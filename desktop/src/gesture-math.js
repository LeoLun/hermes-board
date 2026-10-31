// Pointer gesture math (design §5.3). Every step recomputes from the layout captured at gesture start, so
// cards pushed aside snap back when the pointer moves away again.
import { itemRect, spanToCells, toCells } from './grid-math.js';
import { allowedSizes, displaySize, moveItem, placeRect, sameLayout, snapResize } from './layout-ops.js';

const DRAG_THRESHOLD = 3;
const pick = (i) => ({ x: i.x, y: i.y, w: i.w, h: i.h });

export function beginGesture({ items, id, mode, handle = null, cell, clientX, clientY, pointerId = null }) {
  const item = items.find((i) => i.id === id);
  if (!item) return null;
  const rect = itemRect(item, cell);
  return {
    id, mode, handle, cell, pointerId, base: items, item, rect,
    origin: { x: clientX, y: clientY }, moved: false,
    preview: items, target: { ...item }, drag: { ...rect }, label: displaySize(item.w, item.h),
  };
}

export function stepGesture(g, { clientX, clientY, sizes }) {
  const dx = clientX - g.origin.x;
  const dy = clientY - g.origin.y;
  const moved = g.moved || Math.abs(dx) + Math.abs(dy) > DRAG_THRESHOLD;
  if (!moved) return g;
  if (g.mode === 'move') {
    const left = g.rect.left + dx;
    const top = g.rect.top + dy;
    const preview = moveItem(g.base, g.id, toCells(left, g.cell), toCells(top, g.cell));
    const target = preview.find((i) => i.id === g.id);
    return { ...g, moved, preview, target, drag: { ...g.drag, left, top } };
  }
  const width = g.handle === 'bl' ? g.rect.width - dx : g.rect.width + dx;
  const height = g.rect.height + dy;
  const desired = { w: spanToCells(width, g.cell), h: spanToCells(height, g.cell) };
  const snap = snapResize(g.item, g.handle, desired, allowedSizes(sizes));
  const preview = placeRect(g.base, g.id, { x: snap.x, y: g.item.y, w: snap.w, h: snap.h });
  const target = preview.find((i) => i.id === g.id);
  return { ...g, moved, preview, target, label: displaySize(target.w, target.h) };
}

/** {op, items} to commit, or null when nothing changed (click without drag, dropped in place). */
export function finishGesture(g) {
  if (!g || (g.mode !== 'key' && !g.moved) || sameLayout(g.base, g.preview)) return null;
  return { op: { type: 'rect', id: g.id, rect: pick(g.target) }, items: g.preview };
}
