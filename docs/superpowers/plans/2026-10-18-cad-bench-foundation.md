# cad-bench Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-project `cad/` folders with git-backed checkpoint / try / revert / keep / back / forward, and a native local live bench that redraws exact hidden-line views on every slider move, keeps typed values exact, and flags bad parameters.

**Architecture:** Small stdlib-first Python modules under `scripts/` (`cadproj`, `cadvc`, `views`, `sense`, `bench_server`) behind one CLI, `scripts/cad.py`, whose routine output is one line. The live bench is `assets/live-bench.html`, served by `bench_server.py` on localhost; it reuses the existing recipe format (params / derive / cards / checks) and gets its drawings from the server instead of a hand-written `draw()`. Git is driven through the `git` CLI via `subprocess`.

**Tech Stack:** Python 3.12 (venv `C:\Users\gritp\cad-bench-venv`), build123d via `scripts/brep.py`, stdlib `http.server`, git ≥ 2.40 CLI, Node (for the page's JS tests), pytest (dev only).

**Spec:** `docs/superpowers/specs/2026-10-18-cad-bench-foundation-design.md`

## Global Constraints

- Local and offline only; Windows first, macOS/Linux not broken. Paths may contain spaces and be long; always pass paths as list args to `subprocess`, never through a shell string.
- `import brep as B`, never `import build123d` directly (font-scan crash on Windows).
- One line of output on success for every new command and for the server log; full detail only on failure.
- A CAD experiment never switches the user's branch, never moves `HEAD` except via `keep`, and never touches files outside `cad/`.
- Typed values are used exactly: no min/max clamp, no step snap. Sliders keep `step`.
- Exports (`cad/exports/`) are never versioned.
- Existing gates unchanged: `export_verified`, `wall_check`, `check_bench.py`. Existing `models/` examples keep working.
- No new runtime dependencies beyond the existing venv (`build123d`, `trimesh`, `numpy`). `pytest` is dev-only.
- Do not edit files the parallel assemblies branch owns: `scripts/assembly.py`, `scripts/mjcf.py`, `references/assembly.md`, and the "Assemblies" sections of SKILL.md / README.md.

## Review Focus

1. **Dirty firmware repo**: user has staged and unstaged non-CAD changes when they run checkpoint / try / revert / keep → those changes are byte-identical and still staged/unstaged exactly as before. Pinned in Task 2 (`test_non_cad_changes_untouched`).
2. **Path with spaces**: project at `.../my project/` → every command and the server work. Pinned in Task 1 (`test_project_in_path_with_spaces`) and Task 2 fixtures use a spaced temp dir.
3. **Build fails mid-drag** (fillet larger than the wall, etc.) → server answers `{"ok": false, "error": "<one line>"}`, page keeps the last good views and shows the error; server keeps running. Pinned in Task 5 (`test_build_error_is_reported_not_fatal`).
4. **Files created during an experiment** → `revert` removes them from `cad/`, and they are still recoverable from the abandoned try. Pinned in Task 2 (`test_revert_removes_new_files_and_keeps_them_recoverable`).
5. **Detached HEAD / merge in progress** → checkpoint, try and keep refuse with one line naming the state; nothing is written. Pinned in Task 2 (`test_refuses_on_detached_head`).

---

### Task 0: Dev test setup

**Files:**
- Create: `tests/conftest.py`, `tests/__init__.py` (empty)
- Modify: `.gitignore` (add `.pytest_cache/`)

**Interfaces:**
- Produces: fixtures `git_repo(tmp_path)` → `Path` of a fresh repo in a directory whose name contains a space, with one committed non-CAD file `firmware/main.c`; `plain_dir(tmp_path)` → `Path` of a non-repo directory with a space in its name. `sys.path` gets `scripts/` prepended.

- [ ] **Step 1:** `C:\Users\gritp\cad-bench-venv\Scripts\python -m pip install pytest`
- [ ] **Step 2:** Write `tests/conftest.py` with the two fixtures (set `user.name`/`user.email` locally in the fixture repo).
- [ ] **Step 3:** Run `python -m pytest -q` → `no tests ran`, exit 5 is fine.
- [ ] **Step 4:** Commit `test: add pytest scaffolding`.

### Task 1: Project folder (`cadproj`)

**Files:**
- Create: `scripts/cadproj.py`, `tests/test_cadproj.py`

**Interfaces:**
- Produces:
  - `class Project` (dataclass): `root: Path` (the working folder), `cad: Path`, `parts: Path`, `assemblies: Path`, `exports: Path`, `settings_path: Path` (`cad/.cad-bench.json`), `skill_scripts: Path`.
  - `open_project(working_dir: Path, create: bool = True) -> Project` — creates `cad/parts`, `cad/assemblies`, `cad/exports`, `cad/.cad-bench.json` (`{"auto_checkpoint": false}`), and `cad/.gitignore` containing `exports/` and `__pycache__/`; idempotent; never overwrites existing files. `create=False` raises `ProjectError` if `cad/` is missing.
  - `load_settings(p: Project) -> dict`, `save_settings(p: Project, s: dict) -> None`.
  - `class ProjectError(Exception)`.

- [ ] **Step 1: Failing tests**
  - `test_creates_layout`: after `open_project(plain_dir)`, the four dirs exist, settings == `{"auto_checkpoint": False}`, `cad/.gitignore` contains `exports/`.
  - `test_idempotent_and_non_destructive`: write `cad/parts/x.py` = "keep", call again, file unchanged.
  - `test_open_without_create_raises`: `open_project(plain_dir, create=False)` raises `ProjectError`.
  - `test_project_in_path_with_spaces`: works under `plain_dir` (name contains a space).
- [ ] **Step 2:** Run `python -m pytest tests/test_cadproj.py -q` → FAIL (module missing).
- [ ] **Step 3:** Implement `scripts/cadproj.py`.
- [ ] **Step 4:** Tests pass.
- [ ] **Step 5:** Commit `feat: per-project cad/ folder`.

### Task 2: Version control (`cadvc`)

**Files:**
- Create: `scripts/cadvc.py`, `tests/test_cadvc.py`

**Interfaces:**
- Consumes: `Project` (Task 1).
- Produces (all return a one-line `str` summary unless noted; all raise `VCError` with a one-line message on refusal):
  - `ensure_repo(p: Project) -> Repo` — `Repo(top: Path, cad_rel: str)`. Inside an existing repo: `top` = `git rev-parse --show-toplevel`, `cad_rel` = path of `cad/` relative to it. Outside a repo: `git init` **inside `cad/`**, `cad_rel = "."`.
  - `checkpoint(p, name: str | None) -> str` — commits only `cad_rel` paths (`git add -- <cad_rel>` then `git commit -m "cad: <name>" -- <cad_rel>`), so other staged/unstaged changes stay as they were. While an experiment is active, the commit goes onto the try ref instead (see `try_`), not onto the branch.
  - `try_(p, idea: str) -> str` — records `{"active": idea, "base": <HEAD sha>, "base_tree": <cad tree sha>}` in `<git-dir>/cad-bench/state.json`. Experiment commits are created with plumbing on `refs/cad-bench/try/<slug>` using a temporary `GIT_INDEX_FILE` (`read-tree HEAD`, `add -- <cad_rel>`, `write-tree`, `commit-tree -p <prev tip or HEAD>`, `update-ref`); `HEAD`, the branch and the real index are never touched.
  - `revert(p, reason: str) -> str` — snapshots the current `cad/` onto the try ref with message `abandoned: <reason>`, then restores `cad/` (including deleting files not present at base) to `base_tree`; clears `active`.
  - `keep(p) -> str` — makes the current `cad/` a normal commit on the current branch (`checkpoint` semantics, message `cad: keep <idea>`), tags the try ref as kept in state; clears `active`.
  - `back(p) -> str` / `forward(p) -> str` — move a cursor over the checkpoint list and restore `cad/` from that checkpoint without moving `HEAD` or rewriting history; `forward` past the newest is a no-op line.
  - `set_auto(p, on: bool) -> str`; `is_auto(p) -> bool` (reads `Project` settings).
  - `history(p, part: str | None = None) -> list[dict]` — newest first; each `{"sha","msg","when","kind": "checkpoint"|"try"|"abandoned"|"kept","track": "main"|<try slug>,"parent"}`; with `part`, only commits touching `cad/parts/<part>.*`.
  - `class VCError(Exception)`.
- One-line summary format: `<verb> <name> · <n> file(s) · <short sha>`; Task 6 appends the part-change summary.

- [ ] **Step 1: Failing tests** (use both `git_repo` and `plain_dir` via parametrize where marked [both])
  - `test_ensure_repo_outside_git_inits_in_cad` / `test_ensure_repo_inside_git_uses_existing`.
  - [both] `test_checkpoint_commits_only_cad`: after editing `cad/parts/a.py` and `firmware/main.c`, `checkpoint` → `git show --name-only HEAD` lists only `cad/...`.
  - `test_non_cad_changes_untouched`: stage one change and leave another unstaged in `firmware/`; run checkpoint, try, edit, checkpoint, revert, try, keep; finally `git diff` and `git diff --cached` for `firmware/` equal what they were before.
  - `test_try_does_not_move_head_or_branch`: `HEAD` sha and branch name identical before and after `try_` + experiment checkpoints.
  - `test_revert_removes_new_files_and_keeps_them_recoverable`: during a try, create `cad/parts/new.py`; `revert("too thin")` → file gone; `history()` contains an `abandoned` entry whose tree contains `new.py`, message contains `too thin`.
  - `test_keep_lands_on_branch`: after try + edit + `keep`, branch tip message starts `cad: keep`, file content present.
  - `test_back_forward_round_trip`: three checkpoints with distinct content; `back` twice → content of the first; `forward` twice → content of the third; `HEAD` unchanged throughout.
  - `test_refuses_on_detached_head`: detach HEAD; `checkpoint`, `try_`, `keep` raise `VCError` whose message contains `detached`; no new commits or refs.
  - `test_auto_setting_persists`: `set_auto(True)` then a fresh `open_project` → `is_auto` is True.
  - `test_history_filters_by_part`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `scripts/cadvc.py`. All git calls go through one helper `_git(repo, *args, env=None) -> str` that raises `VCError` with the first stderr line.
- [ ] **Step 4:** Tests pass.
- [ ] **Step 5:** Commit `feat: git-backed checkpoints, try/revert/keep, back/forward`.

### Task 3: Exact views (`views`)

**Files:**
- Create: `scripts/views.py`, `tests/test_views.py`

**Interfaces:**
- Produces:
  - `VIEWS = {"top": ((0,0,1),(0,1,0)), "front": ((0,-1,0),(0,0,1)), "side": ((1,0,0),(0,0,1)), "iso": ((1,-1,1),(0,0,1))}` (direction, up).
  - `project(part, names=("top","front","side","iso"), distance=1000.0, samples=24) -> dict[str, {"vis": list[polyline], "hid": list[polyline]}]` where polyline = `list[[x, y]]` rounded to 3 dp; lines sampled with 2 points, curves with `samples+1`. Uses `part.project_to_viewport(origin, viewport_up=up)`.
  - `to_svg(view: dict, width=320, height=240) -> str` — self-contained SVG, visible edges as `class="vis"` solid paths, hidden as `class="hid"` with `stroke-dasharray="4 3"`, `vector-effect="non-scaling-stroke"`, viewBox fitted to content with 6% padding, y flipped.
  - `sheet_svg(views: dict) -> str` — the four views in a 2×2 sheet with captions, for exports and history thumbnails.

- [ ] **Step 1: Failing tests** (fixture: the spike part — 80×60×30 box, vertical-edge fillet 6, shelled 2.4 open top, Ø8 cross-bore along X at z=15)
  - `test_all_views_present_with_hidden_edges`: four keys; `front` and `side` have ≥1 `hid` polyline (the cavity / bore are hidden there).
  - `test_bore_visible_in_side_view`: some `side` vis polyline is a closed loop with radius ≈ 4 (± 0.05) around (0, 15).
  - `test_svg_has_dashed_hidden`: `to_svg(...)` contains `class="hid"` and `stroke-dasharray`.
  - `test_speed`: rebuild + `project` of three views < 500 ms after warm-up (measured ~50 ms native; generous bound for CI noise).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Pass. **Step 5:** Commit `feat: exact hidden-line views from the kernel`.

### Task 4: Model loading + scaffold into `cad/parts`

**Files:**
- Create: `scripts/partmodel.py`, `tests/test_partmodel.py`
- Modify: `scripts/new_part.py` (MODEL template and `main()`)

**Interfaces:**
- Consumes: `Project`.
- Produces:
  - `load_model(path: Path) -> ModelModule` — imports a part file by path in an isolated module name (`cadpart_<stem>_<hash>`), with `scripts/` on `sys.path`; module must expose `PARAMS: dict`, `derive(P)`, `build(P)`. Re-import on mtime change.
  - `effective_params(model, params_json: Path | None) -> dict` — defaults overridden by `<name>.params.json` (only known keys, floats).
  - `build_part(model, P: dict) -> part` — `model.build(P)`.
- `new_part.py` changes:
  - New flag `--project DIR` (default: current working directory). Writes `cad/parts/<name>.py` and `.recipe.js` via `open_project`. Keep `--examples` to write into the skill's own `models/` (old behaviour, used for worked examples).
  - The generated model finds the skill via env `CAD_BENCH_SCRIPTS`, falling back to the absolute `scripts/` path baked in at scaffold time.
  - Generated `main()` exports to `cad/exports/<name>.stl` when the file lives in `cad/parts/`, else next to the file (examples).
  - Generated recipe: `file:"cad/parts/<name>.py"`, and `draw()` becomes optional (live bench draws from the kernel).

- [ ] **Step 1: Failing tests**
  - `test_scaffold_into_project`: run `new_part.py --project <plain_dir> --name spacer --params "w=40,t=3"` → `cad/parts/spacer.py` and `.recipe.js` exist; running the model with the venv python exits 0 and writes `cad/exports/spacer.stl`.
  - `test_load_model_and_params_override`: write `spacer.params.json` `{"w": 52.4}` → `effective_params(...)["w"] == 52.4` exactly.
  - `test_examples_still_work`: `python models/boss_plate.py` exits 0.
- [ ] **Step 2–4:** fail → implement → pass. **Step 5:** Commit `feat: scaffold parts into the project's cad/ folder`.

### Task 5: Live bench server

**Files:**
- Create: `scripts/bench_server.py`, `tests/test_bench_server.py`

**Interfaces:**
- Consumes: `open_project`, `load_model`, `effective_params`, `build_part`, `views.project`, `views.sheet_svg`, `cadvc.*`, `sense.sense` (Task 7; endpoint added there).
- Produces: `serve(project_dir: Path, port: int = 0, open_browser: bool = False) -> (server, url)`; CLI `python scripts/bench_server.py --project DIR [--port N]` prints exactly one line: `bench: http://127.0.0.1:<port>/  (<n> parts)`.
  - `ThreadingHTTPServer` bound to `127.0.0.1` only. Builds are serialized by one lock; each request carries `seq`; a build whose `seq` is older than the newest received for that part returns `{"ok": false, "stale": true}` without building (latest-value-wins).
  - Endpoints (JSON in/out):
    - `GET /` → `assets/live-bench.html`.
    - `GET /api/parts` → `[{name, label, params:[...recipe params], recipe_js: "<source>"}]` (recipe source read from `<name>.recipe.js`).
    - `POST /api/build {part, params, seq}` → `{ok, views:{top,front,side,iso}, volume, bbox, ms}` or `{ok:false, error:"<one line>"}`.
    - `POST /api/handoff {part, params}` → writes `cad/parts/<part>.params.json` (exact floats), returns `{ok, path}`; if auto-checkpoint is on, also checkpoints.
    - `GET /api/history?part=` → `cadvc.history`; `POST /api/vc {op: "checkpoint"|"try"|"revert"|"keep"|"back"|"forward"|"goto", arg}` → `{ok, line}`. `goto` restores `cad/` from a given sha (same mechanics as `back`).
    - `GET /api/thumb?sha=&part=` → `sheet_svg` of that part built from that commit's files (cached by sha).
  - No stack traces in responses or the log; the log prints one line per error.

- [ ] **Step 1: Failing tests** (start `serve(port=0)` on a temp project holding the scaffolded `spacer` part; use `urllib.request`)
  - `test_parts_listing`.
  - `test_build_returns_views_fast`: second build < 500 ms; four view keys.
  - `test_build_error_is_reported_not_fatal`: params making `build` raise → `ok:false` with a one-line `error` (no newline); a following valid build still returns `ok:true`.
  - `test_stale_request_skipped`: send seq 2 then seq 1 → the seq-1 response has `stale:true`.
  - `test_handoff_writes_exact_params`: `{"t": 0.4}` → file contains `0.4` exactly.
  - `test_binds_localhost_only`: server address host is `127.0.0.1`.
- [ ] **Step 2–4:** fail → implement → pass. **Step 5:** Commit `feat: local live bench server`.

### Task 6: Live bench page + exact typed values (both pages)

**Files:**
- Create: `assets/live-bench.html`, `tests/js/numbox.test.mjs`, `tests/test_pages_js.py` (runs the node test)
- Modify: `assets/bench-template.html:456` (`vals`), `:556-577` (`commitNumbox`), `:579-585` (`render` numbox formatting), `:636-658` (paste loader clamp)

**Interfaces:**
- Consumes: server endpoints (Task 5).
- Produces (shared by both pages, same code): a value store `VALUES[partKey][paramId]` that is the source of truth; `vals()` reads it, not the slider element.
  - Slider `input` → store = slider value.
  - Numbox commit → store = the parsed number exactly (no clamp, no snap); slider shows `min(max, max(min, v))`; box shows the real value with the box's own decimals (`String(v)`), plus a small "outside slider range" hint when outside. Unparseable → revert box to store value.
  - Paste-constants loader: values applied exactly; message lists any outside slider range as info, not as "clamped".
- `live-bench.html` layout: part picker; sliders + numboxes (same rules); four kernel views (from `/api/build`, latest-wins via `seq`, last good views kept on error with the error shown); recipe `cards` and `checks` evaluated client-side from `recipe_js`; **Hand these to Claude** → `/api/handoff`; **History** tab: branch graph from `/api/history` (main track and try tracks as lanes, abandoned tries dimmed with reason), node thumbnail from `/api/thumb`, buttons Go here / Compare with current (overlay current vs selected `sheet_svg`, differing paths highlighted) / Branch from here (`try` from that node).

- [ ] **Step 1: Failing tests** (`numbox.test.mjs` extracts the shared value-store functions from each page's `<script>` and runs them on stubs)
  - typed `0.4` on a step-0.5 slider → `vals().x === 0.4`;
  - typed `250` on a `max:200` slider → `vals().x === 250`, slider element value `200`;
  - typed `abc` → value unchanged;
  - pasted `const T = 0.43 * MM;` → `vals().t === 0.43`.
  Run for both `bench-template.html` and `live-bench.html`.
- [ ] **Step 2:** `python -m pytest tests/test_pages_js.py -q` → FAIL.
- [ ] **Step 3:** Implement both pages' value store; build `live-bench.html`.
- [ ] **Step 4:** Tests pass; `python scripts/check_bench.py assets/bench-template.html` still passes.
- [ ] **Step 5:** Manual check in the app's browser pane: start the server on a scaffolded part, drag a slider (views redraw), type 0.4 (stays 0.4), break the part (error shown, old views kept), Hand off (params.json written), checkpoint + try + revert from the History tab. One screenshot.
- [ ] **Step 6:** Commit `feat: live bench page; typed values are exact on both benches`.

### Task 7: Dimension sensing (`sense`)

**Files:**
- Create: `scripts/sense.py`, `tests/test_sense.py`
- Modify: `scripts/bench_server.py` (add `GET /api/sense?part=`), `scripts/cadvc.py` (`checkpoint` appends sensing flags count to its line when any)

**Interfaces:**
- Produces: `sense(model, P: dict, rel_step: float = 0.02) -> list[dict]`, each `{"kind": "redundant"|"no_effect"|"hard_coded", "params": [...], "detail": str}`.
  - Signature of a built part: volume, surface area, bbox min/max (6), and for every circular edge its radius and centre (sorted, matched by nearest centre between builds).
  - Nudge each parameter by `max(abs(v)*rel_step, 0.05)`; a build failure for a nudge is skipped with `detail` noting it.
  - `no_effect`: signature change below `1e-6` relative. `redundant`: two parameters whose change vectors have cosine ≥ 0.999 and both non-zero. `hard_coded`: a circular feature whose radius and centre never change under any nudge while the part's bbox does.
- One-line CLI summary: `sense <part>: 2 flags (redundant: inset~edge_gap; hard-coded: Ø4.0 hole at (10,0))` or `sense <part>: clean`.

- [ ] **Step 1: Failing tests** with small fixture models written in `tmp_path`:
  - `test_flags_redundant` (two params that both set the same width), `test_flags_no_effect` (unused param), `test_flags_hard_coded_hole` (hole at a literal 10 mm while width is a param), `test_clean_model_has_no_flags` (`models/boss_plate.py`).
- [ ] **Step 2–4:** fail → implement → pass. **Step 5:** Commit `feat: dimension sensing`.

### Task 8: CLI, change summaries, docs

**Files:**
- Create: `scripts/cad.py`, `tests/test_cli.py`
- Modify: `scripts/cadvc.py` (summary line gets the part delta), `SKILL.md` (workflow), `README.md` ("Where it's heading" → step 1 marked available; "What's inside" tree), `references/bench-artifact.md` (typed values exact; `draw()` optional with the live bench)

**Interfaces:**
- Produces: `python scripts/cad.py <cmd> [args] [--project DIR]` with `init | checkpoint [name] | try <idea> | revert <reason> | keep | back | forward | auto on|off | history [part] | serve | sense <part> | drawing <part>`; `drawing` writes `cad/exports/<part>.svg` (`views.sheet_svg` at effective params), which is what the shared claude.ai bench shows for that part (its recipe's `draw()` returns that SVG). Section views are left out (spec marks them optional). Each command prints exactly one line on success, exits non-zero with one line on `VCError`/`ProjectError`.
  - Part delta appended to checkpoint/keep/revert lines when exactly one part changed: `volume +2.1 cm³, bbox 80×60×30 → 90×60×30` (volume and bbox from `build_part` at effective params, before vs after).

- [ ] **Step 1: Failing tests**: `test_each_command_prints_one_line` (subprocess, stdout has exactly one line for each command in a sequence init→checkpoint→try→checkpoint→revert→keep→back→forward→auto on→history); `test_error_is_one_line_and_nonzero` (detached HEAD).
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5:** Update SKILL.md: new section "0. Project folder" (invoke in the user's working folder; `cad.py init`), §2 scaffold uses `--project`, new "Version control" section with the plain-word commands mapped to `cad.py`, §5 "Bench page" becomes "Live bench" (`cad.py serve`, open in the browser pane; claude.ai bench kept for sharing), §6 read-back is local `params.json`. Keep the token-economy rules; add: never print git output, never poll the server.
- [ ] **Step 6:** `python -m pytest -q` all green; `python scripts/check_bench.py assets/bench-template.html` passes; `python models/enclosure.py` passes.
- [ ] **Step 7:** Commit `feat: cad.py CLI, change summaries; docs for project folders, version control, live bench`.

### Task 9: Install into the user's account

**Files:** none in the repo.

- [ ] **Step 1:** Push the branch, merge to `main` (user has approved merging), push.
- [ ] **Step 2:** Update the installed skill at `C:\Users\gritp\.claude\skills\cad-bench` to match `main`. Ask the user before overwriting anything there; preferred: rename the old folder to `cad-bench.old-2026-10-18` and clone `main` into `cad-bench`, so nothing is lost.
- [ ] **Step 3:** Verify: fresh session-style smoke test from an empty temp folder — `cad.py init`, scaffold a part, `cad.py serve`, one build request, `cad.py checkpoint`. Then diff installed vs `main` (content, ignoring CRLF) → identical.
