// SOP wiki view (§6.4 "sop"): phone-first page tree (drill-down list),
// rendered page viewer with tappable checklists, and a split Markdown editor.
// Rendering happens on the server (fathom/markdown.py); this module only
// fetches HTML and wires interactions. The viewer pieces (renderPageBody,
// applyTaskState) are kept free of app chrome so a public page can reuse them.

import { h, parseHash, buildHash } from './app.js';
import { deviceTitle } from './model-core.js';

const KINDS = [['sop', 'SOP'], ['troubleshooting', 'Troubleshooting'], ['checklist', 'Checklist'], ['reference', 'Reference']];
const STATUSES = [['draft', 'Draft'], ['published', 'Published'], ['archived', 'Archived']];
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

// ---------------------------------------------------------------- task state

function taskKey(project, slug) { return 'fathom.sop.tasks.' + project + '.' + slug; }
function readTasks(project, slug) {
  try { const v = JSON.parse(sessionStorage.getItem(taskKey(project, slug)) || '[]'); return Array.isArray(v) ? v : []; } catch (e) { return []; }
}
function writeTasks(project, slug, list) {
  try { if (list.length) sessionStorage.setItem(taskKey(project, slug), JSON.stringify(list)); else sessionStorage.removeItem(taskKey(project, slug)); } catch (e) { /* private mode */ }
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
  const state = { parent: null, query: '', kind: '', slug: '', mode: 'tree' };
  let editor = null;

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

  // ---------------------------------------------------------- page tree

  function listItem(p, opts) {
    opts = opts || {};
    const kids = childrenOf(store.doc, p.id).length;
    const sub = [kindBadge(p), statusBadge(p)];
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
      return h('button', { type: 'button', class: 'chip' + (state.kind === k[0] ? ' on' : ''), 'aria-pressed': state.kind === k[0] ? 'true' : 'false', onclick: function () { state.kind = k[0]; renderTree(); } }, k[1]);
    }));
    const head = h('div', { class: 'sop-tree-head' }, [
      h('div', { class: 'sop-tree-title' }, [
        h('h2', null, 'Procedures'),
        h('span', { class: 'grow' }),
        canEdit ? h('button', { type: 'button', class: 'primary', 'data-action': 'new', onclick: function () { openNew(state.parent ? { parent: (byId(doc, state.parent) || {}).slug } : {}); } }, 'New page') : null,
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
        .filter(function (p) { return canEdit || (p.status || 'published') !== 'draft'; })
        .filter(function (p) { return (p.status || 'published') !== 'archived' || q; });
      if (!all.length) {
        listHost.appendChild(h('div', { class: 'sop-empty' }, [
          h('p', null, pagesOf(doc).length ? 'No pages match.' : 'No procedures yet.'),
          canEdit && !pagesOf(doc).length ? h('p', { class: 'muted' }, 'Write the first SOP for this system: power-up, shut-down, or a troubleshooting guide.') : null,
        ]));
        return;
      }
      const ul = h('ul', { class: 'sop-list', role: 'list' });
      const qq = state.query.trim().toLowerCase();
      if (qq) {
        const hits = all.filter(function (p) { return matches(p, qq); }).sort(orderKey);
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
    menuItems.push({ label: 'Versions', action: function () { versionsDialog(p); } });
    if (canEdit) {
      menuItems.push({ label: 'New child page', action: function () { openNew({ parent: p.slug }); } });
      menuItems.push({ label: 'Duplicate', action: function () { openNew({ from: p.slug }); } });
      menuItems.push({ sep: true });
      menuItems.push({ label: (p.status || 'published') === 'archived' ? 'Delete page' : 'Archive / delete page', danger: true, action: function () { deletePage(p); } });
    }
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
      h('div', { class: 'sop-head-badges' }, [kindBadge(p), statusBadge(p), p.review_due && new Date(p.review_due) < new Date() ? h('span', { class: 'sop-badge sop-badge-due' }, 'Review overdue') : null]),
      h('h1', { id: 'sop-title' }, p.title),
      p.summary ? h('p', { class: 'sop-summary' }, p.summary) : null,
    ]);
    main.appendChild(headEl);
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
      const update = function (done, total) {
        progress.innerHTML = '';
        progress.appendChild(h('span', { class: 'sop-progress-text' }, done + ' of ' + total + ' done'));
        progress.appendChild(h('span', { class: 'sop-progress-bar', 'aria-hidden': 'true' }, h('i', { style: { width: Math.round(100 * done / Math.max(1, total)) + '%' } })));
        progress.appendChild(h('button', { type: 'button', class: 'sop-progress-reset', hidden: !done, onclick: function () {
          writeTasks(project, p.slug, []);
          Array.prototype.forEach.call(body.querySelectorAll('input[data-task]'), function (b) { b.checked = false; const li = b.closest('li'); if (li) li.classList.remove('done'); });
          update(0, total);
        } }, 'Reset'));
      };
      const st = applyTaskState(body, project, p.slug, update);
      update(st.done, st.total);
    }

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
    const meta = [];
    if (p.updated) meta.push('Updated ' + fmtDate(p.updated) + (p.updated_by ? ' by ' + p.updated_by : ''));
    if (p.review_due) meta.push('Review due ' + fmtDate(p.review_due));
    if (p.owner && p.owner !== p.updated_by) meta.push('Owner ' + p.owner);
    meta.push('r' + data.revision);
    main.appendChild(h('footer', { class: 'sop-meta' }, meta.join(' \u00b7 ')));

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
      if (!page.body) page.body = '## Steps\n\n- [ ] On [[device:' + dev + ']], \u2026\n';
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
      h('h2', { class: 'sop-editor-title' }, isNew ? 'New page' : 'Edit page'),
    ]));
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
    if (state.mode !== 'tree') return;
    if ((d.touched || []).some(function (t) { return t.indexOf('pages/') === 0; }) || d.source === 'load') renderTree();
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
