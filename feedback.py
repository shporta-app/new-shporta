"""What visitors tell us is wrong on a product page, and what the nightly matching learns from it.

    record(kind, item, offer, note, ip, ua)   POST /api/feedback from the product page's "Raporto gabim"
    excluded()                                match.py: listings that several people say are another product

kind: "tjeter-produkt" (this shop's listing is a different product), "madhesi" (another size), "cmim" (the price
on the shop's page is different), "tjeter" (anything else, with a note).
A listing leaves the comparison when 3 different visitors (on different days or devices) say it's another product
or another size: one person can't remove a shop from a comparison, a few independent ones can. The owner sees
every report on the private statistics page. Kept: the day, the product, the listing, the reason, a short note and
the same daily visitor code as stats.py (no address, no cookie).
"""
import collections
import re
import hashlib
import os
import sqlite3
import threading
import time
from datetime import date
from pathlib import Path

DB = Path(os.environ.get("FEEDBACK_DB", Path(__file__).parent / "data" / "feedback.db"))
KINDS = {"tjeter-produkt", "madhesi", "cmim", "tjeter"}
NEEDED = 3            # independent reports before a listing leaves the comparison
PER_IP_HOUR = 20
_lock = threading.Lock()
_recent = {}


def con():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS reports (day TEXT, item TEXT, offer INTEGER, kind TEXT, note TEXT,
                 visitor TEXT, done INTEGER DEFAULT 0)""")
    return c


def record(kind, item, offer, note, ip, ua):
    """(status, message)"""
    if kind not in KINDS or not re.fullmatch(r"[gp][0-9a-f]{12}", item or ""):
        return 400, "Zgjidh çfarë nuk shkon."
    now = time.time()
    with _lock:
        hits = [t for t in _recent.get(ip, []) if now - t < 3600]
        if len(hits) >= PER_IP_HOUR:
            return 429, "Shumë raportime. Provo përsëri pas pak."
        _recent[ip] = hits + [now]
        if len(_recent) > 20000:  # forget addresses quiet for an hour
            for k in [k for k, v in _recent.items() if not v or now - v[-1] > 3600]:
                del _recent[k]
    import stats  # the same daily code: counted once per person per day, never recognised on another day
    visitor = stats.person(ip)
    with _lock, con() as c:
        c.execute("INSERT INTO reports (day, item, offer, kind, note, visitor) VALUES (?,?,?,?,?,?)",
                  (date.today().isoformat(), item, offer, kind, (note or "")[:300], visitor))
    return 200, "Faleminderit. E kontrollojmë dhe e rregullojmë në përditësimin e radhës."


def excluded():
    """Listing ids (products.id) that NEEDED different visitors say are another product or another size."""
    if not DB.exists():
        return set()
    with con() as c:
        rows = c.execute("""SELECT offer, COUNT(DISTINCT visitor || day), COUNT(DISTINCT day) FROM reports
                            WHERE kind IN ('tjeter-produkt', 'madhesi') AND offer IS NOT NULL GROUP BY offer""").fetchall()
    return {o for o, n, days in rows if n >= NEEDED and days >= 2}  # one person can't do it in an afternoon


def summary(days=30):
    """For the owner's statistics page: the latest reports, newest first."""
    if not DB.exists():
        return []
    with con() as c:
        return c.execute("""SELECT day, item, offer, kind, note, COUNT(*) OVER (PARTITION BY offer, kind) FROM reports
                            WHERE day >= date('now', ?) ORDER BY day DESC, rowid DESC LIMIT 200""",
                         (f"-{days} day",)).fetchall()
