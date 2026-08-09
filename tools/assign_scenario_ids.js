const fs = require('fs');
const crypto = require('crypto');
const vm = require('vm');

const path = 'speaking_buddy.html';
let source = fs.readFileSync(path, 'utf8');
const match = source.match(/const SCENARIOS=\{([\s\S]*?)\n\};/);
if (!match) throw new Error('SCENARIOS catalog not found');
const expected = { basics: 20, daily: 52, travel: 46, work: 34, move: 18 };
let body = match[1];
const categories = [...body.matchAll(/^\s*(\w+):\[/gm)];
for (let c = categories.length - 1; c >= 0; c -= 1) {
  const category = categories[c][1];
  if (!(category in expected)) throw new Error(`unknown category ${category}`);
  const start = categories[c].index;
  const end = c + 1 < categories.length ? categories[c + 1].index : body.length;
  let block = body.slice(start, end);
  let index = 0;
  block = block.replace(/\{(?:id:'sc\.v1\.[^']+',)?emoji:/g, () => {
    index += 1;
    return `{id:'sc.v1.${category}.${String(index).padStart(3, '0')}',emoji:`;
  });
  if (index !== expected[category]) {
    throw new Error(`${category}: expected ${expected[category]}, found ${index}`);
  }
  body = body.slice(0, start) + block + body.slice(end);
}
source = source.slice(0, match.index) + `const SCENARIOS={${body}\n};` + source.slice(match.index + match[0].length);
fs.writeFileSync(path, source, 'utf8');
const updatedCatalog = source.match(/const SCENARIOS=\{[\s\S]*?\n\};/)[0];
const context = {};
vm.createContext(context);
vm.runInContext(updatedCatalog.replace('const SCENARIOS', 'SCENARIOS'), context);
const categoryMeta = {
  basics: ['continuous', 'A1'], daily: ['continuous', 'A1'],
  travel: ['continuous', 'A2'], work: ['continuous', 'A2'], move: ['real_life', 'B1'],
};
const entries = Object.entries(context.SCENARIOS).flatMap(([category, scenarios]) =>
  scenarios.map((scenario, legacyIndex) => ({
    id: scenario.id, category, legacy_index: legacyIndex, title: scenario.title,
    route: categoryMeta[category][0], cefr_level: categoryMeta[category][1], prerequisites: [],
  }))
);
const catalogHash = crypto.createHash('sha256').update(JSON.stringify(entries)).digest('hex');
const manifest = {
  schema: 'speakchain.scenario-catalog.v1', catalog_version: 1,
  catalog_hash: catalogHash, scenario_count: entries.length,
  category_counts: expected,
  legacy_recommendation_aliases: {
    basics: 'sc.v1.basics.001', daily: 'sc.v1.daily.001', travel: 'sc.v1.travel.001',
    work: 'sc.v1.work.001', interview: 'sc.v1.work.001', coffee: 'sc.v1.daily.049',
  },
  entries,
};
fs.writeFileSync('scenario_identity_contract.json', JSON.stringify(manifest, null, 2) + '\n', 'utf8');
console.log(`assigned ${entries.length} immutable IDs; catalog hash ${catalogHash}`);
