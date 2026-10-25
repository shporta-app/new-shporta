"""What search engines and AI crawlers read: the page HTML with its own title, description, canonical address,
structured data (schema.org JSON-LD) and the page's content already in it, plus robots.txt, sitemaps and llms.txt.

The site is a single-page app (web/app.js draws every page in the browser). Google runs that script, late; most AI
crawlers (GPTBot, ClaudeBot, PerplexityBot) don't run it at all. So server.py answers every page with index.html in
which <main> already holds a plain version of the page; app.js then replaces it with the full one.

Only products sold by 2+ shops are indexed: a single shop's product is that shop's own page, nothing to compare.
"""
import html
import json
import re
from datetime import datetime
from pathlib import Path

BASE = "https://shporta.app"
WEB = Path(__file__).parent / "web"
OG_IMAGE = BASE + "/assets/og.png"
INDEXNOW_KEY = "029f48a586fe6c2bf319e1539d1d11dd"  # served at /<key>.txt; nightly.py tells Bing/Yandex what changed
SITEMAP_CHUNK = 10000
NAME = "shporta"
TAGLINE = "Krahaso çmimet e të njëjtit produkt në dyqanet online shqiptare"

e = html.escape


def lek(n, cur="ALL"):
    if cur == "EUR":
        return f"€{n:.2f}"
    if cur and cur != "ALL":
        return f"{n:.2f} {cur}"
    return f"{round(n):,}".replace(",", " ") + " L"


def day_sq(iso):
    months = ["janar", "shkurt", "mars", "prill", "maj", "qershor", "korrik", "gusht", "shtator", "tetor", "nëntor", "dhjetor"]
    d = datetime.fromisoformat(iso[:10])
    return f"{d.day} {months[d.month - 1]} {d.year}"


def ld(obj):
    # "</" inside a JSON string must not close the <script> element
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def page_html(title, desc, path, body, robots="index,follow", image=OG_IMAGE, data=(), og_type="website"):
    """index.html with this page's head tags and content."""
    canonical = BASE + path
    head = f"""<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(canonical)}">
<meta name="robots" content="{robots},max-image-preview:large,max-snippet:-1">
<meta property="og:site_name" content="shporta">
<meta property="og:locale" content="sq_AL">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(canonical)}">
<meta property="og:image" content="{e(image or OG_IMAGE)}">
<meta name="twitter:card" content="summary_large_image">
<link rel="alternate" type="text/plain" title="llms.txt" href="/llms.txt">
""" + "\n".join(ld(d) for d in data)
    tpl = (WEB / "index.html").read_text(encoding="utf-8")
    tpl = re.sub(r"<title>.*?</title>\s*<meta name=\"description\"[^>]*>", lambda m: head, tpl, count=1, flags=re.S)
    return tpl.replace('<main id="main" tabindex="-1"></main>', f'<main id="main" tabindex="-1" data-ssr>{body}</main>', 1)


def breadcrumbs(*crumbs):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": BASE + p}
                                for i, (n, p) in enumerate(crumbs)]}


def item_li(it):
    shops = it["in_stock_shops"] or it["shops"]
    price = f"nga {lek(it['min_price'], it['currency'])}" + (f" deri {lek(it['max_price'], it['currency'])}" if it["max_price"] > it["min_price"] else "")
    return (f'<li><a href="/produkt/{e(it["id"])}">{e(it["title"])}</a>: {price}'
            f'{f" në {shops} dyqane" if shops > 1 else ""}</li>')


# ------------------------------------------------------------------ pages

def home(srv):
    h = srv.cached_home()
    s = h["stats"]
    cats = "".join(f'<li><a href="/kategori/{e(c["id"])}">{e(c["label"])}</a> ({num(c["count"])} produkte)</li>'
                   for c in h["categories"] if c["count"])
    deals = "".join(item_li(d) for d in h["deals"][:16])
    imp = h.get("impact")
    fact = (f"<p>Për {num(imp['products'])} produkte që i shesin 3 ose më shumë dyqane, dyqani më i shtrenjtë kërkon zakonisht "
            f"{imp['median_more_pct']}% më shumë se më i liri, për të njëjtin produkt në të njëjtën madhësi.</p>") if imp else ""
    body = f"""<div class="wrap">
<h1>shporta: krahaso çmimet në dyqanet online shqiptare</h1>
<p>I njëjti produkt, në të njëjtën madhësi, kushton ndryshe në dyqane të ndryshme. shporta krahason çdo ditë
{num(s['offers'])} çmime nga {s['shops']} dyqane online në Shqipëri: kozmetikë, parfume, veshje, këpucë, syze, ora, teknologji, elektroshtëpiake, shtëpi e kuzhinë, libra, fëmijë, shëndet, kafshë dhe auto.
{num(s['compared'])} produkte i gjejmë në dy ose më shumë dyqane.</p>{fact}
<form action="/kerko" role="search"><label>Kërko produkt ose markë <input name="q" type="search"></label></form>
<h2>Kategoritë</h2><ul>{cats}</ul>
<h2>Diferencat më të mëdha sot</h2><ul>{deals}</ul>
<p><a href="/rreth">Si funksionon shporta</a> | <a href="/dupe">Dupe: alternativa më të lira</a> | <a href="/dyqanet">Dyqanet</a> | <a href="/shtesa">Shtesa për shfletuesin</a></p>
</div>"""
    org = {"@context": "https://schema.org", "@type": "Organization", "@id": BASE + "/#org", "name": NAME, "url": BASE + "/",
           "logo": BASE + "/assets/icon-512.png", "description": TAGLINE + ".", "areaServed": {"@type": "Country", "name": "Albania"},
           "knowsLanguage": ["sq", "en"]}
    site = {"@context": "https://schema.org", "@type": "WebSite", "@id": BASE + "/#website", "name": NAME, "url": BASE + "/",
            "inLanguage": "sq", "publisher": {"@id": BASE + "/#org"}, "description": TAGLINE + ".",
            "potentialAction": {"@type": "SearchAction", "target": {"@type": "EntryPoint", "urlTemplate": BASE + "/kerko?q={search_term_string}"},
                                "query-input": "required name=search_term_string"}}
    desc = (f"Krahaso çmimet e të njëjtit produkt në {s['shops']} dyqane online shqiptare: kozmetikë, parfume, veshje, "
            f"teknologji, shtëpi, libra dhe më shumë. Gjej ku kushton më lirë sot. Falas, çdo ditë.")
    return 200, page_html("shporta: krahaso çmimet në dyqanet online të Shqipërisë", desc, "/", body, data=[org, site])


def with_size(title, size):
    """"Anua Cleansing Oil - 200" + "200 ml" -> "Anua Cleansing Oil 200 ml" (a shop's bare number gets its unit once)."""
    if not size or size.lower().replace(" ", "") in title.lower().replace(" ", ""):
        return title
    title = re.sub(r"\s*[-–*:]?\s*" + re.escape(size.split()[0]) + r"\s*$", "", title)
    return f"{title} {size}"


def num(n):
    return f"{n:,}".replace(",", " ")


def product(srv, item_id):
    it = srv.item(item_id)
    if not it:
        return None
    offers = [o for o in it["offers"] if o["currency"] == it["currency"]]
    live = [o for o in offers if o["in_stock"]]
    shops = {o["shop"] for o in offers}
    lo = min((o["price"] for o in live), default=it["min_price"])
    hi = max((o["price"] for o in live), default=it["max_price"])
    cheapest = next((o for o in sorted(live, key=lambda o: o["price"])), None)
    title_name = with_size(it["title"], it.get("size"))
    many = len(shops) > 1
    if many and live:
        title = f"{title_name}: {lek(lo, it['currency'])} te më i liri, {len(shops)} dyqane | shporta"
        desc = (f"{title_name}: çmimi në {len(shops)} dyqane online në Shqipëri, nga {lek(lo, it['currency'])} deri "
                f"{lek(hi, it['currency'])}. Më i liri sot: {cheapest['shop'].removeprefix('www.') if cheapest else ''}. "
                f"Krahaso të njëjtën madhësi para se të blesh.")
    else:
        title = f"{title_name}: çmimi | shporta"
        desc = f"{title_name}: {lek(lo, it['currency'])}. Shiko çmimin dhe produkte të ngjashme në dyqane të tjera shqiptare."
    rows = "".join(
        f"<tr><td>{e(o['shop'].removeprefix('www.'))}</td><td>{e(o['title'])}</td><td>{lek(o['price'], o['currency'])}</td>"
        f"<td>{'në stok' if o['in_stock'] else 'pa gjendje'}</td></tr>" for o in it["offers"])
    updated = srv.meta("updated")
    body = f"""<div class="wrap">
<p><a href="/">shporta</a> › <a href="/kategori/{e(it['cat'])}">{e(it['category_label'])}</a></p>
<h1>{e(it['title'])}</h1>
{f"<p>Krahasojmë vetëm madhësinë {e(it['size'])}.</p>" if it.get('size') else ""}
<p>{f"Në {len(shops)} dyqane, nga {lek(lo, it['currency'])} deri {lek(hi, it['currency'])}." if many else f"Çmimi: {lek(lo, it['currency'])}."}
{f" Më i liri: {e(cheapest['shop'].removeprefix('www.'))}." if many and cheapest else ""}
{f" Çmimet u kontrolluan më {day_sq(updated)}." if updated else ""}</p>
<table><thead><tr><th>Dyqani</th><th>Emri te dyqani</th><th>Çmimi</th><th>Gjendja</th></tr></thead><tbody>{rows}</tbody></table>
{"<h2>Edhe në madhësi të tjera</h2><ul>" + "".join(item_li(x) for x in it["other_sizes"][:8]) + "</ul>" if it.get("other_sizes") else ""}
{"<h2>Produkte të ngjashme</h2><ul>" + "".join(item_li(x) for x in it["similar"][:8]) + "</ul>" if it.get("similar") else ""}
</div>"""
    data = [breadcrumbs(("shporta", "/"), (it["category_label"], f"/kategori/{it['cat']}"), (it["title"], f"/produkt/{item_id}"))]
    if offers:
        prod = {"@context": "https://schema.org", "@type": "Product", "name": title_name.strip(), "url": f"{BASE}/produkt/{item_id}",
                "category": it["category_label"]}
        if it.get("image"):
            prod["image"] = [it["image"]]
        brand = next((o.get("brand") for o in offers if o.get("brand")), None)
        if brand:
            prod["brand"] = {"@type": "Brand", "name": brand}
        if it.get("size"):
            prod["size"] = it["size"]
        each = [{"@type": "Offer", "price": round(o["price"], 2), "priceCurrency": o["currency"], "url": o["url"],
                 "availability": "https://schema.org/" + ("InStock" if o["in_stock"] else "OutOfStock"),
                 "seller": {"@type": "Organization", "name": o["shop"].removeprefix("www.")}} for o in offers if o.get("url")]
        prod["offers"] = {"@type": "AggregateOffer", "priceCurrency": it["currency"], "lowPrice": round(lo, 2),
                          "highPrice": round(hi, 2), "offerCount": len(shops),
                          "availability": "https://schema.org/" + ("InStock" if live else "OutOfStock"), "offers": each}
        data.append(prod)
    # indexed: a real comparison (2+ shops) of new products; a single shop's listing is that shop's page, not ours
    robots = "index,follow" if many and not it.get("used") else "noindex,follow"
    return 200, page_html(title, desc, f"/produkt/{item_id}", body, robots=robots, image=it.get("image"), data=data, og_type="product")


def category(srv, cat, q):
    page = srv.page_num(q)
    res = srv.category(cat, {"page": page} if page else {})
    if not res:
        return None
    path = f"/kategori/{cat}" + (f"?page={page}" if page else "")
    lis = "".join(item_li(x) for x in res["items"])
    pages = (res["total"] + srv.PAGE_SIZE - 1) // srv.PAGE_SIZE
    nav = (f'<p>{f"<a href=/kategori/{cat}?page={page - 1}>Faqja e mëparshme</a> " if page else ""}'
           f'{f"<a href=/kategori/{cat}?page={page + 1}>Faqja tjetër</a>" if page + 1 < pages else ""}</p>')
    body = f"""<div class="wrap"><p><a href="/">shporta</a> › <a href="/kategorite">Kategoritë</a></p>
<h1>{e(res['label'])}: krahaso çmimet</h1>
<p>{num(res['total'])} produkte në kategorinë {e(res['label'])} nga dyqanet online shqiptare. Të parat janë ato që i shesin më shumë dyqane.</p>
<ul>{lis}</ul>{nav}</div>"""
    data = [breadcrumbs(("shporta", "/"), ("Kategoritë", "/kategorite"), (res["label"], f"/kategori/{cat}")),
            {"@context": "https://schema.org", "@type": "ItemList", "name": res["label"],
             "itemListElement": [{"@type": "ListItem", "position": i + 1 + page * srv.PAGE_SIZE, "url": f"{BASE}/produkt/{x['id']}",
                                  "name": x["title"]} for i, x in enumerate(res["items"])]}]
    title = f"{res['label']}: krahaso çmimet në dyqanet online shqiptare" + (f", faqja {page + 1}" if page else "") + " | shporta"
    desc = (f"{res['label']} në Shqipëri: krahaso çmimet e {num(res['total'])} produkteve në dyqanet online. "
            f"I njëjti produkt dhe e njëjta madhësi, nga më i liri te më i shtrenjti.")
    # filtered or sorted lists are the same list: only the plain one (and its pages) is indexed
    robots = "noindex,follow" if set(q) - {"page"} else "index,follow"
    return 200, page_html(title, desc, path, body, robots=robots, data=data)


def categories(srv):
    h = srv.cached_home()
    lis = "".join(f'<li><a href="/kategori/{e(c["id"])}">{e(c["label"])}</a>: {num(c["count"])} produkte</li>' for c in h["categories"] if c["count"])
    body = f'<div class="wrap"><h1>Kategoritë</h1><ul>{lis}</ul></div>'
    return 200, page_html("Kategoritë: krahaso çmimet sipas kategorisë | shporta",
                          "Kozmetikë, parfume, grim, flokë, veshje, këpucë, syze, ora, bizhuteri dhe produkte për fëmijë: krahaso çmimet në dyqanet online shqiptare.",
                          "/kategorite", body, data=[breadcrumbs(("shporta", "/"), ("Kategoritë", "/kategorite"))])


def faq_pairs():
    src = (WEB / "pages" / "rreth.html").read_text(encoding="utf-8")
    pairs = re.findall(r"<h3>(.*?)</h3>\s*<p>(.*?)</p>", src, re.S)
    strip = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(s))).strip()
    return [(strip(q), strip(a)) for q, a in pairs]


def about(srv):
    body = (WEB / "pages" / "rreth.html").read_text(encoding="utf-8")
    faq = {"@context": "https://schema.org", "@type": "FAQPage",
           "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq_pairs()]}
    return 200, page_html("Si funksionon shporta: krahasimi i çmimeve në Shqipëri | shporta",
                          "shporta krahason çdo ditë çmimet e të njëjtit produkt në të njëjtën madhësi në dyqanet online shqiptare. Falas, pa llogari, nuk shet asgjë.",
                          "/rreth", body, data=[faq, breadcrumbs(("shporta", "/"), ("Si funksionon", "/rreth"))])


def shops_page(srv):
    rows = srv.shops()
    lis = "".join(f'<li><a href="https://{e(r["domain"])}" rel="nofollow">{e(r["domain"].removeprefix("www."))}</a>: {num(r["products"])} produkte</li>'
                  for r in rows if r["products"])
    body = f'<div class="wrap"><h1>Dyqanet që krahasojmë</h1><p>{len(rows)} dyqane online shqiptare.</p><ul>{lis}</ul></div>'
    return 200, page_html("Dyqanet online shqiptare që krahasojmë | shporta",
                          f"Lista e {len(rows)} dyqaneve online shqiptare që krahason shporta: kozmetikë, farmaci, parfumeri, modë, këpucë, syze dhe ora.",
                          "/dyqanet", body)


def dupes_page(srv, q):
    res = srv.dupe_list({})
    lis = "".join(f'<li><a href="/produkt/{e(r["orig_id"])}">{e(r["orig_title"])}</a> ({lek(r["orig_price"])}): '
                  f'alternativë <a href="/produkt/{e(r["dupe_id"])}">{e(r["dupe_title"])}</a> ({lek(r["dupe_price"])}), {e(r["reason"] or "")}</li>'
                  for r in res["items"])
    body = f"""<div class="wrap"><h1>Dupe: alternativa më të lira për produktet e shtrenjta</h1>
<p>Produkte të tjera, më të lira, që bëjnë të njëjtën punë. Nuk janë i njëjti produkt dhe nuk përzihen me krahasimin e çmimeve.</p>
<ul>{lis}</ul></div>"""
    return 200, page_html("Dupe: alternativa më të lira për parfume dhe kozmetikë | shporta",
                          "Alternativa më të lira për parfume dhe kujdes lëkure të shtrenjtë, me të njëjtin përbërës aktiv ose të frymëzuara nga origjinali, në dyqanet shqiptare.",
                          "/dupe", body, robots="noindex,follow" if q else "index,follow")


MUAJ = ["janar", "shkurt", "mars", "prill", "maj", "qershor", "korrik", "gusht", "shtator", "tetor", "nëntor", "dhjetor"]


def month_sq(m):
    """'2026-10' -> 'tetor 2026'"""
    return f"{MUAJ[int(m[5:7]) - 1]} {m[:4]}"


def report_page(srv, month=None):
    r = srv.report_with_history(month)
    if not r:
        return not_found()
    day = day_sq(r["updated"]) if r["updated"] else ""
    path = f"/raport/{month}" if month else "/raport"
    when = f"{month_sq(month)} (të dhënat e {day})" if month else f"të dhënat e {day}"
    prev = r.get("previous")
    trend = (f"<p>Në {month_sq(prev['month'])} kjo shifër ishte {prev['median_more_pct']}% ({lek(prev['median_diff'])} për produkt).</p>"
             if prev else "")
    archive = "".join(f'<li><a href="/raport/{m}">Raporti i {month_sq(m)}</a></li>' for m in r["months"] if m != month)
    archive = f"<h2>Raportet e mëparshme</h2><ul>{archive}</ul>" if archive else ""
    cats = "".join(f'<li><a href="/kategori/{e(c["id"])}">{e(c["label"])}</a>: {c["median_more_pct"]}% më shumë '
                   f'(diferenca tipike {lek(c["median_diff"])}, {num(c["products"])} produkte)</li>' for c in r["categories"])
    shops = "".join(f'<li>{e(s["shop"].removeprefix("www."))}: më i liri te {s["cheapest_pct"]}% e {num(s["products"])} produkteve, '
                    f'zakonisht {s["median_above_pct"]}% mbi çmimin më të ulët</li>' for s in r["shops_table"])
    big = "".join(item_li(it) for it in r["biggest"])
    lead = (f"Për {num(r['products'])} produkte që i shesin të paktën tre dyqane online në Shqipëri, në të njëjtën madhësi dhe në stok, "
            f"dyqani më i shtrenjtë kërkon zakonisht {r['median_more_pct']}% më shumë se më i liri ({lek(r['median_diff'])} për produkt). "
            f"Te {r['share_over_20']}% e produkteve diferenca kalon 20%, te {r['share_over_50']}% kalon 50%.")
    body = f"""<div class="wrap"><h1>Raporti i çmimeve: sa më shumë paguan për të njëjtin produkt</h1>
<p>{e(when.capitalize())}. {e(lead)}</p>{trend}
<h2>Sipas kategorisë</h2><ul>{cats}</ul>
<h2>Dyqanet</h2><ul>{shops}</ul>
<h2>Diferencat më të mëdha në lek</h2><ul>{big}</ul>
<h2>Si e llogaritëm</h2><p>Vetëm produkte të njëjta (marka, emri dhe madhësia), në stok në 3 ose më shumë dyqane, me çmim në lek. Për çdo dyqan merret çmimi i tij më i ulët për atë produkt. Diferencat mbi 70% lihen jashtë, sepse zakonisht janë dy produkte të ndryshme.</p>{archive}</div>"""
    desc = (f"Sa më shumë kushton i njëjti produkt te dyqani më i shtrenjtë në Shqipëri: zakonisht {r['median_more_pct']}% "
            f"({lek(r['median_diff'])}). Të dhëna për {num(r['products'])} produkte, sipas kategorisë dhe dyqanit, {day}.")
    dataset = {"@context": "https://schema.org", "@type": "Dataset", "name": "Raporti i çmimeve të shportës",
               "description": lead, "url": BASE + path, "inLanguage": "sq", "isAccessibleForFree": True,
               "creator": {"@id": BASE + "/#org"}, "spatialCoverage": {"@type": "Place", "name": "Albania"},
               "dateModified": (r["updated"] or "")[:10], "temporalCoverage": f"{r['tracked_since'] or ''}/{(r['updated'] or '')[:10]}",
               "variableMeasured": ["diferenca e çmimit mes dyqaneve (%)", "diferenca e çmimit mes dyqaneve (lek)"]}
    article = {"@context": "https://schema.org", "@type": "Article", "headline": "Sa më shumë paguan për të njëjtin produkt në Shqipëri",
               "description": desc, "inLanguage": "sq", "dateModified": r["updated"], "author": {"@id": BASE + "/#org"},
               "publisher": {"@id": BASE + "/#org"}, "mainEntityOfPage": BASE + path, "image": OG_IMAGE}
    crumbs = [("shporta", "/"), ("Raporti i çmimeve", "/raport")] + ([(month_sq(month), path)] if month else [])
    title = f"Raporti i çmimeve, {month_sq(month)}" if month else "Raporti i çmimeve në Shqipëri"
    return 200, page_html(f"{title}: sa më shumë paguan për të njëjtin produkt | shporta", desc, path, body,
                          data=[article, dataset, breadcrumbs(*crumbs)], og_type="article")


STATIC = {  # pages app.js draws itself; the server gives them a title, description and a short text
    "/shtesa": ("Shtesa për shfletuesin: krahaso çmimin ndërsa blen | shporta",
                "Shtesa e shportës për Edge dhe Firefox, ose butoni për çdo shfletues: në faqen e një dyqani online të tregon nëse i njëjti produkt kushton më pak diku tjetër në Shqipëri.",
                "Shtesa për shfletuesin", "index,follow"),
    "/privatesia": ("Cookies dhe privatësia | shporta", "Çfarë ruan shporta dhe pse.", "Cookies dhe privatësia", "index,follow"),
    "/ndaj": ("Krahaso një link | shporta", "Ngjit ose ndaj linkun e një produkti nga një dyqan online dhe shiko ku kushton më lirë.",
              "Krahaso një link", "noindex,follow"),
    "/shporta": ("Shporta ime | shporta", "Shto disa produkte dhe shiko ku t'i blesh që të paguash më pak, te një dyqan ose në dy.",
                 "Shporta ime", "noindex,follow"),
    "/lista": ("Produktet që ndjek | shporta", "Produktet që ruajte në këtë shfletues dhe sa ka ndryshuar çmimi që kur i ruajte.",
               "Produktet që ndjek", "noindex,follow"),
    "/kerko": ("Kërko | shporta", "Kërko një produkt ose markë në dyqanet online shqiptare.", "Kërko", "noindex,follow"),
}


def render(srv, path, q):
    """(status, html) for a page address; None when it isn't a page (static file or API)."""
    if path == "/":
        return home(srv)
    if path == "/kategorite":
        return categories(srv)
    if path == "/rreth":
        return about(srv)
    if path == "/dyqanet":
        return shops_page(srv)
    if path == "/dupe":
        return dupes_page(srv, q)
    if path == "/raport":
        return report_page(srv)
    m = re.fullmatch(r"/raport/(\d{4}-\d{2})", path)
    if m:
        return report_page(srv, m[1])
    m = re.fullmatch(r"/kategori/([\w-]+)", path)
    if m:
        return category(srv, m[1], q) or not_found()
    m = re.fullmatch(r"/produkt/([\w-]+)", path)
    if m:
        return product(srv, m[1]) or not_found()
    if path in STATIC:
        title, desc, h1, robots = STATIC[path]
        return 200, page_html(title, desc, path, f'<div class="wrap"><h1>{e(h1)}</h1><p>{e(desc)}</p></div>', robots=robots)
    return not_found()


def not_found():
    return 404, page_html("Kjo faqe nuk ekziston | shporta", "Kjo faqe nuk ekziston.", "/404",
                          '<div class="wrap"><h1>Kjo faqe nuk ekziston</h1><p><a href="/">Kthehu në faqen kryesore</a></p></div>',
                          robots="noindex,follow")


# ------------------------------------------------------------------ files for crawlers

AI_BOTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User", "PerplexityBot",
           "Perplexity-User", "Google-Extended", "Applebot-Extended", "Bingbot", "CCBot", "meta-externalagent", "DuckAssistBot"]


def robots_txt():
    rules = "Allow: /\nDisallow: /go/\nDisallow: /api/\nDisallow: /kerko\nDisallow: /ndaj\nDisallow: /lista\nDisallow: /shporta\nDisallow: /njoftim/\n"
    named = "".join(f"User-agent: {b}\n" for b in AI_BOTS)
    return (f"# shporta.app: price comparison for Albanian online shops. Search engines and AI assistants are welcome.\n"
            f"User-agent: *\n{rules}\n{named}{rules}\nSitemap: {BASE}/sitemap.xml\n")


def sitemap_index(srv):
    n = srv.db().execute("SELECT COUNT(*) FROM items WHERE shops >= 2").fetchone()[0]
    lastmod = (srv.meta("updated") or "")[:10]
    parts = ["faqet"] + [f"produkte-{i + 1}" for i in range((n + SITEMAP_CHUNK - 1) // SITEMAP_CHUNK)]
    body = "".join(f"<sitemap><loc>{BASE}/sitemap-{p}.xml</loc>{f'<lastmod>{lastmod}</lastmod>' if lastmod else ''}</sitemap>" for p in parts)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</sitemapindex>'


def urlset(urls, lastmod):
    body = "".join(f"<url><loc>{e(u)}</loc>{f'<lastmod>{lastmod}</lastmod>' if lastmod else ''}</url>" for u in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'


def page_urls(srv):
    cats = [r[0] for r in srv.db().execute("SELECT cat FROM items GROUP BY cat HAVING COUNT(*) > 0")]
    return [BASE + p for p in ("/", "/raport", "/kategorite", "/rreth", "/dupe", "/dyqanet", "/shtesa", "/privatesia")] + \
           [f"{BASE}/kategori/{c}" for c in cats] + [f"{BASE}/raport/{m}" for m in srv.report_months()]


def product_urls(srv, chunk=None):
    """Compared products, the most-compared first (also what nightly.py sends to IndexNow)."""
    sql = "SELECT id FROM items WHERE shops >= 2 ORDER BY shops DESC, save_pct DESC, id"
    if chunk is not None:
        sql += f" LIMIT {SITEMAP_CHUNK} OFFSET {chunk * SITEMAP_CHUNK}"
    return [f"{BASE}/produkt/{r[0]}" for r in srv.db().execute(sql)]


def sitemap(srv, name):
    lastmod = (srv.meta("updated") or "")[:10]
    if name == "faqet":
        return urlset(page_urls(srv), lastmod)
    m = re.fullmatch(r"produkte-(\d{1,3})", name)
    if m and int(m[1]) >= 1:
        urls = product_urls(srv, int(m[1]) - 1)
        return urlset(urls, lastmod) if urls else None
    return None


def llms_txt(srv):
    h = srv.cached_home()
    s, imp = h["stats"], h.get("impact")
    cats = "\n".join(f"- [{c['label']}]({BASE}/kategori/{c['id']}): {num(c['count'])} products" for c in h["categories"] if c["count"])
    deals = "\n".join(f"- [{d['title']}]({BASE}/produkt/{d['id']}): {lek(d['min_price'])} to {lek(d['max_price'])} across {d['in_stock_shops']} shops"
                      for d in h["deals"][:10])
    faq = "\n\n".join(f"### {q}\n{a}" for q, a in faq_pairs())
    updated = s.get("updated") or ""
    return f"""# shporta

> shporta.app is a free price comparison website for Albania. Every day it collects the prices that Albanian online shops publish (cosmetics, perfume, clothing, shoes, eyewear, watches, jewellery, electronics, home appliances, home and kitchen, books, toys and baby, health and supplements, pets, car parts), finds the exact same product in the same size across shops, and shows where it is cheapest today. Prices are in Albanian lek (ALL). shporta does not sell anything; every price links to the shop.

Key facts (updated {updated[:10]}):
- {num(s['offers'])} prices from {s['shops']} Albanian online shops; {num(s['compared'])} products found in two or more shops.
- Exact comparison only: same brand, same product name and same size (ml, g, pieces). Sets, testers and other sizes are never mixed in. Shops that don't state the size are shown separately and never counted as the cheapest.
- Prices are re-checked daily; a price not seen for 3 days is no longer shown. Daily price history shows drops, rises and the lowest price of the last 30 days.
{f"- For {num(imp['products'])} products sold by 3 or more shops, the most expensive shop typically asks {imp['median_more_pct']}% more than the cheapest one for the identical product." if imp else ""}
- Language of the site: Albanian (sq). Free, no account needed.
- Browser extension for Edge and Firefox, and a bookmark button for any browser, that compares the product page a shopper has open.
- "Dupes": cheaper different products that do the same job (same active ingredient at the same strength, or inspired-by perfumes), always listed apart from the price comparison.

When citing a price, link the product page on shporta.app and mention the date: shop prices change.

## Main pages
- [Home]({BASE}/): biggest price differences today
- [Price report]({BASE}/raport): how much more the same product costs across Albanian shops, by category and by shop (updated daily)
- [How it works and FAQ]({BASE}/rreth)
- [Categories]({BASE}/kategorite)
- [Shops compared]({BASE}/dyqanet)
- [Dupes]({BASE}/dupe): cheaper alternatives
- [Browser extension]({BASE}/shtesa)
- Search: {BASE}/kerko?q=<product or brand>

## Categories
{cats}

## Examples: the same product, different prices today
{deals}

## FAQ (Albanian)
{faq}
"""
