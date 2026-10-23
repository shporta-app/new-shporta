"""Balkan Sport (balkansport.com.al): JSON-LD is a schema.org ProductGroup whose hasVariant entries
(one per colour) carry the price in offers.priceSpecification. The sitemap lists every product in
/sq/ and /en/; we read only /sq/products/ pages. One row per colour variant (sku).

The shop appends every viewed product id to a `recent_product_ids` cookie; after ~650 pages the Cookie header is
too large and every request gets HTTP 400 (earlier runs "stopped" at ~1,000 rows because of this). We drop that
cookie before each request; the session cookie is kept."""
import importlib.util
import json
import re
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_common", Path(__file__).resolve().parent / "_phia_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)
S = C.S


def _blocks(html):
    for b in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            d = json.loads(b.strip())
        except ValueError:
            continue
        yield from (d.get("@graph") or [d]) if isinstance(d, dict) else d


def _rows(client, max_pages):
    urls = [u for u in S.sitemap_urls(client, client.base + "/sitemap_blk.xml.gz") if "/sq/products/" in u]
    for url in list(dict.fromkeys(urls))[:max_pages]:
        for ck in [ck for ck in client.s.cookies if ck.name == "recent_product_ids"]:
            client.s.cookies.clear(ck.domain, ck.path, ck.name)
        r = client.get(url)
        if r.status_code != 200:
            continue
        for g in _blocks(r.text):
            if not isinstance(g, dict) or g.get("@type") not in ("ProductGroup", "Product"):
                continue
            variants = g.get("hasVariant") or [g]
            brand = g.get("brand")
            brand = brand.get("name") if isinstance(brand, dict) else brand
            for v in variants:
                o = v.get("offers") or {}
                o = o[0] if isinstance(o, list) and o else o
                ps = o.get("priceSpecification") or {}
                ps = ps[0] if isinstance(ps, list) and ps else ps
                price = S.num(ps.get("price") if isinstance(ps, dict) else None) or S.num(o.get("price"))
                if not price:
                    continue
                img = v.get("image")
                img = img.get("url") if isinstance(img, dict) else img
                title = S.strip_html(v.get("name") or g.get("name"))
                if v.get("color"):
                    title = f"{title} - {v['color']}"
                yield dict(
                    external_id=str(v.get("sku") or g.get("productGroupID") or url) + (f"/{v.get('color')}" if v.get("color") else ""),
                    url=url, title=title, brand=brand, category_raw=None,
                    image=img if isinstance(img, str) else None, gtin=v.get("gtin13") or v.get("gtin"), sku=v.get("sku"),
                    currency=(ps.get("priceCurrency") if isinstance(ps, dict) else None) or o.get("priceCurrency"),
                    price=price, regular_price=price, in_stock=int("InStock" in str(o.get("availability", "InStock"))),
                )


def scrape(client, max_pages):
    yield from C.buffered(_rows(client, max_pages))
