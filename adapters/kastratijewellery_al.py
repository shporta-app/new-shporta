"""Kastrati Jewellery (WooCommerce Store API, EUR). Many items show "Cmimi sipas kerkeses" (price on
request) on the live page while the API still carries a number; those are skipped because the shop
does not publish that price. Everything else follows scrape.scrape_woocommerce."""
import importlib.util
import re
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_common", Path(__file__).resolve().parent / "_phia_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)
S = C.S
ON_REQUEST = re.compile(r"sipas\s+k\S*rkes|on request|kpor-price", re.I)


def scrape(client, max_pages):
    for page in range(1, max_pages + 1):
        r = client.get(f"/wp-json/wc/store/v1/products?per_page=100&page={page}")
        if r.status_code in (400, 404):
            break
        r.raise_for_status()
        items = r.json()
        if not items:
            break
        for p in items:
            if ON_REQUEST.search(p.get("price_html") or ""):
                continue
            pr = p.get("prices") or {}
            unit = 10 ** int(pr.get("currency_minor_unit", 0) or 0)
            price = S.num(pr.get("price"))
            if not price:
                continue
            reg = S.num(pr.get("regular_price"))
            yield dict(
                external_id=str(p["id"]), url=p.get("permalink"), title=S.strip_html(p.get("name")),
                brand=", ".join(b["name"] for b in p.get("brands", [])) or None,
                category_raw=", ".join(S.strip_html(x["name"]) for x in p.get("categories", [])),
                image=(p.get("images") or [{}])[0].get("src"), gtin=None, sku=p.get("sku") or None,
                currency=pr.get("currency_code"), price=price / unit, regular_price=(reg / unit) if reg else price / unit,
                in_stock=int(bool(p.get("is_in_stock"))),
            )
        if page >= int(r.headers.get("X-WP-TotalPages", page) or page):
            break
