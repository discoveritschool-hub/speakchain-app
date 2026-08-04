const CACHE = 'speakchain-shell-v2';
const SHELL = [
  './index_v2.html', './player.html', './vocab.html', './speaking_buddy.html',
  './progress.html', './tokens.css', './pwa.js', './manifest.webmanifest',
  './speakchain_logo_transparent.png'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  // Never cache backend data, Telegram resources, or YouTube. Pages must be
  // network-first: otherwise Telegram keeps an old player after a GitHub push.
  if (url.origin !== self.location.origin) return;
  event.respondWith(fetch(event.request).then(response => {
    if (!response.ok || response.type !== 'basic') return response;
    const copy = response.clone();
    caches.open(CACHE).then(cache => cache.put(event.request, copy));
    return response;
  }).catch(() => caches.match(event.request).then(cached => cached || caches.match('./index_v2.html'))));
});
