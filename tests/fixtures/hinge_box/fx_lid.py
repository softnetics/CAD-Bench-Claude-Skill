"""fx_lid.py -- test fixture: a flat lid (hinge_box.py)."""
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
    "w": 40.0,
    "d": 30.0,
    "t": 2.0,
}


def derive(P):
    return dict(P)


def build(P):
    return B.Box(P["w"], P["d"], P["t"],
                 align=(B.Align.CENTER, B.Align.CENTER, B.Align.MIN))


def connectors(P):
    return {
        # back bottom edge, same orientation as the base's hinge
        "hinge": A.frame((0, P["d"] / 2.0, 0), z=(1, 0, 0), x=(0, 0, 1)),
        # top face centre, pointing up
        "mount": A.frame((0, 0, P["t"]), z=(0, 0, 1), x=(1, 0, 0)),
    }
