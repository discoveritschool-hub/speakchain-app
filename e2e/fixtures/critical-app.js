const { test: base, expect } = require('@playwright/test');
const backendAuthConfigContract = require('../../contracts/backend-pwa-auth-config.json');

const authConfigContract = backendAuthConfigContract.endpoint_contract;
const ACCOUNT_LINKING_CONFIG_KEY = 'account_linking_enabled';
if (authConfigContract?.path !== '/api/v1/session/config'
    || authConfigContract?.authentication !== 'public'
    || !authConfigContract?.response_required?.includes(ACCOUNT_LINKING_CONFIG_KEY)) {
  throw new Error('Backend PWA auth-config manifest does not expose account_linking_enabled');
}

const FIXED_NOW = '2026-08-07T12:00:00.000Z';
const LOCAL_ORIGIN = `http://127.0.0.1:${Number(process.env.SPEAKCHAIN_E2E_PORT || 4173)}`;
const BACKEND_ORIGIN = 'https://speakchain-bot-production.up.railway.app';
const ACTIVITY_ORIGIN = 'https://speakchain-bot-production.up.railway.app';
const TELEGRAM_INIT_DATA = 'query_id=e2e-query&user=%7B%22id%22%3A9001%7D&auth_date=1786104000&hash=e2e-hash';
const E2E_VIDEO_ID = 'dQw4w9WgXcQ';
const E2E_VIDEO_TITLE = 'E2E Own Video';
const E2E_CAPTION = 'Practice makes progress every day.';

function criticalInvariant(_id, assertion) {
  return assertion();
}

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
    chain_length: 5
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
      utc_offset: 2,
      notification_pref: 'evening',
      profile_settings_revision: 0,
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
    return `(() => {
      const PlayerState = { PLAYING: 1, PAUSED: 2 };
      window.YT = {
        PlayerState,
        Player: function(_target, options) {
          let currentTime = 1;
          let state = PlayerState.PAUSED;
          this.getCurrentTime = () => currentTime;
          this.getPlayerState = () => state;
          this.getVideoData = () => ({ title: '${E2E_VIDEO_TITLE}' });
          this.pauseVideo = () => { state = PlayerState.PAUSED; };
          this.playVideo = () => {
            state = PlayerState.PLAYING;
            options?.events?.onStateChange?.({ data: state, target: this });
          };
          this.seekTo = value => { currentTime = Number(value) || 0; };
          this.destroy = () => {};
          setTimeout(() => options?.events?.onReady?.({ target: this }), 0);
        }
      };
      setTimeout(() => window.onYouTubeIframeAPIReady?.(), 0);
    })();`;
  }
  if (resource === 'accounts.google.com/gsi/client') {
    return 'window.google = window.google || undefined;';
  }
  if (resource === 'discoveritschool-hub.github.io/speakchain-app/toast_rewards.js') return '';
  return null;
}

function installBrowserSession(context, userId = 7001, provider = 'google') {
  return context.addInitScript(({ now, uid, provider }) => {
    localStorage.setItem('speakchain.pwa.access.v1', 'access-stored');
    localStorage.setItem('speakchain.pwa.refresh.v1', 'refresh-stored');
    localStorage.setItem('speakchain.pwa.access.exp.v1', '2026-08-08T12:00:00.000Z');
    localStorage.setItem('speakchain.pwa.user.v1', String(uid));
    localStorage.setItem('speakchain.pwa.provider.v1', provider);
    window.__SPEAKCHAIN_E2E_NOW = now;
  }, { now: FIXED_NOW, uid: userId, provider });
}

function installTelegramMiniApp(context, userId = 9001, options = {}) {
  return context.addInitScript(({ initData, uid, options }) => {
    const backCallbacks = [];
    const version = String(options.version || '8.0');
    const versionAtLeast = minimum => {
      const current = version.split('.').map(part => Number(part) || 0);
      const required = String(minimum || '0').split('.').map(part => Number(part) || 0);
      for (let index = 0; index < Math.max(current.length, required.length); index += 1) {
        const left = current[index] || 0;
        const right = required[index] || 0;
        if (left !== right) return left > right;
      }
      return true;
    };
    window.Telegram = {
      WebApp: {
        initData,
        initDataUnsafe: { user: { id: uid, first_name: 'Telegram E2E' }, start_param: '' },
        platform: 'android',
        version,
        isVersionAtLeast: versionAtLeast,
        ready() {}, expand() {},
        requestFullscreen() {
          window.__telegramFullscreenCalls = (window.__telegramFullscreenCalls || 0) + 1;
          if (options.fullscreenThrows) throw new Error(String(options.fullscreenThrows));
        },
        setHeaderColor() {}, setBackgroundColor() {},
        close() { window.__telegramCloseCalled = true; },
        sendData(data) { (window.__telegramSendData ||= []).push(data); },
        openLink(url) { (window.__telegramOpenLinks ||= []).push(url); },
        openTelegramLink(url) { (window.__telegramLinks ||= []).push(url); },
        BackButton: {
          onClick(callback) { backCallbacks.push(callback); },
          show() { window.__telegramBackVisible = true; },
          hide() { window.__telegramBackVisible = false; }
        }
      }
    };
  }, { initData: TELEGRAM_INIT_DATA, uid: userId, options });
}

const test = base.extend({
  scenario: async ({}, use) => {
    await use({
      requests: [],
      unexpected: [],
      payloadFailures: new Map(),
      payloadDelays: new Map(),
      profileMutationFailures: [],
      profileMutationResponses: [],
      profileMutationLedger: new Map(),
      profileSettings: {
        utc_offset: 2, notification_pref: 'evening',
        profile_settings_revision: 0
      },
      accountLinkingEnabled: false,
      accountLinkRouteAbsent: false,
      accountLinkIntentResponses: [],
      accountLinkCompleteResponses: [],
      sessionMode: 'success',
      phraselabAccess: { ok: true, access: true, reason: 'student_plan', purchase_price_usd: 7 },
      pageErrors: [],
      consoleErrors: [],
      localFailures: [],
      reportedErrors: [],
      allowedHttpConsoleErrors: 0
    });
  },

  appPage: async ({ page, context, scenario }, use) => {
    page.on('pageerror', error => scenario.pageErrors.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error') scenario.consoleErrors.push(message.text());
    });
    page.on('response', response => {
      const url = new URL(response.url());
      if (url.origin === LOCAL_ORIGIN && response.status() >= 400) {
        scenario.localFailures.push(`${response.status()} ${url.pathname}`);
      }
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

      if (url.origin === ACTIVITY_ORIGIN
          && request.method() === 'GET'
          && url.pathname === '/api/v1/live-sessions/me') {
        await route.fulfill(json({ ok: true, sessions: [] }));
        return;
      }
      if (url.origin === ACTIVITY_ORIGIN
          && request.method() === 'GET'
          && url.pathname === '/api/v1/activity-results/me') {
        await route.fulfill(json({ ok: true, results: [] }));
        return;
      }

      if (url.origin !== BACKEND_ORIGIN) {
        scenario.unexpected.push(`${request.method()} ${url.href}`);
        await route.fulfill(json({ error: 'unexpected_external_request' }, 599));
        return;
      }

      const body = postData(request);
      const query = Object.fromEntries(url.searchParams.entries());
      const headers = request.headers();
      scenario.requests.push({ method: request.method(), path: url.pathname, query, headers, body });

      if (request.method() === 'GET' && url.pathname === '/captions') {
        if (query.v !== E2E_VIDEO_ID || query.lang !== 'en' || Object.keys(query).length !== 2) {
          scenario.unexpected.push(`GET ${url.pathname} invalid_query`);
          await route.fulfill(json({ error: 'invalid_caption_fixture_query' }, 400));
          return;
        }
        await route.fulfill(json({
          events: [{
            tStartMs: 1000,
            dDurationMs: 3500,
            segs: [{ utf8: E2E_CAPTION }]
          }],
          caption_source: 'youtube',
          caption_resolver_source: 'youtube_player'
        }));
        return;
      }

      if (request.method() === 'GET' && url.pathname === '/video_summary') {
        if (query.vid !== E2E_VIDEO_ID || Object.keys(query).length !== 1) {
          scenario.unexpected.push(`GET ${url.pathname} invalid_query`);
          await route.fulfill(json({ error: 'invalid_video_summary_fixture_query' }, 400));
          return;
        }
        await route.fulfill(json({
          ok: true,
          summary: 'A short lesson about consistent daily practice.'
        }));
        return;
      }

      if (request.method() === 'GET' && url.pathname === '/buddy_victory') {
        if (!/^\d+$/.test(query.uid || '') || Object.keys(query).length !== 1) {
          scenario.unexpected.push(`GET ${url.pathname} invalid_query`);
          await route.fulfill(json({ error: 'invalid_buddy_victory_fixture_query' }, 400));
          return;
        }
        await route.fulfill(json({
          ok: true,
          xp_gained: 12,
          multiplier: 1,
          streak: 5,
          rank: 11,
          percentile: 80,
          gap_to_next: 20
        }));
        return;
      }

      if (request.method() === 'GET' && url.pathname === '/buddy_image') {
        if (!query.q || Object.keys(query).length !== 1) {
          scenario.unexpected.push(`GET ${url.pathname} invalid_query`);
          await route.fulfill(json({ error: 'invalid_buddy_image_fixture_query' }, 400));
          return;
        }
        await route.fulfill(json({ url: null }));
        return;
      }

      if (request.method() !== 'POST') {
        scenario.unexpected.push(`${request.method()} ${url.pathname}`);
        await route.fulfill(json({ error: 'unexpected_backend_method' }, 599));
        return;
      }

      if (url.pathname === '/api/v1/session/config') {
        await route.fulfill(json({
          google_client_id: 'google-client-e2e',
          telegram_bot_username: 'SpeakChain_bot',
          [ACCOUNT_LINKING_CONFIG_KEY]: scenario.accountLinkingEnabled
        }));
        return;
      }
      if (url.pathname === '/api/v1/account-link/intents') {
        if (scenario.accountLinkRouteAbsent) {
          await route.fulfill(json({ error: { code: 'not_found', message: 'Not found' } }, 404));
          return;
        }
        const planned = scenario.accountLinkIntentResponses.shift();
        if (planned?.delayMs) await new Promise(resolve => setTimeout(resolve, planned.delayMs));
        if (planned && Number(planned.status || 200) >= 400) {
          await route.fulfill(json({ error: { code: planned.code, message: planned.message || 'fixture error' } }, planned.status));
          return;
        }
        await route.fulfill(json(planned?.body || {
          ok: true, link_token: 'intent-token-e2e', expires_in: 600,
          target_provider: body.target_provider
        }));
        return;
      }
      if (url.pathname === '/api/v1/account-link/complete') {
        const planned = scenario.accountLinkCompleteResponses.shift();
        if (planned?.delayMs) await new Promise(resolve => setTimeout(resolve, planned.delayMs));
        if (planned && Number(planned.status || 200) >= 400) {
          await route.fulfill(json({ error: { code: planned.code, message: planned.message || 'fixture error' } }, planned.status)).catch(() => {});
          return;
        }
        await route.fulfill(json(planned?.body || {
          ok: true, outcome: 'merged', canonical_user_id: 7001,
          merge_id: 'merge-e2e', replayed: false
        })).catch(() => {});
        return;
      }
      if (url.pathname === '/api/v1/notifications') {
        await route.fulfill(json({ok: true, notifications: [], unread_count: 0, next_cursor: null}));
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
        const delay = Number(scenario.payloadDelays.get(screen) || 0);
        if (delay > 0) await new Promise(resolve => setTimeout(resolve, delay));
        const failures = Number(scenario.payloadFailures.get(screen) || 0);
        if (failures > 0) {
          scenario.payloadFailures.set(screen, failures - 1);
          await route.fulfill(json({ ok: false, error: 'temporary fixture failure' }, 503)).catch(() => {});
        } else {
          const payload = payloadFor(screen);
          if (screen === 's-profile') Object.assign(payload, scenario.profileSettings);
          await route.fulfill(json({ ok: true, d: payload })).catch(() => {});
        }
        return;
      }
      if (url.pathname === '/phraselab_access') {
        await route.fulfill(json(scenario.phraselabAccess));
        return;
      }
      if (url.pathname === '/api/v1/notifications') {
        await route.fulfill(json({ items: [], unread: 0, push: {} }));
        return;
      }
      if (url.pathname === '/miniapp_action') {
        if (body.action === 'profile_settings_update') {
          const planned = scenario.profileMutationResponses.shift();
          if (planned?.delayMs) {
            await new Promise(resolve => setTimeout(resolve, planned.delayMs));
          }
          const failure = scenario.profileMutationFailures.shift();
          if (failure || (planned && Number(planned.status || 200) >= 400)) {
            const terminal = failure || planned;
            await route.fulfill(json({ ok: false, error: terminal.error || 'temporary_failure' }, terminal.status || 503)).catch(() => {});
            return;
          }
          const settings = planned?.settings || body.settings || {};
          const mutationId = body.mutation_id;
          const expectedRevision = body.expected_revision;
          const fingerprint = JSON.stringify({ expectedRevision, settings });
          if (typeof mutationId !== 'string' || mutationId.length < 16 ||
              !Number.isInteger(expectedRevision) || expectedRevision < 0) {
            await route.fulfill(json({ ok: false, error: 'invalid_mutation_metadata' }, 400)).catch(() => {});
            return;
          }
          const previous = scenario.profileMutationLedger.get(mutationId);
          if (previous) {
            if (previous.fingerprint !== fingerprint) {
              await route.fulfill(json({ ok: false, error: 'mutation_id_reused' }, 409)).catch(() => {});
              return;
            }
            const revision = scenario.profileSettings.profile_settings_revision;
            const payload = {
              ok: previous.outcome === 'applied', outcome: previous.outcome,
              replayed: true, revision,
              mutation_revision: previous.mutationRevision,
              settings: { level: 'B1', current_plan: 'basic', ...scenario.profileSettings }
            };
            await route.fulfill(json(payload, previous.outcome === 'applied' ? 200 : 409)).catch(() => {});
            return;
          }
          const currentRevision = scenario.profileSettings.profile_settings_revision;
          if (expectedRevision !== currentRevision) {
            scenario.profileMutationLedger.set(mutationId, {
              fingerprint, outcome: 'conflict', mutationRevision: currentRevision
            });
            await route.fulfill(json({
              ok: false, outcome: 'conflict', replayed: false,
              revision: currentRevision, mutation_revision: null,
              settings: { level: 'B1', current_plan: 'basic', ...scenario.profileSettings }
            }, 409)).catch(() => {});
            return;
          }
          Object.assign(scenario.profileSettings, settings);
          const revision = currentRevision + 1;
          scenario.profileSettings.profile_settings_revision = revision;
          scenario.profileMutationLedger.set(mutationId, {
            fingerprint, outcome: 'applied', mutationRevision: revision
          });
          while (scenario.profileMutationLedger.size > 16) {
            scenario.profileMutationLedger.delete(scenario.profileMutationLedger.keys().next().value);
          }
          await route.fulfill(json({
            ok: true, outcome: 'applied', replayed: false,
            revision, mutation_revision: revision,
            settings: {
              level: 'B1', current_plan: 'basic',
              ...scenario.profileSettings
            }
          })).catch(() => {});
          return;
        }
        await route.fulfill(json({ ok: true }));
        return;
      }
      if (url.pathname === '/word_lookup') {
        if (typeof body.word === 'string' && body.word.trim()) {
          await route.fulfill(json({
            ok: true,
            card: {
              word: body.word,
              phonetic: '/\u02c8pr\u00e6kt\u026as/',
              translation_uk: '\u043f\u0440\u0430\u043a\u0442\u0438\u043a\u0430',
              definition_en: 'Repeated action that improves a skill.',
              examples: ['Daily practice builds confidence.']
            }
          }));
          return;
        }
        if (typeof body.text === 'string' && body.text.trim()) {
          await route.fulfill(json({ ok: true, translation_uk: '\u041f\u0440\u0430\u043a\u0442\u0438\u043a\u0430 \u0449\u043e\u0434\u043d\u044f \u043f\u0440\u0438\u043d\u043e\u0441\u0438\u0442\u044c \u043f\u0440\u043e\u0433\u0440\u0435\u0441.' }));
          return;
        }
        scenario.unexpected.push(`POST ${url.pathname} invalid_body`);
        await route.fulfill(json({ error: 'invalid_word_lookup_fixture_body' }, 400));
        return;
      }
      if (url.pathname === '/player_action') {
        if (body.action !== 'save_phrase' || typeof body.phrase !== 'string' || !body.phrase.trim()) {
          scenario.unexpected.push(`POST ${url.pathname} invalid_body`);
          await route.fulfill(json({ error: 'invalid_player_action_fixture_body' }, 400));
          return;
        }
        await route.fulfill(json({ ok: true }));
        return;
      }
      if (url.pathname === '/vocab_data') {
        const phrases = scenario.requests
          .filter(entry => entry.path === '/player_action' && entry.body?.action === 'save_phrase')
          .map(entry => ({
            phrase: entry.body.phrase,
            translation_uk: entry.body.translation || '',
            video_id: entry.body.video_id || '',
            video_title: entry.body.video_title || '',
            video_time: Number(entry.body.current_time || 0)
          }));
        await route.fulfill(json({ phrases, due: [] }));
        return;
      }
      if (url.pathname === '/buddy_status') {
        await route.fulfill(json({
          ok: true,
          max_messages: 20,
          msg_count: 0,
          remaining: 20,
          history: [],
          memory_enabled: false
        }));
        return;
      }
      if (url.pathname === '/buddy_chat') {
        await route.fulfill(json({
          reply: 'Exactly. Tell me how daily practice helps you make progress.',
          feedback: []
        }));
        return;
      }
      if (url.pathname === '/buddy_realtime_token') {
        // The production module probes Realtime for spoken greetings first.
        // Match the backend's real not-configured contract so this text-path
        // cycle falls back without minting a key or touching OpenAI.
        await route.fulfill(json({ error: 'Voice AI is not configured' }, 503));
        return;
      }
      if (url.pathname === '/err_fix') {
        scenario.reportedErrors.push(body);
        await route.fulfill(json({ ok: true }));
        return;
      }
      if (url.pathname === '/buddy_session_end') {
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
    criticalInvariant('network.deny_default', () => expect(
      scenario.unexpected, 'Every non-local request must be explicitly mocked'
    ).toEqual([]));
    criticalInvariant('paid.no_requests', () => expect(
      scenario.requests.filter(request => /\/(?:pay|checkout|wayforpay|lottery_buy_ticket|admin_nudge_send)(?:\/|$)/.test(request.path)),
      'E2E must never submit payments or learner/admin messages'
    ).toEqual([]));
    criticalInvariant('errors.page', () => expect(
      scenario.pageErrors, 'Production app paths must not raise uncaught page errors'
    ).toEqual([]));
    expect(scenario.reportedErrors, 'Production app paths must not report runtime errors').toEqual([]);
    criticalInvariant('errors.local_assets', () => expect(
      scenario.localFailures, 'Every local app asset must resolve'
    ).toEqual([]));
    // Chromium may omit the console diagnostic when a mocked 503 finishes
    // during navigation/teardown. Treat the configured count as a strict cap;
    // every emitted message must still be the explicitly induced 503 below.
    criticalInvariant('errors.console_allowlist', () => expect(
      scenario.consoleErrors.length,
      'Only explicitly induced fixture HTTP failures may reach the console'
    ).toBeLessThanOrEqual(scenario.allowedHttpConsoleErrors));
    for (const message of scenario.consoleErrors) {
      expect(message).toMatch(/^Failed to load resource: the server responded with a status of (?:404|409|410|503) /);
    }
  }
});

module.exports = {
  BACKEND_ORIGIN,
  E2E_CAPTION,
  E2E_VIDEO_ID,
  E2E_VIDEO_TITLE,
  expect,
  FIXED_NOW,
  installBrowserSession,
  installTelegramMiniApp,
  LOCAL_ORIGIN,
  TELEGRAM_INIT_DATA,
  test
};
