// Pure helpers for the Helper panel (SPEC §6.9.5b "Draft a room"): no DOM, no fetch, importable in Node.
// assistant-ui.js renders with these; the mode and room are remembered per session by the panel itself.

export const MODES = ['ask', 'draft'];
export const ASK_PLACEHOLDER = 'Ask about your system\u2026';
export const DRAFT_PLACEHOLDER = 'Describe the room: e.g. X32 with an S16 stage box, 4 ULXD wireless, 2 K12.2 on stands, ATEM Mini, QuickQ 10';
export const DRAFT_EXAMPLE = 'X32 with an S16 stage box, 4 ULXD wireless, 2 K12.2 on stands, ATEM Mini, QuickQ 10';
export const DRAFT_HINT = 'Nothing is changed until you apply.';

// Singular kind names for the recognised chips ("Shure ULXD4D wireless receiver ×4"); the vocab wins when it has a label.
const KIND_NAMES = {
  source: 'source', stage_io: 'stage box', computer: 'computer', console: 'console', iem: 'IEM transmitter', pa: 'PA', network: 'network device',
  video: 'video device', other: 'device', mic: 'microphone', wireless_rx: 'wireless receiver', processor: 'DSP', amp: 'amplifier', speaker: 'speaker',
  recorder: 'recorder', intercom: 'intercom', camera: 'camera', video_source: 'playback', video_switcher: 'video switcher', video_router: 'video router',
  converter: 'converter', encoder: 'encoder', stream: 'stream destination', display: 'display', projector: 'projector', lighting_console: 'lighting console',
  dmx_node: 'DMX node', dimmer: 'dimmer', fixture: 'lighting fixture', switch: 'network switch', control: 'control processor', touch_panel: 'touch panel',
  power: 'power', patch_panel: 'patch panel', container: 'case',
};

export function normaliseMode(mode) {
  return mode === 'draft' ? 'draft' : 'ask';
}

export function placeholderFor(mode) {
  return normaliseMode(mode) === 'draft' ? DRAFT_PLACEHOLDER : ASK_PLACEHOLDER;
}

export function kindName(kind, vocab) {
  const k = String(kind || '');
  const v = vocab && vocab.kinds && vocab.kinds[k];
  if (KIND_NAMES[k]) return KIND_NAMES[k];
  if (v && v.label) return String(v.label).split(' \u00b7')[0].toLowerCase();
  return k.replace(/_/g, ' ');
}

// One recognised mention -> chip text: "<label> <kind> ×N" (the kind is left out when the label already says it).
export function recognisedLabel(item, vocab) {
  if (!item) return '';
  const label = String(item.label || item.template || item.preset || item.text || '').trim();
  const kind = kindName(item.kind, vocab);
  // presets and bare kinds are already type names ("Stagebox / I/O rack", "Loudspeaker"); templates get the kind after the model
  const typed = !item.template || !kind || label.toLowerCase().indexOf(kind.toLowerCase()) >= 0;
  const n = Number(item.count) || 1;
  return (typed ? label : label + ' ' + kind) + (n > 1 ? ' \u00d7' + n : '');
}

export function unknownLine(unknown) {
  const list = (unknown || []).map(function (u) { return typeof u === 'string' ? u : (u && u.text) || ''; }).filter(Boolean);
  return list.length ? 'Couldn\u2019t place: ' + list.join(', ') : '';
}

// Rooms for the Draft select: [{id, name}]; the default is the current room, else settings.default_room, else the first.
export function roomOptions(doc, current) {
  const rooms = ((doc && doc.rooms) || []).filter(function (r) { return r && r.id; }).map(function (r) { return { id: String(r.id), name: String(r.name || r.id) }; });
  const ids = rooms.map(function (r) { return r.id; });
  let def = current && ids.indexOf(String(current)) >= 0 ? String(current) : '';
  if (!def && doc && doc.settings && doc.settings.default_room && ids.indexOf(String(doc.settings.default_room)) >= 0) def = String(doc.settings.default_room);
  if (!def && rooms.length) def = rooms[0].id;
  return { rooms: rooms, selected: def };
}

export function roomName(doc, id) {
  const r = ((doc && doc.rooms) || []).filter(function (x) { return x && String(x.id) === String(id); })[0];
  return r ? String(r.name || r.id) : String(id || '');
}

// Resolve the room of a `fathom:assistant-open` event (id or name) against the project rooms.
export function resolveRoom(doc, text) {
  const t = String(text || '').trim();
  if (!t) return '';
  const rooms = ((doc && doc.rooms) || []).filter(function (r) { return r && r.id; });
  const byId = rooms.filter(function (r) { return String(r.id) === t; })[0];
  if (byId) return String(byId.id);
  const low = t.toLowerCase();
  const byName = rooms.filter(function (r) { return String(r.name || '').toLowerCase() === low || String(r.code || '').toLowerCase() === low; })[0];
  return byName ? String(byName.id) : '';
}

// The request body of POST …/assistant for a turn in either mode.
export function buildPayload(mode, question, opts) {
  const o = opts || {};
  const payload = { question: question, use_llm: o.useLlm !== false, history: o.history || [] };
  if (normaliseMode(mode) === 'draft') {
    payload.mode = 'draft';
    payload.room = o.draftRoom || o.room || '';
  } else if (o.room) {
    payload.room = o.room;
  }
  return payload;
}
