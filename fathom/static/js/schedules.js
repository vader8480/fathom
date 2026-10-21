// Schedules view: cables (tag preview + assign), IP, DMX, BOM, patch, racks,
// labels. Rows come from GET …/schedules/<kind> when ctx.api exists; in harness
// mode (ctx.api === null) minimal rows are computed locally from the doc.
// mount(el, ctx) (§6.4, §6.7).
import {rackDevices, findRack, ruLabel} from './rack-core.js';

const FT = 0.3048;

export const KINDS = [
  {key: 'cables', label: 'Cables'},
  {key: 'ip', label: 'IP'},
  {key: 'dmx', label: 'DMX'},
  {key: 'bom', label: 'BOM'},
  {key: 'patch', label: 'Patch'},
  {key: 'racks', label: 'Racks'},
  {key: 'labels', label: 'Labels'},
];

// §5.8.2 columns (JSON key / CSV label).
export const COLUMNS = {
  patch: [['room', 'Room'], ['device', 'Device'], ['section', 'Section'], ['dir', 'Dir'], ['port', 'Port'], ['label', 'Label'], ['peer_device', 'Peer device'], ['peer_port', 'Peer port'], ['cable_tag', 'Cable'], ['medium', 'Medium'], ['source', 'Source']],
  cables: [['tag', 'Tag'], ['from_room', 'From room'], ['from_device', 'From device'], ['from_port', 'From port'], ['to_room', 'To room'], ['to_device', 'To device'], ['to_port', 'To port'], ['medium', 'Medium'], ['type', 'Type'], ['length', 'Length'], ['length_unit', 'Unit'], ['color', 'Color'], ['channels', 'Channels'], ['signal', 'Signal'], ['status', 'Status'], ['bundle', 'Bundle'], ['note', 'Note'], ['id', 'Id']],
  ip: [['room', 'Room'], ['device', 'Device'], ['interface', 'Interface'], ['role', 'Role'], ['ip', 'IP'], ['prefix', 'Prefix'], ['gateway', 'Gateway'], ['vlan', 'VLAN'], ['network', 'Network'], ['mac', 'MAC'], ['hostname', 'Hostname'], ['switch', 'Switch'], ['switch_port', 'Switch port'], ['protocol', 'Protocol'], ['dhcp', 'DHCP'], ['source', 'Source'], ['note', 'Note']],
  dmx: [['universe', 'Universe'], ['address', 'Address'], ['end', 'End'], ['footprint', 'Footprint'], ['device', 'Device'], ['room', 'Room'], ['mode', 'Mode'], ['channel', 'Console channel'], ['protocol', 'Protocol'], ['sacn_group', 'sACN group'], ['artnet', 'Art-Net (net:sub:uni)'], ['source', 'Source']],
  bom: [['category', 'Category'], ['manufacturer', 'Manufacturer'], ['model', 'Model'], ['template', 'Template'], ['qty', 'Qty'], ['unit_cost', 'Unit cost'], ['extended', 'Extended'], ['currency', 'Currency'], ['planned', 'Planned'], ['installed', 'Installed'], ['spare', 'Spare'], ['retired', 'Retired'], ['length_total_m', 'Total length (m)']],
  racks: [['rack', 'Rack'], ['room', 'Room'], ['units', 'Units'], ['face', 'Face'], ['u', 'U'], ['height', 'Height'], ['side', 'Side'], ['device', 'Device'], ['model', 'Model']],
};

// Doc-backed editable columns per kind (§6.7).
const EDITABLE = {
  cables: ['tag', 'type', 'length', 'color', 'note', 'status'],
  ip: ['ip', 'vlan', 'mac', 'hostname', 'switch', 'switch_port'],
  dmx: ['universe', 'address', 'footprint', 'mode', 'channel'],
};
const NUMERIC_EDIT = {length: 'decimal', vlan: 'numeric', universe: 'numeric', address: 'numeric', footprint: 'numeric'};
const STATUSES = ['installed', 'planned', 'spare', 'retired'];

// ------------------------------------------------------------ pure helpers

function list(v) { return Array.isArray(v) ? v : []; }

function slug(text) {
  const s = String(text == null ? '' : text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return s || 'item';
}

function byId(arr) {
  const m = {};
  list(arr).forEach(function (e) { if (e && e.id != null) m[e.id] = e; });
  return m;
}

function portOf(dev, pid) {
  const ps = list(dev && dev.ports);
  for (let i = 0; i < ps.length; i++) if (ps[i].id === pid) return ps[i];
  return null;
}

function portName(dev, pid) {
  const p = portOf(dev, pid);
  return p ? (p.label || p.name || p.id) : (pid || '');
}

function mediumInfo(medium, vocab) {
  const m = vocab && vocab.media;
  return (m && (m[medium] || m.other)) || {discipline: 'other', short: 'OTH', label: medium || ''};
}

function deviceDiscipline(dev, vocab) {
  if (!dev) return 'other';
  if (dev.discipline) return dev.discipline;
  const k = vocab && vocab.kinds && vocab.kinds[dev.kind];
  return (k && k.discipline) || 'other';
}

function stateOk(status, state) {
  const s = status || 'installed';
  if (state === 'everything') return true;
  if (s === 'retired') return false;
  if (state === 'as_built') return s === 'installed';
  if (state === 'planned') return s === 'installed' || s === 'planned';
  return true;
}

function deviceCode(dev) {
  if (!dev) return 'X';
  return dev.code || slug(dev.name || dev.id).replace(/-/g, '').toUpperCase().slice(0, 8);
}

function roomCode(room) {
  if (!room) return 'X';
  return room.code || slug(room.id || room.name).replace(/-/g, '').toUpperCase().slice(0, 4);
}

function roomName(rooms, id) {
  if (!id) return 'Shared';
  return rooms[id] ? rooms[id].name : id;
}

export function csvString(columns, rows) {
  function q(v) {
    const s = v == null ? '' : String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  const out = [columns.map(function (c) { return q(c.label); }).join(',')];
  rows.forEach(function (r) { out.push(columns.map(function (c) { return q(r[c.key]); }).join(',')); });
  return out.join('\r\n') + '\r\n';
}

export function normalizeMac(text) {
  const hex = String(text || '').replace(/[^0-9a-fA-F]/g, '').toLowerCase();
  if (hex.length !== 12 || !/^[0-9a-f:.\- ]+$/i.test(String(text).trim())) return null;
  return hex.match(/../g).join(':');
}

// ---------------------------------------------------- §4.8 local tag preview
// Harness-mode stand-in for the server tag preview (cables.assign_tags_ops).

function renderTagWith(pattern, cable, doc, vocab, nText) {
  const devs = byId(doc.devices);
  const rooms = byId(doc.rooms);
  const info = mediumInfo(cable.medium, vocab);
  const disc = info.discipline || 'other';
  const dinfo = vocab && vocab.disciplines && vocab.disciplines[disc];
  const from = devs[cable.from && cable.from.device];
  const to = devs[cable.to && cable.to.device];
  return String(pattern).replace(/\{(\w+)(?::(\d+))?\}/g, function (all, name, fmt) {
    switch (name) {
      case 'D': return (dinfo && dinfo.letter) || 'X';
      case 'disc': return disc;
      case 'DISC': return disc.toUpperCase();
      case 'M': return String(info.short || 'OTH').toUpperCase();
      case 'room': return roomCode(from && rooms[from.room]);
      case 'from': return deviceCode(from);
      case 'to': return deviceCode(to);
      case 'n': return nText(fmt ? parseInt(fmt, 10) : 0);
      default: return all;
    }
  });
}

export function renderTag(pattern, cable, doc, vocab, n) {
  return renderTagWith(pattern, cable, doc, vocab, function (w) {
    let s = String(n);
    while (s.length < w) s = '0' + s;
    return s;
  });
}

function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

export function assignTagsLocal(doc, scope, pattern, vocab) {
  const pat = pattern || (doc.settings && doc.settings.cable_tag_pattern) || '{D}-{n:03}';
  const PH = '\u0001N\u0001';
  const existing = scope === 'all' ? [] : list(doc.cables).map(function (c) { return c.tag; }).filter(Boolean);
  const assigned = [];
  const max = {};
  const ops = [];
  list(doc.cables).forEach(function (c) {
    if (c.auto) return;
    if (scope !== 'all' && c.tag) return;
    const key = renderTagWith(pat, c, doc, vocab, function () { return PH; });
    if (!(key in max)) {
      const re = new RegExp('^' + escapeRe(key).split(escapeRe(PH)).join('(\\d+)') + '$');
      let m = 0;
      existing.concat(assigned).forEach(function (t) {
        const mm = re.exec(t);
        if (mm) for (let i = 1; i < mm.length; i++) m = Math.max(m, parseInt(mm[i], 10));
      });
      max[key] = m;
    }
    max[key] += 1;
    const tag = renderTag(pat, c, doc, vocab, max[key]);
    assigned.push(tag);
    if (tag !== c.tag) ops.push({op: 'merge', coll: 'cables', id: c.id, value: {tag: tag}});
  });
  return ops;
}

// ------------------------------------------------------ local schedule rows

function cols(kind) { return COLUMNS[kind].map(function (c) { return {key: c[0], label: c[1]}; }); }

function inRoom(dev, room) { return room === '*' || !room || (dev && (dev.room || '') === room); }

export function localSchedule(doc, kind, params, vocab, overlay) {
  const p = params || {};
  const room = p.room || '*';
  const state = p.state || 'all';
  const disc = p.discipline || '';
  const devs = byId(doc.devices);
  const rooms = byId(doc.rooms);
  const units = (doc.settings && doc.settings.units) || 'metric';
  const okDev = function (d) { return d && !d.auto && stateOk(d.status, state); };
  const rows = [];
  const problems = [];
  let totals = null;

  if (kind === 'cables') {
    list(doc.cables).forEach(function (c) {
      const a = devs[c.from && c.from.device];
      const b = devs[c.to && c.to.device];
      if (c.auto || !stateOk(c.status, state) || !okDev(a) || !okDev(b)) return;
      if (!(inRoom(a, room) || inRoom(b, room))) return;
      const cd = mediumInfo(c.medium, vocab).discipline || 'other';
      if (disc && cd !== disc) return;
      rows.push({
        id: c.id, tag: c.tag || '', from_room: roomName(rooms, a.room), from_device: a.name, from_device_id: a.id,
        from_port: c.from.port ? portName(a, c.from.port) : '', from_port_id: c.from.port || '',
        to_room: roomName(rooms, b.room), to_device: b.name, to_device_id: b.id,
        to_port: c.to.port ? portName(b, c.to.port) : '', to_port_id: c.to.port || '',
        medium: c.medium || '', type: c.type || '',
        length: c.length_m == null ? '' : (units === 'imperial' ? Math.round(c.length_m / FT * 10) / 10 : c.length_m),
        length_unit: c.length_m == null ? '' : (units === 'imperial' ? 'ft' : 'm'),
        color: c.color || '', channels: c.channels == null ? '' : c.channels, signal: c.signal || '', status: c.status || 'installed',
        bundle: c.bundle || '', note: c.note || '', discipline: cd,
      });
    });
    const seen = {};
    list(doc.cables).forEach(function (c) {
      if (!c.tag) return;
      if (seen[c.tag]) problems.push({level: 'warning', code: 'tag_duplicate', ref: 'cables/' + c.id, message: 'Tag ' + c.tag + ' is used by ' + seen[c.tag] + ' and ' + c.id});
      else seen[c.tag] = c.id;
    });
  } else if (kind === 'ip') {
    const nets = byId(doc.networks);
    const manual = {};
    list(doc.devices).forEach(function (d) {
      if (!okDev(d) || !inRoom(d, room)) return;
      list(d.interfaces).forEach(function (i) {
        manual[d.id + '|' + (i.role || 'primary')] = true;
        rows.push(ipRow(d, i, 'manual'));
      });
    });
    const ov = (overlay && overlay.interfaces) || {};
    Object.keys(ov).forEach(function (did) {
      const d = devs[did];
      if (d && (!okDev(d) || !inRoom(d, room))) return;
      list(ov[did]).forEach(function (i) {
        if (manual[did + '|' + (i.role || 'primary')]) return;
        rows.push(ipRow(d || {id: did, name: did}, i, i.source || 'import'));
      });
    });
    const seenIp = {};
    rows.forEach(function (r) {
      if (!r.ip) return;
      const k = (r.network_id || '') + '|' + r.ip;
      if (seenIp[k]) problems.push({level: 'warning', code: 'ip_duplicate', ref: 'devices/' + r.device_id, message: r.ip + ' is used by ' + seenIp[k] + ' and ' + r.device});
      else seenIp[k] = r.device;
    });
    function ipRow(d, i, source) {
      const net = nets[i.network];
      let prefix = i.prefix;
      if (prefix == null && net && net.subnet && net.subnet.indexOf('/') > 0) prefix = parseInt(net.subnet.split('/')[1], 10);
      const sw = devs[i.switch];
      return {
        room: roomName(rooms, d.room), device: d.name, device_id: d.id, interface: i.id || '', interface_id: i.id || '', role: i.role || 'primary',
        ip: i.ip || '', prefix: prefix == null ? '' : prefix, gateway: i.gateway || (net && net.gateway) || '', vlan: i.vlan == null ? (net && net.vlan != null ? net.vlan : '') : i.vlan,
        network: net ? net.name : (i.network || ''), network_id: i.network || '', mac: i.mac ? (normalizeMac(i.mac) || i.mac) : '', hostname: i.hostname || '',
        switch: sw ? sw.name : (i.switch || ''), switch_id: i.switch || '', switch_port: sw ? (portOf(sw, i.switch_port) ? portName(sw, i.switch_port) : (i.switch_port || '')) : (i.switch_port || ''),
        protocol: i.protocol || (net && net.protocol) || '', dhcp: i.dhcp ? 'yes' : '', source: source, note: i.note || '', discipline: deviceDiscipline(d, vocab),
      };
    }
  } else if (kind === 'dmx') {
    const ovd = (overlay && overlay.dmx) || {};
    const ids = {};
    list(doc.devices).forEach(function (d) {
      if (!okDev(d) || !inRoom(d, room)) return;
      if (d.dmx && d.dmx.universe != null && d.dmx.address != null) { ids[d.id] = true; rows.push(dmxRow(d, d.dmx, 'manual')); }
    });
    Object.keys(ovd).forEach(function (did) {
      if (ids[did]) return;
      const d = devs[did] || {id: did, name: did};
      if (devs[did] && (!okDev(d) || !inRoom(d, room))) return;
      rows.push(dmxRow(d, ovd[did], ovd[did].source || 'import'));
    });
    rows.sort(function (a, b) { return a.universe - b.universe || a.address - b.address; });
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (r.end > 512) problems.push({level: 'warning', code: 'dmx_overflow', ref: 'devices/' + r.device_id, message: r.device + ' ends at ' + r.end + ' (past 512) in universe ' + r.universe});
      for (let j = i + 1; j < rows.length && rows[j].universe === r.universe && rows[j].address <= r.end; j++) {
        problems.push({level: 'warning', code: 'dmx_overlap', ref: 'devices/' + r.device_id, message: r.device + ' and ' + rows[j].device + ' overlap in universe ' + r.universe});
      }
    }
    function dmxRow(d, x, source) {
      const u = parseInt(x.universe, 10) || 1;
      const a = parseInt(x.address, 10) || 1;
      const fp = parseInt(x.footprint, 10) || 1;
      const pa = u - 1;
      return {
        universe: u, address: a, end: a + fp - 1, footprint: x.footprint == null ? '' : fp, device: d.name, device_id: d.id, room: roomName(rooms, d.room),
        mode: x.mode || '', channel: x.channel == null ? '' : String(x.channel), protocol: x.protocol || 'dmx',
        sacn_group: '239.255.' + (u >> 8) + '.' + (u & 255), artnet: (pa >> 8) + ':' + ((pa >> 4) & 15) + ':' + (pa & 15), source: source,
        discipline: deviceDiscipline(d, vocab),
      };
    }
  } else if (kind === 'bom') {
    const tpls = byId(doc.templates);
    const groups = {};
    const order = [];
    const cur = (doc.settings && doc.settings.currency) || 'USD';
    totals = {};
    list(doc.devices).forEach(function (d) {
      if (d.auto || !inRoom(d, room)) return;
      if ((d.status || 'installed') !== 'spare' && !stateOk(d.status, state)) return;
      const dd = deviceDiscipline(d, vocab);
      if (disc && dd !== disc) return;
      const key = d.template ? 't:' + d.template : (d.manufacturer || d.model ? 'm:' + (d.manufacturer || '') + '|' + (d.model || '') : 'k:' + d.kind);
      if (!groups[key]) {
        groups[key] = {category: dd, manufacturer: d.manufacturer || '', model: d.model || (vocab && vocab.kinds && vocab.kinds[d.kind] ? vocab.kinds[d.kind].label : d.kind),
          template: d.template || '', qty: 0, unit_cost: null, extended: 0, currency: '', planned: 0, installed: 0, spare: 0, retired: 0, length_total_m: '', _units: {}};
        order.push(key);
      }
      const g = groups[key];
      const n = parseInt(d.count, 10) > 0 ? parseInt(d.count, 10) : 1;
      const t = tpls[d.template];
      const unit = d.inventory && d.inventory.cost != null ? Number(d.inventory.cost) : (t && t.cost != null ? Number(t.cost) : 0);
      const c = (d.inventory && d.inventory.currency) || (t && t.currency) || cur;
      g.qty += n;
      g.extended += unit * n;
      g._units[unit] = true;
      g.currency = c;
      g[d.status || 'installed'] = (g[d.status || 'installed'] || 0) + n;
      totals[c] = (totals[c] || 0) + unit * n;
    });
    order.forEach(function (k) {
      const g = groups[k];
      const us = Object.keys(g._units);
      g.unit_cost = us.length === 1 ? Number(us[0]) : null;
      g.extended = Math.round(g.extended * 100) / 100;
      delete g._units;
      rows.push(g);
    });
    const cg = {};
    const corder = [];
    list(doc.cables).forEach(function (c) {
      const a = devs[c.from && c.from.device];
      const b = devs[c.to && c.to.device];
      if (c.auto || !stateOk(c.status, state) || !okDev(a) || !okDev(b) || !(inRoom(a, room) || inRoom(b, room))) return;
      if (disc && (mediumInfo(c.medium, vocab).discipline || 'other') !== disc) return;
      const k = (c.medium || '') + '|' + (c.type || '');
      if (!cg[k]) {
        cg[k] = {category: 'cable', manufacturer: '', model: (c.medium || '') + (c.type ? ' \u00b7 ' + c.type : ''), template: '', qty: 0, unit_cost: null, extended: 0, currency: cur,
          planned: 0, installed: 0, spare: 0, retired: 0, length_total_m: 0};
        corder.push(k);
      }
      cg[k].qty += 1;
      cg[k][c.status || 'installed'] += 1;
      cg[k].length_total_m = Math.round((cg[k].length_total_m + (Number(c.length_m) || 0)) * 100) / 100;
    });
    corder.forEach(function (k) { rows.push(cg[k]); });
  } else if (kind === 'patch') {
    const byPort = {};
    list(doc.cables).forEach(function (c) {
      if (c.auto) return;
      [['from', 'to', 'out'], ['to', 'from', 'in']].forEach(function (e) {
        const k = c[e[0]].device + ':' + (c[e[0]].port || '');
        (byPort[k] = byPort[k] || []).push({cable: c, peer: c[e[1]]});
      });
    });
    list(doc.devices).forEach(function (d) {
      if (!okDev(d) || !inRoom(d, room)) return;
      if (disc && deviceDiscipline(d, vocab) !== disc) return;
      list(d.ports).forEach(function (p) {
        const links = byPort[d.id + ':' + p.id] || [null];
        links.forEach(function (l) {
          const peer = l ? devs[l.peer.device] : null;
          rows.push({
            room: roomName(rooms, d.room), device: d.name, device_id: d.id, section: p.group || ((mediumInfo(p.medium, vocab).short || '') + ' ' + ({in: 'In', out: 'Out', io: 'I/O'}[p.dir] || '')),
            dir: p.dir, port: p.label || p.name || p.id, port_id: p.id, label: p.label || '', peer_device: peer ? peer.name : '', peer_device_id: peer ? peer.id : '',
            peer_port: peer && l.peer.port ? portName(peer, l.peer.port) : '', cable_tag: l ? (l.cable.tag || '') : '', cable_id: l ? l.cable.id : '',
            medium: p.medium || '', source: l ? 'cable' : '', discipline: mediumInfo(p.medium, vocab).discipline || 'other',
          });
        });
      });
    });
  } else if (kind === 'racks') {
    list(doc.racks).forEach(function (rk) {
      if (room !== '*' && room && (rk.room || '') !== room) return;
      rackDevices(doc, rk.id).sort(function (a, b) { return b.u - a.u; }).forEach(function (pl) {
        const d = devs[pl.device];
        rows.push({rack: rk.name, rack_id: rk.id, room: roomName(rooms, rk.room), units: rk.units, face: pl.face, u: ruLabel(findRack(doc, rk.id), pl.u), height: pl.height,
          side: pl.side, device: d ? d.name : pl.device, device_id: pl.device, model: d ? ((d.manufacturer || '') + ' ' + (d.model || '')).trim() : '', discipline: deviceDiscipline(d, vocab)});
      });
    });
  }
  return {kind: kind, columns: kind === 'labels' ? [] : cols(kind), rows: rows, problems: problems, totals: totals};
}

// Label preview rows (two labels per tagged cable, FR-CAB-04) for harness mode.
export function localLabels(doc, room) {
  const devs = byId(doc.devices);
  const out = [];
  list(doc.cables).forEach(function (c) {
    if (!c.tag || c.auto) return;
    const a = devs[c.from.device];
    const b = devs[c.to.device];
    if (!(inRoom(a, room) || inRoom(b, room))) return;
    const line = deviceCode(a) + ' ' + (c.from.port ? portName(a, c.from.port) : '') + ' \u2192 ' + deviceCode(b) + ' ' + (c.to.port ? portName(b, c.to.port) : '');
    out.push({tag: c.tag, line: line.toUpperCase(), end: 'A'});
    out.push({tag: c.tag, line: line.toUpperCase(), end: 'B'});
  });
  return out;
}

// --------------------------------------------------------------- DOM view

function h(tag, attrs, children) {
  const n = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (v == null || v === false) return;
      if (k === 'text') n.textContent = v;
      else if (k === 'class') n.className = v;
      else if (k === 'style') n.setAttribute('style', v);
      else n.setAttribute(k, v === true ? '' : v);
    });
  }
  (children || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
  return n;
}

export function mount(el, ctx) {
  const store = ctx.store;
  const vocab = ctx.vocab || store.vocab || {};
  const S = {kind: 'cables', room: 'current', state: 'all', disc: '', text: '', sort: null, data: {}, loading: false, preview: null, csvUrl: '', reqId: 0};
  const listeners = [];
  function on(target, type, fn, opts) {
    target.addEventListener(type, fn, opts);
    listeners.push([target, type, fn, opts]);
  }

  el.innerHTML = '';
  const root = h('div', {class: 'sch-root'});
  const tabs = h('div', {class: 'sch-tabs', role: 'tablist', 'aria-label': 'Schedules'});
  KINDS.forEach(function (k) {
    tabs.appendChild(h('button', {type: 'button', role: 'tab', id: 'sch-tab-' + k.key, 'data-kind': k.key, 'aria-controls': 'sch-panel', 'aria-selected': 'false', tabindex: '-1', text: k.label}));
  });
  const roomSel = h('select', {id: 'sch-room', 'aria-label': 'Room filter'}, [h('option', {value: 'current', text: 'Current room'}), h('option', {value: '*', text: 'All rooms'})]);
  const stateSel = h('select', {id: 'sch-state', 'aria-label': 'State filter'}, [
    h('option', {value: 'all', text: 'All (no retired)'}), h('option', {value: 'planned', text: 'Planned + installed'}),
    h('option', {value: 'as_built', text: 'As built'}), h('option', {value: 'everything', text: 'Everything'})]);
  const discSel = h('select', {id: 'sch-disc', 'aria-label': 'Discipline filter'}, [h('option', {value: '', text: 'All disciplines'})].concat(
    Object.keys(vocab.disciplines || {}).map(function (k) { return h('option', {value: k, text: vocab.disciplines[k].label || k}); })));
  const textIn = h('input', {id: 'sch-filter', type: 'search', placeholder: 'Filter rows', 'aria-label': 'Filter rows'});
  const btnTags = h('button', {id: 'sch-assign-tags', type: 'button', class: 'sch-btn', text: 'Assign tags\u2026'});
  const csv = h('a', {id: 'sch-csv', class: 'sch-btn', role: 'button', text: 'CSV'});
  const btnPrint = h('button', {id: 'sch-print', type: 'button', class: 'sch-btn', text: 'Print'});
  const count = h('span', {class: 'sch-count', role: 'status'});
  const toolbar = h('div', {class: 'sch-toolbar'}, [roomSel, stateSel, discSel, textIn, btnTags, csv, btnPrint, count]);
  const tagPanel = h('div', {class: 'sch-tagpanel', hidden: true, role: 'region', 'aria-label': 'Cable tag preview'});
  const problemsEl = h('ul', {class: 'sch-problems', 'aria-label': 'Schedule warnings'});
  const panel = h('div', {class: 'sch-panel', id: 'sch-panel', role: 'tabpanel'});
  root.appendChild(tabs);
  root.appendChild(toolbar);
  root.appendChild(tagPanel);
  root.appendChild(problemsEl);
  root.appendChild(panel);
  el.appendChild(root);

  function doc() { return store.doc; }
  function readOnly() { return !!store.readOnly; }
  function room() {
    if (S.room === '*') return '*';
    return store.room && store.room !== '*' ? store.room : '*';
  }
  function params() {
    const p = {room: room(), state: S.state};
    if (S.disc) p.discipline = S.disc;
    return p;
  }
  function units() { return (doc().settings && doc().settings.units) || 'metric'; }

  // ------------------------------------------------------------ loading
  function load() {
    const kind = S.kind;
    if (!ctx.api || kind === 'labels') {
      S.data[kind] = kind === 'labels' ? null : localSchedule(doc(), kind, params(), vocab, store.overlay);
      render();
      return;
    }
    const id = ++S.reqId;
    S.loading = true;
    render();
    Promise.resolve(ctx.api.schedule(ctx.project, kind, params())).then(function (res) {
      if (id !== S.reqId) return;
      S.loading = false;
      S.data[kind] = res || {columns: cols(kind), rows: []};
      render();
    }, function (err) {
      if (id !== S.reqId) return;
      S.loading = false;
      S.data[kind] = localSchedule(doc(), kind, params(), vocab, store.overlay);
      S.data[kind].error = (err && err.message) || 'Could not load the schedule; showing local rows.';
      render();
    });
  }

  let reloadTimer = null;
  function reloadSoon() {
    if (reloadTimer) clearTimeout(reloadTimer);
    reloadTimer = setTimeout(function () { reloadTimer = null; load(); }, ctx.api ? 300 : 0);
  }

  // ---------------------------------------------------------- rendering
  function render() {
    Array.prototype.forEach.call(tabs.children, function (b) {
      const sel = b.getAttribute('data-kind') === S.kind;
      b.setAttribute('aria-selected', sel ? 'true' : 'false');
      b.tabIndex = sel ? 0 : -1;
    });
    panel.setAttribute('aria-labelledby', 'sch-tab-' + S.kind);
    btnTags.hidden = S.kind !== 'cables';
    btnTags.disabled = readOnly();
    if (S.kind !== 'cables') tagPanel.hidden = true;
    renderCsv();
    if (S.kind === 'labels') { renderLabels(); return; }
    const data = S.data[S.kind];
    panel.innerHTML = '';
    problemsEl.innerHTML = '';
    if (!data) { panel.appendChild(h('p', {class: 'sch-hint', text: 'Loading\u2026'})); count.textContent = ''; return; }
    if (data.error) panel.appendChild(h('p', {class: 'sch-error', text: data.error}));
    list(data.problems).forEach(function (p) { problemsEl.appendChild(h('li', {class: 'sch-' + (p.level || 'warning'), text: p.message || p.code})); });
    const columns = list(data.columns).length ? data.columns : cols(S.kind);
    const rows = filteredRows(data.rows, columns);
    count.textContent = (S.loading ? 'Refreshing\u2026 ' : '') + rows.length + ' row' + (rows.length === 1 ? '' : 's');
    panel.appendChild(renderTable(columns, rows));
    if (data.totals && Object.keys(data.totals).length) {
      panel.appendChild(h('p', {class: 'sch-totals', text: 'Total: ' + Object.keys(data.totals).map(function (c) {
        return Number(data.totals[c]).toFixed(2) + ' ' + c;
      }).join(' \u00b7 ')}));
    }
  }

  function filteredRows(rows, columns) {
    let out = list(rows).slice();
    const t = S.text.trim().toLowerCase();
    if (t) {
      out = out.filter(function (r) {
        return columns.some(function (c) { const v = r[c.key]; return v != null && String(v).toLowerCase().indexOf(t) >= 0; });
      });
    }
    if (S.sort) {
      const k = S.sort.key;
      const dir = S.sort.dir;
      out.sort(function (a, b) {
        const x = a[k];
        const y = b[k];
        const nx = parseFloat(x);
        const ny = parseFloat(y);
        let c;
        if (!isNaN(nx) && !isNaN(ny) && String(nx) === String(x).trim() && String(ny) === String(y).trim()) c = nx - ny;
        else c = String(x == null ? '' : x).localeCompare(String(y == null ? '' : y), undefined, {numeric: true});
        return c * dir;
      });
    }
    return out;
  }

  function rowDiscipline(r) {
    if (r.discipline) return r.discipline;
    const d = doc();
    if (S.kind === 'cables' || S.kind === 'patch') {
      const c = (d.cables || []).filter(function (x) { return x.id === (r.id || r.cable_id); })[0];
      if (c) return mediumInfo(c.medium, vocab).discipline || 'other';
      if (r.medium) return mediumInfo(r.medium, vocab).discipline || 'other';
    }
    if (S.kind === 'bom') return r.category === 'cable' ? '' : r.category;
    const dev = (d.devices || []).filter(function (x) { return x.id === r.device_id; })[0];
    return dev ? deviceDiscipline(dev, vocab) : '';
  }

  function chip(disc) {
    if (!disc) return h('span', {class: 'sch-chip sch-chip-none', text: S.kind === 'bom' ? 'Cable' : ''});
    const info = vocab.disciplines && vocab.disciplines[disc];
    return h('span', {class: 'sch-chip', style: '--sch-color:' + ((info && info.color) || '#9aa3b5'), text: (info && info.label) || disc});
  }

  function rowEditable(r) {
    if (readOnly()) return false;
    if (S.kind === 'cables') return !!r.id;
    if (S.kind === 'ip' || S.kind === 'dmx') return !!r.device_id && (!r.source || r.source === 'manual');
    return false;
  }

  function renderTable(columns, rows) {
    const table = h('table', {class: 'sch-table', 'data-kind': S.kind});
    const caption = h('caption', {class: 'sch-sr', text: (KINDS.filter(function (k) { return k.key === S.kind; })[0] || {}).label + ' schedule'});
    table.appendChild(caption);
    const trh = h('tr');
    trh.appendChild(h('th', {scope: 'col', class: 'sch-chipcol', text: 'Discipline'}));
    columns.forEach(function (c) {
      const sorted = S.sort && S.sort.key === c.key;
      trh.appendChild(h('th', {scope: 'col', 'aria-sort': sorted ? (S.sort.dir > 0 ? 'ascending' : 'descending') : 'none'}, [
        h('button', {type: 'button', class: 'sch-sort', 'data-sort': c.key, text: c.label + (sorted ? (S.sort.dir > 0 ? ' \u25b2' : ' \u25bc') : '')}),
      ]));
    });
    table.appendChild(h('thead', null, [trh]));
    const tbody = h('tbody');
    const editCols = EDITABLE[S.kind] || [];
    rows.forEach(function (r, ri) {
      const tr = h('tr', {'data-row': String(ri), 'data-id': r.id || r.device_id || '',
        class: (r.status === 'planned' ? 'sch-planned' : '') + (S.kind === 'cables' && !r.tag ? ' sch-untagged' : '')});
      tr.appendChild(h('td', {class: 'sch-chipcol'}, [chip(rowDiscipline(r)), r.status === 'planned' ? h('span', {class: 'sch-chip sch-chip-planned', text: 'planned'}) : null]));
      const editable = rowEditable(r);
      columns.forEach(function (c) {
        const v = r[c.key];
        if (editable && editCols.indexOf(c.key) >= 0) {
          tr.appendChild(h('td', {class: 'sch-edit'}, [editor(r, c, v)]));
        } else if (c.key === 'medium' && v) {
          const m = mediumInfo(v, vocab);
          tr.appendChild(h('td', null, [h('span', {class: 'sch-mdot', style: 'background:' + (m.color || '#9aa3b5'), 'aria-hidden': 'true'}), String(v)]));
        } else if ((c.key === 'unit_cost' || c.key === 'extended') && v !== '' && v != null) {
          tr.appendChild(h('td', {class: 'sch-num', text: Number(v).toFixed(2)}));
        } else if (c.key === 'unit_cost' && v == null && r.qty) {
          tr.appendChild(h('td', {class: 'sch-num sch-muted', text: r.category === 'cable' ? '' : 'varies'}));
        } else {
          tr.appendChild(h('td', {class: typeof v === 'number' ? 'sch-num' : null, text: v == null ? '' : String(v)}));
        }
      });
      tbody.appendChild(tr);
    });
    if (!rows.length) tbody.appendChild(h('tr', null, [h('td', {colspan: String(columns.length + 1), class: 'sch-hint', text: 'No rows for this filter.'})]));
    table.appendChild(tbody);
    S.rows = rows;
    return h('div', {class: 'sch-scroll'}, [table]);
  }

  function editor(r, c, v) {
    const label = c.label + ' for ' + (S.kind === 'cables' ? 'cable ' + (r.tag || r.id) : r.device + (r.interface ? ' ' + r.interface : ''));
    if (c.key === 'status') {
      return h('select', {'data-edit': c.key, 'aria-label': label}, STATUSES.map(function (s) {
        return h('option', {value: s, text: s, selected: (v || 'installed') === s});
      }));
    }
    return h('input', {type: 'text', 'data-edit': c.key, value: v == null ? '' : String(v), 'aria-label': label,
      inputmode: NUMERIC_EDIT[c.key] || null, size: c.key === 'note' ? '18' : (c.key === 'tag' || c.key === 'length' || c.key === 'vlan' || c.key === 'universe' || c.key === 'address' || c.key === 'footprint') ? '6' : '12'});
  }

  function renderCsv() {
    if (S.csvUrl && typeof URL !== 'undefined' && URL.revokeObjectURL) { URL.revokeObjectURL(S.csvUrl); S.csvUrl = ''; }
    if (S.kind === 'labels') { csv.removeAttribute('href'); csv.setAttribute('aria-disabled', 'true'); return; }
    csv.removeAttribute('aria-disabled');
    const name = (ctx.project || 'project') + '-' + S.kind + '.csv';
    csv.setAttribute('download', name);
    if (ctx.api && ctx.api.scheduleUrl) {
      csv.setAttribute('href', ctx.api.scheduleUrl(ctx.project, S.kind, Object.assign({format: 'csv'}, params())));
      return;
    }
    const data = S.data[S.kind];
    if (!data || typeof Blob === 'undefined') { csv.removeAttribute('href'); return; }
    const columns = list(data.columns).length ? data.columns : cols(S.kind);
    S.csvUrl = URL.createObjectURL(new Blob([csvString(columns, data.rows)], {type: 'text/csv;charset=utf-8'}));
    csv.setAttribute('href', S.csvUrl);
  }

  function renderLabels() {
    panel.innerHTML = '';
    problemsEl.innerHTML = '';
    if (ctx.api && ctx.api.scheduleUrl) {
      const url = ctx.api.scheduleUrl(ctx.project, 'labels', Object.assign({format: 'html'}, params()));
      count.textContent = '';
      panel.appendChild(h('p', null, [h('a', {href: url, target: '_blank', rel: 'noopener', class: 'sch-btn', text: 'Open printable label sheet'})]));
      panel.appendChild(h('iframe', {class: 'sch-labels-frame', src: url, title: 'Cable label sheet'}));
      return;
    }
    const labels = localLabels(doc(), room());
    count.textContent = labels.length + ' labels';
    if (!labels.length) { panel.appendChild(h('p', {class: 'sch-hint', text: 'No tagged cables yet. Use "Assign tags" on the Cables tab.'})); return; }
    const grid = h('div', {class: 'sch-labels', role: 'list', 'aria-label': 'Cable labels'});
    labels.forEach(function (l) {
      grid.appendChild(h('div', {class: 'sch-label', role: 'listitem'}, [
        h('div', {class: 'sch-label-tag', text: l.tag}), h('div', {class: 'sch-label-line', text: l.line}), h('div', {class: 'sch-label-end', text: l.end}),
      ]));
    });
    panel.appendChild(grid);
  }

  // ---------------------------------------------------------- tag panel
  function openTags() {
    tagPanel.hidden = false;
    tagPanel.innerHTML = '';
    const pat = (doc().settings && doc().settings.cable_tag_pattern) || '{D}-{n:03}';
    const scope = h('select', {id: 'sch-tag-scope'}, [h('option', {value: 'missing', text: 'Only untagged cables'}), h('option', {value: 'all', text: 'Renumber all cables'})]);
    const pattern = h('input', {id: 'sch-tag-pattern', type: 'text', value: pat, size: '14'});
    const go = h('button', {type: 'button', class: 'sch-btn', 'data-act': 'preview', text: 'Preview'});
    tagPanel.appendChild(h('div', {class: 'sch-tagform'}, [
      h('label', {for: 'sch-tag-scope', text: 'Scope'}), scope,
      h('label', {for: 'sch-tag-pattern', text: 'Pattern'}), pattern, go,
      h('button', {type: 'button', class: 'sch-btn', 'data-act': 'close', text: 'Close'}),
    ]));
    tagPanel.appendChild(h('div', {class: 'sch-tagresult'}));
    preview();
    scope.focus();
  }

  function preview() {
    const scope = tagPanel.querySelector('#sch-tag-scope').value;
    const pattern = tagPanel.querySelector('#sch-tag-pattern').value.trim();
    const out = tagPanel.querySelector('.sch-tagresult');
    out.textContent = 'Computing\u2026';
    const settingsPat = (doc().settings && doc().settings.cable_tag_pattern) || '{D}-{n:03}';
    const p = ctx.api && ctx.api.tagPreview
      ? Promise.resolve(ctx.api.tagPreview(ctx.project, scope, pattern && pattern !== settingsPat ? pattern : undefined))
      : Promise.resolve({ops: assignTagsLocal(doc(), scope, pattern, vocab), base_revision: store.revision, local: true});
    p.then(function (res) {
      const ops = list(res && res.ops);
      S.preview = {ops: ops, base: res ? res.base_revision : null, scope: scope, pattern: pattern};
      showPreview(out, ops, res && res.local);
    }, function (err) {
      out.textContent = (err && err.message) || 'Tag preview failed.';
    });
  }

  function showPreview(out, ops, local) {
    out.innerHTML = '';
    if (!ops.length) { out.appendChild(h('p', {class: 'sch-hint', text: 'Nothing to change: every cable already has a tag.'})); return; }
    const cabs = {};
    (doc().cables || []).forEach(function (c) { cabs[c.id] = c; });
    const devs = byId(doc().devices);
    const table = h('table', {class: 'sch-table sch-preview'});
    table.appendChild(h('caption', {class: 'sch-sr', text: 'Proposed cable tags'}));
    table.appendChild(h('thead', null, [h('tr', null, ['Cable', 'From', 'To', 'Current tag', 'New tag'].map(function (t) { return h('th', {scope: 'col', text: t}); }))]));
    const tb = h('tbody');
    ops.forEach(function (o) {
      const c = cabs[o.id] || {from: {}, to: {}};
      const a = devs[c.from.device];
      const b = devs[c.to.device];
      tb.appendChild(h('tr', null, [
        h('td', {text: o.id}),
        h('td', {text: (a ? a.name : c.from.device || '') + (c.from.port ? ' \u00b7 ' + portName(a, c.from.port) : '')}),
        h('td', {text: (b ? b.name : c.to.device || '') + (c.to.port ? ' \u00b7 ' + portName(b, c.to.port) : '')}),
        h('td', {text: c.tag || '\u2014'}),
        h('td', {class: 'sch-newtag', text: o.value && o.value.tag}),
      ]));
    });
    table.appendChild(tb);
    out.appendChild(h('div', {class: 'sch-scroll sch-preview-scroll'}, [table]));
    out.appendChild(h('div', {class: 'sch-tagform'}, [
      h('button', {type: 'button', class: 'sch-btn sch-primary', 'data-act': 'confirm', disabled: readOnly(), text: 'Assign ' + ops.length + ' tag' + (ops.length === 1 ? '' : 's')}),
      local ? h('span', {class: 'sch-hint', text: 'Local preview (harness mode).'}) : null,
    ]));
  }

  function confirmTags() {
    const pv = S.preview;
    if (!pv || !pv.ops.length) return;
    if (ctx.api && pv.base != null && store.revision != null && pv.base !== store.revision) {
      ctx.toast('The project changed since the preview. Showing a fresh preview.', 'warn');
      preview();
      return;
    }
    ctx.commit(pv.ops, 'Assigned ' + pv.ops.length + ' cable tag' + (pv.ops.length === 1 ? '' : 's'));
    S.preview = null;
    tagPanel.hidden = true;
    btnTags.focus();
  }

  // -------------------------------------------------------------- edits
  function cellOps(r, key, raw) {
    const d = doc();
    const val = String(raw).trim();
    if (S.kind === 'cables') {
      const c = (d.cables || []).filter(function (x) { return x.id === r.id; })[0];
      if (!c) return [];
      if (key === 'length') {
        if (val === '') return c.length_m == null ? [] : [{op: 'merge', coll: 'cables', id: c.id, value: {length_m: null}}];
        const n = parseFloat(val.replace(',', '.'));
        if (!(n >= 0)) { ctx.toast('Length must be a number.', 'warn'); return null; }
        const m = units() === 'imperial' ? Math.round(n * FT * 1000) / 1000 : n;
        return m === c.length_m ? [] : [{op: 'merge', coll: 'cables', id: c.id, value: {length_m: m}}];
      }
      const cur = c[key] == null ? (key === 'status' ? 'installed' : '') : String(c[key]);
      if (cur === val) return [];
      const value = {};
      value[key] = val === '' || (key === 'status' && val === 'installed' && c.status == null) ? null : val;
      return [{op: 'merge', coll: 'cables', id: c.id, value: value}];
    }
    const dev = (d.devices || []).filter(function (x) { return x.id === r.device_id; })[0];
    if (!dev) return [];
    if (S.kind === 'ip') {
      const ifid = r.interface_id || r.interface;
      const ifs = list(dev.interfaces).map(function (i) { return Object.assign({}, i); });
      const it = ifs.filter(function (i) { return i.id === ifid; })[0];
      if (!it) return [];
      let v = val;
      if (key === 'vlan') {
        if (val !== '' && !(parseInt(val, 10) >= 1 && parseInt(val, 10) <= 4094)) { ctx.toast('VLAN must be 1\u20134094.', 'warn'); return null; }
        v = val === '' ? '' : parseInt(val, 10);
      } else if (key === 'mac' && val) {
        const m = normalizeMac(val);
        if (!m) { ctx.toast('MAC must be 12 hex digits (colon, dash, dotted or bare).', 'warn'); return null; }
        v = m;
      } else if (key === 'switch' && val) {
        const sw = (d.devices || []).filter(function (x) { return x.id === val || x.name === val; })[0];
        v = sw ? sw.id : val;
      } else if (key === 'switch_port' && val && it.switch) {
        const sw2 = (d.devices || []).filter(function (x) { return x.id === it.switch; })[0];
        const p = list(sw2 && sw2.ports).filter(function (x) { return x.id === val || x.name === val || x.label === val; })[0];
        v = p ? p.id : val;
      }
      if (String(it[key] == null ? '' : it[key]) === String(v)) return [];
      if (v === '') delete it[key]; else it[key] = v;
      return [{op: 'merge', coll: 'devices', id: dev.id, value: {interfaces: ifs}}];
    }
    if (S.kind === 'dmx') {
      const x = dev.dmx || {};
      let v = val;
      if (key === 'universe' || key === 'address' || key === 'footprint') {
        const lim = key === 'universe' ? 63999 : 512;
        if (val !== '' && !(parseInt(val, 10) >= 1 && parseInt(val, 10) <= lim)) { ctx.toast(key + ' must be 1\u2013' + lim + '.', 'warn'); return null; }
        v = val === '' ? null : parseInt(val, 10);
      } else if (val === '') v = null;
      if ((x[key] == null ? null : x[key]) === v) return [];
      const patch = {};
      patch[key] = v;
      return [{op: 'merge', coll: 'devices', id: dev.id, value: {dmx: patch}}];
    }
    return [];
  }

  function onEdit(e) {
    const inp = e.target.closest('[data-edit]');
    if (!inp) return;
    const tr = inp.closest('tr');
    const r = S.rows && S.rows[parseInt(tr.getAttribute('data-row'), 10)];
    if (!r) return;
    const key = inp.getAttribute('data-edit');
    const ops = cellOps(r, key, inp.value);
    if (ops === null) { inp.value = r[key] == null ? '' : String(r[key]); return; }
    if (!ops.length) return;
    const what = S.kind === 'cables' ? 'cable ' + (r.tag || r.id) : r.device;
    ctx.commit(ops, 'Set ' + key + ' of ' + what);
    r[key] = key === 'mac' ? (normalizeMac(inp.value) || inp.value) : inp.value;
  }

  // ------------------------------------------------------------- events
  on(tabs, 'click', function (e) {
    const b = e.target.closest('[data-kind]');
    if (!b) return;
    S.kind = b.getAttribute('data-kind');
    S.sort = null;
    load();
  });
  on(tabs, 'keydown', function (e) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const i = KINDS.map(function (k) { return k.key; }).indexOf(S.kind);
    const n = KINDS[(i + (e.key === 'ArrowRight' ? 1 : KINDS.length - 1)) % KINDS.length].key;
    S.kind = n;
    S.sort = null;
    load();
    const t = tabs.querySelector('[data-kind="' + n + '"]');
    if (t) t.focus();
  });
  on(roomSel, 'change', function () { S.room = roomSel.value; load(); });
  on(stateSel, 'change', function () { S.state = stateSel.value; load(); });
  on(discSel, 'change', function () { S.disc = discSel.value; load(); });
  on(textIn, 'input', function () { S.text = textIn.value; render(); });
  on(btnTags, 'click', function () { if (tagPanel.hidden) openTags(); else { tagPanel.hidden = true; } });
  on(tagPanel, 'click', function (e) {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    const act = b.getAttribute('data-act');
    if (act === 'preview') preview();
    else if (act === 'confirm') confirmTags();
    else if (act === 'close') { tagPanel.hidden = true; btnTags.focus(); }
  });
  on(tagPanel, 'keydown', function (e) { if (e.key === 'Escape') { tagPanel.hidden = true; btnTags.focus(); } });
  on(btnPrint, 'click', function () { if (typeof window.print === 'function') window.print(); });
  on(csv, 'click', function (e) { if (!csv.getAttribute('href')) e.preventDefault(); });
  on(panel, 'click', function (e) {
    const s = e.target.closest('[data-sort]');
    if (s) {
      const k = s.getAttribute('data-sort');
      S.sort = S.sort && S.sort.key === k ? (S.sort.dir > 0 ? {key: k, dir: -1} : null) : {key: k, dir: 1};
      render();
      const again = panel.querySelector('[data-sort="' + k + '"]');
      if (again) again.focus();
      return;
    }
    if (e.target.closest('input,select,a,button')) return;
    const tr = e.target.closest('tr[data-row]');
    const r = tr && S.rows && S.rows[parseInt(tr.getAttribute('data-row'), 10)];
    if (!r) return;
    if (S.kind === 'cables' && r.id) ctx.select({type: 'cable', id: r.id});
    else if (r.device_id) ctx.select({type: 'device', id: r.device_id});
  });
  on(panel, 'change', onEdit);
  on(panel, 'keydown', function (e) {
    const inp = e.target.closest('input[data-edit]');
    if (!inp) return;
    if (e.key === 'Enter') { e.preventDefault(); inp.blur(); }
    if (e.key === 'Escape') {
      const tr = inp.closest('tr');
      const r = S.rows && S.rows[parseInt(tr.getAttribute('data-row'), 10)];
      if (r) inp.value = r[inp.getAttribute('data-edit')] == null ? '' : String(r[inp.getAttribute('data-edit')]);
      inp.blur();
    }
  });
  on(store, 'doc', function (e) {
    const src = e.detail && e.detail.source;
    if (!ctx.api || src === 'load' || src === 'remote') reloadSoon();
  });
  on(store, 'revision', function () { if (ctx.api) reloadSoon(); });
  on(store, 'room', function () { load(); });
  on(store, 'overlay', function () { if (!ctx.api) reloadSoon(); });
  on(store, 'mode', render);

  load();

  return {
    destroy: function () {
      listeners.forEach(function (l) { l[0].removeEventListener(l[1], l[2], l[3]); });
      if (reloadTimer) clearTimeout(reloadTimer);
      if (S.csvUrl && URL.revokeObjectURL) URL.revokeObjectURL(S.csvUrl);
      el.innerHTML = '';
    },
    focus: function (sel) {
      if (!sel) return;
      if (sel.type === 'cable') { S.kind = 'cables'; load(); }
    },
    getState: function () { return {kind: S.kind, room: S.room, state: S.state, disc: S.disc}; },
    setState: function (s) {
      if (!s) return;
      S.kind = s.kind || S.kind; S.room = s.room || S.room; S.state = s.state || S.state; S.disc = s.disc || '';
      roomSel.value = S.room; stateSel.value = S.state; discSel.value = S.disc;
      load();
    },
    _state: S,
  };
}
