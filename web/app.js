// shporta: a small single-page app over /api. Pages: home, category, product, search, shops, extension.
const main = document.getElementById("main");

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const lek = (n, cur = "ALL") =>
  cur === "EUR" ? "€" + Number(n).toFixed(2) : Math.round(n).toLocaleString("en").replace(/,/g, " ") + " L";
const shopName = (d) => String(d || "").replace(/^www\./, "");
const plural = (n, one, many) => `${n.toLocaleString("en").replace(/,/g, " ")} ${n === 1 ? one : many}`;
const img = (src, alt = "") =>
  src ? `<img src="${esc(src)}" alt="${esc(alt)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'noimg',textContent:'Pa foto'}))">`
      : `<span class="noimg">Pa foto</span>`;

// Every link to a shop goes through /go/: we count the click and tag it utm_source=shporta.
const go_ = (o, item, from) => `/go/${o.id}?i=${encodeURIComponent(item || "")}&f=${from}`;
const shopLink = (o, item, from, cls = "", label = "Hape në dyqan") =>
  `<a class="${cls}" href="${go_(o, item, from)}" target="_blank" rel="noopener sponsored">${label}</a>`;

async function api(path) {
  const r = await fetch(path);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.error || `Gabim ${r.status}`), { status: r.status });
  return data;
}

/* ---------- shared pieces ---------- */

// One product, every shop's price: a bar per shop ending in a price tag; the cheapest in-stock one is lime.
function ruler(item, { heading = "h3", animate = false, linkHead = true, showHead = true, from = "ballina" } = {}) {
  const offers = (item.offers || []).filter((o) => o.currency === item.currency);
  if (!offers.length) return "";
  const max = Math.max(...offers.map((o) => o.price));
  const live = offers.filter((o) => o.in_stock);
  const best = live.length ? Math.min(...live.map((o) => o.price)) : null;
  const rows = offers.slice(0, 10).map((o, i) => {
    const w = Math.max(12, (o.price / max) * 100).toFixed(1);
    const cls = [o.in_stock && o.price === best ? "best" : "", o.in_stock ? "" : "out"].join(" ");
    return `<li class="${cls}" style="--i:${i}">
      <span class="shop" title="${esc(shopName(o.shop))}">${esc(shopName(o.shop))}</span>
      <span class="track"><span class="bar" style="--w:${w}%"></span>
        <a class="tag" style="--w:${w}%" href="${go_(o, item.id, from)}" target="_blank" rel="noopener sponsored"
           aria-label="${esc(shopName(o.shop))}: ${lek(o.price, o.currency)}${o.in_stock ? "" : ", s'ka gjendje"}">${lek(o.price, o.currency)}</a></span>
    </li>`;
  }).join("");
  const head = `${img(item.image, item.title)}<div><${heading}>${esc(item.title)}</${heading}>
      <small>${plural(offers.length, "dyqan", "dyqane")}${item.save_pct ? `, diferencë deri ${item.save_pct}%` : ""}</small></div>`;
  return `<div class="ruler${animate ? " animate" : ""}">
    ${!showHead ? "" : linkHead ? `<a class="ruler-head" href="/produkt/${esc(item.id)}" data-link>${head}</a>` : `<div class="ruler-head">${head}</div>`}
    <ol>${rows}</ol>
  </div>`;
}

function tile(it) {
  const range = it.shops > 1 && it.max_price > it.min_price
    ? `<small>kursen deri ${lek(it.max_price - it.min_price, it.currency)}</small>` : "";
  return `<a class="tile" href="/produkt/${esc(it.id)}" data-link>
    <span class="pic">${img(it.image, it.title)}</span>
    ${it.shops > 1 ? `<span class="chip">${plural(it.shops, "dyqan", "dyqane")}</span>` : ""}
    <span class="name">${esc(it.title)}</span>
    <span class="meta"><span class="num">${it.shops > 1 ? "nga " : ""}${lek(it.min_price, it.currency)}</span>${range}</span>
  </a>`;
}

function deal(it) {
  return `<a class="deal" href="/produkt/${esc(it.id)}" data-link>
    ${img(it.image, it.title)}
    <span><span class="name">${esc(it.title)}</span>
      <span class="range">${lek(it.min_price)} deri ${lek(it.max_price)} në ${plural(it.in_stock_shops, "dyqan", "dyqane")}</span></span>
    <span class="save">−${it.save_pct}%</span>
  </a>`;
}

// A dupe is another brand's product that does the same job for less. Never the same product: we say why it's a dupe.
const DUPE_WHY = {
  inspired: "Dyqani e shet si version të frymëzuar nga ky parfum.",
  active: "I njëjti përbërës kryesor, në të njëjtën përqindje, në të njëjtin lloj produkti.",
  known: "Dupe që komuniteti i bukurisë e krahason gjerësisht me origjinalin. Përbërësit nuk janë të njëjtë; ngjashmëria është te rezultati.",
};
function dupePair(r, { showOrig = true } = {}) {
  const size = (x) => (x ? ` <small>${esc(x)}</small>` : "");
  const orig = showOrig ? `<a class="dp-side" href="/produkt/${esc(r.orig_id)}" data-link>
      <span class="dp-pic">${img(r.orig_image, r.orig_title)}</span>
      <span><small>Origjinali</small><span class="dp-name">${esc(r.orig_title)}</span>
        <span class="num">${lek(r.orig_price)}${size(r.orig_size)}</span></span></a>` : "";
  return `<div class="dp${showOrig ? "" : " dp-single"}">
    ${orig}
    <a class="dp-side dp-dupe" href="/produkt/${esc(r.dupe_id)}" data-link>
      <span class="dp-pic">${img(r.dupe_image, r.dupe_title)}</span>
      <span><small>Dupe</small><span class="dp-name">${esc(r.dupe_title)}</span>
        <span class="num">${lek(r.dupe_price)}${size(r.dupe_size)}</span></span></a>
    <div class="dp-why"><span class="save">−${r.save_pct}%${r.orig_size && r.dupe_size && r.orig_size !== r.dupe_size ? " për ml" : ""}</span>
      <span class="chip">${esc(r.reason)}</span><small>${DUPE_WHY[r.kind] || ""}</small></div>
  </div>`;
}

function pager(data, base) {
  const pages = Math.ceil(data.total / data.page_size);
  if (pages <= 1) return "";
  const link = (p, label) => {
    const u = new URL(base, location.origin);
    u.searchParams.set("page", p);
    return `<a class="btn btn-ghost" href="${u.pathname}${u.search}" data-link>${label}</a>`;
  };
  return `<nav class="pager" aria-label="Faqet">
    ${data.page > 0 ? link(data.page - 1, "Më parë") : ""}
    <span>Faqja ${data.page + 1} nga ${pages}</span>
    ${data.page + 1 < pages ? link(data.page + 1, "Më tej") : ""}
  </nav>`;
}

const searchForm = (id, value = "") => `<form class="hero-search" role="search" data-search>
    <label class="sr" for="${id}">Kërko produkt</label>
    <input id="${id}" name="q" type="search" value="${esc(value)}" placeholder="p.sh. cerave, 345 relief cream, atlete nike">
    <button class="btn" type="submit">Kërko</button>
  </form>`;

/* ---------- pages ---------- */

let homeCache;
async function pageHome() {
  const d = homeCache || (homeCache = await api("/api/home"));
  const s = d.stats;
  setFoot(s.updated);
  let fi = Math.floor(Math.random() * Math.max(1, d.featured.length));
  main.innerHTML = `
  <section class="hero"><div class="wrap hero-in">
    <div>
      <h1>i njëjti produkt, çmime të ndryshme</h1>
      <p>Shiko sa kushton një produkt në çdo dyqan online në Shqipëri, para se ta blesh. Kozmetikë, parfume, veshje, këpucë dhe aksesorë.</p>
      ${searchForm("q-hero")}
      <div class="hero-stats">
        <span><b class="num">${s.offers.toLocaleString("en").replace(/,/g, " ")}</b>çmime</span>
        <span><b class="num">${s.shops}</b>dyqane online</span>
        <span><b class="num">${s.compared.toLocaleString("en").replace(/,/g, " ")}</b>produkte në 2+ dyqane</span>
      </div>
    </div>
    <div id="featured">${d.featured.length ? ruler(d.featured[fi], { animate: true }) : ""}
      ${d.featured.length > 1 ? `<div class="ruler-foot"><span>Të dhëna reale nga dyqanet</span><button type="button" id="next">Një produkt tjetër</button></div>` : ""}
    </div>
  </div></section>

  ${impactSection(d)}

  ${d.dupes && d.dupes.length ? `<section class="section"><div class="wrap">
    <div class="section-head"><h2>dupe të produkteve të shtrenjta</h2><a href="/dupe" data-link>Të gjitha dupe</a></div>
    <p class="lead">Jo i njëjti produkt, por bën të njëjtën punë për shumë më pak. Te parfumet, dyqani vetë thotë nga cili parfum është frymëzuar;
      te kujdesi i lëkurës, përbërësi kryesor dhe përqindja janë të njëjta; te grimi, janë dupe që krahasohen gjerësisht.</p>
    <div class="dps">${d.dupes.slice(0, 6).map((r) => dupePair(r)).join("")}</div>
  </div></section>` : ""}

  <section class="section"><div class="wrap">
    <div class="section-head"><h2>diferencat më të mëdha tani</h2></div>
    <p class="lead">I njëjti produkt, në stok në të paktën tre dyqane. Përqindja tregon sa më lirë është te dyqani më i lirë.</p>
    <div class="deals">${d.deals.map(deal).join("")}</div>
  </div></section>

  <section class="section"><div class="wrap">
    <h2>kategoritë</h2>
    <p class="lead">Çdo produkt që gjetëm, i renditur sipas llojit.</p>
    <div class="cats">${d.categories.filter((c) => c.count).map((c) =>
      `<a href="/kategori/${c.id}" data-link>${esc(c.label)}<span>${c.count.toLocaleString("en").replace(/,/g, " ")}</span></a>`).join("")}</div>
  </div></section>

  <section class="section"><div class="wrap">
    <div class="band">
      <div><h2>kontrollo çmimin kudo që blen</h2>
        <p>Shtesa e shportës për shfletuesin hapet vetë kur shikon një produkt në një dyqan online dhe të tregon nëse çmimi është i mirë, normal apo i lartë, dhe ku e gjen më lirë.</p>
        <a class="btn" href="/shtesa" data-link>Si ta instalosh</a></div>
      <ol><li>Hap një produkt në çdo dyqan online, edhe në Zara apo Mango.</li>
        <li>Shporta krahason çmimin me dyqanet e tjera.</li>
        <li>Blej aty ku është më lirë.</li></ol>
    </div>
  </div></section>`;
  const next = document.getElementById("next");
  if (next) next.onclick = () => {
    fi = (fi + 1) % d.featured.length;
    document.querySelector("#featured .ruler").outerHTML = ruler(d.featured[fi], { animate: true });
  };
}

// What not comparing costs: real numbers from the data, and a basic skincare routine priced both ways.
function impactSection(d) {
  const im = d.impact, r = d.routine;
  if (!im) return "";
  const receipt = r ? `<div class="receipt" aria-label="Rutina bazë e kujdesit për lëkurën">
      <div class="receipt-head"><span>Rutina bazë e lëkurës</span><span>Më lirë</span><span>Më shtrenjtë</span></div>
      ${r.steps.map((s) => `<a class="receipt-row" href="/produkt/${esc(s.id)}" data-link>
          <span><small>${esc(s.step)}</small>${esc(s.title)}</span>
          <span class="num">${lek(s.min_price)}</span><span class="num dear">${lek(s.max_price)}</span></a>`).join("")}
      <div class="receipt-total"><span>Gjithsej</span><span class="num">${lek(r.cheapest)}</span><span class="num dear">${lek(r.dearest)}</span></div>
      <div class="receipt-diff"><span>Paguan më shumë për të njëjtat produkte</span><b class="num">${lek(r.difference)}</b></div>
      <p class="receipt-note">Po ta rinovosh rutinën 4 herë në vit, diferenca bëhet <b class="num">${lek(r.difference * 4)}</b> në vit.</p>
    </div>` : "";
  return `<section class="section impact"><div class="wrap impact-in">
    <div>
      <h2>sa kushton të mos krahasosh</h2>
      <p class="impact-lead">Për të njëjtin produkt, dyqani më i shtrenjtë kërkon mesatarisht
        <b>${im.median_more_pct}% më shumë</b> se më i liri. Te ${im.share_over_20}% e produkteve diferenca kalon 20%.</p>
      <p class="lead">E llogaritëm mbi ${im.products.toLocaleString("en").replace(/,/g, " ")} produkte që gjenden në stok në të paktën tre dyqane online në Shqipëri.
        Diferenca tipike për një produkt është ${lek(im.median_diff)}, çdo herë që e blen.</p>
    </div>
    ${receipt}
  </div></section>`;
}

async function pageCategories() {
  const d = homeCache || (homeCache = await api("/api/home"));
  main.innerHTML = `<div class="wrap"><div class="page-head"><h1>kategoritë</h1>
    <p>${plural(d.stats.compared, "produkt", "produkte")} gjenden në më shumë se një dyqan.</p></div>
    <div class="section" style="padding-top:20px"><div class="cats">${d.categories.filter((c) => c.count).map((c) =>
      `<a href="/kategori/${c.id}" data-link>${esc(c.label)}<span>${c.count.toLocaleString("en").replace(/,/g, " ")}</span></a>`).join("")}
      <a href="/kategori/tjeter" data-link>Të tjera<span></span></a></div></div></div>`;
}

async function pageCategory(cat, params) {
  const q = new URLSearchParams(params);
  const d = await api(`/api/category/${encodeURIComponent(cat)}?${q}`);
  document.title = `${d.label}: krahaso çmimet | shporta`;
  const opt = (v, label, cur) => `<option value="${esc(v)}" ${cur === v ? "selected" : ""}>${esc(label)}</option>`;
  main.innerHTML = `<div class="wrap">
    <div class="page-head"><div class="crumbs"><a href="/kategorite" data-link>Kategoritë</a></div>
      <h1>${esc(d.label)}</h1><p>${plural(d.total, "produkt", "produkte")}</p></div>
    <form class="filters" id="filters">
      <label>Rendit <select name="sort">
        ${opt("compared", "Në më shumë dyqane", q.get("sort") || "compared")}${opt("gap", "Diferenca më e madhe", q.get("sort"))}
        ${opt("cheap", "Më të lirat", q.get("sort"))}${opt("dear", "Më të shtrenjtat", q.get("sort"))}</select></label>
      <label>Dyqani <select name="shop"><option value="">Të gjitha</option>${d.shops.map((s) => opt(s, shopName(s), q.get("shop"))).join("")}</select></label>
      <label><input type="checkbox" name="compared" value="1" ${q.get("compared") === "1" ? "checked" : ""}> Vetëm në 2+ dyqane</label>
    </form>
    ${d.items.length ? `<div class="grid">${d.items.map(tile).join("")}</div>`
      : `<div class="empty"><b>Asnjë produkt me këto filtra.</b>Hiq një filtër ose zgjidh një dyqan tjetër.</div>`}
    ${pager(d, location.pathname + location.search)}
  </div>`;
  document.getElementById("filters").onchange = (e) => {
    const f = new FormData(e.currentTarget);
    const p = new URLSearchParams();
    for (const [k, v] of f) if (v) p.set(k, v);
    go(`/kategori/${cat}?${p}`);
  };
}

async function pageItem(id) {
  const it = await api(`/api/item/${encodeURIComponent(id)}`);
  document.title = `${it.title}: çmimet në ${it.offers.length} dyqane | shporta`;
  const live = it.offers.filter((o) => o.in_stock && o.currency === it.currency);
  const prices = live.map((o) => o.price);
  const lo = prices.length ? Math.min(...prices) : it.min_price;
  const hi = prices.length ? Math.max(...prices) : it.max_price;
  const multiShop = new Set(it.offers.map((o) => o.shop)).size > 1;
  const cheap = live.find((o) => o.price === lo), dear = live.find((o) => o.price === hi);
  const diffCell = (o) => !multiShop || o.currency !== it.currency ? "Në stok"
    : o.price === lo ? `<span class="diff best">Më i liri</span>` : `<span class="diff">+${lek(o.price - lo, o.currency)}</span>`;
  const rows = it.offers.map((o) => `<tr class="${o.in_stock ? "" : "out"}">
      <td><b>${esc(shopName(o.shop))}</b><span class="t">${esc(o.title)}</span></td>
      <td class="p"><span class="num">${lek(o.price, o.currency)}</span>${o.regular_price > o.price ? `<br><s class="t">${lek(o.regular_price, o.currency)}</s>` : ""}</td>
      <td>${o.in_stock ? diffCell(o) : "S'ka gjendje"}</td>
      <td>${shopLink(o, it.id, "produkt", `btn ${o.in_stock && o.price === lo ? "" : "btn-ghost"}`)}</td>
    </tr>`).join("");
  const story = multiShop && cheap && dear && hi > lo
    ? `<p class="story">Te <b>${esc(shopName(dear.shop))}</b> paguan <b class="num">${lek(hi - lo, it.currency)}</b> më shumë se te
        <b>${esc(shopName(cheap.shop))}</b> për të njëjtin produkt. Po ta blesh 4 herë në vit, kjo bën <b class="num">${lek((hi - lo) * 4, it.currency)}</b>.</p>` : "";
  main.innerHTML = `<div class="wrap">
    <div class="page-head" style="padding-bottom:18px"><div class="crumbs"><a href="/kategori/${esc(it.cat)}" data-link>${esc(it.category_label)}</a></div></div>
    <div class="product">
      <div class="pic">${img(it.image, it.title)}</div>
      <div>
        <h1>${esc(it.title)}</h1>
        <div class="summary">
          <div class="low">Më i liri<b>${lek(lo, it.currency)}</b></div>
          ${multiShop && hi > lo ? `<div>Më i shtrenjti<b>${lek(hi, it.currency)}</b></div><div>Kursen deri<b>${lek(hi - lo, it.currency)}</b></div>` : ""}
          <div>${multiShop ? "Dyqane" : "Variante"}<b>${it.offers.length}</b></div>
        </div>
        ${story}
        ${multiShop ? ruler(it, { showHead: false, animate: true, from: "produkt" }) : ""}
        <table class="offers"><thead><tr><th>Dyqani</th><th style="text-align:right">Çmimi</th><th>${multiShop ? "Sa më shumë" : "Gjendja"}</th><th></th></tr></thead>
          <tbody>${rows}</tbody></table>
        ${multiShop && it.size_note ? `<p class="size-warn">${it.size_note === 2
          ? "Asnjë nga këto dyqane nuk e tregon madhësinë në emrin e produktit. I krahasuam sepse emri është i njëjtë dhe çmimet janë afër njëri-tjetrit. Kontrollo madhësinë te dyqani."
          : "Disa dyqane nuk e tregojnë madhësinë. I përfshimë vetëm kur çmimi përputhet me madhësinë që tregojnë dyqanet e tjera. Kontrollo madhësinë te dyqani."}</p>` : ""}
        <p class="note">${multiShop
          ? "Krahasojmë vetëm të njëjtin produkt: i njëjti emër, e njëjta markë dhe e njëjta madhësi. Emri i saktë te çdo dyqan është poshtë çmimit, që ta kontrollosh vetë."
          : "Këtë produkt e gjetëm vetëm në këtë dyqan. Më poshtë ke produkte të ngjashme nga dyqane të tjera."}</p>
      </div>
    </div>
    ${it.dupes && it.dupes.length ? `<section class="section"><h2>dupe më të lira</h2>
      <p class="lead">Jo i njëjti produkt. ${esc(DUPE_WHY[it.dupes[0].kind] || "")} Kontrollo përbërësit dhe madhësinë te dyqani.</p>
      <div class="dps">${it.dupes.map((r) => dupePair(r, { showOrig: false })).join("")}</div></section>` : ""}
    ${it.dupe_of && it.dupe_of.length ? `<section class="section"><h2>alternativë më e lirë e</h2>
      <p class="lead">Ky produkt kushton më pak se origjinali. ${esc(DUPE_WHY[it.dupe_of[0].kind] || "")}</p>
      <div class="dps">${it.dupe_of.map((r) => dupePair(r)).join("")}</div></section>` : ""}
    ${it.similar.length ? `<section class="section"><h2>produkte të ngjashme</h2><p class="lead">Nga dyqane të tjera, më të lirat së pari.</p>
      <div class="grid">${it.similar.map(tile).join("")}</div></section>` : ""}
  </div>`;
}

async function pageSearch(params) {
  const q = new URLSearchParams(params);
  const term = q.get("q") || "";
  document.querySelectorAll('input[name="q"]').forEach((i) => (i.value = term));
  if (!term.trim()) {
    main.innerHTML = `<div class="wrap"><div class="page-head"><h1>kërko</h1></div>${searchForm("q-page")}</div>`;
    return;
  }
  const d = await api(`/api/search?${q}`);
  document.title = `${term}: kërkimi | shporta`;
  main.innerHTML = `<div class="wrap">
    <div class="page-head"><h1>${esc(term)}</h1><p>${plural(d.total, "produkt", "produkte")}. Ato në më shumë dyqane dalin të parat.</p></div>
    <div style="height:22px"></div>
    ${d.items.length ? `<div class="grid">${d.items.map(tile).join("")}</div>`
      : `<div class="empty"><b>Nuk gjetëm "${esc(term)}".</b>Provo një fjalë më të shkurtër, emrin e markës, ose shkruaje pa ë dhe ç.</div>`}
    ${pager(d, location.pathname + location.search)}
  </div>`;
}

const SHOP_GROUPS = { beauty: "Kozmetikë dhe farmaci", perfume: "Parfume", clothing: "Veshje", shoes: "Këpucë",
  accessories: "Aksesorë dhe syze", jewelry: "Bizhuteri dhe ora", sport: "Sport", multi: "Dyqane me shumë kategori" };
async function pageShops() {
  const list = await api("/api/shops");
  document.title = "Dyqanet | shporta";
  const groups = {};
  for (const s of list) (groups[s.category] ||= []).push(s);
  main.innerHTML = `<div class="wrap">
    <div class="page-head"><h1>dyqanet</h1><p>${list.length} dyqane online. Çmimet merren nga faqet e tyre publike.</p></div>
    <div style="height:26px"></div>
    <div class="shop-groups">${Object.entries(SHOP_GROUPS).filter(([k]) => groups[k]).map(([k, label]) =>
      `<div class="shop-group"><h2>${label}</h2>${groups[k].map((s) =>
        `<a href="https://${esc(s.domain)}" target="_blank" rel="noopener">${esc(shopName(s.domain))}<span>${s.products.toLocaleString("en").replace(/,/g, " ")}</span></a>`).join("")}</div>`).join("")}</div>
  </div>`;
}

async function pageDupes(params) {
  const q = new URLSearchParams(params);
  const d = await api(`/api/dupes?${q}`);
  document.title = "Dupe të produkteve të shtrenjta | shporta";
  const tab = (k, label) => `<a class="tab" href="/dupe${k ? `?kind=${k}` : ""}" data-link ${d.kind === k || (!d.kind && !k) ? 'aria-current="page"' : ""}>${label}</a>`;
  main.innerHTML = `<div class="wrap">
    <div class="page-head"><h1>dupe</h1>
      <p>${plural(d.total, "produkt i shtrenjtë", "produkte të shtrenjta")} me një alternativë të paktën 30% më të lirë. Jo i njëjti produkt: për secilin themi pse e quajmë dupe.</p></div>
    <nav class="tabs" aria-label="Lloji">${tab(null, "Të gjitha")}${tab("inspired", "Parfume")}${tab("active", "Kujdesi i lëkurës")}${tab("known", "Grim")}</nav>
    ${d.items.length ? `<div class="dps">${d.items.map((r) => dupePair(r) + (r.count > 1
      ? `<a class="dp-more" href="/produkt/${esc(r.orig_id)}" data-link>Edhe ${r.count - 1} dupe të tjera për këtë produkt</a>` : "")).join("")}</div>`
      : `<div class="empty"><b>Asnjë dupe këtu ende.</b>Provo një kategori tjetër.</div>`}
    ${pager(d, location.pathname + location.search)}
  </div>`;
}

function pageExtension() {
  document.title = "Shtesa për shfletuesin | shporta";
  main.innerHTML = `<div class="wrap">
    <div class="page-head"><h1>shtesa për shfletuesin</h1>
      <p>Kur hap një produkt në një dyqan online, shtesa të tregon nëse çmimi është i mirë dhe ku e gjen më lirë.</p></div>
    <section class="section" style="border:0">
      <div class="band">
        <div><h2>si funksionon</h2>
          <p>Shtesa lexon vetëm emrin dhe çmimin e produktit që ke hapur, dhe e krahason me dyqanet e tjera në shporta. Nuk lexon fjalëkalime, nuk ndjek se ku shfleton dhe nuk blen gjë për ty.</p></div>
        <ol><li>Hap një produkt në çdo dyqan online.</li><li>Në cep të faqes del çmimi: i mirë, normal apo i lartë.</li><li>Kliko një dyqan më të lirë për ta hapur.</li></ol>
      </div>
    </section>
    <section class="section"><h2>instalimi (version testimi)</h2>
      <p class="lead">Shtesa nuk është ende në Chrome Web Store. Për ta provuar në Chrome ose Edge:</p>
      <ol>
        <li>Shkarko dosjen <code>extension</code> nga <a href="https://github.com/shporta-app/new-shporta" target="_blank" rel="noopener">github.com/shporta-app/new-shporta</a>.</li>
        <li>Hap <code>chrome://extensions</code> dhe aktivizo <b>Developer mode</b>.</li>
        <li>Kliko <b>Load unpacked</b> dhe zgjidh dosjen <code>extension</code>.</li>
      </ol>
    </section>
  </div>`;
}

function pagePrivacy() {
  document.title = "Cookies dhe privatësia | shporta";
  const c = getCookie("sp_consent");
  main.innerHTML = `<div class="wrap prose">
    <div class="page-head"><h1>cookies dhe privatësia</h1><p>Çfarë mbledhim kur përdor shportën, dhe pse.</p></div>
    <h2>Cookies të domosdoshme</h2>
    <p><code>sp_consent</code> ruan zgjedhjen tënde për cookies, për një vit. Pa të, do të të pyesnim në çdo vizitë.</p>
    <h2>Cookies për statistika, vetëm me lejen tënde</h2>
    <p><code>sp_id</code> është një numër i rastësishëm, pa emër apo email. Na tregon sa vizitorë të ndryshëm klikojnë drejt dyqaneve, që të dimë sa vlen shporta për to.</p>
    <h2>Kur kalon te një dyqan</h2>
    <p>Lidhjet "Hape në dyqan" kalojnë nga <code>shporta.app/go/…</code>. Ruajmë cilin produkt dhe cilin dyqan zgjodhe dhe kur. Lidhjes i shtojmë
      <code>utm_source=shporta</code>, që dyqani ta dijë se vizita erdhi nga shporta. Kjo mund të na lejojë në të ardhmen të marrim një komision nga dyqani
      për blerjet që sjellim. Çmimi për ty nuk ndryshon kurrë, dhe renditja e dyqaneve bëhet gjithmonë sipas çmimit.</p>
    <p>Nuk shesim të dhëna, nuk kemi llogari përdoruesish dhe nuk shohim çfarë blen te dyqani.</p>
    <h2>Shtesa për shfletuesin</h2>
    <p>Kur hap një faqe produkti, shtesa lexon emrin, çmimin dhe monedhën e produktit, si edhe adresën e faqes, dhe i dërgon te
      <code>shporta.app</code> për të gjetur çmime dhe dupe në dyqane të tjera. Në faqet që nuk janë produkte nuk dërgon asgjë.
      Nuk lexon fjalëkalime, formularë, të dhëna pagese apo historinë e shfletimit, nuk ruan asgjë në kompjuterin tënd dhe nuk
      ruan te ne të dhënat e faqes që ke hapur. Klikimet nga paneli drejt dyqaneve numërohen si te faqja, me <code>/go/</code>.</p>
    <h2>Zgjedhja jote</h2>
    <p>Tani: <b>${c === "all" ? "të gjitha cookies" : c === "essential" ? "vetëm të domosdoshmet" : "pa zgjedhje"}</b>.</p>
    <p><button class="btn" type="button" data-consent="all">Prano të gjitha</button>
       <button class="btn btn-ghost" type="button" data-consent="essential">Vetëm të domosdoshmet</button></p>
  </div>`;
}

function getCookie(name) {
  return document.cookie.split("; ").find((c) => c.startsWith(name + "="))?.split("=")[1];
}
function setConsent(choice) {
  const year = 60 * 60 * 24 * 365;
  const secure = location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `sp_consent=${choice}; Max-Age=${year}; Path=/; SameSite=Lax${secure}`;
  if (choice === "all" && !getCookie("sp_id"))
    document.cookie = `sp_id=${crypto.randomUUID()}; Max-Age=${year}; Path=/; SameSite=Lax${secure}`;
  if (choice !== "all") document.cookie = "sp_id=; Max-Age=0; Path=/";
  document.getElementById("consent")?.remove();
  if (location.pathname === "/privatesia") pagePrivacy();
}
function consentBanner() {
  if (getCookie("sp_consent")) return;
  document.body.insertAdjacentHTML("beforeend", `<div class="consent" id="consent" role="dialog" aria-label="Cookies">
    <p>Përdorim cookies të domosdoshme që faqja të funksionojë. Me lejen tënde, përdorim edhe një identifikues anonim për të numëruar
      klikimet drejt dyqaneve. <a href="/privatesia" data-link>Më shumë</a></p>
    <div><button class="btn" type="button" data-consent="all">Prano të gjitha</button>
      <button class="btn btn-ghost" type="button" data-consent="essential">Vetëm të domosdoshmet</button></div>
  </div>`);
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-consent]");
  if (b) setConsent(b.dataset.consent);
});

/* ---------- router ---------- */

function setFoot(updated) {
  if (!updated) return;
  const d = new Date(updated);
  document.getElementById("foot-updated").textContent =
    `Çmimet u përditësuan më ${d.toLocaleDateString("sq-AL", { day: "numeric", month: "long", year: "numeric" })}.`;
}

async function route() {
  const { pathname, search } = location;
  const params = search.slice(1);
  document.querySelectorAll(".top-nav a").forEach((a) => {
    if (pathname.startsWith(a.getAttribute("href"))) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  main.innerHTML = `<div class="wrap loading">Duke ngarkuar…</div>`;
  document.title = "shporta: krahaso çmimet e modës dhe kozmetikës në Shqipëri";
  try {
    let m;
    if (pathname === "/") await pageHome();
    else if (pathname === "/kategorite") await pageCategories();
    else if ((m = pathname.match(/^\/kategori\/([\w-]+)$/))) await pageCategory(m[1], params);
    else if ((m = pathname.match(/^\/produkt\/([\w-]+)$/))) await pageItem(m[1]);
    else if (pathname === "/kerko") await pageSearch(params);
    else if (pathname === "/dyqanet") await pageShops();
    else if (pathname === "/shtesa") pageExtension();
    else if (pathname === "/privatesia") pagePrivacy();
    else if (pathname === "/dupe") await pageDupes(params);
    else throw Object.assign(new Error("Kjo faqe nuk ekziston."), { status: 404 });
  } catch (e) {
    main.innerHTML = `<div class="wrap empty"><b>${esc(e.status === 404 ? e.message : "Faqja nuk u ngarkua.")}</b>
      ${e.status === 404 ? `<a href="/" data-link>Kthehu në faqen kryesore</a>` : "Serveri mund të jetë duke u zgjuar. Rifresko faqen pas pak sekondash."}</div>`;
  }
  if (!homeCache) api("/api/home").then((d) => { homeCache = d; setFoot(d.stats.updated); }).catch(() => {});
}

function go(url) {
  history.pushState(null, "", url);
  window.scrollTo(0, 0);
  route().then(() => main.focus({ preventScroll: true }));
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-link]");
  if (!a || e.metaKey || e.ctrlKey || e.shiftKey || a.target === "_blank") return;
  e.preventDefault();
  go(a.getAttribute("href"));
});
document.addEventListener("submit", (e) => {
  if (!e.target.matches("[data-search]")) return;
  e.preventDefault();
  const q = new FormData(e.target).get("q").trim();
  if (q) go(`/kerko?q=${encodeURIComponent(q)}`);
});
window.addEventListener("popstate", route);
route();
consentBanner();
