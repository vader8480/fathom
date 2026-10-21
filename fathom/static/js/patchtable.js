// Editable patch table view (§6.6, FR-PT, Knox screenshot c): one block per
// device, inputs (Device · Source · ← · Input) beside outputs (Output · → ·
// Dest · Device), colored port-group headings, live on store events.

import { buildPatchTable, patchTableCsv, patchCellOps, blockPortCount } from './patchtable-core.js';
import { mediumInfo, connectOps, disconnectOps } from './model-core.js';

function h(tag, attrs, children) {
  const el = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (v === undefined || v === null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k.indexOf('on') === 0 && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'value') el.value = v;
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, String(v));
    });
  }
  (Array.isArray(children) ? children : (children == null ? [] : [children])).forEach(function (c) {
    if (c === null || c === undefined || c === false) return;
    el.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
  });
  return el;
}

function download(name, text, type) {
  const blob = new Blob([text], { type: type || 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 800);
}

export function mount(el, ctx) {
  const store = ctx.store;
  const vocab = ctx.vocab || {};
  const state = {
    room: store.room === undefined ? '*' : store.room,
    followRoom: true,
    discs: (store.filter && store.filter.disciplines) ? store.filter.disciplines.slice() : [],
    text: '',
    onlyPatched: false,
    overlay: false,
    split: false,
  };
  let splitHandle = null;
  let raf = 0;
  let selfEdit = false;

  const root = h('div', { class: 'pt-root' });
  const splitTop = h('div', { class: 'pt-split-top hidden', 'aria-label': 'Patch view' });
  const countEl = h('span', { class: 'muted', style: { fontSize: '12px' } });
  const head = h('div', { class: 'pt-head' }, [
    h('span', { class: 'title' }, 'Patch table'), countEl,
    h('span', { class: 'pt-live', role: 'status' }, [h('span', { class: 'dot' }), 'Live \u2014 edits update every view']),
    h('span', { class: 'grow' }),
    h('button', { type: 'button', id: 'pt-split', class: 'small no-print', 'aria-pressed': 'false', title: 'Patch view above, table below' }, 'Split view'),
    h('button', { type: 'button', id: 'pt-print', class: 'small' }, 'Export PDF'),
    h('button', { type: 'button', id: 'pt-csv', class: 'small' }, 'CSV'),
  ]);
  const roomSel = h('select', { id: 'pt-filter-room', 'aria-label': 'Room' });
  const discWrap = h('div', { id: 'pt-filter-disc', class: 'row', role: 'group', 'aria-label': 'Disciplines' });
  const text = h('input', { id: 'pt-filter-text', type: 'search', placeholder: 'Filter devices', 'aria-label': 'Filter devices' });
  const only = h('input', { id: 'pt-only-patched', type: 'checkbox' });
  const ovl = h('input', { id: 'pt-show-overlay', type: 'checkbox' });
  const filters = h('div', { class: 'pt-filters' }, [roomSel, discWrap, text,
    h('label', { class: 'row', for: 'pt-only-patched' }, [only, 'Only patched']),
    h('label', { class: 'row', for: 'pt-show-overlay', title: 'Dante / Videohub routes from imports' }, [ovl, 'Show import rows']),
  ]);
  const scroll = h('div', { class: 'pt-scroll' });
  root.appendChild(splitTop);
  root.appendChild(head);
  root.appendChild(filters);
  root.appendChild(scroll);
  el.appendChild(root);

  function fillRooms() {
    roomSel.innerHTML = '';
    roomSel.appendChild(h('option', { value: '*' }, 'All rooms'));
    (store.doc.rooms || []).forEach(function (r) { roomSel.appendChild(h('option', { value: r.id }, r.name || r.id)); });
    roomSel.appendChild(h('option', { value: '' }, 'Shared inventory'));
    roomSel.value = state.room;
  }
  function fillDiscs() {
    discWrap.innerHTML = '';
    const ds = vocab.disciplines || {};
    Object.keys(ds).forEach(function (k) {
      const on = state.discs.indexOf(k) >= 0;
      discWrap.appendChild(h('button', { type: 'button', class: 'chip' + (on ? ' on' : ''), 'data-disc': k, 'aria-pressed': on ? 'true' : 'false', style: { color: ds[k].color } }, [h('i'), ds[k].label]));
    });
  }

  function labelInput(block, row) {
    const input = h('input', { value: row.label || '', placeholder: row.port_name || '', 'aria-label': 'Label for ' + block.name + ' ' + (row.port_name || ''), 'data-key': block.device + ':' + row.port, readonly: store.readOnly ? true : null });
    function commit() {
      if (store.readOnly) return;
      const v = input.value.trim();
      if (v === (row.label || '')) return;
      const ops = patchCellOps(store.doc, { device: block.device, port: row.port }, 'label', v);
      selfEdit = true;
      try { ctx.commit(ops, (v ? 'Label ' : 'Clear label ') + block.name + ' ' + row.port_name + (v ? ' "' + v + '"' : '')); } finally { selfEdit = false; }
    }
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
      else if (e.key === 'Escape') { e.preventDefault(); input.value = row.label || ''; input.blur(); }
    });
    input.addEventListener('change', commit);
    return input;
  }

  function portCell(block, row) {
    const m = mediumInfo(row.medium, vocab);
    const dot = h('span', { class: 'dot', style: { color: m.color }, title: m.label });
    if (!row.port) return h('div', { class: 'lbl' }, [dot, h('span', { class: 'muted' }, 'device')]);
    if (row.source && row.source !== 'cable') return h('div', { class: 'lbl' }, [dot, h('span', { class: 'ovl' }, row.label || row.port_name)]);
    return h('div', { class: 'lbl' }, [dot, labelInput(block, row)]);
  }

  function patchButton(block, row) {
    if (store.readOnly || !row.port) return h('span', { class: 'pt-dash' }, 'Patch\u2026');
    return h('button', { type: 'button', class: 'pt-patch', 'data-port': row.port, 'data-device': block.device, 'aria-label': 'Patch ' + block.name + ' ' + row.port_name, onclick: function () {
      ctx.pickPort({ compatibleWith: { device: block.device, port: row.port }, room: state.room === '*' ? '*' : state.room }).then(function (t) {
        if (!t) return;
        const ops = patchCellOps(store.doc, { device: block.device, port: row.port }, 'peer', t);
        const peer = (store.doc.devices || []).filter(function (d) { return d.id === t.device; })[0];
        const pp = peer && t.port ? (peer.ports || []).filter(function (p) { return p.id === t.port; })[0] : null;
        ctx.commit(ops, 'Connected ' + block.name + ' ' + row.port_name + ' to ' + (peer ? peer.name : t.device) + (pp ? ' ' + (pp.name || pp.id) : ''));
      });
    } }, 'Patch\u2026');
  }

  function clearButton(block, row) {
    if (store.readOnly || !row.cable || row.source !== 'cable') return null;
    return h('button', { type: 'button', class: 'pt-x', 'aria-label': 'Remove patch ' + block.name + ' ' + (row.port_name || '') + ' to ' + (row.peer_name || ''), title: 'Remove patch', onclick: function () {
      ctx.commit(disconnectOps(store.doc, row.cable), 'Removed patch ' + block.name + ' ' + (row.port_name || '') + ' \u2194 ' + (row.peer_name || ''));
    } }, '\u00d7');
  }

  function peerPortText(row) {
    if (!row.peer_device) return null;
    return row.peer_label || row.peer_port_name || (row.peer_port ? row.peer_port : 'device');
  }

  function inputTable(block, sec) {
    const tb = h('tbody');
    sec.rows.forEach(function (r) {
      const patched = !!r.peer_device;
      tb.appendChild(h('tr', { 'data-port': r.port || '', 'data-cable': r.cable || '' }, [
        h('td', { class: 'x' }, clearButton(block, r)),
        h('td', null, patched ? (r.peer_name || r.peer_device) : patchButton(block, r)),
        h('td', { class: r.source && r.source !== 'cable' ? 'ovl' : '' }, patched ? peerPortText(r) : h('span', { class: 'pt-dash' }, '\u2014')),
        h('td', { class: 'arrow', 'aria-hidden': 'true' }, '\u2190'),
        h('td', { class: 'pn' }, r.port_name || ''),
        h('td', null, portCell(block, r)),
      ]));
    });
    return h('table', { class: 'pt-table' }, [
      h('thead', null, h('tr', null, [h('th', { scope: 'col', class: 'x' }, h('span', { class: 'sr-only' }, 'Remove')), h('th', { scope: 'col' }, 'Device'), h('th', { scope: 'col' }, 'Source'), h('th', { scope: 'col', class: 'arrow' }, ''), h('th', { scope: 'col', class: 'pn' }, h('span', { class: 'sr-only' }, 'Port')), h('th', { scope: 'col' }, sec.title)])),
      tb,
    ]);
  }

  function outputTable(block, sec) {
    const tb = h('tbody');
    sec.rows.forEach(function (r) {
      const patched = !!r.peer_device;
      tb.appendChild(h('tr', { 'data-port': r.port || '', 'data-cable': r.cable || '' }, [
        h('td', { class: 'pn' }, r.port_name || ''),
        h('td', null, portCell(block, r)),
        h('td', { class: 'arrow', 'aria-hidden': 'true' }, '\u2192'),
        h('td', { class: r.source && r.source !== 'cable' ? 'ovl' : '' }, patched ? peerPortText(r) : h('span', { class: 'pt-dash' }, '\u2014')),
        h('td', null, patched ? (r.peer_name || r.peer_device) : patchButton(block, r)),
        h('td', { class: 'x' }, clearButton(block, r)),
      ]));
    });
    return h('table', { class: 'pt-table' }, [
      h('thead', null, h('tr', null, [h('th', { scope: 'col', class: 'pn' }, h('span', { class: 'sr-only' }, 'Port')), h('th', { scope: 'col' }, sec.title), h('th', { scope: 'col', class: 'arrow' }, ''), h('th', { scope: 'col' }, 'Dest'), h('th', { scope: 'col' }, 'Device'), h('th', { scope: 'col', class: 'x' }, h('span', { class: 'sr-only' }, 'Remove'))])),
      tb,
    ]);
  }

  function blockEl(block) {
    const ds = vocab.disciplines || {};
    const d = ds[block.discipline] || { color: '#9aa3b5', label: block.discipline };
    const dev = (store.doc.devices || []).filter(function (x) { return x.id === block.device; })[0] || {};
    const sec = h('section', { class: 'pt-block' + (dev.status === 'planned' ? ' pt-planned' : ''), 'data-device': block.device, 'aria-label': block.name });
    sec.appendChild(h('div', { class: 'pt-block-head' }, [
      h('span', { class: 'dot', style: { color: d.color }, title: d.label }),
      h('button', { type: 'button', class: 'ghost small', style: { fontWeight: '600', border: '0', padding: '0 4px' }, onclick: function () { ctx.openInspector({ type: 'device', id: block.device, device: block.device }); } }, block.name),
      h('span', { class: 'model' }, block.model || ''),
      dev.status === 'planned' ? h('span', { class: 'badge-planned' }, 'planned') : null,
    ]));
    const left = h('div', { class: 'pt-side' });
    const right = h('div', { class: 'pt-side' });
    block.sections.forEach(function (s) {
      const m = mediumInfo(s.medium, vocab);
      const heading = h('div', { class: 'pt-section-h' }, [h('span', { class: 'dot', style: { color: m.color } }), s.title, h('span', { class: 'muted' }, ' \u00b7 ' + (m.label || s.medium || ''))]);
      const box = h('div', null, [heading, s.dir === 'in' ? inputTable(block, s) : outputTable(block, s)]);
      (s.dir === 'in' ? left : right).appendChild(box);
    });
    if (!block.sections.length) left.appendChild(h('div', { class: 'pt-section-h' }, 'No ports'));
    sec.appendChild(h('div', { class: 'pt-cols' }, [left, right]));
    return sec;
  }

  function currentBlocks() {
    return buildPatchTable(store.doc, store.overlay, vocab, { room: state.room, disciplines: state.discs, query: state.text, onlyPatched: state.onlyPatched, includeOverlay: state.overlay });
  }

  function render() {
    raf = 0;
    const active = document.activeElement;
    const key = active && root.contains(active) && active.getAttribute ? active.getAttribute('data-key') : null;
    const top = scroll.scrollTop;
    const blocks = currentBlocks();
    scroll.innerHTML = '';
    let rows = 0;
    blocks.forEach(function (b) { rows += blockPortCount(b); scroll.appendChild(blockEl(b)); });
    if (!blocks.length) scroll.appendChild(h('div', { class: 'app-empty' }, 'No devices match these filters.'));
    countEl.textContent = blocks.length + ' devices \u00b7 ' + rows + ' rows';
    scroll.scrollTop = top;
    if (key) {
      const again = scroll.querySelector('[data-key="' + key.replace(/"/g, '\\"') + '"]');
      if (again) again.focus();
    }
  }
  function schedule() {
    if (!raf) raf = requestAnimationFrame(render);
  }

  // events
  head.querySelector('#pt-csv').addEventListener('click', function () {
    const name = (ctx.project || 'fathom') + '-patch-table' + (state.room && state.room !== '*' ? '-' + state.room : '') + '.csv';
    download(name, patchTableCsv(currentBlocks()), 'text/csv');
  });
  head.querySelector('#pt-print').addEventListener('click', function () { window.print(); });
  const splitBtn = head.querySelector('#pt-split');
  splitBtn.addEventListener('click', function () { setSplit(!state.split); });
  roomSel.addEventListener('change', function () { state.room = roomSel.value; state.followRoom = false; schedule(); });
  discWrap.addEventListener('click', function (e) {
    const b = e.target.closest('[data-disc]');
    if (!b) return;
    const k = b.getAttribute('data-disc');
    const i = state.discs.indexOf(k);
    if (i >= 0) state.discs.splice(i, 1); else state.discs.push(k);
    fillDiscs();
    schedule();
  });
  let tTimer = null;
  text.addEventListener('input', function () { if (tTimer) clearTimeout(tTimer); tTimer = setTimeout(function () { state.text = text.value; schedule(); }, 120); });
  only.addEventListener('change', function () { state.onlyPatched = only.checked; schedule(); });
  ovl.addEventListener('change', function () { state.overlay = ovl.checked; schedule(); });

  function setSplit(on) {
    state.split = !!on && window.innerWidth >= 1100;
    splitBtn.setAttribute('aria-pressed', state.split ? 'true' : 'false');
    splitTop.classList.toggle('hidden', !state.split);
    if (state.split && !splitHandle) {
      splitHandle = { destroy: function () {} };
      const css = ctx.viewCss ? ctx.viewCss('patch') : (ctx.ensureCss ? ctx.ensureCss('patchview.css') : null);
      Promise.all([import('./patchview.js'), css]).then(function (res) {
        const m = res[0];
        if (!state.split) return;
        splitTop.innerHTML = '';
        splitHandle = m.mount(splitTop, ctx) || { destroy: function () {} };
      }).catch(function (e) {
        splitTop.innerHTML = '';
        splitTop.appendChild(h('div', { class: 'app-error-card' }, [h('h3', null, 'Patch view is not available'), h('pre', null, (e && e.message) || String(e))]));
      });
    } else if (!state.split && splitHandle) {
      try { splitHandle.destroy(); } catch (e) { /* ignore */ }
      splitHandle = null;
      splitTop.innerHTML = '';
    }
  }

  function onDoc(e) {
    const d = e.detail || {};
    if (d.touched && d.touched.some(function (r) { return r.indexOf('rooms/') === 0; })) fillRooms();
    if (selfEdit) { schedule(); return; }
    schedule();
  }
  function onRoom() {
    if (state.followRoom) { state.room = store.room; roomSel.value = state.room; schedule(); }
  }
  function onMode() { schedule(); }
  function onOverlay() { if (state.overlay) schedule(); }
  function onSel(e) {
    const sel = e.detail;
    if (!sel) return;
    const dev = sel.device || (sel.type === 'device' ? sel.id : null);
    if (!dev) return;
    const b = scroll.querySelector('section.pt-block[data-device="' + dev.replace(/"/g, '\\"') + '"]');
    if (b && !b.contains(document.activeElement)) b.scrollIntoView({ block: 'nearest' });
  }
  store.addEventListener('doc', onDoc);
  store.addEventListener('room', onRoom);
  store.addEventListener('mode', onMode);
  store.addEventListener('overlay', onOverlay);
  store.addEventListener('selection', onSel);

  fillRooms();
  fillDiscs();
  render();

  return {
    destroy: function () {
      if (raf) cancelAnimationFrame(raf);
      store.removeEventListener('doc', onDoc);
      store.removeEventListener('room', onRoom);
      store.removeEventListener('mode', onMode);
      store.removeEventListener('overlay', onOverlay);
      store.removeEventListener('selection', onSel);
      if (splitHandle) { try { splitHandle.destroy(); } catch (e) { /* ignore */ } }
      el.innerHTML = '';
    },
    focus: function (sel) { onSel({ detail: sel }); },
    getState: function () { return { room: state.room, followRoom: state.followRoom, discs: state.discs.slice(), text: state.text, onlyPatched: state.onlyPatched, overlay: state.overlay, scroll: scroll.scrollTop }; },
    setState: function (s) {
      if (!s) return;
      Object.assign(state, { room: s.followRoom ? store.room : s.room, followRoom: s.followRoom, discs: s.discs || [], text: s.text || '', onlyPatched: !!s.onlyPatched, overlay: !!s.overlay });
      text.value = state.text; only.checked = state.onlyPatched; ovl.checked = state.overlay; roomSel.value = state.room;
      fillDiscs();
      render();
      scroll.scrollTop = s.scroll || 0;
    },
  };
}

export { connectOps };
