#!/usr/bin/env python3
"""
_parity_demo.py -- minimal fixture for scripts/check_mesh_parity.py's own
self-test, not a real part. A box with a cylindrical bore through it: just
complex enough (two primitives, a boolean) to prove the parity checker
catches real drift, simple enough that its exact volume is easy to hand
-verify (box_x*box_y*box_z - pi*(bore_d/2)^2*box_z) while double-checking
the checker itself.

Paired with models/_parity_demo.recipe.js, which builds the SAME shape in
three.js + three-bvh-csg via an explicit mesh(p, THREE, CSG) function. Keep
both in sync by hand when editing -- that manual sync being fallible is
the entire reason check_mesh_parity.py exists.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import brep as B

PARAMS = {
    "box_x": 20.0,
    "box_y": 16.0,
    "box_z": 10.0,
    "bore_d": 6.0,
}


def derive(P):
    d = dict(P)
    d["bore_r"] = P["bore_d"] / 2.0
    return d


def build(P):
    d = derive(P)
    part = B.Box(P["box_x"], P["box_y"], P["box_z"],
                align=(B.Align.CENTER, B.Align.CENTER, B.Align.CENTER))
    bore = B.Cylinder(d["bore_r"], P["box_z"] + 2.0,
                      align=(B.Align.CENTER, B.Align.CENTER, B.Align.CENTER))
    return part - bore


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    P = dict(PARAMS)
    over = os.path.join(here, "_parity_demo.params.json")
    if os.path.exists(over):
        with open(over) as fh:
            P.update({k: float(v) for k, v in json.load(fh).items() if k in PARAMS})

    part = build(P)
    B.export_verified(part, os.path.join(here, "_parity_demo.stl"), "_parity_demo",
                      tolerance=0.01, angular_tolerance=0.1)


if __name__ == "__main__":
    main()
