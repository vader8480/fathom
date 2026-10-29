// Racks view: mount(el, ctx) (§6.4, §6.7). `racks` with no id is the all-racks
// landing: the toolbar, the rack form, the unracked-devices explorer and the
// library panel built here around the elevation from rack-elevation.js.
// `racks/<id>[/<tab>[/front|rear]]` is the rack page (page-rack.js,
// docs/ui-audit.md B.3 RK), which embeds one elevation through the
// createElevation passed to it.
import { h, on } from './dom.js';
import {
  ITEM_TYPES, findRack, rackUnits, outOfRange, newRackOps, deleteRackOps, rackDevices, rackTotals, racksByRow,
  addItemOps, duplicateRackOps, firstFit, placeOps, placeOnShelfOps,
} from './rack-core.js';
import { DISPLAY_MODES, ANNOTATION_FIELDS, STORAGE, formatNumber } from './rack-display-core.js';
import { loadTemplateInfo } from './rack-display.js';
import { deviceFromTemplate } from './rack-palette-core.js';
import { mountRackPalette } from './rack-palette.js';
import { openRackExport } from './rack-export.js';
import { createElevation, roomRacks, deviceById, disciplineOf, discColor, modelLine } from './rack-elevation.js';
import { mountExplorer } from './explorer.js';
import { confirmScope, emptyState } from './feedback.js';
import { createTable } from './datatable.js';
import { mountRackPage } from './page-rack.js';

export { createElevation };

const EXTRA_CSS = ['explorer.css', 'rack.css', 'rack-toolbar.css', 'rack-palette.css'];

const FACES = [{key: 'front', label: 'Front'}, {key: 'rear', label: 'Rear'}, {key: 'both', label: 'Both'}];
const DISPLAY_LABELS = {label: 'Label', image: 'Image', both: 'Both'};
const WIDTHS_IN = [10, 19, 21, 23];
const FORM_FACTORS = [
  ['cabinet', 'Cabinet'], ['open_frame', 'Open frame'], ['two_post', 'Two-post'], ['four_post', 'Four-post'],
  ['wall_mount', 'Wall mount'], ['road_case', 'Road case'],
];
const FORM_LABELS = {};
FORM_FACTORS.forEach(function (f) { FORM_LABELS[f[0]] = f[1]; });
const SWIPE_PX = 60;
const SHORTCUTS = [
  ['i', 'Cycle the display: label, image, both'],
  ['a', 'Cycle the annotation column'],
  ['?', 'Show these shortcuts'],
  ['\u2191 / \u2193', 'Move the focused device or accessory 1 U'],
  ['Shift+\u2191 / \u2193', 'Move it 5 U'],
  ['[ / ]', 'Move it to the previous / next rack at the same U'],
  ['r', 'Flip it front \u2194 rear'],
  ['Ctrl/\u2318+D', 'Duplicate it'],
  ['Delete', 'Unrack the device, or remove the accessory'],
  ['Enter', 'Open it'],
  ['Esc', 'Clear the selection, close a menu or the library'],
  ['Alt/Option + drop', 'Force a drop onto an occupied RU'],
  ['Swipe \u2190 / \u2192', 'Next / previous rack (phone)'],
];

// The shell loads VIEWS css; the dev harness only links plan.css, so the explorer
// and rack sheets are linked next to it there.
function loadCss(ctx) {
  if (ctx && typeof ctx.ensureCss === 'function') { ctx.ensureCss(EXTRA_CSS); return; }
  if (typeof document === 'undefined') return;
  const links = Array.prototype.slice.call(document.querySelectorAll('link[rel=stylesheet]'));
  const plan = links.filter(function (l) { return /\/plan\.css(\?|$)/.test(l.href); })[0];
  if (!plan) return;
  EXTRA_CSS.forEach(function (f) {
    const href = plan.href.replace(/plan\.css(\?.*)?$/, f);
    if (links.some(function (l) { return l.href === href; })) return;
    document.head.appendChild(h('link', {rel: 'stylesheet', href: href}));
  });
}

function readPref(key, allowed, dflt) {
  try {
    const v = window.localStorage.getItem(key);
    return allowed.indexOf(v) >= 0 ? v : dflt;
  } catch (e) { return dflt; }
}

function writePref(key, value) {
  try { window.localStorage.setItem(key, value); } catch (e) { /* storage full or blocked */ }
}

function errText(e) {
  return (e && e.message) || String(e);
}

function numOrNull(v, min) {
  const t = String(v == null ? '' : v).trim();
  if (!t) return null;
  const n = Number(t);
  return isFinite(n) && n >= (min || 0) ? n : null;
}

function typeLabel(type) {
  const t = ITEM_TYPES.filter(function (x) { return x.type === type; })[0];
  return t ? t.label : type;
}

function cssId(s) {
  return String(s).replace(/["\\]/g, '\\$&');
}

// ---------------------------------------------------------------- view entry

export function mount(el, ctx) {
  loadCss(ctx);
  let mode = '';
  let inner = null;
  let landingState = null;

  function routeOf() {
    let r = null;
    try { r = ctx.route; } catch (e) { r = null; }
    return r || {view: 'racks', id: '', tab: '', sub: '', query: {}};
  }

  function show(r) {
    const next = r.id ? 'page' : 'landing';
    if (inner) {
      if (mode === 'landing' && inner.getState) landingState = inner.getState();
      inner.destroy();
    }
    el.innerHTML = '';
    mode = next;
    if (next === 'page') {
      inner = mountRackPage(el, ctx, {route: r, createElevation: createElevation});
    } else {
      inner = mountLanding(el, ctx);
      if (landingState) inner.setState(landingState);
      if (ctx.setTitle) ctx.setTitle('Racks');
    }
  }

  show(routeOf());

  return {
    route: function (r) {
      const rr = r || routeOf();
      if ((rr.id ? 'page' : 'landing') !== mode) { show(rr); return; }
      if (inner.route) inner.route(rr);
      else if (ctx.store.selection && inner.focus) inner.focus(ctx.store.selection);
    },
    destroy: function () {
      if (inner) inner.destroy();
      inner = null;
      el.innerHTML = '';
    },
    focus: function (sel) { if (inner && inner.focus) inner.focus(sel); },
    getState: function () { return mode === 'landing' && inner ? inner.getState() : landingState; },
    setState: function (s) {
      if (mode === 'landing' && inner) inner.setState(s);
      else landingState = s;
    },
    get _state() { return inner && inner._state ? inner._state : {}; },
  };
}

// ------------------------------------------------------------ landing
// Toolbar (#rk-select, #rk-add, #rk-edit, #rk-face, #rk-display, #rk-annotate,
// #rk-library, #rk-accessory, #rk-export, #rk-print, #rk-more, #rk-help), rack
// form (#rk-f-*), the unracked explorer (#rk-unracked) and the library panel
// (#rk-library-panel) around one elevation of every rack in the room. The
// elevation owns {rack, sel}; the landing owns face/display/annotate (stored
// under rack-display-core STORAGE) and passes them with setOptions. onChange
// re-syncs the toolbar and the list and decorates the racks it drew: totals
// chips, row strips (md/lg) or one rack at a time with a pager (sm).

function mountLanding(el, ctx) {
  const store = ctx.store;
  const vocab = ctx.vocab || store.vocab || {};
  const annotateKeys = ANNOTATION_FIELDS.map(function (f) { return f.key; });
  const L = {
    editing: null, listSig: '', info: {}, infoSig: '', page: '', lastSel: null, menu: null, palette: null, swipe: null, layout: '',
    face: readPref(STORAGE.face, ['front', 'rear', 'both'], 'front'),
    display: readPref(STORAGE.display, DISPLAY_MODES, 'label'),
    annotate: readPref(STORAGE.annotate, annotateKeys, ''),
  };
  const offs = [];
  let elev = null;
  let destroyed = false;
  function listen(target, type, fn, opts2) { offs.push(on(target, type, fn, opts2)); }

  el.innerHTML = '';
  const root = h('div', {class: 'rk-root rkt-root'});
  const select = h('select', {id: 'rk-select', 'aria-label': 'Rack'});
  const btnAdd = h('button', {id: 'rk-add', type: 'button', class: 'rk-btn', text: 'New rack'});
  const btnEdit = h('button', {id: 'rk-edit', type: 'button', class: 'rk-btn', text: 'Edit rack'});
  const faceSeg = segmented('rk-face', 'Face', FACES, 'Show the front, the rear or both faces');
  const displaySeg = segmented('rk-display', 'Display', DISPLAY_MODES.map(function (k) { return {key: k, label: DISPLAY_LABELS[k] || k}; }),
    'Show labels, images or both on the blocks (i)');
  const btnAnnotate = h('button', {id: 'rk-annotate', type: 'button', class: 'rk-btn rkt-annotate', 'aria-haspopup': 'menu', 'aria-expanded': 'false',
    title: 'Annotation column (a)'});
  const btnLib = h('button', {id: 'rk-library', type: 'button', class: 'rk-btn', 'aria-pressed': 'false', 'aria-controls': 'rk-library-panel', text: 'Library'});
  const btnAcc = h('button', {id: 'rk-accessory', type: 'button', class: 'rk-btn', 'aria-haspopup': 'menu', 'aria-expanded': 'false', text: 'Accessory \u25be',
    'aria-label': 'Add an accessory'});
  const btnExport = h('button', {id: 'rk-export', type: 'button', class: 'rk-btn', text: 'Export'});
  const btnPrint = h('button', {id: 'rk-print', type: 'button', class: 'rk-btn rkt-print', text: 'Print'});
  const btnMore = h('button', {id: 'rk-more', type: 'button', class: 'rk-btn rkt-icon', 'aria-haspopup': 'menu', 'aria-expanded': 'false',
    'aria-label': 'More rack tools', title: 'More rack tools', text: '\u22ef'});
  const btnHelp = h('button', {id: 'rk-help', type: 'button', class: 'rk-btn rkt-icon', 'aria-haspopup': 'dialog', 'aria-expanded': 'false',
    'aria-label': 'Rack keyboard shortcuts', title: 'Keyboard shortcuts (?)', text: '?'});
  const readout = h('span', {class: 'rk-readout', role: 'status'});
  const toolbar = h('div', {class: 'rk-toolbar rkt-bar', role: 'toolbar', 'aria-label': 'Rack tools'}, [
    h('span', {class: 'rk-group rkt-g-racks'}, [select, btnAdd, btnEdit]),
    h('span', {class: 'rk-group rkt-g-view'}, [faceSeg, displaySeg, btnAnnotate]),
    h('span', {class: 'rk-group rkt-g-tools'}, [btnLib, btnAcc, btnExport, btnPrint, btnMore, btnHelp]),
    readout,
  ]);
  const form = h('form', {class: 'rk-form rkt-form', hidden: true, 'aria-label': 'Rack'});
  const body = h('div', {class: 'rk-body rkt-body'});
  root.appendChild(toolbar);
  root.appendChild(form);
  root.appendChild(body);
  const ex = mountExplorer(body, {
    key: 'racks-unracked', title: 'Unracked devices', listId: 'rk-unracked', mobileLabel: 'Unracked',
    contentLabel: 'Rack elevations', items: [], chips: disciplineChips(),
    footer: function (shown, total) { return total ? (shown === total ? total : shown + ' of ' + total) + ' unracked' : 'Everything is racked'; },
    onSelect: function (it) { if (it && it.id) ctx.select({type: 'device', id: it.id}); },
  });
  const list = ex.list;
  list.classList.add('rk-devlist');
  const head = ex.side.querySelector('.ex-head');
  const hint = h('p', {class: 'rk-hint rk-unracked-hint', text: 'Drag by the grip onto a rack, or press Add. Drop a racked device here to unrack it. Hold Alt/Option to force a drop onto an occupied RU.'});
  if (head && head.parentNode) head.parentNode.insertBefore(hint, head.nextSibling);
  const libClose = h('button', {type: 'button', class: 'rk-btn rkt-icon rkt-lib-close', 'aria-label': 'Close the library', title: 'Close (Esc)', text: '\u00d7'});
  const libBody = h('div', {class: 'rkt-lib-body'});
  const lib = h('aside', {id: 'rk-library-panel', class: 'rkt-lib', hidden: true, 'aria-label': 'Rack library'}, [
    h('div', {class: 'rkt-lib-head'}, [h('h2', {class: 'rkt-lib-title', text: 'Library'}),
      h('span', {class: 'rkt-lib-hint', text: 'Add places it at the first free RU; drag a row onto a rack.'}), libClose]),
    libBody,
  ]);
  body.appendChild(lib);
  const btnPrev = h('button', {id: 'rk-prev', type: 'button', class: 'rk-btn rkt-icon', 'aria-label': 'Previous rack', title: 'Previous rack', text: '\u2039'});
  const btnNext = h('button', {id: 'rk-next', type: 'button', class: 'rk-btn rkt-icon', 'aria-label': 'Next rack', title: 'Next rack', text: '\u203a'});
  const pagerLabel = h('span', {class: 'rkt-pager-label', 'aria-live': 'polite'});
  const pager = h('div', {class: 'rkt-pager', hidden: true, role: 'group', 'aria-label': 'Racks'}, [btnPrev, pagerLabel, btnNext]);
  el.appendChild(root);

  function doc() { return store.doc; }
  function readOnly() { return !!store.readOnly; }
  function room() { return store.room || ''; }
  function layout() { return typeof ctx.layout === 'function' ? ctx.layout() : 'lg'; }
  function racks() {
    const out = [];
    racksByRow(roomRacks(doc(), room())).forEach(function (g) { Array.prototype.push.apply(out, g.racks); });
    return out;
  }
  function shownRack() { return elev ? elev.getState().rack : '*'; }
  function shownIds() {
    const s = shownRack();
    return s && s !== '*' ? [s] : racks().map(function (r) { return r.id; });
  }
  function commit(ops, label) {
    if (!ops || !ops.length) return false;
    if (readOnly()) { ctx.toast('Read-only: changes are not allowed here.', 'warn'); return false; }
    ctx.commit(ops, label);
    return true;
  }
  function roomName() {
    const r = room();
    if (r === '*' || !r) return 'this project';
    const m = (doc().rooms || []).filter(function (x) { return x.id === r; })[0];
    return m ? (m.name || m.id) : r;
  }
  function rackName(id) { const r = findRack(doc(), id); return r ? r.name || r.id : id; }
  function hasApi() { return !!(ctx.api && typeof ctx.api.request === 'function' && ctx.project); }
  function projPath(rest) { return 'api/v2/projects/' + encodeURIComponent(ctx.project) + rest; }

  function emptyNode() {
    const ro = readOnly();
    return h('div', {class: 'rk-empty'}, [emptyState({
      title: 'No racks in ' + roomName() + '.',
      text: ro ? '' : 'Add a rack, start from a template or import a Rackula layout, then drag devices from the unracked list onto it.',
      action: ro ? null : {label: 'Add rack', run: function () { openForm(null); }},
    })]);
  }

  // ------------------------------------------------------------ segmented
  function segmented(id, label, choices, title) {
    return h('div', {id: id, class: 'rkt-seg', role: 'group', 'aria-label': label, title: title},
      choices.map(function (c) {
        return h('button', {type: 'button', class: 'rk-btn rkt-seg-btn', 'data-value': c.key, 'aria-pressed': 'false', text: c.label});
      }));
  }

  function syncSeg(box, label, value, text) {
    Array.prototype.forEach.call(box.querySelectorAll('[data-value]'), function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-value') === value ? 'true' : 'false');
    });
    box.setAttribute('aria-label', label + ': ' + text);
  }

  // ---------------------------------------------------------- rendering
  function sync(state, api) {
    if (!elev) elev = api;
    if ((state.face === 'front' || state.face === 'rear' || state.face === 'both') && state.face !== L.face) L.face = state.face;
    renderToolbar(state);
    renderList();
    decorateRacks(state);
  }

  function renderToolbar(state) {
    const rs = racks();
    const ro = readOnly();
    const want = JSON.stringify([rs.map(function (r) { return [r.id, r.name]; }), state.rack]);
    if (select.getAttribute('data-sig') !== want) {
      select.setAttribute('data-sig', want);
      select.innerHTML = '';
      select.appendChild(h('option', {value: '*', text: rs.length ? 'All racks (' + rs.length + ')' : 'No racks in this room'}));
      rs.forEach(function (r) { select.appendChild(h('option', {value: r.id, text: r.name, selected: r.id === state.rack})); });
      select.value = state.rack || '*';
    }
    btnAdd.disabled = ro;
    btnEdit.disabled = ro || state.rack === '*';
    syncSeg(faceSeg, 'Face', L.face, L.face === 'both' ? 'front and rear' : L.face);
    syncSeg(displaySeg, 'Display', L.display, DISPLAY_LABELS[L.display] || L.display);
    const f = ANNOTATION_FIELDS.filter(function (x) { return x.key === L.annotate; })[0] || ANNOTATION_FIELDS[0];
    btnAnnotate.textContent = f.key ? 'Annotate: ' + f.label : 'Annotate';
    btnAnnotate.setAttribute('aria-label', 'Annotation column: ' + f.label);
    btnAnnotate.setAttribute('data-value', f.key);
    btnLib.hidden = ro;
    btnAcc.hidden = ro;
    btnAcc.disabled = !rs.length;
    btnExport.disabled = !rs.length;
    root.classList.toggle('rkt-ro', ro);
  }

  // #rk-unracked is the explorer list (docs/ui-audit.md B.3 RK); each option gets
  // the drag grip, a discipline dot and an Add button after the explorer renders it.
  function unracked() {
    const r = room();
    const devs = (doc().devices || []).filter(function (d) { return !d.auto && !(d.rack && d.rack.id); });
    const inRoom = devs.filter(function (d) { return r === '*' || (d.room || '') === r; });
    const shared = r && r !== '*' ? devs.filter(function (d) { return (d.room || '') === ''; }) : [];
    const roomsById = {};
    (doc().rooms || []).forEach(function (x) { roomsById[x.id] = x.name || x.id; });
    function item(d, group) {
      elev.templateInfo(d);
      return {id: d.id, label: d.name || d.id, sub: modelLine(d), group: group, disc: disciplineOf(d, vocab)};
    }
    const out = inRoom.map(function (d) {
      if (r === '*') return item(d, d.room ? roomsById[d.room] || d.room : 'Shared inventory');
      return item(d, shared.length ? roomsById[r] || r : '');
    });
    return out.concat(shared.map(function (d) { return item(d, 'Shared inventory'); }));
  }

  // explorer.js builds its chips once, so every discipline gets one at mount and syncChips shows
  // only those present in the current list (none when fewer than two are).
  function disciplineChips() {
    const ds = (vocab && vocab.disciplines) || {};
    const keys = Object.keys(ds);
    if (keys.indexOf('other') < 0) keys.push('other');
    return keys.map(function (k) { return {key: k, label: (ds[k] && ds[k].label) || k.charAt(0).toUpperCase() + k.slice(1), test: function (it) { return it.disc === k; }}; });
  }

  function syncChips(items) {
    const box = ex.side.querySelector('.ex-chips');
    if (!box) return;
    const seen = {};
    items.forEach(function (it) { seen[it.disc] = true; });
    const show = Object.keys(seen).length >= 2;
    Array.prototype.forEach.call(box.querySelectorAll('[data-chip]'), function (b) {
      const off = !show || !seen[b.getAttribute('data-chip')];
      if (off && b.getAttribute('aria-pressed') === 'true') b.click();
      b.hidden = off;
    });
    box.hidden = !show;
  }

  function renderList() {
    const items = unracked();
    const sig = JSON.stringify([items, readOnly(), racks().length]);
    if (sig === L.listSig) { decorate(); return; }
    L.listSig = sig;
    ex.setItems(items);
    syncChips(items);
    decorate();
  }

  function decorate() {
    const ro = readOnly();
    const none = !racks().length;
    Array.prototype.forEach.call(list.querySelectorAll('li.ex-item'), function (li) {
      const id = li.getAttribute('data-id');
      const d = deviceById(doc(), id);
      if (!d) return;
      const want = (ro ? 'r' : 'w') + (none ? '0' : '1');
      if (li.getAttribute('data-rk') === want) return;
      li.setAttribute('data-rk', want);
      li.classList.add('rk-devitem');
      li.setAttribute('data-device', id);
      Array.prototype.forEach.call(li.querySelectorAll('.rk-grip,.rk-addbtn,.rk-dot'), function (n) { n.parentNode.removeChild(n); });
      const a = li.querySelector('a');
      if (a) a.insertBefore(h('span', {class: 'rk-dot', 'aria-hidden': 'true', style: 'background:' + discColor(disciplineOf(d, vocab), vocab)}), a.firstChild);
      if (!ro) li.insertBefore(h('span', {class: 'rk-grip', 'data-device': id, 'aria-hidden': 'true', title: 'Drag onto a rack', text: '\u283f'}), li.firstChild);
      li.appendChild(h('button', {type: 'button', class: 'rk-btn rk-addbtn', 'data-device': id, 'aria-label': 'Add ' + d.name + ' to a rack', disabled: ro || none, text: 'Add'}));
    });
  }

  // ------------------------------------------------ rack decorations
  function viewport() { return ex.content.querySelector('.rk-viewport'); }
  function racksBox() { const v = viewport(); return v ? v.querySelector('.rk-racks') : null; }
  function sections(box) {
    return Array.prototype.filter.call(box.children, function (n) { return n.classList && n.classList.contains('rk-rack'); });
  }

  function decorateRacks(state) {
    const box = racksBox();
    if (!box) return;
    const secs = sections(box);
    loadInfo();
    secs.forEach(function (sec) { totalsChip(sec, sec.getAttribute('data-rack')); });
    const sm = layout() === 'sm';
    L.layout = layout();
    if (sm && state.rack === '*' && secs.length > 1 && !(elev && elev._state && elev._state.print)) pageRacks(box, secs);
    else {
      pager.hidden = true;
      root.classList.remove('rkt-paged');
      if (!sm) groupRows(box, secs);
    }
  }

  function loadInfo() {
    const ids = [];
    racks().forEach(function (r) {
      (doc().devices || []).forEach(function (d) { if (d.rack && d.rack.id === r.id && d.template && ids.indexOf(d.template) < 0) ids.push(d.template); });
    });
    const sig = ids.slice().sort().join(',');
    if (sig === L.infoSig) return;
    L.infoSig = sig;
    if (!ids.length) { L.info = {}; return; }
    loadTemplateInfo(ctx, ids).then(function (info) {
      if (destroyed || sig !== L.infoSig) return;
      L.info = info || {};
      const box = racksBox();
      if (box) Array.prototype.forEach.call(box.querySelectorAll('.rk-rack[data-rack]'), function (sec) { totalsChip(sec, sec.getAttribute('data-rack')); });
    });
  }

  // U free, power vs the circuit limit and weight vs the max load; over a limit is rkt-over.
  function totalsChip(sec, rackId) {
    const t = rackTotals(doc(), rackId, L.info);
    const old = sec.querySelector(':scope > .rkt-totals');
    if (old) old.parentNode.removeChild(old);
    if (!t) return;
    const parts = [h('span', {class: 'rkt-tot' + (t.free_u ? '' : ' rkt-full'), 'data-k': 'u', title: t.used_u + ' of ' + t.units + ' U used',
      text: t.free_u + ' U free'})];
    const pOver = t.power_limit_w !== null && t.power_w > t.power_limit_w;
    if (t.power_w > 0 || t.power_limit_w !== null) {
      parts.push(h('span', {class: 'rkt-tot' + (pOver ? ' rkt-over' : ''), 'data-k': 'power',
        title: pOver ? 'Over the power limit' : 'Power draw' + (t.power_limit_w !== null ? ' vs the circuit limit' : ''),
        text: formatNumber(t.power_w) + (t.power_limit_w !== null ? ' / ' + formatNumber(t.power_limit_w) : '') + ' W'}));
    }
    const wOver = t.max_load_kg !== null && t.weight_kg > t.max_load_kg;
    if (t.weight_kg > 0 || t.max_load_kg !== null) {
      parts.push(h('span', {class: 'rkt-tot' + (wOver ? ' rkt-over' : ''), 'data-k': 'weight',
        title: wOver ? 'Over the max load' : 'Weight' + (t.max_load_kg !== null ? ' vs the max load' : ''),
        text: formatNumber(t.weight_kg) + (t.max_load_kg !== null ? ' / ' + formatNumber(t.max_load_kg) : '') + ' kg'}));
    }
    const chip = h('p', {class: 'rkt-totals' + (pOver || wOver ? ' rkt-warn' : ''), 'data-rack': rackId,
      'aria-label': 'Totals: ' + parts.map(function (p) { return p.textContent; }).join(', ') + (pOver ? ', over the power limit' : '') + (wOver ? ', over the max load' : '')}, parts);
    const title = sec.querySelector(':scope > .rk-title');
    sec.insertBefore(chip, title ? title.nextSibling : sec.firstChild);
  }

  // md/lg: racks sharing a row sit in one titled, horizontally scrolling strip; the racks
  // without a row keep the wrapping layout. Nothing is wrapped while no rack has a row.
  function groupRows(box, secs) {
    const groups = racksByRow(racks());
    if (!groups.some(function (g) { return g.row; })) return;
    const byId = {};
    secs.forEach(function (s) { byId[s.getAttribute('data-rack')] = s; });
    let loose = null;
    groups.forEach(function (g) {
      const mine = g.racks.map(function (r) { return byId[r.id]; }).filter(Boolean);
      if (!mine.length) return;
      if (!g.row) {
        if (!loose) {
          loose = h('div', {class: 'rkt-strip rkt-wrap'});
          box.appendChild(h('div', {class: 'rkt-row rkt-norow'}, [loose]));
        }
        mine.forEach(function (s) { loose.appendChild(s); });
        return;
      }
      loose = null;
      const strip = h('div', {class: 'rkt-strip', role: 'group', 'aria-label': 'Row ' + g.row});
      mine.forEach(function (s) { strip.appendChild(s); });
      box.appendChild(h('div', {class: 'rkt-row', 'data-row': g.row}, [
        h('h3', {class: 'rkt-row-title'}, [g.row, h('span', {class: 'rkt-row-n', text: ' \u00b7 ' + mine.length + (mine.length === 1 ? ' rack' : ' racks')})]),
        strip,
      ]));
    });
  }

  // sm: one rack at a time. The shown one moves first (the elevation fits the width to
  // the first rack), the rest are hidden; prev/next and a horizontal swipe page.
  function pageRacks(box, secs) {
    const ids = secs.map(function (s) { return s.getAttribute('data-rack'); });
    const sel = elev && elev._state ? elev._state.sel : null;
    if (sel !== L.lastSel) {
      L.lastSel = sel;
      const d = sel && deviceById(doc(), sel);
      if (d && d.rack && ids.indexOf(d.rack.id) >= 0) L.page = d.rack.id;
    }
    if (ids.indexOf(L.page) < 0) L.page = ids[0];
    const i = ids.indexOf(L.page);
    secs.forEach(function (s) { s.hidden = s.getAttribute('data-rack') !== L.page; });
    if (box.firstChild !== secs[i]) box.insertBefore(secs[i], box.firstChild);
    root.classList.add('rkt-paged');
    const rack = findRack(doc(), L.page);
    pagerLabel.textContent = (rack && rack.row ? rack.row + ' \u00b7 ' : '') + rackName(L.page) + ' \u00b7 ' + (i + 1) + ' of ' + ids.length;
    btnPrev.disabled = i <= 0;
    btnNext.disabled = i >= ids.length - 1;
    pager.hidden = false;
    const v = viewport();
    if (v && pager.parentNode !== ex.content) ex.content.insertBefore(pager, v);
  }

  function turnPage(step) {
    const box = racksBox();
    if (!box || !root.classList.contains('rkt-paged')) return false;
    const ids = racks().map(function (r) { return r.id; }).filter(function (id) { return !!box.querySelector('.rk-rack[data-rack="' + cssId(id) + '"]'); });
    const i = ids.indexOf(L.page) + step;
    if (i < 0 || i >= ids.length) return false;
    L.page = ids[i];
    elev.render();
    return true;
  }

  // ---------------------------------------------------------- options
  function applyOptions() {
    elev.setOptions({face: L.face, display: L.display, annotate: L.annotate});
  }
  function setFace(f) {
    if (f !== 'front' && f !== 'rear' && f !== 'both') return;
    L.face = f;
    writePref(STORAGE.face, f);
    applyOptions();
  }
  function setDisplay(d) {
    if (DISPLAY_MODES.indexOf(d) < 0) return;
    L.display = d;
    writePref(STORAGE.display, d);
    applyOptions();
    announce('Display: ' + (DISPLAY_LABELS[d] || d));
  }
  function setAnnotate(k) {
    if (annotateKeys.indexOf(k) < 0) return;
    L.annotate = k;
    writePref(STORAGE.annotate, k);
    applyOptions();
    const f = ANNOTATION_FIELDS.filter(function (x) { return x.key === k; })[0];
    announce('Annotation: ' + (f ? f.label : 'None'));
  }
  function cycle(listOf, cur) { return listOf[(listOf.indexOf(cur) + 1) % listOf.length]; }
  function announce(msg) {
    const live = document.getElementById('fathom-live');
    if (live) live.textContent = msg;
    readout.textContent = msg;
  }

  // ------------------------------------------------------------ menus
  // A small popover (bottom sheet at sm) appended to <body>: `items` are
  // {label, action, checked?, disabled?, act?} | {sep} | {info}, or `opts.body` a Node.
  function popMenu(anchor, items, opts) {
    closeMenu();
    const o = opts || {};
    const sheet = layout() === 'sm';
    const menu = h('div', {class: 'rkt-menu' + (sheet ? ' rkt-sheet' : '') + (o.cls ? ' ' + o.cls : ''), role: o.body ? 'dialog' : 'menu',
      'aria-label': o.label || anchor.getAttribute('aria-label') || anchor.textContent});
    if (o.title) menu.appendChild(h('div', {class: 'rkt-menu-title', text: o.title}));
    if (o.body) menu.appendChild(o.body);
    (items || []).forEach(function (it) {
      if (it.sep) { menu.appendChild(h('div', {class: 'rkt-menu-sep', role: 'separator'})); return; }
      if (it.info) { menu.appendChild(h('div', {class: 'rkt-menu-info', text: it.info})); return; }
      const radio = typeof it.checked === 'boolean';
      menu.appendChild(h('button', {type: 'button', role: radio ? 'menuitemradio' : 'menuitem', 'aria-checked': radio ? String(it.checked) : null,
        class: 'rkt-menu-item', 'data-act': it.act || null, disabled: !!it.disabled, text: it.label,
        onclick: function () { closeMenu(true); it.action(); }}));
    });
    const back = sheet ? h('div', {class: 'rkt-menu-back'}) : null;
    if (back) document.body.appendChild(back);
    document.body.appendChild(menu);
    if (!sheet) {
      const r = anchor.getBoundingClientRect();
      const mw = menu.offsetWidth;
      const mh = menu.offsetHeight;
      let top = r.bottom + 4;
      if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 4);
      menu.style.top = top + 'px';
      menu.style.left = Math.max(8, Math.min(window.innerWidth - mw - 8, r.left)) + 'px';
    }
    anchor.setAttribute('aria-expanded', 'true');
    const M = {menu: menu, back: back, anchor: anchor, offs: []};
    L.menu = M;
    const first = menu.querySelector('[aria-checked=true]') || menu.querySelector('button:not([disabled])');
    if (first) first.focus();
    M.offs.push(on(document, 'keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeMenu(true); return; }
      if (e.key === 'Tab' && o.body) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Tab') {
        e.preventDefault();
        const bs = Array.prototype.slice.call(menu.querySelectorAll('button:not([disabled])'));
        if (!bs.length) return;
        const i = bs.indexOf(document.activeElement);
        const back2 = e.key === 'ArrowUp' || (e.key === 'Tab' && e.shiftKey);
        bs[(i + (back2 ? bs.length - 1 : 1)) % bs.length].focus();
      }
    }, true));
    // The outside-press listener waits a tick so the press that opened the menu cannot close it.
    setTimeout(function () {
      if (L.menu !== M) return;
      M.offs.push(on(document, 'pointerdown', function (e) { if (!menu.contains(e.target) && !anchor.contains(e.target)) closeMenu(); }, true));
    }, 0);
    return M;
  }

  function closeMenu(refocus) {
    const M = L.menu;
    if (!M) return;
    L.menu = null;
    M.offs.forEach(function (off) { off(); });
    if (M.menu.parentNode) M.menu.parentNode.removeChild(M.menu);
    if (M.back && M.back.parentNode) M.back.parentNode.removeChild(M.back);
    M.anchor.setAttribute('aria-expanded', 'false');
    if (refocus && M.anchor.isConnected) M.anchor.focus();
  }

  function toggleMenu(anchor, build) {
    if (L.menu && L.menu.anchor === anchor) { closeMenu(true); return; }
    build();
  }

  function annotateMenu() {
    popMenu(btnAnnotate, ANNOTATION_FIELDS.map(function (f) {
      return {label: f.label, checked: f.key === L.annotate, act: 'annotate-' + (f.key || 'none'), action: function () { setAnnotate(f.key); }};
    }), {title: 'Annotation column', label: 'Annotation column'});
  }

  function accessoryMenu() {
    popMenu(btnAcc, ITEM_TYPES.map(function (t) {
      return {label: t.label + (t.height > 1 ? ' (' + t.height + ' U)' : ''), act: 'item-' + t.type, action: function () { addAccessory(t.type); }};
    }), {title: 'Add an accessory to ' + (shownRack() !== '*' ? rackName(shownRack()) : 'a rack'), label: 'Accessories'});
  }

  function moreMenu() {
    const ro = readOnly();
    const items = [];
    if (!ro) {
      items.push({label: 'New rack from template\u2026', act: 'template', disabled: !hasApi(), action: openTemplateDialog});
      items.push({label: 'Import from Rackula\u2026', act: 'import', disabled: !hasApi(), action: openImportDialog});
      items.push({label: 'Duplicate rack\u2026', act: 'duplicate', disabled: !racks().length, action: openDuplicateDialog});
      items.push({sep: true});
    }
    items.push({label: 'Export\u2026', act: 'export', disabled: !racks().length, action: openExport});
    items.push({label: 'Print', act: 'print', action: function () { elev.print(); }});
    items.push({label: 'Keyboard shortcuts', act: 'shortcuts', action: helpPopover});
    popMenu(btnMore, items, {label: 'More rack tools'});
  }

  function helpPopover() {
    const dl = h('dl', {class: 'rkt-keys'});
    SHORTCUTS.forEach(function (s) {
      dl.appendChild(h('dt', null, h('kbd', {text: s[0]})));
      dl.appendChild(h('dd', {text: s[1]}));
    });
    const close = h('button', {type: 'button', class: 'rkt-menu-item rkt-keys-close', text: 'Close', onclick: function () { closeMenu(true); }});
    popMenu(btnHelp, [], {title: 'Rack shortcuts', label: 'Rack keyboard shortcuts', body: h('div', {class: 'rkt-keys-wrap'}, [dl, close]), cls: 'rkt-help'});
  }

  // ------------------------------------------------------ target rack
  // The rack an Add goes to: the shown rack, the only rack, the paged rack at sm, else ask.
  function targetRack(title) {
    const st = shownRack();
    if (st && st !== '*' && findRack(doc(), st)) return Promise.resolve(st);
    const rs = racks();
    if (!rs.length) { ctx.toast('Add a rack first.', 'warn'); return Promise.resolve(''); }
    if (rs.length === 1) return Promise.resolve(rs[0].id);
    if (root.classList.contains('rkt-paged') && findRack(doc(), L.page)) return Promise.resolve(L.page);
    if (typeof ctx.openDialog !== 'function') return Promise.resolve(rs[0].id);
    let dlg = null;
    const picks = h('div', {class: 'rkt-picks', role: 'list'}, rs.map(function (r) {
      const t = rackTotals(doc(), r.id, L.info) || {free_u: 0, units: rackUnits(r)};
      return h('button', {type: 'button', class: 'rkt-pick', role: 'listitem', 'data-rack': r.id,
        onclick: function () { if (dlg) dlg.close(r.id); }}, [
        h('span', {class: 'rkt-pick-name', text: r.name || r.id}),
        h('span', {class: 'rkt-pick-meta', text: rackUnits(r) + ' U \u00b7 ' + t.free_u + ' U free' + (r.row ? ' \u00b7 ' + r.row : '')}),
      ]);
    }));
    return ctx.openDialog({title: title || 'Which rack?', body: picks, buttons: [{label: 'Cancel', value: null}],
      onOpen: function (d) { dlg = d; }}).then(function (v) { return v || ''; });
  }

  // ------------------------------------------------- library palette
  function toggleLibrary(open) {
    const want = open === undefined ? lib.hidden : !!open;
    if (want && readOnly()) return;
    if (want && !L.palette) {
      L.palette = mountRackPalette(libBody, ctx, {onPick: onPick, onDragStart: onPaletteDrag});
    }
    lib.hidden = !want;
    root.classList.toggle('rkt-lib-open', want);
    btnLib.setAttribute('aria-pressed', want ? 'true' : 'false');
    if (want) { if (L.palette) L.palette.focus(); } else if (lib.contains(document.activeElement) || document.activeElement === document.body) btnLib.focus();
  }

  function fullTemplate(entry, template) {
    const t = template || (entry && entry.template) || null;
    if (t && Array.isArray(t.ports)) return Promise.resolve(t);
    if (ctx.api && typeof ctx.api.template === 'function' && entry && entry.id) {
      return Promise.resolve(ctx.api.template(entry.id, ctx.project)).then(function (x) { return x || t || entry; }, function () { return t || entry; });
    }
    return Promise.resolve(t || entry);
  }

  function onPick(entry, template) {
    targetRack('Add ' + (entry.name || entry.id) + ' to which rack?').then(function (rackId) {
      if (rackId) addFromTemplate(template || entry, rackId, null);
    });
  }

  // One commit: the deviceFromTemplate put plus its placement (first fit, or `at`).
  function addFromTemplate(template, rackId, at) {
    const rack = findRack(doc(), rackId);
    if (!rack || readOnly()) return '';
    const name = template.name || template.model || template.id;
    const res = deviceFromTemplate(doc(), template, {room: rack.room || (room() !== '*' ? room() : ''), vocab: vocab});
    const dev = res.ops[0].value;
    const tmp = Object.assign({}, doc(), {devices: (doc().devices || []).concat([dev])});
    let place = [];
    if (at && at.shelf) {
      place = placeOnShelfOps(tmp, res.id, rackId, at.shelf, at.slot);
    } else {
      const po = {face: at && at.face === 'rear' ? 'rear' : (at && at.face === 'front' ? 'front' : (L.face === 'rear' ? 'rear' : 'front'))};
      const ru = parseInt(template.ru, 10);
      po.height = ru >= 1 ? ru : 1;
      if (template.width === 'half') po.side = 'left';
      if (template.full_depth === false) po.depth = 'half';
      if (at && at.force) po.force = true;
      const u = at && at.u ? at.u : firstFit(tmp, rackId, res.id, po);
      place = u ? placeOps(tmp, res.id, rackId, u, po) : [];
    }
    if (!place.length) {
      ctx.toast(at ? name + ' does not fit there.' : 'No free space for ' + name + ' in ' + rackName(rackId) + '.', 'warn');
      return '';
    }
    if (!commit(res.ops.concat(place), 'Add ' + name + ' to ' + rackName(rackId))) return '';
    const p = place[0].value.rack;
    announce('Added ' + name + ' to ' + rackName(rackId) + (p && p.u ? ' at U' + p.u : ''));
    ctx.toast('Added ' + name + ' to ' + rackName(rackId) + '.', 'ok');
    return res.id;
  }

  // A palette row dragged onto a rack goes through the elevation's external drop; the full
  // template is fetched on drop. The md overlay and the sm sheet fade and let the pointer
  // through while the drag runs so the racks under them stay reachable.
  function onPaletteDrag(entry, ev) {
    if (!elev || readOnly() || typeof elev.beginExternalDrag !== 'function') return;
    const t = entry.template || {id: entry.id, name: entry.name, manufacturer: entry.manufacturer, model: entry.model, kind: entry.kind,
      ru: entry.ru, width: entry.width, full_depth: entry.full_depth};
    if (!elev.beginExternalDrag({kind: 'template', entry: entry, template: t}, ev) || layout() === 'lg') return;
    root.classList.add('rkt-lib-dragging');
    const offs2 = [];
    function done() {
      root.classList.remove('rkt-lib-dragging');
      offs2.splice(0).forEach(function (off) { off(); });
    }
    ['pointerup', 'pointercancel'].forEach(function (type) { offs2.push(on(document, type, done, true)); });
    offs2.push(on(document, 'keydown', function (e) { if (e.key === 'Escape') done(); }, true));
  }

  function onExternalDrop(payload, at) {
    if (!payload || !at || !at.rackId || readOnly()) return;
    if (payload.kind === 'item') {
      const spec = {type: payload.type};
      if (at.u) spec.u = at.u;
      if (at.face) spec.face = at.face;
      if (at.force) spec.force = true;
      const r = addItemOps(doc(), at.rackId, spec);
      if (!r.ops.length) { ctx.toast(typeLabel(payload.type) + ' does not fit there.', 'warn'); return; }
      commit(r.ops, 'Add ' + typeLabel(payload.type) + ' to ' + rackName(at.rackId));
      return;
    }
    if (payload.kind === 'template') {
      fullTemplate(payload.entry, payload.template).then(function (t) {
        if (!destroyed) addFromTemplate(t, at.rackId, at);
      });
    }
  }

  // -------------------------------------------------------- accessories
  function addAccessory(type) {
    if (readOnly()) return;
    targetRack('Add a ' + typeLabel(type).toLowerCase() + ' to which rack?').then(function (rackId) {
      if (!rackId) return;
      const spec = {type: type};
      if (L.face === 'rear') spec.face = 'rear';
      const r = addItemOps(doc(), rackId, spec);
      if (!r.ops.length) { ctx.toast('No free space for a ' + typeLabel(type).toLowerCase() + ' in ' + rackName(rackId) + '.', 'warn'); return; }
      if (commit(r.ops, 'Add ' + typeLabel(type) + ' to ' + rackName(rackId))) {
        const it = (findRack(doc(), rackId).items || []).filter(function (x) { return x.id === r.id; })[0];
        announce('Added ' + typeLabel(type) + ' to ' + rackName(rackId) + (it ? ' at U' + it.u : ''));
        ctx.toast('Added ' + typeLabel(type).toLowerCase() + ' to ' + rackName(rackId) + '.', 'ok');
      }
    });
  }

  function openExport() {
    openRackExport(ctx, {racks: shownIds(), face: L.face});
  }

  // ------------------------------------------------- server workflows
  function serverPost(path, bodyObj) {
    const flush = ctx.flush ? Promise.resolve(ctx.flush()).catch(function () { return null; }) : Promise.resolve();
    return flush.then(function () {
      return ctx.api.request('POST', projPath(path), Object.assign({}, bodyObj, {base_revision: store.revision}));
    }).then(function (r) { return r.data; });
  }

  function reloadDoc() {
    return Promise.resolve(typeof ctx.reload === 'function' ? ctx.reload() : null).catch(function () { return null; });
  }

  function openTemplateDialog() {
    if (!hasApi() || readOnly() || typeof ctx.openDialog !== 'function') return;
    let chosen = '';
    let tpls = [];
    const listBox = h('div', {class: 'rkt-tpls', role: 'radiogroup', 'aria-label': 'Rack template'}, [h('p', {class: 'rkt-muted', text: 'Loading templates\u2026'})]);
    const name = h('input', {id: 'rkt-tpl-name', type: 'text', placeholder: 'Default: the template name', autocomplete: 'off'});
    const locs = (doc().locations || []).filter(function (l) { return !room() || room() === '*' || !l.room || l.room === room(); });
    const loc = h('select', {id: 'rkt-tpl-location'}, [h('option', {value: '', text: '\u2014'})].concat(locs.map(function (l) { return h('option', {value: l.id, text: l.name}); })));
    const err = h('p', {class: 'rkt-err', role: 'alert', hidden: true});
    const bodyEl = h('div', {class: 'rkt-dlg rkt-tpl-dlg'}, [
      listBox,
      h('div', {class: 'rkt-dlg-fields'}, [
        h('label', {class: 'rkt-dlg-field', for: 'rkt-tpl-name'}, [h('span', {text: 'Rack name'}), name]),
        locs.length ? h('label', {class: 'rkt-dlg-field', for: 'rkt-tpl-location'}, [h('span', {text: 'Location'}), loc]) : null,
      ]),
      h('p', {class: 'rkt-muted', text: 'Creates the rack in ' + roomName() + ' with planned placeholder devices and accessories; rename and replace them later.'}),
      err,
    ]);
    function render() {
      listBox.innerHTML = '';
      if (!tpls.length) { listBox.appendChild(h('p', {class: 'rkt-muted', text: 'No rack templates are available.'})); return; }
      tpls.forEach(function (t, i) {
        const id = 'rkt-tpl-' + i;
        const meta = [t.units + ' U', (t.width_in || 19) + '\u2033', FORM_LABELS[t.form_factor] || t.form_factor].filter(Boolean).join(' \u00b7 ');
        listBox.appendChild(h('label', {class: 'rkt-tpl', for: id, 'data-template': t.id}, [
          h('input', {type: 'radio', name: 'rkt-tpl', id: id, value: t.id, checked: t.id === chosen,
            onchange: function () { chosen = t.id; err.hidden = true; }}),
          h('span', {class: 'rkt-tpl-text'}, [
            h('span', {class: 'rkt-tpl-name', text: t.name || t.id}),
            h('span', {class: 'rkt-tpl-meta', text: meta}),
            t.description ? h('span', {class: 'rkt-tpl-desc', text: t.description}) : null,
          ]),
        ]));
      });
    }
    ctx.openDialog({
      title: 'New rack from template', wide: true, body: bodyEl,
      buttons: [{label: 'Cancel', value: null}, {label: 'Create rack', primary: true,
        validate: function () { if (chosen) return true; err.textContent = 'Pick a template.'; err.hidden = false; return false; },
        value: function () { return {template: chosen, name: name.value.trim(), location: loc.value}; }}],
      onOpen: function () {
        ctx.api.request('GET', 'api/v2/rack-templates').then(function (r) {
          tpls = (r.data && r.data.templates) || [];
          if (tpls.length && !chosen) chosen = tpls[0].id;
          render();
        }, function (e) {
          listBox.innerHTML = '';
          listBox.appendChild(h('p', {class: 'rkt-err', role: 'alert', text: 'Could not load the rack templates: ' + errText(e)}));
        });
      },
    }).then(function (v) {
      if (!v || !v.template) return;
      const t = tpls.filter(function (x) { return x.id === v.template; })[0];
      const label = v.name || (t && t.name) || v.template;
      const req = {template: v.template, room: room() === '*' ? '' : room()};
      if (v.name) req.name = v.name;
      if (v.location) req.location = v.location;
      serverPost('/racks/from-template', req).then(function (res) {
        return reloadDoc().then(function () {
          if (destroyed) return;
          if (res && res.rack && findRack(doc(), res.rack)) elev.setState({rack: res.rack});
          ctx.toast('Created ' + (res && res.rack ? rackName(res.rack) : label) + ' from a template.', 'ok');
        });
      }, function (e) { ctx.toast('Could not create the rack: ' + errText(e), 'err'); });
    });
  }

  function readFile(file) {
    return new Promise(function (resolve, reject) {
      const zip = /\.zip$/i.test(file.name) || file.type === 'application/zip';
      const fr = new FileReader();
      fr.onerror = function () { reject(fr.error || new Error('Could not read ' + file.name)); };
      fr.onload = function () {
        if (!zip) { resolve({text: String(fr.result || '')}); return; }
        const bytes = new Uint8Array(fr.result);
        let bin = '';
        for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
        resolve({zip_b64: btoa(bin)});
      };
      if (zip) fr.readAsArrayBuffer(file); else fr.readAsText(file);
    });
  }

  // The server files imported racks in this room; without one (all rooms) it uses the first room.
  function importRoom() {
    const r = room();
    return r && r !== '*' ? {room: r} : {};
  }

  // A share link (http… or a bare encoded string) goes as `url`, anything else as `text`.
  function pastedPayload(s) {
    const t = s.trim();
    if (!t) return null;
    if (/^https?:\/\//i.test(t) || (!/\s/.test(t) && !/[:{}[\]]/.test(t) && t.length > 16)) return {url: t};
    return {text: t};
  }

  function openImportDialog() {
    if (!hasApi() || readOnly() || typeof ctx.openDialog !== 'function') return;
    const file = h('input', {id: 'rkt-imp-file', type: 'file', accept: '.yaml,.yml,.json,.zip'});
    const paste = h('textarea', {id: 'rkt-imp-text', rows: '3', spellcheck: 'false', autocomplete: 'off',
      placeholder: 'https://count.racku.la/?l=\u2026 or the layout YAML'});
    const status = h('p', {class: 'rkt-muted rkt-imp-status', role: 'status'});
    const out = h('div', {class: 'rkt-imp-out'});
    const tables = [];
    let D = null;
    let preview = null;
    let payload = null;
    let busy = false;
    const bodyEl = h('div', {class: 'rkt-dlg rkt-imp-dlg'}, [
      h('label', {class: 'rkt-dlg-field', for: 'rkt-imp-file'}, [h('span', {text: 'Layout file (.yaml, .json or .Rackula.zip)'}), file]),
      h('label', {class: 'rkt-dlg-field', for: 'rkt-imp-text'}, [h('span', {text: 'Or paste a share link or the layout'}), paste]),
      status, out,
    ]);
    function footBtn(i) { return D ? D.box.querySelectorAll('footer button')[i] : null; }
    function setStage(previewed) {
      const pv = footBtn(1);
      const ap = footBtn(2);
      if (!pv || !ap) return;
      ap.hidden = !previewed;
      pv.className = previewed ? '' : 'primary';
      ap.className = 'primary';
      pv.textContent = previewed ? 'Preview again' : 'Preview';
    }
    function clearOut() {
      tables.splice(0).forEach(function (t) { t.destroy(); });
      out.innerHTML = '';
    }
    function invalidate() { preview = null; setStage(false); clearOut(); status.textContent = ''; }
    function source() {
      if (file.files && file.files[0]) return readFile(file.files[0]);
      const p = pastedPayload(paste.value);
      return p ? Promise.resolve(p) : Promise.reject(new Error('Choose a file or paste a share link first.'));
    }
    function runPreview() {
      if (busy) return;
      busy = true;
      invalidate();
      status.textContent = 'Reading the layout\u2026';
      source().then(function (p) {
        payload = p;
        return ctx.api.request('POST', projPath('/racks/import'), Object.assign(importRoom(), p));
      }).then(function (r) {
        busy = false;
        preview = r.data || {};
        renderPreview(preview);
        setStage(true);
      }, function (e) {
        busy = false;
        status.textContent = '';
        out.appendChild(h('p', {class: 'rkt-err', role: 'alert', text: 'Could not read that layout: ' + errText(e)}));
      });
    }
    function renderPreview(p) {
      clearOut();
      const rs = p.racks || [];
      const ds = p.devices || [];
      const its = p.items || [];
      const fresh = ds.filter(function (d) { return d.new !== false; }).length;
      status.textContent = rs.length + (rs.length === 1 ? ' rack, ' : ' racks, ') + ds.length + (ds.length === 1 ? ' device' : ' devices')
        + (ds.length ? ' (' + fresh + ' new, ' + (ds.length - fresh) + ' reused)' : '') + ', ' + its.length + (its.length === 1 ? ' accessory' : ' accessories') + '.';
      const warns = p.warnings || [];
      if (warns.length) {
        out.appendChild(h('ul', {class: 'rkt-warns', 'aria-label': 'Import warnings'}, warns.map(function (w) { return h('li', {text: String(w)}); })));
      }
      const rackHost = h('div', {class: 'rkt-imp-table' + (rs.length <= 25 ? ' rkt-onepage' : ''), 'data-table': 'racks'});
      out.appendChild(rackHost);
      tables.push(createTable(rackHost, {
        key: 'racks.import.racks', caption: 'Racks', noun: {one: 'rack', many: 'racks'}, persist: false, search: false, csv: false, pageSize: 25,
        rows: rs.map(function (r) { return Object.assign({}, r, {id: r.id}); }),
        columns: [
          {key: 'name', header: 'Rack', sticky: true},
          {key: 'units', header: 'U', value: function (r) { return r.units; }},
          {key: 'width_in', header: 'Width', value: function (r) { return (r.width_in || 19) + '\u2033'; }},
          {key: 'form_factor', header: 'Form', value: function (r) { return FORM_LABELS[r.form_factor] || r.form_factor || ''; }},
          {key: 'row', header: 'Row', value: function (r) { return r.row || ''; }},
          {key: 'devices', header: 'Devices', value: function (r) { return r.devices; }},
          {key: 'items', header: 'Accessories', value: function (r) { return r.items; }},
        ],
      }));
      if (ds.length) {
        const devHost = h('div', {class: 'rkt-imp-table' + (ds.length <= 25 ? ' rkt-onepage' : ''), 'data-table': 'devices'});
        out.appendChild(devHost);
        tables.push(createTable(devHost, {
          key: 'racks.import.devices', caption: 'Devices', noun: {one: 'device', many: 'devices'}, persist: false, search: false, csv: false, pageSize: 25,
          rows: ds.map(function (d) { return Object.assign({}, d); }),
          columns: [
            {key: 'name', header: 'Device', sticky: true},
            {key: 'model', header: 'Model', value: function (d) { return ((d.manufacturer || '') + ' ' + (d.model || '')).trim(); }},
            {key: 'rack', header: 'Rack', value: function (d) { const r = rs.filter(function (x) { return x.id === d.rack; })[0]; return r ? r.name : d.rack || ''; }},
            {key: 'u', header: 'U', value: function (d) { return d.shelf ? 'shelf ' + d.shelf : (d.u ? d.u + (d.height > 1 ? '\u2013' + (d.u + d.height - 1) : '') : ''); }},
            {key: 'face', header: 'Face', hideOnMobile: true},
            {key: 'new', header: 'Status', value: function (d) { return d.new === false ? 'Reuses an unracked device' : 'New'; }},
          ],
        }));
      }
    }
    file.addEventListener('change', function () { if (file.files && file.files[0]) paste.value = ''; invalidate(); });
    paste.addEventListener('input', function () { if (paste.value && file.value) file.value = ''; invalidate(); });
    ctx.openDialog({
      title: 'Import from Rackula', wide: true, body: bodyEl,
      buttons: [
        {label: 'Cancel', value: null},
        {label: 'Preview', primary: true, validate: function () { runPreview(); return false; }, value: null},
        {label: 'Apply', primary: true, validate: function () { return !!preview && !busy; }, value: 'apply'},
      ],
      onOpen: function (d) { D = d; setStage(false); },
      onClose: function () { tables.splice(0).forEach(function (t) { t.destroy(); }); },
    }).then(function (v) {
      if (v !== 'apply' || !preview || !payload) return;
      const p = preview;
      serverPost('/racks/import', Object.assign({apply: true}, importRoom(), payload)).then(function (res) {
        return reloadDoc().then(function () {
          if (destroyed) return;
          const n = (p.racks || []).length;
          const w = (res && res.warnings) || [];
          ctx.toast('Imported ' + n + (n === 1 ? ' rack' : ' racks') + ' and ' + (p.devices || []).length + ' devices from Rackula'
            + (w.length ? ' (' + w.length + (w.length === 1 ? ' warning' : ' warnings') + ')' : '') + '.', w.length ? 'warn' : 'ok');
          if (n === 1 && findRack(doc(), p.racks[0].id)) elev.setState({rack: p.racks[0].id});
        });
      }, function (e) { ctx.toast('Could not import: ' + errText(e), 'err'); });
    });
  }

  function openDuplicateDialog() {
    if (readOnly()) return;
    const rs = racks();
    if (!rs.length) return;
    const st = shownRack();
    const cur = st !== '*' ? st : (root.classList.contains('rkt-paged') ? L.page : rs[0].id);
    const pick = h('select', {id: 'rkt-dup-rack'}, rs.map(function (r) { return h('option', {value: r.id, text: r.name || r.id, selected: r.id === cur}); }));
    const withDevs = h('input', {id: 'rkt-dup-devices', type: 'checkbox', checked: true});
    const bodyEl = h('div', {class: 'rkt-dlg'}, [
      h('label', {class: 'rkt-dlg-field', for: 'rkt-dup-rack'}, [h('span', {text: 'Rack'}), pick]),
      h('label', {class: 'rkt-check', for: 'rkt-dup-devices'}, [withDevs, h('span', {text: 'Include its devices (copies without serials, asset tags or addresses)'})]),
    ]);
    const go = function () { return {rack: pick.value, devices: withDevs.checked}; };
    const done = function (v) {
      if (!v || !v.rack) return;
      const res = duplicateRackOps(doc(), v.rack, {devices: v.devices});
      if (commit(res.ops, 'Duplicated rack ' + rackName(v.rack))) {
        ctx.toast('Duplicated ' + rackName(v.rack) + ' as ' + rackName(res.id) + '.', 'ok');
        if (shownRack() !== '*') elev.setState({rack: res.id});
        else L.page = res.id;
      }
    };
    if (typeof ctx.openDialog !== 'function') { done({rack: cur, devices: true}); return; }
    ctx.openDialog({title: 'Duplicate rack', body: bodyEl,
      buttons: [{label: 'Cancel', value: null}, {label: 'Duplicate', primary: true, value: go}]}).then(done);
  }

  // ------------------------------------------------------- rack editing
  function rowNames() {
    const seen = {};
    const out = [];
    (doc().racks || []).forEach(function (r) { if (r && r.row && !seen[r.row]) { seen[r.row] = true; out.push(String(r.row)); } });
    return out.sort();
  }

  function openForm(rack) {
    closeMenu();
    L.editing = rack ? rack.id : '';
    form.innerHTML = '';
    const locs = (doc().locations || []).filter(function (l) { return !room() || room() === '*' || !l.room || l.room === room(); });
    const name = h('input', {id: 'rk-f-name', type: 'text', required: true, value: rack ? rack.name : 'Rack ' + (racks().length + 1)});
    const units = h('input', {id: 'rk-f-units', type: 'number', inputmode: 'numeric', min: '1', max: '60', required: true, value: String(rack ? rackUnits(rack) : 12)});
    const numbering = h('select', {id: 'rk-f-numbering'}, [
      h('option', {value: 'bottom_up', text: 'Bottom up (U1 at the bottom)', selected: !rack || rack.numbering !== 'top_down'}),
      h('option', {value: 'top_down', text: 'Top down (U1 at the top)', selected: !!rack && rack.numbering === 'top_down'}),
    ]);
    const loc = h('select', {id: 'rk-f-location'}, [h('option', {value: '', text: '\u2014'})].concat(locs.map(function (l) {
      return h('option', {value: l.id, text: l.name, selected: !!rack && rack.location === l.id});
    })));
    const notes = h('input', {id: 'rk-f-notes', type: 'text', value: rack && rack.notes ? rack.notes : ''});
    const curW = rack && WIDTHS_IN.indexOf(parseInt(rack.width_in, 10)) >= 0 ? parseInt(rack.width_in, 10) : 19;
    const width = h('select', {id: 'rk-f-width'}, WIDTHS_IN.map(function (w) { return h('option', {value: String(w), text: w + '\u2033', selected: w === curW}); }));
    const curF = rack && FORM_LABELS[rack.form_factor] ? rack.form_factor : 'cabinet';
    const formF = h('select', {id: 'rk-f-form'}, FORM_FACTORS.map(function (f) { return h('option', {value: f[0], text: f[1], selected: f[0] === curF}); }));
    const startU = h('input', {id: 'rk-f-start', type: 'number', inputmode: 'numeric', min: '0', step: '1',
      value: String(rack && parseInt(rack.start_u, 10) >= 0 ? parseInt(rack.start_u, 10) : 1)});
    function numInput(id, v, step) { return h('input', {id: id, type: 'number', inputmode: 'decimal', min: '0', step: step || 'any', value: v == null ? '' : String(v), placeholder: '\u2014'}); }
    const weight = numInput('rk-f-weight', rack && rack.weight_kg);
    const maxLoad = numInput('rk-f-maxload', rack && rack.max_load_kg);
    const power = numInput('rk-f-power', rack && rack.power_limit_w);
    const rowList = h('datalist', {id: 'rk-f-rows'}, rowNames().map(function (r) { return h('option', {value: r}); }));
    const row = h('input', {id: 'rk-f-row', type: 'text', list: 'rk-f-rows', autocomplete: 'off', value: rack && rack.row ? rack.row : '', placeholder: 'e.g. Bay A'});
    function field(id, label, input) { return h('div', {class: 'rk-field'}, [h('label', {for: id, text: label}), input]); }
    form.appendChild(h('h3', {text: rack ? 'Edit ' + rack.name : 'New rack'}));
    form.appendChild(field('rk-f-name', 'Name', name));
    form.appendChild(field('rk-f-units', 'Units (1\u201360)', units));
    form.appendChild(field('rk-f-numbering', 'Numbering', numbering));
    form.appendChild(field('rk-f-location', 'Location', loc));
    form.appendChild(field('rk-f-row', 'Row / bay', row));
    form.appendChild(rowList);
    form.appendChild(h('div', {class: 'rkt-formgrid'}, [
      field('rk-f-width', 'Width', width),
      field('rk-f-form', 'Form factor', formF),
      field('rk-f-start', 'Label of RU 1', startU),
      field('rk-f-weight', 'Empty weight (kg)', weight),
      field('rk-f-maxload', 'Max load (kg)', maxLoad),
      field('rk-f-power', 'Power limit (W)', power),
    ]));
    form.appendChild(field('rk-f-notes', 'Notes', notes));
    const btns = h('div', {class: 'rk-formrow'}, [
      h('button', {type: 'submit', class: 'rk-btn rk-primary', text: rack ? 'Save' : 'Create rack'}),
      h('button', {type: 'button', class: 'rk-btn', 'data-act': 'cancel', text: 'Cancel'}),
      rack ? h('button', {type: 'button', class: 'rk-btn rk-danger', 'data-act': 'delete', text: 'Delete rack'}) : null,
    ]);
    form.appendChild(btns);
    form.hidden = false;
    name.focus();
    name.select();
  }

  function closeForm(focusEl) {
    form.hidden = true;
    form.innerHTML = '';
    L.editing = null;
    (focusEl || btnAdd).focus();
  }

  // Rackula fields at their default are left out (null removes them on edit).
  function extraFields(v) {
    const w = parseInt(v('rk-f-width'), 10);
    const s = parseInt(v('rk-f-start'), 10);
    const f = v('rk-f-form');
    return {
      width_in: WIDTHS_IN.indexOf(w) >= 0 && w !== 19 ? w : null,
      form_factor: FORM_LABELS[f] && f !== 'cabinet' ? f : null,
      start_u: s >= 0 && s !== 1 ? s : null,
      weight_kg: numOrNull(v('rk-f-weight')),
      max_load_kg: numOrNull(v('rk-f-maxload')),
      power_limit_w: numOrNull(v('rk-f-power')),
      row: v('rk-f-row').trim() || null,
    };
  }

  function onFormSubmit(e) {
    e.preventDefault();
    const v = function (id) { const n = form.querySelector('#' + id); return n ? n.value : ''; };
    const units = Math.max(1, Math.min(60, parseInt(v('rk-f-units'), 10) || 12));
    const spec = {name: v('rk-f-name').trim() || 'Rack', units: units, numbering: v('rk-f-numbering'), location: v('rk-f-location'), notes: v('rk-f-notes').trim(),
      room: room() === '*' ? '' : room()};
    const extra = extraFields(v);
    if (L.editing) {
      const rack = findRack(doc(), L.editing);
      const value = Object.assign({name: spec.name, units: units, numbering: spec.numbering === 'top_down' ? 'top_down' : null,
        location: spec.location || null, notes: spec.notes || null}, extra);
      commit([{op: 'merge', coll: 'racks', id: rack.id, value: value}], 'Edited rack ' + spec.name);
      if (outOfRange(doc(), rack.id).length) ctx.toast('Some devices are now outside the rack.', 'warn');
      closeForm(btnEdit);
    } else {
      const res = newRackOps(doc(), spec);
      Object.keys(extra).forEach(function (k) { if (extra[k] !== null) res.ops[0].value[k] = extra[k]; });
      commit(res.ops, 'Created rack ' + spec.name);
      closeForm(btnAdd);
      elev.setState({rack: res.id});
    }
  }

  function onFormClick(e) {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    if (b.getAttribute('data-act') === 'cancel') closeForm();
    if (b.getAttribute('data-act') === 'delete') {
      const rack = findRack(doc(), L.editing);
      const n = rackDevices(doc(), rack.id).length;
      confirmScope(ctx, {
        verb: 'Delete', noun: rack.name, danger: true, ok: 'Delete rack',
        detail: n ? n + (n === 1 ? ' device becomes' : ' devices become') + ' unracked.' : 'The rack is empty.',
      }).then(function (ok) {
        if (!ok) return;
        commit(deleteRackOps(doc(), rack.id), 'Deleted rack ' + rack.name);
        closeForm(btnAdd);
        elev.setState({rack: '*'});
      });
    }
  }

  // ------------------------------------------------------------- events
  listen(select, 'change', function () { elev.setState({rack: select.value}); });
  listen(btnAdd, 'click', function () { openForm(null); });
  listen(btnEdit, 'click', function () { const r = findRack(doc(), shownRack()); if (r) openForm(r); });
  // A click on a segment picks it; a click on the group itself (keyboard or script) flips front/rear.
  listen(faceSeg, 'click', function (e) {
    const b = e.target.closest('[data-value]');
    if (b && faceSeg.contains(b)) setFace(b.getAttribute('data-value'));
    else setFace(L.face === 'front' ? 'rear' : 'front');
  });
  listen(displaySeg, 'click', function (e) {
    const b = e.target.closest('[data-value]');
    setDisplay(b && displaySeg.contains(b) ? b.getAttribute('data-value') : cycle(DISPLAY_MODES, L.display));
  });
  listen(btnAnnotate, 'click', function () { toggleMenu(btnAnnotate, annotateMenu); });
  listen(btnLib, 'click', function () { toggleLibrary(); });
  listen(libClose, 'click', function () { toggleLibrary(false); btnLib.focus(); });
  listen(lib, 'keydown', function (e) { if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); toggleLibrary(false); btnLib.focus(); } });
  listen(btnAcc, 'click', function () { toggleMenu(btnAcc, accessoryMenu); });
  listen(btnExport, 'click', openExport);
  listen(btnPrint, 'click', function () { elev.print(); });
  listen(btnMore, 'click', function () { toggleMenu(btnMore, moreMenu); });
  listen(btnHelp, 'click', function () { toggleMenu(btnHelp, helpPopover); });
  listen(btnPrev, 'click', function () { turnPage(-1); });
  listen(btnNext, 'click', function () { turnPage(1); });
  listen(form, 'submit', onFormSubmit);
  listen(form, 'click', onFormClick);
  listen(form, 'keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); closeForm(); } });
  listen(list, 'pointerdown', function (e) {
    const g = e.target.closest('.rk-grip');
    if (g && !readOnly()) elev.startDrag(e, g.getAttribute('data-device'), true, g);
  });
  // The Add buttons sit inside explorer options: keep their clicks and keys from activating the option.
  listen(list, 'click', function (e) {
    const b = e.target.closest('.rk-addbtn');
    if (!b) return;
    e.stopPropagation();
    if (!b.disabled) elev.addToRack(b.getAttribute('data-device'), root.classList.contains('rkt-paged') ? L.page : undefined);
  }, true);
  listen(list, 'keydown', function (e) {
    if (e.target.closest && e.target.closest('.rk-addbtn') && (e.key === 'Enter' || e.key === ' ')) e.stopPropagation();
  }, true);
  // Landing shortcuts: i (display), a (annotation), ? (shortcuts); not while typing or in a dialog.
  listen(document, 'keydown', function (e) {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    // Focus falls back to <body> after a dialog opened from the library closes.
    if (e.key === 'Escape' && !lib.hidden && (!t || t === document.body) && !L.menu && !document.querySelector('.app-dialog-backdrop')) {
      e.preventDefault();
      toggleLibrary(false);
      btnLib.focus();
      return;
    }
    if (e.key !== 'i' && e.key !== 'a' && e.key !== '?') return;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
    if (t && t !== document.body && !root.contains(t)) return;
    if (t && t.closest && t.closest('.rkt-lib, .rkt-menu')) return;
    if (document.querySelector('.app-dialog-backdrop, #app-palette') || !form.hidden) return;
    e.preventDefault();
    if (e.key === 'i') setDisplay(cycle(DISPLAY_MODES, L.display));
    else if (e.key === 'a') setAnnotate(cycle(annotateKeys, L.annotate));
    else toggleMenu(btnHelp, helpPopover);
  });
  // sm pager: a horizontal swipe of SWIPE_PX on the rack background (not a block drag).
  function swipeStart(e) {
    if (!root.classList.contains('rkt-paged') || (e.pointerType === 'mouse' && e.button > 0)) return;
    if (e.target.closest('.rk-block,.rk-item,button,select,input,a,textarea')) return;
    L.swipe = {id: e.pointerId, x: e.clientX, y: e.clientY};
  }
  function swipeEnd(e) {
    const s = L.swipe;
    if (!s || s.id !== e.pointerId) return;
    L.swipe = null;
    if (elev && elev._state && elev._state.drag) return;
    const dx = e.clientX - s.x;
    const dy = e.clientY - s.y;
    if (Math.abs(dx) >= SWIPE_PX && Math.abs(dx) > Math.abs(dy) * 1.5) turnPage(dx < 0 ? 1 : -1);
  }
  listen(document, 'pointerup', swipeEnd);
  listen(document, 'pointercancel', function () { L.swipe = null; });
  listen(window, 'resize', function () {
    if (layout() === L.layout || !elev) return;
    if (layout() !== 'sm' && L.menu) closeMenu();
    elev.render();
  });
  if (typeof MutationObserver === 'function') {
    const mo = new MutationObserver(function () { decorate(); });
    mo.observe(list, {childList: true});
    offs.push(function () { mo.disconnect(); });
  }

  elev = createElevation(ex.content, ctx, {
    root: root,
    racks: racks,
    face: L.face,
    empty: emptyNode,
    onChange: sync,
    onExternalDrop: onExternalDrop,
    list: {
      el: list,
      onLift: function () { ex.close({focus: false}); },
      focus: function () { const b = list.querySelector('.rk-addbtn'); if (b) b.focus(); },
    },
  });
  const vp = viewport();
  if (vp) listen(vp, 'pointerdown', swipeStart);
  applyOptions();

  return {
    destroy: function () {
      destroyed = true;
      closeMenu();
      if (L.palette) L.palette.destroy();
      elev.destroy();
      offs.forEach(function (off) { off(); });
      ex.destroy();
      el.innerHTML = '';
    },
    route: function (r) { elev.route(r); },
    focus: function (sel) { elev.focus(sel); },
    getState: function () { const s = elev.getState(); return {rack: s.rack, face: L.face, page: L.page}; },
    setState: function (s) {
      if (!s) return;
      if (s.page) L.page = s.page;
      if (s.face === 'front' || s.face === 'rear' || s.face === 'both') L.face = s.face;
      elev.setState({rack: s.rack || '*'});
      applyOptions();
    },
    print: function (done) { elev.print(done); },
    elevation: elev,
    get _state() { return elev._state; },
  };
}
