"""essenzestudio.live (custom PHP perfumery; "inspired by" own-brand perfumes, orders online or via WhatsApp).

Product URLs: /product/<slug> from /sitemap.xml (the /en/ copies are skipped). JSON-LD gives name, sku,
image and an AggregateOffer (low/high only), so per-size prices are read from the size buttons:
    <div id="sizes-spray" ...><button class="size-btn" data-price="1500" data-old="1500" ...>10 ML</button>
    <div id="sizes-oil" ...>  (Vajore / oil format)
One row per format+size, e.g. "ES Perfume M40 Frymëzuar nga Noir Extreme - Extrait 50 ML".
"""
import re

from scrape import jsonld_products, num, strip_html

FORMATS = {"spray": "Extrait", "oil": "Vajore"}


def scrape(client, max_pages):
    c = client
    r = c.get("/sitemap.xml")
    urls = list(dict.fromkeys(u for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text) if re.match(r"https://[^/]+/product/", u)))
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
        offers = p.get("offers") or {}
        currency = offers.get("priceCurrency") or "ALL"
        in_stock = int("InStock" in str(offers.get("availability", "InStock")))
        sku = p.get("sku") or url.rsplit("/", 1)[-1]
        brand = p.get("brand")
        brand = brand.get("name") if isinstance(brand, dict) else brand
        base = dict(url=url, brand=brand, category_raw="Parfume (inspired-by)", image=p.get("image"), gtin=None,
                    sku=sku, currency=currency, in_stock=in_stock)
        blocks = re.split(r'<div id="sizes-', html)[1:]
        found = False
        for b in blocks:
            fmt = re.match(r"(\w+)", b).group(1)
            b = b.split("</div>", 1)[0]
            for price, old, label in re.findall(
                    r'<button[^>]*class="size-btn[^"]*"[^>]*data-price="([\d.]+)"\s+data-old="([\d.]*)"[^>]*>\s*([^<]+?)\s*<', b):
                price, old = num(price), num(old)
                if not price:
                    continue
                found = True
                f = FORMATS.get(fmt, fmt.capitalize())
                yield dict(base, external_id=f"{sku}-{fmt}-{label.replace(' ', '').lower()}",
                           title=f"{name} - {f} {label}", price=price,
                           regular_price=old if old and old > price else price)
        if not found and offers.get("@type") == "Offer" and num(offers.get("price")):
            price = num(offers.get("price"))
            yield dict(base, external_id=str(sku), title=name, price=price, regular_price=price)
