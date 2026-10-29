# Fathom: notes for coding agents

Fathom is an AVL (audio, video, lighting) documentation web app: a stdlib-only
Python WSGI server (`fathom/server.py`) plus a no-build ES-module frontend in
`fathom/static/`. The full contract is `docs/SPEC.md`; the module map is in
`README.md` under *Development*.

## Conventions

- **No runtime dependencies.** `pyproject.toml` has `dependencies = []`; only
  `gunicorn` (serve) and `pytest` (dev) are optional. Keep Python 3.9 syntax.
- **Frontend is ES2018** (Safari 15+): no `?.`, `??`, class fields, etc.
  `tests/js/syntax.test.mjs` enforces it. No bundler; files are served as-is.
- **Routes** are registered with `@route(method, regex, role=...)` in
  `server.py`. A new route must also be listed in `SPEC_ROLES` in
  `tests/test_security.py` (and get a `PARAM_HINTS` entry for new path
  parameters), or the route/role and OpenAPI tests fail.
- Engine modules are imported lazily inside handlers; follow that pattern.
- All data lives under `FATHOM_DATA` (default `~/.fathom`; `/data` in Docker).
  Writes are atomic and per-project locked (`project.project_lock`).
 `DELETE /api/v2/projects/<n>` moves a project to `<data>/trash/` (30-day
 retention; `fathom trash list|restore|purge`); `?purge=1` deletes for good.
 Devices get an 8-char `short_code` on save (`/c/<code>` resolves it).

## Frontend conventions

The contract is `docs/SPEC.md` §6.4 (shell, router, ctx), §6.13 (shared
components) and §6.14 (storage keys).

- **Shared components** live in `fathom/static/js/`, each a DOM module plus a
  pure `*-core.js` that imports in Node: `router-core.js`, `explorer.js`,
  `entity-header.js` (+ `entity-core.js`), `datatable.js`, `drawer.js`,
  `search.js`, `home.js`, `feedback.js`, `wizard.js`; CSS in
  `fathom/static/css/<name>.css` with its prefix (`ex-`, `eh-`, `dt-`, `dr-`,
  `sr-`, `hm-`, `fb-`, `wz-`); a harness in `fathom/static/dev/<name>.html`.
  Build views from them; do not re-implement a list, drawer or state.
- **Rack components** (SPEC §4.4.7, §6.7–6.7.3, §6.13.11): `rack-core.js`
  (placement, items, shelves, totals, ops; pure), `rack-elevation.js` (the
  drawn racks, `rk-` in `rack.css`; the landing and the rack page build on
  `createElevation`, and the library drops in through `beginExternalDrag` /
  `onExternalDrop`), `rack.js` (the racks landing, `rkt-` in
  `rack-toolbar.css`), `page-rack.js` (the rack page, `rp-` in
  `page-rack.css`), `rack-display.js` (+
  `rack-display-core.js`: block colours, images, annotations, template info),
  `rack-palette.js` (+ `rack-palette-core.js`, `rpal-`, harness
  `dev/rack-palette.html`) and `rack-export.js` (+ `rack-export-core.js`,
  `rx-`, harness `dev/rack-export.html`). Rack rules mirror `fathom/racks.py`
  and are pinned for both languages by `tests/fixtures/rack_contract.json`.
  UI suites: `test_ui_rk` (the original elevation contract), `test_ui_rk_elev`
  (elevation), `test_ui_rk_landing` (landing), `test_ui_rk_page` (rack page),
  `test_ui_rk_regress` (cross-app regressions), `test_ui_rack_palette`,
  `test_ui_rack_export`.
- **DOM helpers:** `h(tag, attrs, children)`, `esc(s)` and `on(target, type,
  fn)` → `off()` from `dom.js`.
- **Routes:** `#/<project>/<room>/<view>[/<seg4>[/<seg5>[/<seg6>]]][?<query>]`,
  segments named per view by `router-core.VIEW_SHAPES` (e.g.
  `devices/<id>/<tab>/<sub>`); view, id or tab changes push, selection and
  table state replace; write with `ctx.navigateRoute` / `ctx.setParams`.
- **Storage keys** start with `fathom.ui.` (table in SPEC §6.14).
- **Breakpoints:** `layoutFor(width)` → sm < 700, md 700–1099, lg ≥ 1100;
  44 px targets under `(pointer: coarse)`.
- **Every list uses `datatable.js`** (`createTable`, `openTableDialog`).
  Exempt (D9): patch-table blocks, the label sheet, SOP Markdown tables,
  inspector editor grids, picker dialogs (including the rack palette list),
  the search list, explorer lists,
  the drag lists `#rk-unracked` / `#fp-unplaced`, the JSON view and viewer
  pages.
- **UI tests** (`tests/test_ui_*.py`) drive headless Chrome through
  `tests/_ui.py` (`UiCase`, `open(path, size)` with sizes `d`/`t`/`m`,
  `click`, `press`, `wait_for`, `intercept`, `shot`); they skip without
  Chrome. Set `FATHOM_UI_SHOTS=<dir>` to save screenshots. To hold a request
  open (loading states), copy the `Hold` helper from
  `tests/test_ui_states_shell.py`.

## CI

`.github/workflows/ci.yml` runs on every pull request and on pushes to
`main` (Ubuntu, Python 3.12, Node LTS, Google Chrome stable as
`FATHOM_CHROME`): `python -m unittest discover -s tests`,
`node --test tests/js/*.test.mjs` and `fathom selftest`, about 20 minutes
end to end (the `Tests` job has a 45-minute timeout). Logs are uploaded as
an artifact when a step fails. The `Tests` job installs `.[serve,discovery]` when the `discovery` extra exists in
`pyproject.toml`, else `.[serve]`.

- **Approve PR** posts an approving review from `github-actions[bot]` on
  same-repo PRs once tests pass (skipped if one is already there). Needs
  Settings → Actions → General → Workflow permissions → "Allow GitHub Actions
  to create and approve pull requests".
- **Auto-merge worker PR** squash-merges non-draft PRs from `cursor/*`
  branches into `main` (deleting the branch) after the approval; stacked
  PRs whose base is another branch are left alone. It is on by default;
  switch it off with the repository variable `AUTO_MERGE_WORKER_PRS=false`
  (Settings → Secrets and variables → Actions → Variables). It uses
  GitHub-native auto-merge when "Allow auto-merge" (Settings → General →
  Pull Requests) and required status checks on the base branch exist, and
  merges directly otherwise. Merges made by the workflow token do not start
  a `push` run on `main`; the PR run is the record.
- A PR only gets a run once the workflow file is in its base branch (GitHub
  reads workflows from the PR merge commit); push a commit or close/reopen
  an older PR to start its first run.

## Application server

`ccc-apps01` (`10.6.9.239`) is the application server. The checkout is
`/home/cccadmin/Code/fathom` for user `cccadmin`, data is
`/home/cccadmin/.fathom`, and `fathom.service` is enabled and listens on
`http://10.6.9.239:8080`. Connect with SSH host `ccc-apps01`
(`HostName 10.6.9.239`, `User cccadmin`). Key login is already in place;
do not recreate the account, `.venv`, packages, or sample data on this host.
Open that checkout in Cursor with Remote-SSH. Restart `fathom.service` after
Python changes (`sudo systemctl restart fathom.service`); static JS/CSS
changes need only a browser reload. Port 8080 is taken by that service, so
do not start a second `fathom serve` on it.

## Cursor Cloud specific instructions

These steps apply to a Cursor-hosted cloud VM, not to a session already on
`ccc-apps01`. The environment (`.cursor/environment.json`) creates `.venv`
with `pip install -e '.[dev,serve]'`, installs `poppler-utils`, and seeds a
`campus` sample project in `~/.fathom`.

- **Dev server:** `start` (`.cursor/start.sh`) runs it on boot in the
 `fathom-server` tmux session at <http://localhost:8080> with login off
 (everyone is admin); log in `/tmp/fathom-server.log`, boot output in
 `/tmp/cursor/start-user/start-user.log`. After changing Python files,
 `tmux kill-session -t fathom-server && bash .cursor/start.sh`; JS/CSS
 changes need only a reload. The editor UI is at `/` (there is no `/ui`).
- **Backend tests:**
  `FATHOM_CHROME=/usr/bin/google-chrome-stable .venv/bin/python -m unittest discover -s tests -q`
  (1481 tests, about 24 min, most of it the `test_ui_*.py` Chrome suites; all
  pass with 8 skips when the `discovery` extra is installed, as in CI: the
  six `fits` cases of `test_rack_contract` (fit checks are JS only), the
  catalog regeneration check in `test_rack_catalog` (needs a
  Rackula checkout in `/tmp/rackula`) and the report PDF render in
  `test_exports` (set `FATHOM_T1_CHROME=1`)). This
  VM installs only `.[dev,serve]`, so two discovery tests skip and
  `test_discovery.ActiveGuard.test_snmp_pacer_counts_and_pauses` errors (no
  `puresnmp`); `.venv/bin/pip install -e '.[dev,serve,discovery]'` matches
  CI. Without `FATHOM_CHROME`
  the headless-Chrome smoke suite picks up `/usr/local/bin/google-chrome`, a
  desktop wrapper that pins `--remote-debugging-port=9222`; its parallel runs
  then time out (~57 failures, 15 min). To leave out the `test_ui_*.py`
  suites run `-p 'test_[!u]*.py'` and `-p 'test_u[!i]*.py'` (keep
  `FATHOM_CHROME` set; `test_frontend_smoke.py` still uses Chrome). Single suite:
  `FATHOM_CHROME=/usr/bin/google-chrome-stable .venv/bin/python -m unittest discover -s tests -p test_backup.py -v`
  (not `python -m unittest tests.test_backup`: the `discovery` extra installs
  `x690`, whose stray top-level `tests` package shadows ours).
- **Frontend tests:** `node --test tests/js/*.test.mjs` (769 tests; pass the
  files, the bare directory form fails on recent Node).
- **End-to-end check:** `.venv/bin/fathom selftest`.
- **Calling the API with curl:** mutating requests need `X-Fathom: 1`
  (CSRF guard), e.g.
  `curl -X POST -H 'Content-Type: application/json' -H 'X-Fathom: 1' -d '{}' localhost:8080/api/v2/backups`.
  Route list: <http://localhost:8080/api/docs>.
- **Testing with a login:** run a second server with its own data dir, e.g.
  `echo admin-password-1 | FATHOM_DATA=/tmp/fathom-auth .venv/bin/fathom user add admin --role admin --password-stdin`
  then `FATHOM_DATA=/tmp/fathom-auth .venv/bin/fathom serve --port 8081` and
  sign in at `/login` (or use HTTP basic auth with curl: `-u admin:admin-password-1`).
- Tests create throwaway data dirs (`tests/_helpers.py: temp_data_dir`);
  never point them at `~/.fathom`.
