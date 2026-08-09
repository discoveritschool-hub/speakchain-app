const fs = require('fs');

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
console.log(`assigned ${Object.values(expected).reduce((a, b) => a + b, 0)} immutable IDs`);
