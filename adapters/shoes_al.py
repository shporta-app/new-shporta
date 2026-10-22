"""Bata Albania (shoes.al, Shopify, ALL). A few size variants carry typo prices in the shop's own data
(e.g. "Lek 2,290,002,290" next to siblings at Lek 2,290 with compare-at 4,490). A variant priced above
5x its compare-at price is treated as unreadable and skipped; everything else is scrape.scrape_shopify."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_common", Path(__file__).resolve().parent / "_phia_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def scrape(client, max_pages):
    for r in C.S.scrape_shopify(client, max_pages):
        if r["regular_price"] and r["price"] > 5 * r["regular_price"]:
            continue
        yield r
