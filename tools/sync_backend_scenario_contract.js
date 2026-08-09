const fs = require('fs');
const path = require('path');

const targetRoot = process.argv[2];
if (!targetRoot) throw new Error('backend worktree path is required');
const source = fs.readFileSync('scenario_identity_contract.json', 'utf8');
const manifest = JSON.parse(source);
if (manifest.schema !== 'speakchain.scenario-catalog.v1' || manifest.scenario_count !== 170) {
  throw new Error('refusing to sync invalid scenario catalog');
}
const directory = path.join(targetRoot, 'contracts');
fs.mkdirSync(directory, {recursive: true});
fs.writeFileSync(path.join(directory, 'scenario_catalog_v1.json'), source, 'utf8');
console.log(`${manifest.catalog_hash} -> ${directory}`);
