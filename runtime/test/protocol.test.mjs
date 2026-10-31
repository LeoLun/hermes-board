import { test } from 'node:test';
import assert from 'node:assert/strict';
import { BoardError, NS, VERSION, createClient, isMessage, makeMessage, topicMatches, waitForRun } from '../src/protocol.js';

function fakeTimers() {
  let now = 0;
  let seq = 0;
  const queue = new Map();
  return {
    setTimeout(fn, ms) {
      const id = ++seq;
      queue.set(id, { fn, at: now + (ms || 0) });
      return id;
    },
    clearTimeout(id) {
      queue.delete(id);
    },
    now: () => now,
    async advance(ms) {
      const target = now + ms;
      for (;;) {
        const due = [...queue.entries()].filter(([, t]) => t.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        queue.delete(due[0]);
        now = due[1].at;
        due[1].fn();
        await flush();
      }
      now = target;
    },
    get size() {
      return queue.size;
    },
  };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

function setup() {
  const sent = [];
  const timers = fakeTimers();
  const client = createClient({ post: (m) => sent.push(m), token: 'tok', timers, requestTimeoutMs: 1000 });
  const reply = (id, result, ok = true) =>
    client.handle(makeMessage('response', 'tok', ok ? { id, ok, result } : { id, ok, error: result }));
  return { sent, timers, client, reply };
}

test('isMessage checks namespace, version, type and token', () => {
  assert.equal(isMessage(makeMessage('init', 'tok'), 'tok'), true);
  assert.equal(isMessage({ ...makeMessage('init', 'tok'), ns: 'x' }, 'tok'), false);
  assert.equal(isMessage({ ...makeMessage('init', 'tok'), v: VERSION + 1 }, 'tok'), false);
  assert.equal(isMessage(makeMessage('init', 'other'), 'tok'), false);
  assert.equal(isMessage(null, 'tok'), false);
  assert.equal(isMessage('string', 'tok'), false);
  assert.equal(makeMessage('ready', 't').ns, NS);
});

test('request posts a message and resolves on response', async () => {
  const { sent, client, reply, timers } = setup();
  const p = client.request('data.get', { key: 'current' });
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0], { ns: NS, v: VERSION, type: 'request', token: 'tok', id: 'r1', method: 'data.get', params: { key: 'current' } });
  assert.equal(reply('r1', { value: 1, updatedAt: 5 }), true);
  assert.deepEqual(await p, { value: 1, updatedAt: 5 });
  assert.equal(client.pendingCount, 0);
  assert.equal(timers.size, 0, 'timeout timer cleared');
});

test('error responses reject with BoardError carrying code and extra fields', async () => {
  const { client, reply } = setup();
  const p = client.request('scripts.run', { name: 'fetch' });
  reply('r1', { code: 'rate_limited', message: '太快了', retryAfterMs: 1200 }, false);
  await assert.rejects(p, (err) => err instanceof BoardError && err.code === 'rate_limited' && err.retryAfterMs === 1200 && err.message === '太快了');
});

test('responses with unknown id or wrong token are ignored', async () => {
  const { client, reply } = setup();
  const p = client.request('data.list');
  assert.equal(reply('r99', {}), false);
  assert.equal(client.handle(makeMessage('response', 'bad', { id: 'r1', ok: true, result: 1 })), false);
  assert.equal(client.pendingCount, 1);
  reply('r1', 2);
  assert.equal(await p, 2);
});

test('requests time out and are cleaned up', async () => {
  const { client, timers } = setup();
  const p = client.request('data.list');
  const assertion = assert.rejects(p, (err) => err.code === 'timeout');
  await timers.advance(1000);
  await assertion;
  assert.equal(client.pendingCount, 0);
});

test('post failures reject immediately', async () => {
  const client = createClient({ post: () => { throw new Error('detached'); }, token: 'tok', timers: fakeTimers() });
  await assert.rejects(client.request('data.list'), (err) => err.code === 'internal' && /detached/.test(err.message));
});

test('init resolves ready and host events update env and fan out', async () => {
  const { client, sent } = setup();
  client.sendReady();
  assert.equal(sent[0].type, 'ready');
  assert.equal(client.env, null);
  const env = { cardId: 'demo', theme: 'light', size: { w: 4, h: 4, label: '4x4' } };
  assert.equal(client.handle(makeMessage('init', 'tok', { env })), true);
  assert.deepEqual(await client.ready(), env);
  const themes = [];
  const off = client.on('theme', (e) => themes.push(e.theme));
  client.handle(makeMessage('theme', 'tok', { theme: 'dark' }));
  assert.deepEqual(themes, ['dark']);
  assert.equal(client.env.theme, 'dark');
  client.handle(makeMessage('resize', 'tok', { size: { w: 6, h: 4, label: '6x4' }, pixel: { width: 300, height: 200 } }));
  assert.equal(client.env.size.label, '6x4');
  off();
  client.handle(makeMessage('theme', 'tok', { theme: 'light' }));
  assert.deepEqual(themes, ['dark']);
  assert.equal(client.handle(makeMessage('bogus', 'tok')), false);
});

test('listener errors do not break other listeners', () => {
  const timers = fakeTimers();
  const client = createClient({ post: () => {}, token: 'tok', timers });
  const seen = [];
  client.on('visibility', () => { throw new Error('boom'); });
  client.on('visibility', (e) => seen.push(e.visible));
  client.handle(makeMessage('visibility', 'tok', { visible: false }));
  assert.deepEqual(seen, [false]);
  assert.equal(timers.size, 1, 'error is rethrown asynchronously');
});

test('topicMatches supports exact topics and prefix wildcards', () => {
  assert.equal(topicMatches('data:current', 'data:current'), true);
  assert.equal(topicMatches('data:current', 'data:other'), false);
  assert.equal(topicMatches('run:*', 'run:fetch'), true);
  assert.equal(topicMatches('run:*', 'data:fetch'), false);
});

test('waitForRun polls until a terminal status and reports progress', async () => {
  const { client, sent, reply, timers } = setup();
  const progress = [];
  const done = waitForRun(client, 'run1', { intervalMs: 500, timers, now: timers.now, onProgress: (r) => progress.push(r.progress) });
  assert.equal(sent.at(-1).method, 'runs.get');
  assert.deepEqual(sent.at(-1).params, { runId: 'run1' });
  reply(sent.at(-1).id, { runId: 'run1', status: 'running', progress: 0.2 });
  await flush();
  await timers.advance(500);
  reply(sent.at(-1).id, { runId: 'run1', status: 'running', progress: 0.2 });
  await flush();
  await timers.advance(500);
  reply(sent.at(-1).id, { runId: 'run1', status: 'succeeded', progress: 1, result: { ok: true } });
  const run = await done;
  assert.equal(run.status, 'succeeded');
  assert.deepEqual(progress, [0.2], 'unchanged progress is reported once');
});

test('waitForRun polls immediately on a matching run event', async () => {
  const { client, sent, reply, timers } = setup();
  const done = waitForRun(client, 'run2', { intervalMs: 5000, timers, now: timers.now });
  reply(sent.at(-1).id, { runId: 'run2', status: 'running' });
  await flush();
  const before = sent.length;
  client.handle(makeMessage('run', 'tok', { runId: 'other', status: 'succeeded' }));
  assert.equal(sent.length, before);
  client.handle(makeMessage('run', 'tok', { runId: 'run2', status: 'failed' }));
  assert.equal(sent.length, before + 1);
  reply(sent.at(-1).id, { runId: 'run2', status: 'failed', error: 'x' });
  assert.equal((await done).status, 'failed');
});

test('waitForRun rejects when the request fails', async () => {
  const { client, sent, reply, timers } = setup();
  const done = waitForRun(client, 'run3', { timers, now: timers.now });
  reply(sent.at(-1).id, { code: 'not_found', message: 'gone' }, false);
  await assert.rejects(done, (err) => err.code === 'not_found');
});
