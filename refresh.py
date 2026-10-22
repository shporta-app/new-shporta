"""Re-collect every shop that worked last time, then rebuild matches and the report.

    python refresh.py                 # all shops with status ok/error, one at a time
    python refresh.py --only beauty   # one category

Blocked shops are never retried here (they said no). Run it once a day: each run adds a row per product to the
`prices` table, which is the price history the "is this discount real?" check needs.
"""
import argparse
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import scrape

HERE = Path(__file__).parent
# Shops that are slow at their own Crawl-delay: cap pages per run so one shop can't take the whole night.
MAX_PAGES = {"myoptika.al": 300, "www.lcwaikiki.al": 3000, "sportvision.al": 1500}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="category to refresh")
    a = ap.parse_args()
    con = sqlite3.connect(HERE / "data" / "phia.db", timeout=120)
    sql = "SELECT domain, category, platform FROM shops WHERE status IN ('ok', 'error')"
    shops = con.execute(sql + (" AND category = ?" if a.only else "") + " ORDER BY products", (a.only,) if a.only else ()).fetchall()
    con.close()

    t0 = time.time()
    print(f"{datetime.now():%Y-%m-%d %H:%M} refreshing {len(shops)} shops", flush=True)
    for domain, category, platform in shops:
        # custom adapters are picked up by domain; pass the platform only for the built-in ones
        forced = platform if platform in ("woocommerce", "shopify", "jsonld") else None
        try:
            scrape.run(domain, category, forced, MAX_PAGES.get(domain, 3000))
        except Exception as e:  # one broken shop must not stop the rest
            print(f"{domain}: crashed {type(e).__name__}: {e}", flush=True)
    for step in ("match.py", "make_report.py"):
        subprocess.run([sys.executable, str(HERE / step)], check=False)
    print(f"done in {(time.time() - t0) / 3600:.1f} h", flush=True)


if __name__ == "__main__":
    main()
