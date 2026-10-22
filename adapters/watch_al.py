"""Iglisi Watch (watch.al, Durres): one page per watch in sq/en/it; we read only /sq/shop/ pages.
JSON-LD offers carry EUR as the main price plus an explicit ALL priceSpecification; we store the
shop's own ALL price when present, otherwise the EUR price."""
import importlib.util
import re
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_common", Path(__file__).resolve().parent / "_phia_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)
_scrape = C.S


def scrape(client, max_pages):
    yield from C.buffered(_rows(client, max_pages))


def _rows(client, max_pages):
    xml = client.get("/sitemap.xml").text
    urls = [u for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml) if "/sq/shop/" in u and "/brand/" not in u]
    for url in list(dict.fromkeys(urls))[:max_pages]:
        r = client.get(url)
        if r.status_code != 200:
            continue
        found = list(_scrape.jsonld_products(r.text))
        if len(found) != 1:  # listing / collection pages carry many products; read each watch's own page
            continue
        for p in found:
            o = p.get("offers") or {}
            o = o[0] if isinstance(o, list) and o else o
            if not isinstance(o, dict):
                continue
            price, cur = _scrape.num(o.get("price")), o.get("priceCurrency")
            for spec in o.get("priceSpecification") or []:
                if isinstance(spec, dict) and spec.get("priceCurrency") == "ALL" and _scrape.num(spec.get("price")):
                    price, cur = _scrape.num(spec["price"]), "ALL"
            if not price:
                continue
            brand = p.get("brand")
            brand = brand.get("name") if isinstance(brand, dict) else brand
            img = p.get("image")
            img = img[0] if isinstance(img, list) and img else img
            yield dict(
                external_id=str(p.get("sku") or url), url=url, title=_scrape.strip_html(p.get("name")), brand=brand,
                category_raw="Ora", image=img if isinstance(img, str) else None, gtin=p.get("gtin13") or p.get("gtin"),
                sku=p.get("sku"), currency=cur, price=price, regular_price=price,
                in_stock=int("InStock" in str(o.get("availability", "InStock"))),
            )
