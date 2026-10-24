"""Re-collect every shop that worked last time, then rebuild matches and the report.

    python refresh.py                 # all shops with status ok/error, 4 shops at a time
    python refresh.py --only beauty   # one category
    python refresh.py --workers 2     # fewer at once (each shop still gets one request at a time, at its own pace)

Shops that refused us (robots.txt, 403, a bot challenge) are never retried: they said no. Shops that only said
"429 too many requests" are asked again once per run, one such shop at a time, at their Crawl-delay; the first 429
stops that shop again until the next run (scrape.py never works around it). Run it once a day: each run adds a row per product to the
`prices` table, which is the price history the "is this discount real?" check needs.
"""
import argparse
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).parent
# Shops that are slow at their own Crawl-delay: cap pages per run so one shop can't take the whole night.
MAX_PAGES = {"myoptika.al": 300, "www.lcwaikiki.al": 3000, "sportvision.al": 1500}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="category to refresh")
    ap.add_argument("--workers", type=int, default=4, help="shops collected at the same time")
    ap.add_argument("--skip", nargs="*", default=[], help="shops another job is already collecting")
    a = ap.parse_args()
    con = sqlite3.connect(HERE / "data" / "phia.db", timeout=120)
    sql = "SELECT domain, category, platform FROM shops WHERE status IN ('ok', 'error')"
    shops = con.execute(sql + (" AND category = ?" if a.only else "") + " ORDER BY products DESC", (a.only,) if a.only else ()).fetchall()
    slow = con.execute("SELECT domain, category, platform FROM shops WHERE status = 'blocked' AND note LIKE '429 %'"
                       + (" AND category = ?" if a.only else "") + " ORDER BY products DESC", (a.only,) if a.only else ()).fetchall()
    con.close()

    t0 = time.time()
    print(f"{datetime.now():%Y-%m-%d %H:%M} refreshing {len(shops)} shops, retrying {len(slow)} that said 429", flush=True)
    # Different shops in parallel, each in its own process (biggest first, so the long ones don't finish last).
    # Politeness is per shop and unchanged: one request at a time, robots.txt and Crawl-delay obeyed.
    queue, running = [x for x in shops if x[0] not in a.skip], {}
    retry, retrying = [x for x in slow if x[0] not in a.skip], set()
    while queue or retry or running:
        # the 429 shops: never more than one at a time, so we never come back as a burst
        if retry and not retrying & set(running):
            retrying.add(retry[0][0])
            queue.insert(0, retry.pop(0))
        while queue and len(running) < a.workers + (1 if retrying & {queue[0][0]} else 0):
            domain, category, platform = queue.pop(0)
            # custom adapters are picked up by domain; pass the platform only for the built-in ones
            cmd = [sys.executable, str(HERE / "scrape.py"), domain, "--category", category,
                   "--max-pages", str(MAX_PAGES.get(domain, 3000))]
            if platform in ("woocommerce", "shopify", "jsonld"):
                cmd += ["--platform", platform]
            running[domain] = subprocess.Popen(cmd, cwd=HERE)
        time.sleep(2)
        for domain, proc in list(running.items()):
            if proc.poll() is not None:  # one broken shop must not stop the rest
                if proc.returncode:
                    print(f"{domain}: exited with {proc.returncode}", flush=True)
                del running[domain]
    for step in ("match.py", "make_report.py"):
        subprocess.run([sys.executable, str(HERE / step)], check=False)
    print(f"done in {(time.time() - t0) / 3600:.1f} h", flush=True)


if __name__ == "__main__":
    main()
