/*
 * JurisAI servis çalışanı: yalnız "uygulama olarak yüklenebilirlik" ve çevrimdışı uyarı sayfası içindir.
 *
 * KVKK gereği hiçbir API yanıtı, belge, sohbet ya da oturumlu sayfa ÖNBELLEĞE ALINMAZ. Önbelleğe yalnız çevrimdışı sayfa ve simgeler
 * girer. Gezinme isteği ağa gidemezse çevrimdışı sayfa gösterilir; diğer her istek doğrudan ağa gider.
 */
const CACHE = "jurisai-shell-v1";
const SHELL = ["/offline.html", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || request.mode !== "navigate") return; // yalnız sayfa gezintisi; API ve varlıklar ağa gider
  event.respondWith(fetch(request).catch(() => caches.match("/offline.html")));
});
