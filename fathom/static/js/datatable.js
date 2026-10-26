// Shared DataTable (docs/ui-audit.md B.2 TABLE, D1, D3, D8, D9). Every read list
// of records in the app renders through createTable; drill-down counts open
// openTableDialog. State logic is in datatable-core.js; this module owns the DOM.
import { h, on } from './dom.js';
import { layoutFor } from './router-core.js';
import {
  normalizeColumns, applyState, createIndex, distinctValues, toCsv, textOf, mergeState,
  paramsToState, urlPatch, loadState, saveState, defaultState, PAGE_SIZES, EMPTY,
} from './datatable-core.js';

export { PAGE_SIZES, EMPTY };

const SKELETON_ROWS = 8;
const POP_SEARCH_AT = 12;
const POP_MAX_VALUES = 200;
const DEBOUNCE_ROWS = 3000;
const PERSIST_FIELDS = ['sort', 'filters', 'pageSize', 'hidden', 'density', 'extra'];
const IGNORE_ROW_CLICK = 'input,button,a,select,textarea,label,summary,[contenteditable],[data-dt-ignore]';

let uidSeq = 0;
function uid(p) { uidSeq += 1; return 'dt-' + p + '-' + uidSeq; }

function defaultStorage() {
  try { return window.localStorage; } catch (e) { return null; }
}

function own(o, k) { return !!o && Object.prototype.hasOwnProperty.call(o, k); }

function isNode(x) { return !!x && typeof x === 'object' && typeof x.nodeType === 'number'; }

function plural(n, noun) {
  const nn = noun || { one: 'row', many: 'rows' };
  return n + ' ' + (n === 1 ? nn.one : nn.many);
}

function fmt(n) {
  return Number(n).toLocaleString('en-US');
}

function cellContent(v) {
  if (v === null || v === undefined || v === false) return null;
  if (isNode(v)) return v;
  return document.createTextNode(String(v));
}

function slug(s) {
  return String(s || 'export').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'export';
}

export function createTable(host, opts) {
  const o = opts || {};
  const key = String(o.key || 'table');
  const scope = o.scope ? String(o.scope) : '';
  const ids = o.ids || {};
  const filterIds = ids.filters || {};
  const caption = o.caption || '';
  const columns = normalizeColumns(o.columns);
  const colByKey = {};
  columns.forEach(function (c) { colByKey[c.key] = c; });
  const storage = o.storage === undefined || o.storage === null ? defaultStorage() : o.storage;
  const persist = o.persist === false ? [] : (Array.isArray(o.persist) ? o.persist : PERSIST_FIELDS);
  const rowIdFn = typeof o.rowId === 'function' ? o.rowId : function (r) { return r && r.id; };
  const canSelectFn = typeof o.selectable === 'function' ? o.selectable : null;
  const selectable = !!o.selectable;
  const bulkActions = Array.isArray(o.bulkActions) ? o.bulkActions : [];
  const noun = o.noun || (bulkActions.filter(function (b) { return b && b.noun; })[0] || {}).noun || null;
  const pageSizes = Array.isArray(o.pageSizes) && o.pageSizes.length ? o.pageSizes.filter(function (n) { return PAGE_SIZES.indexOf(n) >= 0; }) : PAGE_SIZES;
  const url = o.url && typeof o.url.get === 'function' && typeof o.url.set === 'function' ? o.url : null;
  const defaults = { pageSize: o.pageSize || 50, density: o.density || 'normal' };

  let rows = Array.isArray(o.rows) ? o.rows : [];
  let index = createIndex(rows, columns);
  let view = null;
  let pageById = {};
  let loading = false;
  let error = null;
  let highlight = o.highlight == null ? null : String(o.highlight);
  let scrollToHl = highlight !== null;
  let headSig = '';
  let csvUrl = '';
  let csvStale = true;
  let csvTimer = 0;
  let searchTimer = 0;
  let lastChecked = null;
  let shiftClick = false;
  let pop = null;
  let layout = layoutFor(window.innerWidth);
  let destroyed = false;
  const selected = new Set();
  const offs = [];

  // ---------------------------------------------------------- state

  let state = loadState(storage, scope, key, columns, defaults);
  const base = defaultState(columns, defaults);
  PERSIST_FIELDS.forEach(function (f) { if (persist.indexOf(f) < 0) state[f] = base[f]; });
  if (url) applyUrl(readQuery());

  function readQuery() {
    try { return url.get() || {}; } catch (e) { return {}; }
  }

  // URL beats storage: q and pg always come from the URL; sort and filters only
  // when the URL carries them.
  function applyUrl(query) {
    const u = paramsToState(query, columns);
    const hasF = Object.keys(query).some(function (k) { return k.indexOf('f.') === 0; });
    const partial = { q: u.q, page: u.page };
    if (own(query, 'sort')) partial.sort = u.sort;
    if (hasF) partial.filters = u.filters;
    state = mergeState(state, partial, columns);
  }

  function saveNow() {
    if (!persist.length) return;
    const rec = Object.assign({}, state);
    PERSIST_FIELDS.forEach(function (f) { if (persist.indexOf(f) < 0) rec[f] = base[f]; });
    saveState(storage, scope, key, rec);
  }

  function syncUrl() {
    if (!url) return;
    const patch = urlPatch(readQuery(), state);
    if (Object.keys(patch).length) {
      try { url.set(patch); } catch (e) { /* the view's binding failed; state stays local */ }
    }
  }

  function snapshot() {
    const s = mergeState(state, {}, columns);
    if (view && !loading && view.total) s.page = view.page;
    return s;
  }

  function emit(type, detail) {
    root.dispatchEvent(new CustomEvent(type, { detail: detail, bubbles: true }));
  }

  function commit(partial) {
    const before = JSON.stringify(state);
    state = mergeState(state, partial, columns);
    if (JSON.stringify(state) === before) return;
    saveNow();
    render();
    syncUrl();
    emit('dt:state', snapshot());
  }

  function visibleColumns() {
    return columns.filter(function (c) { return state.hidden.indexOf(c.key) < 0; });
  }

  function idOf(row) { return String(rowIdFn(row)); }
  function canSelect(row) { return selectable && (!canSelectFn || !!canSelectFn(row)); }

  // ---------------------------------------------------------- DOM skeleton

  const root = h('div', { class: 'dt-root', 'data-table': key, id: ids.root });
  const search = h('input', {
    type: 'search', class: 'dt-search', id: ids.search, placeholder: o.searchPlaceholder || 'Search\u2026',
    'aria-label': 'Search ' + (caption || 'table'), autocomplete: 'off', spellcheck: 'false', enterkeyhint: 'search',
  });
  const count = h('span', { class: 'dt-count', role: 'status', 'aria-live': 'polite' });
  const filterBtns = {};
  const filterBox = h('div', { class: 'dt-filters' });
  columns.forEach(function (c) {
    if (!c.filterable) return;
    const b = h('button', {
      type: 'button', class: 'dt-filter', 'data-col': c.key, id: filterIds[c.key], 'aria-haspopup': 'dialog', 'aria-expanded': 'false',
    }, [h('span', { class: 'dt-filter-label', text: c.header }), h('span', { class: 'dt-filter-n' }), h('span', { class: 'dt-caret', 'aria-hidden': 'true', text: '\u25BE' })]);
    filterBtns[c.key] = b;
    filterBox.appendChild(b);
  });
  const sortSelect = h('select', { class: 'dt-sort-select', 'aria-label': 'Sort by' });
  sortSelect.appendChild(h('option', { value: '', text: 'Sort: default' }));
  columns.forEach(function (c) {
    if (!c.sortable) return;
    sortSelect.appendChild(h('option', { value: c.key, text: c.header + ' \u2191' }));
    sortSelect.appendChild(h('option', { value: '-' + c.key, text: c.header + ' \u2193' }));
  });
  const colsList = h('div', { class: 'dt-cols-list', role: 'group', 'aria-label': 'Visible columns' });
  const densityBox = h('input', { type: 'checkbox', class: 'dt-density' });
  const colsPanel = h('div', { class: 'dt-cols-panel' }, [
    colsList,
    h('label', { class: 'dt-opt dt-density-opt' }, [densityBox, h('span', { text: 'Compact rows' })]),
  ]);
  const colsSummary = h('summary', { class: 'dt-cols-btn', 'aria-label': 'Columns and density' }, [
    h('span', { class: 'dt-cols-glyph', 'aria-hidden': 'true', text: '\u2630' }), h('span', { class: 'dt-cols-text', text: 'Columns' }),
  ]);
  const colsBox = h('details', { class: 'dt-cols', id: ids.columns }, [colsSummary, colsPanel]);
  const csv = h('a', {
    class: 'dt-csv', id: ids.csv, role: 'button', href: '#', download: o.csvName || 'export.csv', 'aria-label': 'Download CSV',
  }, [h('span', { 'aria-hidden': 'true', text: '\u21E9' }), h('span', { class: 'dt-csv-text', text: 'CSV' })]);
  const actions = h('div', { class: 'dt-actions' });
  (Array.isArray(o.actions) ? o.actions : []).forEach(function (n) { if (isNode(n)) actions.appendChild(n); });
  const toolbar = h('div', { class: 'dt-toolbar' }, [
    h('div', { class: 'dt-search-wrap' }, [search, count]),
    filterBox, sortSelect, colsBox, csv, actions,
  ]);

  const bulkCount = h('span', { class: 'dt-bulk-count', role: 'status', 'aria-live': 'polite' });
  const bulkAll = h('button', { type: 'button', class: 'dt-bulk-all' });
  const bulkClear = h('button', { type: 'button', class: 'dt-bulk-clear', text: 'Clear' });
  const bulkBox = h('div', { class: 'dt-bulk-actions' });
  bulkActions.forEach(function (a) {
    if (isNode(a)) { bulkBox.appendChild(a); return; }
    if (!a || typeof a.run !== 'function') return;
    bulkBox.appendChild(h('button', {
      type: 'button', class: 'dt-bulk-act' + (a.danger ? ' danger' : ''),
      onclick: function () {
        const picked = selectedRows();
        if (!picked.length) return;
        Promise.resolve().then(function () { return a.run(picked); }).catch(function (e) { console.error(e); });
      },
    }, a.label || 'Apply'));
  });
  const bulk = h('div', { class: 'dt-bulk', hidden: true, role: 'region', 'aria-label': 'Selection' }, [bulkCount, bulkBox, bulkAll, bulkClear]);

  const thead = h('thead');
  const tbody = h('tbody');
  const table = h('table', { class: 'dt-table', id: ids.table }, [caption ? h('caption', { class: 'dt-caption', text: caption }) : null, thead, tbody]);
  const scroller = h('div', { class: 'dt-scroll' }, table);
  const emptyBox = h('div', { class: 'dt-empty', hidden: true });
  const errorBox = h('div', { class: 'dt-error', hidden: true, role: 'alert' });

  const pgFirst = h('button', { type: 'button', class: 'dt-first', 'aria-label': 'First page', text: '\u00AB' });
  const pgPrev = h('button', { type: 'button', class: 'dt-prev', 'aria-label': 'Previous page', text: '\u2039' });
  const pgNext = h('button', { type: 'button', class: 'dt-next', 'aria-label': 'Next page', text: '\u203A' });
  const pgLast = h('button', { type: 'button', class: 'dt-last', 'aria-label': 'Last page', text: '\u00BB' });
  const pgRange = h('span', { class: 'dt-range' });
  const pgSize = h('select', { class: 'dt-size', 'aria-label': 'Rows per page' });
  pageSizes.forEach(function (n) { pgSize.appendChild(h('option', { value: String(n), text: n + ' / page' })); });
  const pager = h('div', { class: 'dt-pager' }, [
    h('div', { class: 'dt-pager-nav' }, [pgFirst, pgPrev, pgRange, pgNext, pgLast]), pgSize,
  ]);

  root.appendChild(toolbar);
  root.appendChild(bulk);
  root.appendChild(errorBox);
  root.appendChild(scroller);
  root.appendChild(emptyBox);
  root.appendChild(pager);
  if (selectable) root.classList.add('dt-selectable');
  if (o.sticky !== false) root.classList.add('dt-sticky-head');
  if (o.cards) root.classList.add('dt-cards');
  if (typeof o.onRow === 'function') root.classList.add('dt-clickable');
  if (!columns.some(function (c) { return c.filterable; })) filterBox.hidden = true;
  if (o.csv === false) csv.hidden = true;
  if (o.search === false) toolbar.querySelector('.dt-search-wrap').classList.add('dt-no-search');
  if (!actions.childNodes.length) actions.hidden = true;
  if (host) host.appendChild(root);

  // ---------------------------------------------------------- head

  function renderHead() {
    const vis = visibleColumns();
    const sig = vis.map(function (c) { return c.key; }).join('|') + (selectable ? '|#' : '');
    if (sig !== headSig) {
      headSig = sig;
      thead.innerHTML = '';
      const tr = h('tr');
      if (selectable) {
        tr.appendChild(h('th', { scope: 'col', class: 'dt-check' }, h('label', { class: 'dt-check-hit' }, [
          h('input', { type: 'checkbox', class: 'dt-select-all', id: ids.selectAll }),
        ])));
      }
      vis.forEach(function (c) {
        const cls = 'dt-col dt-al-' + c.align + (c.hideOnMobile ? ' dt-hide-sm' : '') + (c.sticky ? ' dt-sticky' : '');
        const th = h('th', { scope: 'col', class: cls, 'data-col': c.key });
        if (c.width != null) th.style.width = typeof c.width === 'number' ? c.width + 'px' : String(c.width);
        if (c.sortable) {
          th.appendChild(h('button', { type: 'button', class: 'dt-sort', 'data-col': c.key }, [
            h('span', { class: 'dt-th-text', text: c.header }), h('span', { class: 'dt-sort-ind', 'aria-hidden': 'true' }),
          ]));
        } else {
          th.appendChild(h('span', { class: 'dt-th-text', text: c.header }));
        }
        tr.appendChild(th);
      });
      thead.appendChild(tr);
    }
    Array.prototype.forEach.call(thead.querySelectorAll('th[data-col]'), function (th) {
      const c = colByKey[th.getAttribute('data-col')];
      if (!c || !c.sortable) return;
      const dir = state.sort && state.sort.col === c.key ? state.sort.dir : 0;
      th.setAttribute('aria-sort', dir > 0 ? 'ascending' : dir < 0 ? 'descending' : 'none');
      th.querySelector('.dt-sort-ind').textContent = dir > 0 ? '\u25B2' : dir < 0 ? '\u25BC' : '';
      th.querySelector('.dt-sort').setAttribute('aria-label', c.header + (dir > 0 ? ', sorted ascending' : dir < 0 ? ', sorted descending' : '') + '. Sort');
    });
    sortSelect.value = state.sort ? (state.sort.dir < 0 ? '-' : '') + state.sort.col : '';
  }

  const colChecks = {};
  columns.forEach(function (c) {
    const cb = h('input', { type: 'checkbox', 'data-col': c.key });
    colChecks[c.key] = cb;
    colsList.appendChild(h('label', { class: 'dt-opt' }, [
      cb, h('span', { text: c.header || c.key }), c.hideOnMobile ? h('span', { class: 'dt-opt-note', text: 'wider screens' }) : null,
    ]));
  });

  function renderColsPanel() {
    const nVis = visibleColumns().length;
    columns.forEach(function (c) {
      const cb = colChecks[c.key];
      const shown = state.hidden.indexOf(c.key) < 0;
      cb.checked = shown;
      cb.disabled = shown && nVis <= 1;
      const noteEl = cb.parentNode.querySelector('.dt-opt-note');
      if (noteEl) noteEl.hidden = layout !== 'sm';
    });
    densityBox.checked = state.density === 'compact';
  }

  // ---------------------------------------------------------- body

  function renderSkeleton(vis) {
    const n = vis.length + (selectable ? 1 : 0);
    for (let i = 0; i < SKELETON_ROWS; i++) {
      const tr = h('tr', { class: 'dt-skel', 'aria-hidden': 'true' });
      for (let j = 0; j < n; j++) tr.appendChild(h('td', null, h('span', { class: 'dt-skel-bar' })));
      tbody.appendChild(tr);
    }
  }

  function pruneSelection() {
    if (!selected.size) return false;
    const keep = {};
    view.rows.forEach(function (r) { keep[idOf(r)] = true; });
    let changed = false;
    selected.forEach(function (id) { if (!keep[id]) { selected.delete(id); changed = true; } });
    return changed;
  }

  function locateHighlight() {
    if (highlight === null || !view) return;
    for (let i = 0; i < view.rows.length; i++) {
      if (idOf(view.rows[i]) === highlight) {
        const page = Math.floor(i / view.pageSize) + 1;
        if (page !== view.page) {
          state = mergeState(state, { page: page }, columns);
          view = compute();
        }
        return;
      }
    }
  }

  function compute() {
    return applyState(rows, columns, state, { index: index, groupBy: o.groupBy, groupOrder: o.groupOrder });
  }

  function renderBody() {
    const vis = visibleColumns();
    tbody.innerHTML = '';
    pageById = {};
    table.setAttribute('aria-busy', loading ? 'true' : 'false');
    errorBox.hidden = !error;
    errorBox.innerHTML = '';
    if (error) {
      const msg = error.err && error.err.message ? error.err.message : String(error.err);
      errorBox.appendChild(h('span', { class: 'dt-error-text', text: msg }));
      if (typeof error.retry === 'function') {
        const retry = error.retry;
        errorBox.appendChild(h('button', { type: 'button', class: 'dt-retry', onclick: function () { retry(); } }, 'Retry'));
      }
    }
    if (loading) {
      renderSkeleton(vis);
      emptyBox.hidden = true;
      return;
    }
    if (error) {
      emptyBox.hidden = true;
      return;
    }
    const frag = document.createDocumentFragment();
    const n = vis.length + (selectable ? 1 : 0);
    let lastGroup = null;
    view.pageRows.forEach(function (row) {
      if (typeof o.groupBy === 'function') {
        const g = textOf(o.groupBy(row));
        if (g !== lastGroup) {
          lastGroup = g;
          frag.appendChild(h('tr', { class: 'dt-group' }, h('th', { scope: 'colgroup', colspan: String(n), text: g || '(none)' })));
        }
      }
      const id = idOf(row);
      pageById[id] = row;
      const extra = typeof o.rowAttrs === 'function' ? (o.rowAttrs(row) || {}) : {};
      const tr = h('tr', extra);
      tr.setAttribute('data-id', id);
      tr.setAttribute('tabindex', '0');
      tr.classList.add('dt-row');
      if (typeof o.rowClass === 'function') {
        const rc = o.rowClass(row);
        if (rc) String(rc).split(/\s+/).forEach(function (c) { if (c) tr.classList.add(c); });
      }
      if (highlight !== null && id === highlight) tr.classList.add('dt-hl');
      if (selectable) {
        const ok = canSelect(row);
        const on = selected.has(id);
        if (on) tr.classList.add('dt-sel');
        const first = vis[0] ? textOf(vis[0].value(row)) : id;
        tr.appendChild(h('td', { class: 'dt-check' }, h('label', { class: 'dt-check-hit' }, [
          h('input', { type: 'checkbox', class: 'dt-row-check', checked: on, disabled: !ok, 'aria-label': 'Select ' + (first || id) }),
        ])));
      }
      vis.forEach(function (c, ci) {
        const cls = 'dt-al-' + c.align + (c.hideOnMobile ? ' dt-hide-sm' : '') + (c.sticky ? ' dt-sticky' : '') + (ci === 0 ? ' dt-lead' : '');
        const td = h('td', { class: cls, 'data-col': c.key, 'data-label': c.header });
        const content = cellContent(c.cell ? c.cell(row) : textOf(c.value(row)));
        if (content) td.appendChild(content);
        tr.appendChild(td);
      });
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
    renderEmpty();
  }

  function renderEmpty() {
    emptyBox.innerHTML = '';
    if (view.filtered > 0) { emptyBox.hidden = true; return; }
    emptyBox.hidden = false;
    const info = { total: view.total, filtered: view.filtered };
    if (typeof o.empty === 'function') {
      const node = cellContent(o.empty(snapshot(), info));
      if (node) emptyBox.appendChild(node);
      return;
    }
    if (view.total === 0) {
      emptyBox.appendChild(h('p', { class: 'dt-empty-text', text: o.empty || 'Nothing here yet.' }));
      return;
    }
    emptyBox.appendChild(h('p', { class: 'dt-empty-text', text: 'No rows match these filters.' }));
    emptyBox.appendChild(h('button', { type: 'button', class: 'dt-clear', onclick: function () {
      search.value = '';
      commit({ q: '', filters: {} });
      search.focus();
    } }, 'Clear filters'));
  }

  function renderPager() {
    const busy = loading || !!error;
    const pages = view.pages;
    pager.setAttribute('data-page', String(view.page));
    pager.setAttribute('data-pages', String(pages));
    pager.classList.toggle('dt-one-page', pages <= 1);
    pgFirst.disabled = pgPrev.disabled = busy || view.page <= 1;
    pgNext.disabled = pgLast.disabled = busy || view.page >= pages;
    pgRange.textContent = loading ? 'Loading\u2026' : view.filtered === 0 ? '0 of ' + fmt(view.total)
      : fmt(view.start + 1) + '\u2013' + fmt(view.start + view.pageRows.length) + ' of ' + fmt(view.filtered);
    pgSize.value = String(state.pageSize);
    if (pgSize.value !== String(state.pageSize)) {
      pgSize.appendChild(h('option', { value: String(state.pageSize), text: state.pageSize + ' / page' }));
      pgSize.value = String(state.pageSize);
    }
    const nn = noun || { one: 'row', many: 'rows' };
    const total = fmt(view.total) + ' ' + (view.total === 1 ? nn.one : nn.many);
    count.textContent = loading ? 'Loading\u2026' : view.filtered === view.total ? total : fmt(view.filtered) + ' of ' + total;
  }

  function renderToolbar() {
    if (document.activeElement !== search && search.value !== state.q) search.value = state.q;
    columns.forEach(function (c) {
      const b = filterBtns[c.key];
      if (!b) return;
      const n = (state.filters[c.key] || []).length;
      b.classList.toggle('dt-on', n > 0);
      b.querySelector('.dt-filter-n').textContent = n ? String(n) : '';
      b.setAttribute('aria-label', 'Filter ' + c.header + (n ? ' (' + n + ' selected)' : ''));
    });
    root.classList.toggle('dt-compact', state.density === 'compact');
    renderColsPanel();
  }

  function renderSelection() {
    if (!selectable || !view) return;
    const all = thead.querySelector('.dt-select-all');
    let selectableCount = 0;
    view.rows.forEach(function (r) { if (canSelect(r)) selectableCount++; });
    const n = selected.size;
    if (all) {
      all.checked = n > 0 && n >= selectableCount;
      all.indeterminate = n > 0 && n < selectableCount;
      all.disabled = selectableCount === 0;
      all.setAttribute('aria-label', 'Select all ' + fmt(selectableCount) + ' matching');
      all.title = 'Select all ' + fmt(selectableCount) + ' matching';
    }
    bulk.hidden = n === 0;
    bulkCount.textContent = fmt(n) + ' ' + (noun ? (n === 1 ? noun.one : noun.many) + ' ' : '') + 'selected';
    bulkAll.hidden = n >= selectableCount;
    bulkAll.textContent = 'Select all ' + fmt(selectableCount) + ' matching';
    Array.prototype.forEach.call(tbody.querySelectorAll('tr.dt-row'), function (tr) {
      const on = selected.has(tr.getAttribute('data-id'));
      tr.classList.toggle('dt-sel', on);
      const cb = tr.querySelector('.dt-row-check');
      if (cb) cb.checked = on;
    });
  }

  // state.page keeps the requested page (a deep-linked pg survives rows that are
  // still loading); view.page is the clamped page on screen.
  function render() {
    if (destroyed) return;
    view = compute();
    locateHighlight();
    const pruned = loading ? false : pruneSelection();
    renderHead();
    renderBody();
    renderPager();
    renderToolbar();
    renderSelection();
    markCsvStale();
    if (pruned) emit('dt:select', { ids: selectionIds() });
    if (scrollToHl && tbody.querySelector('tr.dt-hl')) {
      scrollToHl = false;
      setTimeout(function () {
        const tr = tbody.querySelector('tr.dt-hl');
        if (tr && tr.scrollIntoView) tr.scrollIntoView({ block: 'center', inline: 'nearest' });
      }, 0);
    }
  }

  // ---------------------------------------------------------- selection

  function selectionIds() {
    if (!view) return Array.from(selected);
    return view.rows.map(idOf).filter(function (id) { return selected.has(id); });
  }

  function selectedRows() {
    return view ? view.rows.filter(function (r) { return selected.has(idOf(r)); }) : [];
  }

  function selectionChanged() {
    renderSelection();
    emit('dt:select', { ids: selectionIds() });
  }

  function selectAll(onOff) {
    selected.clear();
    if (onOff) view.rows.forEach(function (r) { if (canSelect(r)) selected.add(idOf(r)); });
    selectionChanged();
  }

  // ---------------------------------------------------------- CSV

  function markCsvStale() {
    csvStale = true;
    if (csvTimer) clearTimeout(csvTimer);
    csvTimer = setTimeout(buildCsv, view && view.filtered > DEBOUNCE_ROWS ? 400 : 60);
  }

  function buildCsv() {
    if (csvTimer) { clearTimeout(csvTimer); csvTimer = 0; }
    if (!csvStale || destroyed || !view) return;
    csvStale = false;
    const text = toCsv(visibleColumns(), view.rows);
    if (csvUrl) { try { URL.revokeObjectURL(csvUrl); } catch (e) { /* already gone */ } }
    try {
      csvUrl = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
    } catch (e) {
      csvUrl = '';
    }
    csv.setAttribute('href', csvUrl || 'data:text/csv;charset=utf-8,' + encodeURIComponent(text));
    csv.setAttribute('aria-label', 'Download CSV (' + plural(view.filtered, noun) + ')');
    csv.setAttribute('data-rows', String(view.filtered));
  }

  // ---------------------------------------------------------- filter popover

  function closePop(focusBack) {
    if (!pop) return;
    const p = pop;
    pop = null;
    p.off.forEach(function (f) { f(); });
    p.el.remove();
    p.btn.setAttribute('aria-expanded', 'false');
    if (focusBack) p.btn.focus();
  }

  function openFilter(col, btn) {
    const was = pop && pop.col === col.key;
    closePop(false);
    colsBox.open = false;
    if (was) return;
    const values = distinctValues(rows, col, index);
    const counts = {};
    index.filterValues(col.key).forEach(function (vs) { vs.forEach(function (v) { counts[v] = (counts[v] || 0) + 1; }); });
    const popId = uid('pop');
    const list = h('ul', { class: 'dt-pop-list', role: 'group', 'aria-label': col.header + ' values' });
    const note = h('p', { class: 'dt-pop-note', hidden: true });
    const find = values.length > POP_SEARCH_AT ? h('input', { type: 'search', class: 'dt-pop-search', placeholder: 'Find a value\u2026', 'aria-label': 'Find a ' + col.header + ' value' }) : null;
    function current() { return state.filters[col.key] || []; }
    function fill() {
      const qq = find ? find.value.trim().toLowerCase() : '';
      const chosen = current();
      list.innerHTML = '';
      let shown = 0;
      let matched = 0;
      for (let i = 0; i < values.length; i++) {
        const v = values[i];
        if (qq && v.toLowerCase().indexOf(qq) < 0) continue;
        matched++;
        if (shown >= POP_MAX_VALUES) continue;
        shown++;
        list.appendChild(h('li', null, h('label', { class: 'dt-opt' }, [
          h('input', { type: 'checkbox', value: v, checked: chosen.indexOf(v) >= 0 }),
          h('span', { class: 'dt-pop-val' + (v === EMPTY ? ' dt-pop-empty' : ''), text: v }),
          h('span', { class: 'dt-pop-n', text: fmt(counts[v] || 0) }),
        ])));
      }
      note.hidden = matched <= shown;
      note.textContent = 'Showing ' + fmt(shown) + ' of ' + fmt(matched) + ' values. Type to narrow.';
      if (!matched) list.appendChild(h('li', { class: 'dt-pop-none', text: 'No values' }));
    }
    const el = h('div', { class: 'dt-pop', id: popId, role: 'dialog', 'aria-label': 'Filter by ' + col.header, 'data-col': col.key }, [
      h('div', { class: 'dt-pop-head' }, [
        h('strong', { text: col.header }),
        h('button', { type: 'button', class: 'dt-pop-clear', onclick: function () {
          const f = Object.assign({}, state.filters);
          delete f[col.key];
          commit({ filters: f });
          fill();
        } }, 'Clear'),
        h('button', { type: 'button', class: 'dt-pop-close', 'aria-label': 'Close', onclick: function () { closePop(true); } }, '\u00D7'),
      ]),
      find, list, note,
    ]);
    fill();
    el.addEventListener('change', function (e) {
      const t = e.target;
      if (!t || t.type !== 'checkbox') return;
      const chosen = current().slice();
      const i = chosen.indexOf(t.value);
      if (t.checked && i < 0) chosen.push(t.value);
      if (!t.checked && i >= 0) chosen.splice(i, 1);
      const f = Object.assign({}, state.filters);
      if (chosen.length) f[col.key] = chosen; else delete f[col.key];
      commit({ filters: f });
    });
    if (find) find.addEventListener('input', fill);
    el.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closePop(true); }
    });
    root.appendChild(el);
    const offsList = [
      on(document, 'pointerdown', function (e) { if (pop && !el.contains(e.target) && !btn.contains(e.target)) closePop(false); }, true),
      on(window, 'resize', function () { if (pop) place(el, btn); }),
    ];
    pop = { el: el, btn: btn, col: col.key, off: offsList };
    btn.setAttribute('aria-expanded', 'true');
    btn.setAttribute('aria-controls', popId);
    place(el, btn);
    const first = find || el.querySelector('.dt-pop-list input');
    if (first) first.focus();
  }

  function place(el, anchor) {
    el.style.left = '';
    el.style.top = '';
    if (layoutFor(window.innerWidth) === 'sm') return;
    const rr = root.getBoundingClientRect();
    const br = anchor.getBoundingClientRect();
    const w = el.offsetWidth;
    let left = br.left - rr.left;
    left = Math.max(0, Math.min(left, rr.width - w));
    el.style.left = left + 'px';
    el.style.top = (br.bottom - rr.top + 4) + 'px';
  }

  // ---------------------------------------------------------- events

  offs.push(on(search, 'input', function () {
    if (searchTimer) clearTimeout(searchTimer);
    const run = function () { searchTimer = 0; commit({ q: search.value }); };
    if (rows.length > DEBOUNCE_ROWS) searchTimer = setTimeout(run, 150); else run();
  }));
  offs.push(on(search, 'keydown', function (e) {
    if (e.key === 'Escape' && search.value) { e.preventDefault(); e.stopPropagation(); search.value = ''; commit({ q: '' }); }
    if (e.key === 'Enter') { e.preventDefault(); if (searchTimer) { clearTimeout(searchTimer); searchTimer = 0; commit({ q: search.value }); } }
  }));
  offs.push(on(filterBox, 'click', function (e) {
    const b = e.target.closest('.dt-filter');
    if (!b) return;
    const c = colByKey[b.getAttribute('data-col')];
    if (c) openFilter(c, b);
  }));
  offs.push(on(sortSelect, 'change', function () {
    const v = sortSelect.value;
    commit({ sort: v ? { col: v.charAt(0) === '-' ? v.slice(1) : v, dir: v.charAt(0) === '-' ? -1 : 1 } : null });
  }));
  offs.push(on(thead, 'click', function (e) {
    const b = e.target.closest('.dt-sort');
    if (b) {
      const k = b.getAttribute('data-col');
      const cur = state.sort && state.sort.col === k ? state.sort.dir : 0;
      commit({ sort: cur === 0 ? { col: k, dir: 1 } : cur === 1 ? { col: k, dir: -1 } : null });
      return;
    }
  }));
  offs.push(on(thead, 'change', function (e) {
    if (e.target && e.target.classList.contains('dt-select-all')) selectAll(e.target.checked);
  }));
  offs.push(on(colsBox, 'toggle', function () {
    if (colsBox.open) {
      closePop(false);
      place(colsPanel, colsSummary);
    }
  }));
  offs.push(on(colsPanel, 'change', function (e) {
    const t = e.target;
    if (t === densityBox) { commit({ density: densityBox.checked ? 'compact' : 'normal' }); return; }
    const k = t && t.getAttribute('data-col');
    if (!k) return;
    const hidden = state.hidden.filter(function (x) { return x !== k; });
    if (!t.checked) hidden.push(k);
    commit({ hidden: hidden });
  }));
  offs.push(on(colsBox, 'keydown', function (e) {
    if (e.key === 'Escape' && colsBox.open) { e.preventDefault(); e.stopPropagation(); colsBox.open = false; colsSummary.focus(); }
  }));
  offs.push(on(document, 'pointerdown', function (e) {
    if (colsBox.open && !colsBox.contains(e.target)) colsBox.open = false;
  }, true));
  ['pointerdown', 'focus', 'mouseenter', 'click'].forEach(function (t) {
    offs.push(on(csv, t, function (e) {
      if (csvStale) buildCsv();
      if (t === 'click' && csv.getAttribute('href') === '#') e.preventDefault();
    }));
  });
  offs.push(on(csv, 'keydown', function (e) { if (e.key === ' ') { e.preventDefault(); csv.click(); } }));
  offs.push(on(bulkAll, 'click', function () { selectAll(true); }));
  offs.push(on(bulkClear, 'click', function () { selectAll(false); }));
  offs.push(on(pgFirst, 'click', function () { commit({ page: 1 }); }));
  offs.push(on(pgPrev, 'click', function () { commit({ page: Math.max(1, view.page - 1) }); }));
  offs.push(on(pgNext, 'click', function () { commit({ page: Math.min(view.pages, view.page + 1) }); }));
  offs.push(on(pgLast, 'click', function () { commit({ page: view.pages }); }));
  offs.push(on(pgSize, 'change', function () { commit({ pageSize: Number(pgSize.value) }); }));

  function activate(tr, e) {
    const id = tr.getAttribute('data-id');
    if (!own(pageById, id)) return;
    const row = pageById[id];
    if (typeof o.onRow === 'function') o.onRow(row, e);
    emit('dt:row', { id: id, row: row });
  }

  offs.push(on(tbody, 'click', function (e) {
    const t = e.target;
    const tr = t && t.closest ? t.closest('tr.dt-row') : null;
    if (!tr) return;
    if (t.classList && t.classList.contains('dt-row-check')) { shiftClick = !!e.shiftKey; return; }
    const skip = t.closest(IGNORE_ROW_CLICK);
    if (skip && tr.contains(skip)) return;
    const sel = window.getSelection ? window.getSelection() : null;
    if (sel && !sel.isCollapsed && sel.anchorNode && tr.contains(sel.anchorNode)) return;
    activate(tr, e);
  }));
  offs.push(on(tbody, 'change', function (e) {
    const t = e.target;
    if (!t || !t.classList.contains('dt-row-check')) return;
    const tr = t.closest('tr.dt-row');
    const id = tr.getAttribute('data-id');
    const ids2 = view.pageRows.map(idOf);
    if (shiftClick && lastChecked !== null && ids2.indexOf(lastChecked) >= 0) {
      const a = ids2.indexOf(lastChecked);
      const b = ids2.indexOf(id);
      ids2.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(function (x) {
        if (!canSelect(pageById[x])) return;
        if (t.checked) selected.add(x); else selected.delete(x);
      });
    } else if (t.checked) selected.add(id); else selected.delete(id);
    shiftClick = false;
    lastChecked = id;
    selectionChanged();
  }));
  offs.push(on(tbody, 'keydown', function (e) {
    const tr = e.target;
    if (!tr || !tr.classList || !tr.classList.contains('dt-row')) return;
    if (e.key === 'Enter') { e.preventDefault(); activate(tr, e); return; }
    if (e.key === ' ' && selectable) {
      e.preventDefault();
      const cb = tr.querySelector('.dt-row-check');
      if (cb && !cb.disabled) cb.click();
      return;
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const all = Array.prototype.slice.call(tbody.querySelectorAll('tr.dt-row'));
      const i = all.indexOf(tr) + (e.key === 'ArrowDown' ? 1 : -1);
      if (i >= 0 && i < all.length) { e.preventDefault(); all[i].focus(); }
    }
  }));
  offs.push(on(window, 'resize', function () {
    const l = layoutFor(window.innerWidth);
    if (l === layout) return;
    layout = l;
    root.setAttribute('data-layout', l);
    renderColsPanel();
  }));
  root.setAttribute('data-layout', layout);

  render();

  // ---------------------------------------------------------- handle

  return {
    root: root,
    setRows: function (next) {
      rows = Array.isArray(next) ? next : [];
      index = createIndex(rows, columns);
      loading = false;
      error = null;
      render();
    },
    setLoading: function (b) { loading = !!b; if (loading) error = null; render(); },
    setError: function (err, retry) {
      error = err ? { err: err, retry: retry } : null;
      loading = false;
      render();
    },
    setHighlight: function (id) {
      highlight = id === null || id === undefined || id === '' ? null : String(id);
      scrollToHl = highlight !== null;
      render();
    },
    getState: snapshot,
    setState: function (partial) {
      if (partial && own(partial, 'q') && document.activeElement === search) search.value = String(partial.q || '');
      commit(partial || {});
    },
    readUrl: function () {
      if (!url) return;
      const before = JSON.stringify(state);
      applyUrl(readQuery());
      if (JSON.stringify(state) === before) return;
      saveNow();
      render();
      emit('dt:state', snapshot());
    },
    info: function () {
      return view ? { total: view.total, filtered: view.filtered, page: view.page, pages: view.pages, pageSize: view.pageSize } : null;
    },
    getSelection: selectionIds,
    clearSelection: function () { if (selected.size) selectAll(false); },
    refresh: function () { index = createIndex(rows, columns); render(); },
    destroy: function () {
      if (destroyed) return;
      destroyed = true;
      closePop(false);
      if (csvTimer) clearTimeout(csvTimer);
      if (searchTimer) clearTimeout(searchTimer);
      offs.forEach(function (f) { f(); });
      if (csvUrl) { try { URL.revokeObjectURL(csvUrl); } catch (e) { /* gone */ } }
      root.remove();
    },
  };
}

// ------------------------------------------------------------ drill-down dialog

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])';

// Minimal modal for hosts without ctx.openDialog (dev harnesses): same classes as
// the shell's dialog so its Esc priority (.app-dialog-backdrop) still applies.
function fallbackDialog(title, body, onClose) {
  let closer = null;
  const promise = new Promise(function (resolve) {
    const opener = document.activeElement;
    const titleId = uid('title');
    const box = h('div', { class: 'app-dialog wide dt-dialog', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': titleId }, [
      h('header', null, [
        h('h2', { id: titleId, text: title }),
        h('button', { type: 'button', class: 'icon ghost dt-dialog-close', 'aria-label': 'Close', onclick: function () { close(null); } }, '\u00D7'),
      ]),
      h('div', { class: 'body' }, body),
    ]);
    const back = h('div', { class: 'app-dialog-backdrop dt-dialog-backdrop' }, box);
    let done = false;
    function onKey(e) {
      if (e.key === 'Escape') {
        if (e.defaultPrevented) return;
        e.preventDefault();
        close(null);
        return;
      }
      if (e.key === 'Tab') {
        const f = Array.prototype.filter.call(box.querySelectorAll(FOCUSABLE), function (x) { return x.offsetParent !== null; });
        if (!f.length) return;
        if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    }
    function close(v) {
      if (done) return;
      done = true;
      box.removeEventListener('keydown', onKey);
      back.remove();
      onClose(v);
      if (opener && opener.focus) { try { opener.focus(); } catch (e) { /* gone */ } }
      resolve(v);
    }
    back.addEventListener('pointerdown', function (e) { if (e.target === back) close(null); });
    box.addEventListener('keydown', onKey);
    (document.getElementById('app-dialog') || document.body).appendChild(back);
    const first = box.querySelector('.dt-search') || box.querySelector(FOCUSABLE);
    if (first) first.focus();
    closer = close;
  });
  return { promise: promise, close: closer };
}

// Searchable drill-down modal ("32 cables"). Resolves with the picked row, or null
// when closed. A row pick closes the dialog first, then calls onRow(row, event).
export function openTableDialog(ctx, opts) {
  const c = ctx || {};
  const o = opts || {};
  const title = o.title || '';
  const body = h('div', { class: 'dt-dialog-body' });
  let close = null;
  const table = createTable(body, {
    key: o.key || 'dialog',
    scope: c.project || '',
    caption: title,
    columns: o.columns,
    rows: o.rows,
    rowId: o.rowId,
    pageSize: o.pageSize || 25,
    sticky: true,
    persist: ['pageSize', 'hidden', 'density'],
    empty: o.empty || 'Nothing to show.',
    csvName: o.csvName || slug(title) + '.csv',
    storage: o.storage,
    onRow: function (row, e) {
      if (close) close(row);
      if (typeof o.onRow === 'function') o.onRow(row, e);
    },
  });
  if (typeof c.openDialog === 'function') {
    return Promise.resolve(c.openDialog({
      title: title,
      body: body,
      wide: true,
      onOpen: function (api) {
        close = api.close;
        if (api.box) api.box.classList.add('dt-dialog');
      },
      onClose: function () { table.destroy(); },
    })).then(function (v) { return v || null; });
  }
  const d = fallbackDialog(title, body, function () { table.destroy(); });
  close = d.close;
  return d.promise.then(function (v) { return v || null; });
}
