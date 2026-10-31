// Change polling (design §6.4). Timers are injected so tests can drive time.
import constants from '../../shared/constants.json' with { type: 'json' };

/**
 * @param {object} o
 * @param {(since?: number) => Promise<{seq:number, changes:Array, reset?:boolean}>} o.fetchChanges
 * @param {(changes: Array) => void} o.onChanges
 * @param {() => void} o.onReset          the server could not serve the gap → refresh everything
 * @param {(ok: boolean, err?: any) => void} [o.onStatus]  called on every poll outcome
 * @param {(fn: Function, ms: number) => any} o.setTimer
 * @param {(handle: any) => void} o.clearTimer
 */
export function createPoller({ fetchChanges, onChanges, onReset, onStatus = () => {}, setTimer, clearTimer,
  visibleMs = constants.poll.visibleMs, hiddenMs = constants.poll.hiddenMs, visible = true }) {
  let seq = null;
  let running = false;
  let inflight = false;
  let again = false;
  let timer = null;
  let isVisible = visible;
  let generation = 0;

  const interval = () => (isVisible ? visibleMs : hiddenMs);

  function schedule(ms) {
    if (timer !== null) clearTimer(timer);
    timer = running ? setTimer(() => {
      timer = null;
      tick();
    }, ms) : null;
  }

  async function tick() {
    if (!running) return;
    if (inflight) {
      again = true;
      return;
    }
    inflight = true;
    const gen = generation;
    try {
      const res = await fetchChanges(seq === null ? undefined : seq);
      if (gen !== generation) return;
      const baseline = seq === null;
      seq = Number(res && res.seq) || 0;
      if (!baseline) {
        if (res.reset) onReset();
        else if (Array.isArray(res.changes) && res.changes.length) onChanges(res.changes);
      }
      onStatus(true);
    } catch (err) {
      if (gen === generation) onStatus(false, err);
    } finally {
      inflight = false;
      if (gen === generation && running) {
        if (again) {
          again = false;
          tick();
        } else schedule(interval());
      }
    }
  }

  return {
    start() {
      if (running) return;
      running = true;
      tick();
    },
    stop() {
      running = false;
      generation += 1;
      inflight = false;
      again = false;
      if (timer !== null) clearTimer(timer);
      timer = null;
    },
    /** Poll now (events, a card's run finished, window regained focus). Coalesces with an in-flight poll. */
    kick() {
      if (!running) return;
      if (timer !== null) {
        clearTimer(timer);
        timer = null;
      }
      tick();
    },
    setVisible(v) {
      const was = isVisible;
      isVisible = !!v;
      if (!running) return;
      if (isVisible && !was) this.kick();
      else if (!inflight) schedule(interval());
    },
    /** Forget the cursor (connection/profile switch): the next poll only re-establishes the baseline. */
    rebase() {
      seq = null;
      generation += 1;
      inflight = false;
      again = false;
      if (running) tick();
    },
    get seq() {
      return seq;
    },
    get interval() {
      return interval();
    },
  };
}

/** Topic a change record maps to, as cards subscribe to it ('data:<key>' …, 'run:*'). */
export function changeTopic(change) {
  if (change.kind === 'run') return 'run:*';
  if (change.kind === 'data' || change.kind === 'series' || change.kind === 'state') return `${change.kind}:${change.name}`;
  return null;
}

/**
 * Fan changes out: per-card topic lists, card package updates and layout updates are batched into one
 * callback per listener per poll.
 */
export function createChangeHub() {
  const cards = new Map();
  const layoutListeners = new Set();

  return {
    /** listener({topics, cardChanged, reset}) */
    subscribeCard(cardId, listener) {
      if (!cards.has(cardId)) cards.set(cardId, new Set());
      cards.get(cardId).add(listener);
      return () => {
        const set = cards.get(cardId);
        if (set) {
          set.delete(listener);
          if (!set.size) cards.delete(cardId);
        }
      };
    },
    onLayout(listener) {
      layoutListeners.add(listener);
      return () => layoutListeners.delete(listener);
    },
    dispatch(changes) {
      const perCard = new Map();
      let layout = false;
      for (const c of changes) {
        if (c.kind === 'layout') {
          layout = true;
          continue;
        }
        if (!c.card) continue;
        if (!perCard.has(c.card)) perCard.set(c.card, { topics: new Set(), cardChanged: false });
        const entry = perCard.get(c.card);
        if (c.kind === 'card') {
          entry.cardChanged = true;
          layout = true; // titles, sizes and scripts in /board may have changed too
        }
        const topic = changeTopic(c);
        if (topic) entry.topics.add(topic);
      }
      for (const [cardId, entry] of perCard) {
        for (const fn of cards.get(cardId) || []) fn({ topics: [...entry.topics], cardChanged: entry.cardChanged, reset: false });
      }
      if (layout) for (const fn of layoutListeners) fn();
    },
    reset() {
      for (const set of cards.values()) for (const fn of set) fn({ topics: [], cardChanged: true, reset: true });
      for (const fn of layoutListeners) fn();
    },
  };
}
