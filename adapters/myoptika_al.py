"""myoptika_al: plain sitemap + schema.org Product JSON-LD, read through the buffered helper so the shared
SQLite write lock is only held briefly (see _phia_common.py).

Polite mode (the shop answered 429 before): at least 8 s between requests. On a 429 we honour Retry-After
(or wait 10 minutes) and retry the same URL once; the second 429 of a run stops for good (shop stays blocked).
Any 403 or bot challenge stops immediately. Retry-After is read from a requests response hook, so every fetch
still goes through client.get (robots.txt, UA, delay)."""
import importlib.util
import time
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_phia_common", Path(__file__).resolve().parent / "_phia_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

MIN_DELAY = 8.0
DEFAULT_WAIT = 600
MAX_429 = 2  # the second 429 in a run ends it


def _polite(client):
    last = {}
    client.s.hooks.setdefault("response", []).append(lambda r, *a, **k: last.update(status=r.status_code, ra=r.headers.get("Retry-After")))
    client.delay = max(client.delay, MIN_DELAY)
    orig = client.get
    count = {"429": 0}

    def get(url, **kw):
        while True:
            last.clear()
            try:
                return orig(url, **kw)
            except C.S.Blocked:
                if last.get("status") != 429:
                    raise
                count["429"] += 1
                if count["429"] >= MAX_429:
                    count["stopped"] = url
                    raise C.S.Blocked(f"429 again ({count['429']} this run) at {url}; stopped for good")
                ra = last.get("ra")
                wait = int(ra) if ra and ra.strip().isdigit() else DEFAULT_WAIT
                print(f"  myoptika.al: 429, waiting {wait}s (Retry-After={ra!r}) before one retry", flush=True)
                time.sleep(max(wait, MIN_DELAY))

    client.get = get
    return count


def scrape(client, max_pages):
    state = _polite(client)
    sm = "https://myoptika.al/sitemap.xml"
    yield from C.jsonld_from(client, max_pages, [sm])
    if state.get("stopped"):  # scrape.sitemap_urls swallows Blocked; surface it so the shop is recorded as blocked
        raise C.S.Blocked(f"429 twice this run (last at {state['stopped']}); stopped for good")
