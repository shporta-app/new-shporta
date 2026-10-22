"""iriscosmetic.al (Iris Cosmetic, custom shop, prices in Lek).

The sitemap lists every product twice (/en/product/... and /sq/product/...), so only the Albanian URLs are read,
each page's schema.org Product (name, Offer price/priceCurrency/availability) via scrape.py's JSON-LD parser.
The product slug is the external id (both language versions share it).
"""
import importlib.util
import re
from html import unescape
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_common", Path(__file__).resolve().parent / "_phia_common.py")
_C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_C)
S = _C.S


def _rows(client, max_pages):
    r = client.get("/sitemap.xml")
    urls = [unescape(u) for u in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", r.text) if "/sq/product/" in u]
    for n, url in enumerate(dict.fromkeys(urls)):
        if n >= max_pages:
            return
        p = client.get(url)
        if p.status_code != 200:
            continue
        for d in S.jsonld_products(p.text):
            o = d.get("offers") or {}
            o = o[0] if isinstance(o, list) and o else o
            price = S.num(o.get("price")) if isinstance(o, dict) else None
            if not price:
                continue
            img = d.get("image")
            img = img[0] if isinstance(img, list) and img else img
            brand = d.get("brand")
            brand = brand.get("name") if isinstance(brand, dict) else brand
            yield dict(
                external_id=url.rstrip("/").rsplit("/", 1)[-1], url=url, title=S.strip_html(d.get("name")),
                brand=brand if isinstance(brand, str) else None, category_raw=d.get("category") if isinstance(d.get("category"), str) else None,
                image=img if isinstance(img, str) else None, gtin=d.get("gtin13") or d.get("gtin") or None, sku=d.get("sku"),
                currency=o.get("priceCurrency") or "ALL", price=price, regular_price=price,
                in_stock=int("InStock" in str(o.get("availability", "InStock"))),
            )
            break


def scrape(client, max_pages):
    yield from _C.buffered(_rows(client, max_pages))
