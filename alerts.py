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
                 confirmed INTEGER DEFAULT 0, created TEXT, last_sent TEXT, image TEXT, UNIQUE(email, item))""")
    if "image" not in {r[1] for r in c.execute("PRAGMA table_info(subs)")}:  # a database from before the photo
        c.execute("ALTER TABLE subs ADD COLUMN image TEXT")
    return c


def lek(n, cur="ALL"):
    if cur == "EUR":
        return f"€{n:.2f}"
    if cur and cur != "ALL":
        return f"{n:.2f} {cur}"
    return f"{round(n):,}".replace(",", " ") + " L"


def send(to, subject, body_html, body_text, stop_url):
    """One email through Resend's API, as HTML and plain text. True when Resend accepted it."""
    req = urllib.request.Request("https://api.resend.com/emails", method="POST", data=json.dumps({
        "from": SENDER, "to": [to], "subject": subject, "html": body_html, "text": body_text,
        "reply_to": os.environ.get("ALERT_REPLY_TO") or None,
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


# ------------------------------------------------------------------ email design
# Email clients ignore most CSS: tables, inline styles, web-safe fonts, PNG images (Gmail drops SVG).
INK, PAPER, SOFT, LINE, MUTED, VIOLET, LIME = "#14121F", "#FFFFFF", "#F4F2F9", "#E6E3EE", "#6E6A7C", "#7B4DFF", "#C6F432"
FONT = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
e = html.escape


def button(url, label):
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:26px 0 6px"><tr>'
            f'<td style="background:{VIOLET};border-radius:999px">'
            f'<a href="{e(url)}" style="display:inline-block;padding:14px 26px;font:700 16px {FONT};color:#FFFFFF;'
            f'text-decoration:none;border-radius:999px">{e(label)}</a></td></tr></table>')


def product_card(title, size, image, url, price_html):
    pic = (f'<img src="{e(image)}" width="88" height="88" alt="" style="display:block;width:88px;height:88px;'
           f'object-fit:contain;background:#FFFFFF;border:1px solid {LINE};border-radius:12px">') if image else \
          f'<div style="width:88px;height:88px;background:{SOFT};border-radius:12px"></div>'
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
  style="border:1px solid {LINE};border-radius:16px;margin:18px 0 0"><tr>
  <td width="112" style="padding:14px 0 14px 14px;vertical-align:top"><a href="{e(url)}">{pic}</a></td>
  <td style="padding:14px 16px;vertical-align:top;font:15px/1.45 {FONT};color:{INK}">
    <a href="{e(url)}" style="color:{INK};text-decoration:none;font-weight:700">{e(title)}</a>
    {f'<div style="color:{MUTED};font-size:13px;margin-top:2px">{e(size)}</div>' if size else ""}
    <div style="margin-top:10px">{price_html}</div></td></tr></table>"""


def layout(preheader, heading, intro, body, why, stop_url):
    """The frame of every email: logo band, white card, footer saying why it came and how to stop it."""
    return f"""<!doctype html><html lang="sq"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"><title>{e(heading)}</title></head>
<body style="margin:0;padding:0;background:{SOFT};-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{SOFT}">{e(preheader)}&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{SOFT}"><tr><td align="center" style="padding:28px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px">
  <tr><td style="background:{INK};border-radius:18px 18px 0 0;padding:18px 24px">
    <a href="{BASE}/" style="text-decoration:none"><img src="{BASE}/assets/icon-192.png" width="34" height="34" alt=""
      style="vertical-align:middle;border-radius:8px;border:0"><span style="vertical-align:middle;margin-left:10px;
      font:800 22px {FONT};color:#FFFFFF;letter-spacing:-.3px">shporta</span></a></td></tr>
  <tr><td style="background:{PAPER};padding:30px 28px 30px;border-radius:0 0 18px 18px;font:16px/1.55 {FONT};color:{INK}">
    <h1 style="margin:0 0 10px;font:800 24px/1.25 {FONT};color:{INK};letter-spacing:-.3px">{e(heading)}</h1>
    <p style="margin:0;color:#3D3950">{intro}</p>
    {body}
  </td></tr>
  <tr><td style="padding:22px 28px 0;font:12px/1.6 {FONT};color:{MUTED}">
    {why}<br>Çmimet janë ato që dyqanet online publikojnë në faqet e tyre, të kontrolluara çdo natë. Kontrollo gjithmonë
    çmimin dhe madhësinë te dyqani para se të blesh.<br><br>
    <a href="{e(stop_url)}" style="color:{MUTED}">Ndalo njoftimet</a> &nbsp;·&nbsp;
    <a href="{BASE}/privatesia" style="color:{MUTED}">Privatësia</a> &nbsp;·&nbsp;
    <a href="{BASE}/" style="color:{MUTED}">shporta.app</a><br>
    shporta krahason çmimet e dyqaneve online në Shqipëri. Nuk shesim asgjë.</td></tr>
</table></td></tr></table></body></html>"""


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
        c.execute("""INSERT INTO subs (email, item, title, size, currency, price, last_price, token, confirmed, created, image)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(email, item) DO UPDATE SET price=excluded.price,
                     last_price=excluded.last_price, title=excluded.title, image=excluded.image""",
                  (email, item, it["title"], it.get("size"), it["currency"], price, price, token, int(confirmed),
                   datetime.now().isoformat(timespec="seconds"), it.get("image")))
    if confirmed:
        return 200, f"Gati. Të shkruajmë te {email} kur {it['title']} të kushtojë më pak se {lek(price, it['currency'])}."
    ok = send_confirmation(email, it, price, token)
    if not ok:
        return 502, "Emaili nuk u dërgua. Provo përsëri pas pak."
    return 200, f"Të dërguam një email te {email}. Hap linkun aty për ta konfirmuar."


def send_confirmation(email, it, price, token):
    link = f"{BASE}/njoftim/konfirmo?t={token}"
    stop_url = f"{BASE}/njoftim/ndalo?t={token}"
    url = f"{BASE}/produkt/{it['id']}"
    cur = it["currency"]
    shops = it.get("in_stock_shops") or 0
    card = product_card(it["title"], it.get("size"), it.get("image"), url,
                        f'<span style="font:800 20px {FONT};color:{INK}">{lek(price, cur)}</span>'
                        f'<span style="color:{MUTED};font-size:13px"> &nbsp;çmimi më i lirë sot'
                        f'{f" nga {shops} dyqane" if shops > 1 else ""}</span>')
    body = card + button(link, "Po, më njofto kur bie çmimi") + f"""
    <p style="margin:18px 0 0;font-size:14px;color:{MUTED}">Pas konfirmimit, kontrollojmë çmimin çdo natë në të gjitha dyqanet që krahasojmë
    dhe të shkruajmë vetëm kur bie: i njëjti produkt, në të njëjtën madhësi, në stok.</p>
    <p style="margin:12px 0 0;font-size:14px;color:{MUTED}">Nuk e kërkove ti? Injoroje këtë email. Pa konfirmim nuk të shkruajmë më,
    dhe adresa fshihet pas 7 ditësh.</p>"""
    html_body = layout(f"Një hap: konfirmo dhe të njoftojmë kur {it['title'][:50]} të kushtojë më pak.",
                       "Konfirmo njoftimin e çmimit",
                       "Kërkove të të njoftojmë kur bie çmimi i këtij produkti. Shtyp butonin për ta aktivizuar.",
                       body, "Ke marrë këtë email sepse kjo adresë u shkrua te shporta.app për njoftimin e çmimit.", stop_url)
    size = f" ({it['size']})" if it.get("size") else ""
    text = (f"Konfirmo njoftimin e çmimit\n\n{it['title']}{size}\nSot: {lek(price, cur)} (çmimi më i lirë)\n\n"
            f"Po, më njofto: {link}\n\nNuk e kërkove ti? Injoroje këtë email; adresa fshihet pas 7 ditësh.\n\nshporta.app")
    return send(email, f"Konfirmo njoftimin: {it['title'][:60]}", html_body, text, stop_url)


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
            by_email.setdefault(s["email"], []).append({"sub": s, "now": now, "was": s["last_price"] or s["price"]})
    seed.close()
    sent = 0
    seed = sqlite3.connect(f"file:{seed_db}?mode=ro", uri=True)
    for email, drops in by_email.items():
        if send_drops(email, drops, seed):
            sent += 1
            with con() as c:
                for d in drops:
                    c.execute("UPDATE subs SET last_price = ?, last_sent = ? WHERE id = ?",
                              (d["now"], datetime.now().isoformat(timespec="seconds"), d["sub"]["id"]))
        time.sleep(0.6)  # Resend allows a few requests per second
    seed.close()
    log(f"alerts: {len(subs)} followed, {sent} emails sent")


def send_drops(email, drops, seed):
    """One email for every product of this address that got cheaper, the biggest saving first."""
    drops.sort(key=lambda d: d["now"] - d["was"])
    cards, lines = [], []
    for d in drops:
        s, cur = d["sub"], d["sub"]["currency"]
        shop = seed.execute("""SELECT shop FROM products WHERE item_id = ? AND in_compare = 1 AND in_stock = 1 AND currency = ?
                               ORDER BY price LIMIT 1""", (s["item"], cur)).fetchone()
        shop = shop[0].removeprefix("www.") if shop else None
        pct = round((d["was"] - d["now"]) / d["was"] * 100)
        url = f"{BASE}/produkt/{s['item']}"
        where = f'<div style="font-size:13px;color:{MUTED};margin-top:2px">Më lirë sot te {e(shop)}</div>' if shop else ""
        cards.append(product_card(s["title"], s["size"], s["image"], url, f"""
          <span style="font:800 22px {FONT};color:{INK};background:{LIME};padding:2px 10px;border-radius:8px">{lek(d['now'], cur)}</span>
          <span style="color:{MUTED};font-size:14px;text-decoration:line-through;margin-left:6px">{lek(d['was'], cur)}</span>
          <div style="margin-top:8px;font-size:14px;color:#2F7D32;font-weight:700">Kursen {lek(d['was'] - d['now'], cur)} (−{pct}%)</div>
          {where}
          <div style="margin-top:8px"><a href="{e(url)}" style="font-size:14px;color:{VIOLET};font-weight:700;text-decoration:none">Shiko çmimet në të gjitha dyqanet</a>
          <span style="color:{LINE}"> | </span><a href="{BASE}/njoftim/ndalo?t={e(s['token'])}" style="font-size:13px;color:{MUTED}">mos më njofto më për këtë</a></div>"""))
        size = f" ({s['size']})" if s["size"] else ""
        at = f", më lirë te {shop}" if shop else ""
        lines.append(f"{s['title']}{size}: {lek(d['now'], cur)}, ishte {lek(d['was'], cur)} "
                     f"(kursen {lek(d['was'] - d['now'], cur)}){at}\n{url}")
    first = drops[0]["sub"]
    stop_url = f"{BASE}/njoftim/ndalo?t={first['token']}&all=1"
    total = sum(d["was"] - d["now"] for d in drops if d["sub"]["currency"] == first["currency"])
    if len(drops) == 1:
        subject = f"Ra çmimi: {first['title'][:55]} tani {lek(drops[0]['now'], first['currency'])}"
        heading, intro = "Çmimi ra", "Produkti që ndjek kushton më pak sot se herën e fundit që të shkruam."
    else:
        subject = f"Ra çmimi i {len(drops)} produkteve që ndjek"
        heading = f"Ra çmimi i {len(drops)} produkteve"
        intro = f"Bashkë kursen deri në <b>{lek(total, first['currency'])}</b> krahasuar me herën e fundit që të shkruam."
    body = "".join(cards) + button(f"{BASE}/produkt/{first['item']}", "Shiko ku kushton më lirë") + f"""
    <p style="margin:16px 0 0;font-size:13px;color:{MUTED}">Krahasojmë vetëm të njëjtin produkt në të njëjtën madhësi, në stok.
    Çmimi mund të ndryshojë gjatë ditës: kontrolloje te dyqani.</p>"""
    html_body = layout(f"{first['title'][:60]}: tani {lek(drops[0]['now'], first['currency'])}", heading, intro, body,
                       "Ke marrë këtë email sepse kërkove njoftim për këtë produkt te shporta.app.", stop_url)
    text = f"{heading}\n\n" + "\n\n".join(lines) + f"\n\nNdalo të gjitha njoftimet: {stop_url}\n\nshporta.app"
    return send(email, subject, html_body, text, stop_url)
