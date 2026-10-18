---
name: cad-bench
description: >-
  Model a mechanical part in Python on an exact CAD kernel, let the user
  tune dimensions on an interactive slider page ("CAD Bench") showing binding
  constraints live, and export a verified printable STL. Fillets, chamfers,
  shells, lofts and sweeps are exact geometry. Use whenever the user wants to
  design, model or 3D-print a part -- bracket, mount, standoff, enclosure,
  housing, skirt, tray, spacer, adapter, duct, jig, knob, clip, gasket,
  fixture -- or adjust its dimensions against what binds (wall thickness,
  overhang, clearance, material around a bore) and re-export. Also for
  assemblies and machines: mechanism, robot chassis, joints, hinge, motor
  mount, wheel and shaft, exported as a STEP assembly and a
  MuJoCo/simulation-ready model. Trigger on "make me a bracket", "model a
  mount for X", "design an enclosure", "round the corners", "hollow it out",
  "parametric part", "tweak the dimensions and give me an STL", "export to
  STL", "CAD bench", "put these parts together", "assembly" -- even when no
  CAD tool is named.
---

# cad-bench

Model in Python against a real B-rep kernel, let the user dial dimensions on
a browser page, export a gated STL. No CAD account, no cloud round-trip.

One backend, always: `scripts/brep.py` wrapping build123d/OCCT. Plain
prismatic work goes through it too — there is no second path to choose and no
hand-computed volume to get wrong.

## Setup (once per machine)

```
python -m venv <path>/cad-bench-venv
<path>/cad-bench-venv/Scripts/python -m pip install build123d trimesh numpy
```

`build123d` pulls the OCCT kernel (~500 MB). `trimesh` reads the exported STL
back for verification. Record the venv path; every run uses its `python`.

## Workflow

### 0. Project folder

Parts live with the user's project, not in this skill. Work in the folder the
user is working in (pass `--project DIR` to run from elsewhere):

```
python <skill>/scripts/cad.py init
```

`<skill>` is this skill's folder; `python` is the venv's. `init` creates (or
reopens) `cad/` there:

```
cad/parts/            <name>.py, <name>.params.json, <name>.recipe.js
cad/assemblies/       <name>.py: parts joined into a machine (see Assemblies)
cad/rules/            <kind>.rules: confirmed rules for this project
cad/exports/          STL / STEP / drawings -- rebuilt on demand, never versioned
cad/.cad-bench.json   per-project settings (auto-checkpoint)
```

Inside an existing git repo (a firmware project, say) CAD checkpoints are
ordinary commits in that repo that only ever contain `cad/` paths; otherwise
`cad/` gets a repo of its own. The skill's `models/` holds worked examples
only.

### 1. Pin down the geometry and what binds

The feature tree: which primitives, where, combined in what order. Then the
constraints — not "plate is 60 mm" but "boss wall ≥ 2 mm around a heat-set
insert", "inner corner radius = corner_r − wall, must stay positive". These
become `wall_check()` calls in the model and check rows on the bench, and
they are the point: a bounding box cannot see any of them.

**When the retention/mounting MECHANISM itself — not just its dimensions —
is being inferred from a photo or hand sketch, confirm the mechanism before
building the feature tree, not after.** A photo of a keyhole cutout can be
read as "bolt through a round hole," "boss with a bore," "stadium slot," or
"round head + narrower neck" — each is a legitimate reading of the same
picture and each demands a structurally different model. Getting this wrong
doesn't surface as a `wall_check` failure or a bad boolean; the part builds
cleanly, passes every gate, and is simply the wrong mechanism, discovered
only when someone who knows the real hardware looks at it. If the next
change would replace how the part is HELD IN PLACE (not just resize it),
say back in one sentence what you think the mechanism is before writing the
new feature tree.

**Reverse-engineering an existing, source-less STL instead of designing
something new?** Different failure mode, different method — go to
`references/stl-reverse-engineering.md` before sampling a single point by
hand. Short version: `python <skill>/scripts/inspect_stl.py part.stl` lists every
distinct Z the mesh actually has vertices at (never guess sample heights —
a guessed list can straddle every feature boundary and miss them all), and
`--z <value>` separates a confusing multi-loop face into radius bands before
you try to read a shape off it. Gate the reconstruction against the
**original mesh's own volume**, not just its own tessellation's
self-consistency. And if a feature mates to something real outside the file
(a motor shaft, a bearing, a fastener), check that part's own spec before
trusting a literal reading — the STL can precisely measure someone else's
modelling mistake.

### 2. Scaffold, don't hand-write

```
python <skill>/scripts/new_part.py --project <working folder> --name spacer_plate \
    --params "plate_x=90,plate_y=50,plate_t=4,bore_d=30,hole_d=4.5,inset=8"
```

Writes `cad/parts/spacer_plate.py` (runnable immediately, builds a placeholder
box) and `cad/parts/spacer_plate.recipe.js` (sliders, cards, checks). Run the
model as-is to confirm the harness works, then replace `derive()`, `build()`,
and the recipe's `derive()`/`checks()`. Parameter names are already identical
on both sides, which is the one coupling that must hold. The recipe's `draw()`
is optional: the live bench draws exact views from the kernel (§5).
`--examples` writes into the skill's own `models/` instead -- only for a new
worked example.

### 3. Model it — the rules that prevent most failures

```python
import brep as B                      # NEVER `import build123d` directly
part = B.Box(80, 60, 30, align=(B.Align.CENTER, B.Align.CENTER, B.Align.MIN))
part = B.safe_fillet(part, B.vertical_edges(part), 6)
part = B.offset(part, amount=-2.4, openings=B.top_face(part))
part = B.safe_chamfer(part, B.outer_of(B.top_edges(part)), 0.8)
part -= B.Pos(0, -30, 8) * B.Box(16, 10, 9)
```

- **`import brep as B`, never `build123d`.** build123d scans every system font
  at import and does not catch parse errors; one malformed file (Windows 11
  ships `mstmc.ttf`, a stub) aborts the import and looks like a broken
  install. `brep.py` neutralises it. First import ~6 s; operations after are
  milliseconds.
- **Order: solid → fillet → shell → chamfer → internal features → bores.**
  Fillet while it is still solid; rounding after shelling makes the fillet
  negotiate a thin wall and it often just fails.
- **A shelled rim has TWO loops.** `top_edges()` returns both, and chamfering
  both eats the wall from each side. Use `B.outer_of(B.top_edges(part))`.
- **Never shell a loft.** Loft the outer profiles, loft the inner profiles
  (extended a mm past each end), subtract. Offsetting a doubly-curved surface
  is slow and usually fails.
- **`loft`, `revolve`, `sweep` need `with B.BuildPart()`** — they have no
  algebra form. Take `bp.part` out and go back to `+`/`-`.
- `safe_fillet` / `safe_chamfer` diagnose failures and report the largest
  radius that works, via `B.max_fillet(part, edges)`.

`references/brep.md` is a **lookup** — go to it for a specific operation,
selector or failure, not as a cover-to-cover read. `models/enclosure.py`
(fillet/shell/chamfer) and `models/duct.py` (loft) are usually the faster
answer.

### 4. Verify — the gate is not optional

```python
B.wall_check("inner corner radius", corner_r - wall, 0.5)
if B.solid_count(part) != 1: raise B.VerifyError("expected one solid")
B.export_verified(part, "part.stl", "part", expect_bbox=(lo, hi))
```

`export_verified` raises on: not watertight, winding inconsistent, volume
≤ 0, mesh volume more than 0.5% off the kernel's exact volume, or bbox off by
> 0.05 mm. **A failed export deletes the STL** rather than leaving a wrong
part on disk.

**Output is one line on success, full detail on failure, by design.** A
model gets run several times while it's being built and each run's stdout
comes back into your context — a dozen lines of routine watertight/bbox/radius
detail on every passing run is pure waste. Don't work around this by adding
your own extra prints or re-running "to see the numbers"; if you need the
full report while first writing a model, pass `verbose=True` to
`export_verified` / `verify` / `wall_check`. A failing gate always prints in
full regardless, because that's when the numbers are worth reading.

**A pass is a pass.** Do not re-export with a tighter `tolerance` because the
margin felt close — 0.4% against a 0.5% gate is fine, and halving tolerance
multiplies file size for detail no printer resolves. Tighten only when the
gate actually fails. Pass `step=True` for a STEP file alongside.

**Selection bugs do not raise.** If a fillet or chamfer targets a selected
edge set, prove it hit the right edges by differential volume: build with the
feature at zero, subtract, compare against what it should remove. Recipe in
`references/verification.md`.

**Watertight + correct volume is not proof there are no slivers.** A boolean
can pass every gate above while still carrying degenerate (near-zero-area)
triangles underneath them — measured on a real part, more than once, before
this was checked directly instead of inferred from a watertight/volume pass
or from how a tessellation *looked*. Check face area and edge-manifold count
directly; when a fix needs a tuned offset (a shave, an overlap), sweep a real
range on every variant the model ships rather than picking one cautious
number; and when adding a feature to an existing solid, prefer baking it into
the host's own profile over booleaning two independent tessellations
together. Full method, with the real numbers from where this went wrong
twice, in `references/verification.md`.

### 5. Live bench

```
python <skill>/scripts/cad.py serve
```

Start it **in the background** (it blocks) once per session. It prints one
line, `bench: http://127.0.0.1:<port>/  (<n> parts)`; open that URL in the
app's browser pane and point the user at it. One server serves every part in
the project and picks up model edits on the next slider move (no restart).

What the page does: a slider move rebuilds the part in the warm kernel and
redraws exact top / front / side / iso views (hidden edges dashed) in about
50 ms; the recipe's `cards` and `checks()` update with it. Typed values are
used exactly -- 0.4 stays 0.4, outside the slider's range too; an impossible
value shows as a red check or a build error, never as a silently different
number. A build error keeps the last good views up and shows the one-line
error. The History tab shows each part's checkpoints and tries with their
drawings and can go to, compare with, or branch from any of them. **"Hand
these to Claude"** writes `cad/parts/<part>.params.json` directly.

**Dimension sensing** -- `python <skill>/scripts/cad.py sense <part>` (also
run at each checkpoint, reported as `· sense: N flags`): nudges each
parameter, rebuilds, and reports redundant pairs, parameters with no effect,
and hard-coded features. It only flags; propose the fix to the user, never
rewrite the model on your own.

#### Sharing: the claude.ai CAD Bench artifact

For viewing from another device or sharing, the published CAD Bench artifact
stays: one artifact, a multi-part picker. It shows the last exact drawing as
a static SVG, not live views:

```
python <skill>/scripts/cad.py drawing <part>      # writes cad/exports/<part>.svg
```

and that part's recipe in the artifact gets a `draw()` that returns that SVG
string (it is sized for the page's 620×400 drawing area). First use: publish
`assets/bench-template.html` (declares the `db` capability -- read
`artifact-capabilities` first). Later parts: read the artifact, paste the
`.recipe.js` into `PARTS`, republish to the same URL.

**Before publishing, always:**

```
python <skill>/scripts/check_bench.py <bench.html>
```

It runs every recipe headlessly at defaults and at every slider extreme, and
fails on the bugs this format has. One: reading `d.plate_x` when `plate_x` is
a slider gives `undefined`, `undefined >= 2` is an ordinary `false`, and the
row goes **red like a real constraint failure** -- so you tune sliders chasing
a typo. Sliders are on `p`, computed values on `d`. Two: a hand-written
`draw()` whose views were scaled to fit their own content with no bound on
where the result lands, so a caption or a whole second view ends up drawn on
top of another shape. Three: a model `PARAMS` key with no slider, which the
page can never set. Field spec and the SVG helpers are in
`references/bench-artifact.md`; for a genuinely curved part,
`references/live-mesh-preview.md` covers a live 3D `mesh()` instead.

**"Always" includes republishing an existing part, not just a first-time
recipe.** The recipe's `derive()`/`checks()` and the model are two
independent implementations of one design -- nothing keeps a fix made in
`build()`/`derive()` from silently going stale in the recipe except this
lint. Re-run `check_bench.py` on *every* republish, including "just a small
model fix," and re-check whether the recipe's own default `val`s still pass
any check you just added -- a check added in response to a newly-found bug
can fail the shipped defaults, which means the bug was live in the stock
preset the whole time.

### 6. Read back, regenerate, deliver

When the user says they handed the values over, they are already in
`cad/parts/<part>.params.json`. Re-run the model -- it picks the file up
automatically and exports to `cad/exports/<part>.stl`:

```
python cad/parts/<part>.py
```

(Values handed over from the shared claude.ai artifact instead: read them
once with `Artifact action:read_db url:<artifact-url> db_op:get
collection:"bench" doc_id:"<part>"` and write the returned `params` to that
same file.) Send the STL with the file-delivery tool and report volume, bbox,
and which constraint had the least margin; that is where the next change will
break something.

If you add a dimension to the model, add the slider in the same change or the
bench can never set it.

## Version control

The user talks in plain words; you run `cad.py` (add `--project DIR` when not
in the working folder). Never run git yourself for CAD history.

| The user says | Run |
|---|---|
| "checkpoint", "save this" | `cad.py checkpoint [name]` |
| "try <idea>", "experiment with" | `cad.py try <idea>` |
| "revert", "that didn't work" | `cad.py revert <one-line reason>` |
| "keep it" | `cad.py keep` |
| "back" / "undo", "forward" / "redo" | `cad.py back` / `cad.py forward` |
| "auto checkpoints on/off" | `cad.py auto on` / `cad.py auto off` |
| "what have we tried", "history" | `cad.py history [part]` |

- **Manual by default**: checkpoint when the user asks. With auto on
  (`init`'s line says which), a checkpoint happens at every model change:
  each bench hand-off (the server does it) and each model edit -- after every
  edit you make to a file in `cad/parts/`, run `cad.py checkpoint <what
  changed>` yourself.
- **A snapshot covers `cad/` together** (model, values, recipe), so a revert
  can never desync them. Exports are not stored; rebuild them.
- **Each command prints one line; relay it, don't expand on it.** E.g.
  `checkpoint wider · 1 file · 39471b3 · volume +2.0 cm³, bbox 40×40×10 →
  50×40×10 · sense: 1 flag`. The volume/bbox delta appears when exactly one
  part changed; a `sense` note means `cad.py sense <part>` has flags to look at.
- **A refusal is one line on stderr, exit code 1** (detached HEAD, a merge in
  progress, nothing to keep, unsaved changes before `back`). Tell the user
  what it says; never work around it with git.
- **Checkpoints run the user's git hooks** (no `--no-verify`); a hook
  failure is reported in one line, with nothing left staged.
- `revert` keeps the abandoned attempt on the graph with its reason (the
  History tab shows it). `back` / `forward` restore `cad/` without moving
  `HEAD`; the next checkpoint records where you are. Nothing touches files
  outside `cad/` or switches the branch.
- `cad.py history` prints one summary line; `--json` prints the full list,
  only when you genuinely need it.

## Assemblies

Several parts joined into a machine (a robot chassis, a mechanism). Lookup:
`references/assembly.md`; worked example: `models/balance_bot.py`.

1. **Purpose first.** Before resizing a part or first using it in an
   assembly, write down in plain words what it is for and the rules that
   follow ("wheel hub: bore = motor shaft Ø + 0.1, press fit; hub length ≥
   1.5 × shaft Ø"). Get the user's OK, then ask **project only or
   worldwide**. Save as a `.rules` file in `cad/rules/` (project) or
   `<skill>/library/rules/` (worldwide; git-ignored, never committed unless
   the user explicitly contributes it). Only files whose `confirmed:` is a
   date (`2026-10-18`) or `true` are used. For a new part,
   `python scripts/rules.py list <assembly.py>` shows the saved kinds;
   propose matching rules and wait for a yes before applying them.
2. **Connectors on each part**, computed from its parameters, next to
   `build()`: `A.frame` (pins everything), `A.axis` (roll free: shafts,
   hubs), `A.point`, or anchored to a feature with `A.on_face` /
   `A.on_edge` / `A.on_circle`. A connector's z points out of its part.
3. **Assembly file** in the project's `cad/assemblies/<name>.py`, parts in
   `cad/parts/`, rules in `cad/rules/`. (`models/` in the skill holds only
   the shipped worked example; never put the user's parts, assemblies or
   rules there: the skill is a clone of a public repo.) Start it with the
   same path line generated parts use, so it also runs on its own:
   `sys.path.insert(0, os.environ.get("CAD_BENCH_SCRIPTS") or r"<skill>/scripts")`,
   then `import assembly as A`. `add` parts, `join("a.conn", "b.conn",
   type)` with `fixed`, `revolute`, `slider`, `cylindrical` or `wheel`, an
   optional `motor=A.Motor(...)`, and `use_rules(kind, role=instance)`.
   Never type world coordinates.
4. **Run it**: `python scripts/cad.py assemble <name> --project DIR` (puts
   the skill's scripts on the path). One line on a clean run, one
   `warn:` line per problem; an error is one `assembly: ...` line, exit 1. Warnings never block (under-defined parts with
   the free motions named, overlaps, hard-coded connectors, broken rules).
   Exports go to `cad/exports/<name>/`: `report.txt`, `<name>.png`,
   `<name>.step`, and a MuJoCo `<name>.xml` that has already loaded and
   stepped in `mujoco`.
5. **Look at the PNG after changing any join**: the connector triads (x red,
   y green, z blue) show a flipped or turned part at once. Read
   `report.txt` for numbers rather than adding prints.

`import assembly as A` alongside `import brep as B`; needs `pip install mujoco`
in the venv.

## Token economy

Keep the gates that are cheap and catch real bugs; cut verification that
only *feels* thorough.

**Keep:**
- `wall_check()` / `export_verified()` in the model — one line on success by
  design (see §4), so running it often costs almost nothing.
- `check_bench.py` before every publish of the shared artifact — one Bash call, sweeps defaults and
  every slider extreme, and is the only thing that catches model/recipe
  logic drift (see above) or a newly-broken default.
- Running the same numbers through both the model and a standalone
  re-derivation once, for a change that touches logic shared between the
  two — see below.

**Cut:**
- Don't drive the bench artifact's own sliders in a separate Browser-pane
  session to "verify" a JS-only logic edit. A published artifact viewed in
  a fresh tab is not guaranteed to be the same live session the user is
  looking at — clicking sliders there can burn several tool calls (numbox
  commit-on-blur timing, cross-origin iframes defeating `find`/`read_page`)
  while verifying nothing the user will actually see. If you need to prove
  a JS `derive()`/`checks()` edit is correct, extract the function and run
  it under `node` against the real params instead — deterministic, one
  call, no UI flakiness.
- Don't `read_db` speculatively "just to check" for a handoff. Read it once
  when the user actually signals one ("handed over", "hand to db", a
  "Hand these to Claude" click reflected back in conversation, or a live
  watch notification) and act on what comes back — don't re-poll.
- Don't re-export with a tighter tolerance or add extra prints to "see the
  numbers" on a passing run (see §4) — that habit compounds across a
  session for no benefit.
- **Never print git output.** Don't run `git log` / `status` / `diff` / `show`
  to look at CAD history; `cad.py` prints one line per step and
  `cad.py history` one summary line. Every git screen you print lands in
  context for nothing the user asked to see.
- **Never poll the bench server.** Start `cad.py serve` once in the
  background, read its one line, open the URL in the browser pane, and stop.
  No `curl` to see if it's up, no sleep-and-retry loops, no re-reading its
  log. The page itself shows build errors; the user's hand-off lands in
  `cad/parts/<part>.params.json`, which you read once when they say so.
