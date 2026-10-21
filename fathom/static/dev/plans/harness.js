// W4 harness runtime for dev/floorplan.html, dev/rack.html, dev/schedules.html.
// Loads fixture-v2.json, builds a store (model-core.createStore when present,
// else a local §6.2 shim), a fake ctx (api: null) and mounts the view(s).
// ?smoke=1 writes data-smoke; ?walk=1 runs a scripted walkthrough into data-walk.
/* eslint-disable */
window.__fathomErrors = window.__fathomErrors || [];
(function () {
  const errs = window.__fathomErrors;
  window.addEventListener('error', function (e) { errs.push(String((e && e.message) || e)); });
  window.addEventListener('unhandledrejection', function (e) { errs.push('unhandled: ' + String(e && e.reason && (e.reason.stack || e.reason.message) || e.reason)); });
  const ce = console.error;
  console.error = function () { errs.push(Array.prototype.map.call(arguments, String).join(' ')); return ce.apply(console, arguments); };
})();

export const VOCAB = {"kinds":{"source":{"label":"Sources","discipline":"audio","color":"#2fd4b4"},"stage_io":{"label":"Stage I/O","discipline":"audio","color":"#4ea8ff"},"computer":{"label":"Computers","discipline":"audio","color":"#a98bff"},"console":{"label":"Consoles","discipline":"audio","color":"#7c5cff"},"iem":{"label":"IEM gear","discipline":"audio","color":"#f06aa8"},"pa":{"label":"PA \u00b7 amps, speakers","discipline":"audio","color":"#ff9548"},"network":{"label":"Network","discipline":"network","color":"#7b86ff"},"video":{"label":"Video","discipline":"video","color":"#c084fc"},"other":{"label":"Other","discipline":"other","color":"#9aa3b5"},"mic":{"label":"Microphones","discipline":"audio","color":"#2fd4b4"},"wireless_rx":{"label":"Wireless receivers","discipline":"audio","color":"#38bdf8"},"processor":{"label":"Processors \u00b7 DSP","discipline":"audio","color":"#60a5fa"},"amp":{"label":"Amplifiers","discipline":"audio","color":"#fb923c"},"speaker":{"label":"Loudspeakers","discipline":"audio","color":"#fdba74"},"recorder":{"label":"Recorders","discipline":"audio","color":"#a78bfa"},"intercom":{"label":"Intercom","discipline":"audio","color":"#f472b6"},"camera":{"label":"Cameras","discipline":"video","color":"#34d399"},"video_source":{"label":"Playback \u00b7 media servers","discipline":"video","color":"#2dd4bf"},"video_switcher":{"label":"Video switchers","discipline":"video","color":"#22c55e"},"video_router":{"label":"Video routers","discipline":"video","color":"#10b981"},"converter":{"label":"Converters \u00b7 extenders","discipline":"video","color":"#86efac"},"encoder":{"label":"Encoders \u00b7 streaming","discipline":"video","color":"#4ade80"},"stream":{"label":"Stream destinations","discipline":"network","color":"#fb923c"},"display":{"label":"Displays","discipline":"video","color":"#a3e635"},"projector":{"label":"Projectors","discipline":"video","color":"#bef264"},"lighting_console":{"label":"Lighting consoles","discipline":"lighting","color":"#fbbf24"},"dmx_node":{"label":"DMX nodes \u00b7 splitters","discipline":"lighting","color":"#f59e0b"},"dimmer":{"label":"Dimmers \u00b7 relays","discipline":"lighting","color":"#eab308"},"fixture":{"label":"Lighting fixtures","discipline":"lighting","color":"#fde047"},"switch":{"label":"Network switches","discipline":"network","color":"#fb923c"},"control":{"label":"Control processors","discipline":"control","color":"#c084fc"},"touch_panel":{"label":"Touch panels","discipline":"control","color":"#d8b4fe"},"power":{"label":"Power \u00b7 UPS \u00b7 PDU","discipline":"power","color":"#f87171"},"patch_panel":{"label":"Patch panels \u00b7 wall plates","discipline":"other","color":"#94a3b8"}},"media":{"dante":{"label":"Dante \u00b7 Cat6","discipline":"audio","color":"#7b86ff","dash":"","carries":["audio","network"],"ip":true,"short":"DANTE"},"analog":{"label":"Analog \u00b7 XLR","discipline":"audio","color":"#aab3c5","dash":"","carries":["audio"],"ip":false,"short":"XLR"},"aes3":{"label":"AES3 \u00b7 110 \u03a9","discipline":"audio","color":"#2dd4ee","dash":"7 4","carries":["audio"],"ip":false,"short":"AES"},"aes50":{"label":"AES50 \u00b7 Cat5e","discipline":"audio","color":"#5ac8fa","dash":"2 4","carries":["audio","control"],"ip":false,"short":"AES50"},"madi":{"label":"MADI","discipline":"audio","color":"#fbbf24","dash":"10 4","carries":["audio"],"ip":false,"short":"MADI"},"avb":{"label":"AVB / Milan","discipline":"audio","color":"#34d399","dash":"6 3 2 3","carries":["audio","network"],"ip":true,"short":"AVB"},"speaker":{"label":"Speaker \u00b7 NL4/NL8","discipline":"audio","color":"#ff9548","dash":"","carries":["audio"],"ip":false,"short":"SPK"},"iem_wired":{"label":"Wired IEM","discipline":"audio","color":"#f472b6","dash":"1.5 4","carries":["audio"],"ip":false,"short":"IEM"},"iem_wireless":{"label":"Wireless IEM","discipline":"audio","color":"#e879f9","dash":"1.5 6","carries":["audio"],"ip":false,"short":"IEM"},"rf":{"label":"RF \u00b7 wireless mic","discipline":"audio","color":"#f0abfc","dash":"1.5 6","carries":["audio"],"ip":false,"short":"RF"},"usb":{"label":"USB","discipline":"other","color":"#cbd5e1","dash":"4 3","carries":["audio","video","control"],"ip":false,"short":"USB"},"video":{"label":"SDI / HDMI","discipline":"video","color":"#c084fc","dash":"","carries":["video","audio"],"ip":false,"short":"VID"},"network":{"label":"Control \u00b7 IP","discipline":"network","color":"#94a3b8","dash":"3 3","carries":["network","control","audio","video","lighting"],"ip":true,"short":"CAT"},"other":{"label":"Other","discipline":"other","color":"#9aa3b5","dash":"","carries":["audio","video","lighting","control","network","power"],"ip":false,"short":"OTH"},"aes67":{"label":"AES67 \u00b7 IP audio","discipline":"audio","color":"#818cf8","dash":"","carries":["audio","network"],"ip":true,"short":"AES67"},"qlan":{"label":"Q-LAN","discipline":"audio","color":"#60a5fa","dash":"","carries":["audio","video","control","network"],"ip":true,"short":"QLAN"},"snake":{"label":"Digital snake \u00b7 Cat5e","discipline":"audio","color":"#38bdf8","dash":"2 3","carries":["audio","control"],"ip":false,"short":"SNAKE"},"adat":{"label":"ADAT \u00b7 optical","discipline":"audio","color":"#67e8f9","dash":"1 3","carries":["audio"],"ip":false,"short":"ADAT"},"speaker_70v":{"label":"70/100 V line","discipline":"audio","color":"#fdba74","dash":"8 3","carries":["audio"],"ip":false,"short":"70V"},"intercom":{"label":"Intercom \u00b7 XLR","discipline":"audio","color":"#fb7185","dash":"5 2 1 2","carries":["audio","control"],"ip":false,"short":"COM"},"sdi":{"label":"SDI \u00b7 75 \u03a9 BNC","discipline":"video","color":"#facc15","dash":"","carries":["video","audio"],"ip":false,"short":"SDI"},"hdmi":{"label":"HDMI","discipline":"video","color":"#f59e0b","dash":"","carries":["video","audio"],"ip":false,"short":"HDMI"},"displayport":{"label":"DisplayPort","discipline":"video","color":"#fda4af","dash":"","carries":["video","audio"],"ip":false,"short":"DP"},"hdbaset":{"label":"HDBaseT \u00b7 Cat6","discipline":"video","color":"#fcd34d","dash":"5 2","carries":["video","audio","control"],"ip":false,"short":"HDBT"},"fiber":{"label":"Fiber","discipline":"other","color":"#22d3ee","dash":"12 3","carries":["audio","video","network","control","lighting"],"ip":false,"short":"FIB"},"ndi":{"label":"NDI \u00b7 IP video","discipline":"video","color":"#a3e635","dash":"4 2","carries":["video","audio","network"],"ip":true,"short":"NDI"},"st2110":{"label":"SMPTE ST 2110","discipline":"video","color":"#84cc16","dash":"4 2 1 2","carries":["video","audio","network"],"ip":true,"short":"2110"},"dmx":{"label":"DMX512 \u00b7 XLR5","discipline":"lighting","color":"#fde047","dash":"","carries":["lighting"],"ip":false,"short":"DMX"},"rdm":{"label":"DMX + RDM","discipline":"lighting","color":"#fef08a","dash":"6 2","carries":["lighting","control"],"ip":false,"short":"RDM"},"sacn":{"label":"sACN (E1.31)","discipline":"lighting","color":"#fbbf24","dash":"3 2","carries":["lighting","network"],"ip":true,"short":"SACN"},"artnet":{"label":"Art-Net","discipline":"lighting","color":"#f59e0b","dash":"3 2 1 2","carries":["lighting","network"],"ip":true,"short":"ARTN"},"rs232":{"label":"RS-232 \u00b7 serial","discipline":"control","color":"#c4b5fd","dash":"2 2","carries":["control"],"ip":false,"short":"232"},"rs422":{"label":"RS-422/485","discipline":"control","color":"#a78bfa","dash":"2 2","carries":["control"],"ip":false,"short":"422"},"ir":{"label":"IR emitter","discipline":"control","color":"#ddd6fe","dash":"1 3","carries":["control"],"ip":false,"short":"IR"},"gpio":{"label":"GPIO \u00b7 contact closure","discipline":"control","color":"#e9d5ff","dash":"1 2","carries":["control"],"ip":false,"short":"GPIO"},"osc":{"label":"OSC \u00b7 IP control","discipline":"control","color":"#d8b4fe","dash":"3 3","carries":["control","network"],"ip":true,"short":"OSC"},"midi":{"label":"MIDI","discipline":"control","color":"#f0abfc","dash":"2 3","carries":["control"],"ip":false,"short":"MIDI"},"timecode":{"label":"Timecode (LTC)","discipline":"control","color":"#f5d0fe","dash":"1 2","carries":["control"],"ip":false,"short":"LTC"},"sync":{"label":"Sync \u00b7 word clock / genlock","discipline":"other","color":"#94a3b8","dash":"1 4","carries":["control"],"ip":false,"short":"SYNC"},"power":{"label":"Power \u00b7 mains","discipline":"power","color":"#f87171","dash":"","carries":["power"],"ip":false,"short":"PWR"},"power_dc":{"label":"DC power","discipline":"power","color":"#fca5a5","dash":"","carries":["power"],"ip":false,"short":"DC"}},"disciplines":{"audio":{"label":"Audio","color":"#4ea8ff","letter":"A"},"video":{"label":"Video","color":"#34d399","letter":"V"},"lighting":{"label":"Lighting","color":"#fbbf24","letter":"L"},"network":{"label":"Network","color":"#fb923c","letter":"N"},"control":{"label":"Control","color":"#c084fc","letter":"C"},"power":{"label":"Power","color":"#f87171","letter":"P"},"other":{"label":"Other","color":"#9aa3b5","letter":"X"}},"statuses":["installed","planned","spare","retired"]};

const params = new URLSearchParams(location.search);

// ------------------------------------------------------------ store shim
function clone(v) { return v === undefined ? undefined : JSON.parse(JSON.stringify(v)); }
function isObj(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }
function mergePatch(target, patch) {
  if (!isObj(patch)) return clone(patch);
  const out = isObj(target) ? clone(target) : {};
  Object.keys(patch).forEach(function (k) {
    if (patch[k] === null) delete out[k]; else out[k] = mergePatch(out[k], patch[k]);
  });
  return out;
}
function applyOpsShim(doc, ops) {
  const d = Object.assign({}, doc);
  const inverse = [];
  const touched = [];
  ops.forEach(function (op) {
    if (op.op === 'root') {
      inverse.unshift({op: 'root', key: op.key, value: clone(d[op.key] || {}), replace: true});
      d[op.key] = op.replace ? clone(op.value) : mergePatch(d[op.key] || {}, op.value);
      touched.push(op.key);
      return;
    }
    const coll = (d[op.coll] || []).slice();
    const i = coll.findIndex(function (e) { return e.id === op.id; });
    const before = i >= 0 ? coll[i] : null;
    inverse.unshift(before ? {op: 'put', coll: op.coll, id: op.id, value: clone(before), _index: i} : {op: 'del', coll: op.coll, id: op.id});
    if (op.op === 'put') { if (i >= 0) coll[i] = clone(op.value); else if (op._index != null) coll.splice(op._index, 0, clone(op.value)); else coll.push(clone(op.value)); }
    else if (op.op === 'merge') { if (i < 0) throw new Error('missing_entity ' + op.coll + '/' + op.id); coll[i] = mergePatch(before, op.value); }
    else if (op.op === 'del') { if (i >= 0) coll.splice(i, 1); }
    d[op.coll] = coll;
    touched.push(op.coll + '/' + op.id);
  });
  return {doc: d, inverse: inverse, touched: touched};
}
function ev(type, detail) { const e = new Event(type); e.detail = detail; return e; }

class ShimStore extends EventTarget {
  constructor(o) {
    super();
    this.doc = o.doc; this.vocab = o.vocab; this.overlay = o.overlay || null; this.room = o.room || (o.doc.settings && o.doc.settings.default_room) || '';
    this.readOnly = !!o.readOnly; this.selection = null; this.filter = {}; this.revision = o.doc.revision || 0;
    this._undo = []; this._redo = [];
  }
  get canUndo() { return this._undo.length > 0; }
  get canRedo() { return this._redo.length > 0; }
  get undoLabel() { return this._undo.length ? this._undo[this._undo.length - 1].label : ''; }
  get redoLabel() { return this._redo.length ? this._redo[this._redo.length - 1].label : ''; }
  commit(ops, label) {
    if (this.readOnly) { const e = new Error('read-only'); e.name = 'ReadOnlyError'; throw e; }
    const r = applyOpsShim(this.doc, ops);
    this.doc = r.doc;
    this._undo.push({label: label, ops: ops, inverse: r.inverse});
    if (this._undo.length > 200) this._undo.shift();
    this._redo = [];
    this.dispatchEvent(ev('doc', {ops: ops, inverse: r.inverse, source: 'local', label: label}));
    return this.doc;
  }
  _swap(from, to, source) {
    const e = from.pop();
    if (!e) return;
    const r = applyOpsShim(this.doc, e.inverse);
    this.doc = r.doc;
    to.push({label: e.label, ops: e.inverse, inverse: r.inverse});
    this.dispatchEvent(ev('doc', {ops: e.inverse, inverse: r.inverse, source: source, label: e.label}));
  }
  undo() { this._swap(this._undo, this._redo, 'undo'); }
  redo() { this._swap(this._redo, this._undo, 'redo'); }
  applyRemote(ops, source) { const r = applyOpsShim(this.doc, ops); this.doc = r.doc; this.dispatchEvent(ev('doc', {ops: ops, inverse: r.inverse, source: source || 'remote'})); }
  replaceDoc(doc, revision) { this.doc = doc; this.revision = revision || 0; this._undo = []; this._redo = []; this.dispatchEvent(ev('doc', {ops: [], source: 'load'})); }
  select(sel) { this.selection = sel; this.dispatchEvent(ev('selection', sel)); }
  highlight(hl) { this.dispatchEvent(ev('highlight', hl)); }
  setFilter(p) { this.filter = Object.assign({}, this.filter, p); this.dispatchEvent(ev('filter', this.filter)); }
  setRoom(id) { this.room = id; this.dispatchEvent(ev('room', id)); }
  setOverlay(o) { this.overlay = o; this.dispatchEvent(ev('overlay', o)); }
  setReadOnly(b) { this.readOnly = !!b; this.dispatchEvent(ev('mode', {readOnly: this.readOnly})); }
  setRevision(n) { this.revision = n; this.dispatchEvent(ev('revision', n)); }
}

// ------------------------------------------------------------ fake ctx
function makeCtx(store, ui) {
  const live = document.getElementById('fathom-live');
  return {
    store: store, vocab: VOCAB, api: null, project: 'sunday-demo',
    commit: function (ops, label) {
      if (store.readOnly) { this.toast('Read-only', 'warn'); return store.doc; }
      const d = store.commit(ops, label);
      if (live) live.textContent = label || 'Changed';
      ui.log('commit: ' + (label || '') + ' (' + ops.length + ' op' + (ops.length === 1 ? '' : 's') + ')');
      return d;
    },
    select: function (sel) { store.select(sel); ui.log('select: ' + JSON.stringify(sel)); },
    highlight: function (h) { store.highlight(h); },
    navigate: function (view, p) { ui.log('navigate: ' + view + ' ' + JSON.stringify(p || {})); },
    pickTemplate: function () { return Promise.resolve(null); },
    pickPort: function () { return Promise.resolve(null); },
    pickDevice: function (o) { const d = store.doc.devices.filter(function (x) { return !o || !o.room || x.room === o.room; })[0]; return Promise.resolve(d ? d.id : null); },
    toast: function (msg, level) { ui.toast(msg, level); },
    confirm: function (msg) { ui.log('confirm: ' + msg + ' -> yes'); return Promise.resolve(true); },
    openInspector: function (sel) { ui.log('inspector: ' + JSON.stringify(sel)); },
    env: {touch: matchMedia('(pointer: coarse)').matches, narrow: innerWidth < 700, platform: /iPad|iPhone/.test(navigator.userAgent) ? 'ios' : (/Mac/.test(navigator.platform) ? 'mac' : 'other'), online: navigator.onLine, secure: window.isSecureContext},
  };
}

function makeUi() {
  const toasts = document.getElementById('h-toasts');
  const logEl = document.getElementById('h-log');
  const toastLog = [];
  return {
    toasts: toastLog,
    toast: function (msg, level) {
      toastLog.push({msg: msg, level: level || 'info'});
      if (!toasts) return;
      const t = document.createElement('div');
      t.className = 'h-toast h-' + (level || 'info');
      t.textContent = msg;
      toasts.appendChild(t);
      setTimeout(function () { t.remove(); }, 4000);
    },
    log: function (msg) {
      if (!logEl) return;
      const li = document.createElement('li');
      li.textContent = msg;
      logEl.insertBefore(li, logEl.firstChild);
      while (logEl.childNodes.length > 40) logEl.removeChild(logEl.lastChild);
    },
  };
}

// ------------------------------------------------------------ seeding
function seed(doc, page) {
  if (page === 'floorplan' && !params.has('empty')) {
    doc.attachments = (doc.attachments || []).concat([
      {id: 'att-main-floor', name: 'main-floor.svg', file: 'plans/main-floor.svg', mime: 'image/svg+xml', kind: 'floorplan'},
      {id: 'att-dxf-fixture', name: 'dxf-fixture.svg', file: 'plans/dxf-fixture.svg', mime: 'image/svg+xml', kind: 'floorplan'},
      {id: 'att-stage', name: 'stage.svg', file: 'plans/stage.svg', mime: 'image/svg+xml', kind: 'floorplan'},
    ]);
    doc.floorplans = (doc.floorplans || []).concat([
      {id: 'fp-main-floor', name: 'Main floor', room: 'main', order: 0,
        source: {attachment: 'att-main-floor', kind: 'dxf', page: 0}, image: {attachment: 'att-main-floor', kind: 'svg', width: 2080, height: 1546.67},
        layers: [{name: 'WALLS', visible: true, count: 3}, {name: 'STAGE', visible: true, count: 3}, {name: 'SEATS', visible: true, count: 320},
          {name: 'AV', visible: true, count: 17}, {name: 'DOORS', visible: true, count: 5}, {name: 'TEXT', visible: true}, {name: 'GRID', visible: true}, {name: 'HIDDEN', visible: false}],
        units: {insunits: 6, meters_per_unit: 1.0},
        markers: [{device: 'sound-board', x: 0.46, y: 0.885}, {device: 'atem-mini', x: 0.54, y: 0.885},
          {device: 'main-speakers', x: 0.2, y: 0.32}, {device: 'sub-x2', x: 0.72, y: 0.32}, {device: 'stage-box-1', x: 0.3, y: 0.1}]},
      {id: 'fp-dxf-fixture', name: 'DXF fixture (20 x 15 m)', room: 'main', order: 1,
        source: {attachment: 'att-dxf-fixture', kind: 'dxf', page: 0}, image: {attachment: 'att-dxf-fixture', kind: 'svg', width: 2080, height: 1580},
        layers: [{name: 'WALLS', visible: true, count: 6}, {name: 'SEATS', visible: true, count: 2}, {name: 'HIDDEN', visible: false, count: 1}],
        units: {insunits: 6, meters_per_unit: 1.0}, markers: []},
      {id: 'fp-stage', name: 'Stage', room: 'main', order: 2,
        source: {attachment: 'att-stage', kind: 'drawio', page: 0}, image: {attachment: 'att-stage', kind: 'svg', width: 960, height: 510}, markers: []},
    ]);
  }
  if (page === 'rack' && params.has('demo')) {
    const set = function (id, rack) { doc.devices.forEach(function (d) { if (d.id === id) d.rack = rack; }); };
    set('video-converter', {id: 'rk-foh', u: 8, height: 1, face: 'front', side: 'full'});
    set('atem-mini', {id: 'rk-foh', u: 6, height: 1, face: 'front', side: 'right', depth: 'half'});
    set('sound-board', {id: 'rk-foh', u: 1, height: 3, face: 'rear', side: 'full', depth: 'half'});
  }
  if (page === 'rack' && params.has('collide')) {
    doc.devices.forEach(function (d) { if (d.id === 'sound-board') d.rack = {id: 'rk-foh', u: 10, height: 1, face: 'front', side: 'full'}; });
  }
  if (params.has('readonly')) doc.__readonly = true;
  return doc;
}

// ------------------------------------------------------------ walkthroughs
function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
function pe(target, type, x, y, extra) {
  const o = Object.assign({bubbles: true, cancelable: true, composed: true, clientX: x, clientY: y, pointerId: 7, pointerType: 'mouse', isPrimary: true, button: 0, buttons: type === 'pointerup' ? 0 : 1}, extra || {});
  target.dispatchEvent(new PointerEvent(type, o));
}
function drag(src, from, to, extra, moveTarget) {
  pe(src, 'pointerdown', from.x, from.y, extra);
  const steps = 6;
  for (let i = 1; i <= steps; i++) pe(moveTarget || src, 'pointermove', from.x + (to.x - from.x) * i / steps, from.y + (to.y - from.y) * i / steps, extra);
  pe(moveTarget || src, 'pointerup', to.x, to.y, extra);
}
function center(el) { const r = el.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; }
function key(el, k, extra) { el.dispatchEvent(new KeyboardEvent('keydown', Object.assign({key: k, bubbles: true, cancelable: true}, extra || {}))); }

async function walkFloorplan(root, handle, store, ui) {
  const out = {};
  const vp = root.querySelector('.fp-viewport');
  const S = handle._state;
  const plan = function (id) { return store.doc.floorplans.filter(function (f) { return f.id === id; })[0]; };
  const marker = function (id, dev) { return (plan(id).markers || []).filter(function (m) { return m.device === dev; })[0]; };
  const scr = function (ix, iy) { const vr = vp.getBoundingClientRect(); return {x: vr.left + ix * S.view.k + S.view.x, y: vr.top + iy * S.view.k + S.view.y}; };
  const MF = 'fp-main-floor';
  const W = 2080;
  const H = 1546.67;
  // drag an unplaced device (restream) from the side list onto the plan
  const grip = root.querySelector('.fp-grip[data-device="restream"]');
  drag(grip, center(grip), scr(1500, 1200));
  const mk = marker(MF, 'restream');
  out.dropMarker = mk || null;
  out.dropOk = !!mk && Math.abs(mk.x - 1500 / W) < 0.01 && Math.abs(mk.y - 1200 / H) < 0.01;
  // drag an existing marker and undo
  const before = JSON.stringify(marker(MF, 'sub-x2'));
  const mEl = root.querySelector('.fp-marker[data-device="sub-x2"] .fp-marker-in');
  const mc = scr(0.72 * W, 0.32 * H);
  drag(mEl, {x: mc.x + 4, y: mc.y}, {x: mc.x - 120, y: mc.y + 80}, null, vp);
  const moved = JSON.stringify(marker(MF, 'sub-x2'));
  store.undo();
  out.markerDrag = {moved: moved !== before, undoRestores: JSON.stringify(marker(MF, 'sub-x2')) === before};
  // keyboard nudge
  const k1 = root.querySelector('.fp-marker[data-device="atem-mini"]');
  const x0 = marker(MF, 'atem-mini').x;
  k1.focus();
  key(k1, 'ArrowRight');
  out.keyboardNudge = Math.round((marker(MF, 'atem-mini').x - x0) * 1e4) / 1e4;
  // zoom
  const k0 = S.view.k;
  root.querySelector('#fp-zoom-in').click();
  out.zoomIn = Math.round(S.view.k / k0 * 100) / 100;
  root.querySelector('#fp-fit').click();
  // tap a marker selects the device and opens the popover
  const k2 = root.querySelector('.fp-marker[data-device="sound-board"] .fp-marker-in');
  const c2 = center(k2);
  pe(k2, 'pointerdown', c2.x + 6, c2.y);
  pe(vp, 'pointerup', c2.x + 6, c2.y);
  out.tapSelects = store.selection && store.selection.id;
  out.popover = !root.querySelector('.fp-markerpop').hidden;
  // calibrate 10 m on the DXF fixture render: drawing (0,0) and (10,0) -> image px (40,1540), (1040,1540)
  const sel = root.querySelector('#fp-select');
  sel.value = 'fp-dxf-fixture';
  sel.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(30);
  root.querySelector('#fp-calibrate').click();
  [scr(40, 1540), scr(1040, 1540)].forEach(function (p) { pe(vp, 'pointerdown', p.x, p.y); pe(vp, 'pointerup', p.x, p.y); });
  root.querySelector('#fp-cal-distance').value = '10';
  root.querySelector('#fp-cal-unit').value = 'm';
  root.querySelector('.fp-calform button[type=submit]').click();
  out.calibration = plan('fp-dxf-fixture').calibration;
  // measure the same two points, then the 20 m back wall
  root.querySelector('#fp-measure').click();
  [scr(40, 1540), scr(1040, 1540)].forEach(function (p) { pe(vp, 'pointerdown', p.x, p.y); pe(vp, 'pointerup', p.x, p.y); });
  out.measureText = root.querySelector('.fp-readout').textContent;
  out.measureOk = /10\.0 m/.test(out.measureText);
  [scr(40, 40), scr(2040, 40)].forEach(function (p) { pe(vp, 'pointerdown', p.x, p.y); pe(vp, 'pointerup', p.x, p.y); });
  out.measureWall = root.querySelector('.fp-readout').textContent;
  out.ok = !!(out.calibration && out.measureOk && /20\.0 m/.test(out.measureWall) && out.dropOk && out.markerDrag.moved && out.markerDrag.undoRestores
    && out.keyboardNudge === 0.005 && out.tapSelects === 'sound-board' && out.popover);
  return out;
}

async function walkRack(root, handle, store, ui) {
  const out = {};
  const slots = function () { return root.querySelector('.rk-slots[data-rack="rk-foh"]'); };
  const ru = function () { return 22 * (handle._state.k || 1); };
  const yFor = function (u, h) { const r = slots().getBoundingClientRect(); return r.top + (12 - (u + h - 1)) * ru() + ru() / 2 * h; };
  const xIn = function () { const r = slots().getBoundingClientRect(); return r.left + 80; };
  const dev = function (id) { return store.doc.devices.filter(function (d) { return d.id === id; })[0]; };
  // 1. drop sound-board (full width) onto U10 (Shure Wireless, left half) -> refused
  let grip = root.querySelector('.rk-grip[data-device="sound-board"]');
  drag(grip, center(grip), {x: xIn(), y: yFor(10, 1)});
  out.refused = !dev('sound-board').rack;
  out.refusedToast = ui.toasts.length ? ui.toasts[ui.toasts.length - 1].msg : '';
  // 2. Alt-drop forces a placement with a collision warning
  grip = root.querySelector('.rk-grip[data-device="sound-board"]');
  drag(grip, center(grip), {x: xIn(), y: yFor(10, 1)}, {altKey: true});
  out.forced = dev('sound-board').rack || null;
  out.collideBlocks = root.querySelectorAll('.rk-block.rk-collide').length;
  out.warnings = Array.prototype.map.call(root.querySelectorAll('.rk-warnings li'), function (l) { return l.textContent; });
  // 3. undo removes it
  store.undo();
  out.undoClears = !dev('sound-board').rack && root.querySelectorAll('.rk-block.rk-collide').length === 0;
  // 4. drop ATEM Mini onto a free RU (U5)
  grip = root.querySelector('.rk-grip[data-device="atem-mini"]');
  drag(grip, center(grip), {x: xIn(), y: yFor(5, 1)});
  out.placedFree = dev('atem-mini').rack ? dev('atem-mini').rack.u : null;
  // 5. move a racked block by dragging (ATEM U5 -> U3)
  let blk = root.querySelector('.rk-block[data-device="atem-mini"]');
  const bc = center(blk);
  drag(blk, bc, {x: bc.x, y: bc.y + 2 * ru()});
  out.blockDrag = dev('atem-mini').rack.u;
  // 6. keyboard: Shure Wireless up twice (U12), third refused (out of range)
  blk = root.querySelector('.rk-block[data-device="shure-wireless"]');
  blk.focus(); key(blk, 'ArrowUp');
  blk = root.querySelector('.rk-block[data-device="shure-wireless"]'); key(blk, 'ArrowUp');
  blk = root.querySelector('.rk-block[data-device="shure-wireless"]'); key(blk, 'ArrowUp');
  out.keyboardU = dev('shure-wireless').rack.u;
  // 7. rear face shows full-depth devices from behind
  root.querySelector('#rk-face').click();
  out.rearBehind = root.querySelectorAll('.rk-slots[data-face="rear"] .rk-block.rk-behind').length;
  root.querySelector('#rk-face').click();
  // 8. new 12U rack
  root.querySelector('#rk-add').click();
  root.querySelector('#rk-f-name').value = 'Stage rack';
  root.querySelector('#rk-f-units').value = '12';
  root.querySelector('.rk-form button[type=submit]').click();
  out.newRack = store.doc.racks.filter(function (r) { return r.name === 'Stage rack'; })[0] || null;
  root.querySelector('#rk-select').value = '*';
  root.querySelector('#rk-select').dispatchEvent(new Event('change', {bubbles: true}));
  out.ok = out.refused && !!out.forced && out.collideBlocks === 2 && out.undoClears && out.placedFree === 5 && out.blockDrag === 3 && out.keyboardU === 12 && out.rearBehind >= 1 && !!out.newRack && out.newRack.units === 12;
  return out;
}

async function walkSchedules(root, handles, store, ui) {
  const out = {};
  const sch = root.querySelector('.sch-root');
  const rows = function () { return sch.querySelectorAll('.sch-table tbody tr[data-row]').length; };
  out.cablesRows = rows();
  sch.querySelector('#sch-assign-tags').click();
  await wait(50);
  const prev = handles.schedules._state.preview;
  out.preview = prev ? prev.ops.map(function (o) { return o.id + '=' + o.value.tag; }) : null;
  const want = ['c-0001=A-006', 'c-0002=A-007', 'c-0007=A-008', 'c-0009=A-009', 'c-0010=A-010', 'c-0011=A-011', 'c-0012=V-001', 'c-0013=V-002', 'c-0014=V-003', 'c-0015=X-001'];
  out.previewOk = !!out.preview && out.preview.join() === want.join();
  const confirmBtn = sch.querySelector('[data-act="confirm"]');
  if (confirmBtn) confirmBtn.click();
  await wait(20);
  out.tagsAssigned = store.doc.cables.filter(function (c) { return c.tag; }).length;
  out.undoSteps = store._undo ? store._undo.length : null;
  // inline edit a cable length (imperial fixture: feet -> meters)
  const lenInput = sch.querySelector('tr[data-id="c-0011"] input[data-edit="length"]');
  if (lenInput) { lenInput.value = '50'; lenInput.dispatchEvent(new Event('change', {bubbles: true})); }
  out.lengthM = store.doc.cables.filter(function (c) { return c.id === 'c-0011'; })[0].length_m;
  const tabRows = {};
  for (const k of ['ip', 'dmx', 'bom', 'patch', 'racks', 'labels']) {
    sch.querySelector('[data-kind="' + k + '"]').click();
    await wait(10);
    tabRows[k] = k === 'labels' ? sch.querySelectorAll('.sch-label').length : rows();
  }
  out.tabRows = tabRows;
  sch.querySelector('[data-kind="bom"]').click();
  const rs = sch.querySelector('#sch-room');
  rs.value = '*';
  rs.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(10);
  out.bomTotal = (sch.querySelector('.sch-totals') || {}).textContent || '';
  rs.value = 'current';
  rs.dispatchEvent(new Event('change', {bubbles: true}));
  sch.querySelector('[data-kind="cables"]').click();
  // inventory: bulk set 3 devices to spare = one undo step
  const inv = root.querySelector('.inv-root');
  const undo0 = store._undo ? store._undo.length : 0;
  ['wireless-mics', 'stage-box-1', 'restream'].forEach(function (id) {
    const cb = inv.querySelector('[data-select="' + id + '"]');
    cb.checked = true;
    cb.dispatchEvent(new Event('change', {bubbles: true}));
  });
  const bs = inv.querySelector('#inv-bulk-status');
  bs.value = 'spare';
  bs.dispatchEvent(new Event('change', {bubbles: true}));
  out.bulkSpare = store.doc.devices.filter(function (d) { return d.status === 'spare'; }).map(function (d) { return d.id; });
  out.bulkUndoSteps = (store._undo ? store._undo.length : 0) - undo0;
  store.undo();
  out.bulkUndone = store.doc.devices.filter(function (d) { return d.status === 'spare'; }).length === 1;
  // quick filter: warranty < 90 days excludes sound-board (no warranty)
  inv.querySelector('#inv-q-warranty').click();
  out.warrantyRows = inv.querySelectorAll('#inv-table tbody tr[data-device]').length;
  inv.querySelector('#inv-q-warranty').click();
  inv.querySelector('#inv-q-serial').click();
  out.missingSerialHasSoundBoard = !!inv.querySelector('tr[data-device="sound-board"]');
  inv.querySelector('#inv-q-serial').click();
  // system filter "Main video" -> 4 devices
  const sys = inv.querySelector('#inv-system');
  sys.value = 'main-video';
  sys.dispatchEvent(new Event('change', {bubbles: true}));
  out.mainVideoRows = inv.querySelectorAll('#inv-table tbody tr[data-device]').length;
  sys.value = '';
  sys.dispatchEvent(new Event('change', {bubbles: true}));
  // inventory form edit round-trip
  handles.inventory._openForm('atem-mini', null);
  const f = inv.querySelector('.inv-form');
  f.querySelector('[data-field="serial"]').value = 'ATEM-123';
  f.querySelector('[data-field="warranty_until"]').value = '2027-01-01';
  f.querySelector('[data-field="ip"]').value = '10.20.0.41';
  f.querySelector('button[type=submit]').click();
  const atem = store.doc.devices.filter(function (d) { return d.id === 'atem-mini'; })[0];
  out.formEdit = {serial: atem.inventory && atem.inventory.serial, warranty: atem.inventory && atem.inventory.warranty_until, ip: atem.interfaces[0].ip};
  out.ok = out.cablesRows === 15 && out.previewOk && out.tagsAssigned === 15 && out.lengthM === 15.24 && tabRows.ip === 3 && tabRows.racks === 1
    && /6498\.00 USD/.test(out.bomTotal) && out.bulkUndoSteps === 1 && out.bulkUndone && out.bulkSpare.length === 4 && out.warrantyRows === 0
    && !out.missingSerialHasSoundBoard && out.mainVideoRows === 4 && out.formEdit.serial === 'ATEM-123' && out.formEdit.ip === '10.20.0.41';
  return out;
}

// ------------------------------------------------------------ boot
async function main() {
  const page = document.body.getAttribute('data-harness');
  const ui = makeUi();
  const status = document.getElementById('h-status');
  let mc = null;
  try {
    if (params.has('shim')) throw new Error('shim forced');
    mc = await import('../../js/model-core.js');
    if (!mc || typeof mc.createStore !== 'function') mc = null;
  } catch (err) { mc = null; }
  const res = await fetch('fixture-v2.json');
  if (!res.ok) throw new Error('fixture-v2.json: HTTP ' + res.status);
  const doc = seed(await res.json(), page);
  const ro = !!doc.__readonly;
  delete doc.__readonly;
  const store = mc ? mc.createStore({doc: doc, vocab: VOCAB, readOnly: ro, overlay: null, room: params.get('room') || 'main'})
    : new ShimStore({doc: doc, vocab: VOCAB, readOnly: ro, room: params.get('room') || 'main'});
  const ctx = makeCtx(store, ui);
  window.__w4 = {store: store, ctx: ctx, handles: {}, modelCore: !!mc};
  if (status) status.textContent = (mc ? 'model-core.js store' : 'harness store shim') + ' \u00b7 fixture sunday-demo \u00b7 room ' + store.room + (ro ? ' \u00b7 read-only' : '');
  document.getElementById('h-undo').addEventListener('click', function () { store.undo(); });
  document.getElementById('h-redo').addEventListener('click', function () { store.redo(); });
  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z' && !e.target.closest('input,textarea,select')) {
      e.preventDefault(); if (e.shiftKey) store.redo(); else store.undo();
    }
  });
  const host = document.getElementById('h-main');
  if (page === 'floorplan') {
    const m = await import('../../js/floorplan.js');
    window.__w4.handles.floorplan = m.mount(host, ctx);
  } else if (page === 'rack') {
    const m = await import('../../js/rack.js');
    window.__w4.handles.rack = m.mount(host, ctx);
  } else {
    const m1 = await import('../../js/schedules.js');
    const m2 = await import('../../js/inventory.js');
    window.__w4.handles.schedules = m1.mount(document.getElementById('h-schedules'), ctx);
    window.__w4.handles.inventory = m2.mount(document.getElementById('h-inventory'), ctx);
  }
  await wait(50);
  if (params.has('walk')) {
    let w;
    try {
      if (page === 'floorplan') w = await walkFloorplan(host, window.__w4.handles.floorplan, store, ui);
      else if (page === 'rack') w = await walkRack(host, window.__w4.handles.rack, store, ui);
      else w = await walkSchedules(document.getElementById('h-main'), window.__w4.handles, store, ui);
    } catch (err) {
      w = {ok: false, error: String(err && (err.stack || err.message) || err)};
    }
    document.documentElement.setAttribute('data-walk', JSON.stringify(w));
  }
  if (params.has('smoke')) {
    setTimeout(function () {
      document.documentElement.setAttribute('data-smoke', JSON.stringify({ready: true, errors: window.__fathomErrors, stats: window.__pvStats || null}));
    }, 1000);
  }
}

main().catch(function (err) {
  window.__fathomErrors.push('harness: ' + String(err && (err.stack || err.message) || err));
  if (params.has('smoke')) document.documentElement.setAttribute('data-smoke', JSON.stringify({ready: false, errors: window.__fathomErrors, stats: null}));
});
