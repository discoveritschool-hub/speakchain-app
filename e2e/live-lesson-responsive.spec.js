const { test, expect } = require('@playwright/test');

const activity = {
  slug: 'grammar-live-week-1', title: 'Week 1', version: 1,
  spec: {
    steps: [{
      id: 'shared_context', type: 'information', live_phase: 'context',
      title: 'Спільний контекст', body: 'Починаємо з однієї ситуації для всіх.'
    }],
    run_of_show: [{start_minute: 0, duration_minutes: 60, title: 'Урок', interaction: 'Кліки й мовлення'}],
    speaking_mission: {prompt: 'Запиши коротку відповідь.'},
    personal_routes: {}, language_ladder: []
  }
};

async function mockLiveApi(page) {
  let status = 'scheduled';
  await page.route('https://telegram.org/**', route => route.fulfill({contentType: 'application/javascript', body: ''}));
  await page.route('https://speakchain-bot-production.up.railway.app/vocab_data', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({due: [], phrases: []})
  }));
  await page.route('https://api.test/api/v1/live-sessions/DEMO/register', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ok: true, learner_route: {key: 'A1', label: 'A1', steps: []}})
  }));
  // Playwright resolves matching routes in reverse registration order, so the
  // broad GET fixture is registered before the two mutation fixtures.
  await page.route('https://api.test/api/v1/live-sessions/DEMO/host**', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({
      ok: true, session: {title: 'Масовий індивідуальний урок', status, invite_code: 'DEMO'},
      control: {current_step_id: 'shared_context'}, activity,
      step_stats: {}, personal_learning: {}, questions: [], question_stats: {}
    })
  }));
  await page.route('https://api.test/api/v1/live-sessions/DEMO/host/status**', async route => {
    const body = route.request().postDataJSON();
    status = body.status;
    await route.fulfill({contentType: 'application/json', body: JSON.stringify({
      ok: true, session: {title: 'Масовий індивідуальний урок', status, invite_code: 'DEMO'}
    })});
  });
  await page.route('https://api.test/api/v1/live-sessions/DEMO/host/step**', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ok: true, control: {current_step_id: 'shared_context'}})
  }));
  await page.route('https://api.test/api/v1/live-sessions/DEMO', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({
      ok: true, session: {
        title: 'Масовий індивідуальний урок', status, effective_status: 'live',
        control: {current_step_id: 'shared_context'}, activity
      }
    })
  }));
}

async function expectNoHorizontalOverflow(page) {
  await expect.poll(() => page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth
  }))).toEqual(await page.evaluate(() => ({viewport: window.innerWidth, document: window.innerWidth})));
}

test('private host console is operable without horizontal overflow', async ({ page }) => {
  await mockLiveApi(page);
  await page.goto('/live_host.html?session=DEMO&api=https%3A%2F%2Fapi.test&host_token=test');
  await expect(page.getByText('Спільний контекст', {exact: true})).toBeVisible();
  await expect(page.locator('#start')).toBeVisible();
  await expect(page.locator('#present')).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await page.locator('#start').click();
  await expect(page.locator('#sessionStatus')).toContainText('Ефір триває');
});

test('clean broadcast screen is responsive and contains no private controls', async ({ page }) => {
  await mockLiveApi(page);
  await page.goto('/live_present.html?session=DEMO&api=https%3A%2F%2Fapi.test&host_token=test');
  await expect(page.getByText('Спільний контекст', {exact: true})).toBeVisible();
  await expect(page.locator('#join')).toContainText('код DEMO');
  await expect(page.locator('#start')).toHaveCount(0);
  await expect(page.locator('#next')).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test('learner screen stays touch-safe and synchronized', async ({ page }) => {
  await mockLiveApi(page);
  await page.goto('/live_activity.html?session=DEMO&api=https%3A%2F%2Fapi.test');
  await expect(page.getByText('Спільний контекст', {exact: true})).toBeVisible();
  await expect(page.locator('#connection')).toContainText('Синхронізовано');
  await expect(page.locator('#askOpen')).toBeVisible();
  await expectNoHorizontalOverflow(page);
});
