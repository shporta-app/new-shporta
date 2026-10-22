"""inglot.al (PrestaShop 1.6, Inglot Albania, prices in Lek). No sitemap; robots.txt allows everything.

Category pages carry schema.org microdata per product (name, sku, gtin13, brand, offers.price/priceCurrency/url).
We walk every category linked from the home page, `?p=N` until a page adds no new product, and dedupe by the
product id in the URL. The listing price is the product's default price; shade variants are not split out.
"""
import re
from html import unescape

CAT = re.compile(r'href="(https://inglot\.al/\d+-[a-z0-9-]+)"')


def _meta(block, prop):
    m = re.search(rf'itemprop="{prop}"\s+(?:content|href)="([^"]*)"', block)
    return unescape(m.group(1)).strip() if m else None


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse(html):
    for b in html.split('class="product-container"')[1:]:
        b = b.split('class="product-container"')[0]
        url, name, price, cur = _meta(b, "url"), _meta(b, "name"), _num(_meta(b, "price")), _meta(b, "priceCurrency")
        m = re.search(r"/(\d+)-[^/#?]+$", url or "")
        if not (m and name and price and cur):
            continue  # no readable price -> skip
        yield dict(
            external_id=m.group(1), url=url, title=name, brand=_meta(b, "brand") or "INGLOT", category_raw=None,
            image=_meta(b, "image"), gtin=_meta(b, "gtin13"), sku=_meta(b, "sku"), currency=cur,
            price=price, regular_price=price, in_stock=int("InStock" in (_meta(b, "availability") or "InStock")),
        )


def scrape(client, max_pages):
    home = client.get("/").text
    cats = list(dict.fromkeys(CAT.findall(home)))
    seen, fetched = set(), 0
    for cat in cats:
        label = cat.rsplit("/", 1)[-1]
        for p in range(1, 200):
            if fetched >= max_pages:
                return
            r = client.get(cat if p == 1 else f"{cat}?p={p}")
            fetched += 1
            if r.status_code != 200:
                break
            rows = list(parse(r.text))
            new = [x for x in rows if x["external_id"] not in seen]
            for x in new:
                seen.add(x["external_id"])
                x["category_raw"] = label
                yield x
            if not new or f"p={p + 1}" not in r.text:
                break
