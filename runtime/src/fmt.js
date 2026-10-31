// Chinese formatting helpers exposed as HermesCard.fmt.
const DASH = '—';

function finite(n) {
  return typeof n === 'number' && Number.isFinite(n);
}

export function number(n, digits) {
  if (!finite(n)) return DASH;
  const opts = digits === undefined
    ? { maximumFractionDigits: 2 }
    : { minimumFractionDigits: digits, maximumFractionDigits: digits };
  return new Intl.NumberFormat('zh-CN', opts).format(n);
}

export function percent(ratio, digits = 0) {
  if (!finite(ratio)) return DASH;
  return `${number(ratio * 100, digits)}%`;
}

const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];

export function bytes(n) {
  if (!finite(n)) return DASH;
  const sign = n < 0 ? '-' : '';
  let v = Math.abs(n);
  let i = 0;
  while (v >= 1024 && i < BYTE_UNITS.length - 1) {
    v /= 1024;
    i += 1;
  }
  const text = i === 0 ? String(Math.round(v)) : v < 10 ? v.toFixed(1) : String(Math.round(v));
  return `${sign}${text} ${BYTE_UNITS[i]}`;
}

export function duration(ms) {
  if (!finite(ms)) return DASH;
  const total = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(total / 86400);
  const h = Math.floor((total % 86400) / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (d > 0) return h > 0 ? `${d} 天 ${h} 小时` : `${d} 天`;
  if (h > 0) return m > 0 ? `${h} 小时 ${m} 分` : `${h} 小时`;
  if (m > 0) return s > 0 ? `${m} 分 ${s} 秒` : `${m} 分`;
  return `${s} 秒`;
}

const pad2 = (n) => String(n).padStart(2, '0');

export function time(ts) {
  if (!finite(ts)) return DASH;
  const d = new Date(ts);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

export function date(ts, now = Date.now()) {
  if (!finite(ts)) return DASH;
  const d = new Date(ts);
  const base = `${d.getMonth() + 1}月${d.getDate()}日`;
  return d.getFullYear() === new Date(now).getFullYear() ? base : `${d.getFullYear()}年${base}`;
}

export function relative(ts, now = Date.now()) {
  if (!finite(ts)) return DASH;
  const diff = now - ts;
  const future = diff < 0;
  const abs = Math.abs(diff);
  const suffix = future ? '后' : '前';
  if (abs < 45 * 1000) return future ? '马上' : '刚刚';
  if (abs < 60 * 60 * 1000) return `${Math.max(1, Math.floor(abs / 60000))} 分钟${suffix}`;
  if (abs < 24 * 60 * 60 * 1000) return `${Math.floor(abs / 3600000)} 小时${suffix}`;
  if (abs < 7 * 24 * 60 * 60 * 1000) return `${Math.floor(abs / 86400000)} 天${suffix}`;
  return date(ts, now);
}

export function updated(ts, now = Date.now()) {
  if (!finite(ts)) return '';
  const a = new Date(ts);
  const b = new Date(now);
  const sameDay = a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  return `更新于 ${sameDay ? time(ts) : `${date(ts, now)} ${time(ts)}`}`;
}

export default { number, percent, bytes, duration, time, date, relative, updated };
