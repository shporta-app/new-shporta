"""API (and a small search page) over the compact DB from build_seed.py.

    python server.py            -> http://localhost:8787 (Render sets PORT)

GET  /                      search page
GET  /api/search?q=...      products whose title contains all words, grouped per product
GET  /api/health
POST /api/lookup  {"title","price","currency","url"}
     -> the same product in our shops (name + size match), a price verdict, and similar products when
        there's no exact match (e.g. a Zara page: we hold no Zara data, the shopper's own page supplies it)

Standard library only. All lookups are SQL against a read-only file, so memory stays small (Render free: 512 MB).
"""
import collections
import gzip
import json
import os
import re
import shutil
import sqlite3
import statistics
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from match import parse, same_size

HERE = Path(__file__).parent
PORT = int(os.environ.get("PORT", 8787))
DB_FILE = HERE / "seed" / "phia-api.db"


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


COLS = "id, shop, title, brand, url, image, price, regular_price, currency, in_stock, name_key, size_val, size_unit"


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
    return {k: o[k] for k in ("shop", "title", "brand", "url", "image", "price", "regular_price", "currency", "in_stock")}


def lookup(title, price=None, currency="ALL", url=""):
    key, size = parse(title or "")
    page_host = urlparse(url).netloc.lower().removeprefix("www.") if url else ""
    cands = [dict(r) for r in db().execute(f"SELECT {COLS} FROM products WHERE name_key = ?", (key,))] if key else []
    exact = [o for o in cands if size is None or o["size_val"] is None or same_size(size, (o["size_val"], o["size_unit"]))]
    if size is None and len({(o["size_val"], o["size_unit"]) for o in exact if o["size_val"]}) > 1:
        exact = []  # the page doesn't say which size, and we sell several: don't guess
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
    """Products covering most of the page title's words (in either language), cheaper ones first."""
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


def search(q, limit=40):
    words = [w for w in re.findall(r"\w+", q.lower()) if len(w) > 1][:6]
    if not words:
        return []
    sql = f"SELECT {COLS} FROM products WHERE " + " AND ".join("lower(title) LIKE ?" for _ in words) + " LIMIT 400"
    grouped = collections.defaultdict(list)
    for r in db().execute(sql, [f"%{w}%" for w in words]):
        o = dict(r)
        grouped[(o["name_key"], o["size_val"])].append(o)
    out = [{"name": max((o["title"] for o in v), key=len), "offers": [public(o) for o in one_per_shop(v)]} for v in grouped.values()]
    out.sort(key=lambda g: -len(g["offers"]))
    return out[:limit]


PAGE = (HERE / "web" / "index.html")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/search":
            return self._send(200, search(parse_qs(u.query).get("q", [""])[0]))
        if u.path == "/api/health":
            n = db().execute("SELECT COUNT(*) FROM products").fetchone()[0]
            return self._send(200, {"ok": True, "products": n})
        self._send(404, {"error": "not found"})

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
