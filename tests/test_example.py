"""The worked balance-bot assembly: clean, and a resize carries through."""
import runpy
from pathlib import Path

import numpy as np
import pytest

MODELS = Path(__file__).resolve().parent.parent / "models"


@pytest.fixture(scope="module")
def make():
    return runpy.run_path(str(MODELS / "balance_bot.py"))["make"]


def test_runs_clean_in_one_line(make, tmp_path, capsys):
    make().run(out_dir=tmp_path)
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("balance_bot: 5 parts, 4 joints, 4/4 rules ok -> ")
    assert (tmp_path / "balance_bot.xml").is_file()
    assert (tmp_path / "balance_bot.step").is_file()


def test_shaft_change_moves_the_bore_through_the_rule(make):
    s = make(motor={"shaft_d": 5.0}).solve()
    assert s.instances["wheel_l"].P["bore_d"] == pytest.approx(5.1)
    assert s.warnings == []


def test_chassis_width_carries_motors_and_wheels(make):
    narrow = make().solve()
    wide = make(chassis={"plate_x": 160.0}).solve()
    for inst, dx in (("motor_l", -20), ("wheel_l", -20), ("motor_r", 20), ("wheel_r", 20)):
        shift = wide.placement(inst)[:3, 3] - narrow.placement(inst)[:3, 3]
        assert np.allclose(shift, (dx, 0, 0)), inst


def test_short_shaft_breaks_a_rule_but_still_exports(make, tmp_path, capsys):
    make(wheel={"hub_len": 5.0}).run(out_dir=tmp_path)
    out = capsys.readouterr().out
    assert "rule broken: wheel_l.hub_len >= 1.5 * motor_l.shaft_d: 5 vs 6" in out
    assert (tmp_path / "balance_bot.xml").is_file()
