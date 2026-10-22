"""farmaciababamusta.com (Farmacia Babamusta, OpenCart, prices in Lek).

No sitemap (the google_sitemap feed is empty), no schema.org markup, so: category ids (`path=`) from the
homepage menu, page through `route=product/category&path=<p>&limit=100&page=N` to collect product ids, then read
each product page: `h1.product-name`, `.product-price` (current), `.old-price` (before discount),
"Kodi i Produktit" (an EAN barcode on most items) and "Brands".
"""
import re
from html import unescape


def _num(s):
    s = re.sub(r"[^\d.,]", "", s or "")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        s = re.sub(r"[.,]", "", s)
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _text(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def scrape(client, max_pages):
    fetched = 0
    home = client.get("/").content.decode("utf-8", "ignore")
    fetched += 1
    paths = list(dict.fromkeys(re.findall(r'route=product/category(?:&amp;|&)path=([\d_]+)', home)))
    # Leaf categories hold the products; parents may repeat them, which the id set dedupes.
    products = {}
    for p in paths:
        page = 1
        while fetched < max_pages:
            r = client.get(f"/index.php?route=product/category&path={p}&limit=100&page={page}")
            fetched += 1
            if r.status_code != 200:
                break
            ids = re.findall(r'route=product/product(?:&amp;|&)(?:path=[\d_]+(?:&amp;|&))?product_id=(\d+)', r.text)
            new = [i for i in dict.fromkeys(ids) if i not in products]
            for i in new:
                products[i] = p
            if not new or f"page={page + 1}" not in r.text.replace("&amp;", "&"):
                break
            page += 1
    for pid in products:
        if fetched >= max_pages:
            return
        url = f"{client.base}/index.php?route=product/product&product_id={pid}"
        r = client.get(url)
        fetched += 1
        if r.status_code != 200:
            continue
        t = r.content.decode("utf-8", "ignore")
        title = re.search(r'<h1 class="product-name">(.*?)</h1>', t, re.S)
        box = re.search(r'<div class="product-price-box">(.*?)</div>', t, re.S)
        if not (title and box):
            continue
        price = re.search(r'class="product-price">([^<]+)', box.group(1))
        price = _num(price.group(1)) if price else None
        if not price:
            continue
        old = re.search(r'class="old-price">([^<]+)', box.group(1))
        old = _num(old.group(1)) if old else None
        code = re.search(r'Kodi i Produktit:</span>\s*([^<\s]+)', t)
        brand = re.search(r'Brands</span>\s*(?:<a[^>]*>)?\s*([^<]+)', t)
        img = re.search(r'<meta property="og:image" content="([^"]+)"', t) or re.search(r'class="thumbnail[^"]*"[^>]*href="([^"]+)"', t)
        stock = re.search(r'Disponueshm[^<]*</span>\s*([^<]+)', t)
        code = code.group(1).strip() if code else None
        yield dict(
            external_id=pid, url=url, title=_text(title.group(1)), brand=_text(brand.group(1)) if brand else None,
            category_raw=None, image=img.group(1) if img else None,
            gtin=code if code and re.fullmatch(r"\d{8,14}", code) else None, sku=code, currency="ALL",
            price=price, regular_price=old if old and old > price else price,
            in_stock=(0 if re.search(r"out|jasht", stock.group(1), re.I) else 1) if stock else None,
        )
