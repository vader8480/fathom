"""Dante Controller exports.

Primary input is a **preset** (File → Save Preset, ``.xml``)::

    <preset version="3.0.0">
      <name>...</name>
      <device>
        <name>FOH-CL5</name>              (also friendly_name / default_name)
        <manufacturer_name>Yamaha</manufacturer_name>
        <model_name>CL5</model_name>
        <txchannel danteId="1" mediaType="audio"><label>Main L</label></txchannel>
        <rxchannel danteId="1" mediaType="audio">
          <label>01</label>
          <subscribed_device>Rio3224</subscribed_device>
          <subscribed_channel>01</subscribed_channel>
        </rxchannel>
      </device>
    </preset>

Older presets use ``<name>`` instead of ``<label>`` on channels and some files
carry a default namespace; both are handled. ``.`` as a subscribed device
means "this device".

Also accepted:

* a **Receive / Transmit tab "Copy Entire Table"** paste saved as text
  (tab-separated, ``Connected To`` cells look like ``01@Rio3224``); the
  receiving device name comes from ``--device`` or the file name;
* a **Device Info table** paste (``Device Name``, ``Model Name``,
  ``Manufacturer`` ...), which only adds device inventory;
* a generic **routing CSV** with receiver / rx channel / transmitter / tx
  channel columns (any header wording containing those words).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .common import ParseResult, cell, column_index, find_header, read_rows, read_text


@dataclass
class DanteChannel:
    id: int
    label: str
    sub_device: str = ""  # rx only
    sub_channel: str = ""  # rx only

    @property
    def subscribed(self) -> bool:
        return bool(self.sub_device and self.sub_channel)


@dataclass
class DanteDevice:
    name: str
    manufacturer: str = ""
    model: str = ""
    default_name: str = ""
    samplerate: str = ""
    latency: str = ""
    tx: List[DanteChannel] = field(default_factory=list)
    rx: List[DanteChannel] = field(default_factory=list)
    addresses: List[str] = field(default_factory=list)
    primary_address: str = ""
    secondary_address: str = ""
    primary_mac: str = ""
    secondary_mac: str = ""

    @property
    def primary_ip(self) -> str:
        return self.primary_address or (self.addresses[0] if self.addresses else "")

    @property
    def secondary_ip(self) -> str:
        return self.secondary_address or (self.addresses[1] if len(self.addresses) > 1 else "")

    @property
    def model_text(self) -> str:
        return " ".join(p for p in (self.manufacturer, self.model) if p).strip()

    def tx_by_label(self, label: str) -> Optional[DanteChannel]:
        key = (label or "").strip().lower()
        for ch in self.tx:
            if ch.label.strip().lower() == key:
                return ch
        if key.isdigit():
            n = int(key)
            for ch in self.tx:
                if ch.id == n:
                    return ch
        return None


@dataclass
class Subscription:
    rx_device: str
    rx_id: int
    rx_label: str
    tx_device: str
    tx_label: str
    tx_id: Optional[int] = None


class DanteNetwork(ParseResult):
    kind = "dante"

    def __init__(self) -> None:
        super().__init__()
        self.preset_name = ""
        self.devices: Dict[str, DanteDevice] = {}

    def device(self, name: str) -> DanteDevice:
        d = self.devices.get(name)
        if d is None:
            d = DanteDevice(name=name)
            self.devices[name] = d
        return d

    def find_device(self, name: str) -> Optional[DanteDevice]:
        if name in self.devices:
            return self.devices[name]
        key = (name or "").strip().lower()
        for d in self.devices.values():
            if d.name.lower() == key or d.default_name.lower() == key:
                return d
        return None

    def subscriptions(self) -> List[Subscription]:
        subs: List[Subscription] = []
        for d in self.devices.values():
            for ch in d.rx:
                if not ch.subscribed:
                    continue
                tx_dev_name = d.name if ch.sub_device.strip() == "." else ch.sub_device
                tx_dev = self.find_device(tx_dev_name)
                tx_ch = tx_dev.tx_by_label(ch.sub_channel) if tx_dev else None
                subs.append(
                    Subscription(
                        rx_device=d.name,
                        rx_id=ch.id,
                        rx_label=ch.label,
                        tx_device=tx_dev.name if tx_dev else tx_dev_name,
                        tx_label=ch.sub_channel,
                        tx_id=tx_ch.id if tx_ch else None,
                    )
                )
        return subs

    def flows(self) -> Dict[Tuple[str, str], List[Subscription]]:
        """(tx device, rx device) → subscriptions, in rx channel order."""
        out: Dict[Tuple[str, str], List[Subscription]] = {}
        for s in sorted(self.subscriptions(), key=lambda s: (s.rx_device, s.rx_id)):
            out.setdefault((s.tx_device, s.rx_device), []).append(s)
        return out

    def summary(self) -> Dict[str, object]:
        subs = self.subscriptions()
        return {
            "kind": self.kind,
            "preset": self.preset_name,
            "devices": len(self.devices),
            "device_list": [f"{d.name} ({d.model_text})" if d.model_text else d.name for d in self.devices.values()],
            "tx_channels": sum(len(d.tx) for d in self.devices.values()),
            "rx_channels": sum(len(d.rx) for d in self.devices.values()),
            "subscriptions": len(subs),
            "unresolved_tx": sorted({s.tx_device for s in subs if s.tx_device not in self.devices}),
            "addresses": {d.name: " / ".join(a for a in (d.primary_ip, d.secondary_ip) if a) for d in self.devices.values() if d.primary_ip or d.secondary_ip},
            "notes": list(self.notes),
        }


# ------------------------------------------------------------------- XML


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _child_text(el: ET.Element, *names: str) -> str:
    wanted = {n.lower() for n in names}
    for ch in el:
        if _local(ch.tag) in wanted and (ch.text or "").strip():
            return (ch.text or "").strip()
    for attr, val in el.attrib.items():
        if attr.lower() in wanted and (val or "").strip():
            return val.strip()
    return ""


def _channel_from(el: ET.Element, fallback_id: int) -> DanteChannel:
    id_text = el.attrib.get("danteId") or el.attrib.get("danteid") or el.attrib.get("id") or _child_text(el, "id", "danteid")
    try:
        cid = int(re.sub(r"\D", "", id_text)) if id_text else fallback_id
    except ValueError:
        cid = fallback_id
    label = _child_text(el, "label", "name", "channel_name", "channelname") or f"{cid:02d}"
    return DanteChannel(
        id=cid,
        label=label,
        sub_device=_child_text(el, "subscribed_device", "subscribeddevice", "subscription_device", "sub_device"),
        sub_channel=_child_text(el, "subscribed_channel", "subscribedchannel", "subscription_channel", "sub_channel"),
    )


def parse_preset_xml(path: Path) -> DanteNetwork:
    net = DanteNetwork()
    net.source_files.append(str(path))
    try:
        tree = ET.parse(str(path))
    except ET.ParseError as exc:
        net.note(f"{path.name}: XML parse error: {exc}")
        return net
    root = tree.getroot()
    net.preset_name = _child_text(root, "name") or root.attrib.get("name", "")
    devices = [el for el in root.iter() if _local(el.tag) == "device"]
    if not devices:
        net.note(f"{path.name}: no <device> elements found (is this a Dante Controller preset?)")
        return net
    for el in devices:
        name = _child_text(el, "name", "friendly_name", "friendlyname", "default_name", "defaultname")
        if not name:
            name = f"device-{len(net.devices) + 1}"
        dev = net.device(name)
        dev.manufacturer = dev.manufacturer or _child_text(el, "manufacturer_name", "manufacturer", "manufacturername", "vendor")
        dev.model = dev.model or _child_text(el, "model_name", "model", "modelname", "product")
        dev.default_name = dev.default_name or _child_text(el, "default_name", "defaultname")
        dev.samplerate = dev.samplerate or _child_text(el, "samplerate", "sample_rate")
        dev.latency = dev.latency or _child_text(el, "unicast_latency", "latency")
        for sub in el.iter():
            if _local(sub.tag) in ("address", "ip", "ipv4", "ip_address"):
                if (sub.text or "").strip():
                    dev.addresses.append(sub.text.strip())
        tx_i = rx_i = 0
        for ch in el:
            tag = _local(ch.tag)
            if tag in ("txchannel", "tx_channel", "transmitchannel"):
                tx_i += 1
                dev.tx.append(_channel_from(ch, tx_i))
            elif tag in ("rxchannel", "rx_channel", "receivechannel"):
                rx_i += 1
                dev.rx.append(_channel_from(ch, rx_i))
        dev.tx.sort(key=lambda c: c.id)
        dev.rx.sort(key=lambda c: c.id)
    # devices referenced only as subscription sources (not captured in the preset)
    for s in net.subscriptions():
        if s.tx_device and s.tx_device not in net.devices:
            net.note(f"transmitter '{s.tx_device}' is referenced by subscriptions but is not in the preset (stub added)")
            net.device(s.tx_device)
    return net


# ----------------------------------------------------------------- tables

_AT_RE = re.compile(r"^(?P<ch>.+?)@(?P<dev>.+)$")
_IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def _exact_col(header: List[str], *names: str) -> Optional[int]:
    """Column whose normalised header equals one of ``names`` (no substring matching)."""
    if not header:
        return None
    cells = [re.sub(r"[^a-z0-9]+", " ", (c or "").lower()).strip() for c in header]
    for n in names:
        if n in cells:
            return cells.index(n)
    return None


def _ip_cell(text: str) -> str:
    """``'192.168.1.21 (Link Up)'`` → ``'192.168.1.21'``; ``N/A`` / blank → ``''``."""
    m = _IP_RE.search(text or "")
    return m.group(1) if m else ""


def parse_table(path: Path, device: str = "") -> DanteNetwork:
    """Receive/Transmit tab copy, Device Info copy, or a generic routing CSV."""
    net = DanteNetwork()
    net.source_files.append(str(path))
    rows = read_rows(path)
    if not rows:
        net.note(f"{path.name}: empty")
        return net
    header_idx = find_header(rows, ("channel", "connected to", "device name", "receiver", "rx device", "transmitter", "tx device", "model"))
    header = rows[header_idx] if header_idx is not None else []
    data = rows[(header_idx + 1) if header_idx is not None else 0 :]

    # Device Info table (Device Name, Model Name, Manufacturer, Primary Address, Secondary Address ...)
    name_idx = column_index(header, "device name", "name", "device") if header else None
    model_idx = column_index(header, "model name", "model", "product type", "product") if header else None
    manu_idx = column_index(header, "manufacturer", "manufacturer name", "vendor") if header else None
    pri_idx = _exact_col(header, "primary address", "primary ip", "primary ip address", "primary")
    sec_idx = _exact_col(header, "secondary address", "secondary ip", "secondary ip address", "secondary")
    pmac_idx = _exact_col(header, "primary mac", "primary mac address", "mac address", "mac")
    smac_idx = _exact_col(header, "secondary mac", "secondary mac address")
    has_info = model_idx is not None or manu_idx is not None or pri_idx is not None
    if name_idx is not None and has_info and column_index(header, "connected to", "receiver", "transmitter") is None:
        n_addr = 0
        for r in data:
            name = cell(r, name_idx)
            if not name:
                continue
            d = net.device(name)
            d.model = cell(r, model_idx) or d.model
            d.manufacturer = cell(r, manu_idx) or d.manufacturer
            pri, sec = _ip_cell(cell(r, pri_idx)), _ip_cell(cell(r, sec_idx))
            if pri:
                d.primary_address = pri
                n_addr += 1
            if sec:
                d.secondary_address = sec
                n_addr += 1
            d.primary_mac = cell(r, pmac_idx) or d.primary_mac
            d.secondary_mac = cell(r, smac_idx) or d.secondary_mac
        extra = f", {n_addr} addresses" if n_addr else ""
        net.note(f"{path.name}: device info table ({len(net.devices)} devices{extra}, no routing)")
        return net

    # Generic routing CSV
    rxd = column_index(header, "receiver", "rx device", "rx_device", "receive device", "to device", "destination device", "destination") if header else None
    rxc = column_index(header, "rx channel", "rx_channel", "receive channel", "to channel", "destination channel", "rx") if header else None
    txd = column_index(header, "transmitter", "tx device", "tx_device", "transmit device", "from device", "source device", "source") if header else None
    txc = column_index(header, "tx channel", "tx_channel", "transmit channel", "from channel", "source channel", "tx") if header else None
    if rxd is not None and txd is not None:
        for r in data:
            rx_dev, tx_dev = cell(r, rxd), cell(r, txd)
            if not rx_dev or not tx_dev:
                continue
            d = net.device(rx_dev)
            net.device(tx_dev)
            rx_label = cell(r, rxc) or str(len(d.rx) + 1)
            rx_id = int(re.sub(r"\D", "", rx_label) or len(d.rx) + 1) if re.search(r"\d", rx_label) else len(d.rx) + 1
            d.rx.append(DanteChannel(id=rx_id, label=rx_label, sub_device=tx_dev, sub_channel=cell(r, txc) or rx_label))
        for d in net.devices.values():
            for s in [c for c in d.rx]:
                tx_dev = net.device(s.sub_device)
                if not tx_dev.tx_by_label(s.sub_channel):
                    tx_dev.tx.append(DanteChannel(id=len(tx_dev.tx) + 1, label=s.sub_channel))
        net.note(f"{path.name}: routing table ({len(net.subscriptions())} subscriptions)")
        return net

    # Receive tab copy: Channel | Connected To (label@device) | ...
    conn_idx = column_index(header, "connected to", "connected", "subscription", "source") if header else None
    ch_idx = column_index(header, "channel", "rx channel", "receive channel") if header else None
    if conn_idx is None:
        # no header: find the column with label@device cells
        width = max(len(r) for r in data)
        for i in range(width):
            vals = [r[i] for r in data if i < len(r) and r[i]]
            if vals and sum(1 for v in vals if _AT_RE.match(v)) / len(vals) > 0.5:
                conn_idx = i
                break
        ch_idx = 0 if conn_idx not in (None, 0) else None
    if conn_idx is not None:
        rx_name = device or path.stem
        d = net.device(rx_name)
        for i, r in enumerate(data, start=1):
            label = cell(r, ch_idx) or str(i)
            m = _AT_RE.match(cell(r, conn_idx))
            rx_id = int(re.sub(r"\D", "", label) or i) if re.search(r"\d", label) else i
            ch = DanteChannel(id=rx_id, label=label)
            if m:
                ch.sub_channel = m.group("ch").strip()
                ch.sub_device = m.group("dev").strip()
                tx_dev = net.device(ch.sub_device)
                if not tx_dev.tx_by_label(ch.sub_channel):
                    tx_dev.tx.append(DanteChannel(id=len(tx_dev.tx) + 1, label=ch.sub_channel))
            d.rx.append(ch)
        net.note(f"{path.name}: receive table for '{rx_name}' ({sum(1 for c in d.rx if c.subscribed)} subscriptions)")
        return net

    net.note(f"{path.name}: not recognised as a Dante preset, routing table or device list")
    return net


def _merge_addresses(tgt: DanteDevice, dev: DanteDevice) -> None:
    for a in dev.addresses:
        if a not in tgt.addresses:
            tgt.addresses.append(a)
    tgt.primary_address = tgt.primary_address or dev.primary_address
    tgt.secondary_address = tgt.secondary_address or dev.secondary_address
    tgt.primary_mac = tgt.primary_mac or dev.primary_mac
    tgt.secondary_mac = tgt.secondary_mac or dev.secondary_mac


def parse_dante(path: Path, device: str = "") -> DanteNetwork:
    if path.is_dir():
        merged = DanteNetwork()
        for f in sorted(path.iterdir()):
            if f.suffix.lower() in (".xml", ".csv", ".tsv", ".txt"):
                part = parse_dante(f, device=device)
                merged.notes.extend(part.notes)
                merged.source_files.extend(part.source_files)
                merged.preset_name = merged.preset_name or part.preset_name
                for name, dev in part.devices.items():
                    tgt = merged.device(name)
                    tgt.manufacturer = tgt.manufacturer or dev.manufacturer
                    tgt.model = tgt.model or dev.model
                    tgt.default_name = tgt.default_name or dev.default_name
                    if dev.tx and not tgt.tx:
                        tgt.tx = dev.tx
                    if dev.rx and not tgt.rx:
                        tgt.rx = dev.rx
                    _merge_addresses(tgt, dev)
        return merged
    head = read_text(path)[:2000].lstrip()
    if head.startswith("<") and ("<preset" in head.lower() or "<device" in head.lower()):
        return parse_preset_xml(path)
    if path.suffix.lower() == ".xml":
        return parse_preset_xml(path)
    return parse_table(path, device=device)
