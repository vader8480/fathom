// Floor plan view: plan image + device markers, drag to place, calibrate,
// measure, pan / zoom / pinch, layer toggles, upload. mount(el, ctx) (§6.4, §6.7).
import {
  findPlan, planSize, imageToNorm, normToImage, metersPerPx, distance, formatLength,
  markerOf, markerOps, removeMarkerOps, calibrateOps, unplacedDevices, roomDevices, nudge,
  plansForRoom, newPlanOps, renamePlanOps, deletePlanOps, reorderPlanOps, toggleLayerOps, layerVisible,
  fitView, zoomAt, panBy, pinchView, screenToWorld,
} from './floorplan-core.js';

// Sample renders offered by the plan picker in harness mode (ctx.api === null).
export const DEV_PLANS = [
  {file: 'plans/main-floor.svg', name: 'Main floor', kind: 'svg', source: 'dxf', mime: 'image/svg+xml', width: 2080, height: 1546.67,
    layers: [{name: 'WALLS', visible: true, count: 3}, {name: 'STAGE', visible: true, count: 3}, {name: 'SEATS', visible: true, count: 320},
      {name: 'AV', visible: true, count: 17}, {name: 'DOORS', visible: true, count: 5}, {name: 'TEXT', visible: true}, {name: 'GRID', visible: true}, {name: 'HIDDEN', visible: false}]},
  {file: 'plans/dxf-fixture.svg', name: 'DXF fixture (20 x 15 m)', kind: 'svg', source: 'dxf', mime: 'image/svg+xml', width: 2080, height: 1580,
    layers: [{name: 'WALLS', visible: true, count: 6}, {name: 'SEATS', visible: true, count: 2}, {name: 'HIDDEN', visible: false, count: 1}]},
  {file: 'plans/stage.svg', name: 'Stage', kind: 'svg', source: 'drawio', mime: 'image/svg+xml', width: 960, height: 510},
  {file: 'plans/lobby.svg', name: 'Lobby', kind: 'svg', source: 'svg', mime: 'image/svg+xml', width: 1200, height: 700},
  {file: 'plans/chapel.png', name: 'Chapel', kind: 'png', source: 'png', mime: 'image/png', width: 1000, height: 700},
  {file: 'plans/rcp.png', name: 'RCP (from PDF)', kind: 'png', source: 'pdf', mime: 'image/png', width: 1650, height: 1275},
];

const ACCEPT = '.png,.jpg,.jpeg,.svg,.pdf,.drawio,.xml,.dxf,.dwg';
const DRAG_SLOP = 5;

function h(tag, attrs, children) {
  const n = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (v == null || v === false) return;
      if (k === 'text') n.textContent = v;
      else if (k === 'class') n.className = v;
      else if (k === 'style') n.setAttribute('style', v);
      else n.setAttribute(k, v === true ? '' : v);
    });
  }
  (children || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
  return n;
}

function svgEl(tag, attrs) {
  const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
  return n;
}

function disciplineOf(dev, vocab) {
  if (dev.discipline) return dev.discipline;
  const k = vocab && vocab.kinds && vocab.kinds[dev.kind];
  return (k && k.discipline) || 'other';
}

function discColor(disc, vocab) {
  const d = vocab && vocab.disciplines && vocab.disciplines[disc];
  return (d && d.color) || '#9aa3b5';
}

function deviceById(doc, id) {
  const ds = (doc && doc.devices) || [];
  for (let i = 0; i < ds.length; i++) if (ds[i].id === id) return ds[i];
  return null;
}

export function mount(el, ctx) {
  const store = ctx.store;
  const vocab = ctx.vocab || store.vocab || {};
  const S = {
    fpId: null, view: {x: 0, y: 0, k: 1}, fitted: {}, tool: '', points: [], measure: null,
    sel: null, pointers: {}, gesture: null, natural: {}, imgUrl: '', highlight: null, popFor: null,
  };
  const listeners = [];
  function on(target, type, fn, opts) {
    target.addEventListener(type, fn, opts);
    listeners.push([target, type, fn, opts]);
  }

  // ------------------------------------------------------------------ DOM
  el.innerHTML = '';
  const root = h('div', {class: 'fp-root'});
  const select = h('select', {id: 'fp-select', 'aria-label': 'Floor plan'});
  const btnUp = h('button', {type: 'button', class: 'fp-btn', 'aria-label': 'Move plan earlier', title: 'Move plan earlier', text: '\u2039'});
  const btnDown = h('button', {type: 'button', class: 'fp-btn', 'aria-label': 'Move plan later', title: 'Move plan later', text: '\u203a'});
  const btnRename = h('button', {type: 'button', class: 'fp-btn', text: 'Rename'});
  const btnDelete = h('button', {type: 'button', class: 'fp-btn fp-danger', text: 'Delete'});
  const upload = h('input', {id: 'fp-upload', type: 'file', accept: ACCEPT, class: 'fp-file'});
  const uploadLabel = h('label', {for: 'fp-upload', class: 'fp-btn fp-upload-btn', text: 'Upload plan\u2026'});
  const devSelect = h('select', {id: 'fp-dev-plan', 'aria-label': 'Sample plan'});
  const devAdd = h('button', {type: 'button', class: 'fp-btn', text: 'Add plan'});
  const btnCal = h('button', {id: 'fp-calibrate', type: 'button', class: 'fp-btn', 'aria-pressed': 'false', text: 'Calibrate'});
  const btnMeasure = h('button', {id: 'fp-measure', type: 'button', class: 'fp-btn', 'aria-pressed': 'false', text: 'Measure'});
  const btnLayers = h('button', {id: 'fp-layers', type: 'button', class: 'fp-btn', 'aria-expanded': 'false', 'aria-haspopup': 'true', text: 'Layers'});
  const layersPop = h('div', {class: 'fp-pop fp-layers-pop', role: 'group', 'aria-label': 'Layers', hidden: true});
  const btnZoomOut = h('button', {id: 'fp-zoom-out', type: 'button', class: 'fp-btn fp-icon', 'aria-label': 'Zoom out', text: '\u2212'});
  const btnZoomIn = h('button', {id: 'fp-zoom-in', type: 'button', class: 'fp-btn fp-icon', 'aria-label': 'Zoom in', text: '+'});
  const btnFit = h('button', {id: 'fp-fit', type: 'button', class: 'fp-btn', 'aria-label': 'Fit plan to view', text: 'Fit'});
  const readout = h('span', {class: 'fp-readout', role: 'status'});
  const devGroup = h('span', {class: 'fp-group fp-devplans'}, [devSelect, devAdd]);
  const toolbar = h('div', {class: 'fp-toolbar', role: 'toolbar', 'aria-label': 'Floor plan tools'}, [
    h('span', {class: 'fp-group'}, [select, btnUp, btnDown, btnRename, btnDelete]),
    h('span', {class: 'fp-group'}, [upload, uploadLabel]),
    devGroup,
    h('span', {class: 'fp-group'}, [btnCal, btnMeasure, h('span', {class: 'fp-layers-wrap'}, [btnLayers, layersPop])]),
    h('span', {class: 'fp-group'}, [btnZoomOut, btnZoomIn, btnFit]),
    readout,
  ]);
  const devList = h('ul', {id: 'fp-unplaced', class: 'fp-devlist', 'aria-label': 'Room devices'});
  const side = h('aside', {class: 'fp-side'}, [
    h('h3', {text: 'Devices'}),
    h('p', {class: 'fp-hint', text: 'Drag a device by its grip onto the plan, or press it to drop it in the middle.'}),
    devList,
  ]);
  const img = h('img', {class: 'fp-img', alt: '', draggable: 'false'});
  const overlay = svgEl('svg', {class: 'fp-overlay'});
  const markersEl = h('div', {class: 'fp-markers'});
  const world = h('div', {class: 'fp-world'}, [img, overlay, markersEl]);
  const empty = h('div', {class: 'fp-empty', hidden: true});
  const crosshair = h('div', {class: 'fp-crosshair', 'aria-hidden': 'true', hidden: true});
  const calForm = h('form', {class: 'fp-pop fp-calform', hidden: true, 'aria-label': 'Calibration distance'});
  const calInput = h('input', {id: 'fp-cal-distance', type: 'number', inputmode: 'decimal', min: '0', step: 'any', required: true});
  const calUnit = h('select', {id: 'fp-cal-unit', 'aria-label': 'Unit'}, [h('option', {value: 'm', text: 'm'}), h('option', {value: 'ft', text: 'ft'})]);
  calForm.appendChild(h('label', {for: 'fp-cal-distance', text: 'Real distance'}));
  calForm.appendChild(calInput);
  calForm.appendChild(calUnit);
  calForm.appendChild(h('button', {type: 'submit', class: 'fp-btn fp-primary', text: 'Apply'}));
  const calCancel = h('button', {type: 'button', class: 'fp-btn', text: 'Cancel'});
  calForm.appendChild(calCancel);
  const pop = h('div', {class: 'fp-pop fp-markerpop', hidden: true, role: 'dialog', 'aria-label': 'Marker'});
  const delPop = h('div', {class: 'fp-pop fp-delpop', hidden: true, role: 'dialog', 'aria-labelledby': 'fp-del-title'});
  const viewport = h('div', {class: 'fp-viewport', role: 'application', tabindex: '0',
    'aria-label': 'Floor plan. Arrow keys pan, plus and minus zoom, F fits. With a marker focused, arrows move it, Delete removes it, Enter opens it.'},
  [world, empty, crosshair, calForm, pop]);
  const ghost = h('div', {class: 'fp-ghost', hidden: true, 'aria-hidden': 'true'});
  root.appendChild(toolbar);
  root.appendChild(h('div', {class: 'fp-body'}, [side, viewport]));
  root.appendChild(ghost);
  root.appendChild(delPop);
  el.appendChild(root);

  const harness = !ctx.api;
  devGroup.hidden = !harness;
  (ctx.devPlans || DEV_PLANS).forEach(function (p, i) { devSelect.appendChild(h('option', {value: String(i), text: p.name})); });

  // -------------------------------------------------------------- state
  function doc() { return store.doc; }
  function readOnly() { return !!store.readOnly; }
  function room() { return store.room || (doc().settings && doc().settings.default_room) || ''; }
  function units() { return (doc().settings && doc().settings.units) || 'metric'; }
  function plan() {
    const fp = S.fpId ? findPlan(doc(), S.fpId) : null;
    const nat = fp && S.natural[fp.id];
    if (fp && nat && !(fp.image && Number(fp.image.width) > 0)) return Object.assign({}, fp, {image: Object.assign({}, fp.image, nat)});
    return fp;
  }
  function plans() { return plansForRoom(doc(), room() === '*' || room() === '' ? '*' : room()); }

  function commit(ops, label) {
    if (!ops || !ops.length) return;
    if (readOnly()) { ctx.toast('Read-only: changes are not allowed here.', 'warn'); return; }
    ctx.commit(ops, label);
  }

  function ensurePlan() {
    const ps = plans();
    if (!S.fpId || !ps.some(function (p) { return p.id === S.fpId; })) S.fpId = ps.length ? ps[0].id : null;
  }

  function hiddenLayers(fp) {
    return (fp.layers || []).filter(function (l) { return !layerVisible(fp, l); }).map(function (l) { return l.name; });
  }

  function imageUrl(fp) {
    if (ctx.planImageUrl) return ctx.planImageUrl(fp);
    const hide = hiddenLayers(fp);
    if (ctx.api && ctx.api.floorplanImageUrl) return ctx.api.floorplanImageUrl(ctx.project, fp.id, hide.length ? hide : undefined);
    const att = (doc().attachments || []).filter(function (a) { return a.id === (fp.image && fp.image.attachment); })[0];
    return att ? att.file : '';
  }

  // ------------------------------------------------------------- render
  function render() {
    ensurePlan();
    const fp = plan();
    const ro = readOnly();
    root.classList.toggle('fp-readonly', ro);
    // plan select
    select.innerHTML = '';
    const ps = plans();
    ps.forEach(function (p) { select.appendChild(h('option', {value: p.id, text: p.name, selected: p.id === S.fpId})); });
    if (!ps.length) select.appendChild(h('option', {value: '', text: 'No plans in this room'}));
    select.disabled = !ps.length;
    const idx = fp ? ps.map(function (p) { return p.id; }).indexOf(fp.id) : -1;
    btnUp.disabled = ro || idx <= 0;
    btnDown.disabled = ro || idx < 0 || idx >= ps.length - 1;
    btnRename.disabled = ro || !fp;
    btnDelete.disabled = ro || !fp;
    upload.disabled = ro;
    uploadLabel.classList.toggle('fp-disabled', ro);
    devAdd.disabled = ro;
    btnCal.disabled = ro || !fp;
    btnMeasure.disabled = !fp;
    btnLayers.disabled = !fp || !(fp.layers && fp.layers.length);
    btnZoomIn.disabled = btnZoomOut.disabled = btnFit.disabled = !fp;
    // image
    empty.hidden = !!fp;
    world.hidden = !fp;
    if (!fp) {
      empty.textContent = harness ? 'No floor plan in this room yet. Pick a sample plan and press "Add plan".'
        : 'No floor plan in this room yet. Upload a PNG, JPG, SVG, PDF, Draw.io or DXF file.';
      img.removeAttribute('src');
      S.imgUrl = '';
    } else {
      const sz = planSize(fp);
      img.style.width = sz.w + 'px';
      img.style.height = sz.h + 'px';
      overlay.setAttribute('width', sz.w);
      overlay.setAttribute('height', sz.h);
      overlay.setAttribute('viewBox', '0 0 ' + sz.w + ' ' + sz.h);
      markersEl.style.width = sz.w + 'px';
      markersEl.style.height = sz.h + 'px';
      img.alt = 'Floor plan: ' + fp.name;
      img.classList.toggle('fp-img-dark', !!(fp.source && fp.source.kind === 'dxf'));
      const url = imageUrl(fp);
      if (url !== S.imgUrl) { S.imgUrl = url; img.src = url; }
      if (!S.fitted[fp.id]) { fit(); S.fitted[fp.id] = true; }
    }
    renderMarkers();
    renderDevList();
    renderLayers();
    renderOverlay();
    renderTool();
    applyView();
  }

  function renderMarkers() {
    markersEl.innerHTML = '';
    const fp = plan();
    if (!fp) return;
    const hl = S.highlight && S.highlight.devices && S.highlight.devices.length ? S.highlight.devices : null;
    (fp.markers || []).forEach(function (m) {
      const dev = deviceById(doc(), m.device);
      const name = dev ? dev.name : m.device;
      const pos = normToImage(fp, m);
      const dot = h('span', {class: 'fp-dot', style: 'background:' + (dev ? discColor(disciplineOf(dev, vocab), vocab) : '#9aa3b5')});
      const label = h('span', {class: 'fp-mlabel', text: (m.label || name) + (dev && dev.count > 1 ? ' \u00d7' + dev.count : '')});
      const inner = h('span', {class: 'fp-marker-in'}, [dot, label]);
      const mk = h('div', {
        class: 'fp-marker' + (S.sel === m.device ? ' fp-selected' : '') + (hl ? (hl.indexOf(m.device) >= 0 ? ' fp-hl' : ' fp-dim') : '')
          + (dev && dev.status === 'planned' ? ' fp-planned' : '') + (dev ? '' : ' fp-missing'),
        'data-device': m.device, role: 'button', tabindex: '0',
        'aria-label': name + ' marker' + (readOnly() ? '' : '. Arrow keys move, Delete removes, Enter opens'),
        'aria-pressed': S.sel === m.device ? 'true' : 'false',
        style: 'left:' + pos.x + 'px;top:' + pos.y + 'px',
      }, [inner]);
      markersEl.appendChild(mk);
    });
  }

  function renderDevList() {
    devList.innerHTML = '';
    const fp = plan();
    if (!fp) { devList.appendChild(h('li', {class: 'fp-hint', text: 'Add a plan first.'})); return; }
    const unplaced = unplacedDevices(doc(), fp.id);
    const placed = roomDevices(doc(), fp.room).filter(function (d) { return markerOf(fp, d.id); });
    if (!unplaced.length && !placed.length) devList.appendChild(h('li', {class: 'fp-hint', text: 'No devices in this room.'}));
    unplaced.concat(placed).forEach(function (d) {
      const isPlaced = !!markerOf(fp, d.id);
      const grip = h('span', {class: 'fp-grip', 'data-device': d.id, 'aria-hidden': 'true', title: 'Drag onto the plan', text: '\u283f'});
      const btn = h('button', {
        type: 'button', class: 'fp-dev' + (isPlaced ? ' fp-placed' : ''), 'data-device': d.id,
        'aria-label': (isPlaced ? 'Show ' : 'Place ') + d.name + (isPlaced ? ' on the plan' : ' in the middle of the plan'),
        disabled: !isPlaced && readOnly(),
      }, [
        h('span', {class: 'fp-dot', style: 'background:' + discColor(disciplineOf(d, vocab), vocab)}),
        h('span', {class: 'fp-devname', text: d.name}),
        h('span', {class: 'fp-devstate', text: isPlaced ? 'placed' : ''}),
      ]);
      devList.appendChild(h('li', {class: 'fp-devitem'}, [readOnly() ? null : grip, btn]));
    });
  }

  function renderLayers() {
    layersPop.innerHTML = '';
    const fp = plan();
    if (!fp || !fp.layers || !fp.layers.length) { layersPop.hidden = true; btnLayers.setAttribute('aria-expanded', 'false'); return; }
    fp.layers.forEach(function (l, i) {
      const id = 'fp-layer-' + i;
      const cb = h('input', {type: 'checkbox', id: id, 'data-layer': l.name, checked: layerVisible(fp, l), disabled: readOnly()});
      layersPop.appendChild(h('div', {class: 'fp-layer'}, [cb, h('label', {for: id, text: l.name + (l.count != null ? ' (' + l.count + ')' : '')})]));
    });
    if (harness) layersPop.appendChild(h('p', {class: 'fp-hint', text: 'Harness: layer rendering needs the server.'}));
  }

  function renderOverlay() {
    while (overlay.firstChild) overlay.removeChild(overlay.firstChild);
    const fp = plan();
    if (!fp) return;
    const k = S.view.k || 1;
    function line(a, b, cls) {
      const pa = normToImage(fp, a);
      const pb = normToImage(fp, b);
      overlay.appendChild(svgEl('line', {x1: pa.x, y1: pa.y, x2: pb.x, y2: pb.y, class: cls}));
    }
    function dot(a, cls) {
      const p = normToImage(fp, a);
      overlay.appendChild(svgEl('circle', {cx: p.x, cy: p.y, r: 6 / k, class: cls}));
    }
    if (S.tool === 'calibrate' && fp.calibration && S.points.length === 0) {
      const c = fp.calibration;
      line({x: c.p1[0], y: c.p1[1]}, {x: c.p2[0], y: c.p2[1]}, 'fp-calline fp-old');
    }
    if (S.tool) {
      const cls = S.tool === 'calibrate' ? 'fp-calline' : 'fp-mline';
      S.points.forEach(function (p) { dot(p, cls + '-pt'); });
      if (S.points.length === 2) line(S.points[0], S.points[1], cls);
      if (S.tool === 'measure' && S.measure && S.points.length === 2) {
        const pa = normToImage(fp, S.points[0]);
        const pb = normToImage(fp, S.points[1]);
        const t = svgEl('text', {x: (pa.x + pb.x) / 2, y: (pa.y + pb.y) / 2 - 10 / k, class: 'fp-mtext', 'font-size': 14 / k});
        t.textContent = S.measure;
        overlay.appendChild(t);
      }
    }
  }

  function renderTool() {
    btnCal.setAttribute('aria-pressed', S.tool === 'calibrate' ? 'true' : 'false');
    btnMeasure.setAttribute('aria-pressed', S.tool === 'measure' ? 'true' : 'false');
    viewport.classList.toggle('fp-tool', !!S.tool);
    crosshair.hidden = !S.tool;
    calForm.hidden = !(S.tool === 'calibrate' && S.points.length === 2);
    const fp = plan();
    let txt = '';
    if (S.tool === 'calibrate') {
      txt = S.points.length < 2 ? 'Calibrate: pick point ' + (S.points.length + 1) + ' of 2 (click/tap, or Enter at the crosshair)'
        : 'Enter the real distance between the two points';
    } else if (S.tool === 'measure') {
      txt = S.measure ? 'Distance: ' + S.measure : 'Measure: pick point ' + (S.points.length + 1) + ' of 2';
      if (fp && metersPerPx(fp) == null) txt += ' \u00b7 plan not calibrated';
    } else if (fp) {
      txt = metersPerPx(fp) == null ? 'Not calibrated' : 'Calibrated \u00b7 ' + Math.round(S.view.k * 100) + '%';
    }
    readout.textContent = txt;
  }

  function applyView() {
    const v = S.view;
    world.style.transform = 'translate3d(' + v.x + 'px,' + v.y + 'px,0) scale(' + v.k + ')';
    world.style.setProperty('--fp-inv', String(1 / v.k));
  }

  function setView(v, redrawOverlay) {
    S.view = v;
    applyView();
    if (redrawOverlay && S.tool) renderOverlay();
  }

  function vpSize() {
    const r = viewport.getBoundingClientRect();
    return {w: r.width || 800, h: r.height || 600, left: r.left, top: r.top};
  }

  function fit() {
    const fp = plan();
    if (!fp) return;
    const sz = planSize(fp);
    const vs = vpSize();
    setView(fitView(sz.w, sz.h, vs.w, vs.h, 16), true);
    renderTool();
  }

  function zoomBy(f, pt) {
    const vs = vpSize();
    setView(zoomAt(S.view, pt || {x: vs.w / 2, y: vs.h / 2}, f), true);
    renderTool();
  }

  function localPt(e) {
    const vs = vpSize();
    return {x: e.clientX - vs.left, y: e.clientY - vs.top};
  }

  function normAtScreen(pt) {
    const fp = plan();
    return imageToNorm(fp, screenToWorld(S.view, pt));
  }

  function centerNorm() {
    const vs = vpSize();
    const n = normAtScreen({x: vs.w / 2, y: vs.h / 2});
    return {x: Math.max(0, Math.min(1, n.x)), y: Math.max(0, Math.min(1, n.y))};
  }

  // ---------------------------------------------------------- selection
  function selectDevice(id, openPop) {
    S.sel = id;
    ctx.select(id ? {type: 'device', id: id} : null);
    renderMarkers();
    if (openPop && id) showPop(id); else hidePop();
  }

  function showPop(id) {
    const fp = plan();
    const dev = deviceById(doc(), id);
    if (!fp || !markerOf(fp, id)) return;
    pop.innerHTML = '';
    pop.appendChild(h('strong', {text: dev ? dev.name : id}));
    if (dev && (dev.manufacturer || dev.model)) pop.appendChild(h('div', {class: 'fp-hint', text: ((dev.manufacturer || '') + ' ' + (dev.model || '')).trim()}));
    const row = h('div', {class: 'fp-poprow'});
    const details = h('button', {type: 'button', class: 'fp-btn', 'data-act': 'details', text: 'Details'});
    row.appendChild(details);
    row.appendChild(h('a', {class: 'fp-btn', href: 'p/' + encodeURIComponent(ctx.project || '') + '/d/' + encodeURIComponent(id), target: '_blank', rel: 'noopener', text: 'Open device page'}));
    if (!readOnly()) row.appendChild(h('button', {type: 'button', class: 'fp-btn fp-danger', 'data-act': 'remove', text: 'Remove from plan'}));
    row.appendChild(h('button', {type: 'button', class: 'fp-btn fp-icon', 'data-act': 'close', 'aria-label': 'Close', text: '\u00d7'}));
    pop.appendChild(row);
    S.popFor = id;
    pop.hidden = false;
    positionPop();
  }

  function positionPop() {
    if (pop.hidden || !S.popFor) return;
    const fp = plan();
    const m = fp && markerOf(fp, S.popFor);
    if (!m) { hidePop(); return; }
    const p = normToImage(fp, m);
    const vs = vpSize();
    const x = Math.max(8, Math.min(vs.w - 260, p.x * S.view.k + S.view.x + 14));
    const y = Math.max(8, Math.min(vs.h - 110, p.y * S.view.k + S.view.y + 14));
    pop.style.left = x + 'px';
    pop.style.top = y + 'px';
  }

  function hidePop() { pop.hidden = true; S.popFor = null; }

  // ------------------------------------------------------------ tools
  function setTool(t) {
    S.tool = S.tool === t ? '' : t;
    S.points = [];
    S.measure = null;
    if (S.tool === 'calibrate') {
      const fp = plan();
      calUnit.value = fp && fp.calibration && fp.calibration.unit ? fp.calibration.unit : (units() === 'imperial' ? 'ft' : 'm');
      calInput.value = fp && fp.calibration ? String(fp.calibration.distance) : '';
    }
    renderOverlay();
    renderTool();
    viewport.focus();
  }

  function addPoint(n) {
    const fp = plan();
    if (!fp || !S.tool) return;
    if (S.points.length >= 2) { S.points = []; S.measure = null; }
    S.points.push({x: n.x, y: n.y});
    if (S.tool === 'measure' && S.points.length === 2) {
      const d = distance(fp, S.points[0], S.points[1], units());
      let txt = d.text;
      if (d.meters != null) txt += ' (' + formatLength(d.meters, units() === 'imperial' ? 'metric' : 'imperial') + ')';
      S.measure = txt;
      announce('Distance ' + txt);
    }
    renderOverlay();
    renderTool();
    if (S.tool === 'calibrate' && S.points.length === 2) { calInput.focus(); calInput.select(); }
  }

  function announce(msg) {
    const live = document.getElementById('fathom-live');
    if (live) live.textContent = msg;
  }

  // ------------------------------------------------------ pointer input
  function pointerList() { return Object.keys(S.pointers).map(function (k) { return S.pointers[k]; }); }

  function capture(target, id) { try { target.setPointerCapture(id); } catch (err) { /* synthetic or lost pointer */ } }

  function onDown(e) {
    if (e.button != null && e.button > 0 && e.pointerType === 'mouse') return;
    if (e.target.closest('.fp-pop')) return;
    const pt = localPt(e);
    S.pointers[e.pointerId] = {id: e.pointerId, x: pt.x, y: pt.y};
    const ps = pointerList();
    if (ps.length === 2) {
      cancelMarkerDrag();
      S.gesture = {type: 'pinch', a: {x: ps[0].x, y: ps[0].y}, b: {x: ps[1].x, y: ps[1].y}, view: S.view, ids: [ps[0].id, ps[1].id]};
      capture(viewport, e.pointerId);
      return;
    }
    if (ps.length > 2) return;
    const mk = e.target.closest('.fp-marker');
    capture(viewport, e.pointerId);
    if (mk && !S.tool) {
      const id = mk.getAttribute('data-device');
      S.gesture = {type: 'marker', id: id, el: mk, start: pt, moved: false, pointer: e.pointerId};
      e.preventDefault();
      return;
    }
    S.gesture = {type: 'pan', start: pt, view: S.view, moved: false, pointer: e.pointerId};
  }

  function onMove(e) {
    if (!S.pointers[e.pointerId]) return;
    const pt = localPt(e);
    S.pointers[e.pointerId].x = pt.x;
    S.pointers[e.pointerId].y = pt.y;
    const g = S.gesture;
    if (!g) return;
    if (g.type === 'pinch') {
      const a = S.pointers[g.ids[0]];
      const b = S.pointers[g.ids[1]];
      if (a && b) { setView(pinchView(g, a, b), false); positionPop(); }
      return;
    }
    if (g.pointer !== e.pointerId) return;
    const dx = pt.x - g.start.x;
    const dy = pt.y - g.start.y;
    if (!g.moved && Math.hypot(dx, dy) < DRAG_SLOP) return;
    g.moved = true;
    if (g.type === 'pan') {
      setView(panBy(g.view, dx, dy), false);
      positionPop();
    } else if (g.type === 'marker') {
      if (readOnly()) return;
      const fp = plan();
      const n = normAtScreen(pt);
      const p = normToImage(fp, {x: Math.max(0, Math.min(1, n.x)), y: Math.max(0, Math.min(1, n.y))});
      g.el.style.left = p.x + 'px';
      g.el.style.top = p.y + 'px';
      g.el.classList.add('fp-dragging');
      g.last = n;
      hidePop();
    }
  }

  function onUp(e) {
    if (!S.pointers[e.pointerId]) return;
    const pt = localPt(e);
    delete S.pointers[e.pointerId];
    const g = S.gesture;
    if (!g) return;
    if (g.type === 'pinch') {
      if (g.ids.indexOf(e.pointerId) >= 0) { S.gesture = null; renderOverlay(); renderTool(); }
      return;
    }
    if (g.pointer !== e.pointerId) return;
    S.gesture = null;
    if (g.type === 'marker') {
      if (g.moved && g.last && !readOnly()) {
        const dev = deviceById(doc(), g.id);
        commit(markerOps(doc(), S.fpId, g.id, g.last), 'Moved ' + (dev ? dev.name : g.id) + ' on ' + plan().name);
      } else {
        g.el.classList.remove('fp-dragging');
        selectDevice(g.id, true);
        g.el.focus();
      }
    } else if (g.type === 'pan') {
      if (!g.moved) {
        if (S.tool) addPoint(normAtScreen(pt));
        else { selectDevice(null, false); }
      } else { renderOverlay(); }
    }
  }

  function cancelMarkerDrag() {
    const g = S.gesture;
    if (g && g.type === 'marker' && g.moved) renderMarkers();
    S.gesture = null;
  }

  function onCancel(e) {
    delete S.pointers[e.pointerId];
    cancelMarkerDrag();
  }

  function onWheel(e) {
    if (!plan()) return;
    e.preventDefault();
    const pt = localPt(e);
    if (e.ctrlKey || e.metaKey) zoomBy(Math.exp(-e.deltaY * 0.01), pt);
    else { setView(panBy(S.view, -e.deltaX, -e.deltaY), false); positionPop(); }
  }

  function prevent(e) { e.preventDefault(); }
  function onTouchMove(e) { if (e.touches.length >= 2 || S.gesture) e.preventDefault(); }

  // ------------------------------------------------- side list dragging
  let listDrag = null;
  let suppressClick = false;

  function onListDown(e) {
    const grip = e.target.closest('.fp-grip');
    if (!grip || readOnly() || !plan()) return;
    e.preventDefault();
    listDrag = {id: grip.getAttribute('data-device'), x: e.clientX, y: e.clientY, pointer: e.pointerId, moved: false, src: grip};
    capture(grip, e.pointerId);
  }

  function onListMove(e) {
    if (!listDrag || listDrag.pointer !== e.pointerId) return;
    if (!listDrag.moved && Math.hypot(e.clientX - listDrag.x, e.clientY - listDrag.y) < DRAG_SLOP) return;
    listDrag.moved = true;
    const dev = deviceById(doc(), listDrag.id);
    ghost.textContent = dev ? dev.name : listDrag.id;
    ghost.hidden = false;
    const rr = root.getBoundingClientRect();
    ghost.style.left = (e.clientX - rr.left + 8) + 'px';
    ghost.style.top = (e.clientY - rr.top + 8) + 'px';
    const vs = vpSize();
    const inside = e.clientX >= vs.left && e.clientX <= vs.left + vs.w && e.clientY >= vs.top && e.clientY <= vs.top + vs.h;
    viewport.classList.toggle('fp-droptarget', inside);
    ghost.classList.toggle('fp-ok', inside);
  }

  function onListUp(e) {
    if (!listDrag || listDrag.pointer !== e.pointerId) return;
    const d = listDrag;
    listDrag = null;
    ghost.hidden = true;
    viewport.classList.remove('fp-droptarget');
    if (!d.moved) return;
    suppressClick = true;
    setTimeout(function () { suppressClick = false; }, 0);
    const vs = vpSize();
    const inside = e.clientX >= vs.left && e.clientX <= vs.left + vs.w && e.clientY >= vs.top && e.clientY <= vs.top + vs.h;
    if (!inside) return;
    placeDevice(d.id, normAtScreen({x: e.clientX - vs.left, y: e.clientY - vs.top}));
  }

  function onListCancel() {
    listDrag = null;
    ghost.hidden = true;
    viewport.classList.remove('fp-droptarget');
  }

  function placeDevice(id, n) {
    const fp = plan();
    if (!fp) return;
    const dev = deviceById(doc(), id);
    const had = !!markerOf(fp, id);
    commit(markerOps(doc(), fp.id, id, n), (had ? 'Moved ' : 'Placed ') + (dev ? dev.name : id) + ' on ' + fp.name);
    S.sel = id;
    renderMarkers();
  }

  function onListClick(e) {
    const btn = e.target.closest('.fp-dev');
    if (!btn || suppressClick) return;
    const id = btn.getAttribute('data-device');
    const fp = plan();
    if (!fp) return;
    const m = markerOf(fp, id);
    if (m) {
      const p = normToImage(fp, m);
      const vs = vpSize();
      setView({x: vs.w / 2 - p.x * S.view.k, y: vs.h / 2 - p.y * S.view.k, k: S.view.k}, true);
      selectDevice(id, true);
      const mk = markersEl.querySelector('.fp-marker[data-device="' + cssEscape(id) + '"]');
      if (mk) mk.focus();
      return;
    }
    placeDevice(id, centerNorm());
    const mk2 = markersEl.querySelector('.fp-marker[data-device="' + cssEscape(id) + '"]');
    if (mk2) mk2.focus();
  }

  function cssEscape(s) { return String(s).replace(/["\\]/g, '\\$&'); }

  // ----------------------------------------------------------- keyboard
  function onKey(e) {
    if (e.target.closest('input,select,textarea,form,.fp-pop')) {
      if (e.key === 'Escape') { if (S.tool) setTool(S.tool); hidePop(); viewport.focus(); }
      return;
    }
    const fp = plan();
    if (!fp) return;
    const mk = e.target.closest('.fp-marker');
    const step = e.shiftKey ? 0.025 : 0.005;
    const dirs = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]};
    if (mk) {
      const id = mk.getAttribute('data-device');
      const m = markerOf(fp, id);
      if (dirs[e.key] && m && !readOnly()) {
        e.preventDefault();
        const dev = deviceById(doc(), id);
        commit(markerOps(doc(), fp.id, id, nudge(m, dirs[e.key][0] * step, dirs[e.key][1] * step)), 'Moved ' + (dev ? dev.name : id) + ' on ' + fp.name);
        refocusMarker(id);
        return;
      }
      if ((e.key === 'Delete' || e.key === 'Backspace') && !readOnly()) {
        e.preventDefault();
        removeMarker(id);
        return;
      }
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        selectDevice(id, true);
        if (ctx.openInspector) ctx.openInspector({type: 'device', id: id});
        return;
      }
      if (e.key === 'Escape') { e.preventDefault(); selectDevice(null, false); viewport.focus(); return; }
    }
    if (dirs[e.key]) {
      e.preventDefault();
      setView(panBy(S.view, -dirs[e.key][0] * 40, -dirs[e.key][1] * 40), false);
      positionPop();
      return;
    }
    if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomBy(1.25); return; }
    if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomBy(0.8); return; }
    if (e.key === '0' || e.key === 'f' || e.key === 'F') { e.preventDefault(); fit(); return; }
    if (e.key === 'Enter' && S.tool) { e.preventDefault(); addPoint(centerNorm()); return; }
    if (e.key === 'Escape') {
      e.preventDefault();
      if (S.tool) setTool(S.tool); else selectDevice(null, false);
    }
  }

  function refocusMarker(id) {
    const mk = markersEl.querySelector('.fp-marker[data-device="' + cssEscape(id) + '"]');
    if (mk) mk.focus();
  }

  function removeMarker(id) {
    const fp = plan();
    const dev = deviceById(doc(), id);
    hidePop();
    commit(removeMarkerOps(doc(), fp.id, id), 'Removed ' + (dev ? dev.name : id) + ' from ' + fp.name);
    viewport.focus();
  }

  // ---------------------------------------------------------- toolbar
  function onSelect() {
    S.fpId = select.value || null;
    S.tool = '';
    S.points = [];
    hidePop();
    render();
  }

  function onRename() {
    const fp = plan();
    if (!fp || readOnly()) return;
    const input = h('input', {type: 'text', class: 'fp-rename', value: fp.name, 'aria-label': 'Plan name'});
    select.parentNode.replaceChild(input, select);
    input.focus();
    input.select();
    let done = false;
    function finish(save) {
      if (done) return;
      done = true;
      input.parentNode.replaceChild(select, input);
      if (save) commit(renamePlanOps(doc(), fp.id, input.value), 'Renamed plan to ' + input.value.trim());
      render();
      select.focus();
    }
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); finish(true); }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(false); }
    });
    input.addEventListener('blur', function () { finish(true); });
  }

  function planAttachments(fp) {
    const ids = [];
    [fp.image && fp.image.attachment, fp.source && fp.source.attachment].forEach(function (a) { if (a && ids.indexOf(a) < 0) ids.push(a); });
    const atts = doc().attachments || [];
    return ids.filter(function (a) { return atts.some(function (x) { return x.id === a; }); });
  }

  function onDelete() {
    const fp = plan();
    if (!fp || readOnly()) return;
    const atts = planAttachments(fp);
    delPop.innerHTML = '';
    const title = h('p', {id: 'fp-del-title', class: 'fp-deltitle'}, [h('strong', {text: 'Delete floor plan "' + fp.name + '"?'}), ' Its markers go with it.']);
    const cb = h('input', {type: 'checkbox', id: 'fp-del-files', disabled: !atts.length});
    const lab = h('label', {for: 'fp-del-files', class: 'fp-check',
      text: atts.length ? 'Also delete the uploaded files (' + atts.length + ')' : 'No uploaded files to delete'});
    const yes = h('button', {type: 'button', class: 'fp-btn fp-danger', id: 'fp-del-confirm', text: 'Delete plan'});
    const no = h('button', {type: 'button', class: 'fp-btn', id: 'fp-del-cancel', text: 'Cancel'});
    delPop.appendChild(title);
    delPop.appendChild(h('div', {class: 'fp-checkrow'}, [cb, lab]));
    delPop.appendChild(h('p', {class: 'fp-hint', text: 'Unchecked keeps the files in the project.'}));
    delPop.appendChild(h('div', {class: 'fp-poprow'}, [yes, no]));
    delPop.hidden = false;
    no.focus();
    function close() { delPop.hidden = true; delPop.innerHTML = ''; btnDelete.focus(); }
    no.addEventListener('click', close);
    delPop.onkeydown = function (e) { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); } };
    yes.addEventListener('click', function () {
      const alsoFiles = cb.checked && atts.length > 0;
      delPop.hidden = true;
      delPop.innerHTML = '';
      commit(deletePlanOps(doc(), fp.id), 'Deleted plan ' + fp.name);
      S.fpId = null;
      render();
      btnDelete.focus();
      if (!alsoFiles) return;
      const still = atts.filter(function (a) {
        return !(doc().floorplans || []).some(function (p) { return planAttachments(p).indexOf(a) >= 0; });
      });
      if (!ctx.api || !ctx.api.deleteFile) {
        ctx.toast('Harness mode: the plan was removed; there are no server files to delete.', 'info');
        return;
      }
      deleteFilesAfterSave(still, fp.name);
    });
  }

  // The server refuses to delete an attachment a floor plan still uses (409 in_use),
  // so wait for the plan deletion to be saved, then delete, retrying while in_use.
  function deleteFilesAfterSave(ids, planName) {
    if (!ids.length) return;
    waitSaved(6000).then(function () {
      return Promise.all(ids.map(function (id) { return deleteWithRetry(id, 0); }));
    }).then(function (res) {
      const ok = res.filter(Boolean);
      if (ok.length && store.applyRemote) {
        store.applyRemote(ok.filter(function (id) { return (doc().attachments || []).some(function (a) { return a.id === id; }); })
          .map(function (id) { return {op: 'del', coll: 'attachments', id: id}; }), 'remote');
      }
      if (ok.length === ids.length) ctx.toast('Deleted ' + ok.length + ' file' + (ok.length === 1 ? '' : 's') + ' of ' + planName, 'ok');
      else ctx.toast('Deleted ' + ok.length + ' of ' + ids.length + ' files of ' + planName + '; the rest are kept.', 'warn');
    });
  }

  function waitSaved(timeoutMs) {
    return new Promise(function (resolve) {
      let done = false;
      const finish = function () {
        if (done) return;
        done = true;
        store.removeEventListener('revision', finish);
        store.removeEventListener('saving', onSaving);
        resolve();
      };
      const onSaving = function (e) { if (e.detail && e.detail.state === 'saved') finish(); };
      store.addEventListener('revision', finish);
      store.addEventListener('saving', onSaving);
      setTimeout(finish, timeoutMs);
    });
  }

  function deleteWithRetry(id, attempt) {
    return Promise.resolve(ctx.api.deleteFile(ctx.project, id)).then(function () { return id; }, function (err) {
      if (err && err.status === 409 && err.code === 'in_use' && attempt < 5) {
        return new Promise(function (r) { setTimeout(r, 800 * (attempt + 1)); }).then(function () { return deleteWithRetry(id, attempt + 1); });
      }
      if (err && err.status === 404) return id;
      ctx.toast('Could not delete file ' + id + ': ' + ((err && err.message) || 'error'), 'err');
      return null;
    });
  }

  function onUpload() {
    const files = Array.prototype.slice.call(upload.files || []);
    upload.value = '';
    if (!files.length) return;
    if (!ctx.api) { ctx.toast('Uploading needs the server. In the harness, pick a sample plan instead.', 'warn'); return; }
    const r = room() === '*' ? ((doc().settings && doc().settings.default_room) || '') : room();
    const name = files[0].name.replace(/\.(drawio\.xml|[a-z0-9]+)$/i, '');
    readout.textContent = 'Uploading ' + files[0].name + '\u2026';
    Promise.resolve(ctx.api.upload(ctx.project, 'floorplans', files, {room: r, name: name})).then(function (res) {
      const fpNew = res && res.floorplan;
      if (fpNew && !findPlan(doc(), fpNew.id) && store.applyRemote) {
        store.applyRemote([{op: 'put', coll: 'floorplans', id: fpNew.id, value: fpNew}], 'remote');
      }
      if (res && res.revision && store.setRevision && !(store.revision >= res.revision)) store.setRevision(res.revision);
      (res && res.warnings || []).forEach(function (w) { ctx.toast(w, 'warn'); });
      if (fpNew) { S.fpId = fpNew.id; ctx.toast('Added plan ' + fpNew.name, 'ok'); }
      render();
    }, function (err) {
      ctx.toast((err && err.message) || 'Upload failed', 'err');
      renderTool();
    });
  }

  function onDevAdd() {
    const spec = (ctx.devPlans || DEV_PLANS)[parseInt(devSelect.value, 10) || 0];
    if (!spec) return;
    const r = room() === '*' ? ((doc().settings && doc().settings.default_room) || '') : room();
    const res = newPlanOps(doc(), {room: r, name: spec.name, file: spec.file, mime: spec.mime,
      image: {kind: spec.kind, width: spec.width, height: spec.height}, layers: spec.layers,
      source: spec.source ? {attachment: '', kind: spec.source, page: 0} : null});
    commit(res.ops, 'Added plan ' + spec.name);
    S.fpId = res.id;
    render();
  }

  function onLayerChange(e) {
    const cb = e.target.closest('input[data-layer]');
    if (!cb) return;
    const name = cb.getAttribute('data-layer');
    commit(toggleLayerOps(doc(), S.fpId, name, cb.checked), (cb.checked ? 'Showed' : 'Hid') + ' layer ' + name);
  }

  function onPopClick(e) {
    const b = e.target.closest('[data-act]');
    if (!b || !S.popFor) return;
    const id = S.popFor;
    const act = b.getAttribute('data-act');
    if (act === 'details') { if (ctx.openInspector) ctx.openInspector({type: 'device', id: id}); }
    else if (act === 'remove') removeMarker(id);
    else if (act === 'close') { hidePop(); refocusMarker(id); }
  }

  function onCalSubmit(e) {
    e.preventDefault();
    const fp = plan();
    const d = parseFloat(calInput.value);
    if (!fp || S.points.length !== 2 || !(d > 0)) { calInput.focus(); return; }
    commit(calibrateOps(doc(), fp.id, S.points[0], S.points[1], d, calUnit.value), 'Calibrated ' + fp.name + ' (' + d + ' ' + calUnit.value + ')');
    S.tool = '';
    S.points = [];
    render();
    viewport.focus();
  }

  // ------------------------------------------------------- store events
  function onDoc() { render(); positionPop(); }
  function onSelection(e) {
    const sel = e.detail;
    const id = sel && (sel.type === 'device' || sel.type === 'marker') ? (sel.device || sel.id) : null;
    if (id !== S.sel) { S.sel = id; renderMarkers(); }
  }
  function onHighlight(e) { S.highlight = e.detail; renderMarkers(); }
  function onRoom() { S.fpId = null; S.tool = ''; hidePop(); render(); }

  on(select, 'change', onSelect);
  on(btnUp, 'click', function () { commit(reorderPlanOps(doc(), S.fpId, -1), 'Reordered plans'); });
  on(btnDown, 'click', function () { commit(reorderPlanOps(doc(), S.fpId, 1), 'Reordered plans'); });
  on(btnRename, 'click', onRename);
  on(btnDelete, 'click', onDelete);
  on(upload, 'change', onUpload);
  on(devAdd, 'click', onDevAdd);
  on(btnCal, 'click', function () { setTool('calibrate'); });
  on(btnMeasure, 'click', function () { setTool('measure'); });
  on(btnLayers, 'click', function () {
    layersPop.hidden = !layersPop.hidden;
    btnLayers.setAttribute('aria-expanded', layersPop.hidden ? 'false' : 'true');
    if (!layersPop.hidden) { const cb = layersPop.querySelector('input'); if (cb) cb.focus(); }
  });
  on(layersPop, 'change', onLayerChange);
  on(layersPop, 'keydown', function (e) { if (e.key === 'Escape') { layersPop.hidden = true; btnLayers.setAttribute('aria-expanded', 'false'); btnLayers.focus(); } });
  on(btnZoomIn, 'click', function () { zoomBy(1.25); });
  on(btnZoomOut, 'click', function () { zoomBy(0.8); });
  on(btnFit, 'click', fit);
  on(viewport, 'pointerdown', onDown);
  on(viewport, 'pointermove', onMove);
  on(viewport, 'pointerup', onUp);
  on(viewport, 'pointercancel', onCancel);
  on(viewport, 'lostpointercapture', function (e) { if (S.gesture && S.gesture.pointer === e.pointerId && S.pointers[e.pointerId]) onCancel(e); });
  on(viewport, 'wheel', onWheel, {passive: false});
  on(viewport, 'gesturestart', prevent, {passive: false});
  on(viewport, 'gesturechange', prevent, {passive: false});
  on(viewport, 'gestureend', prevent, {passive: false});
  on(viewport, 'touchmove', onTouchMove, {passive: false});
  on(viewport, 'keydown', onKey);
  on(devList, 'pointerdown', onListDown);
  on(devList, 'pointermove', onListMove);
  on(devList, 'pointerup', onListUp);
  on(devList, 'pointercancel', onListCancel);
  on(devList, 'click', onListClick);
  on(pop, 'click', onPopClick);
  on(calForm, 'submit', onCalSubmit);
  on(calCancel, 'click', function () { setTool('calibrate'); });
  on(img, 'load', function () {
    const fp = plan();
    if (fp && !S.natural[fp.id] && img.naturalWidth) {
      S.natural[fp.id] = {width: img.naturalWidth, height: img.naturalHeight};
      if (!(fp.image && Number(fp.image.width) > 0)) { S.fitted[fp.id] = false; render(); }
    }
  });
  on(img, 'error', function () { if (S.imgUrl) readout.textContent = 'Could not load the plan image.'; });
  on(store, 'doc', onDoc);
  on(store, 'selection', onSelection);
  on(store, 'highlight', onHighlight);
  on(store, 'room', onRoom);
  on(store, 'mode', render);
  let resizeObs = null;
  if (typeof ResizeObserver !== 'undefined') {
    let lastW = 0;
    resizeObs = new ResizeObserver(function () {
      const vs = vpSize();
      if (lastW === 0 && vs.w > 0 && plan()) { lastW = vs.w; fit(); }
      lastW = vs.w;
    });
    resizeObs.observe(viewport);
  }

  render();

  return {
    destroy: function () {
      listeners.forEach(function (l) { l[0].removeEventListener(l[1], l[2], l[3]); });
      if (resizeObs) resizeObs.disconnect();
      el.innerHTML = '';
    },
    focus: function (sel) {
      const id = sel && (sel.device || sel.id);
      if (!id) return;
      const target = plans().filter(function (p) { return markerOf(p, id); })[0];
      if (!target) return;
      S.fpId = target.id;
      render();
      const m = markerOf(target, id);
      const p = normToImage(target, m);
      const vs = vpSize();
      setView({x: vs.w / 2 - p.x * S.view.k, y: vs.h / 2 - p.y * S.view.k, k: S.view.k}, true);
      selectDevice(id, true);
    },
    getState: function () { return {fpId: S.fpId, view: S.view}; },
    setState: function (s) {
      if (!s) return;
      if (s.fpId) { S.fpId = s.fpId; S.fitted[s.fpId] = !!s.view; }
      if (s.view) S.view = s.view;
      render();
    },
    // test hooks (harness walkthroughs)
    _state: S,
  };
}
