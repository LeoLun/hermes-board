// Card ⇄ host message protocol (design §6.2). Pure module: no DOM access, injectable timers.
export const NS = 'hermes-board';
export const VERSION = 1;
export const TERMINAL = ['succeeded', 'failed', 'timeout', 'cancelled'];
export const HOST_EVENTS = ['theme', 'resize', 'visibility', 'changed', 'run'];

export function makeMessage(type, token, fields = {}) {
  return { ns: NS, v: VERSION, type, token, ...fields };
}

export function isMessage(msg, token) {
  return !!msg && typeof msg === 'object' && msg.ns === NS && msg.v === VERSION &&
    typeof msg.type === 'string' && typeof token === 'string' && msg.token === token;
}

export class BoardError extends Error {
  constructor(code, message, extra = {}) {
    super(message || code);
    this.name = 'HermesCardError';
    this.code = code;
    Object.assign(this, extra);
  }
}

export function toError(error) {
  if (error instanceof BoardError) return error;
  const { code = 'internal', message = '未知错误', ...extra } = error || {};
  return new BoardError(code, message, extra);
}

export function topicMatches(pattern, topic) {
  if (pattern === topic) return true;
  if (pattern.endsWith(':*')) return topic.startsWith(pattern.slice(0, -1));
  return false;
}

/**
 * Create the card-side client.
 * @param {{post: (msg: object) => void, token: string, timers?: {setTimeout: Function, clearTimeout: Function},
 *          requestTimeoutMs?: number}} options
 */
export function createClient({ post, token, timers = globalThis, requestTimeoutMs = 30000 }) {
  let seq = 0;
  const pending = new Map();
  const listeners = new Map();
  let env = null;
  let readyResolve;
  const readyPromise = new Promise((resolve) => { readyResolve = resolve; });

  function emit(type, payload) {
    for (const fn of listeners.get(type) || []) {
      try { fn(payload); } catch (err) { setTimeoutSafe(() => { throw err; }); }
    }
  }

  function setTimeoutSafe(fn) { timers.setTimeout(fn, 0); }

  function on(type, fn) {
    if (!listeners.has(type)) listeners.set(type, new Set());
    listeners.get(type).add(fn);
    return () => listeners.get(type)?.delete(fn);
  }

  function request(method, params = {}, { timeoutMs = requestTimeoutMs } = {}) {
    const id = `r${++seq}`;
    return new Promise((resolve, reject) => {
      const timer = timers.setTimeout(() => {
        pending.delete(id);
        reject(new BoardError('timeout', `请求超时：${method}`));
      }, timeoutMs);
      pending.set(id, { resolve, reject, timer });
      try {
        post(makeMessage('request', token, { id, method, params }));
      } catch (err) {
        timers.clearTimeout(timer);
        pending.delete(id);
        reject(new BoardError('internal', String(err && err.message || err)));
      }
    });
  }

  /** Feed a raw incoming message. Returns true when it was accepted. */
  function handle(msg) {
    if (!isMessage(msg, token)) return false;
    if (msg.type === 'response') {
      const entry = pending.get(msg.id);
      if (!entry) return false;
      pending.delete(msg.id);
      timers.clearTimeout(entry.timer);
      if (msg.ok) entry.resolve(msg.result);
      else entry.reject(toError(msg.error));
      return true;
    }
    if (msg.type === 'init') {
      env = msg.env || {};
      readyResolve(env);
      emit('init', env);
      return true;
    }
    if (HOST_EVENTS.includes(msg.type)) {
      if (msg.type === 'theme' && env) env = { ...env, theme: msg.theme };
      if (msg.type === 'resize' && env) env = { ...env, size: msg.size, pixel: msg.pixel };
      const { ns, v, type, token: _t, ...payload } = msg;
      emit(type, payload);
      return true;
    }
    return false;
  }

  function sendReady() {
    post(makeMessage('ready', token));
  }

  return {
    request,
    handle,
    on,
    sendReady,
    ready: () => readyPromise,
    get env() { return env; },
    get pendingCount() { return pending.size; },
  };
}

/**
 * Wait for a run to reach a terminal state by polling ``runs.get``; ``run`` events trigger an immediate poll.
 */
export function waitForRun(client, runId, { intervalMs = 1000, timeoutMs = 11 * 60 * 1000, onProgress,
  timers = globalThis, now = () => Date.now() } = {}) {
  const started = now();
  return new Promise((resolve, reject) => {
    let timer = null;
    let inFlight = false;
    let lastProgress;
    let done = false;
    const off = client.on('run', (evt) => { if (evt && evt.runId === runId) poll(); });

    function finish(fn, value) {
      if (done) return;
      done = true;
      off();
      if (timer !== null) timers.clearTimeout(timer);
      fn(value);
    }

    function schedule() {
      if (done) return;
      if (timer !== null) timers.clearTimeout(timer);
      timer = timers.setTimeout(poll, intervalMs);
    }

    function poll() {
      if (done || inFlight) return;
      if (now() - started > timeoutMs) {
        finish(reject, new BoardError('timeout', '等待运行结束超时'));
        return;
      }
      inFlight = true;
      client.request('runs.get', { runId }).then((run) => {
        inFlight = false;
        if (TERMINAL.includes(run.status)) {
          finish(resolve, run);
          return;
        }
        const key = `${run.progress}|${run.message}|${run.status}`;
        if (onProgress && key !== lastProgress) {
          lastProgress = key;
          try { onProgress(run); } catch { /* card callback errors are its own */ }
        }
        schedule();
      }, (err) => {
        inFlight = false;
        finish(reject, err);
      });
    }

    poll();
  });
}
