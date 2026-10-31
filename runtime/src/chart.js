// SVG charts exposed as HermesCard.chart. Pure *Svg builders return strings (tested in node);
// the DOM wrappers measure the container and render into it.
import fmt from './fmt.js';

const STATUS = new Set(['positive', 'warning', 'critical']);
const SERIES_COLORS = ['var(--hb-accent)', 'var(--hb-ink-2)', 'var(--hb-ink-muted)'];

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const r1 = (n) => Math.round(n * 10) / 10;
const finite = (n) => typeof n === 'number' && Number.isFinite(n);

function open(width, height, label) {
  const aria = label ? ` aria-label="${esc(label)}"` : '';
  return `<svg class="hb-chart" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img"${aria}>`;
}

export function normalizeSeries(series) {
  if (!Array.isArray(series) || series.length === 0) return [];
  const list = series[0] && typeof series[0] === 'object' && Array.isArray(series[0].points)
    ? series
    : [{ name: '', points: series }];
  return list.map((s) => ({
    name: s.name || '',
    points: (s.points || []).filter((p) => p && finite(p.ts) && finite(p.value)).sort((a, b) => a.ts - b.ts),
  }));
}

function extent(values, min, max, padRatio) {
  let lo = finite(min) ? min : Math.min(...values);
  let hi = finite(max) ? max : Math.max(...values);
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  } else if (!finite(min) || !finite(max)) {
    const pad = (hi - lo) * padRatio;
    if (!finite(min)) lo -= pad;
    if (!finite(max)) hi += pad;
  }
  return [lo, hi];
}

export function lineSvg(series, { width = 300, height = 120, min, max, yFormat, xFormat, label } = {}) {
  const list = normalizeSeries(series);
  const points = list.flatMap((s) => s.points);
  let out = open(width, height, label);
  if (points.length === 0) return `${out}</svg>`;
  const padL = 36;
  const padR = 6;
  const padT = 8;
  const padB = 18;
  const innerW = Math.max(1, width - padL - padR);
  const innerH = Math.max(1, height - padT - padB);
  let t0 = Math.min(...points.map((p) => p.ts));
  let t1 = Math.max(...points.map((p) => p.ts));
  if (t0 === t1) {
    t0 -= 1;
    t1 += 1;
  }
  const [v0, v1] = extent(points.map((p) => p.value), min, max, 0.05);
  const x = (ts) => r1(padL + ((ts - t0) / (t1 - t0)) * innerW);
  const y = (v) => r1(padT + (1 - (v - v0) / (v1 - v0)) * innerH);
  const yf = typeof yFormat === 'function' ? yFormat : (v) => fmt.number(v, Math.abs(v1 - v0) < 10 ? 1 : 0);
  const span = t1 - t0;
  const xf = typeof xFormat === 'function' ? xFormat : (ts) => (span > 36 * 3600 * 1000 ? fmt.date(ts) : fmt.time(ts));

  for (const v of [v0, (v0 + v1) / 2, v1]) {
    const gy = y(v);
    out += `<line class="hb-chart__grid" x1="${padL}" x2="${width - padR}" y1="${gy}" y2="${gy}" stroke="var(--hb-hairline)" stroke-width="1"/>`;
    out += `<text x="${padL - 6}" y="${gy}" text-anchor="end" dominant-baseline="middle">${esc(yf(v))}</text>`;
  }
  out += `<text x="${padL}" y="${height - 4}" text-anchor="start">${esc(xf(t0))}</text>`;
  out += `<text x="${width - padR}" y="${height - 4}" text-anchor="end">${esc(xf(t1))}</text>`;

  list.forEach((s, i) => {
    if (s.points.length === 0) return;
    const color = SERIES_COLORS[Math.min(i, SERIES_COLORS.length - 1)];
    const w = i === 0 ? 2 : 1.5;
    if (s.points.length === 1) {
      const p = s.points[0];
      out += `<circle class="hb-chart__dot" cx="${x(p.ts)}" cy="${y(p.value)}" r="3" fill="${color}"/>`;
      return;
    }
    const d = s.points.map((p, j) => `${j === 0 ? 'M' : 'L'}${x(p.ts)},${y(p.value)}`).join(' ');
    out += `<path class="hb-chart__line" d="${d}" fill="none" stroke="${color}" stroke-width="${w}" stroke-linejoin="round" stroke-linecap="round">${s.name ? `<title>${esc(s.name)}</title>` : ''}</path>`;
    if (i === 0) {
      const last = s.points[s.points.length - 1];
      out += `<circle class="hb-chart__dot" cx="${x(last.ts)}" cy="${y(last.value)}" r="3" fill="${color}"/>`;
    }
  });
  return `${out}</svg>`;
}

export function sparklineSvg(values, { width = 120, height = 32, min, max, label } = {}) {
  const vals = (Array.isArray(values) ? values : []).filter(finite);
  let out = open(width, height, label);
  if (vals.length === 0) return `${out}</svg>`;
  const pad = 3;
  const [v0, v1] = extent(vals, min, max, 0.1);
  const n = vals.length;
  const x = (i) => r1(n === 1 ? width / 2 : pad + (i / (n - 1)) * (width - pad * 2));
  const y = (v) => r1(pad + (1 - (v - v0) / (v1 - v0)) * (height - pad * 2));
  if (n > 1) {
    const d = vals.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(v)}`).join(' ');
    out += `<path class="hb-chart__line" d="${d}" fill="none" stroke="var(--hb-accent)" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>`;
  }
  out += `<circle class="hb-chart__dot" cx="${x(n - 1)}" cy="${y(vals[n - 1])}" r="2.5" fill="var(--hb-accent)"/>`;
  return `${out}</svg>`;
}

export function barSvg(items, { width = 300, height = 120, max, yFormat, showValues, label } = {}) {
  const list = (Array.isArray(items) ? items : []).filter((it) => it && finite(it.value));
  let out = open(width, height, label);
  if (list.length === 0) return `${out}</svg>`;
  const values = showValues ?? list.length <= 8;
  const padT = values ? 14 : 4;
  const padB = 16;
  const innerH = Math.max(1, height - padT - padB);
  const top = finite(max) ? max : Math.max(0, ...list.map((it) => it.value));
  const scale = top > 0 ? innerH / top : 0;
  const slot = width / list.length;
  const bw = r1(Math.max(2, Math.min(slot * 0.6, 32)));
  const vf = typeof yFormat === 'function' ? yFormat : (v) => fmt.number(v);
  list.forEach((it, i) => {
    const h = r1(Math.max(0, it.value) * scale);
    const cx = slot * i + slot / 2;
    const bx = r1(cx - bw / 2);
    const by = r1(padT + innerH - h);
    out += `<rect class="hb-chart__bar" x="${bx}" y="${by}" width="${bw}" height="${h}" rx="3" fill="var(--hb-accent)"/>`;
    out += `<text x="${r1(cx)}" y="${height - 4}" text-anchor="middle">${esc(it.label ?? '')}</text>`;
    if (values) out += `<text x="${r1(cx)}" y="${r1(by - 4)}" text-anchor="middle">${esc(vf(it.value))}</text>`;
  });
  return `${out}</svg>`;
}

export function ringSvg(ratio, { size = 96, thickness = 8, label, status } = {}) {
  const value = finite(ratio) ? Math.max(0, Math.min(1, ratio)) : 0;
  const s = Math.max(24, Math.round(size));
  const t = Math.min(thickness, s / 4);
  const rad = (s - t) / 2;
  const c = s / 2;
  const circ = 2 * Math.PI * rad;
  const color = STATUS.has(status) ? `var(--hb-${status})` : 'var(--hb-accent)';
  let out = open(s, s, typeof label === 'string' ? label : undefined);
  out += `<circle class="hb-chart__track" cx="${c}" cy="${c}" r="${r1(rad)}" fill="none" stroke="var(--hb-divider)" stroke-width="${t}"/>`;
  if (value > 0) {
    out += `<circle class="hb-chart__arc" cx="${c}" cy="${c}" r="${r1(rad)}" fill="none" stroke="${color}" stroke-width="${t}" stroke-linecap="round" stroke-dasharray="${r1(circ * value)} ${r1(circ)}" transform="rotate(-90 ${c} ${c})"/>`;
  }
  const text = label ?? fmt.percent(value);
  out += `<text class="hb-chart__center" x="${c}" y="${c}" text-anchor="middle" dominant-baseline="central">${esc(text)}</text>`;
  return `${out}</svg>`;
}

function measure(el, fallbackW, fallbackH) {
  const w = Math.round(el && el.clientWidth) || fallbackW;
  const h = Math.round(el && el.clientHeight) || fallbackH;
  return [w, h];
}

function render(el, svg) {
  if (!el) throw new TypeError('chart: 缺少容器元素');
  el.innerHTML = svg;
  return el.firstElementChild;
}

export function line(el, series, opts = {}) {
  const [width, height] = measure(el, 300, 120);
  return render(el, lineSvg(series, { width, height, ...opts }));
}

export function sparkline(el, values, opts = {}) {
  const [width, height] = measure(el, 120, 32);
  return render(el, sparklineSvg(values, { width, height, ...opts }));
}

export function bar(el, items, opts = {}) {
  const [width, height] = measure(el, 300, 120);
  return render(el, barSvg(items, { width, height, ...opts }));
}

export function ring(el, ratio, opts = {}) {
  const [width, height] = measure(el, 96, 96);
  return render(el, ringSvg(ratio, { size: Math.min(width, height), ...opts }));
}
