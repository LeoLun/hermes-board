// The /hermes-board page (design §5). Optional SDK exports are read from the namespace so an older
// Desktop without them still links (named imports of missing exports fail at module link time).
import * as sdk from '@hermes/plugin-sdk';
import { Button, Codicon, host, useTheme } from '@hermes/plugin-sdk';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { CardFrame } from './card-frame.js';
import { AboutDialog, RunsDialog } from './dialogs.js';
import { boardSize, cellSize, itemRect } from './grid-math.js';
import { useGestures } from './gestures.js';
import { h } from './h.js';
import { API_VERSION } from './api.js';
import { AddCardButton, CardMenu } from './menus.js';
import { BOARD_CSS } from './styles.js';

const DRAG_EXTRA_ROWS = 8;
const icon = (name) => h(Codicon, { name, 'aria-hidden': true });

const noopUnsubscribe = () => {};
function useAtomFallback(atom) {
  const subscribe = useCallback((cb) => (atom && typeof atom.listen === 'function' ? atom.listen(cb) : noopUnsubscribe), [atom]);
  const get = useCallback(() => (atom && typeof atom.get === 'function' ? atom.get() : undefined), [atom]);
  return useSyncExternalStore(subscribe, get, get);
}
const useAtomValue = typeof sdk.useValue === 'function' ? sdk.useValue : useAtomFallback;
const hostState = (host && host.state) || {};

function useResolvedTheme() {
  const t = useTheme() || {};
  return (t.renderedMode || t.resolvedMode) === 'dark' ? 'dark' : 'light';
}

function Center({ title, children, actions }) {
  return h('div', { className: 'hb-center', role: 'status' },
    title ? h('strong', { style: { color: 'var(--ui-text-primary)', fontSize: 15 } }, title) : null,
    children ? h('div', { style: { maxWidth: 460, lineHeight: 1.6 } }, children) : null,
    actions || null);
}

function PhaseView({ st, services }) {
  const retry = h(Button, { size: 'sm', variant: 'outline', onClick: () => services.reloadAll() }, '重试');
  switch (st.phase) {
    case 'not-installed':
      return h('div', { className: 'hb-guide' },
        h('h2', null, '远程 Hermes 上还没有启用看板后端'),
        h('p', null, '看板的数据、卡片和定时任务都保存在当前连接的 Hermes 上。请在那台机器上执行：'),
        h('pre', null, '# 尚未安装时先安装插件\nhermes plugins install <hermes-board 仓库地址>\n\nhermes plugins enable hermes-board\n# 然后重启 hermes serve'),
        h('p', null, '完成后点击“重试”。'),
        retry);
    case 'unauthorized':
      return h(Center, { title: '远程 Hermes 拒绝了访问', actions: retry }, '当前连接的登录状态已失效。请到 Settings → Gateways 重新登录这个连接，然后重试。');
    case 'update-remote':
      return h(Center, { title: '远程的看板后端版本过旧', actions: retry },
        `Desktop 端需要接口版本 ${API_VERSION}，远程返回 ${st.health && st.health.apiVersion != null ? st.health.apiVersion : '未知'}。请在远程更新 hermes-board 插件并重启 hermes serve。`);
    case 'update-desktop':
      return h(Center, { title: '请更新 Desktop 端的看板插件', actions: retry },
        `远程后端的接口版本（${st.health ? st.health.apiVersion : '?'}）比 Desktop 端（${API_VERSION}）新。请在 Capabilities → Plugins 中更新 hermes-board。`);
    case 'disconnected':
      return h(Center, { title: '无法连接到远程 Hermes', actions: retry }, st.error ? st.error.message : '网络连接失败');
    case 'error':
      return h(Center, { title: '看板加载失败', actions: retry }, st.error ? st.error.message : '未知错误');
    default:
      return h(Center, null, '正在加载看板…');
  }
}

function BoardView({ st, theme, scope, services, onMenu }) {
  const scrollRef = useRef(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;
    const measure = () => setWidth(el.clientWidth);
    measure();
    if (typeof ResizeObserver !== 'function') return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const cell = cellSize(width || 1200);
  const cards = useMemo(() => new Map((st.cards || []).map((c) => [c.id, c])), [st.cards]);
  const onCommit = useCallback((op, items) => services.store.commit(op, items), [services]);
  const g = useGestures({ items: st.layout.items, cards, cell, onCommit });
  const items = g.items;
  const gesture = g.gesture;
  const pointer = gesture && gesture.mode !== 'key' && gesture.moved;
  const size = boardSize(items, cell, gesture && gesture.mode !== 'key' ? DRAG_EXTRA_ROWS : 0);
  const onRemove = useCallback((cardId) => services.removeCard(cardId), [services]);

  if (!items.length) {
    return h('div', { className: 'hb-scroll', ref: scrollRef },
      h(Center, { title: '看板上还没有卡片' }, '点击右上角的“添加卡片”，或者在对话中让 Hermes 为你创建一张卡片。'));
  }

  const target = gesture && gesture.target ? itemRect(gesture.target, cell) : null;
  const cursor = gesture && gesture.mode === 'resize' ? (gesture.handle === 'bl' ? 'nesw-resize' : 'nwse-resize') : 'grabbing';
  const showLabel = gesture && (gesture.mode === 'resize' ? gesture.moved : gesture.mode === 'key' && gesture.resized);

  return h('div', { className: 'hb-scroll', ref: scrollRef },
    h('div', {
      className: 'hb-board',
      style: { width: size.width, height: size.height },
      'data-gesture': pointer ? '' : undefined,
    },
    pointer && gesture.mode === 'move' && target ? h('div', { className: 'hb-placeholder', style: target }) : null,
    ...items.map((item) => {
      const card = cards.get(item.card) || null;
      const active = gesture && gesture.id === item.id;
      let r = itemRect(item, cell);
      if (active && gesture.mode === 'move' && gesture.moved) r = { ...r, left: gesture.drag.left, top: gesture.drag.top };
      return h(CardFrame, {
        key: `${item.id}:${card ? card.revision : 0}`,
        item, card, cell, theme, scope, services,
        left: r.left, top: r.top, width: r.width, height: r.height,
        mode: active ? gesture.mode : null,
        handle: active ? gesture.handle : null,
        onStart: g.start, handlers: g.handlers, onKeyDown: g.onKeyDown, onBlur: g.onBlur,
        onMenu, onRemove,
      });
    }),
    pointer ? h('div', { className: 'hb-shield', style: { cursor } }) : null,
    showLabel && target ? h('div', {
      className: 'hb-size-label',
      style: { left: target.left + target.width / 2, top: target.top + target.height / 2 },
    }, gesture.label) : null));
}

export function createBoardPage(services) {
  const { store } = services;
  const HeaderControl = typeof sdk.WorkspacePageHeaderControl === 'function' || typeof sdk.WorkspacePageHeaderControl === 'object'
    ? sdk.WorkspacePageHeaderControl : null;

  function Header({ st }) {
    const controls = h('div', { className: 'hb-header' },
      st.phase === 'ready' && !st.connected ? h('span', { className: 'hb-chip', role: 'status' }, icon('debug-disconnect'), '已断开') : null,
      h(AddCardButton, { cards: st.cards || [], disabled: st.phase !== 'ready', onAdd: (c) => services.addCard(c.id) }),
      h(Button, { size: 'sm', variant: 'ghost', title: '重新加载看板', 'aria-label': '重新加载看板', onClick: () => services.reloadAll() }, icon('refresh')));
    if (HeaderControl) return h(HeaderControl, { id: 'hermes-board.header' }, controls);
    return h('div', { className: 'hb-toolbar' }, h('strong', null, '看板'), controls);
  }

  function ArrangeButton({ disabled }) {
    const [busy, setBusy] = useState(false);
    const run = async () => {
      setBusy(true);
      try {
        await services.arrangeWithUndo();
      } finally {
        setBusy(false);
      }
    };
    return h('button', {
      type: 'button',
      className: 'hb-arrange',
      disabled: disabled || busy,
      title: '自动整理：不改变卡片大小，从左上角开始尽量紧密地排列',
      onClick: run,
    }, icon('layout'), busy ? '整理中…' : '自动整理');
  }

  return function BoardPage() {
    const st = useSyncExternalStore(store.subscribe, store.getState, store.getState);
    const theme = useResolvedTheme();
    const connectionId = useAtomValue(hostState.connectionId);
    const profile = useAtomValue(hostState.profile);
    const scope = `${connectionId == null ? '' : connectionId}|${profile == null ? '' : typeof profile === 'string' ? profile : JSON.stringify(profile)}`;
    const rootRef = useRef(null);
    const [menu, setMenu] = useState(null);
    const [dialog, setDialog] = useState(null);

    useEffect(() => services.attachPage(), []);
    useEffect(() => {
      services.setScope(scope);
    }, [scope]);

    useEffect(() => services.menuBus.on(({ cardId, clientX, clientY }) => {
      const root = rootRef.current;
      if (!root) return;
      const r = root.getBoundingClientRect();
      setMenu({ cardId, x: Math.round(clientX - r.left), y: Math.round(clientY - r.top) });
    }), []);

    const onMenu = useCallback((cardId, clientX, clientY) => services.menuBus.emit({ cardId, clientX, clientY }), []);
    const onAction = useCallback((action, cardId, arg) => {
      if (action === 'reload') services.reloadCard(cardId);
      else if (action === 'run') services.runNow(cardId, arg);
      else if (action === 'runs' || action === 'about') setDialog({ type: action, cardId });
      else if (action === 'remove') services.removeCard(cardId);
    }, []);

    const cardOf = (id) => (st.cards || []).find((c) => c.id === id) || null;
    const ready = st.phase === 'ready' && st.layout;

    return h('div', { className: 'hb-page', ref: rootRef, 'data-theme': theme },
      h('style', null, BOARD_CSS),
      h(Header, { st }),
      ready ? h(BoardView, { st, theme, scope, services, onMenu }) : h('div', { className: 'hb-scroll' }, h(PhaseView, { st, services })),
      ready ? h(ArrangeButton, { disabled: !st.layout.items.length }) : null,
      menu ? h(CardMenu, { menu, card: cardOf(menu.cardId), onClose: () => setMenu(null), onAction }) : null,
      dialog && dialog.type === 'runs' ? h(RunsDialog, { card: cardOf(dialog.cardId), services, onClose: () => setDialog(null) }) : null,
      dialog && dialog.type === 'about' ? h(AboutDialog, { card: cardOf(dialog.cardId), onClose: () => setDialog(null) }) : null);
  };
}
