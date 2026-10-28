// Assistant panel (§6.8, FR-AST UI, Knox "Helper"): question -> traced path
// chips + numbered checks + "Update the map?" suggestion (Yes commits the
// ops through the store, undoable). Offline: local cable trace hints.
// P4C adds the model status line and used-tools row, the "Proposed changes"
// card (Yes applies through POST …/assistant/apply), attachments and pasted
// manual text for the next question, and voice input (speech.js).

import { searchLocal, devicePorts, portLabel, invertOps } from './model-core.js';
import * as speech from './speech.js';

const MANUAL_MAX = 20 * 1024;
const TOOL_LABELS = { search: 'search', trace: 'trace', manual: 'manual', attachments: 'attachments', web: 'web lookup' };

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
  function canEdit() { return ctx.role !== 'viewer' && !store.readOnly; }
  if (ctx.ensureCss) ctx.ensureCss('assistant.css');

  const logEl = h('div', { class: 'ast-log', role: 'log', 'aria-live': 'polite', 'aria-label': 'Assistant conversation' });
  const input = h('input', { type: 'text', placeholder: 'Ask about your system\u2026', 'aria-label': 'Ask the assistant', enterkeyhint: 'send', autocomplete: 'off' });
  const send = h('button', { type: 'submit', class: 'primary', 'aria-label': 'Send' }, '\u2191');
  const mic = speech.available() ? h('button', { type: 'button', class: 'ast-mic', 'aria-label': 'Ask by voice', 'aria-pressed': 'false', title: 'Ask by voice' }, '\uD83C\uDFA4') : null;
  const form = h('form', { class: 'ast-form ast-form-with-status' }, [input, mic, send]);
  const chips = h('div', { class: 'ast-chips', 'aria-label': 'Example questions' });
  // context for the next question: attachment ids and pasted manual text, shown as chips
  const pending = { attachments: [], manual: '' };
  const attachBtn = h('button', { type: 'button', class: 'small ast-attach', 'data-act': 'attach' }, 'Attach');
  const manualBtn = h('button', { type: 'button', class: 'small ast-manual', 'data-act': 'manual' }, 'Paste manual text\u2026');
  const ctxRow = h('div', { class: 'ast-ctx' }, [h('div', { class: 'ast-attached', 'aria-label': 'Attached to the next question' }), h('div', { class: 'ast-ctx-acts' }, [attachBtn, manualBtn])]);
  const attached = ctxRow.firstChild;
  const voiceHint = h('div', { class: 'ast-voice-hint', role: 'status' });
  const statusLlm = h('span', { class: 'ast-status-llm' });
  const tools = h('details', { class: 'ast-tools' }, [h('summary', null, 'Used: '), h('div', { class: 'ast-tools-list' })]);
  tools.hidden = true;
  const status = h('div', { class: 'ast-status' }, [statusLlm, tools]);
  const root = h('div', { class: 'ast' }, [
    h('div', { class: 'ast-head' }, [h('span', { class: 'live', 'aria-hidden': 'true' }), h('h2', null, 'Fathom Helper'),
      h('button', { type: 'button', class: 'small ghost', onclick: function () { log.length = 0; redraw(); } }, 'Clear'),
      h('button', { type: 'button', class: 'icon ghost', 'aria-label': 'Close assistant', onclick: function () { if (ctx.closePanel) ctx.closePanel(); } }, '\u00d7')]),
    logEl, chips, ctxRow, voiceHint, form, status,
  ]);
  el.appendChild(root);

  // ---- model status line (meta until the first answer, then the answer's llm / used_tools)
  function setStatus(llm, usedTools) {
    if (llm && llm.used) statusLlm.textContent = [llm.provider, llm.model].filter(Boolean).join(' \u00b7 ') || 'Model';
    else if (llm && llm.reason) statusLlm.textContent = 'Deterministic mode (' + llm.reason + ')';
    else statusLlm.textContent = 'Deterministic mode (no model configured)';
    statusLlm.setAttribute('data-llm', llm && llm.used ? 'on' : 'off');
    const list = tools.lastChild;
    list.innerHTML = '';
    const names = [];
    (usedTools || []).forEach(function (t) {
      const name = typeof t === 'string' ? t : (t && t.name) || '';
      if (!name) return;
      const label = TOOL_LABELS[name] || name;
      if (names.indexOf(label) < 0) names.push(label);
      list.appendChild(h('span', { class: 'chip ast-tool', 'data-tool': name, title: (t && t.args_summary) || '' }, [label, t && t.args_summary ? h('span', { class: 'ast-tool-args' }, ' \u00b7 ' + t.args_summary) : null]));
    });
    tools.hidden = !names.length;
    tools.open = false;
    tools.firstChild.textContent = 'Used: ' + names.join(', ');
  }
  (function initialStatus() {
    const info = (ctx.meta && ctx.meta.llm) || null;
    if (info && info.configured && useLlm) setStatus({ used: true, provider: info.provider, model: info.model }, []);
    else setStatus({ used: false, reason: !useLlm && info && info.configured ? 'model off for this project' : '' }, []);
  })();

  // ---- context chips (attachments, manual text) for the next question
  function attName(id) {
    const a = (store.doc.attachments || []).filter(function (x) { return x.id === id; })[0];
    return a ? (a.name || a.id) : id;
  }
  function drawCtx() {
    attached.innerHTML = '';
    pending.attachments.forEach(function (id) {
      attached.appendChild(h('span', { class: 'chip on ast-att', 'data-att': id }, [attName(id),
        h('button', { type: 'button', class: 'ast-chip-x', 'aria-label': 'Remove ' + attName(id), onclick: function () { pending.attachments = pending.attachments.filter(function (x) { return x !== id; }); drawCtx(); } }, '\u00d7')]));
    });
    if (pending.manual) {
      attached.appendChild(h('span', { class: 'chip on ast-manual-chip', 'data-manual': String(pending.manual.length) }, ['Manual text (' + (pending.manual.length / 1024).toFixed(1) + ' KB)',
        h('button', { type: 'button', class: 'ast-chip-x', 'aria-label': 'Remove the manual text', onclick: function () { pending.manual = ''; drawCtx(); } }, '\u00d7')]));
    }
    ctxRow.classList.toggle('has-ctx', !!(pending.attachments.length || pending.manual));
    attachBtn.setAttribute('aria-pressed', pending.attachments.length ? 'true' : 'false');
    manualBtn.setAttribute('aria-pressed', pending.manual ? 'true' : 'false');
  }
  function kindOf(a) {
    const mime = String((a && a.mime) || '').toLowerCase();
    const name = String((a && a.name) || '').toLowerCase();
    if (a && a.kind) return a.kind;
    if (mime.indexOf('image/') === 0) return 'image';
    if (mime === 'application/pdf' || /\.pdf$/.test(name)) return 'pdf';
    return 'file';
  }
  function openAttach() {
    if (!ctx.openDialog) return;
    const atts = (store.doc.attachments || []).slice().sort(function (a, b) { return String(a.name || a.id).localeCompare(String(b.name || b.id), undefined, { numeric: true }); });
    const devs = {};
    (store.doc.devices || []).forEach(function (d) { devs[d.id] = d; });
    const boxes = [];
    const list = h('div', { class: 'ast-pick', role: 'group', 'aria-label': 'Project files' }, atts.map(function (a) {
      const cb = h('input', { type: 'checkbox', 'data-att': a.id });
      cb.checked = pending.attachments.indexOf(a.id) >= 0;
      boxes.push(cb);
      const dev = a.device && devs[a.device];
      return h('label', { class: 'ast-pick-row', 'data-att': a.id }, [cb,
        h('span', { class: 'ast-pick-name' }, [a.name || a.id, dev ? h('span', { class: 'muted ast-pick-dev' }, ' \u00b7 ' + (dev.name || dev.id)) : null]),
        h('span', { class: 'chip ast-pick-kind', 'data-kind': kindOf(a) }, kindOf(a))]);
    }));
    const body = atts.length
      ? h('div', null, [h('p', { class: 'muted ast-pick-hint' }, 'The assistant reads the chosen files (manuals, spec sheets, photos with text) when answering the next question.'), list])
      : h('p', { class: 'muted' }, 'No files in this project yet. Upload manuals and spec sheets in Files, then attach them here.');
    ctx.openDialog({
      title: 'Attach files',
      body: body,
      buttons: atts.length ? [{ label: 'Cancel', value: null }, { label: 'Attach', primary: true, value: function () { return boxes.filter(function (b) { return b.checked; }).map(function (b) { return b.getAttribute('data-att'); }); } }] : [{ label: 'Close', value: null }],
    }).then(function (ids) {
      if (!ids) return;
      pending.attachments = ids;
      drawCtx();
      input.focus();
    });
  }
  function openManual() {
    if (!ctx.openDialog) return;
    const ta = h('textarea', { id: 'ast-manual-text', rows: 10, placeholder: 'Paste the relevant part of a manual, a spec sheet or an email\u2026', 'aria-label': 'Manual text', maxlength: String(MANUAL_MAX) });
    ta.value = pending.manual;
    const count = h('div', { class: 'muted ast-manual-count', 'aria-live': 'polite' });
    function tick() {
      const n = ta.value.length;
      count.textContent = (n / 1024).toFixed(1) + ' KB of ' + (MANUAL_MAX / 1024) + ' KB';
      count.classList.toggle('warn', n >= MANUAL_MAX);
    }
    ta.addEventListener('input', tick);
    tick();
    ctx.openDialog({
      title: 'Paste manual text',
      body: h('div', { class: 'ast-manual-sheet' }, [h('p', { class: 'muted' }, 'Text pasted here goes with the next question only; it is not stored in the project.'), ta, count]),
      buttons: [{ label: 'Cancel', value: null }, pending.manual ? { label: 'Remove', value: '' } : null, { label: 'Use text', primary: true, value: function () { return ta.value.slice(0, MANUAL_MAX); } }].filter(Boolean),
    }).then(function (v) {
      if (v === null || v === undefined) return;
      pending.manual = String(v).trim() ? String(v).slice(0, MANUAL_MAX) : '';
      drawCtx();
      input.focus();
    });
  }
  attachBtn.addEventListener('click', openAttach);
  manualBtn.addEventListener('click', openManual);
  drawCtx();

  // ---- voice input: press to listen (interim text in the box), stop on silence or a second press
  let voice = null;
  let voiceBase = '';
  function setVoice(on) {
    if (!mic) return;
    mic.classList.toggle('listening', on);
    mic.setAttribute('aria-pressed', on ? 'true' : 'false');
    mic.setAttribute('data-state', on ? 'listening' : 'idle');
    input.classList.toggle('ast-listening', on);
    if (on) input.placeholder = 'Listening\u2026';
    else input.placeholder = 'Ask about your system\u2026';
  }
  function stopVoice() {
    speech.stop();
    voice = null;
    setVoice(false);
  }
  function startVoice() {
    voiceHint.textContent = '';
    voiceBase = input.value.trim();
    voice = speech.start({
      lang: (typeof navigator !== 'undefined' && navigator.language) || 'en-US',
      onResult: function (r) {
        const sep = voiceBase ? ' ' : '';
        if (r.isFinal) {
          voiceBase = (voiceBase + sep + r.final).trim();
          input.value = voiceBase;
        } else {
          input.value = voiceBase + sep + r.interim;
        }
      },
      onEnd: function () {
        voice = null;
        setVoice(false);
        input.value = voiceBase || input.value.trim();
        input.focus();
      },
      onError: function (code) {
        const text = speech.errorText(code);
        if (text) voiceHint.textContent = text;
        voice = null;
        setVoice(false);
      },
    });
    setVoice(!!voice);
  }
  if (mic) mic.addEventListener('click', function () { if (voice) stopVoice(); else startVoice(); });

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

  // "Proposed changes" (Knox parity): the server's proposal {id, summary[], ops, applicable, problems,
  // expires}. Yes posts it to …/assistant/apply at the store's revision; the result is a normal
  // revision, so the doc is refreshed and the toast offers Undo (the inverse ops as a local commit).
  function proposalExpired(p) {
    if (!p || !p.expires) return false;
    const t = typeof p.expires === 'number' ? p.expires * (p.expires < 1e12 ? 1000 : 1) : Date.parse(p.expires);
    return !isNaN(t) && t <= Date.now();
  }
  function proposalEl(entry) {
    const p = entry.answer && entry.answer.proposal;
    if (!p || entry.proposalState === 'no') return null;
    const lines = Array.isArray(p.summary) ? p.summary : (p.summary ? [String(p.summary)] : []);
    const card = h('div', { class: 'ast-proposal', role: 'group', 'aria-label': 'Proposed changes', 'data-proposal': p.id || '' });
    card.appendChild(h('h4', null, 'Proposed changes'));
    if (entry.proposalState === 'yes') {
      card.setAttribute('data-state', 'applied');
      card.appendChild(h('p', { class: 'ast-proposal-done' }, 'Applied' + (entry.applied && entry.applied.revision ? ' as revision ' + entry.applied.revision : '') + ' \u2014 undo from the toast or with Cmd/Ctrl+Z.'));
      return card;
    }
    if (lines.length) card.appendChild(h('ul', { class: 'ast-proposal-summary' }, lines.map(function (l) { return h('li', { html: renderBold(l) }); })));
    (p.problems || []).forEach(function (pr) { card.appendChild(h('div', { class: 'ast-proposal-problem', role: 'note' }, '\u26A0\uFE0E ' + (typeof pr === 'string' ? pr : (pr.message || pr.text || JSON.stringify(pr))))); });
    if (entry.proposalError) card.appendChild(h('div', { class: 'ast-proposal-problem ast-proposal-err', role: 'alert' }, entry.proposalError));
    const ops = Array.isArray(p.ops) ? p.ops : [];
    if (proposalExpired(p)) {
      card.setAttribute('data-state', 'expired');
      card.appendChild(h('p', { class: 'ast-proposal-hint muted' }, 'Proposal expired \u2014 ask again'));
      return card;
    }
    if (!canEdit()) {
      card.setAttribute('data-state', 'readonly');
      card.appendChild(h('p', { class: 'ast-proposal-hint muted' }, store.readOnly && ctx.role !== 'viewer' ? 'Editing is locked; unlock it in Settings to apply this.' : 'Only editors can apply changes. Ask one to apply this proposal.'));
      return card;
    }
    const applicable = p.applicable !== false && ops.length > 0;
    const yes = h('button', { type: 'button', id: 'ast-proposal-yes', class: 'yes', disabled: applicable ? null : true, title: applicable ? '' : 'This proposal cannot be applied as is.' }, 'Yes, apply');
    const no = h('button', { type: 'button', id: 'ast-proposal-no' }, 'No, leave it');
    yes.addEventListener('click', function () {
      if (!ctx.api || !ctx.api.applyProposal) return;
      yes.disabled = true;
      no.disabled = true;
      yes.textContent = 'Applying\u2026';
      entry.proposalError = '';
      const label = lines[0] ? lines[0].replace(/\*\*/g, '') : 'Assistant proposal';
      let inverse = null;
      try { inverse = ops.length ? invertOps(store.doc, ops) : null; } catch (e) { inverse = null; }
      const flush = ctx.flush ? Promise.resolve(ctx.flush()).catch(function () { return null; }) : Promise.resolve(null);
      flush.then(function () {
        return ctx.api.applyProposal(ctx.project, { proposal: p, id: p.id, base_revision: store.revision });
      }).then(function (res) {
        res = res || {};
        entry.proposalState = 'yes';
        entry.applied = res;
        try { if (ops.length) store.applyRemote(ops, 'remote'); } catch (e) { /* the reload below brings the server doc */ }
        if (typeof res.revision === 'number' && store.setRevision) store.setRevision(res.revision);
        if (ctx.reload) Promise.resolve(ctx.reload()).catch(function () { return null; });
        redraw(true);
        const t = ctx.toast('Applied \u00b7 ' + (res.summary || label), 'ok');
        if (t && t.appendChild && inverse && inverse.length) {
          t.appendChild(h('button', { type: 'button', class: 'small ast-undo', onclick: function (e) {
            e.stopPropagation();
            t.remove();
            const r = ctx.commit(inverse, 'Undo: ' + (res.summary || label));
            if (r) ctx.toast('Undone', 'ok');
          } }, 'Undo'));
        }
      }, function (e) {
        const locked = e && (e.status === 423 || e.code === 'locked');
        entry.proposalError = locked ? 'Editing is locked \u2014 nobody can change the model until someone unlocks it.' : ((e && e.message) || 'Could not apply the proposal.');
        if (e && e.status === 409) entry.proposalError = 'The system changed since this answer. Ask again with the latest data.';
        redraw(true);
      });
    });
    no.addEventListener('click', function () { entry.proposalState = 'no'; redraw(true); });
    card.appendChild(h('div', { class: 'row' }, [yes, no]));
    return card;
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
      lastQ = h('div', { class: 'ast-q' }, [entry.question,
        (entry.attachments && entry.attachments.length) || entry.manual
          ? h('div', { class: 'ast-q-ctx' }, (entry.attachments || []).map(function (id) { return h('span', { class: 'chip ast-q-att', 'data-att': id }, attName(id)); })
            .concat(entry.manual ? [h('span', { class: 'chip ast-q-manual' }, 'Manual text')] : []))
          : null]);
      logEl.appendChild(lastQ);
      if (entry.pending) logEl.appendChild(h('div', { class: 'ast-typing' }, 'Tracing\u2026'));
      else {
        logEl.appendChild(answerEl(entry));
        const s = suggestionEl(entry);
        if (s) logEl.appendChild(s);
        const pr = proposalEl(entry);
        if (pr) logEl.appendChild(pr);
      }
    });
    if (keep) logEl.scrollTop = prevTop;
    else if (lastQ) logEl.scrollTop = Math.max(0, lastQ.getBoundingClientRect().top - logEl.getBoundingClientRect().top + logEl.scrollTop - 8);
    else logEl.scrollTop = 0;
  }

  // Prior turns (last 6); a user turn that carried attachments keeps them in `attachments`.
  function history(entries) {
    const out = [];
    entries.slice(-6).forEach(function (e) {
      const u = { role: 'user', text: e.question };
      if (e.attachments && e.attachments.length) u.attachments = e.attachments.slice();
      out.push(u);
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
    if (voice) stopVoice();
    const hist = history(log);
    const entry = { question: question, pending: true };
    // the chosen files and pasted text go with this question only (the entry remembers them for history)
    if (pending.attachments.length) entry.attachments = pending.attachments.slice();
    if (pending.manual) entry.manual = pending.manual;
    pending.attachments = [];
    pending.manual = '';
    drawCtx();
    log.push(entry);
    redraw();
    const room = store.room === '*' ? undefined : store.room;
    if (!ctx.api || navigator.onLine === false) { entry.pending = false; offlineAnswer(entry); redraw(); return; }
    const payload = { question: question, room: room, use_llm: useLlm, history: hist };
    if (entry.attachments) {
      // P4B reads attachment ids from history[].attachments: this turn is appended there too
      payload.history = hist.concat([{ role: 'user', text: question, attachments: entry.attachments.slice() }]);
      payload.attachments = entry.attachments.slice();
    }
    if (entry.manual) payload.manual_text = entry.manual;
    ctx.api.ask(ctx.project, payload).then(function (a) {
      entry.pending = false;
      entry.answer = a || {};
      if (a && (a.llm || a.used_tools)) setStatus(a.llm, a.used_tools);
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
    destroy: function () { if (voice) stopVoice(); el.removeEventListener('keydown', onKey); store.removeEventListener('room', onRoom); el.innerHTML = ''; },
    focus: function () { setTimeout(function () { input.focus(); }, 60); },
    ask: ask,
  };
}
