// Talks to our API. Content scripts can't call it themselves from an https shop page, so they ask us.
// The hosted API first; the local one (python server.py) when developing.
const APIS = ["https://new-shporta.onrender.com", "http://127.0.0.1:8787"];

async function lookup(product) {
  let lastError;
  for (const api of APIS) {
    try {
      const r = await fetch(`${api}/api/lookup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(product),
      });
      if (r.ok) return await r.json();
      lastError = new Error(`HTTP ${r.status}`);
    } catch (e) {
      lastError = e;
    }
  }
  throw lastError;
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg.type !== "lookup") return;
  lookup(msg.product)
    .then((data) => reply({ ok: true, data }))
    .catch((e) => reply({ ok: false, error: String(e) }));
  return true; // keep the channel open for the async reply
});
