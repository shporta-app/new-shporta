"""Nightly price update: re-collect every shop, rebuild the site's data, publish it.

    python nightly.py              # what the scheduled task runs (02:00)
    python nightly.py --publish-only   # skip scraping; just rebuild and publish the current data

Publishing keeps the 57 MB data file out of main's history:
  1. the file goes to the `data` branch as a single commit (force-pushed, so that branch never grows)
  2. seed/VERSION on main gets that commit's id; pushing it makes Render redeploy, and Render's build
     downloads exactly that file (see render.yaml). Moving to another host only needs that download step.
Log: logs/nightly-YYYY-MM-DD.log
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
SEED = HERE / "seed" / "phia-api.db.gz"
LOG = HERE / "logs" / f"nightly-{datetime.now():%Y-%m-%d}.log"


def log(msg):
    LOG.parent.mkdir(exist_ok=True)
    line = f"{datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(*cmd, check=True):
    log("$ " + " ".join(cmd))
    with open(LOG, "a", encoding="utf-8") as f:
        r = subprocess.run(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           encoding="utf-8", errors="replace", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        f.write(r.stdout)
    if check and r.returncode:
        raise SystemExit(f"failed ({r.returncode}): {' '.join(cmd)}")
    return r.stdout.strip()


def stop_local_server():
    # a local `python server.py` keeps the seed file open, and Windows then refuses to rewrite it
    run("powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object { $_.CommandLine -match 'server.py' } "
        "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }", check=False)


def publish():
    day = f"{datetime.now():%Y-%m-%d}"
    blob = run("git", "hash-object", "-w", str(SEED))
    # bytes, not text: on Windows text mode would write "\r\n" and the file would be named "phia-api.db.gz\r"
    tree = subprocess.run(["git", "mktree"], cwd=HERE, input=f"100644 blob {blob}\tphia-api.db.gz\n".encode(),
                          capture_output=True, check=True).stdout.decode().strip()
    commit = run("git", "commit-tree", tree, "-m", f"Prices {day}")
    run("git", "push", "--force", "origin", f"{commit}:refs/heads/data")
    (HERE / "seed" / "VERSION").write_text(commit + "\n", encoding="utf-8")
    run("git", "add", "seed/VERSION")
    run("git", "commit", "-m", f"Prices {day}")
    run("git", "push", "origin", "HEAD:main")
    log(f"published data {commit[:10]}; Render redeploys from main")
    indexnow()


def indexnow():
    """Tell Bing, Yandex and the other IndexNow engines which pages have new prices (Bing's index also feeds ChatGPT
    search and Copilot). Google doesn't use IndexNow; it reads the sitemap. A failure here never stops the publish."""
    import json
    import sqlite3
    import urllib.request
    import seo
    try:
        con = sqlite3.connect(f"file:{HERE / 'seed' / 'phia-api.db'}?mode=ro", uri=True)
        ids = [r[0] for r in con.execute("SELECT id FROM items WHERE shops >= 2 ORDER BY shops DESC, save_pct DESC LIMIT 9900")]
        cats = [r[0] for r in con.execute("SELECT DISTINCT cat FROM items")]
        con.close()
        urls = [seo.BASE + p for p in ("/", "/kategorite", "/dupe", "/dyqanet", "/rreth")] +                [f"{seo.BASE}/kategori/{c}" for c in cats] + [f"{seo.BASE}/produkt/{i}" for i in ids]
        body = json.dumps({"host": "shporta.app", "key": seo.INDEXNOW_KEY,
                           "keyLocation": f"{seo.BASE}/{seo.INDEXNOW_KEY}.txt", "urlList": urls}).encode()
        req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body,
                                     headers={"Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=60) as r:
            log(f"IndexNow: {len(urls)} pages sent, answer {r.status}")
    except Exception as e:
        log(f"IndexNow failed (not a problem for the site): {e}")


def main():
    log("nightly start")
    stop_local_server()
    if "--publish-only" not in sys.argv:
        run(sys.executable, "refresh.py", check=False)  # one broken shop must not stop the publish
    run(sys.executable, "match.py")
    run(sys.executable, "build_seed.py")
    publish()
    log("nightly done")


if __name__ == "__main__":
    main()
