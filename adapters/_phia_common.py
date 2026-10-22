"""Shared helpers for the accessories adapters (not an adapter itself: no domain has this name).

buffered(): scrape.save() commits every 200 saved rows, and its write transaction stays open while
the generator fetches the next page. For page-per-product scrapers that holds the SQLite write lock
for minutes and other writers fail with 'database is locked'. Buffering rows and handing them over
in batches of exactly 200 valid rows makes each write burst short and aligned with save()'s commit.
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_scrape", Path(__file__).resolve().parent.parent / "scrape.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


def _lenient_jsonld_products(html):
    """scrape.jsonld_products, but json.loads(strict=False): some platforms (buzzsneakers.al, sportvision.al) put raw
    tabs/newlines inside JSON-LD strings, which the strict parser rejects, silently dropping those products."""
    import json
    import re
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip(), strict=False)
        except ValueError:
            continue
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
            elif isinstance(d, dict):
                t = d.get("@type")
                if t == "Product" or (isinstance(t, list) and "Product" in t):
                    yield d
                stack.extend(v for k, v in d.items() if k in ("@graph", "mainEntity", "itemListElement", "item", "hasVariant"))


# This module's private copy of scrape.py (S) uses the lenient parser; scrape.py itself is unchanged.
S.jsonld_products = _lenient_jsonld_products


def buffered(rows, size=200):
    buf = []
    for r in rows:
        if r.get("title") and r.get("price"):
            buf.append(r)
        if len(buf) >= size:
            yield from buf
            buf = []
    yield from buf


def jsonld_from(client, max_pages, sitemap_urls):
    client.sitemaps = list(sitemap_urls)
    yield from buffered(S.scrape_jsonld(client, max_pages))
