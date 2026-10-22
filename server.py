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
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import statistics
import threading
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from match import GENERIC, parse, same_size

HERE = Path(__file__).parent
WEB = HERE / "web"
PORT = int(os.environ.get("PORT", 8787))
DB_FILE = HERE / "seed" / "phia-api.db"
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
COLS = "id, shop, title, brand, url, image, price, regular_price, currency, in_stock, name_key, size_val, size_unit, item_id"
ITEM_COLS = "id, title, image, cat, shops, in_stock_shops, min_price, max_price, currency, save_pct, size_note"


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
    return {"label": label, "lowest": lo, "median": med, "shops": len(peers), "save": round(price - lo) if price > lo else 0}


def public(o):
    return {k: o[k] for k in ("id", "shop", "title", "brand", "url", "image", "price", "regular_price", "currency", "in_stock")
            if k in o.keys()} | ({"item": o["item_id"]} if "item_id" in o.keys() else {})


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
    return {"stats": stats, "deals": deals, "featured": featured, "impact": impact(), "routine": routine(),
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
    offs = [dict(r) for r in db().execute(f"SELECT {COLS} FROM products WHERE item_id = ?", (item_id,))]
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
    page = max(0, int(q.get("page") or 0))
    sql = " AND ".join(where)
    total = db().execute(f"SELECT COUNT(*) FROM items WHERE {sql}", args).fetchone()[0]
    items = item_rows(f"SELECT {ITEM_COLS} FROM items WHERE {sql} ORDER BY {order} LIMIT ? OFFSET ?",
                      args + [PAGE_SIZE, page * PAGE_SIZE])
    shops = [r[0] for r in db().execute(
        "SELECT shop FROM products WHERE cat = ? GROUP BY shop ORDER BY COUNT(*) DESC LIMIT 40", (cat,))]
    return {"id": cat, "label": CATEGORIES.get(cat, "Të tjera"), "total": total, "page": page,
            "page_size": PAGE_SIZE, "items": items, "shops": shops}


def item(item_id):
    r = db().execute(f"SELECT {ITEM_COLS} FROM items WHERE id = ?", (item_id,)).fetchone()
    if not r:
        return None
    it = dict(r)
    it["offers"] = offers_for(item_id)
    first = db().execute("SELECT name_key FROM products WHERE item_id = ? LIMIT 1", (item_id,)).fetchone()
    cur = it["currency"]
    sim = similar(first[0] if first else "", it["min_price"], cur, limit=12)
    seen, out = {item_id}, []
    for o in sim:
        if o["item_id"] not in seen:
            seen.add(o["item_id"])
            out.append(o["item_id"])
    it["similar"] = item_rows(f"SELECT {ITEM_COLS} FROM items WHERE id IN ({','.join('?' * len(out))})", out) if out else []
    it["category_label"] = CATEGORIES.get(it["cat"], "Të tjera")
    return it


def search(q, page=0):
    words = [w for w in re.findall(r"\w+", fold(q)) if len(w) > 1][:6]
    if not words:
        return {"q": q, "total": 0, "items": []}
    where = " AND ".join("search LIKE ?" for _ in words)
    args = [f"%{w}%" for w in words]
    total = db().execute(f"SELECT COUNT(*) FROM items WHERE {where}", args).fetchone()[0]
    items = item_rows(f"""SELECT {ITEM_COLS} FROM items WHERE {where}
                          ORDER BY shops DESC, in_stock_shops DESC, min_price LIMIT ? OFFSET ?""",
                      args + [PAGE_SIZE, page * PAGE_SIZE])
    return {"q": q, "total": total, "page": page, "page_size": PAGE_SIZE, "items": items}


def shops():
    rows = db().execute("""SELECT s.domain, s.category, COUNT(p.id) n
                           FROM shops s LEFT JOIN products p ON p.shop = s.domain GROUP BY s.domain ORDER BY n DESC""")
    return [{"domain": d, "category": c, "products": n} for d, c, n in rows]


# ------------------------------------------------------------------ extension endpoint

def lookup(title, price=None, currency="ALL", url=""):
    key, size = parse(title or "")
    page_host = urlparse(url).netloc.lower().removeprefix("www.") if url else ""
    # Same rules as match.py: a specific name (3+ words, not only generic words like "fustan midi"),
    # and sizes stated on both sides and equal; with no size anywhere, prices must agree within 25%.
    words = key.split()
    specific = len(words) >= 3 and any(w not in GENERIC for w in words)
    cands = [dict(r) for r in db().execute(f"SELECT {COLS} FROM products WHERE name_key = ?", (key,))] if specific else []
    if size is not None:
        exact = [o for o in cands if o["size_val"] is not None and same_size(size, (o["size_val"], o["size_unit"]))]
    else:
        exact = [o for o in cands if o["size_val"] is None and price and price / 1.25 <= o["price"] <= price * 1.25]
    offers = [o for o in one_per_shop(exact) if o["shop"].removeprefix("www.") != page_host]
    out = {"query": {"title": title, "price": price, "currency": currency, "key": key, "size": size},
           "exact": [public(o) for o in offers[:20]], "verdict": verdict(price, currency, offers)}
    if not offers:
        out["similar"] = [public(o) for o in similar(key, price, currency)]
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
]
ALTS = collections.defaultdict(set)
for _g in SYNONYMS:
    for _w in _g:
        ALTS[_w] |= _g


def similar(key, price, currency, limit=8):
    """Products covering most of the title's words (in either language), cheaper ones first."""
    q = [w for w in set(key.split()) if re.fullmatch(r"[a-z0-9]+", w)]
    if len(q) < 2:
        return []
    groups = [sorted(ALTS.get(w) or {w}) for w in q]
    match = " OR ".join("(" + " OR ".join(f'"{a}"' for a in g) + ")" for g in groups)
    cand = [dict(r) for r in db().execute(
        f"""SELECT {COLS} FROM products WHERE id IN (SELECT rowid FROM words WHERE words MATCH ? ORDER BY rank LIMIT 3000)
            AND in_stock = 1 AND currency = ?""", (match, currency))]
    need = max(2, round(len(q) * 0.66))
    scored = []
    for o in cand:
        kw = set((o["name_key"] or "").split())
        hits = sum(1 for g in groups if kw & set(g))
        if hits >= need:
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
    if price:
        res.sort(key=lambda o: (o["price"] >= price, o["price"]))
    return res[:limit]


# ------------------------------------------------------------------ outbound clicks

CLICKS = collections.Counter()  # since the last restart; every click is also printed to the log


def outbound(pid, item_id, from_page, visitor):
    r = db().execute("SELECT shop, url FROM products WHERE id = ?", (pid,)).fetchone()
    if not r or not r["url"]:
        return None
    u = urlparse(r["url"])
    if u.scheme not in ("http", "https"):
        return None
    q = [p for p in u.query.split("&") if p and not p.startswith("utm_")]
    q += ["utm_source=shporta", "utm_medium=referral", "utm_campaign=krahasimi"]
    CLICKS[r["shop"]] += 1
    print(json.dumps({"click": r["shop"], "product": pid, "item": item_id, "from": from_page, "visitor": visitor,
                      "at": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds")}), flush=True)
    return u._replace(query="&".join(q)).geturl()


# ------------------------------------------------------------------ HTTP

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8", cache=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        if cache:
            self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = unquote(u.path)
        try:
            if path == "/api/health":
                return self._send(200, {"ok": True, "offers": db().execute("SELECT COUNT(*) FROM products").fetchone()[0]})
            if path == "/api/home":
                return self._send(200, cached_home(), cache="public, max-age=600")
            if path.startswith("/api/category/"):
                res = category(path.rsplit("/", 1)[1], q)
                return self._send(200 if res else 404, res or {"error": "Kjo kategori nuk ekziston."})
            if path.startswith("/api/item/"):
                res = item(path.rsplit("/", 1)[1])
                return self._send(200 if res else 404, res or {"error": "Ky produkt nuk u gjet."})
            if path == "/api/search":
                return self._send(200, search(q.get("q", ""), max(0, int(q.get("page") or 0))))
            if path == "/api/shops":
                return self._send(200, shops(), cache="public, max-age=3600")
            if path.startswith("/go/"):
                cookies = dict(c.strip().split("=", 1) for c in (self.headers.get("Cookie") or "").split(";") if "=" in c)
                visitor = cookies.get("sp_id") if cookies.get("sp_consent") == "all" else None
                dest = outbound(int(path.rsplit("/", 1)[1]), q.get("i", "")[:20], q.get("f", "")[:20], visitor)
                if not dest:
                    return self._send(404, {"error": "Ky link nuk ekziston më."})
                self.send_response(302)
                self.send_header("Location", dest)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/api/clicks" and os.environ.get("ADMIN_TOKEN") and q.get("token") == os.environ["ADMIN_TOKEN"]:
                return self._send(200, dict(CLICKS.most_common()))
        except (ValueError, sqlite3.Error) as e:
            return self._send(400, {"error": str(e)})
        # static files; anything else is a page of the single-page app
        f = (WEB / path.lstrip("/")).resolve()
        if path != "/" and f.is_file() and WEB.resolve() in f.parents:
            ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            return self._send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") or ctype.endswith("javascript") else ""),
                              cache="public, max-age=300")
        if path.startswith("/api/"):
            return self._send(404, {"error": "not found"})
        return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        if urlparse(self.path).path != "/api/lookup":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(min(n, 20000)) or b"{}")
            price = float(data["price"]) if data.get("price") not in (None, "") else None
            cur = str(data.get("currency") or "ALL")[:3].upper()
            return self._send(200, lookup(str(data.get("title", ""))[:300], price, cur, str(data.get("url", ""))[:500]))
        except (ValueError, KeyError, TypeError) as e:
            return self._send(400, {"error": str(e)})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"listening on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
