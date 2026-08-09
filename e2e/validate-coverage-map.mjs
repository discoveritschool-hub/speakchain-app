import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname } from 'node:path';
import { spawnSync } from 'node:child_process';
import { collectPlaywrightEntries, validateCoverage } from './coverage-map-contract.mjs';

const require = createRequire(import.meta.url);
const read = file => readFileSync(file, 'utf8');
const cli = require.resolve('@playwright/test/cli');
const listed = spawnSync(process.execPath, [cli, 'test', '--list', '--reporter=json'], {
  cwd: process.cwd(), encoding: 'utf8', env: process.env
});
if (listed.status !== 0) {
  process.stderr.write(listed.stderr || listed.stdout || 'Playwright list failed\n');
  process.exit(1);
}
const report = JSON.parse(listed.stdout);
const files = new Set();
for (const entry of collectPlaywrightEntries(report)) files.add(entry.file);
files.add('e2e/fixtures/critical-app.js');
const input = {
  map: JSON.parse(read('e2e/critical-path-coverage.json')),
  entries: collectPlaywrightEntries(report),
  sources: Object.fromEntries([...files].map(file => [file, read(file)])),
  config: read('playwright.config.js')
};
const failures = validateCoverage(input);
if (failures.length) {
  failures.forEach(failure => process.stderr.write(`FAIL: ${failure}\n`));
  process.exit(1);
}
process.stdout.write(`Critical coverage map structurally valid (${Object.keys(input.map.capabilities).length} capabilities, ${input.entries.length} project tests)\n`);
