// Console channels (SPEC §4.3.17, §6.8.6): pure helpers shared by the inspector,
// the trace drawer and the public device page. No DOM, ES2018.
//
// A device carries `channels` (input channels, buses, DCAs, racks) and
// `channel_links` (the edges between them and the device's ports). Importers
// contribute the same shape under `overlay.channels[dev]`; `effectiveChannels`
// picks the persisted set when the device has one, else the overlay's.

export const SHORT = { input: 'CH', stereo_input: 'ST IN', mix: 'MIX', aux: 'AUX', group: 'GRP', matrix: 'MATRIX', stereo: 'ST', mono: 'MONO',
  dca: 'DCA', mute_group: 'MUTE', monitor: 'MONITOR', cue: 'CUE', talkback: 'TALKBACK', oscillator: 'OSC' };
const ORDER = { input: 0, stereo_input: 1, mix: 2, aux: 2, group: 3, matrix: 4, stereo: 5, mono: 6, dca: 7, mute_group: 8, rack: 9, monitor: 10, cue: 11, talkback: 12, oscillator: 13 };
export const GROUPS = [
  { id: 'inputs', label: 'Inputs', kinds: ['input', 'stereo_input'] },
  { id: 'buses', label: 'Buses', kinds: ['mix', 'aux', 'group', 'matrix', 'stereo', 'mono', 'monitor', 'cue', 'talkback', 'oscillator'] },
  { id: 'dcas', label: 'DCAs', kinds: ['dca', 'mute_group'] },
  { id: 'racks', label: 'Racks', kinds: ['rack'] },
];
export const BUS_KINDS = ['mix', 'aux', 'group', 'matrix', 'stereo', 'mono'];
export const AUDIO_LINK_KINDS = ['input_patch', 'send', 'output_patch', 'direct_out', 'insert_send', 'insert_return'];

function norm(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim(); }

export function channelLabel(ch) {
  if (!ch) return '';
  if (ch.label) return String(ch.label);
  const kind = String(ch.kind || '');
  const head = kind === 'rack' ? String(ch.rack || 'RACK').toUpperCase() : (SHORT[kind] || kind.toUpperCase());
  const parts = [head];
  if (ch.index !== undefined && ch.index !== null && kind !== 'stereo' && kind !== 'mono') parts.push(String(ch.index));
  if (ch.side) parts.push(String(ch.side).toUpperCase());
  return parts.join(' ');
}

export function channelTitle(ch) {
  const lab = channelLabel(ch);
  const name = String((ch && ch.name) || '').trim();
  return name && norm(name) !== norm(lab) ? lab + ' \u00b7 ' + name : lab;
}

export function groupOf(ch) {
  const kind = String((ch && ch.kind) || '');
  for (const g of GROUPS) if (g.kinds.indexOf(kind) >= 0) return g.id;
  return 'buses';
}

export function sortChannels(list) {
  return (list || []).slice().sort(function (a, b) {
    const ka = [ORDER[a.kind] === undefined ? 99 : ORDER[a.kind], String(a.rack || ''), Number(a.index || 0), String(a.side || '')];
    const kb = [ORDER[b.kind] === undefined ? 99 : ORDER[b.kind], String(b.rack || ''), Number(b.index || 0), String(b.side || '')];
    for (let i = 0; i < 4; i++) { if (ka[i] < kb[i]) return -1; if (ka[i] > kb[i]) return 1; }
    return 0;
  });
}

// {inputs: [...], buses: [...], dcas: [...], racks: [...]} sorted console-style
export function groupChannels(channels) {
  const out = { inputs: [], buses: [], dcas: [], racks: [] };
  sortChannels(channels).forEach(function (c) { if (c && c.id) out[groupOf(c)].push(c); });
  return out;
}

export function channelMap(channels) {
  const m = {};
  (channels || []).forEach(function (c) { if (c && c.id) m[c.id] = c; });
  return m;
}

// Persisted set wins once applied; else the overlay's; `pending` = an apply would change something.
export function effectiveChannels(device, overlay) {
  const ov = overlay && overlay.channels && device ? overlay.channels[device.id] : null;
  const has = device && Array.isArray(device.channels);
  if (has) {
    return { channels: device.channels.filter(function (c) { return c && c.id; }), links: (device.channel_links || []).filter(Boolean), source: 'device', pending: !!(ov && (ov.channels || []).length && !sameSet(device, ov)) };
  }
  if (ov && ((ov.channels || []).length || (ov.links || []).length)) return { channels: (ov.channels || []).slice(), links: (ov.links || []).slice(), source: 'overlay', pending: true };
  return { channels: [], links: [], source: 'none', pending: false };
}

function canon(v) {
  if (Array.isArray(v)) return '[' + v.map(canon).join(',') + ']';
  if (v && typeof v === 'object') return '{' + Object.keys(v).sort().map(function (k) { return JSON.stringify(k) + ':' + canon(v[k]); }).join(',') + '}';
  return JSON.stringify(v === undefined ? null : v);
}
function strip(o, drop) {
  const out = {};
  Object.keys(o || {}).forEach(function (k) { if (drop.indexOf(k) < 0 && o[k] !== undefined && o[k] !== null && o[k] !== '') out[k] = o[k]; });
  return out;
}
// Cheap "would a re-apply change anything": every imported channel / link already present with the same shape.
function sameSet(device, ov) {
  const have = {};
  (device.channels || []).forEach(function (c) { if (c && c.id) have[c.id] = canon(strip(c, ['source'])); });
  for (const c of (ov.channels || [])) {
    if (!c || !c.id) continue;
    const mine = (device.channels || []).filter(function (x) { return x && x.id === c.id; })[0];
    if (!mine) return false;
    if (mine.source !== 'user' && have[c.id] !== canon(strip(c, ['source']))) return false;
  }
  const links = {};
  (device.channel_links || []).forEach(function (l) { links[linkKey(l)] = true; });
  for (const l of (ov.links || [])) if (!links[linkKey(l)]) return false;
  return true;
}

export function linkKey(ln) { return canon(strip(ln, ['source', 'note'])); }
export function sameEndpoint(a, b) { return canon(strip(a, [])) === canon(strip(b, [])); }

// Per-channel view of the links: what feeds it, where it goes, which DCAs / mute groups it is in.
export function channelIndex(links) {
  const idx = {};
  function at(id) {
    if (!idx[id]) idx[id] = { inputs: [], sends: [], feeds: [], outputs: [], direct: [], insertSend: [], insertReturn: [], dca: [], mute: [], members: [] };
    return idx[id];
  }
  (links || []).forEach(function (ln) {
    if (!ln || !ln.from || !ln.to) return;
    const f = ln.from.channel, t = ln.to.channel;
    switch (ln.kind) {
      case 'input_patch': if (t) at(t).inputs.push(ln); if (f) at(f).outputs.push(ln); break;
      case 'send': if (f) at(f).sends.push(ln); if (t) at(t).feeds.push(ln); break;
      case 'output_patch': if (f) at(f).outputs.push(ln); if (t) at(t).inputs.push(ln); break;
      case 'direct_out': if (f) at(f).direct.push(ln); if (t) at(t).inputs.push(ln); break;
      case 'insert_send': if (f) at(f).insertSend.push(ln); if (t) at(t).inputs.push(ln); break;
      case 'insert_return': if (t) at(t).insertReturn.push(ln); if (f) at(f).outputs.push(ln); break;
      case 'dca': if (f) at(f).dca.push(ln); if (t) at(t).members.push(ln); break;
      case 'mute': if (f) at(f).mute.push(ln); if (t) at(t).members.push(ln); break;
      default: break;
    }
  });
  return idx;
}

// Human text for a link endpoint. ctx = {channels: map, ports: map, labels: {in:{ch:name}, out:{ch:name}} per port id, dir: 'in'|'out'}
export function endpointText(ep, ctx) {
  ctx = ctx || {};
  if (!ep) return '';
  if (ep.channel) {
    const ch = (ctx.channels || {})[ep.channel];
    const base = ch ? channelTitle(ch) : String(ep.channel);
    return ep.tag ? base + ' ' + ep.tag : base;
  }
  if (ep.port) {
    const p = (ctx.ports || {})[ep.port];
    let base = String((p && (p.label || p.name)) || ep.port);
    if (ep.ch) {
      base += ' ' + ep.ch;
      const lab = ctx.labels && ctx.labels[ep.port] && ctx.labels[ep.port][ctx.dir || 'in'];
      const nm = lab && lab[String(ep.ch)];
      if (nm) base += ' \u201c' + nm + '\u201d';
    }
    return base;
  }
  return String(ep.text || '');
}

// The far end of a Dante / stream route into (dir 'in') or out of (dir 'out') device:port#ch, from overlay.routes.
export function routePeer(routes, device, port, ch, dir) {
  for (const rt of (routes || [])) {
    const mine = dir === 'out' ? rt.from : rt.to;
    const other = dir === 'out' ? rt.to : rt.from;
    if (!mine || !other) continue;
    if (mine.device === device && mine.port === port && Number(mine.ch) === Number(ch)) return other;
  }
  return null;
}

// Dense one-line summary for a channel row: {source, dests, groups}
export function channelSummary(ch, idx, ctx) {
  const me = (idx || {})[ch.id] || {};
  const chans = ctx && ctx.channels;
  const out = { source: '', dests: [], groups: [] };
  const ins = (me.inputs || []).concat(me.feeds || []);
  if (ins.length) {
    out.source = ins.map(function (ln) { return endpointText(ln.from, Object.assign({}, ctx, { dir: 'in' })); }).filter(Boolean).slice(0, 3).join(', ');
    if (ins.length > 3) out.source += ' +' + (ins.length - 3);
  }
  (me.sends || []).forEach(function (ln) { out.dests.push(endpointText(ln.to, Object.assign({}, ctx, { dir: 'out' }))); });
  (me.outputs || []).concat(me.direct || []).forEach(function (ln) { out.dests.push(endpointText(ln.to, Object.assign({}, ctx, { dir: 'out' }))); });
  (me.dca || []).concat(me.mute || []).forEach(function (ln) { const g = chans && chans[ln.to.channel]; out.groups.push(g ? channelTitle(g) : String(ln.to.channel)); });
  if (ch.kind === 'dca' || ch.kind === 'mute_group') out.dests = (me.members || []).map(function (ln) { const m = chans && chans[ln.from.channel]; return m ? channelLabel(m) : String(ln.from.channel); });
  return out;
}

export function filterChannels(list, q, idx, ctx) {
  const key = norm(q);
  if (!key) return list.slice();
  return list.filter(function (ch) {
    const s = channelSummary(ch, idx, ctx);
    const hay = norm(channelTitle(ch) + ' ' + (ch.id || '') + ' ' + s.source + ' ' + s.dests.join(' ') + ' ' + s.groups.join(' '));
    return hay.indexOf(key) >= 0;
  });
}

// Node refs understood by GET …/trace (§6.9.3)
export function channelRef(device, ch, tag) { return device + ':@' + (typeof ch === 'string' ? ch : ch.id) + (tag ? '.' + tag : ''); }
export function portChannelRef(device, port, ch, dir) { return device + ':' + port + (ch ? '#' + (dir === 'out' ? 'tx' : dir === 'in' ? 'rx' : '') + ch : ''); }

// ---------------------------------------------------------------- edits
// All editors return a new channel_links array; user edits carry source "user".

function userLink(ln) { return Object.assign({}, ln, { source: 'user' }); }
function without(links, pred) { return (links || []).filter(function (l) { return !pred(l); }); }

export function setInputPatch(links, channelId, endpoint) {
  const rest = without(links, function (l) { return l.kind === 'input_patch' && l.to && l.to.channel === channelId && !l.to.tag; });
  if (!endpoint) return rest;
  return rest.concat([userLink({ from: endpoint, to: { channel: channelId }, kind: 'input_patch' })]);
}

export function toggleSend(links, channelId, busId, on) {
  const rest = without(links, function (l) { return l.kind === 'send' && l.from && l.from.channel === channelId && l.to && l.to.channel === busId; });
  return on ? rest.concat([userLink({ from: { channel: channelId }, to: { channel: busId }, kind: 'send' })]) : rest;
}

export function toggleMembership(links, kind, channelId, groupId, on) {
  const rest = without(links, function (l) { return l.kind === kind && l.from && l.from.channel === channelId && l.to && l.to.channel === groupId; });
  return on ? rest.concat([userLink({ from: { channel: channelId }, to: { channel: groupId }, kind: kind })]) : rest;
}

export function addOutput(links, channelId, endpoint, kind) {
  kind = kind || 'output_patch';
  const ln = userLink({ from: { channel: channelId }, to: endpoint, kind: kind });
  const key = linkKey(ln);
  if ((links || []).some(function (l) { return linkKey(l) === key; })) return (links || []).slice();
  return (links || []).concat([ln]);
}

export function removeLink(links, link) {
  const key = linkKey(link);
  return without(links, function (l) { return linkKey(l) === key; });
}

export function updateChannel(channels, id, patch) {
  let found = false;
  const out = (channels || []).map(function (c) {
    if (!c || c.id !== id) return c;
    found = true;
    const next = Object.assign({}, c, patch, { source: 'user' });
    Object.keys(next).forEach(function (k) { if (next[k] === null || next[k] === '' || next[k] === undefined) delete next[k]; });
    return next;
  });
  if (!found) return (channels || []).slice();
  return out;
}

export function nextChannel(channels, kind) {
  let max = 0;
  (channels || []).forEach(function (c) { if (c && c.kind === kind && Number(c.index) > max) max = Number(c.index); });
  const idx = max + 1;
  const prefix = { input: 'in', stereo_input: 'stin', mix: 'mix', aux: 'aux', group: 'grp', matrix: 'mtx', dca: 'dca', mute_group: 'mute', monitor: 'mon' }[kind] || kind;
  return { id: prefix + '-' + idx, kind: kind, index: idx, source: 'user' };
}

// ---------------------------------------------------------------- trace paths

// Group a trace path's hops by device for the drawer: [{device, name, hops: [{label, via, hop}]}]
export function chainOf(path) {
  const out = [];
  const hops = (path && path.hops) || [];
  const via = (path && path.via) || [];
  hops.forEach(function (hop, i) {
    const name = hop.device_name || '';
    let label = hop.label || hop.title || hop.text || hop.port || '';
    if (name && label.indexOf(name + ' \u00b7 ') === 0) label = label.slice(name.length + 3);
    if (name && label === name) label = hop.kind === 'channel' ? (hop.title || '') : (hop.port || '');
    const last = out[out.length - 1];
    const step = { label: label, via: via[i] || '', hop: hop };
    if (last && last.device === hop.device) last.hops.push(step);
    else out.push({ device: hop.device, name: name || hop.device, hops: [step] });
  });
  return out;
}

export function viaText(via) {
  if (!via) return '';
  if (via.indexOf('cable:') === 0) return 'cable ' + via.slice(6);
  if (via.indexOf('route:') === 0) return via.slice(6) + ' route';
  if (via.indexOf('link:') === 0) return via.slice(5).replace(/_/g, ' ');
  return via;
}

export function pathsText(paths) {
  return (paths || []).map(function (p) { return p.text || ''; }).filter(Boolean).join('\n');
}
