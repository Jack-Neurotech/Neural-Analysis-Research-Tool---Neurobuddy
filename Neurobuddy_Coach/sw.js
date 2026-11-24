/* Neurobuddy app-shell cache. Never deletes IndexedDB or OPFS research data. */
const CACHE = 'neurobuddy-shell-v1';
const PRECACHE = [
  './',
  './index.html',
  './Index.html',
  './manifest.webmanifest',
  './v2/styles.css',
  './v2/app.js',
  './v2/shelf-ui.js',
  './v2/browser-store.js',
  './v2/browser-api.js',
  './v2/pyodide-worker.js',
  './pyodide/python-modules.json',
  './pyodide/pinned-packages.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await Promise.all(PRECACHE.map((url) => cache.add(url).catch(() => null)));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith('neurobuddy-shell-') && key !== CACHE).map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.pathname.includes('/api/')) return;
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return;
  event.respondWith((async () => {
    const cached = await caches.match(request);
    try {
      const response = await fetch(request);
      if (response.ok && url.origin === self.location.origin) {
        const cache = await caches.open(CACHE);
        cache.put(request, response.clone());
      }
      return response;
    } catch {
      if (cached) return cached;
      throw new Error('Offline and uncached');
    }
  })());
});
