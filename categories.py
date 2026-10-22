"""Our product categories, decided from the product name (then the shop's own category text, then the shop's type).

How a category is chosen:
  - every category has words that NAME a product type ("vathë", "xhinse", "serum"); the one that appears FIRST in the
    title wins, because Albanian titles start with the noun ("Kostum me jakë dhe zinxhir" is a suit, not jewellery)
  - materials and colours never decide (a "24K gold" cream, a "silver" fridge, "Lattafa Ansaam Gold" perfume)
  - words with two meanings carry exceptions: "varëse rrobash" is a hanger, "teething ring" is for babies,
    "zinxhir" on clothes is a zip
  - pharmacies and perfume shops can only put a product under clothing, shoes, watches, glasses, bags or jewellery
    when the title starts with that word (Beauty Store's "Vathë flutur" are real earrings)
"""
import re
import unicodedata

CATEGORIES = [
    ("parfume", "Parfume",
     r"\bparfum|\bperfum|eau de (toilette|parfum|cologne)|\bedp\b|\bedt\b|\bextrait\b|kolonj|\bcologne|fragrance|body mist"),
    ("grim", "Grim",
     r"mascara|maskar|\brimel|lipstick|buzekuq|lip ?gloss|lip ?liner|lip ?tint|foundation|fondatin|\bpudr|\bpowder|"
     r"concealer|korrektor|eyeliner|eye ?liner|eye ?shadow|hije sysh|\bblush|\ballik|bronzer|highlighter|\bprimer|"
     r"\bbrows?\b|vetull|makeup|make up|\bgrim\b|manikyr|llak thonj|nail polish|\bthonj|cushion|palette|paleta|\blip\b|\blips\b|\bbuzesh|\bbuze\b"),
    ("floke", "Flokë", r"shampo|conditioner|balsam (per )?flok|\bhair\b|\bflok|keratin|ngjyre (per )?flok"),
    ("femije", "Fëmijë",
     r"\bbaby\b|\bbebe|femij|\bkids?\b|\bjunior|foshnj|neonat|teething|\blodr|\btoys?\b|pelena|biberon|oturak|\bpusket"),
    ("lekure", "Kujdesi i lëkurës",
     r"\bserum|\btoner|\btonik|cleans|pastrues|\bspf|sunscreen|kunder diellit|moistur|hidrat|\bessence|ampoule|"
     r"retinol|niacinamide|hyaluron|\bacne|\bakne|peeling|exfol|micellar|krem fytyr|\bface\b|fytyr|"
     r"eye cream|krem sysh|sheet mask|maske fytyr|\bcream|\bcreme|\bkrem|\blotion|\blocion|\bbalm\b|dermo"),
    ("trup", "Trupi & higjiena",
     r"\bbody\b|\btrupi?\b|\bdush|shower|deodorant|\bdeo\b|\bsapun|\bsoap|\bscrub|pasta dhemb|toothpaste|furce dhemb|"
     r"hand cream|krem duarsh"),
    ("kepuce", "Këpucë",
     r"kepuc|atlete|sneaker|\bshoes?\b|\bcizm|\bboots?\b|\bsandal(e|et|s)?\b|papuc|\bslippers?\b|mokasin|loafer|"
     r"\btaka\b|espadril|\bclogs?\b"),
    ("canta", "Çanta",
     r"\bcant[ae]\b|\bcantat\b|\bbag\b|\bbags\b|portofol|wallet|backpack|cante shpine|valixh|luggage|suitcase|crossbody|\btote\b"),
    ("ora", "Ora", r"\bore dore|\bora dore|\bora\b|\bwatch(es)?\b|smartwatch|chronograph"),
    ("syze", "Syze", r"\bsyze|sunglass|eyeglass|\bkorniz|contact lens|\blente kontakti"),
    ("bizhuteri", "Bizhuteri",
     r"\bunaz|(?<!teething )(?<!fidget )(?<!key )\bring\b|\bvarese\b(?! (rrobash|celes|per|tavani|muri))|necklace|"
     r"\bvathe|earring|byzylyk|bracelet|pendant|jewel|bizhuteri|zinxhir (ari|argjendi|qafe|per qafe)|"
     r"\bvarese qafe|\bgjerdan|\bbroshe|\bbrooch|\bpiercing"),
    ("sport", "Sport", r"\bsportive?\b|fitness|\btraining\b|\brunning\b|vrapim|futboll|\bgym\b|\byoga\b|\btuta\b"),
    ("veshje", "Veshje",
     r"\bbluz|\bfustan|\bxhins|pantallon|\bxhaket|\bxhup|\bpallto|\bkemish|\bfund\b|\btriko|pulover|\bmaic|"
     r"t-?shirt|\bdress|\bjeans\b|\bshirt\b|\bcoat\b|jacket|\bskirt|sweater|hoodie|\btop\b|\bbreke|sutjen|pizham|"
     r"lingerie|te brendshme|corape|\bsocks|\bkostum|blazer|kardigan|cardigan|\bpolo\b|bermuda|\bshorts\b|leggings|"
     r"\bjelek|pajama|\bbra\b|bodysuit|\bbody per femra|rroba banjo|bikini"),
]
LABELS = {c: label for c, label, _ in CATEGORIES}
ORDER = {c: i for i, (c, _, _) in enumerate(CATEGORIES)}
CAT_RE = [(c, re.compile(p)) for c, _, p in CATEGORIES]

# things that are never jewellery/clothing whatever words they share
NOT_JEWELLERY = re.compile(r"organizues|kuti per|llamb|cader|tavan|rrobash|celes|\bparfum|\bedp\b|\bedt\b|teething|fidget|lodr")
HOME = re.compile(r"\bllamb|\btavan|frigorifer|kolltuk|tavolin|karrige|\bdivan|ring light|televizor|\blaptop|"
                  r"\btelefon|\bkarikues|\bkabllo|kuzhin|tenxhere|\btigan|\bfshes")
# generic skincare words lose to a specific word anywhere in the name ("Cream Bronzer" is makeup)
WEAK = {"lekure": re.compile(r"\bcream|\bcreme|\bkrem|\blotion|\blocion|\bbalm\b")}
BEAUTY_SHOPS = {"beauty", "perfume"}
FASHION_CATS = {"veshje", "kepuce", "ora", "syze", "canta", "bizhuteri", "sport"}
SHOP_FALLBACK = {"perfume": "parfume", "shoes": "kepuce", "jewelry": "bizhuteri", "clothing": "veshje", "sport": "sport"}


def fold(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def first_category(text, shop_cat):
    if HOME.search(text):
        return "tjeter"
    best = None
    for cat, rx in CAT_RE:
        m = rx.search(text)
        if not m:
            continue
        if cat == "bizhuteri" and NOT_JEWELLERY.search(text):
            continue
        if shop_cat in BEAUTY_SHOPS and cat in FASHION_CATS and m.start() > 0:
            continue  # a pharmacy's "Krem me ar" is not jewellery; its "Vathë flutur" (title starts with it) is
        weak = cat in WEAK and WEAK[cat].fullmatch(m.group(0) or "") is not None
        key = (m.start() + (10_000 if weak else 0), ORDER[cat])
        if best is None or key < best[0]:
            best = (key, cat)
    return best[1] if best else None


# when the name says nothing, a specialist shop's name does: verdewatches.al sells watches, optica.al glasses
SHOP_NAME_FALLBACK = [("ora", re.compile(r"watch|\bora\b|tufina|orlette|enzoattini")),
                      ("syze", re.compile(r"optik|optic|optica|syze|lente"))]


def classify(title, category_raw, shop_cat, shop=""):
    for text in (fold(title), fold(category_raw)):
        cat = first_category(text, shop_cat)
        if cat:
            if shop_cat == "perfume" and cat in FASHION_CATS:
                return "parfume"
            return cat
    for cat, rx in SHOP_NAME_FALLBACK:
        if rx.search(shop or ""):
            return cat
    return SHOP_FALLBACK.get(shop_cat, "tjeter")
