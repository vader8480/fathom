// Fathom patch view — DOM module. Spec §3.5 FR-PV, §6.4 view contract, §6.5, §6.11.
// ES2018 syntax only. All edits go through ctx.commit as change ops (§4.9).

import * as core from './patchview-core.js';
import {
  canConnect, connectOps, disconnectOps, repatchOps, deleteDeviceOps, duplicateDeviceOps, renameOps,
  addDeviceFromTemplateOps, setPortsOps, applyOps,
} from './model-core.js';
import { esc, on } from './dom.js';
import { layoutFor } from './router-core.js';
import { emptyState, confirmScope, staleBadge } from './feedback.js';

const DISC_ORDER = ['audio', 'video', 'lighting', 'network', 'control', 'power', 'other'];
const STATUS_ORDER = ['installed', 'planned', 'spare', 'retired'];
const LONG_PRESS_MS = 500;
const MOVE_SLOP = 4;
const TOUCH_SLOP = 8;
const SVG_NS = 'http://www.w3.org/2000/svg';
// Query keys this view owns while it is the routed view (docs/ui-audit.md D1, B.3 PV).
const URL_KEYS = ['filter', 'q', 'status'];
// sessionStorage key for the PNG/PDF availability probe ('ok' | 'missing'), FR-EXP-06.
const RASTER_KEY = 'fathom.pv.raster';
// Printable area the canvas is fitted into while printing (landscape A4/letter at 96 dpi less margins).
const PRINT_W = 960;
const PRINT_H = 640;
let uidSeq = 0;

function splitList(s, allowed) {
  return String(s || '').split(',').map(function (x) { return x.trim(); }).filter(function (x, i, a) {
    return x && a.indexOf(x) === i && (!allowed || allowed.indexOf(x) >= 0);
  });
}

// Store filter subset carried by the URL: `filter` (disciplines), `q` (text) and `status`.
function filterFromQuery(q) {
  q = q || {};
  return {disciplines: splitList(q.filter), statuses: splitList(q.status, STATUS_ORDER), query: String(q.q || '')};
}

function queryFromFilter(f) {
  f = f || {};
  const d = (f.disciplines || []).join(','), s = (f.statuses || []).join(','), t = String(f.query || '');
  return {filter: d || null, q: t || null, status: s || null};
}

function hexA(hex, a) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || ''));
  if (!m) return 'rgba(154,163,181,' + a + ')';
  const n = parseInt(m[1], 16);
  return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
}

function cssEsc(s) { return String(s).replace(/["\\]/g, '\\$&'); }

export function mount(el, ctx) {
  const doc0 = el.ownerDocument;
  const win = doc0.defaultView;
  const store = ctx.store;
  const perf = win.performance;
  const t0 = perf.now();
  const uid = 'pv' + (++uidSeq);
  const coarse = !!(win.matchMedia && win.matchMedia('(pointer: coarse)').matches);
  const S = {
    view: {x: 0, y: 0, k: 1}, scene: null, autoPos: {}, expanded: new Set(), showRoutes: false,
    allRooms: !!(store.filter && store.filter.room === '*'), snapOn: true, sel: new Set(), selWire: null, selPort: null,
    gesture: null, pointers: {}, nPointers: 0, space: false, menu: null, rename: null, kb: null, cardHtml: {}, wireSig: {},
    cardEls: {}, wireEls: {}, rendered: false, raf: 0, hoverRaf: 0, hoverWire: null, lastTap: null, destroyed: false,
    geom: coarse ? {rowH: core.COARSE_ROW_H} : null, longTimer: 0, gs: null, filterTimer: 0, lastHover: null,
    pop: null, layout: '', emptyKey: null, probe: false, printSaved: null,
  };
  const stats = {renderMs: 0, cards: 0, wires: 0, lastDragFrameMs: 0};
  const vocab = function () { return store.vocab || ctx.vocab || {}; };
  const ro = function () { return !!store.readOnly || ctx.role === 'viewer'; };

  // ------------------------------------------------------------ DOM skeleton
  // One toolbar row: primary actions, zoom, undo, the text filter, then the View and Arrange
  // popovers. Below 700 px (layoutFor 'sm') zoom, undo and both popover panes move into the
  // "More" popover (placeControls), so every #pv-* control stays in the DOM exactly once.
  el.innerHTML = '';
  const root = doc0.createElement('div');
  root.className = 'pv-root';
  const popTrigger = function (menu, cls, label, text, aria) {
    return '<div class="pv-pop-wrap pv-pop-' + menu + '" data-menu="' + menu + '">' +
      '<button type="button" class="pv-btn ' + cls + '" aria-haspopup="true" aria-expanded="false" aria-controls="' +
        uid + '-' + menu + '"' + (aria ? ' aria-label="' + aria + '"' : '') + '>' + text +
        '<span class="pv-menu-n" hidden></span></button>' +
      '<div class="pv-pop" id="' + uid + '-' + menu + '" role="group" aria-label="' + label + '" hidden>';
  };
  root.innerHTML =
    '<div class="pv-toolbar" role="toolbar" aria-label="Patch view tools">' +
      '<div class="pv-tgroup pv-tmain">' +
        '<button type="button" id="pv-add" class="pv-btn pv-primary" aria-label="Add gear"><span aria-hidden="true">+</span><span class="pv-btxt">Add gear</span></button>' +
        '<button type="button" id="pv-fit" class="pv-btn pv-icon" aria-label="Fit to screen" title="Fit (F)">\u2922</button>' +
      '</div>' +
      '<div class="pv-tgroup pv-tzoom">' +
        '<button type="button" id="pv-zoom-out" class="pv-btn pv-icon" aria-label="Zoom out" title="Zoom out (-)">\u2212</button>' +
        '<span class="pv-zoomlabel" aria-hidden="true">100%</span>' +
        '<button type="button" id="pv-zoom-in" class="pv-btn pv-icon" aria-label="Zoom in" title="Zoom in (+)">+</button>' +
      '</div>' +
      '<div class="pv-tgroup pv-tundo">' +
        '<button type="button" id="pv-undo" class="pv-btn pv-icon" aria-label="Undo" title="Undo (\u2318Z)">\u21b6</button>' +
        '<button type="button" id="pv-redo" class="pv-btn pv-icon" aria-label="Redo" title="Redo (\u21e7\u2318Z)">\u21b7</button>' +
      '</div>' +
      '<div class="pv-search">' +
        '<button type="button" class="pv-btn pv-icon pv-search-toggle" aria-label="Filter devices" aria-expanded="false" ' +
          'aria-controls="pv-filter-text"><span aria-hidden="true">\u26B2</span></button>' +
        '<label class="pv-sr" for="pv-filter-text">Filter devices</label>' +
        '<input id="pv-filter-text" type="search" placeholder="Filter\u2026" autocomplete="off" spellcheck="false">' +
      '</div>' +
      popTrigger('view', 'pv-menu-view', 'View options', 'View <span aria-hidden="true">\u25BE</span>') +
        '<div class="pv-pane pv-pane-view">' +
          '<div class="pv-pop-h" aria-hidden="true">Show</div>' +
          '<div class="pv-tgroup pv-pop-toggles">' +
            '<button type="button" id="pv-show-unconnected" class="pv-btn pv-toggle" aria-pressed="true">Unconnected ports</button>' +
            '<button type="button" id="pv-show-routes" class="pv-btn pv-toggle" aria-pressed="false">Network routes</button>' +
            '<button type="button" id="pv-all-rooms" class="pv-btn pv-toggle" aria-pressed="false">All rooms</button>' +
            '<button type="button" id="pv-snap" class="pv-btn pv-toggle" aria-pressed="true" title="Snap to 8 px grid">Snap</button>' +
          '</div>' +
          '<div class="pv-pop-h" aria-hidden="true">Discipline</div>' +
          '<div id="pv-filter-disc" class="pv-chips" role="group" aria-label="Discipline filter"></div>' +
          '<div class="pv-pop-h" aria-hidden="true">Status</div>' +
          '<div id="pv-filter-status" class="pv-chips" role="group" aria-label="Status filter"></div>' +
        '</div>' +
      '</div></div>' +
      popTrigger('arrange', 'pv-menu-arrange', 'Arrange', 'Arrange <span aria-hidden="true">\u25BE</span>') +
        '<div class="pv-pane pv-pane-arrange">' +
          '<button type="button" id="pv-arrange" class="pv-btn" aria-label="Auto-arrange"><span aria-hidden="true">\u2637</span><span>Auto-arrange</span></button>' +
          '<button type="button" id="pv-save-arrangement" class="pv-btn" hidden>Save arrangement</button>' +
        '</div>' +
      '</div></div>' +
      popTrigger('more', 'pv-icon pv-menu-more', 'More tools', '<span aria-hidden="true">\u22EF</span>', 'More tools') +
        // Export (FR-EXP-06): plain anchors so a tap downloads on iOS too; PNG/PDF grey out without Chrome (syncExport).
        '<div class="pv-pane pv-pane-export">' +
          '<div class="pv-pop-h" aria-hidden="true">Export</div>' +
          '<a id="pv-export-svg" class="pv-btn pv-export" data-ext="svg" href="#" download>Patch SVG</a>' +
          '<a id="pv-export-png" class="pv-btn pv-export" data-ext="png" href="#" download>Patch PNG</a>' +
          '<a id="pv-export-pdf" class="pv-btn pv-export" data-ext="pdf" href="#" download>Patch PDF</a>' +
          '<button type="button" id="pv-print" class="pv-btn">Print\u2026</button>' +
        '</div>' +
      '</div></div>' +
    '</div>' +
    '<div class="pv-viewport" role="application" aria-label="Patch view" tabindex="0" aria-describedby="' + uid + '-help">' +
      '<div class="pv-world">' +
        '<svg class="pv-wires" width="1" height="1" overflow="visible" aria-hidden="true">' +
          '<g class="pv-routes"></g><g class="pv-wire-g"></g><path class="pv-temp" d="" fill="none"></path>' +
        '</svg>' +
        '<div class="pv-cards"></div>' +
      '</div>' +
      '<div class="pv-badge" aria-hidden="true"><span class="pv-badge-dot"></span>Patch view</div>' +
      '<div class="pv-hint" aria-hidden="true">Drag gear \u00b7 re-patch wires \u00b7 rename anything</div>' +
      '<div class="pv-empty" hidden></div>' +
      '<div class="pv-stale-host" hidden></div>' +
      '<div class="pv-box" hidden></div>' +
    '</div>' +
    '<p class="pv-sr" id="' + uid + '-help">Tab moves between devices. Arrow keys move the selected device; hold Shift for larger steps. ' +
      'Enter renames. Press P to move into the ports, Up and Down to change port, C to start a connection, then arrows to pick a target and Enter to connect. ' +
      'Delete removes the selected cable or device. Plus, minus, 0 and F zoom. Escape cancels.</p>' +
    '<div class="pv-menu" role="menu" hidden></div>';
  el.appendChild(root);

  const $ = function (sel) { return root.querySelector(sel); };
  const toolbar = $('.pv-toolbar');
  const viewportEl = $('.pv-viewport');
  const world = $('.pv-world');
  const svg = $('.pv-wires');
  const wiresG = $('.pv-wire-g');
  const routesG = $('.pv-routes');
  const tempPath = $('.pv-temp');
  const cardsEl = $('.pv-cards');
  const emptyEl = $('.pv-empty');
  const staleHost = $('.pv-stale-host');
  const boxEl = $('.pv-box');
  const menuEl = $('.pv-menu');
  const zoomLabel = $('.pv-zoomlabel');
  const textInput = $('#pv-filter-text');
  const searchBox = $('.pv-search');
  const searchToggle = $('.pv-search-toggle');
  const morePop = $('.pv-pop-more .pv-pop');
  const exportPane = $('.pv-pane-export');
  const homes = {
    zoom: {node: $('.pv-tzoom'), parent: toolbar, before: $('.pv-tundo')},
    undo: {node: $('.pv-tundo'), parent: toolbar, before: searchBox},
    arrange: {node: $('.pv-pane-arrange'), parent: $('.pv-pop-arrange .pv-pop'), before: null},
    view: {node: $('.pv-pane-view'), parent: $('.pv-pop-view .pv-pop'), before: null},
  };
  const offs = [];
  // Row CSS always follows the layout geometry so wire anchors and row boxes cannot disagree.
  root.style.setProperty('--pv-row', (S.geom ? S.geom.rowH : core.GEOM.rowH) + 'px');

  // ------------------------------------------------------------ helpers
  function announce(text) {
    const live = doc0.getElementById('fathom-live');
    if (!live || !text) return;
    live.textContent = '';
    win.setTimeout(function () { live.textContent = text; }, 30);
  }
  function toast(msg, level) { if (ctx.toast) ctx.toast(msg, level || 'info'); }
  function commit(ops, label) {
    if (!ops || !ops.length) return;
    if (ro()) { toast('This view is read-only', 'warn'); return; }
    try {
      ctx.commit(ops, label);
    } catch (err) {
      toast((err && err.message) || 'Could not apply the change', 'err');
    }
  }
  function findDevice(id) {
    const ds = store.doc.devices || [];
    for (let i = 0; i < ds.length; i++) if (ds[i].id === id) return ds[i];
    const od = (store.overlay && store.overlay.devices) || [];
    for (let i = 0; i < od.length; i++) if (od[i].id === id) return od[i];
    return null;
  }
  function findPortOf(dev, pid) {
    const ps = core.portsOf(dev);
    for (let i = 0; i < ps.length; i++) if (ps[i].id === pid) return ps[i];
    return null;
  }
  function endName(e) {
    const d = findDevice(e.device);
    if (!d) return e.device;
    const p = e.port ? findPortOf(d, e.port) : null;
    return (d.name || d.id) + (p ? ' ' + (p.name || p.id) : '');
  }
  function localPt(e) {
    const r = viewportEl.getBoundingClientRect();
    return {x: e.clientX - r.left, y: e.clientY - r.top};
  }
  function viewSize() { return {w: viewportEl.clientWidth || 800, h: viewportEl.clientHeight || 600}; }
  function defaultRoom() {
    const d = store.doc;
    if (d.settings && d.settings.default_room) return d.settings.default_room;
    return d.rooms && d.rooms.length ? d.rooms[0].id : '*';
  }
  function currentRoom() {
    if (S.allRooms) return '*';
    const r = store.room;
    return r === undefined || r === null ? defaultRoom() : r;
  }
  function currentFilter() {
    const f = store.filter || {};
    return {room: currentRoom(), disciplines: f.disciplines || [], statuses: f.statuses || [], query: f.query || '',
      system: f.system || '', state: f.state || 'all', showUnconnected: f.showUnconnected !== false};
  }
  function editable(card) { return !ro() && card && !card.auto; }
  function roomLabel() {
    const r = currentRoom();
    if (r === '*') return 'this project';
    if (!r) return 'Shared inventory';
    const m = (store.doc.rooms || []).filter(function (x) { return x.id === r; })[0];
    return m ? (m.name || m.id) : r;
  }

  // ------------------------------------------------------------ URL state (filter, q, status)
  // Only the routed patch view owns these keys; an embedded copy (patch table split) leaves the URL alone.
  function routed() {
    const r = ctx.route;
    return !!(r && r.view === 'patch' && typeof ctx.setParams === 'function');
  }
  function urlFromStore() {
    if (S.destroyed || !routed()) return;
    const want = queryFromFilter(store.filter);
    const q = ctx.route.query || {};
    const same = URL_KEYS.every(function (k) { return (q[k] || null) === want[k]; });
    if (!same) ctx.setParams(want, {replace: true});
  }
  function storeFromQuery(q) {
    const want = filterFromQuery(q);
    const f = store.filter || {};
    const same = (f.query || '') === want.query && (f.disciplines || []).join(',') === want.disciplines.join(',') &&
      (f.statuses || []).join(',') === want.statuses.join(',');
    if (!same) store.setFilter(want);
    return !same;
  }

  // ------------------------------------------------------------ toolbar layout and popovers
  function placeControls(layout) {
    const compact = layout === 'sm';
    if (S.layout && (S.layout === 'sm') === compact) { S.layout = layout; return; }
    S.layout = layout;
    closePop(false);
    root.classList.toggle('pv-compact', compact);
    if (compact) {
      ['zoom', 'undo', 'arrange', 'view'].forEach(function (k) { morePop.insertBefore(homes[k].node, exportPane); });
    } else {
      ['view', 'arrange', 'undo', 'zoom'].forEach(function (k) {
        const h0 = homes[k];
        h0.parent.insertBefore(h0.node, h0.before && h0.before.parentNode === h0.parent ? h0.before : null);
      });
    }
    syncSearch();
  }
  function onResize() { placeControls(layoutFor(win.innerWidth)); }
  function openPop(wrap) {
    if (S.pop && S.pop.wrap === wrap) return;
    closePop(false);
    const btn = wrap.querySelector('[aria-haspopup]');
    const pop = wrap.querySelector('.pv-pop');
    pop.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    wrap.classList.add('pv-open');
    S.pop = {wrap: wrap, btn: btn, pop: pop};
    if (wrap === exportPane.closest('.pv-pop-wrap')) syncExport();
    const first = pop.querySelector('button:not([disabled]):not([hidden]), a[href]:not([aria-disabled="true"])');
    if (first) first.focus({preventScroll: true});
  }
  function closePop(restore) {
    const p = S.pop;
    if (!p) return;
    S.pop = null;
    p.pop.hidden = true;
    p.btn.setAttribute('aria-expanded', 'false');
    p.wrap.classList.remove('pv-open');
    if (restore) p.btn.focus({preventScroll: true});
  }
  function onToolbarKey(e) {
    if (e.key !== 'Escape' || !S.pop) return;
    e.preventDefault();
    e.stopPropagation();
    closePop(true);
  }
  function onToolbarFocusOut(e) {
    const p = S.pop;
    if (p && e.relatedTarget && !p.wrap.contains(e.relatedTarget)) closePop(false);
  }
  function syncSearch() {
    const open = S.layout !== 'sm' || searchBox.classList.contains('pv-search-open') || !!textInput.value;
    searchBox.classList.toggle('pv-search-open', S.layout === 'sm' && open);
    searchToggle.setAttribute('aria-expanded', String(open));
  }
  function openSearch() {
    searchBox.classList.add('pv-search-open');
    syncSearch();
    textInput.focus();
  }
  function onSearchBlur() {
    if (S.layout === 'sm' && !textInput.value) { searchBox.classList.remove('pv-search-open'); syncSearch(); }
  }

  // ------------------------------------------------------------ export (FR-EXP-06, §5.9)
  // Patch SVG / PNG / PDF are the server routes for the room on screen (?scene= while a scene is active or
  // previewed). PNG and PDF need Chrome on the server: one HEAD probe per browser session (400 chrome_missing
  // greys them out), remembered in sessionStorage so the next mount does not ask again.
  function exportRoom() {
    const r = currentRoom();
    return r && r !== '*' ? r : defaultRoom();
  }
  function exportScene() {
    const pv = ctx.preview;
    if (pv && pv.scene) return String(pv.scene);
    const st = store.doc.settings || {};
    return st.scene ? String(st.scene) : '';
  }
  function exportHref(ext) {
    const room = exportRoom();
    if (!ctx.project || !room || room === '*') return '';
    const scene = exportScene();
    return ((ctx.api && ctx.api.base) || '') + 'api/v2/projects/' + encodeURIComponent(ctx.project) + '/rooms/' +
      encodeURIComponent(room) + '/patch.' + ext + (scene ? '?scene=' + encodeURIComponent(scene) : '');
  }
  function rasterState(set) {
    let ss = null;
    try { ss = win.sessionStorage; } catch (err) { ss = null; }
    if (set !== undefined) {
      rasterState.value = set;
      try { if (ss) ss.setItem(RASTER_KEY, set); } catch (err) { /* private mode: keep the in-memory copy */ }
      return set;
    }
    if (rasterState.value) return rasterState.value;
    try { return (ss && ss.getItem(RASTER_KEY)) || ''; } catch (err) { return ''; }
  }
  function syncExport() {
    const missing = rasterState() === 'missing';
    const proj = ctx.project || '';
    exportPane.hidden = !proj;
    root.querySelectorAll('.pv-export').forEach(function (a) {
      const ext = a.getAttribute('data-ext');
      const href = exportHref(ext);
      const off = !href || (ext !== 'svg' && missing);
      if (off) {
        a.removeAttribute('href');
        a.removeAttribute('download');
        a.setAttribute('aria-disabled', 'true');
        a.classList.add('pv-disabled');
        a.title = href ? 'Needs Chrome on the server' : '';
      } else {
        a.setAttribute('href', href);
        a.setAttribute('download', proj + '-' + exportRoom() + '-patch.' + ext);
        a.removeAttribute('aria-disabled');
        a.classList.remove('pv-disabled');
        a.title = '';
      }
    });
    if (proj && !rasterState() && !S.probe) probeRaster();
  }
  function probeRaster() {
    const href = exportHref('png');
    if (!href || typeof win.fetch !== 'function') return;
    S.probe = true;
    win.fetch(href, {method: 'HEAD', credentials: 'same-origin'}).then(function (res) {
      if (res.status === 400) rasterState('missing');
      else if (res.ok) rasterState('ok');
    }).catch(function () { /* offline or blocked: leave the items enabled */ }).then(function () {
      S.probe = false;
      if (!S.destroyed) syncExport();
    });
  }
  // Print (FR-EXP-06): the canvas is fitted to a landscape page while the dialog is up; beforeprint / afterprint
  // cover Cmd+P as well, and the view is put back afterwards.
  function printFit() {
    if (!S.scene || S.printSaved) return;
    S.printSaved = {x: S.view.x, y: S.view.y, k: S.view.k};
    root.classList.add('pv-printing');
    S.view = core.fitView(S.scene.bounds, {w: PRINT_W, h: PRINT_H}, 24, 0.05, 1);
    applyView();
  }
  function printRestore() {
    if (!S.printSaved) return;
    root.classList.remove('pv-printing');
    S.view = S.printSaved;
    S.printSaved = null;
    applyView();
  }
  function printCanvas() {
    closePop(false);
    printFit();
    if (typeof win.print === 'function') win.print();
  }

  // ------------------------------------------------------------ view transform
  function applyView() {
    const v = S.view;
    world.style.transform = 'translate3d(' + v.x + 'px,' + v.y + 'px,0) scale(' + v.k + ')';
    const g = 22 * v.k;
    viewportEl.style.backgroundSize = g + 'px ' + g + 'px';
    viewportEl.style.backgroundPosition = v.x + 'px ' + v.y + 'px';
    zoomLabel.textContent = Math.round(v.k * 100) + '%';
  }
  function zoomBy(factor, pt) {
    const sz = viewSize();
    S.view = core.zoomAt(S.view, pt || {x: sz.w / 2, y: sz.h / 2}, factor);
    applyView();
  }
  function fit() {
    if (!S.scene) return;
    S.view = core.fitView(S.scene.bounds, viewSize(), 40);
    applyView();
  }
  function ensureVisible(x, y, w, h) {
    const sz = viewSize();
    const a = core.worldToScreen(S.view, {x: x, y: y});
    const b = core.worldToScreen(S.view, {x: x + w, y: y + h});
    if (a.x >= 0 && a.y >= 0 && b.x <= sz.w && b.y <= sz.h) return;
    S.view = {x: sz.w / 2 - (x + w / 2) * S.view.k, y: sz.h / 2 - (y + h / 2) * S.view.k, k: S.view.k};
    applyView();
  }

  // ------------------------------------------------------------ rendering
  function rowHtml(card, row) {
    const v = vocab();
    const p = row.port;
    const m = core.mediumInfo(p.medium, v);
    const ref = card.id + ':' + p.id;
    const conn = !!(S.scene.wiresByPort[ref] && S.scene.wiresByPort[ref].length);
    const side = row.side;
    const cls = 'pv-port pv-' + side + (conn ? ' pv-conn' : '');
    const dot = function (s) {
      return '<span class="pv-dot pv-dot-' + s + '" style="--c:' + esc(m.color) + '" aria-hidden="true"></span>';
    };
    const glyph = side === 'left' ? '\u2190' : (side === 'right' ? '\u2192' : '\u21c4');
    const lbl = '<span class="pv-lbl' + (row.overlayLabel ? ' pv-ov' : '') + '"' +
      (row.overlayLabel ? ' title="from import"' : ' title="' + esc(p.name || p.id) + '"') + '>' + esc(row.label) + '</span>';
    const idx = '<span class="pv-idx">' + row.index + '.</span>';
    const g = '<span class="pv-glyph" aria-hidden="true">' + glyph + '</span>';
    const aria = (p.dir === 'in' ? 'Input ' : p.dir === 'out' ? 'Output ' : 'I/O ') + row.index + ', ' + row.label +
      (row.label !== p.name && p.name ? ' (' + p.name + ')' : '') + ', ' + (m.label || p.medium) + (conn ? ', connected' : ', not connected');
    let inner;
    if (side === 'left') inner = dot('l') + idx + g + lbl;
    else if (side === 'right') inner = idx + lbl + g + dot('r');
    else inner = dot('l') + idx + g + lbl + dot('r');
    return '<div class="' + cls + '" data-port="' + esc(p.id) + '" data-side="' + side + '" tabindex="-1" role="button" ' +
      'aria-label="' + esc(aria) + '" style="top:' + row.y + 'px">' + inner + '</div>';
  }

  function cardHtml(card) {
    const v = vocab();
    const d = card.device;
    const L = card.layout;
    const g = L.geom;
    const di = core.disciplineInfo(card.discipline, v);
    const cls = ['pv-card'];
    if (card.status === 'planned') cls.push('pv-planned');
    if (card.status === 'spare') cls.push('pv-spare');
    if (card.external) cls.push('pv-ext');
    if (card.auto) cls.push('pv-auto');
    if (card.dim) cls.push('pv-dim');
    const brand = d.brand && v.brands && v.brands[d.brand];
    const brandHtml = brand ? '<span class="pv-brand" style="background:' + esc(brand.bg) + ';color:' + esc(brand.fg) + '">' +
      esc(brand.text) + '</span>' : '';
    const count = typeof d.count === 'number' && d.count > 1 ? ' <span class="pv-count">\u00d7' + d.count + '</span>' : '';
    const sub = card.external ? '<div class="pv-room">\u2197 ' + esc(card.roomName) + '</div>' : '';
    const tags = (card.auto ? '<span class="pv-tag">auto</span>' : '') +
      (card.status !== 'installed' ? '<span class="pv-tag pv-tag-' + esc(card.status) + '">' + esc(card.status) + '</span>' : '');
    let rows = '';
    L.rows.forEach(function (r) { rows += rowHtml(card, r); });
    const more = L.more || {};
    Object.keys(more).forEach(function (s) {
      rows += '<button type="button" class="pv-more pv-more-' + s + '" data-side="' + s + '" style="top:' + more[s].y + 'px" ' +
        'aria-label="Show ' + more[s].n + ' more ports on ' + esc(d.name || d.id) + '">+' + more[s].n + ' more</button>';
    });
    if (L.ioTop !== null && L.ioTop !== undefined) {
      rows += '<div class="pv-iohead" style="top:' + L.ioTop + 'px" aria-hidden="true">I/O</div>';
    }
    const box = (L.rows.length || Object.keys(more).length) ?
      '<div class="pv-portsbox" style="top:' + (g.headerH) + 'px;bottom:' + (g.pad / 2) + 'px" aria-hidden="true"></div>' : '';
    const aria = (d.name || d.id) + (card.model ? ', ' + card.model : '') + ', ' + L.total + ' ports' +
      (card.external ? ', in ' + card.roomName : '') + (card.status !== 'installed' ? ', ' + card.status : '');
    return '<div class="' + cls.join(' ') + '" data-device="' + esc(card.id) + '" role="group" tabindex="0" aria-roledescription="device" ' +
      'aria-label="' + esc(aria) + '" style="transform:translate(' + card.x + 'px,' + card.y + 'px);width:' + card.w + 'px;height:' + card.h + 'px">' +
      '<div class="pv-head">' +
        '<div class="pv-headrow"><span class="pv-pill" style="color:' + esc(di.color) + ';border-color:' + hexA(di.color, 0.45) +
          ';background:' + hexA(di.color, 0.12) + '">' + esc(String(di.label || card.discipline).toUpperCase()) + '</span>' + brandHtml + tags + '</div>' +
        '<div class="pv-title">' + esc(d.name || d.id) + count + '</div>' +
        '<div class="pv-model">' + esc(card.model) + '</div>' + sub +
      '</div>' + box + rows + '</div>';
  }

  function wireSig(w) {
    return core.wirePath(w.a, w.b) + '|' + w.color + '|' + w.dash + '|' + w.width + '|' + (w.external ? 1 : 0) + (w.planned ? 1 : 0);
  }
  function wireAttrs(path, w) {
    path.setAttribute('d', core.wirePath(w.a, w.b));
    path.setAttribute('stroke', w.color);
    path.setAttribute('stroke-width', String(w.width));
    if (w.dash) path.setAttribute('stroke-dasharray', w.dash); else path.removeAttribute('stroke-dasharray');
    path.setAttribute('class', 'pv-wire' + (w.external ? ' pv-wire-ext' : '') + (w.planned ? ' pv-wire-planned' : ''));
  }
  function wireHtml(w) {
    return '<path data-cable="' + esc(w.id) + '" class="pv-wire' + (w.external ? ' pv-wire-ext' : '') +
      (w.planned ? ' pv-wire-planned' : '') + '" d="' + core.wirePath(w.a, w.b) + '" stroke="' + esc(w.color) +
      '" stroke-width="' + w.width + '"' + (w.dash ? ' stroke-dasharray="' + esc(w.dash) + '"' : '') + ' fill="none"></path>';
  }

  function rebuildScene() {
    S.scene = core.buildScene(store.doc, store.overlay, vocab(), currentFilter(),
      {positions: S.autoPos, expanded: S.expanded, geom: S.geom});
    const ap = S.scene.autoPositions;
    Object.keys(ap).forEach(function (id) { S.autoPos[id] = ap[id]; });
  }

  function mapElements() {
    S.cardEls = {};
    const cs = cardsEl.children;
    for (let i = 0; i < cs.length; i++) S.cardEls[cs[i].getAttribute('data-device')] = cs[i];
    S.wireEls = {};
    const ws = wiresG.children;
    for (let i = 0; i < ws.length; i++) S.wireEls[ws[i].getAttribute('data-cable')] = ws[i];
  }

  function focusedRef() {
    const a = doc0.activeElement;
    if (!a || !root.contains(a)) return null;
    const c = a.closest ? a.closest('.pv-card') : null;
    if (!c) return null;
    const p = a.closest('.pv-port');
    return {device: c.getAttribute('data-device'), port: p ? p.getAttribute('data-port') : null};
  }
  function restoreFocus(f) {
    if (!f) return;
    const c = S.cardEls[f.device];
    if (!c) { viewportEl.focus({preventScroll: true}); return; }
    const t = f.port ? c.querySelector('.pv-port[data-port="' + cssEsc(f.port) + '"]') : c;
    (t || c).focus({preventScroll: true});
  }

  function renderFull() {
    const f = focusedRef();
    const sc = S.scene;
    let html = '';
    S.cardHtml = {};
    sc.cards.forEach(function (c) { const s = cardHtml(c); S.cardHtml[c.id] = s; html += s; });
    cardsEl.innerHTML = html;
    let wh = '';
    S.wireSig = {};
    sc.wires.forEach(function (w) { S.wireSig[w.id] = wireSig(w); wh += wireHtml(w); });
    wiresG.innerHTML = wh;
    mapElements();
    restoreFocus(f);
  }

  function renderDiff() {
    const f = focusedRef();
    const sc = S.scene;
    const tpl = doc0.createElement('div');
    const keep = {};
    let prev = null;
    sc.cards.forEach(function (c) {
      keep[c.id] = true;
      const s = cardHtml(c);
      let node = S.cardEls[c.id];
      if (!node || S.cardHtml[c.id] !== s) {
        tpl.innerHTML = s;
        const fresh = tpl.firstChild;
        if (node) cardsEl.replaceChild(fresh, node);
        node = fresh;
        S.cardEls[c.id] = node;
        S.cardHtml[c.id] = s;
      }
      const want = prev ? prev.nextSibling : cardsEl.firstChild;
      if (want !== node) cardsEl.insertBefore(node, want);
      prev = node;
    });
    Object.keys(S.cardEls).forEach(function (id) {
      if (keep[id]) return;
      const n = S.cardEls[id];
      if (n.parentNode) n.parentNode.removeChild(n);
      delete S.cardEls[id];
      delete S.cardHtml[id];
    });
    const keepW = {};
    sc.wires.forEach(function (w) {
      keepW[w.id] = true;
      const sig = wireSig(w);
      let p = S.wireEls[w.id];
      if (!p) {
        p = doc0.createElementNS(SVG_NS, 'path');
        p.setAttribute('data-cable', w.id);
        p.setAttribute('fill', 'none');
        wiresG.appendChild(p);
        S.wireEls[w.id] = p;
      } else if (S.wireSig[w.id] === sig) return;
      wireAttrs(p, w);
      S.wireSig[w.id] = sig;
    });
    Object.keys(S.wireEls).forEach(function (id) {
      if (keepW[id]) return;
      const n = S.wireEls[id];
      if (n.parentNode) n.parentNode.removeChild(n);
      delete S.wireEls[id];
      delete S.wireSig[id];
    });
    restoreFocus(f);
  }

  function renderRoutes() {
    if (!S.showRoutes || !S.scene.routes.length) { routesG.innerHTML = ''; return; }
    let h = '';
    S.scene.routes.forEach(function (r) {
      const mx = (r.a.x + r.b.x) / 2, my = (r.a.y + r.b.y) / 2;
      h += '<path class="pv-route" d="' + core.wirePath(r.a, r.b) + '" stroke="' + esc(r.color) + '" fill="none"></path>' +
        '<text class="pv-route-lbl" x="' + Math.round(mx) + '" y="' + Math.round(my - 4) + '">' + r.count + ' ch' +
        (r.kinds.length ? ' \u00b7 ' + esc(r.kinds.join(', ')) : '') + '</text>';
    });
    routesG.innerHTML = h;
  }

  function render(full) {
    rebuildScene();
    if (full || !S.rendered) renderFull(); else renderDiff();
    S.rendered = true;
    renderRoutes();
    const n = S.scene.cards.length;
    renderEmpty(n);
    renderStale();
    const nAuto = S.scene.cards.filter(function (c) { return !c.placed && !c.auto; }).length;
    $('#pv-save-arrangement').hidden = !nAuto || ro();
    stats.cards = n;
    stats.wires = S.scene.wires.length;
    applySelection();
    applyHighlight();
    if (S.kb) markTargets(S.kb.targets, S.kb.list[S.kb.i]);
    updateToolbar();
  }

  // Filters that remove cards from the scene; the text query only dims them.
  function hasFilters() {
    const f = store.filter || {};
    return !!((f.disciplines || []).length || (f.statuses || []).length || f.system);
  }
  function clearFilters() {
    textInput.value = '';
    store.setFilter({disciplines: [], statuses: [], query: '', system: ''});
  }
  function renderEmpty(n) {
    emptyEl.hidden = n > 0;
    if (n) { S.emptyKey = null; return; }
    const filtered = hasFilters();
    const title = filtered ? 'No devices match the filters.' : 'No devices in ' + roomLabel() + ' yet.';
    const key = title + '|' + ro();
    if (S.emptyKey === key) return;
    S.emptyKey = key;
    emptyEl.innerHTML = '';
    emptyEl.appendChild(filtered
      ? emptyState({title: title, text: 'Clear the filters to see every device in ' + roomLabel() + '.',
        action: {label: 'Clear filters', run: clearFilters}})
      : emptyState({title: title, text: ro() ? '' : 'Add gear to start patching.',
        action: ro() ? null : {label: 'Add gear', run: addGear}}));
  }

  // Imported cards and network routes come from the server overlay; once the project moves on
  // (another revision) or it ages, the badge offers a refetch. Hidden while fresh.
  let stale = null;
  function overlayShown() {
    return S.scene.cards.some(function (c) { return c.auto; }) || (S.showRoutes && S.scene.routes.length > 0);
  }
  function renderStale() {
    if (typeof ctx.overlayInfo !== 'function') return;
    const shown = overlayShown();
    if (shown && !stale) {
      stale = staleBadge({
        fetchedAt: function () { return ctx.overlayInfo().fetchedAt; },
        fetchedRev: function () { return ctx.overlayInfo().revision; },
        currentRev: function () { return store.revision; },
        onRefresh: typeof ctx.refreshOverlay === 'function' ? function () {
          return Promise.resolve(ctx.refreshOverlay()).then(function () { if (stale) stale.refresh(); }, function (err) {
            toast('Could not refresh the import overlay: ' + ((err && err.message) || 'error'), 'err');
          });
        } : null,
      });
      staleHost.appendChild(stale);
    }
    staleHost.hidden = !shown;
    if (stale) stale.refresh();
  }

  // ------------------------------------------------------------ selection & highlight
  function syncSelFromStore() {
    const s = store.selection;
    S.selWire = null;
    S.selPort = null;
    if (!s) { S.sel = new Set(); return; }
    if (s.type === 'device') { if (!S.sel.has(s.id)) S.sel = new Set([s.id]); }
    else if (s.type === 'cable') { S.sel = new Set(); S.selWire = s.id; }
    else if (s.type === 'port') {
      S.sel = new Set([s.device]);
      S.selPort = s.device + ':' + s.port;
    } else S.sel = new Set();
  }
  function applySelection() {
    root.querySelectorAll('.pv-selected').forEach(function (n) { n.classList.remove('pv-selected'); });
    root.querySelectorAll('.pv-wire.pv-sel').forEach(function (n) { n.classList.remove('pv-sel'); setWireWidth(n, 1); });
    S.sel.forEach(function (id) { if (S.cardEls[id]) S.cardEls[id].classList.add('pv-selected'); });
    if (S.selPort) {
      const i = S.selPort.indexOf(':');
      const c = S.cardEls[S.selPort.slice(0, i)];
      const r = c && c.querySelector('.pv-port[data-port="' + cssEsc(S.selPort.slice(i + 1)) + '"]');
      if (r) r.classList.add('pv-selected');
    }
    if (S.selWire && S.wireEls[S.selWire]) {
      const p = S.wireEls[S.selWire];
      p.classList.add('pv-sel');
      setWireWidth(p, 1.6);
      p.parentNode.appendChild(p);
    }
  }
  function setWireWidth(p, factor) {
    const w = S.scene && S.scene.wireById[p.getAttribute('data-cable')];
    if (w) p.setAttribute('stroke-width', String(Math.round(w.width * factor * 100) / 100));
  }
  function selectDevice(id, additive) {
    if (additive) {
      if (S.sel.has(id)) S.sel.delete(id); else S.sel.add(id);
      S.selWire = null; S.selPort = null;
      applySelection();
      const first = S.sel.size ? Array.from(S.sel)[S.sel.size - 1] : null;
      ctx.select(first ? {type: 'device', id: first} : null);
      return;
    }
    S.sel = new Set([id]);
    ctx.select({type: 'device', id: id});
  }
  function selectPort(dev, port) { S.sel = new Set([dev]); ctx.select({type: 'port', id: dev + ':' + port, device: dev, port: port}); }
  function selectWire(id) { S.sel = new Set(); ctx.select({type: 'cable', id: id}); }
  function clearSelection() { S.sel = new Set(); ctx.select(null); }

  function applyHighlight() {
    const h = store.highlighted || null;
    root.querySelectorAll('.pv-hl').forEach(function (n) { n.classList.remove('pv-hl'); });
    root.classList.toggle('pv-hl-on', !!h);
    root.classList.toggle('pv-hl-ports', !!(h && h.ports && h.ports.length));
    if (!h) return;
    const devs = {};
    (h.devices || []).forEach(function (d) { devs[d] = true; });
    (h.ports || []).forEach(function (ref) {
      const i = ref.indexOf(':');
      const d = i < 0 ? ref : ref.slice(0, i);
      devs[d] = true;
      const c = S.cardEls[d];
      const r = i >= 0 && c && c.querySelector('.pv-port[data-port="' + cssEsc(ref.slice(i + 1)) + '"]');
      if (r) r.classList.add('pv-hl');
    });
    Object.keys(devs).forEach(function (d) { if (S.cardEls[d]) S.cardEls[d].classList.add('pv-hl'); });
    (h.cables || []).forEach(function (id) { if (S.wireEls[id]) S.wireEls[id].classList.add('pv-hl'); });
  }
  function clearHighlight() { if (store.highlighted) ctx.highlight(null); }

  // ------------------------------------------------------------ toolbar
  function renderChips() {
    const v = vocab();
    const f = store.filter || {};
    const active = f.disciplines || [];
    const present = {};
    (store.doc.devices || []).forEach(function (d) { present[core.deviceDiscipline(d, v)] = true; });
    let h = '';
    DISC_ORDER.forEach(function (k) {
      if (!present[k] && active.indexOf(k) < 0) return;
      const di = core.disciplineInfo(k, v);
      const on = active.indexOf(k) >= 0;
      h += '<button type="button" class="pv-chip" data-disc="' + k + '" aria-pressed="' + on + '" style="--c:' + esc(di.color) + '">' +
        '<span class="pv-chip-dot" aria-hidden="true"></span>' + esc(di.label || k) + '</button>';
    });
    $('#pv-filter-disc').innerHTML = h;
    const st = f.statuses || [];
    let hs = '';
    STATUS_ORDER.forEach(function (k) {
      hs += '<button type="button" class="pv-chip pv-chip-st" data-status="' + k + '" aria-pressed="' + (st.indexOf(k) >= 0) + '">' +
        k.charAt(0).toUpperCase() + k.slice(1) + '</button>';
    });
    $('#pv-filter-status').innerHTML = hs;
    if (doc0.activeElement !== textInput) textInput.value = f.query || '';
    syncSearch();
    const nf = (f.disciplines || []).length + st.length;
    root.querySelectorAll('.pv-menu-view .pv-menu-n, .pv-menu-more .pv-menu-n').forEach(function (s) {
      s.hidden = !nf;
      s.textContent = nf ? String(nf) : '';
    });
    $('.pv-menu-view').setAttribute('aria-label', nf ? 'View, ' + nf + ' filter' + (nf === 1 ? '' : 's') + ' on' : 'View');
    $('.pv-menu-more').setAttribute('aria-label', nf ? 'More tools, ' + nf + ' filter' + (nf === 1 ? '' : 's') + ' on' : 'More tools');
  }
  function updateToolbar() {
    const r = ro();
    root.classList.toggle('pv-ro', r);
    // Write actions are not rendered for viewers (D2); the ids stay in the DOM.
    $('#pv-add').hidden = r;
    $('.pv-pop-arrange').hidden = r;
    homes.arrange.node.hidden = r;
    homes.undo.node.hidden = r;
    $('.pv-hint').textContent = r ? 'Select gear to see its connections' : 'Drag gear \u00b7 re-patch wires \u00b7 rename anything';
    $('#pv-add').disabled = r;
    $('#pv-arrange').disabled = r;
    const u = $('#pv-undo'), re = $('#pv-redo');
    u.disabled = r || !store.canUndo;
    re.disabled = r || !store.canRedo;
    u.title = store.canUndo ? 'Undo ' + store.undoLabel + ' (\u2318Z)' : 'Undo (\u2318Z)';
    re.title = store.canRedo ? 'Redo ' + store.redoLabel + ' (\u21e7\u2318Z)' : 'Redo (\u21e7\u2318Z)';
    const f = store.filter || {};
    $('#pv-show-unconnected').setAttribute('aria-pressed', String(f.showUnconnected !== false));
    $('#pv-show-routes').setAttribute('aria-pressed', String(S.showRoutes));
    $('#pv-all-rooms').setAttribute('aria-pressed', String(S.allRooms));
    $('#pv-snap').setAttribute('aria-pressed', String(S.snapOn));
    syncExport();
  }
  // The shell announces undo/redo from the store's doc events (source 'undo' | 'redo').
  function doUndo() { if (!ro() && store.canUndo) store.undo(); }
  function doRedo() { if (!ro() && store.canRedo) store.redo(); }

  function onToolbarClick(e) {
    const a = e.target.closest ? e.target.closest('a.pv-export') : null;
    if (a) {
      // a greyed-out export does nothing; a live one downloads natively and the popover folds away
      if (a.getAttribute('aria-disabled') === 'true' || !a.getAttribute('href')) e.preventDefault();
      else closePop(false);
      return;
    }
    const b = e.target.closest ? e.target.closest('button') : null;
    if (!b || !toolbar.contains(b) || b.disabled) return;
    const id = b.id;
    const f = store.filter || {};
    if (b.hasAttribute('aria-haspopup')) {
      const wrap = b.closest('.pv-pop-wrap');
      if (S.pop && S.pop.wrap === wrap) closePop(true); else openPop(wrap);
      return;
    }
    if (b === searchToggle) { openSearch(); return; }
    if (id === 'pv-print') { printCanvas(); return; }
    if (id === 'pv-arrange' || id === 'pv-save-arrangement') closePop(true);
    if (b.hasAttribute('data-disc')) {
      const k = b.getAttribute('data-disc');
      const list = (f.disciplines || []).slice();
      const i = list.indexOf(k);
      if (i >= 0) list.splice(i, 1); else list.push(k);
      store.setFilter({disciplines: list});
    } else if (b.hasAttribute('data-status')) {
      const k = b.getAttribute('data-status');
      const list = (f.statuses || []).slice();
      const i = list.indexOf(k);
      if (i >= 0) list.splice(i, 1); else list.push(k);
      store.setFilter({statuses: list});
    } else if (id === 'pv-add') addGear();
    else if (id === 'pv-arrange') arrange();
    else if (id === 'pv-save-arrangement') saveArrangement();
    else if (id === 'pv-undo') doUndo();
    else if (id === 'pv-redo') doRedo();
    else if (id === 'pv-zoom-in') zoomBy(1.25);
    else if (id === 'pv-zoom-out') zoomBy(0.8);
    else if (id === 'pv-fit') fit();
    else if (id === 'pv-show-unconnected') store.setFilter({showUnconnected: f.showUnconnected === false});
    else if (id === 'pv-show-routes') { S.showRoutes = !S.showRoutes; renderRoutes(); updateToolbar(); }
    else if (id === 'pv-all-rooms') { S.allRooms = !S.allRooms; S.emptyKey = null; render(true); fit(); }
    else if (id === 'pv-snap') { S.snapOn = !S.snapOn; updateToolbar(); }
  }
  function onFilterInput() {
    win.clearTimeout(S.filterTimer);
    S.filterTimer = win.setTimeout(function () { store.setFilter({query: textInput.value}); }, 150);
  }

  // ------------------------------------------------------------ actions
  function addGear() {
    if (ro() || !ctx.pickTemplate) return;
    Promise.resolve(ctx.pickTemplate({})).then(function (t) {
      if (!t || S.destroyed) return;
      const sz = viewSize();
      const c = core.screenToWorld(S.view, {x: sz.w / 2, y: sz.h / 2});
      const room = currentRoom();
      const r = addDeviceFromTemplateOps(store.doc, t, {room: room === '*' ? defaultRoom() : room,
        x: core.snap(c.x - core.GEOM.cardW / 2, 8), y: core.snap(c.y - 60, 8), vocab: vocab()});
      commit(r.ops, 'Added ' + (t.name || t.model || 'gear'));
      if (r.id) { selectDevice(r.id, false); restoreFocus({device: r.id}); }
    }).catch(function (err) { toast((err && err.message) || 'Could not add gear', 'err'); });
  }
  function arrange() {
    if (ro()) return;
    const ids = S.sel.size > 1 ? Array.from(S.sel) : S.scene.cards.filter(function (c) { return !c.auto; }).map(function (c) { return c.id; });
    if (!ids.length) return;
    let origin = {x: 40, y: 40};
    if (S.sel.size > 1) {
      const b = core.boundsOf(S.scene.cards.filter(function (c) { return S.sel.has(c.id); }));
      origin = {x: b.x, y: b.y};
    }
    const heights = {};
    S.scene.cards.forEach(function (c) { heights[c.id] = c.h; });
    const ops = core.arrangeOps(store.doc, ids, vocab(), {origin: origin, heights: heights, geom: S.geom});
    commit(ops, 'Auto-arranged ' + ops.length + ' devices');
    if (S.sel.size <= 1) win.requestAnimationFrame(fit);
  }
  function saveArrangement() {
    const pos = {};
    S.scene.cards.forEach(function (c) { if (!c.placed && !c.auto) pos[c.id] = {x: c.x, y: c.y}; });
    commit(core.moveOps(store.doc, pos), 'Saved arrangement');
  }
  function duplicate(id) {
    const r = duplicateDeviceOps(store.doc, id, {});
    if (!r.ops.length) return;
    commit(r.ops, 'Duplicated ' + endName({device: id}));
    if (r.id) { selectDevice(r.id, false); restoreFocus({device: r.id}); }
  }
  function deleteDevices(ids) {
    ids = ids.filter(function (id) { return (store.doc.devices || []).some(function (d) { return d.id === id; }); });
    if (!ids.length || ro()) return;
    const names = ids.map(function (id) { return endName({device: id}); });
    const one = ids.length === 1;
    const doomed = {};
    ids.forEach(function (id) {
      deleteDeviceOps(store.doc, id).forEach(function (op) { if (op.op === 'del' && op.coll === 'cables') doomed[op.id] = true; });
    });
    const nc = Object.keys(doomed).length;
    const who = one ? 'it' : 'them';
    const detail = nc ? nc + (nc === 1 ? ' cable is' : ' cables are') + ' deleted with ' + who + '.' : 'No cables are connected to ' + who + '.';
    const asked = typeof ctx.confirm === 'function'
      ? confirmScope(ctx, {verb: 'Delete', count: one ? undefined : ids.length, noun: one ? names[0] : {one: 'device', many: 'devices'},
        scope: one ? '' : roomLabel(), danger: true, ok: one ? 'Delete' : undefined, detail: detail})
      : Promise.resolve(true);
    asked.then(function (ok) {
      if (!ok || S.destroyed) return;
      let doc = store.doc;
      const ops = [];
      const seen = {};
      // Each device's ops see the previous deletions, so marker and extra-card merges stack.
      ids.forEach(function (id) {
        const devOps = deleteDeviceOps(doc, id);
        devOps.forEach(function (op) {
          const key = op.op + op.coll + op.id;
          if (op.op === 'del' && seen[key]) return;
          seen[key] = true;
          ops.push(op);
        });
        doc = applyOps(doc, devOps).doc;
      });
      commit(ops, 'Deleted ' + (ids.length === 1 ? names[0] : ids.length + ' devices'));
      clearSelection();
      viewportEl.focus({preventScroll: true});
    });
  }
  function deleteWire(id) {
    if (ro()) return;
    const c = (store.doc.cables || []).filter(function (x) { return x.id === id; })[0];
    if (!c) return;
    commit(disconnectOps(store.doc, id), 'Disconnected ' + endName(c.from) + ' from ' + endName(c.to));
    clearSelection();
  }
  function trace(start, direction, discipline) {
    const res = core.traceLocal(store.doc, store.overlay, start, {direction: direction, discipline: discipline, vocab: vocab()});
    ctx.highlight({devices: Array.from(res.devices), ports: Array.from(res.ports), cables: Array.from(res.cables), source: 'trace'});
    announce('Traced ' + (direction === 'up' ? 'upstream' : 'downstream') + ': ' + res.cables.size + ' cables, ' + res.devices.size + ' devices');
  }
  function traceDiscipline(dev, portId) {
    if (!portId) return null;
    const p = findPortOf(findDevice(dev), portId);
    if (!p) return null;
    const k = core.mediumDiscipline(p.medium, vocab());
    return k === 'other' ? null : k;
  }
  function doConnect(from, to) {
    const chk = canConnect(store.doc, from, to, vocab());
    if (!chk.ok) { toast("Can't connect: " + chk.reason, 'err'); return false; }
    commit(connectOps(store.doc, from, to, {}, vocab()), 'Connected ' + endName(from) + ' to ' + endName(to));
    if (chk.level === 'warn') toast(chk.reason, 'warn');
    return true;
  }
  function refuseReason(a, b) {
    const c1 = canConnect(store.doc, a, b, vocab());
    if (!c1.ok) {
      const c2 = canConnect(store.doc, b, a, vocab());
      return c2.ok ? '' : c1.reason;
    }
    return '';
  }

  // ------------------------------------------------------------ connection affordances
  function markTargets(targets, current) {
    root.querySelectorAll('.pv-ok, .pv-kbtarget').forEach(function (n) { n.classList.remove('pv-ok', 'pv-kbtarget'); });
    if (!targets) { root.classList.remove('pv-connecting'); return; }
    root.classList.add('pv-connecting');
    targets.forEach(function (ref) {
      const i = ref.indexOf(':');
      const c = S.cardEls[ref.slice(0, i)];
      const r = c && c.querySelector('.pv-port[data-port="' + cssEsc(ref.slice(i + 1)) + '"]');
      if (r) { r.classList.add('pv-ok'); if (ref === current) r.classList.add('pv-kbtarget'); }
    });
  }
  function setHover(ref) {
    if (S.lastHover === ref) return;
    root.querySelectorAll('.pv-hover').forEach(function (n) { n.classList.remove('pv-hover'); });
    S.lastHover = ref;
    if (!ref) return;
    const i = ref.indexOf(':');
    const c = S.cardEls[ref.slice(0, i)];
    const r = c && c.querySelector('.pv-port[data-port="' + cssEsc(ref.slice(i + 1)) + '"]');
    if (r) r.classList.add('pv-hover');
  }
  function drawTemp(a, b) {
    if (!a) { tempPath.setAttribute('d', ''); return; }
    tempPath.setAttribute('d', core.wirePath(a, b));
  }
  function anchorOf(ref, side) {
    const i = ref.indexOf(':');
    const card = S.scene.cardById[ref.slice(0, i)];
    return card ? core.portAnchor(card, ref.slice(i + 1), side) : null;
  }

  // ------------------------------------------------------------ keyboard connect (FR-PV-09)
  function kbStart(dev, portId) {
    if (ro()) return;
    const card = S.scene.cardById[dev];
    if (!editable(card)) return;
    const p = findPortOf(card.device, portId);
    if (!p) return;
    const role = p.dir === 'in' ? 'sink' : (p.dir === 'out' ? 'source' : 'any');
    const targets = core.compatibleTargets(store.doc, S.scene, {device: dev, port: portId, role: role}, vocab());
    if (!targets.size) { toast('No compatible ports for ' + endName({device: dev, port: portId}), 'warn'); return; }
    const a = anchorOf(dev + ':' + portId, 'right');
    const list = Array.from(targets).sort(function (x, y) {
      const ax = anchorOf(x), ay = anchorOf(y);
      const dx = Math.hypot(ax.x - a.x, ax.y - a.y), dy = Math.hypot(ay.x - a.x, ay.y - a.y);
      return dx - dy || (x < y ? -1 : 1);
    });
    S.kb = {from: {device: dev, port: portId}, role: role, targets: targets, list: list, i: 0};
    kbShow();
    announce('Connecting from ' + endName(S.kb.from) + '. ' + list.length + ' compatible ports. Arrow keys choose, Enter connects, Escape cancels.');
  }
  function kbShow() {
    const kb = S.kb;
    const ref = kb.list[kb.i];
    markTargets(kb.targets, ref);
    const fromRef = kb.from.device + ':' + kb.from.port;
    const t = anchorOf(ref, 'left');
    const a = anchorOf(fromRef, t && t.x < anchorOf(fromRef, 'right').x ? 'left' : 'right');
    if (kb.role === 'sink') drawTemp(t, a); else drawTemp(a, t);
    const i = ref.indexOf(':');
    const card = S.scene.cardById[ref.slice(0, i)];
    if (card) ensureVisible(card.x, card.y, card.w, card.h);
    announce(endName({device: ref.slice(0, i), port: ref.slice(i + 1)}));
  }
  function kbCommit() {
    const kb = S.kb;
    const ref = kb.list[kb.i];
    const i = ref.indexOf(':');
    const target = {device: ref.slice(0, i), port: ref.slice(i + 1)};
    const o = core.orient(store.doc, kb.from, target, kb.role);
    kbCancel(true);
    if (o) doConnect(o.from, o.to);
  }
  function kbCancel(silent) {
    if (!S.kb) return;
    const from = S.kb.from;
    S.kb = null;
    markTargets(null);
    drawTemp(null);
    if (!silent) announce('Connection cancelled');
    const c = S.cardEls[from.device];
    const r = c && c.querySelector('.pv-port[data-port="' + cssEsc(from.port) + '"]');
    if (r) r.focus({preventScroll: true});
  }

  // ------------------------------------------------------------ inline rename (FR-PV-06)
  function startRename(dev, portId) {
    if (ro()) return;
    const card = S.scene.cardById[dev];
    if (!editable(card)) return;
    const cel = S.cardEls[dev];
    if (!cel) return;
    const target = portId ? cel.querySelector('.pv-port[data-port="' + cssEsc(portId) + '"] .pv-lbl') : cel.querySelector('.pv-title');
    if (!target) return;
    endRename(false);
    const vr = viewportEl.getBoundingClientRect();
    const tr = target.getBoundingClientRect();
    const input = doc0.createElement('input');
    input.className = 'pv-rename';
    input.type = 'text';
    const port = portId ? findPortOf(card.device, portId) : null;
    input.value = port ? (port.label || '') : (card.device.name || '');
    input.placeholder = port ? (port.name || port.id) : 'Device name';
    input.setAttribute('aria-label', port ? 'Label for ' + endName({device: dev, port: portId}) : 'Name for ' + (card.device.name || dev));
    input.style.left = Math.round(tr.left - vr.left - 4) + 'px';
    input.style.top = Math.round(tr.top - vr.top + tr.height / 2) + 'px';
    input.style.width = Math.max(140, Math.round(tr.width + 40)) + 'px';
    viewportEl.appendChild(input);
    S.rename = {input: input, dev: dev, port: portId};
    input.addEventListener('keydown', function (e) {
      e.stopPropagation();
      if (e.key === 'Enter') { e.preventDefault(); endRename(true); }
      else if (e.key === 'Escape') { e.preventDefault(); endRename(false); }
    });
    input.addEventListener('blur', function () { endRename(true); });
    input.addEventListener('pointerdown', function (e) { e.stopPropagation(); });
    input.focus();
    input.select();
  }
  function endRename(save) {
    const r = S.rename;
    if (!r) return;
    S.rename = null;
    const value = r.input.value;
    if (r.input.parentNode) r.input.parentNode.removeChild(r.input);
    if (save) {
      const d = findDevice(r.dev);
      if (r.port) {
        const ops = renameOps(store.doc, {coll: 'devices', id: r.dev, port: r.port}, value);
        commit(ops, value.trim() ? 'Labelled ' + endName({device: r.dev, port: r.port}) + ' "' + value.trim() + '"' :
          'Cleared label on ' + endName({device: r.dev, port: r.port}));
      } else if (value.trim()) {
        const ops = renameOps(store.doc, {coll: 'devices', id: r.dev}, value);
        commit(ops, 'Renamed ' + ((d && d.name) || r.dev) + ' to ' + value.trim());
      }
    }
    restoreFocus({device: r.dev, port: r.port});
  }

  // ------------------------------------------------------------ context menu (FR-PV-18)
  function openDetails(sel) {
    if (typeof ctx.openDrawer === 'function') ctx.openDrawer(sel);
    else if (ctx.openInspector) ctx.openInspector(sel);
  }
  function go(partial, legacyView, legacyParams) {
    if (typeof ctx.navigateRoute === 'function') ctx.navigateRoute(partial);
    else if (ctx.navigate) ctx.navigate(legacyView, legacyParams);
  }
  function inDoc(id) {
    return (store.doc.devices || []).some(function (d) { return d.id === id; });
  }
  function showInRack(id) {
    const d = findDevice(id);
    const rid = d && d.rack && d.rack.id;
    const rack = rid ? (store.doc.racks || []).filter(function (r) { return r.id === rid; })[0] : null;
    if (!rack) { go({view: 'racks', query: {sel: 'device:' + id}}, 'racks', {sel: 'device:' + id}); return; }
    const p = {view: 'racks', id: rid, tab: 'elevation', query: {sel: 'device:' + id}};
    if (rack.room) p.room = rack.room;
    go(p, 'racks', {sel: 'device:' + id});
  }
  function showOnPlan(id) {
    const d = findDevice(id);
    const has = function (fp) { return (fp.markers || []).some(function (m) { return m.device === id; }); };
    const fps = (store.doc.floorplans || []).filter(has);
    const fp = fps.filter(function (x) { return d && x.room === d.room; })[0] || fps[0];
    if (!fp) { go({view: 'plan', query: {sel: 'device:' + id}}, 'plan', {sel: 'device:' + id}); return; }
    const p = {view: 'plan', id: fp.id, query: {sel: 'marker:' + fp.id + ':' + id}};
    if (fp.room) p.room = fp.room;
    go(p, 'plan', {sel: 'marker:' + fp.id + ':' + id});
  }
  function menuItems(t) {
    const items = [];
    const card = t.device ? S.scene.cardById[t.device] : null;
    const canEdit = card ? editable(card) : !ro();
    if (t.type === 'cable') {
      items.push(['Open details', function () { openDetails({type: 'cable', id: t.cable}); }]);
      const w = S.scene.wireById[t.cable];
      if (w) items.push(['Trace from here', function () { trace(w.from, 'down', null); }]);
      if (!ro()) items.push(['Delete', function () { deleteWire(t.cable); }, true]);
      return items;
    }
    const devSel = {type: 'device', id: t.device};
    if (canEdit) items.push(['Rename', function () { startRename(t.device, t.port || null); }]);
    if (canEdit) items.push(['Duplicate', function () { duplicate(t.device); }]);
    if (canEdit) items.push(['Delete', function () { deleteDevices([t.device]); }, true]);
    if (canEdit) items.push(['Add port\u2026', function () { showAddPort(t.device); }, false, true]);
    if (canEdit && t.port) items.push(['Connect\u2026', function () { kbStart(t.device, t.port); }]);
    items.push(['Open details', function () {
      openDetails(t.port ? {type: 'port', id: t.device + ':' + t.port, device: t.device, port: t.port} : devSel);
    }]);
    if (inDoc(t.device)) {
      items.push(['Open device page', function () { go({view: 'devices', id: t.device}, 'devices', {sel: 'device:' + t.device}); }]);
    }
    items.push(['Show in rack', function () { showInRack(t.device); }]);
    items.push(['Show on plan', function () { showOnPlan(t.device); }]);
    const start = {device: t.device, port: t.port || null};
    items.push(['Trace from here', function () { trace(start, 'down', traceDiscipline(t.device, t.port)); }]);
    items.push(['Trace upstream', function () { trace(start, 'up', traceDiscipline(t.device, t.port)); }]);
    return items;
  }
  function openMenu(pt, t) {
    closeMenu(false);
    const items = menuItems(t);
    if (!items.length) return;
    S.menu = {target: t, items: items, opener: doc0.activeElement};
    let h = '';
    items.forEach(function (it, i) {
      h += '<button type="button" role="menuitem" class="pv-mi' + (it[2] ? ' pv-mi-danger' : '') + '" data-i="' + i + '" tabindex="-1">' +
        esc(it[0]) + '</button>';
    });
    menuEl.innerHTML = h;
    menuEl.hidden = false;
    const rr = root.getBoundingClientRect(), vr = viewportEl.getBoundingClientRect();
    let x = pt.x + vr.left - rr.left, y = pt.y + vr.top - rr.top;
    const mw = menuEl.offsetWidth, mh = menuEl.offsetHeight;
    x = Math.max(4, Math.min(x, rr.width - mw - 4));
    y = Math.max(4, Math.min(y, rr.height - mh - 4));
    menuEl.style.left = x + 'px';
    menuEl.style.top = y + 'px';
    menuEl.setAttribute('aria-label', t.type === 'cable' ? 'Cable actions' : 'Actions for ' + endName(t));
    const first = menuEl.querySelector('.pv-mi');
    if (first) first.focus();
  }
  function closeMenu(restore) {
    if (!S.menu) return;
    const opener = S.menu.opener;
    S.menu = null;
    menuEl.hidden = true;
    menuEl.innerHTML = '';
    if (restore && opener && root.contains(opener)) opener.focus({preventScroll: true});
    else if (restore) viewportEl.focus({preventScroll: true});
  }
  function onMenuClick(e) {
    const b = e.target.closest ? e.target.closest('.pv-mi') : null;
    if (!b || !S.menu) return;
    const it = S.menu.items[+b.getAttribute('data-i')];
    if (!it) return;
    if (it[3]) { it[1](); return; }
    closeMenu(true);
    it[1]();
  }
  function onMenuKey(e) {
    if (!S.menu) return;
    e.stopPropagation();
    const btns = Array.prototype.slice.call(menuEl.querySelectorAll('.pv-mi, input, select, .pv-addport-ok'));
    const i = btns.indexOf(doc0.activeElement);
    if (e.key === 'Escape') { e.preventDefault(); closeMenu(true); }
    else if (e.key === 'ArrowDown' && menuEl.querySelector('.pv-mi')) { e.preventDefault(); btns[(i + 1) % btns.length].focus(); }
    else if (e.key === 'ArrowUp' && menuEl.querySelector('.pv-mi')) { e.preventDefault(); btns[(i - 1 + btns.length) % btns.length].focus(); }
    else if (e.key === 'Tab') {
      e.preventDefault();
      btns[(i + (e.shiftKey ? -1 : 1) + btns.length) % btns.length].focus();
    }
  }
  function showAddPort(dev) {
    const v = vocab();
    const media = Object.keys(v.media || {analog: {}});
    let opts = '';
    media.forEach(function (m) {
      opts += '<option value="' + esc(m) + '">' + esc((v.media && v.media[m] && v.media[m].label) || m) + '</option>';
    });
    menuEl.innerHTML =
      '<form class="pv-addport" novalidate>' +
        '<div class="pv-addport-title">Add port to ' + esc(endName({device: dev})) + '</div>' +
        '<label>Name <input name="name" type="text" value="Input" autocomplete="off"></label>' +
        '<label>Direction <select name="dir"><option value="in">Input</option><option value="out">Output</option><option value="io">I/O</option></select></label>' +
        '<label>Medium <select name="medium">' + opts + '</select></label>' +
        '<div class="pv-addport-row"><button type="button" class="pv-btn pv-addport-cancel">Cancel</button>' +
        '<button type="submit" class="pv-btn pv-primary pv-addport-ok">Add port</button></div>' +
      '</form>';
    const form = menuEl.querySelector('form');
    form.elements.medium.value = media.indexOf('analog') >= 0 ? 'analog' : media[0];
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      const d = findDevice(dev);
      if (!d) return;
      const p = core.newPort(d, {name: form.elements.name.value, dir: form.elements.dir.value, medium: form.elements.medium.value});
      closeMenu(true);
      commit(setPortsOps(store.doc, dev, core.portsOf(d).concat([p])), 'Added port ' + p.name + ' to ' + (d.name || dev));
    });
    menuEl.querySelector('.pv-addport-cancel').addEventListener('click', function () { closeMenu(true); });
    form.elements.name.focus();
    form.elements.name.select();
  }

  // ------------------------------------------------------------ pointer handling
  function hit(pt, extra) {
    const w = core.screenToWorld(S.view, pt);
    return core.hitTest(S.scene, w, Object.assign({k: S.view.k, selectedWire: S.selWire, dotHit: coarse ? 22 : 10, grab: 12}, extra || {}));
  }
  function cancelLong() { if (S.longTimer) { win.clearTimeout(S.longTimer); S.longTimer = 0; } }

  function onPointerDown(e) {
    if (S.destroyed) return;
    if (S.rename && e.target !== S.rename.input) endRename(true);
    if (e.target.closest && e.target.closest('.pv-more, .pv-empty, .pv-stale-host')) return;
    if (S.menu) closeMenu(false);
    if (S.kb) kbCancel(true);
    if (e.pointerType === 'mouse' && e.button === 2) return;
    const pt = localPt(e);
    S.pointers[e.pointerId] = {x: pt.x, y: pt.y, type: e.pointerType};
    S.nPointers = Object.keys(S.pointers).length;
    try { viewportEl.setPointerCapture(e.pointerId); } catch (err) { /* capture is best effort */ }
    if (S.nPointers === 2) {
      cancelLong();
      cancelGesture();
      const ps = pointerList();
      S.gesture = {type: 'pinch', d0: Math.max(1, dist2(ps[0], ps[1])), m0: mid(ps[0], ps[1]), v0: {x: S.view.x, y: S.view.y, k: S.view.k}};
      return;
    }
    if (S.nPointers > 2) return;
    if (e.target.closest && e.target.closest('.pv-card') && e.pointerType !== 'mouse') e.preventDefault();
    const h = hit(pt);
    const g = {type: null, start: pt, cur: pt, hit: h, moved: false, pointerId: e.pointerId, shift: e.shiftKey,
      ptype: e.pointerType, t: perf.now()};
    if (S.space || (e.pointerType === 'mouse' && e.button === 1)) {
      g.type = 'pan';
      g.v0 = {x: S.view.x, y: S.view.y, k: S.view.k};
    } else if (h.type === 'port' && h.onDot && editable(h.card)) {
      g.type = 'wire-pending';
    } else if (h.type === 'wire-end' && !ro() && !(h.card && h.card.auto)) {
      g.type = 'repatch-pending';
    } else if (h.type === 'header' || h.type === 'card' || h.type === 'port' || h.type === 'more') {
      g.type = 'card-pending';
    } else if (h.type === 'wire') {
      g.type = 'pan';
      g.v0 = {x: S.view.x, y: S.view.y, k: S.view.k};
      g.wireClick = h.wire.id;
    } else if (e.shiftKey) {
      g.type = 'box';
    } else {
      g.type = 'pan';
      g.v0 = {x: S.view.x, y: S.view.y, k: S.view.k};
      g.bgClick = true;
    }
    S.gesture = g;
    if (e.pointerType !== 'mouse') {
      cancelLong();
      S.longTimer = win.setTimeout(function () {
        S.longTimer = 0;
        if (S.gesture !== g || g.moved) return;
        const t = menuTarget(h);
        cancelGesture();
        if (t) openMenu(pt, t);
      }, LONG_PRESS_MS);
    }
  }

  function pointerList() {
    return Object.keys(S.pointers).map(function (k) { return S.pointers[k]; });
  }
  function dist2(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }
  function mid(a, b) { return {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2}; }

  function menuTarget(h) {
    if (!h) return null;
    if (h.type === 'wire' || (h.type === 'wire-end' && !h.card)) return {type: 'cable', cable: h.wire.id};
    if (h.type === 'port' || h.type === 'wire-end') return {type: 'port', device: h.card.id, port: h.port.id};
    if (h.card) return {type: 'device', device: h.card.id};
    return null;
  }

  function beginDrag(g) {
    const h = g.hit;
    if (g.type === 'card-pending') {
      if (!editable(h.card)) { g.type = 'noop'; return; }
      const ids = S.sel.has(h.card.id) && S.sel.size > 1 ? Array.from(S.sel) : [h.card.id];
      const orig = {};
      const live = ids.filter(function (id) {
        const c = S.scene.cardById[id];
        if (!c || c.auto) return false;
        orig[id] = {x: c.x, y: c.y};
        return true;
      });
      g.type = 'card';
      g.ids = live;
      g.orig = orig;
      live.forEach(function (id) { if (S.cardEls[id]) S.cardEls[id].classList.add('pv-dragging'); });
      if (!S.sel.has(h.card.id)) selectDevice(h.card.id, false);
    } else if (g.type === 'wire-pending') {
      const p = h.port;
      const role = p.dir === 'in' ? 'sink' : (p.dir === 'out' ? 'source' : 'any');
      g.type = 'wire';
      g.from = {device: h.card.id, port: p.id};
      g.role = role;
      g.anchor = core.portAnchor(h.card, p.id, h.side);
      g.targets = core.compatibleTargets(store.doc, S.scene, {device: h.card.id, port: p.id, role: role}, vocab());
      markTargets(g.targets);
    } else if (g.type === 'repatch-pending') {
      const w = h.wire;
      const end = h.end;
      const fixed = end === 'to' ? w.from : w.to;
      g.type = 'repatch';
      g.wire = w;
      g.end = end;
      g.fixed = fixed;
      g.anchor = end === 'to' ? w.a : w.b;
      g.targets = core.compatibleTargets(store.doc, S.scene, {device: fixed.device, port: fixed.port, role: end === 'to' ? 'source' : 'sink'}, vocab());
      markTargets(g.targets);
      if (S.wireEls[w.id]) S.wireEls[w.id].classList.add('pv-moving');
    }
  }

  function onPointerMove(e) {
    if (S.destroyed) return;
    const pt = localPt(e);
    if (S.pointers[e.pointerId]) { S.pointers[e.pointerId].x = pt.x; S.pointers[e.pointerId].y = pt.y; }
    const g = S.gesture;
    if (!g) {
      if (e.pointerType === 'mouse') scheduleHover(pt);
      return;
    }
    if (g.type === 'pinch') {
      const ps = pointerList();
      if (ps.length < 2) return;
      const m = mid(ps[0], ps[1]);
      const k = core.clampK(g.v0.k * dist2(ps[0], ps[1]) / g.d0);
      const wpt = core.screenToWorld(g.v0, g.m0);
      S.view = {x: m.x - wpt.x * k, y: m.y - wpt.y * k, k: k};
      applyView();
      return;
    }
    if (e.pointerId !== g.pointerId) return;
    g.cur = pt;
    const slop = g.ptype === 'mouse' ? MOVE_SLOP : TOUCH_SLOP;
    if (!g.moved && Math.hypot(pt.x - g.start.x, pt.y - g.start.y) > slop) {
      g.moved = true;
      cancelLong();
      beginDrag(g);
    }
    if (!g.moved) return;
    if (g.type === 'pan') {
      S.view = {x: g.v0.x + pt.x - g.start.x, y: g.v0.y + pt.y - g.start.y, k: g.v0.k};
      applyView();
    } else if (g.type === 'card') {
      if (!S.raf) S.raf = win.requestAnimationFrame(dragFrame);
    } else if (g.type === 'wire' || g.type === 'repatch') {
      const w = core.screenToWorld(S.view, pt);
      const h = hit(pt, {noWireEnd: true, selectedWire: null});
      const ref = h.type === 'port' ? h.card.id + ':' + h.port.id : null;
      setHover(ref && g.targets.has(ref) ? ref : null);
      if (g.type === 'wire') {
        if (g.role === 'sink') drawTemp({x: w.x, y: w.y, side: 'right'}, g.anchor);
        else drawTemp(g.anchor, {x: w.x, y: w.y, side: 'left'});
      } else if (g.end === 'to') drawTemp(g.anchor, {x: w.x, y: w.y, side: 'left'});
      else drawTemp({x: w.x, y: w.y, side: 'right'}, g.anchor);
    } else if (g.type === 'box') {
      const x0 = Math.min(g.start.x, pt.x), y0 = Math.min(g.start.y, pt.y);
      boxEl.hidden = false;
      boxEl.style.transform = 'translate(' + x0 + 'px,' + y0 + 'px)';
      boxEl.style.width = Math.abs(pt.x - g.start.x) + 'px';
      boxEl.style.height = Math.abs(pt.y - g.start.y) + 'px';
    }
  }

  function dragFrame() {
    S.raf = 0;
    const g = S.gesture;
    if (!g || g.type !== 'card') return;
    const t = perf.now();
    let dx = (g.cur.x - g.start.x) / S.view.k, dy = (g.cur.y - g.start.y) / S.view.k;
    if (S.snapOn) {
      const lead = g.orig[g.hit.card.id] || g.orig[g.ids[0]];
      dx = core.snap(lead.x + dx, 8) - lead.x;
      dy = core.snap(lead.y + dy, 8) - lead.y;
    }
    g.ids.forEach(function (id) {
      const c = S.scene.cardById[id];
      const o = g.orig[id];
      const x = o.x + dx, y = o.y + dy;
      c.x = x; c.y = y;
      const n = S.cardEls[id];
      if (n) n.style.transform = 'translate(' + x + 'px,' + y + 'px)';
    });
    core.updateWires(S.scene, g.ids).forEach(function (w) {
      const p = S.wireEls[w.id];
      if (p) p.setAttribute('d', core.wirePath(w.a, w.b));
    });
    if (S.showRoutes && S.scene.routes.length) {
      S.scene.routes.forEach(function (r) {
        const an = core.wireAnchors(S.scene.cardById[r.from.device], r.from.port, S.scene.cardById[r.to.device], r.to.port);
        r.a = an.a; r.b = an.b;
      });
      renderRoutes();
    }
    stats.lastDragFrameMs = Math.round((perf.now() - t) * 100) / 100;
    win.__pvStats = stats;
  }

  function onPointerUp(e) {
    if (S.destroyed) return;
    const g = S.gesture;
    delete S.pointers[e.pointerId];
    S.nPointers = Object.keys(S.pointers).length;
    try { viewportEl.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
    cancelLong();
    if (!g) return;
    if (g.type === 'pinch') {
      if (S.nPointers < 2) S.gesture = null;
      return;
    }
    if (e.pointerId !== g.pointerId) return;
    S.gesture = null;
    const pt = localPt(e);
    if (!g.moved) { tap(g, pt, e); return; }
    if (g.type === 'card') {
      if (S.raf) { win.cancelAnimationFrame(S.raf); S.raf = 0; }
      g.cur = pt;
      dragFrame();
      g.ids.forEach(function (id) { if (S.cardEls[id]) S.cardEls[id].classList.remove('pv-dragging'); });
      const pos = {};
      let changed = false;
      g.ids.forEach(function (id) {
        const c = S.scene.cardById[id];
        pos[id] = {x: c.x, y: c.y};
        if (c.x !== g.orig[id].x || c.y !== g.orig[id].y) changed = true;
      });
      if (changed) {
        // Positions are already snapped as a rigid group (lead card on the grid); only round here.
        const ops = core.moveOps(store.doc, pos, 0);
        commit(ops, g.ids.length === 1 ? 'Moved ' + endName({device: g.ids[0]}) : 'Moved ' + g.ids.length + ' devices');
      }
    } else if (g.type === 'wire') {
      finishWire(g, pt);
    } else if (g.type === 'repatch') {
      finishRepatch(g, pt);
    } else if (g.type === 'box') {
      boxEl.hidden = true;
      const a = core.screenToWorld(S.view, {x: Math.min(g.start.x, pt.x), y: Math.min(g.start.y, pt.y)});
      const b = core.screenToWorld(S.view, {x: Math.max(g.start.x, pt.x), y: Math.max(g.start.y, pt.y)});
      const ids = S.scene.cards.filter(function (c) {
        return c.x < b.x && c.x + c.w > a.x && c.y < b.y && c.y + c.h > a.y;
      }).map(function (c) { return c.id; });
      S.sel = new Set(ids);
      applySelection();
      ctx.select(ids.length ? {type: 'device', id: ids[ids.length - 1]} : null);
      if (ids.length) announce(ids.length + ' devices selected');
    }
  }

  function finishWire(g, pt) {
    markTargets(null);
    setHover(null);
    drawTemp(null);
    const h = hit(pt, {noWireEnd: true, selectedWire: null});
    if (h.type !== 'port') return;
    const target = {device: h.card.id, port: h.port.id};
    const ref = target.device + ':' + target.port;
    if (g.targets.has(ref)) {
      const o = core.orient(store.doc, g.from, target, g.role);
      if (o) doConnect(o.from, o.to);
      return;
    }
    if (target.device === g.from.device && target.port === g.from.port) return;
    const reason = refuseReason(g.role === 'sink' ? target : g.from, g.role === 'sink' ? g.from : target) ||
      (h.card.auto ? 'imported devices cannot be cabled here' : 'incompatible ports');
    toast("Can't connect: " + reason, 'err');
  }

  function finishRepatch(g, pt) {
    markTargets(null);
    setHover(null);
    drawTemp(null);
    if (S.wireEls[g.wire.id]) S.wireEls[g.wire.id].classList.remove('pv-moving');
    const h = hit(pt, {noWireEnd: true, selectedWire: null});
    if (h.type !== 'port') return;
    const target = {device: h.card.id, port: h.port.id};
    const cur = g.end === 'to' ? g.wire.to : g.wire.from;
    if (cur.device === target.device && cur.port === target.port) return;
    if (!g.targets.has(target.device + ':' + target.port)) {
      const reason = g.end === 'to' ? refuseReason(g.fixed, target) : refuseReason(target, g.fixed);
      toast("Can't re-patch: " + (reason || 'incompatible ports'), 'err');
      return;
    }
    const from = g.end === 'to' ? g.fixed : target, to = g.end === 'to' ? target : g.fixed;
    const chk = canConnect(store.doc, from, to, vocab());
    if (!chk.ok) { toast("Can't re-patch: " + chk.reason, 'err'); return; }
    commit(repatchOps(store.doc, g.wire.id, g.end, target), 'Re-patched ' + endName(g.fixed) + ' to ' + endName(target));
    if (chk.level === 'warn' && chk.code !== 'port_overuse') toast(chk.reason, 'warn');
  }

  function tap(g, pt, e) {
    const h = g.hit;
    const key = (h.card ? h.card.id : '') + '|' + (h.port ? h.port.id : '') + '|' + h.type;
    const now = perf.now();
    const dbl = S.lastTap && S.lastTap.key === key && now - S.lastTap.t < 380 &&
      Math.hypot(pt.x - S.lastTap.pt.x, pt.y - S.lastTap.pt.y) < 12;
    S.lastTap = dbl ? null : {key: key, t: now, pt: pt};
    if (h.type === 'wire-end') {
      selectWire(h.wire.id);
      return;
    }
    if (g.wireClick) { selectWire(g.wireClick); return; }
    if (h.type === 'background' || g.bgClick) {
      if (store.highlighted) clearHighlight();
      if (S.sel.size || S.selWire || store.selection) clearSelection();
      return;
    }
    if (h.type === 'more') { expandCard(h.card.id); return; }
    if (h.type === 'port') {
      selectPort(h.card.id, h.port.id);
      if (dbl) startRename(h.card.id, h.port.id);
      return;
    }
    if (h.type === 'header' || h.type === 'card') {
      const additive = !!(g.shift || (e && (e.metaKey || e.ctrlKey)));
      selectDevice(h.card.id, additive);
      if (dbl && h.type === 'header') { startRename(h.card.id, null); return; }
      const n = S.cardEls[h.card.id];
      if (n && !additive && doc0.activeElement !== n) n.focus({preventScroll: true});
    }
  }

  function cancelGesture() {
    const g = S.gesture;
    S.gesture = null;
    cancelLong();
    if (!g) return;
    if (S.raf) { win.cancelAnimationFrame(S.raf); S.raf = 0; }
    if (g.type === 'card') {
      g.ids.forEach(function (id) {
        const c = S.scene.cardById[id];
        c.x = g.orig[id].x; c.y = g.orig[id].y;
        const n = S.cardEls[id];
        if (n) { n.style.transform = 'translate(' + c.x + 'px,' + c.y + 'px)'; n.classList.remove('pv-dragging'); }
      });
      core.updateWires(S.scene, g.ids).forEach(function (w) {
        const p = S.wireEls[w.id];
        if (p) p.setAttribute('d', core.wirePath(w.a, w.b));
      });
    } else if (g.type === 'wire' || g.type === 'repatch') {
      markTargets(null);
      setHover(null);
      drawTemp(null);
      if (g.wire && S.wireEls[g.wire.id]) S.wireEls[g.wire.id].classList.remove('pv-moving');
    } else if (g.type === 'box') boxEl.hidden = true;
  }
  function onPointerCancel(e) {
    delete S.pointers[e.pointerId];
    S.nPointers = Object.keys(S.pointers).length;
    if (S.gesture && (S.gesture.type === 'pinch' || S.gesture.pointerId === e.pointerId)) cancelGesture();
  }

  function scheduleHover(pt) {
    S.hoverPt = pt;
    if (S.hoverRaf) return;
    S.hoverRaf = win.requestAnimationFrame(function () {
      S.hoverRaf = 0;
      if (S.destroyed || S.gesture || !S.scene) return;
      const h = hit(S.hoverPt);
      const wid = h.type === 'wire' ? h.wire.id : null;
      if (wid !== S.hoverWire) {
        if (S.hoverWire && S.wireEls[S.hoverWire] && S.hoverWire !== S.selWire) {
          S.wireEls[S.hoverWire].classList.remove('pv-hov');
          setWireWidth(S.wireEls[S.hoverWire], 1);
        }
        S.hoverWire = wid;
        if (wid && S.wireEls[wid]) { S.wireEls[wid].classList.add('pv-hov'); setWireWidth(S.wireEls[wid], 1.6); }
      }
      let cur = '';
      if (S.space) cur = 'grab';
      else if (h.type === 'port' && h.onDot && !ro()) cur = 'crosshair';
      else if (h.type === 'wire-end' && !ro()) cur = 'move';
      else if ((h.type === 'header' || h.type === 'card') && editable(h.card)) cur = 'grab';
      else if (h.type === 'wire' || h.type === 'more' || h.type === 'port') cur = 'pointer';
      viewportEl.style.cursor = cur;
    });
  }

  function expandCard(id) {
    if (S.expanded.has(id)) S.expanded.delete(id); else S.expanded.add(id);
    render(false);
    restoreFocus({device: id});
  }

  function onClick(e) {
    const m = e.target.closest ? e.target.closest('.pv-more') : null;
    if (!m) return;
    const c = m.closest('.pv-card');
    if (c) expandCard(c.getAttribute('data-device'));
  }

  function onWheel(e) {
    e.preventDefault();
    const pt = localPt(e);
    let dy = e.deltaY, dx = e.deltaX;
    if (e.deltaMode === 1) { dy *= 16; dx *= 16; }
    else if (e.deltaMode === 2) { dy *= 400; dx *= 400; }
    if (e.ctrlKey || e.metaKey) {
      zoomBy(Math.exp(-Math.max(-60, Math.min(60, dy)) * 0.01), pt);
    } else {
      S.view = {x: S.view.x - dx, y: S.view.y - dy, k: S.view.k};
      applyView();
    }
  }
  function onGestureStart(e) { e.preventDefault(); S.gs = {k: S.view.k}; }
  function onGestureChange(e) {
    e.preventDefault();
    if (!S.gs || S.nPointers >= 2) return;
    const pt = localPt(e);
    zoomBy(core.clampK(S.gs.k * e.scale) / S.view.k, pt);
  }
  function onGestureEnd(e) { e.preventDefault(); S.gs = null; }
  function onTouchMove(e) {
    if (e.touches && e.touches.length >= 2) e.preventDefault();
    else if (S.gesture && S.gesture.moved) e.preventDefault();
  }

  function onContextMenu(e) {
    e.preventDefault();
    if (S.menu) return;
    const pt = localPt(e);
    let t = null;
    const cardEl = e.target.closest ? e.target.closest('.pv-card') : null;
    if (e.clientX === 0 && e.clientY === 0 && cardEl) {
      t = focusTarget();
      const r = (doc0.activeElement || cardEl).getBoundingClientRect(), vr = viewportEl.getBoundingClientRect();
      openMenu({x: r.left - vr.left + 20, y: r.top - vr.top + 20}, t);
      return;
    }
    t = menuTarget(hit(pt));
    if (t) {
      if (t.type === 'cable') selectWire(t.cable);
      else if (t.port) selectPort(t.device, t.port);
      else if (!S.sel.has(t.device)) selectDevice(t.device, false);
      openMenu(pt, t);
    }
  }
  function focusTarget() {
    const f = focusedRef();
    if (!f) return null;
    return f.port ? {type: 'port', device: f.device, port: f.port} : {type: 'device', device: f.device};
  }

  // ------------------------------------------------------------ keyboard
  function nudge(dx, dy) {
    const ids = Array.from(S.sel).filter(function (id) { const c = S.scene.cardById[id]; return c && editable(c); });
    if (!ids.length) return;
    const pos = {};
    ids.forEach(function (id) { const c = S.scene.cardById[id]; pos[id] = {x: c.x + dx, y: c.y + dy}; });
    commit(core.moveOps(store.doc, pos, 0), ids.length === 1 ? 'Moved ' + endName({device: ids[0]}) : 'Moved ' + ids.length + ' devices');
    const c = S.scene.cardById[ids[0]];
    if (c) ensureVisible(c.x, c.y, c.w, c.h);
  }
  function rowsOf(dev) {
    const c = S.cardEls[dev];
    return c ? Array.prototype.slice.call(c.querySelectorAll('.pv-port')) : [];
  }

  function onKeyDown(e) {
    if (S.destroyed) return;
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA')) {
      if (t === textInput && e.key === 'Escape' && textInput.value) { textInput.value = ''; store.setFilter({query: ''}); }
      return;
    }
    if (menuEl.contains(t)) return;
    const mod = e.metaKey || e.ctrlKey;
    const key = e.key;
    if (mod && (key === 'z' || key === 'Z')) { e.preventDefault(); if (e.shiftKey) doRedo(); else doUndo(); return; }
    if (mod && (key === 'y' || key === 'Y')) { e.preventDefault(); doRedo(); return; }
    if (toolbar.contains(t)) return;
    if (t && t.closest && t.closest('.pv-empty, .pv-stale-host')) return;
    if (S.kb) {
      e.preventDefault();
      if (key === 'Escape') kbCancel(false);
      else if (key === 'Enter') kbCommit();
      else if (key === 'ArrowDown' || key === 'ArrowRight' || (key === 'Tab' && !e.shiftKey)) { S.kb.i = (S.kb.i + 1) % S.kb.list.length; kbShow(); }
      else if (key === 'ArrowUp' || key === 'ArrowLeft' || key === 'Tab') { S.kb.i = (S.kb.i - 1 + S.kb.list.length) % S.kb.list.length; kbShow(); }
      return;
    }
    if (mod) return;
    const portEl = t && t.closest ? t.closest('.pv-port') : null;
    const cardEl = t && t.closest ? t.closest('.pv-card') : null;
    const dev = cardEl ? cardEl.getAttribute('data-device') : null;
    if (key === 'Escape') {
      if (S.gesture) {
        const pid = S.gesture.pointerId;
        cancelGesture();
        try { viewportEl.releasePointerCapture(pid); } catch (err) { /* not captured */ }
        e.preventDefault();
        return;
      }
      if (store.highlighted) { clearHighlight(); e.preventDefault(); return; }
      if (portEl && cardEl) { cardEl.focus({preventScroll: true}); selectDevice(dev, false); e.preventDefault(); return; }
      if (S.sel.size || S.selWire || store.selection) { clearSelection(); e.preventDefault(); }
      return;
    }
    if (key === ' ' || key === 'Spacebar') {
      if (!portEl && !(t && t.tagName === 'BUTTON')) { S.space = true; viewportEl.style.cursor = 'grab'; e.preventDefault(); }
      return;
    }
    if (key === '+' || key === '=') { zoomBy(1.25); e.preventDefault(); return; }
    if (key === '-' || key === '_') { zoomBy(0.8); e.preventDefault(); return; }
    if (key === '0') { zoomBy(1 / S.view.k); e.preventDefault(); return; }
    if (key === 'f' || key === 'F') { fit(); e.preventDefault(); return; }
    if (key === 'ContextMenu' || (key === 'F10' && e.shiftKey)) {
      const ft = focusTarget();
      if (ft) {
        const r = t.getBoundingClientRect(), vr = viewportEl.getBoundingClientRect();
        openMenu({x: r.left - vr.left + 20, y: r.top - vr.top + 20}, ft);
        e.preventDefault();
      }
      return;
    }
    if (portEl && cardEl) {
      const pid = portEl.getAttribute('data-port');
      const rows = rowsOf(dev);
      const i = rows.indexOf(portEl);
      if (key === 'ArrowDown' || key === 'ArrowUp') {
        const n = rows[(i + (key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length];
        if (n) { n.focus({preventScroll: true}); selectPort(dev, n.getAttribute('data-port')); }
        e.preventDefault();
      } else if (key === 'Enter' || key === 'F2') { startRename(dev, pid); e.preventDefault(); }
      else if (key === 'c' || key === 'C') { kbStart(dev, pid); e.preventDefault(); }
      else if (key === 't' || key === 'T') { trace({device: dev, port: pid}, e.shiftKey ? 'up' : 'down', traceDiscipline(dev, pid)); e.preventDefault(); }
      return;
    }
    if (key === 'Delete' || key === 'Backspace') {
      if (S.selWire) { deleteWire(S.selWire); e.preventDefault(); return; }
      if (S.sel.size) { deleteDevices(Array.from(S.sel)); e.preventDefault(); }
      return;
    }
    if (key === 'ArrowUp' || key === 'ArrowDown' || key === 'ArrowLeft' || key === 'ArrowRight') {
      if (cardEl && e.altKey && key === 'ArrowDown') {
        const r = rowsOf(dev)[0];
        if (r) { r.focus({preventScroll: true}); selectPort(dev, r.getAttribute('data-port')); }
        e.preventDefault();
        return;
      }
      if (!S.sel.size || ro()) return;
      const step = e.shiftKey ? 40 : 8;
      nudge(key === 'ArrowLeft' ? -step : key === 'ArrowRight' ? step : 0, key === 'ArrowUp' ? -step : key === 'ArrowDown' ? step : 0);
      e.preventDefault();
      return;
    }
    if (cardEl && (key === 'Enter' || key === 'F2')) { startRename(dev, null); e.preventDefault(); return; }
    if (cardEl && (key === 'p' || key === 'P')) {
      const r = rowsOf(dev)[0];
      if (r) { r.focus({preventScroll: true}); selectPort(dev, r.getAttribute('data-port')); }
      e.preventDefault();
      return;
    }
    if (cardEl && (key === 'd' || key === 'D') && !ro()) { duplicate(dev); e.preventDefault(); }
  }
  function onKeyUp(e) {
    if (e.key === ' ' || e.key === 'Spacebar') { S.space = false; viewportEl.style.cursor = ''; }
  }
  function onBlur() { S.space = false; }

  function onFocusIn(e) {
    const t = e.target;
    if (!t || !t.classList || S.gesture) return;
    if (t.classList.contains('pv-card')) {
      const id = t.getAttribute('data-device');
      const c = S.scene.cardById[id];
      if (c) ensureVisible(c.x, c.y, c.w, c.h);
      if (!S.sel.has(id) || S.sel.size !== 1 || S.selPort || S.selWire) {
        if (!(S.sel.has(id) && S.sel.size > 1)) selectDevice(id, false);
      }
    }
  }
  function onDocPointerDown(e) {
    if (S.menu && !menuEl.contains(e.target)) closeMenu(false);
    if (S.pop && !S.pop.wrap.contains(e.target)) closePop(false);
  }

  // ------------------------------------------------------------ store events
  function onDoc(e) {
    const d = e.detail || {};
    const touched = d.touched || [];
    if (S.gesture && S.gesture.type !== 'pan' && S.gesture.type !== 'pinch') cancelGesture();
    if (S.kb) kbCancel(true);
    const full = d.source === 'load' || touched.length > 50 ||
      touched.some(function (r) { return r.indexOf('devices/') !== 0 && r.indexOf('cables/') !== 0; });
    syncSelFromStore();
    render(full);
    if (d.source === 'load') { renderChips(); fit(); }
  }
  function onFilter() { renderChips(); render(false); urlFromStore(); }
  function onRoom() { S.autoPos = {}; S.emptyKey = null; render(true); fit(); }
  function onHighlight() { applyHighlight(); }
  function onOverlay() { render(true); }
  function onMode() { cancelGesture(); endRename(false); kbCancel(true); render(false); }
  function onSelection() { syncSelFromStore(); applySelection(); }
  function onRevision() { if (stale) stale.refresh(); }

  const storeListeners = {doc: onDoc, filter: onFilter, room: onRoom, highlight: onHighlight, overlay: onOverlay, mode: onMode, selection: onSelection,
    revision: onRevision};
  Object.keys(storeListeners).forEach(function (k) { store.addEventListener(k, storeListeners[k]); });

  const opt = {passive: false};
  toolbar.addEventListener('click', onToolbarClick);
  toolbar.addEventListener('keydown', onToolbarKey);
  toolbar.addEventListener('focusout', onToolbarFocusOut);
  textInput.addEventListener('input', onFilterInput);
  textInput.addEventListener('blur', onSearchBlur);
  offs.push(on(win, 'resize', onResize));
  offs.push(on(win, 'beforeprint', printFit));
  offs.push(on(win, 'afterprint', printRestore));
  viewportEl.addEventListener('pointerdown', onPointerDown);
  viewportEl.addEventListener('pointermove', onPointerMove);
  viewportEl.addEventListener('pointerup', onPointerUp);
  viewportEl.addEventListener('pointercancel', onPointerCancel);
  viewportEl.addEventListener('lostpointercapture', onPointerCancel);
  viewportEl.addEventListener('click', onClick);
  viewportEl.addEventListener('wheel', onWheel, opt);
  viewportEl.addEventListener('gesturestart', onGestureStart, opt);
  viewportEl.addEventListener('gesturechange', onGestureChange, opt);
  viewportEl.addEventListener('gestureend', onGestureEnd, opt);
  viewportEl.addEventListener('touchmove', onTouchMove, opt);
  viewportEl.addEventListener('contextmenu', onContextMenu);
  viewportEl.addEventListener('focusin', onFocusIn);
  root.addEventListener('keydown', onKeyDown);
  root.addEventListener('keyup', onKeyUp);
  menuEl.addEventListener('click', onMenuClick);
  menuEl.addEventListener('keydown', onMenuKey);
  win.addEventListener('blur', onBlur);
  doc0.addEventListener('pointerdown', onDocPointerDown, true);

  // ------------------------------------------------------------ first render
  // A routed URL carrying any of filter / q / status is authoritative; otherwise the store's filter
  // (kept across views in this session) is written into the URL after the first render.
  const q0 = routed() ? (ctx.route.query || {}) : null;
  const urlHasFilter = !!q0 && URL_KEYS.some(function (k) { return q0[k] != null && q0[k] !== ''; });
  if (urlHasFilter) storeFromQuery(q0);
  placeControls(layoutFor(win.innerWidth));
  syncSelFromStore();
  renderChips();
  render(true);
  fit();
  void root.offsetHeight;
  stats.renderMs = Math.round((perf.now() - t0) * 10) / 10;
  win.__pvStats = stats;
  if (!urlHasFilter) urlFromStore();

  const handle = {
    destroy: function () {
      S.destroyed = true;
      cancelGesture();
      cancelLong();
      if (S.hoverRaf) win.cancelAnimationFrame(S.hoverRaf);
      win.clearTimeout(S.filterTimer);
      Object.keys(storeListeners).forEach(function (k) { store.removeEventListener(k, storeListeners[k]); });
      win.removeEventListener('blur', onBlur);
      doc0.removeEventListener('pointerdown', onDocPointerDown, true);
      offs.forEach(function (off) { off(); });
      if (stale) stale.destroy();
      if (root.parentNode) root.parentNode.removeChild(root);
    },
    // Same-view URL change (D1): the query is authoritative, then the selection is focused as the
    // shell would do for a view without route().
    route: function (r) {
      if (S.destroyed || !r) return;
      const q = r.query || {};
      win.clearTimeout(S.filterTimer);
      storeFromQuery(q);
      if (doc0.activeElement !== textInput) textInput.value = q.q || '';
      syncSearch();
      if (store.selection) handle.focus(store.selection);
    },
    focus: function (sel) {
      if (!sel || !S.scene) return;
      let id = sel.type === 'cable' ? null : (sel.device || sel.id);
      if (sel.type === 'port' && sel.id && sel.id.indexOf(':') > 0 && !sel.device) id = sel.id.split(':')[0];
      if (sel.type === 'cable') {
        const w = S.scene.wireById[sel.id];
        if (w) {
          ensureVisible(Math.min(w.a.x, w.b.x), Math.min(w.a.y, w.b.y), Math.abs(w.b.x - w.a.x) + 1, Math.abs(w.b.y - w.a.y) + 1);
          ctx.select({type: 'cable', id: sel.id});
        }
        return;
      }
      const c = S.scene.cardById[id];
      if (!c) return;
      ensureVisible(c.x, c.y, c.w, c.h);
      if (sel.type === 'port' && (sel.port || sel.id)) {
        const pid = sel.port || sel.id.split(':')[1];
        selectPort(id, pid);
      } else if (sel.type === 'channel') {
        // a console channel lives inside the card: highlight the console, keep the channel selected
        S.sel = new Set([id]); S.selWire = null; S.selPort = null;
        applySelection();
      } else selectDevice(id, false);
      restoreFocus({device: id, port: sel.type === 'port' ? (sel.port || sel.id.split(':')[1]) : null});
    },
    getState: function () {
      return {view: {x: S.view.x, y: S.view.y, k: S.view.k}, showRoutes: S.showRoutes, allRooms: S.allRooms, snapOn: S.snapOn,
        expanded: Array.from(S.expanded)};
    },
    setState: function (s) {
      if (!s) return;
      if (s.view && typeof s.view.k === 'number') { S.view = {x: +s.view.x || 0, y: +s.view.y || 0, k: core.clampK(s.view.k)}; }
      if (typeof s.showRoutes === 'boolean') S.showRoutes = s.showRoutes;
      if (typeof s.snapOn === 'boolean') S.snapOn = s.snapOn;
      if (Array.isArray(s.expanded)) S.expanded = new Set(s.expanded);
      if (typeof s.allRooms === 'boolean' && s.allRooms !== S.allRooms) S.allRooms = s.allRooms;
      render(true);
      applyView();
    },
  };
  return handle;
}
