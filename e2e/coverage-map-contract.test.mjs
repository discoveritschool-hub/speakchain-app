import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import { collectPlaywrightEntries, validateCoverage } from './coverage-map-contract.mjs';

const require = createRequire(import.meta.url);
const read = file => readFileSync(file, 'utf8');
const listed = spawnSync(process.execPath, [require.resolve('@playwright/test/cli'), 'test', '--list', '--reporter=json'], {
  cwd: process.cwd(), encoding: 'utf8', env: process.env
});
if (listed.status !== 0) throw new Error(listed.stderr || listed.stdout || 'Playwright list failed');
const entries = collectPlaywrightEntries(JSON.parse(listed.stdout));
const map = JSON.parse(read('e2e/critical-path-coverage.json'));
const sourceFiles = new Set(entries.map(entry => entry.file));
sourceFiles.add('e2e/fixtures/critical-app.js');
const sources = Object.fromEntries([...sourceFiles].map(file => [file, read(file)]));
const base = { map, entries, sources, config: read('playwright.config.js') };
const expectFailure = (name, mutate) => {
  const input = structuredClone(base);
  mutate(input);
  if (validateCoverage(input).length === 0) throw new Error(`negative mutation passed: ${name}`);
};

const targetTitle = 'L1-13 auth deny keeps protected shell closed';
expectFailure('deleted test', input => {
  input.entries = input.entries.filter(entry => entry.title !== targetTitle);
});
expectFailure('renamed test', input => {
  input.entries = input.entries.map(entry => entry.title === targetTitle
    ? { ...entry, title: `${entry.title} renamed` } : entry);
});
expectFailure('assertion removed', input => {
  input.sources['e2e/critical-path-matrix.spec.js'] = input.sources['e2e/critical-path-matrix.spec.js']
    .replace("criticalAssertion('auth.gate_visible'", "criticalAssertion('auth.gate_removed'");
});
expectFailure('comment-only evidence', input => {
  input.sources['e2e/critical-path-matrix.spec.js'] = input.sources['e2e/critical-path-matrix.spec.js']
    .replace("criticalAssertion('auth.gate_visible'", "criticalAssertion('auth.gate_removed'")
    + "\n// criticalAssertion('auth.gate_visible', () => expect(true).toBe(true));\n";
});
for (const [name, file, before, after] of [
  ['criticalAssertion no-op', 'e2e/critical-path-matrix.spec.js', 'return assertion();', 'return undefined;'],
  ['criticalInvariant no-op', 'e2e/fixtures/critical-app.js', 'return assertion();', 'return undefined;'],
  ['criticalAssertion renamed', 'e2e/critical-path-matrix.spec.js', 'function criticalAssertion(', 'function ignoredCriticalAssertion('],
  ['criticalInvariant renamed', 'e2e/fixtures/critical-app.js', 'function criticalInvariant(', 'function ignoredCriticalInvariant('],
  ['criticalAssertion skips callback', 'e2e/critical-path-matrix.spec.js', 'return assertion();', 'if (false) return assertion(); return undefined;'],
  ['criticalInvariant skips callback', 'e2e/fixtures/critical-app.js', 'return assertion();', 'if (false) return assertion(); return undefined;']
]) {
  expectFailure(name, input => { input.sources[file] = input.sources[file].replace(before, after); });
}
process.stdout.write('Coverage validator mutation tests passed (10/10)\n');
