#!/usr/bin/env python3
"""
bb_wheel.py -- press-on wheel for models/balance_bot.py.

A disc with a hub boss on its inner side and a bore through. Built with its
OUTER face at z = 0 and the wheel extending towards -z, so the `hub`
connector (outer face centre, z pointing out) lands on the motor's shaft
tip and the wheel sits back over the shaft.

`bore_d` is set by the `wheel hub` rules in an assembly (motor shaft + 0.1);
the value here is only used when the wheel is built on its own.

Run alone:  <venv>/Scripts/python models/bb_wheel.py   (verified STL)
"""
import os
import sys

# The skill's scripts: CAD_BENCH_SCRIPTS (set by `cad.py assemble`), else this
# repo's own scripts/ (copied into a project, set the variable or the path).
sys.path.insert(0, os.environ.get("CAD_BENCH_SCRIPTS")
                or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import brep as B
import assembly as A

PARAMS = {
    "tyre_d": 70.0,
    "width": 8.0,
    "hub_d": 12.0,
    "hub_len": 12.0,
    "bore_d": 4.1,
    "edge_r": 1.5,      # rounded tyre edge
}


def derive(P):
    d = dict(P)
    d["hub_wall"] = (P["hub_d"] - P["bore_d"]) / 2.0
    return d


def build(P):
    down = (B.Align.CENTER, B.Align.CENTER, B.Align.MAX)
    disc = B.Cylinder(P["tyre_d"] / 2.0, P["width"], align=down)
    disc = B.safe_fillet(disc, B.circular_edges(disc, P["tyre_d"] / 2.0), P["edge_r"],
                         what="tyre edge")
    wheel = disc + B.Cylinder(P["hub_d"] / 2.0, P["hub_len"], align=down)
    return wheel - B.Pos(0, 0, 1) * B.Cylinder(P["bore_d"] / 2.0, P["hub_len"] + 2, align=down)


def connectors(P):
    return {"hub": A.axis((0, 0, 0), z=(0, 0, 1))}


def main():
    d = derive(PARAMS)
    B.wall_check("hub wall", d["hub_wall"], 2.0)
    part = build(PARAMS)
    B.export_verified(part, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "bb_wheel.stl"), "bb-wheel")


if __name__ == "__main__":
    main()
