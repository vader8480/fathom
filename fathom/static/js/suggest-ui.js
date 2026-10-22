// Model suggestions: "Suggested model: Yamaha Rio1608-D (High · 100%)" with accept / choose
// another library template / none, shown wherever an import or a discovery run is about to
// create a device. The server ranks the library against the manufacturer / model strings the
// source reported (GET /api/v2/library/suggest; overlay.suggestions; findings[].model_suggestions);
// accepting applies the template to the device exactly like the Add gear dialog does
// (model-core.js applyTemplateToDevice).

import { applyTemplateToDevice } from './model-core.js';

export const OTHER = '__other';

function h(tag, attrs, children) {
  const el = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (v === undefined || v === null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k.indexOf('on') === 0 && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'value') el.value = v;
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

export function pct(v) { return Math.round((Number(v) || 0) * 100) + '%'; }
function cap(s) { s = String(s || ''); return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''; }
export function suggestionLabel(s) { return ((s.manufacturer ? s.manufacturer + ' ' : '') + (s.model || s.name || s.template)).trim(); }

// Pick the suggestion that is accepted by default: the best one unless it is only a low-confidence guess.
export function defaultChoice(suggestions) {
  const top = (suggestions || [])[0];
  return top && top.level !== 'low' ? top.template : '';
}

// A compact control for one device. opts: { label (device name for aria), readOnly, pickTemplate(fn → Promise<template|null>), onChange(choice) }.
// Returns { el, value() → template id | '' , template() → the picked library template when chosen via "Choose…", set(id) }.
export function suggestionControl(suggestions, opts) {
  opts = opts || {};
  suggestions = Array.isArray(suggestions) ? suggestions : [];
  const byId = {};
  suggestions.forEach(function (s) { byId[s.template] = s; });
  let picked = null; // template object chosen from the library (not in the suggestion list)
  let prev = defaultChoice(suggestions);
  const root = h('div', { class: 'ms-suggest', 'data-level': suggestions.length ? suggestions[0].level : 'none' });
  const sel = h('select', { class: 'ms-select', 'aria-label': 'Suggested model' + (opts.label ? ' for ' + opts.label : '') });
  const conf = h('span', { class: 'chip disc-conf ms-conf' }, [h('i'), '']);
  const why = h('div', { class: 'muted ms-evidence' });

  function render() {
    sel.innerHTML = '';
    suggestions.forEach(function (s) {
      sel.appendChild(h('option', { value: s.template }, suggestionLabel(s) + ' \u00b7 ' + pct(s.score)));
    });
    if (picked) sel.appendChild(h('option', { value: picked.id }, suggestionLabel(picked) + ' \u00b7 library'));
    if (opts.pickTemplate) sel.appendChild(h('option', { value: OTHER }, 'Choose from library\u2026'));
    sel.appendChild(h('option', { value: '' }, suggestions.length ? 'No model (keep as imported)' : 'No model'));
    sel.value = prev;
    describe();
  }
  function describe() {
    const s = byId[sel.value];
    root.setAttribute('data-choice', sel.value || 'none');
    if (s) {
      conf.hidden = false;
      conf.className = 'chip disc-conf ms-conf disc-conf-' + (s.level || 'low');
      conf.title = 'confidence ' + pct(s.score);
      conf.lastChild.textContent = cap(s.level || 'low') + ' \u00b7 ' + pct(s.score);
      why.textContent = s.evidence || '';
      why.hidden = !s.evidence;
    } else if (picked && sel.value === picked.id) {
      conf.hidden = false;
      conf.className = 'chip disc-conf ms-conf';
      conf.lastChild.textContent = 'Library';
      why.textContent = 'Chosen from the library';
      why.hidden = false;
    } else {
      conf.hidden = true;
      why.textContent = suggestions.length ? 'Kept as imported: no template, ports stay as they are.' : 'Nothing in the library resembles this device.';
      why.hidden = false;
    }
    if (opts.onChange) opts.onChange(sel.value);
  }
  sel.addEventListener('change', function () {
    if (sel.value !== OTHER) { prev = sel.value; describe(); return; }
    Promise.resolve(opts.pickTemplate()).then(function (t) {
      if (t && t.id) { picked = t; prev = t.id; }
      render();
    }, function () { render(); });
  });
  if (opts.readOnly) sel.disabled = true;
  render();
  root.appendChild(h('div', { class: 'ms-row' }, [h('span', { class: 'ms-label' }, 'Suggested model'), sel, conf]));
  root.appendChild(why);
  return {
    el: root,
    value: function () { return sel.value === OTHER ? '' : sel.value; },
    template: function () { return picked && sel.value === picked.id ? picked : null; },
    set: function (id) { prev = id || ''; render(); },
  };
}

// Resolve a control's choice to a full template (the picked one, else fetched by id). Null when no model was chosen.
export function resolveTemplate(ctx, control) {
  const id = control.value();
  if (!id) return Promise.resolve(null);
  const t = control.template();
  if (t && t.id === id) return Promise.resolve(t);
  if (!ctx.api) return Promise.resolve(null);
  return Promise.resolve(ctx.api.template(id, ctx.project));
}

// Apply the control's choice to a device object (in place); resolves to the device.
export function applyChoice(ctx, control, dev) {
  return resolveTemplate(ctx, control).then(function (t) {
    if (t) applyTemplateToDevice(dev, t, ctx.vocab);
    return dev;
  });
}
