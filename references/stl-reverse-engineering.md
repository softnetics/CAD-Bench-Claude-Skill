# Reverse-engineering an existing STL

Sometimes the part already exists as a hand-exported or otherwise
source-less STL and the job is to turn it into a real parametric model —
not to design something new. This is a different failure mode than modelling
from a spec: the geometry is right there in the mesh, which makes it *easy*
to trust blindly and *hard* to notice when a reading is wrong, because
wrong readings still produce a solid that looks plausible.

This file is the method; `scripts/inspect_stl.py` is the tool that makes it
fast. Both came out of a real incident: a first pass reverse-engineered a
fluted shaft's cross-section by sampling Z at guessed heights (0, 1, 2, 5,
10, 17.5, 25...), missed the two heights (0.2 and 15) where a blind hole
actually lived, and read that hole's mouth-chamfer rim — which happened to
share Z=0 with the outer profile — as a deep valley in the flute shape
itself. The reconstruction built, passed its own gate, and was wrong.

## 1. Get the ground truth facts first, with `inspect_stl.py`

```
python scripts/inspect_stl.py part.stl
```

This prints the mesh's own **volume** (the number a reconstruction's kernel-
exact volume gets compared against — not the reconstruction's own
tessellated volume, which only proves internal consistency, not that it
matches the real part) and **every distinct Z the mesh has vertices at**,
each with a vertex count.

**Never hand-sample Z heights by guessing round numbers.** A guessed list
(0, 5, 10, 15, 20...) can straddle every feature boundary in the part and
report back a clean, boring, WRONG cross-section at every single sample —
exactly what happened in the incident above. The distinct-Z list is exact
and cheap; there is no reason to guess when the mesh will just tell you.

Any Z with a vertex count that doesn't fit an obvious pattern (not evenly
spaced from its neighbours, way more or fewer vertices than the "boring"
heights) is where a feature starts, ends, or transitions. Look there first.

## 2. Detail a Z, and separate loops before reading them

```
python scripts/inspect_stl.py part.stl --z 0.2
```

This lists every unique (x, y) at that height, radius from centroid, sorted
into **radius bands** — a gap in sorted radius of more than a few hundredths
of a mm almost always means two unrelated loops share this Z, not one
complicated shape.

**Do not eyeball a mixed angle-sorted dump of a multi-loop face.** In the
incident above, an outer-profile arc (radius climbing smoothly from 4.05 to
4.45 mm) and an unrelated inner hole's chamfer rim (a tight circle at radius
3.3 mm) both live at Z=0. Sorted only by angle, interleaved, that reads as
one confusing shape with a "valley" no simple formula reproduces. Split by
radius band first — each band is a separate feature with its own,
individually simple, story.

A band with near-zero spread (`hi - lo` under ~0.001 mm) is a smooth circle
— a bore, a chamfer rim, a shaft's round body. A band with real spread and
tens of points at irregular angles is a faceted or lobed profile — the kind
`brep.md`'s "arbitrary polygon profile" pattern (sample `r(theta)`, extrude)
reconstructs well.

## 3. The acceptance test is the ORIGINAL mesh's volume, not self-consistency

`export_verified()` checks a reconstruction's tessellated volume against
*its own* kernel-exact volume — that only proves the STL faithfully
represents whatever solid you built, says nothing about whether that solid
is the right one.

The real gate for a reverse-engineered part is comparing the reconstruction's
kernel-exact volume (`part.volume` before export) against the **original
STL's own volume**, from `inspect_stl.py` or `trimesh.load(original).volume`.
Treat anything past about 0.5% as "a feature is still unaccounted for," not
"close enough for a clean parametric approximation" — in the incident above
a first reconstruction was 14% off (1669 vs 1463 mm³) and got explained away
as approximation error instead of triggering a return to step 1. The second,
correct reconstruction (after finding the hole) landed at 0.01%.

A perfectly matched volume is necessary but not sufficient — two very
different shapes of the same volume both pass. Match the bounding box, the
radius bands at the Z's you already found, and the distinct-Z list's own
vertex counts too before calling it reconstructed.

## 4. A literal mesh reading can faithfully reproduce someone else's mistake

Once the geometry is correctly *measured*, one more question remains before
it's correctly *modelled*: does this feature mate to something real outside
the file — a motor shaft, a bearing, a standard fastener, a connector? If
so, the STL's own geometry is evidence of what was actually *built*, not
proof of what was *intended*. A perfectly precise measurement (radius
std-dev of a few microns, in one real case) of a plainly wrong feature — a
round bore over a part that needs a D-shaft to transmit any rotation at all
— is still wrong, just precisely so.

**Before finalizing a feature that mates to a real external part, check that
part's own spec.** A datasheet drawing, a manufacturer's dimension listing,
or a prior physical measurement already in project memory. Two independent
sources agreeing (a physical measurement AND a datasheet, say) is strong
confirmation; the STL's own geometry disagreeing with both is a strong
signal that the *source file*, not your reconstruction, has the bug. Model
the requirement, not the file, when they conflict — and say so explicitly in
the model's docstring and the bench recipe's note, with both readings and
which one won and why.

## 5. Put externally-sourced dimensions on the bench as LOCKED sliders

A dimension that comes from an external requirement (a datasheet, a
measured mating part) rather than the modeller's own design judgement
should default to **locked** on the bench (`locked: true` on the param,
plus a `lockNote` citing the source) — disabled, dimmed, showing the
requirement's own value, with a click-to-override lock icon next to it. See
`bench-artifact.md` for the field format.

This exists specifically so a value that MUST match something real outside
the model doesn't get silently dragged off-spec by someone tuning the
sliders next to it. Free-choice design parameters (a chamfer size, a lobe
count, a clearance margin) stay ordinary unlocked sliders — locking is for
requirements, not preferences.

## 6. Fitting a MATING surface, not the whole envelope

Everything above fits a single part's own overall shape. A different, more
useful question when the goal is to *replace* one part of a multi-part
assembly (a broken clip, a redesigned visor) while it still has to sit flush
against its neighbour: **what curvature does the neighbour's own surface
actually have, right where this part touches it?** That surface is not a
free design choice — whatever new part gets built has to conform to it
exactly, everywhere else is free to change.

**Classify faces by which one they face, not by position.** Position-based
heuristics (front/back, "the near end") are guesses and can be wrong even
when the two parts' rough geometry is well understood (verified the hard
way: an initial reading of which face mated to the neighbour, based on
depth-axis position alone, was later corrected by inspecting the actual
parts and turned out backwards). The reliable test is normal direction: for
each face on the part being replaced, take the face normal and the vector
from that face's centre to the *neighbouring part's own centroid*. A face
whose outward normal points roughly toward that centroid is a candidate
mating face — its outward side, by definition, faces into where the other
part's material is.

```python
to_neighbour = neighbour.centroid - part.triangles_center
to_neighbour /= np.linalg.norm(to_neighbour, axis=1, keepdims=True)
dot = np.einsum('ij,ij->i', part.face_normals, to_neighbour)
mask = dot > threshold          # candidate mating faces
```

**Tighten the threshold and watch the fit converge — don't pick one value
and stop.** A loose threshold pulls in transition/bezel faces that face
*roughly* the right way but aren't the true contact patch, which biases and
noisifies a primitive fit. Fit a sphere (or cylinder) to the candidate faces
at several thresholds from loose to strict; if the residual keeps shrinking
and the fitted radius/centre keep moving in one direction as the threshold
tightens, the loose set is contaminated and only the tight end is trustworthy. If
the residual instead stabilizes early and stays flat as the threshold
tightens further, that stability is itself the evidence the fit is real.
Concretely, on one real part: residual std fell monotonically from 0.99 mm
(threshold 0.5) to 0.03 mm (threshold 0.99) while the fitted radius drifted
from 19.5 mm to 23.8 mm over the same range — a sub-0.1 mm residual on a
~24 mm feature at the tight end means the surface **is** that primitive, not
merely close to it, and the loose-threshold numbers were simply wrong.

**Once fit, that curvature is FIXED geometry, not a bench slider.** Put the
fitted centre and radius as module-level constants in the model (see
`cad/visor_template.py` for a worked example: `BODY_SPHERE_CENTER` /
`BODY_SPHERE_RADIUS`), clearly commented as measured facts, and build the
replacement as boolean geometry sharing that exact centre — e.g. two
concentric spheres of that centre, one at the fixed radius (the surface that
must stay flush) and one offset outward by a free "thickness"/"protrusion"
parameter, clipped to a free footprint. Free dimensions then only change
*where* the footprint clips the fixed surface, never the surface's own
shape — which is what guarantees the part still mates correctly at any size
the user dials. On the bench page, these fixed constants are read-only
values baked into `derive()`, not `params` entries — there is nothing to put
a slider on.
