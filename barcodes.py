"""A barcode for every product we compare.

"Skano" finds a product by its barcode, so every compared product needs one, and every new product too. Shops that
publish the barcode in their feed (gtin, Shopify's variant barcode, an EAN kept as the SKU) are read by scrape.py and
build_seed.py. For the rest, each night, before the build:

  1. pages     the product's own page, where many shops print the barcode (JSON-LD gtin13/gtin, "EAN: ..."), read
               with the collector's rules (robots.txt, crawl delay, stop at the first refusal). A shop whose first
               pages carry no barcode is asked again after 30 days, not page by page.
  2. obf       Open Beauty Facts searched by brand and name: a barcode is taken only when its record's brand, name and
               size match our product as strictly as a comparison does (server.match_text, exact name, sure, size).
               Their search allows 10 requests a minute: at most --obf a night, the oldest unchecked first.

Results go to data/phia.db (page_gtins by page, found_gtins by name+size); build_seed.py adds them to the barcode
table. A third source, shoppers who scan an unknown barcode and pick the product, lives in server.py (learned codes).

    python barcodes.py              # both, every shop
    python barcodes.py --obf 0      # pages only
"""
import argparse
import collections
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from match import valid_gtin
from scrape import Blocked, Client, db, jsonld_products, strip_html

HERE = Path(__file__).parent
SEED = HERE / "seed" / "phia-api.db"
UA = "shporta.app/1.0 (+https://shporta.app)"
LABELLED = re.compile(r"\b(?:ean(?:[- ]?13)?|gtin(?:13)?|barcode|barkodi?|kodi i produktit)\b[^0-9<]{0,25}(\d{8,14})\b", re.I)
SCHEMA = """
CREATE TABLE IF NOT EXISTS page_gtins (url TEXT PRIMARY KEY, gtin TEXT, checked TEXT);
CREATE TABLE IF NOT EXISTS barcode_shops (shop TEXT PRIMARY KEY, has INTEGER, checked TEXT);
CREATE TABLE IF NOT EXISTS found_gtins (name_key TEXT, size_val REAL, size_unit TEXT, gtin TEXT, source TEXT, checked TEXT,
                                        PRIMARY KEY (name_key, size_val, size_unit));
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def page_gtin(html):
    """The barcode a product page states for its product: its structured data, else a labelled "EAN: 123..."."""
    for p in list(jsonld_products(html))[:1]:
        offers = p.get("offers") if isinstance(p.get("offers"), dict) else (p.get("offers") or [{}])[0] if isinstance(p.get("offers"), list) else {}
        for k in ("gtin13", "gtin", "gtin12", "gtin14", "gtin8", "ean"):
            g = valid_gtin(p.get(k)) or valid_gtin((offers or {}).get(k))
            if g:
                return g
    m = re.search(r'itemprop="gtin1?[0-9]?"[^>]*content="(\d{8,14})"', html)
    if m and valid_gtin(m.group(1)):
        return valid_gtin(m.group(1))
    found = {valid_gtin(m.group(1)) for m in LABELLED.finditer(strip_html(html[:400000]))} - {None}
    return found.pop() if len(found) == 1 else None


def needed():
    """Compared products without a barcode: their offers (shop, page) and their name key and size."""
    seed = sqlite3.connect(f"file:{SEED}?mode=ro", uri=True)
    have = {r[0] for r in seed.execute("SELECT DISTINCT item FROM barcodes")}
    rows = seed.execute("""SELECT p.item_id, p.shop, p.url, p.name_key, p.size_val, p.size_unit, i.title FROM products p
                           JOIN items i ON i.id = p.item_id WHERE i.shops >= 2 AND p.in_compare = 1""").fetchall()
    seed.close()
    items = collections.defaultdict(lambda: {"offers": [], "key": None})
    for item, shop, url, key, sv, su, title in rows:
        if item in have:
            continue
        it = items[item]
        it["offers"].append((shop, url))
        it["title"] = title
        if key and sv is not None:
            it["key"] = (key, sv, su)
    return items


# ---- 1. the product's own page
def read_shop(shop, urls):
    con = db()
    con.executescript(SCHEMA)
    row = con.execute("SELECT has, checked FROM barcode_shops WHERE shop = ?", (shop,)).fetchone()
    if row and not row[0] and row[1] > ago(30):
        return 0  # its pages carry no barcode; asked again next month
    done = {u for u, in con.execute("SELECT url FROM page_gtins WHERE gtin IS NOT NULL OR checked > ?", (ago(30),))}
    todo = [u for u in urls if u not in done]
    if not todo:
        return 0
    c, n, found, probe = Client("https://" + urllib.parse.urlparse(todo[0]).netloc), 0, 0, not row or not row[0]
    try:
        for url in todo:
            if probe and n >= 3 and not found:  # three pages without a barcode: this shop doesn't print it
                con.execute("INSERT OR REPLACE INTO barcode_shops VALUES (?, 0, ?)", (shop, now()))
                con.commit()
                break
            if not c.allowed(url):
                continue
            try:
                r = c.get(url)
            except requests.RequestException:
                continue
            g = page_gtin(r.text) if r.status_code == 200 else None
            con.execute("INSERT OR REPLACE INTO page_gtins VALUES (?, ?, ?)", (url, g, now()))
            n, found = n + 1, found + bool(g)
            if found == 1 and g:
                con.execute("INSERT OR REPLACE INTO barcode_shops VALUES (?, 1, ?)", (shop, now()))
            con.commit()
    except Blocked as e:
        print(f"{shop}: stopped, {e}", flush=True)
    con.close()
    print(f"{shop}: {n} pages read, {found} barcodes", flush=True)
    return found


def pages(items):
    con = db()
    con.executescript(SCHEMA)
    ok = {d for d, in con.execute("SELECT domain FROM shops WHERE status = 'ok'")}
    platform = dict(con.execute("SELECT domain, platform FROM shops"))
    con.close()
    by_shop = collections.defaultdict(list)
    for it in items.values():
        for shop, url in it["offers"]:
            if shop in ok and url and url.startswith("http"):
                by_shop[shop].append(url)
    shopify = [(s, u) for s, u in by_shop.items() if platform.get(s) == "shopify"]
    other = [(s, u) for s, u in by_shop.items() if platform.get(s) != "shopify"]
    total = 0
    with ThreadPoolExecutor(6) as pool:  # shops side by side, each one page at a time at its own pace
        futs = [pool.submit(read_shop, s, u) for s, u in other]
        futs.append(pool.submit(lambda: sum(read_shop(s, u) for s, u in shopify)))  # Shopify counts us together: one at a time
        total = sum(f.result() for f in futs)
    print(f"pages: {total} barcodes found", flush=True)


# ---- 2. Open Beauty Facts, by name, matched strictly
def obf_search(q):
    url = "https://world.openbeautyfacts.org/cgi/search.pl?" + urllib.parse.urlencode(
        {"search_terms": q, "search_simple": 1, "action": "process", "json": 1, "page_size": 10,
         "fields": "code,brands,product_name,product_name_en,quantity"})
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r:
        return json.loads(r.read().decode("utf-8")).get("products") or []


def obf(items, limit):
    import server  # the strict matcher and the data the site serves
    con = db()
    con.executescript(SCHEMA)
    done = {(k, v, u) for k, v, u in con.execute("SELECT name_key, size_val, size_unit FROM found_gtins WHERE gtin IS NOT NULL OR checked > ?",
                                                 (ago(60),))}
    todo = [(iid, it) for iid, it in items.items() if it["key"] and it["key"] not in done][:limit]
    found = 0
    for iid, it in todo:
        words = [w for w in re.findall(r"[a-z0-9]+", server.fold(it["title"])) if w not in server.SIZE_LABELS][:7]
        gtin = None
        try:
            for rec in obf_search(" ".join(words)):
                g = valid_gtin(rec.get("code"))
                name = rec.get("product_name_en") or rec.get("product_name") or ""
                if not g or not name or not rec.get("quantity"):
                    continue  # without the size on the record we can't say it is this size
                m = server.match_text(f"{name} {rec['quantity']}", (rec.get("brands") or "").split(",")[0], exact_name=True)
                if m["sure"] and not m["size_missing"] and iid in {x["id"] for x in m["items"]}:
                    gtin = g
                    break
        except Exception as e:
            print(f"obf: {type(e).__name__}: {e}", flush=True)
            time.sleep(60)
            continue
        con.execute("INSERT OR REPLACE INTO found_gtins VALUES (?, ?, ?, ?, 'Open Beauty Facts', ?)", (*it["key"], gtin, now()))
        con.commit()
        found += bool(gtin)
        time.sleep(6.5)  # their search: 10 requests a minute
    con.close()
    print(f"obf: {len(todo)} products searched, {found} barcodes found", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--obf", type=int, default=400, help="products searched on Open Beauty Facts tonight")
    ap.add_argument("--no-pages", action="store_true")
    a = ap.parse_args()
    if not SEED.exists():
        sys.exit("no seed/phia-api.db yet")
    items = needed()
    print(f"{len(items)} compared products without a barcode", flush=True)
    if not a.no_pages:
        pages(items)
    if a.obf:
        obf(items, a.obf)


if __name__ == "__main__":
    main()
