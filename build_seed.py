"""Export the compact, read-only DB the website/API serves, as seed/phia-api.db.gz (committed; the server unpacks it).

    python build_seed.py

Tables:
  products  current offers with match key, size and our category
  matches   product -> group (same product in 2+ shops, from match.py)
  items     what the website lists: one row per product sold by 2+ shops (the same product in the same size), with
            lowest/highest price and how many shops sell it. shporta compares identical products; it is not a
            catalogue, so a product only one shop sells is not listed. The only single-shop rows kept are the ones a
            dupe points to (dupes.py), shown only in the dupes section.
            Prices, the cheapest and "save up to" count only offers whose title states the product's size
            (products.in_compare = 1); shops that sell the product without stating the size are listed apart
            (extra_shops) and never count as the cheapest.
  shops     shop directory
The full data/phia.db (price history, raw data) stays on the machine that scrapes.
"""
import collections
import gzip
import hashlib
import os
import re
import shutil
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import dupes
from match import parse, size_label, valid_gtin

HERE = Path(__file__).parent
SRC = HERE / "data" / "phia.db"
OUT = HERE / "seed" / "phia-api.db"
STALE_DAYS = 3  # an offer not seen for this long (relative to the newest data) is not shown

from categories import CATEGORIES, NOT_LISTED, classify, fold  # noqa: E402  (categories.py explains the rules)


def page_key(url):
    """A shop page's address without scheme, www., query or trailing slash: how the extension recognises our pages."""
    u = (url or "").lower().split("#")[0].split("?")[0].rstrip("/")
    for pre in ("https://", "http://"):
        u = u.removeprefix(pre)
    return u.removeprefix("www.") or None


def price_history(src, today):
    """Per product, from the daily `prices` rows: what the product page needs to say whether a price is really low.

    since    first day we saw a price for it
    low30    lowest price in the last 30 days (what EU rules compare a "sale" with)
    prev     the price before the latest change, changed = the day it changed (None: never changed)
    reg_seen 1 if the shop's current "was" price was actually charged at some point in the last 30 days
    """
    start = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
    out, cur, days = {}, None, []

    def flush():
        if not days:
            return
        h = {"since": days[0][0]}
        recent = [p for d, p, _ in days if d >= start] or [days[-1][1]]
        h["low30"] = min(recent)
        for (_, p0, _), (d1, p1, _) in zip(days, days[1:]):
            if p1 != p0:
                h["prev"], h["changed"] = p0, d1
        reg = days[-1][2]
        if reg and reg > days[-1][1]:
            h["reg_seen"] = int(any(p >= reg - 0.5 for d, p, _ in days if d >= start))
        out[cur] = h

    for pid, d, p, reg in src.execute("SELECT product_id, day, price, regular_price FROM prices WHERE price > 0 "
                                      "ORDER BY product_id, day"):
        if pid != cur:
            flush()
            cur, days = pid, []
        days.append((d, p, reg))
    flush()
    return out


HISTORY_DAYS = 120


def item_history(src, rows, today, current):
    """Per compared product, the lowest price among its shops on each day we checked (the last 120 days), stored
    only where it changed: [["2026-10-22", 1390], ["2026-10-25", 1182], ...]. The product page draws it and says
    whether today's price is low for this product. Only shops in the comparison, only the item's own currency."""
    import json
    start = (date.fromisoformat(today) - timedelta(days=HISTORY_DAYS)).isoformat()
    item_of = {r[0]: (r[14], r[8]) for r in rows if r[16]}  # pid -> (item, currency), compared offers only
    by_item_cur = collections.Counter(item_of.values())
    main_cur = {}
    for (item, cur), n in by_item_cur.items():
        if n > main_cur.get(item, (None, 0))[1]:
            main_cur[item] = (cur, n)
    daily = collections.defaultdict(dict)  # item -> day -> lowest price
    for pid, day, price in src.execute("SELECT product_id, day, price FROM prices WHERE price > 0 AND day >= ?", (start,)):
        info = item_of.get(pid)
        if not info or main_cur[info[0]][0] != info[1]:
            continue
        d = daily[info[0]]
        d[day] = min(d.get(day, price), price)
    out = []
    for item, days in daily.items():
        points, last = [], None
        for day in sorted(days):
            p = round(days[day], 2)
            if p != last:
                points.append([day, p])
                last = p
        # today is the price the page shows: the cheapest shop that has it in stock (a sold-out shop's lower price
        # is in the daily rows but can't be bought)
        if item in current:
            points = [x for x in points if x[0] != today] + [[today, round(current[item], 2)]]
            points = [x for i, x in enumerate(points) if i == 0 or x[1] != points[i - 1][1] or x[0] == today]
        out.append((item, json.dumps(points, separators=(",", ":"))))
    return out


def main():
    OUT.parent.mkdir(exist_ok=True)
    OUT.unlink(missing_ok=True)
    src = sqlite3.connect(SRC, timeout=120)
    dst = sqlite3.connect(OUT)
    dst.executescript("""
        CREATE TABLE products (id INTEGER PRIMARY KEY, shop TEXT, title TEXT, brand TEXT, url TEXT, image TEXT,
                               price REAL, regular_price REAL, currency TEXT, in_stock INTEGER,
                               name_key TEXT, size_val REAL, size_unit TEXT, cat TEXT, item_id TEXT, page TEXT,
                               in_compare INTEGER, seen TEXT, since TEXT, low30 REAL, prev_price REAL, changed TEXT,
                               reg_seen INTEGER);
        CREATE TABLE matches (product_id INTEGER PRIMARY KEY, group_id TEXT);
        CREATE TABLE shops (domain TEXT PRIMARY KEY, category TEXT, products INTEGER);
        CREATE TABLE items (id TEXT PRIMARY KEY, title TEXT, image TEXT, cat TEXT, shops INTEGER, in_stock_shops INTEGER,
                            min_price REAL, max_price REAL, currency TEXT, save_pct INTEGER, search TEXT, size_note INTEGER,
                            size TEXT, extra_shops INTEGER);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE VIRTUAL TABLE words USING fts5(name_key, content='products', content_rowid='id', tokenize='unicode61');
    """)
    shop_cat = dict(src.execute("SELECT domain, category FROM shops"))
    group_of = dict(src.execute("SELECT product_id, group_id FROM matches"))
    # rows match.py joined by barcode: the barcode names one size, so a title that doesn't state it takes the group's
    by_barcode = {r[0] for r in src.execute("SELECT product_id FROM matches WHERE via = 'gtin'")} \
        if "via" in {r[1] for r in src.execute("PRAGMA table_info(matches)")} else set()
    alias = dict(src.execute("SELECT key, canonical FROM key_alias"))
    dst.execute("CREATE TABLE key_alias (key TEXT PRIMARY KEY, canonical TEXT)")
    dst.executemany("INSERT INTO key_alias VALUES (?,?)", alias.items())

    # Only prices we have actually seen lately. A product a shop removed, or one a failed/capped run didn't reach,
    # keeps its last price in data/phia.db forever; after STALE_DAYS it is no longer shown or compared.
    latest = src.execute("SELECT MAX(last_seen) FROM products").fetchone()[0]
    cutoff = (datetime.fromisoformat(latest) - timedelta(days=STALE_DAYS)).isoformat(timespec="seconds")
    history = price_history(src, latest[:10])

    rows = []
    for pid, shop, title, brand, url, image, price, reg, cur, stock, craw, seen in src.execute(
            """SELECT id, shop, title, brand, url, image, price, regular_price, currency, in_stock, category_raw, last_seen
               FROM products WHERE price > 0 AND last_seen >= ?""", (cutoff,)):
        key, size = parse(title)
        key = alias.get(key, key)  # match.py rule 5: "Mancera Red Tobacco" -> "Mancera Red Tobacco EDP"
        cat = classify(title, craw, shop_cat.get(shop), shop)
        gid = group_of.get(pid)
        # one listing item per matched product, otherwise per product page (Shopify ?variant= rows share a page)
        item = "g" + gid if gid else "p" + hashlib.md5(f"{shop}|{(url or str(pid)).split('?')[0]}".encode()).hexdigest()[:12]
        h = history.get(pid, {})
        rows.append([pid, shop, title, brand, url, image, price, reg, cur, stock, key,
                     size[0] if size else None, size[1] if size else None, cat, item, page_key(url), 1,
                     seen[:10], h.get("since"), h.get("low30"), h.get("prev"), h.get("changed"), h.get("reg_seen")])

    # items: aggregate offers
    by_item = collections.defaultdict(list)
    for r in rows:
        by_item[r[14]].append(r)
    items = []
    for iid, offs in by_item.items():
        cats = collections.Counter(o[13] for o in offs)
        cat = cats.most_common(1)[0][0]
        for o in offs:  # a matched product gets one category for all its shops
            o[13] = cat
        if iid.startswith("g") and by_barcode:
            stated = {(o[11], o[12]) for o in offs if o[11] is not None}
            if len(stated) == 1:
                for o in offs:
                    if o[11] is None and o[0] in by_barcode:
                        o[11], o[12] = next(iter(stated))
        # a matched product where some shops state the size: only those are compared
        sized = [o for o in offs if o[11] is not None]
        main = sized if iid.startswith("g") and sized else offs
        for o in offs:
            o[16] = 1 if o in main else 0
        extra_shops = len({o[1] for o in offs} - {o[1] for o in main})
        size = None
        # only a size with a unit is shown as "the size we compare": a bare "- 120" may be a shade number
        common = collections.Counter((o[11], o[12]) for o in sized if o[12])
        if common:
            size = size_label(*common.most_common(1)[0][0])
        lek = [o for o in main if o[8] == "ALL"]
        pool = lek or main
        live = [o for o in pool if o[9]] or pool
        prices = [o[6] for o in live]
        lo, hi = min(prices), max(prices)
        shops = {o[1] for o in main}
        live_shops = {o[1] for o in main if o[9]}
        # per shop take its cheapest offer, so a shop's several sizes don't inflate the spread for single-shop items
        per_shop_min = {}
        for o in live:
            per_shop_min[o[1]] = min(per_shop_min.get(o[1], o[6]), o[6])
        # a saving only between shops that have it in stock: "save 60%" on two sold-out offers saves nobody anything
        save = round((max(per_shop_min.values()) - min(per_shop_min.values())) / max(per_shop_min.values()) * 100) \
            if len(per_shop_min) >= 2 and any(o[9] for o in pool) else 0
        title = min((o[2] for o in main), key=lambda t: (abs(len(t) - 45), t))
        # one shop's page selling several sizes ("- Masa: 75 ML", "- Masa: 125 ML"): no single size label, and the
        # name without any one size, else the tile shows one size's name next to another size's label
        if not iid.startswith("g") and len({(o[11], o[12]) for o in sized}) > 1:
            size = None
            names = [o[2] for o in main]
            base = os.path.commonprefix(names)
            if base and base[-1].isalnum() and any(len(t) > len(base) and t[len(base)].isalnum() for t in names):
                base = re.sub(r"\S+$", "", base)  # never cut inside a word or number ("12 pcs" / "1 pcs" -> not "1")
            base = base.rstrip(" -–:*,(/")
            base = re.sub(r"\s*[-–:]\s*(masa|madhesia|madhësia|sasia|vellimi|vëllimi|format|size)$", "", base, flags=re.I)
            if len(base) >= 8:
                title = base
        image = next((o[5] for o in offs if o[5]), None)
        search = fold(" ".join({o[2] for o in offs}) + " " + " ".join(o[3] or "" for o in offs[:3]))
        # 0: every shop states the size, 1: some don't, 2: none do (shown as a warning on the product page)
        size_note = 0 if len(sized) == len(offs) else 2 if not sized else 1
        items.append((iid, title, image, cat, len(shops), len(live_shops), lo, hi, pool[0][8], save, search[:600], size_note,
                      size, extra_shops))

    dst.executemany(f"INSERT INTO products VALUES ({','.join('?' * len(rows[0]))})", rows)
    dst.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", items)
    n_pairs, n_orig, kinds = dupes.build(dst)  # cheaper alternatives to expensive products (dupes.py)
    print(f"dupes: {n_pairs} pairs for {n_orig} products {kinds}")
    # not a catalogue: a product only one shop sells has nothing to compare, so it isn't listed. Kept only where a
    # dupe points to it. Its offers stay in `products` (the extension still recognises that shop's page).
    dst.execute("DELETE FROM items WHERE shops < 2 AND id NOT IN (SELECT item_id FROM dupes UNION SELECT dupe_id FROM dupes)")
    # no groceries: food and drink are not compared (categories.NOT_LISTED)
    dst.execute(f"DELETE FROM items WHERE cat IN ({','.join('?' * len(NOT_LISTED))})", sorted(NOT_LISTED))
    kept = {r[0] for r in dst.execute("SELECT id FROM items")}
    items = [i for i in items if i[0] in kept]
    # barcodes -> products, for "Skano" (scan a barcode in a shop or at home and see every shop's price)
    item_of_pid = {r[0]: r[14] for r in rows}
    codes = set()
    for pid, code in src.execute("SELECT id, gtin FROM products WHERE gtin IS NOT NULL AND gtin != ''"):
        g = valid_gtin(code)
        if g and item_of_pid.get(pid) in kept:
            codes.add((g, item_of_pid[pid]))
    dst.execute("CREATE TABLE barcodes (gtin TEXT, item TEXT, PRIMARY KEY (gtin, item))")
    dst.executemany("INSERT INTO barcodes VALUES (?,?)", codes)
    dst.execute("CREATE TABLE item_history (id TEXT PRIMARY KEY, h TEXT)")
    dst.executemany("INSERT INTO item_history VALUES (?,?)", [h for h in item_history(src, rows, latest[:10], {i[0]: i[6] for i in items}) if h[0] in kept])
    dst.executemany("INSERT INTO matches VALUES (?,?)", group_of.items())
    dst.executemany("INSERT INTO shops VALUES (?,?,?)",
                    src.execute("SELECT domain, category, products FROM shops WHERE status IN ('ok','error')"))
    tracked = src.execute("SELECT MIN(day) FROM prices").fetchone()[0]
    dst.executemany("INSERT INTO meta VALUES (?,?)", [("updated", latest or ""), ("tracked_since", tracked or ""),
                                                      ("categories", repr([(c, label) for c, label, _ in CATEGORIES]))])
    dst.executescript("""
        CREATE INDEX products_key ON products(name_key);
        CREATE INDEX products_item ON products(item_id);
        CREATE INDEX products_page ON products(page);
        CREATE INDEX matches_group ON matches(group_id);
        CREATE INDEX items_cat ON items(cat, shops DESC, save_pct DESC);
        CREATE INDEX items_deals ON items(save_pct DESC) WHERE shops >= 2;
        INSERT INTO words(words) VALUES('rebuild');
        -- any 3+ letters inside a name, found without reading all items (server.search); about 16 MB
        CREATE VIRTUAL TABLE item_search USING fts5(search, content='items', tokenize='trigram', detail='none');
        INSERT INTO item_search(item_search) VALUES('rebuild');
    """)
    dst.commit()
    dst.execute("VACUUM")
    dst.close()
    with open(OUT, "rb") as f, gzip.open(str(OUT) + ".gz", "wb", compresslevel=9) as g:
        shutil.copyfileobj(f, g)
    cats = collections.Counter(i[3] for i in items)
    print(f"{len(rows):,} offers, {len(items):,} items -> {OUT.stat().st_size / 1e6:.0f} MB, "
          f"gzipped {Path(str(OUT) + '.gz').stat().st_size / 1e6:.0f} MB")
    print("items per category:", dict(cats.most_common()))


if __name__ == "__main__":
    main()
