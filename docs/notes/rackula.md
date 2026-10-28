# Rackula incorporation: worker notes (binding contract)

Plan and feature map live with the coordinator; this file is what workers build against. Sections: Preamble, Contract (A–G), Wave 1 units.


## Rackula worker preamble (pasted verbatim into every worker prompt, followed by the contract and the unit spec)

You are one of several parallel coding workers incorporating features from Rackula (https://github.com/RackulaLives/Rackula, MIT, commit 9c7af6dd28209a776aebdb92080bcf2916cd29e6) into Fathom (repo vader8480/fathom): an AVL (audio/video/lighting) documentation web app for a church AV team. Fathom is a stdlib-only Python WSGI server (`fathom/server.py`) plus a no-build ES2018 frontend in `fathom/static/`. Nobody can answer questions mid-task: decide per Fathom conventions, record the decision in your final message, and keep going.

## Ground rules
- You run on your own cloud VM, on your own branch created from `cursor/rackula`. Commit with clear messages as you go and **push your branch** (`git push -u origin <your-branch>`; retry on network errors with 4/8/16/32 s backoff). Do NOT open a pull request, do NOT merge, do NOT push to any other branch. The coordinator reviews and merges your branch into `cursor/rackula`.
- Read `AGENTS.md` first, then the `docs/SPEC.md` sections named in your unit. Do NOT edit `docs/SPEC.md`, `README.md` or `AGENTS.md` (a docs worker owns them later): put the spec text for what you built in your final message instead (short, SPEC style).
- FILE OWNERSHIP IS STRICT. Create or edit ONLY the files listed under "Owns" in your unit. If you believe you must touch another file, work around it inside your files and report it (file, what, why). Other units are building the other side of each interface in parallel; implement your side exactly as the contract says so the pieces meet. If you consume a JS export that another wave-1 unit is adding, import the module as a namespace (`import * as core from './rack-core.js'`) and feature-detect (`typeof core.itemBlocks === 'function'`) so your branch works before theirs merges; in Python, import inside a function and fall back gracefully (`getattr(module, 'name', None)`).
- Licensing: Rackula is MIT; its device data is NetBox devicetype-library (CC0) and most images are from vastoholic/draw-io (freely shareable). Do NOT copy Svelte/TypeScript source. Re-implement behaviour from scratch in Fathom's style. Only the CAT unit copies assets (catalog data + images) and it records attribution.
- Repo conventions: no runtime dependencies (stdlib only; Python 3.9 syntax: no `match`, no `X | Y` unions, no `list[str]` at runtime outside annotations with `from __future__ import annotations`). Frontend is no-build ES2018 for Safari 15: NO `?.`, NO `??`, NO class fields, NO optional catch binding, NO `Array.prototype.at`, NO top-level await (`tests/js/syntax.test.mjs` enforces it). `*-core.js` modules are pure (no `window`/`document`/`fetch`/`localStorage`/timers; importable in Node, tested with `node --test`). DOM modules use `h(tag, attrs, children)`, `esc`, `on(target, type, fn)` from `./dom.js`. No inline event-handler attributes (CSP). Breakpoints only: sm < 700, md 700–1099, lg ≥ 1100 (`layoutFor(width)`); 44 px targets under `(pointer: coarse)`. CSS: each module owns its own file with its own class prefix; reuse the CSS variables defined in `css/app.css` (do not invent colours except the documented category colours); every list uses `datatable.js` unless it is a picker/palette list (D9 exemptions in AGENTS.md).
- Server: routes are `@route(method, regex, role=...)` in `fathom/server.py`; every new route must be in `SPEC_ROLES` in `tests/test_security.py` (and `PARAM_HINTS` for any new path parameter name). Engine modules are imported lazily inside handlers. All document writes go through the ops pipeline (`POST /api/v2/projects/<n>/changes` ops: `put`/`merge`/`del` on collections) or `project.save_doc` under `project.project_lock`; writes are atomic. Schema changes are additive only: never rename, retype or remove fields; old documents must load unchanged.
- Data lives under `FATHOM_DATA`. Tests use throwaway data dirs (`tests/_helpers.py: temp_data_dir`); never point tests at `~/.fathom`.
- Phone first: any UI you add must work at 390 px wide and at 1440 px.

## Environment
- `.venv` exists (`.venv/bin/python`, `.venv/bin/fathom`), installed editable. If `tests/test_discovery.py` errors with `No module named 'puresnmp'`, run `.venv/bin/pip install -e '.[dev,serve,discovery]'`.
- A dev server may already run on http://localhost:8080 (tmux session `fathom-server`, login off, sample project `campus`); after Python changes restart it with `tmux kill-session -t fathom-server; bash .cursor/start.sh`. Or run your own: `FATHOM_DATA=/tmp/w-data .venv/bin/fathom serve --port 8090` in tmux.
- Headless Chrome: `/usr/bin/google-chrome-stable` (never `/usr/local/bin/google-chrome`). UI tests use `tests/_ui.py` (`UiCase`, `open(path, size)` with sizes `d`/`t`/`m`, `click`, `press`, `wait_for`, `intercept`, `shot`); read an existing `tests/test_ui_rk.py` for the pattern. Screenshots: save desktop (1440×900) and phone (390×844) shots of anything visible you built under `/opt/cursor/artifacts/<unit>/`.
- Rackula source when your unit needs it: `git clone https://github.com/RackulaLives/Rackula /tmp/rackula && git -C /tmp/rackula checkout 9c7af6dd28209a776aebdb92080bcf2916cd29e6`.

## Gates (run before finishing; all must be green)
- While working: your own suites, e.g. `FATHOM_CHROME=/usr/bin/google-chrome-stable .venv/bin/python -m unittest discover -s tests -p 'test_racks*.py' -v` and `node --test tests/js/*.test.mjs`.
- At the end, the full gate from the repo root:
  `FATHOM_CHROME=/usr/bin/google-chrome-stable .venv/bin/python -m unittest discover -s tests -q` (about 800 tests, ~15 min, mostly Chrome UI suites)
  `node --test tests/js/*.test.mjs` (about 567 tests)
  `.venv/bin/fathom selftest`
  Report counts. A failure you believe is pre-existing or caused by another unit's missing half must be named with the test id and reason.

## Final message (under 50 lines, no prose beyond this)
Branch name and head commit SHA; files created/edited; new routes (method + path + role) if any; public functions/exports added with signatures; test counts (python / node / selftest); screenshot paths; SPEC text for what you built (≤ 25 lines); every deviation from the contract and why; defects noticed in files you do not own (file, line, what); anything left undone.


## Rackula build contract (pasted verbatim into every worker prompt)

## A. Existing model (do not break)
- `racks[]`: `{id, name, room, location, units (1–60), numbering bottom_up|top_down, faces, depth_mm, order, notes}`.
- `devices[].rack = {id, u, height, face front|rear, side full|left|right, depth full|half}`. `u` = lowest occupied RU, 1 = bottom. `height` defaults to the template `ru`, else 1. Full depth blocks both faces; half depth blocks only its `face`. Half-width sides collide only with the same side or `full`.
- `rack-core.js` (JS) and `fathom/racks.py` (Python) implement placement, occupancy, collisions, `fits`, `placeOps`, geometry (`RU_PX = 22`, `RACK_W = 320`, `HALF_W = 160`), `ruLabel`, and the rack SVG. `rack.js` draws the elevation (`div.rk-block[data-device]`), `page-rack.js` draws the rack page `racks/<id>/<tab>[/front|rear]`.
- Library templates (`fathom/library/__init__.py`) carry `ru`, `width`, `depth_mm`, `power_w`, `weight_kg`, `kind`, `ports`, … Tier precedence: built-in < extension < global custom < project (`doc.templates`). Presets (`fathom/presets.py`) are templates with `source: "preset"`.

## B. Additive schema (all fields optional)
**`racks[]`:**
- `width_in`: 10|19|21|23, default 19.
- `form_factor`: `cabinet`|`open_frame`|`two_post`|`four_post`|`wall_mount`|`road_case`, default `cabinet`.
- `start_u`: int ≥ 0, default 1. It is the label of RU 1.
- `weight_kg`: num ≥ 0, the empty rack.
- `max_load_kg`: num ≥ 0.
- `power_limit_w`: num ≥ 0.
- `row`: str, the bay/row name.
- `items`: array of RackItem.

**RackItem** `{id, type, u, height, face, depth, label, color, slots, weight_kg, notes}`:
- `id`: str, required, unique within its rack. New ids are `ri-<n>` with the smallest unused n ≥ 1.
- `type`: required; one of `blank`, `vent`, `shelf`, `drawer`, `cable_manager`, `brush`, `lacing_bar`, `other`.
- `u`: int ≥ 1, required.
- `height`: int ≥ 1, default 1.
- `face`: front|rear, default from ITEM_TYPES.
- `depth`: full|half, default from ITEM_TYPES.
- `label`: str.
- `color`: `#rrggbb`.
- `slots`: int 1–4, shelves only, default 2.
- `weight_kg`: num.
- `notes`: str.

Items are always full width. They occupy RUs and collide with devices and other items using the same face/depth rules as devices.

**ITEM_TYPES** (same table in JS `rack-core.ITEM_TYPES` and Python `racks.ITEM_TYPES`, in this order):

| type | label | height | face | depth | color | slots |
|---|---|---|---|---|---|---|
| blank | Blank panel | 1 | front | half | #44475a | — |
| vent | Vent panel | 1 | front | half | #44475a | — |
| shelf | Shelf | 1 | front | full | #6272a4 | 2 |
| drawer | Drawer | 2 | front | full | #6272a4 | — |
| cable_manager | Cable manager | 1 | front | half | #6272a4 | — |
| brush | Brush panel | 1 | front | half | #6272a4 | — |
| lacing_bar | Lacing bar | 1 | rear | half | #6272a4 | — |
| other | Accessory | 1 | front | half | #6272a4 | — |

**`devices[].rack` additions:**
- `shelf`: the item id of a `type: shelf` item in the same rack.
- `slot`: int ≥ 0, the cell index, 0 = leftmost.
- `color`: `#rrggbb` override.
- `image_front`, `image_rear`: attachment ids of this device.

A device with `shelf` is drawn inside that shelf's cell, is NOT part of rack-level occupancy or collisions, and keeps `u` equal to the shelf's `u` (and `face` equal to the shelf's face) so older clients draw it at the right height.

**`devices[]` additions:** `weight_kg`, `power_w` (num ≥ 0). They override the template values.

**Template (library) additions:**
- `full_depth`: bool.
- `airflow`: str, NetBox values `front-to-rear`|`rear-to-front`|`left-to-right`|`right-to-left`|`side-to-rear`|`passive`|`mixed`.
- `rack_category`: str, Rackula category `server|network|firewall|patch-panel|power|storage|kvm|av-media|cooling|shelf|blank|cable-management|chassis|other`.
- `image_front`, `image_rear`: path relative to `/static/rack-images/`, e.g. `apc/apc-smt1500rmi2uc.front.webp`.
- `source`: `"catalog"` for the Rackula catalog tier.

**Category colours** (`CATEGORY_COLORS`, from Rackula): server #4A7A8A, network #7968A6, firewall #C0392B, storage #3D7A4A, power #A84A4A, kvm #926A40, av-media #A85A7A, cooling #75753F, chassis #5A6A8A, shelf #6272A4, blank #44475A, cable-management #6272A4, patch-panel #6272A4, other #6272A4.

## C. Semantics shared by Python and JS (the contract fixture `tests/fixtures/rack_contract.json` tests these)
- **Labels.** `ruLabel(rack, u)` / `racks.ru_label(rack, u)` returns a string. With `s = start_u` (default 1): bottom_up gives `u - 1 + s`; top_down gives `units - u + s`.
- **Width.** `rackWidthPx(rack)` = `Math.round(320 * width_in / 19)`: 10 → 168, 19 → 320, 21 → 354, 23 → 387.
- **Collisions.** `collisions(doc, rackId)` / `racks.collisions(doc, rack_id)` returns `[{a, b, u, face}]`, one per colliding pair and face.
  - Participants are rack-level devices (not shelf children) and items. Item ids are written `item:<id>`.
  - `u` is the lowest overlapping RU.
  - Each pair is ordered so `a < b` as strings. The list is sorted by `(u, face, a, b)`.
- **Fits.** `fits(doc, rackId, deviceId, u, opts)` also counts items, so conflicts may contain `item:<id>`.
  - `itemFits(doc, rackId, itemId, u, spec)` → `{ok, reason, conflicts}`. `itemId` is null for a new item; `spec` is `{type, height, face, depth}` with defaults from ITEM_TYPES and the existing item. `reason` is one of `''`, `rack_unknown`, `out_of_range`, `occupied`.
- **Shelf cells.** `shelfCells(doc, rackId, itemId)` / `racks.shelf_contents(doc, rack_id, item_id)` returns `[{slot, device}]` with length = `slots`. `device` is the first device (in `doc.devices` order) on that cell, or null. Devices whose slot is outside 0..slots−1 are left out.
- **Totals.** `rackTotals(doc, rackId, info)` / `racks.rack_totals(doc, rack_id)` returns `{units, used_u, free_u, weight_kg, max_load_kg, power_w, power_limit_w, devices, items}`.
  - `used_u` = number of RUs 1..units with any rack-level device or item on either face. `free_u = units - used_u`.
  - `weight_kg` = rack `weight_kg` + Σ device weight + Σ item `weight_kg`. Device weight is `device.weight_kg`, else the template `weight_kg`, else 0. It counts devices in the rack, including shelf children.
  - `power_w` = Σ device power. Device power is `device.power_w`, else the template `power_w`, else 0.
  - `max_load_kg` / `power_limit_w` = the rack value or null. `devices` = count of devices in the rack, including shelf children. `items` = count of items.
  - Numbers are rounded to 1 decimal.
  - JS template lookup: `info` is an optional map `{templateId: {weight_kg, power_w, ru, ...}}`, plus `doc.templates`. Python uses `library.get_template` (which includes the catalog tier). Fixtures use only device-level values or `doc.templates`.
- **Annotations.** `annotationValue(doc, device, field, info)` (JS `rack-display-core`) / `racks.annotation_value(doc, device, field)` returns a string, `''` when unknown.
  - `name` = device name.
  - `model` = `manufacturer + ' ' + model`, trimmed.
  - `ip` = the `ip` of the first `device.interfaces[]` entry with `role: "primary"` and a non-empty ip, else the first non-empty `ip`.
  - `serial` = `inventory.serial`. `asset_tag` = `inventory.asset_tag`. `code` = `device.code`.
  - `power` = `'<n> W'` when the device power is > 0. `weight` = `'<n> kg'` when the device weight is > 0 (no trailing `.0`).
  - `status` = `device.status`, or `installed` when unset.
- **Problems.** New Python warnings from `racks.validate_racks(doc)`, in the existing problem shape `{level, code, ref, path, message}`:
  - `rack_overlap` and `rack_out_of_range` now cover items too (ref `racks/<rack>`, path `racks/<rack>/items/<index>`).
  - `rack_shelf_unknown`: `shelf` is not a shelf item of that rack.
  - `rack_shelf_overlap`: two devices on one cell.
  - `rack_slot_out_of_range`.
  - `rack_overweight`: `weight_kg > max_load_kg`.
  - `rack_over_power`: `power_w > power_limit_w`.
  - Schema errors (`fathom/schema.py`): `bad_enum` for item `type`/`face`/`depth`, rack `width_in`/`form_factor`; `bad_type` for non-list `items`; `missing_field` for item `id`/`type`/`u`; `duplicate_id` for item ids repeated within a rack.

## D. Ops (JS `rack-core.js`; all pure, return op arrays the store commits)
- `addItemOps(doc, rackId, spec)` → `{ops, id}`. `spec` is `{type, u?, height?, face?, depth?, label?, color?, slots?}`. When `u` is missing, use the first fit from the top. Returns `{ops: [], id: ''}` when nothing fits.
- `moveItemOps(doc, rackId, itemId, u, opts)` → `ops`. `opts` = `{face?, force?}`. Refuses (`[]`) on a collision unless `force`.
- `updateItemOps(doc, rackId, itemId, patch)` and `delItemOps(doc, rackId, itemId)`. Deleting a shelf also unracks its children, turning them into plain devices with `rack: null`.
- Every item op is one `{op: 'merge', coll: 'racks', id: rackId, value: {items: [...whole array...]}}`, plus device merges where needed.
- `placeOnShelfOps(doc, deviceId, rackId, itemId, slot)` → `[{op: 'merge', coll: 'devices', id, value: {rack: {id, u: shelf.u, height: 1, face: shelf.face, side: 'full', shelf: itemId, slot}}}]`. Returns `[]` if the item is not a shelf, the slot is out of range, or the cell holds another device.
- `duplicateDeviceOps(doc, deviceId, opts)` → `{ops, id}`.
  - Copies the device with a new id (slug of the name, `-2`, `-3`, … as `model-core.slug` dedupes) and the name + ` (copy)`.
  - Drops `inventory.serial`, `inventory.asset_tag`, interface `ip`/`mac`/`hostname`, `merged_from` and `patch`.
  - Places it at the first fit in the same rack (`opts.rackId` overrides); unracked if nothing fits.
- `duplicateRackOps(doc, rackId, opts)` → `{ops, id}`. Copies the rack (name + ` (copy)`, new `rk-` id, same items). With `opts.devices`, it duplicates every device in the rack (via `duplicateDeviceOps`) into the new rack at the same positions.
- `racksByRow(racks)` → `[{row, racks}]`. Racks are sorted by `(order ?? 1e9, name)`. Racks sharing a non-empty `row` are grouped at the position of the first one. Racks with an empty row form singleton groups with `row: ''`.
- `rackWidthPx(rack)` is as in section C.

## E. Routes (SRV adds them; engines provide the functions)

| Method | Path | Role | Handler calls |
|---|---|---|---|
| GET | `/p/<n>/rk/<rack>` | viewer, page="viewer" | `render_rack.rack_page_html(doc, project, rack_id, base=<script root + "/">, share=<?share token if valid>, link_style="viewer")` |
| GET | `/api/v2/projects/<n>/racks/<rack>.svg` | viewer | Existing route, extended: `?face=front\|rear\|both&images=1&annotate=<field>` → `racks.rack_svg(doc, rack, face=..., images=bool, annotate=field or None, base_url="")` |
| GET | `/api/v2/projects/<n>/qr/rack/<rack>.svg` | viewer, page="file" | QR (existing `fathom/qr.py` encoder, as the device QR route `…/qr/<device>.svg` does) of the absolute URL of `/p/<n>/rk/<rack>`, with `?share=` carried like the SOP page QR |
| GET | `/api/v2/projects/<n>/racks/<rack>/totals` | viewer | `racks.rack_totals(doc, rack)`. 404 for an unknown rack |
| POST | `/api/v2/projects/<n>/racks/import` | editor | Body `{text?, zip_b64?, url?, apply?, base_revision?}`. Calls `parsers.rackula.preview(doc, payload)` → `{racks, devices, items, warnings, ops}`. With `apply: true`, the ops are applied through the same code path as `POST …/changes` (revision check, history entry summary "Import from Rackula") and the response is `{revision, applied: n, warnings}`. 422 when the parse fails |
| GET | `/api/v2/rack-templates` | viewer | `{"templates": rack_templates.list_templates()}` |
| POST | `/api/v2/projects/<n>/racks/from-template` | editor | Body `{template, name?, room?, location?, base_revision}`. Calls `rack_templates.apply_ops(doc, template, name=, room=, location=)` → `{ops, rack_id}`, applies them like `…/changes` and returns `{revision, rack: rack_id}`. 404 for an unknown template |
| POST | `/api/v2/library/import/netbox` | editor | Body `{text, override?}`. Calls `parsers.netbox_devicetype.to_template(text)`, validates with `library.validate_template`, saves as a global custom template (same 409 rule as `POST /api/v2/library`) and returns 201 with the template |
| GET | `/api/v2/library/<tid>/netbox.yaml` | viewer | `parsers.netbox_devicetype.from_template(get_template(tid, doc))`, served as `application/yaml` attachment `<tid>.yaml`. 404 when unknown |
| GET | `/api/v2/library` | viewer | Existing route, extended: `?source=catalog\|all&ids=a,b&rack=1` → `list_templates(q, discipline, kind, doc, source=, ids=, rack=)`. Summaries add `full_depth, airflow, rack_category, image_front, image_rear, weight_kg, power_w, width, depth_mm` when present |

Static: `.webp` must be served as `image/webp` (call `mimetypes.add_type("image/webp", ".webp")` at server import).

## F. Library tier (LIB)
- The catalog tier loads `fathom/library/rackula/catalog.json` (`{source, license, commit, generated, templates: [...]}`) once, with each template stamped `source: "catalog"`.
- **Default behaviour is unchanged.** `load_library()` and `list_templates()` exclude the catalog unless `source` is `"catalog"` (only the catalog) or `"all"` (every tier). `library.suggest` stays unchanged and does not see the catalog.
- `get_template(id, doc)` falls back to the catalog as the LOWEST precedence, so a device with `template: <catalog id>` resolves its `ru`, weight, power and images.
- `list_templates(q="", discipline="", kind="", doc=None, source=None, ids=None, rack=False)`: `ids` (list or comma string) returns exactly those templates from any tier, in the given order, with unknown ids skipped. `rack=True` keeps only templates with `ru ≥ 1`.
- `catalog_templates()` → list.
- `_TEMPLATE_KEYS` gains `full_depth`, `airflow`, `rack_category`, `image_front`, `image_rear`, `part_number`.

## G. JS modules (new, in `fathom/static/js/`)
- **`rack-display-core.js`** (pure): `DISPLAY_MODES = ['label','image','both']`, `ANNOTATION_FIELDS = [{key:'', label:'None'}, {key:'name',…}, 'model', 'ip', 'serial', 'asset_tag', 'code', 'power', 'weight', 'status']`, `CATEGORY_COLORS`.
  - `blockColor(device, vocab, info)`: `rack.color`, else `CATEGORY_COLORS[info.rack_category]`, else the discipline colour (`vocab.disciplines[disc].color`, with disc = `device.discipline` or `vocab.kinds[kind].discipline`), else `#9aa3b5`.
  - `deviceImage(device, info, face, opts)`: if `device.rack['image_' + face]` is set and `opts.attachmentUrl` exists, return `opts.attachmentUrl(attId)`; else if `info['image_' + face]`, return `(opts.base || '') + 'static/rack-images/' + path`; else `''`. Never show the front image on the rear.
  - `annotationValue(doc, device, field, info)` as in section C.
  - `airflowGlyph(airflow, face)` → `{glyph, title}` or null.
  - `STORAGE` keys: `fathom.ui.rack.display`, `fathom.ui.rack.annotate`, `fathom.ui.rack.face`.
- **`rack-display.js`**: `loadTemplateInfo(ctx, ids)` → Promise of `{id: summary}`. It uses `ctx.api.library({ids: ids.join(','), project: ctx.project})`, caches per id, and resolves `{}` without `ctx.api`.
- **`rack-palette-core.js`** (pure) and **`rack-palette.js`**: `mountRackPalette(el, ctx, {onPick(entry), onDragStart(entry, event)})` → `{destroy, focus, refresh}`.
  - Entries come from `ctx.api.library({source: 'all', rack: 1, project})` (catalog + built-in + custom + project + presets).
  - An entry is `{id, name, manufacturer, model, ru, kind, rack_category, image_front, source}`.
  - Storage key `fathom.ui.rack.palette` = `{v: 1, favs: [ids], recents: [ids ≤ 12]}`.
  - `deviceFromTemplate(doc, template, {room, name})` → `{ops: [put device], id}`. It mirrors `library.instantiate`: id from the name slug deduped, `kind`, `manufacturer`, `model`, `template: id`, `room`, `ports` expanded from port groups the same way `presets-core.presetPorts` does (reuse it).
- **`rack-export-core.js`** (pure) and **`rack-export.js`**: `openRackExport(ctx, {racks: [ids], face: 'front'|'rear'|'both'})` → Promise. A dialog to pick racks, face, format (SVG, PNG 2×, Print/PDF), legend on/off, annotation field. The core builds the SVG string: `buildRackSvg(doc, rackIds, opts)`, where `opts` = `{face, annotate, legend, images: {deviceId: dataUrl}, info, vocab, title}`.
- **`rack-elevation.js`**: holds `createElevation(el, ctx, opts)` (moved out of `rack.js` by SPLIT). Wave 2 adds `setOptions({face, display, annotate})` and `select(id)`.


## Wave 1 unit specs (each is pasted after the preamble and contract)

## CAT: Rackula catalog data, images, attribution
Owns: `tools/rackula_catalog.py`, `fathom/library/rackula/catalog.json`, `fathom/static/rack-images/**` (including `README.md`), `THIRD_PARTY_NOTICES.md`, `pyproject.toml`, `tests/test_rack_catalog.py`.

1. **Generator.** Write `tools/rackula_catalog.py` (stdlib only; header comment credits Rackula MIT, NetBox CC0, vastoholic). It reads a Rackula checkout (`--src /tmp/rackula`) and writes `fathom/library/rackula/catalog.json` and the images. Inputs:
   - `src/lib/data/brandPacks/*.ts` and `src/lib/data/starterLibrary.ts`: TypeScript object literals. Write a small tokenizer/regex reader for these literal shapes and resolve `CATEGORY_COLOURS[...]` references.
   - `src/lib/data/bundledImages.ts`: maps slug → image file.
   - Images under `src/lib/assets/device-images/`.
2. **Entry mapping** for each device type with integer `u_height ≥ 1`. Skip sub-U and fractional entries and report the count. Skip categories `blank`, `shelf` and `cable-management`, which become rack accessories in Fathom.
   - `id` = slug, sanitized to `^[a-z0-9][a-z0-9-]{1,79}$`. If it collides with a built-in template id (`fathom/library/templates/*.json`) or a preset id (`fathom/presets.py`), append `-rk`.
   - Copied fields: `manufacturer`, `model`, `name` (= model), `part_number`, `ru`, `full_depth` (default true), `airflow`, `weight_kg` (convert lb ×0.4536, round 0.1), `rack_category`, `tags: ["rackula"]`.
   - `kind` ∈ `fathom.vocab.KINDS`:
     - server, storage, kvm and chassis → `computer`.
     - network → `switch`, except router/gateway/controller models → `network`.
     - firewall → `network`. patch-panel → `patch_panel`. power → `power`. cooling and other → `other`.
     - av-media by model keywords: ATEM/switcher → `video_switcher`, Videohub/router → `video_router`, HyperDeck/recorder → `recorder`, amplifier/amp → `amp`, processor/DSP → `processor`, encoder/streaming → `encoder`, receiver → `wireless_rx`; otherwise `video`.
   - `ports`: Fathom port groups from Rackula `interfaces` where present. Map each interface type to a medium and connector (1000base-t → network RJ45, *sfp* → fiber SFP, xlr-3 → analog XLR, speakon → speaker NL4, hdmi → hdmi HDMI, sdi-bnc → sdi BNC, dante → dante RJ45, rs-232 → control DB9). Group consecutive same-type entries with `count`, using the port-group shape that `fathom/presets.py` and `fathom/library/templates/*.json` use. Otherwise `[]`.
   - Every entry must pass `fathom.library.validate_template`.
3. **Images.** Copy front/rear WebP only for these vendor folders: `_generic, apc, eaton, ac-infinity, ubiquiti, netgear, cisco, tp-link, mikrotik, synology, qnap, dell, apple, lenovo, supermicro`. Target `fathom/static/rack-images/<vendor>/<file>.webp`; set `image_front`/`image_rear` to the path relative to `fathom/static/rack-images/`. Total size ≤ 4.5 MB. Write `fathom/static/rack-images/README.md` with origin and licence.
4. **catalog.json** = `{"source": "...", "license": "MIT (Rackula) / CC0 (NetBox devicetype-library data)", "commit": "9c7af6dd…", "generated": "YYYY-MM-DD", "count": n, "templates": [...]}`. Sort by manufacturer then model, one template per line, for readable diffs. No `source` key on the entries (the LIB loader stamps `source: "catalog"`).
5. **`THIRD_PARTY_NOTICES.md`**: full Rackula MIT text and copyright; NetBox devicetype-library CC0 statement; vastoholic/draw-io note; Dracula palette (MIT) for the category colours.
6. **`pyproject.toml`**: add `library/rackula/*.json` to the `fathom.library` and `fathom` package-data (`static/**/*` already covers the images). Do not add dependencies.
7. **Tests** in `tests/test_rack_catalog.py`: ≥ 600 templates; unique ids matching the regex; no collision with built-in/preset ids; kinds in KINDS; every template validates; every image path exists; image total ≤ 4.5 MB; NOTICE mentions Rackula + MIT + NetBox + CC0; the generator is deterministic. The determinism test is skipped when `/tmp/rackula` is absent.

Return also: the counts per kind, the counts skipped, and the image MB.

## LIB: library catalog tier
Owns: `fathom/library/__init__.py`, `tests/test_library_catalog.py`.
Implement contract section F exactly:
- A catalog loader (cached; path constant `CATALOG_PATH = Path(__file__).parent / "rackula" / "catalog.json"`; a missing file gives an empty tier).
- `catalog_templates()`.
- `get_template` falls back to the catalog at the lowest precedence.
- `list_templates(..., source=None, ids=None, rack=False)`.
- The `_TEMPLATE_KEYS` additions, and `validate_template` accepting the new keys (`full_depth` bool, `airflow`/`rack_category`/`image_front`/`image_rear`/`part_number` str).

Default results of `load_library()`, `list_templates()` and `fathom/library/suggest.py` must not change (`tests/test_presets.py`, the library and suggest tests must pass untouched). Tests use a small fixture catalog via monkeypatching `CATALOG_PATH`, plus one test on the real file that is skipped when it is absent.

## SCH: schema additions
Owns: `fathom/schema.py`, `tests/test_rack_schema.py`.
Add contract section B to the JSON schema (the `racks` and `devices` objects near the `_obj({...})` definitions) and to the problem checks:
- `bad_enum` for rack `width_in`/`form_factor` and item `type`/`face`/`depth`.
- `bad_type` for non-list `items` and for non-numeric `weight_kg`/`power_w`/`max_load_kg`/`power_limit_w`.
- `missing_field` for item `id`/`type`/`u`.
- `duplicate_id` for repeated item ids within a rack.
- Device `rack.shelf` must be a string and `rack.slot` an int ≥ 0.

Make sure `normalize`/serialization keeps the new keys, the v1-compatibility check still treats racks as v2, and the `fathom selftest` schema checks pass. Tests: valid fixture docs give no new problems; each bad case gives its code; old sample projects (`fathom/samples`) validate with the same problem list as before.

## RPY: Python racks engine
Owns: `fathom/racks.py`, `tests/test_racks_items.py`.
Implement contract sections B and C in Python:
- `ITEM_TYPES` (an ordered list of dicts, matching the table), `ru_label(rack, u)`, `collisions(doc, rack_id)`, `rack_items(doc, rack_id)`, `shelf_contents(doc, rack_id, item_id)`, `rack_totals(doc, rack_id)`, `annotation_value(doc, device, field)`.
- `placement()` also returns `shelf`, `slot`, `color`.
- `rack_devices` includes shelf children, marked with `shelf`; occupancy and collisions exclude them.
- `rack_occupancy` and `validate_racks` include items and the new warnings.

`rack_svg(doc, rack_id, face="front", scale=1.0, *, images=False, annotate=None, base_url="")`:
- **Faces.** `face="both"` draws front and rear side by side with captions. Width follows `width_in`; RU labels honour `start_u`.
- **Items** are drawn as blocks, each type distinguishable: blank flat, vent slotted, shelf a tray with its cells and child devices drawn inside, drawer with a handle, cable manager with rings, lacing bar a thin bar.
- **Device colour** = `rack.color`, else the category colour of its template's `rack_category`, else the discipline colour.
- **Images.** With `images=True`, devices whose template has `image_<face>` get `<image>`. With `base_url` empty, that is a `data:image/webp;base64,` read from `fathom/static/rack-images/`, capped at 3 MB embedded per SVG, with blocks after the cap; otherwise an `href` of `base_url + "static/rack-images/" + path`.
- **Annotations.** `annotate=<field>` adds a right-hand column with `annotation_value` per device.
- **Title** line carries the totals (U used/free, kg, W).
- The SVG must stay well-formed XML (`xml.etree` parses it) and escape all text.

`rack_schedule` appends one row per item (`device` = label or type label, `model` = type label) and keeps the columns unchanged. All existing rack tests must pass; check `tests/test_exports.py` and every test grepping `rack_svg`/`rack_schedule`.

## RJS: JS rack core
Owns: `fathom/static/js/rack-core.js`, `tests/js/rack-core.test.mjs`, new `tests/js/rack-core-items.test.mjs`.
Implement contract sections B, C and D in JS:
- Constants and readers: `ITEM_TYPES`, `rackItems`, `itemBlocks(doc, rackId, face)` → `[{id: 'item:'+id, item: id, type, u, height, face, depth, label, color, slots, x: 0, y, w: rackWidthPx(rack), h, behind}]`.
- Shelves: `shelfCells`, `shelfChildBlocks(doc, rackId, face)` → `[{device, item, slot, x, y, w, h}]` (cell x = slot × w / slots).
- Fits: `itemFits`, and `fits`/`firstFit`/`occupancy`/`collisions` counting items.
- Ops: `addItemOps`, `moveItemOps`, `updateItemOps`, `delItemOps`, `placeOnShelfOps`, `duplicateDeviceOps`, `duplicateRackOps`.
- Helpers: `rackTotals`, `racksByRow`, `rackWidthPx`, and `ruLabel` with `start_u`.

Existing exports keep their signatures and behaviour for docs without the new fields. `faceBlocks` excludes shelf children; `placement()` adds `shelf`, `slot`, `color`. Keep it pure ES2018. Mirror the semantics of contract section C exactly; the contract tests (written by another unit) will run against your exports.

## CON: contract fixture and tests (test-only unit)
Owns: `tests/fixtures/rack_contract.json`, `tests/test_rack_contract.py`, `tests/js/rack-contract.test.mjs`.
Write ≥ 14 cases in one JSON fixture: `{"cases": [{"name", "doc", "rack", "expect": {...}}]}`. `expect` keys are optional per case:
- `labels {u: label}`, `width_px`, `collisions [...]`, `fits [{device|item, u, spec|opts, ok, reason, conflicts}]`, `shelf {item, cells: [{slot, device}]}`, `totals {...}`, `problems [codes]` (Python only), `annotations {deviceId: {field: value}}`, `rows [[rack ids per group]]` (JS only), `add_item {spec, id, u}` (JS only).

Cover:
- `start_u` 0 and top_down labels; 10" and 23" width.
- Device vs item collision (front); half-depth item vs rear device (no collision); full-depth shelf vs rear device (collision); half-width devices vs a full-width item.
- Items out of range; shelf cells with children; a slot out of range; two devices in one cell.
- Totals with device overrides, `doc.templates` values, item weights and rack weight; overweight and over-power problems; `fits`/`itemFits` reasons.
- Each annotation field; `racksByRow` order; `addItemOps` id allocation (smallest unused `ri-n`) and first fit from the top.

The Python test calls `fathom.racks` (`ru_label`, `collisions`, `shelf_contents`, `rack_totals`, `annotation_value`, `validate_racks`). The JS test imports `rack-core.js` (`ruLabel`, `rackWidthPx`, `collisions`, `fits`, `itemFits`, `shelfCells`, `rackTotals`, `racksByRow`, `addItemOps`) and `rack-display-core.js` (`annotationValue`).

These functions do not exist yet on your branch (other units are writing them). So before committing, verify every expectation by hand AND with a throwaway reference implementation you do not commit. In the committed tests, skip a case cleanly only when the function under test is missing (`unittest.skip` / `t.skip` with "awaiting <function>"), so the coordinator sees real failures once the engines merge. Report the case list.

## IMP: importers (mini YAML, Rackula layouts, NetBox device types)
Owns: `fathom/parsers/mini_yaml.py`, `fathom/parsers/rackula.py`, `fathom/parsers/netbox_devicetype.py`, `tests/test_import_rackula.py`, `tests/test_netbox_devicetype.py`, `tests/fixtures/rackula/**`.

**`mini_yaml.loads(text)`** handles:
- Block mappings and sequences (including `- key: v` items).
- Plain, single-quoted and double-quoted scalars; int/float/bool/null.
- `|` and `>` block scalars; flow `[...]`/`{...}` of scalars.
- Comments and `---`.
- It raises `ValueError("line N: …")` on anchors, aliases and tags.

**`mini_yaml.dumps(obj)`** writes simple block style.

**`rackula.preview(doc, payload)`** → `{racks, devices, items, warnings, ops}`. `payload` is one of `{text}` (YAML or JSON layout), `{zip_b64}` (a `.Rackula.zip`: read the layout YAML inside, ignore assets) or `{url}` (a count.racku.la share link, or the bare encoded string). Study `/tmp/rackula/src/lib/utils/share.ts`, `src/lib/schemas/share.ts`, `src/lib/utils/yaml.ts`, `serialization.ts`, `schemas/migrations.ts` and `docs/reference/SCHEMA.md` for the formats; decode share links with stdlib `zlib`/`base64`.

Mapping:
- **Racks.** Rackula rack → Fathom rack:
  - `id`: `rk-` + slug, deduped against the doc. `name`.
  - `units` = height, clamped to 60 with a warning. `numbering` = `top_down` if `desc_units`.
  - `start_u` = `starting_unit`. `width_in` = width.
  - `form_factor` map: 2-post → two_post, 4-post → four_post, 4-post-cabinet → cabinet, wall-mount → wall_mount, open-frame → open_frame.
  - `depth_mm`, `weight_kg` = `base_weight`, `notes`, `order` = position, `row` = the rack group name (or id) from `rack_groups`.
- **Accessories.** Placed devices whose device type category is blank, cable-management or shelf (or a carrier/container with `slots`) → RackItems `blank`/`cable_manager`/`shelf` (slots = cell count capped at 4). Their container children → devices with `rack.shelf` + `slot`.
- **Devices.** Other placed devices → Fathom devices:
  - `id` from the name slug, deduped. `name` = placement name, else model.
  - `kind` via `KIND_BY_CATEGORY` plus keyword rules: server, storage, kvm and chassis → computer; network → switch; firewall → network; patch-panel → patch_panel; power → power; av-media → video (with the keyword rules ATEM → video_switcher, amp → amp, processor → processor, encoder → encoder); else other.
  - `manufacturer`, `model`.
  - `template` = the slug when `fathom.library.get_template(slug)` finds it (feature-detect).
  - `rack {id, u, height, face, depth, side: 'full', color}`. Position is in internal 1/6-U units in current files (`u = position // 6`); handle the legacy human-unit format per the migrations. Face both → front + depth full; `is_full_depth: false` → depth half. `color` = `colour_override`.
  - `weight_kg`, `note` = notes.
- **Reuse.** An existing unracked doc device with the same normalized name is reused: merge the placement instead of creating, and mark it `new: false` in the preview.
- **Ops** = puts and merges that validate against `fathom/schema.py`. Collisions after import are listed as warnings, not refused.

**`netbox_devicetype.to_template(text)`**: NetBox device-type YAML (manufacturer, model, slug, part_number, u_height, is_full_depth, airflow, weight + weight_unit, interfaces, power-ports, power-outlets, console-ports, front-ports, rear-ports) → a Fathom template that passes `fathom.library.validate_template`.
- `kind` heuristic: power-outlets → power; front/rear ports → patch_panel; ≥ 8 interfaces → switch; else other.
- Ports become port groups with sensible media and connectors.

**`from_template(t)`** writes NetBox YAML that round-trips the subset.

Tests use hand-written fixtures and, if useful, small real files copied from Rackula's e2e/static fixtures with a `# Source: Rackula (MIT)` comment.

## SRV: server routes
Owns: `fathom/server.py`, `tests/test_security.py`, `tests/test_rack_routes.py`.
- Implement every route of contract section E, plus the `_template_summary` extension and `mimetypes.add_type("image/webp", ".webp")`.
- Put the new handlers in ONE clearly delimited block (`# ---- racks: Rackula features`) right after the existing rack SVG route, to keep merges with a concurrent branch (which edits other parts of server.py) easy. Extend the existing `r_rack_svg` and `r_library` in place, minimally.
- Reuse the existing helpers: the project loader, `_NAME`/`_EID` regexes, the share-token check used by the SOP page QR and viewer pages, the code path used by `POST /api/v2/projects/<n>/changes` to apply ops with `base_revision` (find it; do not duplicate the locking), `fathom.qr` as the device QR route uses it, and `ApiError`.
- Add every route to `SPEC_ROLES` (+ `PARAM_HINTS` for new path params such as `rack` if not already there) in `tests/test_security.py`.
- The engines (`racks.rack_totals`, `render_rack`, `rack_templates`, `parsers.rackula`, `parsers.netbox_devicetype`, library `source`/`ids`/`rack` kwargs) are being written by other units in parallel and do not exist on your branch. In `tests/test_rack_routes.py`, inject fakes (`unittest.mock.patch.dict(sys.modules, {...})` or patch attributes) and assert status codes, roles (viewer cannot POST), revision handling, 404/409/422 paths and content types.
- In handlers, a missing engine function raises `ApiError(501, "not available")`, never a 500.

## VWR: public rack viewer page
Owns: `fathom/render_rack.py`, `tests/test_rack_viewer.py`.
`rack_page_html(doc, project, rack_id, *, base, share="", link_style="viewer")` returns a complete HTML page in the style of the existing viewer device page. Find the function that renders `/p/<n>/d/<device>` in `fathom/render_html.py` and reuse its head/CSS helpers by importing them read-only. The page contains:
- A header: rack name, room, location, U, width, form factor.
- Totals: U used/free, weight vs max load, power vs circuit limit, with warning styling. Use `racks.rack_totals` when present; otherwise compute U from `rack_occupancy`.
- The front + rear elevation inline: `racks.rack_svg(doc, rack, face="both", images=True)` when the kwargs exist, else two calls. Scale to 100% width so it reads at 390 px.
- A device list ordered top-down: U, name, model, face. Links go to `{base}p/<project>/d/<id>` (plus `?share=`) in viewer mode, or `../d/<id>.html` in build mode; check how builds lay out device pages in `fathom/export.py` and match that.
- An accessories list, the rack notes (Markdown via `fathom.markdown` if the device page uses it), and a QR image. Viewer mode uses `<img src="{base}api/v2/projects/<p>/qr/rack/<rack>.svg[?share=…]">`; build mode inlines the QR SVG from `fathom.qr` for the page URL, or omits the QR if there is no absolute URL.
- A print stylesheet: one page, no chrome.

Escape every string. Unknown rack → raise `KeyError`. Tests parse the HTML, check links in both modes, check escaping (a rack named `<script>`) and check that a share token is carried.

## BLD: builds and report
Owns: `fathom/export.py`, `fathom/render_html.py`, `tests/test_rack_builds.py`.
- **Builds** keep `racks/<rack>-front.svg` and `-rear.svg` and add, per rack:
  - `racks/<rack>.svg`: both faces with images, via `rack_svg(..., face="both", images=True)` when supported (feature-detect with try/except `TypeError`).
  - `racks/<rack>.html`: `render_rack.rack_page_html(..., link_style="build")` when the module exists.
- **report.html** (`fathom/render_html.py`) gets a Racks section: one row per rack with U used/free and links to `racks/<rack>.html` and the SVG.
- **Device pages** (viewer and build) link their Rack line to the rack page: `/p/<n>/rk/<rack>` in viewer mode, `racks/<rack>.html` relative in build mode.
- Respect the existing optional-module pattern (`_optional`) and the build notes. All existing build/export tests pass. New tests build the `campus` sample with a rack carrying items and check the files and links.

## TPL: rack templates
Owns: `fathom/rack_templates.py`, `tests/test_rack_templates.py`.
- Template data lives as Python data inside `rack_templates.py` (no JSON files).
- `list_templates()` → `[{id, name, description, units, width_in, form_factor}]`.
- `apply_ops(doc, template_id, *, name="", room="", location="")` → `{ops, rack_id}`. It creates the rack (`rk-` slug deduped), placeholder devices with `status: "planned"`, and items.
  - Devices are made via `fathom.library.instantiate(get_template(id))` with ids deduped against the doc (use `fathom.model.slug`) and placed at fixed U/face.
  - Use only template ids that exist in `fathom/presets.py` or `fathom/library/templates/*.json`; a test asserts each exists.
- Five church-oriented templates:
  - `church-audio-12u`: cabinet; PDU/power conditioner, digital stagebox or I/O, wireless receivers, a shelf with 2 cells, blanks, a vent.
  - `road-case-8u`: road_case; PDU, wireless receivers, a drawer, a blank.
  - `video-stream-16u`: cabinet; video switcher, router, encoder, a computer on a shelf, UPS.
  - `network-closet-24u`: four_post; patch panels, 48-port switch, cable managers, router/firewall, UPS, PDU.
  - `desk-10in-6u`: 10"; small switch, PDU, a shelf.
- Tests: apply each template to an empty project doc and to the `campus` sample. Ops apply cleanly, the resulting doc validates with no rack collisions, and ids are unique.

## SPLIT: separate rack landing chrome from the elevation
Owns: `fathom/static/js/rack.js`, new `fathom/static/js/rack-elevation.js`.

Today `createElevation` in `rack.js` holds both the landing chrome (toolbar `#rk-select/#rk-add/#rk-edit/#rk-face/#rk-print`, rack form `#rk-f-*`, unracked explorer `#rk-unracked`) and the elevation (faces, blocks, ghost, drag, keyboard, fitWidth, print). It is used by the landing (`racks`) and, embedded, by `page-rack.js`. Split it with NO behaviour change:
- **`rack-elevation.js`** exports `createElevation(el, ctx, opts)`, now ONLY the elevation: viewport, faces, blocks, ghost, drag within/between racks, drop targets, keyboard on blocks, selection/highlight, fitWidth, print.
  - `opts` = `{rack?, racks?: function () → rack list, face?, onChange?, list?: {el, accept(e)}}`.
  - Returned API: `{render, destroy, setFace(face), getState, setState, focus(sel), route(r), startDrag(e, deviceId, fromList, grabEl), print(done), setOptions(o)}`. `setOptions` merges unknown keys into state and re-renders; wave 2 uses it for display/annotate.
  - Drops onto the unracked list (to unrack) keep working through `opts.list`.
- **`rack.js`** keeps `mount()` and builds the landing chrome itself (toolbar, form, explorer list), driving the elevation through that API. It still exports `createElevation`, re-exported for compatibility.
- `page-rack.js` gets `createElevation` through its opts as today; do not edit it.
- Every DOM id, class, aria label, keyboard behaviour and URL behaviour stays identical: `tests/test_ui_rk.py`, `tests/test_ui_acceptance.py`, `tests/test_ui_states_canvas.py` (if present) and every test touching racks must pass unchanged. The static dev harness for racks (`fathom/static/dev/*rack*` or `plan.html`) must still work.
- Report the final API precisely; two wave-2 workers will build on it.

## XPT: rack export dialog
Owns: `fathom/static/js/rack-export-core.js`, `fathom/static/js/rack-export.js`, `fathom/static/css/rack-export.css` (prefix `rx-`), `fathom/static/dev/rack-export.html`, `tests/js/rack-export-core.test.mjs`, `tests/test_ui_rack_export.py`.

**`rack-export-core.buildRackSvg(doc, rackIds, opts)`** (pure) returns a standalone SVG string. `opts` = `{face: front|rear|both, annotate, legend, images: {deviceId: dataUrl}, info, vocab, title}`.
- Racks laid out left to right (grouped by `racksByRow` when present), each with a title, U labels and blocks.
- Use `rack-core` geometry and, when present, `itemBlocks`/`shelfChildBlocks` and `rack-display-core.blockColor`/`annotationValue` (namespace import + feature-detect; fall back to discipline colours).
- A legend of the categories/disciplines used, and a footer with the project name and date.
- Well-formed and escaped.

**`rack-export.openRackExport(ctx, {racks, face})`** opens a dialog (reuse the dialog pattern in `feedback.js`/`wizard.js`). Choices: racks (checkboxes; default the given ones), face (front/rear/both), format (SVG download, PNG at 2× via `<canvas>` drawImage of the SVG blob, Print/PDF opening a print window with the SVG), legend toggle, annotation field.
- Images: for devices whose template info (`ctx.api.library({ids})`) has `image_<face>`, fetch `/static/rack-images/...` as a dataURL so the PNG is not tainted.
- Filenames: `<project>-<rack|racks>-<face>.<ext>`. At sm the dialog is full-screen.
- Provide a dev harness page. Tests: core unit tests (XML parse via a minimal well-formedness check, escaping, faces, legend); UI test with the harness or app at d and m sizes (dialog opens, SVG download produced via an intercepted anchor/blob).

## PAL: rack library palette
Owns: `fathom/static/js/rack-palette-core.js`, `fathom/static/js/rack-palette.js`, `fathom/static/css/rack-palette.css` (prefix `rpal-`), `fathom/static/dev/rack-palette.html`, `tests/js/rack-palette-core.test.mjs`, `tests/test_ui_rack_palette.py`.

**Pure core:**
- `normalizeEntries(libraryResponse, presets)`.
- `searchEntries(entries, q, opts)`: rank exact (100) > prefix (80) > token (60) > substring (40) > fuzzy edit distance 1 on tokens ≥ 4 chars (25), the same scale as `search-core`. Match name, manufacturer, model, part number, kind label and category. Ties by source (project, custom, builtin, preset, catalog), then name.
- `groupByCategory`, `CATEGORY_LABELS`.
- Favourites/recents state: `readPrefs(raw)` / `toggleFav` / `pushRecent` operate on the parsed value of `fathom.ui.rack.palette`, `{v: 1, favs, recents ≤ 12}`.
- `deviceFromTemplate(doc, template, {room, name})` → `{ops, id}`: mirror `fathom.library.instantiate`, reusing `presets-core.presetPorts` or an equivalent port-group expansion. A template's `ports` are port groups; expand them the way the server does (§4.4.3 in SPEC).

**DOM:** `mountRackPalette(el, ctx, {onPick, onDragStart})` → `{destroy, focus, refresh}`.
- Search input, category chips, Favourites and Recent sections, then results (virtualise or cap at 200 with "show more").
- Each row: thumbnail (`/static/rack-images/<image_front>` lazy `<img loading=lazy>` or a category-colour swatch), name, maker/model, `nU`, a star toggle and an Add button.
- Rows are draggable by pointer: call `onDragStart(entry, event)`; the host owns the drop.
- Data comes from `ctx.api.library({source: 'all', rack: 1, project: ctx.project})`; with no API, from a `presets` list passed in opts.
- Keyboard: arrows move, Enter = Add, `f` = star.
- At sm it fills its container (the host shows it as a bottom sheet). 44 px rows under coarse pointers.
- Provide a dev harness page.

Tests: core ranking, prefs, `deviceFromTemplate` (ids deduped, ports expanded, template id kept); UI test on the harness at d and m (search narrows, star persists across reload, Add calls `onPick`).

## DSP: display core
Owns: `fathom/static/js/rack-display-core.js`, `fathom/static/js/rack-display.js`, `tests/js/rack-display-core.test.mjs`.
- Implement contract section G for these two modules: `DISPLAY_MODES`, `ANNOTATION_FIELDS`, `CATEGORY_COLORS`, `blockColor`, `deviceImage`, `annotationValue` (exactly as in contract section C), `airflowGlyph`, `STORAGE`, plus `loadTemplateInfo(ctx, ids)` with a per-id cache and batching (one request per call for the missing ids; chunks of ≤ 100 ids).
- Also export `textColorOn(hex)`: `#000` or `#fff` by WCAG contrast. Category colours are dark, so labels must stay readable.
- Pure tests cover every field and edge (missing interfaces, a primary ip, power/weight formatting, a rear without an image, the attachment override, unknown categories).

