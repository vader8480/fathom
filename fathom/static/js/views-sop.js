// SOP wiki view (§6.4 "sop"): phone-first page tree (drill-down list),
// rendered page viewer with tappable checklists, and a split Markdown editor.
// Rendering happens on the server (fathom/markdown.py); this module only
// fetches HTML and wires interactions. The viewer pieces (renderPageBody,
// applyTaskState) are kept free of app chrome so a public page can reuse them.

import { h, parseHash, buildHash } from './app.js';
import { deviceTitle } from './model-core.js';

const KINDS = [['sop', 'SOP'], ['troubleshooting', 'Troubleshooting'], ['checklist', 'Checklist'], ['reference', 'Reference']];
const STATUSES = [['draft', 'Draft'], ['published', 'Published'], ['archived', 'Archived']];
// Starter templates offered on page create. `{{device}}` becomes a [[device:…]]
// link when the page is started from a device (inspector → Procedures → New).
const TEMPLATES = [
  { id: 'power-up', title: 'System power-up', kind: 'sop', summary: 'Switch the system on in the correct order.', tags: ['power'],
    body: 'Follow the steps in order. Amplifiers always come on **last**.\n\n> [!WARNING]\n> Never power the amps while the console is still booting.\n\n## 1. Power\n\n- [ ] Switch on the main power distribution ({{device}}).\n- [ ] Wait for the network switches to show green link lights.\n\n## 2. Audio\n\n- [ ] Power on the stage boxes, then the console.\n- [ ] Load the house scene and check the master fader is at **-inf**.\n- [ ] Power on the amplifiers.\n\n## 3. Video\n\n- [ ] Power on the switcher, then the displays / projector.\n- [ ] Confirm the programme output appears on the main screen.\n\n## 4. Lighting\n\n- [ ] Power on the lighting console and load the show file.\n- [ ] Run the *house full* cue.\n\n## Done\n\nPlay a track at a low level and walk the room.\n' },
  { id: 'shut-down', title: 'System shut-down', kind: 'sop', summary: 'End-of-day shut-down. Amps first, then console, video, power.', tags: ['power'],
    body: 'The reverse of power-up. Allow 5 minutes.\n\n> [!IMPORTANT]\n> Do not cut power until the projector fan has stopped.\n\n## 1. Audio\n\n- [ ] Pull the master fader to **-inf**.\n- [ ] Power off the amplifiers.\n- [ ] Save the scene if anything changed, then power off the console.\n\n## 2. Video and lighting\n\n- [ ] Power off the projector / displays and wait for the fan to stop.\n- [ ] Power off the switcher.\n- [ ] Set the lighting console to the *work lights* cue, then power it off.\n\n## 3. Power\n\n- [ ] Switch off the power distribution ({{device}}).\n- [ ] Lock the rack and return keys.\n' },
  { id: 'no-audio', title: 'Troubleshooting: no audio', kind: 'troubleshooting', summary: 'Work from the stage to the speakers to find where the signal stops.', tags: ['audio', 'troubleshooting'],
    body: 'Start at the top and stop when sound returns.\n\n## 1. Is the console seeing the input?\n\n- [ ] Select the channel and check the input meter is moving.\n- [ ] No meter: check the mic is on and the cable is seated at the stage box.\n- [ ] Still nothing: check the sync LED on the stage box ({{device}}).\n\n## 2. Is the console sending to the PA?\n\n- [ ] Channel fader up and **not muted**?\n- [ ] Channel assigned to the main bus?\n- [ ] Master fader up and the main meters moving?\n\n## 3. Are the amps on?\n\n| Symptom | Check |\n|---|---|\n| No LEDs | Power distribution off, or breaker tripped |\n| *Protect* LED | Power-cycle the amp; if it returns, leave it off and tell the AV lead |\n| *Ready* but no sound | Confirm the amp input / routing |\n\n## 4. Still nothing\n\n> [!CAUTION]\n> Do not change routing during a service.\n\nSwitch to the backup input so the event can continue, then log the fault on the device page.\n' },
  { id: 'no-video', title: 'Troubleshooting: no video', kind: 'troubleshooting', summary: 'Nothing on the screen: source, switcher, display.', tags: ['video', 'troubleshooting'],
    body: 'Check in this order: source → switcher → display.\n\n## 1. Source\n\n- [ ] Is the computer awake and showing the presentation on its own screen?\n- [ ] Is the right output selected (extend / duplicate)?\n- [ ] Reseat the cable at the computer.\n\n## 2. Switcher\n\n- [ ] Does the switcher ({{device}}) show the input as *live*?\n- [ ] Is the correct input selected on programme?\n- [ ] Try another input to prove the output path.\n\n## 3. Display\n\n- [ ] Is the projector / display on and on the right input?\n- [ ] *No signal* message: reseat the cable at the display end.\n- [ ] Lamp or power LED flashing: note the pattern and tell the AV lead.\n\n## Still nothing\n\nSwitch to the backup display path or use the stage monitors so the event can continue.\n' },
  { id: 'weekly-checks', title: 'Weekly checks', kind: 'checklist', summary: 'Five-minute walk-through to catch problems before the weekend.', tags: ['maintenance', 'weekly'],
    body: '## Audio\n\n- [ ] All radio mics on charge; batteries rotated.\n- [ ] Stage box ({{device}}) sync LED solid.\n- [ ] Main PA and fills pass a test track.\n\n## Video\n\n- [ ] Projector lamp hours noted: ____\n- [ ] Lyrics computer updated and rebooted.\n- [ ] Streaming encoder reachable.\n\n## Lighting\n\n- [ ] House and stage cues run without missing fixtures.\n- [ ] Dead lamps / fixtures logged on their device pages.\n\n## Infrastructure\n\n- [ ] UPS shows *normal*; no alarms.\n- [ ] Network switches: no amber link lights.\n- [ ] Racks locked, cables tidy, labels legible.\n' },
];
const KIND_LABEL = {};
KINDS.forEach(function (k) { KIND_LABEL[k[0]] = k[1]; });

function slugify(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80);
}
function pagesOf(doc) { return (doc && doc.pages) || []; }
function bySlug(doc, slug) { return pagesOf(doc).filter(function (p) { return p.slug === slug; })[0] || null; }
function byId(doc, id) { return pagesOf(doc).filter(function (p) { return p.id === id; })[0] || null; }
function orderKey(a, b) {
  const oa = a.order === undefined || a.order === null ? 1e9 : Number(a.order);
  const ob = b.order === undefined || b.order === null ? 1e9 : Number(b.order);
  if (oa !== ob) return oa - ob;
  return String(a.title || '').localeCompare(String(b.title || ''));
}
function childrenOf(doc, parentId) {
  return pagesOf(doc).filter(function (p) { return (p.parent || null) === (parentId || null); }).sort(orderKey);
}
function descendants(doc, id) {
  const out = {};
  const walk = function (pid) { childrenOf(doc, pid).forEach(function (c) { out[c.id] = true; walk(c.id); }); };
  walk(id);
  return out;
}
function refsInBody(body) {
  const out = { devices: [], rooms: [], pages: [] };
  const re = /\[\[(device|room|page):([^\]|]+)(?:\|[^\]]*)?\]\]/g;
  let m;
  while ((m = re.exec(body || ''))) {
    const list = out[m[1] + 's'];
    const v = m[2].trim();
    if (list.indexOf(v) < 0) list.push(v);
  }
  return out;
}
// Pages that refer to a device, explicitly or via [[device:id]] in the body.
export function pagesForDevice(doc, deviceId) {
  return pagesOf(doc).filter(function (p) {
    if ((p.devices || []).indexOf(deviceId) >= 0) return true;
    return refsInBody(p.body).devices.indexOf(deviceId) >= 0;
  }).sort(orderKey);
}
function fmtDate(s) {
  if (!s) return '';
  const d = new Date(s);
  if (isNaN(d.getTime())) return String(s);
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}
function statusBadge(p) {
  const st = p.status || 'published';
  if (st === 'published') return null;
  return h('span', { class: 'sop-badge sop-badge-' + st }, st === 'draft' ? 'Draft' : 'Archived');
}
function kindBadge(p) {
  return h('span', { class: 'sop-kind sop-kind-' + (p.kind || 'sop') }, KIND_LABEL[p.kind || 'sop'] || p.kind);
}
// Review-due badge: overdue, or due within 30 days.
export function reviewState(p, now) {
  if (!p || !p.review_due) return '';
  const due = new Date(p.review_due + (p.review_due.length === 10 ? 'T00:00:00' : ''));
  if (isNaN(due.getTime())) return '';
  const t = now || new Date();
  if (due < t) return 'overdue';
  return (due - t) <= 30 * 86400000 ? 'soon' : '';
}
function reviewBadge(p) {
  const st = reviewState(p);
  if (!st) return null;
  return h('span', { class: 'sop-badge ' + (st === 'overdue' ? 'sop-badge-due' : 'sop-badge-soon'), title: 'Review due ' + fmtDate(p.review_due) }, st === 'overdue' ? 'Review overdue' : 'Review due soon');
}

// ---------------------------------------------------------------- task state

function taskKey(project, slug) { return 'fathom.sop.tasks.' + project + '.' + slug; }
function readTasks(project, slug) {
  try { const v = JSON.parse(sessionStorage.getItem(taskKey(project, slug)) || '[]'); return Array.isArray(v) ? v : []; } catch (e) { return []; }
}
function writeTasks(project, slug, list) {
  try { if (list.length) sessionStorage.setItem(taskKey(project, slug), JSON.stringify(list)); else sessionStorage.removeItem(taskKey(project, slug)); } catch (e) { /* private mode */ }
}
// "Mark complete" for this session (ISO time or ''); the same key the public page uses.
function doneKey(project, slug) { return 'fathom.sop.done.' + project + '.' + slug; }
function readDone(project, slug) { try { return sessionStorage.getItem(doneKey(project, slug)) || ''; } catch (e) { return ''; } }
function writeDone(project, slug, v) { try { if (v) sessionStorage.setItem(doneKey(project, slug), v); else sessionStorage.removeItem(doneKey(project, slug)); } catch (e) { /* private mode */ } }
export function lastCompletion(p) {
  const done = ((p && p.completions) || []).filter(function (c) { return c && c.at; });
  if (!done.length) return null;
  return done.slice().sort(function (a, b) { return String(a.at) < String(b.at) ? 1 : -1; })[0];
}

// Make the rendered checklist interactive; state lives in sessionStorage so a
// reload during a procedure keeps the operator's place. Reusable by the public page.
export function applyTaskState(bodyEl, project, slug, onChange) {
  const boxes = bodyEl.querySelectorAll('input[data-task]');
  const done = readTasks(project, slug);
  Array.prototype.forEach.call(boxes, function (box) {
    box.disabled = false;
    box.checked = done.indexOf(Number(box.getAttribute('data-task'))) >= 0;
    const li = box.closest('li');
    if (li) li.classList.toggle('done', box.checked);
    box.addEventListener('change', function () {
      const n = Number(box.getAttribute('data-task'));
      const cur = readTasks(project, slug).filter(function (x) { return x !== n; });
      if (box.checked) cur.push(n);
      writeTasks(project, slug, cur);
      if (li) li.classList.toggle('done', box.checked);
      if (onChange) onChange(cur.length, boxes.length);
    });
  });
  return { total: boxes.length, done: done.length };
}

// Rendered Markdown body with in-app link handling and tap-to-zoom images.
export function renderPageBody(html, handlers) {
  handlers = handlers || {};
  const body = h('div', { class: 'sop-body md' });
  body.innerHTML = html || '';
  body.addEventListener('click', function (e) {
    const a = e.target.closest ? e.target.closest('a') : null;
    if (a && body.contains(a)) {
      const ref = a.getAttribute('data-ref');
      const href = a.getAttribute('href') || '';
      if (ref && handlers.ref) {
        const i = ref.indexOf(':');
        if (handlers.ref(ref.slice(0, i), ref.slice(i + 1), a) !== false) { e.preventDefault(); return; }
      }
      if (href.charAt(0) === '#' && handlers.anchor) { e.preventDefault(); handlers.anchor(href.slice(1)); return; }
      if (/^https?:/i.test(href)) { a.target = '_blank'; a.rel = 'noopener'; }
      return;
    }
    const img = e.target.closest ? e.target.closest('img') : null;
    if (img && body.contains(img) && handlers.image) { e.preventDefault(); handlers.image(img); }
  });
  return body;
}

function lightbox(img) {
  const box = h('div', { class: 'sop-lightbox', role: 'dialog', 'aria-label': img.alt || 'Image' }, [
    h('img', { src: img.getAttribute('src'), alt: img.alt || '' }),
    h('button', { type: 'button', class: 'sop-lightbox-close', 'aria-label': 'Close' }, '\u00d7'),
    img.alt ? h('div', { class: 'sop-lightbox-cap' }, img.alt) : null,
  ]);
  const close = function () { box.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = function (e) { if (e.key === 'Escape') close(); };
  box.addEventListener('click', close);
  document.addEventListener('keydown', onKey);
  document.body.appendChild(box);
}

// ------------------------------------------------------------------ the view

export function mount(el, ctx) {
  const store = ctx.store;
  const api = ctx.api;
  const project = ctx.project;
  const canEdit = !store.readOnly && ctx.role !== 'viewer';
  const root = h('div', { class: 'sop' });
  el.appendChild(root);
  let token = 0;
  let destroyed = false;
  const state = { parent: null, query: '', kind: '', slug: '', mode: 'tree', archived: false };
  let editor = null;
  const vocab = ctx.vocab || {};

  function narrow() { return window.innerWidth < 700; }
  function params() { return parseHash(location.hash).params; }
  function hashFor(p) { return buildHash(project, store.room, 'sop', p); }
  function go(p) { location.hash = hashFor(p); }
  function openPage(slug) { go({ page: slug }); }
  function openTree() { go({}); }
  function openEditor(slug, extra) { go(Object.assign({ page: slug, edit: 1 }, extra || {})); }
  function openNew(extra) { go(Object.assign({ new: 1 }, extra || {})); }
  function err(e) { ctx.toast((e && e.message) || String(e), 'err'); }
  function user() { return (ctx.session && ctx.session.user && ctx.session.user.username) || ''; }
  function isArchived(p) { return (p.status || 'published') === 'archived'; }
  // Volunteers and viewers never see archived pages; editors find them under the "Archived" filter (or by searching).
  function visible(p, q) {
    const st = p.status || 'published';
    if (st === 'draft') return canEdit;
    if (st === 'archived') return canEdit && (state.archived || !!q);
    return !state.archived;
  }
  function problemsOf(doc) { return (doc && doc.problems) || []; }
  function openProblems(doc) { return problemsOf(doc).filter(function (r) { return (r.status || 'open') === 'open'; }).length; }
  function openProblemsView() { go({ problems: 1 }); }

  // ---------------------------------------------------------- page tree

  function listItem(p, opts) {
    opts = opts || {};
    const kids = childrenOf(store.doc, p.id).length;
    const sub = [kindBadge(p), statusBadge(p), reviewBadge(p)];
    if (p.summary) sub.push(h('span', { class: 'sop-item-sum' }, p.summary));
    const main = h('button', { type: 'button', class: 'sop-item-main', onclick: function () {
      if (kids && narrow() && !opts.flat) { state.parent = p.id; state.query = ''; renderTree(); }
      else openPage(p.slug);
    } }, [
      h('span', { class: 'sop-item-title' }, p.title || p.slug),
      h('span', { class: 'sop-item-sub' }, sub),
    ]);
    const li = h('li', { class: 'sop-item' + (kids ? ' has-kids' : ''), 'data-page': p.slug, style: opts.depth ? { paddingLeft: (opts.depth * 16) + 'px' } : null }, [main]);
    if (kids && narrow() && !opts.flat) li.appendChild(h('span', { class: 'sop-item-count', 'aria-label': kids + ' pages' }, [String(kids), h('span', { class: 'chev', 'aria-hidden': 'true' }, '\u203a')]));
    return li;
  }

  function matches(p, q) {
    if (!q) return true;
    const hay = [p.title, p.slug, p.summary, (p.tags || []).join(' '), p.body].join(' ').toLowerCase();
    return q.split(/\s+/).every(function (w) { return hay.indexOf(w) >= 0; });
  }

  function renderTree() {
    state.mode = 'tree';
    editor = null;
    root.innerHTML = '';
    root.className = 'sop sop-tree';
    const doc = store.doc;
    const q = state.query.trim().toLowerCase();
    const search = h('input', { type: 'search', class: 'sop-search', placeholder: 'Search procedures', 'aria-label': 'Search procedures', value: state.query, autocomplete: 'off' });
    search.addEventListener('input', function () { state.query = search.value; renderList(); });
    const chips = h('div', { class: 'sop-chips', role: 'group', 'aria-label': 'Filter by kind' }, [['', 'All']].concat(KINDS).map(function (k) {
      return h('button', { type: 'button', class: 'chip' + (state.kind === k[0] && !state.archived ? ' on' : ''), 'aria-pressed': state.kind === k[0] && !state.archived ? 'true' : 'false', onclick: function () { state.kind = k[0]; state.archived = false; renderTree(); } }, k[1]);
    }));
    const nArchived = pagesOf(doc).filter(isArchived).length;
    if (canEdit && (nArchived || state.archived)) {
      chips.appendChild(h('button', { type: 'button', class: 'chip sop-chip-archived' + (state.archived ? ' on' : ''), 'data-filter': 'archived', 'aria-pressed': state.archived ? 'true' : 'false', onclick: function () { state.archived = !state.archived; state.kind = ''; renderTree(); } }, 'Archived' + (nArchived ? ' (' + nArchived + ')' : '')));
    }
    const nOpen = openProblems(doc);
    const headMenu = [];
    headMenu.push({ label: 'Problems' + (nOpen ? ' (' + nOpen + ' open)' : ''), action: openProblemsView });
    if (canEdit) {
      headMenu.push({ sep: true });
      headMenu.push({ label: 'Download offline bundle', action: function () { window.open(api.sopBundleUrl(project), '_blank', 'noopener'); } });
    }
    const head = h('div', { class: 'sop-tree-head' }, [
      h('div', { class: 'sop-tree-title' }, [
        h('h2', null, 'Procedures'),
        nOpen ? h('button', { type: 'button', class: 'sop-badge sop-badge-open sop-problems-badge', 'data-action': 'problems', title: nOpen + ' open problem report' + (nOpen > 1 ? 's' : ''), onclick: openProblemsView }, nOpen + ' open') : null,
        h('span', { class: 'grow' }),
        canEdit ? h('button', { type: 'button', class: 'primary', 'data-action': 'new', onclick: function () { openNew(state.parent ? { parent: (byId(doc, state.parent) || {}).slug } : {}); } }, 'New page') : null,
        h('button', { type: 'button', class: 'sop-more', 'aria-label': 'More actions', 'aria-haspopup': 'menu', onclick: function (e) { simpleMenu(e.currentTarget, headMenu); } }, '\u22EF'),
      ]),
      search,
      chips,
    ]);
    root.appendChild(head);
    const listHost = h('div', { class: 'sop-tree-list' });
    root.appendChild(listHost);

    function renderList() {
      listHost.innerHTML = '';
      const all = pagesOf(doc).filter(function (p) { return !state.kind || (p.kind || 'sop') === state.kind; })
        .filter(function (p) { return visible(p, q); });
      if (!all.length) {
        listHost.appendChild(h('div', { class: 'sop-empty' }, [
          h('p', null, state.archived ? 'No archived pages.' : (pagesOf(doc).length ? 'No pages match.' : 'No procedures yet.')),
          canEdit && !pagesOf(doc).length ? h('p', { class: 'muted' }, 'Write the first SOP for this system: power-up, shut-down, or a troubleshooting guide.') : null,
        ]));
        return;
      }
      const ul = h('ul', { class: 'sop-list', role: 'list' });
      const qq = state.query.trim().toLowerCase();
      if (qq || state.archived) {
        const hits = all.filter(function (p) { return matches(p, qq) && (!state.archived || isArchived(p)); }).sort(orderKey);
        if (!hits.length) ul.appendChild(h('li', { class: 'sop-empty' }, 'No pages match "' + state.query.trim() + '"'));
        hits.forEach(function (p) { ul.appendChild(listItem(p, { flat: true })); });
        listHost.appendChild(ul);
        return;
      }
      if (narrow()) {
        if (state.parent) {
          const par = byId(doc, state.parent);
          if (!par) { state.parent = null; renderList(); return; }
          const gp = par.parent ? byId(doc, par.parent) : null;
          listHost.appendChild(h('button', { type: 'button', class: 'sop-back', onclick: function () { state.parent = gp ? gp.id : null; renderTree(); } }, ['\u2039 ', gp ? (gp.title || gp.slug) : 'All procedures']));
          ul.appendChild(h('li', { class: 'sop-item sop-item-parent', 'data-page': par.slug }, [
            h('button', { type: 'button', class: 'sop-item-main', onclick: function () { openPage(par.slug); } }, [
              h('span', { class: 'sop-item-title' }, par.title || par.slug),
              h('span', { class: 'sop-item-sub' }, [kindBadge(par), statusBadge(par), h('span', { class: 'sop-item-sum' }, 'Open this page')]),
            ]),
          ]));
        }
        const allowed = {};
        all.forEach(function (p) { allowed[p.id] = true; });
        childrenOf(doc, state.parent).filter(function (p) { return allowed[p.id]; }).forEach(function (p) { ul.appendChild(listItem(p)); });
      } else {
        const allowed = {};
        all.forEach(function (p) { allowed[p.id] = true; });
        const walk = function (pid, depth) {
          childrenOf(doc, pid).forEach(function (p) {
            if (allowed[p.id]) ul.appendChild(listItem(p, { depth: depth, flat: true }));
            walk(p.id, depth + 1);
          });
        };
        walk(null, 0);
      }
      listHost.appendChild(ul);
    }
    renderList();
    if (!narrow()) {
      // Wide screens: tree on the left, hint on the right until a page is picked.
      const side = h('aside', { class: 'sop-side' }, [head, listHost]);
      root.innerHTML = '';
      root.appendChild(side);
      root.appendChild(h('div', { class: 'sop-main sop-placeholder' }, [h('p', { class: 'muted' }, pagesOf(doc).length ? 'Pick a procedure on the left.' : 'No procedures yet.')]));
    }
  }

  // ---------------------------------------------------------- page viewer

  function refHandler(kind, id) {
    if (kind === 'device') { ctx.openInspector({ type: 'device', id: id, device: id }); return true; }
    if (kind === 'room') { ctx.navigate('patch', { room: id, keepSel: false }); return true; }
    if (kind === 'page') { openPage(id); return true; }
    return false;
  }

  function scrollToHeading(id) {
    const t = root.querySelector('#' + CSS.escape(id));
    if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderPage(slug, data) {
    state.mode = 'page';
    state.slug = slug;
    editor = null;
    const p = data.page;
    const wide = !narrow();
    const main = h('article', { class: 'sop-main sop-page', 'data-page': p.slug, 'aria-labelledby': 'sop-title' });

    const menuItems = [];
    menuItems.push({ label: 'Report a problem', action: function () { reportSheet(p, data); } });
    menuItems.push({ label: 'Print', action: function () { window.print(); } });
    menuItems.push({ label: 'QR label', action: function () { qrDialog(p); } });
    menuItems.push({ label: 'Versions', action: function () { versionsDialog(p); } });
    if (data.tasks) {
      menuItems.push({ sep: true });
      menuItems.push({ label: 'Mark complete', action: function () { markComplete(); } });
      menuItems.push({ label: 'Reset checklist', action: function () { resetChecklist(); } });
    }
    if (canEdit) {
      menuItems.push({ sep: true });
      menuItems.push({ label: 'New child page', action: function () { openNew({ parent: p.slug }); } });
      menuItems.push({ label: 'Duplicate', action: function () { openNew({ from: p.slug }); } });
      menuItems.push({ label: 'Download offline bundle', action: function () { window.open(api.sopBundleUrl(project), '_blank', 'noopener'); } });
      menuItems.push({ sep: true });
      if (isArchived(p)) menuItems.push({ label: 'Restore page', action: function () { restorePage(p); } });
      menuItems.push({ label: isArchived(p) ? 'Delete page' : 'Archive / delete page', danger: true, action: function () { deletePage(p); } });
    }
    let resetChecklist = function () {};
    let markComplete = function () {};
    const topbar = h('div', { class: 'sop-topbar' }, [
      h('button', { type: 'button', class: 'sop-back', 'aria-label': 'Back to procedures', onclick: function () {
        if (p.parent && narrow()) { state.parent = p.parent; }
        openTree();
      } }, ['\u2039 ', wide ? 'Procedures' : (data.breadcrumbs.length ? data.breadcrumbs[data.breadcrumbs.length - 1].title : 'Procedures')]),
      h('span', { class: 'grow' }),
      canEdit ? h('button', { type: 'button', 'data-action': 'edit', onclick: function () { openEditor(p.slug); } }, 'Edit') : null,
      h('button', { type: 'button', class: 'sop-more', 'aria-label': 'More actions', 'aria-haspopup': 'menu', onclick: function (e) { simpleMenu(e.currentTarget, menuItems); } }, '\u22EF'),
    ]);
    main.appendChild(topbar);

    if (data.breadcrumbs.length) {
      main.appendChild(h('nav', { class: 'sop-crumbs', 'aria-label': 'Breadcrumb' }, data.breadcrumbs.map(function (c, i) {
        return h('span', null, [i ? h('span', { class: 'sep', 'aria-hidden': 'true' }, ' / ') : null, h('a', { href: hashFor({ page: c.slug }) }, c.title)]);
      })));
    }
    const headEl = h('header', { class: 'sop-head' }, [
      h('div', { class: 'sop-head-badges' }, [kindBadge(p), statusBadge(p), reviewBadge(p)]),
      h('h1', { id: 'sop-title' }, p.title),
      p.summary ? h('p', { class: 'sop-summary' }, p.summary) : null,
    ]);
    main.appendChild(headEl);
    if (isArchived(p)) {
      main.appendChild(h('div', { class: 'sop-warn', role: 'status' }, ['This page is archived and hidden from volunteers and public links.',
        canEdit ? h('button', { type: 'button', 'data-action': 'restore', onclick: function () { restorePage(p); } }, 'Restore') : null]));
    }
    if (data.missing && data.missing.length && canEdit) {
      main.appendChild(h('div', { class: 'sop-warn', role: 'status' }, 'Broken links: ' + data.missing.join(', ')));
    }

    // "Applies to" chips stay in view while scrolling a long procedure.
    const applies = [];
    (data.links.rooms || []).forEach(function (r) {
      applies.push(h('button', { type: 'button', class: 'chip sop-chip-room', onclick: function () { refHandler('room', r.id); } }, ['\u25A3 ', r.name]));
    });
    (data.links.devices || []).forEach(function (d) {
      applies.push(h('button', { type: 'button', class: 'chip sop-chip-device', 'data-device': d.id, onclick: function () { refHandler('device', d.id); } }, d.name));
    });
    if (applies.length) {
      main.appendChild(h('div', { class: 'sop-applies', 'aria-label': 'Applies to' }, [h('span', { class: 'sop-applies-label' }, 'Applies to'), h('div', { class: 'sop-applies-chips' }, applies)]));
    }

    let progress = null;
    if (data.tasks) {
      progress = h('div', { class: 'sop-progress', role: 'status' });
      main.appendChild(progress);
    }
    if (data.toc && data.toc.length > 1) {
      const toc = h('details', { class: 'sop-toc', open: wide ? true : null }, [
        h('summary', null, 'Contents'),
        h('ol', null, data.toc.map(function (t) {
          return h('li', { class: 'lvl-' + t.level }, h('a', { href: '#' + t.id, onclick: function (e) { e.preventDefault(); scrollToHeading(t.id); } }, t.text));
        })),
      ]);
      main.appendChild(toc);
    }
    const body = renderPageBody(data.html, { ref: refHandler, anchor: scrollToHeading, image: lightbox });
    main.appendChild(body);
    if (data.tasks) {
      // Progress ("3 of 8 done"), "Reset checklist" and "Mark complete". Editors' completions are recorded on the
      // page (who / when, last 20); for viewers the mark lives in sessionStorage like the tick state.
      const note = h('p', { class: 'sop-complete-note', role: 'status' });
      let doneAt = readDone(project, p.slug);
      let completions = (p.completions || []).slice();
      const update = function (done, total) {
        progress.innerHTML = '';
        progress.appendChild(h('span', { class: 'sop-progress-text' }, done + ' of ' + total + ' done'));
        progress.appendChild(h('span', { class: 'sop-progress-bar', 'aria-hidden': 'true' }, h('i', { style: { width: Math.round(100 * done / Math.max(1, total)) + '%' } })));
        progress.appendChild(h('button', { type: 'button', class: 'sop-progress-reset', hidden: !done && !doneAt, onclick: resetChecklist }, 'Reset checklist'));
        progress.appendChild(h('button', { type: 'button', class: 'sop-progress-complete', 'data-action': 'complete', hidden: !!doneAt, onclick: markComplete }, 'Mark complete'));
        note.hidden = !doneAt;
        note.textContent = doneAt ? 'Marked complete at ' + new Date(doneAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + (canEdit ? ' by ' + (user() || 'you') + ' (recorded on the page).' : ' on this device.') : '';
      };
      resetChecklist = function () {
        writeTasks(project, p.slug, []);
        writeDone(project, p.slug, '');
        doneAt = '';
        Array.prototype.forEach.call(body.querySelectorAll('input[data-task]'), function (b) { b.checked = false; const li = b.closest('li'); if (li) li.classList.remove('done'); });
        update(0, data.tasks);
      };
      markComplete = function () {
        const all = [];
        Array.prototype.forEach.call(body.querySelectorAll('input[data-task]'), function (b) { b.checked = true; const li = b.closest('li'); if (li) li.classList.add('done'); all.push(Number(b.getAttribute('data-task'))); });
        writeTasks(project, p.slug, all);
        doneAt = new Date().toISOString();
        writeDone(project, p.slug, doneAt);
        update(all.length, data.tasks);
        if (!canEdit) return;
        api.completePage(project, p.slug).then(function (r) {
          completions = r.completions || completions;
          p.completions = completions;
          paintMeta();
          ctx.toast('Marked complete', 'ok');
          return ctx.reload();
        }, err);
      };
      progress.after(note);
      const st = applyTaskState(body, project, p.slug, update);
      update(st.done, st.total);
    }

    // "Report a problem" is a first-class action on every procedure, not buried in a menu.
    main.appendChild(h('div', { class: 'sop-report' }, h('button', { type: 'button', id: 'sop-report', class: 'sop-report-btn', 'data-action': 'report', onclick: function () { reportSheet(p, data); } }, '\u26A0 Report a problem')));

    if (data.children.length) {
      main.appendChild(h('section', { class: 'sop-related' }, [
        h('h2', null, 'In this section'),
        h('ul', { class: 'sop-list' }, data.children.map(function (c) {
          const cp = bySlug(store.doc, c.slug) || c;
          return h('li', { class: 'sop-item' }, h('a', { class: 'sop-item-main', href: hashFor({ page: c.slug }) }, [h('span', { class: 'sop-item-title' }, c.title), cp.summary ? h('span', { class: 'sop-item-sub' }, cp.summary) : null]));
        })),
      ]));
    }
    if (data.backlinks.length) {
      main.appendChild(h('section', { class: 'sop-related' }, [
        h('h2', null, 'Referenced by'),
        h('ul', { class: 'sop-links' }, data.backlinks.map(function (c) { return h('li', null, h('a', { href: hashFor({ page: c.slug }) }, c.title)); })),
      ]));
    }
    const nav = h('nav', { class: 'sop-prevnext', 'aria-label': 'Previous and next page' }, [
      data.prev ? h('a', { class: 'sop-prev', href: hashFor({ page: data.prev.slug }) }, [h('small', null, '\u2039 Previous'), h('span', null, data.prev.title)]) : h('span'),
      data.next ? h('a', { class: 'sop-next', href: hashFor({ page: data.next.slug }) }, [h('small', null, 'Next \u203a'), h('span', null, data.next.title)]) : h('span'),
    ]);
    main.appendChild(nav);
    const metaEl = h('footer', { class: 'sop-meta' });
    const paintMeta = function () {
      const meta = [];
      if (p.updated) meta.push('Updated ' + fmtDate(p.updated) + (p.updated_by ? ' by ' + p.updated_by : ''));
      if (p.review_due) meta.push('Review due ' + fmtDate(p.review_due));
      if (p.owner && p.owner !== p.updated_by) meta.push('Owner ' + p.owner);
      const last = lastCompletion(p);
      if (last) meta.push('Last completed ' + fmtDate(last.at) + (last.by ? ' by ' + last.by : ''));
      meta.push('r' + data.revision);
      metaEl.textContent = meta.join(' \u00b7 ');
    };
    paintMeta();
    main.appendChild(metaEl);

    root.innerHTML = '';
    root.className = 'sop sop-view';
    if (wide) {
      renderTree();
      const side = root.querySelector('.sop-side');
      root.innerHTML = '';
      root.appendChild(side);
      state.mode = 'page';
      const cur = side.querySelector('[data-page="' + p.slug + '"]');
      if (cur) cur.setAttribute('aria-current', 'page');
    }
    root.appendChild(main);
    main.scrollTop = 0;
  }

  function loadPage(slug) {
    const my = ++token;
    root.innerHTML = '';
    root.appendChild(h('div', { class: 'app-loading' }, 'Loading\u2026'));
    return Promise.resolve(ctx.flush ? ctx.flush() : null).catch(function () { return null; }).then(function () {
      return api.getPage(project, slug);
    }).then(function (data) {
      if (my !== token || destroyed) return;
      renderPage(slug, data);
    }, function (e) {
      if (my !== token || destroyed) return;
      root.innerHTML = '';
      root.className = 'sop';
      root.appendChild(h('div', { class: 'sop-main' }, [
        h('div', { class: 'sop-topbar' }, [h('button', { type: 'button', class: 'sop-back', onclick: openTree }, '\u2039 Procedures')]),
        h('div', { class: 'app-error-card', role: 'alert' }, [h('h3', null, e && e.status === 404 ? 'Page not found' : 'Could not load this page'), h('pre', null, (e && e.message) || String(e))]),
      ]));
    });
  }

  function simpleMenu(anchor, items) {
    const list = h('div', { class: 'sop-menu', role: 'menu' });
    items.forEach(function (it) {
      if (it.sep) { list.appendChild(h('hr')); return; }
      list.appendChild(h('button', { type: 'button', role: 'menuitem', class: it.danger ? 'danger' : null, onclick: function () { close(); it.action(); } }, it.label));
    });
    const back = h('div', { class: 'sop-menu-back' }, list);
    const close = function () { back.remove(); };
    back.addEventListener('click', function (e) { if (e.target === back) close(); });
    const r = anchor.getBoundingClientRect();
    list.style.top = Math.min(window.innerHeight - 40, r.bottom + 4) + 'px';
    list.style.right = Math.max(8, window.innerWidth - r.right) + 'px';
    document.body.appendChild(back);
  }

  function deletePage(p) {
    const kids = childrenOf(store.doc, p.id).length;
    const msg = kids ? 'This page has ' + kids + ' child page' + (kids > 1 ? 's' : '') + '. It will be archived instead of deleted.' : 'Delete "' + p.title + '"? The page stays in the project history.';
    ctx.confirm(msg, { danger: true, ok: kids ? 'Archive' : 'Delete' }).then(function (yes) {
      if (!yes) return;
      if (kids) ctx.commit([{ op: 'merge', coll: 'pages', id: p.id, value: { status: 'archived', updated: new Date().toISOString(), updated_by: user() } }], 'Archive SOP ' + p.title);
      else ctx.commit([{ op: 'del', coll: 'pages', id: p.id }], 'Delete SOP ' + p.title);
      state.parent = p.parent || null;
      openTree();
    });
  }

  // Archived → published again (the editor can switch it to draft afterwards).
  function restorePage(p) {
    ctx.commit([{ op: 'merge', coll: 'pages', id: p.id, value: { status: 'published', updated: new Date().toISOString(), updated_by: user() } }], 'Restore SOP ' + p.title);
    ctx.toast('Restored "' + p.title + '"', 'ok');
    loadPage(p.slug);
  }

  // ---------------------------------------------------------- report a problem

  // Phone-first bottom sheet. Editors' reports also land as a timestamped note on the device (and can set its
  // status); everyone's reports show up as a badge in the inspector and in the Problems list.
  function reportSheet(p, data) {
    const devices = (data && data.links && data.links.devices) || [];
    const sel = h('select', { name: 'device', 'aria-label': 'Device' }, [h('option', { value: '' }, devices.length ? 'Not a specific device' : 'No device picked')].concat(devices.map(function (d) {
      return h('option', { value: d.id, selected: devices.length === 1 ? true : null }, d.name);
    })));
    const text = h('textarea', { name: 'text', rows: 3, required: true, maxlength: 2000, placeholder: 'e.g. No sound from the lectern mic; red light on channel 3', 'aria-label': 'What is wrong?' });
    const photo = h('input', { type: 'file', name: 'photo', accept: 'image/*', capture: 'environment', 'aria-label': 'Photo' });
    const preview = h('img', { class: 'sop-photo-preview', alt: '', hidden: true });
    photo.addEventListener('change', function () {
      const f = photo.files && photo.files[0];
      if (!f || typeof URL === 'undefined' || !URL.createObjectURL) { preview.hidden = true; return; }
      preview.src = URL.createObjectURL(f); preview.hidden = false;
    });
    const statuses = (vocab.statuses || ['installed', 'planned', 'spare', 'retired']);
    const statusSel = canEdit ? h('select', { name: 'device_status', 'aria-label': 'Set device status' }, [h('option', { value: '' }, 'Leave the device status as it is')].concat(statuses.map(function (s) { return h('option', { value: s }, 'Set device status: ' + s); }))) : null;
    const status = h('p', { class: 'sop-sheet-status', role: 'status', 'aria-live': 'polite' });
    const email = (store.doc.settings && store.doc.settings.problem_email) || '';
    const submit = h('button', { type: 'submit', class: 'primary' }, 'Send report');
    const form = h('form', { class: 'sop-sheet-panel', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'sop-sheet-title', novalidate: true }, [
      h('div', { class: 'sop-sheet-grip', 'aria-hidden': 'true' }),
      h('h2', { id: 'sop-sheet-title' }, 'Report a problem'),
      h('div', { class: 'sop-field' }, [h('span', null, 'Device'), sel]),
      h('div', { class: 'sop-field' }, [h('span', null, 'What is wrong?'), text]),
      statusSel ? h('div', { class: 'sop-field' }, [h('span', null, 'Device status'), statusSel]) : null,
      h('div', { class: 'sop-field sop-photo' }, [h('span', null, ['Photo ', h('small', null, '(optional)')]), photo, preview]),
      status,
      h('div', { class: 'sop-sheet-actions' }, [h('button', { type: 'button', class: 'sop-sheet-cancel', onclick: function () { close(); } }, 'Cancel'), submit]),
      email ? h('div', { class: 'sop-sheet-foot' }, h('a', { class: 'sop-sheet-mail', href: 'mailto:' + email, onclick: function (e) {
        const dev = sel.selectedIndex > 0 ? sel.options[sel.selectedIndex].text : '';
        e.currentTarget.href = 'mailto:' + encodeURIComponent(email) + '?subject=' + encodeURIComponent('Problem: ' + p.title) + '&body=' + encodeURIComponent('Procedure: ' + p.title + '\nLink: ' + location.href + (dev ? '\nDevice: ' + dev : '') + '\n\n' + text.value.trim());
      } }, 'Email the AV team instead')) : null,
    ]);
    const sheet = h('div', { class: 'sop-sheet', id: 'sop-sheet' }, [h('div', { class: 'sop-sheet-backdrop', onclick: function () { close(); } }), form]);
    const onKey = function (e) { if (e.key === 'Escape') close(); };
    function close() { sheet.remove(); document.body.classList.remove('sop-sheet-open'); document.removeEventListener('keydown', onKey); }
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!text.value.trim()) { status.textContent = 'Describe the problem first.'; text.focus(); return; }
      const fd = new FormData();
      fd.append('text', text.value.trim());
      fd.append('page', p.slug);
      if (sel.value) fd.append('device', sel.value);
      if (statusSel && statusSel.value) fd.append('device_status', statusSel.value);
      if (photo.files && photo.files[0]) fd.append('photo', photo.files[0], photo.files[0].name || 'photo.jpg');
      submit.disabled = true; status.textContent = 'Sending\u2026';
      api.reportProblem(project, fd).then(function (r) {
        close();
        ctx.toast(r.noted ? 'Problem reported and noted on the device' : 'Problem reported', 'ok');
        return ctx.reload();
      }, function (er) {
        submit.disabled = false;
        status.textContent = 'Could not send (' + ((er && er.message) || er) + ').' + (email ? ' Use the email link instead.' : '');
      });
    });
    document.addEventListener('keydown', onKey);
    document.body.classList.add('sop-sheet-open');
    document.body.appendChild(sheet);
    setTimeout(function () { text.focus(); }, 60);
  }

  // ---------------------------------------------------------- problems list

  function renderProblems() {
    state.mode = 'problems';
    editor = null;
    const doc = store.doc;
    const items = problemsOf(doc).slice().sort(function (a, b) {
      const oa = (a.status || 'open') === 'open' ? 0 : 1, ob = (b.status || 'open') === 'open' ? 0 : 1;
      if (oa !== ob) return oa - ob;
      return String(b.created || '') < String(a.created || '') ? -1 : 1;
    });
    const devName = function (id) { const d = (doc.devices || []).filter(function (x) { return x.id === id; })[0]; return d ? deviceTitle(d) : id; };
    const main = h('div', { class: 'sop-main sop-problems-view' }, [
      h('div', { class: 'sop-topbar' }, [h('button', { type: 'button', class: 'sop-back', onclick: openTree }, '\u2039 Procedures')]),
      h('header', { class: 'sop-head' }, [h('h1', null, 'Problems'), h('p', { class: 'sop-summary' }, openProblems(doc) + ' open \u00b7 ' + items.length + ' total. Reports from procedure pages, QR labels and share links.')]),
    ]);
    if (!items.length) main.appendChild(h('div', { class: 'sop-empty' }, 'No problems reported. Every procedure page has a "Report a problem" button.'));
    const ul = h('ul', { class: 'sop-problems', role: 'list' });
    items.forEach(function (r) {
      const open = (r.status || 'open') === 'open';
      const att = r.attachment ? (doc.attachments || []).filter(function (a) { return a.id === r.attachment; })[0] : null;
      const page = r.page ? bySlug(doc, r.page) : null;
      const meta = [
        h('span', { class: 'sop-badge ' + (open ? 'sop-badge-open' : 'sop-badge-resolved') }, open ? 'Open' : 'Resolved'),
        h('span', null, fmtDate(r.created) + (r.by ? ' \u00b7 ' + r.by : '') + (r.via && r.via !== 'app' ? ' \u00b7 via ' + (r.via === 'share' ? 'share link' : 'public page') : '')),
        r.device ? h('button', { type: 'button', class: 'chip sop-chip-device', onclick: function () { refHandler('device', r.device); } }, devName(r.device)) : null,
        page ? h('a', { class: 'chip', href: hashFor({ page: page.slug }) }, page.title || page.slug) : null,
      ];
      const li = h('li', { class: 'sop-problem' + (open ? '' : ' resolved'), 'data-problem': r.id }, [
        h('div', { class: 'sop-problem-text' }, r.text),
        h('div', { class: 'sop-problem-meta' }, meta),
        att ? h('img', { class: 'sop-problem-photo', src: api.fileUrl(project, att), alt: 'Photo', onclick: function (e) { lightbox(e.currentTarget); } }) : null,
        !open && r.resolved ? h('div', { class: 'muted small' }, 'Resolved ' + fmtDate(r.resolved) + (r.resolved_by ? ' by ' + r.resolved_by : '') + (r.note ? ' \u2014 ' + r.note : '')) : null,
        canEdit ? h('div', { class: 'sop-problem-actions' }, [
          h('button', { type: 'button', 'data-action': open ? 'resolve' : 'reopen', onclick: function () {
            api.patchProblem(project, r.id, { status: open ? 'resolved' : 'open' }).then(function () { return ctx.reload(); }).then(function () { renderProblems(); }, err);
          } }, open ? 'Resolve' : 'Reopen'),
        ]) : null,
      ]);
      ul.appendChild(li);
    });
    main.appendChild(ul);
    root.innerHTML = '';
    root.className = 'sop sop-view';
    if (!narrow()) {
      renderTree();
      const side = root.querySelector('.sop-side');
      root.innerHTML = '';
      root.appendChild(side);
      state.mode = 'problems';
    }
    root.appendChild(main);
  }

  function versionsDialog(p) {
    const list = h('ul', { class: 'sop-versions' }, h('li', { class: 'muted' }, 'Loading\u2026'));
    let dlg = null;
    api.pageVersions(project, p.slug).then(function (r) {
      list.innerHTML = '';
      const vs = r.versions || [];
      if (!vs.length) list.appendChild(h('li', { class: 'muted' }, 'No history yet.'));
      vs.forEach(function (v, i) {
        list.appendChild(h('li', null, [
          h('div', { class: 'sop-version-info' }, [
            h('b', null, 'r' + v.revision + (i === 0 ? ' (current)' : '')),
            h('span', { class: 'muted' }, ' \u00b7 ' + fmtDate(v.time) + ' ' + (v.time ? new Date(v.time).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '') + (v.author ? ' \u00b7 ' + v.author : '')),
            v.summary ? h('div', { class: 'muted small' }, v.summary) : null,
          ]),
          h('div', { class: 'row' }, [
            h('button', { type: 'button', onclick: function () { viewVersion(p, v.revision); } }, 'View'),
            canEdit && i > 0 ? h('button', { type: 'button', onclick: function () {
              ctx.confirm('Restore the content of "' + p.title + '" from r' + v.revision + '? A new revision is created; nothing is lost.').then(function (yes) {
                if (!yes) return;
                api.restorePage(project, p.slug, v.revision, store.revision).then(function () { if (dlg) dlg.close(); return ctx.reload(); }).then(function () { loadPage(p.slug); ctx.toast('Restored from r' + v.revision, 'ok'); }, err);
              });
            } }, 'Restore') : null,
          ]),
        ]));
      });
    }, function (e) { list.innerHTML = ''; list.appendChild(h('li', { class: 'muted' }, (e && e.message) || String(e))); });
    ctx.openDialog({ title: 'Versions of ' + p.title, body: list, onOpen: function (d) { dlg = d; }, buttons: [{ label: 'Close', value: null }] });
  }

  function viewVersion(p, rev) {
    api.pageVersion(project, p.slug, rev).then(function (data) {
      const body = renderPageBody(data.html, { image: lightbox });
      Array.prototype.forEach.call(body.querySelectorAll('input'), function (b) { b.disabled = true; });
      ctx.openDialog({
        title: (data.page.title || p.title) + ' \u00b7 r' + rev,
        body: h('div', { class: 'sop sop-version-view' }, [h('p', { class: 'muted' }, 'Read-only snapshot at revision ' + rev + '.'), body]),
        buttons: [{ label: 'Close', value: null }],
      });
    }, err);
  }

  // ---------------------------------------------------------- QR label

  // QR code for the public page. The code can carry a share link so a phone
  // without a login opens the procedure; "procedures only" links expose nothing else.
  function qrDialog(p) {
    if ((p.status || 'published') !== 'published') {
      ctx.toast('Publish the page first: only published pages have a public URL', 'warn');
      return;
    }
    const sel = h('select', { 'aria-label': 'Link the QR code opens' }, [h('option', { value: '' }, 'Project viewer link (needs a login when login is on)')]);
    const img = h('img', { class: 'sop-qr-img', alt: 'QR code for ' + p.title });
    const urlOut = h('input', { type: 'text', readonly: true, class: 'sop-qr-url', 'aria-label': 'Public URL' });
    const hint = h('div', { class: 'muted small sop-qr-hint' });
    const sheetLinks = h('div', { class: 'row sop-qr-sheets' });
    let shares = [];
    function current() { return sel.value; }
    function refresh() {
      const share = current();
      img.src = api.pageQrUrl(project, p.slug, { share: share, scale: 6 });
      urlOut.value = new URL(api.publicPageUrl(project, p.slug, share), location.href).href;
      sheetLinks.innerHTML = '';
      const rooms = (p.rooms || []).map(function (id) { return (store.doc.rooms || []).filter(function (r) { return r.id === id; })[0]; }).filter(Boolean);
      (rooms.length ? rooms : [null]).forEach(function (r) {
        sheetLinks.appendChild(h('a', { class: 'chip', href: api.pagesQrSheetUrl(project, { room: r ? r.id : '', share: share }), target: '_blank', rel: 'noopener' }, 'QR sheet: ' + (r ? (r.name || r.id) : 'all procedures')));
      });
    }
    img.addEventListener('error', function () { hint.textContent = 'The QR code could not be generated. Set a public URL in Settings so codes point at an address phones can reach.'; });
    img.addEventListener('load', function () { hint.textContent = ''; });
    sel.addEventListener('change', refresh);
    function loadShares() {
      return api.shares(project).then(function (r) {
        shares = r.shares || [];
        while (sel.options.length > 1) sel.remove(1);
        shares.forEach(function (s) {
          sel.appendChild(h('option', { value: s.token }, (s.label || s.token) + (s.scope === 'sop' ? ' (procedures only)' : ' (whole viewer)')));
        });
      }, function () { shares = []; });
    }
    const newShare = canEdit ? h('button', { type: 'button', 'data-action': 'new-sop-share', onclick: function () {
      api.createShare(project, { label: 'Procedure QR labels', scope: 'sop' }).then(function (r) {
        return loadShares().then(function () { sel.value = r.share.token; refresh(); ctx.toast('Procedures-only share link created', 'ok'); });
      }, err);
    } }, 'New procedures-only link') : null;
    const body = h('div', { class: 'sop-qr' }, [
      h('div', { class: 'sop-qr-code' }, img),
      h('div', { class: 'sop-field' }, [h('label', { for: 'sop-qr-sel' }, 'Opens'), sel, hint]),
      h('div', { class: 'sop-field' }, [h('label', { for: 'sop-qr-url' }, 'URL'), urlOut]),
      h('div', { class: 'row' }, [
        h('a', { class: 'chip', href: '#', 'data-action': 'download-svg', onclick: function (e) { e.preventDefault(); window.open(api.pageQrUrl(project, p.slug, { share: current(), scale: 8 }), '_blank', 'noopener'); } }, 'Open SVG'),
        h('a', { class: 'chip', href: urlOut.value || '#', target: '_blank', rel: 'noopener', onclick: function (e) { e.currentTarget.href = urlOut.value; } }, 'Open public page'),
        newShare,
      ]),
      h('div', { class: 'muted small' }, 'Print a sheet of labels for every published procedure in a room:'),
      sheetLinks,
    ]);
    sel.id = 'sop-qr-sel'; urlOut.id = 'sop-qr-url';
    loadShares().then(function () {
      const sop = shares.filter(function (s) { return s.scope === 'sop'; })[0];
      if (sop) sel.value = sop.token;
      refresh();
    });
    refresh();
    ctx.openDialog({ title: 'QR label \u00b7 ' + p.title, body: body, buttons: [{ label: 'Close', value: null }] });
  }

  // ---------------------------------------------------------- editor

  function draftKey(id) { return 'fathom.sop.draft.' + project + '.' + id; }
  function readDraft(id) { try { return JSON.parse(localStorage.getItem(draftKey(id)) || 'null'); } catch (e) { return null; } }
  function writeDraft(id, v) { try { if (v) localStorage.setItem(draftKey(id), JSON.stringify(v)); else localStorage.removeItem(draftKey(id)); } catch (e) { /* ignore */ } }

  function newPageFrom(q) {
    const doc = store.doc;
    const parent = q.get('parent') ? bySlug(doc, q.get('parent')) : null;
    const from = q.get('from') ? bySlug(doc, q.get('from')) : null;
    const dev = q.get('device') || '';
    const page = {
      id: 'pg-' + Math.random().toString(16).slice(2, 10),
      slug: '', title: '', kind: parent && parent.kind === 'troubleshooting' ? 'troubleshooting' : 'sop', status: 'draft',
      parent: parent ? parent.id : null, summary: '', tags: [], rooms: [], devices: [], body: '',
    };
    if (from) {
      ['kind', 'summary', 'tags', 'rooms', 'devices', 'body', 'parent'].forEach(function (k) { page[k] = Array.isArray(from[k]) ? from[k].slice() : from[k]; });
      page.title = 'Copy of ' + (from.title || from.slug);
      page.slug = slugify(page.title);
    }
    if (dev) {
      const d = (doc.devices || []).filter(function (x) { return x.id === dev; })[0];
      page.devices = [dev];
      if (d && d.room && page.rooms.indexOf(d.room) < 0) page.rooms.push(d.room);
      if (d && !page.title) { page.title = deviceTitle(d) + ': '; }
    }
    return page;
  }

  function renderEditor(page, isNew) {
    state.mode = 'edit';
    const wide = !narrow();
    const doc = store.doc;
    const orig = JSON.parse(JSON.stringify(page));
    const cur = JSON.parse(JSON.stringify(page));
    cur.tags = cur.tags || []; cur.rooms = cur.rooms || []; cur.devices = cur.devices || [];
    let slugTouched = !isNew && !!cur.slug;
    let dirty = false;
    let previewTimer = null;
    let previewSeq = 0;
    editor = { page: cur, dirty: function () { return dirty; } };

    const draft = readDraft(cur.id);
    const main = h('div', { class: 'sop-main sop-editor', 'data-page': cur.slug || 'new' });

    function field(label, input, hint) {
      input.id = input.id || ('sop-f-' + label.toLowerCase().replace(/\W+/g, '-'));
      return h('div', { class: 'sop-field' }, [h('label', { for: input.id }, label), input, hint ? h('div', { class: 'muted small' }, hint) : null]);
    }
    function mark() { dirty = true; writeDraft(cur.id, cur); status.textContent = 'Unsaved changes'; }

    const title = h('input', { type: 'text', value: cur.title, placeholder: 'Power-up: Main Auditorium', autocomplete: 'off', required: true });
    const slugIn = h('input', { type: 'text', value: cur.slug, placeholder: 'power-up', pattern: '[a-z0-9][a-z0-9-]{0,79}', autocomplete: 'off', spellcheck: 'false', autocapitalize: 'off' });
    title.addEventListener('input', function () { cur.title = title.value; if (!slugTouched) { cur.slug = slugify(title.value); slugIn.value = cur.slug; } mark(); });
    slugIn.addEventListener('input', function () { slugTouched = true; cur.slug = slugIn.value.trim().toLowerCase(); mark(); });
    const kindSel = h('select', null, KINDS.map(function (k) { return h('option', { value: k[0], selected: (cur.kind || 'sop') === k[0] ? true : null }, k[1]); }));
    kindSel.addEventListener('change', function () { cur.kind = kindSel.value; mark(); });
    const statusSel = h('select', null, STATUSES.map(function (k) { return h('option', { value: k[0], selected: (cur.status || 'draft') === k[0] ? true : null }, k[1]); }));
    statusSel.addEventListener('change', function () { cur.status = statusSel.value; mark(); });
    const forbidden = isNew ? {} : descendants(doc, cur.id);
    forbidden[cur.id] = true;
    const parentSel = h('select', null, [h('option', { value: '' }, '\u2014 top level \u2014')].concat(pagesOf(doc).filter(function (p) { return !forbidden[p.id]; }).sort(orderKey).map(function (p) {
      return h('option', { value: p.id, selected: cur.parent === p.id ? true : null }, p.title || p.slug);
    })));
    parentSel.addEventListener('change', function () { cur.parent = parentSel.value || null; mark(); });
    const summary = h('input', { type: 'text', value: cur.summary || '', placeholder: 'One line shown in lists', autocomplete: 'off' });
    summary.addEventListener('input', function () { cur.summary = summary.value; mark(); });
    const tags = h('input', { type: 'text', value: cur.tags.join(', '), placeholder: 'power, sunday', autocomplete: 'off' });
    tags.addEventListener('input', function () { cur.tags = tags.value.split(',').map(function (s) { return s.trim(); }).filter(Boolean); mark(); });
    const review = h('input', { type: 'date', value: cur.review_due || '' });
    review.addEventListener('change', function () { cur.review_due = review.value || null; mark(); });

    const roomChips = h('div', { class: 'sop-chips' });
    function renderRooms() {
      roomChips.innerHTML = '';
      (doc.rooms || []).forEach(function (r) {
        const on = cur.rooms.indexOf(r.id) >= 0;
        roomChips.appendChild(h('button', { type: 'button', class: 'chip' + (on ? ' on' : ''), 'aria-pressed': on ? 'true' : 'false', onclick: function () {
          if (on) cur.rooms = cur.rooms.filter(function (x) { return x !== r.id; }); else cur.rooms.push(r.id);
          mark(); renderRooms();
        } }, r.name || r.id));
      });
    }
    renderRooms();
    const devChips = h('div', { class: 'sop-chips' });
    function renderDevs() {
      devChips.innerHTML = '';
      cur.devices.forEach(function (id) {
        const d = (doc.devices || []).filter(function (x) { return x.id === id; })[0];
        devChips.appendChild(h('span', { class: 'chip on' }, [d ? deviceTitle(d) : id, h('button', { type: 'button', class: 'chip-x', 'aria-label': 'Remove ' + (d ? deviceTitle(d) : id), onclick: function () { cur.devices = cur.devices.filter(function (x) { return x !== id; }); mark(); renderDevs(); } }, '\u00d7')]));
      });
      devChips.appendChild(h('button', { type: 'button', class: 'chip', onclick: function () {
        ctx.pickDevice({ title: 'Add a device this page applies to' }).then(function (id) { if (id && cur.devices.indexOf(id) < 0) { cur.devices.push(id); mark(); renderDevs(); } });
      } }, '+ Add device'));
    }
    renderDevs();

    // ---- body editor + preview
    const ta = h('textarea', { class: 'sop-ta', spellcheck: 'true', 'aria-label': 'Page body (Markdown)', placeholder: '## Steps\n\n- [ ] First step\n- [ ] Second step\n\n> [!WARNING]\n> Things that can go wrong.' });
    ta.value = cur.body || '';
    const preview = h('div', { class: 'sop-preview' }, h('div', { class: 'muted' }, 'Preview appears here.'));
    function insert(before, after, placeholder, block) {
      const s = ta.selectionStart, e = ta.selectionEnd;
      const sel = ta.value.slice(s, e) || placeholder || '';
      let text = before + sel + (after || '');
      let pre = ta.value.slice(0, s);
      if (block && pre && !/\n\n$/.test(pre)) pre += /\n$/.test(pre) ? '\n' : '\n\n';
      ta.value = pre + text + ta.value.slice(e);
      const pos = pre.length + before.length;
      ta.focus();
      ta.setSelectionRange(pos, pos + sel.length);
      onBody();
    }
    function prefixLines(prefix) {
      const s = ta.selectionStart, e = ta.selectionEnd;
      const ls = ta.value.lastIndexOf('\n', s - 1) + 1;
      let le = ta.value.indexOf('\n', e); if (le < 0) le = ta.value.length;
      const lines = ta.value.slice(ls, le).split('\n');
      let n = 0;
      const out = lines.map(function (l) { n++; return (typeof prefix === 'function' ? prefix(n) : prefix) + l; }).join('\n');
      ta.value = ta.value.slice(0, ls) + out + ta.value.slice(le);
      ta.focus();
      ta.setSelectionRange(ls, ls + out.length);
      onBody();
    }
    function onBody() {
      cur.body = ta.value;
      mark();
      if (previewTimer) clearTimeout(previewTimer);
      previewTimer = setTimeout(refreshPreview, 350);
    }
    ta.addEventListener('input', onBody);
    function refreshPreview() {
      const my = ++previewSeq;
      api.previewPage(project, ta.value).then(function (r) {
        if (my !== previewSeq) return;
        preview.innerHTML = '';
        const body = renderPageBody(r.html, { ref: function () { return true; }, anchor: function () {}, image: lightbox });
        Array.prototype.forEach.call(body.querySelectorAll('input'), function (b) { b.disabled = true; });
        preview.appendChild(body);
        if (r.missing && r.missing.length) preview.appendChild(h('div', { class: 'sop-warn' }, 'Broken links: ' + r.missing.join(', ')));
      }, function (e) { preview.innerHTML = ''; preview.appendChild(h('div', { class: 'sop-warn' }, 'Preview failed: ' + ((e && e.message) || e))); });
    }
    function pickFromList(titleText, items) {
      const input = h('input', { type: 'search', class: 'search-input', placeholder: 'Filter', 'aria-label': 'Filter', autofocus: true });
      const list = h('ul', { class: 'pick-list', role: 'listbox' });
      let dlg = null;
      function render() {
        list.innerHTML = '';
        const q = input.value.toLowerCase();
        items.filter(function (it) { return !q || it.label.toLowerCase().indexOf(q) >= 0; }).forEach(function (it) {
          list.appendChild(h('li', { role: 'option', 'data-pick': it.value, onclick: function () { if (dlg) dlg.close(it.value); } }, [it.label, it.sub ? h('span', { class: 'sub' }, it.sub) : null]));
        });
      }
      input.addEventListener('input', render);
      render();
      return ctx.openDialog({ title: titleText, body: h('div', null, [input, list]), onOpen: function (d) { dlg = d; }, buttons: [{ label: 'Cancel', value: null }] });
    }
    const fileIn = h('input', { type: 'file', accept: 'image/*', multiple: true, hidden: true });
    fileIn.addEventListener('change', function () {
      const files = Array.prototype.slice.call(fileIn.files);
      if (!files.length) return;
      ctx.toast('Uploading\u2026');
      api.upload(project, 'files', files, { kind: 'photo' }).then(function (r) {
        (r.attachments || []).forEach(function (a) {
          insert('![' + (a.name || 'image').replace(/\.[^.]+$/, '') + '](att:' + a.id + ')', '', '', true);
          if (!cur.attachments) cur.attachments = [];
          if (cur.attachments.indexOf(a.id) < 0) cur.attachments.push(a.id);
        });
        fileIn.value = '';
        return ctx.reload();
      }).then(function () { ctx.toast('Image added', 'ok'); }, err);
    });
    const tb = function (label, titleText, fn) { return h('button', { type: 'button', title: titleText, 'aria-label': titleText, onclick: fn }, label); };
    const toolbar = h('div', { class: 'sop-toolbar', role: 'toolbar', 'aria-label': 'Formatting' }, [
      tb('H2', 'Heading', function () { insert('## ', '', 'Heading', true); }),
      tb(h('b', null, 'B'), 'Bold', function () { insert('**', '**', 'bold'); }),
      tb(h('i', null, 'I'), 'Italic', function () { insert('*', '*', 'italic'); }),
      tb('\u2611', 'Checklist', function () { prefixLines('- [ ] '); }),
      tb('\u2022', 'Bulleted list', function () { prefixLines('- '); }),
      tb('1.', 'Numbered list', function () { prefixLines(function (n) { return n + '. '; }); }),
      tb('\u26A0', 'Warning callout', function () { insert('> [!WARNING]\n> ', '', 'What can go wrong', true); }),
      tb('\u2318', 'Table', function () { insert('| Column | Column |\n|---|---|\n| ', ' |  |\n', 'cell', true); }),
      h('span', { class: 'sep' }),
      tb('Device', 'Link a device', function () {
        ctx.pickDevice({ title: 'Link a device' }).then(function (id) { if (id) insert('[[device:' + id + ']]'); });
      }),
      tb('Room', 'Link a room', function () {
        pickFromList('Link a room', (doc.rooms || []).map(function (r) { return { value: r.id, label: r.name || r.id }; })).then(function (id) { if (id) insert('[[room:' + id + ']]'); });
      }),
      tb('Page', 'Link a page', function () {
        pickFromList('Link a page', pagesOf(doc).filter(function (p) { return p.id !== cur.id; }).sort(orderKey).map(function (p) { return { value: p.slug, label: p.title || p.slug, sub: KIND_LABEL[p.kind || 'sop'] }; })).then(function (s) { if (s) insert('[[page:' + s + ']]'); });
      }),
      tb('\u{1F5BC}', 'Insert image', function () { fileIn.click(); }),
      fileIn,
    ]);

    const pane = h('div', { class: 'sop-split' }, [
      h('div', { class: 'sop-pane sop-pane-write' }, [toolbar, ta]),
      h('div', { class: 'sop-pane sop-pane-preview' }, [h('div', { class: 'sop-pane-title' }, 'Preview'), preview]),
    ]);
    let tabs = null;
    if (!wide) {
      pane.classList.add('tabbed', 'show-write');
      tabs = h('div', { class: 'sop-tabs', role: 'tablist' }, [
        h('button', { type: 'button', role: 'tab', 'aria-selected': 'true', onclick: function () { pane.classList.add('show-write'); pane.classList.remove('show-preview'); setSel(0); } }, 'Write'),
        h('button', { type: 'button', role: 'tab', 'aria-selected': 'false', onclick: function () { pane.classList.add('show-preview'); pane.classList.remove('show-write'); setSel(1); refreshPreview(); } }, 'Preview'),
      ]);
      const setSel = function (i) { Array.prototype.forEach.call(tabs.children, function (b, j) { b.setAttribute('aria-selected', i === j ? 'true' : 'false'); }); };
    }

    const status = h('span', { class: 'sop-status muted', role: 'status' }, isNew ? 'New page' : '');
    function validate() {
      if (!cur.title.trim()) { ctx.toast('Give the page a title', 'warn'); title.focus(); return false; }
      if (!/^[a-z0-9][a-z0-9-]{0,79}$/.test(cur.slug)) { ctx.toast('Slug must be lowercase letters, digits and dashes', 'warn'); slugIn.focus(); return false; }
      const taken = bySlug(doc, cur.slug);
      if (taken && taken.id !== cur.id) { ctx.toast('Another page already uses the slug "' + cur.slug + '"', 'warn'); slugIn.focus(); return false; }
      return true;
    }
    function save(publish) {
      if (!validate()) return;
      const now = new Date().toISOString();
      const value = {};
      Object.keys(cur).forEach(function (k) { const v = cur[k]; if (v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && !v.length)) value[k] = v; });
      value.title = cur.title.trim();
      value.slug = cur.slug;
      if (publish) value.status = 'published';
      if (!value.status) value.status = 'draft';
      if (!value.kind) value.kind = 'sop';
      if (isNew) {
        value.created = now;
        if (user()) value.owner = value.owner || user();
        const sibs = childrenOf(doc, value.parent || null);
        value.order = sibs.length ? Math.max.apply(null, sibs.map(function (s) { return Number(s.order) || 0; })) + 1 : 1;
      }
      value.updated = now;
      if (user()) value.updated_by = user();
      const r = ctx.commit([{ op: 'put', coll: 'pages', id: cur.id, value: value }], (isNew ? 'Create SOP ' : 'Edit SOP ') + value.title);
      if (r === null) return;
      dirty = false;
      writeDraft(cur.id, null);
      ctx.toast(publish ? 'Published' : 'Saved', 'ok');
      openPage(value.slug);
    }
    function cancel() {
      const leave = function () { writeDraft(cur.id, null); dirty = false; if (isNew) { state.parent = cur.parent || null; openTree(); } else openPage(orig.slug); };
      if (!dirty) { leave(); return; }
      ctx.confirm('Discard unsaved changes?', { danger: true, ok: 'Discard' }).then(function (y) { if (y) leave(); });
    }
    const actions = h('div', { class: 'sop-editor-actions' }, [
      status,
      h('span', { class: 'grow' }),
      h('button', { type: 'button', onclick: cancel }, 'Cancel'),
      h('button', { type: 'button', 'data-action': 'save', onclick: function () { save(false); } }, (cur.status || 'draft') === 'published' ? 'Save' : 'Save draft'),
      (cur.status || 'draft') !== 'published' ? h('button', { type: 'button', class: 'primary', 'data-action': 'publish', onclick: function () { save(true); } }, 'Publish') : null,
    ]);

    main.appendChild(h('div', { class: 'sop-topbar' }, [
      h('button', { type: 'button', class: 'sop-back', onclick: cancel }, '\u2039 ' + (isNew ? 'Procedures' : (orig.title || 'Page'))),
      h('span', { class: 'grow' }),
      !isNew && (orig.status || 'published') === 'published' ? h('button', { type: 'button', 'data-action': 'qr', onclick: function () { qrDialog(orig); } }, 'QR label') : null,
      h('h2', { class: 'sop-editor-title' }, isNew ? 'New page' : 'Edit page'),
    ]));
    if (isNew && !(cur.body || '').trim()) {
      // Starter templates: one tap fills title, kind, summary, tags and body; the author then edits.
      const dev = cur.devices[0] || '';
      const tplBox = h('div', { class: 'sop-templates', role: 'group', 'aria-label': 'Start from a template' }, [
        h('div', { class: 'sop-pane-title' }, 'Start from a template'),
        h('div', { class: 'sop-chips' }, TEMPLATES.map(function (t) {
          return h('button', { type: 'button', class: 'chip', 'data-template': t.id, onclick: function () {
            cur.kind = t.kind; kindSel.value = t.kind;
            if (!cur.title.trim()) cur.title = t.title;
            else if (/:\s*$/.test(cur.title)) cur.title = t.title + ': ' + cur.title.replace(/:\s*$/, '');
            title.value = cur.title;
            if (!slugTouched) { cur.slug = slugify(cur.title); slugIn.value = cur.slug; }
            if (!cur.summary) { cur.summary = t.summary; summary.value = cur.summary; }
            t.tags.forEach(function (tag) { if (cur.tags.indexOf(tag) < 0) cur.tags.push(tag); });
            tags.value = cur.tags.join(', ');
            cur.body = t.body.replace(/ \(\{\{device\}\}\)/g, dev ? ' ([[device:' + dev + ']])' : '').replace(/\{\{device\}\}/g, dev ? '[[device:' + dev + ']]' : 'the device');
            ta.value = cur.body;
            tplBox.remove();
            mark();
            refreshPreview();
            ta.focus();
          } }, [h('span', { class: 'sop-kind sop-kind-' + t.kind }, KIND_LABEL[t.kind]), ' ', t.title]);
        }).concat([h('button', { type: 'button', class: 'chip', onclick: function () { tplBox.remove(); ta.focus(); } }, 'Blank page')])),
      ]);
      main.appendChild(tplBox);
    }
    if (draft && JSON.stringify(draft) !== JSON.stringify(orig)) {
      const bar = h('div', { class: 'sop-warn sop-draft-bar', role: 'status' }, [
        h('span', null, 'You have unsaved changes from an earlier session on this device.'),
        h('button', { type: 'button', onclick: function () {
          Object.keys(draft).forEach(function (k) { cur[k] = draft[k]; });
          cur.tags = cur.tags || []; cur.rooms = cur.rooms || []; cur.devices = cur.devices || [];
          title.value = cur.title || ''; slugIn.value = cur.slug || ''; summary.value = cur.summary || ''; tags.value = cur.tags.join(', '); review.value = cur.review_due || '';
          kindSel.value = cur.kind || 'sop'; statusSel.value = cur.status || 'draft'; parentSel.value = cur.parent || ''; ta.value = cur.body || '';
          renderRooms(); renderDevs(); slugTouched = true; mark(); refreshPreview(); bar.remove();
        } }, 'Restore'),
        h('button', { type: 'button', onclick: function () { writeDraft(cur.id, null); bar.remove(); } }, 'Discard'),
      ]);
      main.appendChild(bar);
    }
    const form = h('form', { class: 'sop-form', onsubmit: function (e) { e.preventDefault(); save(false); } }, [
      h('div', { class: 'sop-form-grid' }, [
        field('Title', title),
        field('Slug', slugIn, 'Used in links: [[page:' + (cur.slug || 'slug') + ']]'),
        field('Kind', kindSel),
        field('Status', statusSel),
        field('Parent', parentSel),
        field('Review due', review),
      ]),
      field('Summary', summary),
      field('Tags', tags),
      h('div', { class: 'sop-field' }, [h('label', null, 'Rooms'), roomChips]),
      h('div', { class: 'sop-field' }, [h('label', null, 'Devices'), devChips]),
    ]);
    main.appendChild(form);
    if (tabs) main.appendChild(tabs);
    main.appendChild(pane);
    main.appendChild(actions);

    root.innerHTML = '';
    root.className = 'sop sop-edit';
    root.appendChild(main);
    if (wide && ta.value) refreshPreview();
    if (isNew) title.focus();
  }

  // ---------------------------------------------------------- routing

  function route() {
    const q = params();
    if (q.get('new')) {
      if (!canEdit) { openTree(); return; }
      renderEditor(newPageFrom(q), true);
      return;
    }
    const slug = q.get('page') || '';
    if (slug && q.get('edit')) {
      if (!canEdit) { openPage(slug); return; }
      const p = bySlug(store.doc, slug);
      if (!p) { loadPage(slug); return; }
      renderEditor(p, false);
      return;
    }
    if (slug) { loadPage(slug); return; }
    if (q.get('problems')) { renderProblems(); return; }
    renderTree();
  }

  function onHash() {
    const r = parseHash(location.hash);
    if (r.view !== 'sop' || r.project !== project) return;
    if (editor && editor.dirty && editor.dirty()) {
      // Keep typing state when the hash changes underneath an unsaved editor.
      const q = r.params;
      if (q.get('edit') && q.get('page') === editor.page.slug) return;
    }
    route();
  }
  function onDoc(e) {
    const d = e.detail || {};
    const touched = function (prefix) { return (d.touched || []).some(function (t) { return t.indexOf(prefix) === 0; }); };
    if (state.mode === 'problems') { if (touched('problems/') || d.source === 'load') renderProblems(); return; }
    if (state.mode !== 'tree') return;
    if (touched('pages/') || touched('problems/') || d.source === 'load') renderTree();
  }
  let resizeTimer = null;
  let wasNarrow = narrow();
  function onResize() {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { if (narrow() !== wasNarrow) { wasNarrow = narrow(); if (state.mode !== 'edit') route(); } }, 150);
  }
  window.addEventListener('hashchange', onHash);
  window.addEventListener('resize', onResize);
  store.addEventListener('doc', onDoc);
  route();

  return {
    destroy: function () {
      destroyed = true;
      window.removeEventListener('hashchange', onHash);
      window.removeEventListener('resize', onResize);
      store.removeEventListener('doc', onDoc);
      if (editor && editor.dirty && editor.dirty()) writeDraft(editor.page.id, editor.page);
    },
    getState: function () { return { parent: state.parent, query: state.query, kind: state.kind }; },
    setState: function (s) {
      if (!s) return;
      state.parent = s.parent || null; state.query = s.query || ''; state.kind = s.kind || '';
      if (state.mode === 'tree') renderTree();
    },
  };
}
