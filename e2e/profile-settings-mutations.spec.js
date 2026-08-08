const {
  expect,
  installBrowserSession,
  installTelegramMiniApp,
  TELEGRAM_INIT_DATA,
  test
} = require('./fixtures/critical-app.js');

const profileMutations = scenario => scenario.requests.filter(request =>
  request.path === '/miniapp_action' && request.body.action === 'profile_settings_update'
);

async function openProfile(page) {
  await page.goto('/index_v2.html');
  await page.locator('#tb-profile').click();
  await expect(page.locator('#s-profile')).toHaveClass(/\bon\b/);
  await expect(page.locator('#profile-utc-offset')).toHaveValue('2');
  await expect(page.locator('#profile-notification-pref')).toHaveValue('evening');
}

test('Telegram profile mutation uses verified initData without body uid', async ({ appPage: page, context, scenario }) => {
  await installTelegramMiniApp(context);
  await openProfile(page);

  await page.locator('#profile-utc-offset').selectOption('3');
  await page.locator('#profile-notification-pref').selectOption('off');
  await expect(page.locator('#profile-settings-save')).toBeEnabled();
  await page.locator('#profile-settings-save').click();

  await expect(page.locator('#profile-settings-status')).toHaveText('Налаштування збережено.');
  await expect(page.locator('#profile-settings-status')).toHaveClass(/success/);
  await expect(page.locator('#p-timezone')).toHaveText('UTC+3');
  const requests = profileMutations(scenario);
  expect(requests).toHaveLength(1);
  expect(requests[0].body).toMatchObject({
    action: 'profile_settings_update',
    settings: { utc_offset: 3, notification_pref: 'off' },
    expected_revision: 0,
    init_data: TELEGRAM_INIT_DATA
  });
  expect(requests[0].body.mutation_id).toMatch(/^[A-Za-z0-9][A-Za-z0-9._:-]{15,63}$/);
  expect(requests[0].body).not.toHaveProperty('uid');
  expect(requests[0].body).not.toHaveProperty('pwa_access_token');
});

test('browser PWA profile mutation carries its access token and no uid', async ({ appPage: page, context, scenario }) => {
  await installBrowserSession(context);
  await openProfile(page);

  await page.locator('#profile-notification-pref').selectOption('on_request');
  await page.locator('#profile-settings-save').click();

  await expect(page.locator('#profile-settings-status')).toHaveText('Налаштування збережено.');
  const requests = profileMutations(scenario);
  expect(requests).toHaveLength(1);
  expect(requests[0].body).toMatchObject({
    action: 'profile_settings_update',
    settings: { notification_pref: 'on_request' },
    expected_revision: 0,
    pwa_access_token: 'access-stored'
  });
  expect(requests[0].body.mutation_id).toMatch(/^[A-Za-z0-9][A-Za-z0-9._:-]{15,63}$/);
  expect(requests[0].body).not.toHaveProperty('uid');
  expect(requests[0].body).not.toHaveProperty('init_data');
});

test('backend error keeps authoritative value and offers an explicit retry', async ({ appPage: page, context, scenario }) => {
  scenario.profileMutationFailures.push({ status: 503, error: 'temporary_failure' });
  scenario.allowedHttpConsoleErrors = 1;
  await installBrowserSession(context);
  await openProfile(page);

  await page.locator('#profile-utc-offset').selectOption('5');
  await page.locator('#profile-settings-save').click();

  await expect(page.locator('#profile-settings-status')).toContainText('Результат запиту невідомий');
  await expect(page.locator('#profile-settings-status')).toHaveClass(/error/);
  await expect(page.locator('#profile-settings-save')).toHaveText('Перевірити й повторити');
  await expect(page.locator('#p-timezone')).toHaveText('UTC+2');
  await expect(page.locator('#profile-utc-offset')).toHaveValue('5');
  await expect(page.locator('#profile-utc-offset')).toBeDisabled();
  expect(profileMutations(scenario)).toHaveLength(1);

  await page.locator('#profile-settings-save').click();
  await expect(page.locator('#profile-settings-status')).toHaveText('Налаштування збережено.');
  await expect(page.locator('#p-timezone')).toHaveText('UTC+5');
  const retried = profileMutations(scenario);
  expect(retried).toHaveLength(2);
  expect(retried[1].body.mutation_id).toBe(retried[0].body.mutation_id);
  expect(retried[1].body.expected_revision).toBe(retried[0].body.expected_revision);
});

test('hung profile save times out once and enables retry only after the terminal abort', async ({ appPage: page, context, scenario }) => {
  scenario.profileMutationResponses.push({ delayMs: 1500 });
  await context.addInitScript(() => {
    window.__SPEAKCHAIN_E2E_PROFILE_SAVE_TIMEOUT_MS = 1000;
  });
  await installBrowserSession(context);
  await openProfile(page);

  await page.locator('#profile-utc-offset').selectOption('4');
  await page.locator('#profile-settings-save').click();
  await expect(page.locator('#profile-settings-save')).toBeDisabled();
  await expect(page.locator('#profile-settings-save')).toHaveText('Зберігаємо…');
  expect(profileMutations(scenario)).toHaveLength(1);

  await expect(page.locator('#profile-settings-status')).toContainText('Не вдалося зберегти вчасно');
  await expect(page.locator('#profile-settings-status')).toHaveClass(/error/);
  await expect(page.locator('#profile-settings-save')).toBeEnabled();
  await expect(page.locator('#profile-settings-save')).toHaveText('Перевірити й повторити');
  expect(profileMutations(scenario)).toHaveLength(1);

  await page.locator('#profile-settings-save').click();
  await expect(page.locator('#profile-settings-status')).toHaveText('Налаштування збережено.');
  await expect(page.locator('#p-timezone')).toHaveText('UTC+4');
  const retried = profileMutations(scenario);
  expect(retried).toHaveLength(2);
  expect(retried[1].body.mutation_id).toBe(retried[0].body.mutation_id);
});

test('delayed first request, safe replay and a newer write survive a fresh authoritative reload', async ({ appPage: page, context, scenario }) => {
  scenario.profileMutationResponses.push({ delayMs: 4000 });
  await context.addInitScript(() => {
    window.__SPEAKCHAIN_E2E_PROFILE_SAVE_TIMEOUT_MS = 3000;
  });
  await installBrowserSession(context);
  await openProfile(page);

  await page.locator('#profile-utc-offset').selectOption('5');
  await page.locator('#profile-settings-save').click();
  await page.locator('.nav button[data-s="s-home"]').click();
  await page.locator('#tb-profile').click();
  await expect(page.locator('#profile-utc-offset')).toHaveValue('5');
  await expect(page.locator('#profile-utc-offset')).toBeDisabled();
  await expect(page.locator('#profile-settings-save')).toHaveText('Зберігаємо…');

  await page.evaluate(() => {
    saveProfileSettings({ preventDefault() {} });
    saveProfileSettings({ preventDefault() {} });
  });
  expect(profileMutations(scenario)).toHaveLength(1);

  await expect(page.locator('#profile-settings-save')).toHaveText('Перевірити й повторити');
  await page.locator('#profile-settings-save').click();
  await expect(page.locator('#profile-settings-status')).toHaveText('Налаштування збережено.');
  await expect(page.locator('#p-timezone')).toHaveText('UTC+5');

  await page.locator('#profile-utc-offset').selectOption('6');
  await page.locator('#profile-settings-save').click();
  await expect(page.locator('#profile-settings-status')).toHaveText('Налаштування збережено.');
  await expect(page.locator('#p-timezone')).toHaveText('UTC+6');
  await page.waitForTimeout(4200);
  await page.evaluate(() => {
    delete PAYLOAD['s-profile'];
    delete PENDING['s-profile'];
  });
  await page.locator('.nav button[data-s="s-home"]').click();
  await page.locator('#tb-profile').click();
  await expect(page.locator('#p-timezone')).toHaveText('UTC+6');
  await expect(page.locator('#profile-utc-offset')).toHaveValue('6');
  expect(scenario.profileSettings.utc_offset).toBe(6);
  expect(scenario.profileSettings.profile_settings_revision).toBe(2);
  const requests = profileMutations(scenario);
  expect(requests).toHaveLength(3);
  expect(requests[1].body.mutation_id).toBe(requests[0].body.mutation_id);
  expect(requests[2].body.mutation_id).not.toBe(requests[0].body.mutation_id);
  expect(requests.map(request => request.body.expected_revision)).toEqual([0, 0, 1]);
});

test('revision conflict reconciles authoritative state before allowing a new change', async ({ appPage: page, context, scenario }) => {
  scenario.allowedHttpConsoleErrors = 1;
  await installBrowserSession(context);
  await openProfile(page);
  Object.assign(scenario.profileSettings, { utc_offset: 4, profile_settings_revision: 1 });

  await page.locator('#profile-utc-offset').selectOption('5');
  await page.locator('#profile-settings-save').click();
  await expect(page.locator('#profile-settings-status')).toContainText('Актуальний стан завантажено');
  await expect(page.locator('#p-timezone')).toHaveText('UTC+4');
  await expect(page.locator('#profile-utc-offset')).toHaveValue('4');

  await page.locator('#profile-utc-offset').selectOption('6');
  await page.locator('#profile-settings-save').click();
  await expect(page.locator('#profile-settings-status')).toHaveText('Налаштування збережено.');
  await expect(page.locator('#p-timezone')).toHaveText('UTC+6');
  expect(profileMutations(scenario).map(request => request.body.expected_revision)).toEqual([0, 1]);
});

test('bounded validation blocks unsupported values and controls stay usable at 360px', async ({ appPage: page, context, scenario }) => {
  await installTelegramMiniApp(context);
  await page.setViewportSize({ width: 360, height: 800 });
  await openProfile(page);

  await page.locator('#profile-utc-offset').evaluate(select => {
    const option = document.createElement('option');
    option.value = '99';
    option.textContent = 'unsafe';
    select.appendChild(option);
    select.value = '99';
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await expect(page.locator('#profile-settings-save')).toBeDisabled();
  await expect(page.locator('#profile-settings-status')).toContainText('UTC−12 до UTC+14');
  expect(profileMutations(scenario)).toHaveLength(0);

  await expect.poll(() => page.locator('.profile-edit-grid').evaluate(node =>
    getComputedStyle(node).gridTemplateColumns.split(' ').length
  )).toBe(1);
  for (const selector of ['#profile-utc-offset', '#profile-notification-pref', '#profile-settings-save']) {
    await expect.poll(() => page.locator(selector).evaluate(node => node.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44);
  }
});
