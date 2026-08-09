const fs = require('fs');
const childProcess = require('child_process');

const shellPath = 'index_v2.html';
const buddyPath = 'speaking_buddy.html';
const shell = fs.readFileSync(shellPath, 'utf8');
const buddySource = fs.readFileSync(buddyPath, 'utf8');
const declaration = 'const APPS   = ';
const jsonStart = shell.indexOf(declaration) + declaration.length;
if (jsonStart < declaration.length) throw new Error('APPS declaration not found');

let depth = 0, quoted = false, escaped = false, jsonEnd = -1;
for (let i = jsonStart; i < shell.length; i += 1) {
  const char = shell[i];
  if (quoted) {
    if (escaped) escaped = false;
    else if (char === '\\') escaped = true;
    else if (char === '"') quoted = false;
    continue;
  }
  if (char === '"') quoted = true;
  else if (char === '{') depth += 1;
  else if (char === '}' && --depth === 0) { jsonEnd = i + 1; break; }
}
if (jsonEnd < 0) throw new Error('APPS object end not found');

const apps = JSON.parse(shell.slice(jsonStart, jsonEnd));
if (process.argv.includes('--restore-vocab-from-main')) {
  const baseline = childProcess.execFileSync('git', ['show', 'origin/main:index_v2.html'], {encoding: 'utf8'});
  const baselineStart = baseline.indexOf(declaration) + declaration.length;
  let d = 0, q = false, e = false, baselineEnd = -1;
  for (let i = baselineStart; i < baseline.length; i += 1) {
    const char = baseline[i];
    if (q) { if (e) e = false; else if (char === '\\') e = true; else if (char === '"') q = false; continue; }
    if (char === '"') q = true; else if (char === '{') d += 1; else if (char === '}' && --d === 0) { baselineEnd = i + 1; break; }
  }
  apps['ov-vocab'] = JSON.parse(baseline.slice(baselineStart, baselineEnd))['ov-vocab'];
}
const css = [...buddySource.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/gi)].map(match => match[1]).join('\n');
const body = buddySource.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
if (!body) throw new Error('speaking buddy body not found');
const js = [...body[1].matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(match => match[1]).join('\n');
const html = body[1].replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '').trim();
for (const marker of ['SCENARIO_CATALOG_VERSION', "id:'sc.v1.basics.001'", 'openScenarioDeepLink']) {
  if (!(css + html + js).includes(marker)) throw new Error(`missing buddy source marker: ${marker}`);
}
apps['s-buddy'] = {css, html, js};
fs.writeFileSync(shellPath, shell.slice(0, jsonStart) + JSON.stringify(apps) + shell.slice(jsonEnd), 'utf8');
console.log(JSON.stringify({buddy: {css: css.length, html: html.length, js: js.length}}));
