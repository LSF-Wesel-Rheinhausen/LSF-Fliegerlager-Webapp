const CACHE_NAME = "{{ cache_name|escapejs }}";
const CACHE_PREFIX = "{{ cache_prefix|escapejs }}";
const OFFLINE_URL = "{{ offline_url|escapejs }}";
const STATIC_ASSETS = [{% for asset in static_assets %}"{{ asset|escapejs }}"{% if not forloop.last %}, {% endif %}{% endfor %}];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME).map((name) => caches.delete(name))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  if (!STATIC_ASSETS.includes(url.pathname)) return;
  event.respondWith(caches.match(url.pathname).then((cached) => cached || fetch(request)));
});

self.addEventListener("push", (event) => {
  const data = event.data ? event.data.json() : {};
  event.waitUntil(self.registration.showNotification(data.title || "Fliegerlager", {
    body: data.body || "Es gibt eine neue Nachricht.",
    icon: "/static/billing/icons/icon-192.png",
    badge: "/static/billing/icons/icon-192.png",
    data: {url: data.url || "/"},
    tag: data.tag || undefined,
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/", self.location.origin);
  if (target.origin !== self.location.origin) return;
  event.waitUntil(clients.openWindow(target.pathname + target.search + target.hash));
});
