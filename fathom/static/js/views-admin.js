// Admin views (§6.8, FR-UX-06/07, FR-IMP-10, FR-HIST, FR-USER-08): Imports, History, Builds,
// Settings. Every list is a shared DataTable (docs/ui-audit.md B.3 ADM, D9); the settings tab
// (`settings/<tab>`) and the history revision (`history/<rev>`) live in the URL (D1), and `?hl=<id>`
// highlights a row of the view's primary table.

import { h } from './dom.js';
import { canSee } from './router-core.js';
import { createTable } from './datatable.js';
import { staleBadge, reviewBadge, confirmScope } from './feedback.js';
import { openWizard } from './wizard.js';
import { slug, newId, deepClone } from './model-core.js';
import { suggestionControl, applyChoice } from './suggest-ui.js';

function msg(e) { return (e && e.message) || String(e); }
function fmtTime(s) {
  if (!s) return '';
  const d = new Date(s);
  return isNaN(d.getTime()) ? s : d.toLocaleString();
}
function fmtSize(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
}
function needApi(el, ctx) {
  if (ctx.api) return false;
  el.appendChild(h('div', { class: 'adm' }, h('div', { class: 'app-error-card' }, [h('h3', null, 'Needs the server'), h('div', null, 'This view talks to the Fathom server.')])));
  return true;
}
let fid = 0;
function fld(label, input) {
  if (!input.id) input.id = 'adm-f' + (++fid);
  return h('div', { class: 'field' }, [h('label', { for: input.id }, label), input]);
}
function canWrite(ctx) { return !(ctx.store && ctx.store.readOnly) && ctx.role !== 'viewer'; }
function query(ctx) { const r = ctx.route; return (r && r.query) || {}; }
function hlOf(ctx) { return query(ctx).hl || null; }
// The view's primary table mirrors q, sort, f.* and pg into the hash (replaceState).
function urlBinding(ctx) {
  return {
    get: function () { return query(ctx); },
    set: function (patch) { if (ctx.setParams) ctx.setParams(patch, { replace: true }); },
  };
}
function actions(cell) {
  return { key: 'actions', header: 'Actions', value: function () { return ''; }, cell: function (r) { return h('span', { class: 'adm-acts' }, cell(r)); }, sortable: false, searchable: false, csv: false };
}
function timeCol(key, header, get) {
  return { key: key, header: header, value: function (r) { return get(r) || ''; }, cell: function (r) { return fmtTime(get(r)); } };
}
function mono(text) { return h('span', { class: 'mono' }, text === undefined || text === null ? '' : String(text)); }
function findRow(t, id) {
  const trs = t.root.querySelectorAll('tr.dt-row');
  for (let i = 0; i < trs.length; i++) if (trs[i].getAttribute('data-id') === String(id)) return trs[i];
  return null;
}

// ------------------------------------------------------------ imports

export function mountImports(el, ctx) {
  if (needApi(el, ctx)) return { destroy: function () { el.innerHTML = ''; } };
  const store = ctx.store;
  const write = canWrite(ctx);
  const root = h('div', { class: 'adm adm-imports' });
  el.appendChild(root);
  const errTables = [];
  // discovery runs are started from the Discovery view, not uploaded here
  const importers = ((ctx.meta && ctx.meta.importers) || []).filter(function (imp) { return imp.mode !== 'discovery'; });

  function deviceSelect() {
    return h('select', { 'aria-label': 'Device' }, [h('option', { value: '' }, 'Auto-detect device')].concat((store.doc.devices || []).map(function (d) { return h('option', { value: d.id }, d.name || d.id); })));
  }
  function roomSelect() {
    const def = store.room && store.room !== '*' ? store.room : ((store.doc.settings && store.doc.settings.default_room) || '');
    return h('select', { 'aria-label': 'Room' }, (store.doc.rooms || []).map(function (r) { return h('option', { value: r.id, selected: r.id === def ? true : null }, r.name || r.id); }));
  }
  function refreshOverlay() {
    return ctx.api.overlay(ctx.project).then(function (o) { store.setOverlay(o); }, function () { /* optional */ });
  }

  function templateBox(imp) {
    const tpls = imp.templates || [];
    if (!tpls.length || !ctx.api.importTemplateUrl) return null;
    const links = tpls.map(function (t) {
      return h('a', { class: 'btn small', role: 'button', href: ctx.api.importTemplateUrl(ctx.project, imp.kind, t.name), download: 'fathom-' + t.name + '-template.csv',
        'data-template': t.name }, '\u2193 ' + (t.label || t.name) + ' template');
    });
    const guide = h('details', { class: 'imp-guide' }, [h('summary', null, 'Columns')].concat(tpls.map(function (t) {
      return h('div', null, [
        h('div', { class: 'imp-guide-title' }, t.label || t.name),
        h('dl', null, (t.columns || []).reduce(function (acc, c) {
          acc.push(h('dt', { class: 'mono' }, [c.key, c.required ? h('span', { class: 'imp-req', title: 'required' }, ' *') : null]));
          acc.push(h('dd', null, [c.help || '', (c.allowed || []).length ? h('div', { class: 'imp-allowed mono' }, c.allowed.join(' \u00b7 ')) : null]));
          return acc;
        }, [])),
      ]);
    })));
    return h('div', { class: 'imp-tpl' }, [
      h('div', { class: 'imp-tpl-text' }, 'Download a template, fill it in (Excel, Numbers, Sheets), save as CSV and upload it here. * = required.'),
      h('div', { class: 'row' }, links),
      guide,
    ]);
  }
  function errorTable(host, errors) {
    const rows = errors.map(function (e, i) { return { id: String(i), row: e.row, column: e.column || '', value: e.value, message: e.message || '' }; });
    const t = createTable(host, {
      key: 'imports.errors', scope: ctx.project, caption: 'Import problems', noun: { one: 'problem', many: 'problems' }, rows: rows, pageSize: 25,
      csvName: 'import-problems.csv',
      columns: [
        { key: 'row', header: 'Row', value: function (r) { return r.row; }, cell: function (r) { return mono(r.row); }, sticky: true },
        { key: 'column', header: 'Column', filterable: true, cell: function (r) { return mono(r.column); } },
        { key: 'value', header: 'Value', value: function (r) { return r.value === undefined || r.value === null ? '' : String(r.value); },
          cell: function (r) { return r.value === '' || r.value === undefined || r.value === null ? h('span', { class: 'muted' }, '(empty)') : mono(r.value); } },
        { key: 'message', header: 'Problem' },
      ],
    });
    errTables.push(t);
    return t;
  }
  function clearOut(out) {
    Array.prototype.forEach.call(out.querySelectorAll('.dt-root'), function (r) {
      for (let i = errTables.length - 1; i >= 0; i--) if (errTables[i].root === r) { errTables[i].destroy(); errTables.splice(i, 1); }
    });
    out.innerHTML = '';
  }
  function liveSummary(out, s) {
    const chips = Object.keys(s || {}).filter(function (k) { return k !== 'kind' && k !== 'notes' && k !== 'files'; }).map(function (k) {
      const v = s[k];
      const txt = Array.isArray(v) ? (v.length > 4 ? v.length + '' : v.join(', ') || '\u2014') : (typeof v === 'object' && v ? Object.keys(v).length + '' : String(v));
      return h('span', { class: 'chip' }, k.replace(/_/g, ' ') + ': ' + txt);
    });
    out.appendChild(h('div', { class: 'row imp-sum' }, chips));
    (s.notes || []).forEach(function (n) { out.appendChild(h('div', { class: 'imp-warn' }, n)); });
  }

  function card(imp) {
    const head = [h('h4', null, imp.label || imp.kind), h('div', { class: 'help' }, imp.help || ''), templateBox(imp)];
    if (!write) return h('div', { class: 'adm-card' + ((imp.templates || []).length ? ' has-tpl' : ''), 'data-importer': imp.kind }, head);
    const files = h('input', { type: 'file', multiple: true, accept: (imp.accepts || []).join(',') || null, 'aria-label': 'Files for ' + imp.label });
    if (imp.folder) { files.setAttribute('webkitdirectory', ''); }
    const dev = deviceSelect();
    const room = roomSelect();
    const out = h('div', { class: 'imp-out hidden', 'aria-live': 'polite' });
    const go = h('button', { type: 'button', class: 'primary small' }, imp.mode === 'oneshot' ? 'Preview' : 'Import');
    let el = null;
    go.addEventListener('click', function () {
      const fs = Array.prototype.slice.call(files.files || []);
      if (!fs.length) { ctx.toast('Choose a file first', 'warn'); return; }
      go.disabled = true;
      const params = { kind: imp.kind, device: dev.value, room: room.value };
      const flush = ctx.flush ? ctx.flush() : Promise.resolve();
      if (imp.mode === 'oneshot') {
        flush.then(function () { return ctx.api.importPreview(ctx.project, fs, params); }).then(function (r) {
          go.disabled = false;
          out.classList.remove('hidden');
          clearOut(out);
          const s = r.summary || {};
          const errors = r.errors || [];
          const errText = {};
          errors.forEach(function (e) { errText['row ' + e.row + (e.column ? ', ' + e.column : '') + ': ' + e.message] = true; });
          el.classList.toggle('wide', errors.length > 0);
          out.appendChild(h('div', { class: 'row imp-sum' }, [
            h('span', { class: 'chip' }, 'create ' + (s.create || 0)), h('span', { class: 'chip' }, 'update ' + (s.update || 0)),
            h('span', { class: 'chip' }, 'skip ' + (s.skip || 0)), errors.length ? h('span', { class: 'chip imp-chip-err' }, errors.length + (errors.length === 1 ? ' problem' : ' problems')) : null,
          ]));
          if (errors.length) {
            const rows = {};
            errors.forEach(function (e) { rows[e.row] = true; });
            const nRows = Object.keys(rows).length;
            out.appendChild(h('div', { class: 'imp-err-head' }, nRows + (nRows === 1 ? ' row has' : ' rows have') + ' problems and will be skipped. Fix them in the file and preview again, or apply the rest.'));
            const host = h('div', { class: 'adm-imp-errors' });
            out.appendChild(host);
            errorTable(host, errors);
          }
          (r.warnings || []).filter(function (w) { return !errText[w]; }).forEach(function (w) { out.appendChild(h('div', { class: 'imp-warn' }, w)); });
          const controls = {};
          const sugg = r.suggestions || {};
          const devOps = (r.ops || []).filter(function (op) { return op.coll === 'devices' && op.op === 'put' && op.value && sugg[op.id]; });
          if (devOps.length) {
            out.appendChild(h('div', { class: 'imp-sugg' }, [h('div', { class: 'muted', style: { fontSize: '12px' } }, 'The library knows gear like these rows. Accept a model to create the device from its template (kind, model, ports), or keep the row as typed.')]
              .concat(devOps.map(function (op) {
                controls[op.id] = suggestionControl(sugg[op.id], { label: op.value.name || op.id, pickTemplate: ctx.pickTemplate ? function () { return ctx.pickTemplate({}); } : null });
                return h('div', { class: 'imp-sugg-row', 'data-device': op.id }, [h('div', { class: 'imp-sugg-dev' }, [op.value.name || op.id, h('div', { class: 'muted', style: { fontWeight: 400 } }, [op.value.manufacturer, op.value.model].filter(Boolean).join(' '))]), controls[op.id].el]);
              }))));
          }
          if ((r.ops || []).length) {
            const apply = h('button', { type: 'button', class: 'primary small adm-apply', onclick: function () {
              apply.disabled = true;
              const ops = deepClone(r.ops);
              Promise.all(ops.map(function (op) {
                const c = controls[op.id];
                return c && op.coll === 'devices' && op.op === 'put' ? applyChoice(ctx, c, op.value) : Promise.resolve(null);
              })).then(function () {
                apply.disabled = false;
                if (r.base_revision !== undefined && r.base_revision !== store.revision) ctx.toast('The project changed since the preview; applying on the latest revision.', 'warn');
                ctx.commit(ops, 'Import ' + (fs[0].name || imp.label));
                ctx.toast('Applied ' + ops.length + ' changes', 'ok');
                out.classList.add('hidden');
                clearOut(out);
                el.classList.remove('wide');
              }, function (e) { apply.disabled = false; ctx.toast(msg(e), 'err'); });
            } }, 'Apply ' + r.ops.length + ' changes');
            out.appendChild(apply);
          } else {
            out.appendChild(h('div', { class: 'muted', style: { marginTop: '6px' } }, 'Nothing to apply.'));
          }
        }, function (e) { go.disabled = false; ctx.toast(msg(e), 'err'); });
        return;
      }
      flush.then(function () { return ctx.api.upload(ctx.project, 'imports', fs, params); }).then(function (r) {
        go.disabled = false;
        out.classList.remove('hidden');
        clearOut(out);
        liveSummary(out, (r && r.summary) || {});
        ctx.toast('Imported ' + imp.label, 'ok');
        return ctx.reload().then(refreshOverlay).then(drawRegistered);
      }, function (e) {
        go.disabled = false;
        out.classList.remove('hidden');
        clearOut(out);
        out.appendChild(h('div', { class: 'imp-err-head' }, msg(e)));
        ctx.toast(msg(e), 'err');
      });
    });
    el = h('div', { class: 'adm-card' + ((imp.templates || []).length ? ' has-tpl' : ''), 'data-importer': imp.kind }, head.concat([
      files,
      h('div', { class: 'row adm-card-opts', style: { marginTop: '6px' } }, [imp.mode === 'oneshot' ? null : dev, room]),
      h('div', { class: 'row', style: { marginTop: '6px' } }, [go, h('span', { class: 'muted', style: { fontSize: '11px' } }, imp.mode === 'oneshot' ? 'one-shot: preview, then apply' : 'kept and re-parsed on every build')]),
      out,
    ]));
    return el;
  }

  // registered imports
  const regHost = h('div', { class: 'adm-reg' });
  const inspectBox = h('div', { class: 'adm-pre adm-inspect hidden', 'aria-live': 'polite' });
  const regTable = createTable(regHost, {
    key: 'imports.registered', scope: ctx.project, caption: 'Registered imports', noun: { one: 'import', many: 'imports' },
    url: urlBinding(ctx), highlight: hlOf(ctx), csvName: 'imports.csv',
    empty: 'No registered imports. Import a console, Dante or CSV export above to add one.',
    columns: [
      { key: 'kind', header: 'Kind', filterable: true, sticky: true },
      { key: 'path', header: 'Path', cell: function (im) { return mono(im.path); } },
      { key: 'device', header: 'Device', value: function (im) { return im.device || ''; }, hideOnMobile: true },
      { key: 'room', header: 'Room', value: function (im) { return im.room || ''; }, filterable: true, hideOnMobile: true },
      actions(function (im) {
        return [
          h('button', { type: 'button', class: 'small', onclick: function () {
            ctx.api.inspectImport(ctx.project, im.id).then(function (r) {
              inspectBox.classList.remove('hidden');
              inspectBox.textContent = im.path + '\n' + JSON.stringify(r.summary || r, null, 2);
            }, function (e) { ctx.toast(msg(e), 'err'); });
          } }, 'Inspect'),
          write ? h('button', { type: 'button', class: 'small danger', onclick: function () {
            ctx.confirm('Remove import ' + im.path + '? Also delete its files?', { danger: true, ok: 'Remove + delete files', cancel: 'Cancel' }).then(function (y) {
              if (!y) return;
              ctx.api.deleteImport(ctx.project, im.id, true).then(function () { return ctx.reload(); }).then(refreshOverlay).then(drawRegistered, function (e) { ctx.toast(msg(e), 'err'); });
            });
          } }, 'Remove') : null,
        ];
      }),
    ],
  });
  function drawRegistered() { regTable.setRows(store.doc.imports || []); }

  // overlay
  const ovlChips = h('div', { class: 'row adm-ovl-chips' });
  const ovlReview = h('span', { class: 'adm-ovl-review' });
  const ovlHost = h('div', { class: 'adm-ovl' });
  const ovlNotes = h('div', { class: 'adm-ovl-notes' });
  const stale = staleBadge({
    fetchedAt: function () { return ctx.overlayInfo ? ctx.overlayInfo().fetchedAt : null; },
    fetchedRev: function () { return ctx.overlayInfo ? ctx.overlayInfo().revision : null; },
    currentRev: function () { return store.revision; },
    onRefresh: function () { return Promise.resolve(ctx.refreshOverlay ? ctx.refreshOverlay() : refreshOverlay()); },
  });
  let ovlCache = {};
  let ovlSugg = {};
  function ovlEntry(d) {
    if (ovlCache[d.id]) return ovlCache[d.id];
    const sub = [d.manufacturer, d.model].filter(Boolean).join(' ') || d.sub || '';
    const control = suggestionControl(ovlSugg[d.id] || [], { label: d.name || d.id, readOnly: !write, pickTemplate: ctx.pickTemplate ? function () { return ctx.pickTemplate({}); } : null });
    const promote = write ? h('button', { type: 'button', class: 'small primary', onclick: function () {
      const dev = deepClone(d);
      delete dev.auto;
      delete dev.source;
      (dev.ports || []).forEach(function (p) { delete p.auto; });
      if ((store.doc.devices || []).some(function (x) { return x.id === dev.id; })) { ctx.toast(dev.id + ' already exists', 'warn'); return; }
      promote.disabled = true;
      applyChoice(ctx, control, dev).then(function () {
        promote.disabled = false;
        ctx.commit([{ op: 'put', coll: 'devices', id: dev.id, value: dev }], 'Promote ' + (d.name || d.id));
        ctx.toast('Promoted ' + (d.name || d.id) + (dev.template ? ' as ' + ((dev.manufacturer ? dev.manufacturer + ' ' : '') + (dev.model || dev.template)) : ' into the model'), 'ok');
      }, function (e) { promote.disabled = false; ctx.toast(msg(e), 'err'); });
    } }, 'Promote') : null;
    const e = {
      cell: h('div', { class: 'adm-ovl-dev' }, [h('div', { class: 'disc-name' }, d.name || d.id), sub ? h('div', { class: 'muted' }, sub) : null, control.el]),
      act: h('span', { class: 'disc-actions' }, promote),
    };
    ovlCache[d.id] = e;
    return e;
  }
  const ovlTable = createTable(ovlHost, {
    key: 'imports.overlay', scope: ctx.project, caption: 'Import devices to promote', noun: { one: 'device', many: 'devices' }, cards: true,
    csvName: 'import-devices.csv',
    rowClass: function () { return 'ovl-row'; },
    rowAttrs: function (d) { return { 'data-device': d.id }; },
    empty: 'Nothing to promote. Devices an import reports that the model does not have yet show up here.',
    columns: [
      { key: 'device', header: 'Device', value: function (d) { return [d.name || d.id, d.manufacturer, d.model].filter(Boolean).join(' '); }, csv: function (d) { return d.name || d.id; },
        cell: function (d) { return ovlEntry(d).cell; }, sticky: true },
      { key: 'kind', header: 'Kind', value: function (d) { return d.kind || ''; }, filterable: true },
      { key: 'source', header: 'From', value: function (d) { return d.source || ''; }, filterable: true, hideOnMobile: true },
      { key: 'actions', header: 'Actions', value: function () { return ''; }, cell: function (d) { return ovlEntry(d).act; }, sortable: false, searchable: false, csv: false },
    ],
  });
  function firstSuggestion() {
    const autos = ((store.overlay && store.overlay.devices) || []).filter(function (d) { return d.auto && (ovlSugg[d.id] || []).length; });
    return autos[0] || null;
  }
  function drawOverlay() {
    const o = store.overlay;
    ovlChips.innerHTML = '';
    ovlNotes.innerHTML = '';
    ovlReview.innerHTML = '';
    ovlCache = {};
    if (!o) {
      ovlChips.appendChild(h('span', { class: 'muted' }, 'Overlay not loaded yet.'));
      ovlTable.setLoading(true);
      stale.refresh();
      return;
    }
    ovlSugg = o.suggestions || {};
    const count = function (x) { return Array.isArray(x) ? x.length : (x ? Object.keys(x).length : 0); };
    [count(o.devices) + ' import devices', count(o.routes) + ' routes', count(o.port_labels) + ' devices with labels', count(o.interfaces) + ' with IPs', count(o.dmx) + ' DMX'].forEach(function (t) {
      ovlChips.appendChild(h('span', { class: 'chip' }, t));
    });
    const autos = (o.devices || []).filter(function (d) { return d.auto; });
    ovlTable.setRows(autos);
    const nSugg = autos.filter(function (d) { return (ovlSugg[d.id] || []).length; }).length;
    const badge = reviewBadge({ count: nSugg, label: nSugg === 1 ? 'model suggestion' : 'model suggestions', title: 'Jump to the first suggested model', onClick: function () {
      const d = firstSuggestion();
      if (!d) return;
      ovlTable.setHighlight(d.id);
      setTimeout(function () {
        const tr = findRow(ovlTable, d.id);
        const ms = tr ? tr.querySelector('.ms-suggest') : root.querySelector('.ms-suggest');
        if (!ms) return;
        if (ms.scrollIntoView) ms.scrollIntoView({ block: 'center' });
        const sel = ms.querySelector('select');
        if (sel) sel.focus();
      }, 30);
    } });
    if (badge) ovlReview.appendChild(badge);
    if (autos.length) ovlNotes.appendChild(h('div', { class: 'muted', style: { fontSize: '12px', marginTop: '4px' } }, 'Suggested models come from the library, matched on what the import reported (manufacturer, model, device name). Accepting one sets kind, model and ports the way Add gear does; "No model" keeps the device as imported.'));
    (o.notes || []).slice(0, 20).forEach(function (n) { ovlNotes.appendChild(h('div', { class: 'muted', style: { fontSize: '12px' } }, n)); });
    stale.refresh();
  }

  root.appendChild(h('h2', null, 'Imports'));
  root.appendChild(h('p', { class: 'muted' }, 'Console, Dante, Waves, Eos, MagicQ, Videohub and CSV exports. Imports never overwrite what you typed: they fill an overlay that is rebuilt every time.'));
  root.appendChild(h('h3', null, write ? 'Add an import' : 'Import templates'));
  const cards = h('div', { class: 'adm-cards' });
  if (!importers.length) cards.appendChild(h('div', { class: 'muted' }, 'The server did not list any importers.'));
  importers.forEach(function (imp) { cards.appendChild(card(imp)); });
  root.appendChild(cards);
  root.appendChild(h('h3', null, 'Registered imports'));
  root.appendChild(regHost);
  root.appendChild(inspectBox);
  root.appendChild(h('div', { class: 'adm-sec-head' }, [h('h3', null, 'Overlay'), stale, ovlReview]));
  root.appendChild(ovlChips);
  root.appendChild(ovlHost);
  root.appendChild(ovlNotes);
  drawRegistered();
  drawOverlay();
  function onDoc(e) { if ((e.detail.touched || []).some(function (r) { return r.indexOf('imports/') === 0; }) || e.detail.source === 'load') drawRegistered(); }
  function onRev() { stale.refresh(); }
  store.addEventListener('doc', onDoc);
  store.addEventListener('overlay', drawOverlay);
  store.addEventListener('revision', onRev);
  return {
    route: function (r) {
      regTable.readUrl();
      regTable.setHighlight((r && r.query && r.query.hl) || null);
    },
    destroy: function () {
      store.removeEventListener('doc', onDoc);
      store.removeEventListener('overlay', drawOverlay);
      store.removeEventListener('revision', onRev);
      stale.destroy();
      errTables.forEach(function (t) { t.destroy(); });
      regTable.destroy();
      ovlTable.destroy();
      el.innerHTML = '';
    },
  };
}

// ------------------------------------------------------------ history

export function mountHistory(el, ctx) {
  if (needApi(el, ctx)) return { destroy: function () { el.innerHTML = ''; } };
  const store = ctx.store;
  const PAGE = 100;
  const root = h('div', { class: 'adm adm-history' });
  el.appendChild(root);
  const diffBox = h('div', { class: 'adm-pre adm-diff hidden', 'aria-live': 'polite' });
  const more = h('button', { type: 'button', class: 'small adm-more', hidden: true }, 'Load older');
  const host = h('div');
  let revs = [];
  let oldest = null;
  let hasMore = false;
  let current = String((ctx.route && ctx.route.id) || '');
  let destroyed = false;
  root.appendChild(h('h2', null, 'History'));
  root.appendChild(h('p', { class: 'muted' }, 'Every save is a revision. Pick a revision to compare it with now, view it read-only, or restore it as a new revision.'));
  root.appendChild(diffBox);
  root.appendChild(host);
  const canRestore = function () { return ctx.role !== 'viewer' && (!store.readOnly || (ctx.isTimeTravel && ctx.isTimeTravel())); };
  const table = createTable(host, {
    key: 'history', scope: ctx.project, caption: 'Revisions', noun: { one: 'revision', many: 'revisions' },
    url: urlBinding(ctx), highlight: current || hlOf(ctx), csvName: 'history.csv', actions: [more],
    rowId: function (r) { return String(r.revision); },
    empty: 'No revisions yet. Every save creates one.',
    onRow: function (r) { pick(r.revision); },
    columns: [
      { key: 'revision', header: 'Rev', value: function (r) { return r.revision; }, cell: function (r) { return mono('r' + r.revision); }, sticky: true },
      timeCol('time', 'Time', function (r) { return r.time; }),
      { key: 'author', header: 'User', value: function (r) { return r.author || ''; }, filterable: true },
      { key: 'source', header: 'Source', value: function (r) { return r.source || ''; }, filterable: true, hidden: true },
      { key: 'summary', header: 'Summary', value: function (r) { return r.summary || ''; } },
      { key: 'ops', header: 'Ops', align: 'right', hideOnMobile: true, value: function (r) { return (r.touched || []).length || r.ops || 0; },
        cell: function (r) { return h('span', { title: (r.touched || []).join('\n') }, String((r.touched || []).length || r.ops || '')); } },
      actions(function (r) {
        return [
          h('button', { type: 'button', class: 'small', onclick: function () { if (ctx.timeTravel) ctx.timeTravel(r.revision); } }, 'View'),
          h('button', { type: 'button', class: 'small', onclick: function () { pick(r.revision); } }, 'Diff'),
          canRestore() ? h('button', { type: 'button', class: 'small', onclick: function () { if (ctx.restoreRevision) ctx.restoreRevision(r.revision); } }, 'Restore') : null,
        ];
      }),
    ],
  });
  // history/<rev> highlights the revision and shows its diff against now (D1: not time travel).
  function pick(rev) {
    const hash = ctx.navigateRoute ? ctx.navigateRoute({ id: String(rev), query: query(ctx) }) : '';
    if (!hash) apply(String(rev));
  }
  function showDiff(rev) {
    if (!rev) { diffBox.classList.add('hidden'); return; }
    const n = Number(rev);
    diffBox.classList.remove('hidden');
    if (n === store.revision) { diffBox.textContent = 'r' + n + ' is the current revision.'; return; }
    diffBox.textContent = 'Comparing r' + n + ' with r' + store.revision + '\u2026';
    ctx.api.historyDiff(ctx.project, n, store.revision).then(function (d) {
      if (destroyed || current !== rev) return;
      diffBox.textContent = 'r' + n + ' vs r' + store.revision + '\nadded: ' + (d.added || []).join(', ') + '\nremoved: ' + (d.removed || []).join(', ') + '\nchanged: ' + (d.changed || []).join(', ');
    }, function (e) { if (current === rev) diffBox.textContent = 'r' + n + ': ' + msg(e); });
  }
  function ensureLoaded(n) {
    if (!n || revs.some(function (r) { return r.revision === n; }) || !hasMore || oldest === null || oldest <= n) return Promise.resolve();
    return load(oldest).then(function () { return ensureLoaded(n); });
  }
  function apply(rev) {
    current = rev || '';
    table.setHighlight(current || null);
    if (!current) { diffBox.classList.add('hidden'); return; }
    ensureLoaded(Number(current)).then(function () { showDiff(current); });
  }
  function load(before) {
    if (!before) table.setLoading(!revs.length);
    return ctx.api.history(ctx.project, { limit: PAGE, before: before }).then(function (r) {
      if (destroyed) return;
      const got = (r && r.revisions) || [];
      revs = before ? revs.concat(got) : got;
      if (got.length) oldest = got[got.length - 1].revision;
      hasMore = got.length >= PAGE && oldest > 1;
      more.hidden = !hasMore;
      table.setRows(revs);
    }, function (e) { if (!destroyed) table.setError(e, function () { load(before); }); });
  }
  more.addEventListener('click', function () { load(oldest); });
  function onRev() { load(); }
  store.addEventListener('revision', onRev);
  load().then(function () { if (current) apply(current); });
  return {
    route: function (r) {
      table.readUrl();
      const id = String((r && r.id) || '');
      if (id !== current) apply(id);
      else if (!id) table.setHighlight((r && r.query && r.query.hl) || null);
    },
    destroy: function () { destroyed = true; store.removeEventListener('revision', onRev); table.destroy(); el.innerHTML = ''; },
  };
}

// ------------------------------------------------------------ builds

function outputKinds(files) {
  const n = {};
  (files || []).forEach(function (f) {
    const m = /\.([A-Za-z0-9]+)$/.exec(f);
    const k = m ? m[1].toLowerCase() : 'other';
    n[k] = (n[k] || 0) + 1;
  });
  return Object.keys(n).sort().map(function (k) { return k.toUpperCase() + ' ' + n[k]; }).join(' \u00b7 ');
}

export function mountBuilds(el, ctx) {
  if (needApi(el, ctx)) return { destroy: function () { el.innerHTML = ''; } };
  const store = ctx.store;
  const write = canWrite(ctx);
  const root = h('div', { class: 'adm adm-builds' });
  el.appendChild(root);
  const caps = (ctx.meta && ctx.meta.capabilities) || {};
  let destroyed = false;
  root.appendChild(h('h2', null, 'Builds'));
  root.appendChild(h('p', { class: 'muted' }, 'A build is a folder you can hand over: per-room maps, device pages, patch tables, cable and IP schedules, rack and floor-plan SVGs, labels, BOM and a zip of it all.'));
  if (write) {
    const state = h('select', { 'aria-label': 'State' }, [['all', 'Everything current'], ['as_built', 'As built (installed only)'], ['planned', 'Planned + installed']].map(function (o) { return h('option', { value: o[0] }, o[1]); }));
    const pdf = h('input', { type: 'checkbox', id: 'bld-pdf', disabled: caps.chrome ? null : true });
    const png = h('input', { type: 'checkbox', id: 'bld-png', disabled: caps.chrome ? null : true });
    const disc = h('input', { type: 'checkbox', id: 'bld-disc' });
    disc.checked = true;
    const rooms = h('div', { class: 'row' }, (store.doc.rooms || []).map(function (r) {
      const b = h('input', { type: 'checkbox', 'data-room': r.id, id: 'bld-room-' + r.id });
      b.checked = true;
      return h('label', { class: 'row', for: b.id }, [b, r.name || r.id]);
    }));
    const go = h('button', { type: 'button', class: 'primary', id: 'bld-go' }, 'Build package');
    go.addEventListener('click', function () {
      const sel = Array.prototype.filter.call(rooms.querySelectorAll('input[data-room]'), function (b) { return b.checked; }).map(function (b) { return b.getAttribute('data-room'); });
      go.disabled = true;
      go.textContent = 'Building\u2026';
      const flush = ctx.flush ? ctx.flush() : Promise.resolve();
      flush.then(function () { return ctx.api.build(ctx.project, { state: state.value, pdf: pdf.checked, png: png.checked, discovery: disc.checked, rooms: sel.length === (store.doc.rooms || []).length ? null : sel }); }).then(function (r) {
        ctx.toast('Built ' + r.build + ' (' + (r.files || []).length + ' files)', 'ok');
        return load().then(function () { table.setHighlight(r.build); });
      }, function (e) { ctx.toast(msg(e), 'err'); }).then(function () { go.disabled = false; go.textContent = 'Build package'; });
    });
    root.appendChild(h('div', { class: 'adm-card adm-build-form' }, [
      fld('State', state),
      h('div', { class: 'field' }, [h('label', null, 'Rooms'), rooms]),
      h('div', { class: 'row' }, [h('label', { class: 'row', for: 'bld-pdf' }, [pdf, 'PDF']), h('label', { class: 'row', for: 'bld-png' }, [png, 'PNG']), caps.chrome ? null : h('span', { class: 'muted' }, 'PDF/PNG need Chrome on the server.')]),
      h('div', { class: 'field' }, [h('label', null, 'Report sections'), h('label', { class: 'row', for: 'bld-disc' }, [disc, 'Discovered connections (latest completed discovery run and promoted discovered cables)'])]),
      h('div', { class: 'row', style: { marginTop: '8px' } }, go),
    ]));
  }
  root.appendChild(h('h3', null, 'Previous builds'));
  const host = h('div');
  root.appendChild(host);
  function base(b) { return (ctx.appRoot || '') + 'builds/' + encodeURIComponent(ctx.project) + '/' + encodeURIComponent(b.name) + '/'; }
  const table = createTable(host, {
    key: 'builds', scope: ctx.project, caption: 'Builds', noun: { one: 'build', many: 'builds' },
    url: urlBinding(ctx), highlight: hlOf(ctx), csvName: 'builds.csv',
    rowId: function (b) { return b.name; },
    empty: write ? 'No builds yet. Build package creates the PDF/HTML pack.' : 'No builds yet.',
    columns: [
      { key: 'name', header: 'Run', cell: function (b) { return mono(b.name); }, sticky: true },
      timeCol('created', 'Time', function (b) { return b.created; }),
      { key: 'outputs', header: 'Outputs', value: function (b) { return outputKinds(b.files); }, csv: function (b) { return outputKinds(b.files); },
        cell: function (b) {
          const zip = (b.files || []).filter(function (f) { return /\.zip$/.test(f); })[0];
          return h('span', { class: 'adm-acts' }, [
            h('a', { class: 'chip', href: base(b) + 'index.html', target: '_blank', rel: 'noopener' }, 'Open'),
            zip ? h('a', { class: 'chip', href: base(b) + zip, download: zip }, 'Zip') : null,
            h('span', { class: 'muted adm-kinds' }, outputKinds(b.files)),
          ]);
        } },
      { key: 'files', header: 'Files', align: 'right', hideOnMobile: true, value: function (b) { return (b.files || []).length; } },
      write ? actions(function (b) {
        return h('button', { type: 'button', class: 'small danger', onclick: function () {
          confirmScope(ctx, { verb: 'Delete', noun: 'build ' + b.name, danger: true, detail: 'Its ' + (b.files || []).length + ' files are removed from the server.' }).then(function (y) {
            if (y) ctx.api.deleteBuild(ctx.project, b.name).then(load, function (e) { ctx.toast(msg(e), 'err'); });
          });
        } }, 'Delete');
      }) : null,
    ].filter(Boolean),
  });
  function load() {
    return ctx.api.builds(ctx.project).then(function (r) {
      if (!destroyed) table.setRows(((r && r.builds) || []).map(function (b) { return Object.assign({ id: b.name }, b); }));
    }, function (e) { if (!destroyed) table.setError(e, load); });
  }
  table.setLoading(true);
  load();
  return {
    route: function (r) { table.readUrl(); table.setHighlight((r && r.query && r.query.hl) || null); },
    destroy: function () { destroyed = true; table.destroy(); el.innerHTML = ''; },
  };
}

// ------------------------------------------------------------ settings

function optionPairs(c) {
  const list = typeof c.options === 'function' ? c.options() : c.options;
  return (list || []).map(function (o) { return Array.isArray(o) ? o : [o, o]; });
}
function displayValue(c, ent) {
  const cur = ent[c.key];
  if (c.type === 'check') return cur ? 'yes' : '';
  if (cur === undefined || cur === null) return '';
  if (c.options) {
    const p = optionPairs(c).filter(function (x) { return String(x[0]) === String(cur); })[0];
    return p ? String(p[1]) : String(cur);
  }
  return String(cur);
}

// An editable collection (venues, rooms, systems, locations, networks): each cell is its own
// inline editor committing one merge op, as before; viewers get plain text.
function crudTable(ctx, coll, cols, opts) {
  opts = opts || {};
  const store = ctx.store;
  const write = canWrite(ctx);
  const noun = coll.replace(/s$/, '');
  const wrap = h('div', { class: 'adm-crud', 'data-coll': coll });
  const host = h('div');
  wrap.appendChild(host);
  function list() { return (store.doc[coll] || []).filter(opts.filter || function () { return true; }); }
  function editor(c, ent) {
    const cur = ent[c.key];
    let input;
    if (c.options) {
      input = h('select', { 'aria-label': c.label + ' of ' + (ent.name || ent.id) }, (c.empty !== undefined ? [h('option', { value: '' }, c.empty)] : []).concat(optionPairs(c).map(function (v) { return h('option', { value: v[0], selected: String(cur) === String(v[0]) ? true : null }, v[1]); })));
    } else if (c.type === 'check') {
      input = h('input', { type: 'checkbox', 'aria-label': c.label + ' of ' + (ent.name || ent.id) });
      input.checked = !!cur;
    } else {
      input = h('input', { value: cur === undefined || cur === null ? '' : String(cur), inputmode: c.number ? 'numeric' : null, 'aria-label': c.label + ' of ' + (ent.name || ent.id) });
    }
    input.addEventListener('change', function () {
      let v = c.type === 'check' ? (input.checked ? true : null) : (input.value.trim() === '' ? null : input.value.trim());
      if (c.number && v !== null) v = Number(v);
      if (c.parse && v !== null) v = c.parse(v);
      if (c.required && v === null) { ctx.toast(c.label + ' is required', 'warn'); refresh(); return; }
      const value = {};
      value[c.key] = v;
      ctx.commit([{ op: 'merge', coll: coll, id: ent.id, value: value }], 'Edit ' + noun + ' ' + (ent.name || ent.id));
    });
    return c.type === 'check' ? h('label', { class: 'chk' }, input) : input;
  }
  const columns = [{ key: 'id', header: 'Id', cell: function (ent) { return mono(ent.id); }, sticky: true }].concat(cols.map(function (c) {
    return {
      key: c.key, header: c.label, filterable: !!c.options || c.type === 'check', hideOnMobile: !!c.hideOnMobile,
      align: c.number ? 'right' : 'left',
      value: function (ent) { return c.number && typeof ent[c.key] === 'number' ? ent[c.key] : displayValue(c, ent); },
      cell: write ? function (ent) { return editor(c, ent); } : null,
    };
  }));
  if (write) {
    columns.push(actions(function (ent) {
      return h('button', { type: 'button', class: 'small danger', 'aria-label': 'Delete ' + (ent.name || ent.id), onclick: function () {
        const blockers = opts.blockers ? opts.blockers(ent) : '';
        if (blockers) { ctx.toast(blockers, 'warn'); return; }
        ctx.confirm('Delete ' + (ent.name || ent.id) + '?', { danger: true }).then(function (y) { if (y) ctx.commit([{ op: 'del', coll: coll, id: ent.id }], 'Delete ' + (ent.name || ent.id)); });
      } }, '\u00d7');
    }));
  }
  const dt = createTable(host, {
    key: 'settings.' + (opts.key || coll), scope: ctx.project, caption: opts.caption || coll, noun: { one: noun, many: coll },
    url: opts.primary ? urlBinding(ctx) : null, highlight: opts.primary ? hlOf(ctx) : null, csvName: coll + '.csv',
    rows: list(), columns: columns, empty: opts.empty || 'None yet.',
  });
  if (write && opts.create) {
    const name = h('input', { placeholder: 'Name', 'aria-label': 'New ' + noun + ' name' });
    const add = h('button', { type: 'button', class: 'small', onclick: function () {
      const n = name.value.trim();
      if (!n) { name.focus(); return; }
      const ent = opts.create(n);
      if (!ent) return;
      ctx.commit([{ op: 'put', coll: coll, id: ent.id, value: ent }], 'Add ' + noun + ' ' + n);
      name.value = '';
      refresh();
      dt.setHighlight(ent.id);
    } }, 'Add ' + noun);
    name.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); add.click(); } });
    wrap.appendChild(h('div', { class: 'row adm-addrow' }, [name, add]));
  }
  function refresh() { dt.setRows(list()); }
  return { el: wrap, dt: dt, refresh: refresh };
}

const SETTINGS_TABS = [
  ['project', 'Project'], ['rooms', 'Venues & rooms'], ['systems', 'Systems'], ['locations', 'Locations'], ['networks', 'Networks'],
  ['templates', 'Templates'], ['users', 'Users'], ['backups', 'Backups'], ['sharing', 'Sharing'], ['offline', 'Offline'],
];

function isoIn(days) {
  return new Date(Date.now() + days * 864e5).toISOString().replace(/\.\d{3}Z$/, 'Z');
}
function endOfDay(date) {
  const d = new Date(date + 'T23:59:59');
  return isNaN(d.getTime()) ? '' : d.toISOString().replace(/\.\d{3}Z$/, 'Z');
}
const EXPIRY = [['never', 'Never'], ['1', '1 day'], ['7', '7 days'], ['30', '30 days'], ['90', '90 days'], ['date', 'On a date\u2026']];

// "New share link" wizard: scope, expiry, review, then the link (copyable) and its QR sheet.
function shareWizard(ctx, onCreated) {
  let created = null;
  function expiresOf(data) {
    if (data.expiry === 'never') return '';
    if (data.expiry === 'date') return endOfDay(data.date);
    return isoIn(Number(data.expiry) || 0);
  }
  function scopeText(s) { return s === 'sop' ? 'procedures (SOP pages) only' : 'the whole project (maps, patch tables, device pages, procedures)'; }
  function expiryText(data) {
    if (data.expiry === 'never') return 'never expires';
    if (data.expiry === 'date') return 'expires at the end of ' + data.date;
    return 'expires in ' + (EXPIRY.filter(function (x) { return x[0] === data.expiry; })[0] || ['', data.expiry + ' days'])[1];
  }
  function shareUrl(r) {
    const base = ctx.appRoot || location.href;
    try { return new URL(r.url || ('s/' + r.share.token + '/'), base).href; } catch (e) { return r.url || ''; }
  }
  function decorate(r) {
    const box = document.querySelector('.wz[data-wizard=share] .wz-result');
    if (!box || !r) return;
    const url = shareUrl(r);
    const input = h('input', { class: 'adm-share-url mono', readonly: true, value: url, 'aria-label': 'Share link' });
    input.addEventListener('focus', function () { input.select(); });
    const copy = h('button', { type: 'button', class: 'small', onclick: function () {
      if (navigator.clipboard) navigator.clipboard.writeText(url).then(function () { ctx.toast('Link copied', 'ok'); }, function () { input.select(); });
      else input.select();
    } }, 'Copy');
    const token = r.share && r.share.token;
    box.appendChild(h('div', { class: 'adm-share-out' }, [
      h('div', { class: 'row adm-share-row' }, [input, copy]),
      h('div', { class: 'row' }, [
        h('a', { class: 'chip', href: url, target: '_blank', rel: 'noopener' }, 'Open link'),
        token && ctx.api.pagesQrSheetUrl ? h('a', { class: 'chip adm-share-qr', href: ctx.api.pagesQrSheetUrl(ctx.project, { share: token }), target: '_blank', rel: 'noopener' }, 'QR sheet') : null,
      ]),
    ]));
  }
  return openWizard(ctx, {
    key: 'share', title: 'New share link', submitLabel: 'Create link',
    data: { label: '', scope: 'all', expiry: 'never', date: '' },
    steps: [
      { key: 'scope', label: 'Scope', render: function (body, data) {
        const label = h('input', { name: 'label', value: data.label, placeholder: 'e.g. Sunday volunteers', autocomplete: 'off', id: 'adm-share-label' });
        label.addEventListener('input', function () { data.label = label.value; });
        const opts = [['all', 'Whole project', 'Maps, patch tables, device pages and procedures, read-only.'], ['sop', 'Procedures only', 'SOP pages and the files they embed; good for QR labels on racks.']];
        const radios = opts.map(function (o) {
          const r = h('input', { type: 'radio', name: 'scope', value: o[0], checked: data.scope === o[0] ? true : null });
          r.addEventListener('change', function () { if (r.checked) data.scope = o[0]; });
          return h('label', { class: 'adm-radio' }, [r, h('span', null, [h('strong', null, o[1]), h('span', { class: 'muted' }, ' \u2014 ' + o[2])])]);
        });
        body.appendChild(h('div', { class: 'wz-field' }, [h('label', { class: 'wz-label', for: 'adm-share-label' }, 'Label'), label]));
        body.appendChild(h('fieldset', { class: 'adm-fieldset' }, [h('legend', null, 'What the link shows')].concat(radios)));
      } },
      { key: 'expiry', label: 'Expiry', render: function (body, data) {
        const sel = h('select', { name: 'expiry', id: 'adm-share-expiry' }, EXPIRY.map(function (o) { return h('option', { value: o[0], selected: data.expiry === o[0] ? true : null }, o[1]); }));
        const date = h('input', { type: 'date', name: 'date', value: data.date, id: 'adm-share-date', 'aria-label': 'Expiry date' });
        const dateField = h('div', { class: 'wz-field' }, [h('label', { class: 'wz-label', for: 'adm-share-date' }, 'Date'), date]);
        dateField.hidden = data.expiry !== 'date';
        sel.addEventListener('change', function () { data.expiry = sel.value; dateField.hidden = sel.value !== 'date'; });
        date.addEventListener('input', function () { data.date = date.value; });
        date.addEventListener('change', function () { data.date = date.value; });
        body.appendChild(h('div', { class: 'wz-field' }, [h('label', { class: 'wz-label', for: 'adm-share-expiry' }, 'Link expires'), sel]));
        body.appendChild(dateField);
      }, validate: function (data) {
        if (data.expiry !== 'date') return {};
        const e = endOfDay(data.date);
        if (!e) return { date: 'Pick a date' };
        return e <= new Date().toISOString() ? { date: 'Pick a date in the future' } : {};
      } },
    ],
    review: function (data) {
      return h('div', null, [
        h('p', null, 'Create a read-only link to ' + scopeText(data.scope) + '.'),
        h('p', { class: 'muted' }, (data.label ? 'Label "' + data.label + '"; ' : 'No label; ') + 'the link ' + expiryText(data) + '. Anyone with it can view without signing in; revoke it any time.'),
      ]);
    },
    submit: function (data) {
      return ctx.api.createShare(ctx.project, { label: data.label.trim(), scope: data.scope, expires: expiresOf(data) }).then(function (r) {
        created = r;
        if (onCreated) onCreated(r);
        return r;
      });
    },
    result: function (r) {
      setTimeout(function () { decorate(r || created); }, 0);
      return { text: 'Share link created' + (r && r.share && r.share.label ? ' ("' + r.share.label + '")' : '') + '.' };
    },
  });
}

export function mountSettings(el, ctx) {
  const store = ctx.store;
  const vocab = ctx.vocab || {};
  const role = ctx.role || 'admin';
  const write = canWrite(ctx);
  const root = h('div', { class: 'adm adm-settings' });
  el.appendChild(root);
  const tabBar = h('nav', { class: 'adm-tabs', role: 'tablist', 'aria-label': 'Settings sections' });
  const panel = h('div', { class: 'adm-panel', role: 'tabpanel', id: 'adm-settings-panel' });
  root.appendChild(h('h2', null, 'Settings'));
  root.appendChild(tabBar);
  root.appendChild(panel);
  let cur = null;
  let pendingRefresh = false;
  let destroyed = false;
  const visibleTabs = function () { return SETTINGS_TABS.filter(function (t) { return canSee('settings', role, t[0]); }); };
  const tabOf = function (r) {
    const t = (r && r.tab) || '';
    return visibleTabs().some(function (x) { return x[0] === t; }) ? t : 'project';
  };
  let tab = tabOf(ctx.route);
  const ids = function (coll) { return (store.doc[coll] || []).map(function (x) { return x.id; }); };
  const venueOpts = function () { return (store.doc.venues || []).map(function (v) { return [v.id, v.name || v.id]; }); };
  const roomOpts = function () { return (store.doc.rooms || []).map(function (r) { return [r.id, r.name || r.id]; }); };

  function tabHref(t) { return ctx.routeHref ? ctx.routeHref({ view: 'settings', tab: t, query: {} }) : '#'; }
  function drawTabs() {
    tabBar.innerHTML = '';
    visibleTabs().forEach(function (t) {
      const on = tab === t[0];
      const a = h('a', {
        class: 'adm-tab', role: 'tab', href: tabHref(t[0]), id: 'adm-tab-' + t[0], 'data-tab': t[0],
        'aria-selected': on ? 'true' : 'false', 'aria-controls': 'adm-settings-panel', tabindex: on ? null : '-1',
      }, t[1]);
      a.addEventListener('click', function (e) {
        if (a.getAttribute('href') !== '#') return;
        e.preventDefault();
        show(t[0]);
      });
      tabBar.appendChild(a);
    });
    const active = tabBar.querySelector('[aria-selected=true]');
    if (active && active.scrollIntoView && tabBar.scrollWidth > tabBar.clientWidth) active.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }
  tabBar.addEventListener('keydown', function (e) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft' && e.key !== 'Home' && e.key !== 'End') return;
    const all = Array.prototype.slice.call(tabBar.querySelectorAll('.adm-tab'));
    const i = all.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    const j = e.key === 'Home' ? 0 : e.key === 'End' ? all.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + all.length) % all.length;
    all[j].focus();
  });

  function projectPanel() {
    const m = store.doc.meta || {};
    function rootField(key, sub, label, opts) {
      opts = opts || {};
      const cur2 = (store.doc[key] || {})[sub];
      let input;
      if (opts.options) input = h('select', null, opts.options.map(function (o) { const v = Array.isArray(o) ? o : [o, o]; return h('option', { value: v[0], selected: String(cur2) === String(v[0]) ? true : null }, v[1]); }));
      else if (opts.check) { input = h('input', { type: 'checkbox' }); input.checked = cur2 !== false; }
      else if (opts.multiline) { input = h('textarea', { rows: 3 }); input.value = cur2 || ''; }
      else input = h('input', { value: cur2 === undefined || cur2 === null ? '' : String(cur2), placeholder: opts.placeholder || '', inputmode: opts.inputmode });
      if (store.readOnly) input.disabled = true;
      input.addEventListener('change', function () {
        const v = opts.check ? input.checked : (input.value.trim() === '' ? null : input.value.trim());
        const value = {};
        value[sub] = v;
        ctx.commit([{ op: 'root', key: key, value: value }], 'Edit ' + label.toLowerCase());
        if (key === 'settings' && sub === 'autosave' && ctx.queue) ctx.queue.setAutosave(v !== false);
      });
      return fld(label, input);
    }
    const cards = [
      h('section', { class: 'adm-card adm-form', 'data-card': 'about' }, [
        h('h3', null, 'About'),
        rootField('meta', 'org', 'Organization'), rootField('meta', 'system', 'System'), rootField('meta', 'title', 'Map title'),
        rootField('meta', 'description', 'Description', { multiline: true }), rootField('meta', 'author', 'Author'), rootField('meta', 'version', 'Version'),
      ]),
      h('section', { class: 'adm-card adm-form', 'data-card': 'preferences' }, [
        h('h3', null, 'Preferences'),
        rootField('settings', 'default_room', 'Default room', { options: roomOpts() }),
        rootField('settings', 'units', 'Units', { options: [['metric', 'Metric (m)'], ['imperial', 'Imperial (ft)']] }),
        rootField('settings', 'cable_tag_pattern', 'Cable tag pattern', { placeholder: '{D}-{n:03}' }),
        rootField('settings', 'currency', 'Currency', { placeholder: 'USD' }),
        rootField('settings', 'public_url', 'Public URL', { placeholder: 'https://av.example.org (used in QR codes)' }),
        rootField('settings', 'problem_email', 'Problem reports email', { placeholder: 'av-team@example.org (email fallback for "Report a problem")' }),
        rootField('settings', 'autosave', 'Autosave', { check: true }),
        h('div', { class: 'muted', style: { fontSize: '12px' } }, 'Tag pattern tokens: {D} discipline letter, {M} medium, {room}, {from}, {to}, {n:03}. ' + (m.slug ? 'Project slug: ' + m.slug : '')),
      ]),
    ];
    if (role === 'admin' && ctx.api) {
      cards.push(h('section', { class: 'adm-card', 'data-card': 'danger' }, [h('h3', null, 'Danger zone'),
        h('p', { class: 'muted' }, 'Deleting a project removes it and all its history from this server.'),
        h('div', null, h('button', { type: 'button', class: 'danger', onclick: function () {
          ctx.prompt('Type the project name (' + ctx.project + ') to delete it and all its history.', '', { title: 'Delete project', ok: 'Delete' }).then(function (v) {
            if (v !== ctx.project) { if (v !== null) ctx.toast('Name did not match', 'warn'); return; }
            ctx.api.deleteProject(ctx.project).then(function () { location.hash = ''; location.reload(); }, function (e) { ctx.toast(msg(e), 'err'); });
          });
        } }, 'Delete project')),
      ]));
    }
    return { nodes: [h('div', { class: 'adm-grid' }, cards)], tables: [], rebuild: true };
  }

  function crudPanel(tables, nodes) {
    return { nodes: nodes, tables: tables.map(function (t) { return t.dt; }), primary: tables[tables.length - 1].dt, refresh: function () { tables.forEach(function (t) { t.refresh(); }); } };
  }

  function roomsPanel() {
    const venues = crudTable(ctx, 'venues', [{ key: 'name', label: 'Name', required: true }, { key: 'address', label: 'Address', hideOnMobile: true }, { key: 'order', label: 'Order', number: true, hideOnMobile: true }], {
      caption: 'Venues',
      create: function (n) { return { id: newId(null, ids('venues'), n), name: n }; },
      blockers: function (v) { return (store.doc.rooms || []).some(function (r) { return r.venue === v.id; }) ? 'Move or delete its rooms first' : ''; },
    });
    const rooms = crudTable(ctx, 'rooms', [
      { key: 'name', label: 'Name', required: true },
      { key: 'code', label: 'Code', parse: function (v) { return v.toUpperCase().replace(/[^A-Z0-9-]/g, '').slice(0, 8); } },
      { key: 'kind', label: 'Kind', options: vocab.room_kinds || ['other'] },
      { key: 'venue', label: 'Venue', options: venueOpts, required: true },
      { key: 'order', label: 'Order', number: true, hideOnMobile: true },
    ], {
      caption: 'Rooms', primary: true,
      create: function (n) {
        const venue = (store.doc.venues || [])[0];
        if (!venue) { ctx.toast('Add a venue first', 'warn'); return null; }
        const id = newId(null, ids('rooms'), n);
        return { id: id, name: n, venue: venue.id, code: slug(n).replace(/-/g, '').slice(0, 4).toUpperCase() || 'ROOM', kind: 'other' };
      },
      blockers: function (r) {
        const n = (store.doc.devices || []).filter(function (d) { return d.room === r.id; }).length;
        return n ? 'Move its ' + n + ' devices first (Inventory view)' : '';
      },
    });
    return crudPanel([venues, rooms], [h('h3', null, 'Venues'), venues.el, h('h3', null, 'Rooms'), rooms.el]);
  }

  function systemsPanel() {
    const discOpts = Object.keys(vocab.disciplines || {}).map(function (k) { return [k, vocab.disciplines[k].label]; });
    const systems = crudTable(ctx, 'systems', [{ key: 'name', label: 'Name', required: true }, { key: 'room', label: 'Room', options: roomOpts, required: true }, { key: 'discipline', label: 'Discipline', options: discOpts, required: true }], {
      caption: 'Systems', primary: true,
      create: function (n) { const room = store.room && store.room !== '*' ? store.room : ((store.doc.rooms || [])[0] || {}).id; if (!room) { ctx.toast('Add a room first', 'warn'); return null; } return { id: newId(null, ids('systems'), n), name: n, room: room, discipline: 'audio' }; },
    });
    return crudPanel([systems], [h('h3', null, 'Systems'), systems.el]);
  }

  function locationsPanel() {
    const locations = crudTable(ctx, 'locations', [{ key: 'name', label: 'Name', required: true }, { key: 'kind', label: 'Kind', options: vocab.location_kinds || ['booth', 'stage', 'rack_room', 'storage', 'catwalk', 'closet', 'other'] }, { key: 'venue', label: 'Venue', options: venueOpts, empty: '\u2014', hideOnMobile: true }, { key: 'room', label: 'Room', options: roomOpts, empty: '\u2014' }], {
      caption: 'Locations', primary: true,
      create: function (n) { return { id: newId(null, ids('locations'), n), name: n, kind: 'other' }; },
    });
    return crudPanel([locations], [h('h3', null, 'Locations'), locations.el]);
  }

  function networksPanel() {
    const nets = crudTable(ctx, 'networks', [{ key: 'name', label: 'Name', required: true }, { key: 'vlan', label: 'VLAN', number: true }, { key: 'subnet', label: 'Subnet (CIDR)' }, { key: 'gateway', label: 'Gateway', hideOnMobile: true }, { key: 'protocol', label: 'Protocol', options: vocab.network_protocols || ['dante', 'aes67', 'avb', 'ndi', 'st2110', 'sacn', 'artnet', 'qlan', 'control', 'management', 'other'], empty: '\u2014' }, { key: 'dhcp_range', label: 'DHCP range', hideOnMobile: true }], {
      caption: 'Networks', primary: true,
      create: function (n) { return { id: newId(null, ids('networks'), n), name: n }; },
    });
    const p = crudPanel([nets], [h('h3', null, 'Networks'), nets.el, h('div', { class: 'muted', style: { fontSize: '12px', marginTop: '6px' } }, 'Device IPs are edited per device in the inspector; the IP schedule lives in Schedules.')]);
    return p;
  }

  function templatesPanel() {
    const host = h('div');
    const dt = createTable(host, {
      key: 'settings.templates', scope: ctx.project, caption: 'Project templates', noun: { one: 'template', many: 'templates' },
      url: urlBinding(ctx), highlight: hlOf(ctx), csvName: 'templates.csv', rows: store.doc.templates || [],
      empty: 'No project templates. Use "Save as template" on a device in the inspector to add a global one.',
      columns: [
        { key: 'id', header: 'Id', cell: function (t) { return mono(t.id); }, sticky: true },
        { key: 'model', header: 'Model', value: function (t) { return ((t.manufacturer || '') + ' ' + (t.model || '')).trim(); } },
        { key: 'kind', header: 'Kind', value: function (t) { return t.kind || ''; }, filterable: true },
        { key: 'ports', header: 'Ports', align: 'right', hideOnMobile: true, value: function (t) { return (t.ports || []).length; }, cell: function (t) { return String((t.ports || []).length) + ' groups'; } },
        write ? actions(function (t) {
          return h('button', { type: 'button', class: 'small danger', 'aria-label': 'Delete template ' + t.id, onclick: function () {
            ctx.commit([{ op: 'del', coll: 'templates', id: t.id }], 'Delete template ' + t.id);
          } }, '\u00d7');
        }) : null,
      ].filter(Boolean),
    });
    return {
      nodes: [h('h3', null, 'Project templates'), host, h('div', { class: 'muted', style: { marginTop: '8px', fontSize: '12px' } }, ((ctx.meta && ctx.meta.library_count) || 0) + ' templates in the library.')],
      tables: [dt], primary: dt, refresh: function () { dt.setRows(store.doc.templates || []); },
    };
  }

  function needsServer() { return { nodes: [h('div', { class: 'muted' }, 'Needs the server.')], tables: [] }; }

  function usersPanel() {
    if (!ctx.api) return needsServer();
    const nodes = [h('h3', null, 'Users')];
    if (ctx.session && !ctx.session.auth_enabled) nodes.push(h('p', { class: 'muted' }, 'Login is off: everyone on this server has full access. Add a user to turn it on (or set FATHOM_AUTH).'));
    const host = h('div');
    const dt = createTable(host, {
      key: 'settings.users', scope: '', caption: 'Users', noun: { one: 'user', many: 'users' },
      url: urlBinding(ctx), highlight: hlOf(ctx), csvName: 'users.csv', rowId: function (u) { return u.username; },
      empty: 'No user accounts yet.',
      columns: [
        { key: 'username', header: 'User', sticky: true },
        { key: 'role', header: 'Role', filterable: true, value: function (u) { return u.role || ''; }, cell: function (u) {
          const sel = h('select', { 'aria-label': 'Role for ' + u.username }, ['viewer', 'editor', 'admin'].map(function (x) { return h('option', { value: x, selected: u.role === x ? true : null }, x); }));
          sel.addEventListener('change', function () { ctx.api.updateUser(u.username, { role: sel.value }).then(function () { ctx.toast('Role updated', 'ok'); load(); }, function (e) { ctx.toast(msg(e), 'err'); load(); }); });
          return sel;
        } },
        { key: 'disabled', header: 'Disabled', filterable: true, value: function (u) { return u.disabled ? 'yes' : ''; }, cell: function (u) {
          const dis = h('input', { type: 'checkbox', 'aria-label': 'Disable ' + u.username });
          dis.checked = !!u.disabled;
          dis.addEventListener('change', function () { ctx.api.updateUser(u.username, { disabled: dis.checked }).then(load, function (e) { ctx.toast(msg(e), 'err'); load(); }); });
          return h('label', { class: 'chk' }, dis);
        } },
        timeCol('created', 'Created', function (u) { return u.created; }),
        actions(function (u) {
          return [
            h('button', { type: 'button', class: 'small', onclick: function () {
              ctx.prompt('New password for ' + u.username + ' (8+ characters)', '', { type: 'password', title: 'Reset password', ok: 'Set password' }).then(function (pw) {
                if (!pw) return;
                ctx.api.updateUser(u.username, { password: pw }).then(function () { ctx.toast('Password reset', 'ok'); }, function (e) { ctx.toast(msg(e), 'err'); });
              });
            } }, 'Reset password'),
            h('button', { type: 'button', class: 'small danger', onclick: function () {
              ctx.confirm('Remove user ' + u.username + '?', { danger: true }).then(function (y) { if (y) ctx.api.deleteUser(u.username).then(load, function (e) { ctx.toast(msg(e), 'err'); }); });
            } }, 'Remove'),
          ];
        }),
      ],
    });
    function load() {
      return ctx.api.users().then(function (r) { if (!destroyed) dt.setRows((r && r.users) || []); }, function (e) { if (!destroyed) dt.setError(e, load); });
    }
    const un = h('input', { placeholder: 'username', autocapitalize: 'none', autocomplete: 'off', 'aria-label': 'New username' });
    const pw = h('input', { type: 'password', placeholder: 'password (8+)', autocomplete: 'new-password', 'aria-label': 'New password' });
    const rl = h('select', { 'aria-label': 'New user role' }, ['viewer', 'editor', 'admin'].map(function (x) { return h('option', { value: x, selected: x === 'editor' ? true : null }, x); }));
    const add = h('button', { type: 'button', class: 'small primary', onclick: function () {
      ctx.api.createUser({ username: un.value.trim(), password: pw.value, role: rl.value }).then(function () { const n = un.value.trim(); un.value = ''; pw.value = ''; ctx.toast('User added', 'ok'); load().then(function () { dt.setHighlight(n); }); }, function (e) { ctx.toast(msg(e), 'err'); });
    } }, 'Add user');
    dt.setLoading(true);
    load();
    nodes.push(host, h('div', { class: 'row adm-addrow' }, [un, pw, rl, add]));
    return { nodes: nodes, tables: [dt], primary: dt };
  }

  function backupsPanel() {
    if (!ctx.api) return needsServer();
    const maxMb = (ctx.meta && ctx.meta.limits && ctx.meta.limits.max_backup_mb) || 0;
    const host = h('div');
    function download(name) {
      const a = h('a', { href: ctx.api.backupUrl(name), download: name, style: { display: 'none' } });
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
    function restore(b) {
      const what = (b.projects || []).length + ' project' + ((b.projects || []).length === 1 ? '' : 's') + (b.created ? ' from ' + fmtTime(b.created) : '');
      return ctx.prompt('This replaces every project, user account and custom template on this server with the backup (' + what + '). '
        + 'A "pre-restore" backup of the current data is taken first, so you can undo this. You may need to sign in again afterwards. Type RESTORE to continue.',
      '', { title: 'Restore ' + b.name, ok: 'Restore' }).then(function (v) {
        if (v === null) return false;
        if (String(v).trim().toUpperCase() !== 'RESTORE') { ctx.toast('Not restored: type RESTORE to confirm', 'warn'); return false; }
        ctx.toast('Restoring ' + b.name + '\u2026', 'ok');
        const flush = ctx.flush ? ctx.flush() : Promise.resolve();
        return flush.then(function () { return ctx.api.restoreBackup(b.name); }).then(function (r) {
          ctx.toast('Restored ' + b.name + (r.pre_restore_backup ? '. Previous data saved as ' + r.pre_restore_backup : '') + '. Reloading\u2026', 'ok');
          setTimeout(function () { location.reload(); }, 1500);
          return true;
        }, function (e) { ctx.toast(msg(e), 'err'); load(); return false; });
      });
    }
    function kindOf(b) { return b.error ? 'unreadable' : (b.kind === 'pre-restore' ? 'before a restore' : (/-uploaded(-\d+)?\.zip$/.test(b.name) ? 'uploaded' : (b.kind || ''))); }
    const dt = createTable(host, {
      key: 'settings.backups', scope: '', caption: 'Backups on this server', noun: { one: 'backup', many: 'backups' },
      url: urlBinding(ctx), highlight: hlOf(ctx), csvName: 'backups.csv', rowId: function (b) { return b.name; },
      rowAttrs: function (b) { return { 'data-backup': b.name }; },
      empty: 'No backups on this server yet.',
      columns: [
        { key: 'name', header: 'Backup', cell: function (b) { return mono(b.name); }, sticky: true },
        timeCol('created', 'Created', function (b) { return b.created || b.modified; }),
        { key: 'projects', header: 'Projects', value: function (b) { return b.error ? b.error : String((b.projects || []).length) + (b.include_builds ? ' + builds' : ''); },
          cell: function (b) { return h('span', { title: b.error || (b.projects || []).join('\n') }, b.error ? b.error : String((b.projects || []).length) + (b.include_builds ? ' + builds' : '')); } },
        { key: 'kind', header: 'Kind', filterable: true, value: kindOf, cell: function (b) { return h('span', null, [kindOf(b), b.label ? h('div', { class: 'muted', style: { fontSize: '11px' } }, b.label) : null]); } },
        { key: 'size', header: 'Size', align: 'right', hideOnMobile: true, value: function (b) { return Number(b.size) || 0; }, cell: function (b) { return fmtSize(b.size); } },
        actions(function (b) {
          return [
            h('a', { class: 'chip', href: ctx.api.backupUrl(b.name), download: b.name }, 'Download'),
            b.error ? null : h('button', { type: 'button', class: 'small danger', onclick: function () { restore(b); } }, 'Restore'),
            h('button', { type: 'button', class: 'small danger', 'aria-label': 'Delete ' + b.name, onclick: function () {
              ctx.confirm('Delete backup ' + b.name + ' from the server? Downloaded copies are not affected.', { danger: true, ok: 'Delete' }).then(function (y) {
                if (y) ctx.api.deleteBackup(b.name).then(load, function (e) { ctx.toast(msg(e), 'err'); });
              });
            } }, 'Delete'),
          ];
        }),
      ],
    });
    function load() {
      return ctx.api.backups().then(function (r) { if (!destroyed) dt.setRows((r && r.backups) || []); }, function (e) { if (!destroyed) dt.setError(e, load); });
    }

    const label = h('input', { placeholder: 'note (optional), e.g. before Easter changes', 'aria-label': 'Backup note' });
    const builds = h('input', { type: 'checkbox', id: 'bk-builds' });
    const create = h('button', { type: 'button', class: 'primary' }, 'Back up now');
    create.addEventListener('click', function () {
      create.disabled = true;
      create.textContent = 'Backing up\u2026';
      const flush = ctx.flush ? ctx.flush() : Promise.resolve();
      flush.then(function () { return ctx.api.createBackup({ label: label.value.trim(), include_builds: builds.checked }); }).then(function (r) {
        const b = r.backup || {};
        ctx.toast('Backup ' + b.name + ' created (' + fmtSize(b.size) + '); downloading a copy', 'ok');
        label.value = '';
        download(b.name);
        load().then(function () { dt.setHighlight(b.name); });
      }, function (e) { ctx.toast(msg(e), 'err'); }).then(function () { create.disabled = false; create.textContent = 'Back up now'; });
    });

    const file = h('input', { type: 'file', accept: '.zip,application/zip', 'aria-label': 'Backup file' });
    const upload = h('button', { type: 'button', class: 'danger' }, 'Upload and restore\u2026');
    upload.addEventListener('click', function () {
      const f = file.files && file.files[0];
      if (!f) { ctx.toast('Choose a backup .zip first', 'warn'); return; }
      if (maxMb && f.size > maxMb * 1024 * 1024) { ctx.toast('That file is larger than the ' + maxMb + ' MB limit (FATHOM_MAX_BACKUP_MB)', 'err'); return; }
      upload.disabled = true;
      upload.textContent = 'Uploading\u2026';
      ctx.api.uploadBackup(f).then(function (r) {
        file.value = '';
        load();
        return restore(r.backup || {});
      }, function (e) { ctx.toast(msg(e), 'err'); }).then(function () { upload.disabled = false; upload.textContent = 'Upload and restore\u2026'; });
    });

    dt.setLoading(true);
    load();
    return {
      nodes: [
        h('div', { class: 'adm-grid' }, [
          h('section', { class: 'adm-card', 'data-card': 'backup' }, [
            h('h3', null, 'Back up'),
            h('p', { class: 'muted' }, 'One .zip with every project (history, photos, floor plans and imports included), user accounts and custom equipment templates. '
              + 'A copy stays on this server and one downloads to this device. Keep the downloaded copy somewhere else: the server copy is lost with the server. '
              + 'The file contains password hashes, so store it like a password.'),
            h('div', { class: 'row' }, [label, h('label', { class: 'row', for: 'bk-builds' }, [builds, 'Include builds']), create]),
          ]),
          h('section', { class: 'adm-card', 'data-card': 'restore' }, [
            h('h3', null, 'Restore from a file'),
            h('p', { class: 'muted' }, 'Upload a backup .zip saved earlier (from this server or another one). You confirm before anything is replaced.'),
            h('div', { class: 'row' }, [file, upload]),
          ]),
        ]),
        h('h3', null, 'Backups on this server'),
        host,
      ],
      tables: [dt], primary: dt,
    };
  }

  function sharingPanel() {
    if (!ctx.api) return needsServer();
    const host = h('div');
    function shareHref(s) { return (ctx.appRoot || '') + 's/' + s.token + '/'; }
    const dt = createTable(host, {
      key: 'settings.sharing', scope: ctx.project, caption: 'Read-only share links', noun: { one: 'link', many: 'links' },
      url: urlBinding(ctx), highlight: hlOf(ctx), csvName: 'share-links.csv', rowId: function (s) { return s.token; },
      empty: write ? 'No share links yet. New share link creates one.' : 'No share links yet.',
      columns: [
        { key: 'label', header: 'Label', value: function (s) { return s.label || ''; }, sticky: true },
        { key: 'link', header: 'Link', value: function (s) { return 's/' + s.token + '/'; }, csv: function (s) { return shareHref(s); },
          cell: function (s) { return h('a', { href: shareHref(s), target: '_blank', rel: 'noopener', class: 'mono' }, 's/' + String(s.token).slice(0, 8) + '\u2026'); } },
        { key: 'scope', header: 'Shows', filterable: true, value: function (s) { return s.scope === 'sop' ? 'procedures' : 'project'; } },
        timeCol('created', 'Created', function (s) { return s.created; }),
        { key: 'expires', header: 'Expires', hideOnMobile: true, value: function (s) { return s.expires || ''; }, cell: function (s) { return s.expires ? fmtTime(s.expires) : 'never'; } },
        write ? actions(function (s) {
          return h('button', { type: 'button', class: 'small danger', onclick: function () { ctx.api.deleteShare(ctx.project, s.token).then(load, function (e) { ctx.toast(msg(e), 'err'); }); } }, 'Revoke');
        }) : null,
      ].filter(Boolean),
    });
    function load() {
      return ctx.api.shares(ctx.project).then(function (r) { if (!destroyed) dt.setRows((r && r.shares) || []); }, function (e) { if (!destroyed) dt.setError(new Error('Share links are not available: ' + msg(e)), load); });
    }
    const create = write ? h('button', { type: 'button', class: 'primary adm-new-share', onclick: function () {
      shareWizard(ctx, function (r) {
        if (r && r.url && navigator.clipboard) navigator.clipboard.writeText(new URL(r.url, ctx.appRoot || location.href).href).then(null, function () { /* no clipboard permission */ });
        load().then(function () { if (r && r.share) dt.setHighlight(r.share.token); });
      });
    } }, 'New share link') : null;
    dt.setLoading(true);
    load();
    return {
      nodes: [h('h3', null, 'Read-only share links'), h('p', { class: 'muted' }, 'Anyone with the link can view maps, patch tables and device pages (or only procedures). Revoke it any time.'), create ? h('div', { class: 'row adm-addrow' }, create) : null, host],
      tables: [dt], primary: dt,
    };
  }

  function offlinePanel() {
    const secure = window.isSecureContext && 'serviceWorker' in navigator;
    return { nodes: [
      h('h3', null, 'Offline'),
      secure ? h('p', null, 'Viewer pages and this project can be saved on this device for the booth or catwalk. Use "Make available offline" from the user menu (top right).') : h('p', { style: { color: 'var(--warn)' } }, 'Offline mode needs HTTPS (or localhost). On a plain http:// LAN address the browser does not allow it.'),
      h('p', { class: 'muted' }, 'Edits made while offline are kept on this device and sent when the connection comes back.'),
    ], tables: [] };
  }

  const PANELS = { project: projectPanel, rooms: roomsPanel, systems: systemsPanel, locations: locationsPanel, networks: networksPanel, templates: templatesPanel, users: usersPanel, backups: backupsPanel, sharing: sharingPanel, offline: offlinePanel };

  function clearPanel() {
    if (cur) cur.tables.forEach(function (t) { t.destroy(); });
    cur = null;
    pendingRefresh = false;
    panel.innerHTML = '';
  }
  function drawPanel() {
    clearPanel();
    panel.setAttribute('aria-labelledby', 'adm-tab-' + tab);
    panel.setAttribute('data-tab', tab);
    cur = (PANELS[tab] || projectPanel)();
    cur.nodes.forEach(function (n) { if (n) panel.appendChild(n); });
  }
  function show(t) {
    tab = t;
    drawTabs();
    drawPanel();
  }
  function refreshPanel() {
    if (!cur) return;
    if (cur.rebuild) { drawPanel(); return; }
    if (cur.refresh) cur.refresh();
  }
  // Inline editors commit on change; while one still has focus the refresh waits, so typing and
  // tabbing through a row is not interrupted by the re-render.
  function editing() {
    const a = document.activeElement;
    return !!(a && panel.contains(a) && /^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName) && a.closest('.dt-table, .adm-form'));
  }
  function onDoc() {
    if (!cur || !(cur.rebuild || cur.refresh)) return;
    if (editing()) { pendingRefresh = true; return; }
    refreshPanel();
  }
  panel.addEventListener('focusout', function () {
    setTimeout(function () {
      if (destroyed || !pendingRefresh || editing()) return;
      pendingRefresh = false;
      refreshPanel();
    }, 0);
  });
  store.addEventListener('doc', onDoc);
  drawTabs();
  drawPanel();
  if (ctx.route && ctx.route.tab && ctx.route.tab !== tab) {
    // a tab this role cannot see (or an unknown one) falls back to Project
    setTimeout(function () { if (!destroyed && ctx.navigateRoute) ctx.navigateRoute({ view: 'settings', tab: '', query: {} }, { replace: true }); }, 0);
  }
  return {
    route: function (r) {
      const next = tabOf(r);
      if (r && r.tab && r.tab !== next && ctx.navigateRoute) {
        setTimeout(function () { if (!destroyed) ctx.navigateRoute({ view: 'settings', tab: '', query: {} }, { replace: true }); }, 0);
      }
      if (next !== tab) { show(next); return; }
      if (cur && cur.primary) {
        cur.primary.readUrl();
        cur.primary.setHighlight((r && r.query && r.query.hl) || null);
      }
    },
    destroy: function () { destroyed = true; store.removeEventListener('doc', onDoc); clearPanel(); el.innerHTML = ''; },
  };
}
