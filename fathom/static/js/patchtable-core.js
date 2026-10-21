// Patch table core (§6.6): PatchBlock rows from doc + overlay, filters, CSV,
// cell edits -> ops. Pure; imports in Node.

import { devicePorts, disciplineOf, mediumDiscipline, portLabel, renameOps, connectOps, repatchOps, disconnectOps, stateIncludes } from './model-core.js';

export const PATCH_COLUMNS = [
  { key: 'room', label: 'Room' },
  { key: 'device', label: 'Device' },
  { key: 'section', label: 'Section' },
  { key: 'dir', label: 'Dir' },
  { key: 'port', label: 'Port' },
  { key: 'label', label: 'Label' },
  { key: 'peer_device', label: 'Peer device' },
  { key: 'peer_port', label: 'Peer port' },
  { key: 'cable_tag', label: 'Cable' },
  { key: 'medium', label: 'Medium' },
  { key: 'source', label: 'Source' },
];

function shortOf(medium, vocab) {
  const m = vocab && vocab.media ? vocab.media[medium] : null;
  return (m && m.short) || String(medium || 'OTH').toUpperCase();
}

function dirWord(dir) {
  return dir === 'in' ? 'In' : dir === 'out' ? 'Out' : 'I/O';
}

function normFilter(filter) {
  const f = filter || {};
  let discs = [];
  if (Array.isArray(f.disciplines)) discs = f.disciplines.filter(Boolean);
  else if (f.discipline) discs = String(f.discipline).split(',').filter(Boolean);
  return {
    room: f.room === undefined || f.room === null ? '*' : f.room,
    discs: discs,
    query: String(f.query || f.text || '').trim().toLowerCase(),
    onlyPatched: !!(f.onlyPatched || f.only_patched),
    includeOverlay: !!(f.includeOverlay || f.include_overlay),
    state: f.state || 'all',
  };
}

function emptyRow(port) {
  return {
    port: port ? port.id : null,
    port_name: port ? (port.name || port.id) : null,
    label: port && port.label ? port.label : null,
    peer_device: null, peer_name: null, peer_port: null, peer_port_name: null, peer_label: null,
    cable: null, tag: null,
    medium: port ? (port.medium || null) : null,
    source: null,
  };
}

export function buildPatchTable(doc, overlay, vocab, filter) {
  const f = normFilter(filter);
  const devices = (doc && doc.devices) || [];
  const byId = {};
  devices.forEach(function (d) { byId[d.id] = d; });
  const cables = (doc && doc.cables) || [];
  const routes = (f.includeOverlay && overlay && Array.isArray(overlay.routes)) ? overlay.routes : [];
  const blocks = [];
  devices.forEach(function (d) {
    if (d.auto) return;
    if (f.room !== '*' && (d.room || '') !== f.room) return;
    if (!stateIncludes(d.status, f.state)) return;
    if (f.discs.length && f.discs.indexOf(disciplineOf(d, vocab)) < 0) {
      const any = devicePorts(d).some(function (p) { return f.discs.indexOf(mediumDiscipline(p.medium, vocab)) >= 0; });
      if (!any) return;
    }
    if (f.query) {
      const hay = [d.id, d.name, d.manufacturer, d.model, d.sub, d.code].concat(d.aliases || []).filter(Boolean).join(' ').toLowerCase();
      if (hay.indexOf(f.query) < 0) return;
    }
    const portsById = {};
    devicePorts(d).forEach(function (p) { portsById[p.id] = p; });
    function peerOf(c, mine) {
      const other = mine === 'from' ? c.to : c.from;
      const pd = byId[other && other.device];
      const pp = pd && other.port ? (devicePorts(pd).filter(function (x) { return x.id === other.port; })[0] || null) : null;
      return {
        peer_device: other ? other.device : null,
        peer_name: pd ? (pd.name || pd.id) : (other ? other.device : null),
        peer_port: other && other.port ? other.port : null,
        peer_port_name: pp ? (pp.name || pp.id) : (other && other.port ? other.port : null),
        peer_label: pp && pp.label ? pp.label : null,
      };
    }
    function cableRows(port) {
      const rows = [];
      cables.forEach(function (c) {
        if (c.auto) return;
        let mine = null;
        if (c.from && c.from.device === d.id && (c.from.port || null) === port.id) mine = 'from';
        else if (c.to && c.to.device === d.id && (c.to.port || null) === port.id) mine = 'to';
        if (!mine) return;
        const r = emptyRow(port);
        Object.assign(r, peerOf(c, mine));
        r.cable = c.id;
        r.tag = c.tag || null;
        r.medium = c.medium || port.medium || null;
        r.source = 'cable';
        rows.push(r);
      });
      return rows;
    }
    function routeRows(port) {
      const rows = [];
      routes.forEach(function (rt) {
        let mine = null;
        if (rt.from && rt.from.device === d.id && (rt.from.port || null) === port.id) mine = 'from';
        else if (rt.to && rt.to.device === d.id && (rt.to.port || null) === port.id) mine = 'to';
        if (!mine) return;
        const other = mine === 'from' ? rt.to : rt.from;
        const pd = byId[other && other.device];
        const r = emptyRow(port);
        r.peer_device = other ? other.device : null;
        r.peer_name = pd ? (pd.name || pd.id) : (other ? other.device : null);
        r.peer_port = other && other.port ? other.port : null;
        r.peer_port_name = (other && (other.channel || other.port)) || null;
        r.peer_label = rt.label || null;
        r.medium = rt.medium || port.medium || null;
        r.source = rt.kind || 'import';
        rows.push(r);
      });
      return rows;
    }
    const sections = [];
    let cur = null;
    devicePorts(d).forEach(function (p) {
      const title = p.group || (shortOf(p.medium, vocab) + ' ' + dirWord(p.dir));
      if (!cur || cur._key !== title) {
        cur = { _key: title, title: title, dir: p.dir || 'io', medium: p.medium || null, rows: [] };
        sections.push(cur);
      } else if (cur.dir !== (p.dir || 'io')) {
        cur.dir = 'io';
      }
      let rows = cableRows(p);
      if (!rows.length) rows = [emptyRow(p)];
      rows = rows.concat(routeRows(p));
      rows.forEach(function (r) { cur.rows.push(r); });
    });
    // device-level cable endpoints
    const devRows = [];
    let dirs = {};
    cables.forEach(function (c) {
      if (c.auto) return;
      let mine = null;
      if (c.from && c.from.device === d.id && !c.from.port) mine = 'from';
      else if (c.to && c.to.device === d.id && !c.to.port) mine = 'to';
      if (!mine) return;
      dirs[mine === 'from' ? 'out' : 'in'] = true;
      const r = emptyRow(null);
      Object.assign(r, peerOf(c, mine));
      r.cable = c.id;
      r.tag = c.tag || null;
      r.medium = c.medium || null;
      r.source = 'cable';
      devRows.push(r);
    });
    if (devRows.length) {
      const dd = dirs.in && dirs.out ? 'io' : dirs.in ? 'in' : 'out';
      sections.push({ _key: '\u0000device', title: 'Device', dir: dd, medium: devRows[0].medium, rows: devRows });
    }
    let out = sections.map(function (s) { return { title: s.title, dir: s.dir, medium: s.medium, rows: s.rows }; });
    if (f.onlyPatched) {
      out = out.map(function (s) { return { title: s.title, dir: s.dir, medium: s.medium, rows: s.rows.filter(function (r) { return !!r.source; }) }; }).filter(function (s) { return s.rows.length; });
      if (!out.length) return;
    }
    blocks.push({
      device: d.id,
      name: d.name || d.id,
      model: ((d.manufacturer || '') + ' ' + (d.model || '')).trim() || d.sub || '',
      room: d.room || '',
      discipline: disciplineOf(d, vocab),
      kind: d.kind || 'other',
      sections: out,
    });
  });
  return blocks;
}

function csvField(v) {
  const s = v === null || v === undefined ? '' : String(v);
  if (/[",\r\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
  return s;
}

export function patchTableRows(blocks) {
  const rows = [];
  (blocks || []).forEach(function (b) {
    (b.sections || []).forEach(function (s) {
      (s.rows || []).forEach(function (r) {
        rows.push({
          room: b.room || '',
          device: b.name || '',
          section: s.title || '',
          dir: s.dir || '',
          port: r.port ? (r.label || r.port_name || r.port) : '',
          label: r.label || '',
          peer_device: r.peer_name || '',
          peer_port: r.peer_port ? (r.peer_label || r.peer_port_name || r.peer_port) : (r.peer_port_name || ''),
          cable_tag: r.tag || '',
          medium: r.medium || '',
          source: r.source || '',
        });
      });
    });
  });
  return rows;
}

export function patchTableCsv(blocks) {
  const lines = [PATCH_COLUMNS.map(function (c) { return csvField(c.label); }).join(',')];
  patchTableRows(blocks).forEach(function (r) {
    lines.push(PATCH_COLUMNS.map(function (c) { return csvField(r[c.key]); }).join(','));
  });
  return lines.join('\r\n') + '\r\n';
}

export function patchCellOps(doc, rowRef, field, value) {
  rowRef = rowRef || {};
  if (field === 'label') {
    if (!rowRef.port) return [];
    return renameOps(doc, { coll: 'devices', id: rowRef.device, port: rowRef.port }, value);
  }
  if (field === 'clear') {
    return rowRef.cable ? disconnectOps(doc, rowRef.cable) : [];
  }
  if (field === 'peer') {
    if (!value || !value.device) return [];
    if (rowRef.cable) {
      const c = ((doc && doc.cables) || []).filter(function (x) { return x.id === rowRef.cable; })[0];
      if (!c) return [];
      const mineFrom = c.from && c.from.device === rowRef.device && (c.from.port || null) === (rowRef.port || null);
      return repatchOps(doc, rowRef.cable, mineFrom ? 'to' : 'from', value);
    }
    const dev = ((doc && doc.devices) || []).filter(function (x) { return x.id === rowRef.device; })[0];
    const port = dev ? devicePorts(dev).filter(function (p) { return p.id === rowRef.port; })[0] : null;
    const here = { device: rowRef.device, port: rowRef.port || null };
    if (port && port.dir === 'in') return connectOps(doc, value, here, {});
    return connectOps(doc, here, value, {});
  }
  return [];
}

export function blockPortCount(block) {
  let n = 0;
  (block.sections || []).forEach(function (s) { n += s.rows.length; });
  return n;
}

export { portLabel };
