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
  0. or: both carry the same barcode (GTIN/EAN with a valid check digit), even when the shops name it very
     differently ("Lansinoh Perla 3-N-1" / "THERAPEARL 3IN1 - LANSINOH"). Shops do make barcode mistakes (one gives
     Mustela's 50 ml cream the 100 ml code), so a barcode never joins two different sizes, two products we already
     keep apart, a shop's barcode written on several different names, nor a price far from the group's (rule 4)
Tech: "8/256GB", "256 GB" and "256gb" read the same, the storage is the size, and a phone's "5G" is not 5 grams.
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
LABELS_RE = re.compile(r"\b(vellimi|volumi|masa|madhesia|sasia|size|volume|format|permbajtja|ngjyra|color|colour)\b\s*:?|\bx\s*1\b|\b1\s*x\b"
                       r"|\b(marka|brand|sex|gjinia|pesha|lloji)\s*:")  # "Marka: DSQUARED², Sex: Unisex"
# the same word in Albanian and English, or spelled two ways
SAME = {"krem": "cream", "creme": "cream", "kremi": "cream", "shampo": "shampoo", "shampon": "shampoo", "xhel": "gel",
        "locion": "lotion", "maske": "mask", "masque": "mask", "ampula": "ampoule", "shkume": "foam", "mousse": "foam",
        "serumi": "serum", "tonik": "toner", "moisturiser": "moisturizer", "moisturising": "moisturizing",
        "hidratues": "moisturizing", "pastrues": "cleanser", "balsam": "conditioner", "vaj": "oil", "baume": "balm"}
CLOTHING_SIZES = {"s", "m", "l", "xs", "xl", "xxl", "xxxl", "2xl", "3xl"}
# words shops add or leave out for the same product: "CeraVe Hydrating (Facial) Cleanser", "(Women)" on a perfume
NOISE = {"facial", "natural", "original", "new", "korean", "official", "authentic", "genuine",
         "zgjidhni", "nje", "opsion"}  # "Zgjidhni një opsion: 90" (choose an option)
CONCENTRATIONS = {"edp", "edt", "parfum", "extrait", "edc", "cologne"}
# words shops add to describe what a product is for, in either language ("Serum për flokë", "Hair Mask")
DESCRIPTIONS = set("""hair floke flokeve floku flokesh flokut kujdes thate thata forcim skin lekure lekuren
treatment trajtim per""".split())
# product types: a name without one ("8H Magic Night") may join the same name with it ("8H Magic Night Serum")
TYPE_WORDS_BEAUTY = set("""cream serum toner lotion gel mask shampoo conditioner soap spray oil balm cleanser foam
fluid essence ampoule emulsion mist scrub""".split())
# words that make another product (another edition, strength, pack, shade or person), never a line name
VARIANT_WORDS = set("""refill rimbushes rimbushese tester set kit mini travel sample intense intensive intensement
elixir extreme absolu absolue noir nuit night day jour plus forte max ultra rich riche light legere lite fresh
sport summer winter limited edition gift duo trio pack bundle box men women homme femme uomo donna kids baby junior
child children teen pour for him her tinted mat matte glow gloss shine oud
hand hands duar dore foot feet kembe kembet lip lips buze buzet eye eyes sy syve nail nails thonj thonjve body trup trupi
face fytyre fytyren fytyres scalp beard mjekerr intim intimate sun dielli after pas pre post
waterproof waterprooof refillable double""".split())
# makeup: the words after the name are shades ("Orgasm" / "Orgasm Rush"), so only exact names match there
MAKEUP_WORDS = set("""blush lipstick foundation concealer mascara eyeshadow shadow gloss liner eyeliner pencil
powder bronzer highlighter palette brow lip tint cushion primer rimel rimelit buzekuq pudra fondatine""".split())


def line_word(w):
    """A word that can name a product line ("Nutritive", "Genesis"): letters only, not a type, description,
    colour, variant or perfume word."""
    return (w.isalpha() and len(w) >= 4 and w not in GENERIC and w not in VARIANT_WORDS and w not in DESCRIPTIONS
            and w not in TYPE_WORDS_BEAUTY and w not in PERFUME_WORDS and w not in CONCENTRATIONS)
PERFUME_WORDS = {"eau", "parfum", "toilette", "edp", "edt", "extrait", "cologne", "perfume", "parfume"}
# perfume and its spin-offs: a word more is another scent, so only exact names (and rule 5) match there
SCENT_WORDS = PERFUME_WORDS | CONCENTRATIONS | {"vapo", "aftershave", "deodorant", "deo", "shower", "dush", "edc"}
# gender labels shops add after a perfume's name ("(Women)", "për femra"); words inside names stay (Uomo, Homme, Men)
GENDER_LABEL_RE = re.compile(r"\((women|woman|men|man|unisex|femra|meshkuj|for (wo)?men)\)|\bper (femra|meshkuj)\b|\(?unisex\)?")


# Shops that sell used / vintage items: never "the same product" as a new one, and labelled wherever they appear.
SECOND_HAND = {"thrift.al"}
# a title that says who it's for; "(Men)" and "(Women)" on the same name are two different perfumes
MEN_RE = re.compile(r"\b(men|man|homme|uomo|meshkuj|him|male|masculin)\b")
WOMEN_RE = re.compile(r"\b(women|woman|femme|donna|femra|her|female|feminin)\b")
# the words that name a separate men's / women's line of a product ("Light Blue Pour Homme")
MEN_WORDS = {"men", "man", "homme", "uomo", "him", "male", "masculin", "meshkuj"}
WOMEN_WORDS = {"women", "woman", "femme", "donna", "her", "female", "feminin", "femra"}


# phones, computers and other electronics: their numbers are storage, memory, screen and power, not grams or ml
# Brands that are also ordinary words or names ("Lattafa Honor & Glory", a "Galaxy" eyeshadow) count only with a
# model number after them ("Honor 90", "Galaxy S24"); anything sold by the ml or gram, or named as a perfume, is not tech.
TECH_RE = re.compile(r"\b(iphone|ipad|macbook|imac|xiaomi|huawei|oneplus|laptop|notebook|chromebook|smartphone|telefon|"
                     r"celular|smartwatch|airpods|earbuds|kufje|headphones?|headset|monitor|televizor|playstation|ps5|ps4|"
                     r"xbox|nintendo|ssd|hdd|router|printer|powerbank|power bank|karikues|charger|tastier[eë]?|keyboard|"
                     r"procesor|processor|rtx|gtx|geforce|radeon)\b"
                     r"|\b(galaxy|redmi|poco|oppo|realme|pixel|nokia|motorola|honor|vivo|lenovo)\s+(tab\b|note\b|watch\b|buds\b|"
                     r"fold|flip|magic|[a-z]{0,2}\d)")
# grams count from 10 g ("5G" on a phone is the network); ml, kg and oz always
NOT_TECH_RE = re.compile(r"\d\s*(ml|gr|kg|oz)\b|\d{2,}\s*g\b|\b(edp|edt|parfum|eau|extrait|cologne|perfume|parfume)\b")
TECH_UNITS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(gb|tb|mb|mah|wh|w|hz|mp|mm|l|lt)\b")
TECH_INCH_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:\"|''|”|inch(?:es)?|inç|in\b)")
TECH_RAM_STORAGE_RE = re.compile(r"\b(\d{1,2})\s*(?:gb)?\s*/\s*(\d{2,4})\s*(gb|tb)\b")  # "8/256GB" = 8 GB RAM, 256 GB


def valid_gtin(code):
    """A barcode (EAN-8, UPC-12, EAN-13, GTIN-14) with a correct check digit, as 14 digits; None otherwise."""
    g = re.sub(r"\D", "", str(code or ""))
    if len(g) not in (8, 12, 13, 14) or len(set(g)) == 1:
        return None
    digits = [int(x) for x in g]
    body = digits[:-1][::-1]
    total = sum(x * (3 if i % 2 == 0 else 1) for i, x in enumerate(body))
    return g.zfill(14) if (10 - total % 10) % 10 == digits[-1] else None


def gender_of(title):
    """"men" / "women" when the title says who it's for (and not both), else None."""
    t = fold(title)
    men, women = bool(MEN_RE.search(t)), bool(WOMEN_RE.search(t))
    return None if men == women else "men" if men else "women"


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
    if TECH_RE.search(t) and not NOT_TECH_RE.search(t):
        return parse_tech(t)
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
            tail = {size_of(m) for m in metric if seps and m.start() >= seps[-1]}
            if len(tail) > 1 and re.search(r"/|\bor\b|\bose\b", t[seps[-1]:]):
                size = None  # the title offers a choice ("- 50 ml / 100 ml"): we can't tell which one this price is
            elif seps and last.start() >= seps[-1] and not re.search(r"\+|,|\bdhe\b|\band\b", t[seps[-1]:]):
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
    if size and size[0]:
        words.discard(f"{size[0]:g}")  # "Serum 90ml - 90": the variant's bare number is the size again
    return " ".join(sorted(words)), size


def parse_tech(t):
    """A phone, laptop or other device: "Samsung Galaxy S24 5G 8/256GB Black" -> words with "8gb", "256gb", "5g";
    the storage (the largest GB/TB figure) is the size. Units are written one way so shops' spellings agree."""
    t = TECH_RAM_STORAGE_RE.sub(lambda m: f" {m.group(1)}gb {m.group(2)}{m.group(3)} ", t)
    t = TECH_INCH_RE.sub(lambda m: f" {m.group(1).replace(',', '.')}inch ", t)
    t = TECH_UNITS_RE.sub(lambda m: f" {m.group(1).replace(',', '.')}{m.group(2)} ", t)
    storage = [(float(v) * (1000 if u == "tb" else 1)) for v, u in re.findall(r"\b(\d+(?:\.\d+)?)(gb|tb)\b", t)]
    big = [x for x in storage if x >= 16]  # 16 GB and up is storage; 4/8/12 GB is memory
    size = (max(big), "gb") if big else None
    if not size:  # an appliance's capacity ("Friteze 5,5L", "Furre mikrovale 20L"), in ml like other litres
        litres = re.findall(r"\b(\d+(?:\.\d+)?)(?:l|lt)\b", t)
        if len(set(litres)) == 1:
            size = (round(float(litres[0]) * 1000, 2), "ml")
    words = set()
    for w in re.findall(r"[a-z0-9%+.]+", t):
        w = w.strip(".+")
        if not w or w in STOP or w in CLOTHING_SIZES:
            continue
        words.add(w)
    words -= NOISE
    if words & set(TECH_BRAND_OF):
        # a phone, laptop or console of a known line: what kind of device it is and labels like "RAM" or "Dual SIM"
        # are words some shops write and others don't. Accessories keep every word ("Mbajtëse për telefon" is not
        # "Mbajtëse për tablet", a wireless charger is not a cable one)
        words -= TECH_LABELS
        words |= {TECH_BRAND_OF[w] for w in words if w in TECH_BRAND_OF}  # "iPhone 15" is "Apple iPhone 15"
    return " ".join(sorted(words)), size


# words some shops write and others leave out, never what tells two devices apart
TECH_LABELS = set("""telefon telefoni celular celulari smartphone mobile laptop laptopi notebook kufje headphones
headphone ram rom memory memorie storage dual sim dualsim ds 5g 4g lte nfc unlocked global version""".split())
TECH_BRAND_OF = {"iphone": "apple", "ipad": "apple", "macbook": "apple", "imac": "apple", "airpods": "apple",
                 "galaxy": "samsung", "redmi": "xiaomi", "poco": "xiaomi", "pixel": "google", "playstation": "sony",
                 "ps5": "sony", "ps4": "sony", "xbox": "microsoft", "ideapad": "lenovo", "thinkpad": "lenovo",
                 "zenbook": "asus", "vivobook": "asus", "pavilion": "hp", "elitebook": "hp", "inspiron": "dell",
                 "latitude": "dell", "xps": "dell"}


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
    key_brands = collections.defaultdict(set)  # the words of the brand the shops give for each name
    brand_names = collections.defaultdict(set)
    parsed = {}  # pid -> (name key, size), for the barcode rule
    for pid, shop, title, price, cur, brand in con.execute(
            "SELECT id, shop, title, price, currency, brand FROM products WHERE price > 0"):
        key, size = parse(title)
        price_of[pid] = (price, cur)
        parsed[pid] = (key, size)
        if len(key.split()) >= 2 and shop not in SECOND_HAND:  # one word ("Bluza") is too vague to match on
            by_name[key].append((pid, shop, size))
            if brand:
                brand_names[key].add(" ".join(re.findall(r"[a-z0-9]+", fold(brand))))
    # a name's brand counts only when all its shops give the same one ("Pour Homme EDT" from Versace and Lacoste
    # listings is two perfumes, so it gets no brand)
    for key, names in brand_names.items():
        if len(names) == 1:
            key_brands[key] = set(next(iter(names)).split())

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

    # rule 5: the same name with one word left out. "Mancera Red Tobacco" is "Mancera Red Tobacco EDP" when the
    # perfume exists only as EDP in our shops; "Retisil Intensive Serum" is "Sesderma Retisil Intensive Serum" when
    # that's the only brand that sells it. Only when exactly one fuller name exists (a perfume sold as both EDT and
    # EDP stays apart), and sizes and prices are still checked below as for any other match.
    extra_of = collections.defaultdict(set)
    for key in by_name:
        words = set(key.split())
        # the left-out word is a concentration, or the brand the shops themselves give for the fuller name
        for w in words & (CONCENTRATIONS | (key_brands[key] & brand_words)):
            extra_of[" ".join(sorted(words - {w}))].add(key)
    alias = {}
    for key in list(by_name):
        fuller = extra_of.get(key, set())
        if len(fuller) != 1 or not specific(key):
            continue
        target = next(iter(fuller))
        added = set(target.split()) - set(key.split())
        if added <= CONCENTRATIONS and set(key.split()) & CONCENTRATIONS:
            continue  # "X EDT" never becomes "X EDT EDP"
        if not added <= CONCENTRATIONS and not added <= key_brands[key]:
            continue  # a brand is filled in only when the listing's own shop gives that brand
        alias[key] = target
        stats["name completed (one word left out)"] += len(by_name[key])
    # rule 6: the same product written with descriptions added or left out. "Kerastase 8H Magic Night Serum",
    # "Kérastase Nutritive 8H Magic Night Serum 90ml – Kujdes për flokë të thatë" and "8H Magic Night Serum 90 ml"
    # (brand in the shop's brand field) are one serum. A shorter name joins a fuller one when the extra words are
    # only descriptions ("hair", "për flokë"), the brand its own shop gives, a product type the shorter name doesn't
    # have, or one product-line word ("Nutritive") — and only when every fuller name adds the same line word, so
    # "Light Blue" never joins "Light Blue Intense" or "Light Blue Pour Homme" (words that make another product
    # never count, see VARIANT_WORDS). Sizes are still compared and prices checked as for every completed name.
    by_rule5 = set(alias)  # a concentration or brand filled in: the tighter price check below
    posting = collections.defaultdict(set)
    for key in by_name:
        for w in key.split():
            posting[w].add(key)
    parent = {}

    def root(k):
        while parent.get(k, k) != k:
            k = parent[k]
        return k

    # brands as the shops' brand fields name them (not title openers: "Nutritive …" opens titles but is a line)
    field_brands = {w for w, n in brands.items() if n >= 2 and len(w) >= 3 and w not in GENERIC}
    shop_cat = dict(con.execute("SELECT domain, category FROM shops"))
    beauty = {k for k, items in by_name.items() if all(shop_cat.get(s) in ("beauty", "perfume") for _, s, _ in items)}
    shops_of = {k: {s for _, s, _ in items} for k, items in by_name.items()}
    for key in list(by_name):
        words = set(key.split())
        core = words - DESCRIPTIONS - TYPE_WORDS_BEAUTY - key_brands[key]
        core -= MEN_WORDS | WOMEN_WORDS | {"pour", "for"}
        if key not in beauty or words & (MAKEUP_WORDS | SCENT_WORDS) or not specific(key) or len(core) < 2:
            continue  # beauty and pharmacy only: in clothing "Washed", "Pebble" are another colour or finish
        # ties in alphabetical order: a set's order changes from run to run, and so would the groups (and their ids)
        rare = sorted(words, key=lambda w: (len(posting[w]), w))[:2]
        fuller = (posting[rare[0]] & posting[rare[-1]]) - {key}
        if any(set(t.split()) & SCENT_WORDS for t in fuller if words < set(t.split())):
            continue  # a perfume's name: a word more is another scent ("Pour Homme" / "Aqua Pour Homme")
        typed = bool(words & TYPE_WORDS_BEAUTY)
        ok, lines = [], set()
        for t in (fuller & beauty) - {k for k in fuller if set(k.split()) & MAKEUP_WORDS}:
            extra = set(t.split()) - words
            if not extra or not words < set(t.split()):
                continue
            rest = extra - DESCRIPTIONS - key_brands[key] - (set() if typed else TYPE_WORDS_BEAUTY)
            if len(rest) > 1 or any(not line_word(w) or w in field_brands for w in rest):
                continue  # another product: "Intense", "Refill", a shade number, a second line word…
            if rest and shops_of[key] & shops_of[t]:
                continue  # one shop sells both: "Collagen Cream" and "Collagen Deep Cream" are two products
            ok.append(t)
            lines.add(frozenset(extra - DESCRIPTIONS - key_brands[key]))  # a type it adds counts as its line too
        if len(lines - {frozenset()}) > 1:
            # two different lines or types ("+ Serum", "+ Toner"): only names that add descriptions join
            ok = [t for t in ok if not set(t.split()) - words - DESCRIPTIONS - key_brands[key]]
        for t in ok:
            a, b = root(key), root(t)
            if a != b:
                parent[a] = b
    groups_of = collections.defaultdict(list)
    for k in parent:
        groups_of[root(k)].append(k)
    for r, ks in groups_of.items():
        members = set(ks) | {r}
        canon = max(sorted(members), key=lambda k: (len({s for _, s, _ in by_name[k]}), len(k), k))  # the most shops' name

        def rest(k):  # what still differs from the chosen name once descriptions, brand and type are set aside
            a, b = set(k.split()), set(canon.split())
            d = (a ^ b) - DESCRIPTIONS - key_brands[k] - key_brands[canon]
            if not a & TYPE_WORDS_BEAUTY or not b & TYPE_WORDS_BEAUTY:
                d -= TYPE_WORDS_BEAUTY
            return d
        # names from two brands never become one product ("Kerastase" and "Kérastase Paris" are one brand)
        # and every name must show that brand, in its title or its own shop's brand field ("Dry Body Oil" alone
        # could be any brand's)
        main = key_brands[canon] or next((key_brands[k] for k in sorted(members) if key_brands[k]), set())
        members = {k for k in members if main and (key_brands[k] or set(k.split())) & main}
        if canon not in members:
            continue
        # a name that differs by more than descriptions, sold by a shop that also sells the chosen name, is another
        # product of that shop (the chains above can link "Cleansing Oil Mild" to "Cleansing Oil" through a third name)
        plain_shops = set().union(*(shops_of[k] for k in members if k == canon or not rest(k)))
        members = {k for k in members if k == canon or not (rest(k) and shops_of[k] & plain_shops)}
        rests = {k: rest(k) for k in members - {canon}}
        line = set().union(*rests.values()) if rests else set()
        if len(line) > 1 or any(not line_word(w) for w in line):
            members = {canon} | {k for k, d in rests.items() if not d}  # checked directly: descriptions only
        for k in members - {canon}:
            alias[k] = canon
        stats["name completed (descriptions)"] += sum(len(by_name[k]) for k in members - {canon})

    def final(k):
        seen = set()
        while k in alias and k not in seen:
            seen.add(k)
            k = alias[k]
        return k
    alias = {k: final(k) for k in alias if final(k) != k}
    completed = {}  # rows that joined under a fuller name -> how far their price may be from the full name's
    for key, target in alias.items():
        if key in by_name:
            completed.update({pid: 1.25 if key in by_rule5 else 1.5 for pid, _, _ in by_name[key]})
            by_name[target].extend(by_name.pop(key))
    con.execute("CREATE TABLE IF NOT EXISTS key_alias (key TEXT PRIMARY KEY, canonical TEXT)")
    con.execute("DELETE FROM key_alias")
    con.executemany("INSERT INTO key_alias VALUES (?, ?)", alias.items())

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

    # rule 0: the same barcode in 2+ shops is the same product, whatever the names say (see the top of the file)
    via_gtin = set()
    gid_of = dict(rows)
    shop_of_pid, gtin_of = {}, {}
    for pid, shop, code in con.execute("SELECT id, shop, gtin FROM products WHERE price > 0 AND gtin IS NOT NULL AND gtin != ''"):
        g = valid_gtin(code)
        if g and shop not in SECOND_HAND and pid in parsed:
            gtin_of[pid], shop_of_pid[pid] = g, shop
    names_on = collections.defaultdict(set)  # (shop, barcode) -> the names that shop writes it on
    for pid, g in gtin_of.items():
        names_on[(shop_of_pid[pid], g)].add(parsed[pid][0])
    by_gtin = collections.defaultdict(list)
    for pid, g in gtin_of.items():
        if len(names_on[(shop_of_pid[pid], g)]) == 1:  # one barcode on several names: that shop's codes are unreliable
            by_gtin[g].append(pid)
    reliable = {p for ps in by_gtin.values() for p in ps}
    # A name group whose shops give two barcodes is usually one product in two packagings or markets (Davines,
    # SKIN1004), and stays. But when a row's barcode is also on a product we know under another name, the barcode
    # says what it is: one shop's "Mustela Gentle Shampoo" carries the code of the organic "Shampooing Doux Bio",
    # so it leaves the classic shampoo's group and joins the organic one through the barcode below.
    codes_in, keys_in, members = collections.defaultdict(set), collections.defaultdict(set), collections.defaultdict(list)
    for p, gid in rows:
        keys_in[gid].add(parsed[p][0])
        members[gid].append(p)
        if p in reliable:
            codes_in[gid].add(gtin_of[p])
    claimed = set()
    for gid, codes in codes_in.items():
        if len(codes) < 2:
            continue
        for p in members[gid]:
            if p in reliable and any(gid_of.get(q) != gid and parsed[q][0] not in keys_in[gid]
                                     for q in by_gtin[gtin_of[p]] if q != p):
                claimed.add(p)
    if claimed:
        stats["left a name group for the product its barcode names"] += len(claimed)
        rows = [(p, g) for p, g in rows if p not in claimed]
        gid_of = dict(rows)
    for g, pids in by_gtin.items():
        if len({shop_of_pid[p] for p in pids}) < 2:
            continue
        sizes = []
        for p in pids:
            sz = parsed[p][1]
            if sz and not any(same_size(sz, x) for x in sizes):
                sizes.append(sz)
        if len(sizes) > 1:
            stats["barcode on two sizes"] += 1
            continue
        groups = {gid_of[p] for p in pids if p in gid_of}
        if len(groups) > 1:
            stats["barcode across two products we keep apart"] += 1
            continue
        gid = next(iter(groups)) if groups else hashlib.md5(f"gtin|{g}".encode()).hexdigest()[:12]
        for p in pids:
            if p not in gid_of:
                gid_of[p] = gid
                rows.append((p, gid))
                via_gtin.add(p)
    stats["joined by barcode"] += len(via_gtin)

    # what visitors taught us: a listing that 3 different people reported as another product or size (feedback.py)
    try:
        import feedback
        reported = feedback.excluded()
    except Exception:
        reported = set()
    if reported:
        before = len(rows)
        rows = [(p, g) for p, g in rows if p not in reported]
        stats["reported by visitors as another product"] += before - len(rows)

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
    # a row whose name was completed must cost about the same as the rows that name it in full: within 25% for a
    # filled-in concentration or brand ("Mancera Red Tobacco" -> "... EDP"), within 50% when only descriptions
    # differed, so another concentration or edition at another price can't slip in
    for (gid, cur), pids in by_group.items():
        full = [price_of[p][0] for p in pids if p not in completed and p in keep]  # not rows rule 4 just dropped
        if not full:
            continue  # every shop left the same word out: they match each other as before
        med = statistics.median(full)
        for p in pids:
            if p in completed and not (med / completed[p] <= price_of[p][0] <= med * completed[p]):
                keep.discard(p)
                stats["completed name, price off"] += 1
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

    # A group whose titles say both "for men" and "for women" (and not "unisex" / "him & her") mixes two
    # products that share a name: keep the side most shops agree on.
    titles = {pid: fold(t) for pid, t in con.execute("SELECT id, title FROM products WHERE price > 0")}
    members = collections.defaultdict(list)
    for pid, gid in rows:
        members[gid].append(pid)
    drop = set()
    for gid, pids in members.items():
        men = {p for p in pids if MEN_RE.search(titles[p]) and not WOMEN_RE.search(titles[p])}
        women = {p for p in pids if WOMEN_RE.search(titles[p]) and not MEN_RE.search(titles[p])}
        if men and women:
            drop |= men if len(men) < len(women) else women if len(women) < len(men) else men | women
            stats["men/women label conflict"] += 1
    # A name that also exists as a separate men's or women's line ("Light Blue" next to "Light Blue Pour
    # Homme"): there the label is part of what the product is, so "(Men)" titles match only other "(Men)" titles.
    key_of = {pid: key for key, offs in by_name.items() for pid, _, _ in offs}
    has_men_line, has_women_line = set(), set()
    for key in by_name:
        words = set(key.split())
        for gender, line in ((MEN_WORDS, has_men_line), (WOMEN_WORDS, has_women_line)):
            if words & gender:
                line.add(" ".join(sorted(words - gender - {"pour", "for"})))
    relabel, gendered = {}, has_men_line | has_women_line
    for gid, pids in members.items():
        for p in pids:
            k = key_of.get(p)
            if k in gendered:
                gender = gender_of(titles[p])
                if gender:
                    relabel[p] = hashlib.md5(f"{gid}|{gender}".encode()).hexdigest()[:12]
                    stats["gender label on a name with a gendered sibling line"] += 1
    rows = [(p, relabel.get(p, g)) for p, g in rows if p not in drop]

    # keep only groups that really span 2+ shops after the size split
    shops_per_group = collections.defaultdict(set)
    for pid, gid in rows:
        shops_per_group[gid].add(info[pid][0])
    rows = [(p, g) for p, g in rows if len(shops_per_group[g]) >= 2]

    con.execute("DELETE FROM matches")
    if "via" not in {r[1] for r in con.execute("PRAGMA table_info(matches)")}:
        con.execute("ALTER TABLE matches ADD COLUMN via TEXT")  # 'gtin': joined by barcode, its size is the group's
    con.executemany("INSERT INTO matches (product_id, group_id, via) VALUES (?, ?, ?)",
                    [(p, g, "gtin" if p in via_gtin else None) for p, g in rows])
    con.commit()
    groups = len({g for _, g in rows})
    print(f"{groups:,} products matched across 2+ shops ({len(rows):,} shop listings)")
    print("left out:", dict(stats))


if __name__ == "__main__":
    main()
