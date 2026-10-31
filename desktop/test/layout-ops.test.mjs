import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { cellSize, span, spanToCells, itemRect, pixelSize, boardSize, toCells, MIN_CELL, MAX_CELL, PADDING, GAP } from '../src/grid-math.js';
import {
  arrange, cycleSize, firstFit, hasOverlap, height, moveItem, nudge, pushDown, replay, sameLayout, snapResize, allowedSizes,
} from '../src/layout-ops.js';

const cases = JSON.parse(readFileSync(new URL('../../tests/fixtures/layout-cases.json', import.meta.url), 'utf8'));
const it = (id, x, y, w, h) => ({ id, card: id, x, y, w, h });
const resolve = (items) => (items === 'defaultLayout' ? cases.defaultLayout : items);

test('cell size is clamped to 24–72px and gaps are counted', () => {
  assert.equal(cellSize(100), MIN_CELL);
  assert.equal(cellSize(10000), MAX_CELL);
  const c = cellSize(1280);
  assert.ok(Math.abs(c - (1280 - 2 * PADDING - 23 * GAP) / 24) < 1e-9);
  assert.equal(span(1, 40), 40);
  assert.equal(span(4, 40), 4 * 40 + 3 * GAP);
  assert.ok(Math.abs(spanToCells(span(6, 37.5), 37.5) - 6) < 1e-9);
  assert.deepEqual(itemRect(it('a', 2, 1, 4, 4), 40), { left: PADDING + 2 * 52, top: PADDING + 52, width: 196, height: 196 });
  assert.deepEqual(pixelSize(8, 4, 40.5), { width: Math.round(8 * 40.5 + 7 * 12), height: Math.round(4 * 40.5 + 3 * 12) });
  assert.equal(toCells(PADDING + 3 * 52, 40), 3);
  assert.equal(boardSize([], 40).height, 2 * PADDING);
  assert.equal(cellSize(NaN), MIN_CELL);
});

test('widening the window keeps grid coordinates and scales pixels', () => {
  const item = it('a', 8, 0, 8, 4);
  const small = itemRect(item, cellSize(1280));
  const large = itemRect(item, cellSize(1600));
  assert.ok(large.width > small.width && large.left > small.left);
  assert.equal(large.width, span(8, cellSize(1600)));
  assert.equal(large.left, PADDING + 8 * (cellSize(1600) + GAP));
  assert.deepEqual([item.x, item.y, item.w, item.h], [8, 0, 8, 4]);
});

test('firstFit — shared cases (same as Python)', () => {
  for (const c of cases.firstFit) assert.deepEqual(firstFit(resolve(c.items), c.w, c.h), c.expect, c.name);
});

test('pushDown — shared cases (same as Python)', () => {
  for (const c of cases.pushDown) assert.deepEqual(pushDown(c.items, c.active), c.expect, c.name);
});

test('snapResize — shared cases', () => {
  for (const c of cases.snapResize) assert.deepEqual(snapResize(c.item, c.handle, c.desired, c.allowed), c.expect, c.name);
});

test('arrange — shared cases', () => {
  for (const c of cases.arrange) {
    const items = resolve(c.items);
    const out = arrange(items);
    assert.equal(out.changed, !c.unchanged, c.name);
    if (c.expect) assert.deepEqual(out.items, c.expect, c.name);
    assert.ok(!hasOverlap(out.items), c.name);
    assert.ok(out.height <= height(items), c.name);
    out.items.forEach((i, n) => assert.deepEqual([i.w, i.h], [items[n].w, items[n].h], `${c.name}: sizes unchanged`));
  }
});

test('spec: dragging B onto A pushes A down to y=4', () => {
  const out = moveItem([it('a', 0, 0, 8, 8), it('b', 8, 0, 8, 4)], 'b', 0, 0);
  assert.deepEqual(out, [it('a', 0, 4, 8, 8), it('b', 0, 0, 8, 4)]);
});

test('spec: bottom-left handle keeps the right edge (4x4 @8 → 8x4 @4)', () => {
  const r = snapResize(it('c', 8, 0, 4, 4), 'bl', { w: 7.6, h: 4.3 }, allowedSizes(['4x4', '6x4', '8x4']));
  assert.deepEqual(r, { x: 4, w: 8, h: 4 });
  assert.equal(r.x + r.w, 12);
});

test('spec: against the right edge only fitting sizes count, otherwise unchanged', () => {
  assert.deepEqual(snapResize(it('c', 20, 0, 4, 4), 'br', { w: 9, h: 4 }, allowedSizes(['4x4', '8x4'])), { x: 20, w: 4, h: 4 });
  assert.deepEqual(snapResize(it('c', 0, 0, 4, 4), 'bl', { w: 9, h: 4 }, allowedSizes(['4x4', '8x4'])), { x: 0, w: 4, h: 4 });
});

test('move clamps into the 24 columns and never goes above row 0', () => {
  const out = moveItem([it('a', 0, 0, 8, 4)], 'a', 30, -3);
  assert.deepEqual(out, [it('a', 16, 0, 8, 4)]);
});

test('keyboard: two right arrows move 2 cells (with push), Shift cycles sizes', () => {
  let items = [it('a', 0, 0, 4, 4), it('b', 6, 0, 4, 4)];
  items = nudge(nudge(items, 'a', 1, 0), 'a', 1, 0);
  assert.deepEqual(items, [it('a', 2, 0, 4, 4), it('b', 6, 0, 4, 4)]);
  items = nudge(items, 'a', 1, 0);
  assert.deepEqual(items, [it('a', 3, 0, 4, 4), it('b', 6, 4, 4, 4)]);
  const sized = cycleSize([it('n', 20, 0, 4, 4)], 'n', 1, ['4x4', '8x4']);
  assert.deepEqual(sized, [it('n', 16, 0, 8, 4)]);
  assert.deepEqual(cycleSize(sized, 'n', 1, ['4x4', '8x4']), [it('n', 16, 0, 4, 4)]);
  assert.deepEqual(cycleSize([it('n', 0, 0, 4, 4)], 'n', 1, ['4x4']), [it('n', 0, 0, 4, 4)]);
});

test('arrange then undo restores the previous layout', () => {
  const before = [it('a', 0, 0, 8, 4), it('b', 0, 10, 8, 4)];
  const out = arrange(before);
  assert.ok(out.changed);
  const restored = replay({ type: 'restore', items: before }, out.items);
  assert.ok(sameLayout(restored, before));
});

test('409 replay: Agent added a card while the user was dragging', () => {
  // User dragged b onto (0,0) based on revision N; meanwhile the Agent added c at the first free slot.
  const op = { type: 'rect', id: 'b', rect: { x: 0, y: 0, w: 8, h: 4 } };
  const latest = [it('a', 0, 0, 8, 8), it('b', 8, 0, 8, 4), it('c', 16, 0, 8, 4)];
  const out = replay(op, latest);
  assert.deepEqual(out, [it('a', 0, 4, 8, 8), it('b', 0, 0, 8, 4), it('c', 16, 0, 8, 4)]);
  assert.ok(!hasOverlap(out));
  assert.equal(replay(op, [it('a', 0, 0, 8, 8)]), null, 'card removed elsewhere → nothing to replay');
  const arranged = replay({ type: 'arrange' }, [it('a', 0, 6, 4, 4)]);
  assert.deepEqual(arranged, [it('a', 0, 0, 4, 4)]);
});

test('restore replay keeps cards added in the meantime without overlap', () => {
  const before = [it('a', 0, 0, 8, 4), it('b', 0, 10, 8, 4)];
  const latest = [it('a', 0, 0, 8, 4), it('b', 8, 0, 8, 4), it('n', 0, 10, 8, 4)];
  const out = replay({ type: 'restore', items: before }, latest);
  assert.ok(!hasOverlap(out));
  assert.deepEqual(out.map((i) => i.id), ['a', 'b', 'n']);
  assert.deepEqual(out.find((i) => i.id === 'b'), it('b', 0, 10, 8, 4));
});

test('pushDown never mutates its input', () => {
  const items = [it('a', 0, 0, 4, 4), it('b', 4, 0, 4, 4)];
  const snapshot = JSON.stringify(items);
  pushDown(items, it('a', 4, 0, 4, 4));
  arrange(items);
  assert.equal(JSON.stringify(items), snapshot);
});
