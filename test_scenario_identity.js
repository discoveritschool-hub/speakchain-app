const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('speaking_buddy.html', 'utf8');
const manifest = JSON.parse(fs.readFileSync('scenario_identity_contract.json', 'utf8'));
const catalogMatch = source.match(/const SCENARIOS=\{[\s\S]*?\n\};/);
const identityMatch = source.match(/\/\/ Stable scenario identity contract\.[\s\S]*?window\.SC_SCENARIOS = Object\.freeze\([\s\S]*?\n\}\);/);
assert(catalogMatch && identityMatch, 'catalog identity runtime exists');

class MemoryStorage {
  constructor(seed = {}) { this.data = new Map(Object.entries(seed)); }
  getItem(key) { return this.data.has(key) ? this.data.get(key) : null; }
  setItem(key, value) { this.data.set(key, String(value)); }
  removeItem(key) { this.data.delete(key); }
}

function runtime(storage = new MemoryStorage()) {
  const context = { window: { localStorage: storage }, console };
  vm.createContext(context);
  vm.runInContext(catalogMatch[0].replace('const SCENARIOS', 'SCENARIOS'), context);
  vm.runInContext(identityMatch[0].replace('const SCENARIO_CATALOG_VERSION', 'var SCENARIO_CATALOG_VERSION'), context);
  return { api: context.window.SC_SCENARIOS, storage, catalog: context.SCENARIOS, buildIndex: context.buildScenarioIdentityIndex };
}

const { api, catalog, buildIndex } = runtime();
const rows = Object.entries(catalog).flatMap(([cat, values]) => values.map((scenario, idx) => [scenario.id, cat, idx, scenario.title]));
assert.equal(rows.length, manifest.scenario_count);
assert.deepEqual(Object.fromEntries(Object.entries(catalog).map(([cat, values]) => [cat, values.length])), manifest.category_counts);
assert.equal(crypto.createHash('sha256').update(JSON.stringify(rows)).digest('hex'), manifest.ordered_catalog_sha256);
assert.equal(new Set(rows.map(row => row[0])).size, 170, 'all canonical IDs unique');
rows.forEach(row => assert(new RegExp(manifest.canonical_id_pattern).test(row[0]), row[0]));

assert.equal(api.resolve('basics:0').id, 'sc.v1.basics.001');
assert.equal(api.resolve('basics/0').id, 'sc.v1.basics.001');
assert.equal(api.resolve('basics-0').id, 'sc.v1.basics.001');
assert.equal(api.resolve('Greeting someone new').id, 'sc.v1.basics.001');
assert.equal(api.resolve('sc.v1.move.018').scenario.title, 'Embassy visit');
for (const malformed of [null, '', 'unknown:1', 'x'.repeat(161), 'bad\u0000id', {}, {catId: 'basics', idx: 1.5}]) assert.equal(api.resolve(malformed), null);

const collisionCatalog = Object.fromEntries(Object.entries(catalog).map(([cat, values]) => [cat, values.map(item => ({...item}))]));
collisionCatalog.daily[0].title = collisionCatalog.basics[0].title;
assert.equal(buildIndex(collisionCatalog).aliases.get('greeting someone new'), null, 'title alias collisions fail closed');

const legacy = new MemoryStorage({
  'chainy.bookmarks': JSON.stringify(['basics:0', 'travel/0']),
  'scenario_progress': JSON.stringify({'basics-0': {turns: 4}, 'sc.v1.travel.001': {turns: 2}}),
  'scenario_mastery': JSON.stringify({'Greeting someone new': 0.75}),
});
const migrated = runtime(legacy).api.migrate(legacy);
assert.equal(migrated.status, 'complete');
const canonical = JSON.parse(legacy.getItem('speakchain.scenarios.v1'));
assert.deepEqual(canonical.bookmarks, {'sc.v1.basics.001': true, 'sc.v1.travel.001': true});
assert.deepEqual(canonical.progress['sc.v1.basics.001'], {turns: 4});
assert.equal(canonical.mastery['sc.v1.basics.001'], 0.75);
assert.equal(runtime(legacy).api.migrate(legacy).status, 'already_complete', 'restart/replay is idempotent');

const unknown = new MemoryStorage({'chainy.bookmarks': JSON.stringify(['missing:999'])});
assert.equal(runtime(unknown).api.migrate(unknown).status, 'blocked');
assert.equal(unknown.getItem('speakchain.scenarios.v1'), null, 'unknown alias makes no canonical write');

const conflicting = new MemoryStorage({
  'scenario_progress': JSON.stringify({'basics:0': {turns: 1}, 'sc.v1.basics.001': {turns: 2}}),
});
assert.equal(runtime(conflicting).api.migrate(conflicting).status, 'blocked');
assert.equal(conflicting.getItem('speakchain.scenarios.v1'), null, 'collision makes no canonical write');

const rollbackRuntime = runtime(legacy);
assert.equal(rollbackRuntime.api.rollback(legacy).status, 'rolled_back');
assert.equal(legacy.getItem('chainy.bookmarks'), JSON.stringify(['basics:0', 'travel/0']));
assert.equal(legacy.getItem('speakchain.scenarios.v1'), null);

const shell = fs.readFileSync('index_v2.html', 'utf8');
const declaration = 'const APPS   = ';
const start = shell.indexOf(declaration) + declaration.length;
let depth = 0, quoted = false, escaped = false, end = -1;
for (let i = start; i < shell.length; i += 1) {
  const ch = shell[i];
  if (quoted) { if (escaped) escaped = false; else if (ch === '\\') escaped = true; else if (ch === '"') quoted = false; continue; }
  if (ch === '"') quoted = true; else if (ch === '{') depth += 1; else if (ch === '}' && --depth === 0) { end = i + 1; break; }
}
const buddy = JSON.parse(shell.slice(start, end))['s-buddy'].js;
assert(buddy.includes("id:'sc.v1.basics.001'"));
assert(buddy.includes('scenario_id:   currentScenario.id || null'));
assert(buddy.includes('openScenarioDeepLink'));
assert.equal((buddy.match(/id:'sc\.v1\./g) || []).length, 170, 'PWA/TMA embedded catalog parity');

console.log('scenario identity contract: 170 IDs, migration, replay, malformed/collision and PWA/TMA parity OK');
