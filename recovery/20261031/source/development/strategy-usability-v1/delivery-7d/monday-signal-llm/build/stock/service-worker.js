const STATIC_CACHE = "kquant-static-v2-versioned-assets-v2";

function isVersionedStaticAsset(url) {
  if (url.origin !== self.location.origin) return false;
  return /^\/assets\/[^/]+-[A-Za-z0-9_-]+\.(?:js|css)$/.test(url.pathname);
}

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) => Promise.all(
    names.filter((name) => name.startsWith("kquant-static-") && name !== STATIC_CACHE).map((name) => caches.delete(name)),
    )).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || !isVersionedStaticAsset(url)) return;
  event.respondWith(
    caches.open(STATIC_CACHE).then(async (cache) => {
      const cached = await cache.match(request);
      const network = fetch(request)
        .then((response) => {
          if (response.ok && url.origin === self.location.origin) cache.put(request, response.clone());
          return response;
        })
        .catch(() => cached || Response.error());
      return cached || network;
    }),
  );
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { title: "KQUANT", body: event.data ? event.data.text() : "有新的研究提醒。" };
  }
  const title = payload.title || "KQUANT 主动提醒";
  const options = {
    body: payload.body || "打开 KQUANT 查看详情。",
    icon: "/kquant-mark.svg",
    badge: "/kquant-mark.svg",
    tag: payload.tag || `kquant-${Date.now()}`,
    renotify: payload.severity === "RISK" || payload.severity === "CRITICAL",
    data: { url: payload.url || "/?workspace=today" },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/?workspace=today", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      const existing = clients.find((client) => client.url.startsWith(self.location.origin));
      if (existing) {
        existing.navigate(target);
        return existing.focus();
      }
      return self.clients.openWindow(target);
    }),
  );
});
