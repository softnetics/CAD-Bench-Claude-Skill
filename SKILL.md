---
name: cad-bench
description: >-
  Model a mechanical part in Python with an exact CAD kernel, let the user
  tune its dimensions on an interactive slider page ("CAD Bench") that shows
  the binding constraints live, and export a verified, printable STL. Handles
  fillets, chamfers, shells, lofts, sweeps and revolves as real geometry, not
  approximations. Use whenever the user wants to design, model or 3D-print a
  part -- bracket, mount, standoff, enclosure, housing, skirt, tray, spacer,
  adapter, duct, jig, knob, clip, gasket, fixture -- or wants to adjust a
  part's dimensions against what actually binds (wall thickness, print
  overhang, clearance, material around a bore) and re-export. Trigger on
  "make me a bracket", "model a mount for X", "design an enclosure", "round
  the corners", "hollow it out", "parametric part", "tweak the dimensions and
  give me an STL", "export to STL", "CAD bench" -- even when no CAD tool is
  named.
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
hand. Short version: `python scripts/inspect_stl.py part.stl` lists every
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
python scripts/new_part.py --name spacer_plate \
    --params "plate_x=90,plate_y=50,plate_t=4,bore_d=30,hole_d=4.5,inset=8"
```

Writes `models/spacer_plate.py` (runnable immediately, builds a placeholder
box) and `models/spacer_plate.recipe.js` (a bench entry stub with matching
sliders). Run it as-is to confirm the harness works, then replace `derive()`,
`build()`, and the recipe's `checks()`/`draw()`. Parameter names are already
identical on both sides, which is the one coupling that must hold.

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

### 5. Bench page

One shared CAD Bench artifact, a multi-part picker. First use: publish
`assets/bench-template.html` (declares the `db` capability — read
`artifact-capabilities` first). Later parts: read the artifact, paste your
`.recipe.js` into `PARTS`, republish to the same URL.

**Before publishing, always:**

```
python scripts/check_bench.py <bench.html>
```

It runs every recipe headlessly at defaults and at every slider extreme, and
fails on two classes of bug this format has. One: reading `d.plate_x` when
`plate_x` is a slider gives `undefined`, `undefined >= 2` is an ordinary
`false`, and the row goes **red like a real constraint failure** — so you
tune sliders chasing a typo. Sliders are on `p`, computed values on `d`. Two:
a `draw()` whose views were scaled to fit their own content with no bound on
where the result lands, so a caption or a whole second view ends up drawn on
top of another shape — unreadable, but nothing throws. The checker parses
the SVG for text mostly covered by a filled shape, and solid shapes heavily
overlapping each other, at every slider extreme, not just defaults. Field
spec, the SVG helpers, and how to lay out more than one view without this
happening are in `references/bench-artifact.md`.

Then hand the user the link: adjust sliders, and when the checks are green
press **"Hand these to Claude"**.

**"Always" includes republishing an existing part, not just a first-time
recipe.** The bench recipe and the model are two independent
implementations of one design — nothing keeps a fix made in `build()`/
`derive()` from silently going stale in the recipe's `derive()`/`checks()`
except this lint. Concretely: fixing a constraint in the model (say, which
variables a feature is anchored to) and forgetting to mirror the same
change into the recipe leaves the bench describing a part that no longer
matches what the model builds — nothing errors, the old recipe just keeps
reporting green on the wrong geometry. Re-run `check_bench.py` on *every*
republish, including "just a small model fix," and re-check whether the
recipe's own default `val`s still pass any check you just added — a check
added in response to a newly-found bug can fail the shipped defaults, which
means the bug was live in the stock preset the whole time.

### 6. Read back, regenerate, deliver

```
Artifact  action:read_db  url:<artifact-url>  db_op:get
          collection:"bench"  doc_id:"<part>"
```

Write the returned `params` to `models/<part>.params.json` and re-run the
model — it picks the file up automatically. Send the STL with the
file-delivery tool and report volume, bbox, and which constraint had the
least margin; that is where the next change will break something.

Each hand-off overwrites `bench/<part>`. If you add a dimension to the model,
add the slider in the same change or the round-trip silently drops it.

## Token economy

Keep the gates that are cheap and catch real bugs; cut verification that
only *feels* thorough.

**Keep:**
- `wall_check()` / `export_verified()` in the model — one line on success by
  design (see §4), so running it often costs almost nothing.
- `check_bench.py` before every publish — one Bash call, sweeps defaults and
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
