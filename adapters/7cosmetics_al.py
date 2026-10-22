"""7cosmetics.al (custom storefront, no sitemap, very large catalogue: thousands of /shop?page=N pages).

Rows are read straight from the catalogue cards on /shop?page=N (16 per page), so no product page is fetched:
    <article class="product-card" data-ga4-item="{&quot;item_id&quot;:&quot;50494&quot;,...}">
      <a class="product-image" href="/product/<slug>-<id>"><img src="...">
      <p class="product-category">lips</p> <h3><a ...>Name</a></h3>
      <div class="product-price"> [<s>3 500 Lekë</s>] <span>2 900 Lekë</span> </div>
Current price = the <span>, regular price = the struck-through <s> if present. Pagination stops when a page
adds no new product links. external_id = the numeric id at the end of the product slug.
"""
import re
from html import unescape
from urllib.parse import unquote

from scrape import num, strip_html


def _lek(s):
    m = re.search(r"([\d\s .,]+)\s*Lek", s or "")
    return num(re.sub(r"[\s ]", "", m.group(1))) if m else None


def scrape(client, max_pages):
    c = client
    seen = set()
    for page in range(1, max_pages + 1):
        r = c.get(f"/shop?page={page}")
        if r.status_code != 200:
            break
        new = 0
        for card in re.findall(r'<article class="product-card[^"]*"(.*?)</article>', r.text, re.S):
            m = re.search(r'href="(/product/[^"?#]+)"', card)
            if not m or m.group(1) in seen:
                continue
            path = m.group(1)
            seen.add(path)
            new += 1
            name = re.search(r"<h3>\s*<a[^>]*>(.*?)</a>", card, re.S)
            pr = re.search(r'<div class="product-price">(.*?)</div>', card, re.S)
            if not name or not pr:
                continue
            price = _lek(" ".join(re.findall(r"<span>(.*?)</span>", pr.group(1))))
            old = _lek(" ".join(re.findall(r"<s>(.*?)</s>", pr.group(1))))
            if not price:
                continue
            cat = re.search(r'<p class="product-category">(.*?)</p>', card, re.S)
            img = re.search(r'<img src="[^"]*image=([^&"]+)', card)
            idm = re.search(r"-(\d+)$", path)
            yield dict(external_id=idm.group(1) if idm else path, url=c.base + path, title=strip_html(name.group(1)),
                       brand=None, category_raw=strip_html(cat.group(1)) if cat else None,
                       image=unquote(unescape(img.group(1))) if img else None, gtin=None, sku=None, currency="ALL",
                       price=price, regular_price=old if old and old > price else price, in_stock=1)
        if not new:
            break
