"""run(): report, picture, STEP, MuJoCo model; one line on a clean run."""
import xml.etree.ElementTree as ET

import numpy as np
import pytest

import assembly as A

BLOCK = '''
import brep as B
import assembly as A
PARAMS = {"x": 40.0, "y": 30.0, "h": 10.0}
def derive(P): return dict(P)
def build(P):
    return B.Box(P["x"], P["y"], P["h"],
                 align=(B.Align.CENTER, B.Align.CENTER, B.Align.MIN))
def connectors(P):
    return {"top": A.frame((0, 0, P["h"]), z=(0, 0, 1)),
            "bottom": A.frame((0, 0, 0), z=(0, 0, -1)),
            "side": A.axis((P["x"] / 2, 0, P["h"] / 2), z=(1, 0, 0))}
'''

DISC = '''
import brep as B
import assembly as A
PARAMS = {"d": 30.0, "w": 5.0}
def derive(P): return dict(P)
def build(P):
    return B.Cylinder(P["d"] / 2, P["w"],
                      align=(B.Align.CENTER, B.Align.CENTER, B.Align.MAX))
def connectors(P):
    return {"hub": A.axis((0, 0, -P["w"]), z=(0, 0, -1))}
'''


def project(root, layout="flat"):
    parts = root / "cad" / "parts" if layout == "cad" else root
    parts.mkdir(parents=True, exist_ok=True)
    (parts / "block.py").write_text(BLOCK)
    (parts / "disc.py").write_text(DISC)
    asm_dir = root / "cad" / "assemblies" if layout == "cad" else root
    asm_dir.mkdir(parents=True, exist_ok=True)
    return asm_dir / "cart.py"


def cart(path, base_joint="free"):
    asm = A.Assembly("cart", path=path, base_joint=base_joint)
    asm.add("body", part="block", material="PLA")
    asm.add("wheel", part="disc", mass=0.05)
    asm.join("body.side", "wheel.hub", "wheel", gap=1.0, motor=A.Motor(torque=0.2, speed=20))
    return asm


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    root = tmp_path_factory.mktemp("cart")
    path = project(root)
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        solved = cart(path).run()
    return root, solved, buf.getvalue()


def test_clean_run_prints_one_line(ran):
    root, solved, out = ran
    lines = out.strip().splitlines()
    assert len(lines) == 1, out
    assert lines[0].startswith("cart: 2 parts, 1 joint")
    assert "exports" in lines[0]


def test_all_files_written(ran):
    root, _, _ = ran
    d = root / "exports" / "cart"
    for f in ("report.txt", "cart.png", "cart.step", "cart.xml",
              "meshes/body.stl", "meshes/wheel.stl"):
        assert (d / f).is_file(), f
    report = (d / "report.txt").read_text(encoding="utf-8")
    assert "wheel" in report and "body.side" in report and "mass" in report


def test_picture_is_an_image(ran):
    from PIL import Image
    root, _, _ = ran
    im = Image.open(root / "exports" / "cart" / "cart.png")
    assert im.size[0] >= 800
    px = np.asarray(im.convert("RGB")).reshape(-1, 3)
    # connector markers: pure-ish red, green and blue pixels exist
    assert ((px[:, 0] > 200) & (px[:, 1] < 60) & (px[:, 2] < 60)).any()
    assert ((px[:, 2] > 200) & (px[:, 0] < 60) & (px[:, 1] < 90)).any()


def test_step_holds_both_parts(ran):
    import brep as B
    root, _, _ = ran
    shape = B.import_step(str(root / "exports" / "cart" / "cart.step"))
    vol = 40 * 30 * 10 + np.pi * 15 ** 2 * 5
    assert len(shape.solids()) == 2
    assert shape.volume == pytest.approx(vol, rel=1e-6)


def test_mjcf_loads_steps_and_has_cad_masses(ran):
    import mujoco
    root, _, _ = ran
    xml = root / "exports" / "cart" / "cart.xml"
    m = mujoco.MjModel.from_xml_path(str(xml))
    d = mujoco.MjData(m)
    for _ in range(100):
        mujoco.mj_step(m, d)
    assert np.isfinite(d.qpos).all()
    body = m.body("body")
    assert m.body_mass[body.id] == pytest.approx(40 * 30 * 10 * 1.24e-6, rel=1e-6)
    assert m.body_mass[m.body("wheel").id] == pytest.approx(0.05)
    # box inertia about its own centre: m (y^2 + h^2) / 12, in kg m^2
    mass = 40 * 30 * 10 * 1.24e-6
    want = sorted([mass * (30e-3 ** 2 + 10e-3 ** 2) / 12, mass * (40e-3 ** 2 + 10e-3 ** 2) / 12,
                   mass * (40e-3 ** 2 + 30e-3 ** 2) / 12])
    assert sorted(m.body_inertia[body.id]) == pytest.approx(want, rel=1e-6)
    tree = ET.parse(xml).getroot()
    assert tree.find(".//body[@name='body']/freejoint") is not None
    hinge = tree.find(".//joint[@name='body.side-wheel.hub']")
    assert hinge.get("type") == "hinge" and hinge.get("limited") is None
    act = tree.find(".//actuator/motor")
    assert act.get("joint") == "body.side-wheel.hub" and act.get("ctrlrange") == "-0.2 0.2"
    assert tree.find(".//custom/numeric").get("data") == "20"


def test_free_base_sits_on_the_floor(ran):
    import mujoco
    root, _, _ = ran
    m = mujoco.MjModel.from_xml_path(str(root / "exports" / "cart" / "cart.xml"))
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    # lowest point is the wheel rim: wheel centre at h/2 above the body bottom
    # so the body was lifted until the wheel touches z = 0
    lift = m.body_pos[m.body("body").id][2]
    assert lift == pytest.approx((15 - 5) / 1000, abs=1e-6)


def test_cad_layout_exports_to_cad_exports(tmp_path, capsys):
    path = project(tmp_path, layout="cad")
    cart(path, base_joint="fixed").run()
    assert (tmp_path / "cad" / "exports" / "cart" / "cart.xml").is_file()
    assert not (tmp_path / "cad" / "assemblies" / "exports").exists()
    out = capsys.readouterr().out
    assert "cad" in out.splitlines()[0]


def test_warnings_print_one_line_each_and_still_export(tmp_path, capsys):
    path = project(tmp_path)
    asm = A.Assembly("loose", path=path)
    asm.add("body", part="block")
    asm.add("wheel", part="disc")
    asm.join("body.side", "wheel.hub", "fixed")          # axis on fixed: roll free
    asm.rule("wheel.d >= 100", why="big wheel", confirmed=True)
    asm.run()
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].startswith("loose: 2 parts, 1 joint, 0/1 rules ok, 2 warnings")
    assert len(lines) == 3 and all(x.startswith("  warn: ") for x in lines[1:])
    assert (tmp_path / "exports" / "loose" / "loose.xml").is_file()


def test_rerun_overwrites(tmp_path, capsys):
    path = project(tmp_path)
    cart(path).run()
    cart(path).run()
    assert (tmp_path / "exports" / "cart" / "cart.xml").is_file()


def _hinge_state(tmp_path, base, q):
    """Range, and the arm's turn in the body's frame from angle 0 to angle q.

    The base differs between calls, so the world frame does too; everything is
    compared in the body's frame.
    """
    import mujoco

    import asm_export
    import mjcf
    path = project(tmp_path / base)
    asm = A.Assembly("hinge", path=path, base=base, base_joint="fixed")
    asm.add("body", part="block")
    asm.add("arm", part="block")
    asm.join("body.side", "arm.bottom", "revolute", limits=(0, 90),
             motor=A.Motor(torque=0.1))
    solved = asm.solve()
    masses = {n: asm_export.mass_properties(i) for n, i in solved.instances.items()}
    xml = path.parent / "hinge.xml"
    mjcf.write(solved, xml, masses)
    m = mujoco.MjModel.from_xml_path(str(xml))
    d = mujoco.MjData(m)
    j = m.joint("body.side-arm.bottom")

    def arm_in_body(angle):
        d.qpos[j.qposadr[0]] = angle
        mujoco.mj_forward(m, d)
        Rb, Ra = (d.xmat[m.body(n).id].reshape(3, 3) for n in ("body", "arm"))
        return Rb.T @ Ra

    turn = arm_in_body(q) @ arm_in_body(0.0).T
    return tuple(m.jnt_range[j.id]), turn


def _turn_axis(R):
    v = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    return v / np.linalg.norm(v)


def test_hinge_sense_and_limits_do_not_depend_on_which_part_is_placed_first(tmp_path):
    q = np.radians(30)
    rng1, turn1 = _hinge_state(tmp_path, "body", q)     # arm is the child
    rng2, turn2 = _hinge_state(tmp_path, "arm", q)      # body is the child
    assert rng1 == pytest.approx((0, np.pi / 2), abs=1e-5) and rng2 == pytest.approx(rng1)
    # a positive angle turns the arm about +body.side z (+x), whichever came first
    assert np.allclose(_turn_axis(turn1), (1, 0, 0), atol=1e-9)
    assert np.allclose(_turn_axis(turn2), (1, 0, 0), atol=1e-9)
    assert np.allclose(turn2, turn1, atol=1e-9)
