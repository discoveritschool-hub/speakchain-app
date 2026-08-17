const fs = require('fs');

const files = process.argv.slice(2);
const scriptPattern = /<script(?:[^>]*)>([\s\S]*?)<\/script>/gi;

for (const file of files) {
  const source = fs.readFileSync(file, 'utf8');
  for (const match of source.matchAll(scriptPattern)) {
    if (match[1].trim()) new Function(match[1]);
  }
  console.log(`${file} ok`);
}
