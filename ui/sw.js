
// Service Worker: เก็บเฉพาะไฟล์ Demo
// ไม่เก็บคำตอบจาก AWS API

const CACHE_NAME = "muletrace-v1";

const FILES = [
  "./",
  "./index.html",
  "./style.css",
  "./data.js",
  "./config.js",
  "./app.js",
  "./manifest.webmanifest",
  "./assets/icon-192.png",
  "./assets/icon-512.png"
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