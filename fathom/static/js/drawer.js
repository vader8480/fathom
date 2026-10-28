// Drawer behaviour for the inspector host (docs/ui-audit.md D3, D4, B.2 DRAWER).
// The host keeps its content (inspector.js renders into it as before); this
// module owns the mode classes, roles, the backdrop, the focus trap, Esc and
// focus return.
//
//   const d = createDrawer(document.getElementById('app-inspector'), { label: 'Details', onClose: fn });
//   d.open(); d.close(); d.isOpen(); d.mode(); d.relayout(); d.destroy();
//
// Options beyond the contract: `layers()` returns the {palette, dialog, trace,
// assistant, explorer} flags used for the Esc order (default: read from the
// DOM); `open({focus: false})` opens without moving focus (canvas selection
// at lg); `relayout(width)` takes an explicit width. domLayers(doc, host) also
// reports `dialog` for any rendered [role=dialog][aria-modal=true] outside the
// drawer host and the palette, assistant, explorer and trace layers.

import { h, on } from './dom.js';
import { drawerMode, isModal, topLayer, trapIndex, LAYERS } from './drawer-core.js';

const MODES = ['docked', 'sheet', 'full'];
const FOCUSABLE = 'a[href], area[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), ' +
  'select:not([disabled]), textarea:not([disabled]), summary, iframe, [tabindex]:not([tabindex="-1"]), ' +
  '[contenteditable=""], [contenteditable="true"]';

function rendered(el) {
  if (!el || !el.getClientRects().length) return false;
  // Chrome gives layout rects to the content of a closed <details>.
  for (let p = el.parentElement, c = el; p; c = p, p = p.parentElement) {
    if (p.tagName === 'DETAILS' && !p.open && !(c.tagName === 'SUMMARY' && c.parentElement === p)) return false;
  }
  if (typeof el.checkVisibility === 'function' &&
    !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true, opacityProperty: true, visibilityProperty: true })) return false;
  const cs = el.ownerDocument.defaultView.getComputedStyle(el);
  return cs.visibility !== 'hidden' && cs.opacity !== '0';
}

function shown(doc, selector) {
  const all = doc.querySelectorAll(selector);
  for (let i = 0; i < all.length; i++) if (rendered(all[i])) return true;
  return false;
}

// Modal dialogs that belong to another layer (or are the drawer itself) and so
// do not count as a generic dialog.
const OWN_LAYER = '#app-palette, #app-assistant, .ex-side, .trace-backdrop, .trace-sheet';

// Any rendered [role=dialog][aria-modal=true] outside `host` and the other
// layers: wizard and admin dialogs that have no .app-dialog-backdrop.
function genericDialog(d, host) {
  const all = d.querySelectorAll('[role="dialog"][aria-modal="true"]');
  for (let i = 0; i < all.length; i++) {
    const el = all[i];
    if (host && (el === host || host.contains(el) || el.contains(host))) continue;
    if (el.closest(OWN_LAYER)) continue;
    if (rendered(el)) return true;
  }
  return false;
}

// Layers above the drawer, read from the shell's DOM (D4 Esc order). `host` (the
// drawer element) is left out of the generic modal-dialog check.
export function domLayers(doc, host) {
  const d = doc || document;
  const ast = d.getElementById('app-assistant');
  return {
    palette: shown(d, '#app-palette'),
    dialog: shown(d, '.app-dialog-backdrop, .sop-sheet, .sop-lightbox') || genericDialog(d, host || null),
    trace: shown(d, '.trace-backdrop'),
    assistant: !!ast && ast.classList.contains('open'),
    explorer: shown(d, '.ex-backdrop'),
  };
}

function isField(el) {
  const t = el && el.tagName;
  return t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT' || !!(el && el.isContentEditable);
}

function focusEl(el) {
  try {
    el.focus({ preventScroll: true });
  } catch (e) {
    el.focus();
  }
}

export function createDrawer(host, opts) {
  const o = opts || {};
  const doc = host.ownerDocument;
  const win = doc.defaultView;
  const saved = {};
  ['role', 'aria-modal', 'aria-label', 'tabindex'].forEach(function (k) { saved[k] = host.getAttribute(k); });
  const label = o.label || saved['aria-label'] || 'Details';
  const offs = [];
  let isOpenNow = false;
  let mode = '';
  let opener = null;
  let backdrop = null;
  let parentMarked = null;
  let destroyed = false;

  host.classList.add('dr-host');
  if (saved.tabindex === null) host.setAttribute('tabindex', '-1');

  function flags() {
    let f = null;
    try {
      f = o.layers ? o.layers() : domLayers(doc, host);
    } catch (e) {
      f = null;
    }
    const r = {};
    LAYERS.forEach(function (k) { r[k] = !!(f && f[k]); });
    r.drawer = isOpenNow;
    return r;
  }

  function focusInside() {
    const ae = doc.activeElement;
    return !!ae && host.contains(ae);
  }

  function focusHost() {
    focusEl(host);
  }

  function rememberOpener() {
    const ae = doc.activeElement;
    if (ae && ae !== doc.body && ae !== doc.documentElement && !host.contains(ae) && ae !== backdrop) opener = ae;
  }

  function apply() {
    const modal = isModal(mode);
    MODES.forEach(function (m) { host.classList.toggle('dr-' + m, m === mode); });
    host.classList.toggle('dr-open', isOpenNow);
    host.setAttribute('aria-label', label);
    if (modal) {
      host.setAttribute('role', 'dialog');
      host.setAttribute('aria-modal', 'true');
    } else {
      host.setAttribute('role', 'complementary');
      host.removeAttribute('aria-modal');
    }
    if (isOpenNow && modal && !backdrop && host.parentNode) {
      backdrop = h('div', { class: 'dr-backdrop', 'aria-hidden': 'true', onclick: function () { dismiss('backdrop'); } });
      host.parentNode.insertBefore(backdrop, host);
    } else if ((!isOpenNow || !modal) && backdrop) {
      if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
      backdrop = null;
    }
    const parent = host.parentElement;
    if (parentMarked && parentMarked !== parent) parentMarked.classList.remove('dr-docked-open');
    parentMarked = parent;
    if (parent) parent.classList.toggle('dr-docked-open', isOpenNow && mode === 'docked');
  }

  function relayout(width) {
    if (destroyed) return mode;
    const prev = mode;
    mode = drawerMode(typeof width === 'number' ? width : win.innerWidth);
    if (prev === mode) return mode;
    apply();
    if (isOpenNow && isModal(mode) && !isModal(prev) && !focusInside()) {
      if (!opener) rememberOpener();
      focusHost();
    }
    return mode;
  }

  function open(openOpts) {
    if (destroyed) return;
    relayout();
    if (isOpenNow) return;
    const focus = !(openOpts && openOpts.focus === false) || isModal(mode);
    opener = null;
    rememberOpener();
    isOpenNow = true;
    apply();
    if (focus) focusHost();
  }

  function close() {
    if (!isOpenNow) return;
    const ae = doc.activeElement;
    const inside = focusInside();
    const lost = !ae || ae === doc.body || ae === doc.documentElement;
    isOpenNow = false;
    apply();
    const back = opener;
    opener = null;
    if ((inside || lost) && back && back.isConnected && rendered(back)) focusEl(back);
  }

  function dismiss(reason) {
    close();
    if (typeof o.onClose === 'function') o.onClose(reason);
  }

  // Layers are read in the capture phase, before any handler closes one of
  // them, and acted on in the bubble phase, after the content's own handlers
  // (which may preventDefault, e.g. to cancel an inline edit).
  let escSnap = null;
  function onKeyCapture(e) {
    escSnap = isOpenNow && (e.key === 'Escape' || e.key === 'Esc') ? { e: e, top: topLayer(flags()), inside: focusInside() } : null;
  }

  function onKey(e) {
    if (!isOpenNow || destroyed || e.defaultPrevented) return;
    const modal = isModal(mode);
    if (e.key === 'Escape' || e.key === 'Esc') {
      const snap = escSnap && escSnap.e === e ? escSnap : { top: topLayer(flags()), inside: focusInside() };
      escSnap = null;
      if (!modal && !snap.inside) return;
      if (snap.top !== 'drawer') return;
      e.preventDefault();
      const ae = doc.activeElement;
      if (ae && ae !== host && host.contains(ae) && isField(ae)) {
        // First Esc leaves the field (committing it on blur), the next one closes.
        ae.blur();
        focusHost();
        return;
      }
      dismiss('escape');
      return;
    }
    if (e.key === 'Tab' && modal) {
      if (topLayer(flags()) !== 'drawer') return;
      const list = Array.prototype.filter.call(host.querySelectorAll(FOCUSABLE), rendered);
      const next = trapIndex(list.length, list.indexOf(doc.activeElement), e.shiftKey);
      if (next === null) return;
      e.preventDefault();
      if (next < 0) focusHost();
      else focusEl(list[next]);
    }
  }

  function onFocusIn(e) {
    if (!isOpenNow || !isModal(mode)) return;
    const t = e.target;
    if (t === win || t === doc || host.contains(t)) return;
    if (topLayer(flags()) !== 'drawer') return;
    focusHost();
  }

  offs.push(on(doc, 'keydown', onKeyCapture, true));
  offs.push(on(doc, 'keydown', onKey));
  offs.push(on(doc, 'focusin', onFocusIn));
  offs.push(on(win, 'resize', function () { relayout(); }));
  relayout();

  function destroy() {
    if (destroyed) return;
    destroyed = true;
    offs.forEach(function (off) { off(); });
    if (backdrop && backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
    backdrop = null;
    if (parentMarked) parentMarked.classList.remove('dr-docked-open');
    host.classList.remove('dr-host', 'dr-open', 'dr-docked', 'dr-sheet', 'dr-full');
    Object.keys(saved).forEach(function (k) {
      if (saved[k] === null) host.removeAttribute(k);
      else host.setAttribute(k, saved[k]);
    });
    isOpenNow = false;
    opener = null;
  }

  return {
    el: host,
    open: open,
    close: close,
    isOpen: function () { return isOpenNow; },
    mode: function () { return mode; },
    relayout: relayout,
    destroy: destroy,
  };
}
