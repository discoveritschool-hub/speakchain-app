const {
  expect, installBrowserSession, installTelegramMiniApp, test
} = require('./fixtures/critical-app');

async function enableBuild(context) {
  await context.addInitScript(() => { window.SC_ACCOUNT_LINKING_BUILD_ENABLED = true; });
}

async function openProfile(page) {
  await page.goto('/index_v2.html?s=s-profile');
  await expect(page.locator('#s-profile')).toHaveClass(/\bon\b/);
}

async function consentAndStart(page) {
  await page.locator('#account-link-consent').check();
  await page.locator('#account-link-start').click();
  await expect(page.locator('#account-link-verify')).toBeVisible();
}

function linkingRequests(scenario, path) {
  return scenario.requests.filter(request => request.path === path);
}

test('account linking stays absent unless both build and backend gates are enabled', async ({ appPage: page, context, scenario }) => {
  await installBrowserSession(context, 7001, 'google');
  scenario.accountLinkingEnabled = true;
  await openProfile(page);
  await expect(page.locator('#account-linking-card')).toHaveCount(0);

  await page.reload();
  scenario.accountLinkingEnabled = false;
  await expect(page.locator('#account-linking-card')).toHaveCount(0);
  expect(linkingRequests(scenario, '/api/v1/account-link/intents')).toHaveLength(0);
});

test('route-absent backend hides the gated card without claiming a merge', async ({ appPage: page, context, scenario }) => {
  await installBrowserSession(context, 7001, 'google');
  await enableBuild(context);
  scenario.accountLinkingEnabled = true;
  scenario.accountLinkRouteAbsent = true;
  scenario.allowedHttpConsoleErrors = 1;
  await openProfile(page);
  await expect(page.locator('#account-link-source')).toHaveText('Google');
  await expect(page.locator('#account-link-target')).toHaveText('Telegram');
  await page.locator('#account-link-consent').check();
  await page.locator('#account-link-start').click();
  await expect(page.locator('#account-linking-card')).toBeHidden();
  await expect(page.locator('text=Прогрес доступний з обох способів входу')).toHaveCount(0);
});

test('browser Google session submits synthetic Telegram target only after explicit consent and server confirmation', async ({ appPage: page, context, scenario }) => {
  await installBrowserSession(context, 7001, 'google');
  await enableBuild(context);
  scenario.accountLinkingEnabled = true;
  await openProfile(page);

  await expect(page.locator('#account-link-start')).toBeDisabled();
  await consentAndStart(page);
  await page.evaluate(() => window.SC_ACCOUNT_LINKING.telegramTarget({
    id: 9001, first_name: '<img src=x onerror=alert(1)>', auth_date: 1786104000, hash: 'signed-e2e'
  }));
  await expect(page.locator('#account-link-status')).toContainText('Сервер підтвердив підключення');
  await expect(page.locator('#account-link-status')).toHaveClass(/success/);

  const intents = linkingRequests(scenario, '/api/v1/account-link/intents');
  const completions = linkingRequests(scenario, '/api/v1/account-link/complete');
  expect(intents).toHaveLength(1);
  expect(intents[0].headers.authorization).toBe('Bearer access-stored');
  expect(intents[0].body).toEqual({target_provider: 'telegram', consent: true});
  expect(completions).toHaveLength(1);
  expect(completions[0].headers.authorization).toBe('Bearer access-stored');
  expect(completions[0].body.link_token).toBe('intent-token-e2e');
  expect(completions[0].body).not.toHaveProperty('uid');
  expect(completions[0].body).not.toHaveProperty('pwa_access_token');
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText('intent-token-e2e');

  await page.evaluate(() => window.SC_ACCOUNT_LINKING.telegramTarget({id: 9001}));
  expect(linkingRequests(scenario, '/api/v1/account-link/complete')).toHaveLength(1);
});

test('Telegram Mini App links Google with the same provider-bound contract', async ({ appPage: page, context, scenario }) => {
  await installTelegramMiniApp(context, 9001);
  await enableBuild(context);
  scenario.accountLinkingEnabled = true;
  await openProfile(page);
  await expect(page.locator('#account-link-source')).toHaveText('Telegram');
  await expect(page.locator('#account-link-target')).toHaveText('Google');
  await consentAndStart(page);
  await page.evaluate(() => window.SC_ACCOUNT_LINKING.googleTarget({credential: 'synthetic-google-e2e'}));
  await expect(page.locator('#account-link-status')).toContainText('Сервер підтвердив підключення');

  const completion = linkingRequests(scenario, '/api/v1/account-link/complete')[0];
  expect(completion.headers.authorization).toBe('Bearer access-telegram-mini');
  expect(completion.body).toEqual({link_token: 'intent-token-e2e', credential: 'synthetic-google-e2e'});
  expect(completion.body).not.toHaveProperty('init_data');
  expect(completion.body).not.toHaveProperty('uid');
});

test('transient completion can replay the same single-use intent without an optimistic claim', async ({ appPage: page, context, scenario }) => {
  await installBrowserSession(context, 7001, 'google');
  await enableBuild(context);
  scenario.accountLinkingEnabled = true;
  scenario.accountLinkCompleteResponses.push(
    {status: 503, code: 'persistence_unavailable'},
    {body: {ok: true, outcome: 'merged', canonical_user_id: 7001, merge_id: 'merge-e2e', replayed: true}}
  );
  scenario.allowedHttpConsoleErrors = 1;
  await openProfile(page);
  await consentAndStart(page);
  await page.evaluate(() => window.SC_ACCOUNT_LINKING.telegramTarget({id: 9001, auth_date: 1786104000, hash: 'signed-e2e'}));
  await expect(page.locator('#account-link-status')).toContainText('безпечно повторити');
  await expect(page.locator('#account-link-status')).not.toContainText('Сервер підтвердив');
  await page.locator('#account-link-retry').click();
  await expect(page.locator('#account-link-status')).toContainText('Сервер підтвердив підключення');

  const completions = linkingRequests(scenario, '/api/v1/account-link/complete');
  expect(completions).toHaveLength(2);
  expect(completions[0].body).toEqual(completions[1].body);
});

for (const failure of [
  ['intent_expired', 410, 'Час підтвердження минув'],
  ['cross_user_rejected', 409, 'іншій сесії'],
  ['identity_conflict', 409, 'пов’язаний з іншим профілем'],
]) {
  test(`${failure[0]} clears the intent and never renders backend-controlled HTML`, async ({ appPage: page, context, scenario }) => {
    await installBrowserSession(context, 7001, 'google');
    await enableBuild(context);
    scenario.accountLinkingEnabled = true;
    scenario.accountLinkCompleteResponses.push({
      status: failure[1], code: failure[0], message: '<img src=x onerror=alert(1)>'
    });
    scenario.allowedHttpConsoleErrors = 1;
    await openProfile(page);
    await consentAndStart(page);
    await page.evaluate(() => window.SC_ACCOUNT_LINKING.telegramTarget({id: 9001, auth_date: 1786104000, hash: 'signed-e2e'}));
    await expect(page.locator('#account-link-status')).toContainText(failure[2]);
    await expect(page.locator('#account-link-start')).toBeVisible();
    await expect(page.locator('#account-link-start')).toBeDisabled();
    await expect(page.locator('img[src="x"]')).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText('intent-token-e2e');
  });
}
