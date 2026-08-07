const {
  expect,
  installBrowserSession,
  installTelegramMiniApp,
  test
} = require('./fixtures/critical-app.js');

test('profile settings expose supported values and honest unavailable states', async ({ appPage: page, context, scenario }) => {
  await installTelegramMiniApp(context);
  await page.goto('/index_v2.html');

  await page.locator('#tb-profile').click();
  await expect(page.locator('#s-profile')).toHaveClass(/\bon\b/);
  await expect(page.locator('#p-cefr')).toHaveText('B1');
  await expect(page.locator('#p-tariff')).toHaveText('Basic');
  await expect(page.locator('#p-session-duration')).toHaveText('Ще недоступно');
  await expect(page.locator('#p-timezone')).toHaveText('Ще недоступно');
  await expect(page.locator('#p-billing-term')).toHaveText('Ще недоступно');
  await expect(page.locator('#p-plan-expiry')).toHaveText('Ще недоступно');

  const videoGuide = page.locator('#profile-video-guide');
  await expect(videoGuide).toBeDisabled();
  await expect(videoGuide).toHaveAttribute('aria-disabled', 'true');

  await page.evaluate(() => {
    window.__profileWindowOpen = [];
    window.open = (...args) => window.__profileWindowOpen.push(args);
    PAYLOAD['s-profile'].support_bot_url = 'https://t.me.evil.example/report';
  });
  await page.locator('#profile-report-bug').click();
  await expect.poll(() => page.evaluate(() => window.__telegramLinks || []))
    .toContain('https://t.me/SpeakChain_bot');
  await expect.poll(() => page.evaluate(() => window.__profileWindowOpen))
    .toEqual([]);
  expect(scenario.requests.filter(request => request.path === '/miniapp_action'))
    .toHaveLength(0);
});

test('profile settings keep authoritative fields scalar and bounded at narrow width', async ({ appPage: page, context }) => {
  await installTelegramMiniApp(context);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto('/index_v2.html');
  await page.locator('#tb-profile').click();

  await page.evaluate(() => {
    PAYLOAD['s-profile'] = {
      ...PAYLOAD['s-profile'],
      level: 'C1',
      current_plan: 'premium',
      billing_term: '6m',
      premium_until: '2027-02-07T00:00:00Z',
      timezone: 'Europe/Kyiv',
      session_minutes: 30,
      profile_video_url: 'https://docs.speakchain.example/profile-guide',
      plan: 'wrong-plan',
      expires_at: '1999-01-01'
    };
    PAYLOAD['s-home'] = {
      ...PAYLOAD['s-home'],
      level: 'A2',
      current_plan: 'wrong-home-plan',
      expires_at: '1998-01-01',
      timezone: 'Wrong/Home',
      session_minutes: 60
    };
    renderProfileSettings(PAYLOAD['s-profile'], PAYLOAD['s-home']);
  });

  await expect(page.locator('#p-cefr')).toHaveText('C1');
  await expect(page.locator('#p-tariff')).toHaveText('Premium');
  await expect(page.locator('#p-billing-term')).toHaveText('6 місяців');
  await expect(page.locator('#p-plan-expiry')).toHaveText('07.02.2027');
  await expect(page.locator('#p-timezone')).toHaveText('Europe/Kyiv');
  await expect(page.locator('#p-session-duration')).toHaveText('30 хв');

  await page.evaluate(() => {
    window.__profileWindowOpen = [];
    window.open = (...args) => window.__profileWindowOpen.push(args);
  });
  await page.locator('#profile-video-guide').click();
  await expect.poll(() => page.evaluate(() => window.__telegramOpenLinks || []))
    .toContain('https://docs.speakchain.example/profile-guide');
  await expect.poll(() => page.evaluate(() => window.__profileWindowOpen))
    .toEqual([]);

  await page.evaluate(() => {
    PAYLOAD['s-profile'].billing_term = 'annual';
    PAYLOAD['s-profile'].premium_until = '2028-02-29T23:59:59-08:00';
    renderProfileSettings(PAYLOAD['s-profile'], PAYLOAD['s-home']);
  });
  await expect(page.locator('#p-billing-term')).toHaveText('1 рік');
  await expect(page.locator('#p-plan-expiry')).toHaveText('29.02.2028');

  await page.evaluate(() => {
    PAYLOAD['s-profile'].premium_until = '2027-02-07Tgarbage';
    renderProfileSettings(PAYLOAD['s-profile'], PAYLOAD['s-home']);
  });
  await expect(page.locator('#p-plan-expiry')).toHaveText('Ще недоступно');

  await page.evaluate(() => {
    PAYLOAD['s-profile'].billing_term = 'forever';
    PAYLOAD['s-profile'].premium_until = '2027-02-30';
    delete PAYLOAD['s-profile'].basic_until;
    renderProfileSettings(PAYLOAD['s-profile'], PAYLOAD['s-home']);
  });
  await expect(page.locator('#p-billing-term')).toHaveText('Ще недоступно');
  await expect(page.locator('#p-plan-expiry')).toHaveText('Ще недоступно');

  await page.evaluate(() => {
    delete PAYLOAD['s-profile'].timezone;
    PAYLOAD['s-profile'].utc_offset = 2;
    renderProfileSettings(PAYLOAD['s-profile'], PAYLOAD['s-home']);
  });
  await expect(page.locator('#p-timezone')).toHaveText('UTC+2');

  await page.evaluate(() => {
    PAYLOAD['s-profile'] = {
      ...PAYLOAD['s-profile'],
      level: { unsafe: true },
      current_plan: 7,
      billing_term: 'lifetime',
      premium_until: 20270207,
      basic_until: { unsafe: true },
      timezone: { unsafe: true },
      utc_offset: [2],
      session_minutes: '9999',
      profile_video_url: 'javascript:alert(1)'
    };
    PAYLOAD['s-home'] = {
      ...PAYLOAD['s-home'],
      level: ['B2'],
      session_minutes: 'not-a-number'
    };
    renderProfileSettings(PAYLOAD['s-profile'], PAYLOAD['s-home']);
  });

  for (const selector of ['#p-cefr', '#p-tariff', '#p-billing-term', '#p-plan-expiry', '#p-timezone', '#p-session-duration']) {
    await expect(page.locator(selector)).toHaveText('Ще недоступно');
  }
  await expect(page.locator('#profile-video-guide')).toBeDisabled();

  await page.evaluate(() => {
    PAYLOAD['s-profile'].utc_offset = -12;
    renderProfileSettings(PAYLOAD['s-profile'], PAYLOAD['s-home']);
  });
  await expect(page.locator('#p-timezone')).toHaveText('UTC-12');

  await page.evaluate(() => {
    PAYLOAD['s-profile'].utc_offset = 15;
    renderProfileSettings(PAYLOAD['s-profile'], PAYLOAD['s-home']);
  });
  await expect(page.locator('#p-timezone')).toHaveText('Ще недоступно');

  await page.evaluate(() => {
    PAYLOAD['s-profile'].timezone = 'Very/Long/'.repeat(20);
    renderProfileSettings(PAYLOAD['s-profile'], PAYLOAD['s-home']);
  });
  await expect.poll(() => page.locator('#p-timezone').evaluate(node => node.textContent.length))
    .toBe(64);
  await expect.poll(() => page.locator('#p-timezone').evaluate(node => getComputedStyle(node).overflowWrap))
    .toBe('anywhere');
  await expect.poll(() => page.locator('.profile-actions').evaluate(node => getComputedStyle(node).gridTemplateColumns.split(' ').length))
    .toBe(1);
});

test('profile links use sanitized Telegram SDK paths and browser fallbacks', async ({ appPage: page, context }) => {
  await installBrowserSession(context);
  await page.goto('/index_v2.html');
  await page.locator('#tb-profile').click();

  await page.evaluate(() => {
    window.__profileWindowOpen = [];
    window.open = (...args) => window.__profileWindowOpen.push(args);
    PAYLOAD['s-profile'].support_bot_url = 'https://t.me/SpeakChain_bot';
    PAYLOAD['s-profile'].profile_video_url = 'https://docs.speakchain.example/profile-guide';
    renderProfileSettings(PAYLOAD['s-profile'], PAYLOAD['s-home']);
  });

  await page.locator('#profile-report-bug').click();
  await page.locator('#profile-video-guide').click();
  await expect.poll(() => page.evaluate(() => window.__profileWindowOpen))
    .toEqual([
      ['https://t.me/SpeakChain_bot', '_blank', 'noopener'],
      ['https://docs.speakchain.example/profile-guide', '_blank', 'noopener']
    ]);
});
