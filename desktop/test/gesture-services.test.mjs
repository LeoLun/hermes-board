import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError } from '../src/api.js';
import { errorSummary, fmtDuration, fmtSize, fmtTime, cardProblem, cronText } from '../src/format.js';
import { beginGesture, finishGesture, stepGesture } from '../src/gesture-math.js';
import { itemRect, span } from '../src/grid-math.js';
import { createEmitter, createServices } from '../src/services.js';

const flush = async () => {
  for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r));
};
const item = (id, x, y, w, h) => ({ id, card: id, x, y, w, h });
const CELL = 40;
const pitch = CELL + 12;

test('move gesture: below threshold is a click, then snaps and pushes, and drops back cleanly', () => {
  const items = [item('a', 0, 0, 4, 4), item('b', 4, 0, 4, 4)];
  let g = beginGesture({ items, id: 'a', mode: 'move', cell: CELL, clientX: 100, clientY: 100, pointerId: 1 });
  assert.equal(stepGesture(g, { clientX: 102, clientY: 101 }), g, 'within 3 px nothing happens');
  assert.equal(finishGesture(g), null, 'click without drag commits nothing');
  g = stepGesture(g, { clientX: 100 + 4 * pitch, clientY: 100 });
  assert.deepEqual([g.target.x, g.target.y], [4, 0]);
  assert.deepEqual(g.preview.find((i) => i.id === 'b'), item('b', 4, 4, 4, 4), 'b is pushed down');
  assert.equal(g.drag.left, itemRect(items[0], CELL).left + 4 * pitch);
  const done = finishGesture(g);
  assert.deepEqual(done.op, { type: 'rect', id: 'a', rect: { x: 4, y: 0, w: 4, h: 4 } });
  // Moving back over the origin restores b (always recomputed from the start layout).
  g = stepGesture(g, { clientX: 100, clientY: 100 });
  assert.deepEqual(g.preview, items);
  assert.equal(finishGesture(g), null);
});

test('resize gesture snaps to the nearest allowed size; bl keeps the right edge', () => {
  const items = [item('a', 8, 0, 4, 4)];
  const sizes = ['4x4', '8x4', '8x8'];
  let g = beginGesture({ items, id: 'a', mode: 'resize', handle: 'br', cell: CELL, clientX: 0, clientY: 0 });
  g = stepGesture(g, { clientX: span(7.6, CELL) - span(4, CELL), clientY: span(4.3, CELL) - span(4, CELL), sizes });
  assert.deepEqual([g.target.x, g.target.w, g.target.h, g.label], [8, 8, 4, '8×4']);
  g = beginGesture({ items, id: 'a', mode: 'resize', handle: 'bl', cell: CELL, clientX: 0, clientY: 0 });
  g = stepGesture(g, { clientX: -(span(7.6, CELL) - span(4, CELL)), clientY: span(4.3, CELL) - span(4, CELL), sizes });
  assert.deepEqual([g.target.x, g.target.w, g.target.h], [4, 8, 4], 'right edge stays at column 12');
  assert.deepEqual(finishGesture(g).op.rect, { x: 4, y: 0, w: 8, h: 4 });
});

test('format helpers', () => {
  const now = new Date(2026, 9, 31, 12, 0, 0).getTime();
  assert.equal(fmtTime(new Date(2026, 9, 31, 9, 5, 7).getTime(), now), '今天 09:05:07');
  assert.equal(fmtTime(new Date(2026, 9, 30, 23, 0, 0).getTime(), now), '昨天 23:00:00');
  assert.equal(fmtTime(new Date(2026, 8, 1, 8, 0, 0).getTime(), now), '9月1日 08:00:00');
  assert.equal(fmtTime(null), '—');
  assert.equal(fmtDuration({ startedAt: 1000, finishedAt: 1500 }), '500 毫秒');
  assert.equal(fmtDuration({ startedAt: 0, finishedAt: 12345 }), '12.3 秒');
  assert.equal(fmtDuration({ startedAt: 0, finishedAt: 125000 }), '2 分 5 秒');
  assert.equal(fmtDuration({ status: 'running', startedAt: 1 }), '进行中');
  assert.equal(errorSummary({ error: 'boom' }), 'boom');
  assert.equal(errorSummary({ stderrTail: 'a\n\nb\nc\nd\ne\n' }), 'b\nc\nd\ne');
  assert.ok(errorSummary({ stderrTail: 'x'.repeat(900) }, 100).startsWith('…'));
  assert.equal(fmtSize('8x4'), '8×4');
  assert.equal(cardProblem({ status: 'invalid', errors: [{ message: 'title 必填' }] }), '卡片清单不合法：title 必填');
  assert.equal(cardProblem(null), '卡片包不存在或已被删除');
  assert.equal(cronText({ schedule: null }), '仅手动运行');
  assert.equal(cronText({ schedule: 'every 30m', cronAvailable: true, cron: { paused: true } }), 'every 30m · 已暂停');
  assert.equal(cronText({ schedule: 'every 30m', cronAvailable: true, cron: { paused: false } }), 'every 30m · 已启用');
  assert.equal(cronText({ schedule: 'every 30m', cronAvailable: false }), 'every 30m · 定时不可用');
});

test('emitter', () => {
  const e = createEmitter();
  const got = [];
  const off = e.on((v) => got.push(v));
  e.emit(1);
  off();
  e.emit(2);
  assert.deepEqual(got, [1]);
});

function fakeBackend() {
  let layout = { schema: 'hermes-board/layout@1', revision: 1, items: [item('note', 0, 0, 8, 8), item('todo', 8, 0, 8, 8)] };
  const cards = [{ id: 'note', title: '便签', status: 'ok', sizes: ['8x8'], scripts: [] }, { id: 'todo', title: '待办', status: 'ok', sizes: ['8x8'], scripts: [] }];
  const calls = [];
  let seq = 0;
  let fail = null;
  const rest = async (path, opts = {}) => {
    calls.push([opts.method || 'GET', path, opts.body]);
    if (fail) throw fail;
    if (path === '/health') return { ok: true, apiVersion: 1 };
    if (path === '/board' && !opts.method) return { layout, cards };
    if (path.startsWith('/changes')) return { seq, changes: [] };
    if (path.startsWith('/board/items/')) {
      const id = decodeURIComponent(path.split('/')[3].split('?')[0]);
      layout = { ...layout, revision: layout.revision + 1, items: layout.items.filter((i) => i.card !== id) };
      return { layout };
    }
    if (path === '/board/items') {
      layout = { ...layout, revision: layout.revision + 1, items: [...layout.items, item(opts.body.card, 16, 0, 8, 8)] };
      return { layout };
    }
    if (path === '/board' && opts.method === 'PUT') {
      if (opts.body.baseRevision !== layout.revision) throw new Error(`409: ${JSON.stringify({ detail: { code: 'conflict', message: 'x', current: layout } })}`);
      layout = { ...layout, revision: layout.revision + 1, items: opts.body.items };
      return { layout };
    }
    if (path.endsWith('/runs') && opts.method === 'POST') return { runId: 'r1', status: 'queued' };
    return {};
  };
  return { rest, calls, get layout() { return layout; }, setFail: (e) => { fail = e; } };
}

function servicesSetup() {
  const backend = fakeBackend();
  const toasts = [];
  const timers = [];
  const events = new Map();
  const osNotes = [];
  const services = createServices({
    rest: backend.rest,
    setTimeout: (fn, ms) => {
      const t = { fn, ms, cancelled: false };
      timers.push(t);
      return () => {
        t.cancelled = true;
      };
    },
    onEvent: (type, listener) => {
      events.set(type, listener);
      return () => events.delete(type);
    },
    notify: (input) => toasts.push(input),
    os: { notify: (n) => osNotes.push(n), openExternal: async () => true },
    runtimeJs: '', tokensCss: '', log: () => {}, doc: null, win: null,
  });
  return { services, backend, toasts, timers, events, osNotes };
}

test('services: first scope loads, attach polls, backend events kick the poller', async () => {
  const { services, backend, events } = servicesSetup();
  assert.equal(events.size, 4);
  const detach = services.attachPage();
  services.setScope('c1|default');
  await flush();
  assert.equal(services.store.getState().phase, 'ready');
  const polls = () => backend.calls.filter((c) => c[1].startsWith('/changes')).length;
  const before = polls();
  events.get('plugin.hermes-board.run.finished')({});
  await flush();
  assert.equal(polls(), before + 1);
  detach();
  events.get('plugin.hermes-board.layout.updated')({});
  await flush();
  assert.equal(polls(), before + 1, 'detached page stops polling');
});

test('services: scope switch resets the board and the doc cache', async () => {
  const { services } = servicesSetup();
  services.attachPage();
  services.setScope('c1|default');
  await flush();
  services.docCache.load({ document: async () => ({ html: 'x', sha256: 's', revision: 1 }) }, 'c1|default', 'note');
  await flush();
  assert.ok(services.docCache.peek('c1|default', 'note'));
  const phases = [];
  services.store.subscribe((s) => phases.push(s.phase));
  services.setScope('c2|default');
  await flush();
  assert.equal(services.docCache.peek('c1|default', 'note'), null);
  assert.equal(phases[0], 'idle');
  assert.equal(services.store.getState().phase, 'ready');
});

test('services: remove offers undo that restores the original position', async () => {
  const { services, backend, toasts } = servicesSetup();
  services.setScope('c|p');
  await flush();
  await services.removeCard('note');
  assert.ok(!backend.layout.items.some((i) => i.card === 'note'));
  const toast = toasts.at(-1);
  assert.match(toast.message, /已从看板移除「便签」/);
  await toast.action.onClick();
  await services.store.idle();
  const note = backend.layout.items.find((i) => i.card === 'note');
  assert.deepEqual([note.x, note.y], [0, 0]);
});

test('services: arrange with undo, runNow toasts, reminders fire both notifications', async () => {
  const { services, backend, toasts, timers, osNotes } = servicesSetup();
  services.setScope('c|p');
  await flush();
  await services.removeCard('note'); // leaves a hole at x=0
  const res = await services.arrangeWithUndo();
  assert.ok(res.changed);
  assert.equal(backend.layout.items.find((i) => i.card === 'todo').x, 0);
  assert.equal(toasts.at(-1).message, '已自动整理');
  await toasts.at(-1).action.onClick();
  assert.equal(backend.layout.items.find((i) => i.card === 'todo').x, 8);
  await services.runNow('todo', 'sync');
  assert.deepEqual(backend.calls.filter((c) => c[0] === 'POST' && c[1].endsWith('/runs')).at(-1)[2], { script: 'sync', args: {}, trigger: 'manual' });
  assert.match(toasts.at(-1).message, /已开始运行 sync/);
  backend.setFail(new Error('500: {"detail":{"code":"internal","message":"炸了"}}'));
  await services.runNow('todo', 'sync');
  assert.equal(toasts.at(-1).kind, 'error');
  backend.setFail(null);
  const ui = services.cardUi('todo');
  ui.remind('todo', { id: 'x', at: Date.now() + 1000, title: '专注结束', message: '休息一下' });
  const t = timers.filter((x) => !x.cancelled).at(-1);
  t.fn();
  assert.equal(toasts.at(-1).title, '专注结束');
  assert.deepEqual(osNotes.at(-1), { title: '专注结束', body: '休息一下', activate: '/hermes-board' });
  ui.notify('todo', '同步完成', 'success');
  assert.deepEqual([toasts.at(-1).kind, toasts.at(-1).title], ['success', '待办']);
});

test('services: network failure while ready marks disconnected; recovery resets the hub', async () => {
  const { services, backend } = servicesSetup();
  services.attachPage();
  services.setScope('c|p');
  await flush();
  const resets = [];
  services.hub.subscribeCard('note', (e) => resets.push(e.reset));
  backend.setFail(new ApiError(0, 'network', 'offline'));
  services.poller.kick();
  await flush();
  assert.equal(services.store.getState().connected, false);
  backend.setFail(null);
  services.poller.kick();
  await flush();
  assert.equal(services.store.getState().connected, true);
  assert.ok(resets.includes(true));
  services.dispose();
});
