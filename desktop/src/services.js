// Plugin-level services shared by the page and every card host. Created once per plugin activation.
import constants from '../../shared/constants.json' with { type: 'json' };
import { createApi } from './api.js';
import { createBoardStore } from './board-store.js';
import { createDocCache } from './card-host.js';
import { replay, sizeLabel } from './layout-ops.js';
import { createChangeHub, createPoller } from './poller.js';
import { createReminders } from './reminders.js';

export const BOARD_PATH = '/hermes-board';
export const BACKEND_EVENTS = ['layout.updated', 'card.updated', 'card.removed', 'run.finished'];

export function createEmitter() {
  const set = new Set();
  return {
    on(fn) {
      set.add(fn);
      return () => set.delete(fn);
    },
    emit(value) {
      for (const fn of [...set]) fn(value);
    },
  };
}

/**
 * @param {object} o
 * @param {(path: string, opts: object) => Promise<any>} o.rest         ctx.rest
 * @param {(fn: () => void, ms: number) => () => void} o.setTimeout   ctx.setTimeout (returns a cancel function)
 * @param {(type: string, listener: Function) => () => void} [o.onEvent] ctx.onEvent
 * @param {(input: object) => void} o.notify                          host.notify
 * @param {{notify?: Function, openExternal?: Function}} [o.os]        ctx.os
 */
export function createServices({ rest, setTimeout, onEvent, notify, os = {}, runtimeJs, tokensCss,
  log = (...args) => console.warn(...args), doc = globalThis.document, win = globalThis.window }) {
  const api = createApi(rest);
  const toast = (kind, message, extra = {}) => {
    try {
      notify({ kind, message, ...extra });
    } catch (err) {
      log('hermes-board: notify failed', err);
    }
  };
  const store = createBoardStore({ api, notify: (kind, message) => toast(kind, message), log });
  const hub = createChangeHub();
  const docCache = createDocCache();
  const frames = new Map();
  const menuBus = createEmitter();
  const disposers = [];
  const titleOf = (cardId) => {
    const c = store.card(cardId);
    return (c && c.title) || cardId;
  };

  const poller = createPoller({
    fetchChanges: (since) => api.changes(since),
    onChanges: (changes) => hub.dispatch(changes),
    onReset: () => hub.reset(),
    onStatus: (ok, err) => {
      if (ok) {
        if (store.setConnected(true)) hub.reset();
      } else if (err && err.code === 'network') {
        store.setConnected(false);
      }
    },
    setTimer: (fn, ms) => setTimeout(fn, ms),
    clearTimer: (cancel) => {
      if (typeof cancel === 'function') cancel();
    },
  });
  disposers.push(hub.onLayout(() => store.refresh()));

  if (typeof onEvent === 'function') {
    for (const name of BACKEND_EVENTS) {
      const off = onEvent(`plugin.${constants.pluginId}.${name}`, () => poller.kick());
      if (typeof off === 'function') disposers.push(off);
    }
  }

  const reminders = createReminders({
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    fire: ({ cardId, title, message }) => {
      const body = message || titleOf(cardId);
      toast('info', body, { title, durationMs: 15000 });
      try {
        if (os && typeof os.notify === 'function') os.notify({ title, body, activate: BOARD_PATH });
      } catch (err) {
        log('hermes-board: os.notify failed', err);
      }
    },
  });

  const ui = {
    notify: (cardId, message, kind) => toast(kind || 'info', message, { title: titleOf(cardId) }),
    remind: (cardId, reminder) => reminders.schedule(cardId, reminder),
    cancelRemind: (cardId, id) => reminders.cancel(cardId, id),
    openExternal: (url) => {
      if (!os || typeof os.openExternal !== 'function') return Promise.reject(new Error('当前 Desktop 不支持打开外部链接'));
      return os.openExternal(url);
    },
    contextmenu: (cardId, { x, y }) => {
      const frame = frames.get(cardId);
      if (!frame || !frame.element) return;
      const r = frame.element.getBoundingClientRect();
      menuBus.emit({ cardId, clientX: r.left + x, clientY: r.top + y });
    },
  };

  let scope = null;
  let attached = 0;

  const onVisibility = () => poller.setVisible(!doc || doc.visibilityState !== 'hidden');
  const onFocus = () => poller.kick();

  const services = {
    api, store, hub, poller, docCache, reminders, frames, menuBus, runtimeJs, tokensCss, log,
    cardUi: () => ui,
    registerFrame(cardId, entry) {
      frames.set(cardId, entry);
      return () => {
        if (frames.get(cardId) === entry) frames.delete(cardId);
      };
    },
    /** Page mounted: poll while it is visible. Returns the detach function. */
    attachPage() {
      attached += 1;
      if (attached === 1) {
        if (doc) doc.addEventListener('visibilitychange', onVisibility);
        if (win) win.addEventListener('focus', onFocus);
        onVisibility();
        poller.start();
        if (scope !== null) store.load();
      }
      return () => {
        attached -= 1;
        if (attached === 0) {
          poller.stop();
          if (doc) doc.removeEventListener('visibilitychange', onVisibility);
          if (win) win.removeEventListener('focus', onFocus);
        }
      };
    },
    /** Connection/profile of the current gateway. A change drops everything from the old one. */
    setScope(next) {
      if (next === scope) return;
      const first = scope === null;
      scope = next;
      if (first) {
        store.load();
        return;
      }
      docCache.clear();
      store.reset();
      poller.rebase();
    },
    get scope() {
      return scope;
    },
    async runNow(cardId, name) {
      try {
        await api.runNow(cardId, name);
        toast('info', `已开始运行 ${name}`, { title: titleOf(cardId), durationMs: 3000 });
        poller.kick();
      } catch (err) {
        toast('error', `运行 ${name} 失败：${err.message}`, { title: titleOf(cardId) });
      }
    },
    addCard: (cardId) => store.addCard(cardId),
    async removeCard(cardId) {
      const layout = store.getState().layout;
      const before = layout && layout.items.find((i) => i.card === cardId);
      const title = titleOf(cardId);
      const res = await store.removeCard(cardId);
      if (!res.ok || !before) return res;
      toast('info', `已从看板移除「${title}」`, {
        detail: '卡片包和数据仍然保留，可以在“添加卡片”中重新添加。',
        durationMs: 8000,
        action: {
          label: '撤销',
          onClick: async () => {
            const added = await store.addCard(cardId, sizeLabel(before.w, before.h));
            if (!added.ok) return;
            const items = store.getState().layout.items;
            const placed = items.find((i) => i.card === cardId);
            if (!placed || (placed.x === before.x && placed.y === before.y)) return;
            const op = { type: 'rect', id: placed.id, rect: { x: before.x, y: before.y, w: placed.w, h: placed.h } };
            const next = replay(op, items);
            if (next) await store.commit(op, next);
          },
        },
      });
      return res;
    },
    async arrangeWithUndo() {
      if (store.getState().phase !== 'ready') await store.load();
      const res = await store.arrange();
      if (res.changed) {
        toast('success', '已自动整理', { durationMs: 8000, action: { label: '撤销', onClick: () => res.undo() } });
      }
      return res;
    },
    reloadCard(cardId) {
      const frame = frames.get(cardId);
      if (frame) frame.reload();
    },
    async reloadAll() {
      docCache.clear();
      await store.load();
      for (const frame of frames.values()) frame.reload();
      poller.kick();
    },
    dispose() {
      poller.stop();
      reminders.cancelAll();
      for (const off of disposers.splice(0)) {
        try {
          off();
        } catch {
          /* ignore */
        }
      }
    },
  };
  return services;
}
