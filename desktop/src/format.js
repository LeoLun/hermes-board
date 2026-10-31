// Text formatting for host chrome (runs dialog, about dialog, toasts). Pure.
import { displaySize, parseSize } from './layout-ops.js';

export const RUN_STATUS = { queued: '排队中', running: '运行中', succeeded: '成功', failed: '失败', timeout: '超时', cancelled: '已取消' };
export const RUN_TRIGGER = { cron: '定时', action: '卡片', install: '安装', tool: 'Agent', manual: '手动' };

const pad = (n) => String(n).padStart(2, '0');

export function fmtTime(ts, now = Date.now()) {
  if (!ts) return '—';
  const d = new Date(ts);
  const today = new Date(now);
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  if (d.toDateString() === today.toDateString()) return `今天 ${hm}`;
  const y = new Date(now - 86400000);
  if (d.toDateString() === y.toDateString()) return `昨天 ${hm}`;
  return `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
}

export function fmtDuration(run) {
  if (!run || run.startedAt == null || run.finishedAt == null) return run && (run.status === 'running' || run.status === 'queued') ? '进行中' : '—';
  const ms = Math.max(0, run.finishedAt - run.startedAt);
  if (ms < 1000) return `${ms} 毫秒`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} 秒`;
  const m = Math.floor(ms / 60000);
  return `${m} 分 ${Math.round((ms % 60000) / 1000)} 秒`;
}

/** error field first, else the last lines of stderr; at most `max` characters. */
export function errorSummary(run, max = 400) {
  if (!run) return '';
  if (run.error) return String(run.error).slice(0, max);
  const tail = String(run.stderrTail || '').trim();
  if (!tail) return '';
  const lines = tail.split('\n').filter((l) => l.trim());
  let out = lines.slice(-4).join('\n');
  if (out.length > max) out = `…${out.slice(-max)}`;
  return out;
}

export function fmtSize(label) {
  try {
    const { w, h } = parseSize(label);
    return displaySize(w, h);
  } catch {
    return String(label || '');
  }
}

export function cardProblem(card) {
  if (!card) return '卡片包不存在或已被删除';
  const errs = Array.isArray(card.errors) ? card.errors : [];
  const first = errs[0];
  const text = typeof first === 'string' ? first : first && (first.message || first.msg);
  if (card.status === 'missing') return '卡片包不存在或已被删除';
  return text ? `卡片清单不合法：${text}` : '卡片清单不合法';
}

export function cronText(script) {
  if (!script || !script.schedule) return '仅手动运行';
  if (!script.cronAvailable) return `${script.schedule} · 定时不可用`;
  const c = script.cron;
  if (!c) return `${script.schedule} · 未登记`;
  if (c.paused || c.enabled === false) return `${script.schedule} · 已暂停`;
  return `${script.schedule} · 已启用`;
}
