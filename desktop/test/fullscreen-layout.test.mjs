import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { fullscreenEnv } from '../src/fullscreen-env.js';
import { BOARD_CSS } from '../src/styles.js';

test('fullscreen environment uses a presentation label and measured pixels', () => {
  assert.deepEqual(fullscreenEnv(1280.4, 719.6), {
    size: { w: 24, h: 16, label: 'fullscreen' },
    pixel: { width: 1280, height: 720 },
  });
  assert.deepEqual(fullscreenEnv(0, NaN).pixel, { width: 1, height: 1 });
});

test('fullscreen dialog gives the SDK inner body a bounded two-row layout', () => {
  const dialog = fs.readFileSync(new URL('../src/fullscreen-card.js', import.meta.url), 'utf8');
  const styles = fs.readFileSync(new URL('../src/styles.js', import.meta.url), 'utf8');
  assert.match(dialog, /bodyClassName:\s*'hb-fullscreen-body'/);
  assert.match(styles, /\.hb-fullscreen-body\s*\{[^}]*grid-template-rows:\s*auto minmax\(0,\s*1fr\)/s);
  assert.match(styles, /\.hb-fullscreen-stage\s*\{[^}]*width:\s*100%[^}]*height:\s*100%/s);
});

test('board CSS reserves scrollbar width and disables geometry transitions while arranging', () => {
  assert.match(BOARD_CSS, /\.hb-scroll[^}]*scrollbar-gutter:\s*stable/);
  assert.match(BOARD_CSS, /\.hb-board\[data-arranging\][^}]*\.hb-card[^}]*transition:\s*none/);
});
