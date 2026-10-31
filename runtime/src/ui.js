// DOM helpers exposed under HermesCard.ui (local-only parts).
import fmt from './fmt.js';

export const DEFAULT_TEXT = { loading: '加载中…', empty: '暂无数据', error: '加载失败' };
const KINDS = new Set(['loading', 'empty', 'error', 'ready']);

export function setState(el, kind, text) {
  if (!el) return;
  const k = KINDS.has(kind) ? kind : 'error';
  el.dataset.state = k;
  if (k === 'ready') {
    el.textContent = '';
    el.hidden = true;
    el.removeAttribute('role');
    return;
  }
  el.hidden = false;
  el.textContent = text === undefined || text === null || text === '' ? DEFAULT_TEXT[k] : String(text);
  el.setAttribute('role', k === 'error' ? 'alert' : 'status');
  el.setAttribute('aria-live', 'polite');
}

export function setUpdated(el, ts, now = Date.now()) {
  if (!el) return;
  el.textContent = fmt.updated(ts, now);
  if (typeof ts === 'number' && Number.isFinite(ts)) el.title = new Date(ts).toLocaleString('zh-CN');
}
