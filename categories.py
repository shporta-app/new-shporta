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
     r"\bbrows?\b|vetull|\blaps (sysh|buzesh|per sy|per buze|per vetulla)|\bfurre thonj|makeup|make up|\bgrim\b|manikyr|llak thonj|nail polish|\bthonj|cushion|palette|paleta|setting spray|fixing spray|setting powder|finishing powder|\blip\b|\blips\b|\bbuzesh|\bbuze\b"),
    ("floke", "Flokë", r"shampo|conditioner|balsam (per )?flok|\bhair\b|\bflok|keratin|ngjyre (per )?flok"),
    ("femije", "Fëmijë",
     r"\bbaby\b|\bbebe|femij|\bkids?\b|\bjunior|foshnj|neonat|teething|\blod[eë]?r|\btoys?\b|pelena|biberon|oturak|\bpusket"),
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
    ("ora", "Ora", r"\bore\b(?! (pune|shkolle|mesimi))|\bore dore|\bora dore|\bora\b|\bwatch(es)?\b|smartwatch|chronograph"),
    ("syze", "Syze", r"\bsyze|sunglass|eyeglass|\bkorniz|contact lens|\blente kontakti"),
    ("bizhuteri", "Bizhuteri",
     r"\bunaz|(?<!teething )(?<!fidget )(?<!key )\bring\b|\bvarese\b(?! (rrobash|celes|per|tavani|muri))|necklace|"
     r"\bvathe|earring|byzylyk|bracelet|pendant|jewel|bizhuteri|zinxhir (ari|argjendi|qafe|per qafe)|"
     r"\bvarese qafe|\bgjerdan|\bbroshe|\bbrooch|\bpiercing"),
    ("sport", "Sport", r"\bsportive?\b|fitness|\btraining\b|\brunning\b|vrapim|futboll|\bgym\b|\byoga\b|\btuta\b"),
    # electronics: phones, computers, TV, audio, gaming, and their accessories
    ("teknologji", "Teknologji",
     r"\btelefon|\bcelular|smartphone|\biphone|\bipad\b|macbook|\blaptop|\bnotebook\b|chromebook|\btablet\b(?! ?(vitamin|mg|klor))|"
     r"\bkufje|headphone|earbuds|airpods|headset|televizor|\bsmart tv\b|\bmonitor\b|\bkompjuter|\bcomputer|\bpc\b|"
     r"playstation|\bps[45]\b|\bxbox|nintendo|\bkonsol|\bgaming\b|\bleve loje|\bssd\b|\bhdd\b|hard disk|\busb\b|"
     r"\brouter|\bmodem|printer|\bprintues|\bkarikues|\bcharger|power ?bank|\bkabllo|\bcable\b|(?<!mickey )\bmouse\b|\bmaus\b|"
     r"tastier|keyboard|\bkamera\b|\bcamera\b|\bgopro|\bdron|altoparlant|\bspeaker|soundbar|projektor|projector|"
     r"smartwatch|\bsmart ?band|\bgalaxy (s|a|z|tab|watch|buds)|\bredmi\b|\bxiaomi\b|\bprocesor|\bram\b|karte grafike|graphics card"),
    # large and small household appliances
    ("elektroshtepiake", "Elektroshtëpiake",
     r"frigorifer|lavatrice|rrobalares|lavastovilj|pjatalares|\bfurr[eë]\b(?! thonj)|mikroval|microwave|kondicioner|air condition|"
     r"aspirator|fshese elektrike|vacuum|\bhekur (rrobash|me avull)|\bmakine (kafeje|kafe|larese|qepese)|espresso|"
     r"blender|\bmikser|\bmixer\b|\bfriteze|air ?fryer|tharese (rrobash|duarsh)|\bngrohes|\bstufe\b|\bventilator|"
     r"kaldaj|boiler|\bsanduic|toaster|\bthekë|\bkettle|ibrik elektrik|zgare elektrike|robot (kuzhine|pastrues)"),
    # furniture, home, kitchen, garden, DIY
    ("shtepi", "Shtëpi & kuzhinë",
     r"\bmobilj|\bdivan|kolltuk|karrige|tavolin|\bkrevat|\bdyshek|mattress|\braft|\bdollap|komodin|\bllamb|\btavan|"
     r"\btapet|\bqilim|\bperde|\bjastek|carcaf|\bbatanij|\bmbules|tenxhere|\btigan|\bpjat[aë]\b|\bgota\b|filxhan|"
     r"\bthika\b|luge|pirun|\bene kuzhin|kuzhin[eë]s?\b|\bvazo|pasqyr|dekor|organizues|\bkuti\b|\bvegl|\bdrapan|"
     r"trapan|\bbojë mur|\bboje mur|kopsht|garden|\bvazo lulesh|\bçekiç|\bcekic|\bkacavid|\bshpues|\bdrill\b|\bsharre|"
     r"\bbojatis|\bfurniture|\bsofa\b|\bchair\b|\btable\b|\bbed\b|\blamp\b|\bpillow|\bblanket|\bcookware|\bpan\b"),
    ("libra", "Libra & zyrë",
     r"\blib[eë]r\b|\blibra\b|\broman\b|\bbook\b|\bbooks\b|\bnovel\b|\bfletor|\bblloks|\bstilolaps|\blaps(a|at)? (me ngjyra|grafit|shkolle)|"
     r"\bçant[aë] shkolle|\bcante shkolle|\bmaterial(e)? shkollore|\bzyre\b|\bletër a4|\bleter a4"),
    ("kafshe", "Kafshë",
     r"\bqen\b|\bqeni|\bmace\b|\bmaces|\bkafsh|\bpet\b|\bpets\b|\bdog\b|\bdogs\b|\bcat food|\bpuppy|\bkitten|"
     r"\brere per mace|\bzogj|\bpeshk akuarium|akuarium"),
    ("auto", "Auto & moto",
     r"\bgom[aë]\b|\bgoma makin|\btyres?\b|\btires?\b|vaj motori|motor oil|\bbateri makin|\bpjes[eë] k[eë]mbimi|"
     r"\bper makine\b|\bcar (charger|holder|mount|seat)|\bmotorr|\bhelmet[eë]?\b|\bkaska\b|\bwiper|fshirese xhami"),
    ("ushqime", "Ushqime & pije",
     r"\bkafe (kokërr|kokerr|e bluar|espresso|kapsula)|\bcoffee (beans|capsules|ground)|\bçaj\b|\bcaj\b|\bsheqer|\boriz\b|\bmakarona|"
     r"\bvaj ulliri|olive oil|\bbirr[eë]|\bver[eë]\b|\bwine\b|\bwhisk|\bvodka|\bçokollat|\bcokollat|\bbiskot|"
     r"\bqumësht|\bqumesht|\bdjath|\bmjalt|\bhoney\b|\bmiell(i|in)?\b|\bdrith|\bsnack|\bpije energjike|\bujë mineral|\buje mineral"),
    ("shendet", "Shëndet & suplemente",
     r"suplement|supplement|probiotik|probiotic|multivitamin|\bomega ?3|\d+ ?(kapsula|kaps|capsules?|tableta|tablets?|"
     r"softgels?|sachets?|bustina)\b|\d+ ?mcg\b|\bampula pije|termomet|tensiomet|\bmaske mjekesore|"
     r"\bdorez[ae]? (mjekesore|nitril|latex|vinil)|glukomet|\binhalator|"
     r"\bnebulizator|\bfasho|\bortoz|\bortopedik"),
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
HOME = re.compile(r"ring light")  # beauty shops' lights: not jewellery ("ring"), not skincare
# generic skincare words lose to a specific word anywhere in the name ("Cream Bronzer" is makeup)
WEAK = {"lekure": re.compile(r"\bcream|\bcreme|\bkrem|\blotion|\blocion|\bbalm\b")}
BEAUTY_SHOPS = {"beauty", "perfume"}
FASHION_CATS = {"veshje", "kepuce", "ora", "syze", "canta", "bizhuteri", "sport", "teknologji", "elektroshtepiake",
                "shtepi", "libra", "kafshe", "auto", "ushqime"}
SHOP_FALLBACK = {"perfume": "parfume", "shoes": "kepuce", "jewelry": "bizhuteri", "clothing": "veshje", "sport": "sport",
                 "tech": "teknologji", "gaming": "teknologji", "appliances": "elektroshtepiake", "home": "shtepi",
                 "diy": "shtepi", "kids": "femije", "books": "libra", "office": "libra", "pets": "kafshe", "auto": "auto",
                 "grocery": "ushqime", "health": "shendet"}


def fold(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def first_category(text, shop_cat):
    if HOME.search(text):
        return "shtepi"
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
