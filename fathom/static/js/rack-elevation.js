// Rack elevation (§6.7, docs/ui-audit.md B.3 RK): one or more racks drawn as
// front/rear faces with device blocks, accessories (rack items) and shelf
// cells, the drag ghost, drag within and between racks and from/to a device
// list, external drops (library palette), keyboard moves, the block menu,
// selection and cable highlight, fit-to-width and print. rack.js builds the
// landing chrome (toolbar, rack form, unracked explorer) around it;
// page-rack.js embeds one rack.
//
// createElevation(el, ctx, opts); every opts key is optional:
//   rack      one rack id: embedded mode (.rk-embedded, no title links, focus()
//             ignores other racks, setState() ignores `rack`).
//   racks     () -> the racks to draw without `rack` (default: roomRacks for the
//             store room); state.rack '*' draws them all, an id draws that one.
//   face      'front' | 'rear' | 'both' (default front). Both draws the faces
//             side by side at md/lg; at sm it draws the last single face with a
//             .rk-facetoggle button per rack.
//   display   'label' | 'image' | 'both' (default label); annotate: an
//             ANNOTATION_FIELDS key ('' = none). Both also come via setOptions.
//   root      an existing .rk-root to style (rk-readonly, rk-printing, --rk-ru,
//             --rk-w) and hold the ghost; `el` then gets only the viewport.
//             Without it the elevation creates its own .rk-root inside `el`.
//   list      {el, accept(e)?, onLift()?, focus()?}: a device list that starts
//             drags (call startDrag) and takes drops. Pointer moves/ups on `el`
//             feed the drag; a racked device dropped where accept(e) is true
//             (default: inside el's box) is unracked, and `el` has
//             .rk-droptarget while one hovers. onLift() runs when a drag from
//             the list first moves; focus() runs after Delete unracks a block
//             (without `list`, the first block takes focus).
//   empty     () -> Node drawn when there is no rack to show.
//   onChange  (state, api) after every render; state is getState().
//   onExternalDrop  (payload, {rackId, u, face, shelf?, slot?, force?}) when an
//             external drag (beginExternalDrag) is dropped on a free spot; the
//             host creates the device or item.
// Returns {render, destroy, setFace(face), getState() -> {rack, face, display,
//   annotate}, setState({rack?, face?}), setOptions(o), focus(sel), route(r),
//   startDrag(e, deviceId, fromList, grabEl), beginExternalDrag(payload, e),
//   openMenu(target), closeMenu(), print(done), addToRack(deviceId, rackId?),
//   addDevice(), templateInfo(dev), _state}. setOptions sets `face` and `rack`
//   like setState and merges every other key into _state.options (`display`,
//   `annotate` are read from there), then renders. The viewport element carries
//   the api as `__rkElevation` (tests, dev tools).
//
// Blocks: div.rk-block[data-device][data-rack] (racked devices),
// div.rk-block.rk-onshelf[data-device][data-shelf][data-slot] (devices on a
// shelf cell) and div.rk-item[data-item][data-rack][data-type] (accessories).
// Keys on a focused block: ↑/↓ move 1 RU (Shift: 5, Alt: force), Delete
// unracks / removes, Enter opens the device (inspector) or the item menu,
// Ctrl/Cmd+D duplicates, r flips front/rear, [ / ] move to the previous/next
// rack at the same U, ←/→ move a shelf device between cells, Shift+F10 or the
// context-menu key opens the block menu (also right-click, a 500 ms press or
// the ⋯ button).
import { h, on } from './dom.js';
import { layoutFor } from './router-core.js';
import {
  RU_PX, RACK_W, ITEM_TYPES, findRack, rackUnits, heightOf, placement, faceBlocks, itemBlocks, shelfChildBlocks,
  shelfCells, rackItems, collisions, outOfRange, fits, itemFits, placeOps, unplaceOps, firstFit, uToY, yToU, ruLabel,
  rackWidthPx, addItemOps, moveItemOps, updateItemOps, delItemOps, placeOnShelfOps, duplicateDeviceOps,
} from './rack-core.js';
import {
  DISPLAY_MODES, ANNOTATION_FIELDS, CATEGORY_COLORS, blockColor, deviceImage, annotationValue, airflowGlyph, textColorOn,
} from './rack-display-core.js';
import { loadTemplateInfo } from './rack-display.js';
import { confirmScope } from './feedback.js';

const DRAG_SLOP = 4;
const MIN_RACK_W = 200;
const MIN_RACK_W_TIGHT = 120;
const LONG_PRESS_MS = 500;
const SHELF_LIP = 5;
const ITEM_PREFIX = 'item:';
const EXT_ID = '\u0000external';
const FACE_MODES = ['front', 'rear', 'both'];
const MAX_SHELF_CHOICES = 8;

const TYPE_BY = {};
ITEM_TYPES.forEach(function (t) { TYPE_BY[t.type] = t; });

// One swatch per distinct category colour, named after its first category.
const SWATCHES = (function () {
  const seen = {};
  const out = [];
  Object.keys(CATEGORY_COLORS).forEach(function (k) {
    const c = CATEGORY_COLORS[k].toLowerCase();
    if (seen[c]) return;
    seen[c] = true;
    out.push({color: c, label: k.replace(/-/g, ' ')});
  });
  return out;
})();

export function disciplineOf(dev, vocab) {
  if (dev.discipline) return dev.discipline;
  const k = vocab && vocab.kinds && vocab.kinds[dev.kind];
  return (k && k.discipline) || 'other';
}

export function discColor(disc, vocab) {
  return blockColor({discipline: disc, kind: ''}, vocab, null);
}

export function deviceById(doc, id) {
  const ds = (doc && doc.devices) || [];
  for (let i = 0; i < ds.length; i++) if (ds[i].id === id) return ds[i];
  return null;
}

export function modelLine(dev) {
  return ((dev.manufacturer || '') + ' ' + (dev.model || '')).trim() || dev.sub || '';
}

// Racks of a room ('*' or '' = all) in `order`.
export function roomRacks(doc, room) {
  return ((doc && doc.racks) || []).filter(function (k) { return room === '*' || !room || (k.room || '') === room; })
    .slice().sort(function (a, b) { return (a.order == null ? 1e9 : a.order) - (b.order == null ? 1e9 : b.order); });
}

// 44 px per RU on coarse pointers (FR-MOB-02); geometry from rack-core is scaled by ruScale().
function ruScale() {
  return typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches ? 2 : 1;
}

// Blocks are positioned in % of their rack's drawn width (rackWidthPx).
function pct(px, rack) {
  return (px / rackWidthPx(rack) * 100) + '%';
}

// The slot width: --rk-w is the fitted width of a 19" rack; other widths scale with it.
function slotWidthCss(w) {
  return w === RACK_W ? 'var(--rk-w, ' + RACK_W + 'px)' : 'calc(var(--rk-w, ' + RACK_W + 'px) * ' + (w / RACK_W).toFixed(4) + ')';
}

function px(v) {
  return parseFloat(v) || 0;
}

function cssq(s) {
  return String(s).replace(/["\\]/g, '\\$&');
}

function normFace(f) {
  return FACE_MODES.indexOf(f) >= 0 ? f : 'front';
}

function otherFace(f) {
  return f === 'rear' ? 'front' : 'rear';
}

function typeLabel(type) {
  return (TYPE_BY[type] || TYPE_BY.other).label;
}

export function createElevation(el, ctx, opts) {
  const o = opts || {};
  const embedded = !!o.rack;
  const store = ctx.store;
  const vocab = ctx.vocab || store.vocab || {};
  const lst = o.list && o.list.el ? o.list : null;
  const list = lst ? lst.el : null;
  const S = {
    rack: embedded ? o.rack : '*', face: normFace(o.face), single: o.face === 'rear' ? 'rear' : 'front',
    sel: null, selItem: null, print: false, drag: null, ext: null, press: null, menu: null,
    tpl: {}, info: {}, infoReq: {}, highlight: null, w: 0, layout: '', dead: false, options: {},
  };
  if (o.display) S.options.display = o.display;
  if (o.annotate) S.options.annotate = o.annotate;
  const offs = [];
  function listen(target, type, fn, opts2) { offs.push(on(target, type, fn, opts2)); }

  const ownRoot = !o.root;
  const root = o.root || h('div', {class: 'rk-root' + (embedded ? ' rk-embedded' : '')});
  const racksEl = h('div', {class: 'rk-racks'});
  const viewport = h('div', {class: 'rk-viewport', role: 'application', 'aria-label': 'Rack elevations. Tab to a device or accessory; arrow up and down move it one RU, Delete unracks or removes it, Enter opens it, Shift+F10 opens its menu.'}, [racksEl]);
  const ghost = h('div', {class: 'rk-ghost', hidden: true, 'aria-hidden': 'true'});
  if (ownRoot) {
    root.appendChild(viewport);
    root.appendChild(ghost);
    el.appendChild(root);
  } else {
    el.appendChild(viewport);
    root.appendChild(ghost);
  }

  function doc() { return store.doc; }
  function readOnly() { return !!store.readOnly; }
  function layout() {
    if (typeof ctx.layout === 'function') return ctx.layout();
    return layoutFor(typeof window !== 'undefined' ? window.innerWidth : 1280);
  }
  function racks() {
    if (embedded) { const k = findRack(doc(), S.rack); return k ? [k] : []; }
    if (typeof o.racks === 'function') return o.racks() || [];
    return roomRacks(doc(), store.room || '');
  }
  function shownRacks() {
    const rs = racks();
    if (S.rack === '*') return rs;
    return rs.filter(function (r) { return r.id === S.rack; });
  }
  // Racks that [ / ] and "Move to rack" cycle through.
  function peerRacks() {
    return embedded ? roomRacks(doc(), '*') : racks();
  }
  function facesShown() {
    if (S.print) return ['front', 'rear'];
    if (S.face === 'both') return layout() === 'sm' ? [S.single] : ['front', 'rear'];
    return [S.face];
  }
  function curFace() { return S.face === 'both' ? S.single : S.face; }
  function multiFace() { return facesShown().length > 1; }
  function displayMode() {
    const d = S.options.display;
    return DISPLAY_MODES.indexOf(d) >= 0 ? d : 'label';
  }
  function annotateField() {
    const a = S.options.annotate;
    return a && ANNOTATION_FIELDS.some(function (f) { return f.key === a; }) ? a : '';
  }
  function commit(ops, label) {
    if (!ops || !ops.length) return false;
    if (readOnly()) { ctx.toast('Read-only: changes are not allowed here.', 'warn'); return false; }
    ctx.commit(ops, label);
    return true;
  }
  function toast(msg, level) {
    if (typeof ctx.toast === 'function') ctx.toast(msg, level);
    announce(msg);
  }
  function findItem(rackId, itemId) {
    return rackItems(doc(), rackId).filter(function (it) { return it.id === itemId; })[0] || null;
  }
  function rawItem(rackId, itemId) {
    const rack = findRack(doc(), rackId);
    return ((rack && rack.items) || []).filter(function (it) { return it && String(it.id) === itemId; })[0] || null;
  }
  // A device name, or for `item:<id>` the item label (else its type label).
  function devName(id, rackId) {
    const s = String(id);
    if (s.indexOf(ITEM_PREFIX) === 0) {
      const iid = s.slice(ITEM_PREFIX.length);
      const ids = rackId ? [rackId] : [];
      ((doc().racks) || []).forEach(function (r) { if (ids.indexOf(r.id) < 0) ids.push(r.id); });
      for (let i = 0; i < ids.length; i++) {
        const it = findItem(ids[i], iid);
        if (it) return it.label || typeLabel(it.type);
      }
      return typeLabel('other');
    }
    const d = deviceById(doc(), s);
    return d ? d.name : s;
  }
  function rackHref(id) {
    if (typeof ctx.routeHref !== 'function') return '';
    const href = ctx.routeHref({view: 'racks', id: id, tab: '', sub: '', query: {}});
    return href && href !== '#' ? href : '';
  }
  function announce(msg) {
    const live = typeof document !== 'undefined' && document.getElementById('fathom-live');
    if (live) live.textContent = msg;
  }

  // Template ru/width (FR-RACK-02 default height); fetched from the library when an API exists.
  function templateInfo(dev) {
    const tid = dev && dev.template;
    if (!tid) return null;
    const local = (doc().templates || []).filter(function (t) { return t.id === tid; })[0];
    if (local) return {ru: local.ru, width: local.width};
    if (S.info[tid]) return {ru: S.info[tid].ru, width: S.info[tid].width};
    if (S.tpl[tid] !== undefined) return S.tpl[tid];
    S.tpl[tid] = null;
    if (ctx.api && ctx.api.template) {
      Promise.resolve(ctx.api.template(tid, ctx.project)).then(function (t) {
        S.tpl[tid] = t ? {ru: t.ru, width: t.width} : null;
      }, function () { S.tpl[tid] = null; });
    }
    return null;
  }
  function placeDefaults(dev) {
    if (dev.rack && dev.rack.id) return {};
    const t = templateInfo(dev);
    const po = {face: curFace()};
    if (t && parseInt(t.ru, 10) >= 1) po.height = parseInt(t.ru, 10);
    else po.height = heightOf(doc(), dev);
    if (t && t.width === 'half') po.side = 'left';
    return po;
  }

  // Display summaries (rack_category, images, airflow): a project template, else the library.
  function infoOf(dev) {
    const tid = dev && dev.template;
    if (!tid) return null;
    const local = (doc().templates || []).filter(function (t) { return t && t.id === tid; })[0];
    return local || S.info[tid] || null;
  }
  function wantInfo(rs) {
    const ids = [];
    const shown = {};
    rs.forEach(function (r) { shown[r.id] = true; });
    (doc().devices || []).forEach(function (d) {
      const tid = d && d.template;
      if (!tid || !d.rack || !shown[d.rack.id] || S.infoReq[tid]) return;
      S.infoReq[tid] = true;
      ids.push(tid);
    });
    if (!ids.length) return;
    Promise.resolve(loadTemplateInfo(ctx, ids)).then(function (m) {
      if (S.dead || !m) return;
      let changed = false;
      Object.keys(m).forEach(function (k) { if (S.info[k] !== m[k]) { S.info[k] = m[k]; changed = true; } });
      if (changed) render();
    }, function () { /* never rejects */ });
  }
  function attachmentUrl(attId) {
    const att = (doc().attachments || []).filter(function (a) { return a && a.id === attId; })[0];
    if (!att || !ctx.api || typeof ctx.api.fileUrl !== 'function') return '';
    return ctx.api.fileUrl(ctx.project, att);
  }

  // The devices sharing cables with the selected racked device (store highlight wins).
  function highlightSet() {
    if (S.highlight && S.highlight.devices && S.highlight.devices.length) return S.highlight.devices;
    if (!S.sel) return null;
    const dev = deviceById(doc(), S.sel);
    if (!dev || !dev.rack || !dev.rack.id) return null;
    const linked = [S.sel];
    (doc().cables || []).forEach(function (c) {
      const a = c && c.from && c.from.device;
      const b = c && c.to && c.to.device;
      if (a === S.sel && b && linked.indexOf(b) < 0) linked.push(b);
      if (b === S.sel && a && linked.indexOf(a) < 0) linked.push(a);
    });
    return linked.length > 1 ? linked : null;
  }

  // ---------------------------------------------------------- rendering
  function render() {
    if (S.dead) return;
    const rs = racks();
    if (!embedded && S.rack !== '*' && !rs.some(function (r) { return r.id === S.rack; })) S.rack = '*';
    const ro = readOnly();
    root.classList.toggle('rk-readonly', ro);
    root.classList.toggle('rk-printing', S.print);
    S.k = S.print ? 1 : ruScale();
    S.layout = layout();
    root.style.setProperty('--rk-ru', (RU_PX * S.k) + 'px');
    renderRacks();
    if (S.menu) refreshMenu();
    if (typeof o.onChange === 'function') o.onChange(getState(), api);
  }

  function renderRacks() {
    racksEl.innerHTML = '';
    const rs = shownRacks();
    if (!rs.length) {
      const empty = typeof o.empty === 'function' ? o.empty()
        : h('p', {class: 'rk-empty', text: embedded ? 'This rack no longer exists.' : 'No racks.'});
      if (empty) racksEl.appendChild(empty);
      return;
    }
    wantInfo(rs);
    const faces = facesShown();
    rs.forEach(function (rack) {
      const faceEls = faces.map(function (f) { return renderFace(rack, f); });
      const coll = collisions(doc(), rack.id);
      const oor = outOfRange(doc(), rack.id);
      const warn = h('ul', {class: 'rk-warnings', 'aria-label': 'Rack warnings'});
      coll.filter(function (c) { return faces.indexOf(c.face) >= 0; }).forEach(function (c) {
        warn.appendChild(h('li', {text: 'U' + ruLabel(rack, c.u) + ' ' + c.face + ': ' + devName(c.a, rack.id) + ' overlaps ' + devName(c.b, rack.id)}));
      });
      oor.forEach(function (id) { warn.appendChild(h('li', {text: devName(id, rack.id) + ' is outside the rack\'s ' + rackUnits(rack) + ' RU'})); });
      const loc = (doc().locations || []).filter(function (l) { return l.id === rack.location; })[0];
      const href = embedded || S.print ? '' : rackHref(rack.id);
      const name = href ? h('a', {class: 'rk-pagelink', href: href, title: 'Open the ' + rack.name + ' page', text: rack.name}) : rack.name;
      const wIn = parseInt(rack.width_in, 10);
      const sub = ' ' + rackUnits(rack) + 'U' + (wIn && wIn !== 19 && rackWidthPx(rack) !== RACK_W ? ' \u00b7 ' + wIn + '\u2033' : '')
        + (loc ? ' \u00b7 ' + loc.name : '') + (rack.numbering === 'top_down' ? ' \u00b7 numbered top-down' : '');
      const other = otherFace(faces[0]);
      const toggle = S.face === 'both' && !S.print && faces.length === 1
        ? h('button', {type: 'button', class: 'rk-btn rk-facetoggle', 'data-face': other, 'aria-label': 'Show the ' + other + ' face of ' + rack.name,
          text: other === 'rear' ? 'Rear \u21c4' : 'Front \u21c4'})
        : null;
      racksEl.appendChild(h('section', {class: 'rk-rack', 'data-rack': rack.id, 'aria-label': rack.name}, [
        h('h3', {class: 'rk-title'}, [name, h('span', {class: 'rk-sub', text: sub}), toggle]),
        h('div', {class: 'rk-faces'}, faceEls),
        warn.childNodes.length ? warn : null,
      ]));
    });
    fitWidth();
  }

  // Shrink the rack drawings to the viewport (never wider than RACK_W per 19");
  // blocks are positioned in % of their slot width, so only --rk-w changes.
  // --rk-w lives on .rk-root because the print sheet overrides it there.
  function fitWidth() {
    if (!root.isConnected) return;
    const rackEls = racksEl.querySelectorAll('.rk-rack');
    if (S.print || !rackEls.length) { root.style.removeProperty('--rk-w'); S.w = 0; return; }
    const vs = getComputedStyle(viewport);
    const avail = viewport.clientWidth - px(vs.paddingLeft) - px(vs.paddingRight);
    if (avail <= 0) return;
    let best = RACK_W;
    let found = false;
    Array.prototype.forEach.call(rackEls, function (r) {
      const figs = r.querySelectorAll('.rk-face');
      const slots = r.querySelectorAll('.rk-slots');
      if (!slots.length) return;
      const rs = getComputedStyle(r);
      const fs = getComputedStyle(r.querySelector('.rk-faces'));
      let figW = 0;
      Array.prototype.forEach.call(figs, function (f) { figW += f.offsetWidth; });
      let slotW = 0;
      let units = 0;
      Array.prototype.forEach.call(slots, function (s) {
        slotW += s.offsetWidth;
        units += (parseInt(s.getAttribute('data-w'), 10) || RACK_W) / RACK_W;
      });
      const gap = px(fs.columnGap) * Math.max(0, figs.length - 1);
      const fixed = px(rs.paddingLeft) + px(rs.paddingRight) + px(rs.borderLeftWidth) + px(rs.borderRightWidth) + gap + figW - slotW;
      best = Math.min(best, Math.floor((avail - fixed) / units));
      found = true;
    });
    if (!found) return;
    const min = multiFace() || annotateField() ? MIN_RACK_W_TIGHT : MIN_RACK_W;
    const w = Math.max(min, Math.min(RACK_W, best));
    if (w === S.w) return;
    S.w = w;
    if (w === RACK_W) root.style.removeProperty('--rk-w');
    else root.style.setProperty('--rk-w', w + 'px');
  }

  function renderFace(rack, face) {
    const units = rackUnits(rack);
    const k = S.k || 1;
    const H = units * RU_PX * k;
    const W = rackWidthPx(rack);
    const left = h('div', {class: 'rk-rail', 'aria-hidden': 'true', style: 'height:' + H + 'px'});
    const right = h('div', {class: 'rk-rail', 'aria-hidden': 'true', style: 'height:' + H + 'px'});
    const slots = h('div', {class: 'rk-slots', 'data-rack': rack.id, 'data-face': face, 'data-w': String(W), style: 'width:' + slotWidthCss(W) + ';height:' + H + 'px'});
    for (let u = 1; u <= units; u++) {
      const y = uToY(rack, u, 1) * k;
      const lab = ruLabel(rack, u);
      left.appendChild(h('span', {class: 'rk-ru', style: 'top:' + y + 'px', text: lab}));
      right.appendChild(h('span', {class: 'rk-ru', style: 'top:' + y + 'px', text: lab}));
      slots.appendChild(h('div', {class: 'rk-blank', style: 'top:' + y + 'px'}));
    }
    const coll = collisions(doc(), rack.id).filter(function (c) { return c.face === face; });
    const bad = {};
    coll.forEach(function (c) { bad[c.a] = true; bad[c.b] = true; });
    const hl = highlightSet();
    const field = annotateField();
    const rows = [];
    function note(dev, b) {
      if (!field) return;
      const v = annotationValue(doc(), dev, field, infoOf(dev));
      if (!v) return;
      const key = b.y + '|' + b.h;
      const row = rows.filter(function (r) { return r.key === key; })[0];
      if (row) row.texts.push(v);
      else rows.push({key: key, y: b.y, h: b.h, texts: [v], dev: dev.id});
    }
    itemBlocks(doc(), rack.id, face).forEach(function (b) { slots.appendChild(renderItem(rack, face, b, bad, hl)); });
    // wide blocks first so half-width / colliding blocks stay visible on top
    faceBlocks(doc(), rack.id, face).sort(function (a, b) { return b.w - a.w || (a.behind ? -1 : 0) - (b.behind ? -1 : 0); }).forEach(function (b) {
      const dev = deviceById(doc(), b.device) || {id: b.device, name: b.device};
      slots.appendChild(renderBlock(rack, face, dev, b, bad, hl));
      note(dev, b);
    });
    shelfChildBlocks(doc(), rack.id, face).forEach(function (c) {
      const dev = deviceById(doc(), c.device) || {id: c.device, name: c.device};
      const p = dev.rack ? placement(doc(), dev) : {u: 0, height: 1, face: face, side: 'full'};
      const b = {device: c.device, u: p.u, height: 1, face: p.face, side: 'full', x: c.x, y: c.y, w: c.w, h: c.h, behind: c.behind, shelf: c.item, slot: c.slot};
      slots.appendChild(renderBlock(rack, face, dev, b, bad, hl));
      note(dev, b);
    });
    const kids = [
      h('figcaption', {text: face === 'front' ? 'Front' : 'Rear'}),
      h('div', {class: 'rk-frame'}, [left, slots, right]),
    ];
    if (field) {
      const label = ANNOTATION_FIELDS.filter(function (f) { return f.key === field; })[0].label;
      const inner = h('div', {class: 'rk-annot-in', style: 'height:' + H + 'px'});
      rows.forEach(function (r) {
        inner.appendChild(h('div', {class: 'rk-anno', 'data-device': r.dev, style: 'top:' + (r.y * k) + 'px;height:' + (r.h * k) + 'px', title: r.texts.join(' \u00b7 ')}, [
          h('span', {text: r.texts.join(' \u00b7 ')}),
        ]));
      });
      kids.push(h('div', {class: 'rk-annot', 'data-face': face, 'data-field': field, role: 'list', 'aria-label': label + ' of the ' + face + ' devices'}, [inner]));
    }
    return h('figure', {class: 'rk-face' + (field ? ' rk-annotated' : ''), 'data-face': face}, kids);
  }

  function moreButton(name) {
    return h('button', {type: 'button', class: 'rk-more', tabindex: '-1', 'aria-label': 'Menu for ' + name, title: 'Menu', text: '\u22ef'});
  }

  function renderBlock(rack, face, dev, b, bad, hl) {
    const k = S.k || 1;
    const info = infoOf(dev);
    const color = blockColor(dev, vocab, info);
    const mode = displayMode();
    const img = mode !== 'label' ? deviceImage(dev, info, face, {base: ctx.appRoot || '', attachmentUrl: attachmentUrl}) : '';
    const air = mode === 'both' && info ? airflowGlyph(info.airflow, face) : null;
    const onShelf = !!b.shelf;
    const shelf = onShelf ? findItem(rack.id, b.shelf) : null;
    const hlCls = hl ? (b.device === S.sel ? '' : hl.indexOf(b.device) >= 0 ? ' rk-hl' : ' rk-dim') : '';
    const cls = 'rk-block' + (onShelf ? ' rk-onshelf' : '') + (b.behind ? ' rk-behind' : '') + (bad[b.device] ? ' rk-collide' : '')
      + (S.sel === b.device ? ' rk-selected' : '') + (dev.status === 'planned' ? ' rk-planned' : '') + (b.height * k === 1 ? ' rk-1u' : '') + hlCls
      + (img ? ' rk-showimg' + (mode === 'both' ? ' rk-imglabel' : '') : '');
    const where = onShelf
      ? 'on ' + (shelf ? shelf.label : 'a shelf') + ' cell ' + (b.slot + 1) + ', U' + ruLabel(rack, b.u)
      : 'U' + ruLabel(rack, b.u) + (b.height > 1 ? '\u2013' + ruLabel(rack, b.u + b.height - 1) : '') + ', ' + b.height + 'U, ' + b.face + (b.side !== 'full' ? ' ' + b.side : '');
    const label = dev.name + ', ' + where + (b.behind ? ' (seen from the ' + face + ')' : '') + (bad[b.device] ? ', collides' : '') + (air ? ', ' + air.title : '');
    const hint = readOnly() ? '' : onShelf ? '. Left or right moves it between cells, Delete unracks it, Enter opens it' : '. Arrow up or down moves it, Delete unracks it, Enter opens it';
    const kids = [h('span', {class: 'rk-stripe', 'aria-hidden': 'true'})];
    if (img) {
      kids.push(h('img', {class: 'rk-img', src: img, alt: '', draggable: 'false', loading: 'lazy', onerror: function (e) {
        const blk = e.target.parentNode;
        if (blk) blk.classList.remove('rk-showimg', 'rk-imglabel');
        if (e.target.parentNode) e.target.parentNode.removeChild(e.target);
      }}));
    }
    kids.push(h('span', {class: 'rk-bname', text: (b.behind ? 'Rear of ' : '') + dev.name + (dev.count > 1 ? ' \u00d7' + dev.count : '')}));
    kids.push(h('span', {class: 'rk-bmodel', text: modelLine(dev)}));
    kids.push(h('span', {class: 'rk-bru', text: b.height + 'U'}));
    if (air) kids.push(h('span', {class: 'rk-air', title: air.title, 'aria-hidden': 'true', text: air.glyph}));
    if (!S.print) kids.push(moreButton(dev.name));
    const hpx = onShelf ? Math.max(8, b.h * k - SHELF_LIP) : b.h * k;
    return h('div', {
      class: cls, 'data-device': b.device, 'data-rack': rack.id, 'data-shelf': onShelf ? b.shelf : null, 'data-slot': onShelf ? String(b.slot) : null,
      tabindex: S.print ? null : '0', role: 'button', 'aria-label': label + hint,
      style: 'left:' + pct(b.x, rack) + ';top:' + (b.y * k) + 'px;width:' + pct(b.w, rack) + ';height:' + hpx + 'px;--rk-color:' + color + ';--rk-text:' + textColorOn(color),
      title: label,
    }, kids);
  }

  function renderItem(rack, face, b, bad, hl) {
    const k = S.k || 1;
    const key = rack.id + '/' + b.item;
    const range = 'U' + ruLabel(rack, b.u) + (b.height > 1 ? '\u2013' + ruLabel(rack, b.u + b.height - 1) : '');
    const label = b.label + ', ' + range + ', ' + b.height + 'U, ' + b.face + (b.depth === 'full' ? ', full depth' : '')
      + (b.type === 'shelf' ? ', ' + b.slots + (b.slots === 1 ? ' cell' : ' cells') : '') + (b.behind ? ' (seen from the ' + face + ')' : '') + (bad[b.id] ? ', collides' : '');
    const cls = 'rk-item rk-item-' + b.type + (b.behind ? ' rk-behind' : '') + (bad[b.id] ? ' rk-collide' : '') + (S.selItem === key ? ' rk-selected' : '')
      + (b.height * k === 1 ? ' rk-1u' : '') + (hl ? ' rk-dim' : '');
    const kids = [];
    if (b.type === 'shelf') {
      for (let s = 0; s < b.slots; s++) {
        kids.push(h('span', {class: 'rk-cell', 'data-slot': String(s), 'aria-hidden': 'true', style: 'left:' + (s * 100 / b.slots) + '%;width:' + (100 / b.slots) + '%'}));
      }
    }
    kids.push(h('span', {class: 'rk-iname', text: b.label}));
    if (!S.print) kids.push(moreButton(b.label));
    return h('div', {
      class: cls, 'data-item': b.item, 'data-rack': rack.id, 'data-type': b.type, tabindex: S.print ? null : '0', role: 'button',
      'aria-label': label + (readOnly() ? '' : '. Arrow up or down moves it, Delete removes it, Enter opens its menu'),
      style: 'left:0;top:' + (b.y * k) + 'px;width:100%;height:' + (b.h * k) + 'px;--rk-color:' + b.color + ';--rk-text:' + textColorOn(b.color),
      title: label,
    }, kids);
  }

  // ------------------------------------------------------------ placing
  function tryPlace(id, rackId, u, opts2, force) {
    const rack = findRack(doc(), rackId);
    const po = Object.assign({}, opts2 || {});
    const f = fits(doc(), rackId, id, u, po);
    const what = devName(id) + ' at U' + ruLabel(rack, u) + ' in ' + (rack ? rack.name : rackId);
    if (!f.ok && f.reason === 'occupied' && force) {
      po.force = true;
      if (commit(placeOps(doc(), id, rackId, u, po), 'Racked ' + what + ' (collision)')) {
        ctx.toast('Placed ' + what + ' over ' + f.conflicts.map(function (c) { return devName(c, rackId); }).join(', ') + ' (collision warning).', 'warn');
      }
      return true;
    }
    if (!f.ok) {
      toast(refusal(f, rack, rackId, u), 'warn');
      return false;
    }
    commit(placeOps(doc(), id, rackId, u, po), 'Racked ' + what);
    return true;
  }

  function refusal(f, rack, rackId, u) {
    if (f.reason === 'occupied') return 'U' + ruLabel(rack, u) + ' is occupied by ' + f.conflicts.map(function (c) { return devName(c, rackId); }).join(', ') + '. Hold Alt/Option to force.';
    if (f.reason === 'out_of_range') return 'That does not fit inside ' + (rack ? rack.name : rackId) + '.';
    return 'Unknown rack.';
  }

  // First free RU of rackId (default: the shown rack, else the first rack).
  function addToRack(id, rackId) {
    const dev = deviceById(doc(), id);
    const target = rackId || (S.rack !== '*' ? S.rack : (racks()[0] && racks()[0].id));
    if (!dev || !target) return;
    const po = placeDefaults(dev);
    const u = firstFit(doc(), target, id, po);
    if (!u) { ctx.toast('No free space for ' + dev.name + ' in ' + findRack(doc(), target).name + '.', 'warn'); return; }
    S.sel = id;
    tryPlace(id, target, u, po, false);
    refocus(id);
  }

  function refocus(id) {
    const b = racksEl.querySelector('.rk-block[data-device="' + cssq(id) + '"]');
    if (b) b.focus();
  }
  function refocusItem(rackId, itemId) {
    const b = racksEl.querySelector('.rk-item[data-rack="' + cssq(rackId) + '"][data-item="' + cssq(itemId) + '"]');
    if (b) b.focus();
  }
  function refocusTarget(t) {
    if (!t) return;
    if (t.kind === 'item') refocusItem(t.rack, t.id);
    else refocus(t.id);
  }
  function focusFirst() {
    const first = racksEl.querySelector('.rk-block,.rk-item');
    if (first) first.focus();
  }

  function duplicateDevice(id) {
    const dev = deviceById(doc(), id);
    if (!dev || readOnly()) return;
    const res = duplicateDeviceOps(doc(), id, {});
    if (!commit(res.ops, 'Duplicated ' + dev.name)) return;
    const copy = deviceById(doc(), res.id);
    if (copy && copy.rack && copy.rack.id) {
      select1(res.id);
      announce('Duplicated ' + dev.name + ' as ' + copy.name);
    } else {
      toast('No free space for a copy of ' + dev.name + ' in its rack; the copy is unracked.', 'warn');
      refocus(id);
    }
  }

  function flipDevice(id, force) {
    const dev = deviceById(doc(), id);
    if (!dev || !dev.rack || !dev.rack.id) return;
    const p = placement(doc(), dev);
    if (p.shelf) { toast(dev.name + ' follows its shelf\'s face.', 'warn'); return; }
    const to = otherFace(p.face);
    S.sel = id;
    if (!tryPlace(id, dev.rack.id, p.u, {face: to}, force)) return;
    if (!embedded && !multiFace() && p.depth !== 'full') {
      if (S.face === 'both') S.single = to; else S.face = to;
      render();
    }
    announce(dev.name + ' is now mounted on the ' + to + ' face');
    refocus(id);
  }

  function shiftRack(id, dir, force) {
    const dev = deviceById(doc(), id);
    if (!dev || !dev.rack || !dev.rack.id) return;
    const rs = peerRacks();
    const i = rs.map(function (r) { return r.id; }).indexOf(dev.rack.id);
    const next = rs[i + dir];
    if (i < 0 || !next) { toast('No ' + (dir < 0 ? 'previous' : 'next') + ' rack.', 'warn'); return; }
    const p = placement(doc(), dev);
    const po = p.shelf ? {height: heightOf(doc(), Object.assign({}, dev, {rack: null})), face: p.face, side: 'full'} : {};
    S.sel = id;
    if (!tryPlace(id, next.id, p.u, po, force)) return;
    if (!embedded && S.rack !== '*') S.rack = next.id;
    render();
    announce('Moved ' + dev.name + ' to ' + next.name);
    refocus(id);
  }

  // ←/→ on a shelf device: the next free cell of the same shelf.
  function shiftCell(id, dir) {
    const dev = deviceById(doc(), id);
    const p = dev && dev.rack ? placement(doc(), dev) : null;
    if (!p || !p.shelf) return;
    const cells = shelfCells(doc(), dev.rack.id, p.shelf);
    for (let s = p.slot + dir; s >= 0 && s < cells.length; s += dir) {
      if (!cells[s].device) {
        commit(placeOnShelfOps(doc(), id, dev.rack.id, p.shelf, s), 'Moved ' + dev.name + ' to cell ' + (s + 1));
        refocus(id);
        return;
      }
    }
    toast('No free cell ' + (dir < 0 ? 'to the left' : 'to the right') + '.', 'warn');
  }

  // ↑/↓ on a shelf device: off the shelf, just above or below it.
  function liftOffShelf(id, dir, force) {
    const dev = deviceById(doc(), id);
    const p = dev && dev.rack ? placement(doc(), dev) : null;
    if (!p || !p.shelf) return;
    const shelf = findItem(dev.rack.id, p.shelf);
    const height = heightOf(doc(), Object.assign({}, dev, {rack: null}));
    const u = shelf ? (dir > 0 ? shelf.u + shelf.height : shelf.u - height) : p.u + dir;
    S.sel = id;
    tryPlace(id, dev.rack.id, u, {height: height, face: p.face, side: 'full'}, force);
    refocus(id);
  }

  // ------------------------------------------------------------- items
  function itemSpec(it) {
    return {type: it.type, height: it.height, face: it.face, depth: it.depth};
  }

  // Move item `itemId` of `rackId` to `u` of `toRack` (another rack: delete +
  // add, shelf devices follow). face: optional new face.
  function moveItem(rackId, itemId, toRack, u, face, force) {
    const it = findItem(rackId, itemId);
    if (!it || readOnly()) return false;
    const rack = findRack(doc(), toRack);
    const what = it.label + ' to U' + ruLabel(rack, u) + (toRack !== rackId && rack ? ' in ' + rack.name : '');
    if (toRack === rackId) {
      const spec = face && face !== it.face ? {face: face} : {};
      const f = itemFits(doc(), rackId, itemId, u, spec);
      if (!f.ok && !(force && f.reason === 'occupied')) { toast(refusal(f, rack, rackId, u), 'warn'); return false; }
      const ops = moveItemOps(doc(), rackId, itemId, u, Object.assign({force: !!force}, spec));
      if (commit(ops, 'Moved ' + what + (f.ok ? '' : ' (collision)')) && !f.ok) toast('Placed ' + what + ' over ' + f.conflicts.map(function (c) { return devName(c, rackId); }).join(', ') + ' (collision warning).', 'warn');
      return ops.length > 0;
    }
    const spec2 = Object.assign(itemSpec(it), face ? {face: face} : {});
    const f2 = itemFits(doc(), toRack, null, u, spec2);
    if (!f2.ok && !(force && f2.reason === 'occupied')) { toast(refusal(f2, rack, toRack, u), 'warn'); return false; }
    const raw = rawItem(rackId, itemId) || {};
    const add = addItemOps(doc(), toRack, Object.assign({}, spec2, {
      u: u, label: raw.label, color: raw.color, slots: raw.slots, weight_kg: raw.weight_kg, notes: raw.notes, force: !!force,
    }));
    if (!add.ops.length) return false;
    let ops = delItemOps(doc(), rackId, itemId).concat(add.ops);
    if (it.type === 'shelf') {
      shelfCells(doc(), rackId, itemId).forEach(function (c) {
        if (!c.device) return;
        ops = ops.concat([{op: 'merge', coll: 'devices', id: c.device, value: {rack: {id: toRack, u: u, height: 1, face: spec2.face, side: 'full', shelf: add.id, slot: c.slot}}}]);
      });
    }
    commit(ops, 'Moved ' + what);
    S.selItem = toRack + '/' + add.id;
    return add.id;
  }

  function deleteItem(rackId, itemId) {
    const it = findItem(rackId, itemId);
    if (!it || readOnly()) return Promise.resolve(false);
    const kids = it.type === 'shelf' ? shelfCells(doc(), rackId, itemId).filter(function (c) { return !!c.device; }).length : 0;
    const go = kids ? confirmScope(ctx, {
      verb: 'Remove', noun: it.label, danger: true, ok: 'Remove shelf',
      detail: kids + (kids === 1 ? ' device on it becomes' : ' devices on it become') + ' unracked.',
    }) : Promise.resolve(true);
    return go.then(function (ok) {
      if (!ok) { refocusItem(rackId, itemId); return false; }
      if (S.selItem === rackId + '/' + itemId) S.selItem = null;
      commit(delItemOps(doc(), rackId, itemId), 'Removed ' + it.label);
      if (lst && typeof lst.focus === 'function' && kids) lst.focus();
      else focusFirst();
      return true;
    });
  }

  function duplicateItem(rackId, itemId) {
    const it = findItem(rackId, itemId);
    if (!it || readOnly()) return;
    const raw = rawItem(rackId, itemId) || {};
    const res = addItemOps(doc(), rackId, Object.assign(itemSpec(it), {label: raw.label, color: raw.color, slots: raw.slots, weight_kg: raw.weight_kg, notes: raw.notes}));
    if (!res.ops.length) { toast('No free space for another ' + it.label + ' in ' + findRack(doc(), rackId).name + '.', 'warn'); return; }
    commit(res.ops, 'Added ' + it.label);
    selectItem(rackId, res.id);
    announce('Added a copy of ' + it.label);
  }

  function flipItem(rackId, itemId, force) {
    const it = findItem(rackId, itemId);
    if (!it) return;
    const to = otherFace(it.face);
    if (!moveItem(rackId, itemId, rackId, it.u, to, force)) return;
    if (!embedded && !multiFace() && it.depth !== 'full') {
      if (S.face === 'both') S.single = to; else S.face = to;
      render();
    }
    announce(it.label + ' is now on the ' + to + ' face');
    refocusItem(rackId, itemId);
  }

  function shiftItemRack(rackId, itemId, dir, force) {
    const it = findItem(rackId, itemId);
    if (!it) return;
    const rs = peerRacks();
    const i = rs.map(function (r) { return r.id; }).indexOf(rackId);
    const next = rs[i + dir];
    if (i < 0 || !next) { toast('No ' + (dir < 0 ? 'previous' : 'next') + ' rack.', 'warn'); return; }
    const id = moveItem(rackId, itemId, next.id, it.u, null, force);
    if (!id) return;
    if (!embedded && S.rack !== '*') S.rack = next.id;
    render();
    refocusItem(next.id, id);
  }

  // ----------------------------------------------------------- dragging
  function capture(target, id) { try { target.setPointerCapture(id); } catch (err) { /* synthetic pointer */ } }
  function release(target, id) { try { if (target && target.hasPointerCapture && target.hasPointerCapture(id)) target.releasePointerCapture(id); } catch (err) { /* gone */ } }

  function slotRects() {
    return Array.prototype.slice.call(racksEl.querySelectorAll('.rk-slots')).map(function (s) {
      return {el: s, rack: s.getAttribute('data-rack'), face: s.getAttribute('data-face'), r: s.getBoundingClientRect()};
    });
  }

  function srcFace(grabEl) {
    const s = grabEl && grabEl.closest ? grabEl.closest('.rk-slots') : null;
    return s ? s.getAttribute('data-face') : '';
  }

  function startDrag(e, id, fromList, grabEl) {
    const dev = deviceById(doc(), id);
    if (!dev || readOnly()) return;
    const p = dev.rack && dev.rack.id ? placement(doc(), dev) : null;
    const po = p ? {} : placeDefaults(dev);
    const onShelf = !!(p && p.shelf);
    const height = onShelf ? heightOf(doc(), Object.assign({}, dev, {rack: null})) : p ? p.height : (po.height || 1);
    if (onShelf) { po.height = height; po.face = p.face; po.side = 'full'; }
    let grabY = (RU_PX * (S.k || 1) * height) / 2;
    if (!fromList && !onShelf) {
      const br = grabEl.getBoundingClientRect();
      grabY = e.clientY - br.top;
    }
    S.drag = {kind: 'device', id: id, pointer: e.pointerId, x: e.clientX, y: e.clientY, moved: false, fromList: fromList, opts: po, face: p ? p.face : '',
      height: height, side: onShelf ? 'full' : p ? p.side : (po.side || 'full'), grabY: grabY, rects: slotRects(), target: null, src: grabEl,
      srcFace: fromList ? '' : srcFace(grabEl), shelf: onShelf ? p.shelf : '', slot: onShelf ? p.slot : null};
    capture(grabEl, e.pointerId);
    e.preventDefault();
  }

  function startItemDrag(e, rackId, itemId, grabEl) {
    const it = findItem(rackId, itemId);
    if (!it || readOnly()) return;
    const br = grabEl.getBoundingClientRect();
    S.drag = {kind: 'item', id: itemId, rack: rackId, item: it, pointer: e.pointerId, x: e.clientX, y: e.clientY, moved: false, face: it.face,
      height: it.height, side: 'full', grabY: e.clientY - br.top, rects: slotRects(), target: null, src: grabEl, srcFace: srcFace(grabEl)};
    capture(grabEl, e.pointerId);
    e.preventDefault();
  }

  function inList(e) {
    if (!lst) return false;
    if (typeof lst.accept === 'function') return !!lst.accept(e);
    const lr = list.getBoundingClientRect();
    return lr.width > 0 && e.clientX >= lr.left && e.clientX <= lr.right && e.clientY >= lr.top && e.clientY <= lr.bottom;
  }

  // The shelf cell under the pointer on slot rect `s`: {item, slot, slots, y, h} or null.
  function shelfAt(s, e) {
    if (e.clientX < s.r.left || e.clientX > s.r.right) return null;
    const k = S.k || 1;
    const yy = (e.clientY - s.r.top) / k;
    const shelves = itemBlocks(doc(), s.rack, s.face).filter(function (b) { return b.type === 'shelf' && yy >= b.y && yy < b.y + b.h; });
    if (!shelves.length) return null;
    const b = shelves[0];
    const slot = Math.max(0, Math.min(b.slots - 1, Math.floor((e.clientX - s.r.left) / s.r.width * b.slots)));
    return {item: b.item, slot: slot, slots: b.slots, y: b.y, h: b.h};
  }

  function dragTarget(e, drag) {
    const d = drag || S.drag;
    const k = S.k || 1;
    for (let i = 0; i < d.rects.length; i++) {
      const s = d.rects[i];
      if (e.clientX >= s.r.left - 24 && e.clientX <= s.r.right + 24 && e.clientY >= s.r.top - RU_PX * k && e.clientY <= s.r.bottom + RU_PX * k) {
        const rack = findRack(doc(), s.rack);
        const u = yToU(rack, (e.clientY - s.r.top - d.grabY) / k, d.height);
        const t = {rack: s.rack, face: s.face, u: u, rect: s};
        if (d.kind === 'device' || (d.kind === 'ext' && d.payload.kind === 'template')) {
          const cell = shelfAt(s, e);
          if (cell) t.cell = cell;
        }
        return t;
      }
    }
    if (d.kind !== 'ext' && inList(e)) return {unrack: true};
    return null;
  }

  // Placement options of a device drag at target t: list drops and drops onto
  // the other face's column (both faces shown) take that face.
  function devOpts(d, t) {
    const po = Object.assign({}, d.opts);
    if (d.fromList || (multiFace() && d.srcFace && t.face !== d.srcFace) || (d.shelf && t.face !== d.face)) po.face = t.face;
    return po;
  }
  function itemFace(d, t) {
    return multiFace() && d.srcFace && t.face !== d.srcFace ? t.face : null;
  }

  // -> {ok, reason, conflicts, name} for drag `d` at target `t`.
  function evalTarget(d, t) {
    if (t.cell) {
      const cells = shelfCells(doc(), t.rack, t.cell.item);
      const who = cells[t.cell.slot] ? cells[t.cell.slot].device : null;
      const ok = !who || (d.kind === 'device' && who === d.id);
      return {ok: ok, reason: ok ? '' : 'occupied', conflicts: who ? [who] : []};
    }
    if (d.kind === 'device') return fits(doc(), t.rack, d.id, t.u, devOpts(d, t));
    if (d.kind === 'item') {
      const face = itemFace(d, t);
      if (t.rack === d.rack) return itemFits(doc(), t.rack, d.id, t.u, face ? {face: face} : {});
      return itemFits(doc(), t.rack, null, t.u, Object.assign(itemSpec(d.item), face ? {face: face} : {}));
    }
    if (d.payload.kind === 'template') return fits(doc(), t.rack, EXT_ID, t.u, {height: d.height, face: t.face, side: d.side, depth: d.depth});
    return itemFits(doc(), t.rack, null, t.u, {type: d.payload.type, face: t.face});
  }

  function dragName(d) {
    if (d.kind === 'device') return devName(d.id);
    if (d.kind === 'item') return d.item.label;
    return d.name;
  }

  function showGhost(e, d, t) {
    const rr = root.getBoundingClientRect();
    const k = S.k || 1;
    if (t && t.rack) {
      const rack = findRack(doc(), t.rack);
      const f = evalTarget(d, t);
      ghost.hidden = false;
      ghost.className = 'rk-ghost ' + (f.ok ? 'rk-ok' : (e.altKey && f.reason === 'occupied' && !t.cell ? 'rk-force' : 'rk-bad'));
      if (t.cell) {
        const cw = t.rect.r.width / t.cell.slots;
        ghost.style.left = (t.rect.r.left - rr.left + t.cell.slot * cw) + 'px';
        ghost.style.top = (t.rect.r.top - rr.top + t.cell.y * k) + 'px';
        ghost.style.width = cw + 'px';
        ghost.style.height = (t.cell.h * k) + 'px';
        const shelf = findItem(t.rack, t.cell.item);
        ghost.textContent = dragName(d) + ' \u00b7 ' + (shelf ? shelf.label : 'Shelf') + ' ' + (t.cell.slot + 1) + (f.ok ? '' : ' \u00b7 taken');
        return;
      }
      const half = t.rect.r.width / 2;
      ghost.style.left = (t.rect.r.left - rr.left + (d.side === 'right' ? half : 0)) + 'px';
      ghost.style.top = (t.rect.r.top - rr.top + uToY(rack, t.u, d.height) * k) + 'px';
      ghost.style.width = (d.side === 'full' ? t.rect.r.width : half) + 'px';
      ghost.style.height = (d.height * RU_PX * k) + 'px';
      ghost.textContent = dragName(d) + ' \u00b7 U' + ruLabel(rack, t.u) + (f.ok ? '' : f.reason === 'occupied' ? ' \u00b7 occupied' : ' \u00b7 does not fit');
    } else {
      ghost.hidden = false;
      ghost.className = 'rk-ghost rk-float';
      ghost.style.left = (e.clientX - rr.left + 10) + 'px';
      ghost.style.top = (e.clientY - rr.top + 10) + 'px';
      ghost.style.width = '';
      ghost.style.height = '';
      ghost.textContent = dragName(d) + (t && t.unrack ? ' \u00b7 unrack' : '');
    }
  }

  function onDragMove(e) {
    pressMove(e);
    const d = S.drag;
    if (!d || d.pointer !== e.pointerId) return;
    if (!d.moved && Math.hypot(e.clientX - d.x, e.clientY - d.y) < DRAG_SLOP) return;
    if (!d.moved && d.fromList && lst && typeof lst.onLift === 'function') lst.onLift();
    d.moved = true;
    const t = dragTarget(e);
    d.target = t;
    if (list) list.classList.toggle('rk-droptarget', !!(t && t.unrack && !d.fromList && d.kind === 'device'));
    showGhost(e, d, t && (t.rack || (t.unrack && d.kind === 'device')) ? t : null);
  }

  function onDragUp(e) {
    cancelPress();
    const d = S.drag;
    if (!d || d.pointer !== e.pointerId) return;
    S.drag = null;
    ghost.hidden = true;
    if (list) list.classList.remove('rk-droptarget');
    if (!d.moved) {
      if (d.kind === 'item') selectItem(d.rack, d.id);
      else if (!d.fromList) select1(d.id);
      return;
    }
    const t = dragTarget(e, d);
    if (d.kind === 'item') {
      if (!t || !t.rack) return;
      const id = moveItem(d.rack, d.id, t.rack, t.u, itemFace(d, t), !!e.altKey);
      if (id) refocusItem(t.rack, typeof id === 'string' ? id : d.id);
      return;
    }
    if (t && t.cell) {
      const f = evalTarget(d, t);
      const shelf = findItem(t.rack, t.cell.item);
      if (!f.ok) { toast('That cell of ' + (shelf ? shelf.label : 'the shelf') + ' holds ' + devName(f.conflicts[0]) + '.', 'warn'); return; }
      S.sel = d.id;
      commit(placeOnShelfOps(doc(), d.id, t.rack, t.cell.item, t.cell.slot), 'Put ' + devName(d.id) + ' on ' + (shelf ? shelf.label : 'a shelf') + ' cell ' + (t.cell.slot + 1));
      refocus(d.id);
    } else if (t && t.rack) {
      S.sel = d.id;
      tryPlace(d.id, t.rack, t.u, devOpts(d, t), !!e.altKey);
      refocus(d.id);
    } else if (t && t.unrack && !d.fromList) {
      commit(unplaceOps(doc(), d.id), 'Unracked ' + devName(d.id));
    }
  }

  function onDragCancel() {
    cancelPress();
    S.drag = null;
    ghost.hidden = true;
    if (list) list.classList.remove('rk-droptarget');
  }

  // ------------------------------------------------------ external drag
  // payload {kind: 'template', entry, template} | {kind: 'item', type}. The
  // pointer is tracked on the document (the host may hold its capture); a drop
  // on a free spot calls opts.onExternalDrop(payload, target); Esc, a drop
  // outside or on a taken spot cancels. Returns true when the drag started.
  function beginExternalDrag(payload, e) {
    if (!payload || readOnly() || S.dead || typeof document === 'undefined') return false;
    let height = 1;
    let name = '';
    let side = 'full';
    let depth = 'full';
    if (payload.kind === 'template') {
      const t = payload.template || {};
      const en = payload.entry || {};
      const ru = parseInt(t.ru, 10) >= 1 ? parseInt(t.ru, 10) : parseInt(en.ru, 10);
      height = ru >= 1 ? Math.min(ru, 60) : 1;
      name = t.name || en.name || t.model || en.model || t.id || en.id || 'Device';
      if ((t.width || en.width) === 'half') side = 'left';
      if (t.full_depth === false || en.full_depth === false) depth = 'half';
    } else if (payload.kind === 'item' && TYPE_BY[payload.type]) {
      height = TYPE_BY[payload.type].height;
      name = TYPE_BY[payload.type].label;
    } else {
      return false;
    }
    endExternal();
    closeMenu(false);
    const x = {kind: 'ext', payload: payload, pointer: e && e.pointerId != null ? e.pointerId : null, height: height, side: side, depth: depth, name: name,
      grabY: (RU_PX * (S.k || 1) * height) / 2, rects: slotRects(), target: null, offs: []};
    S.ext = x;
    function mine(ev) { return x.pointer === null || ev.pointerId === x.pointer; }
    x.offs.push(on(document, 'pointermove', function (ev) {
      if (S.ext !== x || !mine(ev)) return;
      x.rects = slotRects();
      const t = dragTarget(ev, x);
      x.target = t;
      showGhost(ev, x, t);
    }, true));
    x.offs.push(on(document, 'pointerup', function (ev) {
      if (S.ext !== x || !mine(ev)) return;
      x.rects = slotRects();
      const t = dragTarget(ev, x);
      endExternal();
      if (!t || !t.rack) { announce('Drop cancelled.'); return; }
      const f = evalTarget(x, t);
      const force = !f.ok && !!ev.altKey && f.reason === 'occupied' && !t.cell;
      if (!f.ok && !force) {
        const rack = findRack(doc(), t.rack);
        toast(t.cell ? 'That shelf cell is taken.' : refusal(f, rack, t.rack, t.u), 'warn');
        return;
      }
      const target = {rackId: t.rack, u: t.u, face: t.face};
      if (t.cell) {
        const shelf = findItem(t.rack, t.cell.item);
        target.shelf = t.cell.item;
        target.slot = t.cell.slot;
        if (shelf) { target.u = shelf.u; target.face = shelf.face; }
      }
      if (force) target.force = true;
      if (typeof o.onExternalDrop === 'function') o.onExternalDrop(payload, target);
    }, true));
    x.offs.push(on(document, 'pointercancel', function (ev) { if (S.ext === x && mine(ev)) endExternal(); }, true));
    x.offs.push(on(document, 'keydown', function (ev) {
      if (S.ext !== x || ev.key !== 'Escape') return;
      ev.preventDefault();
      ev.stopPropagation();
      endExternal();
      announce('Drop cancelled.');
    }, true));
    if (e && typeof e.clientX === 'number') showGhost(e, x, dragTarget(e, x));
    return true;
  }

  function endExternal() {
    const x = S.ext;
    if (!x) return;
    S.ext = null;
    x.offs.forEach(function (off) { off(); });
    ghost.hidden = true;
  }

  // ------------------------------------------------- long press, selection
  function startPress(e, t) {
    cancelPress();
    S.press = {pointer: e.pointerId, x: e.clientX, y: e.clientY, t: t, timer: setTimeout(function () {
      const p = S.press;
      S.press = null;
      if (!p) return;
      if (S.drag) {
        if (S.drag.moved) return;
        release(S.drag.src, S.drag.pointer);
        S.drag = null;
        ghost.hidden = true;
      }
      openMenu(p.t);
    }, LONG_PRESS_MS)};
  }
  function pressMove(e) {
    const p = S.press;
    if (p && p.pointer === e.pointerId && Math.hypot(e.clientX - p.x, e.clientY - p.y) >= DRAG_SLOP * 2) cancelPress();
  }
  function cancelPress() {
    if (S.press) clearTimeout(S.press.timer);
    S.press = null;
  }

  function select1(id) {
    S.sel = id;
    S.selItem = null;
    ctx.select(id ? {type: 'device', id: id} : null);
    render();
    if (id) refocus(id);
  }

  function selectItem(rackId, itemId) {
    const hadDevice = !!S.sel;
    S.sel = null;
    S.selItem = rackId + '/' + itemId;
    if (hadDevice) ctx.select(null);
    render();
    refocusItem(rackId, itemId);
  }

  function targetOf(node) {
    const it = node && node.closest ? node.closest('.rk-item') : null;
    if (it) return {kind: 'item', id: it.getAttribute('data-item'), rack: it.getAttribute('data-rack')};
    const b = node && node.closest ? node.closest('.rk-block') : null;
    if (b) return {kind: 'device', id: b.getAttribute('data-device'), rack: b.getAttribute('data-rack')};
    return null;
  }

  // ----------------------------------------------------------- keyboard
  function onKey(e) {
    if (e.target.closest('.rk-more,.rk-facetoggle')) return;
    const itEl = e.target.closest('.rk-item');
    if (itEl) { onItemKey(e, itEl.getAttribute('data-rack'), itEl.getAttribute('data-item')); return; }
    const b = e.target.closest('.rk-block');
    if (!b) return;
    const id = b.getAttribute('data-device');
    const rackId = b.getAttribute('data-rack');
    const dev = deviceById(doc(), id);
    if (!dev) return;
    const ro = readOnly();
    const mod = e.ctrlKey || e.metaKey;
    const key = e.key;
    const onShelf = b.classList.contains('rk-onshelf');
    if ((key === 'ArrowUp' || key === 'ArrowDown') && !ro && !mod) {
      e.preventDefault();
      const dir = key === 'ArrowUp' ? 1 : -1;
      if (onShelf) { liftOffShelf(id, dir, e.altKey); return; }
      const p = placement(doc(), dev);
      S.sel = id;
      tryPlace(id, rackId, p.u + dir * (e.shiftKey ? 5 : 1), {}, e.altKey);
      refocus(id);
    } else if ((key === 'ArrowLeft' || key === 'ArrowRight') && onShelf && !ro && !mod) {
      e.preventDefault();
      shiftCell(id, key === 'ArrowLeft' ? -1 : 1);
    } else if ((key === 'Delete' || key === 'Backspace') && !ro) {
      e.preventDefault();
      commit(unplaceOps(doc(), id), 'Unracked ' + dev.name);
      if (lst) {
        if (typeof lst.focus === 'function') lst.focus();
      } else {
        focusFirst();
      }
    } else if (mod && (key === 'd' || key === 'D')) {
      e.preventDefault();
      if (!ro) duplicateDevice(id);
    } else if ((key === 'r' || key === 'R') && !mod && !ro) {
      e.preventDefault();
      flipDevice(id, e.altKey);
    } else if ((key === '[' || key === ']') && !mod && !ro) {
      e.preventDefault();
      shiftRack(id, key === '[' ? -1 : 1, e.altKey);
    } else if (key === 'ContextMenu' || (key === 'F10' && e.shiftKey)) {
      e.preventDefault();
      openMenu({kind: 'device', id: id, rack: rackId});
    } else if (key === 'Enter' || key === ' ') {
      e.preventDefault();
      select1(id);
      if (ctx.openInspector) ctx.openInspector({type: 'device', id: id});
    } else if (key === 'Escape') {
      e.preventDefault();
      select1(null);
    }
  }

  function onItemKey(e, rackId, itemId) {
    const it = findItem(rackId, itemId);
    if (!it) return;
    const ro = readOnly();
    const mod = e.ctrlKey || e.metaKey;
    const key = e.key;
    if ((key === 'ArrowUp' || key === 'ArrowDown') && !ro && !mod) {
      e.preventDefault();
      S.selItem = rackId + '/' + itemId;
      moveItem(rackId, itemId, rackId, it.u + (key === 'ArrowUp' ? 1 : -1) * (e.shiftKey ? 5 : 1), null, e.altKey);
      refocusItem(rackId, itemId);
    } else if ((key === 'Delete' || key === 'Backspace') && !ro) {
      e.preventDefault();
      deleteItem(rackId, itemId);
    } else if (mod && (key === 'd' || key === 'D')) {
      e.preventDefault();
      if (!ro) duplicateItem(rackId, itemId);
    } else if ((key === 'r' || key === 'R') && !mod && !ro) {
      e.preventDefault();
      flipItem(rackId, itemId, e.altKey);
    } else if ((key === '[' || key === ']') && !mod && !ro) {
      e.preventDefault();
      shiftItemRack(rackId, itemId, key === '[' ? -1 : 1, e.altKey);
    } else if (key === 'Enter' || key === ' ' || key === 'ContextMenu' || (key === 'F10' && e.shiftKey)) {
      e.preventDefault();
      openMenu({kind: 'item', id: itemId, rack: rackId});
    } else if (key === 'Escape') {
      e.preventDefault();
      S.selItem = null;
      render();
    }
  }

  // ---------------------------------------------------------- the menu
  // A popover next to the block (a bottom sheet at sm) with the block's
  // settings and actions; every change commits at once and the menu redraws.
  function openMenu(t, at) {
    if (!t || typeof document === 'undefined') return;
    closeMenu(false);
    const sm = layout() === 'sm';
    const menu = h('div', {class: 'rk-menu' + (sm ? ' rk-sheet' : ''), role: 'dialog', 'aria-modal': sm ? 'true' : null});
    const back = sm ? h('div', {class: 'rk-menu-back', 'aria-hidden': 'true'}) : null;
    const m = {t: t, el: menu, back: back, at: at || null, offs: []};
    S.menu = m;
    if (back) document.body.appendChild(back);
    document.body.appendChild(menu);
    if (!fillMenu()) return;
    placeMenu();
    m.offs.push(on(menu, 'click', onMenuClick));
    m.offs.push(on(menu, 'change', onMenuChange));
    m.offs.push(on(menu, 'keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeMenu(true); }
    }));
    m.offs.push(on(menu, 'focusout', function (e) {
      const to = e.relatedTarget;
      if (to && !menu.contains(to) && S.menu === m) closeMenu(false);
    }));
    if (back) m.offs.push(on(back, 'pointerdown', function (e) { e.preventDefault(); closeMenu(true); }));
    setTimeout(function () {
      if (S.menu !== m) return;
      m.offs.push(on(document, 'pointerdown', function (e) {
        if (S.menu === m && !menu.contains(e.target) && !(back && e.target === back)) closeMenu(false);
      }, true));
    }, 0);
    const first = menu.querySelector('button:not([disabled]),input:not([disabled]),select:not([disabled])');
    if (first) first.focus();
  }

  function closeMenu(refocusIt) {
    const m = S.menu;
    if (!m) return;
    S.menu = null;
    m.offs.forEach(function (off) { off(); });
    [m.el, m.back].forEach(function (n) { if (n && n.parentNode) n.parentNode.removeChild(n); });
    if (refocusIt) refocusTarget(m.t);
  }

  function placeMenu() {
    const m = S.menu;
    if (!m || m.el.classList.contains('rk-sheet')) return;
    const menu = m.el;
    const mw = menu.offsetWidth;
    const mh = menu.offsetHeight;
    const W = window.innerWidth;
    const H = window.innerHeight;
    let x;
    let y;
    if (m.at && typeof m.at.x === 'number') {
      x = m.at.x;
      y = m.at.y;
    } else {
      const blk = blockEl(m.t);
      const r = blk ? blk.getBoundingClientRect() : {left: W / 2, right: W / 2, top: H / 2, bottom: H / 2};
      x = r.right - mw;
      y = r.bottom + 4;
      if (y + mh > H - 8) y = r.top - mh - 4;
    }
    menu.style.left = Math.max(8, Math.min(W - mw - 8, x)) + 'px';
    menu.style.top = Math.max(8, Math.min(H - mh - 8, y)) + 'px';
  }

  function blockEl(t) {
    if (!t) return null;
    if (t.kind === 'item') return racksEl.querySelector('.rk-item[data-rack="' + cssq(t.rack) + '"][data-item="' + cssq(t.id) + '"]');
    return racksEl.querySelector('.rk-block[data-device="' + cssq(t.id) + '"]');
  }

  function refreshMenu() {
    const m = S.menu;
    if (!m) return;
    const a = document.activeElement;
    const inMenu = a && m.el.contains(a);
    if (inMenu && a.tagName === 'INPUT' && a.type === 'text') return;
    const key = inMenu ? [a.getAttribute('data-act'), a.getAttribute('data-v')] : null;
    if (!fillMenu()) return;
    placeMenu();
    if (key && key[0]) {
      const sel = '[data-act="' + cssq(key[0]) + '"]' + (key[1] != null ? '[data-v="' + cssq(key[1]) + '"]' : '');
      const n = m.el.querySelector(sel + ':not([disabled])') || m.el.querySelector('[data-act="' + cssq(key[0]) + '"]:not([disabled])');
      if (n) n.focus();
    }
  }

  function row(label, control) {
    return h('div', {class: 'rk-menu-row'}, [h('span', {class: 'rk-menu-l', text: label}), control]);
  }
  function seg(label, act, value, choices, disabled) {
    return row(label, h('div', {class: 'rk-seg', role: 'group', 'aria-label': label}, choices.map(function (c) {
      return h('button', {type: 'button', class: 'rk-btn', 'data-act': act, 'data-v': c.v, 'aria-pressed': String(c.v === value), disabled: !!disabled || !!c.disabled, text: c.label});
    })));
  }
  function swatchRow(act, value, disabled) {
    const cur = (value || '').toLowerCase();
    const kids = SWATCHES.map(function (s) {
      return h('button', {type: 'button', class: 'rk-swatch', 'data-act': act, 'data-v': s.color, 'aria-pressed': String(cur === s.color), disabled: !!disabled,
        'aria-label': 'Colour ' + s.label, title: s.label, style: '--rk-sw:' + s.color});
    });
    kids.push(h('button', {type: 'button', class: 'rk-btn rk-swclear', 'data-act': act, 'data-v': '', 'aria-pressed': String(!cur), disabled: !!disabled, text: 'Auto'}));
    return row('Colour', h('div', {class: 'rk-swatches', role: 'group', 'aria-label': 'Colour'}, kids));
  }

  // Rebuild the menu body from the doc; false (and the menu closes) when the target is gone.
  function fillMenu() {
    const m = S.menu;
    const t = m.t;
    const ro = readOnly();
    let body = null;
    if (t.kind === 'item') {
      const it = findItem(t.rack, t.id);
      if (it) body = itemMenu(t, it, ro);
    } else {
      const dev = deviceById(doc(), t.id);
      if (dev && dev.rack && dev.rack.id) { t.rack = dev.rack.id; body = deviceMenu(t, dev, ro); }
    }
    if (!body) { closeMenu(false); return false; }
    m.el.innerHTML = '';
    m.el.setAttribute('aria-label', body.title);
    body.nodes.forEach(function (n) { if (n) m.el.appendChild(n); });
    return true;
  }

  function deviceMenu(t, dev, ro) {
    const p = placement(doc(), dev);
    const rack = findRack(doc(), dev.rack.id);
    const shelf = p.shelf ? findItem(rack.id, p.shelf) : null;
    const sub = (rack ? rack.name + ' \u00b7 ' : '') + 'U' + ruLabel(rack, p.u) + ' \u00b7 ' + (shelf ? 'on ' + shelf.label + ' cell ' + (p.slot + 1) : p.height + 'U \u00b7 ' + p.face);
    const nodes = [h('div', {class: 'rk-menu-h'}, [
      h('strong', {text: dev.name}), h('span', {class: 'rk-menu-sub', text: sub}),
      h('button', {type: 'button', class: 'rk-btn rk-menu-x', 'data-act': 'close', 'aria-label': 'Close', text: '\u00d7'}),
    ])];
    const fixed = ro || !!shelf;
    nodes.push(seg('Face', 'face', p.face, [{v: 'front', label: 'Front'}, {v: 'rear', label: 'Rear'}], fixed));
    nodes.push(seg('Side', 'side', p.side, [{v: 'full', label: 'Full'}, {v: 'left', label: 'Left'}, {v: 'right', label: 'Right'}], fixed));
    nodes.push(seg('Depth', 'depth', p.depth, [{v: 'full', label: 'Full'}, {v: 'half', label: 'Half'}], fixed));
    if (shelf) nodes.push(h('p', {class: 'rk-menu-note', text: 'On a shelf: face and position follow the shelf.'}));
    nodes.push(swatchRow('color', p.color, ro));
    if (!ro) {
      const others = peerRacks().filter(function (r) { return r.id !== rack.id; });
      if (others.length) {
        const sel = h('select', {class: 'rk-menu-rack', 'aria-label': 'Move to rack'}, others.map(function (r) {
          const full = !firstFit(doc(), r.id, dev.id, shelf ? {height: heightOf(doc(), Object.assign({}, dev, {rack: null})), side: 'full'} : {});
          return h('option', {value: r.id, disabled: full, text: r.name + (full ? ' (full)' : '')});
        }));
        nodes.push(row('Rack', h('div', {class: 'rk-menu-inline'}, [sel, h('button', {type: 'button', class: 'rk-btn', 'data-act': 'rack', text: 'Move'})])));
      }
      const cells = [];
      peerRacks().forEach(function (r) {
        rackItems(doc(), r.id).forEach(function (it) {
          if (it.type !== 'shelf') return;
          shelfCells(doc(), r.id, it.id).forEach(function (c) {
            if (!c.device && cells.length < MAX_SHELF_CHOICES) cells.push({rack: r, item: it, slot: c.slot});
          });
        });
      });
      if (cells.length) {
        nodes.push(row('Shelf', h('div', {class: 'rk-seg rk-menu-cells', role: 'group', 'aria-label': 'Move to a free shelf cell'}, cells.map(function (c) {
          return h('button', {type: 'button', class: 'rk-btn', 'data-act': 'shelf', 'data-v': c.rack.id + '/' + c.item.id + '/' + c.slot,
            'data-rack': c.rack.id, 'data-item': c.item.id, 'data-slot': String(c.slot),
            text: (c.rack.id !== rack.id ? c.rack.name + ' \u00b7 ' : '') + c.item.label + ' ' + (c.slot + 1)});
        }))));
      }
    }
    nodes.push(h('div', {class: 'rk-menu-acts'}, [
      ro ? null : h('button', {type: 'button', class: 'rk-btn', 'data-act': 'dup', text: 'Duplicate', title: 'Ctrl/Cmd+D'}),
      ro || !shelf ? null : h('button', {type: 'button', class: 'rk-btn', 'data-act': 'offshelf', text: 'Off the shelf'}),
      ro ? null : h('button', {type: 'button', class: 'rk-btn rk-danger', 'data-act': 'unrack', text: 'Unrack'}),
      h('button', {type: 'button', class: 'rk-btn rk-primary', 'data-act': 'open', text: 'Open'}),
    ]));
    return {title: dev.name + ' menu', nodes: nodes};
  }

  function itemMenu(t, it, ro) {
    const rack = findRack(doc(), t.rack);
    const raw = rawItem(t.rack, t.id) || {};
    const nodes = [h('div', {class: 'rk-menu-h'}, [
      h('strong', {text: it.label}),
      h('span', {class: 'rk-menu-sub', text: (rack ? rack.name + ' \u00b7 ' : '') + typeLabel(it.type) + ' \u00b7 U' + ruLabel(rack, it.u) + ' \u00b7 ' + it.height + 'U'}),
      h('button', {type: 'button', class: 'rk-btn rk-menu-x', 'data-act': 'close', 'aria-label': 'Close', text: '\u00d7'}),
    ])];
    nodes.push(row('Label', h('input', {type: 'text', class: 'rk-menu-label', 'data-act': 'label', 'aria-label': 'Label', value: raw.label || '', placeholder: typeLabel(it.type), readonly: ro, maxlength: '80'})));
    nodes.push(swatchRow('icolor', raw.color || '', ro));
    if (it.type === 'shelf') {
      nodes.push(seg('Cells', 'slots', String(it.slots), [1, 2, 3, 4].map(function (n) { return {v: String(n), label: String(n)}; }), ro));
    }
    nodes.push(row('Height', h('div', {class: 'rk-menu-inline rk-stepper', role: 'group', 'aria-label': 'Height'}, [
      h('button', {type: 'button', class: 'rk-btn', 'data-act': 'height', 'data-v': String(it.height - 1), 'aria-label': 'Shorter', disabled: ro || it.height <= 1, text: '\u2212'}),
      h('output', {class: 'rk-menu-n', text: it.height + 'U'}),
      h('button', {type: 'button', class: 'rk-btn', 'data-act': 'height', 'data-v': String(it.height + 1), 'aria-label': 'Taller', disabled: ro, text: '+'}),
    ])));
    nodes.push(seg('Face', 'iface', it.face, [{v: 'front', label: 'Front'}, {v: 'rear', label: 'Rear'}], ro));
    nodes.push(seg('Depth', 'idepth', it.depth, [{v: 'full', label: 'Full'}, {v: 'half', label: 'Half'}], ro));
    if (!ro) {
      nodes.push(h('div', {class: 'rk-menu-acts'}, [
        h('button', {type: 'button', class: 'rk-btn', 'data-act': 'idup', text: 'Duplicate', title: 'Ctrl/Cmd+D'}),
        h('button', {type: 'button', class: 'rk-btn rk-danger', 'data-act': 'idel', text: 'Remove'}),
      ]));
    }
    return {title: it.label + ' menu', nodes: nodes};
  }

  function onMenuClick(e) {
    const b = e.target.closest('button[data-act]');
    const m = S.menu;
    if (!b || b.disabled || !m) return;
    const act = b.getAttribute('data-act');
    const v = b.getAttribute('data-v');
    if (act === 'close') { closeMenu(true); return; }
    if (m.t.kind === 'item') itemAct(m.t, act, v);
    else deviceAct(m.t, act, v, b);
  }

  function onMenuChange(e) {
    const m = S.menu;
    if (!m || m.t.kind !== 'item' || !e.target.classList.contains('rk-menu-label') || readOnly()) return;
    const label = e.target.value.trim();
    const it = findItem(m.t.rack, m.t.id);
    if (!it) return;
    commit(updateItemOps(doc(), m.t.rack, m.t.id, {label: label || null}), 'Renamed ' + it.label + (label ? ' to ' + label : ''));
  }

  function deviceAct(t, act, v, btn) {
    const dev = deviceById(doc(), t.id);
    if (!dev || !dev.rack) { closeMenu(false); return; }
    const p = placement(doc(), dev);
    if (act === 'face' || act === 'side' || act === 'depth') {
      if (p[act] === v) return;
      const po = {};
      po[act] = v;
      S.sel = dev.id;
      tryPlace(dev.id, dev.rack.id, p.u, po, false);
    } else if (act === 'color') {
      commit([{op: 'merge', coll: 'devices', id: dev.id, value: {rack: {color: v || null}}}], v ? 'Coloured ' + dev.name : 'Cleared the colour of ' + dev.name);
    } else if (act === 'rack') {
      const sel = S.menu.el.querySelector('.rk-menu-rack');
      const to = sel && sel.value;
      if (!to) return;
      const po = p.shelf ? {height: heightOf(doc(), Object.assign({}, dev, {rack: null})), face: p.face, side: 'full'} : {};
      const u = firstFit(doc(), to, dev.id, po);
      if (!u) { toast('No free space for ' + dev.name + ' in ' + findRack(doc(), to).name + '.', 'warn'); return; }
      closeMenu(false);
      S.sel = dev.id;
      if (tryPlace(dev.id, to, u, po, false) && !embedded && S.rack !== '*') { S.rack = to; render(); }
      refocus(dev.id);
    } else if (act === 'shelf') {
      const rk = btn.getAttribute('data-rack');
      const item = btn.getAttribute('data-item');
      const slot = parseInt(btn.getAttribute('data-slot'), 10);
      const shelf = findItem(rk, item);
      closeMenu(false);
      S.sel = dev.id;
      if (!commit(placeOnShelfOps(doc(), dev.id, rk, item, slot), 'Put ' + dev.name + ' on ' + (shelf ? shelf.label : 'a shelf') + ' cell ' + (slot + 1))) {
        toast('That shelf cell is taken.', 'warn');
      }
      refocus(dev.id);
    } else if (act === 'offshelf') {
      const po2 = {height: heightOf(doc(), Object.assign({}, dev, {rack: null})), face: p.face, side: 'full'};
      const u2 = firstFit(doc(), dev.rack.id, dev.id, po2);
      if (!u2) { toast('No free space for ' + dev.name + ' in this rack.', 'warn'); return; }
      closeMenu(false);
      S.sel = dev.id;
      tryPlace(dev.id, dev.rack.id, u2, po2, false);
      refocus(dev.id);
    } else if (act === 'dup') {
      closeMenu(false);
      duplicateDevice(dev.id);
    } else if (act === 'unrack') {
      closeMenu(false);
      commit(unplaceOps(doc(), dev.id), 'Unracked ' + dev.name);
      if (lst && typeof lst.focus === 'function') lst.focus();
      else focusFirst();
    } else if (act === 'open') {
      closeMenu(false);
      select1(dev.id);
      if (ctx.openInspector) ctx.openInspector({type: 'device', id: dev.id});
    }
  }

  function itemAct(t, act, v) {
    const it = findItem(t.rack, t.id);
    if (!it) { closeMenu(false); return; }
    const rack = findRack(doc(), t.rack);
    if (act === 'icolor') {
      commit(updateItemOps(doc(), t.rack, t.id, {color: v || null}), v ? 'Coloured ' + it.label : 'Cleared the colour of ' + it.label);
    } else if (act === 'slots') {
      const n = parseInt(v, 10);
      if (n === it.slots) return;
      const lost = shelfCells(doc(), t.rack, t.id).filter(function (c) { return c.device && c.slot >= n; }).length;
      const go = lost ? confirmScope(ctx, {verb: 'Shrink', noun: it.label, ok: 'Shrink shelf',
        detail: lost + (lost === 1 ? ' device on a removed cell becomes' : ' devices on removed cells become') + ' unracked.'}) : Promise.resolve(true);
      go.then(function (ok) {
        if (ok) commit(updateItemOps(doc(), t.rack, t.id, {slots: n}), it.label + ': ' + n + (n === 1 ? ' cell' : ' cells'));
      });
    } else if (act === 'height') {
      const hgt = parseInt(v, 10);
      if (!(hgt >= 1)) return;
      const f = itemFits(doc(), t.rack, t.id, it.u, {height: hgt});
      if (!f.ok) { toast(refusal(f, rack, t.rack, it.u), 'warn'); return; }
      commit(updateItemOps(doc(), t.rack, t.id, {height: hgt}), it.label + ': ' + hgt + 'U');
    } else if (act === 'iface') {
      if (v === it.face) return;
      moveItem(t.rack, t.id, t.rack, it.u, v, false);
    } else if (act === 'idepth') {
      if (v === it.depth) return;
      const f2 = itemFits(doc(), t.rack, t.id, it.u, {depth: v});
      if (!f2.ok) { toast(refusal(f2, rack, t.rack, it.u), 'warn'); return; }
      commit(updateItemOps(doc(), t.rack, t.id, {depth: v}), it.label + ': ' + v + ' depth');
    } else if (act === 'idup') {
      closeMenu(false);
      duplicateItem(t.rack, t.id);
    } else if (act === 'idel') {
      closeMenu(false);
      deleteItem(t.rack, t.id);
    }
  }

  function doPrint(done) {
    closeMenu(false);
    S.print = true;
    render();
    const fin = function () {
      window.removeEventListener('afterprint', fin);
      S.print = false;
      render();
      if (typeof done === 'function') done();
    };
    window.addEventListener('afterprint', fin);
    if (typeof window.print === 'function') window.print();
  }

  // Rack page: pick a device (any room, racked or not) and place it at the first free RU of this face.
  function addDevice() {
    const rack = findRack(doc(), S.rack);
    if (!rack || readOnly() || typeof ctx.pickDevice !== 'function') return;
    Promise.resolve(ctx.pickDevice({title: 'Add a device to ' + rack.name, room: rack.room || '*'})).then(function (id) {
      if (!id) return;
      const dev = deviceById(doc(), id);
      if (!dev) return;
      const po = dev.rack && dev.rack.id === rack.id ? {} : Object.assign(placeDefaults(Object.assign({}, dev, {rack: null})), {face: curFace()});
      const u = firstFit(doc(), rack.id, id, po);
      if (!u) { ctx.toast('No free space for ' + dev.name + ' in ' + rack.name + '.', 'warn'); return; }
      S.sel = id;
      tryPlace(id, rack.id, u, po, false);
      refocus(id);
    });
  }

  // ------------------------------------------------------------- events
  listen(racksEl, 'pointerdown', function (e) {
    if (e.target.closest('.rk-more,.rk-facetoggle')) return;
    const t = targetOf(e.target);
    if (!t || (e.pointerType === 'mouse' && e.button > 0)) return;
    const node = t.kind === 'item' ? e.target.closest('.rk-item') : e.target.closest('.rk-block');
    startPress(e, t);
    if (readOnly()) {
      if (t.kind === 'item') selectItem(t.rack, t.id); else select1(t.id);
      return;
    }
    if (t.kind === 'item') startItemDrag(e, t.rack, t.id, node);
    else startDrag(e, t.id, false, node);
  });
  listen(racksEl, 'pointerup', function (e) {
    cancelPress();
    if (!S.drag && !targetOf(e.target) && !e.target.closest('.rk-more,.rk-facetoggle') && (S.sel || S.selItem)) {
      if (S.sel) select1(null);
      else { S.selItem = null; render(); }
    }
  });
  listen(racksEl, 'click', function (e) {
    const more = e.target.closest('.rk-more');
    if (more) {
      e.preventDefault();
      const t = targetOf(more);
      if (S.menu && S.menu.t.kind === (t && t.kind) && S.menu.t.id === t.id) { closeMenu(true); return; }
      openMenu(t);
      return;
    }
    const tog = e.target.closest('.rk-facetoggle');
    if (tog) {
      S.single = tog.getAttribute('data-face') === 'rear' ? 'rear' : 'front';
      const rk = tog.closest('.rk-rack');
      const rackId = rk ? rk.getAttribute('data-rack') : '';
      render();
      const again = racksEl.querySelector('.rk-rack[data-rack="' + cssq(rackId) + '"] .rk-facetoggle');
      if (again) again.focus();
    }
  });
  listen(racksEl, 'contextmenu', function (e) {
    const t = targetOf(e.target);
    if (!t) return;
    e.preventDefault();
    cancelPress();
    if (S.drag && !S.drag.moved) { release(S.drag.src, S.drag.pointer); S.drag = null; ghost.hidden = true; }
    if (S.menu && S.menu.t.kind === t.kind && S.menu.t.id === t.id) return;
    openMenu(t, e.clientX || e.clientY ? {x: e.clientX, y: e.clientY} : null);
  });
  (list ? [racksEl, list] : [racksEl]).forEach(function (t) {
    listen(t, 'pointermove', onDragMove);
    listen(t, 'pointerup', onDragUp);
    listen(t, 'pointercancel', onDragCancel);
  });
  // One-finger / mouse drag on the background scrolls (the canvas has touch-action: none).
  let pan = null;
  listen(viewport, 'pointerdown', function (e) {
    if (e.target.closest('.rk-block,.rk-item,button,select,input,a') || (e.pointerType === 'mouse' && e.button > 0)) return;
    pan = {id: e.pointerId, x: e.clientX, y: e.clientY, sl: viewport.scrollLeft, st: viewport.scrollTop};
  });
  listen(viewport, 'pointermove', function (e) {
    if (!pan || pan.id !== e.pointerId || S.drag) return;
    viewport.scrollLeft = pan.sl - (e.clientX - pan.x);
    viewport.scrollTop = pan.st - (e.clientY - pan.y);
  });
  listen(viewport, 'pointerup', function () { pan = null; });
  listen(viewport, 'pointercancel', function () { pan = null; });
  listen(viewport, 'keydown', onKey);
  listen(viewport, 'touchmove', function (e) { if (S.drag || S.ext || e.touches.length >= 2) e.preventDefault(); }, {passive: false});
  ['gesturestart', 'gesturechange', 'gestureend'].forEach(function (t) { listen(viewport, t, function (e) { e.preventDefault(); }, {passive: false}); });
  listen(store, 'doc', render);
  if (!embedded) listen(store, 'room', function () { S.rack = '*'; render(); });
  listen(store, 'mode', render);
  listen(store, 'highlight', function (e) { S.highlight = e.detail; render(); });
  listen(store, 'selection', function (e) {
    const sel = e.detail;
    const id = sel && sel.type === 'device' ? sel.id : null;
    if (id !== S.sel) { S.sel = id; if (id) S.selItem = null; render(); }
  });
  function onResize() {
    if (layout() !== S.layout && (S.face === 'both' || S.menu)) { closeMenu(false); render(); return; }
    fitWidth();
  }
  if (typeof ResizeObserver === 'function') {
    const ro = new ResizeObserver(onResize);
    ro.observe(viewport);
    offs.push(function () { ro.disconnect(); });
  }
  if (typeof window !== 'undefined') listen(window, 'resize', onResize);

  // ---------------------------------------------------------------- api
  function getState() { return {rack: S.rack, face: S.face, display: displayMode(), annotate: annotateField()}; }

  function setFaceMode(f) {
    S.face = normFace(f);
    if (S.face !== 'both') S.single = S.face;
  }

  function assign(s) {
    if ('rack' in s && !embedded) S.rack = s.rack || '*';
    if ('face' in s) setFaceMode(s.face);
  }

  function focus(sel) {
    const id = sel && (sel.device || sel.id);
    const dev = id && deviceById(doc(), id);
    if (sel && sel.type === 'rack') { if (!embedded) { S.rack = sel.id; render(); } return; }
    if (!dev || !dev.rack || !dev.rack.id) return;
    if (embedded && dev.rack.id !== S.rack) return;
    if (!embedded) S.rack = '*';
    S.sel = id;
    S.selItem = null;
    const p = placement(doc(), dev);
    if (!embedded && p.depth !== 'full' && facesShown().indexOf(p.face) < 0) {
      if (S.face === 'both') S.single = p.face; else S.face = p.face;
    }
    render();
    refocus(id);
  }

  const api = {
    render: render,
    destroy: function () {
      S.dead = true;
      cancelPress();
      endExternal();
      closeMenu(false);
      offs.forEach(function (off) { off(); });
      if (ownRoot) {
        if (root.parentNode) root.parentNode.removeChild(root);
      } else {
        [viewport, ghost].forEach(function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
      }
    },
    focus: focus,
    // A shell route for this view: `sub` front|rear|both sets the face, then the store selection is focused.
    route: function (r) {
      if (r && FACE_MODES.indexOf(r.sub) >= 0 && r.sub !== S.face) { setFaceMode(r.sub); render(); }
      if (store.selection) focus(store.selection);
    },
    setFace: function (face) {
      const f = normFace(face);
      if (f === S.face) return;
      setFaceMode(f);
      render();
    },
    getState: getState,
    setState: function (s) {
      if (!s) return;
      assign(s);
      render();
    },
    setOptions: function (opts2) {
      if (!opts2) return;
      assign(opts2);
      Object.keys(opts2).forEach(function (k) { if (k !== 'rack' && k !== 'face') S.options[k] = opts2[k]; });
      S.w = 0;
      render();
    },
    startDrag: startDrag,
    beginExternalDrag: beginExternalDrag,
    openMenu: function (t) { openMenu(t); },
    closeMenu: function () { closeMenu(false); },
    print: doPrint,
    addToRack: addToRack,
    addDevice: addDevice,
    templateInfo: templateInfo,
    _state: S,
  };
  viewport.__rkElevation = api;

  const initial = store.selection;
  if (initial && initial.type === 'device') S.sel = initial.id;
  render();

  return api;
}
