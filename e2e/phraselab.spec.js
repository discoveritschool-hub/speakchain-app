const {
  expect,
  installBrowserSession,
  installTelegramMiniApp,
  test
} = require('./fixtures/critical-app.js');

const topicIds = Array.from({ length: 16 }, (_, index) => String(index + 1).padStart(2, '0'));

test('completed challenge participant can open every workbook deep-linked situation', async ({ appPage: page, context, scenario }) => {
  scenario.phraselabAccess = {
    ok: true, access: true, reason: 'challenge_gift', purchase_price_usd: 7
  };
  await installTelegramMiniApp(context);

  for (const topicId of topicIds) {
    await page.goto(`/phraselab.html?topic=${topicId}`);
    await expect(page.locator('.topic-select')).toHaveValue(topicId);
    await expect(page.locator('.topic-select option')).toHaveCount(16);
    await expect(page.locator('.phrases .phrase')).toHaveCount(12);
  }

  const accessRequests = scenario.requests.filter(request => request.path === '/phraselab_access');
  expect(accessRequests).toHaveLength(16);
  expect(accessRequests.every(request => request.body.init_data)).toBe(true);
});

test('paid student opens bonus situation 16 without another purchase', async ({ appPage: page, context, scenario }) => {
  scenario.phraselabAccess = {
    ok: true, access: true, reason: 'student_plan', purchase_price_usd: 7
  };
  await installBrowserSession(context);

  await page.goto('/phraselab.html?topic=16');

  await expect(page.locator('.topic-select')).toHaveValue('16');
  await expect(page.locator('h1')).toHaveText('Пошта й доставка');
  await expect(page.locator('.gate-card')).toHaveCount(0);
  const accessRequest = scenario.requests.find(request => request.path === '/phraselab_access');
  expect(accessRequest?.body).toMatchObject({ uid: 7001, pwa_access_token: 'access-stored' });
});

test('new visitor stays locked and keeps the requested deep link', async ({ appPage: page, context, scenario }) => {
  scenario.phraselabAccess = {
    ok: true, access: false, reason: 'locked', purchase_price_usd: 7
  };
  await installBrowserSession(context, 7100);

  await page.goto('/phraselab.html?topic=14');

  await expect(page.locator('.gate-card')).toBeVisible();
  await expect(page.locator('.gate-card')).toContainText('PhraseLab чекає на тебе');
  await expect(page.locator('.gate-card a')).toHaveCount(2);
  await expect(page.locator('.gate-card a').first()).toHaveAttribute('href', /start=phraselab_14$/);
  await expect(page.locator('.topic-select')).toHaveCount(0);
});
