(function () {
  'use strict';

  const API_FALLBACK = 'https://speakchain-bot-production.up.railway.app';
  const ACCESS_KEY = 'speakchain.pwa.access.v1';
  const REFRESH_KEY = 'speakchain.pwa.refresh.v1';
  const EXP_KEY = 'speakchain.pwa.access.exp.v1';
  const nativeFetch = window.fetch.bind(window);
  let installPrompt = null;

  function apiBase() {
    try { if (typeof BOT_API !== 'undefined' && BOT_API) return String(BOT_API).replace(/\/$/, ''); } catch (_) {}
    return API_FALLBACK;
  }
  function read(key) { try { return localStorage.getItem(key) || ''; } catch (_) { return ''; } }
  function writeSession(data) {
    try {
      if (data.access_token) localStorage.setItem(ACCESS_KEY, data.access_token);
      if (data.refresh_token) localStorage.setItem(REFRESH_KEY, data.refresh_token);
      if (data.expires_at) localStorage.setItem(EXP_KEY, data.expires_at);
    } catch (_) {}
  }
  function accessValid() {
    const exp = Date.parse(read(EXP_KEY));
    return Boolean(read(ACCESS_KEY) && Number.isFinite(exp) && exp > Date.now() + 30000);
  }
  async function jsonPost(path, body) {
    const response = await nativeFetch(apiBase() + path, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    });
    if (!response.ok) throw new Error('session_' + response.status);
    return response.json();
  }
  async function ensureSession() {
    const tg = window.Telegram?.WebApp;
    const initData = tg?.initData || '';
    try {
      if (initData) {
        const data = await jsonPost('/api/v1/session', {init_data: initData});
        writeSession(data);
        return {authenticated: true, source: 'telegram'};
      }
      if (accessValid()) return {authenticated: true, source: 'pwa'};
      const refreshToken = read(REFRESH_KEY);
      if (refreshToken) {
        const data = await jsonPost('/api/v1/session/refresh', {refresh_token: refreshToken});
        writeSession(data);
        return {authenticated: true, source: 'refresh'};
      }
    } catch (_) {}
    return {authenticated: Boolean(initData), source: initData ? 'telegram-legacy' : 'none'};
  }

  // Existing endpoints are migrated without duplicating every call site.
  // Only cross-origin JSON POSTs to the SpeakChain API are enriched; static
  // assets, YouTube, Telegram and third-party requests are untouched.
  window.fetch = async function(input, init) {
    let next = init ? Object.assign({}, init) : {};
    let enriched = false;
    try {
      const url = new URL(typeof input === 'string' ? input : input.url, location.href);
      const method = String(next.method || (typeof input !== 'string' && input.method) || 'GET').toUpperCase();
      const contentType = new Headers(next.headers || (typeof input !== 'string' ? input.headers : undefined)).get('Content-Type') || '';
      if (method === 'POST' && url.origin === new URL(apiBase()).origin && contentType.includes('application/json') && typeof next.body === 'string') {
        const body = JSON.parse(next.body);
        if (!body.init_data && !body.pwa_access_token && read(ACCESS_KEY)) {
          body.pwa_access_token = read(ACCESS_KEY);
          next.body = JSON.stringify(body);
          enriched = true;
        }
      }
    } catch (_) {}
    let response = await nativeFetch(input, next);
    if (response.status === 401 && enriched && read(REFRESH_KEY)) {
      const refreshed = await ensureSession();
      if (refreshed.authenticated && read(ACCESS_KEY)) {
        try {
          const body = JSON.parse(next.body);
          body.pwa_access_token = read(ACCESS_KEY);
          next.body = JSON.stringify(body);
          response = await nativeFetch(input, next);
        } catch (_) {}
      }
    }
    return response;
  };

  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault(); installPrompt = event;
    window.dispatchEvent(new CustomEvent('speakchain-install-ready'));
  });
  window.addEventListener('appinstalled', () => { installPrompt = null; });

  async function install() {
    if (installPrompt) {
      installPrompt.prompt();
      const choice = await installPrompt.userChoice.catch(() => null);
      if (choice?.outcome === 'accepted') installPrompt = null;
      return Boolean(choice?.outcome === 'accepted');
    }
    return false;
  }

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', async () => {
      try {
        const registration = await navigator.serviceWorker.register('./sw.js');
        registration.update().catch(() => {});
        registration.addEventListener('updatefound', () => {
          const worker = registration.installing;
          worker?.addEventListener('statechange', () => {
            if (worker.state === 'installed' && navigator.serviceWorker.controller) {
              window.dispatchEvent(new CustomEvent('speakchain-update-ready', {detail:{registration}}));
            }
          });
        });
      } catch (_) {}
    });
  }

  window.SC_PWA = {
    ready: ensureSession(), install,
    isStandalone: () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true,
    hasSession: accessValid,
    refresh: ensureSession,
  };
})();
