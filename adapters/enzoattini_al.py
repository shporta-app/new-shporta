"""Enzo Attini (Shopify, EUR). The catalogue contains payment-link pseudo-products
("Pagese", "Link pagese", "Pagese kapari online", "Iute...") used for deposits; they are not goods and are skipped."""
import importlib.util
import re
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_common", Path(__file__).resolve().parent / "_phia_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)
JUNK = re.compile(r"^\s*(pages[eë]|link\b|iute)", re.I)


def scrape(client, max_pages):
    for r in C.S.scrape_shopify(client, max_pages):
        if not JUNK.search(r["title"]):
            yield r
