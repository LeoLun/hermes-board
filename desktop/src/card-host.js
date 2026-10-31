// One mounted card (design §6.1–6.4). Framework-free: the React view feeds it iframe load/message events
// and renders `snapshot().src` keyed by `snapshot().key` (a new key forces a fresh iframe).
import constants from '../../shared/constants.json' with { type: 'json' };
import { topicMatches } from '../../runtime/src/protocol.js';
import { createBridge } from './bridge.js';
import { buildCardDocument, randomToken } from './html-transform.js';

const MAX_SELF_RELOADS = 3;

/**
 * @param {object} o
 * @param {{id:string,title:string,version:string}} o.card
 * @param {{size:{w,h,label}, pixel:{width,height}, theme:'light'|'dark', visible:boolean}} o.env
 * @param {string} o.runtimeJs
 * @param {string} o.tokensCss
 * @param {object} o.api      bridge-facing REST methods (see api.js)
 * @param {object} o.ui       notify/remind/cancelRemind/openExternal/contextmenu
 * @param {(snapshot) => void} o.onChange
 */
export function createCardHost({ card, env, runtimeJs, tokensCss, api, ui, onChange = () => {}, setTimer, clearTimer,
  readyTimeoutMs = constants.bridge.readyTimeoutMs, makeToken = randomToken, now, log = () => {} }) {
  let current = { ...env };
  let html = null;
  let token = null;
  let bridge = null;
  let src = null;
  let status = 'idle';
  let error = null;
  let scriptError = null;
  let loads = 0;
  let selfReloads = 0;
  let timer = null;
  let disposed = false;

  const snapshot = () => ({ key: token, src, status, error, scriptError });
  const emit = () => {
    if (!disposed) onChange(snapshot());
  };
  const stopTimer = () => {
    if (timer !== null) clearTimer(timer);
    timer = null;
  };

  const getEnv = () => ({
    cardId: card.id, title: card.title, version: card.version, protocol: 1, locale: 'zh-CN',
    theme: current.theme, size: current.size, pixel: current.pixel, visible: current.visible !== false,
  });

  function mount() {
    if (disposed || html === null) return;
    stopTimer();
    bridge?.dispose();
    token = makeToken();
    loads = 0;
    status = 'loading';
    error = null;
    scriptError = null;
    bridge = createBridge({
      cardId: card.id, token, getEnv, api, ui, now, log,
      post: (msg) => post(msg),
      onReady: () => {
        stopTimer();
        if (status !== 'ready') {
          status = 'ready';
          emit();
        }
      },
      onError: (message) => {
        scriptError = message;
        emit();
      },
    });
    src = buildCardDocument(html, { token, card, size: current.size, pixel: current.pixel, theme: current.theme, runtimeJs, tokensCss });
    emit();
  }

  let frameWindow = null;
  function post(msg) {
    try {
      frameWindow?.postMessage(msg, '*');
    } catch (err) {
      log('card-host: postMessage failed', err);
    }
  }

  return {
    snapshot,
    get bridge() {
      return bridge;
    },
    /** (Re)load with new HTML; unchanged HTML keeps the current iframe. */
    setHtml(next) {
      if (next === html && token) return;
      html = next;
      selfReloads = 0;
      mount();
    },
    setFrameWindow(win) {
      frameWindow = win || null;
    },
    /** iframe `load`. A second load in the same mount means the card navigated itself → rebuild. */
    handleLoad() {
      if (disposed || !token) return;
      loads += 1;
      if (loads === 1) {
        stopTimer();
        timer = setTimer(() => {
          timer = null;
          if (status === 'loading') {
            status = 'timeout';
            error = '卡片在 10 秒内没有完成加载';
            emit();
          }
        }, readyTimeoutMs);
        return;
      }
      log(`card-host: ${card.id} navigated away from its document; rebuilding`);
      if (selfReloads >= MAX_SELF_RELOADS) {
        stopTimer();
        bridge?.dispose();
        status = 'error';
        error = '卡片反复尝试离开自身页面，已停止加载';
        emit();
        return;
      }
      selfReloads += 1;
      mount();
    },
    /** window `message`. Only messages whose source is this iframe's window reach the bridge. */
    handleMessage(event) {
      if (disposed || !bridge || !frameWindow || event.source !== frameWindow) return false;
      return bridge.handleMessage(event.data);
    },
    setEnv(next) {
      const prev = current;
      current = { ...current, ...next };
      if (!bridge || status !== 'ready') return;
      if (next.theme && next.theme !== prev.theme) bridge.sendEvent('theme', { theme: current.theme });
      const sizeChanged = next.size && (next.size.w !== prev.size?.w || next.size.h !== prev.size?.h);
      const pixelChanged = next.pixel && (next.pixel.width !== prev.pixel?.width || next.pixel.height !== prev.pixel?.height);
      if (sizeChanged || pixelChanged) bridge.sendEvent('resize', { size: current.size, pixel: current.pixel });
      if (next.visible !== undefined && next.visible !== prev.visible) bridge.sendEvent('visibility', { visible: !!current.visible });
    },
    /** Forward changed topics the card subscribed to. Returns the topics actually sent. */
    notifyTopics(topics) {
      if (!bridge || status !== 'ready') return [];
      const subs = bridge.topics;
      const matched = topics.filter((t) => subs.some((p) => topicMatches(p, t)));
      if (matched.length) bridge.sendEvent('changed', { topics: matched });
      return matched;
    },
    retry() {
      selfReloads = 0;
      mount();
    },
    fail(message) {
      stopTimer();
      bridge?.dispose();
      bridge = null;
      token = token || 'failed';
      src = null;
      status = 'error';
      error = message;
      emit();
    },
    dispose() {
      disposed = true;
      stopTimer();
      bridge?.dispose();
      frameWindow = null;
    },
  };
}

/**
 * Card documents cached per connection/profile/card; revalidated with `?known=<sha>` so an unchanged
 * card costs one tiny request.
 */
export function createDocCache() {
  const entries = new Map();
  const inflight = new Map();
  return {
    async load(api, scope, cardId) {
      const key = `${scope}|${cardId}`;
      if (inflight.has(key)) return inflight.get(key);
      const job = (async () => {
        const cached = entries.get(key);
        const res = await api.document(cardId, cached?.sha256);
        if (res && res.unchanged && cached) return cached;
        const entry = { html: res.html, sha256: res.sha256, revision: res.revision };
        entries.set(key, entry);
        return entry;
      })();
      inflight.set(key, job);
      try {
        return await job;
      } finally {
        inflight.delete(key);
      }
    },
    peek(scope, cardId) {
      return entries.get(`${scope}|${cardId}`) || null;
    },
    clear() {
      entries.clear();
    },
  };
}
