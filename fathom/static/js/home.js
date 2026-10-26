// Home view (docs/ui-audit.md B.2 HOME): project title, section cards, room
// cards, recents strip and project cards. Every card is a real <a href> from
// ctx.routeHref, so middle-click and copy-link work; ctx.sections is already
// role-filtered by the shell. Data shaping lives in home-core.js.

import { h, on } from './dom.js';
import { emptyState, inlineError, skeleton } from './feedback.js';
import { layoutFor, parseRoute, buildRoute, mergeRoute, sectionsFor, DEFAULT_VIEW } from './router-core.js';
import {
  sectionCards, roomCards, recentStrip, projectCards, recentInput, recentKey, projectTitle, RECENT_TYPES,
} from './home-core.js';

const LEDE = 'Fathom documents this venue\'s audio, video and lighting: what is installed, where it is, and how it is wired.';
const RECENT_GLYPH = { device: '\u25EB', room: '\u25A3', rack: '\u25A3', page: '\u2611' };

function fnOf(ctx, name) {
  return ctx && typeof ctx[name] === 'function' ? ctx[name] : null;
}

function currentRoute(ctx) {
  const r = ctx && ctx.route;
  if (r && typeof r === 'object' && r.project) return r;
  const p = parseRoute(typeof location !== 'undefined' ? location.hash : '');
  if (!p.project) p.project = (ctx && ctx.project) || '';
  if (!p.view) p.view = DEFAULT_VIEW;
  return p;
}

// '#' is makeCtx's harness default for routeHref, i.e. "no router": build the
// href from the current hash instead.
function hrefFor(ctx, partial) {
  const fn = fnOf(ctx, 'routeHref');
  if (fn) {
    const s = fn(partial);
    if (typeof s === 'string' && s && s !== '#') return s;
  }
  return buildRoute(mergeRoute(currentRoute(ctx), partial));
}

function go(ctx, partial) {
  const fn = fnOf(ctx, 'navigateRoute');
  const done = fn ? fn(partial) : '';
  if (!done) location.hash = hrefFor(ctx, partial);
}

function layoutOf(ctx) {
  const fn = fnOf(ctx, 'layout');
  const v = fn ? fn() : null;
  return v === 'sm' || v === 'md' || v === 'lg' ? v : layoutFor(window.innerWidth);
}

function canEdit(ctx) {
  return !(ctx.store && ctx.store.readOnly) && ctx.role !== 'viewer';
}

function readStored(project) {
  try {
    const raw = window.localStorage.getItem(recentKey(project));
    const o = raw ? JSON.parse(raw) : null;
    return o && typeof o === 'object' ? o : {};
  } catch (e) {
    return {};
  }
}

// Recents in the D8 shape: ids from ctx.recent.list(type), times from the
// stored fathom.ui.recent.<project> object (list() returns ids only).
function readRecent(ctx) {
  const stored = readStored(ctx.project || currentRoute(ctx).project);
  const rec = ctx.recent;
  if (!rec || typeof rec.list !== 'function') return recentInput(null, stored);
  const lists = {};
  RECENT_TYPES.forEach(function (type) {
    let ids = [];
    try { ids = rec.list(type) || []; } catch (e) { ids = []; }
    lists[type] = Array.isArray(ids) ? ids : [];
  });
  return recentInput(lists, stored);
}

function sectionsSection(ctx) {
  const secs = Array.isArray(ctx.sections) ? ctx.sections : sectionsFor(ctx.role || 'viewer');
  const cards = sectionCards(secs);
  if (!cards.length) return null;
  return h('section', { class: 'hm-sections', 'aria-labelledby': 'hm-sections-h' }, [
    h('h2', { id: 'hm-sections-h', class: 'sr-only' }, 'Sections'),
    h('div', { class: 'hm-grid' }, cards.map(function (c) {
      return h('a', { class: 'hm-card', 'data-section': c.key, href: hrefFor(ctx, { view: c.view, query: {} }) }, [
        h('span', { class: 'hm-card-glyph', 'aria-hidden': 'true' }, c.glyph),
        h('span', { class: 'hm-card-body' }, [
          h('span', { class: 'hm-card-name' }, c.label),
          h('span', { class: 'hm-card-text' }, c.text),
        ]),
      ]);
    })),
  ]);
}

function roomsSection(ctx, doc, recent) {
  const cards = roomCards(doc, recent, doc.pages || []);
  const body = [h('h2', { id: 'hm-rooms-h', class: 'hm-h' }, 'Rooms')];
  if (!cards.length) {
    const action = canEdit(ctx) ? { label: 'Add a room', run: function () { go(ctx, { view: 'settings', tab: 'rooms', query: {} }); } } : null;
    body.push(emptyState({
      title: 'No rooms yet',
      text: 'Add a room in Settings \u25B8 Rooms, or import a spreadsheet in Data \u25B8 Imports.',
      action: action,
    }));
  } else {
    body.push(h('div', { class: 'hm-room-grid' }, cards.map(function (c) {
      return h('div', { class: 'hm-room', 'data-room': c.id }, [
        h('div', { class: 'hm-room-head' }, [
          h('h3', { class: 'hm-room-name' }, c.name),
          c.code ? h('span', { class: 'hm-room-code' }, c.code) : null,
        ]),
        h('p', { class: 'hm-room-counts' }, c.counts),
        h('nav', { class: 'hm-links', 'aria-label': c.name }, c.links.map(function (l) {
          const partial = { room: c.id, view: l.view, query: {} };
          if (l.id) partial.id = l.id;
          return h('a', { class: 'hm-link', 'data-link': l.key, href: hrefFor(ctx, partial) }, l.label);
        })),
      ]);
    })));
  }
  return h('section', { class: 'hm-rooms', 'aria-labelledby': 'hm-rooms-h' }, body);
}

// Rooms but nothing documented in them yet (a new blank project). Without rooms the rooms
// section carries the empty state instead.
function startSection(ctx, doc) {
  const rooms = doc.rooms || [];
  const devices = (doc.devices || []).filter(function (d) { return d && !d.auto; });
  if (!rooms.length || devices.length || (doc.cables || []).length) return null;
  const edit = canEdit(ctx);
  const room = rooms[0].id;
  return h('section', { class: 'hm-start', 'aria-label': 'Get started' }, emptyState({
    title: 'Nothing here yet',
    text: edit
      ? 'Add a room, then add gear in Patch. A spreadsheet in Data \u25B8 Imports works too.'
      : 'Nobody has documented gear in this project yet.',
    action: edit ? { label: 'Add gear in Patch', href: hrefFor(ctx, { room: room, view: 'patch', query: {} }) } : null,
    secondary: edit ? { label: 'Add a room', href: hrefFor(ctx, { view: 'settings', tab: 'rooms', query: {} }) } : null,
  }));
}

function recentSection(ctx, doc, recent) {
  const items = recentStrip(doc, recent);
  if (!items.length) return null;
  return h('section', { class: 'hm-recent', 'aria-labelledby': 'hm-recent-h' }, [
    h('h2', { id: 'hm-recent-h', class: 'hm-h' }, 'Recent'),
    h('div', { class: 'hm-strip' }, items.map(function (r) {
      return h('a', { class: 'hm-recent', 'data-type': r.type, 'data-id': r.id, href: hrefFor(ctx, r.route) }, [
        h('span', { class: 'hm-recent-glyph', 'aria-hidden': 'true' }, RECENT_GLYPH[r.type] || ''),
        h('span', { class: 'hm-recent-body' }, [
          h('span', { class: 'hm-recent-title' }, r.title),
          h('span', { class: 'hm-recent-kind' }, r.label),
        ]),
      ]);
    })),
  ]);
}

function projectsStatus(ctx) {
  const fn = fnOf(ctx, 'projectsStatus');
  const st = fn ? fn() : null;
  return { loading: !!(st && st.loading), error: (st && st.error) || null };
}

function projectsSection(ctx, layout, retry) {
  let list = Array.isArray(ctx.projects) ? ctx.projects : [];
  const current = ctx.project || currentRoute(ctx).project;
  const st = projectsStatus(ctx);
  if (st.loading || st.error) {
    return h('section', { class: 'hm-projects', 'aria-labelledby': 'hm-projects-h' }, [
      h('h2', { id: 'hm-projects-h', class: 'hm-h' }, 'Projects'),
      st.loading ? skeleton('cards', 2) : inlineError(st.error, retry),
    ]);
  }
  if (!list.length && current) list = [{ name: current, title: projectTitle(ctx.store && ctx.store.doc, current) }];
  const cards = projectCards(list, current);
  if (!cards.length || (cards.length < 2 && layout !== 'sm')) return null;
  return h('section', { class: 'hm-projects', 'aria-labelledby': 'hm-projects-h' }, [
    h('h2', { id: 'hm-projects-h', class: 'hm-h' }, 'Projects'),
    h('div', { class: 'hm-project-grid' }, cards.map(function (p) {
      return h('a', {
        class: 'hm-project', 'data-project': p.name, 'aria-current': p.current ? 'page' : null,
        href: hrefFor(ctx, { project: p.name, room: '', view: 'home', extra: [], query: {} }),
      }, [
        h('span', { class: 'hm-project-title' }, p.title),
        p.org || p.counts ? h('span', { class: 'hm-project-sub' }, [p.org, p.counts].filter(Boolean).join(' \u00b7 ')) : null,
      ]);
    })),
  ]);
}

export function mount(el, ctx) {
  ctx = ctx || {};
  const root = h('div', { class: 'hm-root' });
  el.appendChild(root);
  const offs = [];
  let layout = layoutOf(ctx);
  let pending = false;
  let dead = false;

  function render() {
    pending = false;
    if (dead) return;
    layout = layoutOf(ctx);
    const doc = (ctx.store && ctx.store.doc) || {};
    const recent = readRecent(ctx);
    const meta = doc.meta || {};
    root.innerHTML = '';
    root.appendChild(h('header', { class: 'hm-head' }, [
      meta.org ? h('p', { class: 'hm-kicker' }, String(meta.org)) : null,
      h('h1', { class: 'hm-title' }, projectTitle(doc, ctx.project || currentRoute(ctx).project)),
      h('p', { class: 'hm-lede' }, LEDE),
    ]));
    [startSection(ctx, doc), sectionsSection(ctx), roomsSection(ctx, doc, recent), recentSection(ctx, doc, recent), projectsSection(ctx, layout, retryProjects)]
      .forEach(function (s) { if (s) root.appendChild(s); });
  }

  // Retry for a failed project list: the section shows a skeleton while the request runs, then
  // the cards or the new error. Always resolves, so the Retry button never reports an error itself.
  function retryProjects() {
    const fn = fnOf(ctx, 'reloadProjects');
    if (!fn) return Promise.resolve();
    let p;
    try { p = Promise.resolve(fn()); } catch (e) { p = Promise.reject(e); }
    schedule();
    return p.then(function () { schedule(); }, function () { schedule(); });
  }

  function schedule() {
    if (pending || dead) return;
    pending = true;
    Promise.resolve().then(render);
  }

  function relayout() {
    if (layoutOf(ctx) !== layout) schedule();
  }

  render();
  const setTitle = fnOf(ctx, 'setTitle');
  if (setTitle) setTitle('Home');

  const store = ctx.store;
  if (store && typeof store.addEventListener === 'function') {
    offs.push(on(store, 'doc', schedule));
    offs.push(on(store, 'room', schedule));
  }
  const sub = fnOf(ctx, 'subscribe');
  if (sub) {
    ['layout', 'route'].forEach(function (type) {
      const off = sub(type, type === 'layout' ? relayout : schedule);
      if (typeof off === 'function') offs.push(off);
    });
  }
  offs.push(on(window, 'resize', relayout));

  return {
    route: function () { schedule(); },
    refresh: schedule,
    destroy: function () {
      dead = true;
      offs.forEach(function (off) { try { off(); } catch (e) { /* already removed */ } });
      offs.length = 0;
    },
  };
}
