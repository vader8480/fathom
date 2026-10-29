// Rack export dialog: pick racks, face, format (SVG, PNG at 2x, Print/PDF),
// legend and annotation field, with a live preview. The SVG comes from
// rack-export-core.buildRackSvg; rack-display-core / rack-display are loaded
// when present for block colours, annotation fields and template info.
// openRackExport(ctx, {racks: [ids], face}) -> Promise resolved when the
// dialog closes, with {format, filename, racks, face} of the export made, or
// null when it was cancelled.

import { h, on } from './dom.js';
import * as X from './rack-export-core.js';

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
const CHUNK = 100;
let seq = 0;
let displayP = null;
const imageCache = {};
const infoCache = {};

function safeStorage() {
  try { return window.localStorage; } catch (e) { return null; }
}

function loadPrefs() {
  try {
    const s = safeStorage();
    return X.readPrefs(s ? s.getItem(X.STORAGE_KEY) : null);
  } catch (e) {
    return X.readPrefs(null);
  }
}

function savePrefs(p) {
  try {
    const s = safeStorage();
    if (s) s.setItem(X.STORAGE_KEY, JSON.stringify(X.readPrefs(p)));
  } catch (e) { /* quota or private mode */ }
}

function tryImport(load) {
  try { return load().catch(function () { return null; }); } catch (e) { return Promise.resolve(null); }
}

// {core, dom} of rack-display-core.js / rack-display.js, each null when absent.
function displayModules() {
  if (!displayP) {
    displayP = Promise.all([
      tryImport(function () { return import('./rack-display-core.js'); }),
      tryImport(function () { return import('./rack-display.js'); }),
    ]).then(function (m) { return {core: m[0], dom: m[1]}; });
  }
  return displayP;
}

function announce(text) {
  const live = document.getElementById('fathom-live');
  if (!live || !text) return;
  live.textContent = '';
  setTimeout(function () { live.textContent = text; }, 30);
}

function visible(el) {
  return !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
}

// App root ('…/') for static/rack-images and api paths.
function baseUrl(ctx) {
  const b = ctx.api && typeof ctx.api.base === 'string' ? ctx.api.base : '';
  if (b) return /\/$/.test(b) ? b : b + '/';
  if (typeof ctx.appRoot === 'string' && ctx.appRoot) return /\/$/.test(ctx.appRoot) ? ctx.appRoot : ctx.appRoot + '/';
  const p = location.pathname;
  const i = p.indexOf('/static/');
  return location.origin + (i >= 0 ? p.slice(0, i + 1) : p.replace(/[^/]*$/, ''));
}

function templateInfo(ctx, mods, ids) {
  const scope = String(ctx.project || '') + '\u0000';
  const want = ids.filter(function (id) { return !Object.prototype.hasOwnProperty.call(infoCache, scope + id); });
  const pick = function () {
    const out = {};
    ids.forEach(function (id) { if (infoCache[scope + id]) out[id] = infoCache[scope + id]; });
    return out;
  };
  if (!want.length) return Promise.resolve(pick());
  if (mods.dom && typeof mods.dom.loadTemplateInfo === 'function') {
    return Promise.resolve(mods.dom.loadTemplateInfo(ctx, ids)).then(function (m) { return m || {}; }, function () { return {}; });
  }
  if (!ctx.api || typeof ctx.api.library !== 'function') return Promise.resolve({});
  const chunks = [];
  for (let i = 0; i < want.length; i += CHUNK) chunks.push(want.slice(i, i + CHUNK));
  return Promise.all(chunks.map(function (c) {
    return Promise.resolve(ctx.api.library({ids: c.join(','), project: ctx.project})).then(function (res) {
      const ts = Array.isArray(res) ? res : (res && res.templates) || [];
      const set = {};
      c.forEach(function (id) { set[id] = true; });
      ts.forEach(function (t) { if (t && set[t.id]) infoCache[scope + t.id] = t; });
      c.forEach(function (id) { if (!infoCache[scope + id]) infoCache[scope + id] = null; });
    }, function () { /* no info: plain blocks */ });
  })).then(pick);
}

function blobToDataUrl(blob) {
  return new Promise(function (resolve) {
    const fr = new FileReader();
    fr.onload = function () { resolve(String(fr.result || '')); };
    fr.onerror = function () { resolve(''); };
    fr.readAsDataURL(blob);
  });
}

// Same-origin fetch to a data: URL so the PNG canvas is not tainted; '' on failure.
function imageData(url) {
  if (!imageCache[url]) {
    imageCache[url] = fetch(url, {credentials: 'same-origin'}).then(function (r) {
      if (!r.ok) return '';
      return r.blob().then(function (b) { return /^image\//.test(b.type) ? blobToDataUrl(b) : ''; });
    }).catch(function () { return ''; });
  }
  return imageCache[url];
}

function attachmentUrl(ctx, doc, attId) {
  const att = ((doc && doc.attachments) || []).filter(function (a) { return a && a.id === attId; })[0];
  if (!att || !ctx.project) return '';
  if (ctx.api && typeof ctx.api.fileUrl === 'function') return ctx.api.fileUrl(ctx.project, att);
  return baseUrl(ctx) + 'api/v2/projects/' + encodeURIComponent(ctx.project) + '/files/' + encodeURIComponent(att.id) + '/' + encodeURIComponent(att.name || 'file');
}

// -> Promise<{deviceId: {front?, rear?}}>
function loadImages(ctx, doc, rackIds, face, info) {
  const reqs = X.imageRequests(doc, rackIds, face, info);
  const base = baseUrl(ctx);
  const out = {};
  return Promise.all(reqs.map(function (r) {
    const url = r.att ? attachmentUrl(ctx, doc, r.att) : base + 'static/rack-images/' + r.path.split('/').map(encodeURIComponent).join('/');
    if (!url) return null;
    return imageData(url).then(function (data) {
      if (!data) return;
      out[r.device] = out[r.device] || {};
      out[r.device][r.face] = data;
    });
  })).then(function () { return out; });
}

function svgDataUrl(svg) {
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = h('a', {href: url, download: filename, class: 'rx-dl', hidden: true});
  document.body.appendChild(a);
  a.click();
  setTimeout(function () { a.remove(); URL.revokeObjectURL(url); }, 4000);
}

function svgToPng(svg) {
  const size = X.svgSize(svg);
  const scale = X.pngScale(size.width, size.height, 2);
  return new Promise(function (resolve, reject) {
    const img = new Image();
    img.onload = function () {
      try {
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(size.width * scale);
        canvas.height = Math.round(size.height * scale);
        const g = canvas.getContext('2d');
        g.fillStyle = '#ffffff';
        g.fillRect(0, 0, canvas.width, canvas.height);
        g.drawImage(img, 0, 0, canvas.width, canvas.height);
        canvas.toBlob(function (b) { if (b) resolve(b); else reject(new Error('The PNG could not be created')); }, 'image/png');
      } catch (e) {
        reject(e);
      }
    };
    img.onerror = function () { reject(new Error('The SVG could not be rendered')); };
    img.src = svgDataUrl(svg);
  });
}

function printSvg(svg, title) {
  const old = document.querySelector('iframe.rx-print-frame');
  if (old) old.remove();
  const frame = h('iframe', {class: 'rx-print-frame', title: 'Print preview', 'aria-hidden': 'true', tabindex: '-1'});
  document.body.appendChild(frame);
  const w = frame.contentWindow;
  const d = w.document;
  d.open();
  d.write('<!doctype html><html><head><meta charset="utf-8"><title>' + X.xmlEsc(title) + '</title><style>' +
    '@page{margin:10mm}html,body{margin:0;background:#fff}' +
    'svg{display:block;width:100%;height:auto;max-height:100vh}</style></head><body>' +
    svg.replace(/^<\?xml[^?]*\?>\s*/, '') + '</body></html>');
  d.close();
  let done = false;
  function cleanup() {
    if (done) return;
    done = true;
    setTimeout(function () { frame.remove(); }, 1000);
  }
  w.addEventListener('afterprint', cleanup);
  setTimeout(cleanup, 120000);
  return new Promise(function (resolve, reject) {
    setTimeout(function () {
      try {
        w.focus();
        w.print();
        resolve();
      } catch (e) {
        cleanup();
        reject(e);
      }
    }, 50);
  });
}

function today() {
  const d = new Date();
  const p = function (n) { return (n < 10 ? '0' : '') + n; };
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
}

function radioGroup(name, legendText, choices, value, uid) {
  return h('fieldset', {class: 'rx-group rx-seg', 'data-group': name}, [
    h('legend', {class: 'rx-label'}, legendText),
    h('div', {class: 'rx-seg-row'}, choices.map(function (c) {
      const id = uid + '-' + name + '-' + c.key;
      const input = h('input', {type: 'radio', name: uid + '-' + name, id: id, value: c.key, 'data-field': name, checked: c.key === value});
      return h('label', {class: 'rx-seg-opt', for: id}, [input, h('span', null, c.label)]);
    })),
  ]);
}

export function openRackExport(ctx, opts) {
  ctx = ctx || {};
  opts = opts || {};
  const css = ctx.ensureCss ? Promise.resolve(ctx.ensureCss('rack-export.css')).catch(function () { return null; }) : Promise.resolve();
  return Promise.all([css, displayModules()]).then(function (r) {
    return new Promise(function (resolve) { mount(ctx, opts, r[1], resolve); });
  });
}

function mount(ctx, opts, mods, resolve) {
  const uid = 'rx' + (++seq);
  const opener = document.activeElement;
  const store = ctx.store || {};
  const doc = function () { return store.doc || {}; };
  const racks = ((doc().racks) || []).slice();
  const given = (opts.racks || []).filter(function (id) { return racks.some(function (r) { return r.id === id; }); });
  const prefs = loadPrefs();
  const dcore = mods.core || {};
  const fields = X.normalizeFields(Array.isArray(dcore.ANNOTATION_FIELDS) ? dcore.ANNOTATION_FIELDS : X.BASIC_FIELDS);
  const state = {
    racks: given.length ? given : racks.map(function (r) { return r.id; }),
    face: opts.face === 'front' || opts.face === 'rear' || opts.face === 'both' ? opts.face : prefs.face,
    format: prefs.format,
    legend: prefs.legend,
    annotate: fields.some(function (f) { return f.key === prefs.annotate; }) ? prefs.annotate : '',
    info: {},
    images: {},
  };
  const offs = [];
  let closed = false;
  let busy = false;
  let loadSeq = 0;
  let result = null;

  const title = h('h2', {id: uid + '-title', class: 'rx-title'}, 'Export racks');
  const closeBtn = h('button', {type: 'button', class: 'icon ghost rx-close', 'aria-label': 'Close'}, '\u00d7');

  const rackBoxes = racks.map(function (r) {
    const id = uid + '-rk-' + r.id;
    const cb = h('input', {type: 'checkbox', id: id, value: r.id, 'data-field': 'rack', checked: state.racks.indexOf(r.id) >= 0});
    return h('label', {class: 'rx-rack-opt', for: id}, [cb, h('span', {class: 'rx-rack-name'}, r.name || r.id),
      h('span', {class: 'rx-rack-meta'}, (r.units || 1) + ' U')]);
  });
  const allBtn = h('button', {type: 'button', class: 'small ghost rx-all'}, 'All');
  const noneBtn = h('button', {type: 'button', class: 'small ghost rx-none'}, 'None');
  const rackGroup = h('div', {class: 'rx-group rx-racks', role: 'group', 'aria-labelledby': uid + '-racks'}, [
    h('div', {class: 'rx-racks-head'}, [h('span', {class: 'rx-label', id: uid + '-racks'}, 'Racks'), h('span', {class: 'rx-racks-tools'}, [allBtn, noneBtn])]),
    racks.length ? h('div', {class: 'rx-rack-list'}, rackBoxes) : h('p', {class: 'rx-empty'}, 'This project has no racks yet.'),
  ]);
  const faceGroup = radioGroup('face', 'Face', X.FACE_CHOICES, state.face, uid);
  const formatGroup = radioGroup('format', 'Format', X.FORMATS, state.format, uid);
  const legendBox = h('input', {type: 'checkbox', id: uid + '-legend', 'data-field': 'legend', checked: state.legend});
  const annSel = h('select', {id: uid + '-annotate', 'data-field': 'annotate'}, fields.map(function (f) {
    return h('option', {value: f.key}, f.label);
  }));
  annSel.value = state.annotate;
  const opts2 = h('div', {class: 'rx-group rx-more'}, [
    h('label', {class: 'rx-check', for: uid + '-legend'}, [legendBox, h('span', null, 'Legend')]),
    h('div', {class: 'rx-field'}, [h('label', {class: 'rx-label', for: uid + '-annotate'}, 'Annotation column'), annSel]),
  ]);
  const form = h('form', {class: 'rx-form', novalidate: true}, [rackGroup, faceGroup, formatGroup, opts2]);

  const previewImg = h('img', {class: 'rx-preview-img', alt: 'Preview of the export'});
  const previewMeta = h('p', {class: 'rx-preview-meta', 'aria-live': 'polite'});
  const preview = h('div', {class: 'rx-preview', 'aria-label': 'Preview'}, [h('div', {class: 'rx-preview-frame'}, previewImg), previewMeta]);

  const body = h('div', {class: 'rx-body', id: uid + '-body'}, [form, preview]);
  const msg = h('span', {class: 'rx-msg', 'aria-live': 'polite'});
  const cancelBtn = h('button', {type: 'button', class: 'rx-cancel'}, 'Cancel');
  const goBtn = h('button', {type: 'button', class: 'primary rx-go'}, 'Export');
  const foot = h('div', {class: 'rx-foot'}, [msg, cancelBtn, goBtn]);
  const box = h('div', {class: 'rx', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': uid + '-title'}, [
    h('header', {class: 'rx-head'}, [title, closeBtn]), body, foot,
  ]);
  const backdrop = h('div', {class: 'rx-backdrop app-dialog-backdrop'}, box);

  function svgNow() {
    return X.buildRackSvg(doc(), state.racks, {
      face: state.face, annotate: state.annotate, legend: state.legend, images: state.images, info: state.info,
      vocab: ctx.vocab || store.vocab || {}, title: (doc().meta && doc().meta.title) || ctx.project || '', date: today(), fields: fields,
      blockColor: typeof dcore.blockColor === 'function' ? dcore.blockColor : null,
      annotationValue: typeof dcore.annotationValue === 'function' ? dcore.annotationValue : null,
    });
  }

  function filename(ext) {
    return X.exportFilename(ctx.project || 'fathom', state.racks, state.face, ext);
  }

  function render() {
    if (closed) return;
    const svg = svgNow();
    const size = X.svgSize(svg);
    previewImg.src = svgDataUrl(svg);
    previewImg.setAttribute('width', String(size.width));
    previewImg.setAttribute('height', String(size.height));
    const n = state.racks.length;
    previewMeta.textContent = n ? n + (n === 1 ? ' rack' : ' racks') + ' \u00b7 ' + size.width + ' \u00d7 ' + size.height + ' px' : '';
    const f = X.formatOf(state.format);
    goBtn.textContent = busy ? (f.key === 'print' ? 'Preparing\u2026' : 'Exporting\u2026') : f.action;
    goBtn.disabled = busy || !n;
    if (!busy) msg.textContent = n ? '' : 'Choose at least one rack';
    box.setAttribute('data-format', f.key);
    box.setAttribute('data-face', state.face);
    if (busy) box.setAttribute('aria-busy', 'true'); else box.removeAttribute('aria-busy');
  }

  // Template info and panel images for the current racks and face; re-renders when they arrive.
  function refreshAssets() {
    const mine = ++loadSeq;
    const d = doc();
    const ids = X.templateIds(d, state.racks);
    state.ready = templateInfo(ctx, mods, ids).then(function (info) {
      if (mine !== loadSeq || closed) return;
      state.info = Object.assign({}, state.info, info);
      return loadImages(ctx, d, state.racks, state.face, state.info).then(function (imgs) {
        if (mine !== loadSeq || closed) return;
        state.images = Object.assign({}, state.images, imgs);
        render();
      });
    }).catch(function () { /* export without images */ });
    return state.ready;
  }

  function persist() {
    savePrefs({v: 1, face: state.face, format: state.format, legend: state.legend, annotate: state.annotate});
  }

  function readForm(e) {
    const t = e && e.target;
    const key = t && t.getAttribute && t.getAttribute('data-field');
    if (!key) return;
    if (key === 'rack') {
      state.racks = rackBoxes.map(function (l) { return l.querySelector('input'); }).filter(function (c) { return c.checked; }).map(function (c) { return c.value; });
      refreshAssets();
    } else if (key === 'face' && t.checked) {
      state.face = t.value;
      refreshAssets();
    } else if (key === 'format' && t.checked) {
      state.format = t.value;
    } else if (key === 'legend') {
      state.legend = t.checked;
    } else if (key === 'annotate') {
      state.annotate = t.value;
    }
    persist();
    render();
  }

  function setAll(v) {
    rackBoxes.forEach(function (l) { l.querySelector('input').checked = v; });
    state.racks = v ? racks.map(function (r) { return r.id; }) : [];
    refreshAssets();
    render();
  }

  function run() {
    if (busy || closed || !state.racks.length) return;
    busy = true;
    render();
    const f = X.formatOf(state.format);
    const name = filename(f.ext);
    persist();
    Promise.resolve(state.ready).then(function () {
      const svg = svgNow();
      if (f.key === 'svg') {
        download(new Blob([svg], {type: 'image/svg+xml'}), name);
        return null;
      }
      if (f.key === 'png') return svgToPng(svg).then(function (blob) { download(blob, name); });
      return printSvg(svg, name.replace(/\.pdf$/, ''));
    }).then(function () {
      busy = false;
      result = {format: f.key, filename: name, racks: state.racks.slice(), face: state.face};
      announce(f.key === 'print' ? 'Sent to print' : 'Exported ' + name);
      close();
    }, function (err) {
      busy = false;
      render();
      msg.textContent = (err && err.message) || 'The export failed';
      if (ctx.toast) ctx.toast(msg.textContent, 'err');
    });
  }

  function close() {
    if (closed) return;
    closed = true;
    offs.forEach(function (off) { off(); });
    backdrop.remove();
    document.documentElement.classList.remove('rx-open');
    if (opener && opener.focus && document.contains(opener)) { try { opener.focus(); } catch (e) { /* gone */ } }
    resolve(result);
  }

  function trapTab(e) {
    const f = Array.prototype.filter.call(box.querySelectorAll(FOCUSABLE), visible);
    if (!f.length) { e.preventDefault(); return; }
    const first = f[0];
    const last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || !box.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (document.activeElement === last || !box.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
  }

  function onBoxKey(e) {
    if (e.key === 'Escape') {
      if (e.defaultPrevented) return;
      e.preventDefault();
      if (!busy) close();
    } else if (e.key === 'Tab') {
      trapTab(e);
    } else if (e.key === 'Enter' && e.target && e.target.tagName === 'INPUT' && e.target.type !== 'checkbox' && e.target.type !== 'radio') {
      e.preventDefault();
    }
    e.stopPropagation();
  }

  function onDocKey(e) {
    if (closed || box.contains(e.target)) return;
    if (document.querySelector('#app-dialog .app-dialog-backdrop')) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (!busy) close(); }
    else if (e.key === 'Tab') trapTab(e);
  }

  offs.push(on(box, 'keydown', onBoxKey));
  offs.push(on(document, 'keydown', onDocKey));
  offs.push(on(form, 'change', readForm));
  offs.push(on(form, 'submit', function (e) { e.preventDefault(); }));
  offs.push(on(allBtn, 'click', function () { setAll(true); }));
  offs.push(on(noneBtn, 'click', function () { setAll(false); }));
  offs.push(on(closeBtn, 'click', function () { if (!busy) close(); }));
  offs.push(on(cancelBtn, 'click', function () { if (!busy) close(); }));
  offs.push(on(goBtn, 'click', run));
  offs.push(on(backdrop, 'pointerdown', function (e) { if (e.target === backdrop && !busy) close(); }));

  document.documentElement.classList.add('rx-open');
  document.body.appendChild(backdrop);
  render();
  refreshAssets();
  const first = box.querySelector('.rx-rack-list input:checked') || box.querySelector('.rx-rack-list input') || goBtn;
  try { first.focus(); } catch (e) { /* detached */ }
}
