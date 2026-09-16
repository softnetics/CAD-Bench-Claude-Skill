# How to use cad-bench

This is the end-user side of the workflow `SKILL.md` describes to Claude.
You don't run any of the commands below yourself — Claude does — this page
just shows what to expect at each step. Every screenshot below is a real
capture of the skill's own worked example (`models/boss_plate.py`) running
in a browser, not a mockup.

**Jump to:** [ask for a part](#1-ask-for-a-part) ·
[the model](#2-claude-writes-a-parametric-model-not-a-one-off-shape) ·
[the bench page](#3-claude-publishes-a-cad-bench-page--this-is-what-you-see) ·
[the checks](#4-a-row-of-checks-not-a-generic-linter) ·
[handing values back](#5-hand-the-values-back-to-claude) ·
[locked sliders](#6-some-sliders-are-locked-on-purpose) ·
[several parts in one file](#7-if-the-stl-is-actually-several-parts-in-one-file) ·
[mating to a real part](#8-when-the-new-part-has-to-mate-flush-against-something-real) ·
[live 3D preview](#9-a-live-3d-preview-for-the-rare-part-that-needs-one) ·
[what it won't do](#what-it-wont-do)

## 1. Ask for a part

You don't need to name the skill or mention CAD tools. Any of these trigger it:

> "make me a mounting plate, four corner bosses for M4 heat-set inserts,
> bore each one, keep the wall around each insert at least 2 mm"

> "I need a bracket for a Pi Zero, rounded corners, wall thickness that
> survives a drop"

> "tweak the enclosure — thinner wall, still passes the checks"

There's a second starting point too: **"here's an STL someone printed, no
source file — make it a parametric part I can tune."** Claude reads the
mesh's own geometry (never by eyeballing a screenshot of it) with
`scripts/inspect_stl.py`, cross-checks anything that mates to a real
component (a motor shaft, a bearing) against that component's own spec, and
builds a proper model from what it finds — see §6 below for what that looks
like on the resulting bench page.

That path has an honest limit: `inspect_stl.py` screens the mesh first, and
a **sculpted or organic shape** (a character model, anything with
continuously varying freeform curvature, no flat faces or constant-radius
fillets to find) fails it. Claude says so and stops, rather than quietly
handing back numbers measured off a mesh that was never built from
primitives in the first place — this skill models mechanical parts, not
sculptures. If the STL turns out to be **several parts glued into one
file**, that's a different, solvable case — see §7.

## 2. Claude writes a parametric model, not a one-off shape

Every part is a small Python file against a real B-rep kernel
(`build123d`/OCCT — the same kernel lineage as FreeCAD), not a mesh
approximation. For the corner-boss plate above, that's `models/boss_plate.py`:
a rectangular plate, a cylindrical boss at each corner, each bored, corners
rounded. Running it directly (which Claude does, not you) prints one line on
success:

```
$ python models/boss_plate.py
[boss-plate] OK  watertight  vol=9400.1 mm^3, 0.010% vs exact (kernel)  bbox 60.0x40.0x12.0
  0.23 MB, 4572 tri -> boss_plate.stl
```

That line is a gate, not a progress message. It means: watertight, correctly
wound, the mesh is within 0.010% of the kernel's own exact volume (the gate
is 0.5%), and the bounding box is the size the parameters say it should be.
If any of that were false, **the file would not exist** — a failed check
deletes the STL rather than leaving a wrong part on disk.

## 3. Claude publishes a CAD Bench page — this is what you see

A live page with a slider for every dimension, a preview sketch that
redraws as you move them:

![Sliders on the left, a live top-view and section sketch on the right](docs/screenshots/01-sliders-drawing.png)

Type a value directly in the box next to a slider instead of dragging, and
it clamps to that slider's own range and snaps to its step — 17.3 mm on a
0.5 mm-step slider lands on 17.5, not 17.3, matching exactly what the slider
itself would have landed on.

## 4. A row of checks, not a generic linter

Below the sketch, the numbers that actually matter for this part — and a
pass/fail row for every physical constraint, in plain language:

![Six constraint rows, all green: boss wall thickness, standoff height, edge clearance, bore depth](docs/screenshots/02-checks-green.png)

Each row is a real constraint, not "is this number positive" — *"does this
wall survive a heat-set insert being melted into it,"* not a generic range
check. Push a value past what the part can actually take and a row turns
red, with the exact number that failed:

![One red row -- boss wall thinned to 0.50mm against a 2mm minimum -- five still green](docs/screenshots/04-checks-red.png)

(This one is real too: the boss diameter was set to 5 mm against a 4 mm
bore, so the wall left around the insert is only 0.5 mm — the check catches
it and says by how much, not just pass/fail.)

## 5. Hand the values back to Claude

Once every check is green, the bottom of the page has the constants your
sliders landed on, ready to hand off:

![A textarea to paste constants back in, and a generated const block for the model's parameters](docs/screenshots/03-handoff.png)

Inside the Claude Code app this panel also shows a **"Hand these to
Claude"** button (it needs a small capability the app grants; a plain
browser falls back to **Copy parameters**, shown above). Either way, Claude
reads the values back, writes them to `models/boss_plate.params.json`, and
re-runs the model — same gate, same one-line-on-success report, now with
your numbers instead of the defaults. You get the new STL and a note on
which check had the least margin, since that's where the next change is
most likely to break something.

## 6. Some sliders are locked, on purpose

Not every dimension is a free choice. If a value has to match something
real outside the model — a motor's shaft diameter, a bearing bore, a
fastener standard — dragging it around while tuning everything else is how
a part quietly stops fitting the thing it mates to. Those sliders render
**locked**: dimmed, disabled, a 🔒 next to the label, showing exactly the
number the requirement demands.

![Bore diameter slider dimmed and disabled, a lock icon next to its label, still showing 4 mm](docs/screenshots/05-locked-slider.png)

(This one's real too: `bore_d` on the boss plate above is fixed to the M4
insert the boss is sized for. Every *other* slider on the page stays free —
locking is for requirements, not for "the default I happened to pick.")

Hover the lock icon for why it's fixed. If the real part on your bench
turns out to measure differently than the spec says, click the 🔒 — it
flips to 🔓 and the slider unlocks for that session, same as any other.

This is also what a part reverse-engineered from an existing STL (§1) tends
to produce: `python scripts/inspect_stl.py part.stl` finds the geometry,
but a dimension that mates to a real component gets locked to that
component's own spec rather than to whatever the loose STL happened to
measure — full method in `references/stl-reverse-engineering.md`.

## 7. If the STL is actually several parts in one file

Sometimes "here's an STL" means a whole small assembly exported as one
mesh — a body, a bracket, several pieces that only look like one part.
Claude splits it by actual connectivity, not by guessing:

```
$ python scripts/segment_stl.py assembly.stl
  4 disjoint components (by connectivity, not by name):
  #0  volume=10445.09mm^3  bbox=[20. 20. 40.]  LARGEST
  #1  volume=  419.29mm^3  bbox=[ 6.  6. 15.]  GROUND-CONTACT, PERIPHERAL, MIRROR-PAIR with #2
  #2  volume=  419.29mm^3  bbox=[ 6.  6. 15.]  GROUND-CONTACT, PERIPHERAL, MIRROR-PAIR with #1
  #3  volume=   90.00mm^3  bbox=[10.  1.5   6.]  THIN-SHELL
```

Notice what it does **not** say: it never claims "#1 is a leg" or "#3 is a
bracket." It reports what's actually measurable — which piece is biggest,
which two are a genuine mirror pair (checked geometrically, by reflecting
one against the other, not just "similar size"), which piece touches the
ground, which is a thin shell rather than a solid lump. A part's print
orientation (which side happened to face the print bed) has nothing to do
with which way is "up" for the object itself, so guessing a real name from
position alone is a coin flip — naming each piece, and deciding which (if
any) to drop, is left to you. `--export-parts` writes each one to its own
STL so you can open and eyeball them before anything gets deleted.

## 8. When the new part has to mate flush against something real

If the piece being designed has to sit flush against one of those
segmented parts — a replacement piece that clips onto a body, a bracket
that seats against a housing — the surface where they touch isn't a free
design choice. Claude fits it directly: classifies which faces of the
existing part actually face the neighbour, then tightens that
classification until a primitive (usually a sphere or a cylinder) fits
cleanly. That fitted curvature becomes a **fixed fact** in the new model,
not a slider — you can resize the new part all you want, but the surface
that has to touch the real thing stays locked to what the real thing
actually measures. (Whether that fact becomes a hard boolean constraint or
a softer validation check depends on whether the neighbouring part is
hollow or solid inside — a detail Claude works out and states, not
something you need to track yourself.)

## 9. A live 3D preview, for the rare part that needs one

Most bench pages show a flat 2D sketch — a top view, a section — redrawn
live as sliders move. That's the default because it's cheap and exact for
anything prismatic. A small minority of parts (something with a real,
doubly-curved surface — a dome, a lofted shell) can instead get a rendered
3D preview that rotates and updates live, built the same way a video game
renders a shape rather than by computing a 2D outline formula by hand.
Claude decides which a part gets using a short checklist, not by default —
most parts, including almost everything mechanical, stay on the plain
sketch. If a part does get the 3D version, it's checked against the real
exported model automatically before publishing, the same way every other
check on this page is: silently and continuously, not something you have
to ask for.

## What it won't do

Assemblies with mates, thread modelling, sheet-metal unfolding, FEA,
sculpted/organic shapes (see §1 — no feature tree to recover from a
character model or anything with continuously varying freeform curvature),
or output formats other than STL/STEP. If a request needs one of those, the
skill says so rather than quietly handing back something that looks right
and isn't.

## For anyone extending the skill itself

If you're editing `SKILL.md`, the models, or the bench template rather than
just using them: `references/verification.md` has the sliver-checking
method and the fudge-factor-tuning discipline this skill's own development
needed the hard way — worth reading before touching a boolean-heavy model.
`references/live-mesh-preview.md` has the checklist for when a part earns a
live 3D preview (rare) versus the plain 2D sketch (the default, correct
choice for almost everything) — and `scripts/check_mesh_parity.py`'s own
test fixture (`models/_parity_demo.*`) is a small, complete worked example
if you're adding one.
