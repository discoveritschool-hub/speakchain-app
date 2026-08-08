const fs = require('fs');

const shellPath = 'index_v2.html';
let shell = fs.readFileSync(shellPath, 'utf8');

const before = `messages: sessionMsgCount, session_id: sessionId, voice: !!voiceMode,
        }),`;
const after = `messages: sessionMsgCount, session_id: sessionId, voice: !!voiceMode,
          history: history.slice(-40),
          target_phrases: (currentScenario?.videoPractice?.phrases || []).slice(0, 3),
        }),`;
const encodeJsonStringBody = value => JSON.stringify(value).slice(1, -1);
const encodedBefore = encodeJsonStringBody(before);
const encodedAfter = encodeJsonStringBody(after);
const occurrences = shell.split(encodedBefore).length - 1;
const alreadySynced = shell.split(encodedAfter).length - 1;
if (occurrences === 0 && alreadySynced === 1) {
  // Idempotent rerun: validation below still proves both finish paths.
} else if (occurrences !== 1) {
  throw new Error(`expected one embedded explicit-finish payload, found ${occurrences}`);
} else {
  shell = shell.replace(encodedBefore, encodedAfter);
  fs.writeFileSync(shellPath, shell, 'utf8');
}

const declaration = 'const APPS   = ';
const start = shell.indexOf(declaration) + declaration.length;
const apps = JSON.parse(shell.slice(start, findObjectEnd(shell, start)));
const buddy = apps['s-buddy'].js;
if ((buddy.match(/\/buddy_session_end/g) || []).length !== 2
    || (buddy.match(/history:\s+history\.slice/g) || []).length < 2
    || (buddy.match(/target_phrases:/g) || []).length < 2) {
  throw new Error('embedded Chainy finish paths are incomplete');
}

function findObjectEnd(source, objectStart) {
  let depth = 0;
  let quoted = false;
  let escaped = false;
  for (let i = objectStart; i < source.length; i += 1) {
    const char = source[i];
    if (quoted) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === '"') quoted = false;
      continue;
    }
    if (char === '"') quoted = true;
    else if (char === '{') depth += 1;
    else if (char === '}' && --depth === 0) return i + 1;
  }
  throw new Error('APPS object end not found');
}
