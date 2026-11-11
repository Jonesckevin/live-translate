/* Live Translate - Service Worker
 *
 * Strategy:
 *  - Precache the app shell (HTML + static assets) so the UI loads instantly
 *    and works as an installed app.
 *  - Navigations (HTML) are network-first with an offline fallback to the
 *    cached shell, so users always get the latest UI when online.
 *  - Static assets are cache-first (stale-while-revalidate) for speed.
 *  - API / Socket.IO requests are NEVER cached: they are server-backed and
 *    require authentication, so caching them could leak data across users.
 */

// Substituted with the app's ASSET_VERSION when served from /sw.js (app.py).
// Bumping ASSET_VERSION changes CACHE_NAME, which is what forces browsers to
// refetch static assets that would otherwise be served cache-first.
// Keep the `v` prefix: this becomes `live-translate-v<version>`.
const VERSION = 'v__ASSET_VERSION__';
const CACHE_NAME = `live-translate-${VERSION}`;

// Core app shell. Keep in sync with templates/index.html script/style refs.
const PRECACHE_URLS = [
  '/',
  '/static/style.css?v=__ASSET_VERSION__',
  '/static/icons.js?v=__ASSET_VERSION__',
  '/static/app.js?v=__ASSET_VERSION__',
  '/static/socket.io.min.js?v=__ASSET_VERSION__',
  '/static/api-manager.js?v=__ASSET_VERSION__',
  '/static/auth-widget.js?v=__ASSET_VERSION__',
  '/static/keyboard-manager.js?v=__ASSET_VERSION__',
  '/static/live-view.js?v=__ASSET_VERSION__',
  '/static/speech-manager.js?v=__ASSET_VERSION__',
  '/static/manifest.json?v=__ASSET_VERSION__',
  '/static/icons/icon-192.png?v=__ASSET_VERSION__',
  '/static/icons/icon-512.png?v=__ASSET_VERSION__',
  '/static/icons/icon-maskable-512.png?v=__ASSET_VERSION__',
];

// Requests to these path prefixes must never be served from cache.
const NETWORK_ONLY_PREFIXES = ['/api/', '/socket.io/', '/auth/'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith('live-translate-') && key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;

  // Only handle GET requests.
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never cache authenticated/API traffic.
  if (NETWORK_ONLY_PREFIXES.some((p) => url.pathname.startsWith(p))) {
    return;
  }

  // Navigations: network-first, fall back to cached shell when offline.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put('/', copy));
          return response;
        })
        .catch(() =>
          caches.match('/').then((cached) => cached || caches.match(request))
        )
    );
    return;
  }

  // Static assets: cache-first (stale-while-revalidate).
  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((response) => {
          if (response && response.status === 200 && response.type === 'basic') {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
