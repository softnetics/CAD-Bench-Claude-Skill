# cad-bench foundation: project folder, version control, live local bench

Status: design, approved for planning 2026-10-18. Project 1 of 3 (see *Roadmap*).

## Intent

cad-bench today designs one part at a time, keeps the user's models inside the
skill's own folder, has no history, and shows each part as a hand-traced SVG
sketch that silently misses features the model has (holes, fillets, hidden
pockets). The user wants to:

- **experiment safely**: try a new feature on an existing part, and go back if
  it turns out not to be possible, or forward again if they change their mind;
- **see the real part while tuning it**: exact top / front / side views that
  can't miss a detail, updating as a slider moves;
- **type the number they mean**: 0.4 mm is 0.4 mm, not snapped to a 0.5 grid
  or clamped to a slider's range;
- **trust the parameters**: the skill should notice when two sliders fight
  over one dimension, when a slider does nothing, or when a feature is pinned
  by a typed-in number instead of a parameter.

This is the base the later projects (assemblies, simulation) stand on: they
need a per-project folder, a history, and a live kernel to talk to.

## Roadmap (context, not in scope here)

1. **Foundation** (this document).
2. **Assemblies**: parts declare named connection points (origin + axis)
   computed from their own parameters; an assembly file joins them (fixed,
   revolute, slider, wheel, ...). Under-defined placement warns (it does not
   block); overlaps after a rebuild and connection points that don't follow a
   resize are flagged. Outputs: placement report with connector markers, STEP
   of the assembly, a MuJoCo model.
3. **Simulation**: MuJoCo, local and free. Real part specs (Claude finds the
   datasheet from a part number), motor limits, an animation of the assembly
   moving, and a feasibility verdict: on failure, the analysis plus the
   minimum specs that would work (no shopping list).

## Goals

### 1a. Project folder and version control

- **Project = one part or one machine.** Invoking the skill in any working
  folder creates (or reopens) a `cad/` folder there holding everything for
  that project. The skill folder holds only the tool and its examples.
- Suggested layout (builder may refine):
  ```
  <working folder>/cad/
    parts/<name>.py, <name>.params.json, <name>.recipe.js
    assemblies/            (project 2)
    exports/               STL / STEP / drawings -- rebuildable, not versioned
    .cad-bench.json        project settings (e.g. auto-checkpoint on/off)
  ```
- **History is git**, hidden behind plain words. The user never types git.
  - `checkpoint [name]`: snapshot now. **Manual by default.**
  - `auto checkpoints on|off`: when on, a checkpoint at every model change.
    The setting persists per project.
  - `try [idea]`: start an experiment; the working version is untouched.
  - `revert`: abandon the experiment, back to where it started. The failed
    attempt is **kept** on the graph with a one-line reason.
  - `keep it`: the experiment becomes the main version.
  - `back` / `forward`: step through checkpoints like undo/redo, surviving
    across sessions.
- **A snapshot covers** the part's model, slider values and recipe (and, from
  project 2, assemblies) together, so reverting can never desync them.
  Exports are not stored.
- Each step reports one line, e.g. `+4 clips, volume +2.1 cm³, min wall 2.0 → 1.6 mm`.
- **Inside an existing git repo** (e.g. an ESP-IDF firmware project): CAD
  checkpoints are **ordinary commits in that repo's history, next to firmware
  commits** (user's decision). Those commits only ever contain `cad/` paths;
  uncommitted non-CAD changes are never swept in. *Builder's call, flagged:*
  CAD experiments must never switch the user's branch or touch non-CAD files
  (plain `git checkout` of a branch would); `keep it` lands the result as a
  normal commit on the current branch. One way: keep experiment tips on
  private refs (e.g. `refs/cad-bench/try/<name>`) and materialise only `cad/`
  from them.
- **Outside a git repo**: the skill initialises a repo scoped to `cad/`.
- *Builder's call, flagged:* `back` / `forward` restore `cad/` files from a
  checkpoint without rewriting history or moving `HEAD`; the next checkpoint
  records the state. History is per project, and the graph for one part shows
  the commits that touched that part.

### 1b. Live local bench

- **Route A, chosen after measurement**: a native local Python server keeps
  build123d/OCCT imported and warm; the bench page is served from it on
  `localhost` and opened in the app's browser pane. Claude starts it in the
  background when a bench is needed and it serves every part in the project.
  Measured on the user's machine (shelled, filleted box with a cross-bore):
  ~14 s kernel import once, then **~40-50 ms per change** for rebuild plus three
  hidden-line views.
- **Exact views from the kernel**, replacing hand-written `draw()` as the
  source of truth: top, front, side (+ iso), visible edges solid, **hidden
  edges dashed**, optional section views. Generated with build123d's
  `project_to_viewport`. They cannot omit a feature because they are
  projections of the real solid.
- **Slider → server → views**, latest-value-wins (drop stale requests while a
  rebuild runs). The existing checks (`checks()`) stay and update live.
- **Typed values are exact.** The number box has no min/max clamp and no step
  snapping; 0.4 stays 0.4. The slider keeps a `step` for dragging; a typed
  value outside the slider's range parks the slider at its end while the box
  shows the real value. Impossible values surface as red checks, and the
  model's own gates (`wall_check`, `export_verified`) still refuse a broken
  export. Currently the template clamps and snaps
  (`assets/bench-template.html`, the numbox handler near "Typed value: clamp");
  that behaviour is removed.
- **Hand-off becomes local**: "Hand these to Claude" writes
  `cad/parts/<name>.params.json` directly (no artifact database round-trip).
- **Dimension sensing** (run on demand and at each checkpoint): nudge each
  parameter, rebuild, measure features (hole diameters, wall thicknesses,
  feature positions, volume, bbox), and report:
  - **redundant**: two parameters that move the part identically, with a
    suggestion to make one derived;
  - **no effect**: a parameter that changes nothing;
  - **hard-coded**: a feature that never moves under any parameter, with an
    offer to promote it to a slider.
  Report only flags; never rewrite the model silently.
- **History tab** on the local bench page: branch graph per part, each node a
  checkpoint with its exact drawing thumbnail and one-line change summary;
  abandoned tries shown with their reason. Clicking a node offers *Go here*,
  *Compare with current* (overlay, changes highlighted), *Branch from here*;
  the server performs them directly on the git history.
- The **claude.ai CAD Bench artifact stays** for viewing from other devices
  and sharing; it shows the last exact drawing (as a static SVG), not live
  views.

## Non-goals

- Running the kernel inside a claude.ai artifact. Tested 2026-10-18: build123d
  runs in a normal web page via OCP.wasm + Pyodide (~0.25 s per change, ~56 MB
  trimmed), but the OCP kernel is a single 145 MB WebAssembly module and
  artifacts cap binary files at 15 MB and refuse archives. Not to be worked
  around by disguising file types.
- Onshape or any cloud CAD (token cost; free-plan limits).
- Assemblies and simulation (projects 2 and 3).
- A git UI for non-CAD files.

## Anti-goals (would make this a failure even if it "works")

- A CAD experiment that moves firmware files or the user's branch.
- A typed value that silently becomes a different number.
- Views that can drift from the model (a second hand-written copy of the geometry).
- Chatty tooling: routine success prints more than one line (cad-bench's
  existing token rule applies to every new command and to the server log).
- A revert that loses work: abandoned tries are always recoverable.

## Constraints

- Local and offline; Windows first (the user's machine), macOS/Linux should
  not be broken.
- Reuse the existing venv (`build123d`, `trimesh`, `numpy`); new dependencies
  only if clearly needed. `import brep as B`, never `build123d` directly.
- Existing gates are unchanged: `export_verified`, `wall_check`, `check_bench.py`
  (extend it for the no-clamp numbox behaviour).
- Existing worked examples in `models/` keep working.

## Left to the builder

Server framework and protocol (HTTP vs WebSocket), page structure, ref naming
for experiments, exact layout file names, thumbnail format, how the feature
measurements for dimension sensing are chosen, how a part is "opened" on the
server, and migration of any parts a user already has under the skill's
`models/` into a project `cad/` folder.
