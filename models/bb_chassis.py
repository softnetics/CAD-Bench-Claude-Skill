#!/usr/bin/env python3
"""
bb_chassis.py -- balance-bot chassis plate (part of models/balance_bot.py).

A flat plate with rounded corners and two motor mounts on its underside,
each with a pair of screw holes. The mount connectors sit on the underside
at `mount_x` from the centre, so widening the plate does not move the
motors unless `mount_x` follows -- here it does: mount_x = plate_x/2 - inset.

Run alone:  <venv>/Scripts/python models/bb_chassis.py   (verified STL)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts"))
import brep as B
import assembly as A

PARAMS = {
    "plate_x": 120.0,   # across the axle
    "plate_y": 80.0,    # front to back
    "plate_t": 4.0,
    "corner_r": 8.0,
    "inset": 25.0,      # motor mount centre in from each side edge
    "hole_d": 3.2,      # M3 clearance
    "hole_pitch": 17.0, # screw spacing along the motor body
}


def derive(P):
    d = dict(P)
    d["mount_x"] = P["plate_x"] / 2.0 - P["inset"]
    return d


def build(P):
    d = derive(P)
    plate = B.Box(P["plate_x"], P["plate_y"], P["plate_t"],
                  align=(B.Align.CENTER, B.Align.CENTER, B.Align.MIN))
    plate = B.safe_fillet(plate, B.vertical_edges(plate), P["corner_r"], what="corner")
    for sx in (-1, 1):
        for dx in (-P["hole_pitch"] / 2, P["hole_pitch"] / 2):
            plate -= B.Pos(sx * d["mount_x"] + dx, 0, -1) * B.Cylinder(
                P["hole_d"] / 2, P["plate_t"] + 2,
                align=(B.Align.CENTER, B.Align.CENTER, B.Align.MIN))
    return plate


def connectors(P):
    d = derive(P)
    return {
        # underside, z out of the plate (down); x points the way the shaft goes
        "motor_l": A.frame((-d["mount_x"], 0, 0), z=(0, 0, -1), x=(-1, 0, 0)),
        "motor_r": A.frame((d["mount_x"], 0, 0), z=(0, 0, -1), x=(1, 0, 0)),
        "top": A.frame((0, 0, P["plate_t"]), z=(0, 0, 1)),     # for a board later
    }


def main():
    part = build(PARAMS)
    B.wall_check("corner radius fits", PARAMS["plate_y"] / 2 - PARAMS["corner_r"], 1.0)
    B.export_verified(part, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "bb_chassis.stl"), "bb-chassis")


if __name__ == "__main__":
    main()
