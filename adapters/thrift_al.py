"""thrift.al (Nuxt front end, second-hand clothing marketplace).

Category pages render in the browser from the public API at api.thrift.al (its robots.txt has no rules).
We page through `/v1/products/search`, the same call the site's listing pages make. `finalPrice` is the
price shown to buyers (item price + 50 L buyer-protection fee) and matches the product page's JSON-LD.
Items are one-off used listings.
"""
API = "https://api.thrift.al/v1/products/search"


def scrape(client, max_pages):
    page, total_pages = 1, 1
    while page <= total_pages and page <= max_pages:
        r = client.get(f"{API}?page={page}&limit=100")
        if r.status_code != 200:
            break
        d = r.json()
        total_pages = int((d.get("pagination") or {}).get("totalPages") or 1)
        items = d.get("data") or []
        if not items:
            break
        for p in items:
            if p.get("status") not in (None, "active"):
                continue
            price = p.get("finalPrice") or p.get("price")
            if not price:
                continue
            brand = (p.get("brand") or {}).get("name")
            size = (p.get("size") or {}).get("name")
            yield dict(
                external_id=str(p["id"]), url=f'https://thrift.al/products/{p["slug"]}',
                title=(p.get("title") or "").strip(), brand=None if brand in (None, "No Brand") else brand,
                category_raw=f'second-hand; condition={p.get("condition")}; size={size}',
                image=p.get("imageUrl"), gtin=None, sku=None, currency="ALL",
                price=float(price), regular_price=float(price), in_stock=1,
            )
        page += 1
