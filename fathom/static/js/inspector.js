// Entity inspector / editor (§6.8): device, port, cable, rack, floor plan,
// marker, bundle, room. Field changes become ops through ctx.commit; text
// edits debounce 400 ms into one op per field burst.

import {
  devicePorts, portLabel, deviceTitle, disciplineOf, mediumInfo, setPortsOps, deleteDeviceOps, duplicateDeviceOps,
  connectOps, disconnectOps, repatchOps, expandPortGroups, newId, slug, formatLength, parseLength, deepClone,
  normalizeMac,
} from './model-core.js';
import { duplicateHints, openMergeDialog } from './merge-ui.js';
import {
  GROUPS, BUS_KINDS, effectiveChannels, groupChannels, channelMap, channelIndex, channelLabel, channelTitle, channelSummary, filterChannels,
  endpointText as linkEndpointText, routePeer, channelRef, setInputPatch, toggleSend, toggleMembership, addOutput, removeLink, updateChannel, nextChannel,
} from './console-core.js';
import { openTraceDrawer } from './trace-ui.js';

const DEBOUNCE = 400;
const CHANNEL_COLORS = ['Off', 'Blue', 'Orange', 'Yellow', 'Purple', 'Cyan', 'Magenta', 'Red', 'Green', 'Pink', 'White'];
let uid = 0;

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
  let openSections = { identity: true, ports: true, endpoints: true, fields: true, console: true };
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

  function section(key, title, children, open) {
    const isOpen = openSections[key] !== undefined ? openSections[key] : !!open;
    const d = h('details', { class: 'ins-section', open: isOpen ? true : null, 'data-section': key }, [h('summary', null, title), h('div', { class: 'inner' }, children)]);
    d.addEventListener('toggle', function () { openSections[key] = d.open; });
    return d;
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

  function head(kindLabel, color, title, sub, extra) {
    return h('div', { class: 'ins-title' }, [
      h('div', { class: 'row' }, [h('span', { class: 'kind', style: { color: color || 'var(--muted)' } }, kindLabel), h('span', { class: 'grow' }), extra || null,
        h('button', { type: 'button', class: 'icon ghost', 'aria-label': 'Close inspector', onclick: function () { ctx.closeInspector(); store.select(null); } }, '\u00d7')]),
      h('h3', null, title),
      sub ? h('div', { class: 'sub' }, sub) : null,
    ]);
  }

  // -------------------------------------------------- device

  function renderDevice(d) {
    const disc = disciplineOf(d, vocab);
    const dcol = vocab.disciplines && vocab.disciplines[disc] ? vocab.disciplines[disc].color : '#9aa3b5';
    const kinds = vocab.kinds || {};
    const proj = encodeURIComponent(ctx.project || '');
    const devUrl = (ctx.appRoot || '') + 'p/' + proj + '/d/' + encodeURIComponent(d.id);
    const problems = problemsFor(d);
    const nOpen = problems.filter(function (r) { return (r.status || 'open') === 'open'; }).length;
    root.appendChild(head(((vocab.disciplines && vocab.disciplines[disc] && vocab.disciplines[disc].label) || disc) + ' \u00b7 ' + ((kinds[d.kind] && kinds[d.kind].label) || d.kind || 'device'), dcol, deviceTitle(d),
      [((d.manufacturer || '') + ' ' + (d.model || '')).trim() || d.sub || '', d.status && d.status !== 'installed' ? ' \u00b7 ' + d.status : ''].join(''),
      h('span', { class: 'row' }, [
        nOpen ? h('button', { type: 'button', class: 'badge-problem', 'data-badge': 'problems', title: nOpen + ' open problem report' + (nOpen > 1 ? 's' : ''), onclick: function () {
          const sec = root.querySelector('[data-section="problems"]'); if (sec) { sec.open = true; sec.scrollIntoView({ block: 'start', behavior: 'smooth' }); }
        } }, '\u26A0 ' + nOpen + ' open') : null,
        d.status === 'planned' ? h('span', { class: 'badge-planned' }, 'planned') : null,
      ])));
    const actions = h('div', { class: 'ins-actions' }, [
      h('button', { type: 'button', class: 'small', onclick: function () { ctx.navigate('patch', { sel: 'device:' + d.id }); } }, 'Show in patch view'),
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
    root.appendChild(section('inventory', 'Inventory', [
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
      function fill() {
        if (filled) return;
        filled = true;
        host.appendChild(duplicateHints(ctx, id, function (res) {
          if (res && res.survivor) store.select({ type: 'device', id: res.survivor, device: res.survivor });
        }));
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
    const tbody = h('tbody');
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
      const nameI = cell('name', h('input', { value: p.name || '', 'aria-label': 'Port name' }));
      const labelI = cell('label', h('input', { value: p.label || '', placeholder: '\u2014', 'aria-label': 'Port label' }));
      const dirS = cell('dir', h('select', { 'aria-label': 'Direction' }, ['in', 'out', 'io'].map(function (x) { return h('option', { value: x, selected: (p.dir || 'io') === x ? true : null }, x); })));
      const medS = h('select', { 'aria-label': 'Medium' });
      if (p.medium && !(vocab.media || {})[p.medium]) medS.appendChild(h('option', { value: p.medium }, p.medium));
      mediaOptions().forEach(function (m) { medS.appendChild(h('option', { value: m[0], selected: m[0] === p.medium ? true : null }, m[1])); });
      cell('medium', medS);
      const conI = cell('connector', h('input', { value: p.connector || '', list: connectorList(), 'aria-label': 'Connector', placeholder: '\u2014' }));
      const chI = cell('channels', h('input', { value: p.channels || '', class: 'num', inputmode: 'numeric', 'aria-label': 'Channels', placeholder: '1' }), function (v) { const n = parseInt(v, 10); return n > 1 ? n : null; });
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
      tbody.appendChild(h('tr', { 'data-port': p.id }, [
        h('td', null, h('span', { class: 'dot', style: { color: m.color }, title: m.label })),
        h('td', null, nameI), h('td', null, labelI), h('td', null, dirS), h('td', null, medS), h('td', null, conI), h('td', null, chI),
        h('td', { style: { whiteSpace: 'nowrap' } }, [n ? h('span', { class: 'muted', title: n + ' cable(s)' }, '\u25CF') : null, up, del]),
      ]));
    });
    out.push(h('div', { style: { overflowX: 'auto' } }, h('table', { class: 'ins-table' }, [
      h('thead', null, h('tr', null, ['', 'Name', 'Label', 'Dir', 'Medium', 'Connector', 'Ch', ''].map(function (t) { return h('th', { scope: 'col' }, t); }))), tbody,
    ])));
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
      out.push(h('button', { type: 'button', class: 'small', onclick: function () { ctx.navigate('racks', { sel: 'rack:' + rk.id }); } }, 'Show in rack'));
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
    const cctx = channelCtx(d, eff);
    const idx = channelIndex(eff.links);
    const me = idx[ch.id] || { inputs: [], sends: [], feeds: [], outputs: [], direct: [], insertSend: [], insertReturn: [], dca: [], mute: [], members: [] };
    const editable = !ro() && eff.source === 'device';
    const kindLabel = { input: 'Input channel', stereo_input: 'Stereo input', mix: 'Mix bus', aux: 'Aux bus', group: 'Group bus', matrix: 'Matrix', stereo: 'Stereo bus', mono: 'Mono bus', dca: 'DCA', mute_group: 'Mute group', rack: 'Rack' }[ch.kind] || ch.kind;
    const back = h('button', { type: 'button', class: 'small ghost', 'aria-label': 'Back to ' + d.name, onclick: function () { store.select({ type: 'device', id: d.id, device: d.id }); } }, '\u2190 ' + (d.name || d.id));
    root.appendChild(head(kindLabel, groupColor(ch), channelTitle(ch), [d.name || d.id, ch.source && ch.source !== 'user' ? ' \u00b7 from ' + ch.source + ' import' : ''].join(''), back));
    root.appendChild(h('div', { class: 'ins-actions' }, [
      ctx.api ? h('button', { type: 'button', class: 'small primary', 'data-action': 'trace', onclick: function () { openTrace(channelRef(d.id, ch), channelTitle(ch), d.name || d.id, d); } }, 'Trace path') : null,
      h('button', { type: 'button', class: 'small', onclick: function () { ctx.navigate('patch', { sel: 'device:' + d.id }); } }, 'Show console in patch view'),
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
      actions: [{ label: 'Open in patch view', onclick: function (st) { st.close(); ctx.navigate('patch', { sel: 'device:' + (d ? d.id : ref.split(':')[0]) }); } }],
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
    const m = mediumInfo(p.medium, vocab);
    root.appendChild(head('Port \u00b7 ' + (p.dir || 'io'), m.color, (d.name || d.id) + ' \u00b7 ' + portLabel(p), (p.name || '') + (p.group ? ' \u00b7 ' + p.group : '') + ' \u00b7 ' + (m.label || p.medium)));
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
    const cables = store.index.cablesByPort[d.id + ':' + p.id] || [];
    const list = h('div');
    cables.forEach(function (c) {
      const mine = c.from.device === d.id && c.from.port === p.id ? 'from' : 'to';
      const other = mine === 'from' ? c.to : c.from;
      const od = find(store.doc.devices, other.device);
      const op = od && other.port ? devicePorts(od).filter(function (x) { return x.id === other.port; })[0] : null;
      list.appendChild(h('div', { class: 'row', style: { margin: '4px 0' } }, [
        h('span', null, (mine === 'from' ? '\u2192 ' : '\u2190 ') + (od ? od.name : other.device) + (op ? ' \u00b7 ' + portLabel(op) : '')),
        c.tag ? h('span', { class: 'chip' }, c.tag) : null,
        h('span', { class: 'grow' }),
        h('button', { type: 'button', class: 'small', onclick: function () { store.select({ type: 'cable', id: c.id }); } }, 'Cable'),
        ro() ? null : h('button', { type: 'button', class: 'small danger', 'aria-label': 'Disconnect', onclick: function () { commit(disconnectOps(store.doc, c.id), 'Disconnect ' + portLabel(p)); render(); } }, '\u00d7'),
      ]));
    });
    if (!cables.length) list.appendChild(h('div', { class: 'muted' }, 'Not patched.'));
    if (!ro()) list.appendChild(h('button', { type: 'button', class: 'small', onclick: function () {
      ctx.pickPort({ compatibleWith: { device: d.id, port: p.id }, room: store.room }).then(function (t) {
        if (!t) return;
        const here = { device: d.id, port: p.id };
        const ops = p.dir === 'in' ? connectOps(store.doc, t, here, {}, vocab) : connectOps(store.doc, here, t, {}, vocab);
        commit(ops, 'Connect ' + (d.name || d.id) + ' ' + portLabel(p));
        render();
      });
    } }, 'Patch\u2026'));
    root.appendChild(section('cables', 'Connections (' + cables.length + ')', [list], true));
    root.appendChild(h('div', { class: 'ins-actions' }, [
      h('button', { type: 'button', class: 'small', onclick: function () { store.select({ type: 'device', id: d.id, device: d.id }); } }, 'Device details'),
      ctx.api ? h('button', { type: 'button', class: 'small', 'data-action': 'trace', onclick: function () { openTrace(d.id + ':' + p.id, (d.name || d.id) + ' \u00b7 ' + portLabel(p), p.channels > 1 ? p.channels + ' channels' : (m.label || p.medium || ''), d); } }, 'Trace path') : null,
    ]));
  }

  // -------------------------------------------------- cable

  function endpointText(e) {
    const dd = find(store.doc.devices, e && e.device);
    const pp = dd && e.port ? devicePorts(dd).filter(function (x) { return x.id === e.port; })[0] : null;
    return (dd ? dd.name : (e && e.device) || '?') + (pp ? ' \u00b7 ' + portLabel(pp) : (e && e.port ? ' \u00b7 ' + e.port : ' (device)'));
  }

  function renderCable(c) {
    const m = mediumInfo(c.medium, vocab);
    const units = (store.doc.settings && store.doc.settings.units) || 'metric';
    root.appendChild(head('Cable \u00b7 ' + (m.label || c.medium), m.color, c.tag || c.label || c.id, endpointText(c.from) + ' \u2192 ' + endpointText(c.to)));
    function endRow(end) {
      const e = c[end];
      return h('div', { class: 'row', style: { margin: '4px 0' } }, [
        h('span', { class: 'muted', style: { width: '40px' } }, end === 'from' ? 'From' : 'To'),
        h('span', { class: 'grow' }, endpointText(e)),
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
      fieldRow('Medium', boundSelect('cables', c.id, ['medium'], mediaOptions(), { label: 'Set medium' })),
      fieldRow('Tag', bound('cables', c.id, ['tag'], { placeholder: 'e.g. A-012', label: 'Set tag' })),
      fieldRow('Type', bound('cables', c.id, ['type'], { placeholder: 'e.g. XLR3 M-F', list: connectorList() })),
      fieldRow('Length', lenI),
      fieldRow('Color', bound('cables', c.id, ['color'])),
      fieldRow('Channels', bound('cables', c.id, ['channels'], { inputmode: 'numeric', number: true })),
      fieldRow('Status', boundSelect('cables', c.id, ['status'], (vocab.statuses || ['installed', 'planned', 'spare', 'retired']), { defaultValue: 'installed', default: 'installed' })),
      fieldRow('Bundle', boundSelect('cables', c.id, ['bundle'], (store.doc.bundles || []).map(function (b) { return [b.id, b.tag || b.label || b.id]; }), { empty: 'None' })),
      fieldRow('Signal', bound('cables', c.id, ['signal'])),
      fieldRow('Map label', bound('cables', c.id, ['label'])),
      fieldRow('Two-way', boundCheck('cables', c.id, ['bidirectional'])),
      fieldRow('Note', bound('cables', c.id, ['note'], { multiline: true })),
    ], true));
    if (!ro()) root.appendChild(h('div', { class: 'ins-actions' }, [h('button', { type: 'button', class: 'small danger', onclick: function () { commit(disconnectOps(store.doc, c.id), 'Delete cable ' + (c.tag || c.id)); store.select(null); } }, 'Delete cable')]));
  }

  // -------------------------------------------------- other entities

  function renderRack(r) {
    root.appendChild(head('Rack', 'var(--accent)', r.name || r.id, (r.units || '?') + 'U'));
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
    if (!f || !mk) { renderEmpty(); return; }
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
    root.appendChild(head('Room', 'var(--accent)', r.name || r.id, r.code || ''));
    root.appendChild(section('fields', 'Room', [
      fieldRow('Name', bound('rooms', r.id, ['name'])),
      fieldRow('Code', bound('rooms', r.id, ['code'], { parse: function (v) { return v.toUpperCase().replace(/[^A-Z0-9-]/g, '').slice(0, 8); } })),
      fieldRow('Kind', boundSelect('rooms', r.id, ['kind'], vocab.room_kinds || ['other'])),
      fieldRow('Venue', boundSelect('rooms', r.id, ['venue'], (store.doc.venues || []).map(function (v) { return [v.id, v.name || v.id]; }))),
      fieldRow('Order', bound('rooms', r.id, ['order'], { inputmode: 'numeric', number: true })),
      fieldRow('Notes', bound('rooms', r.id, ['notes'], { multiline: true })),
    ], true));
  }

  function renderEmpty() {
    const doc = store.doc;
    const room = store.room;
    const devs = (doc.devices || []).filter(function (d) { return room === '*' || (d.room || '') === room; });
    root.appendChild(h('div', { class: 'sheet-head' }, [h('h2', null, 'Details'), h('button', { type: 'button', class: 'icon ghost', 'aria-label': 'Close inspector', onclick: function () { ctx.closeInspector(); } }, '\u00d7')]));
    root.appendChild(h('div', { class: 'ins-empty' }, [
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

  function render() {
    flushTimers();
    const scroll = el.scrollTop;
    root.innerHTML = '';
    const sel = store.selection;
    const doc = store.doc;
    if (!sel) { renderEmpty(); return; }
    if (sel.type === 'device' || (sel.type === 'port' && !sel.port)) {
      const d = find(doc.devices, sel.device || sel.id);
      if (d) renderDevice(d); else renderEmpty();
    } else if (sel.type === 'port') {
      const d = find(doc.devices, sel.device || sel.id);
      const p = d ? devicePorts(d).filter(function (x) { return x.id === sel.port; })[0] : null;
      if (d && p) renderPort(d, p); else if (d) renderDevice(d); else renderEmpty();
    } else if (sel.type === 'channel') {
      const d = find(doc.devices, sel.device || sel.id);
      const eff = d ? effectiveChannels(d, store.overlay) : null;
      const ch = eff ? eff.channels.filter(function (x) { return x.id === sel.channel; })[0] : null;
      if (d && ch) renderChannel(d, ch, eff); else if (d) renderDevice(d); else renderEmpty();
    } else if (sel.type === 'cable') {
      const c = find(doc.cables, sel.id);
      if (c) renderCable(c); else renderEmpty();
    } else if (sel.type === 'rack') {
      const r = find(doc.racks, sel.id);
      if (r) renderRack(r); else renderEmpty();
    } else if (sel.type === 'floorplan') {
      const f = find(doc.floorplans, sel.id);
      if (f) renderFloorplan(f); else renderEmpty();
    } else if (sel.type === 'marker') {
      renderMarker(sel);
    } else if (sel.type === 'bundle') {
      const b = find(doc.bundles, sel.id);
      if (b) renderBundle(b); else renderEmpty();
    } else if (sel.type === 'room') {
      const r = find(doc.rooms, sel.id);
      if (r) renderRoom(r); else renderEmpty();
    } else {
      renderEmpty();
    }
    el.scrollTop = scroll;
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
    const key = sel ? JSON.stringify(sel) : '';
    if (key === lastSelKey) return;
    lastSelKey = key;
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
    // do not yank the field the user is typing in
    if (el.contains(document.activeElement) && d.source === 'local') return;
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
  lastSelKey = store.selection ? JSON.stringify(store.selection) : '';
  render();
  return {
    destroy: function () {
      flushTimers();
      store.removeEventListener('selection', onSelection);
      store.removeEventListener('doc', onDoc);
      store.removeEventListener('mode', onMode);
      store.removeEventListener('overlay', onOverlay);
      if (traceDrawer) traceDrawer.close();
      el.innerHTML = '';
    },
    focus: function (sel) { if (sel) store.select(sel); },
    render: render,
  };
}
