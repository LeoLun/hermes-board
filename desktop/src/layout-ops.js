// Layout operations (design §4, §5.3–5.4). Pure functions over item arrays; never mutate inputs.
// Mirrors hermes_board_core/layout.py (first_fit, push_down) — both sides share tests/fixtures/layout-cases.json.
import constants from '../../shared/constants.json' with { type: 'json' };

export const COLUMNS = constants.grid.columns;
export const PRESETS = constants.presets;

export function parseSize(label) {
  const m = /^(\d+)x(\d+)$/.exec(String(label));
  if (!m) throw new Error(`尺寸不合法：${label}`);
  return { w: Number(m[1]), h: Number(m[2]) };
}

export const sizeLabel = (w, h) => `${w}x${h}`;
export const displaySize = (w, h) => `${w}×${h}`;

const copy = (i) => ({ id: i.id, card: i.card, x: i.x, y: i.y, w: i.w, h: i.h });

export function overlaps(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

export function height(items) {
  let bottom = 0;
  for (const i of items) bottom = Math.max(bottom, i.y + i.h);
  return bottom;
}

/** Smallest y, then smallest x, where a w×h rect overlaps nothing. */
export function firstFit(items, w, h, columns = COLUMNS) {
  if (w > columns) throw new Error(`宽度 ${w} 超过 ${columns} 列`);
  const bottom = height(items);
  for (let y = 0; y <= bottom; y++) {
    for (let x = 0; x <= columns - w; x++) {
      const rect = { x, y, w, h };
      if (!items.some((p) => overlaps(rect, p))) return { x, y };
    }
  }
  return { x: 0, y: bottom };
}

function readingOrder(a, b) {
  return a.y - b.y || a.x - b.x || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

/** Place `active` at its rect; colliding cards move down in (y, x) order, chaining. */
export function pushDown(items, active) {
  const placed = [copy(active)];
  const others = items.filter((i) => i.id !== active.id).map(copy).sort(readingOrder);
  for (const item of others) {
    for (;;) {
      const hits = placed.filter((p) => overlaps(item, p));
      if (!hits.length) break;
      item.y = Math.max(...hits.map((p) => p.y + p.h));
    }
    placed.push(item);
  }
  const order = new Map(items.map((i, n) => [i.id, n]));
  if (!order.has(active.id)) order.set(active.id, order.size);
  return placed.sort((a, b) => order.get(a.id) - order.get(b.id));
}

export function sameLayout(a, b) {
  if (a.length !== b.length) return false;
  const byId = new Map(b.map((i) => [i.id, i]));
  return a.every((i) => {
    const o = byId.get(i.id);
    return o && o.x === i.x && o.y === i.y && o.w === i.w && o.h === i.h;
  });
}

export function hasOverlap(items) {
  for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) if (overlaps(items[i], items[j])) return true;
  return false;
}

/** Sizes a card may take: global presets ∩ its declared sizes, in preset order. */
export function allowedSizes(cardSizes) {
  const declared = new Set(cardSizes || []);
  return PRESETS.filter((s) => declared.has(s)).map(parseSize);
}

/**
 * Resize snapping. `handle` is 'br' (top-left fixed) or 'bl' (top-right fixed); `desired` is the
 * fractional {w, h} implied by the pointer. Picks the allowed size nearest to `desired` that still
 * fits the 24 columns with the fixed corner; ties prefer the smaller area. No candidate → unchanged.
 */
export function snapResize(item, handle, desired, allowed) {
  const right = item.x + item.w;
  let best = null;
  for (const label of allowed) {
    const { w, h } = typeof label === 'string' ? parseSize(label) : label;
    if (!PRESETS.includes(sizeLabel(w, h))) continue;
    const x = handle === 'bl' ? right - w : item.x;
    if (x < 0 || x + w > COLUMNS) continue;
    const dist = Math.hypot(w - desired.w, h - desired.h);
    const area = w * h;
    if (!best || dist < best.dist - 1e-9 || (Math.abs(dist - best.dist) <= 1e-9 && area < best.area)) {
      best = { x, w, h, dist, area };
    }
  }
  return best ? { x: best.x, w: best.w, h: best.h } : { x: item.x, w: item.w, h: item.h };
}

/** Clamp a target position into the grid for an item of the given width. */
export function clampPosition(x, y, w) {
  return { x: Math.min(COLUMNS - w, Math.max(0, Math.round(x))), y: Math.max(0, Math.round(y)) };
}

export function moveItem(items, id, x, y) {
  const item = items.find((i) => i.id === id);
  if (!item) return items.map(copy);
  const pos = clampPosition(x, y, item.w);
  return pushDown(items, { ...copy(item), ...pos });
}

export function placeRect(items, id, rect) {
  const item = items.find((i) => i.id === id);
  if (!item) return items.map(copy);
  const w = rect.w ?? item.w;
  const pos = clampPosition(rect.x ?? item.x, rect.y ?? item.y, w);
  return pushDown(items, { ...copy(item), ...pos, w, h: rect.h ?? item.h });
}

export function nudge(items, id, dx, dy) {
  const item = items.find((i) => i.id === id);
  return item ? moveItem(items, id, item.x + dx, item.y + dy) : items.map(copy);
}

/** Shift+Arrow: step through the allowed sizes (preset order), keeping the top-left corner when possible. */
export function cycleSize(items, id, dir, cardSizes) {
  const item = items.find((i) => i.id === id);
  if (!item) return items.map(copy);
  const sizes = allowedSizes(cardSizes);
  if (sizes.length < 2) return items.map(copy);
  const at = sizes.findIndex((s) => s.w === item.w && s.h === item.h);
  const next = sizes[(Math.max(0, at) + (dir > 0 ? 1 : -1) + sizes.length) % sizes.length];
  const x = Math.min(item.x, COLUMNS - next.w);
  return pushDown(items, { ...copy(item), x, w: next.w, h: next.h });
}

function displacement(before, after) {
  const prev = new Map(before.map((i) => [i.id, i]));
  let total = 0;
  for (const i of after) {
    const p = prev.get(i.id);
    if (p) total += Math.abs(p.x - i.x) + Math.abs(p.y - i.y);
  }
  return total;
}

const ARRANGE_ORDERS = [
  (a, b) => readingOrder(a, b),
  (a, b) => b.w * b.h - a.w * a.h || readingOrder(a, b),
  (a, b) => b.h - a.h || b.w - a.w || readingOrder(a, b),
];

/**
 * Auto-arrange (design §5.4): positions only, sizes never change. Tries three orders with first-fit
 * placement and keeps the lexicographically smallest (total height, Σ|Δx|+|Δy|).
 */
export function arrange(items) {
  const current = items.map(copy);
  let best = null;
  for (const cmp of ARRANGE_ORDERS) {
    const placed = [];
    for (const item of [...current].sort(cmp)) {
      const pos = firstFit(placed, item.w, item.h);
      placed.push({ ...item, ...pos });
    }
    const byId = new Map(placed.map((i) => [i.id, i]));
    const result = current.map((i) => byId.get(i.id));
    const score = [height(result), displacement(current, result)];
    if (!best || score[0] < best.score[0] || (score[0] === best.score[0] && score[1] < best.score[1])) {
      best = { items: result, score };
    }
  }
  const out = best ? best.items : current;
  return { items: out, changed: !sameLayout(current, out), height: height(out) };
}

/**
 * Re-apply a user operation on a newer layout after a 409 (design §4). Returns the new items, or null when
 * the operation no longer makes sense (e.g. the card was removed elsewhere).
 *   {type:'rect', id, rect:{x,y,w,h}}  move or resize result
 *   {type:'arrange'}                    auto-arrange
 *   {type:'restore', items}             undo of an arrange
 */
export function replay(op, latest) {
  if (op.type === 'rect') {
    if (!latest.some((i) => i.id === op.id)) return null;
    return placeRect(latest, op.id, op.rect);
  }
  if (op.type === 'arrange') return arrange(latest).items;
  if (op.type === 'restore') {
    const present = new Map(latest.map((i) => [i.id, i]));
    const out = [];
    for (const saved of op.items) {
      const now = present.get(saved.id);
      if (!now) continue;
      const rect = { ...copy(now), x: saved.x, y: saved.y };
      if (rect.x + rect.w > COLUMNS || out.some((p) => overlaps(p, rect))) {
        Object.assign(rect, firstFit(out, rect.w, rect.h));
      }
      out.push(rect);
    }
    for (const now of latest) {
      if (out.some((p) => p.id === now.id)) continue;
      out.push({ ...copy(now), ...firstFit(out, now.w, now.h) });
    }
    const order = new Map(latest.map((i, n) => [i.id, n]));
    return out.sort((a, b) => order.get(a.id) - order.get(b.id));
  }
  return null;
}
