// Admin views (§6.8, FR-UX-06/07, FR-IMP-10, FR-HIST, FR-USER-08): Imports, History, Builds,
// Settings. Every list is a shared DataTable (docs/ui-audit.md B.3 ADM, D9); the settings tab
// (`settings/<tab>`) and the history revision (`history/<rev>`) live in the URL (D1), and `?hl=<id>`
// highlights a row of the view's primary table.

import { h } from './dom.js';
import { canSee, buildRoute } from './router-core.js';
import { createTable } from './datatable.js';
import { skeleton, emptyState, inlineError, staleBadge, reviewBadge, confirmScope } from './feedback.js';
import { openWizard } from './wizard.js';
import { slug, newId, deepClone } from './model-core.js';
import { suggestionControl, applyChoice } from './suggest-ui.js';

function msg(e) { return (e && e.details && typeof e.details.detail === 'string' && e.details.detail) || (e && e.message) || String(e); }
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

// An error for inlineError that names the action ("Could not delete build x: …") but keeps the
// status, so offline and server failures are still told apart.
function actErr(what, e) {
  return { message: what + ': ' + msg(e), status: e && e.status, code: e && e.code, name: e && e.name };
}

// States of a server-backed list (docs/ui-audit.md B.5): a table-shaped skeleton until the first
// rows, then inlineError + Retry in its place, or (compact) above rows already shown when a
// later request or a row action fails. `shown` starts true for tables filled from the document.
function listState(t, shown) {
  const slot = h('div', { class: 'adm-state', 'aria-live': 'polite' });
  t.root.parentNode.insertBefore(slot, t.root);
  shown = !!shown;
  function show(on) { t.root.style.display = on ? '' : 'none'; }
  return {
    slot: slot,
    busy: function () {
      if (shown) return;
      slot.innerHTML = '';
      slot.appendChild(skeleton('table', 5));
      show(false);
    },
    done: function (rows) {
      shown = true;
      slot.innerHTML = '';
      show(true);
      if (rows) t.setRows(rows);
    },
    fail: function (err, retry) {
      slot.innerHTML = '';
      slot.appendChild(inlineError(err, retry, { compact: shown }));
      show(shown);
    },
    clear: function () { if (shown) slot.innerHTML = ''; },
  };
}

// A slot beside a form button for its request failures (inlineError + Retry).
function errSlot(cls) {
  const el = h('div', { class: 'adm-err' + (cls ? ' ' + cls : ''), 'aria-live': 'polite' });
  return {
    el: el,
    show: function (err, retry, compact) { el.innerHTML = ''; el.appendChild(inlineError(err, retry, { compact: compact !== false })); },
    clear: function () { el.innerHTML = ''; },
  };
}

// Endpoints the api object has no method for yet (invites, suggestions): the api's generic request
// helper when it exists (same base, CSRF header and error mapping), else fetch with the same contract.
function apiCall(ctx, method, path, body, params) {
  const api = ctx.api || {};
  if (typeof api.request === 'function') return api.request(method, path, body, { params: params }).then(function (r) { return r.data; });
  const q = Object.keys(params || {}).filter(function (k) { return params[k] !== undefined && params[k] !== null && params[k] !== ''; })
    .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(String(params[k])); }).join('&');
  const headers = { 'X-Fathom': '1', 'Accept': 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  return fetch((api.base || '') + path + (q ? '?' + q : ''), { method: method, headers: headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: 'same-origin' }).then(function (res) {
    if (res.status === 204) return null;
    return res.json().catch(function () { return null; }).then(function (data) {
      if (res.ok) return data;
      const err = new Error((data && data.error) || 'HTTP ' + res.status);
      err.status = res.status;
      err.code = (data && data.code) || '';
      throw err;
    });
  });
}
// A server without the endpoint (older build, sibling feature not merged yet): the list is empty
// rather than broken.
function isMissing(e) { return !!(e && (e.status === 404 || e.status === 405)); }
function absUrl(ctx, rel) {
  if (!rel) return '';
  try { return new URL(rel, ctx.appRoot || location.href).href; } catch (e) { return rel; }
}
// Copy to the clipboard (clipboard API, else select + execCommand); the input keeps the text selected
// so a manual copy works too.
function copyField(ctx, input, text) {
  function fallback() {
    input.focus();
    input.select();
    let ok = false;
    try { ok = document.execCommand && document.execCommand('copy'); } catch (e) { ok = false; }
    ctx.toast(ok ? 'Link copied' : 'Select the link and copy it', ok ? 'ok' : 'warn');
  }
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(function () { ctx.toast('Link copied', 'ok'); }, fallback);
  else fallback();
}
function overridesText(projects) {
  const n = Object.keys(projects || {}).length;
  return n ? n + (n === 1 ? ' override' : ' overrides') : '\u2014';
}

// Per-project role overrides (users, invites): rows of `project · role` with add / remove. `value()`
// is the whole map (rows without a project are skipped); `valid()` marks duplicate projects.
function projectRolesEditor(ctx, initial, opts) {
  opts = opts || {};
  const live = (ctx.projects || []).map(function (p) { return { name: p.name, title: p.title && p.title !== p.name ? p.name + ' \u00b7 ' + p.title : p.name }; });
  if (ctx.project && !live.some(function (p) { return p.name === ctx.project; })) live.unshift({ name: ctx.project, title: ctx.project });
  const rows = [];
  const list = h('div', { class: 'adm-pr-rows' });
  const err = h('div', { class: 'adm-pr-err', 'aria-live': 'polite' });
  const hint = h('div', { class: 'muted adm-pr-hint' }, opts.hint || 'No overrides: the server role applies to every project.');
  function options(cur) {
    const names = live.slice();
    if (cur && !names.some(function (p) { return p.name === cur; })) names.push({ name: cur, title: cur + ' (not on this server)' });
    return [h('option', { value: '' }, 'Choose a project\u2026')].concat(names.map(function (p) { return h('option', { value: p.name, selected: p.name === cur ? true : null }, p.title); }));
  }
  function sync() {
    hint.hidden = rows.length > 0;
    valid();
    if (opts.onChange) opts.onChange();
  }
  function addRow(name, role) {
    const proj = h('select', { class: 'adm-pr-proj', 'aria-label': 'Project' }, options(name || ''));
    const rl = h('select', { class: 'adm-pr-role', 'aria-label': 'Role in that project' }, ['viewer', 'editor'].map(function (x) { return h('option', { value: x, selected: x === (role || 'viewer') ? true : null }, x); }));
    const rm = h('button', { type: 'button', class: 'small adm-pr-rm', 'aria-label': 'Remove this project' }, '\u00d7');
    const row = h('div', { class: 'adm-pr-row' }, [proj, h('span', { class: 'muted adm-pr-dot', 'aria-hidden': 'true' }, '\u00b7'), rl, rm]);
    const entry = { el: row, proj: proj, rl: rl };
    rm.addEventListener('click', function () { rows.splice(rows.indexOf(entry), 1); row.remove(); sync(); });
    proj.addEventListener('change', sync);
    rl.addEventListener('change', sync);
    rows.push(entry);
    list.appendChild(row);
    hint.hidden = true;
  }
  function value() {
    const out = {};
    rows.forEach(function (r) { if (r.proj.value) out[r.proj.value] = r.rl.value; });
    return out;
  }
  function valid() {
    const seen = {};
    let dup = false;
    rows.forEach(function (r) { r.el.classList.remove('adm-pr-dup'); });
    rows.forEach(function (r) {
      const n = r.proj.value;
      if (!n) return;
      if (seen[n]) { dup = true; r.el.classList.add('adm-pr-dup'); seen[n].el.classList.add('adm-pr-dup'); } else seen[n] = r;
    });
    err.textContent = dup ? 'A project is listed twice. Remove one of the rows.' : '';
    return !dup;
  }
  Object.keys(initial || {}).sort().forEach(function (k) { addRow(k, initial[k]); });
  hint.hidden = rows.length > 0;
  const add = h('button', { type: 'button', class: 'small adm-pr-add', onclick: function () { addRow('', 'viewer'); const last = rows[rows.length - 1]; if (last) last.proj.focus(); sync(); } }, '+ Add project');
  const el = h('div', { class: 'adm-pr', 'data-rows': 'projects' }, [list, hint, err, h('div', { class: 'row' }, add)]);
  return { el: el, value: value, valid: valid, count: function () { return rows.length; } };
}

// DataTable `empty` as a node: the emptyState when there are no rows at all, otherwise the table's
// own "no match" line with Clear filters.
function emptyFor(getTable, o) {
  return function (state, info) {
    if (info && info.total > 0) {
      return h('div', null, [
        h('p', { class: 'dt-empty-text' }, 'No rows match these filters.'),
        h('button', { type: 'button', class: 'dt-clear', onclick: function () { const t = getTable(); if (t) t.setState({ q: '', filters: {} }); } }, 'Clear filters'),
      ]);
    }
    return emptyState(typeof o === 'function' ? o() : o);
  };
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
    function failed(e, what) {
      go.disabled = false;
      out.classList.remove('hidden');
      clearOut(out);
      el.classList.remove('wide');
      out.appendChild(inlineError(actErr(what, e), run));
    }
    function run() {
      const fs = Array.prototype.slice.call(files.files || []);
      if (!fs.length) { ctx.toast('Choose a file first', 'warn'); return null; }
      go.disabled = true;
      const params = { kind: imp.kind, device: dev.value, room: room.value };
      const flush = ctx.flush ? ctx.flush() : Promise.resolve();
      if (imp.mode === 'oneshot') {
        return flush.then(function () { return ctx.api.importPreview(ctx.project, fs, params); }).then(function (r) {
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
            const applyErr = errSlot('adm-apply-err');
            const doApply = function () {
              apply.disabled = true;
              applyErr.clear();
              const ops = deepClone(r.ops);
              return Promise.all(ops.map(function (op) {
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
              }, function (e) { apply.disabled = false; applyErr.show(actErr('Could not apply the import', e), doApply); });
            };
            const apply = h('button', { type: 'button', class: 'primary small adm-apply', onclick: doApply }, 'Apply ' + r.ops.length + ' changes');
            out.appendChild(apply);
            out.appendChild(applyErr.el);
          } else {
            out.appendChild(h('div', { class: 'muted', style: { marginTop: '6px' } }, 'Nothing to apply.'));
          }
        }, function (e) { failed(e, 'Could not preview ' + (fs[0].name || imp.label)); });
      }
      return flush.then(function () { return ctx.api.upload(ctx.project, 'imports', fs, params); }).then(function (r) {
        go.disabled = false;
        out.classList.remove('hidden');
        clearOut(out);
        liveSummary(out, (r && r.summary) || {});
        ctx.toast('Imported ' + imp.label, 'ok');
        return ctx.reload().then(refreshOverlay).then(drawRegistered);
      }, function (e) { failed(e, 'Could not import ' + (fs[0].name || imp.label)); });
    }
    go.addEventListener('click', run);
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
    empty: write ? 'No registered imports. Import a console, Dante or CSV export above to add one.' : 'No registered imports. Editors add them from console, Dante or CSV exports.',
    columns: [
      { key: 'kind', header: 'Kind', filterable: true, sticky: true },
      { key: 'path', header: 'Path', cell: function (im) { return mono(im.path); } },
      { key: 'device', header: 'Device', value: function (im) { return im.device || ''; }, hideOnMobile: true },
      { key: 'room', header: 'Room', value: function (im) { return im.room || ''; }, filterable: true, hideOnMobile: true },
      actions(function (im) {
        return [
          h('button', { type: 'button', class: 'small', onclick: function () { inspect(im); } }, 'Inspect'),
          write ? h('button', { type: 'button', class: 'small danger', onclick: function () {
            confirmScope(ctx, { verb: 'Remove', noun: 'import ' + im.path, danger: true, ok: 'Remove + delete files',
              detail: 'Its files are deleted from the server and the overlay is rebuilt without it. Nothing you typed changes.' }).then(function (y) { if (y) removeImport(im); });
          } }, 'Remove') : null,
        ];
      }),
    ],
  });
  const regState = listState(regTable, true);
  function drawRegistered() { regTable.setRows(store.doc.imports || []); }
  function inspect(im) {
    return ctx.api.inspectImport(ctx.project, im.id).then(function (r) {
      regState.clear();
      inspectBox.classList.remove('hidden');
      inspectBox.textContent = im.path + '\n' + JSON.stringify(r.summary || r, null, 2);
    }, function (e) { regState.fail(actErr('Could not inspect ' + im.path, e), function () { return inspect(im); }); });
  }
  function removeImport(im) {
    return ctx.api.deleteImport(ctx.project, im.id, true).then(function () {
      regState.clear();
      return ctx.reload().then(refreshOverlay).then(drawRegistered);
    }, function (e) { regState.fail(actErr('Could not remove ' + im.path, e), function () { return removeImport(im); }); });
  }

  // overlay
  const ovlChips = h('div', { class: 'row adm-ovl-chips' });
  const ovlReview = h('span', { class: 'adm-ovl-review' });
  const ovlHost = h('div', { class: 'adm-ovl' });
  const ovlNotes = h('div', { class: 'adm-ovl-notes' });
  const stale = staleBadge({
    fetchedAt: function () { return ctx.overlayInfo ? ctx.overlayInfo().fetchedAt : null; },
    fetchedRev: function () { return ctx.overlayInfo ? ctx.overlayInfo().revision : null; },
    currentRev: function () { return store.revision; },
    onRefresh: function () { return loadOverlay(); },
  });
  let destroyed = false;
  function fetchOverlay() {
    return ctx.api.overlay(ctx.project).then(function (o) { if (!destroyed) store.setOverlay(o); return o; });
  }
  // The shell fetches the overlay once per project load and swallows failures; this view shows the
  // skeleton until it lands and its own failure (with Retry) when it does not.
  function loadOverlay() {
    if (!store.overlay) ovlState.busy();
    return fetchOverlay().then(function () { if (!destroyed) ovlState.clear(); }, function (e) {
      if (!destroyed) ovlState.fail(actErr(store.overlay ? 'Could not refresh the overlay' : 'Could not load the overlay', e), loadOverlay);
    });
  }
  let ovlCache = {};
  let ovlSugg = {};
  function ovlEntry(d) {
    if (ovlCache[d.id]) return ovlCache[d.id];
    const sub = [d.manufacturer, d.model].filter(Boolean).join(' ') || d.sub || '';
    const control = suggestionControl(ovlSugg[d.id] || [], { label: d.name || d.id, readOnly: !write, pickTemplate: ctx.pickTemplate ? function () { return ctx.pickTemplate({}); } : null });
    const perr = errSlot('adm-row-err');
    function doPromote() {
      const dev = deepClone(d);
      delete dev.auto;
      delete dev.source;
      (dev.ports || []).forEach(function (p) { delete p.auto; });
      if ((store.doc.devices || []).some(function (x) { return x.id === dev.id; })) { ctx.toast(dev.id + ' already exists', 'warn'); return null; }
      promote.disabled = true;
      perr.clear();
      return applyChoice(ctx, control, dev).then(function () {
        promote.disabled = false;
        ctx.commit([{ op: 'put', coll: 'devices', id: dev.id, value: dev }], 'Promote ' + (d.name || d.id));
        ctx.toast('Promoted ' + (d.name || d.id) + (dev.template ? ' as ' + ((dev.manufacturer ? dev.manufacturer + ' ' : '') + (dev.model || dev.template)) : ' into the model'), 'ok');
      }, function (e) { promote.disabled = false; perr.show(actErr('Could not promote ' + (d.name || d.id), e), doPromote); });
    }
    const promote = write ? h('button', { type: 'button', class: 'small primary', onclick: doPromote }, 'Promote') : null;
    const e = {
      cell: h('div', { class: 'adm-ovl-dev' }, [h('div', { class: 'disc-name' }, d.name || d.id), sub ? h('div', { class: 'muted' }, sub) : null, control.el]),
      act: h('span', { class: 'disc-actions' }, [promote, write ? perr.el : null]),
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
  const ovlState = listState(ovlTable);
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
      ovlState.busy();
      stale.refresh();
      return;
    }
    ovlSugg = o.suggestions || {};
    const count = function (x) { return Array.isArray(x) ? x.length : (x ? Object.keys(x).length : 0); };
    [count(o.devices) + ' import devices', count(o.routes) + ' routes', count(o.port_labels) + ' devices with labels', count(o.interfaces) + ' with IPs', count(o.dmx) + ' DMX'].forEach(function (t) {
      ovlChips.appendChild(h('span', { class: 'chip' }, t));
    });
    const autos = (o.devices || []).filter(function (d) { return d.auto; });
    ovlState.done(autos);
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
  if (!store.overlay) loadOverlay();
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
      destroyed = true;
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
    empty: emptyFor(function () { return table; }, { title: 'No revisions yet', text: 'Every save creates one.' }),
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
          canRestore() ? h('button', { type: 'button', class: 'small', onclick: function () { restore(r.revision); } }, 'Restore') : null,
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
    if (!rev) { diffBox.classList.add('hidden'); return null; }
    const n = Number(rev);
    diffBox.classList.remove('hidden');
    if (n === store.revision) { diffBox.textContent = 'r' + n + ' is the current revision.'; return null; }
    diffBox.textContent = 'Comparing r' + n + ' with r' + store.revision + '\u2026';
    return ctx.api.historyDiff(ctx.project, n, store.revision).then(function (d) {
      if (destroyed || current !== rev) return;
      diffBox.textContent = 'r' + n + ' vs r' + store.revision + '\nadded: ' + (d.added || []).join(', ') + '\nremoved: ' + (d.removed || []).join(', ') + '\nchanged: ' + (d.changed || []).join(', ');
    }, function (e) {
      if (destroyed || current !== rev) return;
      diffBox.textContent = '';
      diffBox.appendChild(inlineError(actErr('Could not compare r' + n + ' with r' + store.revision, e), function () { return showDiff(rev); }, { compact: true }));
    });
  }
  // Restore runs here rather than through the shell's restoreRevision so the question carries the
  // revision it creates (B.5) and a failure stays beside the list with Retry.
  function restore(rev) {
    const flush = ctx.flush ? ctx.flush() : Promise.resolve();
    return flush.then(function () {
      const latest = Math.max(Number(store.revision) || 0, revs.length ? Number(revs[0].revision) || 0 : 0);
      return confirmScope(ctx, { verb: 'Restore', noun: 'revision ' + rev, ok: 'Restore',
        detail: 'This creates revision ' + (latest + 1) + '. Nothing is lost: the current state stays in history.' });
    }).then(function (yes) { if (yes) return doRestore(rev); });
  }
  function doRestore(rev) {
    if (ctx.isTimeTravel && ctx.isTimeTravel() && ctx.endTimeTravel) ctx.endTimeTravel();
    return ctx.api.restore(ctx.project, rev, store.revision).then(function (r) {
      list.clear();
      ctx.toast('Restored as revision ' + r.revision, 'ok');
      return (ctx.reload ? ctx.reload() : Promise.resolve()).then(function () { if (!destroyed) return load(); });
    }, function (e) { if (!destroyed) list.fail(actErr('Could not restore revision ' + rev, e), function () { return doRestore(rev); }); });
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
  const list = listState(table);
  function load(before) {
    if (!before) list.busy();
    return ctx.api.history(ctx.project, { limit: PAGE, before: before }).then(function (r) {
      if (destroyed) return;
      const got = (r && r.revisions) || [];
      revs = before ? revs.concat(got) : got;
      if (got.length) oldest = got[got.length - 1].revision;
      hasMore = got.length >= PAGE && oldest > 1;
      more.hidden = !hasMore;
      list.done(revs);
    }, function (e) {
      if (!destroyed) list.fail(before ? actErr('Could not load older revisions', e) : e, function () { return load(before); });
    });
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
  let go = null;
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
    go = h('button', { type: 'button', class: 'primary', id: 'bld-go' }, 'Build package');
    const buildErr = errSlot('adm-build-err');
    const runBuild = function () {
      const sel = Array.prototype.filter.call(rooms.querySelectorAll('input[data-room]'), function (b) { return b.checked; }).map(function (b) { return b.getAttribute('data-room'); });
      go.disabled = true;
      go.textContent = 'Building\u2026';
      buildErr.clear();
      const flush = ctx.flush ? ctx.flush() : Promise.resolve();
      return flush.then(function () { return ctx.api.build(ctx.project, { state: state.value, pdf: pdf.checked, png: png.checked, discovery: disc.checked, rooms: sel.length === (store.doc.rooms || []).length ? null : sel }); }).then(function (r) {
        ctx.toast('Built ' + r.build + ' (' + (r.files || []).length + ' files)', 'ok');
        return load().then(function () { table.setHighlight(r.build); });
      }, function (e) { if (!destroyed) buildErr.show(actErr('Build failed', e), runBuild, false); }).then(function () { go.disabled = false; go.textContent = 'Build package'; });
    };
    go.addEventListener('click', runBuild);
    root.appendChild(h('div', { class: 'adm-card adm-build-form' }, [
      fld('State', state),
      h('div', { class: 'field' }, [h('label', null, 'Rooms'), rooms]),
      h('div', { class: 'row' }, [h('label', { class: 'row', for: 'bld-pdf' }, [pdf, 'PDF']), h('label', { class: 'row', for: 'bld-png' }, [png, 'PNG']), caps.chrome ? null : h('span', { class: 'muted' }, 'PDF/PNG need Chrome on the server.')]),
      h('div', { class: 'field' }, [h('label', null, 'Report sections'), h('label', { class: 'row', for: 'bld-disc' }, [disc, 'Discovered connections (latest completed discovery run and promoted discovered cables)'])]),
      h('div', { class: 'row', style: { marginTop: '8px' } }, go),
      buildErr.el,
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
    empty: emptyFor(function () { return table; }, function () {
      return write
        ? { title: 'No builds yet', text: 'Build creates the PDF/HTML pack: maps, patch tables, schedules, labels and a zip of it all.', action: { label: 'Build package', run: function () { if (go && !go.disabled) go.click(); } } }
        : { title: 'No builds yet', text: 'Editors build the PDF/HTML pack here; finished builds show up in this list.' };
    }),
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
            if (y) remove(b);
          });
        } }, 'Delete');
      }) : null,
    ].filter(Boolean),
  });
  const list = listState(table);
  function remove(b) {
    return ctx.api.deleteBuild(ctx.project, b.name).then(function () { list.clear(); return load(); }, function (e) {
      if (!destroyed) list.fail(actErr('Could not delete build ' + b.name, e), function () { return remove(b); });
    });
  }
  function load() {
    list.busy();
    return ctx.api.builds(ctx.project).then(function (r) {
      if (!destroyed) list.done(((r && r.builds) || []).map(function (b) { return Object.assign({ id: b.name }, b); }));
    }, function (e) { if (!destroyed) list.fail(e, load); });
  }
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
        confirmScope(ctx, { verb: 'Delete', noun: noun + ' ' + (ent.name || ent.id), danger: true }).then(function (y) { if (y) ctx.commit([{ op: 'del', coll: coll, id: ent.id }], 'Delete ' + (ent.name || ent.id)); });
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
  ['templates', 'Templates'], ['users', 'Users'], ['invites', 'Invites'], ['backups', 'Backups'], ['sharing', 'Sharing'], ['suggestions', 'Suggestions'],
  ['assistant', 'Assistant'], ['offline', 'Offline'], ['trash', 'Trash'],
];
// Settings › Assistant (P4C): provider labels in the order the select shows them, env variable names
// for the "Set by environment" hint, and the local-server presets used when the catalogue has none.
const LLM_LABELS = { openai: 'OpenAI', anthropic: 'Anthropic', xai: 'xAI Grok', openai_compat: 'Local / OpenAI-compatible server' };
const LLM_ENV = { base_url: 'FATHOM_LLM_URL', api_key: 'FATHOM_LLM_API_KEY', provider: 'FATHOM_LLM_PROVIDER', model: 'FATHOM_LLM_MODEL', api: 'FATHOM_LLM_API',
  temperature: 'FATHOM_LLM_TEMPERATURE', max_tokens: 'FATHOM_LLM_MAX_TOKENS', web_lookup: 'FATHOM_LLM_WEB_LOOKUP', daily_cap: 'FATHOM_LLM_DAILY_CAP' };
const LLM_PRESETS = [['ollama', 'Ollama', 'http://localhost:11434/v1'], ['lmstudio', 'LM Studio', 'http://localhost:1234/v1'], ['vllm', 'vLLM', 'http://localhost:8000/v1'], ['llamacpp', 'llama.cpp', 'http://localhost:8080/v1']];
const INVITE_TTL = [['24', '24 hours'], ['72', '72 hours'], ['168', '7 days']];

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

  // Lock editing (P2C): one `settings.locked` op through the ops pipeline; the server stamps
  // locked_by / locked_at and answers other ops with 423 while locked. The toggle is shown to every
  // editor even while the store is read-only, because unlocking is how it stops being read-only.
  function lockCard() {
    const s = store.doc.settings || {};
    const locked = s.locked === true;
    const who = locked && (s.locked_by || s.locked_at) ? (s.locked_by ? 'by ' + s.locked_by : '') + (s.locked_at ? (s.locked_by ? ' \u00b7 ' : '') + fmtTime(s.locked_at) : '') : '';
    const status = h('div', { class: 'adm-lock-status', 'data-locked': locked ? 'true' : 'false' }, [
      h('span', { class: 'chip' + (locked ? ' on' : '') }, locked ? 'Locked' : 'Unlocked'),
      who ? h('span', { class: 'adm-lock-who' }, who) : null,
    ]);
    const mayToggle = role !== 'viewer' && (!store.readOnly || locked) && !(ctx.isTimeTravel && ctx.isTimeTravel());
    const toggle = mayToggle ? h('button', { type: 'button', class: locked ? 'primary' : '', 'data-act': 'lock-toggle', 'aria-pressed': locked ? 'true' : 'false', onclick: function () {
      ctx.commit([{ op: 'root', key: 'settings', value: { locked: !locked } }], locked ? 'Unlock editing' : 'Lock editing');
      ctx.toast(locked ? 'Editing unlocked' : 'Editing locked', 'ok');
    } }, locked ? 'Unlock editing' : 'Lock editing') : null;
    return h('section', { class: 'adm-card', 'data-card': 'lock' }, [
      h('h3', null, 'Lock editing'),
      status,
      toggle ? h('div', { class: 'row adm-lock-row' }, toggle) : null,
      h('p', { class: 'muted adm-lock-hint' }, 'While locked, nobody can change the model until someone unlocks it. Builds, files and procedures are unaffected.'),
    ]);
  }

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
      lockCard(),
    ];
    if (role === 'admin' && ctx.api) {
      // Typing the name stays: it is a stronger guard than confirmScope for the one delete that
      // takes a whole project and its history.
      const delErr = errSlot();
      const deleteProject = function () {
        delErr.clear();
        return ctx.api.deleteProject(ctx.project).then(function () { location.hash = ''; location.reload(); }, function (e) {
          if (!destroyed) delErr.show(actErr('Could not move ' + ctx.project + ' to the trash', e), deleteProject);
        });
      };
      cards.push(h('section', { class: 'adm-card', 'data-card': 'danger' }, [h('h3', null, 'Danger zone'),
        h('p', { class: 'muted' }, 'Moving a project to the trash takes it off the project list. An admin can restore it, with its history and files, from Settings \u203a Trash until it is deleted permanently there.'),
        h('div', null, h('button', { type: 'button', class: 'danger', 'data-act': 'trash-project', onclick: function () {
          ctx.prompt('Type the project name (' + ctx.project + ') to move it to the trash. It can be restored from Settings \u203a Trash.', '', { title: 'Move to trash', ok: 'Move to trash' }).then(function (v) {
            if (v !== ctx.project) { if (v !== null) ctx.toast('Name did not match', 'warn'); return; }
            deleteProject();
          });
        } }, 'Move to trash')),
        delErr.el,
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
            confirmScope(ctx, { verb: 'Delete', noun: 'template ' + t.id, danger: true, detail: 'Existing devices keep their ports; Undo brings the template back.' }).then(function (y) {
              if (y) ctx.commit([{ op: 'del', coll: 'templates', id: t.id }], 'Delete template ' + t.id);
            });
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
      rowAttrs: function (u) { return { 'data-user': u.username }; }, cards: true,
      empty: 'No user accounts yet. Add a user below to turn sign-in on.',
      columns: [
        { key: 'username', header: 'User', sticky: true },
        { key: 'role', header: 'Role', filterable: true, value: function (u) { return u.role || ''; }, cell: function (u) {
          const sel = h('select', { 'aria-label': 'Role for ' + u.username }, ['viewer', 'editor', 'admin'].map(function (x) { return h('option', { value: x, selected: u.role === x ? true : null }, x); }));
          sel.addEventListener('change', function () { update(u, { role: sel.value }, 'Could not change the role of ' + u.username, 'Role updated'); });
          return sel;
        } },
        { key: 'projects', header: 'Projects', value: function (u) { return overridesText(u.projects); }, csv: function (u) { return Object.keys(u.projects || {}).sort().map(function (k) { return k + ': ' + u.projects[k]; }).join('; '); },
          cell: function (u) {
            const keys = Object.keys(u.projects || {}).sort();
            return h('span', { class: keys.length ? 'adm-user-projects' : 'muted adm-user-projects', title: keys.map(function (k) { return k + ': ' + u.projects[k]; }).join('\n') || null }, overridesText(u.projects));
          } },
        { key: 'disabled', header: 'Disabled', filterable: true, value: function (u) { return u.disabled ? 'yes' : ''; }, cell: function (u) {
          const dis = h('input', { type: 'checkbox', 'aria-label': 'Disable ' + u.username });
          dis.checked = !!u.disabled;
          dis.addEventListener('change', function () { update(u, { disabled: dis.checked }, 'Could not ' + (dis.checked ? 'disable ' : 'enable ') + u.username); });
          return h('label', { class: 'chk' }, dis);
        } },
        timeCol('created', 'Created', function (u) { return u.created; }),
        actions(function (u) {
          return [
            h('button', { type: 'button', class: 'small', 'data-act': 'access', 'aria-label': 'Access per project for ' + u.username, onclick: function () { openAccess(u); } }, 'Access'),
            h('button', { type: 'button', class: 'small', onclick: function () {
              ctx.prompt('New password for ' + u.username + ' (8+ characters)', '', { type: 'password', title: 'Reset password', ok: 'Set password' }).then(function (pw) {
                if (pw) update(u, { password: pw }, 'Could not reset the password of ' + u.username, 'Password reset', true);
              });
            } }, 'Reset password'),
            h('button', { type: 'button', class: 'small danger', onclick: function () {
              confirmScope(ctx, { verb: 'Remove', noun: 'user ' + u.username, danger: true, ok: 'Remove user',
                detail: 'They can no longer sign in. Revisions they saved stay in history.' }).then(function (y) { if (y) removeUser(u); });
            } }, 'Remove'),
          ];
        }),
      ],
    });
    const list = listState(dt);
    function load() {
      list.busy();
      return ctx.api.users().then(function (r) { if (!destroyed) list.done((r && r.users) || []); }, function (e) { if (!destroyed) list.fail(e, load); });
    }
    function update(u, patch, what, ok, noReload) {
      return ctx.api.updateUser(u.username, patch).then(function () {
        list.clear();
        if (ok) ctx.toast(ok, 'ok');
        return noReload ? null : load();
      }, function (e) {
        // reload first so the control shows the server value again, then the failure above it
        const show = function () { if (!destroyed) list.fail(actErr(what, e), function () { return update(u, patch, what, ok, noReload); }); };
        if (destroyed) return null;
        return noReload ? show() : load().then(show);
      });
    }
    function removeUser(u) {
      return ctx.api.deleteUser(u.username).then(function () { list.clear(); return load(); }, function (e) {
        if (!destroyed) list.fail(actErr('Could not remove user ' + u.username, e), function () { return removeUser(u); });
      });
    }
    // Access per project (P2C): a dialog (bottom sheet at sm) with the per-project rows; Save PATCHes
    // the whole `projects` map. Admins have no overrides to edit.
    const accessSlot = h('div', { class: 'adm-user-access' });
    function openAccess(u) {
      const admin = u.role === 'admin';
      const body = h('div', { class: 'adm-access', 'data-user': u.username }, [
        h('h4', null, 'Access per project'),
        admin ? h('p', { class: 'muted adm-access-admin' }, 'Admins have full access everywhere.')
          : h('p', { class: 'muted' }, 'The server role (' + (u.role || 'viewer') + ') applies everywhere except in the projects listed here.'),
      ]);
      const editor = admin ? null : projectRolesEditor(ctx, u.projects || {});
      if (editor) body.appendChild(editor.el);
      function save() {
        return update(u, { projects: editor.value() }, 'Could not save the access of ' + u.username, 'Access updated');
      }
      if (ctx.openDialog) {
        return ctx.openDialog({
          title: u.username,
          body: body,
          buttons: editor ? [{ label: 'Cancel', value: null }, { label: 'Save', primary: true, validate: editor.valid, value: true }] : [{ label: 'Close', value: null }],
        }).then(function (v) { if (v && editor) return save(); return null; });
      }
      // harness: no dialog host, the editor opens under the table
      accessSlot.innerHTML = '';
      if (editor) body.appendChild(h('div', { class: 'row' }, [h('button', { type: 'button', class: 'small primary', onclick: function () { if (editor.valid()) save().then(function () { accessSlot.innerHTML = ''; }); } }, 'Save'), h('button', { type: 'button', class: 'small', onclick: function () { accessSlot.innerHTML = ''; } }, 'Cancel')]));
      accessSlot.appendChild(body);
      return Promise.resolve(null);
    }
    const un = h('input', { placeholder: 'username', autocapitalize: 'none', autocomplete: 'off', 'aria-label': 'New username' });
    const pw = h('input', { type: 'password', placeholder: 'password (8+)', autocomplete: 'new-password', 'aria-label': 'New password' });
    const rl = h('select', { 'aria-label': 'New user role' }, ['viewer', 'editor', 'admin'].map(function (x) { return h('option', { value: x, selected: x === 'editor' ? true : null }, x); }));
    const addErr = errSlot();
    const addUser = function () {
      addErr.clear();
      return ctx.api.createUser({ username: un.value.trim(), password: pw.value, role: rl.value }).then(function () {
        const n = un.value.trim();
        un.value = '';
        pw.value = '';
        ctx.toast('User added', 'ok');
        return load().then(function () { dt.setHighlight(n); });
      }, function (e) { if (!destroyed) addErr.show(actErr('Could not add ' + (un.value.trim() || 'the user'), e), addUser); });
    };
    const add = h('button', { type: 'button', class: 'small primary', onclick: addUser }, 'Add user');
    load();
    nodes.push(host, accessSlot, h('div', { class: 'row adm-addrow' }, [un, pw, rl, add]), addErr.el);
    return { nodes: nodes, tables: [dt], primary: dt };
  }

  // Settings › Invites (P2C, admin): one-time invite links with a role, optional per-project
  // overrides and an expiry; the list of open invites with Revoke.
  function invitesPanel() {
    if (!ctx.api) return needsServer();
    const host = h('div');
    const roleSel = h('select', { id: 'adm-inv-role', 'aria-label': 'Role of the invited user' }, ['viewer', 'editor', 'admin'].map(function (x) { return h('option', { value: x, selected: x === 'editor' ? true : null }, x); }));
    const ttl = h('select', { id: 'adm-inv-ttl', 'aria-label': 'Link expires' }, INVITE_TTL.map(function (o) { return h('option', { value: o[0], selected: o[0] === '72' ? true : null }, o[1]); }));
    const note = h('input', { id: 'adm-inv-note', placeholder: 'e.g. for Jordan, Sunday volunteers', autocomplete: 'off', maxlength: '120' });
    const pr = projectRolesEditor(ctx, {}, { hint: 'No overrides: the role above applies to every project.' });
    const adminNote = h('div', { class: 'muted adm-access-admin' }, 'Admins have full access everywhere.');
    const prField = h('div', { class: 'field adm-inv-projects' }, [h('label', null, 'Access per project'), h('div', null, [pr.el, adminNote])]);
    function syncRole() {
      const admin = roleSel.value === 'admin';
      pr.el.hidden = admin;
      adminNote.hidden = !admin;
    }
    roleSel.addEventListener('change', syncRole);
    syncRole();
    const out = h('div', { class: 'adm-inv-out', hidden: true, 'aria-live': 'polite' });
    const createErr = errSlot();
    const create = h('button', { type: 'button', class: 'primary adm-inv-create', 'data-act': 'create-invite' }, 'Create link');
    function showLink(r) {
      const url = absUrl(ctx, r.url || ((r.accept_url || 'invite/') + (/\/$/.test(r.accept_url || 'invite/') ? '' : '/') + (r.token || (r.invite && r.invite.token) || '')));
      out.innerHTML = '';
      out.hidden = false;
      const input = h('input', { class: 'adm-inv-url mono', readonly: true, value: url, 'aria-label': 'Invite link' });
      input.addEventListener('focus', function () { input.select(); });
      const copy = h('button', { type: 'button', class: 'small adm-inv-copy', 'data-act': 'copy-invite', onclick: function () { copyField(ctx, input, url); } }, 'Copy');
      out.appendChild(h('div', { class: 'row adm-share-row' }, [input, copy]));
      out.appendChild(h('div', { class: 'muted adm-inv-hint' }, 'Send this link yourself \u2014 it works once' + (r.expires ? ' and expires ' + fmtTime(r.expires) : '') + '.'));
    }
    function doCreate() {
      if (!pr.valid()) return null;
      create.disabled = true;
      createErr.clear();
      const body = { role: roleSel.value, projects: roleSel.value === 'admin' ? {} : pr.value(), ttl_hours: Number(ttl.value) || 72, note: note.value.trim() };
      return apiCall(ctx, 'POST', 'api/v2/invites', body).then(function (r) {
        create.disabled = false;
        if (destroyed) return null;
        r = r || {};
        showLink(r);
        ctx.toast('Invite link created', 'ok');
        note.value = '';
        const token = r.token || (r.invite && r.invite.token);
        return load().then(function () { if (token) dt.setHighlight(token); });
      }, function (e) {
        create.disabled = false;
        if (destroyed) return null;
        createErr.show(actErr(isMissing(e) ? 'This server has no invite links yet' : 'Could not create the invite link', e), isMissing(e) ? null : doCreate, false);
        return null;
      });
    }
    create.addEventListener('click', doCreate);
    function projectsText(inv) {
      const p = inv.projects || {};
      const keys = Object.keys(p).sort();
      return keys.length ? keys.map(function (k) { return k + ': ' + p[k]; }).join(', ') : '\u2014';
    }
    const dt = createTable(host, {
      key: 'settings.invites', scope: '', caption: 'Open invites', noun: { one: 'invite', many: 'invites' }, cards: true,
      url: urlBinding(ctx), highlight: hlOf(ctx), csvName: 'invites.csv', rowId: function (i) { return i.token; },
      rowAttrs: function (i) { return { 'data-invite': i.token }; },
      empty: emptyFor(function () { return dt; }, { title: 'No open invites.', text: 'Create link makes a one-time link you send yourself; it shows up here until it is used, expires or is revoked.' }),
      columns: [
        { key: 'role', header: 'Role', filterable: true, value: function (i) { return i.role || ''; }, sticky: true },
        { key: 'projects', header: 'Projects', value: projectsText, cell: function (i) { return h('span', { class: Object.keys(i.projects || {}).length ? '' : 'muted' }, projectsText(i)); } },
        { key: 'created_by', header: 'Created by', filterable: true, value: function (i) { return i.created_by || ''; } },
        timeCol('expires', 'Expires', function (i) { return i.expires; }),
        { key: 'note', header: 'Note', value: function (i) { return i.note || ''; } },
        actions(function (i) {
          return h('button', { type: 'button', class: 'small danger', 'data-act': 'revoke', 'aria-label': 'Revoke invite ' + (i.note || String(i.token).slice(0, 8)), onclick: function () {
            confirmScope(ctx, { verb: 'Revoke', noun: 'invite link' + (i.note ? ' \u201c' + i.note + '\u201d' : ''), danger: true, ok: 'Revoke',
              detail: 'The link stops working at once. Nobody who already used it is affected.' }).then(function (y) { if (y) revoke(i); });
          } }, 'Revoke');
        }),
      ],
    });
    const list = listState(dt);
    function load() {
      list.busy();
      return apiCall(ctx, 'GET', 'api/v2/invites').then(function (r) { if (!destroyed) list.done((r && r.invites) || []); }, function (e) {
        if (destroyed) return;
        if (isMissing(e)) list.done([]);
        else list.fail(actErr('Could not load the invites', e), load);
      });
    }
    function revoke(i) {
      return apiCall(ctx, 'DELETE', 'api/v2/invites/' + encodeURIComponent(i.token)).then(function () { list.clear(); ctx.toast('Invite revoked', 'ok'); return load(); }, function (e) {
        if (!destroyed) list.fail(actErr('Could not revoke the invite', e), function () { return revoke(i); });
      });
    }
    load();
    return {
      nodes: [
        h('section', { class: 'adm-card adm-form adm-inv-form', 'data-card': 'invite' }, [
          h('h3', null, 'Invite someone'),
          h('p', { class: 'muted' }, 'An invite link lets one person create their own account with the role you choose. It works once and expires on its own.'),
          fld('Role', roleSel),
          prField,
          fld('Expires in', ttl),
          fld('Note', note),
          h('div', { class: 'row adm-inv-row' }, create),
          createErr.el,
          out,
        ]),
        h('h3', null, 'Open invites'),
        host,
      ],
      tables: [dt], primary: dt,
    };
  }

  // Settings › Suggestions (P2C, admin): problem reports of kind `suggestion` for this project, or
  // for every project; Resolve / Reopen reuses the problems PATCH.
  function suggestionsPanel() {
    if (!ctx.api) return needsServer();
    const host = h('div');
    let all = false;
    const allBox = h('input', { type: 'checkbox', id: 'adm-sug-all' });
    allBox.addEventListener('change', function () { all = allBox.checked; load(); });
    const summary = h('span', { class: 'muted adm-sug-summary' });
    const isOpen = function (r) { return (r.status || 'open') === 'open'; };
    const projectOf = function (r) { return r.project || ctx.project; };
    const deviceHref = function (r) { return buildRoute({ project: projectOf(r), room: '*', view: 'devices', id: r.device, query: {} }); };
    const pageHref = function (r) { return buildRoute({ project: projectOf(r), room: '*', view: 'sop', query: { page: r.page } }); };
    const aboutText = function (r) { return r.device ? (r.device_name || r.device) : (r.page ? (r.page_title || r.page) : ''); };
    function setStatus(r, status) {
      return ctx.api.patchProblem(projectOf(r), r.id, { status: status }).then(function () {
        list.clear();
        ctx.toast(status === 'resolved' ? 'Suggestion resolved' : 'Suggestion reopened', 'ok');
        const p = projectOf(r) === ctx.project && ctx.reload ? ctx.reload() : Promise.resolve();
        return p.then(load, load);
      }, function (e) {
        if (!destroyed) list.fail(actErr('Could not ' + (status === 'resolved' ? 'resolve' : 'reopen') + ' the suggestion', e), function () { return setStatus(r, status); });
      });
    }
    const dt = createTable(host, {
      key: 'settings.suggestions', scope: ctx.project, caption: 'Suggestions', noun: { one: 'suggestion', many: 'suggestions' }, cards: true,
      url: urlBinding(ctx), highlight: hlOf(ctx), csvName: 'suggestions.csv', rowId: function (r) { return projectOf(r) + ':' + r.id; },
      rowAttrs: function (r) { return { 'data-suggestion': r.id, 'data-project': projectOf(r) }; },
      rowClass: function (r) { return isOpen(r) ? '' : 'adm-sug-resolved'; },
      empty: emptyFor(function () { return dt; }, { title: 'No suggestions yet.', text: 'Anyone can send one from the user menu.' }),
      columns: [
        { key: 'text', header: 'Suggestion', sticky: true, value: function (r) { return r.text || ''; }, cell: function (r) {
          return h('div', { class: 'adm-sug-text' }, [r.text || '', !isOpen(r) && r.resolved ? h('div', { class: 'muted adm-sug-resolved-note' }, 'Resolved ' + fmtTime(r.resolved) + (r.resolved_by ? ' by ' + r.resolved_by : '') + (r.note ? ' \u2014 ' + r.note : '')) : null]);
        } },
        { key: 'project', header: 'Project', filterable: true, value: projectOf, cell: function (r) { return mono(projectOf(r)); } },
        { key: 'by', header: 'By', filterable: true, value: function (r) { return r.by || ''; } },
        timeCol('created', 'When', function (r) { return r.created; }),
        { key: 'about', header: 'About', value: aboutText, cell: function (r) {
          if (r.device) return h('a', { class: 'chip adm-sug-about', 'data-device': r.device, href: deviceHref(r) }, r.device_name || r.device);
          if (r.page) return h('a', { class: 'chip adm-sug-about', 'data-page': r.page, href: pageHref(r) }, r.page_title || r.page);
          return h('span', { class: 'muted' }, '\u2014');
        } },
        { key: 'status', header: 'Status', filterable: true, value: function (r) { return isOpen(r) ? 'Open' : 'Resolved'; }, cell: function (r) { return h('span', { class: 'chip' + (isOpen(r) ? ' on' : ''), 'data-status': isOpen(r) ? 'open' : 'resolved' }, isOpen(r) ? 'Open' : 'Resolved'); } },
        write ? actions(function (r) {
          const open = isOpen(r);
          return h('button', { type: 'button', class: 'small', 'data-act': open ? 'resolve' : 'reopen', onclick: function () { setStatus(r, open ? 'resolved' : 'open'); } }, open ? 'Resolve' : 'Reopen');
        }) : null,
      ].filter(Boolean),
    });
    const list = listState(dt);
    function done(rows) {
      list.done(rows);
      const nOpen = rows.filter(isOpen).length;
      summary.textContent = rows.length ? nOpen + ' open \u00b7 ' + rows.length + ' total' : '';
    }
    function load() {
      list.busy();
      const wantAll = all;
      const p = wantAll
        ? apiCall(ctx, 'GET', 'api/v2/suggestions').then(function (r) { return ((r && r.items) || []).map(function (x) { return Object.assign({ project: x.project || ctx.project }, x); }); })
        // an older server ignores ?kind= and returns every report; only suggestions are shown
        : ctx.api.problems(ctx.project, { kind: 'suggestion' }).then(function (r) { return ((r && r.problems) || []).filter(function (x) { return x.kind === 'suggestion'; }).map(function (x) { return Object.assign({ project: ctx.project }, x); }); });
      return p.then(function (rows) { if (!destroyed && wantAll === all) done(rows); }, function (e) {
        if (destroyed || wantAll !== all) return;
        if (isMissing(e)) done([]);
        else list.fail(actErr('Could not load the suggestions', e), load);
      });
    }
    load();
    return {
      nodes: [
        h('div', { class: 'adm-sec-head adm-sug-head' }, [
          h('h3', null, 'Suggestions'),
          h('label', { class: 'chk adm-sug-all', for: 'adm-sug-all' }, [allBox, 'All projects']),
          summary,
        ]),
        h('p', { class: 'muted' }, 'Ideas and requests people send from the user menu. Resolve them when done; the sender is named so you can follow up.'),
        host,
      ],
      tables: [dt], primary: dt,
    };
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
    // `where` shows a failure (err, retry) beside the control that started the restore.
    function restore(b, where) {
      const n = (b.projects || []).length;
      return confirmScope(ctx, { verb: 'Restore', noun: 'backup ' + b.name, danger: true, ok: 'Replace everything',
        detail: 'Every project, user account and custom template on this server is replaced with the backup\u2019s ' + n + ' project' + (n === 1 ? '' : 's')
          + (b.created ? ' from ' + fmtTime(b.created) : '') + '. A "pre-restore" backup of the current data is taken first, so you can undo this. You may need to sign in again afterwards.' })
        .then(function (y) { return y ? doRestore(b, where) : false; });
    }
    function doRestore(b, where) {
      ctx.toast('Restoring ' + b.name + '\u2026', 'ok');
      const flush = ctx.flush ? ctx.flush() : Promise.resolve();
      return flush.then(function () { return ctx.api.restoreBackup(b.name); }).then(function (r) {
        ctx.toast('Restored ' + b.name + (r.pre_restore_backup ? '. Previous data saved as ' + r.pre_restore_backup : '') + '. Reloading\u2026', 'ok');
        setTimeout(function () { location.reload(); }, 1500);
        return true;
      }, function (e) {
        if (destroyed) return false;
        (where || failList)(actErr('Could not restore ' + b.name, e), function () { return doRestore(b, where); });
        return false;
      });
    }
    function failList(err, retry) { list.fail(err, retry); }
    function removeBackup(b) {
      return ctx.api.deleteBackup(b.name).then(function () { list.clear(); return load(); }, function (e) {
        if (!destroyed) list.fail(actErr('Could not delete ' + b.name, e), function () { return removeBackup(b); });
      });
    }
    function kindOf(b) { return b.error ? 'unreadable' : (b.kind === 'pre-restore' ? 'before a restore' : (/-uploaded(-\d+)?\.zip$/.test(b.name) ? 'uploaded' : (b.kind || ''))); }
    const dt = createTable(host, {
      key: 'settings.backups', scope: '', caption: 'Backups on this server', noun: { one: 'backup', many: 'backups' },
      url: urlBinding(ctx), highlight: hlOf(ctx), csvName: 'backups.csv', rowId: function (b) { return b.name; },
      rowAttrs: function (b) { return { 'data-backup': b.name }; },
      empty: 'No backups on this server yet. Back up now creates one; uploaded backups show up here too.',
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
              confirmScope(ctx, { verb: 'Delete', noun: 'backup ' + b.name, danger: true, detail: 'It is removed from this server; downloaded copies are not affected.' }).then(function (y) {
                if (y) removeBackup(b);
              });
            } }, 'Delete'),
          ];
        }),
      ],
    });
    const list = listState(dt);
    function load() {
      list.busy();
      return ctx.api.backups().then(function (r) { if (!destroyed) list.done((r && r.backups) || []); }, function (e) { if (!destroyed) list.fail(e, load); });
    }

    const label = h('input', { placeholder: 'note (optional), e.g. before Easter changes', 'aria-label': 'Backup note' });
    const builds = h('input', { type: 'checkbox', id: 'bk-builds' });
    const create = h('button', { type: 'button', class: 'primary' }, 'Back up now');
    const createErr = errSlot();
    const backUp = function () {
      create.disabled = true;
      create.textContent = 'Backing up\u2026';
      createErr.clear();
      const flush = ctx.flush ? ctx.flush() : Promise.resolve();
      return flush.then(function () { return ctx.api.createBackup({ label: label.value.trim(), include_builds: builds.checked }); }).then(function (r) {
        const b = r.backup || {};
        ctx.toast('Backup ' + b.name + ' created (' + fmtSize(b.size) + '); downloading a copy', 'ok');
        label.value = '';
        download(b.name);
        load().then(function () { dt.setHighlight(b.name); });
      }, function (e) { if (!destroyed) createErr.show(actErr('Backup failed', e), backUp); }).then(function () { create.disabled = false; create.textContent = 'Back up now'; });
    };
    create.addEventListener('click', backUp);

    const file = h('input', { type: 'file', accept: '.zip,application/zip', 'aria-label': 'Backup file' });
    const upload = h('button', { type: 'button', class: 'danger' }, 'Upload and restore\u2026');
    const uploadErr = errSlot();
    const uploadRestore = function () {
      const f = file.files && file.files[0];
      if (!f) { ctx.toast('Choose a backup .zip first', 'warn'); return null; }
      if (maxMb && f.size > maxMb * 1024 * 1024) { uploadErr.show(new Error('That file is larger than the ' + maxMb + ' MB limit (FATHOM_MAX_BACKUP_MB)'), null); return null; }
      upload.disabled = true;
      upload.textContent = 'Uploading\u2026';
      uploadErr.clear();
      return ctx.api.uploadBackup(f).then(function (r) {
        file.value = '';
        load();
        return restore(r.backup || {}, uploadErr.show);
      }, function (e) { if (!destroyed) uploadErr.show(actErr('Could not upload ' + f.name, e), uploadRestore); }).then(function () { upload.disabled = false; upload.textContent = 'Upload and restore\u2026'; });
    };
    upload.addEventListener('click', uploadRestore);

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
            createErr.el,
          ]),
          h('section', { class: 'adm-card', 'data-card': 'restore' }, [
            h('h3', null, 'Restore from a file'),
            h('p', { class: 'muted' }, 'Upload a backup .zip saved earlier (from this server or another one). You confirm before anything is replaced.'),
            h('div', { class: 'row' }, [file, upload]),
            uploadErr.el,
          ]),
        ]),
        h('h3', null, 'Backups on this server'),
        host,
      ],
      tables: [dt], primary: dt,
    };
  }

  // Settings › Trash (admin): projects moved to the trash, with Restore and Delete permanently.
  function trashPanel() {
    if (!ctx.api || !ctx.api.listTrash) return needsServer();
    const host = h('div');
    let retention = null;
    function retentionText() {
      return retention ? 'Deleted projects are kept for ' + retention + ' day' + (retention === 1 ? '' : 's') + '.' : 'Deleted projects are kept here until an admin deletes them permanently.';
    }
    function restoreProject(t) {
      return ctx.api.restoreTrash(t.name).then(function () {
        ctx.toast('Restored ' + t.name, 'ok');
        if (ctx.reloadProjects) ctx.reloadProjects();
        list.clear();
        return load();
      }, function (e) {
        if (!destroyed) list.fail(actErr('Could not restore ' + t.name, e), function () { return restoreProject(t); });
      });
    }
    function purgeProject(t) {
      return ctx.api.purgeTrash(t.name).then(function () {
        ctx.toast('Deleted ' + t.name + ' permanently', 'ok');
        list.clear();
        return load();
      }, function (e) {
        if (!destroyed) list.fail(actErr('Could not delete ' + t.name, e), function () { return purgeProject(t); });
      });
    }
    const dt = createTable(host, {
      key: 'settings.trash', scope: '', caption: 'Trash', noun: { one: 'project', many: 'projects' },
      url: urlBinding(ctx), highlight: hlOf(ctx), csvName: 'trash.csv', rowId: function (t) { return t.name; },
      rowAttrs: function (t) { return { 'data-trash': t.name }; },
      empty: emptyFor(function () { return dt; }, function () { return { title: 'Nothing in the trash.', text: retentionText() }; }),
      columns: [
        { key: 'name', header: 'Project', cell: function (t) { return mono(t.name); }, sticky: true },
        timeCol('trashed_at', 'Trashed', function (t) { return t.trashed_at; }),
        { key: 'trashed_by', header: 'By', hideOnMobile: true, value: function (t) { return t.trashed_by || ''; } },
        { key: 'rooms', header: 'Rooms', align: 'right', hideOnMobile: true, value: function (t) { return Number(t.rooms) || 0; } },
        { key: 'devices', header: 'Devices', align: 'right', value: function (t) { return Number(t.devices) || 0; } },
        actions(function (t) {
          return [
            h('button', { type: 'button', class: 'small', 'data-act': 'restore', 'aria-label': 'Restore ' + t.name, onclick: function () { restoreProject(t); } }, 'Restore'),
            h('button', { type: 'button', class: 'small danger', 'data-act': 'purge', 'aria-label': 'Delete ' + t.name + ' permanently', onclick: function () {
              confirmScope(ctx, { verb: 'Delete permanently', noun: 'project ' + t.name, danger: true, ok: 'Delete permanently',
                detail: 'The project, its history and its files are removed from this server for good. Backups are not affected.' }).then(function (y) {
                if (y) purgeProject(t);
              });
            } }, 'Delete permanently'),
          ];
        }),
      ],
    });
    const list = listState(dt);
    const note = h('p', { class: 'muted adm-trash-note' }, retentionText());
    function load() {
      list.busy();
      return ctx.api.listTrash().then(function (r) {
        if (destroyed) return;
        const days = Number(r && r.retention_days);
        retention = days > 0 ? days : null;
        note.textContent = retentionText();
        list.done((r && r.items) || []);
      }, function (e) { if (!destroyed) list.fail(e, load); });
    }
    load();
    return {
      nodes: [
        h('section', { class: 'adm-card', 'data-card': 'trash' }, [
          h('h3', null, 'Trash'),
          h('p', { class: 'muted' }, 'Projects moved to the trash from Settings › Project can be restored here with their history and files. ' + 'Deleting permanently cannot be undone.'),
          note,
        ]),
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
          return h('button', { type: 'button', class: 'small danger', onclick: function () {
            confirmScope(ctx, { verb: 'Revoke', noun: 'share link ' + (s.label ? '\u201c' + s.label + '\u201d' : 's/' + String(s.token).slice(0, 8) + '\u2026'), danger: true, ok: 'Revoke',
              detail: 'Anyone using it loses access at once. QR labels printed with it stop working.' }).then(function (y) { if (y) revoke(s); });
          } }, 'Revoke');
        }) : null,
      ].filter(Boolean),
    });
    const list = listState(dt);
    function load() {
      list.busy();
      return ctx.api.shares(ctx.project).then(function (r) { if (!destroyed) list.done((r && r.shares) || []); }, function (e) { if (!destroyed) list.fail(actErr('Share links are not available', e), load); });
    }
    function revoke(s) {
      return ctx.api.deleteShare(ctx.project, s.token).then(function () { list.clear(); return load(); }, function (e) {
        if (!destroyed) list.fail(actErr('Could not revoke ' + (s.label || 'the link'), e), function () { return revoke(s); });
      });
    }
    const create = write ? h('button', { type: 'button', class: 'primary adm-new-share', onclick: function () {
      shareWizard(ctx, function (r) {
        if (r && r.url && navigator.clipboard) navigator.clipboard.writeText(new URL(r.url, ctx.appRoot || location.href).href).then(null, function () { /* no clipboard permission */ });
        load().then(function () { if (r && r.share) dt.setHighlight(r.share.token); });
      });
    } }, 'New share link') : null;
    load();
    return {
      nodes: [h('h3', null, 'Read-only share links'), h('p', { class: 'muted' }, 'Anyone with the link can view maps, patch tables and device pages (or only procedures). Revoke it any time.'), create ? h('div', { class: 'row adm-addrow' }, create) : null, host],
      tables: [dt], primary: dt,
    };
  }

  // Settings › Assistant (P4C, admin): the language model behind the Helper. Reads the provider
  // catalogue and the saved settings from the P4A endpoints; a server without them (404) shows a
  // note instead of the form. Fields the server marks `source: env` are disabled with a hint.
  function assistantPanel() {
    if (!ctx.api || !ctx.api.llmProviders) return needsServer();
    const host = h('div', { class: 'adm-llm', 'data-card': 'llm-host' });
    const state = h('div', { class: 'adm-state', 'aria-live': 'polite' });
    host.appendChild(state);
    state.appendChild(skeleton('cards', 2));
    let providers = [];
    let settings = null;
    let clearKey = false;
    let lastDefault = '';

    function providerOf(id) { return providers.filter(function (p) { return p.id === id; })[0] || null; }
    function labelOf(p) { return p.label || LLM_LABELS[p.id] || p.id; }
    function fromEnv(field) { return !!(settings && settings.source && settings.source[field] === 'env'); }
    function envHint(field) { return h('div', { class: 'muted adm-llm-env', 'data-env': field }, 'Set by environment (' + (LLM_ENV[field] || ('FATHOM_LLM_' + field.toUpperCase())) + ')'); }
    function field(label, input, key, extra) {
      const wrap = fld(label, h('div', { class: 'adm-llm-field' }, [input].concat(extra || [])));
      if (key && fromEnv(key)) {
        input.disabled = true;
        wrap.classList.add('adm-llm-from-env');
        wrap.lastChild.appendChild(envHint(key));
      }
      return wrap;
    }
    function presetsOf(p) {
      const given = (p && p.presets) || {};
      return LLM_PRESETS.map(function (x) { return { id: x[0], label: x[1], url: given[x[0]] || x[2] }; });
    }

    function form() {
      const s = settings || {};
      const provSel = h('select', { id: 'adm-llm-provider', 'aria-label': 'Provider' }, providers.map(function (p) { return h('option', { value: p.id, selected: p.id === s.provider ? true : null }, labelOf(p)); }));
      if (!providerOf(s.provider) && providers.length) provSel.value = providers[0].id;
      const url = h('input', { id: 'adm-llm-url', type: 'url', inputmode: 'url', autocomplete: 'off', spellcheck: 'false', placeholder: 'https://…', value: s.base_url || '' });
      const presets = h('div', { class: 'row adm-llm-presets', role: 'group', 'aria-label': 'Local server presets' });
      const key = h('input', { id: 'adm-llm-key', type: 'password', autocomplete: 'new-password', placeholder: s.api_key_set ? 'Stored' : 'Paste the API key', 'aria-label': 'API key' });
      const keyClear = h('button', { type: 'button', class: 'small ghost adm-llm-clear-key', 'data-act': 'clear-key' }, 'Clear key');
      const keyState = h('span', { class: 'muted adm-llm-key-state' }, s.api_key_set ? 'A key is stored; typing replaces it.' : 'No key stored.');
      const apiSel = h('select', { id: 'adm-llm-api', 'aria-label': 'OpenAI API' }, [['chat', 'Chat Completions'], ['responses', 'Responses']].map(function (o) { return h('option', { value: o[0], selected: (s.api || 'chat') === o[0] ? true : null }, o[1]); }));
      const model = h('input', { id: 'adm-llm-model', list: 'adm-llm-models', autocomplete: 'off', spellcheck: 'false', placeholder: 'e.g. gpt-4o-mini', value: s.model || '' });
      const models = h('datalist', { id: 'adm-llm-models' });
      const fetchBtn = h('button', { type: 'button', class: 'small', 'data-act': 'fetch-models' }, 'Fetch models');
      const modelsErr = errSlot('adm-llm-models-err');
      const temp = h('input', { id: 'adm-llm-temp', type: 'number', inputmode: 'decimal', step: '0.1', min: '0', max: '2', value: s.temperature === undefined || s.temperature === null ? '' : String(s.temperature) });
      const maxTok = h('input', { id: 'adm-llm-max', type: 'number', inputmode: 'numeric', step: '1', min: '1', value: s.max_tokens === undefined || s.max_tokens === null ? '' : String(s.max_tokens) });
      const testBtn = h('button', { type: 'button', 'data-act': 'test' }, 'Test connection');
      const testOut = h('span', { class: 'adm-llm-test-out', role: 'status', 'aria-live': 'polite' });
      const web = h('input', { type: 'checkbox', id: 'adm-llm-web' });
      web.checked = !!s.web_lookup;
      const cap = h('input', { id: 'adm-llm-cap', type: 'number', inputmode: 'numeric', step: '1', min: '0', value: s.daily_cap === undefined || s.daily_cap === null ? '' : String(s.daily_cap) });
      const save = h('button', { type: 'button', class: 'primary', 'data-act': 'save' }, 'Save');
      const saveErr = errSlot('adm-llm-save-err');
      const saved = h('span', { class: 'muted adm-llm-saved', role: 'status' });

      const urlField = field('Base URL', url, 'base_url', [presets]);
      const keyField = field('API key', key, 'api_key', [h('div', { class: 'row adm-llm-key-row' }, [keyState, keyClear])]);
      const apiField = field('API', apiSel, 'api');
      const modelField = field('Model', model, 'model', [models, h('div', { class: 'row adm-llm-model-row' }, [fetchBtn]), modelsErr.el]);

      function drawPresets(p) {
        presets.innerHTML = '';
        presets.hidden = !p || p.id !== 'openai_compat';
        if (presets.hidden) return;
        presetsOf(p).forEach(function (x) {
          presets.appendChild(h('button', { type: 'button', class: 'chip adm-llm-preset', 'data-preset': x.id, title: x.url, disabled: url.disabled ? true : null, onclick: function () {
            url.value = x.url;
            lastDefault = x.url;
            url.dispatchEvent(new Event('input', { bubbles: true }));
          } }, x.label));
        });
      }
      function syncProvider(initial) {
        const p = providerOf(provSel.value);
        const def = (p && p.default_base_url) || '';
        if (!url.disabled && (initial ? !url.value : (!url.value.trim() || url.value.trim() === lastDefault))) url.value = def;
        lastDefault = def;
        drawPresets(p);
        apiField.hidden = !p || p.id !== 'openai';
        const needsKey = !p || p.needs_key !== false;
        keyField.classList.toggle('adm-llm-optional', !needsKey);
        key.placeholder = s.api_key_set ? 'Stored' : (needsKey ? 'Paste the API key' : 'Optional for a local server');
        fetchBtn.disabled = !(p && p.lists_models) || model.disabled;
        fetchBtn.title = p && p.lists_models ? '' : 'This provider does not list its models; type the model name.';
        keyClear.hidden = !s.api_key_set || clearKey || key.disabled;
      }
      provSel.addEventListener('change', function () { syncProvider(false); testOut.textContent = ''; });
      keyClear.addEventListener('click', function () {
        clearKey = true;
        key.value = '';
        key.placeholder = 'Paste the API key';
        keyState.textContent = 'The stored key is removed when you save.';
        keyClear.hidden = true;
      });
      key.addEventListener('input', function () { if (key.value) { clearKey = false; keyState.textContent = 'The new key is saved when you save.'; } });
      // only a typed key travels; an untouched field keeps the stored one
      function keyBody() {
        const out = {};
        if (fromEnv('api_key')) return out;
        if (key.value) out.api_key = key.value;
        else if (clearKey) out.clear_api_key = true;
        return out;
      }
      function connBody() {
        return Object.assign({ provider: provSel.value, base_url: url.value.trim() }, key.value ? { api_key: key.value } : {});
      }
      fetchBtn.addEventListener('click', function () {
        modelsErr.clear();
        fetchBtn.disabled = true;
        fetchBtn.textContent = 'Fetching\u2026';
        ctx.api.llmModels(connBody()).then(function (r) {
          const list = (r && r.models) || [];
          models.innerHTML = '';
          list.forEach(function (mname) { models.appendChild(h('option', { value: typeof mname === 'string' ? mname : (mname && mname.id) || '' })); });
          if (!list.length) modelsErr.show({ message: 'The server listed no models.', status: 200 }, null);
          else if (!model.value) model.value = typeof list[0] === 'string' ? list[0] : (list[0].id || '');
          model.setAttribute('data-models', String(list.length));
        }, function (e) {
          if (!destroyed) modelsErr.show(actErr('Could not fetch the models', e), null);
        }).then(function () { if (destroyed) return; fetchBtn.disabled = false; fetchBtn.textContent = 'Fetch models'; });
      });
      testBtn.addEventListener('click', function () {
        testBtn.disabled = true;
        testBtn.setAttribute('aria-busy', 'true');
        testOut.className = 'adm-llm-test-out';
        testOut.innerHTML = '';
        testOut.appendChild(h('span', { class: 'adm-llm-spin', 'aria-hidden': 'true' }));
        testOut.appendChild(document.createTextNode(' Testing\u2026'));
        ctx.api.llmTest(Object.assign(connBody(), { model: model.value.trim() })).then(function (r) {
          if (destroyed) return;
          r = r || {};
          const ok = r.ok !== false;
          testOut.className = 'adm-llm-test-out ' + (ok ? 'ok' : 'warn');
          testOut.setAttribute('data-ok', ok ? 'true' : 'false');
          testOut.textContent = ok
            ? 'OK' + (r.model ? ' \u00b7 ' + r.model : '') + (typeof r.latency_ms === 'number' ? ' \u00b7 ' + Math.round(r.latency_ms) + ' ms' : '')
            : 'Failed' + (r.detail ? ' \u00b7 ' + r.detail : '');
        }, function (e) {
          if (destroyed) return;
          testOut.className = 'adm-llm-test-out warn';
          testOut.setAttribute('data-ok', 'false');
          testOut.textContent = 'Failed \u00b7 ' + msg(e);
        }).then(function () { if (destroyed) return; testBtn.disabled = false; testBtn.removeAttribute('aria-busy'); });
      });
      function num(input, integer) {
        const v = input.value.trim();
        if (v === '') return null;
        const n = Number(v);
        if (isNaN(n)) return null;
        return integer ? Math.round(n) : n;
      }
      function body() {
        const out = {};
        const put = function (k, v) { if (!fromEnv(k)) out[k] = v; };
        put('provider', provSel.value);
        put('base_url', url.value.trim());
        put('model', model.value.trim());
        if (provSel.value === 'openai') put('api', apiSel.value);
        put('temperature', num(temp, false));
        put('max_tokens', num(maxTok, true));
        put('web_lookup', web.checked);
        put('daily_cap', num(cap, true));
        return Object.assign(out, keyBody());
      }
      const doSave = function () {
        saveErr.clear();
        saved.textContent = '';
        save.disabled = true;
        return ctx.api.saveLlmSettings(body()).then(function (r) {
          if (destroyed) return;
          settings = r && r.provider ? r : Object.assign({}, settings, body(), { api_key_set: key.value ? true : (clearKey ? false : s.api_key_set) });
          clearKey = false;
          key.value = '';
          s.api_key_set = settings.api_key_set;
          key.placeholder = s.api_key_set ? 'Stored' : 'Paste the API key';
          keyState.textContent = s.api_key_set ? 'A key is stored; typing replaces it.' : 'No key stored.';
          keyClear.hidden = !s.api_key_set;
          saved.textContent = 'Saved';
          ctx.toast('Assistant settings saved', 'ok');
        }, function (e) { if (!destroyed) saveErr.show(actErr('Could not save the assistant settings', e), doSave); }).then(function () { if (!destroyed) save.disabled = false; });
      };
      save.addEventListener('click', doSave);
      syncProvider(true);

      const llmCard = h('section', { class: 'adm-card adm-form adm-llm-card', 'data-card': 'llm' }, [
        h('h3', null, 'Language model'),
        h('p', { class: 'muted adm-llm-intro' }, 'The Helper answers from the project data on its own. A model adds plain-language notes and proposals; nothing is applied without a click.'),
        field('Provider', provSel, 'provider'),
        urlField,
        keyField,
        apiField,
        modelField,
        field('Temperature', temp, 'temperature'),
        field('Max tokens', maxTok, 'max_tokens'),
        h('div', { class: 'row adm-llm-test-row' }, [testBtn, testOut]),
      ]);
      const behaviourCard = h('section', { class: 'adm-card adm-form adm-llm-card', 'data-card': 'behaviour' }, [
        h('h3', null, 'Behaviour'),
        field('Web lookup for manuals', h('label', { class: 'chk adm-llm-toggle', for: 'adm-llm-web' }, [web, h('span', null, 'Let the model look up equipment manuals online')]), 'web_lookup',
          [h('div', { class: 'muted adm-llm-hint' }, 'When off, the assistant never contacts the internet.')]),
        field('Daily request cap', cap, 'daily_cap', [h('div', { class: 'muted adm-llm-hint' }, 'Model requests per day for this server; 0 or empty means no cap.')]),
      ]);
      return [
        h('div', { class: 'adm-grid adm-llm-grid' }, [llmCard, behaviourCard]),
        h('div', { class: 'row adm-llm-actions' }, [save, saved]),
        saveErr.el,
      ];
    }

    function load() {
      state.innerHTML = '';
      state.appendChild(skeleton('cards', 2));
      return Promise.all([ctx.api.llmProviders(), ctx.api.llmSettings()]).then(function (r) {
        if (destroyed) return;
        providers = ((r[0] && r[0].providers) || []).filter(function (p) { return p && p.id; });
        settings = r[1] || {};
        state.innerHTML = '';
        if (!providers.length) {
          host.appendChild(h('p', { class: 'muted adm-llm-missing' }, 'This server lists no language-model providers.'));
          return;
        }
        form().forEach(function (n) { host.appendChild(n); });
      }, function (e) {
        if (destroyed) return;
        state.innerHTML = '';
        if (isMissing(e)) {
          host.appendChild(h('section', { class: 'adm-card', 'data-card': 'llm-missing' }, [h('h3', null, 'Language model'),
            h('p', { class: 'muted adm-llm-missing' }, 'This server has no language-model settings yet (it needs a newer Fathom). The Helper keeps answering from the project data; a model can be set with FATHOM_LLM_URL and FATHOM_LLM_MODEL.')]));
          return;
        }
        state.appendChild(inlineError(actErr('Could not load the assistant settings', e), load));
      });
    }
    load();
    return { nodes: [h('h3', null, 'Assistant'), host], tables: [] };
  }

  function offlinePanel() {
    const secure = window.isSecureContext && 'serviceWorker' in navigator;
    return { nodes: [
      h('h3', null, 'Offline'),
      secure ? h('p', null, 'Viewer pages and this project can be saved on this device for the booth or catwalk. Use "Make available offline" from the user menu (top right).') : h('p', { style: { color: 'var(--warn)' } }, 'Offline mode needs HTTPS (or localhost). On a plain http:// LAN address the browser does not allow it.'),
      h('p', { class: 'muted' }, 'Edits made while offline are kept on this device and sent when the connection comes back.'),
    ], tables: [] };
  }

  const PANELS = { project: projectPanel, rooms: roomsPanel, systems: systemsPanel, locations: locationsPanel, networks: networksPanel, templates: templatesPanel, users: usersPanel, invites: invitesPanel, backups: backupsPanel, sharing: sharingPanel, suggestions: suggestionsPanel, assistant: assistantPanel, offline: offlinePanel, trash: trashPanel };

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
