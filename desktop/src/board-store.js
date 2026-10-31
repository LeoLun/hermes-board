// Board state for the current connection/profile (design §4, §5, §9). Framework-free; React reads it via
// subscribe/getState (useSyncExternalStore). All writes are serialized and optimistic.
import { checkVersion } from './api.js';
import { arrange, replay } from './layout-ops.js';

/** Phase for a failed load: 'not-installed' | 'unauthorized' | 'disconnected' | 'error'. */
export function phaseFor(err) {
  if (!err) return 'error';
  if (err.status === 404) return 'not-installed';
  if (err.status === 401 || err.status === 403) return 'unauthorized';
  if (err.code === 'network') return 'disconnected';
  return 'error';
}

const CONFLICT_MESSAGE = '布局已在其他地方更新，已显示最新布局';

/**
 * @param {object} o
 * @param {object} o.api                  see api.js
 * @param {(kind: string, message: string, extra?: object) => void} [o.notify]
 */
export function createBoardStore({ api, notify = () => {}, log = () => {} }) {
  let state = { phase: 'idle', error: null, health: null, layout: null, cards: [], connected: true };
  const listeners = new Set();
  let queue = Promise.resolve();
  let loadSeq = 0;
  let writing = 0;
  let refreshAfterWrite = false;

  function set(patch) {
    state = { ...state, ...patch };
    for (const fn of [...listeners]) fn(state);
  }

  function serial(fn) {
    const run = queue.then(fn, fn);
    queue = run.catch(() => undefined);
    return run;
  }

  function lost(err) {
    if (err && err.code === 'network' && state.connected) set({ connected: false });
  }

  async function load() {
    const seq = ++loadSeq;
    if (state.phase !== 'ready') set({ phase: 'loading', error: null });
    try {
      const health = await api.health();
      if (seq !== loadSeq) return state;
      const version = checkVersion(health);
      if (version !== 'ok') {
        set({ phase: version, health, error: null });
        return state;
      }
      const view = await api.board();
      if (seq !== loadSeq) return state;
      set({ phase: 'ready', health, layout: view.layout, cards: view.cards || [], error: null, connected: true });
    } catch (err) {
      if (seq !== loadSeq) return state;
      if (state.phase === 'ready' && err.code === 'network') set({ connected: false });
      else set({ phase: phaseFor(err), error: err });
    }
    return state;
  }

  async function refresh() {
    if (state.phase !== 'ready') return load();
    if (writing) {
      refreshAfterWrite = true;
      return state;
    }
    const seq = loadSeq;
    try {
      const view = await api.board();
      if (seq !== loadSeq) return state;
      if (writing) refreshAfterWrite = true;
      else set({ layout: view.layout, cards: view.cards || [], connected: true });
    } catch (err) {
      lost(err);
      if (err.code !== 'network') log('hermes-board: refresh failed', err);
    }
    return state;
  }

  function beginWrite() {
    writing += 1;
  }
  function endWrite() {
    writing -= 1;
    if (!writing && refreshAfterWrite) {
      refreshAfterWrite = false;
      refresh();
    }
  }

  /** Persist `items` produced by `op` (see layout-ops replay); on 409 replay once on the latest layout. */
  function commit(op, items) {
    return serial(async () => {
      const before = state.layout;
      if (!before) return { ok: false };
      beginWrite();
      set({ layout: { ...before, items } });
      try {
        let res;
        try {
          res = await api.putBoard(before.revision, items);
        } catch (err) {
          if (err.code !== 'conflict' || !err.detail || !err.detail.current) throw err;
          const latest = err.detail.current;
          const again = replay(op, latest.items);
          if (!again) {
            set({ layout: latest });
            notify('warning', CONFLICT_MESSAGE);
            return { ok: false, conflict: true };
          }
          set({ layout: { ...latest, items: again } });
          try {
            res = await api.putBoard(latest.revision, again);
          } catch (err2) {
            if (err2.code === 'conflict' && err2.detail && err2.detail.current) {
              set({ layout: err2.detail.current });
              notify('warning', CONFLICT_MESSAGE);
              return { ok: false, conflict: true };
            }
            throw err2;
          }
        }
        set({ layout: res.layout, connected: true });
        return { ok: true, layout: res.layout };
      } catch (err) {
        set({ layout: before });
        lost(err);
        notify('error', `保存布局失败：${err.message}`);
        return { ok: false, error: err };
      } finally {
        endWrite();
      }
    });
  }

  async function arrangeBoard() {
    if (state.phase !== 'ready' || !state.layout) return { changed: false };
    const items = state.layout.items;
    const result = arrange(items);
    if (!result.changed) {
      notify('info', '卡片已经是最紧凑的排列');
      return { changed: false };
    }
    const saved = await commit({ type: 'arrange' }, result.items);
    if (!saved.ok) return { changed: false };
    const undo = () => {
      const op = { type: 'restore', items };
      const restored = replay(op, state.layout.items);
      return commit(op, restored);
    };
    return { changed: true, undo };
  }

  /** Server-side item operations (add / remove) — retried once with the latest revision on 409. */
  function itemOp(run, failure) {
    return serial(async () => {
      if (!state.layout) return { ok: false };
      beginWrite();
      try {
        let res;
        try {
          res = await run(state.layout.revision);
        } catch (err) {
          if (err.code !== 'conflict' || !err.detail || !err.detail.current) throw err;
          res = await run(err.detail.current.revision);
        }
        set({ layout: res.layout, connected: true });
        return { ok: true, layout: res.layout };
      } catch (err) {
        lost(err);
        notify('error', `${failure}：${err.message}`);
        return { ok: false, error: err };
      } finally {
        refreshAfterWrite = true; // card summaries carry onBoard flags and cron status
        endWrite();
      }
    });
  }

  return {
    getState: () => state,
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    load,
    refresh,
    commit,
    arrange: arrangeBoard,
    addCard: (cardId, size) => itemOp((rev) => api.addItem({ baseRevision: rev, card: cardId, size }), '添加卡片失败'),
    removeCard: (cardId) => itemOp((rev) => api.removeItem(cardId, rev), '移除卡片失败'),
    setConnected(ok) {
      if (ok && !state.connected) {
        set({ connected: true });
        refresh();
        return true;
      }
      if (!ok && state.connected && state.phase === 'ready') set({ connected: false });
      return false;
    },
    /** Connection or profile switched: forget everything and load again. */
    reset() {
      loadSeq += 1;
      set({ phase: 'idle', error: null, health: null, layout: null, cards: [], connected: true });
      return load();
    },
    card(cardId) {
      return state.cards.find((c) => c.id === cardId) || null;
    },
    /** Wait for queued writes (tests, palette commands). */
    idle: () => queue,
  };
}
