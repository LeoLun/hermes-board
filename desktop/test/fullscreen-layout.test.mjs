import test from 'node:test';
import assert from 'node:assert/strict';
import { fullscreenEnv } from '../src/fullscreen-env.js';
import { BOARD_CSS } from '../src/styles.js';

test('fullscreen environment uses a presentation label and measured pixels', () => {
  assert.deepEqual(fullscreenEnv(1280.4, 719.6), {
    size: { w: 24, h: 16, label: 'fullscreen' },
    pixel: { width: 1280, height: 720 },
  });
  assert.deepEqual(fullscreenEnv(0, NaN).pixel, { width: 1, height: 1 });
});

test('board CSS reserves scrollbar width and disables geometry transitions while arranging', () => {
  assert.match(BOARD_CSS, /\.hb-scroll[^}]*scrollbar-gutter:\s*stable/);
  assert.match(BOARD_CSS, /\.hb-board\[data-arranging\][^}]*\.hb-card[^}]*transition:\s*none/);
});
