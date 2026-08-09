import { createRequire } from 'node:module';
import { dirname, join, relative, resolve } from 'node:path';

const require = createRequire(import.meta.url);
const playwrightPackage = require.resolve('playwright/package.json', {
  paths: [dirname(require.resolve('@playwright/test/package.json'))]
});
const { babelParse } = require(join(dirname(playwrightPackage), 'lib/transform/babelBundle.js'));

function walk(node, visitor) {
  if (!node || typeof node !== 'object') return;
  visitor(node);
  for (const [key, value] of Object.entries(node)) {
    if (['loc', 'start', 'end', 'leadingComments', 'trailingComments', 'innerComments'].includes(key)) continue;
    if (Array.isArray(value)) value.forEach(child => walk(child, visitor));
    else if (value && typeof value === 'object' && typeof value.type === 'string') walk(value, visitor);
  }
}

function analyzeSource(source, filename) {
  const ast = babelParse(source, filename, false);
  const functions = new Map();
  const declarations = new Map();
  const assertions = new Set();
  const invariants = new Set();

  walk(ast, node => {
    if (node.type === 'FunctionDeclaration' && node.id?.name) functions.set(node.id.name, node);
    if (node.type === 'VariableDeclarator' && node.id?.type === 'Identifier'
        && ['ArrowFunctionExpression', 'FunctionExpression'].includes(node.init?.type)) {
      functions.set(node.id.name, node.init);
    }
    if (node.type !== 'CallExpression' || node.callee?.type !== 'Identifier') return;
    if (node.callee.name === 'criticalAssertion' || node.callee.name === 'criticalInvariant') {
      const id = node.arguments?.[0];
      const callback = node.arguments?.[1];
      if (id?.type !== 'StringLiteral'
          || !['ArrowFunctionExpression', 'FunctionExpression'].includes(callback?.type)) return;
      let hasExpect = false;
      walk(callback.body, child => {
        if (child.type === 'CallExpression' && child.callee?.type === 'Identifier'
            && child.callee.name === 'expect') hasExpect = true;
      });
      if (!hasExpect) return;
      (node.callee.name === 'criticalAssertion' ? assertions : invariants).add(id.value);
    }
  });

  const hasExecutableAssertion = (node, seen = new Set()) => {
    let found = false;
    walk(node, child => {
      if (found || child.type !== 'CallExpression') return;
      if (child.callee?.type === 'MemberExpression'
          && child.callee.object?.type === 'Identifier' && child.callee.object.name === 'expect') {
        found = true;
        return;
      }
      if (child.callee?.type !== 'Identifier') return;
      const name = child.callee.name;
      if (name === 'expect' || name === 'criticalAssertion' || name === 'criticalInvariant') {
        found = true;
        return;
      }
      const target = functions.get(name);
      if (target && !seen.has(name)) {
        const next = new Set(seen).add(name);
        if (hasExecutableAssertion(target.body || target, next)) found = true;
      }
    });
    return found;
  };

  walk(ast, node => {
    if (node.type !== 'CallExpression' || node.callee?.type !== 'Identifier' || node.callee.name !== 'test') return;
    const callback = node.arguments?.[1];
    if (!['ArrowFunctionExpression', 'FunctionExpression'].includes(callback?.type)) return;
    declarations.set(node.loc.start.line, hasExecutableAssertion(callback.body));
  });
  return { assertions, declarations, invariants };
}

export function collectPlaywrightEntries(report, root = process.cwd()) {
  const entries = [];
  const visit = node => {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node.specs)) {
      for (const spec of node.specs) {
        for (const test of spec.tests || []) {
          entries.push({
            title: spec.title,
            project: test.projectName,
            file: relative(root, resolve(report.config.rootDir, spec.file || '')).replaceAll('\\', '/'),
            line: Number(spec.line || 0)
          });
        }
      }
    }
    for (const suite of node.suites || []) visit(suite);
  };
  for (const suite of report.suites || []) visit(suite);
  return entries;
}

export function validateCoverage({ map, entries, sources, config }) {
  const failures = [];
  if (map.schema_version !== 2) failures.push('unsupported coverage schema');
  if (!map.registry_ids?.includes('L1-13')) failures.push('coverage must reference registry L1-13');
  if (map.verification_boundaries?.live_authorized !== 'pending_external_credentials') {
    failures.push('live/authorized verification must remain explicitly pending');
  }
  if (map.verification_boundaries?.telegram_backend_cryptographic_verification !== 'not_covered_by_app_e2e') {
    failures.push('backend Telegram cryptographic verification boundary is missing');
  }

  const analyses = new Map(Object.entries(sources).map(([file, source]) => [file, analyzeSource(source, file)]));
  const assertionIds = new Set();
  const invariantIds = new Set();
  for (const analysis of analyses.values()) {
    analysis.assertions.forEach(id => assertionIds.add(id));
    analysis.invariants.forEach(id => invariantIds.add(id));
  }
  const projects = map.matrix?.projects || [];
  for (const project of ['chromium-desktop', 'chromium-mobile']) {
    if (!projects.includes(project) || !config.includes(`name: '${project}'`)) failures.push(`missing project: ${project}`);
  }
  for (const surface of ['pwa-session-fixture', 'telegram-initdata-synthetic']) {
    if (!map.matrix?.surfaces?.includes(surface)) failures.push(`missing synthetic surface: ${surface}`);
  }

  for (const [capability, evidence] of Object.entries(map.capabilities || {})) {
    if (evidence.verification !== 'ci_simulated') failures.push(`${capability}: verification must be ci_simulated`);
    for (const title of evidence.tests || []) {
      for (const project of projects) {
        const matches = entries.filter(entry => entry.title === title && entry.project === project);
        if (matches.length !== 1) {
          failures.push(`${capability}: expected one executable ${project} test: ${title}`);
          continue;
        }
        const entry = matches[0];
        const declaration = analyses.get(entry.file)?.declarations.get(entry.line);
        if (declaration !== true) failures.push(`${capability}: test has no executable assertion: ${entry.file}:${entry.line}`);
      }
    }
    for (const id of evidence.assertions || []) {
      if (!assertionIds.has(id)) failures.push(`${capability}: missing executable assertion id: ${id}`);
    }
    for (const id of evidence.fixture_invariants || []) {
      if (!invariantIds.has(id)) failures.push(`${capability}: missing executable fixture invariant: ${id}`);
    }
    if (!(evidence.tests?.length || evidence.fixture_invariants?.length)) failures.push(`${capability}: no executable evidence`);
  }
  return failures;
}
