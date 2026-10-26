// Pure drawer core (docs/ui-audit.md D1, D3, D4, B.2 DRAWER): drawer modes,
// the sel/sec/drawer query keys, Esc layering and the canvas-selection rule.
// No DOM, window, timers or storage, so the module imports in Node.

import { layoutFor } from './router-core.js';

const MODE_FOR_LAYOUT = { sm: 'full', md: 'sheet', lg: 'docked' };

// 'docked' (>= 1100), 'sheet' (700-1099) or 'full' (< 700).
export function drawerMode(width) {
  return MODE_FOR_LAYOUT[layoutFor(width)];
}

// Sheet and full modes are modal (backdrop, focus trap); docked is not.
export function isModal(mode) {
  return mode === 'sheet' || mode === 'full';
}

function str(v) {
  return v === undefined || v === null || v === '' ? null : String(v);
}

// {sel, section, open}; only drawer === '0' keeps a selection with the drawer closed.
export function parseDrawer(query) {
  const q = query || {};
  const sel = str(q.sel);
  return { sel: sel, section: str(q.sec), open: !!sel && q.drawer !== '0' };
}

// Query patch for withQuery/setParams: null deletes a key.
export function drawerParams(state) {
  const s = state || {};
  const sel = str(s.sel);
  return {
    sel: sel,
    sec: sel ? str(s.section) : null,
    drawer: sel && !s.open ? '0' : null,
  };
}

// D1 history rule: opening from closed pushes (so Back closes the drawer);
// switching subject or section while open, and closing, replace. null = no change.
export function drawerHistory(prev, next) {
  const a = drawerParams(prev);
  const b = drawerParams(next);
  const wasOpen = !!a.sel && a.drawer === null;
  const isOpen = !!b.sel && b.drawer === null;
  if (a.sel === b.sel && a.sec === b.sec && a.drawer === b.drawer) return null;
  return !wasOpen && isOpen ? 'push' : 'replace';
}

// D4 Esc order, topmost first.
export const LAYERS = ['palette', 'dialog', 'trace', 'assistant', 'explorer', 'drawer'];

// The layer Esc closes, or null when none is open.
export function topLayer(flags) {
  const f = flags || {};
  for (let i = 0; i < LAYERS.length; i++) {
    if (f[LAYERS[i]]) return LAYERS[i];
  }
  return null;
}

export const CANVAS_VIEWS = ['patch', 'plan', 'map'];

// Canvas views, plus racks when there is no rack id or the tab is the elevation.
export function isCanvas(view, route) {
  const r = route || {};
  const v = view || r.view || '';
  if (CANVAS_VIEWS.indexOf(v) >= 0) return true;
  if (v === 'racks') return !r.id || r.tab === 'elevation';
  return false;
}

// D4: explicit intent (list row, search, "Details") always opens the drawer;
// a plain canvas selection opens it only where it docks (lg).
export function selectionOpensDrawer(view, route, layout, intent) {
  if (intent === true) return true;
  if (!isCanvas(view, route)) return true;
  return layout === 'lg';
}

// Focus-trap step for Tab inside a modal drawer. `current` is the index of the
// focused element among `count` focusables (-1 for the host itself or outside).
// Returns the index to focus, -1 for the host, or null to let Tab move normally.
export function trapIndex(count, current, back) {
  if (!count) return -1;
  if (current < 0 || current >= count) return back ? count - 1 : 0;
  if (back && current === 0) return count - 1;
  if (!back && current === count - 1) return 0;
  return null;
}
