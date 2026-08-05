(function () {
  'use strict';

  const API_FALLBACK = 'https://speakchain-bot-production.up.railway.app';
  const ACCESS_KEY = 'speakchain.pwa.access.v1';
  const REFRESH_KEY = 'speakchain.pwa.refresh.v1';
  const EXP_KEY = 'speakchain.pwa.access.exp.v1';
  const USER_KEY = 'speakchain.pwa.user.v1';
  const nativeFetch = window.fetch.bind(window);
  let installPrompt = null;
  let authResolve = null;
  let authPromise = null;
  let authConfig = null;

  function apiBase() {
    try { if (window.SC_BOT_API) return String(window.SC_BOT_API).replace(/\/$/, ''); } catch (_) {}
    return API_FALLBACK;
  }
  function read(key) { try { return localStorage.getItem(key) || ''; } catch (_) { return ''; } }
  function writeSession(data) {
    try {
      if (data.access_token) localStorage.setItem(ACCESS_KEY, data.access_token);
      if (data.refresh_token) localStorage.setItem(REFRESH_KEY, data.refresh_token);
      if (data.expires_at) localStorage.setItem(EXP_KEY, data.expires_at);
      if (data.user_id) localStorage.setItem(USER_KEY, String(data.user_id));
    } catch (_) {}
  }
  function clearSession() {
    try { [ACCESS_KEY, REFRESH_KEY, EXP_KEY, USER_KEY].forEach(key => localStorage.removeItem(key)); } catch (_) {}
  }
  function accessValid() {
    const exp = Date.parse(read(EXP_KEY));
    return Boolean(read(ACCESS_KEY) && read(USER_KEY) && Number.isFinite(exp) && exp > Date.now() + 30000);
  }
  function hasTrustedEmbeddedPayload() {
    try {
      const page = location.pathname.split('/').pop().toLowerCase();
      return page === 'blogger.html' && new URLSearchParams(location.search).has('d');
    } catch (_) { return false; }
  }
  async function jsonPost(path, body, options) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), Number(options?.timeout || 15000));
    let response;
    try {
      response = await nativeFetch(apiBase() + path, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body || {}), signal: controller.signal
      });
    } catch (error) {
      const unavailable = new Error(error?.name === 'AbortError'
        ? 'Сервер входу не відповідає. Спробуйте ще раз.'
        : 'Немає звʼязку із сервером входу.');
      unavailable.code = error?.name === 'AbortError' ? 'session_timeout' : 'session_network';
      throw unavailable;
    } finally {
      clearTimeout(timeout);
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data?.error?.message || ('session_' + response.status));
      error.code = data?.error?.code || ('session_' + response.status);
      throw error;
    }
    return data;
  }
  async function sessionFromTelegramMiniApp() {
    const initData = window.Telegram?.WebApp?.initData || '';
    if (!initData) return null;
    const data = await jsonPost('/api/v1/session', {init_data: initData});
    writeSession(data);
    return {authenticated: true, source: 'telegram', userId: Number(data.user_id)};
  }
  async function restoreSession() {
    try {
      const telegram = await sessionFromTelegramMiniApp();
      if (telegram) return telegram;
      if (accessValid()) return {authenticated: true, source: 'pwa', userId: Number(read(USER_KEY))};
      const refreshToken = read(REFRESH_KEY);
      if (refreshToken) {
        const data = await jsonPost('/api/v1/session/refresh', {refresh_token: refreshToken});
        writeSession(data);
        return {authenticated: true, source: 'refresh', userId: Number(data.user_id || read(USER_KEY))};
      }
    } catch (_) {
      if (!window.Telegram?.WebApp?.initData) clearSession();
    }
    return {authenticated: false, source: 'none', userId: 0};
  }

  function authStatus(message, bad) {
    const el = document.getElementById('sc-auth-status');
    if (!el) return;
    el.textContent = message || '';
    el.style.color = bad ? '#f76e6e' : '#8888a8';
  }
  function finishAuth(data, source) {
    writeSession(data);
    document.getElementById('sc-auth-gate')?.remove();
    const result = {authenticated: true, source, userId: Number(data.user_id)};
    if (authResolve) authResolve(result);
    authResolve = null;
    return result;
  }
  async function telegramLogin(user) {
    authStatus('Перевіряємо Telegram…');
    try {
      return finishAuth(await jsonPost('/api/v1/session/telegram', {user}), 'telegram-login');
    } catch (error) {
      authStatus(error.message || 'Не вдалося увійти через Telegram.', true);
      throw error;
    }
  }
  async function googleLogin(response) {
    authStatus('Перевіряємо Google…');
    try {
      if (!response?.credential) throw new Error('Google не передав дані акаунта. Спробуйте ще раз.');
      return finishAuth(await jsonPost('/api/v1/session/google', {credential: response?.credential || ''}), 'google');
    } catch (error) {
      authStatus(error.message || 'Не вдалося увійти через Google.', true);
      throw error;
    }
  }
  function renderGoogleButton(clientId, attempt) {
    const host = document.getElementById('sc-google-login');
    if (!host) return;
    if (!clientId) {
      host.innerHTML = '<button class="sc-auth-disabled" disabled>Google — завершуємо налаштування</button>';
      return;
    }
    if (!window.google?.accounts?.id) {
      if ((attempt || 0) < 40) setTimeout(() => renderGoogleButton(clientId, (attempt || 0) + 1), 150);
      else authStatus('Google тимчасово не завантажився. Спробуйте Telegram.', true);
      return;
    }
    window.google.accounts.id.initialize({client_id: clientId, callback: googleLogin, auto_select: false});
    const availableWidth = Math.max(220, Math.min(360, Math.floor(host.getBoundingClientRect().width || 300)));
    window.google.accounts.id.renderButton(host, {theme: 'filled_black', size: 'large', shape: 'pill', width: availableWidth, text: 'continue_with'});
  }
  function renderTelegramButton(username) {
    const host = document.getElementById('sc-telegram-login');
    if (!host || !username) return;
    window.SC_PWA.telegramLogin = telegramLogin;
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://telegram.org/js/telegram-widget.js?22';
    script.setAttribute('data-telegram-login', username.replace(/^@/, ''));
    script.setAttribute('data-size', 'large');
    script.setAttribute('data-radius', '12');
    script.setAttribute('data-userpic', 'false');
    script.setAttribute('data-request-access', 'write');
    script.setAttribute('data-onauth', 'SC_PWA.telegramLogin(user)');
    host.replaceChildren(script);
  }
  async function showAuthGate() {
    if (authPromise) return authPromise;
    authPromise = new Promise(resolve => { authResolve = resolve; });
    const mount = async () => {
      if (document.getElementById('sc-auth-gate')) return;
      let config = {};
      let configError = null;
      try { config = await jsonPost('/api/v1/session/config', {}, {timeout: 12000}); } catch (error) { configError = error; }
      authConfig = config;
      const gate = document.createElement('div');
      gate.id = 'sc-auth-gate';
      gate.innerHTML = '<style>\n'
        + '#sc-auth-gate{position:fixed;inset:0;z-index:10000;background:#0d0d14;color:#eaeaf5;display:grid;place-items:center;padding:clamp(12px,3vw,32px);font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display",sans-serif;overflow:auto}\n'
        + '.sc-auth-card{width:min(100%,420px);background:#16161f;border:1px solid #2a2a3a;border-radius:clamp(18px,3vw,24px);padding:clamp(20px,4vh,32px) clamp(16px,3vw,28px);text-align:center;box-shadow:0 20px 70px rgba(0,0,0,.45)}\n'
        + '.sc-auth-logo{width:72px;height:72px;border-radius:20px;margin-bottom:16px}.sc-auth-card h1{font-size:25px;margin:0 0 8px}.sc-auth-card p{font-size:14px;line-height:1.5;color:#8888a8;margin:0 0 22px}\n'
        + '.sc-auth-provider{width:100%;min-height:44px;display:flex;justify-content:center;align-items:center;margin:10px 0}.sc-auth-provider>div,.sc-auth-provider iframe{max-width:100%!important}.sc-auth-disabled{width:min(100%,360px);min-height:44px;padding:10px 16px;border:1px solid #2a2a3a;border-radius:999px;background:#1e1e2a;color:#8888a8;font-weight:700}\n'
        + '.sc-auth-divider{display:flex;align-items:center;gap:10px;color:#5a5a72;font-size:12px;margin:12px 0}.sc-auth-divider:before,.sc-auth-divider:after{content:"";height:1px;background:#2a2a3a;flex:1}\n'
        + '#sc-auth-status{min-height:20px;margin-top:13px;font-size:12px}.sc-auth-note{font-size:11px!important;margin:15px 0 0!important;color:#5a5a72!important}\n'
        + '</style><div class="sc-auth-card"><img class="sc-auth-logo" src="icon-192.png" alt="SpeakChain"><h1>Увійдіть у SpeakChain</h1><p>Ваш прогрес, Chain і підписка залишаться з вами в браузері та застосунку.</p><div id="sc-google-login" class="sc-auth-provider"></div><div class="sc-auth-divider">або</div><div id="sc-telegram-login" class="sc-auth-provider"></div><div id="sc-auth-status"></div><p class="sc-auth-note">Вже користувалися SpeakChain у Telegram? Оберіть Telegram, щоб відкрити той самий профіль.</p></div>';
      document.body.appendChild(gate);
      renderGoogleButton(config.google_client_id || '', 0);
      renderTelegramButton(config.telegram_bot_username || 'SpeakChain_bot');
      if (configError) authStatus(configError.message || 'Сервер входу тимчасово недоступний. Оновіть сторінку й спробуйте ще раз.', true);
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
    else mount();
    return authPromise;
  }
  async function ensureSession() {
    // Telegram opens blogger.html with a backend-built payload in `d`.
    // It must not be covered a moment later by the generic browser login.
    // Direct browser/admin opens have no `d` and keep the signed role check.
    if (hasTrustedEmbeddedPayload()) {
      return {authenticated: true, source: 'telegram-payload', userId: 0};
    }
    const restored = await restoreSession();
    if (restored.authenticated) return restored;
    return showAuthGate();
  }

  window.fetch = async function(input, init) {
    let next = init ? Object.assign({}, init) : {};
    let enriched = false;
    try {
      const url = new URL(typeof input === 'string' ? input : input.url, location.href);
      const method = String(next.method || (typeof input !== 'string' && input.method) || 'GET').toUpperCase();
      const headers = new Headers(next.headers || (typeof input !== 'string' ? input.headers : undefined));
      const contentType = headers.get('Content-Type') || '';
      if (method === 'POST' && url.origin === new URL(apiBase()).origin && contentType.includes('application/json') && typeof next.body === 'string') {
        const body = JSON.parse(next.body);
        if (!body.init_data && !body.pwa_access_token && read(ACCESS_KEY) && !url.pathname.startsWith('/api/v1/session')) {
          body.pwa_access_token = read(ACCESS_KEY);
          if (!body.uid && read(USER_KEY)) body.uid = Number(read(USER_KEY));
          next.body = JSON.stringify(body);
          enriched = true;
        }
      }
    } catch (_) {}
    let response = await nativeFetch(input, next);
    if (response.status === 401 && enriched && read(REFRESH_KEY)) {
      const refreshed = await restoreSession();
      if (refreshed.authenticated && read(ACCESS_KEY)) {
        try {
          const body = JSON.parse(next.body);
          body.pwa_access_token = read(ACCESS_KEY);
          body.uid = Number(read(USER_KEY)) || body.uid;
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
    if (!installPrompt) return false;
    installPrompt.prompt();
    const choice = await installPrompt.userChoice.catch(() => null);
    if (choice?.outcome === 'accepted') installPrompt = null;
    return Boolean(choice?.outcome === 'accepted');
  }
  function logout() { clearSession(); location.reload(); }

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', async () => {
      try {
        const registration = await navigator.serviceWorker.register('./sw.js');
        registration.update().catch(() => {});
      } catch (_) {}
    });
  }

  window.SC_PWA = {
    ready: ensureSession(), install, logout, telegramLogin, googleLogin,
    isStandalone: () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true,
    hasSession: accessValid,
    refresh: ensureSession,
    userId: () => Number(read(USER_KEY)) || 0,
  };
})();
