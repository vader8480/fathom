// Pure explorer core (docs/ui-audit.md B.2 EXPLORER, D3, D8): width clamping,
// persisted {w, c} state, filtering, grouping, list keyboard steps and the
// drawer/side mode. No DOM, window, timers or storage globals; storage is
// injected, so the module imports in Node.

import { layoutFor } from './router-core.js';

export const MIN_WIDTH = 240;
export const MAX_WIDTH = 480;
export const DEFAULT_WIDTH = 300;
export const RAIL_WIDTH = 56;
export const KEY_STEP = 16;
export const STORAGE_PREFIX = 'fathom.ui.explorer.';

export function storageKey(key) {
  return STORAGE_PREFIX + String(key === undefined || key === null ? '' : key);
}

export function clampWidth(w) {
  if (typeof w !== 'number' || !isFinite(w)) return DEFAULT_WIDTH;
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(w)));
}

function defaults() {
  return { w: DEFAULT_WIDTH, c: false };
}

export function loadExplorer(storage, key) {
  const st = defaults();
  if (!storage) return st;
  let raw = null;
  try {
    raw = storage.getItem(storageKey(key));
  } catch (e) {
    return st;
  }
  if (typeof raw !== 'string' || !raw) return st;
  let v;
  try {
    v = JSON.parse(raw);
  } catch (e) {
    return st;
  }
  if (!v || typeof v !== 'object' || Array.isArray(v)) return st;
  if (typeof v.w === 'number' && isFinite(v.w)) st.w = clampWidth(v.w);
  st.c = v.c === true;
  return st;
}

// Returns true when the state was written.
export function saveExplorer(storage, key, state) {
  if (!storage) return false;
  const s = state || {};
  try {
    storage.setItem(storageKey(key), JSON.stringify({ w: clampWidth(s.w), c: s.c === true }));
    return true;
  } catch (e) {
    return false;
  }
}

function hasKey(keys, k) {
  if (!keys) return false;
  if (typeof keys.has === 'function') return !!keys.has(k);
  if (Array.isArray(keys)) return keys.indexOf(k) !== -1;
  return false;
}

function lower(v) {
  return v === undefined || v === null ? '' : String(v).toLowerCase();
}

export function defaultMatch(item, q) {
  const needle = lower(q);
  if (!needle) return true;
  return lower(item && item.label).indexOf(needle) !== -1 || lower(item && item.sub).indexOf(needle) !== -1;
}

// Chips are OR within the active set, AND with the query. `match(item, q)`
// replaces the label + sub test; it gets the trimmed query as typed.
export function filterItems(items, q, activeChipKeys, chips, match) {
  const list = Array.isArray(items) ? items : [];
  const query = String(q === undefined || q === null ? '' : q).trim();
  const active = (Array.isArray(chips) ? chips : []).filter(function (c) {
    return c && typeof c.test === 'function' && hasKey(activeChipKeys, c.key);
  });
  const test = typeof match === 'function' ? match : defaultMatch;
  return list.filter(function (item) {
    if (active.length && !active.some(function (c) { return !!c.test(item); })) return false;
    return !query || !!test(item, query);
  });
}

// [{group, items}] in first-seen order; missing, null and '' share group ''.
export function groupItems(items) {
  const out = [];
  const index = {};
  (Array.isArray(items) ? items : []).forEach(function (item) {
    const g = item && item.group !== undefined && item.group !== null ? String(item.group) : '';
    const k = '\u0000' + g;
    if (!Object.prototype.hasOwnProperty.call(index, k)) {
      index[k] = out.length;
      out.push({ group: g, items: [] });
    }
    out[index[k]].items.push(item);
  });
  return out;
}

// Display order of groupItems output, which is also the keyboard order.
export function flattenGroups(groups) {
  const out = [];
  (groups || []).forEach(function (g) { g.items.forEach(function (it) { out.push(it); }); });
  return out;
}

// Listbox step for ArrowDown/ArrowUp (wrapping), Home and End; -1 when empty.
export function nextIndex(count, current, key) {
  const n = Math.max(0, Math.floor(Number(count) || 0));
  if (!n) return -1;
  const cur = typeof current === 'number' && isFinite(current) ? Math.floor(current) : -1;
  if (key === 'Home') return 0;
  if (key === 'End') return n - 1;
  if (key === 'ArrowDown') return cur < 0 || cur >= n ? 0 : (cur + 1) % n;
  if (key === 'ArrowUp') return cur < 0 || cur >= n ? n - 1 : (cur - 1 + n) % n;
  return cur < 0 ? -1 : Math.min(cur, n - 1);
}

// Resizer keyboard: ←/→ by KEY_STEP, Home/End to the bounds; null for other keys.
export function resizeKey(width, key) {
  const w = clampWidth(width);
  if (key === 'ArrowLeft') return clampWidth(w - KEY_STEP);
  if (key === 'ArrowRight') return clampWidth(w + KEY_STEP);
  if (key === 'Home') return MIN_WIDTH;
  if (key === 'End') return MAX_WIDTH;
  return null;
}

// Pointer drag: the width the sidebar has after moving from startX to x.
export function dragWidth(startWidth, startX, x) {
  return clampWidth(clampWidth(startWidth) + (Number(x) - Number(startX)));
}

export function explorerMode(width) {
  return layoutFor(width) === 'sm' ? 'drawer' : 'side';
}

export function footerText(shown, total, footer) {
  if (typeof footer === 'function') {
    const v = footer(shown, total);
    return v === undefined || v === null ? '' : String(v);
  }
  return shown === total ? total + (total === 1 ? ' item' : ' items') : shown + ' of ' + total;
}

export function openLabel(label, total) {
  return '\u2630 ' + String(label || '') + ' (' + (Number(total) || 0) + ')';
}
