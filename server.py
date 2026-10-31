"""Website + API over the compact DB from build_seed.py.

    python server.py            -> http://localhost:8787 (Render sets PORT)

Pages are a small single-page app in web/ (index.html, app.js, styles.css). API:
GET  /api/home                      stats, a featured comparison, biggest price gaps, categories
GET  /api/category/<cat>?sort=&shop=&compared=&page=
GET  /api/item/<id>                 every shop's offer for one product, plus similar products
GET  /api/search?q=&page=
GET  /api/shops
POST /api/lookup  {"title","price","currency","url"}   (browser extension)

Standard library only. All lookups are SQL against a read-only file, so memory stays small (Render free: 512 MB).
"""
import ast
import collections
import gzip
import hashlib
import hmac
import json
import math
import mimetypes
import os
import re
import secrets
import shutil
import sys
import sqlite3
import statistics
import threading
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import alerts
import crowd
import dupes
import feedback
import partners
import push
import seo
import stats
from match import GENERIC, MEN_WORDS, PERFUME_WORDS, SECOND_HAND, WOMEN_WORDS, gender_of, parse, same_size, size_by_price, size_label

HERE = Path(__file__).parent
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("application/wasm", ".wasm")  # the barcode reader (web/vendor), compiled while it downloads
WEB = HERE / "web"
PORT = int(os.environ.get("PORT", 8787))
DB_FILE = Path(os.environ["PHIA_DB"]) if os.environ.get("PHIA_DB") else HERE / "seed" / "phia-api.db"  # PHIA_DB: test a new build locally
PAGE_SIZE = 30


def ensure_db():
    gz = Path(str(DB_FILE) + ".gz")
    if gz.exists() and (not DB_FILE.exists() or DB_FILE.stat().st_mtime < gz.stat().st_mtime):
        with gzip.open(gz, "rb") as g, open(DB_FILE, "wb") as f:
            shutil.copyfileobj(g, f)


ensure_db()
_local = threading.local()


def db():
    # one read-only connection per thread (ThreadingHTTPServer)
    if not hasattr(_local, "con"):
        _local.con = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
        _local.con.row_factory = sqlite3.Row
    return _local.con


def meta(key):
    r = db().execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return r[0] if r else None


CATEGORIES = dict(ast.literal_eval(meta("categories") or "[]"))
COLS = ("id, shop, title, brand, url, image, price, regular_price, currency, in_stock, name_key, size_val, size_unit, item_id,"
        " in_compare, cat")
# price history per offer (build_seed.price_history); an older data file without it still works
HISTORY = ("seen", "since", "low30", "prev_price", "changed", "reg_seen")
if set(HISTORY) <= {r[1] for r in db().execute("PRAGMA table_info(products)")}:
    COLS += ", " + ", ".join(HISTORY)
if "via" in {r[1] for r in db().execute("PRAGMA table_info(products)")}:
    COLS += ", via"  # 'user': a price a shopper shared from a shop we can't collect (crowd.py)
TRACKED_SINCE = meta("tracked_since")
HAS_ITEM_SEARCH = bool(db().execute("SELECT 1 FROM sqlite_master WHERE name = 'item_search'").fetchone())


def page_key(url):
    u = (url or "").lower().split("#")[0].split("?")[0].rstrip("/")
    for pre in ("https://", "http://"):
        u = u.removeprefix(pre)
    return u.removeprefix("www.") or None
ITEM_COLS = "id, title, image, cat, shops, in_stock_shops, min_price, max_price, currency, save_pct, size_note, size, extra_shops"


def fold(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def one_per_shop(offers):
    best = {}
    for o in offers:
        b = best.get(o["shop"])
        if b is None or (o["in_stock"], -o["price"]) > (b["in_stock"], -b["price"]):
            best[o["shop"]] = o
    return sorted(best.values(), key=lambda o: (o["currency"] != "ALL", not o["in_stock"], o["price"]))


def verdict(price, currency, offers):
    """good / normal / high against the in-stock offers in the same currency (the page's own shop excluded)."""
    peers = [o["price"] for o in offers if o["currency"] == currency and o["in_stock"]]
    if not price or len(peers) < 2:
        return None
    lo, med = min(peers), statistics.median(peers)
    label = "good" if price <= lo * 1.03 else "high" if price > med * 1.10 else "normal"
    save = (round(price - lo) if currency == "ALL" else round(price - lo, 2)) if price > lo else 0  # €2.60, not €3
    return {"label": label, "lowest": lo, "median": med, "shops": len(peers), "save": save}


def o_size_num(o):
    v = o.get("_size_val")
    return f"{v:g}" if v else None


def public(o):
    out = {k: o[k] for k in ("id", "shop", "title", "brand", "url", "image", "price", "regular_price", "currency", "in_stock")
           if k in o.keys()} | ({"item": o["item_id"]} if "item_id" in o.keys() else {})
    for k in HISTORY:  # when we last saw this price, and what it was before (product page: "is this low?")
        if k in o.keys() and o[k] is not None:
            out[k] = o[k]
    if "size_val" in o.keys():  # what this shop's own listing says; None = not stated (a bare number may be a shade)
        out["size"] = size_label(o["size_val"], o["size_unit"]) if o["size_unit"] else None
    if "size_val" in o.keys() and o["size_val"]:
        out["_size_val"] = o["size_val"]
    if o["shop"] in SECOND_HAND:
        out["used"] = True  # a used / vintage item: always labelled
    if "via" in o.keys() and o["via"]:
        out["via"] = o["via"]  # "parë nga një përdorues": the site says where the price came from
    return out


def page_num(q):
    """?page= as a sane number: no negative pages, and no number too big for SQLite (that crashed the request)."""
    try:
        return min(max(0, int(q.get("page") or 0)), 10000)
    except ValueError:
        return 0


# what the site lists: the same product sold by 2+ shops. shporta compares, it is not a catalogue of one shop's
# products (the only single-shop items in the data are dupes, shown only in the dupes section)
LISTED = "shops >= 2 AND cat NOT IN ('ushqime')"  # no groceries (categories.NOT_LISTED)


def listed(t):
    """LISTED for a query that joins items under the name t (other tables have a cat column too)."""
    return f"{t}.shops >= 2 AND {t}.cat NOT IN ('ushqime')"


def listed_ids(ids):
    ids = list(ids)
    return {r[0] for r in db().execute(f"SELECT id FROM items WHERE {LISTED} AND id IN ({','.join('?' * len(ids))})", ids)}         if ids else set()


def item_rows(sql, args):
    return [dict(r) for r in db().execute(sql, args)]


# ------------------------------------------------------------------ site endpoints

def home():
    stats = {
        "offers": db().execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "shops": db().execute("SELECT COUNT(*) FROM shops").fetchone()[0],
        "compared": db().execute(f"SELECT COUNT(*) FROM items WHERE {LISTED}").fetchone()[0],
        "updated": meta("updated"),
    }
    # deals: the same product, in stock in 3+ shops, with a real gap (very large gaps are usually a mismatch)
    pool = item_rows(f"""SELECT {ITEM_COLS} FROM items WHERE in_stock_shops >= 3 AND currency = 'ALL' AND cat NOT IN ('tjeter', 'ushqime')
                         AND save_pct BETWEEN 15 AND 65 AND image IS NOT NULL
                         ORDER BY save_pct * min(in_stock_shops, 6) DESC LIMIT 400""", ())
    # at most two per brand (first word of the name) and four per category, so the list isn't one brand
    deals, per_brand, per_cat = [], collections.Counter(), collections.Counter()
    for d in pool:
        brand = fold(d["title"]).split()[0] if d["title"].strip() else ""
        if per_brand[brand] < 2 and per_cat[d["cat"]] < 4:
            per_brand[brand] += 1
            per_cat[d["cat"]] += 1
            deals.append(d)
        if len(deals) == 24:
            break
    featured = item_rows(f"""SELECT {ITEM_COLS} FROM items WHERE in_stock_shops >= 5 AND currency = 'ALL' AND cat NOT IN ('tjeter', 'ushqime')
                             AND save_pct BETWEEN 20 AND 60 AND image IS NOT NULL
                             ORDER BY in_stock_shops DESC, save_pct DESC LIMIT 12""", ())
    for f in featured:
        f["offers"] = offers_for(f["id"])
    cats = {c: n for c, n in db().execute(f"SELECT cat, COUNT(*) FROM items WHERE {LISTED} GROUP BY cat")}
    # each category's picture: the product most shops sell in it, with a photo (a real product, never a stock image)
    pics = {c: img for c, img in db().execute(f"""SELECT cat, image FROM (SELECT cat, image, ROW_NUMBER() OVER
                (PARTITION BY cat ORDER BY in_stock_shops DESC, shops DESC) AS n FROM items
                WHERE {LISTED} AND image IS NOT NULL AND image != '') WHERE n = 1""")}
    top = {k: [r for r in dupe_list({"kind": k})["items"] if r["orig_image"]] for k in ("inspired", "active", "known")}
    picks = [r for trio in zip(top["inspired"][:4], top["known"][:4] or [None] * 4, top["active"][:4]) for r in trio if r][:9]
    return {"stats": stats, "deals": deals, "featured": featured, "impact": impact(), "routine": routine(), "dupes": picks,
            "categories": [{"id": c, "label": label, "count": cats.get(c, 0), "image": pics.get(c)} for c, label in CATEGORIES.items()]
                          + [{"id": "tjeter", "label": "Të tjera", "count": cats.get("tjeter", 0), "image": pics.get("tjeter")}]}


_home = {"at": 0, "data": None}


def cached_home():
    import time
    if not _home["data"] or time.time() - _home["at"] > 600:
        _home["data"], _home["at"] = home(), time.time()
    return _home["data"]


def impact():
    """How much more the dearest shop asks than the cheapest, for the same product in stock in 3+ shops."""
    rows = db().execute("""SELECT min_price, max_price FROM items WHERE in_stock_shops >= 3 AND currency = 'ALL'
                           AND cat NOT IN ('tjeter', 'ushqime') AND save_pct BETWEEN 3 AND 70""").fetchall()
    if not rows:
        return None
    more = sorted((hi / lo - 1) * 100 for lo, hi in rows if lo > 0)
    diff = sorted(hi - lo for lo, hi in rows)
    return {"products": len(rows), "median_more_pct": round(statistics.median(more)),
            "median_diff": round(statistics.median(diff)), "share_over_20": round(sum(m >= 20 for m in more) / len(more) * 100)}


def report():
    """The price report (/raport): what the same product costs across shops, from today's data only. Products in stock
    in 3+ shops, priced in lek; one price per shop (its cheapest listing of that size), so every number is a like-for-like gap."""
    rows = db().execute("""SELECT p.item_id, p.shop, MIN(p.price), i.cat FROM items i CROSS JOIN products p ON p.item_id = i.id
                           WHERE p.in_compare = 1 AND p.in_stock = 1 AND p.currency = 'ALL' AND p.price > 0
                             AND i.in_stock_shops >= 3 AND i.currency = 'ALL' AND i.cat NOT IN ('tjeter', 'ushqime') AND i.id LIKE 'g%'
                           GROUP BY p.item_id, p.shop""").fetchall()
    by_item = collections.defaultdict(dict)
    cat_of = {}
    for iid, shop, price, cat in rows:
        by_item[iid][shop] = price
        cat_of[iid] = cat
    # a gap over 70% is more often two different products than a real price: left out, as on the home page
    items = {i: s for i, s in by_item.items() if len(s) >= 3 and max(s.values()) / min(s.values()) <= 1 / 0.3}
    if len(items) < 50:
        return None
    gap = {i: (max(s.values()) / min(s.values()) - 1) * 100 for i, s in items.items()}
    diff = {i: max(s.values()) - min(s.values()) for i, s in items.items()}
    cats = []
    for c, label in CATEGORIES.items():
        ids = [i for i in items if cat_of[i] == c]
        if len(ids) >= 15:
            cats.append({"id": c, "label": label, "products": len(ids), "median_more_pct": round(statistics.median(gap[i] for i in ids)),
                         "median_diff": round(statistics.median(diff[i] for i in ids))})
    cats.sort(key=lambda c: -c["median_more_pct"])
    # per shop: of the compared products it sells, how often it has the lowest price, and how far above the lowest it is
    shop_stats = collections.defaultdict(lambda: [0, 0, []])
    for s in items.values():
        lo = min(s.values())
        for shop, p in s.items():
            st = shop_stats[shop]
            st[0] += 1
            st[1] += p == lo
            st[2].append((p / lo - 1) * 100)
    shops = sorted(({"shop": sh, "products": n, "cheapest_pct": round(c / n * 100), "median_above_pct": round(statistics.median(a))}
                    for sh, (n, c, a) in shop_stats.items() if n >= 40), key=lambda r: (r["median_above_pct"], -r["cheapest_pct"]))
    top = sorted(items, key=lambda i: -diff[i])[:12]
    biggest = item_rows(f"SELECT {ITEM_COLS} FROM items WHERE id IN ({','.join('?' * len(top))})", top)
    biggest.sort(key=lambda it: -diff[it["id"]])
    more = sorted(gap.values())
    return {"updated": meta("updated"), "tracked_since": TRACKED_SINCE, "products": len(items),
            "shops": len({sh for s in items.values() for sh in s}),
            "median_more_pct": round(statistics.median(more)), "median_diff": round(statistics.median(diff.values())),
            "share_over_20": round(sum(m >= 20 for m in more) / len(more) * 100),
            "share_over_50": round(sum(m >= 50 for m in more) / len(more) * 100),
            "total_diff": round(sum(diff.values())), "categories": cats, "shops_table": shops, "biggest": biggest,
            "routine": routine()}


_report = {"at": 0, "data": None}
REPORTS = Path(os.environ.get("REPORTS_DIR", HERE / "data" / "reports"))


def cached_report():
    import time
    if not _report["data"] or time.time() - _report["at"] > 3600:
        _report["data"], _report["at"] = report(), time.time()
        save_month(_report["data"])
    return _report["data"]


def save_month(r):
    """Keep this month's report: rewritten with each day's data, so a past month holds its last day's numbers.
    The archive (/raport/2026-10) is what lets us say how prices moved, not just how they are today."""
    if not r or not r.get("updated"):
        return
    try:
        REPORTS.mkdir(parents=True, exist_ok=True)
        tmp = REPORTS / f"{r['updated'][:7]}.json.tmp"
        tmp.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        tmp.replace(REPORTS / f"{r['updated'][:7]}.json")
    except OSError as e:
        print(json.dumps({"error": f"report archive: {e}"}), flush=True)


def report_months():
    return sorted((f.stem for f in REPORTS.glob("????-??.json")), reverse=True) if REPORTS.exists() else []


def report_with_history(month=None):
    """Today's report (no month) or an archived month, plus the list of months and the month before it to compare."""
    r = cached_report() if not month else month_report(month)
    if not r:
        return None
    months = report_months()
    this = (r.get("updated") or "")[:7]
    before = [m for m in months if m < this]
    prev = month_report(before[0]) if before else None
    keep = ("updated", "products", "median_more_pct", "median_diff", "share_over_20", "share_over_50")
    return {**r, "month": month, "months": months,
            "previous": {"month": before[0], **{k: prev.get(k) for k in keep}} if prev else None}


def month_report(month):
    if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
        return None
    f = REPORTS / f"{month}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


# A basic skincare routine, priced with real matched products: one per step, the one sold in most shops.
ROUTINE = [("Pastrues", r"cleans|pastrues|foam|cleansing"), ("Tonik", r"toner|tonik"),
           ("Serum", r"serum|essence|ampoule"), ("Krem hidratues", r"moistur|hidrat|face cream|krem fytyr|\bcream\b|\bkrem\b"),
           ("Mbrojtje nga dielli", r"\bspf|sunscreen|sun cream|kunder diellit")]


def routine():
    pool = item_rows(f"""SELECT {ITEM_COLS} FROM items WHERE cat = 'lekure' AND in_stock_shops >= 4 AND currency = 'ALL'
                         AND save_pct BETWEEN 10 AND 65 AND image IS NOT NULL ORDER BY in_stock_shops DESC, save_pct DESC""", ())
    steps, used = [], set()
    for label, rx in ROUTINE:
        r = re.compile(rx)
        pick = next((it for it in pool if it["id"] not in used and r.search(fold(it["title"]))
                     and not re.search(r"\beye\b|sysh|mask|maske|patch|\bbody\b|trup|\bhand|duar|\blip|buze|\bhair|flok|\bfoot|kemb", fold(it["title"]))), None)
        if pick:
            used.add(pick["id"])
            steps.append({"step": label, **pick})
    if len(steps) < 3:
        return None
    lo, hi = sum(s["min_price"] for s in steps), sum(s["max_price"] for s in steps)
    return {"steps": steps, "cheapest": lo, "dearest": hi, "difference": hi - lo}


def offers_for(item_id):
    """The price comparison: one offer per shop, only listings that state the product's size (build_seed.py)."""
    offs = [dict(r) for r in db().execute(f"SELECT {COLS} FROM products WHERE item_id = ? AND in_compare = 1", (item_id,))]
    if item_id.startswith("g"):
        return [public(o) for o in one_per_shop(offs)]
    # a single shop's page: list its sizes/colours
    return [public(o) for o in sorted(offs, key=lambda o: (not o["in_stock"], o["price"]))]


SORTS = {"compared": "shops DESC, save_pct DESC", "cheap": "min_price ASC", "dear": "min_price DESC", "gap": "save_pct DESC"}


def category(cat, q):
    if cat not in CATEGORIES and cat != "tjeter" or cat == "ushqime":  # no groceries
        return None
    where, args = ["cat = ?", LISTED], [cat]
    if q.get("shop"):
        where.append("id IN (SELECT item_id FROM products WHERE shop = ?)")
        args.append(q["shop"])
    order = SORTS.get(q.get("sort"), SORTS["compared"])
    page = page_num(q)
    sql = " AND ".join(where)
    total = db().execute(f"SELECT COUNT(*) FROM items WHERE {sql}", args).fetchone()[0]
    items = item_rows(f"SELECT {ITEM_COLS} FROM items WHERE {sql} ORDER BY {order} LIMIT ? OFFSET ?",
                      args + [PAGE_SIZE, page * PAGE_SIZE])
    shops = [r[0] for r in db().execute(
        f"""SELECT p.shop FROM products p JOIN items i ON i.id = p.item_id WHERE i.cat = ? AND {listed('i')} AND p.in_compare = 1
            GROUP BY p.shop ORDER BY COUNT(*) DESC LIMIT 40""", (cat,))]
    return {"id": cat, "label": CATEGORIES.get(cat, "Të tjera"), "total": total, "page": page,
            "page_size": PAGE_SIZE, "items": items, "shops": shops}


DUPE_COLS = """x.kind, x.reason, x.save_pct, x.orig_price, x.dupe_price, x.orig_size, x.dupe_size, x.dupe_product,
               o.id AS orig_id, o.title AS orig_title, o.image AS orig_image, o.shops AS orig_shops,
               d.id AS dupe_id, d.title AS dupe_title, d.image AS dupe_image, d.shops AS dupe_shops"""
DUPE_FROM = "FROM dupes x JOIN items o ON o.id = x.item_id JOIN items d ON d.id = x.dupe_id"


def dupes_of(item_id, limit=3):
    """The closest dupes first (dupes.py keeps at most three per product): the strongest evidence, then the saving."""
    return item_rows(f"""SELECT {DUPE_COLS} {DUPE_FROM} WHERE x.item_id = ?
                         ORDER BY CASE x.kind WHEN 'inspired' THEN 0 WHEN 'known' THEN 1 ELSE 2 END, x.save_pct DESC LIMIT ?""",
                     (item_id, limit))


def originals_of(item_id):
    return item_rows(f"SELECT {DUPE_COLS} {DUPE_FROM} WHERE x.dupe_id = ? ORDER BY o.shops DESC LIMIT 3", (item_id,))


def dupe_list(q):
    """One row per expensive product: its best dupe. Newest perfume and skincare finds first by price."""
    kind = q.get("kind") if q.get("kind") in ("inspired", "active", "known") else None
    page = page_num(q)
    # one row per expensive product; for a well-known makeup pair, one row per pair (not one per Dior shade)
    where = ("WHERE x.save_pct = (SELECT MAX(save_pct) FROM dupes y WHERE y.item_id = x.item_id)"
             " AND (x.kind != 'known' OR x.item_id = (SELECT z.item_id FROM dupes z WHERE z.kind = 'known'"
             " AND z.reason = x.reason ORDER BY z.orig_price DESC, z.item_id LIMIT 1))" + (" AND x.kind = ?" if kind else ""))
    args = [kind] if kind else []
    total = db().execute(f"SELECT COUNT(DISTINCT x.item_id) {DUPE_FROM} {where}", args).fetchone()[0]
    rows = item_rows(f"SELECT {DUPE_COLS} {DUPE_FROM} {where} GROUP BY x.item_id ORDER BY x.orig_price DESC LIMIT ? OFFSET ?",
                     args + [PAGE_SIZE, page * PAGE_SIZE])
    for r in rows:
        r["count"] = db().execute("SELECT COUNT(*) FROM dupes WHERE item_id = ?", (r["orig_id"],)).fetchone()[0]
    return {"total": total, "page": page, "page_size": PAGE_SIZE, "kind": kind, "items": rows}


def item(item_id):
    r = db().execute(f"SELECT {ITEM_COLS} FROM items WHERE id = ?", (item_id,)).fetchone()
    if not r or r["cat"] == "ushqime":  # no groceries
        return None
    it = dict(r)
    it["offers"] = offers_for(item_id)
    # shops selling it without stating the size: listed apart, never the cheapest, never in "save up to"
    main_shops = {o["shop"] for o in it["offers"]}
    it["unconfirmed"] = [public(o) for o in one_per_shop([dict(x) for x in db().execute(
        f"SELECT {COLS} FROM products WHERE item_id = ? AND in_compare = 0", (item_id,))]) if o["shop"] not in main_shops]
    first = db().execute("SELECT name_key FROM products WHERE item_id = ? LIMIT 1", (item_id,)).fetchone()
    cur = it["currency"]
    sim = similar(first[0] if first else "", it["min_price"], cur, limit=20)
    # the same product name in other sizes (or other single listings): their own list, never "similar"
    same = [r[0] for r in db().execute("SELECT DISTINCT item_id FROM products WHERE name_key = ? AND item_id != ? LIMIT 12",
                                       (first[0], item_id))] if first and len(first[0].split()) >= 2 else []
    it["other_sizes"] = item_rows(f"SELECT {ITEM_COLS} FROM items WHERE {LISTED} AND id IN ({','.join('?' * len(same))})",
                                  same) if same else []
    seen, out = {item_id} | set(same), []
    for o in sim:
        if o["item_id"] not in seen:
            seen.add(o["item_id"])
            out.append(o["item_id"])
    it["similar"] = item_rows(f"SELECT {ITEM_COLS} FROM items WHERE {LISTED} AND id IN ({','.join('?' * len(out))})",
                              out)[:8] if out else []
    it["category_label"] = CATEGORIES.get(it["cat"], "Të tjera")
    it["tracked_since"] = TRACKED_SINCE  # the first day of price history: claims about "lowest" only reach back to it
    it["used"] = any(o["shop"] in SECOND_HAND for o in it["offers"])
    # a price far below the other shops for the very same product can be a fake or another size: say so, never hide it
    live = sorted(o["price"] for o in it["offers"] if o["in_stock"] and o["currency"] == it["currency"])
    if len(live) >= 3:
        mid = live[len(live) // 2]
        for o in it["offers"]:
            if o["in_stock"] and o["currency"] == it["currency"] and o["price"] < mid * 0.65:
                o["risk"] = True
    for o in it["offers"]:  # a shop that writes only "55" in a 55 g comparison: same number, show it with the unit
        if not o.get("size") and it["size"] and o_size_num(o) == it["size"].split()[0]:
            o["size"] = it["size"]
    it["dupes"] = dupes_of(item_id)
    it["dupe_of"] = originals_of(item_id)
    it["alerts"] = alerts.enabled()  # the product page shows the email form only when emails can go out
    it["history"] = item_history(item_id)
    return it


# the same thing in Albanian and English, or spelled two ways: a search for one also finds the others
SYNONYMS = [
    {"atlete", "sneakers", "sneaker"}, {"kepuce", "shoes", "shoe"}, {"cizme", "boots"}, {"sandale", "sandals"},
    {"canta", "cante", "bag", "bags"}, {"ore", "ora", "watch"}, {"syze", "sunglasses", "glasses"},
    {"parfum", "parfume", "perfume", "edp", "edt"}, {"krem", "cream", "creme"}, {"shampo", "shampoo"},
    {"fustan", "dress"}, {"xhakete", "jacket"}, {"bluze", "blouse", "shirt"}, {"pantallona", "pants", "trousers"},
    {"telefon", "celular", "phone", "smartphone"}, {"kufje", "headphones", "earbuds", "headset"},
    {"laptop", "notebook"}, {"televizor", "tv"}, {"karikues", "charger"}, {"lodra", "loder", "toy", "toys"},
    {"liber", "libra", "book", "books"}, {"qen", "dog"}, {"mace", "cat"}, {"femije", "kids", "baby", "bebe"},
    {"buzekuq", "lipstick"}, {"rimel", "mascara"}, {"pudra", "powder"}, {"vathe", "earrings"}, {"unaze", "ring"},
    {"varese", "necklace"}, {"byzylyk", "bracelet"}, {"frigorifer", "fridge", "refrigerator"},
    {"rrobalarese", "lavatrice"}, {"divan", "sofa"}, {"karrige", "chair"},
    {"moisturising", "moisturizing", "moisturiser", "moisturizer", "hidratues"}, {"colour", "color"},
    {"cleanser", "pastrues"}, {"sunscreen", "spf", "dielli", "diellit"}, {"toner", "tonik"},
    {"duar", "duarsh", "hand", "hands"}, {"fytyre", "fytyres", "face", "facial"}, {"trup", "trupi", "body"},
    {"flok", "floke", "flokesh", "hair"}, {"buze", "buzesh", "lip", "lips"}, {"vaj", "oil"}, {"sapun", "soap"},
    {"maske", "mask"}, {"thonj", "nail", "nails"},
]
SYN_OF = {w: g for g in SYNONYMS for w in g}
_vocab = None


def vocabulary():
    """Words of our product names that several products use: what a mistyped search word is checked against."""
    global _vocab
    if _vocab is None:
        n = collections.Counter()
        for (t,) in db().execute(f"SELECT search FROM items WHERE {LISTED}"):
            n.update(set(re.findall(r"[a-z0-9]{4,}", t)))
        _vocab = {w: c for w, c in n.items() if c >= 3}
    return _vocab


threading.Thread(target=lambda: (vocabulary(), brand_words()), daemon=True).start()  # ready before the first search


def search_items(words, limit):
    """Items whose names contain every word (or one of its synonyms), best matches first: the most query words
    found as whole words in the name, then sold by more shops, then in stock, then cheaper."""
    where, args, long_args, long_parts = [], [], [], []
    for w in words:
        alts = sorted(SYN_OF.get(w, {w}) | {w})
        where.append("(" + " OR ".join("search LIKE ?" for _ in alts) + ")")
        args += [f"%{a}%" for a in alts]
        if HAS_ITEM_SEARCH and all(len(a) >= 3 for a in alts):
            # the trigram index answers one LIKE at a time quickly, an OR of them slowly: one lookup per synonym,
            # UNION for a word's synonyms, INTERSECT across words. The LIKEs on items stay the rule.
            long_parts.append(" UNION ".join("SELECT rowid FROM item_search WHERE search LIKE ?" for _ in alts))
            long_args += [f"%{a}%" for a in alts]
    sql_where = " AND ".join(where + [LISTED])
    if long_parts:
        sql_where = f"rowid IN ({' INTERSECT '.join(long_parts)}) AND {sql_where}"
        args = long_args + args
    total = db().execute(f"SELECT COUNT(*) FROM items WHERE {sql_where}", args).fetchone()[0]
    cand = item_rows(f"""SELECT {ITEM_COLS}, search FROM items WHERE {sql_where}
                         ORDER BY shops DESC, in_stock_shops DESC, min_price LIMIT 800""", args)

    def score(it):
        title = fold(it["title"])
        whole = sum(1 for w in words if any(re.search(rf"\b{re.escape(a)}\b", title) for a in SYN_OF.get(w, {w}) | {w}))
        starts = 1 if title.startswith(words[0]) else 0
        return (-whole, -starts, -min(it["shops"], 5), -bool(it["in_stock_shops"]), it["min_price"])
    cand.sort(key=score)
    for it in cand:
        it.pop("search", None)
    return total, cand[:limit]


def sound(w):
    """How a word sounds, roughly: people write brand names the way they say them in Albanian ("serave" for CeraVe,
    "rosh pozai" for Roche-Posay, "savage" for Sauvage). Same consonants in the same order = sounds alike."""
    w = re.sub(r"ch|sh|zh|xh|ç", "s", w).replace("ph", "f")
    w = w.translate(str.maketrans("ckqzxwyj", "sssssvii"))
    return re.sub(r"(.)\1+", r"\1", w[0] + re.sub(r"[aeiou]", "", w[1:]))


_sounds = None


def correct(words, force=False):
    """A mistyped word ("cerave" typed "cereve" or "serave", "parfume" typed "parfumm") -> the closest word in our
    names. force: also a word some odd name contains ("savage"), when the search found nothing at all."""
    import difflib
    global _sounds
    vocab, out, changed = vocabulary(), [], False
    if _sounds is None:
        _sounds = collections.defaultdict(list)
        for v in vocab:
            _sounds[sound(v)].append(v)
    for w in words:
        table = "item_search" if HAS_ITEM_SEARCH else "items"
        known = w in vocab or db().execute(f"SELECT 1 FROM {table} WHERE search LIKE ? LIMIT 1", (f"%{w}%",)).fetchone()
        if len(w) < 4 or w in SYN_OF or (known and not force) or vocab.get(w, 0) >= 10:
            out.append(w)
            continue
        key = sound(w)
        near = set(difflib.get_close_matches(w, [v for v in vocab if abs(len(v) - len(w)) <= 2 and sound(v)[0] == key[0]], n=6, cutoff=0.75))
        near |= {v for v in _sounds.get(key, ()) if abs(len(v) - len(w)) <= 3}
        # among close spellings, the word most of our products use ("nivae" -> "nivea", not "niva")
        best = max(near, key=lambda v: (difflib.SequenceMatcher(None, w, v).ratio() >= 0.8, sound(v) == key, vocab[v]), default=None)
        if best and known and vocab[best] <= 2 * vocab.get(w, 0):
            best = None  # the word is used as typed: keep it
        out.append(best or w)
        changed |= bool(best)
    return out if changed else None


def search(q, page=0):
    words = [w for w in re.findall(r"[^\W_]+", fold(q)) if len(w) > 1][:6]  # no "_": it's a LIKE wildcard
    if not words:
        return {"q": q, "total": 0, "items": []}
    total, items = search_items(words, (page + 1) * PAGE_SIZE)
    fixed = None
    if total < 3:  # nothing or almost nothing: a typo? use the spelling that finds more
        for f in (correct(words), total == 0 and correct(words, force=True)):
            if not f or f == fixed:
                continue
            t2, i2 = search_items(f, (page + 1) * PAGE_SIZE)
            if t2 > total:
                total, items, fixed = t2, i2, f
    return {"q": q, "total": total, "page": page, "page_size": PAGE_SIZE, "items": items[page * PAGE_SIZE:],
            "corrected": " ".join(fixed) if fixed and total else None}


def suggest(q):
    """As someone types: up to 7 products with a photo and the price range, the best matches first."""
    words = [w for w in re.findall(r"[^\W_]+", fold(q)) if len(w) > 1][:6]
    if not words or len("".join(words)) < 3:
        return {"items": []}
    total, items = search_items(words, 7)
    if total < 3 and (fixed := correct(words)):
        t2, i2 = search_items(fixed, 7)
        if t2 > total:
            total, items = t2, i2
    return {"total": total, "items": items}


# words on a label that describe rather than name a product ("for dry to very dry skin")
LABEL_WORDS = {"for", "with", "dry", "oily", "normal", "all", "types", "very", "sensitive", "combination", "skin", "use",
               "daily", "day", "and", "the", "new"}
_obf, _obf_lock = {}, threading.Lock()


def obf_product(gtin):
    """A barcode's brand, name and size from Open Beauty Facts (open data, ODbL), for products whose barcode no shop
    of ours publishes. Remembered for a day, misses too. Only the barcode is sent."""
    import time
    import urllib.request
    code = gtin[1:] if len(gtin) == 14 and gtin[0] == "0" else gtin
    with _obf_lock:
        hit = _obf.get(code)
    if hit and time.time() - hit[0] < 86400:
        return hit[1]
    out = None
    try:
        req = urllib.request.Request(
            f"https://world.openbeautyfacts.org/api/v2/product/{code}.json?fields=brands,product_name,product_name_en,product_name_fr,quantity",
            headers={"User-Agent": "shporta.app/1.0 (+https://shporta.app)"})
        with urllib.request.urlopen(req, timeout=4) as r:
            d = json.loads(r.read().decode("utf-8"))
        if d.get("status") == 1:
            out = d.get("product") or None
    except Exception:
        return None  # not remembered: the next scan asks again
    with _obf_lock:
        if len(_obf) > 5000:
            _obf.clear()
        _obf[code] = (time.time(), out)
    return out


def name_match(brand, name, quantity=""):
    """A product's brand and name (from its barcode's record, or read off the package) -> our products whose names
    have every one of those words, in the same size when the size is known. Only a specific name counts: the brand
    plus at least two words of the product's own name (or all of them), never a looser search."""
    from match import SIZE_RE, size_of
    vocab, brands = vocabulary(), brand_words()
    bwords = [w for w in re.findall(r"[a-z0-9]+", fold(brand or "")) if w in vocab and w in brands]
    if not bwords:
        return None
    known, unknown = [], 0
    for w in re.findall(r"[a-z0-9]+", fold(name or "")):
        if w in bwords or w in LABEL_WORDS or (len(w) < 3 and not w.isdigit()) or SIZE_RE.fullmatch(w):
            continue
        if w in vocab and w not in known:
            known.append(w)
        elif w not in vocab:
            unknown += 1
    if not (len(known) >= 2 or (known and not unknown)):
        return None
    items = closest(bwords + known, f"{brand} {name}")
    if not items:
        return None
    m = SIZE_RE.search(fold(quantity or ""))
    if m:
        want = size_of(m)
        sized = [it for it in items if (n := SIZE_RE.search(fold(it.get("size") or ""))) and size_of(n) == want]
        if sized:
            return {"items": sized, "size_ok": True, "words": bwords + known}
    return {"items": items, "size_ok": False, "words": bwords + known}


def closest(words, text="", limit=6):
    """The products named exactly by these words: every word in the name, and nothing in the name that isn't on the
    package too (text: everything read on it), apart from numbers ("CeraVe Moisturising Cream" in its sizes, never
    "CeraVe Intensive Moisturizing Cream", a refill or a set). Empty when no product is that close: then we don't
    know which one it is, and say so."""
    want = set(canonical_key(parse(" ".join(words))[0]).split())
    seen = want | set(canonical_key(parse(text)[0]).split()) | set(re.findall(r"[a-z0-9%]+", fold(text)))
    total, items = search_items(words, 60)
    if not total:
        return []
    near = []
    for it in items:
        have = set(canonical_key(parse(it["title"])[0]).split())
        if want <= have and all(w in seen or re.fullmatch(r"[\d.,%]+", w) for w in have - want):
            near.append(it)
    return near[:limit] if 0 < len(near) <= limit * 2 else []


def barcode(code):
    """"Skano": a barcode read by the phone's camera -> the products that carry it, most shops first. When no shop of
    ours publishes this barcode, its name and size from Open Beauty Facts, matched exactly by name (name_match)."""
    from match import valid_gtin
    g = valid_gtin(code)
    if not g:
        return {"code": code, "valid": False, "items": []}
    try:
        ids = [r[0] for r in db().execute("SELECT item FROM barcodes WHERE gtin = ?", (g,))]
    except sqlite3.OperationalError:  # a data file from before barcodes
        ids = []
    items = item_rows(f"""SELECT {ITEM_COLS} FROM items WHERE {LISTED} AND id IN ({','.join('?' * len(ids))})
                          ORDER BY shops DESC, in_stock_shops DESC""",
                      ids) if ids else []
    out = {"code": g.lstrip("0"), "valid": True, "items": items, "how": "barcode"}
    if items:
        return out
    # a barcode shoppers taught us: two different people scanned it and picked the same product
    taught = learned(g)
    if taught:
        items = item_rows(f"SELECT {ITEM_COLS} FROM items WHERE {LISTED} AND id IN ({','.join('?' * len(taught))})", taught)
        if items:
            return out | {"items": items, "how": "learned"}
    rec = obf_product(g)
    source = "Open Beauty Facts"
    if not rec:
        rec, source = upc_product(g), "UPCitemdb"
    if rec:
        brands = [b.strip() for b in (rec.get("brands") or "").split(",") if b.strip()]
        names = [x for x in (rec.get("product_name_en"), rec.get("product_name"), rec.get("product_name_fr")) if x]
        # "L'Oréal, Maybelline": the brand printed on the product is the one our shops use; the owner comes first in the record
        ours = brand_words()
        brand = next((b for b in brands if any(w in ours for w in re.findall(r"[a-z0-9]+", fold(b)))), brands[0] if brands else "")
        out["name"] = " ".join(x for x in (brand, names[0] if names else "", rec.get("quantity")) if x)
        out["source"] = source
        m = match_text(" ".join(names[:1] + [rec.get("quantity") or ""]), " ".join(brands), exact_name=True)
        out.update(how="name", sure=m["sure"], items=m["items"], maybe=m["maybe"], size_missing=m["size_missing"],
                   size_ok=not m["size_missing"], offers=m.get("offers", []), words=m["words"])
    return out


LEARN_DB = Path(os.environ.get("LEARN_DB", HERE / "data" / "learned.db"))
_learn_lock = threading.Lock()


def _learn_con():
    LEARN_DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(LEARN_DB, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS learned (gtin TEXT, item TEXT, visitor TEXT, day TEXT, PRIMARY KEY (gtin, item, visitor))")
    return c


def learn(code, item, ip, ua):
    """A shopper scanned a barcode we didn't know and picked this product from the list: one vote for code -> item.
    Kept: the barcode, the product, the same daily visitor code as stats.py (no address, no cookie)."""
    from match import valid_gtin
    from datetime import date
    g = valid_gtin(code)
    if not g or not re.fullmatch(r"[gp][0-9a-f]{12}", item or ""):
        return False
    visitor = hashlib.sha256(f"{stats._daily_salt(date.today().isoformat())}|{ip}|{ua}".encode()).hexdigest()[:16]
    with _learn_lock, _learn_con() as c:
        c.execute("INSERT OR IGNORE INTO learned VALUES (?, ?, ?, ?)", (g, item, visitor, date.today().isoformat()))
    return True


def learned(g):
    """Products two or more different shoppers picked for this barcode (and nobody picked anything else as often)."""
    if not LEARN_DB.exists():
        return []
    with _learn_con() as c:
        votes = c.execute("SELECT item, COUNT(DISTINCT visitor) n FROM learned WHERE gtin = ? GROUP BY item ORDER BY n DESC", (g,)).fetchall()
    if not votes or votes[0][1] < 2 or (len(votes) > 1 and votes[1][1] >= votes[0][1]):
        return []
    return [votes[0][0]]


_upc, _upc_lock = {}, threading.Lock()


def upc_product(gtin):
    """A barcode's brand and name from UPCitemdb's free lookup, when Open Beauty Facts doesn't know it. Remembered
    for a day. Only the barcode is sent."""
    import time
    import urllib.request
    code = gtin.lstrip("0") if len(gtin.lstrip("0")) >= 12 else gtin[-13:]
    with _upc_lock:
        hit = _upc.get(code)
    if hit and time.time() - hit[0] < 86400:
        return hit[1]
    out = None
    try:
        req = urllib.request.Request(f"https://api.upcitemdb.com/prod/trial/lookup?upc={code}",
                                     headers={"User-Agent": "shporta.app/1.0 (+https://shporta.app)", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=4) as r:
            d = json.loads(r.read().decode("utf-8"))
        it = (d.get("items") or [None])[0]
        if it and it.get("title"):
            out = {"brands": it.get("brand") or "", "product_name": it["title"], "quantity": it.get("size") or ""}
    except Exception:
        return None
    with _upc_lock:
        if len(_upc) > 5000:
            _upc.clear()
        _upc[code] = (time.time(), out)
    return out


_df = None


def title_df():
    """How many listed products use each word in their name: a rare word ("mucin", "effaclar") says more."""
    global _df
    if _df is None:
        n = collections.Counter()
        for (t,) in db().execute(f"SELECT title FROM items WHERE {LISTED}"):
            n.update(set(re.findall(r"[a-z0-9]+", fold(t))))
        _df = n
    return _df


def name_words(title):
    """The words that name a product, without its size or packaging numbers."""
    from match import SIZE_RE
    t = SIZE_RE.sub(" ", fold(title))
    return [w for w in re.findall(r"[a-z0-9]+", t) if not w.isdigit() and w not in LABEL_WORDS and w not in SIZE_LABELS
            and len(w) >= 2]


# the words shops put before a size ("Sasia: 50ml", "vellimi: 236ml", "Format: 100 ml"): not part of the name
SIZE_LABELS = {"sasia", "sasi", "vellimi", "volumi", "format", "formati", "madhesia", "pesha", "size", "volume", "ml", "gr", "oz",
               "fl", "pcs", "cope", "x"}


def match_text(text, brand_hint="", exact_name=False):
    """What is written on a package (the phone's OCR, or a barcode record's brand + name + size) -> our product.
    Every candidate is scored: the rare words of its name that are on the package count for it, the words of its
    name that are not there count against it. sure: the brand and most of the name match, clearly better than the
    next product. size: the size printed on the package picks among the sizes; a size we don't have is said so,
    never shown as the same product. maybe: the closest products when we're not sure, labelled as such."""
    import difflib
    from match import SIZE_RE, size_of
    df, brands = title_df(), brand_words()
    N = max(1, len(df))
    idf = lambda w: math.log(N / (1 + df.get(w, 0)))
    raw = re.findall(r"[a-z0-9]+", fold(f"{brand_hint} {text}"))
    # OCR splits a word ("Cera Ve", "La Roche Posay" fine, "Neutro gena"): two neighbours that make a known word are one
    raw += [a + b for a, b in zip(raw, raw[1:]) if a + b in df and len(a + b) >= 5 and (a not in df or b not in df or a + b in brands)]
    # and misreads letters: l/1 for i, 0 for o, rn for m
    fix = lambda w: w if w in df else next((v for v in (w.replace("l", "i"), w.replace("1", "i"), w.replace("0", "o"),
                                                         w.replace("rn", "m")) if v in df), w)
    raw = [fix(w) for w in raw]
    seen = set()
    for w in raw:
        if len(w) < 3 or w.isdigit():
            seen.add(w)
            continue
        if w in df:
            seen.add(w)
        else:  # OCR misreads a letter or two ("CeraVc", "Niacinamlde"): the closest word our names use
            close = difflib.get_close_matches(w, [v for v in df if v[:1] == w[:1] and abs(len(v) - len(w)) <= 2], 1, 0.8)
            seen.add(close[0] if close else w)
    # words printed on most packages ("made in Korea", "for all skin types") are never the brand
    common = LABEL_WORDS | {"made", "for", "in", "by", "of", "korea", "france", "italy", "germany", "usa", "new", "paris",
                            "tested", "dermatologically", "free", "natural", "organic", "professional", "care"}
    found_brands = [w for w in dict.fromkeys(raw) if w in brands and w not in common] or [w for w in seen if w in brands and w not in common]
    # candidates: every product of the brand(s) on the package; with no brand, the products with its rarest words
    keys = found_brands[:3] or sorted((w for w in seen if w in df and len(w) >= 4), key=idf, reverse=True)[:3]
    cand = {}
    for k in keys:
        for it in search_items([k], 800)[1]:
            cand[it["id"]] = it
    if not cand:
        return {"items": [], "sure": False, "maybe": [], "offers": offers_like(raw, found_brands, idf),
                "words": [w for w in raw if w in df][:6] or [w for w in raw if len(w) >= 3][:6], "brand": None}
    scored = []
    for it in cand.values():
        words = set(name_words(it["title"]))
        if not words:
            continue
        hit = sum(idf(w) for w in words if w in seen)
        miss = sum(idf(w) for w in words if w not in seen)
        scored.append((hit - 0.8 * miss, hit / (hit + miss or 1), it, words))
    scored.sort(key=lambda s: (-s[0], -s[2]["shops"]))
    if not scored:
        return {"items": [], "sure": False, "maybe": [], "words": [], "brand": None}
    # the same product in its sizes is one answer: group by the name without the size
    # (also when two shops spell it differently: "Moisturizing" and "Moisturising" Cream is one product)
    import difflib as _dl
    unit = {"ml", "g", "gr", "kg", "l", "oz", "sasia", "vellimi", "format"}
    def alike(a, b):
        a, b = a - unit, b - unit
        if a == b:
            return True
        left = [w for w in a if w not in b]
        right = [w for w in b if w not in a]
        return len(left) == len(right) <= 2 and all(_dl.SequenceMatcher(None, x, y).ratio() >= 0.8 for x, y in zip(sorted(left), sorted(right)))
    best = scored[0]
    group = [s for s in scored if alike(s[3], best[3])]
    rest = [s for s in scored if s not in group]
    brand_ok = not found_brands or any(b in best[3] for b in found_brands)
    named = [w for w in best[3] if w in seen and w not in brands]
    margin = best[0] - (rest[0][0] if rest else -99)
    # a refill, a set, a travel size or a tester is another product: the package and the name must agree on it
    variant = {"refill", "recharge", "ricarica", "set", "kit", "mini", "travel", "tester", "sample", "duo", "trio", "coffret", "gift"}
    same_variant = (variant & seen) == (variant & best[3])
    # the words that tell products of a line apart are rare ("Double", "Purifying", "Intensive"): every rare word of
    # our name must be on the package; and a barcode's record names the product exactly, so its rare words must be
    # in our name too ("Toleriane Purifying Foaming Cleanser" is not "Toleriane Foaming Double Cleanser")
    rare = lambda w: idf(w) >= 3.0 and w not in brands and len(w) >= 3
    ours_on_pack = all(w in seen for w in best[3] if rare(w))
    theirs_in_ours = not exact_name or all(w in best[3] for w in set(name_words(text)) if w in df and rare(w) and w not in common)
    sure = (brand_ok and best[1] >= 0.7 and len(named) >= 2 and margin >= 1.5 and same_variant
            and ours_on_pack and theirs_in_ours)
    items = [s[2] for s in group][:6]
    sizes = {size_of(m) for m in SIZE_RE.finditer(fold(text))}
    # a cream is 340 g on the jar and "340 ml" at a shop: the same number in g and ml is the same size here
    # and "3.38 fl.oz" (US packages print both) is 100 ml
    def same(a, b):
        if a == b or (a[0] == b[0] and {a[1], b[1]} <= {"g", "ml"}):
            return True
        ml = lambda z: z[0] * 29.57 if z[1] == "oz" else z[0] if z[1] in ("ml", "g") else None
        x, y = ml(a), ml(b)
        return bool(x and y and "oz" in (a[1], b[1]) and abs(x - y) <= 0.04 * max(x, y))
    size_missing = False
    if sizes:
        sized = [it for it in items if (m := SIZE_RE.search(fold(it.get("size") or it["title"])))
                 and any(same(size_of(m), z) for z in sizes)]
        if sized:
            items = sized
        elif sure:
            size_missing = True  # the right product, but not in the size on the package: shown as other sizes
    maybe = [] if sure else [s[2] for s in scored[:12] if s[1] >= 0.4][:6]
    offers = [] if sure or maybe else offers_like(raw, found_brands, idf)
    return {"items": items if sure else [], "sure": sure, "size_missing": size_missing, "maybe": maybe, "offers": offers,
            "words": [w for w in dict.fromkeys(raw) if w in df and w in best[3]][:6] or [w for w in raw if w in df][:6],
            "brand": found_brands[0] if found_brands else None,
            "printed_size": size_label(*sorted(sizes, key=lambda z: z[1] == "oz")[0]) if sizes else None}


def offers_like(raw, brands, idf):
    """A product we don't compare (no two shops sell it under one name), but that shops we follow do sell: their
    listings whose name has the brand and most words of what was read, one per shop, in stock first."""
    common = LABEL_WORDS | SIZE_LABELS | {"made", "for", "in", "by", "of", "new", "the", "and", "with"}
    words = [w for w in dict.fromkeys(raw) if len(w) >= 3 and not w.isdigit() and w not in common]
    if not words:
        return []
    # a brand on the package AND a word of its name: precise even for a brand with thousands of listings
    named = sorted((w for w in words if w not in brands), key=lambda w: -len(w))[:6]
    if not named:
        return []
    where = "(" + " OR ".join("name_key LIKE ?" for _ in named) + ")"
    args = [f"%{w}%" for w in named]
    if brands:
        where = "(" + " OR ".join("name_key LIKE ?" for _ in brands[:3]) + ") AND " + where
        args = [f"%{b}%" for b in brands[:3]] + args
    rows = {r["id"]: dict(r) for r in db().execute(f"SELECT {COLS} FROM products WHERE {where} LIMIT 5000", args)}
    said = set(words)
    best = []
    for o in rows.values():
        have = set(name_words(o["title"]))
        named = have - set(brands)
        if len(named & said) < 2:
            continue  # the brand alone, or one word, is not this product
        # a powder is not a foundation: when both say what kind of product it is, they must agree
        kinds = {"powder", "foundation", "concealer", "primer", "mascara", "lipstick", "gloss", "liner", "eyeliner", "blush",
                 "bronzer", "highlighter", "spray", "cream", "serum", "toner", "cleanser", "mask", "shampoo", "conditioner",
                 "oil", "gel", "lotion", "balm", "palette", "pencil", "cushion", "fluid", "parfum", "toilette", "deodorant"}
        if have & kinds and said & kinds and not have & said & kinds:
            continue
        hit = len(have & said) / len(have)
        if hit >= 0.6:
            best.append((hit, o))
    # the shade or number printed on the package ("120 Classic Ivory") first
    nums = {n for n in raw if n.isdigit()}
    best.sort(key=lambda x: (-bool(nums & set(re.findall(r"\d+", fold(x[1]["title"])))), -x[0], -x[1]["in_stock"], x[1]["price"]))
    seen_shop, out = set(), []
    for hit, o in best:
        if (o["shop"], fold(o["title"])) in seen_shop:
            continue
        seen_shop.add((o["shop"], fold(o["title"])))
        out.append(public(o))
    return out[:8]


def identify(text):
    """"Skano" with a photo of the label: the phone reads the text (OCR), match_text finds the product."""
    return match_text(text)


def identify_old(text):
    """"Skano" with a photo of the label: the phone reads the text (OCR, on the phone), we keep the words our product
    names use, rarest first (a brand or line name says more than "cream"), and search with fewer words until
    something is found. OCR misreads letters, so each word also gets the typo correction."""
    from match import DESCRIPTIONS, NOISE, STOP
    vocab, skip = vocabulary(), DESCRIPTIONS | NOISE | STOP | LABEL_WORDS
    words = []
    for w in re.findall(r"[a-z0-9]{3,}", fold(text)):
        if w in skip:
            continue  # label words that describe ("for dry skin") rather than name the product
        w = w if w in vocab else (correct([w]) or [w])[0]
        if w in vocab and w not in words:
            words.append(w)
    brands = brand_words()
    # the brand first, then the words in the order the label prints them: the product's name comes right after the brand,
    # in big letters; the small print under it ("for dry to very dry skin") comes later
    words.sort(key=lambda w: w not in brands)
    # words one at a time, brand and rarest first; a word that leaves nothing ("strength", "high" on the label but
    # not in any product name) is skipped, so marketing text on a label can't push the search off the product
    chosen, total = [], 0
    for w in words[:12]:
        t, _ = search_items(chosen + [w], 1)
        if t:
            chosen, total = chosen + [w], t
        if len(chosen) == 5 or total == 1:
            break
    # sure: the brand and two words of the product's name, and few enough products that it is one of them
    # (usually the same product in its sizes). Anything less is a guess, and the page says so instead of listing it.
    brand = next((w for w in chosen if w in brands), None)
    if chosen:
        total, _ = search_items(chosen, 1)
        items = closest(chosen, text) if brand and len([w for w in chosen if w not in brands]) >= 2 else []
        from match import SIZE_RE, size_of
        sizes = {size_of(m) for m in SIZE_RE.finditer(fold(text))}
        sized = [it for it in items if (n := SIZE_RE.search(fold(it.get("size") or ""))) and size_of(n) in sizes]
        items = sized or items  # the size printed on the package picks the one in the hand
        return {"words": chosen, "total": total, "items": items, "sure": bool(items), "brand": brand}
    return {"words": words[:4], "total": 0, "items": [], "sure": False, "brand": None}


def basket(ids):
    """"Shporta ime": for each product, every shop that has it in stock at its lowest price (one per shop, the
    product's own currency, exact comparison only). app.js works out the cheapest way to buy them all."""
    ids = [i for i in dict.fromkeys(ids.split(",")) if re.fullmatch(r"[\w-]{1,20}", i)][:40]
    out = []
    for iid in ids:
        rows = item_rows(f"SELECT {ITEM_COLS} FROM items WHERE id = ?", (iid,))
        if not rows:
            out.append({"id": iid, "missing": True})
            continue
        it = rows[0]
        offs = [o for o in offers_for(iid) if o["in_stock"] and o["currency"] == it["currency"]]
        best = {}
        for o in offs:
            if o["shop"] not in best or o["price"] < best[o["shop"]]["price"]:
                best[o["shop"]] = {"shop": o["shop"], "price": o["price"], "id": o["id"]}
        out.append({**it, "offers": sorted(best.values(), key=lambda o: o["price"])})
    return {"items": out}


def alert_item(item_id):
    if not re.fullmatch(r"[\w-]{1,20}", item_id or ""):
        return None
    rows = item_rows(f"SELECT {ITEM_COLS} FROM items WHERE id = ?", (item_id,))
    return rows[0] if rows else None


def alert_page(path, q):
    """The pages the links in our emails open: confirm, or stop alerts (one click, no login)."""
    t = q.get("t", "")
    if path == "/njoftim/konfirmo":
        r = alerts.confirm(t)
        h, p = (("Njoftimi u konfirmua", f"Do të të shkruajmë kur {r['title']} të kushtojë më pak. Çdo email ka një link për t'i ndaluar njoftimet.")
                if r else ("Ky link nuk vlen më", "Mund ta kërkosh përsëri njoftimin te faqja e produktit."))
    elif q.get("all") == "1":
        r = alerts.stop_all(t)
        h, p = ("Njoftimet u ndalën", f"Nuk do të marrësh më asnjë email nga shporta. Adresa jote u fshi.") if r else                ("Njoftimet janë ndalur tashmë", "Kjo adresë nuk ka asnjë njoftim aktiv.")
    else:
        r = alerts.stop(t)
        h, p = ("Njoftimi u ndal", f"Nuk do të të shkruajmë më për {r['title']}.") if r else                ("Njoftimi është ndalur tashmë", "Ky produkt nuk ka më njoftim aktiv.")
    return seo.page_html(f"{h} | shporta", p, path, f'<div class="wrap page-head"><h1>{seo.e(h)}</h1><p>{seo.e(p)}</p>'
                         f'<p><a class="btn" href="/">Kthehu te shporta</a></p></div>', robots="noindex,nofollow")


def item_history(item_id):
    try:
        r = db().execute("SELECT h FROM item_history WHERE id = ?", (item_id,)).fetchone()
    except sqlite3.OperationalError:  # a data file from before the history
        return []
    return json.loads(r[0]) if r else []


def items_by_ids(ids):
    """Today's prices for the products a visitor watches (app.js: the list lives only in their browser)."""
    ids = [i for i in ids.split(",") if re.fullmatch(r"[\w-]{1,20}", i)][:100]
    if not ids:
        return {"items": []}
    return {"items": item_rows(f"SELECT {ITEM_COLS} FROM items WHERE id IN ({','.join('?' * len(ids))})", ids)}


def shops():
    rows = db().execute("""SELECT s.domain, s.category, COUNT(p.id) n
                           FROM shops s LEFT JOIN products p ON p.shop = s.domain GROUP BY s.domain ORDER BY n DESC""")
    return [{"domain": d, "category": c, "products": n} for d, c, n in rows]


# ------------------------------------------------------------------ extension endpoint

def has_gendered_line(words):
    """True when these name words also exist with "pour homme" / "for women"… added: a separate perfume line."""
    extra = MEN_WORDS | WOMEN_WORDS
    q = " AND ".join(f'"{w}"' for w in words) + " AND (" + " OR ".join(f'"{w}"' for w in sorted(extra)) + ")"
    try:
        rows = db().execute("SELECT name_key FROM products WHERE id IN (SELECT rowid FROM words WHERE words MATCH ? LIMIT 200)",
                            (q,)).fetchall()
    except sqlite3.OperationalError:
        return False
    return any(set(r[0].split()) - extra - {"pour", "for"} == set(words) for r in rows)


def canonical_key(key):
    """match.py rule 5: a name with one word left out ("Mancera Red Tobacco") under its full name."""
    try:
        r = db().execute("SELECT canonical FROM key_alias WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:  # a seed built before key_alias existed
        return key
    return r[0] if r else key


def lookup(title, price=None, currency="ALL", url="", gtin=""):
    """What the extension shows for the product page a shopper has open, in three separate parts:
       exact    the same product in the same size at other shops (the only thing the price verdict uses)
       similar  only when there's no exact match: other products with most of the same words, never "the same"
       dupes    a different product that does the same job for less
    query.size_label is the size compared; query.size_assumed is true when the page itself doesn't state it."""
    key, size = parse(title or "")
    key = canonical_key(key)
    page_host = urlparse(url).netloc.lower().removeprefix("www.") if url else ""
    q = {"title": title, "price": price, "currency": currency, "size_label": size_label(*size) if size and size[1] else None,
         "size_assumed": False}

    def answer(offers, item_id=None):
        offers = [o for o in one_per_shop(offers) if o["shop"].removeprefix("www.") != page_host  # never the shop you're on
                  and o["cat"] != "ushqime"]  # no groceries
        item_id = item_id or next((o["item_id"] for o in offers if o["item_id"].startswith("g")), None)
        exact = [public(o) for o in offers[:20]]
        for o in exact:  # a shop that writes only "55" in a 55 g comparison: same number, show it with the unit
            if not o.get("size") and q.get("size_label") and o_size_num(o) == q["size_label"].split()[0]:
                o["size"] = q["size_label"]
        out = {"query": q, "exact": exact, "verdict": None if q.get("no_verdict") else verdict(q["price"], currency, offers),
               "item": item_id}
        v = out["verdict"]
        if v and q["price"] and v["shops"] >= 2 and q["price"] < v["median"] * 0.65:
            out["risk"] = True  # far below every other shop for the same product: a fake, a used one or another size?
        if item_id:  # shops selling it without stating the size: only counted, the product page lists them
            row = db().execute("SELECT extra_shops FROM items WHERE id = ?", (item_id,)).fetchone()
            out["unconfirmed"] = (row[0] or 0) if row else 0
        # the same product name at shops not in the comparison: they don't state the size, or sell another size.
        # Listed with each shop's own size, never compared on price, and never shown as "similar".
        taken = {o["shop"] for o in offers} | {page_host}
        same = [o for o in one_per_shop([dict(r) for r in db().execute(
                    f"SELECT {COLS} FROM products WHERE name_key = ? AND currency = ?", (key, currency))])
                if o["shop"].removeprefix("www.") not in taken and o["shop"] not in taken and o["shop"] not in SECOND_HAND]
        out["same_name"] = [public(o) for o in same[:12]] if len(key.split()) >= 2 else []
        if not offers:  # only products we compare (2+ shops): never one shop's own product as an advert
            sim = [o for o in similar(key, price, currency, limit=30)
                   if o["shop"].removeprefix("www.") != page_host and o["name_key"] != key]
            ok = listed_ids({o["item_id"] for o in sim})
            out["similar"] = [public(o) for o in sim if o["item_id"] in ok][:8]
        out["dupes"] = dupes_of(item_id) if item_id else page_dupes(title, price, currency, offers)
        return out

    def compared(item_id):
        return [dict(r) for r in db().execute(f"SELECT {COLS} FROM products WHERE item_id = ? AND in_compare = 1", (item_id,))]

    # 1. a page we collected: we know exactly which product it is, whatever name the page shows
    #    (several sizes on one page: the page's price says which one is selected)
    mine = [dict(r) for r in db().execute(f"SELECT {COLS} FROM products WHERE page = ?", (page_key(url),))] if url else []
    if mine:
        exact_price = [o for o in mine if price and abs(o["price"] - price) < 1]
        matched = [o for o in mine if o["item_id"].startswith("g")]
        if len(exact_price) == 1 and (exact_price[0]["item_id"].startswith("g") or len(mine) == 1):
            here = exact_price[0]  # the page's price names the size the shopper picked
        elif matched:
            # several sizes and the page only says "from 880 L": compare the size most shops sell, and say which
            here = max(matched, key=lambda o: db().execute(
                "SELECT COUNT(DISTINCT shop) FROM products WHERE item_id = ? AND in_compare = 1", (o["item_id"],)).fetchone()[0])
            if not price:
                q["price"] = here["price"]  # the page shows no price: ours, from the shop's own listing
            elif len(mine) > 1 and abs(price - here["price"]) > max(1, here["price"] * 0.03):
                # the page's price fits none of its sizes as we last saw them: which size it is isn't certain,
                # so list the shops but give no verdict. (One size only: the page's price is the truth, so the
                # verdict below is on what the shopper sees now, never on our older price.)
                q["no_verdict"] = True
        else:
            here = min(mine, key=lambda o: abs(o["price"] - price) if price else 0)
        if here["item_id"].startswith("g"):
            it = db().execute("SELECT size FROM items WHERE id = ?", (here["item_id"],)).fetchone()
            q["size_label"] = it["size"] if it else None
            q["size_assumed"] = not here["in_compare"]  # this shop doesn't write the size; we matched it by price
            q["known_page"] = True
            return answer(compared(here["item_id"]), here["item_id"])
        key, size = here["name_key"] or key, (here["size_val"], here["size_unit"]) if here["size_val"] else size
        if size and size[1] and not q["size_label"]:
            q["size_label"] = size_label(*size)  # the page's own listing states it

    # 2. the barcode the shop's page publishes (schema.org gtin13 / gtin): exact, whatever the name says
    from match import valid_gtin
    g = valid_gtin(gtin)
    if g:
        try:
            ids = [r[0] for r in db().execute("SELECT item FROM barcodes WHERE gtin = ? ORDER BY item", (g,))]
        except sqlite3.OperationalError:
            ids = []
        grouped = [i for i in ids if i.startswith("g")]
        if len(grouped) == 1:
            it = db().execute("SELECT size FROM items WHERE id = ?", (grouped[0],)).fetchone()
            q["size_label"], q["by_barcode"] = (it["size"] if it else q["size_label"]), True
            return answer(compared(grouped[0]), grouped[0])

    # 3. otherwise by name, with match.py's rules: a specific name, and the same size
    words = key.split()
    if not (len(words) >= 3 and any(w not in GENERIC for w in words)):
        return answer([])
    cands = [dict(r) for r in db().execute(f"SELECT {COLS} FROM products WHERE name_key = ?", (key,))
             if r["shop"] not in SECOND_HAND]  # a used item is never "the same product"
    # who it's for, as match.py: a "(Men)" title never matches a "(Women)" one, and where the name also exists
    # as a separate men's/women's line ("Light Blue" / "Light Blue Pour Homme") the label must be the same
    mine_g = gender_of(title or "")
    if has_gendered_line(words):
        cands = [o for o in cands if gender_of(o["title"]) == mine_g]
    elif mine_g:
        cands = [o for o in cands if gender_of(o["title"]) in (None, mine_g)]
    sized =[o for o in cands if o["size_val"] is not None]
    if size is not None:
        return answer([o for o in sized if same_size(size, (o["size_val"], o["size_unit"]))])
    # the page doesn't state a size: compare only when the size is certain from the other shops
    options = []
    for o in sorted(sized, key=lambda o: o["size_unit"] is None):  # "55 g" rather than a bare "55"
        if not any(same_size((o["size_val"], o["size_unit"]), x) for x in options):
            options.append((o["size_val"], o["size_unit"]))
    medians = {x: statistics.median(o["price"] for o in sized if same_size(x, (o["size_val"], o["size_unit"])))
               for x in options}
    pick = None
    if len(options) == 1 and len({o["shop"] for o in sized}) >= 2 and price and             medians[options[0]] / 1.5 <= price <= medians[options[0]] * 1.5:
        pick = options[0]  # the product comes in one size and the price fits it
    elif len(options) > 1 and price:
        pick = size_by_price(price, medians)  # several sizes: only when the price clearly says which one
    if pick:
        q["size_label"], q["size_assumed"] = size_label(*pick) if pick[1] else None, True
        return answer([o for o in sized if same_size(pick, (o["size_val"], o["size_unit"]))])
    # no size anywhere (or the price doesn't say which): never "the same product" with a verdict. The same name
    # still shows, in its own block with each shop's size ("dyqani nuk e shkruan madhësinë"), never compared.
    return answer([])


def page_dupes(title, price, currency, offers):
    """Dupes for the product on the shopper's page: the known ones when we have the product, otherwise skincare
    with the same active at the same strength in the same kind of product, 30%+ cheaper (same rule as dupes.py)."""
    if offers and offers[0].get("item_id"):
        rows = dupes_of(offers[0]["item_id"])
        if rows:
            return rows
    if not price or currency != "ALL":
        return []
    # perfume: the page names an original that shops sell "inspired by" versions of ("Creed Aventus")
    words = set(re.findall(r"[a-z0-9]+", dupes.fold(title)))
    for reason, orig_id in db().execute("SELECT DISTINCT reason, item_id FROM dupes WHERE kind = 'inspired'"):
        name = [w for w in re.findall(r"[a-z0-9]+", dupes.fold(reason.split(" nga ", 1)[-1])) if w not in dupes.GENDER]
        if len(name) >= 2 and all(w in words for w in name):
            rows = [r for r in dupes_of(orig_id) if r["dupe_price"] <= price * 0.7]
            if rows:
                return rows
    m = dupes.ACTIVE_RE.search(dupes.fold(title))
    acts, kind = dupes.actives(title), dupes.kind_of(title)
    if not (m and kind):
        return []
    out = []
    for it in item_rows(f"""SELECT {ITEM_COLS} FROM items WHERE cat = 'lekure' AND currency = 'ALL' AND in_stock_shops >= 1
                            AND search LIKE ? AND search LIKE ? AND min_price <= ? ORDER BY min_price LIMIT 300""",
                        (f"%{m.group(1)}%", f"%{m.group(2)}%", price * 0.7)):
        if dupes.actives(it["title"]) == acts and dupes.kind_of(it["title"]) == kind \
                and not dupes.same_brand(it["title"], title):
            out.append({"kind": "active", "reason": dupes.reason(acts), "dupe_id": it["id"],
                        "dupe_title": it["title"], "dupe_image": it["image"], "dupe_price": it["min_price"],
                        "save_pct": round((1 - it["min_price"] / price) * 100)})
        if len(out) == 3:
            break
    return out


# Same thing in English / Albanian (accents folded, as in match.parse). Shops mix both languages.
SYNONYMS = [
    {"jeans", "xhinse", "xhins", "denim"}, {"coat", "pallto"}, {"jacket", "xhakete", "xhup"},
    {"dress", "fustan"}, {"skirt", "fund"}, {"shirt", "kemishe"}, {"tshirt", "bluze", "bluza", "maice"},
    {"sweater", "pulover", "triko", "knit"}, {"trousers", "pants", "pantallona"}, {"shorts", "pantallona", "shkurtra"},
    {"shoes", "kepuce"}, {"sneakers", "atlete", "trainers"}, {"boots", "cizme", "kepuce"}, {"sandals", "sandale"},
    {"bag", "cante", "canta"}, {"wallet", "portofol"}, {"belt", "rrip"}, {"scarf", "shall"}, {"hat", "kapele"},
    {"watch", "ore", "ora"}, {"sunglasses", "syze"}, {"ring", "unaze"}, {"necklace", "varese", "gjerdan"},
    {"earrings", "vathe"}, {"bracelet", "byzylyk"}, {"long", "gjate"}, {"short", "shkurter"}, {"wool", "lesh"},
    {"leather", "lekure"}, {"cotton", "pambuk"}, {"women", "femra", "grua"}, {"men", "meshkuj", "burra"},
    {"kids", "femije"}, {"cream", "krem", "creme"}, {"perfume", "parfum", "parfume"}, {"shampoo", "shampo"},
    {"cleanser", "pastrues"}, {"sunscreen", "spf", "dielli"}, {"lipstick", "buzekuq"}, {"mascara", "maskara", "rimel"},
    {"high", "larte"}, {"waist", "shtrat", "bel", "beli", "rise"}, {"wide", "gjere"}, {"slim", "ngushte", "skinny"},
    {"straight", "drejte"}, {"oversize", "oversized"}, {"blazer", "xhakete"},
]
ALTS = collections.defaultdict(set)
for _g in SYNONYMS:
    for _w in _g:
        ALTS[_w] |= _g
# product-type words: a similar product must be the same kind of thing (jeans with jeans, never with a dress)
TYPE_WORDS = {w for g in SYNONYMS[:24] for w in g} | {"blazer", "kostum", "hoodie", "top", "cardigan", "kardigan"}
# the cut of a garment: wide-leg jeans are only similar to wide-leg jeans, never to skinny ones
CUTS = [{"wide", "gjere", "palazzo"}, {"straight", "drejte"}, {"slim", "ngushte", "skinny"}, {"flare", "bootcut"},
        {"barrel"}, {"baggy"}, {"mom"}, {"cargo"}, {"oversize", "oversized"}, {"cropped"}, {"regular"}]
CUT_OF = {w: frozenset(g) for g in CUTS for w in g}


# a colour ("Jeans … - E zezë") shouldn't decide what counts as a similar product
COLOURS = set("""zeze zi bardhe kuqe blu gri roze jeshile kafe bezhe portokalli verdhe vjollce bojeqielli
black white red blue grey gray pink green brown beige orange yellow purple navy ecru khaki""".split())


def known_word(w):
    try:
        return db().execute("SELECT 1 FROM words WHERE words MATCH ? LIMIT 1", (f'"{w}"',)).fetchone() is not None
    except sqlite3.Error:
        return False


BEAUTY_CATS = {"parfume", "lekure", "grim", "floke", "trup"}
_brand_words = None


def brand_words():
    """Words of the shops' brand fields that 2+ shops use ("dolce", "gabbana", "medicube"), not product words."""
    global _brand_words
    if _brand_words is None:
        shops = collections.defaultdict(set)
        for brand, shop in db().execute("SELECT DISTINCT brand, shop FROM products WHERE brand IS NOT NULL AND brand != ''"):
            for w in re.findall(r"[a-z0-9]+", fold(brand)):
                shops[w].add(shop)
        _brand_words = {w for w, s in shops.items() if len(s) >= 2 and len(w) >= 3 and not w.isdigit()
                        and w not in GENERIC and w not in TYPE_WORDS and w not in PERFUME_WORDS and w not in COLOURS}
    return _brand_words


def similar(key, price, currency, limit=8):
    """Products covering most of the title's words (in either language), cheaper ones first.
    Words no other shop uses (a brand's line names like Zara's "TRF", "Z1975") are ignored.
    Beauty and perfume suggestions keep the brand (another brand's "Light and Refreshing EDT" isn't similar
    to Light Blue); clothing may be any brand. A colour word counts only in a perfume's name ("Light Blue")."""
    words = set(key.split())
    perfume = bool(words & (PERFUME_WORDS | {"edp", "edt"}))
    q = [w for w in words if re.fullmatch(r"[a-z0-9]+", w) and (perfume or w not in COLOURS)]
    brand = words & brand_words()
    q = [w for w in q if any(known_word(a) for a in (ALTS.get(w) or {w}))]
    types = [w for w in q if w in TYPE_WORDS]
    cuts = {CUT_OF[w] for w in set(key.split()) if w in CUT_OF}
    if len(q) < 2 and not types:  # one word is enough only when it names the kind of product ("blazer")
        return []
    groups = [sorted(ALTS.get(w) or {w}) for w in q]
    match = " OR ".join("(" + " OR ".join(f'"{a}"' for a in g) + ")" for g in groups)
    cand = [dict(r) for r in db().execute(
        f"""SELECT {COLS} FROM products WHERE id IN (SELECT rowid FROM words WHERE words MATCH ? ORDER BY rank LIMIT 3000)
            AND in_stock = 1 AND currency = ?""", (match, currency)) if r["shop"] not in SECOND_HAND]  # never used items
    need = max(min(2, len(q)), round(len(q) * 0.6))
    scored = []
    for o in cand:
        kw = set((o["name_key"] or "").split())
        hits = sum(1 for g in groups if kw & set(g))
        same_type = not types or any(kw & (ALTS.get(t) or {t}) for t in types)
        same_cut = not cuts or (all(kw & c for c in cuts) and not any(kw & c for c in set(CUT_OF.values()) - cuts))
        same_brand = not brand or o["cat"] not in BEAUTY_CATS or bool(kw & brand)
        if hits >= need and same_type and same_cut and same_brand:
            scored.append((hits / len(q), -len(kw), o))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    seen, per_shop, res = set(), collections.Counter(), []
    for *_, o in scored:
        name = o["title"].split(" - ")[0].lower()  # variants of one product collapse into one entry
        if (o["shop"], name) in seen or per_shop[o["shop"]] >= 2:
            continue
        seen.add((o["shop"], name))
        per_shop[o["shop"]] += 1
        res.append(o)
        if len(res) >= 20:
            break
    # cheaper than the page first; with no price (a shared link) simply cheapest first
    res.sort(key=lambda o: (o["price"] >= price, o["price"]) if price else (False, o["price"]))
    return res[:limit]


# ------------------------------------------------------------------ outbound clicks

CLICKS_LOCK = threading.Lock()
CLICKS = collections.Counter()  # since the last restart; every click is also printed to the log


def outbound(pid, item_id, from_page, visitor, count=True, cid=None):
    r = db().execute("SELECT shop, url FROM products WHERE id = ?", (pid,)).fetchone()
    if not r or not r["url"]:
        return None
    u = urlparse(r["url"])
    if u.scheme not in ("http", "https"):
        return None
    q = [p for p in u.query.split("&") if p and not p.startswith("utm_")]
    q = [p for p in q if not p.startswith("sp_click=")]
    q += ["utm_source=shporta", "utm_medium=referral", "utm_campaign=krahasimi"] + ([f"sp_click={cid}"] if cid else [])
    if not count:
        return u._replace(query="&".join(q)).geturl(), r["shop"]
    with CLICKS_LOCK:
        CLICKS[r["shop"]] += 1
    print(json.dumps({"click": r["shop"], "product": pid, "item": item_id, "from": from_page, "visitor": visitor,
                      "at": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds")}), flush=True)
    return u._replace(query="&".join(q)).geturl(), r["shop"]


def stats_page(data):
    """The owner's private view of /api/stats (needs ADMIN_TOKEN)."""
    e = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;")
    kinds = ["visitors", "page", "product", "category", "search", "lookup", "click"]
    names = {"visitors": "Vizitorë", "page": "Faqe të hapura", "product": "Produkte", "category": "Kategori",
             "search": "Kërkime", "lookup": "Shtesa / Ndaj", "click": "Klikime te dyqanet"}
    rows = "".join("<tr><td>" + e(d["day"]) + "".join(f"<td>{d.get(k, 0)}" for k in kinds) for d in reversed(data["days"]))
    refs = "".join(f"<tr><td>{e(r)}<td>{n}" for r, n in data.get("referrers", []))
    bots = "".join(f"<tr><td>{e(b)}<td>{n}<td>{e(last)}" for b, n, last in data.get("crawlers", []))
    shops = "".join(f"<tr><td>{e(s.removeprefix('www.'))}<td>{n}<td>{v}<td>{e((src or '').replace(',', ', '))}"
                    for s, n, v, src in data.get("shops", []))
    reports = "".join(f"<tr><td>{e(d)}<td><a href='/produkt/{e(i)}'>{e(i)}</a><td>{e(o)}<td>{e(k)}<td>{e(n)}<td>{c}"
                      for d, i, o, k, n, c in feedback.summary())
    return f"""<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><title>Statistika | shporta</title>
<style>body{{font:15px system-ui;margin:24px;max-width:960px}}table{{border-collapse:collapse;margin:8px 0 28px}}
td,th{{border-bottom:1px solid #ddd;padding:5px 10px;text-align:right}}td:first-child,th:first-child{{text-align:left}}</style>
<h1>Statistika e shportës (30 ditët e fundit)</h1>
<p>Pa cookies dhe pa ruajtur adresa: një vizitor numërohet një herë në ditë. Robotët e kërkimit dhe të AI-së numërohen veçmas.</p>
<table><tr><th>Dita{"".join(f"<th>{names[k]}" for k in kinds)}{rows}</table>
<h2>Raportimet e gabimeve</h2><p>Një listim del nga krahasimi kur 3 vizitorë të ndryshëm thonë që është produkt ose madhësi tjetër.</p>
<table><tr><th>Dita<th>Produkti<th>Listimi<th>Arsyeja<th>Shënim<th>Sa herë{reports or "<tr><td>Ende asnjë"}</table>
<h2>Klikime te çdo dyqan</h2><p>Kjo është prova që u tregojmë dyqaneve: sa vizitorë u dërgojmë (çdo link ka utm_source=shporta).</p>
<table><tr><th>Dyqani<th>Klikime<th>Vizitorë<th>Nga faqja{shops or "<tr><td>Ende asnjë"}</table>
<h2>Nga erdhën vizitorët</h2><table><tr><th>Faqja<th>Vizita{refs or "<tr><td>Ende asnjë"}</table>
<h2>Robotët e kërkimit dhe AI që lexojnë shportën</h2><table><tr><th>Roboti<th>Kërkesa<th>Hera e fundit{bots or "<tr><td>Ende asnjë"}</table>"""


# ------------------------------------------------------------------ HTTP

class Handler(BaseHTTPRequestHandler):
    timeout = 15  # a client that stops sending (or sends a wrong Content-Length) can't hold a thread forever

    def _send(self, code, body, ctype="application/json; charset=utf-8", cache=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        if cache:
            self.send_header("Cache-Control", cache)
        if getattr(self, "noindex", False):
            self.send_header("X-Robots-Tag", "noindex")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":  # HEAD gets the same headers without the body (link checkers use it)
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_OPTIONS(self):
        self._send(204, b"")

    def count(self, kind, shop=None, src=None, cid=None):
        # behind Caddy the visitor's address is in X-Forwarded-For; stats.py never stores it, only a daily hash
        ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
        stats.record(kind, ip, self.headers.get("User-Agent", ""), self.headers.get("Referer", ""), shop=shop, src=src, cid=cid)

    def admin(self, q):
        token = os.environ.get("ADMIN_TOKEN")
        given = self.headers.get("X-Admin-Token") or q.get("token") or ""
        return bool(token) and hmac.compare_digest(given.encode(), token.encode())

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = unquote(u.path)
        if (self.headers.get("Host") or "").lower().startswith("www."):  # one address for search engines: shporta.app
            self.send_response(301)
            self.send_header("Location", seo.BASE + self.path)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            crawl = self.crawler_file(path)
            if crawl:
                self.count("crawl")  # robots.txt, sitemaps, llms.txt: mostly search and AI crawlers
                return self._send(200, crawl[1].encode(), crawl[0], cache="public, max-age=3600")
            if path == "/api/health":
                return self._send(200, {"ok": True, "offers": db().execute("SELECT COUNT(*) FROM products").fetchone()[0]})
            if path == "/api/home":
                return self._send(200, cached_home(), cache="public, max-age=600")
            if path.startswith("/api/category/"):
                self.count("category")
                res = category(path.rsplit("/", 1)[1], q)
                return self._send(200 if res else 404, res or {"error": "Kjo kategori nuk ekziston."})
            if path.startswith("/api/item/"):
                self.count("product")
                res = item(path.rsplit("/", 1)[1])
                return self._send(200 if res else 404, res or {"error": "Ky produkt nuk u gjet."})
            if path == "/api/search":
                self.count("search")
                return self._send(200, search(q.get("q", ""), page_num(q)))
            if path == "/api/report":
                res = report_with_history(q.get("month"))
                return self._send(200 if res else 404, res or {"error": "Ky raport nuk ekziston."}, cache="public, max-age=600")
            if path in ("/njoftim/konfirmo", "/njoftim/ndalo"):
                self.noindex = True
                return self._send(200, alert_page(path, q).encode(), "text/html; charset=utf-8", cache="no-store")
            if path == "/api/suggest":
                return self._send(200, suggest(q.get("q", "")[:100]), cache="public, max-age=300")
            if path == "/api/barcode":
                self.count("search")
                return self._send(200, barcode(q.get("code", "")[:20]))
            if path == "/api/identify":
                self.count("search")
                return self._send(200, identify(q.get("text", "")[:600]))
            if path == "/api/basket":
                return self._send(200, basket(q.get("ids", "")))
            if path == "/api/items":
                return self._send(200, items_by_ids(q.get("ids", "")))
            if path == "/api/dupes":
                return self._send(200, dupe_list(q), cache="public, max-age=600")
            if path == "/api/shops":
                return self._send(200, shops(), cache="public, max-age=3600")
            if path == "/api/dyqan":  # /per-dyqanet: a shop's position against the others (partners.py)
                code, out = partners.check(sys.modules[__name__], q.get("d", "")[:200])
                return self._send(code, out)
            if path == "/api/dyqan/kerkesat" and self.admin(q):  # what shops asked us (owner only)
                return self._send(200, partners.requests_list())
            if path == "/api/push/key":  # notifications on the phone/computer (push.py)
                return self._send(200, {"key": push.key()}, cache="public, max-age=86400")
            if path.startswith("/go/"):
                cookies = dict(c.strip().split("=", 1) for c in (self.headers.get("Cookie") or "").split(";") if "=" in c)
                visitor = cookies.get("sp_id") if cookies.get("sp_consent") == "all" else None
                pid = path.rsplit("/", 1)[1]
                if not pid.isdigit() or len(pid) > 12:
                    return self._send(404, {"error": "Ky link nuk ekziston më."})
                # HEAD is a link checker or prefetch, not a shopper: never counted as a click
                # a random number per click, not per person: a shop that agrees can report the order it led to
                cid = secrets.token_urlsafe(6) if self.command == "GET" else None
                dest, shop = outbound(int(pid), q.get("i", "")[:20], q.get("f", "")[:20], visitor,
                                      count=self.command == "GET", cid=cid) or (None, None)
                if dest and self.command == "GET":
                    self.count("click", shop=shop, src=q.get("f", ""), cid=cid)
                if not dest:
                    return self._send(404, {"error": "Ky link nuk ekziston më."})
                self.send_response(302)
                self.send_header("Location", dest)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path in ("/api/clicks", "/api/stats", "/statistika") and self.admin(q):
                if path == "/api/clicks":
                    return self._send(200, dict(CLICKS.most_common()))
                data = stats.summary(int(q.get("days") or 30))
                if path == "/api/stats":
                    return self._send(200, data)
                return self._send(200, stats_page(data).encode(), "text/html; charset=utf-8")
        except (ValueError, sqlite3.Error):
            return self._send(400, {"error": "Kërkesë e pavlefshme."})
        except Exception as e:  # never drop the connection without an answer
            print(json.dumps({"error": f"{type(e).__name__}: {e}", "path": path[:200]}), flush=True)
            return self._send(500, {"error": "Diçka shkoi keq. Provo përsëri."})
        # static files; anything else is a page of the single-page app
        f = (WEB / path.lstrip("/")).resolve()
        if path.startswith("/pages/"):
            self.noindex = True  # a piece of a page (the app loads it); the full page is the one to index
        if path != "/" and f.is_file() and WEB.resolve() in f.parents:
            ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            return self._send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") or ctype.endswith("javascript") else ""),
                              cache="public, max-age=300")
        if path.startswith("/api/"):
            return self._send(404, {"error": "not found"})
        # a page of the app: its own title, description, structured data and content, for search engines and AI crawlers
        try:
            code, page = seo.render(sys.modules[__name__], path, q)
            if code == 200 and self.command == "GET":
                self.count("page")
        except Exception as e:
            print(json.dumps({"error": f"seo {type(e).__name__}: {e}", "path": path[:200]}), flush=True)
            code, page = 200, (WEB / "index.html").read_text(encoding="utf-8")  # the app still works without it
        return self._send(code, page.encode(), "text/html; charset=utf-8")

    def crawler_file(self, path):
        me = sys.modules[__name__]
        if path == "/robots.txt":
            return "text/plain; charset=utf-8", seo.robots_txt()
        if path == "/llms.txt":
            return "text/plain; charset=utf-8", seo.llms_txt(me)
        if path == f"/{seo.INDEXNOW_KEY}.txt":
            return "text/plain; charset=utf-8", seo.INDEXNOW_KEY
        if path == "/sitemap.xml":
            return "application/xml; charset=utf-8", seo.sitemap_index(me)
        m = re.fullmatch(r"/sitemap-([\w-]+)\.xml", path)
        if m:
            xml = seo.sitemap(me, m[1])
            return ("application/xml; charset=utf-8", xml) if xml else None
        return None

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/njoftim/ndalo":  # Gmail's own "unsubscribe" button (List-Unsubscribe-Post): stop every alert
            alerts.stop_all(parse_qs(urlparse(self.path).query).get("t", [""])[0])
            return self._send(200, {"ok": True})
        if path not in ("/api/lookup", "/api/alert", "/api/feedback", "/api/push/subscribe", "/api/push/unsubscribe", "/api/push/test",
                        "/api/dyqan", "/api/barcode/learn"):
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            if not 0 <= n <= 20000:
                return self._send(413, {"error": "Kërkesë shumë e madhe."})
            data = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("expected an object")
            if path == "/api/barcode/learn":  # Skano: the product a shopper picked for a barcode we didn't know
                ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
                return self._send(200, {"ok": learn(str(data.get("code", ""))[:20], str(data.get("item", ""))[:20], ip,
                                                    self.headers.get("User-Agent", ""))})
            if path == "/api/dyqan":  # a shop asks to be listed, sends its catalogue, wants the report or to leave
                ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
                code, msg = partners.request(data, ip, self.headers.get("User-Agent", ""))
                return self._send(code, {"message": msg} if code == 200 else {"error": msg})
            if path == "/api/feedback":  # "Raporto gabim" on a product page (feedback.py)
                ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
                offer = data.get("offer")
                offer = int(offer) if str(offer or "").isdigit() else None
                code, msg = feedback.record(str(data.get("kind", ""))[:20], str(data.get("item", ""))[:20], offer,
                                            str(data.get("note", ""))[:300], ip, self.headers.get("User-Agent", ""))
                return self._send(code, {"message": msg} if code == 200 else {"error": msg})
            if path == "/api/push/subscribe":  # notifications on: this device's push address + the products it follows
                ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
                code, msg = push.subscribe(data.get("subscription"), data.get("items"), ip, alert_item)
                return self._send(code, {"message": msg} if code == 200 else {"error": msg})
            if path == "/api/push/test":  # "Dërgo një njoftim provë" on /njoftime
                code, msg = push.test(str(data.get("endpoint", ""))[:1000])
                return self._send(code, {"message": msg} if code == 200 else {"error": msg})
            if path == "/api/push/unsubscribe":
                code, msg = push.unsubscribe(str(data.get("endpoint", ""))[:1000])
                return self._send(code, {"message": msg})
            if path == "/api/alert":  # "email me when it gets cheaper" on a product page (alerts.py)
                ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
                code, msg = alerts.subscribe(str(data.get("email", ""))[:254], str(data.get("item", ""))[:20], ip, alert_item)
                return self._send(code, {"message": msg} if code == 200 else {"error": msg})
            price = float(data["price"]) if data.get("price") not in (None, "") else None
            if price is not None and not (math.isfinite(price) and price > 0):
                price = None  # "nan", "inf", 0 or negative: as if the page showed no price
            cur = str(data.get("currency") or "ALL")[:3].upper()
            self.count("lookup")  # the extension or the share page asked about a shop's product page
            out = lookup(str(data.get("title", ""))[:300], price, cur, str(data.get("url", ""))[:500],
                         str(data.get("gtin", ""))[:20])
            try:  # a shop we can't collect: the extension may ask the shopper to share what they see (crowd.py)
                if crowd.shop_of(str(data.get("url", ""))):
                    out["wanted"] = True
                    if data.get("share") is True:
                        ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
                        out["shared"] = crowd.record(data, ip, self.headers.get("User-Agent", ""))
            except Exception as e:
                print(json.dumps({"error": f"crowd: {type(e).__name__}: {e}"}), flush=True)
            return self._send(200, out)
        except (ValueError, KeyError, TypeError):
            return self._send(400, {"error": "Kërkesë e pavlefshme."})
        except Exception as e:
            print(json.dumps({"error": f"{type(e).__name__}: {e}", "path": "/api/lookup"}), flush=True)
            return self._send(500, {"error": "Diçka shkoi keq. Provo përsëri."})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"listening on :{PORT}", flush=True)
    threading.Thread(target=push.morning, args=(DB_FILE, lambda m: print(json.dumps({"push": m}), flush=True)),
                     daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
