// Files view: every attachment of the project (photos, PDFs, documents, floor-plan sources)
// in the shared DataTable with filters by kind and device, project-level upload and delete.
// A file opens in a new tab; the device column selects that device. mount(el, ctx) (§6.4).
import {h, on} from './dom.js';
import {createTable} from './datatable.js';
import {emptyState, skeleton} from './feedback.js';

const PROJECT = 'Project';
const ACCEPT = 'image/*,application/pdf,.txt,.csv,.md';
const FILE_NOUN = {one: 'file', many: 'files'};
const FILTER_IDS = {kind: 'files-kind', device: 'files-device'};
const MOBILE_COLUMNS = ['name', 'kind', 'device', 'size'];

function list(v) { return Array.isArray(v) ? v : []; }

function byId(arr) {
  const m = {};
  list(arr).forEach(function (e) { if (e && e.id != null) m[e.id] = e; });
  return m;
}

// image | pdf | other from the stored mime (falls back to the file name).
export function fileKind(att) {
  const mime = String((att && att.mime) || '').toLowerCase();
  const name = String((att && att.name) || '').toLowerCase();
  if (mime.indexOf('image/') === 0) return 'image';
  if (mime === 'application/pdf' || /\.pdf$/.test(name)) return 'pdf';
  return 'other';
}

export function formatSize(n) {
  const b = Number(n);
  if (!(b >= 0)) return '';
  if (b < 1024) return b + ' B';
  if (b < 1024 * 1024) return (b / 1024).toFixed(b < 10240 ? 1 : 0) + ' KB';
  if (b < 1024 * 1024 * 1024) return (b / (1024 * 1024)).toFixed(1) + ' MB';
  return (b / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

function when(s) {
  const t = String(s || '');
  return t.length >= 16 ? t.slice(0, 10) + ' ' + t.slice(11, 16) : t.slice(0, 10);
}

// One row per attachment; `device` is the device name or "Project" for unattached files.
export function fileRows(doc) {
  const devs = byId(doc && doc.devices);
  return list(doc && doc.attachments).map(function (a) {
    const dev = a.device ? devs[a.device] : null;
    return {
      id: a.id, name: a.name || a.id, kind: fileKind(a), mime: a.mime || '',
      device: a.device ? (dev ? dev.name || dev.id : a.device) : PROJECT, device_id: a.device || '',
      size: a.size == null ? '' : Number(a.size), size_text: formatSize(a.size), uploaded: a.uploaded || '', by: a.by || '',
      att_kind: a.kind || '', att: a,
    };
  }).sort(function (x, y) { return String(y.uploaded).localeCompare(String(x.uploaded)) || String(x.name).localeCompare(String(y.name), undefined, {numeric: true}); });
}

export function mount(el, ctx) {
  const store = ctx.store;
  const S = {destroyed: false, busy: false};
  const offs = [];
  let table = null;
  let builtReadOnly = null;
  let loadingNode = null;

  function readOnly() { return !!store.readOnly || ctx.role === 'viewer' || !ctx.api; }
  function doc() { return store.doc; }
  function docReady() { return !!store.doc && typeof store.doc === 'object'; }
  function route() { return ctx.route && typeof ctx.route === 'object' ? ctx.route : null; }
  function routed() { const r = route(); return !!r && r.view === 'files' && typeof ctx.setParams === 'function'; }
  function query() { const r = route(); return (r && r.query) || {}; }

  el.innerHTML = '';
  const root = h('div', {class: 'files-root'});
  const tableHost = h('div', {class: 'files-tablehost'});
  root.appendChild(tableHost);
  el.appendChild(root);

  // ------------------------------------------------------------ toolbar

  const fileInput = h('input', {type: 'file', id: 'files-upload', class: 'files-input', multiple: true, accept: ACCEPT, 'aria-label': 'Upload files'});
  const uploadLabel = h('label', {for: 'files-upload', class: 'files-btn files-primary files-upload', role: 'button', tabindex: '0', text: 'Upload\u2026'});
  const uploadBox = h('span', {class: 'files-uploadbox'}, [fileInput, uploadLabel]);
  const delBtn = h('button', {id: 'files-delete', type: 'button', class: 'files-btn files-danger', text: 'Delete'});

  function selectDevice(id) {
    const sel = {type: 'device', id: id};
    if (typeof ctx.select === 'function') ctx.select(sel);
    if (typeof ctx.openDrawer === 'function') ctx.openDrawer(sel);
  }

  function openFile(row) {
    const url = ctx.api && ctx.api.fileUrl ? ctx.api.fileUrl(ctx.project, row.att) : row.att.file;
    if (url && typeof window !== 'undefined' && window.open) window.open(url, '_blank', 'noopener');
  }

  const columns = [
    {
      key: 'name', header: 'Name', sticky: true,
      cell: function (r) {
        const url = ctx.api && ctx.api.fileUrl ? ctx.api.fileUrl(ctx.project, r.att) : r.att.file;
        return h('a', {class: 'files-name', href: url, target: '_blank', rel: 'noopener', 'data-file': r.id, text: r.name});
      },
    },
    {key: 'kind', header: 'Kind', filterable: true, cell: function (r) { return h('span', {class: 'files-kind files-kind-' + r.kind, text: r.kind}); }},
    {
      key: 'device', header: 'Device', filterable: true,
      cell: function (r) {
        if (!r.device_id) return h('span', {class: 'files-muted', text: PROJECT});
        return h('button', {
          type: 'button', class: 'files-link', 'data-device': r.device_id, text: r.device, title: 'Select ' + r.device,
          onclick: function (e) { e.stopPropagation(); selectDevice(r.device_id); },
        });
      },
    },
    {key: 'size', header: 'Size', align: 'right', value: function (r) { return r.size; }, cell: function (r) { return r.size_text; }, csv: function (r) { return r.size; }},
    {key: 'uploaded', header: 'Uploaded', hideOnMobile: true, cell: function (r) { return when(r.uploaded); }},
    {key: 'by', header: 'By', hideOnMobile: true},
  ].map(function (c) {
    if (c.hideOnMobile === undefined) c.hideOnMobile = MOBILE_COLUMNS.indexOf(c.key) < 0;
    return c;
  });

  function emptyNode(state, info) {
    if (info && info.total > 0) {
      return h('div', {class: 'files-empty'}, [
        h('p', {class: 'dt-empty-text', text: 'No files match these filters.'}),
        h('button', {type: 'button', class: 'dt-clear', onclick: function () { if (table) table.setState({q: '', filters: {}}); }}, 'Clear filters'),
      ]);
    }
    const ro = readOnly();
    return emptyState({
      title: 'No files yet.',
      text: ro ? 'Photos and documents uploaded to this project will be listed here.' : 'Upload photos, PDFs or notes for the whole project, or attach them to a device from its drawer.',
      action: ro ? null : {label: 'Upload\u2026', run: function () { fileInput.click(); }},
    });
  }

  function urlBinding() {
    if (!routed()) return null;
    return {
      get: function () { return query(); },
      set: function (patch) { ctx.setParams(patch, {replace: true}); },
    };
  }

  function build() {
    if (table) table.destroy();
    const ro = readOnly();
    builtReadOnly = ro;
    table = createTable(tableHost, {
      key: 'files',
      scope: ctx.project || '',
      caption: 'Files',
      columns: columns,
      rows: fileRows(doc()),
      rowAttrs: function (r) { return {'data-file': r.id}; },
      selectable: !ro,
      cards: true,
      noun: FILE_NOUN,
      bulkActions: ro ? [] : [delBtn],
      actions: ro ? [] : [uploadBox],
      ids: {table: 'files-table', columns: 'files-columns', csv: 'files-csv', search: 'files-filter', selectAll: 'files-select-all', filters: FILTER_IDS},
      url: urlBinding(),
      csvName: (ctx.project || 'project') + '-files.csv',
      searchPlaceholder: 'Search files',
      highlight: query().hl || null,
      empty: emptyNode,
      onRow: openFile,
    });
  }

  function refreshRows() { if (table) table.setRows(fileRows(doc())); }

  // ------------------------------------------------------------ upload / delete

  function applyUploaded(res) {
    const added = list(res && res.attachments);
    if (added.length && store.applyRemote) {
      const have = byId(doc().attachments);
      store.applyRemote(added.filter(function (a) { return !have[a.id]; }).map(function (a) { return {op: 'put', coll: 'attachments', id: a.id, value: a}; }), 'remote');
    }
    if (res && res.revision && store.setRevision && !(store.revision >= res.revision)) store.setRevision(res.revision);
    if (!added.length || !store.applyRemote) return Promise.resolve(ctx.reload ? ctx.reload() : null);
    return Promise.resolve(added.length);
  }

  function upload(files) {
    if (!files || !files.length || readOnly() || S.busy) return;
    S.busy = true;
    uploadLabel.setAttribute('aria-busy', 'true');
    fileInput.disabled = true;
    ctx.toast('Uploading ' + files.length + ' file' + (files.length === 1 ? '' : 's') + '\u2026', 'info');
    const go = ctx.flush ? ctx.flush() : Promise.resolve();
    go.then(function () { return ctx.api.upload(ctx.project, 'files', files); })
      .then(applyUploaded)
      .then(function () {
        ctx.toast('Uploaded ' + files.length + ' file' + (files.length === 1 ? '' : 's'), 'ok');
        refreshRows();
      }, function (e) { ctx.toast((e && e.message) || 'Upload failed.', 'err'); })
      .then(function () { S.busy = false; uploadLabel.removeAttribute('aria-busy'); fileInput.disabled = false; });
  }

  function deleteSelected() {
    if (!table || readOnly()) return;
    const ids = table.getSelection();
    if (!ids.length) { ctx.toast('Select files first.', 'info'); return; }
    const rows = byId(fileRows(doc()));
    const names = ids.map(function (id) { return rows[id] ? rows[id].name : id; });
    const msg = ids.length === 1 ? 'Delete ' + names[0] + '?' : 'Delete ' + ids.length + ' files?';
    ctx.confirm(msg + ' This cannot be undone.', {danger: true, ok: 'Delete'}).then(function (yes) {
      if (!yes) return;
      let done = 0;
      const failed = [];
      const next = function (i) {
        if (i >= ids.length) {
          if (done) ctx.toast('Deleted ' + done + ' file' + (done === 1 ? '' : 's'), 'ok');
          if (failed.length) ctx.toast('Could not delete ' + failed.join(', '), 'err');
          table.clearSelection();
          return Promise.resolve(ctx.reload ? ctx.reload() : null).then(refreshRows);
        }
        return ctx.api.deleteFile(ctx.project, ids[i]).then(function () { done++; }, function (e) {
          failed.push((rows[ids[i]] ? rows[ids[i]].name : ids[i]) + ((e && e.message) ? ' (' + e.message + ')' : ''));
        }).then(function () { return next(i + 1); });
      };
      return next(0);
    });
  }

  offs.push(on(fileInput, 'change', function () {
    const files = Array.prototype.slice.call(fileInput.files || []);
    fileInput.value = '';
    upload(files);
  }));
  offs.push(on(uploadLabel, 'keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); } }));
  offs.push(on(delBtn, 'click', deleteSelected));

  // ------------------------------------------------------------ lifecycle

  function start() {
    if (table || S.destroyed) return;
    if (!docReady()) {
      if (!loadingNode) { loadingNode = skeleton('table'); tableHost.appendChild(loadingNode); }
      return;
    }
    if (loadingNode) { loadingNode.remove(); loadingNode = null; }
    build();
  }
  function onDoc() { if (!table) start(); else refreshRows(); }
  function onMode() { if (!table) start(); else if (readOnly() !== builtReadOnly) build(); else refreshRows(); }
  store.addEventListener('doc', onDoc);
  store.addEventListener('mode', onMode);
  offs.push(function () {
    store.removeEventListener('doc', onDoc);
    store.removeEventListener('mode', onMode);
  });
  start();

  return {
    destroy: function () {
      S.destroyed = true;
      offs.forEach(function (f) { f(); });
      if (table) { table.destroy(); table = null; }
      el.innerHTML = '';
    },
    route: function (r) {
      if (!table || !r || r.view !== 'files') return;
      table.readUrl();
      table.setHighlight((r.query || {}).hl || null);
    },
    focus: function (sel) {
      const id = sel && sel.id;
      if (!id || !table) return;
      const row = tableHost.querySelector('tr[data-file="' + String(id).replace(/["\\]/g, '\\$&') + '"]');
      if (row && row.scrollIntoView) row.scrollIntoView({block: 'center'});
    },
    _table: function () { return table; },
  };
}
