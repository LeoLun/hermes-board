// Application-modal fullscreen presentation for one card. It mounts an isolated card host while
// leaving the board instance and persisted grid geometry untouched.
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@hermes/plugin-sdk';
import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { CardFrame } from './card-frame.js';
import { fullscreenEnv } from './fullscreen-env.js';
import { h } from './h.js';

export function FullscreenCardDialog({ card, theme, scope, services, onClose }) {
  const stageRef = useRef(null);
  const [pixel, setPixel] = useState({ width: 1, height: 1 });

  useLayoutEffect(() => {
    const el = stageRef.current;
    if (!el) return undefined;
    const measure = () => {
      const next = fullscreenEnv(el.clientWidth, el.clientHeight).pixel;
      setPixel((current) => current.width === next.width && current.height === next.height ? current : next);
    };
    measure();
    if (typeof ResizeObserver !== 'function') return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const env = fullscreenEnv(pixel.width, pixel.height);
  const item = useMemo(() => ({ id: card.id, card: card.id, x: 0, y: 0, w: 24, h: 16 }), [card.id]);
  const title = card.title || card.id;

  return h(Dialog, { open: true, onOpenChange: (open) => { if (!open) onClose(); } },
    h(DialogContent, { className: 'hb-fullscreen-dialog' },
      h(DialogHeader, { className: 'hb-fullscreen-header' },
        h(DialogTitle, null, title),
        h(DialogDescription, null, '全屏查看卡片；关闭后看板布局保持不变。')),
      h('div', { className: 'hb-fullscreen-stage', ref: stageRef },
        h(CardFrame, {
          key: `fullscreen:${card.id}:${card.revision || 0}`,
          item, card, cell: 1, theme, scope, services,
          left: 0, top: 0, width: '100%', height: '100%',
          envSize: env.size, pixel: env.pixel, presentation: true, registerFrame: false,
        }))));
}
