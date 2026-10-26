# Fathom UI uplift: audit and plan

Status: Phase A (audit) and Phase B (plan) of the UI/UX uplift brief. This file is the contract Phase C
workers are judged against. Base: `cursor/ui-uplift` at `2df0709`. Written 2026-10-26.

How to read it:

- **Audit** (A.1 to A.5) records what Fathom does today against the ten reference patterns, measured at
  1280, 820 and 390 px.
- **Plan** (B.1 to B.8) records decisions, then one section per work unit. Unit ids in capitals
  (`ROUTER`, `SHELL`, `TABLE`, `INV`, …) are used everywhere, including the file ownership matrix (B.7)
  and the verification matrix (B.8).
- "MUST" marks something a reviewer checks. Anything not stated is the worker's call, within the hard
  constraints restated in B.1.0.
- Workflow: each unit is built by one worker on its own branch `cursor/ui-<unit>-<suffix>` off
  `cursor/ui-uplift`, pushed, and reviewed by the coordinator, who runs the full gate and either merges
  it into `cursor/ui-uplift` with a `--no-ff` merge commit named after the unit (the per-unit record;
  the coordinator's tooling cannot open pull requests whose base is `cursor/ui-uplift`) or sends back a
  defect report. Nothing in this uplift merges to `main` until the final draft PR
  `cursor/ui-uplift` → `main` is reviewed by the owner.

Contents: [Audit](#audit) · [A.1 Method](#a1-method) · [A.2 Audit table](#a2-audit-table) ·
[A.3 Domain mapping and entity set](#a3-domain-mapping-and-entity-set) ·
[A.4 Already good — do not regress](#a4-already-good--do-not-regress) ·
[A.5 Per-view inventory](#a5-per-view-inventory) · [Plan](#plan) · [B.1 Decisions](#b1-decisions) ·
[B.2 Wave 1](#b2-wave-1-shared-primitives) · [B.3 Wave 2](#b3-wave-2-view-migrations) ·
[B.4 Server](#b4-server-work) · [B.5 Wave 3](#b5-wave-3-states-and-feedback-sweep) ·
[B.6 Docs](#b6-docs) · [B.7 Dependencies and ownership](#b7-dependency-graph-waves-and-file-ownership) ·
[B.8 Verification matrix](#b8-verification-matrix) · [Done / Deferred](#done--deferred)

---

## Audit

### A.1 Method

I ran the dev server from `.cursor/start.sh` (login off, so every request is admin) on the seeded
`campus` sample: 3 rooms, 73 devices, 109 cables, 3 racks, 3 floor plans, 5 SOP pages and 5 networks.
A Python script drove headless Chrome (`/usr/bin/google-chrome-stable`) over the DevTools protocol.
It loaded 24 pages at three sizes: `d` 1280×900 desktop, `t` 820×1180 iPad portrait (mobile emulation,
touch) and `m` 390×844 phone (mobile emulation, touch). On each load it waited up to 8 s for
`<html data-smoke>`, took a full screenshot, and measured:

- page-level horizontal scroll (`scrollWidth > innerWidth`);
- visible controls outside the viewport, both page-level and inside scroll containers;
- elements with inner horizontal scroll;
- `<table>` count;
- JS errors.

A second script exercised:

- the search palette with the queries `foh`, `chapel`, `A-001` (cable tag), `RC-0001` (asset tag) and
  `10.20.0.10` (IP);
- the assistant panel;
- the "More" tab menus.

I read `app.js` and every view module, SPEC §3.18, §3.21, §3.26–3.28, §5.11 and §6, and
`tests/test_frontend_smoke.py`.

The 24 pages, all on project `campus` and room `main` unless shown:

- **App views:** `map`, `patch`, `table`, `plan`, `racks`, `inventory`, `schedules` (shot as
  `sch-cables`), `imports`, `discovery`, `history`, `builds`, `settings`, `sop`, `sop?page=power-up`
  (`sop-page`), `json`.
- **Inspector states:**
  - `ins-device`: `patch?sel=device:foh-cl5`
  - `ins-port`: `patch?sel=port:rio-sl:analog-in-9`
  - `ins-cable`: `schedules?sel=cable:c-0001`
  - `ins-rack`: `racks?sel=rack:rk-foh`
- **Server-rendered viewer:** `/p/campus/rooms` (`v-rooms`), `/p/campus/r/main` (`v-room`),
  `/p/campus/r/main/patch` (`v-patch`), `/p/campus/d/foh-cl5` (`v-device`), `/p/campus/sop` (`v-sop`).

Screenshots are in `/opt/cursor/artifacts/audit/` as `<page>-<d|t|m>.png`, plus `palette-<query>-<d|m>.png`,
`assistant-<d|m>.png`, `more-menu-m.png` and `views-more-<d|t>.png`. The raw numbers are in
`/opt/cursor/artifacts/audit/measurements.log`. No page logged a JS error.

Limits: the app was walked as admin only, so viewer-role behaviour in the app comes from reading the code.
iOS Safari quirks were not exercised; Chrome mobile emulation stood in for them.

### A.2 Audit table

The parent row states the pattern overall. Rows starting with "↳" break it down per view. Effort: S is a
local change inside one file, M is one work unit (one module plus its core, CSS and tests), L is
cross-cutting across several units. Impact is the impact on users.

| Pattern | Current state | Gap | Proposed change | Effort | Impact |
| --- | --- | --- | --- | --- | --- |
| **1. App shell and nav memory** | One header row: brand, `#app-project`, `#app-room`, 15 view tabs, undo/redo, Search button, Helper, save state, user. Tabs that don't fit go into "More" (`fitTabs`). `#app-banner` sits below the header. | No sections, so every view is a peer tab. No memory of the last sub-page. Tabs are not role-filtered. Search is a button, not a visible box. | Two rows: header (brand → home, a search field centred and always visible, then a right-hand cluster: bell, assistant, save, user) and a 40px section nav (8 sections, icon + label, underline marks the active one). Per-section memory in sessionStorage. Banner strip moves above the header. Sub-views get a tab row (`#app-subnav`). | L | H |
| ↳ desktop 1280 | Only 6 of 15 tabs fit (map, patch, table, plan, racks, inventory); 9 sit in More (`views-more-d.png`). | Schedules, SOPs, Imports and Settings are two clicks away. | 7 section buttons always fit; the sub-views of the active section show in `#app-subnav`. | — | H |
| ↳ tablet 820 | Only map and patch fit; 13 views are in More (`views-more-t.png`). | Navigation is mostly hidden. | Same section nav; labels hide when measured overflow says so. | — | H |
| ↳ phone 390 | Bottom `#app-tabbar`: Map, Patch, Table, Plan, SOPs, More. More holds 9 views plus Search and Helper (`more-menu-m.png`). | Search and Helper are buried; Inventory, Racks and Schedules are 2 taps away. | The bottom tab bar shows the 8 sections as icons only (`data-tab=<section>`, so `[data-tab=sop]` is kept). Search is an icon in the header; Helper moves to the user menu. | — | H |
| ↳ banner | Conflict, offline, pending, time-travel and read-only states render in `#app-banner` below the header. | Brief: a full-width strip above the header. | Move `#app-banner` above `#app-top`; behaviour unchanged. | S | M |
| **2. Explorer + drill-in** | No shared explorer. SOP has its own tree (desktop: sidebar + "Pick a procedure on the left" placeholder; phone: drill-down). Racks and plan have ad-hoc side lists (`#rk-unracked`, `#fp-unplaced`). | No device, room or rack browser at all. Nothing is resizable, collapsible or persisted. On phones the side lists stack above the content. | `explorer.js`: resizable 240–480px, collapsible to a 56px rail, persisted in localStorage, a slide-in drawer below 700px, and a footer with counts. Used by device, room and rack pages, plus the plan and racks side lists. | M | H |
| ↳ devices | Devices are browsable only as inventory rows or patch cards. | No device list to browse. | `#/<p>/<room>/devices` landing table, then an explorer list beside each device page. | — | H |
| ↳ racks | `#rk-unracked` list renders above the rack at 390 (`racks-m.png`). | The rack sits below the fold on phones. | The unracked list becomes an explorer (sidebar on md/lg, drawer on sm). | — | M |
| ↳ plan | `#fp-unplaced` side list. | Not collapsible; takes width on tablet. | Explorer; on sm it is a drawer that closes when a drag starts. | — | M |
| ↳ SOP | Own tree, phone-first and well tested. Desktop shows an empty placeholder until a page is picked (`sop-d.png`). | Empty placeholder (the pattern says the explorer is the page). | Keep the tree; replace the placeholder with a landing (recent pages, pages due for review). | S | M |
| **3. Entity pages** | No entity pages in the app. The inspector (selection-driven, collapsible form) is the only per-entity view. The viewer has a good server-rendered device page (`v-device-*.png`) and room page. | No sticky header, no URL tabs, no overview, no recents. "Device page" in the inspector opens the public viewer page. | `entity-header.js` (sticky, facts, status, actions, overflow, URL tabs, compact variant) plus pages for device, room and rack with URL tabs; overview cards with drill-down. | L | H |
| ↳ device | Inspector sections: identity, map, ports, console, rack, inventory, net, dmx, files, qr, notes, cables, procedures, problems, dups, merged, … | 20+ sections in one scrolling form (`ins-device-d.png`). | `devices/<id>/<tab>`: overview, ports, cables, network, dmx, channels, inventory, procedures, files. Editing stays in the drawer. | — | H |
| ↳ room | Room is only a picker (`#app-room`) plus the map iframe. | No room overview. | `rooms/<id>/<tab>`: overview, devices, cables, racks, plans, procedures. | — | M |
| ↳ rack | Racks view shows all elevations; `?sel=rack:` opens the inspector. | No rack page or per-rack URL. | `racks/<id>/<tab>[/front or rear]`: overview, elevation, devices, cables. | — | M |
| **4. Shared DataTable** | About 12 ad-hoc tables (inspector `.ins-*`, `.inv-*`, `.sch-*`, `.pt-block`, `.adm-table`, `.disc-table`, `.ovl-table`). | No shared component. No pagination anywhere. No state persisted. No URL state. Inconsistent search, sort and filter. | `datatable.js` + `datatable-core.js` used by every list (see D9 for exemptions). | L | H |
| ↳ inventory | Sort, column toggle (`#inv-columns`), CSV (`#inv-csv`, the server export when online), bulk edit, filters, quick filters, group by location. All in memory. Table is 1355–1386px wide inside `.inv-scroll`; 50–60 controls sit off-screen in it. | No pagination or persistence. Filters take about 55% of the 390 screen. Row click selects but opens no drawer below 1100px. | DataTable (`key: inventory`) with the ids kept; row click opens the device drawer at `sec=inventory`. | M | H |
| ↳ schedules | Kind tabs `#sch-tab-<kind>` (cables, ip, dmx, bom, patch, racks, labels); kind is in memory (`S.kind`); filter, CSV, inline edit. Inner scroll 1747–1939px; 257–431 controls off-screen. | Kind not in the URL; no pagination or persistence; very wide. | `schedules/<kind>`; one DataTable per kind with `hideOnMobile` columns; labels stays a sheet. | M | H |
| ↳ patch table | `.pt-block` per device (printable). At 820 and 390, 111 "Remove patch" × buttons are clipped off-screen. | Can't see or patch across devices; clipped actions. | Blocks/Rows toggle: Rows is a DataTable; Blocks is kept and fixed so nothing clips. | M | M |
| ↳ imports, history, builds, settings | `.adm-table` tables (registered imports, errors, overlay, history, builds, templates, users, shares, backups), no search, sort or paging. Settings tab is in memory. | Inconsistent; nothing deep-linkable. | DataTables; `settings/<tab>`; `history/<rev>`; `?hl=` highlight. | M | M |
| ↳ discovery | `.disc-table` findings tabs (new, matches, connections, networks, unresolved, changes) in memory, under long source cards. | Findings below the fold; tab not in the URL. | `discovery/<tab>?run=`; DataTables; sources collapse into a summary. | M | M |
| **5. Progressive disclosure (drawer)** | The inspector is drawer-like: docked at ≥1100, a slide-over sheet `min(420px, 92vw)` at 700–1099, an 88dvh bottom sheet below 700. Selection writes `?sel=` (replaceState); reload with `?sel=` reopens it. | Not formalised. Below 1100, list clicks don't open it. Cable search results navigate to schedules. No section targeting. No drill-down modals. Closing always deselects. | `drawer.js` formalises the three modes on `#app-inspector`. `ctx.openDrawer(sel, {section})` writes `sel` and `sec`; `drawer=0` keeps a canvas selection without the sheet. `openTableDialog` provides count drill-downs. | M | H |
| ↳ port | `?sel=port:` shows a port form (`ins-port-*.png`). | "What is on this port now" is not first. | Port drawer leads with far end, cable and Trace. | — | H |
| ↳ cable | Clicking a cable in search navigates to schedules (`ins-cable-*.png`). | Navigation used to inspect. | Rows open the cable drawer in place; search still navigates (changing context). | — | H |
| ↳ inventory row | Selects the device; no drawer below 1100. | — | Opens the device drawer at the inventory section. | — | H |
| **6. Landing + global search** | A project opens on Patch. The palette (⌘K, `#app-palette`) is grouped by kind with arrow, Enter and Esc keys. It already finds `foh`, `chapel`, `A-001`, `RC-0001` (FOH CL5 first) and IPs (`palette-*.png`). | No home, recents, category filter or status. Networks are not indexed. No "inventory" category. Search is not a visible field. | `home` view: section cards, room cards, recents strip, project cards. Search adds a field look, a category select, recents, status, a networks kind and an inventory category. | M | H |
| **7. States and feedback** | "Loading X…" text; a good error card for failed modules (`test_view_error_card`); toasts; the banner. Confirms are generic (`confirmDialog`). Review signals are scattered (model suggestions `.ms-*`, inspector `dups`, discovery unresolved). | No skeletons, no consistent empty copy, no freshness (the overlay can be older than the doc), no bell, inconsistent scope restating. | `feedback.js`: skeleton, emptyState, inlineError + retry, `confirmScope`, staleBadge, reviewBadge, notices + bell. Wave-3 sweep per view. | M | M |
| **8. Forms and wizards** | Inline autosaving inspector forms; dialogs (new project, add gear via `pickTemplate`, add rack); CSV imports with preview (bulk via files). | No wizard; no paste-to-bulk-add beside "add one"; no remembered values. | `wizard.js`: step list, validation, review, result. `bulkAdd` for devices and cables from pasted rows, using the same validators as single add. `rememberForm`. | M | M |
| **9. URL as state** | `#/<p>/<room>/<view>?sel=&filter=` plus SOP params (`page`, `edit`, `new`, `parent`, `device`, `from`). | Kind, tab, floor plan, rack, filters, sort, search and page live only in memory. Back after a selection goes to the previous view. | `router-core.js` extends the grammar to `/<view>/<id>/<tab>/<sub>` with `q`, `sort`, `f.*`, `pg`, `sec`, `hl`, `drawer`, `mode`, `run`. All old URLs keep working. | M | H |
| **10. Responsive** | Breakpoints 1100/700 (FR-MOB-01) plus local 899, 719, 599, 559. `(pointer: coarse)` gives 44px targets. No page-level horizontal scroll on any app view at 390 (the viewer room map is wider by design). | Inner horizontal scroll and clipped controls (see A.5): PV toolbar 663/390, `.rk-viewport` 420/390, imports `.app-view` 507/390, inventory and schedules tables, patch-table × buttons, inspector "Show 15 more ports". | Named breakpoints sm/md/lg. `hideOnMobile` columns. One-row toolbars with overflow menus. Explorer drawer. Icon-only nav at sm. Selection bar for canvas views. | M | H |

### A.3 Domain mapping and entity set

Mapping each pattern onto Fathom:

1. **Shell.** Sections (D2):
   - Home: `home`
   - Patch: `patch`, `table`, `map`
   - Rooms: `rooms`, `plan`, `racks`
   - Devices: `devices`, `inventory`
   - Schedules: `schedules`, `builds`
   - SOPs: `sop`
   - Data: `imports`, `discovery`, `history`, `json`
   - Settings: `settings`

   Notifications are offline flushes, conflicts, imports with errors, discovery runs finished and new
   problem reports. There is no theme switch (out of scope).
2. **Explorer.** The device explorer is a list of devices in the current room, grouped by discipline,
   with discipline chips and the footer "40 devices · Main Auditorium". The room explorer lists rooms
   (grouped by venue when the doc has venues) with device counts. The rack explorer lists racks grouped
   by room. Canvas sub-routes (patch, plan canvas, map) hide the sidebar and use full width.
3. **Entity pages.**
   - **Device.** Sticky header: name, discipline glyph and kind, status pill, room, rack · U, primary IP
     or Dante name, ports "n (m patched)".
     - Tabs: overview, ports, cables, network, dmx, channels, inventory, procedures, files.
     - Overview cards: Ports, Cables, Network, Procedures, Problems, Files.
   - **Room.** Header: name, code, venue, devices, racks, plans, open problems, with a floor-plan
     thumbnail.
     - Tabs: overview, devices, cables, racks, plans, procedures.
   - **Rack.** Header: name, room, height U, used/free U, device count, location.
     - Tabs: overview, elevation (front or rear), devices, cables.
4. **DataTable.** Lists of devices, ports, cables, IP rows, DMX rows, BOM lines, rack rows, imports,
   overlay rows, revisions, builds, rooms, systems, locations, networks, templates, users, shares,
   backups, discovery findings and runs, and problem reports.
5. **Drawer.** Port: far end, cable, signal, Trace. Cable: endpoints, tag, medium, length, state.
   Device: the existing inspector. Inventory item: the device drawer at the inventory section. Drill-down
   modal: overview counts ("32 cables") open `openTableDialog`.
6. **Landing.** Cards per section (role-filtered), per-room quick cards (Patch, Plan, Racks and SOPs for
   that room), a recents strip and project cards. Search covers devices, inventory (serial or asset tag
   match), rooms, racks, ports, cables, networks and IPs, plans, procedures and files.
7. **States.** The overlay (import-derived data) carries a "Stale · updated N min ago" badge when it is
   older than the doc revision. Discovery runs show their age. Review badges cover model suggestions,
   duplicate devices, unresolved discovery findings and problem reports.
8. **Forms.** Wizards: bulk add devices, bulk add cables, new share link. Prefill: current room, current
   device. Remembered: last room and status used in bulk add.
9. **URL.** D1.
10. **Responsive.** D3. Phones are first-class for lookup: find a device, read a port, open a SOP, scan a
    QR. Heavy editing (patch canvas drag, rack edit) assumes md or wider but stays usable at sm.

**Entity set: page or drawer.** Rule: an entity gets a **page** when a person orients by it and it has
several kinds of related records. It is a **drawer item** when you inspect it from a list without
changing context.

| Entity | Page or drawer | URL | Why |
| --- | --- | --- | --- |
| Device | Page + drawer | `devices/<id>/<tab>`; drawer `?sel=device:<id>[&sec=<section>]` | Orienting entity with ports, cables, network, SOPs and files. The drawer stays the editing surface so canvas editing is unchanged. |
| Room | Page | `rooms/<id>/<tab>` (room segment set to `<id>`) | Location entity; the context for patch, plan and racks. |
| Rack | Page + drawer | `racks/<id>/<tab>[/front or rear]`; drawer `?sel=rack:<id>` | Physical container with an elevation and devices. The drawer keeps the existing rack form. |
| Cable | Drawer | `?sel=cable:<id>` | A port-to-port link. Inspected from lists, schedules and device pages; its related records are just its two ends. |
| Port | Drawer | `?sel=port:<device>:<port>` | Always seen in the context of its device. The device page's ports tab lists them. |
| Inventory item | Drawer (the device) | `inventory?sel=device:<id>&sec=inventory` | An inventory item is a device record seen through its inventory fields (serial, asset tag, status, location). No separate entity exists on disk, and the data format must not change. |
| Floor plan | Canvas view | `plan/<fp>` | A floor plan is a working surface, not a record to read. Its "detail" is the canvas. Metadata stays in the existing floor-plan drawer (`?sel=floorplan:<id>`). |
| Network | Drawer-like row highlight | `settings/networks?hl=<id>` | Networks are configuration (VLAN, subnet) edited in Settings. Device membership shows on device network tabs. A page is Deferred. |
| SOP page | Page (existing) | `sop?page=<slug>` (unchanged) | Already a phone-first, tested page with its own grammar. Changing it risks the SOP flows. |
| Interface, channel, marker, bundle | Drawer | `?sel=device:<id>&sec=net`, `?sel=channel:…`, `?sel=marker:…`, `?sel=bundle:…` | Sub-records of a device or plan. |

### A.4 Already good — do not regress

| # | Behaviour | Guarding test(s) |
| --- | --- | --- |
| 1 | Port-to-port drag patching on the canvas (mouse and touch) | Logic: `tests/js/patchview-core.test.mjs` "hitTest", "compatibleTargets"; `tests/js/model-core.test.mjs` "canConnect", "connectOps", "repatchOps". The **gesture is unguarded**; `PV` adds a CDP drag test first (B.3 PV). |
| 2 | Trace / "light every path" highlighting and the trace drawer | `patchview-core.test.mjs` "traceLocal …" (4 tests); `test_api.py::test_trace`; `tests/test_trace_channels.py`; `test_console_channels.py::test_public_device_page_lists_channels_with_trace_buttons`. The in-app trace drawer UI is **unguarded**; `QA` covers it. |
| 3 | QR device pages and QR sheets | `test_api.py::test_qr_endpoint`; `test_exports.py` QR class; `test_sop.py::test_qr_code_and_sheet`; viewer page `/p/sunday-demo/d/atem-mini` in `test_frontend_smoke.py::test_viewer_pages`. |
| 4 | Viewer read-only permissions | `test_security.py::test_viewer_put_403_and_users_admin_only`; `model-core.test.mjs` "store read-only"; `test_device_merge.py::test_viewer_cannot_merge`. In-app hiding of edit controls is **unguarded**; `QA` adds a viewer-role run. |
| 5 | PWA installability (manifest, icons, SW) | `test_api.py::test_manifest` (manifest fields, icons, `/sw.js` contains `fathom-shell-`). The precache list and installability are **unguarded** (manual DevTools check by `QA`). |
| 6 | Offline change queue and conflict banner | `tests/js/api.test.mjs` "ChangeQueue persists and flushes", "ChangeQueue conflict pauses"; `test_api.py::test_stale_put_rebase_and_conflict`, `::test_changes_rebase_and_conflict`. Banner UI is **unguarded**. |
| 7 | SOP wiki phone-first flows | `test_frontend_smoke.py::test_sop_viewer_on_a_phone`, `::test_public_sop_page_on_a_phone_via_share_link`, `::test_report_a_problem_sheet_on_a_phone`; `tests/test_sop.py`. |
| 8 | Deep link `?sel=` opens the inspector on reload | `test_frontend_smoke.py::test_deep_link_selection`. |
| 9 | A failing view module shows an inline error card | `test_frontend_smoke.py::test_view_error_card`. |
| 10 | ARIA: canvas `role=application`, cards `role=group`, `#fathom-live` polite, `<th scope>` | `test_frontend_smoke.py::test_aria_landmarks`. |
| 11 | Patch view renders 150 devices / 600 cables in budget | `test_frontend_smoke.py::test_patchview_perf_150_600`. |
| 12 | Search ranking and IP lookup | `model-core.test.mjs` "searchLocal", "searchLocal ranking"; `test_assistant.py::test_search_ip`, `::test_search_ranking`; `test_api.py::test_search`. |
| 13 | Imports model-suggestion flow on a phone | `test_frontend_smoke.py::test_model_suggestion_in_imports_overlay_on_a_phone`. |
| 14 | No page-level horizontal scroll on app views at 390 (measured in A.1) | **Unguarded**; `SHELL` adds a guard in `tests/test_ui_shell.py`. |
| 15 | 44px touch targets under `(pointer: coarse)` | Partly: the SOP phone test (rows ≥ 44px) and the suggestion test (buttons ≥ 44px). The rest is **unguarded**; each wave-2 UI test checks its primary actions. |
| 16 | Undo/redo (store and ⌘Z / ⌘⇧Z) | `model-core.test.mjs` store undo tests. Keyboard shortcuts are **unguarded**. |
| 17 | Login, session and no redirect loop | `test_frontend_smoke.py` `LoginFlow`. |
| 18 | CLI, imports, builds and exports | `tests/test_fathom.py`, `tests/test_importers.py`, `tests/test_exports.py`, `fathom selftest`. |
| 19 | Server-rendered viewer pages (device facts, QR, tables, Trace buttons; phone friendly) | `test_frontend_smoke.py::test_viewer_pages`; `test_compat.py::test_rrc_viewer_unchanged_structure`. |
| 20 | Harnesses (patch view, floor plan, rack, schedules, patch table) | `test_frontend_smoke.py::test_harnesses`, `::test_patchview_harness`, `::test_rack_harness`. |
| 21 | Every view in `VIEWS` mounts without errors; shell ids exist | `test_frontend_smoke.py::test_app_views`, `::test_app_shell_dom_ids`. |
| 22 | CSP: no inline script or handlers in the app | `test_security.py::test_security_headers` (CSP string). Inline handlers are **unguarded**; `h()` binds `on*` functions as listeners, which is the rule (D12). |

### A.5 Per-view inventory

The "breaks at 390" column uses the measurements in A.1. Screenshots are in `/opt/cursor/artifacts/audit/`.

| View | Module / file | Lists (DataTable candidates) | Inspect-one (drawer candidates) | What breaks at 390px | Screenshots |
| --- | --- | --- | --- | --- | --- |
| Shell | `app.js`, `app.css`, `app.html` | — | — | 6 tabs + More; Search and Helper only in More; banner below the header | `more-menu-m.png`, `views-more-d.png`, `views-more-t.png` |
| Map | `app.js` (internal iframe) | — | Device markers (inside the iframe) | Nothing | `map-*.png` |
| Patch view | `patchview.js`, `patchview.css` | Context lists only (exempt) | Device card, port, cable wire | `.pv-toolbar` wraps to about 50% of screen height (inner scroll 663/390); 5 controls off-screen | `patch-*.png`, `ins-device-*.png`, `ins-port-*.png` |
| Patch table | `patchtable.js`, styles in `app.css` | Patch rows (a new Rows mode) | Port row, cable | 111 "Remove patch" buttons clipped (also at 820) | `table-*.png` |
| Floor plan | `floorplan.js`, `plan.css` | `#fp-unplaced` (drag source; exempt, gets search) | Marker, floor plan | Three-row toolbar; unplaced list takes height | `plan-*.png` |
| Racks | `rack.js`, `plan.css` | Rack devices (rack page tab); `#rk-unracked` (drag source; exempt) | Rack, rack block (device) | Unracked list above the rack; `.rk-viewport` 420/390 | `racks-*.png`, `ins-rack-*.png` |
| Inventory | `inventory.js`, `plan.css` | Inventory rows | Inventory row → device drawer (`sec=inventory`) | `.inv-scroll` 1386/390; 60 controls off-screen inside it; filters take about 55% of the screen | `inventory-*.png` |
| Schedules | `schedules.js`, `plan.css` | cables, ip, dmx, bom, patch, racks (labels is a sheet) | Cable row; device rows (ip, dmx, bom) | `.sch-scroll` 1747/370; 431 controls off-screen inside it | `sch-cables-*.png`, `ins-cable-*.png` |
| Imports | `views-admin.js` (`mountImports`), styles in `app.css` | Registered imports, import errors, overlay (`.ovl-table`), preview errors | Overlay row → device drawer | `.app-view` 507/390; 12 controls off-screen | `imports-*.png` |
| Discovery | `views-discovery.js`, styles in `app.css` | Runs; findings tabs (new, matches, connections, networks, unresolved, changes) | Finding → device drawer when matched | Long source cards push findings below the fold | `discovery-*.png` |
| History | `views-admin.js` (`mountHistory`) | Revisions | Revision (highlight, diff, time travel) | Nothing; minimal empty state | `history-*.png` |
| Builds | `views-admin.js` (`mountBuilds`) | Build runs, outputs | — | Nothing | `builds-*.png` |
| Settings | `views-admin.js` (`mountSettings`) | rooms, systems, locations, networks, templates, users, shares, backups | Row → existing edit dialog | Tab strip wraps; tab not in the URL | `settings-*.png` |
| SOP | `views-sop.js`, `sop.css` | Problem reports | Device chip → device drawer (`sec=procedures`) | Nothing (phone-first); `.sop-applies-chips` inner scroll is intended | `sop-*.png`, `sop-page-*.png` |
| JSON | `app.js` (internal) | — | — | Nothing | `json-*.png` |
| Inspector | `inspector.js`, styles in `app.css` | Port editor (exempt editor) | Is the drawer | 88dvh sheet; "Show 15 more ports" off-screen | `ins-*.png` |
| Assistant | `assistant-ui.js` | — | — | Full-screen panel (fine) | `assistant-d.png`, `assistant-m.png` |
| Search palette | `app.js` (`openPalette`) | Results (exempt: combobox) | — | Fine; no category filter | `palette-*.png` |
| Viewer pages | `fathom/render_html.py` (server) | Server tables (out of scope, D7) | — | Room map 1424px wide by design (pinch-zoom) | `v-*.png` |

---

## Plan

### B.1 Decisions

#### B.1.0 Hard constraints (restated; every unit is judged against them)

- Out of scope: colours, theme, typography, icon set, branding. Change layout and behaviour, not
  styling for its own sake. Reuse the existing unicode glyphs and CSS variables.
- No-build, ES2018 (no `?.`, `??`, class fields, optional catch binding), framework-free, no new
  runtime dependencies. `tests/js/syntax.test.mjs` scans every new file.
- Must not break:
  - port-to-port drag, trace / "light every path", QR pages;
  - viewer read-only, PWA install, CLI, imports, builds and exports;
  - the offline queue, the conflict banner, and the SOP phone flows.
- No change to on-disk data formats or to the revision/history mechanism. No feature is removed; it is
  relocated (drawer, tab or overflow menu).
- Keep the hash router: the app at `/`, the viewer at `/p/...`. No server route change is needed for
  client URLs.
- Keep the smoke ids:
  - Shell: `#app`, `#app-top`, `#app-project`, `#app-room`, `#app-views` with `[data-view]`,
    `#app-search`, `#app-assistant-btn`, `#app-save`, `#app-user`, `#app-main`, `#app-inspector`,
    `#app-assistant`, `#fathom-live`, `#app-toasts`, `#app-dialog`, `#app-palette`,
    `#app-palette-input`.
  - View ids: `#pv-*`, `#pt-*`, `#fp-*`, `#rk-*`, `#sch-*`, `#inv-*`.
  - Tests reference only `.pv-viewport`, `.pv-card`, `.fp-viewport` and `.rk-block`. The ids are a SPEC
    contract (§6.5–6.7), so a moved control keeps its id (its element type may change; `DOCS` records
    that).

#### D1. URL grammar (`router-core.js`)

```
#/<project>/<room>/<view>[/<seg4>[/<seg5>[/<seg6>]]][?<query>]
```

- `<project>` and `<room>` are as today (`*` means all rooms; empty means the default room). An empty
  `<view>` means `home`; legacy `/?p=<name>` also leads to home. This changes today's default from patch.
- `parseRoute(hash)` returns `{project, room, view, id, tab, sub, extra, query}`:
  - `extra` holds raw segments beyond the view's shape;
  - `query` is a plain object of decoded strings, first value winning;
  - unknown keys are kept and round-trip.
- `buildRoute(route)` writes segments with `encodeURIComponent` (keeping `*` in the room, as `buildHash`
  does). Query values are written with `encodeURIComponent`, then `%3A`→`:`, `%2C`→`,`, `%7C`→`|` and
  `%2F`→`/`. Trailing empty segments and empty, null or undefined query values are dropped. Key order
  follows insertion order.
- Round trips: `buildRoute(parseRoute(h)) === h` byte-for-byte for every hash `buildRoute` itself
  produces. For hashes written by the legacy `buildHash` (which escapes `,`, `|` and `/` in query
  values as `%2C`, `%7C`, `%2F`) the round trip is semantic: `parseRoute` yields the same route object,
  and `sameRoute(parseRoute(h), parseRoute(buildRoute(parseRoute(h))))` is true. A test vector table is
  in B.2 ROUTER. (Settled by the coordinator after T-ROUTER/ROUTER flagged the contradiction; the
  implementation's behaviour is normative.)
- Settled by ROUTER (normative): `legacyHash` maps an empty view to `home`; `mergeRoute(route, patch)`
  replaces `query` wholesale when `patch.query` is given (use `withQuery` for key-wise changes) and
  resets `id/tab/sub/extra` when the view changes; `sectionRoot(key, route, role)` returns `null` for an
  unknown or not-permitted section; `navMemory.target(project, key, route, role)` returns `''` only in
  that case, and otherwise returns the remembered hash when it is still permitted for `role`, else the
  section root.
- `parseHash` and `buildHash` stay exported from `app.js` as thin wrappers; `views-sop.js` imports them.
  `selToString` and `selFromString` move to `router-core.js` and `app.js` re-exports them unchanged.

Path shapes per view (`VIEW_SHAPES`):

| View | Segments after `<view>` | Example |
| --- | --- | --- |
| `home`, `patch`, `table`, `map`, `inventory`, `builds`, `sop`, `json` | none | `#/campus/main/inventory?sel=device:foh-cl5&sec=inventory` |
| `devices` | `id`, `tab`, `sub` | `#/campus/main/devices/foh-cl5/ports?sel=port:foh-cl5:omni-in-1` |
| `rooms` | `id`, `tab` | `#/campus/chapel/rooms/chapel/devices` |
| `racks` | `id`, `tab`, `sub` | `#/campus/main/racks/rk-foh/elevation/rear` |
| `plan` | `id` (floor plan) | `#/campus/main/plan/fp-main-stage?sel=marker:fp-main-stage:foh-cl5&drawer=0` |
| `schedules` | `tab` (kind) | `#/campus/main/schedules/cables?q=drum&sort=-length&pg=2` |
| `imports` | `tab` (reserved; landing only for now) | `#/campus/main/imports?hl=imp-0003` |
| `settings` | `tab` | `#/campus/main/settings/networks?hl=av-dante` |
| `discovery` | `tab`, `sub` (`sub` reserved) | `#/campus/main/discovery/unresolved?run=run-20261026-101500-0001` |
| `history` | `id` (revision: highlight and diff only, not time travel) | `#/campus/main/history/42` |

Query keys:

| Key | Meaning | Writer |
| --- | --- | --- |
| `sel` | Selection and drawer subject (existing grammar: `device:`, `port:dev:port`, `cable:`, `rack:`, `floorplan:`, `marker:fp:dev`, `channel:dev:ch`, `bundle:`, `room:`) | shell selection listener (replaceState); `ctx.openDrawer` |
| `sec` | Drawer section to focus (inspector `data-section` key, e.g. `inventory`, `net`, `procedures`) | `ctx.openDrawer`, inspector |
| `drawer` | `0` means the item is selected but the drawer is closed (canvas views below 1100) | shell |
| `filter` | Patch-view discipline filter (existing) | patch view |
| `q` | Search text of the view's primary DataTable or filter box | DataTable / view |
| `sort` | `col` ascending, `-col` descending | DataTable |
| `f.<col>` | Column filter values joined with `\|`; `~` alone means "(empty)"; a literal `\|`, `~` or `\` is escaped with `\` | DataTable |
| `pg` | 1-based page index (not `page`, which SOP uses) | DataTable |
| `hl` | Highlight a row by id (deep links from search) | caller |
| `mode` | `rows` or `blocks` (patch table) | patch table |
| `run` | Discovery run id | discovery |
| `quick` | Inventory quick filter `warranty` or `serial` | inventory |
| `page`, `edit`, `new`, `parent`, `device`, `from` | SOP (unchanged) | SOP |
| `smoke`, `debug_missing_view` | Test hooks; read from `location.search` or the hash query; ignored by routing | tests |

History rules:

- Changing view, entity (`id`) or tab uses `pushState`.
- Selection changes use `replaceState`, as today.
- Opening the drawer from closed uses `pushState`, so the phone Back gesture closes it. Switching drawer
  subject while open, and closing, use `replaceState`.
- DataTable state (`q`, `sort`, `f.*`, `pg`) uses `replaceState`.
- The shell writes with `history.pushState` or `replaceState` and then calls its hash handler itself,
  because `pushState` fires no `hashchange`.

Same-view hash changes:

- If the mounted view handle has the new optional method `route(r)`, the shell calls it.
- Otherwise the shell remounts when `id`, `tab` or `sub` changed (keeping `getState`/`setState`).
- Otherwise it does what it does today (`focus(sel)`), which keeps SOP's own hash handling intact.

#### D2. Sections, role filtering and nav memory

`SECTIONS` lives in `router-core.js`. Glyphs are existing unicode, with `\uFE0E` text presentation where
iOS would draw an emoji.

| key | label | glyph | views (first = root) | shown in |
| --- | --- | --- | --- | --- |
| `home` | Home | ⌂ `\u2302` | `home` | phone tab bar only (brand link on md/lg) |
| `patch` | Patch | ⮕ `\u2B95` | `patch`, `table`, `map` | all |
| `rooms` | Rooms | ▣ `\u25A3` | `rooms`, `plan`, `racks` | all |
| `devices` | Devices | ◫ `\u25EB` | `devices`, `inventory` | all |
| `schedules` | Schedules | ☰ `\u2630` | `schedules`, `builds` | all |
| `sop` | SOPs | ☑ `\u2611` | `sop` | all |
| `data` | Data | ⇅ `\u21C5` | `imports`, `discovery`, `history`, `json` | all |
| `settings` | Settings | ⚙ `\u2699\uFE0E` | `settings` | all |

Role filtering follows the API roles in `SPEC_ROLES`. Every current view's GET routes are viewer-readable,
so **no section is hidden for viewers**; hiding Imports or Discovery would remove features. Filtering
happens at tab and action level instead:

- Settings tabs: `users` and `backups` need admin; `sharing` needs editor.
- Write actions (Add, Bulk add, Build, Run discovery, Upload, Apply JSON, Delete, Merge, bulk edits) are
  not rendered for viewers.
- `router-core` exports `VIEW_ROLES` (all `viewer`), `TAB_ROLES` and `canSee(view, role, tab)`, so a later
  role-gated view needs only a table entry.
- With login off everyone is admin, as today.

Nav memory:

- sessionStorage `fathom.ui.nav` holds `{"<project>": {"<section>": "<full hash>"}}`, written on every
  route.
- Clicking a section that is not active goes to its remembered hash, or to its root (first permitted
  view, same room, no id or query).
- Clicking the active section goes to its root.

#### D3. Breakpoints

Keep FR-MOB-01's numbers and name them: **sm < 700**, **md 700–1099**, **lg ≥ 1100**. Every existing CSS
rule and test already uses 700 and 1100, and an iPad mini in portrait (744) stays md.

- `router-core` exports `BP = {md: 700, lg: 1100}` and `layoutFor(width)`, which returns `'sm'`, `'md'`
  or `'lg'`.
- CSS uses `@media (max-width: 699px)`, `(min-width: 700px) and (max-width: 1099px)` and
  `(min-width: 1100px)`.
- New code uses no other breakpoints. Existing local ones (899, 719, 599, 559) are left alone unless
  their owner is already editing that rule.
- `(pointer: coarse)` keeps 44px targets; everywhere else the minimum is 40px (pattern 10).

| | sm (< 700) | md (700–1099) | lg (≥ 1100) |
| --- | --- | --- | --- |
| Section nav | Bottom `#app-tabbar`, icons only, `aria-label` | `#app-views` row, icon + label; labels hide when they don't fit | `#app-views` row, icon + label |
| Sub-views | `#app-subnav` chip row (scrolls inside itself) | `#app-subnav` | `#app-subnav` |
| Search | Icon button → full-screen palette | Field → anchored dropdown | Field → anchored dropdown |
| Explorer | Slide-in drawer (85vw, max 24rem) | Sidebar (resizable, collapsible) | Sidebar |
| Drawer (`#app-inspector`) | Full-height sheet, modal | Slide-over sheet `min(420px, 92vw)`, modal | Docked column, non-modal |
| Canvas selection | Select + `#app-selbar`, `drawer=0` | Select + `#app-selbar`, `drawer=0` | Docked drawer opens (as today) |
| DataTable | `hideOnMobile` columns hidden; first column sticky | All visible columns | All visible columns |
| Entity header | Compact single row; facts in a `details` | Full; compact once scrolled | Full; compact once scrolled |

#### D4. Inspector = drawer

- `#app-inspector` stays the single drawer host, and `inspector.js` stays its content.
- `drawer.js` owns the three modes (docked, sheet, full), the backdrop, focus trap, Esc and focus return.
- The inspector stays **selection-driven**, so drag patching and every existing `ctx.select` caller work
  unchanged.
- **Drawer state is `sel` (+ `sec`).** On reload, `sel` without `drawer=0` opens the drawer at every width.
  This preserves `test_deep_link_selection`.
- `ctx.openDrawer(sel, {section})` is for explicit inspection: list rows, search, "Details" buttons. It
  selects, writes `sel`/`sec`, removes `drawer`, opens, and calls the inspector's `focusSection`.
- Plain `ctx.select` from a canvas (patch, plan, rack elevation) opens the docked drawer at lg, as
  today. Below lg it writes `drawer=0` and shows `#app-selbar` ("FOH CL5 · Details ›  ×"), so the sheet
  never covers the canvas mid-gesture.
- Close (×, Esc, backdrop) calls `ctx.closeDrawer()`, which deselects and removes `sel`, `sec` and
  `drawer`, as today.
- Esc priority, topmost first: palette, dialog (`.app-dialog-backdrop`), trace drawer
  (`.trace-backdrop`), assistant, explorer drawer, drawer, highlight. At lg the docked drawer closes on
  Esc only when focus is inside it.
- The trace drawer (`trace-ui.js`) stacks above the drawer and is not URL-addressed (Deferred).
- **Rows open drawers, landings navigate:** a row in a landing list (devices, rooms) changes entity, so
  it navigates. A row of related records inside a page or list (ports, cables, inventory, room devices)
  opens the drawer.

#### D5. Entity pages

Device, room and rack get pages (A.3). Pages are read-mostly: tabs are DataTables and summaries, and
editing happens in the drawer ("Edit" opens `?sel=<entity>`). Every field therefore keeps one editor, the
inspector.

Unknown id: inline error "<Kind> “x” not found" with a link to the landing. Unknown tab: the URL is
replaced with the default tab `overview`.

#### D6. Shell layout and stable ids

`app.html` order inside `#app`:

1. `#app-banner` (moved above the header)
2. `header#app-top`, containing:
   - `a#app-home.app-brand` (brand → home)
   - `#app-project` (hidden at sm; project switching moves to the user menu and home)
   - `#app-room`
   - `#app-search` (a `button` styled as a field: glyph + "Search devices, cables, rooms…" + `⌘K` hint;
     icon-only at sm)
   - `#app-undo`, `#app-redo` (hidden at sm; in the user menu)
   - `#app-assistant-btn` (hidden at sm; in the user menu)
   - `#app-notify` with `#app-notify-count`
   - `#app-save` (a dot + `aria-label` at sm)
   - `#app-user`
3. `nav#app-views` (section buttons)
4. `nav#app-subnav`
5. `#app-body` > `main#app-main` + `aside#app-inspector`
6. `#app-selbar`
7. `nav#app-tabbar`

`#app-assistant`, `#app-toasts`, `#app-dialog` and `#fathom-live` stay outside `#app`.

Section buttons are `button.app-sec[data-section=<key>][data-views="<v1> <v2>"]` with `aria-current="page"`
on the active one. Each holds a `hidden` `ul.app-sec-menu` with one `button[data-view=<view>]` per
permitted view. The menu opens on ArrowDown, or on contextmenu/long-press, never on hover. Every view
therefore keeps a `[data-view]` button inside `#app-views`, which keeps `test_app_shell_dom_ids` valid.
The `home` section button is also rendered in `#app-views` (hidden by CSS at md/lg, where the brand link
replaces it), so `[data-view=home]` exists at every width.
`#app-subnav` holds `a.app-subtab[data-view][href]` for the active section. Tab bar buttons are
`button[data-tab=<section>]`, so `[data-tab=sop]` is kept.

#### D7. Viewer impact

- **Read-only viewer in the app** (role `viewer`, or `store.readOnly`): sees every section. Write actions
  are not rendered (D2). The drawer shows the inspector's existing read-only rendering. DataTables hide
  checkboxes and bulk bars when `ctx.store.readOnly`. The wizard entry points are hidden.
- **Server-rendered viewer** (`/p/<project>/…`, `fathom/render_html.py`): **unchanged** in this uplift.
  The audit found it phone-friendly (A.2 row 3, A.5). Adopting the DataTable there needs a server-side
  renderer, so it is Deferred. QR links and the "Public page" action keep pointing to it.

#### D8. Storage keys

Existing keys are untouched: `fathom.pending.<project>` and `fathom.sop.tasks.` / `.done.` / `.draft.`.

| Key | Store | Shape | Owner |
| --- | --- | --- | --- |
| `fathom.ui.nav` | sessionStorage | `{"<project>": {"<section>": "<hash>"}}` | ROUTER (logic), SHELL (wiring) |
| `fathom.ui.explorer.<key>` | localStorage | `{"w": 240..480, "c": false}` | EXPLORER |
| `fathom.ui.table.<scope>.<key>` | localStorage | `{"v": 1, "sort": {"col", "dir": 1 or -1} or null, "filters": {"<col>": ["v", …]}, "pageSize": 25/50/100/200, "hidden": ["col"], "density": "normal" or "compact", "extra": {}}`; `<scope>` is the project, or omitted with its dot when empty | TABLE |
| `fathom.ui.recent.<project>` | localStorage | `{"device": [{"id", "t"}], "room": […], "rack": […], "page": […]}`, newest first, max 8 per type, deduped | SHELL (`ctx.recent`) |
| `fathom.ui.notices.<project>` | sessionStorage | `[{"id", "level", "text", "href", "t", "read"}]`, max 50 | FEEDBACK |
| `fathom.ui.form.<key>` | localStorage | Last-used values for a form | WIZARD |

All readers tolerate missing or corrupt JSON (fall back to defaults) and a throwing `localStorage`
(Safari private mode).

#### D9. What counts as a list (DataTable scope)

**Every read list of records** uses `datatable.js`. QA enforces this mechanically: on each view at lg,
`table:not(.dt-table)` outside the exempt selectors must be empty.

Exempt:

- `.pt-block table` (patch table Blocks mode, a printable sheet; Rows mode is the DataTable)
- the schedules labels sheet (`.sch-labels`)
- `.md-table` (Markdown content)
- inspector editor grids (port editor, channel editor)
- picker dialogs (`pickTemplate`, `pickPort`, `pickDevice`) and the map groups dialog
- `#app-palette-list` (combobox)
- explorer lists (navigation)
- drag-source lists (`#rk-unracked`, `#fp-unplaced`), which get a search box instead
- the JSON view
- viewer pages

#### D10. Tests: ids and ownership

- No wave-2 or wave-3 unit edits `tests/test_frontend_smoke.py`. Only `SHELL` (wave 1) edits it, as
  listed in B.2 SHELL. If a migration would break an existing assertion, the unit keeps the selector
  working (adds the class or attribute to the new markup).
- Each UI unit owns one new `tests/test_ui_<unit>.py` built on `tests/_ui.py` (created by `ROUTER`,
  which merges first, to the specification in B.2 SHELL item 10; read by everyone else, extended by
  nobody — a unit needing another helper defines it in its own test file). Files named `_ui.py` are not
  collected by `unittest discover`.
- Each `*-core.js` gets `tests/js/<name>-core.test.mjs` using `loadModule` from
  `tests/js/fixtures/helpers.mjs`.
- Each wave-1 component also owns a dev harness page `fathom/static/dev/<name>.html` with
  `fathom/static/dev/<name>-harness.js`, so it can be tested in a browser before `SHELL` lands.
- Budget: each `test_ui_*.py` file finishes in about 20 s. Start one server per class, as
  `FrontendSmoke` does, and use `/usr/bin/google-chrome-stable` through `FATHOM_CHROME`.

#### D11. CSS ownership

- `app.css` is owned by `SHELL` in wave 1 and `ST-SHELL` in wave 3. Nobody else edits it.
- `plan.css` is owned by `FP` in wave 2. `RK`, `INV` and `SCH` must not edit it; they put overrides in
  their own new CSS files, loaded through the `VIEWS` registry (`css` becomes an array, e.g.
  `['plan.css', 'rack.css']`).
- Inspector, patch table, admin and discovery styles stay in `app.css`. Their new files
  (`inspector.css`, `patchtable.css`, `admin.css`, `discovery.css`) hold only new or overriding rules.
  Moving legacy rules out of `app.css` is Deferred.
- New class prefixes: `ex-` explorer, `eh-` entity header, `dt-` DataTable, `dr-` drawer, `sr-` search,
  `hm-` home, `fb-` feedback, `wz-` wizard, `pd-` device page, `pr-` room page, `rp-` rack page.

#### D12. Module rules

- New shared components import DOM helpers from a new `dom.js` (`h`, `esc`, `on`), not from `app.js`.
  That avoids import cycles with the shell, which imports them. Wave-2 views may keep importing from
  `app.js`.
- `*-core.js` files are pure: no `document`, `window` or `localStorage` at module top level, and storage
  is injected. They must import in Node.
- Views treat every new `ctx` member as optional. `makeCtx` provides safe defaults (B.2 SHELL), so
  `fathom/static/dev/plans/harness.js` (which calls `makeCtx`) keeps working unchanged.
- No inline event-handler attributes (CSP `script-src 'self'`); `h()` binds `on*` functions as listeners.
- Lazy imports: views are `import()`ed by the shell. Shared components are imported statically by views.

#### D13. Merge order within a wave

- **Wave 1** runs as three sub-waves so that no unit has to import a module that is not yet on
  `cursor/ui-uplift`:
  - **1a:** `ROUTER` (with `tests/_ui.py`) and `SRV` start at once; `ROUTER` merges first because every
    other unit imports `dom.js` and `router-core.js`. The test-first workers (B.7) also start here.
  - **1b** (after `ROUTER` merged): `EXPLORER`, `ENTITY`, `TABLE`, `DRAWER`, `SEARCH`, `FEEDBACK` in any
    order, plus `HOME`, `WIZARD` and `SHELL`, which depend on 1b siblings: they code against this
    document's contracts, keep merging `origin/cursor/ui-uplift` into their branch as siblings land, and
    finish only once their dependencies are merged and their own tests pass against the real modules.
  - **1c:** `SHELL` merges last, after a final merge of `origin/cursor/ui-uplift` and a full gate run.
- **Waves 2 and 3:** any order (disjoint files).
- **Wave 4:** `QA` and `DOCS` in either order. The coordinator then fills Done / Deferred.

#### D14. Deferred by decision

| Item | Reason |
| --- | --- |
| Shared table on server-rendered viewer pages | Needs a Python-side renderer; the pages already pass the phone audit. |
| URL-addressed trace drawer | `trace-ui.js` is shared with the viewer; the drawer is transient. |
| Network entity page | Networks are configuration; a Settings row highlight plus device network tabs cover lookup. |
| Per-entity history tab | No per-entity history API; it would need server diff scanning. |
| Moving legacy rules out of `app.css` | Pure churn with regression risk; overrides suffice. |
| Assistant panel changes | Already full-screen on phones; no gap against the patterns. |
| Wizards for add-one flows other than share links | Add gear (`pickTemplate`) works and is tested in use; bulk add covers the "bulk beside single" rule. |
| Chart freshness shading | Fathom has no time-series charts. |

---

### B.2 Wave 1: shared primitives

All 11 wave-1 units start in parallel off `cursor/ui-uplift`, in the merge order of D13. In each section,
"Owns" lists every file the unit may create or edit.

#### ROUTER: `router-core.js` and `dom.js`

**Owns:** `fathom/static/js/router-core.js`, `fathom/static/js/dom.js`, `tests/js/router-core.test.mjs`,
`tests/_ui.py` (the shared headless-Chrome test helper specified in B.2 SHELL item 10; ROUTER creates it
so every other wave-1 unit can build its `tests/test_ui_<unit>.py` on it).
**Depends on:** nothing.

API (all pure):

```js
export const BP = { md: 700, lg: 1100 };
export function layoutFor(width) {}                 // 'sm' | 'md' | 'lg'
export const DEFAULT_VIEW = 'home';
export const VIEW_SHAPES = { devices: ['id', 'tab', 'sub'], rooms: ['id', 'tab'], racks: ['id', 'tab', 'sub'],
  plan: ['id'], schedules: ['tab'], imports: ['tab'], settings: ['tab'], discovery: ['tab', 'sub'], history: ['id'] };
export const SECTIONS = [ /* D2 table: {key, label, glyph, views, nav: 'all' | 'sm'} */ ];
export const VIEW_ROLES = {};                       // view -> 'viewer' | 'editor' | 'admin' (all 'viewer' now)
export const TAB_ROLES = { settings: { users: 'admin', backups: 'admin', sharing: 'editor' } };
export function canSee(view, role, tab) {}          // bool; role rank viewer < editor < admin
export function sectionOf(view) {}                  // section key; unknown views -> 'data'
export function sectionsFor(role) {}                // SECTIONS with views filtered, empty sections dropped
export function sectionRoot(key, route, role) {}    // route {project, room, view, query: {}}
export function parseRoute(hash) {}                 // {project, room, view, id, tab, sub, extra: [], query: {}}
export function buildRoute(route) {}                // '#/…'
export function withQuery(route, patch) {}          // new route; null or '' deletes a key
export function mergeRoute(route, partial) {}       // partial {view?, id?, tab?, sub?, room?, project?, query?}; changing view clears id/tab/sub unless given
export function sameRoute(a, b, ignoreKeys) {}      // bool
export function selToString(sel) {}                 // moved verbatim from app.js
export function selFromString(s) {}                 // moved verbatim from app.js
export function navMemory(storage) {}               // {remember(project, hash), target(project, key, route, role) -> hash, clear()}
export function legacyHash(project, room, view, params) {} // exactly today's buildHash output
```

`dom.js` (no top-level DOM access, so it imports in Node):

- `export function h(tag, attrs, children)` and `export function esc(s)`, copied verbatim from `app.js`.
- `export function on(target, type, fn, opts)`, which returns an `off()` function.

Tests (`router-core.test.mjs`), each a named `test()`:

1. **Round trips.** `buildRoute(parseRoute(x)) === x` for:
   - `#/campus/main/patch`
   - `#/campus/*/table`
   - `#/campus/main/patch?sel=device:foh-cl5`
   - `#/campus/main/patch?sel=port:rio-sl:analog-in-9`
   - `#/campus/main/plan?sel=marker:fp-main-floor:foh-cl5`
   - `#/campus/main/sop?page=power-up&edit=1`
   - `#/sunday-demo/main/patch?sel=device:atem-mini&filter=audio,video`
   - `#/campus/main/devices/foh-cl5/ports?sel=port:foh-cl5:omni-in-1&sec=ports`
   - `#/campus/main/schedules/cables?q=drum&sort=-length&f.state=planned|~&pg=2`
   - a project name with a space (`#/my%20show/main/patch`)
2. `legacyHash` equals the old `buildHash` for 10 vectors (copy them from the current implementation).
3. `parseRoute('')`, `parseRoute('#/campus')` and `parseRoute('#/campus/main/')` give view `''`. Callers
   map `''` to `DEFAULT_VIEW`.
4. Shapes:
   - `#/p/r/devices/x/ports/extra/more` gives `id x`, `tab ports`, `sub extra`, `extra ['more']`.
   - An unknown view keeps its segments in `extra`.
5. `selToString`/`selFromString` keep all existing vectors (copy them from `app.js` behaviour, including
   `device:x:port` → port).
6. `sectionsFor('viewer')` still includes all 8 sections. `canSee('settings', 'viewer', 'users')` is
   false; for `'editor'` with `'sharing'` it is true.
7. `navMemory`:
   - `target` returns the remembered hash for another section;
   - for the active section it returns the root;
   - it is per project;
   - it survives corrupt storage.
8. `layoutFor(699) === 'sm'`, `layoutFor(700) === 'md'`, `layoutFor(1099) === 'md'`,
   `layoutFor(1100) === 'lg'`.

**Acceptance:** all tests pass; `syntax.test.mjs` passes; no file outside "Owns" is touched.

#### SHELL: app shell (`app.js`, `app.css`, `app.html`)

**Owns:**

- `fathom/static/js/app.js`, `fathom/static/css/app.css`, `fathom/static/app.html`, `fathom/static/sw.js`
- stubs `fathom/static/js/page-device.js` and `fathom/static/js/page-room.js` (wave 1 only; `PDEV`/`PROOM`
  take them over in wave 2)
- placeholder CSS files (wave 1 only, each a one-line comment): `page-device.css`, `page-room.css`,
  `rack.css`, `inventory.css`, `schedules.css`, `admin.css`, `discovery.css`, `inspector.css`,
  `patchtable.css`
- `fathom/static/dev/plans/harness.js` (only if needed for new ctx logging)
- `tests/test_frontend_smoke.py`, `tests/test_ui_shell.py` (`tests/_ui.py` is created by ROUTER to the
  specification in item 10 below; SHELL reads it)

**Depends on:** ROUTER, DRAWER, SEARCH, FEEDBACK, HOME (merges last; codes against their contracts).

Changes:

1. **Layout** per D6 and D3. Header height 48px; `#app-views` 40px (md/lg); `#app-subnav` 36px, rendered
   only when the section has two or more permitted views; `#app-tabbar` 56px plus the safe-area inset
   (sm).
   - Section labels hide when they don't fit: measure like today's `fitTabs` and add `.app-views--icons`.
     `fitTabs` and the More menu are removed; their job is done by sections.
   - At sm the header shows room, search icon, bell, save dot and user. Undo, Redo, Helper and project
     switching move to the `#app-user` menu.
2. **Registry.** Add views to `VIEWS`:
   - `home` → `./home.js`, css `home.css`
   - `devices` → `./page-device.js`, css `['entity-header.css', 'datatable.css', 'explorer.css', 'page-device.css']`
   - `rooms` → `./page-room.js`, css `['entity-header.css', 'datatable.css', 'explorer.css', 'page-room.css']`

   `css` may be an array, and `ensureCss` resolves all of them. Final css arrays for existing views:
   - `table`: `['datatable.css', 'patchtable.css']`
   - `racks`: `['plan.css', 'explorer.css', 'entity-header.css', 'datatable.css', 'rack.css']`
   - `inventory`: `['plan.css', 'datatable.css', 'inventory.css']`
   - `schedules`: `['plan.css', 'datatable.css', 'schedules.css']`
   - `plan`: `['plan.css', 'explorer.css']`
   - `imports`, `history`, `builds`, `settings`: `['datatable.css', 'admin.css']`
   - `discovery`: `['datatable.css', 'discovery.css']`
   - at boot the shell loads `drawer.css`, `inspector.css`, `search.css` and `feedback.css`

   `DEFAULT_VIEW` becomes `home` (imported from router-core). `PHONE_TABS` and `TAB_ICONS` are replaced by
   `SECTIONS`. Wave-1 stubs for `page-device.js` and `page-room.js` export `mount(el, ctx)` rendering a
   heading and a plain link list. They must mount without errors, because the smoke test mounts every view.
3. **Router.**
   - `onHash` uses `parseRoute`. The room segment follows the existing rules; for `rooms/<id>` the store
     room is set to `<id>`.
   - Drawer per D4. Same-view changes per D1. `navMemory.remember` runs on every route.
   - `parseHash`, `buildHash`, `selToString` and `selFromString` stay exported. `buildHash` delegates to
     `legacyHash`.
   - `navigate(view, params)` keeps its signature and behaviour, so existing callers keep working.
4. **ctx additions** in `makeCtx`, with harness-safe defaults shown after `→`:

   | Member | Contract | `makeCtx` default |
   | --- | --- | --- |
   | `route` | Getter: the current parsed route (a copy) | → `{project: '', room: '', view: '', id: '', tab: '', sub: '', extra: [], query: {}}` |
   | `navigateRoute(partial, {replace})` | `mergeRoute` + write (push by default) | → no-op, returns `''` |
   | `routeHref(partial)` | `buildRoute(mergeRoute(route, partial))` for `<a href>` | → `'#'` |
   | `setParams(patch, {replace = true})` | Merge into query; `null` deletes | → no-op |
   | `openDrawer(sel, {section})` | D4 | → `ctx.openInspector(sel)` |
   | `closeDrawer()` | D4 | → `ctx.closeInspector(); store.select(null)` |
   | `layout()` | `layoutFor(innerWidth)` | → same |
   | `subscribe(type, fn)` | `type` ∈ `route`, `layout`, `problems`, `overlay`; returns `unsubscribe` | → returns a no-op |
   | `recent` | `{push(type, id), list(type) -> ids}` on `fathom.ui.recent.<project>` | → `{push() {}, list() { return []; }}` |
   | `notify({level, text, href})` | Adds a notice to the bell (FEEDBACK) | → `toast(text, level)` |
   | `sections` | `sectionsFor(role)` | → `SECTIONS` |
   | `projects` | `[{name, title}]` | → `[]` |
   | `setTitle(text)` | `document.title = text + ' · ' + project + ' · Fathom'` | → no-op |
   | `problems()` | Current problem list (`A.problems`) | → `[]` |
   | `overlayInfo()` | `{fetchedAt: ms or null, revision: number or null}` (recorded when the overlay response arrives; `revision` from the response) | → `{fetchedAt: null, revision: null}` |
   | `refreshOverlay()` | Refetch the overlay; returns a Promise | → `Promise.resolve()` |

   `openInspector` stays as an alias of `openDrawer`, and `closeInspector` of `closeDrawer`. The view
   handle may implement `route(r)` (D1).
5. **Search.** `#app-search` click and ⌘K call `openSearch(ctx)` from `search.js`; the old
   `openPalette`/`pick` code is removed. `pick` routing moves to `search-core.targetFor`.
6. **Bell.** `#app-notify` is `mountBell` from FEEDBACK. The shell calls `ctx.notify` on:
   - offline → online flush ("Saved 3 queued changes");
   - conflict;
   - the overlay finishing with import errors;
   - new problem reports since the last visit.

   It never toasts and notifies the same event twice.
7. **Selection bar** `#app-selbar` (D4): `span.app-selbar-title`, `button.app-selbar-open` "Details",
   `button.app-selbar-close[aria-label="Clear selection"]`. Height 48px; it sits above the tab bar at sm.
8. **Service worker.**
   - Bump `VERSION` to `0.4.0`.
   - Add to `PRECACHE`: every new file in this plan (`router-core.js`, `dom.js`, `explorer.js`,
     `explorer-core.js`, `entity-header.js`, `entity-core.js`, `datatable.js`, `datatable-core.js`,
     `drawer.js`, `drawer-core.js`, `search.js`, `search-core.js`, `home.js`, `home-core.js`,
     `feedback.js`, `feedback-core.js`, `wizard.js`, `wizard-core.js`, `page-device.js`, `page-room.js`,
     `page-rack.js`), every new CSS file, and the missing existing `views-discovery.js` and `merge-ui.js`.
   - `page-rack.js` is created by `RK` in wave 2. Precache entries are per-file try/catch, so a missing
     file in wave 1 does not break install.
9. **Edits to `tests/test_frontend_smoke.py`** (only this unit):
   - line 41 `VIEWS`: append `"home", "devices", "rooms"`;
   - line 44 `SHELL_IDS`: append `"app-banner", "app-subnav", "app-notify", "app-tabbar", "app-selbar"`;
   - `test_app_shell_dom_ids` (lines 571–579): logic unchanged (still finds `[data-view]` anywhere);
     update the message text to "§6.4: no [data-view=%s] control (section menu or subnav)";
   - `test_sop_viewer_on_a_phone` line 667 is unchanged: `#app-tabbar [data-tab=sop]` must exist.
10. **`tests/_ui.py`** (specification; the file itself is created by ROUTER):
    - `UiServer` (temp `FATHOM_DATA` holding the `sunday-demo` fixture and the `campus-demo` sample
      copied as in `FrontendSmoke.setUpClass`; threaded WSGI server; `.base`);
    - `SIZES = {'d': (1280, 900, False), 't': (820, 1180, True), 'm': (390, 844, True)}`;
    - `open(path, size)`, a context manager returning a `CDP` session (reuse `CDP`, `cdp_session` and
      `smoke_url` from `tests.test_frontend_smoke`; set device metrics and touch for `t` and `m`);
    - helpers `js`, `wait_for`, `click(selector)`, `press(key)`, `rect(selector)`,
      `page_hscroll() -> int` (`scrollWidth - innerWidth`), `offscreen(selector) -> int`, `reload()`;
    - `shot(name)`, which writes PNGs to `$FATHOM_UI_SHOTS/<name>.png` when that env var is set;
    - skip when `CHROME` is None.

Tests (`tests/test_ui_shell.py`), at d, t and m unless noted:

- At d and t, `#app-views` shows 7 visible section buttons (home is reached through `#app-home`). At m,
  `#app-tabbar button[data-tab]` has 8 entries, each ≥ 40px wide and with an `aria-label`, and
  `#app-views` is hidden.
- At d, `#app-views .app-sec .app-sec-label` is visible.
- Nav memory:
  1. visit `#/campus-demo/main/schedules`, then `#/campus-demo/main/patch`;
  2. click `[data-section=schedules]`: the hash is the schedules hash;
  3. click it again: the section root.
- `#app-banner` precedes `#app-top` in DOM order.
- `?sel=device:atem-mini` on `sunday-demo` opens the drawer at m and d (the text "ATEM Mini" is in
  `#app-inspector`).
- `#/sunday-demo/main/patch?sel=device:atem-mini&drawer=0` at m: `#app-selbar` is visible and the drawer
  is closed. Clicking "Details" opens the drawer and removes `drawer=0`.
- **No page horizontal scroll** at m and t on every `VIEWS` entry (`page_hscroll() <= 0`), for `campus-demo`.
- `⌘K` opens `#app-palette`; Esc closes it and returns focus to `#app-search`.
- The legacy URL `/?p=sunday-demo` lands on home.

**Acceptance:**

- The full gate passes: unittest (with `FATHOM_CHROME`), node tests and selftest.
- All smoke ids are present.
- Old `#/<p>/<room>/<view>?sel=` URLs still work (covered by the `test_ui_shell.py` cases above).
- Screenshots at 3 widths: `home`, `patch`, `schedules` (`$FATHOM_UI_SHOTS`).

#### EXPLORER: `explorer.js` + `explorer-core.js` + `explorer.css`

**Owns:**

- `fathom/static/js/explorer.js`, `fathom/static/js/explorer-core.js`, `fathom/static/css/explorer.css`
- `tests/js/explorer-core.test.mjs`
- `fathom/static/dev/explorer.html`, `fathom/static/dev/explorer-harness.js`, `tests/test_ui_explorer.py`

**Depends on:** ROUTER (`dom.js`, `layoutFor`).

API:

```js
import { mountExplorer } from './explorer.js';
const ex = mountExplorer(el, {
  key: 'devices',                  // storage key fathom.ui.explorer.devices
  title: 'Devices', glyph: '\u25EB',
  items: [],                       // [{id, label, sub, glyph, badge, group, href, depth}]
  chips: [{ key: 'audio', label: 'Audio', test: function (item) { return item.disc === 'audio'; } }],
  match: null,                     // optional (item, q) -> bool; default: label + sub, case-insensitive
  toolbar: [],                     // extra small buttons (Nodes)
  footer: function (shown, total) { return shown + ' of ' + total + ' devices'; },
  rail: [],                        // [{key, label, glyph, href, active}] shown when collapsed
  selected: null,                  // id
  onSelect: null,                  // default: location.hash = item.href
  mobileLabel: 'Devices',
});
ex.content;                        // HTMLElement: put the page here
ex.setItems(items); ex.setSelected(id); ex.open(); ex.close(); ex.isOpen();
ex.setCollapsed(bool); ex.setWidth(px); ex.destroy();
```

DOM: `div.ex-root[data-explorer=<key>]`, containing in order:

1. `aside.ex-side` holding:
   - `.ex-head` (title, `input.ex-search[type=search][aria-label]`, `.ex-chips` > `button.ex-chip[aria-pressed]`, `.ex-toolbar`)
   - `ul.ex-list[role=listbox][aria-label]` > `li.ex-group` headers and `li.ex-item[role=option][data-id][aria-selected]` > `a[href]`
   - `.ex-foot` (counts + `button.ex-collapse[aria-expanded]`)
2. `div.ex-resizer[role=separator][aria-orientation=vertical][aria-valuemin=240][aria-valuemax=480][aria-valuenow][tabindex=0]`
3. `section.ex-content`

At sm, `button.ex-open` ("☰ Devices (40)", ≥ 44px) is placed at the top of `.ex-content`.

Behaviour:

- Drag the resizer (pointer capture) or use the keyboard (←/→ 16px, Home/End). Width is clamped to
  240–480 and persisted on pointerup.
- Collapse leaves a 56px rail showing `rail` icons (links) plus an expand chevron, and persists `c`.
- ↑/↓/Home/End move within the list, Enter activates, and typing focuses search.
- At sm the sidebar is a fixed drawer (left, `width: 85vw; max-width: 24rem`) with a backdrop
  `.ex-backdrop`, a focus trap, and Esc to close. It auto-closes when `setSelected` changes the id and
  when `close()` is called (for example at drag start).
- `prefers-reduced-motion` disables the slide.

Core (`explorer-core.js`):

- `clampWidth(w)` → 240–480, default 300.
- `loadExplorer(storage, key)` and `saveExplorer(storage, key, state)`; default `{w: 300, c: false}`,
  tolerant of corrupt values.
- `filterItems(items, q, activeChipKeys, chips)`: chips are OR within the chip set, AND with `q`.
- `groupItems(items)` → `[{group, items}]` in first-seen order.
- `nextIndex(count, current, key)`.
- `explorerMode(width)` → `'drawer'` (< 700) or `'side'`.

Tests:

- **Core:** clamp bounds, load and save round trip, corrupt JSON, filter with chips and query, grouping,
  `nextIndex` wrap rules.
- **UI (harness):**
  - resize to 400 then reload: width is 400;
  - collapse then reload: still collapsed, rail visible;
  - at m, `.ex-open` opens the drawer, Esc closes it, `setSelected` closes it;
  - no page horizontal scroll at m.

**Acceptance:** tests pass; harness screenshots at 3 widths.

#### ENTITY: `entity-header.js` + `entity-core.js` + `entity-header.css`

**Owns:**

- `fathom/static/js/entity-header.js`, `fathom/static/js/entity-core.js`, `fathom/static/css/entity-header.css`
- `tests/js/entity-core.test.mjs`
- `fathom/static/dev/entity.html`, `fathom/static/dev/entity-harness.js`, `tests/test_ui_entity.py`

**Depends on:** ROUTER (`dom.js`).

API:

```js
import { mountEntityHeader } from './entity-header.js';
const eh = mountEntityHeader(el, {
  kind: 'device', id: 'foh-cl5', glyph: '\u25CF', title: 'FOH CL5', subtitle: 'Yamaha CL5',
  status: { label: 'Installed', level: 'ok' },          // level: ok | warn | err | muted
  facts: [{ label: 'Room', value: 'Main Auditorium', href: '#/…' }],
  badges: [{ label: '2 to review', level: 'warn', title: '…', onClick: fn }],
  actions: [{ key: 'edit', label: 'Edit', primary: true, run: fn }],   // rendered as buttons
  overflow: [{ key: 'delete', label: 'Delete', danger: true, run: fn }],
  tabs: [{ key: 'overview', label: 'Overview', count: null, href: '#/…' }],
  activeTab: 'overview',
  thumb: null,                                          // {src, alt, href} (room floor plan)
});
eh.update(partialOpts); eh.setTab(key); eh.destroy();
```

DOM: `header.eh[data-entity=<kind>][data-id]`, sticky at `top: 0` inside the view scroller, containing:

- `.eh-main` (glyph, `h1.eh-title`, `span.eh-status.eh-<level>`, `.eh-badges`)
- `dl.eh-facts` (`div` > `dt` + `dd`)
- `.eh-actions` (buttons + `button.eh-more[aria-haspopup=menu]` → `ul.eh-menu[role=menu]`)
- `.eh-thumb`
- `nav.eh-tabs[role=tablist]` > `a.eh-tab[role=tab][aria-selected][href][data-tab]`, with the count in
  `span.eh-count`

The compact variant `.eh--compact` applies when a sentinel above the header leaves the viewport
(IntersectionObserver) or at sm. It is one row of glyph, title (ellipsis), status and the ⋯ menu, with
the primary action moved into the menu at sm. At sm the facts sit in `details.eh-facts-more` and the tab
strip scrolls inside itself, scrolling the active tab into view. Tabs are real links (URL tabs);
←/→ moves between tabs.

Core (`entity-core.js`, pure, imports `model-core.js` helpers):

- `deviceFacts(doc, vocab, device, overlay)` → `[{key, label, value, href?}]`, in order: kind
  (discipline label + kind), status (`device.status`), room, rack · U, network (the `ip` of the interface
  with `role: 'primary'`, else the first interface with an `ip`, plus `device.dante_name` when set, e.g.
  `10.20.0.10 · FOH-CL5`), ports "n (m patched)". Facts with no value are omitted.
- `roomFacts(doc, room)` → venue, code, devices, racks, plans, cables.
- `rackFacts(doc, rack)` → room, height U, used U, free U, devices, location.
- `deviceTabs(doc, device)` → `['overview', 'ports', 'cables', 'network', 'dmx'?, 'channels'?, 'inventory', 'procedures', 'files']`.
  `dmx` appears only when the device has a DMX address or universe, and `channels` only when it has
  console channels.
- `roomTabs()`, `rackTabs()`.
- `resolveTab(tabs, requested)` → `{tab, redirect}`.
- `summaryCards(kind, doc, entity, ctxInfo)` → `[{key, label, count, sub, tab, drill: {title, kind, ids}}]`.
  `ctxInfo` = `{problems, pages}`.

Tests:

- **Core** on `fathom/static/dev/fixture-v2.json`: facts for `atem-mini` (order, omitted empties),
  `deviceTabs` with and without DMX or channels, `resolveTab` unknown → overview + redirect, room and
  rack facts, summary card counts match the doc.
- **UI (harness):**
  - the header stays visible after scrolling 2000px;
  - the compact class applies after scroll and at m;
  - clicking a tab changes `location.hash`;
  - the overflow menu opens with keyboard and closes on Esc;
  - targets ≥ 40px at m.

#### TABLE: `datatable.js` + `datatable-core.js` + `datatable.css`

**Owns:**

- `fathom/static/js/datatable.js`, `fathom/static/js/datatable-core.js`, `fathom/static/css/datatable.css`
- `tests/js/datatable-core.test.mjs`
- `fathom/static/dev/datatable.html`, `fathom/static/dev/datatable-harness.js`, `tests/test_ui_datatable.py`

**Depends on:** ROUTER (`dom.js`, `layoutFor`).

API:

```js
import { createTable, openTableDialog } from './datatable.js';
const t = createTable(host, {
  key: 'inventory',                         // stateKey
  scope: ctx.project,                       // storage scope
  caption: 'Inventory',                     // visually hidden <caption>
  columns: [{
    key: 'name', header: 'Name',
    value: function (row) { return row.name; },   // sort, search, filter, CSV default
    cell: null,                                   // (row) -> Node or string; default value
    csv: null,                                    // (row) -> string
    sortable: true, filterable: false, searchable: true,
    hideOnMobile: false, hidden: false,           // hidden = default visibility
    align: 'left', width: null, sticky: false,    // sticky: first column at sm
  }],
  rows: [],
  rowId: function (row) { return row.id; },
  onRow: null,                              // (row, event) on click or Enter (ignored on input/button/a/select/textarea/label)
  rowAttrs: null, rowClass: null,           // (row) -> {attr: value} / 'class names'
  groupBy: null,                            // (row) -> group label; renders tr.dt-group headers
  selectable: false,                        // checkbox column + bulk bar; off when ctx.store.readOnly
  bulkActions: [],                          // [{label, run(rows), danger, noun: {one, many}}]
  actions: [],                              // Nodes for the toolbar right slot
  ids: {},                                  // {root, table, search, csv, columns, selectAll, filters: {col: id}}
  url: null,                                // {get: () => query, set: (patch) => void} for the view's primary table only
  pageSizes: [25, 50, 100, 200], pageSize: 50, sticky: true, density: 'normal',
  empty: 'Nothing here yet.',               // string or (state) -> Node
  csvName: 'export.csv',
  highlight: null,                          // row id: jump to its page, add .dt-hl, scroll into view
  storage: null,                            // default window.localStorage
});
t.setRows(rows); t.setLoading(bool); t.setError(err, retryFn); t.setHighlight(id);
t.getState(); t.setState(partial); t.getSelection(); t.clearSelection(); t.refresh(); t.destroy();
openTableDialog(ctx, { title: '32 cables', columns, rows, onRow, key });  // searchable drill-down modal
```

DOM: `div.dt-root[data-table=<key>]`, containing:

- `.dt-toolbar`:
  - `input.dt-search[type=search][aria-label]`
  - `button.dt-filter[data-col][aria-haspopup=dialog]`, opening a popover with a checkbox list of
    distinct values, including "(empty)", plus a search box when there are more than 12 values
  - `details.dt-cols` (column checkboxes)
  - `button.dt-csv`
  - `.dt-actions`
- `.dt-bulk[hidden]` ("12 selected · actions · Clear")
- `.dt-scroll` > `table.dt-table`:
  - `thead`: `th[scope=col][aria-sort]` with a `button` for sortable columns
  - `tbody`: `tr[data-id][tabindex=0]`, with classes `.dt-hl`, `.dt-skel` (loading) and `.dt-group`
- `.dt-empty` (message + optional action)
- `.dt-error` (inline error + Retry)
- `.dt-pager` (prev/next, "51–100 of 240", page-size `select`)

Events dispatched on root: `dt:state` (`detail` = state), `dt:select` (`detail.ids`), `dt:row`
(`detail = {id, row}`).

Behaviour:

- Header click sorts asc → desc → none. Sorting is natural (numbers and tags like `A-010` after `A-002`)
  and stable.
- Search matches any visible searchable column, case-insensitive, with AND across tokens.
- Filters are OR within a column and AND across columns.
- "Select all" selects the **filtered** set across all pages and says so ("Select all 240 matching").
- CSV exports the filtered and sorted set (all pages), visible columns only, as RFC 4180 with CRLF.
  It is byte-compatible with `schedules.js` `csvString` (no BOM).
- State persists per D8 on every change. URL keys (`q`, `sort`, `f.*`, `pg`) are written only when `url`
  is given; URL beats storage on load.
- Below 700px, `hideOnMobile` columns are hidden (CSS class plus the column list).
- `sticky` keeps `thead` sticky.
- `density: 'compact'` reduces row padding. A density toggle sits in `.dt-cols`.
- `setLoading(true)` renders 8 skeleton rows of the visible columns.

Core (`datatable-core.js`, pure):

- `normalizeColumns(cols)`
- `applyState(rows, columns, state)` → `{rows, total, filtered, pageRows, page, pages}`
- `distinctValues(rows, column)` → sorted, with `''` reported as `(empty)`
- `matchesQuery(row, columns, q)`
- `compareValues(a, b)` (natural sort)
- `toCsv(columns, rows)`
- `stateToParams(state)` and `paramsToState(query, columns)` (D1 grammar, including `\` escapes and `~`)
- `loadState(storage, scope, key)` and `saveState(storage, scope, key, state)` (versioned; ignores unknown
  columns)
- `PAGE_SIZES`
- `selectAllFiltered(rows, columns, state)` → ids

Tests:

- **Core:**
  - sort natural and stable; `-col` parse;
  - filter with "(empty)";
  - search across columns;
  - pagination edges (last page clamps when filters shrink rows);
  - CSV escaping matches `csvString` on 5 vectors;
  - params round trip with `|`, `~` and `\` in values;
  - storage corrupt and version mismatch;
  - select-all limited to filtered rows.
- **UI (harness, 240 generated rows):**
  - type in search: count text updates;
  - sort by clicking a header: `aria-sort` changes;
  - filter popover lists "(empty)";
  - hide a column, reload: still hidden;
  - page size 25: 10 pages;
  - CSV link `href` is a blob holding exactly the filtered rows plus a header;
  - row Enter fires `dt:row`;
  - at m, `hideOnMobile` columns are not displayed and there is no page horizontal scroll;
  - all `th` have `scope`.

#### DRAWER: `drawer.js` + `drawer-core.js` + `drawer.css`

**Owns:**

- `fathom/static/js/drawer.js`, `fathom/static/js/drawer-core.js`, `fathom/static/css/drawer.css`
- `tests/js/drawer-core.test.mjs`
- `fathom/static/dev/drawer.html`, `fathom/static/dev/drawer-harness.js`, `tests/test_ui_drawer.py`

**Depends on:** ROUTER.

API:

```js
import { createDrawer } from './drawer.js';
const d = createDrawer(document.getElementById('app-inspector'), { label: 'Details', onClose: fn });
d.open(); d.close(); d.isOpen(); d.mode(); d.relayout(); d.destroy();   // the inspector renders into the host as today
```

Core (`drawer-core.js`):

- `drawerMode(width)` → `'docked'` (≥ 1100), `'sheet'` (700–1099) or `'full'` (< 700).
- `parseDrawer(query)` → `{sel, section, open}`, where `open = !!sel && query.drawer !== '0'`.
- `drawerParams({sel, section, open})` → query patch `{sel, sec, drawer}` (`drawer: '0'` only when
  `sel && !open`; `null` deletes).
- `topLayer(flags)`: given `{palette, dialog, trace, assistant, explorer, drawer}` booleans, returns the
  key that Esc closes, in D4 order.
- `CANVAS_VIEWS = ['patch', 'plan', 'map']`, plus `racks` when there is no id or the tab is `elevation`.
- `selectionOpensDrawer(view, route, layout, intent)` → bool (D4).

Behaviour:

- Mode classes `dr-docked`, `dr-sheet` and `dr-full` on the host.
- `role="complementary"` when docked; `role="dialog"` + `aria-modal="true"` + `aria-label` in sheet and
  full modes.
- `.dr-backdrop` in sheet and full modes.
- Focus moves into the drawer on open, is trapped while modal, and returns to the opener on close.
- `relayout()` runs on resize (the shell calls it on `layout` change).
- The full mode keeps the existing 88dvh bottom-sheet geometry and safe-area padding.

Tests:

- **Core:** mode thresholds; `parseDrawer`/`drawerParams` round trip; `topLayer` order;
  `selectionOpensDrawer` truth table for the patch, inventory and racks views at sm, md and lg, with and
  without intent.
- **UI (harness):** open at d has no backdrop, focus is not trapped; open at t and m traps focus, Esc
  closes, focus returns.

#### SEARCH: `search.js` + `search-core.js` + `search.css`

**Owns:**

- `fathom/static/js/search.js`, `fathom/static/js/search-core.js`, `fathom/static/css/search.css`
- `tests/js/search-core.test.mjs`
- `fathom/static/dev/search.html`, `fathom/static/dev/search-harness.js`, `tests/test_ui_search.py`

**Depends on:** ROUTER, SRV (soft: works without the `network` kind or `status` field).

API: `openSearch(ctx, {query, category})` and `closeSearch()`.

DOM, keeping the existing ids:

- `div#app-palette[role=dialog][aria-label="Search"]`: an anchored dropdown under `#app-search` at md/lg
  (`width: min(640px, 90vw)`); full screen at sm.
- `input#app-palette-input[role=combobox][aria-expanded][aria-controls=app-palette-list][aria-activedescendant]`
- `select#app-search-cat` (categories)
- `ul#app-palette-list[role=listbox]`, containing:
  - `li.sr-group[role=presentation]` headers;
  - `li.sr-hit[role=option][id=sr-hit-<n>][data-hit-kind][data-hit-id]`, each holding glyph,
    `.sr-title`, `.sr-sub` and `.sr-status`.
- Empty query: a "Recent" group (from `ctx.recent`) and a "Go to" group (sections).
- No results: "No matches for “x” in Cables." plus `button.sr-all` "Search all categories".

Keys: ↑/↓ (wrapping), Enter (go), Esc (close; focus returns to `#app-search`), Tab (to the category
select). Requests are debounced by 150 ms, as today. Online it calls
`api.search(project, q, {limit: 40, kinds})`; offline or on error it uses `augmentLocal`.

Core (`search-core.js`):

- `CATEGORIES = [all, devices, inventory, rooms, racks, ports, cables, networks, plans, procedures, files]`,
  each `{key, label, glyph, kinds}`:
  - `inventory.kinds = ['device']`
  - `networks.kinds = ['network', 'interface']`
- `categorize(hit)`: a device whose `match` is `serial` or `asset_tag` is `inventory`; otherwise the
  category by kind.
- `groupHits(hits, category)`: CATEGORIES order; max 6 per group in `all`, 50 in a single category.
  When the category is `inventory`, every device hit is shown as an inventory item.
- `kindsFor(category)`.
- `augmentLocal(doc, q, limit)`: `searchLocal` + network hits from `doc.networks` (fields `name`, `id`,
  `vlan`, `subnet`, `protocol`, the same as SRV) + `status` (`device.status`) on device hits. Same hit
  shape (§5.11).
- `mergeHits(a, b)` dedupes by `kind:id`.
- `roleFilter(hits, role)`: drops `page` hits with `status === 'draft'` for viewers.
- `targetFor(hit, route, doc)` → partial route:
  - device → `{view: 'devices', id, room: device.room || route.room}`
  - inventory → `{view: 'inventory', query: {sel: 'device:<id>', sec: 'inventory'}}`
  - port → `{view: 'devices', id: device, tab: 'ports', query: {sel: 'port:<dev>:<port>'}}`
  - cable → `{view: 'schedules', tab: 'cables', query: {sel: 'cable:<id>'}}`
  - interface → `{view: 'devices', id: device, tab: 'network', query: {hl: <interface id>}}`
  - network → `{view: 'settings', tab: 'networks', query: {hl: id}}`
  - room → `{view: 'rooms', id, room: id}`
  - rack → `{view: 'racks', id}`
  - floorplan → `{view: 'plan', id}`
  - attachment with a device → `{view: 'devices', id: device, tab: 'files', query: {hl: id}}`; without a
    device, today's `pick()` behaviour
  - page → `{view: 'sop', query: {page: id}}`
- `recentHits(doc, recent)`.
- `moveActive(count, index, delta)`.

On Enter the shell calls `ctx.recent.push` for device, room, rack and page hits.

Tests:

- **Core** (fixture + campus-like vectors):
  - `categorize` of a serial match is inventory;
  - `groupHits` order and caps;
  - `augmentLocal` finds a network by name and VLAN;
  - `targetFor` for every kind;
  - `roleFilter` drops drafts for viewers only;
  - `moveActive` wraps.
- **UI (harness with fixture doc, offline mode):**
  - "atem" → first option is the ATEM Mini device;
  - ↓ ↓ ↑ moves `aria-activedescendant`;
  - Enter reports the target route;
  - the category select narrows results;
  - Esc closes;
  - at m the palette is full-screen with no horizontal scroll.

The end-to-end search acceptance (device, room, cable tag `A-001`, inventory `RC-0001`) is in QA.

#### HOME: `home.js` + `home-core.js` + `home.css`

**Owns:** `fathom/static/js/home.js`, `fathom/static/js/home-core.js`, `fathom/static/css/home.css`,
`tests/js/home-core.test.mjs`, `tests/test_ui_home.py` (runs against the app after SHELL merges; before
that it skips when the `home` view is not registered).
**Depends on:** ROUTER, FEEDBACK (`emptyState`).

View `home`: `mount(el, ctx)`. Layout, top to bottom:

1. `h1.hm-title`: the project title.
2. `p.hm-lede`: "Fathom documents this venue's audio, video and lighting: what is installed, where it is,
   and how it is wired."
3. `section.hm-sections`: a grid of `a.hm-card[data-section]`, one per section from `ctx.sections` except
   home. Each card has a glyph, a name and one line:
   - Patch: "Wire devices port to port and trace signal paths."
   - Rooms: "Floor plans, racks and room overviews."
   - Devices: "Every device, its ports, network and inventory record."
   - Schedules: "Cable, IP, DMX and parts lists, and printable builds."
   - SOPs: "Step-by-step procedures for volunteers."
   - Data: "Imports, network discovery, history and raw JSON."
   - Settings: "Project, rooms, systems, networks, users and sharing."
4. `section.hm-rooms`: one `div.hm-room[data-room]` per room. Each shows the room name, counts
   ("40 devices · 70 cables") and link chips to Patch, Plan (when the room has plans), Racks (when it
   has racks), SOPs (when it has pages) and the room page. Rooms in recents come first.
5. `section.hm-recent`: a strip of up to 8 `a.hm-recent[data-type][data-id]` across types, newest first.
6. `section.hm-projects`: rendered when there is more than one project, or always at sm (the project
   select is hidden there).

Empty project: `emptyState({title: 'No rooms yet', text: 'Add a room in Settings ▸ Rooms, or import a
spreadsheet in Data ▸ Imports.', action})`. The action button is only for editors.

Core (`home-core.js`):

- `sectionCards(sections)`
- `roomCards(doc, recent, pages)` → `[{id, name, counts, links: [{key, label, view, id?}]}]`
- `recentStrip(doc, recent)` → merged by `t` desc, max 8, unknown ids dropped
- `projectCards(projects, current)`

Tests:

- **Core:** link chips depend on racks, plans and pages; recent ordering; dropped unknown ids.
- **UI:**
  - home at d, t and m has no horizontal scroll;
  - every card link resolves to a view that mounts;
  - at m the project cards render;
  - card targets ≥ 40px.

#### FEEDBACK: `feedback.js` + `feedback-core.js` + `feedback.css`

**Owns:**

- `fathom/static/js/feedback.js`, `fathom/static/js/feedback-core.js`, `fathom/static/css/feedback.css`
  (the shell loads it at boot)
- `tests/js/feedback-core.test.mjs`
- `fathom/static/dev/feedback.html`, `fathom/static/dev/feedback-harness.js`, `tests/test_ui_feedback.py`

**Depends on:** ROUTER (`dom.js`).

API (`feedback.js`):

- `skeleton(kind, n)` → Node. `kind` ∈ `table`, `cards`, `page`, `list`. The shapes match the content.
  `aria-busy="true"` goes on the container, and the skeleton is `aria-hidden`.
- `emptyState({title, text, action: {label, run} | null, secondary})` → `div.fb-empty`.
- `inlineError(err, retry, {compact})` → `div.fb-error[role=alert]`: the message (from `ApiError` when
  present) plus `button.fb-retry` "Retry".
- `confirmScope(ctx, {verb, count, noun: {one, many}, scope, danger, detail})` → `Promise<boolean>` via
  `ctx.confirm`, worded by `scopeText`, e.g. "Delete 12 cables in Main Auditorium?".
- `staleBadge({fetchedAt, fetchedRev, currentRev, onRefresh})` → `span.fb-stale` "Stale · updated 4 min
  ago" with a Refresh button. It updates every 30 s, is hidden when fresh, and announces through
  `#fathom-live` when it turns stale.
- `reviewBadge({count, label, onClick})` → `button.fb-review` "⚠ 3 to review". Not rendered when
  `count` is 0.
- `createNotices(storage, project)` → `{add(n), list(), unread(), markAllRead(), subscribe(fn)}`.
- `mountBell(button, countEl, notices, ctx)`: the badge count; the dropdown `ul.fb-notices[role=menu]`
  with links; "Mark all read"; `aria-label` "Notifications, 2 unread".

Core:

- `freshness(fetchedAt, now, fetchedRev, currentRev)` → `{stale, text, reason}`. It is stale when the
  revision differs (reason `revision`) or the age is over 15 min (reason `age`).
- `relTime(ms, now)` → "just now", "N min ago", "N h ago" or "N d ago".
- `scopeText({verb, count, noun, scope})`.
- `addNotice(list, n, now)` dedupes the same text within 60 s and caps at 50.

Tests:

- **Core:** freshness reasons; `relTime` boundaries; `scopeText` singular, plural and no-scope; notice
  dedupe and cap.
- **UI (harness):** the bell count updates; the menu is keyboard-operable; the stale badge appears when
  revisions differ; Retry calls back.

#### WIZARD: `wizard.js` + `wizard-core.js` + `wizard.css`

**Owns:**

- `fathom/static/js/wizard.js`, `fathom/static/js/wizard-core.js`, `fathom/static/css/wizard.css`
- `tests/js/wizard-core.test.mjs`
- `fathom/static/dev/wizard.html`, `fathom/static/dev/wizard-harness.js`, `tests/test_ui_wizard.py`

**Depends on:** ROUTER, TABLE (the preview step uses `createTable`), FEEDBACK.

API:

- `openWizard(ctx, {title, steps: [{key, label, render(body, data), validate(data) -> {field: msg}}], review(data) -> Node, submit(data) -> Promise<result>, result(res) -> {text, href, hrefLabel}})`
  → `Promise<result | null>`.
- `bulkAdd(ctx, {kind: 'devices' | 'cables', room})`. Steps:
  1. Paste (textarea; tab, comma or semicolon detected; or file input)
  2. Map columns (guessed)
  3. Preview (DataTable with a per-row error column; only valid rows are selectable)
  4. Review ("Add 18 devices to Main Auditorium")
  5. Result (link to the devices landing or schedules filtered to the new rows)

  It commits one `ctx.commit(ops, 'Bulk add 18 devices')`, so one undo step.
- `rememberForm(key, data)` and `recallForm(key)` on `fathom.ui.form.<key>`.

DOM: `div.wz[role=dialog][aria-modal=true][aria-labelledby]` > `ol.wz-steps` (`li[aria-current=step]`) +
`.wz-body` + `.wz-foot` (Back, Next or Submit; Next is disabled while there are errors, which show inline
under each field with `aria-describedby`). Full screen at sm.

Core:

- `parsePasted(text)` → `{delimiter, header, rows}`, quote-aware.
- `guessMapping(header, fields)`.
- `validateDeviceRow(doc, row)`: name required; room exists; status in vocab; no duplicate id.
- `validateCableRow(doc, row)`: both endpoints exist; port free unless `repatch`; `canConnect`.
- `bulkDeviceOps(doc, rows, {room})` and `bulkCableOps(doc, rows)`: built from model-core op builders
  (`connectOps`, and device add ops shaped like `duplicateDeviceOps` output).
- `canAdvance(step, errors)`.

The same validators back single add. `INV` and `SCH` call them.

Tests:

- **Core:** delimiter detection (tab, comma, semicolon, quoted commas); mapping guesses; device and cable
  validators on the fixture (unknown port, occupied port, bad room); ops apply cleanly with `applyOps`.
- **UI (harness):** the step list advances; Next stays disabled on errors; Back keeps data; Esc asks
  before discarding.

#### SRV: search server additions (see B.4)

**Owns:** `fathom/search.py`, `tests/test_search_kinds.py`.

---

### B.3 Wave 2: view migrations

Every wave-2 unit:

- consumes wave-1 primitives as merged on `cursor/ui-uplift`;
- keeps its view's ids (B.1.0) and its harness behaviour;
- verifies at d, t and m through its own `tests/test_ui_<unit>.py`;
- saves screenshots under `$FATHOM_UI_SHOTS/<unit>/` (the coordinator sets it to `/opt/cursor/artifacts/<unit>`);
- runs the full gate before opening its PR.

None edits `app.js`, `app.css`, `app.html`, `sw.js`, `router-core.js`, the primitives or
`tests/test_frontend_smoke.py`. A primitive bug goes in the PR description and is worked around locally;
the coordinator routes the fix.

#### PV: patch view (`patchview.js`, `patchview.css`)

**Owns:** `fathom/static/js/patchview.js`, `fathom/static/css/patchview.css`, `tests/test_ui_pv.py`.
`patchview-core.js` is not changed.

- **First commit: drag regression test.** On `/static/dev/patchview.html`, dispatch pointer events with
  CDP `Input.dispatchMouseEvent` from a free output port anchor to a compatible free input. Assert one
  more `path[data-cable]` and one more cable in the harness store. Repeat with
  `Input.dispatchTouchEvent` at m. This test must pass before and after the refactor.
- **Toolbar.** One row at md/lg:
  - `#pv-add`, `#pv-fit`, `#pv-zoom-out`, `#pv-zoom-in`, `#pv-undo`, `#pv-redo`, `#pv-filter-text`;
  - `button.pv-menu-view` "View ▾" holding `#pv-show-unconnected`, `#pv-show-routes`, `#pv-all-rooms`,
    `#pv-snap`, `#pv-filter-disc` (chips `[data-disc]`) and `#pv-filter-status`;
  - `button.pv-menu-arrange` "Arrange ▾" holding `#pv-arrange` and `#pv-save-arrangement`.

  At sm: `#pv-add`, `#pv-fit`, a search toggle that expands `#pv-filter-text`, and `button.pv-menu-more`
  "⋯" holding everything else. Menus are popovers whose content stays in the DOM (ids present), with
  `aria-haspopup`, `aria-expanded` and Esc to close.
- **URL.** `filter` (existing), `q` (text filter) and `status`, all with replaceState through
  `ctx.setParams`; read from `ctx.route.query` on mount and in `route(r)`.
- **Selection.** Unchanged (`ctx.select`); the shell applies D4. The context menu "Open details" calls
  `ctx.openDrawer(sel)`. A new item "Open device page" calls
  `ctx.navigateRoute({view: 'devices', id})`. "Show in rack" goes to
  `racks/<rack>/elevation?sel=device:<id>`. "Show on plan" goes to `plan/<fp>?sel=marker:<fp>:<id>`.
- **States.** Empty room: `emptyState` "No devices in Main Auditorium yet." with "Add gear" (editor).
- **Tests:** the drag test above; all `#pv-*` ids present; toolbar height ≤ 56px at d, t and m;
  `.pv-toolbar` has no inner horizontal scroll at m; reloading with `?q=cl5` restores the filter text;
  `test_aria_landmarks` still passes.

#### PT: patch table (`patchtable.js`, `patchtable.css`)

**Owns:** `fathom/static/js/patchtable.js`, `fathom/static/css/patchtable.css`, `tests/test_ui_pt.py`
(`patchtable-core.js` and its test only if needed).

- **Mode toggle** `#pt-mode`: `button[data-mode=blocks]` and `button[data-mode=rows]`, `aria-pressed`.
  URL `mode`. Default is `blocks` at md/lg and `rows` at sm; an explicit choice persists in the table
  state's `extra.mode`.
- **Rows mode.** `createTable` with key `patch-rows`. Columns, with `hideOnMobile` marked †:
  - Room†, Device, Port, Dir, Signal†
  - Connected device, Connected port, Cable tag, Medium†
  - Remove action (editor; `button.pt-remove[aria-label]`)

  Row click calls `ctx.openDrawer({type: 'port', id: device, device, port})`. Bulk "Remove patch"
  (selectable for editors) uses `confirmScope` ("Remove 6 patches in Main Auditorium?").
- **Blocks mode** is kept as is (`section.pt-block[data-device]`), with layout fixed so no "Remove patch"
  button is clipped at t or m.
- **Ids kept:** `#pt-filter-text` (DataTable search id in rows mode; the existing filter in blocks mode;
  one input), `#pt-filter-room`, `#pt-filter-disc`, `#pt-only-patched`, `#pt-show-overlay`, `#pt-csv`
  (DataTable CSV in rows mode, existing in blocks), `#pt-print`, `#pt-split`.
- **Tests:**
  - at t and m, `offscreen('.pt-block button')` is 0;
  - rows mode at m hides † columns and has no page horizontal scroll;
  - `?mode=rows&q=kick` survives reload;
  - a row click opens the drawer without the hash view changing;
  - the patch table harness still has `th[scope]` everywhere.

#### FP: floor plan (`floorplan.js`, `plan.css`)

**Owns:** `fathom/static/js/floorplan.js`, `fathom/static/css/plan.css`, `tests/test_ui_fp.py`
(`floorplan-core.js` and `tests/js/floorplan-core.test.mjs` only if needed).

- **Route** `plan/<fp>`. `#fp-select` stays and its change event navigates (push). A missing or unknown
  `<fp>` falls back to the room's first floor plan (replace).
- **Toolbar.** One row: `#fp-select`, `#fp-fit`, `#fp-zoom-*`, then `button.fp-menu-more` "⋯" holding
  `#fp-upload`, `#fp-calibrate`, `#fp-measure` and `#fp-layers` at md and sm (inline at lg when they fit).
- **Unplaced devices.** `#fp-unplaced` becomes an explorer:

  ```js
  const ex = mountExplorer(el, { key: 'plan-unplaced', title: 'Unplaced', items: unplaced, chips: disciplineChips,
    mobileLabel: 'Unplaced', onSelect: function (it) { ctx.select({ type: 'device', id: it.id }); } });
  // on pointerdown of a drag from ex: ex.close() so the drop lands on the canvas at sm
  ```

  The list keeps the id `fp-unplaced` on `ul.ex-list`, and drag from the list keeps working at every width.
- **Selection.** Markers use `ctx.select` (canvas: D4).
- **CSS ownership.** FP must not remove or rename `rk-`, `inv-` or `sch-` rules in `plan.css`.
- **Tests:**
  - `#/campus-demo/main/plan/fp-main-stage` reload gives `#fp-select` value `fp-main-stage`;
  - toolbar height ≤ 56px at d, t and m;
  - at m `.ex-open` opens the unplaced drawer;
  - no page horizontal scroll;
  - `.fp-viewport[role=application]` present;
  - the floor plan harness passes.

#### RK: racks (`rack.js`, new `page-rack.js`, new `rack.css`)

**Owns:** `fathom/static/js/rack.js`, `fathom/static/js/page-rack.js`, `fathom/static/css/rack.css`,
`tests/test_ui_rk.py` (`rack-core.js` and `tests/js/rack-core.test.mjs` only if needed).

- **Landing** `racks` (no id) keeps today's all-racks elevation and every `#rk-*` id. The rack harness
  (no route) is unchanged, so `test_rack_harness` passes. `#rk-unracked` becomes an explorer (key
  `racks-unracked`; drag closes it at sm, as in FP). `.rk-viewport` scales to the container width
  (no 420/390 overflow).
- **Rack page** `racks/<id>[/<tab>[/front or rear]]`, rendered by `page-rack.js`. `rack.js` delegates
  when `ctx.route.id` is set.

  ```js
  const ex = mountExplorer(el, { key: 'racks', title: 'Racks', items: racksByRoom, selected: id, mobileLabel: 'Racks' });
  const eh = mountEntityHeader(ex.content, { kind: 'rack', id, title: rack.name, facts: rackFacts(doc, rack),
    actions: [{ key: 'edit', label: 'Edit', primary: true, run: function () { ctx.openDrawer({ type: 'rack', id }); } },
              { key: 'print', label: 'Print', run: printRack }],
    overflow: [{ key: 'delete', label: 'Delete rack', danger: true, run: deleteWithScope }],
    tabs: rackTabs().map(function (k) { return { key: k, label: LABELS[k], href: ctx.routeHref({ view: 'racks', id, tab: k }) }; }),
    activeTab: tab });
  ```

  Tabs:
  - **overview**: `summaryCards` (Height / Used / Free U; Devices and Cables cards open `openTableDialog`;
    Problems).
  - **elevation**: the existing renderer for one rack, with sub `front` or `rear` as a segmented control.
    `.rk-block[data-device]` is kept; a block click calls `ctx.select` (canvas: D4).
  - **devices**: DataTable `rack.devices` with U, Device, Model†, Status, Depth†. Row → `openDrawer` device.
  - **cables**: DataTable `rack.cables` with cables touching rack devices. Row → `openDrawer` cable.

  On mount: `ctx.recent.push('rack', id)` and `ctx.setTitle(rack.name)`.
- **Tests:**
  - reload `racks/rk-foh/elevation/rear` lands on the rear face;
  - `racks/rk-foh/devices` row click opens the drawer and the hash keeps `racks/rk-foh/devices`;
  - the header is sticky after scroll;
  - explorer width persists;
  - no page horizontal scroll at m.

#### INV: inventory (`inventory.js`, new `inventory.css`)

**Owns:** `fathom/static/js/inventory.js`, `fathom/static/css/inventory.css`, `tests/test_ui_inv.py`.

- **DataTable** key `inventory`, primary (`url` bound), columns from `INV_COLUMNS` with
  `hideOnMobile` on everything except Name, Status and Room.

  ```js
  const t = createTable(host, { key: 'inventory', scope: ctx.project, url: urlBinding(ctx), selectable: !ctx.store.readOnly,
    columns: invColumns(ctx.vocab), rows: inventoryRows(ctx.store.doc, ctx.vocab), groupBy: S.group ? byLocation : null,
    ids: { table: 'inv-table', columns: 'inv-columns', csv: 'inv-csv', search: 'inv-filter', selectAll: 'inv-select-all',
           filters: { room: 'inv-room', status: 'inv-status', location: 'inv-location', kind: 'inv-kind', system: 'inv-system' } },
    bulkActions: [setStatus, setRoom, setLocation],   // existing #inv-bulk-* controls render in .dt-bulk
    onRow: function (row) { ctx.openDrawer({ type: 'device', id: row.id }, { section: 'inventory' }); } });
  ```

- **Ids and actions.**
  - `#inv-bulk-status`, `#inv-bulk-room` and `#inv-bulk-location` stay inside `.dt-bulk`; each uses
    `confirmScope` when more than one row is selected.
  - `#inv-q-warranty` and `#inv-q-serial` become quick-filter chips (URL `quick`). `#inv-group`
    toggles `groupBy`.
  - `#inv-dups`, `#inv-merge` and `#inv-mark-installed` stay in the actions slot.
  - The server export moves to "⋯ ▸ Export all (import format)" as `#inv-csv-all`.
  - Row action `button.inv-edit[data-device]` opens the existing `openForm(id)`. At sm the form is full
    width with no horizontal scroll.
  - "Bulk add" calls `bulkAdd(ctx, {kind: 'devices', room})`.
- **Tests:**
  - row click: the drawer opens with the inventory section expanded, the hash view stays `inventory`
    with `sel=device:…&sec=inventory`;
  - reload: the drawer is open at the same section;
  - search plus a status filter plus sort survive reload (URL) and a fresh visit (storage);
  - CSV has the filtered row count;
  - select-all selects only filtered rows;
  - at m there is no page horizontal scroll and all primary actions (search, filters, Bulk add) are
    within the viewport;
  - the schedules harness (which mounts inventory) passes.

#### SCH: schedules (`schedules.js`, new `schedules.css`)

**Owns:** `fathom/static/js/schedules.js`, `fathom/static/css/schedules.css`, `tests/test_ui_sch.py`.

- **Route** `schedules/<kind>`. The default `cables` is replaced into the URL. The legacy
  `schedules?sel=cable:x` lands on cables with the drawer open. Tabs `#sch-tab-<kind>` become
  `a[role=tab][href]` with the same ids.
- **One primary DataTable per kind** (key `schedules.<kind>`, columns from `COLUMNS[kind]`). Inline
  editors stay as cell renderers; row click ignores inputs.
  - Ids: search `sch-filter`, csv `sch-csv`. Filters `{room: 'sch-room', state: 'sch-state', disc: 'sch-disc'}`
    where the kind has that column; otherwise the control is not rendered.
  - Rows:
    - cables → `openDrawer({type: 'cable', id})`
    - ip → device drawer `sec: 'net'`
    - dmx → `sec: 'dmx'`
    - bom → `sec: 'inventory'`
    - patch → port drawer
    - racks → rack drawer
  - `#sch-assign-tags`, `#sch-tag-pattern`, `#sch-tag-scope`, `#sch-panel` and `#sch-print` are kept (the
    tag panel stays as it is).
  - `labels` stays a printable sheet (exempt).
  - "Bulk add cables" (cables tab, editor) calls `bulkAdd(ctx, {kind: 'cables', room})`.
- **Tests:**
  - reload `schedules/ip` lands on IP;
  - `schedules/cables?sel=cable:c-0001` opens the drawer showing c-0001, with the row `.dt-hl` and in view;
  - `q`, `sort` and `pg` survive reload;
  - CSV has the filtered rows;
  - at m, † columns are hidden, the first column is sticky and there is no page horizontal scroll;
  - the schedules harness passes.

#### ADM: imports, history, builds, settings (`views-admin.js`, new `admin.css`)

**Owns:** `fathom/static/js/views-admin.js`, `fathom/static/css/admin.css`, `tests/test_ui_adm.py`.

- **Imports.**
  - DataTables: `imports.registered`, `imports.errors`, and `imports.overlay` (rows keep class `ovl-row` and
    `data-device`; cells keep `.ms-suggest`, `.ms-conf`, `.ms-label`, `.ms-evidence` and
    `.disc-actions`). `?hl=<import id>` highlights.
  - The card grid becomes one column at sm (no 507/390 overflow).
  - `staleBadge` sits on the overlay table (`ctx.overlayInfo()` vs `ctx.store.revision`, Refresh calls
    `ctx.refreshOverlay`).
  - `reviewBadge` "N model suggestions" scrolls to the first `.ms-suggest`.
  - `test_model_suggestion_in_imports_overlay_on_a_phone` must pass unchanged.
- **History.** DataTable `history` (Rev, Time, User, Summary, Ops†). `history/<rev>` highlights the row;
  the existing time-travel action stays a row button. Empty: "No revisions yet. Every save creates one."
- **Builds.** DataTable `builds` (Run, Time, User, Outputs, Size†). Delete uses `confirmScope`. Download
  links are kept.
- **Settings.**
  - Route `settings/<tab>` with tabs project, rooms, systems, locations, networks, templates, users,
    backups, sharing, offline. Tabs are filtered with `canSee` (D2); a hidden tab in the URL falls back
    to `project`.
  - Lists become DataTables (`settings.<tab>`). Row click opens the existing edit dialog. `?hl=<id>`
    highlights (network search target).
  - "New share link" becomes `openWizard`: scope (project or SOP pages), expiry, review, then a result
    with the link and a QR (`api.qrUrl` / existing share QR).
- **Tests:**
  - reload `settings/networks?hl=av-dante` lands on the Networks tab with the row highlighted;
  - `history/1` highlights revision 1;
  - every list in imports, history, builds and settings is a `.dt-table`;
  - at m, imports has no inner horizontal scroll beyond `.dt-scroll`;
  - the share wizard steps advance;
  - a viewer-role run (second server with login, `tests/_ui.py` helper) shows no users, backups or sharing
    tabs.

#### DISC: discovery (`views-discovery.js`, new `discovery.css`)

**Owns:** `fathom/static/js/views-discovery.js`, `fathom/static/css/discovery.css`, `tests/test_ui_disc.py`.

- **Route** `discovery[/<tab>]?run=<rid>`. `<tab>` ∈ the findings tabs `new`, `matches`, `connections`,
  `networks`, `unresolved`, `changes`, plus `runs`. With no tab, the latest run's `new` tab shows (replace).
- **Layout.** Source cards collapse into `details.disc-sources` ("3 sources configured · Edit"; open by
  default only when no source is configured), so findings sit above the fold at m and t. Run controls
  stay at the top (editor).
- **Findings tables** are DataTables (`discovery.<tab>`). A row with a matched device opens
  `openDrawer({type: 'device', id})`; promote actions stay in their row (`.disc-actions`). Runs tab:
  DataTable `discovery.runs`; a row sets `run`. Freshness: `staleBadge` in age mode "Run 2 h ago".
  `reviewBadge` shows the unresolved count, linking to `discovery/unresolved`.
- **Tests (discovery fixtures as in `tests/test_discovery.py`, or a seeded finished run):**
  - reload `discovery/unresolved?run=<rid>` lands there;
  - findings are visible without scrolling at t;
  - every table is `.dt-table`;
  - no page horizontal scroll at m.

#### SOP: SOP wiki (`views-sop.js`, `sop.css`), light touch

**Owns:** `fathom/static/js/views-sop.js`, `fathom/static/css/sop.css`, `tests/test_ui_sop.py`.

- Keep the tree, the hash params and every class used by the three SOP phone tests.
- Replace the desktop placeholder "Pick a procedure on the left" with `div.sop-landing`: recently opened
  pages (`ctx.recent.list('page')`), pages due for review (`reviewState`) with `reviewBadge`, and pages
  per room.
- On page open: `ctx.recent.push('page', slug)` and `ctx.setTitle(title)`.
- `.sop-applies .chip[data-device]` calls `ctx.openDrawer({type: 'device', id}, {section: 'procedures'})`.
  `test_sop_viewer_on_a_phone` expects `#app-inspector [data-section=procedures] .ins-procs li`.
- Problem reports list → DataTable `sop.problems`.
- **Tests:** the desktop landing shows recents after opening `power-up`; the device chip opens the drawer
  with `sec=procedures` in the URL; the three SOP phone tests pass unchanged.

#### INS: inspector as drawer content (`inspector.js`, new `inspector.css`)

**Owns:** `fathom/static/js/inspector.js`, `fathom/static/css/inspector.css`, `tests/test_ui_ins.py`.

- **Header** `.ins-head`: kind glyph, title, `a.ins-open-page` "Open page" (device, rack and room →
  `ctx.routeHref`), and `button.ins-close[aria-label="Close details"]` calling `ctx.closeDrawer` (falling
  back to today's behaviour).
- **Section index.** A sticky `nav.ins-index` of chips for the sections present. A click calls
  `focusSection`.
- **Handle methods.** `focusSection(key)` opens `details[data-section=key]`, scrolls it into view and
  calls `ctx.setParams({sec: key})`. `sections()` returns the present keys. The shell calls
  `focusSection(route.query.sec)` after each render.
- **Port drawer order.** First a "Now connected" block: far-end device · port (link → port drawer), cable
  tag (link → cable drawer) and a Trace button (`trace-ui`). Then the existing fields.
- **Cable drawer.** Endpoints first (links to device pages and port drawers), then tag, signal, medium,
  length, state, then "Open in schedules" (`schedules/cables?sel=cable:<id>`).
- Every `data-section` key and `.ins-procs` is kept. "Show N more ports" wraps inside the drawer at m.
  Existing `ctx.navigate('patch' | 'racks')` calls switch to `ctx.navigateRoute` when it exists.
- **Tests:**
  - `?sel=device:foh-cl5&sec=inventory` opens with the inventory section expanded and in view;
  - the port drawer shows the far end first;
  - "Open page" goes to `devices/foh-cl5`;
  - at m, `offscreen('#app-inspector button')` is 0;
  - `test_deep_link_selection` passes.

#### PDEV: device landing and device page (`page-device.js`, `page-device.css`)

**Owns:** `fathom/static/js/page-device.js` and `fathom/static/css/page-device.css` (replacing the SHELL
stub and placeholder), `tests/test_ui_pdev.py`.

- **Landing** `devices`: DataTable `devices`, primary. Columns: Name, Kind, Model†, Room, Rack · U†,
  Status, IP†, Ports† ("48 / 32 patched"), and a `reviewBadge` cell for problems and duplicates.
  - Scoped to the room segment (`*` means all), with a Room filter. A row click navigates to
    `devices/<id>` (D4: landing rows navigate).
  - Actions (editor): "Add device" (existing `ctx.pickTemplate` flow, prefilled with the current room)
    and "Bulk add" (`bulkAdd`).
- **Page** `devices/<id>[/<tab>[/<sub>]]`:

  ```js
  const ex = mountExplorer(el, { key: 'devices', title: 'Devices', items: devicesInRoom, chips: disciplineChips,
    selected: id, footer: countsFooter, rail: tabRail, mobileLabel: 'Devices' });
  const eh = mountEntityHeader(ex.content, { kind: 'device', id, title: d.name, subtitle: model, status: statusOf(d),
    facts: deviceFacts(doc, ctx.vocab, d, overlay), badges: reviewBadges,
    actions: [edit /* openDrawer device */, showInPatch, trace /* trace-ui */, publicPage /* /p/<project>/d/<id> */],
    overflow: [duplicate /* duplicateDeviceOps */, merge /* merge-ui */, qr /* api.qrUrl */, del /* confirmScope + deleteDeviceOps */],
    tabs: tabsFor(deviceTabs(doc, d)), activeTab: resolveTab(deviceTabs(doc, d), route.tab).tab });
  ```

  Tabs:
  - **overview**: `summaryCards`. Counts open `openTableDialog` (e.g. "32 cables"). Notes.
  - **ports**: DataTable `device.ports` with Port, Label, Dir, Signal†, Connector†, Connected to (device ·
    port link), Cable tag. Row → `openDrawer({type: 'port', …})`.
  - **cables**: DataTable `device.cables`. Row → cable drawer.
  - **network**: DataTable `device.net` (interfaces: IP, MAC, Hostname, Role, Network, Switch port†);
    `?hl=<iface>` highlights. Row → device drawer `sec: 'net'`.
  - **dmx**: DataTable `device.dmx`. Row → device drawer `sec: 'dmx'`.
  - **channels**: DataTable `device.channels`. Row → `openDrawer({type: 'channel', …})`.
  - **inventory**: facts (serial, asset tag, purchase, warranty, location, status) plus "Edit" → drawer
    `sec: 'inventory'`.
  - **procedures**: DataTable of `pagesForDevice` (imported from `views-sop.js`). Row → `sop?page=`.
  - **files**: DataTable of attachments. Row → file link.

  Unknown id or tab per D5. On mount: `ctx.recent.push('device', id)` and `ctx.setTitle(d.name)`.
- **Tests:**
  - reload `devices/foh-cl5/ports` lands on Ports;
  - a port row opens the drawer and the hash keeps `devices/foh-cl5/ports` plus `sel`;
  - reload keeps the drawer open;
  - the header is sticky after scrolling 1500px;
  - explorer width persists across reload;
  - at m the explorer is behind `.ex-open`, the header is compact and there is no page horizontal scroll;
  - Delete is in the overflow and asks with scope.

#### PROOM: room landing and room page (`page-room.js`, `page-room.css`)

**Owns:** `fathom/static/js/page-room.js` and `fathom/static/css/page-room.css` (replacing the stubs),
`tests/test_ui_proom.py`.

- **Landing** `rooms`: DataTable `rooms` (Name, Code†, Devices, Cables, Racks†, Plans†, Procedures†). A row
  navigates to `rooms/<id>` with the room segment set to `<id>`.
- **Page** `rooms/<id>[/<tab>]`: explorer (key `rooms`, grouped by venue when present) plus an entity
  header with `roomFacts` and a thumbnail of the room's first floor plan (`api.floorplanImageUrl`, linking
  to `plan/<fp>`).
  - Actions: Patch, Plan, Racks and SOPs for this room (links), and Edit (room settings dialog via
    `settings/rooms?hl=<id>`).

  Tabs:
  - **overview**: summary cards, with drill-downs via `openTableDialog`.
  - **devices**: DataTable `room.devices`. Row → device drawer, whose "Open page" link leads to the page.
  - **cables**: row → cable drawer.
  - **racks**: row → rack drawer.
  - **plans**: row → `plan/<fp>`.
  - **procedures**: row → `sop?page=`.

  On mount: `ctx.recent.push('room', id)`.
- **Tests:** reload `rooms/chapel/cables` lands on Cables with the room select showing Chapel; a cable row
  opens the drawer without navigation; sticky header; no page horizontal scroll at m.

---

### B.4 Server work

Single owner: **SRV** (wave 1). No new HTTP routes, so `SPEC_ROLES` and `PARAM_HINTS` in
`tests/test_security.py` are unchanged; the OpenAPI test is unaffected.

`fathom/search.py`:

1. Add `network` to `KIND_ORDER` after `interface`. In `build_index`, index `doc.networks[]` as kind
   `network`: id, title = `name` or id, subtitle `"VLAN <vlan> · <subnet>"`, and fields `name`, `id`,
   `vlan`, `subnet`, `protocol` (as in campus-demo `av-dante`:
   `{name: 'Dante primary', vlan: 20, subnet: '10.20.0.0/24', protocol: 'dante'}`).
2. Add `status` to every returned hit: devices → `device.status` (`''` when unset); pages → `page.status`
   (`draft` or `published`, the field `_add_pages` already reads); other kinds → `''`.
3. `kinds=network` filtering works through the existing `kinds` parameter.

New test file `tests/test_search_kinds.py` (does not touch `test_api.py`):

- `av-dante` (campus-demo) is found by name and by VLAN;
- device hits carry `status`;
- page hits carry `draft` for a draft page;
- `kinds=network` returns only networks;
- the existing ranking is unchanged for `atem` (first is ATEM Mini).

`model-core.searchLocal` is not changed; `search-core.augmentLocal` adds networks and status on the client.

---

### B.5 Wave 3: states and feedback sweep

Same file owners as wave 2, grouped into 5 units so ownership stays disjoint. Each unit adds a new test
file `tests/test_ui_states_<group>.py`. The checklist per view:

1. A **skeleton** in the shape of the content while data loads (`skeleton(kind)`).
2. **Empty copy** that says why and what creates content.
3. An **inline error** with Retry beside the failing thing (no toast-only failures).
4. **confirmScope** on every delete, bulk write and long-running action.
5. A **freshness** badge where data is derived or remote.
6. **Review badges** where records need a human.

| Unit | Owns | Views: required states |
| --- | --- | --- |
| ST-CANVAS | `patchview.js`, `patchview.css`, `patchtable.js`, `patchtable.css`, `floorplan.js`, `plan.css`, `rack.js`, `page-rack.js`, `rack.css` | Patch: empty room ("No devices in <room> yet." + Add gear); overlay stale badge on overlay routes; delete device confirmScope with cable count. Patch table: empty ("No ports match these filters." + Clear filters). Plan: no plans ("No floor plan for <room>. Upload a PDF, SVG or image." + Upload); image load error inline + Retry. Racks: none ("No racks in <room>." + Add rack); rack delete confirmScope ("Delete FOH rack? 6 devices become unracked."). |
| ST-LISTS | `inventory.js`, `inventory.css`, `schedules.js`, `schedules.css` | Inventory: skeleton until the doc is ready; empty ("No devices in <room>. Add gear in Patch or bulk add from a spreadsheet."); bulk edit confirmScope; review badge for duplicates (`#inv-dups`). Schedules: skeleton while a server schedule loads; error inline + Retry; empty per kind ("No IP addresses recorded yet. Add interfaces in a device's Network tab."); tag assignment confirmScope ("Assign tags to 42 untagged cables in Main Auditorium?"). |
| ST-ADMIN | `views-admin.js`, `admin.css`, `views-discovery.js`, `discovery.css` | Imports: skeleton; errors inline; overlay stale badge; delete import confirmScope. History: skeleton; empty copy; restore confirmScope ("Restore revision 12? This creates revision 43."). Builds: skeleton; empty ("No builds yet. Build creates the PDF/HTML pack."); delete confirmScope. Settings: user, share and backup deletes confirmScope; backup restore confirmScope. Discovery: skeleton per tab; run age badge; unresolved review badge; promote confirmScope for more than one finding. |
| ST-ENTITY | `page-device.js`, `page-device.css`, `page-room.js`, `page-room.css`, `inspector.js`, `inspector.css` | Device and room pages: skeleton on first render (`skeleton('page')`); empty per tab ("No cables connected to FOH CL5." + Open in patch view); not-found inline error. Inspector: review badge in the header for `dups` and `problems`, jumping to the section. |
| ST-SHELL | `app.js`, `app.css`, `home.js`, `home.css`, `views-sop.js`, `sop.css` | Shell: replace "Loading X…" with `skeleton` per view kind; the view error card stays; bell notices (D6 events). Home: skeleton while projects load; empty project copy. SOP: problem report list empty copy; landing empty ("No procedures yet." + New page for editors). |

Acceptance for each ST unit:

- Each listed state is reachable in its test, forced by fixtures or by stubbing `ctx.api` to reject
  through `tests/_ui.py` request interception (`Fetch.enable` in CDP).
- Text matches the copy above (exact wording may improve; the meaning must hold).
- No page horizontal scroll at m.

---

### B.6 Docs

Single unit **DOCS** in wave 4. **Owns:** `docs/SPEC.md`, `AGENTS.md`, `README.md` (Development section).

1. **SPEC §6.4.**
   - New registry rows (`home`, `devices`, `rooms`) and css arrays.
   - The new shell DOM order and ids (`#app-banner` above, `#app-home`, `#app-subnav`, `#app-notify`,
     `#app-selbar`, `#app-tabbar` sections).
   - ctx members (B.2 SHELL table) and the handle method `route(r)`.
   - Router: the D1 grammar, shapes table, query keys, and history rules; DEFAULT `home`.
2. **New §6.13 "Shared UI components":** one subsection each for router-core, explorer, entity-header,
   datatable, drawer, search, home, feedback and wizard, carrying the API blocks from B.2 verbatim as
   merged (update to match the code).
3. **§6.5–6.7.** Moved ids and element-type changes (`#inv-room` etc. are now DataTable filter buttons;
   `#sch-tab-*` are links; `#pt-mode`; `#inv-csv-all`; `#fp-unplaced` on the explorer list).
4. **§6.8.** Inspector header, section index, `focusSection`, port and cable drawer order.
5. **§6.10.** The precache list and `VERSION 0.4.0`.
6. **§5.11.** `network` kind and `status` field. **FR-SRCH-01/02/04:** network kind, categories,
   inventory category, recents, and the kind order with `network`.
7. **FR-MOB-01.** Named breakpoints and the tab bar of sections.
8. **New FR rows** in §3.28: FR-UX-09 sections and nav memory; FR-UX-10 entity pages and URL tabs;
   FR-UX-11 shared DataTable and state persistence; FR-UX-12 drawer URL state; FR-UX-13 home launchpad;
   FR-UX-14 feedback states. Each gets a matching §9 acceptance checklist row pointing at its
   `tests/test_ui_*.py`.
9. A **storage keys** table (D8).
10. **AGENTS.md:**
    - a "Frontend conventions" bullet list: shared components and where they live; `dom.js` for helpers;
      the D1 route grammar in one line; storage key prefix `fathom.ui.`; breakpoints sm/md/lg; "every list
      uses `datatable.js`" with the exemption list; how to run `tests/test_ui_*.py`
      (`FATHOM_UI_SHOTS` for screenshots);
    - update the test count in Cursor Cloud instructions once QA reports it.
11. **README Development:** module map rows for the new files.

**Acceptance:** every new route shape, storage key, component and ctx member in the merged code appears
in SPEC. `QA` cross-checks by grepping `fathom.ui.` and `export function` in new files against SPEC.

---

### B.7 Dependency graph, waves and file ownership

```
Wave 1 (parallel; merge order per D13)
  ROUTER ──┬─> EXPLORER ─┐
           ├─> ENTITY ───┤
           ├─> TABLE ────┼─> WIZARD (uses TABLE at runtime; codes to the contract)
           ├─> DRAWER ───┤
           ├─> SEARCH <──┼── SRV (soft)
           ├─> FEEDBACK ─┼─> HOME
           └─────────────┴─> SHELL (merges last; integrates DRAWER, SEARCH, FEEDBACK, HOME)
Wave 2 (parallel, after all of wave 1 merged)
  PV  PT  FP  RK  INV  SCH  ADM  DISC  SOP  INS  PDEV  PROOM
  (INV and SCH use WIZARD; RK, PDEV, PROOM use EXPLORER + ENTITY + TABLE; all use DRAWER via ctx)
Wave 3 (parallel, after wave 2)
  ST-CANVAS  ST-LISTS  ST-ADMIN  ST-ENTITY  ST-SHELL
Wave 4 (parallel)
  DOCS  QA
```

Worker counts: wave 1 has 11 units (up to 19 workers with the test-first split below), wave 2 has 12,
wave 3 has 5, wave 4 has 2.

**Priority (impact ÷ effort).** Waves enforce dependencies (shell and primitives before views). Within a
wave all units run in parallel. If fewer workers are available, start them in this order:

- Wave 1: ROUTER, SHELL, TABLE, DRAWER, SEARCH, SRV, ENTITY, EXPLORER, FEEDBACK, HOME, WIZARD.
- Wave 2: INV, SCH, INS, PDEV, PV, PT, RK, PROOM, ADM, FP, DISC, SOP.
- Wave 3: ST-LISTS, ST-ENTITY, ST-CANVAS, ST-ADMIN, ST-SHELL.

**Test-first workers (wave 1).** For each `*-core.js` contract, a separate test-first worker writes a
**contract test** from this document alone (never from the implementation) into
`tests/js/<name>-contract.test.mjs`. The implementing unit keeps writing its own
`tests/js/<name>-core.test.mjs`. The two files have different owners and never collide; a contract test
that fails after the implementation lands means either the code or the contract drifted, and the
coordinator decides which one is fixed (the document wins unless it is wrong).

| Test-first worker | Owns |
| --- | --- |
| T-ROUTER | `tests/js/router-contract.test.mjs` |
| T-EXPLORER | `tests/js/explorer-contract.test.mjs` |
| T-ENTITY | `tests/js/entity-contract.test.mjs` |
| T-TABLE | `tests/js/datatable-contract.test.mjs` |
| T-DRAWER | `tests/js/drawer-contract.test.mjs` |
| T-SEARCH | `tests/js/search-contract.test.mjs` |
| T-HOME | `tests/js/home-contract.test.mjs` |
| T-FEEDBACK | `tests/js/feedback-contract.test.mjs` |
| T-WIZARD | `tests/js/wizard-contract.test.mjs` |

Contract tests are merged only after the module they import has merged. Exactly one owner per file.

**File ownership matrix.** One owner per file per wave; "—" means untouched in that wave. All paths are
under `fathom/static/` unless they start with `tests/`, `docs/`, `fathom/` or are root files.

| File | Wave 1 | Wave 2 | Wave 3 | Wave 4 |
| --- | --- | --- | --- | --- |
| `js/router-core.js`, `js/dom.js` | ROUTER | — | — | — |
| `tests/js/router-core.test.mjs` | ROUTER | — | — | — |
| `tests/js/<name>-contract.test.mjs` (nine files) | T-<NAME> | — | — | — |
| `js/app.js`, `css/app.css`, `app.html`, `sw.js` | SHELL | — | ST-SHELL (`app.js`, `app.css` only) | — |
| `dev/plans/harness.js` | SHELL | — | — | — |
| `tests/_ui.py` | ROUTER | — | — | — |
| `tests/test_frontend_smoke.py`, `tests/test_ui_shell.py` | SHELL | — | — | — |
| `js/explorer.js`, `js/explorer-core.js`, `css/explorer.css`, `dev/explorer.html`, `dev/explorer-harness.js`, `tests/test_ui_explorer.py` | EXPLORER | — | — | — |
| `tests/js/explorer-core.test.mjs` | EXPLORER | — | — | — |
| `js/entity-header.js`, `js/entity-core.js`, `css/entity-header.css`, `dev/entity.html`, `dev/entity-harness.js`, `tests/test_ui_entity.py` | ENTITY | — | — | — |
| `tests/js/entity-core.test.mjs` | ENTITY | — | — | — |
| `js/datatable.js`, `js/datatable-core.js`, `css/datatable.css`, `dev/datatable.html`, `dev/datatable-harness.js`, `tests/test_ui_datatable.py` | TABLE | — | — | — |
| `tests/js/datatable-core.test.mjs` | TABLE | — | — | — |
| `js/drawer.js`, `js/drawer-core.js`, `css/drawer.css`, `dev/drawer.html`, `dev/drawer-harness.js`, `tests/test_ui_drawer.py` | DRAWER | — | — | — |
| `tests/js/drawer-core.test.mjs` | DRAWER | — | — | — |
| `js/search.js`, `js/search-core.js`, `css/search.css`, `dev/search.html`, `dev/search-harness.js`, `tests/test_ui_search.py` | SEARCH | — | — | — |
| `tests/js/search-core.test.mjs` | SEARCH | — | — | — |
| `js/home.js`, `js/home-core.js`, `css/home.css` | HOME | — | ST-SHELL (`home.js`, `home.css`) | — |
| `tests/test_ui_home.py` | HOME | — | — | — |
| `tests/js/home-core.test.mjs` | HOME | — | — | — |
| `js/feedback.js`, `js/feedback-core.js`, `css/feedback.css`, `dev/feedback.html`, `dev/feedback-harness.js`, `tests/test_ui_feedback.py` | FEEDBACK | — | — | — |
| `tests/js/feedback-core.test.mjs` | FEEDBACK | — | — | — |
| `js/wizard.js`, `js/wizard-core.js`, `css/wizard.css`, `dev/wizard.html`, `dev/wizard-harness.js`, `tests/test_ui_wizard.py` | WIZARD | — | — | — |
| `tests/js/wizard-core.test.mjs` | WIZARD | — | — | — |
| `fathom/search.py`, `tests/test_search_kinds.py` | SRV | — | — | — |
| `js/patchview.js`, `css/patchview.css` | — | PV | ST-CANVAS | — |
| `tests/test_ui_pv.py` | — | PV | — | — |
| `js/patchtable.js` | — | PT | ST-CANVAS | — |
| `css/patchtable.css` | SHELL (placeholder) | PT | ST-CANVAS | — |
| `js/patchtable-core.js`, `tests/js/patchtable-core.test.mjs`, `tests/test_ui_pt.py` | — | PT | — | — |
| `js/floorplan.js`, `css/plan.css` | — | FP | ST-CANVAS | — |
| `js/floorplan-core.js`, `tests/js/floorplan-core.test.mjs`, `tests/test_ui_fp.py` | — | FP | — | — |
| `js/rack.js`, `js/page-rack.js` | — | RK | ST-CANVAS | — |
| `css/rack.css` | SHELL (placeholder) | RK | ST-CANVAS | — |
| `js/rack-core.js`, `tests/js/rack-core.test.mjs`, `tests/test_ui_rk.py` | — | RK | — | — |
| `js/inventory.js` | — | INV | ST-LISTS | — |
| `css/inventory.css` | SHELL (placeholder) | INV | ST-LISTS | — |
| `tests/test_ui_inv.py` | — | INV | — | — |
| `js/schedules.js` | — | SCH | ST-LISTS | — |
| `css/schedules.css` | SHELL (placeholder) | SCH | ST-LISTS | — |
| `tests/test_ui_sch.py` | — | SCH | — | — |
| `js/views-admin.js` | — | ADM | ST-ADMIN | — |
| `css/admin.css` | SHELL (placeholder) | ADM | ST-ADMIN | — |
| `tests/test_ui_adm.py` | — | ADM | — | — |
| `js/views-discovery.js` | — | DISC | ST-ADMIN | — |
| `css/discovery.css` | SHELL (placeholder) | DISC | ST-ADMIN | — |
| `tests/test_ui_disc.py` | — | DISC | — | — |
| `js/views-sop.js`, `css/sop.css` | — | SOP | ST-SHELL | — |
| `tests/test_ui_sop.py` | — | SOP | — | — |
| `js/inspector.js` | — | INS | ST-ENTITY | — |
| `css/inspector.css` | SHELL (placeholder) | INS | ST-ENTITY | — |
| `tests/test_ui_ins.py` | — | INS | — | — |
| `js/page-device.js`, `css/page-device.css` | SHELL (stub, placeholder) | PDEV | ST-ENTITY | — |
| `tests/test_ui_pdev.py` | — | PDEV | — | — |
| `js/page-room.js`, `css/page-room.css` | SHELL (stub, placeholder) | PROOM | ST-ENTITY | — |
| `tests/test_ui_proom.py` | — | PROOM | — | — |
| `tests/test_ui_states_canvas.py`, `tests/test_ui_states_lists.py`, `tests/test_ui_states_admin.py`, `tests/test_ui_states_entity.py`, `tests/test_ui_states_shell.py` | — | — | ST-CANVAS, ST-LISTS, ST-ADMIN, ST-ENTITY, ST-SHELL (one each) | — |
| `docs/SPEC.md`, `AGENTS.md`, `README.md` | — | — | — | DOCS |
| `tests/test_ui_acceptance.py` | — | — | — | QA |
| `docs/ui-audit.md` | this PR | — | — | coordinator (Done / Deferred) |
| `js/assistant-ui.js`, `js/merge-ui.js`, `js/trace-ui.js`, `js/suggest-ui.js`, `js/api.js`, `js/model-core.js`, `css/trace.css`, `fathom/render_html.py`, `fathom/server.py`, `tests/test_security.py`, `tests/test_api.py` | — | — | — | — |

Wave-2 units import (read) primitives and `views-sop.js` (PDEV imports `pagesForDevice`) but never edit
them. `QA` edits only its own test file and reports defects to the coordinator.

---

### B.8 Verification matrix

**QA** (wave 4) owns `tests/test_ui_acceptance.py`, a single end-to-end file run by the normal
unittest gate. It also does a manual pass at d, t and m with screenshots in
`/opt/cursor/artifacts/qa/`, plus a short report in the PR description.

| Owner acceptance criterion | Units | Verified by |
| --- | --- | --- |
| unittest, node tests and `fathom selftest` pass | all | CI (`.github/workflows/ci.yml`) and each unit's gate run before its PR |
| Every list uses the shared table with search, sort, filter, pagination, column toggle, CSV and persisted state | TABLE, INV, SCH, PT, ADM, DISC, SOP, RK, PDEV, PROOM | `tests/js/datatable-core.test.mjs`; `tests/test_ui_datatable.py`; per-view `tests/test_ui_{inv,sch,pt,adm,disc,rk,pdev,proom}.py`; `test_ui_acceptance.py::test_every_list_is_a_datatable` (each view at d: `table:not(.dt-table)` outside the D9 exemptions is empty) |
| Device, room and rack pages have a sticky header and URL tabs; reload lands on the same tab | ENTITY, PDEV, PROOM, RK, ROUTER, SHELL | `tests/js/entity-core.test.mjs`, `tests/js/router-core.test.mjs`; `tests/test_ui_{entity,pdev,proom,rk}.py`; `test_ui_acceptance.py::test_entity_tabs_survive_reload` (`devices/foh-cl5/ports`, `rooms/chapel/cables`, `racks/rk-foh/elevation/rear`) |
| Port, cable and inventory row clicks open a drawer without navigation; drawer state is in the URL and survives reload | DRAWER, SHELL, INS, INV, SCH, PDEV, PT | `tests/js/drawer-core.test.mjs`; `tests/test_ui_{drawer,ins,inv,sch,pdev,pt}.py`; `test_ui_acceptance.py::test_row_click_opens_drawer_in_place` (port row on `devices/foh-cl5/ports`, cable row on `schedules/cables`, inventory row: view segment unchanged, `sel` present, drawer open after reload) |
| Top nav returns to the last visited sub-page; explorer width and collapse persist | ROUTER, SHELL, EXPLORER | `tests/js/router-core.test.mjs` (`navMemory`), `tests/js/explorer-core.test.mjs`; `tests/test_ui_shell.py`, `tests/test_ui_explorer.py`; `test_ui_acceptance.py::test_nav_memory_and_explorer_persistence` |
| Global search finds a device, room, cable tag and inventory item, with keyboard navigation | SEARCH, SRV, SHELL | `tests/js/search-core.test.mjs`; `tests/test_search_kinds.py`; `tests/test_ui_search.py`; `test_ui_acceptance.py::test_global_search` (campus-demo: `foh` → device, `chapel` → room, `A-001` → cable, `RC-0001` → Inventory group; ↓/↑/Enter navigates; Esc closes) |
| At ~390px: explorer is a drawer, nav shows icons only, no horizontal page scroll, all primary actions reachable | SHELL, EXPLORER, all wave-2 units | `tests/test_ui_shell.py` (no page horizontal scroll on every view at m; icon-only tab bar); each `tests/test_ui_*.py` at m; `test_ui_acceptance.py::test_phone_layout` (`devices/foh-cl5` at m: `.ex-side` hidden until `.ex-open`; `#app-tabbar` buttons have no visible text; `offscreen` of primary actions is 0) |
| No regression in patch drag, trace, viewer read-only, QR pages or PWA install | PV, INS, SHELL, QA | `tests/test_ui_pv.py` (CDP drag, mouse and touch); `test_frontend_smoke.py` (unchanged tests: ARIA, harnesses, viewer pages, perf, deep link); `test_api.py::test_trace`, `::test_qr_endpoint`, `::test_manifest`; `test_security.py::test_viewer_put_403_and_users_admin_only`; `test_ui_acceptance.py::test_trace_drawer`, `::test_viewer_role_read_only` (login server with a viewer user: no write actions rendered, PUT is 403); QA manual: DevTools Application → Manifest installable, SW active with `fathom-shell-0.4.0` |
| `docs/ui-audit.md` exists with audit, plan and Done/Deferred; SPEC.md and AGENTS.md updated | this PR, DOCS, coordinator | This file; DOCS acceptance grep; coordinator fills Done / Deferred |

Additional per-unit verification at three widths: each `tests/test_ui_<unit>.py` runs its key assertions at
`d` (1280×900), `t` (820×1180 touch) and `m` (390×844 touch). With `FATHOM_UI_SHOTS` set it saves
`<view>-<d|t|m>.png`, matching the audit names in `/opt/cursor/artifacts/audit/` for before/after
comparison.

---

## Done / Deferred

Filled in by the coordinator as waves merge. Each unit's branch was merged into `cursor/ui-uplift` with a
`--no-ff` merge commit named after the unit after the full gate passed on the merged tree.

### Wave 1 (shared primitives) — merged

| Unit | Merge | Contract tests | Accepted deviations from B.2 (document amended by this entry) |
| --- | --- | --- | --- |
| SRV | 57ba9da | 14 py | `vlan 20` does not match a network (the field holds the bare number). |
| T-* | 9 merges | 198 js | Test-first workers own `tests/js/<name>-contract.test.mjs`. |
| ROUTER | b28519f | 30/30 | D1 round-trip wording settled (byte-exact for `buildRoute` output, semantic for legacy hashes); `mergeRoute` replaces `query` wholesale; see D1. ROUTER also owns `tests/_ui.py` and `tests/test_ui_router.py`. |
| DRAWER | 4a5f922 | 9/9 | sm is the existing 88dvh bottom sheet (B.2), not the D3 table's "full-height"; extra exports `isModal, drawerHistory, LAYERS, isCanvas, trapIndex, domLayers`; `createDrawer(host, {layers})`, `open({focus:false})`, `relayout(width)`; first Esc inside a field blurs it, the second closes. |
| ENTITY | 7617524 | 16/16 | Header and sentinel are prepended to the host; page content must share the host (`position: sticky`). `resolveTab` returns `redirect: true` for a missing tab segment. Tab arrows move focus only; Enter follows. Compact mode keeps badges and tabs; actions go to ⋯ (all of them at sm). |
| SEARCH | 04c0d45 | 15/15 | `targetFor` always fills `id/tab/sub/query`; `groupHits` sets `category` on copies; `search.js` pushes recents itself; the no-results row and `button.sr-all` sit outside the listbox; `openSearch` returns `{root, input, close}`; "Go to" opens the section root. `ctx.recent` must expose the D8 arrays as well as `push/list`. |
| EXPLORER | 4de531a | 28/28 | `ex.content` is `div.ex-page` inside `section.ex-content`; `open()/close()` act only at sm; picking an item closes the sm drawer; resizer hit area 12 px (20 px coarse) with keyboard resizing as the accessible alternative; drawer `max-width: 24rem` = 312 px at the 13 px root font (kept). |
| FEEDBACK | 0117bda | 23/23 | `inlineError` is the API, `errorState` a re-export alias; the `skeleton()` node is itself the `aria-busy` wrapper (replace it, never clear it); `reviewBadge` returns `null` at 0; `mountBell` appends its menu to `body` and returns `{open, close, toggle, render, isOpen, destroy, pop, menu}`; `button.fb-bell` is 40/44 px. |
| TABLE | b16295c | 30/30 | CSV control is `a.dt-csv[role=button][download]` with a blob href (matches `#inv-csv`/`#sch-csv`); sm default is a table with a sticky first column (D3), card mode is opt-in `cards: true`; search text and page are not persisted (D8); sticky header needs `.dt-scroll` as an inner scroller (`--dt-max-h`); extra options `persist, noun, selectable(fn), search:false, csv:false, searchPlaceholder, groupOrder, pageSizes`; handle extras `setHighlight, readUrl, info`. |
| HOME | f36788c | 17/17 | Needs only `ctx.store.doc`; reads `fathom.ui.recent.<project>` directly for timestamps; synthesises the current project card at sm when `ctx.projects` is empty; cross-room cables count in both rooms; recents section omitted when empty. |
| WIZARD | 6fcc960 | 30/30 | Review and Result steps are appended automatically; `bulkDeviceOps/bulkCableOps` return plain op arrays; repatch deletes the displaced cables in the same commit; own per-row checkbox column (TABLE has no per-row `selectable`); backdrop also carries `.app-dialog-backdrop` so DRAWER's layer detection sees it; result link adds `hl=<first id>` and `f.id=a|b|…` for ≤ 50 rows; keydown does not bubble out of the open wizard. |
| SHELL | 2e8c1ed | — (12 py) | Section menus are siblings of their buttons; `navigateRoute`/`routeHref` reset the query when view or id changes and no query is given; a remembered section hash has its room rewritten to the current room; new storage key `fathom.ui.seen.<project>` (problem-report high-water mark; add to D8); subnav chips are 36 px tall (44 px coarse) — D6 wins over the 40 px rule here; `#app-views` is 44 px under a coarse pointer; restored offline edits keep their toast and get no notice; below lg legacy `navigate()` writes `drawer=0` on canvas views; the `/?p=` redirect keeps other query parameters. `A.inspector.focusSection` is guarded until INS lands. |

Gate at the end of wave 1 (`2e8c1ed`): 590 Python tests OK (1 skip), 557/557 Node tests, `fathom selftest` OK.

Follow-ups carried into later waves: DRAWER `domLayers` should also detect a generic `[role=dialog][aria-modal=true]` outside the host (wave 3 ST-SHELL or a DRAWER fix-up); `model-core.searchLocal` does not index SOP pages offline (D14 candidate); `fathom/static/dev/index.html` should link the new harnesses and the smoke `HARNESSES` list may include them (DOCS/QA); `AGENTS.md` test counts and the dotted single-suite command (`.[discovery]` pulls `x690`, whose stray top-level `tests` package breaks `python -m unittest tests.test_x`; use `discover -s tests -p test_x.py`) (DOCS).

### Wave 2 (view migrations) — merged

| Unit | Merge | Tests | Accepted deviations from B.3 (document amended by this entry) |
| --- | --- | --- | --- |
| SOP | d49538e | 4 py | Keeps `parseHash`/`buildHash` and its own `hashchange` listener with a same-params guard (no `route(r)` member); wide landing only ≥ 700 px; problems DataTable is not URL-bound and uses cards below 700 px; a device chip opens `sec=problems`. |
| PROOM | e22c764 | 12 py | Landing rows go straight to `rooms/<id>/overview`; explorer room links keep the current tab; page-tab tables use `sticky: false`; problem counts come from problem reports; "Public page" lives in ⋯; no landing explorer. |
| FP | 8a3414a | 7 py | Explorer lists "Devices" with a Placed group; picking a device drops/centres it and then selects it; reorder/rename/delete sit in ⋯; scale shown as a pill; writes hidden for viewers. |
| PT | d789080 | 7 py + 4 js | Dir/Medium are the only filterable columns; the Blocks filter writes `q`; Rows CSV is the DataTable CSV while Blocks keeps the server-equal CSV; sm scrolls the whole view with a sticky first column; the empty state has copy only (Clear filters → ST-CANVAS). |
| PDEV | d3852e5 | 7 py | `sub` highlights a row; switching tabs keeps `sel`/`sec`/`drawer`; the rail lists the seven common tabs; "Details" for viewers; the landing is a table only; the header wraps at md. |
| INV | 5e4e105 | 10 py | `#inv-scope` is a select; merge/mark-installed live in `.dt-bulk`; `#inv-csv` is the DataTable CSV and the import-format export stays as `#inv-csv-all` in ⋯; quick chips pre-filter; no group counts. |
| PV | 57559d8 | 7 py | Context menu falls back to `navigate()` when no rack/plan exists; on mount the URL wins, otherwise the session filter is written to the URL; writes hidden for viewers; empty state with Clear filters; zoom label hidden at md. |
| ADM | 46acb43 | 17 py | Builds table shows Outputs (the API has no user/size); settings rows have inline editors (row click is a no-op); a history row opens `history/<rev>`; Systems and Locations are separate tabs; share QR via `qr/pages.html?share=`; writes hidden for viewers; the view filters its own tabs with `canSee`. |
| RK | c66dcda | 13 py | `rp-` prefix for the rack page; Face column; "Details" for viewers; "Add device…" on the elevation; summary cards without `ctx.problems()`. |
| INS | ab86799 | 9 py | Handle `{destroy, focus(sel), render, focusSection(key), sections()}`; chips are deep links; new storage key `fathom.ui.inspector` (add to D8); "Now connected" puts the cables section first; status pill; `drawer=0` written for canvas targets below lg. |
| SCH | 3a6fb16 | 15 py | The default `cables` tab is replaced into the URL on mount only for a tab-less URL without params (`schedules` and `schedules?q=drum` stay as written; unknown tabs are always replaced); `#sch-state` stays a select (server state scope); `#sch-room` is the room-column filter (IP/DMX/Patch/Racks); `#sch-disc` filters a client-side Discipline column and the server `discipline` parameter is no longer sent; per-kind phone columns; BOM rows open the drawer for one device, a drill-down dialog otherwise; `#sch-bulk-add` and `#sch-csv-all` (old server CSV) added; print uses an all-filtered-rows sheet. |
| DISC | cb4456d | 10 py | Legacy `.disc-*` rules stay in `app.css` (D11); tabs are `button[data-disc-tab]` with arrow/Home/End keys, not links; a bad tab or run canonicalises with replace; the "Show run" select stays beside the Runs tab; the shown run gets a chip and accent edge instead of DataTable `highlight`; empty tabs use `emptyState`; finding rows are cards at sm; the Changes sub-tables are not URL-bound; viewer write controls are not rendered; `confirmScope` and per-tab skeletons landed early; the run-age badge has no Refresh button. |

Integration commits by the coordinator (treated as merge-conflict resolution, not feature work):

- `cefa51d` — INV's `openSection` polling of `#app-inspector details[data-section]` fought INS's `focusSection` (4 failures on `inventory?sel=…&sec=inventory`); the polling was removed since `ctx.openDrawer(sel, {section})` now focuses the section.
- `4845c09` — SCH's new `test_harness_walk` exposed that the inventory half of `dev/plans/harness.js` `walkSchedules` still drives the pre-DataTable inventory view. The harness now selects `tr[data-device] .dt-row-check` and reports `schedulesOk`, `inventoryOk` and `ok` separately; `test_ui_sch` asserts `schedulesOk`. ST-LISTS restores the inventory walk and asserts `ok`.

Gate at the end of wave 2 (`4845c09`): 708 Python tests (1 skip), 563/563 Node tests, `fathom selftest` OK.

Follow-ups carried into wave 3 (owner in parentheses):

- Primitives (PRIM-FIX, a wave-3 unit owning the primitive files no sweep unit owns): explorer post-mount `setRail`/`update`, `setChips`, custom row renderer/attrs, head slot, configurable empty text; entity-header live tab-link update and `a.eh-action.eh-primary` styling; `entity-core.summaryCards` comment/filter mismatch; DataTable `openTableDialog` passing `noun`, filter buttons hidden for hidden/`hideOnMobile` columns at sm, separate bulk-bar noun, `setHighlight` keeping the focus target and taking a no-scroll option, `readUrl` dropping stored filters when the URL drops `f.*`, a `<table>` class option, `csvName` setter, read-only awareness, `.dt-cols-panel` laid out off-screen while closed; `dom.h` style objects with CSS custom properties; drawer `domLayers` generic `[role=dialog][aria-modal=true]`; `dev/index.html` harness links and `dev/patchtable.html`/`dev/floorplan.html`/`dev/schedules.html` CSS links.
- Shell (ST-SHELL): `app.js` `globalKeys` skips Esc whenever `.ex-backdrop` exists (the explorer always renders it hidden) — use `.ex-backdrop:not([hidden])`; the shell selects the same device twice on load; dead `app.css` rules (`.app-palette` 118–123/180–189; `.disc-bulk`, `.disc-bulk-n`, `.disc-table .disc-sel`, `.disc-scroll`, `.disc-conn`); coarse-pointer `button,select,.chip{min-height:44px}` also hits non-interactive span chips; SOP empty-state copy and `.sop-landing-empty`.
- Canvas (ST-CANVAS): PT empty state Clear filters; RK discipline chips on the unracked explorer; floorplan rewrites `sel=marker:` to `sel=device:` after mount (decide against D1); `plan.css` `.sch-untagged td.sch-edit:first-of-type` never matches, `.sch-table` td/th rules depend on load order and the hover `background` shorthand wipes the row highlight, coarse `min-width: 44px !important` shrinks full-width editors.
- Lists (ST-LISTS): restore the harness inventory walk (`walk.ok`).
- Admin (ST-ADMIN): revoke share / delete user / delete backup still use old prompts → `confirmScope`.
- Entity (ST-ENTITY): `.ins-badges` hook (`reviewBadge`/`inlineError` unused), PROOM skeleton/empty/not-found states.
- Docs (DOCS): D8 add `fathom.ui.seen.<project>` and `fathom.ui.inspector`; `AGENTS.md` test counts and single-suite command; D14 candidate `model-core.searchLocal` not indexing SOP pages offline.
- QA: viewer-role run; search test on `sunday-demo` or `foh`; `vlan 20` does not match a network.
