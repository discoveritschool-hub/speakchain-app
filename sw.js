const CACHE = 'speakchain-shell-v19';
const SHELL = [
  './index_v2.html', './telegram_auth_callback.html', './offline.html', './player.html', './vocab.html', './speaking_buddy.html',
  './progress.html', './tokens.css', './pwa.js', './chainy_memory.js', './chainy_interest.js', './manifest.webmanifest',
  './icon-192.png', './icon-512.png', './Chainy.png', './toast_rewards.js'
];
const SHELL_PATHS = new Set(SHELL.map(path => new URL(path, self.location.href).pathname));

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('message', event => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request).catch(() => caches.match('./index_v2.html').then(r => r || caches.match('./offline.html'))));
    return;
  }
  // Cache a fixed public shell only. Query-bearing URLs can contain lesson or
  // user handoff data and must never become a shared browser cache entry.
  if (!SHELL_PATHS.has(url.pathname) || url.search) return;
  event.respondWith(caches.match(event.request).then(cached => {
    const fresh = fetch(event.request).then(response => {
      if (response.ok && response.type === 'basic') caches.open(CACHE).then(cache => cache.put(event.request, response.clone()));
      return response;
    }).catch(() => cached);
    return cached || fresh;
  }));
});
