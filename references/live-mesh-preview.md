# Live 3D preview: when it's worth it, and how to keep it honest

The bench's normal `draw(p,d)` is a flat 2D SVG sketch, computed live in
plain JS as sliders move. That's cheap and exact for prismatic parts, but
for a genuinely curved part (a lofted, doubly-curved shape) it means
re-deriving projection math by hand -- error-prone, confirmed the hard way
reconstructing a bean-shaped visor's silhouette: an initial approach traced
each cross-section's own upper/lower bound in depth order, which is wrong
whenever the width rises then falls (a given point on the true outline can
be reached by two different depths, and the real boundary is whichever
cross-section reaches furthest -- not whichever one the trace was visiting).

## The alternative: render an actual mesh, don't compute a silhouette formula

A GPU rasterizer already solves "what does this shape look like from this
direction" via z-buffering. So instead of deriving a 2D projection by hand:

1. Write the part's geometry construction a second time in JS -- not to
   solve projection math, but to produce a real triangulated mesh mirroring
   what `build()` does in Python.
2. Render it with **three.js** using an `OrthographicCamera` pointed along
   the axis you want ("Top", "Front", etc.).
3. The view IS what the camera sees -- exact, because the GPU rasterizes
   the real triangles, not an approximation of them.

For the boolean ops a `mesh()` needs (union/subtract, mirroring the
Python model's own `+`/`-`), use **`three-bvh-csg`** -- a lightweight
mesh-boolean library, not a full CAD kernel. Both are CDN-loadable
(cdnjs.cloudflare.com or cdn.jsdelivr.net/npm/, within the Artifact rules)
and small next to the ~500MB OCCT install this skill already requires.

## Decide with this checklist, in order -- stop at the first "no"

**1. Does the part's shape actually need curvature to read correctly?**
Boxes, ribs, bores, brackets, flat plates with holes -- a flat dimensioned
SVG sketch already shows everything that matters. If yes, stop here; keep
the existing SVG `draw()`. This is most parts. A 3D renderer for a
prismatic bracket is pure cost for no clarity gained.

**2. Is the geometry built ONLY from primitives + booleans + lofts through
explicit cross-sections?**
If `build()` uses `safe_fillet`, `safe_chamfer`, `offset` (shell),
`sweep`, or a tangency-blended `revolve` -- anything where OCCT's own
curvature math is doing real work -- a lightweight JS mesh library cannot
reproduce it faithfully. A live preview built that way would show a
plausible-looking but WRONG shape, silently diverging from the real STL.
That is worse than no live preview, because it looks authoritative. If no,
stop here; if a curved part in this category still needs an exact 2D view,
compute the projection in Python (where the true OCCT geometry lives, e.g.
via its own projection/HLR facilities) and ship the result as static SVG
path data -- not live, but not wrong either.

**3. Is the shape topologically stable across the FULL slider range?**
Sweep every slider from min to max and ask: does the part ever split into
multiple solids, collapse a feature to zero, or change which surfaces even
exist? A JS mirror tested only at defaults will confidently render
nonsense the first time a slider lands somewhere its own math never
accounted for. If the topology can change, either fix the sliders' own
range so it can't, or don't attempt a live mesh mirror for this part.

**4. Only if all three pass**, build the `mesh(p, THREE, CSG)` function
(see the contract below) and gate its publish on `check_mesh_parity.py`
passing -- not optionally, the same way `check_bench.py` is mandatory
before every bench publish.

## The `mesh(p, THREE, CSG)` contract

```js
export function mesh(p, THREE, CSG) {
  const box = new CSG.Brush(new THREE.BoxGeometry(p.box_x, p.box_y, p.box_z));
  box.updateMatrixWorld();
  const bore = new CSG.Brush(new THREE.CylinderGeometry(p.bore_d/2, p.bore_d/2, p.box_z+2, 32));
  bore.rotateX(Math.PI/2);
  bore.updateMatrixWorld();
  const evaluator = new CSG.Evaluator();
  return evaluator.evaluate(box, bore, CSG.SUBTRACTION).geometry;
}
```

**Take `THREE` and `CSG` as explicit function arguments — never `import`
them inside the function.** The exact same function then runs unchanged in
two different hosts: the published bench page (which loads three.js once
from a CDN and passes its own reference in) and `check_mesh_parity.py`'s
headless Node harness (which imports the installed npm packages and passes
those instead). A `mesh()` with its own `import` statement only runs in
whichever one of those two happens to match its import style.

`CSG` is `{Brush, Evaluator, SUBTRACTION, UNION, INTERSECTION}` from
`three-bvh-csg` — the bench page and the checker both inject the same
names, so a recipe never needs to know which host it's running in.

See `models/_parity_demo.py` / `models/_parity_demo.recipe.js` for a
complete, checker-verified pair (a box with a bore) — copy the shape of
that, not just the snippet above.

## Verifying it: `check_mesh_parity.py`

```bash
npm install                                     # once, installs three + three-bvh-csg
python scripts/check_mesh_parity.py models/part.py models/part.recipe.js \
    --python <path-to-cad-bench-venv>/python
```

Compares volume and bounding box between the JS mesh and the real Python/
OCCT STL export, at the recipe's own default values AND at every slider's
min/max — the same sweep `check_bench.py` already does for the 2D checks,
for the same reason: a mismatch that only shows up away from defaults is a
real, previously-seen bug class, not a hypothetical. Verified against a
deliberately-broken fixture (a JS bore radius scaled by 0.5×) during
development: caught it at 7 of 9 test cases with volume deltas from 2.75%
to 41%, correctly passed the matching pair with 0 mismatches.

Exits non-zero on any mismatch — wire it into the same "run before every
publish" habit `check_bench.py` already established, for any part that
ships a `mesh()`.
