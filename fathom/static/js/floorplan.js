// Floor plan view: plan image + device markers, drag to place, calibrate,
// measure, pan / zoom / pinch, layer toggles, upload. mount(el, ctx) (§6.4, §6.7).
// Route plan/<fp> (docs/ui-audit.md D1, B.3 FP); the room's devices are an explorer
// (#fp-unplaced) that is a sidebar at md/lg and a drawer at sm.
// Phase 5 (P5B): shared paths (#fp-paths tool), cable runs between placed markers
// (#fp-runs toggle, labels, run panel with length estimates, route editing) and the
// export menu (#fp-export). Runs are computed locally from the doc; GET …/runs confirms
// the numbers when the server has them (404 = older server: layer and tools hidden).
import {
  findPlan, planSize, imageToNorm, normToImage, metersPerPx, distance, formatLength,
  markerOf, markerOps, removeMarkerOps, calibrateOps, unplacedDevices, roomDevices, nudge,
  plansForRoom, newPlanOps, renamePlanOps, deletePlanOps, reorderPlanOps, toggleLayerOps, layerVisible,
  fitView, zoomAt, panBy, pinchView, screenToWorld,
  PATH_KINDS, PATH_KIND_LABELS, ESTIMATE_ROUND, pathById, polylineLength, snapToPaths, resolveRun, runsForPlan,
  estimateChanges, runLabel, roundUp, pathUsers, addPathOps, updatePathOps, deletePathOps, setRouteOps, clearRouteOps, normalizeRoute,
} from './floorplan-core.js';
import { h, on as listen } from './dom.js';
import { layoutFor } from './router-core.js';
import { mountExplorer } from './explorer.js';
import { emptyState, inlineError, skeleton } from './feedback.js';

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
const EXPLORER_KEY = 'plan-unplaced';
const RUNS_KEY = 'fathom.ui.plan.runs';
const SNAP_PX = 20;
const LONG_PRESS_MS = 500;
const CHROME_HINT = 'Needs Chrome on the server';
const MISSING_HINT = 'Export is not available on this server';
const EXPORTS = [['svg', 'Plan SVG'], ['png', 'Plan PNG'], ['pdf', 'Plan PDF']];

function storage() {
  try { return window.localStorage; } catch (e) { return null; }
}

function readRunsPref() {
  try {
    const s = storage();
    const v = s ? s.getItem(RUNS_KEY) : null;
    return v === null ? true : v !== '0';
  } catch (e) { return true; }
}

function writeRunsPref(on) {
  try { const s = storage(); if (s) s.setItem(RUNS_KEY, on ? '1' : '0'); } catch (e) { /* storage full or disabled */ }
}

// The shell loads explorer.css through the VIEWS registry; the dev harness only
// links plan.css, so put explorer.css beside it there.
function ensureExplorerCss(ctx) {
  if (typeof ctx.ensureCss === 'function') return Promise.resolve(ctx.ensureCss(['plan.css', 'explorer.css']));
  if (document.querySelector('link[href*="explorer.css"]')) return Promise.resolve();
  const plan = document.querySelector('link[href*="plan.css"]');
  if (!plan) return Promise.resolve();
  return new Promise(function (resolve) {
    const link = h('link', {rel: 'stylesheet', href: plan.getAttribute('href').replace(/plan\.css/, 'explorer.css')});
    link.addEventListener('load', function () { resolve(); });
    link.addEventListener('error', function () { resolve(); });
    document.head.appendChild(link);
  });
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

function cableById(doc, id) {
  const cs = (doc && doc.cables) || [];
  for (let i = 0; i < cs.length; i++) if (cs[i].id === id) return cs[i];
  const bs = (doc && doc.bundles) || [];
  for (let i = 0; i < bs.length; i++) if (bs[i].id === id) return bs[i];
  return null;
}

function mediumDisc(medium, vocab) {
  const m = vocab && vocab.media && vocab.media[medium];
  return (m && m.discipline) || 'other';
}

function mediumLabel(medium, vocab) {
  const m = vocab && vocab.media && vocab.media[medium];
  return (m && m.label) || medium || 'Other';
}

function ptsEqual(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (Math.abs(Number(a[i][0]) - Number(b[i][0])) > 2e-3 || Math.abs(Number(a[i][1]) - Number(b[i][1])) > 2e-3) return false;
  }
  return true;
}

export function mount(el, ctx) {
  const store = ctx.store;
  const vocab = ctx.vocab || store.vocab || {};
  const S = {
    fpId: null, view: {x: 0, y: 0, k: 1}, fitted: {}, tool: '', points: [], measure: null,
    sel: null, pointers: {}, gesture: null, natural: {}, imgUrl: '', highlight: null, popFor: null,
    pinned: false, routeSel: '', destroyed: false, emptyKey: '', imgState: '',
    // P5B: runs layer toggle, server confirmations per plan ({ok, byCable, calibrated, unit} or {ok: false}
    // after a 404), selected run / path, device filter, route editing, export probe.
    runs: readRunsPref(), server: {}, fetching: {}, runSel: null, pathSel: null, runFilter: null,
    routeEdit: false, dragRun: null, chrome: null, pathDraft: null,
  };
  const offs = [];
  function on(target, type, fn, opts) { offs.push(listen(target, type, fn, opts)); }

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
  const btnPaths = h('button', {id: 'fp-paths', type: 'button', class: 'fp-btn', 'aria-pressed': 'false', text: 'Paths',
    title: 'Draw a shared path (tray, catwalk, trench) that cable runs can follow'});
  const btnRuns = h('button', {id: 'fp-runs', type: 'button', class: 'fp-btn', 'aria-pressed': 'false', text: 'Runs',
    title: 'Show cable runs between placed devices'});
  const btnExport = h('button', {id: 'fp-export', type: 'button', class: 'fp-btn', 'aria-expanded': 'false', 'aria-haspopup': 'true', text: 'Export'});
  const exportPop = h('div', {class: 'fp-pop fp-export-pop', role: 'group', 'aria-label': 'Export plan', hidden: true});
  const exportWrap = h('span', {class: 'fp-export-wrap'}, [btnExport, exportPop]);
  const btnLayers = h('button', {id: 'fp-layers', type: 'button', class: 'fp-btn', 'aria-expanded': 'false', 'aria-haspopup': 'true', text: 'Layers'});
  const layersPop = h('div', {class: 'fp-pop fp-layers-pop', role: 'group', 'aria-label': 'Layers', hidden: true});
  const btnZoomOut = h('button', {id: 'fp-zoom-out', type: 'button', class: 'fp-btn fp-icon', 'aria-label': 'Zoom out', text: '\u2212'});
  const btnZoomIn = h('button', {id: 'fp-zoom-in', type: 'button', class: 'fp-btn fp-icon', 'aria-label': 'Zoom in', text: '+'});
  const btnFit = h('button', {id: 'fp-fit', type: 'button', class: 'fp-btn', 'aria-label': 'Fit plan to view', text: 'Fit'});
  const readout = h('span', {class: 'fp-readout', role: 'status'});
  const devGroup = h('span', {class: 'fp-group fp-devplans'}, [devSelect, devAdd]);
  const uploadGroup = h('span', {class: 'fp-group fp-upload'}, [upload, uploadLabel]);
  // Inline at lg when the row has room, otherwise inside the ⋯ menu (fitToolbar).
  const tools = h('span', {class: 'fp-group fp-tools'}, [
    uploadGroup, devGroup, btnCal, btnMeasure, btnPaths, btnRuns, h('span', {class: 'fp-layers-wrap'}, [btnLayers, layersPop]), exportWrap,
    h('span', {class: 'fp-group fp-planedit'}, [btnUp, btnDown, btnRename, btnDelete]),
  ]);
  const menuBtn = h('button', {type: 'button', class: 'fp-btn fp-icon fp-menu-more', 'aria-haspopup': 'true', 'aria-expanded': 'false',
    'aria-controls': 'fp-menu', 'aria-label': 'More floor plan tools', title: 'More tools', text: '\u22ef'});
  const menu = h('div', {id: 'fp-menu', class: 'fp-menu', role: 'group', 'aria-label': 'More floor plan tools', hidden: true});
  const menuWrap = h('span', {class: 'fp-menu-wrap'}, [menuBtn, menu]);
  const toolbar = h('div', {class: 'fp-toolbar', role: 'toolbar', 'aria-label': 'Floor plan tools'}, [
    h('span', {class: 'fp-group fp-group-plan'}, [select]),
    h('span', {class: 'fp-group fp-group-view'}, [btnFit, btnZoomOut, btnZoomIn]),
    tools,
    menuWrap,
  ]);
  const main = h('div', {class: 'fp-main'});
  const img = h('img', {class: 'fp-img', alt: '', draggable: 'false'});
  const overlay = svgEl('svg', {class: 'fp-overlay'});
  const runsSvg = svgEl('svg', {class: 'fp-runs', 'aria-hidden': 'true'});
  const labelsEl = h('div', {class: 'fp-runlabels'});
  const handlesEl = h('div', {class: 'fp-handles'});
  const markersEl = h('div', {class: 'fp-markers'});
  const world = h('div', {class: 'fp-world'}, [img, runsSvg, overlay, labelsEl, markersEl, handlesEl]);
  const empty = h('div', {class: 'fp-empty', hidden: true});
  // Plan image state: a skeleton under the (hidden) image while it loads, an inline error with
  // Retry over the canvas when it fails. Markers stay usable in both.
  const imgLoad = h('div', {class: 'fp-imgload', hidden: true});
  const imgError = h('div', {class: 'fp-imgerror', hidden: true});
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
  // P5B: the path sheet (name + kind after drawing), the run / path panel (side panel at md/lg,
  // bottom sheet at sm) and the runs bar (count, Estimate all, device filter chip).
  const pathForm = h('form', {class: 'fp-pop fp-pathform', hidden: true, 'aria-label': 'New path'});
  const pathName = h('input', {id: 'fp-path-name', type: 'text', 'aria-label': 'Path name', placeholder: 'Name', autocomplete: 'off'});
  const pathKindSel = h('select', {id: 'fp-path-kind', 'aria-label': 'Path kind'}, PATH_KINDS.map(function (k) { return h('option', {value: k, text: PATH_KIND_LABELS[k]}); }));
  const pathCancel = h('button', {type: 'button', class: 'fp-btn', text: 'Cancel'});
  pathForm.appendChild(h('strong', {text: 'New path'}));
  pathForm.appendChild(h('div', {class: 'fp-pathfields'}, [pathName, pathKindSel]));
  pathForm.appendChild(h('div', {class: 'fp-poprow'}, [h('button', {type: 'submit', class: 'fp-btn fp-primary', id: 'fp-path-save', text: 'Save path'}), pathCancel]));
  const panel = h('div', {class: 'fp-pop fp-runpanel', id: 'fp-runpanel', hidden: true, role: 'region', 'aria-label': 'Cable run'});
  const runsBar = h('div', {class: 'fp-runsbar', hidden: true});
  const viewport = h('div', {class: 'fp-viewport', role: 'application', tabindex: '0',
    'aria-label': 'Floor plan. Arrow keys pan, plus and minus zoom, F fits. With a marker focused, arrows move it, Delete removes it, Enter opens it.'},
  [imgLoad, world, empty, imgError, crosshair, calForm, pathForm, runsBar, pop, panel, readout]);
  const ghost = h('div', {class: 'fp-ghost', hidden: true, 'aria-hidden': 'true'});
  root.appendChild(toolbar);
  root.appendChild(main);
  root.appendChild(ghost);
  root.appendChild(delPop);
  el.appendChild(root);

  const harness = !ctx.api;
  devGroup.hidden = !harness;
  (ctx.devPlans || DEV_PLANS).forEach(function (p, i) { devSelect.appendChild(h('option', {value: String(i), text: p.name})); });

  // ------------------------------------------------------------ explorer
  // explorer.js builds its chips once, so a new discipline set remounts it (room change).
  let ex = null;
  let devList = null;
  let exChipKey = null;
  let exObserver = null;
  let itemMeta = {};
  const counts = {unplaced: 0, placed: 0};
  const hint = h('p', {class: 'fp-hint fp-exhint', text: 'Drag a device by its grip onto the plan, or press it to drop it in the middle.'});

  function discLabel(disc) {
    const d = vocab.disciplines && vocab.disciplines[disc];
    return (d && d.label) || disc.charAt(0).toUpperCase() + disc.slice(1);
  }

  function footerText(shown, total) {
    if (!plan()) return 'Add a plan first.';
    if (!total) return 'No devices in this room.';
    if (shown !== total) return shown + ' of ' + total + ' devices';
    return counts.unplaced + ' unplaced \u00b7 ' + counts.placed + ' placed';
  }

  function buildExplorer(discs) {
    if (ex) {
      if (exObserver) exObserver.disconnect();
      ex.destroy();
    }
    exChipKey = discs.join(',');
    ex = mountExplorer(main, {
      key: EXPLORER_KEY, title: 'Devices', glyph: '\u25EB', items: [], listId: 'fp-unplaced', mobileLabel: 'Devices',
      contentLabel: 'Floor plan canvas', footer: footerText, onSelect: onListSelect,
      chips: discs.map(function (d) { return {key: d, label: discLabel(d), test: function (it) { return it.disc === d; }}; }),
    });
    devList = ex.list;
    const head = ex.side.querySelector('.ex-head');
    if (head) head.appendChild(hint);
    ex.content.appendChild(viewport);
    if (typeof MutationObserver !== 'undefined') {
      exObserver = new MutationObserver(decorateList);
      exObserver.observe(devList, {childList: true});
    }
  }

  // explorer.js renders plain rows; this adds the drag grip (.fp-grip[data-device]) and
  // the discipline dot after each of its renders.
  function decorateList() {
    if (!devList) return;
    Array.prototype.forEach.call(devList.querySelectorAll('li.ex-item'), function (li) {
      const id = li.getAttribute('data-id');
      const meta = itemMeta[id];
      if (!meta) return;
      li.classList.add('fp-exitem');
      li.classList.toggle('fp-placed', meta.placed);
      const g = li.querySelector('.ex-item-glyph');
      if (g && !g.classList.contains('fp-grip')) {
        g.classList.add('fp-grip');
        g.setAttribute('data-device', id);
        g.setAttribute('title', 'Drag onto the plan');
      }
      let dot = li.querySelector('.fp-dot');
      if (!dot) {
        const text = li.querySelector('.ex-item-text');
        dot = h('span', {class: 'fp-dot', 'aria-hidden': 'true'});
        if (text && text.parentNode) text.parentNode.insertBefore(dot, text);
      }
      dot.style.background = meta.color;
    });
  }

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
    // D7: write actions are not rendered for viewers.
    [btnUp, btnDown, btnRename, btnDelete, uploadGroup, btnCal].forEach(function (b) { b.hidden = ro; });
    devGroup.hidden = !harness || ro;
    hint.hidden = ro;
    // P5B: runs need the server's /runs route (older servers answer 404: tool and layer hidden).
    const rs = runsSupported();
    btnPaths.hidden = ro || !rs;
    btnPaths.disabled = ro || !fp;
    btnRuns.hidden = !rs;
    btnRuns.disabled = !fp;
    exportWrap.hidden = !(ctx.api && ctx.api.floorplanExportUrl);
    btnExport.disabled = !fp;
    const tbKey = [ro, rs, exportWrap.hidden].join('|');
    if (tbKey !== S.tbKey) { S.tbKey = tbKey; fitToolbar(true); }
    btnMeasure.disabled = !fp;
    btnLayers.disabled = !fp || !(fp.layers && fp.layers.length);
    btnZoomIn.disabled = btnZoomOut.disabled = btnFit.disabled = !fp;
    // image
    empty.hidden = !!fp;
    world.hidden = !fp;
    if (!fp) {
      renderEmpty();
      img.removeAttribute('src');
      S.imgUrl = '';
      setImgState('');
    } else {
      S.emptyKey = '';
      const sz = planSize(fp);
      img.style.width = sz.w + 'px';
      img.style.height = sz.h + 'px';
      overlay.setAttribute('width', sz.w);
      overlay.setAttribute('height', sz.h);
      overlay.setAttribute('viewBox', '0 0 ' + sz.w + ' ' + sz.h);
      runsSvg.setAttribute('width', sz.w);
      runsSvg.setAttribute('height', sz.h);
      runsSvg.setAttribute('viewBox', '0 0 ' + sz.w + ' ' + sz.h);
      [markersEl, labelsEl, handlesEl].forEach(function (layer) { layer.style.width = sz.w + 'px'; layer.style.height = sz.h + 'px'; });
      img.alt = 'Floor plan: ' + fp.name;
      img.classList.toggle('fp-img-dark', !!(fp.source && fp.source.kind === 'dxf'));
      const url = imageUrl(fp);
      if (url !== S.imgUrl) { S.imgUrl = url; setImgState(url ? 'loading' : ''); img.src = url; }
      if (!S.fitted[fp.id]) { fit(); S.fitted[fp.id] = true; }
    }
    renderMarkers();
    renderDevList();
    renderLayers();
    renderOverlay();
    renderRuns();
    renderPanel();
    renderTool();
    applyView();
    probeRuns();
    const title = fp ? fp.name + ' \u00b7 Plan' : 'Plan';
    if (title !== S.title) { S.title = title; if (typeof ctx.setTitle === 'function') ctx.setTitle(title); }
    scheduleRouteSync();
  }

  function roomName() {
    const r = room();
    const m = (doc().rooms || []).filter(function (x) { return x.id === r; })[0];
    return m ? (m.name || m.id) : r;
  }

  function renderEmpty() {
    const ro = readOnly();
    const all = room() === '*' || room() === '';
    const key = [all ? '*' : roomName(), ro, harness].join('|');
    if (S.emptyKey === key) return;
    S.emptyKey = key;
    const title = all ? 'No floor plans in this project yet.' : 'No floor plan for ' + roomName() + '.';
    let text = '';
    let action = null;
    if (!ro && harness) {
      text = 'Pick a sample plan and press \u201CAdd plan\u201D.';
      action = {label: 'Add plan', run: onDevAdd};
    } else if (!ro) {
      text = 'Upload a PDF, SVG or image (PNG, JPG); Draw.io and DXF drawings work too.';
      action = {label: 'Upload', run: function () { upload.click(); }};
    }
    empty.innerHTML = '';
    empty.appendChild(emptyState({title: title, text: text, action: action}));
  }

  // '' (no image), 'loading' or 'error'.
  function setImgState(st) {
    if (st === S.imgState) return;
    S.imgState = st;
    img.classList.toggle('fp-img-pending', st !== '');
    imgLoad.innerHTML = '';
    if (st === 'loading') imgLoad.appendChild(skeleton('cards', 1));
    imgLoad.hidden = st !== 'loading';
    imgError.innerHTML = '';
    imgError.hidden = st !== 'error';
    if (st === 'error') {
      const fp = plan();
      imgError.appendChild(inlineError({message: 'The image for ' + (fp ? fp.name : 'this plan') + ' did not load.'}, retryImage));
    }
  }

  function retryImage() {
    const url = S.imgUrl;
    if (!url) return;
    setImgState('loading');
    img.removeAttribute('src');
    return new Promise(function (resolve) {
      setTimeout(function () {
        if (!S.destroyed && S.imgUrl === url) img.src = url;
        resolve();
      }, 0);
    });
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

  function listDevices(fp) {
    if (!fp) return {unplaced: [], placed: []};
    return {
      unplaced: unplacedDevices(doc(), fp.id),
      placed: roomDevices(doc(), fp.room).filter(function (d) { return markerOf(fp, d.id); }),
    };
  }

  function discsFor(fp) {
    const l = listDevices(fp);
    const seen = {};
    l.unplaced.concat(l.placed).forEach(function (d) { seen[disciplineOf(d, vocab)] = true; });
    const order = Object.keys(vocab.disciplines || {});
    return Object.keys(seen).sort(function (a, b) {
      const ia = order.indexOf(a) < 0 ? 1e3 : order.indexOf(a);
      const ib = order.indexOf(b) < 0 ? 1e3 : order.indexOf(b);
      return ia - ib || (a < b ? -1 : a > b ? 1 : 0);
    });
  }

  function renderDevList() {
    const fp = plan();
    const discs = discsFor(fp);
    if (!ex || discs.join(',') !== exChipKey) buildExplorer(discs);
    const l = listDevices(fp);
    const ro = readOnly();
    const kinds = vocab.kinds || {};
    counts.unplaced = l.unplaced.length;
    counts.placed = l.placed.length;
    itemMeta = {};
    const items = [];
    [[l.unplaced, false], [l.placed, true]].forEach(function (pair) {
      pair[0].forEach(function (d) {
        const disc = disciplineOf(d, vocab);
        const kind = kinds[d.kind];
        itemMeta[d.id] = {placed: pair[1], color: discColor(disc, vocab)};
        items.push({
          id: d.id, label: d.name || d.id, sub: (kind && kind.label) || '', disc: disc,
          glyph: ro ? '' : '\u283f', group: pair[1] ? 'Placed' : 'Unplaced',
        });
      });
    });
    ex.setItems(items);
    ex.setSelected(S.sel && itemMeta[S.sel] ? S.sel : null);
    decorateList();
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
    if (S.tool === 'paths') {
      // The path being drawn: corners plus the open polyline (closed by double-click / Enter).
      if (S.points.length > 1) {
        const pl = svgEl('polyline', {class: 'fp-pathdraft', points: S.points.map(function (p) { const q = normToImage(fp, p); return q.x + ',' + q.y; }).join(' ')});
        overlay.appendChild(pl);
      }
      S.points.forEach(function (p) { dot(p, 'fp-pathdraft-pt'); });
    } else if (S.tool) {
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
    btnPaths.setAttribute('aria-pressed', S.tool === 'paths' ? 'true' : 'false');
    btnRuns.setAttribute('aria-pressed', S.runs ? 'true' : 'false');
    viewport.classList.toggle('fp-tool', !!S.tool);
    crosshair.hidden = !S.tool || !pathForm.hidden;
    calForm.hidden = !(S.tool === 'calibrate' && S.points.length === 2);
    if (S.tool !== 'paths') pathForm.hidden = true;
    runsBar.hidden = !!S.tool || runsBar.childNodes.length === 0;
    const fp = plan();
    let txt = '';
    if (S.tool === 'calibrate') {
      txt = S.points.length < 2 ? 'Calibrate: pick point ' + (S.points.length + 1) + ' of 2 (click/tap, or Enter at the crosshair)'
        : 'Enter the real distance between the two points';
    } else if (S.tool === 'measure') {
      txt = S.measure ? 'Distance: ' + S.measure : 'Measure: pick point ' + (S.points.length + 1) + ' of 2';
      if (fp && metersPerPx(fp) == null) txt += ' \u00b7 plan not calibrated';
    } else if (S.tool === 'paths') {
      txt = !pathForm.hidden ? 'Name the path and pick its kind'
        : 'Path: click to add corners (' + S.points.length + '), double-click or Enter to finish, Esc cancels (Space adds the crosshair point)';
    } else if (fp) {
      txt = metersPerPx(fp) == null ? 'Not calibrated' : 'Calibrated \u00b7 ' + Math.round(S.view.k * 100) + '%';
    }
    readout.textContent = txt;
  }

  // ------------------------------------------------------ runs & paths (P5B)
  function sceneId() { return (ctx.preview && ctx.preview.scene) || undefined; }
  function collOfId(id) { return (doc().cables || []).some(function (x) { return x.id === id; }) ? 'cables' : 'bundles'; }
  function serverInfo() { return S.fpId ? S.server[S.fpId] : null; }
  function runsSupported() { const si = serverInfo(); return !(si && si.ok === false); }
  function runsShown() { return S.runs && runsSupported() && !!plan(); }
  function pathsShown() { return runsSupported() && !!plan() && (S.runs || S.tool === 'paths' || !!S.pathSel); }

  function localRuns(fp) {
    const all = runsForPlan(doc(), fp.id);
    if (!S.runFilter) return all;
    return all.filter(function (r) { return r.from === S.runFilter || r.to === S.runFilter; });
  }

  function runOf(fp, cableId) {
    const c = cableById(doc(), cableId);
    return c ? resolveRun(doc(), fp, c) : null;
  }

  // The server's length wins when it confirmed the same geometry (P5A is the source of truth).
  function runLength(run) {
    const si = serverInfo();
    const sr = si && si.byCable && si.byCable[run.cable];
    if (sr && sr.unit === 'm' && typeof sr.length_m === 'number' && ptsEqual(sr.points, run.points)) {
      return {text: formatLength(sr.length_m, units()), meters: sr.length_m, server: true};
    }
    if (run.unit !== 'm') return {text: '?', meters: null, server: false};
    return {text: runLabel(run, units()), meters: run.length_m, server: false};
  }

  function runEstimate(run) {
    const si = serverInfo();
    const sr = si && si.byCable && si.byCable[run.cable];
    if (sr && typeof sr.estimate_m === 'number' && ptsEqual(sr.points, run.points)) return sr.estimate_m;
    return run.estimate_m;
  }

  // GET …/runs once per plan (and again after edits while runs are shown); 404 = older server.
  function probeRuns() {
    const fp = plan();
    if (!fp || !ctx.api || typeof ctx.api.planRuns !== 'function') return;
    const key = fp.id + '|' + (sceneId() || '');
    if (S.fetching[key] || (S.server[fp.id] && S.server[fp.id].key === key && !S.server[fp.id].stale)) return;
    S.fetching[key] = true;
    Promise.resolve(ctx.api.planRuns(ctx.project, fp.id, sceneId())).then(function (res) {
      delete S.fetching[key];
      if (S.destroyed) return;
      const byCable = {};
      ((res && res.runs) || []).forEach(function (r) { if (r && r.cable) byCable[r.cable] = r; });
      S.server[fp.id] = {ok: true, key: key, byCable: byCable, calibrated: !!(res && res.calibrated), unit: (res && res.unit) || 'm', totals: (res && res.totals) || null};
      renderRuns();
      renderPanel();
    }, function (err) {
      delete S.fetching[key];
      if (S.destroyed) return;
      if (err && err.status === 404) {
        S.server[fp.id] = {ok: false, key: key};
        if (S.tool === 'paths') { S.tool = ''; S.points = []; }
        S.runSel = null;
        S.pathSel = null;
        render();
      } else {
        // Network or server error: keep the local numbers, retry on the next render.
        S.server[fp.id] = Object.assign({}, S.server[fp.id] || {ok: true, byCable: {}}, {key: key, stale: false});
      }
    });
  }

  let refetchTimer = 0;
  function scheduleRefetch() {
    if (!ctx.api || !S.fpId || !S.runs) return;
    if (S.server[S.fpId]) S.server[S.fpId].stale = true;
    if (refetchTimer) clearTimeout(refetchTimer);
    // After the change queue's debounce and save.
    refetchTimer = setTimeout(function () { refetchTimer = 0; if (!S.destroyed) probeRuns(); }, 1500);
  }

  function runColor(cable) {
    return discColor(mediumDisc(cable && cable.medium, vocab), vocab);
  }

  function imgPts(fp, pts) {
    return pts.map(function (p) { const q = normToImage(fp, p); return [q.x, q.y]; });
  }

  function midpoint(pts) {
    // Point halfway along the polyline and the unit normal of the segment it falls on.
    let total = 0;
    for (let i = 1; i < pts.length; i++) total += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    let acc = 0;
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1];
      const b = pts[i];
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (acc + len >= total / 2 || i === pts.length - 1) {
        const u = len > 0 ? (total / 2 - acc) / len : 0;
        const nx = len > 0 ? -(b[1] - a[1]) / len : 0;
        const ny = len > 0 ? (b[0] - a[0]) / len : -1;
        return {x: a[0] + (b[0] - a[0]) * u, y: a[1] + (b[1] - a[1]) * u, nx: nx, ny: ny || -1};
      }
      acc += len;
    }
    return {x: pts[0][0], y: pts[0][1], nx: 0, ny: -1};
  }

  function labelAt(fp, pts, cls, attrs, text, offset) {
    const m = midpoint(imgPts(fp, pts));
    const ny = m.ny <= 0 ? m.ny : -m.ny;
    const nx = m.ny <= 0 ? m.nx : -m.nx;
    const el = h('span', Object.assign({class: cls, text: text,
      style: 'left:' + m.x + 'px;top:' + m.y + 'px;--fp-ox:' + (nx * offset) + 'px;--fp-oy:' + (ny * offset) + 'px'}, attrs));
    labelsEl.appendChild(el);
    return el;
  }

  function polyAttr(fp, pts) {
    return imgPts(fp, pts).map(function (p) { return p[0] + ',' + p[1]; }).join(' ');
  }

  function renderRuns() {
    while (runsSvg.firstChild) runsSvg.removeChild(runsSvg.firstChild);
    labelsEl.innerHTML = '';
    handlesEl.innerHTML = '';
    const fp = plan();
    const showPaths = pathsShown();
    const showRuns = runsShown();
    runsSvg.classList.toggle('fp-runs-editing', S.routeEdit && !!S.runSel);
    if (!fp || (!showPaths && !showRuns)) { renderRunsBar(null, []); return; }
    if (showPaths) {
      (fp.paths || []).forEach(function (p) {
        const pts = (p.points || []).filter(function (q) { return Array.isArray(q) && q.length >= 2; });
        if (pts.length < 2) return;
        const kind = PATH_KINDS.indexOf(p.kind) >= 0 ? p.kind : 'other';
        const sel = S.pathSel === p.id;
        const attrs = {points: polyAttr(fp, pts), class: 'fp-path fp-path-' + kind + (sel ? ' fp-selected' : ''), 'data-path': p.id};
        if (p.color) attrs.style = 'stroke:' + p.color;
        runsSvg.appendChild(svgEl('polyline', attrs));
        runsSvg.appendChild(svgEl('polyline', {points: attrs.points, class: 'fp-path-hit', 'data-path': p.id}));
        labelAt(fp, pts, 'fp-pathlabel fp-pathlabel-' + kind + (sel ? ' fp-selected' : ''), {'data-path': p.id, role: 'button', tabindex: '0', title: PATH_KIND_LABELS[kind]}, p.name || p.id, 0);
      });
    }
    let runs = [];
    if (showRuns) {
      runs = localRuns(fp);
      const stack = {};
      const d = doc();
      runs.forEach(function (r) {
        const cable = cableById(d, r.cable);
        const sel = S.runSel === r.cable;
        const dragging = S.dragRun && S.dragRun.cable === r.cable ? S.dragRun.points : null;
        const pts = dragging || r.points;
        const color = runColor(cable);
        const cls = 'fp-run' + (r.auto && !dragging ? ' fp-auto' : '') + (sel ? ' fp-selected' : '') + (S.runSel && !sel ? ' fp-dim' : '');
        runsSvg.appendChild(svgEl('polyline', {points: polyAttr(fp, pts), class: cls, 'data-run': r.cable, style: 'stroke:' + color}));
        runsSvg.appendChild(svgEl('polyline', {points: polyAttr(fp, pts), class: 'fp-run-hit', 'data-run': r.cable}));
        // Coincident runs (same two markers, straight) stack their labels along the normal.
        const key = pts.map(function (p) { return Math.round(p[0] * 1e3) + ',' + Math.round(p[1] * 1e3); }).join('|');
        const n = stack[key] || 0;
        stack[key] = n + 1;
        const len = runLength(r);
        const tag = cable && cable.tag ? cable.tag + ' \u00b7 ' : '';
        const lab = labelAt(fp, pts, 'fp-runlabel' + (sel ? ' fp-selected' : '') + (S.runSel && !sel ? ' fp-dim' : ''),
          {'data-run': r.cable, role: 'button', tabindex: '0', 'aria-label': 'Cable run ' + (cable && cable.tag ? cable.tag : r.cable) + ', ' + (len.text === '?' ? 'length unknown' : len.text)},
          tag + len.text, 14 + n * 20);
        lab.style.setProperty('--fp-runcolor', color);
        if (len.text === '?') lab.title = 'Calibrate the plan to get lengths';
      });
      if (S.routeEdit && S.runSel) renderHandles(fp);
    }
    renderRunsBar(fp, runs);
  }

  // Route editing: corner handles (manual routes) and midpoint "add a corner" handles.
  function renderHandles(fp) {
    const run = S.dragRun || runOf(fp, S.runSel);
    if (!run || readOnly()) return;
    const cable = cableById(doc(), S.runSel);
    const manual = !!(cable && cable.route && cable.route.mode === 'manual' && (!cable.route.plan || cable.route.plan === fp.id));
    const pts = run.points;
    if (manual) {
      pts.slice(1, -1).forEach(function (p, i) {
        const q = normToImage(fp, p);
        handlesEl.appendChild(h('div', {class: 'fp-handle fp-corner', 'data-corner': String(i), role: 'button', tabindex: '0',
          'aria-label': 'Corner ' + (i + 1) + '. Drag to move, double-click to remove', title: 'Drag to move \u00b7 double-click to remove',
          style: 'left:' + q.x + 'px;top:' + q.y + 'px'}, [h('span', {class: 'fp-handle-in'})]));
      });
    }
    for (let i = 1; i < pts.length; i++) {
      const a = normToImage(fp, pts[i - 1]);
      const b = normToImage(fp, pts[i]);
      handlesEl.appendChild(h('div', {class: 'fp-handle fp-mid', 'data-seg': String(i - 1), role: 'button', tabindex: '0',
        'aria-label': 'Add a corner on segment ' + i, title: 'Drag to add a corner (near a path: follow it)',
        style: 'left:' + (a.x + b.x) / 2 + 'px;top:' + (a.y + b.y) / 2 + 'px'}, [h('span', {class: 'fp-handle-in'})]));
    }
  }

  function renderRunsBar(fp, runs) {
    runsBar.innerHTML = '';
    if (!fp || !runsShown()) { runsBar.hidden = true; return; }
    let total = 0;
    let calibrated = true;
    runs.forEach(function (r) { const l = runLength(r); if (l.meters == null) calibrated = false; else total += l.meters; });
    const n = runs.length;
    runsBar.appendChild(h('span', {class: 'fp-runs-total', text: n + ' run' + (n === 1 ? '' : 's') + (n && calibrated ? ' \u00b7 ' + formatLength(total, units()) : '')}));
    if (S.runFilter) {
      const dev = deviceById(doc(), S.runFilter);
      runsBar.appendChild(h('button', {type: 'button', class: 'fp-chip', 'data-act': 'clear-filter', 'aria-label': 'Show runs for every device',
        text: 'Runs: ' + (dev ? dev.name : S.runFilter) + ' \u2715'}));
    }
    if (!readOnly() && n && calibrated) {
      runsBar.appendChild(h('button', {type: 'button', class: 'fp-btn', id: 'fp-estimate-all', text: 'Estimate all', title: 'Write the plan lengths into every run\u2019s cable length'}));
    }
    runsBar.hidden = !!S.tool;
  }

  // ---------------------------------------------------------- run panel
  function closePanel() {
    S.runSel = null;
    S.pathSel = null;
    S.routeEdit = false;
    panel.hidden = true;
    panel.innerHTML = '';
    renderRuns();
  }

  function selectRun(id) {
    S.pathSel = null;
    S.runSel = id;
    S.routeEdit = false;
    hidePop();
    if (id) ctx.select({type: 'cable', id: id});
    renderRuns();
    renderPanel();
  }

  function selectPath(id) {
    S.runSel = null;
    S.routeEdit = false;
    S.pathSel = id;
    hidePop();
    renderRuns();
    renderPanel();
  }

  function lengthIn(meters) {
    // Panel inputs follow settings.units: metres, or feet when imperial.
    if (meters == null) return '';
    return units() === 'imperial' ? String(Math.round(meters / 0.3048 * 100) / 100) : String(Math.round(meters * 1000) / 1000);
  }
  function lengthOut(text) {
    const v = parseFloat(String(text || '').replace(',', '.'));
    if (!(v >= 0)) return 0;
    return units() === 'imperial' ? v * 0.3048 : v;
  }
  function unitLabel() { return units() === 'imperial' ? 'ft' : 'm'; }

  function row(label, value, cls) {
    return h('div', {class: 'fp-runrow' + (cls ? ' ' + cls : '')}, [h('span', {class: 'fp-runkey', text: label}), h('span', {class: 'fp-runval', text: value})]);
  }

  function renderPanel() {
    const fp = plan();
    if (!fp || (!S.runSel && !S.pathSel) || !runsSupported()) { panel.hidden = true; panel.innerHTML = ''; return; }
    panel.innerHTML = '';
    const ro = readOnly();
    const closeBtn = h('button', {type: 'button', class: 'fp-btn fp-icon', 'data-act': 'close', 'aria-label': 'Close', text: '\u00d7'});
    if (S.pathSel) {
      const p = pathById(fp, S.pathSel);
      if (!p) { closePanel(); return; }
      const kind = PATH_KINDS.indexOf(p.kind) >= 0 ? p.kind : 'other';
      const users = pathUsers(doc(), p.id);
      const len = polylineLength(p.points || [], fp);
      panel.setAttribute('aria-label', 'Path ' + (p.name || p.id));
      panel.appendChild(h('div', {class: 'fp-runhead'}, [h('strong', {class: 'fp-runtitle', text: p.name || p.id}), h('span', {class: 'fp-hint', text: PATH_KIND_LABELS[kind]}), closeBtn]));
      panel.appendChild(row('Length', metersPerPx(fp) == null ? Math.round(len) + ' px (not calibrated)' : formatLength(len, units())));
      panel.appendChild(row('Corners', String((p.points || []).length)));
      panel.appendChild(row('Used by', users.length ? users.length + ' run' + (users.length === 1 ? '' : 's') : 'no runs'));
      if (!ro) {
        const nameIn = h('input', {type: 'text', id: 'fp-path-rename', 'aria-label': 'Path name', value: p.name || ''});
        const kindIn = h('select', {id: 'fp-path-rekind', 'aria-label': 'Path kind'}, PATH_KINDS.map(function (k) { return h('option', {value: k, text: PATH_KIND_LABELS[k], selected: k === kind}); }));
        const elevIn = h('input', {type: 'number', id: 'fp-path-elev', inputmode: 'decimal', min: '0', step: 'any', 'aria-label': 'Extra rise per use', value: lengthIn(p.elevation_m || 0)});
        nameIn.addEventListener('change', function () { commit(updatePathOps(doc(), fp.id, p.id, {name: nameIn.value}), 'Renamed path ' + nameIn.value.trim()); });
        kindIn.addEventListener('change', function () { commit(updatePathOps(doc(), fp.id, p.id, {kind: kindIn.value}), 'Changed path kind'); });
        elevIn.addEventListener('change', function () { commit(updatePathOps(doc(), fp.id, p.id, {elevation_m: lengthOut(elevIn.value)}), 'Set path rise'); });
        panel.appendChild(h('label', {class: 'fp-runfield'}, [h('span', {text: 'Name'}), nameIn]));
        panel.appendChild(h('label', {class: 'fp-runfield'}, [h('span', {text: 'Kind'}), kindIn]));
        panel.appendChild(h('label', {class: 'fp-runfield'}, [h('span', {text: 'Rise per use (' + unitLabel() + ')'}), elevIn]));
        panel.appendChild(h('div', {class: 'fp-poprow'}, [h('button', {type: 'button', class: 'fp-btn fp-danger', id: 'fp-path-delete', 'data-act': 'delete-path', text: 'Delete path'})]));
      }
      panel.hidden = false;
      return;
    }
    const cable = cableById(doc(), S.runSel);
    const run = cable ? resolveRun(doc(), fp, cable) : null;
    if (!cable || !run) { closePanel(); return; }
    const from = deviceById(doc(), cable.from.device);
    const to = deviceById(doc(), cable.to.device);
    const len = runLength(run);
    const est = runEstimate(run);
    const route = normalizeRoute(Object.assign({plan: fp.id}, cable.route || {}));
    const entered = cable.length_m != null && isFinite(Number(cable.length_m)) ? formatLength(Number(cable.length_m), units()) : '\u2014';
    panel.setAttribute('aria-label', 'Cable run ' + (cable.tag || cable.id));
    panel.appendChild(h('div', {class: 'fp-runhead'}, [
      h('span', {class: 'fp-dot', style: 'background:' + runColor(cable)}),
      h('strong', {class: 'fp-runtitle', text: cable.tag || cable.label || cable.id}),
      h('span', {class: 'fp-hint', text: mediumLabel(cable.medium, vocab)}),
      closeBtn,
    ]));
    panel.appendChild(h('div', {class: 'fp-runends', text: (from ? from.name : cable.from.device) + ' \u2192 ' + (to ? to.name : cable.to.device)}));
    const lenRow = row('Length (plan)', len.text === '?' ? '? (calibrate the plan to get lengths)' : len.text + (run.auto ? ' \u00b7 straight / auto' : ' \u00b7 manual route'), 'fp-runlen');
    if (len.server) lenRow.title = 'Confirmed by the server';
    panel.appendChild(lenRow);
    panel.appendChild(row('Length (entered)', entered, 'fp-runentered'));
    if (est != null) {
      const extra = [];
      if (route.slack_m) extra.push('slack ' + formatLength(route.slack_m, units()));
      if (route.drop_m) extra.push('2 \u00d7 drop ' + formatLength(route.drop_m, units()));
      if (run.via.length) extra.push('path rise');
      panel.appendChild(row('Estimate', formatLength(roundUp(est, ESTIMATE_ROUND), units()) + (extra.length ? ' (' + extra.join(', ') + ')' : ''), 'fp-runest'));
    }
    if (run.via.length || route.via.length) {
      const chips = h('div', {class: 'fp-viarow', role: 'group', 'aria-label': 'Paths followed'}, [h('span', {class: 'fp-hint', text: 'via'})]);
      route.via.forEach(function (id, i) {
        const p = pathById(fp, id);
        const chip = h('span', {class: 'fp-chip fp-viachip', 'data-via': id}, [
          i > 0 ? h('span', {class: 'fp-hint', text: '\u203a '}) : null,
          h('span', {text: p ? (p.name || id) : id}),
          ro ? null : h('button', {type: 'button', class: 'fp-chip-x', 'data-act': 'drop-via', 'data-via': id, 'aria-label': 'Stop following ' + (p ? p.name : id), text: '\u2715'}),
        ]);
        chips.appendChild(chip);
      });
      panel.appendChild(chips);
    }
    if (!ro) {
      const canEstimate = est != null;
      const use = h('button', {type: 'button', class: 'fp-btn fp-primary', id: 'fp-use-estimate', 'data-act': 'use-estimate', disabled: !canEstimate,
        title: canEstimate ? 'Write the estimate into the cable length' : 'Calibrate the plan to get lengths', text: 'Use estimate'});
      const edit = h('button', {type: 'button', class: 'fp-btn', id: 'fp-edit-route', 'data-act': 'edit-route', 'aria-pressed': S.routeEdit ? 'true' : 'false', text: S.routeEdit ? 'Done editing' : 'Edit route'});
      const straight = h('button', {type: 'button', class: 'fp-btn', id: 'fp-straighten', 'data-act': 'straighten', disabled: !cable.route, text: 'Straighten'});
      panel.appendChild(h('div', {class: 'fp-poprow'}, [use, edit, straight]));
      if (S.routeEdit) panel.appendChild(h('p', {class: 'fp-hint fp-edithint', text: 'Drag a hollow handle to add a corner; drop it on a path to follow that path. Double-click a corner to remove it.'}));
      const slackIn = h('input', {type: 'number', id: 'fp-run-slack', inputmode: 'decimal', min: '0', step: 'any', 'aria-label': 'Slack', value: lengthIn(route.slack_m)});
      const dropIn = h('input', {type: 'number', id: 'fp-run-drop', inputmode: 'decimal', min: '0', step: 'any', 'aria-label': 'Drop at each end', value: lengthIn(route.drop_m)});
      slackIn.addEventListener('change', function () { setRoute(cable.id, Object.assign({}, route, {slack_m: lengthOut(slackIn.value)}), 'Set slack'); });
      dropIn.addEventListener('change', function () { setRoute(cable.id, Object.assign({}, route, {drop_m: lengthOut(dropIn.value)}), 'Set drop'); });
      panel.appendChild(h('div', {class: 'fp-runfields'}, [
        h('label', {class: 'fp-runfield'}, [h('span', {text: 'Slack (' + unitLabel() + ')'}), slackIn]),
        h('label', {class: 'fp-runfield'}, [h('span', {text: 'Drop each end (' + unitLabel() + ')'}), dropIn]),
      ]));
    }
    panel.appendChild(h('div', {class: 'fp-poprow'}, [
      h('button', {type: 'button', class: 'fp-btn', 'data-act': 'cable-details', text: 'Cable details'}),
    ]));
    panel.hidden = false;
  }

  function setRoute(cableId, route, label) {
    const fp = plan();
    if (!fp) return;
    const cable = cableById(doc(), cableId);
    commit(setRouteOps(doc(), cableId, Object.assign({plan: fp.id}, route)), (label || 'Changed route') + ' of ' + (cable && cable.tag ? cable.tag : cableId));
    scheduleRefetch();
  }

  function onPanelClick(e) {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    const act = b.getAttribute('data-act');
    const fp = plan();
    if (act === 'close') { closePanel(); viewport.focus(); return; }
    if (!fp) return;
    if (act === 'cable-details' && S.runSel) { openDetails({type: 'cable', id: S.runSel}); return; }
    if (act === 'edit-route') { S.routeEdit = !S.routeEdit; renderRuns(); renderPanel(); return; }
    if (act === 'straighten' && S.runSel) {
      const cable = cableById(doc(), S.runSel);
      commit(clearRouteOps(doc(), S.runSel), 'Straightened run ' + (cable && cable.tag ? cable.tag : S.runSel));
      S.routeEdit = false;
      scheduleRefetch();
      return;
    }
    if (act === 'drop-via' && S.runSel) {
      const cable = cableById(doc(), S.runSel);
      const route = normalizeRoute(Object.assign({plan: fp.id}, (cable && cable.route) || {}));
      route.via = route.via.filter(function (v) { return v !== b.getAttribute('data-via'); });
      setRoute(S.runSel, route, 'Changed paths');
      return;
    }
    if (act === 'use-estimate' && S.runSel) { useEstimate([S.runSel], false); return; }
    if (act === 'delete-path' && S.pathSel) { deletePath(S.pathSel); }
  }

  function deletePath(id) {
    const fp = plan();
    const p = fp && pathById(fp, id);
    if (!p) return;
    const users = pathUsers(doc(), id);
    const msg = 'Delete path "' + (p.name || id) + '"?' + (users.length ? '\n' + users.length + ' run' + (users.length === 1 ? ' follows' : 's follow') + ' it and will go straight again.' : '\nNo runs follow it.');
    Promise.resolve(ctx.confirm ? ctx.confirm(msg, {danger: true, ok: 'Delete path'}) : window.confirm(msg)).then(function (yes) {
      if (yes !== true) return;
      commit(deletePathOps(doc(), fp.id, id), 'Deleted path ' + (p.name || id));
      closePanel();
      scheduleRefetch();
      viewport.focus();
    });
  }

  // Use estimate / Estimate all: the server writes length_m (POST …/runs/estimate); the harness
  // (no API) commits the same change locally. The toast offers Undo (inverse merges).
  function useEstimate(ids, all) {
    const fp = plan();
    if (!fp || readOnly()) return;
    const label = function (ch) {
      if (ch.length === 1) return 'Length set to ' + formatLength(ch[0].to_m, units());
      return 'Updated ' + ch.length + ' cable length' + (ch.length === 1 ? '' : 's');
    };
    const local = estimateChanges(doc(), fp.id, all ? null : ids, ESTIMATE_ROUND);
    if (!ctx.api || typeof ctx.api.planEstimate !== 'function') {
      if (!local.length) { ctx.toast('Lengths already match the plan', 'info'); return; }
      commit(local.map(function (c) { return {op: 'merge', coll: collOfId(c.cable), id: c.cable, value: {length_m: c.to_m}}; }),
        'Estimated cable lengths from ' + fp.name + ' (' + local.length + ')');
      toastUndo(label(local), local);
      renderPanel();
      return;
    }
    const body = Object.assign(all ? {all: true} : {cables: ids}, {base_revision: store.revision, round_to: ESTIMATE_ROUND});
    const flush = typeof ctx.flush === 'function' ? Promise.resolve(ctx.flush()).catch(function () { return null; }) : Promise.resolve(null);
    panel.classList.add('fp-busy');
    flush.then(function () {
      body.base_revision = store.revision;
      return ctx.api.planEstimate(ctx.project, fp.id, body);
    }).then(function (res) {
      panel.classList.remove('fp-busy');
      const updated = (res && res.updated) || [];
      const ops = updated.filter(function (u) { return u && cableById(doc(), u.cable); }).map(function (u) {
        return {op: 'merge', coll: collOfId(u.cable), id: u.cable, value: {length_m: u.to_m}};
      });
      try { if (ops.length && store.applyRemote) store.applyRemote(ops, 'remote'); } catch (e) { /* the next resync brings the server doc */ }
      if (res && typeof res.revision === 'number' && store.setRevision && !(store.revision >= res.revision)) store.setRevision(res.revision);
      if (!updated.length) { ctx.toast('Lengths already match the plan', 'info'); renderPanel(); return; }
      toastUndo(label(updated), updated);
      renderPanel();
    }, function (err) {
      panel.classList.remove('fp-busy');
      if (err && err.status === 409) {
        ctx.toast('The project changed since the plan was loaded \u2014 reloading, then try again.', 'warn');
        if (typeof ctx.reload === 'function') Promise.resolve(ctx.reload()).catch(function () { return null; });
      } else if (err && (err.status === 423 || err.code === 'locked')) {
        ctx.toast('Editing is locked \u2014 the lengths were not changed.', 'warn');
      } else if (err && err.status === 404) {
        ctx.toast('This server cannot estimate lengths (update Fathom).', 'warn');
      } else {
        ctx.toast('Could not estimate: ' + ((err && err.message) || 'error'), 'err');
      }
    });
  }

  function toastUndo(text, changes) {
    const t = ctx.toast(text, 'ok');
    if (!t || !t.appendChild) return;
    const inverse = changes.map(function (c) {
      return {op: 'merge', coll: collOfId(c.cable), id: c.cable, value: {length_m: c.from_m == null ? null : c.from_m}};
    });
    t.appendChild(document.createTextNode(' \u00b7 '));
    t.appendChild(h('button', {type: 'button', class: 'small fp-toast-undo', onclick: function (e) {
      e.stopPropagation();
      t.remove();
      commit(inverse, 'Undo: ' + text);
      ctx.toast('Undone', 'ok');
      scheduleRefetch();
    }}, 'Undo'));
  }

  function estimateAll() {
    const fp = plan();
    if (!fp || readOnly()) return;
    const runs = runsForPlan(doc(), fp.id);
    const changes = estimateChanges(doc(), fp.id, null, ESTIMATE_ROUND);
    const msg = 'Estimate lengths for ' + runs.length + ' run' + (runs.length === 1 ? '' : 's') + ' on ' + fp.name + '?\n'
      + (changes.length ? changes.length + ' cable length' + (changes.length === 1 ? '' : 's') + ' would change (rounded up to ' + formatLength(ESTIMATE_ROUND, units()) + ').' : 'Every length already matches the plan.');
    Promise.resolve(ctx.confirm ? ctx.confirm(msg, {ok: 'Estimate', title: 'Estimate all'}) : window.confirm(msg)).then(function (yes) {
      if (yes === true) useEstimate(null, true);
    });
  }

  function onRunsBarClick(e) {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.getAttribute('data-act') === 'clear-filter') { S.runFilter = null; renderRuns(); return; }
    if (b.id === 'fp-estimate-all') estimateAll();
  }

  function filterRuns(deviceId) {
    S.runFilter = deviceId;
    if (!S.runs) toggleRuns(true);
    hidePop();
    renderRuns();
    const dev = deviceById(doc(), deviceId);
    announce('Showing runs for ' + (dev ? dev.name : deviceId));
  }

  function toggleRuns(force) {
    S.runs = typeof force === 'boolean' ? force : !S.runs;
    writeRunsPref(S.runs);
    if (!S.runs) { S.runSel = null; S.routeEdit = false; S.runFilter = null; }
    renderRuns();
    renderPanel();
    renderTool();
    if (S.runs) probeRuns();
  }

  // --------------------------------------------------------- paths tool
  function finishPath() {
    const fp = plan();
    if (!fp || S.tool !== 'paths') return;
    // A double-click leaves a duplicate last corner.
    const pts = [];
    S.points.forEach(function (p) {
      const q = normToImage(fp, p);
      const last = pts.length ? normToImage(fp, pts[pts.length - 1]) : null;
      if (!last || Math.hypot(q.x - last.x, q.y - last.y) > 2 / (S.view.k || 1)) pts.push(p);
    });
    S.points = pts;
    if (pts.length < 2) { ctx.toast('A path needs at least two corners.', 'warn'); renderOverlay(); renderTool(); return; }
    pathName.value = 'Path ' + ((fp.paths || []).length + 1);
    pathKindSel.value = 'tray';
    pathForm.hidden = false;
    renderOverlay();
    renderTool();
    pathName.focus();
    pathName.select();
  }

  function onPathSubmit(e) {
    e.preventDefault();
    const fp = plan();
    if (!fp || S.tool !== 'paths' || S.points.length < 2) return;
    const res = addPathOps(doc(), fp.id, {name: pathName.value, kind: pathKindSel.value, points: S.points.map(function (p) { return [p.x, p.y]; })});
    S.tool = '';
    S.points = [];
    pathForm.hidden = true;
    commit(res.ops, 'Added path ' + (pathName.value.trim() || res.id) + ' to ' + fp.name);
    S.pathSel = res.id;
    render();
    scheduleRefetch();
    viewport.focus();
  }

  function cancelPathForm() {
    pathForm.hidden = true;
    if (S.tool === 'paths') setTool('paths');
  }

  // ------------------------------------------------------- route editing
  function handleGesture(el, pt, pointerId) {
    const fp = plan();
    const run = fp && runOf(fp, S.runSel);
    if (!run) return null;
    const corner = el.getAttribute('data-corner');
    const seg = el.getAttribute('data-seg');
    return {type: 'handle', start: pt, moved: false, pointer: pointerId, run: run, cable: S.runSel,
      corner: corner == null ? -1 : parseInt(corner, 10), seg: seg == null ? -1 : parseInt(seg, 10), el: el, last: null, snap: null};
  }

  function snapNorm(fp, n) {
    const sz = planSize(fp);
    const maxNorm = SNAP_PX / ((S.view.k || 1) * Math.sqrt(sz.w * sz.h));
    return snapToPaths(fp, [n.x, n.y], maxNorm);
  }

  function moveHandle(g, pt) {
    const fp = plan();
    if (!fp) return;
    const n0 = normAtScreen(pt);
    const n = {x: Math.max(0, Math.min(1, n0.x)), y: Math.max(0, Math.min(1, n0.y))};
    const snap = snapNorm(fp, n);
    const p = snap ? snap.point : [n.x, n.y];
    const pts = g.run.points.slice();
    if (g.corner >= 0) pts[g.corner + 1] = p;
    else pts.splice(g.seg + 1, 0, p);
    g.last = p;
    g.snap = snap;
    S.dragRun = {cable: g.cable, points: pts};
    viewport.classList.toggle('fp-snapping', !!snap);
    renderRuns();
  }

  function endHandle(g) {
    S.dragRun = null;
    viewport.classList.remove('fp-snapping');
    if (!g.moved || !g.last || readOnly()) { renderRuns(); return; }
    const fp = plan();
    const cable = cableById(doc(), g.cable);
    if (!fp || !cable) { renderRuns(); return; }
    const route = normalizeRoute(Object.assign({plan: fp.id}, cable.route || {}));
    const manual = route.mode === 'manual' && (!cable.route || !cable.route.plan || cable.route.plan === fp.id);
    if (!manual && g.snap && g.corner < 0) {
      // Dropped on a path while auto: follow it (inserted after the paths the run already uses before this segment).
      let before = 0;
      g.run.segments.slice(0, g.seg).forEach(function (s) { if (s.kind === 'path') before++; });
      const via = route.via.filter(function (v) { return v !== g.snap.path; });
      via.splice(Math.min(before, via.length), 0, g.snap.path);
      const p = pathById(fp, g.snap.path);
      setRoute(g.cable, Object.assign({}, route, {mode: 'auto', points: [], via: via}), 'Routed via ' + (p ? p.name : g.snap.path));
      return;
    }
    // Otherwise the geometry becomes a manual route with the dragged / added corner.
    const inner = g.run.points.slice(1, -1).map(function (q) { return [q[0], q[1]]; });
    if (g.corner >= 0) inner[g.corner] = g.last;
    else inner.splice(g.seg, 0, g.last);
    setRoute(g.cable, Object.assign({}, route, {mode: 'manual', points: inner}), g.corner >= 0 ? 'Moved a corner' : 'Added a corner');
  }

  function removeCorner(idx) {
    const fp = plan();
    const cable = fp && cableById(doc(), S.runSel);
    if (!cable || !cable.route || cable.route.mode !== 'manual') return;
    const route = normalizeRoute(Object.assign({plan: fp.id}, cable.route));
    route.points.splice(idx, 1);
    setRoute(S.runSel, route, 'Removed a corner');
  }

  // ----------------------------------------------------------- export menu
  function exportHrefs(fp) {
    return EXPORTS.map(function (f) {
      return {fmt: f[0], label: f[1], href: ctx.api.floorplanExportUrl(ctx.project, fp.id, f[0], {runs: S.runs, scene: sceneId()})};
    });
  }

  function renderExport() {
    exportPop.innerHTML = '';
    const fp = plan();
    if (!fp || !ctx.api || !ctx.api.floorplanExportUrl) return;
    const missing = S.chrome === 'missing';
    exportHrefs(fp).forEach(function (x) {
      const needsChrome = x.fmt !== 'svg';
      const off = missing || (needsChrome && S.chrome === false);
      const hint = missing ? MISSING_HINT : (needsChrome && S.chrome === false ? CHROME_HINT : null);
      const a = h('a', {class: 'fp-btn fp-export-item', 'data-fmt': x.fmt, href: off ? null : x.href, download: off ? null : '',
        'aria-disabled': off ? 'true' : null, title: hint, text: x.label});
      exportPop.appendChild(a);
    });
    const note = missing ? MISSING_HINT + '.' : S.chrome === false ? CHROME_HINT + ' for PNG and PDF.'
      : (S.runs ? 'Includes the cable runs.' : 'Without the cable runs (turn Runs on to include them).');
    exportPop.appendChild(h('p', {class: 'fp-hint', text: note}));
  }

  // One HEAD on the PNG route tells whether the server can rasterise (400 chrome_missing) or lacks the
  // export routes altogether (404: every item disabled).
  function probeChrome() {
    const fp = plan();
    if (S.chrome !== null || !fp || !ctx.api || typeof fetch !== 'function') return;
    S.chrome = 'probing';
    const href = ctx.api.floorplanExportUrl(ctx.project, fp.id, 'png', {});
    fetch(href, {method: 'HEAD', credentials: 'same-origin', headers: {'X-Fathom': '1'}}).then(function (res) {
      S.chrome = res.status === 400 ? false : res.status === 404 ? 'missing' : true;
      if (!exportPop.hidden) renderExport();
    }, function () {
      S.chrome = null;
    });
  }

  function toggleExport(open) {
    const want = typeof open === 'boolean' ? open : exportPop.hidden;
    if (want) { renderExport(); probeChrome(); }
    exportPop.hidden = !want;
    btnExport.setAttribute('aria-expanded', want ? 'true' : 'false');
    if (want) { const first = exportPop.querySelector('a[href]'); if (first) first.focus(); }
  }

  function onExportClick(e) {
    const a = e.target.closest('a.fp-export-item');
    if (!a) return;
    if (a.getAttribute('aria-disabled') === 'true') { e.preventDefault(); ctx.toast(a.title || CHROME_HINT, 'warn'); return; }
    toggleExport(false);
    closeMenu(false);
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
    if (runsSupported()) {
      const n = runsForPlan(doc(), fp.id).filter(function (r) { return r.from === id || r.to === id; }).length;
      row.appendChild(h('button', {type: 'button', class: 'fp-btn', 'data-act': 'runs', disabled: !n, text: 'Show runs for this device' + (n ? ' (' + n + ')' : '')}));
    }
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
    pathForm.hidden = true;
    if (S.tool === 'paths') { S.runSel = null; S.routeEdit = false; hidePop(); renderPanel(); }
    if (S.tool === 'calibrate') {
      const fp = plan();
      calUnit.value = fp && fp.calibration && fp.calibration.unit ? fp.calibration.unit : (units() === 'imperial' ? 'ft' : 'm');
      calInput.value = fp && fp.calibration ? String(fp.calibration.distance) : '';
    }
    renderOverlay();
    renderRuns();
    renderTool();
    viewport.focus();
  }

  function addPoint(n) {
    const fp = plan();
    if (!fp || !S.tool) return;
    if (S.tool === 'paths') {
      if (!pathForm.hidden) return;
      S.points.push({x: Math.max(0, Math.min(1, n.x)), y: Math.max(0, Math.min(1, n.y))});
      renderOverlay();
      renderTool();
      return;
    }
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
    if (e.target.closest('.fp-pop, .fp-empty, .fp-imgerror, .fp-runsbar')) return;
    const pt = localPt(e);
    S.pointers[e.pointerId] = {id: e.pointerId, x: pt.x, y: pt.y};
    const ps = pointerList();
    if (ps.length === 2) {
      cancelMarkerDrag();
      clearLongPress();
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
      // Long-press (touch / pen) opens the marker menu with "Show runs for this device".
      if (e.pointerType !== 'mouse' && runsSupported()) {
        clearLongPress();
        longPress = setTimeout(function () {
          longPress = 0;
          if (S.gesture && S.gesture.type === 'marker' && !S.gesture.moved) { S.gesture.longPressed = true; selectDevice(id, true); }
        }, LONG_PRESS_MS);
      }
      e.preventDefault();
      return;
    }
    const handle = e.target.closest('.fp-handle');
    if (handle && !S.tool && S.routeEdit && S.runSel && !readOnly()) {
      const g = handleGesture(handle, pt, e.pointerId);
      if (g) { S.gesture = g; e.preventDefault(); return; }
    }
    // Run / path hits select on release when the pointer did not pan.
    const hitEl = S.tool ? null : e.target.closest('[data-run], [data-path]');
    const hit = hitEl ? (hitEl.getAttribute('data-run') ? {run: hitEl.getAttribute('data-run')} : {path: hitEl.getAttribute('data-path')}) : null;
    S.gesture = {type: 'pan', start: pt, view: S.view, moved: false, pointer: e.pointerId, hit: hit};
  }

  let longPress = 0;
  function clearLongPress() { if (longPress) { clearTimeout(longPress); longPress = 0; } }

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
    clearLongPress();
    if (g.type === 'pan') {
      setView(panBy(g.view, dx, dy), false);
      positionPop();
    } else if (g.type === 'handle') {
      moveHandle(g, pt);
    } else if (g.type === 'marker') {
      if (readOnly() || g.longPressed) return;
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
    clearLongPress();
    if (g.type === 'marker') {
      if (g.longPressed) return;
      if (g.moved && g.last && !readOnly()) {
        const dev = deviceById(doc(), g.id);
        commit(markerOps(doc(), S.fpId, g.id, g.last), 'Moved ' + (dev ? dev.name : g.id) + ' on ' + plan().name);
      } else {
        g.el.classList.remove('fp-dragging');
        selectDevice(g.id, true);
        g.el.focus();
      }
    } else if (g.type === 'handle') {
      endHandle(g);
    } else if (g.type === 'pan') {
      if (!g.moved) {
        if (S.tool) addPoint(normAtScreen(pt));
        else if (g.hit && g.hit.run) selectRun(g.hit.run);
        else if (g.hit && g.hit.path) selectPath(g.hit.path);
        else { selectDevice(null, false); if (S.runSel || S.pathSel) closePanel(); }
      } else { renderOverlay(); }
    }
  }

  function cancelMarkerDrag() {
    const g = S.gesture;
    if (g && g.type === 'marker' && g.moved) renderMarkers();
    if (g && g.type === 'handle') { S.dragRun = null; viewport.classList.remove('fp-snapping'); renderRuns(); }
    clearLongPress();
    S.gesture = null;
  }

  function onDblClick(e) {
    if (S.tool === 'paths') { e.preventDefault(); finishPath(); return; }
    const hd = e.target.closest('.fp-handle.fp-corner');
    if (hd && S.routeEdit && S.runSel && !readOnly()) { e.preventDefault(); removeCorner(parseInt(hd.getAttribute('data-corner'), 10)); }
  }

  // Right-click on a marker: the marker menu (with "Show runs for this device").
  function onContextMenu(e) {
    const mk = e.target.closest('.fp-marker');
    if (!mk || S.tool) return;
    e.preventDefault();
    selectDevice(mk.getAttribute('data-device'), true);
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

  // Pointer capture goes to the root, not the grip: at sm the explorer drawer hides
  // (visibility) under the pointer once the drag starts.
  function onListDown(e) {
    const grip = e.target.closest && e.target.closest('.fp-grip');
    if (!grip || !devList || !devList.contains(grip) || readOnly() || !plan()) return;
    if (e.button != null && e.button > 0 && e.pointerType === 'mouse') return;
    e.preventDefault();
    listDrag = {id: grip.getAttribute('data-device'), x: e.clientX, y: e.clientY, pointer: e.pointerId, moved: false, src: grip};
    capture(root, e.pointerId);
  }

  function onListMove(e) {
    if (!listDrag || listDrag.pointer !== e.pointerId) return;
    if (!listDrag.moved && Math.hypot(e.clientX - listDrag.x, e.clientY - listDrag.y) < DRAG_SLOP) return;
    if (!listDrag.moved && ex && ex.isOpen()) ex.close({focus: false});
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

  // The click that ends a list drag lands on the grip or, with root capture, on the root.
  function onClickCapture(e) {
    if (!suppressClick || !(e.target === root || (devList && devList.contains(e.target)))) return;
    e.preventDefault();
    e.stopPropagation();
  }

  function centerOn(fp, id) {
    const m = markerOf(fp, id);
    if (!m) return false;
    const p = normToImage(fp, m);
    const vs = vpSize();
    setView({x: vs.w / 2 - p.x * S.view.k, y: vs.h / 2 - p.y * S.view.k, k: S.view.k}, true);
    return true;
  }

  // Explorer activation (click, tap, Enter): a placed device is shown, an unplaced one
  // is dropped in the middle of the plan (the keyboard alternative to dragging).
  function onListSelect(item) {
    const id = String(item.id);
    const fp = plan();
    if (!fp) { ctx.select({type: 'device', id: id}); return; }
    if (centerOn(fp, id)) {
      selectDevice(id, true);
      refocusMarker(id);
      return;
    }
    if (readOnly()) { selectDevice(id, false); return; }
    placeDevice(id, centerNorm());
    selectDevice(id, false);
    refocusMarker(id);
  }

  function cssEscape(s) { return String(s).replace(/["\\]/g, '\\$&'); }

  // ----------------------------------------------------------- keyboard
  function onKey(e) {
    if (e.target.closest('input,select,textarea,form,.fp-pop,.fp-empty,.fp-imgerror,.fp-runsbar')) {
      if (e.key === 'Escape') {
        if (!pathForm.hidden) { cancelPathForm(); viewport.focus(); return; }
        if (S.tool) setTool(S.tool);
        hidePop();
        if (S.runSel || S.pathSel) closePanel();
        viewport.focus();
      }
      return;
    }
    const fp = plan();
    if (!fp) return;
    // Run labels, path labels and route handles are keyboard targets too.
    const runEl = e.target.closest('[data-run], [data-path]');
    if (runEl && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      if (runEl.getAttribute('data-run')) selectRun(runEl.getAttribute('data-run')); else selectPath(runEl.getAttribute('data-path'));
      return;
    }
    const hd = e.target.closest('.fp-handle.fp-corner');
    if (hd && (e.key === 'Delete' || e.key === 'Backspace') && S.routeEdit && !readOnly()) {
      e.preventDefault();
      removeCorner(parseInt(hd.getAttribute('data-corner'), 10));
      return;
    }
    if (S.tool === 'paths') {
      if (e.key === 'Enter') { e.preventDefault(); if (S.points.length >= 2) finishPath(); else addPoint(centerNorm()); return; }
      if (e.key === ' ') { e.preventDefault(); addPoint(centerNorm()); return; }
    }
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
        openDetails(id);
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
      if (S.tool) setTool(S.tool);
      else if (S.runSel || S.pathSel) closePanel();
      else selectDevice(null, false);
    }
  }

  // Explicit inspection opens the drawer at every width (D4); plain selection stays ctx.select.
  function openDetails(id) {
    const sel = typeof id === 'string' ? {type: 'device', id: id} : id;
    if (typeof ctx.openDrawer === 'function') ctx.openDrawer(sel);
    else if (ctx.openInspector) ctx.openInspector(sel);
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
    S.pinned = !!S.fpId;
    S.tool = '';
    S.points = [];
    hidePop();
    leavePlan();
    render();
    if (routed()) ctx.navigateRoute({id: S.fpId || ''});
  }

  // ------------------------------------------------------------- route
  // plan/<fp> (D1). The URL follows S.fpId: #fp-select pushes; fallbacks (missing or
  // unknown id, deleted plan, room change, new plan) replace and keep the query.
  function routed() {
    const r = ctx.route;
    return !!(r && r.view === 'plan' && typeof ctx.navigateRoute === 'function');
  }

  let syncTimer = 0;
  function scheduleRouteSync() {
    if (syncTimer || !routed()) return;
    // Deferred: writing the hash while the shell is still mounting would remount the view.
    syncTimer = setTimeout(function () {
      syncTimer = 0;
      if (S.destroyed || !routed()) return;
      const r = ctx.route;
      const want = S.fpId || '';
      if ((r.id || '') !== want) ctx.navigateRoute({id: want, query: r.query}, {replace: true});
    }, 0);
  }

  function knownPlan(id) {
    return !!id && plans().some(function (p) { return p.id === id; });
  }

  function applyRouteId(id) {
    if (knownPlan(id)) {
      S.pinned = true;
      if (id === S.fpId) return false;
      S.fpId = id;
    } else {
      S.pinned = false;
      if (knownPlan(S.fpId)) return false;
      S.fpId = null;
    }
    S.tool = '';
    S.points = [];
    S.measure = null;
    hidePop();
    leavePlan();
    return true;
  }

  // Per-plan P5B state that does not carry over to another plan.
  function leavePlan() {
    S.runSel = null;
    S.pathSel = null;
    S.routeEdit = false;
    S.runFilter = null;
    S.dragRun = null;
    pathForm.hidden = true;
    exportPop.hidden = true;
    btnExport.setAttribute('aria-expanded', 'false');
  }

  // -------------------------------------------------- toolbar and ⋯ menu
  let fitKey = '';
  function fitToolbar(force) {
    if (S.destroyed) return;
    const width = toolbar.clientWidth;
    const lay = layoutFor(window.innerWidth);
    const key = width + '|' + lay;
    if (!force && key === fitKey) return;
    fitKey = key;
    let inline = lay === 'lg';
    if (inline) {
      if (tools.parentNode !== toolbar) toolbar.insertBefore(tools, menuWrap);
      menuWrap.hidden = true;
      toolbar.classList.add('fp-measuring');
      inline = toolbar.scrollWidth <= toolbar.clientWidth + 1;
      toolbar.classList.remove('fp-measuring');
    }
    if (!inline && tools.parentNode !== menu) menu.appendChild(tools);
    menuWrap.hidden = inline;
    root.classList.toggle('fp-tools-inline', inline);
    if (inline) closeMenu(false);
  }

  function menuOpen() { return !menu.hidden; }

  function openMenu() {
    if (menuOpen()) return;
    menu.hidden = false;
    menuBtn.setAttribute('aria-expanded', 'true');
    const first = menu.querySelector('button:not([disabled]):not([hidden]), label.fp-btn:not(.fp-disabled), select:not([disabled])');
    if (first && first.offsetParent) first.focus();
  }

  function closeMenu(focusBtn) {
    if (!menuOpen()) return;
    menu.hidden = true;
    menuBtn.setAttribute('aria-expanded', 'false');
    layersPop.hidden = true;
    btnLayers.setAttribute('aria-expanded', 'false');
    exportPop.hidden = true;
    btnExport.setAttribute('aria-expanded', 'false');
    if (focusBtn) menuBtn.focus();
  }

  function onMenuClick(e) {
    const b = e.target.closest('button, label.fp-btn');
    if (!b || b === btnLayers || layersPop.contains(b) || b === btnExport || exportPop.contains(b)) return;
    // The label opens the file picker first; the menu closes after that click.
    setTimeout(function () { closeMenu(false); }, 0);
  }

  function onDocPointer(e) {
    if (menuOpen() && !menuWrap.contains(e.target)) closeMenu(false);
    if (!exportPop.hidden && !exportWrap.contains(e.target)) toggleExport(false);
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
    if (act === 'details') openDetails(id);
    else if (act === 'runs') filterRuns(id);
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
  function onDoc(e) {
    render();
    positionPop();
    const d = e && e.detail;
    const touched = (d && d.touched) || [];
    if (d && d.source === 'load') { Object.keys(S.server).forEach(function (k) { if (S.server[k].ok !== false) S.server[k].stale = true; }); probeRuns(); }
    else if (touched.some(function (t) { return /^(floorplans|cables|bundles)\//.test(String(t)); })) scheduleRefetch();
  }
  function onSelection(e) {
    const sel = e.detail;
    const id = sel && (sel.type === 'device' || sel.type === 'marker') ? (sel.device || sel.id) : null;
    if (id !== S.sel) { S.sel = id; renderMarkers(); }
    if (S.runSel && !(sel && sel.type === 'cable' && sel.id === S.runSel)) { S.runSel = null; S.routeEdit = false; renderRuns(); renderPanel(); }
  }
  function onHighlight(e) { S.highlight = e.detail; renderMarkers(); }
  function onRoom() { S.fpId = null; S.pinned = false; S.tool = ''; hidePop(); leavePlan(); render(); }

  on(menuBtn, 'click', function () { if (menuOpen()) closeMenu(true); else openMenu(); });
  on(menu, 'click', onMenuClick);
  on(menu, 'keydown', function (e) {
    if (e.key !== 'Escape' || layersPop.contains(e.target)) return;
    e.preventDefault();
    e.stopPropagation();
    closeMenu(true);
  });
  on(upload, 'change', function () { closeMenu(false); });
  on(document, 'pointerdown', onDocPointer, true);
  on(select, 'change', onSelect);
  on(btnUp, 'click', function () { commit(reorderPlanOps(doc(), S.fpId, -1), 'Reordered plans'); });
  on(btnDown, 'click', function () { commit(reorderPlanOps(doc(), S.fpId, 1), 'Reordered plans'); });
  on(btnRename, 'click', onRename);
  on(btnDelete, 'click', onDelete);
  on(upload, 'change', onUpload);
  on(devAdd, 'click', onDevAdd);
  on(btnCal, 'click', function () { setTool('calibrate'); });
  on(btnMeasure, 'click', function () { setTool('measure'); });
  on(btnPaths, 'click', function () { setTool('paths'); });
  on(btnRuns, 'click', function () { toggleRuns(); });
  on(btnExport, 'click', function () { toggleExport(); });
  on(exportPop, 'click', onExportClick);
  on(exportPop, 'keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); toggleExport(false); btnExport.focus(); } });
  on(pathForm, 'submit', onPathSubmit);
  on(pathCancel, 'click', cancelPathForm);
  on(panel, 'click', onPanelClick);
  on(runsBar, 'click', onRunsBarClick);
  on(viewport, 'dblclick', onDblClick);
  on(viewport, 'contextmenu', onContextMenu);
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
  on(root, 'pointerdown', onListDown);
  on(root, 'pointermove', onListMove);
  on(root, 'pointerup', onListUp);
  on(root, 'pointercancel', onListCancel);
  on(root, 'click', onClickCapture, true);
  on(pop, 'click', onPopClick);
  on(calForm, 'submit', onCalSubmit);
  on(calCancel, 'click', function () { setTool('calibrate'); });
  on(img, 'load', function () {
    if (img.getAttribute('src')) setImgState('');
    const fp = plan();
    if (fp && !S.natural[fp.id] && img.naturalWidth) {
      S.natural[fp.id] = {width: img.naturalWidth, height: img.naturalHeight};
      if (!(fp.image && Number(fp.image.width) > 0)) { S.fitted[fp.id] = false; render(); }
    }
  });
  on(img, 'error', function () { if (S.imgUrl) setImgState('error'); });
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
  let toolbarObs = null;
  if (typeof ResizeObserver !== 'undefined') {
    toolbarObs = new ResizeObserver(function () { fitToolbar(false); });
    toolbarObs.observe(toolbar);
  } else {
    on(window, 'resize', function () { fitToolbar(false); });
  }

  const initial = ctx.route;
  S.routeSel = (initial && initial.query && initial.query.sel) || '';
  applyRouteId(initial && initial.view === 'plan' ? initial.id : '');
  ensurePlan();
  buildExplorer(discsFor(plan()));
  render();
  ensureExplorerCss(ctx).then(function () { fitToolbar(true); });

  // Prefers the plan the selection names, then the current plan, then (unless the URL
  // names a plan) the first plan of the room that has the device.
  function focusSel(sel, center) {
    const id = sel && (sel.device || sel.id);
    if (!id) return;
    let target = null;
    if (sel.type === 'marker' && knownPlan(sel.floorplan) && markerOf(findPlan(doc(), sel.floorplan), id)) target = findPlan(doc(), sel.floorplan);
    else if (plan() && markerOf(plan(), id)) target = plan();
    else if (!S.pinned) target = plans().filter(function (p) { return markerOf(p, id); })[0] || null;
    if (!target) return;
    if (target.id !== S.fpId) { S.fpId = target.id; S.pinned = true; S.tool = ''; S.points = []; hidePop(); }
    render();
    if (center) centerOn(target, id);
    if (sel.type !== 'marker') { selectDevice(id, true); return; }
    // A marker deep link stays a marker selection: the inspector has a marker panel.
    const cur = store.selection;
    if (!(cur && cur.type === 'marker' && cur.floorplan === target.id && (cur.device || cur.id) === id)) {
      ctx.select({type: 'marker', id: id, floorplan: target.id, device: id});
    }
    S.sel = id;
    renderMarkers();
    showPop(id);
  }

  return {
    destroy: function () {
      S.destroyed = true;
      if (syncTimer) clearTimeout(syncTimer);
      if (refetchTimer) clearTimeout(refetchTimer);
      clearLongPress();
      offs.forEach(function (off) { off(); });
      if (resizeObs) resizeObs.disconnect();
      if (toolbarObs) toolbarObs.disconnect();
      if (exObserver) exObserver.disconnect();
      if (ex) ex.destroy();
      el.innerHTML = '';
    },
    focus: function (sel) { focusSel(sel, true); },
    // Same-view URL change (D1): plan id, plus explicit marker deep links.
    route: function (r) {
      if (!r || r.view !== 'plan') return;
      if (applyRouteId(r.id)) { ensurePlan(); render(); }
      else scheduleRouteSync();
      const s = (r.query && r.query.sel) || '';
      const changed = s !== S.routeSel;
      S.routeSel = s;
      const sel = store.selection;
      if (changed && sel && sel.type === 'marker') focusSel(sel, true);
    },
    getState: function () { return {fpId: S.fpId, view: S.view}; },
    setState: function (s) {
      if (!s) return;
      // A plan named by the URL wins over the remembered one.
      if (s.fpId && !S.pinned && knownPlan(s.fpId)) S.fpId = s.fpId;
      if (s.view && s.fpId === S.fpId) { S.view = s.view; S.fitted[S.fpId] = true; }
      render();
    },
    // test hooks (harness walkthroughs)
    _state: S,
  };
}
