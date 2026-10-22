// Talks to shporta.app for the content script (it can't call our API itself from a shop's page).
// Sends only the product name, price, currency and page address; stores nothing.
const API = "https://shporta.app";

async function lookup(product) {
  // the free server sleeps when idle and takes up to a minute to wake: wait for it once
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 75000);
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

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg.type !== "lookup") return;
  lookup(msg.product)
    .then((data) => reply({ ok: true, data }))
    .catch((e) => reply({ ok: false, error: String(e) }));
  return true; // keep the channel open for the async reply
});
