"""Probe each shop in shops.txt: is it alive, what does robots.txt allow, which platform is it on.

Writes probe.json. Nothing here downloads product catalogs; it only fetches robots.txt,
the homepage and one tiny API call per platform check.
"""
import json
import re
import sys
import time
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

UA = "shportaBot/1.0 (+https://shporta.app/per-dyqanet)"
HERE = Path(__file__).parent
TIMEOUT = 15
SLOW_PAUSE = 30  # seconds between shops in --slow mode

# Paths the scraper would request, per platform.
PLATFORM_PATHS = {
    "shopify": "/products.json",
    "woocommerce": "/wp-json/wc/store/v1/products",
    "sitemap": "/sitemap.xml",
}


def load_shops(path):
    shops = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            shops.append(line.split("|")[0].strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/"))
    return list(dict.fromkeys(shops))


def get(session, url, **kw):
    try:
        return session.get(url, timeout=TIMEOUT, allow_redirects=True, **kw)
    except requests.RequestException as e:
        return e


def probe(domain):
    s = requests.Session()
    s.headers["User-Agent"] = UA
    out = {"domain": domain, "alive": False}

    home = get(s, f"https://{domain}/")
    if isinstance(home, Exception):
        out["error"] = type(home).__name__
        return out
    out["status"] = home.status_code
    out["final_url"] = home.url
    out["alive"] = home.status_code < 400
    base = re.match(r"https?://[^/]+", home.url).group(0)
    out["base"] = base
    html = home.text[:400_000] if out["alive"] else ""

    # WAF / bot challenge markers: if present we stop and treat the shop as off-limits.
    waf = re.search(r"cf-chl-opt|safeline|sgcaptcha|<title>Just a moment|Attention Required! \| Cloudflare", html, re.I)
    out["bot_challenge"] = bool(waf) or home.status_code in (403, 429, 503)

    # robots.txt
    r = get(s, f"{base}/robots.txt")
    rp = urllib.robotparser.RobotFileParser()
    if not isinstance(r, Exception) and r.status_code == 200 and "<html" not in r.text[:500].lower():
        rp.parse([l for l in r.text.splitlines() if l.strip()])  # blank lines would make the parser drop rules
        out["robots"] = "present"
        out["sitemaps"] = rp.site_maps() or []
    else:
        rp.parse([])  # missing robots.txt means everything is allowed
        out["robots"] = "missing"
        out["sitemaps"] = []
    out["crawl_delay"] = rp.crawl_delay(UA) or rp.crawl_delay("*")
    out["allowed"] = {k: rp.can_fetch(UA, base + p) for k, p in PLATFORM_PATHS.items()}
    out["allowed"]["home"] = rp.can_fetch(UA, base + "/")
    if not isinstance(r, Exception) and re.search(r"ClaudeBot|anthropic|GPTBot|ai crawl", r.text, re.I):
        out["robots_mentions_ai"] = True

    # Platform detection
    platform = None
    if re.search(r"cdn\.shopify\.com|Shopify\.theme", html):
        platform = "shopify"
    elif re.search(r"wp-content|woocommerce", html, re.I):
        platform = "woocommerce"
    elif re.search(r"Magento|mage/|static/version\d+", html):
        platform = "magento"
    elif re.search(r"prestashop", html, re.I):
        platform = "prestashop"
    elif re.search(r"opencart|route=product", html, re.I):
        platform = "opencart"
    elif re.search(r"__NEXT_DATA__", html):
        platform = "nextjs"
    out["platform"] = platform

    # Confirm the product API answers (one tiny request).
    if platform == "shopify" and out["allowed"]["shopify"]:
        p = get(s, f"{base}/products.json?limit=1")
        out["api_ok"] = not isinstance(p, Exception) and p.status_code == 200 and '"products"' in p.text
    elif platform == "woocommerce" and out["allowed"]["woocommerce"]:
        p = get(s, f"{base}/wp-json/wc/store/v1/products?per_page=1")
        ok = not isinstance(p, Exception) and p.status_code == 200 and p.text.lstrip().startswith("[")
        out["api_ok"] = ok
        if ok:
            out["api_total"] = int(p.headers.get("X-WP-Total", 0) or 0)
    # JSON-LD product markup is the fallback for any other platform.
    out["has_jsonld"] = '"@type":"Product"' in html.replace(" ", "") or "application/ld+json" in html
    out["currency_hint"] = (
        "ALL" if re.search(r"\bLek[ëe]?\b|\bALL\b", html) else "EUR" if re.search(r"€|\bEUR\b", html) else None
    )
    return out


def main():
    # --slow: one shop at a time with a long pause, for shops that answered 429 to the parallel run.
    # A second 429 is final: the shop stays out, we don't come back.
    slow = "--slow" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--slow"]
    shops = load_shops(args[0] if args else HERE / "shops.txt")
    out = HERE / (args[1] if len(args) > 1 else "probe.json")
    if slow:
        results = []
        for i, d in enumerate(shops):
            if i:
                time.sleep(SLOW_PAUSE)
            results.append(probe(d))
            out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"{i + 1}/{len(shops)} {d}: {results[-1].get('status', results[-1].get('error'))}", flush=True)
    else:
        with ThreadPoolExecutor(8) as ex:
            results = list(ex.map(probe, shops))
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    for r in results:
        flags = []
        if not r["alive"]:
            flags.append(f"DOWN {r.get('status', r.get('error'))}")
        if r.get("bot_challenge"):
            flags.append("WAF")
        if r.get("allowed") and not r["allowed"]["home"]:
            flags.append("robots-disallow-all")
        print(f"{r['domain']:28} {str(r.get('platform')):12} api={str(r.get('api_ok')):5} total={r.get('api_total', '')!s:6}"
              f" delay={r.get('crawl_delay')} {r.get('currency_hint')} {' '.join(flags)}")


if __name__ == "__main__":
    main()
