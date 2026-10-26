// Pure helpers behind the wizard and bulk add (docs/ui-audit.md B.2 WIZARD).
// No DOM, storage or timers: storage is injected. Imports only model-core, so
// it loads in Node. The same validators back single add (INV, SCH).
import { STATUSES, ID_RE, newId, indexDoc, canConnect, connectOps, parseLength, portLabel } from './model-core.js';

export const MAX_ROWS = 1000;
export const FORM_PREFIX = 'fathom.ui.form.';

// Field catalogues: key, label and header synonyms (normalised by normHeader).
export const DEVICE_FIELDS = [
  { key: 'name', label: 'Name', required: true, synonyms: ['device', 'device name', 'label', 'title', 'description'] },
  { key: 'id', label: 'Id', synonyms: ['device id', 'identifier', 'key', 'slug'] },
  { key: 'room', label: 'Room', synonyms: ['room id', 'room name', 'space', 'area'] },
  { key: 'status', label: 'Status', synonyms: ['state'] },
  { key: 'kind', label: 'Kind', synonyms: ['type', 'category', 'device type', 'device kind'] },
  { key: 'manufacturer', label: 'Manufacturer', synonyms: ['make', 'brand', 'mfr', 'mfg', 'maker'] },
  { key: 'model', label: 'Model', synonyms: ['model number', 'model no', 'part number', 'part no', 'part'] },
  { key: 'serial', label: 'Serial', synonyms: ['serial number', 'serial no', 'serial num', 's n', 'sn'] },
  { key: 'asset_tag', label: 'Asset tag', synonyms: ['asset', 'asset number', 'asset no', 'asset id', 'tag'] },
  { key: 'note', label: 'Note', synonyms: ['notes', 'comment', 'comments', 'remarks'] },
];

export const CABLE_FIELDS = [
  { key: 'from', label: 'From', required: true, synonyms: ['from device', 'source', 'source device', 'a end', 'start', 'origin'] },
  { key: 'from_port', label: 'From port', synonyms: ['source port', 'output', 'out port', 'out'] },
  { key: 'to', label: 'To', required: true, synonyms: ['to device', 'destination', 'destination device', 'dest', 'target', 'b end', 'end'] },
  { key: 'to_port', label: 'To port', synonyms: ['destination port', 'dest port', 'input', 'in port', 'in'] },
  { key: 'tag', label: 'Tag', synonyms: ['cable', 'cable id', 'cable tag', 'cable number', 'cable no', 'number', 'no'] },
  { key: 'medium', label: 'Medium', synonyms: ['media', 'signal type', 'format'] },
  { key: 'type', label: 'Type', synonyms: ['cable type', 'connector'] },
  { key: 'length_m', label: 'Length', synonyms: ['length', 'length m', 'len', 'metres', 'meters'] },
  { key: 'color', label: 'Colour', synonyms: ['colour', 'jacket'] },
  { key: 'status', label: 'Status', synonyms: ['state'] },
  { key: 'label', label: 'Label', synonyms: ['signal', 'description'] },
  { key: 'repatch', label: 'Repatch', synonyms: ['replace', 'move'] },
];

export function fieldsFor(kind) {
  return kind === 'cables' ? CABLE_FIELDS : DEVICE_FIELDS;
}

function str(v) {
  return v === undefined || v === null ? '' : String(v).trim();
}

function hasKeys(o) {
  if (!o || typeof o !== 'object') return false;
  return Object.keys(o).some(function (k) { return !!o[k]; });
}

// ------------------------------------------------------------ parsing

const DELIMS = ['\t', ';', ','];

// Quote-aware split of the whole text into records (quoted fields may hold
// delimiters, doubled quotes and newlines). Fields are trimmed; blank records
// (only whitespace and delimiters) are dropped.
export function splitRecords(text, delim) {
  const s = String(text == null ? '' : text);
  const out = [];
  let rec = [];
  let field = '';
  let quoted = false;
  let wasQuoted = false;
  let i = 0;
  function endField() {
    rec.push(wasQuoted ? field : field.trim());
    field = '';
    wasQuoted = false;
  }
  function endRecord() {
    endField();
    if (rec.some(function (f) { return f !== ''; })) out.push(rec);
    rec = [];
  }
  while (i < s.length) {
    const c = s.charAt(i);
    if (quoted) {
      if (c === '"') {
        if (s.charAt(i + 1) === '"') { field += '"'; i += 2; continue; }
        quoted = false;
        i++;
        continue;
      }
      field += c;
      i++;
      continue;
    }
    if (c === '"' && field.trim() === '') { quoted = true; wasQuoted = true; field = ''; i++; continue; }
    if (c === delim) { endField(); i++; continue; }
    if (c === '\r' || c === '\n') {
      endRecord();
      if (c === '\r' && s.charAt(i + 1) === '\n') i++;
      i++;
      continue;
    }
    if (wasQuoted) { i++; continue; }  // junk after a closing quote is dropped
    field += c;
    i++;
  }
  if (field !== '' || rec.length || wasQuoted) endRecord();
  return out;
}

export function detectDelimiter(text) {
  let best = null;
  DELIMS.forEach(function (d, order) {
    const recs = splitRecords(text, d).slice(0, 50);
    if (!recs.length) return;
    const n = recs[0].length;
    if (n < 2) return;
    const same = recs.filter(function (r) { return r.length === n; }).length / recs.length;
    const score = [same, n, -order];
    if (!best || score[0] > best.score[0] || (score[0] === best.score[0] && (score[1] > best.score[1] || (score[1] === best.score[1] && score[2] > best.score[2])))) {
      best = { d: d, score: score };
    }
  });
  if (best) return best.d;
  return String(text || '').indexOf('\t') >= 0 ? '\t' : ',';
}

// parsePasted(text, {header: true, delimiter}) -> {delimiter, header, rows}.
// The first non-empty record is the header unless header === false, in which
// case columns are named "Column 1"... Rows longer than the header extend it.
export function parsePasted(text, opts) {
  opts = opts || {};
  const delimiter = opts.delimiter || detectDelimiter(text);
  const recs = splitRecords(text, delimiter);
  let header = [];
  let rows = recs;
  if (opts.header !== false && recs.length) {
    header = recs[0].slice();
    rows = recs.slice(1);
  }
  let width = header.length;
  rows.forEach(function (r) { if (r.length > width) width = r.length; });
  for (let i = header.length; i < width; i++) header.push('Column ' + (i + 1));
  return { delimiter: delimiter, header: header, rows: rows };
}

// ------------------------------------------------------------ column mapping

export function normHeader(text) {
  return str(text).toLowerCase().replace(/[_.#:()\[\]/\\-]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function fieldList(fields) {
  return (fields || []).map(function (f) {
    if (typeof f === 'string') {
      const known = DEVICE_FIELDS.concat(CABLE_FIELDS).filter(function (x) { return x.key === f; })[0];
      return { key: f, label: known ? known.label : f, synonyms: known ? known.synonyms : [], required: !!(known && known.required) };
    }
    return { key: f.key, label: f.label || f.key, synonyms: f.synonyms || [], required: !!f.required };
  });
}

// guessMapping(header, fields) -> array aligned with header: a field key or null.
// Exact key or label first (each field used once, first column wins), then synonyms.
export function guessMapping(header, fields) {
  const list = fieldList(fields);
  const norm = (header || []).map(normHeader);
  const out = norm.map(function () { return null; });
  const used = {};
  function pass(match) {
    norm.forEach(function (h, i) {
      if (out[i] !== null || !h) return;
      for (const f of list) {
        if (used[f.key]) continue;
        if (match(h, f)) { out[i] = f.key; used[f.key] = true; return; }
      }
    });
  }
  pass(function (h, f) { return h === normHeader(f.key) || h === normHeader(f.label); });
  pass(function (h, f) { return f.synonyms.some(function (s) { return normHeader(s) === h; }); });
  return out;
}

// A header row is likely when at least one column maps to a known field.
export function looksLikeHeader(header, fields) {
  return guessMapping(header, fields).some(function (k) { return k !== null; });
}

// Fields mapped more than once: {columnIndex: message} for the later columns.
export function mappingErrors(mapping, fields, header) {
  const list = fieldList(fields);
  const errs = {};
  const first = {};
  (mapping || []).forEach(function (k, i) {
    if (!k) return;
    if (first[k] !== undefined) {
      const f = list.filter(function (x) { return x.key === k; })[0];
      errs['col-' + i] = (f ? f.label : k) + ' is already mapped to “' + ((header || [])[first[k]] || 'column ' + (first[k] + 1)) + '”';
    } else first[k] = i;
  });
  list.forEach(function (f) {
    if (f.required && first[f.key] === undefined) errs.mapping = errs.mapping ? errs.mapping + '; ' + 'map a column to ' + f.label : 'Map a column to ' + f.label;
  });
  return errs;
}

// rowObject(cells, mapping) -> {field: value}; the first non-empty column wins.
export function rowObject(cells, mapping) {
  const o = {};
  (mapping || []).forEach(function (k, i) {
    if (!k) return;
    const v = str((cells || [])[i]);
    if (v !== '' && (o[k] === undefined || o[k] === '')) o[k] = v;
    else if (o[k] === undefined) o[k] = v;
  });
  return o;
}

// ------------------------------------------------------------ lookups

function lower(s) {
  return str(s).toLowerCase();
}

export function resolveRoom(doc, text) {
  const t = str(text);
  if (!t) return '';
  const rooms = (doc && doc.rooms) || [];
  for (const r of rooms) if (r.id === t) return r.id;
  const l = t.toLowerCase();
  const hits = rooms.filter(function (r) { return lower(r.id) === l || lower(r.name) === l || (r.code && lower(r.code) === l); });
  return hits.length === 1 ? hits[0].id : null;
}

export function resolveStatus(text, vocab) {
  const t = lower(text);
  if (!t) return '';
  const list = (vocab && Array.isArray(vocab.statuses) && vocab.statuses.length) ? vocab.statuses : STATUSES;
  return list.indexOf(t) >= 0 ? t : null;
}

// Kind key from a key or label; without a vocab any non-empty text is kept.
export function resolveKind(text, vocab) {
  const t = str(text);
  if (!t) return '';
  const kinds = vocab && vocab.kinds;
  if (!kinds) return t;
  if (kinds[t]) return t;
  const l = t.toLowerCase();
  const keys = Object.keys(kinds);
  for (const k of keys) if (k.toLowerCase() === l || k.toLowerCase() === l.replace(/[\s-]+/g, '_')) return k;
  for (const k of keys) if (lower(kinds[k].label) === l) return k;
  return null;
}

function deviceMatches(doc, text) {
  const t = str(text);
  const devs = (doc && doc.devices) || [];
  const byId = devs.filter(function (d) { return d.id === t; });
  if (byId.length) return byId;
  const l = t.toLowerCase();
  return devs.filter(function (d) { return lower(d.id) === l || lower(d.name) === l; });
}

function portMatches(device, text) {
  const t = str(text);
  const ports = (device && device.ports) || [];
  const byId = ports.filter(function (p) { return p.id === t; });
  if (byId.length) return byId;
  const l = t.toLowerCase();
  const exact = ports.filter(function (p) { return lower(p.id) === l || lower(p.name) === l; });
  if (exact.length) return exact;
  return ports.filter(function (p) { return p.label && lower(p.label) === l; });
}

// resolveEndpoint(doc, value, portText) -> {device, port} or {error}.
// value is "device:port", a device id or name, or {device, port}; device and
// port also match by name (and port label) case-insensitively when unique.
export function resolveEndpoint(doc, value, portText) {
  let devText;
  let port = str(portText);
  if (value && typeof value === 'object') {
    devText = str(value.device);
    if (!port) port = str(value.port);
  } else {
    devText = str(value);
  }
  if (!devText) return { error: 'required' };
  let cands = [];
  if (!value || typeof value !== 'object') {
    // whole text as a device first, then each ':' split (device names may hold ':')
    if (!port) {
      const whole = deviceMatches(doc, devText);
      if (whole.length === 1) return endpointOn(whole[0], '', devText);
      for (let i = devText.indexOf(':'); i >= 0; i = devText.indexOf(':', i + 1)) {
        cands.push({ dev: devText.slice(0, i), port: devText.slice(i + 1) });
      }
      if (!cands.length) cands.push({ dev: devText, port: '' });
    } else {
      cands.push({ dev: devText, port: port });
    }
  } else {
    cands.push({ dev: devText, port: port });
  }
  let firstErr = null;
  for (const c of cands) {
    const ds = deviceMatches(doc, c.dev);
    if (ds.length > 1) { firstErr = firstErr || 'More than one device is called “' + c.dev + '”; use its id'; continue; }
    if (!ds.length) { firstErr = firstErr || 'Unknown device “' + c.dev + '”'; continue; }
    const r = endpointOn(ds[0], c.port, devText);
    if (!r.error) return r;
    firstErr = r.error;
  }
  return { error: firstErr || 'Unknown device “' + devText + '”' };
}

function endpointOn(device, portText, original) {
  const p = str(portText);
  if (!p) return { device: device.id, port: null };
  const ps = portMatches(device, p);
  if (ps.length > 1) return { error: 'More than one port on ' + (device.name || device.id) + ' matches “' + p + '”; use its id' };
  if (!ps.length) return { error: 'Unknown port “' + p + '” on ' + (device.name || device.id) };
  return { device: device.id, port: ps[0].id };
}

function truthy(v) {
  if (v === true) return true;
  const t = lower(v);
  return t === 'true' || t === 'yes' || t === 'y' || t === '1' || t === 'x';
}

// ------------------------------------------------------------ validators

function existingDeviceIds(doc) {
  const set = {};
  ((doc && doc.devices) || []).forEach(function (d) { if (d && d.id) set[d.id] = true; });
  ((doc && doc.rooms) || []).forEach(function (r) {
    ((r.flow && r.flow.extra_cards) || []).forEach(function (x) { if (x && x.id) set[x.id] = true; });
  });
  return set;
}

// validateDeviceRow(doc, row, {vocab, room, taken}) -> {field: message}; {} when valid.
// `taken` holds ids claimed by earlier rows of the same batch.
export function validateDeviceRow(doc, row, opts) {
  opts = opts || {};
  row = row || {};
  const e = {};
  if (!str(row.name)) e.name = 'Name is required';
  const id = str(row.id);
  if (id) {
    if (!ID_RE.test(id)) e.id = 'Ids use letters, digits, “.”, “_” and “-” (no spaces)';
    else if (existingDeviceIds(doc)[id]) e.id = 'A device with id “' + id + '” already exists';
    else if (opts.taken && opts.taken[id]) e.id = 'Id “' + id + '” is used by another pasted row';
  }
  if (str(row.room)) {
    if (resolveRoom(doc, row.room) === null) e.room = 'Unknown room “' + str(row.room) + '”';
  } else if (opts.room && resolveRoom(doc, opts.room) === null) {
    e.room = 'Unknown room “' + opts.room + '”';
  }
  if (str(row.status) && resolveStatus(row.status, opts.vocab) === null) {
    e.status = 'Status must be one of ' + ((opts.vocab && opts.vocab.statuses) || STATUSES).join(', ');
  }
  if (str(row.kind) && resolveKind(row.kind, opts.vocab) === null) e.kind = 'Unknown kind “' + str(row.kind) + '”';
  return e;
}

// Non-blocking notes for a device row.
export function deviceRowWarnings(doc, row) {
  const w = {};
  const n = lower(row && row.name);
  if (n && ((doc && doc.devices) || []).some(function (d) { return lower(d.name) === n; })) w.name = 'A device with this name already exists';
  return w;
}

function endpointOf(doc, row, end) {
  return resolveEndpoint(doc, row[end], row[end + '_port']);
}

// validateCableRow(doc, row, {vocab, repatch, used}) -> {field: message}; {} when valid.
// Endpoints are "device:port" text or {device, port}. A port that already has a
// cable is rejected unless row.repatch (or opts.repatch); `used` maps port refs
// claimed by earlier rows of the same batch to their row number.
export function validateCableRow(doc, row, opts) {
  opts = opts || {};
  row = row || {};
  const e = {};
  const ends = {};
  const idx = indexDoc(doc);
  const repatch = truthy(row.repatch) || !!opts.repatch;
  ['from', 'to'].forEach(function (end) {
    const label = end === 'from' ? 'From' : 'To';
    const r = endpointOf(doc, row, end);
    if (r.error === 'required') { e[end] = label + ' is required'; return; }
    if (r.error) { e[end] = r.error; return; }
    ends[end] = r;
    if (!r.port) return;
    const ref = r.device + ':' + r.port;
    const on = idx.cablesByPort[ref] || [];
    if (on.length && !repatch) {
      const c = on[0];
      e[end] = portName(doc, r) + ' is already patched' + (c.tag ? ' (cable ' + c.tag + ')' : '') + '; set Repatch to replace it';
    } else if (opts.used && opts.used[ref] !== undefined) {
      e[end] = portName(doc, r) + ' is used by row ' + opts.used[ref];
    }
  });
  if (ends.from && ends.to && !e.from && !e.to) {
    const r = canConnect(doc, ends.from, ends.to, opts.vocab);
    if (r.level === 'error') {
      const fp = findPort(doc, ends.from);
      const field = r.code === 'bad_direction' ? (fp && fp.dir === 'in' ? 'from' : 'to') : 'to';
      e[field] = r.reason;
    }
  }
  if (str(row.medium) && opts.vocab && opts.vocab.media && !opts.vocab.media[str(row.medium)]) e.medium = 'Unknown medium “' + str(row.medium) + '”';
  if (str(row.length_m) && parseLength(row.length_m, doc && doc.settings && doc.settings.units) === null) e.length_m = 'Length must be a number, e.g. 15 or 15 m';
  if (str(row.status) && resolveStatus(row.status, opts.vocab) === null) e.status = 'Status must be one of ' + STATUSES.join(', ');
  return e;
}

function findPort(doc, ep) {
  const d = ((doc && doc.devices) || []).filter(function (x) { return x.id === ep.device; })[0];
  return d ? ((d.ports || []).filter(function (p) { return p.id === ep.port; })[0] || null) : null;
}

function portName(doc, ep) {
  const d = ((doc && doc.devices) || []).filter(function (x) { return x.id === ep.device; })[0];
  const p = findPort(doc, ep);
  return (p ? portLabel(p) : ep.port) + ' on ' + ((d && d.name) || ep.device);
}

// Non-blocking notes for a cable row (media that may not match, duplicate tags).
export function cableRowWarnings(doc, row, opts) {
  opts = opts || {};
  const w = {};
  const f = endpointOf(doc, row || {}, 'from');
  const t = endpointOf(doc, row || {}, 'to');
  if (!f.error && !t.error) {
    const r = canConnect(doc, f, t, opts.vocab);
    if (r.level === 'warn' && r.code !== 'port_overuse') w.to = r.reason;
  }
  const tag = str(row && row.tag);
  if (tag && ((doc && doc.cables) || []).some(function (c) { return c.tag === tag; })) w.tag = 'Tag ' + tag + ' is already used';
  return w;
}

// validateRows(doc, kind, rows, opts) -> [{errors, warnings}] aligned with rows,
// including duplicates inside the batch (ids, ports, tags).
export function validateRows(doc, kind, rows, opts) {
  opts = opts || {};
  const out = [];
  if (kind === 'cables') {
    const used = {};
    const tags = {};
    (rows || []).forEach(function (row, i) {
      const errors = validateCableRow(doc, row, { vocab: opts.vocab, repatch: opts.repatch, used: used });
      const warnings = cableRowWarnings(doc, row, opts);
      const tag = str(row.tag);
      if (tag) {
        if (tags[tag] !== undefined && !warnings.tag) warnings.tag = 'Tag ' + tag + ' repeats row ' + tags[tag];
        else tags[tag] = i + 1;
      }
      if (!hasKeys(errors)) {
        ['from', 'to'].forEach(function (end) {
          const r = endpointOf(doc, row, end);
          if (r.port) used[r.device + ':' + r.port] = i + 1;
        });
      }
      out.push({ errors: errors, warnings: warnings });
    });
    return out;
  }
  const taken = {};
  (rows || []).forEach(function (row) {
    const errors = validateDeviceRow(doc, row, { vocab: opts.vocab, room: opts.room, taken: taken });
    const id = str(row.id);
    if (id && !errors.id) taken[id] = true;
    out.push({ errors: errors, warnings: deviceRowWarnings(doc, row) });
  });
  return out;
}

// ------------------------------------------------------------ ops

// bulkDeviceOps(doc, rows, {room, vocab}) -> [put ops], one per row with a name.
// Ops are shaped like duplicateDeviceOps output. A row's own valid, unused id is
// kept; otherwise the id is the name's slug made unique (-2, -3, ...). A row's
// room (id or name) beats opts.room; serial and asset tag go under inventory.
export function bulkDeviceOps(doc, rows, opts) {
  opts = opts || {};
  const taken = existingDeviceIds(doc);
  const ops = [];
  (rows || []).forEach(function (row) {
    row = row || {};
    const name = str(row.name);
    if (!name) return;
    let id = str(row.id);
    if (!id || !ID_RE.test(id) || taken[id]) id = newId(null, Object.keys(taken), name);
    taken[id] = true;
    const kind = resolveKind(row.kind, opts.vocab) || 'other';
    const dev = { id: id, name: name, kind: kind };
    const room = str(row.room) ? resolveRoom(doc, row.room) : (opts.room === undefined || opts.room === null ? null : opts.room);
    if (room !== null && room !== undefined) dev.room = room;
    if (str(row.manufacturer)) dev.manufacturer = str(row.manufacturer);
    if (str(row.model)) dev.model = str(row.model);
    const status = resolveStatus(row.status, opts.vocab);
    if (status) dev.status = status;
    if (str(row.note)) dev.note = str(row.note);
    const inv = {};
    if (str(row.serial)) inv.serial = str(row.serial);
    if (str(row.asset_tag)) inv.asset_tag = str(row.asset_tag);
    if (Object.keys(inv).length) dev.inventory = inv;
    dev.ports = [];
    ops.push({ op: 'put', coll: 'devices', id: id, value: dev });
  });
  return ops;
}

// bulkCableOps(doc, rows, {vocab, repatch}) -> ops: one cable put per resolvable
// row (built with connectOps), preceded by dels of the cables a repatch row
// replaces on its ports.
export function bulkCableOps(doc, rows, opts) {
  opts = opts || {};
  const idx = indexDoc(doc);
  const takenIds = ((doc && doc.cables) || []).map(function (c) { return c.id; });
  const units = doc && doc.settings && doc.settings.units;
  const dels = [];
  const deleted = {};
  const puts = [];
  (rows || []).forEach(function (row) {
    row = row || {};
    const from = endpointOf(doc, row, 'from');
    const to = endpointOf(doc, row, 'to');
    if (from.error || to.error) return;
    if (truthy(row.repatch) || opts.repatch) {
      [from, to].forEach(function (ep) {
        if (!ep.port) return;
        (idx.cablesByPort[ep.device + ':' + ep.port] || []).forEach(function (c) {
          if (deleted[c.id]) return;
          deleted[c.id] = true;
          dels.push({ op: 'del', coll: 'cables', id: c.id });
        });
      });
    }
    const id = newId('c', takenIds);
    takenIds.push(id);
    const o = { id: id };
    if (str(row.tag)) o.tag = str(row.tag);
    if (str(row.type)) o.type = str(row.type);
    if (str(row.medium)) o.medium = str(row.medium);
    const len = str(row.length_m) ? parseLength(row.length_m, units) : null;
    if (len !== null) o.length_m = len;
    const status = resolveStatus(row.status, opts.vocab);
    if (status) o.status = status;
    const op = connectOps(doc, { device: from.device, port: from.port }, { device: to.device, port: to.port }, o, opts.vocab)[0];
    if (str(row.color)) op.value.color = str(row.color);
    if (str(row.label)) op.value.label = str(row.label);
    puts.push(op);
  });
  return dels.concat(puts);
}

// Cable ids a set of ops would remove (repatch).
export function replacedCables(ops) {
  return (ops || []).filter(function (o) { return o.op === 'del' && o.coll === 'cables'; }).map(function (o) { return o.id; });
}

// ------------------------------------------------------------ steps and text

// canAdvance(step, errors): errors is {field: msg}, a list of such objects, or nothing.
export function canAdvance(step, errors) {
  if (!errors) return true;
  if (Array.isArray(errors)) return errors.every(function (e) { return !(e && (typeof e !== 'object' || hasKeys(e))); });
  if (typeof errors === 'object') return !hasKeys(errors);
  return !errors;
}

export function plural(n, one, many) {
  return n + ' ' + (n === 1 ? one : (many || one + 's'));
}

// "Add 18 devices to Main Auditorium", "Add 1 cable".
export function reviewText(kind, count, roomName) {
  const noun = kind === 'cables' ? plural(count, 'cable') : plural(count, 'device');
  if (kind === 'cables') return 'Add ' + noun + (roomName ? ' in ' + roomName : '');
  return 'Add ' + noun + (roomName ? ' to ' + roomName : roomName === '' ? ' to shared inventory' : '');
}

export function commitLabel(kind, count) {
  return 'Bulk add ' + (kind === 'cables' ? plural(count, 'cable') : plural(count, 'device'));
}

// Route patch for the result link: one device opens its page; otherwise the
// devices landing or the cables schedule, highlighting the first new row and
// filtering the id column to the new rows (D1 `f.<col>` grammar) when few.
export function resultRoute(kind, ids) {
  ids = ids || [];
  const query = {};
  if (ids.length) query.hl = ids[0];
  if (ids.length > 1 && ids.length <= 50) query['f.id'] = ids.map(escFilter).join('|');
  if (kind === 'cables') return { view: 'schedules', tab: 'cables', query: query };
  if (ids.length === 1) return { view: 'devices', id: ids[0], query: {} };
  return { view: 'devices', query: query };
}

function escFilter(v) {
  return String(v).replace(/[\\|~]/g, function (c) { return '\\' + c; });
}

// ------------------------------------------------------------ remembered form values (D8)

export function loadForm(storage, key) {
  if (!storage || !key) return null;
  try {
    const raw = storage.getItem(FORM_PREFIX + key);
    if (!raw) return null;
    const v = JSON.parse(raw);
    return v && typeof v === 'object' && !Array.isArray(v) ? v : null;
  } catch (e) {
    return null;
  }
}

export function saveForm(storage, key, data) {
  if (!storage || !key) return false;
  try {
    storage.setItem(FORM_PREFIX + key, JSON.stringify(data || {}));
    return true;
  } catch (e) {
    return false;
  }
}

// Apply remembered {normHeader: field} choices over a guessed mapping.
export function applyRemembered(header, mapping, remembered, fields) {
  const keys = fieldList(fields).map(function (f) { return f.key; });
  const out = (mapping || []).slice();
  if (!remembered || typeof remembered !== 'object') return out;
  (header || []).forEach(function (hd, i) {
    const k = normHeader(hd);
    if (!Object.prototype.hasOwnProperty.call(remembered, k)) return;
    const v = remembered[k];
    if (v === null || keys.indexOf(v) >= 0) {
      for (let j = 0; j < out.length; j++) if (j !== i && v !== null && out[j] === v) out[j] = null;
      out[i] = v;
    }
  });
  return out;
}

export function rememberMapping(header, mapping) {
  const o = {};
  (header || []).forEach(function (hd, i) {
    const k = normHeader(hd);
    if (k && !/^column \d+$/.test(k)) o[k] = (mapping || [])[i] || null;
  });
  return o;
}
