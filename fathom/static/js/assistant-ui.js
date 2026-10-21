// Assistant panel (§6.8, FR-AST UI, Knox "Helper"): question -> traced path
// chips + numbered checks + "Update the map?" suggestion (Yes commits the
// ops through the store, undoable). Offline: local cable trace hints.

import { searchLocal, devicePorts, portLabel } from './model-core.js';

function h(tag, attrs, children) {
  const el = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (v === undefined || v === null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k.indexOf('on') === 0 && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
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

function escHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; });
}

// escape HTML first, then **bold** -> <strong>
export function renderBold(text) {
  return escHtml(text).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
}

const transcripts = {};

function exampleQuestions(doc, room) {
  const devs = (doc.devices || []).filter(function (d) { return !room || room === '*' || (d.room || '') === room; });
  const byKind = function (kinds) { return devs.filter(function (d) { return kinds.indexOf(d.kind) >= 0; })[0]; };
  const out = [];
  const stream = byKind(['stream', 'encoder']);
  if (stream) out.push('House sound is fine, but the livestream has no audio.');
  const disp = byKind(['display', 'projector']);
  if (disp) out.push('What feeds ' + disp.name + '?');
  const cons = byKind(['console', 'processor']);
  const spk = byKind(['speaker', 'amp', 'pa']);
  if (cons && spk) out.push('How does the ' + cons.name + ' get to the ' + spk.name + '?');
  const spare = (doc.devices || []).filter(function (d) { return d.status === 'spare'; })[0];
  if (spare) out.push('Where is the ' + spare.name + '?');
  if (out.length < 4 && disp) out.push(disp.name + ' has no picture.');
  if (out.length < 4) out.push('The mains are silent.');
  return out.slice(0, 4);
}

// device-level upstream walk over doc cables (offline hint only)
function localUpstream(doc, deviceId) {
  const into = {};
  (doc.cables || []).forEach(function (c) {
    if (!c.from || !c.to) return;
    (into[c.to.device] = into[c.to.device] || []).push(c);
    if (c.bidirectional) (into[c.from.device] = into[c.from.device] || []).push({ from: c.to, to: c.from, id: c.id });
  });
  const names = {};
  (doc.devices || []).forEach(function (d) { names[d.id] = d; });
  const paths = [];
  (function walk(dev, path, seen) {
    const ins = (into[dev] || []).filter(function (c) { return !seen[c.from.device]; });
    if (!ins.length || path.length > 10) { if (path.length > 1) paths.push(path.slice().reverse()); return; }
    ins.forEach(function (c) {
      if (paths.length >= 3) return;
      seen[c.from.device] = true;
      const pd = names[c.from.device];
      const pp = pd ? devicePorts(pd).filter(function (p) { return p.id === c.from.port; })[0] : null;
      path.push((pd ? pd.name : c.from.device) + (pp ? ' \u00b7 ' + portLabel(pp) : ''));
      walk(c.from.device, path, seen);
      path.pop();
      delete seen[c.from.device];
    });
  })(deviceId, [names[deviceId] ? names[deviceId].name : deviceId], (function () { const s = {}; s[deviceId] = true; return s; })());
  return paths;
}

export function mountAssistant(el, ctx) {
  const store = ctx.store;
  const key = ctx.project || '_';
  const log = transcripts[key] = transcripts[key] || [];
  const useLlm = !(store.doc.settings && store.doc.settings.assistant && store.doc.settings.assistant.llm === false);

  const logEl = h('div', { class: 'ast-log', role: 'log', 'aria-live': 'polite', 'aria-label': 'Assistant conversation' });
  const input = h('input', { type: 'text', placeholder: 'Ask about your system\u2026', 'aria-label': 'Ask the assistant', enterkeyhint: 'send', autocomplete: 'off' });
  const send = h('button', { type: 'submit', class: 'primary', 'aria-label': 'Send' }, '\u2191');
  const form = h('form', { class: 'ast-form' }, [input, send]);
  const chips = h('div', { class: 'ast-chips', 'aria-label': 'Example questions' });
  const root = h('div', { class: 'ast' }, [
    h('div', { class: 'ast-head' }, [h('span', { class: 'live', 'aria-hidden': 'true' }), h('h2', null, 'Fathom Helper'),
      h('button', { type: 'button', class: 'small ghost', onclick: function () { log.length = 0; redraw(); } }, 'Clear'),
      h('button', { type: 'button', class: 'icon ghost', 'aria-label': 'Close assistant', onclick: function () { if (ctx.closePanel) ctx.closePanel(); } }, '\u00d7')]),
    logEl, chips, form,
  ]);
  el.appendChild(root);

  function fillChips() {
    chips.innerHTML = '';
    exampleQuestions(store.doc, store.room).forEach(function (q) {
      chips.appendChild(h('button', { type: 'button', class: 'small', onclick: function () { ask(q); } }, q));
    });
  }

  function chipFor(hop, path) {
    return h('button', { type: 'button', class: 'ast-chip', 'data-device': hop.device, 'data-port': hop.port || '', onclick: function () {
      const sel = hop.port ? { type: 'port', id: hop.device, device: hop.device, port: hop.port } : { type: 'device', id: hop.device, device: hop.device };
      ctx.select(sel);
      const devices = [];
      const ports = [];
      (path.hops || []).forEach(function (x) {
        if (devices.indexOf(x.device) < 0) devices.push(x.device);
        if (x.port) ports.push(x.device + ':' + x.port);
      });
      ctx.highlight({ devices: devices, ports: ports, cables: (path.cables || []).slice(), source: 'assistant' });
      if (ctx.openInspector && window.innerWidth >= 1100) ctx.openInspector(sel);
    } }, hop.label || (hop.device + (hop.port ? ':' + hop.port : '')));
  }

  function answerEl(entry) {
    const a = entry.answer;
    const box = h('div', { class: 'ast-a' });
    if (entry.error) {
      box.appendChild(h('div', { html: renderBold(entry.error) }));
      (entry.hints || []).forEach(function (p) { box.appendChild(h('div', { class: 'ast-path' }, p.map(function (t, i) { return [i ? h('span', { class: 'ast-arrow' }, '\u2192') : null, h('span', { class: 'ast-chip' }, t)]; }).reduce(function (x, y) { return x.concat(y); }, []))); });
      return box;
    }
    if (a.summary) box.appendChild(h('div', { html: renderBold(a.summary) }));
    (a.paths || []).forEach(function (p, pi) {
      const row = h('div', { class: 'ast-path', 'aria-label': (p.role === 'suspect' ? 'Suspect path: ' : 'Path: ') + (p.text || '') });
      (p.hops || []).forEach(function (hop, i) {
        if (i) row.appendChild(h('span', { class: 'ast-arrow', 'aria-hidden': 'true' }, '\u2192'));
        row.appendChild(chipFor(hop, p));
      });
      if (pi > 0) row.style.opacity = '0.75';
      box.appendChild(row);
    });
    if (a.checks && a.checks.length) {
      const ol = h('ol');
      a.checks.forEach(function (c, i) {
        const done = !!(entry.done && entry.done[i]);
        const cb = h('input', { type: 'checkbox', 'aria-label': 'Done: check ' + (c.n || i + 1) });
        cb.checked = done;
        const li = h('li', { class: done ? 'done' : '' }, [h('span', { class: 'n' }, (c.n || i + 1) + '.'), h('label', { class: 'chk ast-chk' }, [cb, h('span', { class: 't', html: renderBold(c.text) })])]);
        cb.addEventListener('change', function () { entry.done = entry.done || {}; entry.done[i] = cb.checked; li.className = cb.checked ? 'done' : ''; });
        ol.appendChild(li);
      });
      box.appendChild(ol);
    }
    if (a.unresolved && a.unresolved.length) {
      a.unresolved.forEach(function (u) {
        const name = typeof u === 'string' ? u : (u.text || u.phrase || '');
        const sugg = (u && u.suggestions) || [];
        box.appendChild(h('div', { class: 'ast-notes' }, ['I couldn\u2019t find \u201c' + name + '\u201d.', sugg.length ? ' Did you mean: ' : '',
          sugg.map(function (s, i) { const t = typeof s === 'string' ? s : (s.title || s.id); return [i ? ', ' : '', h('button', { type: 'button', class: 'ast-chip', onclick: function () { input.value = entry.question.replace(name, t); input.focus(); } }, t)]; }).reduce(function (x, y) { return x.concat(y); }, [])]));
      });
    }
    (a.notes || []).forEach(function (n) { box.appendChild(h('div', { class: 'ast-notes', html: renderBold(n) })); });
    if (a.llm && a.llm.used && a.llm.text) {
      box.appendChild(h('div', { class: 'ast-llm' }, [h('div', { class: 'h' }, 'AI notes \u2014 verify against the system' + (a.llm.model ? ' \u00b7 ' + a.llm.model : '')), h('div', null, a.llm.text)]));
    }
    return box;
  }

  function suggestionEl(entry) {
    const s = entry.answer && entry.answer.suggestion;
    if (!s || !s.ops || !s.ops.length || entry.suggestionState === 'no') return null;
    if (entry.suggestionState === 'yes') return h('div', { class: 'ast-suggest' }, [h('h4', null, 'Map updated'), h('p', null, s.text + ' \u2014 undo with Cmd/Ctrl+Z.')]);
    const yes = h('button', { type: 'button', id: 'ast-suggest-yes', class: 'yes', disabled: store.readOnly ? true : null }, 'Yes, update the map');
    const no = h('button', { type: 'button', id: 'ast-suggest-no' }, 'No, leave it');
    yes.addEventListener('click', function () {
      const moved = s.base_revision !== undefined && s.base_revision !== null && store.revision !== s.base_revision;
      const pending = ctx.queue && ctx.queue.pending;
      if (moved || pending) {
        ctx.confirm('The system changed since this answer (revision ' + s.base_revision + ' \u2192 ' + store.revision + '). Ask again with the latest data before updating the map?', { ok: 'Ask again' }).then(function (y) {
          if (y) { entry.suggestionState = 'no'; ask(entry.question); }
        });
        return;
      }
      const res = ctx.commit(s.ops, 'Assistant: ' + s.text);
      if (res) { entry.suggestionState = 'yes'; redraw(true); ctx.toast('Map updated', 'ok'); }
    });
    no.addEventListener('click', function () { entry.suggestionState = 'no'; redraw(true); });
    return h('div', { class: 'ast-suggest', role: 'group', 'aria-label': 'Update the map?' }, [h('h4', null, 'Update the map?'), h('p', null, s.text), h('div', { class: 'row' }, [yes, no])]);
  }

  // keep: leave the scroll position alone (in-place updates); otherwise bring the latest
  // question to the top so its path chips are visible even when the answer is long.
  function redraw(keep) {
    const prevTop = logEl.scrollTop;
    let lastQ = null;
    logEl.innerHTML = '';
    if (!log.length) {
      logEl.appendChild(h('div', { class: 'ast-a' }, [h('div', null, 'Ask about this system: what feeds a screen, why the stream has no audio, where a spare lives. Answers trace the actual cables and ports.'),
        h('div', { class: 'ast-notes' }, 'Room: ' + (store.room === '*' ? 'all rooms' : (((store.doc.rooms || []).filter(function (r) { return r.id === store.room; })[0] || {}).name || store.room)))]));
    }
    log.forEach(function (entry) {
      lastQ = h('div', { class: 'ast-q' }, entry.question);
      logEl.appendChild(lastQ);
      if (entry.pending) logEl.appendChild(h('div', { class: 'ast-typing' }, 'Tracing\u2026'));
      else {
        logEl.appendChild(answerEl(entry));
        const s = suggestionEl(entry);
        if (s) logEl.appendChild(s);
      }
    });
    if (keep) logEl.scrollTop = prevTop;
    else if (lastQ) logEl.scrollTop = Math.max(0, lastQ.getBoundingClientRect().top - logEl.getBoundingClientRect().top + logEl.scrollTop - 8);
    else logEl.scrollTop = 0;
  }

  function history() {
    const out = [];
    log.slice(-6).forEach(function (e) {
      out.push({ role: 'user', text: e.question });
      if (e.answer && e.answer.summary) out.push({ role: 'assistant', text: e.answer.summary });
    });
    return out;
  }

  function offlineAnswer(entry) {
    const words = entry.question.replace(/[?!.,]/g, ' ');
    const hits = searchLocal(store.doc, words, 30).filter(function (x) { return x.kind === 'device' && x.score >= 60; });
    const tokens = words.toLowerCase().split(/\s+/).filter(function (t) { return t.length >= 3; });
    const named = (store.doc.devices || []).filter(function (d) {
      const n = (d.name || '').toLowerCase();
      return n && (words.toLowerCase().indexOf(n) >= 0 || tokens.some(function (t) { return n.split(/\s+/).indexOf(t) >= 0 && t.length >= 4; }));
    });
    const ids = [];
    hits.concat(named).forEach(function (d) { const id = d.device || d.id; if (ids.indexOf(id) < 0) ids.push(id); });
    let hints = [];
    ids.slice(0, 2).forEach(function (id) { hints = hints.concat(localUpstream(store.doc, id)); });
    entry.error = 'The assistant needs the server. ' + (hints.length ? 'Here is how the cables reach what you named:' : 'Name a device in the question to see its cable path.');
    entry.hints = hints.slice(0, 3);
  }

  function ask(q) {
    const question = String(q || '').trim();
    if (!question) return;
    input.value = '';
    const hist = history();
    const entry = { question: question, pending: true };
    log.push(entry);
    redraw();
    const room = store.room === '*' ? undefined : store.room;
    if (!ctx.api || navigator.onLine === false) { entry.pending = false; offlineAnswer(entry); redraw(); return; }
    ctx.api.ask(ctx.project, { question: question, room: room, use_llm: useLlm, history: hist }).then(function (a) {
      entry.pending = false;
      entry.answer = a || {};
      redraw();
      if (a && a.paths && a.paths[0]) {
        const p = a.paths[0];
        const devices = [];
        (p.hops || []).forEach(function (x) { if (devices.indexOf(x.device) < 0) devices.push(x.device); });
        ctx.highlight({ devices: devices, ports: (p.hops || []).filter(function (x) { return x.port; }).map(function (x) { return x.device + ':' + x.port; }), cables: (p.cables || []).slice(), source: 'assistant' });
      }
    }, function (e) {
      entry.pending = false;
      if (e && e.status === 0) offlineAnswer(entry);
      else entry.error = (e && e.message) || 'The assistant failed.';
      redraw();
    });
  }

  form.addEventListener('submit', function (e) { e.preventDefault(); ask(input.value); });
  function onKey(e) {
    if (e.key === 'Escape' && el.classList.contains('open') && !document.querySelector('.app-dialog-backdrop')) {
      e.preventDefault();
      if (ctx.closePanel) ctx.closePanel();
    }
  }
  el.addEventListener('keydown', onKey);
  function onRoom() { fillChips(); }
  store.addEventListener('room', onRoom);
  fillChips();
  redraw();
  return {
    destroy: function () { el.removeEventListener('keydown', onKey); store.removeEventListener('room', onRoom); el.innerHTML = ''; },
    focus: function () { setTimeout(function () { input.focus(); }, 60); },
    ask: ask,
  };
}
