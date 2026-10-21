# Fathom 0.3 QA report

Date: 2026-10-21. QA worker. Single source of truth: `docs/SPEC.md`. Scope: gates G1-G13 (§8.1), the §9 acceptance checklist, the §8.4 security checklist, the integration watch-list, and §8.2 performance.

## 0. Close-out (2026-10-21)

Re-verification of D1-D14 against the current tree, using the original repro steps. Environment rules as before: temporary `FATHOM_DATA` (`/tmp/qa/co/ld.*` for the server, `/tmp/qa/co/d.*` for the build), server on port 18101 only, headless Chrome through the same `/tmp/qa/drv.py` driver, no code edits, no git state changes. The server, every Chrome instance, the `fq` container and the `fathom:0.3` image were removed afterwards. Scripts and logs: `/tmp/qa/co/`.

Result: gates G1-G12 all pass. 13 of 14 defects are verified fixed. D5 is still failing: the singular question is fixed, but the plural question "The chapel speakers have no sound" still resolves to Chapel ATEM. FR counts: pass 188, fail 1 (FR-AST-02), gap 0, not verified 6.

### Control-plane addendum (2026-10-21, after QA close-out)
D5 residual fixed by W6 round 2 (`fathom/assistant.py` target resolution, `checklists/synonyms.json`, `checklists/symptoms.json`) and verified independently on the final tree:
- `parse_intent` targets: "The chapel speakers have no sound", "Chapel speakers have no sound" and "No sound from the chapel speakers" -> `ch-spk-l, ch-spk-r`; "Chapel speaker L has no sound" -> `ch-spk-l`; "The projector is black" -> `projector` only (no `bc-router` false match; symptom `no_video`); "No sound from the mains" -> `main-l, main-r`.
- `answer()` for the plural chapel question traces the mixer path to both speakers via `c-0086` and `c-0087`; the sunday-demo section 5.10 answer is unchanged (summary, 7 checks, suggestion).
- Final gate run after the fix: 226 Python tests OK on 3.14 and 3.9 (1 Chrome-gated skip), selftest OK on both, 120/120 JS tests, syntax lint 37/37, frozen files untouched, ownership clean.
Final FR counts: pass 189, fail 0, gap 0, not verified 6 (physical iPad/iPhone Safari, VoiceOver, macOS Safari automation permission).

### Close-out gate run

| Gate | Result | Key output |
| --- | --- | --- |
| G1 | pass | `python3` 3.14.6: `Ran 226 tests in 43.241s` / `OK (skipped=1)` (same Chrome-named skip) |
| G2 | pass | `/usr/bin/python3` 3.9.6: `Ran 226 tests in 52.841s` / `OK (skipped=1)` |
| G3 | pass | selftest on 3.14 and 3.9: both exit 0, `ok: fathom selftest passed` |
| G4 | pass | `node --test tests/js/*.test.mjs` (ratified glob form): `tests 120`, `pass 120`, `fail 0`, `skipped 0` |
| G5 | pass | `/usr/bin/python3 -m compileall -q fathom tests`: exit 0 |
| G6 | pass | `node --check` on every `fathom/static/js/*.js`, `sw.js`, `static/dev/*.js` and `static/dev/plans/harness.js`: all OK; `tests/js/syntax.test.mjs`: `tests 37`, `pass 37` |
| G7 | pass | `tests.test_frontend_smoke`: `Ran 11 tests`, `OK`; `[T2] patchview 150/600 renderMs (real time) = 59.4 ms` |
| G8 | pass | frozen-file `git diff --quiet`: exit 0 |
| G9 | pass | 224 changed or new paths, every one maps to an owner in §7.2; none uncovered |
| G10 | pass | `fathom demo` exit 0 (54 cards, 32 links, 584 patch rows); campus-demo build exit 0 in `real 0.90` s; all 918 relative `href`/`src` links across every HTML file in the run folder resolve (0 broken, 0 absolute); 284 room-to-device and 286 device-to-room links resolve |
| G11 | pass | `fathom_audio-0.3.0-py3-none-any.whl`, 182 entries, all 5 named files present |
| G12 | pass | `docker build` exit 0; `/healthz` `{"ok": true, "version": "0.3.0"}` on the second poll (about 1 s); `docker exec fq which pdftoppm`: `/usr/bin/pdftoppm`; container and image removed |

### Defect verification

| Defect | FR | Status | Evidence from the close-out run |
| --- | --- | --- | --- |
| D1 | FR-EXP-04 | verified fixed | Campus build: 918 relative links in all HTML files, 0 broken. `rooms/main/patch.html` links `../../devices/am2-drums.html`; `devices/foh-cl5.html` links `../devices/switcher.html`, `../rooms/index.html` |
| D2 | FR-NET-04 | verified fixed | `/p/cd/d/foh-cl5`, `ulxd-main`, `switcher` and the matching build pages show `ac:44:f2:a1:00:10`, `00:0e:dd:31:00:31`, `7c:2e:0d:11:22:33`; inspector MAC field for foh-cl5 shows `ac:44:f2:a1:00:10` |
| D3 | FR-TRC-04 | verified fixed | API `from=restream&direction=up` 23 paths (same as `from=restream:usb-in-1` and the CLI's 23); `sound-board` down 7; `atem-mini` up 22; `cd ch-spk-l` up audio 50, first `Chapel mixer · Analog In 10 → Omni Out 1 → Chapel speaker L` |
| D4 | FR-TRC-01 | verified fixed | `cd from=foh-cl5:omni-out-1&direction=down`: 50 paths, all 50 reach Main switcher, 0 revisit FOH CL5; first `FOH CL5 · Stream L → Main switcher · Stream mix L → SDI Out 5` (cable c-0049). CLI output identical |
| D5 | FR-AST-02 | still failing | Fixed: `fathom ask cd "Chapel speaker L has no sound" --room chapel --no-llm` answers `Lectern mic · Mic Out → Altar wall plate · XLR In 1 → Home run → Chapel mixer · Analog In 1 → Omni Out 1 → Chapel speaker L` with 8 checks. Still failing: `"The chapel speakers have no sound"` (also `"Chapel speakers have no sound"`, `"No sound from the chapel speakers"`, CLI and API, room chapel) gives intent targets `['ch-atem']`, summary `Here is how the signal reaches Chapel ATEM: Chapel camera · Audio In → HDMI Out → Chapel ATEM.` Expected targets `ch-spk-l` and `ch-spk-r` |
| D6 | FR-AST-06 | verified fixed | `/#/as1/main/patch`, livestream question, click `ATEM Mini · Stream` chip: hash `#/as1/main/patch?sel=port:atem-mini:analog-in-1`, card `atem-mini` selected, inspector `display: block` showing `ATEM Mini · Stream`; selection kept after the drawer closes |
| D7 | FR-PT-04 | verified fixed | Fresh `/#/as1/main/table`, Split view: `patchview.css` added to the stylesheets, top pane 392 px with a 303 px viewport, toolbar `display: flex`, 11 of 11 cards visible (`co-table-split-1400.png`) |
| D8 | FR-UX-01 | verified fixed | Autosave off, two renames of sub-x2: indicator `2 pending`, server revision unchanged; Cmd+S: `Saved · r4` (r3 to r4), name `Sub QA2` |
| D9 | FR-PLN-02 | verified fixed | `/p/cd`: `<div class="card hasbadge planned" data-id="bc-ma3"`, rule `.card.planned{border-style:dashed;...}`; app Map view computed `border-top-style: dashed` |
| D10 | FR-A11Y-04 | verified fixed | `prefers-reduced-motion: reduce` matched: 0 elements with a transition or animation on `/p/cd`, `/p/cd/r/chapel`, `/p/cd/d/foh-cl5`, `/p/cd/r/main/patch`, `/p/cd/rooms` (control with no-preference: 76 on `/p/cd`) |
| D11 | FR-MOB-02 | verified fixed | Chrome 1180x820, touch emulation, `(pointer: coarse)` true. Interactive elements under 44x44 px (or not inside a 44 px label): 0 of 39 (patch), 139 (table), 76 (racks), 165 (inventory), 103 (plan), 550 (schedules), 23 (map). Rack `--rk-ru` 44 px, 1U blocks 320x44, grips 44x44. Patch view ports: `--pv-row` 36 px pitch, row box 32 px in canvas units (`offsetHeight` 32); at the auto-fit zoom 0.69 the row reads 22.2 px on screen (pitch 24.9 px), at zoom 1.0 32 px with a 36 px pitch; port dot touch target 44x44 px |
| D12 | FR-MAP-01 | verified fixed | `/p/cd` has no `chapel-tf` or `bcast-dm7` card; build notes: `dante: 'CHAPEL-TF' belongs to room chapel; not drawn here`, same for `BCAST-DM7` |
| D13 | FR-MOB-07 | verified fixed | `/p/cd` and `/p/cd/r/chapel`: `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">` |
| D14 | FR-PLAN-12 | verified fixed | Plan view Delete opens a popover with `Also delete the uploaded files (2)` (unchecked) and `Unchecked keeps the files in the project.` Delete with it unchecked: plan removed, 5 attachments kept. Delete with it checked: plan removed, server log `DELETE /api/v2/projects/cd/files/att-7128de90fcba` and `att-927e0767ee05` both 200, attachments 5 to 3 |

### Still not verified

- Physical iPad and iPhone Safari: FR-PV-07, FR-PV-18, FR-PLAN-09 (pinch and long-press), FR-MAP-03 (tap tips), FR-INV-03 (photo picker). Chrome touch emulation passes for each.
- VoiceOver: FR-A11Y-02 (ARIA test and live region pass).
- macOS Safari: AppleScript inspection blocked by the macOS Automation permission prompt.
- Lesser items unchanged from section 6 (DevTools manifest pane, admin reset password, iPad performance budget).

### Ratified deviations (not defects)

1. G4 runs as `node --test tests/js/*.test.mjs`; the literal `node --test tests/js` exits 1 before running tests.
2. QR version 40-M byte-mode capacity is 2331 bytes (§C.3 expects `encode("x" * 2332, "M")` to give version 40).
3. `×` is treated as opaque text inside port names.
4. Wire arrowheads are not drawn.

## Original run (2026-10-21, before fixes)

Summary: all twelve command gates pass (G4 with the ratified glob form). The live walk (G13) found 13 FR failures and 1 gap, all on P0 requirements, plus 6 items that need a physical iOS device or VoiceOver. The most serious failures are broken internal links in every build (D1), wrong HTTP trace results for bare device ids (D3), traces that walk backwards through a device (D4), a broken patch-table split view (D7), and touch hit targets below 44 px (D11). Sections 1 to 9 below record that run; the per-FR table, totals and watch-list carry close-out status.

## 1. Environment

| Item | Value |
| --- | --- |
| OS | macOS 26.6.2 (darwin 25.6.0), arm64 |
| Python | `python3` 3.14.6; `/usr/bin/python3` 3.9.6 (G2, G3, G5) |
| Node | v26.0.0 |
| Chrome | Google Chrome 155.0.8059.40, headless (`--headless=new`) and DevTools protocol through T2's `CDP` client |
| Docker | Docker Desktop, server 27.4.0 |
| PDF rasterizer | `/opt/homebrew/bin/pdftoppm` present locally; `sips` present |
| Repo state | `main` has no commits; v0.2 files are staged in the index, all 0.3 work is unstaged or untracked. G8/G9 compare against the index |
| Servers | `FATHOM_DATA=$(mktemp -d) python3 -m fathom serve` on ports 18101-18110 (18101 main walk; 18102 upload cap 1 MB; 18103 `FATHOM_AUTH=qa:secret`; 18104 auth + `FATHOM_PUBLIC_VIEW=1`; 18105 upload cap 200 MB for DXF limits; 18106 LLM env with unreachable endpoint; 18110 stopped mid-test for real offline checks) |
| Projects | `sunday-demo`, `pv`, `as1` (fixture `fathom/static/dev/fixture-v2.json` via POST + PUT `If-Match: "r0"`), `cd`, `cd2`, `qa-new` (`fathom new … --template campus-demo`), `rrc` (`--template rrc-littleton`) |
| Scratch | `/tmp/qa/` (scripts, logs, screenshots). All servers, Chrome instances and the `fq` container were stopped; image `fathom:0.3` was removed |

## 2. Quality gates

| Gate | Command (as run) | Result | Key output |
| --- | --- | --- | --- |
| G1 | `python3 -m unittest discover -s tests -v` | pass | `Ran 226 tests in 49.612s` / `OK (skipped=1)`. Only skip: `test_report_pdf` ("headless Chrome PDF render takes ~15 s; set FATHOM_T1_CHROME=1 to run it (Chrome present)"), reason names Chrome. Run separately with `FATHOM_T1_CHROME=1`: OK |
| G2 | `/usr/bin/python3 -m unittest discover -s tests` | pass | `Ran 226 tests in 56.080s` / `OK (skipped=1)` (same skip) |
| G3 | `python3 -m fathom selftest`; `/usr/bin/python3 -m fathom selftest` | pass | both exit 0, last line `ok: fathom selftest passed` |
| G4 | `node --test tests/js/*.test.mjs` (ratified form) | pass | `tests 120`, `pass 120`, `fail 0`, `skipped 0`. Literal `node --test tests/js` exits 1 before running (ratified deviation 1) |
| G5 | `/usr/bin/python3 -m compileall -q fathom tests` | pass | exit 0 |
| G6 | `for f in fathom/static/js/*.js fathom/static/sw.js fathom/static/dev/*.js; do node --check "$f" \|\| exit 1; done` and `node --test tests/js/syntax.test.mjs` | pass | all files OK; `tests 37`, `pass 37`. `fathom/static/dev/plans/harness.js` is outside the glob; checked separately with `node --check`: OK |
| G7 | `python3 -m unittest tests.test_frontend_smoke -v` (inside G1/G2, and the perf test alone) | pass | 11 tests OK; `[T2] patchview 150/600 renderMs (real time) = 75.2 ms` (G1), 56.9 ms (G2), 73.3 ms (standalone) |
| G8 | `git diff --quiet -- tests/test_fathom.py fathom/samples/rrc-littleton/project.json fathom/samples/rrc-littleton/exports` | pass | exit 0; other frozen files (`.gitignore`, `.dockerignore`, `fathom/__main__.py`, `docs/demo.png`) also unchanged |
| G9 | `git status --porcelain --untracked-files=all` checked against §7.2 | pass | 223 new/modified paths, every one maps to an owner in §7.2, `docs/notes/*.md`, or pre-existing frozen docs (`docs/SPEC.md`, `docs/Inspo/*`). No uncovered path |
| G10 | `python3 -m fathom demo`; `FATHOM_DATA=$(mktemp -d) sh -c 'python3 -m fathom new cd --template campus-demo && python3 -m fathom build cd'`; repeated with `FATHOM_PUBLIC_URL=http://localhost:8080` | pass | demo exit 0 (54 cards, 32 links, 584 patch rows); campus build exit 0 in 1.28 s, run folder has every §5.9 file (index.html, diagram.svg, patch-sheet.csv, project.json, build-notes.txt, rooms/{main,chapel,broadcast}/{index.html,diagram.svg,patch.html}, rooms/index.html, 73 devices/*.html, the 7 CSVs/label sheet, 6 rack SVGs, 3 floorplan SVGs, report.html, zip). Without public URL: build note "QR codes skipped". With it: 73 `qr/*.svg`, valid XML, 37x37 modules |
| G11 | `python3 -m pip wheel . --no-deps -w "$(mktemp -d)"`; `python3 -m zipfile -l <wheel>` | pass | `fathom_audio-0.3.0-py3-none-any.whl`, 182 entries, contains all five named files. Side effect: pip created gitignored `build/` and `fathom_audio.egg-info/` in the repo root |
| G12 | `docker build -t fathom:0.3 .`; `docker run --rm -d --name fq -p 18080:8080 fathom:0.3`; `curl -fsS http://127.0.0.1:18080/healthz`; `docker exec fq which pdftoppm`; `docker rm -f fq` | pass | build exit 0; healthz `{"ok": true, "version": "0.3.0"}` after about 1 s; `/usr/bin/pdftoppm`; cmd `gunicorn --bind 0.0.0.0:8080 … fathom.server:app`, volume `/data`. Container and image removed |
| G13 | live server walk (ports 18101-18110 instead of 18081, per QA instructions) | fail | Original run: 13 FR failures, 1 gap. Close-out: 1 FR failure (FR-AST-02, D5), 0 gaps; 6 items not verified (section 6) |

## 3. Integration watch-list

| Item | Result | Evidence |
| --- | --- | --- |
| (a) Assistant round-trip | pass | `POST /api/v2/projects/sunday-demo/assistant` returned every §5.10 key; intent, summary, `paths[0].text`, cables `c-0011, c-0015`, branch, HDMI note, confidence `high` all match §5.10; `suggestion.base_revision` 2 = project revision 2. Applying the ops via `/changes` gave revision 3 and `atem-mini:analog-in-1.note = "Stream feed: Audio Rack 1 → ATEM Mini · check Audio tab"` |
| (b) No duplicate `dmx_range` | pass | `wireless-mics.dmx = {universe 70000, address 600}`: project `problems` and `schedules/dmx` each list one `dmx_range` for the device |
| (c) Library `source`, builtin delete refused | pass | 57 entries all `source: builtin`; with `project=cd` one `project` entry; a POSTed custom template lists as `custom` and deletes with 204; `DELETE /api/v2/library/shure-sm58` returns 409 and the template remains |
| (d) DXF layer hide | pass | `fp-main-floor/image` has 6 `data-layer` groups; `?hide=WALLS` drops the WALLS group (different SVG); `?hide=WALLS,SEATS` drops both |
| (e) MAC display on device page | pass (close-out) | D2 verified fixed: `ac:44:f2:a1:00:10` on `/p/cd/d/foh-cl5` and the build page |
| (f) Build relative links | pass (close-out) | D1 verified fixed: 918 relative links, 0 broken |
| (g) CLI trace and ask | pass with defects | `fathom trace cd foh-cl5:omni-out-1` and `fathom ask cd "…"` run and print paths/checks; the content was wrong in places (D4, D5). Close-out: D4 fixed; D5 plural speaker question still wrong |
| (h) RRC Dante preset into campus-demo | pass | doc devices 73 before and after; overlay devices 15 to 46, none matching an existing campus device by id, name, code or Dante name; build notes list only devices absent from campus. Pre-existing duplicates from the campus preset itself are D12 |

## 4. Per-FR status (195 FR ids in §3)

The brief mentions 191; §3 contains 195 ids (174 P0, 20 P1, 1 P2). None are roadmap items (§2.2 items are not FR ids, and FR-IMP-09 P2 was delivered).

Totals after close-out: pass 188, fail 1, gap 0, not verified 6, out of scope / roadmap 0. (Original run: pass 175, fail 13, gap 1, not verified 6.)

Evidence key: "G1" / "G4" / "G7" = the named automated test exists and passed in that gate run; "M" = manual check on the live server; screenshot names refer to `/tmp/qa/shots/`. All §9 automated test names exist under the exact §9 names (verified with `/tmp/qa/names.py`; JS test names also matched in the G4 output). Defects D1-D14 are in section 5.

| FR | Pri | Owner (spec) | Status | Evidence |
| --- | --- | --- | --- | --- |
| FR-ROOM-01 | P0 | W1 | pass | G1 test_room_collections_validate |
| FR-ROOM-02 | P0 | W1, W5 | pass | G4 model-core "filterDevices shared inventory" |
| FR-ROOM-03 | P0 | W5 | pass | M: cd room picker -> hash #/cd/chapel/patch; 12 chapel cards + ghost sw-foh (room-switch-chapel.png) |
| FR-ROOM-04 | P0 | W5 | pass | M: Settings > Venues & rooms added 'Chapel 2' (id chapel-2); in picker after reload |
| FR-ROOM-05 | P0 | W5, W3 | pass | G4 "external ghost devices"; M: atem-mini moved to Chapel 2, 4 cables kept, ghost card 50% opacity with room name (room-ghost-atem.png) |
| FR-ROOM-06 | P1 | W4 | pass | M: Inventory 'Group by location' on cd (10 location groups, inventory-grouped.png) |
| FR-ROOM-07 | P0 | W1, W5 | pass | G1 test_viewer_room_maps |
| FR-ROOM-08 | P1 | W4, W3 | pass | G4 "filter by system"; W4 schedules harness walk mainVideoRows=4 |
| FR-VOC-01 | P0 | W2 | pass | G1 test_vocab_kinds |
| FR-VOC-02 | P0 | W2 | pass | G1 test_vocab_media_v1_subset |
| FR-VOC-03 | P0 | W2 | pass | G1 test_vocab_disciplines |
| FR-VOC-04 | P0 | W1 | pass | G1 test_meta_v1_and_v2 |
| FR-VOC-05 | P0 | W3, W4, W5 | pass | M: patch-view pills per discipline color, wires by medium color/dash (13 distinct styles), schedule chip column (desk-app-sunday-demo-patch.png) |
| FR-VOC-06 | P1 | W5 | pass | M: inspector port Connector input list=ins-connectors, 54 options |
| FR-VOC-07 | P0 | W1 | pass | G1 test_unknown_medium_is_warning |
| FR-PORT-01 | P0 | W1 | pass | G1 test_port_validation |
| FR-PORT-02 | P0 | W1, W3 | pass | G1 test_device_level_cable; M: device-level cable c-dev1 wire ends at card header edge |
| FR-PORT-03 | P0 | W1, W5 | pass | G1 test_port_expansion_vectors; G4 "expandPortGroups vectors" |
| FR-PORT-04 | P0 | W5, W1 | pass | G4 "canConnect"; G1 test_port_overuse_warning |
| FR-PORT-05 | P0 | W6 | pass | G1 test_passthrough_routing |
| FR-PORT-06 | P0 | W5 | pass | M: inspector Add 8 x Analog In on samsung-tv-1 -> analog-in-1..8 |
| FR-PORT-07 | P1 | W3, W5 | pass | M: cd broadcast bc-router 40 italic labels title 'from import', revision unchanged; see observation O4 (RRC has 0 overlay port labels) |
| FR-MIG-01 | P0 | W1 | pass | G1 test_migrate_rrc_valid |
| FR-MIG-02 | P0 | W1 | pass | G1 test_load_signalflow_v1 |
| FR-MIG-03 | P0 | W1 | pass | G1 test_rrc_layout_identity |
| FR-MIG-04 | P0 | W1 | pass | G1 test_v1_backup_written_once |
| FR-MIG-05 | P0 | W2 | pass | G1 test_cli_migrate |
| FR-MIG-06 | P0 | W1 | pass | G1 test_v1_put_expressible_and_409; live viewer 403 on v1 PUT |
| FR-MIG-07 | P0 | W1 | pass | G1 test_migration_bundles_drums_neve1 |
| FR-PV-01 | P0 | W3 | pass | M: fixture patch view matches Knox (b) layout (desk-app-sunday-demo-patch.png vs docs/Inspo/2026-10-20_14-38-25.jpg) |
| FR-PV-02 | P0 | W3 | pass | G1 test_patchview_harness (15 wires); arrowheads not drawn (ratified deviation 4) |
| FR-PV-03 | P0 | W3 | pass | G4 "moveOps snaps"; M: drag restream +96/+48 (8 px grid), one merge op, Cmd+Z restored exactly |
| FR-PV-04 | P0 | W3 | pass | G4 "connectOps"; M: drag thru-1 -> sub-x2 Input 2 created 1 cable; in->in refused with toast |
| FR-PV-05 | P0 | W3 | pass | G4 "repatchOps"; M: re-patch changed only the to-end, undo restored; selected wire + Delete removed it |
| FR-PV-06 | P0 | W3 | pass | M: double-click title -> 'Restream QA'; port label 'YT Out'; patch table shows it after view switch |
| FR-PV-07 | P0 | W3 | not verified | Desktop: +/=/-/0/F keys, buttons, Cmd+wheel zoom, wheel pan, limits 0.15-3.0 pass. Chrome touch emulation pinch pass, page scale 1. iPad Safari not available |
| FR-PV-08 | P0 | W3, W5 | pass | G4 "store undo/redo 20 steps" |
| FR-PV-09 | P0 | W3 | pass | M: Tab/P/arrows to thru-2, C, Enter -> cable created; live region announced (see O3) |
| FR-PV-10 | P0 | W3 | pass | G4 "buildScene filters"; M: Video chip -> stage-box-1, atem-mini, video-converter, samsung-tv-1 only (pv-video-chip.png) |
| FR-PV-11 | P0 | W3 | pass | G4 "addDeviceFromTemplateOps", "deleteDeviceOps"; M: Add gear picker 'atem mini pro' -> device with 9 template ports |
| FR-PV-12 | P0 | W3 | pass | G4 "autoLayout no overlap on migrated RRC"; M: RRC 53 cards, 0 overlapping |
| FR-PV-13 | P0 | W3 | pass | M: viewer login, drag and Delete emit no ops, 'Read-only - r3', Add gear hidden (viewer-readonly-patch.png) |
| FR-PV-14 | P0 | W3 | pass | M: assistant chip lit audio-rack-1, atem-mini, restream + c-0011, c-0015 (the fixture path has 2 cables) |
| FR-PV-15 | P0 | W3 | pass | G7 test_patchview_perf_150_600 renderMs 75.2 / 56.9 / 73.3 ms; drag JS <= 0.2 ms per frame. iPad A12 not measured |
| FR-PV-16 | P1 | W3 | pass | M: Shift-drag selected 3 cards; group drag moved 3 devices in one revision; Cmd+Z restored all |
| FR-PV-17 | P1 | W3 | pass | M: RRC Network routes toggle -> 31 aggregated route paths (rrc-network-routes.png) |
| FR-PV-18 | P0 | W3 | not verified | M: right-click menu has all 8 items + 'Trace upstream'; Chrome touch long-press opens it (touch-longpress-menu.png). iPad not available |
| FR-PT-01 | P0 | W5 | pass | G4 "fixture blocks equal golden"; M: matches Knox (c) structure |
| FR-PT-02 | P0 | W5 | pass | M: Patch... on Main Speakers Input 2 -> picker -> audio-rack-1:analog-out-2 cable created |
| FR-PT-03 | P0 | W5 | pass | M: label 'Sub 2' -> 'Sub 2 QA'; x removed c-0010; Cmd+Z restored |
| FR-PT-04 | P0 | W5 | pass | Close-out: D7 verified fixed (fresh table load, split view loads patchview.css, 11/11 cards visible) |
| FR-PT-05 | P0 | W5, W6 | pass | G4 "csv equals server"; G1 test_schedule_patch_csv |
| FR-PT-06 | P0 | W5 | pass | G4 "filters" |
| FR-PT-07 | P1 | W5 | pass | M: RRC 'Show import rows' lists Dante rows in italic (rrc-table-import-rows.png) |
| FR-PT-08 | P0 | W5 | pass | G7 test_viewer_pages; M: /p/cd/r/main/patch at 4 sizes, errors [] |
| FR-MAP-01 | P0 | W5, W1 | pass | Close-out: D12 verified fixed (no CHAPEL-TF / BCAST-DM7 cards on the main map); 3 distinct room maps |
| FR-MAP-02 | P0 | W5 | pass | G1 test_rrc_key_label |
| FR-MAP-03 | P0 | W5 | not verified | Chrome touch emulation 390x844: tap shows tip, second tap traces (phone-viewer-tap1/2.png); iPhone Safari not available |
| FR-MAP-04 | P0 | W5 | pass | M: inspector Map group C->A saved, map iframe reloaded; Groups & columns dialog CRUD (map-groups-dialog.png) |
| FR-MAP-05 | P1 | W5 | pass | M: assistant chip in Map view lit cam-1, sw-foh, projector, 83 dimmed (map-assistant-highlight.png) |
| FR-MAP-06 | P0 | W5, W1 | pass | G1 test_room_index_and_device_page; M: rooms/device pages offline after visit / prefetch |
| FR-PLAN-01 | P0 | W2, W4, W1 | pass | G1 test_floorplan_uploads; M: all 6 samples + a JPG upload and render (pdf via pdftoppm) |
| FR-PLAN-02 | P0 | W2 | pass | G1 test_drawio_compressed_and_plain |
| FR-PLAN-03 | P0 | W2 | pass | G1 test_dxf_fixture; binary DXF -> 415 live |
| FR-PLAN-04 | P0 | W2 | pass | G1 test_svg_sanitize; live: script/onload/javascript:/foreignObject/external href stripped |
| FR-PLAN-05 | P0 | W2, W1 | pass | G1 test_pdf_rasterizer_and_fallback; live rcp.pdf -> PNG |
| FR-PLAN-06 | P0 | W2, W1 | pass | G1 test_dwg_415; live 415 dwg_unsupported with 'DXF' |
| FR-PLAN-07 | P1 | W2 | pass | G1 test_oda_fake_converter |
| FR-PLAN-08 | P0 | W4 | pass | G4 "markerOps"; M: unplaced listed first; drop at (0.30, 0.40); marker drag persisted |
| FR-PLAN-09 | P0 | W4 | not verified | Chrome touch emulation pinch scale 0.43 -> 2.06 (touch-plan-pinch.png); iPad not available |
| FR-PLAN-10 | P0 | W4 | pass | G4 "calibrate 10 m"; M: measure 12.5 m consistent with stored 10 m calibration; harness 10.0 m |
| FR-PLAN-11 | P1 | W4, W2 | pass | G1 test_floorplan_hide_layers; M: WALLS toggle -> hidden_layers [WALLS], img ?hide=WALLS; watch-list (d) |
| FR-PLAN-12 | P0 | W4 | pass | Close-out: D14 verified fixed (Also delete the uploaded files option; unchecked keeps files, checked deletes them); cd main had 2 plans |
| FR-PLAN-13 | P0 | W2 | pass | G1 test_build_floorplan_svg_markers |
| FR-RACK-01 | P0 | W4, W1 | pass | M: New rack 'QA rack' 12U created in room main |
| FR-RACK-02 | P0 | W4, W6 | pass | G4 "fixture placement U10 left" |
| FR-RACK-03 | P0 | W4 | pass | G7 test_rack_harness |
| FR-RACK-04 | P0 | W4 | pass | G4 "fits refuses overlap"; M: drop on occupied U5 refused with toast; Alt-drop placed with overlap warning (rack-alt-drop.png) |
| FR-RACK-05 | P0 | W6 | pass | G1 test_validate_racks_overlap |
| FR-RACK-06 | P0 | W4, W6 | pass | G1 test_build_rack_svgs; G10 build has racks/*-front/rear.svg |
| FR-CAB-01 | P0 | W5, W1 | pass | M: tag/length/color edits saved and shown after reload; '10' ft -> 3.048 m, '3 m' -> 3 m |
| FR-CAB-02 | P0 | W2, W4 | pass | G1 test_assign_tags_fixture; harness preview exact |
| FR-CAB-03 | P0 | W2 | pass | G1 test_schedule_cables_csv_header |
| FR-CAB-04 | P0 | W2 | pass | G1 test_label_sheet_counts |
| FR-CAB-05 | P1 | W2, W4 | pass | G1 test_bundle_members_rrc |
| FR-CAB-06 | P0 | W2 | pass | G1 test_cable_csv_roundtrip |
| FR-NET-01 | P0 | W1 | pass | G1 test_network_validation |
| FR-NET-02 | P0 | W2 | pass | G1 test_dante_device_info_addresses |
| FR-NET-03 | P0 | W2 | pass | G1 test_ip_duplicate_warning |
| FR-NET-04 | P0 | W2, W4 | pass | Close-out: D2 verified fixed (device pages, build pages and inspector show colon lowercase MACs) |
| FR-NET-05 | P1 | W2, W4 | pass | G1 test_ip_switch_ports_campus; live IP schedule switch ports |
| FR-DMX-01 | P0 | W1, W6 | pass | G1 test_dmx_range_warning; watch-list (b) single dmx_range |
| FR-DMX-02 | P0 | W6 | pass | G1 test_dmx_overlap |
| FR-DMX-03 | P0 | W6, W2 | pass | G1 test_eos_overlay_dmx |
| FR-DMX-04 | P1 | W6 | pass | G1 test_sacn_artnet_helpers |
| FR-LIB-01 | P0 | W2 | pass | G1 test_library_count_and_valid (57 templates) |
| FR-LIB-02 | P0 | W2 | pass | G1 test_template_schema |
| FR-LIB-03 | P0 | W2, W1, W5 | pass | G1 test_library_search_rio; live q=rio; M: picker search |
| FR-LIB-04 | P0 | W2 | pass | G1 test_custom_template_precedence; watch-list (c) |
| FR-LIB-05 | P0 | W2, W5 | pass | G1 test_apply_template_idempotent |
| FR-INV-01 | P0 | W1, W5 | pass | M: inspector serial/asset tag/firmware saved and shown after reload |
| FR-INV-02 | P0 | W4 | pass | M: 3 devices -> spare in one revision; one Cmd+Z restored all 3 |
| FR-INV-03 | P0 | W5, W1 | not verified | G1 test_file_upload_download; M desktop: JPG via inspector file input saved (mime image/jpeg) and shown; iPad not available |
| FR-INV-04 | P0 | W4 | pass | G1 test_schedule_inventory_csv |
| FR-INV-05 | P1 | W4 | pass | M: Warranty<90 days -> 0 rows (sound-board excluded); Missing serial -> 9 devices |
| FR-PLN-01 | P0 | W1, W2, W5 | pass | G1 test_build_state_as_built |
| FR-PLN-02 | P0 | W3, W5 | pass | Close-out: D9 verified fixed (map card class planned, dashed border); patch view dashed, tables chip |
| FR-PLN-03 | P0 | W2 | pass | G1 test_bom_fixture_total (6498.00 USD) |
| FR-PLN-04 | P1 | W4 | pass | M: Mark installed on planned restream -> installed |
| FR-AST-01 | P0 | W5 | pass | M: toolbar button and Cmd+J open, Esc closes, focus returns to button; phone = full-screen 390x844 sheet |
| FR-AST-02 | P0 | W6 | fail | D5 partly fixed: singular "Chapel speaker L has no sound" now correct; plural "The chapel speakers have no sound" still targets ch-atem. Fixture AC passes (G1 test_livestream_no_audio, watch-list (a)) |
| FR-AST-03 | P0 | W6, W5 | pass | G1 test_suggestion_ops; M: Yes set the note at r3, Cmd+Z removed it; watch-list (a) |
| FR-AST-04 | P0 | W6 | pass | G1 test_trace_question_tv; live 'What feeds Samsung TV - 1?' type trace, 0 checks |
| FR-AST-05 | P1 | W6 | pass | G1 test_locate_spare; live describe 'Wireless 1' |
| FR-AST-06 | P0 | W5 | pass | Close-out: D6 verified fixed (chip sets ?sel=port:atem-mini:analog-in-1, card selected, inspector shown) |
| FR-AST-07 | P0 | W6 | pass | G1 test_llm_stub_and_unconfigured; live unreachable LLM -> llm.error, 200, no key in responses/log |
| FR-AST-08 | P0 | W6 | pass | G1 test_unresolved_suggestions; live 'projector 2' message |
| FR-AST-09 | P0 | W2 (CLI), W6 | pass | G1 test_cli_ask; watch-list (g) CLI runs |
| FR-TRC-01 | P0 | W6 | pass | Close-out: D4 verified fixed (foh-cl5:omni-out-1 down: 50/50 paths reach Main switcher via c-0049) |
| FR-TRC-02 | P0 | W6 | pass | G1 test_discipline_filter_video |
| FR-TRC-03 | P0 | W6 | pass | G1 test_path_text_rule |
| FR-TRC-04 | P0 | W6, W2 | pass | Close-out: D3 verified fixed (bare device ids return paths: restream up 23, equal to the CLI) |
| FR-TRC-05 | P0 | W3 | pass | G4 "traceLocal downstream audio" |
| FR-SRCH-01 | P0 | W6 | pass | G1 test_search_ip; palette '10.20.0.40' -> ATEM Mini interface |
| FR-SRCH-02 | P0 | W5 | pass | M: Cmd+K palette, grouped results; Enter: device -> patch + sel, cable -> schedules, interface -> inspector; phone search icon present |
| FR-SRCH-03 | P0 | W5 | pass | G4 "searchLocal" |
| FR-SRCH-04 | P0 | W6, W5 | pass | G1 test_search_ranking; G4 "searchLocal ranking"; 'atem' -> ATEM Mini first |
| FR-HIST-01 | P0 | W1 | pass | G1 test_history_entries |
| FR-HIST-02 | P0 | W1, W5 | pass | G1 test_restore_revision; History view has View/Restore |
| FR-HIST-03 | P0 | W1 | pass | G1 test_put_requires_if_match |
| FR-HIST-04 | P0 | W1 | pass | G1 test_stale_put_rebase_and_conflict |
| FR-HIST-05 | P0 | W1 | pass | G1 test_changes_rebase_and_conflict |
| FR-HIST-06 | P0 | W5 | pass | M: two browsers; banner 'Someone else changed ...', Keep mine -> B's value r35; Reload -> A's value r36 (conflict-banner.png); see O5 |
| FR-HIST-07 | P1 | W1, W5 | pass | G1 test_history_diff; History view Diff button (history-view.png) |
| FR-HIST-08 | P0 | W1 | pass | G1 test_history_snapshots_every_25 |
| FR-USER-01 | P0 | W1 | pass | G1 test_role_matrix; live viewer 403 on 15 write routes, editor 403 on admin routes |
| FR-USER-02 | P0 | W1 | pass | G1 test_password_hash_format; users.json pbkdf2_sha256$600000$..., no plaintext |
| FR-USER-03 | P0 | W1, W5 | pass | G1 test_session_cookie_flags_and_epoch; live Set-Cookie HttpOnly, SameSite=Lax, Path=/, Max-Age=1209600, Secure with X-Forwarded-Proto https |
| FR-USER-04 | P0 | W1 | pass | G1 test_basic_auth_users_and_env; live curl -u qa:secret 200, wrong 401 |
| FR-USER-05 | P0 | W1 | pass | G1 test_auth_off_is_admin; live no-creds 401 with WWW-Authenticate |
| FR-USER-06 | P0 | W1 | pass | G1 test_public_view; live /p/* and /builds/* 200, /api/* 401 |
| FR-USER-07 | P0 | W2, W1 | pass | G1 test_cli_user_commands; live CLI user add/list |
| FR-USER-08 | P0 | W5 | pass | M: admin Users panel add (qa2), role change, disable; reset password not exercised |
| FR-USER-09 | P1 | W1, W5 | pass | G1 test_share_links |
| FR-USER-10 | P1 | W1 | pass | G1 test_login_throttle; live 5x401 then 429 |
| FR-MOB-01 | P0 | W5 | pass | M: 1400 docked inspector (static), 820 slide-over (fixed), 390 bottom tab bar Map/Patch/Table/Plan/More; see O1, O2 |
| FR-MOB-02 | P0 | W3, W4, W5 | pass | Close-out: D11 verified fixed (coarse pointer: 0 targets under 44 px in 7 views; port rows 32 px box, 36 px pitch in canvas units) |
| FR-MOB-03 | P0 | W5 | pass | M (Chrome emulation 390x844): map pinch not disabled, tap tips, stacked patch table, device pages render; real iPhone not available |
| FR-MOB-04 | P0 | W1 | pass | G1 test_manifest; live manifest fields and 3 icons 200, apple-touch-icon PNG; DevTools manifest pane not opened |
| FR-MOB-05 | P0 | W1, W5 | pass | M real outage (server stopped): visited /p/as1 and app shell load from SW; unvisited page fails |
| FR-MOB-06 | P0 | W1, W5 | pass | M: user menu 'Make available offline' -> 'Available offline: 44 saved'; server stopped; unvisited device page and rooms load |
| FR-MOB-07 | P0 | W3, W4, W5 | pass | Close-out: D13 verified fixed (viewport-fit=cover on /p/cd) |
| FR-MOB-08 | P0 | W5 | pass | G4 "ChangeQueue persists and flushes"; M: offline 2 edits ('Offline - 2 pending', localStorage 2 items) -> online exactly 1 new revision |
| FR-EXT-01 | P0 | W2 | pass | G1 test_plugin_dir_registers |
| FR-EXT-02 | P0 | W2 | pass | G1 test_plugin_api |
| FR-EXT-03 | P0 | W2, W6 | pass | G1 test_extra_checklist_dir |
| FR-EXT-04 | P0 | W1 | pass | G1 test_openapi_covers_routes; /api/openapi.json 83 path+method entries |
| FR-EXT-05 | P0 | W2 | pass | G1 test_cli_plugins |
| FR-EXP-01 | P0 | W2 | pass | G1 test_build_layout_campus; G10 file list complete |
| FR-EXP-02 | P0 | W2 | pass | G3 selftest; G1 test_v1_artifacts |
| FR-EXP-03 | P0 | W2, W1 | pass | G1 test_build_rooms_subset |
| FR-EXP-04 | P0 | W2 | pass | Close-out: D1 verified fixed (918 relative links, 0 broken); QR branch: 73 qr/*.svg with FATHOM_PUBLIC_URL, build note without |
| FR-EXP-05 | P1 | W2, W5 | pass | test_report_pdf with FATHOM_T1_CHROME=1 OK; live build pdf+png -> report.pdf 2.59 MB |
| FR-QR-01 | P0 | W2 | pass | G1 test_qr_vectors, test_qr_rs_selfcheck (2331-byte capacity per ratified deviation 2) |
| FR-QR-02 | P0 | W2, W1, W5 | pass | G1 test_qr_endpoint; device page QR rendered |
| FR-IMP-01 | P0 | W2 | pass | G1 test_legacy_overlay_rrc (221 Dante routes live); watch-list (h) RRC import into cd adds no duplicate of an existing device |
| FR-IMP-02 | P0 | W2 | pass | G1 test_dante_device_info_addresses |
| FR-IMP-03 | P0 | W2 | pass | G1 test_eos_csv |
| FR-IMP-04 | P0 | W2 | pass | G1 test_usitt_ascii |
| FR-IMP-05 | P0 | W2 | pass | G1 test_lightwright_text |
| FR-IMP-06 | P0 | W2 | pass | G1 test_lighting_contribution_matching |
| FR-IMP-07 | P0 | W2 | pass | G1 test_videohub_dump |
| FR-IMP-08 | P0 | W2, W1 | pass | G1 test_generic_csv_preview |
| FR-IMP-09 | P2 | W2 | pass | G1 test_atem_xml |
| FR-IMP-10 | P0 | W5 | pass | M: Imports view upload cards (7 file inputs), Inspect inline, Remove, Promote REC-DVS -> device (imports-view.png) |
| FR-SEC-01 | P0 | W1 | pass | G1 test_path_traversal; live 22 traversal variants 400/404; symlinks in files/ and builds/ -> 404 |
| FR-SEC-02 | P0 | W1 | pass | G1 test_body_caps; live FATHOM_MAX_UPLOAD_MB=1: 2 MB -> 413 (also chunked), 0.5 MB -> 201 |
| FR-SEC-03 | P0 | W1, W5 | pass | G1 test_csrf_rule; live multipart/text/urlencoded without X-Fathom -> 403; cookie + foreign Origin -> 403 |
| FR-SEC-04 | P0 | W1 | pass | G1 test_security_headers; live headers per route class |
| FR-SEC-05 | P0 | W1, W2 | pass | G1 test_user_file_headers; live txt attachment + sandbox CSP, SVG sanitized |
| FR-SEC-06 | P0 | W1 | pass | G1 test_no_secrets_exposed; live secret.key 0600, key/hash/password/LLM key absent from 9 endpoints, builds, log |
| FR-SEC-07 | P0 | W1 | pass | G1 test_concurrent_changes_lock |
| FR-SEC-08 | P0 | W1 | pass | G1 test_500_has_no_trace; live bad JSON/ops -> 400 JSON, no traceback in body or log |
| FR-A11Y-01 | P0 | W3, W4, W5 | pass | M: dialog traps focus (25 Tabs), Esc closes, focus returns to opener; keyboard-only connect; Cmd+K/Cmd+J |
| FR-A11Y-02 | P0 | W3, W4, W5 | not verified | G7 test_aria_landmarks pass; live region announces commits; VoiceOver not run (one unlabelled inspector textarea) |
| FR-A11Y-03 | P0 | W3, W4, W5 | pass | M: contrast text 15.7:1, muted 6.1-6.5:1, accent 7.9:1, pills 6.4-7.1:1; media differ by dash |
| FR-A11Y-04 | P0 | W3, W4, W5 | pass | Close-out: D10 verified fixed (0 transitions on 5 viewer pages under reduce); app shell 0 |
| FR-UX-01 | P0 | W5 | pass | Close-out: D8 verified fixed (autosave off: 2 pending, then Saved · r4 after Cmd+S); Read-only, Offline - n pending, Conflict observed |
| FR-UX-02 | P0 | W5 | pass | G7 test_deep_link_selection; /?p=sunday-demo -> #/sunday-demo/main/patch |
| FR-UX-03 | P0 | W5 | pass | G7 test_view_error_card |
| FR-UX-04 | P0 | W5 | pass | M: inspector for device, port, cable, rack, floor plan, marker; edits round-trip |
| FR-UX-05 | P0 | W5 | pass | M: autosave off queues edits (no revision), Cmd+S flushes 2 edits as 1 revision; indicator issue in D8 |
| FR-UX-06 | P0 | W5 | pass | M: New project dialog (blank + 2 samples) created qa-new; Settings fields; JSON view Apply -> r37 source put |
| FR-UX-07 | P0 | W5 | pass | M: Imports, History, Builds, Settings tabs (venues/rooms, systems/locations, networks, templates, users, sharing, offline) render, errors [] |
| FR-UX-08 | P0 | W3, W4, W5 | pass | M: CSS variables equal the spec palette; system font stack, document.fonts.size 0 |

§2.3 compatibility row (§9 item 196): pass. `tests/test_fathom.py` 12 tests pass unchanged; `test_compat.py::test_public_v1_functions_exist` and `test_py39_forbidden_syntax` pass; G2 and G5 pass on Python 3.9.6; WSGI entry and Docker command unchanged (G12).

## 5. Defects

Severity follows the FR's priority. Every defect below is on a P0 requirement. Close-out status (section 0): D1-D4 and D6-D14 verified fixed; D5 still failing for the plural question. Repro paths assume `FATHOM_DATA=$(mktemp -d) python3 -m fathom serve --port 18101`, `python3 -m fathom new cd --template campus-demo`, and `sunday-demo` loaded from the fixture.

### D1 - Build pages link to viewer URLs that do not exist in the build folder
- FR: FR-EXP-04 (also §5.9 "All internal links in a build are relative so the folder works from file://"). Severity P0. Owner: W2 (`export.write_build`).
- Repro: `python3 -m fathom build cd`; open `<run>/rooms/main/patch.html` or `<run>/devices/foh-cl5.html` from `file://`; follow any device or room link.
- Expected: room pages link to `../../devices/<dev>.html`, device pages link to `../rooms/<room>/index.html`, all resolving inside the run folder.
- Actual: the room index, room patch pages and all 73 device pages use the live-viewer link style: `rooms/main/patch.html` links `../../d/rio-sl`; `devices/foh-cl5.html` links `../r/main`, `../d/ulxd-main`, `../rooms`, `../r/main/patch`. 729 of 902 relative links in those pages point at missing files; 0 room-to-device and 0 device-to-room links resolve. Only the map pages' nav links (`../../rooms/index.html`, `../../report.html`) work.
- Evidence: `/tmp/qa/links.py` output. Cause: `export.py` lines 305 and 315 call `render_patch_page` / `render_room_index` (and the device page renderer) without `link_style="build"`, which W5's renderers support (`render_html.py` 744, 856, 976; requested in `docs/notes/W5.md`).

### D2 - Device pages show MAC addresses unnormalized
- FR: FR-NET-04. Severity P0. Owner: W5 (`render_html.render_device_page`; FR owners W2/W4, `network.normalize_mac` exists).
- Repro: `GET /p/cd/d/foh-cl5`, `/p/cd/d/ulxd-main`, `/p/cd/d/switcher`; same in `<run>/devices/*.html`.
- Expected: `ac:44:f2:a1:00:10`, `00:0e:dd:31:00:31`, `7c:2e:0d:11:22:33`.
- Actual: `AC44.F2A1.0010`, `00-0E-DD-31-00-31`, `7c2e0d112233` (raw stored values). The IP schedule normalizes correctly.
- Evidence: `/tmp/qa/dev-*.html`; `desk-viewer-cd-dev.png`; `render_html.py:917` prints `i.get("mac")` directly.

### D3 - HTTP trace returns no paths when `from` is a bare device id
- FR: FR-TRC-04 (§5.8 `from=<dev[:port]>`). Severity P0. Owner: W1 (`server.r_trace_v2`).
- Repro: `curl 'http://127.0.0.1:18101/api/v2/projects/sunday-demo/trace?from=restream&direction=up'`; also `from=sound-board&direction=down`, `from=atem-mini&direction=up`, `cd from=ch-spk-l&direction=up&discipline=audio`.
- Expected: paths for any port of the device, as the CLI gives (`fathom trace sunday-demo restream --up` prints 23 paths).
- Actual: `{"paths": []}` for every bare-device query. With a port (`from=restream:usb-in-1`) the API returns 23 paths.
- Evidence: shell transcript; `server.py` `node()` turns a portless ref into `"<dev>:*"`, a node W6 only creates for devices with device-level endpoints, while `trace` accepts a bare id as "any port" (`docs/notes/W6.md` item 8).

### D4 - Downstream trace from an output port walks back into the device
- FR: FR-TRC-01 (cable edges direction from to; internal edges by routing). Severity P0. Owner: W6 (`trace.port_graph` / `downstream_paths`). Also flagged in `docs/notes/W2.md`.
- Repro: `curl 'http://127.0.0.1:18101/api/v2/projects/cd/trace?from=foh-cl5:omni-out-1&direction=down'` or `fathom trace cd foh-cl5:omni-out-1`.
- Expected: the cabled path `FOH CL5 · Stream L → Main switcher · Stream mix L → …` (cable c-0049) and onward.
- Actual: 50 paths, all of the form `FOH CL5 · Stream L → FOH CL5 → AES Out` / `→ Omni Out 3` / `→ Dante Primary → …`; none reaches the switcher. The output port connects to the device's `dev:*` node, which fans out to the device's other outputs.
- Evidence: shell transcript (0 of 50 paths contain `switcher`).

### D5 - Assistant gives wrong answers on campus-demo speaker questions
- FR: FR-AST-02 (fixture acceptance criterion passes). Severity P0. Owner: W6 (`assistant.py`).
- Repro: `fathom ask cd "Chapel speaker L has no sound" --room chapel --no-llm`; `fathom ask cd "The chapel speakers have no sound" --room chapel --json --no-llm`.
- Expected: upstream path `Chapel mixer · Analog In … → Omni Out 1 → Chapel speaker L` (cable c-0086 `ch-mixer:omni-out-1 → ch-spk-l:input-1`, analog) with checks.
- Actual: first question answers "I couldn't trace a audio path into **Chapel speaker L**: none of its inputs carrying audio are patched." with 14 notes "Input 1 on Chapel speaker L also carries audio, but its source (Chapel mixer · Analog In 10) is not patched." Input 1 is patched. Second question resolves the target to `ch-atem` (Chapel ATEM), traces the camera audio, and returns 48 notes of the form "Network 1 on Chapel camera also carries embedded audio, but its source (Chapel mixer · Analog In 12) is not patched." The API trace `from=ch-spk-l:input-1&direction=up` does find the mixer path.
- Evidence: shell transcript.
- Close-out: the first question is fixed. The second still resolves to `ch-atem` (targets `['ch-atem']`, summary "Here is how the signal reaches Chapel ATEM: Chapel camera · Audio In → HDMI Out → Chapel ATEM."), also for "Chapel speakers have no sound" and "No sound from the chapel speakers".

### D6 - Assistant path chips do not select the device
- FR: FR-AST-06 (AC: "Clicking a chip selects that device in the inspector"). Severity P0. Owner: W5 (`assistant-ui.js` / shell selection).
- Repro: `/#/as1/main/patch` at 1400x900, open the assistant, ask the livestream question, click the "ATEM Mini · Stream" chip.
- Expected: device (or port) selected, `?sel=` in the hash, inspector shows ATEM Mini.
- Actual: the highlight works (3 cards, 2 wires lit), but the hash stays `#/as1/main/patch`, no card has a selected class, and `#app-inspector` stays `display: none` with empty content, also after closing the drawer.
- Evidence: `/tmp/qa/ast2.py` output; `assistant-chip-click.png`.

### D7 - Patch table split view is broken unless the Patch view was opened first
- FR: FR-PT-04. Severity P0. Owner: W5 (`patchtable.js` split view; `app.js` loads `patchview.css` only when the Patch view mounts).
- Repro: fresh load of `/#/as1/main/table` at 1400x900 or 1920x1080, click "Split view".
- Expected: patch view above (styled canvas with cards), table below; re-patching updates the table.
- Actual: only `static/css/app.css` is loaded; the patch toolbar renders as unstyled stacked buttons, `.pv-viewport` is 1747 px tall inside a 385 px pane, and no cards are visible. After visiting the Patch view first (which loads `patchview.css`), split view works and the table updated within 0.4 s of a re-patch.
- Evidence: `table-split-1400.png` (broken), `table-split-via-patch.png` (working); `/tmp/qa/pt6.py` stylesheet list.

### D8 - Save indicator says "Saved" while edits are queued
- FR: FR-UX-01 (states include `3 pending`), related FR-UX-05. Severity P0. Owner: W5.
- Repro: set `settings.autosave` false; on `/#/pv/main/patch?sel=device:sub-x2` rename the device twice in the inspector.
- Expected: indicator shows `2 pending` until Save or Cmd+S.
- Actual: indicator shows `Saved · r22` with 2 unsent edits (server revision unchanged); Cmd+S then writes revision 23. Offline pending (`Offline · 2 pending`) is shown correctly.
- Evidence: `/tmp/qa/ux3.py` output.

### D9 - Planned devices are not distinct on the signal-flow map
- FR: FR-PLN-02 (dashed border in patch view and map). Severity P0. Owner: W5 (`render_html.py` / `layout.py`).
- Repro: `GET /p/cd` (main room); `bc-ma3` has `status: planned`.
- Expected: dashed border (or equivalent planned styling) on the map card.
- Actual: `<div class="card hasbadge" data-id="bc-ma3" …>` is identical in style to installed cards; `render_html.py` uses `planned` only on the device page header. The patch view (dashed border) and tables (`planned` chip) are correct.
- Evidence: `/tmp/qa/cd-map.html`.

### D10 - Viewer map pages ignore prefers-reduced-motion
- FR: FR-A11Y-04. Severity P0. Owner: W5 (`render_html.py:49` `svg.overlay .lk{transition:opacity .15s}`).
- Repro: Chrome with `Emulation.setEmulatedMedia prefers-reduced-motion: reduce`, open `/p/cd`.
- Expected: no transitions or animations.
- Actual: 76 SVG link elements keep `transition-duration: 0.15s`. The app shell has 0 offenders under the same setting.
- Evidence: `/tmp/qa/misc1.py` output `reduced_motion_viewer`.

### D11 - Touch hit targets below 44 px under (pointer: coarse)
- FR: FR-MOB-02 (§6.11 rule 8). Severity P0. Owner: W5 (shell, patch table), W4 (inventory, racks), W3 (port rows).
- Repro: Chrome touch emulation 1180x820 (coarse pointer confirmed), views patch, table, racks, inventory.
- Expected: hit targets at least 44x44 px; port rows 32 px tall on touch.
- Actual: top-bar view tabs 40 px tall; undo, redo, search, user buttons 34x44; project and room selects 32 px tall; patch-table toolbar buttons 40 px tall, remove "×" 22x40, checkboxes 13x13; inventory filter 31 px tall and column checkboxes 18x18; rack 1U blocks 22 px tall; patch view port rows 28 px (`offsetHeight`), not 32.
- Evidence: `/tmp/qa/touch2.py` output.

### D12 - Room map shows duplicate cards for devices that live in other rooms
- FR: FR-MAP-01 (map per room from `flow_project(doc, room)`), related FR-ROOM-05. Severity P0. Owner: W2 (legacy Dante merge into the flow project), W1 (`flow_project` external devices). Known as `docs/notes/W2.md` open question 2.
- Repro: `GET /p/cd` (Main Auditorium) or the Map view of `cd`; build notes of any campus build.
- Expected: devices of other rooms appear at most as external ghosts.
- Actual: the main map has standalone cards `CHAPEL-TF` (Yamaha TF-Rack, the Chapel room's `ch-mixer`) and `BCAST-DM7` (Yamaha DM7 Compact, the Broadcast room's `bc-mixer`); build notes say "dante: added card for unplaced device 'CHAPEL-TF'". The overlay itself maps them to the real devices (no duplicate overlay device).
- Evidence: `desk-app-cd-map.png`; `/tmp/qa/cd-main.html` data-ids `chapel-tf`, `bcast-dm7`.

### D13 - Flow-map viewer page lacks viewport-fit=cover
- FR: FR-MOB-07 (§6.11 rule 2). Severity P0 (low impact). Owner: W5 (`render_html.py:460`).
- Repro: `GET /p/cd`, read `<meta name="viewport">`.
- Expected: `width=device-width, initial-scale=1, viewport-fit=cover` (as on `app.html`, `login.html` and the other viewer pages, `render_html.py:716`).
- Actual: `width=device-width, initial-scale=1`.
- Evidence: `/tmp/qa/misc1.py` output `viewer_viewport_meta`.

### D14 - Floor plan delete has no "also delete files" option (gap)
- FR: FR-PLAN-12. Severity P0 (gap; AC "campus-demo main room has 2 plans" passes). Owner: W4.
- Repro: Plan view, Delete plan.
- Expected: delete keeps files unless "also delete files" is chosen.
- Actual: only the entity is deleted; the option is not offered (`docs/notes/W4.md` item 8).

## 6. P1/P2 slips, not verified items, observations

P1/P2 slips: none. All 20 P1 FRs and the P2 FR (FR-IMP-09) pass.

Not verified, and what is needed:

| Item | Why | Needed |
| --- | --- | --- |
| FR-PV-07, FR-PV-18, FR-PLAN-09 (iPad Safari pinch, long-press) | no iPad; Chrome touch emulation passed | physical iPad with Safari 15+ |
| FR-MAP-03 (iPhone Safari tips) | no iPhone; emulation passed | physical iPhone |
| FR-INV-03 (photo upload on iPad) | desktop upload passed | physical iPad camera / photo picker |
| FR-A11Y-02 (VoiceOver) | ARIA test and live region pass; screen reader not run | VoiceOver session on macOS/iOS |
| FR-PV-15 iPad budget (2500 ms) | desktop only | A12+ iPad |
| FR-MOB-07 device quirks (keyboard overlap, safe areas on notch devices) | CSS rules present; D13 fixed at close-out | physical iOS devices |
| Safari macOS (browser matrix) | `open -a Safari http://127.0.0.1:18101/p/sunday-demo` opened a window, but AppleScript inspection blocked on a macOS Automation permission prompt; nothing could be read | grant Automation access or a manual Safari pass. A Safari window may still be open on that URL |
| FR-MOB-04 DevTools manifest pane | fields and icons checked by fetch | interactive DevTools |
| FR-USER-08 reset password | add, role, disable verified | one manual click-through |
| Firefox | best effort, not gated | none |

Observations (no FR acceptance criterion fails):

- O1: at 820x1180 (iPad portrait) the 12 view tabs sit in a 55 px wide horizontal scroll strip; only "Map" is visible (`topbar-820x1180.png`). At 1400 px "Settings" and "JSON" are cut off and need horizontal scrolling of the strip.
- O2: at 390x844 the patch toolbar takes about 270 px of height with chips stacked vertically (`phone-app-sunday-demo-patch.png`).
- O3: keyboard connect offered the device's own input first (`main-speakers:thru-2 → main-speakers:analog-in-2`, a self loop).
- O4: the RRC overlay has 0 `port_labels` and 0 `interfaces`, so CL5 channel names do not appear as overlay labels on RRC (campus shows 2 CL5 labels and 40 Videohub labels).
- O5: the conflict banner names the device by this tab's unsaved name ("Someone else changed VC from B").
- O6: assistant text "a audio path" (grammar).
- O7: `POST /api/v2/library` echoes `"source": "builtin"` when the posted body carries that key; listing then shows `custom` correctly.
- O8: hostile Dante XML (external entity, entity bomb) is rejected by the parser but still registered as an import (201) with a parse-error note.
- O9: G11's `pip wheel` leaves gitignored `build/` and `fathom_audio.egg-info/` in the repo root.
- O10: the patch-table port picker lists outputs of mismatched media (RF, HDMI) with "needs a converter?" warnings; allowed by §4.4.4.
- O11: `rack_overlap` is reported once per face (front and rear) for a full-depth collision, as W6 documents.
- O12: attachment display names keep the raw upload name (`../../../evil<script>.txt`); the stored file is `files/att-…/evil_script_.txt`.

## 7. Security checklist (§8.4), live probes

| # | Check | Result | Evidence |
| --- | --- | --- | --- |
| 1 | No file outside its root | pass | 22 variants (`..`, `%2e%2e`, `..%2f`, `%5c`, `//etc/passwd`, `%2fetc`, NUL) on `/static`, `/builds`, `/p`, `/api/v2/projects`, `/files`: 404 (NUL 400). Symlinks created in `files/<att>/` and in a build run folder pointing to `/tmp/qa/outside.txt`: 404 |
| 2 | Uploads capped, names sanitized, random ids | pass | `FATHOM_MAX_UPLOAD_MB=1`: 2 MB multipart 413 `too_large` (also chunked), 0.5 MB 201. Filename sanitized under `att-<hex>` |
| 3 | SVG sanitized; restrictive CSP, nosniff on user files | pass | `onload`, `<script>`, `javascript:`, `<foreignObject>/<iframe>`, external `href` removed; `default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox`; text file `Content-Disposition: attachment` |
| 4 | CSRF | pass | multipart, `text/plain`, urlencoded POST without `X-Fathom` 403 `csrf`; cookie session with foreign `Origin` 403, same origin 200 |
| 5 | PBKDF2 600k | pass | `pbkdf2_sha256$600000$…`, no plaintext in users.json; constant-time use covered by G1 |
| 6 | Cookie flags | pass | `HttpOnly; SameSite=Lax; Path=/; Max-Age=1209600`; `Secure` added with `X-Forwarded-Proto: https` |
| 7 | Roles on every mutating route | pass | viewer 403 on 15 write routes (v1 and v2, multipart included), editor 403 on users and project delete; G1 role matrix |
| 8 | No secrets in responses, logs, OpenAPI, builds | pass | 64-hex `secret.key` (0600), a PBKDF2 hash fragment, `qa:secret` and `FATHOM_LLM_API_KEY=sk-QA-SECRET-123` absent from `/api/openapi.json`, `/api/v2/meta`, `/api/meta`, `/api/docs`, session, users, project, doc.json, `/p/cd`, build folders and server logs; meta shows only `llm: {configured: true, model}` |
| 9 | No stack traces | pass | bad JSON, non-object body, bad op, wrong types: 400 JSON with message; no `Traceback` in server logs |
| 10 | LLM only when configured; never executes output | pass | unreachable endpoint gives `llm.used false, error "LLM endpoint unreachable (ConnectionRefusedError)"`, HTTP 200; G1 asserts no socket when unconfigured; suggestions require Yes |
| 11 | Safe XML, size and DXF bounds | pass | external entity `file:///…` not resolved ("undefined entity"); entity bomb stopped ("limit on input amplification factor"); 51 MB DXF 415 "floor plans are limited to 50 MB" (413 on the default 50 MB body cap); 600 000-entity DXF accepted truncated with warning "entity limit (500000) reached"; binary DXF 415; DWG 415 |
| 12 | Subprocesses as argument lists with timeouts | pass (G1) | covered by T1 tests; not probed live |

## 8. Performance (§8.2)

| Scenario | Target | Measured |
| --- | --- | --- |
| Patch view 150/600 first render (desktop Chrome) | <= 1500 ms | 75.2 ms (G1), 56.9 ms (G2), 73.3 ms (standalone G7 perf test), 59-65 ms (own CDP runs) |
| Patch view drag JS per frame | <= 16 ms | `__pvStats.lastDragFrameMs` 0.0-0.2 ms during a 60-step drag on the 150/600 harness |
| Pan/zoom | single transform | `.pv-world` carries one `translate3d(...) scale(...)`; pinch and wheel change only that |
| Campus-demo build without PDF | <= 10 s | `real 0m1.277s` |
| App shell load (cached) | <= 1.5 s to interactive | 0.23-0.24 s from navigation to first patch cards; domInteractive 25 ms |
| DXF limits | 50 000 entities <= 5 s (T1) | T1 soft test passes in G1; 600 000-entity upload converted (truncated at 500 000) in about 8 s |
| GET project, changes, RRC overlay | soft | T1 `test_perf_soft_targets` passes |

## 9. Screenshots

All under `/tmp/qa/shots/` (scratch; 167 PNG files). Main evidence:

- Gate walk, every view: `desk-app-<project>-<view>.png` (25 files), `ipadL-…`, `ipadP-…`, `phone-…` (sizes 1400x900, 1180x820, 820x1180, 390x844), viewer pages `*-viewer-*.png`, `*-login.png`.
- Patch view: `desk-app-sunday-demo-patch.png`, `pv-after-edits.png`, `pv-video-chip.png`, `pv-context-menu.png`, `pv-box-select.png`, `pv-picker.png`, `touch-longpress-menu.png`, `rrc-network-routes.png`, `room-switch-chapel.png`, `room-ghost-atem.png`, `viewer-readonly-patch.png`.
- Patch table: `desk-app-sunday-demo-table.png`, `pt-restream-block.png`, `table-pickport.png`, `table-split-1400.png` (D7), `table-split-via-patch.png`, `table-split-live.png`, `rrc-table-import-rows.png`.
- Assistant and search: `assistant-answer.png`, `assistant-highlight.png`, `assistant-chip-click.png` (D6), `map-assistant-highlight.png`, `search-palette.png`, `phone-assistant-sheet.png`.
- Map: `desk-app-cd-map.png` (D12), `map-groups-dialog.png`, `map-after-group-change.png`, `phone-viewer-tap1.png`, `phone-viewer-tap2.png`.
- Plans, racks, inventory: `desk-app-cd-plan.png`, `plan-walls-hidden.png`, `plan-measure.png`, `touch-plan-pinch.png`, `desk-app-cd-racks.png`, `rack-alt-drop.png`, `inventory-grouped.png`, `harness-floorplan-walk.png`, `harness-rack-walk.png`, `harness-schedules-walk.png`.
- Inspector, history, conflict, admin: `inspector-photo.png`, `history-view.png`, `conflict-banner.png`, `admin-users.png`, `login-page.png`, `imports-view.png`, `imports-inspect.png`.
- Offline: `offline-viewer-reload.png`, `offline-app-shell.png`, `offline-prefetched-device.png`, `offline-pending.png`.
- Layout: `topbar-1400x900.png`, `topbar-1180x820.png`, `topbar-820x1180.png` (O1), `topbar-390x844.png`, `topbar-1920x1080.png`.
- Device page with raw MAC (D2): `desk-viewer-cd-dev.png`.
