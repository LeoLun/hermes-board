// hermes-board Desktop entry. Only @hermes/plugin-sdk, react and react/jsx-runtime may be imported at
// runtime; everything else (card runtime, tokens CSS, shared constants) is bundled by esbuild.
import { PALETTE_AREA, ROUTES_AREA, SIDEBAR_NAV_AREA, host } from '@hermes/plugin-sdk';
import { RUNTIME_JS, TOKENS_CSS } from 'virtual:card-runtime';
import { createBoardPage } from './board-page.js';
import { h } from './h.js';
import { BOARD_PATH, createServices } from './services.js';

export default {
  id: 'hermes-board',
  name: '看板',
  defaultEnabled: true,
  register(ctx) {
    const services = createServices({
      rest: (path, opts) => ctx.rest(path, opts),
      setTimeout: (fn, ms) => ctx.setTimeout(fn, ms),
      onEvent: typeof ctx.onEvent === 'function' ? (type, listener) => ctx.onEvent(type, listener) : undefined,
      notify: (input) => host.notify(input),
      os: ctx.os || {},
      runtimeJs: RUNTIME_JS,
      tokensCss: TOKENS_CSS,
      log: (...args) => console.warn(...args),
    });
    const BoardPage = createBoardPage(services);
    const open = () => host.navigate(BOARD_PATH);

    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: BOARD_PATH }, render: () => h(BoardPage, {}) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, order: 45, data: { path: BOARD_PATH, label: '看板', codicon: 'dashboard' } },
      {
        id: 'open', area: PALETTE_AREA,
        data: { id: 'hermes-board.open', label: '打开看板', keywords: ['board', 'dashboard', '看板', '卡片'], run: open },
      },
      {
        id: 'arrange', area: PALETTE_AREA,
        data: {
          id: 'hermes-board.arrange', label: '看板：自动整理', keywords: ['arrange', 'compact', '整理', '排列'],
          run: () => {
            open();
            services.arrangeWithUndo();
          },
        },
      },
      {
        id: 'reload', area: PALETTE_AREA,
        data: {
          id: 'hermes-board.reload', label: '看板：重新加载', keywords: ['reload', 'refresh', '刷新', '重新加载'],
          run: () => {
            open();
            services.reloadAll();
          },
        },
      },
    ]);
    if (typeof ctx.onDispose === 'function') ctx.onDispose(() => services.dispose());
  },
};
