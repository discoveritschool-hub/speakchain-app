// v45 consolidates live lessons on the canonical production API.
const CACHE = 'speakchain-shell-v45';
const SHELL = [
  './index_v2.html', './telegram_auth_callback.html', './offline.html', './player.html', './vocab.html', './speaking_buddy.html',
  './progress.html', './tokens.css', './pwa.js', './api_client.js', './account_linking.js', './notification_center.js', './chainy_memory.js', './chainy_interest.js', './player_seek.js', './manifest.webmanifest',
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
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) {}
  event.waitUntil(self.registration.showNotification(data.title || 'SpeakChain', {
    body: data.body || '', icon: './icon-192.png', badge: './icon-192.png',
    tag: 'speakchain-' + (data.kind || 'info'), data: {url: data.url || './index_v2.html?s=s-home'},
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || './index_v2.html?s=s-home', self.location.href).href;
  event.waitUntil(clients.matchAll({type: 'window', includeUncontrolled: true}).then(list => {
    const existing = list.find(client => client.url.startsWith(self.location.origin));
    return existing ? existing.focus().then(() => existing.navigate(target)) : clients.openWindow(target);
  }));
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
