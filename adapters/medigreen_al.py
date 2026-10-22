"""medigreen.al (Medigreen Farmaci, Odoo eShop, prices in Lek).

Product URLs (`/shop/<slug>-<template id>`, slug usually starting with the EAN) come from the sitemap.
Product pages carry microdata: `itemprop="name"`, a hidden `itemprop="price"` / `priceCurrency`, and on sale
items a struck-through `itemprop="listPrice"` (hidden with `d-none` when there is no discount).
"""
import re
from html import unescape


def _num(s):
    s = re.sub(r"[^\d.]", "", (s or "").replace(",", ""))
    try:
        return float(s)
    except ValueError:
        return None


def scrape(client, max_pages):
    fetched = 0
    r = client.get("/sitemap.xml")
    fetched += 1
    urls = []
    for loc in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", r.text):
        loc = unescape(loc)
        if re.search(r"/shop/[^/]+-\d+$", loc) and "/shop/category/" not in loc:
            urls.append(loc)
    for url in dict.fromkeys(urls):
        if fetched >= max_pages:
            return
        r = client.get(url)
        fetched += 1
        if r.status_code != 200:
            continue
        t = r.text
        title = re.search(r'<h1 itemprop="name"[^>]*>(.*?)</h1>', t, re.S)
        price = re.search(r'itemprop="price"[^>]*>\s*([\d.,]+)', t)
        cur = re.search(r'itemprop="priceCurrency"[^>]*>\s*([A-Z]{3})', t)
        if not (title and price):
            continue
        price = _num(price.group(1))
        if not price:
            continue
        lst = re.search(r'<span([^>]*)itemprop="listPrice"([^>]*)>.*?oe_currency_value">([\d.,]+)', t, re.S)
        reg = None
        if lst and "d-none" not in lst.group(1) + lst.group(2):
            reg = _num(lst.group(3))
        img = re.search(r'<meta property="og:image" content="([^"]+)"', t)
        slug = url.rsplit("/", 1)[-1]
        ean = re.match(r"(\d{8,14})-", slug)
        tid = re.search(r"-(\d+)$", slug).group(1)
        yield dict(
            external_id=tid, url=url, title=re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", title.group(1)))).strip(),
            brand=None, category_raw=None, image=img.group(1) if img else None, gtin=ean.group(1) if ean else None,
            sku=None, currency=cur.group(1) if cur else "ALL", price=price,
            regular_price=reg if reg and reg > price else price, in_stock=None,
        )
