const {
  expect,
  installBrowserSession,
  installTelegramMiniApp,
  test
} = require('./fixtures/critical-app.js');

async function delayPwaReady(context, delayMs) {
  await context.addInitScript(delay => {
    let current;
    Object.defineProperty(window, 'SC_PWA', {
      configurable: true,
      get() { return current; },
      set(next) {
        if (next?.ready) {
          const nativeReady = next.ready;
          next.ready = new Promise(resolve => {
            setTimeout(() => Promise.resolve(nativeReady).then(resolve), delay);
          });
        }
        current = next;
      }
    });
  }, delayMs);
}

test('PWA profile deep link activates before delayed auth and stale home payload', async ({ appPage: page, context, scenario }) => {
  await installBrowserSession(context);
  await delayPwaReady(context, 700);
  scenario.payloadDelays.set('s-home', 1800);
  scenario.payloadDelays.set('s-profile', 40);

  await page.goto('/index_v2.html?s=s-profile');
  await expect(page.locator('#s-profile')).toHaveClass(/\bon\b/, { timeout: 350 });
  await expect(page.locator('#s-home')).not.toHaveClass(/\bon\b/);
  await expect(page.locator('#p-nm')).toHaveText('E2E Learner', { timeout: 4000 });
  await page.waitForTimeout(1900);
  await expect(page.locator('#s-profile')).toHaveClass(/\bon\b/);
  await expect(page.locator('#s-home')).not.toHaveClass(/\bon\b/);
});

test('Telegram buddy deep link survives delayed payloads and uses supported fullscreen', async ({ appPage: page, context, scenario }) => {
  await installTelegramMiniApp(context);
  scenario.payloadDelays.set('s-home', 1600);
  scenario.payloadDelays.set('s-buddy', 80);

  // Start a real slow Home request, then reproduce a TMA deep-link handoff
  // while that stale response is still in flight.
  await page.goto('/index_v2.html?s=s-home');
  await expect.poll(() => scenario.requests.filter(request =>
    request.path.endsWith('/miniapp_payload') && request.body.screen === 's-home'
  ).length).toBeGreaterThan(0);
  await page.evaluate(() => {
    history.replaceState(null, '', '/index_v2.html?s=s-buddy');
    return go('s-buddy');
  });
  await expect(page.locator('#s-buddy')).toHaveClass(/\bon\b/, { timeout: 350 });
  await expect(page.locator('#s-home')).not.toHaveClass(/\bon\b/);
  await expect.poll(() => page.evaluate(() => window.__telegramFullscreenCalls || 0)).toBe(1);
  await page.waitForTimeout(1800);
  await expect(page.locator('#s-buddy')).toHaveClass(/\bon\b/);
  await expect(page.locator('#s-home')).not.toHaveClass(/\bon\b/);
});

test('Telegram 6.0 capability guard never calls the exposed unsupported fullscreen method', async ({ appPage: page, context }) => {
  await installTelegramMiniApp(context, 9001, { version: '6.0' });

  await page.goto('/index_v2.html');
  expect(await page.evaluate(() => window.__telegramFullscreenCalls || 0)).toBe(0);
  expect(await page.evaluate(() => ({
    six: window.SC_canRequestTelegramFullscreen({
      version: '6.0', requestFullscreen() {}
    }),
    eight: window.SC_canRequestTelegramFullscreen({
      version: '8.0', requestFullscreen() {}
    }),
    sdk: window.SC_canRequestTelegramFullscreen(window.Telegram.WebApp)
  }))).toEqual({ six: false, eight: true, sdk: false });
});

test('Telegram 8.0 fullscreen failure is reported without blocking a deep link', async ({ appPage: page, context }) => {
  await installTelegramMiniApp(context, 9001, {
    version: '8.0',
    fullscreenThrows: 'fullscreen denied by client'
  });
  const warnings = [];
  page.on('console', message => {
    if (message.type() === 'warning') warnings.push(message.text());
  });

  await page.goto('/index_v2.html?s=s-buddy');
  await expect(page.locator('#s-buddy')).toHaveClass(/\bon\b/, { timeout: 350 });
  await expect(page.locator('#s-home')).not.toHaveClass(/\bon\b/);
  expect(await page.evaluate(() => window.__telegramFullscreenCalls || 0)).toBe(1);
  expect(await page.evaluate(() => window.SC_RUNTIME_REPORTS)).toEqual([{
    source: 'telegram.requestFullscreen',
    message: 'fullscreen denied by client'
  }]);
  expect(warnings.filter(message => message.includes('Telegram fullscreen unavailable'))).toHaveLength(1);
});
