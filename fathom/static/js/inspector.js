// Entity inspector / editor (§6.8): device, port, cable, rack, floor plan,
// marker, bundle, room. Field changes become ops through ctx.commit; text
// edits debounce 400 ms into one op per field burst.
//
// It is the content of the drawer host #app-inspector (docs/ui-audit.md D4,
// B.3 INS): drawer.js owns modes, focus and Esc; this module renders the
// header (.ins-head), the sticky section index (nav.ins-index) and the
// details[data-section] sections. The handle's focusSection(key) opens and
// scrolls to a section and writes `sec` to the URL; collapse state persists
// per entity kind in localStorage `fathom.ui.inspector`.

import { h } from './dom.js';
import { selToString } from './router-core.js';
import {
  devicePorts, portLabel, deviceTitle, disciplineOf, mediumInfo, setPortsOps, deleteDeviceOps, duplicateDeviceOps,
  connectOps, disconnectOps, repatchOps, expandPortGroups, newId, slug, formatLength, parseLength, deepClone,
  normalizeMac, conditionsOf, containerDevices, containerContents, deepEqual,
} from './model-core.js';
import { formatShortCode } from './search-core.js';
import { duplicateHints, fetchDuplicates, openMergeDialog } from './merge-ui.js';
import { inlineError, reviewBadge } from './feedback.js';
import {
  GROUPS, BUS_KINDS, effectiveChannels, groupChannels, channelMap, channelIndex, channelLabel, channelTitle, channelSummary, filterChannels,
  endpointText as linkEndpointText, routePeer, channelRef, setInputPatch, toggleSend, toggleMembership, addOutput, removeLink, updateChannel, nextChannel,
} from './console-core.js';
import { openTraceDrawer } from './trace-ui.js';

const DEBOUNCE = 400;
const CHANNEL_COLORS = ['Off', 'Blue', 'Orange', 'Yellow', 'Purple', 'Cyan', 'Magenta', 'Red', 'Green', 'Pink', 'White'];
const STATE_KEY = 'fathom.ui.inspector';
const GLYPH = { device: '\u25EB', port: '\u25CB', cable: '\u223F', rack: '\u2261', floorplan: '\u25A6', marker: '\u25A6', bundle: '\u223F', room: '\u25A3', channel: '\u25CF' };
const KIND_NAME = { device: 'Device', port: 'Port', cable: 'Cable', rack: 'Rack', floorplan: 'Floor plan', marker: 'Marker', bundle: 'Bundle', room: 'Room', channel: 'Channel' };
// Index chip labels; other sections use their title without the count.
const SHORT = {
  identity: 'Identity', map: 'Map', ports: 'Ports', console: 'Channels', rack: 'Rack', inventory: 'Inventory', net: 'Network', dmx: 'DMX',
  files: 'Files', procedures: 'Procedures', problems: 'Problems', qr: 'QR', notes: 'Notes', dups: 'Duplicates', merged: 'Merges',
  endpoints: 'Endpoints', cables: 'Connected', input: 'Input', fedby: 'Fed by', sends: 'Sends', groups: 'Groups', members: 'Members', outputs: 'Outputs',
};
const DEFAULT_OPEN = { identity: true, ports: true, endpoints: true, fields: true, console: true };
const INDEX_MIN = 3;
const SEC_RE = /^[A-Za-z0-9_-]+$/;
let uid = 0;

function localStore() {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null;
  } catch (e) {
    return null;
  }
}

// {"v": 1, "open": {"<kind>": {"<section>": bool}}}; only sections the user toggled are stored.
function readState(storage) {
  const empty = { v: 1, open: {} };
  try {
    const raw = storage ? storage.getItem(STATE_KEY) : null;
    const o = raw ? JSON.parse(raw) : null;
    if (!o || typeof o !== 'object' || !o.open || typeof o.open !== 'object' || Array.isArray(o.open)) return empty;
    const out = { v: 1, open: {} };
    Object.keys(o.open).forEach(function (kind) {
      const m = o.open[kind];
      if (!m || typeof m !== 'object') return;
      out.open[kind] = {};
      Object.keys(m).forEach(function (k) { if (typeof m[k] === 'boolean') out.open[kind][k] = m[k]; });
    });
    return out;
  } catch (e) {
    return empty;
  }
}

function prefersReducedMotion() {
  try {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  } catch (e) {
    return false;
  }
}

function plainClick(e) {
  return !(e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || (e.button && e.button !== 0));
}

function find(list, id) {
  for (const e of (list || [])) if (e && e.id === id) return e;
  return null;
}

function getPath(obj, path) {
  let v = obj;
  for (const k of path) { if (v == null) return undefined; v = v[k]; }
  return v;
}

function nest(path, value) {
  const out = {};
  let cur = out;
  path.forEach(function (k, i) {
    if (i === path.length - 1) cur[k] = value;
    else { cur[k] = {}; cur = cur[k]; }
  });
  return out;
}

export function mountInspector(el, ctx) {
  const store = ctx.store;
  const vocab = ctx.vocab || {};
  let selfCommit = 0;
  const pendingTimers = {};
  const root = h('div', { class: 'ins' });
  el.appendChild(root);
  const storage = localStore();
  const saved = readState(storage);
  // Session open state per kind, seeded from the user's saved choices.
  const openByKind = {};
  Object.keys(saved.open).forEach(function (k) { openByKind[k] = Object.assign({}, saved.open[k]); });
  let kind = '';
  let resetScroll = false;
  let echo = null;
  let consoleTab = 'inputs';
  let consoleQuery = '';
  let traceDrawer = null;

  function ro() { return store.readOnly; }
  function commit(ops, label) {
    if (!ops || !ops.length) return;
    selfCommit++;
    try { ctx.commit(ops, label); } finally { selfCommit--; }
  }
  function flushTimers() {
    Object.keys(pendingTimers).forEach(function (k) { const t = pendingTimers[k]; clearTimeout(t.id); delete pendingTimers[k]; t.fn(); });
  }
  function debounced(key, fn) {
    if (pendingTimers[key]) clearTimeout(pendingTimers[key].id);
    pendingTimers[key] = { fn: fn, id: setTimeout(function () { delete pendingTimers[key]; fn(); }, DEBOUNCE) };
  }

  // -------------------------------------------------- generic fields

  function fieldRow(label, input, extra) {
    if (!input.id) input.id = 'ins-f' + (++uid);
    const row = h('div', { class: 'field' + (input.type === 'checkbox' ? ' check' : '') }, [h('label', { for: input.id }, label), input]);
    if (extra) row.appendChild(extra);
    if (ro()) input.disabled = true;
    return row;
  }

  // text/number field bound to an entity path; empty clears (null)
  function bound(coll, id, path, opts) {
    opts = opts || {};
    const ent = find(store.doc[coll], id);
    const cur = ent ? getPath(ent, path) : undefined;
    let input;
    if (opts.multiline) input = h('textarea', { rows: 3 });
    else input = h('input', { type: opts.type || 'text', inputmode: opts.inputmode, list: opts.list, placeholder: opts.placeholder, autocomplete: 'off' });
    input.value = cur === undefined || cur === null ? '' : (opts.format ? opts.format(cur) : String(cur));
    if (ro()) input.disabled = true;
    const key = coll + '/' + id + '/' + path.join('.');
    function send() {
      const raw = input.value;
      let v = raw.trim() === '' ? null : (opts.parse ? opts.parse(raw) : (opts.number ? Number(raw) : raw));
      if (opts.number && v !== null && isNaN(v)) return;
      const e = find(store.doc[coll], id);
      if (!e) return;
      const before = getPath(e, path);
      if ((before === undefined || before === null ? null : before) === v) return;
      commit([{ op: 'merge', coll: coll, id: id, value: nest(path, v) }], (opts.label || ('Edit ' + path[path.length - 1])) + ' \u00b7 ' + (e.name || e.tag || id));
    }
    input.addEventListener('input', function () { debounced(key, send); });
    input.addEventListener('change', function () { if (pendingTimers[key]) { clearTimeout(pendingTimers[key].id); delete pendingTimers[key]; } send(); });
    return input;
  }

  function boundSelect(coll, id, path, options, opts) {
    opts = opts || {};
    const ent = find(store.doc[coll], id);
    const cur = ent ? getPath(ent, path) : undefined;
    const sel = h('select');
    const vals = options.map(function (o) { return Array.isArray(o) ? o : [o, o]; });
    const curStr = cur === undefined || cur === null ? (opts.empty !== undefined ? '' : '') : String(cur);
    if (opts.empty !== undefined) sel.appendChild(h('option', { value: '' }, opts.empty));
    if (curStr && !vals.some(function (v) { return String(v[0]) === curStr; })) sel.appendChild(h('option', { value: curStr }, curStr + ' (unknown)'));
    vals.forEach(function (v) { sel.appendChild(h('option', { value: String(v[0]) }, v[1])); });
    sel.value = curStr || (opts.empty !== undefined ? '' : (opts.default || (vals[0] ? String(vals[0][0]) : '')));
    sel.addEventListener('change', function () {
      const e = find(store.doc[coll], id);
      if (!e) return;
      let v = sel.value === '' ? null : sel.value;
      if (opts.defaultValue !== undefined && v === opts.defaultValue) v = null;
      if (opts.number && v !== null) v = Number(v);
      commit([{ op: 'merge', coll: coll, id: id, value: nest(path, v) }], (opts.label || 'Set ' + path[path.length - 1]) + ' \u00b7 ' + (e.name || e.tag || id));
    });
    return sel;
  }

  function boundCheck(coll, id, path, opts) {
    opts = opts || {};
    const ent = find(store.doc[coll], id);
    const cur = ent ? getPath(ent, path) : undefined;
    const box = h('input', { type: 'checkbox' });
    box.checked = opts.invertDefault ? cur !== false : !!cur;
    box.addEventListener('change', function () {
      let v;
      if (opts.invertDefault) v = box.checked ? null : false;
      else v = box.checked ? true : null;
      commit([{ op: 'merge', coll: coll, id: id, value: nest(path, v) }], (opts.label || 'Toggle ' + path[path.length - 1]));
    });
    return box;
  }

  function openState() {
    if (!openByKind[kind]) openByKind[kind] = {};
    return openByKind[kind];
  }
  function persistOpen(k, key, value) {
    if (!saved.open[k]) saved.open[k] = {};
    if (saved.open[k][key] === value) return;
    saved.open[k][key] = value;
    try {
      if (storage) storage.setItem(STATE_KEY, JSON.stringify(saved));
    } catch (e) { /* storage full or disabled */ }
  }

  function section(key, title, children, open) {
    const st = openState();
    const k = kind;
    const isOpen = st[key] !== undefined ? st[key] : (DEFAULT_OPEN[key] !== undefined ? DEFAULT_OPEN[key] : !!open);
    const summary = h('summary', null, title);
    const d = h('details', {
      class: 'ins-section', open: isOpen ? true : null, 'data-section': key,
      'data-label': SHORT[key] || String(title).replace(/\s*\(.*$/, ''),
    }, [summary, h('div', { class: 'inner' }, children)]);
    let byUser = false;
    summary.addEventListener('click', function () { byUser = true; });
    d.addEventListener('toggle', function () {
      st[key] = d.open;
      if (!byUser) return;
      byUser = false;
      persistOpen(k, key, d.open);
      if (d.open) { markIndex(key); writeSec(key); } else if (routeQuery().sec === key) { markIndex(''); writeSec(null); }
    });
    return d;
  }

  // -------------------------------------------------- drawer, URL and navigation (D1, D4)

  function routeQuery() {
    const r = ctx.route;
    return (r && r.query) || {};
  }
  function routed() {
    const r = ctx.route;
    return !!(r && r.project);
  }
  // `sec` is only written while the URL's `sel` is the entity shown here.
  function writeSec(key) {
    const q = routeQuery();
    if (typeof ctx.setParams !== 'function' || !q.sel || q.sel !== selToString(store.selection)) return;
    if ((q.sec || '') === (key || '')) return;
    echo = { key: key || '', t: Date.now() };
    ctx.setParams({ sec: key || null });
  }
  function closeDetails() {
    if (typeof ctx.closeDrawer === 'function') ctx.closeDrawer();
    else { if (ctx.closeInspector) ctx.closeInspector(); store.select(null); }
  }
  function inspect(sel) {
    if (typeof ctx.openDrawer === 'function') ctx.openDrawer(sel);
    else store.select(sel);
  }
  // In-app page link (device, rack, room), or null without a router or when already there.
  function pageHref(p) {
    if (typeof ctx.routeHref !== 'function' || !routed()) return null;
    const r = ctx.route;
    if (r.view === p.view && r.id === p.id) return null;
    const partial = { view: p.view, id: p.id };
    if (p.room) partial.room = p.room;
    const href = ctx.routeHref(partial);
    return href && href !== '#' ? href : null;
  }
  function selHref(sel, sec) {
    if (typeof ctx.routeHref !== 'function' || !routed()) return '#';
    const q = Object.assign({}, routeQuery(), { sel: selToString(sel), sec: sec || null, drawer: null });
    return ctx.routeHref({ query: q }) || '#';
  }
  // A link that inspects `sel` in this drawer; modified clicks follow the href (a deep link).
  function selLink(sel, text, cls, attrs) {
    return h('a', Object.assign({ class: cls, href: selHref(sel), onclick: function (e) {
      if (!plainClick(e)) return;
      e.preventDefault();
      inspect(sel);
    } }, attrs || {}), text);
  }
  // Leaves the drawer for another view showing `sel`; canvas views keep the sheet closed below lg (D4).
  function goTo(view, sel, opts) {
    const o = opts || {};
    if (typeof ctx.navigateRoute === 'function' && routed()) {
      const lg = typeof ctx.layout !== 'function' || ctx.layout() === 'lg';
      const partial = { view: view, query: { sel: sel, drawer: o.canvas && !lg ? '0' : null } };
      if (o.tab) partial.tab = o.tab;
      ctx.navigateRoute(partial);
    } else {
      ctx.navigate(view, { sel: sel });
    }
  }

  // -------------------------------------------------- section index and focusSection

  function topSections() {
    return Array.prototype.filter.call(root.children, function (c) { return c.tagName === 'DETAILS' && c.hasAttribute('data-section'); });
  }
  function sectionEl(key) {
    const all = topSections();
    for (let i = 0; i < all.length; i++) if (all[i].getAttribute('data-section') === key) return all[i];
    return null;
  }
  function buildIndex() {
    const secs = topSections();
    if (secs.length < INDEX_MIN) return;
    const cur = routeQuery().sec || '';
    const nav = h('nav', { class: 'ins-index', 'aria-label': 'Sections' }, secs.map(function (d) {
      const key = d.getAttribute('data-section');
      return h('a', { class: 'ins-index-chip', href: selHref(store.selection, key), 'data-sec': key, 'aria-current': key === cur ? 'true' : null, onclick: function (e) {
        if (!plainClick(e)) return;
        e.preventDefault();
        focusSection(key, { user: true });
      } }, d.getAttribute('data-label') || key);
    }));
    root.insertBefore(nav, secs[0]);
  }
  function markIndex(key) {
    const nav = root.querySelector('.ins-index');
    if (!nav) return;
    Array.prototype.forEach.call(nav.querySelectorAll('.ins-index-chip'), function (a) {
      const on = !!key && a.getAttribute('data-sec') === key;
      if (on) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
      if (on && (a.offsetLeft < nav.scrollLeft || a.offsetLeft + a.offsetWidth > nav.scrollLeft + nav.clientWidth)) {
        nav.scrollLeft = Math.max(0, a.offsetLeft - 12);
      }
    });
  }
  function refreshIndex() {
    const nav = root.querySelector('.ins-index');
    if (!nav) return;
    Array.prototype.forEach.call(nav.querySelectorAll('.ins-index-chip'), function (a) { a.setAttribute('href', selHref(store.selection, a.getAttribute('data-sec'))); });
  }
  function scrollToSection(d, smooth) {
    const nav = root.querySelector('.ins-index');
    const hostBox = el.getBoundingClientRect();
    const pad = parseFloat(getComputedStyle(el).paddingTop) || 0;
    const off = (nav ? nav.getBoundingClientRect().height : 0) + pad;
    const top = Math.max(0, el.scrollTop + d.getBoundingClientRect().top - hostBox.top - el.clientTop - off);
    if (el.scrollHeight <= el.clientHeight + 1) { d.scrollIntoView({ block: 'nearest' }); return; }
    if (smooth && !prefersReducedMotion() && typeof el.scrollTo === 'function') el.scrollTo({ top: top, behavior: 'smooth' });
    else el.scrollTop = top;
  }
  // Opens details[data-section=key], scrolls it below the index and writes `sec`. The shell calls this
  // with the URL's `sec`; the echo of our own write is not scrolled again.
  function focusSection(key, opts) {
    const o = opts || {};
    if (!key || typeof key !== 'string' || !SEC_RE.test(key)) return false;
    const d = sectionEl(key);
    if (!d) return false;
    const isEcho = !o.user && !!echo && echo.key === key && Date.now() - echo.t < 1500;
    echo = null;
    if (!d.open) d.open = true;
    openState()[key] = true;
    markIndex(key);
    if (!isEcho) scrollToSection(d, !!o.user);
    if (o.user) {
      const s = d.querySelector('summary');
      if (s) { try { s.focus({ preventScroll: true }); } catch (e) { s.focus(); } }
    }
    writeSec(key);
    return true;
  }

  function closeButton() {
    return h('button', { type: 'button', class: 'icon ghost ins-close', 'aria-label': 'Close details', title: 'Close details', onclick: closeDetails }, '\u00d7');
  }
  function statusPill(s) {
    return h('span', { class: 'ins-status', 'data-status': s }, s);
  }

  function mediaOptions() {
    const m = vocab.media || {};
    return Object.keys(m).map(function (k) { return [k, m[k].label || k]; });
  }
  function connectorList() {
    let dl = document.getElementById('ins-connectors');
    if (!dl) {
      dl = h('datalist', { id: 'ins-connectors' }, (vocab.connectors || []).map(function (c) { return h('option', { value: c }); }));
      document.body.appendChild(dl);
    }
    return 'ins-connectors';
  }
  function roomOptions(withShared) {
    const out = (store.doc.rooms || []).map(function (r) { return [r.id, r.name || r.id]; });
    if (withShared) out.unshift(['', 'Shared inventory']);
    return out;
  }

  // .ins-head: kind glyph and label, `extra`, "Open page", close; title; status pill and subtitle;
  // then `badges` (div.ins-badges, review badges on their own wrapping row).
  function head(kindLabel, color, title, sub, opts) {
    const o = opts || {};
    const c = color || 'var(--muted)';
    const page = o.page ? pageHref(o.page) : null;
    return h('div', { class: 'ins-head ins-title', 'data-kind': kind }, [
      h('div', { class: 'ins-head-row' }, [
        h('span', { class: 'ins-glyph', 'aria-hidden': 'true', style: { color: c } }, GLYPH[kind] || '\u25CF'),
        h('span', { class: 'kind', style: { color: c } }, kindLabel),
        h('span', { class: 'grow' }),
        o.extra || null,
        page ? h('a', { class: 'chip ins-open-page', href: page, title: 'Open the ' + (KIND_NAME[kind] || 'entity').toLowerCase() + ' page' }, 'Open page') : null,
        closeButton(),
      ]),
      h('h3', null, title),
      o.status || sub ? h('div', { class: 'ins-head-meta' }, [o.status ? statusPill(o.status) : null, sub ? h('span', { class: 'sub' }, sub) : null]) : null,
      o.badges || null,
    ]);
  }

  // Review badge (B.5 checklist 6) that jumps to its section; `data-badge` names the section.
  function sectionBadge(key, count, label, title) {
    const b = reviewBadge({ count: count, label: label, title: title, onClick: function () { focusSection(key, { user: true }); } });
    if (b) b.setAttribute('data-badge', key);
    return b;
  }
  function addDupBadge(box, n) {
    if (!box.isConnected || box.querySelector('[data-badge=dups]')) return;
    const b = sectionBadge('dups', n, n === 1 ? 'possible duplicate' : 'possible duplicates', 'Review likely duplicates of this device');
    if (b) box.appendChild(b);
  }

  // -------------------------------------------------- device

  function renderDevice(d) {
    kind = 'device';
    const disc = disciplineOf(d, vocab);
    const dcol = vocab.disciplines && vocab.disciplines[disc] ? vocab.disciplines[disc].color : '#9aa3b5';
    const kinds = vocab.kinds || {};
    const proj = encodeURIComponent(ctx.project || '');
    const devUrl = (ctx.appRoot || '') + 'p/' + proj + '/d/' + encodeURIComponent(d.id);
    const problems = problemsFor(d);
    const nOpen = problems.filter(function (r) { return (r.status || 'open') === 'open'; }).length;
    const badges = h('div', { class: 'ins-badges' }, [
      sectionBadge('problems', nOpen, nOpen === 1 ? 'open problem' : 'open problems', 'Show the open problem reports'),
    ]);
    root.appendChild(head(((vocab.disciplines && vocab.disciplines[disc] && vocab.disciplines[disc].label) || disc) + ' \u00b7 ' + ((kinds[d.kind] && kinds[d.kind].label) || d.kind || 'device'), dcol, deviceTitle(d),
      ((d.manufacturer || '') + ' ' + (d.model || '')).trim() || d.sub || '', {
        status: d.status || 'installed',
        page: { view: 'devices', id: d.id },
        badges: badges,
      }));
    // Duplicates are advisory: a failed check shows in the section (with Retry), not in the header.
    if (ctx.api) fetchDuplicates(ctx, { device: d.id }).then(function (list) { addDupBadge(badges, (list || []).length); }, function () { /* see the section */ });
    const actions = h('div', { class: 'ins-actions' }, [
      h('button', { type: 'button', class: 'small', onclick: function () { goTo('patch', 'device:' + d.id, { canvas: true }); } }, 'Show in patch view'),
      ctx.api ? h('button', { type: 'button', class: 'small', 'data-action': 'trace', onclick: function () { openTrace(d.id, deviceTitle(d), 'all ports', d); } }, 'Trace path') : null,
      h('a', { class: 'chip', href: devUrl, target: '_blank', rel: 'noopener' }, 'Device page'),
      ro() ? null : h('button', { type: 'button', class: 'small', onclick: function () {
        const r = duplicateDeviceOps(store.doc, d.id);
        commit(r.ops, 'Duplicate ' + d.name);
        if (r.id) store.select({ type: 'device', id: r.id, device: r.id });
      } }, 'Duplicate'),
      ro() || !ctx.api ? null : h('button', { type: 'button', class: 'small', onclick: function () {
        ctx.pickDevice({ title: 'Merge ' + d.name + ' with which device?' }).then(function (other) {
          if (!other || other === d.id) return;
          openMergeDialog(ctx, [d.id, other], { survivor: d.id });
        });
      } }, 'Merge\u2026'),
      ro() ? null : h('button', { type: 'button', class: 'small danger', onclick: function () {
        const n = ((store.index.cablesByDevice[d.id]) || []).length;
        ctx.confirm('Delete ' + d.name + (n ? ' and its ' + n + ' cable' + (n > 1 ? 's' : '') : '') + '?', { danger: true }).then(function (yes) {
          if (!yes) return;
          commit(deleteDeviceOps(store.doc, d.id), 'Delete ' + d.name);
          store.select(null);
        });
      } }, 'Delete'),
    ]);
    root.appendChild(actions);

    const id = d.id;
    // identity
    root.appendChild(section('identity', 'Identity', [
      fieldRow('Name', bound('devices', id, ['name'], { label: 'Rename' })),
      fieldRow('Kind', boundSelect('devices', id, ['kind'], Object.keys(kinds).map(function (k) { return [k, kinds[k].label]; }), { label: 'Set kind' })),
      fieldRow('Discipline', boundSelect('devices', id, ['discipline'], Object.keys(vocab.disciplines || {}).map(function (k) { return [k, vocab.disciplines[k].label]; }), { empty: 'From kind', label: 'Set discipline' })),
      fieldRow('Manufacturer', bound('devices', id, ['manufacturer'])),
      fieldRow('Model', bound('devices', id, ['model'])),
      fieldRow('Code', bound('devices', id, ['code'], { placeholder: 'label code, e.g. FOH' })),
      fieldRow('Room', boundSelect('devices', id, ['room'], roomOptions(false), { empty: 'Shared inventory', label: 'Move room' })),
      fieldRow('System', boundSelect('devices', id, ['system'], (store.doc.systems || []).map(function (s) { return [s.id, s.name || s.id]; }), { empty: '\u2014' })),
      fieldRow('Location', boundSelect('devices', id, ['location'], (store.doc.locations || []).map(function (s) { return [s.id, s.name || s.id]; }), { empty: '\u2014' })),
      fieldRow('Status', boundSelect('devices', id, ['status'], (vocab.statuses || ['installed', 'planned', 'spare', 'retired']), { defaultValue: 'installed', default: 'installed', label: 'Set status' })),
      fieldRow('Subtitle', bound('devices', id, ['sub'])),
      fieldRow('Brand badge', boundSelect('devices', id, ['brand'], Object.keys(vocab.brands || {}).map(function (k) { return [k, (vocab.brands[k].text || k)]; }), { empty: 'None' })),
      fieldRow('Count', bound('devices', id, ['count'], { type: 'number', inputmode: 'numeric', number: true })),
      fieldRow('Tags', tagsInput(d)),
    ], true));

    // map placement
    const room = find(store.doc.rooms, d.room);
    const flow = (room && room.flow) || {};
    root.appendChild(section('map', 'Signal-flow map', [
      fieldRow('Group', boundSelect('devices', id, ['flow', 'group'], (flow.groups || []).map(function (g) { return [g.id, g.id + ' \u00b7 ' + (g.label || '')]; }), { empty: 'Unplaced', label: 'Map group' })),
      fieldRow('Column', boundSelect('devices', id, ['flow', 'column'], (flow.columns || []).filter(function (c) { return c.side !== 'spine'; }).map(function (c) { return [c.id, c.label || c.id]; }), { empty: 'Automatic', label: 'Map column' })),
      fieldRow('Order', bound('devices', id, ['flow', 'order'], { type: 'number', inputmode: 'numeric', number: true })),
      fieldRow('Show on map', boundCheck('devices', id, ['flow', 'show'], { invertDefault: true, label: 'Show on map' })),
      fieldRow('Dante device', boundCheck('devices', id, ['dante'], { label: 'Dante' })),
      fieldRow('Dante name', bound('devices', id, ['dante_name'])),
    ]));

    root.appendChild(section('ports', 'Ports (' + devicePorts(d).length + ')', portsEditor(d), true));
    const eff = effectiveChannels(d, store.overlay);
    if (eff.source !== 'none') {
      root.appendChild(section('console', 'Console channels (' + eff.channels.length + ')' + (eff.source === 'overlay' ? ' \u00b7 imported' : ''), consoleSection(d, eff), true));
    }
    root.appendChild(section('rack', 'Rack', rackFields(d)));
    const isBox = d.kind === 'container';
    const boxes = containerDevices(store.doc).filter(function (c) { return c.id !== id; });
    root.appendChild(section('inventory', 'Inventory', [
      fieldRow('Condition', boundSelect('devices', id, ['inventory', 'condition'], conditionsOf(vocab, ctx.meta), { empty: '\u2014', label: 'Set condition' })),
      isBox ? null : fieldRow('Stored in', boundSelect('devices', id, ['container'], boxes.map(function (c) { return [c.id, c.name || c.id]; }), { empty: '\u2014', label: 'Set container' })),
      isBox ? holdsBlock(d) : null,
      codeRow(d),
      fieldRow('Serial', bound('devices', id, ['inventory', 'serial'])),
      fieldRow('Asset tag', bound('devices', id, ['inventory', 'asset_tag'])),
      fieldRow('Firmware', bound('devices', id, ['inventory', 'firmware'])),
      fieldRow('Purchased', bound('devices', id, ['inventory', 'purchase_date'], { type: 'date' })),
      fieldRow('Warranty until', bound('devices', id, ['inventory', 'warranty_until'], { type: 'date' })),
      fieldRow('Vendor', bound('devices', id, ['inventory', 'vendor'])),
      fieldRow('Cost', bound('devices', id, ['inventory', 'cost'], { type: 'text', inputmode: 'decimal', number: true })),
      fieldRow('Currency', bound('devices', id, ['inventory', 'currency'], { placeholder: (store.doc.settings && store.doc.settings.currency) || 'USD' })),
      fieldRow('PO', bound('devices', id, ['inventory', 'po'])),
      fieldRow('Notes', bound('devices', id, ['inventory', 'notes'], { multiline: true })),
      customFieldsBlock(d),
    ]));
    root.appendChild(section('net', 'Network interfaces (' + (d.interfaces || []).length + ')', interfacesEditor(d)));
    root.appendChild(section('dmx', 'DMX', [
      fieldRow('Universe', bound('devices', id, ['dmx', 'universe'], { inputmode: 'numeric', number: true })),
      fieldRow('Address', bound('devices', id, ['dmx', 'address'], { inputmode: 'numeric', number: true })),
      fieldRow('Footprint', bound('devices', id, ['dmx', 'footprint'], { inputmode: 'numeric', number: true })),
      fieldRow('Mode', bound('devices', id, ['dmx', 'mode'])),
      fieldRow('Console channel', bound('devices', id, ['dmx', 'channel'])),
      fieldRow('Protocol', boundSelect('devices', id, ['dmx', 'protocol'], ['dmx', 'sacn', 'artnet'], { empty: '\u2014' })),
    ]));
    root.appendChild(section('files', 'Photos & documents', attachmentsBlock(d)));
    const procs = proceduresFor(d);
    root.appendChild(section('procedures', 'Procedures' + (procs.length ? ' (' + procs.length + ')' : ''), proceduresBlock(d, procs), procs.length > 0));
    root.appendChild(section('problems', 'Problems' + (nOpen ? ' (' + nOpen + ' open)' : problems.length ? ' (' + problems.length + ')' : ''), problemsBlock(d, problems), nOpen > 0));
    root.appendChild(section('qr', 'QR label', qrBlock(d, devUrl)));
    root.appendChild(section('notes', 'Notes', [bound('devices', id, ['note'], { multiline: true, label: 'Edit note' })], !!d.note));
    if (ctx.api) {
      const host = h('div', { class: 'ins-dups' });
      const dups = section('dups', 'Possible duplicates', [host], true);
      let filled = false;
      const load = function () {
        host.textContent = '';
        host.appendChild(h('div', { class: 'muted' }, 'Looking for duplicates\u2026'));
        return fetchDuplicates(ctx, { device: id }).then(function (list) {
          if (!host.isConnected) return;
          host.textContent = '';
          host.appendChild(duplicateHints(ctx, id, function (res) {
            if (res && res.survivor) store.select({ type: 'device', id: res.survivor, device: res.survivor });
          }));
          addDupBadge(badges, (list || []).length);
        }, function (e) {
          if (!host.isConnected) return;
          host.textContent = '';
          const msg = (e && e.message) || '';
          const err = inlineError({ name: e && e.name, status: e && e.status, code: e && e.code,
            message: 'Could not check for duplicates' + (msg ? ': ' + msg : '.') }, load, { compact: true });
          err.classList.add('ins-dups-error');
          host.appendChild(err);
        });
      };
      function fill() {
        if (filled) return;
        filled = true;
        load();
      }
      if (dups.open) fill();
      dups.addEventListener('toggle', function () { if (dups.open) fill(); });
      root.appendChild(dups);
    }
    if (d.merged_from && d.merged_from.length) {
      root.appendChild(section('merged', 'Merge history (' + d.merged_from.length + ')', [h('ul', { class: 'ins-merged' }, d.merged_from.map(function (m) {
        return h('li', null, [h('b', null, m.name || m.id), ' (' + (m.source || 'project') + ')', m.at ? ' \u00b7 ' + String(m.at).slice(0, 10) : '', m.by ? ' by ' + m.by : '',
          m.fields && m.fields.length ? h('div', { class: 'muted' }, 'took: ' + m.fields.join(', ')) : null]);
      }))]));
    }
  }

  // Problem reports filed against this device (from SOP pages, QR labels and share links), open first.
  function problemsFor(d) {
    return (store.doc.problems || []).filter(function (r) { return r.device === d.id; }).sort(function (a, b) {
      const oa = (a.status || 'open') === 'open' ? 0 : 1, ob = (b.status || 'open') === 'open' ? 0 : 1;
      if (oa !== ob) return oa - ob;
      return String(b.created || '').localeCompare(String(a.created || ''));
    });
  }

  function problemsBlock(d, problems) {
    const who = (ctx.session && ctx.session.user && ctx.session.user.username) || 'local';
    const out = [];
    if (!problems.length) out.push(h('div', { class: 'muted', style: { fontSize: '12px' } }, 'No problems reported for this device.'));
    else {
      out.push(h('ul', { class: 'ins-problems' }, problems.map(function (r) {
        const open = (r.status || 'open') === 'open';
        const att = r.attachment ? (store.doc.attachments || []).filter(function (a) { return a.id === r.attachment; })[0] : null;
        const when = r.created ? new Date(r.created).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '';
        return h('li', { class: open ? 'open' : 'resolved', 'data-problem': r.id }, [
          h('div', { class: 'ins-problem-text' }, r.text),
          h('div', { class: 'ins-problem-sub' }, [
            h('span', { class: 'ins-problem-state' }, open ? 'Open' : 'Resolved'),
            ' \u00b7 ' + when + (r.by ? ' \u00b7 ' + r.by : '') + (r.via && r.via !== 'app' ? ' \u00b7 via ' + (r.via === 'share' ? 'share link' : 'public page') : ''),
          ]),
          att ? h('a', { href: ctx.api.fileUrl(ctx.project, att), target: '_blank', rel: 'noopener' }, h('img', { class: 'ins-problem-photo', src: ctx.api.fileUrl(ctx.project, att), alt: 'Photo' })) : null,
          ro() ? null : h('button', { type: 'button', class: 'small', 'data-action': open ? 'resolve' : 'reopen', onclick: function () {
            const now = new Date().toISOString();
            commit([{ op: 'merge', coll: 'problems', id: r.id, value: open ? { status: 'resolved', resolved: now, resolved_by: who } : { status: 'open', resolved: null, resolved_by: null } }], (open ? 'Resolve' : 'Reopen') + ' problem');
          } }, open ? 'Resolve' : 'Reopen'),
        ]);
      })));
    }
    const sopHash = '#/' + encodeURIComponent(ctx.project) + '/' + encodeURIComponent(store.room || '*').replace(/%2A/g, '*') + '/sop?problems=1';
    out.push(h('div', { class: 'row', style: { marginTop: '6px' } }, h('a', { class: 'chip', href: sopHash }, 'All problems')));
    return out;
  }

  // SOP pages that apply to this device: listed in page.devices or linked as [[device:id]] in the body.
  // Archived pages are hidden from viewers; drafts too.
  function proceduresFor(d) {
    const re = /\[\[device:([^\]|]+)(?:\|[^\]]*)?\]\]/g;
    return (store.doc.pages || []).filter(function (p) {
      if (ro() && (p.status || 'published') !== 'published') return false;
      if ((p.devices || []).indexOf(d.id) >= 0) return true;
      let m;
      re.lastIndex = 0;
      while ((m = re.exec(p.body || ''))) if (m[1].trim() === d.id) return true;
      return false;
    }).sort(function (a, b) { return String(a.title || '').localeCompare(String(b.title || '')); });
  }

  function proceduresBlock(d, procs) {
    const KIND = { sop: 'SOP', troubleshooting: 'Troubleshooting', checklist: 'Checklist', reference: 'Reference' };
    const sopHash = function (params) {
      const q = Object.keys(params).map(function (k) { return k + '=' + encodeURIComponent(params[k]); }).join('&');
      return '#/' + encodeURIComponent(ctx.project) + '/' + encodeURIComponent(store.room || '*').replace(/%2A/g, '*') + '/sop' + (q ? '?' + q : '');
    };
    const out = [];
    if (!procs.length) out.push(h('div', { class: 'muted', style: { fontSize: '12px' } }, 'No procedures mention this device yet.'));
    else {
      out.push(h('ul', { class: 'ins-procs' }, procs.map(function (p) {
        return h('li', null, h('a', { href: sopHash({ page: p.slug }), 'data-page': p.slug }, [
          h('span', { class: 'ins-proc-title' }, p.title || p.slug),
          h('span', { class: 'ins-proc-sub' }, (KIND[p.kind || 'sop'] || p.kind) + ((p.status || 'published') !== 'published' ? ' \u00b7 ' + p.status : '') + (p.summary ? ' \u00b7 ' + p.summary : '')),
        ]));
      })));
    }
    if (!ro()) out.push(h('div', { class: 'row', style: { marginTop: '6px' } }, h('a', { class: 'chip', href: sopHash({ new: 1, device: d.id }) }, '+ New SOP for this device')));
    return out;
  }

  function tagsInput(d) {
    const input = h('input', { value: (d.tags || []).join(', '), placeholder: 'comma separated' });
    const key = 'tags/' + d.id;
    function send() {
      const tags = input.value.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      commit([{ op: 'merge', coll: 'devices', id: d.id, value: { tags: tags.length ? tags : null } }], 'Edit tags');
    }
    input.addEventListener('input', function () { debounced(key, send); });
    return input;
  }

  // ports editor
  function portsEditor(d) {
    const out = [];
    const cablesAt = store.index.cablesByPort;
    const list = h('ul', { class: 'ins-ports', 'aria-label': 'Ports' });
    const ports = devicePorts(d);
    function commitPorts(next, label) { commit(setPortsOps(store.doc, d.id, next), label + ' \u00b7 ' + d.name); }
    function current() { const dd = find(store.doc.devices, d.id); return dd ? deepClone(devicePorts(dd)) : []; }
    ports.forEach(function (p, i) {
      const n = (cablesAt[d.id + ':' + p.id] || []).length;
      function cell(field, input, parse) {
        const key = 'port/' + d.id + '/' + p.id + '/' + field;
        function send() {
          const next = current();
          const t = next.filter(function (x) { return x.id === p.id; })[0];
          if (!t) return;
          const v = parse ? parse(input.value) : input.value.trim();
          if (v === '' || v === null) delete t[field]; else t[field] = v;
          if (field === 'name' && !t.name) t.name = p.id;
          commitPorts(next, 'Edit port ' + (p.label || p.name));
        }
        if (input.tagName === 'SELECT') input.addEventListener('change', send);
        else { input.addEventListener('input', function () { debounced(key, send); }); input.addEventListener('change', function () { if (pendingTimers[key]) { clearTimeout(pendingTimers[key].id); delete pendingTimers[key]; send(); } }); }
        if (ro()) input.disabled = true;
        return input;
      }
      const nameI = cell('name', h('input', { value: p.name || '', placeholder: 'Name', title: 'Name', 'aria-label': 'Port name' }));
      const labelI = cell('label', h('input', { value: p.label || '', placeholder: 'Label', title: 'Label', 'aria-label': 'Port label' }));
      const dirS = cell('dir', h('select', { 'aria-label': 'Direction', title: 'Direction' }, ['in', 'out', 'io'].map(function (x) { return h('option', { value: x, selected: (p.dir || 'io') === x ? true : null }, x); })));
      const medS = h('select', { 'aria-label': 'Medium', title: 'Medium' });
      if (p.medium && !(vocab.media || {})[p.medium]) medS.appendChild(h('option', { value: p.medium }, p.medium));
      mediaOptions().forEach(function (m) { medS.appendChild(h('option', { value: m[0], selected: m[0] === p.medium ? true : null }, m[1])); });
      cell('medium', medS);
      const conI = cell('connector', h('input', { value: p.connector || '', list: connectorList(), 'aria-label': 'Connector', title: 'Connector', placeholder: 'Connector' }));
      const chI = cell('channels', h('input', { value: p.channels || '', class: 'num', inputmode: 'numeric', 'aria-label': 'Channels', title: 'Channels', placeholder: '1 ch' }), function (v) { const n = parseInt(v, 10); return n > 1 ? n : null; });
      const m = mediumInfo(p.medium, vocab);
      const up = h('button', { type: 'button', class: 'small ghost', 'aria-label': 'Move up', disabled: i === 0 || ro() ? true : null, onclick: function () { const next = current(); const t = next.splice(i, 1)[0]; next.splice(i - 1, 0, t); commitPorts(next, 'Reorder ports'); render(); } }, '\u2191');
      const del = h('button', { type: 'button', class: 'small ghost danger', 'aria-label': 'Remove port ' + portLabel(p), disabled: ro() ? true : null, onclick: function () {
        const go = function () {
          const next = current().filter(function (x) { return x.id !== p.id; });
          const ops = setPortsOps(store.doc, d.id, next);
          (cablesAt[d.id + ':' + p.id] || []).forEach(function (c) { ops.push({ op: 'del', coll: 'cables', id: c.id }); });
          commit(ops, 'Remove port ' + portLabel(p));
          render();
        };
        if (n) ctx.confirm(portLabel(p) + ' has ' + n + ' cable' + (n > 1 ? 's' : '') + '. Remove the port and its cables?', { danger: true, ok: 'Remove' }).then(function (y) { if (y) go(); });
        else go();
      } }, '\u00d7');
      list.appendChild(h('li', { class: 'ins-port', 'data-port': p.id }, [
        h('span', { class: 'dot', style: { color: m.color }, title: m.label }),
        nameI, labelI,
        h('span', { class: 'ins-port-act' }, [n ? h('span', { class: 'muted', title: n + ' cable(s)' }, '\u25CF') : null, up, del]),
        h('div', { class: 'ins-port-meta' }, [dirS, medS, conI, chI]),
      ]));
    });
    out.push(list);
    if (!ports.length) out.push(h('div', { class: 'muted' }, 'No ports yet.'));
    if (ro()) return out;
    // add one / bulk add
    const cnt = h('input', { type: 'number', inputmode: 'numeric', value: '8', min: '1', max: '512', style: { width: '64px' }, 'aria-label': 'Port count' });
    const grp = h('input', { value: 'Analog In', 'aria-label': 'Group name', style: { width: '120px' } });
    const dir = h('select', { 'aria-label': 'Direction' }, ['in', 'out', 'io'].map(function (x) { return h('option', { value: x }, x); }));
    const med = h('select', { 'aria-label': 'Medium' }, mediaOptions().map(function (mm) { return h('option', { value: mm[0], selected: mm[0] === 'analog' ? true : null }, mm[1]); }));
    grp.addEventListener('change', function () { const g = grp.value.toLowerCase(); if (/\bin(put)?s?\b/.test(g)) dir.value = 'in'; else if (/\bout(put)?s?\b/.test(g)) dir.value = 'out'; });
    out.push(h('div', { class: 'row', style: { marginTop: '8px' } }, [
      h('button', { type: 'button', class: 'small', onclick: function () {
        const n = Math.max(1, Math.min(512, parseInt(cnt.value, 10) || 1));
        const existing = current();
        const taken = {};
        existing.forEach(function (x) { taken[x.id] = true; });
        const fresh = expandPortGroups([{ group: grp.value.trim() || 'Port', dir: dir.value, medium: med.value, count: n }]).map(function (x) {
          x.origin = 'user';
          let pid = x.id;
          let k = 2;
          while (taken[pid]) pid = x.id + '-' + (k++);
          x.id = pid;
          taken[pid] = true;
          return x;
        });
        commitPorts(existing.concat(fresh), 'Add ' + n + ' \u00d7 ' + (grp.value || 'Port'));
        render();
      } }, 'Add'), cnt, h('span', null, '\u00d7'), grp, dir, med,
    ]));
    const tplRow = h('div', { class: 'row', style: { marginTop: '8px' } });
    if (d.template && ctx.api) {
      tplRow.appendChild(h('button', { type: 'button', class: 'small', onclick: function () {
        ctx.api.template(d.template, ctx.project).then(function (t) {
          const existing = current();
          const have = {};
          existing.forEach(function (x) { have[x.id] = true; });
          const add = expandPortGroups((t && t.ports) || []).filter(function (x) { return !have[x.id]; });
          if (!add.length) { ctx.toast('Ports already match the template', 'ok'); return; }
          commitPorts(existing.concat(add), 'Apply template ports');
          ctx.toast('Added ' + add.length + ' ports from ' + d.template, 'ok');
          render();
        }, function (e) { ctx.toast(e.message || String(e), 'err'); });
      } }, 'Apply template ports'));
    }
    if (ctx.api) tplRow.appendChild(h('button', { type: 'button', class: 'small', onclick: function () { saveAsTemplate(d); } }, 'Save as template'));
    out.push(tplRow);
    return out;
  }

  function templateFromDevice(d, id) {
    const groups = [];
    let cur = null;
    devicePorts(d).forEach(function (p) {
      const g = p.group || p.name;
      if (!cur || cur.group !== g || cur.dir !== p.dir || cur.medium !== p.medium) {
        cur = { group: g, dir: p.dir || 'io', medium: p.medium || 'other', _names: [] };
        if (p.connector) cur.connector = p.connector;
        if (p.channels > 1) cur.channels = p.channels;
        groups.push(cur);
      }
      const nm = p.name && p.name.indexOf(g + ' ') === 0 ? p.name.slice(g.length + 1) : (p.name === g ? '' : p.name);
      cur._names.push(nm);
    });
    const ports = groups.map(function (g) {
      const out = { group: g.group, dir: g.dir, medium: g.medium };
      if (g.connector) out.connector = g.connector;
      if (g.channels) out.channels = g.channels;
      const numeric = g._names.every(function (n, i) { return n === String(i + 1); });
      if (g._names.length === 1 && !g._names[0]) { /* single */ }
      else if (numeric) out.count = g._names.length;
      else out.names = g._names.map(function (n, i) { return n || String(i + 1); });
      return out;
    });
    const t = { id: id, manufacturer: d.manufacturer || 'Custom', model: d.model || d.name, name: d.name, kind: d.kind || 'other', ports: ports };
    if (d.brand) t.brand = d.brand;
    if (d.discipline) t.discipline = d.discipline;
    if (d.dante) t.dante = true;
    return t;
  }

  function saveAsTemplate(d) {
    const sug = slug((d.manufacturer || 'custom') + '-' + (d.model || d.name)).replace(/[^a-z0-9-]/g, '');
    ctx.prompt('Template id (lowercase, dashes)', sug, { title: 'Save as template', ok: 'Save' }).then(function (tid) {
      if (!tid) return;
      ctx.api.saveTemplate(templateFromDevice(d, tid)).then(function () { ctx.toast('Saved template ' + tid, 'ok'); }, function (e) { ctx.toast(e.message || String(e), 'err'); });
    });
  }

  function rackFields(d) {
    const rk = d.rack || {};
    const racks = store.doc.racks || [];
    const sel = h('select', { 'aria-label': 'Rack' }, [h('option', { value: '' }, 'Not racked')].concat(racks.map(function (r) { return h('option', { value: r.id, selected: rk.id === r.id ? true : null }, r.name || r.id); })));
    sel.addEventListener('change', function () {
      if (!sel.value) commit([{ op: 'merge', coll: 'devices', id: d.id, value: { rack: null } }], 'Unrack ' + d.name);
      else commit([{ op: 'merge', coll: 'devices', id: d.id, value: { rack: Object.assign({ u: 1, height: 1, face: 'front' }, rk, { id: sel.value }) } }], 'Rack ' + d.name);
      render();
    });
    const out = [fieldRow('Rack', sel)];
    if (rk.id) {
      out.push(fieldRow('U (lowest)', bound('devices', d.id, ['rack', 'u'], { inputmode: 'numeric', number: true })));
      out.push(fieldRow('Height (RU)', bound('devices', d.id, ['rack', 'height'], { inputmode: 'numeric', number: true })));
      out.push(fieldRow('Face', boundSelect('devices', d.id, ['rack', 'face'], ['front', 'rear'])));
      out.push(fieldRow('Side', boundSelect('devices', d.id, ['rack', 'side'], ['full', 'left', 'right'], { defaultValue: 'full', default: 'full' })));
      out.push(fieldRow('Depth', boundSelect('devices', d.id, ['rack', 'depth'], ['full', 'half'], { defaultValue: 'full', default: 'full' })));
      out.push(h('button', { type: 'button', class: 'small', onclick: function () { goTo('racks', 'rack:' + rk.id, { canvas: true }); } }, 'Show in rack'));
    }
    return out;
  }

  function interfacesEditor(d) {
    const list = deepClone(d.interfaces || []);
    const nets = store.doc.networks || [];
    const switches = (store.doc.devices || []).filter(function (x) { return x.kind === 'switch' || x.kind === 'network'; });
    function send(label) { commit([{ op: 'merge', coll: 'devices', id: d.id, value: { interfaces: list.length ? deepClone(list) : null } }], label || 'Edit interfaces'); }
    const out = [];
    list.forEach(function (it, i) {
      const rows = [];
      function txt(label, key, opts) {
        opts = opts || {};
        const raw = it[key] === undefined || it[key] === null ? '' : String(it[key]);
        const inp = h('input', { value: opts.format ? opts.format(raw) : raw, inputmode: opts.inputmode, placeholder: opts.placeholder, autocapitalize: opts.parse ? 'none' : null, spellcheck: opts.parse ? 'false' : null });
        const warn = opts.check ? h('div', { class: 'problems hidden', role: 'status', style: { gridColumn: '2' } }) : null;
        const k = 'if/' + d.id + '/' + i + '/' + key;
        function showWarn() {
          if (!warn) return;
          const msg = inp.value.trim() ? opts.check(inp.value.trim()) : '';
          warn.textContent = msg || '';
          warn.classList.toggle('hidden', !msg);
        }
        inp.addEventListener('input', function () {
          debounced(k, function () {
            const v = inp.value.trim();
            if (!v) delete it[key]; else it[key] = opts.number ? Number(v) : (opts.parse ? opts.parse(v) : v);
            send('Edit ' + key + ' \u00b7 ' + d.name);
          });
        });
        inp.addEventListener('change', function () {
          if (opts.format && inp.value.trim()) inp.value = opts.format(inp.value.trim());
          showWarn();
        });
        const row = fieldRow(label, inp);
        if (warn) { row.appendChild(warn); showWarn(); }
        rows.push(row);
      }
      function pick(label, key, options) {
        const s = h('select', null, [h('option', { value: '' }, '\u2014')].concat(options.map(function (o) { return h('option', { value: o[0], selected: it[key] === o[0] ? true : null }, o[1]); })));
        s.addEventListener('change', function () { if (s.value) it[key] = s.value; else delete it[key]; send('Edit ' + key + ' \u00b7 ' + d.name); });
        rows.push(fieldRow(label, s));
      }
      if (it.source === 'discovery') {
        rows.push(h('div', { class: 'muted', style: { fontSize: '11.5px' } }, [
          h('span', { class: 'badge-discovered', style: { marginLeft: 0 }, title: 'Filled in by network discovery' }, 'discovered'),
          it.last_seen ? ' last seen ' + String(it.last_seen).replace('T', ' ').replace('Z', ' UTC') : '',
        ]));
      }
      txt('Id', 'id');
      pick('Role', 'role', ['primary', 'secondary', 'control', 'management', 'media'].map(function (x) { return [x, x]; }));
      txt('IP', 'ip', { inputmode: 'decimal', placeholder: '10.0.0.10' });
      txt('Prefix', 'prefix', { inputmode: 'numeric', number: true });
      txt('VLAN', 'vlan', { inputmode: 'numeric', number: true });
      txt('MAC', 'mac', {
        placeholder: 'aa:bb:cc:dd:ee:ff',
        format: function (v) { return normalizeMac(v) || v; },
        parse: function (v) { return normalizeMac(v) || v; },
        check: function (v) { return normalizeMac(v) ? '' : 'Not a MAC address; saved as typed.'; },
      });
      txt('Hostname', 'hostname');
      pick('Network', 'network', nets.map(function (n) { return [n.id, n.name || n.id]; }));
      pick('Switch', 'switch', switches.map(function (s) { return [s.id, s.name || s.id]; }));
      txt('Switch port', 'switch_port');
      pick('Protocol', 'protocol', ['dante', 'aes67', 'avb', 'ndi', 'st2110', 'sacn', 'artnet', 'qlan', 'control', 'management', 'other'].map(function (x) { return [x, x]; }));
      if (!ro()) rows.push(h('button', { type: 'button', class: 'small danger', onclick: function () { list.splice(i, 1); send('Remove interface'); render(); } }, 'Remove interface'));
      out.push(h('div', { style: { borderTop: i ? '1px solid var(--border)' : 'none', paddingTop: i ? '6px' : '0' } }, rows));
    });
    if (!ro()) out.push(h('button', { type: 'button', class: 'small', onclick: function () {
      const ids = {};
      list.forEach(function (x) { ids[x.id] = true; });
      const nid = !ids.primary ? 'primary' : newId('if', ids);
      list.push({ id: nid, role: nid === 'primary' ? 'primary' : 'secondary' });
      send('Add interface');
      render();
    } }, 'Add interface'));
    return out;
  }

  // -------------------------------------------------- inventory extras (FR-INV-10..13)

  const FIELD_KEY_MAX = 40;
  const FIELD_MAX = 32;

  // Short code row: XXXX-XXXX, a Copy link button and the device QR as a thumbnail (same image the QR section shows).
  function codeRow(d) {
    const code = d.short_code ? formatShortCode(d.short_code) : '';
    const row = h('div', { class: 'ins-code', 'data-code': code || '' });
    if (!code) {
      row.appendChild(h('span', { class: 'muted', 'aria-label': 'No code yet', text: '\u2014' }));
      return fieldRow('Code', h('div', { class: 'ins-code-wrap' }, [row]));
    }
    const link = ctx.api && ctx.api.codeLink ? ctx.api.codeLink(code) : '';
    row.appendChild(h('code', { class: 'ins-code-text', text: code }));
    if (link) {
      row.appendChild(h('button', { type: 'button', class: 'small chip ins-copy-link', 'data-copy': link, title: link, 'aria-label': 'Copy link for ' + d.name, onclick: function () {
        const done = function () { ctx.toast('Link copied: ' + link, 'ok'); };
        const fail = function () { ctx.toast('Could not copy. The link is ' + link, 'warn'); };
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(link).then(done, fail); return; }
        } catch (e) { /* fall through */ }
        fail();
      } }, 'Copy link'));
    }
    if (ctx.api && ctx.api.qrUrl) {
      const thumb = h('img', { class: 'ins-qr ins-qr-thumb', alt: 'QR code for ' + d.name, src: ctx.api.qrUrl(ctx.project, d.id), loading: 'lazy' });
      thumb.addEventListener('error', function () { thumb.classList.add('hidden'); });
      row.appendChild(thumb);
    }
    return fieldRow('Code', h('div', { class: 'ins-code-wrap' }, [row]));
  }

  // A container lists what it holds; each entry selects that device.
  function holdsBlock(d) {
    const items = containerContents(store.doc, d.id).sort(function (a, b) { return String(a.name || a.id).localeCompare(String(b.name || b.id), undefined, { numeric: true }); });
    const body = items.length
      ? h('ul', { class: 'ins-holds' }, items.map(function (x) {
        return h('li', null, [selLink({ type: 'device', id: x.id, device: x.id }, x.name || x.id, 'ins-holds-link', { 'data-device': x.id }), h('span', { class: 'muted', text: ' \u00b7 ' + (x.kind || 'device') })]);
      }))
      : h('div', { class: 'muted', text: 'Nothing stored here yet. Pick this container under "Stored in" on a device, or use "Put in container" in Inventory.' });
    return h('div', { class: 'field ins-holds-row' }, [h('label', null, 'Holds (' + items.length + ')'), body]);
  }

  // Key/value editor for inventory.fields; the whole object is written on change/blur (nulls delete removed keys).
  function customFieldsBlock(d) {
    const id = d.id;
    const cur = d.inventory && d.inventory.fields && typeof d.inventory.fields === 'object' ? d.inventory.fields : {};
    const rows = h('div', { class: 'ins-fields-rows' });
    const errHost = h('div', { class: 'ins-fields-err' });
    const wrap = h('div', { class: 'ins-fields', 'data-fields': id });
    function showError(msg) {
      errHost.textContent = '';
      if (msg) errHost.appendChild(inlineError({ message: msg }, null, { compact: true }));
    }
    function collect() {
      const next = {};
      let error = '';
      Array.prototype.forEach.call(rows.querySelectorAll('.ins-field-row'), function (r) {
        const kIn = r.querySelector('.ins-field-key');
        const vIn = r.querySelector('.ins-field-val');
        const k = kIn.value.trim().slice(0, FIELD_KEY_MAX);
        kIn.classList.remove('ins-field-dup');
        if (!k) return;
        if (Object.prototype.hasOwnProperty.call(next, k)) { error = 'Duplicate field name \u201c' + k + '\u201d. Field names must be unique.'; kIn.classList.add('ins-field-dup'); return; }
        next[k] = vIn.value;
      });
      if (!error && Object.keys(next).length > FIELD_MAX) error = 'At most ' + FIELD_MAX + ' custom fields per device.';
      return { next: next, error: error };
    }
    function write() {
      const c = collect();
      showError(c.error);
      if (c.error) return;
      const e = find(store.doc.devices, id);
      if (!e) return;
      const before = e.inventory && e.inventory.fields && typeof e.inventory.fields === 'object' ? e.inventory.fields : {};
      if (deepEqual(before, c.next)) return;
      let patch;
      if (!Object.keys(c.next).length) patch = null;
      else {
        patch = {};
        Object.keys(before).forEach(function (k) { patch[k] = null; });
        Object.keys(c.next).forEach(function (k) { patch[k] = c.next[k]; });
      }
      commit([{ op: 'merge', coll: 'devices', id: id, value: { inventory: { fields: patch } } }], 'Edit custom fields \u00b7 ' + (e.name || id));
    }
    function addRow(k, v, focus) {
      const kIn = h('input', { type: 'text', class: 'ins-field-key', placeholder: 'Field', maxlength: String(FIELD_KEY_MAX), 'aria-label': 'Field name', autocomplete: 'off' });
      kIn.value = k;
      const vIn = h('input', { type: 'text', class: 'ins-field-val', placeholder: 'Value', 'aria-label': 'Value' + (k ? ' for ' + k : ''), autocomplete: 'off' });
      vIn.value = v;
      const rm = h('button', { type: 'button', class: 'small ghost danger ins-field-rm', 'aria-label': 'Remove field' + (k ? ' ' + k : ''), text: '\u2715' });
      const r = h('div', { class: 'ins-field-row' }, [kIn, vIn, rm]);
      if (ro()) { kIn.disabled = true; vIn.disabled = true; rm.disabled = true; }
      kIn.addEventListener('change', write);
      vIn.addEventListener('change', write);
      kIn.addEventListener('blur', write);
      vIn.addEventListener('blur', write);
      rm.addEventListener('click', function () { r.remove(); write(); if (!rows.children.length) addBtn.focus(); });
      rows.appendChild(r);
      if (focus) kIn.focus();
      return r;
    }
    Object.keys(cur).forEach(function (k) { addRow(k, cur[k] == null ? '' : String(cur[k]), false); });
    const addBtn = h('button', { type: 'button', class: 'small chip ins-field-add', text: 'Add field' });
    addBtn.addEventListener('click', function () {
      if (rows.querySelectorAll('.ins-field-row').length >= FIELD_MAX) { showError('At most ' + FIELD_MAX + ' custom fields per device.'); return; }
      addRow('', '', true);
    });
    if (ro()) addBtn.disabled = true;
    wrap.appendChild(h('div', { class: 'ins-fields-head' }, [h('span', { class: 'muted', text: 'Custom fields' }), ro() ? null : addBtn]));
    if (!Object.keys(cur).length && ro()) wrap.appendChild(h('div', { class: 'muted', text: 'None.' }));
    wrap.appendChild(rows);
    wrap.appendChild(errHost);
    return wrap;
  }

  function attachmentsBlock(d) {
    const out = [];
    const atts = (store.doc.attachments || []).filter(function (a) { return a.device === d.id; });
    const thumbs = h('div', { class: 'ins-thumbs' });
    atts.forEach(function (a) {
      const url = ctx.api ? ctx.api.fileUrl(ctx.project, a) : '#';
      const isImg = /^image\//.test(a.mime || '');
      thumbs.appendChild(h('figure', null, [
        h('a', { href: url, target: '_blank', rel: 'noopener' }, isImg ? h('img', { src: url, alt: a.name, loading: 'lazy' }) : h('div', { class: 'chip' }, 'PDF / file')),
        h('figcaption', null, a.name),
        ro() || !ctx.api ? null : h('button', { type: 'button', class: 'small ghost danger', onclick: function () {
          ctx.confirm('Delete ' + a.name + '?', { danger: true }).then(function (y) {
            if (!y) return;
            ctx.api.deleteFile(ctx.project, a.id).then(function () { return ctx.reload(); }).then(render, function (e) { ctx.toast(e.message || String(e), 'err'); });
          });
        } }, 'Delete'),
      ]));
    });
    out.push(atts.length ? thumbs : h('div', { class: 'muted' }, 'No photos or documents.'));
    if (!ro() && ctx.api) {
      const upload = function (files, kind) {
        if (!files || !files.length) return;
        ctx.toast('Uploading ' + files.length + ' file' + (files.length > 1 ? 's' : '') + '\u2026');
        const go = ctx.flush ? ctx.flush() : Promise.resolve();
        go.then(function () { return ctx.api.upload(ctx.project, 'files', files, { device: d.id, kind: kind }); })
          .then(function () { return ctx.reload(); })
          .then(function () { ctx.toast('Uploaded', 'ok'); render(); }, function (e) { ctx.toast(e.message || String(e), 'err'); });
      };
      const fi = h('input', { type: 'file', accept: 'image/*,application/pdf', multiple: true, class: 'sr-only', id: 'ins-file-' + d.id });
      const cam = h('input', { type: 'file', accept: 'image/*', capture: 'environment', class: 'sr-only', id: 'ins-cam-' + d.id });
      fi.addEventListener('change', function () { const fs = Array.prototype.slice.call(fi.files); upload(fs, fs.every(function (f) { return /^image\//.test(f.type); }) ? 'photo' : 'document'); });
      cam.addEventListener('change', function () { upload(Array.prototype.slice.call(cam.files), 'photo'); });
      out.push(h('div', { class: 'row' }, [
        fi, h('label', { for: fi.id, class: 'chip', role: 'button', tabindex: '0' }, 'Upload photo / PDF'),
        cam, h('label', { for: cam.id, class: 'chip', role: 'button', tabindex: '0' }, 'Take photo'),
      ]));
    }
    return out;
  }

  function qrBlock(d, devUrl) {
    if (!ctx.api) return [h('div', { class: 'muted' }, 'QR codes need the server.')];
    const hint = h('div', { class: 'muted hidden', style: { fontSize: '12px' } }, 'No public URL yet. Set one in Settings (or FATHOM_PUBLIC_URL) to print QR labels.');
    const img = h('img', { class: 'ins-qr', alt: 'QR code for the ' + d.name + ' device page', src: ctx.api.qrUrl(ctx.project, d.id), loading: 'lazy' });
    img.addEventListener('error', function () { img.classList.add('hidden'); hint.classList.remove('hidden'); });
    return [img, hint, h('div', { class: 'row', style: { marginTop: '6px' } }, [h('a', { class: 'chip', href: ctx.api.qrUrl(ctx.project, d.id), download: d.id + '-qr.svg' }, 'Download SVG'), h('a', { class: 'chip', href: devUrl, target: '_blank', rel: 'noopener' }, 'Open device page')])];
  }

  // -------------------------------------------------- console channels (§6.8.6)

  function portMap(d) {
    const m = {};
    devicePorts(d).forEach(function (p) { m[p.id] = p; });
    return m;
  }
  function channelCtx(d, eff) {
    const ov = store.overlay || {};
    return {
      channels: channelMap(eff.channels), ports: portMap(d),
      labels: (ov.channel_labels && ov.channel_labels[d.id]) || {}, routes: ov.routes || [],
    };
  }
  function groupColor(ch) {
    const k = ch.kind;
    if (k === 'input' || k === 'stereo_input') return '#6fe2b4';
    if (k === 'dca' || k === 'mute_group') return 'var(--warn)';
    if (k === 'rack') return 'var(--muted)';
    return '#8ea2ff';
  }
  // Where the signal on a port sub-channel comes from / goes to over the network (overlay routes)
  function peerText(cctx, d, ep, dir) {
    if (!ep || !ep.port || !ep.ch) return '';
    const peer = routePeer(cctx.routes, d.id, ep.port, ep.ch, dir);
    if (!peer) return '';
    const pd = find(store.doc.devices, peer.device);
    return (pd ? pd.name : peer.device) + (peer.channel ? ' \u00b7 ' + peer.channel : '');
  }
  function selectChannel(d, ch) { store.select({ type: 'channel', id: d.id, device: d.id, channel: typeof ch === 'string' ? ch : ch.id }); }

  function applyButton(d, eff) {
    if (!ctx.api || ro() || !eff.pending) return null;
    return h('button', { type: 'button', class: 'small primary', 'data-action': 'apply-channels', onclick: function () {
      const go = ctx.flush ? ctx.flush() : Promise.resolve();
      go.then(function () { return ctx.api.applyChannels(ctx.project, d.id); }).then(function (res) {
        const s = (res && res.summary) || {};
        ctx.toast(res && res.changed ? 'Applied ' + (s.channels || 0) + ' channels and ' + (s.links || 0) + ' links to ' + d.name : 'Already up to date', 'ok');
        return ctx.reload().then(function () { return ctx.api.overlay(ctx.project).then(function (o) { store.setOverlay(o); }, function () { /* optional */ }); });
      }).then(render, function (e) { ctx.toast(e.message || String(e), 'err'); });
    } }, eff.source === 'overlay' ? 'Apply to device' : 'Re-apply import');
  }

  function consoleSection(d, eff) {
    const out = [];
    const cctx = channelCtx(d, eff);
    const idx = channelIndex(eff.links);
    const groups = groupChannels(eff.channels);
    const srcNote = eff.source === 'overlay'
      ? 'Imported from the console export and not applied yet \u2014 read-only until applied to the device.'
      : (eff.pending ? 'A newer import differs from what is on the device.' : '');
    const apply = applyButton(d, eff);
    if (srcNote || apply) {
      out.push(h('div', { class: 'ins-console-note' + (eff.source === 'overlay' ? ' pending' : '') }, [h('span', { class: 'grow' }, srcNote), apply]));
    }
    if (!groups[consoleTab].length) consoleTab = GROUPS.map(function (g) { return g.id; }).filter(function (gid) { return groups[gid].length; })[0] || 'inputs';
    const seg = h('div', { class: 'ins-seg', role: 'tablist', 'aria-label': 'Channel groups' }, GROUPS.map(function (g) {
      const n = groups[g.id].length;
      return h('button', { type: 'button', role: 'tab', class: 'ins-seg-btn' + (consoleTab === g.id ? ' on' : ''), 'aria-selected': consoleTab === g.id ? 'true' : 'false', disabled: n ? null : true, 'data-tab': g.id, onclick: function () {
        consoleTab = g.id; render();
      } }, g.label + (n ? ' ' + n : ''));
    }));
    const search = h('input', { type: 'search', class: 'ins-console-search', placeholder: 'Filter channels, names, patches', 'aria-label': 'Filter channels', value: consoleQuery, autocomplete: 'off' });
    search.addEventListener('input', function () { consoleQuery = search.value; debounced('console-q/' + d.id, function () { fillList(); }); });
    out.push(seg, search);
    const list = h('ul', { class: 'ins-chans', 'data-group': consoleTab });
    function fillList() {
      list.innerHTML = '';
      list.setAttribute('data-group', consoleTab);
      const rows = filterChannels(groups[consoleTab], consoleQuery, idx, cctx);
      rows.slice(0, 400).forEach(function (ch) {
        const s = channelSummary(ch, idx, cctx);
        const bits = [];
        const me = idx[ch.id] || {};
        if (s.source) {
          const first = (me.inputs || []).concat(me.feeds || [])[0];
          const peer = first && first.kind === 'input_patch' ? peerText(cctx, d, first.from, 'in') : '';
          bits.push('\u2190 ' + s.source + (peer ? ' (' + peer + ')' : ''));
        }
        if (s.dests.length) bits.push((ch.kind === 'dca' || ch.kind === 'mute_group' ? '' : '\u2192 ') + s.dests.slice(0, 4).join(', ') + (s.dests.length > 4 ? ' +' + (s.dests.length - 4) : ''));
        if (s.groups.length) bits.push(s.groups.join(', '));
        const btn = h('button', { type: 'button', class: 'ins-chan', 'data-channel': ch.id, onclick: function () { selectChannel(d, ch); } }, [
          h('span', { class: 'ins-chan-dot', style: { color: groupColor(ch) } }),
          h('span', { class: 'ins-chan-text' }, [
            h('span', { class: 'ins-chan-title' }, channelTitle(ch)),
            h('span', { class: 'ins-chan-sub' }, bits.length ? bits.join(' \u00b7 ') : (ch.kind === 'input' || ch.kind === 'stereo_input' ? 'no input patch' : 'nothing patched')),
          ]),
        ]);
        list.appendChild(h('li', null, btn));
      });
      if (!rows.length) list.appendChild(h('li', { class: 'muted', style: { padding: '8px 0' } }, consoleQuery ? 'No channel matches \u201c' + consoleQuery + '\u201d.' : 'None.'));
    }
    fillList();
    out.push(list);
    if (!ro() && eff.source === 'device') {
      const kindSel = h('select', { 'aria-label': 'Channel kind' }, [['input', 'Input channel'], ['stereo_input', 'Stereo input'], ['mix', 'Mix bus'], ['matrix', 'Matrix'], ['group', 'Group'], ['aux', 'Aux'], ['dca', 'DCA'], ['mute_group', 'Mute group']].map(function (k) { return h('option', { value: k[0] }, k[1]); }));
      kindSel.value = consoleTab === 'buses' ? 'mix' : consoleTab === 'dcas' ? 'dca' : 'input';
      out.push(h('div', { class: 'row', style: { marginTop: '8px' } }, [h('button', { type: 'button', class: 'small', onclick: function () {
        const dd = find(store.doc.devices, d.id);
        const ch = nextChannel((dd && dd.channels) || [], kindSel.value);
        commit([{ op: 'merge', coll: 'devices', id: d.id, value: { channels: ((dd && dd.channels) || []).concat([ch]) } }], 'Add ' + channelLabel(ch) + ' \u00b7 ' + d.name);
        selectChannel(d, ch);
      } }, 'Add'), kindSel]));
    }
    return out;
  }

  function renderChannel(d, ch, eff) {
    kind = 'channel';
    const cctx = channelCtx(d, eff);
    const idx = channelIndex(eff.links);
    const me = idx[ch.id] || { inputs: [], sends: [], feeds: [], outputs: [], direct: [], insertSend: [], insertReturn: [], dca: [], mute: [], members: [] };
    const editable = !ro() && eff.source === 'device';
    const kindLabel = { input: 'Input channel', stereo_input: 'Stereo input', mix: 'Mix bus', aux: 'Aux bus', group: 'Group bus', matrix: 'Matrix', stereo: 'Stereo bus', mono: 'Mono bus', dca: 'DCA', mute_group: 'Mute group', rack: 'Rack' }[ch.kind] || ch.kind;
    const back = h('button', { type: 'button', class: 'small ghost', 'aria-label': 'Back to ' + d.name, onclick: function () { store.select({ type: 'device', id: d.id, device: d.id }); } }, '\u2190 ' + (d.name || d.id));
    root.appendChild(head(kindLabel, groupColor(ch), channelTitle(ch), [d.name || d.id, ch.source && ch.source !== 'user' ? ' \u00b7 from ' + ch.source + ' import' : ''].join(''), { extra: back }));
    root.appendChild(h('div', { class: 'ins-actions' }, [
      ctx.api ? h('button', { type: 'button', class: 'small primary', 'data-action': 'trace', onclick: function () { openTrace(channelRef(d.id, ch), channelTitle(ch), d.name || d.id, d); } }, 'Trace path') : null,
      h('button', { type: 'button', class: 'small', onclick: function () { goTo('patch', 'device:' + d.id, { canvas: true }); } }, 'Show console in patch view'),
    ]));
    if (eff.source === 'overlay') {
      root.appendChild(h('div', { class: 'ins-console-note pending', style: { margin: '0 12px 8px' } }, [
        h('span', { class: 'grow' }, 'Imported, not applied yet. Apply the import to the device to edit channels and patches.'), applyButton(d, eff),
      ]));
    }

    function links() { const dd = find(store.doc.devices, d.id); return ((dd && dd.channel_links) || []).slice(); }
    function commitLinks(next, label) { commit([{ op: 'merge', coll: 'devices', id: d.id, value: { channel_links: next } }], label + ' \u00b7 ' + channelTitle(ch)); render(); }
    function chanField(label, key, opts) {
      opts = opts || {};
      const input = opts.select || h('input', { value: ch[key] === undefined || ch[key] === null ? '' : String(ch[key]), placeholder: opts.placeholder, list: opts.list });
      const k = 'chan/' + d.id + '/' + ch.id + '/' + key;
      function send() {
        const dd = find(store.doc.devices, d.id);
        if (!dd) return;
        const patch = {};
        patch[key] = input.value.trim() === '' ? null : input.value.trim();
        commit([{ op: 'merge', coll: 'devices', id: d.id, value: { channels: updateChannel(dd.channels || [], ch.id, patch) } }], 'Edit ' + key + ' \u00b7 ' + channelLabel(ch) + ' \u00b7 ' + d.name);
      }
      if (input.tagName === 'SELECT') input.addEventListener('change', send);
      else { input.addEventListener('input', function () { debounced(k, send); }); input.addEventListener('change', function () { if (pendingTimers[k]) { clearTimeout(pendingTimers[k].id); delete pendingTimers[k]; send(); } }); }
      const row = fieldRow(label, input);
      if (!editable) input.disabled = true;
      return row;
    }
    const colorSel = h('select', null, CHANNEL_COLORS.map(function (c) { return h('option', { value: c === 'Off' ? '' : c, selected: (ch.color || '') === (c === 'Off' ? '' : c) ? true : null }, c); }));
    if (ch.color && CHANNEL_COLORS.indexOf(ch.color) < 0) colorSel.appendChild(h('option', { value: ch.color, selected: true }, ch.color));
    root.appendChild(section('fields', 'Channel', [
      chanField('Name', 'name', { placeholder: 'e.g. Bass' }),
      chanField('Label', 'label', { placeholder: channelLabel(Object.assign({}, ch, { label: null })) }),
      chanField('Colour', 'color', { select: colorSel }),
      chanField('Icon', 'icon', { placeholder: 'console icon' }),
      chanField('Note', 'note', { select: (function () { const t = h('textarea', { rows: 2 }); t.value = ch.note || ''; return t; })() }),
    ], true));

    function linkRow(ln, text, sub, removable) {
      return h('div', { class: 'ins-link row', 'data-link-kind': ln.kind }, [
        h('span', { class: 'grow' }, [h('span', null, text), sub ? h('span', { class: 'muted' }, ' ' + sub) : null]),
        ln.source && ln.source !== 'user' ? h('span', { class: 'chip', title: 'From the ' + ln.source + ' import' }, ln.source) : null,
        editable && removable !== false ? h('button', { type: 'button', class: 'small ghost danger', 'aria-label': 'Remove', onclick: function () { commitLinks(removeLink(links(), ln), 'Remove ' + ln.kind.replace(/_/g, ' ')); } }, '\u00d7') : null,
      ]);
    }
    // endpoint editor: a port of this device (+ channel number) or a rack return
    function endpointPicker(dir, onPick, okLabel) {
      const ports = devicePorts(d).filter(function (p) { return (p.dir || 'io') === 'io' || p.dir === dir; });
      const racks = eff.channels.filter(function (c) { return c.kind === 'rack'; });
      const kindSel = h('select', { 'aria-label': 'Source kind' }, [h('option', { value: 'port' }, 'Port'), racks.length ? h('option', { value: 'rack' }, 'Rack') : null, h('option', { value: 'text' }, 'Text')]);
      const portSel = h('select', { 'aria-label': 'Port' }, ports.map(function (p) { return h('option', { value: p.id }, portLabel(p) + (p.channels > 1 ? ' (' + p.channels + ' ch)' : '')); }));
      const chI = h('input', { type: 'number', inputmode: 'numeric', min: '1', placeholder: 'ch', 'aria-label': 'Channel number', style: { width: '64px' } });
      const rackSel = h('select', { 'aria-label': 'Rack', class: 'hidden' }, racks.map(function (c) { return h('option', { value: c.id }, channelTitle(c)); }));
      const tagSel = h('select', { 'aria-label': 'Rack side', class: 'hidden' }, [['', '\u2014'], ['A', 'A'], ['B', 'B']].map(function (t) { return h('option', { value: t[0] }, t[1]); }));
      const textI = h('input', { placeholder: 'e.g. REC 1', 'aria-label': 'Text', class: 'hidden' });
      function sync() {
        const k = kindSel.value;
        portSel.classList.toggle('hidden', k !== 'port');
        const p = ports.filter(function (x) { return x.id === portSel.value; })[0];
        chI.classList.toggle('hidden', k !== 'port' || !(p && p.channels > 1));
        if (p && p.channels > 1) chI.max = String(p.channels);
        rackSel.classList.toggle('hidden', k !== 'rack');
        tagSel.classList.toggle('hidden', k !== 'rack');
        textI.classList.toggle('hidden', k !== 'text');
      }
      kindSel.addEventListener('change', sync);
      portSel.addEventListener('change', sync);
      sync();
      const ok = h('button', { type: 'button', class: 'small', onclick: function () {
        const k = kindSel.value;
        let ep = null;
        if (k === 'port' && portSel.value) {
          ep = { port: portSel.value };
          const p = ports.filter(function (x) { return x.id === portSel.value; })[0];
          if (p && p.channels > 1) { const n = parseInt(chI.value, 10); if (!(n >= 1)) { ctx.toast('Enter the channel number on ' + portLabel(p), 'warn'); return; } ep.ch = n; }
        } else if (k === 'rack' && rackSel.value) {
          ep = { channel: rackSel.value };
          if (tagSel.value) ep.tag = tagSel.value;
        } else if (k === 'text' && textI.value.trim()) ep = { text: textI.value.trim() };
        if (ep) onPick(ep);
      } }, okLabel || 'Set');
      return h('div', { class: 'row ins-ep', style: { flexWrap: 'wrap', marginTop: '6px' } }, [kindSel, portSel, chI, rackSel, tagSel, textI, ok]);
    }
    const isInput = ch.kind === 'input' || ch.kind === 'stereo_input';
    const isBus = BUS_KINDS.indexOf(ch.kind) >= 0;
    const isGroup = ch.kind === 'dca' || ch.kind === 'mute_group';

    // --- input patch / fed by
    if (isInput || ch.kind === 'rack') {
      const rows = [];
      me.inputs.forEach(function (ln) {
        const peer = peerText(cctx, d, ln.from, 'in');
        rows.push(linkRow(ln, '\u2190 ' + linkEndpointText(ln.from, Object.assign({}, cctx, { dir: 'in' })), peer ? '(' + peer + ')' : ''));
      });
      me.insertReturn.forEach(function (ln) { rows.push(linkRow(ln, '\u21A9 insert ' + (ln.insert || '') + ' return from ' + linkEndpointText(ln.from, Object.assign({}, cctx, { dir: 'in' })))); });
      if (!rows.length) rows.push(h('div', { class: 'muted' }, 'No input patch.'));
      if (editable) rows.push(endpointPicker('in', function (ep) { commitLinks(isInput ? setInputPatch(links(), ch.id, ep) : links().concat([{ from: ep, to: { channel: ch.id }, kind: 'input_patch', source: 'user' }]), 'Patch input'); }, 'Patch input'));
      root.appendChild(section('input', 'Input patch', rows, true));
    }
    if (isBus || ch.kind === 'rack') {
      const rows = me.feeds.map(function (ln) {
        const src = cctx.channels[ln.from.channel];
        return h('div', { class: 'ins-link row' }, [
          h('button', { type: 'button', class: 'ins-chan-link grow', onclick: function () { if (src) selectChannel(d, src); } }, (src ? channelTitle(src) : String(ln.from.channel)) + (ln.level !== undefined && ln.level !== null ? ' \u00b7 ' + ln.level : '')),
          editable ? h('button', { type: 'button', class: 'small ghost danger', 'aria-label': 'Remove send', onclick: function () { commitLinks(removeLink(links(), ln), 'Remove send'); } }, '\u00d7') : null,
        ]);
      });
      me.inputs.forEach(function (ln) { rows.push(linkRow(ln, '\u2190 ' + linkEndpointText(ln.from, Object.assign({}, cctx, { dir: 'in' })) + (ln.insert ? ' (insert ' + ln.insert + ' send)' : ''))); });
      if (!rows.length) rows.push(h('div', { class: 'muted' }, isBus ? 'Nothing is sent to this bus yet \u2014 a console export has no send levels; tick sends on the channels or import a CSV.' : 'Nothing patched in.'));
      root.appendChild(section('fedby', (isBus ? 'Fed by' : 'Inputs') + ' (' + rows.length + ')', rows, true));
    }
    // --- sends (inputs → buses, buses → matrix / stereo)
    if (isInput || (isBus && ch.kind !== 'matrix' && ch.kind !== 'stereo' && ch.kind !== 'mono')) {
      const targets = eff.channels.filter(function (c) {
        if (c.id === ch.id || BUS_KINDS.indexOf(c.kind) < 0) return false;
        if (isInput) return true;
        return c.kind === 'matrix' || c.kind === 'stereo' || c.kind === 'mono';
      });
      const on = {};
      me.sends.forEach(function (ln) { on[ln.to.channel] = ln; });
      const grid = h('div', { class: 'ins-chipgrid', role: 'group', 'aria-label': 'Sends' }, targets.map(function (c) {
        const active = !!on[c.id];
        return h('button', { type: 'button', class: 'chip' + (active ? ' on' : ''), 'aria-pressed': active ? 'true' : 'false', 'data-send': c.id, title: channelTitle(c), disabled: editable ? null : true, onclick: function () {
          commitLinks(toggleSend(links(), ch.id, c.id, !active), (active ? 'Remove send to ' : 'Send to ') + channelLabel(c));
        } }, channelLabel(c));
      }));
      const n = me.sends.length;
      root.appendChild(section('sends', 'Sends (' + n + ')', [
        targets.length ? grid : h('div', { class: 'muted' }, 'No buses on this console yet.'),
        !n ? h('div', { class: 'muted', style: { marginTop: '6px', fontSize: '12px' } }, 'No sends recorded \u2014 nothing is assumed, not even Stereo L/R. The trace stops here until a send is ticked.') : null,
      ], true));
    }
    // --- DCA / mute membership
    if (isInput || isBus) {
      const groupsList = eff.channels.filter(function (c) { return c.kind === 'dca' || c.kind === 'mute_group'; });
      if (groupsList.length || me.dca.length || me.mute.length) {
        const mine = {};
        me.dca.concat(me.mute).forEach(function (ln) { mine[ln.to.channel] = ln; });
        const grid = h('div', { class: 'ins-chipgrid', role: 'group', 'aria-label': 'DCA and mute groups' }, groupsList.map(function (c) {
          const active = !!mine[c.id];
          return h('button', { type: 'button', class: 'chip' + (active ? ' on' : ''), 'aria-pressed': active ? 'true' : 'false', 'data-group': c.id, title: channelTitle(c), disabled: editable ? null : true, onclick: function () {
            commitLinks(toggleMembership(links(), c.kind === 'dca' ? 'dca' : 'mute', ch.id, c.id, !active), (active ? 'Remove from ' : 'Add to ') + channelTitle(c));
          } }, channelTitle(c));
        }));
        root.appendChild(section('groups', 'DCA / mute groups (' + (me.dca.length + me.mute.length) + ')', [grid], true));
      }
    }
    if (isGroup) {
      const candidates = eff.channels.filter(function (c) { return c.kind === 'input' || c.kind === 'stereo_input' || BUS_KINDS.indexOf(c.kind) >= 0; });
      const mem = {};
      me.members.forEach(function (ln) { mem[ln.from.channel] = ln; });
      const grid = h('div', { class: 'ins-chipgrid', role: 'group', 'aria-label': 'Members' }, candidates.map(function (c) {
        const active = !!mem[c.id];
        return h('button', { type: 'button', class: 'chip' + (active ? ' on' : ''), 'aria-pressed': active ? 'true' : 'false', 'data-member': c.id, title: channelTitle(c), disabled: editable ? null : true, onclick: function () {
          commitLinks(toggleMembership(links(), ch.kind === 'dca' ? 'dca' : 'mute', c.id, ch.id, !active), (active ? 'Remove ' : 'Add ') + channelLabel(c) + (active ? ' from ' : ' to ') + channelLabel(ch));
        } }, channelLabel(c));
      }));
      root.appendChild(section('members', 'Members (' + me.members.length + ')', [grid, !me.members.length ? h('div', { class: 'muted', style: { marginTop: '6px', fontSize: '12px' } }, 'No members recorded yet. Tap channels to add them.') : null], true));
    }
    // --- outputs / direct out / insert sends
    if (isInput || isBus || ch.kind === 'rack') {
      const rows = [];
      me.outputs.forEach(function (ln) { const peer = peerText(cctx, d, ln.to, 'out'); rows.push(linkRow(ln, '\u2192 ' + linkEndpointText(ln.to, Object.assign({}, cctx, { dir: 'out' })), peer ? '(' + peer + ')' : '')); });
      me.direct.forEach(function (ln) { const peer = peerText(cctx, d, ln.to, 'out'); rows.push(linkRow(ln, '\u2192 direct out \u2192 ' + linkEndpointText(ln.to, Object.assign({}, cctx, { dir: 'out' })), peer ? '(' + peer + ')' : '')); });
      me.insertSend.forEach(function (ln) { rows.push(linkRow(ln, '\u21AA insert ' + (ln.insert || '') + ' send to ' + linkEndpointText(ln.to, Object.assign({}, cctx, { dir: 'out' })))); });
      if (!rows.length) rows.push(h('div', { class: 'muted' }, isBus ? 'No output patch.' : 'No direct out or inserts.'));
      if (editable) {
        const kind = isBus || ch.kind === 'rack' ? 'output_patch' : 'direct_out';
        rows.push(endpointPicker('out', function (ep) { commitLinks(addOutput(links(), ch.id, ep, kind), kind === 'direct_out' ? 'Add direct out' : 'Add output patch'); }, kind === 'direct_out' ? 'Add direct out' : 'Add output'));
      }
      root.appendChild(section('outputs', (isBus || ch.kind === 'rack' ? 'Output patch' : 'Direct out & inserts') + ' (' + (me.outputs.length + me.direct.length + me.insertSend.length) + ')', rows, true));
    }
    if (editable) {
      root.appendChild(h('div', { class: 'ins-actions' }, [h('button', { type: 'button', class: 'small danger', onclick: function () {
        ctx.confirm('Delete ' + channelTitle(ch) + ' and its patches?', { danger: true }).then(function (y) {
          if (!y) return;
          const dd = find(store.doc.devices, d.id);
          if (!dd) return;
          const chans = (dd.channels || []).filter(function (c) { return c && c.id !== ch.id; });
          const lns = (dd.channel_links || []).filter(function (l) { return !(l && ((l.from && l.from.channel === ch.id) || (l.to && l.to.channel === ch.id))); });
          commit([{ op: 'merge', coll: 'devices', id: d.id, value: { channels: chans, channel_links: lns } }], 'Delete ' + channelTitle(ch) + ' \u00b7 ' + d.name);
          store.select({ type: 'device', id: d.id, device: d.id });
        });
      } }, 'Delete channel')]));
    }
  }

  // Trace drawer (§6.8.7) over GET …/trace; tapping a hop selects it in the inspector.
  function openTrace(ref, title, sub, d) {
    if (!ctx.api) return;
    if (traceDrawer) traceDrawer.close();
    traceDrawer = openTraceDrawer({
      from: ref, title: title, sub: sub, direction: 'down', dca: true,
      fetchPaths: function (params) { return ctx.api.trace(ctx.project, params); },
      actions: [{ label: 'Open in patch view', onclick: function (st) { st.close(); goTo('patch', 'device:' + (d ? d.id : ref.split(':')[0]), { canvas: true }); } }],
      onHop: function (hop) {
        if (!hop || !hop.device) return;
        if (hop.kind === 'channel' || hop.kind === 'dca') store.select({ type: 'channel', id: hop.device, device: hop.device, channel: hop.channel });
        else if (hop.port) store.select({ type: 'port', id: hop.device, device: hop.device, port: hop.port });
        else store.select({ type: 'device', id: hop.device, device: hop.device });
        if (traceDrawer) traceDrawer.close();
      },
      onClose: function () { traceDrawer = null; },
    });
  }

  // -------------------------------------------------- port

  function renderPort(d, p) {
    kind = 'port';
    const m = mediumInfo(p.medium, vocab);
    const cables = store.index.cablesByPort[d.id + ':' + p.id] || [];
    root.appendChild(head('Port \u00b7 ' + (p.dir || 'io'), m.color, (d.name || d.id) + ' \u00b7 ' + portLabel(p), (p.name || '') + (p.group ? ' \u00b7 ' + p.group : '') + ' \u00b7 ' + (m.label || p.medium),
      { status: cables.length ? 'patched' : 'not patched' }));

    // "Now connected" leads: far end (port drawer), cable (cable drawer), Trace; then the port fields.
    const list = h('div', { class: 'ins-now' });
    cables.forEach(function (c) {
      const mine = c.from.device === d.id && c.from.port === p.id ? 'from' : 'to';
      const other = mine === 'from' ? c.to : c.from;
      const od = find(store.doc.devices, other.device);
      const op = od && other.port ? devicePorts(od).filter(function (x) { return x.id === other.port; })[0] : null;
      const peerText = (od ? od.name : other.device) + (op ? ' \u00b7 ' + portLabel(op) : (other.port ? ' \u00b7 ' + other.port : ''));
      const peerSel = op ? { type: 'port', id: od.id, device: od.id, port: op.id } : { type: 'device', id: other.device, device: other.device };
      list.appendChild(h('div', { class: 'ins-now-row', 'data-cable': c.id }, [
        h('span', { class: 'ins-now-dir', title: mine === 'from' ? 'Goes to' : 'Comes from' }, mine === 'from' ? '\u2192' : '\u2190'),
        od ? selLink(peerSel, peerText, 'ins-now-peer', { 'data-peer': selToString(peerSel) }) : h('span', { class: 'ins-now-peer' }, peerText),
        selLink({ type: 'cable', id: c.id }, c.tag || 'Cable', 'chip ins-now-cable', { 'aria-label': 'Cable ' + (c.tag || c.id), title: 'Cable ' + (c.tag || c.id) }),
        ro() ? null : h('button', { type: 'button', class: 'small danger', 'aria-label': 'Disconnect', onclick: function () { commit(disconnectOps(store.doc, c.id), 'Disconnect ' + portLabel(p)); render(); } }, '\u00d7'),
      ]));
    });
    if (!cables.length) list.appendChild(h('div', { class: 'muted' }, 'Not patched.'));
    const tools = h('div', { class: 'row ins-now-tools' }, [
      ctx.api ? h('button', { type: 'button', class: 'small', 'data-action': 'trace', onclick: function () { openTrace(d.id + ':' + p.id, (d.name || d.id) + ' \u00b7 ' + portLabel(p), p.channels > 1 ? p.channels + ' channels' : (m.label || p.medium || ''), d); } }, 'Trace path') : null,
      ro() ? null : h('button', { type: 'button', class: 'small', onclick: function () {
        ctx.pickPort({ compatibleWith: { device: d.id, port: p.id }, room: store.room }).then(function (t) {
          if (!t) return;
          const here = { device: d.id, port: p.id };
          const ops = p.dir === 'in' ? connectOps(store.doc, t, here, {}, vocab) : connectOps(store.doc, here, t, {}, vocab);
          commit(ops, 'Connect ' + (d.name || d.id) + ' ' + portLabel(p));
          render();
        });
      } }, 'Patch\u2026'),
    ]);
    root.appendChild(section('cables', 'Now connected (' + cables.length + ')', [list, tools.children.length ? tools : null], true));

    function portField(label, key, opts) {
      opts = opts || {};
      const input = opts.select || h('input', { value: p[key] === undefined || p[key] === null ? '' : String(p[key]), list: opts.list, inputmode: opts.inputmode, placeholder: opts.placeholder });
      const k = 'pf/' + d.id + '/' + p.id + '/' + key;
      function send() {
        const dd = find(store.doc.devices, d.id);
        if (!dd) return;
        const next = deepClone(devicePorts(dd));
        const t = next.filter(function (x) { return x.id === p.id; })[0];
        if (!t) return;
        let v = input.value.trim();
        if (opts.number) { const n = parseInt(v, 10); v = n > 1 ? n : ''; }
        if (v === '') delete t[key]; else t[key] = v;
        if (key === 'name' && !t.name) t.name = p.id;
        commit(setPortsOps(store.doc, d.id, next), 'Edit ' + key + ' \u00b7 ' + (d.name || d.id) + ' ' + portLabel(p));
      }
      if (input.tagName === 'SELECT') input.addEventListener('change', send);
      else { input.addEventListener('input', function () { debounced(k, send); }); input.addEventListener('change', function () { if (pendingTimers[k]) { clearTimeout(pendingTimers[k].id); delete pendingTimers[k]; send(); } }); }
      return fieldRow(label, input);
    }
    const medS = h('select');
    if (p.medium && !(vocab.media || {})[p.medium]) medS.appendChild(h('option', { value: p.medium }, p.medium));
    mediaOptions().forEach(function (mm) { medS.appendChild(h('option', { value: mm[0], selected: mm[0] === p.medium ? true : null }, mm[1])); });
    const dirS = h('select', null, ['in', 'out', 'io'].map(function (x) { return h('option', { value: x, selected: (p.dir || 'io') === x ? true : null }, x); }));
    const noteI = h('textarea', { rows: 3 });
    noteI.value = p.note || '';
    root.appendChild(section('fields', 'Port', [
      portField('Label', 'label', { placeholder: 'what is on it' }),
      portField('Name', 'name'),
      portField('Direction', 'dir', { select: dirS }),
      portField('Medium', 'medium', { select: medS }),
      portField('Connector', 'connector', { list: connectorList() }),
      portField('Channels', 'channels', { inputmode: 'numeric', number: true }),
      portField('Note', 'note', { select: noteI }),
    ], true));
    root.appendChild(h('div', { class: 'ins-actions' }, [
      h('button', { type: 'button', class: 'small', onclick: function () { store.select({ type: 'device', id: d.id, device: d.id }); } }, 'Device details'),
    ]));
  }

  // -------------------------------------------------- cable

  function endpointText(e) {
    const dd = find(store.doc.devices, e && e.device);
    const pp = dd && e.port ? devicePorts(dd).filter(function (x) { return x.id === e.port; })[0] : null;
    return (dd ? dd.name : (e && e.device) || '?') + (pp ? ' \u00b7 ' + portLabel(pp) : (e && e.port ? ' \u00b7 ' + e.port : ' (device)'));
  }

  // Device name → device page (device drawer without a router) · port label → port drawer.
  function endpointLinks(e) {
    const dd = find(store.doc.devices, e && e.device);
    const pp = dd && e.port ? devicePorts(dd).filter(function (x) { return x.id === e.port; })[0] : null;
    if (!dd) return h('span', { class: 'ins-ep-text' }, endpointText(e));
    const devHref = pageHref({ view: 'devices', id: dd.id });
    const devSel = { type: 'device', id: dd.id, device: dd.id };
    return h('span', { class: 'ins-ep-text' }, [
      devHref ? h('a', { class: 'ins-ep-dev', href: devHref, title: 'Open the device page' }, dd.name || dd.id) : selLink(devSel, dd.name || dd.id, 'ins-ep-dev'),
      ' \u00b7 ',
      pp ? selLink({ type: 'port', id: dd.id, device: dd.id, port: pp.id }, portLabel(pp), 'ins-ep-port', { 'data-peer': 'port:' + dd.id + ':' + pp.id })
        : h('span', { class: 'muted' }, e.port ? e.port : '(device)'),
    ]);
  }

  function renderCable(c) {
    kind = 'cable';
    const m = mediumInfo(c.medium, vocab);
    const units = (store.doc.settings && store.doc.settings.units) || 'metric';
    root.appendChild(head('Cable \u00b7 ' + (m.label || c.medium), m.color, c.tag || c.label || c.id, endpointText(c.from) + ' \u2192 ' + endpointText(c.to),
      { status: c.status || 'installed' }));
    function endRow(end) {
      const e = c[end];
      return h('div', { class: 'row ins-ep-row', 'data-end': end }, [
        h('span', { class: 'muted ins-ep-label' }, end === 'from' ? 'From' : 'To'),
        endpointLinks(e),
        ro() ? null : h('button', { type: 'button', class: 'small', onclick: function () {
          const other = end === 'from' ? c.to : c.from;
          ctx.pickPort({ compatibleWith: other && other.port ? other : null, room: store.room }).then(function (t) {
            if (!t) return;
            commit(repatchOps(store.doc, c.id, end, t), 'Re-patch ' + (c.tag || c.id));
            render();
          });
        } }, 'Change\u2026'),
      ]);
    }
    root.appendChild(section('endpoints', 'Endpoints', [endRow('from'), endRow('to')], true));
    const lenI = bound('cables', c.id, ['length_m'], { inputmode: 'decimal', parse: function (v) { return parseLength(v, units); }, format: function (v) { return formatLength(v, units); }, placeholder: units === 'imperial' ? 'e.g. 25 ft' : 'e.g. 7.5 m', label: 'Set length' });
    root.appendChild(section('fields', 'Cable', [
      fieldRow('Tag', bound('cables', c.id, ['tag'], { placeholder: 'e.g. A-012', label: 'Set tag' })),
      fieldRow('Signal', bound('cables', c.id, ['signal'])),
      fieldRow('Medium', boundSelect('cables', c.id, ['medium'], mediaOptions(), { label: 'Set medium' })),
      fieldRow('Length', lenI),
      fieldRow('Status', boundSelect('cables', c.id, ['status'], (vocab.statuses || ['installed', 'planned', 'spare', 'retired']), { defaultValue: 'installed', default: 'installed' })),
      fieldRow('Type', bound('cables', c.id, ['type'], { placeholder: 'e.g. XLR3 M-F', list: connectorList() })),
      fieldRow('Color', bound('cables', c.id, ['color'])),
      fieldRow('Channels', bound('cables', c.id, ['channels'], { inputmode: 'numeric', number: true })),
      fieldRow('Bundle', boundSelect('cables', c.id, ['bundle'], (store.doc.bundles || []).map(function (b) { return [b.id, b.tag || b.label || b.id]; }), { empty: 'None' })),
      fieldRow('Map label', bound('cables', c.id, ['label'])),
      fieldRow('Two-way', boundCheck('cables', c.id, ['bidirectional'])),
      fieldRow('Note', bound('cables', c.id, ['note'], { multiline: true })),
    ], true));
    const inSchedules = routed() && ctx.route.view === 'schedules' && (ctx.route.tab || 'cables') === 'cables';
    const actions = h('div', { class: 'ins-actions' }, [
      inSchedules ? null : h('button', { type: 'button', class: 'small', 'data-action': 'schedules', onclick: function () { goTo('schedules', 'cable:' + c.id, { tab: 'cables' }); } }, 'Open in schedules'),
      ro() ? null : h('button', { type: 'button', class: 'small danger', onclick: function () { commit(disconnectOps(store.doc, c.id), 'Delete cable ' + (c.tag || c.id)); store.select(null); } }, 'Delete cable'),
    ]);
    if (actions.children.length) root.appendChild(actions);
  }

  // -------------------------------------------------- other entities

  function renderRack(r) {
    kind = 'rack';
    root.appendChild(head('Rack', 'var(--accent)', r.name || r.id, (r.units || '?') + 'U', { page: { view: 'racks', id: r.id } }));
    root.appendChild(section('fields', 'Rack', [
      fieldRow('Name', bound('racks', r.id, ['name'])),
      fieldRow('Room', boundSelect('racks', r.id, ['room'], roomOptions(false), { empty: '\u2014' })),
      fieldRow('Location', boundSelect('racks', r.id, ['location'], (store.doc.locations || []).map(function (l) { return [l.id, l.name || l.id]; }), { empty: '\u2014' })),
      fieldRow('Units', bound('racks', r.id, ['units'], { inputmode: 'numeric', number: true })),
      fieldRow('Numbering', boundSelect('racks', r.id, ['numbering'], ['bottom_up', 'top_down'], { defaultValue: 'bottom_up', default: 'bottom_up' })),
      fieldRow('Notes', bound('racks', r.id, ['notes'], { multiline: true })),
    ], true));
    if (!ro()) root.appendChild(h('div', { class: 'ins-actions' }, [h('button', { type: 'button', class: 'small danger', onclick: function () {
      ctx.confirm('Delete rack ' + (r.name || r.id) + '? Devices in it become unracked.', { danger: true }).then(function (y) {
        if (!y) return;
        const ops = [{ op: 'del', coll: 'racks', id: r.id }];
        (store.doc.devices || []).forEach(function (d) { if (d.rack && d.rack.id === r.id) ops.push({ op: 'merge', coll: 'devices', id: d.id, value: { rack: null } }); });
        commit(ops, 'Delete rack ' + (r.name || r.id));
        store.select(null);
      });
    } }, 'Delete rack')]));
  }

  function renderFloorplan(f) {
    kind = 'floorplan';
    root.appendChild(head('Floor plan', 'var(--accent)', f.name || f.id, ((f.markers || []).length) + ' markers'));
    root.appendChild(section('fields', 'Floor plan', [
      fieldRow('Name', bound('floorplans', f.id, ['name'])),
      fieldRow('Room', boundSelect('floorplans', f.id, ['room'], roomOptions(false))),
      fieldRow('Order', bound('floorplans', f.id, ['order'], { inputmode: 'numeric', number: true })),
      fieldRow('Notes', bound('floorplans', f.id, ['notes'], { multiline: true })),
    ], true));
    if (!ro()) root.appendChild(h('div', { class: 'ins-actions' }, [h('button', { type: 'button', class: 'small danger', onclick: function () {
      ctx.confirm('Delete floor plan ' + (f.name || f.id) + '? The uploaded files are kept.', { danger: true }).then(function (y) { if (y) { commit([{ op: 'del', coll: 'floorplans', id: f.id }], 'Delete floor plan'); store.select(null); } });
    } }, 'Delete plan')]));
  }

  function renderMarker(sel) {
    const f = find(store.doc.floorplans, sel.floorplan);
    const dev = find(store.doc.devices, sel.device || sel.id);
    const markers = (f && f.markers) || [];
    const mk = markers.filter(function (m) { return m.device === (sel.device || sel.id); })[0];
    if (!f || !mk) { renderEmpty(sel); return; }
    kind = 'marker';
    root.appendChild(head('Marker', 'var(--accent)', dev ? dev.name : mk.device, f.name));
    function setMarker(patch, label) {
      const next = deepClone(markers).map(function (m) { return m.device === mk.device ? Object.assign(m, patch) : m; });
      next.forEach(function (m) { Object.keys(m).forEach(function (k) { if (m[k] === null || m[k] === '') delete m[k]; }); });
      commit([{ op: 'merge', coll: 'floorplans', id: f.id, value: { markers: next } }], label);
    }
    const lab = h('input', { value: mk.label || '' });
    lab.addEventListener('input', function () { debounced('mk-label', function () { setMarker({ label: lab.value.trim() || null }, 'Marker label'); }); });
    const rot = h('input', { value: mk.rotation || '', inputmode: 'decimal' });
    rot.addEventListener('change', function () { const n = parseFloat(rot.value); setMarker({ rotation: isNaN(n) ? null : n }, 'Rotate marker'); });
    root.appendChild(section('fields', 'Marker', [fieldRow('Label', lab), fieldRow('Rotation', rot)], true));
    root.appendChild(h('div', { class: 'ins-actions' }, [
      dev ? h('button', { type: 'button', class: 'small', onclick: function () { store.select({ type: 'device', id: dev.id, device: dev.id }); } }, 'Device details') : null,
      ro() ? null : h('button', { type: 'button', class: 'small danger', onclick: function () {
        commit([{ op: 'merge', coll: 'floorplans', id: f.id, value: { markers: deepClone(markers.filter(function (m) { return m.device !== mk.device; })) } }], 'Remove marker');
        store.select(null);
      } }, 'Remove marker'),
    ]));
  }

  function renderBundle(b) {
    kind = 'bundle';
    root.appendChild(head('Bundle \u00b7 ' + (b.kind || 'link'), 'var(--accent)', b.tag || b.label || b.id, ((store.doc.cables || []).filter(function (c) { return c.bundle === b.id; }).length) + ' cables'));
    root.appendChild(section('fields', 'Bundle', [
      fieldRow('Kind', boundSelect('bundles', b.id, ['kind'], ['multicore', 'loom', 'snake', 'link'])),
      fieldRow('Tag', bound('bundles', b.id, ['tag'])),
      fieldRow('Type', bound('bundles', b.id, ['type'])),
      fieldRow('Length (m)', bound('bundles', b.id, ['length_m'], { inputmode: 'decimal', number: true })),
      fieldRow('Label', bound('bundles', b.id, ['label'])),
      fieldRow('Signal', bound('bundles', b.id, ['signal'])),
      fieldRow('Note', bound('bundles', b.id, ['note'], { multiline: true })),
    ], true));
  }

  function renderRoom(r) {
    kind = 'room';
    root.appendChild(head('Room', 'var(--accent)', r.name || r.id, r.code || '', { page: { view: 'rooms', id: r.id, room: r.id } }));
    root.appendChild(section('fields', 'Room', [
      fieldRow('Name', bound('rooms', r.id, ['name'])),
      fieldRow('Code', bound('rooms', r.id, ['code'], { parse: function (v) { return v.toUpperCase().replace(/[^A-Z0-9-]/g, '').slice(0, 8); } })),
      fieldRow('Kind', boundSelect('rooms', r.id, ['kind'], vocab.room_kinds || ['other'])),
      fieldRow('Venue', boundSelect('rooms', r.id, ['venue'], (store.doc.venues || []).map(function (v) { return [v.id, v.name || v.id]; }))),
      fieldRow('Order', bound('rooms', r.id, ['order'], { inputmode: 'numeric', number: true })),
      fieldRow('Notes', bound('rooms', r.id, ['notes'], { multiline: true })),
    ], true));
  }

  // `missing`: a selection whose entity is not in the document.
  function renderEmpty(missing) {
    kind = 'empty';
    const doc = store.doc;
    const room = store.room;
    const devs = (doc.devices || []).filter(function (d) { return room === '*' || (d.room || '') === room; });
    const what = missing ? (KIND_NAME[missing.type] || 'Item') + ' \u201c' + selToString(missing).replace(/^[a-z]+:/, '') + '\u201d not found.' : '';
    root.appendChild(h('div', { class: 'sheet-head' }, [h('h2', null, 'Details'), closeButton()]));
    root.appendChild(h('div', { class: 'ins-empty' }, [
      what ? h('p', { class: 'ins-missing' }, what) : null,
      h('p', null, 'Select a device, port or cable to see and edit its details.'),
      h('p', { class: 'muted' }, devs.length + ' devices in ' + (room === '*' ? 'all rooms' : 'this room') + '.'),
      ro() ? null : h('button', { type: 'button', onclick: function () {
        ctx.pickTemplate({}).then(function (t) {
          if (!t) return;
          import('./model-core.js').then(function (mc) {
            const r = mc.addDeviceFromTemplateOps(store.doc, t, { room: store.room === '*' ? ((store.doc.settings && store.doc.settings.default_room) || '') : store.room, vocab: vocab });
            commit(r.ops, 'Add ' + (t.name || t.model || t.id));
            store.select({ type: 'device', id: r.id, device: r.id });
          });
        });
      } }, 'Add gear from library\u2026'),
    ]));
  }

  // -------------------------------------------------- render

  // The first section still visible below the index, so a re-render (the channel overlay arriving,
  // a commit elsewhere) keeps that section where it was instead of keeping a raw pixel offset.
  function scrollAnchor() {
    if (!el.scrollTop) return null;
    const nav = root.querySelector('.ins-index');
    const top = nav ? nav.getBoundingClientRect().bottom : el.getBoundingClientRect().top;
    const secs = topSections();
    for (let i = 0; i < secs.length; i++) {
      const r = secs[i].getBoundingClientRect();
      if (r.bottom > top + 1) return { key: secs[i].getAttribute('data-section'), dy: r.top - top };
    }
    return null;
  }
  function restoreAnchor(a, scroll) {
    el.scrollTop = scroll;
    const d = a && sectionEl(a.key);
    if (!d) return;
    const nav = root.querySelector('.ins-index');
    const top = nav ? nav.getBoundingClientRect().bottom : el.getBoundingClientRect().top;
    el.scrollTop += d.getBoundingClientRect().top - top - a.dy;
  }

  function render() {
    flushTimers();
    const scroll = resetScroll ? 0 : el.scrollTop;
    const anchor = resetScroll ? null : scrollAnchor();
    resetScroll = false;
    echo = null;
    root.innerHTML = '';
    const sel = store.selection;
    const doc = store.doc;
    if (!sel) {
      renderEmpty();
    } else if (sel.type === 'device' || (sel.type === 'port' && !sel.port)) {
      const d = find(doc.devices, sel.device || sel.id);
      if (d) renderDevice(d); else renderEmpty(sel);
    } else if (sel.type === 'port') {
      const d = find(doc.devices, sel.device || sel.id);
      const p = d ? devicePorts(d).filter(function (x) { return x.id === sel.port; })[0] : null;
      if (d && p) renderPort(d, p); else if (d) renderDevice(d); else renderEmpty(sel);
    } else if (sel.type === 'channel') {
      const d = find(doc.devices, sel.device || sel.id);
      const eff = d ? effectiveChannels(d, store.overlay) : null;
      const ch = eff ? eff.channels.filter(function (x) { return x.id === sel.channel; })[0] : null;
      if (d && ch) renderChannel(d, ch, eff); else if (d) renderDevice(d); else renderEmpty(sel);
    } else if (sel.type === 'cable') {
      const c = find(doc.cables, sel.id);
      if (c) renderCable(c); else renderEmpty(sel);
    } else if (sel.type === 'rack') {
      const r = find(doc.racks, sel.id);
      if (r) renderRack(r); else renderEmpty(sel);
    } else if (sel.type === 'floorplan') {
      const f = find(doc.floorplans, sel.id);
      if (f) renderFloorplan(f); else renderEmpty(sel);
    } else if (sel.type === 'marker') {
      renderMarker(sel);
    } else if (sel.type === 'bundle') {
      const b = find(doc.bundles, sel.id);
      if (b) renderBundle(b); else renderEmpty(sel);
    } else if (sel.type === 'room') {
      const r = find(doc.rooms, sel.id);
      if (r) renderRoom(r); else renderEmpty(sel);
    } else {
      renderEmpty();
    }
    buildIndex();
    restoreAnchor(anchor, scroll);
  }

  function selRefs() {
    const sel = store.selection;
    if (!sel) return [];
    const map = { device: 'devices', port: 'devices', channel: 'devices', cable: 'cables', rack: 'racks', floorplan: 'floorplans', marker: 'floorplans', bundle: 'bundles', room: 'rooms' };
    const coll = map[sel.type];
    if (!coll) return [];
    const id = sel.type === 'marker' ? sel.floorplan : (sel.type === 'port' || sel.type === 'channel' ? (sel.device || sel.id) : sel.id);
    const refs = [coll + '/' + id];
    if (sel.type === 'port' || sel.type === 'device') refs.push('cables/');
    return refs;
  }

  let lastSelKey = '';
  function onSelection() {
    const sel = store.selection;
    // canonical, so re-selecting the same entity in another shape ({type,id} vs {type,id,device}) keeps the scroll
    const key = selToString(sel);
    if (key === lastSelKey) return;
    lastSelKey = key;
    resetScroll = true;
    render();
  }
  function onDoc(e) {
    const d = e.detail || {};
    if (selfCommit && d.source === 'local') return;
    if (d.source === 'load' || d.source === 'history' || d.source === 'pending') { render(); return; }
    const refs = selRefs();
    if (!refs.length) { if (!store.selection) render(); return; }
    const touched = d.touched || [];
    const hit = touched.some(function (t) { return refs.some(function (r) { return r.charAt(r.length - 1) === '/' ? t.indexOf(r) === 0 : t === r; }); });
    if (!hit) return;
    // do not yank the field the user is typing in (the drawer host itself takes focus on open)
    const ae = document.activeElement;
    if (ae && ae !== el && el.contains(ae) && d.source === 'local') return;
    render();
  }
  function onMode() { render(); }
  function onOverlay() {
    const sel = store.selection;
    if (sel && (sel.type === 'device' || sel.type === 'channel') && !(el.contains(document.activeElement) && document.activeElement.tagName === 'INPUT')) render();
  }
  store.addEventListener('selection', onSelection);
  store.addEventListener('doc', onDoc);
  store.addEventListener('mode', onMode);
  store.addEventListener('overlay', onOverlay);
  const offRoute = typeof ctx.subscribe === 'function' ? ctx.subscribe('route', refreshIndex) : null;
  lastSelKey = selToString(store.selection);
  render();
  return {
    destroy: function () {
      flushTimers();
      store.removeEventListener('selection', onSelection);
      store.removeEventListener('doc', onDoc);
      store.removeEventListener('mode', onMode);
      store.removeEventListener('overlay', onOverlay);
      if (typeof offRoute === 'function') offRoute();
      if (traceDrawer) traceDrawer.close();
      el.innerHTML = '';
    },
    focus: function (sel) { if (sel) store.select(sel); },
    render: render,
    focusSection: function (key) { return focusSection(key); },
    sections: function () { return topSections().map(function (d) { return d.getAttribute('data-section'); }); },
  };
}
