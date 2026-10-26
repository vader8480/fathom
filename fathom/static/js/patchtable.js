// Editable patch table view (§6.6, FR-PT, Knox screenshot c). Two layouts
// (docs/ui-audit.md B.3 PT), toggled by #pt-mode and the URL `mode`:
// - Blocks: one printable block per device, inputs (Device · Source · ← · Input)
//   beside outputs (Output · → · Dest · Device), colored port-group headings;
// - Rows: one shared DataTable row per port (key `patch-rows`), rows open the
//   port drawer, editors bulk-remove patches.
// Both re-render live on store events.

import { h } from './dom.js';
import { createTable } from './datatable.js';
import { loadState, saveState } from './datatable-core.js';
import { confirmScope } from './feedback.js';
import { buildPatchTable, patchTableCsv, patchCellOps, blockPortCount, patchRows, pickMode, peerPortText, rowCables, PT_MODES } from './patchtable-core.js';
import { mediumInfo, connectOps, disconnectOps } from './model-core.js';

const ROWS_KEY = 'patch-rows';
const ROWS_PAGE_SIZE = 100;

function download(name, text, type) {
  const blob = new Blob([text], { type: type || 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 800);
}

function localStore() {
  try { return window.localStorage; } catch (e) { return null; }
}

function own(o, k) { return !!o && Object.prototype.hasOwnProperty.call(o, k); }

export function mount(el, ctx) {
  const store = ctx.store;
  const vocab = ctx.vocab || {};
  const scope = ctx.project || '';
  function readOnly() { return !!store.readOnly || ctx.role === 'viewer'; }
  function routeQuery() {
    const r = ctx.route;
    return (r && r.query) || {};
  }
  function layoutNow() {
    if (typeof ctx.layout === 'function') return ctx.layout();
    return window.innerWidth < 700 ? 'sm' : window.innerWidth < 1100 ? 'md' : 'lg';
  }
  function setParams(patch) {
    if (typeof ctx.setParams === 'function') ctx.setParams(patch);
  }

  const query0 = routeQuery();
  const state = {
    room: store.room === undefined ? '*' : store.room,
    followRoom: true,
    discs: (store.filter && store.filter.disciplines) ? store.filter.disciplines.slice() : [],
    text: typeof query0.q === 'string' ? query0.q : '',
    onlyPatched: false,
    overlay: false,
    split: false,
    mode: 'blocks',
    modeSource: 'default',
  };
  let splitHandle = null;
  let raf = 0;
  let selfEdit = false;
  let table = null;
  let hlId = null;
  let rowPick = false;
  const offs = [];

  if (ctx.viewCss) ctx.viewCss('table');

  // The explicit Blocks/Rows choice lives in the Rows table's persisted state (D8, extra.mode).
  function storedMode() {
    const s = loadState(localStore(), scope, ROWS_KEY, null, { pageSize: ROWS_PAGE_SIZE });
    return s.extra ? s.extra.mode : null;
  }
  function storeMode(mode) {
    const st = localStore();
    const s = loadState(st, scope, ROWS_KEY, null, { pageSize: ROWS_PAGE_SIZE });
    s.extra = Object.assign({}, s.extra || {}, { mode: mode });
    saveState(st, scope, ROWS_KEY, s);
  }

  const root = h('div', { class: 'pt-root' });
  const splitTop = h('div', { class: 'pt-split-top hidden', 'aria-label': 'Patch view' });
  const countEl = h('span', { class: 'muted', style: { fontSize: '12px' } });
  const modeBtns = {
    blocks: h('button', { type: 'button', 'data-mode': 'blocks', 'aria-pressed': 'false', title: 'One block per device (printable)' }, 'Blocks'),
    rows: h('button', { type: 'button', 'data-mode': 'rows', 'aria-pressed': 'false', title: 'One row per port: search, sort, filter' }, 'Rows'),
  };
  const modeWrap = h('div', { id: 'pt-mode', class: 'pt-mode no-print', role: 'group', 'aria-label': 'Layout' }, [modeBtns.blocks, modeBtns.rows]);
  const splitBtn = h('button', { type: 'button', id: 'pt-split', class: 'small no-print', 'aria-pressed': 'false', title: 'Patch view above, table below' }, 'Split view');
  const printBtn = h('button', { type: 'button', id: 'pt-print', class: 'small' }, 'Export PDF');
  const csvBtn = h('button', { type: 'button', id: 'pt-csv', class: 'small' }, 'CSV');
  const head = h('div', { class: 'pt-head' }, [
    h('span', { class: 'title' }, 'Patch table'), countEl,
    h('span', { class: 'pt-live', role: 'status' }, [h('span', { class: 'dot' }), 'Live', h('span', { class: 'pt-live-more' }, '\u2014 edits update every view')]),
    h('span', { class: 'grow' }),
    modeWrap, splitBtn, printBtn, csvBtn,
  ]);
  const roomSel = h('select', { id: 'pt-filter-room', 'aria-label': 'Room' });
  const discWrap = h('div', { id: 'pt-filter-disc', class: 'row', role: 'group', 'aria-label': 'Disciplines' });
  const text = h('input', { id: 'pt-filter-text', type: 'search', placeholder: 'Filter devices', 'aria-label': 'Filter devices' });
  text.value = state.text;
  const only = h('input', { id: 'pt-only-patched', type: 'checkbox' });
  const ovl = h('input', { id: 'pt-show-overlay', type: 'checkbox' });
  const onlyLabel = h('label', { class: 'row', for: 'pt-only-patched' }, [only, 'Only patched']);
  const filters = h('div', { class: 'pt-filters' }, [roomSel, discWrap, text,
    onlyLabel,
    h('label', { class: 'row', for: 'pt-show-overlay', title: 'Dante / Videohub routes from imports' }, [ovl, 'Show import rows']),
  ]);
  const scroll = h('div', { class: 'pt-scroll' });
  const rowsHost = h('div', { class: 'pt-rows' });
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
  function scopeName() {
    if (state.room === '*') return 'all rooms';
    if (!state.room) return 'Shared inventory';
    const r = (store.doc.rooms || []).filter(function (x) { return x.id === state.room; })[0];
    return r ? (r.name || r.id) : state.room;
  }
  function csvName() {
    return (ctx.project || 'fathom') + '-patch-table' + (state.room && state.room !== '*' ? '-' + state.room : '') + '.csv';
  }

  // ---------------------------------------------------------- shared cell controls

  function patchButton(device, deviceName, port, portName) {
    if (readOnly() || !port) return h('span', { class: 'pt-dash' }, 'Patch\u2026');
    return h('button', { type: 'button', class: 'pt-patch', 'data-port': port, 'data-device': device, 'aria-label': 'Patch ' + deviceName + ' ' + portName, onclick: function () {
      ctx.pickPort({ compatibleWith: { device: device, port: port }, room: state.room === '*' ? '*' : state.room }).then(function (t) {
        if (!t) return;
        const ops = patchCellOps(store.doc, { device: device, port: port }, 'peer', t);
        const peer = (store.doc.devices || []).filter(function (d) { return d.id === t.device; })[0];
        const pp = peer && t.port ? (peer.ports || []).filter(function (p) { return p.id === t.port; })[0] : null;
        ctx.commit(ops, 'Connected ' + deviceName + ' ' + portName + ' to ' + (peer ? peer.name : t.device) + (pp ? ' ' + (pp.name || pp.id) : ''));
      });
    } }, 'Patch\u2026');
  }

  function removeButton(cls, deviceName, portName, peerName, cable) {
    return h('button', { type: 'button', class: cls, 'aria-label': 'Remove patch ' + deviceName + ' ' + (portName || '') + ' to ' + (peerName || ''), title: 'Remove patch', onclick: function () {
      ctx.commit(disconnectOps(store.doc, cable), 'Removed patch ' + deviceName + ' ' + (portName || '') + ' \u2194 ' + (peerName || ''));
    } }, '\u00d7');
  }

  // ---------------------------------------------------------- Blocks mode

  function labelInput(block, row) {
    const input = h('input', { placeholder: row.port_name || '', 'aria-label': 'Label for ' + block.name + ' ' + (row.port_name || ''), 'data-key': block.device + ':' + row.port, readonly: readOnly() ? true : null });
    input.value = row.label || '';
    function commit() {
      if (readOnly()) return;
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

  function clearButton(block, row) {
    if (readOnly() || !row.cable || row.source !== 'cable') return null;
    return removeButton('pt-x', block.name, row.port_name, row.peer_name, row.cable);
  }

  function inputTable(block, sec) {
    const tb = h('tbody');
    sec.rows.forEach(function (r) {
      const patched = !!r.peer_device;
      tb.appendChild(h('tr', { 'data-port': r.port || '', 'data-cable': r.cable || '' }, [
        h('td', { class: 'x' }, clearButton(block, r)),
        h('td', null, patched ? (r.peer_name || r.peer_device) : patchButton(block.device, block.name, r.port, r.port_name)),
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
        h('td', null, patched ? (r.peer_name || r.peer_device) : patchButton(block.device, block.name, r.port, r.port_name)),
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

  function renderBlocks(blocks) {
    const active = document.activeElement;
    const key = active && root.contains(active) && active.getAttribute ? active.getAttribute('data-key') : null;
    const top = scroll.scrollTop;
    scroll.innerHTML = '';
    blocks.forEach(function (b) { scroll.appendChild(blockEl(b)); });
    if (!blocks.length) scroll.appendChild(h('div', { class: 'app-empty' }, 'No devices match these filters.'));
    scroll.scrollTop = top;
    if (key) {
      const again = scroll.querySelector('[data-key="' + key.replace(/"/g, '\\"') + '"]');
      if (again) again.focus();
    }
  }

  // ---------------------------------------------------------- Rows mode (DataTable)

  function dotText(color, label) {
    return h('span', { class: 'pt-dot-text' }, [h('span', { class: 'dot', style: { color: color } }), label]);
  }

  function rowColumns(editable) {
    const ds = vocab.disciplines || {};
    const cols = [
      { key: 'room', header: 'Room', value: function (r) { return r.room_name; }, hideOnMobile: true },
      { key: 'device', header: 'Device', sticky: true, value: function (r) { return r.device_name; } },
      { key: 'port', header: 'Port',
        value: function (r) { return r.port ? r.port_name + (r.label && r.label !== r.port_name ? ' \u00b7 ' + r.label : '') : ''; },
        cell: function (r) {
          if (!r.port) return h('span', { class: 'muted' }, 'device');
          return h('span', null, [r.port_name, r.label && r.label !== r.port_name ? h('span', { class: 'muted' }, ' \u00b7 ' + r.label) : null]);
        } },
      { key: 'dir', header: 'Dir', filterable: true, value: function (r) { return r.dir; } },
      { key: 'signal', header: 'Signal', hideOnMobile: true, value: function (r) { return r.signal; },
        cell: function (r) { return r.signal ? dotText((ds[r.signal_key] || {}).color || '#9aa3b5', r.signal) : ''; } },
      { key: 'peer_device', header: 'Connected device', value: function (r) { return r.peer_name; },
        cell: function (r) {
          if (r.peer_device) return r.peer_name;
          if (!r.source && r.port) return patchButton(r.device, r.device_name, r.port, r.port_name);
          return h('span', { class: 'pt-dash' }, '\u2014');
        } },
      { key: 'peer_port', header: 'Connected port', value: function (r) { return r.peer_port_text; },
        cell: function (r) { return r.source && r.source !== 'cable' ? h('span', { class: 'ovl' }, r.peer_port_text) : r.peer_port_text; } },
      { key: 'tag', header: 'Cable tag', value: function (r) { return r.tag || (r.source && r.source !== 'cable' ? 'from import' : ''); },
        cell: function (r) { return r.source && r.source !== 'cable' ? h('span', { class: 'ovl' }, 'from import') : r.tag; } },
      { key: 'medium', header: 'Medium', filterable: true, hideOnMobile: true, value: function (r) { return r.medium_label; },
        cell: function (r) { return r.medium ? dotText(mediumInfo(r.medium, vocab).color, r.medium_label) : ''; } },
    ];
    if (editable) {
      cols.push({ key: 'remove', header: 'Remove', sortable: false, searchable: false, csv: false, align: 'center', value: function () { return ''; },
        cell: function (r) { return r.source === 'cable' && r.cable ? removeButton('pt-x pt-remove', r.device_name, r.port_name, r.peer_name, r.cable) : null; } });
    }
    return cols;
  }

  function openRow(row) {
    const sel = row.port ? { type: 'port', id: row.device, device: row.device, port: row.port } : { type: 'device', id: row.device, device: row.device };
    rowPick = true;
    try { (ctx.openDrawer || ctx.openInspector)(sel); } finally { rowPick = false; }
  }

  function bulkRemove(rows) {
    const ids = rowCables(rows);
    if (!ids.length) return Promise.resolve();
    const where = scopeName();
    return confirmScope(ctx, { verb: 'Remove', count: ids.length, noun: { one: 'patch', many: 'patches' }, scope: where, danger: true }).then(function (ok) {
      if (!ok) return;
      let ops = [];
      ids.forEach(function (id) { ops = ops.concat(disconnectOps(store.doc, id)); });
      ctx.commit(ops, 'Removed ' + ids.length + (ids.length === 1 ? ' patch' : ' patches') + ' in ' + where);
      if (table) table.clearSelection();
    });
  }

  function onTableState(e) {
    const s = e.detail || {};
    if (typeof s.q === 'string') state.text = s.q;
  }

  function createRowsTable() {
    const editable = !readOnly();
    scroll.innerHTML = '';
    rowsHost.innerHTML = '';
    scroll.appendChild(rowsHost);
    hlId = null;
    table = createTable(rowsHost, {
      key: ROWS_KEY,
      scope: scope,
      caption: 'Patch rows',
      columns: rowColumns(editable),
      rows: [],
      rowId: function (r) { return r.id; },
      onRow: openRow,
      rowAttrs: function (r) { return { 'data-device': r.device, 'data-port': r.port || '', 'data-cable': r.cable || '' }; },
      rowClass: function (r) { return r.source && r.source !== 'cable' ? 'pt-ovl-row' : ''; },
      selectable: editable ? function (r) { return r.source === 'cable' && !!r.cable; } : false,
      bulkActions: editable ? [{ label: 'Remove patch', danger: true, run: bulkRemove }] : [],
      noun: { one: 'row', many: 'rows' },
      ids: { search: 'pt-filter-text', csv: 'pt-csv' },
      url: { get: routeQuery, set: setParams },
      pageSize: ROWS_PAGE_SIZE,
      csvName: csvName(),
      searchPlaceholder: 'Search ports, devices, cable tags',
      empty: 'No ports match these filters.',
    });
    rowsHost.addEventListener('dt:state', onTableState);
  }

  function destroyRowsTable() {
    if (!table) return;
    rowsHost.removeEventListener('dt:state', onTableState);
    table.destroy();
    table = null;
    hlId = null;
  }

  function renderRows(blocks) {
    if (!table) createRowsTable();
    table.setRows(patchRows(blocks, store.doc, vocab));
  }

  // ---------------------------------------------------------- render + mode

  function currentBlocks(forRows) {
    return buildPatchTable(store.doc, store.overlay, vocab, { room: state.room, disciplines: state.discs, query: forRows ? '' : state.text, onlyPatched: state.onlyPatched, includeOverlay: state.overlay });
  }

  function render() {
    raf = 0;
    const rowsMode = state.mode === 'rows';
    const blocks = currentBlocks(rowsMode);
    let rows = 0;
    blocks.forEach(function (b) { rows += blockPortCount(b); });
    countEl.textContent = blocks.length + ' devices \u00b7 ' + rows + ' rows';
    if (rowsMode) renderRows(blocks);
    else renderBlocks(blocks);
  }
  function schedule() {
    if (!raf) raf = requestAnimationFrame(render);
  }

  // One #pt-filter-text and one #pt-csv at a time: the DataTable's in Rows mode.
  function syncModeUi() {
    const rowsMode = state.mode === 'rows';
    PT_MODES.forEach(function (m) { modeBtns[m].setAttribute('aria-pressed', m === state.mode ? 'true' : 'false'); });
    root.setAttribute('data-mode', state.mode);
    scroll.classList.toggle('pt-scroll--rows', rowsMode);
    if (rowsMode) {
      if (text.parentNode) text.parentNode.removeChild(text);
      if (csvBtn.parentNode) csvBtn.parentNode.removeChild(csvBtn);
    } else {
      if (!text.parentNode) filters.insertBefore(text, onlyLabel);
      if (document.activeElement !== text) text.value = state.text;
      if (!csvBtn.parentNode) head.insertBefore(csvBtn, printBtn.nextSibling);
    }
  }

  function modeParams(mode) {
    const p = { mode: mode };
    if (mode === 'blocks') {
      p.q = state.text || null;
      p.sort = null;
      p.pg = null;
      Object.keys(routeQuery()).forEach(function (k) { if (k.indexOf('f.') === 0) p[k] = null; });
    }
    return p;
  }

  // opts: {explicit} persists the choice and writes the URL `mode`.
  function setMode(mode, opts) {
    const o = opts || {};
    if (PT_MODES.indexOf(mode) < 0) return;
    if (state.mode === 'rows' && table) state.text = table.getState().q;
    if (o.explicit) {
      storeMode(mode);
      state.modeSource = 'stored';
      setParams(modeParams(mode));
    } else if (o.source) {
      state.modeSource = o.source;
    }
    if (mode === state.mode && (mode === 'blocks' || table)) { syncModeUi(); return; }
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    destroyRowsTable();
    state.mode = mode;
    syncModeUi();
    if (mode === 'rows') {
      createRowsTable();
      if (table.getState().q !== state.text) table.setState({ q: state.text });
    }
    render();
    if (store.selection) onSel({ detail: store.selection });
  }

  // ---------------------------------------------------------- events

  csvBtn.addEventListener('click', function () {
    download(csvName(), patchTableCsv(currentBlocks(false)), 'text/csv');
  });
  printBtn.addEventListener('click', function () { window.print(); });
  splitBtn.addEventListener('click', function () { setSplit(!state.split); });
  modeWrap.addEventListener('click', function (e) {
    const b = e.target.closest('[data-mode]');
    if (b) setMode(b.getAttribute('data-mode'), { explicit: true });
  });
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
  text.addEventListener('input', function () {
    if (tTimer) clearTimeout(tTimer);
    tTimer = setTimeout(function () {
      tTimer = null;
      state.text = text.value;
      setParams({ q: state.text || null });
      schedule();
    }, 120);
  });
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
  function onMode() {
    if (table) { destroyRowsTable(); createRowsTable(); }
    schedule();
  }
  function onOverlay() { if (state.overlay) schedule(); }
  function onSel(e) {
    const sel = e.detail;
    if (!sel) return;
    const dev = sel.device || (sel.type === 'device' ? sel.id : null);
    if (!dev) return;
    if (table) {
      if (rowPick) return;
      const prefix = dev + '|' + (sel.type === 'port' && sel.port ? sel.port + '|' : '');
      const rows = patchRows(currentBlocks(true), store.doc, vocab);
      const hit = rows.filter(function (r) { return r.id.indexOf(prefix) === 0; })[0];
      const id = hit ? hit.id : null;
      if (id && id !== hlId) { hlId = id; table.setHighlight(id); }
      return;
    }
    const b = scroll.querySelector('section.pt-block[data-device="' + dev.replace(/"/g, '\\"') + '"]');
    if (b && !b.contains(document.activeElement)) b.scrollIntoView({ block: 'nearest' });
  }
  function onLayout() {
    if (state.modeSource !== 'default') return;
    const m = pickMode({}, null, layoutNow()).mode;
    if (m !== state.mode) setMode(m, {});
  }
  store.addEventListener('doc', onDoc);
  store.addEventListener('room', onRoom);
  store.addEventListener('mode', onMode);
  store.addEventListener('overlay', onOverlay);
  store.addEventListener('selection', onSel);
  if (typeof ctx.subscribe === 'function') offs.push(ctx.subscribe('layout', onLayout));

  fillRooms();
  fillDiscs();
  const first = pickMode(query0, storedMode(), layoutNow());
  state.mode = first.mode;
  state.modeSource = first.source;
  syncModeUi();
  if (state.mode === 'rows') {
    createRowsTable();
    if (table.getState().q !== state.text) table.setState({ q: state.text });
  }
  render();

  return {
    destroy: function () {
      if (raf) cancelAnimationFrame(raf);
      if (tTimer) clearTimeout(tTimer);
      store.removeEventListener('doc', onDoc);
      store.removeEventListener('room', onRoom);
      store.removeEventListener('mode', onMode);
      store.removeEventListener('overlay', onOverlay);
      store.removeEventListener('selection', onSel);
      offs.forEach(function (f) { try { f(); } catch (e) { /* ignore */ } });
      destroyRowsTable();
      if (splitHandle) { try { splitHandle.destroy(); } catch (e) { /* ignore */ } }
      el.innerHTML = '';
    },
    focus: function (sel) { onSel({ detail: sel }); },
    // Same-view URL change (D1): back/forward or an edited hash with another mode or q.
    route: function (r) {
      const q = (r && r.query) || {};
      const want = pickMode(q, storedMode(), layoutNow());
      if (want.mode !== state.mode) setMode(want.mode, { source: want.source });
      if (table) table.readUrl();
      else {
        const t = typeof q.q === 'string' ? q.q : '';
        if (t !== state.text) {
          state.text = t;
          if (document.activeElement !== text) text.value = t;
          schedule();
        }
      }
      if (store.selection) onSel({ detail: store.selection });
    },
    getState: function () {
      return { room: state.room, followRoom: state.followRoom, discs: state.discs.slice(), text: state.text, onlyPatched: state.onlyPatched, overlay: state.overlay, mode: state.mode, modeSource: state.modeSource, scroll: scroll.scrollTop };
    },
    // Restores the session state of an earlier visit; the URL's `mode` and `q` win over it.
    setState: function (s) {
      if (!s) return;
      const q = routeQuery();
      Object.assign(state, { room: s.followRoom ? store.room : s.room, followRoom: s.followRoom, discs: s.discs || [], onlyPatched: !!s.onlyPatched, overlay: !!s.overlay });
      only.checked = state.onlyPatched; ovl.checked = state.overlay; roomSel.value = state.room;
      fillDiscs();
      if (!own(q, 'mode') && PT_MODES.indexOf(s.mode) >= 0 && s.modeSource && s.modeSource !== 'default' && s.mode !== state.mode) {
        setMode(s.mode, { source: s.modeSource });
      }
      if (!own(q, 'q') && s.text) {
        state.text = s.text;
        if (table) table.setState({ q: s.text });
        else { text.value = s.text; setParams({ q: s.text }); }
      }
      render();
      scroll.scrollTop = s.scroll || 0;
    },
  };
}

export { connectOps };
