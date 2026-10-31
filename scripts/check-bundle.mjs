// Bundle checks for desktop/plugin.js:
//  1. only @hermes/plugin-sdk / react / react/jsx-runtime are imported (the Desktop loader refuses others);
//  2. no eval / new Function / dynamic import;
//  3. the committed bundle matches a fresh build of desktop/src;
//  4. the module links against stub modules exporting exactly the imported names and register(ctx)
//     contributes the route, the sidebar entry and the three palette commands.
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { DESKTOP_OUT, EXTERNALS, buildDesktop } from './build-desktop.mjs';

const failures = [];
const fail = (msg) => failures.push(msg);

const text = readFileSync(DESKTOP_OUT, 'utf8');

// 1. imports
const importRe = /^\s*import\s+(?:([\s\S]*?)\s+from\s+)?["']([^"']+)["'];?/gm;
const imports = new Map();
for (const m of text.matchAll(importRe)) {
  const spec = m[2];
  if (!imports.has(spec)) imports.set(spec, { named: new Set(), namespace: false, default: false });
  const entry = imports.get(spec);
  const clause = (m[1] || '').trim();
  if (!clause) continue;
  if (/^\*\s+as\s+/.test(clause)) entry.namespace = true;
  const braces = clause.match(/\{([\s\S]*)\}/);
  if (braces) {
    for (const part of braces[1].split(',')) {
      const name = part.trim().split(/\s+as\s+/)[0].trim();
      if (name) entry.named.add(name);
    }
  }
  const head = clause.replace(/\{[\s\S]*\}/, '').replace(/\*\s+as\s+\w+/, '').replace(/,/g, ' ').trim();
  if (head) entry.default = true;
}
for (const spec of imports.keys()) if (!EXTERNALS.includes(spec)) fail(`unsupported import: ${spec}`);

// 1b. every named SDK import must exist in the host SDK (a missing name fails at module link time on the
// Desktop). Checked against the local Hermes checkout when present.
const agentRoot = process.env.HERMES_AGENT_ROOT || join(homedir(), '.hermes', 'hermes-agent');
const sdkIndex = join(agentRoot, 'apps', 'desktop', 'src', 'sdk', 'index.ts');
let sdkChecked = false;
if (existsSync(sdkIndex) && imports.has('@hermes/plugin-sdk')) {
  const src = readFileSync(sdkIndex, 'utf8');
  for (const name of imports.get('@hermes/plugin-sdk').named) {
    if (!new RegExp(`(^|[^A-Za-z0-9_$])${name.replace(/\$/g, '\\$')}([^A-Za-z0-9_$]|$)`).test(src)) fail(`@hermes/plugin-sdk has no export named ${name}`);
  }
  sdkChecked = true;
}

// 2. forbidden constructs (the card runtime string is inlined, so scan outside string literals loosely)
if (/\beval\s*\(/.test(text)) fail('bundle contains eval(');
if (/\bnew\s+Function\s*\(/.test(text)) fail('bundle contains new Function(');
if (/\bimport\s*\(/.test(text)) fail('bundle contains dynamic import()');
if (!/export\s*\{[^}]*\bas\s+default\b[^}]*\}|export\s+default\b/.test(text)) fail('bundle has no default export');

// 3. freshness
const fresh = await buildDesktop({ write: false });
if (fresh.text !== text) fail('desktop/plugin.js is stale — run `pnpm build` and commit the result');

// 4. link + register against stubs
const dir = mkdtempSync(join(tmpdir(), 'hb-check-'));
const registered = [];
const stubSource = (spec, entry) => {
  const lines = [`const g = globalThis.__HB_STUBS__[${JSON.stringify(spec)}];`, 'export default g;'];
  const names = [...entry.named].filter((n) => n !== 'default');
  if (names.length) lines.push(`export const { ${names.join(', ')} } = g;`);
  return lines.join('\n');
};
const anyFn = () => null;
const namedProxy = (extra = {}) => new Proxy(extra, { get: (t, k) => (k in t ? t[k] : anyFn) });
globalThis.__HB_STUBS__ = {
  '@hermes/plugin-sdk': namedProxy({
    ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'sidebar.nav', PALETTE_AREA: 'palette',
    host: { notify: anyFn, navigate: anyFn, state: {} },
    useTheme: () => ({ resolvedMode: 'light' }),
  }),
  react: namedProxy({ memo: (c) => c }),
  'react/jsx-runtime': namedProxy({ jsx: (t, p) => ({ t, p }), jsxs: (t, p) => ({ t, p }), Fragment: 'Fragment' }),
};
let linked = text;
for (const [spec, entry] of imports) {
  const file = join(dir, `${spec.replace(/[^a-z0-9]+/gi, '_')}.mjs`);
  writeFileSync(file, stubSource(spec, entry));
  linked = linked.split(`"${spec}"`).join(JSON.stringify(pathToFileURL(file).href));
}
const bundleFile = join(dir, 'plugin.mjs');
writeFileSync(bundleFile, linked);
try {
  const mod = await import(pathToFileURL(bundleFile).href);
  const plugin = mod.default;
  if (!plugin || plugin.id !== 'hermes-board') fail(`default export id is ${plugin && plugin.id}`);
  if (!plugin || plugin.defaultEnabled !== true) fail('defaultEnabled must be true');
  const disposers = [];
  plugin.register({
    rest: async () => ({}),
    setTimeout: () => () => {},
    onEvent: (type) => {
      registered.push({ event: type });
      return () => {};
    },
    os: {},
    registerMany: (items) => registered.push(...items),
    onDispose: (fn) => disposers.push(fn),
  });
  const byArea = (area) => registered.filter((r) => r.area === area);
  const route = byArea('routes')[0];
  if (!route || route.data.path !== '/hermes-board' || typeof route.render !== 'function') fail('route /hermes-board missing');
  const nav = byArea('sidebar.nav')[0];
  if (!nav || nav.data.label !== '看板' || nav.data.codicon !== 'dashboard' || nav.data.path !== '/hermes-board') fail('sidebar entry wrong');
  const palette = byArea('palette').map((p) => p.data.label).sort();
  const want = ['打开看板', '看板：自动整理', '看板：重新加载'].sort();
  if (JSON.stringify(palette) !== JSON.stringify(want)) fail(`palette commands: ${palette.join(', ')}`);
  const events = registered.filter((r) => r.event).map((r) => r.event).sort();
  const wantEvents = ['card.removed', 'card.updated', 'layout.updated', 'run.finished'].map((e) => `plugin.hermes-board.${e}`).sort();
  if (JSON.stringify(events) !== JSON.stringify(wantEvents)) fail(`event subscriptions: ${events.join(', ')}`);
  if (disposers.length !== 1) fail('register must hand one disposer to ctx.onDispose');
  disposers.forEach((d) => d());
} catch (err) {
  fail(`bundle failed to link/register: ${err && err.stack ? err.stack : err}`);
}

const summary = {
  bytes: Buffer.byteLength(text),
  sdkExportsChecked: sdkChecked ? sdkIndex : 'skipped (no local Hermes checkout)',
  imports: Object.fromEntries([...imports].map(([k, v]) => [k, { named: [...v.named].sort(), namespace: v.namespace }])),
};
if (failures.length) {
  console.error('check-bundle FAILED');
  for (const f of failures) console.error(` - ${f}`);
  process.exit(1);
}
console.log('check-bundle ok', JSON.stringify(summary));
