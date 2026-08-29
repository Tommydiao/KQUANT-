const CACHE = "kquant-crypto-static-v3";
const STATIC_PATHS = ["/manifest.webmanifest", "/favicon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(STATIC_PATHS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  const payload = event.data?.json?.() ?? { title: "KQUANT Crypto", body: "New research update", deep_link: "/" };
  event.waitUntil(self.registration.showNotification(payload.title, { body: payload.body, tag: payload.notification_id, data: { deep_link: payload.deep_link || "/" } }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.deep_link || "/", self.location.origin).href;
  event.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
    const current = windows.find((window) => "focus" in window);
    if (current) { current.navigate(target); return current.focus(); }
    return clients.openWindow(target);
  }));
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (!(url.pathname.startsWith("/assets/") || STATIC_PATHS.includes(url.pathname))) return;
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
});
