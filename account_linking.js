(function () {
  'use strict';

  const BUILD_ENABLED = window.SC_ACCOUNT_LINKING_BUILD_ENABLED === true;
  const INTENT_PATH = '/api/v1/account-link/intents';
  const COMPLETE_PATH = '/api/v1/account-link/complete';
  const CONFIG_ENABLED_KEY = 'account_linking_enabled';
  const PROVIDERS = new Set(['google', 'telegram']);
  const state = {
    mounted: false, source: '', target: '', token: '', expiresAt: 0,
    completing: false, completed: false, retryPayload: null, timer: null,
  };

  const copy = {
    linking_unavailable: 'Повторно увійдіть у поточний акаунт і спробуйте ще раз.',
    invalid_intent: 'Цей запит недійсний. Почніть підключення ще раз.',
    intent_expired: 'Час підтвердження минув. Почніть підключення ще раз.',
    cross_user_rejected: 'Цей запит належить іншій сесії. Почніть у своєму акаунті.',
    target_identity_mismatch: 'Підтверджений акаунт не відповідає цьому запиту.',
    identity_conflict: 'Один з акаунтів уже пов’язаний з іншим профілем.',
    already_linked: 'Ці акаунти вже пов’язані. Дані не змінено.',
    profile_too_large: 'Для цього профілю потрібна допомога підтримки.',
    persistence_unavailable: 'Сервіс тимчасово недоступний. Можна безпечно повторити.',
    account_link_timeout: 'Відповідь не отримано. Можна безпечно повторити цей самий запит.',
  };

  function providerName(provider) {
    return provider === 'google' ? 'Google' : provider === 'telegram' ? 'Telegram' : '';
  }
  function element(id) { return document.getElementById(id); }
  function setText(id, value) {
    const node = element(id);
    if (node) node.textContent = String(value || '').slice(0, 240);
  }
  function setStatus(message, kind) {
    const status = element('account-link-status');
    if (!status) return;
    status.textContent = String(message || '').slice(0, 240);
    status.className = 'account-link-status' + (kind ? ' ' + kind : '');
  }
  function clearIntent() {
    state.token = '';
    state.expiresAt = 0;
    state.retryPayload = null;
    state.completing = false;
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
  }
  function resetFlow(message) {
    clearIntent();
    const consent = element('account-link-consent');
    if (consent) consent.checked = false;
    const verify = element('account-link-verify');
    if (verify) verify.hidden = true;
    const start = element('account-link-start');
    if (start) { start.hidden = false; start.disabled = true; }
    if (message) setStatus(message, 'error');
  }
  function updateExpiry() {
    if (!state.expiresAt) return;
    const seconds = Math.max(0, Math.ceil((state.expiresAt - Date.now()) / 1000));
    setText('account-link-expiry', seconds ? `Підтвердьте протягом ${seconds} с.` : 'Час підтвердження минув.');
    if (!seconds) resetFlow(copy.intent_expired);
  }
  function definiteError(code, status) {
    return status === 404 || ['invalid_intent', 'intent_expired', 'cross_user_rejected',
      'target_identity_mismatch', 'identity_conflict', 'already_linked', 'profile_too_large',
      'linking_unavailable'].includes(code);
  }
  function friendly(error) {
    return copy[error?.code] || (error?.status === 404
      ? 'Підключення акаунтів ще не доступне.'
      : 'Не вдалося завершити підключення. Спробуйте ще раз.');
  }

  async function createIntent() {
    if (state.token || state.completing || state.completed) return;
    const consent = element('account-link-consent');
    if (!consent?.checked) {
      setStatus('Підтвердьте згоду перед продовженням.', 'error');
      return;
    }
    const button = element('account-link-start');
    if (button) button.disabled = true;
    setStatus('Створюємо захищений запит…');
    try {
      const result = await window.SC_PWA.authenticatedPost(INTENT_PATH, {
        target_provider: state.target, consent: true,
      }, {timeout: 15000});
      if (!result?.ok || typeof result.link_token !== 'string' || !result.link_token ||
          result.target_provider !== state.target) throw new Error('invalid response');
      state.token = result.link_token;
      const ttl = Number(result.expires_in);
      state.expiresAt = Date.now() + (Number.isFinite(ttl) && ttl > 0 ? Math.min(ttl, 600) : 600) * 1000;
      if (button) button.hidden = true;
      const verify = element('account-link-verify');
      if (verify) verify.hidden = false;
      setStatus(`Запит створено. Підтвердьте ${providerName(state.target)}; профілі ще не об’єднано.`);
      renderTargetVerification();
      updateExpiry();
      state.timer = setInterval(updateExpiry, 1000);
    } catch (error) {
      if (error?.status === 404) {
        const card = element('account-linking-card');
        if (card) card.hidden = true;
      }
      setStatus(friendly(error), 'error');
      if (button) button.disabled = false;
    }
  }

  function renderTargetVerification() {
    const host = element('account-link-provider-control');
    if (!host) return;
    host.replaceChildren();
    if (state.target === 'google') {
      const buttonHost = document.createElement('div');
      buttonHost.id = 'account-link-google';
      host.appendChild(buttonHost);
      renderGoogleTarget(buttonHost, 0);
      return;
    }
    const fallback = document.createElement('button');
    fallback.type = 'button';
    fallback.className = 'account-link-provider-button';
    fallback.textContent = 'Підтвердити Telegram';
    fallback.disabled = true;
    fallback.setAttribute('aria-describedby', 'account-link-status');
    host.appendChild(fallback);
    window.SC_PWA.config().then(config => {
      const username = String(config?.telegram_bot_username || '').replace(/^@/, '');
      if (!/^[A-Za-z0-9_]{5,32}$/.test(username)) {
        setStatus('Telegram-підтвердження ще не налаштовано.', 'error');
        return;
      }
      const script = document.createElement('script');
      script.async = true;
      script.src = 'https://telegram.org/js/telegram-widget.js?22';
      script.setAttribute('data-telegram-login', username);
      script.setAttribute('data-size', 'large');
      script.setAttribute('data-radius', '12');
      script.setAttribute('data-userpic', 'false');
      script.setAttribute('data-request-access', 'write');
      script.setAttribute('data-onauth', 'SC_ACCOUNT_LINKING.telegramTarget(user)');
      host.replaceChildren(script);
    }).catch(() => setStatus('Telegram-підтвердження тимчасово недоступне.', 'error'));
  }

  function renderGoogleTarget(host, attempt) {
    if (!state.token || state.target !== 'google') return;
    if (!window.google?.accounts?.id) {
      if (attempt < 40) setTimeout(() => renderGoogleTarget(host, attempt + 1), 150);
      else setStatus('Google-підтвердження тимчасово недоступне.', 'error');
      return;
    }
    window.SC_PWA.config().then(config => {
      const clientId = String(config?.google_client_id || '');
      if (!clientId) throw new Error('not configured');
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: response => complete({credential: String(response?.credential || '')}),
        auto_select: false,
      });
      const width = Math.max(220, Math.min(340, Math.floor(host.getBoundingClientRect().width || 280)));
      window.google.accounts.id.renderButton(host, {
        theme: 'filled_black', size: 'large', shape: 'pill', width, text: 'continue_with',
      });
    }).catch(() => setStatus('Google-підтвердження ще не налаштовано.', 'error'));
  }

  async function complete(targetProof) {
    if (!state.token || state.completed || state.completing) return;
    const proof = targetProof && typeof targetProof === 'object' ? targetProof : {};
    const validGoogle = state.target === 'google' && typeof proof.credential === 'string' && proof.credential.length > 0;
    const validTelegram = state.target === 'telegram' && proof.telegram_user && typeof proof.telegram_user === 'object';
    if (!validGoogle && !validTelegram) {
      setStatus(`Не вдалося підтвердити ${providerName(state.target)}.`, 'error');
      return;
    }
    state.completing = true;
    state.retryPayload = Object.assign({link_token: state.token},
      validGoogle ? {credential: proof.credential} : {telegram_user: proof.telegram_user});
    const retry = element('account-link-retry');
    if (retry) retry.hidden = true;
    setStatus('Перевіряємо обидва акаунти. Дані ще не змінено…');
    try {
      const result = await window.SC_PWA.authenticatedPost(COMPLETE_PATH, state.retryPayload, {timeout: 20000});
      if (!result?.ok || !['merged', 'already_linked'].includes(String(result.outcome || ''))) {
        throw new Error('invalid response');
      }
      state.completed = true;
      clearIntent();
      const verify = element('account-link-verify');
      if (verify) verify.hidden = true;
      const consent = element('account-link-consent');
      if (consent) consent.disabled = true;
      setStatus(result.outcome === 'already_linked'
        ? 'Сервер підтвердив: ці акаунти вже були пов’язані.'
        : 'Сервер підтвердив підключення. Прогрес доступний з обох способів входу.', 'success');
    } catch (error) {
      state.completing = false;
      const canRetry = !definiteError(error?.code, error?.status);
      setStatus(friendly(error), 'error');
      if (canRetry) {
        if (retry) retry.hidden = false;
      } else {
        resetFlow(friendly(error));
      }
    }
  }

  function retryCompletion() {
    if (!state.retryPayload || state.completing || !state.token) return;
    const proof = state.target === 'google'
      ? {credential: state.retryPayload.credential}
      : {telegram_user: state.retryPayload.telegram_user};
    complete(proof);
  }

  function buildCard() {
    const slot = element('account-linking-slot');
    if (!slot || state.mounted) return;
    state.mounted = true;
    slot.hidden = false;
    const card = document.createElement('section');
    card.id = 'account-linking-card';
    card.className = 'account-linking-card';
    card.setAttribute('aria-labelledby', 'account-link-title');
    card.innerHTML = '<h3 id="account-link-title">Способи входу</h3>'
      + '<p class="account-link-identities"><span>Поточний вхід: <strong id="account-link-source"></strong></span><span>Додати: <strong id="account-link-target"></strong></span></p>'
      + '<p class="account-link-note">SpeakChain перевірить обидва акаунти. Профілі зміняться лише після відповіді сервера; скасування або помилка не означають об’єднання. Якщо безпечне збереження не завершиться, сервер відкотить операцію.</p>'
      + '<label class="account-link-consent"><input id="account-link-consent" type="checkbox"> <span>Я підтверджую, що обидва акаунти належать мені, і погоджуюся об’єднати прогрес та підписку.</span></label>'
      + '<button id="account-link-start" class="account-link-primary" type="button" disabled>Почати безпечне підключення</button>'
      + '<div id="account-link-verify" hidden><p id="account-link-expiry" class="account-link-expiry"></p><div id="account-link-provider-control"></div><button id="account-link-retry" class="account-link-secondary" type="button" hidden>Безпечно повторити</button></div>'
      + '<p id="account-link-status" class="account-link-status" role="status" aria-live="polite" aria-atomic="true">Акаунти ще не пов’язані.</p>';
    slot.appendChild(card);
    setText('account-link-source', providerName(state.source));
    setText('account-link-target', providerName(state.target));
    element('account-link-consent')?.addEventListener('change', event => {
      const button = element('account-link-start');
      if (button) button.disabled = !event.target.checked || Boolean(state.token);
    });
    element('account-link-start')?.addEventListener('click', createIntent);
    element('account-link-retry')?.addEventListener('click', retryCompletion);
  }

  async function init() {
    if (!BUILD_ENABLED || !window.SC_PWA?.config || !window.SC_PWA?.authenticatedPost) return;
    try {
      await window.SC_PWA.ready;
      const config = await window.SC_PWA.config();
      if (config?.[CONFIG_ENABLED_KEY] !== true) return;
      state.source = String(window.SC_PWA.provider?.() || '').toLowerCase();
      if (!PROVIDERS.has(state.source) || !window.SC_PWA.hasSession?.()) return;
      state.target = state.source === 'google' ? 'telegram' : 'google';
      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', buildCard, {once: true});
      else buildCard();
    } catch (_) {}
  }

  window.SC_ACCOUNT_LINKING = Object.freeze({
    init,
    googleTarget: response => complete({credential: String(response?.credential || '')}),
    telegramTarget: user => complete({telegram_user: user}),
    retry: retryCompletion,
  });
  init();
})();
