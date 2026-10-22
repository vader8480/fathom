// Device merge UI: duplicate suggestions and the side-by-side merge preview.
// The server computes suggestions (/devices/duplicates) and the merge plan
// (/devices/merge/preview); the ops are applied through ctx.commit so the
// merge is one undoable step locally and one revision on the server.
// No imports: used by the inspector and the inventory view alike.

function h(tag, attrs, children) {
  const el = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (v === undefined || v === null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
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

function errMsg(e) {
  if (!e) return 'unknown error';
  if (typeof e === 'string') return e;
  return e.message || (e.data && e.data.error) || String(e);
}

function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }

export function formatValue(v) {
  if (v === null || v === undefined || v === '') return '';
  if (v === true) return 'yes';
  if (v === false) return 'no';
  if (Array.isArray(v)) return v.map(function (x) { return typeof x === 'object' ? JSON.stringify(x) : String(x); }).join(', ');
  if (typeof v === 'object') {
    if (v.id !== undefined && v.u !== undefined) return v.id + ' \u00b7 U' + v.u + (v.height ? ' (' + v.height + 'U)' : '') + (v.face ? ' \u00b7 ' + v.face : '');
    return Object.keys(v).filter(function (k) { return v[k] !== null && v[k] !== undefined && v[k] !== ''; })
      .map(function (k) { return k + ': ' + formatValue(v[k]); }).join(' \u00b7 ');
  }
  return String(v);
}

function confidencePill(conf) {
  const color = conf === 'high' ? 'var(--ok)' : (conf === 'medium' ? 'var(--warn)' : 'var(--muted)');
  return h('span', { class: 'pill mg-conf', style: { color: color } }, conf);
}

function deviceLabel(d) {
  const bits = [];
  if (d.kind) bits.push(d.kind);
  if (d.room) bits.push(d.room);
  if (d.auto) bits.push((d.source || 'import') + ' import');
  return bits.join(' \u00b7 ');
}

// ----------------------------------------------------------- suggestions

const CACHE = {};
const TTL = 20000;

export function fetchDuplicates(ctx, opts) {
  opts = opts || {};
  if (!ctx.api || !ctx.project) return Promise.resolve([]);
  const key = ctx.project + '|' + (opts.device || '*') + '|' + (opts.min || '');
  const hit = CACHE[key];
  const now = Date.now();
  if (hit && !opts.force && now - hit.at < TTL) return hit.p;
  const p = ctx.api.duplicates(ctx.project, { device: opts.device, min: opts.min, limit: opts.limit }).then(function (r) {
    return (r && r.duplicates) || [];
  });
  CACHE[key] = { at: now, p: p };
  p.catch(function () { delete CACHE[key]; });
  return p;
}

export function invalidateDuplicates() { Object.keys(CACHE).forEach(function (k) { delete CACHE[k]; }); }

function suggestionRow(ctx, s, deviceId, onMerged) {
  const other = s.devices[0].id === deviceId ? s.devices[1] : s.devices[0];
  const canMerge = ctx.store && !ctx.store.readOnly && ctx.api;
  const ids = [s.devices[0].id, s.devices[1].id];
  const survivor = s.suggested_survivor;
  const nameBtn = h('button', { type: 'button', class: 'mg-link', title: 'Show ' + other.name, onclick: function () {
    if (other.auto) { ctx.toast(other.name + ' comes from the ' + (other.source || '') + ' import.', 'info'); return; }
    ctx.select({ type: 'device', id: other.id, device: other.id });
  } }, other.name);
  return h('li', { class: 'mg-hint', 'data-device': other.id }, [
    h('div', { class: 'mg-hint-top' }, [
      nameBtn,
      confidencePill(s.confidence),
      h('span', { class: 'muted mg-score' }, Math.round(s.score * 100) + '%'),
      h('span', { class: 'grow' }),
      canMerge ? h('button', { type: 'button', class: 'small', onclick: function () {
        openMergeDialog(ctx, ids, { survivor: survivor }).then(function (done) { if (done && onMerged) onMerged(done); });
      } }, 'Merge\u2026') : null,
    ]),
    h('div', { class: 'muted mg-hint-sub' }, deviceLabel(other)),
    h('ul', { class: 'mg-reasons' }, s.reasons.filter(function (r) { return r.weight > 0.05 || r.weight < 0; }).map(function (r) {
      return h('li', { class: r.weight < 0 ? 'neg' : '' }, r.text);
    })),
  ]);
}

// Element that lists likely duplicates of one device (inspector section).
export function duplicateHints(ctx, deviceId, onMerged) {
  const box = h('div', { class: 'mg-hints' }, h('div', { class: 'muted' }, 'Looking for duplicates\u2026'));
  if (!ctx.api) { box.textContent = ''; box.appendChild(h('div', { class: 'muted' }, 'Not available offline.')); return box; }
  fetchDuplicates(ctx, { device: deviceId }).then(function (list) {
    box.textContent = '';
    if (!list.length) {
      box.appendChild(h('div', { class: 'muted' }, 'No likely duplicates.'));
    } else {
      box.appendChild(h('ul', { class: 'mg-hint-list' }, list.slice(0, 5).map(function (s) { return suggestionRow(ctx, s, deviceId, onMerged); })));
      if (list.length > 5) box.appendChild(h('div', { class: 'muted' }, 'and ' + (list.length - 5) + ' more'));
    }
    box.appendChild(h('div', { class: 'mg-hint-foot' }, [
      h('button', { type: 'button', class: 'small ghost', onclick: function () {
        invalidateDuplicates();
        const fresh = duplicateHints(ctx, deviceId, onMerged);
        box.replaceWith(fresh);
      } }, 'Re-check'),
      (ctx.store && !ctx.store.readOnly) ? h('button', { type: 'button', class: 'small ghost', onclick: function () {
        pickAndMerge(ctx, deviceId).then(function (done) { if (done && onMerged) onMerged(done); });
      } }, 'Merge with\u2026') : null,
    ]));
  }, function (e) {
    box.textContent = '';
    box.appendChild(h('div', { class: 'muted' }, 'Could not check: ' + errMsg(e)));
  });
  return box;
}

function pickAndMerge(ctx, deviceId) {
  if (!ctx.pickDevice) return Promise.resolve(false);
  return ctx.pickDevice({ title: 'Merge with which device?', exclude: [deviceId] }).then(function (other) {
    if (!other || other === deviceId) return false;
    return openMergeDialog(ctx, [deviceId, other], { survivor: deviceId });
  });
}

// Project-wide list of suggestions with a "Review" button per pair.
export function openDuplicatesDialog(ctx) {
  const body = h('div', { class: 'mg-dups' }, h('div', { class: 'muted' }, 'Scanning devices\u2026'));
  let dialog = null;
  function load(force) {
    body.textContent = '';
    body.appendChild(h('div', { class: 'muted' }, 'Scanning devices\u2026'));
    fetchDuplicates(ctx, { force: force, limit: 100 }).then(function (list) {
      body.textContent = '';
      if (!list.length) { body.appendChild(h('p', { class: 'muted' }, 'No likely duplicates found. Devices are compared by name, model, Dante name, IP / MAC / hostname, serial and rack position.')); return; }
      body.appendChild(h('p', { class: 'muted mg-intro' }, plural(list.length, 'possible duplicate pair') + ', most likely first.'));
      body.appendChild(h('ul', { class: 'mg-hint-list' }, list.map(function (s) {
        const a = s.devices[0];
        const b = s.devices[1];
        return h('li', { class: 'mg-hint' }, [
          h('div', { class: 'mg-hint-top' }, [
            h('span', { class: 'mg-pair' }, [h('b', null, a.name), h('span', { class: 'muted' }, ' \u2194 '), h('b', null, b.name)]),
            confidencePill(s.confidence),
            h('span', { class: 'muted mg-score' }, Math.round(s.score * 100) + '%'),
            h('span', { class: 'grow' }),
            (ctx.store && !ctx.store.readOnly) ? h('button', { type: 'button', class: 'small', onclick: function () {
              openMergeDialog(ctx, [a.id, b.id], { survivor: s.suggested_survivor }).then(function (done) { if (done) load(true); });
            } }, 'Review\u2026') : null,
          ]),
          h('div', { class: 'muted mg-hint-sub' }, deviceLabel(a) + (deviceLabel(b) !== deviceLabel(a) ? '  |  ' + deviceLabel(b) : '')),
          h('ul', { class: 'mg-reasons' }, s.reasons.filter(function (r) { return r.weight > 0.05 || r.weight < 0; }).map(function (r) {
            return h('li', { class: r.weight < 0 ? 'neg' : '' }, r.text);
          })),
        ]);
      })));
    }, function (e) { body.textContent = ''; body.appendChild(h('p', { class: 'muted' }, 'Could not scan: ' + errMsg(e))); });
  }
  load(false);
  return ctx.openDialog({
    title: 'Possible duplicate devices',
    body: body,
    buttons: [{ label: 'Re-scan', value: 'rescan' }, { label: 'Close', value: null, primary: true }],
    onOpen: function (d) {
      dialog = d;
      // "Re-scan" must not close the dialog: intercept the footer button
      const btns = d.box.querySelectorAll('footer button');
      if (btns[0]) {
        const clone = btns[0].cloneNode(true);
        btns[0].replaceWith(clone);
        clone.addEventListener('click', function () { invalidateDuplicates(); load(true); });
      }
    },
  }).then(function () { return dialog; });
}

// ----------------------------------------------------------- merge dialog

function fieldCell(row, dev, state, onChoose) {
  const v = row.values[dev.id];
  const empty = v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length) || (typeof v === 'object' && !Array.isArray(v) && !Object.keys(v).length);
  const picked = row.winner === dev.id;
  const text = empty ? '\u2014' : formatValue(v);
  const cell = h('td', { class: 'mg-val' + (picked ? ' mg-picked' : '') + (empty ? ' mg-empty' : ''), 'data-label': dev.name });
  if (row.overridable && !empty) {
    const id = 'mg-' + row.key.replace(/[^a-z0-9]/gi, '-') + '-' + dev.id.replace(/[^a-z0-9]/gi, '-');
    const radio = h('input', { type: 'radio', name: 'mg-' + row.key, id: id, value: dev.id, checked: picked, 'aria-label': row.label + ' from ' + dev.name, onchange: function () { onChoose(row.key, dev.id); } });
    cell.appendChild(h('label', { for: id, class: 'mg-opt' }, [radio, h('span', { class: 'mg-text', title: text }, text)]));
  } else {
    cell.appendChild(h('span', { class: 'mg-text', title: text }, text));
  }
  return cell;
}

function resultCell(row, onChoose) {
  const v = row.result;
  const empty = v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length);
  const text = empty ? '\u2014' : formatValue(v);
  const combinable = row.overridable && (row.rule === 'list' || row.rule === 'text' || row.rule === 'routing');
  const cell = h('td', { class: 'mg-res', 'data-label': 'Result' }, [
    h('div', { class: 'mg-text' + (empty ? ' mg-empty' : ''), title: text }, text),
    h('div', { class: 'mg-why muted' }, row.reason || ''),
  ]);
  if (combinable) {
    const id = 'mg-' + row.key.replace(/[^a-z0-9]/gi, '-') + '-union';
    cell.appendChild(h('label', { for: id, class: 'mg-opt mg-union' }, [
      h('input', { type: 'radio', name: 'mg-' + row.key, id: id, value: 'union', checked: row.winner === 'union', 'aria-label': 'Combine ' + row.label, onchange: function () { onChoose(row.key, 'union'); } }),
      h('span', null, row.rule === 'text' ? 'Combine texts' : 'Combine all'),
    ]));
  }
  return cell;
}

function refsSummary(plan, survivorName) {
  const r = plan.references || {};
  const bits = [];
  if (r.cables && r.cables.length) bits.push(plural(r.cables.length, 'cable') + ' re-pointed');
  if (r.markers && r.markers.length) bits.push(plural(r.markers.length, 'floor-plan marker') + ' moved');
  if (r.markers_dropped && r.markers_dropped.length) bits.push(plural(r.markers_dropped.length, 'marker') + ' dropped');
  if (r.attachments && r.attachments.length) bits.push(plural(r.attachments.length, 'attachment') + ' re-attached');
  if (r.imports && r.imports.length) bits.push(plural(r.imports.length, 'import') + ' re-attached');
  if (r.extra_cards && r.extra_cards.length) bits.push(plural(r.extra_cards.length, 'map card') + ' updated');
  if (r.switch_links && r.switch_links.length) bits.push(plural(r.switch_links.length, 'switch link') + ' updated');
  const p = plan.ports || {};
  const portBits = [];
  if (p.kept) portBits.push(p.kept + ' kept');
  if (p.unified && p.unified.length) portBits.push(p.unified.length + ' matched');
  if (p.added && p.added.length) portBits.push(p.added.length + ' added');
  if (p.renamed && p.renamed.length) portBits.push(p.renamed.length + ' renamed (' + p.renamed.map(function (x) { return x.port + '\u2192' + x.to; }).join(', ') + ')');
  const i = plan.interfaces || {};
  const itfBits = [];
  if (i.kept) itfBits.push(i.kept + ' kept');
  if (i.unified && i.unified.length) itfBits.push(i.unified.length + ' matched');
  if (i.added && i.added.length) itfBits.push(i.added.length + ' added');
  return h('div', { class: 'mg-refs' }, [
    h('div', null, [h('b', null, 'Ports: '), portBits.length ? portBits.join(', ') : 'none']),
    h('div', null, [h('b', null, 'Interfaces: '), itfBits.length ? itfBits.join(', ') : 'none']),
    h('div', null, [h('b', null, 'References: '), bits.length ? bits.join(', ') + ' \u2192 ' + survivorName : 'nothing else points at the duplicates']),
  ]);
}

export function openMergeDialog(ctx, ids, opts) {
  opts = opts || {};
  ids = (ids || []).filter(function (x, i, a) { return x && a.indexOf(x) === i; });
  if (!ctx.api) { ctx.toast('Merging needs a server connection.', 'warn'); return Promise.resolve(false); }
  if (ids.length < 2) { ctx.toast('Select at least two devices to merge.', 'info'); return Promise.resolve(false); }
  if (ctx.store && ctx.store.readOnly) { ctx.toast('Read-only: devices cannot be merged.', 'warn'); return Promise.resolve(false); }

  const state = { survivor: opts.survivor && ids.indexOf(opts.survivor) >= 0 ? opts.survivor : ids[0], choices: {}, plan: null, onlyDiff: true, busy: false };
  const body = h('div', { class: 'mg' });
  const status = h('div', { class: 'mg-status muted', role: 'status' }, 'Preparing preview\u2026');
  const head = h('div', { class: 'mg-head' });
  const summary = h('div', { class: 'mg-summary' });
  const tableWrap = h('div', { class: 'mg-table-wrap' });
  const tail = h('div', { class: 'mg-tail' });
  body.appendChild(head);
  body.appendChild(status);
  body.appendChild(summary);
  body.appendChild(tableWrap);
  body.appendChild(tail);
  let dlg = null;
  let mergeBtn = null;

  function duplicates() { return ids.filter(function (x) { return x !== state.survivor; }); }

  function preview() {
    state.busy = true;
    status.textContent = state.plan ? 'Updating preview\u2026' : 'Preparing preview\u2026';
    status.hidden = false;
    if (mergeBtn) mergeBtn.disabled = true;
    const flush = ctx.flush ? ctx.flush() : Promise.resolve();
    return Promise.resolve(flush).catch(function () { return null; }).then(function () {
      return ctx.api.mergePreview(ctx.project, state.survivor, duplicates(), state.choices);
    }).then(function (plan) {
      state.plan = plan;
      state.busy = false;
      status.hidden = true;
      render();
      if (mergeBtn) mergeBtn.disabled = false;
      return plan;
    }, function (e) {
      state.busy = false;
      status.hidden = false;
      status.textContent = 'Preview failed: ' + errMsg(e);
      render();
      return null;
    });
  }

  function choose(key, who) {
    state.choices[key] = who;
    preview();
  }

  function renderHead() {
    head.textContent = '';
    const devs = state.plan ? state.plan.devices : ids.map(function (id) { return { id: id, name: id }; });
    const group = h('div', { class: 'mg-keep', role: 'radiogroup', 'aria-label': 'Device to keep' }, [h('span', { class: 'mg-keep-lbl' }, 'Keep')]);
    const ordered = devs.slice().sort(function (a, b) { return ids.indexOf(a.id) - ids.indexOf(b.id); });
    ordered.forEach(function (d) {
      const id = 'mg-keep-' + d.id.replace(/[^a-z0-9]/gi, '-');
      const disabled = !!d.auto;
      group.appendChild(h('label', { class: 'chip mg-keep-opt' + (state.survivor === d.id ? ' on' : '') + (disabled ? ' off' : ''), for: id, title: disabled ? 'Import-only devices cannot be the survivor' : '' }, [
        h('input', { type: 'radio', name: 'mg-keep', id: id, value: d.id, checked: state.survivor === d.id, disabled: disabled, onchange: function () {
          state.survivor = d.id;
          state.choices = {};
          preview();
        } }),
        h('span', null, d.name),
        d.auto ? h('span', { class: 'muted' }, ' (' + (d.source || 'import') + ')') : null,
      ]));
    });
    head.appendChild(group);
    head.appendChild(h('p', { class: 'muted mg-explain' }, 'The kept device wins every field it has a value for; blanks are filled from the duplicates, lists are combined and notes concatenated. Pick a different value where they disagree.'));
  }

  function render() {
    renderHead();
    summary.textContent = '';
    tableWrap.textContent = '';
    tail.textContent = '';
    const plan = state.plan;
    if (!plan) return;
    const survivor = plan.devices[0];
    const rows = plan.fields || [];
    const conflicts = rows.filter(function (r) { return r.conflict; });
    const diffRows = rows.filter(function (r) {
      const present = Object.keys(r.values).filter(function (k) { const v = r.values[k]; return !(v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length)); });
      if (present.length === 1) return present[0] !== survivor.id;
      const seen = {};
      present.forEach(function (k) { seen[JSON.stringify(r.values[k])] = true; });
      return Object.keys(seen).length > 1;
    });
    const onlyToggle = h('label', { class: 'chip mg-toggle' + (state.onlyDiff ? ' on' : '') }, [
      h('input', { type: 'checkbox', checked: state.onlyDiff, onchange: function (e) { state.onlyDiff = e.target.checked; render(); } }),
      'Only differences (' + diffRows.length + ')',
    ]);
    summary.appendChild(h('div', { class: 'row mg-chips' }, [
      h('span', { class: 'chip' }, plural(plan.duplicates.length, 'duplicate') + ' \u2192 ' + survivor.name),
      h('span', { class: 'chip' + (conflicts.length ? ' mg-warnchip' : '') }, plural(conflicts.length, 'conflict')),
      h('span', { class: 'chip', title: 'Applied together as one undoable revision' }, plural((plan.ops || []).length, 'change op') + ' \u00b7 1 revision'),
      h('span', { class: 'grow' }),
      onlyToggle,
    ]));
    const shown = state.onlyDiff ? diffRows : rows;
    const cols = plan.devices;
    const table = h('table', { class: 'mg-table' });
    table.appendChild(h('thead', null, h('tr', null, [h('th', { scope: 'col' }, 'Field')].concat(cols.map(function (d, i) {
      return h('th', { scope: 'col', class: i === 0 ? 'mg-col-keep' : '' }, [d.name, i === 0 ? h('span', { class: 'pill mg-keep-pill' }, 'kept') : (d.auto ? h('span', { class: 'pill mg-auto-pill' }, d.source || 'import') : null)]);
    })).concat([h('th', { scope: 'col' }, 'Result')]))));
    const tbody = h('tbody');
    if (!shown.length) tbody.appendChild(h('tr', null, h('td', { colspan: cols.length + 2, class: 'muted mg-none' }, 'The devices do not differ in any field; ports, interfaces and references are combined as listed below.')));
    shown.forEach(function (r) {
      const tr = h('tr', { class: (r.conflict ? 'mg-conflict' : '') + (state.choices[r.key] ? ' mg-chosen' : '') }, [
        h('th', { scope: 'row', class: 'mg-field' }, [r.label, r.conflict ? h('span', { class: 'pill mg-conf-pill' }, 'conflict') : null]),
      ]);
      cols.forEach(function (d) { tr.appendChild(fieldCell(r, d, state, choose)); });
      tr.appendChild(resultCell(r, choose));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    tail.appendChild(refsSummary(plan, survivor.name));
    if (plan.warnings && plan.warnings.length) {
      tail.appendChild(h('ul', { class: 'mg-warnings' }, plan.warnings.map(function (w) { return h('li', null, w); })));
    }
    const hasChoices = Object.keys(state.choices).length > 0;
    if (hasChoices) {
      tail.appendChild(h('button', { type: 'button', class: 'small ghost', onclick: function () { state.choices = {}; preview(); } }, 'Reset my choices'));
    }
  }

  function apply() {
    if (state.busy || !state.plan) return;
    const plan = state.plan;
    const label = plan.summary;
    let p = Promise.resolve(plan);
    if (ctx.store && ctx.store.revision && plan.revision && ctx.store.revision !== plan.revision) p = preview();
    p.then(function (fresh) {
      if (!fresh) return;
      const d = ctx.commit(fresh.ops, label);
      if (!d) return;
      invalidateDuplicates();
      ctx.toast(label + '. Undo with Cmd/Ctrl+Z.', 'ok');
      if (dlg) dlg.close({ survivor: fresh.survivor, duplicates: fresh.duplicates });
      if (ctx.select) ctx.select({ type: 'device', id: fresh.survivor, device: fresh.survivor });
    });
  }

  renderHead();
  return ctx.openDialog({
    title: 'Merge devices',
    wide: true,
    body: body,
    buttons: [{ label: 'Cancel', value: null }, { label: 'Merge', value: 'merge', primary: true }],
    onOpen: function (d) {
      dlg = d;
      d.box.classList.add('mg-dialog');
      const btns = d.box.querySelectorAll('footer button');
      mergeBtn = btns[btns.length - 1];
      if (mergeBtn) {
        const clone = mergeBtn.cloneNode(true);
        mergeBtn.replaceWith(clone);
        mergeBtn = clone;
        mergeBtn.disabled = true;
        mergeBtn.addEventListener('click', apply);
      }
      preview();
    },
  }).then(function (v) { return v && typeof v === 'object' ? v : false; });
}
