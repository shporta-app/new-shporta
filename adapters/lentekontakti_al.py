"""lentekontakti_al: plain sitemap + schema.org Product JSON-LD, read through the buffered helper so the shared
SQLite write lock is only held briefly (see _phia_common.py)."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_common", Path(__file__).resolve().parent / "_phia_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def scrape(client, max_pages):
    sm = "/export/sitemap/"
    yield from C.jsonld_from(client, max_pages, [sm if sm.startswith("http") else client.base + sm])
