"""Prices shoppers share from shops we can't collect.

Some shops refuse our collector (a bot check, 429, a server that times out for us) but show their prices to every
person who opens them. A shopper who turned on "Ndaj çmimet" in the extension sends, from a product page they
opened themselves, what that page publishes about the product (name, price, barcode, picture, in stock): the same
thing the extension already sends to compare it. Nothing about the person: the same daily visitor code as stats.py.

    record(p, ip, ua)   POST /api/lookup with "share": true, only for the shops in wanted()
    merge()             nightly, before match.py: the shared prices into data/phia.db (products.via = 'user')

Only shops that refused our collector, never one that said no in writing (robots.txt, its terms): those stay out.
A shared price goes on the site only if it is plausible: a price 50% away from the last one we knew needs a second
person who saw the same price. The site says where it came from: "parë nga një përdorues më 31 tetor".
"""
import hashlib
import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).parent
DB = Path(os.environ.get("CROWD_DB", HERE / "data" / "crowd.db"))
PHIA = HERE / "data" / "phia.db"
PER_VISITOR_DAY = 300
PER_SHOP_DAY = 3000   # shared observations of one shop a day, everyone together
# where shops keep their pictures, besides their own address
IMAGE_CDNS = {"cdn.shopify.com", "i0.wp.com", "i1.wp.com", "i2.wp.com"}
KEEP_DAYS = 7          # a shared price is shown at most this long after it was seen (build_seed.CROWD_STALE_DAYS)
_lock = threading.Lock()
_wanted, _wanted_at = set(), 0.0
_count = {}
# shops that said no in writing (robots.txt or their terms): never, whatever the data says about them today
SAID_NO = {"colispharmacy.al", "defacto.com.al", "skinkorean.com", "gjirafamall.com", "fantasticlook.al", "nutri.al",
           "tesi-shop.com"}


def con():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS seen (at TEXT, shop TEXT, url TEXT, title TEXT, price REAL, regular_price REAL,
                 currency TEXT, gtin TEXT, image TEXT, in_stock INTEGER, visitor TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS seen_url ON seen(shop, url)")
    return c


def wanted():
    """Shops whose prices we'd take from shoppers: ones that refused our collector or whose prices we haven't
    collected for 2 days. Not the ones that said no in writing (robots.txt, terms), nor a site we don't list."""
    global _wanted, _wanted_at
    if time.time() - _wanted_at < 3600 or not PHIA.exists():
        return _wanted
    c = sqlite3.connect(f"file:{PHIA}?mode=ro", uri=True, timeout=30)
    ours = "AND p.via IS NULL" if "via" in {r[1] for r in c.execute("PRAGMA table_info(products)")} else ""
    rows = c.execute(f"""SELECT s.domain, s.status, coalesce(s.note, ''),
                                (SELECT max(last_seen) FROM products p WHERE p.shop = s.domain {ours})
                         FROM shops s""").fetchall()
    c.close()
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    _wanted = {d.removeprefix("www.") for d, status, note, last in rows
               if d.removeprefix("www.") not in SAID_NO and not re.match(r"robots|tos|ndalohet", note, re.I)
               and (status in ("blocked", "down") or (status in ("ok", "error") and (last or "") < old))}
    _wanted_at = time.time()
    return _wanted


def shop_of(url):
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    return host if host in wanted() else None


def record(p, ip, ua):
    """Keep one shared observation if it is from a wanted shop and looks like a real product listing."""
    url = str(p.get("url") or "")[:500]
    shop = shop_of(url)
    if not shop or not url.startswith("https://") or p.get("source") not in ("jsonld", "meta"):
        return False
    try:
        price = float(p.get("price"))
        reg = float(p["regular_price"]) if p.get("regular_price") not in (None, "") else None
    except (TypeError, ValueError):
        return False
    title = re.sub(r"\s+", " ", str(p.get("title") or "")).strip()[:300]
    image = str(p.get("image") or "")[:500]
    host = urlparse(image).netloc.lower()
    if not (image.startswith("https://") and (host == shop or host.endswith("." + shop) or host in IMAGE_CDNS)):
        image = ""  # a picture from anywhere else is not the shop's
    cur = str(p.get("currency") or "")[:3].upper()
    # an international shop (zara.com, mango.com): only its Albanian store, in lek
    if not (0 < price < 5_000_000 and 3 <= len(title) and (cur == "ALL" or (cur == "EUR" and shop.endswith(".al")))):
        return False
    import stats  # the same daily code: one person per day, never recognised on another day
    visitor = stats.person(ip)
    with _lock:
        key, shop_key = (date.today().isoformat(), visitor), (date.today().isoformat(), "shop:" + shop)
        if _count.get(key, 0) >= PER_VISITOR_DAY or _count.get(shop_key, 0) >= PER_SHOP_DAY:
            return False
        _count[key] = _count.get(key, 0) + 1
        _count[shop_key] = _count.get(shop_key, 0) + 1
        if len(_count) > 50000:
            _count.clear()
        with con() as c:
            c.execute("INSERT INTO seen VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (datetime.now(timezone.utc).isoformat(timespec="seconds"), shop, url.split("?")[0].split("#")[0],
                       title, price, reg if reg and reg > price else None, cur,
                       re.sub(r"\D", "", str(p.get("gtin") or ""))[:14] or None,
                       image or None, 0 if p.get("in_stock") is False else 1, visitor))
    return True


def page(url):
    u = (url or "").lower().split("#")[0].split("?")[0].rstrip("/")
    return u.removeprefix("https://").removeprefix("http://").removeprefix("www.")


def merge():
    """The newest plausible shared price of each page (last KEEP_DAYS days) into data/phia.db."""
    if not DB.exists():
        return 0
    since = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    with con() as c:
        c.execute("DELETE FROM seen WHERE at < ?", ((datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),))
        obs = c.execute("SELECT at, shop, url, title, price, regular_price, currency, gtin, image, in_stock, visitor "
                        "FROM seen WHERE at >= ? ORDER BY at", (since,)).fetchall()
    by_page = {}
    for o in obs:
        by_page.setdefault((o[1], page(o[2])), []).append(o)
    db = sqlite3.connect(PHIA, timeout=120)
    if "via" not in {r[1] for r in db.execute("PRAGMA table_info(products)")}:
        db.execute("ALTER TABLE products ADD COLUMN via TEXT")
    n = 0
    for (shop, key), seen in by_page.items():
        at, _, url, title, price, reg, cur, gtin, image, stock, _ = seen[-1]
        rows = [r for r in db.execute("SELECT id, shop, url, title, price, last_seen FROM products WHERE shop IN (?, ?)",
                                      (shop, "www." + shop)) if page(r[2]) == key]
        known = rows[0] if len(rows) == 1 else None
        if len(rows) > 1:  # one page with several sizes in our data: which one the shopper saw isn't certain
            continue
        if known and known[5] > at:
            continue  # our own collector saw it later
        # a product we never had, or a change of more than 20%, needs two people (two addresses) who saw that price
        people = {s[10] for s in seen if abs(s[4] - price) < 1}
        if (not known or abs(price - known[4]) > known[4] * 0.2) and len(people) < 2:
            continue
        if known:
            db.execute("""UPDATE products SET price=?, regular_price=?, in_stock=?, currency=?, last_seen=?, via='user',
                          gtin=coalesce(gtin, ?), image=coalesce(image, ?) WHERE id=?""",
                       (price, reg, stock, cur, at, gtin, image, known[0]))
            pid = known[0]
        else:
            shop_domain = db.execute("SELECT domain FROM shops WHERE domain IN (?, ?)", (shop, "www." + shop)).fetchone()
            db.execute("""INSERT OR IGNORE INTO products (shop, external_id, url, title, image, gtin, currency, price,
                          regular_price, in_stock, first_seen, last_seen, via) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'user')""",
                       (shop_domain[0] if shop_domain else shop, "u:" + key, url, title, image, gtin, cur, price, reg,
                        stock, at, at))
            pid = db.execute("SELECT id FROM products WHERE shop=? AND external_id=?",
                             (shop_domain[0] if shop_domain else shop, "u:" + key)).fetchone()[0]
        db.execute("INSERT OR REPLACE INTO prices (product_id, day, price, regular_price) VALUES (?,?,?,?)",
                   (pid, at[:10], price, reg))
        n += 1
    db.commit()
    db.close()
    return n


if __name__ == "__main__":
    print(f"{merge()} shared prices merged")
