"""fashionandfriends.com, Albanian store only (/al/, prices in Lek).

The Magento grids are rendered by the Athena search module (eu-1.athenasearch.cloud, website token in the page).
Its results reach the browser as server-rendered HTML on the shop's own domain: the infinite scroll simply
requests `/al/<category>/filter/page:N/`, 24 products per page, the same URLs as the "next page" link. We read
those pages (allowed by robots.txt) instead of calling the Athena API directly. Category list comes from the AL
mega-menu JSON (`/al/cache/index/index/desktop/?menu=true...`), top-level gender/section categories only, since
subcategories repeat the same products. One row per Magento parent product (data-product-id); price is the
finalPrice the grid shows, the crossed price becomes regular_price.

robots.txt note: its rules after the first blank line are ignored by Python's parser, so we also avoid
/catalogsearch/, /catalog/, /pub/ and ?dir/?mode/?limit URLs ourselves (we never request them).
"""
import re
from html import unescape

MENU = "/al/cache/index/index/desktop/?menu=true&alias=ff_albania-ff-sq_AL-menu&key=ff_albania_sq_AL"
FALLBACK = [f"/al/{g}/{s}/" for g in ("femra", "meshkuj") for s in ("veshje", "kepuce", "cante", "aksesore")]
AVOID = re.compile(r"/catalogsearch/|/catalog/|/pub/|[?&](dir|mode|limit)")


def _num(s):
    s = re.sub(r"[^\d.,]", "", s or "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})*(,\d{1,2})?", s):
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _text(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def categories(client):
    try:
        r = client.get(MENU)
        s = (r.json() if r.status_code == 200 else "") or ""
    except ValueError:
        s = ""
    s = s if isinstance(s, str) else str(s)
    urls = set(re.findall(r"https://www\.fashionandfriends\.com(/al/(?:femra|meshkuj)/[a-z0-9-]+/)(?=[\"\\])", s.replace("\\/", "/")))
    urls = [u for u in urls if not u.endswith("/te-reja/")]  # "new in" repeats the others
    return sorted(set(urls) | set(FALLBACK))


def parse(html, cat):
    for b in re.split(r'<li class="item product product-item', html)[1:]:
        b = b.split("</li>")[0]
        pid = re.search(r'data-product-id="(\d+)"', b)
        link = re.search(r'<a class="product-item-link" href="([^"]+)">(.*?)</a>', b, re.S)
        amt = re.search(r'data-price-amount="([\d.]+)" data-price-type="finalPrice"', b)
        if not (pid and link and amt):
            continue
        price = float(amt.group(1))
        if not price:
            continue
        crossed = re.search(r'class="crossed price ">([^<]+)<', b)
        reg = _num(crossed.group(1)) if crossed else None
        title = _text(link.group(2))
        img = re.search(r'<img class="product-image-photo[^"]*" src="([^"]+)"', b)
        yield dict(
            external_id=pid.group(1), url=link.group(1), title=title, brand=title.split(" - ")[0] if " - " in title else None,
            category_raw=cat.strip("/").removeprefix("al/"), image=img.group(1) if img else None, gtin=None, sku=None,
            currency="ALL", price=price, regular_price=reg if reg and reg > price else price, in_stock=None,
        )


def scrape(client, max_pages):
    seen, fetched = set(), 0
    for cat in categories(client):
        url = cat
        while url and fetched < max_pages:
            if AVOID.search(url) or not url.startswith("/al/"):
                break
            r = client.get(url)
            fetched += 1
            if r.status_code != 200:
                break
            html = r.content.decode("utf-8", "replace")
            rows = list(parse(html, cat))
            if not rows:
                break
            for row in rows:
                if row["external_id"] not in seen:
                    seen.add(row["external_id"])
                    yield row
            nxt = re.search(r'pages-item-next"><a class="action next" href="([^"]+)"', html)
            url = nxt.group(1).replace("https://www.fashionandfriends.com", "") if nxt else None
