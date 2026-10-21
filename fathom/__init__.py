"""Fathom: know your AV system.

Audio, video and lighting (AVL) documentation: rooms, devices with ports,
port-to-port cables, racks, floor plans, networks, DMX and inventory, plus the
signal-flow maps, patch tables, schedules and a troubleshooting assistant built
from them. Imports the exports you already have (Yamaha CL/QL CSV, Dante
Controller presets, Waves racks, ETC Eos, Videohub, generic CSV) and hosts
everything from a small web app with history, users and an offline viewer.

Pure Python standard library; see ``fathom.server:app`` for the WSGI entry
point and ``fathom.cli`` for the command line.
"""

from __future__ import annotations

__version__ = "0.3.0"
