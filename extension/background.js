// Talks to shporta.app for the content script (it can't call our API itself from a shop's page), sets the toolbar
// badge (the saving on this page), and gives the popup the last result of the current tab.
// Sends only the product name, price, currency, barcode and page address. At a shop shporta can't read itself, and
// only after the shopper said yes, shporta keeps that (with the picture and stock the page publishes) as a shared price.
const API = "https://shporta.app";
// the service worker sleeps between events, so the last result per tab lives in session storage (cleared on restart)

async function lookup(product) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 20000);
  try {
    const r = await fetch(`${API}/api/lookup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(product),
      signal: ctrl.signal,
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  const tab = sender.tab && sender.tab.id;
  if (msg.type === "lookup") {
    lookup(msg.product)
      .then((data) => { if (tab != null) chrome.storage.session.set({ [`t${tab}`]: { product: msg.product, data } }); reply({ ok: true, data }); })
      .catch((e) => reply({ ok: false, error: String(e) }));
    return true; // keep the channel open for the async reply
  }
  if (msg.type === "badge" && tab != null) {
    chrome.action.setBadgeText({ tabId: tab, text: msg.text || "" });
    if (msg.color) chrome.action.setBadgeBackgroundColor({ tabId: tab, color: msg.color });
    if (chrome.action.setBadgeTextColor) chrome.action.setBadgeTextColor({ tabId: tab, color: "#14121F" });
    reply({});
  }
  if (msg.type === "last") {
    chrome.storage.session.get(`t${msg.tab}`, (v) => reply((v && v[`t${msg.tab}`]) || null));
    return true;
  }
});

chrome.tabs.onRemoved.addListener((tab) => chrome.storage.session.remove(`t${tab}`));
