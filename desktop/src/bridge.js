// Host-side bridge for one mounted card (design §6.2–6.3). Framework-free; all effects are injected.
import constants from '../../shared/constants.json' with { type: 'json' };
import { NS, VERSION, makeMessage } from '../../runtime/src/protocol.js';

export const KEY_RE = /^[A-Za-z0-9_.-]{1,64}$/;
export const NAME_RE = /^[a-z][a-z0-9_]{0,31}$/;
export const TOPIC_RE = /^(?:(?:data|series|state):[A-Za-z0-9_.-]{1,64}|run:\*)$/;
const NOTIFY_KINDS = new Set(['info', 'success', 'warning', 'error']);
const MAX_TOPICS = 64;
const MAX_REMIND_AHEAD_MS = 7 * 24 * 3600 * 1000;
const B = constants.bridge;
const L = constants.limits;

export class BridgeError extends Error {
  constructor(code, message, extra = {}) {
    super(message);
    this.code = code;
    Object.assign(this, extra);
  }
}

const invalid = (message) => new BridgeError('invalid', message);

export function jsonBytes(value) {
  let text;
  try {
    text = JSON.stringify(value);
  } catch {
    throw invalid('值无法序列化为 JSON');
  }
  if (text === undefined) throw invalid('值无法序列化为 JSON');
  return new TextEncoder().encode(text).length;
}

function isPlainObject(v) {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

function key(params, field = 'key') {
  const v = params[field];
  if (typeof v !== 'string' || !KEY_RE.test(v)) throw invalid(`${field} 不合法`);
  return v;
}

function name(params) {
  const v = params.name;
  if (typeof v !== 'string' || !NAME_RE.test(v)) throw invalid('name 不合法');
  return v;
}

function optNumber(params, field) {
  const v = params[field];
  if (v === undefined || v === null) return undefined;
  if (typeof v !== 'number' || !Number.isFinite(v)) throw invalid(`${field} 必须是数字`);
  return v;
}

function optInt(params, field, lo, hi) {
  const v = optNumber(params, field);
  if (v === undefined) return undefined;
  if (!Number.isInteger(v) || v < lo || v > hi) throw invalid(`${field} 必须是 ${lo} 到 ${hi} 的整数`);
  return v;
}

function text(params, field, max, required = true) {
  const v = params[field];
  if (v === undefined && !required) return undefined;
  if (typeof v !== 'string' || (required && v.length === 0)) throw invalid(`${field} 必须是字符串`);
  return v.slice(0, max);
}

export function validateHttpUrl(raw) {
  let url;
  try {
    url = new URL(String(raw));
  } catch {
    throw invalid('链接不合法');
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') throw invalid('只允许打开 http(s) 链接');
  return url.toString();
}

export function createRateWindow(limit, windowMs, now) {
  const hits = [];
  return {
    take() {
      const t = now();
      while (hits.length && t - hits[0] >= windowMs) hits.shift();
      if (hits.length >= limit) return windowMs - (t - hits[0]);
      hits.push(t);
      return 0;
    },
  };
}

/**
 * @param {object} o
 * @param {string} o.cardId          card id held by the host (requests can never choose another card)
 * @param {string} o.token           mount token
 * @param {(msg: object) => void} o.post        post a message into the iframe
 * @param {() => object} o.getEnv
 * @param {object} o.api             REST client: getData, listData, querySeries, getState, setState, deleteState,
 *                                   startRun, getRun, listRuns, invokeAi — each (cardId, ...) => Promise
 * @param {object} o.ui              notify(cardId, message, kind), remind(cardId, r), cancelRemind(cardId, id),
 *                                   openExternal(url), contextmenu(cardId, {x, y})
 * @param {() => void} [o.onReady]
 * @param {(topics: string[]) => void} [o.onSubscribe]
 * @param {() => number} [o.now]
 * @param {(...args: any[]) => void} [o.log]
 */
export function createBridge({ cardId, token, post, getEnv, api, ui, onReady, onSubscribe, now = () => Date.now(), log = () => {} }) {
  const requests = createRateWindow(B.requestsPerSecond, 1000, now);
  const aiWindow = createRateWindow(B.aiPerMinute, 60000, now);
  let aiInFlight = 0;
  let lastNotify = -Infinity;
  let topics = [];
  let disposed = false;

  const methods = {
    'env.get': () => getEnv(),
    'data.get': (p) => api.getData(cardId, key(p)),
    'data.list': () => api.listData(cardId),
    'series.query': (p) => {
      const query = {
        since: optNumber(p, 'since'),
        until: optNumber(p, 'until'),
        limit: optInt(p, 'limit', 1, L.seriesQueryLimit),
        order: p.order === undefined ? undefined : p.order,
      };
      if (query.order !== undefined && query.order !== 'asc' && query.order !== 'desc') throw invalid('order 只能是 asc 或 desc');
      return api.querySeries(cardId, key(p, 'name'), query);
    },
    'state.get': (p) => api.getState(cardId, key(p)),
    'state.set': (p) => {
      const k = key(p);
      if (!('value' in p)) throw invalid('缺少 value');
      if (jsonBytes(p.value) > L.stateValueBytes) throw new BridgeError('too_large', `状态值超过 ${L.stateValueBytes} 字节`);
      return api.setState(cardId, k, p.value);
    },
    'state.delete': (p) => api.deleteState(cardId, key(p)),
    'scripts.run': (p) => {
      const args = p.args === undefined ? {} : p.args;
      if (!isPlainObject(args)) throw invalid('args 必须是对象');
      return api.startRun(cardId, name(p), args);
    },
    'runs.get': (p) => {
      if (typeof p.runId !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(p.runId)) throw invalid('runId 不合法');
      return api.getRun(cardId, p.runId);
    },
    'runs.list': (p) => api.listRuns(cardId, optInt(p, 'limit', 1, L.runsPerCard) ?? 20),
    'ai.invoke': async (p) => {
      const n = name(p);
      const input = p.input === undefined ? {} : p.input;
      if (!isPlainObject(input)) throw invalid('input 必须是对象');
      if (jsonBytes(input) > L.aiInputBytes) throw new BridgeError('too_large', `输入超过 ${L.aiInputBytes} 字节`);
      if (aiInFlight >= B.aiConcurrent) throw new BridgeError('busy', 'AI 任务正在运行');
      const wait = aiWindow.take();
      if (wait > 0) throw new BridgeError('rate_limited', 'AI 调用过于频繁', { retryAfterMs: wait });
      aiInFlight += 1;
      try {
        return await api.invokeAi(cardId, n, input);
      } finally {
        aiInFlight -= 1;
      }
    },
    subscribe: (p) => {
      const list = p.topics;
      if (!Array.isArray(list) || list.length > MAX_TOPICS) throw invalid(`topics 必须是不超过 ${MAX_TOPICS} 项的数组`);
      for (const t of list) if (typeof t !== 'string' || !TOPIC_RE.test(t)) throw invalid(`主题不合法：${String(t)}`);
      topics = [...new Set(list)];
      onSubscribe?.(topics);
      return { topics };
    },
    'ui.notify': (p) => {
      const message = text(p, 'message', 200);
      const kind = p.kind === undefined ? 'info' : p.kind;
      if (!NOTIFY_KINDS.has(kind)) throw invalid('kind 不合法');
      const t = now();
      if (t - lastNotify < B.notifyIntervalMs) {
        throw new BridgeError('rate_limited', '提示过于频繁', { retryAfterMs: B.notifyIntervalMs - (t - lastNotify) });
      }
      lastNotify = t;
      ui.notify(cardId, message, kind);
      return { shown: true };
    },
    'ui.remind': (p) => {
      const id = key(p, 'id');
      const at = optNumber(p, 'at');
      const t = now();
      if (at === undefined || at <= t - 1000 || at > t + MAX_REMIND_AHEAD_MS) throw invalid('at 必须是未来 7 天内的时间');
      const reminder = { id, at, title: text(p, 'title', 60), message: text(p, 'message', 200, false) ?? '' };
      return ui.remind(cardId, reminder);
    },
    'ui.cancelRemind': (p) => ui.cancelRemind(cardId, key(p, 'id')),
    'ui.openExternal': (p) => {
      const url = validateHttpUrl(p.url);
      return Promise.resolve(ui.openExternal(url)).then(() => ({ opened: true }));
    },
    'ui.contextmenu': (p) => {
      const x = optNumber(p, 'x') ?? 0;
      const y = optNumber(p, 'y') ?? 0;
      ui.contextmenu(cardId, { x, y });
      return { opened: true };
    },
  };

  function respond(id, ok, payload) {
    if (disposed) return;
    post(makeMessage('response', token, ok ? { id, ok: true, result: payload === undefined ? null : payload } : { id, ok: false, error: payload }));
  }

  function toWireError(err) {
    if (err && typeof err.code === 'string') {
      const out = { code: err.code, message: String(err.message || err.code) };
      if (typeof err.retryAfterMs === 'number') out.retryAfterMs = Math.max(0, Math.round(err.retryAfterMs));
      if (Array.isArray(err.errors)) out.errors = err.errors.slice(0, 20);
      return out;
    }
    log('bridge: unexpected error', err);
    return { code: 'internal', message: String((err && err.message) || err || '未知错误') };
  }

  async function handleRequest(msg) {
    const { id, method } = msg;
    if (typeof id !== 'string' || id.length > 64) return;
    const params = msg.params === undefined ? {} : msg.params;
    if (!Object.prototype.hasOwnProperty.call(methods, method)) {
      respond(id, false, { code: 'invalid', message: `不支持的方法：${String(method)}` });
      return;
    }
    if (!isPlainObject(params)) {
      respond(id, false, { code: 'invalid', message: 'params 必须是对象' });
      return;
    }
    const wait = requests.take();
    if (wait > 0) {
      respond(id, false, { code: 'rate_limited', message: '请求过于频繁', retryAfterMs: wait });
      return;
    }
    try {
      if (jsonBytes(params) > B.maxParamBytes) throw new BridgeError('too_large', '请求参数过大');
      const result = await methods[method](params);
      respond(id, true, result);
    } catch (err) {
      respond(id, false, toWireError(err));
    }
  }

  /** Accept a message whose source has already been verified by the caller. */
  function handleMessage(msg) {
    if (disposed || !msg || typeof msg !== 'object' || msg.ns !== NS || msg.v !== VERSION || msg.token !== token) {
      return false;
    }
    if (msg.type === 'ready') {
      post(makeMessage('init', token, { env: getEnv() }));
      onReady?.();
      return true;
    }
    if (msg.type === 'request') {
      handleRequest(msg);
      return true;
    }
    return false;
  }

  function sendEvent(type, payload = {}) {
    if (disposed) return;
    post(makeMessage(type, token, payload));
  }

  return {
    handleMessage,
    sendEvent,
    get topics() {
      return topics;
    },
    dispose() {
      disposed = true;
    },
  };
}
