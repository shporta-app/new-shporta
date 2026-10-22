"""vicino.al (Vicino Fashion Boutique, custom PHP shop, prices in Lek).

No schema.org markup and a partial sitemap, so: collect category ids from the homepage menu
(`NAME-<id>-C` links), page through `category.php?id=<id>&page=N` to collect product links (`...-<id>-i`),
then read each product page: `h1.product-title`, `.price-sales` (current price) and `.price-standard`
(price before discount, only shown on sale items).
"""
import re
from html import unescape


def _num(s):
    s = re.sub(r"[^\d.,]", "", s or "")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        s = re.sub(r"[.,]", "", s)
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def scrape(client, max_pages):
    fetched = 0
    home = client.get("/").text
    fetched += 1
    cats = list(dict.fromkeys(re.findall(r'href="[^"]*?-(\d+)-[cC]"', home)))
    products = {}
    for cid in cats:
        page = 1
        while fetched < max_pages:
            r = client.get(f"/category.php?id={cid}&page={page}")
            fetched += 1
            links = re.findall(r'href="([^"]*-(\d+)-i)"', r.text, re.I)
            new = [(u, pid) for u, pid in links if pid not in products]
            for u, pid in new:
                products[pid] = u if u.startswith("http") else client.base + "/" + u.lstrip("/")
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
        t = r.text
        title = re.search(r'<h1 class="product-title">\s*([^<]+)', t)
        sale = re.search(r'id="item-price">\s*([\d.,]+)\s*Lek', t)
        std = re.search(r'class="price-standard">\s*([\d.,]+)', t)
        price = _num(sale.group(1)) if sale else None
        if not (title and price):
            continue
        reg = _num(std.group(1)) if std else None
        code = re.search(r'class="product-code">\s*Kodi\s*:\s*([^<]+)', t)
        img = re.search(r'<meta property="og:image" content="([^"]+)"', t)
        cat = re.search(r'<li><a href="[^"]*-\d+-[cC]">([^<]+)</a></li>\s*<li class="active"', t)
        yield dict(
            external_id=pid, url=url, title=unescape(title.group(1)).strip(), brand=None,
            category_raw=cat.group(1) if cat else None, image=img.group(1) if img else None, gtin=None,
            sku=code.group(1).strip() if code else None, currency="ALL", price=price,
            regular_price=reg if reg and reg > price else price, in_stock=None,
        )
