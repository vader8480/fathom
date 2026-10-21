// js/presets-core.js: Add gear presets — search / grouping, form pre-fill and the template built from the edited form.
// Preset data comes from fathom.presets (python3) so the two sides cannot drift; skipped when python3 is unavailable.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { loadModule, ROOT, clone } from './fixtures/helpers.mjs';

const { mod: pc, error } = await loadModule('js/presets-core.js', 'presets');
const mc = (await loadModule('js/model-core.js', 'W5')).mod;
if (error) test('presets-core.js imports in Node', () => { throw error; });

function loadPresetData() {
  for (const py of [process.env.PYTHON, `${ROOT}/.venv/bin/python`, 'python3', 'python']) {
    if (!py) continue;
    try {
      const out = execFileSync(py, ['-c', 'import json, sys; sys.path.insert(0, sys.argv[1]); from fathom import presets; print(json.dumps(presets.as_dict()))', ROOT], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
      return JSON.parse(out);
    } catch (e) { /* try the next interpreter */ }
  }
  return null;
}

const data = loadPresetData();
const skip = error ? 'presets-core.js failed to import' : (!data ? 'python3 with fathom.presets not available' : false);
const T = (name, fn) => test(name, { skip }, fn);
const byId = (id) => data.presets.find((p) => p.id === id);

T('filterPresets: tokens match label / alias / kind / group, results keep group order', () => {
  const all = pc.filterPresets(data.presets, '', data.groups);
  assert.equal(all.length, data.presets.length);
  const ranks = all.map((p) => data.groups.indexOf(p.group));
  assert.deepEqual(ranks, ranks.slice().sort((a, b) => a - b), 'sorted by group order');
  const sw = pc.filterPresets(data.presets, 'network switch', data.groups).map((p) => p.id);
  assert.deepEqual(sw.slice(0, 2), ['generic-switch-24', 'generic-switch-48']);
  assert.deepEqual(pc.filterPresets(data.presets, 'UPS').map((p) => p.id), ['generic-ups']);
  assert.deepEqual(pc.filterPresets(data.presets, 'access point').map((p) => p.id), ['generic-wifi-ap']);
  assert.ok(pc.filterPresets(data.presets, 'patch panel').map((p) => p.id).includes('generic-patch-panel-fibre'));
  assert.deepEqual(pc.filterPresets(data.presets, 'zzz-nothing'), []);
});

T('groupPresets: sections in group order, empty groups omitted', () => {
  const g = pc.groupPresets(data.presets, data.groups);
  assert.deepEqual(g.map((x) => x.group), data.groups);
  assert.equal(g.reduce((n, x) => n + x.items.length, 0), data.presets.length);
  const only = pc.groupPresets(pc.filterPresets(data.presets, 'ups'), data.groups);
  assert.deepEqual(only.map((x) => x.group), ['Power']);
});

T('presetForm: pre-fills name, kind, ru and one editable count per port group', () => {
  const p = byId('generic-switch-24');
  const f = pc.presetForm(p);
  assert.equal(f.preset, 'generic-switch-24');
  assert.equal(f.name, p.label);
  assert.equal(f.kind, 'switch');
  assert.equal(f.ru, 1);
  assert.equal(f.manufacturer, '');
  assert.equal(f.model, '');
  assert.deepEqual(f.ports, [
    { group: 'Port', count: 24, fixed: false },
    { group: 'SFP+', count: 4, fixed: false },
    { group: 'Mains In', count: 1, fixed: false },
  ]);
  const ap = pc.presetForm(byId('generic-wifi-ap'));
  assert.equal(ap.ru, null, 'not rack-mounted → blank RU');
  const rx = pc.presetForm(byId('generic-wireless-mic-rx'));
  const ant = rx.ports.find((g) => g.group === 'Antenna');
  assert.deepEqual(ant, { group: 'Antenna', count: 2, fixed: true }, 'named groups are fixed-size');
});

T('presetTemplate: untouched form keeps the template link and the preset ports', () => {
  const p = byId('generic-pdu');
  const t = pc.presetTemplate(p, pc.presetForm(p));
  assert.equal(t.id, 'generic-pdu');
  assert.equal(t.kind, 'power');
  assert.equal(t.name, 'PDU');
  assert.equal(t.ru, 1);
  assert.equal(t.routing, 'passthrough');
  assert.deepEqual(t.ports, p.ports);
  assert.equal(t.manufacturer, undefined);
  const dev = mc.addDeviceFromTemplateOps({ devices: [] }, clone(t), { room: 'main' }).ops[0].value;
  assert.equal(dev.template, 'generic-pdu');
  assert.equal(dev.rack, undefined, 'height comes from the template while linked');
  assert.equal(dev.ports.filter((x) => x.group === 'Outlet').length, 8);
  assert.equal(dev.ports[0].id, 'mains-in');
});

T('presetTemplate: renaming alone keeps the link; manufacturer / model / kind / ru / ports edits detach it', () => {
  const p = byId('generic-switch-24');
  const base = pc.presetForm(p);
  assert.equal(pc.presetTemplate(p, Object.assign({}, base, { name: 'Core A' })).id, 'generic-switch-24');
  assert.ok(pc.formMatchesPreset(p, Object.assign({}, base, { name: 'x' })));
  for (const edit of [{ manufacturer: 'Cisco' }, { model: 'C9300' }, { kind: 'network' }, { ru: 2 }, { ru: null }]) {
    const t = pc.presetTemplate(p, Object.assign({}, base, edit));
    assert.equal(t.id, undefined, 'detached after ' + JSON.stringify(edit));
  }
  const edited = clone(base);
  edited.ports[1].count = 2;
  const t = pc.presetTemplate(p, edited);
  assert.equal(t.id, undefined);
  assert.equal(t.ports.find((g) => g.group === 'SFP+').count, 2);
});

T('presetTemplate: edited counts flow into the device; 0 drops a group; count 1 has no count key', () => {
  const p = byId('generic-switch-24');
  const f = pc.presetForm(p);
  f.name = 'Edge switch';
  f.manufacturer = 'Netgear';
  f.model = 'M4250';
  f.ports[0].count = 12;
  f.ports[1].count = 0;
  f.ports[2].count = 1;
  const t = pc.presetTemplate(p, f);
  assert.deepEqual(t.ports.map((g) => g.group), ['Port', 'Mains In']);
  assert.equal(t.ports[0].count, 12);
  assert.equal('count' in t.ports[1], false);
  assert.equal(t.manufacturer, 'Netgear');
  assert.equal(t.model, 'M4250');
  const dev = mc.addDeviceFromTemplateOps({ devices: [] }, t, { room: 'main' }).ops[0].value;
  assert.equal(dev.name, 'Edge switch');
  assert.equal(dev.template, undefined);
  assert.deepEqual(dev.rack, { height: 1 }, 'a detached device carries its own RU');
  assert.equal(dev.ports.length, 13);
  assert.equal(dev.ports[11].id, 'port-12');
  assert.equal(dev.ports[12].id, 'mains-in');
});

T('presetTemplate: kind change drops the preset discipline override but keeps dante / dmx fields', () => {
  const d = byId('generic-dante-interface');
  const t = pc.presetTemplate(d, Object.assign(pc.presetForm(d), { kind: 'processor' }));
  assert.equal(t.kind, 'processor');
  assert.equal(t.dante, true);
  const dim = byId('generic-dimmer-pack');
  const t2 = pc.presetTemplate(dim, pc.presetForm(dim));
  assert.equal(t2.dmx_footprint, 6);
  const dev = mc.addDeviceFromTemplateOps({ devices: [] }, t2, {}).ops[0].value;
  assert.deepEqual(dev.dmx, { footprint: 6 });
});

T('portsSummary', () => {
  assert.equal(pc.portsSummary(byId('generic-pdu').ports), 'Mains In \u00b7 8\u00d7 Outlet');
  assert.equal(pc.portsSummary(byId('generic-wireless-mic-rx').ports).split(' \u00b7 ')[0], '2\u00d7 Antenna');
});
