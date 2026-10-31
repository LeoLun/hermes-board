// Card runtime entry. Bundled as an IIFE and injected by the host as the first <script> in <head>,
// preceded by `window.__HB_BOOT__ = {...}`. The mount token lives only in this closure.
import { BoardError, createClient, topicMatches, waitForRun } from './protocol.js';
import fmt from './fmt.js';
import * as charts from './chart.js';
import { setState, setUpdated } from './ui.js';

(function bootRuntime(win) {
  if (win.HermesCard) return;
  const boot = win.__HB_BOOT__ || {};
  try {
    delete win.__HB_BOOT__;
  } catch {
    win.__HB_BOOT__ = undefined;
  }

  const parentWin = win.parent;
  const postToParent = parentWin.postMessage.bind(parentWin);
  const addListener = win.addEventListener.bind(win);
  const later = win.setTimeout.bind(win);
  const activation = win.navigator && win.navigator.userActivation;
  const activeGetter = activation
    ? Object.getOwnPropertyDescriptor(Object.getPrototypeOf(activation), 'isActive')?.get
    : undefined;
  const userActive = () => {
    try {
      return activeGetter ? !!activeGetter.call(activation) : true;
    } catch {
      return true;
    }
  };

  const client = createClient({ post: (msg) => postToParent(msg, '*'), token: String(boot.token || '') });
  const root = win.document.documentElement;

  function applyEnv(env) {
    if (!env) return;
    if (env.size && env.size.w && env.size.h) {
      root.dataset.size = env.size.label || `${env.size.w}x${env.size.h}`;
      root.dataset.w = String(env.size.w);
      root.dataset.h = String(env.size.h);
    }
    if (env.theme === 'light' || env.theme === 'dark') root.dataset.theme = env.theme;
  }

  applyEnv(boot);
  addListener('message', (event) => {
    if (event.source !== parentWin) return;
    client.handle(event.data);
  });
  client.on('init', applyEnv);
  client.on('theme', (e) => applyEnv({ theme: e.theme }));
  client.on('resize', (e) => applyEnv({ size: e.size }));

  // Subscriptions: union of all topics is sent to the host; `changed` fans out locally.
  const subs = new Set();
  function syncSubscriptions() {
    const topics = [...new Set([...subs].flatMap((s) => s.topics))];
    return client.request('subscribe', { topics }).catch(() => undefined);
  }
  client.on('changed', ({ topics = [] } = {}) => {
    for (const sub of subs) {
      for (const topic of topics) {
        if (!sub.topics.some((p) => topicMatches(p, topic))) continue;
        try {
          sub.fn(topic);
        } catch (err) {
          later(() => {
            throw err;
          }, 0);
        }
      }
    }
  });

  addListener('contextmenu', (event) => {
    if (event.defaultPrevented) return;
    event.preventDefault();
    client.request('ui.contextmenu', { x: event.clientX, y: event.clientY }).catch(() => undefined);
  });

  const api = {
    protocol: 1,
    Error: BoardError,
    ready: () => client.ready(),
    get env() {
      return client.env;
    },
    on: (type, fn) => client.on(type, fn),
    data: {
      get: (key) => client.request('data.get', { key }),
      list: () => client.request('data.list'),
    },
    series: {
      query: (name, opts = {}) => client.request('series.query', { ...opts, name }),
    },
    state: {
      get: (key) => client.request('state.get', { key }).then((r) => (r ? r.value : null)),
      set: (key, value) => client.request('state.set', { key, value }),
      delete: (key) => client.request('state.delete', { key }),
    },
    run(name, args = {}, opts = {}) {
      const started = client.request('scripts.run', { name, args });
      if (!opts.wait) return started;
      return started.then((r) => waitForRun(client, r.runId, { onProgress: opts.onProgress }));
    },
    scripts: {
      run: (name, args = {}) => client.request('scripts.run', { name, args }),
    },
    runs: {
      get: (runId) => client.request('runs.get', { runId }),
      list: (limit = 20) => client.request('runs.list', { limit }),
    },
    ai: {
      invoke: (name, input = {}) => client.request('ai.invoke', { name, input }, { timeoutMs: 130000 }),
    },
    subscribe(topics, fn) {
      const list = (Array.isArray(topics) ? topics : [topics]).filter((t) => typeof t === 'string');
      if (typeof fn !== 'function') throw new TypeError('subscribe 需要回调函数');
      const sub = { topics: list, fn };
      subs.add(sub);
      syncSubscriptions();
      return () => {
        if (subs.delete(sub)) syncSubscriptions();
      };
    },
    ui: {
      state: setState,
      updated: (el, ts) => setUpdated(el, ts),
      notify: (message, kind = 'info') => client.request('ui.notify', { message: String(message), kind }),
      remind: (opts = {}) => client.request('ui.remind', opts),
      cancelRemind: (id) => client.request('ui.cancelRemind', { id }),
      openExternal(url) {
        if (!userActive()) {
          return Promise.reject(new BoardError('invalid', 'openExternal 必须在用户点击等操作中调用'));
        }
        return client.request('ui.openExternal', { url: String(url) });
      },
      contextmenu: (pos = {}) => client.request('ui.contextmenu', { x: pos.x, y: pos.y }),
    },
    fmt,
    chart: {
      line: charts.line,
      sparkline: charts.sparkline,
      bar: charts.bar,
      ring: charts.ring,
    },
  };

  Object.defineProperty(win, 'HermesCard', { value: Object.freeze(api), writable: false, configurable: false });

  client.sendReady();
  // One retry in case the host listener attached late; the host ignores duplicate handshakes.
  later(() => {
    if (!client.env) client.sendReady();
  }, 1500);
})(window);
