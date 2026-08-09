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

for (const entry of [
  { name: 'PWA', install: installBrowserSession },
  { name: 'Telegram', install: installTelegramMiniApp }
]) {
  test(`${entry.name} notification opens unscripted free conversation directly`, async ({ appPage: page, context }) => {
    await entry.install(context);
    await page.goto('/index_v2.html?s=s-buddy&practice_mode=free_conversation');
    await expectFreeConversation(page);
    await criticalAssertion('deeplink.pwa_tma_parity', () =>
      expect(page.locator('#tb-title')).toHaveText('Chainy'));
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
