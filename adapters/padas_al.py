"""padas.al (PADAS: shoes, bags, wallets; WooCommerce, prices in Lek).

The versioned Store API route (/wp-json/wc/store/v1/products) is missing on this site, but the older unversioned
route (/wp-json/wc/store/products) answers with the same JSON. So: the shared WooCommerce scraper, with requests
rewritten to the unversioned route. Requests still go through client.get (robots.txt, delay, block detection).
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_common", Path(__file__).resolve().parent / "_phia_common.py")
_C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_C)
S = _C.S


class _Unversioned:
    def __init__(self, client):
        self._c = client
        self.base = client.base

    def get(self, url, **kw):
        return self._c.get(url.replace("/wp-json/wc/store/v1/", "/wp-json/wc/store/"), **kw)

    def allowed(self, url):
        return self._c.allowed(url)


def scrape(client, max_pages):
    yield from S.scrape_woocommerce(_Unversioned(client), max_pages)
