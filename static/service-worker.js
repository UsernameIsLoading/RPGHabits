const CACHE_NAME = 'rpg-habitos-shell-v4';
const CORE = [
  '/static/style.css', '/static/app.js', '/static/manifest.json',
  '/static/icon-192.svg', '/static/icon-512.svg', '/static/offline.html',
  '/static/sprites/guardiao.svg', '/static/sprites/sentinela.svg', '/static/sprites/lutador.svg',
  '/static/sprites/duelista.svg', '/static/sprites/invocador.svg', '/static/sprites/arcanista.svg',
  '/static/sprites/monge.svg', '/static/sprites/explorador.svg'
];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(async cache => {
    await cache.addAll(CORE);
    // Cache the current route as well, so the PWA has an HTML entry point offline after the first install.
    try { await cache.add('/'); } catch { /* The static offline page remains the fallback. */ }
  }));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('rpg-habitos-shell-') && key !== CACHE_NAME).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('message', event => {
  if (event.data?.type === 'ACTIVATE_UPDATE') self.skipWaiting();
});
self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return; // API data is stored in IndexedDB by app.js, never in Cache Storage.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(caches.match(req).then(cached => cached || fetch(req).then(res => {
      if (res.ok) caches.open(CACHE_NAME).then(cache => cache.put(req, res.clone()));
      return res;
    })));
    return;
  }
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).then(res => {
      if (res.ok && url.pathname === '/') caches.open(CACHE_NAME).then(cache => cache.put('/', res.clone()));
      return res;
    }).catch(async () => (await caches.match('/')) || (await caches.match('/static/offline.html'))));
  }
});
