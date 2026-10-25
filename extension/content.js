// Reads the product on the page the shopper is viewing, asks shporta.app, shows a small pill that opens into a panel.
// It never contacts the shop and stores nothing from the page (only, if asked, "don't show on this site").
(() => {
  const SITE = "https://shporta.app";
  const CUR = { L: "ALL", LEK: "ALL", "LEKË": "ALL", LEKE: "ALL", ALL: "ALL", "€": "EUR", EUR: "EUR" };
  if (location.hostname.endsWith("shporta.app")) return;
  const HOST = location.hostname.replace(/^www\./, "");

  function num(v) {
    if (v == null) return null;
    let s = String(v).replace(/[^\d.,]/g, "");
    if (/^\d{1,3}(\.\d{3})+(,\d+)?$/.test(s)) s = s.replace(/\./g, "").replace(",", ".");
    else if (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(s)) s = s.replace(/,/g, "");
    else s = s.replace(",", ".");
    const n = parseFloat(s);
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  // the barcode a shop publishes for search engines: the most exact way to know which product this is
  const gtinOf = (d, offers) => [d.gtin13, d.gtin, d.gtin12, d.gtin14, d.gtin8, offers && (offers.gtin13 || offers.gtin)]
    .map((g) => String(g || "").replace(/\D/g, "")).find((g) => [8, 12, 13, 14].includes(g.length)) || "";

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
          if (d.name && price) return { title: d.name, price, currency: offers.priceCurrency || "ALL", gtin: gtinOf(d, offers) };
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
    return { title: title.trim(), price, currency: m("product:price:currency") || m("og:price:currency") || "ALL",
             gtin: String(m("gtin13") || m("product:ean") || "").replace(/\D/g, "") };
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
    p.url = location.origin + location.pathname;  // never the query or #part: they can carry tracking or session ids
    return p;
  }

  const fmt = (n, c) => (c === "EUR" ? "€" + Number(n).toFixed(2) : c === "USD" ? "$" + Number(n).toFixed(2)
    : c && c !== "ALL" ? Number(n).toFixed(2) + " " + c : Math.round(n).toLocaleString("en").replace(/,/g, " ") + " L");
  const host = (d) => String(d || "").replace(/^www\./, "");
  const VERDICT = { good: ["Çmim i mirë", "good"], normal: ["Çmim normal", "normal"], high: ["Çmim i lartë", "high"] };

  // The panel's look: shporta's own (violet, lime for the cheapest, ink), light and dark, inside a shadow root
  // so the shop's CSS can't touch it and ours can't touch the shop.
  const STYLE = `
    :host{all:initial}
    *{box-sizing:border-box}
    .w{position:fixed;right:16px;bottom:16px;z-index:2147483647;font:13px/1.45 system-ui,"Segoe UI",Roboto,sans-serif;color:var(--ink);
      --ink:#14121F;--paper:#fff;--soft:#F6F5F9;--line:#E7E5EE;--muted:#6E6A7C;--violet:#7B4DFF;--vdeep:#5B2EE0;--tint:#F1ECFF;--lime:#C6F432}
    @media (prefers-color-scheme:dark){.w{--ink:#F1EFF7;--paper:#1B1829;--soft:#241F38;--line:#2C2840;--muted:#A7A2B8;--violet:#A58BFF;--vdeep:#C2B1FF;--tint:#2B2445}}
    .pill{display:flex;align-items:center;gap:8px;background:var(--ink);color:var(--paper);border:0;border-radius:999px;padding:7px 14px 7px 7px;
      font:600 13px/1 system-ui,"Segoe UI",sans-serif;cursor:pointer;box-shadow:0 10px 28px rgba(20,18,31,.28)}
    @media (prefers-color-scheme:dark){.pill{background:#F1EFF7;color:#14121F}}
    .pill img{width:24px;height:24px;border-radius:7px}
    .pill b{background:var(--lime);color:#14121F;border-radius:999px;padding:4px 8px}
    .pill.warn b{background:#FFB497}
    .p{width:340px;max-width:calc(100vw - 32px);max-height:min(560px,calc(100vh - 40px));overflow:auto;background:var(--paper);
      border:1px solid var(--line);border-radius:18px;box-shadow:0 18px 50px rgba(20,18,31,.28);padding:14px 16px 12px}
    .hd{display:flex;align-items:center;gap:8px;margin-bottom:10px}
    .hd img{width:26px;height:26px;border-radius:8px}
    .hd strong{font:800 16px/1 system-ui,sans-serif;letter-spacing:-.02em;flex:1}
    .ic{border:0;background:var(--soft);color:var(--muted);width:28px;height:28px;border-radius:50%;cursor:pointer;font-size:16px;line-height:28px}
    .ic:hover{color:var(--ink)}
    .verdict{border-radius:12px;padding:10px 12px;margin-bottom:10px;background:var(--soft)}
    .verdict.good{background:color-mix(in srgb,var(--lime) 28%,var(--paper))}
    .verdict.high{background:color-mix(in srgb,#FF9A73 22%,var(--paper))}
    .verdict .v{font-weight:800;font-size:15px}
    .verdict .s{color:var(--muted);margin-top:2px}
    .verdict .big{font:800 22px/1.1 system-ui,sans-serif;margin-top:4px}
    .risk{border:1px solid #FFB497;background:color-mix(in srgb,#FF9A73 14%,var(--paper));border-radius:12px;padding:8px 10px;margin-bottom:10px;font-weight:600}
    h3{margin:12px 0 4px;font-size:12px;color:var(--muted);font-weight:700;text-transform:none}
    .note{color:var(--muted);font-size:12px;margin:2px 0 6px}
    a.row{display:grid;grid-template-columns:1fr auto;gap:2px 10px;padding:7px 0;border-top:1px solid var(--line);color:inherit;text-decoration:none;align-items:center}
    a.row:hover .n{color:var(--violet)}
    .n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
    .pr{font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
    .best .pr{background:var(--lime);color:#14121F;border-radius:6px;padding:1px 6px}
    .bar{grid-column:1/-1;height:3px;border-radius:2px;background:var(--line);overflow:hidden}
    .bar i{display:block;height:100%;background:var(--violet);border-radius:2px}
    .best .bar i{background:var(--lime)}
    .out{opacity:.5}
    .chip{font-size:11px;background:var(--tint);color:var(--vdeep);border-radius:999px;padding:1px 7px;margin-left:4px}
    .alt{margin-top:8px;padding:6px 10px 2px;background:var(--soft);border-radius:12px}
    .acts{display:flex;gap:8px;margin-top:12px}
    .btn{flex:1;text-align:center;font:700 13px/1 system-ui,sans-serif;border-radius:999px;padding:10px 12px;text-decoration:none;border:0;cursor:pointer}
    .btn.pri{background:var(--violet);color:#fff}
    .btn.sec{background:var(--soft);color:var(--ink)}
    .ft{display:flex;justify-content:space-between;gap:8px;color:var(--muted);font-size:11px;margin-top:10px}
    .ft button{border:0;background:none;color:var(--muted);text-decoration:underline;cursor:pointer;font:inherit;padding:0}`;

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
  const LOGO = chrome.runtime.getURL("icons/icon-48.png");
  const go = (o) => `${SITE}/go/${encodeURIComponent(o.id)}?i=${encodeURIComponent(o.item || "")}&f=ext`;

  function mount(build) {
    document.getElementById("shporta-host")?.remove();
    const el = document.createElement("div");
    el.id = "shporta-host";
    const root = el.attachShadow({ mode: "open" });
    const w = node("div", { class: "w" });
    root.append(node("style", { text: STYLE }), w);
    build(w, el);
    document.documentElement.appendChild(el);
    return el;
  }
  const badge = (text, color) => chrome.runtime.sendMessage({ type: "badge", text, color }, () => void chrome.runtime.lastError);

  // the short version, in the corner: what matters in one line; a click opens the panel
  function summary(product, data) {
    const live = (data.exact || []).filter((o) => o.in_stock);
    const v = data.verdict;
    if (data.risk) return ["Kujdes: çmim shumë i ulët", true];
    if (v && v.save > 0) return [`${fmt(v.save, product.currency)} më lirë diku tjetër`, false];
    if (v) return [VERDICT[v.label][0], false];
    if (live.length) return [`Në ${live.length} dyqane të tjera`, false];
    if ((data.dupes || []).length) return ["Ka dupe më të lirë", false];
    if ((data.same_name || []).length || (data.similar || []).length) return ["Produkte të ngjashme", false];
    return null;
  }

  function render(product, data, open) {
    const sum = summary(product, data);
    if (!sum) { badge("", ""); return mount((w, el) => { w.append(pillNode("Nuk e gjetëm në dyqanet e tjera", false, () => el.remove())); setTimeout(() => el.isConnected && el.remove(), 6000); }); }
    const v = data.verdict;
    badge(data.risk ? "!" : v && v.save > 0 ? `-${v.save >= 1000 ? Math.round(v.save / 1000) + "k" : Math.round(v.save)}` : v ? "✓" : "",
          data.risk ? "#FF9A73" : v && v.save > 0 ? "#C6F432" : "#7B4DFF");
    mount((w, el) => {
      const show = (expanded) => {
        w.replaceChildren(expanded ? panelNode(product, data, el, () => show(false)) : pillNode(sum[0], sum[1], () => show(true)));
      };
      show(open);
    });
  }

  function pillNode(text, warn, onclick) {
    const b = node("button", { class: "pill" + (warn ? " warn" : ""), "aria-label": `shporta: ${text}. Hape` },
      node("img", { src: LOGO, alt: "" }), node("span", { text: "shporta" }), node("b", { text }));
    b.onclick = onclick;
    return b;
  }

  // Three parts, never mixed: the same product in the same size (the only thing the price verdict uses),
  // then, apart and labelled, other products: the same name in other sizes, similar ones and dupes.
  function panelNode(product, data, el, minimize) {
    const live = (data.exact || []).filter((o) => o.in_stock);
    const exact = live.length ? live : data.exact || [];
    const same = data.same_name || [];
    const similar = exact.length || same.length ? [] : data.similar || [];
    const dupes = data.dupes || [];
    const q = data.query || {};
    const p = node("div", { class: "p", role: "dialog", "aria-label": "shporta" });
    const min = node("button", { class: "ic", title: "Zvogëlo", "aria-label": "Zvogëlo", text: "–" });
    min.onclick = minimize;
    const x = node("button", { class: "ic", title: "Mbyll", "aria-label": "Mbyll", text: "×" });
    x.onclick = () => el.remove();
    p.append(node("div", { class: "hd" }, node("img", { src: LOGO, alt: "" }), node("strong", { text: "shporta" }), min, x));

    if (data.risk) p.append(node("div", { class: "risk", text:
      "Ky çmim është shumë më i ulët se te dyqanet e tjera për të njëjtin produkt. Kontrollo që është origjinal, i ri dhe në të njëjtën madhësi." }));
    const v = data.verdict;
    if (exact.length && v) {
      p.append(node("div", { class: `verdict ${VERDICT[v.label][1]}` },
        node("div", { class: "v", text: VERDICT[v.label][0] }),
        v.save > 0 ? node("div", { class: "big", text: `${fmt(v.save, product.currency)} më lirë` }) : null,
        node("div", { class: "s", text: v.save > 0 ? `te dyqani më i lirë, për të njëjtin produkt${q.size_label ? " " + q.size_label : ""}`
          : `Mesatarja në ${v.shops} dyqane: ${fmt(v.median, product.currency)}` })));
    }
    if (exact.length) {
      p.append(node("h3", { text: "I njëjti produkt" + (q.size_label ? `, ${q.size_label}` : "") + (q.by_barcode ? " (sipas barkodit)" : "") }));
      if (q.size_assumed && q.size_label)
        p.append(node("div", { class: "note", text: `Kjo faqe nuk e shkruan madhësinë. E krahasuam me ${q.size_label}, sipas çmimit: kontrolloje te dyqani.` }));
      const all = [...exact.slice(0, 6).map((o) => o.price), product.price].filter(Boolean);
      const max = Math.max(...all), lo = Math.min(...exact.filter((o) => o.in_stock).map((o) => o.price));
      // the page you're on, then the other shops, all on one scale
      p.append(row(null, `${HOST} (kjo faqe)`, product.price, product.currency, product.price / max, product.price <= lo));
      exact.slice(0, 6).forEach((o) => p.append(row(go(o), host(o.shop) + (o.in_stock ? "" : " · s'ka gjendje"), o.price, o.currency,
        o.price / max, o.in_stock && o.price === lo && o.price < product.price, !o.in_stock)));
      if (data.unconfirmed && data.item && !same.length)
        p.append(node("div", { class: "note", text: `+${data.unconfirmed} dyqane e kanë pa shkruar madhësinë.` }));
    } else if (!same.length) {
      p.append(node("div", { class: "note", text: q.size_label ? `Nuk e gjetëm këtë produkt, ${q.size_label}, në dyqane të tjera.` : "Nuk e gjetëm këtë produkt në dyqane të tjera." }));
    }
    if (same.length) {
      const box = node("div", { class: "alt" }, node("h3", { text: "Emër i njëjtë, madhësi tjetër ose pa e shkruar" }));
      same.slice(0, 4).forEach((o) => box.append(row(go(o), `${host(o.shop)} · ${o.size || "pa madhësi"}`, o.price, o.currency)));
      p.append(box);
    }
    if (similar.length) {
      const box = node("div", { class: "alt" }, node("h3", { text: "Të ngjashme (jo i njëjti produkt)" }));
      similar.slice(0, 4).forEach((o) => box.append(row(go(o), `${host(o.shop)} · ${o.title}`, o.price, o.currency)));
      p.append(box);
    }
    if (dupes.length) {
      const box = node("div", { class: "alt" }, node("h3", { text: "Dupe: produkt tjetër, bën të njëjtën punë" }));
      dupes.slice(0, 3).forEach((d) => {
        const r = row(`${SITE}/produkt/${encodeURIComponent(d.dupe_id)}`, d.dupe_title, d.dupe_price, "ALL");
        if (d.reason) r.querySelector(".n").append(node("span", { class: "chip", text: d.reason }));
        box.append(r);
      });
      p.append(box);
    }
    if (data.item) {
      const page = `${SITE}/produkt/${encodeURIComponent(data.item)}`;
      p.append(node("div", { class: "acts" },
        node("a", { class: "btn pri", href: page, target: "_blank", rel: "noopener", text: "Të gjitha çmimet" }),
        node("a", { class: "btn sec", href: `${page}#ndiq`, target: "_blank", rel: "noopener", text: "Ndiq çmimin" })));
    }
    const off = node("button", { text: `Mos e shfaq te ${HOST}` });
    off.onclick = () => chrome.storage.local.set({ [`off:${HOST}`]: true }, () => { badge("", ""); el.remove(); });
    p.append(node("div", { class: "ft" }, node("span", { text: "Çmimet e sotme nga dyqanet shqiptare" }), off));
    return p;
  }

  function row(href, label, price, cur, share, best, out) {
    const r = node(href ? "a" : "div", href ? { class: "row" + (best ? " best" : "") + (out ? " out" : ""), href, target: "_blank", rel: "noopener sponsored" }
      : { class: "row" + (best ? " best" : ""), style: "display:grid;grid-template-columns:1fr auto;gap:2px 10px;padding:7px 0;border-top:1px solid var(--line)" },
      node("span", { class: "n", text: label }), node("span", { class: "pr", text: fmt(price, cur) }));
    if (share) r.append(node("span", { class: "bar" }, node("i", { style: `width:${Math.max(6, Math.min(100, share * 100)).toFixed(0)}%` })));
    return r;
  }

  let lastKey = "";
  function check() {
    const p = detect();
    const key = p ? p.url + "|" + p.price : "";
    if (!p || key === lastKey) return;
    lastKey = key;
    chrome.runtime.sendMessage({ type: "lookup", product: p }, (res) => {
      if (chrome.runtime.lastError || !res) return;
      if (res.ok) render(p, res.data, false);
    });
  }

  chrome.storage.local.get(`off:${HOST}`, (v) => {
    if (v && v[`off:${HOST}`]) return;  // the shopper chose not to see shporta on this site
    check();
    setInterval(check, 2000);  // single-page shops (Zara, LC Waikiki...) change product without reloading
  });
  // the toolbar button asks to open the panel
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "open") { lastKey = ""; const p = detect(); if (p) chrome.runtime.sendMessage({ type: "lookup", product: p }, (res) => res && res.ok && render(p, res.data, true)); }
  });
})();
