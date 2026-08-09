const fs = require('fs');
const crypto = require('crypto');
const vm = require('vm');

const EXPECTED = { basics: 20, daily: 52, travel: 46, work: 34, move: 18 };
const CATEGORY_META = {
  basics: ['continuous', 'A1'], daily: ['continuous', 'A1'],
  travel: ['continuous', 'A2'], work: ['continuous', 'A2'], move: ['real_life', 'B1'],
};
const ID_RE = /^sc\.v(\d+)\.(basics|daily|travel|work|move)\.(\d{3})$/;

function catalogFromSource(source) {
  const match = source.match(/const SCENARIOS=\{[\s\S]*?\n\};/);
  if (!match) throw new Error('SCENARIOS catalog not found');
  const context = {};
  vm.createContext(context);
  vm.runInContext(match[0].replace('const SCENARIOS', 'SCENARIOS'), context);
  return context.SCENARIOS;
}

function stableKey(category, scenario) {
  if (!scenario || typeof scenario.title !== 'string' || !scenario.title.trim()) {
    throw new Error(`scenario in ${category} has no stable title identity`);
  }
  return `${category}\u0000${scenario.title.trim()}`;
}

function entriesFromCatalog(catalog, version) {
  const entries = [];
  const seenIds = new Set();
  const seenKeys = new Set();
  for (const [category, scenarios] of Object.entries(catalog)) {
    if (!(category in EXPECTED) || !Array.isArray(scenarios)) throw new Error(`unknown category ${category}`);
    for (let legacyIndex = 0; legacyIndex < scenarios.length; legacyIndex += 1) {
      const scenario = scenarios[legacyIndex];
      const key = stableKey(category, scenario);
      if (seenKeys.has(key)) throw new Error(`duplicate stable identity ${category}/${scenario.title}`);
      seenKeys.add(key);
      const match = typeof scenario.id === 'string' && scenario.id.match(ID_RE);
      if (!match || Number(match[1]) !== version || match[2] !== category) {
        throw new Error(`missing/invalid explicit v${version} ID for ${category}/${scenario.title}`);
      }
      if (seenIds.has(scenario.id)) throw new Error(`duplicate scenario ID ${scenario.id}`);
      seenIds.add(scenario.id);
      entries.push({
        id: scenario.id, category, legacy_index: legacyIndex, title: scenario.title,
        route: CATEGORY_META[category][0], cefr_level: CATEGORY_META[category][1], prerequisites: [],
      });
    }
  }
  return entries;
}

function assertImmutableV1(previous, nextEntries) {
  if (previous.catalog_version !== 1) throw new Error('expected v1 manifest');
  const beforeByKey = new Map(previous.entries.map(item => [`${item.category}\u0000${item.title.trim()}`, item]));
  const afterByKey = new Map(nextEntries.map(item => [`${item.category}\u0000${item.title.trim()}`, item]));
  if (beforeByKey.size !== afterByKey.size) throw new Error('v1 insertion/removal requires explicit version migration');
  for (const [key, before] of beforeByKey) {
    const after = afterByKey.get(key);
    if (!after) throw new Error(`v1 removal/rename requires explicit version migration: ${before.id}`);
    if (after.id !== before.id) throw new Error(`immutable ID remap rejected: ${before.id} -> ${after.id}`);
    if (after.legacy_index !== before.legacy_index) throw new Error(`v1 reorder requires explicit version migration: ${before.id}`);
  }
  for (const key of afterByKey.keys()) {
    if (!beforeByKey.has(key)) throw new Error('v1 insertion requires explicit version migration');
  }
}

function buildManifest(source, previous, { migrateVersion = null } = {}) {
  const currentVersion = Number(previous.catalog_version);
  const requested = migrateVersion == null ? currentVersion : Number(migrateVersion);
  if (!Number.isInteger(requested) || requested < currentVersion || requested > currentVersion + 1) {
    throw new Error('version migration must be exactly the next integer');
  }
  if (requested !== currentVersion) {
    throw new Error('version migration requires a dedicated explicit ID mapping artifact; automatic remap is forbidden');
  }
  const entries = entriesFromCatalog(catalogFromSource(source), currentVersion);
  assertImmutableV1(previous, entries);
  const catalogHash = crypto.createHash('sha256').update(JSON.stringify(entries)).digest('hex');
  return {...previous, catalog_hash: catalogHash, scenario_count: entries.length,
    category_counts: Object.fromEntries(Object.entries(catalogFromSource(source)).map(([k, v]) => [k, v.length])), entries};
}

function main() {
  const sourcePath = process.env.SCENARIO_SOURCE || 'speaking_buddy.html';
  const manifestPath = process.env.SCENARIO_MANIFEST || 'scenario_identity_contract.json';
  const source = fs.readFileSync(sourcePath, 'utf8');
  const previous = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const versionArg = process.argv.find(arg => arg.startsWith('--migrate-version='));
  const manifest = buildManifest(source, previous, {
    migrateVersion: versionArg ? Number(versionArg.split('=')[1]) : null,
  });
  // Write only after every immutability check passes.
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n', 'utf8');
  console.log(`verified ${manifest.entries.length} immutable v${manifest.catalog_version} IDs; catalog hash ${manifest.catalog_hash}`);
}

if (require.main === module) main();
module.exports = { buildManifest, catalogFromSource, entriesFromCatalog, assertImmutableV1 };
