// Makes shporta installable (and so a target in the phone's Share menu). It doesn't cache prices:
// every request goes to the network, so what you see is always the latest data.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;
  e.respondWith(fetch(e.request).catch(() => new Response(
    "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>" +
    "<p style='font:16px system-ui;padding:24px'>shporta ka nevojë për internet. Provo përsëri kur të jesh online.</p>",
    { headers: { "Content-Type": "text/html; charset=utf-8" } })));
});
