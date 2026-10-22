// Console channels helpers (SPEC §4.3.17, §6.8.6, §6.8.7): js/console-core.js against the CL5 shapes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule } from './fixtures/helpers.mjs';

const { mod: cc, skip: absent, error } = await loadModule('js/console-core.js', 'console');
const skip = absent || (error ? 'console-core.js failed to import' : false);
const T = (name, fn) => test(name, { skip }, fn);
if (error) test('console-core.js imports in Node', () => { throw error; });

const CHANNELS = [
  { id: 'in-12', kind: 'input', index: 12, name: 'Bass', source: 'yamaha' },
  { id: 'in-1', kind: 'input', index: 1, name: 'Vox 1', source: 'yamaha' },
  { id: 'stin-4-l', kind: 'stereo_input', index: 4, side: 'L', name: 'PC', source: 'yamaha' },
  { id: 'mix-9', kind: 'mix', index: 9, name: 'IEM 9', source: 'yamaha' },
  { id: 'mtx-7', kind: 'matrix', index: 7, name: 'Lobby', source: 'yamaha' },
  { id: 'st-l', kind: 'stereo', side: 'L', source: 'yamaha' },
  { id: 'st-r', kind: 'stereo', side: 'R', source: 'yamaha' },
  { id: 'mono', kind: 'mono', source: 'yamaha' },
  { id: 'dca-1', kind: 'dca', index: 1, name: 'BAND', source: 'yamaha' },
  { id: 'mute-2', kind: 'mute_group', index: 2, source: 'yamaha' },
  { id: 'fx-1', kind: 'rack', rack: 'FX', index: 1, source: 'yamaha' },
];
const LINKS = [
  { from: { port: 'dante-primary', ch: 17 }, to: { channel: 'in-12' }, kind: 'input_patch', source: 'yamaha' },
  { from: { port: 'omni-in-1' }, to: { channel: 'in-1' }, kind: 'input_patch', source: 'yamaha' },
  { from: { channel: 'in-12' }, to: { channel: 'st-l' }, kind: 'send', source: 'user' },
  { from: { channel: 'in-12' }, to: { channel: 'dca-1' }, kind: 'dca', source: 'user' },
  { from: { channel: 'st-l' }, to: { port: 'dante-primary', ch: 63 }, kind: 'output_patch', source: 'yamaha' },
  { from: { channel: 'mix-9' }, to: { text: 'REC 1' }, kind: 'output_patch', source: 'yamaha' },
  { from: { channel: 'in-12' }, to: { channel: 'fx-1', tag: 'A' }, kind: 'insert_send', insert: 1, source: 'yamaha' },
  { from: { channel: 'fx-1', tag: 'A' }, to: { channel: 'in-12' }, kind: 'insert_return', insert: 1, source: 'yamaha' },
];
const PORTS = { 'dante-primary': { id: 'dante-primary', label: 'Dante Primary', channels: 64 }, 'omni-in-1': { id: 'omni-in-1', name: 'Omni In 1' } };
const LABELS = { 'dante-primary': { in: { 17: '17 Bass' }, out: { 63: 'Main L' } } };
const ctx = () => ({ channels: cc.channelMap(CHANNELS), ports: PORTS, labels: LABELS });

T('channelLabel / channelTitle follow the console wording (§4.3.17)', () => {
  assert.equal(cc.channelLabel(CHANNELS[0]), 'CH 12');
  assert.equal(cc.channelTitle(CHANNELS[0]), 'CH 12 · Bass');
  assert.equal(cc.channelLabel(CHANNELS[2]), 'ST IN 4 L');
  assert.equal(cc.channelLabel({ kind: 'stereo', side: 'L' }), 'ST L');
  assert.equal(cc.channelLabel({ kind: 'mono' }), 'MONO');
  assert.equal(cc.channelLabel({ kind: 'rack', rack: 'FX', index: 1 }), 'FX 1');
  assert.equal(cc.channelTitle({ kind: 'mix', index: 1, name: 'MIX 1' }), 'MIX 1', 'name equal to the label is not repeated');
  assert.equal(cc.channelLabel({ kind: 'input', index: 3, label: 'Kick' }), 'Kick', 'explicit label wins');
});

T('groupChannels sorts console-style into Inputs | Buses | DCAs | Racks', () => {
  const g = cc.groupChannels(CHANNELS);
  assert.deepEqual(g.inputs.map((c) => c.id), ['in-1', 'in-12', 'stin-4-l']);
  assert.deepEqual(g.buses.map((c) => c.id), ['mix-9', 'mtx-7', 'st-l', 'st-r', 'mono']);
  assert.deepEqual(g.dcas.map((c) => c.id), ['dca-1', 'mute-2']);
  assert.deepEqual(g.racks.map((c) => c.id), ['fx-1']);
});

T('effectiveChannels: device set wins, overlay otherwise, pending flags a differing import', () => {
  const ov = { channels: { foh: { channels: CHANNELS, links: LINKS } } };
  const none = cc.effectiveChannels({ id: 'foh' }, ov);
  assert.equal(none.source, 'overlay');
  assert.equal(none.pending, true);
  assert.equal(none.channels.length, CHANNELS.length);
  const applied = cc.effectiveChannels({ id: 'foh', channels: CHANNELS, channel_links: LINKS }, ov);
  assert.equal(applied.source, 'device');
  assert.equal(applied.pending, false, 'identical sets → nothing to re-apply');
  const newer = cc.effectiveChannels({ id: 'foh', channels: CHANNELS.slice(1), channel_links: LINKS }, ov);
  assert.equal(newer.pending, true, 'import has a channel the device lacks');
  const renamed = cc.effectiveChannels({ id: 'foh', channels: [Object.assign({}, CHANNELS[0], { name: 'Bass DI', source: 'user' })].concat(CHANNELS.slice(1)), channel_links: LINKS }, ov);
  assert.equal(renamed.pending, false, 'a user rename of an imported channel is not a pending import');
  assert.equal(cc.effectiveChannels({ id: 'x' }, {}).source, 'none');
  assert.equal(cc.effectiveChannels({ id: 'x' }, null).source, 'none');
});

T('channelIndex groups links per channel in both directions', () => {
  const idx = cc.channelIndex(LINKS);
  assert.equal(idx['in-12'].inputs.length, 1);
  assert.equal(idx['in-12'].sends.length, 1);
  assert.equal(idx['in-12'].dca.length, 1);
  assert.equal(idx['in-12'].insertSend.length, 1);
  assert.equal(idx['in-12'].insertReturn.length, 1);
  assert.equal(idx['st-l'].feeds.length, 1);
  assert.equal(idx['st-l'].outputs.length, 1);
  assert.equal(idx['dca-1'].members.length, 1);
  assert.equal(idx['fx-1'].inputs.length, 1, 'insert send arrives at the rack');
  assert.equal(idx['fx-1'].outputs.length, 1, 'insert return leaves the rack');
});

T('endpointText shows both the console port and the Dante channel name', () => {
  const c = ctx();
  assert.equal(cc.endpointText({ port: 'dante-primary', ch: 17 }, Object.assign({ dir: 'in' }, c)), 'Dante Primary 17 “17 Bass”');
  assert.equal(cc.endpointText({ port: 'dante-primary', ch: 63 }, Object.assign({ dir: 'out' }, c)), 'Dante Primary 63 “Main L”');
  assert.equal(cc.endpointText({ port: 'omni-in-1' }, c), 'Omni In 1');
  assert.equal(cc.endpointText({ channel: 'fx-1', tag: 'A' }, c), 'FX 1 A');
  assert.equal(cc.endpointText({ channel: 'in-12' }, c), 'CH 12 · Bass');
  assert.equal(cc.endpointText({ text: 'REC 1' }, c), 'REC 1');
  assert.equal(cc.endpointText({ port: 'unknown', ch: 2 }, c), 'unknown 2');
});

T('channelSummary builds the dense row text; filterChannels searches it', () => {
  const idx = cc.channelIndex(LINKS);
  const s = cc.channelSummary(CHANNELS[0], idx, ctx());
  assert.equal(s.source, 'Dante Primary 17 “17 Bass”');
  assert.deepEqual(s.dests, ['ST L']);
  assert.deepEqual(s.groups, ['DCA 1 · BAND']);
  const dca = cc.channelSummary(CHANNELS[8], idx, ctx());
  assert.deepEqual(dca.dests, ['CH 12'], 'a DCA lists its members');
  const stl = cc.channelSummary(CHANNELS[5], idx, ctx());
  assert.equal(stl.source, 'CH 12 · Bass');
  assert.deepEqual(stl.dests, ['Dante Primary 63 “Main L”']);
  assert.deepEqual(cc.filterChannels(CHANNELS, 'bass', idx, ctx()).map((c) => c.id), ['in-12', 'st-l', 'fx-1'], 'matches name and fed-by text (ST L and the FX insert are fed by Bass)');
  assert.deepEqual(cc.filterChannels(CHANNELS, '17', idx, ctx()).map((c) => c.id), ['in-12'], 'matches the Dante channel');
  assert.equal(cc.filterChannels(CHANNELS, '', idx, ctx()).length, CHANNELS.length);
});

T('routePeer finds the far end of an overlay route', () => {
  const routes = [{ kind: 'dante', from: { device: 'rio', port: 'dante-primary', ch: 6, channel: 'Bass 17' }, to: { device: 'foh', port: 'dante-primary', ch: 17 } }];
  assert.equal(cc.routePeer(routes, 'foh', 'dante-primary', 17, 'in').device, 'rio');
  assert.equal(cc.routePeer(routes, 'rio', 'dante-primary', 6, 'out').device, 'foh');
  assert.equal(cc.routePeer(routes, 'foh', 'dante-primary', 18, 'in'), null);
});

T('node refs match the trace API (§6.9.3)', () => {
  assert.equal(cc.channelRef('foh', CHANNELS[0]), 'foh:@in-12');
  assert.equal(cc.channelRef('foh', 'fx-1', 'A'), 'foh:@fx-1.A');
  assert.equal(cc.portChannelRef('rio', 'dante-primary', 6, 'out'), 'rio:dante-primary#tx6');
  assert.equal(cc.portChannelRef('foh', 'dante-primary', 17, 'in'), 'foh:dante-primary#rx17');
  assert.equal(cc.portChannelRef('foh', 'omni-in-1'), 'foh:omni-in-1');
});

T('edits are pure, idempotent and stamped source "user"', () => {
  let l = cc.setInputPatch(LINKS, 'in-12', { port: 'omni-in-2' });
  assert.equal(l.filter((x) => x.kind === 'input_patch' && x.to.channel === 'in-12').length, 1, 'replaces the input patch');
  assert.equal(l.filter((x) => x.kind === 'input_patch' && x.to.channel === 'in-12')[0].source, 'user');
  assert.equal(cc.setInputPatch(LINKS, 'in-12', null).filter((x) => x.kind === 'input_patch' && x.to.channel === 'in-12').length, 0);
  l = cc.toggleSend(LINKS, 'in-12', 'mix-9', true);
  assert.equal(l.length, LINKS.length + 1);
  assert.equal(cc.toggleSend(l, 'in-12', 'mix-9', true).length, l.length, 'adding twice does not duplicate');
  assert.equal(cc.toggleSend(l, 'in-12', 'mix-9', false).length, LINKS.length);
  assert.equal(cc.toggleSend(LINKS, 'in-12', 'st-l', false).length, LINKS.length - 1, 'removes the existing send');
  l = cc.toggleMembership(LINKS, 'mute', 'in-12', 'mute-2', true);
  assert.deepEqual(l[l.length - 1], { from: { channel: 'in-12' }, to: { channel: 'mute-2' }, kind: 'mute', source: 'user' });
  l = cc.addOutput(LINKS, 'mix-9', { port: 'omni-out-3' });
  assert.equal(l.length, LINKS.length + 1);
  assert.equal(cc.addOutput(l, 'mix-9', { port: 'omni-out-3' }).length, l.length, 'duplicate output ignored');
  assert.equal(cc.removeLink(LINKS, LINKS[2]).length, LINKS.length - 1);
  assert.equal(cc.removeLink(LINKS, Object.assign({}, LINKS[2], { source: 'yamaha' })).length, LINKS.length - 1, 'source does not take part in identity');
  assert.deepEqual(LINKS.length, 8, 'input untouched');
  const ch = cc.updateChannel(CHANNELS, 'in-12', { name: 'Bass DI', color: null });
  assert.equal(ch[0].name, 'Bass DI');
  assert.equal(ch[0].source, 'user');
  assert.equal('color' in ch[0], false);
  assert.equal(CHANNELS[0].name, 'Bass', 'input untouched');
  assert.deepEqual(cc.nextChannel(CHANNELS, 'mix'), { id: 'mix-10', kind: 'mix', index: 10, source: 'user' });
  assert.deepEqual(cc.nextChannel([], 'dca'), { id: 'dca-1', kind: 'dca', index: 1, source: 'user' });
});

T('chainOf groups trace hops by device and strips the device prefix (§6.8.7)', () => {
  const path = {
    hops: [
      { device: 'bass-di', port: 'out', label: 'Bass DI · Out', device_name: 'Bass DI' },
      { device: 'rio-sl', port: 'analog-in-6', label: 'Rio3224 SL · Analog In 6', device_name: 'Rio3224 SL' },
      { device: 'rio-sl', port: 'dante-primary', kind: 'port_channel', ch: 6, dir: 'out', label: 'Dante Primary 6 “Bass 17”', device_name: 'Rio3224 SL' },
      { device: 'foh', port: 'dante-primary', kind: 'port_channel', ch: 17, dir: 'in', label: 'FOH CL5 · Dante Primary 17 “17 Bass”', device_name: 'FOH CL5' },
      { device: 'foh', port: null, kind: 'channel', channel: 'in-12', title: 'CH 12 · Bass', label: 'CH 12 · Bass', device_name: 'FOH CL5' },
      { device: 'foh', kind: 'dca', channel: 'dca-1', title: 'DCA 1 · BAND', control: true, label: '(via DCA 1 · BAND)', device_name: 'FOH CL5' },
      { device: 'pa-l', port: 'in', label: 'PA Left', device_name: 'PA Left' },
    ],
    via: ['', 'cable:c1', 'internal', 'route:dante', 'link:input_patch', 'link:dca', 'cable:c5'],
    text: 'x',
  };
  const chain = cc.chainOf(path);
  assert.deepEqual(chain.map((g) => g.name), ['Bass DI', 'Rio3224 SL', 'FOH CL5', 'PA Left']);
  assert.deepEqual(chain[1].hops.map((s) => s.label), ['Analog In 6', 'Dante Primary 6 “Bass 17”']);
  assert.deepEqual(chain[2].hops.map((s) => s.label), ['Dante Primary 17 “17 Bass”', 'CH 12 · Bass', '(via DCA 1 · BAND)']);
  assert.deepEqual(chain[2].hops.map((s) => s.via), ['route:dante', 'link:input_patch', 'link:dca']);
  assert.equal(chain[3].hops[0].label, 'in', 'a final input hop labelled with the device name falls back to the port id');
  assert.equal(cc.viaText('cable:c1'), 'cable c1');
  assert.equal(cc.viaText('route:dante'), 'dante route');
  assert.equal(cc.viaText('link:input_patch'), 'input patch');
  assert.equal(cc.viaText('internal'), 'internal');
  assert.equal(cc.pathsText([{ text: 'a' }, { text: '' }, { text: 'b' }]), 'a\nb');
  assert.deepEqual(cc.chainOf(null), []);
});
