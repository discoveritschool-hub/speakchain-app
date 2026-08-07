(function () {
  'use strict';

  const API_FALLBACK = 'https://speakchain-bot-production.up.railway.app';
  const ACCESS_KEY = 'speakchain.pwa.access.v1';
  const TOPIC_KEY = /^[a-z0-9][a-z0-9_.:-]{0,63}$/;
  const PREFERENCES = ['like', 'dislike', 'avoid', 'neutral'];
  const state = {
    enabled: false,
    busy: false,
    catalog: [],
    recommended: null,
    selectedKey: '',
    pendingCustomTopic: '',
  };

  function el(id) { return document.getElementById(id); }
  function apiBase() {
    try { return String(window.SC_BOT_API || API_FALLBACK).replace(/\/$/, ''); }
    catch (_) { return API_FALLBACK; }
  }
  function pwaToken() {
    try { return localStorage.getItem(ACCESS_KEY) || ''; }
    catch (_) { return ''; }
  }
  function authPayload() {
    const initData = window.Telegram?.WebApp?.initData || '';
    if (initData) return { init_data: initData };
    const token = pwaToken();
    return token ? { pwa_access_token: token } : {};
  }
  function authHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    const initData = window.Telegram?.WebApp?.initData || '';
    const token = pwaToken();
    if (initData) headers['X-Telegram-Init-Data'] = initData;
    else if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
  }
  function safeTopic(item) {
    if (!item || typeof item !== 'object') return null;
    const topicKey = String(item.topic_key || '');
    const topicId = String(item.topic_id || '');
    const label = String(item.label_uk || '').trim();
    if (!TOPIC_KEY.test(topicKey) || !topicId || topicId.length > 128 || !label || label.length > 100) return null;
    return {
      topic_id: topicId,
      topic_key: topicKey,
      label_uk: label,
      eligible: item.eligible !== false,
      explicit: PREFERENCES.includes(item.explicit) ? item.explicit : '',
    };
  }
  function setStatus(message, isError) {
    const node = el('chainy-interest-status');
    if (!node) return;
    node.textContent = message || '';
    node.hidden = !message;
    node.classList.toggle('error', Boolean(isError));
  }
  function setBusy(busy) {
    state.busy = busy;
    document.querySelectorAll('#chainy-interest-panel button, #chainy-interest-panel input')
      .forEach(control => { control.disabled = busy; });
  }
  function errorMessage(error) {
    if (error?.name === 'AbortError') return 'Сервер не відповів вчасно. Спробуй ще раз.';
    if (error?.status === 401) return 'Увійди через Telegram або PWA, щоб керувати темами.';
    if (error?.status === 409 || error?.code === 'consent_required') return 'Спочатку увімкни пам’ять Chainy у налаштуваннях пам’яті.';
    if (error?.status === 429) return 'Забагато запитів. Спробуй трохи пізніше.';
    return 'Не вдалося оновити теми. Розмову можна почати без вибору.';
  }
  async function request(op, fields) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    let response;
    try {
      response = await fetch(apiBase() + '/chainy_interest', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify(Object.assign({ op }, fields || {}, authPayload())),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeout);
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data?.ok === false) {
      const code = typeof data?.error === 'string'
        ? data.error
        : data?.error?.code || data?.detail?.code || data?.code || '';
      const error = new Error('chainy_interest_failed');
      error.status = response.status;
      error.code = code;
      throw error;
    }
    return data;
  }
  function button(label, handler, options) {
    const control = document.createElement('button');
    control.type = 'button';
    control.className = `interest-btn${options?.className ? ` ${options.className}` : ''}`;
    control.textContent = label;
    if (options?.ariaLabel) control.setAttribute('aria-label', options.ariaLabel);
    if (options?.pressed !== undefined) control.setAttribute('aria-pressed', String(Boolean(options.pressed)));
    control.addEventListener('click', handler);
    return control;
  }
  function resetPreferences() {
    if (!window.confirm('Скинути всі адаптивні вподобання тем Chainy?')) return;
    state.selectedKey = '';
    mutate('reset', {}, 'Скидаємо вподобання…', 'Адаптивні вподобання скинуто.');
  }
  function renderConsentOff() {
    const box = el('chainy-interest-consent');
    const content = el('chainy-interest-content');
    if (!box || !content) return;
    box.hidden = false;
    content.hidden = true;
    box.replaceChildren();
    const copy = document.createElement('p');
    copy.className = 'interest-status';
    copy.textContent = 'Адаптивні теми доступні після явної згоди на пам’ять. До згоди приховані теми не показуються й не використовуються.';
    const open = button('Відкрити пам’ять Chainy', () => window.openChainyMemory?.(), {
      ariaLabel: 'Відкрити налаштування пам’яті Chainy',
    });
    const actions = document.createElement('div');
    actions.className = 'interest-actions';
    actions.append(open, button('Скинути приховані вподобання', resetPreferences, {
      className: 'danger',
      ariaLabel: 'Скинути адаптивні вподобання без увімкнення пам’яті',
    }));
    box.append(copy, actions);
  }
  function renderRecommendation() {
    const node = el('chainy-interest-recommended');
    if (!node) return;
    node.replaceChildren();
    const recommended = safeTopic(state.recommended);
    if (!recommended || !recommended.eligible || !state.catalog.some(item => item.topic_key === recommended.topic_key)) {
      node.hidden = true;
      return;
    }
    const label = document.createElement('span');
    label.textContent = `Рекомендована тема: ${recommended.label_uk}`;
    node.appendChild(label);
    node.hidden = false;
  }
  function chooseTopic(item) {
    if (state.busy || !item.eligible) return;
    state.selectedKey = item.topic_key;
    state.pendingCustomTopic = '';
    const input = el('chainy-interest-custom');
    if (input) input.value = '';
    renderCatalog();
    setStatus(`Обрано для наступної розмови: ${item.label_uk}`);
  }
  async function mutate(op, fields, pendingMessage, successMessage) {
    if (state.busy) return;
    setBusy(true);
    setStatus(pendingMessage);
    try {
      applyView(await request(op, fields));
      setStatus(successMessage || 'Готово.');
    } catch (error) {
      setStatus(errorMessage(error), true);
    } finally {
      setBusy(false);
    }
  }
  function preferenceLabel(value) {
    return { like: 'Подобається', dislike: 'Не моє', avoid: 'Не пропонувати', neutral: 'Нейтрально' }[value];
  }
  function renderCatalog() {
    const list = el('chainy-interest-catalog');
    if (!list) return;
    list.replaceChildren();
    const visible = state.catalog.filter(item => item.eligible);
    if (!visible.length) {
      const empty = document.createElement('p');
      empty.className = 'interest-status';
      empty.textContent = 'Наразі немає доступних рекомендацій. Можна почати з власної теми.';
      list.appendChild(empty);
      return;
    }
    visible.forEach(item => {
      const card = document.createElement('article');
      card.className = `interest-topic${state.selectedKey === item.topic_key ? ' selected' : ''}`;
      const top = document.createElement('div');
      top.className = 'interest-topic-row';
      const label = document.createElement('span');
      label.className = 'interest-topic-label';
      label.textContent = item.label_uk;
      const select = button(state.selectedKey === item.topic_key ? 'Обрано' : 'Обрати', () => chooseTopic(item), {
        className: state.selectedKey === item.topic_key ? 'primary' : '',
        ariaLabel: `Обрати тему: ${item.label_uk}`,
        pressed: state.selectedKey === item.topic_key,
      });
      top.append(label, select);
      const actions = document.createElement('div');
      actions.className = 'interest-actions';
      PREFERENCES.forEach(preference => {
        actions.appendChild(button(preferenceLabel(preference), () => {
          if (preference === 'avoid' && state.selectedKey === item.topic_key) state.selectedKey = '';
          mutate('prefer', { topic_key: item.topic_key, preference },
            'Зберігаємо оцінку…', 'Оцінку теми оновлено.');
        }, {
          ariaLabel: `${preferenceLabel(preference)}: ${item.label_uk}`,
          pressed: item.explicit === preference,
        }));
      });
      actions.appendChild(button('Видалити', () => {
        if (!window.confirm(`Видалити тему «${item.label_uk}» з адаптивних уподобань?`)) return;
        if (state.selectedKey === item.topic_key) state.selectedKey = '';
        mutate('delete', { topic_id: item.topic_id }, 'Видаляємо тему…', 'Тему видалено.');
      }, { className: 'danger', ariaLabel: `Видалити тему: ${item.label_uk}` }));
      card.append(top, actions);
      list.appendChild(card);
    });
  }
  function applyView(data) {
    state.enabled = Boolean(data?.enabled);
    if (!state.enabled) {
      state.catalog = [];
      state.recommended = null;
      state.selectedKey = '';
      renderConsentOff();
      setStatus('');
      return;
    }
    const catalog = Array.isArray(data?.catalog) ? data.catalog.map(safeTopic).filter(Boolean) : [];
    state.catalog = catalog;
    state.recommended = data?.selected_recommendation || null;
    const eligibleKeys = new Set(catalog.filter(item => item.eligible).map(item => item.topic_key));
    if (!eligibleKeys.has(state.selectedKey)) {
      const recommended = safeTopic(state.recommended);
      state.selectedKey = recommended && eligibleKeys.has(recommended.topic_key) ? recommended.topic_key : '';
    }
    const consent = el('chainy-interest-consent');
    const content = el('chainy-interest-content');
    if (consent) consent.hidden = true;
    if (content) content.hidden = false;
    renderRecommendation();
    renderCatalog();
    setStatus('');
  }
  async function load() {
    if (state.busy) return;
    setBusy(true);
    setStatus('Завантажуємо теми…');
    try {
      applyView(await request('view'));
    } catch (error) {
      state.catalog = [];
      state.recommended = null;
      state.selectedKey = '';
      const content = el('chainy-interest-content');
      if (content) content.hidden = true;
      setStatus(errorMessage(error), true);
    } finally {
      setBusy(false);
    }
  }
  function mount() {
    const panel = el('chainy-interest-panel');
    if (!panel) return;
    el('chainy-interest-custom-form')?.addEventListener('submit', event => {
      event.preventDefault();
      const input = el('chainy-interest-custom');
      const custom = String(input?.value || '').trim().replace(/\s+/g, ' ').slice(0, 120);
      if (custom.length < 2) {
        setStatus('Напиши тему хоча б двома символами.', true);
        input?.focus();
        return;
      }
      state.pendingCustomTopic = custom;
      state.selectedKey = '';
      setStatus('Власна тема діє лише в цій сесії й не зберігається як інтерес.');
      window.startChainyChat?.();
    });
    el('chainy-interest-reset')?.addEventListener('click', () => {
      resetPreferences();
    });
    load();
  }
  function attachSessionTopic(scenario) {
    if (!scenario || !scenario.isChainy || !state.pendingCustomTopic) return;
    scenario.customInterestTopic = state.pendingCustomTopic;
    state.pendingCustomTopic = '';
  }
  function payloadContext(scenario) {
    const baseDescription = String(scenario?.desc || '').slice(0, 300);
    // Explicit role-play, video/book practice and custom session topics always
    // outrank adaptive recommendations.
    if (!scenario?.isChainy || scenario?.mySituation || scenario?.videoPractice) {
      return { scenario_desc: baseDescription, interest_topic: null, interest_topic_source: null };
    }
    const custom = String(scenario?.customInterestTopic || '').trim().replace(/\s+/g, ' ').slice(0, 120);
    if (custom) {
      return {
        scenario_desc: `${baseDescription}\nLearner-selected topic for this session: ${custom}`.slice(0, 500),
        interest_topic: null,
        interest_topic_source: 'custom',
      };
    }
    const allowed = state.catalog.some(item => item.eligible && item.topic_key === state.selectedKey);
    return {
      scenario_desc: baseDescription,
      interest_topic: allowed ? state.selectedKey : null,
      interest_topic_source: allowed ? 'catalog' : null,
    };
  }

  window.SC_CHAINY_INTEREST = { mount, attachSessionTopic, payloadContext };
  window.addEventListener('speakchain:memory-control-changed', event => {
    if (event?.detail?.enabled === false) {
      state.enabled = false;
      state.catalog = [];
      state.recommended = null;
      state.selectedKey = '';
      if (el('chainy-interest-panel')) {
        renderConsentOff();
        setStatus('');
      }
    } else if (el('chainy-interest-panel')) {
      load();
    }
  });
  // The inline page renders the initial Chainy card before this deferred
  // controller is loaded. Mount once now; later category renders call mount
  // themselves on the newly-created panel.
  if (el('chainy-interest-panel')) queueMicrotask(mount);
}());
