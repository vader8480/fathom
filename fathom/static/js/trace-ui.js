// Trace-path drawer (SPEC §6.8.7): a phone-first sheet that shows the end-to-end
// signal path for a console channel, a port or a device, backed by
// GET …/trace. Used by the editor inspector and by the public device page, so
// it has no dependency on app.js. ES2018.

import { chainOf, viaText, pathsText } from './console-core.js';

function h(tag, attrs, children) {
  const el = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (v === undefined || v === null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.indexOf('on') === 0 && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, String(v));
    });
  }
  (Array.isArray(children) ? children : (children == null ? [] : [children])).forEach(function (c) {
    if (c === null || c === undefined || c === false) return;
    el.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
  });
  return el;
}

function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
  return new Promise(function (resolve, reject) {
    const ta = h('textarea', { style: 'position:fixed;opacity:0', 'aria-hidden': 'true' });
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); resolve(); } catch (e) { reject(e); } finally { ta.remove(); }
  });
}

const HOP_KIND = { channel: 'console', port_channel: 'stream', dca: 'control', text: 'note' };

export function renderPaths(paths, o) {
  o = o || {};
  const out = h('div', { class: 'trace-paths' });
  if (!paths || !paths.length) {
    out.appendChild(h('div', { class: 'trace-empty' }, o.emptyText || 'No path found.'));
    return out;
  }
  paths.forEach(function (p, pi) {
    const chain = chainOf(p);
    const ol = h('ol', { class: 'trace-chain' }, chain.map(function (grp) {
      return h('li', { class: 'trace-dev', 'data-device': grp.device }, [
        h('div', { class: 'trace-dev-name' }, grp.name),
        h('ul', { class: 'trace-hops' }, grp.hops.map(function (s) {
          const hop = s.hop;
          const row = h('li', { class: 'trace-hop' + (hop.kind ? ' k-' + hop.kind : '') + (hop.control ? ' control' : ''), 'data-ref': hopRef(hop) }, [
            s.via ? h('span', { class: 'trace-via', title: s.via }, viaText(s.via)) : h('span', { class: 'trace-via start' }, pi === 0 && !s.via ? 'start' : ''),
            h('span', { class: 'trace-hop-label' }, s.label || '\u2014'),
            hop.kind && HOP_KIND[hop.kind] ? h('span', { class: 'trace-kind' }, HOP_KIND[hop.kind]) : null,
          ]);
          if (o.onHop) {
            row.classList.add('clickable');
            row.setAttribute('tabindex', '0');
            row.setAttribute('role', 'button');
            row.addEventListener('click', function () { o.onHop(hop); });
            row.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); o.onHop(hop); } });
          }
          return row;
        })),
      ]);
    }));
    const box = h('section', { class: 'trace-path' + (p.incomplete ? ' incomplete' : ''), 'aria-label': 'Path ' + (pi + 1) }, [
      paths.length > 1 ? h('div', { class: 'trace-path-n' }, 'Path ' + (pi + 1) + ' of ' + paths.length) : null,
      ol,
      p.incomplete ? h('div', { class: 'trace-gap', role: 'note' }, ['\u26A0 ', p.incomplete]) : null,
    ]);
    out.appendChild(box);
  });
  return out;
}

function hopRef(hop) {
  if (!hop) return '';
  if (hop.kind === 'channel' || hop.kind === 'dca') return hop.device + ':@' + hop.channel + (hop.tag ? '.' + hop.tag : '');
  if (hop.kind === 'text') return hop.device + ':~' + hop.text;
  if (hop.kind === 'port_channel') return hop.device + ':' + hop.port + '#' + (hop.dir === 'out' ? 'tx' : 'rx') + hop.ch;
  return hop.device + (hop.port ? ':' + hop.port : '');
}

// o: { title, sub, from, direction ('down'|'up'), dca, fetchPaths(params) → Promise<{paths}>, actions: [{label, onclick}], onHop(hop), onClose }
export function openTraceDrawer(o) {
  o = o || {};
  const opener = document.activeElement;
  let direction = o.direction || 'down';
  let dca = o.dca !== false;
  let latest = [];
  let seq = 0;
  const titleId = 'trace-t' + Math.random().toString(36).slice(2, 8);
  const body = h('div', { class: 'trace-body' });
  const status = h('div', { class: 'trace-status', role: 'status', 'aria-live': 'polite' });
  const seg = h('div', { class: 'trace-seg', role: 'group', 'aria-label': 'Direction' });
  const dcaBox = h('input', { type: 'checkbox', id: titleId + '-dca' });
  dcaBox.checked = dca;
  const copyBtn = h('button', { type: 'button', class: 'trace-btn', onclick: function () {
    const text = pathsText(latest);
    if (!text) { status.textContent = 'Nothing to copy yet.'; return; }
    copyText(text).then(function () { status.textContent = 'Copied ' + latest.length + ' path' + (latest.length > 1 ? 's' : '') + ' as text.'; }, function () { status.textContent = 'Copy failed.'; });
  } }, 'Copy as text');
  const sheet = h('div', { class: 'trace-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': titleId }, [
    h('header', { class: 'trace-head' }, [
      h('div', { class: 'trace-head-text' }, [
        h('div', { class: 'trace-eyebrow' }, 'Signal path'),
        h('h2', { id: titleId }, o.title || o.from || 'Trace'),
        o.sub ? h('div', { class: 'trace-sub' }, o.sub) : null,
      ]),
      h('button', { type: 'button', class: 'trace-close', 'aria-label': 'Close', onclick: function () { close(); } }, '\u00d7'),
    ]),
    h('div', { class: 'trace-controls' }, [
      seg,
      h('label', { class: 'trace-check', for: dcaBox.id }, [dcaBox, 'DCA hops']),
      h('span', { class: 'trace-grow' }),
      copyBtn,
    ].concat((o.actions || []).map(function (a) {
      return h('button', { type: 'button', class: 'trace-btn', onclick: function () { a.onclick({ paths: latest, direction: direction, close: close }); } }, a.label);
    }))),
    status,
    body,
  ]);
  const back = h('div', { class: 'trace-backdrop' }, sheet);
  let done = false;
  function close() {
    if (done) return;
    done = true;
    document.removeEventListener('keydown', onKey, true);
    back.remove();
    document.body.classList.remove('trace-open');
    if (o.onClose) o.onClose();
    if (opener && opener.focus) { try { opener.focus(); } catch (e) { /* gone */ } }
  }
  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
  }
  function segBtn(dir, label) {
    const b = h('button', { type: 'button', class: 'trace-seg-btn' + (direction === dir ? ' on' : ''), 'aria-pressed': direction === dir ? 'true' : 'false', 'data-dir': dir, onclick: function () {
      if (direction === dir) return;
      direction = dir;
      Array.prototype.forEach.call(seg.children, function (c) { const on = c.getAttribute('data-dir') === dir; c.classList.toggle('on', on); c.setAttribute('aria-pressed', on ? 'true' : 'false'); });
      load();
    } }, label);
    return b;
  }
  seg.appendChild(segBtn('up', '\u2190 Upstream'));
  seg.appendChild(segBtn('down', 'Downstream \u2192'));
  dcaBox.addEventListener('change', function () { dca = dcaBox.checked; load(); });

  function load() {
    const my = ++seq;
    status.textContent = 'Tracing\u2026';
    body.innerHTML = '';
    sheet.classList.add('loading');
    const params = { from: o.from, direction: direction, dca: dca ? 1 : '' };
    if (o.to) params.to = o.to;
    Promise.resolve().then(function () { return o.fetchPaths(params); }).then(function (res) {
      if (my !== seq || done) return;
      sheet.classList.remove('loading');
      latest = (res && res.paths) || [];
      const n = latest.length;
      const gaps = latest.filter(function (p) { return p.incomplete; }).length;
      status.textContent = n ? (n + ' path' + (n > 1 ? 's' : '') + (gaps ? ' \u00b7 ' + gaps + ' incomplete' : '')) : '';
      body.appendChild(renderPaths(latest, { onHop: o.onHop, emptyText: direction === 'up' ? 'Nothing feeds this yet.' : 'Nothing patched downstream yet.' }));
    }, function (err) {
      if (my !== seq || done) return;
      sheet.classList.remove('loading');
      latest = [];
      status.textContent = '';
      body.appendChild(h('div', { class: 'trace-error', role: 'alert' }, (err && err.message) || String(err)));
    });
  }

  back.addEventListener('pointerdown', function (e) { if (e.target === back) close(); });
  document.addEventListener('keydown', onKey, true);
  document.body.appendChild(back);
  document.body.classList.add('trace-open');
  load();
  const closeBtn = sheet.querySelector('.trace-close');
  if (closeBtn) closeBtn.focus();
  return { close: close, reload: load, element: sheet };
}

// Public pages: any element with data-trace="<node ref>" opens the drawer on click.
// o: { base (app root, '' or '../../'), project }
export function bindTraceButtons(root, o) {
  o = o || {};
  const base = o.base || '';
  function fetchPaths(params) {
    const q = Object.keys(params).filter(function (k) { return params[k] !== '' && params[k] !== undefined && params[k] !== null; })
      .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(String(params[k])); }).join('&');
    return fetch(base + 'api/v2/projects/' + encodeURIComponent(o.project) + '/trace?' + q, { credentials: 'same-origin', headers: { Accept: 'application/json' } }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) throw new Error((data && data.error) || ('HTTP ' + res.status));
        return data;
      });
    });
  }
  Array.prototype.forEach.call(root.querySelectorAll('[data-trace]'), function (el) {
    el.addEventListener('click', function (e) {
      e.preventDefault();
      openTraceDrawer({
        from: el.getAttribute('data-trace'),
        title: el.getAttribute('data-trace-title') || el.getAttribute('data-trace'),
        sub: el.getAttribute('data-trace-sub') || '',
        direction: el.getAttribute('data-trace-dir') || 'down',
        fetchPaths: fetchPaths,
      });
    });
  });
}
