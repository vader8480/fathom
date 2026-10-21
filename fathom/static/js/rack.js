// Rack elevations: front/rear faces, drag devices to RU with collision
// highlighting, add devices from the room, printable. mount(el, ctx) (§6.4, §6.7).
import {
  RU_PX, RACK_W, findRack, rackUnits, heightOf, placement, faceBlocks, collisions, outOfRange,
  fits, placeOps, unplaceOps, firstFit, uToY, yToU, ruLabel, newRackOps, deleteRackOps,
} from './rack-core.js';

const DRAG_SLOP = 4;

function h(tag, attrs, children) {
  const n = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (v == null || v === false) return;
      if (k === 'text') n.textContent = v;
      else if (k === 'class') n.className = v;
      else if (k === 'style') n.setAttribute('style', v);
      else n.setAttribute(k, v === true ? '' : v);
    });
  }
  (children || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
  return n;
}

function disciplineOf(dev, vocab) {
  if (dev.discipline) return dev.discipline;
  const k = vocab && vocab.kinds && vocab.kinds[dev.kind];
  return (k && k.discipline) || 'other';
}

function discColor(disc, vocab) {
  const d = vocab && vocab.disciplines && vocab.disciplines[disc];
  return (d && d.color) || '#9aa3b5';
}

function deviceById(doc, id) {
  const ds = (doc && doc.devices) || [];
  for (let i = 0; i < ds.length; i++) if (ds[i].id === id) return ds[i];
  return null;
}

// 44 px per RU on coarse pointers (FR-MOB-02); geometry from rack-core is scaled by ruScale().
function ruScale() {
  return typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches ? 2 : 1;
}

function modelLine(dev) {
  return ((dev.manufacturer || '') + ' ' + (dev.model || '')).trim() || dev.sub || '';
}

export function mount(el, ctx) {
  const store = ctx.store;
  const vocab = ctx.vocab || store.vocab || {};
  const S = {rack: '*', face: 'front', sel: null, print: false, drag: null, tpl: {}, editing: null, highlight: null};
  const listeners = [];
  function on(target, type, fn, opts) {
    target.addEventListener(type, fn, opts);
    listeners.push([target, type, fn, opts]);
  }

  el.innerHTML = '';
  const root = h('div', {class: 'rk-root'});
  const select = h('select', {id: 'rk-select', 'aria-label': 'Rack'});
  const btnAdd = h('button', {id: 'rk-add', type: 'button', class: 'rk-btn', text: 'New rack'});
  const btnEdit = h('button', {id: 'rk-edit', type: 'button', class: 'rk-btn', text: 'Edit rack'});
  const btnFace = h('button', {id: 'rk-face', type: 'button', class: 'rk-btn', 'aria-pressed': 'false'});
  const btnPrint = h('button', {id: 'rk-print', type: 'button', class: 'rk-btn', text: 'Print'});
  const readout = h('span', {class: 'rk-readout', role: 'status'});
  const toolbar = h('div', {class: 'rk-toolbar', role: 'toolbar', 'aria-label': 'Rack tools'}, [
    h('span', {class: 'rk-group'}, [select, btnAdd, btnEdit]),
    h('span', {class: 'rk-group'}, [btnFace, btnPrint]),
    readout,
  ]);
  const list = h('ul', {id: 'rk-unracked', class: 'rk-devlist', 'aria-label': 'Unracked devices'});
  const side = h('aside', {class: 'rk-side'}, [
    h('h3', {text: 'Unracked devices'}),
    h('p', {class: 'rk-hint', text: 'Drag by the grip onto a rack, or press Add. Drop a racked device here to unrack it. Hold Alt/Option to force a drop onto an occupied RU.'}),
    list,
  ]);
  const racksEl = h('div', {class: 'rk-racks'});
  const viewport = h('div', {class: 'rk-viewport', role: 'application', 'aria-label': 'Rack elevations. Tab to a device; arrow up and down move it one RU, Delete unracks it, Enter opens it.'}, [racksEl]);
  const form = h('form', {class: 'rk-form', hidden: true, 'aria-label': 'Rack'});
  const ghost = h('div', {class: 'rk-ghost', hidden: true, 'aria-hidden': 'true'});
  root.appendChild(toolbar);
  root.appendChild(form);
  root.appendChild(h('div', {class: 'rk-body'}, [side, viewport]));
  root.appendChild(ghost);
  el.appendChild(root);

  function doc() { return store.doc; }
  function readOnly() { return !!store.readOnly; }
  function room() { return store.room || ''; }
  function racks() {
    const r = room();
    return (doc().racks || []).filter(function (k) { return r === '*' || !r || (k.room || '') === r; })
      .slice().sort(function (a, b) { return (a.order == null ? 1e9 : a.order) - (b.order == null ? 1e9 : b.order); });
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
    const o = {face: S.face};
    if (t && parseInt(t.ru, 10) >= 1) o.height = parseInt(t.ru, 10);
    else o.height = heightOf(doc(), dev);
    if (t && t.width === 'half') o.side = 'left';
    return o;
  }

  // ---------------------------------------------------------- rendering
  function render() {
    const rs = racks();
    if (S.rack !== '*' && !rs.some(function (r) { return r.id === S.rack; })) S.rack = '*';
    const ro = readOnly();
    root.classList.toggle('rk-readonly', ro);
    root.classList.toggle('rk-printing', S.print);
    S.k = S.print ? 1 : ruScale();
    root.style.setProperty('--rk-ru', (RU_PX * S.k) + 'px');
    select.innerHTML = '';
    select.appendChild(h('option', {value: '*', text: rs.length ? 'All racks (' + rs.length + ')' : 'No racks in this room'}));
    rs.forEach(function (r) { select.appendChild(h('option', {value: r.id, text: r.name, selected: r.id === S.rack})); });
    btnAdd.disabled = ro;
    btnEdit.disabled = ro || S.rack === '*';
    btnFace.textContent = S.face === 'front' ? 'Showing front' : 'Showing rear';
    btnFace.setAttribute('aria-pressed', S.face === 'rear' ? 'true' : 'false');
    btnFace.setAttribute('aria-label', 'Showing ' + S.face + ' face. Switch to ' + (S.face === 'front' ? 'rear' : 'front'));
    renderRacks();
    renderList();
  }

  function renderRacks() {
    racksEl.innerHTML = '';
    const rs = shownRacks();
    if (!rs.length) {
      racksEl.appendChild(h('p', {class: 'rk-empty', text: readOnly() ? 'No racks in this room.' : 'No racks in this room yet. Press "New rack" to create one.'}));
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
      racksEl.appendChild(h('section', {class: 'rk-rack', 'data-rack': rack.id, 'aria-label': rack.name}, [
        h('h3', {class: 'rk-title'}, [rack.name, h('span', {class: 'rk-sub', text: ' ' + rackUnits(rack) + 'U' + (loc ? ' \u00b7 ' + loc.name : '') + (rack.numbering === 'top_down' ? ' \u00b7 numbered top-down' : '')})]),
        h('div', {class: 'rk-faces'}, faceEls),
        warn.childNodes.length ? warn : null,
      ]));
    });
  }

  function renderFace(rack, face) {
    const units = rackUnits(rack);
    const k = S.k || 1;
    const H = units * RU_PX * k;
    const left = h('div', {class: 'rk-rail', 'aria-hidden': 'true', style: 'height:' + H + 'px'});
    const right = h('div', {class: 'rk-rail', 'aria-hidden': 'true', style: 'height:' + H + 'px'});
    const slots = h('div', {class: 'rk-slots', 'data-rack': rack.id, 'data-face': face, style: 'width:' + RACK_W + 'px;height:' + H + 'px'});
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
        style: 'left:' + b.x + 'px;top:' + (b.y * k) + 'px;width:' + b.w + 'px;height:' + (b.h * k) + 'px;--rk-color:' + color,
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

  function renderList() {
    list.innerHTML = '';
    const r = room();
    const devs = (doc().devices || []).filter(function (d) { return !d.auto && !(d.rack && d.rack.id); });
    const inRoom = devs.filter(function (d) { return r === '*' || (d.room || '') === r; });
    const shared = r && r !== '*' ? devs.filter(function (d) { return (d.room || '') === ''; }) : [];
    function item(d) {
      templateInfo(d);
      const grip = h('span', {class: 'rk-grip', 'data-device': d.id, 'aria-hidden': 'true', title: 'Drag onto a rack', text: '\u283f'});
      const add = h('button', {type: 'button', class: 'rk-btn rk-addbtn', 'data-device': d.id, 'aria-label': 'Add ' + d.name + ' to a rack', disabled: readOnly() || !racks().length, text: 'Add'});
      return h('li', {class: 'rk-devitem', 'data-device': d.id}, [
        readOnly() ? null : grip,
        h('span', {class: 'rk-dot', style: 'background:' + discColor(disciplineOf(d, vocab), vocab)}),
        h('span', {class: 'rk-devname', text: d.name}),
        add,
      ]);
    }
    if (!inRoom.length && !shared.length) list.appendChild(h('li', {class: 'rk-hint', text: 'Every device in this room is racked.'}));
    inRoom.forEach(function (d) { list.appendChild(item(d)); });
    if (shared.length) {
      list.appendChild(h('li', {class: 'rk-subhead', text: 'Shared inventory'}));
      shared.forEach(function (d) { list.appendChild(item(d)); });
    }
  }

  // ------------------------------------------------------------ placing
  function tryPlace(id, rackId, u, opts, force) {
    const rack = findRack(doc(), rackId);
    const o = Object.assign({}, opts || {});
    const f = fits(doc(), rackId, id, u, o);
    const what = devName(id) + ' at U' + ruLabel(rack, u) + ' in ' + (rack ? rack.name : rackId);
    if (!f.ok && f.reason === 'occupied' && force) {
      o.force = true;
      if (commit(placeOps(doc(), id, rackId, u, o), 'Racked ' + what + ' (collision)')) {
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
    commit(placeOps(doc(), id, rackId, u, o), 'Racked ' + what);
    return true;
  }

  function announce(msg) {
    const live = document.getElementById('fathom-live');
    if (live) live.textContent = msg;
  }

  function addToRack(id) {
    const dev = deviceById(doc(), id);
    const target = S.rack !== '*' ? S.rack : (racks()[0] && racks()[0].id);
    if (!dev || !target) return;
    const o = placeDefaults(dev);
    const u = firstFit(doc(), target, id, o);
    if (!u) { ctx.toast('No free space for ' + dev.name + ' in ' + findRack(doc(), target).name + '.', 'warn'); return; }
    S.sel = id;
    tryPlace(id, target, u, o, false);
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
    const opts = p ? {} : placeDefaults(dev);
    const height = p ? p.height : (opts.height || 1);
    let grabY = (RU_PX * (S.k || 1) * height) / 2;
    if (!fromList) {
      const br = grabEl.getBoundingClientRect();
      grabY = e.clientY - br.top;
    }
    S.drag = {id: id, pointer: e.pointerId, x: e.clientX, y: e.clientY, moved: false, fromList: fromList, opts: opts,
      height: height, side: p ? p.side : (opts.side || 'full'), grabY: grabY, rects: slotRects(), target: null, src: grabEl};
    capture(grabEl, e.pointerId);
    e.preventDefault();
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
    const lr = list.getBoundingClientRect();
    if (e.clientX >= lr.left && e.clientX <= lr.right && e.clientY >= lr.top && e.clientY <= lr.bottom) return {unrack: true};
    return null;
  }

  function onDragMove(e) {
    const d = S.drag;
    if (!d || d.pointer !== e.pointerId) return;
    if (!d.moved && Math.hypot(e.clientX - d.x, e.clientY - d.y) < DRAG_SLOP) return;
    d.moved = true;
    const t = dragTarget(e);
    d.target = t;
    list.classList.toggle('rk-droptarget', !!(t && t.unrack && !d.fromList));
    const rr = root.getBoundingClientRect();
    if (t && t.rack) {
      const rack = findRack(doc(), t.rack);
      const o = Object.assign({}, d.opts, d.fromList ? {face: t.face} : {});
      const f = fits(doc(), t.rack, d.id, t.u, o);
      ghost.hidden = false;
      ghost.className = 'rk-ghost ' + (f.ok ? 'rk-ok' : (e.altKey && f.reason === 'occupied' ? 'rk-force' : 'rk-bad'));
      const sx = d.side === 'right' ? 160 : 0;
      const w = d.side === 'full' ? RACK_W : 160;
      ghost.style.left = (t.slot.r.left - rr.left + sx) + 'px';
      ghost.style.top = (t.slot.r.top - rr.top + uToY(rack, t.u, d.height) * (S.k || 1)) + 'px';
      ghost.style.width = w + 'px';
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
    list.classList.remove('rk-droptarget');
    if (!d.moved) {
      if (!d.fromList) select1(d.id);
      return;
    }
    const t = dragTarget(e, d);
    if (t && t.rack) {
      const o = Object.assign({}, d.opts, d.fromList ? {face: t.face} : {});
      S.sel = d.id;
      tryPlace(d.id, t.rack, t.u, o, !!e.altKey);
      refocus(d.id);
    } else if (t && t.unrack && !d.fromList) {
      commit(unplaceOps(doc(), d.id), 'Unracked ' + devName(d.id));
    }
  }

  function onDragCancel() {
    S.drag = null;
    ghost.hidden = true;
    list.classList.remove('rk-droptarget');
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
      const first = list.querySelector('.rk-addbtn');
      if (first) first.focus();
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      select1(id);
      if (ctx.openInspector) ctx.openInspector({type: 'device', id: id});
    } else if (e.key === 'Escape') {
      e.preventDefault();
      select1(null);
    }
  }

  // ------------------------------------------------------- rack editing
  function openForm(rack) {
    S.editing = rack ? rack.id : '';
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
    function field(id, label, input) { return h('div', {class: 'rk-field'}, [h('label', {for: id, text: label}), input]); }
    form.appendChild(h('h3', {text: rack ? 'Edit ' + rack.name : 'New rack'}));
    form.appendChild(field('rk-f-name', 'Name', name));
    form.appendChild(field('rk-f-units', 'Units (1\u201360)', units));
    form.appendChild(field('rk-f-numbering', 'Numbering', numbering));
    form.appendChild(field('rk-f-location', 'Location', loc));
    form.appendChild(field('rk-f-notes', 'Notes', notes));
    const row = h('div', {class: 'rk-formrow'}, [
      h('button', {type: 'submit', class: 'rk-btn rk-primary', text: rack ? 'Save' : 'Create rack'}),
      h('button', {type: 'button', class: 'rk-btn', 'data-act': 'cancel', text: 'Cancel'}),
      rack ? h('button', {type: 'button', class: 'rk-btn rk-danger', 'data-act': 'delete', text: 'Delete rack'}) : null,
    ]);
    form.appendChild(row);
    form.hidden = false;
    name.focus();
    name.select();
  }

  function closeForm(focusEl) {
    form.hidden = true;
    form.innerHTML = '';
    S.editing = null;
    (focusEl || btnAdd).focus();
  }

  function onFormSubmit(e) {
    e.preventDefault();
    const v = function (id) { const n = form.querySelector('#' + id); return n ? n.value : ''; };
    const units = Math.max(1, Math.min(60, parseInt(v('rk-f-units'), 10) || 12));
    const spec = {name: v('rk-f-name').trim() || 'Rack', units: units, numbering: v('rk-f-numbering'), location: v('rk-f-location'), notes: v('rk-f-notes').trim(),
      room: room() === '*' ? '' : room()};
    if (S.editing) {
      const rack = findRack(doc(), S.editing);
      const value = {name: spec.name, units: units, numbering: spec.numbering === 'top_down' ? 'top_down' : null,
        location: spec.location || null, notes: spec.notes || null};
      commit([{op: 'merge', coll: 'racks', id: rack.id, value: value}], 'Edited rack ' + spec.name);
      if (outOfRange(doc(), rack.id).length) ctx.toast('Some devices are now outside the rack.', 'warn');
      closeForm(btnEdit);
    } else {
      const res = newRackOps(doc(), spec);
      commit(res.ops, 'Created rack ' + spec.name);
      S.rack = res.id;
      closeForm(btnAdd);
      render();
    }
  }

  function onFormClick(e) {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    if (b.getAttribute('data-act') === 'cancel') closeForm();
    if (b.getAttribute('data-act') === 'delete') {
      const rack = findRack(doc(), S.editing);
      Promise.resolve(ctx.confirm('Delete rack "' + rack.name + '"? Its devices become unracked.', {danger: true})).then(function (ok) {
        if (!ok) return;
        commit(deleteRackOps(doc(), rack.id), 'Deleted rack ' + rack.name);
        S.rack = '*';
        closeForm(btnAdd);
        render();
      });
    }
  }

  function doPrint() {
    S.print = true;
    render();
    const done = function () { window.removeEventListener('afterprint', done); S.print = false; render(); };
    window.addEventListener('afterprint', done);
    if (typeof window.print === 'function') window.print();
  }

  // ------------------------------------------------------------- events
  on(select, 'change', function () { S.rack = select.value; render(); });
  on(btnAdd, 'click', function () { openForm(null); });
  on(btnEdit, 'click', function () { const r = findRack(doc(), S.rack); if (r) openForm(r); });
  on(btnFace, 'click', function () { S.face = S.face === 'front' ? 'rear' : 'front'; render(); btnFace.focus(); });
  on(btnPrint, 'click', doPrint);
  on(form, 'submit', onFormSubmit);
  on(form, 'click', onFormClick);
  on(form, 'keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); closeForm(); } });
  on(racksEl, 'pointerdown', function (e) {
    const b = e.target.closest('.rk-block');
    if (!b || (e.pointerType === 'mouse' && e.button > 0)) return;
    if (readOnly()) { select1(b.getAttribute('data-device')); return; }
    startDrag(e, b.getAttribute('data-device'), false, b);
  });
  on(racksEl, 'pointerup', function (e) {
    if (!S.drag && !e.target.closest('.rk-block') && S.sel) select1(null);
  });
  on(list, 'pointerdown', function (e) {
    const g = e.target.closest('.rk-grip');
    if (g && !readOnly()) startDrag(e, g.getAttribute('data-device'), true, g);
  });
  [racksEl, list].forEach(function (t) {
    on(t, 'pointermove', onDragMove);
    on(t, 'pointerup', onDragUp);
    on(t, 'pointercancel', onDragCancel);
  });
  on(list, 'click', function (e) {
    const b = e.target.closest('.rk-addbtn');
    if (b) addToRack(b.getAttribute('data-device'));
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
  on(store, 'room', function () { S.rack = '*'; render(); });
  on(store, 'mode', render);
  on(store, 'highlight', function (e) { S.highlight = e.detail; render(); });
  on(store, 'selection', function (e) {
    const sel = e.detail;
    const id = sel && sel.type === 'device' ? sel.id : null;
    if (id !== S.sel) { S.sel = id; render(); }
  });

  render();

  return {
    destroy: function () {
      listeners.forEach(function (l) { l[0].removeEventListener(l[1], l[2], l[3]); });
      el.innerHTML = '';
    },
    focus: function (sel) {
      const id = sel && (sel.device || sel.id);
      const dev = id && deviceById(doc(), id);
      if (sel && sel.type === 'rack') { S.rack = sel.id; render(); return; }
      if (!dev || !dev.rack || !dev.rack.id) return;
      S.rack = '*';
      S.sel = id;
      const p = placement(doc(), dev);
      if (p.face !== S.face && p.depth !== 'full') S.face = p.face;
      render();
      refocus(id);
    },
    getState: function () { return {rack: S.rack, face: S.face}; },
    setState: function (s) { if (s) { S.rack = s.rack || '*'; S.face = s.face === 'rear' ? 'rear' : 'front'; render(); } },
    _state: S,
  };
}
