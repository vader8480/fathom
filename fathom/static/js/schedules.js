// Schedules view: cables (tag preview + assign), IP, DMX, BOM, patch, racks,
// labels. Rows come from GET …/schedules/<kind> when ctx.api exists; in harness
// mode (ctx.api === null) minimal rows are computed locally from the doc.
// mount(el, ctx) (§6.4, §6.7). Each kind is one DataTable under the routed tab
// schedules/<kind> (docs/ui-audit.md B.3 SCH); labels stay a printable sheet.
import {rackDevices, findRack, ruLabel} from './rack-core.js';
import {h, on} from './dom.js';
import {createTable, openTableDialog} from './datatable.js';
import {applyState, normalizeColumns, storageKey, textOf} from './datatable-core.js';
import {selToString} from './router-core.js';

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
          template: d.template || '', qty: 0, unit_cost: null, extended: 0, currency: '', planned: 0, installed: 0, spare: 0, retired: 0, length_total_m: '', devices: [], _units: {}};
        order.push(key);
      }
      const g = groups[key];
      g.devices.push(d.id);
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
          planned: 0, installed: 0, spare: 0, retired: 0, length_total_m: 0, medium: c.medium || '', type: c.type || ''};
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

// Columns that stay on screen below 700px; the first is the sticky lead. Every
// other column is hideOnMobile (still in the CSV and the column chooser).
const MOBILE_COLS = {
  cables: ['tag', 'from_device', 'from_port', 'to_device', 'to_port'],
  ip: ['device', 'interface', 'ip'],
  dmx: ['universe', 'address', 'device'],
  bom: ['model', 'qty', 'extended'],
  patch: ['device', 'port', 'peer_device', 'peer_port'],
  racks: ['rack', 'u', 'device'],
};
const FILTER_COLS = {
  cables: ['medium', 'status'],
  ip: ['room', 'network'],
  dmx: ['room', 'universe'],
  bom: [],
  patch: ['room', 'dir'],
  racks: ['room', 'rack'],
};
const NUMERIC_COLS = ['length', 'channels', 'prefix', 'vlan', 'address', 'end', 'footprint', 'qty', 'unit_cost', 'extended',
  'planned', 'installed', 'spare', 'retired', 'length_total_m', 'units', 'u', 'height'];
const NOUNS = {
  cables: {one: 'cable', many: 'cables'}, ip: {one: 'address', many: 'addresses'}, dmx: {one: 'patch', many: 'patches'},
  bom: {one: 'line', many: 'lines'}, patch: {one: 'port', many: 'ports'}, racks: {one: 'placement', many: 'placements'},
};
const SECTIONS = {ip: 'net', dmx: 'dmx', bom: 'inventory'};
const KEEP_ON_TAB = ['sel', 'sec', 'drawer'];

function kindOf(k) {
  for (let i = 0; i < KINDS.length; i++) if (KINDS[i].key === k) return k;
  return null;
}

function kindLabel(k) {
  const m = KINDS.filter(function (x) { return x.key === k; })[0];
  return m ? m.label : k;
}

function rowKey(kind, r) {
  if (kind === 'cables') return r.id || '';
  if (kind === 'ip') return [r.device_id, r.interface_id || r.interface, r.role].join('|');
  if (kind === 'dmx') return [r.device_id, r.universe, r.address].join('|');
  if (kind === 'bom') return [r.category, r.manufacturer, r.model, r.template, r.medium || '', r.type || ''].join('|');
  if (kind === 'patch') return [r.device_id, r.port_id, r.cable_id || ''].join('|');
  if (kind === 'racks') return [r.rack_id, r.device_id, r.face, r.u].join('|');
  return '';
}

function money(v) { return v === '' || v == null ? '' : Number(v).toFixed(2); }

export function mount(el, ctx) {
  const store = ctx.store;
  const vocab = ctx.vocab || store.vocab || {};
  const r0 = ctx.route;
  // Routed: the shell owns the URL (tab segment + table params). Otherwise (dev
  // harness, hosts without a router) tabs switch in memory.
  const ROUTED = !!(r0 && r0.view === 'schedules' && typeof ctx.navigateRoute === 'function' && typeof ctx.setParams === 'function');
  const S = {kind: (ROUTED && kindOf(r0.tab)) || 'cables', room: 'current', state: 'all', data: {}, gen: 0, reqId: 0,
    preview: null, rows: [], byId: {}, hl: null, pending: false};
  const offs = [];
  let table = null;
  let lastPick = null;
  let printSheet = null;
  let reloadTimer = null;
  let destroyed = false;
  function listen(target, type, fn, opts) { if (target) offs.push(on(target, type, fn, opts)); }

  el.innerHTML = '';
  const root = h('div', {class: 'sch-root', 'data-routed': ROUTED ? 'true' : 'false'});
  const tabs = h('div', {class: 'sch-tabs', role: 'tablist', 'aria-label': 'Schedules'});
  KINDS.forEach(function (k) {
    tabs.appendChild(h('a', {role: 'tab', id: 'sch-tab-' + k.key, 'data-kind': k.key, 'aria-controls': 'sch-panel', 'aria-selected': 'false', tabindex: '-1', href: '#', text: k.label}));
  });
  const stateSel = h('select', {id: 'sch-state', 'aria-label': 'State filter', title: 'Which devices and cables the schedule includes'}, [
    h('option', {value: 'all', text: 'All (no retired)'}), h('option', {value: 'planned', text: 'Planned + installed'}),
    h('option', {value: 'as_built', text: 'As built'}), h('option', {value: 'everything', text: 'Everything'})]);
  // Routed views follow the header room picker; the harness has none, so it keeps its own.
  const roomSel = ROUTED ? null : h('select', {id: 'sch-room', 'aria-label': 'Room filter'}, [h('option', {value: 'current', text: 'Current room'}), h('option', {value: '*', text: 'All rooms'})]);
  const btnTags = h('button', {id: 'sch-assign-tags', type: 'button', class: 'sch-btn', text: 'Assign tags\u2026'});
  const btnBulk = h('button', {id: 'sch-bulk-add', type: 'button', class: 'sch-btn', text: 'Bulk add cables\u2026'});
  const btnPrint = h('button', {id: 'sch-print', type: 'button', class: 'sch-btn', text: 'Print'});
  const csvAll = ctx.api && ctx.api.scheduleUrl ? h('a', {id: 'sch-csv-all', class: 'sch-btn', role: 'button', title: 'Server CSV of every row in this room and state', text: 'Full CSV'}) : null;
  const labelsCsv = h('a', {id: 'sch-csv', class: 'sch-btn', role: 'button', 'aria-disabled': 'true', text: 'CSV'});
  const tagPanel = h('div', {class: 'sch-tagpanel', hidden: true, role: 'region', 'aria-label': 'Cable tag preview'});
  const errorEl = h('p', {class: 'sch-error', role: 'alert', hidden: true});
  const problemsEl = h('ul', {class: 'sch-problems', 'aria-label': 'Schedule warnings'});
  const host = h('div', {class: 'sch-host'});
  const totalsEl = h('p', {class: 'sch-totals', hidden: true});
  const panel = h('div', {class: 'sch-panel', id: 'sch-panel', role: 'tabpanel'}, [tagPanel, errorEl, problemsEl, host, totalsEl]);
  root.appendChild(tabs);
  root.appendChild(panel);
  el.appendChild(root);

  function doc() { return store.doc; }
  function readOnly() { return !!store.readOnly || ctx.role === 'viewer'; }
  function room() {
    if (!ROUTED && S.room === '*') return '*';
    return store.room && store.room !== '*' ? store.room : '*';
  }
  function params() { return {room: room(), state: S.state}; }
  function paramKey() { return room() + '|' + S.state; }
  function units() { return (doc().settings && doc().settings.units) || 'metric'; }
  function query() {
    const r = ROUTED ? ctx.route : null;
    return (r && r.view === 'schedules' && r.query) || {};
  }

  // ------------------------------------------------------------- tabs
  function tabHref(k) {
    if (!ROUTED || typeof ctx.routeHref !== 'function') return '#';
    try { return ctx.routeHref({tab: k, query: {}}) || '#'; } catch (e) { return '#'; }
  }

  function refreshTabs() {
    Array.prototype.forEach.call(tabs.children, function (a) {
      const k = a.getAttribute('data-kind');
      const cur = k === S.kind;
      a.setAttribute('aria-selected', cur ? 'true' : 'false');
      a.tabIndex = cur ? 0 : -1;
      a.setAttribute('href', tabHref(k));
    });
    panel.setAttribute('aria-labelledby', 'sch-tab-' + S.kind);
  }

  function goTab(k) {
    if (!ROUTED) { if (k !== S.kind) activate(k); return; }
    const r = ctx.route;
    if (k === S.kind && r.tab === k) return;
    const q = r.query || {};
    const keep = {};
    KEEP_ON_TAB.forEach(function (n) { if (q[n]) keep[n] = q[n]; });
    ctx.navigateRoute({tab: k, query: keep});
  }

  function activate(k) {
    S.kind = k;
    refreshTabs();
    if (k !== 'cables') tagPanel.hidden = true;
    if (typeof ctx.setTitle === 'function') ctx.setTitle(kindLabel(k) + ' schedule');
    buildTable();
    load();
  }

  // ------------------------------------------------------------ table
  function discLabel(kind, d) {
    if (!d) return kind === 'bom' ? 'Cable' : '';
    const info = vocab.disciplines && vocab.disciplines[d];
    return (info && info.label) || d;
  }

  function chip(kind, disc) {
    if (!disc) return h('span', {class: 'sch-chip sch-chip-none', text: kind === 'bom' ? 'Cable' : ''});
    const info = vocab.disciplines && vocab.disciplines[disc];
    return h('span', {class: 'sch-chip', style: '--sch-color:' + ((info && info.color) || '#9aa3b5'), text: (info && info.label) || disc});
  }

  function rowDiscipline(kind, r, devs, cabs) {
    if (r.discipline) return r.discipline;
    if (kind === 'cables' || kind === 'patch') {
      const c = cabs[r.id || r.cable_id];
      if (c) return mediumInfo(c.medium, vocab).discipline || 'other';
      if (r.medium) return mediumInfo(r.medium, vocab).discipline || 'other';
    }
    if (kind === 'bom') return r.category === 'cable' ? '' : r.category;
    const dev = devs[r.device_id];
    return dev ? deviceDiscipline(dev, vocab) : '';
  }

  function rowEditable(kind, r) {
    if (readOnly()) return false;
    if (kind === 'cables') return !!r.id;
    if (kind === 'ip' || kind === 'dmx') return !!r.device_id && (!r.source || r.source === 'manual');
    return false;
  }

  function editor(kind, r, c, v) {
    const label = c.label + ' for ' + (kind === 'cables' ? 'cable ' + (r.tag || r.id) : r.device + (r.interface ? ' ' + r.interface : ''));
    if (c.key === 'status') {
      return h('select', {'data-edit': c.key, 'aria-label': label}, STATUSES.map(function (s) {
        return h('option', {value: s, text: s, selected: (v || 'installed') === s});
      }));
    }
    return h('input', {type: 'text', 'data-edit': c.key, value: v == null ? '' : String(v), 'aria-label': label,
      inputmode: NUMERIC_EDIT[c.key] || null, size: c.key === 'note' ? '18' : (c.key === 'tag' || c.key === 'length' || c.key === 'vlan' || c.key === 'universe' || c.key === 'address' || c.key === 'footprint') ? '6' : '12'});
  }

  function columnsFor(kind) {
    const mob = MOBILE_COLS[kind];
    const fil = FILTER_COLS[kind];
    const edit = EDITABLE[kind] || [];
    const out = [{
      key: 'disc', header: 'Discipline', csv: false, filterable: true, hideOnMobile: true,
      value: function (r) { return r._discLabel; },
      cell: function (r) {
        return h('span', {class: 'sch-chips'}, [chip(kind, r._disc), r.status === 'planned' ? h('span', {class: 'sch-chip sch-chip-planned', text: 'planned'}) : null]);
      },
    }];
    COLUMNS[kind].forEach(function (pair) {
      const key = pair[0];
      const c = {key: key, label: pair[1]};
      const col = {
        key: key, header: pair[1], hideOnMobile: mob.indexOf(key) < 0, sticky: key === mob[0],
        filterable: fil.indexOf(key) >= 0, align: NUMERIC_COLS.indexOf(key) >= 0 ? 'right' : 'left',
      };
      if (edit.indexOf(key) >= 0) {
        col.cell = function (r) {
          return rowEditable(kind, r) ? h('span', {class: 'sch-edit'}, editor(kind, r, c, r[key])) : textOf(r[key]);
        };
      } else if (key === 'medium') {
        col.cell = function (r) {
          if (!r.medium) return '';
          const m = mediumInfo(r.medium, vocab);
          return h('span', null, [h('span', {class: 'sch-mdot', style: 'background:' + (m.color || '#9aa3b5'), 'aria-hidden': 'true'}), String(r.medium)]);
        };
      } else if (key === 'unit_cost' || key === 'extended') {
        col.cell = function (r) {
          const v = r[key];
          if (v !== '' && v != null) return money(v);
          if (key === 'unit_cost' && r.qty && r.category !== 'cable') return h('span', {class: 'sch-muted', text: 'varies'});
          return '';
        };
      }
      out.push(col);
    });
    return out;
  }

  function filterIds(kind) {
    const ids = {disc: 'sch-disc'};
    if (ROUTED && FILTER_COLS[kind].indexOf('room') >= 0) ids.room = 'sch-room';
    return ids;
  }

  function actionsFor(kind) {
    return [stateSel, roomSel, kind === 'cables' ? btnTags : null, kind === 'cables' && !readOnly() ? btnBulk : null, btnPrint, csvAll]
      .filter(function (n) { return !!n; });
  }

  // A bulk-add result link filters by f.id; once the URL drops it the stored
  // filter must go too, or it would hide every other cable on the next visit.
  function scrubStaleId(scope, key) {
    if (query()['f.id']) return;
    try {
      const ls = window.localStorage;
      const k = storageKey(scope, key);
      const raw = ls.getItem(k);
      if (!raw) return;
      const j = JSON.parse(raw);
      if (j && j.filters && j.filters.id) { delete j.filters.id; ls.setItem(k, JSON.stringify(j)); }
    } catch (e) { /* storage unavailable: nothing persisted */ }
  }

  function dropStaleId() {
    if (!table || query()['f.id']) return;
    const st = table.getState();
    if (!st.filters || !st.filters.id) return;
    const f = Object.assign({}, st.filters);
    delete f.id;
    table.setState({filters: f});
  }

  const urlBinding = {
    get: query,
    set: function (patch) { if (!destroyed && ctx.route && ctx.route.view === 'schedules') ctx.setParams(patch); },
  };

  function buildTable() {
    dropPrintSheet();
    if (table) { table.destroy(); table = null; }
    host.innerHTML = '';
    errorEl.hidden = true;
    problemsEl.innerHTML = '';
    totalsEl.hidden = true;
    S.rows = [];
    S.byId = {};
    S.hl = null;
    S.pending = false;
    const kind = S.kind;
    if (kind === 'labels') return;
    const scope = (ROUTED ? '' : 'dev.') + (ctx.project || '');
    scrubStaleId(scope, 'schedules.' + kind);
    S.hl = wantHl();
    table = createTable(host, {
      key: 'schedules.' + kind,
      scope: scope,
      caption: kindLabel(kind) + ' schedule',
      columns: columnsFor(kind),
      rows: [],
      rowId: function (r) { return r._id; },
      onRow: function (r) { pick(kind, r); },
      rowAttrs: function (r) { return {'data-row': String(r._i)}; },
      rowClass: function (r) { return (r.status === 'planned' ? 'sch-planned' : '') + (kind === 'cables' && !r.tag ? ' sch-untagged' : ''); },
      actions: actionsFor(kind),
      ids: {root: 'sch-dt', search: 'sch-filter', csv: 'sch-csv', filters: filterIds(kind)},
      url: ROUTED ? urlBinding : null,
      csvName: (ctx.project || 'project') + '-' + kind + '.csv',
      highlight: S.hl,
      noun: NOUNS[kind],
      empty: 'No rows for this room and state.',
      searchPlaceholder: 'Filter rows',
    });
    const t = table.root.querySelector('.dt-table');
    t.classList.add('sch-table');
    t.setAttribute('data-kind', kind);
    btnTags.disabled = readOnly();
  }

  function decorate(kind, rows) {
    const devs = byId(doc().devices);
    const cabs = byId(doc().cables);
    const seen = {};
    return list(rows).map(function (r, i) {
      r._i = i;
      r._disc = rowDiscipline(kind, r, devs, cabs);
      r._discLabel = discLabel(kind, r._disc);
      let id = String(rowKey(kind, r));
      if (seen[id]) id += '#' + i;
      seen[id] = true;
      r._id = id;
      return r;
    });
  }

  function editing() {
    const a = document.activeElement;
    return !!(a && a.hasAttribute && a.hasAttribute('data-edit') && host.contains(a));
  }

  function showData() {
    const kind = S.kind;
    const entry = S.data[kind];
    if (!table || !entry) return;
    if (editing()) { S.pending = true; return; }
    S.pending = false;
    const res = entry.res;
    S.rows = decorate(kind, res.rows);
    S.byId = {};
    S.rows.forEach(function (r) { S.byId[r._id] = r; });
    errorEl.hidden = !res.error;
    errorEl.textContent = res.error || '';
    problemsEl.innerHTML = '';
    list(res.problems).forEach(function (p) { problemsEl.appendChild(h('li', {class: 'sch-' + (p.level || 'warning'), text: p.message || p.code})); });
    const tot = res.totals && Object.keys(res.totals).length ? res.totals : null;
    totalsEl.hidden = !tot;
    totalsEl.textContent = tot ? 'Total: ' + Object.keys(tot).map(function (c) { return Number(tot[c]).toFixed(2) + ' ' + c; }).join(' \u00b7 ') : '';
    table.setRows(S.rows);
    syncHl(false);
    if (csvAll) {
      csvAll.setAttribute('href', ctx.api.scheduleUrl(ctx.project, kind, Object.assign({format: 'csv'}, params())));
      csvAll.setAttribute('download', (ctx.project || 'project') + '-' + kind + '-all.csv');
    }
  }

  // ------------------------------------------------------------ loading
  function load() {
    const kind = S.kind;
    if (kind === 'labels') { renderLabels(); return; }
    const key = paramKey();
    const entry = S.data[kind];
    if (entry && entry.key === key && entry.gen === S.gen) { showData(); return; }
    if (!ctx.api) {
      S.data[kind] = {key: key, gen: S.gen, res: localSchedule(doc(), kind, params(), vocab, store.overlay)};
      showData();
      return;
    }
    const id = ++S.reqId;
    const gen = S.gen;
    if (entry && entry.key === key) showData();
    else if (table) table.setLoading(true);
    Promise.resolve(ctx.api.schedule(ctx.project, kind, params())).then(function (res) {
      if (destroyed || id !== S.reqId) return;
      S.data[kind] = {key: key, gen: gen, res: res || {columns: [], rows: []}};
      if (S.kind === kind) showData();
    }, function (err) {
      if (destroyed || id !== S.reqId) return;
      const res = localSchedule(doc(), kind, params(), vocab, store.overlay);
      res.error = (err && err.message) || 'Could not load the schedule; showing local rows.';
      S.data[kind] = {key: key, gen: gen, res: res};
      if (S.kind === kind) showData();
    });
  }

  function reloadSoon() {
    S.gen++;
    if (reloadTimer) clearTimeout(reloadTimer);
    reloadTimer = setTimeout(function () { reloadTimer = null; if (!destroyed) load(); }, ctx.api ? 300 : 0);
  }

  // ------------------------------------------------------- highlight
  function matchSel(kind, sel) {
    if (kind === 'cables') return sel.type === 'cable' ? sel.id : null;
    const dev = sel.type === 'device' || sel.type === 'port' || sel.type === 'channel' || sel.type === 'marker' ? (sel.device || sel.id) : null;
    for (let i = 0; i < S.rows.length; i++) {
      const r = S.rows[i];
      let hit = false;
      if (kind === 'patch') {
        if (sel.type === 'port') hit = r.device_id === dev && r.port_id === sel.port;
        else if (sel.type === 'cable') hit = r.cable_id === sel.id;
        else if (dev) hit = r.device_id === dev;
      } else if (kind === 'racks') {
        hit = sel.type === 'rack' ? r.rack_id === sel.id : (!!dev && r.device_id === dev);
      } else if (kind === 'bom') {
        hit = !!dev && list(r.devices).indexOf(dev) >= 0;
      } else if (dev) {
        hit = r.device_id === dev;
      }
      if (hit) return r._id;
    }
    return null;
  }

  function wantHl() {
    const kind = S.kind;
    const sel = store.selection;
    const s = sel ? selToString(sel) : '';
    if (s && lastPick && lastPick.kind === kind && lastPick.sel === s && S.byId[lastPick.id]) return lastPick.id;
    const m = sel ? matchSel(kind, sel) : null;
    if (m) return m;
    return query().hl || null;
  }

  // DataTable.setHighlight always scrolls the row to the centre; after a click on
  // a row that is already on screen, put the scroll positions back.
  function setHl(id, keepScroll) {
    const next = id == null || id === '' ? null : String(id);
    if (!table || next === S.hl) return;
    S.hl = next;
    if (!keepScroll) { table.setHighlight(next); return; }
    const sc = table.root.querySelector('.dt-scroll');
    const pos = [sc ? sc.scrollTop : 0, sc ? sc.scrollLeft : 0, el.scrollTop, panel.scrollTop];
    table.setHighlight(next);
    setTimeout(function () {
      if (sc) { sc.scrollTop = pos[0]; sc.scrollLeft = pos[1]; }
      el.scrollTop = pos[2];
      panel.scrollTop = pos[3];
    }, 0);
  }

  function syncHl(keepScroll) { setHl(wantHl(), keepScroll); }

  // --------------------------------------------------------- row → drawer
  function openSel(sel, section) {
    if (!sel) return;
    if (typeof ctx.openDrawer === 'function') ctx.openDrawer(sel, section ? {section: section} : undefined);
    else if (typeof ctx.select === 'function') ctx.select(sel);
  }

  function selFor(kind, r) {
    if (kind === 'cables') return r.id ? {type: 'cable', id: r.id} : null;
    if (kind === 'patch') {
      if (!r.device_id) return null;
      return r.port_id ? {type: 'port', id: r.device_id, device: r.device_id, port: r.port_id} : {type: 'device', id: r.device_id, device: r.device_id};
    }
    if (kind === 'racks') return r.rack_id ? {type: 'rack', id: r.rack_id} : null;
    return r.device_id ? {type: 'device', id: r.device_id, device: r.device_id} : null;
  }

  function pick(kind, r) {
    if (kind === 'bom') { pickBom(r); return; }
    const sel = selFor(kind, r);
    if (!sel) return;
    lastPick = {kind: kind, sel: selToString(sel), id: r._id};
    setHl(r._id, true);
    openSel(sel, SECTIONS[kind] || '');
  }

  function bomCables(r) {
    const devs = byId(doc().devices);
    const rm = room();
    return list(doc().cables).filter(function (c) {
      if (c.auto || (c.medium || '') !== (r.medium || '') || (c.type || '') !== (r.type || '') || !stateOk(c.status, S.state)) return false;
      const a = devs[c.from && c.from.device];
      const b = devs[c.to && c.to.device];
      return inRoom(a, rm) || inRoom(b, rm);
    });
  }

  function pickBom(r) {
    const rooms = byId(doc().rooms);
    if (r.category === 'cable') {
      const devs = byId(doc().devices);
      const cabs = bomCables(r);
      if (cabs.length === 1) { openSel({type: 'cable', id: cabs[0].id}, ''); return; }
      if (!cabs.length) return;
      const end = function (e) { const d = devs[e && e.device]; return (d ? d.name : (e && e.device) || '') + (e && e.port ? ' \u00b7 ' + portName(d, e.port) : ''); };
      openTableDialog(ctx, {
        title: r.model + ' (' + cabs.length + ')', key: 'schedules.bom.cables', rows: cabs,
        columns: [
          {key: 'tag', header: 'Tag', value: function (c) { return c.tag || ''; }},
          {key: 'from', header: 'From', value: function (c) { return end(c.from); }},
          {key: 'to', header: 'To', value: function (c) { return end(c.to); }, hideOnMobile: true},
          {key: 'length_m', header: 'Length (m)', align: 'right'},
          {key: 'status', header: 'Status', value: function (c) { return c.status || 'installed'; }, hideOnMobile: true},
        ],
        onRow: function (c) { openSel({type: 'cable', id: c.id}, ''); },
      });
      return;
    }
    const ids = list(r.devices);
    if (ids.length === 1) { openSel({type: 'device', id: ids[0], device: ids[0]}, 'inventory'); return; }
    if (!ids.length) return;
    const all = byId(doc().devices);
    const devRows = ids.map(function (id) { return all[id] || {id: id, name: id}; });
    openTableDialog(ctx, {
      title: (r.model || r.template || 'Devices') + ' (' + devRows.length + ')', key: 'schedules.bom.devices', rows: devRows,
      columns: [
        {key: 'name', header: 'Device', value: function (d) { return d.name || d.id; }},
        {key: 'room', header: 'Room', value: function (d) { return roomName(rooms, d.room); }},
        {key: 'status', header: 'Status', value: function (d) { return d.status || 'installed'; }},
        {key: 'serial', header: 'Serial', value: function (d) { return (d.inventory && d.inventory.serial) || ''; }, hideOnMobile: true},
      ],
      onRow: function (d) { openSel({type: 'device', id: d.id, device: d.id}, 'inventory'); },
    });
  }

  // ------------------------------------------------------------ labels
  function renderLabels() {
    host.innerHTML = '';
    errorEl.hidden = true;
    problemsEl.innerHTML = '';
    totalsEl.hidden = true;
    const count = h('span', {class: 'sch-count', role: 'status'});
    host.appendChild(h('div', {class: 'sch-toolbar sch-labelbar'}, [stateSel, roomSel, btnPrint, labelsCsv, count]));
    const body = h('div', {class: 'sch-labelbody'});
    host.appendChild(body);
    if (ctx.api && ctx.api.scheduleUrl) {
      const url = ctx.api.scheduleUrl(ctx.project, 'labels', Object.assign({format: 'html'}, params()));
      body.appendChild(h('p', null, [h('a', {href: url, target: '_blank', rel: 'noopener', class: 'sch-btn', text: 'Open printable label sheet'})]));
      body.appendChild(h('iframe', {class: 'sch-labels-frame', src: url, title: 'Cable label sheet'}));
      return;
    }
    const labels = localLabels(doc(), room());
    count.textContent = labels.length + ' labels';
    if (!labels.length) { body.appendChild(h('p', {class: 'sch-hint', text: 'No tagged cables yet. Use "Assign tags" on the Cables tab.'})); return; }
    const grid = h('div', {class: 'sch-labels', role: 'list', 'aria-label': 'Cable labels'});
    labels.forEach(function (l) {
      grid.appendChild(h('div', {class: 'sch-label', role: 'listitem'}, [
        h('div', {class: 'sch-label-tag', text: l.tag}), h('div', {class: 'sch-label-line', text: l.line}), h('div', {class: 'sch-label-end', text: l.end}),
      ]));
    });
    body.appendChild(grid);
  }

  // ------------------------------------------------------------- print
  // The DataTable prints only its current page; print every filtered row instead.
  function buildPrintSheet() {
    dropPrintSheet();
    if (!table || S.kind === 'labels') return;
    const st = table.getState();
    const cols = normalizeColumns(columnsFor(S.kind));
    const vis = cols.filter(function (c) { return st.hidden.indexOf(c.key) < 0; });
    const rows = applyState(S.rows, cols, st).rows;
    const tb = h('tbody');
    rows.forEach(function (r) {
      tb.appendChild(h('tr', {class: r.status === 'planned' ? 'sch-planned' : null}, vis.map(function (c) {
        const v = c.key === 'unit_cost' || c.key === 'extended' ? money(r[c.key]) : textOf(c.value(r));
        return h('td', {class: c.align === 'right' ? 'sch-num' : null, text: v});
      })));
    });
    printSheet = h('table', {class: 'sch-table sch-printsheet', hidden: true, 'data-rows': String(rows.length)}, [
      h('caption', {class: 'sch-sr', text: kindLabel(S.kind) + ' schedule'}),
      h('thead', null, [h('tr', null, vis.map(function (c) { return h('th', {scope: 'col', class: c.align === 'right' ? 'sch-num' : null, text: c.header}); }))]),
      tb,
    ]);
    host.appendChild(printSheet);
    host.classList.add('sch-printing');
  }

  function dropPrintSheet() {
    if (printSheet) { printSheet.remove(); printSheet = null; }
    host.classList.remove('sch-printing');
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
    const table2 = h('table', {class: 'sch-table sch-preview'});
    table2.appendChild(h('caption', {class: 'sch-sr', text: 'Proposed cable tags'}));
    table2.appendChild(h('thead', null, [h('tr', null, ['Cable', 'From', 'To', 'Current tag', 'New tag'].map(function (t) { return h('th', {scope: 'col', text: t}); }))]));
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
    table2.appendChild(tb);
    out.appendChild(h('div', {class: 'sch-scroll sch-preview-scroll'}, [table2]));
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

  function editRow(inp) {
    const tr = inp.closest('tr[data-id]');
    return tr ? S.byId[tr.getAttribute('data-id')] : null;
  }

  function onEdit(e) {
    const inp = e.target.closest ? e.target.closest('[data-edit]') : null;
    if (!inp || !host.contains(inp)) return;
    const r = editRow(inp);
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
  listen(tabs, 'click', function (e) {
    const a = e.target.closest('[data-kind]');
    if (!a) return;
    if (ROUTED && (e.button > 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)) return;
    e.preventDefault();
    goTab(a.getAttribute('data-kind'));
  });
  listen(tabs, 'keydown', function (e) {
    const order = KINDS.map(function (k) { return k.key; });
    let i = order.indexOf(S.kind);
    if (e.key === 'ArrowRight') i = (i + 1) % order.length;
    else if (e.key === 'ArrowLeft') i = (i + order.length - 1) % order.length;
    else if (e.key === 'Home') i = 0;
    else if (e.key === 'End') i = order.length - 1;
    else return;
    e.preventDefault();
    goTab(order[i]);
    const t = tabs.querySelector('[data-kind="' + order[i] + '"]');
    if (t) t.focus();
  });
  if (roomSel) listen(roomSel, 'change', function () { S.room = roomSel.value; S.gen++; load(); });
  listen(stateSel, 'change', function () { S.state = stateSel.value; S.gen++; load(); });
  listen(btnTags, 'click', function () { if (tagPanel.hidden) openTags(); else tagPanel.hidden = true; });
  listen(btnBulk, 'click', function () {
    import('./wizard.js').then(function (m) { return m.bulkAdd(ctx, {kind: 'cables', room: store.room}); }).catch(function (err) {
      if (typeof ctx.toast === 'function') ctx.toast((err && err.message) || 'Bulk add is not available.', 'err');
    });
  });
  listen(tagPanel, 'click', function (e) {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    const act = b.getAttribute('data-act');
    if (act === 'preview') preview();
    else if (act === 'confirm') confirmTags();
    else if (act === 'close') { tagPanel.hidden = true; btnTags.focus(); }
  });
  listen(tagPanel, 'keydown', function (e) { if (e.key === 'Escape') { tagPanel.hidden = true; btnTags.focus(); } });
  listen(btnPrint, 'click', function () { if (typeof window.print === 'function') window.print(); });
  listen(labelsCsv, 'click', function (e) { e.preventDefault(); });
  listen(window, 'beforeprint', buildPrintSheet);
  listen(window, 'afterprint', dropPrintSheet);
  listen(host, 'change', onEdit);
  listen(host, 'keydown', function (e) {
    const inp = e.target.closest ? e.target.closest('input[data-edit]') : null;
    if (!inp) return;
    if (e.key === 'Enter') { e.preventDefault(); inp.blur(); }
    if (e.key === 'Escape') {
      e.stopPropagation();
      const r = editRow(inp);
      const k = inp.getAttribute('data-edit');
      if (r) inp.value = r[k] == null ? '' : String(r[k]);
      inp.blur();
    }
  });
  listen(host, 'focusout', function () {
    setTimeout(function () { if (!destroyed && S.pending && !editing()) showData(); }, 0);
  });
  listen(store, 'doc', function (e) {
    const src = e.detail && e.detail.source;
    if (!ctx.api || src === 'load' || src === 'remote') reloadSoon();
  });
  listen(store, 'revision', function () { if (ctx.api) reloadSoon(); });
  listen(store, 'room', function () { S.gen++; load(); });
  listen(store, 'overlay', function () { if (!ctx.api) reloadSoon(); });
  listen(store, 'selection', function () { syncHl(false); });
  listen(store, 'mode', function () { buildTable(); load(); });
  if (ROUTED && typeof ctx.subscribe === 'function') {
    const off = ctx.subscribe('route', function () { if (!destroyed) refreshTabs(); });
    if (typeof off === 'function') offs.push(off);
  }

  activate(S.kind);

  // schedules (no tab, no params) and unknown tabs canonicalise to schedules/cables.
  // A tab-less URL with params (a legacy ?sel=, a remembered ?q=) is left as written.
  if (ROUTED && ((r0.tab && !kindOf(r0.tab)) || (!r0.tab && !Object.keys(r0.query || {}).length))) {
    setTimeout(function () {
      const r = ctx.route;
      if (!destroyed && r && r.view === 'schedules' && !kindOf(r.tab)) ctx.navigateRoute({tab: 'cables'}, {replace: true});
    }, 0);
  }

  return {
    destroy: function () {
      destroyed = true;
      offs.forEach(function (f) { f(); });
      if (reloadTimer) clearTimeout(reloadTimer);
      dropPrintSheet();
      if (table) { table.destroy(); table = null; }
      el.innerHTML = '';
    },
    route: function (r) {
      if (destroyed || !r || r.view !== 'schedules') return;
      const k = kindOf(r.tab);
      if (r.tab && !k) {
        setTimeout(function () { if (!destroyed && ctx.route.view === 'schedules') ctx.navigateRoute({tab: 'cables'}, {replace: true}); }, 0);
        return;
      }
      const kind = k || 'cables';
      if (kind !== S.kind) { activate(kind); return; }
      refreshTabs();
      if (table) { table.readUrl(); dropStaleId(); }
      syncHl(false);
    },
    focus: function (sel) {
      if (!sel) return;
      if (!ROUTED && sel.type === 'cable' && S.kind !== 'cables') activate('cables');
      syncHl(false);
    },
    getState: function () { return {kind: S.kind, room: S.room, state: S.state}; },
    setState: function (s) {
      if (!s) return;
      let changed = false;
      if (s.state && s.state !== S.state) { S.state = s.state; stateSel.value = s.state; changed = true; }
      if (!ROUTED && s.room && s.room !== S.room) { S.room = s.room; roomSel.value = s.room; changed = true; }
      const k = ROUTED ? null : kindOf(s.kind);
      if (changed) S.gen++;
      if (k && k !== S.kind) activate(k);
      else if (changed) load();
    },
    _state: S,
  };
}
