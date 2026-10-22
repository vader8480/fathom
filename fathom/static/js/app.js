// Fathom app shell (§6.4): hash router, store + change queue wiring, lazy
// views with error cards, top bar, room/project pickers, dialogs, pickers,
// toasts, search palette, offline / conflict handling, SW registration and
// the login page. app.html and login.html both load this module.

import {
  createStore, canConnect, devicePorts, portLabel, deviceTitle, disciplineOf, mediumInfo, searchLocal,
  filterDevices, parsePortRef, slug, deepClone,
} from './model-core.js';
import { createApi, ChangeQueue, ApiError } from './api.js';

export const VIEWS = {
  map: { label: 'Map', module: null, internal: true },
  patch: { label: 'Patch', module: './patchview.js', export: 'mount', css: 'patchview.css' },
  table: { label: 'Table', module: './patchtable.js', export: 'mount' },
  plan: { label: 'Plan', module: './floorplan.js', export: 'mount', css: 'plan.css' },
  racks: { label: 'Racks', module: './rack.js', export: 'mount', css: 'plan.css' },
  inventory: { label: 'Inventory', module: './inventory.js', export: 'mount', css: 'plan.css' },
  schedules: { label: 'Schedules', module: './schedules.js', export: 'mount', css: 'plan.css' },
  imports: { label: 'Imports', module: './views-admin.js', export: 'mountImports' },
  discovery: { label: 'Discovery', module: './views-discovery.js', export: 'mount' },
  history: { label: 'History', module: './views-admin.js', export: 'mountHistory' },
  builds: { label: 'Builds', module: './views-admin.js', export: 'mountBuilds' },
  settings: { label: 'Settings', module: './views-admin.js', export: 'mountSettings' },
  sop: { label: 'SOPs', module: './views-sop.js', export: 'mount', css: 'sop.css' },
  json: { label: 'JSON', module: null, internal: true },
};
const PHONE_TABS = ['map', 'patch', 'table', 'plan', 'sop'];
const TAB_ICONS = { map: '\u25A6', patch: '\u2B95', table: '\u2630', plan: '\u25A3', sop: '\u2611', more: '\u22EF' };
const DEFAULT_VIEW = 'patch';
const FALLBACK_VOCAB = {
  kinds: {}, media: {}, brands: {}, connectors: [], statuses: ['installed', 'planned', 'spare', 'retired'],
  disciplines: { audio: { label: 'Audio', color: '#4ea8ff', letter: 'A' }, video: { label: 'Video', color: '#34d399', letter: 'V' }, lighting: { label: 'Lighting', color: '#fbbf24', letter: 'L' }, network: { label: 'Network', color: '#fb923c', letter: 'N' }, control: { label: 'Control', color: '#c084fc', letter: 'C' }, power: { label: 'Power', color: '#f87171', letter: 'P' }, other: { label: 'Other', color: '#9aa3b5', letter: 'X' } },
};

// ------------------------------------------------------------ DOM helpers

export function h(tag, attrs, children) {
  const el = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (v === undefined || v === null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k.indexOf('on') === 0 && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, String(v));
    });
  }
  (Array.isArray(children) ? children : (children === undefined || children === null ? [] : [children])).forEach(function (c) {
    if (c === null || c === undefined || c === false) return;
    el.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
  });
  return el;
}

export function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; });
}

function errMsg(e) {
  return (e && (e.message || String(e))) || 'Unknown error';
}

function staticBase() {
  const s = document.querySelector('script[src*="js/app.js"]');
  if (s && s.src) return s.src.replace(/js\/app\.js.*$/, '');
  return new URL('static/', location.href).href;
}

function appRoot() {
  return staticBase().replace(/static\/$/, '');
}

const loadedCss = {};
// Resolves once the stylesheet has loaded (or failed), so views can measure styled layout.
export function ensureCss(file) {
  if (!file) return Promise.resolve();
  if (loadedCss[file]) return loadedCss[file];
  loadedCss[file] = new Promise(function (resolve) {
    const link = h('link', { rel: 'stylesheet', href: staticBase() + 'css/' + file });
    link.addEventListener('load', function () { resolve(); });
    link.addEventListener('error', function () { resolve(); });
    document.head.appendChild(link);
  });
  return loadedCss[file];
}

// ------------------------------------------------------------ error capture + smoke

function installErrorCapture() {
  if (window.__fathomErrors) return;
  window.__fathomErrors = [];
  function push(m) { window.__fathomErrors.push(String(m).slice(0, 500)); }
  window.addEventListener('error', function (e) { push((e && e.message) || 'error'); });
  window.addEventListener('unhandledrejection', function (e) { push('unhandled: ' + errMsg(e && e.reason)); });
  const orig = console.error;
  console.error = function () {
    push(Array.prototype.map.call(arguments, function (a) { return a && a.message ? a.message : String(a); }).join(' '));
    return orig.apply(console, arguments);
  };
}

function urlParam(name) {
  const s = new URLSearchParams(location.search);
  if (s.has(name)) return s.get(name);
  const hq = location.hash.indexOf('?');
  if (hq >= 0) {
    const hp = new URLSearchParams(location.hash.slice(hq + 1));
    if (hp.has(name)) return hp.get(name);
  }
  return null;
}

let smokeDone = false;
export function markRendered() {
  if (smokeDone || urlParam('smoke') !== '1') return;
  smokeDone = true;
  setTimeout(function () {
    document.documentElement.setAttribute('data-smoke', JSON.stringify({ ready: true, errors: window.__fathomErrors || [], stats: window.__pvStats || null }));
  }, 1000);
}

// ------------------------------------------------------------ announcements, toasts

export function announce(text) {
  const live = document.getElementById('fathom-live');
  if (!live || !text) return;
  live.textContent = '';
  setTimeout(function () { live.textContent = text; }, 30);
}

export function toast(message, level) {
  let host = document.getElementById('app-toasts');
  if (!host) {
    host = h('div', { id: 'app-toasts', class: 'app-toasts', 'aria-live': 'polite' });
    document.body.appendChild(host);
  }
  const lv = level || 'info';
  const el = h('div', { class: 'app-toast ' + lv, role: lv === 'err' ? 'alert' : 'status' }, String(message));
  el.addEventListener('click', function () { el.remove(); });
  host.appendChild(el);
  setTimeout(function () { el.remove(); }, lv === 'err' ? 7000 : 4000);
  return el;
}

// ------------------------------------------------------------ dialogs

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

export function openDialog(o) {
  return new Promise(function (resolve) {
    const opener = document.activeElement;
    let host = document.getElementById('app-dialog');
    if (!host) { host = h('div', { id: 'app-dialog' }); document.body.appendChild(host); }
    const titleId = 'dlg-' + Math.random().toString(36).slice(2, 8);
    const body = h('div', { class: 'body' }, o.body || null);
    const footer = h('footer');
    const box = h('div', { class: 'app-dialog' + (o.wide ? ' wide' : ''), role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': titleId }, [
      h('header', null, [h('h2', { id: titleId }, o.title || ''), h('button', { class: 'icon ghost', type: 'button', 'aria-label': 'Close', onclick: function () { close(null); } }, '\u00d7')]),
      body,
    ]);
    if (o.buttons && o.buttons.length) box.appendChild(footer);
    const back = h('div', { class: 'app-dialog-backdrop' }, box);
    let done = false;
    function close(v) {
      if (done) return;
      done = true;
      document.removeEventListener('keydown', onKey, true);
      back.remove();
      if (o.onClose) o.onClose(v);
      if (opener && opener.focus) { try { opener.focus(); } catch (e) { /* gone */ } }
      resolve(v);
    }
    function onKey(e) {
      if (!host.contains(e.target) && e.target !== document.body) { /* still trap */ }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(null); return; }
      if (e.key === 'Tab') {
        const f = Array.prototype.filter.call(box.querySelectorAll(FOCUSABLE), function (x) { return x.offsetParent !== null || x === document.activeElement; });
        if (!f.length) return;
        const first = f[0];
        const last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    (o.buttons || []).forEach(function (b) {
      footer.appendChild(h('button', { type: 'button', class: (b.primary ? 'primary' : '') + (b.danger ? ' danger' : ''), onclick: function () {
        if (b.validate && !b.validate()) return;
        close(typeof b.value === 'function' ? b.value() : b.value);
      } }, b.label));
    });
    back.addEventListener('pointerdown', function (e) { if (e.target === back) close(null); });
    document.addEventListener('keydown', onKey, true);
    host.appendChild(back);
    const api = { close: close, box: box, body: body };
    if (o.onOpen) o.onOpen(api);
    setTimeout(function () {
      const auto = box.querySelector('[autofocus]') || box.querySelector('input,select,textarea') || box.querySelector('footer button.primary') || box.querySelector(FOCUSABLE);
      if (auto) auto.focus();
    }, 20);
  });
}

export function confirmDialog(message, opts) {
  opts = opts || {};
  return openDialog({
    title: opts.title || (opts.danger ? 'Are you sure?' : 'Confirm'),
    body: h('p', { style: { margin: '0', whiteSpace: 'pre-wrap' } }, message),
    buttons: [{ label: opts.cancel || 'Cancel', value: false }, { label: opts.ok || (opts.danger ? 'Delete' : 'OK'), value: true, primary: !opts.danger, danger: !!opts.danger }],
  }).then(function (v) { return v === true; });
}

export function promptDialog(message, value, opts) {
  opts = opts || {};
  const input = h('input', { type: opts.type || 'text', value: value || '', autofocus: true, inputmode: opts.inputmode, 'aria-label': message, style: { width: '100%' } });
  return openDialog({
    title: opts.title || message,
    body: h('div', null, [opts.title ? h('p', { style: { marginTop: '0' } }, message) : null, input]),
    onOpen: function (d) { input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); d.close(input.value); } }); },
    buttons: [{ label: 'Cancel', value: null }, { label: opts.ok || 'OK', primary: true, value: function () { return input.value; } }],
  });
}

// keyboard-navigable list inside a dialog
function listNav(input, list, onPick) {
  let idx = -1;
  function items() { return Array.prototype.filter.call(list.querySelectorAll('li[data-pick]'), function () { return true; }); }
  function set(i) {
    const its = items();
    if (!its.length) return;
    idx = Math.max(0, Math.min(its.length - 1, i));
    its.forEach(function (x, j) { x.setAttribute('aria-selected', j === idx ? 'true' : 'false'); });
    its[idx].scrollIntoView({ block: 'nearest' });
  }
  input.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); set(idx + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); set(idx - 1); }
    else if (e.key === 'Enter') {
      const its = items();
      if (its.length) { e.preventDefault(); onPick(its[idx >= 0 ? idx : 0]); }
    }
  });
  list.addEventListener('click', function (e) {
    const li = e.target.closest('li[data-pick]');
    if (li) onPick(li);
  });
  return { reset: function () { idx = -1; } };
}

// ------------------------------------------------------------ pickers

const ADD_GEAR_TAB_KEY = 'fathom.addgear.tab';
let presetsCache = null;

function loadPresets(ctx) {
  if (presetsCache) return Promise.resolve(presetsCache);
  if (!ctx.api || !ctx.api.presets) return Promise.reject(new Error('Presets need a connection to the server'));
  return Promise.resolve(ctx.api.presets()).then(function (r) {
    presetsCache = { groups: (r && r.groups) || [], presets: (r && r.presets) || [] };
    return presetsCache;
  });
}

function readTab() {
  try { return window.localStorage.getItem(ADD_GEAR_TAB_KEY) || ''; } catch (e) { return ''; }
}

function writeTab(v) {
  try { window.localStorage.setItem(ADD_GEAR_TAB_KEY, v); } catch (e) { /* private mode */ }
}

// Presets tab of the Add gear dialog: searchable grouped list → pre-filled form → template for addDeviceFromTemplateOps.
function presetsPanel(ctx, opts, onReady) {
  const vocab = ctx.vocab || FALLBACK_VOCAB;
  const root = h('div', { class: 'pf-panel' });
  const input = h('input', { type: 'search', class: 'search-input', placeholder: 'Search presets (e.g. "ups", "switch", "patch panel")', 'aria-label': 'Search presets' });
  const list = h('ul', { class: 'pick-list pf-list', role: 'listbox', 'aria-label': 'Device presets' });
  const status = h('div', { class: 'muted', style: { marginTop: '6px', fontSize: '12px' } }, 'Loading presets\u2026');
  const pickView = h('div', { class: 'pf-pick' }, [input, list, status]);
  const formView = h('div', { class: 'pf-form', hidden: true });
  root.appendChild(pickView);
  root.appendChild(formView);
  const S = { data: null, preset: null, form: null, api: null, byId: {} };

  function kindLabel(k) { const m = (vocab.kinds || {})[k]; return m ? m.label : k; }
  function kindColor(k) { const m = (vocab.kinds || {})[k]; return m ? m.color : '#9aa3b5'; }

  function renderList() {
    list.innerHTML = '';
    S.byId = {};
    if (!S.data) return;
    let items = S.api.filterPresets(S.data.presets, input.value, S.data.groups);
    if (opts.kind) items = items.filter(function (p) { return p.kind === opts.kind; });
    S.api.groupPresets(items, S.data.groups).forEach(function (g) {
      list.appendChild(h('li', { class: 'group' }, g.group));
      g.items.forEach(function (p) {
        S.byId[p.id] = p;
        list.appendChild(h('li', { 'data-pick': p.id, role: 'option' }, [
          h('span', { class: 'dot', style: { color: kindColor(p.kind) } }),
          h('div', { class: 'pf-item' }, [h('div', null, p.label), h('div', { class: 'muted pf-ports' }, S.api.portsSummary(p.ports))]),
          h('span', { class: 'sub' }, kindLabel(p.kind) + (p.ru ? ' \u00b7 ' + p.ru + 'U' : '')),
        ]));
      });
    });
    status.textContent = items.length ? items.length + ' presets \u00b7 pick one to pre-fill the form' : 'No presets match.';
  }

  function openForm(p) {
    S.preset = p;
    S.form = S.api.presetForm(p);
    formView.innerHTML = '';
    const f = S.form;
    const name = h('input', { type: 'text', id: 'pf-name', value: f.name, autocomplete: 'off', autofocus: true });
    const kinds = Object.keys(vocab.kinds || {}).sort(function (a, b) { return kindLabel(a).localeCompare(kindLabel(b)); });
    if (kinds.indexOf(f.kind) < 0) kinds.unshift(f.kind);
    const kind = h('select', { id: 'pf-kind' }, kinds.map(function (k) { return h('option', { value: k, selected: k === f.kind }, kindLabel(k)); }));
    const manu = h('input', { type: 'text', id: 'pf-manufacturer', placeholder: 'optional', autocomplete: 'off' });
    const model = h('input', { type: 'text', id: 'pf-model', placeholder: 'optional', autocomplete: 'off' });
    const ru = h('input', { type: 'number', id: 'pf-ru', min: 0, max: 60, step: 1, inputmode: 'numeric', value: f.ru || '', placeholder: 'not racked' });
    name.addEventListener('input', function () { f.name = name.value; });
    kind.addEventListener('change', function () { f.kind = kind.value; });
    manu.addEventListener('input', function () { f.manufacturer = manu.value; });
    model.addEventListener('input', function () { f.model = model.value; });
    ru.addEventListener('input', function () { const n = parseInt(ru.value, 10); f.ru = n >= 1 ? n : null; });
    const field = function (id, label, el) { return h('div', { class: 'pf-field' }, [h('label', { for: id }, label), el]); };
    const ports = h('div', { class: 'pf-portlist' }, f.ports.map(function (g, i) {
      const src = (p.ports || [])[i] || {};
      const mi = mediumInfo(src.medium, vocab);
      const num = h('input', { type: 'number', min: 0, max: 512, step: 1, inputmode: 'numeric', value: g.count, disabled: g.fixed, 'aria-label': g.group + ' count' });
      num.addEventListener('input', function () { const n = parseInt(num.value, 10); g.count = n >= 0 ? n : 0; });
      return h('div', { class: 'pf-port' }, [
        h('span', { class: 'dot', style: { color: mi.color || '#9aa3b5' } }),
        h('span', { class: 'pf-port-name' }, g.group),
        h('span', { class: 'muted pf-port-meta' }, [mi.short || src.medium || '', src.connector ? ' \u00b7 ' + src.connector : '', src.channels > 1 ? ' \u00b7 ' + src.channels + ' ch' : '']),
        num,
      ]);
    }));
    formView.appendChild(h('div', { class: 'pf-head' }, [
      h('button', { type: 'button', class: 'chip', onclick: function () { showPick(); } }, '\u2190 Presets'),
      h('div', { class: 'pf-title' }, [h('strong', null, p.label), h('div', { class: 'muted pf-desc' }, p.description || '')]),
    ]));
    formView.appendChild(h('div', { class: 'pf-fields' }, [
      field('pf-name', 'Name', name), field('pf-kind', 'Kind', kind),
      field('pf-manufacturer', 'Manufacturer', manu), field('pf-model', 'Model', model),
      field('pf-ru', 'Rack units', ru),
    ]));
    formView.appendChild(h('div', { class: 'pf-section' }, [h('h4', null, 'Ports'), h('span', { class: 'muted' }, 'Set a count to 0 to drop a group.')]));
    formView.appendChild(ports);
    formView.appendChild(h('p', { class: 'muted pf-hint' }, 'Everything can still be changed later in the inspector.'));
    formView.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && e.target && e.target.tagName === 'INPUT') { e.preventDefault(); onReady.create(); }
    });
    pickView.hidden = true;
    formView.hidden = false;
    onReady.step('form');
    setTimeout(function () { name.focus(); name.select(); }, 20);
  }

  function showPick() {
    S.preset = null;
    formView.hidden = true;
    pickView.hidden = false;
    onReady.step('pick');
    setTimeout(function () { input.focus(); }, 20);
  }

  input.addEventListener('input', renderList);
  listNav(input, list, function (li) { const p = S.byId[li.getAttribute('data-pick')]; if (p) openForm(p); });
  Promise.all([import('./presets-core.js'), loadPresets(ctx)]).then(function (r) {
    S.api = r[0];
    S.data = r[1];
    renderList();
  }, function (e) { status.textContent = errMsg(e); });

  return {
    el: root,
    focus: function () { if (S.preset) return; setTimeout(function () { input.focus(); }, 20); },
    result: function () {
      if (!S.preset || !S.api) return null;
      if (!(S.form.name || '').trim()) { toast('Give the device a name', 'warn'); return null; }
      return S.api.presetTemplate(S.preset, S.form);
    },
  };
}

function makePickTemplate(getCtx) {
  return function pickTemplate(opts) {
    opts = opts || {};
    const ctx = getCtx();
    const vocab = ctx.vocab || FALLBACK_VOCAB;
    let disc = opts.discipline || '';
    const input = h('input', { type: 'search', class: 'search-input', placeholder: 'Search the library (e.g. "rio", "atem")', 'aria-label': 'Search templates' });
    const chips = h('div', { class: 'row', style: { marginTop: '8px' } });
    const list = h('ul', { class: 'pick-list', role: 'listbox', 'aria-label': 'Templates' });
    const status = h('div', { class: 'muted', style: { marginTop: '6px', fontSize: '12px' } });
    let byId = {};
    let timer = null;
    let dlg = null;
    let createBtn = null;
    const hasPresets = !!(ctx.api && ctx.api.presets);
    let tab = hasPresets && readTab() !== 'library' ? 'presets' : 'library';
    const presets = hasPresets ? presetsPanel(ctx, opts, {
      step: function (s) { if (createBtn) createBtn.hidden = s !== 'form'; },
      create: function () { if (dlg && createBtn && !createBtn.hidden) createBtn.click(); },
    }) : null;
    const libraryPanel = h('div', { class: 'pf-panel' }, [input, chips, list, status]);
    const tabs = h('div', { class: 'pf-tabs', role: 'tablist' });
    function renderTabs() {
      tabs.innerHTML = '';
      [['presets', 'Presets'], ['library', 'Library']].forEach(function (t) {
        if (t[0] === 'presets' && !presets) return;
        tabs.appendChild(h('button', { type: 'button', role: 'tab', class: 'pf-tab' + (tab === t[0] ? ' on' : ''), 'aria-selected': tab === t[0] ? 'true' : 'false', onclick: function () { setTab(t[0]); } }, t[1]));
      });
      if (presets) presets.el.hidden = tab !== 'presets';
      libraryPanel.hidden = tab !== 'library';
      if (createBtn) createBtn.hidden = !(tab === 'presets' && presets && !presets.el.querySelector('.pf-form').hidden);
    }
    function setTab(t) {
      tab = t;
      writeTab(t);
      renderTabs();
      if (t === 'library') setTimeout(function () { input.focus(); }, 20);
      else if (presets) presets.focus();
    }
    function renderChips() {
      chips.innerHTML = '';
      [''].concat(Object.keys(vocab.disciplines || {})).forEach(function (k) {
        const d = (vocab.disciplines || {})[k];
        chips.appendChild(h('button', { type: 'button', class: 'chip' + (disc === k ? ' on' : ''), 'aria-pressed': disc === k ? 'true' : 'false', style: d ? { color: d.color } : null, onclick: function () { disc = k; renderChips(); load(); } }, k ? [h('i'), d.label] : 'All'));
      });
    }
    function show(templates, source) {
      list.innerHTML = '';
      byId = {};
      templates.forEach(function (t) {
        byId[t.id] = t;
        list.appendChild(h('li', { 'data-pick': t.id, role: 'option' }, [
          h('div', null, [h('div', null, (t.manufacturer ? t.manufacturer + ' ' : '') + (t.model || t.name || t.id)), h('div', { class: 'muted', style: { fontSize: '11.5px' } }, t.ports_summary || '')]),
          h('span', { class: 'sub' }, [t.kind || '', t.source && t.source !== 'builtin' ? ' \u00b7 ' + t.source : '']),
        ]));
      });
      status.textContent = templates.length ? templates.length + ' templates' + (source ? ' (' + source + ')' : '') : 'No templates match.';
    }
    function localTemplates() {
      const q = input.value.trim().toLowerCase();
      return ((ctx.store && ctx.store.doc.templates) || []).filter(function (t) {
        const hay = [t.id, t.manufacturer, t.model, t.name, t.kind].join(' ').toLowerCase();
        return (!q || hay.indexOf(q) >= 0) && (!disc || t.discipline === disc);
      });
    }
    function load() {
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () {
        if (!ctx.api) { show(localTemplates(), 'project'); return; }
        ctx.api.library({ q: input.value.trim(), discipline: disc, kind: opts.kind, project: ctx.project }).then(function (r) {
          show((r && r.templates) || [], '');
        }, function (e) { show(localTemplates(), 'offline'); status.textContent += ' \u00b7 ' + errMsg(e); });
      }, 180);
    }
    input.addEventListener('input', load);
    listNav(input, list, function (li) { if (dlg) dlg.close(li.getAttribute('data-pick')); });
    renderChips();
    renderTabs();
    load();
    return openDialog({
      title: 'Add gear', wide: true,
      body: h('div', { class: 'pf-root' }, [presets ? tabs : null, presets ? presets.el : null, libraryPanel]),
      onOpen: function (d) {
        dlg = d;
        createBtn = d.box.querySelector('footer button.primary');
        renderTabs();
        setTimeout(function () { if (tab === 'library') input.focus(); else if (presets) presets.focus(); }, 25);
      },
      buttons: [{ label: 'Cancel', value: null }].concat(presets ? [{
        label: 'Create device', primary: true,
        validate: function () { return !!presets.result(); },
        value: function () { return { preset: presets.result() }; },
      }] : []),
    }).then(function (id) {
      if (!id) return null;
      if (typeof id === 'object') return id.preset ? deepClone(id.preset) : null;
      const t = byId[id];
      if (t && Array.isArray(t.ports)) return deepClone(t);
      if (!ctx.api) return t || null;
      return ctx.api.template(id, ctx.project).catch(function (e) { toast(errMsg(e), 'err'); return null; });
    });
  };
}

function makePickPort(getCtx) {
  return function pickPort(opts) {
    opts = opts || {};
    const ctx = getCtx();
    const store = ctx.store;
    const doc = store.doc;
    const src = opts.compatibleWith || null;
    let srcPort = null;
    if (src) {
      const sd = (doc.devices || []).filter(function (d) { return d.id === src.device; })[0];
      srcPort = sd ? devicePorts(sd).filter(function (p) { return p.id === src.port; })[0] || null : null;
    }
    let room = opts.room !== undefined ? opts.room : store.room;
    let allRooms = room === '*' || room === undefined;
    const input = h('input', { type: 'search', class: 'search-input', placeholder: 'Filter devices and ports', 'aria-label': 'Filter ports', autofocus: true });
    const allBox = h('input', { type: 'checkbox', id: 'pp-all' });
    allBox.checked = allRooms;
    const list = h('ul', { class: 'pick-list', role: 'listbox', 'aria-label': 'Ports' });
    let dlg = null;
    function render() {
      list.innerHTML = '';
      const q = input.value.trim().toLowerCase();
      let count = 0;
      (doc.devices || []).forEach(function (d) {
        if (d.auto) return;
        if (!allRooms && (d.room || '') !== room) return;
        const rows = [];
        devicePorts(d).forEach(function (p) {
          if (src && d.id === src.device && p.id === src.port) return;
          let res = { level: 'ok', reason: '' };
          if (src) {
            const incoming = srcPort && srcPort.dir === 'in';
            res = incoming ? canConnect(doc, { device: d.id, port: p.id }, src, ctx.vocab) : canConnect(doc, src, { device: d.id, port: p.id }, ctx.vocab);
            if (res.level === 'error') return;
          }
          const text = (d.name + ' ' + (p.name || '') + ' ' + (p.label || '')).toLowerCase();
          if (q && text.indexOf(q) < 0) return;
          const m = mediumInfo(p.medium, ctx.vocab);
          rows.push(h('li', { 'data-pick': d.id + ':' + p.id, role: 'option' }, [
            h('span', { class: 'dot', style: { color: m.color } }),
            h('span', null, portLabel(p)),
            p.label && p.name ? h('span', { class: 'muted', style: { fontSize: '12px' } }, p.name) : null,
            h('span', { class: 'sub' }, [res.level === 'warn' ? h('span', { class: 'warn' }, res.reason + ' ') : null, m.short || p.medium || '']),
          ]));
        });
        if (rows.length) {
          list.appendChild(h('li', { class: 'group' }, deviceTitle(d)));
          rows.forEach(function (r) { list.appendChild(r); count++; });
        }
      });
      if (!count) list.appendChild(h('li', { class: 'group' }, 'No compatible ports' + (allRooms ? '' : ' in this room')));
    }
    input.addEventListener('input', render);
    allBox.addEventListener('change', function () { allRooms = allBox.checked; render(); });
    listNav(input, list, function (li) { if (dlg) dlg.close(li.getAttribute('data-pick')); });
    render();
    const title = src && srcPort ? 'Patch ' + portLabel(srcPort) + (srcPort.dir === 'in' ? ' from\u2026' : ' to\u2026') : 'Pick a port';
    return openDialog({
      title: title, wide: true,
      body: h('div', null, [input, h('label', { class: 'row', for: 'pp-all', style: { marginTop: '8px' } }, [allBox, 'All rooms']), list]),
      onOpen: function (d) { dlg = d; },
      buttons: [{ label: 'Cancel', value: null }],
    }).then(function (v) { return v ? parsePortRef(v) : null; });
  };
}

function makePickDevice(getCtx) {
  return function pickDevice(opts) {
    opts = opts || {};
    const ctx = getCtx();
    const input = h('input', { type: 'search', class: 'search-input', placeholder: 'Filter devices', 'aria-label': 'Filter devices', autofocus: true });
    const list = h('ul', { class: 'pick-list', role: 'listbox', 'aria-label': 'Devices' });
    let dlg = null;
    function render() {
      list.innerHTML = '';
      const f = Object.assign({ room: opts.room === undefined ? '*' : opts.room }, opts.filter || {}, { query: input.value });
      filterDevices(ctx.store.doc, f, ctx.vocab).forEach(function (d) {
        const disc = (ctx.vocab.disciplines || {})[disciplineOf(d, ctx.vocab)];
        list.appendChild(h('li', { 'data-pick': d.id, role: 'option' }, [h('span', { class: 'dot', style: { color: disc ? disc.color : '#9aa3b5' } }), deviceTitle(d), h('span', { class: 'sub' }, ((d.manufacturer || '') + ' ' + (d.model || '')).trim())]));
      });
    }
    input.addEventListener('input', render);
    listNav(input, list, function (li) { if (dlg) dlg.close(li.getAttribute('data-pick')); });
    render();
    return openDialog({ title: opts.title || 'Pick a device', body: h('div', null, [input, list]), onOpen: function (d) { dlg = d; }, buttons: [{ label: 'Cancel', value: null }] });
  };
}

// ------------------------------------------------------------ env

function detectEnv() {
  const ua = navigator.userAgent || '';
  const iOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  return {
    touch: !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches) || ('ontouchstart' in window),
    narrow: window.innerWidth < 700,
    platform: iOS ? 'ios' : (/Mac/.test(navigator.platform || '') ? 'mac' : 'other'),
    online: navigator.onLine !== false,
    secure: !!window.isSecureContext,
  };
}

// ------------------------------------------------------------ ctx

export function makeCtx(store, extras) {
  extras = extras || {};
  const ctx = {};
  const get = function () { return ctx; };
  Object.assign(ctx, {
    store: store,
    vocab: (store && store.vocab) || FALLBACK_VOCAB,
    api: null,
    project: '',
    meta: null,
    role: store && store.readOnly ? 'viewer' : 'admin',
    env: (typeof window !== 'undefined') ? detectEnv() : { touch: false, narrow: false, platform: 'other', online: true, secure: false },
    commit: function (ops, label) {
      if (!ops || !ops.length) return null;
      if (ctx.store.readOnly) { ctx.toast('Read-only: this change was not made', 'warn'); return null; }
      try {
        const d = ctx.store.commit(ops, label);
        announce(label);
        return d;
      } catch (e) {
        ctx.toast(errMsg(e), 'err');
        return null;
      }
    },
    select: function (sel) { ctx.store.select(sel); },
    highlight: function (hl) { ctx.store.highlight(hl); },
    ensureCss: ensureCss,
    viewCss: function (key) { return ensureCss((VIEWS[key] || {}).css); },
    navigate: function () {},
    toast: toast,
    confirm: confirmDialog,
    prompt: promptDialog,
    openDialog: openDialog,
    openInspector: function (sel) { if (sel) ctx.store.select(sel); },
    closeInspector: function () {},
    reload: function () { return Promise.resolve(null); },
    timeTravel: null,
  });
  ctx.pickTemplate = makePickTemplate(get);
  ctx.pickPort = makePickPort(get);
  ctx.pickDevice = makePickDevice(get);
  Object.keys(extras).forEach(function (k) { ctx[k] = extras[k]; });
  return ctx;
}

// ------------------------------------------------------------ router

export function parseHash(hash) {
  let s = String(hash || '').replace(/^#\/?/, '');
  let query = '';
  const qi = s.indexOf('?');
  if (qi >= 0) { query = s.slice(qi + 1); s = s.slice(0, qi); }
  const parts = s.split('/').map(function (p) { try { return decodeURIComponent(p); } catch (e) { return p; } });
  return { project: parts[0] || '', room: parts[1] || '', view: parts[2] || '', params: new URLSearchParams(query) };
}

export function buildHash(project, room, view, params) {
  let s = '#/' + encodeURIComponent(project || '') + '/' + encodeURIComponent(room || '').replace(/%2A/g, '*') + '/' + (view || DEFAULT_VIEW);
  const q = [];
  if (params) Object.keys(params).forEach(function (k) { if (params[k] !== undefined && params[k] !== null && params[k] !== '') q.push(encodeURIComponent(k) + '=' + encodeURIComponent(params[k]).replace(/%3A/g, ':')); });
  if (q.length) s += '?' + q.join('&');
  return s;
}

export function selToString(sel) {
  if (!sel) return '';
  if (sel.type === 'port') return 'port:' + (sel.device || sel.id) + ':' + sel.port;
  if (sel.type === 'marker') return 'marker:' + (sel.floorplan || '') + ':' + (sel.device || sel.id);
  return sel.type + ':' + sel.id;
}

export function selFromString(s) {
  if (!s) return null;
  const parts = String(s).split(':');
  const type = parts[0];
  if (type === 'port') return { type: 'port', id: parts[1], device: parts[1], port: parts[2] || null };
  if (type === 'marker') return { type: 'marker', id: parts[2], floorplan: parts[1], device: parts[2] };
  if (!parts[1]) return null;
  const sel = { type: type, id: parts[1] };
  if (type === 'device') sel.device = parts[1];
  if (parts[2]) { sel.port = parts[2]; sel.device = parts[1]; sel.type = type === 'device' ? 'port' : type; }
  return sel;
}

// ------------------------------------------------------------ shell

const A = {
  api: null, session: null, meta: null, vocab: FALLBACK_VOCAB, projects: [], project: '', store: null, queue: null,
  ctx: null, role: 'admin', view: '', viewHandle: null, viewToken: 0, viewStates: {}, inspector: null, assistant: null,
  inspectorOpen: false, sheetOpen: false, offline: false, travel: null, banner: null, unsubs: [], problems: [],
};

function $(id) { return document.getElementById(id); }

function disciplineVars(vocab) {
  const ds = (vocab && vocab.disciplines) || {};
  Object.keys(ds).forEach(function (k) { document.documentElement.style.setProperty('--discipline-' + k, ds[k].color); });
}

function on(target, type, fn, opts) {
  target.addEventListener(type, fn, opts);
  A.unsubs.push(function () { target.removeEventListener(type, fn, opts); });
}

function roomName(id) {
  if (id === '*') return 'All rooms';
  if (!A.store) return id;
  const r = (A.store.doc.rooms || []).filter(function (x) { return x.id === id; })[0];
  return r ? r.name : (id || 'Shared inventory');
}

function defaultRoom(doc) {
  const rooms = doc.rooms || [];
  const d = doc.settings && doc.settings.default_room;
  if (d && rooms.some(function (r) { return r.id === d; })) return d;
  return rooms.length ? rooms[0].id : '';
}

function currentHashParams(extra) {
  const r = parseHash(location.hash);
  const p = {};
  r.params.forEach(function (v, k) { p[k] = v; });
  return Object.assign(p, extra || {});
}

function replaceHash(project, room, view, params) {
  const nh = buildHash(project, room, view, params);
  if (location.hash !== nh) history.replaceState(null, '', location.pathname + location.search + nh);
}

function renderTabs() {
  const nav = $('app-views');
  nav.innerHTML = '';
  const strip = h('div', { class: 'app-views-strip' });
  Object.keys(VIEWS).forEach(function (k) {
    strip.appendChild(h('button', { type: 'button', 'data-view': k, 'aria-current': A.view === k ? 'page' : null, onclick: function () { navigate(k); } }, VIEWS[k].label));
  });
  const overflow = h('button', { type: 'button', class: 'app-views-more', 'aria-haspopup': 'menu', hidden: true }, ['More', h('span', { class: 'caret', 'aria-hidden': 'true' }, '\u25BE')]);
  overflow.addEventListener('click', function () {
    const items = Array.prototype.filter.call(strip.children, function (b) { return b.hidden; }).map(function (b) {
      const k = b.getAttribute('data-view');
      return { label: VIEWS[k].label, current: A.view === k, action: function () { navigate(k); } };
    });
    openMenu(overflow, items);
  });
  nav.appendChild(strip);
  nav.appendChild(overflow);
  fitTabs();
  const bar = $('app-tabbar');
  bar.innerHTML = '';
  PHONE_TABS.forEach(function (k) {
    bar.appendChild(h('button', { type: 'button', 'data-tab': k, 'aria-current': A.view === k ? 'page' : null, onclick: function () { navigate(k); } }, [h('span', { class: 'ico', 'aria-hidden': 'true' }, TAB_ICONS[k]), VIEWS[k].label]));
  });
  const moreOn = PHONE_TABS.indexOf(A.view) < 0;
  const more = h('button', { type: 'button', 'data-tab': 'more', 'aria-current': moreOn ? 'page' : null, 'aria-haspopup': 'menu' }, [h('span', { class: 'ico', 'aria-hidden': 'true' }, TAB_ICONS.more), 'More']);
  more.addEventListener('click', function () {
    const items = Object.keys(VIEWS).filter(function (k) { return PHONE_TABS.indexOf(k) < 0; }).map(function (k) { return { label: VIEWS[k].label, action: function () { navigate(k); } }; });
    items.push({ sep: true });
    items.push({ label: 'Search', action: openPalette });
    items.push({ label: 'Helper', action: function () { toggleAssistant(true); } });
    openMenu(more, items);
  });
  bar.appendChild(more);
}

// Tabs that do not fit the top bar move, last first, into the More menu.
function fitTabs() {
  const nav = $('app-views');
  const strip = nav && nav.querySelector('.app-views-strip');
  const more = nav && nav.querySelector('.app-views-more');
  if (!strip || !more) return;
  const tabs = strip.children;
  let i;
  for (i = 0; i < tabs.length; i++) tabs[i].hidden = false;
  more.hidden = true;
  more.removeAttribute('aria-current');
  if (!nav.offsetWidth || strip.scrollWidth <= strip.clientWidth) return;
  more.hidden = false;
  for (i = tabs.length - 1; i >= 0 && strip.scrollWidth > strip.clientWidth; i--) tabs[i].hidden = true;
  if (strip.querySelector('[aria-current][hidden]')) more.setAttribute('aria-current', 'page');
}

function renderPickers() {
  const ps = $('app-project');
  ps.innerHTML = '';
  A.projects.forEach(function (p) {
    ps.appendChild(h('option', { value: p.name, selected: p.name === A.project ? true : null }, p.title && p.title !== p.name ? p.name + ' \u00b7 ' + (p.org || p.title) : p.name));
  });
  if (A.role !== 'viewer') ps.appendChild(h('option', { value: '__new__' }, 'New project\u2026'));
  ps.value = A.project;
  const rs = $('app-room');
  rs.innerHTML = '';
  if (!A.store) return;
  const doc = A.store.doc;
  const venues = doc.venues || [];
  const rooms = (doc.rooms || []).slice().sort(function (a, b) { return (a.order || 0) - (b.order || 0); });
  const used = {};
  venues.forEach(function (v) {
    const vr = rooms.filter(function (r) { return r.venue === v.id; });
    if (!vr.length) return;
    const og = h('optgroup', { label: v.name || v.id });
    vr.forEach(function (r) { used[r.id] = true; og.appendChild(h('option', { value: r.id }, r.name || r.id)); });
    rs.appendChild(og);
  });
  rooms.forEach(function (r) { if (!used[r.id]) rs.appendChild(h('option', { value: r.id }, r.name || r.id)); });
  rs.appendChild(h('option', { value: '*' }, 'All rooms'));
  rs.value = A.store.room;
}

function liveSaveState() {
  const q = A.queue;
  if (!q) return { state: 'saved', pending: 0 };
  let st = q.state;
  if (st === 'idle' || st === 'saved') st = q.pending ? 'pending' : 'saved';
  return { state: st, pending: q.pending };
}

function saveLabel(d) {
  const rev = A.store ? A.store.revision : 0;
  const n = (d && d.pending) || (A.queue ? A.queue.pending : 0);
  const st = d ? d.state : 'saved';
  if (A.travel) return 'Viewing r' + A.travel.rev;
  if (A.store && A.store.readOnly && !n) return (A.offline ? 'Offline \u00b7 ' : 'Read-only \u00b7 ') + 'r' + rev;
  if (st === 'saving') return 'Saving\u2026';
  if (st === 'pending') return n + ' pending';
  if (st === 'offline') return 'Offline \u00b7 ' + n + ' pending';
  if (st === 'conflict') return 'Conflict';
  if (st === 'error') return n ? 'Save failed \u00b7 ' + n + ' pending' : 'Save failed';
  return 'Saved \u00b7 r' + rev;
}

function updateSave(d) {
  const b = $('app-save');
  if (!b) return;
  if (!d) d = liveSaveState();
  b.textContent = saveLabel(d);
  b.setAttribute('data-state', (d && d.state) || 'saved');
  b.title = (d && d.error ? d.error + ' \u00b7 ' : '') + 'Save now (Cmd/Ctrl+S)';
  const u = $('app-undo');
  const r = $('app-redo');
  if (u && A.store) { u.disabled = !A.store.canUndo; u.title = 'Undo ' + (A.store.undoLabel || '') + ' (Cmd/Ctrl+Z)'; }
  if (r && A.store) { r.disabled = !A.store.canRedo; r.title = 'Redo ' + (A.store.redoLabel || '') + ' (Shift+Cmd/Ctrl+Z)'; }
}

function refName(ref) {
  const i = ref.indexOf('/');
  if (i < 0) return ref;
  const coll = ref.slice(0, i);
  const id = ref.slice(i + 1);
  const ent = A.store ? (A.store.doc[coll] || []).filter(function (x) { return x.id === id; })[0] : null;
  return ent ? (ent.name || ent.tag || id) : id;
}

function setBanner(kind, content) {
  const b = $('app-banner');
  if (!b) return;
  b.className = 'app-banner' + (kind ? ' ' + kind : '');
  b.innerHTML = '';
  if (content) (Array.isArray(content) ? content : [content]).forEach(function (c) { if (c) b.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
}

function refreshBanner() {
  if (A.travel) {
    setBanner('info', [
      h('b', null, 'Viewing revision ' + A.travel.rev + ' (read-only). '),
      h('button', { type: 'button', class: 'small', onclick: function () { endTimeTravel(); } }, 'Back to current'),
      A.role !== 'viewer' ? h('button', { type: 'button', class: 'small primary', onclick: function () { restoreRevision(A.travel.rev); } }, 'Restore this revision') : null,
    ]);
    return;
  }
  const q = A.queue;
  if (q && q.state === 'conflict' && q.conflict) {
    const names = (q.conflict.conflicts || []).map(refName);
    setBanner('err', [
      h('span', null, 'Someone else changed ' + (names.length ? names.slice(0, 4).join(', ') + (names.length > 4 ? ' and ' + (names.length - 4) + ' more' : '') : 'this project') + (q.conflict.by && q.conflict.by.length ? ' (' + q.conflict.by.join(', ') + ')' : '') + '. '),
      h('button', { type: 'button', class: 'small', id: 'app-conflict-reload', onclick: function () { q.resolveConflict('reload').then(afterResync); } }, 'Reload'),
      h('button', { type: 'button', class: 'small', id: 'app-conflict-keep', onclick: function () { q.resolveConflict('keep').then(afterResync); } }, 'Keep mine'),
    ]);
    return;
  }
  if (A.offline) { setBanner('warn', 'Offline copy \u00b7 read-only. Edits come back when the server is reachable.'); return; }
  if (navigator.onLine === false || (q && q.state === 'offline')) { setBanner('warn', 'Offline \u00b7 ' + (q ? q.pending : 0) + ' pending edits. They are kept on this device and sent when you reconnect.'); return; }
  if (A.store && A.store.readOnly) { setBanner('info', 'Read-only access. You can browse, search and trace.'); return; }
  setBanner('', null);
}

function afterResync() {
  renderPickers();
  refreshBanner();
  updateSave(null);
}

function layoutInspector() {
  const body = $('app-body');
  if (!body) return;
  body.classList.toggle('has-inspector', !!A.inspectorOpen);
  body.classList.toggle('sheet-open', !!A.sheetOpen);
}

function openInspector(sel) {
  if (sel) A.store.select(sel);
  A.inspectorOpen = true;
  A.sheetOpen = true;
  layoutInspector();
  ensureInspector();
}

function closeInspector() {
  A.sheetOpen = false;
  A.inspectorOpen = false;
  layoutInspector();
}

function ensureInspector() {
  if (A.inspector || !A.ctx) return;
  A.inspector = { destroy: function () {} };
  const el = $('app-inspector');
  import('./inspector.js').then(function (m) {
    if (!A.ctx) return;
    el.innerHTML = '';
    A.inspector = m.mountInspector(el, A.ctx) || { destroy: function () {} };
  }, function (e) {
    el.innerHTML = '';
    el.appendChild(errorCard('Inspector', e));
  });
}

function errorCard(name, e) {
  return h('div', { class: 'app-error-card', role: 'alert', 'data-error-view': name }, [
    h('h3', null, name + ' is not available'),
    h('div', null, 'This part of Fathom failed to load. The rest of the app keeps working.'),
    h('pre', null, errMsg(e)),
  ]);
}

function navigate(view, params) {
  params = params || {};
  const v = view || A.view || DEFAULT_VIEW;
  const room = params.room !== undefined ? params.room : (A.store ? A.store.room : '');
  const extra = {};
  if (params.sel) extra.sel = params.sel;
  else if (A.store && A.store.selection && params.keepSel !== false) extra.sel = selToString(A.store.selection);
  const nh = buildHash(A.project, room, v, extra);
  if (location.hash === nh) onHash();
  else location.hash = nh;
}

function mountInternal(key, el, ctx) {
  if (key === 'map') return mountMap(el, ctx);
  if (key === 'json') return mountJson(el, ctx);
  return { destroy: function () {} };
}

function mountView(key) {
  if (!VIEWS[key]) key = DEFAULT_VIEW;
  const token = ++A.viewToken;
  if (A.viewHandle) {
    try { if (A.viewHandle.getState) A.viewStates[A.view] = A.viewHandle.getState(); } catch (e) { /* ignore */ }
    try { if (A.viewHandle.destroy) A.viewHandle.destroy(); } catch (e) { console.warn(e); }
  }
  A.viewHandle = null;
  A.view = key;
  renderTabs();
  const host = $('app-main');
  host.innerHTML = '';
  const el = h('div', { class: 'app-view', 'data-view': key });
  host.appendChild(el);
  const def = VIEWS[key];
  const done = function (handle) {
    if (token !== A.viewToken) { if (handle && handle.destroy) handle.destroy(); return; }
    A.viewHandle = handle || { destroy: function () {} };
    const st = A.viewStates[key];
    if (st && A.viewHandle.setState) { try { A.viewHandle.setState(st); } catch (e) { /* ignore */ } }
    if (A.store && A.store.selection && A.viewHandle.focus) { try { A.viewHandle.focus(A.store.selection); } catch (e) { /* ignore */ } }
    markRendered();
  };
  if (def.internal) { done(mountInternal(key, el, A.ctx)); return Promise.resolve(); }
  ensureCss(def.css);
  let mod = def.module;
  if (urlParam('debug_missing_view') === key) mod = './__missing_view_' + key + '.js';
  el.appendChild(h('div', { class: 'app-loading' }, 'Loading ' + def.label + '\u2026'));
  return import(mod).then(function (m) {
    if (token !== A.viewToken) return;
    const fn = m[def.export];
    if (typeof fn !== 'function') throw new Error(def.module + ' has no export "' + def.export + '"');
    el.innerHTML = '';
    done(fn(el, A.ctx));
  }).catch(function (e) {
    if (token !== A.viewToken) return;
    el.innerHTML = '';
    el.appendChild(errorCard(def.label, e));
    done({ destroy: function () {} });
  });
}

// ---- map view (iframe of the server viewer)

function mapUrl(room) {
  const doc = A.store.doc;
  const def = defaultRoom(doc);
  const r = room && room !== '*' ? room : def;
  return appRoot() + 'p/' + encodeURIComponent(A.project) + (r && r !== def ? '/r/' + encodeURIComponent(r) : '');
}

function mountMap(el, ctx) {
  const store = ctx.store;
  const frame = h('iframe', { class: 'map-frame', title: 'Signal-flow map', src: mapUrl(store.room) });
  const note = h('span', { class: 'muted', style: { fontSize: '12px' } }, 'Shows the last saved revision.');
  const bar = h('div', { class: 'map-bar' }, [
    h('b', null, roomName(store.room === '*' ? defaultRoom(store.doc) : store.room)),
    note,
    h('span', { class: 'grow' }),
    store.readOnly ? null : h('button', { type: 'button', id: 'map-groups', onclick: function () { groupsDialog(ctx); } }, 'Groups & columns'),
    h('button', { type: 'button', onclick: function () { frame.src = mapUrl(store.room); } }, 'Reload'),
    h('a', { href: mapUrl(store.room), target: '_blank', rel: 'noopener', class: 'chip' }, 'Open viewer'),
  ]);
  el.appendChild(bar);
  el.appendChild(frame);
  let timer = null;
  function reload() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(function () { try { frame.contentWindow.location.reload(); } catch (e) { frame.src = mapUrl(store.room); } }, 600);
  }
  function onRoom() { frame.src = mapUrl(store.room); bar.firstChild.textContent = roomName(store.room); }
  function onHl(e) {
    const hl = e.detail;
    const msg = { type: 'fathom:highlight', nodes: [], edges: [] };
    if (hl) {
      msg.nodes = (hl.devices || []).slice();
      (hl.cables || []).forEach(function (cid) {
        const c = (store.doc.cables || []).filter(function (x) { return x.id === cid; })[0];
        if (c && c.from && c.to) msg.edges.push([c.from.device, c.to.device]);
      });
    }
    try { frame.contentWindow.postMessage(msg, location.origin); } catch (err) { /* frame not ready */ }
  }
  store.addEventListener('revision', reload);
  store.addEventListener('room', onRoom);
  store.addEventListener('highlight', onHl);
  return { destroy: function () { if (timer) clearTimeout(timer); store.removeEventListener('revision', reload); store.removeEventListener('room', onRoom); store.removeEventListener('highlight', onHl); } };
}

function groupsDialog(ctx) {
  const store = ctx.store;
  const roomId = store.room && store.room !== '*' ? store.room : defaultRoom(store.doc);
  const room = (store.doc.rooms || []).filter(function (r) { return r.id === roomId; })[0];
  if (!room) { toast('No room to configure', 'warn'); return; }
  const flow = deepClone(room.flow || {});
  const groups = flow.groups || [];
  const columns = flow.columns || [];
  const spine = Object.assign({ label: 'Dante network', show: true }, flow.spine || {});
  const options = Object.assign({ auto_dante_nodes: true, auto_sources: true, dante_counts: false, appendix: true }, flow.options || {});
  function rowsTable(list, fields) {
    const tb = h('tbody');
    const table = h('table', { class: 'adm-table' }, [h('thead', null, h('tr', null, fields.map(function (f) { return h('th', { scope: 'col' }, f[1]); }).concat([h('th', { scope: 'col' }, '')]))), tb]);
    function draw() {
      tb.innerHTML = '';
      list.forEach(function (g, i) {
        const tr = h('tr');
        fields.forEach(function (f) {
          let input;
          if (f[0] === 'side') {
            input = h('select', { 'aria-label': f[1] }, ['left', 'right'].concat(fields.extraSides || []).map(function (s) { return h('option', { value: s, selected: (g.side || 'left') === s ? true : null }, s); }));
          } else {
            input = h('input', { value: g[f[0]] || '', 'aria-label': f[1] });
          }
          input.addEventListener('change', function () { if (input.value) g[f[0]] = input.value; else delete g[f[0]]; });
          tr.appendChild(h('td', null, input));
        });
        tr.appendChild(h('td', null, h('button', { type: 'button', class: 'small danger', 'aria-label': 'Remove', onclick: function () { list.splice(i, 1); draw(); } }, '\u00d7')));
        tb.appendChild(tr);
      });
    }
    draw();
    return { table: table, add: function (row) { list.push(row); draw(); } };
  }
  const gFields = [['id', 'Id'], ['label', 'Label'], ['side', 'Side'], ['note', 'Note']];
  const cFields = [['id', 'Id'], ['label', 'Label'], ['side', 'Side']];
  cFields.extraSides = ['spine'];
  const gt = rowsTable(groups, gFields);
  const ct = rowsTable(columns, cFields);
  const spLabel = h('input', { value: spine.label || '', 'aria-label': 'Spine label' });
  const spShow = h('input', { type: 'checkbox', id: 'gc-spine-show' });
  spShow.checked = spine.show !== false;
  const optBoxes = {};
  const optRow = h('div', { class: 'row' }, ['auto_dante_nodes', 'auto_sources', 'dante_counts', 'appendix'].map(function (k) {
    const b = h('input', { type: 'checkbox', id: 'gc-opt-' + k });
    b.checked = !!options[k];
    optBoxes[k] = b;
    return h('label', { class: 'row', for: 'gc-opt-' + k }, [b, k.replace(/_/g, ' ')]);
  }));
  openDialog({
    title: 'Groups & columns \u00b7 ' + (room.name || room.id), wide: true,
    body: h('div', { class: 'adm', style: { padding: '0' } }, [
      h('h3', null, 'Groups'), gt.table, h('button', { type: 'button', class: 'small', onclick: function () { gt.add({ id: String.fromCharCode(65 + groups.length), label: 'New group', side: 'left' }); } }, 'Add group'),
      h('h3', null, 'Columns'), ct.table, h('button', { type: 'button', class: 'small', onclick: function () { ct.add({ id: 'col-' + (columns.length + 1), label: 'Column', side: 'right' }); } }, 'Add column'),
      h('h3', null, 'Spine'), h('div', { class: 'row' }, [spLabel, h('label', { class: 'row', for: 'gc-spine-show' }, [spShow, 'Show spine'])]),
      h('h3', null, 'Options'), optRow,
    ]),
    buttons: [{ label: 'Cancel', value: null }, { label: 'Save', primary: true, value: 'save' }],
  }).then(function (v) {
    if (v !== 'save') return;
    const o = {};
    Object.keys(optBoxes).forEach(function (k) { o[k] = optBoxes[k].checked; });
    const nf = { groups: groups.filter(function (g) { return g.id; }), columns: columns.filter(function (c) { return c.id; }), spine: { label: spLabel.value || 'Dante network', show: spShow.checked }, options: o };
    ctx.commit([{ op: 'merge', coll: 'rooms', id: room.id, value: { flow: nf } }], 'Edit map groups & columns');
  });
}

// ---- JSON view

function mountJson(el, ctx) {
  const store = ctx.store;
  const ta = h('textarea', { spellcheck: 'false', 'aria-label': 'Project JSON', readonly: store.readOnly ? true : null });
  const status = h('span', { class: 'muted' });
  function fill() { ta.value = JSON.stringify(store.doc, null, 2); status.textContent = 'Revision ' + store.revision; }
  fill();
  const apply = h('button', { type: 'button', class: 'primary', disabled: store.readOnly || !ctx.api ? true : null, onclick: function () {
    let doc;
    try { doc = JSON.parse(ta.value); } catch (e) { toast('Invalid JSON: ' + errMsg(e), 'err'); return; }
    const go = function () {
      ctx.api.putProject(ctx.project, doc, store.revision, 'JSON edit').then(function (r) {
        toast('Saved revision ' + r.revision + (r.rebased ? ' (merged with newer changes)' : ''), 'ok');
        return ctx.reload();
      }).then(fill).catch(function (e) { toast(errMsg(e), 'err'); });
    };
    if (A.queue && A.queue.pending) A.queue.flush().then(go); else go();
  } }, 'Apply');
  const dl = h('a', { class: 'chip', href: ctx.api ? ctx.api.url('api/v2/projects/' + encodeURIComponent(ctx.project) + '/doc.json') : '#', download: ctx.project + '-project.json' }, 'Download');
  el.appendChild(h('div', { class: 'json-view' }, [h('div', { class: 'row' }, [apply, h('button', { type: 'button', onclick: fill }, 'Revert'), dl, status]), ta]));
  function onDoc(e) { if (document.activeElement !== ta && e.detail.source !== 'local') fill(); else status.textContent = 'Changed since loaded \u00b7 Revert to refresh'; }
  store.addEventListener('doc', onDoc);
  return { destroy: function () { store.removeEventListener('doc', onDoc); } };
}

// ---- palette

function openPalette() {
  if (!A.store) return;
  if ($('app-palette')) { $('app-palette-input').focus(); return; }
  const opener = document.activeElement;
  const input = h('input', { id: 'app-palette-input', type: 'search', placeholder: 'Search devices, ports, cables, IPs, rooms\u2026', 'aria-label': 'Search', autocomplete: 'off', role: 'combobox', 'aria-controls': 'app-palette-list', 'aria-expanded': 'true' });
  const list = h('ul', { id: 'app-palette-list', role: 'listbox' });
  const foot = h('div', { class: 'foot' }, '\u2191\u2193 to move \u00b7 Enter to open \u00b7 Esc to close');
  const box = h('div', { class: 'box', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Search' }, [input, list, foot]);
  const pal = h('div', { id: 'app-palette', class: 'app-palette' }, box);
  let hits = [];
  let idx = 0;
  let timer = null;
  let seq = 0;
  function close() { pal.remove(); document.removeEventListener('keydown', onKey, true); if (opener && opener.focus) opener.focus(); }
  function render() {
    list.innerHTML = '';
    let lastKind = '';
    hits.forEach(function (hit, i) {
      if (hit.kind !== lastKind) { lastKind = hit.kind; list.appendChild(h('li', { class: 'kind', role: 'presentation' }, hit.kind + 's')); }
      const li = h('li', { role: 'option', 'data-hit-kind': hit.kind, 'data-hit-id': hit.id, 'aria-selected': i === idx ? 'true' : 'false' }, [h('span', null, hit.title), h('span', { class: 'sub' }, hit.subtitle || '')]);
      li.addEventListener('click', function () { pick(hit); });
      li.addEventListener('pointermove', function () { if (idx !== i) { idx = i; mark(); } });
      list.appendChild(li);
    });
    if (!hits.length && input.value.trim()) list.appendChild(h('li', { class: 'kind' }, 'No matches'));
  }
  function mark() {
    Array.prototype.forEach.call(list.querySelectorAll('li[data-hit-id]'), function (li, i) { li.setAttribute('aria-selected', i === idx ? 'true' : 'false'); if (i === idx) li.scrollIntoView({ block: 'nearest' }); });
  }
  function search() {
    const q = input.value.trim();
    const my = ++seq;
    if (!q) { hits = []; render(); return; }
    const local = function () { hits = searchLocal(A.store.doc, q, 20); idx = 0; render(); foot.textContent = 'Offline search \u00b7 Enter to open'; };
    if (!A.api || A.offline || navigator.onLine === false) { local(); return; }
    A.api.search(A.project, q, { limit: 20 }).then(function (r) { if (my !== seq) return; hits = (r && r.hits) || []; idx = 0; render(); }, function () { if (my === seq) local(); });
  }
  function pick(hit) {
    close();
    const store = A.store;
    if (hit.room !== null && hit.room !== undefined && hit.room !== store.room && store.room !== '*' && ['device', 'port'].indexOf(hit.kind) >= 0 && hit.room !== '') store.setRoom(hit.room);
    if (hit.kind === 'device') navigate('patch', { sel: 'device:' + hit.device, keepSel: false });
    else if (hit.kind === 'port') navigate('patch', { sel: 'port:' + hit.device + ':' + hit.port, keepSel: false });
    else if (hit.kind === 'cable') navigate('schedules', { sel: 'cable:' + hit.id, keepSel: false });
    else if (hit.kind === 'interface') openInspector({ type: 'device', id: hit.device, device: hit.device });
    else if (hit.kind === 'room') { store.setRoom(hit.id); navigate(A.view); }
    else if (hit.kind === 'rack') navigate('racks', { sel: 'rack:' + hit.id, keepSel: false });
    else if (hit.kind === 'floorplan') navigate('plan', { sel: 'floorplan:' + hit.id, keepSel: false });
    else if (hit.kind === 'attachment' && hit.device) openInspector({ type: 'device', id: hit.device, device: hit.device });
    else if (hit.kind === 'page') location.hash = buildHash(A.project, store.room, 'sop', { page: hit.id });
  }
  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); idx = Math.min(hits.length - 1, idx + 1); mark(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); idx = Math.max(0, idx - 1); mark(); }
    else if (e.key === 'Enter') { if (hits[idx]) { e.preventDefault(); pick(hits[idx]); } }
    else if (e.key === 'Tab') { e.preventDefault(); input.focus(); }
  }
  input.addEventListener('input', function () { if (timer) clearTimeout(timer); timer = setTimeout(search, 150); });
  pal.addEventListener('pointerdown', function (e) { if (e.target === pal) close(); });
  document.addEventListener('keydown', onKey, true);
  document.body.appendChild(pal);
  input.focus();
}

// ---- menus

function openMenu(anchor, items) {
  const old = document.querySelector('.app-menu');
  if (old) old.remove();
  const menu = h('div', { class: 'app-menu', role: 'menu' });
  items.forEach(function (it) {
    if (it.sep) { menu.appendChild(h('div', { class: 'sep', role: 'separator' })); return; }
    if (it.info) { menu.appendChild(h('div', { class: 'lbl' }, it.info)); return; }
    menu.appendChild(h('button', { type: 'button', role: 'menuitem', 'aria-current': it.current ? 'page' : null, onclick: function () { close(); it.action(); } }, it.label));
  });
  document.body.appendChild(menu);
  const r = anchor.getBoundingClientRect();
  const mw = menu.offsetWidth;
  const mh = menu.offsetHeight;
  let top = r.bottom + 4;
  if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 4);
  menu.style.top = top + 'px';
  menu.style.left = Math.max(8, Math.min(window.innerWidth - mw - 8, r.right - mw)) + 'px';
  const first = menu.querySelector('button');
  if (first) first.focus();
  function close() { menu.remove(); document.removeEventListener('pointerdown', outside, true); document.removeEventListener('keydown', key, true); }
  function outside(e) { if (!menu.contains(e.target)) close(); }
  function key(e) {
    if (e.key === 'Escape') { e.preventDefault(); close(); anchor.focus(); }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const bs = Array.prototype.slice.call(menu.querySelectorAll('button'));
      const i = bs.indexOf(document.activeElement);
      const n = bs[(i + (e.key === 'ArrowDown' ? 1 : bs.length - 1)) % bs.length];
      if (n) n.focus();
    }
  }
  setTimeout(function () { document.addEventListener('pointerdown', outside, true); document.addEventListener('keydown', key, true); }, 0);
}

function userMenu() {
  const s = A.session || {};
  const u = s.user;
  const items = [{ info: u ? u.username + ' \u00b7 ' + u.role : (s.auth_enabled ? 'Not signed in' : 'Local mode (no login)') }];
  items.push({ label: 'Make available offline', action: makeOffline });
  items.push({ label: 'Keyboard shortcuts', action: shortcutsDialog });
  if (s.auth_enabled && u) {
    items.push({ label: 'Change password', action: changePasswordDialog });
    items.push({ sep: true });
    items.push({ label: 'Log out', action: function () { A.api.logout().then(function () { location.href = appRoot() + 'login'; }, function (e) { toast(errMsg(e), 'err'); }); } });
  }
  openMenu($('app-user'), items);
}

function shortcutsDialog() {
  const rows = [['Cmd/Ctrl+K', 'Search'], ['Cmd/Ctrl+J', 'Helper (assistant)'], ['Cmd/Ctrl+S', 'Save now'], ['Cmd/Ctrl+Z', 'Undo'], ['Shift+Cmd/Ctrl+Z, Ctrl+Y', 'Redo'], ['Esc', 'Close dialogs, panels and highlights']];
  openDialog({ title: 'Keyboard shortcuts', body: h('table', { class: 'adm-table' }, h('tbody', null, rows.map(function (r) { return h('tr', null, [h('th', { scope: 'row' }, r[0]), h('td', null, r[1])]); }))), buttons: [{ label: 'Close', value: null, primary: true }] });
}

function changePasswordDialog() {
  const old = h('input', { type: 'password', autocomplete: 'current-password', id: 'pw-old' });
  const nw = h('input', { type: 'password', autocomplete: 'new-password', id: 'pw-new' });
  openDialog({
    title: 'Change password',
    body: h('div', null, [h('div', { class: 'field' }, [h('label', { for: 'pw-old' }, 'Current'), old]), h('div', { class: 'field' }, [h('label', { for: 'pw-new' }, 'New (8+ chars)'), nw])]),
    buttons: [{ label: 'Cancel', value: null }, { label: 'Change', primary: true, value: 'ok' }],
  }).then(function (v) {
    if (v !== 'ok') return;
    A.api.changePassword(old.value, nw.value).then(function () { toast('Password changed. Other sessions are signed out.', 'ok'); }, function (e) { toast(errMsg(e), 'err'); });
  });
}

function makeOffline() {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) { toast('Offline mode needs HTTPS (or localhost).', 'warn'); return; }
  A.api.offlineManifest(A.project).then(function (r) {
    const urls = ((r && r.urls) || []).map(function (u) { return new URL(u, appRoot()).href; });
    return navigator.serviceWorker.ready.then(function (reg) {
      const sw = navigator.serviceWorker.controller || reg.active;
      if (!sw) throw new Error('Service worker not active yet; reload and try again.');
      toast('Saving ' + urls.length + ' pages for offline use\u2026');
      sw.postMessage({ type: 'fathom:prefetch', urls: urls });
    });
  }).catch(function (e) { toast(errMsg(e), 'err'); });
}

function registerSW() {
  if (!('serviceWorker' in navigator) || !window.isSecureContext || location.protocol === 'file:') return;
  const root = appRoot();
  navigator.serviceWorker.register(root + 'sw.js', { scope: new URL(root).pathname }).catch(function (e) { console.warn('service worker: ' + errMsg(e)); });
  navigator.serviceWorker.addEventListener('message', function (e) {
    const d = e.data || {};
    if (d.type === 'fathom:prefetched') toast('Available offline: ' + d.ok + ' saved' + (d.failed && d.failed.length ? ', ' + d.failed.length + ' failed' : ''), d.failed && d.failed.length ? 'warn' : 'ok');
  });
}

// ---- assistant panel

function toggleAssistant(force) {
  const el = $('app-assistant');
  if (!el || !A.ctx) return;
  const open = force === undefined ? !el.classList.contains('open') : !!force;
  el.classList.toggle('open', open);
  el.setAttribute('aria-hidden', open ? 'false' : 'true');
  if ($('app')) $('app').classList.toggle('ast-open', open);
  if (open && !A.assistant) {
    A.assistant = { destroy: function () {} };
    import('./assistant-ui.js').then(function (m) {
      el.innerHTML = '';
      A.assistant = m.mountAssistant(el, Object.assign({}, A.ctx, { closePanel: function () { toggleAssistant(false); } })) || { destroy: function () {} };
      if (A.assistant.focus) A.assistant.focus();
    }, function (e) { el.innerHTML = ''; el.appendChild(errorCard('Assistant', e)); });
  } else if (open && A.assistant && A.assistant.focus) {
    A.assistant.focus();
  }
  if (!open) $('app-assistant-btn').focus();
}

// ---- time travel / restore

function startTimeTravel(rev) {
  if (!A.api) return Promise.resolve();
  return A.api.historyDoc(A.project, rev).then(function (r) {
    if (!A.travel) A.travel = { rev: rev, doc: A.store.doc, revision: A.store.revision, readOnly: A.store.readOnly };
    A.travel.rev = rev;
    A.store.setReadOnly(true);
    A.store.replaceDoc(r.doc, A.travel.revision, 'history');
    refreshBanner();
    updateSave(null);
  }).catch(function (e) { toast(errMsg(e), 'err'); });
}

function endTimeTravel() {
  const t = A.travel;
  if (!t) return;
  A.travel = null;
  A.store.replaceDoc(t.doc, t.revision, 'load');
  A.store.setReadOnly(t.readOnly);
  refreshBanner();
  updateSave(null);
}

function restoreRevision(rev) {
  confirmDialog('Restore revision ' + rev + ' as a new revision? Nothing is lost; the current state stays in history.', { ok: 'Restore' }).then(function (yes) {
    if (!yes) return;
    const base = A.travel ? A.travel.revision : A.store.revision;
    if (A.travel) endTimeTravel();
    A.api.restore(A.project, rev, base).then(function (r) {
      toast('Restored as revision ' + r.revision, 'ok');
      return A.queue.resync();
    }).then(afterResync).catch(function (e) { toast(errMsg(e), 'err'); });
  });
}

// ---- new project

function newProjectDialog() {
  const name = h('input', { id: 'np-name', placeholder: 'e.g. riverside', autocapitalize: 'none', autocomplete: 'off' });
  const org = h('input', { id: 'np-org', placeholder: 'Organization' });
  const tpl = h('select', { id: 'np-template' }, [h('option', { value: 'blank' }, 'Blank')].concat(((A.meta && A.meta.samples) || []).map(function (s) { return h('option', { value: s }, 'Sample: ' + s); })));
  name.addEventListener('input', function () { if (!org.value) org.placeholder = name.value ? name.value : 'Organization'; });
  return openDialog({
    title: 'New project',
    body: h('div', null, [h('div', { class: 'field' }, [h('label', { for: 'np-name' }, 'Name'), name]), h('div', { class: 'field' }, [h('label', { for: 'np-org' }, 'Organization'), org]), h('div', { class: 'field' }, [h('label', { for: 'np-template' }, 'Start from'), tpl])]),
    buttons: [{ label: 'Cancel', value: null }, { label: 'Create', primary: true, value: 'ok', validate: function () { if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(name.value || slug(name.value))) { toast('Use letters, digits, dot, dash or underscore', 'warn'); return false; } return true; } }],
  }).then(function (v) {
    if (v !== 'ok') { renderPickers(); return; }
    const n = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(name.value) ? name.value : slug(name.value);
    return A.api.createProject({ name: n, template: tpl.value, org: org.value }).then(function () {
      return A.api.listProjects();
    }).then(function (r) {
      A.projects = (r && r.projects) || [];
      location.hash = buildHash(n, '', DEFAULT_VIEW);
    }).catch(function (e) { toast(errMsg(e), 'err'); renderPickers(); });
  });
}

// ---- project load / teardown

function teardown() {
  A.unsubs.forEach(function (f) { try { f(); } catch (e) { /* ignore */ } });
  A.unsubs = [];
  if (A.viewHandle && A.viewHandle.destroy) { try { A.viewHandle.destroy(); } catch (e) { /* ignore */ } }
  A.viewHandle = null;
  if (A.inspector && A.inspector.destroy) { try { A.inspector.destroy(); } catch (e) { /* ignore */ } }
  A.inspector = null;
  if (A.assistant && A.assistant.destroy) { try { A.assistant.destroy(); } catch (e) { /* ignore */ } }
  A.assistant = null;
  const ins = $('app-inspector');
  if (ins) ins.innerHTML = '';
  const ast = $('app-assistant');
  if (ast) { ast.innerHTML = ''; ast.classList.remove('open'); }
  if ($('app')) $('app').classList.remove('ast-open');
  A.viewStates = {};
  A.travel = null;
}

function loadProject(name, route) {
  teardown();
  A.project = name;
  $('app-main').innerHTML = '<div class="app-loading">Loading ' + esc(name) + '\u2026</div>';
  return A.api.getProject(name).then(function (p) {
    A.offline = !!p.offline;
    A.role = p.role || 'admin';
    const doc = p.doc || {};
    let room = route.room;
    if (room !== '*' && !(doc.rooms || []).some(function (r) { return r.id === room; })) room = defaultRoom(doc);
    const store = createStore({ doc: doc, vocab: A.vocab, readOnly: A.role === 'viewer' || A.offline, room: room, revision: p.revision });
    A.store = store;
    A.problems = p.problems || [];
    let storage = null;
    try { storage = window.localStorage; } catch (e) { storage = null; }
    const queue = new ChangeQueue({ api: A.api, project: name, store: store, storage: storage, autosave: !(doc.settings && doc.settings.autosave === false) });
    A.queue = queue;
    const restored = queue.takeRestored();
    if (restored.length && !store.readOnly) {
      try { store.applyRemote(restored, 'pending'); toast(restored.length + ' offline edits restored; sending\u2026'); } catch (e) { toast('Could not re-apply offline edits: ' + errMsg(e), 'warn'); }
      queue.flush();
    }
    const ctx = makeCtx(store, {
      api: A.api, project: name, meta: A.meta, role: A.role, session: A.session,
      navigate: navigate,
      openInspector: openInspector,
      closeInspector: closeInspector,
      reload: function () { return queue.resync().then(function (r) { afterResync(); return r; }); },
      flush: function () { return queue.flush(); },
      timeTravel: startTimeTravel,
      endTimeTravel: endTimeTravel,
      restoreRevision: restoreRevision,
      queue: queue,
      appRoot: appRoot(),
      isTimeTravel: function () { return !!A.travel; },
    });
    A.ctx = ctx;
    on(store, 'doc', function (e) {
      const d = e.detail;
      if (d.source === 'local' || d.source === 'undo' || d.source === 'redo') {
        if (A.travel) return;
        queue.enqueue(d.ops, d.label || d.source);
        if (d.source !== 'local') announce((d.source === 'undo' ? 'Undid ' : 'Redid ') + (d.label || 'edit'));
      }
      if (d.touched && d.touched.some(function (r) { return r.indexOf('rooms/') === 0 || r.indexOf('venues/') === 0; })) renderPickers();
      if (d.source === 'load') renderPickers();
      updateSave(null);
    });
    on(store, 'selection', function (e) {
      const sel = e.detail;
      const r = parseHash(location.hash);
      replaceHash(A.project, store.room, r.view || A.view, currentHashParams({ sel: sel ? selToString(sel) : '' }));
      if (sel && window.innerWidth >= 1100) { A.inspectorOpen = true; ensureInspector(); }
      if (!sel && window.innerWidth >= 1100) A.inspectorOpen = false;
      layoutInspector();
    });
    on(store, 'room', function () {
      $('app-room').value = store.room;
      replaceHash(A.project, store.room, A.view, currentHashParams());
    });
    on(store, 'error', function (e) { toast(errMsg(e.detail && e.detail.error), 'err'); });
    on(queue, 'state', function (e) { updateSave(e.detail); refreshBanner(); });
    on(queue, 'dropped', function (e) { toast('Change rejected by the server: ' + errMsg(e.detail.error) + '. Reloaded the project.', 'err'); });
    on(queue, 'problems', function (e) { A.problems = e.detail || []; });
    on(window, 'online', function () { refreshBanner(); queue.flush(); });
    on(window, 'offline', refreshBanner);
    on(window, 'beforeunload', function (e) { if (queue.pending && navigator.onLine !== false) { queue.flush(); e.preventDefault(); e.returnValue = ''; } });
    renderPickers();
    refreshBanner();
    updateSave(null);
    // overlay in the background
    A.api.overlay(name).then(function (o) { if (A.store === store) store.setOverlay(o); }, function () { /* overlay optional */ });
    const sel = selFromString(route.params.get('sel'));
    const view = VIEWS[route.view] ? route.view : DEFAULT_VIEW;
    replaceHash(name, room, view, currentHashParams());
    if (sel) {
      store.select(sel);
      openInspector(sel);
    }
    return mountView(view);
  }).catch(function (e) {
    const main = $('app-main');
    main.innerHTML = '';
    if (e instanceof ApiError && e.status === 401) { location.href = appRoot() + 'login?next=' + encodeURIComponent(location.pathname + location.search + location.hash); return; }
    const card = errorCard('Project "' + name + '"', e);
    if (e instanceof ApiError && e.status === 0) card.appendChild(h('p', null, 'You are offline and this project has not been saved for offline use.'));
    main.appendChild(card);
    markRendered();
  });
}

function onHash() {
  const r = parseHash(location.hash);
  if (!r.project) {
    if (A.projects.length) { location.replace(location.pathname + location.search + buildHash(A.projects[0].name, '', DEFAULT_VIEW)); }
    return;
  }
  if (r.project !== A.project || !A.store) { loadProject(r.project, r); return; }
  const store = A.store;
  if (r.room && r.room !== store.room && (r.room === '*' || (store.doc.rooms || []).some(function (x) { return x.id === r.room; }))) store.setRoom(r.room);
  const sel = selFromString(r.params.get('sel'));
  if (sel && selToString(sel) !== selToString(store.selection)) store.select(sel);
  const view = VIEWS[r.view] ? r.view : DEFAULT_VIEW;
  if (view !== A.view) mountView(view);
  else if (sel && A.viewHandle && A.viewHandle.focus) { try { A.viewHandle.focus(sel); } catch (e) { /* ignore */ } }
}

function emptyState() {
  const main = $('app-main');
  main.innerHTML = '';
  main.appendChild(h('div', { class: 'app-empty' }, [
    h('h2', null, 'No projects yet'),
    h('p', null, 'Start a blank system or open one of the samples.'),
    A.role !== 'viewer' ? h('button', { type: 'button', class: 'primary', onclick: newProjectDialog }, 'New project') : null,
  ]));
  markRendered();
}

function globalKeys(e) {
  const mod = e.metaKey || e.ctrlKey;
  const t = e.target;
  const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
  const k = (e.key || '').toLowerCase();
  if (mod && k === 'k') { e.preventDefault(); openPalette(); return; }
  if (mod && k === 'j') { e.preventDefault(); toggleAssistant(); return; }
  if (mod && k === 's') { e.preventDefault(); if (A.queue) A.queue.flush().then(function () { if (A.queue && !A.queue.pending) announce('Saved'); }); return; }
  if (e.defaultPrevented || typing || !A.store) return;
  if (mod && k === 'z' && !e.shiftKey) { e.preventDefault(); if (A.store.canUndo) A.store.undo(); return; }
  if ((mod && k === 'z' && e.shiftKey) || (e.ctrlKey && k === 'y')) { e.preventDefault(); if (A.store.canRedo) A.store.redo(); return; }
  if (e.key === 'Escape') {
    const ast = $('app-assistant');
    if (ast && ast.classList.contains('open')) { toggleAssistant(false); return; }
    if (A.sheetOpen && window.innerWidth < 1100) { closeInspector(); return; }
    if (A.store.highlighted) A.store.highlight(null);
  }
}

export function boot(root, opts) {
  opts = opts || {};
  installErrorCapture();
  A.api = opts.api || createApi({ base: appRoot() });
  // legacy /?p=<project>
  const legacy = new URLSearchParams(location.search).get('p');
  if (legacy && !location.hash) history.replaceState(null, '', location.pathname + buildHash(legacy, '', DEFAULT_VIEW));
  $('app-search').addEventListener('click', openPalette);
  $('app-assistant-btn').addEventListener('click', function () { toggleAssistant(); });
  $('app-save').addEventListener('click', function () { if (A.queue) A.queue.flush(); });
  $('app-user').addEventListener('click', userMenu);
  $('app-undo').addEventListener('click', function () { if (A.store && A.store.canUndo) A.store.undo(); });
  $('app-redo').addEventListener('click', function () { if (A.store && A.store.canRedo) A.store.redo(); });
  $('app-project').addEventListener('change', function (e) {
    const v = e.target.value;
    if (v === '__new__') { newProjectDialog(); return; }
    location.hash = buildHash(v, '', A.view || DEFAULT_VIEW);
  });
  $('app-room').addEventListener('change', function (e) {
    if (!A.store) return;
    A.store.setRoom(e.target.value);
    navigate(A.view, { room: e.target.value, keepSel: false });
  });
  document.addEventListener('keydown', globalKeys);
  window.addEventListener('hashchange', onHash);
  window.addEventListener('resize', function () {
    if (A.ctx) { A.ctx.env.narrow = window.innerWidth < 700; }
    if (window.innerWidth >= 1100 && A.store && A.store.selection) A.inspectorOpen = true;
    layoutInspector();
    if (typeof ResizeObserver === 'undefined') fitTabs();
  });
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(fitTabs).observe($('app-views'));
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitTabs);
  renderTabs();
  registerSW();
  return A.api.session().catch(function (e) {
    return { auth_enabled: false, authenticated: true, user: null, offline: true, error: errMsg(e) };
  }).then(function (s) {
    A.session = s;
    if (s.auth_enabled && !s.authenticated && !s.public_view) {
      location.href = appRoot() + 'login?next=' + encodeURIComponent(location.pathname + location.search + location.hash);
      return null;
    }
    if (s.user && s.user.role) A.role = s.user.role;
    else if (s.auth_enabled && !s.authenticated) A.role = 'viewer';
    $('app-user').title = s.user ? s.user.username + ' (' + s.user.role + ')' : 'Local mode';
    return Promise.all([
      A.api.meta().catch(function () { return null; }),
      A.api.listProjects().catch(function () { return { projects: [] }; }),
    ]);
  }).then(function (res) {
    if (!res) return null;
    A.meta = res[0];
    A.vocab = (A.meta && A.meta.vocab) || FALLBACK_VOCAB;
    disciplineVars(A.vocab);
    A.projects = (res[1] && res[1].projects) || [];
    const r = parseHash(location.hash);
    if (!r.project) {
      if (!A.projects.length) { renderPickers(); emptyState(); return null; }
      location.replace(location.pathname + location.search + buildHash(A.projects[0].name, '', DEFAULT_VIEW));
      return loadProject(A.projects[0].name, parseHash(location.hash));
    }
    return loadProject(r.project, r);
  }).catch(function (e) {
    $('app-main').innerHTML = '';
    $('app-main').appendChild(errorCard('Fathom', e));
    markRendered();
  });
}

// ------------------------------------------------------------ login page

function safeNext(n) {
  if (!n || n.charAt(0) !== '/' || n.charAt(1) === '/' || n.indexOf('\\') >= 0) return appRoot();
  return n;
}

export function bootLogin() {
  installErrorCapture();
  const api = createApi({ base: appRoot() });
  const form = $('login-form');
  const err = $('login-error');
  const next = safeNext(new URLSearchParams(location.search).get('next'));
  api.session().then(function (s) {
    if (s.auth_enabled && s.authenticated) { location.replace(next); return; }
    if (!s.auth_enabled) {
      err.textContent = '';
      form.insertBefore(h('p', { id: 'login-off', style: { color: 'var(--ok)' } }, ['Sign-in is not required on this server. ', h('a', { href: next }, 'Open Fathom')]), form.querySelector('label'));
    }
  }, function () { /* server offline: keep the form */ }).then(markRendered, markRendered);
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    err.textContent = '';
    const btn = $('login-submit');
    btn.disabled = true;
    api.login($('login-user').value.trim(), $('login-pass').value).then(function () {
      location.replace(next);
    }, function (ex) {
      btn.disabled = false;
      err.textContent = ex.status === 401 ? 'Wrong username or password.' : ex.status === 429 ? 'Too many attempts. Wait a few minutes and try again.' : errMsg(ex);
      $('login-pass').select();
    });
  });
}

// ------------------------------------------------------------ dev harness (§6.12)

const HARNESS_MODULES = { patchtable: ['./patchtable.js', 'mount'], inspector: ['./inspector.js', 'mountInspector'] };

function fakePickPort(ctx) {
  return function (opts) {
    const doc = ctx.store.doc;
    const src = (opts && opts.compatibleWith) || null;
    const sd = src ? (doc.devices || []).filter(function (d) { return d.id === src.device; })[0] : null;
    const sp = sd ? devicePorts(sd).filter(function (p) { return p.id === src.port; })[0] : null;
    for (const d of (doc.devices || [])) {
      for (const p of devicePorts(d)) {
        if (src && d.id === src.device) continue;
        const res = !src ? { level: 'ok' } : (sp && sp.dir === 'in' ? canConnect(doc, { device: d.id, port: p.id }, src, ctx.vocab) : canConnect(doc, src, { device: d.id, port: p.id }, ctx.vocab));
        if (res.level === 'ok') return Promise.resolve({ device: d.id, port: p.id });
      }
    }
    return Promise.resolve(null);
  };
}

export function bootHarness(name) {
  installErrorCapture();
  const host = document.getElementById('harness') || document.body;
  const status = document.getElementById('harness-status');
  const log = function (m) { if (status) status.textContent = String(m); };
  const params = new URLSearchParams(location.search);
  const fixtureUrl = staticBase() + 'dev/' + (params.get('fixture') || 'fixture-v2.json');
  const metaP = fetch(appRoot() + 'api/v2/meta', { headers: { Accept: 'application/json' } }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
  const docP = fetch(fixtureUrl).then(function (r) { if (!r.ok) throw new Error('fixture: HTTP ' + r.status); return r.json(); });
  return Promise.all([docP, metaP]).then(function (res) {
    const doc = res[0];
    const vocab = (res[1] && res[1].vocab) || FALLBACK_VOCAB;
    disciplineVars(vocab);
    const store = createStore({ doc: doc, vocab: vocab, readOnly: params.get('readonly') === '1', room: params.get('room') || (doc.settings && doc.settings.default_room) || '*' });
    const ctx = makeCtx(store, {
      api: null, project: (doc.meta && doc.meta.slug) || 'harness',
      toast: function (m, lv) { console.log('[toast ' + (lv || 'info') + '] ' + m); log(m); },
      confirm: function () { return Promise.resolve(true); },
      navigate: function (v, p) { log('navigate ' + v + ' ' + JSON.stringify(p || {})); },
      openInspector: function (sel) { if (sel) store.select(sel); },
      appRoot: appRoot(),
    });
    ctx.pickPort = fakePickPort(ctx);
    ctx.pickTemplate = function () { return Promise.resolve(((store.doc.templates || [])[0]) || null); };
    ctx.pickDevice = function () { return Promise.resolve(((store.doc.devices || [])[0] || {}).id || null); };
    window.__harness = { store: store, ctx: ctx };
    store.addEventListener('doc', function (e) { log((e.detail.source || '') + ': ' + (e.detail.label || '') + ' \u00b7 ' + (e.detail.ops || []).length + ' ops'); });
    const undo = document.getElementById('harness-undo');
    const redo = document.getElementById('harness-redo');
    if (undo) undo.addEventListener('click', function () { if (store.canUndo) store.undo(); });
    if (redo) redo.addEventListener('click', function () { if (store.canRedo) store.redo(); });
    document.addEventListener('keydown', function (e) {
      const k = (e.key || '').toLowerCase();
      const t = e.target;
      if (e.defaultPrevented || (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA'))) return;
      if ((e.metaKey || e.ctrlKey) && k === 'z') { e.preventDefault(); if (e.shiftKey) { if (store.canRedo) store.redo(); } else if (store.canUndo) store.undo(); }
    });
    const spec = HARNESS_MODULES[name];
    if (!spec) throw new Error('unknown harness ' + name);
    return import(spec[0]).then(function (m) {
      host.innerHTML = '';
      const handle = m[spec[1]](host, ctx);
      window.__harness.handle = handle;
      const side = document.getElementById('harness-inspector');
      if (side && name !== 'inspector') return import('./inspector.js').then(function (mi) { mi.mountInspector(side, ctx); });
      return null;
    });
  }).then(function () { markRendered(); }, function (e) {
    host.innerHTML = '';
    host.appendChild(errorCard('Harness ' + name, e));
    console.error(e);
    markRendered();
  });
}

// ------------------------------------------------------------ autoboot

if (typeof document !== 'undefined') {
  if (document.getElementById('login-form')) bootLogin();
  else if (document.body && document.body.getAttribute('data-fathom-harness')) bootHarness(document.body.getAttribute('data-fathom-harness'));
  else if (document.body && document.body.hasAttribute('data-fathom-app') && document.getElementById('app')) boot(document.getElementById('app'));
}
