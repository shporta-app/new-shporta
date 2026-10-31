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
  if (o.via === "user") out.push(`<span class="hist">çmimi i parë nga një përdorues i shportës më ${day(o.seen)}: ky dyqan nuk lejon leximin automatik, kontrolloje te dyqani</span>`);
  else if (o.seen && daysAgo(o.seen) >= 1) out.push(`<span class="hist">çmimi i parë më ${day(o.seen)}</span>`);
  return out.length ? `<br>${out.join("<br>")}` : "";
}
// Shops write titles their own way ("CeraVe – Moisturizing Cream - Sasia: 340gr", "Serum 30 ml - 30 ml", all in capitals).
// For reading we drop the size labels and a size repeated at the end, and soften all-capital titles. Display only:
// the exact title each shop uses stays on its row of the price table.
const ACRONYM = /^(SPF|EDP|EDT|EDC|UV|UVA|UVB|AHA|BHA|PHA|NYX|CBD|DHA|HA|MAC|NARS|YSL|DKNY|CK|BB|CC|XL|XXL|XS|USB|LED|TV|HD|PRO|II|III)$/;
function nice(t, size) {
  let s = String(t || "").replace(/\s*[-–|,/]?\s*\b(sasia|v[eë]llimi|format|madh[eë]sia|pesha|pesh[eë]|size)\s*:\s*/gi, " - ")
    .replace(/\s+\|\s+/g, " ").replace(/\s+/g, " ").trim();
  const n = String(size || "").match(/^\d+(?:[.,]\d+)?/);
  if (n) {
    const end = new RegExp(`\\s*[-–*,/]?\\s*${n[0].replace(/[.,]/, "[.,]")}\\s*(ml|g|gr|l|kg|cl|cop[eë]|kapsula|caps|tableta|tab)?\\.?\\s*$`, "i");
    for (let i = 0; i < 2 && end.test(s) && s.replace(end, "").length > 8; i++) s = s.replace(end, "");
  }
  s = s.replace(/\s*[-–]\s*$/, "").replace(/\s[-–]\s[-–]\s/g, " – ");
  const letters = s.replace(/[^A-Za-zÀ-ž]/g, "");
  if (letters.length > 10 && letters.replace(/[^A-ZÀ-Þ]/g, "").length / letters.length > 0.7)
    s = s.split(" ").map((w) => ACRONYM.test(w) || /\d/.test(w) ? w : w.charAt(0) + w.slice(1).toLowerCase()).join(" ");
  return s;
}
function mono(shop) {
  const name = shopName(shop);
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `<span class="mono" style="--h:${h}" aria-hidden="true">${esc(name.charAt(0).toUpperCase())}</span>`;
}
const EASE_OUT = "cubic-bezier(0.23, 1, 0.32, 1)";
const calm = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
// a sheet at the bottom leaves the way it came in, then goes away
function dismiss(el) {
  if (!el) return;
  if (calm() || !el.animate) return el.remove();
  el.animate([{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateY(16px)" }], { duration: 180, easing: EASE_OUT })
    .finished.then(() => el.remove(), () => el.remove());
}
const shopName = (d) => String(d || "").replace(/^www\./, "");
const plural = (n, one, many) => `${n.toLocaleString("en").replace(/,/g, " ")} ${n === 1 ? one : many}`;
// Shopify shops serve any picture at the width asked for: 500 px is sharp on a phone and about a quarter of the bytes
const small = (src) => /^https:\/\/(cdn\.shopify\.com\/|[^/]+\/cdn\/shop\/)/.test(src) && !/[?&]width=/.test(src)
  ? src + (src.includes("?") ? "&" : "?") + "width=500" : src;
const img = (src, alt = "") =>
  src ? `<img src="${esc(small(src))}" alt="${esc(alt)}" loading="lazy" decoding="async" referrerpolicy="no-referrer" data-fade onload="this.classList.add('in')" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'noimg',textContent:'Pa foto'}))">`
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
const watchSave = (l) => { try { localStorage.setItem(WATCH_KEY, JSON.stringify(l.slice(0, 100))); } catch {} watchBadge(); pushSync(); };
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
  a.hidden = !n && !savings().length;
  a.querySelector("span").textContent = n ? ` (${n})` : "";
}

/* ---------- Notifications ---------- */
// In the app: the bell lists price drops on products the visitor follows, worked out here and kept only in this browser.
// Outside it: with the visitor's permission the browser gives us a push address, and each night after the price update
// the server (push.py) sends a notification when a followed product gets cheaper, even with shporta closed.
const NOTES_KEY = "shporta-njoftime";
const notes = () => { try { return JSON.parse(localStorage.getItem(NOTES_KEY)) || []; } catch { return []; } };
const notesSave = (l) => { try { localStorage.setItem(NOTES_KEY, JSON.stringify(l.slice(0, 50))); } catch {} bellBadge(); };
function bellBadge() {
  const a = document.getElementById("nav-bell");
  if (!a) return;
  const n = notes().filter((x) => !x.read).length;
  a.querySelector("b").textContent = n ? (n > 9 ? "9+" : String(n)) : "";
  a.setAttribute("aria-label", n ? `Njoftimet, ${n} të reja` : "Njoftimet");
}
// a followed product cheaper than the last time we told the visitor (or than the day they followed it)
async function noteDrops() {
  const l = await watchFetch();
  const list = watchList(), add = [], today = new Date().toISOString().slice(0, 10);
  for (const w of l) {
    const mine = list.find((x) => x.id === w.id);
    if (!dropped(w) || !mine || w.now.min_price >= (mine.told ?? w.price)) continue;
    add.push({ id: w.id, title: w.title, image: w.image, size: w.size, cur: w.currency, was: mine.told ?? w.price,
               now: w.now.min_price, date: today });
    mine.told = w.now.min_price;
  }
  if (!add.length) return;
  try { localStorage.setItem(WATCH_KEY, JSON.stringify(list)); } catch {}
  notesSave([...add, ...notes()]);
}

function pushReady() { return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window; }
function onIPhone() { return /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1); }
function asApp() { return matchMedia("(display-mode: standalone)").matches || navigator.standalone === true; }
const keyBytes = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4)), (c) => c.charCodeAt(0));
const pushItems = () => watchList().map((w) => ({ id: w.id, price: w.price }));
async function pushSub() {
  if (!pushReady()) return null;
  return (await navigator.serviceWorker.ready).pushManager.getSubscription();
}
async function pushPost(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || "Diçka shkoi keq. Provo përsëri.");
  return d;
}
async function pushOn() {
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error(perm === "denied"
    ? "Njoftimet janë bllokuar për shporta.app. Lejoji te cilësimet e shfletuesit (ikona pranë adresës), pastaj provo përsëri."
    : "Nuk dhe leje për njoftime.");
  const { key } = await api("/api/push/key");
  const reg = await navigator.serviceWorker.ready;
  const sub = (await reg.pushManager.getSubscription())
    || (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) }));
  return pushPost("/api/push/subscribe", { subscription: sub.toJSON(), items: pushItems() });
}
async function pushOff() {
  const sub = await pushSub();
  if (!sub) return;
  await pushPost("/api/push/unsubscribe", { endpoint: sub.endpoint }).catch(() => {});
  await sub.unsubscribe();
}
// the list changed: the server gets the new list for this device (only when notifications are on)
let pushTimer;
function pushSync() {
  clearTimeout(pushTimer);
  pushTimer = setTimeout(async () => {
    const sub = await pushSub().catch(() => null);
    if (sub && Notification.permission === "granted")
      pushPost("/api/push/subscribe", { subscription: sub.toJSON(), items: pushItems() }).catch(() => {});
  }, 800);
}

function pushCard(el) {
  if (!el) return;
  const draw = async (msg = "", err = false) => {
    if (!pushReady()) {
      el.innerHTML = `<h2>njoftime në telefon</h2><p>${onIPhone() && !asApp()
        ? "Në iPhone njoftimet punojnë kur shporta është në ekranin kryesor: në Safari shtyp Ndaj (katrori me shigjetë lart), pastaj “Add to Home Screen”. Hape shportën nga ikona dhe aktivizo njoftimet këtu."
        : "Ky shfletues nuk i mbështet njoftimet. Provo Chrome, Edge, Firefox ose Safari."}</p>`;
      return;
    }
    const sub = await pushSub().catch(() => null);
    const on = Boolean(sub) && Notification.permission === "granted";
    const state = on ? "Aktive në këtë pajisje" : Notification.permission === "denied" ? "Të bllokuara në këtë shfletues" : "Joaktive";
    el.innerHTML = `<h2>njoftime në telefon dhe kompjuter</h2>
      <p>Një njoftim kur bie çmimi i një produkti që ndjek, edhe kur shporta është e mbyllur. Të njoftojmë një herë në ditë, në mëngjes (pas orës 9), pasi përditësohen çmimet. Pa llogari dhe pa email.</p>
      <div class="row"><span class="state${on ? " on" : ""}">${state}</span>
        ${on ? `<button type="button" class="btn" id="push-test">Dërgo një njoftim provë</button>` : ""}
        <button type="button" class="btn${on ? " btn-ghost" : ""}" id="push-toggle">${on ? "Çaktivizo njoftimet" : "Aktivizo njoftimet"}</button></div>
      ${msg ? `<p class="${err ? "err" : "ok"}" role="status">${esc(msg)}</p>` : ""}`;
    const t = el.querySelector("#push-test");
    if (t) t.onclick = async () => {
      t.disabled = true;
      try { draw((await pushPost("/api/push/test", { endpoint: sub.endpoint })).message); }
      catch (x) { draw(x.message, true); }
    };
    el.querySelector("#push-toggle").onclick = async (e) => {
      e.target.disabled = true;
      try {
        if (on) { await pushOff(); draw("Njoftimet u çaktivizuan në këtë pajisje."); }
        else {
          const d = await pushOn();
          draw(watchList().length ? d.message : "Njoftimet janë aktive. Ndiq një produkt (“Ndiq çmimin”) dhe të njoftojmë kur i bie çmimi.");
        }
      } catch (x) { draw(x.message, true); }
    };
  };
  draw();
}

async function pageNotes() {
  document.title = "Njoftimet | shporta";
  await noteDrops().catch(() => {});
  const l = notes();
  const row = (n) => `<li class="${n.read ? "" : "unread"}"><a href="/produkt/${esc(n.id)}" data-link>${img(n.image, n.title)}
      <span><span class="t">Ra çmimi: ${esc(n.title)}${n.size ? ` <small>${esc(n.size)}</small>` : ""}</span>
        Tani <b class="num">${lek(n.now, n.cur)}</b>, ishte ${lek(n.was, n.cur)}.<br><small>${esc(day(n.date))}</small></span></a></li>`;
  main.innerHTML = `<div class="wrap">
    <div class="page-head"><h1>njoftimet</h1>
      <p>Kur bie çmimi i një produkti që ndjek, e sheh këtu. Njoftimet ruhen vetëm në këtë shfletues.</p></div>
    <section class="push-card" id="push-card" aria-live="polite"></section>
    ${l.length ? `<ul class="notes">${l.map(row).join("")}</ul>`
      : `<div class="empty"><b>Asnjë njoftim ende.</b>${watchList().length
        ? "Kur bie çmimi i një produkti që ndjek, e sheh këtu."
        : "Hap një produkt dhe shtyp “Ndiq çmimin”. Kur i bie çmimi, të njoftojmë."}</div>`}
  </div>`;
  pushCard(document.getElementById("push-card"));
  if (l.some((n) => !n.read)) notesSave(l.map((n) => ({ ...n, read: true })));
}

// "Kursimet e mia": when a visitor goes from shporta to a shop, this browser notes how much less that shop asks than
// the dearest shop for the same product. Kept only here (localStorage), never sent to us. It is a possible saving:
// we don't know whether they bought.
const SAVE_KEY = "shporta-kursime";
const OFFERS_ON_SCREEN = new Map();  // offer id -> what a click on it means; only offers of an exact comparison
function noteOffers(item, offers) {
  const live = offers.filter((o) => o.in_stock && o.currency === item.currency);
  if (new Set(live.map((o) => o.shop)).size < 2) return;  // one shop: nothing compared, no saving to claim
  const dear = Math.max(...live.map((o) => o.price));
  for (const o of live) OFFERS_ON_SCREEN.set(String(o.id), { item: item.id, title: item.title, price: o.price, dear, cur: o.currency });
}
const savings = () => { try { return JSON.parse(localStorage.getItem(SAVE_KEY)) || []; } catch { return []; } };
document.addEventListener("click", (e) => {
  const a = e.target.closest('a[href^="/go/"]');
  const info = a && OFFERS_ON_SCREEN.get(a.getAttribute("href").split("/")[2].split("?")[0]);
  if (!info || info.dear <= info.price) return;
  const today = new Date().toISOString().slice(0, 10);
  const log = savings().filter((x) => !(x.item === info.item && x.date === today));  // one entry per product per day
  log.unshift({ ...info, saved: info.dear - info.price, date: today });
  try { localStorage.setItem(SAVE_KEY, JSON.stringify(log.slice(0, 300))); } catch {}
}, true);
// milestones: what the visitor has done, never a promise of money
const BADGES = [
  { id: "first", name: "Krahasimi i parë", test: (s) => s.n >= 1, how: "Kalo te dyqani më i lirë një herë" },
  { id: "hunter", name: "Gjuetar zbritjesh", test: (s) => s.n >= 5, how: "5 herë te një dyqan më i lirë" },
  { id: "5k", name: "5 000 L kursim i mundshëm", test: (s) => s.total >= 5000, how: "Mblidh 5 000 L" },
  { id: "20k", name: "20 000 L kursim i mundshëm", test: (s) => s.total >= 20000, how: "Mblidh 20 000 L" },
  { id: "watch", name: "Ndjekës i çmimeve", test: (s) => s.watched >= 5, how: "Ndiq 5 produkte" },
];
function savingsSummary() {
  const log = savings().filter((x) => x.cur === "ALL");
  const month = new Date().toISOString().slice(0, 7);
  const sum = (l) => l.reduce((t, x) => t + x.saved, 0);
  return { log, n: log.length, total: sum(log), month: sum(log.filter((x) => x.date.startsWith(month))), watched: watchList().length };
}
function savingsBox() {
  const s = savingsSummary();
  const badges = BADGES.map((b) => `<li class="${b.test(s) ? "got" : ""}" title="${esc(b.how)}">${esc(b.name)}</li>`).join("");
  return `<section class="savings" aria-labelledby="sav-h">
    <h2 id="sav-h">kursimet e mia</h2>
    ${s.n ? `<div class="sav-nums"><p><b class="num">${lek(s.month)}</b>këtë muaj</p><p><b class="num">${lek(s.total)}</b>gjithsej, ${plural(s.n, "herë", "herë")}</p></div>`
      : `<p class="note">Kur kalon nga shporta te dyqani më i lirë, këtu shfaqet sa më pak kërkon ai se dyqani më i shtrenjtë për të njëjtin produkt.</p>`}
    <ul class="badges">${badges}</ul>
    <p class="note">Kursim i mundshëm: diferenca mes çmimit të dyqanit ku kalove dhe dyqanit më të shtrenjtë, për të njëjtin produkt në të njëjtën madhësi.
      Nuk e dimë nëse e bleve. Ruhet vetëm në këtë shfletues.</p>
    ${s.n ? `<details><summary>Ku kalove</summary><ul class="sav-log">${s.log.slice(0, 20).map((x) =>
      `<li><a href="/produkt/${esc(x.item)}" data-link>${esc(x.title)}</a> <span>${day(x.date)}: ${lek(x.price)}, ${lek(x.saved)} më pak</span></li>`).join("")}</ul></details>` : ""}
  </section>`;
}

/* ---------- shared pieces ---------- */

// One product, every shop's price: a bar per shop ending in a price tag; the cheapest in-stock one is lime.
function ruler(item, { heading = "h3", animate = false, linkHead = true, showHead = true, from = "ballina" } = {}) {
  const offers = (item.offers || []).filter((o) => o.currency === item.currency);
  if (!offers.length) return "";
  noteOffers(item, offers);
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
  const head = `${img(item.image, item.title)}<div><${heading}>${esc(nice(item.title, item.size))}${item.size ? ` <small>${esc(item.size)}</small>` : ""}</${heading}>
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
    <span class="pic">${img(it.image, it.title)}${range && it.save_pct >= 5 ? `<span class="off">−${it.save_pct}%</span>` : ""}</span>
    <span class="name">${esc(nice(it.title, it.size))}</span>${it.size ? `<span class="size">${esc(it.size)}</span>` : ""}
    <span class="meta"><span class="num">${it.shops > 1 ? "nga " : ""}${lek(it.min_price, it.currency)}</span>${it.shops > 1
      ? `<small>në ${plural(it.shops, "dyqan", "dyqane")}</small>` : ""}</span>
  </a>`;
}

function deal(it) {
  return `<a class="deal" href="/produkt/${esc(it.id)}" data-link>
    ${img(it.image, it.title)}
    <span><span class="name">${esc(nice(it.title, it.size))}${it.size ? ` <small>${esc(it.size)}</small>` : ""}</span>
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
      <span><small>Origjinali</small><span class="dp-name">${esc(nice(r.orig_title, r.orig_size))}</span>
        <span class="num">${lek(r.orig_price)}${size(r.orig_size)}</span></span></a>` : "";
  return `<div class="dp${showOrig ? "" : " dp-single"}">
    ${orig}
    <a class="dp-side dp-dupe" href="/produkt/${esc(r.dupe_id)}" data-link>
      <span class="dp-pic">${img(r.dupe_image, r.dupe_title)}</span>
      <span><small>Dupe</small><span class="dp-name">${esc(nice(r.dupe_title, r.dupe_size))}</span>
        <span class="num">${lek(r.dupe_price)}${size(r.dupe_size)}</span></span></a>
    <div class="dp-why"><span class="save">−${r.save_pct}%${r.orig_size && r.dupe_size && r.orig_size !== r.dupe_size ? " për ml" : ""}</span>
      <span class="chip">${esc(r.reason)}</span><small>${DUPE_WHY[r.kind] || ""}</small></div>
  </div>`;
}

// long lists show a handful at a time; "Shfaq më shumë" adds the next ones under them (and asks the server for the
// next page when what we have runs out). box: the list's element, already on the page. next(page) -> {items}
const STEP = 12;
function growList(box, { items, render, total, page = 0, next = null, step = STEP, noun = ["produkt", "produkte"] }) {
  if (!box) return;
  const buf = items.slice();
  let shown = 0, busy = false;
  const foot = document.createElement("div");
  foot.className = "grow";
  foot.innerHTML = `<p class="grow-count"></p><button type="button" class="btn btn-ghost">Shfaq më shumë</button>`;
  box.after(foot);
  const btn = foot.querySelector("button"), count = foot.querySelector(".grow-count");
  const add = async () => {
    if (busy) return;
    busy = true;
    if (buf.length < step && shown + buf.length < total && next) {
      btn.textContent = "Duke ngarkuar…";
      try { buf.push(...(await next(++page)).items); } catch { page--; }
      btn.textContent = "Shfaq më shumë";
    }
    const part = buf.splice(0, step);
    box.insertAdjacentHTML("beforeend", part.map(render).join(""));
    shown += part.length;
    const left = Math.max(total - shown, 0);
    count.textContent = `${shown} nga ${total} ${total === 1 ? noun[0] : noun[1]}`;
    foot.hidden = !left || (!buf.length && !next);
    busy = false;
  };
  btn.onclick = add;
  add();
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
    <input id="${id}" name="q" type="search" value="${esc(value)}" placeholder="Kërko produkt ose markë" enterkeyhint="search">
    <button class="btn" type="submit">Kërko</button>
  </form>`;

/* ---------- pages ---------- */

// an empty page shows where to start: the products with the biggest gap between shops today
async function startHere() {
  const d = homeCache || (homeCache = await api("/api/home").catch(() => null));
  return d && d.deals.length ? `<section class="section start"><h2>fillo nga këto</h2>
    <p class="lead">Produktet me diferencën më të madhe mes dyqaneve sot.</p>
    <div class="grid">${d.deals.slice(0, 6).map(tile).join("")}</div></section>` : "";
}

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
      <p>Shiko ku kushton më pak, para se ta blesh. Krahasojmë ${s.shops} dyqane online në Shqipëri.</p>
      ${searchForm("q-hero")}
      <nav class="quick" aria-label="Kategoritë">${d.categories.filter((c) => c.count >= 100 && c.id !== "tjeter").sort((a, b) => b.count - a.count)
        .map((c) => `<a href="/kategori/${c.id}" data-link>${esc(c.label)}</a>`).join("")}</nav>
      <p class="hero-stats"><b class="num">${s.compared.toLocaleString("en").replace(/,/g, " ")}</b> produkte të krahasuara,
        <b class="num">${s.offers.toLocaleString("en").replace(/,/g, " ")}</b> çmime, të përditësuara çdo ditë.</p>
    </div>
    <div id="featured">${d.featured.length ? ruler(d.featured[fi], { animate: true }) : ""}
      ${d.featured.length > 1 ? `<div class="ruler-foot"><span>Të dhëna reale nga dyqanet</span><button type="button" id="next">Një produkt tjetër</button></div>` : ""}
    </div>
  </div></section>

  ${impactSection(d)}

  <section class="section"><div class="wrap">
    <div class="section-head"><h2>diferencat më të mëdha tani</h2></div>
    <p class="lead">I njëjti produkt, në stok në të paktën tre dyqane. Përqindja tregon sa më lirë është te dyqani më i lirë.</p>
    <div class="deals" id="home-deals"></div>
  </div></section>

  <section class="section"><div class="wrap">
    <h2>kategoritë</h2>
    <p class="lead">Produktet që gjenden në dy ose më shumë dyqane, të renditura sipas llojit.</p>
    ${catTiles(d.categories)}
  </div></section>

  ${d.dupes && d.dupes.length ? `<section class="section"><div class="wrap">
    <div class="section-head"><h2>dupe të produkteve të shtrenjta</h2><a href="/dupe" data-link>Të gjitha dupe</a></div>
    <p class="lead">Jo i njëjti produkt, por bën të njëjtën punë për shumë më pak. Te parfumet, dyqani vetë thotë nga cili parfum është frymëzuar;
      te kujdesi i lëkurës, përbërësi kryesor dhe përqindja janë të njëjta; te grimi, janë dupe që krahasohen gjerësisht.</p>
    <div class="dps">${d.dupes.slice(0, 3).map((r) => dupePair(r)).join("")}</div>
  </div></section>` : ""}

  <section class="section"><div class="wrap">
    <div class="band">
      <div><h2>kontrollo çmimin kudo që blen</h2>
        <p>Shtesa e shportës për shfletuesin hapet vetë kur shikon një produkt në një dyqan online dhe të tregon nëse çmimi është i mirë, normal apo i lartë, dhe ku e gjen më lirë.</p>
        <a class="btn" href="/shtesa" data-link>Si ta instalosh</a></div>
      <ol><li>Hap një produkt në një dyqan online shqiptar.</li>
        <li>Shporta krahason çmimin me dyqanet e tjera.</li>
        <li>Blej aty ku është më lirë.</li></ol>
    </div>
  </div></section>`;
  growList(document.getElementById("home-deals"), { items: d.deals, render: deal, total: d.deals.length, step: 8 });
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
          <span><small>${esc(s.step)}</small>${esc(nice(s.title, s.size))}</span>
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

// the categories as a catalogue: a square per category, with the product most shops sell in it and how many we compare
const catTiles = (cats) => `<div class="cat-grid">${cats.filter((c) => c.count)
  .sort((a, b) => (a.id === "tjeter") - (b.id === "tjeter") || b.count - a.count).map((c) =>
  `<a class="cat-tile" href="/kategori/${c.id}" data-link>
    <span class="cat-pic">${c.image ? `<img src="${esc(c.image)}" alt="" loading="lazy" data-fade onload="this.classList.add('in')">` : ""}</span>
    <span class="cat-name">${esc(c.label)}</span>
    <span class="cat-count">${plural(c.count, "produkt", "produkte")}</span></a>`).join("")}</div>`;
async function pageCategories() {
  const d = homeCache || (homeCache = await api("/api/home"));
  main.innerHTML = `<div class="wrap"><div class="page-head"><h1>kategoritë</h1>
    <p>${plural(d.stats.compared, "produkt", "produkte")} gjenden në më shumë se një dyqan.</p></div>
    ${catTiles(d.categories)}</div>`;
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
      <fieldset class="sorts"><legend class="sr">Rendit</legend>
        ${[["compared", "Në më shumë dyqane"], ["gap", "Kursimi më i madh"], ["cheap", "Më të lirat"], ["dear", "Më të shtrenjtat"]].map(([v, label]) =>
          `<label><input type="radio" name="sort" value="${v}" ${(q.get("sort") || "compared") === v ? "checked" : ""}><span>${label}</span></label>`).join("")}
      </fieldset>
      <label>Dyqani <select name="shop"><option value="">Të gjitha</option>${d.shops.map((s) => opt(s, shopName(s), q.get("shop"))).join("")}</select></label>
    </form>
    ${d.items.length ? `<div class="grid" id="list"></div>`
      : `<div class="empty"><b>Asnjë produkt me këto filtra.</b>Hiq një filtër ose zgjidh një dyqan tjetër.</div>`}
  </div>`;
  growList(document.getElementById("list"), { items: d.items, render: tile, total: d.total, page: d.page,
    next: (p) => { const n = new URLSearchParams(q); n.set("page", p); return api(`/api/category/${encodeURIComponent(cat)}?${n}`); } });
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
  if (multiShop) noteOffers(it, it.offers);
  const fold = it.offers.length > 8;  // many shops: the cheapest 6 first, the rest one tap away
  const rows = it.offers.map((o, i) => `<tr class="${o.in_stock ? "" : "out"}${o.in_stock && o.price === lo && multiShop ? " is-best" : ""}${fold && i >= 6 ? " extra" : ""}">
      <td><b>${mono(o.shop)}${esc(shopName(o.shop))}</b><span class="t">${esc(o.title)}</span>${o.risk ? `<span class="risk">Shumë më lirë se dyqanet e tjera: kontrollo që është origjinal dhe e njëjta madhësi.</span>` : ""}</td>
      <td class="p"><span class="num">${lek(o.price, o.currency)}</span>${o.regular_price > o.price ? `<br><s class="t">${lek(o.regular_price, o.currency)}</s>` : ""}${priceNote(o)}</td>
      <td>${o.in_stock ? diffCell(o) : "S'ka gjendje"}</td>
      <td>${shopLink(o, it.id, "produkt", `btn ${o.in_stock && o.price === lo ? "" : "btn-ghost"}`)}</td>
    </tr>`).join("");
  // shops that sell it without writing the size: shown, but never compared (we can't confirm it's the same size)
  const unconfirmed = (it.unconfirmed || []).map((o) => `<tr class="${o.in_stock ? "" : "out"}">
      <td><b>${mono(o.shop)}${esc(shopName(o.shop))}</b><span class="t">${esc(o.title)}</span></td>
      <td class="p"><span class="num">${lek(o.price, o.currency)}</span></td>
      <td>${o.in_stock ? "Kontrollo madhësinë" : "S'ka gjendje"}</td>
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
        <h1>${esc(nice(it.title, it.size))}</h1>
        ${it.used ? `<p class="size-warn">Artikull i përdorur (second-hand / vintage). Nuk e krahasojmë me produkte të reja.</p>` : ""}
        ${it.size ? `<p class="size-line">Krahasojmë vetëm madhësinë <b>${esc(it.size)}</b>. Çdo dyqan më poshtë e shkruan këtë madhësi te produkti.</p>` : ""}
        ${cheap && multiShop ? `<div class="best-card">
            ${mono(cheap.shop)}<span class="bc-shop"><small>Më i liri sot</small><b>${esc(shopName(cheap.shop))}</b></span>
            <b class="bc-price num">${lek(lo, it.currency)}</b>
            ${shopLink(cheap, it.id, "produkt", "btn btn-ink")}
          </div>
          <p class="spread">${live.length > 1 && hi > lo ? `Te dyqanet e tjera deri në <b class="num">${lek(hi, it.currency)}</b>. Kursen deri
            <b class="num">${lek(hi - lo, it.currency)}</b>. ` : ""}${plural(it.offers.length, "dyqan", "dyqane")} e shesin këtë produkt.</p>`
        : `<div class="summary">
          ${live.length ? `<div class="low">Më i liri<b>${lek(lo, it.currency)}</b></div>`
            : `<div>S'ka gjendje askund<b>${lek(lo, it.currency)}</b></div>`}
          <div>${multiShop ? "Dyqane" : "Variante"}<b>${it.offers.length}</b></div>
        </div>`}
        ${multiShop ? ruler(it, { showHead: false, animate: true, from: "produkt" }) : ""}
        <table class="offers"><thead><tr><th>Dyqani</th><th style="text-align:right">Çmimi</th><th>${multiShop ? "Sa më shumë" : "Gjendja"}</th><th></th></tr></thead>
          <tbody>${rows}</tbody></table>
          ${fold ? `<button type="button" class="btn btn-ghost more-shops" onclick="this.previousElementSibling.classList.add('all');this.remove()">Shfaq të gjitha dyqanet (${it.offers.length})</button>` : ""}
        ${story}
        <p class="watch"><button type="button" class="btn" id="basket-add" aria-pressed="${inBasket(it.id)}"></button>
          <button type="button" class="btn btn-ghost" id="watch" aria-pressed="${watching(it.id)}"></button>
          <button type="button" class="btn btn-ghost share-btn" id="share-item" aria-label="Ndaj këtë produkt"><svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V3M8 7l4-4 4 4M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg>Ndaj</button>
          <small>Ruhet vetëm në këtë shfletues. Kur rihap shportën, të tregojmë nëse çmimi ra.</small></p>
        ${it.alerts ? `<form class="alert-form" id="alert-form">
          <label for="alert-email">Më njofto me email kur bie çmimi</label>
          <span><input id="alert-email" name="email" type="email" autocomplete="email" required placeholder="emaili yt">
          <button class="btn" type="submit">Më njofto</button></span>
          <small id="alert-msg" role="status">Të shkruajmë vetëm kur bie çmimi. Çdo email ka një link për t’i ndaluar.</small>
        </form>` : ""}
        ${multiShop || (it.history || []).length > 1 ? (() => { const v = priceVerdict(it.history || [], lo);
          return `<div class="verdict ${v.kind}"><p>${v.text}</p>${priceChart(it.history || [], it.currency)}</div>`; })() : ""}
        ${multiShop && it.size_note === 2 ? `<p class="size-warn">Te emrat e produktit në këto dyqane nuk e gjetëm madhësinë.
          I krahasuam sepse emri është i njëjtë dhe çmimet janë brenda 25% të njëri-tjetrit. Kontrollo madhësinë te dyqani para se të blesh.</p>` : ""}
        ${unconfirmed ? `<h2 class="sub">Edhe këto dyqane e kanë</h2>
          <p class="note">Madhësinë te këto dyqane nuk e lexuam dot, ndaj nuk i krahasojmë dhe nuk i numërojmë te më i liri. Mund të jetë ${it.size ? esc(it.size) : "e njëjta madhësi"}: kontrolloje te dyqani.</p>
          <table class="offers unconfirmed"><tbody>${unconfirmed}</tbody></table>` : ""}
        ${unitValue(it)}
        <p class="note">${multiShop
          ? "Krahasojmë vetëm të njëjtin produkt: i njëjti emër, e njëjta markë dhe e njëjta madhësi. Emri i saktë te çdo dyqan është poshtë çmimit, që ta kontrollosh vetë."
          : "Këtë produkt e gjetëm vetëm në këtë dyqan. Më poshtë ke produkte të ngjashme nga dyqane të tjera."}
          ${it.tracked_since ? ` Çmimet i kontrollojmë çdo ditë që nga ${dateSq(it.tracked_since + "T12:00:00")}.` : ""}
          <button type="button" class="linkish" id="report-open">Raporto gabim</button></p>
      </div>
    </div>
    ${it.dupes && it.dupes.length ? `<section class="section apart"><h2>dupe: një produkt tjetër, më i lirë</h2>
      <p class="lead">Këto nuk janë i njëjti produkt dhe nuk hyjnë te krahasimi i çmimeve më sipër. ${esc(DUPE_WHY[it.dupes[0].kind] || "")} Kontrollo përbërësit dhe madhësinë te dyqani.</p>
      <div class="dps">${it.dupes.map((r) => dupePair(r, { showOrig: false })).join("")}</div></section>` : ""}
    ${it.dupe_of && it.dupe_of.length ? `<section class="section apart"><h2>alternativë më e lirë e</h2>
      <p class="lead">Ky produkt kushton më pak se origjinali. ${esc(DUPE_WHY[it.dupe_of[0].kind] || "")}</p>
      <div class="dps">${it.dupe_of.map((r) => dupePair(r)).join("")}</div></section>` : ""}
    ${(it.other_sizes || []).length ? `<section class="section"><h2>i njëjti produkt, madhësi tjetër</h2><p class="lead">I njëjti emër, por madhësi tjetër, ose madhësi që nuk e lexuam dot. Nuk krahasohen me çmimet më sipër.</p>
      <div class="grid">${it.other_sizes.map(tile).join("")}</div></section>` : ""}
    ${it.similar.length ? `<section class="section apart"><h2>produkte të ngjashme</h2><p class="lead">Emër i ngjashëm: nuk e konfirmojmë që është i njëjti produkt. Nga dyqane të tjera, më të lirat së pari.</p>
      <div class="grid">${it.similar.map(tile).join("")}</div></section>` : ""}
  </div>`;
  if (cheap && multiShop) {  // phones: the cheapest offer stays in reach while scrolling
    const bar = document.createElement("div");
    bar.className = "buybar";
    bar.innerHTML = `<span><small>Më i liri te ${esc(shopName(cheap.shop))}</small><b class="num">${lek(lo, it.currency)}</b></span>
      ${shopLink(cheap, it.id, "produkt", "btn", "Hape në dyqan")}`;
    main.append(bar);
    // the card with the cheapest shop says the same: the bar comes once the card has scrolled away
    const card = main.querySelector(".best-card");
    if (card && "IntersectionObserver" in window) {
      bar.classList.add("wait");
      new IntersectionObserver(([e]) => bar.classList.toggle("wait", e.isIntersecting || e.boundingClientRect.top > 0)).observe(card);
    }
  }
  const bb = document.getElementById("basket-add");
  const blabel = () => { bb.textContent = inBasket(it.id) ? "Në shportë ✓" : "Shto në shportë"; bb.setAttribute("aria-pressed", inBasket(it.id)); };
  blabel();
  bb.onclick = () => { basketToggle(it.id); blabel(); };
  document.getElementById("report-open").onclick = () => reportDialog(it);
  wireChart(main);
  const btn = document.getElementById("watch");
  const label = () => { btn.textContent = watching(it.id) ? "E ndjek ✓ (hiqe)" : "Ndiq çmimin"; btn.setAttribute("aria-pressed", watching(it.id)); };
  label();
  btn.onclick = () => { const on = watchToggle(it); watchNow = null; label(); if (on) offerPush(btn); };
  if (location.hash === "#ndiq" && !watching(it.id)) {  // "Ndiq çmimin" from the browser extension
    watchToggle(it); watchNow = null; label();
    history.replaceState(history.state, "", location.pathname);
  }
  const share = document.getElementById("share-item");
  share.onclick = async () => {
    const url = `https://shporta.app/produkt/${encodeURIComponent(it.id)}`;
    const cheap = (it.offers || []).filter((o) => o.in_stock).sort((a, b) => a.price - b.price)[0];
    const text = cheap ? `${it.title}: nga ${lek(cheap.price, cheap.currency)} te ${shopName(cheap.shop)}` : it.title;
    if (navigator.share) return navigator.share({ title: it.title, text, url }).catch(() => {});
    try { await navigator.clipboard.writeText(url); share.textContent = "Linku u kopjua ✓"; }
    catch { share.textContent = "Kopjo linkun nga shiriti i adresës"; }
    setTimeout(() => { share.textContent = "Ndaj"; }, 2500);
  };
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

// right after "Ndiq çmimin": once, ask whether to send a notification when the price drops (the browser asks only on a tap)
async function offerPush(btn) {
  if (!pushReady() || Notification.permission !== "default" || document.getElementById("push-offer")) return;
  if (await pushSub().catch(() => null)) return;
  btn.closest("p").insertAdjacentHTML("afterend", `<p class="push-hint" id="push-offer">Të njoftojmë në telefon kur bie çmimi?
    <button type="button" class="btn btn-ghost" id="push-offer-on">Aktivizo njoftimet</button></p>`);
  document.getElementById("push-offer-on").onclick = async (e) => {
    e.target.disabled = true;
    const box = document.getElementById("push-offer");
    try { await pushOn(); box.textContent = "Njoftimet janë aktive. Do të të njoftojmë kur bie çmimi."; }
    catch (x) { box.textContent = x.message; }
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
        <span><span class="name">${esc(nice(w.title, w.size))}${w.size ? ` <small>${esc(w.size)}</small>` : ""}</span>
        <span class="num">${n ? `${n.shops > 1 ? "nga " : ""}${lek(n.min_price, n.currency)}` : ""}</span>${change}</span></a>
      <button type="button" class="btn btn-ghost" data-unwatch="${esc(w.id)}">Hiqe</button></li>`;
  };
  const drops = l.filter(dropped);
  main.innerHTML = `<div class="wrap">
    <div class="page-head"><h1>produktet që ndjek</h1>
      <p>${l.length ? `${plural(l.length, "produkt", "produkte")}${drops.length ? `, ${drops.length} me çmim më të ulët se kur e ruajte` : ""}.` : ""}
        Lista ruhet vetëm në këtë shfletues: nuk ka llogari dhe ne nuk e shohim. Krahasojmë çmimin më të lirë në stok sot me atë të ditës kur e ruajte.</p></div>
    ${l.length ? `<ul class="watchlist">${[...drops, ...l.filter((w) => !dropped(w))].map(row).join("")}</ul>${savingsBox()}`
      : `<div class="empty"><b>Nuk ndjek asnjë produkt ende.</b>Hap një produkt dhe shtyp "Ndiq çmimin". Kur i bie çmimi, të njoftojmë.</div>${await startHere()}`}
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
      <div class="deals" id="biggest"></div></section>
    <section class="section"><h2>si e llogaritëm</h2>
      <p class="note">Vetëm produkte të njëjta (marka, emri dhe madhësia), në stok në 3 ose më shumë dyqane, me çmim në lek. Për çdo dyqan merret çmimi i tij më i ulët për atë produkt.
        Diferencat mbi 70% lihen jashtë, sepse zakonisht janë dy produkte të ndryshme. Mund ta citosh këtë raport me link te shporta.app/raport dhe datën.
        Çdo muaj ruajmë një kopje me të dhënat e ditës së fundit të muajit.</p></section>
    ${others.length ? `<section class="section"><h2>raportet e muajve</h2><p class="cats">${others.map((m) =>
      `<a href="/raport/${m}" data-link>${esc(monthSq(m))}</a>`).join("")}</p></section>` : ""}
  </div>`;
  growList(document.getElementById("biggest"), { items: r.biggest, render: deal, total: r.biggest.length, step: 8 });
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
    <div class="page-head"><h1>${esc(term)}</h1><p>${d.corrected ? `Treguam rezultatet për <b>${esc(d.corrected)}</b>. ` : ""}${plural(d.total, "produkt", "produkte")}. Më të përshtatshmit dalin të parët.</p></div>
    <div style="height:22px"></div>
    ${d.items.length ? `<div class="grid" id="list"></div>`
      : `<div class="empty"><b>Nuk gjetëm "${esc(term)}".</b>Provo një fjalë më të shkurtër, emrin e markës, ose shkruaje pa ë dhe ç.</div>`}
  </div>`;
  growList(document.getElementById("list"), { items: d.items, render: tile, total: d.total, page: d.page,
    next: (p) => { const n = new URLSearchParams(q); n.set("page", p); return api(`/api/search?${n}`); } });
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
    ${d.items.length ? `<div class="dps" id="list"></div>`
      : `<div class="empty"><b>Asnjë dupe këtu ende.</b>Provo një kategori tjetër.</div>`}
  </div>`;
  growList(document.getElementById("list"), { items: d.items, total: d.total, page: d.page, step: 6,
    noun: ["produkt i shtrenjtë", "produkte të shtrenjta"],
    render: (r) => dupePair(r) + (r.count > 1
      ? `<a class="dp-more" href="/produkt/${esc(r.orig_id)}" data-link>Edhe ${r.count - 1} dupe të tjera për këtë produkt</a>` : ""),
    next: (p) => { const n = new URLSearchParams(q); n.set("page", p); return api(`/api/dupes?${n}`); } });
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
    const sameRow = (o) => `<tr><td><b>${esc(shopName(o.shop))}</b><span class="t">${esc(o.size ? `madhësia: ${o.size}` : "madhësinë kontrolloje te dyqani")}</span>${o.in_stock ? "" : `<span class="t">s'ka gjendje tani</span>`}</td>
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
          ${exact.length && r.query.size_assumed ? " Madhësinë te kjo faqe nuk e lexuam dot: e krahasuam sipas çmimit, kontrolloje te dyqani." : ""}</p></div>
      ${exact.length ? block("i njëjti produkt", exact.slice(0, 12).map((o) => offerRow(o, false)).join("")) : ""}
      ${same.length ? block(exact.length ? "edhe këto dyqane e kanë, në madhësi tjetër ose me madhësi që nuk e lexuam dot" : "i njëjti produkt, madhësia nuk konfirmohet",
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
    <h2>Shporta ime</h2>
    <p>Produktet që shton në shportë ruhen vetëm në këtë shfletues. Për të llogaritur ku t'i blesh, shfletuesi na kërkon vetëm çmimet e sotme për ato produkte.</p>
    <h2>Çmimet që ndan me shtesën</h2>
    <p>Disa dyqane nuk e lejojnë leximin automatik. Nëse në shtesë zgjedh "Ndaj çmimet", kur hap një produkt te një nga këto dyqane
      ruajmë atë që faqja publikon për produktin: emrin, çmimin, barkodin, foton, gjendjen dhe adresën e produktit, me të njëjtin kod ditor
      si te statistikat (pa adresë IP, pa cookie, pa emër). Në shportë ky çmim shfaqet me datën dhe me shënimin që e ndau një përdorues.
      E çaktivizon kur të duash te butoni i shtesës.</p>
    <h2>Kërkesat e dyqaneve</h2>
    <p>Kur një dyqan na shkruan te "Për dyqanet", ruajmë atë që shkruan në formular për t'iu përgjigjur, dhe asgjë tjetër.</p>
    <h2>Raportimet e gabimeve</h2>
    <p>Kur raporton një gabim, ruajmë produktin, dyqanin, arsyen, shënimin tënd dhe të njëjtin kod ditor si te statistikat (pa adresë, pa cookie).</p>
    <h2>Kursimet e mia</h2>
    <p>Kur kalon nga shporta te një dyqan, ky shfletues shënon produktin, çmimin dhe sa më pak kërkon ai dyqan se më i shtrenjti,
      që te "Lista ime" të shohësh kursimin e mundshëm. Ruhet vetëm në shfletuesin tënd (localStorage) dhe nuk na dërgohet kurrë.</p>
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
    <h2>Njoftimet në telefon dhe kompjuter</h2>
    <p>Nëse aktivizon njoftimet, shfletuesi yt na jep një adresë njoftimesh (një adresë e rastësishme te Google, Mozilla, Apple ose Microsoft,
      pa emër dhe pa email). Ruajmë vetëm atë adresë, produktet që ndjek dhe çmimin e tyre, që të të njoftojmë një herë në ditë kur bie çmimi.
      Mesazhi është i enkriptuar: vetëm shfletuesi yt e lexon. Kur i çaktivizon te "Njoftimet", adresa dhe lista fshihen te ne.
      Njoftimet e shfaqura brenda shportës ruhen vetëm në këtë shfletues.</p>
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
  dismiss(document.getElementById("consent"));
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
  const [r, d] = await Promise.all([fetch("/pages/rreth.html"), homeCache || api("/api/home")]);
  if (!r.ok) throw new Error("Faqja nuk u ngarkua.");
  homeCache = d;
  document.title = "Si funksionon shporta: krahasimi i çmimeve në Shqipëri | shporta";
  const src = document.createElement("div");
  src.innerHTML = await r.text();
  const faq = [...src.querySelectorAll(".faq h3")].map((h) => [h.textContent, h.nextElementSibling ? h.nextElementSibling.innerHTML : ""]);
  // the example: a real product sold by many shops today, and its real prices
  const it = (d.featured || []).find((f) => (f.offers || []).filter((o) => o.in_stock).length >= 4) || (d.featured || [])[0];
  const offers = it ? (it.offers || []).filter((o) => o.in_stock).sort((a, b) => a.price - b.price) : [];
  const lo = offers[0], hi = offers[offers.length - 1];
  const name = it ? nice(it.title, it.size) : "CeraVe Moisturizing Cream";
  const shown = offers.slice(0, 4);
  const max = shown.length ? Math.max(...shown.map((o) => o.price)) : 1;
  const steps = [
    ["Kërko ose skano", "Shkruaj emrin e produktit, skano barkodin me kamerë, ose ngjit linkun nga një dyqan.",
      `<div class="tv-search"><span class="tv-type">${esc(name)}</span></div>
       <div class="tv-chips"><span>${MI('<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><path d="M8 8v8M11 8v8M14 8v8M17 8v8"/>')}Skano</span>
       <span>${MI('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>')}Ngjit linkun</span></div>`],
    ["I njëjti produkt, në çdo dyqan", `Gjejmë të njëjtin produkt, në të njëjtën madhësi${it && it.size ? ` (${esc(it.size)})` : ""}, te të gjitha dyqanet që e shesin sot.`,
      `<div class="tv-prod">${it && it.image ? `<img src="${esc(it.image)}" alt="">` : ""}<b>${esc(name)}</b></div>
       <ul class="tv-offers">${shown.map((o, i) => `<li class="${i ? "" : "best"}"><span>${esc(shopName(o.shop))}</span><i style="--w:${Math.round(35 + 65 * (o.price - shown[0].price) / Math.max(1, max - shown[0].price))}%"></i><b>${lek(o.price, o.currency)}</b></li>`).join("")}</ul>`],
    ["Shiko sa kursen", "Më i liri del i pari. Të themi sa paguan më shumë te dyqani më i shtrenjtë, për të njëjtën gjë.",
      lo && hi && hi.price > lo.price ? `<div class="tv-save"><small>Kursen</small><b>${lek(hi.price - lo.price, lo.currency)}</b>
       <span>te ${esc(shopName(lo.shop))} në vend të ${esc(shopName(hi.shop))}</span></div>` : `<div class="tv-save"><b>−23%</b><span>mesatarisht, për të njëjtin produkt</span></div>`],
    ["Ndiq çmimin", "Shtyp \"Ndiq çmimin\" dhe të njoftojmë në telefon ose me email kur bie. Pa llogari. (Njoftimi më lart është shembull.)",
      `<div class="tv-note">${MI('<path d="M6 9a6 6 0 0 1 12 0c0 4.5 1.6 6.3 2.4 7H3.6C4.4 15.3 6 13.5 6 9z"/><path d="M10 19.5a2.2 2.2 0 0 0 4 0"/>')}
       <div><b>Ra çmimi</b><span>${esc(name)}</span><span>${lo ? `tani <em>${lek(lo.price, lo.currency)}</em> te ${esc(shopName(lo.shop))}` : ""}</span></div></div>`],
    ["Bli te dyqani", "shporta nuk shet asgjë. Një prekje dhe je te faqja e dyqanit, me çmimin që pe.",
      `<div class="tv-buy"><span>Më i liri sot</span><b>${lo ? esc(shopName(lo.shop)) : "dyqani"}</b><em>${lo ? lek(lo.price, lo.currency) : ""}</em>
       <span class="tv-btn">Hape në dyqan</span></div>`],
  ];
  main.innerHTML = `<div class="tour">
    <div class="wrap"><div class="page-head"><h1>si funksionon shporta</h1><p>Pesë hapa. Rrëshqit për t'i parë.</p></div></div>
    <div class="tour-track" id="tour" tabindex="0" aria-label="Si funksionon, hap pas hapi">${steps.map(([t, p, vis], i) =>
      `<article class="tour-card" aria-label="Hapi ${i + 1} nga ${steps.length}">
        <div class="tour-vis">${vis}</div>
        <div class="tour-txt"><span class="tour-n">${i + 1}/${steps.length}</span><h2>${t}</h2><p>${p}</p></div></article>`).join("")}
      <article class="tour-card tour-end" aria-label="Fillo">
        <div class="tour-txt"><h2>Gati?</h2><p>${plural(d.stats.compared, "produkt", "produkte")} te ${d.stats.shops} dyqane, çmimet e sotme.</p>
          <a class="btn" href="/" data-link>Fillo të krahasosh</a>
          <a class="btn btn-ghost" href="#" data-install>Shkarko aplikacionin</a></div></article>
    </div>
    <div class="wrap tour-nav"><button type="button" class="tour-arrow" id="tour-prev" aria-label="Hapi i mëparshëm">${MI('<path d="M15 5l-7 7 7 7"/>')}</button>
      <div class="tour-dots">${[...steps, 0].map((_, i) => `<button type="button" aria-label="Hapi ${i + 1}" data-i="${i}"></button>`).join("")}</div>
      <button type="button" class="tour-arrow next" id="tour-next">Tjetri ${MI('<path d="M9 5l7 7-7 7"/>')}</button></div>
    <div class="wrap faq-list"><h2>Pyetje të shpeshta</h2>
      ${faq.map(([q, a]) => `<details><summary>${esc(q)}</summary><div>${a}</div></details>`).join("")}</div>
  </div>`;
  const track = document.getElementById("tour"), cards = [...track.children];
  const dots = [...document.querySelectorAll(".tour-dots button")];
  const next = document.getElementById("tour-next"), prev = document.getElementById("tour-prev");
  let at = 0;
  const show = (i) => cards[Math.max(0, Math.min(cards.length - 1, i))].scrollIntoView({ behavior: calm() ? "auto" : "smooth", block: "nearest", inline: "start" });
  const mark = (i) => {
    at = i;
    dots.forEach((b, j) => b.toggleAttribute("aria-current", j === i));
    prev.disabled = i === 0;
    next.hidden = i === cards.length - 1;
    cards.forEach((c, j) => c.classList.toggle("on", j === i));
  };
  const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && mark(cards.indexOf(e.target))), { root: track, threshold: 0.6 });
  cards.forEach((c) => io.observe(c));
  next.onclick = () => show(at + 1);
  prev.onclick = () => show(at - 1);
  dots.forEach((b) => (b.onclick = () => show(Number(b.dataset.i))));
  track.addEventListener("keydown", (e) => { if (e.key === "ArrowRight") { e.preventDefault(); show(at + 1); } if (e.key === "ArrowLeft") { e.preventDefault(); show(at - 1); } });
  mark(0);
}

/* ---------- /per-dyqanet: for shops. Their position against the others (free, instant), then what they can ask ---------- */
const BIZ_WANTS = [["listim", "Shtoni dyqanin tim në shporta"], ["katalog", "Kam një katalog produktesh (link)"],
  ["raport", "Dua raportin mujor të çmimeve"], ["hiqe", "Hiqni dyqanin tim nga shporta"], ["tjeter", "Diçka tjetër"]];
function pageForShops(params) {
  const q = new URLSearchParams(params);
  document.title = "Për dyqanet: si krahasohen çmimet tuaja | shporta";
  main.innerHTML = `<div class="wrap biz">
    <div class="page-head"><h1>për dyqanet</h1>
      <p>Klientët tuaj i krahasojnë çmimet para se të blejnë. shporta u tregon ku e gjejnë të njëjtin produkt, në të njëjtën madhësi, dhe çdo klikim shkon drejt e te faqja e dyqanit. Falas.</p></div>
    <section class="biz-sec">
      <h2>Si krahasohen çmimet tuaja?</h2>
      <form class="alert-form" id="biz-check">
        <label for="biz-d">Adresa e dyqanit tuaj</label>
        <span><input id="biz-d" name="d" placeholder="dyqani.al" autocomplete="url" autocapitalize="none" spellcheck="false" required>
        <button class="btn" type="submit">Shiko</button></span>
        <small>Pa regjistrim. Janë të njëjtat çmime që sheh çdokush te shporta, të mbledhura për dyqanin tuaj.</small>
      </form>
      <div id="biz-out" aria-live="polite"></div>
    </section>
    <section class="biz-sec">
      <h2>Çfarë mund të bëni</h2>
      <dl class="biz-ways">
        <div><dt>Listim falas</dt><dd>Dyqanet në WooCommerce dhe Shopify i lexojmë vetë. Për të tjerët mjafton një link katalogu
          (Google Merchant, Facebook, XML ose CSV). Listimi është dhe mbetet falas.</dd></div>
        <div><dt>Raporti mujor i çmimeve</dt><dd>Çdo muaj: produktet ku jeni më i liri dhe ku më i shtrenjti, sa larg jeni nga konkurrenca,
          çfarë shesin të tjerët që ju nuk e keni, dhe sa vizitorë ju dërguam. Falas për 3 muajt e parë.</dd></div>
        <div><dt>Çmim i gabuar?</dt><dd>Na shkruani dhe e rregullojmë në përditësimin e radhës.</dd></div>
        <div><dt>Heqje nga shporta</dt><dd>Nëse nuk doni të jeni në shporta, ju heqim brenda 48 orësh, pasi të konfirmojmë që kërkesa vjen nga dyqani.</dd></div>
      </dl>
    </section>
    <section class="biz-sec">
      <h2>Rregullat tona</h2>
      <ul class="biz-rules">
        <li>Renditja bëhet gjithmonë sipas çmimit, vetëm për të njëjtin produkt në të njëjtën madhësi. Nuk shitet.</li>
        <li>Nëse një ditë do të ketë vend të paguar, do të shkruhet qartë "Sponsorizuar" dhe nuk do të ndryshojë renditjen.</li>
        <li>Lexojmë vetëm emrin, çmimin, foton, gjendjen dhe linkun publik të produktit, një herë në ditë, një faqe në çast
          dhe me ritmin që kërkon robots.txt juaj. Te refuzimi i parë ndalojmë.</li>
        <li>Boti ynë quhet <code>shportaBot</code> dhe ju sjell këtu. Nëse e ndaloni, e respektojmë. Mund të shfaqim akoma
          çmimin që një blerës e ka parë vetë në faqen tuaj dhe na e ka ndarë, gjithmonë me datën dhe me shënimin që e ndau një përdorues.</li>
        <li>Linku drejt jush mban <code>utm_source=shporta</code>, që t'i shihni vizitat tona në statistikat tuaja.</li>
      </ul>
    </section>
    <section class="biz-sec" id="kerkese">
      <h2>Na shkruani</h2>
      <form class="biz-form" id="biz-form" novalidate>
        <label>Emri i dyqanit<input name="shop" autocomplete="organization" maxlength="120"></label>
        <label>Adresa e dyqanit<input name="site" placeholder="dyqani.al" autocapitalize="none" spellcheck="false" required></label>
        <label>Email<input name="email" type="email" autocomplete="email" required></label>
        <label>Telefon <small>(nuk është e detyrueshme)</small><input name="phone" type="tel" autocomplete="tel" maxlength="40"></label>
        <fieldset><legend>Çfarë dëshironi?</legend>
          ${BIZ_WANTS.map(([v, t]) => `<label class="check"><input type="checkbox" name="wants" value="${v}"> ${t}</label>`).join("")}</fieldset>
        <label>Linku i katalogut <small>(nëse keni)</small><input name="feed" type="url" placeholder="https://…" maxlength="500"></label>
        <label>Mesazh <small>(nuk është e detyrueshme)</small><textarea name="note" rows="3" maxlength="1000"></textarea></label>
        <button class="btn" type="submit">Dërgo</button>
        <small id="biz-msg" role="status">Ju përgjigjemi me email brenda 2 ditësh pune. Emailin e përdorim vetëm për këtë kërkesë.</small>
      </form>
    </section>
  </div>`;
  const out = document.getElementById("biz-out"), form = document.getElementById("biz-form");
  const fill = (d, want) => {
    form.site.value = d;
    form.querySelectorAll('[name="wants"]').forEach((c) => { if (c.value === want) c.checked = true; });
  };
  const nf = (n) => Number(n).toLocaleString("en").replace(/,/g, " ");
  async function check(d) {
    out.innerHTML = `<p class="note">Duke llogaritur…</p>`;
    let r;
    try { r = await api(`/api/dyqan?d=${encodeURIComponent(d)}`); }
    catch (e) { out.innerHTML = `<p class="size-warn">${esc(e.message || "Nuk u llogarit. Provo përsëri.")}</p>`; return; }
    if (!r.listed) {
      out.innerHTML = `<div class="biz-out"><p><b>${esc(r.domain)}</b> nuk është ende në shporta, ku krahasojmë ${nf(r.shops)} dyqane.
        Shtojeni falas: e lexojmë vetë nëse dyqani është në WooCommerce ose Shopify, përndryshe mjafton linku i katalogut.</p>
        <p><a class="btn" href="#kerkese" id="biz-go">Shtoni dyqanin falas</a></p></div>`;
      document.getElementById("biz-go").onclick = () => fill(r.domain, "listim");
      return;
    }
    const ex = r.examples.map((x) => `<li><a href="/produkt/${esc(x.item)}" data-link>${esc(x.title)}</a>
      <span>ju ${lek(x.price, "ALL")}, më i liri ${lek(x.lowest, "ALL")}</span></li>`).join("");
    out.innerHTML = `<div class="biz-out">
      <p><b>${nf(r.compared)}</b> produkte të ${esc(r.domain)} krahasohen sot me të njëjtin produkt në dyqane të tjera.</p>
      <dl class="biz-nums">
        <div><dt>Ku jeni më i liri</dt><dd>${nf(r.cheapest)}</dd></div>
        <div><dt>Ku jeni më i shtrenjti</dt><dd>${nf(r.dearest)}</dd></div>
        <div><dt>Mbi më të lirin, mesatarisht</dt><dd>${r.above_pct}%</dd></div>
        ${r.clicks30 ? `<div><dt>Vizitorë që ju dërguam, 30 ditë</dt><dd>${nf(r.clicks30)}</dd></div>` : ""}
      </dl>
      ${ex ? `<h3>Ku jeni më larg nga çmimi më i ulët</h3><ul class="biz-ex">${ex}</ul>` : ""}
      <p><a class="btn" href="#kerkese" id="biz-go">Merrni raportin e plotë falas</a></p></div>`;
    document.getElementById("biz-go").onclick = () => fill(r.domain, "raport");
  }
  document.getElementById("biz-check").onsubmit = (e) => {
    e.preventDefault();
    const d = e.target.d.value.trim();
    if (d) { history.replaceState(null, "", `/per-dyqanet?d=${encodeURIComponent(d)}`); check(d); }
  };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const msg = document.getElementById("biz-msg"), f = new FormData(form);
    const body = Object.fromEntries([...f.entries()].filter(([k]) => k !== "wants"));
    body.wants = f.getAll("wants");
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      const r = await fetch("/api/dyqan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const d = await r.json();
      msg.textContent = d.message || d.error;
      msg.classList.toggle("bad", !r.ok);
      if (r.ok) form.reset();
    } catch { msg.textContent = "Nuk u dërgua. Provo përsëri."; msg.classList.add("bad"); }
    btn.disabled = false;
  };
  if (q.get("d")) { document.getElementById("biz-d").value = q.get("d"); check(q.get("d")); }
}

/* ---------- "Shporta ime": several products, the cheapest way to buy them all ---------- */
// Kept in this browser only. The optimizer is plain arithmetic on today's prices: every product at its cheapest
// shop, everything at one shop, or split between two shops. Delivery costs are not in our data, so we say so.
const BASKET_KEY = "shporta-basket";
const basketList = () => { try { return JSON.parse(localStorage.getItem(BASKET_KEY)) || []; } catch { return []; } };
const basketSave = (l) => { try { localStorage.setItem(BASKET_KEY, JSON.stringify(l.slice(0, 40))); } catch {} basketBadge(); };
const inBasket = (id) => basketList().some((b) => b.id === id);
function basketToggle(id) {
  const l = basketList();
  basketSave(l.some((b) => b.id === id) ? l.filter((b) => b.id !== id) : [...l, { id, qty: 1 }]);
  return inBasket(id);
}
function basketBadge() {
  const a = document.getElementById("nav-basket");
  if (!a) return;
  const n = basketList().reduce((t, b) => t + b.qty, 0);
  const more = basketBadge.n !== undefined && n > basketBadge.n;
  basketBadge.n = n;
  a.querySelector("span").textContent = n ? n : "";
  a.classList.toggle("has", n > 0);
  const t = document.querySelector(".tab-basket b");
  if (t) t.textContent = n ? n : "";
  if (more && !calm()) [a.querySelector("span"), t].forEach((b) => b && b.animate &&
    b.animate([{ transform: "scale(1)" }, { transform: "scale(1.35)" }, { transform: "scale(1)" }], { duration: 320, easing: EASE_OUT }));
}

// items: [{id, title, qty, offers: [{shop, price}]}] -> the plans worth showing, cheapest first
function basketPlans(items) {
  const avail = items.filter((i) => i.offers && i.offers.length);
  if (!avail.length) return null;
  const shops = [...new Set(avail.flatMap((i) => i.offers.map((o) => o.shop)))];
  const priceAt = (it, shop) => (it.offers.find((o) => o.shop === shop) || {}).price;
  const plan = (pick) => {  // pick(item) -> offer or null
    const lines = avail.map((it) => ({ it, o: pick(it) }));
    const got = lines.filter((l) => l.o);
    return { lines, total: got.reduce((t, l) => t + l.o.price * l.it.qty, 0), missing: lines.filter((l) => !l.o).map((l) => l.it),
             shops: [...new Set(got.map((l) => l.o.shop))] };
  };
  const cheapest = plan((it) => it.offers[0]);
  const dearest = avail.reduce((t, it) => t + Math.max(...it.offers.map((o) => o.price)) * it.qty, 0);
  // one shop: the shop that has the most of them, then the lowest total
  let one = null;
  for (const s of shops) {
    const p = plan((it) => it.offers.find((o) => o.shop === s) || null);
    if (!one || p.missing.length < one.missing.length || (p.missing.length === one.missing.length && p.total < one.total)) one = p;
  }
  // two shops: every pair, each product at the cheaper of the two
  let two = null;
  if (shops.length <= 60) {
    for (let a = 0; a < shops.length; a++) for (let b = a + 1; b < shops.length; b++) {
      const p = plan((it) => {
        const x = priceAt(it, shops[a]), y = priceAt(it, shops[b]);
        if (x == null && y == null) return null;
        return y == null || (x != null && x <= y) ? { shop: shops[a], price: x } : { shop: shops[b], price: y };
      });
      if (!two || p.missing.length < two.missing.length || (p.missing.length === two.missing.length && p.total < two.total)) two = p;
    }
  }
  return { cheapest, one, two: two && two.shops.length === 2 ? two : null, dearest, count: avail.length };
}

async function pageBasket() {
  document.title = "Shporta ime | shporta";
  const l = basketList();
  if (!l.length) {
    main.innerHTML = `<div class="wrap"><div class="page-head"><h1>shporta ime</h1>
      <p>Shto disa produkte dhe shporta llogarit ku t'i blesh që të paguash më pak: të gjitha te një dyqan, të ndara në dy dyqane, ose secilin te më i liri.</p></div>
      <div class="empty"><b>Shporta është bosh.</b>Hap një produkt dhe shtyp "Shto në shportë".</div>${await startHere()}</div>`;
    return;
  }
  const d = await api(`/api/basket?ids=${l.map((b) => encodeURIComponent(b.id)).join(",")}`);
  const qty = Object.fromEntries(l.map((b) => [b.id, b.qty]));
  const items = d.items.map((i) => ({ ...i, qty: qty[i.id] || 1 }));
  const plans = basketPlans(items);
  const planBox = (p, title, note, cls = "") => !p ? "" : `<div class="plan ${cls}">
      <div class="plan-head"><h3>${title}</h3><b class="num">${lek(p.total)}</b></div>
      <p class="note">${note}${p.missing.length ? ` Mungon: ${p.missing.map((m) => esc(m.title)).join(", ")}.` : ""}</p>
      <ul>${p.lines.filter((x) => x.o).map((x) => `<li><span>${esc(nice(x.it.title, x.it.size))}${x.it.qty > 1 ? ` × ${x.it.qty}` : ""}</span>
        <span class="plan-shop">${esc(shopName(x.o.shop))}</span><span class="num">${lek(x.o.price * x.it.qty)}</span></li>`).join("")}</ul>
    </div>`;
  const best = plans && plans.cheapest;
  main.innerHTML = `<div class="wrap basket">
    <div class="page-head"><h1>shporta ime</h1>
      <p>${plural(items.length, "produkt", "produkte")}. Çmimet e sotme në stok, vetëm i njëjti produkt në të njëjtën madhësi.</p></div>
    ${plans ? `<section class="basket-sum">
      <div><small>Po t'i blesh te dyqanet më të shtrenjta</small><s class="num">${lek(plans.dearest)}</s></div>
      <div class="win"><small>Me shportën paguan</small><b class="num">${lek(best.total)}</b></div>
      <div><small>Kursen</small><b class="num save">${lek(plans.dearest - best.total)}</b></div>
    </section>
    <div class="plans">
      ${planBox(plans.cheapest, "Secili te dyqani më i lirë", `${plural(plans.cheapest.shops.length, "dyqan", "dyqane")}: çmimi më i ulët për çdo produkt.`, "best")}
      ${plans.two && plans.two.shops.length < plans.cheapest.shops.length ? planBox(plans.two, "Vetëm dy dyqane",
        `${esc(plans.two.shops.map(shopName).join(" dhe "))}: më pak porosi, ${lek(plans.two.total - best.total)} më shumë se më i liri.`) : ""}
      ${plans.one && plans.cheapest.shops.length > 1 ? planBox(plans.one, plans.one.missing.length
          ? `${plans.count - plans.one.missing.length} nga ${plans.count} te ${esc(shopName(plans.one.shops[0] || ""))}`
          : `Gjithçka te ${esc(shopName(plans.one.shops[0] || ""))}`,
        `Një porosi e vetme${plans.one.missing.length ? "" : `, ${lek(plans.one.total - best.total)} më shumë se më i liri`}.`) : ""}
    </div>
    <p class="note">Pa kostot e transportit, që nuk i kemi: shumë dyqane e dërgojnë falas mbi një shumë. Kontrollo çmimin te dyqani para se të blesh.</p>` : ""}
    <h2 class="sub">produktet</h2>
    <ul class="basket-list">${items.map((it) => `<li>
      ${it.missing ? `<span>Ky produkt nuk gjendet më.</span>` : `<a href="/produkt/${esc(it.id)}" data-link>${img(it.image, it.title)}<span><b>${esc(it.title)}</b>
        ${it.size ? `<small>${esc(it.size)}</small>` : ""}<small>${it.offers.length ? `nga ${lek(it.offers[0].price)} te ${esc(shopName(it.offers[0].shop))}` : "S'ka gjendje askund sot"}</small></span></a>`}
      <span class="qty"><button type="button" data-q="-1" data-id="${esc(it.id)}" aria-label="Një më pak">−</button><b>${it.qty}</b>
        <button type="button" data-q="1" data-id="${esc(it.id)}" aria-label="Një më shumë">+</button></span>
      <button type="button" class="btn btn-ghost" data-rm="${esc(it.id)}">Hiqe</button></li>`).join("")}</ul>
  </div>`;
  main.querySelectorAll("[data-q]").forEach((b) => (b.onclick = () => {
    const l2 = basketList().map((x) => x.id === b.dataset.id ? { ...x, qty: Math.max(1, Math.min(20, x.qty + Number(b.dataset.q))) } : x);
    basketSave(l2); pageBasket();
  }));
  main.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = () => { basketSave(basketList().filter((x) => x.id !== b.dataset.rm)); pageBasket(); }));
}

/* ---------- the price over time, and whether today's is low ---------- */
// history: [[day, lowest price that day], ...] only where it changed (build_seed.item_history)
function expandDays(h) {
  const out = [];
  for (let i = 0; i < h.length; i++) {
    const end = i + 1 < h.length ? new Date(h[i + 1][0] + "T12:00:00") : new Date(h[i][0] + "T12:00:00");
    for (let d = new Date(h[i][0] + "T12:00:00"); d <= end; d.setDate(d.getDate() + 1)) {
      if (i + 1 < h.length && d.getTime() === end.getTime()) break;
      out.push([d.toISOString().slice(0, 10), h[i][1]]);
    }
  }
  return out;
}
function priceVerdict(h, now) {
  const days = expandDays(h);
  if (days.length < 14) return { kind: "early", text: `Po mbledhim historinë e çmimit: ${plural(days.length, "ditë", "ditë")} deri tani. Pas dy javësh të themi nëse çmimi i sotëm është i ulët.` };
  const prices = days.map((d) => d[1]).sort((a, b) => a - b);
  const low = prices[0], med = prices[Math.floor(prices.length / 2)];
  if (now <= low * 1.005) return { kind: "low", text: `Çmimi më i ulët që kemi parë në ${days.length} ditë. Koha e mirë për ta blerë.` };
  if (now > med * 1.05) return { kind: "high", text: `Më shtrenjtë se zakonisht: në ${days.length} ditët e fundit kushtoi zakonisht ${lek(med)}, më lirë ${lek(low)}. Mund t'ia vlejë të presësh, ose ndiqe çmimin.` };
  return { kind: "normal", text: `Çmim i zakonshëm: në ${days.length} ditët e fundit ishte ${lek(low)} deri ${lek(prices[prices.length - 1])}.` };
}
function priceChart(h, cur) {
  const days = expandDays(h);
  if (days.length < 2) return "";
  const ps = days.map((d) => d[1]), lo = Math.min(...ps), hi = Math.max(...ps), span = hi - lo || hi * 0.1 || 1;
  const W = 640, H = hi === lo ? 70 : 170, P = 26;  // a price that never moved: a short line, not a tall empty box
  const x = (i) => P + (i / (days.length - 1)) * (W - 2 * P);
  const y = (p) => H - P - ((p - lo) / span) * (H - 2 * P);
  let path = `M${x(0)},${y(ps[0])}`;
  for (let i = 1; i < ps.length; i++) path += ` H${x(i)} V${y(ps[i])}`;  // steps: a price holds until it changes
  const area = `${path} V${H - P} H${x(0)} Z`;
  return `<figure class="chart" data-days='${esc(JSON.stringify(days))}'>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Çmimi më i ulët çdo ditë, nga ${lek(lo, cur)} deri ${lek(hi, cur)}">
      <path class="area" d="${area}"/><path class="line" d="${path}"/>
      <line class="lo" x1="${P}" x2="${W - P}" y1="${y(lo)}" y2="${y(lo)}"/>
      <text x="${W - P}" y="${y(lo) - 6}" text-anchor="end">më i ulëti ${lek(lo, cur)}</text>
      <circle class="today" cx="${x(ps.length - 1)}" cy="${y(ps[ps.length - 1])}" r="5"/>
      <g class="hover" visibility="hidden"><line y1="${P / 2}" y2="${H - P}"/><circle r="4"/></g>
    </svg>
    <figcaption><span>${day(days[0][0])}</span><output></output><span>sot</span></figcaption>
  </figure>`;
}
function wireChart(root) {
  const f = root.querySelector(".chart");
  if (!f) return;
  const days = JSON.parse(f.dataset.days), svg = f.querySelector("svg"), g = svg.querySelector(".hover"), out = f.querySelector("output");
  const W = 640, P = 26;
  svg.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left) / r.width * W - P) / (W - 2 * P) * (days.length - 1));
    const k = Math.max(0, Math.min(days.length - 1, i));
    const cx = P + (k / Math.max(1, days.length - 1)) * (W - 2 * P);
    const c = svg.querySelectorAll("circle.today")[0];
    const ps = days.map((d) => d[1]), lo = Math.min(...ps), span = Math.max(...ps) - lo || Math.max(...ps) * 0.1 || 1;
    const H = Number(svg.getAttribute("viewBox").split(" ")[3]);
    const cy = H - P - ((days[k][1] - lo) / span) * (H - 2 * P);
    g.setAttribute("visibility", "visible");
    g.querySelector("line").setAttribute("x1", cx); g.querySelector("line").setAttribute("x2", cx);
    g.querySelector("circle").setAttribute("cx", cx); g.querySelector("circle").setAttribute("cy", cy);
    out.textContent = `${day(days[k][0])}: ${lek(days[k][1])}`;
    c.style.opacity = 0.35;
  });
  svg.addEventListener("pointerleave", () => { g.setAttribute("visibility", "hidden"); out.textContent = ""; svg.querySelector("circle.today").style.opacity = 1; });
}

/* ---------- which size is the better deal ---------- */
function unitValue(it) {
  const parse = (x) => { const m = /^([\d.]+)\s*(ml|g|copë)$/.exec(x.size || ""); return m ? { n: Number(m[1]), u: m[2] } : null; };
  const rows = [it, ...(it.other_sizes || [])].filter((x) => x.currency === it.currency && parse(x) && x.min_price > 0)
    .map((x) => { const s = parse(x); return { ...x, s, per: x.min_price / s.n * (s.u === "copë" ? 1 : 100) }; });
  const unit = rows.length && rows[0].s.u;
  const same = rows.filter((r) => r.s.u === unit);
  if (same.length < 2) return "";
  const best = Math.min(...same.map((r) => r.per));
  const label = unit === "copë" ? "për copë" : `për 100 ${unit}`;
  return `<section class="unit"><h2 class="sub">cila madhësi ia vlen</h2>
    <p class="note">Çmimi më i lirë i secilës madhësi, ${label}. Madhësitë e tjera nuk hyjnë te krahasimi më sipër.</p>
    <ul>${same.sort((a, b) => a.s.n - b.s.n).map((r) => `<li class="${r.per === best ? "best" : ""}">
      ${r.id === it.id ? `<b>${esc(r.size)}</b>` : `<a href="/produkt/${esc(r.id)}" data-link>${esc(r.size)}</a>`}
      <span class="num">${lek(r.min_price, r.currency)}</span>
      <span class="num per">${lek(r.per, r.currency)} ${label}</span>
      ${r.per === best ? `<span class="chip-best">ia vlen më shumë</span>` : `<span class="more">+${Math.round((r.per / best - 1) * 100)}%</span>`}</li>`).join("")}</ul></section>`;
}

/* ---------- "Raporto gabim": what visitors tell us, the matching learns from ---------- */
function reportDialog(it) {
  let d = document.getElementById("report");
  if (d) d.remove();
  d = document.createElement("dialog");
  d.id = "report";
  d.innerHTML = `<form method="dialog" class="report">
    <h2>raporto gabim</h2>
    <p class="note">Na ndihmon ta mbajmë krahasimin të saktë. Kur disa njerëz raportojnë të njëjtën gjë, e rregullojmë automatikisht.</p>
    <label>Dyqani <select name="offer"><option value="">Asnjë dyqan i veçantë</option>
      ${it.offers.map((o) => `<option value="${o.id}">${esc(shopName(o.shop))}: ${lek(o.price, o.currency)}</option>`).join("")}</select></label>
    <fieldset><legend>Çfarë nuk shkon?</legend>
      <label><input type="radio" name="kind" value="tjeter-produkt" required> Nuk është i njëjti produkt</label>
      <label><input type="radio" name="kind" value="madhesi"> Është madhësi tjetër</label>
      <label><input type="radio" name="kind" value="cmim"> Çmimi te dyqani është tjetër</label>
      <label><input type="radio" name="kind" value="tjeter"> Diçka tjetër</label></fieldset>
    <label>Shënim (pa të dhëna personale) <textarea name="note" maxlength="300" rows="2"></textarea></label>
    <p class="report-msg" role="status"></p>
    <div class="report-actions"><button type="submit" class="btn" value="send">Dërgo</button><button type="button" class="btn btn-ghost" data-close>Mbyll</button></div>
  </form>`;
  document.body.append(d);
  d.querySelector("[data-close]").onclick = () => d.close();
  d.querySelector("form").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target), msg = d.querySelector(".report-msg");
    const r = await fetch("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item: it.id, offer: f.get("offer") || null, kind: f.get("kind"), note: f.get("note") }) }).catch(() => null);
    const j = r ? await r.json().catch(() => ({})) : {};
    msg.textContent = j.message || j.error || "Nuk u lidhëm dot. Provo përsëri.";
    if (r && r.ok) setTimeout(() => d.close(), 1600);
  };
  d.showModal();
}

/* ---------- the menu: every place in shporta, one tap from anywhere (a sheet on phones, a side panel on computers) ---------- */
const MI = (d) => `<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const MENU = [
  [null, [
    ["/kategorite", "Kategoritë", MI('<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>')],
    ["/dupe", "Dupe: alternativa më të lira", MI('<path d="M8 4h8l-1 5H9z"/><path d="M9 9c-2 2-3 4-3 7a4 4 0 0 0 4 4h4a4 4 0 0 0 4-4c0-3-1-5-3-7"/>')],
    ["/raport", "Raporti i çmimeve", MI('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>')],
    ["/dyqanet", "Dyqanet", MI('<path d="M4 9l1.5-5h13L20 9M4 9h16v11H4zM9 20v-6h6v6"/>')],
  ]],
  ["Mjetet e mia", [
    ["/skano", "Skano barkodin", MI('<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><path d="M8 8v8M11 8v8M14 8v8M17 8v8"/>')],
    ["/ndaj", "Krahaso një link", MI('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>')],
    ["/shporta", "Shporta ime", MI('<path d="M3 6h2l2.2 10.2a1.5 1.5 0 0 0 1.5 1.2h8.6a1.5 1.5 0 0 0 1.5-1.2L20.5 9H6.2"/><circle cx="9.5" cy="21" r="1"/><circle cx="17" cy="21" r="1"/>'), "basket"],
    ["/lista", "Të ndjekurat", MI('<path d="M12 21s-7-4.4-9.3-9A5.2 5.2 0 0 1 12 6.5 5.2 5.2 0 0 1 21.3 12C19 16.6 12 21 12 21z"/>')],
    ["/njoftime", "Njoftimet", MI('<path d="M6 9a6 6 0 0 1 12 0c0 4.5 1.6 6.3 2.4 7H3.6C4.4 15.3 6 13.5 6 9z"/><path d="M10 19.5a2.2 2.2 0 0 0 4 0"/>'), "bell"],
  ]],
  ["shporta kudo", [
    ["#install", "Shkarko aplikacionin", MI('<rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M12 7v7M9 11l3 3 3-3"/>'), "install"],
    ["/shtesa", "Shtesa për shfletuesin", MI('<path d="M10 3h4v3a2 2 0 1 0 0 4v0h3v4h-3a2 2 0 1 0 0 4v3h-4v-3a2 2 0 1 0-4 0v3H3v-7h3a2 2 0 1 0 0-4H3V3h7z"/>')],
    ["#share", "Ndaje shportën me një mik", MI('<circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="M8.2 10.8l7.6-4.4M8.2 13.2l7.6 4.4"/>'), "share"],
  ]],
  ["Rreth shportës", [
    ["/rreth", "Si funksionon", MI('<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>')],
    ["/per-dyqanet", "Për dyqanet", MI('<path d="M3 21h18M5 21V9l7-5 7 5v12M9 21v-6h6v6"/>')],
    ["/privatesia", "Cookies dhe privatësia", MI('<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/>')],
  ]],
];
function menuDialog() {
  let d = document.getElementById("menu");
  if (d) return d;
  const row = ([href, label, icon, kind]) => {
    if (kind === "install" && isStandalone()) return "";
    if (kind === "share" && !navigator.share) return "";
    const tag = href.startsWith("#") ? `button type="button" data-menu="${kind}"` : `a href="${href}" data-link`;
    return `<li><${tag} class="menu-row">${icon}<span>${label}</span>${kind === "basket" || kind === "bell" ? `<b class="menu-count" data-count="${kind}"></b>` : ""}
      <svg class="chev" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg></${tag.split(" ")[0]}></li>`;
  };
  document.body.insertAdjacentHTML("beforeend", `<dialog class="menu" id="menu" aria-label="Menuja">
    <div class="menu-grab" aria-hidden="true"></div>
    <div class="menu-hd"><a class="brand" href="/" data-link aria-label="shporta, faqja kryesore"><img src="/assets/shporta-mark.svg" alt="" width="30" height="30"><span class="wm">shp<i></i>rta</span></a>
      <button type="button" class="menu-x" data-menu="close" aria-label="Mbyll menynë" autofocus>${MI('<path d="M6 6l12 12M18 6L6 18"/>')}</button></div>
    <nav class="menu-body" aria-label="Menuja">${MENU.map(([title, rows]) =>
      `<section>${title ? `<h2>${title}</h2>` : ""}<ul>${rows.map(row).join("")}</ul></section>`).join("")}
      <p class="menu-foot" id="menu-updated"></p></nav>
  </dialog>`);
  d = document.getElementById("menu");
  d.addEventListener("click", async (e) => {
    if (e.target === d) return closeMenu();  // the dimmed area around the sheet
    const b = e.target.closest("[data-menu]");
    if (e.target.closest("a[data-link]")) return closeMenu(true);
    if (!b) return;
    if (b.dataset.menu === "close") closeMenu();
    if (b.dataset.menu === "share") navigator.share({ title: "shporta", text: "Krahaso çmimin e të njëjtit produkt në dyqanet online të Shqipërisë", url: "https://shporta.app/?nga=ndaj" }).catch(() => {});
    if (b.dataset.menu === "install") {
      closeMenu();
      if (installPrompt) {
        installPrompt.prompt();
        const { outcome } = await installPrompt.userChoice;
        installPrompt = null;
        if (outcome !== "accepted") try { localStorage.setItem(INSTALL_KEY, String(Date.now())); } catch {}
      } else installCard(true);  // iPhone and browsers without the prompt: how to add it by hand
    }
  });
  d.addEventListener("close", () => document.getElementById("menu-open").setAttribute("aria-expanded", "false"));
  // a sheet you can pull down to close, like any phone app
  let y0 = null, dy = 0;
  d.addEventListener("touchstart", (e) => {
    const body = d.querySelector(".menu-body");
    y0 = (body.scrollTop <= 0 || !body.contains(e.target)) && matchMedia("(max-width: 719px)").matches ? e.touches[0].clientY : null; dy = 0;
  }, { passive: true });
  d.addEventListener("touchmove", (e) => {
    if (y0 === null) return;
    dy = Math.max(0, e.touches[0].clientY - y0);
    d.style.transition = "none";
    d.style.transform = `translateY(${dy}px)`;
  }, { passive: true });
  d.addEventListener("touchend", () => {
    if (y0 === null) return;
    d.style.transition = d.style.transform = "";
    if (dy > 90) closeMenu();
    y0 = null;
  });
  return d;
}
function openMenu() {
  const d = menuDialog();
  const n = basketList().reduce((t, b) => t + b.qty, 0);
  d.querySelectorAll("[data-count]").forEach((c) => {
    c.textContent = c.dataset.count === "basket" ? (n || "") : (document.querySelector("#nav-bell b")?.textContent || "");
  });
  d.querySelectorAll("a[data-link]").forEach((a) => a.toggleAttribute("aria-current",
    a.getAttribute("href") !== "/" && location.pathname.startsWith(a.getAttribute("href"))));
  d.querySelector("#menu-updated").textContent = document.getElementById("foot-updated")?.textContent || "";
  d.showModal();
  document.getElementById("menu-open").setAttribute("aria-expanded", "true");
}
function closeMenu(now = false) {
  const d = document.getElementById("menu");
  if (!d || !d.open) return;
  if (now || calm()) return d.close();  // a link: the next page appears at once, no waiting on the sheet
  d.classList.add("closing");
  setTimeout(() => { d.classList.remove("closing"); d.close(); }, 200);
}
document.getElementById("menu-open").addEventListener("click", openMenu);

/* ---------- instant suggestions while typing ---------- */
function wireSuggest(form) {
  if (form.dataset.suggest) return;
  form.dataset.suggest = "1";
  const input = form.querySelector('input[name="q"]');
  const box = document.createElement("div");
  box.className = "suggest";
  box.setAttribute("role", "listbox");
  box.id = `${input.id}-sug`;
  box.hidden = true;
  form.append(box);
  input.setAttribute("autocomplete", "off");
  input.setAttribute("aria-controls", box.id);
  input.setAttribute("aria-expanded", "false");
  let timer, active = -1, seq = 0;
  const close = () => { box.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; };
  const mark = () => box.querySelectorAll("a").forEach((a, i) => a.setAttribute("aria-selected", i === active));
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const v = input.value.trim();
    if (v.length < 3) return close();
    timer = setTimeout(async () => {
      const my = ++seq;
      const d = await api(`/api/suggest?q=${encodeURIComponent(v)}`).catch(() => null);
      if (my !== seq || !d) return;
      if (!d.items.length) return close();
      box.innerHTML = d.items.map((it) => `<a role="option" href="/produkt/${esc(it.id)}" data-link>${img(it.image, "")}
        <span><b>${esc(it.title)}</b><small>${it.shops > 1 ? `${it.shops} dyqane, ` : ""}${it.shops > 1 && it.max_price > it.min_price ? `${lek(it.min_price, it.currency)} deri ${lek(it.max_price, it.currency)}` : lek(it.min_price, it.currency)}</small></span>
        ${it.save_pct && it.in_stock_shops > 1 ? `<i>−${it.save_pct}%</i>` : ""}</a>`).join("")
        + `<a class="all" href="/kerko?q=${encodeURIComponent(v)}" data-link>Të gjitha ${plural(d.total, "rezultat", "rezultatet")}</a>`;
      box.hidden = false;
      input.setAttribute("aria-expanded", "true");
      active = -1;
    }, 140);
  });
  input.addEventListener("keydown", (e) => {
    const links = box.querySelectorAll("a");
    if (box.hidden || !links.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + links.length) % links.length;
      mark();
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      close();
      go(links[active].getAttribute("href"));
    } else if (e.key === "Escape") close();
  });
  box.addEventListener("click", close);
  document.addEventListener("click", (e) => { if (!form.contains(e.target)) close(); });
}
const wireAllSuggest = () => document.querySelectorAll("form[data-search]").forEach(wireSuggest);

/* ---------- "Skano": the phone's camera reads a barcode or a label; we show every shop's price ---------- */
// Barcodes: the browser's own BarcodeDetector where it exists (Chrome on Android), else the ZXing library (iPhone).
// Labels: Tesseract reads the text on the phone itself; the photo never leaves the device, only the words do.
const ZXING = "https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js";
const TESSERACT = "https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js";
const loadScript = (src) => new Promise((ok, fail) => {
  if (document.querySelector(`script[src="${src}"]`)) return ok();
  const s = Object.assign(document.createElement("script"), { src, onload: ok, onerror: fail, crossOrigin: "anonymous" });
  document.head.append(s);
});
let scanStop = null;  // stops the camera when leaving the page

async function pageScan() {
  document.title = "Skano një produkt | shporta";
  const icoCode = `<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><path d="M8 8v8M11 8v8M14 8v8M17 8v8"/></svg>`;
  const icoPhoto = `<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.5"/></svg>`;
  main.innerHTML = `<div class="wrap scan">
    <div class="page-head"><h1>Skano një produkt</h1>
      <p>Ke një produkt në dorë, në dyqan apo në shtëpi? Shiko sa kushton në çdo dyqan online.</p></div>
    <div class="scan-ways">
      <button type="button" class="scan-way" id="way-code">${icoCode}<span><b>Skano barkodin</b>
        <small>Vijat me numra, zakonisht pas ose poshtë paketimit.</small></span></button>
      <label class="scan-way">${icoPhoto}<span><b>Fotografo paketimin</b>
        <small>Pjesa e përparme, ku duken qartë marka dhe emri.</small></span>
        <input type="file" id="scan-file" accept="image/*" capture="environment" hidden></label>
    </div>
    <div class="scan-stage" id="scan-stage" hidden>
      <video id="scan-video" playsinline muted></video>
      <div class="scan-frame" aria-hidden="true"><i></i></div>
      <p class="scan-status" id="scan-status" role="status"></p>
      <button type="button" class="scan-close" id="scan-close" aria-label="Mbyll kamerën">✕</button>
    </div>
    <details class="scan-type"><summary>Barkodi nuk lexohet? Shkruaj numrin</summary>
      <form id="scan-code" class="scan-code"><label class="sr" for="scan-digits">Numri i barkodit</label>
        <input id="scan-digits" inputmode="numeric" autocomplete="off" pattern="[0-9 ]{8,18}" placeholder="p.sh. 3337875597388">
        <button class="btn" type="submit">Kërko</button></form></details>
    <div id="scan-result" aria-live="polite"></div>
    <p class="note">Kamera dhe fotoja përdoren vetëm në telefonin tënd: te ne vjen vetëm numri i barkodit ose fjalët e lexuara.
      Kur barkodi nuk është te dyqanet tona, emrin e produktit e marrim nga Open Beauty Facts. Tregojmë një produkt vetëm kur jemi të sigurt që është ai.</p>
  </div>`;
  const stage = document.getElementById("scan-stage"), status = document.getElementById("scan-status");
  const result = document.getElementById("scan-result");
  // what the person is waiting for comes onto the screen: the "reading…" line, then the answer
  const reveal = () => result.scrollIntoView({ behavior: calm() ? "auto" : "smooth", block: "start" });
  const busy = (text) => { result.innerHTML = `<p class="loading scan-busy">${text}</p>`; reveal(); };
  const say = (html) => { result.innerHTML = html; reveal(); };
  const photoBtn = `<label class="btn">Fotografo paketimin<input type="file" accept="image/*" capture="environment" hidden data-photo></label>`;
  // one product (or the same product in its sizes): straight to it, or the sizes to pick from. Never a guess.
  const answer = (items, head, foot = "") => {
    if (items.length === 1) return go(`/produkt/${items[0].id}`);
    say(`<h2 class="sub">${head}</h2><p class="note">Zgjidh madhësinë që ke në dorë.</p>
      <div class="grid">${items.map(tile).join("")}</div>${foot}`);
  };
  const unsure = (d) => say(`<div class="scan-unsure"><b>Nuk jemi të sigurt cili produkt është.</b>
      <p>${d.words && d.words.length ? `Lexuam: <i>${esc(d.words.join(" "))}</i>. ` : ""}Fotografo emrin nga afër, me dritë, ose kërko vetë:</p>
      <form class="scan-code" data-search><input name="q" value="${esc((d.words || []).join(" "))}" aria-label="Kërko produktin">
        <button class="btn" type="submit">Kërko</button></form></div>`);

  const byCode = async (code) => {
    busy(`Barkodi ${esc(code)}: po kërkojmë…`);
    const d = await api(`/api/barcode?code=${encodeURIComponent(code)}`).catch(() => null);
    if (!d) return say(`<div class="empty"><b>Nuk u lidhëm dot.</b>Provo përsëri.</div>`);
    if (d.valid === false) return say(`<div class="empty"><b>Ky numër nuk është barkod i plotë.</b>Kontrollo shifrat dhe provo përsëri.</div>`);
    if (d.items.length) return answer(d.items, `Barkodi ${esc(d.code)}`,
      d.source ? `<p class="note">Emri i produktit sipas barkodit: ${esc(d.name)} (Open Beauty Facts).${d.size_ok ? "" : " Madhësinë kontrolloje vetë."}</p>` : "");
    say(`<div class="scan-unsure"><b>Ky barkod nuk është te dyqanet që krahasojmë.</b>
      <p>${d.name ? `Sipas barkodit është <i>${esc(d.name)}</i>, por nuk e gjejmë saktësisht te dyqanet online. ` : "Pak dyqane e shkruajnë barkodin. "}Provo një foto të pjesës së përparme.</p>
      ${photoBtn}</div>`);
  };

  // the camera: a code counts only when it is read the same twice in a row with a correct check digit
  let stream = null, timer = null, zx = null, last = null;
  const checkDigit = (c) => { const d = c.split("").map(Number), body = d.slice(0, -1).reverse();
    return (10 - body.reduce((t, x, i) => t + x * (i % 2 ? 1 : 3), 0) % 10) % 10 === d[d.length - 1]; };
  const seen = (code) => {
    if (!/^\d{8,14}$/.test(code) || !checkDigit(code)) return;
    if (code !== last) { last = code; return; }
    stop(); navigator.vibrate?.(60); byCode(code);
  };
  const stop = () => {
    clearInterval(timer); timer = null; last = null;
    if (zx) { zx.reset(); zx = null; }
    if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
    stage.classList.remove("live"); stage.hidden = true;
  };
  scanStop = stop;
  const video = { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 }, advanced: [{ focusMode: "continuous" }] };
  document.getElementById("way-code").onclick = async () => {
    result.innerHTML = "";
    stage.hidden = false;
    status.textContent = "Duke hapur kamerën…";
    stage.scrollIntoView({ behavior: calm() ? "auto" : "smooth", block: "center" });
    const v = document.getElementById("scan-video");
    try {
      if ("BarcodeDetector" in window) {
        stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
        v.srcObject = stream;
        await v.play();
        const det = new BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a", "upc_e"] });
        timer = setInterval(async () => { const c = await det.detect(v).catch(() => []); if (c.length) seen(c[0].rawValue); }, 200);
      } else {
        await loadScript(ZXING);
        const hints = new Map([[ZXing.DecodeHintType.POSSIBLE_FORMATS, [ZXing.BarcodeFormat.EAN_13, ZXing.BarcodeFormat.EAN_8,
          ZXing.BarcodeFormat.UPC_A, ZXing.BarcodeFormat.UPC_E]], [ZXing.DecodeHintType.TRY_HARDER, true]]);
        zx = new ZXing.BrowserMultiFormatReader(hints, 150);
        zx.decodeFromConstraints({ video }, v, (r) => { if (r) seen(r.getText()); });
      }
      stage.classList.add("live");
      status.textContent = "Mbaje barkodin brenda kornizës, 10–15 cm larg.";
    } catch {
      stop();
      say(`<div class="scan-unsure"><b>Kamera nuk u hap.</b><p>Lejo kamerën te cilësimet e shfletuesit, ose bëj një foto.</p>${photoBtn}</div>`);
    }
  };
  document.getElementById("scan-close").onclick = stop;
  document.getElementById("scan-code").onsubmit = (e) => {
    e.preventDefault();
    const code = document.getElementById("scan-digits").value.replace(/\D/g, "");
    if (code) { stop(); byCode(code); }
  };

  // a photo: its barcode first (exact), else the words on the package
  const photo = async (file) => {
    stop();
    busy("Duke lexuar foton në telefon… (herën e parë zgjat pak)");
    try {
      let code = null;
      if ("BarcodeDetector" in window) {
        const c = await new BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a", "upc_e"] }).detect(await createImageBitmap(file)).catch(() => []);
        code = c[0]?.rawValue || null;
      } else {
        await loadScript(ZXING).catch(() => {});
        if (window.ZXing) {
          const url = URL.createObjectURL(file);
          const r = await new ZXing.BrowserMultiFormatReader(new Map([[ZXing.DecodeHintType.TRY_HARDER, true]])).decodeFromImageUrl(url).catch(() => null);
          URL.revokeObjectURL(url);
          code = r ? r.getText() : null;
        }
      }
      if (code && checkDigit(code)) {
        const d = await api(`/api/barcode?code=${encodeURIComponent(code)}`).catch(() => null);
        if (d && d.items.length) return answer(d.items, `Barkodi ${esc(d.code)}`);
        busy(`Barkodi ${esc(code)} nuk është te dyqanet tona. Po lexojmë emrin në foto…`);
      }
      await loadScript(TESSERACT);
      const { data } = await Tesseract.recognize(file, "eng");
      const text = data.text.replace(/\s+/g, " ").trim();
      if (!text) return say(`<div class="scan-unsure"><b>Nuk lexuam dot asnjë fjalë.</b><p>Fotografo emrin e produktit nga afër, me dritë.</p>${photoBtn}</div>`);
      const d = await api(`/api/identify?text=${encodeURIComponent(text.slice(0, 600))}`).catch(() => null);
      if (d && d.sure && d.items.length) return answer(d.items, `Lexuam: ${esc(d.words.join(" "))}`);
      unsure(d || {});
    } catch {
      say(`<div class="scan-unsure"><b>Nuk e lexuam dot foton.</b><p>Provo përsëri ose kërko me emër.</p>${photoBtn}</div>`);
    }
  };
  main.querySelector(".scan").addEventListener("change", (e) => {
    if (!e.target.matches("#scan-file, [data-photo]")) return;
    const f = e.target.files[0];
    e.target.value = "";  // the same photo can be chosen again
    if (f) photo(f);
  });
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
  if (scanStop) { scanStop(); scanStop = null; }
  document.querySelectorAll(".tabbar a").forEach((a) => {
    const h = a.getAttribute("href");
    a.toggleAttribute("aria-current", h === "/" ? pathname === "/" : pathname.startsWith(h));
  });
  document.body.classList.toggle("on-product", pathname.startsWith("/produkt/"));
  document.body.classList.toggle("at-home", pathname === "/");  // the home page has its own big search
  const params = search.slice(1);
  document.querySelectorAll(".top-nav a").forEach((a) => {
    if (pathname.startsWith(a.getAttribute("href"))) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  // the links in our emails open pages the server writes in full: nothing to add to them
  if (pathname.startsWith("/njoftim/") && main.hasAttribute("data-ssr")) return;
  // the first page already came from the server (seo.py): keep it on screen until the full one is ready
  if (main.hasAttribute("data-ssr")) main.removeAttribute("data-ssr");
  else {
    const was = main.firstElementChild;
    setTimeout(() => { if (main.firstElementChild === was) main.innerHTML = `<div class="wrap skel" aria-busy="true"><span class="sr">Duke ngarkuar…</span>
      <i class="sk-title"></i><i class="sk-line"></i><div class="grid">${"<i class=sk-tile></i>".repeat(4)}</div></div>`; }, 150);
  }
  document.title = "shporta: krahaso çmimet në dyqanet online të Shqipërisë";
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
    else if (pathname === "/per-dyqanet") pageForShops(params);
    else if (pathname === "/dupe") await pageDupes(params);
    else if (pathname === "/ndaj") await pageShare(params);
    else if (pathname === "/lista") await pageList();
    else if (pathname === "/njoftime") await pageNotes();
    else if (pathname === "/raport") await pageReport();
    else if (pathname === "/shporta") await pageBasket();
    else if (pathname === "/skano") await pageScan();
    else if ((m = pathname.match(/^\/raport\/(\d{4}-\d{2})$/))) await pageReport(m[1]);
    else throw Object.assign(new Error("Kjo faqe nuk ekziston."), { status: 404 });
  } catch (e) {
    main.innerHTML = `<div class="wrap empty"><b>${esc(e.status === 404 ? e.message : "Faqja nuk u ngarkua.")}</b>
      ${e.status === 404 ? `<a href="/" data-link>Kthehu në faqen kryesore</a>` : "Serveri mund të jetë duke u zgjuar. Rifresko faqen pas pak sekondash."}</div>`;
  }
  wireAllSuggest();
  if (!homeCache) api("/api/home").then((d) => { homeCache = d; setFoot(d.stats.updated); }).catch(() => {});
}

function go(url) {
  history.replaceState({ ...(history.state || {}), y: window.scrollY }, "");  // back returns to this spot
  history.pushState({ depth: ((history.state || {}).depth || 0) + 1 }, "", url);
  window.scrollTo(0, 0);
  route().then(() => {
    main.focus({ preventScroll: true });
    if (main.animate) main.animate(calm() ? [{ opacity: 0 }, { opacity: 1 }]
      : [{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], { duration: 220, easing: EASE_OUT });
  });
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
if ("scrollRestoration" in history) history.scrollRestoration = "manual";
window.addEventListener("popstate", (e) => {
  const y = (e.state && e.state.y) || 0;
  route().then(() => requestAnimationFrame(() => window.scrollTo(0, y)));
});
// the back arrow: one step back inside shporta, or up to the page this one belongs to when you arrived here directly
const backBtn = document.getElementById("nav-back");
function backTarget() {
  return document.querySelector("main .crumbs a")?.getAttribute("href") || "/";
}
backBtn.onclick = () => ((history.state || {}).depth > 0 ? history.back() : go(backTarget()));
backBtn.hidden = location.pathname === "/";
new MutationObserver(() => { backBtn.hidden = location.pathname === "/"; }).observe(main, { childList: true });
route();
watchBadge();
basketBadge();
bellBadge();
if (watchList().length && location.pathname !== "/njoftime") noteDrops().catch(() => {});
consentBanner();
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
  navigator.serviceWorker.addEventListener("message", (e) => {
    if (e.data?.type === "open") go(new URL(e.data.url, location.origin).pathname);
    if (e.data?.type === "push") { watchNow = null; noteDrops().catch(() => {}); }  // a notification just came in
  });
}

/* ---------- Install on the phone ---------- */
// Chrome, Edge and Samsung Internet hand us an install prompt; iPhone Safari has none, so there we explain the two taps.
// The card shows once the cookie banner is gone, and stays away for 30 days after "Jo tani".
let installPrompt = null;
const INSTALL_KEY = "shporta-install-later";
const isStandalone = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const isPhone = () => matchMedia("(max-width: 860px)").matches;
const installHelp = () => isIOS()
  ? "Në Safari shtyp butonin Ndaj (katrori me shigjetë lart), pastaj “Add to Home Screen” / “Shto në ekranin bazë”."
  : "Hap menynë e shfletuesit (⋮ lart djathtas), pastaj “Instalo aplikacionin” ose “Add to Home screen”.";

function installCard(help) {
  document.getElementById("install")?.remove();
  document.body.insertAdjacentHTML("beforeend", `<div class="install" id="install" role="dialog" aria-label="Shkarko aplikacionin">
    <img src="/assets/icon-192.png?v=2" alt="" width="44" height="44">
    <p><strong>shporta në telefon</strong><span>${help ? installHelp() : "Me një prekje nga ekrani. Falas."}</span></p>
    <div>${help ? "" : '<button class="btn" type="button" data-install>Instalo</button>'}
      <button class="install-x" type="button" data-install-later aria-label="Jo tani">×</button></div>
  </div>`);
}

function maybeOfferInstall() {
  if (isStandalone() || !isPhone() || document.getElementById("consent")) return;
  try { if (Date.now() - Number(localStorage.getItem(INSTALL_KEY) || 0) < 30 * 864e5) return; } catch {}
  if (installPrompt) installCard(false);
  else if (isIOS() && /safari/i.test(navigator.userAgent) && !/crios|fxios|edgios/i.test(navigator.userAgent)) installCard(false);
}

window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e; setTimeout(maybeOfferInstall, 4000); });
window.addEventListener("appinstalled", () => { installPrompt = null; document.getElementById("install")?.remove(); });
setTimeout(maybeOfferInstall, 6000);
document.addEventListener("click", async (e) => {
  if (e.target.closest("[data-consent]")) setTimeout(maybeOfferInstall, 1500);
  if (e.target.closest("[data-install-later]")) {
    try { localStorage.setItem(INSTALL_KEY, String(Date.now())); } catch {}
    document.getElementById("install")?.remove();
  }
  if (!e.target.closest("[data-install]")) return;
  e.preventDefault();
  if (isStandalone()) return;
  if (installPrompt) {
    installPrompt.prompt();
    const { outcome } = await installPrompt.userChoice;
    installPrompt = null;
    document.getElementById("install")?.remove();
    if (outcome !== "accepted") try { localStorage.setItem(INSTALL_KEY, String(Date.now())); } catch {}
  } else installCard(true);
});
