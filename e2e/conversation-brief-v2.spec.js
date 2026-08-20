const { expect, test } = require('@playwright/test');

const KEY = 'speakchain.my-situation.v2';
const legacy = { who: 'a recruiter', what: 'a product interview', focus: 'clear examples' };

test('My Situation adapts legacy, persists edits and submits v2 accessibly', async ({ page }) => {
  const logs = [];
  page.on('console', message => logs.push(message.text()));
  await page.goto('/speaking_buddy.html');
  await page.evaluate(({ key, legacy }) => localStorage.setItem(key, JSON.stringify(legacy)), { key: KEY, legacy });
  await page.reload();

  const opener = page.locator('.my-situation-fab');
  await opener.focus();
  await opener.click();
  const dialog = page.getByRole('dialog', { name: '⭐ Моя ситуація' });
  const field = page.locator('#ms-situation');
  await expect(dialog).toBeVisible();
  await expect(field).toBeFocused();
  await expect(field).toHaveValue('Conversation partner: a recruiter\nSituation: a product interview\nPractice goal: clear examples');

  const edited = 'Interview tomorrow — practise concise product examples.';
  await field.fill(edited);
  await expect(page.locator('#ms-situation-count')).toHaveText(`${edited.length}/600`);
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(opener).toBeFocused();
  await opener.click();
  await expect(field).toHaveValue(edited);
  await page.locator('.ms-cancel').focus();
  await page.keyboard.press('Tab');
  await expect(field).toBeFocused();
  await page.locator('.ms-start').click();

  const brief = await page.evaluate(() => currentScenario.mySituation);
  expect(brief).toEqual({ version: 'conversation-brief.v2', situation: edited, legacy });
  expect(brief).not.toHaveProperty('uid');
  expect(logs.join('\n')).not.toContain('a recruiter');
});

test('My Situation stays usable when draft storage is unavailable', async ({ page }) => {
  await page.addInitScript(key => {
    const getItem = Storage.prototype.getItem;
    const setItem = Storage.prototype.setItem;
    Storage.prototype.getItem = function (name) {
      if (name === key) throw new DOMException('blocked', 'SecurityError');
      return getItem.call(this, name);
    };
    Storage.prototype.setItem = function (name, value) {
      if (name === key) throw new DOMException('blocked', 'SecurityError');
      return setItem.call(this, name, value);
    };
  }, KEY);
  await page.goto('/speaking_buddy.html');
  await page.locator('.my-situation-fab').click();
  await expect(page.locator('#ms-situation')).toHaveValue('');
  await page.locator('#ms-situation').fill('Ask for a refund politely');
  await page.locator('.ms-start').click();
  await expect.poll(() => page.evaluate(() => currentScenario?.mySituation)).toEqual({
    version: 'conversation-brief.v2', situation: 'Ask for a refund politely'
  });
});
