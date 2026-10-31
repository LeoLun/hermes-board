import { test } from 'node:test';
import assert from 'node:assert/strict';
import { makeMessage } from '../../runtime/src/protocol.js';
import { createBridge, validateHttpUrl } from '../src/bridge.js';

const flush = () => new Promise((resolve) => setImmediate(resolve));

function setup(overrides = {}) {
  let clock = 1_000_000;
  const sent = [];
  const calls = [];
  const record = (fn, result) => (...args) => {
    calls.push([fn, ...args]);
    return typeof result === 'function' ? result(...args) : Promise.resolve(result);
  };
  const api = {
    getData: record('getData', { value: 1, updatedAt: 2 }),
    listData: record('listData', {}),
    querySeries: record('querySeries', []),
    getState: record('getState', { value: '北京', updatedAt: null }),
    setState: record('setState', { updatedAt: 3 }),
    deleteState: record('deleteState', { deleted: true }),
    startRun: record('startRun', { runId: 'r1', status: 'queued', deduplicated: false }),
    getRun: record('getRun', { runId: 'r1', status: 'running' }),
    listRuns: record('listRuns', { runs: [] }),
    invokeAi: record('invokeAi', { parsed: { node: 'a' } }),
    ...overrides.api,
  };
  const ui = {
    notify: record('notify'),
    remind: record('remind', { scheduled: true }),
    cancelRemind: record('cancelRemind', { cancelled: true }),
    openExternal: record('openExternal'),
    contextmenu: record('contextmenu'),
    ...overrides.ui,
  };
  let readyCount = 0;
  let subscribed = null;
  const bridge = createBridge({
    cardId: 'weather', token: 'tok', post: (m) => sent.push(m), getEnv: () => ({ cardId: 'weather', theme: 'light' }),
    api, ui, onReady: () => readyCount++, onSubscribe: (t) => { subscribed = t; }, now: () => clock,
  });
  let seq = 0;
  async function call(method, params) {
    const id = `q${++seq}`;
    bridge.handleMessage(makeMessage('request', 'tok', { id, method, params }));
    await flush();
    await flush();
    return sent.filter((m) => m.type === 'response' && m.id === id).at(-1);
  }
  return {
    bridge, sent, calls, call, api,
    advance: (ms) => { clock += ms; },
    get readyCount() { return readyCount; },
    get subscribed() { return subscribed; },
  };
}

test('ready handshake replies with init env', () => {
  const s = setup();
  assert.equal(s.bridge.handleMessage(makeMessage('ready', 'tok')), true);
  assert.deepEqual(s.sent[0], makeMessage('init', 'tok', { env: { cardId: 'weather', theme: 'light' } }));
  assert.equal(s.readyCount, 1);
});

test('messages with a wrong token, namespace or version are dropped', () => {
  const s = setup();
  assert.equal(s.bridge.handleMessage(makeMessage('ready', 'nope')), false);
  assert.equal(s.bridge.handleMessage({ ...makeMessage('ready', 'tok'), ns: 'x' }), false);
  assert.equal(s.bridge.handleMessage({ ...makeMessage('ready', 'tok'), v: 2 }), false);
  assert.equal(s.bridge.handleMessage(null), false);
  assert.equal(s.sent.length, 0);
});

test('requests are scoped to the host-held card id', async () => {
  const s = setup();
  const res = await s.call('data.get', { key: 'current', cardId: 'other' });
  assert.deepEqual(res.result, { value: 1, updatedAt: 2 });
  assert.deepEqual(s.calls.at(-1), ['getData', 'weather', 'current']);
  await s.call('scripts.run', { name: 'fetch', args: { city: '上海' } });
  assert.deepEqual(s.calls.at(-1), ['startRun', 'weather', 'fetch', { city: '上海' }]);
  await s.call('series.query', { name: 'temp', since: 5, limit: 10, order: 'desc' });
  assert.deepEqual(s.calls.at(-1), ['querySeries', 'weather', 'temp', { since: 5, until: undefined, limit: 10, order: 'desc' }]);
});

test('unknown methods and invalid params are rejected without calling the API', async () => {
  const s = setup();
  const cases = [
    ['fs.read', {}],
    ['data.get', { key: '../x' }],
    ['data.get', 'str'],
    ['series.query', { name: 'temp', limit: 9999 }],
    ['series.query', { name: 'temp', order: 'up' }],
    ['scripts.run', { name: 'Fetch' }],
    ['scripts.run', { name: 'fetch', args: [] }],
    ['runs.get', { runId: '../../etc' }],
    ['state.set', { key: 'k' }],
    ['subscribe', { topics: ['data:a', 'files:/etc'] }],
    ['ui.notify', { message: 'x', kind: 'loud' }],
    ['ui.openExternal', { url: 'javascript:alert(1)' }],
    ['ui.openExternal', { url: 'file:///etc/passwd' }],
  ];
  for (const [method, params] of cases) {
    const res = await s.call(method, params);
    assert.equal(res.ok, false, method);
    assert.equal(res.error.code, 'invalid', `${method} ${JSON.stringify(params)}`);
  }
  assert.equal(s.calls.length, 0);
});

test('oversized state values are rejected', async () => {
  const s = setup();
  const res = await s.call('state.set', { key: 'notes', value: 'x'.repeat(70000) });
  assert.equal(res.error.code, 'too_large');
  assert.equal(s.calls.length, 0);
});

test('API errors keep their code and retry hint', async () => {
  const err = Object.assign(new Error('太快了'), { code: 'rate_limited', retryAfterMs: 1500.4 });
  const s = setup({ api: { startRun: () => Promise.reject(err) } });
  const res = await s.call('scripts.run', { name: 'fetch' });
  assert.deepEqual(res.error, { code: 'rate_limited', message: '太快了', retryAfterMs: 1500 });
  const s2 = setup({ api: { getData: () => Promise.reject(new TypeError('boom')) } });
  assert.deepEqual((await s2.call('data.get', { key: 'a' })).error, { code: 'internal', message: 'boom' });
});

test('per-card request rate limit: 20 per second', async () => {
  const s = setup();
  const results = [];
  for (let i = 0; i < 21; i++) results.push(await s.call('data.list', {}));
  assert.equal(results.filter((r) => r.ok).length, 20);
  assert.equal(results[20].error.code, 'rate_limited');
  assert.ok(results[20].error.retryAfterMs > 0);
  s.advance(1000);
  assert.equal((await s.call('data.list', {})).ok, true);
});

test('AI calls: at most one in flight and six per minute', async () => {
  let release;
  const s = setup({ api: { invokeAi: () => new Promise((resolve) => { release = () => resolve({ parsed: {} }); }) } });
  const id = 'ai1';
  s.bridge.handleMessage(makeMessage('request', 'tok', { id, method: 'ai.invoke', params: { name: 'pick', input: {} } }));
  await flush();
  const busy = await s.call('ai.invoke', { name: 'pick', input: {} });
  assert.equal(busy.error.code, 'busy');
  release();
  await flush();
  await flush();
  assert.equal(s.sent.find((m) => m.id === id).ok, true);

  const s2 = setup();
  const res = [];
  for (let i = 0; i < 7; i++) {
    res.push(await s2.call('ai.invoke', { name: 'pick', input: { i } }));
    s2.advance(1100);
  }
  assert.equal(res.filter((r) => r.ok).length, 6);
  assert.equal(res[6].error.code, 'rate_limited');
  const big = await s2.call('ai.invoke', { name: 'pick', input: { blob: 'x'.repeat(40000) } });
  assert.equal(big.error.code, 'too_large');
});

test('notify is limited to one per 3 seconds per card', async () => {
  const s = setup();
  assert.equal((await s.call('ui.notify', { message: '完成', kind: 'success' })).ok, true);
  assert.equal((await s.call('ui.notify', { message: 'again' })).error.code, 'rate_limited');
  s.advance(3000);
  assert.equal((await s.call('ui.notify', { message: 'ok' })).ok, true);
  assert.deepEqual(s.calls.filter((c) => c[0] === 'notify').map((c) => c.slice(1)), [['weather', '完成', 'success'], ['weather', 'ok', 'info']]);
});

test('subscribe validates topics and reports them to the host', async () => {
  const s = setup();
  const res = await s.call('subscribe', { topics: ['data:current', 'series:temp', 'state:city', 'run:*', 'data:current'] });
  assert.deepEqual(res.result.topics, ['data:current', 'series:temp', 'state:city', 'run:*']);
  assert.deepEqual(s.subscribed, ['data:current', 'series:temp', 'state:city', 'run:*']);
  assert.deepEqual(s.bridge.topics, s.subscribed);
});

test('reminders must be in the next 7 days', async () => {
  const s = setup();
  const now = 1_000_000;
  assert.equal((await s.call('ui.remind', { id: 'pomodoro', at: now + 25 * 60000, title: '番茄钟', message: '休息一下' })).ok, true);
  assert.deepEqual(s.calls.at(-1), ['remind', 'weather', { id: 'pomodoro', at: now + 25 * 60000, title: '番茄钟', message: '休息一下' }]);
  assert.equal((await s.call('ui.remind', { id: 'p', at: now - 5000, title: 'x' })).error.code, 'invalid');
  assert.equal((await s.call('ui.remind', { id: 'p', at: now + 8 * 86400000, title: 'x' })).error.code, 'invalid');
  assert.equal((await s.call('ui.cancelRemind', { id: 'pomodoro' })).ok, true);
});

test('openExternal and contextmenu', async () => {
  const s = setup();
  assert.deepEqual((await s.call('ui.openExternal', { url: 'https://open-meteo.com/' })).result, { opened: true });
  assert.deepEqual(s.calls.at(-1), ['openExternal', 'https://open-meteo.com/']);
  await s.call('ui.contextmenu', { x: 10, y: 20 });
  assert.deepEqual(s.calls.at(-1), ['contextmenu', 'weather', { x: 10, y: 20 }]);
  assert.equal(validateHttpUrl('http://example.com/a?b=1'), 'http://example.com/a?b=1');
});

test('sendEvent posts tokenized events; dispose stops all traffic', async () => {
  const s = setup();
  s.bridge.sendEvent('changed', { topics: ['data:current'] });
  assert.deepEqual(s.sent.at(-1), makeMessage('changed', 'tok', { topics: ['data:current'] }));
  s.bridge.dispose();
  const before = s.sent.length;
  s.bridge.sendEvent('theme', { theme: 'dark' });
  assert.equal(s.bridge.handleMessage(makeMessage('ready', 'tok')), false);
  assert.equal(s.sent.length, before);
});
