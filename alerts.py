"""Price-drop emails: a visitor asks to be told when a product gets cheaper; each night we check and write to them.

    subscribe(email, item, ...)   the product page's form (POST /api/alert): stored unconfirmed, a confirmation email goes out
    confirm(token)                the link in that email (/njoftim/konfirmo?t=...): only confirmed addresses ever get alerts
    stop(token)                   the link in every email (/njoftim/ndalo?t=...): one click, no login
    check(seed_db)                nightly.py --server after the rebuild: today's cheapest in-stock price below the one we
                                  last told them (or the one on the day they asked) -> one email per address

Only the email address, the product and two prices are kept (data/alerts.db). A confirmation link that is never
clicked is deleted after 7 days, an address with nothing left to follow is deleted, and nothing is shared or sold.
Emails go out through Resend (RESEND_API_KEY in /etc/shporta.env); without a key the form says it isn't ready yet.
"""
import html
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

DB = Path(os.environ.get("ALERTS_DB", Path(__file__).parent / "data" / "alerts.db"))
BASE = "https://shporta.app"
SENDER = os.environ.get("ALERT_FROM", "shporta <njoftime@shporta.app>")
EMAIL = re.compile(r"^[^@\s<>\"',;]{1,64}@[A-Za-z0-9.-]{1,200}\.[A-Za-z]{2,24}$")
PER_EMAIL = 50       # products one address may follow
PER_IP_HOUR = 10     # new subscriptions per address per hour: the form can't be used to flood someone's inbox
_lock = threading.Lock()
_recent = {}


def enabled():
    return bool(os.environ.get("RESEND_API_KEY"))


def con():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS subs (id INTEGER PRIMARY KEY, email TEXT NOT NULL, item TEXT NOT NULL,
                 title TEXT, size TEXT, currency TEXT, price REAL, last_price REAL, token TEXT UNIQUE NOT NULL,
                 confirmed INTEGER DEFAULT 0, created TEXT, last_sent TEXT, UNIQUE(email, item))""")
    return c


def lek(n, cur="ALL"):
    if cur == "EUR":
        return f"€{n:.2f}"
    if cur and cur != "ALL":
        return f"{n:.2f} {cur}"
    return f"{round(n):,}".replace(",", " ") + " L"


def send(to, subject, body_html, stop_url):
    """One email through Resend's API. True when Resend accepted it."""
    req = urllib.request.Request("https://api.resend.com/emails", method="POST", data=json.dumps({
        "from": SENDER, "to": [to], "subject": subject, "html": body_html,
        # Gmail and others show their own "unsubscribe" button for this
        "headers": {"List-Unsubscribe": f"<{stop_url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
    }).encode(), headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}", "Content-Type": "application/json",
                          "User-Agent": "shporta.app"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return 200 <= r.status < 300
    except urllib.error.HTTPError as e:
        print(json.dumps({"error": f"resend {e.code}: {e.read()[:300].decode(errors='replace')}"}), flush=True)
    except OSError as e:
        print(json.dumps({"error": f"resend: {e}"}), flush=True)
    return False


def page(title, inner):
    e = html.escape
    return f"""<!doctype html><html lang="sq"><body style="margin:0;background:#F7F6FA;font:16px/1.5 Arial,sans-serif;color:#14121F">
<div style="max-width:560px;margin:0 auto;padding:28px 20px">
<p style="font:800 22px Arial,sans-serif;margin:0 0 18px">shporta</p>
<h1 style="font:700 21px/1.3 Arial,sans-serif;margin:0 0 14px">{e(title)}</h1>{inner}
<p style="color:#6E6A7C;font-size:13px;margin-top:28px">Çmimet janë ato që dyqanet publikojnë në faqet e tyre, të kontrolluara çdo natë.
Kontrollo gjithmonë çmimin dhe madhësinë te dyqani para se të blesh.</p></div></body></html>"""


def subscribe(email, item, ip, lookup_item):
    """(status, message). lookup_item(id) -> today's item dict or None (server.item)."""
    email = (email or "").strip()
    if not EMAIL.match(email) or len(email) > 254:
        return 400, "Shkruaj një adresë emaili të vlefshme."
    if not enabled():
        return 503, "Njoftimet me email nuk janë aktive ende."
    now = time.time()
    with _lock:
        hits = [t for t in _recent.get(ip, []) if now - t < 3600]
        if len(hits) >= PER_IP_HOUR:
            return 429, "Shumë kërkesa. Provo përsëri pas pak."
        _recent[ip] = hits + [now]
    it = lookup_item(item)
    if not it:
        return 404, "Ky produkt nuk u gjet."
    price = it["min_price"]
    with _lock, con() as c:
        rows = c.execute("SELECT item, confirmed, token FROM subs WHERE lower(email) = lower(?)", (email,)).fetchall()
        if len(rows) >= PER_EMAIL and item not in {r["item"] for r in rows}:
            return 400, f"Mund të ndjekësh deri në {PER_EMAIL} produkte me një email."
        known = next((r for r in rows if r["item"] == item), None)
        confirmed = any(r["confirmed"] for r in rows)  # this address already confirmed once: no second confirmation
        token = known["token"] if known else secrets.token_urlsafe(24)
        c.execute("""INSERT INTO subs (email, item, title, size, currency, price, last_price, token, confirmed, created)
                     VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(email, item) DO UPDATE SET price=excluded.price,
                     last_price=excluded.last_price, title=excluded.title""",
                  (email, item, it["title"], it.get("size"), it["currency"], price, price, token, int(confirmed),
                   datetime.now().isoformat(timespec="seconds")))
    if confirmed:
        return 200, f"Gati. Të shkruajmë te {email} kur {it['title']} të kushtojë më pak se {lek(price, it['currency'])}."
    link = f"{BASE}/njoftim/konfirmo?t={token}"
    stop_url = f"{BASE}/njoftim/ndalo?t={token}"
    e = html.escape
    ok = send(email, "Konfirmo njoftimin e çmimit në shporta", page("Konfirmo që do njoftime për këtë produkt", f"""
<p>Dikush (shpresojmë ti) kërkoi njoftim në shporta.app kur bie çmimi i <b>{e(it['title'])}</b>{f" ({e(it['size'])})" if it.get('size') else ""}.
Sot kushton më pak <b>{lek(price, it['currency'])}</b>.</p>
<p><a href="{e(link)}" style="display:inline-block;background:#7B4DFF;color:#fff;text-decoration:none;padding:12px 20px;border-radius:999px;font-weight:700">Po, më njofto</a></p>
<p style="color:#6E6A7C;font-size:14px">Nëse nuk e kërkove ti, injoroje këtë email: pa konfirmim nuk të shkruajmë më, dhe adresa fshihet pas 7 ditësh.</p>"""), stop_url)
    if not ok:
        return 502, "Emaili nuk u dërgua. Provo përsëri pas pak."
    return 200, f"Të dërguam një email te {email}. Hap linkun aty për ta konfirmuar."


def confirm(token):
    with _lock, con() as c:
        r = c.execute("SELECT email, title FROM subs WHERE token = ?", (token or "",)).fetchone()
        if not r:
            return None
        c.execute("UPDATE subs SET confirmed = 1 WHERE lower(email) = lower(?)", (r["email"],))
        return dict(r)


def stop(token):
    """Stops this product's alerts; the email's footer link with ?all=1 stops every alert for the address."""
    with _lock, con() as c:
        r = c.execute("SELECT email, title FROM subs WHERE token = ?", (token or "",)).fetchone()
        if not r:
            return None
        c.execute("DELETE FROM subs WHERE token = ?", (token,))
        return dict(r)


def stop_all(token):
    with _lock, con() as c:
        r = c.execute("SELECT email FROM subs WHERE token = ?", (token or "",)).fetchone()
        if not r:
            return None
        n = c.execute("DELETE FROM subs WHERE lower(email) = lower(?)", (r["email"],)).rowcount
        return {"email": r["email"], "count": n}


def check(seed_db, log=print):
    """After the nightly rebuild: write to each confirmed address whose products are now cheaper than when we last
    told them. Only an in-stock price counts, in the same currency, for the same product and size (the item id)."""
    if not DB.exists():
        return
    if not enabled():
        log("alerts: RESEND_API_KEY not set, nothing sent")
        return
    seed = sqlite3.connect(f"file:{seed_db}?mode=ro", uri=True)
    with con() as c:
        c.execute("DELETE FROM subs WHERE confirmed = 0 AND created < ?", ((datetime.now() - timedelta(days=7)).isoformat(),))
        subs = c.execute("SELECT * FROM subs WHERE confirmed = 1").fetchall()
    by_email = {}
    for s in subs:
        r = seed.execute("SELECT min_price, currency, in_stock_shops FROM items WHERE id = ?", (s["item"],)).fetchone()
        if not r or not r[2] or r[1] != s["currency"]:
            continue
        now = r[0]
        if now < (s["last_price"] or s["price"]) - 0.005:
            by_email.setdefault(s["email"], []).append((s, now))
    seed.close()
    sent = 0
    e = html.escape
    for email, drops in by_email.items():
        rows = "".join(f"""<tr><td style="padding:10px 0;border-bottom:1px solid #E6E3EE">
<a href="{BASE}/produkt/{e(s['item'])}" style="color:#14121F;font-weight:700">{e(s['title'])}</a>{f" <span style='color:#6E6A7C'>{e(s['size'])}</span>" if s['size'] else ""}<br>
<span style="background:#C6F432;padding:2px 8px;border-radius:6px;font-weight:700">{lek(now, s['currency'])}</span>
<span style="color:#6E6A7C"> ishte {lek(s['last_price'] or s['price'], s['currency'])}</span>
<br><a href="{BASE}/njoftim/ndalo?t={e(s['token'])}" style="color:#6E6A7C;font-size:13px">Mos më njofto më për këtë</a></td></tr>""" for s, now in drops)
        first = drops[0][0]
        subject = (f"Ra çmimi: {first['title'][:60]}" if len(drops) == 1 else f"Ra çmimi i {len(drops)} produkteve që ndjek")
        body = page("Çmimi ra" if len(drops) == 1 else f"Ra çmimi i {len(drops)} produkteve", f"""
<p>Çmimi më i lirë në stok sot, në dyqanet online shqiptare që krahason shporta:</p><table style="width:100%;border-collapse:collapse">{rows}</table>
<p><a href="{BASE}/produkt/{e(first['item'])}" style="display:inline-block;background:#7B4DFF;color:#fff;text-decoration:none;padding:12px 20px;border-radius:999px;font-weight:700">Shiko ku kushton më lirë</a></p>
<p style="font-size:13px;color:#6E6A7C"><a href="{BASE}/njoftim/ndalo?t={e(first['token'])}&amp;all=1" style="color:#6E6A7C">Ndalo të gjitha njoftimet</a></p>""")
        if send(email, subject, body, f"{BASE}/njoftim/ndalo?t={first['token']}&all=1"):
            sent += 1
            with con() as c:
                for s, now in drops:
                    c.execute("UPDATE subs SET last_price = ?, last_sent = ? WHERE id = ?",
                              (now, datetime.now().isoformat(timespec="seconds"), s["id"]))
        time.sleep(0.6)  # Resend allows a few requests per second
    log(f"alerts: {len(subs)} followed, {sent} emails sent")
