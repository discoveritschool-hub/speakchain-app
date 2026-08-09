const {
  expect,
  installBrowserSession,
  installTelegramMiniApp,
  TELEGRAM_INIT_DATA,
  test
} = require('./fixtures/critical-app.js');

test('browser Telegram callback persists and resumes one PWA session', async ({ appPage: page, scenario }) => {
  await page.goto('/telegram_auth_callback.html?id=7001&first_name=Browser&auth_date=1786104000&hash=signed-e2e');

  await expect(page).toHaveURL(/index_v2\.html$/);
  await expect(page.locator('#sc-auth-gate')).toHaveCount(0);
  await expect(page.locator('#s-home')).toHaveClass(/\bon\b/);
  await expect.poll(() => page.evaluate(() => localStorage.getItem('speakchain.pwa.access.v1')))
    .toBe('access-callback');

  const callback = scenario.requests.find(request => request.path === '/api/v1/session/telegram');
  expect(callback?.body).toEqual({
    user: {
      id: '7001',
      first_name: 'Browser',
      auth_date: '1786104000',
      hash: 'signed-e2e'
    }
  });

  await page.reload();
  await expect(page.locator('#sc-auth-gate')).toHaveCount(0);
  await expect(page.locator('#s-home')).toHaveClass(/\bon\b/);
  const payload = scenario.requests.find(request => request.path === '/miniapp_payload');
  expect(payload?.body).toMatchObject({ uid: 7001, pwa_access_token: 'access-callback', screen: 's-home' });
});

test('Telegram initData remains the authenticated fallback when session handoff is unavailable', async ({ appPage: page, context, scenario }) => {
  scenario.sessionMode = 'unavailable';
  scenario.allowedHttpConsoleErrors = 1;
  await installTelegramMiniApp(context);

  await page.goto('/index_v2.html');

  await expect(page.locator('#sc-auth-gate')).toHaveCount(0);
  await expect(page.locator('#s-home')).toHaveClass(/\bon\b/);
  await expect.poll(() => page.evaluate(async () => (await window.SC_PWA.ready).source))
    .toBe('telegram-initdata');
  await expect.poll(() => page.evaluate(() => localStorage.getItem('speakchain.pwa.access.v1')))
    .toBeNull();

  const handoff = scenario.requests.find(request => request.path === '/api/v1/session');
  expect(handoff?.body).toEqual({ init_data: TELEGRAM_INIT_DATA });
  const payload = scenario.requests.find(request => request.path === '/miniapp_payload');
  expect(payload?.body).toMatchObject({ uid: 9001, init_data: TELEGRAM_INIT_DATA, screen: 's-home' });
  expect(payload?.body).not.toHaveProperty('pwa_access_token');
});

test('native keyboard navigation reaches Chainy, Progress and Profile', async ({ appPage: page, context, scenario }) => {
  scenario.allowedHttpConsoleErrors = 1;
  await installBrowserSession(context);
  await page.goto('/index_v2.html');

  const chainy = page.locator('.nav button[data-s="s-buddy"]');
  await chainy.focus();
  await expect(chainy).toBeFocused();
  await chainy.press('Enter');
  await expect(page.locator('#s-buddy')).toHaveClass(/\bon\b/);
  await expect(page.locator('#tb-title')).toHaveText('Chainy');

  const progress = page.locator('.nav button[data-s="s-prog"]');
  await page.keyboard.press('Tab');
  await expect(page.locator('.nav button[data-s="s-social"]')).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(progress).toBeFocused();
  await progress.press('Enter');
  await expect(page.locator('#s-prog')).toHaveClass(/\bon\b/);
  await expect(page.locator('#tb-title')).toHaveText('Прогрес');

  const profile = page.locator('#tb-profile');
  await profile.focus();
  await expect(profile).toBeFocused();
  await profile.press('Enter');
  await expect(page.locator('#s-profile')).toHaveClass(/\bon\b/);
  await expect(page.locator('#p-nm')).toHaveText('E2E Learner');
});

test('Telegram native navigation reaches Chainy, Progress and Profile with initData identity', async ({ appPage: page, context, scenario }) => {
  scenario.sessionMode = 'unavailable';
  // Session handoff and the intentionally unconfigured Realtime greeting
  // each fail closed before the verified initData/text path continues.
  scenario.allowedHttpConsoleErrors = 2;
  await installTelegramMiniApp(context);
  await page.goto('/index_v2.html');

  await page.locator('.nav button[data-s="s-buddy"]').click();
  await expect(page.locator('#s-buddy')).toHaveClass(/\bon\b/);
  await expect(page.locator('#tb-title')).toHaveText('Chainy');
  await page.evaluate(() => window.closeOv());

  await page.locator('.nav button[data-s="s-prog"]').click();
  await expect(page.locator('#s-prog')).toHaveClass(/\bon\b/);
  await expect(page.locator('#tb-title')).toHaveText('Прогрес');

  await page.locator('#tb-profile').click();
  await expect(page.locator('#s-profile')).toHaveClass(/\bon\b/);
  await expect(page.locator('#p-nm')).toHaveText('E2E Learner');

  const payloads = scenario.requests.filter(request => request.path === '/miniapp_payload');
  expect(payloads.length).toBeGreaterThanOrEqual(3);
  for (const request of payloads) {
    expect(request.body).toMatchObject({ uid: 9001, init_data: TELEGRAM_INIT_DATA });
    expect(request.body).not.toHaveProperty('pwa_access_token');
  }
});

test('failed payload retries surface a recovery control and recover without reload', async ({ appPage: page, context, scenario }) => {
  scenario.payloadFailures.set('s-home', 2);
  scenario.allowedHttpConsoleErrors = 2;
  await installBrowserSession(context);
  await page.goto('/index_v2.html');

  const banner = page.locator('#offline-banner');
  await expect(banner).toBeVisible();
  await expect(banner).toContainText('temporary fixture failure');
  await banner.getByRole('button', { name: 'Повторити' }).click();

  await expect(banner).toBeHidden();
  await expect(page.locator('#s-home')).toHaveClass(/\bon\b/);
  const homeRequests = scenario.requests.filter(request =>
    request.path === '/miniapp_payload' && request.body.screen === 's-home');
  expect(homeRequests).toHaveLength(3);
});

test('Telegram payload failure recovers without reload and preserves verified initData', async ({ appPage: page, context, scenario }) => {
  scenario.sessionMode = 'unavailable';
  scenario.payloadFailures.set('s-home', 2);
  scenario.allowedHttpConsoleErrors = 3;
  await installTelegramMiniApp(context);
  await page.goto('/index_v2.html');

  const banner = page.locator('#offline-banner');
  await expect(banner).toBeVisible();
  await expect(banner).toContainText('temporary fixture failure');
  await banner.getByRole('button', { name: 'Повторити' }).click();

  await expect(banner).toBeHidden();
  await expect(page.locator('#s-home')).toHaveClass(/\bon\b/);
  const homeRequests = scenario.requests.filter(request =>
    request.path === '/miniapp_payload' && request.body.screen === 's-home');
  expect(homeRequests).toHaveLength(3);
  for (const request of homeRequests) {
    expect(request.body).toMatchObject({ uid: 9001, init_data: TELEGRAM_INIT_DATA });
    expect(request.body).not.toHaveProperty('pwa_access_token');
  }
});
