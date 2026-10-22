"""Crocs Albania (crocs.al, ALL). No sitemap and no Product JSON-LD; every category page
(/products/<id>, linked from the homepage menu) embeds its article list as `let products = [...]`
with regularPrice and discountPrice (0 = no discount). One row per article (model), price =
discountPrice when set, otherwise regularPrice, as shown on the listing."""
import importlib.util
import json
import re
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_common", Path(__file__).resolve().parent / "_phia_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)
S = C.S


def _rows(client, max_pages):
    home = client.get("/").text
    cats = list(dict.fromkeys(re.findall(r'href="(/products/\d+)"', home)))[:max_pages]
    seen = set()
    for cat in cats:
        h = client.get(cat).text
        m = re.search(r"let products\s*=\s*\[", h)
        if not m:
            continue
        try:
            items, _ = json.JSONDecoder().raw_decode(h, m.end() - 1)
        except ValueError:
            continue
        for a in items:
            aid = str(a.get("id"))
            if aid in seen or a.get("disableLink"):
                continue
            seen.add(aid)
            reg = S.num(a.get("regularPrice"))
            disc = S.num(a.get("discountPrice"))
            price = disc if disc else reg
            if not price:
                continue
            img = None
            for col in a.get("colors") or []:
                if col.get("images"):
                    img = client.base + col["images"][0]
                    break
            yield dict(
                external_id=aid, url=client.base + a["url"], title=S.strip_html(a.get("name")), brand="Crocs",
                category_raw=cat, image=img, gtin=None, sku=None, currency="ALL",
                price=price, regular_price=max(reg or price, price), in_stock=int(not a.get("isZeroStock")),
            )


def scrape(client, max_pages):
    yield from C.buffered(_rows(client, max_pages))
