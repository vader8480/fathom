"""Markdown subset renderer and strict HTML sanitizer for SOP pages (stdlib only).

Supported (§4.3.15): ATX headings, paragraphs, hard breaks (two trailing
spaces or a backslash), ``**bold**`` / ``__bold__``, ``*italic*`` / ``_italic_``,
``~~strike~~``, `code`, fenced code blocks, ordered / unordered lists with
nesting, task lists (``- [ ]`` / ``- [x]``), GFM pipe tables, blockquotes,
callouts (``> [!NOTE]`` / ``[!TIP]`` / ``[!IMPORTANT]`` / ``[!WARNING]`` /
``[!CAUTION]``), horizontal rules, links, autolinks, images and the Fathom
reference syntax ``[[device:id]]``, ``[[room:id]]``, ``[[page:slug]]``
(optionally ``[[device:id|label]]``) plus ``![caption](att:att-id)`` images
served from the project's attachments.

Raw HTML in the source is never passed through: every text run is escaped,
URLs are scheme-filtered and the finished fragment goes through
:func:`sanitize`, an allow-list filter, so the output is safe to inject
into the app, a public page or a report without further processing.

``render(text, resolver)`` returns ``{"html", "toc", "refs", "missing",
"tasks"}``. The optional ``resolver(kind, ref)`` maps ``device`` / ``room`` /
``page`` / ``attachment`` references to ``{"href", "label"}`` (``None`` when
unknown); without one, references render as inert labels.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List, Optional, Tuple

Resolver = Callable[[str, str], Optional[Dict[str, Any]]]

REF_KINDS: Tuple[str, ...] = ("device", "room", "page")
CALLOUTS: Dict[str, str] = {"note": "Note", "tip": "Tip", "important": "Important", "warning": "Warning", "caution": "Caution"}

_FENCE_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})\s*(?P<lang>[\w+#.-]*)\s*$")
_ATX_RE = re.compile(r"^ {0,3}(?P<hashes>#{1,6})(?:\s+(?P<text>.*?))?\s*#*\s*$")
_HR_RE = re.compile(r"^ {0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$")
_QUOTE_RE = re.compile(r"^ {0,3}>")
_LIST_RE = re.compile(r"^(?P<ind>\s*)(?P<marker>[-*+]|\d{1,9}[.)])(?P<sp>\s+|$)(?P<rest>.*)$")
_TASK_RE = re.compile(r"^\[(?P<mark>[ xX])\]\s+(?P<rest>.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_CALLOUT_RE = re.compile(r"^\[!(?P<kind>[A-Za-z]+)\]\s*(?P<title>.*)$")
_REF_RE = re.compile(r"\[\[(?P<kind>device|room|page):(?P<id>[^\]|\n]+?)(?:\|(?P<label>[^\]\n]+))?\]\]")
_ATT_RE = re.compile(r"!\[[^\]]*\]\(att:(?P<id>att-[0-9a-f]{12})")
_SAFE_SCHEME_RE = re.compile(r"^(?:https?://|mailto:|tel:)", re.I)
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_TAG_RE = re.compile(r"<[^>]+>")
_IMAGE_ONLY_RE = re.compile(r"^!\[[^\]]*\]\((?:[^()\s]|\([^()\s]*\))+(?:\s+\"[^\"]*\")?\)\s*$")

_INLINE_RE = re.compile(
    r"(?P<code>`+)(?P<codetxt>.+?)(?P=code)"
    r"|(?P<esc>\\[\\`*_{}\[\]()#+\-.!|>~<])"
    r"|(?P<br>(?: {2,}|\\)\n)"
    r"|!\[(?P<imgalt>[^\]]*)\]\((?P<imgsrc>(?:[^()\s]|\([^()\s]*\))+)(?:\s+\"(?P<imgtitle>[^\"]*)\")?\)"
    r"|\[\[(?P<refkind>device|room|page):(?P<refid>[^\]|\n]+?)(?:\|(?P<reflabel>[^\]\n]+))?\]\]"
    r"|\[(?P<ltext>[^\]\n]+)\]\((?P<lhref>(?:[^()\s]|\([^()\s]*\))+)(?:\s+\"(?P<ltitle>[^\"]*)\")?\)"
    r"|<(?P<auto>(?:https?://|mailto:)[^\s<>]+)>"
    r"|\*\*(?P<strong>\S(?:.*?\S)?)\*\*"
    r"|__(?P<strong2>\S(?:.*?\S)?)__"
    r"|\*(?P<em>[^\s*](?:[^*\n]*?[^\s*])?)\*"
    r"|(?<![\w])_(?P<em2>[^\s_](?:[^_\n]*?[^\s_])?)_(?![\w])"
    r"|~~(?P<del>\S(?:.*?\S)?)~~",
    re.S,
)


# ------------------------------------------------------------------ helpers


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def safe_url(url: Any) -> str:
    """``url`` when its scheme is http(s), mailto, tel, a fragment or a relative path; else ``""``."""
    u = _CTRL_RE.sub("", str(url or "")).strip()
    if not u:
        return ""
    if _SAFE_SCHEME_RE.match(u) or u.startswith(("#", "/", "./", "../", "?")):
        return "" if u.startswith("//") else u
    head = u.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if ":" in head:
        return ""
    return u


def slugify(text: str) -> str:
    return _SLUG_RE.sub("-", str(text or "").casefold()).strip("-")[:80]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _strip_tags(fragment: str) -> str:
    return html.unescape(_TAG_RE.sub("", fragment))


class _Ctx:
    def __init__(self, resolver: Optional[Resolver]) -> None:
        self.resolver = resolver
        self.toc: List[Dict[str, Any]] = []
        self.ids: Dict[str, int] = {}
        self.refs: Dict[str, List[str]] = {"device": [], "room": [], "page": [], "attachment": []}
        self.missing: List[str] = []
        self.tasks = 0
        self.figure = False

    def note(self, kind: str, ref: str, found: bool) -> None:
        lst = self.refs.setdefault(kind, [])
        if ref not in lst:
            lst.append(ref)
        key = f"{kind}:{ref}"
        if not found and key not in self.missing:
            self.missing.append(key)

    def resolve(self, kind: str, ref: str) -> Optional[Dict[str, Any]]:
        if self.resolver is None:
            return None
        try:
            return self.resolver(kind, ref) or None
        except Exception:
            return None

    def heading_id(self, text: str) -> str:
        base = slugify(text) or "section"
        n = self.ids.get(base, 0) + 1
        self.ids[base] = n
        return "h-" + base + ("" if n == 1 else f"-{n}")


# ------------------------------------------------------------------ inline


def _inline(text: str, ctx: _Ctx) -> str:
    out: List[str] = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        out.append(_esc(text[pos:m.start()]))
        pos = m.end()
        g = m.groupdict()
        if g["code"] is not None:
            out.append("<code>" + _esc(g["codetxt"].strip()) + "</code>")
        elif g["esc"] is not None:
            out.append(_esc(g["esc"][1]))
        elif g["br"] is not None:
            out.append("<br>\n")
        elif g["imgsrc"] is not None:
            out.append(_image(g["imgalt"] or "", g["imgsrc"], g["imgtitle"], ctx))
        elif g["refkind"] is not None:
            out.append(_ref(g["refkind"], g["refid"].strip(), (g["reflabel"] or "").strip(), ctx))
        elif g["lhref"] is not None:
            href = safe_url(g["lhref"])
            inner = _inline(g["ltext"], ctx)
            if href:
                title = f' title="{_esc(g["ltitle"])}"' if g["ltitle"] else ""
                ext = ' rel="noopener"' if _SAFE_SCHEME_RE.match(href) else ""
                out.append(f'<a href="{_esc(href)}"{title}{ext}>{inner}</a>')
            else:
                out.append(inner)
        elif g["auto"] is not None:
            href = safe_url(g["auto"])
            out.append(f'<a href="{_esc(href)}" rel="noopener">{_esc(g["auto"])}</a>' if href else _esc(g["auto"]))
        elif g["strong"] is not None or g["strong2"] is not None:
            out.append("<strong>" + _inline(g["strong"] if g["strong"] is not None else g["strong2"], ctx) + "</strong>")
        elif g["em"] is not None or g["em2"] is not None:
            out.append("<em>" + _inline(g["em"] if g["em"] is not None else g["em2"], ctx) + "</em>")
        elif g["del"] is not None:
            out.append("<del>" + _inline(g["del"], ctx) + "</del>")
    out.append(_esc(text[pos:]))
    return "".join(out)


def _ref(kind: str, ref: str, label: str, ctx: _Ctx) -> str:
    hit = ctx.resolve(kind, ref)
    ctx.note(kind, ref, hit is not None)
    text = label or (hit or {}).get("label") or ref
    data = f'data-ref="{_esc(kind)}:{_esc(ref)}"'
    if hit is None or not safe_url(hit.get("href")):
        return f'<span class="md-ref md-ref-{kind} md-missing" {data} title="{_esc(kind)} {_esc(ref)} not found">{_esc(text)}</span>'
    return f'<a class="md-ref md-ref-{kind}" href="{_esc(safe_url(hit.get("href")))}" {data}>{_esc(text)}</a>'


def _image(alt: str, src: str, title: Optional[str], ctx: _Ctx) -> str:
    if src.startswith("att:"):
        att = src[4:].strip()
        hit = ctx.resolve("attachment", att)
        ctx.note("attachment", att, hit is not None)
        if hit is None or not safe_url(hit.get("href")):
            return f'<span class="md-missing" data-ref="attachment:{_esc(att)}">[image {_esc(att)} not found]</span>'
        src = str(hit.get("href"))
        alt = alt or str(hit.get("label") or "")
    url = safe_url(src)
    if not url:
        return _esc(alt)
    t = f' title="{_esc(title)}"' if title else ""
    img = f'<img src="{_esc(url)}" alt="{_esc(alt)}" loading="lazy"{t}>'
    if alt and ctx.figure:
        return f'<figure class="md-figure">{img}<figcaption>{_esc(alt)}</figcaption></figure>'
    return img


# ------------------------------------------------------------------ blocks

Block = Tuple[str, str]  # (kind, html)


def _starts_block(line: str) -> bool:
    return bool(_ATX_RE.match(line) or _FENCE_RE.match(line) or _HR_RE.match(line) or _QUOTE_RE.match(line) or _LIST_RE.match(line))


def _parse_blocks(lines: List[str], ctx: _Ctx) -> List[Block]:
    blocks: List[Block] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fm = _FENCE_RE.match(line)
        if fm:
            fence = fm.group("fence")
            lang = fm.group("lang") or ""
            j = i + 1
            body: List[str] = []
            while j < n and not re.match(r"^ {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + ",}\\s*$", lines[j]):
                body.append(lines[j])
                j += 1
            cls = f' class="language-{_esc(slugify(lang))}"' if lang else ""
            blocks.append(("pre", f"<pre><code{cls}>{_esc(chr(10).join(body))}</code></pre>"))
            i = j + 1
            continue
        if _HR_RE.match(line):
            blocks.append(("hr", "<hr>"))
            i += 1
            continue
        hm = _ATX_RE.match(line)
        if hm:
            level = len(hm.group("hashes"))
            raw = (hm.group("text") or "").strip()
            inner = _inline(raw, ctx)
            hid = ctx.heading_id(_strip_tags(inner))
            ctx.toc.append({"level": level, "id": hid, "text": _strip_tags(inner)})
            blocks.append(("h", f'<h{level} id="{hid}">{inner}</h{level}>'))
            i += 1
            continue
        if _QUOTE_RE.match(line):
            inner_lines: List[str] = []
            while i < n and (_QUOTE_RE.match(lines[i]) or (lines[i].strip() and inner_lines and inner_lines[-1].strip() and not _starts_block(lines[i]))):
                s = lines[i]
                if _QUOTE_RE.match(s):
                    s = s.lstrip(" ")[1:]
                    if s.startswith(" "):
                        s = s[1:]
                inner_lines.append(s)
                i += 1
            blocks.append(_quote(inner_lines, ctx))
            continue
        lm = _LIST_RE.match(line)
        if lm:
            blk, i = _list(lines, i, ctx)
            blocks.append(blk)
            continue
        if "|" in line and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]) and "|" in lines[i + 1]:
            rows = [line]
            j = i + 2
            while j < n and lines[j].strip() and "|" in lines[j]:
                rows.append(lines[j])
                j += 1
            blocks.append(("table", _table(rows[0], lines[i + 1], rows[1:], ctx)))
            i = j
            continue
        para = [line]
        i += 1
        while i < n and lines[i].strip() and not _starts_block(lines[i]) and not (
            "|" in lines[i] and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]) and "|" in lines[i + 1]
        ):
            para.append(lines[i])
            i += 1
        text = "\n".join(s.lstrip() if k else s for k, s in enumerate(para)).rstrip()
        if _IMAGE_ONLY_RE.match(text):
            ctx.figure = True
            inner = _inline(text, ctx)
            ctx.figure = False
            blocks.append(("figure", inner))
        else:
            blocks.append(("p", "<p>" + _inline(text, ctx) + "</p>"))
    return blocks


def _quote(inner_lines: List[str], ctx: _Ctx) -> Block:
    first = next((s for s in inner_lines if s.strip()), "")
    cm = _CALLOUT_RE.match(first.strip())
    if cm and cm.group("kind").lower() in CALLOUTS:
        kind = cm.group("kind").lower()
        title = cm.group("title").strip() or CALLOUTS[kind]
        idx = inner_lines.index(first)
        rest = inner_lines[idx + 1:]
        body = "".join(h for _, h in _parse_blocks(rest, ctx))
        return ("callout", f'<div class="md-callout md-callout-{kind}" role="note"><p class="md-callout-title">{_inline(title, ctx)}</p>{body}</div>')
    return ("quote", "<blockquote>" + "".join(h for _, h in _parse_blocks(inner_lines, ctx)) + "</blockquote>")


def _list(lines: List[str], i: int, ctx: _Ctx) -> Tuple[Block, int]:
    n = len(lines)
    first = _LIST_RE.match(lines[i])
    assert first is not None
    base_ind = _indent(lines[i])
    ordered = first.group("marker")[0].isdigit()
    start = int(first.group("marker")[:-1]) if ordered else 1
    items: List[List[str]] = []
    content_ind = base_ind
    loose = False

    def same_type(m: "re.Match[str]") -> bool:
        return m.group("marker")[0].isdigit() == ordered

    while i < n:
        line = lines[i]
        if not line.strip():
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j >= n or not items:
                break
            nxt = lines[j]
            nm = _LIST_RE.match(nxt)
            if nm and _indent(nxt) == base_ind and same_type(nm):
                loose = True
                i = j
                continue
            if _indent(nxt) >= content_ind:
                items[-1].append("")
                loose = True
                i = j
                continue
            break
        ind = _indent(line)
        m = _LIST_RE.match(line)
        if m and ind == base_ind and same_type(m):
            content_ind = ind + len(m.group("marker")) + max(1, min(4, len(m.group("sp"))))
            items.append([m.group("rest")])
            i += 1
            continue
        if ind < base_ind or (m and ind == base_ind):
            break
        if items and ind >= content_ind:
            items[-1].append(line[content_ind:])
            i += 1
            continue
        if items and ind > base_ind and m:
            items[-1].append(line[ind:] if ind <= content_ind else line[content_ind:])
            i += 1
            continue
        if items and items[-1] and items[-1][-1].strip() and not _starts_block(line):
            items[-1].append(line.strip())
            i += 1
            continue
        break

    parts: List[str] = []
    for item in items:
        task = _TASK_RE.match(item[0]) if item else None
        if task:
            item = [task.group("rest")] + item[1:]
        blocks = _parse_blocks(item, ctx)
        if not blocks:
            blocks = [("p", "<p></p>")]
        html_parts: List[str] = []
        for k, (kind, frag) in enumerate(blocks):
            if kind == "p" and (not loose or (task and k == 0)):
                frag = frag[3:-4]
            html_parts.append(frag)
        if task:
            n_task = ctx.tasks
            ctx.tasks += 1
            checked = " checked" if task.group("mark").lower() == "x" else ""
            head = html_parts[0] if html_parts else ""
            tail = "".join(html_parts[1:])
            parts.append(f'<li class="md-task"><label class="md-task-label"><input type="checkbox" data-task="{n_task}"{checked}>'
                         f'<span class="md-task-text">{head}</span></label>{tail}</li>')
        else:
            parts.append("<li>" + "".join(html_parts) + "</li>")
    tag = "ol" if ordered else "ul"
    attrs = f' start="{start}"' if ordered and start != 1 else ""
    cls = ' class="md-tasks"' if any(p.startswith('<li class="md-task"') for p in parts) else ""
    return ((tag, f"<{tag}{attrs}{cls}>" + "".join(parts) + f"</{tag}>"), i)


def _split_row(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells: List[str] = []
    cur: List[str] = []
    k = 0
    while k < len(s):
        ch = s[k]
        if ch == "\\" and k + 1 < len(s) and s[k + 1] == "|":
            cur.append("|")
            k += 2
            continue
        if ch == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        k += 1
    cells.append("".join(cur).strip())
    return cells


def _table(head: str, sep: str, body: List[str], ctx: _Ctx) -> str:
    heads = _split_row(head)
    aligns: List[str] = []
    for c in _split_row(sep):
        c = c.strip()
        left, right = c.startswith(":"), c.endswith(":")
        aligns.append("center" if left and right else "right" if right else "left" if left else "")
    width = max(len(heads), len(aligns))
    while len(aligns) < width:
        aligns.append("")

    def cell(tag: str, k: int, text: str) -> str:
        al = f' align="{aligns[k]}"' if k < len(aligns) and aligns[k] else ""
        return f"<{tag}{al}>{_inline(text, ctx)}</{tag}>"

    thead = "<thead><tr>" + "".join(cell("th", k, heads[k] if k < len(heads) else "") for k in range(width)) + "</tr></thead>"
    rows = []
    for r in body:
        cells = _split_row(r)
        rows.append("<tr>" + "".join(cell("td", k, cells[k] if k < len(cells) else "") for k in range(width)) + "</tr>")
    tbody = "<tbody>" + "".join(rows) + "</tbody>" if rows else ""
    return f'<div class="md-table"><table>{thead}{tbody}</table></div>'


# ------------------------------------------------------------------ sanitizer

_ALLOWED_TAGS = frozenset({
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "pre", "code", "em", "strong", "del",
    "a", "img", "table", "thead", "tbody", "tr", "th", "td", "div", "span", "input", "figure", "figcaption", "label", "sup", "sub", "kbd",
})
_VOID_TAGS = frozenset({"br", "hr", "img", "input"})
_DROP_CONTENT = frozenset({"script", "style", "iframe", "object", "embed", "svg", "math", "template", "noscript", "textarea", "title", "head"})
_GLOBAL_ATTRS = frozenset({"class", "id", "title", "data-ref", "data-task", "role"})
_TAG_ATTRS: Dict[str, frozenset] = {
    "a": frozenset({"href", "rel"}), "img": frozenset({"src", "alt", "loading", "width", "height"}),
    "input": frozenset({"type", "checked", "disabled"}), "ol": frozenset({"start"}), "td": frozenset({"align", "colspan", "rowspan"}),
    "th": frozenset({"align", "colspan", "rowspan", "scope"}),
}
_CLASS_RE = re.compile(r"^[\w -]{1,200}$")
_ID_RE = re.compile(r"^[\w-]{1,120}$")
_INT_RE = re.compile(r"^\d{1,4}$")


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []
        self.open: List[str] = []
        self.skip = 0

    def _attrs(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> str:
        allowed = _GLOBAL_ATTRS | _TAG_ATTRS.get(tag, frozenset())
        parts: List[str] = []
        for name, value in attrs:
            name = name.lower()
            if name not in allowed:
                continue
            v = value if value is not None else ""
            if name in ("href", "src"):
                v = safe_url(v)
                if not v:
                    continue
            elif name == "class" and not _CLASS_RE.match(v):
                continue
            elif name == "id" and not _ID_RE.match(v):
                continue
            elif name == "type" and v.lower() != "checkbox":
                continue
            elif name in ("start", "colspan", "rowspan", "width", "height", "data-task") and not _INT_RE.match(v):
                continue
            elif name == "align" and v not in ("left", "right", "center"):
                continue
            elif name == "rel":
                v = "noopener"
            elif name == "loading":
                v = "lazy"
            elif name == "role" and v not in ("note", "img", "presentation"):
                continue
            elif name == "scope" and v not in ("col", "row"):
                continue
            parts.append(f' {name}="{_esc(v)}"' if not (name in ("checked", "disabled")) else f" {name}")
        return "".join(parts)

    @staticmethod
    def _is_checkbox(attrs: List[Tuple[str, Optional[str]]]) -> bool:
        return any(k.lower() == "type" and (v or "").lower() == "checkbox" for k, v in attrs)

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if self.skip:
            if tag in _DROP_CONTENT:
                self.skip += 1
            return
        if tag in _DROP_CONTENT:
            self.skip = 1
            return
        if tag not in _ALLOWED_TAGS or (tag == "input" and not self._is_checkbox(attrs)):
            return
        self.out.append(f"<{tag}{self._attrs(tag, attrs)}>")
        if tag not in _VOID_TAGS:
            self.open.append(tag)

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if self.skip or tag not in _ALLOWED_TAGS or (tag == "input" and not self._is_checkbox(attrs)):
            return
        self.out.append(f"<{tag}{self._attrs(tag, attrs)}>")
        if tag not in _VOID_TAGS:
            self.out.append(f"</{tag}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip:
            if tag in _DROP_CONTENT:
                self.skip -= 1
            return
        if tag in _VOID_TAGS or tag not in _ALLOWED_TAGS or tag not in self.open:
            return
        while self.open:
            t = self.open.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        return

    def handle_decl(self, decl: str) -> None:
        return

    def handle_pi(self, data: str) -> None:
        return

    def unknown_decl(self, data: str) -> None:
        return

    def result(self) -> str:
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


def sanitize(fragment: str) -> str:
    """Allow-list filter: keeps the tags and attributes the renderer emits,
    drops scripts / styles / event handlers / unsafe URLs, escapes the rest."""
    s = _Sanitizer()
    s.feed(str(fragment or ""))
    s.close()
    return s.result()


# ------------------------------------------------------------------ public API


def render(text: str, resolver: Optional[Resolver] = None) -> Dict[str, Any]:
    """Render Markdown ``text``; see the module docstring for the result shape."""
    src = str(text or "").replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    ctx = _Ctx(resolver)
    blocks = _parse_blocks(src.split("\n"), ctx)
    body = "\n".join(frag for _, frag in blocks)
    return {
        "html": sanitize(body),
        "toc": ctx.toc,
        "refs": {k + "s": list(v) for k, v in ctx.refs.items()},
        "missing": ctx.missing,
        "tasks": ctx.tasks,
    }


def find_refs(text: str) -> Dict[str, List[str]]:
    """Cheap scan for ``[[kind:id]]`` references and ``att:`` images (no rendering)."""
    out: Dict[str, List[str]] = {"devices": [], "rooms": [], "pages": [], "attachments": []}
    for m in _REF_RE.finditer(str(text or "")):
        key = m.group("kind") + "s"
        ref = m.group("id").strip()
        if ref and ref not in out[key]:
            out[key].append(ref)
    for m in _ATT_RE.finditer(str(text or "")):
        if m.group("id") not in out["attachments"]:
            out["attachments"].append(m.group("id"))
    return out


def plain_text(text: str, limit: int = 0) -> str:
    """Markdown source reduced to readable text (search fields, summaries)."""
    s = str(text or "").replace("\r\n", "\n")
    s = re.sub(r"```.*?```", " ", s, flags=re.S)
    s = _REF_RE.sub(lambda m: (m.group("label") or m.group("id")).strip(), s)
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"^ {0,3}#{1,6}\s*", "", s, flags=re.M)
    s = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?", "", s, flags=re.M)
    s = re.sub(r"^\s*>\s?(?:\[![A-Za-z]+\]\s*)?", "", s, flags=re.M)
    s = re.sub(r"[`*_~|]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[: limit - 1].rstrip() + "\u2026"
    return s


def headings(text: str) -> List[str]:
    """Heading texts of ``text`` (search index)."""
    out: List[str] = []
    for line in str(text or "").split("\n"):
        m = _ATX_RE.match(line)
        if m and (m.group("text") or "").strip():
            out.append(plain_text(m.group("text")))
    return out


__all__ = ["render", "sanitize", "safe_url", "find_refs", "plain_text", "headings", "slugify", "REF_KINDS", "CALLOUTS"]
