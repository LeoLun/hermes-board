// Plugin-level reminders for ui.remind (design §6.3). Timers live on ctx.setTimeout, so they keep firing
// after the board page unmounts; they are lost on app restart and re-registered by the card on next load.

/**
 * @param {object} o
 * @param {(fn: Function, ms: number) => (() => void)} o.setTimeout   ctx.setTimeout (returns a canceller)
 * @param {(reminder: {cardId, id, title, message}) => void} o.fire
 * @param {() => number} [o.now]
 */
export function createReminders({ setTimeout, fire, now = () => Date.now() }) {
  const timers = new Map();
  const keyOf = (cardId, id) => `${cardId}\u0000${id}`;

  function cancel(cardId, id) {
    const key = keyOf(cardId, id);
    const cancelTimer = timers.get(key);
    if (!cancelTimer) return { cancelled: false };
    timers.delete(key);
    try {
      cancelTimer();
    } catch {
      /* already fired */
    }
    return { cancelled: true };
  }

  return {
    schedule(cardId, { id, at, title, message = '' }) {
      cancel(cardId, id);
      const key = keyOf(cardId, id);
      const delay = Math.max(0, at - now());
      const cancelTimer = setTimeout(() => {
        timers.delete(key);
        fire({ cardId, id, title, message });
      }, delay);
      timers.set(key, typeof cancelTimer === 'function' ? cancelTimer : () => {});
      return { scheduled: true, at };
    },
    cancel,
    cancelAll() {
      for (const key of [...timers.keys()]) {
        const [cardId, id] = key.split('\u0000');
        cancel(cardId, id);
      }
    },
    get size() {
      return timers.size;
    },
  };
}
