const {
  E2E_CAPTION,
  E2E_VIDEO_ID,
  E2E_VIDEO_TITLE,
  expect,
  installBrowserSession,
  installTelegramMiniApp,
  TELEGRAM_INIT_DATA,
  test
} = require('./fixtures/critical-app.js');

const byPath = (scenario, path) => scenario.requests.filter(request => request.path === path);

async function runOwnVideoCycle(page, context, scenario, surface) {
  scenario.allowedHttpConsoleErrors = 1;
  if (surface === 'telegram') await installTelegramMiniApp(context);
  else await installBrowserSession(context);

  await page.goto('/index_v2.html');

  const ownVideo = page.locator('button.own-video-entry');
  await ownVideo.focus();
  await expect(ownVideo).toBeFocused();
  await ownVideo.press('Enter');
  await expect(page.locator('#ov-player')).toHaveClass(/\bon\b/);

  const player = page.frameLocator('#ov-player-host iframe[title="SpeakChain Player"]');
  await expect(player.locator('#paste-url')).toBeVisible();
  await player.locator('#paste-url').fill(`https://youtu.be/${E2E_VIDEO_ID}`);
  const start = player.locator('button.paste-go');
  await start.focus();
  await expect(start).toBeFocused();
  await start.press('Enter');

  await expect(player.locator('#caption-status')).toHaveClass(/\bready\b/);
  const englishCaptionWords = E2E_CAPTION.match(/[A-Za-z][A-Za-z'-]*/g).join(' ');
  await expect(player.locator('#transcript-text')).toHaveText(englishCaptionWords);

  const word = player.locator('.caption-word').first();
  await word.focus();
  await expect(word).toBeFocused();
  await word.press('Enter');
  await expect(player.locator('#word-card')).toHaveClass(/\bshow\b/);
  await expect(player.locator('#word-card-translation'))
    .toHaveText('\u043f\u0440\u0430\u043a\u0442\u0438\u043a\u0430');
  await player.locator('#word-card-vocab').click();
  await expect(player.locator('#word-card-vocab')).toContainText('Збережено');

  await player.locator('#phrase-save').click();
  await expect(player.locator('#phrase-save')).toHaveText('✓');
  await player.locator('#vocab-drawer-open').click();
  await expect(player.locator('#vocab-drawer-backdrop')).toHaveClass(/\bopen\b/);
  await expect(player.locator('#mini-vocab-list')).toContainText('practice');
  await expect(player.locator('#mini-vocab-list')).toContainText(englishCaptionWords);
  await player.locator('#vocab-drawer-close').click();
  await expect(player.locator('#vocab-drawer-backdrop')).not.toHaveClass(/\bopen\b/);

  const validContext = {
    type: 'speakchain-video-context', version: 'v1', video_id: E2E_VIDEO_ID,
    title: E2E_VIDEO_TITLE, mode: 'practice_phrase', phrases: [E2E_CAPTION],
    current_time: 12, resource_kind: 'video'
  };
  const malformedContexts = [
    { ...validContext, phrases: { 0: E2E_CAPTION } },
    { ...validContext, mode: 'system' },
    { ...validContext, title: 'x'.repeat(161) },
    { ...validContext, phrases: ['x'.repeat(301)] },
    { ...validContext, unexpected: 'field' }
  ];
  for (const payload of malformedContexts) {
    await player.locator('body').evaluate((_, data) => {
      window.parent.postMessage(data, window.location.origin);
    }, payload);
  }
  const legacyBook = {
    type: 'speakchain-book-retell', title: 'A short book excerpt', videoId: E2E_VIDEO_ID
  };
  for (const payload of [
    { ...legacyBook, title: 'x'.repeat(161) },
    { ...legacyBook, videoId: 'invalid' },
    { ...legacyBook, phrases: [] }
  ]) {
    await player.locator('body').evaluate((_, data) => {
      window.parent.postMessage(data, window.location.origin);
    }, payload);
  }

  await page.evaluate(data => {
    const source = document.querySelector('#ov-player-host > iframe[title="SpeakChain Player"]').contentWindow;
    window.dispatchEvent(new MessageEvent('message', {
      data, origin: 'https://decoy.invalid', source
    }));
  }, validContext);
  await page.evaluate(data => {
    const source = document.querySelector('#ov-player-host > iframe[title="SpeakChain Player"]').contentWindow;
    window.dispatchEvent(new MessageEvent('message', {
      data, origin: 'https://decoy.invalid', source
    }));
  }, legacyBook);

  // A same-origin iframe is still untrusted unless it is the currently
  // mounted SpeakChain player. Keep its WindowProxy and replay it after
  // detaching to cover both decoy and stale-frame sources.
  await page.evaluate(async ({ videoContext, bookContext }) => {
    const decoy = document.createElement('iframe');
    decoy.hidden = true;
    decoy.src = 'about:blank';
    document.body.appendChild(decoy);
    await new Promise(resolve => requestAnimationFrame(resolve));
    const staleSource = decoy.contentWindow;
    window.dispatchEvent(new MessageEvent('message', {
      data: videoContext, origin: window.location.origin, source: staleSource
    }));
    window.dispatchEvent(new MessageEvent('message', {
      data: bookContext, origin: window.location.origin, source: staleSource
    }));
    decoy.remove();
    window.dispatchEvent(new MessageEvent('message', {
      data: videoContext, origin: window.location.origin, source: staleSource
    }));
    window.dispatchEvent(new MessageEvent('message', {
      data: bookContext, origin: window.location.origin, source: staleSource
    }));
  }, {
    videoContext: { ...validContext, title: 'decoy context' },
    bookContext: legacyBook
  });

  await expect(page.locator('#ov-player')).toHaveClass(/\bon\b/);
  await expect(page.locator('#ov-buddy')).not.toHaveClass(/\bon\b/);
  expect(byPath(scenario, '/buddy_realtime_token')).toHaveLength(0);

  // Finishing a phrase inside the player must not open Chainy. The prompt is
  // unlocked only after the video reports ENDED and the player is closed.
  await player.locator('body').evaluate((_, data) => {
    window.parent.postMessage({ ...data, type: 'speakchain-video-completed', mode: 'discuss' }, window.location.origin);
  }, validContext);
  await expect(page.locator('#ov-player')).toHaveClass(/\bon\b/);
  await expect(page.locator('#ov-buddy')).not.toHaveClass(/\bon\b/);

  await page.locator('#ov-player [onclick="stopPlayer()"]').click();
  await expect(page.locator('#ov-player')).not.toHaveClass(/\bon\b/);
  await expect(page.locator('#speak-nudge')).toHaveClass(/\bon\b/);
  const speak = page.locator('#speak-nudge .sn-go');
  await speak.focus();
  await expect(speak).toBeFocused();
  await speak.press('Enter');
  await expect(page.locator('#ov-buddy')).toHaveClass(/\bon\b/);
  const buddy = page.locator('#ov-buddy-host');
  await expect(buddy.locator('#chat-messages')).toContainText(E2E_VIDEO_TITLE);
  await expect(buddy.locator('#chat-messages')).toContainText('Tell me in your own words');

  const input = buddy.locator('#chat-input');
  await input.fill('Daily practice helps me make progress.');
  await input.press('Enter');
  await expect(buddy.locator('#chat-messages'))
    .toContainText('Tell me how daily practice helps you make progress.');

  const finish = buddy.locator('#finish-btn');
  await finish.focus();
  await expect(finish).toBeFocused();
  await finish.press('Enter');
  await expect(buddy.locator('#victory')).toHaveClass(/\bshow\b/);
  await expect(buddy.locator('#vc-xp')).toContainText('+12');
  await expect(buddy.locator('#vc-btn')).toBeVisible();

  expect(byPath(scenario, '/captions')).toHaveLength(1);
  expect(byPath(scenario, '/word_lookup')).toHaveLength(1);
  expect(byPath(scenario, '/player_action')).toHaveLength(2);
  expect(byPath(scenario, '/vocab_data')).toHaveLength(1);
  expect(byPath(scenario, '/video_summary')).toHaveLength(1);
  expect(byPath(scenario, '/buddy_chat')).toHaveLength(1);
  expect(byPath(scenario, '/buddy_realtime_token')).toHaveLength(1);
  expect(byPath(scenario, '/buddy_session_end')).toHaveLength(1);
  expect(byPath(scenario, '/buddy_victory')).toHaveLength(1);

  const captions = byPath(scenario, '/captions')[0];
  const wordRequests = byPath(scenario, '/word_lookup');
  const savedItems = byPath(scenario, '/player_action');
  const chat = byPath(scenario, '/buddy_chat')[0];
  const realtimeToken = byPath(scenario, '/buddy_realtime_token')[0];
  expect(captions.query).toEqual({ v: E2E_VIDEO_ID, lang: 'en' });
  expect(wordRequests[0].body).toMatchObject({ word: 'practice', context: E2E_CAPTION });
  expect(savedItems.map(entry => entry.body.phrase)).toEqual(['practice', E2E_CAPTION]);
  expect(chat.body.video_practice).toMatchObject({
    brief_version: 'v1',
    video_id: E2E_VIDEO_ID,
    topic: E2E_VIDEO_TITLE,
    mode: 'discuss',
    phrases: [E2E_CAPTION],
    resource_kind: 'video',
    content_status: 'grounded'
  });

  if (surface === 'telegram') {
    expect(captions.headers['x-telegram-init-data']).toBe(TELEGRAM_INIT_DATA);
    expect(captions.headers.authorization).toBeUndefined();
    for (const request of [...wordRequests, chat, realtimeToken, ...byPath(scenario, '/buddy_session_end')]) {
      expect(request.body).toMatchObject({ uid: 9001, init_data: TELEGRAM_INIT_DATA });
      expect(request.body).not.toHaveProperty('pwa_access_token');
    }
  } else {
    expect(captions.headers.authorization).toBe('Bearer access-stored');
    expect(captions.headers['x-telegram-init-data']).toBeUndefined();
    for (const request of [...wordRequests, chat, realtimeToken, ...byPath(scenario, '/buddy_session_end')]) {
      expect(request.body).toMatchObject({ uid: 7001, pwa_access_token: 'access-stored' });
      expect(request.body.init_data || '').toBe('');
    }
  }
}

async function runLegacyBookCycle(page, context, scenario, surface) {
  scenario.allowedHttpConsoleErrors = 1;
  if (surface === 'telegram') await installTelegramMiniApp(context);
  else await installBrowserSession(context);
  await page.goto('/index_v2.html');
  await page.locator('button.own-video-entry').click();
  const player = page.frameLocator('#ov-player-host iframe[title="SpeakChain Player"]');
  await expect(player.locator('body')).toBeVisible();

  const legacyBook = {
    type: 'speakchain-book-retell', title: 'A short book excerpt', videoId: E2E_VIDEO_ID
  };
  await player.locator('body').evaluate((_, payload) => {
    window.parent.postMessage(payload, window.location.origin);
    window.parent.postMessage(payload, window.location.origin);
  }, legacyBook);

  await expect(page.locator('#ov-player')).not.toHaveClass(/\bon\b/);
  await expect(page.locator('#ov-buddy')).toHaveClass(/\bon\b/);
  const buddy = page.locator('#ov-buddy-host');
  await expect(buddy.locator('#chat-messages')).toContainText('A short book excerpt');
  await expect(buddy.locator('#chat-messages')).toContainText('book excerpt was about');
  await expect(buddy.locator('#voice-toggle')).toHaveClass(/\bactive\b/);

  // The greeting deliberately starts in voice mode. Wait on the observable
  // token request rather than racing its 600 ms delayed TTS kickoff. The 503
  // fixture then exercises the same text fallback as the Video conversation.
  await expect.poll(() => byPath(scenario, '/buddy_realtime_token').length).toBe(1);
  expect(byPath(scenario, '/buddy_realtime_token')).toHaveLength(1);
  expect(byPath(scenario, '/buddy_chat')).toHaveLength(0);
  const summaries = byPath(scenario, '/video_summary');
  expect(summaries).toHaveLength(1);
  expect(summaries[0].query).toEqual({ vid: E2E_VIDEO_ID });
}

test('browser own YouTube caption continues into grounded Chainy result without retries', async ({
  appPage: page, context, scenario
}) => {
  await runOwnVideoCycle(page, context, scenario, 'browser');
});

test('Telegram own YouTube caption continues into grounded Chainy result without retries', async ({
  appPage: page, context, scenario
}) => {
  await runOwnVideoCycle(page, context, scenario, 'telegram');
});

test('browser legacy Book Loop handoff accepts only the current player and ignores a rapid duplicate', async ({
  appPage: page, context, scenario
}) => {
  await runLegacyBookCycle(page, context, scenario, 'browser');
});

test('Telegram legacy Book Loop handoff accepts only the current player and ignores a rapid duplicate', async ({
  appPage: page, context, scenario
}) => {
  await runLegacyBookCycle(page, context, scenario, 'telegram');
});
