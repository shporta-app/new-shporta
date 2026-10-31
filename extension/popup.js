// The toolbar window: what shporta found on this tab, a search box, and a switch for showing the panel on this site.
const SITE = "https://shporta.app";
const fmt = (n, c) => (c === "EUR" ? "€" + Number(n).toFixed(2) : c && c !== "ALL" ? Number(n).toFixed(2) + " " + c
  : Math.round(n).toLocaleString("en").replace(/,/g, " ") + " L");
const el = (tag, props = {}, ...kids) => { const n = document.createElement(tag); Object.assign(n, props); n.append(...kids.filter(Boolean)); return n; };

document.getElementById("q").onsubmit = (e) => {
  e.preventDefault();
  const q = new FormData(e.target).get("q").trim();
  if (q) chrome.tabs.create({ url: `${SITE}/kerko?q=${encodeURIComponent(q)}` });
};

const shareBox = document.getElementById("share-on");
chrome.storage.local.get("share", (v) => { shareBox.checked = v.share === true; });
shareBox.onchange = () => chrome.storage.local.set({ share: shareBox.checked });

chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
  if (!tab) return;
  let hostName = "";
  try { hostName = new URL(tab.url).hostname.replace(/^www\./, ""); } catch {}
  if (hostName && !hostName.endsWith("shporta.app") && /^https:/.test(tab.url)) {
    const key = `off:${hostName}`;
    document.getElementById("site").hidden = false;
    document.getElementById("site-name").textContent = hostName;
    const box = document.getElementById("site-on");
    chrome.storage.local.get(key, (v) => { box.checked = !(v && v[key]); });
    box.onchange = () => (box.checked ? chrome.storage.local.remove(key) : chrome.storage.local.set({ [key]: true }));
  }
  chrome.runtime.sendMessage({ type: "last", tab: tab.id }, (res) => {
    const here = document.getElementById("here");
    if (!res || !res.data) {
      here.append(el("div", { className: "card" }, el("p", { className: "muted", textContent:
        "Hap një produkt në një dyqan online: shporta të tregon nëse çmimi është i mirë dhe ku e gjen më lirë." })));
      return;
    }
    const { product, data } = res, v = data.verdict;
    const card = el("div", { className: "card" }, el("h2", { textContent: product.title }));
    if (data.risk) card.append(el("p", { textContent: "Kujdes: shumë më lirë se dyqanet e tjera. Kontrollo origjinalitetin." }));
    if (v && v.save > 0) card.append(el("div", { className: "big save", textContent: `${fmt(v.save, product.currency)} më lirë` }),
      el("div", { className: "muted", textContent: `diku tjetër, nga ${v.shops} dyqane që e kanë` }));
    else if (v) card.append(el("div", { className: "big", textContent: v.label === "good" ? "Çmim i mirë" : v.label === "high" ? "Çmim i lartë" : "Çmim normal" }),
      el("div", { className: "muted", textContent: `Mesatarja në ${v.shops} dyqane: ${fmt(v.median, product.currency)}` }));
    else card.append(el("div", { className: "muted", textContent: (data.exact || []).length ? "Gjendet edhe në dyqane të tjera." : "Nuk e gjetëm në dyqanet e tjera." }));
    const acts = el("div", { style: "display:flex;gap:6px;margin-top:10px" });
    const open = el("button", { className: "sec", textContent: "Hape panelin", style: "flex:1" });
    open.onclick = () => { chrome.tabs.sendMessage(tab.id, { type: "open" }); window.close(); };
    acts.append(open);
    if (data.item) acts.append(el("a", { className: "btn pri", href: `${SITE}/produkt/${encodeURIComponent(data.item)}`, target: "_blank",
      textContent: "Të gjitha çmimet", style: "flex:1" }));
    card.append(acts);
    here.append(card);
  });
});
