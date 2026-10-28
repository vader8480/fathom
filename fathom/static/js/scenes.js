// Scene bar (§6.15, FR-SCN): a slim bar under the sub-nav of the patch, table, map, plan, racks
// and rooms views. "Scene:" select of Base + scenes (each with its diff vs Base), a ⋯ actions menu
// (new / save / rename / delete / compare / preview), and a tinted chip while a non-base scene is
// active. The shell (app.js) owns preview mode: ctx.previewScene(sid, name), ctx.exitPreview(),
// ctx.preview. Every surface tolerates a server without scene support (404 → hidden / toast).

import { h } from './dom.js';
import { activeSceneId, sceneDiffText } from './model-core.js';
import { isLockedError } from './api.js';

export const SCENE_VIEWS = ['patch', 'table', 'map', 'plan', 'racks', 'rooms'];
export const UNSUPPORTED_TEXT = 'Scenes need a server with scene support';
const LOCKED_TEXT = 'Editing is locked \u2014 this change was not made';
const REFRESH_DEBOUNCE = 150;

function errMsg(e) {
  return (e && (e.message || String(e))) || 'Unknown error';
}

export function isBase(s) {
  return !s || s.id === 'base' || s.base === true;
}

// The id the server addresses a scene by: 'base' for the Base entry, else its sc-… id.
export function sceneKey(s) {
  return isBase(s) ? 'base' : s.id;
}

export function sceneName(s) {
  return isBase(s) ? 'Base' : (s.name || s.id);
}

// Option text of the select: "<name> — <diff vs base>"; Base reads "Base".
export function optionText(s) {
  if (isBase(s)) return 'Base';
  return sceneName(s) + ' \u2014 ' + (s.text || sceneDiffText(s.diff));
}

function findScene(list, sid) {
  const key = sid || 'base';
  return (list || []).filter(function (s) { return sceneKey(s) === key; })[0] || null;
}

function failure(ctx, e, fallback) {
  if (isLockedError(e)) { ctx.toast(LOCKED_TEXT, 'warn'); return; }
  if (e && e.status === 404) { ctx.toast(UNSUPPORTED_TEXT, 'warn'); return; }
  ctx.toast(fallback ? fallback + ': ' + errMsg(e) : errMsg(e), 'err');
}

function canEdit(ctx) {
  if (typeof ctx.sceneEditor === 'boolean') return ctx.sceneEditor;
  return ctx.role !== 'viewer';
}

function previewOf(ctx) {
  return ctx.preview || null;
}

// ------------------------------------------------------------ menu (same shape as the shell's .app-menu)

function openMenu(anchor, items) {
  const old = document.querySelector('.app-menu');
  if (old) old.remove();
  const menu = h('div', { class: 'app-menu app-scenes-menu', role: 'menu', 'aria-label': 'Scene actions' });
  items.forEach(function (it) {
    if (!it) return;
    if (it.sep) { menu.appendChild(h('div', { class: 'sep', role: 'separator' })); return; }
    menu.appendChild(h('button', {
      type: 'button', role: 'menuitem', id: it.id || null, disabled: !!it.disabled, class: it.danger ? 'danger' : null,
      onclick: function () { close(); it.action(); },
    }, it.label));
  });
  document.body.appendChild(menu);
  const r = anchor.getBoundingClientRect();
  const mw = menu.offsetWidth;
  const mh = menu.offsetHeight;
  let top = r.bottom + 4;
  if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 4);
  menu.style.top = top + 'px';
  menu.style.left = Math.max(8, Math.min(window.innerWidth - mw - 8, r.right - mw)) + 'px';
  anchor.setAttribute('aria-expanded', 'true');
  const first = menu.querySelector('button:not([disabled])');
  if (first) first.focus();
  function close() {
    menu.remove();
    anchor.setAttribute('aria-expanded', 'false');
    document.removeEventListener('pointerdown', outside, true);
    document.removeEventListener('keydown', key, true);
  }
  function outside(e) { if (!menu.contains(e.target)) close(); }
  function key(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); anchor.focus(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const bs = Array.prototype.slice.call(menu.querySelectorAll('button:not([disabled])'));
      const i = bs.indexOf(document.activeElement);
      const n = bs[(i + (e.key === 'ArrowDown' ? 1 : bs.length - 1)) % bs.length];
      if (n) n.focus();
    } else if (e.key === 'Tab') close();
  }
  document.addEventListener('keydown', key, true);
  setTimeout(function () { document.addEventListener('pointerdown', outside, true); }, 0);
  return { close: close, el: menu };
}

// ------------------------------------------------------------ dialogs

function field(id, label, input) {
  return h('div', { class: 'field' }, [h('label', { for: id }, label), input]);
}

// New scene: name (required), note, "Start from" current state | copy of <scene>, "Switch to it now".
export function openNewSceneDialog(ctx, scenes, opts) {
  opts = opts || {};
  const name = h('input', { type: 'text', id: 'scn-name', autocomplete: 'off', maxlength: 80, placeholder: 'e.g. Christmas', autofocus: true });
  const note = h('input', { type: 'text', id: 'scn-note', autocomplete: 'off', placeholder: 'optional' });
  const from = h('select', { id: 'scn-from' }, [h('option', { value: 'current' }, 'Current state')].concat((scenes || []).map(function (s) {
    return h('option', { value: sceneKey(s) }, 'Copy of ' + sceneName(s));
  })));
  const activate = h('input', { type: 'checkbox', id: 'scn-activate' });
  activate.checked = opts.activate !== false;
  return ctx.openDialog({
    title: 'New scene',
    body: h('div', { class: 'scn-form' }, [
      field('scn-name', 'Name', name),
      field('scn-note', 'Note', note),
      field('scn-from', 'Start from', from),
      h('label', { class: 'row scn-check', for: 'scn-activate' }, [activate, 'Switch to it now']),
      h('p', { class: 'muted scn-hint' }, 'A scene keeps its own cables, bundles and gear placement. Everything else stays shared.'),
    ]),
    onOpen: function (d) {
      name.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); const b = d.box.querySelector('footer button.primary'); if (b) b.click(); } });
    },
    buttons: [
      { label: 'Cancel', value: null },
      { label: 'Create', primary: true, validate: function () { if (!name.value.trim()) { ctx.toast('Give the scene a name', 'warn'); name.focus(); return false; } return true; }, value: function () {
        const body = { name: name.value.trim(), note: note.value.trim(), activate: activate.checked };
        if (from.value !== 'current') body.copy_from = from.value;
        return body;
      } },
    ],
  }).then(function (body) { return body || null; });
}

// Rename: name + note of an existing scene.
export function openRenameDialog(ctx, scene) {
  const name = h('input', { type: 'text', id: 'scn-name', autocomplete: 'off', maxlength: 80, value: scene.name || '', autofocus: true });
  const note = h('input', { type: 'text', id: 'scn-note', autocomplete: 'off', value: scene.note || '', placeholder: 'optional' });
  return ctx.openDialog({
    title: 'Rename scene',
    body: h('div', { class: 'scn-form' }, [field('scn-name', 'Name', name), field('scn-note', 'Note', note)]),
    onOpen: function (d) {
      name.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); const b = d.box.querySelector('footer button.primary'); if (b) b.click(); } });
      setTimeout(function () { name.select(); }, 30);
    },
    buttons: [
      { label: 'Cancel', value: null },
      { label: 'Save', primary: true, validate: function () { if (!name.value.trim()) { ctx.toast('Give the scene a name', 'warn'); return false; } return true; }, value: function () { return { name: name.value.trim(), note: note.value.trim() }; } },
    ],
  });
}

// Pick one scene (Preview without switching…, Compare… while Base is active). Resolves sid or null.
export function openPickSceneDialog(ctx, scenes, opts) {
  opts = opts || {};
  const list = (scenes || []).filter(function (s) { return sceneKey(s) !== opts.exclude && (opts.allowBase !== false || !isBase(s)); });
  if (!list.length) { ctx.toast(opts.empty || 'No other scenes yet', 'info'); return Promise.resolve(null); }
  const sel = h('select', { id: 'scn-pick', autofocus: true }, list.map(function (s) { return h('option', { value: sceneKey(s) }, optionText(s)); }));
  return ctx.openDialog({
    title: opts.title || 'Pick a scene',
    body: h('div', { class: 'scn-form' }, [opts.text ? h('p', { class: 'muted', style: { marginTop: '0' } }, opts.text) : null, field('scn-pick', 'Scene', sel)]),
    buttons: [{ label: 'Cancel', value: null }, { label: opts.ok || 'OK', primary: true, value: function () { return sel.value; } }],
  });
}

function deviceName(doc, id) {
  const d = ((doc && doc.devices) || []).filter(function (x) { return x.id === id; })[0];
  return d ? (d.name || d.id) : (id || '?');
}

function endText(doc, end) {
  if (!end || typeof end !== 'object') return '\u2014';
  return deviceName(doc, end.device) + (end.port ? ' : ' + end.port : '');
}

function cableLine(doc, c, cls, extra) {
  return h('li', { class: 'scn-row ' + cls }, [
    h('span', { class: 'scn-tag' }, c.tag || c.id || ''),
    h('span', { class: 'scn-ends' }, endText(doc, c.from) + ' \u2192 ' + endText(doc, c.to)),
    extra ? h('span', { class: 'muted scn-extra' }, extra) : null,
  ]);
}

function changeText(ch) {
  const fields = Array.isArray(ch.fields) && ch.fields.length ? ch.fields : Object.keys(ch.after || {});
  return fields.map(function (f) {
    const b = ch.before && ch.before[f] !== undefined ? ch.before[f] : '\u2014';
    const a = ch.after && ch.after[f] !== undefined ? ch.after[f] : '\u2014';
    return f + ': ' + fmt(b) + ' \u2192 ' + fmt(a);
  }).join(' \u00b7 ');
}

function fmt(v) {
  if (v === null || v === undefined || v === '') return '\u2014';
  if (typeof v === 'object') {
    if (typeof v.x === 'number' && typeof v.y === 'number') return Math.round(v.x) + ',' + Math.round(v.y);
    if (typeof v.device === 'string') return v.device + (v.port ? ':' + v.port : '');
    try { return JSON.stringify(v); } catch (e) { return String(v); }
  }
  return String(v);
}

function section(title, items, render) {
  if (!items || !items.length) return null;
  return h('div', { class: 'scn-sec' }, [h('h4', null, title + ' (' + items.length + ')'), h('ul', { class: 'scn-list' }, items.map(render))]);
}

// Renders a diff dict (§5.6 Scenes GET …/diff) into the two-column (stacked at sm) compare body.
export function renderDiff(doc, diff) {
  diff = diff || {};
  const cables = diff.cables || {};
  const bundles = diff.bundles || {};
  const devices = diff.devices || {};
  const markers = diff.markers || {};
  const left = [
    section('Cables added', cables.added, function (c) { return cableLine(doc, c, 'add'); }),
    section('Cables removed', cables.removed, function (c) { return cableLine(doc, c, 'del'); }),
    section('Cables changed', cables.changed, function (ch) {
      const c = Object.assign({ id: ch.id }, ch.after || ch.before || {});
      return cableLine(doc, c, 'chg', changeText(ch));
    }),
    section('Bundles added', bundles.added, function (b) { return h('li', { class: 'scn-row add' }, b.tag || b.name || b.id || ''); }),
    section('Bundles removed', bundles.removed, function (b) { return h('li', { class: 'scn-row del' }, b.tag || b.name || b.id || ''); }),
    section('Bundles changed', bundles.changed, function (ch) { return h('li', { class: 'scn-row chg' }, [h('span', { class: 'scn-tag' }, ch.id), h('span', { class: 'muted scn-extra' }, changeText(ch))]); }),
  ].filter(Boolean);
  const markerRow = function (cls) {
    return function (mk) { return h('li', { class: 'scn-row ' + cls }, deviceName(doc, mk.device) + ' on ' + (mk.fp || mk.floorplan || '?')); };
  };
  const right = [
    section('Devices moved', devices.moved, function (mv) {
      return h('li', { class: 'scn-row chg' }, [h('span', { class: 'scn-tag' }, deviceName(doc, mv.id)), h('span', { class: 'scn-ends' }, changeText(mv))]);
    }),
    section('Markers added', markers.added, markerRow('add')),
    section('Markers removed', markers.removed, markerRow('del')),
    section('Markers moved', markers.moved, markerRow('chg')),
  ].filter(Boolean);
  const text = diff.text || sceneDiffText(diff.summary || {});
  return h('div', { class: 'scn-diff' }, [
    h('p', { class: 'scn-diff-text' }, text),
    left.length || right.length ? h('div', { class: 'scn-cols' }, [
      h('div', { class: 'scn-col' }, left.length ? left : h('p', { class: 'muted' }, 'Same patch as Base.')),
      h('div', { class: 'scn-col' }, right.length ? right : h('p', { class: 'muted' }, 'Same gear placement as Base.')),
    ]) : null,
  ]);
}

// Compare <scene> with Base. Buttons: Switch to <scene> (editors, when it is not active), Close.
export function openCompareDialog(ctx, scene, opts) {
  opts = opts || {};
  const sid = sceneKey(scene);
  const name = sceneName(scene);
  const body = h('div', { class: 'scn-compare' }, h('p', { class: 'muted scn-loading' }, 'Comparing\u2026'));
  const buttons = [];
  if (opts.canSwitch) buttons.push({ label: 'Switch to ' + name, value: 'switch' });
  buttons.push({ label: 'Close', value: null, primary: true });
  const p = ctx.openDialog({ title: 'Compare ' + name + ' with Base', wide: true, body: body, buttons: buttons });
  if (!ctx.api) {
    body.innerHTML = '';
    body.appendChild(h('p', { class: 'muted' }, UNSUPPORTED_TEXT));
  } else {
    ctx.api.sceneDiff(ctx.project, sid, 'base').then(function (diff) {
      body.innerHTML = '';
      body.appendChild(renderDiff(ctx.store ? ctx.store.doc : null, diff));
    }, function (e) {
      body.innerHTML = '';
      body.appendChild(h('p', { class: 'scn-error', role: 'alert' }, e && e.status === 404 ? UNSUPPORTED_TEXT : errMsg(e)));
    });
  }
  return p;
}

// ------------------------------------------------------------ the bar

export function mountSceneBar(el, ctx) {
  const S = { scenes: null, active: 'base', supported: true, failed: false, token: 0, timer: null, destroyed: false, doc: ctx.store ? ctx.store.doc : null };
  el.classList.add('app-scenes');
  el.setAttribute('role', 'toolbar');
  el.setAttribute('aria-label', 'Scenes');
  el.hidden = true;
  const label = h('label', { class: 'app-scenes-label', for: 'app-scene-select' }, 'Scene:');
  const select = h('select', { id: 'app-scene-select', 'aria-label': 'Scene' });
  const chip = h('span', { class: 'app-scene-chip', hidden: true });
  const menuBtn = h('button', { type: 'button', id: 'app-scene-menu', class: 'icon ghost app-scenes-more', 'aria-label': 'Scene actions', 'aria-haspopup': 'menu', 'aria-expanded': 'false', title: 'Scene actions' }, '\u22ef');
  const status = h('span', { class: 'app-scenes-status muted', hidden: true });
  el.innerHTML = '';
  [label, select, chip, status, h('span', { class: 'grow' }), menuBtn].forEach(function (c) { el.appendChild(c); });

  function scenes() { return S.scenes || []; }
  function current() {
    const pv = previewOf(ctx);
    return pv ? pv.scene : S.active;
  }
  function currentScene() { return findScene(scenes(), current()); }
  function activeEntry() { return findScene(scenes(), S.active); }
  function hasScenes() { return scenes().some(function (s) { return !isBase(s); }); }

  function render() {
    if (S.destroyed) return;
    const editor = canEdit(ctx);
    const pv = previewOf(ctx);
    const show = S.supported && !S.failed && S.scenes !== null && (editor || hasScenes() || !!pv);
    el.hidden = !show;
    el.classList.toggle('app-scenes--active', !pv && S.active !== 'base');
    el.classList.toggle('app-scenes--preview', !!pv);
    if (!show) return;
    select.innerHTML = '';
    const cur = current();
    let have = false;
    scenes().forEach(function (s) {
      const key = sceneKey(s);
      if (key === cur) have = true;
      select.appendChild(h('option', { value: key, selected: key === cur ? true : null }, optionText(s)));
    });
    if (!have && pv) select.appendChild(h('option', { value: cur, selected: true }, pv.name || cur));
    select.value = cur;
    select.title = editor && !pv ? 'Switch scene' : 'Preview scene';
    const act = activeEntry();
    const activeName = act && !isBase(act) ? sceneName(act) : '';
    if (activeName && !pv) {
      chip.textContent = 'Scene ' + activeName;
      chip.title = 'Edits go into scene ' + activeName;
      chip.hidden = false;
    } else {
      chip.hidden = true;
    }
    menuBtn.disabled = false;
  }

  function setStatus(text) {
    status.textContent = text || '';
    status.hidden = !text;
  }

  // GET …/scenes; 404 = a server without scene support (bar hidden), other failures also hide it.
  function refresh() {
    if (S.destroyed) return Promise.resolve(null);
    if (!ctx.api || typeof ctx.api.scenes !== 'function') { S.supported = false; render(); return Promise.resolve(null); }
    const token = ++S.token;
    return Promise.resolve(ctx.api.scenes(ctx.project)).then(function (r) {
      if (S.destroyed || token !== S.token) return null;
      const list = (r && Array.isArray(r.scenes)) ? r.scenes.slice() : [];
      if (!list.some(isBase)) list.unshift({ id: 'base', name: 'Base', base: true });
      S.scenes = list;
      S.active = (r && r.active) || activeSceneId(S.doc);
      S.supported = true;
      S.failed = false;
      render();
      return r;
    }, function (e) {
      if (S.destroyed || token !== S.token) return null;
      S.failed = true;
      if (e && e.status === 404) S.supported = false;
      render();
      return null;
    });
  }

  function refreshSoon() {
    if (S.timer) clearTimeout(S.timer);
    S.timer = setTimeout(function () { S.timer = null; refresh(); }, REFRESH_DEBOUNCE);
  }

  // Server-side change (activate, create, delete…): the doc changed, so reload it, then the list.
  function afterMutation(reload) {
    const p = reload && typeof ctx.reload === 'function' ? Promise.resolve(ctx.reload()).catch(function (e) { ctx.toast(errMsg(e), 'err'); return null; }) : Promise.resolve(null);
    return p.then(function () { return refresh(); });
  }

  function activate(sid, name) {
    setStatus('Switching\u2026');
    select.disabled = true;
    return ctx.api.activateScene(ctx.project, sid).then(function (r) {
      select.disabled = false;
      setStatus('');
      const text = r && r.diff && (r.diff.text || sceneDiffText(r.diff.summary || r.diff));
      ctx.toast('Switched to ' + (name || sid) + (text && text !== 'No differences' ? ' (' + text + ')' : ''), 'ok');
      return afterMutation(true);
    }, function (e) {
      select.disabled = false;
      setStatus('');
      failure(ctx, e, 'Could not switch scene');
      render();
    });
  }

  function preview(sid, name) {
    if (typeof ctx.previewScene !== 'function') { ctx.toast(UNSUPPORTED_TEXT, 'warn'); render(); return Promise.resolve(null); }
    setStatus('Loading preview\u2026');
    return Promise.resolve(ctx.previewScene(sid, name)).then(function () { setStatus(''); render(); }, function (e) { setStatus(''); failure(ctx, e, 'Could not preview'); render(); });
  }

  function onSelect() {
    const sid = select.value;
    const s = findScene(scenes(), sid);
    const name = s ? sceneName(s) : sid;
    const pv = previewOf(ctx);
    if (pv) {
      if (sid === S.active && typeof ctx.exitPreview === 'function') { ctx.exitPreview(); render(); return; }
      preview(sid, name);
      return;
    }
    if (sid === S.active) return;
    if (canEdit(ctx)) activate(sid, name);
    else preview(sid, name);
  }

  function newScene() {
    openNewSceneDialog(ctx, scenes(), {}).then(function (body) {
      if (!body) return null;
      return ctx.api.createScene(ctx.project, body).then(function (r) {
        const sc = (r && r.scene) || {};
        ctx.toast((body.activate ? 'Switched to new scene ' : 'Created scene ') + (sc.name || body.name), 'ok');
        return afterMutation(true);
      }, function (e) { failure(ctx, e, 'Could not create the scene'); });
    });
  }

  function saveCurrent() {
    const act = activeEntry();
    if (!act || isBase(act)) return;
    ctx.api.saveScene(ctx.project, sceneKey(act)).then(function () {
      ctx.toast('Saved the current state into ' + sceneName(act), 'ok');
      return afterMutation(false);
    }, function (e) { failure(ctx, e, 'Could not save the scene'); });
  }

  function rename() {
    const act = activeEntry();
    if (!act || isBase(act)) return;
    openRenameDialog(ctx, act).then(function (v) {
      if (!v) return null;
      return ctx.api.patchScene(ctx.project, sceneKey(act), v).then(function () {
        ctx.toast('Renamed to ' + v.name, 'ok');
        return afterMutation(false);
      }, function (e) { failure(ctx, e, 'Could not rename the scene'); });
    });
  }

  function remove() {
    const act = activeEntry();
    if (!act || isBase(act)) return;
    const name = sceneName(act);
    ctx.confirm('Delete scene "' + name + '"? Its cables and placement are lost; the project goes back to Base.', { danger: true, ok: 'Delete scene', title: 'Delete scene' }).then(function (yes) {
      if (!yes) return null;
      return ctx.api.deleteScene(ctx.project, sceneKey(act)).then(function () {
        ctx.toast('Deleted scene ' + name, 'ok');
        // The server switched to Base when the deleted scene was active: reload the doc either way.
        return afterMutation(true);
      }, function (e) { failure(ctx, e, 'Could not delete the scene'); });
    });
  }

  function compareWith(scene) {
    const editor = canEdit(ctx);
    const key = sceneKey(scene);
    openCompareDialog(ctx, scene, { canSwitch: editor && key !== S.active }).then(function (v) {
      if (v === 'switch') activate(key, sceneName(scene));
    });
  }

  function compare() {
    const cur = currentScene();
    if (cur && !isBase(cur)) { compareWith(cur); return; }
    openPickSceneDialog(ctx, scenes(), { title: 'Compare with Base', ok: 'Compare', exclude: 'base', allowBase: false, empty: 'No scenes to compare yet' }).then(function (sid) {
      const s = sid ? findScene(scenes(), sid) : null;
      if (s) compareWith(s);
    });
  }

  function previewPick() {
    openPickSceneDialog(ctx, scenes(), { title: 'Preview without switching', ok: 'Preview', exclude: current(), text: 'Shows the project as it looks in that scene. Nothing changes until you switch.' }).then(function (sid) {
      const s = sid ? findScene(scenes(), sid) : null;
      if (s) preview(sceneKey(s), sceneName(s));
    });
  }

  function menuItems() {
    const editor = canEdit(ctx);
    const pv = previewOf(ctx);
    const act = activeEntry();
    const named = act && !isBase(act);
    const items = [];
    if (pv) {
      const cur = currentScene();
      if (cur && !isBase(cur)) items.push({ id: 'app-scene-compare', label: 'Compare with base\u2026', action: compare });
      if (editor && pv.scene !== S.active) items.push({ id: 'app-scene-switch', label: 'Switch to ' + (pv.name || pv.scene), action: function () { activate(pv.scene, pv.name); } });
      items.push({ id: 'app-scene-exit', label: 'Exit preview', action: function () { if (typeof ctx.exitPreview === 'function') ctx.exitPreview(); render(); } });
      return items;
    }
    if (editor) {
      items.push({ id: 'app-scene-new', label: 'New scene from current\u2026', action: newScene });
      if (named) {
        items.push({ id: 'app-scene-save', label: 'Save current state into ' + sceneName(act), action: saveCurrent });
        items.push({ id: 'app-scene-rename', label: 'Rename\u2026', action: rename });
        items.push({ id: 'app-scene-delete', label: 'Delete scene\u2026', action: remove, danger: true });
      }
      items.push({ sep: true });
    }
    items.push({ id: 'app-scene-compare', label: 'Compare with base\u2026', action: compare, disabled: !hasScenes() });
    items.push({ id: 'app-scene-preview', label: 'Preview without switching\u2026', action: previewPick, disabled: !hasScenes() });
    return items;
  }

  function openActions() {
    if (el.hidden) return null;
    return openMenu(menuBtn, menuItems());
  }

  select.addEventListener('change', onSelect);
  menuBtn.addEventListener('click', function () { openActions(); });

  function onDoc(e) {
    const d = e.detail || {};
    S.doc = ctx.store.doc;
    if (d.source === 'preview') { render(); return; }
    const touched = d.touched || [];
    const relevant = d.source === 'load' || d.source === 'remote' || d.source === 'pending' || touched.indexOf('settings') >= 0 || touched.some(function (r) { return r.indexOf('scenes/') === 0 || r === 'scenes'; });
    if (relevant) refreshSoon();
    else render();
  }
  function onMode() { render(); }
  if (ctx.store) {
    ctx.store.addEventListener('doc', onDoc);
    ctx.store.addEventListener('mode', onMode);
  }
  refresh();

  return {
    el: el,
    update: function (doc) { S.doc = doc || (ctx.store ? ctx.store.doc : null); render(); },
    refresh: refresh,
    render: render,
    openMenu: openActions,
    newScene: newScene,
    compare: compare,
    // scenes is null until GET …/scenes has answered.
    state: function () { return { scenes: S.scenes, active: S.active, supported: S.supported, failed: S.failed, hidden: el.hidden }; },
    destroy: function () {
      S.destroyed = true;
      if (S.timer) clearTimeout(S.timer);
      if (ctx.store) {
        ctx.store.removeEventListener('doc', onDoc);
        ctx.store.removeEventListener('mode', onMode);
      }
      const menu = document.querySelector('.app-scenes-menu');
      if (menu) menu.remove();
      el.innerHTML = '';
      el.hidden = true;
      el.classList.remove('app-scenes--active', 'app-scenes--preview');
    },
  };
}
