# brep.py lookup

Exact geometry via `build123d` / OCCT. This is the only backend.

**Use this file as a lookup, not a read-through.** SKILL.md already carries
the rules that prevent most failures. Come here for a specific operation, a
selector you cannot name, or a failure you cannot explain. Jump to the
section you need.

```python
import brep as B          # NOT `import build123d` -- see "The import" below
part = B.Box(40, 30, 10)
part = B.safe_fillet(part, B.vertical_edges(part), 4)
B.export_verified(part, "part.stl", "part")
```

## Contents

1. The import, and why it is wrapped
2. Selectors — the part that actually goes wrong
3. Operations and their failure modes
4. Order of operations
5. Tessellation and verification
6. Builder mode vs algebra mode
7. Fitting a curved face against a cylinder — inside vs outside
8. A rotation or mirror's sign is not obvious by inspection — check it
9. A sphere's own pole/seam can land exactly on your cut plane

---

## 1. The import, and why it is wrapped

`build123d` registers every system font at import time so `Text()` works. On
Windows it walks `C:/Windows/Fonts` with fontTools and does **not** catch
parse errors, so one malformed file anywhere in that folder aborts
`import build123d` entirely. Windows 11 ships `mstmc.ttf` — a touch-keyboard
stub, not a real font — which triggers exactly this. The symptom is a
`TTLibError: Not a TrueType or OpenType font (bad sfntVersion)` traceback
from inside `import`, and it looks like a broken install rather than a bad
font.

`brep.py` filters unreadable font files out of the folder scan for the
duration of the import, then restores `glob.glob`. Every readable font still
registers. It also raises the logging threshold during that window, because
fontTools reports malformed tables at `log.error` (not warning) for several
stock fonts, and that noise would otherwise bury the verification output.

So: **`import brep`, never `import build123d` directly.** First import costs
~6 s (OCCT plus the font scan); operations after that are milliseconds.

## 2. Selectors — the part that actually goes wrong

Picking the wrong edges is the dominant failure mode of scripted B-rep, and
the bad outcomes are asymmetric: a wrong selection either throws an opaque
OCCT error, or silently rounds an edge you did not mean and you find out when
the part comes off the printer.

### Built-in selection

```python
part.edges()                                  # every edge
part.faces()                                  # every face
part.vertices()

.filter_by(Axis.Z)                            # edges PARALLEL to Z
.filter_by(GeomType.CIRCLE)                   # arcs and circles
.filter_by(lambda e: e.length > 10)           # arbitrary predicate

.group_by(Axis.Z)                             # buckets by Z position
.group_by(Axis.Z)[-1]                         # the highest bucket
.group_by(Axis.Z)[0]                          # the lowest

.sort_by(Axis.Z)[-1]                          # single extreme item
.sort_by(SortBy.AREA)[-1]                      # biggest face
.sort_by(SortBy.LENGTH)
```

`filter_by(Axis.Z)` means *parallel to Z* — the vertical edges of an upright
box, the ones you round. `group_by(Axis.Z)[-1]` means *at the top* — the rim.
Confusing the two is a common and silent error.

### Helpers in `brep.py`

| helper | returns |
|---|---|
| `vertical_edges(part)` | edges parallel to Z |
| `top_edges(part)` / `bottom_edges(part)` | highest / lowest Z group |
| `top_face(part)` / `bottom_face(part)` | single extreme face — the usual `openings=` argument |
| `circular_edges(part, radius=None)` | circles, optionally of one radius (bore rims) |
| `edge_loops(edges)` | partition into connected loops, largest footprint first |
| `outer_of(edges)` / `inner_of(edges)` | the outer loop / everything else |

### The two-loop trap

After shelling, a rim carries **two** loops at the same height — outer and
inner — and `top_edges()` hands you both. Chamfering both eats the wall from
each side at once: on a 2.4 mm wall a 0.8 mm chamfer leaves 0.8 mm of land.
Use `outer_of(top_edges(part))`.

Do **not** separate them by distance from the Z axis. On a rounded rectangle
the outer loop's own radial range — centre of a long side out to the centre
of a corner arc — overlaps the inner loop's, so any radial threshold mixes
them. (This was a real bug in an earlier version of `outer_of`: it returned
12 of 16 edges and the rim chamfer quietly removed twice the intended
material.) `edge_loops()` groups by shared vertices instead, which is
topological and correct for any profile.

### Proving a selection is right

Selection bugs do not raise. Check them by differential volume — build twice
and confirm the delta matches what the feature should remove:

```python
v0 = build(dict(P, rim_cham=0.0)).volume
v1 = build(P).volume
# a chamfer of side c along a loop of length L removes about L * c^2 / 2
expected = outer_perimeter * P["rim_cham"] ** 2 / 2
assert abs((v0 - v1) - expected) / expected < 0.05
```

Also assert `solid_count(part) == 1` whenever the part should be one piece —
more than one usually means a boss is floating clear of the floor, or a
boolean did not merge.

## 3. Operations and their failure modes

### fillet

```python
part = B.safe_fillet(part, B.vertical_edges(part), radius=4)
```

Fails when the radius exceeds the thinnest adjacent wall, when neighbouring
fillets would overlap, or when it would consume a whole face. OCCT's own
error says none of this; `safe_fillet` catches it, runs `max_fillet()` by
bisection, and tells you the largest radius that works here.

```python
r = B.max_fillet(part, B.vertical_edges(part)) * 0.8   # stay off the limit
```

**Fillet the solid before shelling.** Rounding after shelling asks the fillet
to negotiate a thin wall instead of a solid corner, which is slower and often
fails.

### chamfer

```python
part = B.safe_chamfer(part, B.bottom_edges(part), length=0.6)
```

A 0.4–0.8 mm chamfer on the bottom outer edge is elephant-foot relief and is
almost always worth adding. The bottom of a shelled part has only one loop
(the floor is solid), so `bottom_edges()` is unambiguous there — unlike the
top.

### shell (`offset`)

```python
part = B.offset(part, amount=-2.4, openings=B.top_face(part))
```

Negative `amount` is inward. `openings` takes the face(s) to leave open —
omit it and you get a sealed hollow with no way in. Fails when the wall
exceeds the smallest internal radius: an inner corner radius is the outer
radius minus the wall, so `corner_r` must exceed `wall`, and the model should
assert that (`wall_check("inner corner radius", corner_r - wall, 0.5)`).

**Never shell a loft** — see below.

### loft

```python
with B.BuildPart() as bp:
    with B.BuildSketch(B.Plane.XY):
        B.RectangleRounded(70, 45, 6)
    with B.BuildSketch(B.Plane.XY.offset(65)):
        B.Circle(25)
    B.loft()
part = bp.part
```

Loft has **no algebra-mode form**. It consumes the sketches pending on a
`BuildPart`, in the order added, so it must run inside the builder context.

To give a loft a wall, **loft the outer profiles, loft the inner profiles,
and subtract** — do not `offset()` it. Offsetting a doubly-curved lofted
surface is slow and frequently fails outright, and subtracting gives you
exact control of the wall at both ends:

```python
body = outer_loft - inner_loft      # inner profiles inset by the wall,
                                    # extended past both ends so it cuts clean
```

Extend the inner loft a millimetre beyond each end of the outer one **when
the inner surface has to punch through a separate face it doesn't share a
plane with** — duct.py's flange is the case this rule is for: the inner
loft's own ends don't lie in the flange's flat face, so without the
extension the coincident geometry there leaves zero-thickness slivers.

**When inner and outer loft the exact same end cross-sections instead (no
separate abutting face), do NOT extend — let them share the same end
planes.** There, `loft()`'s own end caps already do the work: outer's
full-size cap minus inner's shrunk, coplanar cap at the identical z leaves a
flat annular rim — precisely the open edge a shell needs, with no
protruding pad. Adding a z-pad here doesn't just do nothing, it can
introduce the exact instability described in the next paragraph, since it
means feeding `loft()` more sections spaced unevenly near the ends.

**A smooth (non-ruled) loft through many closely-spaced sections whose
centre drifts non-monotonically can overshoot between samples and
self-intersect — pass `ruled=True`.** Confirmed on a real 18-section loft
(profiles' centre wobbled by ~2mm along the loft, a genuine feature of the
source mesh, not noise): the default smooth spline loft tessellated to
39,000–48,000 triangles (every other model in this project's own bench
lands at 500–2,500) and reproducibly failed `export_verified`'s
"not watertight" check from self-intersections in the subsequent boolean,
even though the outer and inner lofts each individually tessellated fine on
their own. Switching to `B.loft(ruled=True)` (linear interpolation between
consecutive sections rather than a fitted spline) dropped the triangle count
to ~3,600 and fixed it outright — with 18 real samples already close
together, a ruled loft looks just as smooth and has no spline to overshoot.
Prefer `ruled=True` by default whenever the section count is high (a dozen
or more, e.g. reconstructing a profile straight from measured mesh data)
rather than waiting for a mysterious watertightness failure to suggest it.

Profiles must have compatible orientation; a rectangle lofted to a circle is
fine, but reversing one profile's winding produces a twisted, self-
intersecting solid that still "builds".

### revolve / sweep

```python
with B.BuildPart() as bp:
    with B.BuildSketch(B.Plane.XZ):
        ...                          # profile must not cross the axis
    B.revolve(axis=B.Axis.Z)
```

A profile touching the axis is fine; one crossing it is not.

## 4. Order of operations

This order avoids most failures:

1. Build the solid outer form (primitives, booleans).
2. **Fillet** the outer edges while it is still solid.
3. **Shell** it (`offset` with `openings`).
4. **Chamfer** rims and the base — use `outer_of()` on the top.
5. Add internal features — bosses, ribs — after shelling, or they get
   hollowed too.
6. Subtract bores and ports last, so they cut through everything cleanly.

## 5. Tessellation and verification

`export_verified()` does the whole gate:

```python
B.export_verified(part, "part.stl", "part",
                  tolerance=0.01, angular_tolerance=0.1,
                  expect_bbox=((x0, y0, z0), (x1, y1, z1)))
```

The kernel knows the **exact** volume, so the check is "did tessellation lose
anything it should not have" — no hand computation needed, unlike the mesh
backend. Measured on the shipped examples: 0.007% loss on the enclosure,
0.036% on the duct. The default gate is 0.5%; if a part exceeds that, the
tessellation is too coarse for its curvature — lower `tolerance`, don't raise
the gate.

| `tolerance` | use |
|---|---|
| 0.05 | draft, fast preview |
| 0.01 | default; good for FDM |
| 0.002 | resin, or small parts with tight curvature |

`angular_tolerance` (radians) controls facets around tight curves; 0.1 is
fine, drop to 0.05 for small-radius fillets that must look smooth.

A failed verification **deletes the STL** rather than leaving a wrong part on
disk.

Use `wall_check()` for dimensions the bounding box cannot see — wall
thickness, bore land, clearance to a rim. Those are the values that make a
part unprintable and they are invisible in bbox and volume alike.

## 6. Builder mode vs algebra mode

build123d offers two styles. `brep.py` re-exports both.

**Algebra** — expressions, `+` and `-`. Preferred here: it composes, is easy
to factor into functions, and reads like the feature tree.

```python
body = B.Box(40, 30, 10) + B.Pos(0, 0, 10) * B.Cylinder(5, 8)
body -= B.Pos(10, 0, 0) * B.Cylinder(2, 30)
```

**Builder** — `with BuildPart()` contexts, required for `loft`, `revolve`,
`sweep` and anything sketch-driven. Take `bp.part` out at the end and go back
to algebra.

Mixing is fine and normal: build lofted pieces in builder blocks, combine
them with `+` and `-`.

## 7. Fitting a curved face against a cylinder — inside vs outside

A part that mounts against a cylindrical wall (a boss glued to a pole, a
plug fitting inside a tube, a wedge glued to the inside of a skirt) needs
one of two DIFFERENT booleans depending on which side of the wall it sits
on, and it is easy to pick the wrong one because both "just work" (produce
a valid, watertight, plausible-looking solid) — the mistake is only visible
as a real-world fit problem, not a modelling error.

**Material OUTSIDE a cylinder of radius `R`** (a boss clamped onto the
*outside* of a pole) — subtract a hollow cylinder from a box that starts at
the axis:

```python
blank = B.Box(span, w, h, align=(B.Align.MIN, B.Align.CENTER, B.Align.CENTER))
blank -= B.Cylinder(R, tall)          # removes X < R, leaves X > R
```

The resulting back face is **concave** (it cups around the pole, like a
saddle) — correct for a part that hugs a convex surface from outside.

**Material INSIDE a cylinder of radius `R`** (a plug or liner fitting
*inside* a tube) — the mirror-image intent, but NOT the mirror-image
construction: build a box that ends flush at `X = R` and reaches inward,
then **intersect** (not subtract) with a *filled* cylinder to trim the flat
end cap back to the true curve:

```python
blank = B.Box(span, w, h, align=(B.Align.MAX, B.Align.CENTER, B.Align.CENTER))
blank = B.Pos(R + eps, 0, 0) * blank    # ends at X=R+eps, extends inward
blank &= B.Cylinder(R, tall)            # trims the flat cap to the true curve
```

The resulting back face is **convex** (it bulges toward the wall, like the
outside of the same cylinder) — correct for a part that fits a concave
surface from inside.

**Do not try to get from one to the other by mirroring the finished solid
about a plane tangent to the cylinder (e.g. the plane `X = R`).** This looks
right (a reflection ought to flip inside/outside) and is wrong: reflecting a
*curved* boundary about a plane that only touches it at one point does not
reproduce the same curve on the other side — it produces a different curve
that pokes back past the wall away from the tangent point. Verified the hard
way: mirroring a correctly-built "outside" wedge about its own tangent plane
gave a solid whose edges stuck out past `R` instead of receding from it. If
you need a mirror image, mirror about a plane that keeps the SAME side of
the wall (e.g. `Plane.XZ` to flip left/right along a cylinder whose axis is
already `Z`) — never about a plane meant to flip which side of the curve the
material is on.

## 8. A rotation or mirror's sign is not obvious by inspection — check it

`rotate(Axis(...), angle)`, which face a `mirror(Plane(...))` keeps, which
half a `Box(align=MIN/MAX...)` occupies — these all have a definite,
deterministic answer, but the sign/direction is very easy to get backwards
by reasoning about it on paper, especially once a construction has been
adapted from a mirror-image or previous-revision version of itself (see §7
above for a real example: fixing "concave should be convex" took one wrong
attempt before the right one, and the right one still needed its rotation
sign re-derived from scratch rather than reasoned out).

**Before trusting a sign/orientation choice in the full model, check it
numerically against an independent expectation**, e.g.:

```python
# Does the top edge really come out to wedge_min_t, and the bottom to
# wedge_max_t, or did the taper direction get flipped?
for z, want in [(h/2 - 0.05, min_t), (-h/2 + 0.05, max_t)]:
    slice_ = (B.Pos(0, 0, -z) * part) & B.Box(1000, 1000, 0.02)
    bb = slice_.bounding_box()
    got = bb.max.X - bb.min.X
    assert abs(got - want) < 0.05, f"z={z}: got {got}, want {want}"
```

or simpler, just print `part.bounding_box()` / a thin slice's thickness and
compare by hand before it goes into `build()` for real. This costs a few
seconds per check and catches a class of bug that otherwise only shows up
after printing the part (or, worse, after being told by someone else that
the part is backwards).

## 9. A sphere's own pole/seam can land exactly on your cut plane

`Sphere(r) & Box(...)` (or any boolean that slices a sphere along a plane
through its centre) can tessellate as **"not watertight" regardless of
tessellation tolerance** — confirmed by sweeping `tolerance`/`angular_tolerance`
from 0.001 to 0.1 and finding the same handful of degenerate zero-length
edges every time, then confirming the bare `sphere & box` (before any
subtraction) already fails identically. This isolates the cause to the
sphere's own UV pole or seam, not the boolean combination or the mesh
deflection settings: an *unrotated* `Sphere()`'s pole sits at a specific,
predictable point (straight up its local Z from centre) and its
parametrization seam is a specific meridian line — and a symmetric clipping
box, or a footprint centred on the sphere's own axis, has an unpleasant habit
of cutting exactly through one or both.

**Fix: rotate the sphere off the world axes before positioning it, not
after.** A sphere is rotationally symmetric, so this changes nothing about
the real geometry — only where OCCT's internal pole/seam happen to sit —
but it reliably moves both off of wherever the boolean is cutting:

```python
def _sphere_at(radius, cx, cy, cz):
    tilted = B.Sphere(radius).rotate(B.Axis.X, 23).rotate(B.Axis.Y, 17)
    return B.Pos(cx, cy, cz) * tilted
```

The exact angles don't matter (23°/17° are arbitrary, chosen only to not be
a multiple of 90° or of each other) — what matters is that the rotation
happens on the un-positioned, un-clipped sphere, before it is moved to its
final centre or intersected with anything. Diagnosing this from the
export failure alone is slow; the fast path is checking `bare_sphere &
your_clip_shape` in isolation the moment a boolean involving a sphere (or
any full closed-surface revolve) reports "not watertight" with no other
symptom.
