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
