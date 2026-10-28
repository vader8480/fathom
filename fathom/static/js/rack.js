// Racks view: mount(el, ctx) (§6.4, §6.7). `racks` with no id is the all-racks
// landing: the toolbar, the rack form and the unracked-devices explorer built
// here around the elevation from rack-elevation.js. `racks/<id>[/<tab>[/front|rear]]`
// is the rack page (page-rack.js, docs/ui-audit.md B.3 RK), which embeds one
// elevation through the createElevation passed to it.
import { h } from './dom.js';
import { findRack, rackUnits, outOfRange, newRackOps, deleteRackOps, rackDevices } from './rack-core.js';
import { createElevation, roomRacks, deviceById, disciplineOf, discColor, modelLine } from './rack-elevation.js';
import { mountExplorer } from './explorer.js';
import { confirmScope, emptyState } from './feedback.js';
import { mountRackPage } from './page-rack.js';

export { createElevation };

const EXTRA_CSS = ['explorer.css', 'rack.css'];

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
// Toolbar (#rk-select, #rk-add, #rk-edit, #rk-face, #rk-print), rack form
// (#rk-f-*) and the unracked explorer (#rk-unracked) around one elevation of
// every rack in the room. The elevation owns {rack, face}; onChange re-syncs
// the toolbar and the list after each of its renders.

function mountLanding(el, ctx) {
  const store = ctx.store;
  const vocab = ctx.vocab || store.vocab || {};
  const L = {editing: null, listSig: ''};
  const listeners = [];
  let elev = null;
  function on(target, type, fn, opts2) {
    target.addEventListener(type, fn, opts2);
    listeners.push([target, type, fn, opts2]);
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
  const form = h('form', {class: 'rk-form', hidden: true, 'aria-label': 'Rack'});
  const body = h('div', {class: 'rk-body'});
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
  el.appendChild(root);

  function doc() { return store.doc; }
  function readOnly() { return !!store.readOnly; }
  function room() { return store.room || ''; }
  function racks() { return roomRacks(doc(), room()); }
  function shownRack() { return elev ? elev.getState().rack : '*'; }
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

  function emptyNode() {
    const ro = readOnly();
    return h('div', {class: 'rk-empty'}, [emptyState({
      title: 'No racks in ' + roomName() + '.',
      text: ro ? '' : 'Add a rack, then drag devices from the unracked list onto it.',
      action: ro ? null : {label: 'Add rack', run: function () { openForm(null); }},
    })]);
  }

  // ---------------------------------------------------------- rendering
  function sync(state, api) {
    if (!elev) elev = api;
    renderToolbar(state);
    renderList();
  }

  function renderToolbar(state) {
    const rs = racks();
    const ro = readOnly();
    select.innerHTML = '';
    select.appendChild(h('option', {value: '*', text: rs.length ? 'All racks (' + rs.length + ')' : 'No racks in this room'}));
    rs.forEach(function (r) { select.appendChild(h('option', {value: r.id, text: r.name, selected: r.id === state.rack})); });
    btnAdd.disabled = ro;
    btnEdit.disabled = ro || state.rack === '*';
    btnFace.textContent = state.face === 'front' ? 'Showing front' : 'Showing rear';
    btnFace.setAttribute('aria-pressed', state.face === 'rear' ? 'true' : 'false');
    btnFace.setAttribute('aria-label', 'Showing ' + state.face + ' face. Switch to ' + (state.face === 'front' ? 'rear' : 'front'));
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

  // ------------------------------------------------------- rack editing
  function openForm(rack) {
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
    L.editing = null;
    (focusEl || btnAdd).focus();
  }

  function onFormSubmit(e) {
    e.preventDefault();
    const v = function (id) { const n = form.querySelector('#' + id); return n ? n.value : ''; };
    const units = Math.max(1, Math.min(60, parseInt(v('rk-f-units'), 10) || 12));
    const spec = {name: v('rk-f-name').trim() || 'Rack', units: units, numbering: v('rk-f-numbering'), location: v('rk-f-location'), notes: v('rk-f-notes').trim(),
      room: room() === '*' ? '' : room()};
    if (L.editing) {
      const rack = findRack(doc(), L.editing);
      const value = {name: spec.name, units: units, numbering: spec.numbering === 'top_down' ? 'top_down' : null,
        location: spec.location || null, notes: spec.notes || null};
      commit([{op: 'merge', coll: 'racks', id: rack.id, value: value}], 'Edited rack ' + spec.name);
      if (outOfRange(doc(), rack.id).length) ctx.toast('Some devices are now outside the rack.', 'warn');
      closeForm(btnEdit);
    } else {
      const res = newRackOps(doc(), spec);
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
  on(select, 'change', function () { elev.setState({rack: select.value}); });
  on(btnAdd, 'click', function () { openForm(null); });
  on(btnEdit, 'click', function () { const r = findRack(doc(), shownRack()); if (r) openForm(r); });
  on(btnFace, 'click', function () { elev.setFace(elev.getState().face === 'front' ? 'rear' : 'front'); btnFace.focus(); });
  on(btnPrint, 'click', function () { elev.print(); });
  on(form, 'submit', onFormSubmit);
  on(form, 'click', onFormClick);
  on(form, 'keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); closeForm(); } });
  on(list, 'pointerdown', function (e) {
    const g = e.target.closest('.rk-grip');
    if (g && !readOnly()) elev.startDrag(e, g.getAttribute('data-device'), true, g);
  });
  // The Add buttons sit inside explorer options: keep their clicks and keys from activating the option.
  on(list, 'click', function (e) {
    const b = e.target.closest('.rk-addbtn');
    if (!b) return;
    e.stopPropagation();
    if (!b.disabled) elev.addToRack(b.getAttribute('data-device'));
  }, true);
  on(list, 'keydown', function (e) {
    if (e.target.closest && e.target.closest('.rk-addbtn') && (e.key === 'Enter' || e.key === ' ')) e.stopPropagation();
  }, true);
  if (typeof MutationObserver === 'function') {
    const mo = new MutationObserver(function () { decorate(); });
    mo.observe(list, {childList: true});
    listeners.push([{removeEventListener: function () { mo.disconnect(); }}, '', null, null]);
  }

  elev = createElevation(ex.content, ctx, {
    root: root,
    racks: racks,
    empty: emptyNode,
    onChange: sync,
    list: {
      el: list,
      onLift: function () { ex.close({focus: false}); },
      focus: function () { const b = list.querySelector('.rk-addbtn'); if (b) b.focus(); },
    },
  });

  return {
    destroy: function () {
      elev.destroy();
      listeners.forEach(function (l) { l[0].removeEventListener(l[1], l[2], l[3]); });
      ex.destroy();
      el.innerHTML = '';
    },
    route: function (r) { elev.route(r); },
    focus: function (sel) { elev.focus(sel); },
    getState: function () { return elev.getState(); },
    setState: function (s) { if (s) elev.setState({rack: s.rack || '*', face: s.face}); },
    print: function (done) { elev.print(done); },
    elevation: elev,
    get _state() { return elev._state; },
  };
}
