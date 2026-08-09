const {
  expect,
  installBrowserSession,
  installTelegramMiniApp,
  test
} = require('./fixtures/critical-app.js');

function criticalAssertion(_id, assertion) {
  return assertion();
}

async function expectFreeConversation(page) {
  await criticalAssertion('deeplink.free_conversation_direct', async () => {
    await expect(page.locator('#s-buddy')).toHaveClass(/\bon\b/);
    await expect(page.locator('#ov-buddy')).toHaveClass(/\bon\b/);
  });
  await expect(page.locator('#ov-buddy-host #s-chat')).toHaveClass(/\bactive\b/);
  await expect(page.locator('#ov-buddy-host #chat-name')).toHaveText('Chainy');
  await expect(page.locator('#ov-buddy-host #s-home')).not.toHaveClass(/\bactive\b/);
}

test('fresh PWA notification waits behind sign-in without protected requests', async ({ appPage: page, scenario }) => {
  await page.goto('/index_v2.html?s=s-buddy&practice_mode=free_conversation');
  await criticalAssertion('deeplink.free_conversation_pre_auth_fail_closed', async () => {
    await expect(page.locator('#sc-auth-gate')).toBeVisible();
    await expect(page.locator('#s-buddy')).toHaveClass(/\bon\b/);
    await expect(page.locator('#ov-buddy')).not.toHaveClass(/\bon\b/);
  });
  await page.waitForTimeout(1200);
  expect(scenario.requests.filter(request =>
    request.path === '/miniapp_payload' || request.path === '/buddy_realtime_token'
  )).toEqual([]);
});

for (const entry of [
  { name: 'PWA', install: installBrowserSession },
  { name: 'Telegram', install: installTelegramMiniApp }
]) {
  test(`${entry.name} notification opens unscripted free conversation directly`, async ({ appPage: page, context, scenario }) => {
    // Direct Chainy startup intentionally probes the fixture's unconfigured
    // Realtime endpoint once, then proves the safe text fallback.
    scenario.allowedHttpConsoleErrors = 1;
    await entry.install(context);
    await page.goto('/index_v2.html?s=s-buddy&practice_mode=free_conversation');
    await expectFreeConversation(page);
    await criticalAssertion('deeplink.pwa_tma_parity', () =>
      expect(page.locator('#tb-title')).toHaveText('Chainy'));
  });

  test(`${entry.name} newer navigation cancels a delayed free-conversation intent`, async ({ appPage: page, context, scenario }) => {
    await entry.install(context);
    scenario.payloadDelays.set('s-buddy', 1200);
    await page.goto('/index_v2.html?s=s-buddy&practice_mode=free_conversation');
    await expect.poll(() => scenario.requests.filter(request =>
      request.path === '/miniapp_payload' && request.body.screen === 's-buddy'
    ).length).toBe(1);

    await page.locator('#tb-profile').click();
    await expect(page.locator('#s-profile')).toHaveClass(/\bon\b/);
    await expect(page.locator('#p-nm')).toHaveText('E2E Learner');
    await page.waitForTimeout(1400);
    await criticalAssertion('deeplink.notification_stale_navigation_suppressed', async () => {
      await expect(page.locator('#s-profile')).toHaveClass(/\bon\b/);
      await expect(page.locator('#ov-buddy')).not.toHaveClass(/\bon\b/);
    });
  });

  test(`${entry.name} notification exercise fallback opens the structured Practice selector`, async ({ appPage: page, context }) => {
    await entry.install(context);
    await page.goto('/index_v2.html?s=s-listen&practice_mode=exercise');
    await criticalAssertion('deeplink.exercise_structured_selector', async () => {
      await expect(page.locator('#s-listen')).toHaveClass(/\bon\b/);
      await expect(page.locator('#s-prog')).not.toHaveClass(/\bon\b/);
    });
    await criticalAssertion('deeplink.pwa_tma_parity', () =>
      expect(page.locator('#tb-title')).toHaveText('Практика'));
    await expect(page.locator('#md-active')).toBeVisible();
    await expect(page.locator('#md-passive')).toBeVisible();
    await expect(page.locator('#md-book')).toBeVisible();
  });
}
