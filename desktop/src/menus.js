// Host-side card menu (right click on a card) and the "添加卡片" picker.
import { useState } from 'react';
import {
  Button, Codicon, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
  Popover, PopoverContent, PopoverTrigger,
} from '@hermes/plugin-sdk';
import { cardProblem, fmtSize } from './format.js';
import { h } from './h.js';

const icon = (name) => h(Codicon, { name, 'aria-hidden': true });

/**
 * @param {{cardId: string, x: number, y: number} | null} props.menu  page-relative anchor
 * @param {(action: 'reload'|'run'|'runs'|'about'|'remove', arg?: string) => void} props.onAction
 */
export function CardMenu({ menu, card, onClose, onAction }) {
  if (!menu) return null;
  const scripts = (card && card.status === 'ok' && card.scripts) || [];
  const select = (action, arg) => () => {
    onClose();
    onAction(action, menu.cardId, arg);
  };
  return h(DropdownMenu, {
    key: `${menu.cardId}:${menu.x}:${menu.y}`,
    open: true,
    onOpenChange: (open) => {
      if (!open) onClose();
    },
  },
  h(DropdownMenuTrigger, { asChild: true },
    h('button', { type: 'button', tabIndex: -1, 'aria-hidden': true, className: 'hb-menu-anchor', style: { left: menu.x, top: menu.y } })),
  h(DropdownMenuContent, { align: 'start', side: 'bottom', sideOffset: 2, style: { minWidth: 200 } },
    h(DropdownMenuItem, { onSelect: select('reload') }, icon('refresh'), '刷新'),
    ...scripts.map((s) => h(DropdownMenuItem, { key: `run:${s.name}`, onSelect: select('run', s.name) }, icon('play'), `立即运行 ${s.name}`)),
    h(DropdownMenuItem, { onSelect: select('runs'), disabled: !scripts.length && !(card && card.ai && card.ai.length) }, icon('history'), '最近运行'),
    h(DropdownMenuItem, { onSelect: select('about') }, icon('info'), '关于此卡片'),
    h(DropdownMenuSeparator, null),
    h(DropdownMenuItem, { onSelect: select('remove') }, icon('close'), '从看板移除')));
}

export function AddCardButton({ cards, onAdd, disabled }) {
  const [open, setOpen] = useState(false);
  const available = cards.filter((c) => !c.onBoard);
  const body = available.length
    ? h('div', { className: 'hb-picker', role: 'list' }, available.map((c) => h('button', {
      key: c.id,
      type: 'button',
      role: 'listitem',
      disabled: c.status !== 'ok',
      onClick: () => {
        setOpen(false);
        onAdd(c);
      },
    },
    h('span', { className: 'hb-picker-title' }, c.title || c.id),
    h('small', null, c.status === 'ok'
      ? `${c.description ? `${c.description} · ` : ''}默认 ${fmtSize(c.defaultSize)}`
      : cardProblem(c)))))
    : h('div', { className: 'hb-picker-empty' },
      '所有已安装的卡片都已经在看板上了。在对话中告诉 Hermes 你想要的卡片，例如“做一张显示本机 CPU 和内存占用的卡片”。');
  return h(Popover, { open, onOpenChange: setOpen },
    h(PopoverTrigger, { asChild: true },
      h(Button, { size: 'sm', variant: 'ghost', disabled, title: '添加卡片' }, icon('add'), '添加卡片')),
    h(PopoverContent, { align: 'end', sideOffset: 6, style: { width: 300, padding: 6 } }, body));
}
