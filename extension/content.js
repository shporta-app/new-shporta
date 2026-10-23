// Reads the product on the page the shopper is viewing, asks shporta.app, shows a small panel.
// It never contacts the shop and stores nothing from the page.
(() => {
  const SITE = "https://shporta.app";
  const CUR = { L: "ALL", LEK: "ALL", "LEKË": "ALL", LEKE: "ALL", ALL: "ALL", "€": "EUR", EUR: "EUR" };
  if (location.hostname.endsWith("shporta.app")) return;

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

  // Some big shops (Zara) put no product data in the page's code: only the visible text "3.950 ALL".
  // Used only on pages that say they are a product page (og:type=product) or have a product-style address.
  const MONEY = /(?:(€|EUR|ALL|Lek[ëe]?)\s*(\d[\d.,\s]*\d|\d))|(?:(\d[\d.,\s]*\d|\d)\s*(ALL|Lek[ëe]?|L(?![a-z])|€|EUR))/i;
  function fromPage() {
    const og = (p) => document.querySelector(`meta[property="${p}"]`)?.content;
    const looksLikeProduct = og("og:type") === "product" || /[-/]p\d{5,}|\/product[s]?\/|\/produkt/i.test(location.pathname);
    if (!looksLikeProduct) return null;
    const title = (og("og:title") || document.querySelector("h1")?.textContent || "").trim();
    const els = [...document.querySelectorAll('[class*="price" i], [data-qa*="price" i], [itemprop="price"]')]
      .filter((e) => e.offsetParent !== null && !/old|original|crossed|strike|before|was|regular/i.test(e.className + " " + e.parentElement?.className));
    els.sort((a, b) => /current|sale|final|now/i.test(b.className) - /current|sale|final|now/i.test(a.className));
    for (const el of els) {
      const m = (el.textContent || "").replace(/\s+/g, " ").match(MONEY);
      if (!m) continue;
      const price = num(m[2] || m[3]);
      if (title && price) return { title, price, currency: m[1] || m[4] };
    }
    return null;
  }

  function detect() {
    const p = fromJsonLd() || fromMeta() || fromPage();
    if (!p) return null;
    p.currency = CUR[String(p.currency).trim().toUpperCase()] || String(p.currency).toUpperCase();
    p.url = location.href;
    return p;
  }

  const fmt = (n, c) => (c === "EUR" ? "€" + Number(n).toFixed(2) : Math.round(n).toLocaleString("en").replace(/,/g, " ") + " L");
  const host = (d) => String(d || "").replace(/^www\./, "");
  const LABEL = { good: ["Çmim i mirë", "#1f7a4d"], normal: ["Çmim normal", "#7a6a1f"], high: ["Çmim i lartë", "#b3261e"] };

  const STYLE = `.p{position:fixed;right:16px;bottom:16px;z-index:2147483647;width:310px;max-width:calc(100vw - 32px);background:#fff;color:#14121F;
     border:1px solid #E7E5EE;border-radius:12px;box-shadow:0 8px 28px rgba(20,18,31,.18);font:13px/1.4 system-ui,"Segoe UI",sans-serif;padding:12px 14px}
    .brand{font-weight:800;letter-spacing:-.02em;color:#7B4DFF;font-size:13px;margin-bottom:4px}
    .v{font-weight:700;font-size:15px}.s{color:#555;margin:2px 0 8px}
    h3{margin:0 0 4px;font-size:13px;font-weight:700}
    h4{margin:0 0 2px;font-size:12px;color:#6E6A7C;font-weight:600}
    .alt{margin-top:10px;padding:8px 10px 2px;background:#F6F5F9;border-radius:8px}
    a{display:flex;gap:10px;padding:6px 0;border-top:1px solid #eee;color:inherit;text-decoration:none;align-items:baseline;flex-wrap:wrap}
    a:hover span{text-decoration:underline}
    b{min-width:68px;font-variant-numeric:tabular-nums}span{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
    i{font-style:normal;font-size:11px;background:#F1ECFF;color:#5B2EE0;border-radius:999px;padding:1px 7px;margin-left:78px}
    .x{position:absolute;top:6px;right:8px;border:0;background:none;font-size:18px;cursor:pointer;color:#888}
    .f{color:#888;font-size:11px;margin-top:6px}
    a.more{display:block;color:#5B2EE0;font-size:12px}`;

  // Built with DOM nodes and textContent only: nothing from the page or the server is ever parsed as HTML.
  function node(tag, props = {}, ...children) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "text") n.textContent = v;
      else if (k === "style") n.style.cssText = v;
      else n.setAttribute(k, v);
    }
    n.append(...children.filter(Boolean));
    return n;
  }
  const link = (href, price, label, chip) => node("a", { href, target: "_blank", rel: "noopener" },
    node("b", { text: price }), node("span", { text: label }), chip ? node("i", { text: chip }) : null);

  // Three parts, never mixed: the same product in the same size (the only thing the price verdict uses),
  // then, apart and labelled, other products: similar ones (only when there's no exact match) and dupes.
  function render(product, data) {
    document.getElementById("shporta-host")?.remove();
    const exact = (data.exact || []).filter((o) => o.in_stock);
    const similar = exact.length ? [] : data.similar || [];
    const dupes = data.dupes || [];
    if (!exact.length && !similar.length && !dupes.length) return;
    const q = data.query || {};
    const el = document.createElement("div");
    el.id = "shporta-host";
    const root = el.attachShadow({ mode: "open" });
    const panel = node("div", { class: "p", role: "dialog", "aria-label": "shporta" });
    const close = node("button", { class: "x", title: "Mbyll", "aria-label": "Mbyll", text: "×" });
    close.onclick = () => el.remove();
    panel.append(close, node("div", { class: "brand", text: "shporta" }));
    const go = (o) => `${SITE}/go/${encodeURIComponent(o.id)}?i=${encodeURIComponent(o.item || "")}&f=ext`;

    if (exact.length) {
      const v = data.verdict;
      panel.append(node("h3", { text: "I njëjti produkt" + (q.size_label ? `, ${q.size_label}` : "") }));
      if (q.size_assumed && q.size_label)
        panel.append(node("div", { class: "s", text: `Kjo faqe nuk e shkruan madhësinë. E krahasuam me ${q.size_label}, sipas çmimit: kontrolloje te dyqani.` }));
      if (v) {
        panel.append(node("div", { class: "v", style: `color:${LABEL[v.label][1]}`, text: LABEL[v.label][0] }),
          node("div", { class: "s", text: v.save ? `${fmt(v.save, product.currency)} më lirë te dyqani më i lirë`
            : `Mesatarja në ${v.shops} dyqane: ${fmt(v.median, product.currency)}` }));
      }
      exact.slice(0, 5).forEach((o) => panel.append(link(go(o), fmt(o.price, o.currency), host(o.shop) + (o.size ? ` · ${o.size}` : ""))));
      if (data.unconfirmed && data.item)
        panel.append(node("a", { class: "more", href: `${SITE}/produkt/${encodeURIComponent(data.item)}`, target: "_blank", rel: "noopener",
          text: `+${data.unconfirmed} dyqane e kanë pa shkruar madhësinë: shiko te shporta.app` }));
    } else {
      panel.append(node("div", { class: "s", text: "Nuk e gjetëm këtë produkt, në këtë madhësi, në dyqane të tjera." }));
    }
    if (similar.length) {
      const box = node("div", { class: "alt" }, node("h4", { text: "Të ngjashme: jo i njëjti produkt" }));
      similar.slice(0, 4).forEach((o) => box.append(link(go(o), fmt(o.price, o.currency), `${host(o.shop)} · ${o.title}`)));
      panel.append(box);
    }
    if (dupes.length) {
      const box = node("div", { class: "alt" }, node("h4", { text: "Dupe: produkt tjetër, bën të njëjtën punë" }));
      dupes.slice(0, 3).forEach((d) => box.append(
        link(`${SITE}/produkt/${encodeURIComponent(d.dupe_id)}`, fmt(d.dupe_price, "ALL"), d.dupe_title, d.reason)));
      panel.append(box);
    }
    panel.append(node("div", { class: "f", text: "Çmimet nga dyqanet online shqiptare, në shporta.app" }));
    root.append(node("style", { text: STYLE }), panel);
    document.documentElement.appendChild(el);
  }

  let lastKey = "";
  let retried = false;
  function check() {
    const p = detect();
    const key = p ? p.url + "|" + p.price : "";
    if (!p || key === lastKey) return;
    lastKey = key;
    chrome.runtime.sendMessage({ type: "lookup", product: p }, (res) => {
      if (res && res.ok) render(p, res.data);
      else if (!retried) { retried = true; lastKey = ""; setTimeout(check, 20000); } // server may have been waking up
    });
  }

  check();
  // Single-page shops (Zara, LC Waikiki...) change product without reloading.
  setInterval(check, 2000);
})();
