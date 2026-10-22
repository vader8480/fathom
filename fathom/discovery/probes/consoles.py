"""Console and router protocols with a documented read-only query (active, opt-in).

Three probe objects live here, one per protocol, each contacting only the
hosts listed in its settings, one host at a time over a single TCP
connection, with a pause between commands, a timeout per read and a time
budget per host. None of them sends a command that changes anything:

- :data:`YAMAHA` — Yamaha SCP (CL / QL / TF / DM / Rivage, TCP 49280):
  ``devinfo`` product name, device id and device name, the current scene,
  and input / mix / matrix / DCA channel names via ``get … Label/Name``.
- :data:`VIDEOHUB` — Blackmagic Videohub (TCP 9990): connects and reads the
  state dump the router sends on its own (model, friendly name, unique id,
  input / output labels, routing); nothing is written to the socket. The
  text is parsed by the existing :mod:`fathom.parsers.videohub`.
- :data:`QSYS` — Q-SYS Remote Control (QRC, TCP 1710, JSON-RPC with NUL
  terminators): ``StatusGet`` (platform, design name, state) and
  ``Component.GetComponents`` (component names and types). ``Logon`` is only
  sent when a user / password is configured.

Raw payloads keep the exchanges verbatim (``responses`` / ``text`` /
``messages``) so a capture from a real device replays as a fixture.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
from typing import Any, Dict, List, Optional, Tuple

from ...network import normalize_mac
from . import ACTIVE, Observation, ProbeInfo, ProbeResult, fixture_payload, host_list, split_host_port

CONNECT_TIMEOUT = 4.0
READ_TIMEOUT = 3.0
PAUSE = 0.05  # between commands on one connection
HOST_BUDGET = 20.0  # seconds per host
HOST_PAUSE = 0.2  # between hosts


class ConsoleError(Exception):
    pass


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


class _Conn:
    """One TCP connection with line / NUL framing, read timeouts and a per-host time budget."""

    def __init__(self, host: str, port: int, budget: float = HOST_BUDGET) -> None:
        self.host, self.port = host, port
        self.deadline = time.time() + budget
        self.buf = b""
        self.sent = 0
        try:
            self.sock = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
        except (OSError, socket.timeout) as exc:
            raise ConsoleError(f"{host}:{port}: cannot connect: {getattr(exc, 'strerror', None) or exc}")
        self.sock.settimeout(READ_TIMEOUT)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _left(self) -> float:
        return self.deadline - time.time()

    def send(self, data: bytes) -> None:
        if self._left() <= 0:
            raise ConsoleError(f"{self.host}: time budget used up")
        if self.sent:
            time.sleep(PAUSE)
        self.sent += 1
        try:
            self.sock.sendall(data)
        except (OSError, socket.timeout) as exc:
            raise ConsoleError(f"{self.host}: send failed: {exc}")

    def read_until(self, terminator: bytes, timeout: float = READ_TIMEOUT, max_bytes: int = 1 << 20) -> Optional[bytes]:
        """Bytes up to (excluding) ``terminator``; None on timeout / close."""
        end = time.time() + min(timeout, max(0.1, self._left()))
        while True:
            i = self.buf.find(terminator)
            if i >= 0:
                out, self.buf = self.buf[:i], self.buf[i + len(terminator):]
                return out
            left = end - time.time()
            if left <= 0 or len(self.buf) > max_bytes:
                return None
            self.sock.settimeout(min(READ_TIMEOUT, left))
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                return None
            except OSError:
                return None
            if not chunk:
                return None
            self.buf += chunk

    def drain(self, idle: float = 1.0, total: float = 10.0, stop: bytes = b"") -> bytes:
        """Everything the peer sends on its own until ``stop`` appears, or ``idle`` s pass without data."""
        out = self.buf
        self.buf = b""
        end = time.time() + min(total, max(0.1, self._left()))
        while time.time() < end:
            if stop and stop in out:
                break
            self.sock.settimeout(min(idle, max(0.05, end - time.time())))
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                break
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        return out


class _ConsoleProbe:
    """Shared collect / test loop: hosts in turn, one connection each, failures recorded per host."""

    INFO: ProbeInfo
    PORT: int = 0

    def _settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        s = settings or {}
        return {"hosts": host_list(s.get("hosts")), "username": str(s.get("username") or ""), "password": str(s.get("password") or "")}

    def query(self, conn: _Conn, s: Dict[str, Any], job: Any, quick: bool = False) -> Dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError

    def describe(self, entry: Dict[str, Any]) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def collect(self, settings: Dict[str, Any], job: Any = None) -> Dict[str, Any]:
        fx = fixture_payload(self.INFO.id)
        if fx is not None:
            return fx
        s = self._settings(settings)
        if not s["hosts"]:
            raise ConsoleError("no hosts listed")
        out: Dict[str, Any] = {"fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "hosts": {}}
        for i, item in enumerate(s["hosts"]):
            if i and job is not None:
                job.wait(HOST_PAUSE)
            elif i:
                time.sleep(HOST_PAUSE)
            host, port = split_host_port(item, self.PORT)
            entry: Dict[str, Any] = {"host": host, "port": port, "status": "ok", "error": "", "elapsed": 0.0}
            out["hosts"][item] = entry
            if job is not None:
                job.log(f"{self.INFO.id}: querying {host}:{port} (read-only)")
            t0 = time.time()
            conn = None
            try:
                conn = _Conn(host, port)
                entry.update(self.query(conn, s, job))
            except ConsoleError as exc:
                entry["status"], entry["error"] = "error", str(exc)
                if job is not None:
                    job.log(f"{self.INFO.id}: {exc}", "warn")
            finally:
                if conn is not None:
                    conn.close()
            entry["elapsed"] = round(time.time() - t0, 2)
            if entry["status"] == "ok" and job is not None:
                job.log(f"{self.INFO.id}: {host}: {self.describe(entry)} ({entry['elapsed']} s)")
            if job is not None:
                job.check()
        return out

    def test(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        fx = fixture_payload(self.INFO.id)
        if fx is not None:
            return {"ok": True, "message": f"fixture replay: {len(fx.get('hosts') or {})} hosts", "fixture": True}
        s = self._settings(settings)
        if not s["hosts"]:
            return {"ok": False, "message": "List at least one host first."}
        parts, good = [], 0
        for item in s["hosts"][:4]:
            host, port = split_host_port(item, self.PORT)
            conn = None
            try:
                conn = _Conn(host, port, budget=8.0)
                entry = self.query(conn, s, None, quick=True)
            except ConsoleError as exc:
                parts.append(str(exc))
                continue
            finally:
                if conn is not None:
                    conn.close()
            good += 1
            parts.append(f"{host}: {self.describe(entry)}")
        return {"ok": good > 0, "message": "; ".join(parts), "reachable": good}

    def parse(self, raw: Any, settings: Optional[Dict[str, Any]] = None) -> ProbeResult:
        res = ProbeResult(probe=self.INFO.id)
        if not isinstance(raw, dict):
            res.status = "error"
            res.notes.append(f"{self.INFO.id}: payload is not an object")
            return res
        seen = str(raw.get("fetched") or "")
        hosts = raw.get("hosts") or {}
        if not isinstance(hosts, dict) or not hosts:
            res.status = "skipped"
            res.notes.append(f"{self.INFO.id}: no hosts queried")
            return res
        failed = 0
        for key, entry in hosts.items():
            if not isinstance(entry, dict):
                continue
            host = str(entry.get("host") or key)
            if entry.get("status") != "ok":
                failed += 1
                res.notes.append(f"{self.INFO.id} {host}: {entry.get('error') or 'no data'}")
                continue
            try:
                self.parse_host(host, entry, seen, res)
            except Exception as exc:  # one odd device must not hide the others
                failed += 1
                res.notes.append(f"{self.INFO.id} {host}: could not parse the reply: {type(exc).__name__}: {exc}")
        res.stats.update({"hosts": len(hosts), "failed": failed})
        if failed == len(hosts):
            res.status = "error"
        return res

    def parse_host(self, host: str, entry: Dict[str, Any], seen: str, res: ProbeResult) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


# ------------------------------------------------------------------ Yamaha SCP


_SCP_OK = re.compile(r'^OK\s+(?P<cmd>devinfo\s+\S+|get\s+\S+\s+\d+\s+\d+|sscurrent_ex\s+\S+)\s*(?P<val>.*)$')
_SCP_LISTS: List[Tuple[str, str, int]] = [  # (label, address, cap)
    ("inputs", "MIXER:Current/InCh/Label/Name", 144), ("mixes", "MIXER:Current/Mix/Label/Name", 72),
    ("matrix", "MIXER:Current/Mtrx/Label/Name", 36), ("dca", "MIXER:Current/DCA/Label/Name", 24),
]


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return v


class _Yamaha(_ConsoleProbe):
    PORT = 49280
    INFO = ProbeInfo(
        id="yamaha", label="Yamaha console (SCP)", mode=ACTIVE, maturity="tested", default_enabled=False, targets="hosts",
        help="Asks each listed Yamaha console (CL, QL, TF, DM3 / DM7, Rivage) for its product name, device id and name, the current scene and its input / mix / matrix / DCA channel names.",
        sends="TCP 49280 to the listed consoles only: `devinfo productname|deviceid|devicename|protocolver`, `sscurrent_ex MIXER:Lib/Scene` and `get MIXER:Current/<InCh|Mix|Mtrx|DCA>/Label/Name n 0` "
              "per channel (50 ms apart, stops at the first error, at most 276 reads). Nothing is set or recalled.",
        fields=[{"key": "hosts", "label": "Consoles", "type": "list", "placeholder": "10.20.0.5", "env": "FATHOM_YAMAHA_HOSTS", "help": "Console IP addresses, one per line."}],
    )

    def _cmd(self, conn: _Conn, cmd: str) -> Tuple[bool, str]:
        conn.send(cmd.encode("utf-8") + b"\n")
        for _ in range(50):  # skip unsolicited NOTIFY / OKm lines
            line = conn.read_until(b"\n")
            if line is None:
                raise ConsoleError(f"{conn.host}: no reply to `{cmd}`")
            text = line.decode("utf-8", "replace").strip()
            if text.startswith("OK ") or text == "OK":
                return True, text
            if text.startswith("ERROR"):
                return False, text
        raise ConsoleError(f"{conn.host}: only notifications received")

    def query(self, conn: _Conn, s: Dict[str, Any], job: Any, quick: bool = False) -> Dict[str, Any]:
        responses: List[Dict[str, str]] = []

        def ask(cmd: str) -> Tuple[bool, str]:
            ok, reply = self._cmd(conn, cmd)
            responses.append({"cmd": cmd, "reply": reply})
            return ok, reply

        ok, reply = ask("devinfo productname")
        if not ok:
            raise ConsoleError(f"{conn.host}: devinfo refused: {reply}")
        if quick:
            return {"responses": responses}
        for cmd in ("devinfo deviceid", "devinfo devicename", "devinfo protocolver", "sscurrent_ex MIXER:Lib/Scene"):
            ask(cmd)
            if job is not None:
                job.check()
        for _label, address, cap in _SCP_LISTS:
            for i in range(cap):
                ok, _ = ask(f"get {address} {i} 0")
                if not ok:
                    break
                if job is not None and i % 16 == 15:
                    job.check()
        return {"responses": responses}

    @staticmethod
    def _decode(entry: Dict[str, Any]) -> Dict[str, Any]:
        info: Dict[str, Any] = {"product": "", "device_id": "", "device_name": "", "protocol": "", "scene": "", "channels": {}}
        for r in entry.get("responses") or []:
            m = _SCP_OK.match(str(r.get("reply") or ""))
            if not m:
                continue
            cmd, val = m.group("cmd").split(), _unquote(m.group("val"))
            if cmd[0] == "devinfo":
                key = {"productname": "product", "deviceid": "device_id", "devicename": "device_name", "protocolver": "protocol"}.get(cmd[1])
                if key:
                    info[key] = val
            elif cmd[0] == "sscurrent_ex":
                info["scene"] = val
            elif cmd[0] == "get" and len(cmd) >= 3:
                label = next((lab for lab, addr, _ in _SCP_LISTS if addr == cmd[1]), cmd[1].split("/")[1] if "/" in cmd[1] else cmd[1])
                info["channels"].setdefault(label, []).append({"index": int(cmd[2]) + 1, "name": val})
        return info

    def describe(self, entry: Dict[str, Any]) -> str:
        info = self._decode(entry)
        ch = ", ".join(f"{len(v)} {k}" for k, v in info["channels"].items() if v)
        return f"{info['product'] or 'Yamaha'} '{info['device_name'] or '?'}'" + (f", scene {info['scene']}" if info["scene"] else "") + (f", names: {ch}" if ch else "")

    def parse_host(self, host: str, entry: Dict[str, Any], seen: str, res: ProbeResult) -> None:
        info = self._decode(entry)
        if not info["product"] and not info["device_name"]:
            res.notes.append(f"yamaha {host}: no devinfo answer")
            return
        named = {k: [c for c in v if c["name"] and not re.fullmatch(r"(ch|mx|mt|dca)?\s*\d+", c["name"], re.I)] for k, v in info["channels"].items()}
        dev_id = info["device_id"]
        mac = normalize_mac(dev_id[2:] if dev_id.lower().startswith("0x") else dev_id) if re.fullmatch(r"(0x)?[0-9A-Fa-f]{12}", dev_id) else ""  # the device id is the MAC on CL / QL / TF
        res.observations.append(Observation(
            source="yamaha", mac=mac or "", ip=host if _is_ip(host) else "", hostname="" if _is_ip(host) else host, name=info["device_name"], manufacturer="Yamaha", model=info["product"],
            serial="" if mac else dev_id, kind_hint="console", services=["scp"], seen=seen,
            evidence={"protocol": info["protocol"], "device_id": dev_id, "scene": info["scene"], "channel_names": {k: [[c["index"], c["name"]] for c in v] for k, v in named.items() if v},
                      "channels": {k: len(v) for k, v in info["channels"].items()}, "port": entry.get("port")},
        ))
        res.stats["consoles"] = res.stats.get("consoles", 0) + 1
        res.stats["channel_names"] = res.stats.get("channel_names", 0) + sum(len(v) for v in named.values())
        res.notes.append(f"yamaha {host}: {self.describe(entry)}")


# ------------------------------------------------------------------ Blackmagic Videohub


class _Videohub(_ConsoleProbe):
    PORT = 9990
    INFO = ProbeInfo(
        id="videohub", label="Blackmagic Videohub", mode=ACTIVE, maturity="mature", default_enabled=False, targets="hosts",
        help="Connects to each listed Videohub router and reads the state it announces on connect: model, friendly name, unique id, input / output labels and the current routing.",
        sends="One TCP connection to port 9990 per listed router; nothing is written to the socket — the router sends its state dump on connect and the connection is closed after `END PRELUDE:`.",
        fields=[{"key": "hosts", "label": "Routers", "type": "list", "placeholder": "10.30.0.90", "env": "FATHOM_VIDEOHUB_HOSTS", "help": "Videohub IP addresses, one per line."}],
    )

    def query(self, conn: _Conn, s: Dict[str, Any], job: Any, quick: bool = False) -> Dict[str, Any]:
        text = conn.drain(idle=1.5, total=6.0 if quick else 12.0, stop=b"END PRELUDE:").decode("utf-8", "replace")
        if "VIDEOHUB DEVICE:" not in text and "PROTOCOL PREAMBLE:" not in text:
            raise ConsoleError(f"{conn.host}: no Videohub preamble received" + (" (empty)" if not text.strip() else ""))
        return {"text": text}

    @staticmethod
    def _dump(entry: Dict[str, Any]) -> Any:
        from ...parsers.videohub import VideohubDump, _parse_text

        dump = VideohubDump()
        _parse_text(str(entry.get("text") or ""), dump)
        return dump

    def describe(self, entry: Dict[str, Any]) -> str:
        d = self._dump(entry)
        return f"{d.model or 'Videohub'} '{d.friendly_name or '?'}', {d.inputs}×{d.outputs}, {len(d.routing)} routes, {len(d.input_labels) + len(d.output_labels)} labels"

    def parse_host(self, host: str, entry: Dict[str, Any], seen: str, res: ProbeResult) -> None:
        d = self._dump(entry)
        if not (d.model or d.friendly_name or d.inputs):
            res.notes.append(f"videohub {host}: preamble without a VIDEOHUB DEVICE block")
            return
        mac = normalize_mac(d.unique_id) if re.fullmatch(r"[0-9A-Fa-f]{12}", d.unique_id or "") else ""
        res.observations.append(Observation(
            source="videohub", mac=mac or "", ip=host if _is_ip(host) else "", hostname="" if _is_ip(host) else host, name=d.friendly_name, manufacturer="Blackmagic Design",
            model=d.model.replace("Blackmagic ", "") if d.model else "", serial="" if mac else (d.unique_id or ""), kind_hint="video_router", services=["videohub"], seen=seen,
            evidence={"unique_id": d.unique_id, "inputs": d.inputs, "outputs": d.outputs, "routes": len(d.routing),
                      "input_labels": [[k + 1, v] for k, v in sorted(d.input_labels.items())][:64], "output_labels": [[k + 1, v] for k, v in sorted(d.output_labels.items())][:64],
                      "routing": [[o + 1, i + 1] for o, i in sorted(d.routing.items())][:128], "port": entry.get("port")},
        ))
        res.stats["routers"] = res.stats.get("routers", 0) + 1
        res.stats["routes"] = res.stats.get("routes", 0) + len(d.routing)
        res.notes.append(f"videohub {host}: {self.describe(entry)}")


# ------------------------------------------------------------------ Q-SYS QRC


class _Qsys(_ConsoleProbe):
    PORT = 1710
    INFO = ProbeInfo(
        id="qsys", label="Q-SYS core (QRC)", mode=ACTIVE, maturity="tested", default_enabled=False, targets="hosts",
        help="Asks each listed Q-SYS core for its platform, running design and state (`StatusGet`) and the list of named components with their types (`Component.GetComponents`).",
        sends="TCP 1710 (QRC JSON-RPC) to the listed cores only: `StatusGet` and `Component.GetComponents`; `Logon` first when a user / password is set. No control values are read or written.",
        fields=[
            {"key": "hosts", "label": "Cores", "type": "list", "placeholder": "10.30.0.10", "env": "FATHOM_QSYS_HOSTS", "help": "Core IP addresses, one per line."},
            {"key": "username", "label": "QRC user", "env": "FATHOM_QSYS_USER", "help": "Only when the design has access control enabled."},
            {"key": "password", "label": "QRC password", "secret": True, "env": "FATHOM_QSYS_PASSWORD"},
        ],
    )

    def _rpc(self, conn: _Conn, rid: int, method: str, params: Any, messages: List[Dict[str, Any]]) -> Any:
        conn.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}).encode("utf-8") + b"\x00")
        for _ in range(50):
            frame = conn.read_until(b"\x00")
            if frame is None:
                raise ConsoleError(f"{conn.host}: no reply to {method}")
            frame = frame.strip()
            if not frame:
                continue
            try:
                msg = json.loads(frame.decode("utf-8", "replace"))
            except ValueError:
                continue
            if isinstance(msg, dict):
                messages.append(msg)
                if msg.get("id") == rid:
                    if "error" in msg:
                        err = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
                        raise ConsoleError(f"{conn.host}: {method}: {err.get('message') or err}")
                    return msg.get("result")
        raise ConsoleError(f"{conn.host}: {method}: only notifications received")

    def query(self, conn: _Conn, s: Dict[str, Any], job: Any, quick: bool = False) -> Dict[str, Any]:
        messages: List[Dict[str, Any]] = []
        hello = conn.drain(idle=0.4, total=1.0, stop=b"\x00")  # EngineStatus notification on connect
        for frame in hello.split(b"\x00"):
            try:
                msg = json.loads(frame.decode("utf-8", "replace")) if frame.strip() else None
            except ValueError:
                msg = None
            if isinstance(msg, dict):
                messages.append(msg)
        rid = 1
        if s.get("username") or s.get("password"):
            self._rpc(conn, rid, "Logon", {"User": s.get("username") or "", "Password": s.get("password") or ""}, messages)
            rid += 1
        status = self._rpc(conn, rid, "StatusGet", 0, messages)
        out: Dict[str, Any] = {"status_get": status if isinstance(status, dict) else {"raw": status}, "messages": messages, "components": []}
        if quick:
            return out
        if job is not None:
            job.check()
        comps = self._rpc(conn, rid + 1, "Component.GetComponents", 0, messages)
        out["components"] = [c for c in comps if isinstance(c, dict)] if isinstance(comps, list) else []
        return out

    @staticmethod
    def _status(entry: Dict[str, Any]) -> Dict[str, Any]:
        st = entry.get("status_get") if isinstance(entry.get("status_get"), dict) else {}
        if not st:
            for m in entry.get("messages") or []:
                if isinstance(m, dict) and isinstance(m.get("result"), dict) and "Platform" in m["result"]:
                    st = m["result"]
                    break
                if isinstance(m, dict) and m.get("method") == "EngineStatus" and isinstance(m.get("params"), dict):
                    st = st or m["params"]
        return st or {}

    def describe(self, entry: Dict[str, Any]) -> str:
        st = self._status(entry)
        comps = entry.get("components") or []
        status = st.get("Status") if isinstance(st.get("Status"), dict) else {}
        return f"{st.get('Platform') or 'Q-SYS'} running '{st.get('DesignName') or '?'}' ({st.get('State') or '?'}{', ' + str(status.get('String')) if status.get('String') else ''})" + (f", {len(comps)} components" if comps else "")

    def parse_host(self, host: str, entry: Dict[str, Any], seen: str, res: ProbeResult) -> None:
        st = self._status(entry)
        if not st:
            res.notes.append(f"qsys {host}: no StatusGet answer")
            return
        comps = [c for c in entry.get("components") or [] if isinstance(c, dict)]
        by_type: Dict[str, int] = {}
        for c in comps:
            t = str(c.get("Type") or "?")
            by_type[t] = by_type.get(t, 0) + 1
        dante = [str(c.get("Name")) for c in comps if "dante" in str(c.get("Type") or "").lower()]
        status = st.get("Status") if isinstance(st.get("Status"), dict) else {}
        res.observations.append(Observation(
            source="qsys", ip=host if _is_ip(host) else "", hostname="" if _is_ip(host) else host, manufacturer="QSC", model=str(st.get("Platform") or ""), kind_hint="processor",
            services=["qrc"] + (["dante"] if dante else []), seen=seen,
            evidence={"design": st.get("DesignName"), "design_code": st.get("DesignCode"), "state": st.get("State"), "status": status.get("String"), "status_code": status.get("Code"),
                      "redundant": st.get("IsRedundant"), "emulator": st.get("IsEmulator"), "components": len(comps), "component_types": by_type, "dante_components": dante[:32],
                      "component_names": [str(c.get("Name")) for c in comps][:128], "port": entry.get("port")},
        ))
        res.stats["cores"] = res.stats.get("cores", 0) + 1
        res.stats["components"] = res.stats.get("components", 0) + len(comps)
        res.notes.append(f"qsys {host}: {self.describe(entry)}")


YAMAHA = _Yamaha()
VIDEOHUB = _Videohub()
QSYS = _Qsys()

__all__ = ["CONNECT_TIMEOUT", "ConsoleError", "HOST_BUDGET", "PAUSE", "QSYS", "READ_TIMEOUT", "VIDEOHUB", "YAMAHA"]
