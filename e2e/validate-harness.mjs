import { readFileSync } from 'node:fs';

const read = file => readFileSync(file, 'utf8');
const FIXED_NOW_LITERAL = '2026-08-07T12:00:00.000Z';
const pkg = JSON.parse(read('package.json'));
const config = read('playwright.config.js');
const spec = read('e2e/critical-paths.spec.js');
const youtubeSpec = read('e2e/youtube-chainy-cycle.spec.js');
const fixture = read('e2e/fixtures/critical-app.js');
const workflow = read('.github/workflows/e2e.yml');
const lock = read('pnpm-lock.yaml');
const server = read('e2e/static-server.mjs');
const uses = [...workflow.matchAll(/^\s*uses:\s*([^\s#]+)/gm)].map(match => match[1]);

const checks = [
  [pkg.devDependencies?.['@playwright/test'] === '1.62.1', 'Playwright must be exactly pinned'],
  [pkg.packageManager === 'pnpm@11.16.0', 'pnpm must be exactly pinned'],
  [lock.includes("'@playwright/test':") && lock.includes('specifier: 1.62.1')
    && lock.includes('version: 1.62.1'), 'lockfile must resolve the exact Playwright version'],
  [config.includes("name: 'chromium-desktop'") && config.includes("name: 'chromium-mobile'"), 'desktop/mobile Chromium projects are required'],
  [config.includes("serviceWorkers: 'block'"), 'service workers must not bypass request routing'],
  [config.includes('retries: 0'), 'critical CI must not hide flakes with retries'],
  [fixture.includes("context.route('**/*'") && fixture.includes('unexpected_external_request'), 'all network must be deny-by-default'],
  [fixture.includes('pageErrors') && fixture.includes('consoleErrors'), 'runtime errors must fail the test'],
  [fixture.includes("resource === 'telegram.org/js/telegram-web-app.js'")
    && !fixture.includes("hostname === 'telegram.org'"), 'SDK stubs must allowlist exact resources'],
  [fixture.includes('DeterministicDate') && fixture.includes(FIXED_NOW_LITERAL), 'clock must be deterministic'],
  [!spec.includes('waitForTimeout') && !youtubeSpec.includes('waitForTimeout'), 'tests must not use timing sleeps'],
  [youtubeSpec.includes("'/captions'") && youtubeSpec.includes("'/buddy_chat'")
    && youtubeSpec.includes("'/buddy_victory'"), 'own-video critical cycle must cover captions, Chainy and visible result'],
  [workflow.includes('pnpm install --frozen-lockfile'), 'CI must use the frozen lockfile'],
  [uses.length === 5 && uses.every(value => /@[0-9a-f]{40}$/.test(value)), 'every action must use an immutable commit SHA'],
  [workflow.includes('branches: [main]') && workflow.includes('cancel-in-progress: true'), 'CI must avoid duplicate branch runs'],
  [workflow.includes("node-version: '24.14.0'"), 'CI Node.js must be exactly pinned'],
  [!workflow.includes('secrets.'), 'deterministic E2E must not receive repository secrets'],
  [workflow.includes('actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830')
    && workflow.includes('ms-playwright'), 'CI must cache the pinned browser'],
  [workflow.includes('playwright install --with-deps chromium'), 'CI must install Chromium and OS dependencies'],
  [server.includes("'Cache-Control': 'no-store'") && server.includes('!file.startsWith(root + sep)')
    && server.includes("response.writeHead(400"), 'static server must disable cache and reject malformed/traversal paths']
];

const failures = checks.filter(([ok]) => !ok).map(([, message]) => message);
if (failures.length) {
  for (const failure of failures) process.stderr.write(`FAIL: ${failure}\n`);
  process.exit(1);
}
process.stdout.write(`E2E harness validation passed (${checks.length}/${checks.length})\n`);
