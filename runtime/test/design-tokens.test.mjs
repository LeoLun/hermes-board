import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const css = readFileSync(new URL('../card-tokens.css', import.meta.url), 'utf8');

test('light theme exposes the Claude cream, warm ink and coral tokens', () => {
  assert.match(css, /--hb-surface:\s*#faf9f5/);
  assert.match(css, /--hb-surface-2:\s*#efe9de/);
  assert.match(css, /--hb-ink:\s*#141413/);
  assert.match(css, /--hb-ink-2:\s*#3d3d3a/);
  assert.match(css, /--hb-ink-muted:\s*#6c6a64/);
  assert.match(css, /--hb-accent:\s*#cc785c/);
  assert.match(css, /--hb-accent-active:\s*#a9583e/);
});

test('dark theme stays warm and keeps coral as its interaction accent', () => {
  const dark = css.match(/html\[data-theme="dark"\]\s*\{([\s\S]*?)\n\}/)?.[1] ?? '';
  assert.match(dark, /--hb-surface:\s*#181715/);
  assert.match(dark, /--hb-surface-2:\s*#252320/);
  assert.match(dark, /--hb-ink:\s*#faf9f5/);
  assert.match(dark, /--hb-accent:\s*#cc785c/);
  assert.doesNotMatch(dark, /#2997ff|#0071e3/);
});

test('type and shape tokens encode the Claude editorial hierarchy', () => {
  assert.match(css, /--hb-font-display:[^;]*Tiempos Headline[^;]*serif/);
  assert.match(css, /--hb-font-body:[^;]*Inter[^;]*sans-serif/);
  assert.match(css, /--hb-radius-control:\s*8px/);
  assert.match(css, /--hb-radius-card:\s*12px/);
  assert.match(css, /\.hb-title\s*\{[^}]*font-family:\s*var\(--hb-font-display\)/s);
  assert.match(css, /\.hb-metric-lg[^\n]*font-family:\s*var\(--hb-font-display\)/);
  assert.match(css, /\.hb-btn\s*\{[^}]*border-radius:\s*var\(--hb-radius-control\)/s);
  assert.match(css, /\.hb-well\s*\{[^}]*border-radius:\s*var\(--hb-radius-card\)/s);
});
