// PRIM-FIX: js/dom.js h() beyond tests/js/router-contract.test.mjs (docs/ui-audit.md D12, B.5 PRIM-FIX):
// style objects with camelCase, hyphenated and custom properties; listeners, not inline handlers.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule } from './fixtures/helpers.mjs';

const { mod, skip, error } = await loadModule('js/dom.js', 'ROUTER');
const T = (name, fn) => test(name, { skip: skip || (error ? 'import failed' : false) }, fn);
if (error) test('dom.js imports', () => { throw error; });

// Just enough of document/element for h(): attributes, a CSSStyleDeclaration-like style, listeners.
function fakeDocument() {
  function el(tag) {
    const props = {};
    const style = {
      setProperty(k, v) { props[k] = String(v); },
      getPropertyValue(k) { return props[k] || ''; },
    };
    return {
      tagName: tag.toUpperCase(), attrs: {}, children: [], listeners: {}, style, props,
      setAttribute(k, v) { this.attrs[k] = String(v); },
      getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
      addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
      appendChild(c) { this.children.push(c); return c; },
      set className(v) { this.attrs.class = v; },
      set textContent(v) { this.children = [String(v)]; },
    };
  }
  return { createElement: el, createTextNode: (s) => ({ text: s }) };
}

function withDocument(fn) {
  const had = Object.prototype.hasOwnProperty.call(globalThis, 'document');
  const prev = globalThis.document;
  globalThis.document = fakeDocument();
  try { return fn(); } finally { if (had) globalThis.document = prev; else delete globalThis.document; }
}

T('h(): style object sets camelCase properties directly and custom/hyphenated ones with setProperty', () => {
  withDocument(() => {
    const n = mod.h('div', { style: { paddingLeft: '26px', '--sch-color': '#9aa3b5', 'grid-column': '2', '--rk-ru': 18, width: null, height: undefined } });
    assert.equal(n.style.paddingLeft, '26px');
    assert.equal(n.style.getPropertyValue('--sch-color'), '#9aa3b5', 'custom property');
    assert.equal(n.style.getPropertyValue('--rk-ru'), '18', 'numbers are stringified');
    assert.equal(n.style.getPropertyValue('grid-column'), '2', 'hyphenated name');
    assert.equal('width' in n.style, false, 'null values are skipped');
    assert.equal('height' in n.style, false, 'undefined values are skipped');
    assert.equal(n.getAttribute('style'), null, 'an object never becomes a style attribute');
  });
});

T('h(): a style string stays an attribute; on* functions are listeners, not attributes (CSP)', () => {
  withDocument(() => {
    const fn = () => {};
    const n = mod.h('button', { style: 'left:4px;--x:1', onclick: fn, class: 'a b', 'data-k': 3, hidden: true, title: false });
    assert.equal(n.getAttribute('style'), 'left:4px;--x:1');
    assert.deepEqual(n.listeners.click, [fn]);
    assert.equal(n.getAttribute('onclick'), null);
    assert.equal(n.getAttribute('class'), 'a b');
    assert.equal(n.getAttribute('data-k'), '3');
    assert.equal(n.getAttribute('hidden'), '');
    assert.equal(n.getAttribute('title'), null);
  });
});
