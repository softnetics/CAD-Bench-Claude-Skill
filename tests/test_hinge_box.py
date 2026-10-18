"""The hinge_box fixture assembly: clean, and a resize carries through."""
import runpy
from pathlib import Path

import numpy as np
import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "hinge_box"


@pytest.fixture(scope="module")
def make():
    return runpy.run_path(str(FIXTURE / "hinge_box.py"))["make"]


def test_runs_clean_in_one_line(make, tmp_path, capsys):
    make().run(out_dir=tmp_path)
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("hinge_box: 3 parts, 2 joints, 2/2 rules ok -> ")
    for ext in ("xml", "step", "png"):
        assert (tmp_path / f"hinge_box.{ext}").is_file()
    assert (tmp_path / "report.txt").is_file()


def test_exported_mjcf_loads_with_the_hinge_limits_and_motor(make, tmp_path):
    mujoco = pytest.importorskip("mujoco")
    make().run(out_dir=tmp_path)
    model = mujoco.MjModel.from_xml_path(str(tmp_path / "hinge_box.xml"))
    assert model.nu == 1 and model.njnt == 2      # free base + the hinge
    hinge = model.jnt_range[model.jnt_limited.astype(bool)]
    assert np.allclose(np.degrees(hinge), [[0, 110]])


def test_base_width_change_moves_the_lid_width_through_the_rule(make):
    s = make(base={"w": 60.0}).solve()
    assert s.instances["lid"].P["w"] == pytest.approx(60.0)
    assert s.warnings == []


def test_base_width_carries_the_foot_plate(make):
    narrow = make().solve()
    wide = make(base={"w": 60.0}).solve()
    shift = wide.placement("plate")[:3, 3] - narrow.placement("plate")[:3, 3]
    assert np.allclose(shift, (10, 0, 0))


def test_thin_lid_breaks_a_rule_but_still_exports(make, tmp_path, capsys):
    make(lid={"t": 1.0}).run(out_dir=tmp_path)
    out = capsys.readouterr().out
    assert "rule broken: lid.t >= base.h / 5: 1 vs 2" in out
    assert (tmp_path / "hinge_box.xml").is_file()
