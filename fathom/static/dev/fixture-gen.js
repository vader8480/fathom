// Fathom patch view harness support (W3). Spec §6.12.
// makeFixture() is pure and importable in Node (T2 tests). bootPatchviewHarness() drives dev/patchview.html;
// it only runs when that page imports this module (the page carries data-harness="patchview").
// ES2018 syntax only.

import {cardLayout, slug} from '../js/patchview-core.js';
// Static (not dynamic) imports: headless Chrome's virtual clock tracks the initial module graph but not import().
// Both modules are side-effect free at import time, so Node can still import this file.
import {createStore} from '../js/model-core.js';
import {mount} from '../js/patchview.js';

// Snapshot of vocab.as_dict() (kinds, media, disciplines, brands, statuses) used when no server is reachable.
export const HARNESS_VOCAB = {"kinds":{"source":{"label":"Sources","discipline":"audio","color":"#2fd4b4","side":"left","routing":"none","legacy":"source"},"stage_io":{"label":"Stage I/O","discipline":"audio","color":"#4ea8ff","side":"left","routing":"matrix","legacy":"stage_io"},"computer":{"label":"Computers","discipline":"audio","color":"#a98bff","side":"left","routing":"matrix","legacy":"computer"},"console":{"label":"Consoles","discipline":"audio","color":"#7c5cff","side":"right","routing":"matrix","legacy":"console"},"iem":{"label":"IEM gear","discipline":"audio","color":"#f06aa8","side":"right","routing":"matrix","legacy":"iem"},"pa":{"label":"PA \u00b7 amps, speakers","discipline":"audio","color":"#ff9548","side":"right","routing":"matrix","legacy":"pa"},"network":{"label":"Network","discipline":"network","color":"#7b86ff","side":"right","routing":"matrix","legacy":"network"},"video":{"label":"Video","discipline":"video","color":"#c084fc","side":"left","routing":"matrix","legacy":"video"},"other":{"label":"Other","discipline":"other","color":"#9aa3b5","side":"right","routing":"matrix","legacy":"other"},"mic":{"label":"Microphones","discipline":"audio","color":"#2fd4b4","side":"left","routing":"none","legacy":"source"},"wireless_rx":{"label":"Wireless receivers","discipline":"audio","color":"#38bdf8","side":"left","routing":"matrix","legacy":"stage_io"},"processor":{"label":"Processors \u00b7 DSP","discipline":"audio","color":"#60a5fa","side":"right","routing":"matrix","legacy":"console"},"amp":{"label":"Amplifiers","discipline":"audio","color":"#fb923c","side":"right","routing":"matrix","legacy":"pa"},"speaker":{"label":"Loudspeakers","discipline":"audio","color":"#fdba74","side":"right","routing":"passthrough","legacy":"pa"},"recorder":{"label":"Recorders","discipline":"audio","color":"#a78bfa","side":"right","routing":"matrix","legacy":"computer"},"intercom":{"label":"Intercom","discipline":"audio","color":"#f472b6","side":"right","routing":"matrix","legacy":"other"},"camera":{"label":"Cameras","discipline":"video","color":"#34d399","side":"left","routing":"matrix","legacy":"video"},"video_source":{"label":"Playback \u00b7 media servers","discipline":"video","color":"#2dd4bf","side":"left","routing":"matrix","legacy":"video"},"video_switcher":{"label":"Video switchers","discipline":"video","color":"#22c55e","side":"right","routing":"matrix","legacy":"console"},"video_router":{"label":"Video routers","discipline":"video","color":"#10b981","side":"right","routing":"matrix","legacy":"console"},"converter":{"label":"Converters \u00b7 extenders","discipline":"video","color":"#86efac","side":"right","routing":"matrix","legacy":"video"},"encoder":{"label":"Encoders \u00b7 streaming","discipline":"video","color":"#4ade80","side":"right","routing":"matrix","legacy":"computer"},"stream":{"label":"Stream destinations","discipline":"network","color":"#fb923c","side":"right","routing":"none","legacy":"pa"},"display":{"label":"Displays","discipline":"video","color":"#a3e635","side":"right","routing":"passthrough","legacy":"pa"},"projector":{"label":"Projectors","discipline":"video","color":"#bef264","side":"right","routing":"none","legacy":"pa"},"lighting_console":{"label":"Lighting consoles","discipline":"lighting","color":"#fbbf24","side":"left","routing":"matrix","legacy":"console"},"dmx_node":{"label":"DMX nodes \u00b7 splitters","discipline":"lighting","color":"#f59e0b","side":"right","routing":"matrix","legacy":"stage_io"},"dimmer":{"label":"Dimmers \u00b7 relays","discipline":"lighting","color":"#eab308","side":"right","routing":"matrix","legacy":"pa"},"fixture":{"label":"Lighting fixtures","discipline":"lighting","color":"#fde047","side":"right","routing":"passthrough","legacy":"pa"},"switch":{"label":"Network switches","discipline":"network","color":"#fb923c","side":"right","routing":"matrix","legacy":"network"},"control":{"label":"Control processors","discipline":"control","color":"#c084fc","side":"right","routing":"matrix","legacy":"other"},"touch_panel":{"label":"Touch panels","discipline":"control","color":"#d8b4fe","side":"left","routing":"none","legacy":"source"},"power":{"label":"Power \u00b7 UPS \u00b7 PDU","discipline":"power","color":"#f87171","side":"right","routing":"matrix","legacy":"other"},"patch_panel":{"label":"Patch panels \u00b7 wall plates","discipline":"other","color":"#94a3b8","side":"right","routing":"passthrough","legacy":"stage_io"}},"media":{"dante":{"label":"Dante \u00b7 Cat6","color":"#7b86ff","dash":"","width":1.6,"arrow":false,"discipline":"audio","carries":["audio","network"],"ip":true,"connector":"etherCON","short":"DANTE"},"analog":{"label":"Analog \u00b7 XLR","color":"#aab3c5","dash":"","width":1.4,"arrow":true,"discipline":"audio","carries":["audio"],"ip":false,"connector":"XLR3","short":"XLR"},"aes3":{"label":"AES3 \u00b7 110 \u03a9","color":"#2dd4ee","dash":"7 4","width":1.5,"arrow":true,"discipline":"audio","carries":["audio"],"ip":false,"connector":"XLR3","short":"AES"},"aes50":{"label":"AES50 \u00b7 Cat5e","color":"#5ac8fa","dash":"2 4","width":1.6,"arrow":false,"discipline":"audio","carries":["audio","control"],"ip":false,"connector":"etherCON","short":"AES50"},"madi":{"label":"MADI","color":"#fbbf24","dash":"10 4","width":1.5,"arrow":true,"discipline":"audio","carries":["audio"],"ip":false,"connector":"BNC","short":"MADI"},"avb":{"label":"AVB / Milan","color":"#34d399","dash":"6 3 2 3","width":1.5,"arrow":false,"discipline":"audio","carries":["audio","network"],"ip":true,"connector":"etherCON","short":"AVB"},"speaker":{"label":"Speaker \u00b7 NL4/NL8","color":"#ff9548","dash":"","width":1.8,"arrow":true,"discipline":"audio","carries":["audio"],"ip":false,"connector":"NL4","short":"SPK"},"iem_wired":{"label":"Wired IEM","color":"#f472b6","dash":"1.5 4","width":1.6,"arrow":true,"discipline":"audio","carries":["audio"],"ip":false,"connector":"TRS 1/4\"","short":"IEM"},"iem_wireless":{"label":"Wireless IEM","color":"#e879f9","dash":"1.5 6","width":1.6,"arrow":true,"discipline":"audio","carries":["audio"],"ip":false,"connector":"RF","short":"IEM"},"rf":{"label":"RF \u00b7 wireless mic","color":"#f0abfc","dash":"1.5 6","width":1.6,"arrow":true,"discipline":"audio","carries":["audio"],"ip":false,"connector":"BNC","short":"RF"},"usb":{"label":"USB","color":"#cbd5e1","dash":"4 3","width":1.2,"arrow":true,"discipline":"other","carries":["audio","video","control"],"ip":false,"connector":"USB-C","short":"USB"},"video":{"label":"SDI / HDMI","color":"#c084fc","dash":"","width":1.2,"arrow":true,"discipline":"video","carries":["video","audio"],"ip":false,"connector":"BNC","short":"VID"},"network":{"label":"Control \u00b7 IP","color":"#94a3b8","dash":"3 3","width":1.0,"arrow":false,"discipline":"network","carries":["network","control","audio","video","lighting"],"ip":true,"connector":"RJ45","short":"CAT"},"other":{"label":"Other","color":"#9aa3b5","dash":"","width":1.2,"arrow":true,"discipline":"other","carries":["audio","video","lighting","control","network","power"],"ip":false,"connector":"","short":"OTH"},"aes67":{"label":"AES67 \u00b7 IP audio","color":"#818cf8","dash":"","width":1.6,"arrow":false,"discipline":"audio","carries":["audio","network"],"ip":true,"connector":"RJ45","short":"AES67"},"qlan":{"label":"Q-LAN","color":"#60a5fa","dash":"","width":1.6,"arrow":false,"discipline":"audio","carries":["audio","video","control","network"],"ip":true,"connector":"RJ45","short":"QLAN"},"snake":{"label":"Digital snake \u00b7 Cat5e","color":"#38bdf8","dash":"2 3","width":1.6,"arrow":false,"discipline":"audio","carries":["audio","control"],"ip":false,"connector":"etherCON","short":"SNAKE"},"adat":{"label":"ADAT \u00b7 optical","color":"#67e8f9","dash":"1 3","width":1.4,"arrow":true,"discipline":"audio","carries":["audio"],"ip":false,"connector":"TOSLINK","short":"ADAT"},"speaker_70v":{"label":"70/100 V line","color":"#fdba74","dash":"8 3","width":1.6,"arrow":true,"discipline":"audio","carries":["audio"],"ip":false,"connector":"terminal","short":"70V"},"intercom":{"label":"Intercom \u00b7 XLR","color":"#fb7185","dash":"5 2 1 2","width":1.4,"arrow":false,"discipline":"audio","carries":["audio","control"],"ip":false,"connector":"XLR3","short":"COM"},"sdi":{"label":"SDI \u00b7 75 \u03a9 BNC","color":"#facc15","dash":"","width":1.6,"arrow":true,"discipline":"video","carries":["video","audio"],"ip":false,"connector":"BNC","short":"SDI"},"hdmi":{"label":"HDMI","color":"#f59e0b","dash":"","width":1.6,"arrow":true,"discipline":"video","carries":["video","audio"],"ip":false,"connector":"HDMI-A","short":"HDMI"},"displayport":{"label":"DisplayPort","color":"#fda4af","dash":"","width":1.4,"arrow":true,"discipline":"video","carries":["video","audio"],"ip":false,"connector":"DP","short":"DP"},"hdbaset":{"label":"HDBaseT \u00b7 Cat6","color":"#fcd34d","dash":"5 2","width":1.6,"arrow":true,"discipline":"video","carries":["video","audio","control"],"ip":false,"connector":"RJ45","short":"HDBT"},"fiber":{"label":"Fiber","color":"#22d3ee","dash":"12 3","width":1.6,"arrow":false,"discipline":"other","carries":["audio","video","network","control","lighting"],"ip":false,"connector":"LC","short":"FIB"},"ndi":{"label":"NDI \u00b7 IP video","color":"#a3e635","dash":"4 2","width":1.4,"arrow":false,"discipline":"video","carries":["video","audio","network"],"ip":true,"connector":"RJ45","short":"NDI"},"st2110":{"label":"SMPTE ST 2110","color":"#84cc16","dash":"4 2 1 2","width":1.4,"arrow":false,"discipline":"video","carries":["video","audio","network"],"ip":true,"connector":"SFP","short":"2110"},"dmx":{"label":"DMX512 \u00b7 XLR5","color":"#fde047","dash":"","width":1.6,"arrow":true,"discipline":"lighting","carries":["lighting"],"ip":false,"connector":"XLR5","short":"DMX"},"rdm":{"label":"DMX + RDM","color":"#fef08a","dash":"6 2","width":1.6,"arrow":false,"discipline":"lighting","carries":["lighting","control"],"ip":false,"connector":"XLR5","short":"RDM"},"sacn":{"label":"sACN (E1.31)","color":"#fbbf24","dash":"3 2","width":1.4,"arrow":true,"discipline":"lighting","carries":["lighting","network"],"ip":true,"connector":"RJ45","short":"SACN"},"artnet":{"label":"Art-Net","color":"#f59e0b","dash":"3 2 1 2","width":1.4,"arrow":true,"discipline":"lighting","carries":["lighting","network"],"ip":true,"connector":"RJ45","short":"ARTN"},"rs232":{"label":"RS-232 \u00b7 serial","color":"#c4b5fd","dash":"2 2","width":1.0,"arrow":true,"discipline":"control","carries":["control"],"ip":false,"connector":"DB9","short":"232"},"rs422":{"label":"RS-422/485","color":"#a78bfa","dash":"2 2","width":1.0,"arrow":false,"discipline":"control","carries":["control"],"ip":false,"connector":"Phoenix","short":"422"},"ir":{"label":"IR emitter","color":"#ddd6fe","dash":"1 3","width":1.0,"arrow":true,"discipline":"control","carries":["control"],"ip":false,"connector":"TS 3.5mm","short":"IR"},"gpio":{"label":"GPIO \u00b7 contact closure","color":"#e9d5ff","dash":"1 2","width":1.0,"arrow":true,"discipline":"control","carries":["control"],"ip":false,"connector":"Phoenix","short":"GPIO"},"osc":{"label":"OSC \u00b7 IP control","color":"#d8b4fe","dash":"3 3","width":1.0,"arrow":true,"discipline":"control","carries":["control","network"],"ip":true,"connector":"RJ45","short":"OSC"},"midi":{"label":"MIDI","color":"#f0abfc","dash":"2 3","width":1.0,"arrow":true,"discipline":"control","carries":["control"],"ip":false,"connector":"DIN5","short":"MIDI"},"timecode":{"label":"Timecode (LTC)","color":"#f5d0fe","dash":"1 2","width":1.0,"arrow":true,"discipline":"control","carries":["control"],"ip":false,"connector":"XLR3","short":"LTC"},"sync":{"label":"Sync \u00b7 word clock / genlock","color":"#94a3b8","dash":"1 4","width":1.0,"arrow":true,"discipline":"other","carries":["control"],"ip":false,"connector":"BNC","short":"SYNC"},"power":{"label":"Power \u00b7 mains","color":"#f87171","dash":"","width":2.0,"arrow":true,"discipline":"power","carries":["power"],"ip":false,"connector":"IEC C13","short":"PWR"},"power_dc":{"label":"DC power","color":"#fca5a5","dash":"","width":1.4,"arrow":true,"discipline":"power","carries":["power"],"ip":false,"connector":"barrel","short":"DC"}},"disciplines":{"audio":{"label":"Audio","color":"#4ea8ff","letter":"A"},"video":{"label":"Video","color":"#34d399","letter":"V"},"lighting":{"label":"Lighting","color":"#fbbf24","letter":"L"},"network":{"label":"Network","color":"#fb923c","letter":"N"},"control":{"label":"Control","color":"#c084fc","letter":"C"},"power":{"label":"Power","color":"#f87171","letter":"P"},"other":{"label":"Other","color":"#9aa3b5","letter":"X"}},"brands":{"yamaha":{"text":"YAMAHA","bg":"#1a1a1a","fg":"#ffffff","style":"wordmark"},"shure":{"text":"SHURE","bg":"#f3f4f6","fg":"#111111","style":"bold-italic"},"focusrite":{"text":"Focusrite","bg":"#f3f4f6","fg":"#c2410c","style":"serif"},"neve":{"text":"N","bg":"#d7263d","fg":"#ffffff","style":"mono"},"ross":{"text":"ROSS","bg":"#f3f4f6","fg":"#c01830","style":"bold"},"genelec":{"text":"GENELEC","bg":"#ffffff","fg":"#0b6e4f","style":"bold"},"waves":{"text":"W","bg":"#111111","fg":"#ffffff","style":"mono"},"ableton":{"text":"\u25ae\u25ae\u25ae","bg":"#f3f4f6","fg":"#111111","style":"mono"},"avid":{"text":"AVID","bg":"#7c3aed","fg":"#ffffff","style":"bold"},"l-acoustics":{"text":"L-A","bg":"#f3f4f6","fg":"#111111","style":"mono"},"lectrosonics":{"text":"LECTRO","bg":"#1f2937","fg":"#e5e7eb","style":"bold"},"behringer":{"text":"BEHRINGER","bg":"#1f2937","fg":"#facc15","style":"bold"},"midas":{"text":"MIDAS","bg":"#1f2937","fg":"#e5e7eb","style":"bold"},"sennheiser":{"text":"SENNHEISER","bg":"#111111","fg":"#ffffff","style":"bold"},"allen-heath":{"text":"A&H","bg":"#111111","fg":"#ffffff","style":"bold"},"digico":{"text":"DiGiCo","bg":"#111111","fg":"#ffffff","style":"bold"},"qsc":{"text":"QSC","bg":"#111111","fg":"#60a5fa","style":"bold"},"powersoft":{"text":"POWERSOFT","bg":"#111111","fg":"#ffffff","style":"bold"},"d&b":{"text":"d&b","bg":"#f3f4f6","fg":"#111111","style":"bold"},"meyer":{"text":"MEYER","bg":"#f3f4f6","fg":"#111111","style":"bold"},"audinate":{"text":"Dante","bg":"#1d4ed8","fg":"#ffffff","style":"bold"},"blackmagic":{"text":"BMD","bg":"#111111","fg":"#f59e0b","style":"bold"},"apple":{"text":"","bg":"#f3f4f6","fg":"#111111","style":"mono"},"microsoft":{"text":"MS","bg":"#f3f4f6","fg":"#111111","style":"bold"},"ma":{"text":"MA","bg":"#111111","fg":"#f5c518","style":"bold"},"etc":{"text":"ETC","bg":"#111111","fg":"#ffffff","style":"bold"},"chauvet":{"text":"CHAUVET","bg":"#111111","fg":"#e5e7eb","style":"bold"},"martin":{"text":"MARTIN","bg":"#111111","fg":"#ef4444","style":"bold"},"panasonic":{"text":"Panasonic","bg":"#f3f4f6","fg":"#1d4ed8","style":"serif"},"sony":{"text":"SONY","bg":"#111111","fg":"#ffffff","style":"bold"},"epson":{"text":"EPSON","bg":"#f3f4f6","fg":"#1e3a8a","style":"bold"},"samsung":{"text":"SAMSUNG","bg":"#1e3a8a","fg":"#ffffff","style":"bold"},"extron":{"text":"EXTRON","bg":"#111111","fg":"#ffffff","style":"bold"},"crestron":{"text":"CRESTRON","bg":"#111111","fg":"#93c5fd","style":"bold"},"cisco":{"text":"CISCO","bg":"#f3f4f6","fg":"#0369a1","style":"bold"},"netgear":{"text":"NETGEAR","bg":"#111111","fg":"#a78bfa","style":"bold"},"ubiquiti":{"text":"UBNT","bg":"#f3f4f6","fg":"#0ea5e9","style":"bold"},"decimator":{"text":"DECIMATOR","bg":"#111111","fg":"#f97316","style":"bold"},"whirlwind":{"text":"WHIRLWIND","bg":"#111111","fg":"#e5e7eb","style":"bold"},"electro-voice":{"text":"EV","bg":"#111111","fg":"#ef4444","style":"bold"}},"statuses":["installed","planned","spare","retired"]};

// ---------------------------------------------------------------- synthetic fixture

function rng(seed) {
  let a = (seed >>> 0) || 1;
  return function () {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Per kind: label, manufacturer/model, and port groups [group, dir, medium, weight].
const KIND_SPECS = [
  {kind: 'mic', label: 'Wireless Mic', mf: 'Shure', model: 'ULXD2', groups: [['RF Out', 'out', 'rf', 1], ['Analog Out', 'out', 'analog', 1]]},
  {kind: 'stage_io', label: 'Stage Box', mf: 'Allen & Heath', model: 'AR2412', groups: [['Analog In', 'in', 'analog', 3], ['Analog Out', 'out', 'analog', 2], ['Network', 'io', 'network', 0.3]]},
  {kind: 'wireless_rx', label: 'Wireless Receiver', mf: 'Shure', model: 'ULXD4Q', groups: [['RF In', 'in', 'rf', 1], ['Analog Out', 'out', 'analog', 1]]},
  {kind: 'console', label: 'Console', mf: 'Yamaha', model: 'CL5', groups: [['Analog In', 'in', 'analog', 2], ['Analog Out', 'out', 'analog', 1], ['AES Out', 'out', 'aes3', 0.5], ['Network', 'io', 'network', 0.3]]},
  {kind: 'processor', label: 'DSP', mf: 'QSC', model: 'Core 110f', groups: [['Analog In', 'in', 'analog', 1], ['AES In', 'in', 'aes3', 0.5], ['Analog Out', 'out', 'analog', 1]]},
  {kind: 'amp', label: 'Amplifier', mf: 'Powersoft', model: 'X4', groups: [['Analog In', 'in', 'analog', 1], ['Speaker Out', 'out', 'speaker', 1]]},
  {kind: 'speaker', label: 'Loudspeaker', mf: 'd&b', model: 'Y10P', groups: [['Speaker In', 'in', 'speaker', 1], ['Speaker Thru', 'out', 'speaker', 0.3]]},
  {kind: 'camera', label: 'Camera', mf: 'Panasonic', model: 'AW-UE150', groups: [['SDI Out', 'out', 'sdi', 1], ['HDMI Out', 'out', 'hdmi', 0.5], ['Network', 'io', 'network', 0.3]]},
  {kind: 'video_switcher', label: 'Switcher', mf: 'Blackmagic Design', model: 'ATEM Constellation', groups: [['SDI In', 'in', 'sdi', 2], ['HDMI In', 'in', 'hdmi', 1], ['SDI Out', 'out', 'sdi', 1], ['HDMI Out', 'out', 'hdmi', 0.5]]},
  {kind: 'converter', label: 'Converter', mf: 'Decimator Design', model: 'MD-HX', groups: [['HDMI In', 'in', 'hdmi', 1], ['SDI In', 'in', 'sdi', 1], ['SDI Out', 'out', 'sdi', 1], ['HDMI Out', 'out', 'hdmi', 1]]},
  {kind: 'display', label: 'Display', mf: 'Samsung', model: 'QB65', groups: [['SDI In', 'in', 'sdi', 1], ['HDMI In', 'in', 'hdmi', 1]]},
  {kind: 'lighting_console', label: 'Lighting Desk', mf: 'ETC', model: 'Ion Xe', groups: [['DMX Out', 'out', 'dmx', 1], ['Network', 'io', 'network', 0.3]]},
  {kind: 'dmx_node', label: 'DMX Node', mf: 'ETC', model: 'Response 4-Port', groups: [['DMX In', 'in', 'dmx', 1], ['DMX Out', 'out', 'dmx', 2]]},
  {kind: 'fixture', label: 'Fixture', mf: 'Chauvet', model: 'Maverick', groups: [['DMX In', 'in', 'dmx', 1], ['DMX Thru', 'out', 'dmx', 1]]},
  {kind: 'switch', label: 'Network Switch', mf: 'Netgear', model: 'M4250', groups: [['Port', 'io', 'network', 1]]},
  {kind: 'control', label: 'Control Processor', mf: 'Crestron', model: 'CP4N', groups: [['Network', 'io', 'network', 1], ['RS-232 Out', 'out', 'rs232', 1]]},
  {kind: 'projector', label: 'Projector', mf: 'Epson', model: 'EB-PU2010', groups: [['HDMI In', 'in', 'hdmi', 1], ['HDBaseT In', 'in', 'hdbaset', 0.5], ['RS-232 In', 'in', 'rs232', 0.5]]},
];

function makePorts(spec, n, rand) {
  const gs = spec.groups;
  const totalW = gs.reduce(function (s, g) { return s + g[3]; }, 0);
  const counts = gs.map(function (g) { return Math.max(1, Math.floor(n * g[3] / totalW)); });
  let sum = counts.reduce(function (s, c) { return s + c; }, 0);
  let i = 0;
  while (sum < n) { counts[i % counts.length]++; sum++; i++; }
  while (sum > n) {
    const j = counts.indexOf(Math.max.apply(null, counts));
    counts[j]--; sum--;
  }
  const ports = [];
  gs.forEach(function (g, gi) {
    const base = slug(g[0]);
    for (let k = 1; k <= counts[gi]; k++) {
      const p = {id: base + '-' + k, name: (g[1] === 'in' ? 'Input ' : g[1] === 'out' ? 'Output ' : 'Port ') + k,
        dir: g[1], medium: g[2], group: g[0], index: k};
      if (rand() < 0.3) p.label = g[0].split(' ')[0] + ' ' + k;
      ports.push(p);
    }
  });
  return ports;
}

export function makeFixture(opts) {
  opts = opts || {};
  const nDev = opts.devices === undefined ? 150 : Math.max(1, opts.devices | 0);
  const nCab = opts.cables === undefined ? 600 : Math.max(0, opts.cables | 0);
  const rand = rng(opts.seed === undefined ? 1 : opts.seed);
  const pick = function (n) { return Math.floor(rand() * n); };
  const devices = [];
  const counters = {};
  for (let i = 0; i < nDev; i++) {
    const spec = KIND_SPECS[i % KIND_SPECS.length];
    counters[spec.kind] = (counters[spec.kind] || 0) + 1;
    const n = 4 + pick(21);
    const d = {id: slug(spec.kind) + '-' + counters[spec.kind], name: spec.label + ' ' + counters[spec.kind],
      kind: spec.kind, room: 'main', manufacturer: spec.mf, model: spec.model,
      status: rand() < 0.06 ? 'planned' : 'installed', ports: makePorts(spec, n, rand)};
    devices.push(d);
  }
  // Cables: out -> in (unused in ports, same medium), io <-> io for network; prefer targets later in the list.
  const freeIn = {};
  const outs = [];
  const ios = [];
  devices.forEach(function (d, di) {
    d.ports.forEach(function (p) {
      if (p.dir === 'in') (freeIn[p.medium] || (freeIn[p.medium] = [])).push({di: di, p: p});
      else if (p.dir === 'out') outs.push({di: di, p: p});
      else ios.push({di: di, p: p, used: false});
    });
  });
  const cables = [];
  const usedOut = {};
  let guard = 0;
  function addCable(a, b, bidi) {
    const c = {id: 'c-' + String(cables.length + 1).padStart(4, '0'),
      from: {device: devices[a.di].id, port: a.p.id}, to: {device: devices[b.di].id, port: b.p.id}, medium: a.p.medium};
    if (bidi) c.bidirectional = true;
    cables.push(c);
  }
  while (cables.length < nCab && guard++ < nCab * 40) {
    if (ios.length > 1 && rand() < 0.12) {
      const a = ios[pick(ios.length)];
      if (a.used) continue;
      let best = null;
      for (let t = 0; t < 12; t++) {
        const b = ios[pick(ios.length)];
        if (!b.used && b.di !== a.di && b.p.medium === a.p.medium) { best = b; break; }
      }
      if (!best) continue;
      a.used = best.used = true;
      addCable(a, best, true);
      continue;
    }
    const o = outs[pick(outs.length)];
    const key = o.di + ':' + o.p.id;
    if (usedOut[key] && rand() < 0.85) continue;
    const pool = freeIn[o.p.medium];
    if (!pool || !pool.length) continue;
    let bi = -1;
    for (let t = 0; t < 16; t++) {
      const j = pick(pool.length);
      const cand = pool[j];
      if (cand.di === o.di) continue;
      if (cand.di > o.di || t > 10) { bi = j; break; }
    }
    if (bi < 0) continue;
    const target = pool.splice(bi, 1)[0];
    usedOut[key] = true;
    addCable(o, target, false);
  }
  // Positions: columns by device order, stacked by card height.
  const cols = Math.max(1, Math.round(Math.sqrt(nDev / 1.3)));
  const perCol = Math.ceil(nDev / cols);
  const connected = {};
  cables.forEach(function (c) {
    [c.from, c.to].forEach(function (e) { (connected[e.device] || (connected[e.device] = new Set())).add(e.port); });
  });
  let y = 40;
  devices.forEach(function (d, i) {
    const col = Math.floor(i / perCol);
    if (i % perCol === 0) y = 40;
    d.patch = {x: 40 + col * 344, y: y};
    y += cardLayout(d, {connected: connected[d.id] || new Set()}).h + 24;
    y = Math.round(y / 8) * 8;
  });
  return {
    fathom: 2, revision: 0,
    meta: {org: 'Synthetic', system: 'Load test', title: 'Synthetic ' + nDev + ' / ' + nCab, slug: 'synthetic'},
    settings: {default_room: 'main', units: 'metric', cable_tag_pattern: '{D}-{n:03}', currency: 'USD', public_url: '', autosave: true},
    venues: [{id: 'venue', name: 'Synthetic Venue'}],
    rooms: [{id: 'main', venue: 'venue', name: 'Main', code: 'MAIN', kind: 'auditorium'}],
    systems: [], locations: [], racks: [], networks: [], devices: devices, cables: cables, bundles: [],
    floorplans: [], attachments: [], templates: [], imports: [],
  };
}

// ---------------------------------------------------------------- harness (browser only)

export const HARNESS_TEMPLATE = {
  id: 'blackmagic-atem-mini-pro', manufacturer: 'Blackmagic Design', model: 'ATEM Mini Pro', name: 'ATEM Mini Pro',
  kind: 'video_switcher', discipline: 'video', brand: 'blackmagic',
  ports: [
    {group: 'HDMI In', dir: 'in', medium: 'hdmi', connector: 'HDMI-A', count: 4},
    {group: 'Mic In', dir: 'in', medium: 'analog', connector: 'TRS 3.5mm', count: 2},
    {group: 'HDMI Out', dir: 'out', medium: 'hdmi', connector: 'HDMI-A'},
    {group: 'USB Out', dir: 'out', medium: 'usb', connector: 'USB-C'},
    {group: 'Ethernet', dir: 'io', medium: 'network', connector: 'RJ45'},
  ],
};

const HARNESS_OVERLAY = {
  devices: [],
  routes: [
    {kind: 'dante', from: {device: 'sound-board', port: 'slink'}, to: {device: 'atem-mini'}, medium: 'dante', label: 'Stream L'},
    {kind: 'dante', from: {device: 'sound-board', port: 'slink'}, to: {device: 'atem-mini'}, medium: 'dante', label: 'Stream R'},
  ],
  port_labels: {'audio-rack-1': {'analog-in-5': 'Pastor lav', 'analog-in-6': 'Choir L'}},
};

function getText(url) {
  return new Promise(function (resolve, reject) {
    const x = new XMLHttpRequest();
    x.open('GET', url, true);
    x.onload = function () {
      if (x.status === 200 || (x.status === 0 && x.responseText)) resolve(x.responseText);
      else reject(new Error('HTTP ' + x.status + ' for ' + url));
    };
    x.onerror = function () { reject(new Error('Cannot load ' + url)); };
    x.send();
  });
}

export function bootPatchviewHarness(win) {
  const document = win.document;
  const errors = win.__fathomErrors || (win.__fathomErrors = []);
  win.addEventListener('error', function (e) { errors.push(String((e && e.message) || e)); });
  win.addEventListener('unhandledrejection', function (e) { errors.push('unhandled: ' + String(e && e.reason && (e.reason.stack || e.reason))); });
  const origError = win.console.error;
  win.console.error = function () {
    errors.push(Array.prototype.map.call(arguments, String).join(' '));
    return origError.apply(win.console, arguments);
  };
  const params = new URLSearchParams(win.location.search);
  const smoke = params.get('smoke') === '1';
  const host = document.getElementById('pv-host');
  const live = document.getElementById('fathom-live');
  const toasts = document.getElementById('pv-harness-toasts');
  const logEl = document.getElementById('pv-harness-log');
  function log(msg) {
    if (!logEl) return;
    const li = document.createElement('li');
    li.textContent = msg;
    logEl.insertBefore(li, logEl.firstChild);
    while (logEl.childNodes.length > 40) logEl.removeChild(logEl.lastChild);
  }
  function toast(message, level) {
    log('toast[' + (level || 'info') + ']: ' + message);
    if (!toasts) return;
    const t = document.createElement('div');
    t.className = 'h-toast h-' + (level || 'info');
    t.setAttribute('role', 'status');
    t.textContent = message;
    toasts.appendChild(t);
    win.setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 3200);
  }
  function announce(text) {
    if (!live || !text) return;
    live.textContent = '';
    win.setTimeout(function () { live.textContent = text; }, 30);
  }
  const nDev = params.get('devices');
  const nCab = params.get('cables');
  const docP = (nDev || nCab)
    ? Promise.resolve(makeFixture({devices: nDev ? +nDev : 150, cables: nCab ? +nCab : 600, seed: +(params.get('seed') || 1)}))
    : getText('fixture-v2.json').then(JSON.parse);
  const vocabP = /^https?:$/.test(win.location.protocol)
    ? getText('../../api/v2/meta').then(function (t) { const m = JSON.parse(t); return m.vocab || HARNESS_VOCAB; })
      .catch(function () { return HARNESS_VOCAB; })
    : Promise.resolve(HARNESS_VOCAB);
  return Promise.all([docP, vocabP]).then(function (r) {
    const doc = r[0], vocab = r[1];
    const store = createStore({doc: doc, vocab: vocab, readOnly: params.get('readonly') === '1',
      overlay: params.get('overlay') === '1' && !nDev ? HARNESS_OVERLAY : null,
      room: params.has('room') ? params.get('room') : ((doc.settings && doc.settings.default_room) || 'main')});
    const ctx = {
      store: store, vocab: vocab, api: null, project: nDev ? 'synthetic' : 'sunday-demo',
      commit: function (ops, label) {
        if (store.readOnly) { toast('Read-only: changes are not allowed', 'warn'); return store.doc; }
        const d = store.commit(ops, label);
        announce(label);
        log('commit: ' + (label || 'Edit') + ' (' + ops.length + ' ops)');
        return d;
      },
      select: function (sel) { store.select(sel); },
      highlight: function (h) { store.highlight(h); },
      navigate: function (view, p) { toast('navigate ' + view + ' ' + JSON.stringify(p || {}), 'info'); },
      pickTemplate: function () { return Promise.resolve(HARNESS_TEMPLATE); },
      pickPort: function () { return Promise.resolve(null); },
      pickDevice: function () { return Promise.resolve(store.doc.devices.length ? store.doc.devices[0].id : null); },
      toast: toast,
      confirm: function (message) { log('confirm: ' + message + ' -> yes'); return Promise.resolve(true); },
      openInspector: function (sel) { toast('inspector: ' + JSON.stringify(sel), 'info'); },
      env: {touch: win.matchMedia ? win.matchMedia('(pointer: coarse)').matches : false,
        narrow: win.innerWidth < 700, platform: /iP(ad|hone|od)/.test(win.navigator.userAgent) ? 'ios' :
          (/Mac/.test(win.navigator.platform) ? 'mac' : 'other'), online: win.navigator.onLine, secure: !!win.isSecureContext},
    };
    store.addEventListener('selection', function (e) { log('selection: ' + JSON.stringify(e.detail)); });
    const handle = mount(host, ctx);
    win.__pv = {store: store, ctx: ctx, handle: handle, makeFixture: makeFixture};
    if (smoke) {
      win.setTimeout(function () {
        document.documentElement.setAttribute('data-smoke', JSON.stringify({ready: true, errors: errors,
          stats: win.__pvStats || null}));
      }, 1000);
    }
    return win.__pv;
  }).catch(function (err) {
    errors.push('harness: ' + String(err && (err.stack || err)));
    if (host) host.textContent = 'Harness failed: ' + String(err && err.message);
    if (smoke) document.documentElement.setAttribute('data-smoke', JSON.stringify({ready: false, errors: errors, stats: null}));
  });
}

if (typeof window !== 'undefined' && typeof document !== 'undefined' && document.documentElement &&
    document.documentElement.getAttribute('data-harness') === 'patchview') {
  bootPatchviewHarness(window);
}
