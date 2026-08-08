const fs = require('fs');

const shellPath = 'index_v2.html';
const sourcePath = 'vocab.html';
const buddyPath = 'speaking_buddy.html';
const shell = fs.readFileSync(shellPath, 'utf8');
const source = fs.readFileSync(sourcePath, 'utf8');
const buddySource = fs.readFileSync(buddyPath, 'utf8');

const declaration = 'const APPS   = ';
const jsonStart = shell.indexOf(declaration) + declaration.length;
if (jsonStart < declaration.length) throw new Error('APPS declaration not found');

let depth = 0;
let quoted = false;
let escaped = false;
let jsonEnd = -1;
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
  else if (char === '}' && --depth === 0) {
    jsonEnd = i + 1;
    break;
  }
}
if (jsonEnd < 0) throw new Error('APPS object end not found');

const apps = JSON.parse(shell.slice(jsonStart, jsonEnd));
if (!apps['ov-vocab']) throw new Error('ov-vocab module not found');

const css = [...source.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/gi)]
  .map(match => match[1]).join('\n');
const bodyMatch = source.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
if (!bodyMatch) throw new Error('vocab body not found');
const inlineScripts = [...bodyMatch[1].matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)]
  .map(match => match[1]).join('\n');
const html = bodyMatch[1].replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '').trim();

for (const marker of ['collection-tabs', 'word-detail', 'setCollectionTab', 'openWordDetail']) {
  if (!(css + html + inlineScripts).includes(marker)) throw new Error(`missing source marker: ${marker}`);
}

function extractModule(document, label) {
  const moduleCss = [...document.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/gi)]
    .map(match => match[1]).join('\n');
  const moduleBody = document.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
  if (!moduleBody) throw new Error(`${label} body not found`);
  const moduleJs = [...moduleBody[1].matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)]
    .map(match => match[1]).join('\n');
  const moduleHtml = moduleBody[1].replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '').trim();
  return { css: moduleCss, html: moduleHtml, js: moduleJs };
}

apps['ov-vocab'] = {css, html, js: inlineScripts};
const buddy = extractModule(buddySource, 'speaking buddy');
for (const marker of ['normalizeConversationBrief', 'videoPractice', 'finishSessionWithCard']) {
  if (!(buddy.css + buddy.html + buddy.js).includes(marker)) throw new Error(`missing buddy source marker: ${marker}`);
}
apps['s-buddy'] = buddy;
const replacement = JSON.stringify(apps);
const updated = shell.slice(0, jsonStart) + replacement + shell.slice(jsonEnd);
fs.writeFileSync(shellPath, updated, 'utf8');
console.log(JSON.stringify({
  vocab: {css: css.length, html: html.length, js: inlineScripts.length},
  buddy: {css: buddy.css.length, html: buddy.html.length, js: buddy.js.length}
}));
