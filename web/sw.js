// Makes shporta installable (and so a target in the phone's Share menu). It doesn't cache prices:
// every request goes to the network, so what you see is always the latest data.
// It also shows the price-drop notifications the server sends (push.py), even when shporta is closed.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;
  e.respondWith(fetch(e.request).catch(() => new Response(
    "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>" +
    "<p style='font:16px system-ui;padding:24px'>shporta ka nevojë për internet. Provo përsëri kur të jesh online.</p>",
    { headers: { "Content-Type": "text/html; charset=utf-8" } })));
});

self.addEventListener("push", (e) => {
  let m = {};
  try { m = e.data ? e.data.json() : {}; } catch { m = { title: "shporta", body: e.data ? e.data.text() : "" }; }
  e.waitUntil((async () => {
    await self.registration.showNotification(m.title || "shporta", {
      body: m.body || "", tag: m.tag, renotify: Boolean(m.tag), data: { url: m.url || "/njoftime" },
      icon: "/assets/icon-192.png", lang: "sq",
    });
    // an open shporta tab adds it to its own list of notifications at once
    for (const c of await self.clients.matchAll({ type: "window" })) c.postMessage({ type: "push", message: m });
  })());
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = new URL(e.notification.data?.url || "/", self.location.origin).href;
  e.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const tab = open.find((c) => new URL(c.url).origin === self.location.origin);
    if (tab) { await tab.focus(); return tab.navigate(url).catch(() => tab.postMessage({ type: "open", url })); }
    return self.clients.openWindow(url);
  })());
});
