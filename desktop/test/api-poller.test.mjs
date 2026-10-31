import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError, checkVersion, createApi, parseRestError, API_VERSION } from '../src/api.js';
import { changeTopic, createChangeHub, createPoller } from '../src/poller.js';
import { createReminders } from '../src/reminders.js';

const flush = async () => {
  for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
};

test('parseRestError understands the IPC prefix, JSON details and transport failures', () => {
  const e1 = parseRestError(new Error(`Error invoking remote method 'hermes:api': Error: 409: {"detail":{"code":"conflict","message":"布局已在其他地方更新","current":{"revision":7}}}`));
  assert.equal(e1.status, 409);
  assert.equal(e1.code, 'conflict');
  assert.equal(e1.message, '布局已在其他地方更新');
  assert.equal(e1.detail.current.revision, 7);
  const e2 = parseRestError(new Error('404: {"detail":"Not Found"}'));
  assert.deepEqual([e2.status, e2.code, e2.message], [404, 'not_found', 'Not Found']);
  const e3 = parseRestError(new Error('502: <html>bad gateway</html>'));
  assert.deepEqual([e3.status, e3.code], [502, 'internal']);
  const e4 = parseRestError(new Error('net::ERR_CONNECTION_REFUSED'));
  assert.deepEqual([e4.status, e4.code], [0, 'network']);
  assert.ok(parseRestError(e1) === e1);
});

test('checkVersion compares apiVersion both ways', () => {
  assert.equal(checkVersion({ apiVersion: API_VERSION }), 'ok');
  assert.equal(checkVersion({ apiVersion: API_VERSION + 1 }), 'update-desktop');
  assert.equal(checkVersion({ apiVersion: API_VERSION - 1 }), 'update-remote');
  assert.equal(checkVersion({}), 'update-remote');
});

test('createApi builds card-scoped paths and unwraps list responses', async () => {
  const calls = [];
  const responses = {
    '/cards/weather/data': { items: { now: { value: 1, updatedAt: 2 } } },
    '/cards/weather/series/temp?since=5&limit=10': { points: [{ ts: 1, value: 2 }] },
    '/cards/weather/runs?limit=20': { runs: [{ runId: 'r1' }] },
    '/runs/r1': { runId: 'r1', card: 'weather' },
    '/runs/r2': { runId: 'r2', card: 'todo' },
  };
  const rest = async (path, opts) => {
    calls.push([path, opts.method || 'GET', opts.body, opts.timeoutMs]);
    if (path in responses) return responses[path];
    return { ok: true };
  };
  const api = createApi(rest);
  assert.deepEqual(await api.listData('weather'), { now: { value: 1, updatedAt: 2 } });
  assert.deepEqual(await api.querySeries('weather', 'temp', { since: 5, limit: 10, until: undefined }), [{ ts: 1, value: 2 }]);
  assert.deepEqual(await api.listRuns('weather'), [{ runId: 'r1' }]);
  assert.equal((await api.getRun('weather', 'r1')).runId, 'r1');
  await assert.rejects(api.getRun('weather', 'r2'), (e) => e instanceof ApiError && e.code === 'not_found');
  await api.putBoard(3, []);
  await api.removeItem('note', 4);
  await api.setState('note', 'text', 'hi');
  await api.startRun('weather', 'fetch_weather', { city: '北京' });
  await api.invokeAi('xray', 'pick', { a: 1 });
  await api.document('weather', 'abc');
  const byPath = Object.fromEntries(calls.map((c) => [c[0], c]));
  assert.deepEqual(byPath['/board'].slice(1, 3), ['PUT', { baseRevision: 3, items: [] }]);
  assert.equal(byPath['/board/items/note?baseRevision=4'][1], 'DELETE');
  assert.deepEqual(byPath['/cards/note/state/text'].slice(1, 3), ['PUT', { value: 'hi' }]);
  assert.deepEqual(byPath['/cards/weather/runs'][2], { script: 'fetch_weather', args: { city: '北京' } });
  assert.equal(byPath['/cards/xray/ai/pick'][3], 130000);
  assert.ok(byPath['/cards/weather/document?known=abc']);
});

test('createApi converts rejections into ApiError', async () => {
  const api = createApi(async () => {
    throw new Error('401: {"detail":"Unauthorized"}');
  });
  await assert.rejects(api.health(), (e) => e.status === 401 && e.code === 'unauthorized');
});

function fakeTimers() {
  let nextId = 1;
  const pending = new Map();
  return {
    setTimer: (fn, ms) => {
      const id = nextId++;
      pending.set(id, { fn, ms });
      return id;
    },
    clearTimer: (id) => pending.delete(id),
    pending,
    async fire() {
      const [[id, t]] = [...pending.entries()];
      pending.delete(id);
      t.fn();
      await flush();
      return t.ms;
    },
  };
}

test('poller: baseline first, then changes, reset, visibility intervals', async () => {
  const timers = fakeTimers();
  const replies = [{ seq: 10, changes: [] }, { seq: 12, changes: [{ card: 'a', kind: 'data', name: 'now' }] }, { seq: 12, changes: [] }, { seq: 40, changes: [], reset: true }];
  const seen = [];
  const sinces = [];
  let resets = 0;
  const statuses = [];
  const poller = createPoller({
    fetchChanges: async (since) => {
      sinces.push(since);
      return replies.shift();
    },
    onChanges: (c) => seen.push(c),
    onReset: () => resets++,
    onStatus: (ok) => statuses.push(ok),
    ...timers,
    visibleMs: 5000,
    hiddenMs: 30000,
  });
  poller.start();
  await flush();
  assert.equal(poller.seq, 10);
  assert.deepEqual(seen, []);
  assert.equal(await timers.fire(), 5000);
  assert.deepEqual(seen, [[{ card: 'a', kind: 'data', name: 'now' }]]);
  poller.setVisible(false);
  assert.equal([...timers.pending.values()][0].ms, 30000);
  await timers.fire();
  poller.kick();
  await flush();
  assert.equal(resets, 1);
  assert.equal(poller.seq, 40);
  assert.deepEqual(sinces, [undefined, 10, 12, 12]);
  assert.deepEqual(statuses, [true, true, true, true]);
  poller.stop();
  assert.equal(timers.pending.size, 0);
});

test('poller: kick during an in-flight poll coalesces into one follow-up; errors report status', async () => {
  const timers = fakeTimers();
  let release;
  let calls = 0;
  const statuses = [];
  const poller = createPoller({
    fetchChanges: () => {
      calls += 1;
      if (calls === 2) return Promise.reject(Object.assign(new Error('down'), { code: 'network' }));
      if (calls === 1) return new Promise((r) => { release = () => r({ seq: 1, changes: [] }); });
      return Promise.resolve({ seq: 1, changes: [] });
    },
    onChanges: () => {}, onReset: () => {}, onStatus: (ok) => statuses.push(ok), ...timers,
  });
  poller.start();
  poller.kick();
  poller.kick();
  release();
  await flush();
  assert.equal(calls, 2, 'two kicks during one in-flight poll → exactly one follow-up');
  assert.deepEqual(statuses, [true, false]);
  assert.equal(timers.pending.size, 1, 'after a failure the next poll waits for the timer');
  poller.rebase();
  await flush();
  assert.equal(calls, 3);
  assert.deepEqual(statuses, [true, false, true]);
  poller.stop();
});

test('change hub groups per card and signals layout/card updates', () => {
  const hub = createChangeHub();
  const got = [];
  let layouts = 0;
  hub.subscribeCard('a', (e) => got.push(['a', e]));
  const off = hub.subscribeCard('b', (e) => got.push(['b', e]));
  hub.onLayout(() => layouts++);
  hub.dispatch([
    { card: 'a', kind: 'data', name: 'now' }, { card: 'a', kind: 'series', name: 'temp' }, { card: 'a', kind: 'run', name: 'fetch' },
    { card: 'b', kind: 'card', name: null }, { card: null, kind: 'layout', name: null },
  ]);
  assert.deepEqual(got, [
    ['a', { topics: ['data:now', 'series:temp', 'run:*'], cardChanged: false, reset: false }],
    ['b', { topics: [], cardChanged: true, reset: false }],
  ]);
  assert.equal(layouts, 1);
  off();
  got.length = 0;
  hub.reset();
  assert.deepEqual(got, [['a', { topics: [], cardChanged: true, reset: true }]]);
  assert.equal(layouts, 2);
  assert.equal(changeTopic({ kind: 'state', name: 'x' }), 'state:x');
  assert.equal(changeTopic({ kind: 'layout' }), null);
});

test('reminders fire once, replace by id and can be cancelled', () => {
  const pending = new Map();
  let n = 0;
  const fired = [];
  const r = createReminders({
    setTimeout: (fn, ms) => {
      const id = ++n;
      pending.set(id, { fn, ms });
      return () => pending.delete(id);
    },
    fire: (x) => fired.push(x),
    now: () => 1000,
  });
  assert.deepEqual(r.schedule('pomodoro', { id: 'end', at: 61000, title: '专注结束' }), { scheduled: true, at: 61000 });
  r.schedule('pomodoro', { id: 'end', at: 31000, title: '专注结束', message: '休息一下' });
  assert.equal(pending.size, 1);
  const [only] = pending.values();
  assert.equal(only.ms, 30000);
  only.fn();
  assert.deepEqual(fired, [{ cardId: 'pomodoro', id: 'end', title: '专注结束', message: '休息一下' }]);
  assert.equal(r.size, 0);
  r.schedule('pomodoro', { id: 'b', at: 500, title: 'x' });
  assert.equal([...pending.values()].at(-1).ms, 0);
  assert.deepEqual(r.cancel('pomodoro', 'b'), { cancelled: true });
  assert.deepEqual(r.cancel('pomodoro', 'b'), { cancelled: false });
  r.schedule('a', { id: 'x', at: 5000, title: 'x' });
  r.cancelAll();
  assert.equal(r.size, 0);
});
