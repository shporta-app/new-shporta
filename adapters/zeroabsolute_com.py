"""zeroabsolute.com (Zero Absolute, Tirana fast-fashion brand; Laravel + Inertia/Vue, prices in Lek).

No JSON-LD. Each product page embeds its data as JSON in the root `data-page` attribute (Inertia props).
The sitemap lists `/products/show/<group>?color=<c>&size=<s>`; we fetch one URL per (group, colour).
`item.rate` is the list price; `item.pricelist_rate`, when set, is the current (discounted) price and
agrees with `item.discount_percentage`.
"""
import json
import re
from html import unescape


def scrape(client, max_pages):
    sm = client.get("/sitemap.xml").text
    urls = {}
    for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", sm):
        loc = unescape(loc)
        m = re.search(r"/products/show/(\d+)\?(.*)$", loc)
        if not m:
            continue
        color = re.search(r"color=(\d+)", m.group(2))
        urls.setdefault((m.group(1), color.group(1) if color else ""), loc)
    fetched = 0
    for (group, color), url in urls.items():
        if fetched >= max_pages:
            return
        r = client.get(url)
        fetched += 1
        m = re.search(r'data-page="([^"]+)"', r.text)
        if r.status_code != 200 or not m:
            continue
        try:
            props = json.loads(unescape(m.group(1))).get("props") or {}
        except ValueError:
            continue
        it = props.get("item") or {}
        if props.get("currency") not in (None, "ALL") or not it:
            continue
        try:
            rate = float(it.get("rate") or 0)
            plr = float(it.get("pricelist_rate") or 0)
        except (TypeError, ValueError):
            continue
        price = plr if 0 < plr < rate else rate
        if not price:
            continue
        medias = props.get("medias") or []
        img = None
        if medias and isinstance(medias, list) and isinstance(medias[0], dict):
            img = medias[0].get("original_url") or medias[0].get("url")
        name = it.get("name") or it.get("title")
        yield dict(
            external_id=f"{group}-{it.get('color_id') or color}", url=url, title=name.strip(), brand="Zero Absolute",
            category_raw=", ".join(x for x in (it.get("category_name"), it.get("cf_nenkategori_1"), it.get("gender")) if x),
            image=img, gtin=None, sku=it.get("sku"), currency="ALL", price=price, regular_price=rate,
            in_stock=int((it.get("actual_available_stock") or 0) > 0),
        )
