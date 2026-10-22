"""Sport Reality Albania (same platform and group as Sport Vision): product URLs only from files/sitemap/ALB_al/product.xml (the sitemap index also
lists ~140 category pages without Product markup). Prices from schema.org Product JSON-LD (ALL)."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_common", Path(__file__).resolve().parent / "_phia_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def scrape(client, max_pages):
    yield from C.jsonld_from(client, max_pages, [client.base + "/files/sitemap/ALB_al/product.xml"])
