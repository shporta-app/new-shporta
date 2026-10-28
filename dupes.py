"""Dupes: cheaper products from another brand that do the same job as an expensive one.

Called by build_seed.py on the seed DB (tables products, items). Fills `dupes`. A dupe is NOT the same product,
so it never enters the exact-price comparison; the site shows it separately, with the reason.

Evidence we accept (nothing is guessed):
  inspired  the cheaper perfume names the original ("Frymëzuar nga Gucci Guilty", "inspired by …") and that
            original is in our data
  active    skincare with the same key active at the same strength (niacinamide 10%, retinol 0.3%, …)
            in the same kind of product (serum with serum), from another brand
A dupe must be at least 30% cheaper, per ml when both sizes are known (a 3 ml oil isn't cheaper than 100 ml).
"""
import collections
import re
import unicodedata

MIN_SAVING = 0.30
# "expensive things": an original must cost at least this much (lek) to be worth a dupe
MIN_ORIGINAL = {"parfume": 5000, "lekure": 2000, "grim": 1500}
NOT_A_PRODUCT = re.compile(r"\b(tester|set|kit|mini|sample|kampion|travel|gift|dhurate)\b")


def fold(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def ml(size_val, size_unit):
    if size_val and size_unit in ("ml", None):
        return size_val
    if size_val and size_unit == "l":
        return size_val * 1000
    return None


def first_word(title):
    w = re.findall(r"[a-z0-9]+", fold(title))
    return w[0] if w else ""


# ---------------------------------------------------------------- perfume: "inspired by"

INSPIRED_RE = re.compile(r"(?:frymezuar nga|frymezim nga|inspired by|inspiruar nga|e frymezuar nga)\s+(.+?)(?:\s+[-–|(]|$)")
GENDER = {"femra", "meshkuj", "per", "unisex", "women", "woman", "men", "man", "pour", "homme", "femme", "vajore",
          "extrait", "edp", "edt", "parfum", "eau", "de", "toilette", "parfume", "perfume", "ml", "the", "for", "and", "&"}
NOT_ORIGINAL = re.compile(r"frymezuar|inspired|inspiruar|aroma te frymezuara|\bdupe\b|alternative|version")


def inspired_pairs(products, items):
    by_item = collections.defaultdict(list)
    for p in products:
        by_item[p["item_id"]].append(p)
    originals = [it for it in items if it["cat"] == "parfume" and not NOT_ORIGINAL.search(fold(it["title"]))]
    orig_words = [(it, set(re.findall(r"[a-z0-9]+", fold(it["title"])))) for it in originals]
    pairs = []
    for it in items:
        m = INSPIRED_RE.search(fold(it["title"]))
        if not m:
            continue
        name = [w for w in re.findall(r"[a-z0-9]+", m.group(1)) if w not in GENDER]
        if len(name) < 2:  # "Diesel" alone could be any Diesel perfume
            continue
        hits = [o for o, words in orig_words if all(w in words for w in name) and o["id"] != it["id"]]
        if not hits:
            continue
        # the original most shops carry is the one people mean
        orig = max(hits, key=lambda o: (o["shops"], -len(o["title"])))
        pairs.append((orig, it, "inspired", f"Frymëzuar nga {m.group(1).strip().title()}"))
    return pairs, by_item


# ---------------------------------------------------------------- skincare: same active, same strength

ACTIVES = {
    "niacinamide": "Niacinamide", "retinol": "Retinol", "retinal": "Retinal", "hyaluronic": "Acid hialuronik",
    "vitamin c": "Vitaminë C", "ascorbic": "Vitaminë C", "salicylic": "Acid salicilik", "bha": "Acid salicilik",
    "glycolic": "Acid glikolik", "azelaic": "Acid azelaik", "tranexamic": "Acid tranexamik", "arbutin": "Arbutin",
    "mandelic": "Acid mandelik", "lactic": "Acid laktik", "urea": "Ure", "snail": "Mucinë kërmilli",
}
ACTIVE_RE = re.compile(r"(" + "|".join(ACTIVES) + r")[^0-9%]{0,14}(\d+(?:[.,]\d+)?)\s*%")
KINDS = [("serum", r"serum|essence|ampoule|booster|concentrate|drops"), ("toner", r"toner|tonik|exfoliant|liquid|solution"),
         ("cream", r"cream|krem|creme|moistur|gel cream|emulsion|lotion"), ("cleanser", r"cleans|pastrues|wash|foam"),
         ("mask", r"mask|maske|peel"), ("spot", r"spot|patch")]


def kind_of(title):
    t = fold(title)
    for k, rx in KINDS:
        if re.search(rx, t):
            return k
    return None


def active_pairs(items):
    groups = collections.defaultdict(list)
    for it in items:
        if it["cat"] != "lekure":
            continue
        acts = actives(it["title"])
        k = kind_of(it["title"])
        if acts and k:
            groups[(acts, k)].append(it)
    pairs = []
    for (acts, k), its in groups.items():
        for orig in its:
            for d in its:
                if d is orig or same_brand(d["title"], orig["title"]):
                    continue  # another brand only
                pairs.append((orig, d, "active", reason(acts)))
    return pairs


def actives(title):
    """Every key active with its strength: {("Niacinamide", "10"), ("Zinc", "1")}. A dupe must have all of them,
    at the same strengths (an AHA 30% + BHA 2% peel is not a BHA 2% toner)."""
    t = fold(title)
    known = {(ACTIVES[m.group(1)], pct(m.group(2))) for m in ACTIVE_RE.finditer(t)}
    # a strength we can't name ("+ Zinc 4%", "2%BHA") still counts: it must be there in both
    other = {("", pct(n)) for n in re.findall(r"(\d+(?:[.,]\d+)?)\s*%", t)} - {("", p) for _, p in known}
    return frozenset(known | other) if known else frozenset()


def reason(acts):
    return " + ".join(f"{a} {p}%" for a, p in sorted(acts) if a)


def pct(n):
    return f"{float(n.replace(',', '.')):g}"  # "10" stays 10, "0.30" becomes 0.3


def same_brand(a, b):
    """The same brand, also when spelled two ways ("K-SECRET" / "Ksecret")."""
    return first_word(a) == first_word(b) or re.sub(r"[^a-z0-9]", "", fold(a))[:5] == re.sub(r"[^a-z0-9]", "", fold(b))[:5]


# ---------------------------------------------------------------- makeup: well-known dupe pairs

# Makeup has no evidence in the name (no "inspired by", no active %), so these are dupes the beauty community widely
# compares. A pair appears only when both products are in our data; add a line when shops start carrying a new dupe.
# (original must match, original must not match, dupe must match, dupe must not match, dupe's name)
KNOWN = [
    (r"better than sex", r"mini|eyeliner|liner|primer|\bset\b|kit", r"lash princess", r"mini|\bset\b|primer", 'Essence Lash Princess'),
    (r"better than sex", r"mini|eyeliner|liner|primer|\bset\b|kit", r"lash paradise", r"mini|\bset\b|primer", "L'Oréal Lash Paradise"),
    (r"dior.*lip glow oil", r"mini|\bset\b", r"fat oil lip drip", r"mini|\bset\b", 'NYX Fat Oil Lip Drip'),
    (r"all nighter.*setting spray", r"mini|vitamin c|\bset\b", r"nyx.*setting spray.*matte|nyx.*matte.*setting spray", r"mini|\bset\b", 'NYX Matte Setting Spray'),
    # wait for shops to carry the dupe: e.l.f. Halo Glow, Camo Concealer, Poreless Putty, Camo Liquid Blush
    (r"charlotte tilbury.*flawless filter", r"mini|\bset\b", r"halo glow liquid filter", r"mini|\bset\b", 'e.l.f. Halo Glow Liquid Filter'),
    (r"shape tape", r"mini|\bset\b|contour", r"camo concealer", r"mini|\bset\b", 'e.l.f. 16HR Camo Concealer'),
    (r"porefessional", r"mini|\bset\b|powder|matte", r"poreless putty", r"mini|\bset\b", 'e.l.f. Poreless Putty Primer'),
    (r"rare beauty.*soft pinch liquid blush", r"mini|\bset\b", r"camo liquid blush", r"mini|\bset\b", 'e.l.f. Camo Liquid Blush'),
]


def known_pairs(items):
    pairs = []
    makeup = [it for it in items if it["cat"] in ("grim", "lekure")]
    for orig_rx, orig_not, dupe_rx, dupe_not, dupe_name in KNOWN:
        origs = [it for it in makeup if re.search(orig_rx, fold(it["title"])) and not re.search(orig_not, fold(it["title"]))]
        dps = [it for it in makeup if re.search(dupe_rx, fold(it["title"])) and not re.search(dupe_not, fold(it["title"]))]
        if not origs or not dps:
            continue
        for orig in origs:
            for d in sorted(dps, key=lambda x: (-x["shops"], x["min_price"]))[:2]:  # two shades are enough per original
                pairs.append((orig, d, "known", f"Dupe i njohur: {dupe_name}"))
    return pairs


# ---------------------------------------------------------------- build

def best_offer(item, offers, target_ml=None):
    """The offer to compare: in stock, cheapest; for multi-size pages the size closest to the original's."""
    live = [o for o in offers if o["in_stock"]] or offers
    if target_ml:
        sized = [o for o in live if ml(o["size_val"], o["size_unit"])]
        if sized:
            return min(sized, key=lambda o: (abs(ml(o["size_val"], o["size_unit"]) - target_ml), o["price"]))
    return min(live, key=lambda o: o["price"])


MAX_PER_PRODUCT = 3
CLOSENESS = {"inspired": 0, "known": 1, "active": 2}


def size_gap(a, b):
    """How far apart two sizes ("100 ml", "30 ml") are, as a ratio; unknown sizes last."""
    try:
        x, y = float(a.split()[0]), float(b.split()[0])
        return max(x, y) / min(x, y)
    except (AttributeError, ValueError, ZeroDivisionError, IndexError):
        return 99


def build(con):
    con.row_factory = __import__("sqlite3").Row
    products = [dict(r) for r in con.execute(
        "SELECT id, item_id, shop, title, price, currency, in_stock, size_val, size_unit, name_key FROM products")]
    items = [dict(r) for r in con.execute(
        "SELECT id, title, image, cat, shops, min_price, max_price, currency FROM items WHERE currency = 'ALL'")]
    insp, by_item = inspired_pairs(products, items)
    pairs = insp + active_pairs(items) + known_pairs(items)

    rows, seen = [], set()
    for orig, dupe, kind, reason in pairs:
        if (orig["id"], dupe["id"]) in seen or NOT_A_PRODUCT.search(fold(orig["title"])):
            continue
        o_off = by_item.get(orig["id"]) or []
        d_off = by_item.get(dupe["id"]) or []
        o_off = [x for x in o_off if x["currency"] == "ALL"]
        d_off = [x for x in d_off if x["currency"] == "ALL"]
        if not o_off or not d_off:
            continue
        o = best_offer(orig, o_off)
        o_ml = ml(o["size_val"], o["size_unit"])
        d = best_offer(dupe, d_off, target_ml=o_ml)
        d_ml = ml(d["size_val"], d["size_unit"])
        if o_ml and d_ml:
            saving = 1 - (d["price"] / d_ml) / (o["price"] / o_ml)
        elif (o_ml or d_ml) and kind != "known":
            continue  # one side's size unknown: can't tell if it's really cheaper
        elif o_ml or d_ml:
            saving = 1 - d["price"] / o["price"]  # makeup: sizes are similar and rarely stated; compare the price
        else:
            saving = 1 - d["price"] / o["price"]
        if saving < MIN_SAVING or d["price"] >= o["price"] or o["price"] < MIN_ORIGINAL.get(orig["cat"], 2000):
            continue
        if (orig["id"], d["name_key"]) in seen:
            continue  # the same dupe listed by two shops: show it once
        seen.add((orig["id"], dupe["id"]))
        seen.add((orig["id"], d["name_key"]))
        rows.append((orig["id"], dupe["id"], kind, reason, o["price"], d["price"],
                     f"{o['size_val']:g} {o['size_unit'] or 'ml'}" if o["size_val"] else None,
                     f"{d['size_val']:g} {d['size_unit'] or 'ml'}" if d["size_val"] else None,
                     round(saving * 100), d["id"]))
    # secondary to the price comparison, so few: per product only the closest ones. Closest = the strongest evidence
    # (the shop names the original, then a widely compared makeup pair, then the same active), then the nearest size
    per_orig = collections.defaultdict(list)
    for r in rows:
        per_orig[r[0]].append(r)
    rows = [r for rs in per_orig.values()
            for r in sorted(rs, key=lambda r: (CLOSENESS[r[2]], size_gap(r[6], r[7]), -r[8]))[:MAX_PER_PRODUCT]]
    con.executescript("""
        DROP TABLE IF EXISTS dupes;
        CREATE TABLE dupes (item_id TEXT, dupe_id TEXT, kind TEXT, reason TEXT, orig_price REAL, dupe_price REAL,
                            orig_size TEXT, dupe_size TEXT, save_pct INTEGER, dupe_product INTEGER);
    """)
    con.executemany("INSERT INTO dupes VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.executescript("CREATE INDEX dupes_item ON dupes(item_id, save_pct DESC); CREATE INDEX dupes_dupe ON dupes(dupe_id);")
    con.commit()
    con.row_factory = None
    kinds = collections.Counter(r[2] for r in rows)
    return len(rows), len({r[0] for r in rows}), dict(kinds)
