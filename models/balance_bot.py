#!/usr/bin/env python3
"""
balance_bot.py -- worked assembly: two-wheel balance-bot chassis.

    chassis --fixed--> motor_l --wheel(motored)--> wheel_l
            --fixed--> motor_r --wheel(motored)--> wheel_r

No world coordinates: each part is placed by matching connectors. The wheel
bores follow the motor shaft through the confirmed `wheel hub` rules in
models/rules/wheel-hub.rules. Motor mass and limits are stand-ins until
project 3 reads a datasheet.

Run:  <venv>/Scripts/python models/balance_bot.py
      -> models/exports/balance_bot/{report.txt, .png, .step, .xml, meshes/}
"""
import os
import sys

# The skill's scripts: CAD_BENCH_SCRIPTS (set by `cad.py assemble`), else this
# repo's own scripts/ (copied into a project, set the variable or the path).
sys.path.insert(0, os.environ.get("CAD_BENCH_SCRIPTS")
                or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import assembly as A


def make(chassis=None, motor=None, wheel=None):
    asm = A.Assembly("balance_bot", base="chassis", base_joint="free", path=__file__)
    asm.add("chassis", part="bb_chassis", params=chassis, material="PLA")
    for side in ("l", "r"):
        asm.add(f"motor_{side}", part="bb_gear_motor", params=motor, mass=0.03)
        asm.add(f"wheel_{side}", part="bb_wheel", params=wheel, material="PLA")
        asm.join(f"chassis.motor_{side}", f"motor_{side}.mount", "fixed")
        asm.join(f"motor_{side}.shaft", f"wheel_{side}.hub", "wheel", flip=True,
                 motor=A.Motor(torque=0.08, speed=20.0))
        asm.use_rules("wheel hub", wheel=f"wheel_{side}", shaft=f"motor_{side}")
    return asm


if __name__ == "__main__":
    make().run()
