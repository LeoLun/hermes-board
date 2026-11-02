// Board chrome CSS, rendered once by the page as a <style> element. Only Hermes theme variables are used
// (the plugin cannot rely on Tailwind classes being compiled into the app).
import { RADIUS } from './grid-math.js';

const surface = 'var(--ui-bg-card, var(--ui-bg-elevated, #fff))';

export const BOARD_CSS = `
.hb-page { position: relative; height: 100%; min-height: 0; display: flex; flex-direction: column;
  color: var(--ui-text-primary); background: var(--ui-bg-editor, transparent); }
.hb-scroll { position: relative; flex: 1; min-height: 0; overflow: auto; scrollbar-gutter: stable; }
.hb-board { position: relative; margin: 0 auto; }
.hb-card { position: absolute; box-sizing: border-box; border-radius: ${RADIUS}px; overflow: hidden; background: ${surface};
  box-shadow: 0 0 0 1px var(--ui-stroke-tertiary, rgba(0,0,0,.08));
  transition: left .2s ease, top .2s ease, width .2s ease, height .2s ease, box-shadow .15s ease; }
.hb-card[data-active] { transition: box-shadow .15s ease; z-index: 6;
  box-shadow: 0 14px 36px rgba(0,0,0,.18), 0 0 0 1px var(--ui-stroke-secondary, rgba(0,0,0,.16)); }
.hb-card[data-active][data-mode=resize] { transition: left .12s ease, top .12s ease, width .12s ease, height .12s ease, box-shadow .15s ease; }
.hb-board[data-arranging] .hb-card { transition: none; }
.hb-card > iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; display: block; background: transparent; }
.hb-board[data-gesture] iframe { pointer-events: none; }
.hb-grip-zone { position: absolute; top: 0; left: 50%; transform: translateX(-50%); width: 76px; height: 18px; z-index: 4;
  margin: 0; padding: 6px 0 0; border: 0; background: transparent; cursor: grab; display: flex; justify-content: center;
  outline: none; border-radius: 0 0 10px 10px; }
.hb-grip { width: 36px; height: 5px; border-radius: 3px; background: var(--ui-text-quaternary, rgba(0,0,0,.3));
  opacity: 0; transition: opacity .12s ease, background .12s ease; pointer-events: none; }
.hb-grip-zone:hover .hb-grip, .hb-grip-zone:focus-visible .hb-grip, .hb-card[data-active] .hb-grip { opacity: 1; }
.hb-grip-zone:hover .hb-grip, .hb-card[data-mode=move] .hb-grip { background: var(--ui-text-tertiary, rgba(0,0,0,.45)); }
.hb-grip-zone:focus-visible { box-shadow: inset 0 0 0 2px var(--ui-accent); }
.hb-card[data-mode=move] .hb-grip-zone { cursor: grabbing; }
.hb-corner { position: absolute; bottom: 0; width: 24px; height: 24px; z-index: 4; touch-action: none; }
.hb-corner[data-handle=bl] { left: 0; cursor: nesw-resize; }
.hb-corner[data-handle=br] { right: 0; cursor: nwse-resize; }
.hb-corner svg { position: absolute; inset: 0; opacity: 0; transition: opacity .12s ease; pointer-events: none; }
.hb-corner path { fill: none; stroke: var(--ui-accent, #0071e3); stroke-width: 3; stroke-linecap: round; }
.hb-corner:hover svg, .hb-card[data-handle=bl] .hb-corner[data-handle=bl] svg,
.hb-card[data-handle=br] .hb-corner[data-handle=br] svg { opacity: 1; }
.hb-expand { position: absolute; top: 10px; right: 10px; z-index: 5; width: 30px; height: 30px; margin: 0; padding: 0;
  display: grid; place-items: center; border: 1px solid var(--ui-stroke-tertiary, rgba(0,0,0,.08)); border-radius: 9px;
  background: color-mix(in srgb, var(--ui-bg-elevated, #fff) 88%, transparent); color: var(--ui-text-primary);
  box-shadow: 0 2px 8px rgba(0,0,0,.1); cursor: pointer; opacity: 1; transition: background .12s ease; }
.hb-expand:hover { background: var(--ui-control-hover-background, var(--ui-bg-secondary)); }
.hb-expand:focus-visible { outline: 2px solid var(--ui-accent); outline-offset: 2px; }
.hb-fullscreen-dialog { width: calc(100vw - 64px); max-width: none; height: calc(100vh - 64px); max-height: none;
  display: flex; flex-direction: column; gap: 12px; padding: 20px; box-sizing: border-box; }
.hb-fullscreen-header { flex: none; padding-right: 36px; }
.hb-fullscreen-stage { position: relative; flex: 1; min-width: 0; min-height: 0; overflow: hidden; border-radius: ${RADIUS}px; }
.hb-fullscreen-stage .hb-card { border-radius: ${RADIUS}px; }
.hb-shield { position: absolute; inset: 0; z-index: 20; }
.hb-placeholder { position: absolute; box-sizing: border-box; border-radius: ${RADIUS}px; z-index: 1; pointer-events: none;
  border: 2px dashed var(--ui-stroke-secondary, rgba(0,0,0,.2)); background: var(--ui-selection-background, rgba(0,113,227,.08));
  transition: left .12s ease, top .12s ease, width .12s ease, height .12s ease; }
.hb-size-label { position: absolute; z-index: 21; transform: translate(-50%, -50%); padding: 3px 10px; border-radius: 999px;
  background: var(--ui-bg-elevated, #fff); color: var(--ui-text-primary); font: 600 12px/18px system-ui, sans-serif;
  box-shadow: 0 2px 8px rgba(0,0,0,.16), 0 0 0 1px var(--ui-stroke-tertiary, rgba(0,0,0,.08)); pointer-events: none;
  font-variant-numeric: tabular-nums; }
.hb-card-state { position: absolute; inset: 0; z-index: 2; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 8px; padding: 16px; box-sizing: border-box; text-align: center; background: ${surface};
  color: var(--ui-text-tertiary); font-size: 12px; line-height: 1.5; }
.hb-card-state strong { color: var(--ui-text-primary); font-size: 13px; font-weight: 600; }
.hb-card-state .hb-actions { display: flex; gap: 6px; flex-wrap: wrap; justify-content: center; }
.hb-card-loading { position: absolute; inset: 0; z-index: 1; background: ${surface}; pointer-events: none; }
.hb-card-loading::after { content: ''; position: absolute; left: 16px; right: 40%; top: 18px; height: 10px; border-radius: 5px;
  background: var(--ui-bg-tertiary, rgba(0,0,0,.06)); }
.hb-card-badge { position: absolute; left: 8px; right: 8px; bottom: 8px; z-index: 3; display: flex; align-items: center; gap: 8px;
  padding: 4px 8px 4px 10px; border-radius: 10px; font-size: 11px; line-height: 18px;
  background: color-mix(in srgb, var(--ui-red, #d70015) 12%, var(--ui-bg-elevated, #fff)); color: var(--ui-red, #d70015); }
.hb-card-badge span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hb-linkbtn { border: 0; background: transparent; color: inherit; font: inherit; font-weight: 600; cursor: pointer; padding: 0 2px; }
.hb-linkbtn:hover { text-decoration: underline; }
.hb-floating-actions { position: absolute; right: 20px; bottom: 20px; z-index: 30; display: flex; align-items: center; gap: 4px;
  padding: 3px; border: 1px solid var(--ui-stroke-tertiary, rgba(0,0,0,.08)); border-radius: 12px;
  background: var(--ui-bg-elevated, #fff); box-shadow: 0 6px 18px rgba(0,0,0,.12); }
.hb-arrange { display: inline-flex; align-items: center; gap: 6px;
  height: 36px; padding: 0 14px; border-radius: 18px; border: 1px solid var(--ui-stroke-tertiary, rgba(0,0,0,.08));
  background: transparent; color: var(--ui-text-primary); font: 600 12px/1 system-ui, sans-serif; cursor: pointer; }
.hb-arrange:hover { background: var(--ui-control-hover-background, var(--ui-bg-secondary)); }
.hb-arrange:disabled { opacity: .55; cursor: default; }
.hb-arrange:focus-visible { outline: 2px solid var(--ui-accent); outline-offset: 2px; }
.hb-center { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; min-height: 60%;
  padding: 48px 24px; text-align: center; color: var(--ui-text-secondary); font-size: 13px; }
.hb-guide { max-width: 560px; margin: 0 auto; padding: 56px 24px; color: var(--ui-text-secondary); font-size: 13px; line-height: 1.6; }
.hb-guide h2 { margin: 0 0 8px; color: var(--ui-text-primary); font-size: 18px; font-weight: 600; }
.hb-guide pre { margin: 12px 0; padding: 12px 14px; border-radius: 8px; background: var(--ui-bg-secondary, rgba(0,0,0,.04));
  color: var(--ui-text-primary); font: 12px/1.7 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; user-select: text; }
.hb-menu-anchor { position: absolute; width: 1px; height: 1px; padding: 0; border: 0; opacity: 0; pointer-events: none; }
.hb-picker { display: flex; flex-direction: column; gap: 2px; max-height: 360px; overflow: auto; }
.hb-picker button { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; width: 100%; padding: 8px 10px;
  border: 0; border-radius: 6px; background: transparent; color: var(--ui-text-primary); text-align: left; cursor: pointer; font: inherit; }
.hb-picker button:hover:not(:disabled), .hb-picker button:focus-visible { background: var(--ui-row-hover-background, rgba(0,0,0,.05)); outline: none; }
.hb-picker button:disabled { cursor: default; opacity: .6; }
.hb-picker small { color: var(--ui-text-tertiary); font-size: 11px; }
.hb-picker .hb-picker-title { font-size: 12px; font-weight: 600; }
.hb-picker-empty { padding: 10px; color: var(--ui-text-tertiary); font-size: 12px; line-height: 1.6; }
.hb-runs { display: flex; flex-direction: column; gap: 14px; max-height: 60vh; overflow: auto; font-size: 12px; }
.hb-runs section { display: flex; flex-direction: column; gap: 6px; }
.hb-runs header { display: flex; align-items: center; gap: 8px; }
.hb-runs header strong { flex: 1; font-size: 13px; }
.hb-run { display: grid; grid-template-columns: 64px 1fr auto; gap: 4px 10px; padding: 6px 8px; border-radius: 6px;
  background: var(--ui-bg-secondary, rgba(0,0,0,.03)); }
.hb-run code { grid-column: 1 / -1; white-space: pre-wrap; word-break: break-all; color: var(--ui-text-tertiary);
  font: 11px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; max-height: 88px; overflow: auto; }
.hb-run small { color: var(--ui-text-tertiary); font-variant-numeric: tabular-nums; }
.hb-status[data-s=succeeded] { color: var(--ui-green, #248a3d); }
.hb-status[data-s=failed], .hb-status[data-s=timeout] { color: var(--ui-red, #d70015); }
.hb-status[data-s=running], .hb-status[data-s=queued] { color: var(--ui-blue, #0071e3); }
.hb-status[data-s=cancelled] { color: var(--ui-text-tertiary); }
.hb-about { display: grid; grid-template-columns: 88px 1fr; gap: 6px 12px; font-size: 12px; line-height: 1.6; }
.hb-about dt { color: var(--ui-text-tertiary); }
.hb-about dd { margin: 0; color: var(--ui-text-primary); word-break: break-word; }
.hb-muted { color: var(--ui-text-tertiary); }
@media (prefers-reduced-motion: reduce) {
  .hb-card, .hb-placeholder, .hb-grip, .hb-corner svg { transition: none !important; }
}
`;
