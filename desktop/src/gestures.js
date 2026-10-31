// React hook wiring pointer capture, Esc-to-cancel and keyboard moves to gesture-math.
import { useCallback, useEffect, useRef, useState } from 'react';
import { beginGesture, finishGesture, stepGesture } from './gesture-math.js';
import { cycleSize, displaySize, nudge } from './layout-ops.js';

const ARROWS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

/**
 * @param {object} o
 * @param {Array} o.items          committed layout items
 * @param {Map<string, object>} o.cards  card summaries by id (sizes)
 * @param {number} o.cell
 * @param {(op, items) => void} o.onCommit
 */
export function useGestures({ items, cards, cell, onCommit }) {
  const [gesture, setGesture] = useState(null);
  const ref = useRef(null);
  const live = useRef({ items, cards, cell, onCommit });
  live.current = { items, cards, cell, onCommit };

  const update = useCallback((next) => {
    ref.current = next;
    setGesture(next);
  }, []);

  const cancel = useCallback(() => update(null), [update]);

  const commit = useCallback((g) => {
    update(null);
    const done = finishGesture(g);
    if (done) live.current.onCommit(done.op, done.items);
  }, [update]);

  const pointerActive = !!gesture && gesture.mode !== 'key';
  useEffect(() => {
    if (!pointerActive) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        cancel();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [pointerActive, cancel]);

  const start = useCallback((e, item, mode, handle) => {
    if (e.button !== 0 || ref.current) return;
    e.preventDefault();
    e.stopPropagation();
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      /* synthetic events in tests */
    }
    const { items: now, cell } = live.current;
    update(beginGesture({ items: now, id: item.id, mode, handle, cell, clientX: e.clientX, clientY: e.clientY, pointerId: e.pointerId }));
  }, [update]);

  const handlers = {
    onPointerMove(e) {
      const g = ref.current;
      if (!g || g.mode === 'key' || e.pointerId !== g.pointerId) return;
      const card = live.current.cards.get(g.id);
      const next = stepGesture(g, { clientX: e.clientX, clientY: e.clientY, sizes: card ? card.sizes : [] });
      if (next !== g) update(next);
    },
    onPointerUp(e) {
      const g = ref.current;
      if (!g || g.mode === 'key' || e.pointerId !== g.pointerId) return;
      commit(g);
    },
    onPointerCancel(e) {
      const g = ref.current;
      if (g && g.mode !== 'key' && e.pointerId === g.pointerId) cancel();
    },
    onLostPointerCapture(e) {
      const g = ref.current;
      if (g && g.mode !== 'key' && e.pointerId === g.pointerId) cancel();
    },
  };

  const onKeyDown = useCallback((e, item) => {
    const g = ref.current && ref.current.mode === 'key' && ref.current.id === item.id ? ref.current : null;
    if (ARROWS[e.key]) {
      if (ref.current && !g) return; // a pointer gesture owns the board
      e.preventDefault();
      const { items: now, cards } = live.current;
      const base = g ? g.base : now;
      const current = g ? g.preview : now;
      const [dx, dy] = ARROWS[e.key];
      const card = cards.get(item.id);
      const next = e.shiftKey ? cycleSize(current, item.id, dx + dy > 0 ? 1 : -1, card ? card.sizes : []) : nudge(current, item.id, dx, dy);
      const target = next.find((i) => i.id === item.id);
      update({ id: item.id, mode: 'key', base, preview: next, target, label: displaySize(target.w, target.h), resized: e.shiftKey || (g && g.resized) });
      return;
    }
    if (!g) return;
    if (e.key === 'Enter') {
      e.preventDefault();
      commit(g);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancel();
    }
  }, [cancel, commit, update]);

  const onBlur = useCallback((item) => {
    const g = ref.current;
    if (g && g.mode === 'key' && g.id === item.id) commit(g);
  }, [commit]);

  return { gesture, items: gesture ? gesture.preview : items, start, handlers, onKeyDown, onBlur, cancel };
}
