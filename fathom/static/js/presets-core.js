// Device type presets (pure helpers, ES2018, no DOM): search / grouping of the presets returned by
// GET /api/v2/presets, the pre-filled "new device" form state, and the template handed to
// addDeviceFromTemplateOps once the user has edited that form.

export const PRESET_GROUPS = ['Power', 'Network & IT', 'Audio', 'Video', 'Lighting'];

function norm(s) {
  return String(s == null ? '' : s).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

function haystack(p) {
  return norm([p.id, p.label, p.kind, p.group].concat(p.aliases || [], p.tags || []).join(' '));
}

// Presets whose text contains every query token, in group order then preset order.
export function filterPresets(presets, query, groups) {
  const order = groups && groups.length ? groups : PRESET_GROUPS;
  const words = norm(query).split(' ').filter(Boolean);
  const out = (presets || []).filter(function (p) {
    if (!words.length) return true;
    const hay = haystack(p);
    return words.every(function (w) { return hay.indexOf(w) >= 0; });
  });
  const rank = function (p) { const i = order.indexOf(p.group); return i < 0 ? order.length : i; };
  return out.map(function (p, i) { return { p: p, i: i }; })
    .sort(function (a, b) { return (rank(a.p) - rank(b.p)) || (a.i - b.i); })
    .map(function (x) { return x.p; });
}

// [{group, items}] in group order; empty groups are omitted.
export function groupPresets(presets, groups) {
  const order = (groups && groups.length ? groups : PRESET_GROUPS).slice();
  const by = {};
  (presets || []).forEach(function (p) {
    const g = p.group || 'Other';
    if (order.indexOf(g) < 0) order.push(g);
    (by[g] = by[g] || []).push(p);
  });
  return order.filter(function (g) { return by[g] && by[g].length; }).map(function (g) { return { group: g, items: by[g] }; });
}

function groupCount(g) {
  return g.names ? g.names.length : (parseInt(g.count, 10) >= 1 ? parseInt(g.count, 10) : 1);
}

// Initial state of the create-device form for a preset: everything the user may still edit.
export function presetForm(preset) {
  const p = preset || {};
  return {
    preset: p.id || '',
    name: p.label || '',
    kind: p.kind || 'other',
    manufacturer: '',
    model: '',
    ru: parseInt(p.ru, 10) >= 1 ? parseInt(p.ru, 10) : null,
    ports: (p.ports || []).map(function (g) { return { group: g.group, count: groupCount(g), fixed: !!g.names }; }),
  };
}

// True when the form still describes the generic preset itself (so the device may keep the template link).
export function formMatchesPreset(preset, form) {
  const base = presetForm(preset);
  if ((form.kind || 'other') !== base.kind) return false;
  if ((form.manufacturer || '').trim() || (form.model || '').trim()) return false;
  if ((form.ru || null) !== (base.ru || null)) return false;
  if ((form.ports || []).length !== base.ports.length) return false;
  return base.ports.every(function (g, i) { return form.ports[i] && form.ports[i].group === g.group && form.ports[i].count === g.count; });
}

// Port groups with the edited counts applied; a count of 0 removes the group.
export function presetPorts(preset, form) {
  const counts = {};
  (form && form.ports || []).forEach(function (g) { counts[g.group] = g.count; });
  const out = [];
  ((preset && preset.ports) || []).forEach(function (g0) {
    const g = Object.assign({}, g0);
    const n = Object.prototype.hasOwnProperty.call(counts, g.group) ? counts[g.group] : groupCount(g);
    if (!(n >= 1)) return;
    if (!g.names) {
      if (n > 1) g.count = n; else delete g.count;
      delete g.start;
    }
    out.push(g);
  });
  return out;
}

// The template-shaped object addDeviceFromTemplateOps expects. Keeps `id` (= device.template) only while the
// form still matches the preset; otherwise the device is free-standing and carries its own `ru`.
export function presetTemplate(preset, form) {
  const p = preset || {};
  const f = Object.assign(presetForm(p), form || {});
  const t = { name: (f.name || '').trim() || p.label || 'Device', kind: f.kind || p.kind || 'other', ports: presetPorts(p, f) };
  if ((f.manufacturer || '').trim()) t.manufacturer = f.manufacturer.trim();
  if ((f.model || '').trim()) t.model = f.model.trim();
  if (f.ru >= 1) t.ru = f.ru;
  ['width', 'dante', 'dmx_footprint', 'routing', 'discipline'].forEach(function (k) { if (p[k] !== undefined && p[k] !== null) t[k] = p[k]; });
  if (t.kind !== p.kind) delete t.discipline;
  if (formMatchesPreset(p, f)) t.id = p.id;
  return t;
}

export function portsSummary(ports) {
  return (ports || []).map(function (g) {
    const n = groupCount(g);
    return n > 1 ? n + '\u00d7 ' + g.group : g.group;
  }).join(' \u00b7 ');
}
