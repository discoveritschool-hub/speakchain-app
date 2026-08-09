const {
  expect,
  installBrowserSession,
  installTelegramMiniApp,
  TELEGRAM_INIT_DATA,
  test
} = require('./fixtures/critical-app.js');

test('PWA ApiClient authenticates without uid, bounds retries and suppresses stale generations', async ({ appPage: page, context, scenario }) => {
  await installBrowserSession(context);
  scenario.allowedHttpConsoleErrors = 4;
  let reads = 0;
  let unsafeMutations = 0;
  let stableMutations = 0;
  let mismatchMutations = 0;
  let cancelledReads = 0;
  let timeoutReads = 0;
  let timeoutMutations = 0;
  const stableBodies = [];
  const timeoutMutationBodies = [];
  await context.route('**/api-boundary-read', async route => {
    reads += 1;
    await route.fulfill({
      status: reads === 1 ? 503 : 200,
      contentType: 'application/json',
      body: JSON.stringify(reads === 1 ? { error: 'temporary' } : { ok: true })
    });
  });
  await context.route('**/api-boundary-mutation', async route => {
    unsafeMutations += 1;
    await route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"temporary"}' });
  });
  await context.route('**/api-boundary-stable-mutation', async route => {
    stableMutations += 1;
    stableBodies.push(route.request().postDataJSON());
    await route.fulfill({
      status: stableMutations === 1 ? 503 : 200,
      contentType: 'application/json',
      body: JSON.stringify(stableMutations === 1 ? { error: 'temporary' } : { ok: true })
    });
  });
  await context.route('**/api-boundary-mismatch', async route => {
    mismatchMutations += 1;
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' });
  });
  await context.route('**/api-boundary-cancelled-read', async route => {
    cancelledReads += 1;
    await route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"temporary"}' });
  });
  await context.route('**/api-boundary-timeout-read', async route => {
    timeoutReads += 1;
    if (timeoutReads === 1) await new Promise(resolve => setTimeout(resolve, 400));
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' }).catch(() => {});
  });
  await context.route('**/api-boundary-timeout-mutation', async route => {
    timeoutMutations += 1;
    timeoutMutationBodies.push(route.request().postData());
    if (timeoutMutations === 1) await new Promise(resolve => setTimeout(resolve, 400));
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' }).catch(() => {});
  });

  await page.goto('/index_v2.html');
  const result = await page.evaluate(async () => {
    const auth = await window.SC_API.auth();
    const first = window.SC_API.beginGeneration('e2e-navigation');
    const second = window.SC_API.beginGeneration('e2e-navigation');
    const read = await window.SC_API.request('/api-boundary-read', {
      base: location.origin, operation: 'read', attempts: 2, timeout: 1000
    });
    let mutationKind = '';
    try {
      await window.SC_API.request('/api-boundary-mutation', {
        base: location.origin, operation: 'mutation', attempts: 2, timeout: 1000
      });
    } catch (error) { mutationKind = error.kind; }
    const stableId = 'profile:e2e-stable-0001';
    const stable = await window.SC_API.request('/api-boundary-stable-mutation', {
      base: location.origin, operation: 'mutation', mutationId: stableId,
      attempts: 2, timeout: 1000,
      body: { action: 'profile_settings_update', uid: 999999, init_data: 'attacker' }
    });
    let mismatchKind = '';
    try {
      await window.SC_API.request('/api-boundary-mismatch', {
        base: location.origin, operation: 'mutation', mutationId: stableId,
        attempts: 2, body: {
          action: 'charge_subscription', mutation_id: 'profile:e2e-other-00002'
        }
      });
    } catch (error) { mismatchKind = error.kind; }
    const abortController = new AbortController();
    setTimeout(() => abortController.abort(), 40);
    let cancelledKind = '';
    try {
      await window.SC_API.request('/api-boundary-cancelled-read', {
        base: location.origin, operation: 'read', attempts: 2,
        timeout: 1000, signal: abortController.signal
      });
    } catch (error) { cancelledKind = error.kind; }
    await new Promise(resolve => setTimeout(resolve, 350));
    const timeoutRead = await window.SC_API.request('/api-boundary-timeout-read', {
      base: location.origin, operation: 'read', attempts: 2, timeout: 250
    });
    const timeoutMutation = await window.SC_API.request('/api-boundary-timeout-mutation', {
      base: location.origin, operation: 'mutation', mutationId: stableId,
      attempts: 2, timeout: 250, body: { action: 'profile_settings_update' }
    });
    return {
      auth, readOk: read.payload.ok, mutationKind,
      stableOk: stable.payload.ok, mismatchKind, cancelledKind,
      timeoutReadOk: timeoutRead.payload.ok,
      timeoutMutationOk: timeoutMutation.payload.ok,
      firstCurrent: window.SC_API.isCurrent('e2e-navigation', first),
      secondCurrent: window.SC_API.isCurrent('e2e-navigation', second)
    };
  });

  expect(result.auth).toEqual({ pwa_access_token: 'access-stored' });
  expect(result.auth).not.toHaveProperty('uid');
  expect(result).toMatchObject({
    readOk: true, mutationKind: 'server', stableOk: true,
    mismatchKind: 'invalid_request', cancelledKind: 'cancelled',
    timeoutReadOk: true, timeoutMutationOk: true,
    firstCurrent: false, secondCurrent: true
  });
  expect(reads).toBe(2);
  expect(unsafeMutations).toBe(1);
  expect(stableMutations).toBe(2);
  expect(stableBodies.map(body => body.mutation_id)).toEqual([
    'profile:e2e-stable-0001', 'profile:e2e-stable-0001'
  ]);
  for (const body of stableBodies) {
    expect(body).not.toHaveProperty('uid');
    expect(body).not.toHaveProperty('init_data');
    expect(body.pwa_access_token).toBe('access-stored');
  }
  expect(mismatchMutations).toBe(0);
  expect(cancelledReads).toBe(1);
  expect(timeoutReads).toBe(2);
  expect(timeoutMutations).toBe(2);
  expect(timeoutMutationBodies[0]).toBe(timeoutMutationBodies[1]);
  expect(JSON.parse(timeoutMutationBodies[0]).mutation_id).toBe('profile:e2e-stable-0001');
  scenario.localFailures = scenario.localFailures.filter(item => !item.includes('/api-boundary-'));

  await page.evaluate(() => {
    localStorage.removeItem('speakchain.pwa.access.v1');
    delete window.Telegram;
  });
  await expect.poll(() => page.evaluate(() => window.SC_API.auth())).toBeNull();
  expect(await page.evaluate(async () => {
    try {
      await window.SC_API.request('/api-boundary-read', { base: location.origin, operation: 'read' });
    } catch (error) { return error.kind; }
    return 'none';
  })).toBe('auth');
});

test('slow shell payload is aborted when navigation advances to Profile', async ({ appPage: page, context, scenario }) => {
  await installBrowserSession(context);
  await context.addInitScript(() => {
    const NativeAbortController = window.AbortController;
    window.__e2eAbortCount = 0;
    window.AbortController = class TrackedAbortController extends NativeAbortController {
      abort(reason) {
        window.__e2eAbortCount += 1;
        return super.abort(reason);
      }
    };
  });
  scenario.payloadDelays.set('s-home', 4000);
  await page.goto('/index_v2.html');
  await expect.poll(() => scenario.requests.filter(request =>
    request.path === '/miniapp_payload' && request.body.screen === 's-home').length).toBe(1);
  const abortsBeforeNavigation = await page.evaluate(() => window.__e2eAbortCount);

  await page.locator('#tb-profile').click();
  await expect.poll(() => page.evaluate(() => window.__e2eAbortCount))
    .toBeGreaterThan(abortsBeforeNavigation);
  await expect(page.locator('#s-profile')).toHaveClass(/\bon\b/);
  await expect(page.locator('#p-nm')).toHaveText('E2E Learner');
  await page.waitForTimeout(500);
  await expect(page.locator('#s-profile')).toHaveClass(/\bon\b/);
  await expect(page.locator('#offline-banner')).toBeHidden();
});

test('Telegram ApiClient prefers verified initData and reports offline recovery state', async ({ appPage: page, context }) => {
  await installTelegramMiniApp(context);
  await page.goto('/index_v2.html');

  expect(await page.evaluate(() => window.SC_API.auth())).toEqual({ init_data: TELEGRAM_INIT_DATA });
  const kind = await page.evaluate(async () => {
    const originalFetch = window.fetch;
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false });
    window.fetch = () => Promise.reject(new TypeError('offline'));
    try {
      await window.SC_API.request('/api-boundary-offline', {
        base: location.origin,
        operation: 'read', attempts: 1, timeout: 500, body: { screen: 's-home' }
      });
    } catch (error) { return error.kind; }
    finally {
      window.fetch = originalFetch;
      Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
    }
    return 'none';
  });
  expect(kind).toBe('offline');
});
