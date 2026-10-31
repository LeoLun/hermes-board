// One card on the board: SandboxedFrame + host overlay (grip, corner handles, state layers).
import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { Button, SandboxedFrame } from '@hermes/plugin-sdk';
import { createCardHost } from './card-host.js';
import { cardProblem } from './format.js';
import { pixelSize } from './grid-math.js';
import { h } from './h.js';
import { allowedSizes, sizeLabel } from './layout-ops.js';

const ARCS = { br: 'M 21 6 A 15 15 0 0 1 6 21', bl: 'M 3 6 A 15 15 0 0 0 18 21' };
const FRAME_STYLE = { position: 'absolute', inset: 0, width: '100%', height: '100%', border: 0, display: 'block', background: 'transparent' };

function arc(handle) {
  return h('svg', { viewBox: '0 0 24 24', width: 24, height: 24 }, h('path', { d: ARCS[handle] }));
}

const sizeEnv = (item) => ({ w: item.w, h: item.h, label: sizeLabel(item.w, item.h) });

function CardFrameImpl(props) {
  const { item, card, cell, theme, scope, services, mode, handle } = props;
  const wrapperRef = useRef(null);
  const [snap, setSnap] = useState(null);
  const [docTick, setDocTick] = useState(0);
  const title = (card && card.title) || item.card;

  const [host] = useState(() => createCardHost({
    card: { id: item.card, title, version: (card && card.version) || '0.0.0' },
    env: { size: sizeEnv(item), pixel: pixelSize(item.w, item.h, cell), theme, visible: true },
    runtimeJs: services.runtimeJs,
    tokensCss: services.tokensCss,
    api: services.api,
    ui: services.cardUi(item.card),
    onChange: setSnap,
    setTimer: (fn, ms) => window.setTimeout(fn, ms),
    clearTimer: (id) => window.clearTimeout(id),
    log: services.log,
  }));

  const reload = useCallback(() => {
    setDocTick((t) => t + 1);
    host.retry();
  }, [host]);

  useEffect(() => () => host.dispose(), [host]);

  useEffect(() => {
    const onMessage = (event) => host.handleMessage(event);
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [host]);

  const status = card ? card.status : 'missing';
  useEffect(() => {
    let cancelled = false;
    if (status !== 'ok') {
      host.fail(cardProblem(card));
      return undefined;
    }
    services.docCache.load(services.api, scope, item.card).then(
      (doc) => {
        if (!cancelled) host.setHtml(doc.html);
      },
      (err) => {
        if (!cancelled) host.fail(`加载卡片失败：${err.message}`);
      },
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [host, scope, item.card, status, docTick]);

  useEffect(() => services.hub.subscribeCard(item.card, ({ topics, cardChanged, reset }) => {
    if (cardChanged) setDocTick((t) => t + 1);
    const send = reset ? (host.bridge ? host.bridge.topics : []) : topics;
    if (send.length) host.notifyTopics(send);
  }), [host, item.card, services]);

  useEffect(() => {
    host.setEnv({ theme });
  }, [host, theme]);

  const px = pixelSize(item.w, item.h, cell);
  useEffect(() => {
    host.setEnv({ size: sizeEnv(item), pixel: px });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [host, item.w, item.h, px.width, px.height]);

  useEffect(() => {
    const el = wrapperRef.current;
    if (!el) return undefined;
    let inView = true;
    const update = () => host.setEnv({ visible: inView && document.visibilityState !== 'hidden' });
    const io = typeof IntersectionObserver === 'function'
      ? new IntersectionObserver((entries) => {
        inView = entries.some((e) => e.isIntersecting);
        update();
      })
      : null;
    if (io) io.observe(el);
    document.addEventListener('visibilitychange', update);
    return () => {
      if (io) io.disconnect();
      document.removeEventListener('visibilitychange', update);
    };
  }, [host]);

  useEffect(() => services.registerFrame(item.card, { element: wrapperRef.current, reload }), [services, item.card, reload]);

  const frameRef = useCallback((el) => host.setFrameWindow(el ? el.contentWindow : null), [host]);
  const onLoad = useCallback(() => host.handleLoad(), [host]);

  const resizable = !!card && allowedSizes(card.sizes).length > 1;
  const st = snap ? snap.status : 'idle';
  const failed = st === 'timeout' || st === 'error';

  return h('div', {
    ref: wrapperRef,
    className: 'hb-card',
    style: { left: props.left, top: props.top, width: props.width, height: props.height },
    'data-card': item.card,
    'data-status': st,
    'data-active': mode ? '' : undefined,
    'data-mode': mode || undefined,
    'data-handle': handle || undefined,
    onContextMenu: (e) => {
      e.preventDefault();
      props.onMenu(item.card, e.clientX, e.clientY);
    },
  },
  snap && snap.src ? h(SandboxedFrame, { key: snap.key, src: snap.src, title, ref: frameRef, onLoad, style: FRAME_STYLE }) : null,
  !failed && st !== 'ready' ? h('div', { className: 'hb-card-loading', 'aria-hidden': 'true' }) : null,
  failed ? h('div', { className: 'hb-card-state', role: 'alert' },
    h('strong', null, st === 'timeout' ? '卡片加载失败' : '卡片不可用'),
    h('span', null, snap.error),
    h('div', { className: 'hb-actions' },
      status === 'ok' ? h(Button, { size: 'sm', variant: 'outline', onClick: reload }, '重试') : null,
      h(Button, { size: 'sm', variant: 'ghost', onClick: () => props.onRemove(item.card) }, '从看板移除'))) : null,
  st === 'ready' && snap.scriptError ? h('div', { className: 'hb-card-badge', role: 'status' },
    h('span', { title: snap.scriptError }, `卡片出错：${snap.scriptError}`),
    h('button', { type: 'button', className: 'hb-linkbtn', onClick: reload }, '重新加载')) : null,
  h('button', {
    type: 'button',
    className: 'hb-grip-zone',
    'aria-label': `移动「${title}」：方向键移动，Shift+方向键切换尺寸，Enter 确认，Esc 取消`,
    onPointerDown: (e) => props.onStart(e, item, 'move'),
    onKeyDown: (e) => props.onKeyDown(e, item),
    onBlur: () => props.onBlur(item),
    ...props.handlers,
  }, h('span', { className: 'hb-grip' })),
  resizable ? h('div', {
    className: 'hb-corner', 'data-handle': 'bl', 'aria-hidden': 'true',
    onPointerDown: (e) => props.onStart(e, item, 'resize', 'bl'), ...props.handlers,
  }, arc('bl')) : null,
  resizable ? h('div', {
    className: 'hb-corner', 'data-handle': 'br', 'aria-hidden': 'true',
    onPointerDown: (e) => props.onStart(e, item, 'resize', 'br'), ...props.handlers,
  }, arc('br')) : null);
}

export const CardFrame = memo(CardFrameImpl);
