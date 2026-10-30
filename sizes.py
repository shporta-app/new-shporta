"""Sizes from the product's own page.

Many shops write the size next to a product's name ("Sasia: 50 ml", "Zgjidhni dozimin: 50 ml", a line under the
price, the description) instead of in it, and their feeds don't carry it. Without the size such a shop can't be
compared, and the site would wrongly say the shop doesn't state it. Each night, before collecting, this reads the
page of every product we couldn't size but that other shops sell in a stated size, once (a page found without a
size is read again after 30 days), with the collector's rules: robots.txt, the shop's crawl delay, and a stop at
the first refusal (403/429/challenge). scrape.py then adds the size to the product's name when it collects it.

    python sizes.py            # every shop
    python sizes.py --limit 20 # at most 20 pages a shop (a test)
"""
import argparse
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from scrape import Blocked, Client, db, page_size

HERE = Path(__file__).parent
SEED = HERE / "seed" / "phia-api.db"


def candidates():
    """Pages of products in a comparison group whose name has no size, from shops we may collect."""
    seed = sqlite3.connect(f"file:{SEED}?mode=ro", uri=True)
    rows = seed.execute("""SELECT DISTINCT p.shop, p.url, p.title FROM products p JOIN items i ON i.id = p.item_id
                           WHERE p.in_compare = 0 AND p.item_id LIKE 'g%' AND i.shops >= 2 AND p.url LIKE 'http%'""").fetchall()
    seed.close()
    con = db()
    ok = {d for d, in con.execute("SELECT domain FROM shops WHERE status = 'ok'")}
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    done = {u for u, in con.execute("SELECT url FROM page_sizes WHERE size IS NOT NULL OR checked > ?", (old,))}
    con.close()
    by_shop = {}
    for shop, url, title in rows:
        if shop in ok and url not in done:
            by_shop.setdefault(shop, []).append((url, title))
    return by_shop


def read_shop(shop, urls, limit):
    host = "https://" + urls[0][0].split("/")[2]
    c, con, n, sized = Client(host), db(), 0, 0
    try:
        for url, title in urls[:limit]:
            if not c.allowed(url):
                continue
            try:
                r = c.get(url)
            except requests.RequestException:
                continue
            size = page_size(r.text, title) if r.status_code == 200 else None
            con.execute("INSERT OR REPLACE INTO page_sizes VALUES (?, ?, ?)",
                        (url, size, datetime.now(timezone.utc).isoformat(timespec="seconds")))
            con.commit()
            n, sized = n + 1, sized + bool(size)
    except Blocked as e:
        print(f"{shop}: stopped, {e}", flush=True)
    con.close()
    print(f"{shop}: {n} pages read, {sized} with a size", flush=True)
    return sized


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100000)
    a = ap.parse_args()
    if not SEED.exists():
        sys.exit("no seed/phia-api.db yet")
    work = candidates()
    print(f"{sum(map(len, work.values()))} pages in {len(work)} shops", flush=True)
    con = db()
    shopify = {d for d, in con.execute("SELECT domain FROM shops WHERE platform = 'shopify'")}
    con.close()
    # shops side by side, each one page at a time at its own pace; Shopify shops one after another (Shopify counts
    # our requests to all its shops together, see refresh.py)
    jobs = [[kv] for kv in work.items() if kv[0] not in shopify] + [[kv for kv in work.items() if kv[0] in shopify]]
    with ThreadPoolExecutor(6) as pool:
        total = sum(pool.map(lambda job: sum(read_shop(d, urls, a.limit) for d, urls in job), jobs))
    print(f"done: {total} sizes found", flush=True)


if __name__ == "__main__":
    main()
