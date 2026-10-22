"""elixir.al (Astro storefront, perfumery).

Product URLs: /produkt/<slug>-<6 hex> from the sitemap. JSON-LD gives name/brand/image but for multi-size
products only an AggregateOffer (low/high), so sizes and prices come from the embedded product record:
    "variants":[{"pid":"fcfefdc6-...","label":"50ML","price":7500,"was":null,"soldOut":false,...}, ...]
The page also embeds neighbouring products ("vicini"), so only variants whose pid starts with the URL's
6-hex suffix are used. One row per size: "<name> - 50ML", external_id = "<pid>-<label>".
"""
import json
import re

from scrape import jsonld_products, num, sitemap_urls, strip_html


def scrape(client, max_pages):
    c = client
    urls = []
    for root in c.sitemaps or [c.base + "/sitemap.xml"]:
        urls += [u for u in sitemap_urls(c, root) if "/produkt/" in u]
    urls = list(dict.fromkeys(urls))
    for n, url in enumerate(urls):
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
        currency = offers.get("priceCurrency") or "ALL"
        suffix = url.rstrip("/").rsplit("-", 1)[-1].lower()
        h = html.replace('\\"', '"')
        rows = {}
        for m in re.finditer(r'"variants":\[', h):
            try:
                vs, _ = json.JSONDecoder().raw_decode(h, m.end() - 1)
            except ValueError:
                continue
            for v in vs:
                if not isinstance(v, dict) or not str(v.get("pid", "")).lower().startswith(suffix):
                    continue
                price = num(v.get("price"))
                if not price:
                    continue
                label = (v.get("label") or v.get("option") or "").strip()
                if v.get("tester"):
                    label = (label + " Tester").strip()
                was = num(v.get("was")) if isinstance(v.get("was"), (int, float)) else None
                key = f'{v["pid"]}-{label}'
                rows[key] = dict(external_id=key, url=url, title=f"{name} - {label}" if label else name,
                                 brand=brand if isinstance(brand, str) else None, category_raw="Parfume",
                                 image=img if isinstance(img, str) else None, gtin=None, sku=v.get("pid"),
                                 currency=currency, price=price, regular_price=was if was and was > price else price,
                                 in_stock=int(not v.get("soldOut")))
            if rows:
                break
        if rows:
            yield from rows.values()
        elif offers.get("@type") == "Offer" and num(offers.get("price")):
            price = num(offers.get("price"))
            yield dict(external_id=url.rsplit("/", 1)[-1], url=url, title=name, brand=brand if isinstance(brand, str) else None,
                       category_raw="Parfume", image=img if isinstance(img, str) else None, gtin=None, sku=None,
                       currency=currency, price=price, regular_price=price,
                       in_stock=int("InStock" in str(offers.get("availability", "InStock"))))
