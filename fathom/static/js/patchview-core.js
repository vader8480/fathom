// Fathom patch view — pure logic (no DOM). Spec §6.5, §6.9.1–6.9.4.
// Runs in browsers (Safari 15+, Chrome) and in Node >= 18. ES2018 syntax only.

export const GEOM = {cardW: 248, headerH: 56, rowH: 22, sectionH: 18, ioSectionH: 18, pad: 8, dotR: 5, grid: 8, maxRows: 12};

// Row pitch under (pointer: coarse): a 32 px row box plus the 4 px gap (§6.11 item 8). Pass as opts.geom.rowH.
export const COARSE_ROW_H = 36;

export const ZOOM_MIN = 0.15;
export const ZOOM_MAX = 3.0;

const FALLBACK_MEDIUM = {label: 'Other', color: '#9aa3b5', dash: '', width: 1.2, discipline: 'other',
  carries: ['audio', 'video', 'lighting', 'control', 'network', 'power']};
const FALLBACK_DISC = {label: 'Other', color: '#9aa3b5', letter: 'X'};

// ---------------------------------------------------------------- helpers

function geomOf(opts) {
  const g = Object.assign({}, GEOM);
  if (opts && opts.geom) Object.assign(g, opts.geom);
  return g;
}

function arr(v) {
  if (!v) return [];
  if (Array.isArray(v)) return v;
  if (typeof v === 'string') return v ? v.split(',').filter(Boolean) : [];
  if (typeof v.forEach === 'function') { const out = []; v.forEach(function (x) { out.push(x); }); return out; }
  return [];
}

function has(setLike, key) {
  if (!setLike) return false;
  if (typeof setLike.has === 'function') return setLike.has(key);
  if (Array.isArray(setLike)) return setLike.indexOf(key) >= 0;
  return !!setLike[key];
}

function num(v) { return typeof v === 'number' && isFinite(v); }

function r1(v) { return String(Math.round(v * 10) / 10); }

export function slug(text) {
  const s = String(text == null ? '' : text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return s || 'item';
}

export function portsOf(device) {
  return device && Array.isArray(device.ports) ? device.ports : [];
}

export function mediumInfo(medium, vocab) {
  const media = (vocab && vocab.media) || {};
  return media[medium] || media.other || FALLBACK_MEDIUM;
}

export function carriesOf(medium, vocab) {
  const info = mediumInfo(medium, vocab);
  if (Array.isArray(info.carries)) return info.carries;
  return info.discipline ? [info.discipline] : [];
}

export function mediumDiscipline(medium, vocab) {
  return mediumInfo(medium, vocab).discipline || 'other';
}

export function deviceDiscipline(device, vocab) {
  if (device && device.discipline) return device.discipline;
  const kinds = (vocab && vocab.kinds) || {};
  const k = device && kinds[device.kind];
  return (k && k.discipline) || 'other';
}

export function disciplineInfo(key, vocab) {
  const d = (vocab && vocab.disciplines) || {};
  return d[key] || d.other || FALLBACK_DISC;
}

export function portLabelOf(port) {
  if (!port) return '';
  return port.label || port.name || port.id || '';
}

export function modelLine(device) {
  const m = ((device.manufacturer || '') + ' ' + (device.model || '')).trim();
  return m || device.sub || '';
}

export function deviceTitleOf(device) {
  let t = device.name || device.id;
  if (num(device.count) && device.count > 1) t += ' \u00d7' + device.count;
  if (device.suffix) t += ' ' + device.suffix;
  return t;
}

function statusOf(e) { return (e && e.status) || 'installed'; }

function stateOk(status, state) {
  switch (state || 'all') {
    case 'everything': return true;
    case 'planned': return status === 'planned' || status === 'installed';
    case 'as_built': return status === 'installed';
    default: return status !== 'retired';
  }
}

function intersects(a, b) {
  for (let i = 0; i < a.length; i++) if (b.indexOf(a[i]) >= 0) return true;
  return false;
}

// ---------------------------------------------------------------- card layout

export function cardLayout(device, opts) {
  opts = opts || {};
  const g = geomOf(opts);
  const connected = opts.connected || new Set();
  const labels = opts.labels || {};
  const showUnconnected = opts.showUnconnected !== false;
  const expanded = !!opts.expanded;
  const maxRows = opts.maxRows || g.maxRows;
  const cols = {left: [], right: [], both: []};
  portsOf(device).forEach(function (p) {
    const side = p.dir === 'in' ? 'left' : (p.dir === 'out' ? 'right' : 'both');
    cols[side].push({port: p, pos: cols[side].length + 1});
  });
  const hidden = {left: 0, right: 0, io: 0};
  const vis = {};
  ['left', 'right', 'both'].forEach(function (side) {
    let list = cols[side];
    if (!showUnconnected) list = list.filter(function (e) { return has(connected, e.port.id); });
    if (!expanded && list.length > maxRows) {
      const before = list.length;
      list = list.filter(function (e) {
        return has(connected, e.port.id) || !!e.port.label || !!labels[e.port.id];
      });
      hidden[side === 'both' ? 'io' : side] = before - list.length;
    }
    vis[side] = list;
  });
  const rows = [];
  const more = {};
  const top = g.headerH + g.pad;
  function mk(e, side, y) {
    const p = e.port;
    const ov = !p.label && !!labels[p.id];
    rows.push({port: p, side: side, y: y, index: e.pos, label: p.label || (ov ? labels[p.id] : '') || p.name || p.id,
      overlayLabel: ov});
  }
  vis.left.forEach(function (e, i) { mk(e, 'left', top + i * g.rowH); });
  vis.right.forEach(function (e, i) { mk(e, 'right', top + i * g.rowH); });
  let nl = vis.left.length, nr = vis.right.length;
  if (hidden.left) { more.left = {y: top + nl * g.rowH, n: hidden.left}; nl++; }
  if (hidden.right) { more.right = {y: top + nr * g.rowH, n: hidden.right}; nr++; }
  const colRows = Math.max(nl, nr);
  let bottom = top + colRows * g.rowH;
  let ioTop = null;
  if (vis.both.length || hidden.io) {
    ioTop = bottom + (colRows ? 4 : 0);
    const rowsTop = ioTop + g.ioSectionH;
    vis.both.forEach(function (e, i) { mk(e, 'both', rowsTop + i * g.rowH); });
    bottom = rowsTop + vis.both.length * g.rowH;
    if (hidden.io) { more.io = {y: bottom, n: hidden.io}; bottom += g.rowH; }
  }
  const h = (colRows || ioTop !== null) ? bottom + g.pad : g.headerH + 4;
  return {w: g.cardW, h: h, rows: rows, hidden: hidden, more: more, ioTop: ioTop, colRows: colRows, geom: g,
    total: portsOf(device).length};
}

// ---------------------------------------------------------------- anchors & wires

function findRow(card, portId) {
  const rows = card.layout.rows;
  for (let i = 0; i < rows.length; i++) if (rows[i].port.id === portId) return rows[i];
  return null;
}

export function portAnchor(card, portId, side) {
  const g = card.layout.geom || GEOM;
  const row = portId == null ? null : findRow(card, portId);
  if (!row) {
    const s = side === 'left' ? 'left' : 'right';
    return {x: s === 'left' ? card.x : card.x + card.w, y: card.y + g.headerH / 2, side: s, header: true};
  }
  let s = row.side;
  if (s === 'both') s = side === 'left' ? 'left' : 'right';
  return {x: s === 'left' ? card.x : card.x + card.w, y: card.y + row.y + g.rowH / 2, side: s, header: false};
}

export function wireControls(a, b) {
  const off = Math.max(40, Math.abs(b.x - a.x) / 2);
  return {
    c1: {x: a.side === 'left' ? a.x - off : a.x + off, y: a.y},
    c2: {x: b.side === 'right' ? b.x + off : b.x - off, y: b.y},
  };
}

export function wirePath(a, b) {
  const c = wireControls(a, b);
  return 'M ' + r1(a.x) + ' ' + r1(a.y) + ' C ' + r1(c.c1.x) + ' ' + r1(c.c1.y) + ' ' + r1(c.c2.x) + ' ' +
    r1(c.c2.y) + ' ' + r1(b.x) + ' ' + r1(b.y);
}

function bezierAt(a, c1, c2, b, t) {
  const u = 1 - t;
  return {
    x: u * u * u * a.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * b.x,
    y: u * u * u * a.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * b.y,
  };
}

function segDist(p, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const l2 = dx * dx + dy * dy;
  let t = l2 ? ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2 : 0;
  t = Math.max(0, Math.min(1, t));
  const x = a.x + t * dx - p.x, y = a.y + t * dy - p.y;
  return Math.sqrt(x * x + y * y);
}

export function wireDistance(wire, pt) {
  const a = wire.a, b = wire.b, c = wireControls(a, b);
  let prev = a, best = Infinity;
  for (let i = 1; i <= 24; i++) {
    const p = bezierAt(a, c.c1, c.c2, b, i / 24);
    const d = segDist(pt, prev, p);
    if (d < best) best = d;
    prev = p;
  }
  return best;
}

// Which edge of a card an endpoint uses: fixed for in/out rows, chosen for io rows and header anchors.
function pickSide(card, row, other, defSide) {
  if (row && row.side !== 'both') return row.side;
  if (!other) return defSide;
  const cx = card.x + card.w / 2, ox = other.x + other.w / 2;
  if (Math.abs(ox - cx) < card.w * 0.5) return 'right';
  return ox > cx ? 'right' : 'left';
}

export function wireAnchors(fromCard, fromPort, toCard, toPort) {
  const fr = fromPort == null ? null : findRow(fromCard, fromPort);
  const tr = toPort == null ? null : findRow(toCard, toPort);
  const a = portAnchor(fromCard, fr ? fromPort : null, pickSide(fromCard, fr, toCard, 'right'));
  const b = portAnchor(toCard, tr ? toPort : null, pickSide(toCard, tr, fromCard, 'left'));
  return {a: a, b: b};
}

// ---------------------------------------------------------------- scene

function deviceMatchesQuery(d, q) {
  if (!q) return true;
  const hay = [d.name, d.id, d.model, d.manufacturer, d.sub, d.code, d.note].concat(d.tags || [], d.aliases || []);
  portsOf(d).forEach(function (p) { hay.push(p.label, p.name); });
  for (let i = 0; i < hay.length; i++) if (hay[i] && String(hay[i]).toLowerCase().indexOf(q) >= 0) return true;
  return false;
}

function deviceDiscs(d, vocab) {
  const out = [deviceDiscipline(d, vocab)];
  portsOf(d).forEach(function (p) {
    const k = mediumDiscipline(p.medium, vocab);
    if (out.indexOf(k) < 0) out.push(k);
  });
  return out;
}

export function buildScene(doc, overlay, vocab, filter, opts) {
  doc = doc || {};
  filter = filter || {};
  opts = opts || {};
  const g = geomOf(opts);
  const room = filter.room == null ? '*' : filter.room;
  const discs = arr(filter.disciplines);
  const statuses = arr(filter.statuses);
  const q = String(filter.query || '').trim().toLowerCase();
  const system = filter.system || '';
  const state = filter.state || 'all';
  const showUnconnected = filter.showUnconnected !== false;
  const rooms = {};
  (doc.rooms || []).forEach(function (r) { rooms[r.id] = r; });

  const devices = (doc.devices || []).slice();
  const byId = {};
  devices.forEach(function (d) { byId[d.id] = d; });
  ((overlay && overlay.devices) || []).forEach(function (d) {
    if (!d || !d.id || byId[d.id]) return;
    const od = Object.assign({}, d, {auto: true});
    devices.push(od);
    byId[d.id] = od;
  });

  function statusOk(d) {
    const s = statusOf(d);
    return statuses.length ? statuses.indexOf(s) >= 0 : stateOk(s, state);
  }
  function primaryOk(d) {
    if (!statusOk(d)) return false;
    if (room !== '*' && (d.room || '') !== room) return false;
    if (system && d.system !== system) return false;
    if (discs.length && !intersects(deviceDiscs(d, vocab), discs)) return false;
    return true;
  }
  function cableOk(c) {
    if (!c || !c.from || !c.to) return false;
    const fd = byId[c.from.device], td = byId[c.to.device];
    if (!fd || !td || !statusOk(fd) || !statusOk(td)) return false;
    return stateOk(statusOf(c), statuses.length ? 'everything' : state);
  }
  function wireDiscOk(c) {
    if (!discs.length) return true;
    return discs.indexOf(mediumDiscipline(c.medium, vocab)) >= 0 || intersects(carriesOf(c.medium, vocab), discs);
  }

  const primary = {};
  devices.forEach(function (d) { if (primaryOk(d)) primary[d.id] = true; });

  const cables = (doc.cables || []).filter(cableOk);
  const connected = {};
  cables.forEach(function (c) {
    [c.from, c.to].forEach(function (e) {
      if (!e.port) return;
      (connected[e.device] || (connected[e.device] = new Set())).add(e.port);
    });
  });

  const ghosts = {};
  if (room !== '*') {
    const elsewhere = function (id) { return (byId[id].room || '') !== room; };
    cables.forEach(function (c) {
      if (!wireDiscOk(c)) return;
      const f = primary[c.from.device], t = primary[c.to.device];
      if (f && !t && elsewhere(c.to.device)) ghosts[c.to.device] = true;
      else if (t && !f && elsewhere(c.from.device)) ghosts[c.from.device] = true;
    });
  }

  const positions = opts.positions || {};
  const expanded = opts.expanded || null;
  const labelsAll = (overlay && overlay.port_labels) || {};
  const cards = [];
  const cardById = {};
  const missing = [];
  devices.forEach(function (d) {
    const ext = !primary[d.id] && !!ghosts[d.id];
    if (!primary[d.id] && !ext) return;
    const layout = cardLayout(d, {connected: connected[d.id] || new Set(), labels: labelsAll[d.id] || {},
      showUnconnected: showUnconnected, expanded: has(expanded, d.id), maxRows: opts.maxRows, geom: opts.geom});
    let pos = null;
    if (d.patch && num(d.patch.x) && num(d.patch.y)) pos = d.patch;
    else if (positions[d.id]) pos = positions[d.id];
    const disc = deviceDiscipline(d, vocab);
    const card = {id: d.id, device: d, x: pos ? pos.x : 0, y: pos ? pos.y : 0, w: layout.w, h: layout.h, layout: layout,
      external: ext, auto: !!d.auto, dim: !!q && !deviceMatchesQuery(d, q), discipline: disc,
      title: deviceTitleOf(d), model: modelLine(d), status: statusOf(d),
      roomName: ext ? ((rooms[d.room] && rooms[d.room].name) || (d.room ? d.room : 'Shared inventory')) : '',
      placed: !!pos};
    if (!pos) missing.push(card);
    cards.push(card);
    cardById[d.id] = card;
  });

  const autoPositions = {};
  if (missing.length) {
    let ox = 40, oy = 40;
    const placed = cards.filter(function (c) { return c.placed; });
    if (placed.length) {
      const b = boundsOf(placed);
      ox = b.x;
      oy = b.y + b.h + 80;
    }
    const heights = {};
    missing.forEach(function (c) { heights[c.id] = c.h; });
    const lay = autoLayout(doc, missing.map(function (c) { return c.id; }), vocab,
      {origin: {x: ox, y: oy}, heights: heights, devices: byId});
    missing.forEach(function (c) {
      const p = lay[c.id] || {x: ox, y: oy};
      c.x = p.x; c.y = p.y;
      autoPositions[c.id] = {x: p.x, y: p.y};
    });
  }

  const wires = [];
  const wireById = {};
  const wiresByDevice = {};
  const wiresByPort = {};
  cables.forEach(function (c) {
    if (!wireDiscOk(c)) return;
    const fc = cardById[c.from.device], tc = cardById[c.to.device];
    if (!fc || !tc) return;
    const m = mediumInfo(c.medium, vocab);
    const an = wireAnchors(fc, c.from.port, tc, c.to.port);
    const w = {id: c.id, cable: c, from: {device: c.from.device, port: c.from.port || null},
      to: {device: c.to.device, port: c.to.port || null}, medium: c.medium, color: m.color || FALLBACK_MEDIUM.color,
      dash: m.dash || '', width: num(m.width) ? m.width : 1.2, external: fc.external || tc.external,
      planned: statusOf(c) === 'planned', a: an.a, b: an.b};
    wires.push(w);
    wireById[w.id] = w;
    (wiresByDevice[fc.id] || (wiresByDevice[fc.id] = [])).push(w.id);
    if (tc.id !== fc.id) (wiresByDevice[tc.id] || (wiresByDevice[tc.id] = [])).push(w.id);
    [w.from, w.to].forEach(function (e) {
      if (!e.port) return;
      const k = e.device + ':' + e.port;
      (wiresByPort[k] || (wiresByPort[k] = [])).push(w.id);
    });
  });

  const routes = [];
  const agg = {};
  ((overlay && overlay.routes) || []).forEach(function (rt) {
    if (!rt || !rt.from || !rt.to) return;
    const fc = cardById[rt.from.device], tc = cardById[rt.to.device];
    if (!fc || !tc || fc === tc) return;
    const key = fc.id + '>' + tc.id;
    let e = agg[key];
    if (!e) {
      const m = mediumInfo(rt.medium || 'dante', vocab);
      e = agg[key] = {id: 'r:' + key, from: {device: fc.id, port: rt.from.port || null},
        to: {device: tc.id, port: rt.to.port || null}, count: 0, kinds: [], medium: rt.medium || 'dante',
        color: m.color || FALLBACK_MEDIUM.color};
      routes.push(e);
    }
    e.count += 1;
    if (rt.kind && e.kinds.indexOf(rt.kind) < 0) e.kinds.push(rt.kind);
  });
  routes.forEach(function (e) {
    const an = wireAnchors(cardById[e.from.device], e.from.port, cardById[e.to.device], e.to.port);
    e.a = an.a; e.b = an.b;
  });

  return {cards: cards, wires: wires, routes: routes, bounds: boundsOf(cards), cardById: cardById, wireById: wireById,
    wiresByDevice: wiresByDevice, wiresByPort: wiresByPort, autoPositions: autoPositions, geom: g, room: room};
}

export function boundsOf(cards) {
  if (!cards.length) return {x: 0, y: 0, w: 0, h: 0};
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  cards.forEach(function (c) {
    if (c.x < x0) x0 = c.x;
    if (c.y < y0) y0 = c.y;
    if (c.x + c.w > x1) x1 = c.x + c.w;
    if (c.y + c.h > y1) y1 = c.y + c.h;
  });
  return {x: x0, y: y0, w: x1 - x0, h: y1 - y0};
}

// Recompute geometry of wires attached to the given cards (used while dragging). Mutates wires in place.
export function updateWires(scene, deviceIds) {
  const seen = {};
  const out = [];
  deviceIds.forEach(function (id) {
    (scene.wiresByDevice[id] || []).forEach(function (wid) {
      if (seen[wid]) return;
      seen[wid] = true;
      const w = scene.wireById[wid];
      const an = wireAnchors(scene.cardById[w.from.device], w.from.port, scene.cardById[w.to.device], w.to.port);
      w.a = an.a; w.b = an.b;
      out.push(w);
    });
  });
  return out;
}

// ---------------------------------------------------------------- auto layout

export function autoLayout(doc, deviceIds, vocab, opts) {
  opts = opts || {};
  const g = geomOf(opts);
  const colGap = opts.colGap == null ? 96 : opts.colGap;
  const rowGap = opts.rowGap == null ? 24 : opts.rowGap;
  const origin = opts.origin || (num(opts.x) && num(opts.y) ? {x: opts.x, y: opts.y} : {x: 40, y: 40});
  const devMap = opts.devices || {};
  (doc.devices || []).forEach(function (d) { if (!devMap[d.id]) devMap[d.id] = d; });
  const ids = (deviceIds ? arr(deviceIds) : (doc.devices || []).map(function (d) { return d.id; }))
    .filter(function (id) { return !!devMap[id]; });
  const order = {};
  ids.forEach(function (id, i) { order[id] = i; });
  const adj = {}, preds = {};
  ids.forEach(function (id) { adj[id] = []; preds[id] = []; });
  (doc.cables || []).forEach(function (c) {
    if (!c || !c.from || !c.to) return;
    const f = c.from.device, t = c.to.device;
    if (f === t || order[f] == null || order[t] == null) return;
    if (adj[f].indexOf(t) < 0) adj[f].push(t);
  });
  // DFS topological order ignoring back edges (cycles).
  const mark = {}, post = [];
  ids.forEach(function (root) {
    if (mark[root]) return;
    const stack = [[root, 0]];
    mark[root] = 1;
    while (stack.length) {
      const top = stack[stack.length - 1];
      const nb = adj[top[0]];
      if (top[1] < nb.length) {
        const v = nb[top[1]++];
        if (!mark[v]) { mark[v] = 1; stack.push([v, 0]); }
      } else {
        mark[top[0]] = 2;
        post.push(top[0]);
        stack.pop();
      }
    }
  });
  const topo = post.reverse();
  const tIdx = {};
  topo.forEach(function (id, i) { tIdx[id] = i; });
  const layer = {};
  ids.forEach(function (id) { layer[id] = 0; });
  topo.forEach(function (u) {
    adj[u].forEach(function (v) {
      if (tIdx[v] > tIdx[u]) {
        if (layer[u] + 1 > layer[v]) layer[v] = layer[u] + 1;
        preds[v].push(u);
      }
    });
  });
  const layers = [];
  ids.forEach(function (id) { (layers[layer[id]] || (layers[layer[id]] = [])).push(id); });
  // Default heights must match rendering, which keeps cabled ports visible in collapsed columns.
  let connected = null;
  if (!opts.heights) {
    connected = {};
    (doc.cables || []).forEach(function (c) {
      if (!c || !c.from || !c.to) return;
      [c.from, c.to].forEach(function (e) {
        if (e.port) (connected[e.device] || (connected[e.device] = new Set())).add(e.port);
      });
    });
  }
  const rank = {};
  const out = {};
  let x = origin.x;
  for (let L = 0; L < layers.length; L++) {
    const list = layers[L] || [];
    const key = {};
    list.forEach(function (id) {
      const ps = preds[id].filter(function (p) { return rank[p] != null; });
      key[id] = ps.length ? ps.reduce(function (s, p) { return s + rank[p]; }, 0) / ps.length : Infinity;
    });
    list.sort(function (a, b) {
      if (key[a] !== key[b]) return key[a] < key[b] ? -1 : 1;
      return order[a] - order[b];
    });
    let y = origin.y;
    list.forEach(function (id, i) {
      rank[id] = i;
      out[id] = {x: snap(x, g.grid), y: snap(y, g.grid)};
      const h = (opts.heights && opts.heights[id]) ||
        cardLayout(devMap[id], {geom: opts.geom, connected: (connected && connected[id]) || new Set()}).h;
      y = snap(y, g.grid) + h + rowGap;
    });
    x += g.cardW + colGap;
  }
  return out;
}

// ---------------------------------------------------------------- hit testing

export function hitTest(scene, pt, opts) {
  opts = opts || {};
  const g = scene.geom || GEOM;
  const k = opts.k || 1;
  const grab = (opts.grab || 12) / k;
  const dotHit = Math.max(g.dotR + 3, opts.dotHit || 10) / k;
  if (opts.selectedWire && scene.wireById[opts.selectedWire]) {
    const w = scene.wireById[opts.selectedWire];
    if (dist(pt, w.a) <= grab) return {type: 'wire-end', wire: w, end: 'from'};
    if (dist(pt, w.b) <= grab) return {type: 'wire-end', wire: w, end: 'to'};
  }
  const inside = function (c) { return pt.x >= c.x && pt.x <= c.x + c.w && pt.y >= c.y && pt.y <= c.y + c.h; };
  // Nearest dot wins, across cards too: at low zoom the touch hit radius can exceed the row pitch and
  // reach the neighbouring card, so the first card in z-order must not claim a dot that another card's
  // port is closer to. A card stacked above the winning dot's card still takes a point inside its body.
  let bestDot = null;
  for (let i = scene.cards.length - 1; i >= 0; i--) {
    const c = scene.cards[i];
    if (pt.x < c.x - dotHit || pt.x > c.x + c.w + dotHit || pt.y < c.y - dotHit || pt.y > c.y + c.h + dotHit) continue;
    const rows = c.layout.rows;
    for (let j = 0; j < rows.length; j++) {
      const row = rows[j];
      const cy = c.y + row.y + g.rowH / 2;
      if (Math.abs(pt.y - cy) > dotHit) continue;
      const sides = row.side === 'both' ? ['left', 'right'] : [row.side];
      for (let s = 0; s < sides.length; s++) {
        const cx = sides[s] === 'left' ? c.x : c.x + c.w;
        const d = Math.abs(pt.x - cx) <= dotHit ? Math.sqrt((pt.x - cx) * (pt.x - cx) + (pt.y - cy) * (pt.y - cy)) : Infinity;
        if (d <= dotHit && (!bestDot || d < bestDot.d)) bestDot = {d: d, card: c, idx: i, row: row, side: sides[s]};
      }
    }
  }
  if (bestDot) {
    for (let i = scene.cards.length - 1; i > bestDot.idx; i--) {
      if (inside(scene.cards[i])) { bestDot = null; break; }
    }
  }
  if (bestDot) {
    const c = bestDot.card, bestRow = bestDot.row;
    const ref = c.id + ':' + bestRow.port.id;
    const ws = scene.wiresByPort[ref] || [];
    if (bestRow.port.dir === 'in' && ws.length === 1 && !opts.noWireEnd) {
      const w = scene.wireById[ws[0]];
      return {type: 'wire-end', wire: w, end: w.to.device === c.id && w.to.port === bestRow.port.id ? 'to' : 'from',
        card: c, port: bestRow.port};
    }
    return {type: 'port', card: c, port: bestRow.port, row: bestRow, side: bestDot.side, onDot: true};
  }
  for (let i = scene.cards.length - 1; i >= 0; i--) {
    const c = scene.cards[i];
    if (!inside(c)) continue;
    const rows = c.layout.rows;
    const ly = pt.y - c.y, lx = pt.x - c.x;
    if (ly < g.headerH) return {type: 'header', card: c};
    for (let j = 0; j < rows.length; j++) {
      const row = rows[j];
      if (ly < row.y || ly >= row.y + g.rowH) continue;
      if (row.side === 'left' && lx > c.w / 2) continue;
      if (row.side === 'right' && lx < c.w / 2) continue;
      return {type: 'port', card: c, port: row.port, row: row, side: row.side, onDot: false};
    }
    const more = c.layout.more || {};
    const msides = Object.keys(more);
    for (let j = 0; j < msides.length; j++) {
      const m = more[msides[j]];
      if (ly >= m.y && ly < m.y + g.rowH) return {type: 'more', card: c, side: msides[j]};
    }
    return {type: 'card', card: c};
  }
  const tol = (opts.wireTol || 6) / k;
  let best = null, bestD = tol;
  for (let i = 0; i < scene.wires.length; i++) {
    const w = scene.wires[i];
    const x0 = Math.min(w.a.x, w.b.x) - 60, x1 = Math.max(w.a.x, w.b.x) + 60;
    const y0 = Math.min(w.a.y, w.b.y) - tol, y1 = Math.max(w.a.y, w.b.y) + tol;
    if (pt.x < x0 - Math.abs(w.b.x - w.a.x) || pt.x > x1 + Math.abs(w.b.x - w.a.x) || pt.y < y0 || pt.y > y1) continue;
    const d = wireDistance(w, pt);
    if (d <= bestD) { bestD = d; best = w; }
  }
  if (best) return {type: 'wire', wire: best};
  return {type: 'background'};
}

function dist(a, b) { const dx = a.x - b.x, dy = a.y - b.y; return Math.sqrt(dx * dx + dy * dy); }

// ---------------------------------------------------------------- connection rules (direction subset of §4.4.4)

function findPort(doc, ref) {
  const devs = doc.devices || [];
  for (let i = 0; i < devs.length; i++) {
    if (devs[i].id !== ref.device) continue;
    if (ref.port == null) return {device: devs[i], port: null};
    const ps = portsOf(devs[i]);
    for (let j = 0; j < ps.length; j++) if (ps[j].id === ref.port) return {device: devs[i], port: ps[j]};
    return null;
  }
  return null;
}

function dirOk(fromDir, toDir) {
  return (fromDir === 'out' || fromDir === 'io') && (toDir === 'in' || toDir === 'io');
}

// Orient two endpoints into {from, to} following §4.4.4, or null when no direction is legal.
// role: 'source' (a must be the from end), 'sink' (a must be the to end) or 'any'.
export function orient(doc, a, b, role) {
  if (a.device === b.device && (a.port || null) === (b.port || null)) return null;
  const pa = findPort(doc, a), pb = findPort(doc, b);
  if (!pa || !pb) return null;
  const da = pa.port ? pa.port.dir : 'io', db = pb.port ? pb.port.dir : 'io';
  if (role !== 'sink' && dirOk(da, db)) return {from: a, to: b};
  if (role !== 'source' && dirOk(db, da)) return {from: b, to: a};
  return null;
}

export function compatibleTargets(doc, scene, from, vocab) {
  const out = new Set();
  if (!from) return out;
  const role = from.role || 'any';
  const start = {device: from.device, port: from.port == null ? null : from.port};
  scene.cards.forEach(function (c) {
    if (c.auto) return;
    c.layout.rows.forEach(function (row) {
      const t = {device: c.id, port: row.port.id};
      if (orient(doc, start, t, role)) out.add(c.id + ':' + row.port.id);
    });
  });
  return out;
}

// ---------------------------------------------------------------- ops

export function snap(v, grid) {
  if (!grid) return Math.round(v);
  return Math.round(v / grid) * grid;
}

export function moveOps(doc, positions, grid) {
  const g = grid === undefined ? GEOM.grid : grid;
  const ids = {};
  (doc.devices || []).forEach(function (d) { ids[d.id] = true; });
  const ops = [];
  Object.keys(positions || {}).forEach(function (id) {
    if (!ids[id]) return;
    const p = positions[id];
    if (!p || !num(p.x) || !num(p.y)) return;
    ops.push({op: 'merge', coll: 'devices', id: id, value: {patch: {x: snap(p.x, g), y: snap(p.y, g)}}});
  });
  return ops;
}

export function arrangeOps(doc, deviceIds, vocab, opts) {
  return moveOps(doc, autoLayout(doc, deviceIds, vocab, opts), (opts && opts.grid) == null ? GEOM.grid : opts.grid);
}

// A new port for "Add port…": unique id from the name within the device.
export function newPort(device, spec) {
  spec = spec || {};
  const name = String(spec.name || 'Port').trim() || 'Port';
  const taken = {};
  portsOf(device).forEach(function (p) { taken[p.id] = true; });
  const base = slug(name);
  let id = base, n = 2;
  while (taken[id]) id = base + '-' + (n++);
  const p = {id: id, name: name, dir: spec.dir === 'out' || spec.dir === 'io' ? spec.dir : 'in',
    medium: spec.medium || 'analog', origin: 'user'};
  if (spec.group) p.group = spec.group;
  return p;
}

// ---------------------------------------------------------------- viewport math

export function clampK(k, min, max) {
  return Math.max(min == null ? ZOOM_MIN : min, Math.min(max == null ? ZOOM_MAX : max, k));
}

export function screenToWorld(view, pt) { return {x: (pt.x - view.x) / view.k, y: (pt.y - view.y) / view.k}; }

export function worldToScreen(view, pt) { return {x: pt.x * view.k + view.x, y: pt.y * view.k + view.y}; }

export function zoomAt(view, pt, factor, min, max) {
  const k = clampK(view.k * factor, min, max);
  const w = screenToWorld(view, pt);
  return {x: pt.x - w.x * k, y: pt.y - w.y * k, k: k};
}

export function fitView(bounds, size, margin, min, max) {
  const m = margin == null ? 40 : margin;
  if (!bounds || !bounds.w || !bounds.h) return {x: m, y: m, k: 1};
  const k = clampK(Math.min((size.w - 2 * m) / bounds.w, (size.h - 2 * m) / bounds.h, 1), min, max);
  return {x: (size.w - bounds.w * k) / 2 - bounds.x * k, y: (size.h - bounds.h * k) / 2 - bounds.y * k, k: k};
}

// ---------------------------------------------------------------- tracing (§6.9.1–6.9.4)

const STEM_DROP = ['in', 'input', 'inputs', 'out', 'output', 'outputs', 'thru', 'through', 'loop'];

function stem(group) {
  return slug(group || '').split('-').filter(function (t) { return STEM_DROP.indexOf(t) < 0; }).join('-');
}

function routingMode(d, vocab) {
  if (d.routing && d.routing.mode) return d.routing.mode;
  const k = vocab && vocab.kinds && vocab.kinds[d.kind];
  return (k && k.routing) || 'matrix';
}

function internalEdges(d, vocab, carriesD) {
  const ps = portsOf(d);
  const mode = routingMode(d, vocab);
  const edges = [];
  const isIn = function (p) { return p.dir === 'in' || p.dir === 'io'; };
  const isOut = function (p) { return p.dir === 'out' || p.dir === 'io'; };
  if (mode === 'none') return edges;
  if (mode === 'explicit') {
    ((d.routing && d.routing.map) || []).forEach(function (pair) {
      if (!Array.isArray(pair) || pair.length < 2) return;
      const a = ps.filter(function (p) { return p.id === pair[0]; })[0];
      const b = ps.filter(function (p) { return p.id === pair[1]; })[0];
      if (a && b && carriesD(a.medium) && carriesD(b.medium)) edges.push([a.id, b.id]);
    });
    return edges;
  }
  if (mode === 'passthrough') {
    const groupIns = {}, posInGroup = {}, counters = {};
    ps.forEach(function (p) {
      const gk = p.group || '';
      counters[gk] = (counters[gk] || 0) + 1;
      posInGroup[p.id] = counters[gk];
      if (p.dir === 'in') groupIns[gk] = (groupIns[gk] || 0) + 1;
    });
    const idx = function (p) { return num(p.index) ? p.index : posInGroup[p.id]; };
    ps.forEach(function (a) {
      if (!isIn(a)) return;
      ps.forEach(function (b) {
        if (a === b || !isOut(b) || a.medium !== b.medium) return;
        const ga = a.group || '', gb = b.group || '';
        let ok = false;
        if (ga === gb) ok = groupIns[ga] === 1;
        else ok = idx(a) === idx(b) && stem(ga) === stem(gb);
        if (ok && carriesD(a.medium) && carriesD(b.medium)) edges.push([a.id, b.id]);
      });
    });
    return edges;
  }
  // matrix
  ps.forEach(function (a) {
    if (!isIn(a)) return;
    ps.forEach(function (b) {
      if (a === b || !isOut(b)) return;
      if (!carriesD(a.medium) || !carriesD(b.medium)) return;
      const ca = carriesD.list(a.medium), cb = carriesD.list(b.medium);
      if (intersects(ca, cb)) edges.push([a.id, b.id]);
    });
  });
  return edges;
}

export function buildTraceGraph(doc, overlay, opts) {
  opts = opts || {};
  const vocab = opts.vocab || null;
  const disc = opts.discipline || null;
  const state = opts.state || 'all';
  const carriesD = function (m) {
    if (!disc) return true;
    if (!vocab || !vocab.media) return true;
    return carriesOf(m, vocab).indexOf(disc) >= 0;
  };
  carriesD.list = function (m) {
    const c = vocab && vocab.media ? carriesOf(m, vocab) : ['*'];
    return disc ? c.filter(function (x) { return x === disc || x === '*'; }) : c;
  };
  const devs = (doc.devices || []).slice();
  const seen = {};
  devs.forEach(function (d) { seen[d.id] = true; });
  ((overlay && overlay.devices) || []).forEach(function (d) { if (d && d.id && !seen[d.id]) { devs.push(d); seen[d.id] = true; } });
  const byId = {};
  devs.forEach(function (d) { if (stateOk(statusOf(d), state)) byId[d.id] = d; });
  const fwd = {}, rev = {};
  function add(a, b, cable) {
    (fwd[a] || (fwd[a] = [])).push({node: b, cable: cable || null});
    (rev[b] || (rev[b] = [])).push({node: a, cable: cable || null});
  }
  const virtual = {};
  if (opts.virtualFor) virtual[opts.virtualFor] = true;
  function ref(e) {
    if (e.port) return e.device + ':' + e.port;
    virtual[e.device] = true;
    return e.device + ':*';
  }
  Object.keys(byId).forEach(function (id) {
    internalEdges(byId[id], vocab, carriesD).forEach(function (e) { add(id + ':' + e[0], id + ':' + e[1]); });
  });
  const portDir = function (e) {
    const d = byId[e.device];
    if (!d || !e.port) return null;
    const p = portsOf(d).filter(function (x) { return x.id === e.port; })[0];
    return p ? p.dir : null;
  };
  (doc.cables || []).forEach(function (c) {
    if (!c || !c.from || !c.to || !byId[c.from.device] || !byId[c.to.device]) return;
    if (!stateOk(statusOf(c), state === 'all' ? 'all' : state)) return;
    if (!carriesD(c.medium)) return;
    const a = ref(c.from), b = ref(c.to);
    add(a, b, c.id);
    if (c.bidirectional || (portDir(c.from) === 'io' && portDir(c.to) === 'io')) add(b, a, c.id);
  });
  ((overlay && overlay.routes) || []).forEach(function (rt) {
    if (!rt || !rt.from || !rt.to || !byId[rt.from.device] || !byId[rt.to.device]) return;
    if (!carriesD(rt.medium || 'other')) return;
    add(ref(rt.from), ref(rt.to), null);
  });
  // Device-level endpoints: dev:* <-> every port of that device, both ways (filtered by discipline).
  Object.keys(virtual).forEach(function (id) {
    const d = byId[id];
    if (!d) return;
    portsOf(d).forEach(function (p) {
      if (!carriesD(p.medium)) return;
      add(id + ':*', id + ':' + p.id);
      add(id + ':' + p.id, id + ':*');
    });
  });
  return {fwd: fwd, rev: rev, devices: byId};
}

function startRef(start) {
  if (typeof start === 'string') return start.indexOf(':') >= 0 ? start : start + ':*';
  return start.port ? start.device + ':' + start.port : start.device + ':*';
}

export function traceLocal(doc, overlay, start, opts) {
  opts = opts || {};
  const s = startRef(start);
  const sDev = s.split(':')[0];
  const graph = buildTraceGraph(doc, overlay, Object.assign({}, opts, {virtualFor: s.slice(-2) === ':*' ? sDev : null}));
  const depth = opts.depth || 24;
  const dir = opts.direction || 'down';
  const ports = new Set(), cables = new Set(), devices = new Set();
  function bfs(adj) {
    const lvl = {};
    lvl[s] = 0;
    const queue = [s];
    while (queue.length) {
      const n = queue.shift();
      if (lvl[n] >= depth) continue;
      (adj[n] || []).forEach(function (e) {
        if (e.cable) cables.add(e.cable);
        if (lvl[e.node] == null) { lvl[e.node] = lvl[n] + 1; queue.push(e.node); }
      });
    }
    Object.keys(lvl).forEach(function (n) {
      const i = n.indexOf(':');
      devices.add(n.slice(0, i));
      if (n.slice(i + 1) !== '*') ports.add(n);
    });
  }
  if (graph.devices[sDev]) {
    if (dir === 'down' || dir === 'both') bfs(graph.fwd);
    if (dir === 'up' || dir === 'both') bfs(graph.rev);
  }
  const res = {ports: ports, cables: cables, devices: devices};
  if (opts.paths) res.paths = tracePaths(graph, s, dir === 'up' ? 'up' : 'down', depth, opts.limit || 50);
  return res;
}

function tracePaths(graph, s, dir, depth, limit) {
  const adj = dir === 'up' ? graph.rev : graph.fwd;
  const found = [];
  let budget = 20000;
  const onPath = {};
  function walk(node, nodes, cabs) {
    if (--budget < 0) return;
    const next = (adj[node] || []).filter(function (e) { return !onPath[e.node]; });
    if (!next.length || nodes.length > depth) {
      if (nodes.length > 1) found.push({nodes: nodes.slice(), cables: cabs.slice()});
      return;
    }
    next.forEach(function (e) {
      onPath[e.node] = true;
      nodes.push(e.node);
      if (e.cable) cabs.push(e.cable);
      walk(e.node, nodes, cabs);
      if (e.cable) cabs.pop();
      nodes.pop();
      onPath[e.node] = false;
    });
  }
  onPath[s] = true;
  walk(s, [s], []);
  const paths = found.map(function (p) {
    const nodes = dir === 'up' ? p.nodes.slice().reverse() : p.nodes;
    const cabs = dir === 'up' ? p.cables.slice().reverse() : p.cables;
    const hops = nodes.filter(function (n) { return n.slice(-2) !== ':*'; }).map(function (n) {
      const i = n.indexOf(':');
      return {device: n.slice(0, i), port: n.slice(i + 1)};
    });
    return {hops: hops, cables: cabs, key: nodes.join(' ')};
  });
  paths.sort(function (a, b) {
    if (a.hops.length !== b.hops.length) return a.hops.length - b.hops.length;
    return a.key < b.key ? -1 : (a.key > b.key ? 1 : 0);
  });
  return paths.slice(0, limit).map(function (p) { return {hops: p.hops, cables: p.cables}; });
}

export function pathText(doc, path) {
  const byId = {};
  (doc.devices || []).forEach(function (d) { byId[d.id] = d; });
  const hops = path.hops || path;
  const parts = [];
  hops.forEach(function (h, i) {
    const d = byId[h.device] || {name: h.device, ports: []};
    const p = portsOf(d).filter(function (x) { return x.id === h.port; })[0];
    const pl = p ? portLabelOf(p) : h.port;
    if (i === hops.length - 1 && p && p.dir === 'in') {
      parts.push(d.name || d.id);
    } else if (i === 0 || h.device !== hops[i - 1].device) {
      parts.push((d.name || d.id) + ' \u00b7 ' + pl);
    } else {
      parts.push(pl);
    }
  });
  return parts.join(' \u2192 ');
}
