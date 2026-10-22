# phia-al

A Phia-style price comparison for Albania: clothing, shoes, accessories, jewelry, cosmetics and perfume.
This folder holds the data collection. All shops write into one SQLite DB, `data/phia.db`.

## Run

```
python probe.py shops.txt          # alive? robots.txt? platform? -> probe.json
python scrape.py <domain> --category beauty [--max-pages N] [--platform shopify|woocommerce|jsonld]
```

Categories: `clothing | shoes | beauty | perfume | jewelry | accessories | sport | multi`.

## Adapters

- `shopify`: `/products.json`, one row per variant, with the barcode as `gtin`
- `woocommerce`: the public Store API `/wp-json/wc/store/v1/products`
- `jsonld`: product URLs from the sitemap, read from schema.org `Product` markup (Magento, PrestaShop, custom sites)
- custom: `adapters/<domain_with_underscores>.py` defining `scrape(client, max_pages)` that yields the same dicts.
  `scrape.py` picks it up automatically. Use `client.get()` so robots.txt and delays still apply.

## Rules

- Obey robots.txt and Crawl-delay (at least 1 s between requests). Identify as `PhiaALBot`.
- On a bot challenge, 403 or 429, stop and record the shop as `blocked`. Never bypass a WAF or rotate IPs/UAs.
- Never invent or estimate prices. If a price isn't readable, skip the product.
- Respect a shop's terms if they explicitly forbid automated collection: list it as `blocked` with a note.

## Matching, report, API, extension

```
python match.py         # groups the same product across shops (name words + size) -> matches table
python make_report.py   # report.html: shops + "same product, different shops"
python server.py        # local API on http://localhost:8787 (/api/lookup, /api/search)
```

Browser extension (dev): Chrome or Edge → `chrome://extensions` → turn on Developer mode → **Load unpacked** →
choose the `extension` folder. Keep `python server.py` running. Open any product page (a shop we scraped, or one
we can't, like Zara): a panel shows the price verdict (good / normal / high) and cheaper offers, or similar products
when there's no exact match. The extension only reads the page the shopper already opened; it never requests the shop.

WooCommerce variable products are stored per variant ("… - 50 ml"), not as the parent's lowest price.

## Deploy (Render)

The API runs on Render from `render.yaml` (repo `shporta-app/new-shporta`). It serves `seed/phia-api.db.gz`,
a compact export of the scrape DB (`python build_seed.py`), so the full `data/phia.db` never leaves this machine.
To publish fresh prices: `python refresh.py` → `python build_seed.py` → commit `seed/phia-api.db.gz` → push.

## Tables

`shops` (one row per domain, status ok/blocked/down/error/no-products), `products` (latest state per shop item),
`prices` (one row per product per day, which becomes price history once scraping runs daily).
