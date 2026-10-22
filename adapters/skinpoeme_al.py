"""skinpoeme.al (custom K-beauty shop). Same as the JSON-LD adapter, but only the Albanian /shop/ pages:
the /en/shop/ copies carry the same SKU priced in EUR, which overwrote the ALL rows."""
import re

from scrape import jsonld_products, num, sitemap_urls, strip_html


def scrape(client, max_pages):
    c = client
    urls = []
    for root in c.sitemaps or [c.base + "/sitemap.xml"]:
        urls += [u for u in sitemap_urls(c, root) if re.match(r"https://[^/]+/shop/[^/?#]+", u)]
    for n, url in enumerate(dict.fromkeys(urls)):
        if n >= max_pages:
            return
        r = c.get(url)
        if r.status_code != 200:
            continue
        for p in jsonld_products(r.text):
            offers = p.get("offers") or {}
            offers = offers if isinstance(offers, list) else [offers]
            # Each page lists the same item twice: an ALL offer and a EUR offer. Keep the ALL one.
            all_ = [o for o in offers if isinstance(o, dict) and o.get("priceCurrency") == "ALL"]
            offers = all_[:1] or offers[:1]
            for i, o in enumerate(offers):
                price = num(o.get("price")) if isinstance(o, dict) else None
                if not price:
                    continue
                brand = p.get("brand")
                brand = brand.get("name") if isinstance(brand, dict) else brand
                img = p.get("image")
                img = img[0] if isinstance(img, list) and img else img
                yield dict(external_id=str(p.get("sku") or f"{url}#{i}"), url=url, title=strip_html(p.get("name")),
                           brand=brand if isinstance(brand, str) else None, category_raw=None,
                           image=img if isinstance(img, str) else None, gtin=p.get("gtin13") or p.get("gtin"),
                           sku=p.get("sku"), currency=o.get("priceCurrency"), price=price, regular_price=price,
                           in_stock=int("InStock" in str(o.get("availability", "InStock"))))
            break
