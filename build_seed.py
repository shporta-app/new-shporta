"""Export the compact, read-only DB the website/API serves, as seed/phia-api.db.gz (committed; the server unpacks it).

    python build_seed.py

Tables:
  products  current offers with match key, size and our category
  matches   product -> group (same product in 2+ shops, from match.py)
  items     what the website lists: one row per matched product (all its shops) or per single product page
            (variants of one page collapsed), with lowest/highest price and how many shops sell it
  shops     shop directory
The full data/phia.db (price history, raw data) stays on the machine that scrapes.
"""
import collections
import gzip
import hashlib
import re
import shutil
import sqlite3
import unicodedata
from pathlib import Path

from match import parse

HERE = Path(__file__).parent
SRC = HERE / "data" / "phia.db"
OUT = HERE / "seed" / "phia-api.db"

# Our categories, checked in this order against the folded title (then the shop's own category text).
# Word starts, so "ora" matches "ora dore" but not "koral".
CATEGORIES = [
    ("parfume", "Parfume", r"parfum|perfum|eau de (toilette|parfum|cologne)|\bedp\b|\bedt\b|kolonj|cologne|fragrance|body mist"),
    ("grim", "Grim", r"mascara|maskar|rimel|lipstick|buzekuq|lip ?gloss|lip ?liner|foundation|fondatin|pudr|powder|concealer|"
                     r"korrektor|eyeliner|eye ?shadow|hije sysh|blush|allik|bronzer|highlighter|primer|\bbrows?\b|vetull|makeup|make up|"
                     r"\bgrim\b|manikyr|llak thonj|nail polish|\bthonj"),
    ("floke", "Flokë", r"shampo|conditioner|balsam floke|\bhair\b|flok|keratin|ngjyre per floke"),
    ("femije", "Fëmijë", r"\bbaby|\bbebe|femij|\bkids|vajza|djem|\bjunior|foshnj|neonat"),
    ("lekure", "Kujdesi i lëkurës", r"serum|toner|tonik|cleans|pastrues|spf|sunscreen|kunder diellit|moistur|hidrat|essence|ampoule|"
                                    r"retinol|niacinamide|hyaluron|acne|akne|peeling|exfol|micellar|krem fytyr|\bface\b|fytyr|"
                                    r"eye cream|krem sysh|sheet mask|maske fytyr|\bcream|\bcreme|\bkrem|lotion|\bbalm\b|gel pastrues|dermo"),
    ("trup", "Trupi & higjiena", r"\bbody\b|\btrup|\bdush|shower|deodorant|deo |sapun|soap|scrub|pasta dhemb|toothpaste|furce dhemb|kremi i duarve|hand cream"),
    ("kepuce", "Këpucë", r"kepuc|atlete|sneaker|\bshoes?\b|cizm|\bboots?\b|\bsandal(e|et|s)?\b|papuc|\bslippers?\b|mokasin|loafer|\btaka\b|espadril|\bclogs?\b"),
    ("canta", "Çanta", r"\bcant[ae]|\bbag\b|\bbags\b|portofol|wallet|backpack|shpine|valixh|luggage|suitcase|crossbody|tote"),
    ("ora", "Ora", r"\bore dore|\bora\b|\bwatch|smartwatch|chronograph"),
    ("syze", "Syze", r"\bsyze|sunglass|eyeglass|optik|\blente|contact lens|\bkorniz"),
    ("bizhuteri", "Bizhuteri", r"\bunaz|\bring\b|varese|necklace|\bvathe|earring|byzylyk|bracelet|argjend|\bsilver|\bari 1|"
                               r"\bgold\b|jewel|bizhuteri|\bzinxhir|pendant|varese"),
    ("sport", "Sport", r"\bsport|fitness|training|running|vrapim|futboll|\bgym|\byoga|\btuta\b"),
    ("veshje", "Veshje", r"bluz|fustan|xhins|pantallon|xhaket|xhup|pallto|kemish|\bfund\b|triko|pulover|maic|t-?shirt|\bdress|"
                         r"jeans|\bshirt|\bcoat|jacket|skirt|sweater|hoodie|\btop\b|breke|sutjen|pizham|lingerie|te brendshme|"
                         r"corape|\bsocks|kostum|blazer|kardigan|cardigan|polo|bermuda|shorts|leggings|kemishe|jelek|pajama|bra\b"),
]
SHOP_FALLBACK = {"perfume": "parfume", "shoes": "kepuce", "jewelry": "bizhuteri", "clothing": "veshje", "sport": "sport"}
CAT_RE = [(c, re.compile(p)) for c, _, p in CATEGORIES]


def fold(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def classify(title, category_raw, shop_cat):
    for text in (fold(title), fold(category_raw)):
        for cat, rx in CAT_RE:
            if rx.search(text):
                return cat
    return SHOP_FALLBACK.get(shop_cat, "tjeter")


def main():
    OUT.parent.mkdir(exist_ok=True)
    OUT.unlink(missing_ok=True)
    src = sqlite3.connect(SRC, timeout=120)
    dst = sqlite3.connect(OUT)
    dst.executescript("""
        CREATE TABLE products (id INTEGER PRIMARY KEY, shop TEXT, title TEXT, brand TEXT, url TEXT, image TEXT,
                               price REAL, regular_price REAL, currency TEXT, in_stock INTEGER,
                               name_key TEXT, size_val REAL, size_unit TEXT, cat TEXT, item_id TEXT);
        CREATE TABLE matches (product_id INTEGER PRIMARY KEY, group_id TEXT);
        CREATE TABLE shops (domain TEXT PRIMARY KEY, category TEXT, products INTEGER);
        CREATE TABLE items (id TEXT PRIMARY KEY, title TEXT, image TEXT, cat TEXT, shops INTEGER, in_stock_shops INTEGER,
                            min_price REAL, max_price REAL, currency TEXT, save_pct INTEGER, search TEXT, size_note INTEGER);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE VIRTUAL TABLE words USING fts5(name_key, content='products', content_rowid='id', tokenize='unicode61');
    """)
    shop_cat = dict(src.execute("SELECT domain, category FROM shops"))
    group_of = dict(src.execute("SELECT product_id, group_id FROM matches"))

    rows = []
    for pid, shop, title, brand, url, image, price, reg, cur, stock, craw in src.execute(
            """SELECT id, shop, title, brand, url, image, price, regular_price, currency, in_stock, category_raw
               FROM products WHERE price > 0"""):
        key, size = parse(title)
        cat = classify(title, craw, shop_cat.get(shop))
        gid = group_of.get(pid)
        # one listing item per matched product, otherwise per product page (Shopify ?variant= rows share a page)
        item = "g" + gid if gid else "p" + hashlib.md5(f"{shop}|{(url or str(pid)).split('?')[0]}".encode()).hexdigest()[:12]
        rows.append([pid, shop, title, brand, url, image, price, reg, cur, stock, key,
                     size[0] if size else None, size[1] if size else None, cat, item])

    # items: aggregate offers
    by_item = collections.defaultdict(list)
    for r in rows:
        by_item[r[14]].append(r)
    items = []
    for iid, offs in by_item.items():
        cats = collections.Counter(o[13] for o in offs)
        cat = cats.most_common(1)[0][0]
        for o in offs:  # a matched product gets one category for all its shops
            o[13] = cat
        lek = [o for o in offs if o[8] == "ALL"]
        pool = lek or offs
        live = [o for o in pool if o[9]] or pool
        prices = [o[6] for o in live]
        lo, hi = min(prices), max(prices)
        shops = {o[1] for o in offs}
        live_shops = {o[1] for o in offs if o[9]}
        # per shop take its cheapest offer, so a shop's several sizes don't inflate the spread for single-shop items
        per_shop_min = {}
        for o in live:
            per_shop_min[o[1]] = min(per_shop_min.get(o[1], o[6]), o[6])
        save = round((max(per_shop_min.values()) - min(per_shop_min.values())) / max(per_shop_min.values()) * 100) \
            if len(per_shop_min) >= 2 else 0
        title = min((o[2] for o in offs), key=lambda t: (abs(len(t) - 45), t))
        image = next((o[5] for o in offs if o[5]), None)
        search = fold(" ".join({o[2] for o in offs}) + " " + " ".join(o[3] or "" for o in offs[:3]))
        # 0: every shop states the size, 1: some don't, 2: none do (shown as a warning on the product page)
        sized = [o[11] is not None for o in offs]
        size_note = 0 if all(sized) else 2 if not any(sized) else 1
        items.append((iid, title, image, cat, len(shops), len(live_shops), lo, hi, pool[0][8], save, search[:600], size_note))

    dst.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    dst.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", items)
    dst.executemany("INSERT INTO matches VALUES (?,?)", group_of.items())
    dst.executemany("INSERT INTO shops VALUES (?,?,?)",
                    src.execute("SELECT domain, category, products FROM shops WHERE status IN ('ok','error')"))
    last = src.execute("SELECT MAX(last_seen) FROM products").fetchone()[0]
    dst.executemany("INSERT INTO meta VALUES (?,?)", [("updated", last or ""),
                                                      ("categories", repr([(c, label) for c, label, _ in CATEGORIES]))])
    dst.executescript("""
        CREATE INDEX products_key ON products(name_key);
        CREATE INDEX products_item ON products(item_id);
        CREATE INDEX matches_group ON matches(group_id);
        CREATE INDEX items_cat ON items(cat, shops DESC, save_pct DESC);
        CREATE INDEX items_deals ON items(save_pct DESC) WHERE shops >= 2;
        INSERT INTO words(words) VALUES('rebuild');
    """)
    dst.commit()
    dst.execute("VACUUM")
    dst.close()
    with open(OUT, "rb") as f, gzip.open(str(OUT) + ".gz", "wb", compresslevel=9) as g:
        shutil.copyfileobj(f, g)
    cats = collections.Counter(i[3] for i in items)
    print(f"{len(rows):,} offers, {len(items):,} items -> {OUT.stat().st_size / 1e6:.0f} MB, "
          f"gzipped {Path(str(OUT) + '.gz').stat().st_size / 1e6:.0f} MB")
    print("items per category:", dict(cats.most_common()))


if __name__ == "__main__":
    main()
