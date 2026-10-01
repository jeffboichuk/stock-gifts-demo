// Minimal service worker for FHSA Fun(ds).
// Strategy:
//   network-first  : the page itself and same-origin *.json (prices/history
//                    sidecars), so the numbers stay fresh; falls back to the
//                    last cached copy when offline.
//   cache-first    : the CDN chart libraries (versioned URLs, never change)
//                    and same-origin static assets like icons.
// Registered with a relative path so the scope works under the GitHub Pages
// subpath (/stock-gifts/).
const CACHE = "fhsa-funds-v1";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// prices.json / history.json are fetched with a ?ts= cache-buster; strip the
// query so the cache holds one fresh copy per file instead of hundreds.
function cacheKeyFor(url) {
  return url.origin + url.pathname;
}

async function networkFirst(request, url) {
  const cache = await caches.open(CACHE);
  const key = cacheKeyFor(url);
  try {
    const response = await fetch(request);
    if (response && response.ok) cache.put(key, response.clone());
    return response;
  } catch (err) {
    const hit = await cache.match(key);
    if (hit) return hit;
    throw err;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response && response.ok) cache.put(request, response.clone());
  return response;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  const isCdn = url.hostname === "cdn.jsdelivr.net";
  const isPage = request.mode === "navigate" || url.pathname.endsWith("/index.html");
  const isSameOrigin = url.origin === self.location.origin;
  const isJson = isSameOrigin && url.pathname.endsWith(".json");

  if (isPage || isJson) {
    event.respondWith(networkFirst(request, url));
  } else if (isCdn || isSameOrigin) {
    event.respondWith(cacheFirst(request));
  }
  // Anything else (e.g. the Yahoo live-quote fetch) goes straight to the
  // network untouched.
});
