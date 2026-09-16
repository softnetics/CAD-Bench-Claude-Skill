#!/usr/bin/env python3
"""
check_mesh_parity.py -- verify a live-preview recipe's mesh(p, THREE, CSG)
function actually matches the real Python/OCCT model it's supposed to be
previewing.

WHY THIS EXISTS: a bench recipe's `derive()`/`checks()` are JS re-derivations
of a few numbers, and check_bench.py already catches those drifting from the
model's own PARAMS. A `mesh()` function is a full SECOND IMPLEMENTATION of
the model's geometry, in a different language, using a different (lighter,
approximate) geometry library -- see references/live-mesh-preview.md for
when this trade is worth making at all. Nothing else can tell you that
today's edit to build() didn't get mirrored into mesh(), and a live preview
that silently starts showing the WRONG shape is worse than no live preview,
because it looks authoritative. This script is the check for exactly that.

    python scripts/check_mesh_parity.py models/_parity_demo.py models/_parity_demo.recipe.js

Compares volume and bounding box between the two, at the recipe's own
default values AND at every slider's min/max (the same sweep check_bench.py
already does for the 2D checks) -- a mesh() that matches at defaults but
diverges at an extreme is a real, previously-seen bug class (see the visor
STL-segmentation session notes), not a hypothetical.

Requires `node` on PATH with `three` and `three-bvh-csg` installed
(package.json in this skill's root -- `npm install` once).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

VOL_TOL_PCT = 2.0     # mesh vs OCCT volume, relative -- looser than
                       # export_verified's 0.5% because a lightweight JS
                       # mesh (fixed segment counts, no adaptive
                       # tessellation) is expected to be coarser, not
                       # because correctness matters less.
BBOX_TOL_MM = 0.5      # absolute, per axis

MESH_HARNESS = r"""
import * as THREE from 'three';
import * as CSGLIB from 'three-bvh-csg';
const CSG = {{Brush: CSGLIB.Brush, Evaluator: CSGLIB.Evaluator,
             SUBTRACTION: CSGLIB.SUBTRACTION, UNION: CSGLIB.UNION,
             INTERSECTION: CSGLIB.INTERSECTION}};

{recipe_src}

function meshVolume(geometry) {{
  const pos = geometry.attributes.position;
  const idx = geometry.index;
  const triCount = idx ? idx.count / 3 : pos.count / 3;
  const get = i => idx ? idx.getX(i) : i;
  let vol = 0;
  for (let t = 0; t < triCount; t++) {{
    const a = get(t*3), b = get(t*3+1), c = get(t*3+2);
    const v0 = [pos.getX(a), pos.getY(a), pos.getZ(a)];
    const v1 = [pos.getX(b), pos.getY(b), pos.getZ(b)];
    const v2 = [pos.getX(c), pos.getY(c), pos.getZ(c)];
    vol += (v0[0]*(v1[1]*v2[2]-v2[1]*v1[2])
          - v0[1]*(v1[0]*v2[2]-v2[0]*v1[2])
          + v0[2]*(v1[0]*v2[1]-v2[0]*v1[1])) / 6;
  }}
  return Math.abs(vol);
}}

const p = {params_json};
const geometry = mesh(p, THREE, CSG);
geometry.computeBoundingBox();
const bb = geometry.boundingBox;
console.log(JSON.stringify({{
  volume: meshVolume(geometry),
  bbox: [[bb.min.x, bb.min.y, bb.min.z], [bb.max.x, bb.max.y, bb.max.z]],
}}));
"""


def _run_js_mesh(recipe_path, params, node_cwd):
    """Runs mesh(p, THREE, CSG) for one param set, returns {volume, bbox}."""
    with open(recipe_path, encoding="utf-8") as fh:
        recipe_src = fh.read()
    # Strip the `export` keywords -- the harness inlines the recipe source
    # directly rather than doing a real module import, so `mesh` and
    # `params` just need to exist as top-level bindings in the same file.
    recipe_src = re.sub(r"^export\s+", "", recipe_src, flags=re.MULTILINE)

    script = MESH_HARNESS.format(recipe_src=recipe_src, params_json=json.dumps(params))
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, dir=node_cwd) as fh:
        fh.write(script)
        tmp_path = fh.name
    try:
        proc = subprocess.run(["node", tmp_path], capture_output=True, text=True, cwd=node_cwd)
    finally:
        os.remove(tmp_path)
    if proc.returncode != 0:
        raise RuntimeError(f"node failed:\n{proc.stderr}")
    # three-bvh-csg prints a deprecation notice on stderr; stdout carries
    # only our JSON line as long as the recipe itself doesn't console.log.
    line = [l for l in proc.stdout.splitlines() if l.strip().startswith("{")]
    if not line:
        raise RuntimeError(f"no JSON on stdout:\n{proc.stdout}\n{proc.stderr}")
    return json.loads(line[-1])


def _run_python_model(model_path, python_exe, params):
    """Writes a params.json override, runs the model, loads the exported
    STL with trimesh, returns {volume, bbox}."""
    import trimesh

    here = os.path.dirname(os.path.abspath(model_path))
    stem = os.path.splitext(os.path.basename(model_path))[0]
    params_path = os.path.join(here, f"{stem}.params.json")
    stl_path = os.path.join(here, f"{stem}.stl")

    with open(params_path, "w", encoding="utf-8") as fh:
        json.dump(params, fh)
    try:
        proc = subprocess.run([python_exe, model_path], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"model failed:\n{proc.stdout}\n{proc.stderr}")
        mesh = trimesh.load(stl_path)
        return {"volume": float(mesh.volume),
                "bbox": [mesh.bounds[0].tolist(), mesh.bounds[1].tolist()]}
    finally:
        if os.path.exists(params_path):
            os.remove(params_path)


def _compare(name, py, js):
    problems = []
    vol_pct = 100 * abs(py["volume"] - js["volume"]) / py["volume"] if py["volume"] else 0
    if vol_pct > VOL_TOL_PCT:
        problems.append(f"volume differs {vol_pct:.2f}% "
                        f"(python {py['volume']:.2f} vs js {js['volume']:.2f}) mm^3, "
                        f"want <= {VOL_TOL_PCT}%")
    py_lo, py_hi = py["bbox"]
    js_lo, js_hi = js["bbox"]
    for axis, i in zip("XYZ", range(3)):
        for label, pv, jv in [("min", py_lo[i], js_lo[i]), ("max", py_hi[i], js_hi[i])]:
            d = abs(pv - jv)
            if d > BBOX_TOL_MM:
                problems.append(f"bbox {axis} {label} differs {d:.3f}mm "
                                f"(python {pv:.3f} vs js {jv:.3f}), want <= {BBOX_TOL_MM}mm")
    status = "OK  " if not problems else "FAIL"
    print(f"{status} {name}")
    for p in problems:
        print(f"       ! {p}")
    return not problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model", help="path to the Python model (e.g. models/part.py)")
    ap.add_argument("recipe", help="path to the JS recipe fixture "
                    "(exports `params` array and `mesh(p, THREE, CSG)`)")
    ap.add_argument("--python", default=sys.executable,
                    help="python executable with build123d installed "
                    "(default: the interpreter running this script)")
    args = ap.parse_args()

    with open(args.recipe, encoding="utf-8") as fh:
        recipe_src = fh.read()
    m = re.search(r"export\s+const\s+params\s*=\s*(\[[\s\S]*?\]);", recipe_src)
    if not m:
        sys.exit("could not find `export const params = [...]` in the recipe")
    # The params array is plain JSON-ish JS (no functions) -- evaluate it
    # via node rather than hand-rolling a parser for trailing commas etc.
    proc = subprocess.run(["node", "-e", f"console.log(JSON.stringify({m.group(1)}))"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"could not parse params array: {proc.stderr}")
    param_defs = json.loads(proc.stdout)

    node_cwd = os.path.dirname(os.path.abspath(args.recipe))
    # node_modules must be reachable from node_cwd (npm install run once in
    # the skill root) or resolvable via a parent directory's node_modules --
    # both hold for models/*.recipe.js under this skill's own root.

    base = {q["id"]: q["val"] for q in param_defs}
    cases = [("defaults", dict(base))]
    for q in param_defs:
        for bound in ("min", "max"):
            case = dict(base)
            case[q["id"]] = q[bound]
            cases.append((f"{q['id']}={q[bound]}", case))

    all_ok = True
    for name, params in cases:
        try:
            js = _run_js_mesh(args.recipe, params, node_cwd)
            py = _run_python_model(args.model, args.python, params)
        except Exception as e:
            print(f"FAIL {name}\n       ! {e}")
            all_ok = False
            continue
        all_ok &= _compare(name, py, js)

    print()
    print(f"{len(cases)} case(s), {'all parity-checked OK' if all_ok else 'PARITY MISMATCH FOUND'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
