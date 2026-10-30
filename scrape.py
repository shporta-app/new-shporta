"""Shared scraper for Albanian fashion / beauty / accessories shops.

Usage:
    python scrape.py <domain> --category beauty [--max-pages 3000]

Adapters, tried in this order:
    shopify      /products.json (public storefront feed)
    woocommerce  /wp-json/wc/store/v1/products (public Store API)
    jsonld       product URLs from the sitemap, prices read from schema.org Product markup

Rules (same as Shporta):
    - obey robots.txt for every URL and its Crawl-delay (minimum 1 s between requests)
    - stop at a bot challenge, 403 or 429; never work around a WAF
    - never invent data: a product without a readable price is skipped
"""
import argparse
import gzip
import json
import re
import sqlite3
import sys
import time
import urllib.robotparser
from datetime import date, datetime, timezone
from html import unescape
from pathlib import Path

import requests

UA = "PhiaALBot/0.1 (+price comparison for Albanian shoppers)"
HERE = Path(__file__).parent
DB_PATH = HERE / "data" / "phia.db"
MIN_DELAY = 1.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS shops (
  domain TEXT PRIMARY KEY, name TEXT, category TEXT, platform TEXT, currency TEXT,
  status TEXT, note TEXT, products INTEGER, last_scraped TEXT
);
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY, shop TEXT NOT NULL, external_id TEXT NOT NULL,
  url TEXT, title TEXT, brand TEXT, category_raw TEXT, image TEXT, gtin TEXT, sku TEXT,
  currency TEXT, price REAL, regular_price REAL, in_stock INTEGER,
  first_seen TEXT, last_seen TEXT,
  UNIQUE (shop, external_id)
);
CREATE TABLE IF NOT EXISTS prices (
  product_id INTEGER NOT NULL, day TEXT NOT NULL, price REAL, regular_price REAL,
  PRIMARY KEY (product_id, day)
);
CREATE INDEX IF NOT EXISTS products_gtin ON products(gtin);
CREATE TABLE IF NOT EXISTS page_sizes (url TEXT PRIMARY KEY, size TEXT, checked TEXT);
"""


class Blocked(Exception):
    """The shop refused us (robots, WAF, 403/429). We stop, we don't retry around it."""


class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.rp = urllib.robotparser.RobotFileParser()
        self.sitemaps = []
        try:
            r = self.s.get(self.base + "/robots.txt", timeout=20)
            ok = r.status_code == 200 and "<html" not in r.text[:500].lower()
            self.rp.parse([l for l in r.text.splitlines() if l.strip()] if ok else [])
            self.sitemaps = (self.rp.site_maps() or []) if ok else []
        except requests.RequestException:
            self.rp.parse([])
        self.delay = max(MIN_DELAY, float(self.rp.crawl_delay(UA) or self.rp.crawl_delay("*") or 0))
        self._last = 0.0

    def allowed(self, url):
        return self.rp.can_fetch(UA, url)

    def get(self, url, **kw):
        return self._request("get", url, **kw)

    def post(self, url, **kw):
        """Same rules as get(): robots.txt check, Crawl-delay, stop on 403/429/challenge."""
        return self._request("post", url, **kw)

    def _request(self, method, url, **kw):
        if not url.startswith("http"):
            url = self.base + url
        if not self.allowed(url):
            raise Blocked(f"robots.txt disallows {url}")
        # a slow or overloaded shop (timeout, 502/503/504) gets time, then at most two more tries further apart:
        # waiting for a busy server, never a way around a refusal (403/429/challenge stop us at once)
        for attempt, pause in enumerate((0, 30, 90)):
            time.sleep(pause)
            wait = self._last + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = getattr(self.s, method)(url, timeout=(15, 60), **kw)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 2:
                    raise
                continue
            if r.status_code in (403, 429) or re.search(r"<title>Just a moment|cf-chl-opt|safeline|sgcaptcha", r.text[:5000], re.I):
                raise Blocked(f"{r.status_code} / bot challenge at {url}")
            if r.status_code in (502, 503, 504) and attempt < 2:
                continue
            return r


def num(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    v = str(v).strip().replace("\xa0", "").replace(" ", "")
    # "1.250,00" / "1,250.00" / "1250"
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", v):
        v = v.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", v):
        v = v.replace(",", "")
    else:
        v = v.replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def strip_html(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


# a shop's own field for the size ("Sasia", "Vëllimi", "Madhësia", "Zgjidhni dozimin", "Pesha", "Size", "Volume")
SIZE_FIELD = re.compile(r"sasi|v[eë]llim|madh[eë]si|dozim|pesh|size|volum|kapacitet|weight|gramatur|ml\b", re.I)


def sizes_in(fields=(), text=""):
    """Every size a shop states for a product: in its size fields (each with one value) and in the text."""
    from match import SIZE_RE, fold, size_of
    out = set()
    for name, values in fields:
        if SIZE_FIELD.search(name or "") and len(values) == 1:
            out |= {size_of(m) for m in SIZE_RE.finditer(fold(values[0] or ""))}
    # in running text only a size with its label counts ("Formati: 50ml", "Sasia: 200 ml"): a description also
    # names doses ("1-2 lugë, 15-30 ml"), samples and other products. No cosmetic comes in more than 5 l / 5 kg.
    return out | {x for m in size_label_re().finditer(fold(strip_html(text))) if (x := size_of(m))[0] <= 5000}


def size_label_re():
    """A size written with its label: "Sasia: 50ml", "Formati 100 ml", "Zgjidhni dozimin: 30ml", "📏 Madhësia 70ml"."""
    from match import SIZE_RE
    return re.compile(r"\b(?:sasia|sasi|vellimi|volumi|formati|madhesia|paketimi|permbajtja|dozimin?|size|volume|"
                      r"net wt|contenido|contenu|inhalt)\b\s*[:\-]?\s*" + SIZE_RE.pattern)


def with_size(title, fields=(), text=""):
    """The product's name with the size the shop states for it, when the name itself has none. Only when everything
    the shop states agrees on one size: two sizes ("30 ml and 50 ml") is no size. Many shops write "Sasia: 50 ml"
    next to the name instead of in it; without this they looked like shops that don't state the size."""
    from match import SIZE_RE, fold, size_label
    if SIZE_RE.search(fold(title or "")):
        return title
    found = sizes_in(fields, text)
    return f"{title} - {size_label(*found.pop())}" if len(found) == 1 else title


def page_size(html, title=""):
    """The size a product's own page states ("50 ml"), or None. Read only from the product itself: its structured
    data, its information table (not the shipping weight), the block that starts at its name (the line under it,
    the price, "Formati: 50ml") and its description, never from "related products". The page's name must be the
    product's (a shop's link can point at another product), and every place must agree on one size."""
    from match import fold, size_label
    body = re.sub(r"<script(?![^>]*ld\+json).*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    want = {w for w in re.findall(r"[a-z0-9]{3,}", fold(title))}
    names = lambda m: set(re.findall(r"[a-z0-9]{3,}", fold(strip_html(m.group(1)))))
    # the heading that names this product: the theme's product title (an <h1>, sometimes an <h2>/<h3>), else an <h1>
    # (a theme may put the shop's slogan in another <h1>); never the headings of "related products"
    heads = [m for m in re.finditer(r"<h([1-3])([^>]*)>(.*?)</h\1>", body, re.S | re.I)
             if "product_title" in m.group(2) or "product-title" in m.group(2) or m.group(1) == "1"]
    heads.sort(key=lambda m: "product_title" not in m.group(2) and "product-title" not in m.group(2))
    names = lambda m: set(re.findall(r"[a-z0-9]{3,}", fold(strip_html(m.group(3)))))
    h1 = next((m for m in heads if not title or (want and len(want & names(m)) >= 0.6 * len(want))), None)
    if title and not h1:
        return None  # the page shows another product, or we can't tell which one it shows
    from match import SIZE_RE, size_of
    found = set()
    # 1. the shop's own size fields: structured data, the information table (not the shipping weight)
    for p in list(jsonld_products(html))[:1]:
        props = [(x.get("name"), [str(x.get("value") or "")]) for x in p.get("additionalProperty") or [] if isinstance(x, dict)]
        if isinstance(p.get("size"), str):
            props.append(("size", [p["size"]]))
        found |= sizes_in(props)
    rows = re.findall(r'<tr[^>]*class="[^"]*woocommerce-product-attributes-item(?![^"]*--(?:weight|dimensions))[^"]*"[^>]*>\s*'
                      r'<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>', html, re.S | re.I)
    found |= sizes_in([(strip_html(a), [strip_html(b)]) for a, b in rows])
    # 2. a size with its label in the product's own block ("Sasia: 50ml", "Formati: 50ml", "Zgjidhni dozimin: 50 ml")
    # 3. a size on the line right under the product's name ("Hidratues me Acid Azelaik 30ml")
    if h1:
        text = strip_html(body[h1.start():h1.start() + 40000])[:4000]
        end = re.search(r"related|upsell|cross-sell|recently|you may also|t[eë] ngjashme|best seller|produkte t[eë] tjera|"
                        r"mund t[eë] ju p[eë]lqej|klient[eë]t bleu", text, re.I)
        text = fold(text[:end.start()] if end else text)
        label = size_label_re()
        found |= {size_of(m) for m in label.finditer(text)}  # the size's two groups come first in the pattern
        name = fold(strip_html(h1.group(3)))
        after = text[len(name):len(name) + 160] if text.startswith(name) else ""
        after = re.split(r"\d[\d ,.]*\s*(?:l|lek|leke|all|eur|€)\b", after)[0]  # up to the price
        found |= {size_of(m) for m in SIZE_RE.finditer(after) if m.group(2) not in ("l", "lt")}
    # 4. the shop's full name of the product, where it carries the size ("… Kapsule me PDRN 30ml"): the breadcrumb's
    #    last step and the page's title, when they name this product; and a labelled size in the page's summary
    full = [strip_html(x) for x in re.findall(r'class="breadcrumb_last"[^>]*>(.*?)</', body, re.S | re.I)]
    full += [strip_html(x) for x in re.findall(r'"position":\s*\d+,\s*"name":\s*"([^"]+)"\s*\}\s*\]', html)[-1:]]
    for f in full:
        if want and len(want & set(re.findall(r"[a-z0-9]{3,}", fold(f)))) >= 0.8 * len(want):
            found |= {size_of(m) for m in SIZE_RE.finditer(fold(f)) if m.group(2) not in ("l", "lt")}
    for d in re.findall(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', html, re.I)[:1]:
        found |= {size_of(m) for m in label.finditer(fold(strip_html(d)))} if h1 else set()
    return size_label(*found.pop()) if len(found) == 1 else None


# ---------------------------------------------------------------- adapters

def scrape_shopify(c, max_pages):
    home = c.get("/").text
    m = re.search(r'Shopify\.currency\s*=\s*\{"active":"([A-Z]{3})"', home)
    currency = m.group(1) if m else None
    for page in range(1, max_pages + 1):
        r = c.get(f"/products.json?limit=250&page={page}")
        if r.status_code != 200:
            break
        products = r.json().get("products", [])
        if not products:
            break
        for p in products:
            img = (p.get("images") or [{}])[0].get("src")
            for v in p.get("variants", []):
                price = num(v.get("price"))
                if price is None:
                    continue
                title = p["title"] if v.get("title") in (None, "Default Title") else f'{p["title"]} - {v["title"]}'
                if len(p.get("variants", [])) == 1:
                    title = with_size(title, [(o.get("name"), o.get("values") or []) for o in p.get("options", [])], p.get("body_html"))
                yield dict(
                    external_id=str(v["id"]), url=f'{c.base}/products/{p["handle"]}?variant={v["id"]}',
                    title=title, brand=p.get("vendor"), category_raw=p.get("product_type") or ", ".join(p.get("tags", [])[:5]),
                    image=img, gtin=v.get("barcode") or None, sku=v.get("sku") or None, currency=currency,
                    price=price, regular_price=num(v.get("compare_at_price")) or price, in_stock=int(bool(v.get("available"))),
                )


def scrape_woocommerce(c, max_pages):
    for page in range(1, max_pages + 1):
        r = c.get(f"/wp-json/wc/store/v1/products?per_page=100&page={page}")
        if r.status_code == 400 or r.status_code == 404:
            break
        r.raise_for_status()
        items = r.json()
        if not items:
            break
        variable = {}
        for p in items:
            if p.get("type") == "variable" and p.get("variations"):
                # The parent only carries the lowest variant price ("880 L - 1 790 L"); use the variants instead.
                variable[p["id"]] = p
                continue
            row = _woo_row(p)
            if row:
                yield row
        yield from _woo_variations(c, variable)
        if page >= int(r.headers.get("X-WP-TotalPages", page) or page):
            break


def _woo_row(p, parent=None):
    pr = p.get("prices") or {}
    unit = 10 ** int(pr.get("currency_minor_unit", 0) or 0)
    price = num(pr.get("price"))
    if price is None or price == 0:
        return None
    reg = num(pr.get("regular_price"))
    base = parent or p
    title = strip_html(base.get("name"))
    if parent:
        # "Zgjidhni dozimin:: 50 ml, Ngjyra:: E kuqe" -> "50 ml, E kuqe"
        label = ", ".join(x.split("::")[-1].strip() for x in strip_html(p.get("variation") or "").split(", ") if x.strip())
        if label and label.lower() not in title.lower():
            title = f"{title} - {label}"
    if not parent:
        title = with_size(title, [(a.get("name"), [t.get("name") for t in a.get("terms") or []]) for a in p.get("attributes") or []],
                          f'{p.get("short_description") or ""} {p.get("description") or ""}')
    return dict(
        external_id=str(p["id"]), url=p.get("permalink") or base.get("permalink"), title=title,
        brand=", ".join(b["name"] for b in base.get("brands", [])) or None,
        category_raw=", ".join(strip_html(x["name"]) for x in base.get("categories", [])),
        image=((p.get("images") or base.get("images") or [{}])[0]).get("src"), gtin=None, sku=p.get("sku") or None,
        currency=pr.get("currency_code"), price=price / unit, regular_price=(reg / unit) if reg else price / unit,
        in_stock=int(bool(p.get("is_in_stock"))),
    )


def _woo_variations(c, parents):
    """Variants of up to 100 variable products per request (Store API: type=variation&parent=1,2,3)."""
    ids = list(parents)
    for i in range(0, len(ids), 20):
        chunk = ids[i:i + 20]
        for page in range(1, 50):
            r = c.get(f"/wp-json/wc/store/v1/products?type=variation&parent={','.join(map(str, chunk))}&per_page=100&page={page}")
            if r.status_code != 200:
                break
            items = r.json()
            if not isinstance(items, list) or not items:
                break
            for v in items:
                parent = parents.get(v.get("parent")) or next((parents[x] for x in chunk if any(
                    vv["id"] == v["id"] for vv in parents[x]["variations"])), None)
                row = _woo_row(v, parent)
                if row:
                    yield row
            if page >= int(r.headers.get("X-WP-TotalPages", page) or page):
                break


def sitemap_urls(c, url, depth=0):
    if depth > 3:
        return
    try:
        r = c.get(url)
    except (Blocked, requests.RequestException):
        return
    if r.status_code != 200:
        return
    body = r.content
    if url.endswith(".gz"):
        try:
            body = gzip.decompress(body)
        except OSError:
            pass
    text = body.decode("utf-8", "ignore")
    locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", text)
    if "<sitemapindex" in text:
        # Product sitemaps first; skip obvious non-product ones.
        locs.sort(key=lambda u: 0 if re.search(r"product|produkt", u, re.I) else 1)
        for loc in locs:
            if re.search(r"post-sitemap|page-sitemap|category|tag|author|blog|cms", loc, re.I):
                continue
            yield from sitemap_urls(c, unescape(loc), depth + 1)
    else:
        for loc in locs:
            yield unescape(loc)


def jsonld_products(html):
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
            elif isinstance(d, dict):
                t = d.get("@type")
                if t == "Product" or (isinstance(t, list) and "Product" in t):
                    yield d
                # hasVariant: a ProductGroup's per-size/colour Products, each with its own offer
                stack.extend(v for k, v in d.items() if k in ("@graph", "mainEntity", "itemListElement", "item", "hasVariant"))


def scrape_jsonld(c, max_pages):
    roots = c.sitemaps or [c.base + "/sitemap.xml", c.base + "/sitemap_index.xml"]
    seen = set()
    pages = 0
    for root in roots:
        for url in sitemap_urls(c, root):
            if pages >= max_pages:
                return
            if url in seen or not c.allowed(url) or re.search(r"\.(jpg|png|webp|pdf)$", url, re.I):
                continue
            seen.add(url)
            try:
                r = c.get(url)
            except requests.RequestException:
                continue
            pages += 1
            if r.status_code != 200:
                continue
            for p in jsonld_products(r.text):
                offers = p.get("offers") or {}
                if isinstance(offers, dict) and offers.get("@type") == "AggregateOffer":
                    if offers.get("offers"):
                        offers = offers["offers"]
                    elif num(offers.get("lowPrice")) != num(offers.get("highPrice") or offers.get("lowPrice")):
                        continue  # only a "from … to …" range: the price of a specific size is unknown
                    else:
                        offers = [offers]
                offers = offers if isinstance(offers, list) else [offers]
                for i, o in enumerate(offers):
                    if not isinstance(o, dict):
                        continue
                    price = num(o.get("price") or o.get("lowPrice"))
                    if not price:
                        continue
                    brand = p.get("brand")
                    brand = brand.get("name") if isinstance(brand, dict) else brand
                    img = p.get("image")
                    img = img[0] if isinstance(img, list) and img else img
                    img = img.get("url") if isinstance(img, dict) else img
                    ext = o.get("sku") or p.get("sku") or p.get("productID") or f"{url}#{i}"
                    props = [(x.get("name"), [str(x.get("value") or "")]) for x in p.get("additionalProperty") or [] if isinstance(x, dict)]
                    if isinstance(p.get("size"), str):
                        props.append(("size", [p["size"]]))
                    name = with_size(strip_html(p.get("name")), props, p.get("description") if len(offers) == 1 else "")
                    yield dict(
                        external_id=str(ext), url=o.get("url") or url, title=name,
                        brand=brand if isinstance(brand, str) else None, category_raw=p.get("category") if isinstance(p.get("category"), str) else None,
                        image=img if isinstance(img, str) else None,
                        gtin=p.get("gtin13") or p.get("gtin") or p.get("gtin8") or o.get("gtin13"),
                        sku=p.get("sku"), currency=o.get("priceCurrency"), price=price, regular_price=price,
                        in_stock=int("InStock" in str(o.get("availability", "InStock"))),
                    )


ADAPTERS = {"shopify": scrape_shopify, "woocommerce": scrape_woocommerce, "jsonld": scrape_jsonld}


def custom_adapter(domain):
    """adapters/<domain with dots as underscores>.py may define scrape(client, max_pages) for an odd site."""
    f = HERE / "adapters" / (domain.replace(".", "_").replace("-", "_") + ".py")
    if not f.exists():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location(f.stem, f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.scrape


def detect(c):
    html = c.get("/").text
    if re.search(r"cdn\.shopify\.com|Shopify\.theme", html):
        return "shopify"
    if re.search(r"wp-content|woocommerce", html, re.I) and c.allowed(c.base + "/wp-json/wc/store/v1/products"):
        r = c.get("/wp-json/wc/store/v1/products?per_page=1")
        if r.status_code == 200 and r.text.lstrip().startswith("["):
            return "woocommerce"
    return "jsonld"


# ---------------------------------------------------------------- storage

def db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=120)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def save(con, shop, rows, batch=200):
    """Buffer rows and write them in short transactions, so the write lock is never held while pages are
    being fetched (several scrapers share the DB)."""
    n = 0
    buf = []
    for r in rows:
        if not r.get("title") or not r.get("price"):
            continue
        buf.append(r)
        if len(buf) >= batch:
            n += _write(con, shop, buf)
            buf = []
            print(f"  {shop}: {n} saved", flush=True)
    if buf:
        n += _write(con, shop, buf)
    return n


def _write(con, shop, rows):
    for attempt in range(10):
        try:
            _write_once(con, shop, rows)
            return len(rows)
        except sqlite3.OperationalError as e:
            con.rollback()
            if "locked" not in str(e) or attempt == 9:
                raise
            time.sleep(2 + attempt * 2)


def _write_once(con, shop, rows):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    today = date.today().isoformat()
    for r in rows:
        con.execute(
            """INSERT INTO products (shop, external_id, url, title, brand, category_raw, image, gtin, sku, currency,
                                     price, regular_price, in_stock, first_seen, last_seen)
               VALUES (:shop,:external_id,:url,:title,:brand,:category_raw,:image,:gtin,:sku,:currency,
                       :price,:regular_price,:in_stock,:now,:now)
               ON CONFLICT(shop, external_id) DO UPDATE SET url=excluded.url, title=excluded.title, brand=excluded.brand,
                 category_raw=excluded.category_raw, image=excluded.image, gtin=excluded.gtin, sku=excluded.sku,
                 currency=excluded.currency, price=excluded.price, regular_price=excluded.regular_price,
                 in_stock=excluded.in_stock, last_seen=excluded.last_seen""",
            {**r, "shop": shop, "now": now},
        )
        pid = con.execute("SELECT id FROM products WHERE shop=? AND external_id=?", (shop, r["external_id"])).fetchone()[0]
        con.execute(
            "INSERT OR REPLACE INTO prices (product_id, day, price, regular_price) VALUES (?,?,?,?)",
            (pid, today, r["price"], r["regular_price"]),
        )
    con.commit()


def run(domain, category, platform=None, max_pages=3000):
    domain = domain.lower().removeprefix("https://").removeprefix("http://").strip("/")
    base = "https://" + domain
    try:
        base = re.match(r"https?://[^/]+", requests.get(base, headers={"User-Agent": UA}, timeout=20).url).group(0)
    except requests.RequestException as e:
        return record(domain, category, None, "down", type(e).__name__, 0)
    c = Client(base)
    con = db()
    try:
        custom = None if platform else custom_adapter(domain)
        platform = "custom" if custom else platform or detect(c)
        print(f"{domain}: platform={platform} delay={c.delay}s", flush=True)
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        known = dict(con.execute("SELECT url, size FROM page_sizes WHERE size IS NOT NULL AND url LIKE ?", (f"%{domain}%",)))
        rows = (custom or ADAPTERS[platform])(c, max_pages)
        rows = ({**r, "title": with_size(r["title"], [("size", [known[r.get("url")]])])} if r.get("title") and r.get("url") in known
                else r for r in rows)
        n = save(con, domain, rows)
        status, note = ("ok" if n else "no-products"), None
        if n and platform in ("woocommerce", "shopify"):
            # These feeds list the whole catalogue, so anything not seen in this complete run is gone
            # (or was replaced, e.g. a variable product now stored per variant).
            stale = "SELECT id FROM products WHERE shop=? AND last_seen < ?"
            for t in ("prices", "matches"):
                con.execute(f"DELETE FROM {t} WHERE product_id IN ({stale})", (domain, started))
            con.execute("DELETE FROM products WHERE shop=? AND last_seen < ?", (domain, started))
            con.commit()
    except Blocked as e:
        n, status, note = 0, "blocked", str(e)
    except Exception as e:  # keep going with other shops; the note says what broke
        n, status, note = con.execute("SELECT COUNT(*) FROM products WHERE shop=?", (domain,)).fetchone()[0], "error", f"{type(e).__name__}: {e}"[:300]
    con.close()
    return record(domain, category, platform, status, note, n)


def record(domain, category, platform, status, note, n):
    con = db()
    cur = con.execute("SELECT currency FROM products WHERE shop=? GROUP BY currency ORDER BY COUNT(*) DESC LIMIT 1", (domain,)).fetchone()
    con.execute(
        """INSERT INTO shops (domain, category, platform, currency, status, note, products, last_scraped)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(domain) DO UPDATE SET category=excluded.category, platform=excluded.platform,
             currency=excluded.currency, status=excluded.status, note=excluded.note, products=excluded.products,
             last_scraped=excluded.last_scraped""",
        (domain, category, platform, cur[0] if cur else None, status, note, n, datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    con.commit()
    con.close()
    print(f"{domain}: {status} - {n} products {('(' + note + ')') if note else ''}", flush=True)
    return status, n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("domains", nargs="+")
    ap.add_argument("--category", required=True, help="clothing | shoes | beauty | perfume | jewelry | accessories | sport | multi")
    ap.add_argument("--platform", choices=list(ADAPTERS))
    ap.add_argument("--max-pages", type=int, default=3000)
    a = ap.parse_args()
    for d in a.domains:
        run(d, a.category, a.platform, a.max_pages)
