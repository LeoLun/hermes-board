import { test } from 'node:test';
import assert from 'node:assert/strict';
import fmt from '../src/fmt.js';
import { barSvg, lineSvg, normalizeSeries, ringSvg, sparklineSvg } from '../src/chart.js';

test('fmt examples from runtime-api.md', () => {
  assert.equal(fmt.number(1234.5, 1), '1,234.5');
  assert.equal(fmt.percent(0.423, 1), '42.3%');
  assert.equal(fmt.bytes(1536000), '1.5 MB');
  assert.equal(fmt.duration(3723000), '1 小时 2 分');
  const now = new Date(2026, 9, 31, 14, 32).getTime();
  assert.equal(fmt.relative(now - 90000, now), '1 分钟前');
  assert.equal(fmt.time(now), '14:32');
  assert.equal(fmt.date(now, now), '10月31日');
});

test('fmt edge cases', () => {
  for (const fn of [fmt.number, fmt.percent, fmt.bytes, fmt.duration, fmt.time, fmt.relative]) {
    assert.equal(fn(NaN), '—');
    assert.equal(fn(undefined), '—');
  }
  assert.equal(fmt.number(2, 2), '2.00');
  assert.equal(fmt.number(1234567.891), '1,234,567.89');
  assert.equal(fmt.bytes(512), '512 B');
  assert.equal(fmt.bytes(10 * 1024 * 1024 * 1024), '10 GB');
  assert.equal(fmt.duration(45000), '45 秒');
  assert.equal(fmt.duration(125000), '2 分 5 秒');
  assert.equal(fmt.duration(3600000), '1 小时');
  assert.equal(fmt.duration(90000000), '1 天 1 小时');
  const now = new Date(2026, 9, 31, 14, 32).getTime();
  assert.equal(fmt.relative(now - 10000, now), '刚刚');
  assert.equal(fmt.relative(now + 5 * 60000, now), '5 分钟后');
  assert.equal(fmt.relative(now - 3 * 3600000, now), '3 小时前');
  assert.equal(fmt.relative(now - 2 * 86400000, now), '2 天前');
  assert.equal(fmt.relative(now - 30 * 86400000, now), '10月1日');
  assert.equal(fmt.date(new Date(2025, 0, 2).getTime(), now), '2025年1月2日');
  assert.equal(fmt.updated(now - 60000, now), '更新于 14:31');
  assert.equal(fmt.updated(new Date(2026, 9, 30, 9, 5).getTime(), now), '更新于 10月30日 09:05');
  assert.equal(fmt.updated(null, now), '');
});

const COLOR_LITERAL = /#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i;

function count(svg, tag) {
  return (svg.match(new RegExp(`<${tag}[\\s>]`, 'g')) || []).length;
}

test('line chart structure', () => {
  const t = Date.UTC(2026, 9, 1);
  const series = [
    { name: '支出', points: [{ ts: t, value: 10 }, { ts: t + 86400000 * 30, value: 30 }, { ts: t + 86400000 * 60, value: 20 }] },
    { name: '收入', points: [{ ts: t, value: 5 }, { ts: t + 86400000 * 60, value: 8 }] },
  ];
  const svg = lineSvg(series, { width: 320, height: 140, label: '月支出' });
  assert.match(svg, /^<svg class="hb-chart"[^>]*viewBox="0 0 320 140"/);
  assert.match(svg, /aria-label="月支出"/);
  assert.equal(count(svg, 'path'), 2);
  assert.match(svg, /stroke="var\(--hb-accent\)" stroke-width="2"/);
  assert.match(svg, /stroke="var\(--hb-ink-2\)" stroke-width="1.5"/);
  assert.equal(count(svg, 'line'), 3, 'three grid lines');
  assert.doesNotMatch(svg, COLOR_LITERAL);
  assert.match(svg, /10月1日/, 'long spans use date labels');
  assert.ok(svg.endsWith('</svg>'));
});

test('line chart accepts a bare point array, escapes text and handles empty input', () => {
  const svg = lineSvg([{ ts: 1, value: 1 }, { ts: 2, value: 2 }], { yFormat: (v) => `<${v}>` });
  assert.equal(count(svg, 'path'), 1);
  assert.match(svg, /&lt;1\.5&gt;/);
  assert.doesNotMatch(svg, /<1\.5>/);
  assert.doesNotMatch(svg, /<title>/, 'unnamed series has no title');
  assert.equal(lineSvg([]), '<svg class="hb-chart" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 120" width="300" height="120" role="img"></svg>');
  const single = lineSvg([{ ts: 5, value: 3 }]);
  assert.equal(count(single, 'path'), 0);
  assert.equal(count(single, 'circle'), 1);
  assert.deepEqual(normalizeSeries([{ ts: 2, value: 1 }, { ts: 1, value: NaN }, { ts: 0, value: 4 }])[0].points.map((p) => p.ts), [0, 2]);
});

test('line chart respects explicit min/max', () => {
  const svg = lineSvg([{ ts: 0, value: 50 }, { ts: 10, value: 50 }], { width: 200, height: 100, min: 0, max: 100 });
  const d = svg.match(/d="([^"]+)"/)[1];
  const ys = d.split(' ').map((seg) => Number(seg.split(',')[1]));
  assert.deepEqual(ys, [ys[0], ys[0]]);
  assert.ok(ys[0] > 40 && ys[0] < 60, `midpoint near center, got ${ys[0]}`);
});

test('sparkline', () => {
  const svg = sparklineSvg([1, 3, 2, 5], { width: 100, height: 30 });
  assert.equal(count(svg, 'path'), 1);
  assert.equal(count(svg, 'circle'), 1);
  assert.equal(count(svg, 'text'), 0, 'no axes');
  assert.doesNotMatch(svg, COLOR_LITERAL);
  assert.equal(count(sparklineSvg([], {}), 'path'), 0);
  assert.equal(count(sparklineSvg([7]), 'circle'), 1);
});

test('bar chart', () => {
  const svg = barSvg([{ label: '1月', value: 10 }, { label: '2月', value: 20 }, { label: '3月', value: 0 }], { width: 300, height: 120 });
  assert.equal(count(svg, 'rect'), 3);
  assert.match(svg, /fill="var\(--hb-accent\)"/);
  assert.match(svg, />2月</);
  assert.match(svg, />20</, 'values shown for small sets');
  const heights = [...svg.matchAll(/<rect[^>]*height="([\d.]+)"/g)].map((m) => Number(m[1]));
  assert.ok(Math.abs(heights[1] - heights[0] * 2) < 0.2);
  assert.equal(heights[2], 0);
  assert.doesNotMatch(svg, COLOR_LITERAL);
});

test('ring chart', () => {
  const svg = ringSvg(0.25, { size: 100, thickness: 10 });
  const circ = 2 * Math.PI * 45;
  const dash = svg.match(/stroke-dasharray="([\d.]+) ([\d.]+)"/);
  assert.ok(Math.abs(Number(dash[1]) - circ * 0.25) < 0.1);
  assert.ok(Math.abs(Number(dash[2]) - circ) < 0.1);
  assert.match(svg, />25%</);
  assert.match(svg, /stroke="var\(--hb-accent\)"/);
  assert.match(ringSvg(0.9, { status: 'critical' }), /stroke="var\(--hb-critical\)"/);
  assert.match(ringSvg(0.9, { status: 'bogus' }), /stroke="var\(--hb-accent\)"/);
  assert.equal(count(ringSvg(0), 'circle'), 1, 'no arc at zero');
  assert.match(ringSvg(2, { label: '满' }), />满</);
  assert.doesNotMatch(svg, COLOR_LITERAL);
});
