const { test: base, expect } = require('@playwright/test');

const FIXED_NOW = '2026-08-07T12:00:00.000Z';
const LOCAL_ORIGIN = `http://127.0.0.1:${Number(process.env.SPEAKCHAIN_E2E_PORT || 4173)}`;
const BACKEND_ORIGIN = 'https://speakchain-bot-production.up.railway.app';
const TELEGRAM_INIT_DATA = 'query_id=e2e-query&user=%7B%22id%22%3A9001%7D&auth_date=1786104000&hash=e2e-hash';

const session = label => ({
  access_token: `access-${label}`,
  refresh_token: `refresh-${label}`,
  expires_at: '2026-08-08T12:00:00.000Z',
  user_id: label === 'telegram-mini' ? 9001 : 7001
});

function payloadFor(screen) {
  const shared = {
    level: 'B1',
    xp_total: 420,
    streak_days: 4,
    chain_length: 5,
    session_minutes: 15
  };
  if (screen === 's-home') {
    return {
      ...shared,
      name: 'E2E Learner',
      done_lessons: 3,
      daily_progress: { watch: true, repeat: false, speak: false },
      nudge: { kind: 'lesson', title: 'Продовжити практику', subtitle: 'Детермінований E2E маршрут' },
      grammar_focus: 'Present Perfect',
      online_count: 7,
      rank_position: 12
    };
  }
  if (screen === 's-buddy') {
    return {
      ...shared,
      last_topic: 'Travel',
      recommended_category: 'travel',
      recommended_cat: 'travel',
      buddy_history: []
    };
  }
  if (screen === 's-prog') {
    return {
      ...shared,
      cefr_grammar: { A1: [], A2: [], B1: ['Present Perfect'], B2: [], C1: [], C2: [] },
      topics_data: { 'Present Perfect': { mastery: 60 } },
      mastered: [],
      vocab_coverage: { B1: { known: 120, target: 400, pct: 30, gap: 280 } },
      vocab_volume: { B1: 180 },
      vocab_volume_delta: { B1: 12 },
      social_stats: { speaking_minutes: 24, responses: 3, phrases_applied: 5, challenges_done: 1, relay_links: 2 }
    };
  }
  if (screen === 's-profile') {
    return {
      ...shared,
      my_name: 'E2E Learner',
      done_lessons: 3,
      current_plan: 'basic',
      lottery: { tickets: 0 }
    };
  }
  if (screen === 's-social') {
    return { ...shared, me: { name: 'E2E Learner' }, feed: [], challenges: [], notifications: [] };
  }
  return shared;
}

function json(body, status = 200) {
  return {
    status,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify(body)
  };
}

function postData(request) {
  try { return request.postDataJSON() || {}; } catch { return {}; }
}

function sdkStub(request, url) {
  if (request.method() !== 'GET') return null;
  const resource = `${url.hostname}${url.pathname}`;
  if (resource === 'telegram.org/js/telegram-web-app.js'
      || resource === 'telegram.org/js/telegram-widget.js') {
    return 'window.Telegram = window.Telegram || undefined;';
  }
  if (resource === 'www.youtube.com/iframe_api') {
    return 'window.YT = window.YT || { Player: function(){} };';
  }
  if (resource === 'accounts.google.com/gsi/client') {
    return 'window.google = window.google || undefined;';
  }
  if (resource === 'discoveritschool-hub.github.io/speakchain-app/toast_rewards.js') return '';
  return null;
}

function installBrowserSession(context, userId = 7001) {
  return context.addInitScript(({ now, uid }) => {
    localStorage.setItem('speakchain.pwa.access.v1', 'access-stored');
    localStorage.setItem('speakchain.pwa.refresh.v1', 'refresh-stored');
    localStorage.setItem('speakchain.pwa.access.exp.v1', '2026-08-08T12:00:00.000Z');
    localStorage.setItem('speakchain.pwa.user.v1', String(uid));
    window.__SPEAKCHAIN_E2E_NOW = now;
  }, { now: FIXED_NOW, uid: userId });
}

function installTelegramMiniApp(context, userId = 9001) {
  return context.addInitScript(({ initData, uid }) => {
    const backCallbacks = [];
    window.Telegram = {
      WebApp: {
        initData,
        initDataUnsafe: { user: { id: uid, first_name: 'Telegram E2E' }, start_param: '' },
        platform: 'android',
        version: '8.0',
        ready() {}, expand() {}, requestFullscreen() {}, setHeaderColor() {}, setBackgroundColor() {},
        close() { window.__telegramCloseCalled = true; },
        sendData(data) { (window.__telegramSendData ||= []).push(data); },
        openTelegramLink(url) { (window.__telegramLinks ||= []).push(url); },
        BackButton: {
          onClick(callback) { backCallbacks.push(callback); },
          show() { window.__telegramBackVisible = true; },
          hide() { window.__telegramBackVisible = false; }
        }
      }
    };
  }, { initData: TELEGRAM_INIT_DATA, uid: userId });
}

const test = base.extend({
  scenario: async ({}, use) => {
    await use({
      requests: [],
      unexpected: [],
      payloadFailures: new Map(),
      sessionMode: 'success',
      pageErrors: [],
      consoleErrors: [],
      expectedHttpConsoleErrors: 0
    });
  },

  appPage: async ({ page, context, scenario }, use) => {
    page.on('pageerror', error => scenario.pageErrors.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error') scenario.consoleErrors.push(message.text());
    });
    await context.addInitScript(fixed => {
      const NativeDate = Date;
      const fixedMs = NativeDate.parse(fixed);
      class DeterministicDate extends NativeDate {
        constructor(...args) { super(...(args.length ? args : [fixedMs])); }
        static now() { return fixedMs; }
      }
      DeterministicDate.parse = NativeDate.parse;
      DeterministicDate.UTC = NativeDate.UTC;
      window.Date = DeterministicDate;
    }, FIXED_NOW);

    await context.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());

      if (url.origin === LOCAL_ORIGIN) {
        await route.continue();
        return;
      }

      const stub = sdkStub(request, url);
      if (stub !== null) {
        await route.fulfill({ status: 200, contentType: 'text/javascript; charset=utf-8', body: stub });
        return;
      }

      if (url.origin !== BACKEND_ORIGIN) {
        scenario.unexpected.push(`${request.method()} ${url.href}`);
        await route.fulfill(json({ error: 'unexpected_external_request' }, 599));
        return;
      }

      const body = postData(request);
      scenario.requests.push({ method: request.method(), path: url.pathname, body });

      if (request.method() !== 'POST') {
        scenario.unexpected.push(`${request.method()} ${url.pathname}`);
        await route.fulfill(json({ error: 'unexpected_backend_method' }, 599));
        return;
      }

      if (url.pathname === '/api/v1/session/config') {
        await route.fulfill(json({ google_client_id: '', telegram_bot_username: 'SpeakChain_bot' }));
        return;
      }
      if (url.pathname === '/api/v1/session') {
        if (scenario.sessionMode === 'unavailable') {
          await route.fulfill(json({ error: { code: 'session_503', message: 'temporary unavailable' } }, 503));
        } else {
          await route.fulfill(json(session('telegram-mini')));
        }
        return;
      }
      if (url.pathname === '/api/v1/session/telegram') {
        await route.fulfill(json(session('callback')));
        return;
      }
      if (url.pathname === '/api/v1/session/refresh') {
        await route.fulfill(json(session('refresh')));
        return;
      }
      if (url.pathname === '/miniapp_payload') {
        const screen = String(body.screen || '');
        const failures = Number(scenario.payloadFailures.get(screen) || 0);
        if (failures > 0) {
          scenario.payloadFailures.set(screen, failures - 1);
          await route.fulfill(json({ ok: false, error: 'temporary fixture failure' }, 503));
        } else {
          await route.fulfill(json({ ok: true, d: payloadFor(screen) }));
        }
        return;
      }
      if (url.pathname === '/miniapp_action') {
        await route.fulfill(json({ ok: true }));
        return;
      }
      if (url.pathname === '/lottery_status') {
        await route.fulfill(json({
          ok: true,
          has_active: false,
          lottery_links: 0,
          links_needed: 100,
          my_tickets: []
        }));
        return;
      }

      scenario.unexpected.push(`${request.method()} ${url.pathname}`);
      await route.fulfill(json({ error: 'unexpected_backend_endpoint' }, 599));
    });

    await use(page);
    expect(scenario.unexpected, 'Every non-local request must be explicitly mocked').toEqual([]);
    expect(
      scenario.requests.filter(request => /\/(?:pay|checkout|wayforpay|lottery_buy_ticket|admin_nudge_send)(?:\/|$)/.test(request.path)),
      'E2E must never submit payments or learner/admin messages'
    ).toEqual([]);
    expect(scenario.pageErrors, 'Production app paths must not raise uncaught page errors').toEqual([]);
    expect(
      scenario.consoleErrors,
      'Only explicitly induced fixture HTTP failures may reach the console'
    ).toHaveLength(scenario.expectedHttpConsoleErrors);
    for (const message of scenario.consoleErrors) {
      expect(message).toMatch(/^Failed to load resource: the server responded with a status of 503 /);
    }
  }
});

module.exports = {
  BACKEND_ORIGIN,
  expect,
  FIXED_NOW,
  installBrowserSession,
  installTelegramMiniApp,
  LOCAL_ORIGIN,
  TELEGRAM_INIT_DATA,
  test
};
