// Grid geometry (design §5.1). Pure functions; all lengths in CSS pixels.
import constants from '../../shared/constants.json' with { type: 'json' };

const G = constants.grid;
export const COLUMNS = G.columns;
export const GAP = G.gap;
export const PADDING = G.padding;
export const MIN_CELL = G.minCell;
export const MAX_CELL = G.maxCell;
export const RADIUS = G.radius;

/** Cell edge for a container `width` (its clientWidth, i.e. without the vertical scrollbar). */
export function cellSize(width) {
  const raw = (Number(width) - 2 * PADDING - (COLUMNS - 1) * GAP) / COLUMNS;
  if (!Number.isFinite(raw)) return MIN_CELL;
  return Math.min(MAX_CELL, Math.max(MIN_CELL, raw));
}

/** Pixel length of `n` cells including the gaps between them. */
export function span(n, cell) {
  return n <= 0 ? 0 : n * cell + (n - 1) * GAP;
}

/** Inverse of span(): a pixel length expressed as a (fractional) number of cells. */
export function spanToCells(px, cell) {
  return (px + GAP) / (cell + GAP);
}

/** Pixel offset of grid line `n` from the board's top/left edge. */
export function offset(n, cell) {
  return PADDING + n * (cell + GAP);
}

/** Absolute rect of an item inside the board element. */
export function itemRect(item, cell) {
  return { left: offset(item.x, cell), top: offset(item.y, cell), width: span(item.w, cell), height: span(item.h, cell) };
}

/** Integer pixel size handed to the card (env.pixel / resize events). */
export function pixelSize(w, h, cell) {
  return { width: Math.round(span(w, cell)), height: Math.round(span(h, cell)) };
}

export function rows(items) {
  let bottom = 0;
  for (const it of items) bottom = Math.max(bottom, it.y + it.h);
  return bottom;
}

/** Board element size; `extraRows` leaves room below the last card while dragging. */
export function boardSize(items, cell, extraRows = 0) {
  const r = rows(items) + extraRows;
  return { width: 2 * PADDING + span(COLUMNS, cell), height: 2 * PADDING + Math.max(0, span(r, cell)) };
}

/** Convert a pixel position relative to the board into fractional grid coordinates. */
export function toCells(px, cell) {
  return (px - PADDING) / (cell + GAP);
}

export function clamp(v, lo, hi) {
  return Math.min(hi, Math.max(lo, v));
}
