"""Connectors, placement by frame matching, and the warn-only checks."""
import textwrap

import numpy as np
import pytest

import assembly as A

BOX = '''
import brep as B
import assembly as A
PARAMS = {"x": 40.0, "y": 30.0, "h": 10.0}
def derive(P):
    return dict(P)
def build(P):
    return B.Box(P["x"], P["y"], P["h"],
                 align=(B.Align.CENTER, B.Align.CENTER, B.Align.MIN))
def connectors(P):
    return {
        "top": A.frame((0, 0, P["h"]), z=(0, 0, 1)),
        "bottom": A.frame((0, 0, 0), z=(0, 0, -1)),
        "side": A.frame((P["x"] / 2, 0, P["h"] / 2), z=(1, 0, 0)),
        "pin": A.axis((0, 0, P["h"]), z=(0, 0, 1)),
        "dot": A.point((0, 0, P["h"])),
        %EXTRA%
    }
'''


def write_part(folder, name, extra=""):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.py").write_text(BOX.replace("%EXTRA%", extra))
    return folder / f"{name}.py"


@pytest.fixture
def parts(tmp_path):
    write_part(tmp_path, "box")
    return tmp_path


def make(parts, **kw):
    return A.Assembly("t", path=parts / "t.py", **kw)


def origin_of(solved, inst):
    return solved.placement(inst)[:3, 3]


# ---------------------------------------------------------------- frames

def test_frame_is_orthonormal_and_axis_picks_deterministic_x():
    f = A.frame((1, 2, 3), z=(0, 0, 2), x=(1, 1, 0))
    m = f.matrix()
    assert np.allclose(m[:3, :3].T @ m[:3, :3], np.eye(3))
    assert np.allclose(m[:3, 2], (0, 0, 1))
    assert np.allclose(m[:3, 3], (1, 2, 3))
    a = A.axis((0, 0, 0), z=(0, 0, 1))
    assert a.kind == "axis"
    assert np.allclose(a.matrix(), A.axis((0, 0, 0), z=(0, 0, 1)).matrix())
    assert A.point((0, 0, 0)).kind == "point"


def test_geometry_helpers_follow_the_feature():
    import brep as B
    box = B.Box(10, 20, 30, align=(B.Align.CENTER, B.Align.CENTER, B.Align.MIN))
    f = A.on_face(B.top_face(box))
    assert np.allclose(f.matrix()[:3, 3], (0, 0, 30))
    assert np.allclose(f.matrix()[:3, 2], (0, 0, 1))
    e = A.on_edge(box.edges().filter_by(B.Axis.X).sort_by(B.Axis.Z)[0])
    assert abs(e.matrix()[2, 3]) < 1e-9
    assert abs(abs(e.matrix()[0, 0]) - 1) < 1e-9   # x along the edge
    cyl = B.Cylinder(5, 8)
    c = A.on_circle(B.circular_edges(cyl).sort_by(B.Axis.Z)[-1])
    assert np.allclose(c.matrix()[:3, 3], (0, 0, 4))
    assert c.kind == "axis"


# ---------------------------------------------------------------- placement

def test_join_puts_b_on_top_of_a_and_follows_a_resize(parts):
    for h in (10.0, 25.0):
        asm = make(parts)
        asm.add("a", part="box", params={"h": h})
        asm.add("b", part="box")
        asm.join("a.top", "b.bottom", "fixed")
        s = asm.solve()
        assert np.allclose(origin_of(s, "b"), (0, 0, h))
        # orientation unchanged: opposed z axes put b upright
        assert np.allclose(s.placement("b")[:3, :3], np.eye(3))
        assert s.warnings == []


def test_flip_angle_gap(parts):
    asm = make(parts)
    asm.add("a", part="box")
    asm.add("b", part="box")
    asm.join("a.top", "b.top", "fixed", flip=False, gap=2)
    s = asm.solve()
    # top-to-top opposed: b is upside down, its top 2 mm above a's top
    assert np.allclose(origin_of(s, "b"), (0, 0, 22))
    assert np.allclose(s.placement("b")[:3, 2], (0, 0, -1))

    asm = make(parts)
    asm.add("a", part="box")
    asm.add("b", part="box")
    asm.join("a.top", "b.bottom", "fixed", angle=90)
    s = asm.solve()
    assert np.allclose(s.placement("b")[:3, 0], (0, 1, 0), atol=1e-9)

    asm = make(parts)
    asm.add("a", part="box")
    asm.add("b", part="box")
    asm.join("a.top", "b.top", "fixed", flip=True)
    s = asm.solve()
    # flip aligns z: b's top lands on a's top with b pointing up -> b sits inside a
    assert np.allclose(origin_of(s, "b"), (0, 0, 0))


def test_unknown_connector_lists_names(parts):
    asm = make(parts)
    asm.add("a", part="box")
    asm.add("b", part="box")
    asm.join("a.nope", "b.bottom")
    with pytest.raises(A.AssemblyError, match="top.*bottom"):
        asm.solve()


def test_unknown_part_file(parts):
    asm = make(parts)
    with pytest.raises(A.AssemblyError, match="no part file"):
        asm.add("a", part="missing")


def test_part_without_connectors_is_fine_as_base(parts):
    (parts / "plain.py").write_text(textwrap.dedent('''
        import brep as B
        PARAMS = {"s": 10.0}
        def derive(P): return dict(P)
        def build(P): return B.Box(P["s"], P["s"], P["s"])
    '''))
    asm = make(parts)
    asm.add("p", part="plain")
    s = asm.solve()
    assert s.warnings == []


def test_parts_folder_layout(tmp_path):
    write_part(tmp_path / "cad" / "parts", "box")
    asm = A.Assembly("t", path=tmp_path / "cad" / "assemblies" / "t.py")
    asm.add("a", part="box")
    assert asm.solve().warnings == []


# ---------------------------------------------------------------- checks

def test_unjoined_part_names_six_free_motions(parts):
    asm = make(parts)
    asm.add("a", part="box")
    asm.add("b", part="box")
    w = [x for x in asm.solve().warnings if "under-defined" in x]
    assert len(w) == 1 and w[0].startswith("b:") and "6 free" in w[0]


def test_axis_connector_on_fixed_joint_leaves_rotation_free(parts):
    asm = make(parts)
    asm.add("a", part="box")
    asm.add("b", part="box")
    asm.join("a.pin", "b.bottom", "fixed")
    w = asm.solve().warnings
    assert len(w) == 1 and "rotation about z" in w[0]


def test_axis_connector_on_revolute_is_fully_defined(parts):
    asm = make(parts)
    asm.add("a", part="box")
    asm.add("b", part="box")
    asm.join("a.pin", "b.bottom", "revolute")
    assert asm.solve().warnings == []


def test_point_connector_leaves_three_rotations(parts):
    asm = make(parts)
    asm.add("a", part="box")
    asm.add("b", part="box")
    asm.join("a.dot", "b.bottom", "fixed")
    w = asm.solve().warnings
    assert "rotation about x" in w[0] and "rotation about y" in w[0]


def test_loop_mismatch_is_reported(parts):
    asm = make(parts)
    asm.add("a", part="box")
    asm.add("b", part="box")
    asm.join("a.top", "b.bottom")
    asm.join("a.side", "b.bottom")
    w = asm.solve().warnings
    assert any("disagrees" in x for x in w)


def test_overlap_flagged_and_allowed(parts):
    asm = make(parts)
    asm.add("a", part="box")
    asm.add("b", part="box")
    asm.join("a.top", "b.top", flip=True)        # b sits inside a
    w = asm.solve().warnings
    assert any("overlap" in x and "mm^3" in x for x in w)

    asm = make(parts)
    asm.add("a", part="box")
    asm.add("b", part="box")
    asm.join("a.top", "b.top", flip=True)
    asm.allow_overlap("a", "b")
    assert asm.solve().warnings == []


def test_hard_coded_connector_flagged_but_anchor_is_not(parts):
    write_part(parts, "hc", extra='"stuck": A.frame((15, 0, P["h"]), z=(0, 0, 1)),')
    asm = make(parts)
    asm.add("a", part="hc")
    w = asm.solve().warnings
    assert len(w) == 1
    assert "a.stuck" in w[0] and "x stays at 15" in w[0]


def test_part_origin_counts_as_an_anchor(parts):
    # bbox is lopsided (a stub on +x) so x = 0 is not a bbox landmark, but it
    # is the part's own origin: a deliberate datum, not a typed-in number
    (parts / "stub.py").write_text(textwrap.dedent('''
        import brep as B
        import assembly as A
        PARAMS = {"x": 40.0, "stub": 10.0}
        def derive(P): return dict(P)
        def build(P):
            return B.Box(P["x"], 20, 10) + B.Pos(P["x"] / 2, 0, 0) * B.Box(
                P["stub"], 4, 4, align=(B.Align.MIN, B.Align.CENTER, B.Align.CENTER))
        def connectors(P): return {"mount": A.frame((0, 0, 5), z=(0, 0, 1))}
    '''))
    asm = make(parts)
    asm.add("s", part="stub")
    assert asm.solve().warnings == []


def test_imported_part_skips_hard_coded_check(parts, tmp_path):
    import brep as B
    step = tmp_path / "blk.step"
    B.export_step(B.Box(10, 10, 10), str(step))
    (parts / "blk.py").write_text(textwrap.dedent(f'''
        import brep as B
        import assembly as A
        PARAMS = {{}}
        def derive(P): return dict(P)
        def build(P): return B.import_step(r"{step}")
        def connectors(P): return {{"top": A.frame((3, 0, 5), z=(0, 0, 1))}}
    '''))
    asm = make(parts)
    asm.add("box", part="box")
    asm.add("blk", part="blk")
    asm.join("box.top", "blk.top", flip=False)
    s = asm.solve()
    assert s.warnings == []
    assert np.allclose(origin_of(s, "blk"), (-3, 0, 15))
