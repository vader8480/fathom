"""Standalone HTML page: the diagram (cards + SVG overlay), key, patch sheet,
appendix tables, hover details, click-to-trace, downloads and print CSS.

No external assets: system fonts, inline CSS / JS, data embedded as JSON.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from .layout import GROUP_HEADER_H, GROUP_PAD, KEY_ROW_H, Layout
from .model import BRANDS, KINDS, Project
from .patch import build_patch_sheet, patch_sheet_csv
from .render_svg import ACCENT, BG, FONT, MUTED, PANEL, PANEL_BORDER, TEXT, esc, planned_ids, render_svg, rgba, svg_defs, svg_links, svg_spine
from .trace import graph_json

CSS = """
:root{--bg:%(bg)s;--panel:%(panel)s;--border:%(border)s;--text:%(text)s;--muted:%(muted)s;--accent:%(accent)s;}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text);font-family:%(font)s;-webkit-font-smoothing:antialiased}
body{padding:0}
.page{padding:22px 24px 28px;width:max-content;min-width:100%%}
.eyebrow{font-size:9.5px;letter-spacing:1.8px;text-transform:uppercase;color:var(--muted);font-weight:600}
h1{font-size:24px;font-weight:700;margin:8px 0 8px;letter-spacing:-0.2px}
.intro{color:var(--muted);font-size:11.5px;line-height:1.45;max-width:560px;margin:0 0 16px}
.toolbar{position:fixed;top:12px;right:14px;display:flex;gap:6px;z-index:50;flex-wrap:wrap;justify-content:flex-end;max-width:640px}
.toolbar button,.toolbar select{background:#161d2e;border:1px solid var(--border);color:var(--text);font:inherit;font-size:11px;padding:5px 9px;border-radius:7px;cursor:pointer}
.toolbar button:hover{border-color:var(--accent);color:#fff}
.toolbar select{cursor:default;max-width:170px}
.tracebox{position:fixed;top:48px;right:14px;z-index:50;background:#121828;border:1px solid var(--border);border-radius:9px;padding:9px 11px;max-width:560px;font-size:11px;display:none;box-shadow:0 10px 30px rgba(0,0,0,.45)}
.tracebox.open{display:block}
.tracebox h4{margin:0 0 6px;font-size:11px;letter-spacing:1px;text-transform:uppercase;color:var(--muted)}
.tracebox .paths div{padding:3px 4px;border-radius:4px;cursor:pointer;color:var(--text)}
.tracebox .paths div:hover{background:rgba(255,255,255,.06)}
.tracebox .paths div.on{background:rgba(142,162,255,.18)}
.tracebox .muted{color:var(--muted)}
.canvas{position:relative}
.group{position:absolute;border:1px solid var(--border);background:var(--panel);border-radius:10px}
.group .gh{position:absolute;left:%(gpad)spx;top:9px;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;font-weight:600;white-space:nowrap}
.group .gh b{color:var(--accent);margin-right:8px;font-weight:700}
.group.auto{border-style:dashed}
.gnote{position:absolute;color:var(--muted);font-size:10.5px;line-height:14px;padding:0 2px}
.chev{position:absolute;display:flex;align-items:center;gap:8px;padding-left:20px;background:rgba(255,255,255,.05);border:1px solid var(--border);
  clip-path:polygon(0 0,calc(100%% - 12px) 0,100%% 50%%,calc(100%% - 12px) 100%%,0 100%%,12px 50%%);font-size:9.5px;letter-spacing:1.3px;text-transform:uppercase;font-weight:600;white-space:nowrap;overflow:hidden}
.chev b{color:var(--accent);font-weight:700;font-size:10px;letter-spacing:0}
svg.overlay{position:absolute;left:0;top:0;overflow:visible;pointer-events:none}
svg.overlay .lk{transition:opacity .15s}
.card{position:absolute;border-radius:8px;border:1px solid var(--cb);padding:%(cpy)spx %(cpx)spx;
  background:linear-gradient(135deg,var(--c42),var(--c10) 55%%,rgba(20,26,42,.92));
  box-shadow:0 0 0 1px var(--c28) inset,0 6px 18px -10px var(--c60);cursor:default}
.card:hover{border-color:var(--c)}
.card.planned{border-style:dashed;border-color:var(--c)}
.card .t{font-size:12.5px;font-weight:600;line-height:16px;color:var(--text);padding-right:0}
.card.hasbadge .t{padding-right:%(badge)spx}
.card .s{font-size:10.5px;line-height:14px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card .badge{position:absolute;right:8px;top:8px;height:14px;line-height:14px;padding:0 6px;border-radius:3px;font-size:8.5px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;white-space:nowrap}
.card .badge.serif{font-family:Georgia,'Times New Roman',serif;text-transform:none;letter-spacing:0;font-size:9.5px;font-style:italic}
.card .badge.bold-italic{font-style:italic}
.card .badge.wordmark{letter-spacing:1.4px}
.card.dim{opacity:.28}
.card.lit{border-color:#fff;box-shadow:0 0 0 1px #fff inset,0 0 18px -4px var(--c)}
.key{position:absolute;border:1px solid var(--border);background:var(--panel);border-radius:10px}
.key .gh{position:absolute;left:%(gpad)spx;top:9px;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;font-weight:600}
.key-row{position:absolute;display:flex;align-items:center;gap:6px;font-size:10.5px;white-space:nowrap;color:var(--text)}
.key-foot{position:absolute;color:var(--muted);font-size:9.5px;line-height:13px}
.tip{position:absolute;z-index:60;background:#121828;border:1px solid var(--border);border-radius:9px;padding:9px 11px;font-size:11px;line-height:1.4;max-width:360px;box-shadow:0 12px 30px rgba(0,0,0,.5);pointer-events:none;display:none}
.tip.show{display:block}
.tip h5{margin:0 0 4px;font-size:12px}
.tip .k{color:var(--muted)}
.tip ul{margin:4px 0 0;padding-left:14px}
.tip li{margin:1px 0}
.appendix{margin-top:28px;max-width:1360px}
.appendix details{border:1px solid var(--border);border-radius:10px;background:var(--panel);margin:0 0 12px;padding:0 14px}
.appendix summary{cursor:pointer;padding:10px 0;font-size:11px;letter-spacing:1.4px;text-transform:uppercase;font-weight:600}
.appendix summary span{color:var(--muted);font-weight:400;letter-spacing:0;text-transform:none;margin-left:8px}
.appendix table{border-collapse:collapse;width:100%%;font-size:11px;margin:0 0 12px}
.appendix th{text-align:left;color:var(--muted);font-weight:600;font-size:10px;letter-spacing:.8px;text-transform:uppercase;padding:6px 8px;border-bottom:1px solid var(--border)}
.appendix td{padding:5px 8px;border-bottom:1px solid rgba(255,255,255,.05);vertical-align:top}
.appendix td.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:10.5px}
.appendix .dev{margin:6px 0 14px}
.appendix .dev h4{margin:10px 0 4px;font-size:12px}
.appendix .dev h4 small{color:var(--muted);font-weight:400;margin-left:8px}
.pill{display:inline-block;padding:0 6px;border-radius:999px;font-size:9.5px;line-height:15px;border:1px solid var(--border);color:var(--muted);white-space:nowrap}
.pill i{display:inline-block;width:14px;height:0;border-top:2px solid currentColor;vertical-align:middle;margin-right:4px}
.notes{color:var(--muted);font-size:10.5px}
.notes li{margin:2px 0}
.toolbar a.tb{background:#161d2e;border:1px solid var(--border);color:var(--text);font-size:11px;padding:5px 9px;border-radius:7px;text-decoration:none;white-space:nowrap}
.toolbar a.tb:hover{border-color:var(--accent);color:#fff}
.card.tapped{border-color:var(--c)}
@media (hover:none),(pointer:coarse){
  .toolbar button,.toolbar select,.toolbar a.tb,.tracebox button,.tracebox select{min-height:44px;min-width:44px;font-size:13px;padding:8px 11px}
  .toolbar a.tb{display:inline-flex;align-items:center}
  .appendix summary{min-height:44px;display:flex;align-items:center;padding:0}
}
@media (hover:none){
  .tip{position:fixed;left:8px !important;right:8px;top:auto !important;bottom:calc(8px + env(safe-area-inset-bottom,0px));max-width:none;max-height:45vh;overflow:auto;font-size:13px}
}
@media (max-width:1000px){
  .toolbar{position:static;justify-content:flex-start;max-width:none;padding:10px 12px 0;margin:0}
  .tracebox{position:fixed;left:8px;right:8px;top:auto;bottom:8px;max-width:none}
  .page{padding:14px 12px 24px}
}
@media print{
  @page{size:%(pw)spx %(ph)spx;margin:0}
  html,body{background:var(--bg) !important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .toolbar,.tracebox,.tip,.no-print{display:none !important}
  .appendix{%(appendix_print)s}
  .page{padding:22px 24px}
}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;animation:none!important;scroll-behavior:auto!important}}
"""

# error capture + headless smoke marker (?smoke=1), shared by every viewer page
SMOKE_JS = r"""
(function(){
  if(window.__fathomErrors) return; window.__fathomErrors=[];
  function p(m){ window.__fathomErrors.push(String(m).slice(0,500)); }
  window.addEventListener('error', function(e){ p((e && e.message) || 'error'); });
  window.addEventListener('unhandledrejection', function(e){ var r=e && e.reason; p('unhandled: ' + ((r && r.message) || r)); });
  var ce = console.error; console.error = function(){ p(Array.prototype.join.call(arguments, ' ')); return ce.apply(console, arguments); };
  if (/[?&]smoke=1(&|$)/.test(location.search)) {
    window.addEventListener('load', function(){ setTimeout(function(){
      document.documentElement.setAttribute('data-smoke', JSON.stringify({ready: true, errors: window.__fathomErrors, stats: null}));
    }, 1000); });
  }
})();
"""

SW_JS = r"""
(function(){
  var base = document.documentElement.getAttribute('data-app-root');
  if (base === null || !('serviceWorker' in navigator) || !window.isSecureContext || location.protocol === 'file:') return;
  try { var root = new URL(base || './', location.href); navigator.serviceWorker.register(root.href + 'sw.js', {scope: root.pathname}).catch(function(){}); } catch (e) {}
})();
"""

JS = r"""
(function(){
  var D = window.SF_DATA;
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var links = Array.prototype.slice.call(document.querySelectorAll('svg.overlay .lk, svg.overlay .ll'));
  var stubs = Array.prototype.slice.call(document.querySelectorAll('svg.overlay .stub, svg.overlay .dot'));
  var tip = document.getElementById('tip');
  var canvas = document.querySelector('.canvas');
  var locked = null;
  function canon(id){ return (D.refs && D.refs[id]) || id; }

  function nodeLabel(id){ var c = document.querySelector('.card[data-id="'+CSS.escape(id)+'"]'); return c ? c.getAttribute('data-title') : id; }
  function mediumLabel(m){ return (D.media[m] && D.media[m].label) || m; }

  function clearHL(){
    cards.forEach(function(c){ c.classList.remove('dim'); c.classList.remove('lit'); });
    links.forEach(function(l){ l.style.opacity=''; });
    stubs.forEach(function(s){ s.style.opacity=''; });
  }
  function highlightSet(nodeSet, edgeSet){
    cards.forEach(function(c){ var id=canon(c.getAttribute('data-id')); if(nodeSet.has(id)){c.classList.add('lit');c.classList.remove('dim');} else {c.classList.add('dim');c.classList.remove('lit');} });
    links.forEach(function(l){ var k=l.getAttribute('data-s')+'>'+l.getAttribute('data-t'); l.style.opacity = edgeSet.has(k) ? '1' : '0.12'; });
    stubs.forEach(function(s){ s.style.opacity = nodeSet.has(canon(s.getAttribute('data-n'))) ? '1' : '0.15'; });
  }
  function neighbors(id){
    id = canon(id);
    var ns=new Set([id]), es=new Set();
    D.edges.forEach(function(e){ if(e.s===id||e.d===id){ ns.add(e.s); ns.add(e.d); es.add(e.s+'>'+e.d); } });
    return {nodes:ns, edges:es};
  }
  function reach(id){
    id = canon(id);
    var ns=new Set([id]), es=new Set(), q=[id], seen=new Set([id]);
    while(q.length){ var n=q.shift(); D.edges.forEach(function(e){ if(e.s===n){ es.add(e.s+'>'+e.d); ns.add(e.d); if(!seen.has(e.d)){seen.add(e.d);q.push(e.d);} } }); }
    q=[id]; seen=new Set([id]);
    while(q.length){ var n2=q.shift(); D.edges.forEach(function(e){ if(e.d===n2){ es.add(e.s+'>'+e.d); ns.add(e.s); if(!seen.has(e.s)){seen.add(e.s);q.push(e.s);} } }); }
    return {nodes:ns, edges:es};
  }
  function showTip(card, ev){
    var id = card.getAttribute('data-id');
    var html = D.tips[id];
    if(!html) return;
    tip.innerHTML = html;
    tip.classList.add('show');
    var cr = canvas.getBoundingClientRect();
    var r = card.getBoundingClientRect();
    var x = r.right - cr.left + 10, y = r.top - cr.top;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
    var tr = tip.getBoundingClientRect();
    if (tr.right > window.innerWidth - 8) { x = r.left - cr.left - tr.width - 10; if (x < 0) x = 8; tip.style.left = x + 'px'; }
    if (tr.bottom > window.innerHeight - 8) { y = Math.max(0, y - (tr.bottom - window.innerHeight) - 12); tip.style.top = y + 'px'; }
  }
  // touch: first tap shows the tip, second tap on the same card traces (no hover dependence)
  var lastPointer = 'mouse', tapped = null;
  document.addEventListener('pointerdown', function(e){ lastPointer = e.pointerType || 'mouse'; }, true);
  function isTouch(){ return lastPointer === 'touch' || lastPointer === 'pen'; }
  function untap(){ if(tapped){ tapped.classList.remove('tapped'); tapped = null; } tip.classList.remove('show'); }
  cards.forEach(function(card){
    card.addEventListener('mouseenter', function(ev){ if(isTouch()) return; if(!locked){ var h=neighbors(card.getAttribute('data-id')); highlightSet(h.nodes,h.edges);} showTip(card, ev); });
    card.addEventListener('mouseleave', function(){ if(isTouch()) return; tip.classList.remove('show'); if(!locked) clearHL(); });
    card.addEventListener('click', function(ev){
      var id = canon(card.getAttribute('data-id'));
      if (isTouch() && tapped !== card) {
        untap(); tapped = card; card.classList.add('tapped');
        if(!locked){ var hn=neighbors(card.getAttribute('data-id')); highlightSet(hn.nodes,hn.edges); }
        showTip(card, ev); ev.stopPropagation(); return;
      }
      if (isTouch()) { tip.classList.remove('show'); }
      if (locked === id) { locked = null; clearHL(); setStatus(''); untap(); return; }
      locked = id; var h = reach(id); highlightSet(h.nodes, h.edges);
      setStatus('Tracing from <b>'+esc(nodeLabel(id))+'</b>: '+(h.nodes.size-1)+' connected cards. '+(isTouch()?'Tap':'Click')+' again to clear.');
      ev.stopPropagation();
    });
  });
  document.addEventListener('click', function(e){
    if(tapped && !e.target.closest('.card')){ untap(); if(!locked) clearHL(); }
    if(locked && !e.target.closest('.tracebox') && !e.target.closest('.toolbar')){ locked=null; clearHL(); setStatus(''); }
  });
  // highlight bridge: the app's Map view (same origin) posts {type:'fathom:highlight', nodes:[ids], edges:[[s,d]]}
  if (D.bridge) window.addEventListener('message', function(e){
    if (e.origin !== location.origin) return;
    var m = e.data || {};
    if (m.type !== 'fathom:highlight') return;
    var nodes = (m.nodes || []).map(canon);
    if (!nodes.length) { locked = null; clearHL(); setStatus(''); return; }
    var ns = new Set(nodes), es = new Set();
    (m.edges || []).forEach(function(p){ if(p && p.length === 2) es.add(canon(p[0]) + '>' + canon(p[1])); });
    D.edges.forEach(function(ed){ if(ns.has(ed.s) && ns.has(ed.d) && !(m.edges || []).length) es.add(ed.s + '>' + ed.d); });
    locked = '__bridge__'; highlightSet(ns, es);
    var first = document.querySelector('.card.lit'); if (first && first.scrollIntoView) first.scrollIntoView({block: 'center', inline: 'center'});
  });
  var rn = document.getElementById('room-nav');
  if (rn) rn.addEventListener('change', function(){ if (rn.value) location.href = rn.value; });

  function esc(s){ return String(s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  var tb = document.getElementById('tracebox');
  function setStatus(h){ var st=document.getElementById('trace-status'); st.innerHTML=h; tb.classList.toggle('open', !!h || document.getElementById('trace-paths').innerHTML!==''); }
  document.getElementById('btn-trace').addEventListener('click', function(){ tb.classList.toggle('open'); });
  document.getElementById('trace-run').addEventListener('click', function(){
    var from = document.getElementById('trace-from').value, to = document.getElementById('trace-to').value;
    var out = document.getElementById('trace-paths'); out.innerHTML='';
    if(!from){ setStatus('Pick a source card.'); return; }
    var paths = [];
    (function dfs(n, path, visited){
      if(paths.length>=25 || path.length>8) return;
      if(to && n===to && path.length){ paths.push(path.slice()); return; }
      if(!to && path.length && !D.edges.some(function(e){return e.s===n && !visited.has(e.d);})){ paths.push(path.slice()); return; }
      D.edges.forEach(function(e){ if(e.s===n && !visited.has(e.d)){ visited.add(e.d); path.push(e); dfs(e.d, path, visited); path.pop(); visited.delete(e.d); } });
    })(from, [], new Set([from]));
    paths.sort(function(a,b){return a.length-b.length;});
    if(!paths.length){ setStatus('No path from <b>'+esc(nodeLabel(from))+'</b>'+(to?' to <b>'+esc(nodeLabel(to))+'</b>':'')+'.'); return; }
    paths.forEach(function(p){
      var d=document.createElement('div');
      var s = esc(nodeLabel(p[0].s));
      p.forEach(function(e){ s += ' <span class="muted">—['+esc(mediumLabel(e.m))+(e.l?' · '+esc(e.l):'')+']→</span> '+esc(nodeLabel(e.d)); });
      d.innerHTML = s;
      d.addEventListener('click', function(){
        Array.prototype.forEach.call(out.children,function(c){c.classList.remove('on');}); d.classList.add('on');
        var ns=new Set(), es=new Set(); p.forEach(function(e){ns.add(e.s);ns.add(e.d);es.add(e.s+'>'+e.d);}); locked='__path__'; highlightSet(ns,es);
      });
      out.appendChild(d);
    });
    setStatus(paths.length+' path'+(paths.length>1?'s':'')+' from <b>'+esc(nodeLabel(from))+'</b>'+(to?' to <b>'+esc(nodeLabel(to))+'</b>':'')+'. Click one to highlight it.');
  });
  document.getElementById('trace-clear').addEventListener('click', function(){ locked=null; clearHL(); document.getElementById('trace-paths').innerHTML=''; document.getElementById('trace-status').innerHTML=''; tb.classList.remove('open'); });

  function download(name, text, type){ var b=new Blob([text],{type:type||'text/plain'}); var a=document.createElement('a'); a.href=URL.createObjectURL(b); a.download=name; document.body.appendChild(a); a.click(); setTimeout(function(){URL.revokeObjectURL(a.href); a.remove();},500); }
  document.getElementById('btn-print').addEventListener('click', function(){ window.print(); });
  document.getElementById('btn-svg').addEventListener('click', function(){ download(D.slug+'.svg', D.svg, 'image/svg+xml'); });
  document.getElementById('btn-csv').addEventListener('click', function(){ download(D.slug+'-patch-sheet.csv', D.csv, 'text/csv'); });
  document.getElementById('btn-html').addEventListener('click', function(){ download(D.slug+'.html', '<!doctype html>\n'+document.documentElement.outerHTML, 'text/html'); });
  document.getElementById('btn-json').addEventListener('click', function(){ download(D.slug+'-project.json', JSON.stringify(D.project, null, 2), 'application/json'); });
})();
"""


def _brand_badge(brand: str) -> str:
    if not brand:
        return ""
    spec = BRANDS.get(brand, {"text": brand.upper(), "bg": "#1f2937", "fg": "#e5e7eb", "style": "bold"})
    if not spec["text"]:
        return ""
    return f'<span class="badge {esc(spec.get("style", ""))}" style="background:{spec["bg"]};color:{spec["fg"]}">{esc(spec["text"])}</span>'


def _tip_html(project: Project, node, cg) -> str:
    n = node
    primary = project.canonical(n)
    detail = primary.detail
    ids = {n.id, primary.id} | {t.id for t in project.nodes if t.ref and project.canon_id(t.id) == primary.id}
    kind = KINDS.get(n.kind, KINDS["other"])
    g = project.group(n.group)
    col = project.column(n.column)
    parts = [f"<h5>{esc(n.title)}</h5>"]
    meta = [kind["label"]]
    if g:
        meta.append(f"group {esc(g.id)} · {esc(g.label)}")
    if col:
        meta.append(esc(col.label))
    parts.append(f'<div class="k">{" · ".join(meta)}</div>')
    if n.ref and primary is not n:
        pg = project.group(primary.group)
        parts.append(f'<div class="k">Same device as the card in group {esc(pg.id if pg else primary.group)} · {esc(pg.label if pg else "")}</div>')
    if n.sub:
        parts.append(f"<div>{esc(n.sub)}</div>")
    for line in n.lines:
        parts.append(f"<div>{esc(line)}</div>")
    if n.note:
        parts.append(f'<div style="margin-top:4px">{esc(n.note)}</div>')
    if n.ports:
        pl = []
        for p in n.ports:
            labels = p.get("labels")
            cnt = len(labels) if isinstance(labels, list) else p.get("count", "")
            pl.append(f"{esc(p.get('name', 'ports'))}{(' ×' + str(cnt)) if cnt else ''} ({esc(project.medium(str(p.get('medium', 'other')))['label'])})")
        parts.append(f'<div style="margin-top:4px"><span class="k">Ports:</span> {", ".join(pl)}</div>')
    d = detail.get("dante")
    if d:
        parts.append(f'<div style="margin-top:4px"><span class="k">Dante:</span> {esc(d["name"])}{(" · " + esc(d["model"])) if d.get("model") else ""} · tx {d["tx"]} / rx {d["rx"]} ({d["rx_subscribed"]} subscribed){(" · " + esc(d["samplerate"]) + " Hz") if d.get("samplerate") else ""}</div>')
    flows = detail.get("dante_flows") or []
    if flows:
        items = []
        for f in sorted(flows, key=lambda f: (f["dir"] != "out", -f["count"])):
            arrow = "→" if f["dir"] == "out" else "←"
            chans = ", ".join(f["channels"][:6]) + (" …" if len(f["channels"]) > 6 else "")
            items.append(f"<li>{arrow} {esc(f['peer'])} · {f['count']} ch <span class='k'>{esc(chans)}</span></li>")
        parts.append("<ul>" + "".join(items) + "</ul>")
    c = detail.get("console")
    if c:
        parts.append(f'<div style="margin-top:4px"><span class="k">Console:</span> {esc(c.get("model") or "")} · {c["inputs_named"]} named inputs' + (" · " + ", ".join(f"{k} {v}" for k, v in c["patch_by_bus"].items()) if c.get("patch_by_bus") else "") + "</div>")
        cats = c.get("categories") or {}
        if cats:
            parts.append('<div class="k">' + " · ".join(f"{esc(k)} {v}" for k, v in sorted(cats.items(), key=lambda kv: -kv[1])) + "</div>")
    chans = detail.get("channels")
    if chans:
        items = [f"<li>{esc(ch['channel'])} {esc(ch['name'])}{(' <span class=k>← ' + esc(ch['source']) + '</span>') if ch.get('source') else ''}</li>" for ch in chans[:16]]
        if len(chans) > 16:
            items.append(f"<li class='k'>… {len(chans) - 16} more</li>")
        parts.append("<ul>" + "".join(items) + "</ul>")
    w = detail.get("waves")
    if w:
        parts.append(f'<div style="margin-top:4px"><span class="k">Waves:</span> {esc(w.get("app") or "")}{(" · " + esc(w["session"])) if w.get("session") else ""} · {len(w["racks"])} racks · {len(w["plugins"])} plugins</div>')
        items = [f"<li>{esc(r['name'])}{(' <span class=k>' + esc(r['input']) + '</span>') if r.get('input') else ''}: {esc(r['chain'] or '—')}</li>" for r in w["racks"][:10]]
        if len(w["racks"]) > 10:
            items.append(f"<li class='k'>… {len(w['racks']) - 10} more racks</li>")
        parts.append("<ul>" + "".join(items) + "</ul>")
    # direct connections
    ins = [l for l in project.links if l.target in ids]
    outs = [l for l in project.links if l.source in ids]
    if ins or outs:
        items = []
        for l in ins:
            s = project.node(l.source)
            items.append(f"<li>← {esc(s.label if s else l.source)} <span class='k'>{esc(project.medium(l.medium)['label'])}{(' · ' + str(l.count) + ' ch') if l.count else ''}{(' · ' + esc(l.label)) if l.label else ''}</span></li>")
        for l in outs:
            t = project.node(l.target)
            items.append(f"<li>→ {esc(t.label if t else l.target)} <span class='k'>{esc(project.medium(l.medium)['label'])}{(' · ' + str(l.count) + ' ch') if l.count else ''}{(' · ' + esc(l.label)) if l.label else ''}</span></li>")
        parts.append("<ul>" + "".join(items) + "</ul>")
    parts.append('<div class="k" style="margin-top:6px">Click to trace everything connected.</div>')
    return "".join(parts)


def _table(headers: List[str], rows: List[List[str]], mono_cols: tuple = ()) -> str:
    if not rows:
        return '<div class="notes">nothing here</div>'
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = []
    for r in rows:
        tds = []
        for i, c in enumerate(r):
            cls = ' class="mono"' if i in mono_cols else ""
            tds.append(f"<td{cls}>{c}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _pill(project: Project, medium: str) -> str:
    spec = project.medium(medium)
    return f'<span class="pill" style="color:{spec["color"]}"><i></i>{esc(spec["label"])}</span>'


def _appendix(project: Project) -> str:
    out: List[str] = []
    sheets = build_patch_sheet(project)
    if sheets:
        blocks = []
        for s in sheets:
            rows_in = [[esc(r.port), _pill(project, r.medium), esc(r.peer), esc(r.peer_port), esc(r.signal), esc(r.source)] for r in s.inputs]
            rows_out = [[esc(r.port), _pill(project, r.medium), esc(r.peer), esc(r.peer_port), esc(r.signal), esc(r.source)] for r in s.outputs]
            ports = f"<small>{esc(' · '.join(s.declared_ports))}</small>" if s.declared_ports else ""
            blocks.append(f'<div class="dev"><h4>{esc(s.node.title)}{ports}</h4>')
            if rows_in:
                blocks.append("<div class='notes'>Inputs</div>" + _table(["Port", "Cable", "From device", "From port", "Signal", "Source"], rows_in, (0, 3)))
            if rows_out:
                blocks.append("<div class='notes'>Outputs</div>" + _table(["Port", "Cable", "To device", "To port", "Signal", "Source"], rows_out, (0, 3)))
            blocks.append("</div>")
        total = sum(len(s.inputs) + len(s.outputs) for s in sheets)
        out.append(f"<details open><summary>Patch sheet <span>{len(sheets)} devices · {total} rows · CSV via the toolbar</span></summary>{''.join(blocks)}</details>")
    cons = project.appendix.get("console") or []
    if cons:
        rows = [[esc(c.get("console", "")), esc(c["channel"]), esc(c["name"]), esc(c.get("color", "")), esc(c.get("icon", "")), esc(c.get("patch", "")), esc(c.get("source", "")), esc(c.get("category", ""))] for c in cons]
        out.append(f"<details><summary>Console input channels <span>{len(rows)} named</span></summary>{_table(['Console', 'Channel', 'Name', 'Color', 'Icon', 'Patch', 'Fed by', 'Category'], rows, (1, 5))}</details>")
    outs = project.appendix.get("console_outputs") or []
    if outs:
        rows = [[esc(o.get("console", "")), esc(o["port"]), esc(o["source"]), esc(o.get("name", "")), esc(o.get("destination", ""))] for o in outs]
        out.append(f"<details><summary>Console output patch <span>{len(rows)} ports</span></summary>{_table(['Console', 'Output port', 'Source bus', 'Bus name', 'Dante destination'], rows, (1, 2))}</details>")
    buses = project.appendix.get("console_buses") or []
    if buses:
        detailed = any(b.get("insert1") or b.get("insert2") or b.get("feeds") for b in buses)
        if detailed:
            rows = [[esc(b.get("console", "")), esc(b["bus"]), esc(b["name"]), esc(b.get("color", "")), esc(b.get("insert1", "")), esc(b.get("insert2", "")),
                     esc(b.get("feeds") or b.get("outputs", ""))] for b in buses]
            out.append(f"<details><summary>Console buses <span>{len(rows)}</span></summary>{_table(['Console', 'Bus', 'Name', 'Color', 'Insert 1', 'Insert 2', 'Feeds → ports / racks'], rows, (1, 4, 5, 6))}</details>")
        else:
            rows = [[esc(b.get("console", "")), esc(b["bus"]), esc(b["name"]), esc(b.get("color", "")), esc(b.get("outputs", ""))] for b in buses]
            out.append(f"<details><summary>Console buses <span>{len(rows)}</span></summary>{_table(['Console', 'Bus', 'Name', 'Color', 'Output ports'], rows, (1, 4))}</details>")
    racks = project.appendix.get("console_racks") or []
    if racks:
        rows = [[esc(r.get("console", "")), esc(r["rack"]), esc(r.get("fed_by", "")), esc(r.get("returns_to", "")), esc(r.get("status", ""))] for r in racks]
        closed = sum(1 for r in racks if str(r.get("status", "")).startswith("OK"))
        out.append(f"<details><summary>Console racks <span>{len(rows)} rack I/O · {closed} closed insert loops</span></summary>{_table(['Console', 'Rack I/O', 'Fed by', 'Returns to', 'Loop'], rows, (1, 2, 3))}</details>")
    dcas = project.appendix.get("console_dcas") or []
    if dcas:
        rows = [[esc(d.get("console", "")), esc(d["dca"]), esc(d.get("name", "")), esc(d.get("color", "")), esc(d.get("icon", ""))] for d in dcas]
        out.append(f"<details><summary>Console DCAs <span>{len(rows)} · names only, membership is not in the export</span></summary>{_table(['Console', 'DCA', 'Name', 'Color', 'Icon'], rows, (1,))}</details>")
    cwarn = project.appendix.get("console_warnings") or []
    if cwarn:
        items = "".join(f"<li><b>{esc(w.get('console', ''))}</b> · {esc(w.get('warning', ''))}</li>" for w in cwarn)
        out.append(f"<details open><summary>Console warnings <span>{len(cwarn)} things to check in the console patch</span></summary><ul class='notes'>{items}</ul></details>")
    devs = project.appendix.get("dante_devices") or []
    if devs:
        rows = [[esc(d["device"]), esc(d["dante_name"]), esc(d["model"]), str(d["tx"]), str(d["rx"]), str(d["subscribed"]), esc(d.get("samplerate", "")), esc(d.get("latency", ""))] for d in devs]
        out.append(f"<details><summary>Dante devices <span>{len(rows)}</span></summary>{_table(['Card', 'Dante name', 'Model', 'Tx', 'Rx', 'Subscribed', 'Rate', 'Latency µs'], rows, (1,))}</details>")
    dante = project.appendix.get("dante") or []
    if dante:
        rows = [[esc(d["rx_device"]), esc(d["rx_channel"]), esc(d["tx_device"]), esc(d["tx_channel"])] for d in dante]
        out.append(f"<details><summary>Dante routing <span>{len(rows)} subscriptions</span></summary>{_table(['Receiver', 'Rx channel', 'Transmitter', 'Tx channel'], rows, (1, 3))}</details>")
    waves = project.appendix.get("waves") or []
    if waves:
        rows = [[esc(w["host"]), esc(w["rack"]), esc(w["input"]), esc(w["output"]), esc(w["chain"]), esc(w["notes"])] for w in waves]
        out.append(f"<details><summary>Waves racks <span>{len(rows)}</span></summary>{_table(['Host', 'Rack', 'Input', 'Output', 'Plugin chain', 'Notes'], rows, (2, 3))}</details>")
    if project.notes:
        items = "".join(f"<li>{esc(n)}</li>" for n in project.notes)
        out.append(f"<details><summary>Build notes <span>{len(project.notes)}</span></summary><ul class='notes'>{items}</ul></details>")
    return "".join(out)


def _nav_html(nav: Optional[Dict[str, Any]]) -> str:
    if not nav:
        return ""
    out: List[str] = []
    rooms = [r for r in (nav.get("rooms") or []) if isinstance(r, dict)]
    current = str(nav.get("current") or "")
    if len(rooms) > 1:
        opts = "".join(
            f'<option value="{esc(r.get("url", ""))}"{" selected" if str(r.get("id")) == current else ""}>{esc(r.get("name") or r.get("id"))}</option>'
            for r in rooms
        )
        out.append(f'<label class="no-print" style="position:absolute;left:-9999px" for="room-nav">Room</label><select id="room-nav" title="Switch room">{opts}</select>')
    for link in nav.get("links") or []:
        if isinstance(link, dict) and link.get("url"):
            out.append(f'<a class="tb" href="{esc(link["url"])}">{esc(link.get("label") or link["url"])}</a>')
    return "".join(out)


def _head_extra(base_url: str, sw: bool) -> str:
    if not sw:
        return ""
    return f'<meta name="theme-color" content="#0b1020"><link rel="manifest" href="{esc(base_url)}manifest.webmanifest"><link rel="apple-touch-icon" href="{esc(base_url)}apple-touch-icon.png">'


def _root_attr(base_url: str, sw: bool) -> str:
    return f' data-app-root="{esc(base_url)}"' if sw else ""


def render_html(project: Project, layout: Layout, *, nav: Optional[Dict[str, Any]] = None, base_url: str = "", sw: bool = False, highlight_bridge: bool = True, doc: Optional[Dict[str, Any]] = None) -> str:
    W, H = layout.width, layout.height
    planned = planned_ids(project, doc)
    slug = project.meta.slug or "signal-flow"
    css = CSS % {
        "bg": BG, "panel": PANEL, "border": PANEL_BORDER, "text": TEXT, "muted": MUTED, "accent": ACCENT, "font": FONT,
        "gpad": GROUP_PAD, "cpy": 8, "cpx": 11, "badge": 64,
        "pw": int(W + 48), "ph": int(H + 190 + (0 if not project.options.appendix_print else 1200)),
        "appendix_print": "" if project.options.appendix_print else "display:none !important",
    }
    eyebrow = " · ".join(p for p in (project.meta.org, project.meta.system) if p)
    parts: List[str] = []
    parts.append(f'<!doctype html>\n<html lang="en"{_root_attr(base_url, sw)}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>{esc(project.meta.title)} · {esc(project.meta.org)}</title>{_head_extra(base_url, sw)}<script>{SMOKE_JS}</script><style>{css}</style></head><body>')
    # toolbar
    options = "".join(f'<option value="{esc(cg.node.id)}">{esc(cg.node.title)}</option>' for cg in sorted(layout.cards.values(), key=lambda c: c.node.title.lower()) if not cg.node.ref)
    parts.append(
        '<div class="toolbar no-print">'
        + _nav_html(nav)
        + '<button id="btn-trace" title="Find signal paths between two cards">Trace</button>'
        '<button id="btn-csv" title="Patch sheet as CSV">Patch CSV</button>'
        '<button id="btn-svg" title="Diagram as SVG">SVG</button>'
        '<button id="btn-json" title="The project file behind this page">JSON</button>'
        '<button id="btn-html" title="Save this page">HTML</button>'
        '<button id="btn-print" title="Print or save as PDF">Print / PDF</button>'
        "</div>"
        '<div class="tracebox" id="tracebox"><h4>Trace a signal</h4>'
        f'<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center"><select id="trace-from"><option value="">from…</option>{options}</select>'
        f'<select id="trace-to"><option value="">to… (any end)</option>{options}</select>'
        '<button id="trace-run" style="background:#1d2a4a;border:1px solid var(--border);color:#fff;font:inherit;font-size:11px;padding:4px 9px;border-radius:6px;cursor:pointer">Find paths</button>'
        '<button id="trace-clear" style="background:transparent;border:1px solid var(--border);color:var(--muted);font:inherit;font-size:11px;padding:4px 9px;border-radius:6px;cursor:pointer">Clear</button></div>'
        '<div id="trace-status" style="margin-top:6px"></div><div class="paths" id="trace-paths" style="margin-top:4px"></div></div>'
    )
    parts.append('<div class="page">')
    parts.append(f'<div class="eyebrow">{esc(eyebrow)}</div><h1>{esc(project.meta.title)}</h1>')
    if project.meta.intro:
        parts.append(f'<p class="intro">{esc(project.meta.intro)}</p>')
    parts.append(f'<div class="canvas" style="width:{W:.0f}px;height:{H:.0f}px">')
    # groups
    for g in layout.groups:
        b = g.box
        parts.append(f'<div class="group{" auto" if g.auto else ""}" style="left:{b.x:.0f}px;top:{b.y:.0f}px;width:{b.w:.0f}px;height:{b.h:.0f}px"><div class="gh">{("<b>" + esc(g.letter) + "</b>") if g.letter else ""}{esc(g.label)}</div></div>')
        if g.note_box and g.note:
            nb = g.note_box
            parts.append(f'<div class="gnote" style="left:{nb.x:.0f}px;top:{nb.y:.0f}px;width:{nb.w:.0f}px">{esc(g.note)}</div>')
    # chevrons
    for c in layout.columns:
        b = c.box
        parts.append(f'<div class="chev" style="left:{b.x:.0f}px;top:{b.y:.0f}px;width:{b.w:.0f}px;height:{b.h:.0f}px"><b>{esc(c.number)}</b>{esc(c.label)}</div>')
    # svg overlay
    parts.append(f'<svg class="overlay" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}">{svg_defs(project, layout)}{svg_spine(project, layout)}{svg_links(project, layout)}</svg>')
    # cards
    tips: Dict[str, str] = {}
    for cg in layout.cards.values():
        n, b = cg.node, cg.box
        badge = _brand_badge(n.brand)
        sub = "".join(f'<div class="s">{esc(l)}</div>' for l in cg.sub_lines + cg.extra_lines)
        title = "<br>".join(esc(l) for l in cg.title_lines) or esc(n.title)
        c = cg.color
        vars_ = f"--c:{c};--c42:{rgba(c, 0.42)};--c10:{rgba(c, 0.10)};--c28:{rgba(c, 0.28)};--c60:{rgba(c, 0.6)};--cb:{rgba(c, 0.45)}"
        parts.append(
            f'<div class="card{" hasbadge" if badge else ""}{" planned" if n.id in planned else ""}" data-id="{esc(n.id)}" data-title="{esc(n.title)}" style="{vars_};left:{b.x:.0f}px;top:{b.y:.0f}px;width:{b.w:.0f}px;height:{b.h:.0f}px">'
            f'{badge}<div class="t">{title}</div>{sub}</div>'
        )
        tips[n.id] = _tip_html(project, n, cg)
    # key
    if layout.key:
        k = layout.key
        b = k.box
        parts.append(f'<div class="key" style="left:{b.x:.0f}px;top:{b.y:.0f}px;width:{b.w:.0f}px;height:{b.h:.0f}px"><div class="gh">Key</div></div>')
        y0 = b.y + GROUP_HEADER_H + 4
        for i, (kind, label, color) in enumerate(k.kinds):
            parts.append(f'<div class="key-row" style="left:{b.x + GROUP_PAD:.0f}px;top:{y0 + i * KEY_ROW_H - 1:.0f}px"><span class="sw" style="display:inline-block;width:12px;height:12px;border-radius:3px;background:{rgba(color, 0.9)};box-shadow:0 0 8px {rgba(color, 0.5)}"></span>{esc(label)}</div>')
        mx = b.x + b.w / 2
        for i, (m, label, color, dash) in enumerate(k.media):
            d = f' stroke-dasharray="{dash}"' if dash else ""
            parts.append(f'<div class="key-row" style="left:{mx:.0f}px;top:{y0 + i * KEY_ROW_H - 1:.0f}px;gap:8px"><svg width="34" height="6"><line x1="0" y1="3" x2="34" y2="3" stroke="{color}" stroke-width="2"{d}/></svg>{esc(label)}</div>')
        fy = y0 + max(len(k.kinds), len(k.media)) * KEY_ROW_H + 8
        if k.footnote_lines:
            parts.append(f'<div class="key-foot" style="left:{b.x + GROUP_PAD:.0f}px;top:{fy:.0f}px;width:{b.w - 2 * GROUP_PAD:.0f}px">{esc(project.meta.footnote)}</div>')
    parts.append('<div class="tip" id="tip"></div>')
    parts.append("</div>")  # canvas
    if project.options.appendix:
        parts.append(f'<div class="appendix">{_appendix(project)}</div>')
    parts.append("</div>")  # page
    data = {
        "slug": slug,
        "edges": graph_json(project),
        "refs": project.ref_map(),
        "tips": tips,
        "media": {m: {"label": project.medium(m)["label"]} for m in project.used_media()},
        "svg": render_svg(project, layout, doc=doc),
        "csv": patch_sheet_csv(project),
        "project": project.to_dict(),
        "bridge": bool(highlight_bridge),
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    parts.append(f"<script>window.SF_DATA={payload};</script><script>{JS}</script>")
    if sw:
        parts.append(f"<script>{SW_JS}</script>")
    parts.append("</body></html>")
    return "".join(parts)


# ===================================================================== viewer pages (v0.3)

VIEW_CSS = """
:root{--bg:%(bg)s;--panel:#111828;--border:%(border)s;--text:%(text)s;--muted:%(muted)s;--accent:%(accent)s;--ok:#2fd4b4;--warn:#ff9548;--err:#f06aa8}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%%;text-size-adjust:100%%}
html,body{margin:0;background:var(--bg);color:var(--text);font:13px/1.45 %(font)s;-webkit-font-smoothing:antialiased}
a{color:var(--accent)}
.wrap{max-width:1180px;margin:0 auto;padding:calc(14px + env(safe-area-inset-top,0px)) calc(14px + env(safe-area-inset-right,0px)) calc(28px + env(safe-area-inset-bottom,0px)) calc(14px + env(safe-area-inset-left,0px))}
.eyebrow{font-size:10px;letter-spacing:1.8px;text-transform:uppercase;color:var(--muted);font-weight:600}
h1{font-size:22px;margin:6px 0 4px;letter-spacing:-.2px}
h2{font-size:12px;letter-spacing:1.4px;text-transform:uppercase;color:var(--muted);margin:22px 0 8px}
.sub{color:var(--muted)}
.nav{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 4px}
.nav a,.nav button,.nav select{display:inline-flex;align-items:center;min-height:36px;padding:6px 11px;border:1px solid var(--border);border-radius:8px;background:#161d2e;color:var(--text);text-decoration:none;font:inherit;font-size:12.5px;cursor:pointer}
.nav a:hover,.nav button:hover{border-color:var(--accent)}
.nav a[aria-current=page]{border-color:var(--accent);background:rgba(142,162,255,.14)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
.box{border:1px solid var(--border);border-radius:10px;background:var(--panel);padding:12px 14px}
.box h3{margin:0 0 4px;font-size:15px}
.box h3 a{color:var(--text);text-decoration:none}
.box .links{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.box .links a{font-size:12.5px;padding:4px 9px;border:1px solid var(--border);border-radius:7px;text-decoration:none;color:var(--text)}
.pill{display:inline-block;padding:1px 7px;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:.7px;text-transform:uppercase;border:1px solid currentColor;margin-right:6px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%%;background:currentColor;margin-right:5px;vertical-align:middle}
.planned{display:inline-block;padding:0 6px;border:1px dashed var(--warn);color:var(--warn);border-radius:4px;font-size:10.5px;margin-left:6px}
dl.kv{display:grid;grid-template-columns:140px minmax(0,1fr);gap:4px 12px;margin:0}
dl.kv dt{color:var(--muted)}
dl.kv dd{margin:0;word-break:break-word}
table.t{width:100%%;border-collapse:collapse;font-size:12.5px}
table.t th{text-align:left;color:var(--muted);font-weight:600;font-size:10.5px;letter-spacing:.7px;text-transform:uppercase;padding:6px 8px;border-bottom:1px solid var(--border)}
table.t td{padding:6px 8px;border-bottom:1px solid rgba(255,255,255,.05);vertical-align:top}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}
.qr{background:#fff;border-radius:10px;padding:8px;display:inline-block;max-width:220px}
.qr svg{display:block;width:100%%;height:auto}
.photos{display:flex;flex-wrap:wrap;gap:8px}
.photos img{width:150px;height:110px;object-fit:cover;border-radius:8px;border:1px solid var(--border)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.pt-block{border:1px solid var(--border);border-radius:10px;margin:0 0 10px;overflow:hidden;break-inside:avoid;page-break-inside:avoid}
.pt-head{display:flex;justify-content:center;align-items:center;gap:8px;padding:7px 10px;background:#0f1525;border-bottom:1px solid var(--border)}
.pt-head b a{color:var(--text);text-decoration:none}
.pt-cols{display:grid;grid-template-columns:1fr}
@media (min-width:900px){.pt-cols{grid-template-columns:1fr 1fr}.pt-cols>div+div{border-left:1px solid var(--border)}}
.pt-sec{padding:5px 10px;font-size:10.5px;color:var(--muted);background:rgba(255,255,255,.015);border-bottom:1px solid rgba(255,255,255,.05)}
.pt-t{width:100%%;border-collapse:collapse;font-size:12.5px;table-layout:fixed}
.pt-t th{font-weight:600;color:var(--muted);font-size:10.5px;text-align:left;padding:5px 8px}
.pt-t td{padding:6px 8px;border-top:1px solid rgba(255,255,255,.04);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pt-t td.ar{width:22px;color:var(--muted);text-align:center;padding:0}
.pt-t td.pn{width:70px;color:var(--muted)}
.pt-t .none{color:#4a5368}
.pt-t .ovl{font-style:italic;color:var(--muted)}
.live{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border);border-radius:999px;padding:2px 10px;font-size:11.5px}
.live .dot{color:var(--ok)}
@media (hover:none),(pointer:coarse){.nav a,.nav button,.nav select{min-height:44px;min-width:44px}.pt-t td{padding:10px 8px}summary{min-height:44px;display:flex;align-items:center}button,select,a.btn{min-height:44px;min-width:44px}}
@media print{
  html,body{background:#fff !important;color:#000 !important}
  .no-print{display:none !important}
  .box,.pt-block{border-color:#ccc;background:#fff}
  .pt-head,.pt-sec{background:#f3f5f9;color:#000}
  .pt-t td,.pt-t th,table.t td,table.t th{color:#000;border-color:#ddd}
  a{color:#000;text-decoration:none}
}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;animation:none!important;scroll-behavior:auto!important}}
"""


def _view_css() -> str:
    return VIEW_CSS % {"bg": BG, "border": PANEL_BORDER, "text": TEXT, "muted": MUTED, "accent": ACCENT, "font": FONT}


def _vocab_tables() -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    try:
        from . import vocab as _v

        return _v.KINDS, _v.MEDIA, _v.DISCIPLINES
    except Exception:  # pragma: no cover - vocab not importable yet
        from .model import MEDIA as _M

        return dict(KINDS), dict(_M), {"other": {"label": "Other", "color": "#9aa3b5", "letter": "X"}}


def _discipline(dev: Dict[str, Any]) -> str:
    kinds, _media, _discs = _vocab_tables()
    return str(dev.get("discipline") or (kinds.get(str(dev.get("kind") or "")) or {}).get("discipline") or "other")


def _disc_pill(dev: Dict[str, Any]) -> str:
    _kinds, _media, discs = _vocab_tables()
    d = _discipline(dev)
    spec = discs.get(d) or {"label": d, "color": "#9aa3b5"}
    return f'<span class="pill" style="color:{esc(spec.get("color", "#9aa3b5"))}">{esc(spec.get("label", d))}</span>'


def _medium_dot(medium: Optional[str]) -> str:
    _kinds, media, _discs = _vocab_tables()
    spec = media.get(str(medium or "")) or media.get("other") or {"color": "#9aa3b5", "label": medium or ""}
    return f'<span class="dot" style="color:{esc(spec.get("color", "#9aa3b5"))}" title="{esc(spec.get("label", medium or ""))}"></span>'


def _model_line(dev: Dict[str, Any]) -> str:
    return (f'{dev.get("manufacturer") or ""} {dev.get("model") or ""}').strip() or str(dev.get("sub") or "")


def _title(dev: Dict[str, Any]) -> str:
    t = str(dev.get("name") or dev.get("id") or "")
    if dev.get("count"):
        t += f" ×{dev.get('count')}"
    if dev.get("suffix"):
        t += f" {dev.get('suffix')}"
    return t


def _mac(value: Any) -> str:
    """MAC for display, normalized to aa:bb:cc:dd:ee:ff (FR-NET-04); raw text if unparseable."""
    text = str(value or "")
    if not text:
        return ""
    try:
        from .network import normalize_mac
    except Exception:  # pragma: no cover - network module missing
        return text
    try:
        return normalize_mac(text) or text
    except Exception:  # pragma: no cover - defensive
        return text


def _q(s: Any) -> str:
    return quote(str(s), safe="")


class _Links:
    """Relative links between viewer pages (server tree ``p/<n>/…``) or build files."""

    def __init__(self, style: str, here: str, default_room: str) -> None:
        self.style = style  # "viewer" | "build"
        self.here = here  # "rooms" | "room-patch" | "device"
        self.default_room = default_room

    def _up(self) -> str:
        if self.style == "build":
            return "../" if self.here in ("rooms", "device") else "../../"
        return {"rooms": "", "device": "../", "room-patch": "../../"}.get(self.here, "")

    def rooms(self) -> str:
        return self._up() + ("rooms/index.html" if self.style == "build" else "rooms")

    def room_map(self, room: str) -> str:
        if self.style == "build":
            return self._up() + f"rooms/{_q(room)}/index.html"
        return self._up() + f"r/{_q(room or self.default_room)}"

    def room_patch(self, room: str) -> str:
        if self.style == "build":
            return self._up() + f"rooms/{_q(room)}/patch.html"
        return self._up() + f"r/{_q(room)}/patch"

    def device(self, dev: str) -> str:
        if self.style == "build":
            return self._up() + f"devices/{_q(dev)}.html"
        return self._up() + f"d/{_q(dev)}"


def _page(title: str, body: str, *, base_url: str = "", sw: bool = False, extra_css: str = "", body_class: str = "", wrap: bool = True) -> str:
    cls = f' class="{esc(body_class)}"' if body_class else ""
    inner = f'<div class="wrap">{body}</div>' if wrap else body
    return (
        f'<!doctype html>\n<html lang="en"{_root_attr(base_url, sw)}><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        f"<title>{esc(title)}</title>{_head_extra(base_url, sw)}<script>{SMOKE_JS}</script><style>{_view_css()}{extra_css}</style></head>"
        f"<body{cls}>{inner}"
        + (f"<script>{SW_JS}</script>" if sw else "")
        + "</body></html>"
    )


def _doc_rooms(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    rooms = [r for r in doc.get("rooms") or [] if isinstance(r, dict) and r.get("id")]
    return sorted(rooms, key=lambda r: (int(r.get("order") or 0), rooms.index(r)))


def _default_room(doc: Dict[str, Any]) -> str:
    rooms = _doc_rooms(doc)
    want = str((doc.get("settings") or {}).get("default_room") or "")
    if want and any(r.get("id") == want for r in rooms):
        return want
    return str(rooms[0]["id"]) if rooms else ""


def _devices(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [d for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id") and not d.get("auto")]


def _find(lst: Any, eid: str) -> Optional[Dict[str, Any]]:
    for e in lst or []:
        if isinstance(e, dict) and e.get("id") == eid:
            return e
    return None


def _org_eyebrow(doc: Dict[str, Any], extra: str = "") -> str:
    meta = doc.get("meta") or {}
    bits = [str(meta.get("org") or ""), extra]
    return " · ".join(b for b in bits if b)


def _editor_link(base_url: str, project: str, room: str, view: str, sel: str = "") -> str:
    tail = f"#/{_q(project)}/{_q(room)}/{view}" + (f"?sel={sel}" if sel else "")
    return f"{base_url}{tail}"


def render_room_index(doc: Dict[str, Any], *, project: str, base_url: str = "", sw: bool = False, link_style: str = "viewer") -> str:
    L = _Links(link_style, "rooms", _default_room(doc))
    venues = [v for v in doc.get("venues") or [] if isinstance(v, dict)]
    rooms = _doc_rooms(doc)
    devices = _devices(doc)
    cables = [c for c in doc.get("cables") or [] if isinstance(c, dict)]
    by_room: Dict[str, List[Dict[str, Any]]] = {}
    for d in devices:
        by_room.setdefault(str(d.get("room") or ""), []).append(d)
    dev_room = {d["id"]: str(d.get("room") or "") for d in devices}
    out: List[str] = []
    meta = doc.get("meta") or {}
    out.append(f'<div class="eyebrow">{esc(_org_eyebrow(doc, "Rooms"))}</div><h1>{esc(meta.get("title") or project)}</h1>')
    out.append('<nav class="nav no-print" aria-label="Viewer">')
    if link_style != "build":
        out.append(f'<a href="{esc(_editor_link(base_url, project, _default_room(doc), "map"))}">Open editor</a>')
    out.append("</nav>")

    def room_card(r: Dict[str, Any]) -> str:
        rid = str(r["id"])
        devs = by_room.get(rid, [])
        n_cab = sum(1 for c in cables if dev_room.get(str((c.get("from") or {}).get("device"))) == rid or dev_room.get(str((c.get("to") or {}).get("device"))) == rid)
        kind = str(r.get("kind") or "").replace("_", " ")
        items = "".join(f'<li><a href="{esc(L.device(d["id"]))}">{esc(_title(d))}</a> <span class="sub">{esc(_model_line(d))}</span></li>' for d in devs[:60])
        more = f'<li class="sub">… {len(devs) - 60} more</li>' if len(devs) > 60 else ""
        return (
            f'<section class="box" data-room="{esc(rid)}"><h3><a href="{esc(L.room_map(rid))}">{esc(r.get("name") or rid)}</a></h3>'
            f'<div class="sub">{esc(" · ".join(x for x in (str(r.get("code") or ""), kind, f"{len(devs)} devices", f"{n_cab} cables") if x))}</div>'
            f'<div class="links"><a href="{esc(L.room_map(rid))}">Map</a><a href="{esc(L.room_patch(rid))}">Patch table</a></div>'
            f'<details style="margin-top:8px"><summary class="sub">Devices</summary><ul style="margin:6px 0 0;padding-left:18px">{items}{more}</ul></details></section>'
        )

    shown = set()
    for v in venues:
        vr = [r for r in rooms if r.get("venue") == v.get("id")]
        if not vr:
            continue
        out.append(f'<h2>{esc(v.get("name") or v.get("id"))}</h2><div class="cards">')
        for r in vr:
            shown.add(r["id"])
            out.append(room_card(r))
        out.append("</div>")
    rest = [r for r in rooms if r["id"] not in shown]
    if rest:
        out.append('<h2>Rooms</h2><div class="cards">' + "".join(room_card(r) for r in rest) + "</div>")
    shared = by_room.get("", [])
    if shared:
        rows = "".join(
            f'<tr><td><a href="{esc(L.device(d["id"]))}">{esc(_title(d))}</a></td><td>{esc(_model_line(d))}</td><td>{esc(d.get("status") or "installed")}</td><td>{esc(str((_find(doc.get("locations"), str(d.get("location") or "")) or {}).get("name") or ""))}</td></tr>'
            for d in shared
        )
        out.append(f'<h2>Shared inventory</h2><div class="scroll"><table class="t"><thead><tr><th scope="col">Device</th><th scope="col">Model</th><th scope="col">Status</th><th scope="col">Location</th></tr></thead><tbody>{rows}</tbody></table></div>')
    if not rooms:
        out.append('<p class="sub">No rooms yet.</p>')
    return _page(f"Rooms · {meta.get('org') or project}", "".join(out), base_url=base_url, sw=sw)


def _port_rows_for_device(doc: Dict[str, Any], dev: Dict[str, Any], L: _Links, overlay: Optional[Dict[str, Any]]) -> str:
    devs = {d["id"]: d for d in _devices(doc)}
    cables = [c for c in doc.get("cables") or [] if isinstance(c, dict) and not c.get("auto")]
    labels = ((overlay or {}).get("port_labels") or {}).get(dev["id"]) or {}
    rows: List[str] = []

    def peer_html(c: Dict[str, Any], mine: str) -> Tuple[str, str]:
        other = c.get("to") if mine == "from" else c.get("from")
        other = other or {}
        pd = devs.get(str(other.get("device")))
        pname = ""
        if pd and other.get("port"):
            pp = next((p for p in pd.get("ports") or [] if p.get("id") == other.get("port")), None)
            pname = str((pp or {}).get("label") or (pp or {}).get("name") or other.get("port"))
        elif other.get("port"):
            pname = str(other.get("port"))
        link = f'<a href="{esc(L.device(pd["id"]))}">{esc(pd.get("name") or pd["id"])}</a>' if pd else esc(other.get("device") or "")
        return link, esc(pname or "device")

    for p in dev.get("ports") or []:
        if not isinstance(p, dict):
            continue
        mine_cables = []
        for c in cables:
            f, t = c.get("from") or {}, c.get("to") or {}
            if f.get("device") == dev["id"] and f.get("port") == p.get("id"):
                mine_cables.append((c, "from"))
            elif t.get("device") == dev["id"] and t.get("port") == p.get("id"):
                mine_cables.append((c, "to"))
        label = p.get("label") or ""
        lab_html = esc(label) if label else (f'<span class="ovl" title="from import">{esc(labels[p["id"]])}</span>' if p.get("id") in labels else '<span class="none">—</span>')
        arrow = {"in": "←", "out": "→"}.get(str(p.get("dir")), "↔")
        if not mine_cables:
            rows.append(f'<tr><td>{_medium_dot(p.get("medium"))}{esc(p.get("name") or p.get("id"))}</td><td>{lab_html}</td><td class="sub">{arrow}</td><td class="none">not patched</td><td></td><td></td></tr>')
        for c, mine in mine_cables:
            link, pname = peer_html(c, mine)
            rows.append(
                f'<tr><td>{_medium_dot(p.get("medium"))}{esc(p.get("name") or p.get("id"))}</td><td>{lab_html}</td><td class="sub">{"→" if mine == "from" else "←"}</td>'
                f'<td>{link}</td><td>{pname}</td><td class="mono">{esc(c.get("tag") or "")}</td></tr>'
            )
        if p.get("note"):
            rows.append(f'<tr><td></td><td colspan="5" class="sub">{esc(p["note"])}</td></tr>')
    for c in cables:
        f, t = c.get("from") or {}, c.get("to") or {}
        for end, other_end in (("from", "to"), ("to", "from")):
            e = c.get(end) or {}
            if e.get("device") == dev["id"] and not e.get("port"):
                link, pname = peer_html(c, end)
                rows.append(f'<tr><td>{_medium_dot(c.get("medium"))}<span class="sub">device</span></td><td></td><td class="sub">{"→" if end == "from" else "←"}</td><td>{link}</td><td>{pname}</td><td class="mono">{esc(c.get("tag") or "")}</td></tr>')
    if not rows:
        return '<p class="sub">No ports.</p>'
    return ('<div class="scroll"><table class="t"><thead><tr><th scope="col">Port</th><th scope="col">Label</th><th scope="col"></th>'
            '<th scope="col">Connected to</th><th scope="col">Peer port</th><th scope="col">Cable</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")


def render_device_page(doc: Dict[str, Any], device_id: str, *, project: str, overlay: Optional[Dict[str, Any]] = None, base_url: str = "", qr_svg: str = "", sw: bool = False, link_style: str = "viewer") -> str:
    dev = _find(_devices(doc), device_id)
    L = _Links(link_style, "device", _default_room(doc))
    meta = doc.get("meta") or {}
    if dev is None:
        return _page("Device not found", f'<h1>Device not found</h1><p class="sub">{esc(device_id)}</p><p><a href="{esc(L.rooms())}">All rooms</a></p>', base_url=base_url, sw=sw)
    kinds, _media, _discs = _vocab_tables()
    room = _find(doc.get("rooms"), str(dev.get("room") or ""))
    loc = _find(doc.get("locations"), str(dev.get("location") or ""))
    out: List[str] = []
    out.append(f'<div class="eyebrow">{esc(_org_eyebrow(doc, str((room or {}).get("name") or "Shared inventory")))}</div>')
    planned = '<span class="planned">planned</span>' if dev.get("status") == "planned" else ""
    out.append(f'<h1>{esc(_title(dev))}{planned}</h1><div class="sub">{_disc_pill(dev)}{esc(_model_line(dev))}</div>')
    out.append('<nav class="nav no-print" aria-label="Viewer">')
    if room:
        out.append(f'<a href="{esc(L.room_map(str(room["id"])))}">{esc(room.get("name") or room["id"])} map</a><a href="{esc(L.room_patch(str(room["id"])))}">Patch table</a>')
    out.append(f'<a href="{esc(L.rooms())}">All rooms</a>')
    if link_style != "build":
        out.append(f'<a href="{esc(_editor_link(base_url, project, str((room or {}).get("id") or ""), "patch", "device:" + str(dev["id"])))}">Open in editor</a>')
    out.append("</nav>")
    # identity
    kv: List[Tuple[str, str]] = [("Kind", esc((kinds.get(str(dev.get("kind") or "")) or {}).get("label") or dev.get("kind") or ""))]
    kv.append(("Status", esc(dev.get("status") or "installed")))
    if room:
        kv.append(("Room", f'<a href="{esc(L.room_map(str(room["id"])))}">{esc(room.get("name") or room["id"])}</a>'))
    if loc:
        kv.append(("Location", esc(loc.get("name") or loc["id"])))
    rk = dev.get("rack") if isinstance(dev.get("rack"), dict) else None
    if rk and rk.get("id"):
        rack = _find(doc.get("racks"), str(rk.get("id")))
        h_ = int(rk.get("height") or 1)
        u = rk.get("u")
        span = f"U{u}" if h_ <= 1 or u in (None, "") else f"U{u}–U{int(u) + h_ - 1}"
        kv.append(("Rack", esc(f'{(rack or {}).get("name") or rk.get("id")} · {span} · {rk.get("face") or "front"}' + (f' · {rk.get("side")}' if rk.get("side") and rk.get("side") != "full" else ""))))
    if dev.get("code"):
        kv.append(("Label code", esc(dev["code"])))
    inv = dev.get("inventory") if isinstance(dev.get("inventory"), dict) else {}
    for key, label in (("serial", "Serial"), ("asset_tag", "Asset tag"), ("firmware", "Firmware"), ("warranty_until", "Warranty until")):
        if inv.get(key):
            kv.append((label, f'<span class="mono">{esc(inv[key])}</span>'))
    dmx = dev.get("dmx") if isinstance(dev.get("dmx"), dict) else {}
    if dmx.get("universe") or dmx.get("address"):
        kv.append(("DMX", esc(f'universe {dmx.get("universe", "?")} · address {dmx.get("address", "?")}' + (f' · {dmx.get("footprint")} ch' if dmx.get("footprint") else "") + (f' · {dmx.get("mode")}' if dmx.get("mode") else ""))))
    if dev.get("sub"):
        kv.append(("Notes line", esc(dev["sub"])))
    body_kv = "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in kv)
    qr = ""
    if qr_svg:
        qr = f'<div><div class="qr" aria-label="QR code for this page">{qr_svg}</div><div class="sub" style="font-size:11px;margin-top:4px">Scan to open this page</div></div>'
    out.append(f'<div style="display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start;margin-top:14px"><dl class="kv" style="flex:1;min-width:260px">{body_kv}</dl>{qr}</div>')
    if dev.get("note"):
        out.append(f'<h2>Notes</h2><p style="white-space:pre-wrap">{esc(dev["note"])}</p>')
    # interfaces (manual + overlay)
    ifaces = [dict(i, source="manual") for i in dev.get("interfaces") or [] if isinstance(i, dict)]
    for i in ((overlay or {}).get("interfaces") or {}).get(dev["id"]) or []:
        if isinstance(i, dict) and not any(x.get("role") == i.get("role") and x.get("ip") for x in ifaces):
            ifaces.append(i)
    if ifaces:
        nets = {str(n.get("id")): n for n in doc.get("networks") or [] if isinstance(n, dict)}
        rows = "".join(
            f'<tr><td>{esc(i.get("id") or "")}</td><td>{esc(i.get("role") or "")}</td><td class="mono">{esc(i.get("ip") or "")}{("/" + esc(i.get("prefix"))) if i.get("prefix") not in (None, "") else ""}</td>'
            f'<td>{esc(i.get("vlan") or "")}</td><td>{esc((nets.get(str(i.get("network"))) or {}).get("name") or i.get("network") or "")}</td><td class="mono">{esc(_mac(i.get("mac")))}</td><td>{esc(i.get("hostname") or "")}</td><td class="sub">{esc(i.get("source") or "")}</td></tr>'
            for i in ifaces
        )
        out.append('<h2>Network</h2><div class="scroll"><table class="t"><thead><tr><th scope="col">Interface</th><th scope="col">Role</th><th scope="col">IP</th><th scope="col">VLAN</th>'
                   f'<th scope="col">Network</th><th scope="col">MAC</th><th scope="col">Hostname</th><th scope="col">Source</th></tr></thead><tbody>{rows}</tbody></table></div>')
    out.append("<h2>Ports & patching</h2>" + _port_rows_for_device(doc, dev, L, overlay))
    atts = [a for a in doc.get("attachments") or [] if isinstance(a, dict) and a.get("device") == dev["id"]]
    if atts and link_style != "build":
        items = []
        for a in atts:
            url = f'{base_url}api/v2/projects/{_q(project)}/files/{_q(a.get("id"))}/{_q(a.get("name") or "file")}'
            if str(a.get("mime") or "").startswith("image/"):
                items.append(f'<a href="{esc(url)}"><img src="{esc(url)}" alt="{esc(a.get("name") or "")}" loading="lazy"></a>')
            else:
                items.append(f'<a href="{esc(url)}">{esc(a.get("name") or a.get("id"))}</a>')
        out.append('<h2>Photos & documents</h2><div class="photos">' + "".join(items) + "</div>")
    return _page(f"{_title(dev)} · {meta.get('org') or project}", "".join(out), base_url=base_url, sw=sw)


def _patch_block_html(block: Dict[str, Any], L: _Links) -> str:
    _kinds, media, discs = _vocab_tables()
    disc = discs.get(str(block.get("discipline") or "")) or {"color": "#9aa3b5", "label": block.get("discipline") or ""}
    left: List[str] = []
    right: List[str] = []
    for s in block.get("sections") or []:
        mspec = media.get(str(s.get("medium") or "")) or {"label": s.get("medium") or "", "color": "#9aa3b5"}
        head = f'<div class="pt-sec">{_medium_dot(s.get("medium"))}{esc(s.get("title") or "")} <span>· {esc(mspec.get("label", ""))}</span></div>'
        rows: List[str] = []
        is_in = s.get("dir") == "in"
        for r in s.get("rows") or []:
            ovl = r.get("source") not in (None, "cable")
            lab = esc(r.get("label") or "") or '<span class="none">—</span>'
            lab_cell = f'{_medium_dot(r.get("medium"))}<span class="{"ovl" if ovl else ""}">{lab}</span>'
            if r.get("peer_device"):
                peer = f'<a href="{esc(L.device(str(r["peer_device"])))}">{esc(r.get("peer_name") or r["peer_device"])}</a>'
                pport = esc(r.get("peer_label") or r.get("peer_port_name") or r.get("peer_port") or "device")
                if ovl:
                    pport = f'<span class="ovl" title="from import">{pport}</span>'
            else:
                peer, pport = '<span class="none">—</span>', '<span class="none">—</span>'
            pn = esc(r.get("port_name") or ("device" if not r.get("port") else ""))
            if is_in:
                rows.append(f'<tr><td>{peer}</td><td>{pport}</td><td class="ar">←</td><td class="pn">{pn}</td><td>{lab_cell}</td></tr>')
            else:
                rows.append(f'<tr><td class="pn">{pn}</td><td>{lab_cell}</td><td class="ar">→</td><td>{pport}</td><td>{peer}</td></tr>')
        if is_in:
            thead = '<tr><th scope="col">Device</th><th scope="col">Source</th><th scope="col" class="ar"></th><th scope="col" colspan="2">Input</th></tr>'
        else:
            thead = '<tr><th scope="col" colspan="2">Output</th><th scope="col" class="ar"></th><th scope="col">Dest</th><th scope="col">Device</th></tr>'
        table = f'{head}<table class="pt-t"><thead>{thead}</thead><tbody>{"".join(rows)}</tbody></table>'
        (left if is_in else right).append(table)
    return (
        f'<section class="pt-block" data-device="{esc(block.get("device") or "")}">'
        f'<div class="pt-head"><span class="dot" style="color:{esc(disc.get("color", "#9aa3b5"))}" title="{esc(disc.get("label", ""))}"></span>'
        f'<b><a href="{esc(L.device(str(block.get("device") or "")))}">{esc(block.get("name") or block.get("device") or "")}</a></b><span class="sub">{esc(block.get("model") or "")}</span></div>'
        f'<div class="pt-cols"><div>{"".join(left)}</div><div>{"".join(right)}</div></div></section>'
    )


def render_patch_page(doc: Dict[str, Any], room_id: str, blocks: List[Dict[str, Any]], *, project: str, base_url: str = "", sw: bool = False, link_style: str = "viewer") -> str:
    L = _Links(link_style, "room-patch", _default_room(doc))
    room = _find(doc.get("rooms"), room_id) or {"id": room_id, "name": room_id}
    meta = doc.get("meta") or {}
    out: List[str] = []
    out.append(f'<div class="eyebrow">{esc(_org_eyebrow(doc, "Patch table"))}</div><h1>{esc(room.get("name") or room_id)}</h1>')
    n_rows = sum(len(s.get("rows") or []) for b in blocks for s in b.get("sections") or [])
    out.append(f'<div class="sub">{len(blocks)} devices · {n_rows} rows <span class="live no-print" style="margin-left:8px"><span class="dot"></span>Read-only · edits happen in the editor</span></div>')
    out.append('<nav class="nav no-print" aria-label="Viewer">')
    rooms = _doc_rooms(doc)
    for r in rooms:
        cur = ' aria-current="page"' if r["id"] == room_id else ""
        if len(rooms) > 1:
            out.append(f'<a href="{esc(L.room_patch(str(r["id"])))}"{cur}>{esc(r.get("name") or r["id"])}</a>')
    out.append(f'<a href="{esc(L.room_map(room_id))}">Map</a><a href="{esc(L.rooms())}">All rooms</a>')
    if link_style != "build":
        out.append(f'<a href="{esc(base_url)}api/v2/projects/{_q(project)}/schedules/patch?room={_q(room_id)}&amp;format=csv">CSV</a>')
        out.append(f'<a href="{esc(_editor_link(base_url, project, room_id, "table"))}">Open in editor</a>')
    out.append('<button type="button" id="pt-print-btn">Print / PDF</button></nav>')
    if blocks:
        out.append("".join(_patch_block_html(b, L) for b in blocks))
    else:
        out.append('<p class="sub">No devices in this room.</p>')
    out.append("<script>(function(){var b=document.getElementById('pt-print-btn');if(b)b.addEventListener('click',function(){window.print();});})();</script>")
    return _page(f"Patch table · {room.get('name') or room_id} · {meta.get('org') or project}", "".join(out), base_url=base_url, sw=sw)


def render_report(doc: Dict[str, Any], *, project: str, sections: Dict[str, str], extra_css: str = "") -> str:
    meta = doc.get("meta") or {}
    toc = "".join(f'<li><a href="#sec-{i}">{esc(title)}</a></li>' for i, title in enumerate(sections))
    body = [
        f'<div class="eyebrow">{esc(_org_eyebrow(doc, "As-built report"))}</div><h1>{esc(meta.get("title") or project)}</h1>',
        f'<p class="sub">{esc(meta.get("system") or "")}{(" · revision " + str(doc.get("revision"))) if doc.get("revision") else ""}</p>',
        f'<nav class="no-print"><ol>{toc}</ol></nav>' if sections else "",
    ]
    for i, (title, html_part) in enumerate(sections.items()):
        brk = "" if i == 0 else "page-break-before:always;break-before:page;"
        body.append(f'<section id="sec-{i}" style="{brk}"><h2>{esc(title)}</h2>{html_part}</section>')
    return _page(f"Report · {meta.get('org') or project}", "".join(body), extra_css=extra_css)


# ===================================================================== SOP pages (§4.3.15, §5.15)
#
# The public page, the QR sheet and the report section share the `.md` rules of
# static/css/sop.css (inlined so builds and share links work offline) plus the
# small shell below. Everything is phone-first: 17px body text, 44px targets,
# sticky "Applies to" chips, collapsible contents, tap-to-toggle checklists kept
# in sessionStorage and tap-to-zoom images, with no edit controls.

PAGE_KIND_LABELS = {"sop": "SOP", "troubleshooting": "Troubleshooting", "checklist": "Checklist", "reference": "Reference"}

SOP_SHELL_CSS = """
:root{--panel-2:#161d2e;--border-2:#2a3550;--sat:env(safe-area-inset-top,0px);--sab:env(safe-area-inset-bottom,0px);--sal:env(safe-area-inset-left,0px);--sar:env(safe-area-inset-right,0px)}
body.sop-pub{font-size:17px;line-height:1.5}
.sop-pub .sop-main{overflow:visible;max-width:820px;margin:0 auto}
.sop-pub .grow{flex:1}
.sop-pub .muted{color:var(--muted)}
.sop-pub .chip{display:inline-flex;align-items:center;gap:4px;border:1px solid var(--border);border-radius:999px;background:transparent;color:var(--text);text-decoration:none;font:inherit}
.sop-pub .sop-topbar button,.sop-pub .sop-topbar a.btn{min-height:44px;min-width:44px;padding:0 14px;border:1px solid var(--border);border-radius:8px;background:var(--panel-2);color:var(--text);font:inherit;font-size:15px;text-decoration:none;display:inline-flex;align-items:center;cursor:pointer}
.sop-pub .sop-topbar{padding-top:var(--sat)}
.sop-pub .sop-back{text-decoration:none}
.sop-pub .md h1,.sop-pub .md h2,.sop-pub .md h3,.sop-pub .md h4{text-transform:none;letter-spacing:0;color:var(--text)}
.sop-pub .sop-head h1{font-size:26px;margin:0 0 6px}
.sop-pub .sop-applies{top:calc(48px + var(--sat))}
.sop-pub .sop-applies span.chip{opacity:.9}
.sop-pub .sop-index h1{font-size:26px;margin:14px 0 2px}
.sop-pub .sop-index .sop-list{margin-top:10px;border-top:1px solid var(--border)}
.sop-pub .sop-list .sop-item-main{padding-left:calc(16px + var(--sal) + var(--depth,0)*18px)}
.sop-pub .sop-item-main{color:var(--text)}
.sop-pub .sop-progress-bar{min-width:60px}
.sop-pub footer.sop-foot{color:var(--muted);font-size:13px;padding:16px 0 calc(8px + var(--sab))}
.sop-pub .sop-progress-reset{min-height:36px;padding:0 12px;border:1px solid var(--border);border-radius:8px;background:transparent;color:var(--text);font:inherit;font-size:14px}
.sop-pub .sop-lightbox-close{cursor:pointer}
@media print{
  .sop-pub .sop-topbar,.sop-pub .sop-prevnext,.sop-pub .sop-progress,.sop-pub .sop-toc{display:none!important}
  .sop-pub .sop-applies{position:static;border:0;padding-left:0}
  body.sop-pub{font-size:12pt}
  .sop-pub .sop-head h1{font-size:20pt}
  .sop-pub .md,.sop-pub .md h1,.sop-pub .md h2,.sop-pub .md h3,.sop-pub .md h4,.sop-pub .sop-head h1{color:#000}
  .sop-pub .md .md-task-label input[type=checkbox]{border-color:#000;background:#fff}
  .sop-pub .md a.md-ref{border-color:#999;background:#fff;color:#000}
}
"""

SOP_REPORT_CSS = """
.sop-report-page{break-before:page;page-break-before:always;padding-top:6px}
.sop-report-page:first-of-type{break-before:auto;page-break-before:auto}
.sop-report-page h3{font-size:20px;margin:0 0 4px}
.sop-report-page .md h1,.sop-report-page .md h2,.sop-report-page .md h3,.sop-report-page .md h4{text-transform:none;letter-spacing:0;color:var(--text)}
.sop-report-page .sop-report-sub{color:var(--muted);font-size:13px;margin:0 0 12px}
.sop-report-page .md{font-size:14px;line-height:1.5;max-width:820px}
.sop-report-page .md .md-task-label{min-height:0;padding:3px 0;cursor:default}
.sop-report-page .md .md-task-label input[type=checkbox]{width:18px;height:18px;border-radius:4px}
.sop-report-page .md li.md-task{border-bottom:0}
.sop-report-page .md img{max-width:420px;cursor:default}
.sop-report-toc li{margin:3px 0}
@media print{
  .sop-report-page .md,.sop-report-page .md h1,.sop-report-page .md h2,.sop-report-page .md h3,.sop-report-page .md h4,.sop-report-page .md strong{color:#000}
  .sop-report-page .md h2{border-color:#999}
  .sop-report-page .md .md-task-label input[type=checkbox]{border-color:#000;background:#fff}
  .sop-report-page .md a.md-ref{border-color:#999;background:#fff;color:#000}
  .sop-report-page .md .md-callout{background:#fff;border-color:#999}
}
"""

SOP_PUB_JS = r"""
(function(){
  var root=document.querySelector('[data-sop-page]');
  if(!root)return;
  var project=root.getAttribute('data-sop-project')||'',slug=root.getAttribute('data-sop-page')||'';
  var key='fathom.sop.tasks.'+project+'.'+slug;
  function read(){try{var v=JSON.parse(sessionStorage.getItem(key)||'[]');return Array.isArray(v)?v:[]}catch(e){return[]}}
  function write(l){try{if(l.length)sessionStorage.setItem(key,JSON.stringify(l));else sessionStorage.removeItem(key)}catch(e){}}
  var boxes=root.querySelectorAll('input[data-task]'),prog=document.getElementById('sop-progress');
  function paint(){
    var done=0;
    Array.prototype.forEach.call(boxes,function(b){var li=b.closest('li');if(li)li.classList.toggle('done',b.checked);if(b.checked)done++;});
    if(prog){
      prog.querySelector('.sop-progress-text').textContent=done+' of '+boxes.length+' done';
      prog.querySelector('.sop-progress-bar i').style.width=Math.round(100*done/Math.max(1,boxes.length))+'%';
      prog.querySelector('.sop-progress-reset').hidden=!done;
    }
  }
  var done=read();
  Array.prototype.forEach.call(boxes,function(b){
    b.disabled=false;b.checked=done.indexOf(Number(b.getAttribute('data-task')))>=0;
    b.addEventListener('change',function(){
      var n=Number(b.getAttribute('data-task')),cur=read().filter(function(x){return x!==n});
      if(b.checked)cur.push(n);write(cur);paint();
    });
  });
  if(prog){prog.querySelector('.sop-progress-reset').addEventListener('click',function(){write([]);Array.prototype.forEach.call(boxes,function(b){b.checked=false});paint();});}
  paint();
  var pr=document.getElementById('sop-print');if(pr)pr.addEventListener('click',function(){window.print();});
  root.addEventListener('click',function(e){
    var img=e.target.closest?e.target.closest('.md img'):null;
    if(!img)return;
    e.preventDefault();
    var box=document.createElement('div');box.className='sop-lightbox';box.setAttribute('role','dialog');
    var big=document.createElement('img');big.src=img.getAttribute('src');big.alt=img.alt||'';box.appendChild(big);
    var x=document.createElement('button');x.type='button';x.className='sop-lightbox-close';x.setAttribute('aria-label','Close');x.textContent='\u00d7';box.appendChild(x);
    if(img.alt){var c=document.createElement('div');c.className='sop-lightbox-cap';c.textContent=img.alt;box.appendChild(c);}
    function close(){box.remove();document.removeEventListener('keydown',onKey);}
    function onKey(ev){if(ev.key==='Escape')close();}
    box.addEventListener('click',close);document.addEventListener('keydown',onKey);document.body.appendChild(box);
  });
  var toc=document.querySelector('.sop-toc');
  if(toc)toc.addEventListener('click',function(e){var a=e.target.closest?e.target.closest('a'):null;if(!a)return;var id=(a.getAttribute('href')||'').slice(1);var t=id&&document.getElementById(id);if(t){e.preventDefault();t.scrollIntoView({behavior:'smooth',block:'start'});}});
})();
"""


def sop_css() -> str:
    """The SOP stylesheet (``static/css/sop.css``) for inlining into chrome-free pages and builds."""
    try:
        return (Path(__file__).resolve().parent / "static" / "css" / "sop.css").read_text(encoding="utf-8")
    except OSError:  # pragma: no cover - packaging without static files
        return ""


def sop_pages(doc: Dict[str, Any], *, published_only: bool = True) -> List[Dict[str, Any]]:
    return [p for p in doc.get("pages") or [] if isinstance(p, dict) and p.get("id") and p.get("slug")
            and (not published_only or (p.get("status") or "published") == "published")]


def sop_order_key(p: Dict[str, Any]) -> Tuple[int, str]:
    o = p.get("order")
    return (int(o) if isinstance(o, int) and not isinstance(o, bool) else 10 ** 6, str(p.get("title") or "").casefold())


def sop_tree(doc: Dict[str, Any], *, published_only: bool = True) -> List[Tuple[Dict[str, Any], int]]:
    """Pages in tree order (depth-first, siblings by ``order`` then title) with their depth.
    Children of hidden (draft/archived) parents are hoisted to the top level so nothing published is lost."""
    pages = sop_pages(doc, published_only=published_only)
    ids = {p["id"] for p in pages}
    out: List[Tuple[Dict[str, Any], int]] = []
    seen: set = set()

    def walk(parent: Optional[str], depth: int) -> None:
        for p in sorted([x for x in pages if (x.get("parent") or None) == parent], key=sop_order_key):
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            out.append((p, depth))
            if depth < 50:
                walk(p["id"], depth + 1)

    walk(None, 0)
    for p in sorted([x for x in pages if x.get("parent") and x["parent"] not in ids], key=sop_order_key):
        if p["id"] not in seen:
            seen.add(p["id"])
            out.append((p, 0))
            walk(p["id"], 1)
    return out


def sop_link_resolver(doc: Dict[str, Any], *, device: Optional[Callable[[str, Dict[str, Any]], Optional[str]]] = None,
                      room: Optional[Callable[[str, Dict[str, Any]], Optional[str]]] = None,
                      page: Optional[Callable[[str, Dict[str, Any]], Optional[str]]] = None,
                      attachment: Optional[Callable[[str, Dict[str, Any]], Optional[str]]] = None) -> Callable[[str, str], Optional[Dict[str, Any]]]:
    """Markdown ``[[kind:id]]`` resolver; each callback returns an href, ``""`` for a plain chip, or ``None`` for unresolved."""
    devs = {d.get("id"): d for d in doc.get("devices") or [] if isinstance(d, dict)}
    rooms = {r.get("id"): r for r in doc.get("rooms") or [] if isinstance(r, dict)}
    pages = {p.get("slug"): p for p in sop_pages(doc, published_only=False)}
    atts = {a.get("id"): a for a in doc.get("attachments") or [] if isinstance(a, dict)}
    table = {"device": (devs, device, "name"), "room": (rooms, room, "name"), "page": (pages, page, "title"), "attachment": (atts, attachment, "name")}

    def resolve(kind: str, ref: str) -> Optional[Dict[str, Any]]:
        items, fn, label_key = table.get(kind) or ({}, None, "name")
        obj = items.get(ref)
        if obj is None or fn is None:
            return None
        href = fn(ref, obj)
        if href is None:
            return None
        return {"href": href, "label": str(obj.get(label_key) or ref)}

    return resolve


def attachment_filename(att: Dict[str, Any]) -> str:
    return Path(str(att.get("file") or att.get("name") or "file")).name


def _kind_badge(p: Dict[str, Any]) -> str:
    kind = str(p.get("kind") or "sop")
    return f'<span class="sop-kind sop-kind-{esc(kind)}">{esc(PAGE_KIND_LABELS.get(kind, kind))}</span>'


def _review_badge(p: Dict[str, Any], today: Optional[str] = None) -> str:
    due = str(p.get("review_due") or "")
    if not due:
        return ""
    today = today or datetime.date.today().isoformat()
    if due < today:
        return '<span class="sop-badge sop-badge-due">Review overdue</span>'
    try:
        soon = (datetime.date.fromisoformat(due) - datetime.date.fromisoformat(today)).days <= 30
    except ValueError:
        return ""
    return '<span class="sop-badge sop-badge-soon">Review due soon</span>' if soon else ""


def _fmt_date(s: Any) -> str:
    text = str(s or "")
    return text[:10] if len(text) >= 10 else text


def _sop_shell(title: str, body: str, *, base_url: str, sw: bool, js: str = "") -> str:
    return _page(title, body + (f"<script>{js}</script>" if js else ""), base_url=base_url, sw=sw,
                 extra_css=sop_css() + SOP_SHELL_CSS, body_class="sop-pub", wrap=False)


def render_sop_page(doc: Dict[str, Any], data: Dict[str, Any], *, project: str, base_url: str = "", sw: bool = False,
                    rel: str = "../", sop_only: bool = False) -> str:
    """Chrome-free, phone-first page for ``/p/<n>/sop/<slug>`` (and share links).

    ``data`` is the pages API payload (``page``, ``html``, ``toc``, ``tasks``, ``links``, ``breadcrumbs``, ``prev``/``next``,
    ``children``, ``backlinks``); ``rel`` is the relative prefix back to the viewer root (``../`` from a page URL).
    With ``sop_only`` (procedures-only share links) device and room chips are plain text."""
    p = data["page"]
    meta = doc.get("meta") or {}
    crumbs = data.get("breadcrumbs") or []
    back_label = crumbs[-1]["title"] if crumbs else "Procedures"
    back_href = f"{rel}sop/{_q(crumbs[-1]['slug'])}" if crumbs else f"{rel}sop"
    out: List[str] = [f'<main class="sop-main sop-page" data-sop-page="{esc(p["slug"])}" data-sop-project="{esc(project)}">']
    out.append('<div class="sop-topbar">'
               f'<a class="sop-back" href="{esc(back_href)}">\u2039 {esc(back_label)}</a><span class="grow"></span>'
               '<button type="button" id="sop-print" class="no-print">Print</button></div>')
    if crumbs:
        out.append('<nav class="sop-crumbs" aria-label="Breadcrumb">' + " / ".join(f'<a href="{esc(rel)}sop/{_q(c["slug"])}">{esc(c["title"])}</a>' for c in crumbs) + "</nav>")
    badges = _kind_badge(p) + _review_badge(p)
    out.append(f'<header class="sop-head"><div class="eyebrow">{esc(_org_eyebrow(doc, "Procedures"))}</div><div class="sop-head-badges">{badges}</div>'
               f'<h1 id="sop-title">{esc(p.get("title") or p["slug"])}</h1>'
               + (f'<p class="sop-summary">{esc(p["summary"])}</p>' if p.get("summary") else "") + "</header>")
    chips: List[str] = []
    links = data.get("links") or {}
    for r in links.get("rooms") or []:
        chips.append(f'<span class="chip sop-chip-room">\u25A3 {esc(r["name"])}</span>' if sop_only
                     else f'<a class="chip sop-chip-room" href="{esc(rel)}r/{_q(r["id"])}">\u25A3 {esc(r["name"])}</a>')
    for d in links.get("devices") or []:
        chips.append(f'<span class="chip sop-chip-device">{esc(d["name"])}</span>' if sop_only
                     else f'<a class="chip sop-chip-device" href="{esc(rel)}d/{_q(d["id"])}">{esc(d["name"])}</a>')
    if chips:
        out.append('<div class="sop-applies" aria-label="Applies to"><span class="sop-applies-label">Applies to</span>'
                   f'<div class="sop-applies-chips">{"".join(chips)}</div></div>')
    if data.get("tasks"):
        out.append('<div class="sop-progress" id="sop-progress" role="status"><span class="sop-progress-text"></span>'
                   '<span class="sop-progress-bar" aria-hidden="true"><i style="width:0"></i></span>'
                   '<button type="button" class="sop-progress-reset" hidden>Reset</button></div>')
    toc = data.get("toc") or []
    if len(toc) > 1:
        items = "".join(f'<li class="lvl-{int(t.get("level") or 2)}"><a href="#{esc(t["id"])}">{esc(t["text"])}</a></li>' for t in toc)
        out.append(f'<details class="sop-toc"><summary>Contents</summary><ol>{items}</ol></details>')
    out.append(f'<article class="sop-body md">{data.get("html") or ""}</article>')
    kids = data.get("children") or []
    if kids:
        out.append('<section class="sop-related"><h2>In this section</h2><ul class="sop-list">'
                   + "".join(f'<li class="sop-item"><a class="sop-item-main" href="{esc(rel)}sop/{_q(c["slug"])}"><span class="sop-item-title">{esc(c["title"])}</span></a></li>' for c in kids)
                   + "</ul></section>")
    back = data.get("backlinks") or []
    if back:
        out.append('<section class="sop-related"><h2>Referenced by</h2><ul class="sop-links">'
                   + "".join(f'<li><a href="{esc(rel)}sop/{_q(c["slug"])}">{esc(c["title"])}</a></li>' for c in back) + "</ul></section>")
    prev, nxt = data.get("prev"), data.get("next")
    if prev or nxt:
        out.append('<nav class="sop-prevnext" aria-label="Previous and next page">'
                   + (f'<a class="sop-prev" href="{esc(rel)}sop/{_q(prev["slug"])}"><small>\u2039 Previous</small><span>{esc(prev["title"])}</span></a>' if prev else "<span></span>")
                   + (f'<a class="sop-next" href="{esc(rel)}sop/{_q(nxt["slug"])}"><small>Next \u203a</small><span>{esc(nxt["title"])}</span></a>' if nxt else "<span></span>")
                   + "</nav>")
    foot = []
    if p.get("updated"):
        foot.append("Updated " + _fmt_date(p["updated"]) + (f' by {p["updated_by"]}' if p.get("updated_by") else ""))
    if p.get("review_due"):
        foot.append("Review due " + _fmt_date(p["review_due"]))
    if data.get("revision"):
        foot.append(f'r{data["revision"]}')
    out.append(f'<footer class="sop-foot">{esc(" · ".join(foot))}</footer></main>')
    return _sop_shell(f'{p.get("title") or p["slug"]} · {meta.get("org") or project}', "".join(out), base_url=base_url, sw=sw, js=SOP_PUB_JS)


def render_sop_index(doc: Dict[str, Any], *, project: str, base_url: str = "", sw: bool = False, rel: str = "",
                     sop_only: bool = False) -> str:
    """Published procedures as a drill-down list (``/p/<n>/sop``)."""
    meta = doc.get("meta") or {}
    rows = sop_tree(doc)
    out: List[str] = ['<main class="sop-main sop-index">']
    nav = "" if sop_only else f'<a class="btn" href="{esc(rel)}rooms">Rooms</a>'
    out.append(f'<div class="sop-topbar"><span class="grow"></span>{nav}</div>')
    out.append(f'<div class="eyebrow">{esc(_org_eyebrow(doc, "Procedures"))}</div><h1>{esc(meta.get("title") or project)}</h1>'
               f'<p class="muted">{len(rows)} published page{"s" if len(rows) != 1 else ""}. Tap a page to open it; checklists remember your place on this device.</p>')
    if rows:
        items = []
        for p, depth in rows:
            sub = _kind_badge(p) + _review_badge(p) + (f'<span class="sop-item-sum">{esc(p["summary"])}</span>' if p.get("summary") else "")
            items.append(f'<li class="sop-item" style="--depth:{depth}"><a class="sop-item-main" href="{esc(rel)}sop/{_q(p["slug"])}">'
                         f'<span class="sop-item-title">{esc(p.get("title") or p["slug"])}</span><span class="sop-item-sub">{sub}</span></a></li>')
        out.append(f'<ul class="sop-list" role="list">{"".join(items)}</ul>')
    else:
        out.append('<p class="sop-empty">No published procedures yet.</p>')
    out.append("</main>")
    return _sop_shell(f"Procedures · {meta.get('org') or project}", "".join(out), base_url=base_url, sw=sw)


def render_sop_qr_sheet(doc: Dict[str, Any], items: List[Dict[str, Any]], *, project: str, room: str = "", share: bool = False) -> str:
    """Printable sheet of QR labels, one per published page (``items``: ``page``, ``url``, ``svg``)."""
    meta = doc.get("meta") or {}
    css = """
.qr-sheet{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;margin-top:14px}
.qr-card{border:1px solid var(--border);border-radius:12px;padding:12px;background:var(--panel);display:flex;flex-direction:column;gap:8px;break-inside:avoid;page-break-inside:avoid}
.qr-card .qr{max-width:100%;padding:10px;align-self:center;width:100%}
.qr-card h3{margin:0;font-size:16px;line-height:1.3}
.qr-card .url{font-size:11px;color:var(--muted);word-break:break-all;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.qr-card .kind{font-size:10.5px;text-transform:uppercase;letter-spacing:.7px;color:var(--muted)}
@media print{.qr-sheet{grid-template-columns:repeat(3,1fr);gap:10mm}.qr-card{border-color:#999;background:#fff}.qr-card h3,.qr-card .url,.qr-card .kind{color:#000}.qr-card .url{color:#333}}
"""
    out = [f'<div class="eyebrow">{esc(_org_eyebrow(doc, "QR labels"))}</div>',
           f'<h1>{esc(room or meta.get("title") or project)} · Procedures</h1>',
           f'<p class="sub">{len(items)} label{"s" if len(items) != 1 else ""}. Each code opens the published procedure on a phone'
           + (" through a procedures-only share link" if share else "") + ". Print, cut, and stick next to the gear.</p>",
           '<div class="nav no-print"><button type="button" id="qr-print">Print</button></div>']
    if items:
        cards = []
        for it in items:
            p = it["page"]
            kind = str(p.get("kind") or "sop")
            cards.append(f'<div class="qr-card"><div class="qr">{it["svg"]}</div><div class="kind">{esc(PAGE_KIND_LABELS.get(kind, kind))}</div>'
                         f'<h3>{esc(p.get("title") or p["slug"])}</h3><div class="url">{esc(it["url"])}</div></div>')
        out.append(f'<div class="qr-sheet">{"".join(cards)}</div>')
    else:
        out.append('<p class="sub">No published procedures' + (" for this room" if room else "") + ".</p>")
    out.append("<script>(function(){var b=document.getElementById('qr-print');if(b)b.addEventListener('click',function(){window.print();});})();</script>")
    return _page(f"QR labels · {room or project}", "".join(out), extra_css=css)


def render_sop_report_section(doc: Dict[str, Any], entries: List[Dict[str, Any]]) -> str:
    """Report section body: every entry (``page``, ``html``, ``depth``, ``applies``) on its own printed page, in tree order."""
    toc = "".join(f'<li style="margin-left:{int(e.get("depth") or 0) * 16}px"><a href="#sop-{esc(e["page"]["slug"])}">{esc(e["page"].get("title") or e["page"]["slug"])}</a></li>' for e in entries)
    out = [f'<p class="sub">{len(entries)} published procedure{"s" if len(entries) != 1 else ""}. Checklists are printed unticked for use on paper.</p>',
           f'<ol class="sop-report-toc no-print">{toc}</ol>']
    for e in entries:
        p = e["page"]
        kind = str(p.get("kind") or "sop")
        sub = [PAGE_KIND_LABELS.get(kind, kind)]
        if e.get("applies"):
            sub.append("Applies to: " + ", ".join(e["applies"]))
        if p.get("review_due"):
            sub.append("Review due " + _fmt_date(p["review_due"]))
        if p.get("updated"):
            sub.append("Updated " + _fmt_date(p["updated"]))
        out.append(f'<article class="sop-report-page" id="sop-{esc(p["slug"])}"><h3>{esc(p.get("title") or p["slug"])}</h3>'
                   f'<p class="sop-report-sub">{esc(" · ".join(sub))}</p>'
                   + (f'<p class="sop-summary">{esc(p["summary"])}</p>' if p.get("summary") else "")
                   + f'<div class="md">{e.get("html") or ""}</div></article>')
    return "".join(out)
