const {
  expect,
  installBrowserSession,
  installTelegramMiniApp,
  test
} = require('./fixtures/critical-app.js');

const surfaces = [
  ['pwa', installBrowserSession],
  ['telegram', installTelegramMiniApp]
];

test('L1-13 auth deny keeps protected shell closed', async ({ appPage: page, scenario }) => {
  await page.goto('/index_v2.html?s=s-profile');

  await expect(page.locator('#sc-auth-gate')).toBeVisible();
  await expect(page.locator('#s-profile')).not.toHaveClass(/\bon\b/);
  expect(scenario.requests.filter(request => request.path === '/miniapp_payload')).toEqual([]);
});

for (const [surface, install] of surfaces) {
  test(`L1-13 authenticated deeplinks have PWA and Telegram parity (${surface})`, async ({
    appPage: page, context, scenario
  }) => {
    // Opening Chainy intentionally probes the unconfigured Realtime endpoint;
    // the fixture verifies that exact 503 and the safe text fallback.
    scenario.allowedHttpConsoleErrors = 1;
    await install(context);
    await page.goto('/index_v2.html?s=s-profile');

    await expect(page.locator('#sc-auth-gate')).toHaveCount(0);
    await expect(page.locator('#s-profile')).toHaveClass(/\bon\b/);
    await expect(page.locator('#p-nm')).toHaveText('E2E Learner');
    await page.locator('.nav button[data-s="s-buddy"]').click();
    await expect(page.locator('#s-buddy')).toHaveClass(/\bon\b/);
    await expect(page.locator('#tb-title')).toHaveText('Chainy');
  });

  test(`L1-13 learner safety surfaces remain gated and opening plans never charges (${surface})`, async ({
    appPage: page, context, scenario
  }) => {
    scenario.allowedHttpConsoleErrors = 1;
    await install(context);
    await page.goto('/index_v2.html?s=s-profile');

    await expect(page.locator('#role-workspace')).not.toHaveClass(/\bon\b/);
    await page.locator('button.plan-btn', { hasText: 'Обрати план' }).click();
    await expect(page.locator('#ov-plans')).toHaveClass(/\bon\b/);
    expect(scenario.requests.filter(request =>
      /\/(?:pay|checkout|wayforpay|lottery_buy_ticket)(?:\/|$)/.test(request.path)
    )).toEqual([]);

    await page.evaluate(() => window.closeOv());
    await page.locator('.nav button[data-s="s-buddy"]').click();
    await expect(page.locator('#chainy-live-next')).toBeHidden();
  });
}
