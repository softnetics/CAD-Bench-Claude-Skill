import math
import time

import brep as B
import views


def build():
    p = B.Box(80, 60, 30, align=(B.Align.CENTER, B.Align.CENTER, B.Align.MIN))
    p = B.fillet(p.edges().filter_by(B.Axis.Z), radius=6)
    p = B.offset(p, amount=-2.4, openings=p.faces().sort_by(B.Axis.Z)[-1])
    bore = B.Pos(0, 0, 15) * B.Cylinder(4, 200, rotation=(0, 90, 0))
    return p - bore


def test_all_views_present_with_hidden_edges():
    v = views.project(build())
    assert set(v) == {"top", "front", "side", "iso"}
    assert v["front"]["hid"] and v["side"]["hid"]


def test_bore_visible_in_side_view():
    v = views.project(build())
    found = False
    for pl in v["side"]["vis"]:
        if len(pl) > 8 and math.dist(pl[0], pl[-1]) < 1e-2:
            cx = (min(p[0] for p in pl) + max(p[0] for p in pl)) / 2
            cy = (min(p[1] for p in pl) + max(p[1] for p in pl)) / 2
            rs = [math.hypot(p[0] - cx, p[1] - cy) for p in pl]
            if abs(cx) < 0.5 and abs(cy - 15) < 0.5 and all(abs(r - 4) < 0.05 for r in rs):
                found = True
    assert found


def test_svg_has_dashed_hidden():
    svg = views.to_svg(views.project(build(), names=("front",))["front"])
    assert 'class="hid"' in svg and "stroke-dasharray" in svg
    assert "<svg" in svg and "viewBox" in svg


def test_sheet_has_four_captions():
    svg = views.sheet_svg(views.project(build()))
    for n in ("top", "front", "side", "iso"):
        assert n in svg


def test_speed():
    build()
    views.project(build(), names=("top", "front", "side"))
    t = time.perf_counter()
    views.project(build(), names=("top", "front", "side"))
    assert time.perf_counter() - t < 0.5
