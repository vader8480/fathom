"""QR Code encoder (ISO/IEC 18004), standard library only.

Byte mode (UTF-8), error correction L/M/Q/H, versions 1–40, smallest fitting
version by default, mask chosen by the standard penalty rules (N1=3, N2=3,
N3=40, N4=10) unless forced. ``to_svg`` draws the dark modules as one path
with a quiet zone.
"""

from __future__ import annotations

import html
from typing import Any, List, Optional, Tuple, Union

ECLS = ("L", "M", "Q", "H")
_FORMAT_BITS = {"L": 1, "M": 0, "Q": 3, "H": 2}

# Index [ecl][version]; version 0 is unused.
_ECC_PER_BLOCK = {
    "L": (-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    "M": (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28),
    "Q": (-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    "H": (-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
}
_NUM_BLOCKS = {
    "L": (-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25),
    "M": (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49),
    "Q": (-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68),
    "H": (-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81),
}

# ------------------------------------------------------------- GF(256)

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gmul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree: int) -> List[int]:
    """Generator polynomial coefficients (highest power first, leading 1 dropped)."""
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            nxt[j] ^= c
            nxt[j + 1] ^= _gmul(c, _EXP[i])
        poly = nxt
    return poly[1:]


def rs_remainder(data: List[int], degree: int) -> List[int]:
    gen = _rs_generator(degree)
    rem = [0] * degree
    for b in data:
        factor = b ^ rem[0]
        rem = rem[1:] + [0]
        for i, g in enumerate(gen):
            rem[i] ^= _gmul(g, factor)
    return rem


def rs_syndromes(codeword: List[int], degree: int) -> List[int]:
    """Syndromes of a data+ECC block (all zero for a valid block)."""
    out = []
    for i in range(degree):
        s = 0
        for c in codeword:
            s = _gmul(s, _EXP[i]) ^ c
        out.append(s)
    return out


# ------------------------------------------------------------ geometry


def _raw_modules(ver: int) -> int:
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        num_align = ver // 7 + 2
        result -= (25 * num_align - 10) * num_align - 55
        if ver >= 7:
            result -= 36
    return result


def data_codewords(ver: int, ecl: str) -> int:
    return _raw_modules(ver) // 8 - _ECC_PER_BLOCK[ecl][ver] * _NUM_BLOCKS[ecl][ver]


def _count_bits(ver: int) -> int:
    return 8 if ver <= 9 else 16


def byte_capacity(ver: int, ecl: str) -> int:
    return (data_codewords(ver, ecl) * 8 - 4 - _count_bits(ver)) // 8


def _align_positions(ver: int) -> List[int]:
    if ver == 1:
        return []
    num = ver // 7 + 2
    step = 26 if ver == 32 else (ver * 4 + num * 2 + 1) // (num * 2 - 2) * 2
    result = [6]
    for i in range(num - 1):
        result.insert(1, ver * 4 + 17 - 7 - i * step)
    return result


class _Grid:
    def __init__(self, ver: int) -> None:
        self.ver = ver
        self.size = ver * 4 + 17
        self.m = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def set_fn(self, x: int, y: int, dark: bool) -> None:
        self.m[y][x] = dark
        self.fn[y][x] = True

    def draw_function_patterns(self, ecl: str) -> None:
        n = self.size
        for i in range(n):
            self.set_fn(6, i, i % 2 == 0)
            self.set_fn(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        dist = max(abs(dx), abs(dy))
                        self.set_fn(x, y, dist not in (2, 4))
        pos = _align_positions(self.ver)
        last = len(pos) - 1
        for i, a in enumerate(pos):
            for j, b in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == last) or (i == last and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_fn(a + dx, b + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(ecl, 0)
        self.draw_version()

    def draw_format(self, ecl: str, mask: int) -> None:
        data = _FORMAT_BITS[ecl] << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        n = self.size

        def bit(i: int) -> bool:
            return (bits >> i) & 1 != 0

        for i in range(0, 6):
            self.set_fn(8, i, bit(i))
        self.set_fn(8, 7, bit(6))
        self.set_fn(8, 8, bit(7))
        self.set_fn(7, 8, bit(8))
        for i in range(9, 15):
            self.set_fn(14 - i, 8, bit(i))
        for i in range(0, 8):
            self.set_fn(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_fn(8, n - 15 + i, bit(i))
        self.set_fn(8, n - 8, True)  # dark module

    def draw_version(self) -> None:
        if self.ver < 7:
            return
        rem = self.ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = self.ver << 12 | rem
        n = self.size
        for i in range(18):
            b = (bits >> i) & 1 != 0
            a, c = n - 11 + i % 3, i // 3
            self.set_fn(a, c, b)
            self.set_fn(c, a, b)

    def draw_codewords(self, data: List[int]) -> None:
        n = self.size
        i = 0
        right = n - 1
        total = len(data) * 8
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = (n - 1 - vert) if upward else vert
                    if not self.fn[y][x] and i < total:
                        self.m[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 != 0
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            row, fnrow = self.m[y], self.fn[y]
            for x in range(self.size):
                if fnrow[x]:
                    continue
                if mask == 0:
                    inv = (x + y) % 2 == 0
                elif mask == 1:
                    inv = y % 2 == 0
                elif mask == 2:
                    inv = x % 3 == 0
                elif mask == 3:
                    inv = (x + y) % 3 == 0
                elif mask == 4:
                    inv = (x // 3 + y // 2) % 2 == 0
                elif mask == 5:
                    inv = x * y % 2 + x * y % 3 == 0
                elif mask == 6:
                    inv = (x * y % 2 + x * y % 3) % 2 == 0
                else:
                    inv = ((x + y) % 2 + x * y % 3) % 2 == 0
                if inv:
                    row[x] = not row[x]

    def penalty(self) -> int:
        n = self.size
        m = self.m
        score = 0

        def lines() -> List[List[bool]]:
            return [row[:] for row in m] + [[m[y][x] for y in range(n)] for x in range(n)]

        for line in lines():
            run_color = False
            run = 0
            history = [0] * 7
            for x in range(n):
                if line[x] == run_color:
                    run += 1
                    if run == 5:
                        score += 3
                    elif run > 5:
                        score += 1
                else:
                    _push(history, run, n)
                    if not run_color:
                        score += _finder_count(history) * 40
                    run_color = line[x]
                    run = 1
            score += _finder_terminate(run_color, run, history, n) * 40
        for y in range(n - 1):
            for x in range(n - 1):
                c = m[y][x]
                if c == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(1 for v in row if v) for row in m)
        total = n * n
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        score += k * 10
        return score


def _push(history: List[int], run: int, n: int) -> None:
    if history[0] == 0:
        run += n  # light border before the symbol
    history.pop()
    history.insert(0, run)


def _finder_count(h: List[int]) -> int:
    n = h[1]
    core = n > 0 and h[2] == n and h[3] == n * 3 and h[4] == n and h[5] == n
    return (1 if core and h[0] >= n * 4 and h[6] >= n else 0) + (1 if core and h[6] >= n * 4 and h[0] >= n else 0)


def _finder_terminate(color: bool, run: int, history: List[int], n: int) -> int:
    if color:
        _push(history, run, n)
        run = 0
    run += n
    _push(history, run, n)
    return _finder_count(history)


# --------------------------------------------------------------- encode


def _codewords(data: bytes, ver: int, ecl: str) -> List[int]:
    bits: List[int] = []

    def put(val: int, length: int) -> None:
        for i in range(length - 1, -1, -1):
            bits.append((val >> i) & 1)

    put(0b0100, 4)
    put(len(data), _count_bits(ver))
    for b in data:
        put(b, 8)
    cap = data_codewords(ver, ecl) * 8
    put(0, min(4, cap - len(bits)))
    put(0, (8 - len(bits) % 8) % 8)
    pad = 0xEC
    while len(bits) < cap:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    words = [int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, len(bits), 8)]
    nblocks = _NUM_BLOCKS[ecl][ver]
    ecclen = _ECC_PER_BLOCK[ecl][ver]
    raw = _raw_modules(ver) // 8
    nshort = nblocks - raw % nblocks
    shortlen = raw // nblocks
    blocks: List[List[int]] = []
    k = 0
    for i in range(nblocks):
        dlen = shortlen - ecclen + (0 if i < nshort else 1)
        dat = words[k:k + dlen]
        k += dlen
        ecc = rs_remainder(dat, ecclen)
        if i < nshort:
            dat = dat + [0]  # placeholder so all blocks have equal length
        blocks.append(dat + ecc)
    out: List[int] = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != shortlen - ecclen or j >= nshort:
                out.append(blk[i])
    return out


def choose_version(n_bytes: int, ecl: str) -> int:
    for v in range(1, 41):
        if n_bytes <= byte_capacity(v, ecl):
            return v
    raise ValueError(f"data too long for a QR code at level {ecl} ({n_bytes} bytes; max {byte_capacity(40, ecl)})")


def encode(data: Union[str, bytes], ecl: str = "M", version: Optional[int] = None, mask: Optional[int] = None) -> List[List[bool]]:
    """Module matrix (True = dark) without quiet zone."""
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    ecl = (ecl or "M").upper()
    if ecl not in ECLS:
        raise ValueError(f"error correction level must be one of {ECLS}")
    if version is None:
        version = choose_version(len(raw), ecl)
    elif not 1 <= version <= 40:
        raise ValueError("version must be 1-40")
    elif len(raw) > byte_capacity(version, ecl):
        raise ValueError(f"data does not fit in version {version}-{ecl}")
    if mask is not None and not 0 <= mask <= 7:
        raise ValueError("mask must be 0-7")
    words = _codewords(raw, version, ecl)
    if mask is None:
        best: Optional[Tuple[int, int]] = None
        for msk in range(8):
            g = _build(words, version, ecl, msk)
            p = g.penalty()
            if best is None or p < best[0]:
                best = (p, msk)
        mask = best[1] if best else 0
    return [row[:] for row in _build(words, version, ecl, mask).m]


def _build(words: List[int], ver: int, ecl: str, mask: int) -> _Grid:
    g = _Grid(ver)
    g.draw_function_patterns(ecl)
    g.draw_codewords(words)
    g.apply_mask(mask)
    g.draw_format(ecl, mask)
    return g


def to_svg(matrix: List[List[bool]], scale: int = 4, border: int = 4, dark: str = "#000000", light: str = "#ffffff") -> str:
    n = len(matrix)
    full = n + 2 * border
    parts = []
    for y, row in enumerate(matrix):
        x = 0
        while x < n:
            if row[x]:
                start = x
                while x < n and row[x]:
                    x += 1
                parts.append(f"M{start + border} {y + border}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    px = full * int(scale)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{px}" height="{px}" viewBox="0 0 {full} {full}" shape-rendering="crispEdges">'
        f'<rect width="{full}" height="{full}" fill="{html.escape(light)}"/>'
        f'<path d="{"".join(parts)}" fill="{html.escape(dark)}"/></svg>'
    )


def svg(text: str, ecl: str = "M", **kw: Any) -> str:
    """SVG of ``text`` (keywords: version, mask → encode; scale, border, dark, light → to_svg)."""
    enc = {k: kw.pop(k) for k in ("version", "mask") if k in kw}
    return to_svg(encode(text, ecl=ecl, **enc), **kw)


def matrix_text(matrix: List[List[bool]]) -> str:
    return "\n".join("".join("1" if v else "0" for v in row) for row in matrix)


__all__ = ["encode", "to_svg", "svg", "rs_remainder", "rs_syndromes", "byte_capacity", "choose_version", "matrix_text", "ECLS"]
