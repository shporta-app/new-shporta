"""Notifications on the phone or computer (Web Push), like any app: "the price dropped" even when shporta is closed.

    key()                      the public key the browser needs to subscribe (GET /api/push/key)
    subscribe(sub, items, ip)  the browser's subscription and the products it follows (POST /api/push/subscribe);
                               sent again whenever the list changes, so it replaces the list we keep
    unsubscribe(endpoint)      the visitor turned notifications off (POST /api/push/unsubscribe): everything deleted
    check(seed_db)             nightly.py --server after the rebuild: a product cheaper than when we last told them
                               (or than the day they followed it) -> one notification per device

What we keep (data/alerts.db): the push address the browser gave us (a random address at Google/Mozilla/Apple/
Microsoft, no name, no email), the ids of the products followed and two prices. An address the push service says is
gone is deleted. The private key (data/push_vapid.pem) is made on the server the first time and never leaves it.

Standards: RFC 8030 (Web Push), RFC 8291 (message encryption, aes128gcm), RFC 8292 (VAPID). Only `cryptography`
(already on the server) beyond the standard library.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import struct
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import alerts

KEY_FILE = Path(os.environ.get("PUSH_KEY_FILE", Path(__file__).parent / "data" / "push_vapid.pem"))
CONTACT = "https://shporta.app/rreth"  # VAPID "sub": how a push service can reach us
# only the browsers' own push services: a subscription can't make the server send requests anywhere else
PUSH_HOSTS = ("fcm.googleapis.com", "android.googleapis.com", "push.services.mozilla.com", "notify.windows.com",
              "push.apple.com")
PER_DEVICE = 100     # products one device may follow (the list in the browser keeps 100)
PER_IP_HOUR = 30     # subscribe calls per address per hour (each change of the list sends one)
ITEM_ID = re.compile(r"[\w-]{1,20}")
_lock = threading.Lock()
_recent = {}
_key = None


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def private_key():
    """The server's VAPID key: made once, kept only on the server (readable by its own user only)."""
    global _key
    with _lock:
        if _key is None:
            if not KEY_FILE.exists():
                KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
                pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
                fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(pem)
            _key = serialization.load_pem_private_key(KEY_FILE.read_bytes(), None)
    return _key


def raw_public(k):
    return k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def key():
    return b64u(raw_public(private_key()))


def con():
    c = alerts.con()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS push_subs (id INTEGER PRIMARY KEY, endpoint TEXT UNIQUE NOT NULL, p256dh TEXT NOT NULL,
                                              auth TEXT NOT NULL, created TEXT, last_sent TEXT);
        CREATE TABLE IF NOT EXISTS push_items (sub INTEGER NOT NULL, item TEXT NOT NULL, title TEXT, currency TEXT,
                                               price REAL, last_price REAL, PRIMARY KEY (sub, item));
    """)
    return c


def valid_endpoint(url):
    u = urlparse(url or "")
    host = (u.hostname or "").lower()
    return u.scheme == "https" and len(url) <= 1000 and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def subscribe(sub, items, ip, lookup_item):
    """sub: the browser's PushSubscription as JSON. items: [{"id", "price"}] from the list in the browser, the price
    being the one on the day it was followed. We keep only items we know, in their own currency."""
    if not isinstance(sub, dict) or not isinstance(sub.get("keys"), dict):
        return 400, "Kërkesë e pavlefshme."
    endpoint, p256dh, auth = str(sub.get("endpoint", "")), str(sub["keys"].get("p256dh", "")), str(sub["keys"].get("auth", ""))
    try:
        ok = valid_endpoint(endpoint) and len(unb64u(p256dh)) == 65 and len(unb64u(auth)) == 16
    except ValueError:
        ok = False
    if not ok:
        return 400, "Ky shfletues nuk na dha një adresë njoftimesh të vlefshme."
    with _lock:
        now = time.time()
        hits = [t for t in _recent.get(ip, []) if now - t < 3600]
        if len(hits) >= PER_IP_HOUR:
            return 429, "Shumë kërkesa. Provo përsëri pas pak."
        _recent[ip] = hits + [now]
    wanted = {}
    for x in (items if isinstance(items, list) else [])[:PER_DEVICE]:
        iid = str((x or {}).get("id", ""))
        if not ITEM_ID.fullmatch(iid):
            continue
        it = lookup_item(iid)
        if not it:
            continue
        try:
            price = float(x.get("price"))
        except (TypeError, ValueError):
            price = None
        # never above today's price: a made-up high price would only bring a false "the price dropped"
        price = min(price, it["min_price"]) if price and price > 0 else it["min_price"]
        wanted[iid] = (it["title"], it["currency"], price)
    with con() as c:
        c.execute("INSERT INTO push_subs (endpoint, p256dh, auth, created) VALUES (?,?,?,?) ON CONFLICT(endpoint) "
                  "DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth",
                  (endpoint, p256dh, auth, datetime.now().isoformat(timespec="seconds")))
        sid = c.execute("SELECT id FROM push_subs WHERE endpoint = ?", (endpoint,)).fetchone()[0]
        have = {r["item"] for r in c.execute("SELECT item FROM push_items WHERE sub = ?", (sid,))}
        for gone in have - set(wanted):
            c.execute("DELETE FROM push_items WHERE sub = ? AND item = ?", (sid, gone))
        for iid, (title, cur, price) in wanted.items():
            if iid not in have:  # a product already followed keeps the price we last told them
                c.execute("INSERT INTO push_items (sub, item, title, currency, price) VALUES (?,?,?,?,?)",
                          (sid, iid, title, cur, price))
    return 200, f"Njoftimet janë aktive për {len(wanted)} produkte."


def unsubscribe(endpoint):
    with con() as c:
        r = c.execute("SELECT id FROM push_subs WHERE endpoint = ?", (str(endpoint),)).fetchone()
        if r:
            c.execute("DELETE FROM push_items WHERE sub = ?", (r[0],))
            c.execute("DELETE FROM push_subs WHERE id = ?", (r[0],))
    return 200, "Njoftimet u çaktivizuan. Adresa e këtij shfletuesi u fshi."


_tests = {}


def test(endpoint):
    """"Send a test notification": only to a device already subscribed, at most 3 an hour, so anyone can check that
    notifications reach their phone without waiting for a price to drop."""
    with con() as c:
        r = c.execute("SELECT endpoint, p256dh, auth FROM push_subs WHERE endpoint = ?", (str(endpoint),)).fetchone()
    if not r:
        return 404, "Njoftimet nuk janë aktive në këtë pajisje. Aktivizoji përsëri."
    with _lock:
        now = time.time()
        hits = [t for t in _tests.get(r["endpoint"], []) if now - t < 3600]
        if len(hits) >= 3:
            return 429, "Ke dërguar 3 njoftime provë këtë orë. Provo përsëri më vonë."
        _tests[r["endpoint"]] = hits + [now]
    status = send(dict(r), {"title": "shporta: njoftim provë",
                            "body": "Njoftimet punojnë. Kur bie çmimi i një produkti që ndjek, të njoftojmë kështu.",
                            "url": "/njoftime", "tag": "test"})
    if status in (404, 410):
        unsubscribe(r["endpoint"])
        return 410, "Kjo pajisje nuk i pranon më njoftimet. Aktivizoji përsëri."
    if not 200 <= status < 300:
        return 502, "Shërbimi i njoftimeve nuk u përgjigj. Provo përsëri pas pak."
    return 200, "U dërgua. Njoftimi duhet të shfaqet pas pak sekondash."


# ------------------------------------------------------------------ sending

def _hkdf(salt, ikm, info, length):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def encrypt(payload, p256dh, auth):
    """RFC 8291: the message encrypted for this one browser (only it can read it, not the push service)."""
    ua_public = unb64u(p256dh)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    as_key = ec.generate_private_key(ec.SECP256R1())
    as_public = raw_public(as_key)
    shared = as_key.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(unb64u(auth), shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # \x02: the last (only) record
    return salt + struct.pack(">IB", 4096, len(as_public)) + as_public + body


def vapid_header(endpoint):
    """RFC 8292: a short signed note "this is shporta.app" the push service checks against our public key."""
    u = urlparse(endpoint)
    claims = {"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": CONTACT}
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = b64u(json.dumps(claims, separators=(",", ":")).encode())
    r, s = decode_dss_signature(private_key().sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256())))
    jwt = f"{head}.{body}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={jwt}, k={key()}"


def send(sub, message):
    """One notification to one device. Returns the push service's answer: 201 sent, 404/410 the device is gone."""
    data = encrypt(json.dumps(message, ensure_ascii=False).encode(), sub["p256dh"], sub["auth"])
    req = urllib.request.Request(sub["endpoint"], data=data, method="POST", headers={
        "Authorization": vapid_header(sub["endpoint"]), "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream", "TTL": str(3 * 24 * 3600), "Urgency": "normal"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0


def message(drops):
    """What the notification says. One product: its name and both prices. Several: how many, and the list."""
    drops.sort(key=lambda d: d["now"] - d["was"])
    if len(drops) == 1:
        d = drops[0]
        return {"title": f"Ra çmimi: {d['title'][:80]}",
                "body": f"Tani {alerts.lek(d['now'], d['currency'])}, ishte {alerts.lek(d['was'], d['currency'])}. "
                        f"Më i liri në {d['shops']} dyqane.", "url": f"/produkt/{d['item']}", "tag": f"drop-{d['item']}"}
    first = drops[0]
    return {"title": f"Ra çmimi te {len(drops)} produkte që ndjek",
            "body": f"{first['title'][:60]}: {alerts.lek(first['now'], first['currency'])} (ishte "
                    f"{alerts.lek(first['was'], first['currency'])}), dhe {len(drops) - 1} të tjera.",
            "url": "/njoftime", "tag": "drops"}


SEND_FROM, SEND_UNTIL = 9, 21  # local time: price drops found at night wait for the morning, so no phone buzzes at 3 am


def morning(seed_db, log=print):
    """Runs inside the site (server.py), in its own thread: once a day, between 09:00 and 21:00, send the price drops
    of the night. The day it last ran is kept in a file, so a restart neither skips the day nor sends twice."""
    done = alerts.DB.parent / "push_last.txt"
    while True:
        now = datetime.now()
        today = now.date().isoformat()
        last = done.read_text().strip() if done.exists() else ""
        if SEND_FROM <= now.hour < SEND_UNTIL and last != today:
            done.write_text(today)
            try:
                check(seed_db, log)
            except Exception as e:
                log(f"push failed: {type(e).__name__}: {e}")
        time.sleep(60)


def check(seed_db, log=print):
    """Each morning, after the nightly rebuild (see morning): one notification per device whose products are now cheaper than when we last told
    it. Same rule as the emails: an in-stock price, same currency, same product and size (the item id)."""
    if not alerts.DB.exists():
        return
    seed = sqlite3.connect(f"file:{seed_db}?mode=ro", uri=True)
    with con() as c:
        subs = c.execute("SELECT * FROM push_subs").fetchall()
        rows = c.execute("SELECT * FROM push_items").fetchall()
    by_sub = {}
    for r in rows:
        it = seed.execute("SELECT min_price, currency, in_stock_shops FROM items WHERE id = ?", (r["item"],)).fetchone()
        if not it or not it[2] or it[1] != r["currency"]:
            continue
        was = r["last_price"] or r["price"]
        if it[0] < was - 0.005:
            by_sub.setdefault(r["sub"], []).append({"item": r["item"], "title": r["title"], "currency": r["currency"],
                                                    "now": it[0], "was": was, "shops": it[2]})
    seed.close()
    sent = gone = 0
    for s in subs:
        drops = by_sub.get(s["id"])
        if not drops:
            continue
        status = send(s, message(drops))
        with con() as c:
            if status in (404, 410):  # the visitor removed the app or turned notifications off in the browser
                c.execute("DELETE FROM push_items WHERE sub = ?", (s["id"],))
                c.execute("DELETE FROM push_subs WHERE id = ?", (s["id"],))
                gone += 1
            elif 200 <= status < 300:
                sent += 1
                c.execute("UPDATE push_subs SET last_sent = ? WHERE id = ?", (datetime.now().isoformat(timespec="seconds"), s["id"]))
                for d in drops:
                    c.execute("UPDATE push_items SET last_price = ? WHERE sub = ? AND item = ?", (d["now"], s["id"], d["item"]))
            else:
                log(f"push: {urlparse(s['endpoint']).hostname} answered {status}")
        time.sleep(0.2)
    log(f"push: {len(subs)} devices, {len(rows)} products followed, {sent} notifications sent, {gone} devices gone")
