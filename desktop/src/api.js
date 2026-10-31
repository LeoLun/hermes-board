// REST client over ctx.rest (design §9). Every path is relative to /api/plugins/hermes-board.
import constants from '../../shared/constants.json' with { type: 'json' };

export const API_VERSION = constants.apiVersion;
const STATUS_CODES = { 400: 'invalid', 401: 'unauthorized', 403: 'forbidden', 404: 'not_found', 409: 'conflict', 429: 'rate_limited' };

export class ApiError extends Error {
  constructor(status, code, message, detail = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

/**
 * ctx.rest rejects non-2xx with `Error("<status>: <body>")`, possibly prefixed by the IPC layer
 * ("Error invoking remote method 'hermes:api': Error: "). Anything else is a transport failure.
 */
export function parseRestError(err) {
  if (err instanceof ApiError) return err;
  const raw = String((err && err.message) || err || '');
  const m = /(?:^|:\s)(\d{3}): ([\s\S]*)$/.exec(raw);
  if (!m) return new ApiError(0, 'network', raw || '网络错误');
  const status = Number(m[1]);
  let body = null;
  try {
    body = JSON.parse(m[2]);
  } catch {
    body = null;
  }
  const detail = body && typeof body === 'object' ? (body.detail !== undefined ? body.detail : body) : null;
  const obj = detail && typeof detail === 'object' && !Array.isArray(detail) ? detail : null;
  const code = obj && typeof obj.code === 'string' ? obj.code : STATUS_CODES[status] || (status >= 500 ? 'internal' : 'error');
  const message = (obj && typeof obj.message === 'string' && obj.message) || (typeof detail === 'string' && detail) || m[2] || `HTTP ${status}`;
  return new ApiError(status, code, message, obj);
}

/** Compare the remote apiVersion with ours: 'ok' | 'update-remote' | 'update-desktop'. */
export function checkVersion(health) {
  const remote = Number(health && health.apiVersion);
  if (!Number.isFinite(remote) || remote < API_VERSION) return 'update-remote';
  if (remote > API_VERSION) return 'update-desktop';
  return 'ok';
}

const enc = encodeURIComponent;

function query(params) {
  const parts = [];
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null) parts.push(`${enc(k)}=${enc(String(v))}`);
  return parts.length ? `?${parts.join('&')}` : '';
}

/** @param {(path: string, opts?: object) => Promise<any>} rest  ctx.rest */
export function createApi(rest, { timeoutMs = 15000, aiTimeoutMs = 130000 } = {}) {
  async function call(path, opts = {}) {
    try {
      return await rest(path, { timeoutMs, ...opts });
    } catch (err) {
      throw parseRestError(err);
    }
  }
  const card = (id) => `/cards/${enc(id)}`;

  return {
    health: () => call('/health'),
    board: () => call('/board'),
    putBoard: (baseRevision, items) => call('/board', { method: 'PUT', body: { baseRevision, items } }),
    addItem: ({ baseRevision, card: id, size, x, y }) => call('/board/items', { method: 'POST', body: { baseRevision, card: id, size, x, y } }),
    removeItem: (id, baseRevision) => call(`/board/items/${enc(id)}${query({ baseRevision })}`, { method: 'DELETE' }),
    document: (id, known) => call(`${card(id)}/document${query({ known })}`),
    changes: (since) => call(`/changes${query({ since })}`),

    // Bridge-facing methods: the card id always comes from the host, never from the card.
    getData: (id, key) => call(`${card(id)}/data/${enc(key)}`),
    listData: async (id) => (await call(`${card(id)}/data`)).items || {},
    querySeries: async (id, name, q = {}) => (await call(`${card(id)}/series/${enc(name)}${query(q)}`)).points || [],
    getState: (id, key) => call(`${card(id)}/state/${enc(key)}`),
    setState: (id, key, value) => call(`${card(id)}/state/${enc(key)}`, { method: 'PUT', body: { value } }),
    deleteState: (id, key) => call(`${card(id)}/state/${enc(key)}`, { method: 'DELETE' }),
    startRun: (id, name, args = {}) => call(`${card(id)}/runs`, { method: 'POST', body: { script: name, args } }),
    /** Host menu "立即运行": any declared script, no min-interval (never reachable from a card). */
    runNow: (id, name) => call(`${card(id)}/runs`, { method: 'POST', body: { script: name, args: {}, trigger: 'manual' } }),
    async getRun(id, runId) {
      const run = await call(`/runs/${enc(runId)}`);
      if (!run || run.card !== id) throw new ApiError(404, 'not_found', `运行记录不存在：${runId}`);
      return run;
    },
    listRuns: async (id, limit = 20) => (await call(`${card(id)}/runs${query({ limit })}`)).runs || [],
    invokeAi: (id, name, input = {}) => call(`${card(id)}/ai/${enc(name)}`, { method: 'POST', body: { input }, timeoutMs: aiTimeoutMs }),
  };
}
