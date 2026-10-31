import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  CARD_CSP,
  buildCardDocument,
  buildPrelude,
  escapeScript,
  injectPrelude,
  randomToken,
  serializeBoot,
  toBase64Utf8,
  toDataUrl,
  transformCardHtml,
} from '../src/html-transform.js';

const opts = { boot: { token: 't', cardId: 'demo' }, runtimeJs: 'void 0;', tokensCss: ':root{}' };

test('prelude order: CSP, color-scheme, tokens, runtime', () => {
  const p = buildPrelude(opts);
  const order = ['Content-Security-Policy', 'name="color-scheme"', 'id="hb-tokens"', 'id="hb-runtime"'].map((s) => p.indexOf(s));
  assert.ok(order.every((i) => i >= 0), order.join(','));
  assert.deepEqual([...order].sort((a, b) => a - b), order);
  assert.ok(p.includes(`content="${CARD_CSP}"`));
  for (const directive of ["default-src 'none'", "connect-src 'none'", "frame-src 'none'", "worker-src 'none'", "form-action 'none'", "base-uri 'none'"]) {
    assert.ok(CARD_CSP.includes(directive), directive);
  }
  assert.ok(p.includes('window.__HB_BOOT__={"token":"t","cardId":"demo"};void 0;'));
});

test('prelude goes first inside <head>, before the card own meta charset', () => {
  const html = '<!doctype html><html lang="zh-CN"><head data-x="1"><meta charset="utf-8"><title>x</title></head><body></body></html>';
  const out = transformCardHtml(html, opts);
  const headAt = out.indexOf('<head data-x="1">') + '<head data-x="1">'.length;
  assert.equal(out.indexOf('<meta http-equiv="Content-Security-Policy"'), headAt);
  assert.ok(out.indexOf('id="hb-runtime"') < out.indexOf('<meta charset="utf-8">'));
  assert.ok(out.startsWith('<!doctype html><html lang="zh-CN">'));
});

test('documents without <head> get one synthesized', () => {
  assert.equal(injectPrelude('<html lang="zh-CN"><body>x</body></html>', 'P'), '<html lang="zh-CN"><head>P</head><body>x</body></html>');
  assert.equal(injectPrelude('<!DOCTYPE html><body>x</body>', 'P'), '<!DOCTYPE html><head>P</head><body>x</body>');
  assert.equal(injectPrelude('<div>x</div>', 'P'), '<head>P</head><div>x</div>');
  assert.equal(injectPrelude('<HEAD><title>a</title></HEAD>', 'P'), '<HEAD>P<title>a</title></HEAD>');
  assert.equal(injectPrelude('<header>x</header>', 'P'), '<head>P</head><header>x</header>', '<header> is not <head>');
});

test('script and boot payloads cannot break out of the runtime <script>', () => {
  assert.equal(escapeScript('a</script><b'), 'a\\x3C/script><b');
  assert.equal(escapeScript('x</SCRIPT>'), 'x\\x3C/SCRIPT>');
  assert.equal(escapeScript('/<!--/g; "<script id=x>"'), '/\\x3C!--/g; "\\x3Cscript id=x>"');
  // The escaped text still evaluates to the same values in strings, templates and regexes.
  const src = 'return ["</script>", `<script>`, /<!--x/.test("<!--x")];';
  assert.deepEqual(new Function(escapeScript(src))(), ['</script>', '<script>', true]);
  const boot = serializeBoot({ title: '</script><script>alert(1)</script>', amp: 'a&b', ls: '\u2028' });
  assert.doesNotMatch(boot, /<|>|&/);
  assert.deepEqual(JSON.parse(boot), { title: '</script><script>alert(1)</script>', amp: 'a&b', ls: '\u2028' });
  const p = buildPrelude({ ...opts, tokensCss: 'a</style><script>', runtimeJs: 'var s="</script>";' });
  assert.equal(p.match(/<\/style>/gi).length, 1);
  assert.equal(p.match(/<\/script>/gi).length, 1);
});

test('base64 data URL round-trips UTF-8 including CJK and emoji', () => {
  const html = '<p>北京 · 晴 ☀️ 𝄞</p>';
  const url = toDataUrl(html);
  assert.ok(url.startsWith('data:text/html;charset=utf-8;base64,'));
  const decoded = Buffer.from(url.split(',')[1], 'base64').toString('utf8');
  assert.equal(decoded, html);
  const big = 'é'.repeat(200000);
  assert.equal(Buffer.from(toBase64Utf8(big), 'base64').toString('utf8'), big, 'chunked encoding');
});

test('buildCardDocument carries mount boot data', () => {
  const url = buildCardDocument('<html><head></head><body></body></html>', {
    token: 'abc', card: { id: 'weather', title: '天气', version: '1.0.0' },
    size: { w: 8, h: 8, label: '8x8' }, pixel: { width: 400, height: 400 }, theme: 'dark',
    runtimeJs: '', tokensCss: '',
  });
  const html = Buffer.from(url.split(',')[1], 'base64').toString('utf8');
  const boot = JSON.parse(html.match(/window\.__HB_BOOT__=(\{.*?\});/)[1]);
  assert.deepEqual(boot, {
    token: 'abc', cardId: 'weather', title: '天气', version: '1.0.0', protocol: 1, theme: 'dark',
    size: { w: 8, h: 8, label: '8x8' }, pixel: { width: 400, height: 400 }, locale: 'zh-CN',
  });
});

test('randomToken is 128-bit hex and unique', () => {
  const a = randomToken();
  const b = randomToken();
  assert.match(a, /^[0-9a-f]{32}$/);
  assert.notEqual(a, b);
});
