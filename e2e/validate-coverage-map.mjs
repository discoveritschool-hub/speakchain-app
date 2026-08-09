import { readFileSync } from 'node:fs';

const read = file => readFileSync(file, 'utf8');
const map = JSON.parse(read('e2e/critical-path-coverage.json'));
const config = read('playwright.config.js');
const sources = [
  'e2e/critical-paths.spec.js',
  'e2e/critical-path-matrix.spec.js',
  'e2e/api-client-boundary.spec.js',
  'e2e/youtube-chainy-cycle.spec.js'
].map(read).join('\n');
const fixture = read('e2e/fixtures/critical-app.js');
const requiredCapabilities = [
  'auth-deny', 'safe-retry-offline', 'stale-navigation',
  'roles-support-paywall-no-charge', 'rooms-hidden',
  'profile-chainy-parity', 'book-video-parity', 'deeplink-parity',
  'zero-unexpected-errors'
];
const failures = [];

if (map.schema_version !== 1) failures.push('unsupported coverage schema');
if (!map.registry_ids?.includes('L1-13')) failures.push('coverage must reference registry L1-13');
for (const project of ['chromium-desktop', 'chromium-mobile']) {
  if (!map.required_projects?.includes(project) || !config.includes(`name: '${project}'`)) {
    failures.push(`missing required project: ${project}`);
  }
}
for (const surface of ['pwa', 'telegram']) {
  if (!map.required_surfaces?.includes(surface)) failures.push(`missing required surface: ${surface}`);
}
for (const capability of requiredCapabilities) {
  const evidence = map.capabilities?.[capability];
  if (!Array.isArray(evidence) || evidence.length === 0) {
    failures.push(`missing capability evidence: ${capability}`);
    continue;
  }
  for (const title of evidence) {
    if (title === 'fixture:deny-by-default-network-and-runtime-errors') continue;
    if (!sources.includes(title)) failures.push(`stale test evidence: ${capability} -> ${title}`);
  }
}
for (const marker of [
  "context.route('**/*'", 'unexpected_external_request', 'scenario.pageErrors',
  'scenario.consoleErrors', 'E2E must never submit payments'
]) {
  if (!fixture.includes(marker)) failures.push(`fixture invariant drift: ${marker}`);
}
if (failures.length) {
  failures.forEach(failure => process.stderr.write(`FAIL: ${failure}\n`));
  process.exit(1);
}
process.stdout.write(`Critical coverage map valid (${requiredCapabilities.length}/${requiredCapabilities.length})\n`);
