"""supermart.al (CS-Cart + UniTheme2, prices in Lek). Product pages carry no schema.org JSON-LD, so we read the
public category listings `/<category>/page-N/` (20 products per page): product id, title, brand, link, current
price (`sec_discounted_price_<id>`) and struck list price (`sec_list_price_<id>`). Only the fashion / beauty /
accessories categories are walked. robots.txt only disallows /app/ and /store_closed.html.
Price format "13.999" (dot = thousands)."""
import re
from html import unescape

CATEGORIES = ["kujdesi-personal", "aksesore-dhe-canta", "syze-dielli-dhe-optike", "pajisje-per-kujdesin-personal"]


def _num(s):
    s = re.sub(r"[^\d.,]", "", s or "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d{1,2})?", s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _text(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse(html, cat):
    i = html.find('id="pagination_contents"')
    seg = html[i:] if i >= 0 else html
    for b in re.split(r'class="ut2-gl__item', seg)[1:]:
        pid = re.search(r'name="product_data\[(\d+)\]\[product_id\]"', b)
        link = re.search(r'<a href="([^"]+)" class="product-title" title="([^"]*)"', b)
        if not (pid and link):
            continue
        p = pid.group(1)
        cur = re.search(rf'id="sec_discounted_price_{p}" class="ty-price-num">([^<]+)<', b)
        price = _num(cur.group(1)) if cur else None
        if not price:
            continue
        lst = re.search(rf'id="sec_list_price_{p}"[^>]*>([^<]+)<', b)
        reg = _num(lst.group(1)) if lst else None
        brand = re.search(r'<span class="brand-name">([^<]+)</span>', b)
        img = re.search(r'<img class="ty-pict[^>]*\bsrc="([^"]+)"', b)
        yield dict(
            external_id=p, url=link.group(1), title=_text(link.group(2)), brand=_text(brand.group(1)) if brand else None,
            category_raw=cat, image=img.group(1) if img else None, gtin=None, sku=None, currency="ALL",
            price=price, regular_price=reg if reg and reg > price else price, in_stock=None,
        )


def scrape(client, max_pages):
    seen, fetched = set(), 0
    for cat in CATEGORIES:
        page, last = 1, 1
        while page <= last and fetched < max_pages:
            r = client.get(f"/{cat}/" + (f"page-{page}/" if page > 1 else ""))
            fetched += 1
            if r.status_code != 200:
                break
            html = r.content.decode("utf-8", "replace")
            last = max([last] + [int(n) for n in re.findall(rf'href="https://supermart\.al/{cat}/page-(\d+)/"', html)])
            rows = list(parse(html, cat))
            if not rows:
                break
            for row in rows:
                if row["external_id"] not in seen:
                    seen.add(row["external_id"])
                    yield row
            page += 1
