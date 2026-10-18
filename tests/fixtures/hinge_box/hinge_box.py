#!/usr/bin/env python3
"""
hinge_box.py -- test fixture assembly: a box, a hinged lid, a plate on the foot.

    base --revolute(limits, motor)--> lid
         --fixed--> plate

The lid width follows the base through the confirmed `lid fit` rules in
rules/lid-fit.rules. Used by the tests, not shipped with the skill.
"""
import os
import sys

sys.path.insert(0, os.environ.get("CAD_BENCH_SCRIPTS")
                or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "scripts"))
import assembly as A


def make(base=None, lid=None):
    asm = A.Assembly("hinge_box", base="base", base_joint="free", path=__file__)
    asm.add("base", part="fx_base", params=base, material="PLA")
    asm.add("lid", part="fx_lid", params=lid, material="PLA")
    asm.add("plate", part="fx_lid", params={"w": 10.0, "d": 10.0}, mass=0.01)
    asm.join("base.hinge", "lid.hinge", "revolute", flip=True, limits=(0, 110),
             motor=A.Motor(torque=0.05, speed=2.0))
    asm.join("base.foot", "plate.mount", "fixed")
    asm.use_rules("lid fit", lid="lid", base="base")
    return asm


if __name__ == "__main__":
    make().run()
