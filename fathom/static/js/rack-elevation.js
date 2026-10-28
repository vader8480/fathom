// Rack elevation (§6.7, docs/ui-audit.md B.3 RK): one or more racks drawn as
// front/rear faces with device blocks, the drag ghost, drag within and between
// racks and from/to a device list, keyboard moves, selection and highlight,
// fit-to-width and print. rack.js builds the landing chrome (toolbar, rack
// form, unracked explorer) around it; page-rack.js embeds one rack.
//
// createElevation(el, ctx, opts); every opts key is optional:
//   rack      one rack id: embedded mode (.rk-embedded, no title links, focus()
//             ignores other racks, setState() ignores `rack`).
//   racks     () -> the racks to draw without `rack` (default: roomRacks for the
//             store room); state.rack '*' draws them all, an id draws that one.
//   face      'front' | 'rear' (default front).
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
// Returns {render, destroy, setFace(face), getState() -> {rack, face},
//   setState({rack?, face?}), setOptions(o), focus(sel), route(r),
//   startDrag(e, deviceId, fromList, grabEl), print(done), addToRack(deviceId, rackId?),
//   addDevice(), templateInfo(dev), _state}. setOptions sets `face` and `rack`
//   like setState and merges every other key into _state.options, then renders.
import { h } from './dom.js';
import {
  RU_PX, RACK_W, findRack, rackUnits, heightOf, placement, faceBlocks, collisions, outOfRange,
  fits, placeOps, unplaceOps, firstFit, uToY, yToU, ruLabel,
} from './rack-core.js';

const DRAG_SLOP = 4;
const MIN_RACK_W = 200;

export function disciplineOf(dev, vocab) {
  if (dev.discipline) return dev.discipline;
  const k = vocab && vocab.kinds && vocab.kinds[dev.kind];
  return (k && k.discipline) || 'other';
}

export function discColor(disc, vocab) {
  const d = vocab && vocab.disciplines && vocab.disciplines[disc];
  return (d && d.color) || '#9aa3b5';
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

function pct(px) {
  return (px / RACK_W * 100) + '%';
}

function px(v) {
  return parseFloat(v) || 0;
}

export function createElevation(el, ctx, opts) {
  const o = opts || {};
  const embedded = !!o.rack;
  const store = ctx.store;
  const vocab = ctx.vocab || store.vocab || {};
  const lst = o.list && o.list.el ? o.list : null;
  const list = lst ? lst.el : null;
  const S = {rack: embedded ? o.rack : '*', face: o.face === 'rear' ? 'rear' : 'front', sel: null, print: false, drag: null, tpl: {}, highlight: null, w: 0, options: {}};
  const listeners = [];
  function on(target, type, fn, opts2) {
    target.addEventListener(type, fn, opts2);
    listeners.push([target, type, fn, opts2]);
  }

  const ownRoot = !o.root;
  const root = o.root || h('div', {class: 'rk-root' + (embedded ? ' rk-embedded' : '')});
  const racksEl = h('div', {class: 'rk-racks'});
  const viewport = h('div', {class: 'rk-viewport', role: 'application', 'aria-label': 'Rack elevations. Tab to a device; arrow up and down move it one RU, Delete unracks it, Enter opens it.'}, [racksEl]);
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
  function commit(ops, label) {
    if (!ops || !ops.length) return false;
    if (readOnly()) { ctx.toast('Read-only: changes are not allowed here.', 'warn'); return false; }
    ctx.commit(ops, label);
    return true;
  }
  function devName(id) { const d = deviceById(doc(), id); return d ? d.name : id; }
  function rackHref(id) {
    if (typeof ctx.routeHref !== 'function') return '';
    const href = ctx.routeHref({view: 'racks', id: id, tab: '', sub: '', query: {}});
    return href && href !== '#' ? href : '';
  }

  // Template ru/width (FR-RACK-02 default height); fetched from the library when an API exists.
  function templateInfo(dev) {
    const tid = dev && dev.template;
    if (!tid) return null;
    const local = (doc().templates || []).filter(function (t) { return t.id === tid; })[0];
    if (local) return {ru: local.ru, width: local.width};
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
    const po = {face: S.face};
    if (t && parseInt(t.ru, 10) >= 1) po.height = parseInt(t.ru, 10);
    else po.height = heightOf(doc(), dev);
    if (t && t.width === 'half') po.side = 'left';
    return po;
  }

  // ---------------------------------------------------------- rendering
  function render() {
    const rs = racks();
    if (!embedded && S.rack !== '*' && !rs.some(function (r) { return r.id === S.rack; })) S.rack = '*';
    const ro = readOnly();
    root.classList.toggle('rk-readonly', ro);
    root.classList.toggle('rk-printing', S.print);
    S.k = S.print ? 1 : ruScale();
    root.style.setProperty('--rk-ru', (RU_PX * S.k) + 'px');
    renderRacks();
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
    rs.forEach(function (rack) {
      const faces = S.print ? ['front', 'rear'] : [S.face];
      const faceEls = faces.map(function (f) { return renderFace(rack, f); });
      const coll = collisions(doc(), rack.id);
      const oor = outOfRange(doc(), rack.id);
      const warn = h('ul', {class: 'rk-warnings', 'aria-label': 'Rack warnings'});
      coll.filter(function (c) { return S.print || c.face === S.face; }).forEach(function (c) {
        warn.appendChild(h('li', {text: 'U' + ruLabel(rack, c.u) + ' ' + c.face + ': ' + devName(c.a) + ' overlaps ' + devName(c.b)}));
      });
      oor.forEach(function (id) { warn.appendChild(h('li', {text: devName(id) + ' is outside the rack\'s ' + rackUnits(rack) + ' RU'})); });
      const loc = (doc().locations || []).filter(function (l) { return l.id === rack.location; })[0];
      const href = embedded || S.print ? '' : rackHref(rack.id);
      const name = href ? h('a', {class: 'rk-pagelink', href: href, title: 'Open the ' + rack.name + ' page', text: rack.name}) : rack.name;
      racksEl.appendChild(h('section', {class: 'rk-rack', 'data-rack': rack.id, 'aria-label': rack.name}, [
        h('h3', {class: 'rk-title'}, [name, h('span', {class: 'rk-sub', text: ' ' + rackUnits(rack) + 'U' + (loc ? ' \u00b7 ' + loc.name : '') + (rack.numbering === 'top_down' ? ' \u00b7 numbered top-down' : '')})]),
        h('div', {class: 'rk-faces'}, faceEls),
        warn.childNodes.length ? warn : null,
      ]));
    });
    fitWidth();
  }

  // Shrink the rack drawing to the viewport (never wider than RACK_W); blocks are
  // positioned in % of the slot width, so only --rk-w changes. --rk-w lives on
  // .rk-root because the print sheet overrides it there.
  function fitWidth() {
    if (!root.isConnected) return;
    const rack = racksEl.querySelector('.rk-rack');
    const frame = rack && rack.querySelector('.rk-frame');
    const slots = frame && frame.querySelector('.rk-slots');
    if (S.print || !slots) { root.style.removeProperty('--rk-w'); S.w = 0; return; }
    const vs = getComputedStyle(viewport);
    const rsx = getComputedStyle(rack);
    const avail = viewport.clientWidth - px(vs.paddingLeft) - px(vs.paddingRight);
    if (avail <= 0) return;
    const chrome = px(rsx.paddingLeft) + px(rsx.paddingRight) + px(rsx.borderLeftWidth) + px(rsx.borderRightWidth) + (frame.offsetWidth - slots.offsetWidth);
    const w = Math.max(MIN_RACK_W, Math.min(RACK_W, Math.floor(avail - chrome)));
    if (w === S.w) return;
    S.w = w;
    if (w === RACK_W) root.style.removeProperty('--rk-w');
    else root.style.setProperty('--rk-w', w + 'px');
  }

  function renderFace(rack, face) {
    const units = rackUnits(rack);
    const k = S.k || 1;
    const H = units * RU_PX * k;
    const left = h('div', {class: 'rk-rail', 'aria-hidden': 'true', style: 'height:' + H + 'px'});
    const right = h('div', {class: 'rk-rail', 'aria-hidden': 'true', style: 'height:' + H + 'px'});
    const slots = h('div', {class: 'rk-slots', 'data-rack': rack.id, 'data-face': face, style: 'width:var(--rk-w, ' + RACK_W + 'px);height:' + H + 'px'});
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
    const hl = S.highlight && S.highlight.devices && S.highlight.devices.length ? S.highlight.devices : null;
    // wide blocks first so half-width / colliding blocks stay visible on top
    faceBlocks(doc(), rack.id, face).sort(function (a, b) { return b.w - a.w || (a.behind ? -1 : 0) - (b.behind ? -1 : 0); }).forEach(function (b) {
      const dev = deviceById(doc(), b.device) || {id: b.device, name: b.device};
      const color = discColor(disciplineOf(dev, vocab), vocab);
      const cls = 'rk-block' + (b.behind ? ' rk-behind' : '') + (bad[b.device] ? ' rk-collide' : '') + (S.sel === b.device ? ' rk-selected' : '')
        + (dev.status === 'planned' ? ' rk-planned' : '') + (b.height * k === 1 ? ' rk-1u' : '') + (hl ? (hl.indexOf(b.device) >= 0 ? ' rk-hl' : ' rk-dim') : '');
      const label = dev.name + ', U' + ruLabel(rack, b.u) + (b.height > 1 ? '\u2013' + ruLabel(rack, b.u + b.height - 1) : '') + ', ' + b.height + 'U, '
        + b.face + (b.side !== 'full' ? ' ' + b.side : '') + (b.behind ? ' (seen from the ' + face + ')' : '') + (bad[b.device] ? ', collides' : '');
      slots.appendChild(h('div', {
        class: cls, 'data-device': b.device, 'data-rack': rack.id, tabindex: S.print ? null : '0', role: 'button',
        'aria-label': label + (readOnly() ? '' : '. Arrow up or down moves it, Delete unracks it, Enter opens it'),
        style: 'left:' + pct(b.x) + ';top:' + (b.y * k) + 'px;width:' + pct(b.w) + ';height:' + (b.h * k) + 'px;--rk-color:' + color,
        title: label,
      }, [
        h('span', {class: 'rk-stripe', 'aria-hidden': 'true'}),
        h('span', {class: 'rk-bname', text: (b.behind ? 'Rear of ' : '') + dev.name + (dev.count > 1 ? ' \u00d7' + dev.count : '')}),
        h('span', {class: 'rk-bmodel', text: modelLine(dev)}),
        h('span', {class: 'rk-bru', text: b.height + 'U'}),
      ]));
    });
    return h('figure', {class: 'rk-face', 'data-face': face}, [
      h('figcaption', {text: face === 'front' ? 'Front' : 'Rear'}),
      h('div', {class: 'rk-frame'}, [left, slots, right]),
    ]);
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
        ctx.toast('Placed ' + what + ' over ' + f.conflicts.map(devName).join(', ') + ' (collision warning).', 'warn');
      }
      return true;
    }
    if (!f.ok) {
      const msg = f.reason === 'occupied' ? 'U' + ruLabel(rack, u) + ' is occupied by ' + f.conflicts.map(devName).join(', ') + '. Hold Alt/Option to force.'
        : f.reason === 'out_of_range' ? 'That does not fit inside ' + (rack ? rack.name : rackId) + '.' : 'Unknown rack.';
      ctx.toast(msg, 'warn');
      announce(msg);
      return false;
    }
    commit(placeOps(doc(), id, rackId, u, po), 'Racked ' + what);
    return true;
  }

  function announce(msg) {
    const live = document.getElementById('fathom-live');
    if (live) live.textContent = msg;
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
    const b = racksEl.querySelector('.rk-block[data-device="' + String(id).replace(/["\\]/g, '\\$&') + '"]');
    if (b) b.focus();
  }

  // ----------------------------------------------------------- dragging
  function capture(target, id) { try { target.setPointerCapture(id); } catch (err) { /* synthetic pointer */ } }

  function slotRects() {
    return Array.prototype.slice.call(racksEl.querySelectorAll('.rk-slots')).map(function (s) {
      return {el: s, rack: s.getAttribute('data-rack'), face: s.getAttribute('data-face'), r: s.getBoundingClientRect()};
    });
  }

  function startDrag(e, id, fromList, grabEl) {
    const dev = deviceById(doc(), id);
    if (!dev || readOnly()) return;
    const p = dev.rack && dev.rack.id ? placement(doc(), dev) : null;
    const po = p ? {} : placeDefaults(dev);
    const height = p ? p.height : (po.height || 1);
    let grabY = (RU_PX * (S.k || 1) * height) / 2;
    if (!fromList) {
      const br = grabEl.getBoundingClientRect();
      grabY = e.clientY - br.top;
    }
    S.drag = {id: id, pointer: e.pointerId, x: e.clientX, y: e.clientY, moved: false, fromList: fromList, opts: po,
      height: height, side: p ? p.side : (po.side || 'full'), grabY: grabY, rects: slotRects(), target: null, src: grabEl};
    capture(grabEl, e.pointerId);
    e.preventDefault();
  }

  function inList(e) {
    if (!lst) return false;
    if (typeof lst.accept === 'function') return !!lst.accept(e);
    const lr = list.getBoundingClientRect();
    return lr.width > 0 && e.clientX >= lr.left && e.clientX <= lr.right && e.clientY >= lr.top && e.clientY <= lr.bottom;
  }

  function dragTarget(e, drag) {
    const d = drag || S.drag;
    for (let i = 0; i < d.rects.length; i++) {
      const s = d.rects[i];
      if (e.clientX >= s.r.left - 24 && e.clientX <= s.r.right + 24 && e.clientY >= s.r.top - RU_PX * (S.k || 1) && e.clientY <= s.r.bottom + RU_PX * (S.k || 1)) {
        const rack = findRack(doc(), s.rack);
        const u = yToU(rack, (e.clientY - s.r.top - d.grabY) / (S.k || 1), d.height);
        return {rack: s.rack, face: s.face, u: u, slot: s};
      }
    }
    if (inList(e)) return {unrack: true};
    return null;
  }

  function onDragMove(e) {
    const d = S.drag;
    if (!d || d.pointer !== e.pointerId) return;
    if (!d.moved && Math.hypot(e.clientX - d.x, e.clientY - d.y) < DRAG_SLOP) return;
    if (!d.moved && d.fromList && lst && typeof lst.onLift === 'function') lst.onLift();
    d.moved = true;
    const t = dragTarget(e);
    d.target = t;
    if (list) list.classList.toggle('rk-droptarget', !!(t && t.unrack && !d.fromList));
    const rr = root.getBoundingClientRect();
    if (t && t.rack) {
      const rack = findRack(doc(), t.rack);
      const po = Object.assign({}, d.opts, d.fromList ? {face: t.face} : {});
      const f = fits(doc(), t.rack, d.id, t.u, po);
      const half = t.slot.r.width / 2;
      ghost.hidden = false;
      ghost.className = 'rk-ghost ' + (f.ok ? 'rk-ok' : (e.altKey && f.reason === 'occupied' ? 'rk-force' : 'rk-bad'));
      ghost.style.left = (t.slot.r.left - rr.left + (d.side === 'right' ? half : 0)) + 'px';
      ghost.style.top = (t.slot.r.top - rr.top + uToY(rack, t.u, d.height) * (S.k || 1)) + 'px';
      ghost.style.width = (d.side === 'full' ? t.slot.r.width : half) + 'px';
      ghost.style.height = (d.height * RU_PX * (S.k || 1)) + 'px';
      ghost.textContent = devName(d.id) + ' \u00b7 U' + ruLabel(rack, t.u) + (f.ok ? '' : f.reason === 'occupied' ? ' \u00b7 occupied' : ' \u00b7 does not fit');
    } else {
      ghost.hidden = false;
      ghost.className = 'rk-ghost rk-float';
      ghost.style.left = (e.clientX - rr.left + 10) + 'px';
      ghost.style.top = (e.clientY - rr.top + 10) + 'px';
      ghost.style.width = '';
      ghost.style.height = '';
      ghost.textContent = devName(d.id) + (t && t.unrack ? ' \u00b7 unrack' : '');
    }
  }

  function onDragUp(e) {
    const d = S.drag;
    if (!d || d.pointer !== e.pointerId) return;
    S.drag = null;
    ghost.hidden = true;
    if (list) list.classList.remove('rk-droptarget');
    if (!d.moved) {
      if (!d.fromList) select1(d.id);
      return;
    }
    const t = dragTarget(e, d);
    if (t && t.rack) {
      const po = Object.assign({}, d.opts, d.fromList ? {face: t.face} : {});
      S.sel = d.id;
      tryPlace(d.id, t.rack, t.u, po, !!e.altKey);
      refocus(d.id);
    } else if (t && t.unrack && !d.fromList) {
      commit(unplaceOps(doc(), d.id), 'Unracked ' + devName(d.id));
    }
  }

  function onDragCancel() {
    S.drag = null;
    ghost.hidden = true;
    if (list) list.classList.remove('rk-droptarget');
  }

  function select1(id) {
    S.sel = id;
    ctx.select(id ? {type: 'device', id: id} : null);
    render();
    if (id) refocus(id);
  }

  // ----------------------------------------------------------- keyboard
  function onKey(e) {
    const b = e.target.closest('.rk-block');
    if (!b) return;
    const id = b.getAttribute('data-device');
    const rackId = b.getAttribute('data-rack');
    const dev = deviceById(doc(), id);
    if (!dev) return;
    if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && !readOnly()) {
      e.preventDefault();
      const p = placement(doc(), dev);
      S.sel = id;
      tryPlace(id, rackId, p.u + (e.key === 'ArrowUp' ? 1 : -1), {}, e.altKey);
      refocus(id);
    } else if ((e.key === 'Delete' || e.key === 'Backspace') && !readOnly()) {
      e.preventDefault();
      commit(unplaceOps(doc(), id), 'Unracked ' + dev.name);
      if (lst) {
        if (typeof lst.focus === 'function') lst.focus();
      } else {
        const first = racksEl.querySelector('.rk-block');
        if (first) first.focus();
      }
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      select1(id);
      if (ctx.openInspector) ctx.openInspector({type: 'device', id: id});
    } else if (e.key === 'Escape') {
      e.preventDefault();
      select1(null);
    }
  }

  function doPrint(done) {
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
      const po = dev.rack && dev.rack.id === rack.id ? {} : Object.assign(placeDefaults(Object.assign({}, dev, {rack: null})), {face: S.face});
      const u = firstFit(doc(), rack.id, id, po);
      if (!u) { ctx.toast('No free space for ' + dev.name + ' in ' + rack.name + '.', 'warn'); return; }
      S.sel = id;
      tryPlace(id, rack.id, u, po, false);
      refocus(id);
    });
  }

  // ------------------------------------------------------------- events
  on(racksEl, 'pointerdown', function (e) {
    const b = e.target.closest('.rk-block');
    if (!b || (e.pointerType === 'mouse' && e.button > 0)) return;
    if (readOnly()) { select1(b.getAttribute('data-device')); return; }
    startDrag(e, b.getAttribute('data-device'), false, b);
  });
  on(racksEl, 'pointerup', function (e) {
    if (!S.drag && !e.target.closest('.rk-block') && S.sel) select1(null);
  });
  (list ? [racksEl, list] : [racksEl]).forEach(function (t) {
    on(t, 'pointermove', onDragMove);
    on(t, 'pointerup', onDragUp);
    on(t, 'pointercancel', onDragCancel);
  });
  // One-finger / mouse drag on the background scrolls (the canvas has touch-action: none).
  let pan = null;
  on(viewport, 'pointerdown', function (e) {
    if (e.target.closest('.rk-block,button,select,input,a') || (e.pointerType === 'mouse' && e.button > 0)) return;
    pan = {id: e.pointerId, x: e.clientX, y: e.clientY, sl: viewport.scrollLeft, st: viewport.scrollTop};
  });
  on(viewport, 'pointermove', function (e) {
    if (!pan || pan.id !== e.pointerId || S.drag) return;
    viewport.scrollLeft = pan.sl - (e.clientX - pan.x);
    viewport.scrollTop = pan.st - (e.clientY - pan.y);
  });
  on(viewport, 'pointerup', function () { pan = null; });
  on(viewport, 'pointercancel', function () { pan = null; });
  on(viewport, 'keydown', onKey);
  on(viewport, 'touchmove', function (e) { if (S.drag || e.touches.length >= 2) e.preventDefault(); }, {passive: false});
  ['gesturestart', 'gesturechange', 'gestureend'].forEach(function (t) { on(viewport, t, function (e) { e.preventDefault(); }, {passive: false}); });
  on(store, 'doc', render);
  if (!embedded) on(store, 'room', function () { S.rack = '*'; render(); });
  on(store, 'mode', render);
  on(store, 'highlight', function (e) { S.highlight = e.detail; render(); });
  on(store, 'selection', function (e) {
    const sel = e.detail;
    const id = sel && sel.type === 'device' ? sel.id : null;
    if (id !== S.sel) { S.sel = id; render(); }
  });
  if (typeof ResizeObserver === 'function') {
    const ro = new ResizeObserver(function () { fitWidth(); });
    ro.observe(viewport);
    listeners.push([{removeEventListener: function () { ro.disconnect(); }}, '', null, null]);
  } else {
    on(window, 'resize', fitWidth);
  }

  // ---------------------------------------------------------------- api
  function getState() { return {rack: S.rack, face: S.face}; }

  function assign(s) {
    if ('rack' in s && !embedded) S.rack = s.rack || '*';
    if ('face' in s) S.face = s.face === 'rear' ? 'rear' : 'front';
  }

  function focus(sel) {
    const id = sel && (sel.device || sel.id);
    const dev = id && deviceById(doc(), id);
    if (sel && sel.type === 'rack') { if (!embedded) { S.rack = sel.id; render(); } return; }
    if (!dev || !dev.rack || !dev.rack.id) return;
    if (embedded && dev.rack.id !== S.rack) return;
    if (!embedded) S.rack = '*';
    S.sel = id;
    const p = placement(doc(), dev);
    if (!embedded && p.face !== S.face && p.depth !== 'full') S.face = p.face;
    render();
    refocus(id);
  }

  const api = {
    render: render,
    destroy: function () {
      listeners.forEach(function (l) { l[0].removeEventListener(l[1], l[2], l[3]); });
      if (ownRoot) {
        if (root.parentNode) root.parentNode.removeChild(root);
      } else {
        [viewport, ghost].forEach(function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
      }
    },
    focus: focus,
    // A shell route for this view: `sub` front|rear sets the face, then the store selection is focused.
    route: function (r) {
      if (r && (r.sub === 'front' || r.sub === 'rear') && r.sub !== S.face) { S.face = r.sub; render(); }
      if (store.selection) focus(store.selection);
    },
    setFace: function (face) {
      const f = face === 'rear' ? 'rear' : 'front';
      if (f === S.face) return;
      S.face = f;
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
      render();
    },
    startDrag: startDrag,
    print: doPrint,
    addToRack: addToRack,
    addDevice: addDevice,
    templateInfo: templateInfo,
    _state: S,
  };

  const initial = store.selection;
  if (initial && initial.type === 'device') S.sel = initial.id;
  render();

  return api;
}
