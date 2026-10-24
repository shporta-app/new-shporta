"""Nightly price update: re-collect every shop, rebuild the site's data, publish it.

    python nightly.py --server     # on the shporta.app server (systemd timer, 02:00): collect, rebuild, serve
    python nightly.py --pc-only    # on the PC: only the shops that refuse the server (pc_only.txt), sent to it
    python nightly.py              # the old way, all on the PC, published through GitHub
    python nightly.py --publish-only   # skip scraping; just rebuild and publish the current data

The server (Contabo, since 2026-10-24) keeps the full price history in data/phia.db and serves what it builds;
nothing goes through GitHub. A few shops refuse a data-centre address but answer a home connection
(pc_only.txt): the PC collects those when it's on and copies them to the server's inbox, merged on the next run.

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


PC_ONLY = [l.split()[0] for l in (HERE / "pc_only.txt").read_text(encoding="utf-8").splitlines()
           if l.strip() and not l.startswith("#")]
SERVER = "root@194.146.13.188"
INBOX = Path("/srv/shporta/inbox")
BACKUP = Path("/srv/shporta/backup")


def server_nightly():
    """On the server: collect every shop it may, add what the PC sent, rebuild, restart the site, back up."""
    log("server nightly start")
    merge_inbox()  # yesterday's PC-only shops first, so they're in this build too
    run(sys.executable, "refresh.py", "--skip", *PC_ONLY, check=False)
    merge_inbox()
    run(sys.executable, "match.py")
    run(sys.executable, "build_seed.py")
    run("sudo", "/usr/bin/systemctl", "restart", "shporta")
    log("site restarted with the new data")
    backup()
    indexnow()
    log("server nightly done")


def merge_inbox():
    """Rows the PC collected for the PC-only shops (export_pc_only): products by (shop, external_id), their prices."""
    import sqlite3
    if not INBOX.exists():
        return
    con = sqlite3.connect(HERE / "data" / "phia.db", timeout=120)
    for f in sorted(INBOX.glob("*.db")):
        con.execute("ATTACH ? AS pc", (str(f),))
        con.execute("""INSERT INTO shops SELECT * FROM pc.shops WHERE true
                       ON CONFLICT(domain) DO UPDATE SET status=excluded.status, note=excluded.note,
                         products=excluded.products, last_scraped=excluded.last_scraped, currency=excluded.currency""")
        cols = "shop, external_id, url, title, brand, category_raw, image, gtin, sku, currency, price, regular_price, in_stock, first_seen, last_seen"
        con.execute(f"""INSERT INTO products ({cols}) SELECT {cols} FROM pc.products WHERE true
                        ON CONFLICT(shop, external_id) DO UPDATE SET url=excluded.url, title=excluded.title,
                          brand=excluded.brand, category_raw=excluded.category_raw, image=excluded.image, gtin=excluded.gtin,
                          sku=excluded.sku, currency=excluded.currency, price=excluded.price,
                          regular_price=excluded.regular_price, in_stock=excluded.in_stock,
                          last_seen=max(products.last_seen, excluded.last_seen)""")
        n = con.execute("""INSERT OR REPLACE INTO prices (product_id, day, price, regular_price)
                           SELECT p.id, x.day, x.price, x.regular_price FROM pc.prices x
                           JOIN pc.products q ON q.id = x.product_id
                           JOIN products p ON p.shop = q.shop AND p.external_id = q.external_id""").rowcount
        con.commit()
        con.execute("DETACH pc")
        log(f"merged {f.name}: {n} prices")
        f.unlink()
    con.close()


def backup():
    """A consistent copy of the price history (it can't be collected again), the last 7 days kept on the server;
    the PC also fetches the newest one each night (see export_pc_only)."""
    import gzip
    import shutil
    import sqlite3
    BACKUP.mkdir(exist_ok=True)
    tmp = BACKUP / "phia.tmp"
    src, dst = sqlite3.connect(HERE / "data" / "phia.db", timeout=120), sqlite3.connect(tmp)
    src.backup(dst)
    src.close(), dst.close()
    out = BACKUP / f"phia-{datetime.now():%Y-%m-%d}.db.gz"
    with open(tmp, "rb") as f, gzip.open(out, "wb", 6) as g:
        shutil.copyfileobj(f, g)
    tmp.unlink()
    shutil.copyfile(out, BACKUP / "latest.db.gz")  # what the PC fetches
    for old in sorted(BACKUP.glob("phia-*.db.gz"))[:-7]:
        old.unlink()
    log(f"backup {out.name} ({out.stat().st_size / 1e6:.0f} MB)")


def pc_only_nightly():
    """On the PC: collect only the shops that refuse the server, send them to its inbox, fetch its backup."""
    log("pc-only nightly start")
    stop_local_server()
    run(sys.executable, "refresh.py", "--only-shops", *PC_ONLY, "--no-match", check=False)
    export_pc_only()
    log("pc-only nightly done")


def export_pc_only():
    import sqlite3
    out = HERE / "data" / f"pc-only-{datetime.now():%Y-%m-%d-%H%M}.db"
    out.unlink(missing_ok=True)
    con = sqlite3.connect(HERE / "data" / "phia.db", timeout=120)
    con.execute("ATTACH ? AS x", (str(out),))
    q = ",".join("?" * len(PC_ONLY))
    con.execute(f"CREATE TABLE x.shops AS SELECT * FROM shops WHERE domain IN ({q})", PC_ONLY)
    con.execute(f"CREATE TABLE x.products AS SELECT * FROM products WHERE shop IN ({q}) "
                f"AND last_seen >= datetime('now', '-2 day')", PC_ONLY)
    con.execute("CREATE TABLE x.prices AS SELECT * FROM prices WHERE day >= date('now', '-2 day') "
                "AND product_id IN (SELECT id FROM x.products)")
    con.commit()
    con.execute("DETACH x")
    con.close()
    key = str(Path.home() / ".ssh" / "shporta_vps")
    ssh = ["-i", key, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    # into the inbox under a temporary name, renamed when complete, so the server never merges half a file
    run("scp", *ssh, str(out), f"{SERVER}:{INBOX}/{out.name}.part")
    run("ssh", *ssh, SERVER, f"mv {INBOX}/{out.name}.part {INBOX}/{out.name} && chown shporta:shporta {INBOX}/{out.name}")
    out.unlink()
    log(f"sent {out.name} to the server")
    # and the other way: the newest backup of the full price history, so a copy also lives off the server
    (HERE / "backup").mkdir(exist_ok=True)
    run("scp", *ssh, f"{SERVER}:{BACKUP}/latest.db.gz", str(HERE / "backup" / "phia-latest.db.gz"), check=False)


def main():
    if "--server" in sys.argv:
        return server_nightly()
    if "--pc-only" in sys.argv:
        return pc_only_nightly()
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
