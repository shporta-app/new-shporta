"""pelinku.com (PrestaShop 1.7, prices in Lek).

The sitemap is from 2019 and lists categories only, so: collect category links (`/<id>-<slug>`) from the
homepage menu, page through each category (`?page=N`) to collect product links (`/<cat>/<id>-<slug>.html`),
then read each product page's `data-product` JSON (PrestaShop's own product model: name, price_amount,
regular_price_amount, reference, ean13, quantity).
"""
import json
import re
from html import unescape


def scrape(client, max_pages):
    fetched = 0
    home = client.get("/").text
    fetched += 1
    base = re.escape(client.base)
    cats = list(dict.fromkeys(re.findall(rf'href="({base}/\d+-[^"/?#]+)"', home)))
    products = {}
    for cat in cats:
        page = 1
        while fetched < max_pages:
            r = client.get(cat if page == 1 else f"{cat}?page={page}")
            fetched += 1
            if r.status_code != 200:
                break
            links = re.findall(rf'href="({base}/[^"/]+/(\d+)-[^"#?]+\.html)', r.text)
            new = [(u, pid) for u, pid in links if pid not in products]
            for u, pid in new:
                products[pid] = u
            if not new or f"page={page + 1}" not in r.text:
                break
            page += 1
    for pid, url in products.items():
        if fetched >= max_pages:
            return
        r = client.get(url)
        fetched += 1
        if r.status_code != 200:
            continue
        m = re.search(r'data-product="([^"]+)"', r.text)
        if not m:
            continue
        try:
            d = json.loads(unescape(m.group(1)))
        except ValueError:
            continue
        price = d.get("price_amount")
        if not price:
            continue
        reg = d.get("regular_price_amount") if d.get("has_discount") else None
        cover = d.get("cover") or {}
        img = ((cover.get("bySize") or {}).get("large_default") or {}).get("url") or (cover.get("large") or {}).get("url")
        yield dict(
            external_id=str(d.get("id_product") or pid), url=url, title=unescape(d.get("name") or "").strip(),
            brand=d.get("manufacturer_name") or None, category_raw=d.get("category_name"), image=img,
            gtin=d.get("ean13") or None, sku=d.get("reference") or None, currency="ALL", price=float(price),
            regular_price=float(reg) if reg and float(reg) > float(price) else float(price),
            in_stock=int(d.get("availability") == "available" or (d.get("quantity") or 0) > 0),
        )
