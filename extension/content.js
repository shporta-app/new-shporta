// Reads the product on the page the shopper is viewing (no requests to the shop), asks our API, shows a panel.
(() => {
  const CUR = { L: "ALL", LEK: "ALL", "LEKË": "ALL", LEKE: "ALL", ALL: "ALL", "€": "EUR", EUR: "EUR" };

  function num(v) {
    if (v == null) return null;
    let s = String(v).replace(/[^\d.,]/g, "");
    if (/^\d{1,3}(\.\d{3})+(,\d+)?$/.test(s)) s = s.replace(/\./g, "").replace(",", ".");
    else if (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(s)) s = s.replace(/,/g, "");
    else s = s.replace(",", ".");
    const n = parseFloat(s);
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  function fromJsonLd() {
    for (const el of document.querySelectorAll('script[type="application/ld+json"]')) {
      let data;
      try { data = JSON.parse(el.textContent); } catch { continue; }
      const stack = [data];
      while (stack.length) {
        const d = stack.pop();
        if (Array.isArray(d)) { stack.push(...d); continue; }
        if (!d || typeof d !== "object") continue;
        const t = d["@type"];
        if (t === "Product" || t === "ProductGroup" || (Array.isArray(t) && t.includes("Product"))) {
          let offers = d.offers || (d.hasVariant && d.hasVariant[0] && d.hasVariant[0].offers);
          if (Array.isArray(offers)) offers = offers[0];
          const price = num(offers && (offers.price ?? offers.lowPrice));
          if (d.name && price) return { title: d.name, price, currency: offers.priceCurrency || "ALL" };
        }
        for (const k of ["@graph", "mainEntity", "itemListElement", "item"]) if (d[k]) stack.push(d[k]);
      }
    }
    return null;
  }

  function fromMeta() {
    const m = (p) => document.querySelector(`meta[property="${p}"], meta[name="${p}"], meta[itemprop="${p}"]`)?.content;
    const price = num(m("product:price:amount") || m("og:price:amount") || m("price") ||
      document.querySelector('[itemprop="price"]')?.getAttribute("content"));
    const title = m("og:title") || document.querySelector("h1")?.textContent;
    if (!price || !title) return null;
    return { title: title.trim(), price, currency: m("product:price:currency") || m("og:price:currency") || "ALL" };
  }

  function detect() {
    const p = fromJsonLd() || fromMeta();
    if (!p) return null;
    p.currency = CUR[String(p.currency).trim().toUpperCase()] || String(p.currency).toUpperCase();
    p.url = location.href;
    return p;
  }

  const fmt = (n, c) => (c === "EUR" ? "€" + n.toFixed(2) : Math.round(n).toLocaleString("en").replace(/,/g, " ") + " L");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const LABEL = { good: ["Çmim i mirë", "#1f7a4d"], normal: ["Çmim normal", "#7a6a1f"], high: ["Çmim i lartë", "#b3261e"] };

  function render(product, data) {
    document.getElementById("phia-al-host")?.remove();
    const exact = (data.exact || []).filter((o) => o.in_stock);
    const similar = data.similar || [];
    if (!exact.length && !similar.length) return;
    const host = document.createElement("div");
    host.id = "phia-al-host";
    const root = host.attachShadow({ mode: "open" });
    const v = data.verdict;
    const head = v
      ? `<div class="v" style="color:${LABEL[v.label][1]}">${LABEL[v.label][0]}</div>
         <div class="s">${v.save ? `Më lirë me ${fmt(v.save, product.currency)} te dyqani më i lirë` : `Mesatarja në ${v.shops} dyqane: ${fmt(v.median, product.currency)}`}</div>`
      : `<div class="v">${exact.length ? "Edhe në këto dyqane" : "Produkte të ngjashme"}</div>`;
    const list = (exact.length ? exact : similar).slice(0, 6).map((o) =>
      `<a href="${esc(o.url)}" target="_blank" rel="noopener"><b>${fmt(o.price, o.currency)}</b><span>${esc(o.shop.replace(/^www\./, ""))}${exact.length ? "" : " · " + esc(o.title)}</span></a>`).join("");
    root.innerHTML = `<style>
      .p{position:fixed;right:16px;bottom:16px;z-index:2147483647;width:300px;max-width:calc(100vw - 32px);background:#fff;color:#1b1b1f;
         border:1px solid #ddd;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.18);font:13px/1.4 "Segoe UI",system-ui,sans-serif;padding:12px 14px}
      .v{font-weight:700;font-size:15px}.s{color:#555;margin:2px 0 8px}
      a{display:flex;gap:10px;padding:6px 0;border-top:1px solid #eee;color:inherit;text-decoration:none}a:hover span{text-decoration:underline}
      b{min-width:70px;font-variant-numeric:tabular-nums}span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .x{position:absolute;top:6px;right:8px;border:0;background:none;font-size:16px;cursor:pointer;color:#888}
      .f{color:#888;font-size:11px;margin-top:6px}</style>
      <div class="p"><button class="x" title="Mbyll">×</button>${head}${list}<div class="f">Phia AL · çmimet nga dyqanet online shqiptare</div></div>`;
    root.querySelector(".x").onclick = () => host.remove();
    document.documentElement.appendChild(host);
  }

  let lastKey = "";
  function check() {
    const p = detect();
    const key = p ? p.url + "|" + p.price : "";
    if (!p || key === lastKey) return;
    lastKey = key;
    chrome.runtime.sendMessage({ type: "lookup", product: p }, (res) => {
      if (res && res.ok) render(p, res.data);
    });
  }

  check();
  // Single-page shops (Zara, LC Waikiki...) change product without reloading.
  setInterval(check, 2000);
})();
