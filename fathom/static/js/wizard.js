// Step-by-step dialogs and bulk add (docs/ui-audit.md B.2 WIZARD).
//
// openWizard(ctx, spec) shows div.wz[role=dialog]: a step list, the active
// step's body and a footer (Back, Next or Submit). Next stays disabled while
// the step's validate() returns errors, which show inline under their field
// (matched by name or data-field) through aria-describedby. After Review and
// Submit a Result step offers a link. Esc, × and the backdrop ask before
// discarding entered data.
//
// bulkAdd(ctx, {kind, room}) is the paste → map → preview → review → result
// wizard for devices or cables. It writes through one ctx.commit(ops, label),
// so the change goes through the store's existing patch queue as one undo step.
import { h, on } from './dom.js';
import { buildRoute, mergeRoute } from './router-core.js';
import { createTable } from './datatable.js';
import { inlineError } from './feedback.js';
import {
  fieldsFor, parsePasted, guessMapping, looksLikeHeader, mappingErrors, rowObject, validateRows,
  bulkDeviceOps, bulkCableOps, replacedCables, resolveRoom, canAdvance, plural,
  reviewText, commitLabel, resultRoute, loadForm, saveForm, applyRemembered, rememberMapping, MAX_ROWS,
} from './wizard-core.js';

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
let seq = 0;

function safeStorage() {
  try { return window.localStorage; } catch (e) { return null; }
}

export function rememberForm(key, data) {
  return saveForm(safeStorage(), key, data);
}

export function recallForm(key) {
  return loadForm(safeStorage(), key);
}

function announce(text) {
  const live = document.getElementById('fathom-live');
  if (!live || !text) return;
  live.textContent = '';
  setTimeout(function () { live.textContent = text; }, 30);
}

function errText(err) {
  if (!err) return 'Something went wrong';
  return err.message || String(err);
}

function cssKey(s) {
  return String(s).replace(/[^A-Za-z0-9_-]/g, '_');
}

function visible(el) {
  return !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
}

// ------------------------------------------------------------ openWizard

export function openWizard(ctx, spec) {
  ctx = ctx || {};
  spec = spec || {};
  const css = [];
  if (ctx.ensureCss) {
    css.push(ctx.ensureCss('datatable.css'));
    css.push(ctx.ensureCss('wizard.css'));
  }
  return Promise.all(css).catch(function () { return null; }).then(function () {
    return new Promise(function (resolve) { mountWizard(ctx, spec, resolve); });
  });
}

function mountWizard(ctx, spec, resolve) {
  const uid = 'wz' + (++seq);
  const opener = document.activeElement;
  const data = spec.data || {};
  const steps = (spec.steps || []).slice();
  const all = steps.map(function (s) { return { key: s.key, label: s.label }; })
    .concat([{ key: 'review', label: spec.reviewLabel || 'Review' }, { key: 'result', label: spec.resultLabel || 'Done' }]);
  const REVIEW = steps.length;
  const RESULT = steps.length + 1;
  let index = 0;
  let errors = {};
  let touched = {};
  let showAll = false;
  let dirty = false;
  let busy = false;
  let confirming = false;
  let closed = false;
  let result = null;
  let leave = null;
  const offs = [];

  const title = h('h2', { id: uid + '-title', class: 'wz-title' }, spec.title || '');
  const closeBtn = h('button', { type: 'button', class: 'icon ghost wz-close', 'aria-label': 'Close' }, '\u00d7');
  const stepList = h('ol', { class: 'wz-steps', 'aria-label': 'Steps' });
  const body = h('div', { class: 'wz-body', id: uid + '-body', tabindex: '-1' });
  const footMsg = h('span', { class: 'wz-foot-msg', 'aria-live': 'polite' });
  const backBtn = h('button', { type: 'button', class: 'wz-back' }, 'Back');
  const nextBtn = h('button', { type: 'button', class: 'primary wz-next' }, 'Next');
  const foot = h('div', { class: 'wz-foot' }, [footMsg, backBtn, nextBtn]);
  const box = h('div', { class: 'wz', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': uid + '-title', 'data-wizard': spec.key || '' }, [
    h('header', { class: 'wz-head' }, [title, closeBtn]), stepList, body, foot,
  ]);
  const backdrop = h('div', { class: 'wz-backdrop' }, box);

  all.forEach(function (s, i) {
    stepList.appendChild(h('li', { class: 'wz-step', 'data-step': s.key }, [
      h('span', { class: 'wz-step-n', 'aria-hidden': 'true' }, String(i + 1)),
      h('span', { class: 'wz-step-label' }, s.label),
    ]));
  });

  const api = {
    data: data,
    body: body,
    box: box,
    revalidate: function () { update(); },
    rerender: function () { show(index, true); },
    markDirty: function () { dirty = true; },
    next: function () { goNext(); },
    back: function () { goBack(); },
    close: function () { requestClose(); },
  };

  function fieldEl(key) {
    const sel = '[name="' + key + '"],[data-field="' + key + '"]';
    try { return body.querySelector(sel); } catch (e) { return null; }
  }

  function hasValue(el) {
    if (!el) return false;
    if (el.type === 'checkbox' || el.type === 'radio') return false;
    return el.value !== undefined && String(el.value).trim() !== '';
  }

  function clearFieldErrors() {
    Array.prototype.forEach.call(body.querySelectorAll('.wz-err'), function (p) {
      const id = p.id;
      const el = body.querySelector('[aria-describedby~="' + id + '"]');
      if (el) {
        const rest = (el.getAttribute('aria-describedby') || '').split(/\s+/).filter(function (x) { return x && x !== id; });
        if (rest.length) el.setAttribute('aria-describedby', rest.join(' ')); else el.removeAttribute('aria-describedby');
        el.removeAttribute('aria-invalid');
      }
      p.remove();
    });
    const sum = body.querySelector('.wz-errors');
    if (sum) sum.remove();
  }

  function renderErrors() {
    clearFieldErrors();
    const loose = [];
    Object.keys(errors).forEach(function (key) {
      const msg = errors[key];
      if (!msg) return;
      const el = fieldEl(key);
      if (!el) { loose.push(msg); return; }
      if (!(showAll || touched[key] || hasValue(el))) return;
      const id = uid + '-err-' + cssKey(key);
      const p = h('p', { class: 'wz-err', id: id }, [h('span', { 'aria-hidden': 'true' }, '\u26A0 '), String(msg)]);
      const wrap = el.closest('.wz-field');
      if (wrap && body.contains(wrap)) wrap.appendChild(p);
      else el.insertAdjacentElement('afterend', p);
      const ids = (el.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
      ids.push(id);
      el.setAttribute('aria-describedby', ids.join(' '));
      el.setAttribute('aria-invalid', 'true');
    });
    if (loose.length) {
      const list = h('ul', { class: 'wz-errors', role: 'alert' }, loose.map(function (m) {
        return h('li', null, [h('span', { 'aria-hidden': 'true' }, '\u26A0 '), String(m)]);
      }));
      body.insertBefore(list, body.firstChild);
    }
  }

  function update() {
    if (closed) return;
    if (index < steps.length) {
      const s = steps[index];
      let e = {};
      try { e = s.validate ? (s.validate(data) || {}) : {}; } catch (err) { e = { _: errText(err) }; }
      errors = e;
    } else {
      errors = {};
    }
    renderErrors();
    const ok = canAdvance(all[index].key, errors);
    backBtn.hidden = index === 0 || index === RESULT;
    backBtn.disabled = busy;
    if (index === RESULT) {
      nextBtn.textContent = 'Close';
      nextBtn.disabled = false;
    } else if (index === REVIEW) {
      nextBtn.textContent = busy ? (spec.busyLabel || 'Saving\u2026') : (typeof spec.submitLabel === 'function' ? spec.submitLabel(data) : (spec.submitLabel || 'Submit'));
      nextBtn.disabled = busy;
    } else {
      nextBtn.textContent = 'Next';
      nextBtn.disabled = !ok;
    }
    const shown = body.querySelector('.wz-err, .wz-errors');
    footMsg.textContent = !ok && !shown && index < steps.length ? 'Complete this step to continue' : '';
    if (busy) box.setAttribute('aria-busy', 'true'); else box.removeAttribute('aria-busy');
  }

  function renderSteps() {
    Array.prototype.forEach.call(stepList.children, function (li, i) {
      if (i === index) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
      li.classList.toggle('wz-done', i < index);
      li.firstChild.textContent = i < index ? '\u2713' : String(i + 1);
    });
  }

  function focusFirst() {
    const f = body.querySelector('[autofocus]') || body.querySelector('textarea:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled])');
    if (f && visible(f)) { try { f.focus(); } catch (e) { /* detached */ } return; }
    const link = body.querySelector('a[href]');
    if (link && index === RESULT) { link.focus(); return; }
    body.focus();
  }

  function runLeave() {
    if (leave) { try { leave(); } catch (e) { /* step cleanup */ } }
    leave = null;
  }

  function show(i, keepFocus) {
    runLeave();
    index = i;
    errors = {};
    touched = {};
    showAll = false;
    body.textContent = '';
    body.scrollTop = 0;
    box.setAttribute('data-step', all[i].key);
    if (i < steps.length) {
      const ret = steps[i].render(body, data, api);
      if (typeof ret === 'function') leave = ret;
    } else if (i === REVIEW) {
      const node = spec.review ? spec.review(data) : null;
      body.appendChild(h('div', { class: 'wz-review' }, node || h('p', null, 'Ready to submit.')));
    } else {
      renderResult();
    }
    renderSteps();
    update();
    if (!keepFocus) focusFirst();
    announce('Step ' + (i + 1) + ' of ' + all.length + ': ' + all[i].label);
  }

  function renderResult() {
    let r = null;
    try { r = spec.result ? spec.result(result) : null; } catch (e) { r = null; }
    r = r || { text: 'Done.' };
    const kids = [h('p', { class: 'wz-result-text', role: 'status' }, [h('span', { class: 'wz-ok', 'aria-hidden': 'true' }, '\u2713 '), r.text || 'Done.'])];
    if (r.href) {
      kids.push(h('p', null, h('a', { class: 'wz-result-link', href: r.href, onclick: function () { close(result); } }, (r.hrefLabel || 'Open') + ' \u203A')));
    }
    body.appendChild(h('div', { class: 'wz-result' }, kids));
  }

  function firstInvalid() {
    const keys = Object.keys(errors).filter(function (k) { return errors[k]; });
    for (let i = 0; i < keys.length; i++) {
      const el = fieldEl(keys[i]);
      if (el) return el;
    }
    return null;
  }

  function goNext() {
    if (busy || closed) return;
    if (index === RESULT) { close(result); return; }
    if (index === REVIEW) { submit(); return; }
    update();
    if (!canAdvance(all[index].key, errors)) {
      showAll = true;
      renderErrors();
      const el = firstInvalid();
      if (el) el.focus();
      return;
    }
    show(index + 1);
  }

  function goBack() {
    if (busy || closed || index === 0 || index === RESULT) return;
    show(index - 1);
  }

  function submit() {
    busy = true;
    update();
    const old = body.querySelector('.wz-submit-error');
    if (old) old.remove();
    Promise.resolve().then(function () { return spec.submit ? spec.submit(data) : data; }).then(function (res) {
      if (closed) return;
      busy = false;
      result = res === undefined ? null : res;
      dirty = false;
      show(RESULT);
    }, function (err) {
      if (closed) return;
      busy = false;
      update();
      const box2 = h('div', { class: 'wz-submit-error' }, inlineError(err, function () { submit(); }));
      body.insertBefore(box2, body.firstChild);
      const retry = box2.querySelector('button');
      if (retry) retry.focus();
    });
  }

  function requestClose() {
    if (closed || confirming) return;
    if (busy) return;
    if (index === RESULT) { close(result); return; }
    if (!dirty) { close(null); return; }
    confirming = true;
    const msg = spec.discardText || 'Discard what you entered in this wizard?';
    const ask = ctx.confirm
      ? ctx.confirm(msg, { title: 'Discard changes?', ok: 'Discard', cancel: 'Keep editing', danger: true })
      : Promise.resolve(window.confirm(msg));
    Promise.resolve(ask).then(function (yes) {
      confirming = false;
      if (yes) close(null);
      else if (!box.contains(document.activeElement)) focusFirst();
    }, function () { confirming = false; });
  }

  function close(v) {
    if (closed) return;
    closed = true;
    runLeave();
    offs.forEach(function (off) { off(); });
    backdrop.remove();
    document.documentElement.classList.remove('wz-open');
    if (opener && opener.focus && document.contains(opener)) { try { opener.focus(); } catch (e) { /* gone */ } }
    if (spec.onClose) { try { spec.onClose(v); } catch (e) { /* caller */ } }
    resolve(v === undefined ? null : v);
  }

  function trapTab(e) {
    const f = Array.prototype.filter.call(box.querySelectorAll(FOCUSABLE), visible);
    if (!f.length) { e.preventDefault(); body.focus(); return; }
    const first = f[0];
    const last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || !box.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (document.activeElement === last || !box.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
  }

  function onBoxKey(e) {
    if (e.key === 'Escape') {
      if (e.defaultPrevented) return;
      e.preventDefault();
      requestClose();
    } else if (e.key === 'Tab') {
      trapTab(e);
    } else if (e.key === 'Enter' && e.target && e.target.tagName === 'INPUT' && /^(text|search|number|email|url)$/.test(e.target.type || 'text') && !e.target.closest('.dt-root')) {
      e.preventDefault();
      goNext();
    }
    e.stopPropagation();
  }

  // Keys that reach the document while focus is outside the box (after a
  // backdrop click): Esc still closes, Tab comes back in.
  function onDocKey(e) {
    if (closed || confirming || box.contains(e.target)) return;
    if (document.querySelector('.app-dialog-backdrop')) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); requestClose(); }
    else if (e.key === 'Tab') trapTab(e);
  }

  function onInput(e) {
    const t = e.target;
    dirty = true;
    const key = t && (t.getAttribute('name') || t.getAttribute('data-field'));
    if (key) touched[key] = true;
    update();
  }

  function onFocusOut(e) {
    const t = e.target;
    const key = t && (t.getAttribute && (t.getAttribute('name') || t.getAttribute('data-field')));
    if (!key || touched[key] || closed) return;
    if (!t.matches('input,select,textarea')) return;
    touched[key] = true;
    setTimeout(function () { if (!closed) renderErrors(); }, 0);
  }

  offs.push(on(box, 'keydown', onBoxKey));
  offs.push(on(document, 'keydown', onDocKey));
  offs.push(on(body, 'input', onInput));
  offs.push(on(body, 'change', onInput));
  offs.push(on(body, 'focusout', onFocusOut));
  offs.push(on(body, 'wz:change', function () { dirty = true; update(); }));
  offs.push(on(closeBtn, 'click', requestClose));
  offs.push(on(backBtn, 'click', goBack));
  offs.push(on(nextBtn, 'click', goNext));
  offs.push(on(backdrop, 'pointerdown', function (e) { if (e.target === backdrop) requestClose(); }));

  document.documentElement.classList.add('wz-open');
  document.body.appendChild(backdrop);
  show(0);
}

// ------------------------------------------------------------ bulk add

function memoryStorage() {
  const m = {};
  return {
    getItem: function (k) { return Object.prototype.hasOwnProperty.call(m, k) ? m[k] : null; },
    setItem: function (k, v) { m[k] = String(v); },
    removeItem: function (k) { delete m[k]; },
  };
}

function roomName(doc, id) {
  if (id === '') return '';
  const r = ((doc && doc.rooms) || []).filter(function (x) { return x.id === id; })[0];
  return r ? (r.name || r.id) : id;
}

function routeHref(ctx, partial) {
  if (ctx.routeHref) {
    try {
      const href = ctx.routeHref(partial);
      if (href && href !== '#') return href;
    } catch (e) { /* fall back */ }
  }
  const base = ctx.route && ctx.route.project ? ctx.route : { project: ctx.project || '', room: (ctx.store && ctx.store.room) || '', view: '', query: {} };
  return buildRoute(mergeRoute(base, partial));
}

function epText(v) {
  if (v && typeof v === 'object') return v.device + (v.port ? ':' + v.port : '');
  return v === undefined || v === null ? '' : String(v);
}

function field(labelText, control, hint, extraClass) {
  const id = control.id || ('wzf-' + (++seq));
  control.id = id;
  const kids = [h('label', { for: id, class: 'wz-label' }, labelText), control];
  if (hint) {
    const hid = id + '-hint';
    kids.splice(1, 0, h('span', { class: 'wz-hint', id: hid }, hint));
    control.setAttribute('aria-describedby', hid);
  }
  return h('div', { class: 'wz-field' + (extraClass ? ' ' + extraClass : '') }, kids);
}

function checkField(labelText, control) {
  return h('div', { class: 'wz-field wz-check' }, h('label', null, [control, ' ', labelText]));
}

export function bulkAdd(ctx, opts) {
  ctx = ctx || {};
  opts = opts || {};
  const store = ctx.store;
  const kind = opts.kind === 'cables' ? 'cables' : 'devices';
  if (!store || store.readOnly) {
    if (ctx.toast) ctx.toast('Read-only: bulk add is not available', 'warn');
    return Promise.resolve(null);
  }
  const vocab = store.vocab || ctx.vocab || null;
  const fields = fieldsFor(kind);
  const formKey = 'bulk-' + kind;
  const memory = recallForm(formKey) || {};
  const doc = function () { return store.doc; };
  let room = opts.room !== undefined && opts.room !== null ? opts.room : store.room;
  if (room === '*' || (room && resolveRoom(doc(), room) === null)) {
    room = (memory.room !== undefined && resolveRoom(doc(), memory.room) !== null) ? memory.room : ((doc().settings && doc().settings.default_room) || '');
  }
  const noun = kind === 'cables' ? { one: 'cable', many: 'cables' } : { one: 'device', many: 'devices' };

  const data = {
    kind: kind, text: '', fileName: '', header: true, headerAuto: true, parsed: null, parsedKey: '',
    mapping: null, mappingKey: '', room: room, repatch: !!memory.repatch, rows: [], results: [],
    include: {}, previewKey: '',
  };

  function reparse() {
    const key = data.text + '\u0000' + data.header + '\u0000' + data.headerAuto;
    if (data.parsed && data.parsedKey === key) return data.parsed;
    const first = parsePasted(data.text);
    if (data.headerAuto) data.header = !first.rows.length || looksLikeHeader(first.header, fields);
    data.parsed = data.header ? first : parsePasted(data.text, { header: false, delimiter: first.delimiter });
    data.parsedKey = data.text + '\u0000' + data.header + '\u0000' + data.headerAuto;
    const mk = data.parsed.header.join('\u0001') + '\u0000' + data.header;
    if (mk !== data.mappingKey) {
      let m;
      if (data.header) {
        m = applyRemembered(data.parsed.header, guessMapping(data.parsed.header, fields), memory.mapping, fields);
      } else {
        m = data.parsed.header.map(function () { return null; });
        if (kind === 'cables') { if (m.length > 0) m[0] = 'from'; if (m.length > 1) m[1] = 'to'; }
        else if (m.length > 0) m[0] = 'name';
      }
      data.mapping = m;
      data.mappingKey = mk;
    }
    return data.parsed;
  }

  function delimName(d) {
    return d === '\t' ? 'tab-separated' : d === ';' ? 'semicolon-separated' : 'comma-separated';
  }

  function computeRows() {
    const p = reparse();
    const key = data.parsedKey + '\u0000' + (data.mapping || []).join(',') + '\u0000' + data.room + '\u0000' + data.repatch + '\u0000' + (store.revision || 0);
    if (key === data.previewKey) return;
    data.rows = p.rows.map(function (cells) { return rowObject(cells, data.mapping); });
    data.results = validateRows(doc(), kind, data.rows, { vocab: vocab, room: data.room, repatch: data.repatch });
    data.include = {};
    data.results.forEach(function (r, i) { if (!Object.keys(r.errors).length) data.include[i] = true; });
    data.previewKey = key;
  }

  function included() {
    const out = [];
    data.rows.forEach(function (row, i) {
      if (data.include[i] && !Object.keys(data.results[i].errors).length) out.push(row);
    });
    return out;
  }

  function targetRooms(rows) {
    const set = {};
    rows.forEach(function (r) {
      const id = r.room ? resolveRoom(doc(), r.room) : data.room;
      set[id === null ? '?' : id] = true;
    });
    return Object.keys(set);
  }

  function scopeName(rows) {
    if (kind === 'cables') return store.room && store.room !== '*' ? roomName(doc(), store.room) : undefined;
    const rooms = targetRooms(rows);
    return rooms.length === 1 ? roomName(doc(), rooms[0]) : undefined;
  }

  // ---------------------------------------------------------- step 1: paste

  const paste = {
    key: 'paste',
    label: 'Paste',
    render: function (body, d, w) {
      const hint = kind === 'cables'
        ? 'One cable per row with a header row. From and To are device:port (ids or names), or use separate From port and To port columns. Optional: Tag, Type, Length, Medium, Colour, Status, Repatch.'
        : 'One device per row with a header row such as Name, Room, Status, Kind, Manufacturer, Model, Serial. Copy the cells from a spreadsheet and paste them here.';
      const ta = h('textarea', { name: 'text', rows: '9', spellcheck: 'false', autocomplete: 'off', class: 'wz-paste', placeholder: kind === 'cables' ? 'From\tTo\tTag\nStage Box 1:Output 1\tAudio Rack 1:Input 5\tA-101' : 'Name\tRoom\tStatus\nLectern mic\tMain Auditorium\tplanned' });
      ta.value = d.text;
      const file = h('input', { type: 'file', name: 'file', accept: '.csv,.tsv,.txt,text/csv,text/plain,text/tab-separated-values' });
      const sum = h('p', { class: 'wz-paste-sum', 'aria-live': 'polite' });
      function summarize() {
        if (!d.text.trim()) { sum.textContent = ''; return; }
        const p = reparse();
        sum.textContent = plural(p.rows.length, 'row') + ' \u00b7 ' + plural(p.header.length, 'column') + ' \u00b7 ' + delimName(p.delimiter) + (d.fileName ? ' \u00b7 ' + d.fileName : '');
      }
      ta.addEventListener('input', function () { d.text = ta.value; d.fileName = ''; summarize(); });
      file.addEventListener('change', function () {
        const f = file.files && file.files[0];
        if (!f) return;
        const rd = new FileReader();
        rd.onload = function () {
          d.text = String(rd.result || '');
          d.fileName = f.name;
          ta.value = d.text;
          summarize();
          w.markDirty();
          w.revalidate();
        };
        rd.onerror = function () { sum.textContent = 'Could not read ' + f.name; };
        rd.readAsText(f);
      });
      body.appendChild(field(kind === 'cables' ? 'Cable rows' : 'Device rows', ta, hint));
      body.appendChild(field('Or choose a CSV or TSV file', file, null, 'wz-file'));
      body.appendChild(sum);
      summarize();
    },
    validate: function (d) {
      if (!d.text.trim()) return { text: 'Paste some rows or choose a file' };
      const p = reparse();
      if (!p.rows.length) return { text: 'Add at least one row under the header row' };
      if (p.rows.length > MAX_ROWS) return { text: 'At most ' + MAX_ROWS + ' rows at a time (found ' + p.rows.length + ')' };
      return {};
    },
  };

  // ---------------------------------------------------------- step 2: map columns

  const map = {
    key: 'map',
    label: 'Map columns',
    render: function (body, d, w) {
      const p = reparse();
      const hd = h('input', { type: 'checkbox', name: 'header' });
      hd.checked = d.header;
      hd.addEventListener('change', function () { d.header = hd.checked; d.headerAuto = false; w.rerender(); });
      body.appendChild(checkField('First row is a header', hd));
      if (kind === 'devices') {
        const sel = h('select', { name: 'room' });
        ((doc().rooms) || []).forEach(function (r) { sel.appendChild(h('option', { value: r.id }, r.name || r.id)); });
        sel.appendChild(h('option', { value: '' }, 'Shared inventory (no room)'));
        sel.value = d.room;
        if (sel.value !== d.room) { sel.appendChild(h('option', { value: d.room }, d.room)); sel.value = d.room; }
        sel.addEventListener('change', function () { d.room = sel.value; });
        body.appendChild(field('Room for rows without one', sel));
      } else {
        const rp = h('input', { type: 'checkbox', name: 'repatch' });
        rp.checked = d.repatch;
        rp.addEventListener('change', function () { d.repatch = rp.checked; });
        body.appendChild(checkField('Replace cables already on these ports (repatch)', rp));
      }
      const grid = h('div', { class: 'wz-map', role: 'group', 'aria-label': 'Columns' });
      p.header.forEach(function (name, i) {
        const sel = h('select', { name: 'col-' + i });
        sel.appendChild(h('option', { value: '' }, '\u2014 Don\u2019t import'));
        fields.forEach(function (f) { sel.appendChild(h('option', { value: f.key }, f.label + (f.required ? ' *' : ''))); });
        sel.value = d.mapping[i] || '';
        sel.addEventListener('change', function () { d.mapping[i] = sel.value || null; });
        const samples = p.rows.map(function (r) { return r[i]; }).filter(function (v) { return v; }).slice(0, 2);
        const label = name || ('Column ' + (i + 1));
        grid.appendChild(field(label, sel, samples.length ? 'e.g. ' + samples.join(', ') : '(empty)', 'wz-map-row'));
      });
      body.appendChild(grid);
      body.appendChild(h('p', { class: 'wz-hint' }, '* required'));
    },
    validate: function (d) {
      const p = reparse();
      const e = mappingErrors(d.mapping, fields, p.header);
      if (kind === 'devices' && d.room && resolveRoom(doc(), d.room) === null) e.room = 'Unknown room \u201c' + d.room + '\u201d';
      return e;
    },
  };

  // ---------------------------------------------------------- step 3: preview

  const preview = {
    key: 'preview',
    label: 'Preview',
    render: function (body, d, w) {
      computeRows();
      const mapped = fields.filter(function (f) { return d.mapping.indexOf(f.key) >= 0; });
      const tableRows = d.rows.map(function (row, i) {
        const res = d.results[i];
        return { n: i + 1, i: i, row: row, ok: !Object.keys(res.errors).length, errors: res.errors, warnings: res.warnings };
      });
      const bad = tableRows.filter(function (r) { return !r.ok; }).length;
      const sum = h('p', { class: 'wz-preview-sum', 'aria-live': 'polite', tabindex: '-1', autofocus: true });
      function summarize() {
        const n = included().length;
        sum.textContent = n + ' of ' + plural(tableRows.length, 'row') + ' selected' + (bad ? ' \u00b7 ' + bad + ' with problems will be skipped' : '');
      }
      function label(key) {
        const f = fields.filter(function (x) { return x.key === key; })[0];
        return f ? f.label : key;
      }
      function problems(r) {
        const parts = [];
        Object.keys(r.errors).forEach(function (k) { parts.push(label(k) + ': ' + r.errors[k]); });
        Object.keys(r.warnings || {}).forEach(function (k) { if (r.warnings[k] && !r.errors[k]) parts.push(label(k) + ': ' + r.warnings[k]); });
        return parts.join('; ');
      }
      let table = null;
      const columns = [{
        key: 'add', header: 'Add', sortable: false, searchable: false, width: '3.5rem',
        value: function (r) { return r.ok && d.include[r.i] ? 'yes' : 'no'; },
        cell: function (r) {
          const cb = h('input', { type: 'checkbox', class: 'wz-inc', 'data-row': String(r.n), 'aria-label': 'Add row ' + r.n });
          cb.checked = !!(r.ok && d.include[r.i]);
          cb.disabled = !r.ok;
          cb.addEventListener('change', function () {
            if (cb.checked) d.include[r.i] = true; else delete d.include[r.i];
            summarize();
          });
          return h('label', { class: 'wz-inc-wrap' }, cb);
        },
      }, {
        key: 'n', header: '#', align: 'right', width: '3rem', searchable: false,
        value: function (r) { return r.n; },
      }];
      mapped.forEach(function (f, ci) {
        columns.push({
          key: 'f_' + f.key, header: f.label, sticky: ci === 0, hideOnMobile: ci > 1 && f.key !== 'from' && f.key !== 'to',
          value: function (r) { return epText(r.row[f.key]); },
        });
      });
      columns.push({
        key: 'problems', header: 'Problems',
        value: problems,
        cell: function (r) {
          const t = problems(r);
          if (!t) return h('span', { class: 'wz-ok' }, '\u2713');
          return h('span', { class: r.ok ? 'wz-warn' : 'wz-bad' }, [h('span', { 'aria-hidden': 'true' }, '\u26A0 '), t]);
        },
      });
      const allBtn = h('button', { type: 'button', class: 'wz-all' }, 'Select all valid');
      const noneBtn = h('button', { type: 'button', class: 'wz-none' }, 'Clear');
      function setAll(v) {
        d.include = {};
        if (v) tableRows.forEach(function (r) { if (r.ok) d.include[r.i] = true; });
        if (table) table.refresh();
        summarize();
        w.markDirty();
        w.revalidate();
      }
      allBtn.addEventListener('click', function () { setAll(true); });
      noneBtn.addEventListener('click', function () { setAll(false); });
      body.appendChild(sum);
      const host = h('div', { class: 'wz-table', 'data-field': 'rows' });
      body.appendChild(host);
      table = createTable(host, {
        key: 'wizard-' + kind,
        scope: '',
        caption: 'Rows to add',
        columns: columns,
        rows: tableRows,
        rowId: function (r) { return String(r.n); },
        rowClass: function (r) { return r.ok ? '' : 'wz-row-bad'; },
        actions: [allBtn, noneBtn],
        pageSize: 50,
        empty: 'No rows to preview.',
        csvName: 'bulk-' + kind + '-preview.csv',
        storage: memoryStorage(),
      });
      summarize();
      return function () { if (table && table.destroy) table.destroy(); table = null; };
    },
    validate: function () {
      return included().length ? {} : { rows: 'Select at least one valid row to add' };
    },
  };

  // ---------------------------------------------------------- review, submit, result

  function review() {
    const rows = included();
    const skipped = data.rows.length - rows.length;
    const items = [];
    if (skipped) items.push(h('li', null, plural(skipped, 'row') + ' will be skipped'));
    if (kind === 'devices') {
      const rooms = targetRooms(rows);
      if (rooms.length > 1) items.push(h('li', null, 'Into ' + plural(rooms.length, 'room') + ': ' + rooms.map(function (r) { return roomName(doc(), r) || 'shared inventory'; }).join(', ')));
    } else {
      const repl = replacedCables(bulkCableOps(doc(), rows, { vocab: vocab, repatch: data.repatch }));
      if (repl.length) items.push(h('li', { class: 'wz-warn' }, 'Replaces ' + plural(repl.length, 'existing cable')));
    }
    const names = rows.slice(0, 8).map(function (r) {
      return kind === 'cables' ? epText(r.from) + (r.from_port ? ':' + r.from_port : '') + ' \u2192 ' + epText(r.to) + (r.to_port ? ':' + r.to_port : '') : r.name;
    });
    items.push(h('li', { class: 'wz-names' }, names.join(kind === 'cables' ? '; ' : ', ') + (rows.length > 8 ? ' and ' + (rows.length - 8) + ' more' : '')));
    items.push(h('li', { class: 'wz-hint' }, 'One undo step: ' + commitLabel(kind, rows.length)));
    return h('div', null, [h('h3', { class: 'wz-review-title' }, reviewText(kind, rows.length, scopeName(rows))), h('ul', { class: 'wz-review-list' }, items)]);
  }

  function submit() {
    const rows = included();
    const now = doc();
    const again = validateRows(now, kind, rows, { vocab: vocab, room: data.room, repatch: data.repatch });
    const stale = again.filter(function (r) { return Object.keys(r.errors).length; }).length;
    if (stale) throw new Error(plural(stale, 'row') + ' no longer ' + (stale === 1 ? 'fits' : 'fit') + ' the project (it changed meanwhile). Go Back to Preview to check.');
    const ops = kind === 'cables'
      ? bulkCableOps(now, rows, { vocab: vocab, repatch: data.repatch })
      : bulkDeviceOps(now, rows, { room: data.room, vocab: vocab });
    const label = commitLabel(kind, rows.length);
    const ok = ctx.commit ? ctx.commit(ops, label) : store.commit(ops, label);
    if (!ok) throw new Error('Nothing was added: the change could not be applied.');
    rememberForm(formKey, {
      mapping: Object.assign({}, memory.mapping || {}, data.header ? rememberMapping(data.parsed.header, data.mapping) : {}),
      room: data.room,
      repatch: data.repatch,
    });
    const ids = ops.filter(function (o) { return o.op === 'put'; }).map(function (o) { return o.id; });
    return { kind: kind, ids: ids, count: ids.length, replaced: replacedCables(ops), label: label, room: data.room, scope: scopeName(rows) };
  }

  function result(res) {
    if (!res) return { text: 'Done.' };
    let text = 'Added ' + plural(res.count, noun.one, noun.many);
    if (kind === 'devices') text += res.scope !== undefined ? (res.scope ? ' to ' + res.scope : ' to shared inventory') : '';
    else if (res.scope) text += ' in ' + res.scope;
    text += '.';
    if (res.replaced && res.replaced.length) text += ' Replaced ' + plural(res.replaced.length, 'cable') + '.';
    const route = resultRoute(kind, res.ids);
    if (kind === 'devices') {
      const rooms = targetRooms(included());
      route.room = rooms.length === 1 && rooms[0] !== '' ? rooms[0] : '*';
    }
    return {
      text: text,
      href: routeHref(ctx, route),
      hrefLabel: kind === 'cables' ? 'Open the cable schedule' : (res.count === 1 ? 'Open the device' : 'Open the devices'),
    };
  }

  return openWizard(ctx, {
    key: 'bulk-' + kind,
    title: kind === 'cables' ? 'Bulk add cables' : 'Bulk add devices',
    data: data,
    steps: [paste, map, preview],
    review: review,
    submitLabel: function () { const n = included().length; return 'Add ' + plural(n, noun.one, noun.many); },
    busyLabel: 'Adding\u2026',
    submit: submit,
    result: result,
    resultLabel: 'Result',
    discardText: 'Discard the pasted rows?',
  });
}
