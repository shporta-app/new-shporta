"""foleja.al (Shopware 6 marketplace).

Product pages carry no schema.org JSON-LD, and the sitemaps list ~700k URLs (too many to fetch one by one).
Instead we read the public category listing pages (`/<Category>/?p=N`, 48 products per page), which show
title, link, current price and list price for every product. `/listing` (the AJAX widget) is disallowed in
robots.txt and is not used. Clothing (`Veshje`) goes first.
"""
import re
from html import unescape

CATEGORIES = [
    "Veshje", "Nena-Bebe", "Sport-Natyre", "Kozmetike-Kujdesi-Personal", "Teknologji", "Shtepi-Zyre",
    "Argetim-Lodra-dhe-Muzike", "Kujdesi-per-kafshe", "Libra-Artikuj-per-Zyre-Shkolle", "Proteina-Ushqim-Pije",
    "Veture-Mjete-Ndertim",
]


def _num(s):
    s = re.sub(r"[^\d.,]", "", s or "")
    if not s:
        return None
    # Listing pages mix "1,210" (current price) and "2.400" (list price); both are thousands separators.
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        s = re.sub(r"[.,]", "", s)
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+,\d{1,2}", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+\.\d{1,2}", s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _text(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse(html, category):
    boxes = html.split('class="card product-box')[1:]
    for b in boxes:
        pid = re.search(r'name="product-id"\s+value="([0-9a-f]{32})"', b)
        name = re.search(r'name="product-name"\s+value="([^"]*)"', b)
        link = re.search(r'<a href="(https://www\.foleja\.al/[^"]+)"\s+title="[^"]*"\s+class="product-image-link', b) \
            or re.search(r'href="(https://www\.foleja\.al/[^"]+)"\s+class="product-name"', b)
        price = re.search(r'class="whole-original-price[^"]*">(.*?)</span>\s*</span>', b, re.S) \
            or re.search(r'class="product-price[^"]*">(.*?)</span>', b, re.S)
        if not (pid and name and link and price):
            continue
        p = _num(_text(price.group(1)).replace("L", ""))
        if not p:
            continue
        lp = re.search(r'class="list-price-price"\s*>(.*?)</span>', b, re.S)
        reg = _num(_text(lp.group(1)).replace("L", "")) if lp else None
        img = re.search(r'<img src="([^"]+)"', b)
        yield dict(
            external_id=pid.group(1), url=link.group(1), title=unescape(name.group(1)).strip(), brand=None,
            category_raw=category, image=img.group(1) if img else None, gtin=None, sku=None, currency="ALL",
            price=p, regular_price=reg if reg and reg > p else p, in_stock=None,
        )


def scrape(client, max_pages):
    fetched = 0
    for cat in CATEGORIES:
        page, last = 1, 1
        while page <= last and fetched < max_pages:
            r = client.get(f"/{cat}/" + (f"?p={page}" if page > 1 else ""))
            fetched += 1
            if r.status_code != 200:
                break
            html = r.content.decode("utf-8", "replace")
            if page == 1:
                m = re.search(r'id="p-last(?:-bottom)?"\s+value="(\d+)"', html)
                last = int(m.group(1)) if m else 1
            rows = list(parse(html, cat.replace("-", " ")))
            if not rows:
                break
            yield from rows
            page += 1
