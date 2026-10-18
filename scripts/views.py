#!/usr/bin/env python3
"""views.py -- exact hidden-line views straight from the B-rep kernel.

`project()` returns polylines (visible + hidden) per named view; `to_svg()`
and `sheet_svg()` render them. Replaces hand-drawn sketches on the bench page.
"""
from __future__ import annotations

import brep as B

# name -> (viewing direction, up)
VIEWS = {
    "top": ((0, 0, 1), (0, 1, 0)),
    "front": ((0, -1, 0), (0, 0, 1)),
    "side": ((1, 0, 0), (0, 0, 1)),
    "iso": ((1, -1, 1), (0, 0, 1)),
}


def _polylines(compound, samples):
    out = []
    for e in compound.edges():
        n = 1 if e.geom_type == B.GeomType.LINE else samples
        pts = [e.position_at(i / n) for i in range(n + 1)]
        out.append([[round(p.X, 3), round(p.Y, 3)] for p in pts])
    return out


def project(part, names=("top", "front", "side", "iso"), distance=1000.0, samples=24):
    result = {}
    for name in names:
        d, up = VIEWS[name]
        origin = tuple(c * distance for c in d)
        vis, hid = part.project_to_viewport(origin, viewport_up=up, look_at=(0, 0, 0))
        result[name] = {"vis": _polylines(vis, samples), "hid": _polylines(hid, samples)}
    return result


def _bounds(view):
    pts = [p for k in ("vis", "hid") for pl in view[k] for p in pl]
    if not pts:
        return 0.0, 0.0, 1.0, 1.0
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _paths(view, key, cls, extra=""):
    ds = []
    for pl in view[key]:
        ds.append("M" + " L".join(f"{x:g} {-y:g}" for x, y in pl))
    if not ds:
        return ""
    return (f'<path class="{cls}" d="{" ".join(ds)}" fill="none" '
            f'vector-effect="non-scaling-stroke"{extra}/>')


def _body(view):
    return (_paths(view, "hid", "hid", ' stroke="#888" stroke-width="1" stroke-dasharray="4 3"')
            + _paths(view, "vis", "vis", ' stroke="#111" stroke-width="1.5"'))


def _viewbox(view, pad=0.06):
    x0, y0, x1, y1 = _bounds(view)
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    px, py = w * pad, h * pad
    # y is flipped: svg y = -y
    return x0 - px, -y1 - py, w + 2 * px, h + 2 * py


def to_svg(view, width=320, height=240):
    vx, vy, vw, vh = _viewbox(view)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="{vx:g} {vy:g} {vw:g} {vh:g}">{_body(view)}</svg>')


def sheet_svg(views, cell_w=320, cell_h=240):
    order = [n for n in ("top", "front", "side", "iso") if n in views]
    parts = []
    for i, name in enumerate(order):
        x, y = (i % 2) * cell_w, (i // 2) * cell_h
        vx, vy, vw, vh = _viewbox(views[name])
        parts.append(
            f'<svg x="{x}" y="{y + 16}" width="{cell_w}" height="{cell_h - 16}" '
            f'viewBox="{vx:g} {vy:g} {vw:g} {vh:g}">{_body(views[name])}</svg>'
            f'<text x="{x + 6}" y="{y + 12}" font-family="sans-serif" font-size="11" fill="#444">{name}</text>')
    rows = (len(order) + 1) // 2
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{2 * cell_w}" height="{rows * cell_h}" '
            f'viewBox="0 0 {2 * cell_w} {rows * cell_h}"><rect width="100%" height="100%" fill="#fff"/>'
            + "".join(parts) + "</svg>")
