import test from 'node:test';
import assert from 'node:assert/strict';
import { makeMessage } from '../../runtime/src/protocol.js';
import { ApiError } from '../src/api.js';
import { createBoardStore, phaseFor } from '../src/board-store.js';
import { createCardHost, createDocCache } from '../src/card-host.js';

const flush = async () => {
  for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
};

function hostSetup() {
  const timers = new Map();
  let tid = 0;
  const posted = [];
  const snaps = [];
  let tokens = 0;
  const frame = { postMessage: (m) => posted.push(m) };
  const host = createCardHost({
    card: { id: 'weather', title: '天气', version: '1.0.0' },
    env: { size: { w: 8, h: 8, label: '8x8' }, pixel: { width: 400, height: 400 }, theme: 'light', visible: true },
    runtimeJs: '/*rt*/', tokensCss: '/*css*/',
    api: { getData: async () => ({ value: 1, updatedAt: 1 }) },
    ui: {},
    onChange: (s) => snaps.push(s),
    setTimer: (fn, ms) => {
      timers.set(++tid, { fn, ms });
      return tid;
    },
    clearTimer: (id) => timers.delete(id),
    makeToken: () => `tok${++tokens}`,
  });
  host.setFrameWindow(frame);
  return { host, timers, posted, snaps, frame };
}

const ready = (token) => makeMessage('ready', token, { protocol: 1 });

test('card host: builds a data: URL, ready handshake, source check', () => {
  const { host, posted, frame } = hostSetup();
  host.setHtml('<!doctype html><html><head></head><body>hi</body></html>');
  const s = host.snapshot();
  assert.equal(s.status, 'loading');
  assert.ok(s.src.startsWith('data:text/html;charset=utf-8;base64,'));
  assert.equal(s.key, 'tok1');
  assert.equal(host.handleMessage({ source: {}, data: ready('tok1') }), false, 'foreign source dropped');
  assert.equal(host.handleMessage({ source: frame, data: ready('wrong') }), false, 'wrong token dropped');
  assert.equal(host.handleMessage({ source: frame, data: ready('tok1') }), true);
  assert.equal(host.snapshot().status, 'ready');
  assert.equal(posted.at(-1).type, 'init');
  assert.equal(posted.at(-1).env.cardId, 'weather');
  host.setHtml('<!doctype html><html><head></head><body>hi</body></html>');
  assert.equal(host.snapshot().key, 'tok1', 'same HTML keeps the iframe');
});

test('card host: 10 s ready timeout starts at onLoad, retry remounts', () => {
  const { host, timers } = hostSetup();
  host.setHtml('<p>x</p>');
  assert.equal(timers.size, 0, 'no timer before the frame loads');
  host.handleLoad();
  const [t] = timers.values();
  assert.equal(t.ms, 10000);
  t.fn();
  assert.equal(host.snapshot().status, 'timeout');
  host.retry();
  assert.equal(host.snapshot().status, 'loading');
  assert.equal(host.snapshot().key, 'tok2');
});

test('card host: a second load means self-navigation → fresh token; gives up after 3', () => {
  const { host, frame } = hostSetup();
  host.setHtml('<p>x</p>');
  host.handleLoad();
  host.handleLoad();
  assert.equal(host.snapshot().key, 'tok2');
  assert.equal(host.handleMessage({ source: frame, data: ready('tok1') }), false, 'old token is dead');
  for (let i = 0; i < 3; i++) {
    host.handleLoad();
    host.handleLoad();
  }
  assert.equal(host.snapshot().status, 'error');
});

test('card host: env changes become events only after ready; changed topics are filtered', async () => {
  const { host, posted, frame } = hostSetup();
  host.setHtml('<p>x</p>');
  host.setEnv({ theme: 'dark' });
  assert.equal(posted.length, 0);
  host.handleMessage({ source: frame, data: ready('tok1') });
  assert.equal(posted.at(-1).env.theme, 'dark');
  host.setEnv({ theme: 'light' });
  assert.deepEqual([posted.at(-1).type, posted.at(-1).theme], ['theme', 'light']);
  host.setEnv({ size: { w: 4, h: 4, label: '4x4' }, pixel: { width: 200, height: 200 } });
  assert.deepEqual([posted.at(-1).type, posted.at(-1).size.w, posted.at(-1).pixel.width], ['resize', 4, 200]);
  host.setEnv({ visible: false });
  assert.deepEqual([posted.at(-1).type, posted.at(-1).visible], ['visibility', false]);
  host.handleMessage({ source: frame, data: makeMessage('request', 'tok1', { id: 's1', method: 'subscribe', params: { topics: ['data:now', 'run:*'] } }) });
  await flush();
  assert.deepEqual(host.notifyTopics(['data:now', 'series:temp', 'run:*']), ['data:now', 'run:*']);
  assert.deepEqual(posted.at(-1).topics, ['data:now', 'run:*']);
  const count = posted.length;
  assert.deepEqual(host.notifyTopics(['series:temp']), []);
  assert.equal(posted.length, count);
});

test('card host: an uncaught card error marks only this card', () => {
  const { host, frame, snaps } = hostSetup();
  host.setHtml('<p>x</p>');
  host.handleMessage({ source: frame, data: ready('tok1') });
  host.handleMessage({ source: frame, data: makeMessage('error', 'tok1', { message: 'boom' }) });
  assert.equal(host.snapshot().scriptError, 'boom');
  assert.equal(host.snapshot().status, 'ready');
  assert.equal(snaps.at(-1).scriptError, 'boom');
  host.fail('卡片包不存在');
  assert.deepEqual([host.snapshot().status, host.snapshot().src], ['error', null]);
});

test('doc cache revalidates with the known sha', async () => {
  const cache = createDocCache();
  const calls = [];
  const api = {
    document: async (id, known) => {
      calls.push(known);
      return known === 'h1' ? { unchanged: true, sha256: 'h1', revision: 1 } : { html: '<p>1</p>', sha256: 'h1', revision: 1 };
    },
  };
  const a = await cache.load(api, 'c|p', 'weather');
  const b = await cache.load(api, 'c|p', 'weather');
  assert.equal(a, b);
  assert.deepEqual(calls, [undefined, 'h1']);
  await cache.load(api, 'other|p', 'weather');
  assert.deepEqual(calls, [undefined, 'h1', undefined], 'scope is part of the key');
});

// ── board store ────────────────────────────────────────────────────────────

const item = (id, x, y, w, h) => ({ id, card: id, x, y, w, h });
const layout = (revision, items) => ({ schema: 'hermes-board/layout@1', revision, items });

function storeSetup(over = {}) {
  const notes = [];
  const calls = [];
  let server = layout(1, [item('a', 0, 0, 8, 8), item('b', 8, 0, 8, 4)]);
  const api = {
    health: async () => ({ ok: true, apiVersion: 1 }),
    board: async () => ({ layout: server, cards: [{ id: 'a', sizes: ['8x8'] }, { id: 'b', sizes: ['8x4'] }] }),
    putBoard: async (rev, items) => {
      calls.push(['put', rev, items]);
      if (rev !== server.revision) throw new ApiError(409, 'conflict', '布局已在其他地方更新', { current: server });
      server = layout(rev + 1, items);
      return { layout: server };
    },
    addItem: async ({ baseRevision, card }) => {
      calls.push(['add', baseRevision, card]);
      if (baseRevision !== server.revision) throw new ApiError(409, 'conflict', 'x', { current: server });
      server = layout(server.revision + 1, [...server.items, item(card, 16, 0, 4, 4)]);
      return { layout: server };
    },
    removeItem: async (card, rev) => {
      calls.push(['remove', rev, card]);
      server = layout(server.revision + 1, server.items.filter((i) => i.id !== card));
      return { layout: server };
    },
    ...over,
  };
  const store = createBoardStore({ api, notify: (kind, message) => notes.push([kind, message]) });
  return { store, notes, calls, api, setServer: (l) => { server = l; }, getServer: () => server };
}

test('store: phases for missing backend, auth, version mismatch', async () => {
  assert.equal(phaseFor(new ApiError(404, 'not_found', 'x')), 'not-installed');
  assert.equal(phaseFor(new ApiError(401, 'unauthorized', 'x')), 'unauthorized');
  assert.equal(phaseFor(new ApiError(0, 'network', 'x')), 'disconnected');
  const missing = storeSetup({ health: async () => { throw new ApiError(404, 'not_found', 'Not Found'); } });
  assert.equal((await missing.store.load()).phase, 'not-installed');
  const old = storeSetup({ health: async () => ({ ok: true, apiVersion: 0 }) });
  assert.equal((await old.store.load()).phase, 'update-remote');
  const ok = storeSetup();
  const s = await ok.store.load();
  assert.equal(s.phase, 'ready');
  assert.equal(s.layout.revision, 1);
});

test('store: commit writes with baseRevision; 409 replays once on the latest layout', async () => {
  const { store, calls, setServer, getServer, notes } = storeSetup();
  await store.load();
  // Meanwhile the Agent added c.
  setServer(layout(2, [item('a', 0, 0, 8, 8), item('b', 8, 0, 8, 4), item('c', 16, 0, 8, 4)]));
  const moved = [item('a', 0, 4, 8, 8), item('b', 0, 0, 8, 4)];
  const res = await store.commit({ type: 'rect', id: 'b', rect: { x: 0, y: 0, w: 8, h: 4 } }, moved);
  assert.ok(res.ok);
  assert.deepEqual(calls.map((c) => c[1]), [1, 2]);
  assert.deepEqual(getServer().items, [item('a', 0, 4, 8, 8), item('b', 0, 0, 8, 4), item('c', 16, 0, 8, 4)]);
  assert.equal(store.getState().layout.revision, 3);
  assert.deepEqual(notes, []);
});

test('store: double conflict shows the server layout and warns', async () => {
  const { store, setServer, notes } = storeSetup({});
  await store.load();
  const s = storeSetup({
    putBoard: async () => {
      throw new ApiError(409, 'conflict', 'x', { current: layout(9, [item('a', 0, 0, 8, 8)]) });
    },
  });
  await s.store.load();
  const res = await s.store.commit({ type: 'rect', id: 'a', rect: { x: 8, y: 0, w: 8, h: 8 } }, [item('a', 8, 0, 8, 8)]);
  assert.equal(res.ok, false);
  assert.equal(s.store.getState().layout.revision, 9);
  assert.equal(s.notes[0][0], 'warning');
  void store; void setServer; void notes;
});

test('store: failed write rolls back and reports; network marks disconnected but keeps the layout', async () => {
  const s = storeSetup({
    putBoard: async () => {
      throw new ApiError(0, 'network', 'offline');
    },
  });
  await s.store.load();
  const before = s.store.getState().layout;
  await s.store.commit({ type: 'rect', id: 'a', rect: { x: 8, y: 0 } }, [item('a', 8, 0, 8, 8), item('b', 0, 0, 8, 4)]);
  assert.equal(s.store.getState().layout, before);
  assert.equal(s.store.getState().connected, false);
  assert.equal(s.notes[0][0], 'error');
  assert.equal(s.store.setConnected(true), true);
});

test('store: arrange is a no-op when compact, otherwise saves and can be undone', async () => {
  const { store, notes, setServer, getServer } = storeSetup();
  await store.load();
  assert.deepEqual(await store.arrange(), { changed: false });
  assert.equal(notes[0][0], 'info');
  setServer(layout(5, [item('a', 0, 0, 8, 4), item('b', 0, 10, 8, 4)]));
  await store.refresh();
  const res = await store.arrange();
  assert.ok(res.changed);
  assert.deepEqual(getServer().items, [item('a', 0, 0, 8, 4), item('b', 8, 0, 8, 4)]);
  await res.undo();
  assert.deepEqual(getServer().items, [item('a', 0, 0, 8, 4), item('b', 0, 10, 8, 4)]);
  assert.equal(getServer().revision, 7);
});

test('store: add retries with the latest revision; remove refreshes card summaries', async () => {
  const { store, calls, setServer } = storeSetup();
  await store.load();
  setServer(layout(4, [item('a', 0, 0, 8, 8)]));
  const res = await store.addCard('note');
  assert.ok(res.ok);
  assert.deepEqual(calls.map((c) => c.slice(0, 2)), [['add', 1], ['add', 4]]);
  await store.removeCard('note');
  await store.idle();
  await flush();
  assert.ok(!store.getState().layout.items.some((i) => i.id === 'note'));
});

test('store: reset drops state and reloads', async () => {
  const { store } = storeSetup();
  await store.load();
  const seen = [];
  store.subscribe((s) => seen.push(s.phase));
  await store.reset();
  assert.deepEqual(seen.slice(0, 2), ['idle', 'loading']);
  assert.equal(store.getState().phase, 'ready');
});
