"""Group the same product across shops.

    python match.py            -> fills the `matches` table (product_id -> group_id)

How a product is identified:
  name key  = the set of meaningful words in the title (accents folded, punctuation dropped, size removed),
              so "Dr.Althea – 345 Relief Cream" == "DR. ALTHEA 345 Relief Cream" == "Dr. Althea 345 Relief Cream - 50"
  size      = "50ml", or a bare "- 50" suffix (Shopify variant titles), or unknown

Two rows are the same product only when all of these hold:
  1. the name keys are equal (different words never match: cream / cream mist / cream mask / set / tester / refill)
  2. the name is specific: it names a brand (from the shops' brand fields, or a word that opens product names in
     several shops) or a model code, and has at least three words. Generic names like "Këpucë me takë" or
     "Pantallona të shkurtra" in two shops are never treated as one product
  3. the sizes are equal. A title with two sizes uses the variant's ("Shampoo *250ml - 500ml" is 500 ml); a set
     ("Toner 30ml + Serum 10ml") only matches the same set. A row with no size joins only when the name exists in
     exactly one size AND its price is within 50% of it; build_seed.py then lists it apart, outside the comparison.
     Rows with no size are compared with each other only when no shop states any size for that name
  4. its price is plausible for the group: under half or over double the group's typical price means a different
     size or pack, so that row is dropped
  5. the shop doesn't sell several different products under the same name (we couldn't tell which one is meant)
Precision over recall: a wrong match shows a false "cheaper elsewhere", which is worse than a missed one.
"""
import collections
import hashlib
import re
import sqlite3
import statistics
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent

STOP = {
    "the", "and", "for", "with", "of", "de", "la", "le", "di", "per", "me", "dhe", "e", "i", "te", "ne", "nga",
    "a", "an", "in", "on", "by", "x", "pcs", "cope",
}
# Words that describe a product but never identify one: types, colours, materials, people. Never a brand.
GENERIC = set("""
bluze bluza maice kemishe fustan fund xhinse xhins pantallona shkurtra xhakete xhup pallto triko pulover kardigan
jelek kostum tuta pizhame breke sutjena corape rroba banjo kepuce atlete cizme sandale papuce take cante canta
portofol rrip shall kapele ore ora syze unaze varese vathe byzylyk zinxhir bizhuteri set kit pako cope
dress skirt shirt tshirt top jeans pants trousers shorts jacket coat sweater hoodie socks shoes sneakers boots
sandals slippers bag bags wallet belt scarf hat watch sunglasses ring necklace earrings bracelet
krem cream creme serum toner tonik lotion locion gel xhel maske mask shampo shampoo balsam conditioner sapun soap
spray oil vaj parfum parfume perfume deodorant pastrues cleanser scrub balm lipstick mascara pudra powder
femra meshkuj burra gra vajza djem femije bebe baby kids men women woman man unisex junior
zeze zi bardhe kuqe blu gri roze jeshile kafe bezhe portokalli verdhe vjollce ari argjend
black white red blue grey gray pink green brown beige orange yellow purple gold silver navy
pambuk lesh lekure leather cotton wool denim mini maxi midi long short gjate shkurter
per me dhe nga pa new ri original classic basic sport sportive
""".split())
UNIT = {"ml": "ml", "l": "l", "lt": "l", "g": "g", "gr": "g", "gram": "g", "kg": "kg", "oz": "oz", "fl": "oz"}
SIZE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|lt|l|gr|gram|g|kg|fl\.?\s*oz|oz)\b")
# pack counts: "30 Tablets", "*30KAPS", "60 capsules", "20 bustina" are the size of supplements and wipes
COUNT_RE = re.compile(r"(\d{1,4})\s*(tablets?|tableta|tabs?|caps(ules?)?|kapsula|kaps|softgels?|sachets?|bustina|"
                      r"ampula|ampoules?|cope|pcs|pieces|wipes|letra)\b")
BARE_SIZE_RE = re.compile(r"\s[-–]\s*(\d{1,4})\s*$")  # "Cream - 50" (variant title without a unit)
# shop labels around the size ("vëllimi: 236 ml", "Masa: 100 ML", "50 ml x 1")
LABELS_RE = re.compile(r"\b(vellimi|volumi|masa|madhesia|sasia|size|volume|format|permbajtja)\b\s*:?|\bx\s*1\b|\b1\s*x\b")
# the same word in Albanian and English, or spelled two ways
SAME = {"krem": "cream", "creme": "cream", "kremi": "cream", "shampo": "shampoo", "shampon": "shampoo", "xhel": "gel",
        "locion": "lotion", "maske": "mask", "masque": "mask", "ampula": "ampoule", "shkume": "foam", "mousse": "foam",
        "serumi": "serum", "tonik": "toner", "moisturiser": "moisturizer", "moisturising": "moisturizing",
        "hidratues": "moisturizing", "pastrues": "cleanser", "balsam": "conditioner", "vaj": "oil"}
CLOTHING_SIZES = {"s", "m", "l", "xs", "xl", "xxl", "xxxl", "2xl", "3xl"}
# words shops add or leave out for the same product: "CeraVe Hydrating (Facial) Cleanser", "(Women)" on a perfume
NOISE = {"facial", "natural", "original", "new", "korean", "official", "authentic", "genuine"}
PERFUME_WORDS = {"eau", "parfum", "toilette", "edp", "edt", "extrait", "cologne", "perfume", "parfume"}
# gender labels shops add after a perfume's name ("(Women)", "për femra"); words inside names stay (Uomo, Homme, Men)
GENDER_LABEL_RE = re.compile(r"\((women|woman|men|man|unisex|femra|meshkuj|for (wo)?men)\)|\bper (femra|meshkuj)\b|\(?unisex\)?")


def fold(s):
    s = unicodedata.normalize("NFKD", s.lower().replace(" ", " ").replace("\xa0", " "))
    return "".join(ch for ch in s if not unicodedata.combining(ch))


VARIANT_SEP_RE = re.compile(r"\s[-–]\s")  # "Product name - 500ml": what follows is the variant


def size_of(m):
    """A SIZE_RE match as (value, unit), litres and kilos in ml and g so "1 L" == "1000 ml"."""
    v, u = float(m.group(1).replace(",", ".")), m.group(2)
    u = "oz" if "oz" in u else UNIT.get(u, u)
    if u in ("l", "kg"):
        v, u = v * 1000, "ml" if u == "l" else "g"
    return round(v, 2), u


def size_label(val, unit):
    """How a size reads on the site: "250 ml", "60 copë", or a set's "10ml+50ml"."""
    if val is None:
        return None
    if unit and "+" in unit:
        return unit
    return f"{val:g} {'copë' if unit == 'pcs' else unit}" if unit else f"{val:g}"


def parse(title):
    t = LABELS_RE.sub(" ", fold(title))
    if any(w in t for w in PERFUME_WORDS) or "(" in t:
        t = GENDER_LABEL_RE.sub(" ", t)
    # "Eau de Parfum" = "EDP"; a leading "Parfum" ("Parfum Tom Ford Noir Extreme") only says it's a perfume.
    # A later "Parfum" is a concentration (Sauvage Parfum is not Sauvage EDP) and stays.
    t = t.replace("eau de parfum", " edp ").replace("eau de toilette", " edt ").replace("extrait de parfum", " extrait ")
    t = re.sub(r"^[\s\W]*(parfume|parfum|perfume)\s+((per|for) (femra|meshkuj|women|men)\s+)?", " ", t)
    size = None
    sizes = list(SIZE_RE.finditer(t))
    if sizes:
        metric = [m for m in sizes if size_of(m)[1] != "oz"] or sizes  # "30ml (1 fl oz)" is one size
        distinct = {size_of(m) for m in metric}
        if len(distinct) == 1:
            size = size_of(metric[0])  # every mention agrees: "Effaclar K+ 40 ml - 40 ml"
        else:
            seps = [m.end() for m in VARIANT_SEP_RE.finditer(t)]
            last = metric[-1]
            if seps and last.start() >= seps[-1] and not re.search(r"\+|,|\bdhe\b|\band\b", t[seps[-1]:]):
                size = size_of(last)  # the variant's own size wins over the name's: "Shampo *250ml - 500ml" is 500 ml
            else:
                # a set ("Toner 30ml + Serum 10ml + Cream 20g"): only the same set matches it
                size = (0.0, "+".join(f"{v:g}{u}" for v, u in sorted(distinct, key=lambda x: (x[1] or "", x[0]))))
        t = SIZE_RE.sub(" ", t)
    counts = list(COUNT_RE.finditer(t))
    if counts:
        if not size:
            size = (float(counts[0].group(1)), "pcs")
        t = COUNT_RE.sub(" ", t)
    if not size:
        b = BARE_SIZE_RE.search(t)
        if b:
            size = (float(b.group(1)), None)
            t = t[: b.start()]
    words = set()
    for w in re.findall(r"[a-z0-9%+]+", t):
        plus = w.endswith("+") and len(w.strip("+")) > 0
        w = w.strip("+")
        w = SAME.get(w, w) + ("+" if plus else "")  # "k+" stays, a lone "+" goes
        # single letters are kept ("Effaclar H" vs "Effaclar K+", "Vitamin C"); clothing sizes are not
        if not w or w in STOP or w in CLOTHING_SIZES:
            continue
        words.add(w)
    words -= NOISE
    return " ".join(sorted(words)), size


def same_size(a, b):
    return a[0] == b[0] and (a[1] is None or b[1] is None or a[1] == b[1])


def size_by_price(price, size_price):
    """The one size whose typical price this price clearly matches, or None if it's ambiguous."""
    close = [x for x, ref in size_price.items() if ref / 1.15 <= price <= ref * 1.15]
    if len(close) != 1:
        return None
    far = all(not (ref / 1.35 < price < ref * 1.35) for x, ref in size_price.items() if x != close[0])
    return close[0] if far else None


def main():
    con = sqlite3.connect(HERE / "data" / "phia.db", timeout=120)
    con.execute("CREATE TABLE IF NOT EXISTS matches (product_id INTEGER PRIMARY KEY, group_id TEXT NOT NULL)")
    con.execute("CREATE INDEX IF NOT EXISTS matches_group ON matches(group_id)")

    price_of = {}
    by_name = collections.defaultdict(list)
    for pid, shop, title, price, cur in con.execute("SELECT id, shop, title, price, currency FROM products WHERE price > 0"):
        key, size = parse(title)
        price_of[pid] = (price, cur)
        if len(key.split()) >= 2:  # one word ("Bluza") is too vague to match on
            by_name[key].append((pid, shop, size))

    # rule 2: brand words = tokens of the shops' brand fields, and words that open product names in 2+ shops
    brands = collections.Counter()
    for (b,) in con.execute("SELECT brand FROM products WHERE brand IS NOT NULL AND brand != ''"):
        for w in re.findall(r"[a-z0-9]+", fold(b)):
            brands[w] += 1
    openers = collections.defaultdict(set)
    for pid, shop, title in con.execute("SELECT id, shop, title FROM products WHERE price > 0"):
        first = re.findall(r"[a-z0-9]+", fold(title))[:1]
        if first:
            openers[first[0]].add(shop)
    shop_words = {w for (d,) in con.execute("SELECT domain FROM shops") for w in re.findall(r"[a-z0-9]+", d)}
    brand_words = {w for w, n in brands.items() if n >= 2} | {w for w, shops in openers.items() if len(shops) >= 2}
    brand_words = {w for w in brand_words if len(w) >= 2 and not w.isdigit() and w not in GENERIC and w not in shop_words}

    def specific(key):
        words = key.split()
        code = any(re.search(r"\d", w) and re.search(r"[a-z]", w) and len(w) >= 3 for w in words)
        return (code or len(words) >= 3) and (code or any(w in brand_words for w in words))

    stats = collections.Counter()
    rows = []
    for key, items in by_name.items():
        if len({shop for _, shop, _ in items}) < 2:
            continue
        if not specific(key):
            stats["generic name"] += 1
            continue
        sizes = []
        for _, _, s in items:
            if s and not any(same_size(s, x) for x in sizes):
                sizes.append(s)
        # typical price of each known size, and how many shops state it
        size_price, size_shops = {}, {}
        for x in sizes:
            ps = [(price_of[pid][0], shop) for pid, shop, s in items if s and same_size(s, x)]
            size_price[x] = statistics.median(p for p, _ in ps)
            size_shops[x] = len({sh for _, sh in ps})
        unsized = []
        for pid, shop, s in items:
            if s:
                target = next(x for x in sizes if same_size(s, x))
            elif len(sizes) == 1 and size_shops[sizes[0]] >= 2:
                # rule 3: a row without a size joins only when every shop that states a size states the same one
                # (2+ shops), so the product comes in one size, and its price is within 50% of that size's price.
                # It's listed apart on the site ("doesn't state the size") and never counts as the cheapest.
                ref = size_price[sizes[0]]
                if not (ref / 1.5 <= price_of[pid][0] <= ref * 1.5):
                    stats["no size, price off"] += 1
                    continue
                target = sizes[0]
            elif len(sizes) > 1 and (fit := size_by_price(price_of[pid][0], size_price)):
                # several sizes exist (15 ml at 880 L, 50 ml at ~1 750 L): a row without a size joins the one size
                # its price clearly belongs to, within 15% of it and 35%+ away from every other size
                target = fit
            else:
                unsized.append((pid, shop))
                continue
            gid = hashlib.md5(f"{key}|{target}".encode()).hexdigest()[:12]
            rows.append((pid, gid))
        # Rows with no size are compared with each other only when no shop states any size for this name
        # (if it's sold as 50 ml and 100 ml somewhere, two unsized rows could be either). Never perfumes:
        # a perfume always comes in several sizes.
        if sizes and unsized:
            stats["no size, product has sizes"] += len(unsized)
        elif len({shop for _, shop in unsized}) >= 2 and not set(key.split()) & (PERFUME_WORDS | {"edp", "edt"}):
            ps = [price_of[pid][0] for pid, _ in unsized]
            if max(ps) <= min(ps) * 1.25:
                gid = hashlib.md5(f"{key}|unknown".encode()).hexdigest()[:12]
                rows.extend((pid, gid) for pid, _ in unsized)
            else:
                stats["no size, prices disagree"] += len(unsized)
        elif unsized:
            stats["no size, nothing to compare"] += len(unsized)

    # rule 4: drop rows whose price is implausible for the group (per currency)
    by_group = collections.defaultdict(list)
    for pid, gid in rows:
        by_group[(gid, price_of[pid][1])].append(pid)
    keep = set()
    for (gid, cur), pids in by_group.items():
        med = statistics.median(price_of[p][0] for p in pids)
        for p in pids:
            if med / 2 <= price_of[p][0] <= med * 2:
                keep.add(p)
            else:
                stats["price implausible"] += 1
    rows = [(p, g) for p, g in rows if p in keep]

    # A shop that sells several *different* products under one name+size (Rogers: many "ATLETE CALVIN KLEIN
    # JEANS - BLACK / 40" at different URLs and prices) can't be matched: we wouldn't know which one is meant.
    # Variants of one product share a page URL (Shopify ?variant=), so they don't count as different products.
    info = {pid: (shop, (url or "").split("?")[0], price)
            for pid, shop, url, price in con.execute("SELECT id, shop, url, price FROM products")}
    pages = collections.defaultdict(set)
    for pid, gid in rows:
        shop, page, price = info[pid]
        pages[(gid, shop)].add((page, price))
    ambiguous = {k for k, v in pages.items() if len({p for p, _ in v}) > 1 and len({pr for _, pr in v}) > 1}
    rows = [(p, g) for p, g in rows if (g, info[p][0]) not in ambiguous]

    # keep only groups that really span 2+ shops after the size split
    shops_per_group = collections.defaultdict(set)
    for pid, gid in rows:
        shops_per_group[gid].add(info[pid][0])
    rows = [(p, g) for p, g in rows if len(shops_per_group[g]) >= 2]

    con.execute("DELETE FROM matches")
    con.executemany("INSERT INTO matches (product_id, group_id) VALUES (?, ?)", rows)
    con.commit()
    groups = len({g for _, g in rows})
    print(f"{groups:,} products matched across 2+ shops ({len(rows):,} shop listings)")
    print("left out:", dict(stats))


if __name__ == "__main__":
    main()
