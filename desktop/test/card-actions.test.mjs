import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { BOARD_CSS } from '../src/styles.js';

const frame = readFileSync(new URL('../src/card-frame.js', import.meta.url), 'utf8');

test('card action group keeps fullscreen before reversible remove', () => {
  assert.match(frame, /className: 'hb-card-actions'/);
  const fullscreen = frame.indexOf("name: 'screen-full'");
  const remove = frame.indexOf("name: 'trash'");
  assert.ok(fullscreen >= 0 && remove > fullscreen);
  assert.match(frame, /'aria-label': `从看板删除/);
  assert.match(frame, /props\.onRemove\(item\.card\)/);
});

test('card actions are non-interactive until hover or keyboard focus enters', () => {
  assert.match(BOARD_CSS, /\.hb-card-actions\s*\{[^}]*opacity:\s*0[^}]*visibility:\s*hidden[^}]*pointer-events:\s*none/s);
  assert.match(BOARD_CSS, /\.hb-card:hover\s*>\s*\.hb-card-actions/);
  assert.match(BOARD_CSS, /\.hb-card:focus-within\s*>\s*\.hb-card-actions/);
  assert.match(BOARD_CSS, /\.hb-card-action:focus-visible/);
});
