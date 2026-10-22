"""dimocenter.al (custom Next.js perfumery).

Product URLs: /products/<slug> from /sitemap.xml. Each page has schema.org Product JSON-LD (name, brand,
image, ALL price of the default size) and the product record in the Next.js payload with its sizes:
    "slug":"<slug>", ... "variants":[{"id":"...","label":"75 ML","price":15000,"compareAtPrice":"$undefined","inStock":true}]
One row per variant ("<name> - 75 ML", external_id = variant id). Related products on the same page
carry their own "variants", so only the record whose slug matches the URL is used.
"""
import json
import re

from scrape import jsonld_products, num, strip_html


def _variants(h, slug):
    for m in re.finditer(r'"variants":\[', h):
        before = h[max(0, m.start() - 20000):m.start()]
        slugs = re.findall(r'"slug":"([^"]+)"', before)
        if not slugs or slugs[-1] != slug:
            continue
        try:
            v, _ = json.JSONDecoder().raw_decode(h, m.end() - 1)
            return v
        except ValueError:
            return []
    return []


def scrape(client, max_pages):
    c = client
    r = c.get("/sitemap.xml")
    urls = list(dict.fromkeys(u for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text) if "/products/" in u))
    for n, url in enumerate(urls):
        if n >= max_pages:
            return
        r = c.get(url)
        if r.status_code != 200:
            continue
        prods = list(jsonld_products(r.text))
        if not prods:
            continue
        p = prods[0]
        name = strip_html(p.get("name"))
        brand = p.get("brand")
        brand = brand.get("name") if isinstance(brand, dict) else brand
        img = p.get("image")
        img = img[0] if isinstance(img, list) and img else img
        offer = p.get("offers") or {}
        offer = offer[0] if isinstance(offer, list) and offer else offer
        currency = offer.get("priceCurrency") or "ALL"
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        base = dict(url=url, brand=brand if isinstance(brand, str) else None, category_raw=None,
                    image=img if isinstance(img, str) else None, gtin=None, currency=currency)
        variants = _variants(r.text.replace('\\"', '"'), slug)
        if variants:
            for v in variants:
                price = num(v.get("price"))
                if not price:
                    continue
                cmp_ = v.get("compareAtPrice")
                cmp_ = num(cmp_) if isinstance(cmp_, (int, float)) else None
                label = (v.get("label") or "").strip()
                yield dict(base, external_id=str(v.get("id")), title=f"{name} - {label}" if label else name, sku=v.get("id"),
                           price=price, regular_price=cmp_ if cmp_ and cmp_ > price else price,
                           in_stock=int(bool(v.get("inStock"))))
        else:
            price = num(offer.get("price"))
            if not price:
                continue
            yield dict(base, external_id=str(p.get("sku") or url), title=name, sku=p.get("sku"), price=price,
                       regular_price=price, in_stock=int("InStock" in str(offer.get("availability", "InStock"))))
