// shporta: a small single-page app over /api. Pages: home, category, product, search, shops, extension.
const main = document.getElementById("main");

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const lek = (n, cur = "ALL") =>
  cur === "EUR" ? "€" + Number(n).toFixed(2) : cur === "USD" ? "$" + Number(n).toFixed(2)
  : cur && cur !== "ALL" ? Number(n).toFixed(2) + " " + cur  // never show a foreign price as lek
  : Math.round(n).toLocaleString("en").replace(/,/g, " ") + " L";
// Albanian dates written out by hand: not every browser has Albanian locale data ("Oct 22" instead of "22 tetor")
const MUAJ = ["janar", "shkurt", "mars", "prill", "maj", "qershor", "korrik", "gusht", "shtator", "tetor", "nëntor", "dhjetor"];
const dateSq = (d, year = true) => { const x = new Date(d); return `${x.getDate()} ${MUAJ[x.getMonth()]}${year ? " " + x.getFullYear() : ""}`; };
const day = (d) => dateSq(d + "T12:00:00", false);
const daysAgo = (d) => Math.round((Date.now() - new Date(d + "T12:00:00")) / 864e5);

// What the price history says about one shop's price (build_seed.price_history). Only facts we saw ourselves:
// a "was" price is called false only after 30 days of daily prices in which the shop never charged it.
function priceNote(o) {
  const out = [];
  if (o.prev_price && o.changed && o.prev_price !== o.price) {
    out.push(o.prev_price > o.price
      ? `<span class="hist down">ra nga ${lek(o.prev_price, o.currency)} më ${day(o.changed)}</span>`
      : `<span class="hist up">u rrit nga ${lek(o.prev_price, o.currency)} më ${day(o.changed)}</span>`);
  }
  if (o.regular_price > o.price && o.since) {
    if (daysAgo(o.since) >= 30 && o.reg_seen === 0) {
      out.push(`<span class="hist warn">zbritje e dyshimtë: në 30 ditët e fundit nuk e pamë kurrë me ${lek(o.regular_price, o.currency)}</span>`);
    } else if (o.low30 && o.low30 < o.price) {
      out.push(`<span class="hist">më i ulët në 30 ditë: ${lek(o.low30, o.currency)}</span>`);
    }
  }
  if (o.seen && daysAgo(o.seen) >= 1) out.push(`<span class="hist">çmimi i parë më ${day(o.seen)}</span>`);
  return out.length ? `<br>${out.join("<br>")}` : "";
}
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

// Products a visitor follows: kept only in this browser (no account, nothing sent to us but the product ids when the
// list is opened), with the cheapest price on the day they saved it, so the list can say what changed since.
const WATCH_KEY = "shporta-lista";
const watchList = () => { try { return JSON.parse(localStorage.getItem(WATCH_KEY)) || []; } catch { return []; } };
const watchSave = (l) => { try { localStorage.setItem(WATCH_KEY, JSON.stringify(l.slice(0, 100))); } catch {} watchBadge(); };
const watching = (id) => watchList().some((w) => w.id === id);
function watchToggle(it) {
  const l = watchList();
  if (l.some((w) => w.id === it.id)) return watchSave(l.filter((w) => w.id !== it.id)), false;
  watchSave([{ id: it.id, title: it.title, image: it.image, size: it.size, currency: it.currency,
               price: it.min_price, saved: new Date().toISOString().slice(0, 10) }, ...l]);
  return true;
}
// the newest prices for the list, at most once per page view; marks which ones are cheaper than when saved
let watchNow;
async function watchFetch() {
  const l = watchList();
  if (!l.length) return [];
  if (!watchNow) watchNow = api(`/api/items?ids=${l.map((w) => encodeURIComponent(w.id)).join(",")}`).then((d) => d.items).catch(() => null);
  const now = await watchNow;
  const by = new Map((now || []).map((i) => [i.id, i]));
  return l.map((w) => ({ ...w, now: now ? by.get(w.id) || null : undefined }));
}
const dropped = (w) => w.now && w.now.currency === w.currency && w.now.in_stock_shops > 0 && w.now.min_price < w.price;
function watchBadge() {
  const a = document.getElementById("nav-lista");
  if (!a) return;
  const n = watchList().length;
  a.hidden = !n;
  a.querySelector("span").textContent = n ? ` (${n})` : "";
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
  const range = it.in_stock_shops > 1 && it.save_pct > 0 && it.max_price > it.min_price  // sold out everywhere saves nothing
    ? `<small>kursen deri ${lek(it.max_price - it.min_price, it.currency)}</small>` : "";
  return `<a class="tile" href="/produkt/${esc(it.id)}" data-link>
    <span class="pic">${img(it.image, it.title)}</span>
    ${it.shops > 1 ? `<span class="chip">${plural(it.shops, "dyqan", "dyqane")}</span>` : ""}
    <span class="name">${esc(it.title)}</span>${it.size ? `<span class="size">${esc(it.size)}</span>` : ""}
    <span class="meta"><span class="num">${it.shops > 1 ? "nga " : ""}${lek(it.min_price, it.currency)}</span>${range}</span>
  </a>`;
}

function deal(it) {
  return `<a class="deal" href="/produkt/${esc(it.id)}" data-link>
    ${img(it.image, it.title)}
    <span><span class="name">${esc(it.title)}${it.size ? ` <small>${esc(it.size)}</small>` : ""}</span>
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
function receiptBox(r) {
  return r ? `<div class="receipt" aria-label="Rutina bazë e kujdesit për lëkurën">
      <div class="receipt-head"><span>Rutina bazë e lëkurës</span><span>Më lirë</span><span>Më shtrenjtë</span></div>
      ${r.steps.map((s) => `<a class="receipt-row" href="/produkt/${esc(s.id)}" data-link>
          <span><small>${esc(s.step)}</small>${esc(s.title)}</span>
          <span class="num">${lek(s.min_price)}</span><span class="num dear">${lek(s.max_price)}</span></a>`).join("")}
      <div class="receipt-total"><span>Gjithsej</span><span class="num">${lek(r.cheapest)}</span><span class="num dear">${lek(r.dearest)}</span></div>
      <div class="receipt-diff"><span>Paguan më shumë për të njëjtat produkte</span><b class="num">${lek(r.difference)}</b></div>
      <p class="receipt-note">Po ta rinovosh rutinën 4 herë në vit, diferenca bëhet <b class="num">${lek(r.difference * 4)}</b> në vit.</p>
    </div>` : "";
}
function impactSection(d) {
  const im = d.impact;
  if (!im) return "";
  const receipt = receiptBox(d.routine);
  return `<section class="section impact"><div class="wrap impact-in">
    <div>
      <h2>sa kushton të mos krahasosh</h2>
      <p class="impact-lead">Për të njëjtin produkt, dyqani më i shtrenjtë kërkon mesatarisht
        <b>${im.median_more_pct}% më shumë</b> se më i liri. Te ${im.share_over_20}% e produkteve diferenca kalon 20%.</p>
      <p class="lead">E llogaritëm mbi ${im.products.toLocaleString("en").replace(/,/g, " ")} produkte që gjenden në stok në të paktën tre dyqane online në Shqipëri.
        Diferenca tipike për një produkt është ${lek(im.median_diff)}, çdo herë që e blen.</p>
      <p><a class="btn btn-ghost" href="/raport" data-link>Raporti i plotë i çmimeve</a></p>
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
      <td class="p"><span class="num">${lek(o.price, o.currency)}</span>${o.regular_price > o.price ? `<br><s class="t">${lek(o.regular_price, o.currency)}</s>` : ""}${priceNote(o)}</td>
      <td>${o.in_stock ? diffCell(o) : "S'ka gjendje"}</td>
      <td>${shopLink(o, it.id, "produkt", `btn ${o.in_stock && o.price === lo ? "" : "btn-ghost"}`)}</td>
    </tr>`).join("");
  // shops that sell it without writing the size: shown, but never compared (we can't confirm it's the same size)
  const unconfirmed = (it.unconfirmed || []).map((o) => `<tr class="${o.in_stock ? "" : "out"}">
      <td><b>${esc(shopName(o.shop))}</b><span class="t">${esc(o.title)}</span></td>
      <td class="p"><span class="num">${lek(o.price, o.currency)}</span></td>
      <td>${o.in_stock ? "Madhësia s'tregohet" : "S'ka gjendje"}</td>
      <td>${shopLink(o, it.id, "produkt", "btn btn-ghost")}</td>
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
        ${it.used ? `<p class="size-warn">Artikull i përdorur (second-hand / vintage). Nuk e krahasojmë me produkte të reja.</p>` : ""}
        ${it.size ? `<p class="size-line">Krahasojmë vetëm madhësinë <b>${esc(it.size)}</b>. Çdo dyqan më poshtë e shkruan këtë madhësi te produkti.</p>` : ""}
        <div class="summary">
          ${live.length ? `<div class="low">Më i liri<b>${lek(lo, it.currency)}</b></div>`
            : `<div>S'ka gjendje askund<b>${lek(lo, it.currency)}</b></div>`}
          ${live.length > 1 && hi > lo ? `<div>Më i shtrenjti<b>${lek(hi, it.currency)}</b></div><div>Kursen deri<b>${lek(hi - lo, it.currency)}</b></div>` : ""}
          <div>${multiShop ? "Dyqane" : "Variante"}<b>${it.offers.length}</b></div>
        </div>
        ${story}
        <p class="watch"><button type="button" class="btn btn-ghost" id="watch" aria-pressed="${watching(it.id)}"></button>
          <small>Ruhet vetëm në këtë shfletues. Kur rihap shportën, të tregojmë nëse çmimi ra.</small></p>
        ${it.alerts ? `<form class="alert-form" id="alert-form">
          <label for="alert-email">Më njofto me email kur bie çmimi</label>
          <span><input id="alert-email" name="email" type="email" autocomplete="email" required placeholder="emaili yt">
          <button class="btn" type="submit">Më njofto</button></span>
          <small id="alert-msg" role="status">Të shkruajmë vetëm kur bie çmimi. Çdo email ka një link për t’i ndaluar.</small>
        </form>` : ""}
        ${multiShop ? ruler(it, { showHead: false, animate: true, from: "produkt" }) : ""}
        <table class="offers"><thead><tr><th>Dyqani</th><th style="text-align:right">Çmimi</th><th>${multiShop ? "Sa më shumë" : "Gjendja"}</th><th></th></tr></thead>
          <tbody>${rows}</tbody></table>
        ${multiShop && it.size_note === 2 ? `<p class="size-warn">Asnjë nga këto dyqane nuk e shkruan madhësinë te produkti.
          I krahasuam sepse emri është i njëjtë dhe çmimet janë brenda 25% të njëri-tjetrit. Kontrollo madhësinë te dyqani para se të blesh.</p>` : ""}
        ${unconfirmed ? `<h2 class="sub">edhe këto dyqane e kanë, pa e shkruar madhësinë</h2>
          <p class="note">Nuk i krahasojmë dhe nuk i numërojmë te më i liri, sepse nuk e dimë nëse është ${it.size ? esc(it.size) : "e njëjta madhësi"}. Kontrollo madhësinë te dyqani.</p>
          <table class="offers unconfirmed"><tbody>${unconfirmed}</tbody></table>` : ""}
        <p class="note">${multiShop
          ? "Krahasojmë vetëm të njëjtin produkt: i njëjti emër, e njëjta markë dhe e njëjta madhësi. Emri i saktë te çdo dyqan është poshtë çmimit, që ta kontrollosh vetë."
          : "Këtë produkt e gjetëm vetëm në këtë dyqan. Më poshtë ke produkte të ngjashme nga dyqane të tjera."}
          ${it.tracked_since ? ` Çmimet i kontrollojmë çdo ditë që nga ${dateSq(it.tracked_since + "T12:00:00")}.` : ""}</p>
      </div>
    </div>
    ${it.dupes && it.dupes.length ? `<section class="section apart"><h2>dupe: një produkt tjetër, më i lirë</h2>
      <p class="lead">Këto nuk janë i njëjti produkt dhe nuk hyjnë te krahasimi i çmimeve më sipër. ${esc(DUPE_WHY[it.dupes[0].kind] || "")} Kontrollo përbërësit dhe madhësinë te dyqani.</p>
      <div class="dps">${it.dupes.map((r) => dupePair(r, { showOrig: false })).join("")}</div></section>` : ""}
    ${it.dupe_of && it.dupe_of.length ? `<section class="section apart"><h2>alternativë më e lirë e</h2>
      <p class="lead">Ky produkt kushton më pak se origjinali. ${esc(DUPE_WHY[it.dupe_of[0].kind] || "")}</p>
      <div class="dps">${it.dupe_of.map((r) => dupePair(r)).join("")}</div></section>` : ""}
    ${(it.other_sizes || []).length ? `<section class="section"><h2>i njëjti produkt, madhësi tjetër</h2><p class="lead">I njëjti emër, por madhësi tjetër ose dyqani nuk e shkruan madhësinë. Nuk krahasohen me çmimet më sipër.</p>
      <div class="grid">${it.other_sizes.map(tile).join("")}</div></section>` : ""}
    ${it.similar.length ? `<section class="section apart"><h2>produkte të ngjashme</h2><p class="lead">Emër i ngjashëm: nuk e konfirmojmë që është i njëjti produkt. Nga dyqane të tjera, më të lirat së pari.</p>
      <div class="grid">${it.similar.map(tile).join("")}</div></section>` : ""}
  </div>`;
  const btn = document.getElementById("watch");
  const label = () => { btn.textContent = watching(it.id) ? "E ndjek ✓ (hiqe)" : "Ndiq çmimin"; btn.setAttribute("aria-pressed", watching(it.id)); };
  label();
  btn.onclick = () => { watchToggle(it); watchNow = null; label(); };
  const form = document.getElementById("alert-form");
  if (form) form.onsubmit = async (e) => {
    e.preventDefault();
    const msg = document.getElementById("alert-msg"), b = form.querySelector("button");
    b.disabled = true;
    try {
      const r = await fetch("/api/alert", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: form.email.value, item: it.id }) });
      const d = await r.json().catch(() => ({}));
      msg.textContent = d.message || d.error || "Diçka shkoi keq. Provo përsëri.";
      msg.className = r.ok ? "ok" : "err";
      if (r.ok && !watching(it.id)) { watchToggle(it); label(); }
    } catch { msg.textContent = "Nuk u lidhëm dot. Provo përsëri."; msg.className = "err"; }
    b.disabled = false;
  };
}

async function pageList() {
  document.title = "Produktet që ndjek | shporta";
  const l = await watchFetch();
  const row = (w) => {
    const n = w.now;
    const change = n === undefined ? `<span class="hist">Çmimi i sotëm nuk u ngarkua.</span>`
      : !n ? `<span class="hist">Nuk e gjejmë më në asnjë dyqan.</span>`
      : !n.in_stock_shops ? `<span class="hist">S'ka gjendje askund tani.</span>`
      : n.currency !== w.currency || n.min_price === w.price ? `<span class="hist">Njësoj si më ${day(w.saved)}.</span>`
      : n.min_price < w.price ? `<span class="hist down">Ra ${lek(w.price - n.min_price, w.currency)} që nga ${day(w.saved)} (ishte ${lek(w.price, w.currency)}).</span>`
      : `<span class="hist up">U rrit ${lek(n.min_price - w.price, w.currency)} që nga ${day(w.saved)} (ishte ${lek(w.price, w.currency)}).</span>`;
    return `<li class="${dropped(w) ? "drop" : ""}">
      <a href="/produkt/${esc(w.id)}" data-link>${img(w.image, w.title)}
        <span><span class="name">${esc(w.title)}${w.size ? ` <small>${esc(w.size)}</small>` : ""}</span>
        <span class="num">${n ? `${n.shops > 1 ? "nga " : ""}${lek(n.min_price, n.currency)}` : ""}</span>${change}</span></a>
      <button type="button" class="btn btn-ghost" data-unwatch="${esc(w.id)}">Hiqe</button></li>`;
  };
  const drops = l.filter(dropped);
  main.innerHTML = `<div class="wrap">
    <div class="page-head"><h1>produktet që ndjek</h1>
      <p>${l.length ? `${plural(l.length, "produkt", "produkte")}${drops.length ? `, ${drops.length} me çmim më të ulët se kur e ruajte` : ""}.` : ""}
        Lista ruhet vetëm në këtë shfletues: nuk ka llogari dhe ne nuk e shohim. Krahasojmë çmimin më të lirë në stok sot me atë të ditës kur e ruajte.</p></div>
    ${l.length ? `<ul class="watchlist">${[...drops, ...l.filter((w) => !dropped(w))].map(row).join("")}</ul>`
      : `<div class="empty"><b>Nuk ndjek asnjë produkt ende.</b>Hap një produkt dhe shtyp "Ndiq çmimin". Kur rihap shportën, këtu shikon nëse çmimi ra.</div>`}
  </div>`;
  main.querySelectorAll("[data-unwatch]").forEach((b) => (b.onclick = () => {
    watchSave(watchList().filter((w) => w.id !== b.dataset.unwatch));
    watchNow = null;
    pageList();
  }));
}

// The price report: today's data, the same product across shops (server.report explains the rules)
const monthSq = (m) => `${MUAJ[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}`;
async function pageReport(month) {
  const r = await api(`/api/report${month ? `?month=${month}` : ""}`);
  document.title = `Raporti i çmimeve${month ? `, ${monthSq(month)}` : " në Shqipëri"} | shporta`;
  const prev = r.previous;
  const trend = prev ? `<p class="trend">Në ${monthSq(prev.month)} ishte <b>${prev.median_more_pct}%</b> (${lek(prev.median_diff)} për produkt)${
    prev.median_more_pct === r.median_more_pct ? ": njësoj." : prev.median_more_pct > r.median_more_pct ? ": diferencat janë ngushtuar." : ": diferencat janë rritur."}</p>` : "";
  const others = (r.months || []).filter((m) => m !== month);
  const n = (x) => x.toLocaleString("en").replace(/,/g, " ");
  const maxPct = Math.max(...r.categories.map((c) => c.median_more_pct), 1);
  const cats = r.categories.map((c) => `<li>
      <a href="/kategori/${esc(c.id)}" data-link>${esc(c.label)}</a>
      <span class="track"><span class="bar" style="--w:${Math.max(8, (c.median_more_pct / maxPct) * 100).toFixed(1)}%"></span>
        <b class="num">${c.median_more_pct}%</b></span>
      <small>${lek(c.median_diff)} për produkt, ${plural(c.products, "produkt", "produkte")}</small></li>`).join("");
  const shops = r.shops_table.map((s) => `<tr><td><b>${esc(shopName(s.shop))}</b></td><td class="num">${s.cheapest_pct}%</td>
      <td class="num">${s.median_above_pct ? `+${s.median_above_pct}%` : "0%"}</td><td class="num">${n(s.products)}</td></tr>`).join("");
  main.innerHTML = `<div class="wrap report">
    <div class="page-head">${month ? `<div class="crumbs"><a href="/raport" data-link>Raporti i sotëm</a></div>` : ""}<h1>raporti i çmimeve${month ? `, ${monthSq(month)}` : ""}</h1>
      <p>Të dhënat e ${dateSq(r.updated)}, nga ${plural(r.shops, "dyqan", "dyqane")} online në Shqipëri. ${month ? "Kopja e ruajtur e këtij muaji." : "Përditësohet çdo ditë."}</p></div>
    <section class="report-lead">
      <p class="big"><b class="num">${r.median_more_pct}%</b> më shumë</p>
      <p>paguan zakonisht te dyqani më i shtrenjtë, për të njëjtin produkt në të njëjtën madhësi. Kjo bën <b>${lek(r.median_diff)}</b> për produkt.
        Te <b>${r.share_over_20}%</b> e produkteve diferenca kalon 20%, te <b>${r.share_over_50}%</b> kalon 50%.
        Po të blije një herë secilin nga këto ${n(r.products)} produkte te dyqani më i shtrenjtë, do paguaje <b>${lek(r.total_diff)}</b> më shumë.</p>
      ${trend}
    </section>
    <section class="section"><h2>sipas kategorisë</h2>
      <p class="lead">Sa më shumë kërkon zakonisht dyqani më i shtrenjtë se më i liri.</p>
      <ol class="cat-bars">${cats}</ol></section>
    ${r.routine ? `<section class="section"><h2>një shembull: rutina bazë e lëkurës</h2>
      <p class="lead">Të njëjtat produkte, te dyqani më i lirë dhe te më i shtrenjti.</p>${receiptBox(r.routine)}</section>` : ""}
    <section class="section"><h2>dyqanet</h2>
      <p class="lead">Për produktet që i shet secili dyqan bashkë me të paktën dy të tjerë: sa shpesh ka çmimin më të ulët, dhe sa mbi çmimin më të ulët është zakonisht. Vetëm dyqanet me 40+ produkte të tilla.</p>
      <div class="table-scroll"><table class="offers shops-table"><thead><tr><th>Dyqani</th><th>Më i liri</th><th>Zakonisht mbi më të lirin</th><th>Produkte</th></tr></thead>
        <tbody>${shops}</tbody></table></div></section>
    <section class="section"><h2>diferencat më të mëdha në lek</h2>
      <div class="deals">${r.biggest.map(deal).join("")}</div></section>
    <section class="section"><h2>si e llogaritëm</h2>
      <p class="note">Vetëm produkte të njëjta (marka, emri dhe madhësia), në stok në 3 ose më shumë dyqane, me çmim në lek. Për çdo dyqan merret çmimi i tij më i ulët për atë produkt.
        Diferencat mbi 70% lihen jashtë, sepse zakonisht janë dy produkte të ndryshme. Mund ta citosh këtë raport me link te shporta.app/raport dhe datën.
        Çdo muaj ruajmë një kopje me të dhënat e ditës së fundit të muajit.</p></section>
    ${others.length ? `<section class="section"><h2>raportet e muajve</h2><p class="cats">${others.map((m) =>
      `<a href="/raport/${m}" data-link>${esc(monthSq(m))}</a>`).join("")}</p></section>` : ""}
  </div>`;
}

// on the home page: products in the visitor's list that are cheaper now than when they saved them
async function watchStrip() {
  const drops = (await watchFetch()).filter(dropped);
  if (!drops.length || location.pathname !== "/") return;
  const box = document.createElement("section");
  box.className = "section watch-strip";
  box.innerHTML = `<div class="wrap"><p><b>Ra çmimi te ${plural(drops.length, "produkt", "produkte")} që ndjek:</b>
    ${drops.slice(0, 3).map((w) => `<a href="/produkt/${esc(w.id)}" data-link>${esc(w.title)}</a> (${lek(w.price, w.currency)} → ${lek(w.now.min_price, w.currency)})`).join(", ")}${drops.length > 3 ? "…" : ""}
    <a class="btn" href="/lista" data-link>Shiko listën</a></p></div>`;
  main.prepend(box);
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

// "Share to shporta": the phone's Share menu opens /ndaj?title=…&text=…&url=… (installed web app on Android).
// Also a paste box, for iPhone and anyone without the app.
function cleanTitle(t) {
  // "JEANS TRF WIDE LEG - E zezë | ZARA Shqipëri" -> "JEANS TRF WIDE LEG - E zezë"
  return String(t || "").replace(/https?:\/\/\S+/g, " ").split(/\s[|•]\s/)[0].replace(/\s+/g, " ").trim();
}
async function pageShare(params) {
  const q = new URLSearchParams(params);
  const text = q.get("text") || "";
  const url = q.get("url") || (text.match(/https?:\/\/\S+/) || [""])[0];
  const title = cleanTitle(q.get("title") || text);
  document.title = "Krahaso një produkt | shporta";
  const form = `<form class="hero-search" id="share-form">
      <label class="sr" for="share-in">Linku ose emri i produktit</label>
      <input id="share-in" name="v" placeholder="Ngjit linkun e produktit ose shkruaj emrin">
      <button class="btn" type="submit">Krahaso</button></form>`;
  if (!url && !title) {
    main.innerHTML = `<div class="wrap"><div class="page-head"><h1>krahaso një produkt</h1>
      <p>Ngjit linkun e një produkti nga çdo dyqan online, ose shkruaj emrin e tij.</p></div>${form}
      <section class="section" style="border:0"><h2>më shpejt nga telefoni</h2>
      <p class="lead">Në Android: hap shporta.app në Chrome, zgjidh "Shto në ekranin kryesor". Pastaj, kur shikon një produkt në çdo dyqan,
      prek <b>Ndaj</b> dhe zgjidh <b>shporta</b>. Në iPhone: kopjo linkun e produktit dhe ngjite këtu.</p></section></div>`;
  } else {
    main.innerHTML = `<div class="wrap loading">Duke kërkuar ${esc(title || url)}…</div>`;
    const r = await fetch("/api/lookup", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, price: null, currency: "ALL", url }) }).then((x) => x.json()).catch(() => ({}));
    const exact = r.exact || [];  // out of stock too, marked: "not found" would be wrong when a shop lists it
    const same = r.same_name || [];
    const offerRow = (o, withTitle) => `<tr><td><b>${esc(shopName(o.shop))}</b>${withTitle || o.size ? `<span class="t">${esc(withTitle ? o.title : o.size)}</span>` : ""}${o.in_stock ? "" : `<span class="t">s'ka gjendje tani</span>`}</td>
      <td class="p"><span class="num">${lek(o.price, o.currency)}</span></td>
      <td>${shopLink(o, o.item, "ndaj", "btn btn-ghost")}</td></tr>`;
    // the same product name at shops whose size we can't confirm as the same: their own size is shown, never compared
    const sameRow = (o) => `<tr><td><b>${esc(shopName(o.shop))}</b><span class="t">${esc(o.size ? `madhësia: ${o.size}` : "dyqani nuk e shkruan madhësinë")}</span>${o.in_stock ? "" : `<span class="t">s'ka gjendje tani</span>`}</td>
      <td class="p"><span class="num">${lek(o.price, o.currency)}</span></td>
      <td>${shopLink(o, o.item, "ndaj", "btn btn-ghost")}</td></tr>`;
    const headline = exact.length
      ? `I njëjti produkt${r.query.size_label ? `, ${esc(r.query.size_label)},` : ""} gjendet në ${plural(exact.length, "dyqan", "dyqane")} të tjera, më i liri së pari.`
      : same.length ? `I njëjti produkt gjendet në ${plural(same.length, "dyqan", "dyqane")} të tjera, por nuk mund ta konfirmojmë që është e njëjta madhësi: shiko madhësinë te secili.`
      : "Nuk e gjetëm këtë produkt në dyqanet e tjera që krahasojmë.";
    const block = (h, rows, cls = "") => `<section class="section ${cls}" style="padding-top:10px"><h2>${h}</h2>
      <table class="offers"><tbody>${rows}</tbody></table></section>`;
    main.innerHTML = `<div class="wrap">
      <div class="page-head"><h1>${esc(title || "produkti yt")}</h1>
        <p>${headline}
          ${exact.length && r.query.size_assumed ? " Faqja e dyqanit nuk e shkruan madhësinë: e krahasuam sipas çmimit, kontrolloje te dyqani." : ""}</p></div>
      ${exact.length ? block("i njëjti produkt", exact.slice(0, 12).map((o) => offerRow(o, false)).join("")) : ""}
      ${same.length ? block(exact.length ? "edhe këto dyqane e kanë, në madhësi tjetër ose pa e shkruar madhësinë" : "i njëjti produkt, madhësia nuk konfirmohet",
          same.slice(0, 12).map(sameRow).join(""), "unconfirmed") : ""}
      ${!exact.length && !same.length && (r.similar || []).length ? block("të ngjashme: nuk e konfirmojmë që është i njëjti produkt", r.similar.slice(0, 8).map((o) => offerRow(o, true)).join(""), "apart") : ""}
      ${(r.dupes || []).length ? `<section class="section apart"><h2>dupe: një produkt tjetër, më i lirë</h2><div class="dps">${r.dupes.map((d) => dupePair(d, { showOrig: false })).join("")}</div></section>` : ""}
      <section class="section"><h2>krahaso një tjetër</h2>${form}</section></div>`;
  }
  document.getElementById("share-form").onsubmit = (e) => {
    e.preventDefault();
    const v = new FormData(e.currentTarget).get("v").trim();
    if (!v) return;
    go(/^https?:\/\//i.test(v) ? `/ndaj?url=${encodeURIComponent(v)}` : `/kerko?q=${encodeURIComponent(v)}`);
  };
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
    <section class="section"><h2>instalimi</h2>
      <p class="lead"><b>Microsoft Edge:</b> <a href="https://microsoftedge.microsoft.com/addons/detail/joenbehibjodnkecldnmggdpoigedceh" target="_blank" rel="noopener">shto shtesën nga dyqani i Edge</a>.<br>
        <b>Firefox:</b> së shpejti, është në shqyrtim te Mozilla.<br>
        <b>Chrome dhe shfletues të tjerë:</b> shtesa nuk është ende në Chrome Web Store. Deri atëherë përdor butonin më poshtë.</p>
    </section>
    <section class="section" id="bookmarklet"><h2>butoni "Krahaso në shporta"</h2>
      <p class="lead">Një buton në shiritin e faqeve të ruajtura (bookmarks), pa instaluar asgjë. Funksionon në Chrome, Edge, Firefox, Brave dhe Opera në kompjuter.</p>
      <p><a class="btn bookmarklet" href="${BOOKMARKLET}" draggable="true" title="Tërhiqe në shiritin e bookmarks">Krahaso në shporta</a></p>
      <ol>
        <li>Nëse nuk e sheh shiritin e bookmarks, shtyp <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>B</kbd> (në Mac <kbd>⌘</kbd>+<kbd>Shift</kbd>+<kbd>B</kbd>).</li>
        <li>Tërhiq butonin vjollcë më sipër me maus dhe lësho atë në shiritin e bookmarks.</li>
        <li>Kur shikon një produkt në çdo dyqan online, kliko <b>Krahaso në shporta</b> në shirit. Shporta hapet në një skedë të re me të njëjtin produkt, në të njëjtën madhësi, në dyqanet e tjera.</li>
      </ol>
      <p class="lead">Butoni i dërgon shportës vetëm adresën dhe emrin e faqes që ke hapur, njësoj si kur ngjit linkun te <a href="/ndaj" data-link>Krahaso një link</a>. Në telefon përdor <a href="/ndaj" data-link>Krahaso një link</a>.</p>
    </section>
  </div>`;
  const b = main.querySelector(".bookmarklet");
  b.onclick = (e) => { e.preventDefault(); b.textContent = "Tërhiqe në shiritin e bookmarks, mos e kliko këtu"; };
}

// The bookmark button: opens /ndaj for the page it's clicked on, with the product's name (og:title, else the first
// heading, else the tab title; /ndaj strips the "| Shop" part) and the page address, which identifies pages we know.
const BOOKMARKLET = "javascript:(()=>{const m=document.querySelector('meta[property=&quot;og:title&quot;]'),h=document.querySelector('h1'),"
  + "t=((m&&m.content)||(h&&h.innerText)||document.title).trim().slice(0,200);"
  + "window.open('https://shporta.app/ndaj?url='+encodeURIComponent(location.origin+location.pathname)+'&amp;title='+encodeURIComponent(t))})()";

function pagePrivacy() {
  document.title = "Cookies dhe privatësia | shporta";
  const c = getCookie("sp_consent");
  main.innerHTML = `<div class="wrap prose">
    <div class="page-head"><h1>cookies dhe privatësia</h1><p>Çfarë mbledhim kur përdor shportën, dhe pse.</p></div>
    <h2>Cookies të domosdoshme</h2>
    <p><code>sp_consent</code> ruan zgjedhjen tënde për cookies, për një vit. Pa të, do të të pyesnim në çdo vizitë.</p>
    <h2>Cookies për statistika, vetëm me lejen tënde</h2>
    <p><code>sp_id</code> është një numër i rastësishëm, pa emër apo email. Na tregon sa vizitorë të ndryshëm klikojnë drejt dyqaneve, që të dimë sa vlen shporta për to.</p>
    <h2>Sa vizitorë kemi, pa cookies</h2>
    <p>Për çdo faqe që hap numërojmë llojin e faqes, ditën dhe faqen nga erdhe (p.sh. google.com). Që një vizitor të numërohet
      vetëm një herë në ditë, përdorim një kod të përkohshëm të krijuar nga adresa dhe shfletuesi yt bashkë me një çelës që
      ndryshon çdo ditë dhe fshihet. Adresën (IP) nuk e ruajmë, dhe të nesërmen kodi nuk mund të lidhet më me ty.</p>
    <h2>Numri i klikimit</h2>
    <p>Linku që të çon te dyqani ka një numër të rastësishëm klikimi (sp_click), krahas shenjës utm_source=shporta. Ai nuk lidhet me ty:
      nuk ruajmë adresën tënde, as cookie, as emër. Një dyqan që bashkëpunon me ne mund të na thotë vetëm "porosia nga ky klikim u krye",
      që të dimë sa blerje sjell shporta.</p>
    <h2>Produktet që ndjek</h2>
    <p>Kur shtyp "Ndiq çmimin", produkti dhe çmimi i asaj dite ruhen vetëm në këtë shfletues (localStorage), jo te ne.
      Kur hap listën, shfletuesi na kërkon vetëm çmimet e sotme për ato produkte. Për ta fshirë, hiqi nga lista ose fshi të dhënat e faqes.</p>
    <h2>Njoftimet me email</h2>
    <p>Nëse kërkon njoftim kur bie çmimi, ruajmë vetëm emailin, produktin dhe çmimin. Të shkruajmë vetëm pasi ta konfirmosh me linkun që të dërgojmë,
      dhe vetëm kur çmimi bie. Emailet i dërgon për ne shërbimi Resend. Adresën nuk e ndajmë dhe nuk e shesim me askënd; një kërkesë e pakonfirmuar
      fshihet pas 7 ditësh, dhe çdo email ka një link që i ndalon njoftimet dhe e fshin adresën.</p>
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

// How it works + FAQ: one text (web/pages/rreth.html), also what the server sends to search engines
async function pageAbout() {
  const r = await fetch("/pages/rreth.html");
  if (!r.ok) throw new Error("Faqja nuk u ngarkua.");
  main.innerHTML = await r.text();
  document.title = "Si funksionon shporta: krahasimi i çmimeve në Shqipëri | shporta";
}

/* ---------- router ---------- */

function setFoot(updated) {
  if (!updated) return;
  const d = new Date(updated);
  document.getElementById("foot-updated").textContent =
    `Çmimet u përditësuan më ${dateSq(d)}.`;
}

async function route() {
  const { pathname, search } = location;
  const params = search.slice(1);
  document.querySelectorAll(".top-nav a").forEach((a) => {
    if (pathname.startsWith(a.getAttribute("href"))) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  // the links in our emails open pages the server writes in full: nothing to add to them
  if (pathname.startsWith("/njoftim/") && main.hasAttribute("data-ssr")) return;
  // the first page already came from the server (seo.py): keep it on screen until the full one is ready
  if (main.hasAttribute("data-ssr")) main.removeAttribute("data-ssr");
  else main.innerHTML = `<div class="wrap loading">Duke ngarkuar…</div>`;
  document.title = "shporta: krahaso çmimet e modës dhe kozmetikës në Shqipëri";
  try {
    let m;
    if (pathname === "/") { await pageHome(); watchStrip(); }
    else if (pathname === "/kategorite") await pageCategories();
    else if ((m = pathname.match(/^\/kategori\/([\w-]+)$/))) await pageCategory(m[1], params);
    else if ((m = pathname.match(/^\/produkt\/([\w-]+)$/))) await pageItem(m[1]);
    else if (pathname === "/kerko") await pageSearch(params);
    else if (pathname === "/dyqanet") await pageShops();
    else if (pathname === "/shtesa") pageExtension();
    else if (pathname === "/privatesia") pagePrivacy();
    else if (pathname === "/rreth") await pageAbout();
    else if (pathname === "/dupe") await pageDupes(params);
    else if (pathname === "/ndaj") await pageShare(params);
    else if (pathname === "/lista") await pageList();
    else if (pathname === "/raport") await pageReport();
    else if ((m = pathname.match(/^\/raport\/(\d{4}-\d{2})$/))) await pageReport(m[1]);
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
watchBadge();
consentBanner();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
