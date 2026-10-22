"""Lumea Optic (lumeaoptic.al, CS-Cart, prices in EUR): no Product JSON-LD, so we read each product page
listed in sitemap.xml (URLs end in -<EAN>.html) and take the title from <h1>, the price from the
sec_discounted_price_<id> span ("245<sup>00</sup>" = 245.00) with the currency symbol right before it,
and the crossed-out list price if one is shown. The EAN in the URL is stored as gtin."""
import importlib.util
import re
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_common", Path(__file__).resolve().parent / "_phia_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)
S = C.S
SYM = {"€": "EUR", "Lek": "ALL", "ALL": "ALL", "$": "USD"}


def _price(html, key):
    m = re.search(r'id="%s_\d+"[^>]*>([\d.,]+)(?:<sup>(\d+)</sup>)?' % key, html)
    if not m:
        return None
    return S.num(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else ""))


def _rows(client, max_pages):
    xml = client.get("/sitemap.xml").text
    urls = [u for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml) if re.search(r"-\d{12,13}\.html$", u)]
    for url in list(dict.fromkeys(urls))[:max_pages]:
        r = client.get(url)
        if r.status_code != 200:
            continue
        h = r.content.decode("utf-8", "ignore")
        title = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)
        price = _price(h, "sec_discounted_price")
        sym = re.search(r'class="ty-price-num">([^<]+)</span><span id="sec_discounted_price_', h)
        cur = SYM.get(sym.group(1).strip()) if sym else None
        if not title or not price or not cur:
            continue
        reg = _price(h, "sec_list_price") or price
        code = re.search(r'id="product_code_\d+">([^<]+)<', h)
        img = re.search(r'<meta property="og:image" content="([^"]+)"', h)
        ean = re.search(r"-(\d{12,13})\.html$", url).group(1)
        yield dict(
            external_id=ean, url=url, title=S.strip_html(title.group(1)), brand=S.strip_html(title.group(1)).split(" 0")[0].title(),
            category_raw="Syze", image=img.group(1) if img else None, gtin=ean, sku=code.group(1).strip() if code else None,
            currency=cur, price=price, regular_price=max(reg, price),
            in_stock=int("et-in-stock" in h),
        )


def scrape(client, max_pages):
    yield from C.buffered(_rows(client, max_pages))
