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
import hmac
import json
import math
import mimetypes
import os
import re
import shutil
import sys
import sqlite3
import statistics
import threading
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import dupes
import seo
import stats
from match import GENERIC, MEN_WORDS, PERFUME_WORDS, SECOND_HAND, WOMEN_WORDS, gender_of, parse, same_size, size_by_price, size_label

HERE = Path(__file__).parent
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")
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
    return out


def page_num(q):
    """?page= as a sane number: no negative pages, and no number too big for SQLite (that crashed the request)."""
    try:
        return min(max(0, int(q.get("page") or 0)), 10000)
    except ValueError:
        return 0


def item_rows(sql, args):
    return [dict(r) for r in db().execute(sql, args)]


# ------------------------------------------------------------------ site endpoints

def home():
    stats = {
        "offers": db().execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "shops": db().execute("SELECT COUNT(*) FROM shops").fetchone()[0],
        "compared": db().execute("SELECT COUNT(*) FROM items WHERE shops >= 2").fetchone()[0],
        "updated": meta("updated"),
    }
    # deals: the same product, in stock in 3+ shops, with a real gap (very large gaps are usually a mismatch)
    pool = item_rows(f"""SELECT {ITEM_COLS} FROM items WHERE in_stock_shops >= 3 AND currency = 'ALL' AND cat != 'tjeter'
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
    featured = item_rows(f"""SELECT {ITEM_COLS} FROM items WHERE in_stock_shops >= 5 AND currency = 'ALL' AND cat != 'tjeter'
                             AND save_pct BETWEEN 20 AND 60 AND image IS NOT NULL
                             ORDER BY in_stock_shops DESC, save_pct DESC LIMIT 12""", ())
    for f in featured:
        f["offers"] = offers_for(f["id"])
    cats = {c: n for c, n in db().execute("SELECT cat, COUNT(*) FROM items GROUP BY cat")}
    top = {k: [r for r in dupe_list({"kind": k})["items"] if r["orig_image"]] for k in ("inspired", "active", "known")}
    picks = [r for trio in zip(top["inspired"][:4], top["known"][:4] or [None] * 4, top["active"][:4]) for r in trio if r][:9]
    return {"stats": stats, "deals": deals, "featured": featured, "impact": impact(), "routine": routine(), "dupes": picks,
            "categories": [{"id": c, "label": label, "count": cats.get(c, 0)} for c, label in CATEGORIES.items()]}


_home = {"at": 0, "data": None}


def cached_home():
    import time
    if not _home["data"] or time.time() - _home["at"] > 600:
        _home["data"], _home["at"] = home(), time.time()
    return _home["data"]


def impact():
    """How much more the dearest shop asks than the cheapest, for the same product in stock in 3+ shops."""
    rows = db().execute("""SELECT min_price, max_price FROM items WHERE in_stock_shops >= 3 AND currency = 'ALL'
                           AND cat != 'tjeter' AND save_pct BETWEEN 3 AND 70""").fetchall()
    if not rows:
        return None
    more = sorted((hi / lo - 1) * 100 for lo, hi in rows if lo > 0)
    diff = sorted(hi - lo for lo, hi in rows)
    return {"products": len(rows), "median_more_pct": round(statistics.median(more)),
            "median_diff": round(statistics.median(diff)), "share_over_20": round(sum(m >= 20 for m in more) / len(more) * 100)}


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
    if cat not in CATEGORIES and cat != "tjeter":
        return None
    where, args = ["cat = ?"], [cat]
    if q.get("compared") == "1":
        where.append("shops >= 2")
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
        "SELECT shop FROM products WHERE cat = ? GROUP BY shop ORDER BY COUNT(*) DESC LIMIT 40", (cat,))]
    return {"id": cat, "label": CATEGORIES.get(cat, "Të tjera"), "total": total, "page": page,
            "page_size": PAGE_SIZE, "items": items, "shops": shops}


DUPE_COLS = """x.kind, x.reason, x.save_pct, x.orig_price, x.dupe_price, x.orig_size, x.dupe_size, x.dupe_product,
               o.id AS orig_id, o.title AS orig_title, o.image AS orig_image, o.shops AS orig_shops,
               d.id AS dupe_id, d.title AS dupe_title, d.image AS dupe_image, d.shops AS dupe_shops"""
DUPE_FROM = "FROM dupes x JOIN items o ON o.id = x.item_id JOIN items d ON d.id = x.dupe_id"


def dupes_of(item_id, limit=8):
    return item_rows(f"SELECT {DUPE_COLS} {DUPE_FROM} WHERE x.item_id = ? ORDER BY x.save_pct DESC LIMIT ?", (item_id, limit))


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
    if not r:
        return None
    it = dict(r)
    it["offers"] = offers_for(item_id)
    # shops selling it without stating the size: listed apart, never the cheapest, never in "save up to"
    main_shops = {o["shop"] for o in it["offers"]}
    it["unconfirmed"] = [public(o) for o in one_per_shop([dict(x) for x in db().execute(
        f"SELECT {COLS} FROM products WHERE item_id = ? AND in_compare = 0", (item_id,))]) if o["shop"] not in main_shops]
    first = db().execute("SELECT name_key FROM products WHERE item_id = ? LIMIT 1", (item_id,)).fetchone()
    cur = it["currency"]
    sim = similar(first[0] if first else "", it["min_price"], cur, limit=12)
    # the same product name in other sizes (or other single listings): their own list, never "similar"
    same = [r[0] for r in db().execute("SELECT DISTINCT item_id FROM products WHERE name_key = ? AND item_id != ? LIMIT 12",
                                       (first[0], item_id))] if first and len(first[0].split()) >= 2 else []
    it["other_sizes"] = item_rows(f"SELECT {ITEM_COLS} FROM items WHERE id IN ({','.join('?' * len(same))})", same) if same else []
    seen, out = {item_id} | set(same), []
    for o in sim:
        if o["item_id"] not in seen:
            seen.add(o["item_id"])
            out.append(o["item_id"])
    it["similar"] = item_rows(f"SELECT {ITEM_COLS} FROM items WHERE id IN ({','.join('?' * len(out))})", out) if out else []
    it["category_label"] = CATEGORIES.get(it["cat"], "Të tjera")
    it["tracked_since"] = TRACKED_SINCE  # the first day of price history: claims about "lowest" only reach back to it
    it["used"] = any(o["shop"] in SECOND_HAND for o in it["offers"])
    for o in it["offers"]:  # a shop that writes only "55" in a 55 g comparison: same number, show it with the unit
        if not o.get("size") and it["size"] and o_size_num(o) == it["size"].split()[0]:
            o["size"] = it["size"]
    it["dupes"] = dupes_of(item_id)
    it["dupe_of"] = originals_of(item_id)
    return it


def search(q, page=0):
    words = [w for w in re.findall(r"[^\W_]+", fold(q)) if len(w) > 1][:6]  # no "_": it's a LIKE wildcard
    if not words:
        return {"q": q, "total": 0, "items": []}
    where = " AND ".join("search LIKE ?" for _ in words)
    args = [f"%{w}%" for w in words]
    long = [w for w in words if len(w) >= 3]  # the trigram index narrows the items, the LIKEs above stay the rule
    if long and HAS_ITEM_SEARCH:
        where = f"rowid IN (SELECT rowid FROM item_search WHERE {' AND '.join('search LIKE ?' for _ in long)}) AND {where}"
        args = [f"%{w}%" for w in long] + args
    total = db().execute(f"SELECT COUNT(*) FROM items WHERE {where}", args).fetchone()[0]
    items = item_rows(f"""SELECT {ITEM_COLS} FROM items WHERE {where}
                          ORDER BY shops DESC, in_stock_shops DESC, min_price LIMIT ? OFFSET ?""",
                      args + [PAGE_SIZE, page * PAGE_SIZE])
    return {"q": q, "total": total, "page": page, "page_size": PAGE_SIZE, "items": items}


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


def lookup(title, price=None, currency="ALL", url=""):
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
        offers = [o for o in one_per_shop(offers) if o["shop"].removeprefix("www.") != page_host]  # never the shop you're on
        item_id = item_id or next((o["item_id"] for o in offers if o["item_id"].startswith("g")), None)
        exact = [public(o) for o in offers[:20]]
        for o in exact:  # a shop that writes only "55" in a 55 g comparison: same number, show it with the unit
            if not o.get("size") and q.get("size_label") and o_size_num(o) == q["size_label"].split()[0]:
                o["size"] = q["size_label"]
        out = {"query": q, "exact": exact, "verdict": None if q.get("no_verdict") else verdict(q["price"], currency, offers),
               "item": item_id}
        if item_id:  # shops selling it without stating the size: only counted, the product page lists them
            out["unconfirmed"] = db().execute("SELECT extra_shops FROM items WHERE id = ?", (item_id,)).fetchone()[0] or 0
        # the same product name at shops not in the comparison: they don't state the size, or sell another size.
        # Listed with each shop's own size, never compared on price, and never shown as "similar".
        taken = {o["shop"] for o in offers} | {page_host}
        same = [o for o in one_per_shop([dict(r) for r in db().execute(
                    f"SELECT {COLS} FROM products WHERE name_key = ? AND currency = ?", (key, currency))])
                if o["shop"].removeprefix("www.") not in taken and o["shop"] not in taken and o["shop"] not in SECOND_HAND]
        out["same_name"] = [public(o) for o in same[:12]] if len(key.split()) >= 2 else []
        if not offers:
            out["similar"] = [public(o) for o in similar(key, price, currency)
                              if o["shop"].removeprefix("www.") != page_host and o["name_key"] != key]
        out["dupes"] = dupes_of(item_id, limit=4) if item_id else page_dupes(title, price, currency, offers)
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

    # 2. otherwise by name, with match.py's rules: a specific name, and the same size
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
        rows = dupes_of(offers[0]["item_id"], limit=4)
        if rows:
            return rows
    if not price or currency != "ALL":
        return []
    # perfume: the page names an original that shops sell "inspired by" versions of ("Creed Aventus")
    words = set(re.findall(r"[a-z0-9]+", dupes.fold(title)))
    for reason, orig_id in db().execute("SELECT DISTINCT reason, item_id FROM dupes WHERE kind = 'inspired'"):
        name = [w for w in re.findall(r"[a-z0-9]+", dupes.fold(reason.split(" nga ", 1)[-1])) if w not in dupes.GENDER]
        if len(name) >= 2 and all(w in words for w in name):
            rows = [r for r in dupes_of(orig_id, limit=4) if r["dupe_price"] <= price * 0.7]
            if rows:
                return rows
    m = dupes.ACTIVE_RE.search(dupes.fold(title))
    kind = dupes.kind_of(title)
    if not (m and kind):
        return []
    act, pct = m.group(1), float(m.group(2).replace(",", "."))
    out = []
    for it in item_rows(f"""SELECT {ITEM_COLS} FROM items WHERE cat = 'lekure' AND currency = 'ALL' AND in_stock_shops >= 1
                            AND search LIKE ? AND search LIKE ? AND min_price <= ? ORDER BY min_price LIMIT 300""",
                        (f"%{act}%", f"%{m.group(2)}%", price * 0.7)):
        mm = dupes.ACTIVE_RE.search(dupes.fold(it["title"]))
        if mm and mm.group(1) == act and float(mm.group(2).replace(",", ".")) == pct and dupes.kind_of(it["title"]) == kind \
                and dupes.first_word(it["title"]) != dupes.first_word(title):
            out.append({"kind": "active", "reason": f"{dupes.ACTIVES[act]} {pct:g}%", "dupe_id": it["id"],
                        "dupe_title": it["title"], "dupe_image": it["image"], "dupe_price": it["min_price"],
                        "save_pct": round((1 - it["min_price"] / price) * 100)})
        if len(out) == 4:
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


def outbound(pid, item_id, from_page, visitor, count=True):
    r = db().execute("SELECT shop, url FROM products WHERE id = ?", (pid,)).fetchone()
    if not r or not r["url"]:
        return None
    u = urlparse(r["url"])
    if u.scheme not in ("http", "https"):
        return None
    q = [p for p in u.query.split("&") if p and not p.startswith("utm_")]
    q += ["utm_source=shporta", "utm_medium=referral", "utm_campaign=krahasimi"]
    if not count:
        return u._replace(query="&".join(q)).geturl()
    with CLICKS_LOCK:
        CLICKS[r["shop"]] += 1
    print(json.dumps({"click": r["shop"], "product": pid, "item": item_id, "from": from_page, "visitor": visitor,
                      "at": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds")}), flush=True)
    return u._replace(query="&".join(q)).geturl()


def stats_page(data):
    """The owner's private view of /api/stats (needs ADMIN_TOKEN)."""
    e = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;")
    kinds = ["visitors", "page", "product", "category", "search", "lookup", "click"]
    names = {"visitors": "Vizitorë", "page": "Faqe të hapura", "product": "Produkte", "category": "Kategori",
             "search": "Kërkime", "lookup": "Shtesa / Ndaj", "click": "Klikime te dyqanet"}
    rows = "".join("<tr><td>" + e(d["day"]) + "".join(f"<td>{d.get(k, 0)}" for k in kinds) for d in reversed(data["days"]))
    refs = "".join(f"<tr><td>{e(r)}<td>{n}" for r, n in data.get("referrers", []))
    bots = "".join(f"<tr><td>{e(b)}<td>{n}<td>{e(last)}" for b, n, last in data.get("crawlers", []))
    return f"""<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><title>Statistika | shporta</title>
<style>body{{font:15px system-ui;margin:24px;max-width:960px}}table{{border-collapse:collapse;margin:8px 0 28px}}
td,th{{border-bottom:1px solid #ddd;padding:5px 10px;text-align:right}}td:first-child,th:first-child{{text-align:left}}</style>
<h1>Statistika e shportës (30 ditët e fundit)</h1>
<p>Pa cookies dhe pa ruajtur adresa: një vizitor numërohet një herë në ditë. Robotët e kërkimit dhe të AI-së numërohen veçmas.</p>
<table><tr><th>Dita{"".join(f"<th>{names[k]}" for k in kinds)}{rows}</table>
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

    def count(self, kind):
        # behind Caddy the visitor's address is in X-Forwarded-For; stats.py never stores it, only a daily hash
        ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
        stats.record(kind, ip, self.headers.get("User-Agent", ""), self.headers.get("Referer", ""))

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
            if path == "/api/items":
                return self._send(200, items_by_ids(q.get("ids", "")))
            if path == "/api/dupes":
                return self._send(200, dupe_list(q), cache="public, max-age=600")
            if path == "/api/shops":
                return self._send(200, shops(), cache="public, max-age=3600")
            if path.startswith("/go/"):
                cookies = dict(c.strip().split("=", 1) for c in (self.headers.get("Cookie") or "").split(";") if "=" in c)
                visitor = cookies.get("sp_id") if cookies.get("sp_consent") == "all" else None
                pid = path.rsplit("/", 1)[1]
                if not pid.isdigit() or len(pid) > 12:
                    return self._send(404, {"error": "Ky link nuk ekziston më."})
                # HEAD is a link checker or prefetch, not a shopper: never counted as a click
                dest = outbound(int(pid), q.get("i", "")[:20], q.get("f", "")[:20], visitor, count=self.command == "GET")
                if dest and self.command == "GET":
                    self.count("click")
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
        if urlparse(self.path).path != "/api/lookup":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            if not 0 <= n <= 20000:
                return self._send(413, {"error": "Kërkesë shumë e madhe."})
            data = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("expected an object")
            price = float(data["price"]) if data.get("price") not in (None, "") else None
            if price is not None and not (math.isfinite(price) and price > 0):
                price = None  # "nan", "inf", 0 or negative: as if the page showed no price
            cur = str(data.get("currency") or "ALL")[:3].upper()
            self.count("lookup")  # the extension or the share page asked about a shop's product page
            return self._send(200, lookup(str(data.get("title", ""))[:300], price, cur, str(data.get("url", ""))[:500]))
        except (ValueError, KeyError, TypeError):
            return self._send(400, {"error": "Kërkesë e pavlefshme."})
        except Exception as e:
            print(json.dumps({"error": f"{type(e).__name__}: {e}", "path": "/api/lookup"}), flush=True)
            return self._send(500, {"error": "Diçka shkoi keq. Provo përsëri."})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"listening on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
