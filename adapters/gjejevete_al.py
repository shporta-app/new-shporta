"""gjejevete.al (ASP.NET WebForms marketplace, ~350 sellers, prices in Lek). Not Shopify: /products.json is 404.

The listing page `/pg/produkte.aspx?d=<dept>[&cat=<c>[&scat=<s>]]` server-renders its first 40 products
(title, link, seller, price, struck list price). Further pages come only from a POST PageMethod
(`/pg/produkte.aspx/GetProducts`, JSON {pageIndex,pageSize,word}); the mobile site uses POST `/Kategori/LoadMore/`.
Adapters must fetch through client.get (robots + Crawl-delay), so we stay GET-only and walk every
department -> category -> subcategory page of the fashion/beauty departments, deduplicating by product id.
That covers the first 40 items of each leaf, not the full ~80k catalogue (sitemap.aspx lists the product URLs).

Departments: 7 Fashion, 9 Beauty & Health, 11 Jewellery & Accessories, 14 Shoes & Bags, 22 Silver & Accessories.
"""
import re
from html import unescape

DEPTS = [7, 14, 9, 11, 22]


def _num(s):
    s = re.sub(r"[^\d.,]", "", s or "")
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _text(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse(html, base, label):
    i = html.find('id="elements"')
    seg = html[i:] if i >= 0 else html
    seg = seg.split("function GetData()")[0]
    for b in re.split(r"<div class=['\"]ps-product['\"]>", seg)[1:]:
        link = re.search(r'<a class="ps-product__title" href="/pg/detaje\.aspx\?id=(\d+)">(.*?)</a>', b, re.S)
        pr = re.search(r"<p class='ps-product__price( sale)?'>(.*?)</p>", b, re.S)
        if not (link and pr):
            continue
        body = pr.group(2)
        cur_txt = _text(body.split("<del>")[0])
        if "Lek" not in cur_txt:
            continue  # only Lek prices; any other currency is skipped rather than guessed
        price = _num(cur_txt.replace("Lekë", "").replace("Lek", ""))
        if not price:
            continue
        old = re.search(r"<del>(.*?)</del>", body, re.S)
        reg = _num(_text(old.group(1)).replace("Lekë", "").replace("Lek", "")) if old else None
        img = re.search(r'<img src="([^"]+)"', b)
        seller = re.search(r'class="ps-product__vendor"[^>]*>(.*?)</a>', b, re.S)
        yield dict(
            external_id=link.group(1), url=f"{base}/pg/detaje.aspx?id={link.group(1)}", title=_text(link.group(2)),
            brand=None, category_raw=label + (f" | seller: {_text(seller.group(1))}" if seller else ""),
            image=img.group(1) if img else None, gtin=None, sku=None, currency="ALL", price=price,
            regular_price=reg if reg and reg > price else price, in_stock=None,
        )


def scrape(client, max_pages):
    seen, fetched = set(), 0
    for d in DEPTS:
        queue, done = [f"/pg/produkte.aspx?d={d}"], set()
        while queue and fetched < max_pages:
            path = queue.pop(0)
            if path in done:
                continue
            done.add(path)
            r = client.get(path)
            fetched += 1
            if r.status_code != 200:
                continue
            html = r.content.decode("utf-8", "replace")
            if path.endswith(f"d={d}"):
                subs = re.findall(rf'href="(/pg/produkte\.aspx\?d={d}&(?:amp;)?cat=\d+(?:&(?:amp;)?scat=\d+)?)"', html)
                queue += [s.replace("&amp;", "&") for s in dict.fromkeys(subs)]
            for row in parse(html, client.base, path.split("?")[1]):
                if row["external_id"] not in seen:
                    seen.add(row["external_id"])
                    yield row
