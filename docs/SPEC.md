# Fathom 0.3 "AVL" — Product & Engineering Specification

Status: **approved for implementation** · Spec date: 2026-10-20 · Applies to repo `/Users/pallen/Code/Fathom` (package `fathom`, current version 0.2.0 → this release **0.3.0**).

This document is the single source of truth for six implementation workers (W1–W6), two test workers (T1, T2) and one QA worker. It must be read stand-alone. Where this spec and the existing code disagree, the spec wins, **except** for the compatibility guarantees in §2.3, which are absolute.

Conventions used throughout:

- **MUST / MUST NOT / SHOULD / MAY** have RFC 2119 meaning.
- Every functional requirement has an ID (`FR-<AREA>-<NN>`), a priority and a one-line acceptance criterion. **P0** = release blocker. **P1** = should ship; if it cannot, QA records it as a gap (not a failure of other units). **P2** = stretch; may slip to the roadmap without penalty.
- Paths are repo-relative. `fathom/…` is the Python package. "The data dir" is `$FATHOM_DATA` (default `~/.fathom`, `/data` in Docker).
- JSON examples are normative unless marked *illustrative*.
- "doc" = a v2 project document (a plain `dict` in Python, a plain object in JS). "Project" (capital P) = the existing v1 dataclass `fathom.model.Project`, which survives as the **flow-view model** used by the signal-flow map renderer.

## Table of contents

1. Vision & personas
2. Scope of this release · Out of scope / roadmap · Compatibility guarantees
3. Functional requirements
4. Data model v2 (schema, vocabulary, migration, storage)
5. API contract v2
6. Frontend module contracts
7. Work decomposition (units, file ownership, interfaces, integration order)
8. Quality gates
9. Acceptance checklist
10. Research notes (with citations)
- Appendix A — Vocabulary tables (kinds, media, disciplines, connectors)
- Appendix B — Canonical fixture `sunday-demo` (v2)
- Appendix C — QR reference vectors
- Appendix D — Floor-plan fixtures (Draw.io, DXF)
- Appendix E — Starter equipment library (55 templates)
- Appendix F — Checklist & lexicon formats with seed content
- Appendix G — Migration worked example (RRC Littleton excerpt)

---

## 1. Vision & personas

### 1.1 Vision

Fathom becomes a full **AVL (audio, video, lighting) documentation, troubleshooting and planning tool**: one living model of every venue, room, rack, device, port and cable, from which the team gets signal-flow maps, an interactive patch view, patch tables, floor plans with gear placed on them, rack elevations, cable schedules and labels, IP/DMX schedules, a bill of materials and a troubleshooting assistant that answers questions *about this system* — on a laptop, an iPad at FOH or a phone in the catwalk, online or (for reading) offline.

Design principles:

1. **One model, many views.** Every view (map, patch view, patch table, floor plan, racks, schedules) is a projection of the same doc; an edit anywhere updates everything ("Live — edits update the map").
2. **Imports never overwrite people.** Console/Dante/Waves/Eos/Videohub exports are re-parsed on every build into an *overlay*; manual data always wins (existing v0.2 rule, kept).
3. **Stdlib only, runs anywhere.** Pure Python 3.9+ standard library server, vanilla JS (no build, no CDN). Optional extras (gunicorn, poppler-utils, Chromium, an LLM endpoint) add capability but are never required.
4. **Honest about formats.** Where a format is closed (DWG) or needs a renderer we do not have (PDF in the browser), Fathom says so and offers the realistic path.
5. **Grounded help.** The assistant answers from the traced graph and curated checklists; an LLM, when configured, only rephrases and augments, and its text is labelled.

### 1.2 Personas

| Persona | Context | Top jobs | What "done" looks like for them |
| --- | --- | --- | --- |
| **Volunteer tech** ("Sam", Sunday service) | Phone or iPad, limited training, minutes before service | "Livestream has no audio — what do I check?"; find which port a mic is on; read the patch table | Opens the shared link on a phone, asks the assistant, gets the path and 3 numbered checks; sees port labels; works offline in the booth |
| **FOH engineer** ("Priya", touring/house engineer) | Laptop + iPad at FOH, Dante/Yamaha/Waves exports | Keep patch sheets current from console/Dante exports; re-patch quickly; print patch tables | Imports exports, drags wires in Patch view, prints a patch table and cable labels |
| **Integrator** ("Marco", AV contractor) | Desktop, designing and commissioning | Plan a system (planned vs installed), rack elevations, cable schedule with IDs, IP schedule, BOM with costs, as-built package | Builds a zip with viewer HTML, schedules CSVs, rack SVGs, labels, BOM; hands over QR-labelled gear |
| **Campus AVL director** ("Dana", multi-venue) | Desktop + iPad, several auditoriums, staff + volunteers | Multiple rooms, shared inventory/spares, roles, history/audit, find any device or IP fast | Switches rooms, sees spares across rooms, restores yesterday's revision, gives volunteers read-only access |

---

## 2. Scope of this release

### 2.1 In scope (0.3.0)

| Area | Summary | Owner(s) |
| --- | --- | --- |
| Data model v2 | Venues → rooms → systems; locations; racks; devices with explicit **ports**; **port-to-port cables** (+ bundles); networks/interfaces; DMX addressing; inventory & planning status; floor plans with markers; attachments; project-local templates; schema version 2 with automatic migration from v1 | W1 |
| Storage | Atomic writes, per-project lock, **revisions** with history (ops log + snapshots), restore, **entity-level optimistic concurrency** (ETag/If-Match + rebasing change ops) | W1 |
| Users & roles | admin / editor / viewer, session cookie login, PBKDF2-SHA256 passwords, CLI user admin, `FATHOM_AUTH` bootstrap, public read-only viewer, share links (P1) | W1 (+W2 CLI) |
| API v2 + OpenAPI | Full REST API under `/api/v2`, v1 endpoints kept, `/api/openapi.json`, static/PWA routes, hardening | W1 |
| AVL vocabulary | 35 device kinds, 41 media (audio, video, lighting, control, power), 7 disciplines with colors and key | W2 |
| Importers | Plugin registry; existing Yamaha/Dante/Waves; **new** ETC Eos (CSV/USITT ASCII/Lightwright text), Blackmagic Videohub (protocol dump), generic device/cable CSV (one-shot) | W2 |
| Equipment library | 55 starter templates (Appendix E; ≥ 48 required) + custom templates (global and per project) | W2 |
| Floor plans | Upload PNG/JPG/SVG/PDF/Draw.io/DXF; server converts Draw.io & DXF subsets to SVG, PDF → PNG via a local rasterizer when present; DWG explained | W2 (convert), W4 (UI) |
| Schedules & exports | Cable schedule + auto cable tags + printable label sheet; IP schedule; build package with per-room maps, CSVs, rack SVGs, floor-plan SVGs, BOM, device pages, **QR codes (stdlib encoder)** | W2, W6 |
| Patch view | Knox-style node editor: cards with port rows, port-to-port wires, drag, re-patch, rename inline, pan/zoom/pinch, undo/redo, keyboard, filters | W3 |
| Floor plan & rack UI | Place markers, calibrate scale, measure; rack elevations front/rear with drag-to-RU; schedules and inventory views | W4 |
| App shell | New SPA (hash routing, lazy views), inspector, patch table, search palette, assistant panel, admin views, login, mobile/iPad layout, PWA registration | W5 |
| Viewer upgrades | Per-room signal-flow maps, room index, device pages (QR target), read-only patch table page, tap-friendly tips, offline via service worker | W5 (+W1 SW) |
| Assistant & tracing | Port-level tracing incl. device internal routing and overlay routes; deterministic troubleshooting assistant with checklists and "Update the map?" suggestions; optional OpenAI-compatible LLM bridge | W6 |
| Analysis | Search index, rack occupancy/collisions + rack SVG, DMX schedule/conflicts (W6); BOM and inventory schedule (W2) | W6, W2 |
| Tests & QA | Backend unittest suites, Node unit tests for pure JS cores, headless-Chrome smoke test, QA report | T1, T2, QA |

### 2.2 Out of scope / roadmap

These are deliberately **not** in 0.3.0. Workers MUST NOT start them; the data model leaves room for them.

| Item | Why not now | Prerequisite / note |
| --- | --- | --- |
| Native DWG parsing | DWG is a closed, version-fragmented binary format; no reliable pure-Python reader exists. 0.3 asks for DXF/PDF/SVG and optionally shells out to ODA File Converter (FR-PLAN-07) | ODA licensing; could be a plugin |
| In-browser PDF rendering | Needs pdf.js (third-party JS, forbidden). PDF is rasterized server-side when a rasterizer exists | — |
| Real-time co-editing (live cursors, CRDT/OT, websockets) | WSGI + stdlib has no websocket server; entity-level merge (FR-HIST-05) covers the common case | Could use SSE polling later |
| Webhooks / notifications (Slack, Teams, email) | Needs delivery/retry/secret management; low demand vs. scope | Event names reserved: `project.saved`, `build.created` |
| Live device **monitoring** and active probing (Videohub TCP 9990 live, sACN monitor, SNMP walks, Q-SYS QRC, scheduled scans) | Security review of anything that talks to devices; long-running workers | Passive, on-demand discovery (UniFi controller, mDNS / Dante, LLDP / CDP, ARP) ships as the Discovery view, §3.25a / §5.7.5; import-from-dump paths stay for the rest |
| MVR/GDTF import & export (lighting) | Valuable open standard (zip + XML) but W2 is at capacity; Eos/Lightwright text covers patch now | MVR `GeneralSceneDescription.xml` fixtures/addresses map cleanly onto `device.dmx` |
| ATEM settings XML import | Small, but W2 capacity; listed P2 in FR-IMP-09 and moves here if not delivered | `<Input id shortName longName externalPortType>` |
| Shure Wireless Workbench `.shw`, Dante Controller `.dcproj`, Q-SYS design import, Crestron/Control4/Savant as-built import | Undocumented or proprietary formats; need real sample files | Generic CSV import is the bridge |
| RF frequency coordination | Specialist domain; WWB does this | — |
| Rack power/heat/weight budgets, side views, cable-path routing with length estimation on floor plans | Need reliable template data (power_w, weight) first; fields exist in templates | Template fields already reserved |
| Photo thumbnails / image resizing | No stdlib image codec for JPEG; serve originals with `loading=lazy` | Optional Pillow plugin later |
| SSO (OIDC/SAML/LDAP), per-field audit UI, i18n, native apps | Scope | Users model allows `provider` later |
| LLM tool-calling that edits the model | Safety/grounding; 0.3 only proposes ops the user confirms | Suggestion op format reused |
| Label printer drivers (Brother/Brady), in-app QR scanning | Hardware/APIs vary | Printable sheets + QR SVGs now |
| DXF/Visio export of plans, `.vsdx` import | Scope | — |

### 2.3 Compatibility guarantees (absolute)

1. Every existing `project.json` / `.jsonc` / `.toml` / `.yaml` with `"fathom": 1`, `"signalflow": 1` or **no version key** MUST load, auto-migrate in memory (§4.6) and render. It is written as v2 only on the next save, and the first v2 write saves the original as `project.v1.json` beside it (never overwritten afterwards).
2. `fathom/samples/rrc-littleton/` stays a **v1** project (frozen; nobody edits `project.json` or its existing exports) and MUST still build: `python -m fathom demo`, `python -m fathom selftest`, and the frozen test file `tests/test_fathom.py` (12 tests, nobody edits it) MUST pass unchanged.
3. The flow map of a migrated v1 project MUST be **layout-identical** to v0.2: same card ids and boxes (x, y, w, h), same number of routed links (FR-MIG-03).
4. Existing CLI commands and flags keep working: `serve new import inspect build pdf trace patch validate list demo status selftest`.
5. Existing HTTP routes keep working with the same request/response shapes (§5.12 lists each and its mapping).
6. These public Python functions keep their v0.2 signatures and behavior on v1 `Project` objects: `fathom.model.{Project,Node,Link,Group,Column,Options,Meta,ImportSpec,project_from_dict,validate,slug,norm_name,KINDS,MEDIA,BRANDS,DEFAULT_COLUMNS}`, `fathom.project.{load_project,save_project,new_project,list_projects,load_dict,find_project_file,resolve_project,data_root,projects_root,builds_root,SAMPLES_DIR,STATIC_DIR,blank_project_dict,list_builds,new_build_dir}`, `fathom.merge.apply_imports`, `fathom.layout.compute_layout`, `fathom.render_html.render_html(project, layout)`, `fathom.render_svg.render_svg(project, layout)`, `fathom.patch.{build_patch_sheet,patch_sheet_csv}`, `fathom.trace.{build_graph,find_paths,downstream,upstream,resolve_node,describe_path,graph_json}`, `fathom.parsers.{detect_kind,parse_any,parse_yamaha,parse_dante,parse_waves,KINDS}`, `fathom.parsers.yamaha.{parse_port,parse_channel_label,categorize}`, `fathom.export.{build,write_build,render_project,find_chrome,html_to_pdf,html_to_png}`, `fathom.selftest.run_selftest`.
7. The WSGI entry point stays `fathom.server:app`; the Docker image keeps `gunicorn … fathom.server:app`, port 8080, volume `/data`, `/healthz`.
8. With **no** `FATHOM_AUTH` and no users file, the app behaves as today: no login, everyone has full access (single-user local tool).
9. Python 3.9 compatibility: no `match`, no `X | Y` type unions evaluated at runtime, no parenthesized context managers, no backslashes or same-quote nesting inside f-string expressions, no top-level `import tomllib` (keep it lazy as today), no `zip(strict=)`, no `itertools.pairwise`, no `int.bit_count`, no `isinstance(x, A | B)`. (3.9 APIs such as `str.removeprefix`, `Path.is_relative_to`, `dict | dict` are allowed.) Every module keeps `from __future__ import annotations`. JavaScript is limited to **ES2018 syntax** (no `?.`, `??`, class fields, `#private`, static blocks, top-level `await`, numeric separators, `||=`), and must run in Safari 15+ and current Chrome.

---

## 3. Functional requirements

Format: `ID · Priority · Requirement — **AC:** acceptance criterion · Owner`. "Fixture" means `sunday-demo` (Appendix B, committed as `fathom/static/dev/fixture-v2.json`); "RRC" means `fathom/samples/rrc-littleton`; "campus-demo" means the new v2 sample `fathom/samples/campus-demo` (§7.3, W2).

### 3.1 FR-ROOM — Venues, rooms, systems, locations, shared inventory

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-ROOM-01 | P0 | The doc holds `venues[]`, `rooms[]` (each with a `venue`), `systems[]` (room + discipline) and `locations[]` (§4.3). | `validate_doc(fixture)` returns no errors; an op adding a room is returned by the next GET. | W1 |
| FR-ROOM-02 | P0 | Every device has `room`; `""` means shared inventory / unassigned (spares, storage). | `filterDevices(fixture, {room: ""})` returns exactly `spare-ulxd4d`. | W1, W5 |
| FR-ROOM-03 | P0 | Room picker in the top bar (venue › room, plus "All rooms" for inventory/schedules); room-scoped views (map, patch, table, plan, racks) follow it; the URL carries the room. | Switching room changes the hash to `#/<project>/<room>/<view>` and the patch view shows only that room's devices plus external ghosts. | W5 |
| FR-ROOM-04 | P0 | CRUD for venues, rooms (name, code ≤ 8 chars, kind, venue, order), systems and locations in Settings. | Creating room "Chapel" in the UI shows it in the picker after reload. | W5 |
| FR-ROOM-05 | P0 | Moving a device to another room keeps its cables; cross-room cables appear as external ghost cards/stubs in the other room's views. | After moving `atem-mini` to a new room, the main room patch view shows a ghost "ATEM Mini (Room X)" card with its 4 cables. | W5, W3 |
| FR-ROOM-06 | P1 | Locations (booth, stage, rack room, storage, catwalk) per venue/room; `device.location`; racks reference a location. | Inventory view groups by location. | W4 |
| FR-ROOM-07 | P0 | Each room has its own signal-flow map configuration (`room.flow`: columns, groups, spine, options, extra cards). | `/p/campus-demo/r/<room>` renders a different map for each of the 3 rooms. | W1, W5 |
| FR-ROOM-08 | P1 | Systems: devices may reference a system; inventory and patch view can filter by system. | Filter "Main video" on the fixture shows exactly the 4 devices with `system: main-video`. | W4, W3 |

### 3.2 FR-VOC — AVL vocabulary & color coding

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-VOC-01 | P0 | `fathom/vocab.py` defines the 35 device kinds of Appendix A.1; the 9 v1 keys keep their v1 colors. | `len(KINDS) == 34`; v1 keys present with identical `color`. | W2 |
| FR-VOC-02 | P0 | 41 media (Appendix A.2) with `label, color, dash, width, arrow, discipline, carries, ip, connector, short`; the 14 v1 keys keep identical `label/color/dash/width/arrow`. | Unit test compares the v1 subset field by field. | W2 |
| FR-VOC-03 | P0 | 7 disciplines (audio, video, lighting, network, control, power, other) with color and tag letter (Appendix A.3). | `vocab.as_dict()["disciplines"]` has 7 entries with `color` and `letter`. | W2 |
| FR-VOC-04 | P0 | `GET /api/v2/meta` returns `vocab.as_dict()`; `GET /api/meta` (v1) still returns `kinds`/`media` keyed dicts (now larger) and its other v1 keys. | API test on both endpoints. | W1 |
| FR-VOC-05 | P0 | Per-discipline color coding everywhere: patch-view category pill, wire color/dash by medium, map key shows used kinds and media, schedule rows show discipline chips. | QA visual check against Appendix A colors on the fixture. | W3, W4, W5 |
| FR-VOC-06 | P1 | Connector suggestions (Appendix A.4) offered as a datalist when editing ports and cables. | Inspector port "Connector" field offers the list. | W5 |
| FR-VOC-07 | P0 | Unknown kind/medium values are preserved, rendered as `other`, and reported as warnings, never errors. | A save with medium `"laser"` returns 200 with warning code `unknown_medium`. | W1 |

### 3.3 FR-PORT — Port-level model

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-PORT-01 | P0 | Devices declare ports `{id, name, dir: in|out|io, medium, connector, group, channels, label, note, index, origin}` (§4.3.8). | Validation rejects duplicate port ids in a device (`duplicate_port`) and bad `dir` (`bad_enum`). | W1 |
| FR-PORT-02 | P0 | Cables connect `{device, port}` → `{device, port}`; `port` may be empty (device-level cable, legacy/unknown). | A migrated device-level cable renders in the patch view as a wire to/from the card header. | W1, W3 |
| FR-PORT-03 | P0 | Port-group expansion (§4.4.3) is implemented identically in Python (`schema.expand_port_groups`) and JS (`model-core.expandPortGroups`). | T1 and T2 both pass the shared vectors in `tests/fixtures/port-expansion.json`. | W1, W5 |
| FR-PORT-04 | P0 | Connection rules (§4.4.4): out→in, out→io, io→in, io→io allowed; in→in and out→out refused; medium compatibility warnings; `in` port overuse warning. | JS unit vectors for `canConnect`; Python `validate_doc` emits `port_overuse` for the same case. | W5, W1 |
| FR-PORT-05 | P0 | Device internal routing modes `matrix`, `passthrough`, `none`, `explicit` (§4.4.5), defaulted per kind, used by tracing. | On the fixture, tracing upstream from `stage-box-1:hdmi-out-1` reaches only `hdmi-in-1` (not the analog inputs). | W6 |
| FR-PORT-06 | P0 | Ports editor in the inspector: add, remove, reorder, rename; bulk add "N × <group>"; apply template ports (merge by id, keep cabled ports). | Bulk "8 × Analog In" creates `analog-in-1 … analog-in-8`. | W5 |
| FR-PORT-07 | P1 | Port labels from imports (Yamaha channel names, Videohub labels) show as overlay labels (italic, "from import") when the doc label is empty; never persisted unless the user clicks "Keep label". | Videohub sample labels appear in the patch view; the doc is unchanged. | W3, W5 |

### 3.4 FR-MIG — Migration & compatibility

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-MIG-01 | P0 | `schema.migrate(v1_dict) -> doc` per §4.6. | RRC migrates; `validate_doc` returns 0 errors. | W1 |
| FR-MIG-02 | P0 | Loading auto-migrates in memory for `.json/.jsonc/.toml/.yaml`, `"fathom": 1`, `"signalflow": 1`, or no version key. | Test with a copy of RRC whose version key is `"signalflow": 1`. | W1 |
| FR-MIG-03 | P0 | Layout identity: after `apply_imports` on both, `compute_layout(flow_project(migrate(v1), default_room))` equals `compute_layout(project_from_dict(v1))` box-for-box (ids, x, y, w, h rounded to 0.01) with equal link counts; `to_dict()` equal except node `ports`. | `tests/test_model_v2.py::test_rrc_layout_identity`. | W1 |
| FR-MIG-04 | P0 | First v2 write of a v1 file saves `project.v1.json` (once). | Temp-dir test: file exists after first save, unchanged after second. | W1 |
| FR-MIG-05 | P0 | `fathom migrate <project> [--write]` prints a summary (devices, ports declared/generated, cables, bundles, warnings); `--write` saves v2. | CLI test on a temp copy of RRC. | W2 |
| FR-MIG-06 | P0 | v1 HTTP endpoints keep working (§5.12). v1 `PUT /api/projects/<n>` is accepted only if the stored doc is v1-expressible (§4.6.7); otherwise 409 `code: "v2_required"`. | `tests/test_api.py` covers both branches. | W1 |
| FR-MIG-07 | P0 | v1 port texts resolve to declared ports or generate ports deterministically (§4.6.4). | Migrated RRC: link `drums → neve1` becomes 8 cables `drums:kit-mics-1..8 → neve1:mic-line-in-1..8` in bundle `b-0001`. | W1 |

### 3.5 FR-PV — Patch view (interactive node editor, Knox screenshot b)

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-PV-01 | P0 | Dotted dark canvas. Each device is a card: discipline pill (uppercase, discipline color), name, model line (`manufacturer model`, else `sub`), optional brand badge, `×count`, planned = dashed border, external = 50% opacity + room name. Two port columns: inputs left (dot on the left edge), outputs right (dot on the right edge); `io` ports in a bottom "I/O" section with dots on both edges. Each row: index, ← / → glyph, label (or name), colored medium dot. | Harness renders the fixture; QA compares with Knox screenshot (b). | W3 |
| FR-PV-02 | P0 | Wires port-to-port as cubic curves, color + dash from medium; device-level cables attach to the card header; hovered/selected wire width ×1.6; arrowheads optional (setting). | Harness on fixture shows 15 wires; one per cable. | W3 |
| FR-PV-03 | P0 | Drag cards with mouse, pen and touch; 8 px grid snap (toggle); on drag end one `merge` op per moved device sets `patch: {x, y}` — one undo step per drag. | Drag then ⌘Z restores the previous position exactly. | W3 |
| FR-PV-04 | P0 | Draw a wire by dragging from a port dot onto another port; while dragging, incompatible ports dim and compatible ones glow; dropping on empty canvas cancels; result uses `connectOps`. | Creates one `put` cable op with correct endpoints; in→in drop is refused with a toast. | W3 |
| FR-PV-05 | P0 | Re-patch by dragging a wire end (grab radius 12 px screen) to another port (`repatchOps`); select a wire and press Delete/Backspace to remove (`disconnectOps`). | Re-patch changes only the dragged end; undo restores. | W3 |
| FR-PV-06 | P0 | Inline rename: double-click or Enter on a card title renames the device; on a port row renames the port label; Esc cancels; empty label clears to name. | Op recorded; patch table shows the new label without reload. | W3 |
| FR-PV-07 | P0 | Pan: drag background (mouse/one finger), space+drag, plain wheel/trackpad scroll. Zoom: ⌘/Ctrl+wheel and trackpad pinch (`ctrlKey` wheel), two-finger pinch on touch, `+`/`-`/`0` keys, toolbar buttons, Fit (`F`). Zoom limits 0.15–3.0 about the pointer/midpoint. `gesturestart/change/end` prevented on the canvas only. | On iPad Safari a pinch zooms the canvas, not the page. | W3 |
| FR-PV-08 | P0 | Undo/redo via the shared store (⌘/Ctrl+Z, ⇧⌘Z or Ctrl+Y, toolbar). Every user action = one undo step. | 20 random edits, 20 undos → doc deep-equals the start; 20 redos → deep-equals the end. | W3, W5 |
| FR-PV-09 | P0 | Keyboard: Tab/Shift+Tab cycle cards; arrows move the selected card 8 px (Shift 40 px); Enter rename; Delete removes selected wire (card delete asks to confirm); `C` on a focused port starts a connection, arrows cycle compatible targets, Enter commits, Esc cancels. | Keyboard-only connect works in the harness. | W3 |
| FR-PV-10 | P0 | Filters: discipline chips, status chips, current room / all rooms, text filter (non-matches dim to 25%); toggle "show unconnected ports"; columns with > 12 ports collapse to connected/labelled ports plus "+N more" (click expands that card). | Video chip only: audio-only devices hidden, mixed devices (ATEM) shown. | W3 |
| FR-PV-11 | P0 | Add gear (`ctx.pickTemplate`) placed at viewport center; duplicate; delete with `deleteDeviceOps` (also removes its cables, floor-plan markers, extra map cards). | Adding "Blackmagic ATEM Mini Pro" creates a card with the template's ports. | W3 |
| FR-PV-12 | P0 | Auto-arrange: devices without `patch` get positions from `autoLayout` (layered left→right by cable direction) on load (not persisted until moved or "Save arrangement"); "Auto-arrange" button for selection/all emits ops (one undo step). | Migrated RRC (no positions) shows zero overlapping cards. | W3 |
| FR-PV-13 | P0 | Read-only mode (viewer role, history time-travel, offline viewer): pan/zoom/select/highlight only. | Dragging does nothing; no ops are emitted. | W3 |
| FR-PV-14 | P0 | Highlight API: store `highlight` events dim everything except the given devices/ports/cables; Esc or empty click clears. | An assistant path chip highlights 3 devices and their 3 cables. | W3 |
| FR-PV-15 | P0 | Performance with `makeFixture({devices:150, cables:600})`: initial render ≤ 1500 ms in desktop Chrome, ≤ 2500 ms on an A12+ iPad; card drag ≥ 50 fps (only wires attached to moved cards are recomputed, in `requestAnimationFrame`); pan/zoom = one CSS transform on the world layer. | Smoke test reads `window.__pvStats.renderMs ≤ 1500` from the harness. | W3 |
| FR-PV-16 | P1 | Box select (Shift+drag background), Shift-click multi-select, move all selected together (one undo step). Minimap P2. | Shift-drag selects 3 cards; dragging moves all 3. | W3 |
| FR-PV-17 | P1 | Toggle "Show network routes": overlay routes (Dante subscriptions, Videohub crosspoints) drawn as faint dotted lines between the devices' network ports (aggregated per device pair with a channel count). | Migrated RRC shows Dante routes when toggled. | W3 |
| FR-PV-18 | P0 | Context menu (right-click, or long-press 500 ms on touch): Rename, Duplicate, Delete, Add port…, Open details, Show in rack, Show on plan, Trace from here. | Long-press on iPad opens the menu. | W3 |

### 3.6 FR-PT — Patch table (editable, Knox screenshot c)

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-PT-01 | P0 | One block per device (pill, name, model). One section per port group with a medium-colored heading; inputs table `Device · Source · ← · Input` and outputs table `Output · → · Dest · Device`; side by side ≥ 900 px wide, stacked below. Data = `buildPatchTable` (§6.6). | Structure matches Knox screenshot (c) for the fixture. | W5 |
| FR-PT-02 | P0 | Unpatched ports show "Patch…" → `ctx.pickPort` filtered to compatible ports → `connectOps`. | Patch `main-speakers` Input 2 from `audio-rack-1` Output 2 from the table. | W5 |
| FR-PT-03 | P0 | Inline edit of port labels; "×" removes a patch; all undoable. | Edits show in the patch view without reload. | W5 |
| FR-PT-04 | P0 | Live: the table re-renders on store `doc` events; banner "Live — edits update every view"; optional split view (patch view above, table below) on ≥ 1100 px. | In split view, re-patching a wire updates the table immediately. | W5 |
| FR-PT-05 | P0 | Export CSV client-side (`patchTableCsv`, byte-identical to server `GET …/schedules/patch?format=csv` for the same filter) and Print/PDF (print stylesheet; blocks avoid page breaks). | CSV equality test on the fixture (T2). | W5, W6 |
| FR-PT-06 | P0 | Filters: room, discipline, device text, "only patched". | Filter "atem" shows exactly one block. | W5 |
| FR-PT-07 | P1 | "Show import rows": overlay routes listed under network ports, marked "from import". | RRC FOH console block lists Dante rows when enabled. | W5 |
| FR-PT-08 | P0 | Read-only server page `/p/<n>/r/<room>/patch` (phones, viewers, print). | Renders and prints with no console errors. | W5 |

### 3.7 FR-MAP — Signal-flow map (existing viewer, now per room)

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-MAP-01 | P0 | The existing renderer stays and draws one map per room from `flow_project(doc, room)`. `/p/<n>` = default room (backward compatible); `/p/<n>/r/<room>`; a room switcher in the viewer toolbar when the doc has > 1 room. | campus-demo shows 3 room maps; RRC `/p/<n>` output identical to v0.2 except added toolbar links. | W5, W1 |
| FR-MAP-02 | P0 | The key lists used kinds and media from the new vocabulary; the `network` kind row uses the spine label when the spine is shown. | RRC key still reads "Dante network". | W5 |
| FR-MAP-03 | P0 | Mobile viewer: tap a card toggles its tip (no hover dependence), second tap traces; toolbar wraps; page pinch-zoom is never disabled. | QA on iPhone Safari. | W5 |
| FR-MAP-04 | P0 | Map editing in the app: inspector "Signal-flow map" section (group, column, order, show on map) and a "Groups & columns" dialog in Map view (room.flow groups/columns CRUD, spine label/show, options). | Moving a device to group G re-renders the map iframe after save. | W5 |
| FR-MAP-05 | P1 | The viewer accepts `window.postMessage({type: "fathom:highlight", nodes: [...ids], edges: [[s, d], ...]}, origin)` from the same origin and lights those cards/links; `{type:"fathom:highlight", nodes: []}` clears. | Assistant path highlights in Map view. | W5 |
| FR-MAP-06 | P0 | Room index `/p/<n>/rooms`; device pages `/p/<n>/d/<device>` (identity, location, rack, interfaces, patch rows, notes, photos, QR). | Pages render; links work offline after a visit when the SW is active. | W5, W1 |

### 3.8 FR-PLAN — Floor plans

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-PLAN-01 | P0 | Upload per room: PNG, JPG, SVG, PDF, Draw.io (`.drawio`, `.drawio.xml`, `.xml` with `<mxfile>`/`<mxGraphModel>`), DXF (ASCII). | Every file in `fathom/samples/floorplans/` uploads and displays. | W2, W4, W1 |
| FR-PLAN-02 | P0 | Draw.io → SVG: uncompressed `<mxGraphModel>` children and compressed `<diagram>` text (`base64 → raw inflate (wbits −15) → URL-decode`); vertices (rect, `rounded=1`, `ellipse`, `rhombus`, `text`), edges (source/target centers + `<Array as="points">`), child geometry relative to parent vertex, labels with HTML stripped, `fillColor/strokeColor/dashed/fontSize/fontColor/strokeWidth`; page index selectable. | Appendix D.1 renders 2 shapes, 1 dashed edge, label text "FOH booth". | W2 |
| FR-PLAN-03 | P0 | DXF (ASCII) → SVG subset: LINE, LWPOLYLINE (bulge → SVG arc), POLYLINE/VERTEX/SEQEND, CIRCLE, ARC, TEXT, MTEXT (codes stripped, `\P` → line break), INSERT (translate/scale/rotate, nested ≤ 8), layers (off when color < 0, frozen when flag 70 & 1), `$INSUNITS`; y flipped; entities on hidden layers skipped. ELLIPSE, MINSERT, DIMENSION blocks, SOLID are P1. Binary DXF → 415. | Appendix D.2 expectations (size, layer groups, element counts). | W2 |
| FR-PLAN-04 | P0 | SVG sanitization: drop `<script>`, `<foreignObject>`, `on*` attributes, `javascript:` URLs, external `href`/`xlink:href` (only `#frag` and `data:image/(png|jpeg|gif|svg+xml)` kept), `<iframe>/<embed>/<object>`; plans shown via `<img>`. | Security fixture loses all active content (T1). | W2 |
| FR-PLAN-05 | P0 | PDF → PNG (page `page`, default 0) with the first available rasterizer: `$FATHOM_PDF_RASTERIZER` (command template with `{in} {out} {page} {dpi}`), `pdftoppm`, `mutool draw`, `gs`, macOS `sips`. None → HTTP 422 `code: "pdf_unsupported"` with guidance ("Export the page as PNG or SVG, or install poppler-utils"). Docker image installs `poppler-utils` by default. | With `pdftoppm` present a PNG floor plan is created; with an empty `PATH` → 422 with that guidance. | W2, W1 |
| FR-PLAN-06 | P0 | DWG upload → 415 `code: "dwg_unsupported"`: "DWG is a closed format. Export DXF (AutoCAD: SAVEAS → DXF), PDF or SVG, or configure the ODA File Converter (FATHOM_ODA)." | Message contains "DXF". | W2, W1 |
| FR-PLAN-07 | P1 | Optional ODA File Converter: if `FATHOM_ODA` names the binary, convert DWG → DXF with args `<in_dir> <out_dir> ACAD2018 DXF 0 1 <filename>` (prefixed by `xvfb-run -a` when `FATHOM_ODA_XVFB=1`), 120 s timeout, verify output exists (exit code is not trusted), then process as DXF. | Unit test with a fake converter script that writes a DXF. | W2 |
| FR-PLAN-08 | P0 | Place markers by dragging devices from a side list (room devices, unplaced first) onto the plan; drag to move; delete; marker = discipline-colored dot + name (+ count); tap selects the device (inspector) with "Open device page". | Markers persist in `floorplan.markers[]` with normalized `x, y ∈ [0,1]`. | W4 |
| FR-PLAN-09 | P0 | Pan/zoom by mouse, trackpad and touch pinch (same rules as FR-PV-07). | iPad pinch zooms the plan. | W4 |
| FR-PLAN-10 | P0 | Calibrate: pick 2 points, enter real distance + unit (m/ft); measure tool shows distances in settings units. | Calibrating 10 m on the DXF fixture then measuring the same two points shows 10.0 m (±1%). | W4 |
| FR-PLAN-11 | P1 | Layer toggles for DXF-derived plans (server re-render with `?hide=` and image swap). | Hiding `WALLS` removes the walls. | W4, W2 |
| FR-PLAN-12 | P0 | Multiple plans per room (floor, RCP/ceiling, stage); rename, reorder, delete (keeps files unless "also delete files"). | campus-demo main room has 2 plans. | W4 |
| FR-PLAN-13 | P0 | Server-side SVG of a plan with markers and a legend for exports. | Build contains `floorplans/<id>.svg` with one `<g data-device="…">` per marker. | W2 |

### 3.9 FR-RACK — Rack elevations

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-RACK-01 | P0 | Racks: name, room, location, units (1–60), numbering `bottom_up`/`top_down`, faces, notes. | Create a 12U rack in the UI. | W4, W1 |
| FR-RACK-02 | P0 | Device placement `rack: {id, u, height, face, side, depth}`: `u` = lowest occupied RU (1-based, 1 = bottom), `height` defaults to template `ru` (else 1), face `front`/`rear`, side `full`/`left`/`right` (half-width), depth `full`/`half` (full-depth blocks both faces). | Fixture `shure-wireless` renders at U10, left half, front. | W4, W6 |
| FR-RACK-03 | P0 | Front/rear elevation: rails with RU numbers per numbering, device blocks (name, model, `nU`, discipline color stripe), empty RU shown as blanks. | Harness shows the 12U FOH rack with one device. | W4 |
| FR-RACK-04 | P0 | Drag within/between racks snapping to RU; drag unracked devices in from a side list; dropping on an occupied RU is refused (red ghost) unless Alt/Option is held (force, creates a collision warning). | Drop onto an occupied RU is refused; Alt-drop places with a warning. | W4 |
| FR-RACK-05 | P0 | Validation warnings `rack_overlap`, `rack_out_of_range`, `rack_unknown` (§4.7). | `racks.validate_racks` lists an overlap for two full-width devices at the same U/face. | W6 |
| FR-RACK-06 | P0 | Print stylesheet (one rack per page, front and rear side by side) and server SVG per rack/face for builds. | Build contains `racks/rk-foh-front.svg` and `racks/rk-foh-rear.svg`. | W4, W6 |

### 3.10 FR-CAB — Cable schedule & labels

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-CAB-01 | P0 | Cable fields: tag, type, `length_m` (shown in settings units), color, channels, status, signal, note, bundle. | Inspector edits round-trip through save/reload. | W5, W1 |
| FR-CAB-02 | P0 | Auto cable tags from `settings.cable_tag_pattern` (default `{D}-{n:03}`, grammar §4.8): `GET …/cables/tag-preview?scope=missing|all` returns ops; the UI shows them and commits on confirm; `missing` never changes existing tags. | Fixture `scope=missing`: c-0001, c-0002, c-0007, c-0009, c-0010, c-0011 → `A-006…A-011`; c-0012, c-0013, c-0014 → `V-001…V-003`; c-0015 (usb, discipline other) → `X-001`; `A-001…A-005` unchanged (§4.8). | W2, W4 |
| FR-CAB-03 | P0 | Cable schedule JSON + CSV (columns §5.8.2), filters room, state, discipline. | CSV header row equals the spec. | W2 |
| FR-CAB-04 | P0 | Printable label sheet (HTML): two labels per cable (end A, end B); row 1 = tag (AVIXA F501.01 primary identifier), row 2 = `FROM-CODE port → TO-CODE port` (secondary), row 3 = end marker `A`/`B`; uppercase sans-serif ≥ 2.5 mm cap height; grid configurable (`cols, rows, width_in, height_in, page letter|a4`, default 3×10, 2.625×1 in, letter). | Fixture sheet contains 2 × (number of tagged cables) labels. | W2 |
| FR-CAB-05 | P1 | Bundles (multicore/loom/snake) with tag prefix and member cables, listed in the schedule. | Migrated RRC bundle `b-0001` lists 8 members. | W2, W4 |
| FR-CAB-06 | P0 | The cable schedule CSV re-imports via the generic CSV importer, updating tag/type/length/color/note by cable `id` (or tag). | Changing one length in the CSV yields exactly one `merge` op in preview. | W2 |

### 3.11 FR-NET — IP / network schedule

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-NET-01 | P0 | `networks[]` (name, vlan, subnet CIDR, gateway, protocol) and `device.interfaces[]` (§4.3.9), validated with stdlib `ipaddress`. | Invalid IP → `bad_ip` warning; invalid CIDR → `bad_subnet` warning. | W1 |
| FR-NET-02 | P0 | IP schedule JSON/CSV of manual interfaces plus overlay interfaces from imports (Dante preset addresses; Dante Device Info paste "Primary Address"/"Secondary Address"), each row with `source` (`manual`, `dante`, …); manual wins on the same device+role. | A Device Info paste with addresses yields rows with `source: "dante"`. | W2 |
| FR-NET-03 | P0 | Warnings: `ip_duplicate` (same IP twice in the same network or both without network), `ip_outside_subnet`, `bad_mac`, `vlan_mismatch`. | Duplicate IP test. | W2 |
| FR-NET-04 | P0 | MAC display normalized to `aa:bb:cc:dd:ee:ff`; accepted inputs: colon, dash, dotted (Cisco `aabb.ccdd.eeff`), bare 12 hex. | `AABB.CCDD.EEFF` displays `aa:bb:cc:dd:ee:ff`. | W2, W4 |
| FR-NET-05 | P1 | Switch port mapping: `interface.switch` = device of kind `switch`/`network`, `switch_port` = one of its port ids (or free text); schedule shows "Switch · Port". | campus-demo IP schedule shows switch ports. | W2, W4 |

### 3.12 FR-DMX — Lighting addressing

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-DMX-01 | P0 | `device.dmx = {universe 1–63999, address 1–512, footprint 1–512, mode, channel (string), protocol dmx|sacn|artnet, port}`; footprint defaults from template `dmx_footprint`. | Out-of-range universe → `dmx_range` warning. | W1, W6 |
| FR-DMX-02 | P0 | DMX schedule per universe sorted by address, end = address + footprint − 1; warnings `dmx_overlap`, `dmx_overflow` (end > 512), `dmx_footprint_unknown`. | An overlapping pair is flagged with both device ids. | W6 |
| FR-DMX-03 | P0 | Overlay DMX from Eos/Lightwright imports fills rows for devices without manual `dmx` (manual wins); auto fixtures listed with `source`. | Eos sample yields rows with `source: "eos"`. | W6, W2 |
| FR-DMX-04 | P1 | Show sACN multicast group `239.255.<u>>8>.<u&255>` and Art-Net Net/Sub-Net/Universe split of port-address `u − 1` (Art-Net counts from 0) in the schedule. | Universe 300 → `239.255.1.44`; Art-Net port-address 299 = Net 1, Sub-Net 2, Universe 11. | W6 |

### 3.13 FR-LIB — Equipment library

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-LIB-01 | P0 | ≥ 48 templates (Appendix E lists 55; ship all that you can verify) as `fathom/library/templates/<id>.json`. | `len(load_library()) ≥ 48`; every template passes `validate_template`. | W2 |
| FR-LIB-02 | P0 | Template format §4.5 (port groups expanded by §4.4.3; `ru`, `width`, `power_w`, `weight_kg`, `cost`, `dmx_footprint`, `routing`, `checks`, `tags`, `source_url`). | Schema test. | W2 |
| FR-LIB-03 | P0 | Library list/search/get API and a picker dialog (search, discipline filter, port-group preview). | Search "rio" returns `yamaha-rio3224-d2` and `yamaha-rio1608-d2`. | W2, W1, W5 |
| FR-LIB-04 | P0 | Custom templates: per project (`doc.templates[]`) and global (`<data>/library/*.json`, editor role via API); extension dirs `FATHOM_LIBRARY`. Precedence: project > global custom > extension dirs > built-in. | A project template with a built-in id overrides it in that project only. | W2 |
| FR-LIB-05 | P0 | "Save as template" from a device (ports → groups by `group`) and "Apply template" (adds missing ports by id, never removes cabled ports; idempotent). | Applying twice yields no ops the second time. | W2, W5 |
| FR-LIB-06 | P1 | **Device type presets** (`fathom/presets.py`, `GET /api/v2/presets`): ≥ 26 generic AV / IT device types (UPS, PDU, copper and fibre patch panels, 24/48-port switches, router/firewall, access point, server, NAS, KVM, media converter, Dante/AES67 interface, stagebox, audio console, amplifier, DSP, wireless mic receiver, IEM transmitter, video switcher, projector, display, camera, encoder/decoder, lighting console, dimmer/relay pack, DMX node) grouped Power / Network & IT / Audio / Video / Lighting. Each has an Appendix A.1 `kind` (no new kinds), default port groups, typical `ru`, aliases and the relevant fields (`dante`, `dmx_footprint`, `width`, `routing`). Presets are also library templates (`manufacturer: "Generic"`, `source: "preset"`, lowest precedence; cannot be deleted, `?override=1` to shadow). The Add gear dialog opens on a **Presets** tab (searchable, grouped) that pre-fills a create form (name, kind, manufacturer, model, rack units, per-group port counts; 0 drops a group); the **Library** tab is the FR-LIB-03 picker. An unedited form keeps `device.template = <preset id>`; editing kind, manufacturer, model, RU or ports detaches the device and stores its RU as `rack.height`. The CSV `kind` column accepts a preset id, label or alias (§5.7.4). | `len(presets) ≥ 26`; every preset validates as a template; CSV `kind: ups` → `kind: power`, `template: generic-ups`, 6 outlets. | — |

### 3.14 FR-INV — Inventory

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-INV-01 | P0 | `device.inventory` = serial, asset_tag, firmware, purchase_date, warranty_until, vendor, cost, currency, po, notes; plus status, location, rack, interfaces, attachments. | Inspector edits persist. | W1, W5 |
| FR-INV-02 | P0 | Inventory view: device table (current room or all), configurable columns, sort, filters (status, room, location, kind, text), multi-select bulk set status/room/location. | Bulk set 3 devices to `spare` = one undo step. | W4 |
| FR-INV-03 | P0 | Photos/documents per device: upload (`<input type=file accept="image/*,application/pdf" capture>` on iOS), list, open, delete. | JPG uploaded on iPad appears in the inspector. | W5, W1 |
| FR-INV-04 | P0 | Inventory CSV export (all device fields flattened, one row per device). | CSV contains `serial` and `asset_tag` columns. | W4 |
| FR-INV-05 | P1 | Quick filters "warranty < 90 days" and "missing serial". | Filter works on fixture (`sound-board` has no warranty → excluded). | W4 |
| FR-INV-06 | P1 | `device.inventory.condition` ∈ `vocab.CONDITIONS` (`new, good, fair, poor, broken`, Appendix A.5; `GET /api/v2/meta` → `conditions`). `normalize` drops unknown values; `validate_doc` warns `bad_condition`. Inventory schedule / CSV column `condition`. | `conditions` has 5 entries; `condition: "mint"` → warning then dropped on save. | P1A |
| FR-INV-07 | P1 | **Custom fields**: `device.inventory.fields` is a str→str object (≤ 32 keys, keys trimmed to ≤ 40 chars, values stringified to ≤ 500 chars, empty keys dropped). The inventory schedule adds one `field:<key>` column per distinct key (sorted) after the fixed columns. **Project trash**: `DELETE /api/v2/projects/<n>` moves the project (and its builds) to `$FATHOM_DATA/trash/` (§4.10) for 30 days; `GET /api/v2/trash`, restore and purge routes (§5.6); `fathom trash list\|restore\|purge [--expired]`. | 40 keys → 32 kept; trashed project absent from `GET /api/v2/projects`, back after restore; restore onto a live name → 409. | P1A |
| FR-INV-08 | P1 | **Containers**: kind `container` ("Container / case", discipline `other`); `device.container` = id of the container device. Warnings `container_missing`, `container_not_container`, `container_cycle`; `schema.container_contents(doc) -> {container_id: [device_id]}` (computed, never persisted). Schedule column `container` = the container's name. | Cycle a→b→a yields two `container_cycle` warnings. | P1A |
| FR-INV-09 | P1 | **Short codes**: `device.short_code` = 8 chars over `23456789ABCDEFGHJKLMNPQRSTUVWXYZ` (no 0/1/I/O), shown as `XXXX-XXXX` (`schema.format_short_code` / `parse_short_code`). Every write (`save_doc`, `/changes`), project creation from a template and `fathom codes backfill [project]` assign missing codes (`schema.ensure_short_codes`, unique per doc, `secrets.choice`); a device written without its code keeps the stored one (codes are sticky); `settings.short_codes: false` opts a project out. Search: exact code (either spelling, any case) scores 100 and the device subtitle ends with ` · XXXX-XXXX`. `GET /api/v2/codes/<code>` resolves a code across projects; `GET /c/<code>` is the URL printed on labels (§5.13). | `/c/<code>` → 302 to the app for editors, to `/p/<n>/d/<id>` for viewers, HTML 404 when unknown. | P1A |
| FR-INV-10 | P0 | UI for FR-INV-06 — physical condition `device.inventory.condition` ∈ `new | good | fair | poor | broken` (server vocabulary `GET /api/v2/meta` `conditions`; the client falls back to those five). Inventory view: `condition` column (chip, same pill as status) with a multi-value filter, bulk **Set condition…** (one undo step); inspector: Condition select with an empty option. | Bulk set 2 devices to `poor` = one undo step; the inspector select writes `inventory.condition` and `—` clears it. | P1A, P1C |
| FR-INV-11 | P0 | UI for FR-INV-07 — custom fields `device.inventory.fields` (string → string, ≤ 32 keys, key trimmed to ≤ 40 chars). Inventory view: one `field:<key>` column per distinct key (the first three shown by default, the rest in Columns); inspector: key/value editor (add, remove, inline edit) that writes the whole object through ops on change/blur (removed keys are `null` in the merge), duplicate keys refused inline (`feedback.inlineError`). | Editing `bin` keeps the other keys; a duplicate key writes nothing and shows the error. | P1A, P1C |
| FR-INV-12 | P0 | UI for FR-INV-08 — containers: a device of kind `container` holds others through `device.container` (its id). Inventory view: `container` column (name; click selects the container), filter by container, quick filters **Accessories** (no ports, not a container), **In containers**, **Containers**, bulk **Put in container…** (containers or *None*); inspector: *Stored in* select on ordinary devices, *Holds (n)* list on containers (each entry selects that device). | Quick filter *Containers* lists `case-foh` only; bulk put 2 devices in it = one undo step. | P1A, P1C |
| FR-INV-13 | P0 | UI for FR-INV-09 — short codes: `device.short_code` (8 chars from `23456789ABCDEFGHJKLMNPQRSTUVWXYZ`, server-assigned) shown as `XXXX-XXXX`, `—` when absent; **Copy link** copies `api.codeLink(code)` = `<origin>/c/XXXX-XXXX`; `GET /api/v2/codes/<code>` resolves it. Inventory `code` column and the inspector *Code* row (with the device QR as a thumbnail). | `foh-cl5` with `short_code: ABCD2345` shows `ABCD-2345`; the Copy link button carries `/c/ABCD-2345`. | P1A, P1C |

### 3.15 FR-PLN — Planning & BOM

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-PLN-01 | P0 | Status `planned | installed | spare | retired` on devices and cables; views, schedules and builds filter by state `as_built` (installed), `planned` (planned + installed), `all` (default; retired hidden unless `all`). | A build with `state=as_built` omits planned devices from maps and schedules. | W1, W2, W5 |
| FR-PLN-02 | P0 | Planned items render distinctly: dashed border (patch view, map), "planned" chip (tables). | QA visual. | W3, W5 |
| FR-PLN-03 | P0 | BOM: group by template id (else `manufacturer + model`, else `kind`); qty = Σ(count or 1); per device line cost = (`inventory.cost` if set, else template `cost`, else 0) × (count or 1); group `extended` = Σ line costs, `unit_cost` = extended/qty when every member has the same per-unit cost, else `null` ("varies"); per-status counts; cables grouped by medium + type with count and total length; totals per currency; CSV. Starter templates ship with `cost: null`. | Fixture BOM grand total = 6498.00 USD (4499 + 1999). | W2 |
| FR-PLN-04 | P1 | Bulk "Mark installed" for selected planned items. | Ops set `status: installed`. | W4 |

### 3.16 FR-AST — Troubleshooting assistant (Knox screenshot a)

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-AST-01 | P0 | Assistant panel: drawer (desktop/iPad) or full-screen sheet (phone); question box, 4 suggestion chips, transcript (session-local); opened by toolbar button and ⌘/Ctrl+J. | Opens via both; Esc closes. | W5 |
| FR-AST-02 | P0 | Deterministic pipeline (§5.10, §6.9): parse intent (type, symptom, discipline, targets, working references, room) → port-level upstream trace from each target → differential against working references → suspect segment → numbered checks from checklists (kinds, media, template `checks`) → optional suggestion. No network access needed. | Fixture, question "House sound is fine, but the livestream has no audio.": `paths[0].text == "Audio Rack 1 · Stream → ATEM Mini · Stream → USB Stream Out → Restream"`; `len(checks) ≥ 3`; `checks[0].text` contains "Audio Rack 1" and "Stream"; `intent.symptom == "no_audio"`, `intent.targets == ["restream"]`, `intent.working == ["main-speakers", "sub-x2"]`. | W6 |
| FR-AST-03 | P0 | "Update the map?" card: the answer may carry `suggestion {text, ops, base_revision}`; Yes commits the ops through the normal pipeline (undoable), No dismisses; if the doc revision moved since `base_revision`, the UI re-asks before committing. | Yes on the fixture answer sets `atem-mini` port `analog-in-1` note to `Stream feed: Audio Rack 1 → ATEM Mini · check Audio tab`. | W6, W5 |
| FR-AST-04 | P0 | Trace questions ("how does the sound board get to the subs", "what feeds Samsung TV - 1") return `intent.type = "trace"` with paths and no checks. | "What feeds Samsung TV - 1?" returns a path through `video-converter` and `atem-mini`. | W6 |
| FR-AST-05 | P1 | Locate/describe questions ("where is the spare ULXD4D", "what is on Audio Rack 1 input 3"). | Answers include location/rack and port label "Wireless 1". | W6 |
| FR-AST-06 | P0 | Path chips are buttons: click selects the device/port and emits `highlight` for the whole path (patch view dims others; Map view via postMessage). | Clicking a chip selects that device in the inspector. | W5 |
| FR-AST-07 | P0 | Optional LLM bridge (OpenAI-compatible `POST {FATHOM_LLM_URL}/chat/completions`), configured only by env (`FATHOM_LLM_URL`, `FATHOM_LLM_MODEL`, `FATHOM_LLM_API_KEY`, `FATHOM_LLM_TIMEOUT` default 20 s, `FATHOM_LLM_MAX_CONTEXT` default 24000 chars). Grounding = question + traced subgraph + checks (§6.9.6). Output shown as "AI notes — verify against the system". The deterministic answer is always present; failures set `llm.error` and never fail the request. | Stub server → `llm.used == true` and `llm.text` non-empty; not configured → `llm.used == false` and no socket opened (T1 patches `urllib.request.urlopen` to assert). | W6 |
| FR-AST-08 | P0 | Unresolved entity names are reported with up to 3 search suggestions ("I couldn't find 'projector 2'. Did you mean: …?"). | `unresolved` non-empty for "projector 2 has no picture" on the fixture. | W6 |
| FR-AST-09 | P0 | CLI `fathom ask <project> "<question>" [--room R] [--json] [--no-llm]`. | Prints summary, path(s) and numbered checks. | W2 (CLI), W6 |

### 3.17 FR-TRC — Tracing

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-TRC-01 | P0 | Port graph (§6.9.3): cable edges (direction from→to; both ways when `bidirectional` or both ports `io`), device internal edges by routing mode and `carries` intersection, overlay route edges (Dante subscriptions, console patch, Videohub crosspoints). | Unit tests on the fixture. | W6 |
| FR-TRC-02 | P0 | Discipline filter: only edges whose medium carries the discipline; internal edges need both ports' media to carry it. | Video trace from `samsung-tv-1:sdi-in-1` reaches `atem-mini:hdmi-in-1` but not `atem-mini:analog-in-1`. | W6 |
| FR-TRC-03 | P0 | Upstream, downstream and A→B search (depth 24, limit 50, simple paths), path text rendering §6.9.4. | Unit test. | W6 |
| FR-TRC-04 | P0 | `GET …/trace` and CLI `fathom trace <project> <dev[:port]> [<dev[:port]>] [--discipline D] [--up]`; v1 card-level functions unchanged. | `tests/test_fathom.py` still passes; port-level CLI prints hops. | W6, W2 |
| FR-TRC-05 | P0 | Patch view "Trace from here" highlights reachable ports/cables (client-side using the same algorithm on the doc; overlay routes included when loaded). | Harness: downstream audio trace from `audio-rack-1:analog-out-4` highlights exactly cables c-0011, c-0013, c-0014, c-0015. | W3 |

### 3.18 FR-SRCH — Search

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-SRCH-01 | P0 | Search devices (name, code, aliases, manufacturer, model, serial, asset tag, note), ports (name, label, note), cables (tag, label, signal, note), interfaces (ip, mac, hostname), networks (name, id, VLAN, subnet, protocol), rooms, racks, floor plans, attachments (name), SOP pages. Every hit carries `status` (§5.11). Known limits: the query must be a field value, so `vlan 20` does not match a network (`20` does); `model-core.searchLocal` (offline) indexes no SOP pages. | `10.20.0.40` finds the `atem-mini` interface; `20` ranks network `av-dante` first (match `vlan`). | W6, SEARCH |
| FR-SRCH-02 | P0 | Search palette (⌘/Ctrl+K, `#app-search`; §6.13.6): a dropdown under `#app-search` at md/lg, a full-screen sheet at sm; a category select (`CATEGORIES`: All, Devices, Inventory, Rooms, Racks, Ports, Cables, Networks, Plans, Procedures, Files); results grouped by kind (6 per group in All, 50 in a single category); recents (`fathom.ui.recent.<project>`) and, in All, a *Go to* list of sections when the query is empty; arrows + Enter navigate to `targetFor(hit)` (device → `devices/<id>`; port → `devices/<dev>/ports?sel=port:…`; cable → `schedules/cables?sel=cable:<id>`; interface → `devices/<dev>/network?hl=<iface>`; network → `settings/networks?hl=<id>`; room → `rooms/<id>`; rack → `racks/<id>`; floor plan → `plan/<id>`; attachment → `devices/<dev>/files?hl=<id>`; page → `sop?page=<slug>`; Inventory category → `inventory?sel=device:<id>&sec=inventory`). Viewers see no draft pages. | Keyboard navigation works at three sizes. | W5, SEARCH |
| FR-SRCH-03 | P0 | Offline fallback `searchLocal` with the same hit shape (§5.11); the palette wraps it in `search-core.augmentLocal`, which adds network hits (same fields as `fathom/search.py`) and `status` on every hit. | Works with the network disabled. | W5, SEARCH |
| FR-SRCH-04 | P0 | Ranking: exact (100) > prefix (80) > token (60) > substring (40) > fuzzy, edit distance 1 on tokens ≥ 4 chars (25); ties by kind order device, port, cable, interface, network, room, rack, floorplan, attachment, page (`fathom.search.KIND_ORDER` = `search-core.KIND_ORDER`), then title. | "atem" ranks `ATEM Mini` first; networks do not reorder other hits. | W6, W5 |
| FR-SRCH-05 | P0 | Short-code match: when `search-core.isShortCodeQuery(q)` (`^[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}$`) the palette also calls `api.lookupCode(q)` in parallel with the text search; a 200 prepends the device hit `{kind: 'device', id, title: name, subtitle: 'Code XXXX-XXXX · <room>', score: 100, match: 'code'}` (`search-core.codeHit`, deduped by id); 404 or offline adds nothing. Offline, `augmentLocal` adds the same hit for a device whose `short_code` equals the query. | `abcd-2345` leads with `foh-cl5` when the lookup answers; an unknown code shows the text results only. | P1C |

### 3.19 FR-HIST — History & concurrency

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-HIST-01 | P0 | Every successful write creates revision N+1 with UTC time, author, summary, source (`put|changes|restore|migrate|import|files|cli`), touched entity refs. | Three writes → three history entries. | W1 |
| FR-HIST-02 | P0 | View any revision read-only (nearest snapshot + ops replay) and restore it as a new revision. | Restoring rev 2 makes the doc content equal to rev 2 (except `revision`), with a new revision number. | W1, W5 |
| FR-HIST-03 | P0 | `ETag: "r<rev>"` on GET; full PUT needs `If-Match: "r<rev>"` or body `base_revision`; missing → 428. | Test. | W1 |
| FR-HIST-04 | P0 | Stale PUT whose touched refs do not intersect refs touched since the base revision is rebased and accepted (`rebased: true`); intersecting → 409 with `conflicts`. | Two-client test. | W1 |
| FR-HIST-05 | P0 | `POST …/changes` (ops + base_revision) follows the same rule. | Test. | W1 |
| FR-HIST-06 | P0 | Client conflict UI: banner "Someone else changed <names>"; **Reload** (drop my pending ops for conflicting refs, re-apply the rest on fresh doc) or **Keep mine** (resend all with the current revision as base). | Manual two-tab QA. | W5 |
| FR-HIST-07 | P1 | Diff between two revisions (added/removed/changed refs) in the History view. | Shows changed device ids. | W1, W5 |
| FR-HIST-08 | P0 | Snapshot every 25 revisions and at revision 1; history files are append-only. | Storage layout test. | W1 |

### 3.20 FR-USER — Users, roles, sessions

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-USER-01 | P0 | Roles admin > editor > viewer (matrix §5.2); per-project overrides P1. | Viewer PUT → 403. | W1 |
| FR-USER-02 | P0 | `<data>/users.json`; PBKDF2-HMAC-SHA256, 600 000 iterations, 16-byte salt, stored `pbkdf2_sha256$600000$<b64 salt>$<b64 hash>`; `hmac.compare_digest`. | File never contains a plaintext password. | W1 |
| FR-USER-03 | P0 | `/login` page; `POST /api/v2/session` sets `fathom_session` (HMAC-SHA256 signed, HttpOnly, SameSite=Lax, Secure on HTTPS, Max-Age 14 days, Path = app root); logout clears; password change bumps `epoch` (other sessions invalid). | Tests. | W1, W5 |
| FR-USER-04 | P0 | HTTP Basic still accepted for users.json users and `FATHOM_AUTH` users. | `curl -u` works. | W1 |
| FR-USER-05 | P0 | `FATHOM_AUTH="u:p[,u2:p2]"` users are admins, in memory only. Auth is on iff `FATHOM_AUTH` is set or users.json has ≥ 1 enabled user; when off, every request acts as an admin named `local`. | Tests both modes. | W1 |
| FR-USER-06 | P0 | `FATHOM_PUBLIC_VIEW=1` keeps `/p/**`, `/builds/**` public. | Test. | W1 |
| FR-USER-07 | P0 | CLI `fathom user add <name> [--role R] [--password-stdin]`, `list`, `passwd <name>`, `role <name> <role>`, `remove <name>`. | CLI test with a temp data dir. | W2, W1 |
| FR-USER-08 | P0 | Admin UI: list, add, disable/enable, reset password, set role. | Manual QA. | W5 |
| FR-USER-09 | P1 | Share links: `POST …/shares` → token; `/s/<token>/…` mirrors `/p/<project>/…` read-only; revocable; optional expiry. | Revoked token → 404. | W1, W5 |
| FR-USER-10 | P1 | Login throttling: 5 failures per (IP, username) in 5 min → 429 for 5 min (per process). | Test. | W1 |
| FR-USER-11 | P1 | **Invite links** (no e-mail): admins create one-time links (`POST /api/v2/invites` → `url`, `fathom invite create`), stored in `<data>/invites.json` with role, per-project overrides, creator, expiry (default 72 h) and `used_by`/`used_at`. `GET /invite/<token>` (public page `invite.html` + `invite.js`) asks `GET /api/v2/invites/<token>/check` and posts username + password to `…/accept`, which creates the user, marks the invite used and sets the session cookie like a login. Accepting with login off creates the first user (that is how an admin bootstraps logins). Expired entries are pruned on list; revoked / used / expired → 404 `invalid_invite`; accept attempts are throttled per (IP, token) like logins. | `tests/test_invites.py`. | P2A |
| FR-USER-12 | P1 | **Editing lock**: `settings.locked` (+ server-stamped `locked_by`, `locked_at`). While locked, `POST …/changes` and `PUT /api/v2/projects/<n>` answer **423** `{"error", "code": "locked", "details": {"locked_by", "locked_at"}}` unless the request is the lock change itself (only `settings/locked*` touched). Any editor may unlock (the lock prevents accidents, not people). Covers the model editors only: builds, problem reports, SOP pages and file uploads are unaffected. `GET /api/v2/projects` entries carry `locked`, `locked_by`, `locked_at`. | `tests/test_lock.py`. | P2A |
| FR-USER-13 | P1 | **Suggest an improvement**: problem reports carry `kind ∈ problem \| suggestion` (§5.16); suggestions are optionally forwarded as JSON to `settings.suggest_url` / `FATHOM_SUGGEST_URL` (5 s timeout, failures logged, `forwarded` flag) and listed server-wide for admins at `GET /api/v2/suggestions`. | `tests/test_suggestions.py`. | P2A |

### 3.21 FR-MOB — Mobile, responsive, PWA

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-MOB-01 | P0 | Breakpoints (`router-core.layoutFor`, `BP = {md: 700, lg: 1100}`): **lg** ≥ 1100 px = section nav `#app-views` + docked drawer; **md** 700–1099 px (iPad portrait) = drawer as a right-hand sheet; **sm** < 700 px = section bar `#app-tabbar` (one `button[data-tab=<section>]` per `SECTIONS` entry the role may see), drawer as an 88dvh bottom sheet, explorer as a slide-in drawer, search and assistant full screen. Under `(pointer: coarse)` buttons, selects, chips, inputs, section buttons (`.app-sec`) and the `#app-views`/`#app-subnav` bars are ≥ 44 px; the subnav pills (`a.app-subtab`) are 36 px inside the 44 px bar (28 px on fine pointers). No view scrolls the page horizontally. | QA at 390×844, 820×1180, 1440×900; `test_ui_shell.py::test_sections_and_tab_bar`, `::test_no_page_hscroll_on_any_view`. | W5, SHELL |
| FR-MOB-02 | P0 | Editing works on iPad by touch in patch view, plans, racks, inspector; inputs ≥ 16 px font; hit targets ≥ 44 px under `(pointer: coarse)`. | QA on iPad Safari or Chrome touch emulation. | W3, W4, W5 |
| FR-MOB-03 | P0 | Viewer pages work on phones (map pinch-zoom, tap tips, stacked patch table, device pages). | QA. | W5 |
| FR-MOB-04 | P0 | `/manifest.webmanifest` (name "Fathom", short_name "Fathom", id "/", start_url "./", scope "./", display "standalone", theme_color `#0b1020`, background_color `#0b1020`, icons 192/512 PNG any + 512 maskable) and `apple-touch-icon` 180 PNG. | Chrome DevTools manifest pane shows no errors. | W1 |
| FR-MOB-05 | P0 | `/sw.js` (scope `/` or the app root): precache app shell (§6.10 asset list); network-first + cache fallback for `/p/**` navigations and `GET /api/v2/projects/<n>`; stale-while-revalidate for `/static/**`; never cache non-GET, `/api/v2/session`, `/login`, `/builds/**/*.zip`. Registered only when `window.isSecureContext`. | Offline reload of a visited `/p/<n>` on `http://localhost` works. | W1, W5 |
| FR-MOB-06 | P0 | "Make available offline" per project: shell posts `{type: "fathom:prefetch", urls: [...]}` to the SW, which caches them and replies `{type: "fathom:prefetched", ok, failed}`. URL list = `GET /api/v2/projects/<n>/offline-manifest`. | Then offline navigation to a device page works. | W1, W5 |
| FR-MOB-07 | P0 | iOS quirks handled (FR list in §6.11): `100vh`→`100dvh` fallback, safe-area insets, no hover-only affordances, canvas-only `touch-action: none` and `gesture*` prevention, pointer capture, non-selectable draggables, no `position: fixed` inputs under the keyboard. | QA checklist §6.11. | W3, W4, W5 |
| FR-MOB-08 | P0 | Offline editing: queued ops persist in `localStorage["fathom.pending.<project>"]` and flush on reconnect; banner shows the pending count. | DevTools offline, 2 edits, online → exactly one new revision. | W5 |

### 3.22 FR-EXT — Extensibility

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-EXT-01 | P0 | Importer registry `fathom.plugins`: built-ins registered on import of `fathom.parsers`; plugin modules (`*.py`, packages) in `FATHOM_PLUGINS` dirs (os.pathsep-separated) are imported and their `register(api)` called; any exception is caught, logged to stderr and listed in `/api/v2/meta` `plugins_errors`. | A temp plugin dir registering importer `dummy` makes it appear in `/api/v2/meta` `importers`. | W2 |
| FR-EXT-02 | P0 | Plugin API object: `api.version` (str), `api.register_importer(Importer)`, `api.register_template_dir(path)`, `api.register_checklist_dir(path)`. | Test. | W2 |
| FR-EXT-03 | P0 | Library extension dirs (`FATHOM_LIBRARY`) and checklist extension dirs (`FATHOM_CHECKLISTS`, plus plugin-registered) are merged at load. | An extra checklist file changes the assistant's checks for its kind. | W2, W6 |
| FR-EXT-04 | P0 | `/api/openapi.json` (OpenAPI 3.1) documents every route registered in `server.py`; `/api/docs` renders it as HTML (no third-party JS). | Test enumerates the route table and asserts each path+method is in the spec. | W1 |
| FR-EXT-05 | P0 | `fathom plugins` lists importers (kind, label, mode, source module) and plugin errors. | CLI test. | W2 |

### 3.23 FR-EXP — Exports & builds

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-EXP-01 | P0 | Build package layout per §5.9. | `tests/test_exports.py` lists the files for campus-demo. | W2 |
| FR-EXP-02 | P0 | v0.2 artifacts keep their names and semantics: `index.html`, `diagram.svg`, `patch-sheet.csv` (v1 columns), `project.json` (now v2), `build-notes.txt`, `<run>.zip`, optional `report.pdf`, `diagram.png`. | `fathom selftest` v0.2 checks pass. | W2 |
| FR-EXP-03 | P0 | Options: `state` (`as_built`, `planned`, `all`), `rooms` (subset), `pdf`, `png`. | API test with `rooms: ["main"]` builds only that room folder. | W2, W1 |
| FR-EXP-04 | P0 | Device pages use relative links; QR codes encode `<public_url>/p/<project>/d/<device>` where public_url = `settings.public_url` or `FATHOM_PUBLIC_URL` or (server builds) the request's scheme+host+script root; none → no QR, with a build note. | Test both branches. | W2 |
| FR-EXP-05 | P1 | `report.html` (print-oriented: maps, patch tables, schedules, and a *Console channels* section — `render_html.render_console_report_section`, one `<article class="console-report" id="console-<device>">` per console with channels, the same Inputs / Buses / DCAs & mute groups / Racks tables as its device page, no trace buttons — alongside `console-channels.csv`) and `report.pdf` from it when Chrome is present. | With Chrome, `report.pdf` > 10 KB; `test_console_channels.py::Overlay::test_build_report_tables_and_csv`. | W2, W5 |

### 3.24 FR-QR — QR codes

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-QR-01 | P0 | Stdlib encoder `fathom/qr.py`: byte mode (UTF-8), EC L/M/Q/H, versions 1–40, smallest fitting version by default, mask chosen by ISO/IEC 18004 penalties (N1=3, N2=3, N3=40, N4=10) or forced; SVG with 4-module quiet zone. | Appendix C vectors match bit-for-bit with `mask=2, ecl="M"`; Reed–Solomon self-check (all syndromes zero) on 200 random payloads. | W2 |
| FR-QR-02 | P0 | `GET /api/v2/projects/<n>/qr/<device>.svg`; QR in inspector, device pages, builds (`qr/<device>.svg`); label sheet QR P1. | SVG parses as XML; module count = 17 + 4·version. | W2, W1, W5 |
| FR-QR-03 | P1 | **Device labels at true size for the Brady M511** (300 dpi thermal-transfer; prints from Brady Express Labels / Brady Workstation, not a browser). `fathom/labels.py` (stdlib, pure): `PRESETS` in this order — `m511-1x0.5` 25.4×12.7 mm (M4-47-422 / M4-47-483 / M5-17-351, **default**), `m511-1x1` 25.4×25.4 (M4-49-422 / M4-49-498), `m511-1x2` 25.4×50.8 (M4-60-483 / M4-60-428 / M5-20-351), `m511-0.5x1` 12.7×25.4 (M4-131-499), `m511-1.9x1` 48.26×25.4 (M5-78-492), `m511-cont-1.5` continuous 38.1 mm tape, label 50.8 long (M5C-1500-*), `m511-cont-1` continuous 25.4 mm tape, label 38.1 long (M5C-1000-*); each `{id, label, width_mm, height_mm, parts, continuous}`. `device_label_svg(doc, device, preset, base_url)`: root `width="<w>mm" height="<h>mm" viewBox="0 0 <w·300/25.4> <h·300/25.4>"` (300 dpi units, rounded); QR (`qr.encode`, EC M, one quiet module) on the left sized to the height minus 1.5 mm margins when the label is wide (`1x0.5`, `1.9x1`), on top with the text below otherwise (`0.5x1`, `1x1`, `1x2`, continuous); big line = the dashed short code (`schema.format_short_code`) in `ui-monospace, Menlo, monospace` sized to fit (≈ 0.6 em per character), else the device id; then the name (`system-ui, sans-serif`, truncated with `…`), then `room · location` smallest; black on white, no external fonts, text XML-escaped. The QR encodes `<base>/c/<code>` when the device has a short code (and this build formats them), else `<base>/p/<project>/d/<id>`. | `test_labels.py`: seven presets in order, root attributes per preset (`m511-1x0.5` → `viewBox 0 0 300 150`), QR inside the label, `&`/`<` escaped, URL branches. | P1B |
| FR-QR-04 | P1 | Delivery: `label_sheet_html` — self-contained printable page (`@page { margin: 10mm }`, header *Print at 100 % — <preset label> (<w>×<h> mm)*, each label an inline SVG at true size in `div.label[data-device][data-url]` with a hairline border and `break-inside: avoid`; satisfies the file CSP: inline styles only, no scripts or external resources); `labels_csv` — RFC 4180 (CRLF) `device_id,short_code,name,room,location,url,kind,manufacturer,model` for Brady Workstation data import; `labels_zip` — `README.txt` (preset, size, parts, "import SVG/PNG into Brady Express Labels or Brady Workstation; print at 100 %"), `labels.csv`, `<device_id>.svg` per device and `<device_id>.png` (300 dpi) per device when `export.find_chrome()` finds a headless Chrome (skipped silently otherwise); `select_devices(doc, ids, room, state)` — explicit ids in the given order, else a room, else every non-`auto` device sorted by room name then device name, filtered by `status` when `state` is given. Routes §5.8 (`GET /api/v2/labels/presets`, `GET /api/v2/projects/<n>/labels/devices`); every build writes `device-labels.html` (§5.9, default preset, all devices in scope). | Routes: presets, html, csv, zip, svg (400 unless exactly one id), 400 `bad_preset`, viewer allowed; `test_exports.py` build file list. | P1B |
| FR-QR-05 | P1 | Schedules › Labels: section **Device labels** under the cable-label controls (§6.7) — preset select, scope (all devices / this room / selected devices with a filterable picker), **Preview** (new tab), **Download ZIP**, **Download CSV** as plain links to the §5.8 route; stacks at < 700 px with full-width buttons and 40 / 44 px targets. | `test_ui_sch.py::test_device_labels_section`. | P1B |

### 3.25 FR-IMP — Importers

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-IMP-01 | P0 | Yamaha/Dante/Waves importers keep behavior, are registered in the registry, and are lifted into the overlay (devices, detail, routes, port labels, interfaces). | RRC overlay has > 200 `dante` routes. | W2 |
| FR-IMP-02 | P0 | Dante Device Info table paste: `Primary Address` / `Secondary Address` columns → overlay interfaces (role primary/secondary, protocol dante). | Sample paste in `fathom/samples/campus-demo/exports/dante/device-info.txt`. | W2 |
| FR-IMP-03 | P0 | ETC Eos CSV export: blocks `START_<NAME>` … `END_<NAME>` with a title row; patch from `CHANNELS` (alias `PATCH`) block columns `CHANNEL, FIXTURE_TYPE, ADDRESS, LABEL` (+ `PROPORTION, CURVE` ignored); `FIXTURES` block gives footprint = max(`PARAMETER_ADDRESS_OFFSET`)+1 per `FIXTURE_TYPE_NAME`; ADDRESS accepts absolute (`1025`), `u/a` and `u.a`. | Sample yields fixtures with universe/address/footprint. | W2 |
| FR-IMP-04 | P0 | USITT ASCII 3.0 (`.asc`): records are lines; delimiters tab, space, `, / ; < = > @`; keyword match on first 10 chars, case-insensitive; `PATCH page chan dim level …` triplets; channel 0 = unpatched; dimmer = absolute DMX address; `ENDDATA` stops; `$`/`$$` records and `!` comments ignored. | Sample with `Patch 1 5<8@100 2<9@100` yields channel 5 → 1/8, channel 2 → 1/9. | W2 |
| FR-IMP-05 | P0 | Lightwright/Vectorworks instrument-schedule text (tab or comma, header row, any order, case-insensitive): Channel, Dimmer | Address | Absolute Address | DMX, Universe, U Address, Universe Address (`u/a`), Instrument Type | Fixture Type | Type, Position, Unit | Unit Number, Purpose, Color, Mode, Footprint, Label. | Sample yields position/unit/purpose. | W2 |
| FR-IMP-06 | P0 | Lighting contribution: match existing devices by `dmx.channel` = Channel, then by name = Label; unmatched → auto fixture devices (kind `fixture`, room = import room, `auto: true`, `source: "eos"`) in the overlay only; "Promote" persists via ops. | Overlay device count equals unmatched fixtures. | W2 |
| FR-IMP-07 | P0 | Blackmagic Videohub protocol dump (text as received on TCP 9990): blocks `HEADER:` … blank line; parse `VIDEOHUB DEVICE:` (`Model name`, `Friendly name`, `Video inputs`, `Video outputs`), `INPUT LABELS:`, `OUTPUT LABELS:`, `VIDEO OUTPUT ROUTING:`; ignore unknown blocks/lines; zero-based numbers → ports `sdi-in-<n+1>` / `sdi-out-<n+1>`; labels → overlay port labels; routing `o i` → overlay route `sdi-in-<i+1> → sdi-out-<o+1>`; target device = import `device`, else match by friendly name, else auto device from the Videohub template. | Sample (20×20) yields 40 labels and 20 routes. | W2 |
| FR-IMP-08 | P0 | Generic CSV one-shot importer (devices or cables, detected by headers §5.7.4): `POST …/imports/preview` returns ops + warnings, never writes; the client commits. | Preview of the campus-demo `devices.csv` yields `put` ops for new devices and `merge` ops for existing ids. | W2, W1 |
| FR-IMP-09 | P2 | ATEM Software Control settings XML: `<Input id shortName longName externalPortType>` → overlay port labels on the ATEM device (inputs by index). | Sample XML yields labels. | W2 |
| FR-IMP-11 | P1 | ChamSys MagicQ head-list CSV (Patch → View Heads → Print Window → Create CSV, or the legacy EXPORT HEADS file `Headno, Headname, Dmxno, Headtype, Gel, Pinv, Tinv, Swap`): headings matched with MagicQ's own IMPORT HEADS synonyms, case-insensitive; delimiter = first `,` / `;` / tab; DMX `u-aaa`, `u/a`, `u.a`, absolute, or in-universe with a `Universe` column; `virtual`/blank = unpatched (noted, skipped); `Headtype` `Manufacturer_Model` split unless a Manufacturer column exists; overlaps and runs past 512 noted. Contribution as FR-IMP-06 with `source: "magicq"`, ids `mq-<head>`, and name matching only for head names that are unique in the file. A `.shw` show file (undocumented format) is refused with 422 and export instructions. | Samples yield heads with universe/address/footprint/mode. | — |
| FR-IMP-12 | P1 | Generic CSV templates and validation: importers may declare `templates` (+ `template(name, doc)`); `GET …/imports/templates/<kind>/<name>.csv` returns an example file (UTF-8 BOM, examples use the project's default room) that previews without errors; every row is validated and rows with problems are skipped and returned as `errors: [{row, column, value, message}]` (spreadsheet row numbers, the user's header text) and mirrored into `warnings`. | Template download → edit → preview → apply round-trip. | — |
| FR-IMP-10 | P0 | Imports view: upload cards generated from registry metadata (label, help, accepts, folder), registered imports with Inspect/Remove, overlay summary with "Promote" for auto devices. | Manual QA. | W5 |

### 3.25a FR-DISC — Network discovery (on demand; passive by default, opt-in read-only active probes)

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-DISC-01 | P0 | A discovery **run** is started only by an explicit `POST …/discovery/runs` (editor). No scheduler, no always-on listener, no periodic polling anywhere; a run lasts `window` s (10–300, default 60) plus parsing and is killed by a hard time limit. One run per project at a time (409 `run_active`). Runs execute in-process (`jobs.py` thread pool) with live `status`, `progress`, `stage` and a bounded log; `DELETE` cancels and keeps partial results. | Tests: 409 on second start; cancel ends the run; time limit. | — |
| FR-DISC-02 | P0 | Probes are **passive**: UniFi (read-only HTTPS to the configured controller only), mDNS/DNS-SD (standard multicast queries; never a unicast packet to a Dante endpoint), LLDP/CDP (raw-socket listener; sends nothing), ARP (reads the host neighbour cache). Nothing writes to any device. Each probe declares `mode` (`passive` or `active`, FR-DISC-10), `maturity` (`experimental` / `tested` / `mature`), `default_enabled` and a `sends` note. Probes replay recorded payloads when `FATHOM_DISCOVERY_FIXTURES` is set. | Guard test: with sockets patched, a fixture-free run opens no outbound connection except to the configured UniFi host and mDNS multicast. | — |
| FR-DISC-03 | P0 | Correlation: observations merge into one entity by MAC, same-run IP, hostname / Dante name (normalised, generic names excluded) and serial; each entity lists sources, services, uplinks and evidence. Entity confidence: MAC 0.50 (else 0.25) + 0.20 for ≥ 2 sources + 0.15 named + 0.10 manufacturer/model + 0.05 serial; `high` ≥ 0.8, `medium` ≥ 0.5. Entities are matched against document devices using the signals of `dedupe.score_pair` (the entity rendered as a device; exact MAC / serial / IP / name / alias / Dante name / hostname and the differing-serial penalty, no fuzzy name similarity) with discovery's weights (MAC or serial 0.60, IP 0.30, name family 0.35 once, model 0.10 only with another hit, ×0.2 when both serials are known and differ): ≥ 0.60 `match`, ≥ 0.35 `possible`, else `new`; no MAC and no name → `unresolved`. | Tests from fixtures. | — |
| FR-DISC-04 | P0 | Topology: switch port tables (UniFi, SNMP MAC table) and LLDP/CDP neighbours (sniffed, UniFi, SNMP LLDP-MIB) become connections. LLDP/CDP/UniFi-LLDP/SNMP-LLDP 0.90, UniFi uplink/client table 0.85, LLDP + client agree 0.95, a single MAC learned on a port 0.60; a switch-to-switch link reported by both switches (consistent ports) is folded into one `uplink` row with the union of methods plus `mirrored`, confidence 0.95 and the peer port filled in; a port with several MACs is flagged `uplink` when one peer is infrastructure (switch/AP/gateway) else `unmanaged` (−0.2); peers behind an uplink are `via` rows. Connections with confidence ≥ 0.5 and both ends on known or proposed devices carry a proposed cable (`medium` dante/network by role, `type` cat6, `status` planned); existing cables between the same ports mark the row `exists`. Discovered VLANs/subnets become network findings, matched to document networks by VLAN then subnet. | Tests from fixtures. | — |
| FR-DISC-05 | P0 | Findings are promoted by hand (`POST …/findings/promote`): new entities → `put devices` (tags `discovered`, interfaces with `source: "discovery"`, `last_seen`), *merge into* → `merge` on the chosen device (interfaces added or refreshed, blanks filled, nothing overwritten), connections → `put cables`, networks → `put networks`; ignore decisions persist in `exports/discovery/decisions.json`. Re-running after promotion must produce no duplicates (promoted entities re-correlate as `match`, cables as `exists`). | End-to-end test. | — |
| FR-DISC-06 | P0 | The latest run is registered as an import of kind `discovery` (folder `exports/discovery/<run>`), so new entities with confidence ≥ 0.5, interfaces for matched devices and proposed links (routes kind `network`) appear in the overlay like any import. | Overlay test. | — |
| FR-DISC-07 | P0 | Settings per project under `settings.discovery` (`window`, `probes.<id>.{enabled, fields…}`). Secret fields (UniFi API key / password, SNMP community and v3 keys, QRC password) are written to `projects/<n>/discovery-secrets.json` (mode 0600), never to `project.json`, history or API responses (`<key>_set` flags only); run logs and error messages are redacted. `FATHOM_UNIFI_*`, `FATHOM_SNMP_*`, `FATHOM_YAMAHA_HOSTS`, `FATHOM_VIDEOHUB_HOSTS`, `FATHOM_QSYS_*` / `FATHOM_DISCOVERY_INTERFACE*` are server-wide fallbacks (an environment value never enables an active probe). Field types: `text`, `check`, `secret`, `select` (value must be one of `options`), `list` (hosts; comma / newline separated text or a JSON list, stored comma-joined, deduplicated). `POST …/discovery/test` checks one probe's settings (unsaved values allowed) without starting a run. | Tests. | — |
| FR-DISC-08 | P0 | Discovery view: Sources (mode, maturity, settings, Test, last run; active cards carry an *Off by default* chip while disabled and a one-line *What this sends to the device* note), Run (window, Run / Cancel, 1 s polling of progress and log, previous runs, an explicit note that nothing runs unless started here), Findings tabs *New devices / Matches existing / Connections / Networks & VLANs / Unresolved / Changes* (FR-DISC-11) with sources, confidence, evidence, Promote / Merge into / Ignore and bulk select; connections in cable-schedule columns. Inspector shows a *discovered* badge on discovery interfaces. Install hint when the `discovery` extra is missing. Responsive. | Smoke test; manual QA. | — |
| FR-DISC-09 | P1 | Deployment on a plain Ubuntu VM (ESXi): `deploy/fathom.service` runs gunicorn as the non-root `fathom` user with `AmbientCapabilities=CAP_NET_RAW CAP_NET_BIND_SERVICE` (and a matching `CapabilityBoundingSet`) so the LLDP listener and mDNS work without root; `setcap` on the venv's python is the documented alternative. `fathom discovery doctor [--seconds N] [--interface IF] [--json]` reports, without sending anything to a device: `CAP_NET_RAW` / `CAP_NET_BIND_SERVICE` and whether a packet socket opens, interfaces with MAC, addresses, 802.1Q VLAN id, link and promiscuous flag, and (default 35 s) whether LLDP / CDP frames from *other* hosts were heard — the test for ESXi *Promiscuous Mode = Accept*; exit 1 with advice when something is missing. | `tests/test_discovery.py::Doctor`. | — |
| FR-DISC-10 | P1 | **Active probes** are opt-in, read-only and host-scoped: SNMP (`snmp`, v2c / v3; `SNMPv2-MIB` system, `IF-MIB`, `BRIDGE-MIB` / `Q-BRIDGE-MIB` learned MACs per port and VLAN, `LLDP-MIB` neighbours, `ENTITY-MIB` chassis manufacturer / model / serial / firmware, VLAN names; GET / GETBULK of 10 OIDs, 20 ms apart, 5 s timeout, 2 retries, one switch at a time, 120 s per switch, never a SET), Yamaha SCP (`yamaha`, TCP 49280: `devinfo`, `sscurrent_ex`, `get … Label/Name`; ≤ 276 reads), Blackmagic Videohub (`videohub`, TCP 9990: reads the preamble the router sends on connect, writes nothing) and Q-SYS QRC (`qsys`, TCP 1710: `StatusGet`, `Component.GetComponents`, `Logon` only with credentials). Each declares `mode: active`, a maturity label, `default_enabled: false`, a `sends` note and `targets: "hosts"`; a probe without hosts is left out of the run (400 when nothing remains); runs record `mode` (`active` when any active probe took part) and `targets` (probe → hosts) and log that only those hosts are queried. Console connections pause 50 ms between commands, time out per read and have a 20 s budget per host; parse failures are per host. | Fixture tests (SNMP walk dumps, SCP / Videohub / QRC captures); guard test: with sockets patched, each active probe connects only to the listed hosts and, with no hosts, opens nothing; API test: targets, mode, SNMP-derived and mirrored connections. | — |
| FR-DISC-11 | P1 | **Run-to-run diff.** When a run finishes and an earlier completed run exists, the server computes a diff against the previous completed run (by id order) and stores it as `exports/discovery/<rid>/diff.json`; the run brief carries `diff: {against, counts}`. `GET …/discovery/runs/<rid>/diff[?against=<rid>]` recomputes it on request against any other completed run (default: the previous one), with both sides correlated against the *live* document so a promotion in between is not a change. Entities are paired by MAC (identity; several current hosts may share one previous host and vice versa), then serial, then Dante name / hostname / name (normalised, generic names excluded), then IP for MAC-less hosts only. Reported: `new_devices`, `missing_devices`, `moved` (same box, different switch / port; a controller's "behind port N" view and a switch's own port view of the same link are not a move), `changed` (IP, VLAN, hostname by first label, Dante name, name; blanks are not changes), `new_links`, `lost_links` (keyed by switch, canonical port and peer; `via` rows and ignored rows excluded), plus `counts`. No scheduler: "repeat runs" are runs a person starts later. The Discovery view shows a *Changes* tab with a prior-run picker. | `tests/test_discovery.py::RunDiff`, `::RunDiffApi`. | — |
| FR-DISC-12 | P1 | **Discovered connections in the report.** The build writes a *Discovered connections* section (and `discovered-connections.csv`) right after the cable schedule: the cable-schedule columns plus `Signal`, `Status`, `Confidence` (`level (nn%)`), `Sources` (probe methods), `Run`, `Note`. Rows come from cables promoted out of a run (marked `source: "discovery"` with a `discovery: {run, confidence, level, methods}` block; they follow the build's `state` and `rooms` like the cable schedule) and from the latest completed run's connections not yet promoted (`proposed`, `documented` when a hand-drawn cable matches, `observed` when not promotable; `via` and ignored rows excluded; room-scoped by either end). `BuildOptions.discovery` (default `true`; `fathom build --no-discovery`) leaves the section and CSV out; with no run and no promoted cable the section is omitted and a build note says so. | `tests/test_discovery.py::DiscoveredConnectionsReport`. | — |
| FR-DISC-13 | P2 | **Dante Domain Manager** (`ddm`, active, *experimental*, `targets: "url"`): one HTTPS POST of a read-only GraphQL `query` (domains → devices → identity, interfaces, rx / tx channels with subscriptions) to `<url>/graphql` with the API key as a bearer token; no `mutation`, nothing sent to Dante devices. Yields Dante name, MACs, addresses, manufacturer / product / version and the subscriptions as evidence (the preset-XML import remains the route to full Dante routing; the UI says so). Without a URL or key nothing leaves the host. Vendors without a documented read API (ATEM beyond the existing import, Allen & Heath, DiGiCo, Avid) stay mDNS / OUI identified. | `tests/test_discovery.py::DdmProbe` (fixture, correlation, opt-in run, guard). | — |

### 3.26 FR-SEC — Security

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-SEC-01 | P0 | Path traversal: every file route resolves the target and checks containment (`target.resolve().is_relative_to(root.resolve())`); names/ids validated by regex (§4.2) before touching disk. | `..`, `%2e%2e`, absolute paths, NUL bytes → 400/404. | W1 |
| FR-SEC-02 | P0 | Body caps: `FATHOM_MAX_UPLOAD_MB` (default 50) for multipart; `FATHOM_MAX_JSON_MB` (default 20) for JSON; both checked from `Content-Length` before reading; chunked bodies read with the same cap. | Oversize → 413. | W1 |
| FR-SEC-03 | P0 | CSRF: mutating requests must be non-simple (JSON content type, or PUT/PATCH/DELETE) or carry `X-Fathom: 1`; multipart/urlencoded/text POSTs without it → 403; if a cookie session authenticates and `Origin` is present it must equal the request origin. `api.js` always sends `X-Fathom: 1`. | Tests. | W1, W5 |
| FR-SEC-04 | P0 | Headers on all responses: `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: SAMEORIGIN`; CSP for app pages `default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'`; viewer pages same with `script-src 'self' 'unsafe-inline'`; user files `default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox`. | Header test per route class. | W1 |
| FR-SEC-05 | P0 | User files: images served inline with the right type; everything else `Content-Disposition: attachment`; SVG only after sanitization. | Test. | W1, W2 |
| FR-SEC-06 | P0 | `<data>/secret.key` (32 random bytes hex, mode 0600) created on first need; secrets/API keys never logged or returned. | `/api/v2/meta` and OpenAPI contain no key material. | W1 |
| FR-SEC-07 | P0 | Per-project write lock (`fcntl.flock` on `projects/<n>/.lock`; Windows `msvcrt.locking`; fallback `O_CREAT|O_EXCL` lockfile with 10 s stale timeout) around read-check-write; atomic replace (`tmp` + `os.replace`). | 10 threads × 10 changes → revisions 2…101, no lost update. | W1 |
| FR-SEC-08 | P0 | 500 responses are `{"error": "internal error", "id": "<8 hex>"}`; the traceback (with id) goes to stderr only. | Test with a handler forced to raise. | W1 |

### 3.27 FR-A11Y — Accessibility

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-A11Y-01 | P0 | Everything keyboard-reachable with visible focus; dialogs trap focus, Esc closes, focus returns to the opener. | QA keyboard pass. | W3, W4, W5 |
| FR-A11Y-02 | P0 | ARIA: canvases `role="application"` + `aria-label`; cards `role="group"` + `aria-label="<name>, <model>, <n> ports"`; one shared `aria-live="polite"` region (`#fathom-live`) announces commits (e.g. "Connected Stage Box 1 Output 1 to Audio Rack 1 Input 1"); tables use `<th scope>`. | VoiceOver spot check. | W3, W4, W5 |
| FR-A11Y-03 | P0 | Contrast ≥ 4.5:1 body text, ≥ 3:1 large text/icons; color never the only cue (media differ by dash, pills carry text). | QA spot check. | W3, W4, W5 |
| FR-A11Y-04 | P0 | `prefers-reduced-motion: reduce` disables transitions/animations. | QA. | W3, W4, W5 |

### 3.28 FR-UX — App shell

| ID | Pri | Requirement | Acceptance criterion | Owner |
| --- | --- | --- | --- | --- |
| FR-UX-01 | P0 | Top bar: brand, project picker, room picker, view tabs, search, assistant, save state (`Saved · r17`, `Saving…`, `3 pending`, `Offline · 3 pending`, `Conflict`), user menu; ⌘/Ctrl+S flushes immediately. | QA. | W5 |
| FR-UX-02 | P0 | Hash routing `#/<project>/<room>/<view>[/<seg4>[/<seg5>[/<seg6>]]][?<query>]` (§6.4 Router); `sel=<type>:<id>[:<port>]` selects. Legacy `/?p=<project>` (no hash) is replaced by `#/<project>//home`, keeping the other search params; an empty view canonicalizes to `home` and keeps the query. | A deep link selects the device; `test_ui_shell.py::test_legacy_project_url_lands_on_home`. | W5, ROUTER, SHELL |
| FR-UX-03 | P0 | Views load via dynamic `import()`; a failing module shows an inline error card with the message; the rest of the app keeps working. | Smoke test with a deliberately missing module path. | W5 |
| FR-UX-04 | P0 | Inspector for device, port, cable, rack, floor plan, marker covering every editable field of §4.3; text edits debounce 400 ms into one op. | QA. | W5 |
| FR-UX-05 | P0 | Autosave default on (`settings.autosave`); off → ops queue until Save. | QA. | W5 |
| FR-UX-06 | P0 | New project dialog (blank + samples), project settings (meta, units, tag pattern, public URL, currency), JSON view (raw doc; Apply = PUT with If-Match). | QA. | W5 |
| FR-UX-07 | P0 | Admin views: Imports, History, Builds, Settings (venues/rooms/systems/locations/networks, users for admins, share links P1). | QA. | W5 |
| FR-UX-08 | P0 | Dark theme on the existing palette (`--bg #0b1020`, `--panel #111828`, `--border rgba(255,255,255,.09)`, `--text #e6eaf4`, `--muted #8e97ab`, `--accent #8ea2ff`, `--ok #2fd4b4`, `--warn #ff9548`, `--err #f06aa8`); fonts = system stack; no web fonts. | QA. | W3, W4, W5 |
| FR-UX-09 | P0 | Sections and nav memory: the shell groups views into `router-core.SECTIONS` (Home, Patch, Rooms, Devices, Schedules, SOPs, Data, Settings; filtered by `sectionsFor(role)`). md/lg: `#app-views` holds one `button.app-sec[data-section]` per section with a `ul.app-sec-menu` of its views (ArrowDown, context menu or 500 ms long-press); `#app-subnav` shows `a.app-subtab[data-view]` when the section has ≥ 2 views. sm: `#app-tabbar`. Clicking another section returns to its last route this session (`navMemory`, sessionStorage `fathom.ui.nav`, room rewritten to the current room); clicking the active section goes to its root view. | `test_ui_shell.py::test_sections_and_tab_bar`, `::test_nav_memory`, `::test_section_menu_lists_views`. | ROUTER, SHELL |
| FR-UX-10 | P0 | Entity pages with URL tabs: `devices/<id>/<tab>[/<sub>]`, `rooms/<id>/<tab>`, `racks/<id>/<tab>[/<sub>]` (tabs §6.13.3). Each page = explorer (§6.13.2) + sticky entity header (compact after scroll and at sm) + tab body. Without an id, `devices` and `rooms` are landing pages listing the entities in a DataTable, and `racks` is the rack elevation canvas (`rack.js`, which mounts `page-rack.js` when the route has an id; the elevation tab's `<sub>` is `front` or `rear`). A missing or unknown tab resolves to `overview` with a history *replace*; a tab click *pushes* (Back returns); an unknown id shows an inline error with a back link. | `test_ui_entity.py`, `test_ui_pdev.py`, `test_ui_proom.py`, `test_ui_rk.py`. | ENTITY, PDEV, PROOM, RK |
| FR-UX-11 | P0 | Every list of records renders through the shared DataTable (§6.13.4; exemptions §6.13.4): search, sort, per-column filters, pagination, column chooser, density, CSV of the filtered rows, select-all of the filtered set, sticky header with `th[scope]`, mobile columns hidden at sm. Table state is in the URL (`q`, `sort`, `f.<col>`, `pg`; history *replace*); sort, filters, page size, hidden columns and density also persist in `fathom.ui.table.<scope>.<key>` (§6.14); search text and page are URL-only. | `test_ui_datatable.py`; `tests/js/datatable-core.test.mjs`. | TABLE |
| FR-UX-12 | P0 | Drawer URL state (§6.13.5): `sel` names the subject, `sec` the inspector section, `drawer=0` keeps the selection with the drawer closed (`#app-selbar` shows it). Opening from closed *pushes* when there is explicit intent or below lg, so Back closes it; switching subject or section *replaces*. A canvas selection (patch, plan, map, rack elevation) below lg leaves the drawer closed. Modes docked/sheet/full by width; Esc closes the top layer (palette, dialog, trace, assistant, explorer, drawer); reload restores the drawer and section. | `test_ui_drawer.py`, `test_ui_ins.py`, `test_ui_shell.py::test_deep_link_opens_drawer`, `::test_drawer_closed_shows_selection_bar`, `::test_canvas_selection_below_lg_keeps_drawer_closed`. | DRAWER, INS, SHELL |
| FR-UX-13 | P0 | Home launchpad (`DEFAULT_VIEW = 'home'`, §6.13.7): project title and counts, one card per permitted section, room cards, a recents strip (`fathom.ui.recent.<project>`: devices, rooms, racks, pages; 8 each) and project cards; every card is a real `<a href>`. An empty project shows a start card. | `test_ui_home.py`; `tests/js/home-core.test.mjs`. | HOME |
| FR-UX-14 | P0 | Feedback states (§6.13.8): every view shows a skeleton while loading, an empty state with a next action, an inline error with Retry (never a blank pane or only a toast), a scoped confirm for destructive or bulk changes (verb, count, noun, room), a stale badge on overlay data, review badges, and bell notices (`#app-notify`) for offline edits, overlay refresh failures and finished builds. Viewers get the states without write actions. | `test_ui_feedback.py`, `test_ui_states_shell.py`, `test_ui_states_entity.py`, `test_ui_states_lists.py`, `test_ui_states_canvas.py`, `test_ui_states_admin.py`. | FEEDBACK, ST-* |
| FR-UX-15 | P1 | Light theme: `html[data-theme]` is `dark` (default), `light` or `system` (`system` follows `prefers-color-scheme`). The light palette only swaps the base variables (`--bg #f6f7fb`, `--panel #fff`, `--panel-2 #eef1f7`, `--text #111827`, `--muted #5b6475`, borders `rgba(15,23,42,.10/.18)`); accent and discipline colours do not change. `app.js` applies the stored choice (`fathom.ui.theme`, §6.14) before the first paint and keeps `<meta name="theme-color">` in step (`#0b1020` / `#f6f7fb`). The user menu item *Theme: Dark ▸ Light* cycles dark → light → system; `?theme=<t>` (search or hash query) overrides for that load without persisting. | `test_ui_shell.py::test_theme_cycles_and_persists`, `::test_theme_query_override_renders_light_without_hscroll`. | SHELL |
| FR-UX-16 | P1 | First-run tour (`js/tour.js`, `css/tour.css`; §6.4): after the first project load, when `fathom.ui.tour` is unset, the shell runs a five-step spotlight tour (project and room pickers, section nav `#app-views` / `#app-tabbar`, search, Helper, save state and user menu) and then stores `{done: true, at, reason}` whatever the exit (Done, Skip tour, Esc, ×). Steps whose targets are not rendered are skipped; the card docks as a bottom sheet below 700 px; Esc closes, Tab is trapped, Back/Next/Done and ← → move, focus returns to the opener. *Take the tour* in the user menu and in the shortcuts dialog footer re-runs it; `?tour=1` forces a run and `?tour=0` (or `?smoke=1`) suppresses the automatic one. | `test_ui_tour.py`. | SHELL, TOUR |
| FR-UX-17 | P1 | Editing lock: when `doc.settings.locked === true` (`model-core.isLocked`), `#app-lock` (`role=status`, under the top bar) says *Editing is locked by <locked_by> · <relative time>* with an *Unlock* button for editors and admins; the store goes read-only, `ctx.role` reads `viewer` for every view except `settings`, `#app-save` shows *Locked · r<rev>*, and *Lock editing* in the user menu (editors and admins, unlocked projects) locks it. Lock and unlock are a single `{op: 'root', key: 'settings', value: {locked}}` through the change queue. A `/changes` flush that fails with `isLockedError` (HTTP 423 or `code: 'locked'`) drops every queued op, toasts *Someone locked editing — your last change was not saved* and reloads the doc. | `test_ui_shell.py::test_locked_project_shows_banner_and_viewer_mode`, `::test_locked_change_flush_drops_ops_and_reloads`; `api.test.mjs`, `model-core.test.mjs`. | SHELL, API |
| FR-UX-18 | P1 | *Suggest an improvement…* (every role; `js/improve-ui.js`): a dialog with a required description (`#imv-text`, ≤ 2000 chars with a counter), an optional name (`#imv-name`, prefilled with the session user) and a read-only *About: <project> · <view> · <room>* line; Send calls `api.reportSuggestion(project, {text, name, kind: 'suggestion', url})` (`POST /api/v2/projects/<n>/problems`) and toasts *Thanks — your suggestion was saved* (plus *and forwarded* when the response has `forwarded: true`); failures toast the error. Usable at 390 px. | `test_ui_shell.py::test_suggest_improvement_dialog_posts`; `api.test.mjs`. | SHELL, API |

---

## 4. Data model v2

### 4.1 Principles

- A project is one folder; its model is one JSON file `project.json` holding a **doc**: a JSON object with root objects (`meta`, `settings`, `media`) and **collections** (arrays of entities with unique `id`).
- Python passes docs as plain `dict` (no dataclasses for v2). JS passes plain objects. The v1 dataclasses (`fathom.model.Project` etc.) remain and are produced from a doc by the **flow adapter** `schema.flow_project(doc, room_id)` for the signal-flow map.
- Collections (exact names, in this order when serialized): `venues, rooms, systems, locations, racks, networks, devices, cables, bundles, floorplans, attachments, templates, imports, pages`. `pages` (§4.3.15) is optional on disk; `normalize` adds it.
- Optional fields are **omitted** when empty/default (like v1 `to_dict`), except where a table says "always written". Readers MUST tolerate missing optional fields and unknown extra fields (unknown fields are preserved on round-trip).
- Units: lengths in meters (`length_m`), distances on plans in meters internally; `settings.units` only affects display.
- Computed data (imports overlay, validation problems, search index, trace graphs) is **never persisted** in `project.json`. Entities marked `"auto": true` are overlay-only and MUST be stripped by `schema.normalize` before saving.

### 4.2 Identifiers & references

| Thing | Format | Notes |
| --- | --- | --- |
| Entity id (all collections) | `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` | No `:`, `/` or spaces. Case-sensitive. Unique within its collection. |
| Port id | same regex, unique within its device | |
| Generated ids | devices `slug(name)` (dedupe `-2`, `-3`…), cables `c-` + 4 digits (migration) or `c-` + 8 random `[a-z0-9]` (client/server new), bundles `b-` + 4 digits / 8 random, rooms/venues/systems/locations `slug(name)`, racks `rk-` + slug, floor plans `fp-` + slug, attachments `att-` + 12 hex, imports `imp-` + 4 digits, shares `sh-` + 22 base64url | `slug()` = existing `fathom.model.slug` (lowercase, runs of non `[a-z0-9]` → `-`, trimmed, default `item`). JS `model-core.slug` MUST produce identical output for ASCII input. |
| Entity ref (history, conflicts, highlights) | `<collection>/<id>` e.g. `devices/rio3224`; root objects `meta`, `settings`, `media` | |
| Port ref (query strings, CLI) | `<device_id>:<port_id>`; device-level `<device_id>` | |
| Project name | existing `SAFE_NAME_RE` `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` | unchanged |
| Build run name / file names | existing `_RUN_RE` per path segment | builds now have sub-folders (§5.9) |

### 4.3 Entity reference

Types: `str`, `int`, `num` (float), `bool`, `obj`, `[T]` array of T. "Req" = required on save. Defaults apply on read when omitted.

#### 4.3.1 Root

| Field | Type | Req | Default | Notes |
| --- | --- | --- | --- | --- |
| `fathom` | int | yes | — | Always `2` (always written first). |
| `revision` | int | yes | 0 | Managed by the server/storage; client values are ignored on write. |
| `meta` | obj | yes | — | §4.3.2 |
| `settings` | obj | yes | — | §4.3.3 |
| `media` | obj | no | `{}` | Per-project overrides of MEDIA entries by key, e.g. `{"analog": {"label": "Analog · XLR/TRS"}}` (v1 `media`). |
| collections | `[…]` | yes | `[]` | Always written (possibly empty) in the order of §4.1. |

#### 4.3.2 `meta` (v1 fields, unchanged)

`org` (str), `system` (str, default "Audio system"), `title` (str, default "Signal flow, mic to speaker"), `intro` (str, default v1 intro), `footnote` (str, default v1 footnote), `slug` (str), `version` (str), `author` (str), `description` (str, new, optional).

#### 4.3.3 `settings`

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `default_room` | str | first room id | Room used by `/p/<n>`, v1 endpoints and `load_project`. |
| `units` | `"metric"`\|`"imperial"` | `"metric"` | Display of lengths and plan distances. |
| `cable_tag_pattern` | str | `"{D}-{n:03}"` | §4.8 |
| `currency` | str | `"USD"` | ISO 4217 code for BOM/inventory. |
| `public_url` | str | `""` | Base URL used in QR codes, e.g. `https://av.example.org`. No trailing slash. |
| `problem_email` | str | `""` | Address offered as the e-mail fallback of "Report a problem" (§5.16) on SOP pages and the only channel in the offline bundle. Empty → no e-mail option. |
| `autosave` | bool | `true` | |
| `labels` | obj | `{"cols":3,"rows":10,"width_in":2.625,"height_in":1.0,"page":"letter"}` | Label sheet grid. |
| `assistant` | obj | `{"llm": true}` | `llm:false` disables the LLM bridge for this project even if configured. |
| `locked` | bool | absent (`false`) | Editing lock (FR-USER-12): while `true`, `/changes` and `PUT` answer 423 unless they only change `locked*`. Error `bad_type` when not a bool. |
| `locked_by`, `locked_at` | str | absent | Stamped by the server when `locked` flips to `true` (login or `local`, UTC `YYYY-MM-DDTHH:MM:SSZ`); removed when it flips back. Values clients send are overridden. |
| `suggest_url` | str | `""` | http(s) URL that receives a JSON copy of every improvement suggestion (§5.16); `FATHOM_SUGGEST_URL` is the server-wide fallback. Error `bad_enum` when not `http(s)://…`. |

#### 4.3.4 `venues[]`

`id` (req), `name` (req), `address`, `notes`, `order` (int).

#### 4.3.5 `rooms[]`

| Field | Type | Req | Notes |
| --- | --- | --- | --- |
| `id`, `name` | str | yes | |
| `venue` | str | yes | venue id |
| `code` | str | no | ≤ 8 chars `[A-Z0-9-]`, used in cable tags (`{room}`) and labels; default = uppercase first 4 letters of slug |
| `kind` | str | no | one of `ROOM_KINDS` (Appendix A.5); default `other` |
| `order` | int | no | picker order |
| `notes` | str | no | |
| `flow` | obj | no | Signal-flow map config for this room (below) |

`room.flow` (all optional; defaults from v1 `model.py`):

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `title`, `intro`, `footnote`, `system` | str | from `meta` for the default room; `title` = meta.title, `system` = room name for other rooms | Eyebrow is `org · system`. |
| `columns` | `[{id,label,side}]` | `DEFAULT_COLUMNS` | v1 Column dicts. |
| `groups` | `[{id,label,side,note?,order?}]` | `[]` | v1 Group dicts (never `auto`). |
| `spine` | `{label, show}` | `{"label":"Dante network","show":true}` | |
| `options` | obj | v1 `Options` defaults | v1 `options` dict verbatim (`auto_dante_nodes`, `auto_sources`, `dante_counts`, `appendix`, `appendix_print`, `card_width`, `column_gap`). |
| `extra_cards` | `[ExtraCard]` | `[]` | Additional cards for a device drawn twice (v1 `ref` nodes). |

`ExtraCard`: `id` (req, unique among devices **and** extra cards of the doc), `device` (req, device id), `seq` (int), and any v1 node display/placement fields: `name`, `sub`, `lines`, `kind`, `brand`, `group`, `column`, `order`, `dante`, `count`, `suffix`, `icon`, `note`, `aliases`.

#### 4.3.6 `systems[]`, `locations[]`

- System: `id`, `room` (req), `discipline` (req, Appendix A.3 key), `name` (req), `notes`.
- Location: `id`, `name` (req), `venue`, `room` (either may be empty), `kind` (`booth|stage|rack_room|storage|catwalk|closet|other`, default `other`), `notes`.

#### 4.3.7 `racks[]`

`id`, `name` (req), `room`, `location`, `units` (int 1–60, req), `numbering` (`bottom_up` default | `top_down`), `faces` (`["front","rear"]` default), `depth_mm` (num), `order` (int), `notes`.

#### 4.3.8 `devices[]` and ports

| Field | Type | Req | Notes |
| --- | --- | --- | --- |
| `id`, `name` | str | yes | `name` = v1 `label` |
| `kind` | str | yes | Appendix A.1 key (unknown kept, warning) |
| `discipline` | str | no | override; default `KINDS[kind].discipline` (§4.4.2) |
| `room`, `system`, `location` | str | no | ids; `room: ""` = shared inventory |
| `template` | str | no | library template id it was made from |
| `manufacturer`, `model` | str | no | |
| `code` | str | no | short label code (≤ 12 chars) for cable labels; default uppercase slug without dashes, truncated to 8 |
| `sub`, `lines`, `brand`, `count`, `suffix`, `icon`, `note`, `aliases` | | no | v1 display fields (`lines`, `aliases` are `[str]`, `count` int) |
| `dante` | bool | no | v1: card has a Dante stub on the map spine / is a Dante device |
| `dante_name` | str | no | Dante device name for import matching |
| `status` | str | no | `installed` (default) \| `planned` \| `spare` \| `retired` |
| `tags` | `[str]` | no | free tags |
| `routing` | obj | no | `{"mode": "matrix"\|"passthrough"\|"indexed"\|"none"\|"explicit", "map": [[in_port, out_port], …]}`; default mode from kind (§4.4.5) |
| `ports` | `[Port]` | yes | always written (may be `[]`) |
| `channels`, `channel_links` | `[Channel]`, `[ChannelLink]` | no | console internals — input channels, buses, DCAs and the patch edges between them (§4.3.17); a doc with them is v2-only |
| `flow` | obj | no | `{group, column, order, seq, show}` map placement for the device's primary card; `show:false` hides it from the map |
| `patch` | obj | no | `{x, y}` world coordinates in the patch view (px at zoom 1); `collapsed: bool` |
| `rack` | obj | no | `{id, u, height, face, side, depth}` (FR-RACK-02) |
| `inventory` | obj | no | `{serial, asset_tag, firmware, purchase_date (YYYY-MM-DD), warranty_until (YYYY-MM-DD), vendor, cost (num), currency, po, notes, condition, fields}`; `condition` ∈ `CONDITIONS` (A.5; unknown values are dropped by `normalize`, warning `bad_condition`), `fields` = custom fields `{str: str}` (≤ 32 keys ≤ 40 chars, values ≤ 500 chars; FR-INV-07) |
| `container` | str | no | id of the `container`-kind device this device travels or lives in (FR-INV-08); warnings `container_missing`, `container_not_container`, `container_cycle`; contents are computed (`schema.container_contents`) |
| `short_code` | str | no | 8 chars over `23456789ABCDEFGHJKLMNPQRSTUVWXYZ`, unique per doc, shown as `XXXX-XXXX` (FR-INV-09); `normalize` upper-cases, strips `-` and drops malformed values, never assigns; the store assigns missing codes on every write and keeps existing ones (unless `settings.short_codes` is `false`) |
| `interfaces` | `[Interface]` | no | §4.3.9 |
| `dmx` | obj | no | `{universe, address, footprint, mode, channel, protocol, port}` (FR-DMX-01) |
| `merged_from` | `[obj]` | no | provenance written by a device merge (§4.11.1): `[{id, name, source, at, by, fields: [str]}]` per absorbed duplicate |
| `auto`, `source` | | — | overlay-only; never persisted |

**Port**

| Field | Type | Req | Default | Notes |
| --- | --- | --- | --- | --- |
| `id` | str | yes | | unique per device |
| `name` | str | yes | | physical name ("Input 1", "AES Out 1/2") |
| `dir` | `in`\|`out`\|`io` | yes | | |
| `medium` | str | yes | | MEDIA key |
| `connector` | str | no | medium default | e.g. `XLR3F` |
| `group` | str | no | `""` | section heading ("Analog In"); expansion sets it |
| `index` | int | no | position in group (1-based) | display number |
| `channels` | int | no | 1 | multichannel ports (Dante 64, AES 2, MADI 64) |
| `label` | str | no | | what's on it ("Kick In", "Wireless 1") |
| `note` | str | no | | troubleshooting/map note (assistant suggestions write here) |
| `origin` | `template`\|`declared`\|`link`\|`user` | no | `user` | `declared` = from v1 `ports`, `link` = generated by migration from link text |

#### 4.3.9 `networks[]` and interfaces

- Network: `id`, `name` (req), `vlan` (int 1–4094), `subnet` (CIDR, e.g. `10.20.0.0/24`), `gateway` (IP), `protocol` (`dante|aes67|avb|ndi|st2110|sacn|artnet|qlan|control|management|other`), `dhcp_range` (str), `notes`.
- Interface (in `device.interfaces[]`): `id` (req, unique per device, e.g. `primary`), `role` (`primary|secondary|control|management|media`, default `primary`), `ip`, `prefix` (int 0–32) or derive from network, `gateway`, `vlan`, `mac`, `hostname`, `dhcp` (bool), `protocol` (as Network), `network` (network id), `switch` (device id), `switch_port` (port id or text), `port` (this device's port id carrying it), `note`.

#### 4.3.10 `cables[]` and `bundles[]`

**Cable**

| Field | Type | Req | Notes |
| --- | --- | --- | --- |
| `id` | str | yes | |
| `from`, `to` | `{device, port?}` | yes | `port` omitted = device-level endpoint |
| `medium` | str | yes | MEDIA key (default from the from-port, else to-port, else `analog`) |
| `tag` | str | no | printed cable ID (unique within doc; duplicate → warning `tag_duplicate`) |
| `type` | str | no | physical type ("XLR3 M-F", "Cat6 STP", "RG6 12G") |
| `length_m` | num | no | |
| `color` | str | no | jacket/label color name or `#rrggbb` |
| `channels` | int | no | channels carried (default = min(port channels) or 1) |
| `status` | str | no | as device status |
| `bidirectional` | bool | no | |
| `bundle` | str | no | bundle id |
| `label`, `signal`, `note`, `count`, `from_text`, `to_text` | | no | v1 link display fields (`label` = map label "AES · L/R", `signal` = "Main L/R", `count` = v1 channel count, `from_text`/`to_text` = v1 `from_port`/`to_port` text) |
| `flow` | obj | no | `{seq, from_card, to_card}`: map ordering and v1 ref-card endpoints |
| `auto`, `source` | | — | overlay-only |

**Bundle** (multicore / loom / snake): `id`, `kind` (`multicore|loom|snake|link`, default `link` for migration), `tag`, `type`, `length_m`, `medium`, `label`, `signal`, `note`, `count`, `from_text`, `to_text`, `bidirectional`, `flow {seq, from_card, to_card}`. Member cables reference it via `cable.bundle`.

#### 4.3.11 `floorplans[]`

| Field | Type | Req | Notes |
| --- | --- | --- | --- |
| `id`, `name`, `room` | str | yes | |
| `source` | `{attachment, kind, page}` | yes | original upload (`kind` ∈ `png jpg svg pdf drawio dxf dwg`) |
| `image` | `{attachment, kind, width, height}` | yes | displayable render (`kind` ∈ `png jpg svg`); width/height in px |
| `layers` | `[{name, color, visible, count}]` | no | DXF/Draw.io layers |
| `hidden_layers` | `[str]` | no | |
| `calibration` | `{p1:[x,y], p2:[x,y], distance, unit:"m"|"ft"}` | no | normalized points |
| `units` | obj | no | from DXF: `{"insunits": 6, "meters_per_unit": 1.0}` |
| `markers` | `[{device, x, y, rotation?, label?}]` | no | normalized 0–1 coordinates relative to `image` width/height; one marker per device per plan |
| `order`, `notes` | | no | |

#### 4.3.12 `attachments[]`

`id`, `name` (original filename, req), `file` (path relative to the project dir, `files/<id>/<safe-name>`, req), `mime` (req), `size` (int), `sha256`, `device` (optional device id), `kind` (`photo|document|floorplan|floorplan-source|other`), `uploaded` (UTC ISO), `by` (username), `note`.

#### 4.3.13 `imports[]`

`id` (req), `kind` (registry key, req), `path` (relative to project dir or absolute, req), `device` (v1 `node`), `room` (default = default room), `label`, `options` (obj, importer-specific), `added`, `by`.

#### 4.3.14 `templates[]`

Project-local templates in the format of §4.5 plus `"source": "project"`.

#### 4.3.15 `pages[]` — SOP wiki

Standard operating procedures, troubleshooting guides, checklists and reference pages written in Markdown and linked to the equipment they apply to. A doc with pages is v2-only (`is_v1_expressible` → false).

| Field | Type | Req | Default | Notes |
| --- | --- | --- | --- | --- |
| `id` | str | yes | — | Generated `pg-` + 8 hex. |
| `slug` | str | yes | — | `^[a-z0-9][a-z0-9-]{0,79}$`, unique in the project (error `duplicate_slug`); used in URLs and `[[page:<slug>]]` links. |
| `title` | str | yes | — | |
| `kind` | str | no | `sop` | `sop`, `troubleshooting`, `checklist`, `reference` (error `bad_enum`). |
| `status` | str | no | `published` | `draft` (hidden from viewers), `published`, `archived`. |
| `parent` | str | no | — | Parent page id; must exist (`dangling_ref`), no loops (`page_cycle`). |
| `order` | int | no | — | Position among siblings (renumbered 1..n by `/move`). |
| `summary` | str | no | — | One line for lists; falls back to the first 160 characters of the body. |
| `body` | str | no | `""` | Markdown (§5.15). |
| `tags`, `rooms`, `devices`, `attachments` | `[str]` | no | `[]` | Explicit "applies to" links (unknown ids are warnings `dangling_link`). Body refs count too (§5.15 backlinks). |
| `review_due` | str | no | — | ISO date (warning `bad_date`). |
| `owner`, `created`, `updated`, `updated_by` | str | no | — | Set by the server/editor. |
| `completions` | `[{at, by}]` | no | `[]` | "Mark complete" records by editors (§5.16), newest last, capped at 20. |

Archived pages are hidden from viewers and volunteers everywhere (app tree, inspector "Procedures", public routes, QR sheets, report section, offline bundle); editors see them under the tree's "Archived" filter (or when searching) and can restore them (`status: published`). Deleting a page that has children archives it instead (§5.15 DELETE).

#### 4.3.16 `problems[]` — problem reports

"Report a problem" entries filed from SOP pages (app, public `/p/` pages, share links). Small on purpose: a problem is a line of text tied to a device and/or page, with its reporter and channel, until an editor resolves it. A doc with problems is v2-only.

| Field | Type | Req | Default | Notes |
| --- | --- | --- | --- | --- |
| `id` | str | yes | — | Generated `pr-` + 8 hex. |
| `text` | str | yes | — | Description (error `missing_field` when empty; the server caps at 2000 chars). |
| `status` | str | no | `open` | `open`, `resolved` (error `bad_enum`). |
| `device`, `room`, `page` | str | no | — | Device id, its room at report time, page slug (unknown ids are warnings `dangling_link`). |
| `attachment` | str | no | — | Photo uploaded with the report (`attachments[]` entry with `kind: photo`, `note: "Problem report <id>"`; warning `dangling_link`). |
| `created`, `by`, `via` | str | no | — | Set by the server: UTC time, reporter (login, or the typed name, or `anonymous`), channel `app` / `public` / `share`. |
| `resolved`, `resolved_by`, `note` | str | no | — | Set when resolved (cleared on reopen). |

#### 4.3.17 Console channels — `devices[].channels[]` and `channel_links[]` (`fathom/console.py`)

A mixing console is more than its connectors: the signal enters on a Dante receive channel, lands on an **input channel**, is sent to **buses** (mix, matrix, stereo, mono), grouped under **DCAs**, and leaves on a transmit channel or an Omni output. `channels[]` lists those logical channels and `channel_links[]` the edges between them, so a trace can follow *Bass → Rio analog in 6 → Dante 17 → CH 12 "Bass" → ST L/R → Dante 63/64 → Rio out 1/2 → amps*. The model is generic (any console); importers populate it (today the Yamaha CL/QL CSV export, §7.3.x), users edit it, and the tracer reads it. A doc that has them is v2-only (`is_v1_expressible` → false).

**Channel**

| Field | Type | Req | Notes |
| --- | --- | --- | --- |
| `id` | str | yes | unique per device; convention `<prefix>-<index>[-<side>]`: `in-12`, `stin-4-l`, `mix-3`, `mtx-7`, `st-l`, `mono`, `dca-1`, `mute-2`, racks `fx-1` / `geq-3` / `prfx-6` (`console.channel_id`) |
| `kind` | str | yes | `input`, `stereo_input`, `mix`, `aux`, `group`, `matrix`, `stereo`, `mono`, `dca`, `mute_group`, `rack`, `monitor`, `cue`, `talkback`, `oscillator` (`vocab.CHANNEL_KINDS`; unknown kept, warning `unknown_channel_kind`) |
| `index` | int | no | console number (`CH 12` → 12); omitted for `stereo` / `mono` |
| `side` | str | no | `L` / `R` for stereo pairs (`stereo_input`, `stereo`) |
| `rack` | str | no | rack family for `kind: rack` (`FX`, `GEQ`, `PRFX`, `PEQ`); the rack's two sides are endpoint `tag`s `A` / `B` |
| `name` | str | no | console name ("Bass", "9 IEM", "BAND") |
| `label` | str | no | display label override; default `CH 12`, `ST IN 4 L`, `MIX 3`, `MATRIX 7`, `ST L`, `MONO`, `DCA 1`, `FX 1` (`console.channel_label`) |
| `color`, `icon`, `note` | str | no | console colour / icon names, free note |
| `source` | str | no | `user` (default when edited in the app), `yamaha`, `clf`, `dante`, `csv` (`vocab.CHANNEL_SOURCES`; warning `bad_enum`). `user` and `csv` are hand-entered (`console.MANUAL_SOURCES`): imports never overwrite them (§4.11). `clf` is reserved — the CL Editor `.CLF` console file is a proprietary, undocumented binary and is **not** parsed (§7.3, *Console sends*); sends and DCA membership are entered in the inspector or through the console CSV template (§5.7.4). |

**ChannelLink** — `{from, to, kind, insert?, note?, source?}`; `from`/`to` are **endpoints**:

| Endpoint | Meaning |
| --- | --- |
| `{"channel": "in-12"}` | a console channel of this device; racks add `"tag": "A"` / `"B"` |
| `{"port": "dante-primary", "ch": 17}` | sub-channel `ch` (1-based) of a multichannel port of this device; `ch` omitted for mono connectors (`{"port": "omni-out-7"}`). At `from` the signal **enters** the device (a receive channel), at `to` it **leaves** (a transmit channel). |
| `{"text": "REC 1"}` | a console port the importer could not map onto a device port (kept verbatim; warning `dangling_port` when a `port` id is unknown, the link is kept as text) |

| `kind` | Edge | Example |
| --- | --- | --- |
| `input_patch` | port / rack → input channel | `DANTE 17 → CH 12` |
| `send` | channel → bus (level not modelled; absence means *not recorded*, never *off*) | `CH 12 → ST L`, `CH 12 → MIX 9` |
| `output_patch` | bus / channel → port / rack | `ST L → DANTE 63`, `MIX 9 → OMNI 3` |
| `direct_out` | input channel → port (`DIR CH 43`) | `CH 43 → SLOT1 9` |
| `insert_send` / `insert_return` | channel ↔ rack or port; `insert` = insert slot 1/2 | `MATRIX 7 → PRFX 1 A`, `PRFX 1 A → MATRIX 7` |
| `dca`, `mute` | input channel / bus → DCA / mute group (control only — a trace reports them as *via*, never as an audio hop unless asked) | `CH 12 → DCA 1` |

Validation (`schema._channel_problems`): errors `bad_type`, `missing_field` (channel `id`/`kind`, link `from`/`to`/`kind`), `bad_id`, `duplicate_channel`, `dangling_channel` (endpoint channel not in `channels[]`), `bad_enum` for a non-positive `ch` or an `insert` other than 1/2; warnings `unknown_channel_kind`, `unknown_link_kind`, `bad_enum` (source), `dangling_port`. A link whose two endpoints are both ports is allowed (console-internal port-to-port patch). Links are unordered; `console.sort_channels` orders channels by kind, rack, index, side.

### 4.4 Semantics

#### 4.4.1 Normalization (`schema.normalize(doc) -> doc`)

Returns a new doc: sets `fathom: 2`; ensures every collection exists; strips entities/ports with `auto: true`; drops `null` values and empty strings/arrays/objects from optional fields (except `ports`); sorts nothing (order is meaningful). `normalize` is idempotent and is applied before every save.

#### 4.4.2 Discipline

`discipline(device) = device.discipline or KINDS[device.kind].discipline or "other"`. A cable's discipline = `MEDIA[cable.medium].discipline` (unknown → `other`). A port's discipline = its medium's discipline.

#### 4.4.3 Port-group expansion (shared Python/JS algorithm)

Input: list of groups `{group, dir, medium, connector?, count?, names?, dirs?, channels?, start?, label?, labels?}` (`dirs` maps a name to its own direction, e.g. `{"In": "in", "Out": "out"}`). Output: list of ports in order.

```
for g in groups:
    base = slug(g.group)                        # "Mic/Line In" -> "mic-line-in"
    if g.names:                                 # explicit per-port names
        for i, nm in enumerate(g.names, 1):
            emit(id = base + "-" + slug(nm), name = g.group + " " + nm, index = i)
    elif (g.count or 1) > 1 or g.start:         # numbered
        s = g.start or 1
        for k in range(count):
            n = s + k
            emit(id = base + "-" + str(n), name = g.group + " " + str(n), index = n)
    else:                                       # single
        emit(id = base, name = g.group, index = 1)
    each emitted port: dir = g.dirs[nm] if g.dirs and the port came from names and nm in g.dirs else g.dir,
                       medium = g.medium, connector = g.connector (if any),
                       group = g.group, channels = g.channels (if > 1), origin = "template",
                       label = g.labels[i-1] if g.labels and i <= len(labels) else g.label (if any)
de-duplicate ids: if an id already exists in the output, append "-b", "-c", ...
```

v1 `ports` declarations use `{name, direction, medium, count?, labels?}`: they are converted first (`group = name`, `dir = {"in":"in","out":"out","bi":"io","io":"io"}[direction]` default `io`), with `labels` acting as `names` (v1 semantics: one port per label), origin `declared`. **Network media rule (v1 only):** a v1 group whose medium is in `{dante, avb, aes67, aes50, madi, snake, network, qlan}` with `count` N > 1 becomes **one** port (id `slug(name)`, `channels: N`), because v1 counts there are channels, not connectors.

Shared vectors live in `tests/fixtures/port-expansion.json` (T1 creates; T2 reads): `[{"input": {...groups...}, "v1": false, "expected": [...ports...]}]`, at least 8 cases (numbered, named, single, start offset, labels, dedupe, v1 network rule, v1 labels).

#### 4.4.4 Connection rules (`canConnect`)

| From dir → To dir | Result |
| --- | --- |
| out → in, out → io, io → in, io → io | allowed |
| in → anything, anything → out | error `bad_direction` (UI refuses) |
| same device, same port | error `self_loop` |

Medium checks (only when both ports have media): equal → ok; `carries` intersect → warn `medium_mismatch` ("HDMI → SDI: needs a converter?"); disjoint → warn `medium_incompatible`. Target `in` port already having ≥ `channels` cables → warn `port_overuse`. A port with `dir: in` receiving a cable from a device-level endpoint is ok.

#### 4.4.5 Internal routing (used by tracing)

| Mode | Internal edges |
| --- | --- |
| `matrix` | every `in`/`io` port → every `out`/`io` port (≠ itself) where `carries(in) ∩ carries(out) ≠ ∅` (∩ the trace discipline when filtered) |
| `passthrough` | port A (`in`/`io`) → port B (`out`/`io`), `A.medium == B.medium`, and either (a) A and B are in the **same** group and that group has exactly one `in` port (thru semantics: `DMX In → DMX Out/Thru`, `Power In → Power Out`), or (b) `idx(A) == idx(B)` and `stem(A.group) == stem(B.group)` for different groups, where `idx(p) = p.index or (1-based position of p among ports with the same group)` and `stem(g)` = `slug(g)` split on `-` with the tokens `in, input, inputs, out, output, outputs, thru, through, loop` removed, re-joined with `-`. Examples: "Analog In"/"Analog Out" → `analog`; "HDMI In"/"HDMI Out" → `hdmi`; "IEM Return" → `iem-return` (no partner). Used for passive snakes, wall plates, DMX thru, speaker thru. |
| `indexed` | channel-numbered stage boxes and converters: analog/AES **in** port *n* → sub-channel *n* of every multichannel (`channels > 1`) `out`/`io` port, and sub-channel *n* of every multichannel `in`/`io` port → analog/AES **out** port *n*, where *n* counts the device's single-channel in (resp. out) ports in port order, a 2-channel AES port taking two numbers (Rio3224-D: analog in 1–32 → Dante TX 1–32; Dante RX 1–16 → analog out 1–16, RX 17–24 → AES out 1/2–7/8). Port-level tracers (which do not know sub-channels) treat it as `matrix`. |
| `none` | no internal edges (endpoints: speakers without thru, streams, projectors) |
| `explicit` | exactly `routing.map` pairs |

Default mode per kind is the `routing` column of Appendix A.1; a template's `routing` (§4.5) is copied onto devices made from it (`library.instantiate`). The built-in Yamaha R/Tio and Focusrite RedNet stage-box templates use `indexed`.

#### 4.4.6 State filter

`state=all` (default): everything except `retired`; `state=everything`: include retired; `state=planned`: planned + installed; `state=as_built`: installed only. Applies to devices; cables follow their own status, and a cable is excluded if either endpoint device is excluded. Spares (`spare`) are included only in `all`/`everything` and in inventory/BOM regardless of state.

### 4.5 Equipment template format (library, `doc.templates`, `<data>/library/*.json`)

```json
{
  "id": "yamaha-rio3224-d2",
  "manufacturer": "Yamaha",
  "model": "Rio3224-D2",
  "name": "Rio3224-D2",
  "kind": "stage_io",
  "discipline": "audio",
  "brand": "yamaha",
  "ru": 5, "width": "full", "depth_mm": 368, "power_w": 120, "weight_kg": 13.5,
  "cost": null, "currency": "USD",
  "dante": true,
  "routing": "indexed",
  "dmx_footprint": null,
  "ports": [
    {"group": "Analog In", "dir": "in", "medium": "analog", "connector": "XLR3F", "count": 32},
    {"group": "Analog Out", "dir": "out", "medium": "analog", "connector": "XLR3M", "count": 16},
    {"group": "AES Out", "dir": "out", "medium": "aes3", "connector": "XLR3M", "names": ["1/2", "3/4", "5/6", "7/8"], "channels": 2},
    {"group": "Dante", "dir": "io", "medium": "dante", "connector": "etherCON", "names": ["Primary", "Secondary"], "channels": 32}
  ],
  "dante_channels": {"tx": 32, "rx": 24},
  "checks": [
    {"id": "rio.ha-gain", "symptoms": ["no_audio", "noise"], "when": {"port_dir": "in"}, "text": "On the console, check the {device} HA gain and +48V for **{port}**."}
  ],
  "tags": ["stagebox", "dante"],
  "source_url": "https://usa.yamaha.com/products/proaudio/interfaces/r_series_adda_2/specs.html",
  "notes": ""
}
```

| Field | Req | Notes |
| --- | --- | --- |
| `id` | yes | `^[a-z0-9][a-z0-9-]{1,79}$`, convention `<manufacturer-slug>-<model-slug>` |
| `manufacturer`, `model`, `kind` | yes | |
| `name` | no | default `model` |
| `discipline`, `brand`, `ru`, `width` (`full|half`), `depth_mm`, `power_w`, `weight_kg`, `cost`, `currency`, `dante`, `routing`, `dmx_footprint`, `dante_channels`, `checks`, `tags`, `source_url`, `notes` | no | |
| `ports` | yes | groups for §4.4.3 (non-v1 mode) |

`library.instantiate(template, device_id=..., name=None, room="", count=None)` returns a device dict: `id, name (name or template.name), kind, discipline (only if ≠ kind default), manufacturer, model, brand, template: <id>, room, ports: expand_port_groups(template.ports)`, `dante: true` if template.dante, `dmx: {"footprint": dmx_footprint}` if set, `rack: {"height": ru}` is **not** set until racked (the UI reads `ru` from the template when racking).

### 4.6 Migration v1 → v2 (`schema.migrate`)

#### 4.6.1 Detection (`schema.doc_version(d)`)

`2` if `d.get("fathom") == 2`; `1` if `d.get("fathom") == 1` or `"signalflow" in d` or (no `fathom` key and any of `nodes`, `links`, `groups`, `columns` present); `0` for an empty dict (treated as v1 blank). Version > 2 → `SchemaError("project written by a newer Fathom (schema N)")`. `schema.load_any(d) -> doc` migrates v0/v1, normalizes v2.

#### 4.6.2 Root mapping

| v1 | v2 |
| --- | --- |
| `meta` | `meta` (verbatim) |
| `spine`, `columns`, `groups` (non-auto), `options` | `rooms[0].flow.spine/columns/groups/options` |
| `media` | `media` |
| — | `venues = [{"id": "main", "name": meta.org or "Main venue"}]` |
| — | `rooms = [{"id": "main", "venue": "main", "name": "Main room", "code": "MAIN", "kind": "other", "flow": {…}}]` |
| — | `systems = [{"id": "main-audio", "room": "main", "discipline": "audio", "name": meta.system or "Audio system"}]` |
| — | `settings = {"default_room": "main", "units": "metric", "cable_tag_pattern": "{D}-{n:03}", "currency": "USD", "autosave": true}` |
| `imports[i]` | `imports[i] = {"id": "imp-%04d" % (i+1), "kind", "path", "label", "device": node (if any), "room": "main"}` |

#### 4.6.3 Nodes → devices / extra cards

Process v1 `nodes` in order with `seq = position`:

- **Id remap:** if a node id fails the §4.2 regex, new id = `slug(id)` deduped; the old id is appended to `aliases`; every reference (links, imports `node`, `ref`) is remapped.
- Node **without** `ref` → device: `id, name = label, kind, room = "main", system = "main-audio"` (no `status` key: default installed), display fields `sub, lines, brand, count, suffix, icon, note, aliases, dante, dante_name` copied when present, `flow = {"group", "column", "order", "seq"}` (only non-empty keys, `seq` always), `ports = expand_port_groups(v1 ports, v1=True)` (origin `declared`).
- Node **with** `ref` → `rooms[0].flow.extra_cards[]`: `{id, device: canonical(ref), seq, name = label, sub, lines, kind, brand, group, column, order, dante, count, suffix, icon, note, aliases}`; its declared `ports` (if any) are merged into the canonical device's ports (skip ids already present).

#### 4.6.4 Port text resolution (`from_port` / `to_port`)

`parse_port_text(text)` (after `strip()`):

1. `^(?P<prefix>.*?)\s*(?P<a>\d+)\s*[-–]\s*(?P<b>\d+)$` with a ≤ b → **range** (prefix, a, b). "in 1-8", "Omni out 1-8", "out 1-11".
2. `^(?P<prefix>.*?)\s*(?P<n>\d+)$` → **index** (prefix, n, n), **unless** the character immediately before the number is one of `/ . : &` (then opaque). "line out 1", "in 5".
3. otherwise → **opaque** (text). "AES out 1/2", "AES50 A", "OH L/R, ride, perc, TB", "line in L/R ×4", "kit mics" (no digits).

`norm(s)` = `fathom.model.norm_name(s)`. Generic prefixes = `{"", "in", "input", "inputs", "out", "output", "outputs", "ch", "channel"}` (compared after `norm`).

`resolve(device, text, side, medium, count) -> [port_id]` where side is `out` (from) or `in` (to), and a bidirectional link uses `io`:

```
if not text: return []
p = parse_port_text(text)
if p is range/index:
    groups = numbered port groups of device (ports sharing `group`, dir compatible with side:
             out-side accepts out/io, in-side accepts in/io), in device port order
    g = first group where norm(p.prefix) in GENERIC
          or norm(p.prefix) is a substring of norm(group) or norm(group) is a substring of norm(p.prefix)
    if g and p.b <= len(g): return ids of g[p.a-1 : p.b]
    if g is None and device has no numbered group compatible with side:
        name = p.prefix.strip(); if norm(name) in GENERIC: name = "Out" if side == "out" else "In"   # "io" → "I/O"
        g = generate numbered group `name`, size p.b, dir side, medium, origin "link"   # ids slug(name)-1..b
        return ids of g[p.a-1 : p.b]
# opaque, or unresolved range/index
existing = port of device whose norm(name) == norm(text)
if existing: return [existing.id]
if "," not in text and "&" not in text:                 # trailing-token match, e.g. "AES out 1/2" -> "AES/EBU out 1/2"
    tok = last whitespace-separated token of text
    cands = ports with dir compatible with side, medium == link medium, last token of name == tok
    if len(cands) == 1: return [cands[0].id]
create single port: id = slug(text) (dedupe), name = text, dir side, medium, channels = max(1, count), origin "link"
return [that id]
```

A "numbered group" = a `group` value shared by ≥ 2 ports of the device (whatever their naming). If a generated numbered group already exists (from an earlier link) and the needed range exceeds it, extend it to `p.b` ports (keeping ids `slug(name)-<n>`).

**Empty-text side with a K-port other side:** when one side's text is empty and the other resolves to K > 1 ports, the empty side allocates the next K **uncabled** ports of its generated group `"Out"` (from side) / `"In"` (to side), creating/extending that group as needed (origin `link`). This makes RRC `crowd → rio3224 (6)` and `crowd → rio1608 (4)` produce `crowd:out-1…out-6` and `out-7…out-10`.

**Opaque side with a K-port other side (K > 1):** instead of a single port, generate K ports on the opaque side in a group named `text`: if splitting `text` on `,` gives exactly K non-empty parts, the ports are named by the parts (ids `slug(part)`, deduped with `-b`, `-c`…; e.g. "DI, amp mic" → ports `di` "DI" and `amp-mic` "amp mic"); otherwise named `"<text> <i>"` (ids `slug(text)-<i>`).

#### 4.6.5 Links → cables / bundles

For each v1 link in order (`seq` = position), with endpoints remapped to canonical devices (`from_card`/`to_card` recorded when an endpoint was a `ref` card):

- F = resolved from-ports, T = resolved to-ports (after the empty/opaque rules above).
- If `len(F) == len(T) > 1`: create bundle `b-%04d` (`kind: "link"`, `medium`, `label`, `count`, `from_text`, `to_text`, `signal`, `note`, `bidirectional`, `flow: {seq, from_card?, to_card?}`) and `len(F)` cables `c-%04d` pairing F[i]→T[i] with `bundle`, `medium`, `bidirectional`, `flow.seq = seq`.
- Else: one cable `c-%04d` from F[0] (or device-level if F empty) to T[0] (or device-level), with `medium, label, count, from_text, to_text, signal, note, bidirectional, flow {seq, from_card?, to_card?}`.
- Cable/bundle numbering is global and sequential in link order starting at 1.
- `auto` links are never migrated (they are not in v1 files).

#### 4.6.6 Flow adapter (`schema.flow_project(doc, room_id=None) -> Project`)

`room_id` defaults to `settings.default_room`. Produces a v1 `Project` (dataclasses) such that existing `merge.apply_imports`, `layout.compute_layout`, `render_html`, `render_svg`, `patch.build_patch_sheet`, `trace.*` work unchanged:

1. `meta` = `Meta(**doc.meta)` overridden by `room.flow.title/intro/footnote` when set; `meta.system` = `room.flow.system` or (`doc.meta.system` if room is the default room else `room.name`).
2. `columns`, `groups`, `options`, `spine_label`, `spine_show` from `room.flow` (v1 defaults when absent); `media_overrides = doc.media`.
3. Nodes: devices with `room == room_id`, `flow.show != false`, passing the state filter; plus `room.flow.extra_cards` (as nodes with `ref = device`). Sorted by `seq` (missing seq → `1_000_000 + index` in their list, devices before extra cards). Node fields: `id, label = name, sub, lines, kind, brand, group = flow.group, column = flow.column, dante, dante_name, aliases, count, suffix, order = flow.order, icon, note, ref`; `ports` = v1-style groups rebuilt from ports with `origin == "declared"` (group by `group`; `count` = number of ports, or `channels` for a single network-media port; `labels` when the group was built from labels). Devices with `auto` (overlay) are not included — imports re-create them via `apply_imports`.
4. External devices: for each cable with exactly one endpoint device in the room, the other device becomes an auto node (`auto=True`) in auto group `ext-left` / `ext-right` (side by kind) labelled "Other rooms", `sub` = "in <room name>".
5. Links: one per bundle and one per unbundled cable touching a node of this room, ordered by `flow.seq` (entities without `seq` after all with, in list order): `source = flow.from_card or from.device`, `target = flow.to_card or to.device`, `medium`, `label`, `note`, `bidirectional`, `signal`. For **migrated** entities (those having `flow.seq`) `count`, `from_port`, `to_port` are taken verbatim from `count`, `from_text`, `to_text` (absent → `None`/`""`), which preserves v1 exactly. For v2-native entities: bundle `count` = number of member cables, cable `count` = `channels` if > 1 else `None`; `from_port`/`to_port` = `from_text`/`to_text` if set, else the endpoint port's name (bundles: `""`).
6. `imports` = `ImportSpec(kind, path, node=device, label)` for imports whose `room` is this room.

#### 4.6.7 v1-expressibility (`schema.is_v1_expressible(doc) -> bool`)

True iff: ≤ 1 venue and ≤ 1 room; no `racks`, `networks`, `floorplans`, `attachments`, `templates`, `locations`; ≤ 1 system; every device has no `inventory`, `rack`, `interfaces`, `dmx`, `template`, `routing`, `patch`, `tags`, `status` other than `installed`; every port has `origin ∈ {declared, link}` and no `label`/`note`; no cable has `tag`, `type`, `length_m`, `color`, `status`; no bundle has `tag`, `type`, `length_m`. `schema.to_v1(doc) -> dict` = `flow_project(doc).to_dict()` (with declared ports) for such docs.

#### 4.6.8 Identity invariant (tested, FR-MIG-03)

For every v1 dict `d` among RRC, `blank_project_dict()`, and T1's extra fixtures: let `p1 = project_from_dict(d)` and `p2 = flow_project(migrate(d))`; after `apply_imports` on both (same project dir), `strip_ports(p1.to_dict()) == strip_ports(p2.to_dict())`, and `compute_layout` boxes (rounded to 0.01) are identical for every card id. Appendix G shows the RRC excerpt.

### 4.7 Validation (`schema.validate_doc(doc) -> [Problem]`)

`Problem = {"level": "error"|"warning", "code": str, "ref": "<coll>/<id>" | "meta" | "", "path": "devices/rio3224/ports/3/dir", "message": str}`. **Errors block writes** (HTTP 422); warnings are returned with successful writes and shown in the UI.

| Code | Level | Condition |
| --- | --- | --- |
| `bad_type` | error | wrong JSON type for a known field (e.g. `ports` not a list) |
| `missing_field` | error | required field absent/empty |
| `bad_id` | error | id fails §4.2 regex |
| `duplicate_id` | error | duplicate id in a collection (devices and extra cards share one id space) |
| `duplicate_port` | error | duplicate port id in a device |
| `dangling_ref` | error | cable endpoint device, bundle, room.venue, system.room, extra_card.device, marker.device, floorplan.room, attachment.device, import.device that does not exist |
| `dangling_port` | warning | cable endpoint port id not on the device (kept; drawn device-level) |
| `bad_enum` | error | `dir`, `status`, `numbering`, `face`, `side`, `depth`, `units` outside its enum |
| `unknown_kind` / `unknown_medium` / `unknown_discipline` | warning | not in vocab (kept) |
| `bad_direction` | warning | cable from an `in` port or to an `out` port |
| `medium_mismatch` / `medium_incompatible` | warning | §4.4.4 |
| `port_overuse` | warning | §4.4.4 |
| `tag_duplicate` | warning | two cables (or bundles) with the same tag |
| `rack_unknown` / `rack_out_of_range` / `rack_overlap` | warning | §3.9 (computed by `racks.validate_racks`, called from `validate_doc`) |
| `bad_ip` / `bad_subnet` / `bad_mac` / `ip_duplicate` / `ip_outside_subnet` / `vlan_mismatch` | warning | §3.11 (helpers in `network.py`, called from `validate_doc`) |
| `dmx_range` / `dmx_overlap` / `dmx_overflow` | warning | §3.12 (helpers in `dmx.py`) |
| `bad_date` | warning | inventory dates not `YYYY-MM-DD` |
| `marker_out_of_bounds` | warning | marker x/y outside [0, 1] |

`validate_doc` must import the W2/W6 helpers lazily and skip a check (no exception) if a helper module fails to import, so W1 can ship first.

### 4.8 Cable tag pattern grammar

A pattern is literal text with tokens `{name}` or `{name:fmt}`:

| Token | Value |
| --- | --- |
| `{D}` | discipline letter of the cable's medium (A audio, V video, L lighting, N network, C control, P power, X other) |
| `{disc}` | discipline key (`audio`) ; `{DISC}` uppercase |
| `{M}` | `MEDIA[medium].short` uppercase (e.g. `XLR`, `SDI`, `DMX`, `CAT`) |
| `{room}` | room code of the from-device's room (`MAIN`; `X` if none) |
| `{from}` / `{to}` | device `code` of the endpoints |
| `{n}` | sequence number; `{n:03}` zero-pads to 3 digits (`:0W` = width W) |

Algorithm `cables.assign_tags_ops(doc, scope="missing", pattern=None)`: iterate cables in list order; skip cables with a tag when `scope == "missing"`; render the pattern with `{n}` replaced by a placeholder to get the **prefix key**; next n for that key = 1 + max n already used by any existing tag matching the same rendered pattern (regex built from the pattern with `\d+` for `{n}`), counting tags assigned earlier in this run; emit `{"op":"merge","coll":"cables","id":id,"value":{"tag":tag}}`. With `scope == "all"`, existing tags are ignored when computing maxima (full renumber). Bundles get tags with the same rules (P1) using their medium.

### 4.9 Change ops (shared Python/JS contract)

All writes are expressed as ops (PUT computes them by diff). One op per line below (each line is a JSON object; a request carries them in an array):

```json
{"op": "put",   "coll": "devices", "id": "rio3224", "value": {"id": "rio3224", "name": "Rio3224", "kind": "stage_io", "ports": []}}
{"op": "merge", "coll": "devices", "id": "rio3224", "value": {"name": "Rio 1", "patch": {"x": 10, "y": 20}, "note": null}}
{"op": "del",   "coll": "cables",  "id": "c-0012"}
{"op": "root",  "key": "settings", "value": {"units": "imperial"}}
```

| Op | Semantics |
| --- | --- |
| `put` | create or replace the entity with that id; new entities are appended to the end of the collection; replacing keeps the position. `value.id` must equal `id`. |
| `merge` | RFC 7396 JSON Merge Patch applied to the existing entity: objects merge recursively, `null` deletes a key, arrays replace wholesale. Merging into a missing entity is an error `missing_entity` (409 conflict class). |
| `del` | remove the entity; deleting a missing entity is a no-op (idempotent). |
| `root` | RFC 7396 merge into `meta`, `settings` or `media`. |
| `move` (P1) | `{"op":"move","coll":"devices","id":…,"before":<id or null>}` reorder in collection. |

- **Touched refs** of an op: `<coll>/<id>` (or the root key). A batch's touched set is the union.
- **Inverse** (for undo): for `put`/`merge`/`del` capture the entity before (`put` of the old entity, or `del` if it did not exist); for `root` the old root object (`root` with a full-replacement flag `{"op":"root","key":…,"value":…,"replace":true}`).
- `schema.apply_ops(doc, ops) -> (new_doc, touched)` (pure; deep-copies only touched entities), `schema.invert_ops(doc, ops) -> ops`, `schema.merge_patch(target, patch) -> value`, `schema.diff_docs(a, b) -> ops` (per collection: `del` for ids missing in b, `put` for new or changed entities (compared by canonical JSON), `root` with `replace:true` for changed root objects; collection order changes → `move` ops P1, else ignored).
- JS `model-core` implements the same four functions with the same semantics (`applyOps`, `invertOps`, `mergePatch`, `diffDocs`); shared vectors `tests/fixtures/ops-vectors.json` (T1 creates, T2 reads): `[{"doc": …, "ops": […], "expected": …, "touched": […]}]`, ≥ 10 cases.

### 4.10 Storage layout, revisions, history

```text
$FATHOM_DATA/
  users.json                       users (W1 users.py)
  secret.key                       32-byte hex, mode 0600
  library/<template-id>.json       global custom templates
  projects/<name>/
    project.json                   v2 doc (with "revision": N)
    project.v1.json                original v1 file, written once on first v2 save
    .lock                          lock file (POSIX flock / Windows msvcrt)
    exports/<kind>/...             import files (unchanged from v0.2)
    files/<att-id>/<safe-name>     attachments (photos, documents, plan sources and renders)
    files/<att-id>/cache/<sha1>.svg  derived renders (layer-hidden variants); deletable
    history/index.jsonl            one JSON line per revision (append-only)
    history/ops/<rev:06d>.json     ops that produced <rev> from <rev-1>
    history/snap/<rev:06d>.json    full normalized doc at <rev> (rev 1 and every 25th)
    shares.json                    share-link tokens (P1)
  builds/<name>/<stamp>_<slug>/... build runs (layout §5.9)
  trash/<name>/                    a deleted project: the whole projects/<name>/ folder moved here (FR-INV-07)
  trash/<name>/.trashed            {"at": ISO-8601 UTC, "by": username or "", "name": original project name}
  trash/<name>/.builds/...         its builds/<name>/ runs, moved along
```

Trash rules: `DELETE /api/v2/projects/<n>` (and `project.delete_project` / `trash_project`) moves the folder with `shutil.move` under the project lock; when `trash/<name>` already exists the new entry is `trash/<name>-<YYYYmmddHHMMSS>` and `.trashed.name` keeps the original name. `project.list_trashed()` returns `[{name, trashed_at, trashed_by, dir, rooms, devices}]` (`dir` is the trash entry used by the restore / purge routes; counts read from the stored project file, 0 when unreadable) and first purges entries older than 30 days (`purge_expired`, also `fathom trash purge --expired`). `restore_project(dir)` moves the folder and builds back and raises `ProjectExists` when a live project has that name; `purge_project(dir)` deletes the entry. Trashed projects are not under `projects/`, so `list_projects`, `GET /api/v2/projects`, search and `find_by_short_code` never see them.

`history/index.jsonl` line: `{"revision": 18, "time": "2026-10-20T21:14:03Z", "author": "priya", "summary": "Moved 3 devices", "source": "changes", "touched": ["devices/foh", "devices/mon"], "ops": 3, "snapshot": false}`.

Revision rules:
- A project without history (v0.2 or new) gets revision 1 + snapshot on its first write (source `migrate` for a migrated v1 file, else `put`) — before applying the incoming change, so the pre-change state is restorable.
- Each write: under the project lock, load current doc (rev N), check precondition (§5.4), apply ops, `normalize`, `validate_doc` (errors → reject), set `revision = N+1`, append `ops/<N+1>.json`, write snapshot if `(N+1) % 25 == 0`, append index line, atomically replace `project.json`. If any step before the final replace fails, nothing becomes visible (orphan ops files are ignored when `index.jsonl` lacks the line).
- `history.get_revision_doc(dir, rev)` = nearest snapshot ≤ rev + replay ops; if the chain is broken, return 404 `history_missing`.
- `history.touched_since(dir, base_rev) -> set` = union of `touched` of index lines with revision > base_rev.

### 4.11 Overlay (computed, `merge.build_overlay`)

```json
{
  "revision": 17,
  "imports_hash": "9f2c…",
  "devices":    [{"id": "dante-am2-7", "name": "AM2-7", "kind": "iem", "room": "main", "auto": true, "source": "dante", "ports": [{"id": "dante", "name": "Dante", "dir": "io", "medium": "dante", "channels": 2}]}],
  "detail":     {"foh": {"dante": {"name": "FOH-CL5", "tx": 64, "rx": 64}, "console": {"model": "CL5", "inputs_named": 58}}, "foh-pc": {"waves": {"app": "SuperRack SoundGrid", "racks": []}}},
  "routes":     [{"kind": "dante", "from": {"device": "neve1", "port": "dante-tx", "channel": "1 · Kick In", "ch": 1}, "to": {"device": "foh", "port": "dante", "channel": "1 · 01", "ch": 1}, "label": "Kick In", "medium": "dante"}],
  "channels":   {"foh": {"channels": [{"id": "in-12", "kind": "input", "index": 12, "name": "Bass", "source": "yamaha"}], "links": [{"from": {"port": "dante", "ch": 17}, "to": {"channel": "in-12"}, "kind": "input_patch", "source": "yamaha"}]}},
  "channel_labels": {"rio3224": {"dante-primary": {"out": {"6": "Bass 17"}, "in": {"1": "Main L"}}}},
  "port_labels": {"vhub": {"sdi-in-1": "CAM 1"}},
  "interfaces": {"rio3224": [{"id": "dante-primary", "role": "primary", "ip": "192.168.1.21", "protocol": "dante", "source": "dante"}]},
  "dmx":        {"fx-12": {"universe": 1, "address": 101, "footprint": 16, "channel": "12", "source": "eos"}},
  "patch_rows": [],
  "appendix":   {"dante": [], "console": []},
  "notes":      ["dante: added card for unplaced device 'AM2-7'"],
  "suggestions": {"dante-am2-7": [{"template": "focusrite-rednet-am2", "manufacturer": "Focusrite", "model": "RedNet AM2", "name": "RedNet AM2", "kind": "iem", "source": "builtin", "score": 1.0, "level": "high", "evidence": "model \"RedNet AM2\" = RedNet AM2 · manufacturer Focusrite", "kind_matches": true}]}
}
```

- Legacy importers run through `merge.apply_imports` on each room's flow project; results are lifted: auto nodes → overlay devices (kind as inferred, ports: one `dante` io port with `channels = max(tx, rx)` when Dante), `node.detail` → `detail`, Dante subscriptions → `routes` (device-level port = the device's first `dante`-medium port, else omitted; `from.ch` / `to.ch` = the integer TX / RX channel numbers when known), console channel names → `port_labels` on the console's matching Omni ports when they exist.
- `channel_labels[device][port] = {"out": {ch: tx_name}, "in": {ch: rx_name}}` — the Dante channel names of every device in a Dante preset, keyed by its first `dante` port; the UI shows both the Dante name and the console name of a channel.
- `channels[device] = {"channels", "links"}` (§4.3.17) — the console importer's channels and links for the console device the import is attached to, mapped onto that device's ports (`console.console_contribution`: `DANTE n` → the first `dante` io port with `ch: n`; `OMNI n` → the n-th analog Omni in/out port; `SLOTk n` → the k-th slot port with `ch: n`; anything else is kept as a `text` endpoint and listed in `notes`). Nothing is written to the doc: `console.effective_channels` serves the persisted set once the user has applied it (`POST …/channels/apply`, §5.6, or promoting the device copies them) and the overlay set before; on (re-)apply hand-entered (`user` / `csv`) channels and links survive and imported ones are replaced (`pending` compares the two sets regardless of link order).
- New importers contribute directly (`Importer.contribute`, §7.4.2).
- Routes always reference canonical device ids (never extra-card ids).
- Cache key: `(project, revision, imports_hash)` where `imports_hash` = sha1 of `(path, size, mtime_ns)` for every import file.
- `suggestions` (`library.suggest.suggest_for_device`): ranked library models for every overlay device without a `template`, scored from the `manufacturer` / `model` strings the source reported (Dante preset `manufacturer_name` / `model_name`, Device Info, CSV columns) and the device's name / subtitle; `level` is `high` ≥ 0.85, `medium` ≥ 0.60, else `low`. Variants (`Rio1608-D` vs `Rio1608-D2`) never score as exact. Discovery findings carry the same list per entity as `model_suggestions`; one-shot previews return it as `suggestions` keyed by device id.

#### 4.11.1 Merging duplicate devices (`dedupe.py`)

Two entries for one physical box (typically an import-created device and a hand-made one) are merged into a *survivor*; the duplicates disappear. `dedupe.find_duplicates(doc, overlay, device_id, min_score)` scores every pair of persisted + overlay devices (never overlay vs overlay) and `dedupe.merge_plan(doc, survivor, duplicates, choices, overlay)` returns a plan plus the change ops (§4.9) that perform it; both are pure.

- **Field rules.** Scalars (`name`, `kind`, `room`, `manufacturer`, `model`, `dante_name`, `status`, `inventory.*`, …): the survivor's non-empty value wins, blanks are filled from the duplicates in the given order; a differing non-empty value is flagged `conflict` and can be overridden per field (`choices[key] = device_id`). `tags`, `lines`, `aliases` are unioned; `note` / `inventory.notes` are concatenated; `dante` is OR-ed; `rack`, `flow`, `patch`, `dmx` are kept whole from the first device that has them; `routing.mode` comes from the winner, `routing.map` is unioned. Names, Dante names and ids that the merged device no longer carries become `aliases`, so importers that matched a duplicate keep matching the survivor. Unknown extra keys follow the scalar rule.
- **Ports** are unioned by id: same id with compatible `dir`/`medium` → one port (blank `label`/`note`/… filled); same id but incompatible → the duplicate's port is renamed (`_letter_dedupe`) and its cables remapped; new ids are appended. **Interfaces** are unioned by id, then by IP / MAC, blanks filled.
- **References** are re-pointed to the survivor: `cables[].from/to` (with port remap) and `cables[].flow.from_card/to_card`, `rooms[].flow.extra_cards[].device`, `floorplans[].markers[].device` (dropped when the survivor already has a marker on that plan), `attachments[].device`, `imports[].device`, other devices' `interfaces[].switch`. A cable that ends up on the survivor at both ends is kept and reported as a self-loop.
- **Provenance.** The survivor gets `merged_from: [{id, name, source, at, by, fields}]` (duplicates' own entries are carried along). Overlay (`auto`) devices can only be duplicates, are never deleted (they are not persisted) and merely enrich the survivor; the survivor must be a persisted device.
- **Transaction.** The ops are `put devices/<survivor>`, `merge …` for every re-pointed reference, then `del devices/<dup>`; applied together they form one revision (source `merge` via the API, or the client's own undo entry when the app commits them), so a history restore or Cmd/Ctrl+Z undoes the whole merge.
- **Scoring** (noisy-OR of positive signals, then multiplicative penalties; `high` ≥ 0.85, `medium` ≥ 0.65, suggestions below `min_score` 0.5 are dropped): serial 0.97, MAC 0.97, Dante name matching the other's name/alias 0.95, asset tag 0.9, IP 0.9, hostname 0.85, alias ↔ name 0.85, same normalised name 0.8, similar names (token-aware) up to ~0.55, shared model-like name token (`cl5`, `rio3224d`) 0.4, same manufacturer+model 0.3 / model 0.2 / model named in the other's text 0.3–0.45, same rack U 0.6 / same rack 0.15, +0.05 each for same room and kind; ×0.25 for numbered-series names (`Lustr 1`/`Lustr 2`, `Mon L`/`Mon R`) without a hard identifier, ×0.5 differing kinds, ×0.3 differing models, ×0.2 differing serials, ×0.85 differing rooms.

### 4.12 JSON Schema

`schema.JSON_SCHEMA` is a JSON Schema 2020-12 document covering §4.3 (types, required, enums, id patterns; `additionalProperties: true` everywhere for forward compatibility), served at `GET /api/v2/schema.json` and referenced from OpenAPI. `validate_doc` does **not** need a general JSON-Schema engine: it implements the rules of §4.7 directly. T1 checks the fixture and campus-demo against both (`validate_doc`, plus a tiny in-test subset validator for `type/required/enum/pattern/items/properties`).

Annotated example: Appendix B is the normative full example. Minimal valid doc (what `schema.new_doc(org="Hillside")` returns):

```json
{
  "fathom": 2,
  "revision": 0,
  "meta": {"org": "Hillside", "system": "Audio system", "title": "Signal flow, mic to speaker", "intro": "…v1 default…", "footnote": "…v1 default…"},
  "settings": {"default_room": "main", "units": "metric", "cable_tag_pattern": "{D}-{n:03}", "currency": "USD", "autosave": true},
  "venues": [{"id": "main", "name": "Hillside"}],
  "rooms": [{"id": "main", "venue": "main", "name": "Main room", "code": "MAIN", "kind": "auditorium",
             "flow": {"columns": "…DEFAULT_COLUMNS…", "groups": "…blank_project_dict groups…", "spine": {"label": "Dante network", "show": true},
                      "options": {"auto_dante_nodes": true, "auto_sources": true, "dante_counts": false, "appendix": true}}}],
  "systems": [], "locations": [], "racks": [], "networks": [], "devices": [], "cables": [], "bundles": [],
  "floorplans": [], "attachments": [], "templates": [], "imports": []
}
```

`fathom.project.blank_project_dict()` keeps returning the **v1** dict (frozen tests use it); `new_project(..., template="blank")` writes `schema.new_doc(org)` (v2).

---

## 5. API contract v2

### 5.1 Conventions

- WSGI app `fathom.server:app`. All URLs below are relative to the **app root** (`SCRIPT_NAME`, empty by default); the SPA and viewer always use relative URLs so Fathom works behind a sub-path reverse proxy.
- JSON in/out (`application/json; charset=utf-8`). Request JSON must be an object. Dates are UTC ISO 8601 with `Z`.
- Every mutating request from `api.js`, the CLI or scripts SHOULD send `X-Fathom: 1`; multipart/urlencoded/text POSTs MUST (FR-SEC-03).
- Errors: `{"error": "<human message>", "code": "<machine code>", "details": {…}}` with these status codes: 400 `bad_request`, 401 `auth_required` (with `WWW-Authenticate: Basic realm="Fathom"` only when the request had a Basic header or `Accept` is not HTML), 403 `forbidden` / `csrf`, 404 `not_found`, 405 `method_not_allowed`, 409 `conflict` / `v2_required` / `exists`, 413 `too_large`, 415 `unsupported_format` / `dwg_unsupported`, 422 `invalid` (with `details.problems`) / `pdf_unsupported`, 428 `precondition_required`, 429 `throttled`, 500 `internal` (no trace).
- Unauthenticated browser navigation to an app page (`/`, `/static/app.html`) when auth is on → `302 /login?next=<path>`.
- Caching: API responses `Cache-Control: no-store`; `/static/**`, `/sw.js`, `/manifest.webmanifest` → `Cache-Control: no-cache` + `ETag` (sha1 of path+size+mtime) with 304 support; viewer pages `no-cache`.
- Every handler is registered with `@route(method, pattern, role=..., summary=..., tags=..., body=..., response=...)`; `openapi.py` builds the spec from that table (§5.14).

### 5.2 Roles & permissions

Effective role = per-project override (P1: `users.json` user `projects: {"<project>": "viewer"|"editor"}`) else the user's global role. Admin is always admin. When auth is off, every request is admin `local`.

| Capability | viewer | editor | admin |
| --- | --- | --- | --- |
| Read projects, docs, overlay, history, schedules, search, trace, assistant (without applying), viewer pages, builds, SOP pages and their versions | ✓ | ✓ | ✓ |
| Write docs (`PUT`, `/changes`), imports, files, floor plans, restore, builds (create/delete), project-local templates, assistant suggestions, SOP pages (put/delete/move/restore/preview) | | ✓ | ✓ |
| Create projects; write global custom templates; create/revoke share links | | ✓ | ✓ |
| Delete projects; manage users; see `/api/v2/users` | | | ✓ |

### 5.3 Session & users

| Method | Path | Role | Request | Response (200 unless noted) |
| --- | --- | --- | --- | --- |
| GET | `/api/v2/session` | public | — | `{"auth_enabled": bool, "authenticated": bool, "user": {"username", "role"} \| null, "public_view": bool}` |
| POST | `/api/v2/session` | public | `{"username", "password"}` | `{"user": {"username", "role"}}` + `Set-Cookie: fathom_session=…`; 401 `bad_credentials`; 429 `throttled` |
| DELETE | `/api/v2/session` | any | — | `{"ok": true}` + expired cookie |
| GET | `/api/v2/users` | admin | — | `{"users": [{"username", "role", "disabled", "created", "projects"}]}` (never hashes) |
| POST | `/api/v2/users` | admin | `{"username", "password", "role", "projects?"}` | 201 `{"user": …}`; 409 `exists`; 400 weak password (< 8 chars) |
| PATCH | `/api/v2/users/<username>` | admin | any of `{"role", "password", "disabled", "projects"}` | `{"user": …}`; 404 |
| DELETE | `/api/v2/users/<username>` | admin | — | 204; 409 if deleting the last enabled admin |
| POST | `/api/v2/users/me/password` | any authenticated users.json user | `{"old", "new"}` | `{"ok": true}`; 403 wrong old password |
| GET | `/login` | public | — | `static/login.html` |
| GET | `/api/v2/invites` | admin | — | `{"invites": [open invites], "accept_url": "<app root>/invite/{token}"}`; expired entries are pruned, used ones hidden |
| POST | `/api/v2/invites` | admin | `Invite` `{"role?": viewer\|editor\|admin (editor), "projects?": {name: viewer\|editor}, "ttl_hours?": 72, "note?"}` | 201 the stored invite `{token, role, projects, created_by, created, expires, note, used_by, used_at}` + `"url"` (absolute: `FATHOM_PUBLIC_URL` or the request origin + `/invite/<token>`); 400 bad role / projects / ttl |
| DELETE | `/api/v2/invites/<token>` | admin | — | `{"ok": true}`; 404 |
| GET | `/invite/<token>` | public | — | `static/invite.html` (200 whatever the token; the page asks the API). App CSP; assets via `../static/…`, a trailing slash is redirected away |
| GET | `/api/v2/invites/<token>/check` | public | — | `{"ok": true, "role", "expires", "auth_enabled"}`; 404 `invalid_invite` (unknown, used, expired, revoked) |
| POST | `/api/v2/invites/<token>/accept` | public | `{"username", "password"}` | Creates the user with the invite's role and project overrides, marks the invite `used_by`/`used_at`, sets `fathom_session` exactly like `POST /api/v2/session`; `{"user": {"username", "role", "projects?"}}`. 404 `invalid_invite`; 409 `exists`; 400 bad username / `weak_password` (the invite stays open); 429 `throttled` after 5 bad tokens per (IP, token) in 5 min. Works with login off too: the new user turns login on. |

Username regex `^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$`. Session cookie payload `{"u": username, "exp": unix_seconds, "ep": epoch}` → `base64url(json) + "." + base64url(hmac_sha256(secret, base64url(json)))`; valid iff signature ok, `exp` in the future, user exists, enabled, and `ep == user.epoch`. Basic auth checks users.json then `FATHOM_AUTH`. The session `user` object adds `projects` (the per-project override map) when the user has overrides. Invite tokens are `inv-` + 26 url-safe chars (`secrets.token_urlsafe`), stored in `<data>/invites.json` (atomic write, mode 0600, like `users.json`); CLI `fathom invite create [--role R] [--project name=role …] [--hours 72] [--note …]` (prints the path), `fathom invite list [--all]`, `fathom invite revoke <token>`.

**Editing lock (FR-USER-12).** When the stored doc has `settings.locked: true`, `POST /api/v2/projects/<n>/changes` and `PUT /api/v2/projects/<n>` answer **423** `{"error": "this project is locked for editing", "code": "locked", "details": {"locked_by", "locked_at"}}` — unless the request is the lock change itself: every op is a `root` op on `settings` whose value touches only `locked`, `locked_by`, `locked_at` (a `replace: true` root op counts when nothing else differs from the stored settings), or for PUT the only difference from the stored doc is those three keys. Any editor may lock or unlock. The handlers stamp `locked_by` (login, or `local`) and `locked_at` (UTC) when `locked` flips to true, keep the original stamp on a re-lock, and remove both when it flips to false — clients send only `locked`. The lock covers the model editors only: builds, problem reports, SOP page writes, checklist completions and file uploads are unaffected. `GET /api/v2/projects` entries carry `locked` (bool), `locked_by` and `locked_at` (empty strings when unlocked).

### 5.4 Concurrency contract

- `GET /api/v2/projects/<n>` returns `ETag: "r<revision>"`.
- `PUT /api/v2/projects/<n>` requires `If-Match: "r<rev>"` **or** body `"base_revision": <rev>`; neither → 428 `precondition_required`.
- `POST …/changes` requires body `base_revision`.
- Let `cur` = stored revision and `base` = client base. `base > cur` → 409 `conflict` (client ahead/corrupt). `base == cur` → apply. `base < cur` → `T_client` = touched refs of the request ops (for PUT: of `diff_docs(doc_at(base), body.doc)` — computed against the **base** revision doc so the client's unchanged entities are not counted); `T_since = history.touched_since(base)`; if `T_client ∩ T_since == ∅` → apply the client ops to the current doc, respond `rebased: true`; else 409:

```json
{"error": "Someone else changed 2 items since your revision 17", "code": "conflict",
 "details": {"revision": 19, "conflicts": ["devices/atem-mini", "cables/c-0011"], "by": ["sam"]}}
```

- The PUT body `doc` is never stored verbatim when rebased; only its diff ops are applied.

### 5.5 Meta, schema, library

| Method | Path | Role | Response |
| --- | --- | --- | --- |
| GET | `/api/v2/meta` | viewer | `{"version", "vocab": vocab.as_dict(), "importers": [{"kind", "label", "mode", "accepts", "folder", "help"}], "plugins_errors": [str], "samples": [str], "capabilities": {"chrome": bool, "pdf_rasterizer": str\|null, "oda": bool, "llm": {"configured": bool, "model": str}, "secure_context_hint": bool}, "auth": {"enabled": bool, "public_view": bool}, "limits": {"max_upload_mb", "max_json_mb"}, "library_count": int}` |
| GET | `/api/v2/schema.json` | public | `schema.JSON_SCHEMA` |
| GET | `/api/v2/library?q=&discipline=&kind=&project=` | viewer | `{"templates": [{"id", "manufacturer", "model", "name", "kind", "discipline", "ru", "ports_summary": "32× Analog In · 16× Analog Out …", "source": "builtin\|extension\|custom\|project"}]}` (project-local included when `project` given) |
| GET | `/api/v2/library/<id>?project=` | viewer | full template; 404 |
| GET | `/api/v2/library/suggest?manufacturer=&model=&text=&kind=&project=&limit=` | viewer | `{"query": {…}, "suggestions": [{"template", "manufacturer", "model", "name", "kind", "source", "score", "level": "high\|medium\|low", "evidence", "kind_matches"}]}` ranked library models for identity strings (§4.11 `suggestions`); presets are never suggested; `limit` ≤ 20 |
| POST | `/api/v2/library` | editor | body = template → 201 (written to `<data>/library/<id>.json`); 422 problems; 409 when id is built-in and `?override=1` absent |
| DELETE | `/api/v2/library/<id>` | editor | custom only → 204; built-in → 409 |
| GET | `/api/v2/presets` | viewer | `{"groups": ["Power", "Network & IT", "Audio", "Video", "Lighting"], "presets": [{"id", "label", "group", "kind", "description", "aliases", "ru", "ports": [port groups], "dante"?, "dmx_footprint"?, "width"?, "routing"?, "tags"}]}` (FR-LIB-06; the same presets are served by the library routes with `source: "preset"`) |

### 5.6 Projects, documents, changes, history

| Method | Path | Role | Request | Response / codes |
| --- | --- | --- | --- | --- |
| GET | `/api/v2/projects` | viewer | — | `{"projects": [{"name", "org", "title", "schema": 1\|2, "revision", "rooms", "devices", "cables", "updated", "builds", "role"}]}` |
| POST | `/api/v2/projects` | editor | `{"name", "template": "blank"\|<sample>, "org"}` | 201 `{"name", "revision"}`; 400 bad name; 409 `exists` |
| GET | `/api/v2/projects/<n>` | viewer | — | `{"name", "revision", "doc", "problems", "role", "migrated_from": 1\|null}` + `ETag` |
| PUT | `/api/v2/projects/<n>` | editor | `{"doc", "summary?", "base_revision?"}` + `If-Match` | `{"revision", "rebased", "problems"}`; 409; 422; 428 |
| POST | `/api/v2/projects/<n>/changes` | editor | `{"base_revision", "ops": [...], "summary?"}` (≤ 2000 ops) | `{"revision", "rebased", "problems", "touched"}`; 409; 422 |
| DELETE | `/api/v2/projects/<n>?confirm=<n>[&purge=1]` | admin | — | moves the project and its builds to the trash (§4.10): `{"ok": true, "trashed": true}`; `purge=1` deletes for good → `{"ok": true, "trashed": false}`; 400 without confirm |
| GET | `/api/v2/trash` | admin | — | `{"items": [{"name", "trashed_at", "trashed_by", "dir", "rooms", "devices"}], "retention_days": 30}` (newest first; expired entries are purged first) |
| POST | `/api/v2/trash/<dir>/restore` | admin | — | `{"ok": true, "name": <original name>}`; 404 `not_found`; 409 `exists` when a live project has that name |
| DELETE | `/api/v2/trash/<dir>` | admin | — | `{"ok": true}`; 404 `not_found` |
| GET | `/api/v2/codes/<code>` | viewer | — | `<code>` = `XXXX-XXXX` or `XXXXXXXX`, any case: `{"project", "device", "name", "room", "kind"}` for the device carrying that `short_code` in any live project the caller may view; 404 `{"error": "not_found"}` |
| GET | `/api/v2/projects/<n>/doc.json` | viewer | — | doc as download (`Content-Disposition: attachment; filename="<n>-project.json"`) |
| GET | `/api/v2/projects/<n>/history?limit=50&before=<rev>` | viewer | — | `{"revisions": [index lines, newest first]}` |
| GET | `/api/v2/projects/<n>/history/<rev>` | viewer | — | `{"revision", "entry": {…index line…}, "doc"}`; 404 `history_missing` |
| GET | `/api/v2/projects/<n>/history/<rev>/diff?against=<rev2>` | viewer | — | P1 `{"added": [refs], "removed": [refs], "changed": [refs]}` |
| POST | `/api/v2/projects/<n>/history/<rev>/restore` | editor | `{"base_revision"}` | `{"revision"}` (source `restore`, summary "Restored revision <rev>") |
| GET | `/api/v2/projects/<n>/overlay` | viewer | — | overlay (§4.11) + `ETag: "r<rev>-<imports_hash>"` |
| GET | `/api/v2/projects/<n>/devices/duplicates?device=<id>&min=0.5&limit=50` | viewer | — | `{"revision", "min_score", "total", "duplicates": [{"devices": [survivor, duplicate], "score", "confidence": high\|medium\|low, "reasons": [{"signal", "weight", "text"}], "suggested_survivor"}]}` — persisted and overlay devices; scored by serial / MAC / asset tag / IP / hostname / Dante name / aliases / name similarity / model / rack position, penalised for numbered series, differing kinds, models, serials and rooms; 404 unknown `device` |
| POST | `/api/v2/projects/<n>/devices/merge/preview` | editor | `{"survivor", "duplicates": [ids], "choices?": {field: device_id\|"union"}}` | merge plan — **no write**: `{"revision", "survivor", "duplicates", "devices", "fields": [{"key", "label", "rule", "values": {id: v}, "winner", "result", "conflict", "overridable", "reason"}], "ports", "interfaces", "references", "warnings", "result", "ops", "summary"}`; 400 `self_merge`/`no_duplicates`/`auto_survivor`; 404 `not_found` |
| POST | `/api/v2/projects/<n>/devices/merge` | editor | preview body + `"base_revision?"` | applies the plan's ops as one revision (source `merge`, summary "Merged '<dup>' into '<survivor>'"): `{"revision", "rebased", "problems", "touched", "survivor", "duplicates", "summary", "warnings", "ops"}`; 409 on stale `base_revision` |
| GET | `/api/v2/projects/<n>/devices/<id>/channels` | viewer | — | console channels of a device (§4.3.17): `{"device", "channels", "links", "source": "device"\|"overlay"\|"none", "pending", "labels": {port: {"in": {ch: label}, "out": {ch: label}}}, "summary": {"channels", "links", "by_kind", "by_link", "named", "sends", "dca_members"}}` — the persisted set when the device has `channels`, else the imports overlay's; `pending` = an import contribution exists that a (re-)apply would write; `labels` = Dante channel names from the overlay |
| POST | `/api/v2/projects/<n>/devices/<id>/channels/apply` | editor | — | persists the overlay's channels and links onto the device (`console.apply_ops`; `user` / `csv`-sourced entries are kept, everything else replaced) as one revision (source `import`, summary "Apply console channels to <name>"): `{"revision", "changed", "summary"}`; 404 `not_found` when the overlay has nothing for the device |
| GET | `/api/v2/projects/<n>/offline-manifest` | viewer | — | `{"urls": ["p/<n>", "p/<n>/rooms", "p/<n>/r/<room>", "p/<n>/r/<room>/patch", "p/<n>/d/<device>", …, "api/v2/projects/<n>", "api/v2/meta", <app shell assets>]}` (relative) |
| GET/POST/DELETE | `/api/v2/projects/<n>/shares[/<token>]` | editor | POST `{"label?", "expires?", "scope?": "all"\|"sop"}` | P1 `{"shares": [{"token", "label", "created", "expires", "by", "scope"}]}` / 201 `{"share": …, "url": "s/<token>/"}` / 204. `scope: "sop"` (400 `bad_enum` otherwise) limits the mirror to `/s/<token>/sop[/…]` and `/s/<token>/files/…`; other paths → 403 `share_scope`, the bare token opens the procedures index. |

### 5.7 Imports, files, floor plans

| Method | Path | Role | Request | Response / codes |
| --- | --- | --- | --- | --- |
| POST | `/api/v2/projects/<n>/imports?kind=&device=&room=&folder=` | editor | multipart files (+`X-Fathom`) | 201 `{"import": {…}, "summary": {…}, "revision"}`; 400 undetectable kind (files removed); 413 |
| DELETE | `/api/v2/projects/<n>/imports/<import_id>?delete_files=1` | editor | — | `{"revision"}` |
| GET | `/api/v2/projects/<n>/imports/<import_id>/inspect` | viewer | — | `{"kind", "summary"}` |
| POST | `/api/v2/projects/<n>/imports/preview?kind=&room=` | editor | multipart (one-shot importers, e.g. `csv`) | `{"kind", "ops": [...], "summary": {"create": n, "update": n, "skip": n}, "warnings": [str], "errors": [{"row", "column", "value", "message"}], "base_revision"}` — **no write** |
| GET | `/api/v2/projects/<n>/imports/templates/<kind>/<name>.csv` | viewer | — | `text/csv` attachment `fathom-<name>-template.csv`; 404 unknown importer/template (FR-IMP-12) |
| POST | `/api/v2/projects/<n>/files?device=&kind=` | editor | multipart (1..n files) | 201 `{"attachments": [{…}], "revision"}` (attachments appended by server-side ops) |
| GET | `/api/v2/projects/<n>/files/<att_id>/<filename>` | viewer | — | bytes; headers per FR-SEC-04/05 |
| DELETE | `/api/v2/projects/<n>/files/<att_id>` | editor | — | `{"revision"}` (removes entity + folder; also clears references: markers no, floor plans referencing it → 409 `in_use`) |
| POST | `/api/v2/projects/<n>/floorplans?room=&name=&page=` | editor | multipart (one file) | 201 `{"floorplan": {…}, "warnings": [str], "revision"}`; 415 `dwg_unsupported`/`unsupported_format`; 422 `pdf_unsupported` |
| POST | `/api/v2/projects/<n>/floorplans/<fp>/reconvert` | editor | `{"page?", "hidden_layers?"}` | P1 `{"floorplan", "revision"}` |
| GET | `/api/v2/projects/<n>/floorplans/<fp>/image?hide=L1,L2` | viewer | — | rendered image (SVG/PNG); `hide` only for SVG plans from DXF/Draw.io (cached in `files/<att>/cache`) |
| GET | `/api/v2/projects/<n>/floorplans/<fp>.svg` | viewer | — | plan + markers + legend (export) |

Markers, calibration, names, order and `hidden_layers` change through `/changes` ops on `floorplans`.

#### 5.7.5 Network discovery (FR-DISC)

| Method | Path | Role | Request | Response / codes |
| --- | --- | --- | --- | --- |
| GET | `/api/v2/projects/<n>/discovery/runs` | viewer | — | `{"runs": [run…], "active": id\|null, "sources": [{"id", "label", "mode", "maturity", "help", "sends", "needs", "fields", "available", "unavailable_reason", "settings"}], "capabilities": {"zeroconf", "zeroconf_version", "net_raw", "net_raw_message", "puresnmp", "puresnmp_version", "fixtures", "install_hint"}, "mode": "passive"}` (source fields also carry `default_enabled` and `targets`; `settings.<probe>.enabled` says whether an active source is on) |
| POST | `/api/v2/projects/<n>/discovery/runs` | editor | `{"window?": 10–300, "probes?": [id]}` | 202 `{"run": {"id", "status", "progress", "stage", "window", "probes", "mode": "passive"\|"active", "targets": {probe: [host]}, "started", "by", "log": [...]}}`; 409 `run_active` (`details.run`); 400 bad window/probe or no probe left to run (an active probe needs at least one host) |
| GET | `/api/v2/projects/<n>/discovery/runs/<rid>` | viewer | — | `{"run": {… "counts", "summaries", "errors", "finished"}}`; 404 |
| DELETE | `/api/v2/projects/<n>/discovery/runs/<rid>` | editor | — | `{"run": {…}}` (cancel requested; partial results are kept) |
| GET | `/api/v2/projects/<n>/discovery/runs/<rid>/findings` | viewer | — | `{"run", "entities": [{"id", "status", "label", "confidence", "level", "reasons", "sources", "macs", "ips", "match?", "proposed?", "interfaces", "connections"}], "connections": [{"id", "switch", "port", "peer", "methods", "confidence", "level", "flag", "cable?", "status"}], "rows": [cable-schedule columns], "networks": [...], "counts", "notes"}` |
| GET | `/api/v2/projects/<n>/discovery/runs/<rid>/diff` | viewer | `?against=<rid>` (optional; default: the previous completed run) | `{"run", "against": rid\|null, "candidates": [run brief…], "persisted": bool, "diff": {"run", "against", "computed", "new_devices": [entity summary…], "missing_devices", "moved": [{"label", "from": {switch, port…}, "to"}], "changed": [{"label", "field", "before", "after"}], "new_links": [{"switch", "port", "peer", "peer_port", "methods", "confidence", "level", "flag"}], "lost_links", "counts": {"new_devices", "missing_devices", "moved", "changed", "new_links", "lost_links", "unchanged", "paired", "entities", "previous_entities", "links", "previous_links", "changes"}}}`; 400 `against` not another completed run; 404 |
| POST | `/api/v2/projects/<n>/discovery/runs/<rid>/findings/promote` | editor | `{"entities": [id], "merge": {entity: device}, "templates?": {entity: template_id}, "connections": [id], "networks": [id], "ignore": {"entities", "connections", "networks"}, "unignore": {…}, "room?"}` (`templates` applies a library model to a new device the way Add gear does, or to a merge target that has no `template` yet) | `{"ops": n, "summary": {"devices", "merged", "cables", "networks", "ignored"}, "revision"}`; 400 unknown id / unpromotable |
| GET | `/api/v2/projects/<n>/discovery/settings` | viewer | — | `{"settings": {"window", "probes": {id: {"enabled", fields…, "<secret>_set", "<secret>_from_env", "<secret>_env"}}}, "sources", "limits": {"min_window", "max_window"}}` (no secret values) |
| PUT | `/api/v2/projects/<n>/discovery/settings` | editor | same shape; secret `null` keeps, `""` clears | `{"settings", "revision"}` |
| POST | `/api/v2/projects/<n>/discovery/test` | editor | `{"probe", "settings?"}` | `{"probe", "result": {"ok": bool, "message", …}}` (message redacted); 400 unknown probe |

Run ids are `run-YYYYMMDD-HHMMSS-xxxx`; runs live under `exports/discovery/<rid>/{run.json, raw/<probe>.json, findings.json, diff.json}` and the last 20 are kept. `POST …/builds` accepts `discovery: false` to leave the *Discovered connections* report section out (FR-DISC-12).

#### 5.7.4 Generic CSV one-shot importer headers

Header matching: case-insensitive, `common.norm_header`, synonyms in brackets. Cables CSV is detected when `from_device` [from, source device, start device] and `to_device` [to, destination device, end device] exist; console CSV when `console` [mixer, desk, console name] and `channel` [ch, console channel, input, bus] exist; devices CSV when a `name` [device, device name, label] column exists.

| Devices columns | Cables columns |
| --- | --- |
| `id`, `name`*, `kind` [type, category], `manufacturer` [make, brand], `model`, `template`, `room`, `location`, `system`, `status`, `code`, `serial` [serial number], `asset_tag` [asset, asset tag], `firmware`, `purchase_date`, `warranty_until` [warranty], `vendor`, `cost` [price, unit cost], `ip` [ip address, primary ip], `mac`, `vlan`, `hostname`, `rack`, `ru` [u, rack unit], `height` [ru height, size], `face`, `universe`, `address` [dmx address], `footprint`, `dmx_channel` [channel], `notes` [note, comments] | `id`, `tag` [cable id, cable, label], `from_device`*, `from_port` [from port, source port], `to_device`*, `to_port` [to port, destination port], `medium` [signal type, cable type?], `type` [cable type, product], `length` [len], `length_unit` [unit] (`m` default, `ft`, `in`, `cm`), `color` [colour], `channels`, `signal`, `status`, `note` [notes] |

Rows match existing entities by `id`, else devices by exact name (normalized) / cables by `tag`; matched → `merge` ops with only the non-empty cells; unmatched → `put` ops with new ids. Device `ip`/`mac`/`vlan`/`hostname` populate interface `primary`. `rack` matches a rack by id or name. Cable ports that do not exist are created on the device (`merge` of its `ports`, origin `user`, medium from the row). Unresolvable device names → error and row skipped.

Validation (FR-IMP-12) — a row with any problem is skipped and listed in `errors`: device `name` required (unless `id` matches) and unique in the file (normalized); `kind` must be a vocab kind (labels and `video switcher` / `video-switcher` spellings normalize) or a device type preset id / alias (FR-LIB-06, `generic_csv.kind_and_preset`; the column guide's allowed list and the "did you mean" suggestions include them); other values are row errors; `status` ∈ statuses (case-insensitive); `room` must match a room id or name; `ip` valid IPv4/IPv6; `mac` as `aa:bb:…`, `aa-bb-…`, `aabb.ccdd.eeff` or 12 hex digits; `vlan` 1–4094; `ru`/`height` 1–60; `face` front/rear; `universe` ≥ 1; `address`/`footprint` 1–512 with address + footprint − 1 ≤ 512; `cost` numeric; `purchase_date`/`warranty_until` `YYYY-MM-DD`. Cables: `from_device`/`to_device` required for new cables and must resolve; `tag` unique in the file; `medium` a vocab medium; `length` parseable; `channels` ≥ 1; `status` ∈ statuses. Unknown columns and extra cells are reported as warnings. The campus-demo sample ships `exports/csv/devices.csv` and `exports/csv/cables.csv`.

**Console table** (`console` template, *Console sends & DCAs*; §4.3.17) — one row per console channel: `console`*, `channel`*, `name` [channel name, new name], `sends` [send, send to, sends to, feeds, buses], `dca` [dcas, dca group, dca groups, vca], `mute` [mute group, mute groups, mutes], `note` [notes]. `console` is a device name or id that already has channels (persisted, or imported and not yet applied — the preview then builds the overlay and the resulting op persists the imported set together with the rows; the preview says so in `warnings`). `channel` and every list entry are resolved by `console.resolve_channels` against that console's channels: ids (`in-12`), console labels (`CH 12`, `ST IN 2`, `MIX 1`, `MATRIX 3` / `MTX 3`, `ST L`, `MONO`, `DCA 1`, `FX 1`), a bare number (`12` → `CH 12`; in the `dca` / `mute` column → that group), `ST` / `ST L/R` / `MAIN` → both sides of the stereo bus, `ST IN 2` → both sides, `AUX n` ↔ `MIX n` when the console has only one of them, or a channel's console name when unique (`Band` → the DCA named Band). Lists are separated by `;` `,` `|`; `MIX 1-4` expands to a range; an entry prefixed with `-` removes that link (`-MIX 3`). Rows **add** `send` links (`channel` → each bus, `source: csv`), `dca` and `mute` links (`channel` → group), rename (`name`) and annotate (`note`) the channel (`source: csv`); existing identical links of any source are left alone; nothing else is removed. Row errors (skipped): console not found, console without channels, channel not found (with the accepted forms), a DCA / mute group in the `channel` column, a send target that is not a bus, an unknown DCA / mute group. Ops: one `merge` per console with its full `channels` + `channel_links`; `summary.create` counts rows that added links, `update` rows that only removed or renamed, `skip` rows with errors or nothing to change (also listed in `warnings`). `console.MANUAL_SOURCES` makes the next import re-apply keep these entries. The template's example rows name the project's first console that has channels and its real first input / mix / DCA labels so the unedited file previews cleanly.

Device `kind` cells are normalized to an Appendix A.1 key when they spell a kind key or label (`Video switchers`, `video-switcher` → `video_switcher`). A cell that is not a vocabulary kind but names a device type preset (FR-LIB-06) by id, label or alias — `ups`, `pdu`, `network switch`, `copper patch panel`, `fibre patch panel`, `router`, `firewall`, `access point`, `server`, `nas`, `kvm`, `media converter`, `dante interface`, `stagebox`, `audio console`, `power amplifier`, `dsp`, `wireless mic receiver`, `iem transmitter`, `production switcher`, `ptz camera`, `decoder`, `lighting desk`, `dimmer pack`, `dmx gateway`, … (`GET /api/v2/presets` lists every id and alias) — resolves to the preset's kind and, for a **new** device without a `template` cell, to `template: <preset id>` so the device is created with the preset's ports and RU. Vocabulary kinds always win (`switch`, `projector`, `dmx node`, `lighting console` stay plain devices of that kind with no ports; use the preset id or a non-kind alias to get the ports); an explicit `template` cell wins over the preset; matched existing devices only get the kind. Anything else is a row error (FR-IMP-12) whose message lists the kinds and preset aliases.

### 5.8 Schedules, analysis, trace, search, QR

| Method | Path | Role | Query | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v2/projects/<n>/schedules/<kind>` | viewer | `room`, `state`, `discipline`, `format=json\|csv\|html` | `kind ∈ patch, cables, ip, dmx, bom, inventory, racks, labels`. JSON: `{"kind", "columns": [{"key", "label"}], "rows": [{…}], "problems": [Problem], "totals?": {…}}`; CSV: `text/csv` attachment `<n>-<kind>.csv` (UTF-8, header row = column labels, `\r\n` line endings as `csv` module default); `labels` supports only `format=html` (printable sheet) |
| GET | `/api/v2/projects/<n>/cables/tag-preview` | editor | `scope=missing\|all`, `pattern?` | `{"ops": [...], "count": int, "base_revision"}` |
| GET | `/api/v2/projects/<n>/racks/<rack>.svg` | viewer | `face=front\|rear` | SVG |
| GET | `/api/v2/projects/<n>/qr/<device>.svg` | viewer | `ecl=M`, `scale=4` | SVG; 409 `no_public_url` when no base URL can be determined |
| GET | `/api/v2/labels/presets` | viewer | — | `{"presets": [{"id", "label", "width_mm", "height_mm", "parts": [str], "continuous": bool}], "default": "m511-1x0.5"}` — Brady M511 cartridge sizes in cartridge order (FR-QR-03) |
| GET | `/api/v2/projects/<n>/labels/devices` | viewer | `preset=m511-1x0.5`, `format=html\|csv\|zip\|svg` (default `html`), `devices=<id,id>` (explicit list, order kept), `room=<id>`, `status=<installed\|planned\|spare\|retired>`, `png=0` (zip without PNGs) | `html`: the printable sheet (`text/html`, viewer-page CSP like `schedules/labels`); `csv`: `text/csv` attachment `device-labels.csv`; `zip`: `application/zip` attachment `device-labels-<preset>.zip` (README, CSV, one SVG and — with Chrome — one 300 dpi PNG per device); `svg`: one device's label (`image/svg+xml`, file CSP; needs exactly one id in `devices`, else 400 `one_device`). Default scope: every non-`auto` device, room then name. 400 `{"error": "bad_preset", "code": "bad_preset"}` for an unknown preset; 404 unknown room. QR URLs use the request's public base (`settings.public_url`, `FATHOM_PUBLIC_URL` or the request origin) and the project name (FR-QR-04) |
| GET | `/api/v2/projects/<n>/trace` | viewer | `from=<dev[:port]>` (also `dev:in-12`, `CL5 · CH 12`, `CL5 · Bass`, `Rio · Dante 6`, `rio:dante-primary#tx6`, §6.9.4), `to?`, `direction=up\|down` (when no `to`), `discipline?`, `max_depth=24`, `limit=50`, `dca=1?` (DCA membership as hops) | `{"paths": [{"hops": [{"device", "device_name", "port", "label", …channel-level keys §6.9.4}], "cables": [ids], "via": [str], "text", "incomplete?"}], "from": "<node ref>", "to": "<node ref>\|null"}`; the node refs it returns (`dev:@in-12`, `dev:@fx-1.A`, `dev:~REC 1`, `dev:port#rx17`) are accepted back in `from` / `to`; 400 unknown endpoint |
| GET | `/api/v2/projects/<n>/search` | viewer | `q`, `limit=20`, `kinds=device,port,…` | `{"hits": [Hit]}` (§5.11) |
| POST | `/api/v2/projects/<n>/assistant` | viewer | body §5.10 | answer §5.10 |

#### 5.8.2 Schedule columns (JSON `key` / CSV label)

| Kind | Columns (in order) |
| --- | --- |
| `patch` | `room` Room, `device` Device, `section` Section, `dir` Dir, `port` Port, `label` Label, `peer_device` Peer device, `peer_port` Peer port, `cable_tag` Cable, `medium` Medium, `source` Source |
| `cables` | `tag` Tag, `from_room` From room, `from_device` From device, `from_port` From port, `to_room` To room, `to_device` To device, `to_port` To port, `medium` Medium, `type` Type, `length` Length, `length_unit` Unit, `color` Color, `channels` Channels, `signal` Signal, `status` Status, `bundle` Bundle, `note` Note, `id` Id |
| `ip` | `room` Room, `device` Device, `interface` Interface, `role` Role, `ip` IP, `prefix` Prefix, `gateway` Gateway, `vlan` VLAN, `network` Network, `mac` MAC, `hostname` Hostname, `switch` Switch, `switch_port` Switch port, `protocol` Protocol, `dhcp` DHCP, `source` Source, `note` Note |
| `dmx` | `universe` Universe, `address` Address, `end` End, `footprint` Footprint, `device` Device, `room` Room, `mode` Mode, `channel` Console channel, `protocol` Protocol, `sacn_group` sACN group, `artnet` Art-Net (net:sub:uni), `source` Source |
| `bom` | `category` Category (discipline), `manufacturer` Manufacturer, `model` Model, `template` Template, `qty` Qty, `unit_cost` Unit cost, `extended` Extended, `currency` Currency, `planned` Planned, `installed` Installed, `spare` Spare, `retired` Retired; cable lines use `category = "cable"`, `model = "<medium> · <type>"`, `qty` = count, plus `length_total_m` Total length (m) |
| `inventory` | `id`, `name`, `room`, `location`, `kind`, `discipline`, `manufacturer`, `model`, `status`, `serial`, `asset_tag`, `firmware`, `purchase_date`, `warranty_until`, `vendor`, `cost`, `currency`, `po`, `rack`, `ru`, `ips` (semicolon-joined), `notes`, `condition`, `container` (container device name), `short_code` (`XXXX-XXXX`), then one `field:<key>` column per custom-field key in the doc (sorted; FR-INV-06..09) |
| `racks` | `rack` Rack, `room` Room, `units` Units, `face` Face, `u` U, `height` Height, `side` Side, `device` Device, `model` Model |

Device and port columns contain **names** (device `name`, port `label or name`) in CSV and both `*_id` and name keys in JSON rows (e.g. `device`, `device_id`, `port`, `port_id`).

### 5.9 Builds

| Method | Path | Role | Request | Response |
| --- | --- | --- | --- | --- |
| POST | `/api/v2/projects/<n>/builds` | editor | `{"pdf": false, "png": false, "state": "all", "rooms": null}` | 201 `{"build", "files": [relative paths], "url": "builds/<n>/<run>/index.html", "zip": "builds/<n>/<run>/<run>.zip"}`; 400 PDF/PNG without Chrome |
| GET | `/api/v2/projects/<n>/builds` | viewer | — | `{"builds": [{"name", "files", "created"}]}` (files recursive, relative) |
| DELETE | `/api/v2/projects/<n>/builds/<run>` | editor | — | `{"ok": true}` |
| GET | `/builds/<n>/<run>/<path>` | viewer (public with PUBLIC_VIEW) | — | file; `<path>` may contain `/`, each segment must match `_RUN_RE`; containment check |

Build package (run folder):

```text
index.html                     default-room map (v0.2 compatible)
diagram.svg                    default-room map SVG
patch-sheet.csv                v0.2 patch sheet (default room)
project.json                   normalized v2 doc
build-notes.txt                notes (merge notes, skipped QR, missing rasterizer…)
rooms/<room>/index.html        per-room map ; rooms/<room>/diagram.svg ; rooms/<room>/patch.html (read-only patch table)
rooms/index.html               room index
devices/<device>.html          device pages
patch-table.csv  cable-schedule.csv  cable-labels.html  ip-schedule.csv  dmx-schedule.csv  bom.csv  inventory.csv
device-labels.html             device labels at true size for the Brady M511 (default preset m511-1x0.5, every device in scope; FR-QR-04; linked from the build nav)
console-channels.csv           (only when a console has channels, §4.3.17: Console, Group, Channel, Name, Fed by, Goes to, DCA / mute, Members, Source — `console.console_schedule`)
racks/<rack>-front.svg  racks/<rack>-rear.svg
floorplans/<floorplan>.svg
qr/<device>.svg                (when a public URL is known)
report.html                    (P1) print-oriented compilation ; report.pdf (optional, Chrome)
diagram.png                    (optional, Chrome)
<run>.zip                      everything above under <run>/
```

All internal links in a build are relative so the folder works from `file://` and from `/builds/…`.

### 5.10 Assistant

Request:

```json
{"question": "House sound is fine, but the livestream has no audio.", "room": "main", "use_llm": true,
 "history": [{"role": "user", "text": "…"}, {"role": "assistant", "text": "…"}]}
```

Response (normative shape; values for the fixture):

```json
{
  "question": "House sound is fine, but the livestream has no audio.",
  "intent": {"type": "troubleshoot", "symptom": "no_audio", "discipline": "audio",
             "targets": ["restream"], "working": ["main-speakers", "sub-x2"], "room": "main"},
  "summary": "Your stream audio takes its own path: **Audio Rack 1 · Stream** → **ATEM Mini · Stream** → USB Stream Out → Restream.",
  "paths": [{"hops": [{"device": "audio-rack-1", "port": "analog-out-4", "label": "Audio Rack 1 · Stream"},
                      {"device": "atem-mini", "port": "analog-in-1", "label": "ATEM Mini · Stream"},
                      {"device": "atem-mini", "port": "usb-out-1", "label": "USB Stream Out"},
                      {"device": "restream", "port": "usb-in-1", "label": "Restream"}],
             "cables": ["c-0011", "c-0015"],
             "text": "Audio Rack 1 · Stream → ATEM Mini · Stream → USB Stream Out → Restream",
             "role": "suspect"}],
  "branch": {"device": "audio-rack-1", "reason": "Shared with Main Speakers - L/R, which works"},
  "suspects": [{"device": "audio-rack-1", "port": "analog-out-4"}, {"device": "atem-mini", "port": "analog-in-1"},
               {"device": "atem-mini", "port": "usb-out-1"}, {"device": "restream", "port": "usb-in-1"}],
  "checks": [
    {"n": 1, "text": "Confirm the **Stream** output is up on Audio Rack 1 — it feeds ATEM Mini separately from Main Speakers - L/R.", "device": "audio-rack-1", "port": "analog-out-4", "source": "kinds:stage_io/output-up"},
    {"n": 2, "text": "On the ATEM Mini's Audio tab, make sure the **Stream** input is set to ON, not AFV (inputs default to audio-follow-video).", "device": "atem-mini", "port": "analog-in-1", "source": "template:blackmagic-atem-mini-pro/audio-on"},
    {"n": 3, "text": "Check levels on the ATEM Mini's Program meter before it reaches Restream.", "device": "atem-mini", "port": "usb-out-1", "source": "kinds:video_switcher/program-meter"}
  ],
  "notes": ["HDMI In 1 on ATEM Mini also carries embedded audio, but its source (Stage Box 1 · Video Display) is not patched."],
  "suggestion": {"text": "Add note \"Stream feed: Audio Rack 1 → ATEM Mini · check Audio tab\" to ATEM Mini · Stream",
                 "ops": [{"op": "merge", "coll": "devices", "id": "atem-mini", "value": {"ports": ["…full ports array with analog-in-1.note set…"]}}],
                 "base_revision": 1},
  "confidence": "high",
  "unresolved": [],
  "llm": {"used": false}
}
```

Rules (normative where tested): `summary` uses `**bold**` only (UI escapes HTML then renders bold); `checks` ≤ 8, numbered from 1; `suggestion` null when nothing useful; `confidence` = `high` (target + working resolved and one suspect path), `medium` (target resolved), `low` otherwise; `llm` = `{"used": true, "model", "text"}` | `{"used": false, "error?": str}`. Errors: 400 empty question; never 5xx because of the LLM.

### 5.11 Search hit shape

```json
{"kind": "device|port|cable|interface|network|room|rack|floorplan|attachment|page",
 "id": "atem-mini", "device": "atem-mini", "port": null,
 "title": "ATEM Mini", "subtitle": "Blackmagic Design ATEM Mini Pro · Main Auditorium",
 "room": "main", "score": 100, "match": "name", "status": "installed"}
```

For ports `id` = `<device>:<port>`; cables `id` = cable id; interfaces `id` = `<device>/<interface>`; networks `id` = network id (`device`/`port` null, `room` `""`, subtitle `VLAN <n> · <subnet>` without missing parts; matches name, id, vlan, subnet, protocol); pages `id` = slug (matches title, slug, summary, tags, headings and body text). `status` is always present: the device status for devices, the page status for pages, `""` for other kinds. Kinds sort per FR-SRCH-04 (`fathom.search.KIND_ORDER`). A whole query is matched against each field value, so `vlan 20` finds no network; offline (`model-core.searchLocal`) there are no page hits.

### 5.12 v1 endpoints (kept)

| v1 route | v2 behavior |
| --- | --- |
| `GET /` | serves new `static/app.html` (SPA); `?p=<name>` handled client-side |
| `GET /healthz` | unchanged `{"ok": true, "version"}` |
| `GET /api/meta` | v1 keys (`version, kinds, media, brands, import_kinds, default_columns, samples, chrome, auth, public_view, max_upload_mb`) with new vocab content |
| `GET /api/projects` | unchanged shape (`name, org, title, cards, updated, builds`); `cards` = device count |
| `POST /api/projects` | unchanged; creates a v2 project |
| `GET /api/projects/<n>` | `{"name", "data": schema.to_v1_dict(doc), "problems": [str…], "exports", "builds", "schema": 2, "v1_expressible": bool}` where `to_v1_dict` = `flow_project(doc).to_dict()` |
| `PUT /api/projects/<n>` | if stored doc is v1-expressible: `doc = migrate(body)` keeping `imports` if absent (v0.2 rule) → saved as a new revision (source `put`, author, no If-Match needed); else 409 `v2_required` |
| `DELETE /api/projects/<n>?confirm=` | admin; unchanged |
| `POST /api/projects/<n>/imports?kind=&node=&folder=` | same as v2 import with `device=node`; response v1 shape `{"ok", "kind", "path", "summary"}` |
| `DELETE /api/projects/<n>/imports?path=&delete=1` | removes the import with that path |
| `GET /api/projects/<n>/inspect?path=&kind=` | unchanged |
| `GET /api/projects/<n>/trace?from=&to=` | unchanged (card-level, `describe_path` strings) |
| `POST /api/projects/<n>/build`, `GET …/builds`, `DELETE …/builds/<run>` | unchanged shapes (build now includes v2 extras) |
| `GET /p/<n>`, `/p/<n>/diagram.svg`, `/p/<n>/patch-sheet.csv`, `/p/<n>/project.json` | unchanged (default room); `project.json` returns the v2 doc |
| `GET /builds/<n>/<run>/<file>` | unchanged (now also nested paths) |

### 5.13 Viewer, static and PWA routes

| Method | Path | Role | Response |
| --- | --- | --- | --- |
| GET | `/p/<n>/rooms` | viewer | room index HTML |
| GET | `/p/<n>/r/<room>` | viewer | room map HTML (`render_html` with nav) |
| GET | `/p/<n>/r/<room>/diagram.svg` | viewer | room map SVG |
| GET | `/p/<n>/r/<room>/patch` | viewer | read-only patch table HTML |
| GET | `/p/<n>/d/<device>` | viewer | device page HTML |
| GET | `/c/<code>` | viewer | the short link printed on device labels (FR-INV-09; `<code>` = `XXXX-XXXX` or `XXXXXXXX`, any case): 302 to `/#/<project>//devices/<device>` when the caller is an editor or admin of that project, else to `/p/<project>/d/<device>`; unknown code → 404 HTML page |
| GET | `/p/<n>/sop` | viewer | published procedures index (`render_html.render_sop_index`): tree order, kind / review-due badges, ≥44 px rows |
| GET | `/p/<n>/sop/<slug>` | viewer | chrome-free SOP page (`render_html.render_sop_page`, §5.15): published pages only (drafts/archived → 404), the pages-API payload rendered with relative refs (`../d/<id>`, `../r/<id>`, `../sop/<slug>`, `../files/<att>/<name>`), phone-first (17 px body, sticky "Applies to", collapsible contents, tap-to-toggle checklist kept in `sessionStorage` under the app's key, tap-to-zoom images, prev/next, Print button), no edit controls, inline CSS/JS only (`static/css/sop.css` is inlined). Through a `scope: "sop"` share link device/room refs render as plain chips. |
| GET | `/p/<n>/files/<att>/<filename>` | viewer | attachment (same as `/api/v2/…/files/…`) so share links can mirror images embedded in pages |
| GET | `/s/<token>/…` | public (valid token) | P1 mirror of `/p/<project>/…` read-only; honours the share `scope` (§5.6) |
| GET | `/static/<path>` | public | files under `fathom/static/` with extensions `.html .js .css .json .svg .png .webmanifest .txt`; `.js` served as `text/javascript; charset=utf-8`; containment check; `dev/` harness files served only when `FATHOM_DEV=1` or the request comes from loopback |
| GET | `/sw.js` | public | `fathom/static/sw.js`, `Service-Worker-Allowed: /` (scope = app root) |
| GET | `/manifest.webmanifest` | public | `application/manifest+json` |
| GET | `/favicon.ico`, `/apple-touch-icon.png` | public | icons from `fathom/static/icons/` |
| GET | `/api/openapi.json` | public | OpenAPI 3.1 |
| GET | `/api/docs` | public | HTML endpoint reference |

### 5.14 OpenAPI

`openapi.build_spec(routes, version) -> dict`: `openapi: "3.1.0"`, `info {title: "Fathom API", version}`, `servers: [{"url": "./"}]`, `components.securitySchemes {basic: http basic, session: apiKey cookie fathom_session}`, `components.schemas` (`Doc` → `$ref` to `/api/v2/schema.json`, `Op`, `Problem`, `Hit`, `Answer`, `Error`, `Floorplan`, `Attachment`, `Import`, `User`, `Page`, `PagePreview`, `PageMove`), and one `paths` entry per registered route (path params converted from regex groups to `{name}`), each with `summary`, `tags`, `x-fathom-role`, `requestBody` (when declared) and `responses` including the error codes of §5.1. `/api/docs` renders a table of method/path/role/summary grouped by tag.

### 5.15 SOP pages (`fathom/markdown.py`, server section "SOP pages")

Pages are stored in `pages[]` (§4.3.15) and edited like any collection (`/changes` ops; the app commits `put` ops so undo, offline queueing and history work unchanged). The API adds page-shaped reads and conveniences. Rendering happens **only on the server**: `markdown.render(text, resolver) -> {html, toc, refs, missing, tasks}` implements a stdlib Markdown subset — ATX headings (ids `h-<slug>`), paragraphs, hard breaks, `**bold**`/`*em*`/`~~del~~`/`` `code` ``, fenced code, nested ordered/unordered lists, task lists (`- [ ]` → `<li class="md-task"><label><input type="checkbox" data-task="n">…`), GFM tables (wrapped in `<div class="md-table">`), blockquotes, callouts `> [!NOTE|TIP|IMPORTANT|WARNING|CAUTION] title`, rules, links, bare/angle autolinks, images, and Fathom refs `[[device:<id>|label]]`, `[[room:<id>]]`, `[[page:<slug>]]` plus `![alt](att:<attachment id>)` images. Raw HTML is always escaped; the output passes through an allow-list sanitizer (`markdown.sanitize`) that drops scripts, event handlers, `style`, non-checkbox inputs and any `href`/`src` whose scheme is not http(s)/mailto/tel/relative (`markdown.safe_url`). Unresolved refs render as `<span class="md-missing" data-ref="kind:id">` and are listed in `missing`.

| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| GET | `/api/v2/projects/{name}/pages` | viewer | `{pages: [summary…], revision}` sorted by parent then `order`. Filters `?device=`, `?room=` (backlinks: explicit lists ∪ body refs), `?status=`, `?kind=`. Summary = page fields without `body` plus `summary`, `children` (count). |
| POST | `/api/v2/projects/{name}/pages/preview` | editor | `{body}` → `render()` result (1 MB cap → 413). |
| GET | `/api/v2/projects/{name}/pages/{slug}` | viewer | `{page, html, toc, tasks, missing, links: {devices: [{id,name,room,kind}], rooms, pages}, backlinks: [{slug,title}], breadcrumbs, children, prev, next, revision}`. `prev`/`next` are siblings in `order`. |
| PUT | `/api/v2/projects/{name}/pages/{slug}` | editor | Upsert: body carries page fields (not `id`). Creates (201) with `pg-` id, `created`, `owner`, `status: draft`, `kind: sop`, `order` = last sibling + 1; else 200. Optional `base_revision` → conflict semantics of `/changes`; otherwise a server op. Errors: 400 `bad_slug`/`missing_field`/`bad_enum`/`bad_type`/`dangling_ref`/`page_cycle`, 409 `duplicate_slug`. Returns the GET payload + `problems`; `ETag`. |
| DELETE | `/api/v2/projects/{name}/pages/{slug}` | editor | A page with children is archived (`status: archived`), a leaf is removed. `{archived, revision}`. |
| POST | `/api/v2/projects/{name}/pages/{slug}/move` | editor | `{parent, before, order}`; cycle check; siblings renumbered 1..n. |
| GET | `/api/v2/projects/{name}/pages/{slug}/versions` | viewer | `{versions: [{revision, time, author, summary, source}]}` — the history entries whose touched refs include `pages/<id>`, newest first. |
| GET | `/api/v2/projects/{name}/pages/{slug}/versions/{rev}` | viewer | The page as it was at `rev`, rendered (GET shape + `current_revision`). |
| POST | `/api/v2/projects/{name}/pages/{slug}/restore/{rev}` | editor | Puts the page content of `rev` back as a new revision, keeping today's `id`, `slug`, `parent`, `order`, `created`. |
| GET | `/api/v2/projects/{name}/qr/page/{slug}.svg` | viewer | QR code (`?ecl=`, `?scale=`) for the public page: `<public base>/p/<n>/sop/<slug>`, or `<public base>/s/<token>/sop/<slug>` with `?share=<token>` (404 `share_missing` if the token is not this project's). Public base as FR-EXP-04 (409 `no_public_url` when unknown). Only published pages (409 `not_published`). |
| GET | `/api/v2/projects/{name}/qr/pages.html` | viewer | Printable QR sheet (`render_html.render_sop_qr_sheet`): one label (code, kind, title, URL) per published page, tree order; `?room=<id>` keeps pages that apply to the room (explicit `rooms` ∪ body refs; 404 for an unknown room); `?share=<token>` as above. |

Ref hrefs produced by the server are fallbacks for chrome-less pages (`p/<project>/d/<device>`, `p/<project>/r/<room>`, `#/<project>/*/sop?page=<slug>`, `api/v2/projects/<project>/files/<att>/<name>`); the app intercepts clicks on `a[data-ref]` and opens the inspector / navigates instead. A resolver may also return `{"href": "", "label"}` for a ref that is known but not navigable (procedures-only share links): it renders as `<span class="md-ref md-ref-<kind>" data-ref=…>` without `md-missing`. `render_html.sop_link_resolver(doc, device=, room=, page=, attachment=)` builds resolvers for the public pages (relative hrefs) and for builds (`devices/<id>.html`, `rooms/<id>/index.html`, `#sop-<slug>`, `files/<att>/<name>`).

**Report section.** `export.write_build` adds a "Standard operating procedures" section to `report.html` (hence `report.pdf`) when the project has published pages: `render_html.render_sop_report_section` renders them in tree order (`render_html.sop_tree`), each page as `<article class="sop-report-page" id="sop-<slug>">` starting on a new printed page with title, kind, "Applies to", review-due / updated line, summary and the `.md` body (checkboxes unticked, `disabled` look). Images referenced as `att:` are copied to `files/<att>/<name>` in the run folder; `static/css/sop.css` is inlined via `render_report(extra_css=…)`. A build scoped to some rooms keeps only pages that apply to those rooms or to no room. Drafts and archived pages never appear.

### 5.16 Problem reports, checklist completion, offline bundle (server section "problem reports")

Every SOP page — in the app, under `/p/<n>/sop/<slug>` and through share links — has a **Report a problem** button opening a phone-first bottom sheet (`render_html._report_sheet` + `SOP_REPORT_JS` on server pages; `views-sop.js reportSheet` in the app): the devices the page applies to (pre-selected when there is exactly one), a short description, an optional name (anonymous channels), an optional photo (`<input type=file accept=image/* capture=environment>` → the phone camera), and for editors in the app an optional new device status. The sheet posts `multipart/form-data` (or JSON) and always creates a `problems[]` entry (§4.3.16); when `settings.problem_email` is set it also offers a `mailto:` built from the form, which is the only channel in the offline bundle and the fallback when the POST fails.

| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| POST | `/api/v2/projects/{name}/problems` | viewer | Body `ProblemReport` (`text`, `device`, `page`, `name`, `device_status`, `kind`) as JSON or multipart with a `photo` part (images only, 400 `bad_type`). 201 `{problem, noted, revision}` (+ `forwarded` for suggestions). Channel `app`. For **editor+** callers with a `device`, the device additionally gets a timestamped line appended to `note` (`[YYYY-MM-DD HH:MM user] Problem: <text>`, `Suggestion: <text>` for suggestions) and, with `device_status`, a new `status` (§4.3.5 enum, 400 `bad_enum`; ignored for suggestions); `noted: true`. 400 `missing_field` (empty text), `dangling_ref` (unknown device/page), `bad_enum` (unknown `kind`). One revision, history source `problems`. |
| GET | `/api/v2/projects/{name}/problems` | viewer | `{problems: [...], open, open_suggestions, revision}`, newest first; filters `?status=`, `?device=`, `?page=`, `?kind=problem\|suggestion`. `open` counts open problems (entries without a `kind` count as problems), `open_suggestions` open suggestions. Each entry adds `device_name`, `page_title`, `photo` (relative file URL) when resolvable. |
| GET | `/api/v2/suggestions` | admin | Server-wide `{items: [{project, …problem entry…}]}` of every `kind: suggestion` entry across live (non-trashed) projects, newest first. |
| PATCH | `/api/v2/projects/{name}/problems/{pid}` | editor | Body `ProblemPatch` `{status, note}`; `resolved` sets `resolved`/`resolved_by`, `open` clears them. 404 unknown, 400 `bad_enum`. |
| POST | `/p/{name}/problems` | viewer | Same as the API POST, channel `public`; never touches the device (an anonymous or viewer channel). Reporter = typed `name`, else the login (not the implicit local admin), else `anonymous`. |
| POST | `/s/{token}/problems` | public | Same through a share link (any scope), channel `share`. 404 for unknown tokens. |
| POST | `/api/v2/projects/{name}/pages/{slug}/complete` | editor | Appends `{at, by}` to `page.completions` (last 20 kept). `{completion, completions, revision}`. |
| GET | `/api/v2/projects/{name}/sop/bundle.zip` | editor | `export.sop_bundle_zip`: standalone offline copy of the **published** pages (`<project>-procedures/index.html`, `pages/<slug>.html`, `files/<att>/<name>` for embedded images). The same renderers as the public pages with CSS/JS inlined, no manifest/service worker (works from `file://`), relative page links (`page_href`), device/room chips as plain text, an "Offline copy from <stamp>" banner, sessionStorage checklists, and the report sheet as mailto-only when `problem_email` is set. CLI: `fathom sop-bundle <project> [-o out.zip | -o folder]`. |

**Suggest an improvement (FR-USER-13).** A problem report with `kind: "suggestion"` (stored on the entry; absent or `"problem"` = a problem) is an improvement idea rather than a fault: same storage, resolve / reopen and photo handling, but the device status is never changed and the note line reads `Suggestion:`. When `settings.suggest_url` (http(s), validated) or the env `FATHOM_SUGGEST_URL` is set, the server additionally POSTs `{"project", "kind", "text", "name", "device", "page", "url"}` as JSON (`urllib.request`, 5 s timeout) to that URL after the report is stored — `url` is the public link to the device, the page or the project (`settings.public_url` / `FATHOM_PUBLIC_URL` / request origin). Forward errors are logged and ignored; the response says `"forwarded": true|false`. Admins see every suggestion at `GET /api/v2/suggestions`.

**App surfaces.** `views-sop.js`: the page has the report button under the body and in the ⋯ menu; the tree head shows an "N open" badge and a ⋯ menu with **Problems** (list view `#/<p>/<room>/sop?problems=1`: open first, device / page chips, photo, Resolve / Reopen for editors) and **Download offline bundle** (editors); the page menu adds **Mark complete**, **Reset checklist**, **Download offline bundle** and, for archived pages, **Restore page**. Checklist progress reads "n of m done"; **Mark complete** ticks everything and, for editors, calls `/complete` (the footer then shows "Last completed <date> by <user>"); for viewers and on public pages it is session-only (`sessionStorage` key `fathom.sop.done.<project>.<slug>`, shown as "Marked complete at <time> on this device"). `inspector.js`: a device with open reports shows a red "⚠ N open" badge in its header (tap → the **Problems** section, which lists the device's reports with Resolve / Reopen) and hides archived pages from the "Procedures" section for read-only users. Settings (`views-admin.js`) exposes `problem_email`.

**Starter templates and review badges (app).** `views-sop.js` offers templates on page create (System power-up, System shut-down, Troubleshooting: no audio, Troubleshooting: no video, Weekly checks); when the page is started from a device the `{{device}}` placeholders become `[[device:<id>]]`. `reviewState(page)` → `"overdue"` / `"soon"` (≤30 days) drives the `sop-badge-due` / `sop-badge-soon` badges in the tree, page header and server-rendered pages. The page menu has Print (`window.print()`, print CSS in `sop.css`) and QR label (dialog: code, link choice — project viewer or a share link, "New procedures-only link" creating a `scope: "sop"` share, URL, Open SVG / Open public page, QR sheet per room); the editor topbar has the same QR label action for published pages.

---

## 6. Frontend module contracts

### 6.1 Conventions

- Files live under `fathom/static/`: `app.html`, `login.html`, `js/*.js`, `css/*.css`, `icons/*`, `dev/*` (harnesses), `manifest.webmanifest`, `sw.js`. `fathom/static/js/package.json` = `{"type": "module"}` so Node treats `js/*.js` as ES modules.
- Plain ES modules (`import`/`export`), ES2018 syntax only (§2.3 item 9), no third-party code, no build step, no inline event-handler attributes (CSP). Relative imports with explicit `.js` extensions.
- **`*-core.js` modules and `model-core.js` are pure**: no access to `window`, `document`, `localStorage`, `fetch` or timers at import time or in exported functions (they may accept callbacks). They MUST import and run in Node ≥ 18 (`node --test tests/js`). DOM modules may import cores, never the reverse.
- DOM modules render into the element they are given, never query outside it (except `#fathom-live` for announcements and `document` for global key listeners they add/remove in `mount`/`destroy`).
- CSS: each unit owns its CSS file; class names prefixed (`pv-` patch view, `fp-` floor plan, `rk-` rack, `sch-` schedules, `inv-` inventory, `app-`/`pt-`/`ins-`/`ast-` shell; shared components §6.13: `ex-` explorer, `eh-` entity header, `dt-` DataTable, `dr-` drawer, `sr-` search, `hm-` home, `fb-` feedback, `wz-` wizard; pages: `pd-` device, `pr-` room, `rp-` rack; also `adm-` admin, `disc-` discovery, `sop-` SOPs, `trace-` trace drawer). Shared CSS variables are defined only in `css/app.css` (`:root{--bg…}` as FR-UX-08 plus `--discipline-<key>` colors injected at runtime from vocab by `app.js`).
- Loading: `app.html` loads `css/app.css` and `<script type="module" src="static/js/app.js">`; views and their CSS are loaded lazily by `app.js` (`import()` + `<link rel=stylesheet>` added once).

### 6.2 `js/model-core.js` (W5) — doc helpers, ops, store

```js
export const COLLECTIONS = ['venues','rooms','systems','locations','racks','networks','devices','cables','bundles','floorplans','attachments','templates','imports'];
export const ROOTS = ['meta', 'settings', 'media'];

// identifiers
export function slug(text) {}                       // identical to Python fathom.model.slug for ASCII
export function newId(prefix, taken, base) {}       // base ? dedupe(slug(base)) : prefix + '-' + 8 random [a-z0-9]; taken: Set|Array|Object
export function portRef(device, port) {}            // "dev:port" | "dev"
export function parsePortRef(ref) {}                // -> {device, port|null}

// indexing & lookup
export function indexDoc(doc) {}                    // -> Index {byId:{coll:{id:entity}}, ports:{dev:{port:Port}}, cablesByDevice:{dev:[Cable]}, cablesByPort:{'dev:port':[Cable]}, devicesByRoom:{room:[Device]}}
export function devicePorts(device) {}              // always an array
export function portLabel(port) {}                  // label || name || id
export function deviceTitle(device) {}              // name + ' ×count' + ' suffix'
export function disciplineOf(device, vocab) {}
export function mediumInfo(medium, vocab) {}        // vocab.media[medium] || vocab.media.other
export function carries(medium, vocab) {}           // string[]
export function expandPortGroups(groups, opts) {}   // §4.4.3; opts.v1 boolean

// ops (§4.9) — pure, never mutate inputs
export function mergePatch(target, patch) {}
export function applyOps(doc, ops) {}               // -> {doc, inverse, touched:string[]}
export function invertOps(doc, ops) {}
export function diffDocs(a, b) {}

// editing helpers -> ops arrays
export function canConnect(doc, from, to, vocab) {} // -> {ok, level:'ok'|'warn'|'error', code, reason}
export function connectOps(doc, from, to, opts, vocab) {}     // opts {medium, tag, type, length_m, id}
export function disconnectOps(doc, cableId) {}
export function repatchOps(doc, cableId, end, target) {}      // end 'from'|'to'
export function deleteDeviceOps(doc, deviceId) {}             // device + its cables + markers + extra cards
export function duplicateDeviceOps(doc, deviceId, opts) {}    // -> {ops, id}; copies ports, not cables; offsets patch by +24,+24
export function renameOps(doc, ref, value) {}                 // ref {coll:'devices', id, port?}: device name or port label
export function addDeviceFromTemplateOps(doc, template, opts) {} // opts {room, name, x, y, id} -> {ops, id}
export function setPortsOps(doc, deviceId, ports) {}

// filtering & search
export function filterDevices(doc, filter, vocab) {}  // filter {room ('*' all), disciplines:[], statuses:[], state, query, system}
export function searchLocal(doc, q, limit) {}         // -> Hit[] (§5.11), ranking FR-SRCH-04
export function validateLocal(doc, vocab) {}          // subset of §4.7: dangling refs, bad_direction, port_overuse, medium_*
export function formatLength(m, units) {}             // "5 m" / "16.4 ft"

// viewport math (used by patch view and floor plan)
export const viewport = {
  fit(bounds, size, margin) {},          // -> {x, y, k}
  zoomAt(view, pt, factor, min, max) {}, // keeps pt fixed
  screenToWorld(view, pt) {}, worldToScreen(view, pt) {},
  clampK(k, min, max) {},
};

// store
export function createStore({doc, vocab, readOnly, overlay, room}) {}  // -> Store
```

**Store** (DOM-free, extends `EventTarget`; Node ≥ 18 has `EventTarget`/`CustomEvent`-compatible `Event` — use `new Event(type)` + a `detail` property for Node compatibility):

| Member | Description |
| --- | --- |
| `doc`, `vocab`, `overlay`, `room`, `selection`, `filter`, `readOnly`, `revision` | current state (read-only properties) |
| `index` | lazily rebuilt `indexDoc(doc)` (invalidated on change) |
| `commit(ops, label)` | if read-only → throws `ReadOnlyError`; else `applyOps`, push `{label, ops, inverse}` on the undo stack (cap 200), clear redo, emit `doc` `{ops, inverse, source: 'local', label}`; returns the new doc |
| `applyRemote(ops, source)` | apply without touching undo (source `remote`/`load`), emit `doc` |
| `replaceDoc(doc, revision, source)` | load a whole doc (clears undo), emit `doc` `{source: 'load'}` |
| `undo()`, `redo()`, `canUndo`, `canRedo`, `undoLabel`, `redoLabel` | undo applies the inverse as a commit with source `undo`/`redo` (these ops ARE sent to the server) |
| `select(sel)` | `sel = {type: 'device'|'port'|'cable'|'rack'|'floorplan'|'marker'|'bundle', id, device?, port?, floorplan?}` or null; emits `selection` |
| `highlight(h)` | `{devices:[], ports:['dev:port'], cables:[], source}` or null; emits `highlight` |
| `setFilter(partial)`, `setRoom(id)`, `setOverlay(o)`, `setReadOnly(b)`, `setRevision(n)` | emit `filter`, `room`, `overlay`, `mode`, `revision` |

Events (`store.addEventListener(type, e => e.detail)`): `doc`, `selection`, `highlight`, `filter`, `room`, `overlay`, `mode`, `revision`, `saving` (`{state: 'idle'|'pending'|'saving'|'saved'|'offline'|'conflict'|'error', pending: n, revision, error?, conflicts?}` — emitted by the shell's change queue through the store).

### 6.3 `js/api.js` (W5)

```js
export class ApiError extends Error {}   // .status, .code, .details
export function createApi({base = '', fetchImpl} = {}) {
  return {
    meta, session, login(username, password), logout,
    listProjects, createProject({name, template, org}), deleteProject(name, {purge}),   // ?confirm=<name>[&purge=1]
    listTrash(), restoreTrash(name), purgeTrash(name),   // GET/POST …/restore/DELETE api/v2/trash[/<name>] (P1A)
    lookupCode(code), codeLink(code),     // GET api/v2/codes/<XXXXXXXX>; absolute URL for /c/<XXXX-XXXX>
    labelPresets(), deviceLabelsUrl(name, params),       // P1B label endpoints
    getProject(name),                     // -> {doc, revision, problems, role, etag}
    putProject(name, doc, baseRevision, summary),
    postChanges(name, baseRevision, ops, summary),   // -> {revision, rebased, problems, touched}
    overlay(name), offlineManifest(name),
    history(name, {limit, before}), historyDoc(name, rev), historyDiff(name, rev, against), restore(name, rev, baseRevision),
    upload(name, target, files, params),  // target 'imports'|'files'|'floorplans'; FormData + X-Fathom
    importPreview(name, files, params), deleteImport(name, id, deleteFiles), inspectImport(name, id),
    schedule(name, kind, params), scheduleUrl(name, kind, params),   // url for CSV/HTML downloads
    tagPreview(name, scope, pattern), trace(name, params), search(name, q, opts), ask(name, payload),
    qrUrl(name, device), rackSvgUrl(name, rack, face), floorplanImageUrl(name, fp, hide), fileUrl(name, att),
    builds(name), build(name, opts), deleteBuild(name, run),
    library(params), template(id, project), saveTemplate(t), deleteTemplate(id),
    users(), createUser(u), updateUser(username, patch), deleteUser(username), changePassword(old, nw),
    shares(name), createShare(name, opts), deleteShare(name, token),
  };
}
export class ChangeQueue extends EventTarget {
  constructor({api, project, store, debounceMs = 600, maxBatch = 200, storage /* localStorage-like or null */}) {}
  enqueue(ops, label) {}   // called by the shell on store 'doc' events with source local|undo|redo
  flush() {}               // -> Promise; ⌘S
  get pending() {}
  // emits 'state' {state, pending, revision, error, conflicts}
}
```

Rules: every request sends `X-Fathom: 1` and `Accept: application/json`; JSON bodies `Content-Type: application/json`; non-2xx → `ApiError` from the error body. `ChangeQueue` batches ops (debounce 600 ms, max 200 per request), sends `postChanges` with the last known revision, updates the store revision on success, keeps order, retries network errors with backoff 1, 2, 5, 10, 30 s while emitting `offline`, persists unsent ops to `storage["fathom.pending.<project>"]` (JSON) and restores them on startup (FR-MOB-08). On 409 it emits `conflict` with `details.conflicts` and pauses until the shell calls `resolveConflict('reload'|'keep')`.

### 6.4 `js/app.js` (W5, SHELL) — shell, router, view contract

Exports for harnesses/tests: `export function boot(root, {api})` (called by app.html; `api` defaults to `createApi({base: <app root>})`), `bootLogin()` (login.html), `bootHarness(name)`, `export const VIEWS` (registry), `export function makeCtx(store, extras)`, `ensureCss(file | file[])` (adds each `<link rel=stylesheet>` once; resolves on load or error), `markRendered()`, `announce(text)` (`#fathom-live`), `toast(message, level)`, `openDialog(o)`, `confirmDialog(message, opts)`, `promptDialog(message, value, opts)`, the legacy router wrappers `parseHash(hash)` → `{project, room, view, params: URLSearchParams}` and `buildHash(project, room, view, params)` (= `router-core.legacyHash`; `views-sop.js` uses both), and re-exports `h`, `esc` (`dom.js`), `selToString`, `selFromString` (`router-core.js`).

**View registry** (`VIEWS[key] = {label, module, export, css}`; `css` is loaded with `ensureCss` before the module mounts; `PAGE_CSS` = `entity-header.css`, `datatable.css`, `explorer.css`; `ADMIN_CSS` = `datatable.css`, `admin.css`). The shell always loads `BOOT_CSS` = `drawer.css`, `inspector.css`, `search.css`, `feedback.css`.

| key | label | module | export | css |
| --- | --- | --- | --- | --- |
| `home` | Home | `./home.js` (§6.13.7) | `mount` | `home.css` |
| `map` | Map | `./app.js` (internal iframe view) | — | — |
| `patch` | Patch | `./patchview.js` | `mount` | `patchview.css` |
| `table` | Table | `./patchtable.js` | `mount` | `datatable.css`, `patchtable.css` |
| `rooms` | Rooms | `./page-room.js` | `mount` | `PAGE_CSS` + `page-room.css` |
| `plan` | Plan | `./floorplan.js` | `mount` | `plan.css`, `explorer.css` |
| `racks` | Racks | `./rack.js` (mounts `page-rack.js` when the route has an id) | `mount` | `plan.css`, `explorer.css`, `entity-header.css`, `datatable.css`, `rack.css` |
| `devices` | Devices | `./page-device.js` | `mount` | `PAGE_CSS` + `page-device.css` |
| `inventory` | Inventory | `./inventory.js` | `mount` | `plan.css`, `datatable.css`, `inventory.css` |
| `files` | Files | `./files.js` | `mount` | `plan.css`, `datatable.css`, `files.css` — project attachments table (name link, kind, device, size, uploaded, by; filters on kind and device; CSV; `cards` at sm), multi-file upload via `upload(name, 'files', files)` (fixed bottom-right button at sm), bulk delete behind a danger confirm. Read-only for viewers. |
| `schedules` | Schedules | `./schedules.js` | `mount` | `plan.css`, `datatable.css`, `schedules.css` |
| `imports` | Imports | `./views-admin.js` | `mountImports` | `ADMIN_CSS` |
| `discovery` | Discovery | `./views-discovery.js` | `mount` | `datatable.css`, `discovery.css` |
| `history` | History | `./views-admin.js` | `mountHistory` | `ADMIN_CSS` |
| `builds` | Builds | `./views-admin.js` | `mountBuilds` | `ADMIN_CSS` |
| `settings` | Settings | `./views-admin.js` | `mountSettings` | `ADMIN_CSS` |
| `sop` | SOPs | `./views-sop.js` | `mount` | `sop.css` — phone-first SOP wiki (§5.15): drill-down page tree with sticky search, rendered page (sticky "Applies to" chips, collapsible TOC, tappable task lists kept in `sessionStorage`, tap-to-zoom images, prev/next), split Markdown editor with live server preview, versions drawer. Query keys `page=<slug>`, `edit=1`, `new=1[&parent=<slug>&device=<id>&from=<slug>]`, `problems=1`. It has no `route(r)` member and listens to `hashchange` itself. |
| `json` | JSON | `./app.js` (internal) | — | — |

`DEFAULT_VIEW` = `'home'` (`router-core.js`). While a module loads, `#app-main` shows `skeleton(kind)` (§6.13.8): `cards` for home, patch, plan, map; `list` for sop; `table` for the list views; `page` for devices/rooms/racks with an id, `table` without. A failing import shows `.app-error-card[data-error-view]` with Retry (FR-UX-03).

**Sections** (`router-core.SECTIONS`, `{key, label, glyph, views, nav}`; a view's section is `sectionOf(view)`, unknown views → `data`):

| key | label | views | nav |
| --- | --- | --- | --- |
| `home` | Home | `home` | `sm` (the brand link `#app-home` at md/lg) |
| `patch` | Patch | `patch`, `table`, `map` | `all` |
| `rooms` | Rooms | `rooms`, `plan`, `racks` | `all` |
| `devices` | Devices | `devices`, `inventory`, `files` | `all` |
| `schedules` | Schedules | `schedules`, `builds` | `all` |
| `sop` | SOPs | `sop` | `all` |
| `data` | Data | `imports`, `discovery`, `history`, `json` | `all` |
| `settings` | Settings | `settings` | `all` |

Roles: `VIEW_ROLES` is empty (every view is open to viewers); `TAB_ROLES = {settings: {users: 'admin', backups: 'admin', sharing: 'editor', trash: 'admin'}}`; `canSee(view, role, tab)`, `sectionsFor(role)` (sections with ≥ 1 permitted view), `sectionRoot(key, route, role)` (route to the section's first permitted view, same project and room).

**View contract** (every `mount*` export):

```js
export function mount(el, ctx) {
  // render into el, subscribe to ctx.store events
  return {
    destroy() {},          // remove listeners, timers, DOM
    focus(sel) {},         // optional: scroll/zoom to a selection
    route(r) {},           // optional: same-view route change (copy of the parsed route); the view re-renders itself
    getState() {},         // optional: {zoom, scroll, …} restored by the shell when re-mounted
    setState(s) {},        // optional
  };
}
```

Same-view route changes (`applyRoute`): when the handle has `route(r)` it is called and the view stays mounted; otherwise the view re-mounts when `id`, `tab` or `sub` changed; otherwise the shell calls `focus(store.selection)` and re-renders the nav. The inspector handle (`mountInspector`, §6.8) adds `render()`, `focusSection(key)` (opens and scrolls to `details[data-section=key]`, writes `sec`; returns false for an unknown key) and `sections()` (the section keys in order).

**ctx** (built by `makeCtx(store, extras)`; the defaults are harness-safe, the shell passes the rest as `extras`; extras are copied as property descriptors, so getters stay live):

| Member | Type | Notes |
| --- | --- | --- |
| `store` | Store | §6.2 |
| `vocab` | object | `meta.vocab` (store vocab) |
| `api` | api or null | null in harnesses; in the app `build()` is wrapped to post a bell notice when a build finishes or fails |
| `project` | string | project name |
| `meta`, `role`, `session` | object, string, object | `GET /api/v2/meta`; `viewer`\|`editor`\|`admin` (harness: `viewer` when the store is read-only, else `admin`); `GET /api/v2/session` |
| `env` | `{touch, narrow, platform: 'ios'\|'mac'\|'other', online, secure}` | |
| `commit(ops, label)` | fn | store.commit + announce label in `#fathom-live`; no-op + toast when read-only |
| `select(sel)`, `highlight(h)` | fn | store passthrough (re-selecting the item the shell is focusing is a no-op) |
| `navigate(view, params)` | fn | legacy: `params {room, sel, keepSel}`; pushes; adds `drawer=0` when the selection would not open the drawer (§6.13.5) |
| `navigateRoute(partial, {replace})` | fn → hash | `mergeRoute` onto the current route (a different view or id clears the query unless `query` is given) and write it (push unless `replace`); harness: `''` |
| `routeHref(partial)` | fn → string | the hash `navigateRoute` would write; harness: `'#'` |
| `setParams(patch, {replace = true})` | fn | merge query keys (`null` deletes); `sel`/`sec`/`drawer` also apply the selection and drawer |
| `route` | getter → Route | copy of the current parsed route (§6.13.1) |
| `openDrawer(sel, {section})` / `openInspector(sel)` | fn | select with intent (opens the drawer at any width; `sel` may be a string); `section` focuses that inspector section |
| `closeDrawer()` / `closeInspector()` | fn | close and clear the selection |
| `layout()` | fn → `'sm'\|'md'\|'lg'` | `layoutFor(innerWidth)` |
| `subscribe(type, fn)` | fn → off | types `route` (Route), `layout` (`'sm'\|'md'\|'lg'`), `problems`, `overlay` |
| `recent` | getter | snapshot `{device, room, rack, page: [{id, t}]}` of `fathom.ui.recent.<project>` with non-enumerable `push(type, id)` and `list(type)` → ids |
| `notify({text, level, href})` | fn | adds a bell notice (§6.13.8; harness: toast) |
| `sections` | Section[] | `sectionsFor(role)` |
| `projects`, `projectsStatus()`, `reloadProjects()` | getter, fn, fn → Promise | `[{name, title}]`; `{loading, error}`; re-lists projects |
| `setTitle(text)` | fn | `document.title = text · project · Fathom` |
| `problems()` | fn → array | the **validation** results of §4.7 (`{level, code, ref, path, message}` from `getProject` / `postChanges`), not problem reports (`doc.problems`, §5.15) |
| `overlayInfo()`, `refreshOverlay()` | fn | `{fetchedAt, revision}` of the overlay; refetch it (Promise) |
| `reload()`, `flush()` | fn → Promise | change-queue resync; flush pending ops |
| `timeTravel(rev)`, `endTimeTravel()`, `restoreRevision(rev)`, `isTimeTravel()` | fn | History view (FR-HIST) |
| `queue`, `appRoot` | ChangeQueue, string | |
| `ensureCss(file)`, `viewCss(key)` | fn → Promise | load a stylesheet; load `VIEWS[key].css` |
| `pickTemplate({discipline?, kind?})` | fn → Promise\<template\|null\> | library picker dialog (W5) |
| `pickPort({compatibleWith: {device, port}, room})` | fn → Promise\<{device, port}\|null\> | port picker dialog (W5) |
| `pickDevice({room, filter})` | fn → Promise\<deviceId\|null\> | device picker (W5) |
| `toast(message, level)` | fn | `level` ∈ `info`, `ok`, `warn`, `err` |
| `confirm(message, {danger, ok})`, `prompt(message, value, opts)`, `openDialog(o)` | fn → Promise | modals |

**Router** (pure parts in `router-core.js`, §6.13.1). Grammar `#/<project>/<room>/<view>[/<seg4>[/<seg5>[/<seg6>]]][?<query>]`; `<room>` `*` = all rooms. Segments after the view are named by `VIEW_SHAPES`: `devices` [id, tab, sub], `rooms` [id, tab], `racks` [id, tab, sub], `plan` [id], `schedules` [tab], `imports` [tab], `settings` [tab], `discovery` [tab, sub], `history` [id]; other views take none (surplus segments land in `extra`). Query keys: `sel` (`device:<id>`, `port:<dev>:<port>`, `cable:<id>`, `rack:<id>`, `floorplan:<id>`, `marker:<fp>:<dev>`, `channel:<dev>:<ch>`, `bundle:<id>`, `room:<id>`), `sec` (inspector section), `drawer=0`, `filter` / `q` / `status` (patch view), DataTable `q`, `sort`, `f.<col>`, `pg` (§6.13.4), `hl` (row to highlight), `mode` (patch table `blocks`\|`rows`), `quick` (inventory quick filters), `run` (discovery run), and the SOP keys above. `?smoke=1` and `?debug_missing_view=<key>` are test hooks in `location.search`, not the hash.

History rules (D1): a change of view, id or tab **pushes**; a selection change **replaces**; opening the drawer from closed pushes when there is intent or the layout is below lg (Back closes it), else replaces; DataTable state replaces; `setParams` replaces unless `{replace: false}`. Routing writes go through `historyWrite` (push/replaceState) and then dispatch a synthetic `hashchange` (`writeHash`), so views that listen to `hashchange` (`views-sop.js`) see them; shell-state writes (`syncRoute`) update the URL silently without re-routing. Canonicalization replaces: an empty, unknown or unpermitted view becomes `home` (the query is kept); an unknown room becomes the store room; `rooms/<id>` sets the room to `<id>`. Legacy: `/?p=<project>` without a hash is replaced by `legacyHash(project, '', 'home')` keeping the other search params; `buildHash` output is unchanged for every non-empty view. Nav memory: `navMemory(sessionStorage)` stores the last hash per section per project under `fathom.ui.nav`; a section click goes to that hash (when still permitted, with the room rewritten to the current one) or the section root; clicking the active section goes to its root. Every routed hash is recorded in nav memory and emits `route`; devices, rooms, racks and SOP pages that exist are pushed to recents.

On boot: `GET /api/v2/session` (redirect to `login` if needed), `GET /api/v2/meta`, project list, `GET /api/v2/projects/<n>`, then overlay in the background (`store.setOverlay`). Keys: ⌘/Ctrl+K search, ⌘/Ctrl+J assistant, ⌘/Ctrl+S flush, ⌘/Ctrl+Z undo, ⌘/Ctrl+⇧Z or Ctrl+Y redo; Esc per D4 (§6.13.5).

Shell DOM ids (stable; `SHELL_IDS` in `tests/test_frontend_smoke.py` asserts all but `#app-home`, `#app-undo`, `#app-redo`, `#app-notify-count` and `#app-body`), in `app.html` order: `#app`, `#app-banner` (time-travel and conflict banner, before the header; holds `#app-conflict-reload`, `#app-conflict-keep`), `#app-top`, `#app-home` (brand link), `#app-project`, `#app-room`, `#app-search`, `#app-undo`, `#app-redo`, `#app-assistant-btn`, `#app-notify` (bell) with `#app-notify-count`, `#app-save`, `#app-user`, `#app-lock` (editing-lock banner, `role=status`, hidden unless locked; holds `#app-unlock`), `#app-views` (md/lg section nav: `div.app-sec-item` > `button.app-sec[data-section][data-views][aria-haspopup=menu]` + `ul.app-sec-menu[role=menu]` of `button[role=menuitem][data-view]`; `.app-views--icons` when labels do not fit), `#app-subnav` (`a.app-subtab[data-view][href]`, hidden for one-view sections), `#app-body`, `#app-main` (view host), `#app-inspector` (drawer host), `#app-selbar` (selection bar while the drawer is closed; `.app-selbar-title`), `#app-tabbar` (sm: `button[data-tab=<section>]` with `span.ico`), `#app-assistant`, `#app-toasts`, `#app-dialog`, `#fathom-live`. Every view key appears as a `[data-view=<key>]` control (section menu or subnav).

User menu (`#app-user` → `.app-menu[role=menu]`), after the sm-only undo/redo/Helper/projects block: *Theme: <current> ▸ <next>* (`#app-menu-theme`), *Make available offline*, *Keyboard shortcuts*, *Take the tour* (`#app-menu-tour`, disabled without a project), *Lock editing* (`#app-menu-lock`; editors and admins, online, not time-travelling, project unlocked), *Suggest an improvement…* (`#app-menu-suggest`, every role), then sign-in/out. The menu binds its keydown handler at once (Esc, ↑ ↓) and its outside-pointerdown handler on the next tick.

Theme (FR-UX-15): `readTheme()` → `?theme=` (search or hash query, not persisted) else `fathom.ui.theme` else `dark`; `applyTheme(t)` sets `html[data-theme]` and the `theme-color` meta (`resolvedScheme(t)`: `system` follows `matchMedia('(prefers-color-scheme: light)')`, re-applied on change); `setTheme(t, persist)`; `nextTheme(t)` cycles `THEMES` `['dark', 'light', 'system']`. Light-theme CSS lives in `app.css` as `html[data-theme="light"]` plus the same block under `@media (prefers-color-scheme: light) { html[data-theme="system"] }`; component files use the variables and need no light block unless they hard-code dark colours.

Tour (FR-UX-16): `tour.js` exports `startTour(steps, opts)` → `{done: Promise<{done, reason, step}>, index(), isOpen(), next(), back(), goTo(i), close(reason), relayout()}` with `steps = [{target: '<selector list>', title, text}]` and `opts = {onClose, onStep, root}`; it builds `.tour-backdrop`, `.tour-hl` (box-shadow cut-out around the first rendered target, 6 px padding) and `.tour-card[role=dialog][aria-modal=true][data-step][data-side]` (`.tour-count` *n of N*, `.tour-close`, `h2.tour-title`, `p.tour-text`, `.tour-skip`, `.tour-back`, `.tour-next[data-last]`); `placeCard(targetRect, w, h, W, H)` is pure (below → above → right → left → over → centre); below 700 px the card is `.tour-card--sheet`; `findTarget(selectors, root)` and `stepVisible(step, root)` skip hidden targets. The shell (`tourSteps()`, `runTour()`, `maybeStartTour()`) loads `tour.css` and `tour.js` lazily, runs the tour 350 ms after the first `applyRoute` of the first project when `fathom.ui.tour` is unset, and writes `{done: true, at, reason}` on close (`reason`: `done`, `skip`, `esc`, `close`).

Editing lock (FR-UX-17): `lockInfo()` reads `settings.locked`, `locked_by`, `locked_at`; `applyLock()` runs after every doc load and whenever a doc event touches `settings`, sets `A.locked`, `store.setReadOnly(baseReadOnly() || locked)` (`baseReadOnly` = viewer or offline), renders `#app-lock` (hidden while time-travelling) and re-mounts the current view (except `settings`) when the state changed; the view ctx `role` getter returns `viewer` while locked for every view except `settings`. `setLocked(on)` commits one root op on `settings` with label *Lock editing* / *Unlock editing* (temporarily lifting the read-only flag so the op can pass). The change queue (`api.js`) treats `isLockedError` on flush as drop-everything: it clears the queue and its persisted copy, emits `state` `{state: 'error', locked: true, dropped: n}` and `dropped` `{error, ops, locked: true}` and resyncs; the shell toasts *Someone locked editing — your last change was not saved*.

Suggestions (FR-UX-18): `improve-ui.js` exports `SUGGESTION_MAX` 2000, `suggestionBody(text, name, url)` → `{text, kind: 'suggestion', name?, url?}` (trimmed and clipped; name ≤ 80, url ≤ 500), `thanksText(res)` and `openImproveDialog(ctx, {about, name, url})`, which uses `ctx.openDialog` and `ctx.api.reportSuggestion`. The shell passes `about` = project · view label · room name and `url` = `location.href`.

### 6.5 Patch view: `js/patchview-core.js` + `js/patchview.js` (W3)

**Core (pure)**

```js
export const GEOM = {cardW: 248, headerH: 56, rowH: 22, sectionH: 18, ioSectionH: 18, pad: 8, dotR: 5, grid: 8, maxRows: 12};
export function cardLayout(device, opts) {}
  // opts {connected:Set<portId>, labels:{portId:label}, showUnconnected:true, expanded:false, maxRows}
  // -> {w, h, rows:[{port:Port, side:'left'|'right'|'both', y, index, label, overlayLabel:boolean}], hidden:{left, right, io}}
export function buildScene(doc, overlay, vocab, filter, opts) {}
  // filter {room, disciplines, statuses, query, system, showUnconnected}
  // -> {cards:[{id, device, x, y, w, h, layout, external, auto, dim}], wires:[{id, cable, from:{device, port}, to:{device, port}, medium, color, dash, width, external}], routes:[...overlay aggregated...], bounds:{x, y, w, h}}
export function portAnchor(card, portId, side) {}       // -> {x, y} world coords; header anchor when portId null
export function wirePath(a, b) {}                        // "M ax ay C c1x c1y c2x c2y bx by"; c = horizontal tangents, offset max(40, |dx|/2)
export function autoLayout(doc, deviceIds, vocab, opts) {} // -> {id: {x, y}}; layered by longest path, colGap 96, rowGap 24, origin opts
export function hitTest(scene, pt, opts) {}              // -> {type:'port'|'wire-end'|'wire'|'card'|'header'|'background', card?, port?, wire?, end?}
export function compatibleTargets(doc, scene, from, vocab) {} // -> Set<'dev:port'>
export function moveOps(doc, positions) {}               // {id:{x, y}} -> merge ops (snapped)
export function snap(v, grid) {}
export function traceLocal(doc, overlay, start, opts) {} // §6.9 client port-graph trace -> {ports:Set, cables:Set, devices:Set}
```

**DOM module** `mount(el, ctx)`:

- Structure: `div.pv-root` (toolbar `div.pv-toolbar`, viewport `div.pv-viewport[role=application][aria-label="Patch view"][tabindex=0]` with `touch-action:none`, containing `div.pv-world` transformed by `translate3d(x,y,0) scale(k)`; inside: `svg.pv-wires` (one `<path data-cable=id>` per wire), `div.pv-card[data-device=id][role=group]` cards with `div.pv-port[data-port=id]` rows).
- Toolbar (`div.pv-toolbar[role=toolbar]`, one row): `#pv-add`, `#pv-fit`, `#pv-zoom-out`, `#pv-zoom-in`, `#pv-undo`, `#pv-redo`, `#pv-filter-text` (with `button.pv-search-toggle`), then popovers (`div.pv-pop-wrap[data-menu]` > `button[aria-haspopup]` + `div.pv-pop[role=group]`): **View** (`.pv-menu-view`: `#pv-show-unconnected`, `#pv-show-routes`, `#pv-all-rooms`, `#pv-snap`, `#pv-filter-disc` (chips `[data-disc]`), `#pv-filter-status`), **Arrange** (`.pv-menu-arrange`: `#pv-arrange`, `#pv-save-arrangement`), **More** (`.pv-menu-more`, ⋯). At sm zoom, undo and both popover panes move into More; every `#pv-*` control stays in the DOM exactly once. URL keys `filter`, `q`, `status` mirror the discipline, text and status filters. Context menu `div.pv-menu[role=menu]`; empty state `.pv-empty`; stale overlay badge `.pv-stale-host`.
- Emits only through `ctx.commit` / `ctx.select` / `ctx.highlight`; listens to store `doc` (incremental update by touched refs; full rebuild when > 50 refs), `filter`, `room`, `highlight`, `overlay`, `mode`.
- Perf contract: sets `window.__pvStats = {renderMs, cards, wires, lastDragFrameMs}` after first render (harness and app).
- Inline rename uses an absolutely positioned `<input class="pv-rename">` over the title/row; commit on Enter/blur.

### 6.6 Patch table: `js/patchtable-core.js` + `js/patchtable.js` (W5)

```js
export function buildPatchTable(doc, overlay, vocab, filter) {}  // -> PatchBlock[]
export function patchTableCsv(blocks) {}                           // CSV string, columns = §5.8.2 'patch' labels, "\r\n" line endings, RFC 4180 quoting
export function patchCellOps(doc, rowRef, field, value) {}         // field 'label' -> renameOps; 'peer' -> connect/repatch; 'clear' -> disconnect
```

**PatchBlock** (same structure produced by W6 `patch.patch_table` in Python; JSON-equal for the fixture):

```json
{"device": "audio-rack-1", "name": "Audio Rack 1", "model": "Allen & Heath AR84", "room": "main",
 "discipline": "audio", "kind": "stage_io",
 "sections": [
   {"title": "Analog In", "dir": "in", "medium": "analog",
    "rows": [{"port": "analog-in-1", "port_name": "Input 1", "label": "SB1-Out 1",
              "peer_device": "stage-box-1", "peer_name": "Stage Box 1", "peer_port": "analog-out-1",
              "peer_port_name": "Output 1", "peer_label": "SB1-Out 1",
              "cable": "c-0005", "tag": "A-003", "medium": "analog", "source": "cable"}]}]}
```

Rules: blocks in `devices` order (filtered by room/discipline/text; `room: '*'` = all); `model` = `manufacturer + " " + model` trimmed, else `sub`; sections = consecutive port groups in device port order (title = `group`, else `"<MEDIA.short> <In|Out|I/O>"`), `dir` = the group's ports' dir (mixed → `io`), `medium` = first port's medium; one row per port, plus one extra row per additional cable on the same port; unpatched ports have all `peer_*`, `cable`, `tag` = `null` and `source: null`; `source: "cable"` for doc cables, `"dante"|"videohub"|"console"` for overlay rows (only when `filter.includeOverlay`); device-level cable endpoints appear as a row with `port: null` in a final section titled "Device" (`dir` from the cable direction).

CSV row order = blocks → sections → rows; `section` column = section title; `dir` = `in|out|io`; `port` = port label or name; `label` = port label; `peer_device` = peer name; `peer_port` = peer port label or name; `cable_tag` = tag; `source` = source or empty.

DOM `mount(el, ctx)`: ids `#pt-filter-room`, `#pt-filter-disc`, `#pt-filter-text`, `#pt-only-patched`, `#pt-show-overlay`, `#pt-csv`, `#pt-print`, `#pt-mode` (`div[role=group]` with the **Blocks** / **Rows** buttons; URL key `mode=blocks|rows`), `#pt-split` (`button[aria-pressed]`, patch view above the table); blocks mode renders `section.pt-block[data-device]` (a §6.13.4 exemption) with "Patch…" buttons `button.pt-patch[data-port]`; rows mode is a DataTable (`ids {search: 'pt-filter-text', csv: 'pt-csv'}`, bulk action *Remove patch*, per-row `button.pt-remove`). Switching to blocks drops the table keys (`sort`, `pg`, `f.*`) from the URL.

### 6.7 Floor plan, rack, schedules, inventory (W4)

**`js/floorplan-core.js` (pure)**

```js
export function normToImage(fp, pt) {}          // {x,y} 0..1 -> image px
export function imageToNorm(fp, pt) {}
export function metersPerPx(fp) {}               // from calibration; null if none
export function distance(fp, a, b, units) {}     // a,b normalized -> {meters, text}
export function markerOps(doc, fpId, deviceId, pt) {}       // add or move (merge floorplans markers array)
export function removeMarkerOps(doc, fpId, deviceId) {}
export function calibrateOps(doc, fpId, p1, p2, dist, unit) {}
export function unplacedDevices(doc, fpId, room) {}         // devices in room without a marker on this plan
```

**`js/rack-core.js` (pure)** — geometry `RU_PX = 22`, rack inner width 19" drawn as `RACK_W = 320` px, half width = 160 px.

```js
export function rackDevices(doc, rackId) {}       // -> [{device, u, height, face, side, depth}]
export function occupancy(doc, rackId, face) {}   // -> array index u (1..units) of {left:id|null, right:id|null}
export function collisions(doc, rackId) {}        // -> [{a, b, u, face}]
export function fits(doc, rackId, deviceId, u, opts) {}  // -> {ok, reason}
export function placeOps(doc, deviceId, rackId, u, opts) {} // opts {face, height, side, depth, force}
export function unplaceOps(doc, deviceId) {}
export function uToY(rack, u, height) {}          // top px of a block; respects numbering
export function yToU(rack, y, height) {}          // snapped, clamped to 1..units-height+1
export function ruLabel(rack, u) {}
```

DOM modules: `floorplan.js` `mount(el, ctx)`: toolbar `div.fp-toolbar[role=toolbar]` with `#fp-select`, `#fp-fit`, `#fp-zoom-out`, `#fp-zoom-in`, `#fp-upload` (file input, label *Upload plan…*), `#fp-dev-plan` (sample plans), `#fp-calibrate` (dialog `#fp-cal-distance`, `#fp-cal-unit`), `#fp-measure`, `#fp-layers`; tools that do not fit move into ⋯ (`button.fp-menu-more` → `#fp-menu`); the device list is an explorer (§6.13.2, key `plan-unplaced`, title *Devices*, *Unplaced* and *Placed* groups) whose `ul.ex-list` is `#fp-unplaced`; canvas `div.fp-viewport[role=application]`, markers `div.fp-marker[data-device]`; delete dialog `#fp-del-*`. `rack.js`: toolbar `div.rk-toolbar` with `#rk-select`, `#rk-add`, `#rk-edit`, `#rk-face`, `#rk-print`; rack form `#rk-f-*`; unracked devices in an explorer (key `racks-unracked`, discipline chips) whose list is `#rk-unracked`; blocks `div.rk-block[data-device]`; with a route id it mounts the rack page (`page-rack.js`, explorer list `#rp-racks`, classes `rp-*`) and embeds the elevation there. `schedules.js` tabs `a[role=tab]#sch-tab-<kind>[data-kind]` for `cables|ip|dmx|bom|patch|racks|labels` (`schedules/<kind>` in the URL), panel `#sch-panel`; `#sch-state` (select), `#sch-assign-tags` (`#sch-tag-scope`, `#sch-tag-pattern`), `#sch-bulk-add` (§6.13.9 wizard), `#sch-print`, `#sch-csv-all` (server CSV of every row), `#sch-csv`; each kind is a DataTable (key `schedules.<kind>`, `ids {root: 'sch-dt', search: 'sch-filter', csv: 'sch-csv', filters: {disc: 'sch-disc', room: 'sch-room'}}`; `#sch-disc` filters a client-side Discipline column; in the app `#sch-room` is the Room column filter, in the harness a room select); BOM drill-downs open `openTableDialog` (keys `schedules.bom.cables`, `schedules.bom.devices`); the labels tab keeps its print sheet (`.sch-labels`, §6.13.4 exemption) and, with the API, adds `section.sch-devlabels` **Device labels** (FR-QR-05) right under the cable-label controls and before the cable sheet preview: `#sch-dl-preset` (select filled from `GET /api/v2/labels/presets`, default selected, option text `<label> — <w>×<h> mm`), `#sch-dl-scope` (`all` | `room` — disabled when the header room is *All rooms* | `selected`), `#sch-dl-count`, the picker `.sch-dl-pick` (shown for `selected`: `#sch-dl-filter` search box, `ul.pick-list#sch-dl-list[aria-multiselectable]` of `li[role=option][data-pick][aria-selected]`, *Select shown* / *Clear*), and plain links `a#sch-dl-preview[target=_blank]`, `a#sch-dl-zip[download]`, `a#sch-dl-csv[download]` to `…/labels/devices?preset=&format=html|zip|csv` plus `room=` or `devices=` per scope (`aria-disabled` without a preset or devices). Preset, scope and selection live in the view state and survive re-renders; below 700 px the rows stack with full-width controls. Inline edits commit ops for doc-backed columns (cable tag/type/length/color/note/status; interface ip/vlan/mac/hostname/switch/switch_port; dmx universe/address/footprint/mode/channel). `inventory.js`: a DataTable (key `inventory`, `ids {table: 'inv-table', columns: 'inv-columns', csv: 'inv-csv', search: 'inv-filter', selectAll: 'inv-select-all', filters: {room: 'inv-room', status: 'inv-status', location: 'inv-location', kind: 'inv-kind', system: 'inv-system'}}`); `#inv-scope` (select: current room, all rooms, shared inventory), quick filters `#inv-q-warranty`, `#inv-q-serial` (URL key `quick`), `#inv-group` (group by location), `#inv-bulk-add` (wizard), `#inv-dups` (duplicates, with the API), `#inv-csv-all` (import-format export, in ⋯); bulk bar (`.dt-bulk`): `#inv-bulk-status`, `#inv-bulk-room`, `#inv-bulk-location`, `#inv-mark-installed`, `#inv-merge`; edit form `#inv-form-*`. Scope and grouping persist in the table state's `extra`. Knox parity (P1C, FR-INV-10..13): columns `condition` (chip `span.inv-status.inv-cond[data-condition]`, filter `#inv-condition`, values from `conditionsOf(vocab, meta)` — `vocab.conditions`, else `meta.conditions`, else `model-core.CONDITIONS`), `container` (button `.inv-container-link[data-container]` selects the container; filter `#inv-container`, `(empty)` = loose), `code` (`code.inv-code-text` + `button.inv-copy[data-copy]` copying `api.codeLink(code)`), and one `field:<key>` column per custom-field key in the doc (`fieldKeys(doc)`; the first three visible, the rest in the column panel; all `hideOnMobile`); CSV adds Condition, Container, Code. Quick filters `#inv-q-accessories` (no ports), `#inv-q-contained` (in a container), `#inv-q-containers` (kind `container`); bulk `#inv-bulk-condition` (`inventory.condition`, `__none` clears) and `#inv-bulk-container` (`device.container`, a container never stores itself); the edit form gains Condition and *Stored in*. At sm the table is `cards: true` (`.dt-cards`) showing name, kind, status, condition, container, code and Edit. Schedules and inventory read rows from the server when `ctx.api` exists, else compute minimal rows locally from the doc (harness mode).

### 6.8 Inspector, assistant UI, admin views, search palette (W5)

- `js/inspector.js`: `export function mountInspector(el, ctx)` → handle; renders the current selection's form; field changes → ops via `ctx.commit` (text debounced 400 ms, one op per field burst). Device sections: Identity, Map placement, Ports (table editor + bulk add + apply template), **Console channels** (§6.8.6, only when the device has channels persisted or in the overlay), Rack, Inventory, Network interfaces, DMX, Attachments (upload/list), QR, Notes. Cable: endpoints (pickers), medium, tag, type, length (unit aware), color, channels, status, bundle, signal, note. Port: label, name, medium, connector, channels, note, connected cables. Rack, floor plan, marker: their fields. Devices, ports and channels carry a **Trace path** button (§6.8.7).
- Drawer content (D4, B.3 INS): the inspector renders into the drawer host `#app-inspector` (§6.13.5 owns modes, focus, Esc). Header `div.ins-head.ins-title[data-kind]`: `.ins-head-row` (`.ins-glyph`, kind label, `a.chip.ins-open-page` to the entity page for devices, rooms and racks, `button.ins-close`), `h3` title, `.ins-head-meta` (`span.ins-status[data-status]` status pill, subtitle), then `div.ins-badges` (review badges on their own row: `[data-badge=dups]` possible duplicates, `[data-badge=problems]` open problem reports of `doc.problems` for the device; each jumps to its section). Every section is `details[data-section=<key>]` (device keys `identity`, `map`, `ports`, `console`, `rack`, `inventory`, `net`, `dmx`, `files`, `procedures`, `problems`, `qr`, `notes`, `dups`, `merged`; port `cables`, `fields`; cable `endpoints`, `fields`; channel `fields`, `input`, `fedby`, `sends`, `groups`, `members`, `outputs`; rack, floor plan, marker, bundle, room `fields`). With ≥ 3 sections a sticky index `nav.ins-index` of `a.ins-index-chip[data-sec][href]` deep links (`sel=…&sec=<key>`) leads; `focusSection(key)` opens and scrolls to the section and writes `sec` (the shell calls it with the URL's `sec`). Ports lead with *Now connected* (`section cables`: `.ins-now-row[data-cable]` with direction, far end `.ins-now-peer`, cable chip `.ins-now-cable`, Trace), then the port fields; cables lead with *Endpoints*. Open/closed state of sections the user toggled persists per entity kind in localStorage `fathom.ui.inspector` (`{"v": 1, "open": {"<kind>": {"<section>": bool}}}`); defaults open: identity, ports, endpoints, fields, console. Viewers get a read-only drawer; an unknown selection says it was not found.
- Device *Inventory* section, Knox parity (P1C): leads with *Condition* (`boundSelect` on `inventory.condition`, options `conditionsOf(vocab, ctx.meta)`, empty `—`); non-containers get *Stored in* (select over `containerDevices(doc)`, writes `device.container`, `null` clears); containers get *Holds (n)* (`.ins-holds-row` > `ul.ins-holds` of `a.ins-holds-link[data-device]` selecting the content); *Code* (`.ins-code[data-code]`: `code.ins-code-text` as `XXXX-XXXX`, `button.ins-copy-link[data-copy]` copies `api.codeLink`, `img.ins-qr-thumb` from `api.qrUrl`; `—` without a code — codes are server-assigned, never edited here); *Custom fields* editor at the end (`.ins-fields[data-fields]`, `button.ins-field-add`, rows `.ins-field-row` of `input.ins-field-key` (≤ 40 chars) / `input.ins-field-val` / `button.ins-field-rm`, ≤ 32 rows). Each change writes the whole `inventory.fields` object in one `merge` op (removed keys → `null`, empty → `fields: null`); a duplicate key marks both rows `.ins-field-dup` and shows an `inlineError` in `.ins-fields-err` without committing. Read-only for viewers.

#### 6.8.6 Console channels (inspector)

- Pure helpers in `js/console-core.js` (Node-tested): `effectiveChannels(device, overlay)` mirrors `console.effective_channels` (`{channels, links, source: device|overlay|none, pending}`), `groupChannels` → Inputs (`input`, `stereo_input`) | Buses (`mix`, `aux`, `group`, `matrix`, `stereo`, `mono`, …) | DCAs (`dca`, `mute_group`) | Racks, `channelLabel` / `channelTitle` (same wording as the Python), `channelIndex(links)` (per channel: `inputs`, `sends`, `feeds`, `outputs`, `direct`, `insertSend`, `insertReturn`, `dca`, `mute`, `members`), `endpointText(ep, ctx)` (port label + channel number + Dante name from `overlay.channel_labels`, console title, rack side, or the text), `routePeer(routes, dev, port, ch, dir)` (far end of an overlay route), `channelSummary`, `filterChannels`, refs `channelRef(dev, ch, tag?)` → `dev:@in-12`, `portChannelRef`.
- Device section *Console channels (n)*: a note + **Apply to device** (POST `…/channels/apply`, then reload doc and overlay) when the set is overlay-only or a newer import differs; segmented control `Inputs n | Buses n | DCAs n | Racks n`; a filter box (matches title, name, fed-by / goes-to text, Dante channel); dense rows `button.ins-chan[data-channel]` — title `CH 12 · Bass`, sub line `← Dante Primary 17 “17 Bass” (Rio3224 · Bass 17) · → ST L, MIX 1 · DCA 1 · BAND` (or `no input patch` / `nothing patched`). Tapping a row selects `{type: "channel", device, channel}` (hash `sel=channel:<dev>:<ch>`; patch view highlights the console card without re-selecting it). Editors can add a channel (`nextChannel`: next free index of a kind, `source: "user"`).
- Channel inspector: head (kind, title, device, import source) with a back button; actions *Trace path* and *Show console in patch view*; sections *Channel* (name, label override, colour, icon, note → `merge` on `devices[].channels`, the edited channel gets `source: "user"`), *Input patch* (inputs / insert returns with remove ×; picker: a port of this device (+ channel number when `channels > 1`), a rack side, or free text), *Fed by* (buses and racks: the channels sending into it, tap to jump), *Sends* (inputs → every bus; mix/aux/group → matrix / stereo / mono; chip toggles; note that nothing is assumed, not even Stereo L/R), *DCA / mute groups* (chip toggles), *Members* (DCA / mute group: chips over inputs and buses), *Output patch* or *Direct out & inserts* (links to ports / text with remove ×; picker adds `output_patch` or `direct_out`), *Delete channel* (removes its links too). Every edit is one `merge` op on `devices[].channel_links` (whole array, user links stamped `source: "user"`; `console-core` editors are pure and idempotent). Everything is read-only while the set is overlay-only — apply first.

#### 6.8.7 Trace drawer

- `js/trace-ui.js` (no dependency on `app.js`, also loaded by the public device page): `openTraceDrawer({from, title, sub, direction, dca, fetchPaths, actions, onHop, onClose})` renders `.trace-backdrop > .trace-sheet[role=dialog]` — a right-hand drawer from 720 px up, a full-screen sheet below (`static/css/trace.css`): sticky header (eyebrow *Signal path*, title, sub, ×), controls (segmented `← Upstream | Downstream →`, *DCA hops* checkbox → `dca=1`, *Copy as text* → the `text` lines, optional actions such as *Open in patch view*), a status line (`n paths · m incomplete`), then one `section.trace-path` per path: hops grouped by device (`chainOf(path)` uses the hop's `device_name` and strips the `Device · ` prefix from `label`), each hop with its `via` chip (`cable c-0001`, `dante route`, `input patch`, `internal`, …) and a kind tag (`console`, `stream`, `control`, `note`); an incomplete path ends with a warning line `⚠ <reason>`. Escape / backdrop / × close; focus returns to the opener. In the editor a hop is clickable: it selects that channel / port / device in the inspector and closes the drawer.
- `bindTraceButtons(root, {base, project})`: any `[data-trace="<node ref>"]` (`data-trace-title`, `data-trace-sub`, `data-trace-dir`) opens the drawer over `fetch(base + "api/v2/projects/<p>/trace?…")`. The viewer device page (`/p/<n>/d/<id>`) renders *Console channels* tables (Inputs, Buses, DCAs & mute groups, Racks: channel, name, fed by, goes to, DCA / mute, members) from `console.effective_channels` plus a *Trace* button per channel (inputs trace upstream, the rest downstream), per port and for the whole device, and loads `trace-ui.js` + `trace.css`; build output (`link_style="build"`, no API) renders the tables from the doc alone and no buttons.
- `js/assistant-ui.js`: `export function mountAssistant(el, ctx)`; calls `ctx.api.ask(project, {question, room, use_llm, history})`; renders summary (escape HTML, then `**x**` → `<strong>`), path chips (`button.ast-chip[data-device][data-port]`), numbered checks with checkboxes (state local), notes, suggestion card (`#ast-suggest-yes`, `#ast-suggest-no`), "AI notes — verify" block when `llm.used`; offline → message "The assistant needs the server" plus local `traceLocal` path suggestions for any device named in the question.
- `js/views-admin.js`: `mountImports`, `mountHistory`, `mountBuilds`, `mountSettings` per FR-UX-07/FR-IMP-10/FR-HIST/FR-USER-08. Settings › **Trash** (P1C; tab `trash`, admin only via `TAB_ROLES`): card `[data-card=trash]` with a DataTable (key `settings.trash`, rows `[data-trash=<name>]`: project, trashed (relative time), by, rooms, devices, actions) over `api.listTrash()` → `{items, retention_days}`; `button[data-act=restore]` *Restore* (`api.restoreTrash`, then `ctx.reloadProjects()`), `button.danger[data-act=purge]` *Delete permanently* behind a scoped confirm (`api.purgeTrash`); empty state *Nothing in the trash.* names the retention days; load failures use `inlineError` with Retry. The project danger zone's delete is now `button[data-act=trash-project]` *Move to trash* (prompt: type the project name; copy points at Settings › Trash) and calls `api.deleteProject(name)` without `purge`.
- Short-code search (P1C, FR-SRCH-05): `search-core.isShortCodeQuery(q)` (8 base-32 chars, optional dash) makes `search.js` run `api.lookupCode(q)` alongside the text search and lead the hit list with the `codeHit` (title = device name, subtitle `Code XXXX-XXXX · <room>`, `match: 'code'`); offline, `localCodeHits(doc, q)` matches `device.short_code` in the document.
- Search palette: `js/search.js` (§6.13.6; it moved out of `app.js`), opened by `#app-search` and ⌘/Ctrl+K.

### 6.9 Tracing & assistant algorithms (W6 Python; W3 client `traceLocal` implements §6.9.1–6.9.4)

#### 6.9.1 Graph nodes

Node = port ref `dev:port`; plus a virtual node `dev:*` per device used by device-level cable endpoints (connected internally to every port of the device both ways, subject to the discipline filter). Channel-level nodes (`fathom/trace.py`, `parse_ref` / `hop_ref`): **sub-channels** of a multichannel port `dev:port#tx6` (signal leaving the device on channel 6) / `dev:port#rx17` (entering on channel 17), created only when something refers to them (an overlay route with `ch`, a console link, `indexed` routing); **console channels** `dev:@in-12` (§4.3.17; rack sides carry their tag, `dev:@fx-1.A`); and **text** nodes `dev:~REC 1` for console ports the importer could not map. `split_ref` reports a sub-channel node's port and `None` for the others, so port-level consumers keep working.

#### 6.9.2 Discipline

`carries(medium)` from vocab. With discipline D, an edge is usable iff its medium (cable edges: cable medium; internal edges: both port media; route edges: route medium) carries D. No discipline = all edges.

#### 6.9.3 Edges

1. Cable: `from → to`; also `to → from` when `cable.bidirectional` or both ports are `io`.
2. Internal (per device, by routing mode §4.4.5; the mode is the device's `routing`, else its library template's, else the kind default): `in/io → out/io`. `indexed` devices get channel-level edges instead (`analog-in-6 → dante-primary#tx6`, `dante-primary#rx17 → aes-out-1-2`), wired to the first stream port per medium only (Dante Secondary is not a second copy of every path). A device with console `channel_links` gets **no** generic internal edges: its links are its routing.
3. Overlay routes (when an overlay is supplied): `route.from → route.to` (device-level `dev:*` when a route port is missing); when both ends carry an integer `ch`, also `from.port#tx<ch> → to.port#rx<ch>`.
4. Console links (`console.effective_channels`: the device's own set once applied, else the overlay's; audio only): one `link` edge per `input_patch` / `send` / `output_patch` / `direct_out` / `insert_send` / `insert_return` (a `{port, ch}` endpoint is `#rx` at `from` and `#tx` at `to`, a mono port is the port node, `text` is a text node); `dca` / `mute` links are control only — they annotate the member channel's hop (`dca: [{channel, title}]`) and are never traversed.
5. Excluded devices (state filter) contribute no nodes. Sub-channel nodes have no edge to their port node: a port-level cable trace stops at `CL5 · Dante Primary` and a channel-level trace stops at `Dante Primary 6` with a gap, instead of pretending every channel reaches every other.

#### 6.9.4 Search and rendering

- `upstream(start)`: DFS over reversed edges producing simple paths from a *source* (node with no further usable incoming edge, or depth 24) to `start`; `downstream` symmetric; `paths(a, b)` DFS a→b. Limit 50 paths, shortest first, ties by lexical order of hop refs (deterministic).
- A **path** = ordered list of hops `[{device, port}]` (cable and internal steps both appear as consecutive hops) + the cable ids traversed + `via` (one entry per hop naming the edge into it: `""`, `cable:<id>`, `internal`, `device`, `route:dante`, `link:input_patch`, `link:send`, …). Plain port / device hops stay exactly `{device, port}`; channel-level hops add `kind`: `port_channel` (`{device, port, ch, dir, name?}` — `name` is the Dante channel name from `overlay.channel_labels`), `channel` (`{device, port: null, channel, channel_kind, title, name?, tag?, dca?}`), `text` (`{device, text}`), and, with the DCA toggle (`with_dca_hops`, API `dca=1`, CLI `--dca`), control hops `{kind: "dca", channel, title, control: true}` inserted after a member channel (`via` `link:dca`).
- **Gaps.** `upstream` / `downstream` paths whose end has no usable edge at all in the walk direction carry `incomplete: "<reason>"` (`gap_reason`): a transmit sub-channel with no Dante subscriber, a receive sub-channel with no transmitter or (on a device with console data) not patched to a channel, a sub-channel arriving at / leaving a `console` that has no console data at all ("no console patch data for …"; other devices without channel data end naturally), an input channel with no recorded sends (nothing is assumed — a CL5 CSV export has no send levels) or no input patch, a bus with no output patch or nothing sent to it, an unpatched rack side, or an output / input connector with no cable on a device that normally passes signal on (routing not `none` / `passthrough`). An end whose only continuation loops back into the path (insert send + return) is a natural end. A channel-level start with no edge at all returns a single-hop path with its `incomplete` instead of nothing; plain ports keep returning `[]`.
- **Start refs.** `dev:port` on a multichannel port also starts from its sub-channels on that side; `dev:port#17` without `rx`/`tx` leaves on `tx` when tracing downstream / as the A side and arrives on `rx` otherwise; `dev:@fx-1` stands for both rack sides; a bare device expands to its ports **and** their sub-channels. `resolve_ref(doc, text, overlay)` accepts `CL5 · CH 12`, `CL5 · Bass` (unique console name), `foh:in-12`, `CL5 · MIX 9`, `CL5 · ST L`, `Rio · Dante 6`, `Rio · Dante Primary 6`, `rio:dante-primary#tx6` in addition to the port forms, and the API's own node refs `foh:@in-12` / `foh:@fx-1.A` (the channel must exist) and `foh:~REC 1`; a port label / name wins, then a console channel, then a stream-port sub-channel (`Dante 1` is channel 1, not the port whose group index is 1), then the group-index port rule.
- **Path text**: for each hop `h_i`: if `i == last` and the hop is an input of the final device → `device.name`; else if `i == 0` or `h_i.device != h_{i-1}.device` → `"<device.name> · <local>"`; else → `"<local>"`, where `<local>` is the port label or name, `"<port label> <ch> “<Dante name>”"` for a sub-channel, `console.channel_title` (`CH 12 · Bass`, plus ` (via DCA 1 · BAND)` when the channel has DCA membership and no DCA hop follows), `(via DCA 1 · BAND)` for a DCA hop, or the text. Join with `" → "`; an incomplete path appends ` ⚠ <reason>`. Example (fixture in `tests/test_trace_channels.py`): `Bass DI · Out → Rio3224 SL · Analog In 6 → Dante Primary 6 “Bass 17” → FOH CL5 · Dante Primary 17 “17 Bass” → CH 12 · Bass (via DCA 1 · BAND) → ST L → Dante Primary 63 “Main L” → Rio1608 FOH · Dante Primary 1 “FOH/SIDE FILLS L” → Analog Out 1 → d&b D80 · In 1 → Out A → PA Left`.
- **Trimming for answers**: the answer path is trimmed to start at the branch point's output port (§6.9.5) so the fixture text is exactly `Audio Rack 1 · Stream → ATEM Mini · Stream → USB Stream Out → Restream`.

#### 6.9.5 Assistant pipeline (`assistant.answer`)

1. **Normalize** the question (lowercase, collapse spaces, strip punctuation except `·:-`).
2. **Intent type**: `trace` if it matches `^(how does|how do|what feeds|where does|what is fed by|trace)\b`; `locate` for `^(where is|where's|which rack|what rack)\b`; `describe` for `^(what is on|what's on|what is plugged into)\b`; else `troubleshoot`.
3. **Symptom** (troubleshoot): first lexicon match in `checklists/symptoms.json` (Appendix F.1); none → `general`.
4. **Entities**: split clauses on `but|and|,|;|however|although|while`. In each clause, first remove the matched symptom phrase, then find mentions via (a) `checklists/synonyms.json` role phrases (Appendix F.2: e.g. "livestream" → kinds `stream, encoder`; "house sound" → kinds `speaker, amp, pa`), resolved to devices of those kinds in the room (all devices of the kind, document order); (b) search hits (`search.search(index, phrase)`) with score ≥ 60 for n-grams (1–4 words) of what remains after removing role phrases already matched, stopwords (`symptoms.json` `stopwords`) and discipline words (`symptoms.json` `discipline_words`), preferring longest phrases; ports "input 3" bind to the preceding device mention. (So "the livestream has no audio" never matches "Audio Rack 1".)
5. **Working vs failing**: a clause containing a positive marker (`fine|works|working|ok|okay|good|is great|no problem`) yields `working` entities; the remaining entities are `targets`. If the question has a symptom but no target, use the room's endpoints of the symptom discipline (devices with kind routing `none` or no outgoing usable edges) as targets with confidence `low`.
6. **Discipline**: symptom's discipline (`no_audio`/`noise`/`feedback` → audio; `no_video`/`flicker` → video; `lighting_no_response` → lighting; `no_network` → network; `no_power` → power); else the targets' discipline.
7. **Trace**: for each target, `upstream` paths in discipline D from each target input port that has a cable. For each working entity, upstream paths likewise; `W` = set of nodes on working paths.
8. **Branch & suspects**: for a target path P (source → target), the **branch hop** = the last hop of P (walking from the source) whose node is in `W`. Suspect segment = the hops after the branch hop, but starting at the branch device's **output** port that P leaves through (for the fixture: `audio-rack-1:analog-out-4`). Paths are de-duplicated by suspect segment. Ranking: (i) paths with a branch hop in W first; (ii) a path without any W node whose source is an input port with no incoming cable on a device whose kind is not a source kind (`mic, source, video_source, camera, computer, lighting_console, touch_panel`) is **not** a candidate — it becomes a `notes` line "<port> on <device> also carries <discipline>, but its source (<source device> · <source port label>) is not patched."; (iii) shorter suspect segment; (iv) lexical order of hop refs. `paths[0]` = best with `role: "suspect"`; up to 2 more as `role: "context"`. Without any W node the whole path (from its source) is the suspect segment. `branch = {"device", "reason": "Shared with <first working device whose paths contain the branch hop>, which works"}`.
9. **Checks** (three passes, de-duplicated by check id, cap 8): pass 1, for each suspect hop in order: the hop device's template checks (`template.checks`, template resolved via `device.template`), then its kind checks (`checklists/kinds.json[kind]`); pass 2, for each cable in the suspect segment in order: medium checks (`checklists/media.json[medium]`); pass 3, generic checks (`checklists/generic.json`) only while fewer than 3 checks exist. A check applies iff its `symptoms` contain the symptom (or `"*"`) and every key of `when` matches the hop: `port_dir` (str or list), `medium` (list, port medium), `kind` (list), `has_working` (bool). Placeholders: `{device}`, `{port}` (hop port label or name), `{next_device}`, `{next_port}`, `{prev_device}`, `{working}` = name of the working device named in `branch.reason` (else the first working device), `{feeds}` = `" — it feeds {next_device} separately from {working}"` when a working device exists, else `""`, `{medium}` = medium label. `source` = `kinds:<kind>/<id>`, `media:<medium>/<id>`, `generic/<id>` or `template:<template id>/<id>`.
10. **Summary**: troubleshoot → `"Your <discipline-noun> takes its own path: " + bolded first two hop labels + rest + "."` when a branch exists (discipline-noun: audio → "stream audio" when the target kind is stream/encoder, else "<target name> audio"; video → "picture"); else `"Here is how the signal reaches <target>: <path text>."`; trace → `"<n> path(s) from <a> to <b>"`; nothing resolved → apology + unresolved suggestions.
11. **Suggestion**: if a suspect path exists, propose a note on the first suspect **input** port: `"<Discipline> feed: <branch device name> → <device name> · <first template/kind check keyword>"` — for the fixture `Stream feed: Audio Rack 1 → ATEM Mini · check Audio tab` (the keyword phrase comes from the check's optional `"note"` field, e.g. `"check Audio tab"`; the leading word is the target port label "Stream" when the port has a label, else the discipline name). Skip if that port's note already contains the text. Ops = one `merge` of the device's full `ports` array with that port's `note` set (appending `"; "` to an existing note).
12. **LLM** (§6.9.6) when allowed; **confidence** per §5.10.

#### 6.9.6 LLM grounding (`llm.py`)

- `llm.configured()` = `FATHOM_LLM_URL` and `FATHOM_LLM_MODEL` set. `llm.info()` = `{"configured", "model", "host"}` (no key).
- `llm.chat(messages, temperature=0.2, max_tokens=700, timeout=None) -> str`: `POST <url>/chat/completions` JSON `{"model", "messages", "temperature", "max_tokens", "stream": false}`, headers `Content-Type: application/json`, `Authorization: Bearer <key>` when set; returns `choices[0].message.content`; raises `LLMError` on HTTP error, timeout, bad JSON.
- Messages: system = "You are Fathom's AV/lighting troubleshooting assistant. Answer ONLY from the SYSTEM DATA. Name devices and ports exactly as given. If the data does not say, say you don't know. Keep the numbered checks; you may add at most 3 more, marked 'extra'. Never invent equipment." User = question + `"\n\nSYSTEM DATA (JSON):\n"` + JSON of `{room, intent, paths (with hop labels, cables with medium/type/tag), suspects with their device kind/model/ports/notes, checks, working endpoints}` truncated to `FATHOM_LLM_MAX_CONTEXT` chars (drop context paths, then port lists, never the suspect path) + prior `history` (last 6 turns).
- Called only when `use_llm` and `settings.assistant.llm != false` and configured. The returned text is stored in `llm.text`; the deterministic fields are unchanged.

### 6.10 Service worker & manifest (W1 files, W5 registration)

`sw.js` (W1, SHELL): `const VERSION = '0.4.0'`, cache names `fathom-shell-<VERSION>`, `fathom-pages-<VERSION>`. `VERSION` is bumped whenever the precache list or a precached file's contract changes, so `activate` drops the old caches; it is no longer equal to `fathom.__version__` (`0.3.0`). The server still replaces a `__FATHOM_VERSION__` placeholder when serving `/sw.js`, but the file holds a literal version. Precache list (exact; relative to the SW scope; `const PRECACHE` in `sw.js`):

```text
./  static/app.html  static/login.html  static/css/app.css  static/css/patchview.css  static/css/plan.css
static/js/app.js  static/js/api.js  static/js/model-core.js  static/js/inspector.js  static/js/assistant-ui.js
static/js/patchtable.js  static/js/patchtable-core.js  static/js/patchview.js  static/js/patchview-core.js
static/js/floorplan.js  static/js/floorplan-core.js  static/js/rack.js  static/js/rack-core.js
static/js/schedules.js  static/js/inventory.js  static/js/views-admin.js  static/js/presets-core.js  static/js/suggest-ui.js
static/js/views-sop.js  static/css/sop.css  static/js/console-core.js  static/js/trace-ui.js  static/css/trace.css
static/icons/icon-192.png  manifest.webmanifest
static/js/router-core.js  static/js/dom.js  static/js/explorer.js  static/js/explorer-core.js
static/js/entity-header.js  static/js/entity-core.js  static/js/datatable.js  static/js/datatable-core.js
static/js/drawer.js  static/js/drawer-core.js  static/js/search.js  static/js/search-core.js
static/js/home.js  static/js/home-core.js  static/js/feedback.js  static/js/feedback-core.js
static/js/wizard.js  static/js/wizard-core.js  static/js/page-device.js  static/js/page-room.js
static/js/page-rack.js  static/js/views-discovery.js  static/js/merge-ui.js
static/css/explorer.css  static/css/entity-header.css  static/css/datatable.css  static/css/drawer.css
static/css/search.css  static/css/home.css  static/css/feedback.css  static/css/wizard.css
static/css/page-device.css  static/css/page-room.css  static/css/rack.css  static/css/inventory.css
static/css/schedules.css  static/css/admin.css  static/css/discovery.css  static/css/inspector.css
static/css/patchtable.css
```

Every file under `static/js/` (except `package.json`) and `static/css/` is precached, so every view works offline once the shell has loaded online.

Precache uses `cache.addAll` per file with individual try/catch (a missing file must not break install). Strategies: navigations under `p/` and `s/` → network-first (3 s timeout) then cache; `GET api/v2/projects/<n>` and `api/v2/meta` → network-first then cache (response header `X-Fathom-Offline: 1` added when served from cache so the shell switches to read-only offline mode); `static/**` → stale-while-revalidate; everything else → network only. `activate` deletes caches of other versions. Message `{type: "fathom:prefetch", urls}` → fetch + cache each (pages cache), reply via `event.source.postMessage({type: "fathom:prefetched", ok: n, failed: [urls]})`. `{type: "fathom:skip-waiting"}` → `skipWaiting()`.

Registration (W5, `app.js` and viewer pages): only if `'serviceWorker' in navigator && window.isSecureContext && location.protocol !== 'file:'`; `navigator.serviceWorker.register(<app root> + 'sw.js', {scope: <app root>})`; viewer pages get `<app root>` from `render_html(..., base_url=...)`. When not a secure context, Settings shows "Offline mode needs HTTPS (or localhost)".

`manifest.webmanifest` (W1) per FR-MOB-04; icons in `fathom/static/icons/`: `icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, `apple-touch-icon.png` (180), `favicon.ico` (32×32 PNG-in-ICO or plain PNG served as `image/png`); simple design: accent "F" glyph or three stacked bars on `#0b1020`. W1 generates them with a stdlib PNG writer (`zlib` + `struct`) once; the generator script is not shipped.

### 6.11 Mobile & iOS rules (all frontend units)

1. Layout heights: `height: 100vh; height: 100dvh;` (fallback first); `min-height: -webkit-fill-available` for the body on iOS < 15.4.
2. `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`; pad top bar/bottom bar with `env(safe-area-inset-*)`.
3. No hover-only affordances; tooltips also on tap/long-press; `@media (hover: none)` shows always-visible action buttons.
4. Canvases (`.pv-viewport`, `.fp-viewport`, `.rk-viewport`): `touch-action: none`; listen to `gesturestart`/`gesturechange`/`gestureend` with `{passive: false}` and `preventDefault()`; `touchmove` with `{passive: false}` only on the canvas and only `preventDefault()` when ≥ 2 touches or a drag is active. Page-level pinch zoom stays enabled elsewhere.
5. Pointer Events everywhere (`pointerdown/move/up/cancel`), `setPointerCapture` on drag start, cancel cleanly on `pointercancel`/`lostpointercapture`; at most 2 active pointers tracked for pinch.
6. Long-press = 500 ms without moving > 8 px → context menu (also suppress the iOS callout with `-webkit-touch-callout: none` on draggables).
7. Form controls ≥ 16 px font; `inputmode` on numeric fields (`decimal`, `numeric`); date fields use `<input type="date">`.
8. Hit targets ≥ 44 × 44 px under `@media (pointer: coarse)` (port rows grow to 32 px height on touch, with a 44 px invisible hit area for dots).
9. Avoid `position: fixed` inputs at the bottom on iOS (keyboard overlap); sheets use `position: fixed` with `bottom: 0` but scroll their content.
10. File inputs for photos: `accept="image/*"` with `capture="environment"` offered as a separate "Take photo" button.

### 6.12 Harnesses & isolation

Each frontend unit ships a harness page under `fathom/static/dev/` that works when served by `fathom serve` (`/static/dev/<name>.html`, loopback or `FATHOM_DEV=1`), loads `fixture-v2.json` (or `?devices=N&cables=M` via `fixture-gen.js`), builds a store with `createStore`, a fake ctx (pickers resolve to the first candidate, `toast` logs) and mounts the module. Every harness and the app set `window.__fathomErrors = []` and push from `window.onerror`, `unhandledrejection` and a `console.error` wrapper; when the URL has `?smoke=1`, after the first render plus 1000 ms they write `document.documentElement.setAttribute('data-smoke', JSON.stringify({ready: true, errors: window.__fathomErrors, stats: window.__pvStats || null}))` (T2 reads this via `--dump-dom`).

| Harness | Owner | Mounts |
| --- | --- | --- |
| `dev/patchview.html` | W3 | `patchview.js` (`?devices=150&cables=600` uses `fixture-gen.js`) |
| `dev/floorplan.html`, `dev/rack.html`, `dev/schedules.html` | W4 | `floorplan.js` (with `samples/floorplans` images served from `/static/dev/plans/` copies), `rack.js`, `schedules.js` + `inventory.js` |
| `dev/patchtable.html`, `dev/index.html` | W5 | `patchtable.js`; index links all harnesses (with their query variants), the app, the viewer pages and `/login` |
| `dev/datatable.html` + `datatable-harness.js` | TABLE | `createTable` bound to the hash query; `?rows=N` synthetic rows (default 240), `?cards=1` card mode at sm, `?readonly=1`, `?appdialog=1` drill-down through `app.js` `openDialog` |
| `dev/explorer.html` + `explorer-harness.js` | EXPLORER | `mountExplorer` over the fixture devices; `?many=N` extra items, `?empty=1`, `?key=<k>` storage key (default `harness-devices`) |
| `dev/entity.html` + `entity-harness.js` | ENTITY | `mountEntityHeader` + `entity-core` facts, tabs and summary cards; hash `#/<device\|room\|rack>/<id>[/<tab>]`; `?rows=N`; `window.__eh` |
| `dev/drawer.html` + `drawer-harness.js` | DRAWER | `createDrawer` on a shell-shaped `#app-inspector`; state in the hash (`sel`, `sec`, `drawer=0`) written with `drawerHistory` |
| `dev/search.html` + `search-harness.js` | SEARCH | `openSearch` against the server (`?project=`, default `campus-demo`) or the fixture offline (`?fixture=1`); `?role=viewer`, `?recent=`, `?q=&cat=`; navigations in `window.__sr` |
| `dev/feedback.html` + `feedback-harness.js` | FEEDBACK | every `feedback.js` state side by side, notices and bell; `window.__fb` |
| `dev/wizard.html` + `wizard-harness.js` | WIZARD | `openWizard` and `bulkAdd` with a `makeCtx` ctx; `?open=devices\|cables\|generic`, `&sample=1`, `&step=…`, `?readonly=1`; commits in `window.__wz` |

`fathom/static/dev/fixture-gen.js` (W3): `export function makeFixture({devices = 150, cables = 600, seed = 1} = {})` → a valid v2 doc (single room `main`, mixed disciplines, 4–24 ports per device, cables only between compatible ports, deterministic for a seed). T2 tests validate it with `validateLocal` (0 errors).

### 6.13 Shared UI components (UI uplift; `docs/ui-audit.md` B.2, D1–D11)

Each component is a DOM module plus, where it has logic, a pure `*-core.js` (§6.1 rules: Node-importable, tested by `tests/js/<name>-core.test.mjs`, the DOM contract by `tests/js/<name>-contract.test.mjs` and the browser behaviour by `tests/test_ui_<name>.py`). Class prefixes per D11 (§6.1). Every view builds its lists, pages, drawers and states from these; a view does not re-implement one.

#### 6.13.1 Router core — `js/router-core.js` (ROUTER)

Pure (no DOM, timers or storage globals; storage is injected).

```js
export const BP = {md: 700, lg: 1100};
export function layoutFor(width) {}          // 'sm' (< 700) | 'md' (700–1099) | 'lg' (>= 1100)
export const DEFAULT_VIEW = 'home';
export const VIEW_SHAPES = {devices: ['id','tab','sub'], rooms: ['id','tab'], racks: ['id','tab','sub'], plan: ['id'],
  schedules: ['tab'], imports: ['tab'], settings: ['tab'], discovery: ['tab','sub'], history: ['id']};
export const SECTIONS = [/* {key, label, glyph, views, nav: 'sm'|'all'} — table in §6.4 */];
export const VIEW_ROLES = {};                // view -> minimum role (none today)
export const TAB_ROLES = {settings: {users: 'admin', backups: 'admin', sharing: 'editor'}};
export function canSee(view, role, tab) {}   // role rank viewer < editor < admin
export function sectionOf(view) {}           // section key; unknown views -> 'data'
export function sectionsFor(role) {}         // SECTIONS with only the permitted views; empty sections dropped
export function sectionRoot(key, route, role) {} // Route of the section's first permitted view, or null
export function parseRoute(hash) {}          // -> Route
export function buildRoute(route) {}         // -> '#/…'; trailing empty segments dropped; query values keep : , | / unescaped
export function withQuery(route, patch) {}   // merge query keys; null/undefined/'' deletes
export function mergeRoute(route, partial) {}// a new view clears id/tab/sub/extra; a given query replaces the whole query
export function sameRoute(a, b, ignoreKeys) {} // routes or hashes; empty view == DEFAULT_VIEW
export function selToString(sel) {}          // §6.4 `sel` grammar
export function selFromString(s) {}
export function navMemory(storage) {}        // -> {remember(project, hash), target(project, key, route, role) -> hash|'', clear()}
export function legacyHash(project, room, view, params) {} // app.js buildHash's algorithm; empty view -> DEFAULT_VIEW
```

**Route** = `{project, room, view, id, tab, sub, extra: string[], query: {key: string}}` (all strings; segments decoded; `__proto__` keys ignored). Grammar, query keys and history rules: §6.4 Router. Tests: `tests/js/router-core.test.mjs`, `router-contract.test.mjs`; `tests/test_ui_router.py` smoke-tests the shared Chrome helper `tests/_ui.py`.

#### 6.13.2 Explorer — `js/explorer.js` + `js/explorer-core.js` (EXPLORER)

A filterable, grouped list beside a page (entity pages, plan, racks). Side panel at md/lg, resizable 240–480 px (pointer drag on `.ex-resizer`, 12 px hit area, 20 px under coarse pointers; arrow keys step 16 px) and collapsible to a 56 px rail; at sm a slide-in drawer with `.ex-backdrop`, focus trap and Esc (D4 layer `explorer`). Width and collapse persist per `key` (§6.14).

```js
export function mountExplorer(el, opts) {} // -> handle
// opts: key (storage key, required), title, glyph, items, chips, match(item, q), toolbar, footer(shown, total) | string,
//   rail, selected, onSelect(item), mobileLabel, listId, contentLabel, storage, renderItem(item, base) -> Node,
//   itemAttrs(item) -> {}, headSlot: Node, emptyText: string | (query, total) -> string
// item: {id, label, sub, group, glyph, href, badge, depth}; chip: {key, label, test(item)} (OR within chips, AND with the query)
// toolbar: [{key, label, glyph, title, pressed, run}]; rail: [{key, label, glyph, href, active}] or groups [{items: [...]}]
// handle: {root, side, list, content, search, setItems(items), setRail(rail), setChips(chips), setHeadSlot(node),
//   update(partial), setSelected(id), open(), close(), isOpen(), mode() -> 'side'|'drawer', isCollapsed(),
//   width(), setCollapsed(bool), setWidth(px), relayout(), destroy()}
```

DOM: `div.ex-root` > `aside.ex-side` (`.ex-head` with `.ex-titlebar` (`.ex-title`, `.ex-close`), `input.ex-search`, `.ex-chips` of `button.ex-chip[aria-pressed]`, `.ex-toolbar` of `.ex-tool`; `.ex-slot` head slot; `ul.ex-list[role=listbox]` (id = `listId`) of `li.ex-item[role=option][data-id][aria-selected]` holding `a.ex-item-link` or a `div.ex-item-row`; group headers `.ex-group`; `.ex-foot`; `.ex-collapse`; `.ex-rail` when collapsed), `.ex-resizer`, `.ex-backdrop`, and `section.ex-content` > `div.ex-page` (= `handle.content`, where the page renders). Controls inside a row that must not pick the item carry `[data-ex-ignore]`. `open()`/`close()` act only at sm. `update(partial)` applies items, selected, chips, rail, headSlot, toolbar, footer, emptyText, match, renderItem, itemAttrs and mobileLabel without a remount (key, title and glyph are fixed).

Core: `MIN_WIDTH` 240, `MAX_WIDTH` 480, `DEFAULT_WIDTH` 300, `RAIL_WIDTH` 56, `KEY_STEP` 16, `STORAGE_PREFIX` `'fathom.ui.explorer.'`, `storageKey(key)`, `clampWidth(w)`, `loadExplorer(storage, key)` / `saveExplorer(storage, key, state)` (`{w, c}`), `defaultMatch(item, q)` (label or sub contains q), `filterItems(items, q, activeChipKeys, chips, match)`, `groupItems(items)`, `flattenGroups(groups)`, `nextIndex(count, current, key)` (Arrow/Home/End/PageUp/PageDown), `resizeKey(width, key)`, `dragWidth(startWidth, startX, x)`, `explorerMode(width)` (`'drawer'` at sm, else `'side'`), `footerText(shown, total, footer)`, `openLabel(label, total)`. Harness `dev/explorer.html`. Tests: `test_ui_explorer.py`, `explorer-core.test.mjs`, `explorer-contract.test.mjs`.

#### 6.13.3 Entity header — `js/entity-header.js` + `js/entity-core.js` (ENTITY, D5)

Sticky page header for device, room and rack pages. The header and a sentinel are **prepended** to `host` (the page content must follow inside `host`, since `position: sticky` sticks within its parent). Compact (`.eh--compact`) once the sentinel leaves the scroller and always at sm; compact mode keeps badges and tabs.

```js
export function mountEntityHeader(host, options) {} // -> {el, update(partial), setTab(key), setTabs(tabs, activeTab), isCompact(), destroy()}
// options: kind, id, glyph, title, subtitle, status, facts, badges,
//   actions: [{key, label, primary?, danger?, href? | run}], overflow: [{key, label, danger?, run}] (⋯ menu),
//   tabs: [{key, label, count?, href}], activeTab, thumb, onTab(key)
// facts: [{key?, label, value, href?}]; badges: [{label, level, title?, onClick?}]
```

DOM: `.eh-sentinel`, then `header.eh` > `.eh-bar` (`.eh-main`: `.eh-glyph`, `.eh-titles` (`.eh-title`, `.eh-subtitle`), `.eh-status`, `.eh-badges`, `.eh-facts`; `.eh-actions` of `button.eh-action` or `a.eh-action` (with `href`; `.eh-primary` / danger look kept), `.eh-more-wrap` > `button.eh-more[aria-haspopup=menu]` + `.eh-menu` of `.eh-menu-item`), then `nav.eh-tabs[role=tablist]` of `a.eh-tab[role=tab][data-tab][href][aria-selected]` (with `.eh-count`); `.eh--stuck` while stuck. Tabs are real links (the URL is the state, FR-UX-10); Arrow keys move focus only, Enter follows. `setTabs` changes labels, counts and hrefs in place (a different tab set rebuilds only the strip); `update` with other keys re-renders and restores focus to the same tab, action, ⋯ or badge.

Core: `TAB_LABELS` (`overview`, `ports`, `cables`, `network`, `dmx`, `channels`, `inventory`, `procedures`, `files`, `devices`, `racks`, `plans`, `elevation`), `tabLabel(key)`, `statusPill(status)`, `primaryAddress(device)`, `rackPosition(doc, device)`, `deviceFacts(doc, vocab, device, overlay, opts)`, `roomFacts(doc, room, opts)`, `rackFacts(doc, rack, opts)`, `deviceTabs(doc, device)` (`overview`, `ports`, `cables`, `network`, then `dmx` when the device has DMX and `channels` when it has console channels, then `inventory`, `procedures`, `files`), `roomTabs()` (`overview`, `devices`, `cables`, `racks`, `plans`, `procedures`), `rackTabs()` (`overview`, `elevation`, `devices`, `cables`), `resolveTab(tabs, requested)` → `{tab, redirect}` (missing, empty or unknown → `overview` with `redirect: true`, so the page replaces the URL), `summaryCards(kind, doc, entity, ctxInfo)` (overview drill-down cards; problem counts use problem reports `doc.problems`, never validation results). Pages: `page-device.js` (`pd-`), `page-room.js` (`pr-`), `page-rack.js` (`rp-`). Harness `dev/entity.html`. Tests: `test_ui_entity.py`, `test_ui_pdev.py`, `test_ui_proom.py`, `test_ui_rk.py`, `entity-core.test.mjs`, `entity-contract.test.mjs`.

#### 6.13.4 DataTable — `js/datatable.js` + `js/datatable-core.js` (TABLE, D8, D9)

Every read list of records renders through `createTable`; drill-down counts open `openTableDialog`. **Exemptions (D9)**: the patch table's blocks mode (`.pt-block table`), the label sheet (`.sch-labels`), Markdown tables in SOP pages (`.md-table`), inspector editor grids, picker dialogs and the map groups dialog, the search list `#app-palette-list`, explorer lists, the drag-source lists `#rk-unracked` and `#fp-unplaced`, the JSON view and the server-rendered viewer pages.

```js
export { PAGE_SIZES, EMPTY } from './datatable-core.js';
export function createTable(host, opts) {} // -> handle
// opts: key (required), scope, caption, columns, rows, rowId(row), onRow(row, ev), rowAttrs(row) -> {}, rowClass(row),
//   groupBy, groupOrder, selectable (bool | fn(row)), bulkActions: [{label, danger?, run(rows)}], actions (toolbar nodes),
//   ids: {root, table, search, csv, columns, selectAll, filters: {colKey: id}}, url: {get() -> query, set(patch, {replace})},
//   urlFilters: 'authoritative', pageSizes, pageSize, sticky, density, empty: {title, text, action}, csvName, highlight,
//   storage, persist (false = no localStorage), noun: {one, many}, bulkNoun: {one, many}, readOnly (bool | fn),
//   tableClass, cards (card layout at sm, opt-in), search: false, csv: false, searchPlaceholder
// column: {key, header, value(row), cell(row) -> Node|string, csv: fn | false, sortable, filterable, searchable,
//   hideOnMobile, hidden, align: 'right'|'center', width, sticky}
// handle: {root, setRows(rows), setLoading(bool), setError(err, retry), setHighlight(id, {scroll}), setCsvName(name),
//   getState(), setState(partial), readUrl(), info() -> {total, filtered, page, pages, pageSize},
//   getSelection(), clearSelection(), refresh(), destroy()}
// events on root: 'dt:state' (state snapshot), 'dt:select' ({ids}), 'dt:row' ({id, row}; Enter or click, not from controls)
export function openTableDialog(ctx, opts) {} // {title, columns, rows, onRow, key, rowId, noun, empty, csvName, pageSize,
//   storage, rowAttrs, rowClass, tableClass}; persists only pageSize, hidden and density
```

DOM: `div.dt-root` > `.dt-toolbar` (`input.dt-search`, `.dt-filters` of `button.dt-filter` per visible filterable column opening a `.dt-pop` value list, `.dt-cols` column chooser + density, `a.dt-csv[role=button][download]` whose `href` is a Blob URL of the filtered rows as CSV (visible columns, `csv` overrides), `.dt-count`), `.dt-bulk` (`.dt-bulk-count`, `.dt-bulk-actions`) while rows are selected, `.dt-scroll` > `table.dt-table` (`thead` sticky, `th[scope=col]` with `.dt-sort`; `tr.dt-row[data-id]`, `.dt-hl` highlighted, `.dt-group` headers; `.dt-hide-sm` mobile-hidden cells; `.dt-cards` card mode), `.dt-pager` (page size `.dt-size`, `.dt-range`, `.dt-pager-nav`), `.dt-empty` / `.dt-error` (with `.dt-retry`) / `.dt-skel`. Row clicks ignore `input, button, a, select, textarea, label, summary, [contenteditable], [data-dt-ignore]`. Space toggles selection; select-all selects the whole filtered set across pages. `cell(row)` may return the same Node every call; the table re-parents it so its state survives re-renders.

State: `{q, sort: {col, dir: 1|-1} | null, filters: {col: [values]}, page, pageSize, hidden: [col], density: 'normal'|'compact', extra: {}}`. URL (with `url`): `q`, `sort` (`col`, or `-col` descending), `f.<col>` (values joined with `|`; `\` escapes `\ | ~`; `~` = the `EMPTY` value `(empty)`), `pg` (only when > 1); every table write *replaces*. Storage: `fathom.ui.table.<scope>.<key>` keeps `{v, sort, filters, pageSize, hidden, density, extra}`; `q` and `page` are URL-only. Without `f.*` in the URL stored filters apply, unless `urlFilters: 'authoritative'` (then the URL alone decides). Core: `PAGE_SIZES` `[25, 50, 100, 200]`, `DEFAULT_PAGE_SIZE` 50, `STATE_VERSION` 1, `EMPTY` `'(empty)'`, `DENSITIES`, `textOf(v)`, `normalizeColumns(cols)`, `compareValues(a, b)` (numeric-aware; empty values sort last), `createIndex(rows, columns)`, `cleanFilters(filters, columns)`, `defaultState(columns, opts)`, `mergeState(state, partial, columns)`, `matchesQuery(row, columns, q, hidden)`, `applyState(rows, columns, state, opts)` → `{rows, total, filtered, pageRows, page, …}` (opts `index`, `groupBy`, `groupOrder`), `distinctValues(rows, column, index)`, `selectAllFiltered(rows, columns, state, rowId, canSelect)`, `toCsv(columns, rows)` (RFC 4180, `\r\n`), `isTableParam(key)` (`q`, `sort`, `pg`, `f.*`), `stateToParams(state)`, `paramsToState(query, columns)`, `urlPatch(query, state)`, `storageKey(scope, key)`, `loadState(storage, scope, key, columns, defaults)`, `saveState(storage, scope, key, state)`. Harness `dev/datatable.html`. Tests: `test_ui_datatable.py`, `datatable-core.test.mjs`, `datatable-contract.test.mjs`.

#### 6.13.5 Drawer — `js/drawer.js` + `js/drawer-core.js` (DRAWER, D3, D4)

Owns the inspector host `#app-inspector`: mode classes, roles, backdrop, focus trap, Esc and focus return; `inspector.js` renders its content (§6.8).

```js
export function createDrawer(host, {label, onClose(reason), layers}) {}
// -> {el, open({focus = true}), close(), isOpen(), mode() -> 'docked'|'sheet'|'full', relayout(width?), destroy()}
export function domLayers(doc, host) {} // -> {palette, dialog, trace, assistant, explorer}: which layers are open in the DOM
// (dialog = any rendered [role=dialog][aria-modal=true] outside the host and the other layers)
```

Modes by width: **docked** ≥ 1100 px (beside `#app-main`, not modal; the parent gets `.dr-docked-open`), **sheet** 700–1099 px (right-hand sheet), **full** < 700 px (88dvh bottom sheet); sheet and full are modal (`role=dialog`, `aria-modal`, `.dr-backdrop`, focus trap). Classes on the host: `.dr-host`, `.dr-docked|.dr-sheet|.dr-full`, `.dr-open`. Esc (D4 order, topmost first: palette, dialog, trace, assistant, explorer, drawer): the drawer closes only when it is the top layer; inside a text field the first Esc blurs it and the second closes; a docked drawer closes on Esc only while focus is inside it. Motion respects `prefers-reduced-motion`.

Core: `drawerMode(width)`, `isModal(mode)`, `parseDrawer(query)` → `{sel, section, open}` (only `drawer=0` keeps a selection with the drawer closed), `drawerParams(state)` (query patch: `sel`, `sec`, `drawer`), `drawerHistory(prev, next)` → `'push'` (opening from closed) \| `'replace'` (switching subject or section, closing) \| `null`, `LAYERS`, `topLayer(flags)`, `CANVAS_VIEWS` `['patch', 'plan', 'map']`, `isCanvas(view, route)` (canvas views, plus `racks` with no id or tab `elevation`), `selectionOpensDrawer(view, route, layout, intent)` (intent — list row, search, *Details* — always opens; a canvas selection opens only at lg), `trapIndex(count, current, back)`. In the shell a canvas selection below lg writes `drawer=0` and shows `#app-selbar` (*Details* opens, × clears). Harness `dev/drawer.html`. Tests: `test_ui_drawer.py`, `test_ui_ins.py`, `drawer-core.test.mjs`, `drawer-contract.test.mjs`.

#### 6.13.6 Search — `js/search.js` + `js/search-core.js` (SEARCH, FR-SRCH)

```js
export function openSearch(ctx, {query, category}) {} // -> {root, input, close()}; one palette at a time
export function closeSearch() {}
```

A dropdown anchored under `#app-search` at md/lg, a full-screen sheet at sm. Online it calls `api.search(project, q, {limit: 40, kinds})` (150 ms debounce) and merges network hits computed from the doc; offline, without `api` or on error it uses `augmentLocal` and the footer says *Offline search*. Hits without `status` get it from the doc; `roleFilter` hides draft pages from viewers. With an empty query it lists **Recent** (`recentHits`, from `ctx.recent`) and, in All, **Go to** (one entry per `ctx.sections`). Enter opens `targetFor(hit, route, doc)` through `ctx.navigateRoute` and pushes the target to recents. DOM: `div#app-palette.sr-root[role=dialog]`, `input#app-palette-input.sr-input[role=combobox][aria-expanded][aria-activedescendant]`, `select#app-search-cat.sr-cat`, `ul#app-palette-list.sr-list[role=listbox]` of `li.sr-group` headers and `li.sr-hit[role=option]#sr-hit-<n>[data-hit-kind][data-hit-id]`; the no-results row and `button.sr-all` (search all categories) sit outside the listbox.

Core: `CATEGORIES` (`{key, label, glyph, kinds}`: `all`, `devices` [device], `inventory` [device], `rooms`, `racks`, `ports`, `cables`, `networks` [network, interface], `plans` [floorplan], `procedures` [page], `files` [attachment]), `KIND_ORDER` (= `fathom.search.KIND_ORDER`), `kindsFor(key)`, `categorize(hit)`, `groupHits(hits, cat)` (6 per group in All, 50 in one category), `augmentLocal(doc, q, limit)`, `mergeHits(a, b)`, `roleFilter(hits, role)`, `targetFor(hit, route, doc)` → partial route with `id`, `tab`, `sub` and `query` always set, or `null` (attachment without a device) — targets per FR-SRCH-02, `recentType(hit)`, `recentHits(doc, recent)`, `moveActive(count, index, delta)`, `noMatchText(q, cat)`. Harness `dev/search.html`. Tests: `test_ui_search.py`, `test_ui_shell.py::test_search_palette_keyboard`, `test_search_kinds.py`, `search-core.test.mjs`, `search-contract.test.mjs`.

#### 6.13.7 Home — `js/home.js` + `js/home-core.js` (HOME, FR-UX-13)

`mount(el, ctx)` → `{route(), refresh(), destroy()}`; the `home` view and `DEFAULT_VIEW`. Renders `div.hm-root`: `.hm-head` (`.hm-kicker`, `h1.hm-title` project title, `.hm-lede` counts), `section.hm-sections` > `.hm-grid` of `a.hm-card[data-section]` (one per `ctx.sections`, copy from `SECTION_COPY`), `section.hm-rooms` of `a.hm-room[data-room]` with `.hm-links` (`a.hm-link[data-link]`: `patch`, then `plan`, `racks`, `sop` when the room has them, and `room` (the room page)), `section.hm-recent` / `.hm-strip` of `a[data-type][data-id]` (recents, newest first), `section.hm-projects` of `a.hm-project`, and `.hm-start` for an empty project. Every card is a real `<a href>` from `ctx.routeHref`. It reads `fathom.ui.recent.<project>` directly (through `recentKey`) when `ctx.recent` is not given; the projects section shows a skeleton, then an inline error with Retry (`ctx.projectsStatus`, `ctx.reloadProjects`). Core: `SECTION_COPY`, `RECENT_TYPES` (`device`, `room`, `rack`, `page`), `RECENT_MAX` 8, `RECENT_LABELS`, `recentKey(project)`, `countsText(devices, cables)`, `projectTitle(doc, name)`, `sectionCards(sections)`, `recentInput(lists, stored)`, `recentStrip(doc, recent)`, `roomCards(doc, recent, pages)`, `projectCards(projects, current)`. Tests: `test_ui_home.py`, `home-core.test.mjs`, `home-contract.test.mjs`.

#### 6.13.8 Feedback — `js/feedback.js` + `js/feedback-core.js` (FEEDBACK, FR-UX-14)

```js
export function skeleton(kind, n) {}        // kind table|cards|page|list -> div.fb-skeleton.fb-skeleton-<kind>[aria-busy=true]
export function emptyState({title, text, action, secondary}) {} // action/secondary: Node | string | {label, href} | {label, run}
export function inlineError(err, retry, {compact}) {} // div.fb-error[role=alert] (.fb-error-offline offline) + button.fb-retry
export { inlineError as errorState };
export function confirmScope(ctx, {verb, count, noun: {one, many}, scope, danger, detail, ok, title}) {} // -> Promise<bool>
export function staleBadge({fetchedAt, fetchedRev, currentRev, onRefresh, label, always, now}) {}
//   -> span.fb-stale (+ .fb-is-stale, data-reason age|revision) with update(patch), refresh(), destroy(); re-checks every 30 s
export function reviewBadge({count, label, title, onClick}) {} // -> button.fb-review ('<count> <label>'), or null when count <= 0
export function createNotices(storage, project, opts) {} // -> {key, add(n), list(), unread(), markRead(id), markAllRead(), clear(), subscribe(fn)}
export function mountBell(button, countEl, notices, ctx) {}
//   -> {open(), close(), toggle(), render(), isOpen(), destroy(), pop, menu}; the popover .fb-bell-pop is appended to body
```

Rules: loading shows a skeleton, never a blank pane; an empty list says what is missing and offers the next action; a failed load or write shows `inlineError` beside the content with Retry (a toast alone is not enough); bulk and destructive changes confirm with `confirmScope` naming verb, count, noun and scope (*Delete 3 devices from Main Auditorium?*); overlay-derived data carries a stale badge (stale after `STALE_AFTER_MS` = 15 min or when the project revision moved); review badges (duplicates, open problems) jump to their section. Notices (`{id, level, text, href, t, read}`, newest first, max `MAX_NOTICES` 50; the same text again within `NOTICE_DEDUPE_MS` 60 s is dropped) persist per project in sessionStorage; the shell posts restored offline edits, overlay refresh failures and finished or failed builds. Core: `STALE_AFTER_MS`, `NOTICE_DEDUPE_MS`, `MAX_NOTICES`, `NOTICES_PREFIX` `'fathom.ui.notices.'`, `relTime(ms, now)`, `freshText(fetchedAt, now, stale, label)`, `freshness(fetchedAt, now, fetchedRev, currentRev)` → `{stale, reason, text}`, `scopeText(o)`, `addNotice(list, n, now)`, `markRead(list, id)`, `markAllRead(list)`, `unreadCount(list)`, `noticesKey(project)`, `parseNotices(raw)`, `bellLabel(unread)`, `countText(unread)`, `errorInfo(err, online)` → `{kind: 'offline'|'server'|'error', title, message}`, `SKELETON_KINDS`, `skeletonSpec(kind, n)`. Harness `dev/feedback.html`. Tests: `test_ui_feedback.py`, `test_ui_states_*.py`, `feedback-core.test.mjs`, `feedback-contract.test.mjs`.

#### 6.13.9 Wizard — `js/wizard.js` + `js/wizard-core.js` (WIZARD)

```js
export function openWizard(ctx, spec) {} // -> Promise (resolves with the submit result, or null when cancelled)
// spec: {key, title, data, steps: [{key, label, render(body, data, api) -> leave?, validate(data) -> {field: message}}],
//   review(data) -> Node, submit(data) -> Promise, result(res) -> {text, href, hrefLabel}, submitLabel, busyLabel,
//   reviewLabel, resultLabel, discardText, onClose}
// api passed to render: {data, body, box, revalidate(), rerender(), …}
export function bulkAdd(ctx, {kind: 'devices'|'cables', room}) {} // paste -> map -> preview -> review -> result
export function rememberForm(key, data) {}  // localStorage fathom.ui.form.<key>
export function recallForm(key) {}
```

`div.wz-backdrop.app-dialog-backdrop` > `div.wz[role=dialog][aria-modal=true][data-wizard]` (`.wz-head`, `ol.wz-steps` of `li.wz-step[data-step]`, `.wz-body`, `.wz-foot` with `.wz-back`, `.wz-next`). Review and Result steps are appended automatically; Next stays disabled while `validate` returns errors, shown inline under their field via `aria-describedby`; Esc, × and the backdrop ask before discarding entered data; a read-only store opens nothing. `bulkAdd` writes one `ctx.commit(ops, label)` (one undo step through the change queue); its result link (`resultRoute`) opens the new device's page, the devices landing or `schedules/cables` with `hl` = the first new id and `f.id` = all of them (2–50 ids); the column mapping is remembered per kind (`fathom.ui.form.bulk-devices`, `bulk-cables`). Used by `#inv-bulk-add`, `#sch-bulk-add`, the devices landing and the room page's empty Devices tab. Core: `MAX_ROWS` 1000, `FORM_PREFIX` `'fathom.ui.form.'`, `DEVICE_FIELDS`, `CABLE_FIELDS`, `fieldsFor(kind)`, `splitRecords(text, delim)`, `detectDelimiter(text)`, `parsePasted(text, opts)`, `normHeader(text)`, `guessMapping(header, fields)`, `looksLikeHeader(header, fields)`, `mappingErrors(mapping, fields, header)`, `rowObject(cells, mapping)`, `resolveRoom(doc, text)`, `resolveStatus(text, vocab)`, `resolveKind(text, vocab)`, `resolveEndpoint(doc, value, portText)`, `validateDeviceRow(doc, row, opts)`, `deviceRowWarnings(doc, row)`, `validateCableRow(doc, row, opts)`, `cableRowWarnings(doc, row, opts)`, `validateRows(doc, kind, rows, opts)`, `bulkDeviceOps(doc, rows, opts)`, `bulkCableOps(doc, rows, opts)`, `replacedCables(ops)`, `canAdvance(step, errors)`, `plural(n, one, many)`, `reviewText(kind, count, roomName)`, `commitLabel(kind, count)`, `resultRoute(kind, ids)`, `loadForm(storage, key)`, `saveForm(storage, key, data)`, `applyRemembered(header, mapping, remembered, fields)`, `rememberMapping(header, mapping)`. Harness `dev/wizard.html`. Tests: `test_ui_wizard.py`, `wizard-core.test.mjs`, `wizard-contract.test.mjs`.

#### 6.13.10 DOM helpers — `js/dom.js`

```js
export function h(tag, attrs, children) {} // element; attrs: class, text, html, on<event> (listener), style (string or object:
//   camelCase, hyphenated and --custom keys; null values skipped), other keys as attributes (undefined/null/false skipped,
//   true = ''); children: Node | string | number | array of them (null/undefined/false skipped)
export function esc(s) {}                  // HTML-escape & < > " '
export function on(target, type, fn, opts) {} // addEventListener -> idempotent off()
```

New modules import `h`/`esc`/`on` from `dom.js` (`app.js` re-exports `h` and `esc` for older callers). Tests: `tests/js/dom.test.mjs`.

### 6.14 Client storage keys (D8)

All UI state keys start with `fathom.ui.`; every read tolerates missing, full or throwing storage and corrupt JSON.

| Key | Storage | Scope | Stores |
| --- | --- | --- | --- |
| `fathom.ui.nav` | session | tab | `{<project>: {<section>: '#/…'}}` last hash per section (nav memory, FR-UX-09) |
| `fathom.ui.recent.<project>` | local | project | `{device, room, rack, page: [{id, t}]}`, newest first, 8 each (search recents, home) |
| `fathom.ui.table.<scope>.<key>` (`fathom.ui.table.<key>` without a scope) | local | table | `{v: 1, sort, filters, pageSize, hidden, density, extra}` |
| `fathom.ui.explorer.<key>` | local | explorer | `{w: width px, c: collapsed}` |
| `fathom.ui.inspector` | local | browser | `{v: 1, open: {<kind>: {<section>: bool}}}` — only sections the user toggled |
| `fathom.ui.notices.<project>` | session | tab, project | bell notices (max 50) |
| `fathom.ui.seen.<project>` | local | project | ISO time of the newest open problem report already announced |
| `fathom.ui.form.<key>` | local | form | remembered wizard input, e.g. `bulk-devices`, `bulk-cables` column mappings |
| `fathom.ui.theme` | local | browser | `dark` \| `light` \| `system` (FR-UX-15); unset = dark; `?theme=` overrides a load without writing it |
| `fathom.ui.tour` | local | browser | `{done: true, at: <ms>, reason}` once the first-run tour has been completed or dismissed (FR-UX-16); unset = run it after the first project load |

Deliberately **not** persisted: DataTable search text (`q`) and page (`pg`) — URL only; the selection, drawer and section (`sel`, `sec`, `drawer`) — URL only; search palette text and category. Older keys outside the prefix stay as they were: `fathom.pending.<project>` (local, unsent ops, §6.3), `fathom.sop.tasks.*` and `fathom.sop.done.*` (session, SOP task ticks), `fathom.sop.draft.*` (local, SOP editor drafts), `fathom.addgear.tab` (local, add-gear dialog tab), `fathom:login-bounces` (session, login redirect loop guard).

---

## 7. Work decomposition

### 7.1 Units at a glance

| Unit | Mission | Owned files (summary; full list §7.2) | Key interfaces it provides |
| --- | --- | --- | --- |
| **W1** Backend core | Model v2 + migration + flow adapter, storage/locks, history, users/sessions, API v1+v2, OpenAPI, static/PWA routes, hardening, packaging | `model.py`, `schema.py`, `project.py`, `history.py`, `users.py`, `openapi.py`, `server.py`, `__init__.py`, `static/manifest.webmanifest`, `static/sw.js`, `static/icons/*`, `static/dev/fixture-v2.json`, `pyproject.toml`, `Dockerfile`, `docker-compose.yml` | `schema.*` (migrate, normalize, validate_doc, apply_ops, invert_ops, merge_patch, diff_docs, flow_project, expand_port_groups, is_v1_expressible, to_v1_dict, new_doc, load_any, JSON_SCHEMA), `project.load_doc/save_doc/apply_changes/…`, `history.*`, `users.*`, HTTP API §5 |
| **W2** Engine & importers | Vocabulary, plugin registry, importers (3 legacy lifted + Eos + Videohub + CSV), overlay, library, floor-plan conversion, cable tags/schedule/labels, IP schedule, BOM/inventory schedule, QR, builds, CLI, selftest, samples, README | `vocab.py`, `plugins.py`, `parsers/*`, `library/**`, `floorplan.py`, `cables.py`, `network.py`, `bom.py`, `qr.py`, `merge.py`, `export.py`, `cli.py`, `selftest.py`, `samples/campus-demo/**`, `samples/floorplans/**`, new files under `samples/rrc-littleton/exports/` (none required), `README.md` | `vocab.*`, `plugins.*`, `merge.build_overlay`, `library.*`, `floorplan.convert/…`, `cables.*`, `network.*`, `bom.*`, `qr.*`, `export.write_build/build`, CLI |
| **W3** Patch view | Knox-style node editor | `static/js/patchview.js`, `static/js/patchview-core.js`, `static/css/patchview.css`, `static/dev/patchview.html`, `static/dev/fixture-gen.js` | `mount(el, ctx)`, core functions §6.5, `makeFixture` |
| **W4** Plans, racks, schedules, inventory UI | Floor plan editor, rack elevations, schedules & inventory views | `static/js/floorplan.js`, `floorplan-core.js`, `rack.js`, `rack-core.js`, `schedules.js`, `inventory.js`, `static/css/plan.css`, `static/dev/floorplan.html`, `rack.html`, `schedules.html`, `static/dev/plans/*` | `mount(el, ctx)` ×4, cores §6.7 |
| **W5** App shell & viewer | SPA shell/router/store wiring, api client, model-core, inspector, patch table, assistant UI, admin views, search palette, login, mobile layout, SW registration; server-rendered viewer pages | `static/app.html`, `static/login.html`, `static/js/{app,api,model-core,inspector,patchtable,patchtable-core,assistant-ui,views-admin}.js`, `static/js/package.json`, `static/css/app.css`, `static/dev/patchtable.html`, `static/dev/index.html`, `render_html.py`, `render_svg.py`, `layout.py` | `model-core.*`, `createStore`, `api.*`, `ChangeQueue`, ctx contract, `render_html.*` §7.4.4 |
| **W6** Assistant, tracing & analysis | Port-level trace, assistant + checklists, LLM bridge, patch table data, search, racks, DMX | `assistant.py`, `llm.py`, `trace.py`, `patch.py`, `search.py`, `racks.py`, `dmx.py`, `checklists/**` | §7.4.3 |
| **T1** Backend tests | unittest suites + shared vectors/fixtures | `tests/test_model_v2.py`, `test_api.py`, `test_importers.py`, `test_assistant.py`, `test_exports.py`, `test_security.py`, `test_compat.py`, `tests/_helpers.py`, `tests/fixtures/**` | shared vectors `port-expansion.json`, `ops-vectors.json`, golden `patchtable-sunday.json` |
| **T2** Frontend tests | Node unit tests for pure cores + headless-Chrome smoke | `tests/js/*.test.mjs`, `tests/js/fixtures/**`, `tests/test_frontend_smoke.py` | — |
| **QA** | Run gates, verify acceptance checklist, report | `docs/QA-REPORT.md` | — |

### 7.2 File ownership (exhaustive)

A file not listed here MUST NOT be created or edited, except: each unit MAY create `docs/notes/<unit>.md` (e.g. `docs/notes/W3.md`) for its own implementation notes and contract questions. **Frozen (nobody edits):** `tests/test_fathom.py`, `fathom/samples/rrc-littleton/project.json`, `fathom/samples/rrc-littleton/exports/cl5/*`, `…/exports/dante/rrc-littleton-preset.xml`, `…/exports/waves/*`, `docs/SPEC.md`, `docs/Inspo/*`, `docs/demo.png`, `.gitignore`, `.dockerignore`, `fathom/__main__.py`.

| Owner | Files (create or edit) |
| --- | --- |
| W1 | `fathom/__init__.py` (version `0.3.0`, docstring), `fathom/model.py`, `fathom/schema.py`, `fathom/project.py`, `fathom/history.py`, `fathom/users.py`, `fathom/openapi.py`, `fathom/server.py`, `fathom/static/manifest.webmanifest`, `fathom/static/sw.js`, `fathom/static/icons/icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, `apple-touch-icon.png`, `favicon.ico`, `fathom/static/dev/fixture-v2.json` (verbatim Appendix B), `pyproject.toml`, `Dockerfile`, `docker-compose.yml` |
| W2 | `fathom/vocab.py`, `fathom/plugins.py`, `fathom/parsers/__init__.py`, `parsers/common.py`, `parsers/yamaha.py`, `parsers/dante.py`, `parsers/waves.py`, `parsers/eos.py`, `parsers/videohub.py`, `parsers/generic_csv.py`, `parsers/atem.py` (P2), `fathom/library/__init__.py`, `fathom/library/templates/*.json`, `fathom/floorplan.py`, `fathom/cables.py`, `fathom/network.py`, `fathom/bom.py`, `fathom/qr.py`, `fathom/merge.py`, `fathom/export.py`, `fathom/cli.py`, `fathom/selftest.py`, `fathom/samples/campus-demo/**`, `fathom/samples/floorplans/**`, `README.md` |
| W3 | `fathom/static/js/patchview.js`, `fathom/static/js/patchview-core.js`, `fathom/static/css/patchview.css`, `fathom/static/dev/patchview.html`, `fathom/static/dev/fixture-gen.js` |
| W4 | `fathom/static/js/floorplan.js`, `floorplan-core.js`, `rack.js`, `rack-core.js`, `schedules.js`, `inventory.js`, `fathom/static/css/plan.css`, `fathom/static/dev/floorplan.html`, `rack.html`, `schedules.html`, `fathom/static/dev/plans/*` (copies of the sample plan renders for the harness) |
| W5 | `fathom/static/app.html`, `fathom/static/login.html`, `fathom/static/js/app.js`, `api.js`, `model-core.js`, `inspector.js`, `patchtable.js`, `patchtable-core.js`, `assistant-ui.js`, `views-admin.js`, `fathom/static/js/package.json`, `fathom/static/css/app.css`, `fathom/static/dev/patchtable.html`, `fathom/static/dev/index.html`, `fathom/render_html.py`, `fathom/render_svg.py`, `fathom/layout.py` |
| W6 | `fathom/assistant.py`, `fathom/llm.py`, `fathom/trace.py`, `fathom/patch.py`, `fathom/search.py`, `fathom/racks.py`, `fathom/dmx.py`, `fathom/checklists/symptoms.json`, `synonyms.json`, `kinds.json`, `media.json`, `generic.json` |
| T1 | `tests/_helpers.py`, `tests/test_model_v2.py`, `tests/test_api.py`, `tests/test_importers.py`, `tests/test_assistant.py`, `tests/test_exports.py`, `tests/test_security.py`, `tests/test_compat.py`, `tests/fixtures/**` |
| T2 | `tests/js/*.test.mjs`, `tests/js/fixtures/**`, `tests/test_frontend_smoke.py` |
| QA | `docs/QA-REPORT.md` |

### 7.3 Unit briefs

#### W1 — Backend core

Build, in this order:
1. **Milestone 0 (first, within the first ~10% of the pass):** commit `static/dev/fixture-v2.json` (Appendix B verbatim); `schema.py` with `SCHEMA_VERSION = 2`, `COLLECTIONS`, `new_doc`, `normalize`, `merge_patch`, `apply_ops`, `invert_ops`, `expand_port_groups`, `doc_version`, `load_any` (v2 only at first); `model.py` re-exporting `KINDS, MEDIA, BRANDS` from `vocab.py` with a fallback to the current inline dicts if `vocab` cannot be imported yet.
2. Migration (`migrate`, §4.6) + `flow_project` + `is_v1_expressible` + `to_v1_dict`; RRC identity holds (run `tests/test_fathom.py` and your own identity check).
3. `validate_doc` (§4.7) with lazy optional helpers; `diff_docs`; `JSON_SCHEMA`.
4. `project.py`: `load_doc`, `save_doc`, `apply_changes`, `project_lock`, `files_dir`, `ConflictError`, `ValidationError`, `PreconditionError`; v1 functions keep working via the adapter; `new_project` writes v2 for `blank`, copies samples verbatim.
5. `history.py`, `users.py`, session cookie, auth middleware, roles.
6. `server.py`: route table with metadata, all routes of §5, static/SW/manifest, security headers, CSRF, body caps, error ids; engine calls per §7.4.5 with **lazy imports inside handlers** so a missing W2/W6 module only breaks its own endpoints (500 `internal` with message in logs).
7. `openapi.py`, `/api/docs`.
8. Packaging: `pyproject.toml` (packages `fathom, fathom.parsers, fathom.library`; package-data `static/**/*`, `samples/**/*`, `library/templates/*.json`, `checklists/*.json`; version via `fathom.__version__`; description updated to AVL), `Dockerfile` (`ARG WITH_PDF_TOOLS=true` installs `poppler-utils`; keep `WITH_CHROMIUM`; `ENV FATHOM_DATA=/data`; document `FATHOM_PUBLIC_URL`, `FATHOM_LLM_*`), `docker-compose.yml` (commented examples for the new env vars).

Isolation proof: `python -m unittest` on your own scratch tests (not committed) or T1's suites as they land; `curl` walkthrough against `fathom serve` with a temp `FATHOM_DATA`; RRC identity.

#### W2 — Engine & importers

1. **Milestone 0:** `vocab.py` complete (Appendix A, `as_dict()`), so W1/W5/W6 can import it.
2. `plugins.py` registry; refactor `parsers/__init__.py` onto it (keep `KINDS`, `detect_kind`, `parse_any`, `parse_yamaha/dante/waves` exports); `fathom plugins`.
3. Dante Device Info addresses; `merge.build_overlay` (lifting legacy results) + new importers `eos.py`, `videohub.py`, `generic_csv.py` with `contribute`/preview; samples for each under `samples/campus-demo/exports/`.
4. `library/` loader + the 55 templates of Appendix E (≥ 48 required) + `validate_template`, `instantiate`, `template_from_device`, `save_custom_template`.
5. `floorplan.py` (convert/sanitize/drawio/dxf/pdf/dwg/ODA, plan SVG with markers) + `samples/floorplans/` (`main-floor.dxf` = Appendix D.2 extended into a plausible auditorium, `stage.drawio` (compressed), `lobby.svg`, `chapel.png`, `rcp.pdf` (one page, generated with any tool you have; if none, ship without and note it)).
6. `cables.py` (tags, schedule, label sheet), `network.py` (IP schedule, MAC/IP helpers, warnings), `bom.py` (BOM + inventory schedule, FR-PLN-03, FR-INV-04), `qr.py` (+ Appendix C vectors).
7. `export.py` build package §5.9 (calls W5 renderers and W6 analysis); `campus-demo` sample (v2): venue "Riverside Campus", rooms `main` (Main Auditorium: audio + video + lighting, 2 racks, 2 floor plans), `chapel` (small system), `broadcast` (broadcast suite); ≥ 40 devices from the library, ≥ 80 cables, networks + interfaces, Eos patch import, Videohub dump import, Dante preset/device-info import, CSV files, at least one planned and one spare device.
8. `cli.py`: new commands `migrate`, `user` (calls W1 `users.*`), `library list|show`, `schedule <kind>`, `qr`, `plan convert`, `ask`, `history`, `restore`, `vocab --json`, `plugins`; existing commands keep flags (`--kind` choices from the registry); `trace` accepts `dev:port` and `--discipline/--up`.
9. `selftest.py`: keep every v0.2 check; add: RRC migration identity, campus-demo build (all §5.9 files present), QR vector, DXF/Draw.io fixture conversions, Eos/Videohub sample parse counts, assistant answer on the fixture (if `fathom.assistant` importable; else "skip").
10. `README.md`: features, new env vars, data layout, CLI.
11. **Console sends (§4.3.17).** A console's CSV export carries names and patches but no send levels or DCA assignments. Those live in the CL Editor / console session file (`.CLF`, `.CLE`; QL `.QLF`, TF `.TFF`, …), a proprietary flat binary that Yamaha does not document (only partial community reverse engineering of names / input patch exists, with a checksum, and the software terms forbid reverse engineering). Fathom therefore does **not** parse them: `parsers.yamaha.BINARY_CONSOLE_FILES` makes `detect_kind` route such files to the Yamaha importer, which sets `ConsoleData.fatal` (`BINARY_CONSOLE_NOTE`: what the file is, export CSV instead, use the console CSV template) so the upload is refused with 422 and nothing is kept; a folder that mixes a `.CLF` with the CSVs parses the CSVs and keeps the note. Sends and DCA / mute membership come from the inspector (§6.8.6) or the console CSV template (§5.7.4); the `clf` channel source stays reserved should a documented export appear.

Isolation proof: `python -m fathom selftest`; `fathom build` of campus-demo; CLI walkthrough.

#### W3 — Patch view

Ship `patchview-core.js` first (pure, with your own scratch Node checks), then `patchview.js`, `patchview.css`, `fixture-gen.js` and `dev/patchview.html`. Use `model-core.js` (W5) for ops/store/viewport; until it lands, develop against the contract in §6.2 with a local shim **inside your harness page only** (never in owned module files' import paths). Isolation proof: harness with fixture and with `?devices=150&cables=600`; `__pvStats` within budget; keyboard-only and touch (Chrome device emulation) walkthrough.

#### W4 — Floor plans, racks, schedules, inventory

Ship cores first, then DOM modules and harnesses. Upload flows call `ctx.api.upload(project, 'floorplans', files, {room, name})`; in harness mode (`ctx.api === null`) the plan picker offers the images in `static/dev/plans/` and creates floor-plan entities locally via ops. Isolation proof: harnesses for plan (calibrate + measure 10 m test on the DXF render), rack (drag/collision), schedules (fixture rows, tag preview in local mode by a simple local implementation of §4.8 *inside schedules.js only for harness mode* — production uses the server preview).

#### W5 — App shell & viewer

1. **Milestone 0:** `model-core.js` (complete per §6.2, it unblocks W3/W4/T2) and `js/package.json`.
2. `api.js` + `ChangeQueue`; `app.js` shell (router, store wiring, view registry with lazy import and error cards, top bar, room picker, pickers, toasts, dialogs, palette, offline/conflict handling, SW registration), `app.html`, `login.html`, `app.css`.
3. `inspector.js`, `patchtable-core.js` + `patchtable.js` (+ harness), `assistant-ui.js`, `views-admin.js`.
4. Python renderers: `render_html.render_html(project, layout, nav=None, base_url="", sw=False, highlight_bridge=True)` adding the room switcher, mobile tap tips, SW registration and the postMessage bridge **without changing the HTML structure that frozen tests assert** (`class="card`, `data-id="foh"`, `SF_DATA`, `Patch sheet`); new `render_room_index`, `render_device_page`, `render_patch_page`; `layout.py`/`render_svg.py` only for new kinds' colors/gradients and the key's network row (spine label).

Isolation proof: app against `fathom serve` on campus-demo with W1's API; harness `dev/patchtable.html`; frozen tests.

#### W6 — Assistant, tracing & analysis

1. **Milestone 0:** `checklists/*.json` with the Appendix F seeds and `trace.py` port-graph functions (v1 functions untouched).
2. `search.py`, `patch.py` additions (`patch_table`, `patch_table_csv`; v1 `build_patch_sheet` untouched), `racks.py`, `dmx.py`.
3. `assistant.py` (§6.9.5) and `llm.py` (§6.9.6).

Isolation proof: Python REPL/scratch scripts on the fixture reproducing §5.10 exactly; T1's `test_assistant.py`.

#### T1 — Backend tests

Write the shared vector files first (`tests/fixtures/port-expansion.json`, `tests/fixtures/ops-vectors.json`) from §4.4.3/§4.9 so W1 and W5 can test against them; then suites. Tests must run with `python -m unittest discover -s tests` on 3.9 and 3.11+, use temp `FATHOM_DATA` dirs (`tests/_helpers.py: temp_data_dir()` context manager setting/restoring the env var), call the WSGI app in-process (`tests/_helpers.py: call(app, method, path, body=None, headers=None) -> (status, headers, body)` using `wsgiref.util.setup_testing_defaults`), never require network or Chrome (skip cleanly), and never modify the repo. Coverage map: §9.

#### T2 — Frontend tests

`tests/js/*.test.mjs` with `node:test` + `node:assert/strict` only. Import cores via relative paths (`../../fathom/static/js/model-core.js`). Fixtures: `tests/js/fixtures/vocab.json` (generate with `python3 -m fathom vocab --json > tests/js/fixtures/vocab.json`, commit the output), plus reading `fathom/static/dev/fixture-v2.json` and T1's vectors. `tests/test_frontend_smoke.py`: start `fathom.server.serve` in a thread on a free port with a temp data dir containing campus-demo and the fixture as project `sunday-demo`; for each URL run Chrome `--headless=new --disable-gpu --virtual-time-budget=8000 --dump-dom <url>?smoke=1` (via `fathom.export.find_chrome()`), parse `data-smoke` and assert `ready` and `errors == []`; URLs: app `/#/sunday-demo/main/<view>` for every view, the 5 harnesses, `/p/sunday-demo`, `/p/sunday-demo/rooms`, `/p/sunday-demo/d/atem-mini`, `/p/sunday-demo/r/main/patch`, `/login`; perf: harness `?devices=150&cables=600` `stats.renderMs ≤ 1500`. Skip (not fail) when Chrome is absent. Also an ES2018 syntax lint test (§8.1 gate 6).

#### QA

No code. Run every gate in §8, walk the acceptance checklist §9 (automated items: confirm the named test exists and passes; manual items: perform them, at least desktop Chrome + Safari (macOS) + iPad or Chrome touch emulation), write `docs/QA-REPORT.md`: gate results with command output summaries, per-FR status (pass/fail/gap with evidence), defects with repro steps and the owning unit, P1/P2 slips.

### 7.4 Backend interfaces (exact signatures)

All modules start with `from __future__ import annotations`. Type names: `Doc = Dict[str, Any]`, `Op = Dict[str, Any]`, `Problem = Dict[str, Any]`.

#### 7.4.1 W1

```python
# fathom/schema.py
SCHEMA_VERSION: int = 2
COLLECTIONS: Tuple[str, ...]
ROOTS: Tuple[str, ...] = ("meta", "settings", "media")
JSON_SCHEMA: Dict[str, Any]
class SchemaError(ValueError): ...
def new_doc(org: str = "") -> Doc: ...
def doc_version(d: Dict[str, Any]) -> int: ...
def load_any(d: Dict[str, Any]) -> Doc: ...                         # migrate v0/v1, normalize v2
def migrate(v1: Dict[str, Any]) -> Doc: ...
def normalize(doc: Doc) -> Doc: ...
def validate_doc(doc: Doc) -> List[Problem]: ...
def errors(problems: List[Problem]) -> List[Problem]: ...           # level == "error"
def expand_port_groups(groups: List[Dict[str, Any]], v1: bool = False) -> List[Dict[str, Any]]: ...
def parse_port_text(text: str) -> Tuple[str, str, int, int]: ...    # ("range"|"index"|"opaque", prefix_or_text, a, b)
def merge_patch(target: Any, patch: Any) -> Any: ...
def apply_ops(doc: Doc, ops: List[Op]) -> Tuple[Doc, Set[str]]: ... # raises SchemaError(code) on bad op
def invert_ops(doc: Doc, ops: List[Op]) -> List[Op]: ...
def diff_docs(a: Doc, b: Doc) -> List[Op]: ...
def touched_refs(ops: List[Op]) -> Set[str]: ...
def index(doc: Doc) -> "DocIndex": ...                              # .device(id), .port(dev, port), .cables_of(dev), .cables_at(dev, port), .room(id), .rack(id), .template_ids
def discipline_of(device: Dict[str, Any]) -> str: ...
def flow_project(doc: Doc, room_id: Optional[str] = None, state: str = "all") -> "Project": ...
def is_v1_expressible(doc: Doc) -> bool: ...
def to_v1_dict(doc: Doc) -> Dict[str, Any]: ...
def filter_state(doc: Doc, state: str) -> Doc: ...                  # §4.4.6, returns a filtered copy

# fathom/project.py (additions; v0.2 functions keep their signatures)
class ConflictError(Exception): revision: int; conflicts: List[str]; by: List[str]
class ValidationError(Exception): problems: List[Problem]
class PreconditionError(Exception): ...
def load_doc(target: str) -> Tuple[Doc, Path]: ...                  # migrates v1 in memory (no write); same target rules as load_project
def load_doc_info(target: str) -> Tuple[Doc, Path, int]: ...        # (doc, dir, source_version 0|1|2)
def save_doc(doc: Doc, project_dir: Path, *, base_revision: Optional[int], author: str = "", summary: str = "", source: str = "put") -> Dict[str, Any]: ...   # {"revision","rebased","problems","touched"}
def apply_changes(project_dir: Path, ops: List[Op], *, base_revision: int, author: str = "", summary: str = "", source: str = "changes") -> Dict[str, Any]: ...
def project_lock(project_dir: Path): ...                            # context manager
def files_dir(project_dir: Path) -> Path: ...
def add_attachment(project_dir: Path, filename: str, data: bytes, *, mime: str, device: str = "", kind: str = "other", author: str = "") -> Dict[str, Any]: ...  # writes file, returns attachment entity (not yet in doc)
def project_dir_for(name: str) -> Path: ...                         # validates name, 404-able FileNotFoundError

# fathom/history.py
def record(project_dir: Path, revision: int, ops: List[Op], doc_after: Doc, *, author: str, summary: str, source: str, touched: Set[str]) -> None: ...
def list_revisions(project_dir: Path, limit: int = 50, before: Optional[int] = None) -> List[Dict[str, Any]]: ...
def get_revision_doc(project_dir: Path, revision: int) -> Doc: ...  # raises KeyError
def touched_since(project_dir: Path, base_revision: int) -> Set[str]: ...
def diff_revisions(project_dir: Path, a: int, b: int) -> Dict[str, List[str]]: ...

# fathom/users.py
ROLES: Tuple[str, ...] = ("viewer", "editor", "admin")
def auth_enabled() -> bool: ...
def list_users() -> List[Dict[str, Any]]: ...
def add_user(username: str, password: str, role: str = "editor", projects: Optional[Dict[str, str]] = None) -> Dict[str, Any]: ...
def set_password(username: str, password: str) -> None: ...         # bumps epoch
def set_role(username: str, role: str) -> None: ...
def set_disabled(username: str, disabled: bool) -> None: ...
def remove_user(username: str) -> None: ...
def verify(username: str, password: str) -> Optional[Dict[str, Any]]: ...   # users.json then FATHOM_AUTH
def hash_password(password: str, iterations: int = 600_000) -> str: ...
def check_password(stored: str, password: str) -> bool: ...
def make_session(user: Dict[str, Any], max_age: int = 1_209_600) -> str: ...
def read_session(cookie_value: str) -> Optional[Dict[str, Any]]: ...
def effective_role(user: Dict[str, Any], project: str = "") -> str: ...
```

`model.py` keeps every v0.2 name. It imports `KINDS, MEDIA, BRANDS` from `vocab` (W2) for the flow renderer; `Project.used_kinds/used_media` keep their logic over the larger vocab.

#### 7.4.2 W2

```python
# fathom/vocab.py
KINDS: Dict[str, Dict[str, Any]]        # Appendix A.1: label, discipline, color, side, routing, legacy
MEDIA: Dict[str, Dict[str, Any]]        # Appendix A.2: label, color, dash, width, arrow, discipline, carries, ip, connector, short
DISCIPLINES: Dict[str, Dict[str, str]]  # Appendix A.3: label, color, letter
BRANDS: Dict[str, Dict[str, str]]       # v1 brands + additions (Appendix A.6)
CONNECTORS: List[str]; STATUSES: Tuple[str, ...]; ROOM_KINDS: Tuple[str, ...]; PORT_DIRS = ("in", "out", "io")
NETWORK_MEDIA: FrozenSet[str]           # dante, avb, aes67, aes50, madi, snake, network, qlan  (v1 network rule)
SOURCE_KINDS: FrozenSet[str]            # mic, source, video_source, camera, computer, lighting_console, touch_panel
def as_dict() -> Dict[str, Any]: ...    # {"kinds","media","disciplines","brands","connectors","statuses","room_kinds","port_dirs"}
def kind_discipline(kind: str) -> str: ...
def medium_carries(medium: str) -> Tuple[str, ...]: ...

# fathom/plugins.py
@dataclass
class Importer:
    kind: str; label: str
    detect: Callable[[Path], float]                    # 0..1 confidence
    parse: Callable[..., Any]                          # parse(path: Path, **options) -> ParseResult
    contribute: Optional[Callable[[Any, Doc, Dict[str, Any]], Dict[str, Any]]] = None   # (result, doc, ctx{import, room, device}) -> Contribution
    preview: Optional[Callable[[Any, Doc, Dict[str, Any]], Dict[str, Any]]] = None      # one-shot: -> {"ops","summary","warnings"}
    mode: str = "live"                                  # live | oneshot
    accepts: Tuple[str, ...] = ()                       # extensions incl. dot
    folder: bool = False
    help: str = ""
    source: str = "builtin"
def register_importer(imp: Importer) -> None: ...
def get_importer(kind: str) -> Optional[Importer]: ...
def importers() -> List[Importer]: ...
def detect(path: Path) -> str: ...                      # best kind with confidence ≥ 0.3, else "unknown"
def load_plugins(paths: Optional[List[str]] = None) -> List[str]: ...   # returns loaded module names; idempotent
def plugin_errors() -> List[str]: ...
def template_dirs() -> List[Path]: ...; def checklist_dirs() -> List[Path]: ...
class PluginAPI: version: str; register_importer; register_template_dir; register_checklist_dir

# Contribution (returned by Importer.contribute), all keys optional:
# {"devices": [device…], "detail": {dev: {key: …}}, "routes": [route…], "port_labels": {dev: {port: label}},
#  "interfaces": {dev: [iface…]}, "dmx": {dev: {…}}, "patch_rows": […], "appendix": {…}, "notes": [str]}

# fathom/merge.py (apply_imports unchanged)
def build_overlay(doc: Doc, project_dir: Path) -> Dict[str, Any]: ...          # §4.11; never mutates doc
def promote_ops(doc: Doc, overlay: Dict[str, Any], device_ids: List[str]) -> List[Op]: ...

# fathom/library/__init__.py
def load_library(refresh: bool = False) -> Dict[str, Dict[str, Any]]: ...      # builtin + extension + custom
def list_templates(q: str = "", discipline: str = "", kind: str = "", doc: Optional[Doc] = None) -> List[Dict[str, Any]]: ...
def get_template(template_id: str, doc: Optional[Doc] = None) -> Optional[Dict[str, Any]]: ...
def validate_template(t: Dict[str, Any]) -> List[str]: ...
def instantiate(t: Dict[str, Any], *, device_id: str, name: Optional[str] = None, room: str = "", count: Optional[int] = None) -> Dict[str, Any]: ...
def apply_template_ops(doc: Doc, device_id: str, t: Dict[str, Any]) -> List[Op]: ...
def template_from_device(device: Dict[str, Any], template_id: str) -> Dict[str, Any]: ...
def save_custom_template(t: Dict[str, Any], override: bool = False) -> Path: ...
def delete_custom_template(template_id: str) -> None: ...

# fathom/floorplan.py
class UnsupportedPlan(Exception): code: str; message: str            # dwg_unsupported | pdf_unsupported | unsupported_format | binary_dxf
@dataclass
class ConvertResult:
    kind: str                     # source kind
    image_kind: str               # svg | png | jpg
    data: bytes                   # displayable image bytes (SVG utf-8)
    width: float; height: float
    layers: List[Dict[str, Any]]  # [{"name","color","visible","count"}]
    warnings: List[str]
    units: Optional[Dict[str, Any]] = None
def detect_plan_kind(filename: str, head: bytes) -> str: ...
def convert(path: Path, *, page: int = 0, hide_layers: Optional[List[str]] = None) -> ConvertResult: ...
def sanitize_svg(text: str) -> str: ...
def drawio_to_svg(xml_text: str, page: int = 0) -> ConvertResult: ...
def dxf_to_svg(text: str, hide_layers: Optional[List[str]] = None, use_dxf_colors: bool = False) -> ConvertResult: ...
def pdf_to_png(path: Path, page: int = 0, dpi: int = 150) -> bytes: ...      # raises UnsupportedPlan("pdf_unsupported", …)
def rasterizer() -> Optional[str]: ...
def plan_svg(doc: Doc, floorplan_id: str, project_dir: Path) -> str: ...      # export with markers + legend

# fathom/cables.py
def assign_tags_ops(doc: Doc, scope: str = "missing", pattern: Optional[str] = None) -> List[Op]: ...
def render_tag(pattern: str, cable: Dict[str, Any], doc: Doc, n: int) -> str: ...
def cable_schedule(doc: Doc, room: str = "*", state: str = "all", discipline: str = "") -> Dict[str, Any]: ...  # {"kind","columns","rows","problems"}
def label_sheet_html(doc: Doc, *, room: str = "*", layout: Optional[Dict[str, Any]] = None, qr: bool = False, base_url: str = "") -> str: ...

# fathom/network.py
def normalize_mac(text: str) -> Optional[str]: ...
def ip_schedule(doc: Doc, overlay: Optional[Dict[str, Any]] = None, room: str = "*") -> Dict[str, Any]: ...
def network_problems(doc: Doc) -> List[Problem]: ...

# fathom/bom.py
def bom(doc: Doc, state: str = "all", room: str = "*") -> Dict[str, Any]: ...       # {"kind","columns","rows","totals":{"USD": 6498.0}}
def inventory_schedule(doc: Doc, room: str = "*") -> Dict[str, Any]: ...

# fathom/qr.py
def encode(data: Union[str, bytes], ecl: str = "M", version: Optional[int] = None, mask: Optional[int] = None) -> List[List[bool]]: ...
def to_svg(matrix: List[List[bool]], scale: int = 4, border: int = 4, dark: str = "#000000", light: str = "#ffffff") -> str: ...
def svg(text: str, ecl: str = "M", **kw: Any) -> str: ...

# fathom/export.py (v0.2 functions keep signatures; new keyword-only params)
def write_build(project, project_dir: Path, run_dir: Path, pdf: bool = False, png: bool = False, *, doc: Optional[Doc] = None, state: str = "all", rooms: Optional[List[str]] = None, base_url: str = "") -> Dict[str, str]: ...
def build_doc(name_or_dir: str, *, state: str = "all", rooms: Optional[List[str]] = None, pdf: bool = False, png: bool = False, base_url: str = "", run_dir: Optional[Path] = None) -> Path: ...
def device_url(base_url: str, project: str, device_id: str) -> str: ...
```

#### 7.4.3 W6

```python
# fathom/trace.py (v0.2 functions unchanged)
class PortGraph: ...                                   # .edges_out(node), .edges_in(node); node = "dev:port" | "dev:*"
def port_graph(doc: Doc, overlay: Optional[Dict[str, Any]] = None, discipline: Optional[str] = None, state: str = "all") -> PortGraph: ...
def upstream_paths(g: PortGraph, start: str, max_depth: int = 24, limit: int = 50) -> List[Dict[str, Any]]: ...   # [{"hops":[{"device","port"}], "cables":[ids]}]
def downstream_paths(g: PortGraph, start: str, max_depth: int = 24, limit: int = 50) -> List[Dict[str, Any]]: ...
def port_paths(g: PortGraph, a: str, b: str, max_depth: int = 24, limit: int = 50) -> List[Dict[str, Any]]: ...
def path_text(doc: Doc, path: Dict[str, Any]) -> str: ...
def hop_labels(doc: Doc, path: Dict[str, Any]) -> List[str]: ...
def resolve_ref(doc: Doc, text: str) -> Optional[Tuple[str, Optional[str]]]: ...   # "dev[:port]" or a name -> (dev, port)

# fathom/patch.py (v0.2 functions unchanged)
def patch_table(doc: Doc, overlay: Optional[Dict[str, Any]] = None, room: str = "*", discipline: str = "", query: str = "", include_overlay: bool = False, only_patched: bool = False) -> List[Dict[str, Any]]: ...   # PatchBlock[] (§6.6)
def patch_table_csv(blocks: List[Dict[str, Any]]) -> str: ...
def patch_schedule(doc: Doc, overlay=None, room: str = "*", discipline: str = "") -> Dict[str, Any]: ...      # columns/rows form

# fathom/search.py
class SearchIndex: ...
def build_index(doc: Doc, overlay: Optional[Dict[str, Any]] = None) -> SearchIndex: ...
def search(index_or_doc: Union[SearchIndex, Doc], q: str, limit: int = 20, kinds: Optional[List[str]] = None) -> List[Dict[str, Any]]: ...  # Hit[] §5.11

# fathom/racks.py
def rack_occupancy(doc: Doc, rack_id: str) -> Dict[str, Any]: ...    # {"rack","slots":[…],"collisions":[…]}
def validate_racks(doc: Doc) -> List[Problem]: ...
def rack_svg(doc: Doc, rack_id: str, face: str = "front", scale: float = 1.0) -> str: ...
def rack_schedule(doc: Doc, room: str = "*") -> Dict[str, Any]: ...

# fathom/dmx.py
def dmx_schedule(doc: Doc, overlay: Optional[Dict[str, Any]] = None, room: str = "*") -> Dict[str, Any]: ...
def dmx_problems(doc: Doc, overlay: Optional[Dict[str, Any]] = None) -> List[Problem]: ...
def sacn_group(universe: int) -> str: ...                              # "239.255.<u>>8>.<u&255>"
def artnet_split(universe: int) -> Tuple[int, int, int]: ...          # port-address u-1 -> (net, subnet, universe)

# fathom/assistant.py
def answer(doc: Doc, question: str, *, room: Optional[str] = None, overlay: Optional[Dict[str, Any]] = None, use_llm: bool = True, history: Optional[List[Dict[str, str]]] = None, base_revision: Optional[int] = None) -> Dict[str, Any]: ...   # §5.10
def parse_intent(doc: Doc, question: str, room: Optional[str] = None, index=None) -> Dict[str, Any]: ...
def load_checklists(refresh: bool = False) -> Dict[str, Any]: ...    # merges fathom/checklists + extension dirs

# fathom/llm.py
class LLMError(Exception): ...
def configured() -> bool: ...
def info() -> Dict[str, Any]: ...
def chat(messages: List[Dict[str, str]], temperature: float = 0.2, max_tokens: int = 700, timeout: Optional[float] = None) -> str: ...
```

#### 7.4.4 W5 (Python renderers)

```python
# fathom/render_html.py
def render_html(project, layout, *, nav: Optional[Dict[str, Any]] = None, base_url: str = "", sw: bool = False) -> str: ...
    # nav = {"project": "rrc", "rooms": [{"id","name","url"}], "current": "main", "links": [{"label","url"}]}
def render_room_index(doc: Doc, *, project: str, base_url: str = "", sw: bool = False) -> str: ...
def render_device_page(doc: Doc, device_id: str, *, project: str, overlay=None, base_url: str = "", qr_svg: str = "", sw: bool = False) -> str: ...
def render_patch_page(doc: Doc, room_id: str, blocks: List[Dict[str, Any]], *, project: str, base_url: str = "", sw: bool = False) -> str: ...
def render_report(doc: Doc, *, project: str, sections: Dict[str, str]) -> str: ...   # P1, print-oriented report.html
# fathom/render_svg.py, fathom/layout.py: signatures unchanged
```

`base_url` = relative prefix from the page to the app root (e.g. `"../../"`); used for SW registration, static links and room/device links. In builds, pages use relative links between build files instead (W2 passes `nav` with relative URLs and `sw=False`).

#### 7.4.5 Server → engine call map (W1 calls; owners implement)

| Route | Calls |
| --- | --- |
| `GET /api/v2/meta` | `vocab.as_dict()`, `plugins.importers()`, `plugins.plugin_errors()`, `export.find_chrome()`, `floorplan.rasterizer()`, `llm.info()`, `library.load_library()` |
| `GET …/overlay` | `merge.build_overlay(doc, dir)` (cached by key §4.11) |
| imports POST | `plugins.detect`, `get_importer(kind).parse`, `.contribute` (summary only) |
| `imports/preview` | `importer.parse` + `importer.preview(result, doc, ctx)` |
| floorplans POST | `floorplan.convert`, `project.add_attachment` ×2, ops `put floorplans` |
| `floorplans/<fp>/image`, `<fp>.svg` | `floorplan.convert(..., hide_layers=…)` (cached), `floorplan.plan_svg` |
| schedules `patch` | `patch.patch_schedule` / `patch_table_csv(patch_table(...))` |
| schedules `cables`, `labels` | `cables.cable_schedule`, `cables.label_sheet_html` |
| schedules `ip` | `network.ip_schedule(doc, overlay)` |
| schedules `dmx` | `dmx.dmx_schedule(doc, overlay)` |
| schedules `bom`, `inventory` | `bom.bom`, `bom.inventory_schedule` |
| schedules `racks`, `racks/<rack>.svg` | `racks.rack_schedule`, `racks.rack_svg` |
| `cables/tag-preview` | `cables.assign_tags_ops` |
| `qr/<device>.svg` | `qr.svg(export.device_url(base, project, device))` |
| `trace` | `trace.resolve_ref`, `trace.port_graph`, `*_paths`, `path_text` |
| `search` | `search.build_index` (cached per revision) + `search.search` |
| `assistant` | `assistant.answer(doc, q, room=…, overlay=…, use_llm=…, history=…, base_revision=rev)` |
| builds POST | `export.write_build(flow_project(doc), dir, run_dir, pdf, png, doc=doc, state=…, rooms=…, base_url=…)` |
| `/p/<n>[/r/<room>]` | `export.render_project`-equivalent on `flow_project(doc, room)` + `render_html(..., nav, base_url, sw=True)` |
| `/p/<n>/rooms`, `/d/<dev>`, `/r/<room>/patch` | `render_room_index`, `render_device_page(qr_svg=qr.svg(...) when base known)`, `render_patch_page(patch.patch_table(...))` |
| `validate_doc` (inside W1) | lazily `racks.validate_racks`, `network.network_problems`, `dmx.dmx_problems` |

### 7.5 Integration order

1. **Contracts first (all units, first ~10%)**: W2 `vocab.py`; W1 `fixture-v2.json` + `schema.py` ops/expansion + `model.py` re-export; W5 `model-core.js` + `js/package.json`; W6 checklists seeds; T1 vector files; W3 `fixture-gen.js`.
2. **Parallel build** in isolation (each unit's isolation proof in §7.3). Cross-unit calls go only through the interfaces of §6 and §7.4. If an interface is ambiguous, follow this spec literally and document the question in `docs/notes/<unit>.md`; do not edit another unit's file.
3. **Wiring**: W1 wires routes to W2/W6 engines (lazy imports); W5 wires views (lazy `import()`), assistant UI to the API, renderers to W1's viewer routes; W2's `export` wires W5 renderers + W6 analysis.
4. **Tests land**: T1 suites and T2 tests run against the integrated tree; failures are reported to the owning unit, which fixes its own files.
5. **QA** runs §8 gates and §9 checklist, writes the report.

### 7.6 Rules of engagement

- Never edit a file you do not own (§7.2). Need a hook in someone else's file? It is already specified here; if not, record it in your notes and implement the closest compliant behavior in your own files.
- Keep every v0.2 public function working (§2.3). When in doubt, add new functions instead of changing old ones.
- No new runtime dependencies. Optional binaries (Chrome, pdftoppm, ODA) are detected, never required.
- Deterministic output (sorted where order is not semantic, seeded randomness in fixtures, no timestamps in content except build stamps and history).
- All user-visible strings in English; keep the existing terse, friendly tone.

---

## 8. Quality gates

### 8.1 Commands (all MUST pass; run from the repo root)

| # | Gate | Command | Pass condition |
| --- | --- | --- | --- |
| G1 | Unit tests, current Python | `python3 -m unittest discover -s tests -v` | 0 failures/errors; skips only with a reason mentioning Chrome, rasterizer, Docker or ODA |
| G2 | Unit tests, Python 3.9 | `/usr/bin/python3 -m unittest discover -s tests` (macOS ships 3.9.6) — or `uv run --python 3.9 --no-project python -m unittest discover -s tests` — or `docker run --rm -v "$PWD":/src -w /src python:3.9-slim python -m unittest discover -s tests` | same as G1 |
| G3 | Selftest | `python3 -m fathom selftest` and `/usr/bin/python3 -m fathom selftest` | exit 0, last line `ok: fathom selftest passed` |
| G4 | JS unit tests | `node --test tests/js` (Node ≥ 18) | 0 failures |
| G5 | Py 3.9 syntax | `/usr/bin/python3 -m compileall -q fathom tests` (or the uv/docker equivalents) | exit 0 |
| G6 | JS syntax & ES2018 | `for f in fathom/static/js/*.js fathom/static/sw.js fathom/static/dev/*.js; do node --check "$f" \|\| exit 1; done` and `node --test tests/js/syntax.test.mjs` (T2: rejects `?.`, `??`, `\|\|=`, `&&=`, `??=`, class fields/`#private`, `static {`, numeric separators, top-level `await` outside functions, `import.meta` outside `*.mjs` tests; ignores strings/comments) | exit 0 |
| G7 | Frontend smoke | `python3 -m unittest discover -s tests -p test_frontend_smoke.py -v` (the dotted `tests.test_frontend_smoke` form breaks when the `discovery` extra's `x690` installs a top-level `tests` package); the UI suites: `-p 'test_ui_*.py'` | all pages `ready` with `errors == []`; perf budget met; skipped only if no Chrome |
| G8 | Frozen files untouched | `git diff --quiet -- tests/test_fathom.py fathom/samples/rrc-littleton/project.json fathom/samples/rrc-littleton/exports` | exit 0 |
| G9 | Ownership | `git status --porcelain` — every new/modified path is listed in §7.2 (or `docs/notes/*.md`, `docs/QA-REPORT.md`) | QA confirms |
| G10 | Demo builds | `python3 -m fathom demo` ; `FATHOM_DATA=$(mktemp -d) sh -c 'python3 -m fathom new cd --template campus-demo && python3 -m fathom build cd'` | exit 0; run folder contains every §5.9 file (QR only if a public URL is set: run once with `FATHOM_PUBLIC_URL=http://localhost:8080`) |
| G11 | Packaging | `python3 -m pip wheel . --no-deps -w "$(mktemp -d)"` then `python3 -m zipfile -l <wheel>` | wheel contains `fathom/static/js/patchview.js`, `fathom/library/templates/yamaha-rio3224-d2.json`, `fathom/checklists/kinds.json`, `fathom/samples/campus-demo/project.json`, `fathom/static/sw.js` |
| G12 | Docker | `docker build -t fathom:0.3 .` ; `docker run --rm -d --name fq -p 18080:8080 fathom:0.3` ; `curl -fsS http://127.0.0.1:18080/healthz` ; `docker exec fq which pdftoppm` ; `docker rm -f fq` | healthz `{"ok": true, "version": "0.3.0"}` within 20 s; pdftoppm present |
| G13 | Live server walk | `FATHOM_DATA=$(mktemp -d) python3 -m fathom serve --port 18081` + the manual items of §9 | QA report |

### 8.2 Performance targets

| Scenario | Target | Measured by |
| --- | --- | --- |
| Patch view, 150 devices / 600 cables, first render | ≤ 1500 ms desktop Chrome (M1-class); ≤ 2500 ms iPad (A12+) | `__pvStats.renderMs` (G7 asserts desktop) |
| Patch view drag | ≥ 50 fps; ≤ 16 ms per frame of JS on desktop | `__pvStats.lastDragFrameMs` + DevTools (QA) |
| Pan/zoom | ≥ 55 fps (single transform) | DevTools (QA) |
| `GET /api/v2/projects/<n>` for the 150/600 fixture | ≤ 200 ms server time (local) | T1 timing test (soft: warn above, fail above 1000 ms) |
| `POST …/changes` (10 ops) | ≤ 150 ms (local, excluding fsync) | T1 timing test (soft) |
| Overlay for RRC | ≤ 1.5 s cold, cached afterwards | T1 timing test (soft) |
| Build of campus-demo without PDF | ≤ 10 s | G10 (QA notes time) |
| DXF conversion, 50 000 entities | ≤ 5 s, ≤ 30 MB SVG | T1 synthetic test (soft) |
| App shell first load (cached) | ≤ 1.5 s to interactive on desktop | QA |

### 8.3 Accessibility basics

FR-A11Y-01…04 plus: every icon-only button has `aria-label`; form fields have `<label for>`; error text is linked with `aria-describedby`; the patch view offers the patch table as an equivalent non-graphical editor (WCAG alternative); zoom up to 200% keeps the shell usable.

### 8.4 Security checklist (QA verifies each)

1. No route serves a file outside its root (`..`, encoded `..`, absolute, symlink to outside — symlinks are resolved and rejected).
2. Uploads capped; filenames sanitized (`_safe_filename`), stored under random attachment ids.
3. SVG uploads sanitized; user files served with the restrictive CSP and `nosniff`.
4. CSRF rule enforced (multipart without `X-Fathom` → 403).
5. Passwords PBKDF2-SHA256 600k; constant-time comparisons for passwords, cookie signatures and Basic auth.
6. Session cookie flags (HttpOnly, SameSite=Lax, Secure on HTTPS, Path).
7. Roles enforced on every mutating route (T1 matrix test iterates the route table).
8. No secrets in responses, logs, OpenAPI, builds (`users.json`, `secret.key`, `FATHOM_LLM_API_KEY`).
9. Error bodies have no stack traces.
10. LLM requests only when configured; the assistant never executes model output; suggestions require a click.
11. Imports parse untrusted files with stdlib parsers only; XML parsed with `xml.etree.ElementTree` (no external entities resolved by default) and size limits (reject > 50 MB); DXF parser bounded (entity cap 500 000, block nesting ≤ 8, time budget 20 s).
12. Subprocesses (Chrome, rasterizers, ODA) invoked with argument lists (no shell), timeouts, temp dirs.

### 8.5 Browser matrix

Chrome (current) macOS/Windows/Android; Safari 15+ macOS; iOS/iPadOS Safari 15+ (16+ for best results); Firefox current (best effort, not gated).

---

## 9. Acceptance checklist

Legend: **A** = automated (file::test name prefix that MUST exist and pass), **M** = manual by QA (steps). Test names are prefixes; owners may add more tests.

| # | FR | Verify | How |
| --- | --- | --- | --- |
| 1 | FR-ROOM-01 | A | `test_model_v2.py::test_room_collections_validate` (fixture validates; room op round-trip) |
| 2 | FR-ROOM-02 | A | `tests/js/model-core.test.mjs` "filterDevices shared inventory" |
| 3 | FR-ROOM-03 | M | Open campus-demo, switch rooms; hash changes; patch view content changes |
| 4 | FR-ROOM-04 | M | Settings → add room "Chapel 2" → reload → in picker |
| 5 | FR-ROOM-05 | A+M | `model-core.test.mjs` "external ghost devices"; M: move a device, see ghost in old room |
| 6 | FR-ROOM-06 | M | Inventory grouped by location |
| 7 | FR-ROOM-07 | A | `test_api.py::test_viewer_room_maps` (3 rooms → 3 distinct maps) |
| 8 | FR-ROOM-08 | A | `patchview-core.test.mjs` "filter by system" |
| 9 | FR-VOC-01 | A | `test_model_v2.py::test_vocab_kinds` |
| 10 | FR-VOC-02 | A | `test_model_v2.py::test_vocab_media_v1_subset` |
| 11 | FR-VOC-03 | A | `test_model_v2.py::test_vocab_disciplines` |
| 12 | FR-VOC-04 | A | `test_api.py::test_meta_v1_and_v2` |
| 13 | FR-VOC-05 | M | Compare pill/wire colors with Appendix A on fixture |
| 14 | FR-VOC-06 | M | Connector datalist in inspector |
| 15 | FR-VOC-07 | A | `test_api.py::test_unknown_medium_is_warning` |
| 16 | FR-PORT-01 | A | `test_model_v2.py::test_port_validation` |
| 17 | FR-PORT-02 | A+M | `test_model_v2.py::test_device_level_cable`; M: header wire in patch view |
| 18 | FR-PORT-03 | A | `test_model_v2.py::test_port_expansion_vectors` and `model-core.test.mjs` "expandPortGroups vectors" |
| 19 | FR-PORT-04 | A | `model-core.test.mjs` "canConnect"; `test_model_v2.py::test_port_overuse_warning` |
| 20 | FR-PORT-05 | A | `test_assistant.py::test_passthrough_routing` |
| 21 | FR-PORT-06 | M | Bulk add 8 × Analog In |
| 22 | FR-PORT-07 | M | Videohub labels italic in patch view; doc unchanged (history shows no new revision) |
| 23 | FR-MIG-01 | A | `test_model_v2.py::test_migrate_rrc_valid` |
| 24 | FR-MIG-02 | A | `test_model_v2.py::test_load_signalflow_v1` |
| 25 | FR-MIG-03 | A | `test_model_v2.py::test_rrc_layout_identity` |
| 26 | FR-MIG-04 | A | `test_model_v2.py::test_v1_backup_written_once` |
| 27 | FR-MIG-05 | A | `test_exports.py::test_cli_migrate` |
| 28 | FR-MIG-06 | A | `test_api.py::test_v1_put_expressible_and_409` |
| 29 | FR-MIG-07 | A | `test_model_v2.py::test_migration_bundles_drums_neve1` |
| 30 | FR-PV-01 | M | Harness vs Knox (b) |
| 31 | FR-PV-02 | A | `test_frontend_smoke.py::test_patchview_harness` (DOM has 15 `path[data-cable]`) |
| 32 | FR-PV-03 | A+M | `patchview-core.test.mjs` "moveOps snaps"; M: drag + undo |
| 33 | FR-PV-04 | A+M | `model-core.test.mjs` "connectOps"; M: drag a wire, in→in refused |
| 34 | FR-PV-05 | A+M | `model-core.test.mjs` "repatchOps"; M: re-patch and delete |
| 35 | FR-PV-06 | M | Inline rename card + port; table updates |
| 36 | FR-PV-07 | M | Wheel/pinch/keys/fit; iPad pinch |
| 37 | FR-PV-08 | A | `model-core.test.mjs` "store undo/redo 20 steps" |
| 38 | FR-PV-09 | M | Keyboard-only connect |
| 39 | FR-PV-10 | A+M | `patchview-core.test.mjs` "buildScene filters"; M: chips |
| 40 | FR-PV-11 | A+M | `model-core.test.mjs` "addDeviceFromTemplateOps", "deleteDeviceOps"; M: add ATEM |
| 41 | FR-PV-12 | A | `patchview-core.test.mjs` "autoLayout no overlap on migrated RRC" |
| 42 | FR-PV-13 | M | Viewer login → no drags |
| 43 | FR-PV-14 | M | Assistant chip highlights |
| 44 | FR-PV-15 | A | `test_frontend_smoke.py::test_patchview_perf_150_600` |
| 45 | FR-PV-16 | M | Box select (P1) |
| 46 | FR-PV-17 | M | Routes toggle on RRC (P1) |
| 47 | FR-PV-18 | M | Context menu mouse + long-press |
| 48 | FR-PT-01 | A+M | `patchtable-core.test.mjs` "fixture blocks equal golden" (golden `tests/fixtures/patchtable-sunday.json`); M: vs Knox (c) |
| 49 | FR-PT-02 | M | Patch… from the table |
| 50 | FR-PT-03 | M | Label edit + remove, undo |
| 51 | FR-PT-04 | M | Split view live update |
| 52 | FR-PT-05 | A | `patchtable-core.test.mjs` "csv equals server" (compares to `tests/fixtures/patchtable-sunday.csv` produced by T1 from the server) and `test_api.py::test_schedule_patch_csv` |
| 53 | FR-PT-06 | A | `patchtable-core.test.mjs` "filters" |
| 54 | FR-PT-07 | M | Overlay rows on RRC (P1) |
| 55 | FR-PT-08 | A | `test_frontend_smoke.py::test_viewer_pages` (`/p/…/r/main/patch`) |
| 56 | FR-MAP-01 | A | `test_api.py::test_viewer_room_maps`; `test_compat.py::test_rrc_viewer_unchanged_structure` |
| 57 | FR-MAP-02 | A | `test_compat.py::test_rrc_key_label` |
| 58 | FR-MAP-03 | M | iPhone Safari tips |
| 59 | FR-MAP-04 | M | Groups & columns dialog |
| 60 | FR-MAP-05 | M | Highlight via assistant in Map view (P1) |
| 61 | FR-MAP-06 | A | `test_api.py::test_room_index_and_device_page` |
| 62 | FR-PLAN-01 | A+M | `test_api.py::test_floorplan_uploads` (png, jpg, svg, drawio, dxf; pdf if rasterizer); M: display |
| 63 | FR-PLAN-02 | A | `test_importers.py::test_drawio_compressed_and_plain` |
| 64 | FR-PLAN-03 | A | `test_importers.py::test_dxf_fixture` |
| 65 | FR-PLAN-04 | A | `test_security.py::test_svg_sanitize` |
| 66 | FR-PLAN-05 | A | `test_importers.py::test_pdf_rasterizer_and_fallback` (skip positive half if none) |
| 67 | FR-PLAN-06 | A | `test_api.py::test_dwg_415` |
| 68 | FR-PLAN-07 | A | `test_importers.py::test_oda_fake_converter` (P1) |
| 69 | FR-PLAN-08 | A+M | `floorplan-core.test.mjs` "markerOps"; M: drag markers |
| 70 | FR-PLAN-09 | M | iPad pinch on plan |
| 71 | FR-PLAN-10 | A+M | `floorplan-core.test.mjs` "calibrate 10 m"; M: measure tool |
| 72 | FR-PLAN-11 | A+M | `test_api.py::test_floorplan_hide_layers` (P1); M toggle |
| 73 | FR-PLAN-12 | M | Two plans in campus-demo main |
| 74 | FR-PLAN-13 | A | `test_exports.py::test_build_floorplan_svg_markers` |
| 75 | FR-RACK-01 | M | Create 12U rack |
| 76 | FR-RACK-02 | A | `rack-core.test.mjs` "fixture placement U10 left" |
| 77 | FR-RACK-03 | A | `test_frontend_smoke.py::test_rack_harness` |
| 78 | FR-RACK-04 | A+M | `rack-core.test.mjs` "fits refuses overlap"; M: drag/Alt-drop |
| 79 | FR-RACK-05 | A | `test_exports.py::test_validate_racks_overlap` |
| 80 | FR-RACK-06 | A | `test_exports.py::test_build_rack_svgs` |
| 81 | FR-CAB-01 | M | Inspector cable edits round-trip |
| 82 | FR-CAB-02 | A | `test_exports.py::test_assign_tags_fixture` (exact tags of FR-CAB-02) |
| 83 | FR-CAB-03 | A | `test_api.py::test_schedule_cables_csv_header` |
| 84 | FR-CAB-04 | A | `test_exports.py::test_label_sheet_counts` |
| 85 | FR-CAB-05 | A | `test_exports.py::test_bundle_members_rrc` (P1) |
| 86 | FR-CAB-06 | A | `test_importers.py::test_cable_csv_roundtrip` |
| 87 | FR-NET-01 | A | `test_model_v2.py::test_network_validation` |
| 88 | FR-NET-02 | A | `test_importers.py::test_dante_device_info_addresses` |
| 89 | FR-NET-03 | A | `test_exports.py::test_ip_duplicate_warning` |
| 90 | FR-NET-04 | A | `test_exports.py::test_mac_normalization` |
| 91 | FR-NET-05 | A | `test_exports.py::test_ip_switch_ports_campus` (P1) |
| 92 | FR-DMX-01 | A | `test_model_v2.py::test_dmx_range_warning` |
| 93 | FR-DMX-02 | A | `test_exports.py::test_dmx_overlap` |
| 94 | FR-DMX-03 | A | `test_importers.py::test_eos_overlay_dmx` |
| 95 | FR-DMX-04 | A | `test_exports.py::test_sacn_artnet_helpers` (P1) |
| 96 | FR-LIB-01 | A | `test_importers.py::test_library_count_and_valid` |
| 97 | FR-LIB-02 | A | `test_importers.py::test_template_schema` |
| 98 | FR-LIB-03 | A+M | `test_api.py::test_library_search_rio`; M: picker |
| 99 | FR-LIB-04 | A | `test_api.py::test_custom_template_precedence` |
| 100 | FR-LIB-05 | A | `test_importers.py::test_apply_template_idempotent` |
| 101 | FR-INV-01 | M | Inventory fields round-trip |
| 102 | FR-INV-02 | M | Bulk status = one undo |
| 103 | FR-INV-03 | A+M | `test_api.py::test_file_upload_download`; M: iPad photo |
| 104 | FR-INV-04 | A | `test_api.py::test_schedule_inventory_csv` |
| 105 | FR-INV-05 | M | Quick filters (P1) |
| 106 | FR-PLN-01 | A | `test_exports.py::test_build_state_as_built` |
| 107 | FR-PLN-02 | M | Planned dashed |
| 108 | FR-PLN-03 | A | `test_exports.py::test_bom_fixture_total` |
| 109 | FR-PLN-04 | M | Mark installed (P1) |
| 110 | FR-AST-01 | M | Open/close panel |
| 111 | FR-AST-02 | A | `test_assistant.py::test_livestream_no_audio` |
| 112 | FR-AST-03 | A+M | `test_assistant.py::test_suggestion_ops`; M: Yes adds note |
| 113 | FR-AST-04 | A | `test_assistant.py::test_trace_question_tv` |
| 114 | FR-AST-05 | A | `test_assistant.py::test_locate_spare` (P1) |
| 115 | FR-AST-06 | M | Chip selects/highlights |
| 116 | FR-AST-07 | A | `test_assistant.py::test_llm_stub_and_unconfigured` |
| 117 | FR-AST-08 | A | `test_assistant.py::test_unresolved_suggestions` |
| 118 | FR-AST-09 | A | `test_assistant.py::test_cli_ask` |
| 119 | FR-TRC-01 | A | `test_assistant.py::test_port_graph_edges` |
| 120 | FR-TRC-02 | A | `test_assistant.py::test_discipline_filter_video` |
| 121 | FR-TRC-03 | A | `test_assistant.py::test_path_text_rule` |
| 122 | FR-TRC-04 | A | `tests/test_fathom.py` (frozen) + `test_assistant.py::test_cli_trace_port` |
| 123 | FR-TRC-05 | A | `patchview-core.test.mjs` "traceLocal downstream audio" (exact cable set) |
| 124 | FR-SRCH-01 | A | `test_assistant.py::test_search_ip` |
| 125 | FR-SRCH-02 | A+M | `test_ui_search.py` (dropdown keyboard and recents at d, tablet network hit, phone full screen, categories and no results, viewer drafts, inventory target), `test_ui_shell.py::test_search_palette_keyboard`, `search-core.test.mjs`; M: palette keyboard |
| 126 | FR-SRCH-03 | A | `model-core.test.mjs` "searchLocal"; `search-core.test.mjs` (`augmentLocal`); `test_ui_search.py::test_offline_fixture_and_inventory_target` |
| 127 | FR-SRCH-04 | A | `test_assistant.py::test_search_ranking`, `model-core.test.mjs` "searchLocal ranking", `test_search_kinds.py` (network kind order, fields, `kinds=network`, `status` on every hit, ranking unchanged) |
| 128 | FR-HIST-01 | A | `test_api.py::test_history_entries` |
| 129 | FR-HIST-02 | A | `test_api.py::test_restore_revision` |
| 130 | FR-HIST-03 | A | `test_api.py::test_put_requires_if_match` |
| 131 | FR-HIST-04 | A | `test_api.py::test_stale_put_rebase_and_conflict` |
| 132 | FR-HIST-05 | A | `test_api.py::test_changes_rebase_and_conflict` |
| 133 | FR-HIST-06 | M | Two tabs conflict UI |
| 134 | FR-HIST-07 | A | `test_api.py::test_history_diff` (P1) |
| 135 | FR-HIST-08 | A | `test_model_v2.py::test_history_snapshots_every_25` |
| 136 | FR-USER-01 | A | `test_security.py::test_role_matrix` |
| 137 | FR-USER-02 | A | `test_security.py::test_password_hash_format` |
| 138 | FR-USER-03 | A | `test_security.py::test_session_cookie_flags_and_epoch` |
| 139 | FR-USER-04 | A | `test_security.py::test_basic_auth_users_and_env` |
| 140 | FR-USER-05 | A | `test_security.py::test_auth_off_is_admin` |
| 141 | FR-USER-06 | A | `test_security.py::test_public_view` |
| 142 | FR-USER-07 | A | `test_security.py::test_cli_user_commands` |
| 143 | FR-USER-08 | M | Admin users UI |
| 144 | FR-USER-09 | A | `test_api.py::test_share_links` (P1) |
| 145 | FR-USER-10 | A | `test_security.py::test_login_throttle` (P1) |
| 146 | FR-MOB-01 | A+M | `tests/_ui.py` `SIZES` d 1280×900, t 820×1180 (touch), m 390×844 (touch); the `test_ui_*.py` suites check their layouts at these sizes; `test_ui_shell.py::test_sections_and_tab_bar`, `::test_no_page_hscroll_on_any_view`, `test_ui_drawer.py` (docked/sheet/full); M: three viewport sizes |
| 147 | FR-MOB-02 | M | iPad editing walkthrough |
| 148 | FR-MOB-03 | M | Phone viewer walkthrough |
| 149 | FR-MOB-04 | A+M | `test_api.py::test_manifest`; M: DevTools manifest pane |
| 150 | FR-MOB-05 | M | Offline reload on localhost |
| 151 | FR-MOB-06 | M | Make available offline → offline device page |
| 152 | FR-MOB-07 | M | §6.11 checklist |
| 153 | FR-MOB-08 | A+M | `api.test.mjs` "ChangeQueue persists and flushes" (fake fetch + fake storage); M: DevTools offline |
| 154 | FR-EXT-01 | A | `test_importers.py::test_plugin_dir_registers` |
| 155 | FR-EXT-02 | A | `test_importers.py::test_plugin_api` |
| 156 | FR-EXT-03 | A | `test_assistant.py::test_extra_checklist_dir` |
| 157 | FR-EXT-04 | A | `test_api.py::test_openapi_covers_routes` |
| 158 | FR-EXT-05 | A | `test_importers.py::test_cli_plugins` |
| 159 | FR-EXP-01 | A | `test_exports.py::test_build_layout_campus` |
| 160 | FR-EXP-02 | A | selftest (G3) + `test_exports.py::test_v1_artifacts` |
| 161 | FR-EXP-03 | A | `test_api.py::test_build_rooms_subset` |
| 162 | FR-EXP-04 | A | `test_exports.py::test_qr_public_url_branches` |
| 163 | FR-EXP-05 | A | `test_exports.py::test_report_pdf` (skip without Chrome; P1) |
| 164 | FR-QR-01 | A | `test_exports.py::test_qr_vectors` and `test_qr_rs_selfcheck` |
| 165 | FR-QR-02 | A | `test_api.py::test_qr_endpoint` |
| 166 | FR-IMP-01 | A | `test_importers.py::test_legacy_overlay_rrc` |
| 167 | FR-IMP-02 | A | `test_importers.py::test_dante_device_info_addresses` |
| 168 | FR-IMP-03 | A | `test_importers.py::test_eos_csv` |
| 169 | FR-IMP-04 | A | `test_importers.py::test_usitt_ascii` |
| 170 | FR-IMP-05 | A | `test_importers.py::test_lightwright_text` |
| 171 | FR-IMP-06 | A | `test_importers.py::test_lighting_contribution_matching` |
| 172 | FR-IMP-07 | A | `test_importers.py::test_videohub_dump` |
| 173 | FR-IMP-08 | A | `test_importers.py::test_generic_csv_preview` |
| 174 | FR-IMP-09 | A | `test_importers.py::test_atem_xml` (P2; skip if importer absent) |
| 175 | FR-IMP-10 | M | Imports view walkthrough incl. Promote |
| 175a | FR-IMP-11 | A | `test_importers.py::MagicQ` |
| 175b | FR-IMP-12 | A | `test_importers.py::CsvTemplates::test_template_download_edit_upload_roundtrip`, `GenericCsv::test_generic_csv_row_validation` |
| 176 | FR-SEC-01 | A | `test_security.py::test_path_traversal` |
| 177 | FR-SEC-02 | A | `test_security.py::test_body_caps` |
| 178 | FR-SEC-03 | A | `test_security.py::test_csrf_rule` |
| 179 | FR-SEC-04 | A | `test_security.py::test_security_headers` |
| 180 | FR-SEC-05 | A | `test_security.py::test_user_file_headers` |
| 181 | FR-SEC-06 | A | `test_security.py::test_no_secrets_exposed` |
| 182 | FR-SEC-07 | A | `test_security.py::test_concurrent_changes_lock` |
| 183 | FR-SEC-08 | A | `test_security.py::test_500_has_no_trace` |
| 184 | FR-A11Y-01 | M | Keyboard pass |
| 185 | FR-A11Y-02 | A+M | `test_frontend_smoke.py::test_aria_landmarks` (roles/labels present in dumped DOM); M: VoiceOver |
| 186 | FR-A11Y-03 | M | Contrast spot check |
| 187 | FR-A11Y-04 | M | Reduced motion |
| 188 | FR-UX-01 | M | Top bar states incl. offline/conflict |
| 189 | FR-UX-02 | A | `test_frontend_smoke.py::test_deep_link_selection` (`?sel=device:atem-mini` → inspector shows "ATEM Mini") |
| 190 | FR-UX-03 | A | `test_frontend_smoke.py::test_view_error_card` (app with `?debug_missing_view=racks` renders the error card; W5 implements this debug switch) |
| 191 | FR-UX-04 | M | Inspector fields |
| 192 | FR-UX-05 | M | Autosave off/on |
| 193 | FR-UX-06 | M | New project, settings, JSON view |
| 194 | FR-UX-07 | M | Admin views |
| 195 | FR-UX-08 | M | Theme |
| 196 | §2.3 compat | A | `tests/test_fathom.py` (frozen), `test_compat.py::test_public_v1_functions_exist`, `test_compat.py::test_py39_forbidden_syntax` (scans `fathom/**/*.py` with `ast` for `match`, PEP 604 unions in runtime positions, `zip(strict=)`, top-level `tomllib`) |
| 197 | FR-UX-09 | A | `test_ui_shell.py::test_sections_and_tab_bar`, `::test_nav_memory`, `::test_section_menu_lists_views`, `::test_legacy_project_url_lands_on_home`, `::test_empty_view_canonicalizes_to_home_and_keeps_selection`; `router-core.test.mjs`, `router-contract.test.mjs` |
| 198 | FR-UX-10 | A | `test_ui_entity.py` (sticky/compact header, tab links, arrow keys, overflow menu, unknown tab/id), `test_ui_pdev.py`, `test_ui_proom.py`, `test_ui_rk.py` (default tab replaced, tab click pushes, reload keeps the tab, explorer width persists, three sizes); `entity-core.test.mjs` |
| 199 | FR-UX-11 | A | `test_ui_datatable.py` (URL state survives reload, storage restores sort/filters, pagination and `pg`, column chooser and density, CSV of filtered rows, select-all across pages, sticky `th[scope]`, phone columns and cards, 20 000 rows); `datatable-core.test.mjs`, `datatable-contract.test.mjs` |
| 200 | FR-UX-12 | A | `test_ui_drawer.py` (modes at three sizes, Esc order, relayout, reduced motion, modal dialog above the drawer), `test_ui_ins.py` (`sec` round trip, index chips, collapse state per kind, port and cable drawer order), `test_ui_shell.py::test_deep_link_opens_drawer`, `::test_drawer_closed_shows_selection_bar`, `::test_canvas_selection_below_lg_keeps_drawer_closed`; `drawer-core.test.mjs` |
| 201 | FR-UX-13 | A | `test_ui_home.py` (three sizes, room chips, every card link mounts its view, project cards, recents order, empty project); `home-core.test.mjs`, `home-contract.test.mjs` |
| 202 | FR-UX-14 | A | `test_ui_feedback.py`, `test_ui_states_shell.py`, `test_ui_states_entity.py`, `test_ui_states_lists.py`, `test_ui_states_canvas.py`, `test_ui_states_admin.py`; `feedback-core.test.mjs`, `feedback-contract.test.mjs` |
| 203 | FR-UX-09…14 | A | `tests/test_ui_acceptance.py` (written by QA in wave 4): end-to-end acceptance of FR-UX-09…14 |

---

## 10. Research notes (with citations)

Research done 2026-10-20 by web search and vendor documentation. Each note states what we learned and the decision it drove.

### 10.1 AV design & documentation tools

- **D-Tools System Integrator / Cloud**: engineering drawings (line diagrams, plan views with DWG import, rack elevations, schematics) synchronized with the BOM, "draw-first" BOM generation, port-level interconnect schematics in D-Tools Cloud, title blocks, and installation reports including wire checklists and wire labels by head end / location / wire number on 21-up label sheets. → One model drives drawings + BOM (§1.1), port-level cables (FR-PORT), label sheets with configurable grids (FR-CAB-04). Sources: https://www.d-tools.com/system-integrator-features , https://www.d-tools.com/system-integrator , https://www.d-tools.com/system-design , https://docs.d-tools.com/en/articles/9220891-wire-labels , https://docs.d-tools.com/en/collections/9259789-installation-reports
- **Stardraw Design 7.4**: block schematics with rubber-banding cables, auto-incrementing cable labels, start/middle/end labels, cable schedules exported to Excel (start product, start port, labels, end port, end product), cables grid view with editing, layers for Audio/Video/Control/Power/Lighting, rack layouts front/rear/side on a 1 RU grid, DWG/DXF import R12–2018. → Disciplines incl. power and control (Appendix A.3), cable schedule columns (§5.8.2), front/rear rack views (FR-RACK-03). Sources: https://stardraw.com/sd7/features/modules/blockschematic , http://blob.stardraw.com/www/products/stardrawdesign7_4/help/Cable_Schedule.htm , https://www.stardraw.com/sd7/features/modules/racklayout , https://stardraw.com/sd7/features/utilities/dwgimportexport , https://www.stardraw.com/sd7/overview
- **XTEN-AV X-DRAW / X-DOC**: line schematics and signal flow, rack elevations with RU assignment from the BOM, floor plans (upload AutoCAD drawings, place products which then join the BOM), multiple drawing tabs per project, cable schedules from connections, design ZIP export (BOM, cable schedule, schematics, rack layout, floor plans), mobile viewing of signal flow. → Multiple rooms/views per project (FR-ROOM), floor-plan markers tied to devices (FR-PLAN-08), zip package (§5.9). Sources: https://knowledgebase.xtenav.com/en-us/article/what-is-the-difference-between-x-draw-x-doc-and-x-pro-1ieqec4/ , https://knowledgebase.xtenav.com/en-us/category/x-draw-1w51sk9/ , https://xtenav.com/blog/commercial-av-installation-documentation/ , https://knowledgebase.xtenav.com/en-us/article/how-can-i-create-a-rack-elevation-based-on-the-bom-10qwkk5/
- **designMACHINE (Simply Reliable)**: auto-generated wiring diagrams, cable schedules with wire numbers at both ends, labels, IP address schedule, BOM, floor plans (drag a room's products onto the print), as-builts imported from Control4/Crestron/Savant projects; J-STD-710 symbols. → IP schedule (FR-NET), both-end labels (FR-CAB-04); control-system as-built import on the roadmap (§2.2). Sources: https://www.simplyreliable.com/designmachine/ , https://www.simplyreliable.com/faq/ , https://www.simplyreliable.com/design-systems-minutes-not-hours-days/
- **Knox (knoxav.com)** — interaction reference: patch view of device cards with numbered port rows and colored wires ("Drag gear · re-patch wires · rename anything"), patch table per device with "Patch…" placeholders and "Live — edits update the map above", a "Knox Helper" that traces the stream path and offers "Update the map?", and per-map sharing with Owner/Editor/Viewer roles. → FR-PV, FR-PT, FR-AST, FR-USER, share links (FR-USER-09). Source: https://knoxav.com

### 10.2 Standards & practice (AVIXA / CEDIA)

- **ANSI/INFOCOMM J-STD-710 (CEA/CEDIA-2039)** standardizes architectural floor-plan and reflected-ceiling-plan **symbols** for AV/control; it is not a cable-labeling standard. → Floor-plan markers with discipline color now; J-STD-710 symbol set is a possible later marker style. Sources: https://webstore.ansi.org/preview-pages/ANSI/preview_ANSI+J-STD-710-2015.pdf , https://www.avixa.org/resources/standards/av-control-architectural-drawing-symbols
- **AVIXA F501.01:2015 Cable Labeling for Audiovisual Systems**: each cable has a human-readable alphanumeric **unique identifier** defined by the project's scheme, on the first row nearest the connector, with a consistent number of digits; optional prefix/suffix (signal type, room…); optional secondary source-to-destination data; same identifier at both ends; machine-readable codes optional. Georgia Tech's AV standard uses `X###` with type letters (A audio, V video, C control, S speaker, N network, U USB). → Tag pattern `{D}-{n:03}` with discipline letters, both-end labels with FROM → TO row, optional QR (FR-CAB-02/04, §4.8). Sources: https://www.avixa.org/resources/standards/cable-labeling-for-av-systems , https://pdfcoffee.com/download/cable-labeling-working-draft-for-town-hall-pdf-free.html , https://standards.avservices.gatech.edu/standards/audiovisual_standard/
- **EIA-310**: 1 RU = 1.75 in (44.45 mm); 19-in racks; AVIXA F502.01/F502.02 cover rack building/planning. → `u`/`height` integer RU model, half-width side (FR-RACK-02). Sources: https://www.racksolutions.com/news/data-center-optimization/eia-310-definition/ , https://aeonstech.com/blogs/aeons-blogs/standard-rack-and-eia-310

### 10.3 Lighting

- **ETC Eos exports**: USITT ASCII (`.asc`, optional manufacturer data, comma delimiter, mixed-case keywords) and CSV (block format `START_<X>`/`END_<X>` with a title row; community-documented columns include `CHANNELS: CHANNEL FIXTURE_TYPE ADDRESS LABEL PROPORTION CURVE` and `FIXTURES: FIXTURE_TYPE_NAME FIXTURE_TYPE_MANUFACTURER … PARAMETER_ADDRESS_OFFSET …`). Eos also imports Lightwright text patches (Channel, Address, Type, Fixture Type headers). → FR-IMP-03/04/05. Sources: https://www.etcconnect.com/WebDocs/Controls/EosFamilyOnlineHelp/en/Content/05_Show_Files/Exporting_Show_Data.htm , https://support.etcconnect.com/ETC/Consoles/Eos_Family/Software_and_Programming/Importing_and_Exporting_CSV_Files_for_Eos , https://community.etcconnect.com/control_consoles/eos-family-consoles/f/eos-family/25263/is-there-a-document-listing-all-the-targets-lists-and-other-types-that-are-exported-in-the-csv-export-file , https://support.etcconnect.com/ETC/Consoles/Eos_Family/Software_and_Programming/CSV_Importing_and_Exporting_for_Pixel_Maps , https://www.manula.com/manuals/avld/mla/131/en/topic/import-export-eos-patch
- **USITT ASCII 3.0**: `PATCH page chan<dim@level …`; page required (1 when no pages); delimiters tab, space and `, / ; < = > @` are interchangeable; keywords unique in 10 chars; `ENDDATA`; `$`/`$$` manufacturer records. → FR-IMP-04 parser rules. Sources: http://moicestpilou.free.fr/export/ASCII-protocol.pdf , http://westsidesystems.com/alq/sample.html , https://support.etcconnect.com/ETC/Consoles/Eos_Family/Software_and_Programming/Eos_Family_USITT_ASCII_Import
- **grandMA3**: patch export is grandMA3 XML (`/gma3_library/patch`) or **MVR**; CSV only via third-party plugins (e.g. ma3.tools PatchExporter). → MVR (open, zip + XML) is the right future path (§2.2) rather than MA XML now. Sources: https://help.malighting.com/grandMA3/2.5/HTML/patch.html , https://help.malighting.com/grandMA3/2.5/HTML/keyword_export.html , https://www.ma3.tools/Exporters/Patch/
- **MVR / GDTF (DIN SPEC 15801/15800)**: `.mvr` zip with `GeneralSceneDescription.xml`; `Fixture` nodes carry `FixtureID`, `UnitNumber`, `GDTFSpec`, `GDTFMode`, and `Addresses/Address break="0"` as absolute or `Universe.Address`. → Roadmap importer maps onto `device.dmx`. Sources: https://github.com/mvrdevelopment/spec/blob/main/mvr-spec.md , https://www.gdtf.eu/mvr/mvr-spec/file-format-definition/
- **Lightwright / Vectorworks Spotlight**: shared fields Unit Number, Channel, Dimmer, Universe, Address (absolute), Position, Purpose, Color, Instrument Type; Lightwright links Address, Universe and "u/a" forms. → FR-IMP-05 header synonyms and address forms. Sources: https://www.lightwright.com/docs/user-guide/14-external-integration/01-vectorworks.html , https://www.lightwright.com/lightwright-6/support/addresses , https://lw-static-assets.s3.amazonaws.com/assets/pdf/LW6_Reference_Manual.pdf
- **sACN (ANSI E1.31) & Art-Net 4**: sACN universes 1–63999 on UDP 5568, multicast `239.255.<hi>.<lo>` (universe 300 → 239.255.1.44); Art-Net 4 15-bit Port-Address Net(7)/Sub-Net(4)/Universe(4), 0–32767 (0 deprecated), counting from 0. → `dmx.universe` 1–63999 and FR-DMX-04 helpers. Sources: https://art-net.org.uk/downloads/art-net.pdf , https://www.dmxdesktop.com/guides/what-is-sacn , https://www.cuesync.live/docs/connect/art-net-and-sacn
- **Console/fixture port counts** used in Appendix E: ETC Ion Xe 20 has four DMX/RDM 5-pin ports and two Gigabit RJ45; Eos Apex has an I/O Garage (Gadget II, 2 DMX each), four etherCON PoE++ ports and two SFP+. Sources: https://www.etcconnect.com/Products/Consoles/Eos-Consoles/Ion-Xe/Tech-Specs.aspx , https://www.etcconnect.com/Products/Consoles/Eos-Consoles/Apex/Tech-Specs.aspx , https://www.christielites.com/file_uploads/Eos_Apex_10_Datasheet_revA.pdf

### 10.4 Video

- **ChamSys MagicQ**: the `.shw` show file is proprietary and undocumented (header `\ MagicQ Show File. Chamsys Ltd.`); the patch leaves the console as a head-list CSV — Patch → View Heads → File → Print Window → Create CSV (user-selected columns), or in older versions Patch → View Chans → EXPORT HEADS with fixed columns `Headno, Headname, Dmxno, Headtype, Gel, Pinv, Tinv, Swap` (`Dmxno` `1-001`). IMPORT HEADS documents the accepted heading synonyms and `,`/`;` delimiter detection; MagicQ imports MVR but does not export it. → FR-IMP-11. Sources: https://docs.chamsys.co.uk/magicq/1.9.9.x/manual/patching.html , https://secure.chamsys.co.uk/docs/magicq/manual/system_management.html , https://squaresmile.de/help/lighting-watchdog/magicq
- **Blackmagic Videohub Ethernet Protocol v2.3**: text protocol on TCP 9990, blocks with an ALL-CAPS header and colon terminated by a blank line (`VIDEOHUB DEVICE:`, `INPUT LABELS:`, `OUTPUT LABELS:`, `VIDEO OUTPUT ROUTING:`, monitoring/serial/lock/status blocks), zero-based port numbers, clients must ignore unknown blocks/lines. → FR-IMP-07 parses a saved dump; live polling is roadmap. Sources: https://documents.blackmagicdesign.com/DeveloperManuals/VideohubEthernetProtocol.pdf , https://documents.blackmagicdesign.com/DeveloperManuals/VideohubDeveloperInformation.pdf
- **ATEM**: ATEM Software Control saves switcher state as XML; inputs have a 20-char long name, 4-char short name and port type (SDI/HDMI/…). ATEM 1 M/E Constellation HD: 10 × 3G-SDI in, 6 × 3G-SDI out, USB-C webcam out, 2 × ¼" TRS audio in. → FR-IMP-09 (P2) and Appendix E. Sources: https://docs.openswitcher.org/commands/hardware.html , https://www.avned.nl/avned-uploads/handleiding/user-manual-atem-constellation_Engels.pdf , https://www.blackmagicdesign.com/products/atemconstellation/techspecs
- **Ross Ultrix**: source/destination tables export/import as `.xlsx` in DashBoard 6.0+ (no CSV); copy/paste to a spreadsheet works. → Use the generic CSV importer (user saves the sheet as CSV); no native Ultrix importer now. Sources: https://rossvideo.community/discussion/exporting-ultrix-db , https://documentation.rossvideo.com/files/Manuals/Routers/Ultrix/User%20Guides/Ultrix%20and%20Ultricore%20Database%20Guide.pdf
- **Interfaces**: SDI rates (ST 259 SD, ST 292 HD, ST 424 3G, ST 2081 6G, ST 2082 12G), HDMI 1.4/2.0/2.1, DisplayPort, HDBaseT, NDI/NDI HX, SMPTE ST 2110. → Media `sdi, hdmi, displayport, hdbaset, fiber, ndi, st2110` with `carries` (Appendix A.2). Sources: https://coolaboolatech.com/mediaserver/standards/ , https://www.smpte.org/standards/st2110 , https://the-audio-video-company.com/education/networking/av-over-ip

### 10.5 Audio networks beyond Dante

- **Dante Controller Device Info** shows device name, model, versions, Primary/Secondary Address and link speeds (no MAC); no native CSV export — users copy the table; Dante Domain Manager shows primary/secondary IPs per device. → FR-IMP-02 reads the pasted table's address columns. Sources: https://dev.audinate.com/GA/dante-controller/userguide/webhelp/content/device_info_view.htm , https://dev.audinate.com/GA/ddm/userguide/1.7/webhelp/content/ui_device_details.htm , https://www.reddit.com/r/audinate_dante/comments/1k1klet/data_export/
- **AES67 / Milan-AVB / Q-SYS**: L-Acoustics LA7.16i takes Milan-AVB or AES67 on two etherCON ports plus one AES3/analog aux input, 16 outputs on 8 terminal blocks; Q-SYS Designer has no design-inventory CSV export (Core Manager bulk configuration CSV covers MAC/IP), inventory available via Lua `Design.GetInventory`. → Media `aes67`, `avb`, `qlan`; Q-SYS import is roadmap; generic CSV covers Q-SYS bulk CSV columns. Sources: https://www.l-acoustics.com/products/la7-16i/ , https://help.qsys.com/Content/Core_Manager/System_Management/Bulk_Peripheral_Management.htm , https://help.qsys.com/Content/Control_Scripting/Using_Lua_in_Q-Sys/Design.htm , https://www.qscaudio.com/resource-files/applicationguides/systems/q_qsg_sys_dn_qsys_aes67.pdf
- **Shure Wireless Workbench**: inventory report exports PDF/CSV (headers undocumented); coordination report CSV and native `.shw`/`.cws` XML are undocumented but readable. → Roadmap; generic CSV handles flat exports. Sources: https://content-files.shure.com/Pubs/WWB/en-US/en-US/reports.html , https://github.com/allansargeant/wsm-wwb-bridge
- **Port counts** used in Appendix E: Yamaha DM7 (32 in / 16 out, Dante 144×144, AES 2 in/2 out), DM7 Compact (16/16), TF-Rack (16 mic/line + stereo RCA, 16 outs, NY64-D slot), Rio3224-D2 (32/16 + 8 AES out, 5U) and Rio1608-D2 (16/8, 3U), SQ-5 (16 XLR in, talkback, 12 XLR + 2 TRS out, AES out, SLink), AR84 (8 in, 4 out, dSnake). Sources: https://usa.yamaha.com/products/proaudio/mixers/dm7/specs.html , https://usa.yamaha.com/products/proaudio/mixers/tf-rack/specs.html , https://usa.yamaha.com/products/proaudio/interfaces/r_series_adda_2/specs.html , https://www.allen-heath.com/content/uploads/2023/05/SQ-5-Technical-Datasheet_G.pdf , https://support.allen-heath.com/hc/en-gb/articles/40221963830161-AR84-Getting-Started-Guide
- **Extron IPCP Pro 350**: 1 × RS-232/422/485, 2 × RS-232, 2 × IR/serial, 4 relays, 4 digital I/O, eBUS, 3-port LAN switch. Source: https://www.it-revolutions.com/wp-content/uploads/2022/09/IPCP_Pro_350_datasheet.pdf

### 10.6 Floor-plan formats

- **Draw.io**: a `.drawio` file is `<mxfile>` with one `<diagram>` per page holding either an `<mxGraphModel>` child or compressed text = Base64(raw DEFLATE(encodeURIComponent(xml))); Python decode `urllib.parse.unquote(zlib.decompress(base64.b64decode(t), -15).decode())`; new files are uncompressed by default. → FR-PLAN-02, Appendix D.1 fixture (verified round-trip). Source: https://github.com/jgraph/drawio/wiki/File-Format
- **DXF**: ASCII group-code/value pairs; sections HEADER, TABLES (LAYER), BLOCKS, ENTITIES; LWPOLYLINE codes 90/70/10/20/42 (bulge); INSERT 2/10/20/41/42/50/70/71; `$INSUNITS` code 70 (0 unitless, 1 in, 2 ft, 4 mm, 5 cm, 6 m …). → FR-PLAN-03 subset. Sources: https://damassets.autodesk.net/content/dam/autodesk/www/developer-network/platform-technologies/autocad-dxf-archive/acad_r12_dxf.pdf , https://help.autodesk.com/cloudhelp/2023/ENU/AutoCAD-DXF/files/GUID-748FC305-F3F2-4F74-825A-61F04D757A50.htm , https://documentation.help/AutoCAD-DXF/WS1a9193826455f5ff18cb41610ec0a2e719-7a04.htm , https://images.autodesk.com/adsk/files/autocad_2012_pdf_dxf-reference_enu.pdf
- **DWG**: closed, version-fragmented binary; no reliable pure-Python reader; the practical route is the free ODA File Converter (`<inDir> <outDir> <ver> DXF <recurse> <audit> <filter>`, Qt app needing `xvfb-run -a` headless, exit code unreliable — verify the output file). → FR-PLAN-06/07, roadmap for native DWG. Sources: https://www.opendesign.com/guestfiles/oda_file_converter , https://www.cad-gis-bim-interop.org/python-parsing-geometry-extraction/pydwg-integration/batch-converting-dwg-to-dxf-with-oda-file-converter/
- **PDF**: headless Chrome (old and `--headless=new`) does **not** render PDFs to screenshots (it treats them as downloads); rasterize with poppler `pdftoppm`, MuPDF `mutool`, Ghostscript, or macOS `sips`. **This overrides the brief's "PDF via Chrome" idea** (decision D-03). Sources: https://github.com/puppeteer/puppeteer/issues/1872 , https://developer.chrome.com/docs/automation-and-testing/headless-cli
- **SVG**: scripts and external references in user SVG are an XSS vector when served same-origin; display via `<img>` (no script execution) plus sanitization and a sandbox CSP. (Design decision; standard web-security practice.)

### 10.7 Mobile / PWA

- iOS/iPadOS Safari reads `name`, `short_name`, `start_url`, `scope`, `display: standalone`, `id`, `theme_color`; `icons` only without `apple-touch-icon`; no `background_color` splash; manifest changes don't update existing installs; since iOS 26 every Home Screen site opens as a web app by default; Home Screen app storage is isolated from Safari (cookies copied at install); eviction is LRU under pressure; `navigator.storage.persist()` helps. → FR-MOB-04/05, offline-manifest prefetch, apple-touch-icon. Sources: https://progressivewebapps.com/platforms/ios-safari/ , https://webkit.org/blog/17333/webkit-features-in-safari-26-0/ , https://webkit.org/blog/14403/updates-to-storage-policy/ , https://openpwa.net/reference/storage/home-screen-storage-isolation/
- Service worker scope = its URL path; register at the app root. Service workers require a secure context (HTTPS or localhost) — a LAN `http://192.168…` deployment gets no offline mode (documented in-app). Source: https://web.dev/learn/pwa/service-workers
- Touch: `touch-action: none` only on custom canvases; iOS Safari additionally needs `gesturestart/gesturechange/gestureend` `preventDefault()` and non-passive `touchmove` when two touches are active; pointer events with capture; reset on `pointercancel`; `100dvh` instead of `100vh`. → §6.11. Sources: https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/touch-action , https://le.land/blog/ios-mobile-web-meta/ , https://github.com/byronjohnson/litelight/issues/5 , https://github.com/tldraw/tldraw/blob/c8a2902d/packages/editor/src/lib/hooks/useGestureEvents.ts

### 10.8 Assistant & security primitives

- OpenAI-compatible Chat Completions (`POST /v1/chat/completions`, `model` + `messages`, response `choices[0].message.content`) is implemented by Ollama (`http://localhost:11434/v1`) and LM Studio (`http://localhost:1234/v1`) as well as hosted APIs → one stdlib `urllib` client covers local and cloud models (FR-AST-07). Sources: https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx , https://beta.lmstudio.ai/docs/developer/openai-compat/chat-completions , https://developers.openai.com/api/reference/resources/chat/
- Password storage: OWASP recommends PBKDF2-HMAC-SHA256 with ≥ 600 000 iterations when Argon2id/scrypt are unavailable (stdlib has `hashlib.pbkdf2_hmac`). → FR-USER-02. Source: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- QR encoding (ISO/IEC 18004): byte mode indicator `0100`, 8-bit count for versions 1–9 and 16-bit for 10–40, RS over GF(256) with modulus `0x11D`, block interleaving, 8 masks scored by penalties N1–N4 (3, 3, 40, 10). Reference implementation for cross-checking: Nayuki QR-Code-generator (MIT). Appendix C vectors were generated with python-qrcode 8 (byte mode, level M, mask fixed to 2). Sources: https://www.thonky.com/qr-code-tutorial/data-encoding , https://www.thonky.com/qr-code-tutorial/error-correction-coding , https://www.thonky.com/qr-code-tutorial/data-masking , https://github.com/nayuki/QR-Code-generator , https://useqr.app/docs/reference

### 10.9 Decisions taken without the owner (summary; details in the reply)

| ID | Decision |
| --- | --- |
| D-01 | Ports are stored **explicitly** per device (templates use groups); port ids are stable strings. |
| D-02 | All writes are **ops** with entity-level optimistic concurrency (rebase when disjoint), not whole-file last-writer-wins and not CRDT. |
| D-03 | PDF floor plans are rasterized by local tools (poppler/mutool/gs/sips), not Chrome (Chrome cannot). Docker ships poppler-utils. |
| D-04 | DWG is not parsed; DXF/PDF/SVG requested; optional ODA bridge. |
| D-05 | v1 `PUT` only for v1-expressible docs; otherwise 409 `v2_required`. |
| D-06 | Storage stays JSON files (no SQLite); history = ops log + snapshot every 25 revisions. |
| D-07 | RRC sample stays v1 (exercises migration); new v2 sample `campus-demo`; canonical test fixture `sunday-demo` modelled on the Knox screenshots. |
| D-08 | Assistant is deterministic first; LLM optional, env-configured, clearly labelled, never applies changes. |
| D-09 | Hash routing, lazy view modules, autosave on by default, undo stack per session shared by all views. |
| D-10 | ES2018 syntax ceiling kept as briefed (even though Safari 15 supports more). |
| D-11 | Lengths stored in meters; display per project units. |
| D-12 | Version 0.3.0; PyPI name `fathom-audio` unchanged. |

---

## Appendix A — Vocabulary tables (`fathom/vocab.py`)

### A.1 Device kinds (35)

`side` = default side on the signal-flow map; `routing` = default internal routing (§4.4.5); `legacy` = v1 kind whose layout heuristics apply (used by `layout.py` default-column logic and `merge.py` side inference). The first 9 rows are v1 and their `color` MUST NOT change; the v1 `network` label changes to "Network" (the map key shows the spine label for this row when the spine is drawn, FR-MAP-02).

| key | label | discipline | color | side | routing | legacy |
| --- | --- | --- | --- | --- | --- | --- |
| `source` | Sources | audio | `#2fd4b4` | left | none | source |
| `stage_io` | Stage I/O | audio | `#4ea8ff` | left | matrix | stage_io |
| `computer` | Computers | audio | `#a98bff` | left | matrix | computer |
| `console` | Consoles | audio | `#7c5cff` | right | matrix | console |
| `iem` | IEM gear | audio | `#f06aa8` | right | matrix | iem |
| `pa` | PA · amps, speakers | audio | `#ff9548` | right | matrix | pa |
| `network` | Network | network | `#7b86ff` | right | matrix | network |
| `video` | Video | video | `#c084fc` | left | matrix | video |
| `other` | Other | other | `#9aa3b5` | right | matrix | other |
| `mic` | Microphones | audio | `#2fd4b4` | left | none | source |
| `wireless_rx` | Wireless receivers | audio | `#38bdf8` | left | matrix | stage_io |
| `processor` | Processors · DSP | audio | `#60a5fa` | right | matrix | console |
| `amp` | Amplifiers | audio | `#fb923c` | right | matrix | pa |
| `speaker` | Loudspeakers | audio | `#fdba74` | right | passthrough | pa |
| `recorder` | Recorders | audio | `#a78bfa` | right | matrix | computer |
| `intercom` | Intercom | audio | `#f472b6` | right | matrix | other |
| `camera` | Cameras | video | `#34d399` | left | matrix | video |
| `video_source` | Playback · media servers | video | `#2dd4bf` | left | matrix | video |
| `video_switcher` | Video switchers | video | `#22c55e` | right | matrix | console |
| `video_router` | Video routers | video | `#10b981` | right | matrix | console |
| `converter` | Converters · extenders | video | `#86efac` | right | matrix | video |
| `encoder` | Encoders · streaming | video | `#4ade80` | right | matrix | computer |
| `stream` | Stream destinations | network | `#fb923c` | right | none | pa |
| `display` | Displays | video | `#a3e635` | right | passthrough | pa |
| `projector` | Projectors | video | `#bef264` | right | none | pa |
| `lighting_console` | Lighting consoles | lighting | `#fbbf24` | left | matrix | console |
| `dmx_node` | DMX nodes · splitters | lighting | `#f59e0b` | right | matrix | stage_io |
| `dimmer` | Dimmers · relays | lighting | `#eab308` | right | matrix | pa |
| `fixture` | Lighting fixtures | lighting | `#fde047` | right | passthrough | pa |
| `switch` | Network switches | network | `#fb923c` | right | matrix | network |
| `control` | Control processors | control | `#c084fc` | right | matrix | other |
| `touch_panel` | Touch panels | control | `#d8b4fe` | left | none | source |
| `power` | Power · UPS · PDU | power | `#f87171` | right | matrix | other |
| `patch_panel` | Patch panels · wall plates | other | `#94a3b8` | right | passthrough | stage_io |
| `container` | Container / case | other | `#8b94a6` | right | none | other |

### A.2 Media (41)

`carries` uses discipline keys; `ip` = appears in the IP schedule; `short` = tag token `{M}` and patch-table fallback heading. The first 14 rows are v1: `label/color/dash/width/arrow` MUST NOT change.

| key | label | discipline | color | dash | width | arrow | carries | ip | connector | short |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `dante` | Dante · Cat6 | audio | `#7b86ff` | | 1.6 | no | audio, network | yes | etherCON | DANTE |
| `analog` | Analog · XLR | audio | `#aab3c5` | | 1.4 | yes | audio | no | XLR3 | XLR |
| `aes3` | AES3 · 110 Ω | audio | `#2dd4ee` | `7 4` | 1.5 | yes | audio | no | XLR3 | AES |
| `aes50` | AES50 · Cat5e | audio | `#5ac8fa` | `2 4` | 1.6 | no | audio, control | no | etherCON | AES50 |
| `madi` | MADI | audio | `#fbbf24` | `10 4` | 1.5 | yes | audio | no | BNC | MADI |
| `avb` | AVB / Milan | audio | `#34d399` | `6 3 2 3` | 1.5 | no | audio, network | yes | etherCON | AVB |
| `speaker` | Speaker · NL4/NL8 | audio | `#ff9548` | | 1.8 | yes | audio | no | NL4 | SPK |
| `iem_wired` | Wired IEM | audio | `#f472b6` | `1.5 4` | 1.6 | yes | audio | no | TRS 1/4" | IEM |
| `iem_wireless` | Wireless IEM | audio | `#e879f9` | `1.5 6` | 1.6 | yes | audio | no | RF | IEM |
| `rf` | RF · wireless mic | audio | `#f0abfc` | `1.5 6` | 1.6 | yes | audio | no | BNC | RF |
| `usb` | USB | other | `#cbd5e1` | `4 3` | 1.2 | yes | audio, video, control | no | USB-C | USB |
| `video` | SDI / HDMI | video | `#c084fc` | | 1.2 | yes | video, audio | no | BNC | VID |
| `network` | Control · IP | network | `#94a3b8` | `3 3` | 1.0 | no | network, control, audio, video, lighting | yes | RJ45 | CAT |
| `other` | Other | other | `#9aa3b5` | | 1.2 | yes | audio, video, lighting, control, network, power | no | | OTH |
| `aes67` | AES67 · IP audio | audio | `#818cf8` | | 1.6 | no | audio, network | yes | RJ45 | AES67 |
| `qlan` | Q-LAN | audio | `#60a5fa` | | 1.6 | no | audio, video, control, network | yes | RJ45 | QLAN |
| `snake` | Digital snake · Cat5e | audio | `#38bdf8` | `2 3` | 1.6 | no | audio, control | no | etherCON | SNAKE |
| `adat` | ADAT · optical | audio | `#67e8f9` | `1 3` | 1.4 | yes | audio | no | TOSLINK | ADAT |
| `speaker_70v` | 70/100 V line | audio | `#fdba74` | `8 3` | 1.6 | yes | audio | no | terminal | 70V |
| `intercom` | Intercom · XLR | audio | `#fb7185` | `5 2 1 2` | 1.4 | no | audio, control | no | XLR3 | COM |
| `sdi` | SDI · 75 Ω BNC | video | `#facc15` | | 1.6 | yes | video, audio | no | BNC | SDI |
| `hdmi` | HDMI | video | `#f59e0b` | | 1.6 | yes | video, audio | no | HDMI-A | HDMI |
| `displayport` | DisplayPort | video | `#fda4af` | | 1.4 | yes | video, audio | no | DP | DP |
| `hdbaset` | HDBaseT · Cat6 | video | `#fcd34d` | `5 2` | 1.6 | yes | video, audio, control | no | RJ45 | HDBT |
| `fiber` | Fiber | other | `#22d3ee` | `12 3` | 1.6 | no | audio, video, network, control, lighting | no | LC | FIB |
| `ndi` | NDI · IP video | video | `#a3e635` | `4 2` | 1.4 | no | video, audio, network | yes | RJ45 | NDI |
| `st2110` | SMPTE ST 2110 | video | `#84cc16` | `4 2 1 2` | 1.4 | no | video, audio, network | yes | SFP | 2110 |
| `dmx` | DMX512 · XLR5 | lighting | `#fde047` | | 1.6 | yes | lighting | no | XLR5 | DMX |
| `rdm` | DMX + RDM | lighting | `#fef08a` | `6 2` | 1.6 | no | lighting, control | no | XLR5 | RDM |
| `sacn` | sACN (E1.31) | lighting | `#fbbf24` | `3 2` | 1.4 | yes | lighting, network | yes | RJ45 | SACN |
| `artnet` | Art-Net | lighting | `#f59e0b` | `3 2 1 2` | 1.4 | yes | lighting, network | yes | RJ45 | ARTN |
| `rs232` | RS-232 · serial | control | `#c4b5fd` | `2 2` | 1.0 | yes | control | no | DB9 | 232 |
| `rs422` | RS-422/485 | control | `#a78bfa` | `2 2` | 1.0 | no | control | no | Phoenix | 422 |
| `ir` | IR emitter | control | `#ddd6fe` | `1 3` | 1.0 | yes | control | no | TS 3.5mm | IR |
| `gpio` | GPIO · contact closure | control | `#e9d5ff` | `1 2` | 1.0 | yes | control | no | Phoenix | GPIO |
| `osc` | OSC · IP control | control | `#d8b4fe` | `3 3` | 1.0 | yes | control, network | yes | RJ45 | OSC |
| `midi` | MIDI | control | `#f0abfc` | `2 3` | 1.0 | yes | control | no | DIN5 | MIDI |
| `timecode` | Timecode (LTC) | control | `#f5d0fe` | `1 2` | 1.0 | yes | control | no | XLR3 | LTC |
| `sync` | Sync · word clock / genlock | other | `#94a3b8` | `1 4` | 1.0 | yes | control | no | BNC | SYNC |
| `power` | Power · mains | power | `#f87171` | | 2.0 | yes | power | no | IEC C13 | PWR |
| `power_dc` | DC power | power | `#fca5a5` | | 1.4 | yes | power | no | barrel | DC |

### A.3 Disciplines (7)

| key | label | color | letter |
| --- | --- | --- | --- |
| `audio` | Audio | `#4ea8ff` | A |
| `video` | Video | `#34d399` | V |
| `lighting` | Lighting | `#fbbf24` | L |
| `network` | Network | `#fb923c` | N |
| `control` | Control | `#c084fc` | C |
| `power` | Power | `#f87171` | P |
| `other` | Other | `#9aa3b5` | X |

### A.4 Connectors (suggestions, not enforced)

`XLR3F, XLR3M, XLR5F, XLR5M, XLR/TRS combo, TRS 1/4", TS 1/4", TRS 3.5mm, TS 3.5mm, RCA, BNC, HD-BNC, NL2, NL4, NL8, terminal, Phoenix, etherCON, RJ45, SFP, SFP+, LC, SC, ST, opticalCON, TOSLINK, HDMI-A, HDMI-mini, HDMI-micro, DP, mini DP, USB-A, USB-B, USB-C, DB9, DB15, DB25, DIN5, IEC C13, IEC C14, IEC C19, IEC C20, powerCON, powerCON TRUE1, Edison 5-15, Edison 5-20, Schuko, L5-20, Socapex 19, barrel, F-type, TNC, DVI, VGA`

### A.5 Other enums

- `STATUSES = ("installed", "planned", "spare", "retired")`
- `CONDITIONS = ("new", "good", "fair", "poor", "broken")` — `device.inventory.condition` (FR-INV-06); `GET /api/v2/meta` → `conditions` (also `vocab.conditions`)
- `ROOM_KINDS = ("auditorium", "sanctuary", "chapel", "theatre", "studio", "control_room", "broadcast", "classroom", "conference", "lobby", "outdoor", "rack_room", "storage", "other")`
- Location kinds: `booth, stage, rack_room, storage, catwalk, closet, other`
- Rack `numbering`: `bottom_up, top_down`; `face`: `front, rear`; `side`: `full, left, right`; `depth`: `full, half`
- Interface `role`: `primary, secondary, control, management, media`; `protocol`: `dante, aes67, avb, ndi, st2110, sacn, artnet, qlan, control, management, other`
- DMX `protocol`: `dmx, sacn, artnet`
- Symptoms (assistant): `no_audio, no_video, noise, feedback, dropout, latency, no_power, no_network, lighting_no_response, flicker, wrong_source, general`

### A.6 Brands (text badges; v1 entries unchanged, additions)

Add with the same shape `{text, bg, fg, style}`: `ma` ("MA", `#111111`/`#f5c518`), `etc` ("ETC", `#111111`/`#ffffff`), `chauvet` ("CHAUVET", `#111111`/`#e5e7eb`), `martin` ("MARTIN", `#111111`/`#ef4444`), `panasonic` ("Panasonic", `#f3f4f6`/`#1d4ed8`, serif), `sony` ("SONY", `#111111`/`#ffffff`), `epson` ("EPSON", `#f3f4f6`/`#1e3a8a`), `samsung` ("SAMSUNG", `#1e3a8a`/`#ffffff`), `extron` ("EXTRON", `#111111`/`#ffffff`), `crestron` ("CRESTRON", `#111111`/`#93c5fd`), `cisco` ("CISCO", `#f3f4f6`/`#0369a1`), `netgear` ("NETGEAR", `#111111`/`#a78bfa`), `ubiquiti` ("UBNT", `#f3f4f6`/`#0ea5e9`), `decimator` ("DECIMATOR", `#111111`/`#f97316`), `whirlwind` ("WHIRLWIND", `#111111`/`#e5e7eb`), `electro-voice` ("EV", `#111111`/`#ef4444`).

---

## Appendix B — Canonical fixture `sunday-demo` (v2)

W1 commits this JSON **byte-for-byte** as `fathom/static/dev/fixture-v2.json`; T1/T2 also load it from there. It models the Knox screenshots (b)/(c): 12 devices (one spare in shared inventory), 47 ports, 15 cables, one rack, one network. It is the reference for FR-AST-02/03, FR-CAB-02, FR-PLN-03, FR-TRC-02/05, FR-PT-01 and §5.10. Templates it references (`shure-ulxd4d`, `allen-heath-sq-5`, `allen-heath-ar84`, `blackmagic-atem-mini-pro`, `qsc-k12-2`, `decimator-md-hx`) exist in Appendix E; its own `ports` are instance data and intentionally differ from the templates (Knox-style labels).

```json
{
  "fathom": 2,
  "revision": 1,
  "meta": {"org": "Hillside Church", "system": "Main Auditorium", "title": "Signal flow, mic to stream", "intro": "", "footnote": "", "slug": "sunday-demo"},
  "settings": {"default_room": "main", "units": "imperial", "cable_tag_pattern": "{D}-{n:03}", "currency": "USD", "public_url": "", "autosave": true},
  "venues": [{"id": "hillside", "name": "Hillside Church"}],
  "rooms": [{"id": "main", "venue": "hillside", "name": "Main Auditorium", "code": "MAIN", "kind": "auditorium", "flow": {"columns": [{"id": "sources", "label": "Sources", "side": "left"}, {"id": "stage_io", "label": "Stage I/O", "side": "left"}, {"id": "mix", "label": "Mix & video", "side": "right"}, {"id": "outputs", "label": "Speakers · screens · stream", "side": "right"}], "groups": [{"id": "A", "label": "Stage", "side": "left"}, {"id": "E", "label": "Mix & video", "side": "right"}, {"id": "G", "label": "Outputs", "side": "right"}], "spine": {"label": "Network", "show": false}}}],
  "systems": [{"id": "main-audio", "room": "main", "discipline": "audio", "name": "Main audio"}, {"id": "main-video", "room": "main", "discipline": "video", "name": "Main video"}],
  "locations": [{"id": "foh", "name": "FOH booth", "venue": "hillside", "room": "main", "kind": "booth"}, {"id": "stage-left", "name": "Stage left", "venue": "hillside", "room": "main", "kind": "stage"}],
  "racks": [{"id": "rk-foh", "name": "FOH rack", "room": "main", "location": "foh", "units": 12, "numbering": "bottom_up", "faces": ["front", "rear"]}],
  "networks": [{"id": "av-lan", "name": "AV LAN", "vlan": 20, "subnet": "10.20.0.0/24", "gateway": "10.20.0.1", "protocol": "control"}],
  "devices": [
    {"id": "wireless-mics", "name": "Wireless Mics", "kind": "mic", "room": "main", "system": "main-audio", "manufacturer": "Shure", "model": "ULXD2/SM58", "count": 2, "status": "installed",
     "flow": {"group": "A", "column": "sources"}, "patch": {"x": 40, "y": 40},
     "ports": [
       {"id": "rf-out-1", "name": "Output 1", "dir": "out", "medium": "rf", "group": "RF Out", "label": "Wireless 1"},
       {"id": "rf-out-2", "name": "Output 2", "dir": "out", "medium": "rf", "group": "RF Out", "label": "Wireless 2"}]},
    {"id": "shure-wireless", "name": "Shure Wireless", "kind": "wireless_rx", "room": "main", "system": "main-audio", "manufacturer": "Shure", "model": "ULX-D ULXD4D", "template": "shure-ulxd4d", "status": "installed",
     "flow": {"group": "A", "column": "stage_io"}, "patch": {"x": 40, "y": 220},
     "rack": {"id": "rk-foh", "u": 10, "height": 1, "face": "front", "side": "left"},
     "interfaces": [{"id": "primary", "role": "control", "ip": "10.20.0.31", "vlan": 20, "network": "av-lan", "protocol": "control"}],
     "ports": [
       {"id": "rf-in-1", "name": "Input 1", "dir": "in", "medium": "rf", "group": "RF In", "label": "Wireless 1"},
       {"id": "rf-in-2", "name": "Input 2", "dir": "in", "medium": "rf", "group": "RF In", "label": "Wireless 2"},
       {"id": "analog-out-1", "name": "Output 1", "dir": "out", "medium": "analog", "connector": "XLR3M", "group": "Analog Out", "label": "Wireless 1"},
       {"id": "analog-out-2", "name": "Output 2", "dir": "out", "medium": "analog", "connector": "XLR3M", "group": "Analog Out", "label": "Wireless 2"}]},
    {"id": "stage-box-1", "name": "Stage Box 1", "kind": "stage_io", "room": "main", "system": "main-audio", "location": "stage-left", "manufacturer": "Whirlwind", "model": "Unwired Stage Box", "status": "installed",
     "routing": {"mode": "passthrough"},
     "flow": {"group": "A", "column": "stage_io"}, "patch": {"x": 40, "y": 420},
     "ports": [
       {"id": "analog-in-1", "name": "Input 1", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Analog In", "label": "Keyboard"},
       {"id": "analog-in-2", "name": "Input 2", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Analog In", "label": "Acoustic"},
       {"id": "analog-out-1", "name": "Output 1", "dir": "out", "medium": "analog", "connector": "XLR3M", "group": "Analog Out", "label": "SB1-Out 1"},
       {"id": "analog-out-2", "name": "Output 2", "dir": "out", "medium": "analog", "connector": "XLR3M", "group": "Analog Out", "label": "SB1-Out 2"},
       {"id": "return-in-1", "name": "Return 1", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "IEM Return", "label": "Monitor Out 1"},
       {"id": "hdmi-in-1", "name": "Input 1", "dir": "in", "medium": "hdmi", "connector": "HDMI-A", "group": "HDMI In", "label": "Video Display"},
       {"id": "hdmi-out-1", "name": "Output 1", "dir": "out", "medium": "hdmi", "connector": "HDMI-A", "group": "HDMI Out", "label": "SB-Video-1"}]},
    {"id": "sound-board", "name": "Sound Board", "kind": "console", "room": "main", "system": "main-audio", "location": "foh", "manufacturer": "Allen & Heath", "model": "SQ-5", "brand": "allen-heath", "template": "allen-heath-sq-5", "status": "installed",
     "flow": {"group": "E", "column": "mix"}, "patch": {"x": 360, "y": 40},
     "inventory": {"serial": "SQ5-004211", "asset_tag": "HC-0012", "firmware": "1.6.2", "purchase_date": "2023-04-02", "vendor": "Sweetwater", "cost": 4499.0},
     "interfaces": [{"id": "primary", "role": "control", "ip": "10.20.0.10", "vlan": 20, "network": "av-lan", "protocol": "control"}],
     "ports": [
       {"id": "slink", "name": "SLink", "dir": "io", "medium": "snake", "connector": "etherCON", "group": "Network Out", "label": "SLink", "channels": 128}]},
    {"id": "audio-rack-1", "name": "Audio Rack 1", "kind": "stage_io", "room": "main", "system": "main-audio", "location": "stage-left", "manufacturer": "Allen & Heath", "model": "AR84", "brand": "allen-heath", "template": "allen-heath-ar84", "status": "installed",
     "flow": {"group": "A", "column": "stage_io"}, "patch": {"x": 360, "y": 260},
     "ports": [
       {"id": "analog-in-1", "name": "Input 1", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Analog In", "label": "SB1-Out 1"},
       {"id": "analog-in-2", "name": "Input 2", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Analog In", "label": "SB1-Out 2"},
       {"id": "analog-in-3", "name": "Input 3", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Analog In", "label": "Wireless 1"},
       {"id": "analog-in-4", "name": "Input 4", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Analog In", "label": "Wireless 2"},
       {"id": "analog-in-5", "name": "Input 5", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Analog In"},
       {"id": "analog-in-6", "name": "Input 6", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Analog In"},
       {"id": "analog-in-7", "name": "Input 7", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Analog In"},
       {"id": "analog-in-8", "name": "Input 8", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Analog In"},
       {"id": "analog-out-1", "name": "Output 1", "dir": "out", "medium": "analog", "connector": "XLR3M", "group": "Analog Out", "label": "Monitor Out 1"},
       {"id": "analog-out-2", "name": "Output 2", "dir": "out", "medium": "analog", "connector": "XLR3M", "group": "Analog Out", "label": "Mains"},
       {"id": "analog-out-3", "name": "Output 3", "dir": "out", "medium": "analog", "connector": "XLR3M", "group": "Analog Out", "label": "Sub"},
       {"id": "analog-out-4", "name": "Output 4", "dir": "out", "medium": "analog", "connector": "XLR3M", "group": "Analog Out", "label": "Stream"},
       {"id": "dsnake", "name": "dSnake", "dir": "io", "medium": "snake", "connector": "etherCON", "group": "Network In", "label": "dSnake", "channels": 12}]},
    {"id": "atem-mini", "name": "ATEM Mini", "kind": "video_switcher", "room": "main", "system": "main-video", "location": "foh", "manufacturer": "Blackmagic Design", "model": "ATEM Mini Pro", "brand": "blackmagic", "template": "blackmagic-atem-mini-pro", "status": "installed",
     "flow": {"group": "E", "column": "mix"}, "patch": {"x": 700, "y": 300},
     "interfaces": [{"id": "primary", "role": "control", "ip": "10.20.0.40", "vlan": 20, "network": "av-lan", "protocol": "control"}],
     "ports": [
       {"id": "hdmi-in-1", "name": "Input 1", "dir": "in", "medium": "hdmi", "connector": "HDMI-A", "group": "HDMI In", "label": "SB-Video-1"},
       {"id": "hdmi-in-2", "name": "Input 2", "dir": "in", "medium": "hdmi", "connector": "HDMI-A", "group": "HDMI In", "label": "HDMI In 2"},
       {"id": "analog-in-1", "name": "Mic 1", "dir": "in", "medium": "analog", "connector": "TRS 3.5mm", "group": "Analog In", "label": "Stream"},
       {"id": "hdmi-out-1", "name": "Output 1", "dir": "out", "medium": "hdmi", "connector": "HDMI-A", "group": "HDMI Out", "label": "Program Out"},
       {"id": "usb-out-1", "name": "USB", "dir": "out", "medium": "usb", "connector": "USB-C", "group": "USB Out", "label": "USB Stream Out"}]},
    {"id": "main-speakers", "name": "Main Speakers - L/R", "kind": "speaker", "room": "main", "system": "main-audio", "manufacturer": "QSC", "model": "K12.2", "count": 2, "template": "qsc-k12-2", "status": "installed",
     "flow": {"group": "G", "column": "outputs"}, "patch": {"x": 1040, "y": 40},
     "ports": [
       {"id": "analog-in-1", "name": "Input 1", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Analog In", "label": "Main L"},
       {"id": "analog-in-2", "name": "Input 2", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Analog In", "label": "Main R"},
       {"id": "thru-1", "name": "Thru 1", "dir": "out", "medium": "analog", "connector": "XLR3M", "group": "Analog Out", "label": "Thru"},
       {"id": "thru-2", "name": "Thru 2", "dir": "out", "medium": "analog", "connector": "XLR3M", "group": "Analog Out", "label": "Thru"}]},
    {"id": "sub-x2", "name": "Sub x2", "kind": "speaker", "room": "main", "system": "main-audio", "manufacturer": "Electro-Voice", "model": "E118sw 18\" Passive Subwoofer", "count": 2, "status": "installed",
     "flow": {"group": "G", "column": "outputs"}, "patch": {"x": 1040, "y": 220},
     "ports": [
       {"id": "analog-in-1", "name": "Input 1", "dir": "in", "medium": "analog", "group": "Analog In", "label": "Sub 1"},
       {"id": "analog-in-2", "name": "Input 2", "dir": "in", "medium": "analog", "group": "Analog In", "label": "Sub 2"}]},
    {"id": "video-converter", "name": "Video Converter", "kind": "converter", "room": "main", "system": "main-video", "location": "foh", "manufacturer": "Decimator Design", "model": "MD-HX", "template": "decimator-md-hx", "status": "installed",
     "flow": {"group": "E", "column": "mix"}, "patch": {"x": 1040, "y": 400},
     "ports": [
       {"id": "hdmi-in-1", "name": "HDMI In", "dir": "in", "medium": "hdmi", "connector": "HDMI-A", "group": "HDMI In", "label": "Program In"},
       {"id": "sdi-in-1", "name": "SDI In", "dir": "in", "medium": "sdi", "connector": "BNC", "group": "SDI In", "label": "SDI Input 1"},
       {"id": "hdmi-out-1", "name": "HDMI Out", "dir": "out", "medium": "hdmi", "connector": "HDMI-A", "group": "HDMI Out", "label": "HDMI Thru"},
       {"id": "sdi-out-1", "name": "SDI Out A", "dir": "out", "medium": "sdi", "connector": "BNC", "group": "SDI Out", "label": "SDI Program Output"},
       {"id": "sdi-out-2", "name": "SDI Out B", "dir": "out", "medium": "sdi", "connector": "BNC", "group": "SDI Out"}]},
    {"id": "samsung-tv-1", "name": "Samsung TV - 1", "kind": "display", "room": "main", "system": "main-video", "manufacturer": "Samsung", "model": "65\" QBC Series 4K UHD Display", "status": "installed",
     "flow": {"group": "G", "column": "outputs"}, "patch": {"x": 1380, "y": 400},
     "ports": [
       {"id": "sdi-in-1", "name": "Input 1", "dir": "in", "medium": "sdi", "connector": "BNC", "group": "SDI In", "label": "TV 1"},
       {"id": "hdmi-in-1", "name": "HDMI 1", "dir": "in", "medium": "hdmi", "connector": "HDMI-A", "group": "HDMI In"}]},
    {"id": "restream", "name": "Restream", "kind": "stream", "room": "main", "system": "main-video", "sub": "Video Stream", "status": "installed",
     "flow": {"group": "G", "column": "outputs"}, "patch": {"x": 1040, "y": 600},
     "ports": [
       {"id": "usb-in-1", "name": "Input 1", "dir": "in", "medium": "usb", "group": "USB In", "label": "USB Stream In"},
       {"id": "net-out-1", "name": "Output 1", "dir": "out", "medium": "network", "group": "Network Out", "label": "YouTube"}]},
    {"id": "spare-ulxd4d", "name": "ULXD4D (spare)", "kind": "wireless_rx", "room": "", "manufacturer": "Shure", "model": "ULX-D ULXD4D", "template": "shure-ulxd4d", "status": "spare",
     "inventory": {"serial": "3HX0042", "cost": 1999.0}, "ports": []}
  ],
  "cables": [
    {"id": "c-0001", "from": {"device": "wireless-mics", "port": "rf-out-1"}, "to": {"device": "shure-wireless", "port": "rf-in-1"}, "medium": "rf"},
    {"id": "c-0002", "from": {"device": "wireless-mics", "port": "rf-out-2"}, "to": {"device": "shure-wireless", "port": "rf-in-2"}, "medium": "rf"},
    {"id": "c-0003", "tag": "A-001", "from": {"device": "shure-wireless", "port": "analog-out-1"}, "to": {"device": "audio-rack-1", "port": "analog-in-3"}, "medium": "analog", "type": "XLR3 M-F", "length_m": 3.0},
    {"id": "c-0004", "tag": "A-002", "from": {"device": "shure-wireless", "port": "analog-out-2"}, "to": {"device": "audio-rack-1", "port": "analog-in-4"}, "medium": "analog", "type": "XLR3 M-F", "length_m": 3.0},
    {"id": "c-0005", "tag": "A-003", "from": {"device": "stage-box-1", "port": "analog-out-1"}, "to": {"device": "audio-rack-1", "port": "analog-in-1"}, "medium": "analog", "type": "XLR3 M-F", "length_m": 1.5},
    {"id": "c-0006", "tag": "A-004", "from": {"device": "stage-box-1", "port": "analog-out-2"}, "to": {"device": "audio-rack-1", "port": "analog-in-2"}, "medium": "analog", "type": "XLR3 M-F", "length_m": 1.5},
    {"id": "c-0007", "from": {"device": "audio-rack-1", "port": "analog-out-1"}, "to": {"device": "stage-box-1", "port": "return-in-1"}, "medium": "analog"},
    {"id": "c-0008", "tag": "A-005", "from": {"device": "sound-board", "port": "slink"}, "to": {"device": "audio-rack-1", "port": "dsnake"}, "medium": "snake", "type": "Cat6 STP", "length_m": 45.0, "bidirectional": true},
    {"id": "c-0009", "from": {"device": "audio-rack-1", "port": "analog-out-2"}, "to": {"device": "main-speakers", "port": "analog-in-1"}, "medium": "analog"},
    {"id": "c-0010", "from": {"device": "audio-rack-1", "port": "analog-out-3"}, "to": {"device": "sub-x2", "port": "analog-in-1"}, "medium": "analog"},
    {"id": "c-0011", "from": {"device": "audio-rack-1", "port": "analog-out-4"}, "to": {"device": "atem-mini", "port": "analog-in-1"}, "medium": "analog", "type": "XLR3F to TRS 3.5mm", "length_m": 30.0},
    {"id": "c-0012", "from": {"device": "stage-box-1", "port": "hdmi-out-1"}, "to": {"device": "atem-mini", "port": "hdmi-in-1"}, "medium": "hdmi"},
    {"id": "c-0013", "from": {"device": "atem-mini", "port": "hdmi-out-1"}, "to": {"device": "video-converter", "port": "hdmi-in-1"}, "medium": "hdmi"},
    {"id": "c-0014", "from": {"device": "video-converter", "port": "sdi-out-1"}, "to": {"device": "samsung-tv-1", "port": "sdi-in-1"}, "medium": "sdi", "type": "RG6 12G", "length_m": 25.0},
    {"id": "c-0015", "from": {"device": "atem-mini", "port": "usb-out-1"}, "to": {"device": "restream", "port": "usb-in-1"}, "medium": "usb"}
  ],
  "bundles": [],
  "floorplans": [],
  "attachments": [],
  "templates": [],
  "imports": []
}
```

Expected facts (T1/T2 assert them): `validate_doc` → `[]` (no errors and no warnings); `validateLocal` → `[]`; `filterDevices(room="")` → `["spare-ulxd4d"]`; BOM grand total 6498.0 USD; untagged cables per FR-CAB-02; the assistant answer of §5.10.

---

## Appendix C — QR reference vectors

Generated with python-qrcode 8 (`QRCode(error_correction=ERROR_CORRECT_M, mask_pattern=2, border=0)`, data forced to **byte mode**). `qr.encode(text, ecl="M", mask=2)` MUST return exactly these matrices (`1` = dark), row by row, **without** quiet zone. With `mask=None` the encoder chooses the mask by penalty score; T1 then checks function patterns, format bits (BCH-valid for the chosen mask) and zero Reed–Solomon syndromes rather than exact bits.

**C.1** `"FATHOM"` → version 1 (21×21):

```text
111111100010001111111
100000100110001000001
101110101111001011101
101110101111101011101
101110101111101011101
100000101010101000001
111111101010101111111
000000001111100000000
101111100010101111100
101000011110100100100
111110110001010011110
011101000110000111101
010001100001010011110
000000001111111101100
111111100110101100110
100000101011111001101
101110101110100010110
101110101100100100000
101110101101010000100
100000100110000011100
111111101101010010110
```

**C.2** `"https://fathom.example/p/demo/d/rio3224"` (38 bytes) → version 3 (29×29):

```text
11111110011010100111001111111
10000010001111011100101000001
10111010110110000000101011101
10111010111111011100001011101
10111010111010100001101011101
10000010101001011010001000001
11111110101010101010101111111
00000000101000001010100000000
10111110010111000111001111100
00010100010110101111111110001
01111111000100111100001010000
11111000110110010000001001010
11010110100010000100100001100
00010100011001001011111110001
11010111010011110000101011100
00010101011101000010100110010
10000110110010111101010101100
11011101011100001011111110101
10110010011110011000101110100
10010101100010101000011010010
10110110011010000100111110111
00000000111101100110100011111
11111110000111110001101011100
10000010100101011001100010001
10111010101000110100111110100
10111010110000001110000001111
10111010101111111100111111110
10000010001111001001100001010
11111110111110100111000110100
```

**C.3** Version auto-selection (byte-mode capacity at level M: v1 14, v2 26, v3 42, v4 62, v5 84, v6 106, v7 122, v8 152, v9 180, v10 213 bytes): `encode("A" * 100, "M")` → version 6 (41×41); `encode("x" * 2332, "M")` → version 40; 2400 bytes at M raises `ValueError`.

**C.4** `to_svg(matrix, scale=4, border=4)` parses with `xml.etree.ElementTree`; `viewBox = "0 0 (n+8) (n+8)"` in module units with `width/height = (n+8)·4`; dark modules drawn as one `<path>` (preferred) or rects.

---

## Appendix D — Floor-plan fixtures

### D.1 Draw.io

Uncompressed model (one page; shown with line breaks for reading — the compressed payload below encodes the same XML **without** line breaks):

```xml
<mxGraphModel dx="800" dy="600" grid="1" gridSize="10"><root><mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="stage" value="Stage" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;" vertex="1" parent="1"><mxGeometry x="40" y="40" width="400" height="120" as="geometry"/></mxCell>
<mxCell id="foh" value="FOH &lt;b&gt;booth&lt;/b&gt;" style="ellipse;whiteSpace=wrap;html=1;" vertex="1" parent="1"><mxGeometry x="200" y="400" width="80" height="60" as="geometry"/></mxCell>
<mxCell id="snake" value="" style="endArrow=none;dashed=1;strokeColor=#3333ff;" edge="1" parent="1" source="stage" target="foh"><mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="240" y="300"/></Array></mxGeometry></mxCell>
</root></mxGraphModel>
```

Compressed file — W2 ships it as `fathom/samples/floorplans/fixture-compressed.drawio`; T1 copies it to `tests/fixtures/plans/compressed.drawio` (round-trip verified at spec time with `zlib.decompress(base64.b64decode(t), -15)` + `urllib.parse.unquote`):

```xml
<mxfile host="Fathom spec"><diagram id="p1" name="Main floor">rZTdcoMgEIWfxnvU1sltY5P2ptPO5AloXIUpigMkap++i+BPoml7EZ1xlrPsAT6QIE7L9kXRmr3JDEQQkawN4ucgijaE4NcKnROSQSgUz5wUTsKBf4MX+27xLohTJaVxUdmmIKz9UOq89jey3rimCirznwJtaAGu6EzFyU/lMKnadMKrSp6qDGwhCeJtw7iBQ02PNtsgCdSYKQW2QgxzLkQqhVR9bZw/2hd1bZT8glkm6R/M+FmAMtDeXE04MkL8IEswqsMuvuDBk+4umw3PDBskrzHgBRtMPSRCtROK0XlCh4Gnt04yl2zBcf/+GljvROBI208Mij7A7WWDir5jYoEch+C1hr9x3wFeRK7pLfFtVugld4CnK/q1PIZLHFX2pJRssFXJymLJqGb9kQzXzpZ98nzEA1kBv8PB0eRJHWHxcxiqCjAXO70EqUBQw8+XY6xh6UtxJbSbdaglr4yeOX9YYbY/V6c7JuQKsXOcgI9TW9sDbE7XjOs+XWfx7gc=</diagram></mxfile>
```

Expectations for `drawio_to_svg(text, page=0)`: one rectangle (stage: x 40, y 40, 400 × 120, fill `#f5f5f5`, stroke `#666666`); one ellipse (foh: center 240,430, rx 40, ry 30); one dashed polyline/path in stroke `#3333ff` whose points include the waypoint (240,300) between the stage and the foh shapes (endpoints may be clipped to shape outlines); texts "Stage" and "FOH booth" (HTML stripped); `width`/`height` cover the bounds 40…440 × 40…460 plus a margin; the uncompressed variant (`<diagram>` containing the `<mxGraphModel>` element) yields identical SVG; `layers` = `[]` (Draw.io layers P2).

### D.2 DXF (ASCII)

T1 saves this as `tests/fixtures/plans/fixture.dxf` (one group code or value per line, exactly as shown):

```text
0
SECTION
2
HEADER
9
$INSUNITS
70
6
9
$EXTMIN
10
0.0
20
0.0
9
$EXTMAX
10
20.0
20
15.0
0
ENDSEC
0
SECTION
2
TABLES
0
TABLE
2
LAYER
70
3
0
LAYER
2
WALLS
70
0
62
7
6
CONTINUOUS
0
LAYER
2
SEATS
70
0
62
3
6
CONTINUOUS
0
LAYER
2
HIDDEN
70
0
62
-1
6
CONTINUOUS
0
ENDTAB
0
ENDSEC
0
SECTION
2
BLOCKS
0
BLOCK
8
0
2
SEAT
70
0
10
0.0
20
0.0
0
CIRCLE
8
SEATS
10
0.0
20
0.0
40
0.25
0
ENDBLK
8
0
0
ENDSEC
0
SECTION
2
ENTITIES
0
LWPOLYLINE
8
WALLS
90
4
70
1
10
0.0
20
0.0
10
20.0
20
0.0
10
20.0
20
15.0
10
0.0
20
15.0
0
LINE
8
WALLS
10
2.0
20
12.0
11
18.0
21
12.0
0
LWPOLYLINE
8
WALLS
90
2
70
0
10
8.0
20
12.0
42
1.0
10
12.0
20
12.0
0
ARC
8
WALLS
10
10.0
20
3.0
40
2.0
50
0.0
51
180.0
0
TEXT
8
WALLS
10
9.0
20
13.0
40
0.6
1
STAGE
0
MTEXT
8
WALLS
10
9.5
20
2.0
40
0.4
1
FOH\PBooth
0
INSERT
8
SEATS
2
SEAT
10
5.0
20
5.0
0
INSERT
8
SEATS
2
SEAT
10
6.0
20
5.0
41
1.0
42
1.0
50
0.0
0
CIRCLE
8
HIDDEN
10
1.0
20
1.0
40
0.5
0
ENDSEC
0
EOF
```

Expectations for `dxf_to_svg(text)` (T1 `test_dxf_fixture`):

- Scale: bounds of rendered geometry on visible layers (here 0…20 × 0…15, from the closed polyline) → `k = 2000 / max(w, h)` = 100 px per unit; margin 40 px on every side → `width="2080" height="1580" viewBox="0 0 2080 1580"`.
- y is flipped: a drawing point (x, y) maps to `(40 + (x − minx)·k, 40 + (maxy − y)·k)`; text is upright (not mirrored).
- `<g data-layer="WALLS">` contains 1 closed polygon/path with 4 vertices, 1 line, 1 path containing an SVG arc command `A` with radius 200 (the bulge 1.0 segment from (8,12) to (12,12)), 1 arc path (ARC center (10,3) r 2 from 0° to 180°), a `<text>` "STAGE", and MTEXT rendered as two lines "FOH" and "Booth".
- `<g data-layer="SEATS">` contains exactly 2 `<circle>` with `r="25"` centred at the mapped points of (5,5) and (6,5), i.e. (540, 1040) and (640, 1040).
- Nothing from layer HIDDEN (off: color < 0); `layers` = `[{"name": "WALLS", "visible": true, …}, {"name": "SEATS", "visible": true, …}, {"name": "HIDDEN", "visible": false, …}]` in LAYER-table order; `units == {"insunits": 6, "meters_per_unit": 1.0}`.
- Default stroke `#c8cfdd` on transparent background unless `use_dxf_colors=True` (then ACI 7 → `#ffffff`, ACI 3 → `#00ff00`).
- `dxf_to_svg(text, hide_layers=["WALLS"])` has no WALLS group and its bounds come from the SEATS circles.

---

## Appendix E — Starter equipment library (55 templates)

Notation per port group: `count × Group [medium dir connector chN]`; `names a/b/c` = one port per name; `start S` = numbering offset (§4.4.3). Column **Src**: ✓ = port counts verified against the cited datasheet at spec time (§10); `check` = from general knowledge — W2 ships it with `"notes": "Port counts not verified against the datasheet; please check."` and a `source_url` to the product page if known. All templates: `cost: null`. Group names in **bold** are relied on by importers/tests and MUST be exact.

| # | id | Manufacturer · Model | kind | RU / width | Ports | Src |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `yamaha-cl5` | Yamaha · CL5 | console | — | 8 × Omni In [analog in XLR3F] · 8 × Omni Out [analog out XLR3M] · 1 × AES Out [aes3 out XLR3M ch2] · Dante names Primary/Secondary [dante io etherCON ch64] · 3 × MY Slot [other io ch16] · Word Clock names In/Out [sync] | check |
| 2 | `yamaha-ql5` | Yamaha · QL5 | console | — | 32 × Analog In [analog in XLR3F] · 16 × Omni Out [analog out XLR3M] · 1 × AES Out [aes3 out ch2] · Dante names Primary/Secondary [dante io ch64] · 2 × MY Slot [other io] | check |
| 3 | `yamaha-dm7` | Yamaha · DM7 | console | — | 32 × Analog In [analog in XLR3F] · 16 × Omni Out [analog out XLR3M] · 2 × AES In [aes3 in ch2] · 2 × AES Out [aes3 out ch2] · Dante names Primary/Secondary [dante io ch144] · 1 × PY Slot [other io] · Word Clock names In/Out [sync] · 5 × GPI In [gpio in] · 5 × GPI Out [gpio out] · TC In [timecode in] | ✓ |
| 4 | `yamaha-dm7-compact` | Yamaha · DM7 Compact | console | — | 16 × Analog In · 16 × Omni Out · 1 × AES Out [aes3 out ch2] · Dante names Primary/Secondary [dante io ch144] · PY Slot | ✓ |
| 5 | `yamaha-tf-rack` | Yamaha · TF-Rack | console | 3U | 16 × Analog In [analog in XLR/TRS combo] · ST In names L/R [analog in RCA] · 8 × Omni Out [analog out XLR3M] · 8 × Omni Out start 9 [analog out TRS 1/4"] · NY64-D names Primary/Secondary [dante io ch64] · USB [usb io USB-B] | ✓ |
| 6 | `yamaha-rio3224-d2` | Yamaha · Rio3224-D2 | stage_io | 5U | 32 × **Analog In** [analog in XLR3F] · 16 × Analog Out [analog out XLR3M] · AES Out names 1/2, 3/4, 5/6, 7/8 [aes3 out XLR3M ch2] · Dante names Primary/Secondary [dante io etherCON ch32]; `dante_channels {tx 32, rx 24}` | ✓ |
| 7 | `yamaha-rio1608-d2` | Yamaha · Rio1608-D2 | stage_io | 3U | 16 × Analog In · 8 × Analog Out · Dante names Primary/Secondary [dante io ch16]; `dante_channels {tx 16, rx 8}` | ✓ |
| 8 | `shure-ulxd4q` | Shure · ULXD4Q | wireless_rx | 1U | Antenna names A/B [rf in BNC] · 4 × Analog Out [analog out XLR3M] · Mix Out [analog out TRS 1/4"] · Dante names Primary/Secondary [dante io ch4] · Network [network io RJ45] | check |
| 9 | `shure-ulxd4d` | Shure · ULXD4D | wireless_rx | 1U half | Antenna names A/B [rf in BNC] · 2 × Analog Out [analog out XLR3M] · Mix Out [analog out TRS 1/4"] · Dante names Primary/Secondary [dante io ch2] · Network [network io] | check |
| 10 | `shure-ad4q` | Shure · Axient Digital AD4Q | wireless_rx | 1U | Antenna names A/B [rf in BNC] · 4 × Analog Out [analog out XLR3M] · 2 × AES3 Out [aes3 out ch2] · Dante names Primary/Secondary [dante io ch4] · Network [network io] | check |
| 11 | `shure-p10t` | Shure · PSM1000 P10T | iem | 1U | Audio In names Ch1 L/Ch1 R/Ch2 L/Ch2 R [analog in XLR/TRS combo] · Loop Out names Ch1 L/Ch1 R/Ch2 L/Ch2 R [analog out TRS 1/4"] · RF Out names Ch1/Ch2 [iem_wireless out BNC] · Network [network io] | check |
| 12 | `shure-ulxd2-sm58` | Shure · ULXD2/SM58 | mic | — | RF Out [rf out] | ✓ |
| 13 | `shure-sm58` | Shure · SM58 | mic | — | Mic Out [analog out XLR3M] | ✓ |
| 14 | `focusrite-rednet-am2` | Focusrite · RedNet AM2 | iem | — | Dante [dante io RJ45 ch2] · Headphones names 1/4"/3.5mm [iem_wired out] | check |
| 15 | `focusrite-rednet-mp8r` | Focusrite · RedNet MP8R | stage_io | 1U | 8 × Mic In [analog in XLR3F] · Dante names Primary/Secondary [dante io ch8] | check |
| 16 | `focusrite-rednet-a16r-mkii` | Focusrite · RedNet A16R MkII | stage_io | 1U | 16 × Analog In [analog in DB25] · 16 × Analog Out [analog out DB25] · Dante names Primary/Secondary [dante io ch16] | check |
| 17 | `allen-heath-sq-5` | Allen & Heath · SQ-5 | console | — | 16 × Mic In [analog in XLR3F] · Talkback In [analog in XLR3F] · ST In names ST1 L/ST1 R/ST2 L/ST2 R [analog in TRS 1/4"] · 12 × XLR Out [analog out XLR3M] · Out names A/B [analog out TRS 1/4"] · AES Out [aes3 out ch2] · **SLink** [snake io etherCON ch128] · I/O Port [other io] · USB [usb io] | ✓ |
| 18 | `allen-heath-ar84` | Allen & Heath · AR84 | stage_io | — | 8 × Analog In [analog in XLR3F] · 4 × Analog Out [analog out XLR3M] · dSnake [snake io etherCON ch12] | ✓ |
| 19 | `allen-heath-dlive-dm32` | Allen & Heath · dLive DM32 MixRack | console | — | 32 × Mic In [analog in XLR3F] · 16 × Line Out [analog out XLR3M] · gigaACE [snake io etherCON ch128] · 3 × I/O Port [other io] | check |
| 20 | `behringer-x32` | Behringer · X32 | console | — | 32 × Mic In [analog in XLR3F] · 16 × XLR Out [analog out XLR3M] · 6 × Aux In [analog in TRS 1/4"] · 6 × Aux Out [analog out TRS 1/4"] · AES50 names A/B [aes50 io etherCON ch48] · AES Out [aes3 out ch2] · Card Slot [other io] · Talkback In [analog in XLR3F] | check |
| 21 | `behringer-wing` | Behringer · Wing | console | — | 8 × Mic In [analog in XLR3F] · 8 × XLR Out [analog out XLR3M] · AES50 names A/B/C [aes50 io ch48] · StageConnect [other io] · Card Slot [other io] | check |
| 22 | `behringer-s32` | Behringer · S32 | stage_io | 3U | 32 × Mic In · 16 × XLR Out · AES50 names A/B [aes50 io ch48] | check |
| 23 | `midas-m32` | Midas · M32 | console | — | 32 × Mic In · 16 × XLR Out · 6 × Aux In · 6 × Aux Out · AES50 names A/B [aes50 io ch48] · AES Out [aes3 out ch2] · Card Slot | check |
| 24 | `digico-sd12` | DiGiCo · SD12 | console | — | 8 × Mic In [analog in XLR3F] · 8 × Line Out [analog out XLR3M] · 2 × AES In [aes3 in ch2] · 2 × AES Out [aes3 out ch2] · MADI names A/B [madi io BNC ch64] | check |
| 25 | `l-acoustics-la12x` | L-Acoustics · LA12X | amp | 2U | 4 × Analog In [analog in XLR3F] · 4 × Link Out [analog out XLR3M] · AES In names 1/2, 3/4 [aes3 in ch2] · AVB [avb io etherCON] · 4 × Speaker Out [speaker out NL4] | check |
| 26 | `l-acoustics-la7-16i` | L-Acoustics · LA7.16i | amp | 1U | Network names Primary/Secondary [avb io etherCON ch16] · AES/Analog Aux In [aes3 in terminal ch2] · Speaker Out names 1/2, 3/4, 5/6, 7/8, 9/10, 11/12, 13/14, 15/16 [speaker out terminal ch2] · 3 × GPIO [gpio io terminal] | ✓ |
| 27 | `powersoft-x8` | Powersoft · X8 | amp | 2U | 8 × Analog In [analog in XLR3F] · Dante names Primary/Secondary [dante io ch8] · 8 × Speaker Out [speaker out NL4] | check |
| 28 | `qsc-core-110f` | QSC · Core 110f | processor | 1U | 8 × Mic/Line In [analog in Phoenix] · 8 × Line Out [analog out Phoenix] · 8 × Flex I/O [analog io Phoenix] · LAN names A/B [qlan io RJ45] · USB [usb io] · GPIO [gpio io] · RS-232 [rs232 io] | check |
| 29 | `qsc-k12-2` | QSC · K12.2 | speaker | — | 2 × Input [analog in XLR/TRS combo] · Thru [analog out XLR3M] · Power In [power in IEC C14] | check |
| 30 | `blackmagic-atem-mini-pro` | Blackmagic Design · ATEM Mini Pro | video_switcher | — | 4 × HDMI In [hdmi in HDMI-A] · 2 × Mic In [analog in TRS 3.5mm] · HDMI Out [hdmi out HDMI-A] · USB Webcam Out [usb out USB-C] · Ethernet [network io RJ45]; checks: `audio-on` (Appendix F.6) | ✓ |
| 31 | `blackmagic-atem-mini-pro-iso` | Blackmagic Design · ATEM Mini Pro ISO | video_switcher | — | same as #30 (+ USB-C disk recording) | ✓ |
| 32 | `blackmagic-atem-1me-constellation-hd` | Blackmagic Design · ATEM 1 M/E Constellation HD | video_switcher | 1U | 10 × SDI In [sdi in BNC] · 6 × SDI Out [sdi out BNC] · Multiview Out [sdi out BNC] · Audio In names 1/2 [analog in TRS 1/4"] · Talkback [intercom io XLR5F] · Reference In [sync in BNC] · Ethernet [network io] · USB Webcam Out [usb out USB-C] | ✓ |
| 33 | `blackmagic-videohub-20x20-12g` | Blackmagic Design · Videohub 20x20 12G | video_router | — | 20 × **SDI In** [sdi in BNC] (ids `sdi-in-1…20`) · 20 × **SDI Out** [sdi out BNC] (ids `sdi-out-1…20`) · Ethernet [network io] | check |
| 34 | `blackmagic-web-presenter-hd` | Blackmagic Design · Web Presenter HD | encoder | — | SDI In [sdi in BNC] · SDI Loop Out [sdi out BNC] · USB Webcam Out [usb out USB-C] · Ethernet [network out RJ45] | check |
| 35 | `ross-ultrix-fr1` | Ross Video · Ultrix-FR1 | video_router | 1U | 16 × SDI In [sdi in BNC] · 16 × SDI Out [sdi out BNC] · Ethernet [network io]; note: "frame is software/licence configurable — adjust port counts" | check |
| 36 | `decimator-md-hx` | Decimator Design · MD-HX | converter | — | HDMI In [hdmi in] · SDI In [sdi in BNC] · SDI Out names A/B [sdi out BNC] · HDMI Out [hdmi out] | ✓ |
| 37 | `panasonic-aw-ue150` | Panasonic · AW-UE150 | camera | — | SDI Out names 12G/3G [sdi out BNC] · HDMI Out [hdmi out] · Network [network io RJ45] · Genlock In [sync in BNC] · 2 × Audio In [analog in XLR3F] · RS-422 [rs422 io] | check |
| 38 | `sony-srg-x400` | Sony · SRG-X400 | camera | — | HDMI Out [hdmi out] · SDI Out [sdi out BNC] · Network [network io] · RS-232/422 [rs422 io] · Audio In [analog in TRS 3.5mm] | check |
| 39 | `epson-eb-pu2010` | Epson · EB-PU2010 | projector | — | 2 × HDMI In [hdmi in] · HDBaseT In [hdbaset in RJ45] · SDI In [sdi in BNC] · RS-232 [rs232 in DB9] · LAN [network io] | check |
| 40 | `panasonic-pt-req12` | Panasonic · PT-REQ12 | projector | — | HDMI In [hdmi in] · DIGITAL LINK In [hdbaset in RJ45] · SDI In [sdi in BNC] · RS-232 [rs232 in DB9] · LAN [network io] | check |
| 41 | `samsung-qb65c` | Samsung · QB65C (QBC series 65") | display | — | 2 × HDMI In [hdmi in] · RS-232 [rs232 in TRS 3.5mm] · LAN [network io] · USB [usb in USB-A] | check |
| 42 | `etc-ion-xe-20` | ETC · Ion Xe 20 | lighting_console | — | 4 × DMX Out [rdm out XLR5F] · 2 × Ethernet [sacn io RJ45] · Contact Closure [gpio in DB25] | ✓ |
| 43 | `etc-eos-apex-10` | ETC · Eos Apex 10 | lighting_console | — | 4 × Ethernet [sacn io etherCON] · 2 × SFP+ [network io SFP+] · 4 × I/O Garage [other io] | ✓ |
| 44 | `etc-colorsource-20` | ETC · ColorSource 20 | lighting_console | — | DMX Out [dmx out XLR5F] · Ethernet [sacn io RJ45] | check |
| 45 | `ma-grandma3-light` | MA Lighting · grandMA3 light | lighting_console | — | 4 × DMX Out [rdm out XLR5F] · 3 × Ethernet [network io etherCON] | check |
| 46 | `chauvet-maverick-storm-2-profile` | Chauvet Professional · Maverick Storm 2 Profile | fixture | — | DMX names In/Out [dmx XLR5; In = in, Out = out] · Ethernet names In/Out [sacn etherCON] · Power names In/Out [power powerCON TRUE1] | check |
| 47 | `martin-mac-aura-pxl` | Martin · MAC Aura PXL | fixture | — | DMX names In/Thru [dmx XLR5] · Power names In/Thru [power powerCON TRUE1] | check |
| 48 | `etc-source-four-lustr-x8` | ETC · Source Four LED Series 3 Lustr X8 | fixture | — | DMX names In/Thru [dmx XLR5] · Power names In/Thru [power powerCON TRUE1] | check |
| 49 | `etc-sensor3-48` | ETC · Sensor3 48-module rack | dimmer | — | DMX In names A/B [dmx in XLR5F] · Ethernet [sacn in RJ45] · 48 × Dimmer Out [power out terminal] | check |
| 50 | `etc-response-mk2-4port` | ETC · Response Mk2 Four-Port DMX Gateway | dmx_node | — | Ethernet [sacn in RJ45] · 4 × DMX Out [dmx out XLR5F] | check |
| 51 | `cisco-catalyst-9200-24p` | Cisco · Catalyst 9200-24P | switch | 1U | 24 × GbE PoE+ [network io RJ45] · 4 × SFP Uplink [network io SFP] · Console [rs232 io RJ45] | check |
| 52 | `netgear-m4250-26g4f-poe` | NETGEAR · M4250-26G4F-PoE+ | switch | 1U | 24 × GbE PoE+ [network io RJ45] · 2 × GbE start 25 [network io RJ45] · 4 × SFP [network io SFP] | check |
| 53 | `ubiquiti-usw-pro-24-poe` | Ubiquiti · USW-Pro-24-PoE | switch | 1U | 24 × GbE PoE [network io RJ45] · 2 × SFP+ [network io SFP+] | check |
| 54 | `extron-ipcp-pro-350` | Extron · IPCP Pro 350 | control | 1U | COM 1 RS-232/422/485 [rs422 io Phoenix] · 2 × COM start 2 RS-232 [rs232 io Phoenix] · 2 × IR/Serial [ir out Phoenix] · 4 × Relay [gpio out Phoenix] · 4 × Digital I/O [gpio io Phoenix] · eBUS [rs422 io Phoenix] · 3 × LAN [network io RJ45] | ✓ |
| 55 | `crestron-cp4n` | Crestron · CP4-N | control | 1U | 2 × COM [rs232 io DB9] · 8 × IR/Serial [ir out Phoenix] · 8 × Relay [gpio out Phoenix] · 8 × Versiport [gpio io Phoenix] · Cresnet [rs422 io Phoenix] · LAN [network io RJ45] · Control Subnet [network io RJ45] | check |

Plus two generic templates (not counted above, IDs reserved): `generic-dmx-splitter-6` (dmx_node: DMX In [dmx in], DMX Thru [dmx out], 6 × DMX Out [dmx out]) and `generic-pdu-8` (power, 1U: Power In [power in IEC C14], 8 × Outlet [power out IEC C13]).

Routing overrides: `speaker`-kind and `fixture`-kind templates use the kind default `passthrough`; templates #46–#48 rely on passthrough pairing (`DMX In`/`DMX Out|Thru` stems → `dmx`; `Power In`/`Power Out|Thru` → `power`), so their group names MUST be `DMX` with names `In`/`Out`|`Thru` expanded as ids `dmx-in`, `dmx-out`/`dmx-thru` and `dir` set per name (template groups may carry `"dirs": {"In": "in", "Out": "out"}` to give per-name directions; §4.4.3 applies `dirs[name]` when present, else `dir`). DMX footprints (`dmx_footprint`) are left `null` because they depend on the fixture mode.

---

## Appendix F — Checklist & lexicon formats (seed content, W6)

All files are UTF-8 JSON with `"version": 1`. Extension dirs (`FATHOM_CHECKLISTS`, plugin-registered) may contain files with the same names; their entries are **appended** (same `id` within the same key replaces).

### F.1 `fathom/checklists/symptoms.json`

```json
{
  "version": 1,
  "symptoms": {
    "no_audio":   {"discipline": "audio",    "phrases": ["no audio", "no sound", "silent", "can't hear", "cant hear", "cannot hear", "muted", "nothing coming through", "dead mic", "mic not working", "no signal"]},
    "noise":      {"discipline": "audio",    "phrases": ["hum", "buzz", "noise", "crackle", "static", "hiss", "distortion", "distorted"]},
    "feedback":   {"discipline": "audio",    "phrases": ["feedback", "ringing", "squeal", "howl"]},
    "dropout":    {"discipline": "audio",    "phrases": ["dropout", "drops out", "dropping out", "cutting out", "cuts out", "intermittent", "glitch"]},
    "latency":    {"discipline": "audio",    "phrases": ["latency", "lip sync", "out of sync", "delayed", "echo"]},
    "no_video":   {"discipline": "video",    "phrases": ["no video", "no picture", "black screen", "blank screen", "no image", "blue screen", "no input", "no signal on the screen"]},
    "flicker":    {"discipline": "video",    "phrases": ["flicker", "flickering", "flashing", "sparkles", "snow"]},
    "wrong_source": {"discipline": "video",  "phrases": ["wrong source", "wrong input", "wrong camera", "wrong picture"]},
    "lighting_no_response": {"discipline": "lighting", "phrases": ["not responding", "lights not working", "fixture not responding", "no dmx", "lights won't", "stuck on", "not changing"]},
    "no_network": {"discipline": "network",  "phrases": ["offline", "not on the network", "can't see", "cannot see", "not discovered", "no link", "no connection", "disconnected"]},
    "no_power":   {"discipline": "power",    "phrases": ["no power", "won't turn on", "wont turn on", "not powering", "tripped", "dead"]}
  },
  "discipline_words": {
    "audio": ["audio", "sound", "mic", "mics", "microphone", "speaker", "speakers", "mix", "vocal", "vocals"],
    "video": ["video", "picture", "screen", "image", "display", "camera"],
    "lighting": ["light", "lights", "lighting", "dmx", "fixture", "fixtures", "dimmer"],
    "network": ["network", "ip", "ethernet", "wifi"],
    "power": ["power", "breaker", "outlet"]
  },
  "positive": ["fine", "works", "working", "is ok", "is okay", "okay", "good", "great", "no problem", "no problems"],
  "stopwords": ["the", "a", "an", "is", "are", "was", "has", "have", "had", "but", "and", "on", "in", "of", "to", "from", "my", "our", "it", "its", "it's", "no", "not", "there", "this", "that", "we", "i", "for", "with", "at", "any", "all", "now"]
}
```

Matching: lowercase, longest phrase first across all symptoms; ties broken by the discipline whose `discipline_words` occur in the question.

### F.2 `fathom/checklists/synonyms.json`

```json
{
  "version": 1,
  "roles": [
    {"phrases": ["livestream", "live stream", "stream", "streaming", "restream", "youtube", "facebook live", "webcast", "online service"], "kinds": ["stream", "encoder"]},
    {"phrases": ["house sound", "house", "mains", "main speakers", "the pa", "pa", "front of house speakers", "room sound"], "kinds": ["speaker", "amp", "pa"]},
    {"phrases": ["subs", "subwoofers", "sub"], "kinds": ["speaker", "pa"], "name_contains": ["sub"]},
    {"phrases": ["monitors", "wedges", "in-ears", "in ears", "iems", "iem"], "kinds": ["iem"]},
    {"phrases": ["projector", "projectors"], "kinds": ["projector"]},
    {"phrases": ["screen", "screens", "tv", "tvs", "display", "displays", "confidence monitor"], "kinds": ["display", "projector"]},
    {"phrases": ["camera", "cameras", "ptz"], "kinds": ["camera"]},
    {"phrases": ["recording", "recorder", "multitrack"], "kinds": ["recorder", "computer"]},
    {"phrases": ["wireless", "wireless mics", "handhelds", "lavs", "lav"], "kinds": ["wireless_rx", "mic"]},
    {"phrases": ["console", "desk", "board", "mixer"], "kinds": ["console"]},
    {"phrases": ["lighting console", "light board", "lighting desk"], "kinds": ["lighting_console"]},
    {"phrases": ["lights", "fixtures", "movers", "moving lights"], "kinds": ["fixture", "dimmer"]},
    {"phrases": ["switcher", "vision mixer"], "kinds": ["video_switcher"]},
    {"phrases": ["network switch", "switch"], "kinds": ["switch", "network"]}
  ]
}
```

A role resolves to the devices of those kinds in the question's room (document order), filtered by `name_contains` (case-insensitive) when given. Exact device-name search hits (score 100) take precedence over role phrases for the same words (e.g. "Sound Board").

### F.3 `fathom/checklists/kinds.json` (seed; W6 adds at least 2 checks for every kind of Appendix A.1)

```json
{
  "version": 1,
  "kinds": {
    "stage_io": [
      {"id": "output-up", "symptoms": ["no_audio", "dropout"], "when": {"port_dir": "out"}, "text": "Confirm the **{port}** output is up on {device}{feeds}.", "note": "check output level"},
      {"id": "input-gain", "symptoms": ["no_audio", "noise"], "when": {"port_dir": "in"}, "text": "Check the head-amp gain, +48V and pad for **{port}** on {device}."},
      {"id": "link-lights", "symptoms": ["no_audio", "dropout", "no_network"], "when": {"medium": ["dante", "snake", "aes50", "avb", "network"]}, "text": "Check the link/sync lights on {device}'s **{port}** port."}
    ],
    "console": [
      {"id": "channel-routing", "symptoms": ["no_audio"], "when": {"port_dir": "out"}, "text": "On {device}, check that the bus feeding **{port}** is unmuted, its fader is up and the channels are assigned to it."},
      {"id": "input-patch", "symptoms": ["no_audio"], "when": {"port_dir": "in"}, "text": "On {device}, confirm **{port}** is patched to the channel you expect and the channel is unmuted."}
    ],
    "video_switcher": [
      {"id": "program-meter", "symptoms": ["no_audio"], "when": {"port_dir": "out", "medium": ["usb", "hdmi", "sdi", "network"]}, "text": "Check levels on the {device}'s Program meter before it reaches {next_device}."},
      {"id": "program-source", "symptoms": ["no_video", "wrong_source"], "when": {"port_dir": "out"}, "text": "Make sure the right source is on Program on {device} and **{port}** is set to Program, not Preview or Multiview."},
      {"id": "input-format", "symptoms": ["no_video", "flicker"], "when": {"port_dir": "in"}, "text": "Check that the source on **{port}** matches {device}'s video format (resolution and frame rate)."}
    ],
    "stream": [
      {"id": "stream-source", "symptoms": ["no_audio", "no_video"], "when": {"port_dir": "in"}, "text": "In the streaming software for {device}, confirm the input is **{port}** and its audio is not muted."}
    ],
    "speaker": [
      {"id": "amp-power", "symptoms": ["no_audio", "no_power"], "when": {}, "text": "Check that {device} (or its amplifier) is powered and its input level is up."}
    ],
    "fixture": [
      {"id": "dmx-address", "symptoms": ["lighting_no_response"], "when": {}, "text": "Check {device}'s DMX address and mode match the patch, and that the DMX signal LED is lit."}
    ]
  }
}
```

### F.4 `fathom/checklists/media.json` (seed)

For medium checks `{device}`/`{port}` = the cable's from end and `{next_device}`/`{next_port}` = its to end.

```json
{
  "version": 1,
  "media": {
    "analog": [{"id": "reseat", "symptoms": ["no_audio", "noise", "dropout"], "text": "Re-seat or swap the cable from {device} **{port}** to {next_device} **{next_port}**."}],
    "usb":    [{"id": "usb-device", "symptoms": ["no_audio", "no_video"], "text": "Check the USB cable from {device} to {next_device} and that the computer sees {device} as an audio/video input."}],
    "hdmi":   [{"id": "hdmi-handshake", "symptoms": ["no_video", "no_audio", "flicker"], "text": "Re-seat the HDMI cable from {device} to {next_device}; long HDMI runs often fail — try a shorter cable."}],
    "sdi":    [{"id": "sdi-format", "symptoms": ["no_video", "flicker"], "text": "Check the SDI cable from {device} to {next_device} and that both ends use the same SDI rate (HD / 3G / 12G)."}],
    "dante":  [{"id": "dante-subscription", "symptoms": ["no_audio", "dropout"], "text": "In Dante Controller, check {next_device}'s subscription to {device} is green (no clock or latency errors)."}],
    "snake":  [{"id": "snake-link", "symptoms": ["no_audio", "dropout"], "text": "Check the digital snake link between {device} and {next_device} (link lights, cable, connectors)."}],
    "rf":     [{"id": "rf-battery", "symptoms": ["no_audio", "dropout", "noise"], "text": "Check batteries, mute switch and RF signal on {device}; make sure it is on {next_device}'s frequency."}],
    "speaker": [{"id": "speaker-cable", "symptoms": ["no_audio", "noise"], "text": "Check the speaker cable from {device} **{port}** to {next_device}."}],
    "network": [{"id": "network-link", "symptoms": ["no_network", "no_audio", "no_video"], "text": "Check the network link between {device} and {next_device} (link light, switch port, VLAN)."}],
    "dmx":    [{"id": "dmx-chain", "symptoms": ["lighting_no_response", "flicker"], "text": "Check the DMX cable from {device} **{port}** to {next_device} and that the end of the chain is terminated."}],
    "sacn":   [{"id": "sacn-universe", "symptoms": ["lighting_no_response"], "text": "Check {next_device} listens to the same sACN universe {device} sends."}],
    "power":  [{"id": "power-feed", "symptoms": ["no_power"], "text": "Check the power feed from {device} to {next_device} (breaker, outlet, cable)."}]
  }
}
```

### F.5 `fathom/checklists/generic.json`

```json
{
  "version": 1,
  "checks": [
    {"id": "power", "symptoms": ["*"], "text": "Make sure every device on the path is powered and not in standby."},
    {"id": "recent-change", "symptoms": ["*"], "text": "Ask what changed since it last worked (a re-patch, a new scene or show file, a firmware update)."},
    {"id": "swap-test", "symptoms": ["no_audio", "no_video", "noise", "dropout"], "text": "Swap in a known-good cable or source to isolate the fault."}
  ]
}
```

### F.6 Template checks (in templates, W2)

`blackmagic-atem-mini-pro` and `-iso` carry (template excerpt):

```json
{"checks": [
  {"id": "audio-on", "symptoms": ["no_audio"], "when": {"port_dir": "in", "medium": ["analog", "hdmi"]},
   "text": "On the {device}'s Audio tab, make sure the **{port}** input is set to ON, not AFV (inputs default to audio-follow-video).",
   "note": "check Audio tab"}
]}
```

With Appendix B this yields exactly the three first checks of §5.10 in that order (pass 1: Audio Rack 1 `output-up`, ATEM `audio-on`, ATEM `program-meter`; then `stream-source` for Restream; pass 2: `analog/reseat`, `usb/usb-device`).

---

## Appendix G — Migration worked example (RRC Littleton excerpt)

v1 input (excerpt of `fathom/samples/rrc-littleton/project.json`; node index in brackets):

```json
{"nodes": [
  {"id": "drums", "label": "Drums", "count": 12, "suffix": "+ TB", "sub": "8 → Neve #1 · 4 + TB → #2", "kind": "source", "group": "A", "column": "sources"},
  {"id": "neve1", "label": "1073OPX #1", "sub": "8 of 8 · drums", "kind": "stage_io", "brand": "neve", "group": "A", "column": "stage_io", "dante": true, "dante_name": "1073OPX-1",
   "ports": [{"name": "Mic/line in", "direction": "in", "medium": "analog", "count": 8}, {"name": "Dante tx", "direction": "out", "medium": "dante", "count": 8}]},
  {"id": "rio3224", "label": "Rio3224", "kind": "stage_io", "brand": "yamaha", "group": "A", "column": "stage_io", "dante": true, "dante_name": "Rio3224",
   "ports": [{"name": "Mic/line in", "direction": "in", "medium": "analog", "count": 32}, {"name": "Line out", "direction": "out", "medium": "analog", "count": 16}, {"name": "AES/EBU out", "direction": "out", "medium": "aes3", "labels": ["1/2", "3/4", "5/6", "7/8"]}]},
  {"id": "rio3224-out", "ref": "rio3224", "label": "Rio3224", "sub": "stage box · AES + line outs", "kind": "stage_io", "brand": "yamaha", "group": "G", "column": "mix", "dante": true}
 ],
 "links": [
  {"from": "drums", "to": "neve1", "medium": "analog", "count": 8, "from_port": "kit mics 1-8", "to_port": "in 1-8", "signal": "kick in/out, snare top/bottom, hi-hat, toms"},
  {"from": "rio3224-out", "to": "la7-1", "medium": "aes3", "count": 2, "label": "AES · L/R", "from_port": "AES out 1/2", "to_port": "AES in A", "signal": "Main L/R"}
 ]}
```

Positions in the full file: `drums` node 0, `neve1` node 6, `rio3224` node 8, `rio3224-out` node 28; the drums→neve1 link is link 0 and rio3224-out→la7-1 is link 15 (cables c-0001…c-0049 are created by links 0–14 per §4.6.5).

v2 output (excerpt):

```json
{
  "devices": [
    {"id": "drums", "name": "Drums", "kind": "source", "room": "main", "system": "main-audio",
     "sub": "8 → Neve #1 · 4 + TB → #2", "count": 12, "suffix": "+ TB",
     "flow": {"group": "A", "column": "sources", "seq": 0},
     "ports": [
       {"id": "kit-mics-1", "name": "kit mics 1", "dir": "out", "medium": "analog", "group": "kit mics", "index": 1, "origin": "link"},
       "… kit-mics-2 … kit-mics-8 …",
       {"id": "oh-l-r-ride-perc-tb-1", "name": "OH L/R, ride, perc, TB 1", "dir": "out", "medium": "analog", "group": "OH L/R, ride, perc, TB", "index": 1, "origin": "link"},
       "… -2 … -5 (link 1: 5 opaque-side ports because the comma split gives 4 parts ≠ 5) …"
     ]},
    {"id": "neve1", "name": "1073OPX #1", "kind": "stage_io", "room": "main", "system": "main-audio",
     "sub": "8 of 8 · drums", "brand": "neve", "dante": true, "dante_name": "1073OPX-1",
     "flow": {"group": "A", "column": "stage_io", "seq": 6},
     "ports": [
       {"id": "mic-line-in-1", "name": "Mic/line in 1", "dir": "in", "medium": "analog", "group": "Mic/line in", "index": 1, "origin": "declared"},
       "… mic-line-in-2 … mic-line-in-8 …",
       {"id": "dante-tx", "name": "Dante tx", "dir": "out", "medium": "dante", "group": "Dante tx", "index": 1, "channels": 8, "origin": "declared"}
     ]},
    {"id": "rio3224", "name": "Rio3224", "kind": "stage_io", "room": "main", "system": "main-audio",
     "lines": ["stage box", "15 of 32 in used", "outputs: see G · PA & zones"], "brand": "yamaha", "dante": true, "dante_name": "Rio3224",
     "flow": {"group": "A", "column": "stage_io", "seq": 8},
     "ports": [
       "… mic-line-in-1 … mic-line-in-32, line-out-1 … line-out-16 …",
       {"id": "aes-ebu-out-1-2", "name": "AES/EBU out 1/2", "dir": "out", "medium": "aes3", "group": "AES/EBU out", "index": 1, "origin": "declared"},
       "… aes-ebu-out-3-4, aes-ebu-out-5-6, aes-ebu-out-7-8 …"
     ]}
  ],
  "rooms": [{"id": "main", "venue": "main", "name": "Main room", "code": "MAIN", "kind": "other",
             "flow": {"columns": ["…v1 columns…"], "groups": ["…v1 groups…"], "spine": {"label": "Dante network", "show": true}, "options": {"…v1 options…": true},
                      "extra_cards": [{"id": "rio3224-out", "device": "rio3224", "seq": 28, "name": "Rio3224", "sub": "stage box · AES + line outs",
                                       "kind": "stage_io", "brand": "yamaha", "group": "G", "column": "mix", "dante": true}]}}],
  "bundles": [
    {"id": "b-0001", "kind": "link", "medium": "analog", "count": 8, "from_text": "kit mics 1-8", "to_text": "in 1-8",
     "signal": "kick in/out, snare top/bottom, hi-hat, toms", "flow": {"seq": 0}}
  ],
  "cables": [
    {"id": "c-0001", "from": {"device": "drums", "port": "kit-mics-1"}, "to": {"device": "neve1", "port": "mic-line-in-1"}, "medium": "analog", "bundle": "b-0001", "flow": {"seq": 0}},
    "… c-0002 … c-0008 (kit-mics-n → mic-line-in-n) …",
    {"id": "c-0050", "from": {"device": "rio3224", "port": "aes-ebu-out-1-2"}, "to": {"device": "la7-1", "port": "aes-in-a"}, "medium": "aes3",
     "label": "AES · L/R", "count": 2, "from_text": "AES out 1/2", "to_text": "AES in A", "signal": "Main L/R",
     "flow": {"seq": 15, "from_card": "rio3224-out"}}
  ]
}
```

Notes: `AES out 1/2` resolves to the declared `aes-ebu-out-1-2` by the trailing-token rule; `la7-1` gets a generated port `aes-in-a` (`dir: in`, `medium: aes3`, `channels: 2`, `origin: link`). The flow adapter turns bundle `b-0001` back into the v1 link `drums → neve1` (count 8, texts and signal from the bundle) and cable `c-0050` into the link `rio3224-out → la7-1` (from `flow.from_card`), which is what makes FR-MIG-03 hold.

<!-- END OF SPEC -->
