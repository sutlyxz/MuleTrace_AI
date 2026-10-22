
// Service Worker: เก็บเฉพาะไฟล์ Demo
// ไม่เก็บคำตอบจาก AWS API

const CACHE_NAME = "muletrace-v3";

const FILES = [
  "./",
  "./index.html",
  "./assets/css/style.css",
  "./assets/css/case-manager.css",
  "./assets/js/data.js",
  "./assets/js/config.js",
  "./assets/js/i18n.js",
  "./assets/js/api.js",
  "./assets/js/app.js",
  "./assets/js/case-manager.js",
  "./manifest.webmanifest"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(FILES))
  );

  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      )
    )
  );

  self.clients.claim();
});

self.addEventListener("fetch", event => {
  if (event.request.method !== "GET") return;

  const url = new URL(event.request.url);

  if (url.origin !== self.location.origin) return;

  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (
          response.ok &&
          FILES.some(file =>
            new URL(
              file,
              self.registration.scope
            ).href === url.href
          )
        ) {
          const copy = response.clone();

          caches.open(CACHE_NAME)
            .then(cache =>
              cache.put(event.request, copy)
            );
        }

        return response;
      })
      .catch(() =>
        caches.match(event.request)
      )
  );
});
