const fs = require('fs');
const assert = require('assert');

const blogger = fs.readFileSync('blogger.html', 'utf8');
const admin = fs.readFileSync('admin_analytics.html', 'utf8');
const learner = fs.readFileSync('index_v2.html', 'utf8');
const runner = fs.readFileSync('live_activity.html', 'utf8');

for (const text of [
  'Відкриті ефіри', 'Створити ефір', 'live-title', 'live-time', 'live-stream',
  'live-activity', 'Скопіювати запрошення', 'Надіслати моїм учням',
  'Відкрили', 'Почали', 'Завершили', 'Помилки',
]) assert(blogger.includes(text), `blogger interface missing: ${text}`);

for (const text of [
  'owner_blogger_name', 'scheduled_at', 'status', 'Поточне навантаження',
  'admin_live_open', 'admin_live_close', 'admin_live_duplicate',
  'Учасники', 'Відкрили', 'Почали', 'Завершили', 'Помилки',
]) assert(admin.includes(text), `admin interface missing: ${text}`);

for (const text of [
  'Ефір зараз', 'openCurrentLive', 'live-activity-results-section',
  '/api/v1/live-sessions/me', '/api/v1/activity-results/me',
]) assert(learner.includes(text), `learner interface missing: ${text}`);

for (const text of [
  '/events', "event('opened')", "markStarted()", "event('error')", '/attempts',
]) assert(runner.includes(text), `runner telemetry missing: ${text}`);

console.log('Live interface contract passed');
