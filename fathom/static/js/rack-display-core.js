// Rack display core (pure): block colours, device images, annotations and airflow glyphs for
// the rack elevation, export and viewer (Rackula features, docs/notes/rackula.md B, C and G).
// `info` is the device's template summary (`GET /api/v2/library?ids=` or `doc.templates`); a
// `{templateId: summary}` map, as `rack-display.loadTemplateInfo` resolves, is accepted too.

export const DISPLAY_MODES = ['label', 'image', 'both'];

export const ANNOTATION_FIELDS = [
  {key: '', label: 'None'},
  {key: 'name', label: 'Name'},
  {key: 'model', label: 'Model'},
  {key: 'ip', label: 'IP address'},
  {key: 'serial', label: 'Serial'},
  {key: 'asset_tag', label: 'Asset tag'},
  {key: 'code', label: 'Code'},
  {key: 'power', label: 'Power'},
  {key: 'weight', label: 'Weight'},
  {key: 'status', label: 'Status'},
];

// Rackula's category palette (Dracula-derived, MIT); keys are Rackula category names.
export const CATEGORY_COLORS = {
  server: '#4A7A8A',
  network: '#7968A6',
  firewall: '#C0392B',
  storage: '#3D7A4A',
  power: '#A84A4A',
  kvm: '#926A40',
  'av-media': '#A85A7A',
  cooling: '#75753F',
  chassis: '#5A6A8A',
  shelf: '#6272A4',
  blank: '#44475A',
  'cable-management': '#6272A4',
  'patch-panel': '#6272A4',
  other: '#6272A4',
};

export const STORAGE = {
  display: 'fathom.ui.rack.display',
  annotate: 'fathom.ui.rack.annotate',
  face: 'fathom.ui.rack.face',
};

export const FALLBACK_COLOR = '#9aa3b5';

const HEX6 = /^#[0-9a-fA-F]{6}$/;
const HEX3 = /^#[0-9a-fA-F]{3}$/;
const own = Object.prototype.hasOwnProperty;

function isObj(v) {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

function str(v) {
  return v === null || v === undefined ? '' : String(v);
}

export function isHexColor(s) {
  return typeof s === 'string' && HEX6.test(s);
}

// The summary for this device out of `info` (a summary or a {templateId: summary} map). An
// object whose values are all objects and that has no `id` is a map without this device.
function infoFor(device, info) {
  if (!isObj(info)) return null;
  const tid = device && device.template;
  if (tid && own.call(info, tid) && isObj(info[tid])) return info[tid];
  if (typeof info.id === 'string') return info;
  const keys = Object.keys(info);
  if (!keys.length || keys.every(function (k) { return isObj(info[k]); })) return null;
  return info;
}

// The device's template: `info`, else the project template in `doc.templates`, else null.
export function templateInfo(doc, device, info) {
  const t = infoFor(device, info);
  if (t) return t;
  const tid = device && device.template;
  const list = doc && Array.isArray(doc.templates) ? doc.templates : [];
  for (let i = 0; i < list.length; i++) if (list[i] && list[i].id === tid && tid) return list[i];
  return null;
}

export function blockColor(device, vocab, info) {
  const r = device && device.rack;
  if (r && isHexColor(r.color)) return r.color;
  const t = infoFor(device, info);
  const cat = t && t.rack_category;
  if (typeof cat === 'string' && own.call(CATEGORY_COLORS, cat)) return CATEGORY_COLORS[cat];
  const kinds = vocab && vocab.kinds;
  const k = kinds && device && own.call(kinds, device.kind) ? kinds[device.kind] : null;
  const disc = (device && device.discipline) || (k && k.discipline) || 'other';
  const ds = vocab && vocab.disciplines;
  const d = ds && own.call(ds, disc) ? ds[disc] : null;
  return (d && d.color) || FALLBACK_COLOR;
}

export function deviceImage(device, info, face, opts) {
  if (face !== 'front' && face !== 'rear') return '';
  const o = opts || {};
  const key = 'image_' + face;
  const r = device && device.rack;
  const att = r && r[key];
  if (att && typeof o.attachmentUrl === 'function') return str(o.attachmentUrl(att));
  const t = infoFor(device, info);
  const path = t && t[key];
  if (typeof path !== 'string' || !path) return '';
  return (o.base || '') + 'static/rack-images/' + path.replace(/^\/+/, '');
}

// A finite number from a number or numeric string; null when unset or not numeric.
function num(v) {
  if (v === null || v === undefined || typeof v === 'boolean') return null;
  if (typeof v === 'string' && !v.trim()) return null;
  const n = Number(v);
  return isFinite(n) ? n : null;
}

// `<n>` with no trailing `.0` (12.0 → '12', 3.5 → '3.5').
export function formatNumber(n) {
  return String(n === Math.round(n) ? Math.round(n) : n);
}

// The device's value of `key` (`weight_kg`, `power_w`): device, else info, else doc.templates.
function measure(doc, device, key, info) {
  const d = num(device && device[key]);
  if (d !== null) return d;
  const t = infoFor(device, info);
  const i = t ? num(t[key]) : null;
  if (i !== null) return i;
  const p = templateInfo(doc, device, null);
  const v = p ? num(p[key]) : null;
  return v === null ? 0 : v;
}

function primaryIp(device) {
  const list = device && Array.isArray(device.interfaces) ? device.interfaces : [];
  let first = '';
  for (let i = 0; i < list.length; i++) {
    const f = list[i];
    if (!isObj(f)) continue;
    const ip = str(f.ip).trim();
    if (!ip) continue;
    if (f.role === 'primary') return ip;
    if (!first) first = ip;
  }
  return first;
}

export function annotationValue(doc, device, field, info) {
  if (!device) return '';
  const inv = isObj(device.inventory) ? device.inventory : {};
  switch (field) {
    case 'name': return str(device.name);
    case 'model': return (str(device.manufacturer) + ' ' + str(device.model)).trim();
    case 'ip': return primaryIp(device);
    case 'serial': return str(inv.serial);
    case 'asset_tag': return str(inv.asset_tag);
    case 'code': return str(device.code);
    case 'power': {
      const w = measure(doc, device, 'power_w', info);
      return w > 0 ? formatNumber(w) + ' W' : '';
    }
    case 'weight': {
      const kg = measure(doc, device, 'weight_kg', info);
      return kg > 0 ? formatNumber(kg) + ' kg' : '';
    }
    case 'status': return str(device.status) || 'installed';
    default: return '';
  }
}

const IN = '\u21e5';      // ⇥ air enters through this face
const OUT = '\u21a6';     // ↦ air leaves through this face
const RIGHT = '\u2192';   // →
const LEFT = '\u2190';    // ←
const SIDE = '\u2194';    // ↔
const MIXED = '\u21c4';   // ⇄

// Airflow as seen on `face` (NetBox values). Sideways flows are mirrored on the rear, which is
// viewed from behind. null for unknown, empty and passive.
export function airflowGlyph(airflow, face) {
  const rear = face === 'rear';
  switch (airflow) {
    case 'front-to-rear':
      return rear ? {glyph: OUT, title: 'Exhaust (airflow front to rear)'} : {glyph: IN, title: 'Intake (airflow front to rear)'};
    case 'rear-to-front':
      return rear ? {glyph: IN, title: 'Intake (airflow rear to front)'} : {glyph: OUT, title: 'Exhaust (airflow rear to front)'};
    case 'left-to-right':
      return {glyph: rear ? LEFT : RIGHT, title: 'Airflow left to right'};
    case 'right-to-left':
      return {glyph: rear ? RIGHT : LEFT, title: 'Airflow right to left'};
    case 'side-to-rear':
      return rear ? {glyph: OUT, title: 'Exhaust (airflow side to rear)'} : {glyph: SIDE, title: 'Side intake (airflow side to rear)'};
    case 'mixed':
      return {glyph: MIXED, title: 'Mixed airflow'};
    default:
      return null;
  }
}

function channel(c) {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

// WCAG 2 relative luminance of `#rrggbb` / `#rgb`; null when not a colour.
export function luminance(hex) {
  let s = typeof hex === 'string' ? hex.trim() : '';
  if (HEX3.test(s)) s = '#' + s[1] + s[1] + s[2] + s[2] + s[3] + s[3];
  if (!HEX6.test(s)) return null;
  const n = parseInt(s.slice(1), 16);
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

export function contrastRatio(l1, l2) {
  const a = Math.max(l1, l2);
  const b = Math.min(l1, l2);
  return (a + 0.05) / (b + 0.05);
}

// '#000' or '#fff', whichever contrasts more with `hex` (WCAG); '#fff' for a non-colour.
export function textColorOn(hex) {
  const l = luminance(hex);
  if (l === null) return '#fff';
  return contrastRatio(l, 0) > contrastRatio(l, 1) ? '#000' : '#fff';
}
