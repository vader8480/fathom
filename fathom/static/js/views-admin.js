// Admin views (§6.8, FR-UX-06/07, FR-IMP-10, FR-HIST, FR-USER-08):
// Imports, History, Builds, Settings.

import { slug, newId, deepClone } from './model-core.js';
import { suggestionControl, applyChoice } from './suggest-ui.js';

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

// ------------------------------------------------------------ imports

export function mountImports(el, ctx) {
  if (needApi(el, ctx)) return { destroy: function () { el.innerHTML = ''; } };
  const store = ctx.store;
  const root = h('div', { class: 'adm' });
  el.appendChild(root);
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
  function errorTable(errors) {
    const tb = h('tbody');
    errors.forEach(function (e) {
      tb.appendChild(h('tr', null, [
        h('td', { 'data-label': 'Row', class: 'mono' }, String(e.row)), h('td', { 'data-label': 'Column', class: 'mono' }, e.column || ''),
        h('td', { 'data-label': 'Value', class: 'mono' }, e.value === '' ? h('span', { class: 'muted' }, '(empty)') : e.value),
        h('td', { 'data-label': 'Problem' }, e.message),
      ]));
    });
    return h('div', { class: 'imp-errors' }, h('table', { class: 'adm-table' }, [h('thead', null, h('tr', null, ['Row', 'Column', 'Value', 'Problem'].map(function (t) { return h('th', { scope: 'col' }, t); }))), tb]));
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
    const files = h('input', { type: 'file', multiple: true, accept: (imp.accepts || []).join(',') || null, 'aria-label': 'Files for ' + imp.label });
    if (imp.folder) { files.setAttribute('webkitdirectory', ''); }
    const dev = deviceSelect();
    const room = roomSelect();
    const out = h('div', { class: 'imp-out hidden', 'aria-live': 'polite' });
    const go = h('button', { type: 'button', class: 'primary small', disabled: store.readOnly ? true : null }, imp.mode === 'oneshot' ? 'Preview' : 'Import');
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
          out.innerHTML = '';
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
            out.appendChild(errorTable(errors));
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
            const apply = h('button', { type: 'button', class: 'primary small', style: { marginTop: '8px' }, onclick: function () {
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
        out.innerHTML = '';
        liveSummary(out, (r && r.summary) || {});
        ctx.toast('Imported ' + imp.label, 'ok');
        return ctx.reload().then(refreshOverlay).then(drawRegistered);
      }, function (e) {
        go.disabled = false;
        out.classList.remove('hidden');
        out.innerHTML = '';
        out.appendChild(h('div', { class: 'imp-err-head' }, msg(e)));
        ctx.toast(msg(e), 'err');
      });
    });
    el = h('div', { class: 'adm-card' + ((imp.templates || []).length ? ' has-tpl' : ''), 'data-importer': imp.kind }, [
      h('h4', null, imp.label || imp.kind),
      h('div', { class: 'help' }, imp.help || ''),
      templateBox(imp),
      files,
      h('div', { class: 'row adm-card-opts', style: { marginTop: '6px' } }, [imp.mode === 'oneshot' ? null : dev, room]),
      h('div', { class: 'row', style: { marginTop: '6px' } }, [go, h('span', { class: 'muted', style: { fontSize: '11px' } }, imp.mode === 'oneshot' ? 'one-shot: preview, then apply' : 'kept and re-parsed on every build')]),
      out,
    ]);
    return el;
  }

  const regWrap = h('div');
  const ovlWrap = h('div');
  function drawRegistered() {
    regWrap.innerHTML = '';
    const imps = store.doc.imports || [];
    if (!imps.length) { regWrap.appendChild(h('div', { class: 'muted' }, 'No registered imports.')); return; }
    const tb = h('tbody');
    imps.forEach(function (im) {
      const pre = h('div', { class: 'adm-pre hidden' });
      tb.appendChild(h('tr', null, [
        h('td', null, im.kind), h('td', { class: 'mono' }, im.path), h('td', null, im.device || ''), h('td', null, im.room || ''),
        h('td', null, [
          h('button', { type: 'button', class: 'small', onclick: function () {
            ctx.api.inspectImport(ctx.project, im.id).then(function (r) { pre.classList.remove('hidden'); pre.textContent = JSON.stringify(r.summary || r, null, 2); }, function (e) { ctx.toast(msg(e), 'err'); });
          } }, 'Inspect'),
          store.readOnly ? null : h('button', { type: 'button', class: 'small danger', onclick: function () {
            ctx.confirm('Remove import ' + im.path + '? Also delete its files?', { danger: true, ok: 'Remove + delete files', cancel: 'Cancel' }).then(function (y) {
              if (!y) return;
              ctx.api.deleteImport(ctx.project, im.id, true).then(function () { return ctx.reload(); }).then(refreshOverlay).then(drawRegistered, function (e) { ctx.toast(msg(e), 'err'); });
            });
          } }, 'Remove'),
          pre,
        ]),
      ]));
    });
    regWrap.appendChild(h('table', { class: 'adm-table' }, [h('thead', null, h('tr', null, ['Kind', 'Path', 'Device', 'Room', ''].map(function (t) { return h('th', { scope: 'col' }, t); }))), tb]));
  }
  function drawOverlay() {
    ovlWrap.innerHTML = '';
    const o = store.overlay;
    if (!o) { ovlWrap.appendChild(h('div', { class: 'muted' }, 'Overlay not loaded yet.')); return; }
    const count = function (x) { return Array.isArray(x) ? x.length : (x ? Object.keys(x).length : 0); };
    ovlWrap.appendChild(h('div', { class: 'row' }, [
      h('span', { class: 'chip' }, count(o.devices) + ' import devices'), h('span', { class: 'chip' }, count(o.routes) + ' routes'),
      h('span', { class: 'chip' }, count(o.port_labels) + ' devices with labels'), h('span', { class: 'chip' }, count(o.interfaces) + ' with IPs'), h('span', { class: 'chip' }, count(o.dmx) + ' DMX'),
    ]));
    const autos = (o.devices || []).filter(function (d) { return d.auto; });
    if (autos.length) {
      const tb = h('tbody');
      const sugg = o.suggestions || {};
      autos.forEach(function (d) {
        const sub = [d.manufacturer, d.model].filter(Boolean).join(' ') || d.sub || '';
        const control = suggestionControl(sugg[d.id] || [], { label: d.name || d.id, readOnly: store.readOnly, pickTemplate: ctx.pickTemplate ? function () { return ctx.pickTemplate({}); } : null });
        const promote = h('button', { type: 'button', class: 'small primary', onclick: function () {
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
        } }, 'Promote');
        tb.appendChild(h('tr', { class: 'ovl-row', 'data-device': d.id }, [
          h('td', { 'data-label': 'Device' }, [h('div', { class: 'disc-name' }, d.name || d.id), sub ? h('div', { class: 'muted' }, sub) : null, control.el]),
          h('td', { 'data-label': 'Kind' }, d.kind || ''), h('td', { 'data-label': 'From' }, d.source || ''),
          h('td', { 'data-label': '', class: 'disc-actions' }, store.readOnly ? null : promote),
        ]));
      });
      ovlWrap.appendChild(h('table', { class: 'adm-table disc-table ovl-table', style: { marginTop: '8px' } }, [h('thead', null, h('tr', null, ['Device', 'Kind', 'From', ''].map(function (t) { return h('th', { scope: 'col' }, t); }))), tb]));
      ovlWrap.appendChild(h('div', { class: 'muted', style: { fontSize: '12px', marginTop: '4px' } }, 'Suggested models come from the library, matched on what the import reported (manufacturer, model, device name). Accepting one sets kind, model and ports the way Add gear does; "No model" keeps the device as imported.'));
    }
    (o.notes || []).slice(0, 20).forEach(function (n) { ovlWrap.appendChild(h('div', { class: 'muted', style: { fontSize: '12px' } }, n)); });
  }

  root.appendChild(h('h2', null, 'Imports'));
  root.appendChild(h('p', { class: 'muted' }, 'Console, Dante, Waves, Eos, MagicQ, Videohub and CSV exports. Imports never overwrite what you typed: they fill an overlay that is rebuilt every time.'));
  root.appendChild(h('h3', null, 'Add an import'));
  const cards = h('div', { class: 'adm-cards' });
  if (!importers.length) cards.appendChild(h('div', { class: 'muted' }, 'The server did not list any importers.'));
  importers.forEach(function (imp) { cards.appendChild(card(imp)); });
  root.appendChild(cards);
  root.appendChild(h('h3', null, 'Registered imports'));
  root.appendChild(regWrap);
  root.appendChild(h('h3', null, 'Overlay'));
  root.appendChild(ovlWrap);
  drawRegistered();
  drawOverlay();
  function onDoc(e) { if ((e.detail.touched || []).some(function (r) { return r.indexOf('imports/') === 0; }) || e.detail.source === 'load') drawRegistered(); }
  store.addEventListener('doc', onDoc);
  store.addEventListener('overlay', drawOverlay);
  return { destroy: function () { store.removeEventListener('doc', onDoc); store.removeEventListener('overlay', drawOverlay); el.innerHTML = ''; } };
}

// ------------------------------------------------------------ history

export function mountHistory(el, ctx) {
  if (needApi(el, ctx)) return { destroy: function () { el.innerHTML = ''; } };
  const store = ctx.store;
  const root = h('div', { class: 'adm' });
  el.appendChild(root);
  const tb = h('tbody');
  const more = h('button', { type: 'button', class: 'small hidden' }, 'Load older');
  const diffBox = h('div', { class: 'adm-pre hidden', 'aria-live': 'polite' });
  let oldest = null;
  root.appendChild(h('h2', null, 'History'));
  root.appendChild(h('p', { class: 'muted' }, 'Every save is a revision. View any revision read-only, compare it with now, or restore it as a new revision.'));
  root.appendChild(diffBox);
  root.appendChild(h('table', { class: 'adm-table' }, [h('thead', null, h('tr', null, ['Rev', 'When', 'Who', 'Source', 'Summary', 'Changed', ''].map(function (t) { return h('th', { scope: 'col' }, t); }))), tb]));
  root.appendChild(more);
  function row(r) {
    return h('tr', { 'data-rev': r.revision }, [
      h('td', { class: 'mono' }, 'r' + r.revision), h('td', null, fmtTime(r.time)), h('td', null, r.author || ''), h('td', null, r.source || ''), h('td', null, r.summary || ''),
      h('td', { title: (r.touched || []).join('\n') }, String((r.touched || []).length || r.ops || '')),
      h('td', { style: { whiteSpace: 'nowrap' } }, [
        h('button', { type: 'button', class: 'small', onclick: function () { if (ctx.timeTravel) ctx.timeTravel(r.revision); } }, 'View'),
        h('button', { type: 'button', class: 'small', onclick: function () {
          ctx.api.historyDiff(ctx.project, r.revision, store.revision).then(function (d) {
            diffBox.classList.remove('hidden');
            diffBox.textContent = 'r' + r.revision + ' vs r' + store.revision + '\nadded: ' + (d.added || []).join(', ') + '\nremoved: ' + (d.removed || []).join(', ') + '\nchanged: ' + (d.changed || []).join(', ');
          }, function (e) { ctx.toast(msg(e), 'err'); });
        } }, 'Diff'),
        store.readOnly && !(ctx.isTimeTravel && ctx.isTimeTravel()) || ctx.role === 'viewer' ? null : h('button', { type: 'button', class: 'small', onclick: function () { if (ctx.restoreRevision) ctx.restoreRevision(r.revision); } }, 'Restore'),
      ]),
    ]);
  }
  function load(before) {
    return ctx.api.history(ctx.project, { limit: 50, before: before }).then(function (r) {
      const revs = (r && r.revisions) || [];
      if (!before) tb.innerHTML = '';
      revs.forEach(function (x) { tb.appendChild(row(x)); oldest = x.revision; });
      more.classList.toggle('hidden', revs.length < 50 || oldest <= 1);
      if (!before && !revs.length) tb.appendChild(h('tr', null, h('td', { colspan: '7', class: 'muted' }, 'No history yet. The first save starts it.')));
    }, function (e) { tb.innerHTML = ''; tb.appendChild(h('tr', null, h('td', { colspan: '7' }, msg(e)))); });
  }
  more.addEventListener('click', function () { load(oldest); });
  function onRev() { load(); }
  store.addEventListener('revision', onRev);
  load();
  return { destroy: function () { store.removeEventListener('revision', onRev); el.innerHTML = ''; } };
}

// ------------------------------------------------------------ builds

export function mountBuilds(el, ctx) {
  if (needApi(el, ctx)) return { destroy: function () { el.innerHTML = ''; } };
  const store = ctx.store;
  const root = h('div', { class: 'adm' });
  el.appendChild(root);
  const caps = (ctx.meta && ctx.meta.capabilities) || {};
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
  const list = h('div');
  const go = h('button', { type: 'button', class: 'primary', disabled: store.readOnly ? true : null }, 'Build package');
  go.addEventListener('click', function () {
    const sel = Array.prototype.filter.call(rooms.querySelectorAll('input[data-room]'), function (b) { return b.checked; }).map(function (b) { return b.getAttribute('data-room'); });
    go.disabled = true;
    go.textContent = 'Building\u2026';
    const flush = ctx.flush ? ctx.flush() : Promise.resolve();
    flush.then(function () { return ctx.api.build(ctx.project, { state: state.value, pdf: pdf.checked, png: png.checked, discovery: disc.checked, rooms: sel.length === (store.doc.rooms || []).length ? null : sel }); }).then(function (r) {
      ctx.toast('Built ' + r.build + ' (' + (r.files || []).length + ' files)', 'ok');
      load();
    }, function (e) { ctx.toast(msg(e), 'err'); }).then(function () { go.disabled = false; go.textContent = 'Build package'; });
  });
  root.appendChild(h('h2', null, 'Builds'));
  root.appendChild(h('p', { class: 'muted' }, 'A build is a folder you can hand over: per-room maps, device pages, patch tables, cable and IP schedules, rack and floor-plan SVGs, labels, BOM and a zip of it all.'));
  root.appendChild(h('div', { class: 'adm-card' }, [
    fld('State', state),
    h('div', { class: 'field' }, [h('label', null, 'Rooms'), rooms]),
    h('div', { class: 'row' }, [h('label', { class: 'row', for: 'bld-pdf' }, [pdf, 'PDF']), h('label', { class: 'row', for: 'bld-png' }, [png, 'PNG']), caps.chrome ? null : h('span', { class: 'muted' }, 'PDF/PNG need Chrome on the server.')]),
    h('div', { class: 'field' }, [h('label', null, 'Report sections'), h('label', { class: 'row', for: 'bld-disc' }, [disc, 'Discovered connections (latest completed discovery run and promoted discovered cables)'])]),
    h('div', { class: 'row', style: { marginTop: '8px' } }, go),
  ]));
  root.appendChild(h('h3', null, 'Previous builds'));
  root.appendChild(list);
  function load() {
    ctx.api.builds(ctx.project).then(function (r) {
      list.innerHTML = '';
      const bs = (r && r.builds) || [];
      if (!bs.length) { list.appendChild(h('div', { class: 'muted' }, 'No builds yet.')); return; }
      const tb = h('tbody');
      bs.forEach(function (b) {
        const base = (ctx.appRoot || '') + 'builds/' + encodeURIComponent(ctx.project) + '/' + encodeURIComponent(b.name) + '/';
        const zip = (b.files || []).filter(function (f) { return /\.zip$/.test(f); })[0];
        tb.appendChild(h('tr', null, [
          h('td', { class: 'mono' }, b.name), h('td', null, fmtTime(b.created)), h('td', null, String((b.files || []).length)),
          h('td', { style: { whiteSpace: 'nowrap' } }, [
            h('a', { class: 'chip', href: base + 'index.html', target: '_blank', rel: 'noopener' }, 'Open'),
            zip ? h('a', { class: 'chip', href: base + zip, download: zip }, 'Zip') : null,
            store.readOnly ? null : h('button', { type: 'button', class: 'small danger', onclick: function () {
              ctx.confirm('Delete build ' + b.name + '?', { danger: true }).then(function (y) { if (y) ctx.api.deleteBuild(ctx.project, b.name).then(load, function (e) { ctx.toast(msg(e), 'err'); }); });
            } }, 'Delete'),
          ]),
        ]));
      });
      list.appendChild(h('table', { class: 'adm-table' }, [h('thead', null, h('tr', null, ['Run', 'Created', 'Files', ''].map(function (t) { return h('th', { scope: 'col' }, t); }))), tb]));
    }, function (e) { list.innerHTML = ''; list.appendChild(h('div', { class: 'muted' }, msg(e))); });
  }
  load();
  return { destroy: function () { el.innerHTML = ''; } };
}

// ------------------------------------------------------------ settings

function crudTable(ctx, coll, cols, opts) {
  opts = opts || {};
  const store = ctx.store;
  const wrap = h('div');
  function draw() {
    wrap.innerHTML = '';
    const list = (store.doc[coll] || []).filter(opts.filter || function () { return true; });
    const tb = h('tbody');
    list.forEach(function (ent) {
      const tr = h('tr', { 'data-id': ent.id });
      tr.appendChild(h('td', { class: 'mono' }, ent.id));
      cols.forEach(function (c) {
        let input;
        const cur = ent[c.key];
        if (c.options) {
          const opts2 = typeof c.options === 'function' ? c.options() : c.options;
          input = h('select', { 'aria-label': c.label }, (c.empty !== undefined ? [h('option', { value: '' }, c.empty)] : []).concat(opts2.map(function (o) { const v = Array.isArray(o) ? o : [o, o]; return h('option', { value: v[0], selected: String(cur) === String(v[0]) ? true : null }, v[1]); })));
        } else if (c.type === 'check') {
          input = h('input', { type: 'checkbox', 'aria-label': c.label });
          input.checked = !!cur;
        } else {
          input = h('input', { value: cur === undefined || cur === null ? '' : String(cur), inputmode: c.number ? 'numeric' : null, 'aria-label': c.label });
        }
        if (store.readOnly) input.disabled = true;
        input.addEventListener('change', function () {
          let v = c.type === 'check' ? (input.checked ? true : null) : (input.value.trim() === '' ? null : input.value.trim());
          if (c.number && v !== null) v = Number(v);
          if (c.parse && v !== null) v = c.parse(v);
          if (c.required && v === null) { ctx.toast(c.label + ' is required', 'warn'); draw(); return; }
          const value = {};
          value[c.key] = v;
          ctx.commit([{ op: 'merge', coll: coll, id: ent.id, value: value }], 'Edit ' + coll.replace(/s$/, '') + ' ' + (ent.name || ent.id));
        });
        tr.appendChild(h('td', null, c.type === 'check' ? h('label', { class: 'chk' }, input) : input));
      });
      tr.appendChild(h('td', null, store.readOnly ? null : h('button', { type: 'button', class: 'small danger', 'aria-label': 'Delete ' + (ent.name || ent.id), onclick: function () {
        const blockers = opts.blockers ? opts.blockers(ent) : '';
        if (blockers) { ctx.toast(blockers, 'warn'); return; }
        ctx.confirm('Delete ' + (ent.name || ent.id) + '?', { danger: true }).then(function (y) { if (y) ctx.commit([{ op: 'del', coll: coll, id: ent.id }], 'Delete ' + (ent.name || ent.id)); });
      } }, '\u00d7')));
      tb.appendChild(tr);
    });
    wrap.appendChild(h('div', { style: { overflowX: 'auto' } }, h('table', { class: 'adm-table' }, [h('thead', null, h('tr', null, [h('th', { scope: 'col' }, 'Id')].concat(cols.map(function (c) { return h('th', { scope: 'col' }, c.label); })).concat([h('th', { scope: 'col' }, '')]))), tb])));
    if (!list.length) wrap.appendChild(h('div', { class: 'muted' }, 'None yet.'));
    if (!store.readOnly && opts.create) {
      const name = h('input', { placeholder: 'Name', 'aria-label': 'New ' + coll.replace(/s$/, '') + ' name' });
      const add = h('button', { type: 'button', class: 'small', onclick: function () {
        const n = name.value.trim();
        if (!n) { name.focus(); return; }
        const ent = opts.create(n);
        if (!ent) return;
        ctx.commit([{ op: 'put', coll: coll, id: ent.id, value: ent }], 'Add ' + coll.replace(/s$/, '') + ' ' + n);
        name.value = '';
      } }, 'Add');
      name.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); add.click(); } });
      wrap.appendChild(h('div', { class: 'row', style: { marginTop: '6px' } }, [name, add]));
    }
  }
  draw();
  return { el: wrap, draw: draw };
}

export function mountSettings(el, ctx) {
  const store = ctx.store;
  const vocab = ctx.vocab || {};
  const root = h('div', { class: 'adm' });
  el.appendChild(root);
  const tabs = [['project', 'Project'], ['rooms', 'Venues & rooms'], ['systems', 'Systems & locations'], ['networks', 'Networks'], ['templates', 'Templates'], ['users', 'Users'], ['backups', 'Backups'], ['sharing', 'Sharing'], ['offline', 'Offline']];
  let tab = 'project';
  const tabBar = h('div', { class: 'adm-tabs', role: 'tablist' });
  const panel = h('div', { role: 'tabpanel' });
  root.appendChild(h('h2', null, 'Settings'));
  root.appendChild(tabBar);
  root.appendChild(panel);
  let tables = [];
  const ids = function (coll) { return (store.doc[coll] || []).map(function (x) { return x.id; }); };
  const venueOpts = function () { return (store.doc.venues || []).map(function (v) { return [v.id, v.name || v.id]; }); };
  const roomOpts = function () { return (store.doc.rooms || []).map(function (r) { return [r.id, r.name || r.id]; }); };

  function drawTabs() {
    tabBar.innerHTML = '';
    tabs.forEach(function (t) {
      if ((t[0] === 'users' || t[0] === 'backups') && ctx.role !== 'admin') return;
      tabBar.appendChild(h('button', { type: 'button', role: 'tab', 'aria-selected': tab === t[0] ? 'true' : 'false', 'data-tab': t[0], onclick: function () { tab = t[0]; drawTabs(); drawPanel(); } }, t[1]));
    });
  }

  function projectPanel() {
    const m = store.doc.meta || {};
    const s = store.doc.settings || {};
    function rootField(key, sub, label, opts) {
      opts = opts || {};
      const cur = (store.doc[key] || {})[sub];
      let input;
      if (opts.options) input = h('select', null, opts.options.map(function (o) { const v = Array.isArray(o) ? o : [o, o]; return h('option', { value: v[0], selected: String(cur) === String(v[0]) ? true : null }, v[1]); }));
      else if (opts.check) { input = h('input', { type: 'checkbox' }); input.checked = cur !== false; }
      else if (opts.multiline) { input = h('textarea', { rows: 3 }); input.value = cur || ''; }
      else input = h('input', { value: cur === undefined || cur === null ? '' : String(cur), placeholder: opts.placeholder || '', inputmode: opts.inputmode });
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
    return [
      h('h3', null, 'About'),
      rootField('meta', 'org', 'Organization'), rootField('meta', 'system', 'System'), rootField('meta', 'title', 'Map title'),
      rootField('meta', 'description', 'Description', { multiline: true }), rootField('meta', 'author', 'Author'), rootField('meta', 'version', 'Version'),
      h('h3', null, 'Preferences'),
      rootField('settings', 'default_room', 'Default room', { options: roomOpts() }),
      rootField('settings', 'units', 'Units', { options: [['metric', 'Metric (m)'], ['imperial', 'Imperial (ft)']] }),
      rootField('settings', 'cable_tag_pattern', 'Cable tag pattern', { placeholder: '{D}-{n:03}' }),
      rootField('settings', 'currency', 'Currency', { placeholder: 'USD' }),
      rootField('settings', 'public_url', 'Public URL', { placeholder: 'https://av.example.org (used in QR codes)' }),
      rootField('settings', 'problem_email', 'Problem reports email', { placeholder: 'av-team@example.org (email fallback for "Report a problem")' }),
      rootField('settings', 'autosave', 'Autosave', { check: true }),
      h('div', { class: 'muted', style: { fontSize: '12px' } }, 'Tag pattern tokens: {D} discipline letter, {M} medium, {room}, {from}, {to}, {n:03}. ' + (m.slug ? 'Project slug: ' + m.slug : '') + (s.revision ? '' : '')),
      ctx.role === 'admin' && ctx.api ? h('div', null, [h('h3', null, 'Danger zone'), h('button', { type: 'button', class: 'danger', onclick: function () {
        ctx.prompt('Type the project name (' + ctx.project + ') to delete it and all its history.', '', { title: 'Delete project', ok: 'Delete' }).then(function (v) {
          if (v !== ctx.project) { if (v !== null) ctx.toast('Name did not match', 'warn'); return; }
          ctx.api.deleteProject(ctx.project).then(function () { location.hash = ''; location.reload(); }, function (e) { ctx.toast(msg(e), 'err'); });
        });
      } }, 'Delete project')]) : null,
    ];
  }

  function roomsPanel() {
    const venues = crudTable(ctx, 'venues', [{ key: 'name', label: 'Name', required: true }, { key: 'address', label: 'Address' }, { key: 'order', label: 'Order', number: true }], {
      create: function (n) { return { id: newId(null, ids('venues'), n), name: n }; },
      blockers: function (v) { return (store.doc.rooms || []).some(function (r) { return r.venue === v.id; }) ? 'Move or delete its rooms first' : ''; },
    });
    const rooms = crudTable(ctx, 'rooms', [
      { key: 'name', label: 'Name', required: true },
      { key: 'code', label: 'Code', parse: function (v) { return v.toUpperCase().replace(/[^A-Z0-9-]/g, '').slice(0, 8); } },
      { key: 'kind', label: 'Kind', options: vocab.room_kinds || ['other'] },
      { key: 'venue', label: 'Venue', options: venueOpts, required: true },
      { key: 'order', label: 'Order', number: true },
    ], {
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
    tables = [venues, rooms];
    return [h('h3', null, 'Venues'), venues.el, h('h3', null, 'Rooms'), rooms.el];
  }

  function systemsPanel() {
    const discOpts = Object.keys(vocab.disciplines || {}).map(function (k) { return [k, vocab.disciplines[k].label]; });
    const systems = crudTable(ctx, 'systems', [{ key: 'name', label: 'Name', required: true }, { key: 'room', label: 'Room', options: roomOpts, required: true }, { key: 'discipline', label: 'Discipline', options: discOpts, required: true }], {
      create: function (n) { const room = store.room && store.room !== '*' ? store.room : ((store.doc.rooms || [])[0] || {}).id; if (!room) { ctx.toast('Add a room first', 'warn'); return null; } return { id: newId(null, ids('systems'), n), name: n, room: room, discipline: 'audio' }; },
    });
    const locations = crudTable(ctx, 'locations', [{ key: 'name', label: 'Name', required: true }, { key: 'kind', label: 'Kind', options: vocab.location_kinds || ['booth', 'stage', 'rack_room', 'storage', 'catwalk', 'closet', 'other'] }, { key: 'venue', label: 'Venue', options: venueOpts, empty: '\u2014' }, { key: 'room', label: 'Room', options: roomOpts, empty: '\u2014' }], {
      create: function (n) { return { id: newId(null, ids('locations'), n), name: n, kind: 'other' }; },
    });
    tables = [systems, locations];
    return [h('h3', null, 'Systems'), systems.el, h('h3', null, 'Locations'), locations.el];
  }

  function networksPanel() {
    const nets = crudTable(ctx, 'networks', [{ key: 'name', label: 'Name', required: true }, { key: 'vlan', label: 'VLAN', number: true }, { key: 'subnet', label: 'Subnet (CIDR)' }, { key: 'gateway', label: 'Gateway' }, { key: 'protocol', label: 'Protocol', options: vocab.network_protocols || ['dante', 'aes67', 'avb', 'ndi', 'st2110', 'sacn', 'artnet', 'qlan', 'control', 'management', 'other'], empty: '\u2014' }, { key: 'dhcp_range', label: 'DHCP range' }], {
      create: function (n) { return { id: newId(null, ids('networks'), n), name: n }; },
    });
    tables = [nets];
    return [h('h3', null, 'Networks'), nets.el, h('div', { class: 'muted', style: { fontSize: '12px', marginTop: '6px' } }, 'Device IPs are edited per device in the inspector; the IP schedule lives in Schedules.')];
  }

  function templatesPanel() {
    const list = store.doc.templates || [];
    const tb = h('tbody');
    list.forEach(function (t) {
      tb.appendChild(h('tr', null, [h('td', { class: 'mono' }, t.id), h('td', null, (t.manufacturer || '') + ' ' + (t.model || '')), h('td', null, t.kind || ''), h('td', null, String((t.ports || []).length) + ' groups'),
        h('td', null, store.readOnly ? null : h('button', { type: 'button', class: 'small danger', onclick: function () {
          ctx.commit([{ op: 'del', coll: 'templates', id: t.id }], 'Delete template ' + t.id);
        } }, '\u00d7'))]));
    });
    return [
      h('h3', null, 'Project templates'),
      list.length ? h('table', { class: 'adm-table' }, [h('thead', null, h('tr', null, ['Id', 'Model', 'Kind', 'Ports', ''].map(function (x) { return h('th', { scope: 'col' }, x); }))), tb]) : h('div', { class: 'muted' }, 'No project templates. Use "Save as template" on a device in the inspector to add a global one.'),
      h('div', { class: 'muted', style: { marginTop: '8px', fontSize: '12px' } }, ((ctx.meta && ctx.meta.library_count) || 0) + ' templates in the library.'),
    ];
  }

  function usersPanel() {
    const wrap = h('div');
    if (!ctx.api) return [h('div', { class: 'muted' }, 'Needs the server.')];
    if (ctx.session && !ctx.session.auth_enabled) wrap.appendChild(h('p', { class: 'muted' }, 'Login is off: everyone on this server has full access. Add a user to turn it on (or set FATHOM_AUTH).'));
    const tbWrap = h('div');
    function load() {
      ctx.api.users().then(function (r) {
        tbWrap.innerHTML = '';
        const tb = h('tbody');
        ((r && r.users) || []).forEach(function (u) {
          const role = h('select', { 'aria-label': 'Role for ' + u.username }, ['viewer', 'editor', 'admin'].map(function (x) { return h('option', { value: x, selected: u.role === x ? true : null }, x); }));
          role.addEventListener('change', function () { ctx.api.updateUser(u.username, { role: role.value }).then(function () { ctx.toast('Role updated', 'ok'); }, function (e) { ctx.toast(msg(e), 'err'); load(); }); });
          const dis = h('input', { type: 'checkbox', 'aria-label': 'Disabled' });
          dis.checked = !!u.disabled;
          dis.addEventListener('change', function () { ctx.api.updateUser(u.username, { disabled: dis.checked }).then(load, function (e) { ctx.toast(msg(e), 'err'); load(); }); });
          tb.appendChild(h('tr', null, [h('td', null, u.username), h('td', null, role), h('td', null, h('label', { class: 'chk' }, dis)), h('td', null, fmtTime(u.created)),
            h('td', { style: { whiteSpace: 'nowrap' } }, [
              h('button', { type: 'button', class: 'small', onclick: function () {
                ctx.prompt('New password for ' + u.username + ' (8+ characters)', '', { type: 'password', title: 'Reset password', ok: 'Set password' }).then(function (pw) {
                  if (!pw) return;
                  ctx.api.updateUser(u.username, { password: pw }).then(function () { ctx.toast('Password reset', 'ok'); }, function (e) { ctx.toast(msg(e), 'err'); });
                });
              } }, 'Reset password'),
              h('button', { type: 'button', class: 'small danger', onclick: function () {
                ctx.confirm('Remove user ' + u.username + '?', { danger: true }).then(function (y) { if (y) ctx.api.deleteUser(u.username).then(load, function (e) { ctx.toast(msg(e), 'err'); }); });
              } }, 'Remove'),
            ])]));
        });
        tbWrap.appendChild(h('table', { class: 'adm-table' }, [h('thead', null, h('tr', null, ['User', 'Role', 'Disabled', 'Created', ''].map(function (x) { return h('th', { scope: 'col' }, x); }))), tb]));
      }, function (e) { tbWrap.innerHTML = ''; tbWrap.appendChild(h('div', { class: 'muted' }, msg(e))); });
    }
    const un = h('input', { placeholder: 'username', autocapitalize: 'none', autocomplete: 'off', 'aria-label': 'New username' });
    const pw = h('input', { type: 'password', placeholder: 'password (8+)', autocomplete: 'new-password', 'aria-label': 'New password' });
    const rl = h('select', { 'aria-label': 'New user role' }, ['viewer', 'editor', 'admin'].map(function (x) { return h('option', { value: x, selected: x === 'editor' ? true : null }, x); }));
    const add = h('button', { type: 'button', class: 'small primary', onclick: function () {
      ctx.api.createUser({ username: un.value.trim(), password: pw.value, role: rl.value }).then(function () { un.value = ''; pw.value = ''; ctx.toast('User added', 'ok'); load(); }, function (e) { ctx.toast(msg(e), 'err'); });
    } }, 'Add user');
    wrap.appendChild(tbWrap);
    wrap.appendChild(h('div', { class: 'row', style: { marginTop: '8px' } }, [un, pw, rl, add]));
    load();
    return [h('h3', null, 'Users'), wrap];
  }

  function backupsPanel() {
    if (!ctx.api) return [h('div', { class: 'muted' }, 'Needs the server.')];
    const maxMb = (ctx.meta && ctx.meta.limits && ctx.meta.limits.max_backup_mb) || 0;
    const listWrap = h('div');
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
    function load() {
      ctx.api.backups().then(function (r) {
        listWrap.innerHTML = '';
        const bs = (r && r.backups) || [];
        if (!bs.length) { listWrap.appendChild(h('div', { class: 'muted' }, 'No backups on this server yet.')); return; }
        const tb = h('tbody');
        bs.forEach(function (b) {
          const kind = b.error ? 'unreadable' : (b.kind === 'pre-restore' ? 'before a restore' : (/-uploaded(-\d+)?\.zip$/.test(b.name) ? 'uploaded' : (b.kind || '')));
          tb.appendChild(h('tr', { 'data-backup': b.name }, [
            h('td', { class: 'mono' }, b.name),
            h('td', null, fmtTime(b.created || b.modified)),
            h('td', { title: b.error || (b.projects || []).join('\n') }, b.error ? b.error : String((b.projects || []).length) + (b.include_builds ? ' + builds' : '')),
            h('td', null, [kind, b.label ? h('div', { class: 'muted', style: { fontSize: '11px' } }, b.label) : null]),
            h('td', null, fmtSize(b.size)),
            h('td', { style: { whiteSpace: 'nowrap' } }, [
              h('a', { class: 'chip', href: ctx.api.backupUrl(b.name), download: b.name }, 'Download'),
              b.error ? null : h('button', { type: 'button', class: 'small danger', onclick: function () { restore(b); } }, 'Restore'),
              h('button', { type: 'button', class: 'small danger', 'aria-label': 'Delete ' + b.name, onclick: function () {
                ctx.confirm('Delete backup ' + b.name + ' from the server? Downloaded copies are not affected.', { danger: true, ok: 'Delete' }).then(function (y) {
                  if (y) ctx.api.deleteBackup(b.name).then(load, function (e) { ctx.toast(msg(e), 'err'); });
                });
              } }, 'Delete'),
            ]),
          ]));
        });
        listWrap.appendChild(h('div', { style: { overflowX: 'auto' } }, h('table', { class: 'adm-table' }, [h('thead', null, h('tr', null, ['Backup', 'Created', 'Projects', 'Kind', 'Size', ''].map(function (x) { return h('th', { scope: 'col' }, x); }))), tb])));
      }, function (e) { listWrap.innerHTML = ''; listWrap.appendChild(h('div', { class: 'muted' }, msg(e))); });
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
        load();
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

    load();
    return [
      h('h3', null, 'Back up'),
      h('p', { class: 'muted' }, 'One .zip with every project (history, photos, floor plans and imports included), user accounts and custom equipment templates. '
        + 'A copy stays on this server and one downloads to this device. Keep the downloaded copy somewhere else: the server copy is lost with the server. '
        + 'The file contains password hashes, so store it like a password.'),
      h('div', { class: 'row' }, [label, h('label', { class: 'row', for: 'bk-builds' }, [builds, 'Include builds']), create]),
      h('h3', null, 'Restore from a file'),
      h('p', { class: 'muted' }, 'Upload a backup .zip saved earlier (from this server or another one). You confirm before anything is replaced.'),
      h('div', { class: 'row' }, [file, upload]),
      h('h3', null, 'Backups on this server'),
      listWrap,
    ];
  }

  function sharingPanel() {
    if (!ctx.api) return [h('div', { class: 'muted' }, 'Needs the server.')];
    const wrap = h('div');
    function load() {
      ctx.api.shares(ctx.project).then(function (r) {
        wrap.innerHTML = '';
        const tb = h('tbody');
        ((r && r.shares) || []).forEach(function (s) {
          const url = (ctx.appRoot || '') + 's/' + s.token + '/';
          tb.appendChild(h('tr', null, [h('td', null, s.label || ''), h('td', null, h('a', { href: url, target: '_blank', rel: 'noopener', class: 'mono' }, 's/' + String(s.token).slice(0, 8) + '\u2026')), h('td', null, fmtTime(s.created)), h('td', null, s.expires ? fmtTime(s.expires) : 'never'),
            h('td', null, store.readOnly ? null : h('button', { type: 'button', class: 'small danger', onclick: function () { ctx.api.deleteShare(ctx.project, s.token).then(load, function (e) { ctx.toast(msg(e), 'err'); }); } }, 'Revoke'))]));
        });
        wrap.appendChild(h('table', { class: 'adm-table' }, [h('thead', null, h('tr', null, ['Label', 'Link', 'Created', 'Expires', ''].map(function (x) { return h('th', { scope: 'col' }, x); }))), tb]));
      }, function (e) { wrap.innerHTML = ''; wrap.appendChild(h('div', { class: 'muted' }, 'Share links are not available: ' + msg(e))); });
    }
    const label = h('input', { placeholder: 'label (e.g. Sunday volunteers)', 'aria-label': 'Share label' });
    const create = h('button', { type: 'button', class: 'small primary', disabled: store.readOnly ? true : null, onclick: function () {
      ctx.api.createShare(ctx.project, { label: label.value.trim() }).then(function (r) {
        const url = new URL(r.url || ('s/' + r.share.token + '/'), (ctx.appRoot || location.href)).href;
        if (navigator.clipboard) navigator.clipboard.writeText(url).then(function () { ctx.toast('Link copied: ' + url, 'ok'); }, function () { ctx.toast(url, 'ok'); });
        else ctx.toast(url, 'ok');
        label.value = '';
        load();
      }, function (e) { ctx.toast(msg(e), 'err'); });
    } }, 'Create read-only link');
    load();
    return [h('h3', null, 'Read-only share links'), h('p', { class: 'muted' }, 'Anyone with the link can view maps, patch tables and device pages. Revoke it any time.'), h('div', { class: 'row' }, [label, create]), wrap];
  }

  function offlinePanel() {
    const secure = window.isSecureContext && 'serviceWorker' in navigator;
    return [
      h('h3', null, 'Offline'),
      secure ? h('p', null, 'Viewer pages and this project can be saved on this device for the booth or catwalk. Use "Make available offline" from the user menu (top right).') : h('p', { style: { color: 'var(--warn)' } }, 'Offline mode needs HTTPS (or localhost). On a plain http:// LAN address the browser does not allow it.'),
      h('p', { class: 'muted' }, 'Edits made while offline are kept on this device and sent when the connection comes back.'),
    ];
  }

  function drawPanel() {
    panel.innerHTML = '';
    tables = [];
    const map = { project: projectPanel, rooms: roomsPanel, systems: systemsPanel, networks: networksPanel, templates: templatesPanel, users: usersPanel, backups: backupsPanel, sharing: sharingPanel, offline: offlinePanel };
    (map[tab] || projectPanel)().forEach(function (n) { if (n) panel.appendChild(n); });
  }
  function onDoc(e) {
    const d = e.detail || {};
    if (d.source === 'local' && el.contains(document.activeElement) && tab === 'project') return;
    if (tab === 'users' || tab === 'backups' || tab === 'sharing' || tab === 'offline') return;
    const active = document.activeElement;
    if (active && el.contains(active) && active.tagName === 'INPUT' && d.source === 'local' && tab === 'project') return;
    drawPanel();
  }
  store.addEventListener('doc', onDoc);
  drawTabs();
  drawPanel();
  return {
    destroy: function () { store.removeEventListener('doc', onDoc); el.innerHTML = ''; },
    getState: function () { return { tab: tab }; },
    setState: function (s) { if (s && s.tab) { tab = s.tab; drawTabs(); drawPanel(); } },
  };
}
