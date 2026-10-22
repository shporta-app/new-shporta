"""maxoptika.com (Albanian store /sq, prices in ALL).

Listings are rendered in the browser by InstantSearch backed by Typesense Cloud. The listing page itself embeds the
search-only key and host (`bj8chqdzwi5kl1v3p-1.a1.typesense.net`, collection `products`, query_by name,sku,model,
sort product_order:asc). We call that same public search endpoint (`/collections/products/documents/search`, GET,
250 per page) through a scrape.py Client for the Typesense host, so robots.txt (404 there = allowed), the PhiaALBot
UA and the delay still apply. Prices come from `prices.ALL` (price = list, offerPrice = what the shop charges),
exactly as the /sq listing displays them. Product URL is /sq/product/<slug>, as built by the page's hit template.
The key/host are re-read from a live listing page each run, so a rotated key is picked up.
"""
import importlib.util
import re
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_scrape", Path(__file__).resolve().parent.parent / "scrape.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)

LISTING = "/sq/shop/syze-dielli/gucci"
PER_PAGE = 250


def _config(client):
    html = client.get(LISTING).text
    key = re.search(r'apiKey:\s*"([^"]+)"', html)
    host = re.search(r'host:\s*"([^"]+\.typesense\.net)"', html)
    if not (key and host):
        raise RuntimeError("Typesense config not found on listing page")
    return key.group(1), host.group(1)


def scrape(client, max_pages):
    key, host = _config(client)
    ts = S.Client("https://" + host)
    ts.delay = max(ts.delay, client.delay)
    page = 1
    while page <= max_pages:
        r = ts.get("/collections/products/documents/search", headers={"X-TYPESENSE-API-KEY": key}, params={
            "q": "*", "query_by": "name,sku,model", "sort_by": "product_order:asc", "per_page": PER_PAGE, "page": page})
        if r.status_code != 200:
            break
        data = r.json()
        hits = data.get("hits") or []
        if not hits:
            break
        for h in hits:
            d = h.get("document") or {}
            p = ((d.get("prices") or {}).get("ALL") or {})
            price = S.num(p.get("offerPrice")) or None
            if not price or not d.get("slug"):
                continue
            reg = S.num(p.get("price"))
            stock = d.get("stock")
            yield dict(
                external_id=str(d.get("id") or d.get("sku")), url=f"{client.base}/sq/product/{d['slug']}",
                title=d.get("name"), brand=d.get("brand"), category_raw=" / ".join(x for x in (d.get("category"), d.get("gender")) if x),
                image=d.get("image"), gtin=d.get("barcode") or None, sku=d.get("sku"), currency="ALL",
                price=price, regular_price=reg if reg and reg > price else price,
                in_stock=int(stock > 0) if isinstance(stock, (int, float)) else None,
            )
        if page * PER_PAGE >= int(data.get("found") or 0):
            break
        page += 1
