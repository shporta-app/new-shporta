"""stina.al (Odoo website shop, prices in Lek).

Product pages do carry JSON-LD, but there are ~15,000 of them. The public listing `/shop/page/N` shows the
same products ~30 per page with title, link and price, so we read the listing (~485 requests) instead.
Price format is "3.290" (dot = thousands). A struck-through list price, when present, becomes regular_price.
"""
import re
from html import unescape


def _num(s):
    s = re.sub(r"[^\d.,]", "", s or "")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        s = re.sub(r"[.,]", "", s)
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+,\d{1,2}", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse(html, base):
    for card in html.split('<article class="oe_product_cart')[1:]:
        card = card.split("</article>")[0]
        link = re.search(r'<h6 class="o_wsale_products_item_title[^"]*">\s*<a[^>]*href="([^"]+)"[^>]*>\s*<span>([^<]*)</span>', card)
        tmpl = re.search(r'data-product-template-id="(\d+)"', card) or re.search(r"-(\d+)$", link.group(1) if link else "")
        sale = re.search(r'aria-label="Sale price".*?<span class="oe_currency_value">([^<]+)</span>', card, re.S)
        if not (link and tmpl and sale):
            continue
        price = _num(sale.group(1))
        if not price:
            continue
        lst = re.search(r'<del[^>]*>.*?<span class="oe_currency_value">([^<]+)</span>', card, re.S)
        reg = _num(lst.group(1)) if lst else None
        img = re.search(r'<img src="([^"]+)"', card)
        alt = re.search(r'alt="\[(\d{8,14})\]', card)
        yield dict(
            external_id=tmpl.group(1), url=base + link.group(1), title=unescape(link.group(2)).strip(), brand=None,
            category_raw=None, image=(base + img.group(1)) if img and img.group(1).startswith("/") else (img.group(1) if img else None),
            gtin=alt.group(1) if alt else None, sku=None, currency="ALL", price=price,
            regular_price=reg if reg and reg > price else price, in_stock=None,
        )


def scrape(client, max_pages):
    page, last = 1, 1
    while page <= last and page <= max_pages:
        r = client.get("/shop" if page == 1 else f"/shop/page/{page}")
        if r.status_code != 200:
            break
        html = r.content.decode("utf-8", "replace")
        nums = [int(n) for n in re.findall(r'href="/shop/page/(\d+)"', html)]
        last = max([last] + nums)
        rows = list(parse(html, client.base))
        if not rows:
            break
        yield from rows
        page += 1
