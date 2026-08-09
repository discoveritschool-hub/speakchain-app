const {
  expect,
  installBrowserSession,
  installTelegramMiniApp,
  test
} = require('./fixtures/critical-app.js');

const surfaces = [
  ['pwa-session-fixture', installBrowserSession],
  ['telegram-initdata-synthetic', installTelegramMiniApp]
];

function criticalAssertion(_id, assertion) {
  return assertion();
}

test('L1-13 auth deny keeps protected shell closed', async ({ appPage: page, scenario }) => {
  await page.goto('/index_v2.html?s=s-profile');

  await criticalAssertion('auth.gate_visible', () => expect(page.locator('#sc-auth-gate')).toBeVisible());
  await criticalAssertion('auth.gate_topmost', async () => {
    const secure = await page.locator('#sc-auth-gate').evaluate(gate => {
      const rect = gate.getBoundingClientRect();
      const top = document.elementFromPoint(innerWidth / 2, innerHeight / 2);
      return (
        getComputedStyle(gate).position === 'fixed'
        && Number(getComputedStyle(gate).zIndex) >= 10000
        && rect.left === 0 && rect.top === 0
        && rect.width === innerWidth && rect.height === innerHeight
        && (top === gate || gate.contains(top))
      );
    });
    expect(secure).toBe(true);
  });
  criticalAssertion('auth.no_payload', () => expect(
    scenario.requests.filter(request => request.path === '/miniapp_payload')
  ).toEqual([]));
  criticalAssertion('auth.no_authenticated_request', () => expect(scenario.requests.filter(request =>
    request.headers.authorization || request.body.init_data || request.body.pwa_access_token
  )).toEqual([]));
});

for (const [surface, install] of surfaces) {
  test(`L1-13 synthetic deeplinks have PWA and Telegram frontend parity (${surface})`, async ({
    appPage: page, context, scenario
  }) => {
    // Opening Chainy intentionally probes the unconfigured Realtime endpoint;
    // the fixture verifies that exact 503 and the safe text fallback.
    scenario.allowedHttpConsoleErrors = 1;
    await install(context);
    await page.goto('/index_v2.html?s=s-profile');

    await criticalAssertion('deeplink.auth_gate_absent', () => expect(page.locator('#sc-auth-gate')).toHaveCount(0));
    await criticalAssertion('deeplink.profile_open', () => expect(page.locator('#s-profile')).toHaveClass(/\bon\b/));
    await criticalAssertion('deeplink.profile_identity', () => expect(page.locator('#p-nm')).toHaveText('E2E Learner'));
    await page.locator('.nav button[data-s="s-buddy"]').click();
    await criticalAssertion('deeplink.chainy_open', () => expect(page.locator('#s-buddy')).toHaveClass(/\bon\b/));
    await criticalAssertion('deeplink.chainy_title', () => expect(page.locator('#tb-title')).toHaveText('Chainy'));
  });

  test(`L1-13 learner safety surfaces remain gated and opening plans never charges (${surface})`, async ({
    appPage: page, context, scenario
  }) => {
    scenario.allowedHttpConsoleErrors = 1;
    await install(context);
    await page.goto('/index_v2.html?s=s-profile');

    await criticalAssertion('learner.staff_workspace_hidden', () =>
      expect(page.locator('#role-workspace')).not.toHaveClass(/\bon\b/));
    await page.locator('button.plan-btn', { hasText: 'Обрати план' }).click();
    await criticalAssertion('paywall.opened', () => expect(page.locator('#ov-plans')).toHaveClass(/\bon\b/));
    criticalAssertion('paywall.no_charge_request', () => expect(scenario.requests.filter(request =>
      /\/(?:pay|checkout|wayforpay|lottery_buy_ticket)(?:\/|$)/.test(request.path)
    )).toEqual([]));

    await page.evaluate(() => window.closeOv());
    await page.locator('.nav button[data-s="s-buddy"]').click();
    await criticalAssertion('rooms.entry_hidden', () => expect(page.locator('#chainy-live-next')).toBeHidden());
  });
}
