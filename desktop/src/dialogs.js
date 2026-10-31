// "最近运行" and "关于此卡片" dialogs.
import { useEffect, useState } from 'react';
import { Button, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@hermes/plugin-sdk';
import { RUN_STATUS, RUN_TRIGGER, cronText, errorSummary, fmtDuration, fmtSize, fmtTime } from './format.js';
import { h } from './h.js';

const PER_GROUP = 6;

function RunRow({ run }) {
  const problem = run.status === 'failed' || run.status === 'timeout' ? errorSummary(run) : '';
  return h('div', { className: 'hb-run' },
    h('span', { className: 'hb-status', 'data-s': run.status }, RUN_STATUS[run.status] || run.status),
    h('small', null, `${fmtTime(run.createdAt)} · ${RUN_TRIGGER[run.trigger] || run.trigger}`),
    h('small', null, fmtDuration(run)),
    problem ? h('code', null, problem) : null);
}

function Group({ title, subtitle, runs, onRun, running }) {
  return h('section', null,
    h('header', null,
      h('strong', null, title),
      subtitle ? h('span', { className: 'hb-muted' }, subtitle) : null,
      onRun ? h(Button, { size: 'sm', variant: 'outline', disabled: running, onClick: onRun }, running ? '运行中…' : '立即运行') : null),
    runs.length ? runs.map((r) => h(RunRow, { key: r.runId, run: r })) : h('span', { className: 'hb-muted' }, '还没有运行记录'));
}

export function RunsDialog({ card, onClose, services }) {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState(null);
  const cardId = card ? card.id : null;

  useEffect(() => {
    if (!cardId) return undefined;
    let alive = true;
    const load = () => services.api.listRuns(cardId, 50).then(
      (list) => {
        if (alive) {
          setRuns(list);
          setError(null);
        }
      },
      (err) => {
        if (alive) setError(err);
      },
    );
    load();
    const off = services.hub.subscribeCard(cardId, ({ topics, reset }) => {
      if (reset || topics.includes('run:*')) load();
    });
    return () => {
      alive = false;
      off();
    };
  }, [cardId, services]);

  if (!card) return null;
  const list = runs || [];
  const active = (name) => list.some((r) => r.kind === 'script' && r.name === name && (r.status === 'queued' || r.status === 'running'));
  const groups = (card.scripts || []).map((s) => h(Group, {
    key: `s:${s.name}`,
    title: s.name,
    subtitle: cronText(s),
    runs: list.filter((r) => r.kind === 'script' && r.name === s.name).slice(0, PER_GROUP),
    running: active(s.name),
    onRun: () => services.runNow(card.id, s.name),
  }));
  const aiRuns = list.filter((r) => r.kind === 'ai');
  if (aiRuns.length || (card.ai && card.ai.length)) {
    groups.push(h(Group, { key: 'ai', title: 'AI 任务', subtitle: (card.ai || []).join('、'), runs: aiRuns.slice(0, PER_GROUP) }));
  }
  return h(Dialog, { open: true, onOpenChange: (open) => { if (!open) onClose(); } },
    h(DialogContent, { style: { maxWidth: 560 } },
      h(DialogHeader, null,
        h(DialogTitle, null, `最近运行 · ${card.title || card.id}`),
        h(DialogDescription, null, '定时任务、卡片操作和 Agent 触发的运行都会记录在这里，失败时显示错误摘要。')),
      error ? h('div', { className: 'hb-muted', role: 'alert' }, `读取运行记录失败：${error.message}`) : null,
      runs === null && !error ? h('div', { className: 'hb-muted' }, '正在读取…') : null,
      runs !== null ? h('div', { className: 'hb-runs' }, ...groups) : null));
}

function nextRun(cron) {
  if (!cron || !cron.nextRunAt) return '';
  const t = typeof cron.nextRunAt === 'number' ? cron.nextRunAt : Date.parse(cron.nextRunAt);
  return Number.isFinite(t) ? ` · 下次 ${fmtTime(t)}` : '';
}

export function AboutDialog({ card, onClose }) {
  if (!card) return null;
  const rows = [
    ['名称', card.title || card.id],
    ['ID', card.id],
    ['版本', `${card.version || '—'} · 第 ${card.revision || 1} 次保存`],
    ['说明', card.description || '—'],
    ['尺寸', (card.sizes || []).map(fmtSize).join('、') || '—'],
    ['脚本', (card.scripts || []).length
      ? (card.scripts || []).map((s) => `${s.name}：${cronText(s)}${s.schedule ? nextRun(s.cron) : ''}${s.callable ? ' · 可从卡片调用' : ''}`).join('\n')
      : '无'],
    ['AI 任务', (card.ai || []).join('、') || '无'],
    ['来源', card.source || '—'],
    ['位置', `远程 HERMES_HOME 下\nplugin-data/hermes-board/cards/${card.id}/\nscripts/hermes-board/${card.id}/（数据脚本）`],
    ['状态', card.status === 'ok' ? '正常' : (card.errors || []).map((e) => (typeof e === 'string' ? e : e.message)).join('\n') || '不合法'],
  ];
  return h(Dialog, { open: true, onOpenChange: (open) => { if (!open) onClose(); } },
    h(DialogContent, { style: { maxWidth: 520 } },
      h(DialogHeader, null, h(DialogTitle, null, '关于此卡片'), h(DialogDescription, null, '卡片包和数据保存在远程 Hermes 上。')),
      h('dl', { className: 'hb-about' }, ...rows.flatMap(([k, v]) => [
        h('dt', { key: `k:${k}` }, k),
        h('dd', { key: `v:${k}`, style: { whiteSpace: 'pre-line' } }, v),
      ]))));
}
