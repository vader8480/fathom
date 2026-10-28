"""A small YAML subset reader/writer (stdlib only), enough for Rackula layouts
and NetBox device types.

``loads(text)`` reads one document of block mappings and sequences (including
``- key: v`` items and nesting), plain / single- / double-quoted scalars
(escapes, multi-line folding), the core-schema scalars (int, float, bool, null
as ``~`` / ``null`` / empty), ``|`` and ``>`` block scalars with chomping and
indentation indicators, flow ``[...]`` / ``{...}`` collections, comments and
the ``---`` / ``...`` markers. Anchors, aliases, tags, directives, complex keys
and multiple documents raise ``ValueError("line N: ...")``.

``dumps(obj)`` writes plain block style (2-space indent, sequences indented
under their key), quoting strings that would otherwise read back differently.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["loads", "dumps", "resolve_scalar"]

_NULLS = frozenset({"", "~", "null", "Null", "NULL"})
_TRUE = frozenset({"true", "True", "TRUE"})
_FALSE = frozenset({"false", "False", "FALSE"})
_INT_RE = re.compile(r"^[-+]?[0-9]+$")
_HEX_RE = re.compile(r"^0x[0-9a-fA-F]+$")
_OCT_RE = re.compile(r"^0o[0-7]+$")
_FLOAT_RE = re.compile(r"^[-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?$")
_INF_RE = re.compile(r"^[-+]?\.(inf|Inf|INF)$")
_NAN_RE = re.compile(r"^\.(nan|NaN|NAN)$")
_BLOCK_HEADER_RE = re.compile(r"^([|>])(?:([1-9])([+-]?)|([+-])([1-9]?))?(\s+#.*)?$")
_ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r",
    "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0",
    "L": "\u2028", "P": "\u2029",
}
_HEX_ESCAPES = {"x": 2, "u": 4, "U": 8}
_SPECIAL = {"&": "anchors are not supported", "*": "aliases are not supported", "!": "tags are not supported"}


def resolve_scalar(s: str) -> Any:
    """Core-schema resolution of a plain scalar."""
    if s in _NULLS:
        return None
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    if _INT_RE.match(s):
        return int(s)
    if _HEX_RE.match(s):
        return int(s[2:], 16)
    if _OCT_RE.match(s):
        return int(s[2:], 8)
    if _FLOAT_RE.match(s):
        return float(s)
    if _INF_RE.match(s):
        return -math.inf if s.startswith("-") else math.inf
    if _NAN_RE.match(s):
        return math.nan
    return s


# =============================================================== scanning


class _Unterminated(Exception):
    pass


def _is_dash(content: str) -> bool:
    return content[:1] == "-" and (len(content) == 1 or content[1] in " \t")


def _quote_end(s: str, start: int) -> int:
    """Index just past the closing quote of the quoted scalar at ``s[start]``."""
    q = s[start]
    i = start + 1
    n = len(s)
    while i < n:
        c = s[i]
        if q == '"' and c == "\\":
            i += 2
            continue
        if c == q:
            if q == "'" and i + 1 < n and s[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    raise _Unterminated()


def _fold_lines(raw: str, double: bool) -> str:
    """YAML flow folding of the raw text between quotes (before escapes)."""
    if "\n" not in raw:
        return raw
    lines = raw.split("\n")
    out = ""
    empties = 0
    for k, line in enumerate(lines):
        if k > 0:
            line = line.lstrip(" \t")
        if k < len(lines) - 1:
            stripped = line.rstrip(" \t")
            if double and stripped.endswith("\\") and (len(stripped) - len(stripped.rstrip("\\"))) % 2 == 1:
                line = line  # escaped line break: keep the text, join without a space
            else:
                line = stripped
        if k == 0:
            out = line
            continue
        if not line and k < len(lines) - 1:
            empties += 1
            continue
        tail = out.rstrip(" \t")
        if double and tail.endswith("\\") and (len(tail) - len(tail.rstrip("\\"))) % 2 == 1:
            out = tail[:-1] + "\n" * empties + line
        else:
            out += ("\n" * empties if empties else " ") + line
        empties = 0
    return out


def _unescape(s: str) -> str:
    out: List[str] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        e = s[i + 1] if i + 1 < n else ""
        if e in _ESCAPES:
            out.append(_ESCAPES[e])
            i += 2
        elif e in _HEX_ESCAPES:
            k = _HEX_ESCAPES[e]
            hexs = s[i + 2:i + 2 + k]
            if len(hexs) != k or not re.match(r"^[0-9a-fA-F]+$", hexs):
                raise ValueError(f"bad escape \\{e}{hexs}")
            out.append(chr(int(hexs, 16)))
            i += 2 + k
        else:
            raise ValueError(f"unknown escape \\{e}")
    return "".join(out)


def _quoted(s: str, start: int) -> Tuple[str, int]:
    """``(value, end)`` of the quoted scalar at ``s[start]``; ValueError on a bad escape."""
    end = _quote_end(s, start)
    raw = s[start + 1:end - 1]
    if s[start] == "'":
        return _fold_lines(raw, False).replace("''", "'"), end
    return _unescape(_fold_lines(raw, True)), end


def _strip_comment(s: str) -> str:
    """Drop a trailing ``# comment`` (``#`` at the start or after whitespace, outside quotes)."""
    q: Optional[str] = None
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if q:
            if q == '"' and c == "\\":
                i += 2
                continue
            if c == q:
                if q == "'" and i + 1 < n and s[i + 1] == "'":
                    i += 2
                    continue
                q = None
        elif c in "\"'" and (i == 0 or s[i - 1] in " \t[{,:"):
            q = c
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
        i += 1
    return s.rstrip()


def _find_key_colon(s: str) -> Optional[int]:
    """Index of the ``:`` ending a block mapping key on this line, or None."""
    if not s:
        return None
    n = len(s)
    if s[0] in "\"'":
        try:
            i = _quote_end(s, 0)
        except _Unterminated:
            return None
        while i < n and s[i] in " \t":
            i += 1
        if i < n and s[i] == ":" and (i + 1 == n or s[i + 1] in " \t"):
            return i
        return None
    for i, c in enumerate(s):
        if c == "#" and i > 0 and s[i - 1] in " \t":
            return None
        if c == ":" and (i + 1 == n or s[i + 1] in " \t"):
            return i
    return None


def _flow_open(s: str) -> bool:
    """True while brackets are unbalanced or a quote is still open."""
    depth = 0
    q: Optional[str] = None
    i = 0
    while i < len(s):
        c = s[i]
        if q:
            if q == '"' and c == "\\":
                i += 2
                continue
            if c == q:
                if q == "'" and i + 1 < len(s) and s[i + 1] == "'":
                    i += 2
                    continue
                q = None
        elif c in "\"'":
            q = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        i += 1
    return q is not None or depth > 0


def _fold_block(lines: List[str]) -> str:
    """Folded (``>``) block scalar body, trailing newlines excluded."""
    out = ""
    first = True
    prev_more = False
    empties = 0
    for line in lines:
        if line == "":
            empties += 1
            continue
        more = line[:1] in (" ", "\t")
        if first:
            out = "\n" * empties + line
        elif not more and not prev_more:
            out += (" " if empties == 0 else "\n" * empties) + line
        else:
            out += "\n" + "\n" * empties + line
        empties = 0
        prev_more = more
        first = False
    return out


# ================================================================ parser


class _Parser:
    def __init__(self, text: str) -> None:
        if text.startswith("\ufeff"):
            text = text[1:]
        self.lines: List[str] = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.n = len(self.lines)

    def err(self, i: int, msg: str) -> ValueError:
        return ValueError(f"line {max(0, min(i, self.n - 1)) + 1}: {msg}")

    @staticmethod
    def indent_of(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def skip(self, i: int) -> int:
        while i < self.n:
            s = self.lines[i].strip()
            if s and not s.startswith("#"):
                break
            i += 1
        return i

    def check_tabs(self, i: int) -> None:
        line = self.lines[i]
        if "\t" in line[: len(line) - len(line.lstrip(" \t"))]:
            raise self.err(i, "tabs are not allowed in indentation")

    def is_marker(self, i: int, mark: str = "") -> bool:
        line = self.lines[i]
        marks = (mark,) if mark else ("---", "...")
        return any(line.startswith(m) and (len(line) == 3 or line[3] in " \t") for m in marks)

    def at_end(self, i: int) -> bool:
        return i >= self.n or self.is_marker(i)

    def quoted_at(self, i: int, s: str, start: int) -> Tuple[str, int]:
        try:
            return _quoted(s, start)
        except _Unterminated:
            raise self.err(i, "unterminated quoted scalar")
        except ValueError as exc:
            raise self.err(i, str(exc))

    # ------------------------------------------------------------ document

    def document(self) -> Any:
        i = self.skip(0)
        if i < self.n and self.lines[i].startswith("%"):
            raise self.err(i, "directives are not supported")
        if i < self.n and self.is_marker(i, "---"):
            rest = _strip_comment(self.lines[i][3:]).strip()
            if rest:
                self.lines[i] = "    " + rest
            else:
                i += 1
        i = self.skip(i)
        value: Any = None
        if not self.at_end(i):
            self.check_tabs(i)
            value, i = self.node(i, self.indent_of(self.lines[i]), -1)
        i = self.skip(i)
        if i < self.n and self.is_marker(i, "..."):
            i = self.skip(i + 1)
        if i < self.n:
            if self.is_marker(i, "---"):
                raise self.err(i, "multiple documents are not supported")
            raise self.err(i, "unexpected content (check the indentation)")
        return value

    # --------------------------------------------------------------- nodes

    def node(self, i: int, col: int, parent: int) -> Tuple[Any, int]:
        """The node whose first line is ``i``, starting at column ``col``."""
        content = self.lines[i][col:]
        if _is_dash(content):
            return self.sequence(i, col)
        if content[:1] in _SPECIAL:
            raise self.err(i, _SPECIAL[content[0]])
        if content[:2] == "? " or content.rstrip() == "?":
            raise self.err(i, "complex keys are not supported")
        if content[:1] not in "[{" and _find_key_colon(content) is not None:
            return self.mapping(i, col)
        return self.scalar(i, col, content, parent)

    def mapping(self, i: int, col: int) -> Tuple[Dict[str, Any], int]:
        out: Dict[str, Any] = {}
        while True:
            i = self.skip(i)
            if self.at_end(i):
                break
            self.check_tabs(i)
            ind = self.indent_of(self.lines[i])
            if ind < col:
                break
            if ind > col:
                raise self.err(i, "bad indentation of a mapping entry")
            content = self.lines[i][col:]
            if _is_dash(content):
                break
            if content[:2] == "? " or content.rstrip() == "?":
                raise self.err(i, "complex keys are not supported")
            pos = _find_key_colon(content)
            if pos is None:
                raise self.err(i, "expected 'key: value'")
            key = self.key(i, content[:pos].strip())
            if key in out:
                raise self.err(i, f"duplicate key {key!r}")
            value, i = self.value_after(i, col + pos + 1, col, in_map=True)
            out[key] = value
        return out, i

    def sequence(self, i: int, col: int) -> Tuple[List[Any], int]:
        out: List[Any] = []
        while True:
            i = self.skip(i)
            if self.at_end(i):
                break
            self.check_tabs(i)
            ind = self.indent_of(self.lines[i])
            if ind < col:
                break
            if ind > col:
                raise self.err(i, "bad indentation of a sequence entry")
            if not _is_dash(self.lines[i][col:]):
                break
            value, i = self.value_after(i, col + 1, col, in_map=False)
            out.append(value)
        return out, i

    def value_after(self, i: int, at: int, parent: int, in_map: bool) -> Tuple[Any, int]:
        """The value after ``key:`` / ``-`` on line ``i``; its text starts at column ``at``."""
        rest = self.lines[i][at:]
        body = rest.lstrip(" \t")
        if not _strip_comment(body):
            j = self.skip(i + 1)
            if not self.at_end(j):
                self.check_tabs(j)
                ind = self.indent_of(self.lines[j])
                if ind > parent:
                    return self.node(j, ind, parent)
                if in_map and ind == parent and _is_dash(self.lines[j][ind:]):
                    return self.sequence(j, ind)
            return None, i + 1
        col = at + (len(rest) - len(body))
        if body[:1] in _SPECIAL:
            raise self.err(i, _SPECIAL[body[0]])
        if in_map:
            if _is_dash(body):
                raise self.err(i, "a sequence cannot start on the key line")
            return self.scalar(i, col, body, parent)
        self.lines[i] = " " * col + body  # the entry's content, with the dash blanked out
        return self.node(i, col, parent)

    def key(self, i: int, raw: str) -> str:
        if raw[:1] in _SPECIAL:
            raise self.err(i, _SPECIAL[raw[0]])
        if raw[:1] in ("[", "{"):
            raise self.err(i, "complex keys are not supported")
        if raw[:1] in ("'", '"'):
            val, end = self.quoted_at(i, raw, 0)
            if raw[end:].strip():
                raise self.err(i, "unexpected text after a quoted key")
            return val
        return raw

    # ------------------------------------------------------------- scalars

    def scalar(self, i: int, col: int, content: str, parent: int) -> Tuple[Any, int]:
        first = content[:1]
        if first in ("|", ">"):
            return self.block_scalar(i, content, parent)
        if first in ("[", "{"):
            return self.flow(i, content)
        if first in ("'", '"'):
            return self.quoted_multiline(i, content)
        if first in ("@", "`"):
            raise self.err(i, f"a plain scalar cannot start with {first!r}")
        text = _strip_comment(content)
        if _find_key_colon(text) is not None:
            raise self.err(i, "mapping values are not allowed here")
        if text != content.rstrip():
            return resolve_scalar(text.strip()), i + 1
        out = text.strip()
        multi = False
        j = i + 1
        empties = 0
        while j < self.n:
            line = self.lines[j]
            s = line.strip()
            if not s:
                empties += 1
                j += 1
                continue
            if self.indent_of(line) <= parent or s.startswith("#") or self.is_marker(j):
                break
            self.check_tabs(j)
            piece = _strip_comment(s)
            if _is_dash(piece) or _find_key_colon(piece) is not None:
                raise self.err(j, "bad indentation (a mapping or sequence inside a plain scalar)")
            out += ("\n" * empties if empties else " ") + piece
            multi = True
            empties = 0
            j += 1
            if piece != s:
                break
        if not multi:
            return resolve_scalar(out), i + 1
        return out, j - empties if empties else j

    def quoted_multiline(self, i: int, content: str) -> Tuple[str, int]:
        buf = content
        j = i
        while True:
            try:
                end = _quote_end(buf, 0)
                break
            except _Unterminated:
                j += 1
                if j >= self.n:
                    raise self.err(i, "unterminated quoted scalar")
                buf += "\n" + self.lines[j]
        val, _ = self.quoted_at(i, buf, 0)
        if _strip_comment(buf[end:]).strip():
            raise self.err(j, "unexpected text after a quoted scalar")
        return val, j + 1

    def block_scalar(self, i: int, header: str, parent: int) -> Tuple[str, int]:
        m = _BLOCK_HEADER_RE.match(header.strip())
        if not m:
            raise self.err(i, "bad block scalar header")
        style = header.strip()[0]
        digit = m.group(2) or m.group(5)
        chomp = m.group(3) or m.group(4) or ""
        base = max(parent, 0)
        content_indent: Optional[int] = base + int(digit) if digit else None
        lines: List[str] = []
        j = i + 1
        while j < self.n:
            line = self.lines[j]
            if not line.strip():
                lines.append(line[content_indent:] if content_indent is not None and len(line) > content_indent else "")
                j += 1
                continue
            ind = self.indent_of(line)
            if content_indent is None:
                if ind <= parent:
                    break
                content_indent = ind
            if ind < content_indent or (self.is_marker(j) and ind == 0):
                break
            lines.append(line[content_indent:])
            j += 1
        trailing = 0
        while lines and lines[-1].strip(" ") == "":
            lines.pop()
            trailing += 1
        body = "\n".join(lines) if style == "|" else _fold_block(lines)
        if chomp == "-":
            return body, j
        if not lines:
            return ("\n" * trailing if chomp == "+" else ""), j
        if chomp == "+":
            return body + "\n" * (trailing + 1), j
        return body + "\n", j

    def flow(self, i: int, content: str) -> Tuple[Any, int]:
        buf = _strip_comment(content)
        j = i
        while _flow_open(buf):
            j += 1
            if j >= self.n:
                raise self.err(i, "unterminated flow collection")
            buf += " " + _strip_comment(self.lines[j]).strip()
        reader = _FlowReader(buf, lambda msg: self.err(i, msg))
        value = reader.value()
        reader.ws()
        if reader.pos < len(buf):
            raise self.err(j, "unexpected text after a flow collection")
        return value, j + 1


class _FlowReader:
    def __init__(self, s: str, mkerr: Any) -> None:
        self.s = s
        self.pos = 0
        self.mkerr = mkerr

    def ws(self) -> None:
        while self.pos < len(self.s) and self.s[self.pos] in " \t\n":
            self.pos += 1

    def peek(self) -> str:
        return self.s[self.pos] if self.pos < len(self.s) else ""

    def value(self) -> Any:
        self.ws()
        c = self.peek()
        if c == "[":
            return self.seq()
        if c == "{":
            return self.map()
        if c in ("'", '"'):
            try:
                v, self.pos = _quoted(self.s, self.pos)
            except _Unterminated:
                raise self.mkerr("unterminated quoted scalar")
            except ValueError as exc:
                raise self.mkerr(str(exc))
            return v
        if c in _SPECIAL:
            raise self.mkerr(_SPECIAL[c])
        return resolve_scalar(self.plain())

    def plain(self) -> str:
        start = self.pos
        while self.pos < len(self.s):
            c = self.s[self.pos]
            if c in ",[]{}":
                break
            if c == ":" and (self.pos + 1 >= len(self.s) or self.s[self.pos + 1] in " \t,[]{}"):
                break
            self.pos += 1
        return self.s[start:self.pos].strip()

    def seq(self) -> List[Any]:
        self.pos += 1
        out: List[Any] = []
        while True:
            self.ws()
            if self.peek() == "]":
                self.pos += 1
                return out
            if not self.peek():
                raise self.mkerr("unterminated flow sequence")
            item = self.value()
            self.ws()
            if self.peek() == ":":
                raise self.mkerr("mappings inside flow sequences are not supported")
            out.append(item)
            if self.peek() == ",":
                self.pos += 1
            elif self.peek() != "]":
                raise self.mkerr("expected ',' or ']' in a flow sequence")

    def map(self) -> Dict[str, Any]:
        self.pos += 1
        out: Dict[str, Any] = {}
        while True:
            self.ws()
            if self.peek() == "}":
                self.pos += 1
                return out
            c = self.peek()
            if not c:
                raise self.mkerr("unterminated flow mapping")
            if c in ("[", "{"):
                raise self.mkerr("complex keys are not supported")
            if c in _SPECIAL:
                raise self.mkerr(_SPECIAL[c])
            key = self.value() if c in ("'", '"') else self.plain()
            self.ws()
            val: Any = None
            if self.peek() == ":":
                self.pos += 1
                self.ws()
                if self.peek() not in (",", "}"):
                    val = self.value()
            if key in out:
                raise self.mkerr(f"duplicate key {key!r}")
            out[key] = val
            self.ws()
            if self.peek() == ",":
                self.pos += 1
            elif self.peek() != "}":
                raise self.mkerr("expected ',' or '}' in a flow mapping")


def loads(text: str) -> Any:
    """Parse one YAML document (the subset described in the module docstring)."""
    if not isinstance(text, str):
        raise ValueError("line 1: YAML input must be text")
    return _Parser(text).document()


# ================================================================ writer


def _bad_char(c: str) -> bool:
    o = ord(c)
    return o < 32 or o == 127 or 0x80 <= o < 0xA0 or c in "\u2028\u2029\ufeff"


#: Plain strings that YAML 1.1 readers (PyYAML, NetBox tooling) would turn into
#: bools, numbers, sexagesimals or dates; quoted so every reader agrees.
_YAML11_AMBIGUOUS = re.compile(
    r"^(?:[yYnN]|yes|Yes|YES|no|No|NO|on|On|ON|off|Off|OFF"
    r"|[-+]?[0-9_.]+(?:[eE][-+]?[0-9]+)?|0b[01_]+|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+(?:\.[0-9_]*)?"
    r"|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}.*)$"
)


def _needs_quote(s: str) -> bool:
    if s == "" or s != s.strip(" \t\n"):
        return True
    if s[0] in ",[]{}#&*!|>'\"%@`:" or (s[0] in "-?" and (len(s) == 1 or s[1] in " \t")):
        return True
    if ": " in s or s.endswith(":") or " #" in s or "\t" in s or any(_bad_char(c) for c in s):
        return True
    if s.startswith(("---", "...")) or _YAML11_AMBIGUOUS.match(s):
        return True
    return not isinstance(resolve_scalar(s), str)


def _dq(s: str) -> str:
    out = json.dumps(s, ensure_ascii=False)
    return "".join("\\u%04x" % ord(c) if _bad_char(c) else c for c in out)


def _scalar(v: Any) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return ".nan"
        if math.isinf(v):
            return ".inf" if v > 0 else "-.inf"
        r = repr(v)
        return r if any(ch in r for ch in ".e") else r + ".0"
    s = str(v)
    return _dq(s) if _needs_quote(s) else s


def _block_ok(s: str) -> bool:
    if "\n" not in s.rstrip("\n") or s[:1] in (" ", "\t", "\n"):
        return False
    if any(_bad_char(c) and c != "\n" for c in s):
        return False
    return all(ln == ln.rstrip(" \t") for ln in s.split("\n"))


def _block_lines(s: str, ind: int) -> List[str]:
    body = s.rstrip("\n")
    trailing = len(s) - len(body)
    chomp = "-" if trailing == 0 else ("" if trailing == 1 else "+")
    pad = " " * ind
    out = ["|" + chomp] + [pad + ln if ln else "" for ln in body.split("\n")]
    if chomp == "+":
        out.extend([""] * (trailing - 1))
    return out


def _key(k: Any) -> str:
    s = k if isinstance(k, str) else (_scalar(k) if k is None or isinstance(k, (bool, int, float)) else str(k))
    return _dq(s) if _needs_quote(s) else s


def _emit(v: Any, ind: int) -> Tuple[str, List[str]]:
    """``(inline, lines)``: the text after ``key: `` / ``- `` and the lines that follow."""
    pad = " " * ind
    if isinstance(v, dict):
        if not v:
            return "{}", []
        lines: List[str] = []
        for k, x in v.items():
            inline, rest = _emit(x, ind + 2)
            lines.append(f"{pad}{_key(k)}: {inline}" if inline else f"{pad}{_key(k)}:")
            lines.extend(rest)
        return "", lines
    if isinstance(v, (list, tuple)):
        if not v:
            return "[]", []
        lines = []
        for x in v:
            inline, rest = _emit(x, ind + 2)
            if inline:
                lines.append(f"{pad}- {inline}")
                lines.extend(rest)
            else:
                lines.append(pad + "- " + rest[0][ind + 2:])
                lines.extend(rest[1:])
        return "", lines
    if isinstance(v, str) and _block_ok(v):
        bl = _block_lines(v, ind)
        return bl[0], bl[1:]
    return _scalar(v), []


def dumps(obj: Any) -> str:
    """Block-style YAML for JSON-like data (dict / list / str / int / float / bool / None)."""
    inline, lines = _emit(obj, 0)
    if inline:
        return "\n".join([inline] + lines) + "\n"
    return "\n".join(lines) + "\n"
