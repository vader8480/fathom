// Rack export (pure): the standalone SVG of one or more rack elevations used by
// the export dialog (rack-export.js), plus its filenames, remembered choices and
// the list of panel images to embed. Newer rack-core exports (rackWidthPx,
// itemBlocks, shelfChildBlocks, racksByRow, rackTotals, ITEM_TYPES) are
// feature-detected; rack-display-core functions arrive through opts
// (opts.blockColor, opts.annotationValue, opts.textColorOn) so this module
// imports in Node without them.

import * as rackCore from './rack-core.js';

export const STORAGE_KEY = 'fathom.ui.rack.export';

export const FACE_CHOICES = [
  {key: 'front', label: 'Front'},
  {key: 'rear', label: 'Rear'},
  {key: 'both', label: 'Front + rear'},
];

export const FORMATS = [
  {key: 'svg', label: 'SVG', ext: 'svg', action: 'Download SVG'},
  {key: 'png', label: 'PNG (2\u00d7)', ext: 'png', action: 'Download PNG'},
  {key: 'print', label: 'Print / PDF', ext: 'pdf', action: 'Print'},
];

// Annotation fields when rack-display-core (ANNOTATION_FIELDS) is not available.
export const BASIC_FIELDS = [
  {key: '', label: 'None'},
  {key: 'name', label: 'Name'},
  {key: 'model', label: 'Model'},
];

export const CATEGORY_LABELS = {
  server: 'Server', network: 'Network', firewall: 'Firewall', 'patch-panel': 'Patch panel', power: 'Power',
  storage: 'Storage', kvm: 'KVM', 'av-media': 'AV / media', cooling: 'Cooling', shelf: 'Shelf', blank: 'Blank',
  'cable-management': 'Cable management', chassis: 'Chassis', other: 'Other',
};

export const GEOM = {
  pad: 24, ruLabelW: 26, frame: 8, faceGap: 28, rackGap: 48, groupGap: 72, annGap: 10, annW: 150,
  rowCaptionH: 22, titleH: 42, captionH: 20, legendTitleH: 22, legendRowH: 20, footerH: 34, minW: 420,
};

const FONT = 'system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif';
const FALLBACK_COLOR = '#9aa3b5';
const ITEM_FALLBACK = '#6272a4';
// Largest PNG canvas Safari allows (iOS caps the area at 16.7 Mpx).
const MAX_CANVAS_AREA = 16777216;
const MAX_CANVAS_SIDE = 16384;

function list(v) {
  return Array.isArray(v) ? v : [];
}

function str(v) {
  return v === undefined || v === null ? '' : String(v);
}

function fn(name) {
  return typeof rackCore[name] === 'function' ? rackCore[name] : null;
}

// rack-core plus test or caller overrides (opts.core), so missing exports can be supplied.
function coreWith(opts) {
  return opts && opts.core ? Object.assign({}, rackCore, opts.core) : rackCore;
}

function isHex(c) {
  return typeof c === 'string' && /^#[0-9a-fA-F]{6}$/.test(c);
}

// XML text and attribute escaping; drops characters XML 1.0 cannot carry.
export function xmlEsc(s) {
  return str(s)
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\uFFFE\uFFFF]/g, '')
    .replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; });
}

function num(n) {
  const v = Math.round(n * 100) / 100;
  return String(Object.is(v, -0) ? 0 : v);
}

function attrs(o) {
  return Object.keys(o).filter(function (k) { return o[k] !== undefined && o[k] !== null && o[k] !== ''; }).map(function (k) {
    const v = o[k];
    return ' ' + k + '="' + (typeof v === 'number' ? num(v) : xmlEsc(v)) + '"';
  }).join('');
}

function el(tag, o, inner) {
  return '<' + tag + attrs(o || {}) + (inner === undefined ? '/>' : '>' + inner + '</' + tag + '>');
}

function text(x, y, s, o) {
  return el('text', Object.assign({x: x, y: y}, o || {}), xmlEsc(s));
}

// ------------------------------------------------------------------ choices

export function normalizeFace(face) {
  return face === 'rear' || face === 'both' ? face : 'front';
}

export function facesOf(face) {
  const f = normalizeFace(face);
  return f === 'both' ? ['front', 'rear'] : [f];
}

export function formatOf(key) {
  return FORMATS.filter(function (f) { return f.key === key; })[0] || FORMATS[0];
}

// ANNOTATION_FIELDS entries may be {key, label} or bare keys; '' (None) always comes first.
export function normalizeFields(fields) {
  const out = [];
  const seen = {};
  list(fields).forEach(function (f) {
    const o = typeof f === 'string' ? {key: f, label: ''} : (f && typeof f === 'object' ? {key: str(f.key), label: str(f.label)} : null);
    if (!o || seen[o.key]) return;
    seen[o.key] = true;
    if (!o.label) o.label = o.key ? o.key.charAt(0).toUpperCase() + o.key.slice(1).replace(/_/g, ' ') : 'None';
    out.push(o);
  });
  if (!seen['']) out.unshift({key: '', label: 'None'});
  else if (out[0].key !== '') out.sort(function (a, b) { return (a.key === '' ? 0 : 1) - (b.key === '' ? 0 : 1); });
  return out.length > 1 ? out : BASIC_FIELDS.slice();
}

export const DEFAULT_PREFS = {v: 1, face: 'front', format: 'svg', legend: true, annotate: ''};

// The parsed (or raw JSON) value of fathom.ui.rack.export -> {v: 1, face, format, legend, annotate}.
export function readPrefs(raw) {
  let o = raw;
  if (typeof raw === 'string') {
    try { o = JSON.parse(raw); } catch (e) { o = null; }
  }
  const out = Object.assign({}, DEFAULT_PREFS);
  if (!o || typeof o !== 'object' || Array.isArray(o)) return out;
  if (o.face === 'front' || o.face === 'rear' || o.face === 'both') out.face = o.face;
  if (FORMATS.some(function (f) { return f.key === o.format; })) out.format = o.format;
  if (typeof o.legend === 'boolean') out.legend = o.legend;
  if (typeof o.annotate === 'string' && /^[a-z_]{0,32}$/.test(o.annotate)) out.annotate = o.annotate;
  return out;
}

function safeName(s) {
  return str(s).replace(/\.{2,}/g, '-').replace(/[^A-Za-z0-9._-]+/g, '-').replace(/-{2,}/g, '-').replace(/^[-.]+|[-.]+$/g, '');
}

// <project>-<rack id | 'racks'>-<face>.<ext>
export function exportFilename(project, rackIds, face, ext) {
  const ids = list(rackIds);
  const what = ids.length === 1 ? safeName(ids[0]) || 'rack' : 'racks';
  return (safeName(project) || 'fathom') + '-' + what + '-' + normalizeFace(face) + '.' + (ext || 'svg');
}

// PNG scale: `want` (2) unless the canvas would exceed what Safari can allocate.
export function pngScale(width, height, want) {
  const w = Math.max(1, Number(width) || 1);
  const hh = Math.max(1, Number(height) || 1);
  let s = Number(want) > 0 ? Number(want) : 2;
  s = Math.min(s, MAX_CANVAS_SIDE / w, MAX_CANVAS_SIDE / hh, Math.sqrt(MAX_CANVAS_AREA / (w * hh)));
  return Math.max(0.1, Math.floor(s * 100) / 100);
}

// {width, height} from the root <svg> of a string built here.
export function svgSize(svg) {
  const m = /<svg\b[^>]*>/.exec(str(svg));
  if (!m) return {width: 0, height: 0};
  const w = /\swidth="([\d.]+)"/.exec(m[0]);
  const hh = /\sheight="([\d.]+)"/.exec(m[0]);
  return {width: w ? Number(w[1]) : 0, height: hh ? Number(hh[1]) : 0};
}

// '#000' or '#fff', whichever contrasts more (WCAG relative luminance).
export function textColorOn(hex) {
  if (!isHex(hex)) return '#000';
  const c = [1, 3, 5].map(function (i) {
    const v = parseInt(hex.substr(i, 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  const L = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  return (L + 0.05) / 0.05 >= 1.05 / (L + 0.05) ? '#000' : '#fff';
}

function charW(fontPx) {
  return fontPx * 0.58;
}

export function textWidth(s, fontPx) {
  return str(s).length * charW(fontPx);
}

// Truncate with an ellipsis so the text roughly fits `width` px at `fontPx`.
export function fitText(s, width, fontPx) {
  const t = str(s);
  const max = Math.floor(width / charW(fontPx));
  if (max <= 0) return '';
  if (t.length <= max) return t;
  return max <= 1 ? '\u2026' : t.slice(0, max - 1).replace(/\s+$/, '') + '\u2026';
}

// ------------------------------------------------------------------ doc helpers

function rackOf(doc, id) {
  const r = list(doc && doc.racks);
  for (let i = 0; i < r.length; i++) if (r[i].id === id) return r[i];
  return null;
}

function deviceOf(doc, id) {
  const d = list(doc && doc.devices);
  for (let i = 0; i < d.length; i++) if (d[i].id === id) return d[i];
  return null;
}

function infoOf(doc, dev, info) {
  const tid = dev && dev.template;
  if (!tid) return {};
  if (info && info[tid]) return info[tid];
  const t = list(doc && doc.templates).filter(function (x) { return x && x.id === tid; })[0];
  return t || {};
}

function rackWidth(C, rack) {
  if (typeof C.rackWidthPx === 'function') {
    const w = Number(C.rackWidthPx(rack));
    if (w > 0) return w;
  }
  const inch = Number(rack && rack.width_in);
  return inch > 0 && inch !== 19 ? Math.round(C.RACK_W * inch / 19) : C.RACK_W;
}

function unitsOf(C, rack) {
  return typeof C.rackUnits === 'function' ? C.rackUnits(rack) : Math.max(1, Math.min(60, parseInt(rack && rack.units, 10) || 1));
}

function ruLabel(C, rack, u) {
  return typeof C.ruLabel === 'function' ? C.ruLabel(rack, u) : String(u);
}

function devicesIn(doc, rackId) {
  return list(doc && doc.devices).filter(function (d) { return d && d.rack && d.rack.id === rackId && !d.auto; });
}

// Unique template ids of the devices in the given racks (for the library lookup).
export function templateIds(doc, rackIds) {
  const seen = {};
  const out = [];
  list(rackIds).forEach(function (rid) {
    devicesIn(doc, rid).forEach(function (d) {
      if (d.template && !seen[d.template]) { seen[d.template] = true; out.push(String(d.template)); }
    });
  });
  return out;
}

// Panel images to embed: [{device, face, att}] for a device-level attachment
// (rack.image_<face>), else [{device, face, path}] for a template image path
// (relative to static/rack-images/). Never the front image on the rear.
export function imageRequests(doc, rackIds, face, info) {
  const out = [];
  const faces = facesOf(face);
  list(rackIds).forEach(function (rid) {
    devicesIn(doc, rid).forEach(function (d) {
      const t = infoOf(doc, d, info);
      faces.forEach(function (f) {
        const att = d.rack['image_' + f];
        if (att) { out.push({device: d.id, face: f, att: String(att)}); return; }
        const p = t['image_' + f];
        if (p && typeof p === 'string' && !/^[a-z]+:|^\/\/|(^|\/)\.\.(\/|$)/i.test(p)) out.push({device: d.id, face: f, path: p.replace(/^\/+/, '')});
      });
    });
  });
  return out;
}

function disciplineOf(dev, vocab) {
  if (dev.discipline) return dev.discipline;
  const k = vocab && vocab.kinds && vocab.kinds[dev.kind];
  return (k && k.discipline) || 'other';
}

function disciplineColor(disc, vocab) {
  const d = vocab && vocab.disciplines && vocab.disciplines[disc];
  return (d && isHex(d.color) && d.color) || FALLBACK_COLOR;
}

function disciplineLabel(disc, vocab) {
  const d = vocab && vocab.disciplines && vocab.disciplines[disc];
  return (d && d.label) || (disc ? disc.charAt(0).toUpperCase() + disc.slice(1) : 'Other');
}

function itemType(C, type) {
  return list(C.ITEM_TYPES).filter(function (t) { return t && t.type === type; })[0] || null;
}

// {color, key, label} of a device block. key groups the legend; '' = not listed (own colour).
function deviceStyle(doc, dev, o) {
  const vocab = o.vocab || {};
  const info = infoOf(doc, dev, o.info);
  const disc = disciplineOf(dev, vocab);
  let color = '';
  if (typeof o.blockColor === 'function') {
    try { color = o.blockColor(dev, vocab, info); } catch (e) { color = ''; }
  }
  const own = isHex(dev.rack && dev.rack.color) ? dev.rack.color : '';
  if (!isHex(color)) color = own || disciplineColor(disc, vocab);
  if (own && color.toLowerCase() === own.toLowerCase()) return {color: color, key: '', label: ''};
  const cat = info && info.rack_category;
  if (cat && typeof o.blockColor === 'function' && color.toLowerCase() !== disciplineColor(disc, vocab).toLowerCase()) {
    return {color: color, key: 'cat:' + cat, label: CATEGORY_LABELS[cat] || cat};
  }
  return {color: color, key: 'disc:' + disc, label: disciplineLabel(disc, vocab)};
}

function itemStyle(C, b) {
  const t = itemType(C, b.type);
  const color = isHex(b.color) ? b.color : (t && isHex(t.color) ? t.color : ITEM_FALLBACK);
  return {color: color, key: 'item:' + b.type, label: (t && t.label) || b.type || 'Accessory'};
}

function annotationOf(doc, dev, field, o) {
  if (!field) return '';
  if (typeof o.annotationValue === 'function') {
    try { return str(o.annotationValue(doc, dev, field, infoOf(doc, dev, o.info))); } catch (e) { return ''; }
  }
  if (field === 'name') return str(dev.name || dev.id);
  if (field === 'model') return (str(dev.manufacturer) + ' ' + str(dev.model)).trim();
  return '';
}

function annotateField(a) {
  if (a === true) return 'name';
  return typeof a === 'string' ? a : '';
}

function fieldLabel(field, o) {
  const f = normalizeFields(o.fields || BASIC_FIELDS).filter(function (x) { return x.key === field; })[0];
  return f ? f.label : field;
}

function imageFor(o, devId, face, faces, behind) {
  const v = o.images && o.images[devId];
  if (!v) return '';
  if (typeof v === 'string') return !behind && (faces.length === 1 || face === 'front') ? v : '';
  return typeof v[face] === 'string' ? v[face] : '';
}

// ------------------------------------------------------------------ per-face scene

// Everything drawn on one face of one rack, in rack-local px (x 0..rackW, y 0..units*RU_PX).
function faceScene(doc, C, rack, face, o) {
  const rackW = rackWidth(C, rack);
  const items = typeof C.itemBlocks === 'function' ? list(C.itemBlocks(doc, rack.id, face)) : [];
  const children = typeof C.shelfChildBlocks === 'function' ? list(C.shelfChildBlocks(doc, rack.id, face)) : [];
  const childIds = {};
  children.forEach(function (c) { childIds[c.device] = true; });
  const devices = list(C.faceBlocks(doc, rack.id, face)).filter(function (b) { return !childIds[b.device]; }).map(function (b) {
    const half = rackW / 2;
    return Object.assign({}, b, {x: b.side === 'right' ? half : 0, w: b.side === 'full' || !b.side ? rackW : half});
  });
  const shelves = {};
  items.forEach(function (b) { if (b.type === 'shelf') shelves[b.item || String(b.id).replace(/^item:/, '')] = b; });
  const kids = children.map(function (c) {
    const shelf = shelves[c.item] || null;
    const slots = Math.max(1, Math.min(4, parseInt((shelf && shelf.slots) || c.slots, 10) || 2));
    const slot = Math.max(0, parseInt(c.slot, 10) || 0);
    const cellW = rackW / slots;
    const y = isFinite(c.y) ? Number(c.y) : (shelf ? shelf.y : 0);
    const hh = isFinite(c.h) && c.h > 0 ? Number(c.h) : (shelf ? shelf.h : C.RU_PX);
    return {device: c.device, item: c.item, slot: slot, x: slot * cellW + 2, y: y, w: cellW - 4, h: hh, behind: !!c.behind};
  });
  return {rackW: rackW, devices: devices, items: items, children: kids};
}

// ------------------------------------------------------------------ drawing

function drawItem(b, x, y, w, hh, st, C) {
  const fg = textColorOn(st.color);
  const out = [];
  const dim = b.behind ? 0.45 : 1;
  const cx = x + w / 2;
  const cy = y + hh / 2;
  if (b.type !== 'lacing_bar') {
    out.push(el('rect', {x: x, y: y, width: w, height: hh, fill: st.color, 'fill-opacity': dim, stroke: '#1d2230', 'stroke-opacity': 0.35, 'stroke-width': 1}));
  }
  let labelX = cx;
  let labelY = cy + 3.5;
  if (b.type === 'vent') {
    [0.08, 0.17, 0.26, 0.66, 0.75, 0.84].forEach(function (f) {
      out.push(el('rect', {x: x + w * f, y: y + hh * 0.3, width: w * 0.07, height: hh * 0.4, rx: 2, fill: '#000', 'fill-opacity': 0.35}));
    });
  } else if (b.type === 'shelf') {
    const slots = Math.max(1, Math.min(4, parseInt(b.slots, 10) || 2));
    out.push(el('rect', {x: x, y: y + hh - 4, width: w, height: 4, fill: '#000', 'fill-opacity': 0.35}));
    for (let i = 1; i < slots; i++) {
      out.push(el('line', {x1: x + i * w / slots, y1: y + 2, x2: x + i * w / slots, y2: y + hh - 4, stroke: fg, 'stroke-opacity': 0.4, 'stroke-dasharray': '3 3'}));
    }
  } else if (b.type === 'drawer') {
    const tall = hh >= 30;
    const hx = tall ? cx : x + w * 0.75;
    out.push(el('rect', {x: hx - 22, y: tall ? y + hh - 13 : cy - 3, width: 44, height: 6, rx: 3, fill: fg, 'fill-opacity': 0.55}));
    if (tall) labelY = y + 15;
    else labelX = x + w * 0.35;
  } else if (b.type === 'cable_manager') {
    [0.05, 0.16, 0.27, 0.73, 0.84, 0.95].forEach(function (f) {
      out.push(el('rect', {x: x + w * f - 5, y: y + 3, width: 10, height: hh - 6, rx: 4, fill: 'none', stroke: fg, 'stroke-opacity': 0.6, 'stroke-width': 1.5}));
    });
  } else if (b.type === 'brush') {
    out.push(el('rect', {x: x + w * 0.08, y: cy - 2, width: w * 0.84, height: 4, fill: '#000', 'fill-opacity': 0.5}));
  } else if (b.type === 'lacing_bar') {
    out.push(el('rect', {x: x + 4, y: cy - 2, width: w - 8, height: 4, rx: 2, fill: st.color, 'fill-opacity': dim}));
  }
  const label = b.type === 'lacing_bar' || b.type === 'brush' ? '' : str(b.label) || (b.type === 'shelf' ? '' : st.label);
  if (label && hh >= 12) {
    const room = b.type === 'shelf' ? w - 12 : b.type === 'vent' || b.type === 'cable_manager' ? w * 0.36 : b.type === 'drawer' && hh < 30 ? w * 0.5 : w - 12;
    out.push(text(b.type === 'shelf' ? x + 6 : labelX, b.type === 'shelf' ? y + Math.min(hh - 7, 12) : labelY, fitText(label, room, 10),
      {fill: fg, 'font-size': 10, 'text-anchor': b.type === 'shelf' ? 'start' : 'middle', 'fill-opacity': 0.85}));
  }
  return '<g class="rx-item" data-item="' + xmlEsc(b.item || b.id) + '" data-type="' + xmlEsc(b.type) + '">' + out.join('') + '</g>';
}

function drawDevice(doc, dev, b, x, y, w, hh, st, img, face, o) {
  const fg = textColorOn(st.color);
  const out = [];
  const behind = !!b.behind;
  out.push(el('rect', {x: x + 0.5, y: y + 0.5, width: Math.max(0, w - 1), height: Math.max(0, hh - 1), rx: 2, fill: st.color,
    'fill-opacity': behind ? 0.3 : 1, stroke: behind ? st.color : '#0b1020', 'stroke-opacity': behind ? 0.9 : 0.35,
    'stroke-dasharray': behind ? '4 3' : null}));
  const name = str(dev.name || dev.id);
  const model = (str(dev.manufacturer) + ' ' + str(dev.model)).trim();
  const ru = (b.height || 1) + 'U';
  const ink = behind ? '#1d2230' : fg;
  if (img) {
    out.push(el('image', {x: x + 1, y: y + 1, width: Math.max(0, w - 2), height: Math.max(0, hh - 2), preserveAspectRatio: 'none',
      href: img, 'xlink:href': img, opacity: behind ? 0.5 : 1}));
    const lw = Math.min(w - 2, textWidth(name, 10) + 10);
    out.push(el('rect', {x: x + 1, y: y + 1, width: lw, height: 14, fill: '#000', 'fill-opacity': 0.6}));
    out.push(text(x + 6, y + 11.5, fitText(name, lw - 8, 10), {fill: '#fff', 'font-size': 10, 'font-weight': 600}));
  } else if (hh >= 34 && w >= 60) {
    out.push(text(x + 7, y + 15, fitText(name, w - 40, 11), {fill: ink, 'font-size': 11, 'font-weight': 600}));
    if (model) out.push(text(x + 7, y + 28, fitText(model, w - 14, 10), {fill: ink, 'font-size': 10, 'fill-opacity': 0.8}));
    out.push(text(x + w - 6, y + 15, ru, {fill: ink, 'font-size': 10, 'text-anchor': 'end', 'fill-opacity': 0.8}));
  } else {
    const room = w - 14 - (w >= 100 ? 26 : 0);
    const nameFit = fitText(name, room, 11);
    out.push(text(x + 7, y + hh / 2 + 4, nameFit, {fill: ink, 'font-size': 11, 'font-weight': 600}));
    const left = room - textWidth(nameFit, 11) - 8;
    if (model && nameFit === name && left > 30) {
      out.push(text(x + 7 + textWidth(name, 11) + 8, y + hh / 2 + 4, fitText(model, left, 10), {fill: ink, 'font-size': 10, 'fill-opacity': 0.75}));
    }
    if (w >= 100) out.push(text(x + w - 6, y + hh / 2 + 4, ru, {fill: ink, 'font-size': 10, 'text-anchor': 'end', 'fill-opacity': 0.8}));
  }
  const title = name + (model ? ' \u00b7 ' + model : '') + ' \u00b7 ' + ru + (behind ? ' (' + (face === 'front' ? 'rear' : 'front') + ' mounted)' : '');
  return '<g class="rx-device" data-device="' + xmlEsc(dev.id) + '"' + (behind ? ' data-behind="1"' : '') + '>' +
    el('title', {}, xmlEsc(title)) + out.join('') + '</g>';
}

// Width of one face column (U labels + frame + optional annotation column).
function faceColumnW(rackW, annotate) {
  const g = GEOM;
  return g.ruLabelW + rackW + 2 * g.frame + (annotate ? g.annGap + g.annW : 0);
}

function drawFace(doc, C, rack, face, ox, oy, o, legend) {
  const g = GEOM;
  const RU = C.RU_PX;
  const units = unitsOf(C, rack);
  const sc = faceScene(doc, C, rack, face, o);
  const field = annotateField(o.annotate);
  const faces = facesOf(o.face);
  const bx = ox + g.ruLabelW + g.frame;
  const by = oy + g.captionH + g.frame;
  const out = [];
  out.push(text(ox + g.ruLabelW + g.frame + sc.rackW / 2, oy + 13, face === 'rear' ? 'Rear' : 'Front',
    {'font-size': 11, 'font-weight': 600, fill: '#4a5368', 'text-anchor': 'middle', 'letter-spacing': 0.6}));
  out.push(el('rect', {x: ox + g.ruLabelW, y: oy + g.captionH, width: sc.rackW + 2 * g.frame, height: units * RU + 2 * g.frame, rx: 3, fill: '#2b3142'}));
  out.push(el('rect', {x: bx, y: by, width: sc.rackW, height: units * RU, fill: '#f3f4f8'}));
  const lines = [];
  for (let u = 1; u <= units; u++) {
    const y = by + (units - u) * RU;
    if (u < units) lines.push('M' + num(bx) + ' ' + num(y) + 'h' + num(sc.rackW));
    out.push(text(ox + g.ruLabelW - 4, y + RU / 2 + 3.5, ruLabel(C, rack, u), {'font-size': 9, fill: '#6b7488', 'text-anchor': 'end', class: 'rx-ru'}));
  }
  if (lines.length) out.push(el('path', {d: lines.join(''), stroke: '#dde1ea', 'stroke-width': 1, fill: 'none'}));
  sc.items.forEach(function (b) {
    const st = itemStyle(C, b);
    legend.add(st);
    out.push(drawItem(b, bx, by + b.y, sc.rackW, b.h, st, C));
  });
  const ann = [];
  sc.devices.concat(sc.children).forEach(function (b) {
    const dev = deviceOf(doc, b.device);
    if (!dev) return;
    const st = deviceStyle(doc, dev, o);
    legend.add(st);
    const img = imageFor(o, dev.id, face, faces, b.behind);
    out.push(drawDevice(doc, dev, b, bx + b.x, by + b.y, b.w, b.h, st, img, face, o));
    if (field && !b.behind) {
      const v = annotationOf(doc, dev, field, o);
      if (v) ann.push({y: by + b.y + b.h / 2, text: v});
    }
  });
  if (field) {
    const ax = bx + sc.rackW + g.frame + g.annGap;
    out.push(text(ax, oy + 13, fieldLabel(field, o), {'font-size': 10, 'font-weight': 600, fill: '#6b7488'}));
    const rows = {};
    ann.forEach(function (a) {
      const k = Math.round(a.y);
      rows[k] = rows[k] ? rows[k] + ', ' + a.text : a.text;
    });
    const keys = Object.keys(rows).map(Number).sort(function (a, b) { return a - b; });
    out.push('<g class="rx-annotations" data-field="' + xmlEsc(field) + '">' + keys.map(function (k) {
      return el('line', {x1: bx + sc.rackW + g.frame, y1: k, x2: ax - 2, y2: k, stroke: '#b7bdcb', 'stroke-width': 1}) +
        text(ax, k + 3.5, fitText(rows[k], g.annW, 10), {'font-size': 10, fill: '#2b3142', class: 'rx-ann'});
    }).join('') + '</g>');
  }
  return {svg: '<g class="rx-face" data-face="' + face + '">' + out.join('') + '</g>', w: faceColumnW(sc.rackW, !!field), h: g.captionH + units * RU + 2 * g.frame};
}

function totalsLine(doc, C, rack, o) {
  const units = unitsOf(C, rack);
  const parts = [units + ' U'];
  if (rack.width_in && Number(rack.width_in) !== 19) parts.push(rack.width_in + '\u2033');
  if (typeof C.rackTotals === 'function') {
    let t = null;
    try { t = C.rackTotals(doc, rack.id, o.info); } catch (e) { t = null; }
    if (t) {
      parts.push(t.used_u + ' used \u00b7 ' + t.free_u + ' free');
      if (t.weight_kg > 0) parts.push(t.weight_kg + ' kg' + (t.max_load_kg ? ' / ' + t.max_load_kg : ''));
      if (t.power_w > 0) parts.push(t.power_w + ' W' + (t.power_limit_w ? ' / ' + t.power_limit_w : ''));
    }
  }
  return parts.join(' \u00b7 ');
}

function makeLegend() {
  const seen = {};
  const entries = [];
  return {
    add: function (st) {
      if (!st.key || seen[st.key]) return;
      seen[st.key] = true;
      entries.push({key: st.key, label: st.label, color: st.color});
    },
    entries: entries,
  };
}

// Legend entries (categories / disciplines / accessory types) of the exported racks, in drawing order.
export function legendEntries(doc, rackIds, opts) {
  const o = Object.assign({}, opts || {});
  const C = coreWith(o);
  const legend = makeLegend();
  list(rackIds).forEach(function (id) {
    const rack = rackOf(doc, id);
    if (!rack) return;
    facesOf(o.face).forEach(function (f) { drawFace(doc, C, rack, f, 0, 0, o, legend); });
  });
  return sortLegend(legend.entries);
}

// Categories, then disciplines, then accessories; a discipline sharing a
// category's label (both "Network") is marked so the two swatches read apart.
function sortLegend(entries) {
  const rank = function (k) { return k.indexOf('item:') === 0 ? 2 : k.indexOf('cat:') === 0 ? 0 : 1; };
  const cats = {};
  entries.forEach(function (e) { if (rank(e.key) === 0) cats[e.label.toLowerCase()] = true; });
  return entries.map(function (e) {
    return rank(e.key) === 1 && cats[e.label.toLowerCase()] ? Object.assign({}, e, {label: e.label + ' (discipline)'}) : Object.assign({}, e);
  }).sort(function (a, b) { return rank(a.key) - rank(b.key) || (a.label < b.label ? -1 : a.label > b.label ? 1 : 0); });
}

function groupsOf(C, racks) {
  if (typeof C.racksByRow === 'function') {
    try {
      const g = list(C.racksByRow(racks));
      if (g.length) return g.map(function (x) { return {row: str(x.row), racks: list(x.racks)}; });
    } catch (e) { /* fall through to one group per rack */ }
  }
  return racks.map(function (r) { return {row: '', racks: [r]}; });
}

// Standalone SVG of the racks laid out left to right (grouped by row when
// rack-core has racksByRow). opts: {face: front|rear|both, annotate: field
// key, legend: bool (default true), images: {deviceId: dataUrl | {front,
// rear}}, info: {templateId: summary}, vocab, title, date, fields (annotation
// field labels), blockColor, annotationValue, core (rack-core overrides)}.
export function buildRackSvg(doc, rackIds, opts) {
  const o = Object.assign({legend: true}, opts || {});
  o.face = normalizeFace(o.face);
  const C = coreWith(o);
  const g = GEOM;
  const racks = list(rackIds).map(function (id) { return rackOf(doc, id); }).filter(Boolean);
  const groups = groupsOf(C, racks);
  const hasRows = groups.some(function (gr) { return gr.row; });
  const legend = makeLegend();
  const body = [];
  const top = g.pad + (hasRows ? g.rowCaptionH : 0);
  let x = g.pad;
  let maxH = 0;
  groups.forEach(function (gr, gi) {
    if (gi > 0) x += g.groupGap;
    const gx = x;
    gr.racks.forEach(function (rack, ri) {
      if (ri > 0) x += g.rackGap;
      const parts = [];
      let fx = x;
      let colH = 0;
      facesOf(o.face).forEach(function (f, fi) {
        if (fi > 0) fx += g.faceGap;
        const face = drawFace(doc, C, rack, f, fx, top + g.titleH, o, legend);
        parts.push(face.svg);
        fx += face.w;
        colH = Math.max(colH, face.h);
      });
      const colW = fx - x;
      const name = str(rack.name || rack.id);
      const head = text(x, top + 16, fitText(name, colW, 14), {'font-size': 14, 'font-weight': 700, fill: '#151a26'}) +
        text(x, top + 32, fitText(totalsLine(doc, C, rack, o), colW, 10), {'font-size': 10, fill: '#5b6478'});
      body.push('<g class="rx-rack" data-rack="' + xmlEsc(rack.id) + '">' + el('title', {}, xmlEsc(name)) + head + parts.join('') + '</g>');
      maxH = Math.max(maxH, g.titleH + colH);
      x = fx;
    });
    if (gr.row) {
      body.push('<g class="rx-row" data-row="' + xmlEsc(gr.row) + '">' +
        text(gx, g.pad + 12, fitText('Row ' + gr.row, Math.max(80, x - gx), 11), {'font-size': 11, 'font-weight': 600, fill: '#4a5368', 'letter-spacing': 0.4}) +
        el('path', {d: 'M' + num(gx) + ' ' + num(g.pad + 17) + 'H' + num(x), stroke: '#b7bdcb', 'stroke-width': 1, fill: 'none'}) + '</g>');
    }
  });
  if (!racks.length) {
    body.push(text(g.pad, top + 20, 'No racks selected', {'font-size': 12, fill: '#5b6478'}));
    maxH = 40;
    x = g.pad + 200;
  }
  const width = Math.max(g.minW, Math.ceil(x + g.pad));
  let y = top + maxH + 16;
  const entries = sortLegend(legend.entries);
  let legendSvg = '';
  if (o.legend !== false && entries.length) {
    const avail = width - 2 * g.pad;
    let lx = 0;
    let ly = 0;
    const cells = [];
    entries.forEach(function (e) {
      const label = fitText(e.label, avail - 24, 11);
      const cw = 18 + textWidth(label, 11) + 18;
      if (lx > 0 && lx + cw > avail) { lx = 0; ly += g.legendRowH; }
      cells.push('<g class="rx-legend-entry" data-key="' + xmlEsc(e.key) + '">' +
        el('rect', {x: g.pad + lx, y: y + g.legendTitleH + ly, width: 12, height: 12, rx: 2, fill: e.color, stroke: '#0b1020', 'stroke-opacity': 0.25}) +
        text(g.pad + lx + 18, y + g.legendTitleH + ly + 10, label, {'font-size': 11, fill: '#2b3142'}) + '</g>');
      lx += cw;
    });
    legendSvg = '<g class="rx-legend">' + text(g.pad, y + 12, 'Legend', {'font-size': 11, 'font-weight': 600, fill: '#4a5368', 'letter-spacing': 0.4}) + cells.join('') + '</g>';
    y += g.legendTitleH + ly + g.legendRowH + 4;
  }
  const title = str(o.title || (doc && doc.meta && doc.meta.title) || '');
  const footY = y + 8;
  const footLeft = [title, str(o.date)].filter(Boolean).join(' \u00b7 ');
  const footer = '<g class="rx-footer">' +
    el('path', {d: 'M' + g.pad + ' ' + num(footY) + 'H' + num(width - g.pad), stroke: '#d5d9e3', 'stroke-width': 1, fill: 'none'}) +
    (footLeft ? text(g.pad, footY + 17, fitText(footLeft, width - 2 * g.pad - 70, 10), {'font-size': 10, fill: '#5b6478'}) : '') +
    text(width - g.pad, footY + 17, 'Fathom', {'font-size': 10, fill: '#8e97ab', 'text-anchor': 'end'}) + '</g>';
  const height = Math.ceil(footY + g.footerH - 8 + g.pad / 2);
  const docTitle = (title ? title + ' \u00b7 ' : '') + (racks.length === 1 ? str(racks[0].name || racks[0].id) : 'Racks') + ' (' +
    FACE_CHOICES.filter(function (f) { return f.key === o.face; })[0].label.toLowerCase() + ')';
  return '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1"' +
    attrs({width: width, height: height, viewBox: '0 0 ' + width + ' ' + height, 'font-family': FONT, 'data-face': o.face}) + '>' +
    el('title', {}, xmlEsc(docTitle)) +
    el('rect', {x: 0, y: 0, width: width, height: height, fill: '#ffffff'}) +
    body.join('') + legendSvg + footer + '</svg>';
}
