// "Suggest an improvement" (FR-UX-18): a dialog (a bottom sheet at sm through
// the shell's openDialog) for every role, including viewers. Posts a problem
// report with kind "suggestion" via api.reportSuggestion and reports the result
// in a toast. suggest-ui.js (model suggestions) is unrelated.
//
//   openImproveDialog(ctx, {about: 'campus-demo · Inventory · Main', name: 'sam', url: location.href})

import { h } from './dom.js';

export const SUGGESTION_MAX = 2000;

export function suggestionBody(text, name, url) {
  const out = { text: String(text || '').trim().slice(0, SUGGESTION_MAX), kind: 'suggestion' };
  const n = String(name || '').replace(/\s+/g, ' ').trim();
  if (n) out.name = n.slice(0, 80);
  if (url) out.url = String(url).slice(0, 500);
  return out;
}

export function thanksText(res) {
  return 'Thanks \u2014 your suggestion was saved' + (res && res.forwarded === true ? ' and forwarded' : '');
}

export function openImproveDialog(ctx, opts) {
  opts = opts || {};
  if (!ctx || typeof ctx.openDialog !== 'function') return Promise.resolve(null);
  const text = h('textarea', { id: 'imv-text', rows: 5, maxlength: SUGGESTION_MAX, required: true, autofocus: true, placeholder: 'What would make Fathom better for you?', 'aria-describedby': 'imv-count' });
  const count = h('div', { id: 'imv-count', class: 'muted', style: { fontSize: '12px', textAlign: 'right' } }, '0 / ' + SUGGESTION_MAX);
  const name = h('input', { id: 'imv-name', type: 'text', value: opts.name || '', autocomplete: 'name', placeholder: 'optional' });
  text.addEventListener('input', function () { count.textContent = text.value.length + ' / ' + SUGGESTION_MAX; });
  const about = h('p', { class: 'muted imv-about', style: { margin: '0 0 10px', fontSize: '12.5px' } }, ['About: ', h('span', { id: 'imv-about' }, opts.about || ctx.project || '')]);
  const body = h('div', { class: 'imv-root' }, [
    about,
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '10px' } }, [h('label', { for: 'imv-text' }, 'Your suggestion'), text, count]),
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: '4px' } }, [h('label', { for: 'imv-name' }, 'Your name'), name]),
  ]);
  return ctx.openDialog({
    title: 'Suggest an improvement',
    body: body,
    buttons: [
      { label: 'Cancel', value: null },
      {
        label: 'Send', primary: true,
        validate: function () {
          if (!text.value.trim()) { ctx.toast('Describe the improvement first', 'warn'); text.focus(); return false; }
          return true;
        },
        value: function () { return suggestionBody(text.value, name.value, opts.url); },
      },
    ],
  }).then(function (v) {
    if (!v) return null;
    if (!ctx.api || typeof ctx.api.reportSuggestion !== 'function') { ctx.toast('Suggestions need a connection to the server', 'warn'); return null; }
    return Promise.resolve(ctx.api.reportSuggestion(ctx.project, v)).then(function (res) {
      ctx.toast(thanksText(res), 'ok');
      return res || {};
    }, function (e) {
      ctx.toast((e && e.message) || 'Could not send the suggestion', 'err');
      return null;
    });
  });
}
