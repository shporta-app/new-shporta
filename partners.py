"""shporta for shops (/per-dyqanet): a shop's position against the others, and what shops ask of us.

    check(srv, domain)           GET /api/dyqan?d=…   how many of its products we compare, where it is the cheapest
                                                      and the dearest, the clicks we sent it in 30 days, 3 examples
    request(data, ip, ua)        POST /api/dyqan      a shop asks to be listed, sends its catalogue, wants the
                                                      monthly price report, or wants to be removed
    requests_list()              GET /api/dyqan/kerkesat (owner only)

The position is what anyone sees on the site, added up for one shop, so it hides nothing: the full list of products
is the monthly report a shop asks for. Kept for a request: what the shop wrote, and the same daily visitor code as
stats.py (no address, no cookie).
"""
import hashlib
import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DB = Path(os.environ.get("PARTNERS_DB", Path(__file__).parent / "data" / "partners.db"))
WANTS = {"listim", "katalog", "raport", "hiqe", "tjeter"}
PER_IP_HOUR = 5
_lock = threading.Lock()
_recent = {}
_cache = {}


def con():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS requests (at TEXT, shop TEXT, site TEXT, email TEXT, phone TEXT, wants TEXT,
                 feed TEXT, note TEXT, visitor TEXT, done INTEGER DEFAULT 0)""")
    return c


def domain_of(s):
    s = str(s or "").strip().lower()
    s = re.sub(r"^https?://", "", s).split("/")[0].split("?")[0]
    return s.removeprefix("www.")


def clicks(domain, days=30):
    import stats
    if not stats.DB.exists():
        return 0
    since = (date.today() - timedelta(days=days)).isoformat()
    c = sqlite3.connect(f"file:{stats.DB}?mode=ro", uri=True, timeout=30)
    try:
        return c.execute("""SELECT COUNT(DISTINCT visitor || day) FROM hits WHERE day >= ? AND kind = 'click' AND bot IS NULL
                            AND shop IN (?, ?)""", (since, domain, "www." + domain)).fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        c.close()


def check(srv, domain):
    d = domain_of(domain)
    if not re.fullmatch(r"[a-z0-9.-]{3,80}\.[a-z]{2,}", d):
        return 400, {"error": "Shkruaj adresën e dyqanit, p.sh. dyqani.al"}
    hit = _cache.get(d)
    if hit and time.time() - hit[0] < 3600:
        return 200, hit[1]
    db = srv.db()
    shops = {r[0] for r in db.execute("SELECT DISTINCT shop FROM products WHERE shop IN (?, ?)", (d, "www." + d))}
    if not shops:
        out = {"domain": d, "listed": False, "shops": db.execute("SELECT COUNT(*) FROM shops").fetchone()[0]}
        _cache[d] = (time.time(), out)
        return 200, out
    q = ",".join("?" * len(shops))
    # its compared offers, and for each the lowest and highest price of the same product (same size) elsewhere
    rows = db.execute(f"""SELECT p.item_id, i.title, p.price, p.in_stock,
                                 (SELECT MIN(o.price) FROM products o WHERE o.item_id = p.item_id AND o.in_compare = 1
                                   AND o.in_stock = 1 AND o.currency = p.currency AND o.shop NOT IN ({q})),
                                 (SELECT MAX(o.price) FROM products o WHERE o.item_id = p.item_id AND o.in_compare = 1
                                   AND o.in_stock = 1 AND o.currency = p.currency AND o.shop NOT IN ({q}))
                          FROM products p JOIN items i ON i.id = p.item_id
                          WHERE p.shop IN ({q}) AND p.in_compare = 1 AND p.item_id LIKE 'g%' AND p.currency = 'ALL'""",
                      (*shops, *shops, *shops)).fetchall()
    seen, mine = set(), []
    for item, title, price, stock, lo, hi in rows:
        if item in seen or lo is None:
            continue
        seen.add(item)
        mine.append((item, title, price, stock, lo, hi))
    cheapest = sum(1 for m in mine if m[2] <= m[4])
    dearest = sum(1 for m in mine if m[2] > m[5])
    above = [(m[2] - m[4]) / m[4] for m in mine if m[2] > m[4]]
    worst = sorted((m for m in mine if m[2] > m[4]), key=lambda m: (m[2] - m[4]) / m[4], reverse=True)[:3]
    out = {"domain": d, "listed": True, "compared": len(mine), "cheapest": cheapest, "dearest": dearest,
           "above_pct": round(100 * sum(above) / len(above)) if above else 0, "clicks30": clicks(d),
           "examples": [{"item": m[0], "title": m[1], "price": m[2], "lowest": m[4]} for m in worst]}
    _cache[d] = (time.time(), out)
    if len(_cache) > 2000:
        _cache.clear()
    return 200, out


def request(data, ip, ua):
    """(status, message)"""
    site = domain_of(data.get("site"))
    email = str(data.get("email") or "").strip()[:254]
    wants = [w for w in (data.get("wants") or []) if w in WANTS][:5] if isinstance(data.get("wants"), list) else []
    if not re.fullmatch(r"[a-z0-9.-]{3,80}\.[a-z]{2,}", site):
        return 400, "Shkruaj adresën e dyqanit, p.sh. dyqani.al"
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return 400, "Shkruaj një email ku t'ju përgjigjemi."
    if not wants:
        return 400, "Zgjidh çfarë dëshironi."
    now = time.time()
    with _lock:
        hits = [t for t in _recent.get(ip, []) if now - t < 3600]
        if len(hits) >= PER_IP_HOUR:
            return 429, "Shumë kërkesa. Provo përsëri pas pak."
        _recent[ip] = hits + [now]
    import stats
    visitor = hashlib.sha256(f"{stats._daily_salt(date.today().isoformat())}|{ip}|{ua}".encode()).hexdigest()[:16]
    with _lock, con() as c:
        c.execute("INSERT INTO requests (at, shop, site, email, phone, wants, feed, note, visitor) VALUES (?,?,?,?,?,?,?,?,?)",
                  (datetime.now(timezone.utc).isoformat(timespec="seconds"), str(data.get("shop") or "")[:120], site, email,
                   str(data.get("phone") or "")[:40], ",".join(wants), str(data.get("feed") or "")[:500],
                   str(data.get("note") or "")[:1000], visitor))
    if "hiqe" in wants:
        return 200, "E morëm. Pasi të konfirmojmë që emaili është i dyqanit, e heqim brenda 48 orësh dhe ju shkruajmë."
    return 200, "Faleminderit. Ju shkruajmë brenda 2 ditësh pune."


def requests_list():
    if not DB.exists():
        return []
    with con() as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT rowid AS id, * FROM requests ORDER BY at DESC LIMIT 500")]
