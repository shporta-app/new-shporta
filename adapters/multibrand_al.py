"""multibrand.al (WooCommerce, Lek, multi-brand fashion/accessories reseller in Tirana).

robots.txt has `Crawl-delay: 10` and `Disallow: /*?*per_page=`. Python's robotparser ignores `*` wildcards, so
the built-in woocommerce adapter (which sends per_page=100) would look allowed while the rule says no. We call the
public Store API without per_page (default 10 per page) for products and variations. Rows come from
scrape._woo_row, so the output matches the built-in adapter (variable products stored per variant).
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_common", Path(__file__).resolve().parent / "_phia_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)
S = C.S
API = "/wp-json/wc/store/v1/products"


def _pages(client, query):
    for page in range(1, 10000):
        r = client.get(f"{API}?{query}page={page}")
        if r.status_code in (400, 404):
            return
        r.raise_for_status()
        items = r.json()
        if not isinstance(items, list) or not items:
            return
        yield items
        if page >= int(r.headers.get("X-WP-TotalPages", page) or page):
            return


def _rows(client, max_pages):
    for n, items in enumerate(_pages(client, ""), 1):
        variable = {}
        for p in items:
            if p.get("type") == "variable" and p.get("variations"):
                variable[p["id"]] = p
                continue
            row = S._woo_row(p)
            if row:
                yield row
        if variable:
            ids = ",".join(map(str, variable))
            for vitems in _pages(client, f"type=variation&parent={ids}&"):
                for v in vitems:
                    parent = variable.get(v.get("parent")) or next(
                        (p for p in variable.values() if any(x["id"] == v["id"] for x in p["variations"])), None)
                    row = S._woo_row(v, parent)
                    if row:
                        yield row
        if n >= max_pages:
            return


def scrape(client, max_pages):
    yield from C.buffered(_rows(client, max_pages))
