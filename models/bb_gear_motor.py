#!/usr/bin/env python3
"""
bb_gear_motor.py -- stand-in gear motor for models/balance_bot.py.

Not a real motor model: a box for the gearbox and a plain round shaft along
+x. Its job is to carry the two connectors and the shaft size the wheel's
rules read. Replace with an imported STEP of the real motor (PARAMS = {} and
hand-placed connectors) once the part number is known.

Run alone:  <venv>/Scripts/python models/bb_gear_motor.py   (verified STL)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts"))
import brep as B
import assembly as A

PARAMS = {
    "body_x": 48.0,     # along the shaft
    "body_y": 22.0,
    "body_z": 18.0,
    "shaft_d": 4.0,
    "shaft_len": 14.0,
}


def derive(P):
    d = dict(P)
    d["shaft_tip"] = P["body_x"] / 2.0 + P["shaft_len"]
    return d


def build(P):
    body = B.Box(P["body_x"], P["body_y"], P["body_z"])
    shaft = B.Pos(P["body_x"] / 2.0, 0, 0) * B.Rot(0, 90, 0) * B.Cylinder(
        P["shaft_d"] / 2.0, P["shaft_len"],
        align=(B.Align.CENTER, B.Align.CENTER, B.Align.MIN))
    return body + shaft


def connectors(P):
    d = derive(P)
    return {
        "mount": A.frame((0, 0, P["body_z"] / 2.0), z=(0, 0, 1), x=(1, 0, 0)),
        "shaft": A.axis((d["shaft_tip"], 0, 0), z=(1, 0, 0)),     # tip, pointing out
    }


def main():
    part = build(PARAMS)
    if B.solid_count(part) != 1:
        raise B.VerifyError("gear motor: shaft did not fuse to the body")
    B.export_verified(part, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "bb_gear_motor.stl"), "bb-gear-motor")


if __name__ == "__main__":
    main()
