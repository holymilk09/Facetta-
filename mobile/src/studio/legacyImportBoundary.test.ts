import assert from 'node:assert/strict';
import {
  existsSync, readFileSync, readdirSync, realpathSync, statSync,
} from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import * as ts from 'typescript';

const MOBILE_ROOT = realpathSync(path.resolve(__dirname, '../..'));
const STUDIO_ROOT = path.join(MOBILE_ROOT, 'src', 'studio');
const APP_FILE = realpathSync(path.join(MOBILE_ROOT, 'App.tsx'));
const QUARANTINED_LEGACY_FILES = [
  path.join(MOBILE_ROOT, 'src', 'trusted', 'TrustedWorkspaceEntry.tsx'),
  path.join(MOBILE_ROOT, 'src', 'trusted', 'TrustedWorkflowScreen.tsx'),
].map((file) => realpathSync(file));

const configFile = ts.readConfigFile(
  path.join(MOBILE_ROOT, 'tsconfig.json'),
  ts.sys.readFile,
);
assert.equal(configFile.error, undefined, 'mobile/tsconfig.json must be readable');
const compilerConfig = ts.parseJsonConfigFileContent(
  configFile.config,
  ts.sys,
  MOBILE_ROOT,
);

interface ImportEdge {
  parent: string;
  specifier: string;
}

function localProductionModules(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) return localProductionModules(absolute);
    if (!entry.isFile() || !/\.[jt]sx?$/.test(entry.name) || /\.test\.[jt]sx?$/.test(entry.name)) {
      return [];
    }
    return [realpathSync(absolute)];
  });
}

function isInsideMobile(file: string): boolean {
  const relative = path.relative(MOBILE_ROOT, file);
  return relative !== '' && !relative.startsWith(`..${path.sep}`)
    && relative !== '..' && !path.isAbsolute(relative);
}

function resolveLocalModule(importer: string, specifier: string): string | null {
  const resolved = ts.resolveModuleName(
    specifier,
    importer,
    compilerConfig.options,
    ts.sys,
  ).resolvedModule;
  if (resolved === undefined || !existsSync(resolved.resolvedFileName)) return null;
  const canonical = realpathSync(resolved.resolvedFileName);
  if (!isInsideMobile(canonical) || canonical.includes(`${path.sep}node_modules${path.sep}`)) {
    return null;
  }
  return canonical;
}

function computedRuntimeLoads(file: string, source: string): string[] {
  const syntax = file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, syntax);
  const findings: string[] = [];
  const lineOf = (node: ts.Node): number => (
    tree.getLineAndCharacterOfPosition(node.getStart(tree)).line + 1
  );
  const isLiteral = (node: ts.Expression | undefined): boolean => (
    node !== undefined && (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node))
  );
  const visit = (node: ts.Node): void => {
    if (ts.isCallExpression(node)) {
      if (node.expression.kind === ts.SyntaxKind.ImportKeyword && !isLiteral(node.arguments[0])) {
        findings.push(`${path.relative(MOBILE_ROOT, file)}:${lineOf(node)} computed import()`);
      }
      if (ts.isIdentifier(node.expression) && node.expression.text === 'require'
        && (node.arguments.length !== 1 || !isLiteral(node.arguments[0]))) {
        findings.push(`${path.relative(MOBILE_ROOT, file)}:${lineOf(node)} computed require()`);
      }
      if ((ts.isPropertyAccessExpression(node.expression)
        || ts.isElementAccessExpression(node.expression))
        && ts.isIdentifier(node.expression.expression)
        && node.expression.expression.text === 'require') {
        findings.push(`${path.relative(MOBILE_ROOT, file)}:${lineOf(node)} require helper`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(tree);
  return findings;
}

function describeChain(file: string, edges: ReadonlyMap<string, ImportEdge>): string {
  const chain = [path.relative(MOBILE_ROOT, file)];
  let current = file;
  const visited = new Set([file]);
  while (edges.has(current)) {
    const edge = edges.get(current)!;
    chain.unshift(`${path.relative(MOBILE_ROOT, edge.parent)} --${edge.specifier}-->`);
    if (visited.has(edge.parent)) break;
    visited.add(edge.parent);
    current = edge.parent;
  }
  return chain.join(' ');
}

test('production Studio graph keeps legacy workflow screens quarantined', () => {
  const packageJson = JSON.parse(readFileSync(
    path.join(MOBILE_ROOT, 'package.json'), 'utf8',
  )) as { main?: unknown };
  assert.equal(typeof packageJson.main, 'string', 'mobile package main must be explicit');
  const packageMain = realpathSync(path.resolve(MOBILE_ROOT, packageJson.main as string));
  assert.ok(statSync(packageMain).isFile(), 'mobile package main must resolve to a file');

  const studioRoots = localProductionModules(STUDIO_ROOT);
  assert.ok(studioRoots.length > 0, 'Studio production roots must not be empty');
  const roots = [...new Set([packageMain, ...studioRoots])];
  const queue = [...roots];
  const reached = new Set<string>();
  const edges = new Map<string, ImportEdge>();
  const unsafeRuntimeLoads: string[] = [];

  while (queue.length > 0) {
    const file = queue.shift()!;
    if (reached.has(file)) continue;
    reached.add(file);
    const source = readFileSync(file, 'utf8');
    unsafeRuntimeLoads.push(...computedRuntimeLoads(file, source));
    for (const imported of ts.preProcessFile(source, true, true).importedFiles) {
      const dependency = resolveLocalModule(file, imported.fileName);
      if (dependency === null) continue;
      if (!edges.has(dependency) && !roots.includes(dependency)) {
        edges.set(dependency, { parent: file, specifier: imported.fileName });
      }
      queue.push(dependency);
    }
  }

  assert.ok(reached.has(APP_FILE), 'package main graph must reach App.tsx');
  assert.ok(roots.every((root) => reached.has(root)), 'every Studio production root must be visited');
  assert.deepEqual(unsafeRuntimeLoads, [], 'computed module loading can bypass legacy quarantine');
  for (const legacyFile of QUARANTINED_LEGACY_FILES) {
    assert.ok(existsSync(legacyFile), 'legacy deletion remains gated by founder acceptance');
    assert.equal(
      reached.has(legacyFile),
      false,
      `legacy workflow re-entered production graph: ${describeChain(legacyFile, edges)}`,
    );
  }
});
