"""fx_base.py -- test fixture: an open-topped plain box (hinge_box.py)."""
import os
import sys

# The skill's scripts: CAD_BENCH_SCRIPTS (set by `cad.py assemble`), else this
# repo's own scripts/.
sys.path.insert(0, os.environ.get("CAD_BENCH_SCRIPTS")
                or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "scripts"))
import brep as B
import assembly as A

PARAMS = {
    "w": 40.0,      # across the hinge
    "d": 30.0,
    "h": 10.0,
    "inset": 8.0,   # foot connector in from the side edge
}


def derive(P):
    d = dict(P)
    d["foot_x"] = P["w"] / 2.0 - P["inset"]
    return d


def build(P):
    return B.Box(P["w"], P["d"], P["h"],
                 align=(B.Align.CENTER, B.Align.CENTER, B.Align.MIN))


def connectors(P):
    d = derive(P)
    return {
        # hinge line along x on the back top edge; x points up
        "hinge": A.frame((0, P["d"] / 2.0, P["h"]), z=(1, 0, 0), x=(0, 0, 1)),
        # underside, pointing down
        "foot": A.frame((d["foot_x"], 0, 0), z=(0, 0, -1), x=(1, 0, 0)),
    }
