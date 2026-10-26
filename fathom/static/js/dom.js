// Shared DOM helpers (docs/ui-audit.md D12). h() and esc() are the same as
// app.js's, so components can import them without an import cycle through the
// shell. Nothing here touches the DOM at import time, so the module loads in
// Node.
//
// h(tag, attrs, children): `class`, `text`, `html`, `on<event>` functions
// (listeners, never inline attributes: CSP), `style` as a string or an object.
// Style object keys are camelCase properties ({paddingLeft: '4px'}), CSS custom
// properties ({'--x': '1'}) or hyphenated names ({'grid-column': '2'}); null or
// undefined values are skipped.

function setStyle(el, style) {
  Object.keys(style).forEach(function (k) {
    const v = style[k];
    if (v === undefined || v === null) return;
    if (k.indexOf('-') >= 0) el.style.setProperty(k, String(v));
    else el.style[k] = v;
  });
}

export function h(tag, attrs, children) {
  const el = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (v === undefined || v === null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k.indexOf('on') === 0 && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'style' && typeof v === 'object') setStyle(el, v);
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, String(v));
    });
  }
  (Array.isArray(children) ? children : (children === undefined || children === null ? [] : [children])).forEach(function (c) {
    if (c === null || c === undefined || c === false) return;
    el.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
  });
  return el;
}

export function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; });
}

// addEventListener that returns its own off(); calling off() twice is harmless.
export function on(target, type, fn, opts) {
  target.addEventListener(type, fn, opts);
  let done = false;
  return function off() {
    if (done) return;
    done = true;
    target.removeEventListener(type, fn, opts);
  };
}
