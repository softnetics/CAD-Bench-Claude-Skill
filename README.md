# cad-bench

A [Claude Code](https://claude.com/claude-code) skill that turns a plain-English
part description into a verified, printable STL — modelled in Python against a
real CAD kernel, with an interactive slider page for tuning dimensions before
export.

```
you: "make me an enclosure for a Pi Zero 2 W, rounded corners, USB-C cutout"
        │
        ▼
Claude writes a parametric model (fillet → shell → chamfer → bosses → port)
        │
        ▼
publishes a CAD Bench page — sliders, live constraint checks, a preview sketch
        │
        ▼
you drag the sliders until the checks go green, click "Hand these to Claude"
        │
        ▼
Claude reads the values back and exports a gated, watertight STL
```

## Why

Most "AI CAD" demos stop at *"here's a box with a hole in it."* This skill is
built for the part after that one — the enclosure with rounded corners and a
shelled cavity, the round-to-rectangular duct, the bracket where a wall
thickness of 1.8 mm instead of 2.2 mm is the difference between a part that
prints and one that doesn't.

It does that by modelling against **[build123d](https://build123d.readthedocs.io/)**,
a real B-rep kernel (OCCT — the same lineage as FreeCAD and OpenCascade), not
a mesh approximation. Fillets are fillets. Shells are shells. Every export is
gated by a script that checks the mesh is watertight, correctly wound, and
within 0.5% of the kernel's own exact volume — and it **deletes the file**
rather than hand you a part that's wrong.

## Requirements

- Python 3.10+
- A venv with `build123d` installed (pulls the OCCT kernel — the one real
  cost, ~500 MB download):

  ```
  python -m venv cad-bench-venv
  cad-bench-venv/Scripts/python -m pip install build123d trimesh numpy   # Windows
  cad-bench-venv/bin/python -m pip install build123d trimesh numpy       # macOS/Linux
  ```
- Node.js on `PATH`, for `scripts/check_bench.py` (validates a bench page's
  recipes headlessly before you publish them).
- Only if a part uses a **live 3D preview** (rare — see below): run
  `npm install` once in this repo's root to pull `three`/`three-bvh-csg`
  for `scripts/check_mesh_parity.py`. Everything else needs nothing from
  `package.json`.

## How to use it

See **[HOWTO.md](./HOWTO.md)** for the end-user side of the workflow above —
what you actually see and do at each step, walked through with one of the
skill's own worked examples (`models/boss_plate.py`) and its real output.

## Reverse-engineering an existing STL

Sometimes the part already exists as a loose, source-less STL and the job
is to turn *that* into a parametric model, not design something new —
different failure mode, different method.

**First, is it even the right kind of shape?** `inspect_stl.py` screens
for this automatically, before anything else:

```
python scripts/inspect_stl.py part.stl
  shape screen : FEATURE-BASED   (this mesh decomposes into primitives —
                                   flat faces, fillets, circular/rectangular
                                   cross-sections. Reverse-engineering it
                                   is worth attempting.)
```

A **sculpted/organic mesh** — a character model, anything with continuously
varying freeform curvature — fails this screen and says so up front,
instead of quietly producing plausible-looking-but-meaningless numbers off
a mesh that was never built from primitives. If it passes:

```
python scripts/inspect_stl.py part.stl            # every distinct Z the mesh
                                                    # actually has vertices at —
                                                    # never guess sample heights
python scripts/inspect_stl.py part.stl --z 0.2     # detail one height, split
                                                    # into radius bands so two
                                                    # loops sharing one Z don't
                                                    # get read as one shape
```

**If the STL is several parts in one file** (a body, a bracket, a
multi-piece assembly exported as one mesh), split it first:

```
python scripts/segment_stl.py assembly.stl
  4 disjoint components (by connectivity, not by name):
  #0  volume=10445.09mm^3  LARGEST
  #1  volume=  419.29mm^3  GROUND-CONTACT, PERIPHERAL, MIRROR-PAIR with #2
  #2  volume=  419.29mm^3  GROUND-CONTACT, PERIPHERAL, MIRROR-PAIR with #1
  #3  volume=   90.00mm^3  THIN-SHELL
```

It reports **structural facts only** — volume rank, verified mirror pairs
(checked geometrically, not just "similar size"), which piece touches the
ground, which is a thin shell — and deliberately never guesses a real name
like "bracket" or "leg." A part's own print orientation has nothing to do
with which way is "up" or "front" for the object itself, so a
position-based name guess is a coin flip dressed up as an answer. Map the
tags to real names yourself before deleting anything — `--export-parts`
writes each component to its own STL for a quick look.

**If the new part has to mate flush against one of these pieces**, fit
that surface specifically, not the whole neighbouring part's shape:
classify its faces by whether their outward normal points toward the
neighbour's centroid, then tighten that classification until a primitive
fit (usually a sphere or cylinder) converges — full method, plus the
**solid-vs-shell decision** that determines whether the fixed curvature
becomes a boolean construction constraint or a validation check, in
`references/stl-reverse-engineering.md` §6.

Either way: gate the reconstruction against the **original mesh's own
volume**, not just the rebuild's internal tessellation consistency — and if
a feature mates to something real outside the file (a motor shaft, a
bearing, a fastener), check that part's own spec before trusting a literal
mesh reading; a precisely-measured modelling mistake is still a mistake.

Dimensions that come from that kind of external requirement, rather than
free design choice, can be marked `locked:true` on a bench slider — it
renders disabled and dimmed with a 🔒 and the source noted in a tooltip,
so nobody drags a datasheet dimension off-spec while tuning the sliders
next to it. See `references/bench-artifact.md`.

## Live 3D preview for curved parts

Most parts get a flat 2D sketch on the bench page (a top view, a section) —
cheap, exact for anything prismatic, and the default. A genuinely curved
part (a loft, a doubly-curved surface) can instead get a real 3D preview,
rendered live as sliders move with `three.js` — but only when it's actually
worth the cost. `references/live-mesh-preview.md` has the 3-question
checklist (most parts fail the first question and stay on the plain
sketch); if a part does get one, `scripts/check_mesh_parity.py` is a
mandatory gate — it verifies the live-rendered mesh actually matches the
real Python/OCCT model (volume + bounding box, at every slider extreme),
because a live preview that quietly stops matching the real geometry is
worse than no live preview at all.

## Install

**Option A — one file.** Download [`cad-bench.skill`](./cad-bench.skill) from
this repo and drop it into a Claude Code chat. Claude will offer a **Save
skill** button on the file card; click it and you're done.

**Option B — clone it.**

```bash
git clone https://github.com/<you>/cad-bench.git ~/.claude/skills/cad-bench
```

Either way, Claude picks it up automatically the next time a request looks
like CAD/STL/3D-printing work — brackets, mounts, enclosures, adapters,
standoffs, ducts, jigs. You don't need to name the skill for it to trigger.

## What's inside

```
cad-bench/
├── SKILL.md                    the workflow Claude follows
├── HOWTO.md                    the end-user walkthrough, with real screenshots
├── package.json                three.js/three-bvh-csg, dev-only tooling for
│                                check_mesh_parity.py -- npm install, never a
│                                runtime dependency of anything published
├── scripts/
│   ├── brep.py                 build123d wrapper: selectors, safe fillet/chamfer,
│   │                           the Windows-font-crash workaround, export + gate
│   ├── verify.py               the watertight/volume/bbox gate, shared by every export
│   ├── check_bench.py          headless validator for a CAD Bench slider page
│   ├── check_mesh_parity.py    verifies a live-preview mesh() matches the
│   │                           real Python/OCCT model -- volume + bbox, at
│   │                           every slider extreme
│   ├── new_part.py             scaffolds a new model + matching bench recipe
│   ├── inspect_stl.py          first look at an existing STL: shape screen
│   │                           (feature-based vs. organic/sculpted), every
│   │                           distinct Z, radius bands
│   └── segment_stl.py          splits a multi-body STL into disjoint parts,
│                                reports structural facts (never guesses names)
├── references/
│   ├── brep.md                 operation-by-operation lookup: fillet, chamfer,
│   │                           shell, loft, selectors, the failure modes of each
│   ├── bench-artifact.md       the slider-recipe format, locked sliders, the
│   │                           Claude hand-off wiring
│   ├── verification.md         why each gate exists, how to prove a selection is right
│   ├── stl-reverse-engineering.md  method for turning a loose STL into a model,
│   │                           including fitting a MATING surface (§6) and the
│   │                           solid-vs-shell construction decision
│   └── live-mesh-preview.md    when a live 3D preview is worth building, the
│                                mesh(p,THREE,CSG) contract, how to verify it
├── models/                     worked, runnable examples
│   ├── boss_plate.py             — plain prismatic: plate, bosses, bores
│   ├── enclosure.py              — fillet → shell → chamfer, internal bosses, a port
│   ├── duct.py                   — loft: round-to-rectangular transition
│   └── _parity_demo.py/.recipe.js  — check_mesh_parity.py's own test
│                                fixture (a box with a bore), not a real part
└── assets/
    └── bench-template.html     the CAD Bench page, ready to publish
```

## The one thing worth knowing before you use it

Fillets, chamfers, shells and lofts are **exact geometry**, not a faceted
guess — that's the entire point of building on a real kernel instead of mesh
CSG. What it *can't* do: assemblies with mates, thread modelling, sheet-metal
unfolding, FEA, sculpted/organic shapes (a character model, anything with
continuously varying freeform curvature — there's no feature tree to
recover), or file formats other than STL/STEP. If you need those, this
skill will tell you so rather than quietly hand you something wrong.

## License

MIT — see [LICENSE](./LICENSE).
