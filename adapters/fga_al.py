"""fga.al (Fashion Group Albania: Mango, Springfield, Cortefiel, Women'secret, Tom Tailor, Okaidi, Prenatal...).

Nuxt front end over WooCommerce; the public Store API answers on fga.al/wp-json/wc/store/v1/products, but the
home page has no wp-content markers, so auto-detection picks jsonld. Some late pages of 100 products time out
server-side (>30 s), so we request 50 per page and retry a timed-out page once before moving on.
Same row shape as scrape.py's woocommerce adapter.
"""
import requests

from html import unescape
import re


def _strip(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def scrape(client, max_pages):
    page, total = 1, None
    while page <= max_pages and (total is None or page <= total):
        r = None
        for _ in range(2):
            try:
                r = client.get(f"/wp-json/wc/store/v1/products?per_page=50&page={page}")
                break
            except requests.Timeout:
                r = None
        if r is None:
            print(f"  fga.al: page {page} timed out twice, skipped", flush=True)
            page += 1
            continue
        if r.status_code in (400, 404):
            break
        r.raise_for_status()
        total = int(r.headers.get("X-WP-TotalPages", page) or page)
        items = r.json()
        if not items:
            break
        for p in items:
            pr = p.get("prices") or {}
            unit = 10 ** int(pr.get("currency_minor_unit", 0) or 0)
            try:
                price = float(pr.get("price") or 0) / unit
                reg = float(pr.get("regular_price") or 0) / unit
            except ValueError:
                continue
            if not price:
                continue
            yield dict(
                external_id=str(p["id"]), url=p.get("permalink"), title=_strip(p.get("name")),
                brand=", ".join(b["name"] for b in p.get("brands", [])) or None,
                category_raw=", ".join(_strip(x["name"]) for x in p.get("categories", [])),
                image=(p.get("images") or [{}])[0].get("src"), gtin=None, sku=p.get("sku") or None,
                currency=pr.get("currency_code"), price=price, regular_price=reg or price,
                in_stock=int(bool(p.get("is_in_stock"))),
            )
        page += 1
