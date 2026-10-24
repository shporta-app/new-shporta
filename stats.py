"""Visitor counts without cookies and without keeping anyone's address.

For each request the server tells us about (a page, a product, a search, an extension lookup, a click to a shop) we
store: the day, what kind of request it was, the site the visitor came from, and a visitor code. The code is a
hash of the address + browser + a random daily salt that only lives in memory and in a file deleted the next day,
so a visitor can be counted once per day but never recognised later or across days, and the address is never stored.
Search engines and AI crawlers are counted apart by name (Googlebot, GPTBot, ...): that's how we see the site being
read for search and for AI answers.
"""
import collections
import hashlib
import os
import queue
import re
import secrets
import sqlite3
import threading
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

DB = Path(os.environ.get("STATS_DB", Path(__file__).parent / "data" / "stats.db"))
BOTS = ["Googlebot", "Google-InspectionTool", "GoogleOther", "Bingbot", "GPTBot", "OAI-SearchBot", "ChatGPT-User",
        "ClaudeBot", "Claude-SearchBot", "Claude-User", "PerplexityBot", "Perplexity-User", "Applebot", "YandexBot",
        "DuckDuckBot", "DuckAssistBot", "meta-externalagent", "facebookexternalhit", "CCBot", "Bytespider",
        "AhrefsBot", "SemrushBot", "MJ12bot", "DotBot", "PetalBot", "Amazonbot", "WhatsApp", "TelegramBot", "Twitterbot"]
GENERIC_BOT = re.compile(r"bot|crawl|spider|slurp|curl|wget|python-requests|httpclient|headless|monitor|uptime", re.I)

_q = queue.Queue(maxsize=10000)
_salt = {"day": None, "value": None}


def _daily_salt(today):
    if _salt["day"] != today:
        DB.parent.mkdir(parents=True, exist_ok=True)
        f = DB.parent / f".salt-{today}"
        if not f.exists():
            f.write_text(secrets.token_hex(16))
        for old in DB.parent.glob(".salt-*"):  # yesterday's salt goes: its visitor codes can't be linked any more
            if old != f:
                old.unlink(missing_ok=True)
        _salt.update(day=today, value=f.read_text())
    return _salt["value"]


def bot_name(ua):
    for b in BOTS:
        if b.lower() in (ua or "").lower():
            return b
    return "other bot" if not ua or GENERIC_BOT.search(ua) else None


def record(kind, ip, ua, referer="", host="shporta.app", shop=None, src=None):
    """kind: page | product | category | search | lookup | click. Never blocks a request.
    A click also keeps which shop it went to and from which part of shporta (product page, home, report, extension):
    that's what we can show a shop about the visitors we send it."""
    try:
        today = date.today().isoformat()
        bot = bot_name(ua)
        ref = urlparse(referer or "").netloc.lower().removeprefix("www.")
        if ref in ("", host, "shporta.app"):
            ref = ""
        visitor = None if bot else hashlib.sha256(f"{_daily_salt(today)}|{ip}|{ua}".encode()).hexdigest()[:16]
        _q.put_nowait((today, kind, ref, visitor, bot, shop, (src or "")[:20] or None))
    except Exception:
        pass


def _writer():
    con = None
    while True:
        rows = [_q.get()]
        while not _q.empty() and len(rows) < 500:
            rows.append(_q.get_nowait())
        try:
            if con is None:
                DB.parent.mkdir(parents=True, exist_ok=True)
                con = sqlite3.connect(DB)
                con.execute("CREATE TABLE IF NOT EXISTS hits (day TEXT, kind TEXT, ref TEXT, visitor TEXT, bot TEXT)")
                con.execute("CREATE INDEX IF NOT EXISTS hits_day ON hits(day)")
                have = {r[1] for r in con.execute("PRAGMA table_info(hits)")}
                for col in ("shop", "src"):  # a database from before clicks were kept per shop
                    if col not in have:
                        con.execute(f"ALTER TABLE hits ADD COLUMN {col} TEXT")
            con.executemany("INSERT INTO hits (day, kind, ref, visitor, bot, shop, src) VALUES (?,?,?,?,?,?,?)", rows)
            con.commit()
        except Exception as e:
            print(f"stats: {e}", flush=True)
            con = None


threading.Thread(target=_writer, daemon=True).start()


def summary(days=30):
    """Last `days` days: visitors and requests per day, what people did, where they came from, which crawlers read us."""
    if not DB.exists():
        return {"days": []}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    per_day = collections.OrderedDict()
    for d, kind, n, v in con.execute("""SELECT day, kind, COUNT(*), COUNT(DISTINCT visitor) FROM hits
                                        WHERE day >= ? AND bot IS NULL GROUP BY day, kind ORDER BY day""", (since,)):
        per_day.setdefault(d, {"day": d})[kind] = n
    for d, v in con.execute("SELECT day, COUNT(DISTINCT visitor) FROM hits WHERE day >= ? AND bot IS NULL GROUP BY day", (since,)):
        per_day.setdefault(d, {"day": d})["visitors"] = v
    refs = con.execute("""SELECT ref, COUNT(DISTINCT visitor || day) FROM hits WHERE day >= ? AND bot IS NULL AND ref != ''
                          GROUP BY ref ORDER BY 2 DESC LIMIT 25""", (since,)).fetchall()
    bots = con.execute("""SELECT bot, COUNT(*), MAX(day) FROM hits WHERE day >= ? AND bot IS NOT NULL
                          GROUP BY bot ORDER BY 2 DESC""", (since,)).fetchall()
    shops = []
    if "shop" in {r[1] for r in con.execute("PRAGMA table_info(hits)")}:
        shops = con.execute("""SELECT shop, COUNT(*), COUNT(DISTINCT visitor || day), group_concat(DISTINCT src) FROM hits
                               WHERE day >= ? AND kind = 'click' AND bot IS NULL AND shop IS NOT NULL
                               GROUP BY shop ORDER BY 2 DESC""", (since,)).fetchall()
    con.close()
    return {"days": list(per_day.values()), "referrers": refs, "crawlers": bots, "shops": shops}
