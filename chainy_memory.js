(function () {
  'use strict';

  const API_FALLBACK = 'https://speakchain-bot-production.up.railway.app';
  const ACCESS_KEY = 'speakchain.pwa.access.v1';
  const state = { open: false, busy: false, enabled: false, items: [], itemCount: 0, returnFocus: null };

  function el(id) { return document.getElementById(id); }
  function apiBase() {
    try { return String(window.SC_BOT_API || window.BOT_API || API_FALLBACK).replace(/\/$/, ''); }
    catch (_) { return API_FALLBACK; }
  }
  function pwaToken() {
    try { return localStorage.getItem(ACCESS_KEY) || ''; }
    catch (_) { return ''; }
  }
  function authPayload() {
    const initData = window.Telegram?.WebApp?.initData || '';
    if (initData) return { init_data: initData };
    const access = pwaToken();
    return access ? { pwa_access_token: access } : {};
  }
  function authHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    const initData = window.Telegram?.WebApp?.initData || '';
    const access = pwaToken();
    if (initData) headers['X-Telegram-Init-Data'] = initData;
    else if (access) headers.Authorization = `Bearer ${access}`;
    return headers;
  }
  function setStatus(message, isError) {
    const node = el('chainy-memory-status');
    if (!node) return;
    node.textContent = message;
    node.classList.toggle('error', Boolean(isError));
    node.hidden = !message;
  }
  function setBusy(busy) {
    state.busy = busy;
    document.querySelectorAll('#chainy-memory-overlay button, #chainy-memory-overlay input')
      .forEach(control => { control.disabled = busy; });
  }
  function errorMessage(error) {
    if (error?.name === 'AbortError') return 'Сервер не відповів вчасно. Спробуй ще раз.';
    if (error?.status === 401) return 'Увійди через Telegram або PWA, щоб керувати пам’яттю.';
    if (error?.status === 404) return 'Керування пам’яттю ще недоступне на сервері. Розмови працюють як раніше.';
    if (error?.status === 429) return 'Забагато запитів. Зачекай трохи й спробуй ще раз.';
    if (error?.code === 'sensitive_memory') return 'Цей текст не можна зберегти як пам’ять. Прибери чутливі дані й спробуй ще раз.';
    return error?.message || 'Не вдалося оновити пам’ять. Спробуй ще раз.';
  }
  async function memoryRequest(op, fields) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    let response;
    try {
      response = await fetch(apiBase() + '/buddy_memory', {
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
      const message = data?.error?.message || data?.detail?.message || data?.message || `memory_${response.status}`;
      const error = new Error(message);
      error.status = response.status;
      error.code = code;
      throw error;
    }
    return data;
  }
  function normaliseItems(items) {
    if (!Array.isArray(items)) return [];
    return items.filter(item => item && typeof item === 'object' && item.id && typeof item.text === 'string');
  }
  function renderMemory(data) {
    state.enabled = Boolean(data?.enabled);
    const receivedItems = normaliseItems(data?.items);
    const serverCount = Number(data?.item_count);
    state.itemCount = Number.isFinite(serverCount) && serverCount >= 0 ? serverCount : receivedItems.length;
    // A disabled profile has not consented to viewing or using legacy facts.
    // Keep their contents out of the DOM and client state until consent exists.
    state.items = state.enabled ? receivedItems : [];
    const consent = el('chainy-memory-consent');
    const enabled = el('chainy-memory-enabled');
    const disabledSummary = el('chainy-memory-disabled-summary');
    if (consent) consent.hidden = state.enabled;
    if (enabled) enabled.hidden = !state.enabled;
    if (disabledSummary) {
      disabledSummary.textContent = state.itemCount > 0
        ? `Є раніше збережені записи: ${state.itemCount}. До згоди Chainy їх не використовує.`
        : 'До згоди вміст пам’яті не відображається.';
    }
    const list = el('chainy-memory-list');
    if (state.enabled) renderMemoryItems();
    else list?.replaceChildren();
    setStatus('');
  }
  function makeButton(label, action, extraClass, ariaLabel) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `memory-btn${extraClass ? ` ${extraClass}` : ''}`;
    button.textContent = label;
    if (ariaLabel) button.setAttribute('aria-label', ariaLabel);
    button.addEventListener('click', action);
    return button;
  }
  function renderMemoryItems() {
    const list = el('chainy-memory-list');
    if (!list) return;
    list.replaceChildren();
    if (!state.items.length) {
      const empty = document.createElement('p');
      empty.className = 'memory-status';
      empty.textContent = 'Поки що немає збережених фактів. Chainy запропонує їх після наступних розмов.';
      list.appendChild(empty);
      return;
    }
    state.items.forEach(item => {
      const card = document.createElement('article');
      card.className = `memory-item${item.confirmed ? '' : ' pending'}`;
      const meta = document.createElement('div');
      meta.className = 'memory-meta';
      meta.textContent = `${item.confirmed ? 'Підтверджено' : 'Очікує підтвердження'}${item.kind ? ` · ${item.kind}` : ''}`;
      const text = document.createElement('p');
      text.className = 'memory-text';
      text.textContent = item.text;
      const actions = document.createElement('div');
      actions.className = 'memory-actions';
      if (!item.confirmed) {
        actions.appendChild(makeButton('Підтвердити', () => confirmChainyMemory(item.id), 'primary', `Підтвердити: ${item.text}`));
      }
      actions.appendChild(makeButton('Змінити', () => editChainyMemory(item), '', `Змінити: ${item.text}`));
      actions.appendChild(makeButton('Видалити', () => deleteChainyMemory(item), 'danger', `Видалити: ${item.text}`));
      card.append(meta, text, actions);
      list.appendChild(card);
    });
  }
  async function runMutation(op, fields, pendingMessage, successMessage) {
    if (state.busy) return;
    setBusy(true);
    setStatus(pendingMessage);
    try {
      const data = await memoryRequest(op, fields);
      renderMemory(data);
      if (successMessage) setStatus(successMessage);
    } catch (error) {
      setStatus(errorMessage(error), true);
    } finally {
      setBusy(false);
    }
  }

  window.openChainyMemory = async function openChainyMemory() {
    const overlay = el('chainy-memory-overlay');
    if (!overlay) return;
    state.open = true;
    state.returnFocus = document.activeElement;
    overlay.classList.add('show');
    document.body.style.overflow = 'hidden';
    el('chainy-memory-consent')?.setAttribute('hidden', '');
    el('chainy-memory-enabled')?.setAttribute('hidden', '');
    setStatus('Завантажуємо налаштування…');
    setBusy(true);
    el('chainy-memory-title')?.focus?.();
    try {
      renderMemory(await memoryRequest('view'));
    } catch (error) {
      setStatus(errorMessage(error), true);
    } finally {
      setBusy(false);
    }
  };
  window.closeChainyMemory = function closeChainyMemory() {
    if (!state.open || state.busy) return;
    state.open = false;
    el('chainy-memory-overlay')?.classList.remove('show');
    document.body.style.overflow = '';
    state.returnFocus?.focus?.();
  };
  window.enableChainyMemory = function enableChainyMemory() {
    if (!el('chainy-memory-consent-check')?.checked) {
      setStatus('Постав позначку згоди, щоб увімкнути пам’ять.', true);
      return;
    }
    runMutation('consent', {}, 'Вмикаємо пам’ять…', 'Пам’ять увімкнена.');
  };
  window.confirmChainyMemory = function confirmChainyMemory(memoryId) {
    runMutation('confirm', { memory_id: memoryId, confirmed: true }, 'Підтверджуємо факт…', 'Факт підтверджено.');
  };
  window.editChainyMemory = function editChainyMemory(item) {
    const nextText = window.prompt('Зміни факт, який може пам’ятати Chainy:', item.text);
    if (nextText === null) return;
    const text = nextText.trim();
    if (!text) {
      setStatus('Текст пам’яті не може бути порожнім.', true);
      return;
    }
    if (text === item.text) return;
    runMutation('edit', { memory_id: item.id, text }, 'Зберігаємо зміну…', 'Факт змінено.');
  };
  window.deleteChainyMemory = function deleteChainyMemory(item) {
    if (!window.confirm(`Видалити цей факт з пам’яті Chainy?\n\n${item.text}`)) return;
    runMutation('delete', { memory_id: item.id }, 'Видаляємо факт…', 'Факт видалено.');
  };
  window.deleteAllChainyMemory = function deleteAllChainyMemory() {
    if (!window.confirm('Видалити всю збережену пам’ять Chainy? Цю дію не можна скасувати.')) return;
    runMutation('delete_all', {}, 'Видаляємо всю пам’ять…', 'Усю пам’ять Chainy видалено.');
  };
  window.disableChainyMemory = function disableChainyMemory() {
    const warning = 'Вимкнути пам’ять? Це зупинить пам’ять і видалить збережену історію та факти Chainy. Цю дію не можна скасувати.';
    if (!window.confirm(warning)) return;
    runMutation('disable', {}, 'Вимикаємо й очищаємо пам’ять…', 'Пам’ять вимкнено, збережену історію та факти Chainy видалено.');
  };

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && state.open && !state.busy) window.closeChainyMemory();
  });
}());
