import { readFileSync } from 'node:fs';

const read = file => readFileSync(file, 'utf8');
const FIXED_NOW_LITERAL = '2026-08-07T12:00:00.000Z';
const pkg = JSON.parse(read('package.json'));
const config = read('playwright.config.js');
const spec = read('e2e/critical-paths.spec.js');
const fixture = read('e2e/fixtures/critical-app.js');
const workflow = read('.github/workflows/e2e.yml');

const checks = [
  [pkg.devDependencies?.['@playwright/test'] === '1.62.1', 'Playwright must be exactly pinned'],
  [pkg.packageManager === 'pnpm@11.16.0', 'pnpm must be exactly pinned'],
  [config.includes("name: 'chromium-desktop'") && config.includes("name: 'chromium-mobile'"), 'desktop/mobile Chromium projects are required'],
  [config.includes("serviceWorkers: 'block'"), 'service workers must not bypass request routing'],
  [fixture.includes("context.route('**/*'") && fixture.includes('unexpected_external_request'), 'all network must be deny-by-default'],
  [fixture.includes('DeterministicDate') && fixture.includes(FIXED_NOW_LITERAL), 'clock must be deterministic'],
  [!spec.includes('waitForTimeout'), 'tests must not use timing sleeps'],
  [workflow.includes('pnpm install --frozen-lockfile'), 'CI must use the frozen lockfile'],
  [workflow.includes('actions/cache@v4') && workflow.includes('ms-playwright'), 'CI must cache the pinned browser'],
  [workflow.includes('playwright install --with-deps chromium'), 'CI must install Chromium and OS dependencies']
];

const failures = checks.filter(([ok]) => !ok).map(([, message]) => message);
if (failures.length) {
  for (const failure of failures) process.stderr.write(`FAIL: ${failure}\n`);
  process.exit(1);
}
process.stdout.write(`E2E harness validation passed (${checks.length}/${checks.length})\n`);
