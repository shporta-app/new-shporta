"""fragrances.al (wesell.al storefront, Next.js; not Magento, no public GraphQL).

Product URLs come from /sitemap/products*.xml (Albanian /products/... URLs only, the /en/ and /it/
copies are the same items). Each page carries schema.org Product JSON-LD (name, brand, image,
currency, offers) and the product record in the Next.js payload, including its size variants:
    "variants":[{"id":"PcNOw0yCmJ","sku":"PA-252-30ML","size":30,"label":"30 ml","price":1900,"originalPrice":2200,"stock":-1}, ...]
One row per variant, titled "<name> - <size label>", external_id = variant SKU (fallback: variant id).
Simple products get one row with their size from the product record ("size"/"sizeLabel").
"""
import json
import re

from scrape import jsonld_products, num, strip_html


def _product_urls(c):
    roots = [u for u in c.sitemaps] or [c.base + "/sitemap.xml"]
    idx = []
    for root in roots:
        r = c.get(root)
        if r.status_code == 200:
            idx += [u for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text) if "/sitemap/products" in u]
    seen = []
    for sm in idx:
        r = c.get(sm)
        if r.status_code != 200:
            continue
        for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text):
            if re.match(r"https://[^/]+/products/", u) and u not in seen:
                seen.append(u)
    return seen


def _record(h, mpn):
    """The product record from the Next.js payload: (price, size, sizeLabel, originalPrice, variants)."""
    i = h.find(f'"internalCode":"{mpn}"') if mpn else -1
    if i < 0:
        return None
    m = None
    for m in re.finditer(r'"price":([\d.]+),"size":([\d.]+|null),"sizeLabel":"([^"]*)"', h[max(0, i - 8000):i]):
        pass
    orig = re.search(r'"originalPrice":([\d.]+|null),"internalCode"', h[i - 60:i + 20])
    j = h.find('"variants":', i)
    variants = []
    if 0 <= j < i + 3000:
        try:
            variants, _ = json.JSONDecoder().raw_decode(h, j + len('"variants":'))
        except ValueError:
            variants = []
    return dict(
        price=num(m.group(1)) if m else None,
        size=None if not m or m.group(2) == "null" else m.group(2),
        size_label=m.group(3) if m else "",
        original=num(orig.group(1)) if orig and orig.group(1) != "null" else None,
        variants=variants or [],
    )


def _fmt_size(size):
    if size in (None, "", "null"):
        return None
    s = str(size)
    return (s[:-2] if s.endswith(".0") else s) + " ml"


def scrape(client, max_pages):
    c = client
    for n, url in enumerate(_product_urls(c)):
        if n >= max_pages:
            return
        r = c.get(url)
        if r.status_code != 200:
            continue
        html = r.text
        prods = list(jsonld_products(html))
        if not prods:
            continue
        p = prods[0]
        name = strip_html(p.get("name"))
        brand = p.get("brand")
        brand = brand.get("name") if isinstance(brand, dict) else brand
        img = p.get("image")
        img = img[0] if isinstance(img, list) and img else img
        offers = p.get("offers") or {}
        currency = offers.get("priceCurrency") if isinstance(offers, dict) else None
        mpn = p.get("mpn") or p.get("sku")
        rec = _record(html.replace('\\"', '"'), mpn) or {}
        base = dict(url=url, brand=brand if isinstance(brand, str) else None, category_raw="Parfume",
                    image=img if isinstance(img, str) else None, gtin=p.get("gtin13") or p.get("gtin"), currency=currency or "ALL")
        variants = rec.get("variants") or []
        if variants:
            for v in variants:
                price = num(v.get("price"))
                if not price:
                    continue
                label = v.get("label") or _fmt_size(v.get("size"))
                orig = num(v.get("originalPrice"))
                yield dict(base, external_id=str(v.get("sku") or v.get("id")),
                           title=f"{name} - {label}" if label else name, sku=v.get("sku"),
                           price=price, regular_price=orig if orig and orig > price else price,
                           in_stock=int(v.get("stock", -1) != 0))
        else:
            # Simple product: the price comes from the JSON-LD offer (what the page shows).
            o = offers.get("offers")[0] if isinstance(offers, dict) and offers.get("offers") else offers
            price = num(o.get("price") or o.get("lowPrice")) if isinstance(o, dict) else None
            if not price:
                continue
            label = rec.get("size_label") or _fmt_size(rec.get("size"))
            orig = rec.get("original")
            sku = p.get("sku") or mpn
            yield dict(base, external_id=str(sku or url), title=f"{name} - {label}" if label else name, sku=sku,
                       price=price, regular_price=orig if orig and orig > price else price,
                       in_stock=int("InStock" in str(o.get("availability", "InStock"))))
