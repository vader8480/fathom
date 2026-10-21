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
  (283 tests, about 30 s, all pass with one skip). Without `FATHOM_CHROME`
  the headless-Chrome smoke suite picks up `/usr/local/bin/google-chrome`, a
  desktop wrapper that pins `--remote-debugging-port=9222`; its parallel runs
  then time out (~57 failures, 15 min). Single suite:
  `.venv/bin/python -m unittest tests.test_backup -v`.
- **Frontend tests:** `node --test tests/js/*.test.mjs` (pass the files; the
  bare directory form fails on recent Node).
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
