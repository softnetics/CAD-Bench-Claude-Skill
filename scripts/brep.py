#!/usr/bin/env python3
"""
brep.py -- the modelling backend for cad-bench.

Wraps `build123d` (OCCT). The kernel carries real surfaces, so fillets,
chamfers, shells, lofts, sweeps, revolves and draft are exact rather than
faceted impressions of themselves, and the true volume is known -- which is
what lets `export_verified` check tessellation for free.

This is the only backend. Plain prismatic work (boxes, cylinders, bores)
goes through it too -- there is no second path to choose between, and no
hand-computed reference volume to get wrong.

    pip install build123d          # pulls cadquery-ocp (OCCT), ~500 MB

Everything is millimetres. Import this module rather than build123d directly
-- it applies a required import-time workaround (see below) and re-exports
the whole build123d namespace:

    import brep as B
    part = B.fillet(B.Box(40, 30, 10).edges().filter_by(B.Axis.Z), radius=4)
    B.export_verified(part, "part.stl", "my-part")

## Why the import is wrapped

build123d registers every system font at import time so `Text()` works. On
Windows it walks C:/Windows/Fonts with fontTools and does NOT catch parse
errors, so a single malformed file anywhere in that folder raises
`TTLibError` and the entire `import build123d` fails. Windows 11 ships
`mstmc.ttf` (a touch-keyboard stub, not a real font) which does exactly this.

**Default pipeline: the font scan is skipped entirely**, not just filtered.
No part in this project calls `Text()` (checked 2026-09-16), and fontTools
parsing every readable font in C:/Windows/Fonts is real, measured time
(~0.85s on this machine; the docstring here previously guessed 5-6s before
that was actually timed -- don't trust an unverified number over a real one).
`_import_build123d()` makes the font-folder glob return nothing, so build123d
starts with an empty fontTools registry and skips that work.

**Verified 2026-09-16: this does NOT break `Text()`.** `build123d.Text()`
resolves its font (default "Arial", or any `font=`/`font_path=` given)
through OCCT's own font lookup at Text-build time, not through the glob this
module patches -- confirmed by building `Text("Hi", font_size=5)` with both
the default font and an explicit `font="Arial"` in both modes, same result
either way. So there is no known tradeoff for skipping the scan by default.

`BREP_FONTS=1` still exists as an escape hatch (restores the old
scan-every-readable-font behaviour) in case some future font or `Text()`
call needs it, but nothing found so far does.
"""

from __future__ import annotations
import glob as _glob
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify import VerifyError, verify, wall_check  # noqa: E402

_FONT_EXTS = ("ttf", "otf", "ttc")


def _font_readable(path):
    try:
        import logging
        # fontTools logs malformed-table complaints for several stock Windows
        # fonts. They are survivable and not ours to fix; only a raised
        # exception matters here.
        logging.getLogger("fontTools").setLevel(logging.ERROR)
        from fontTools.ttLib import TTFont, ttCollection
        if path.lower().endswith(".ttc"):
            ttCollection.TTCollection(path)
        else:
            TTFont(path)
        return True
    except Exception:
        return False


def _import_build123d():
    """Import build123d with the font-scan cost/hazard neutralised.

    Default: skip the font scan outright (BREP_FONTS unset or falsy) --
    fastest, and safe against any malformed font, but Text() has nothing to
    draw with. Set BREP_FONTS=1 to scan every readable font instead (the
    old behaviour), when a part actually needs Text().
    """
    real_glob = _glob.glob
    scan_fonts = os.environ.get("BREP_FONTS", "").strip() not in ("", "0")

    def filtered(pattern, *a, **kw):
        if isinstance(pattern, str) and pattern.lower().endswith(_FONT_EXTS):
            # build123d globs "<dir>/*ttf" -- no dot -- so match the bare suffix.
            if not scan_fonts:
                return []
            results = real_glob(pattern, *a, **kw)
            skipped = [p for p in results if not _font_readable(p)]
            for p in skipped:
                print(f"brep: skipping unreadable font {os.path.basename(p)}",
                      file=sys.stderr)
            return [p for p in results if p not in skipped]
        return real_glob(pattern, *a, **kw)

    _glob.glob = filtered
    if not scan_fonts:
        print("brep: skipping font scan (Text() is unaffected -- verified) "
              "-- set BREP_FONTS=1 to restore it", file=sys.stderr)
    # Several stock Windows fonts have malformed tables. fontTools reports
    # them with log.ERROR (not warning -- see _n_a_m_e.py), and they are
    # survivable: the font still registers. Raise the global logging threshold
    # for the import window only, so the run's own output stays readable.
    # Anything that actually matters here raises rather than logs.
    import logging
    was_disabled = logging.root.manager.disable
    logging.disable(logging.ERROR)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import build123d as _b3d
    finally:
        logging.disable(was_disabled)
        _glob.glob = real_glob
    return _b3d


try:
    _b3d = _import_build123d()
except ImportError:
    sys.exit(
        "brep: build123d is not installed. It is required.\n"
        "    pip install build123d        # ~500 MB, pulls the OCCT kernel"
    )

# Re-export the whole build123d namespace so `import brep as B` is enough.
globals().update({k: v for k, v in vars(_b3d).items() if not k.startswith("_")})
from build123d import export_stl as _export_stl  # noqa: E402
from build123d import export_step as _export_step  # noqa: E402


# --------------------------------------------------------------------------
# Selectors -- naming the right edges and faces is the hard part of scripted
# B-rep, and a wrong selection fails loudly or, worse, quietly rounds the
# wrong edge. These cover the common intents; see references/brep.md for the
# full cookbook.
# --------------------------------------------------------------------------
def vertical_edges(part):
    """The edges running along Z -- the ones you round on an upright part."""
    return part.edges().filter_by(_b3d.Axis.Z)


def top_face(part):
    """Highest face by Z centre. The usual `openings=` argument for a shell."""
    return part.faces().sort_by(_b3d.Axis.Z)[-1]


def bottom_face(part):
    return part.faces().sort_by(_b3d.Axis.Z)[0]


def top_edges(part):
    """Every edge in the highest Z group -- the rim of an upright part."""
    return part.edges().group_by(_b3d.Axis.Z)[-1]


def bottom_edges(part):
    return part.edges().group_by(_b3d.Axis.Z)[0]


def edge_loops(edges, tol=1e-4):
    """
    Partition an edge group into connected loops by shared vertices.

    This is the honest basis for telling an outer rim from an inner one.
    A radial-distance split is NOT: on a rounded rectangle the outer loop's
    own radial range (centre of a long side to centre of a corner arc)
    overlaps the inner loop's, so a distance threshold mixes them. Grouping
    by shared endpoints is topological and works for any profile.

    Returns a list of ShapeList, largest XY footprint first.
    """
    edges = list(edges)
    if not edges:
        return []

    def key(v):
        return (round(v.X / tol), round(v.Y / tol), round(v.Z / tol))

    verts = [[key(v) for v in e.vertices()] for e in edges]
    parent = list(range(len(edges)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def unite(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    seen = {}
    for i, vs in enumerate(verts):
        for v in vs:
            if v in seen:
                unite(seen[v], i)
            else:
                seen[v] = i

    groups = {}
    for i in range(len(edges)):
        groups.setdefault(find(i), []).append(edges[i])

    def footprint(group):
        xs, ys = [], []
        for e in group:
            bb = e.bounding_box()
            xs += [bb.min.X, bb.max.X]
            ys += [bb.min.Y, bb.max.Y]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))

    ordered = sorted(groups.values(), key=footprint, reverse=True)
    return [_b3d.ShapeList(g) for g in ordered]


def outer_of(edges):
    """
    The outer loop of a coplanar edge group.

    A shelled part's rim carries TWO loops at the same height, and
    `group_by(Axis.Z)[-1]` hands you both. Chamfering both eats the wall from
    each side at once -- on a 2.4 mm wall a 0.8 mm chamfer would leave 0.8 mm.
    """
    loops = edge_loops(edges)
    return loops[0] if loops else _b3d.ShapeList([])


def inner_of(edges):
    """Every loop except the outermost -- the bore/cavity rims."""
    loops = edge_loops(edges)
    out = []
    for g in loops[1:]:
        out.extend(g)
    return _b3d.ShapeList(out)


def circular_edges(part, radius=None, tol=1e-6):
    """Circular edges, optionally only those of a given radius (bore rims)."""
    edges = part.edges().filter_by(_b3d.GeomType.CIRCLE)
    if radius is None:
        return edges
    return _b3d.ShapeList([e for e in edges if abs(e.radius - radius) < tol])


# --------------------------------------------------------------------------
# Operations that fail usefully.
#
# OCCT raises a generic error when a fillet cannot be built, with no hint as
# to which radius was too big. These say so, and can find the limit for you.
# --------------------------------------------------------------------------
def safe_fillet(part, edges, radius, what="fillet"):
    """fillet() with a diagnosis instead of a bare OCCT failure."""
    try:
        return _b3d.fillet(edges, radius=radius)
    except Exception as exc:
        n = len(edges) if hasattr(edges, "__len__") else "?"
        raise VerifyError(
            f"{what}: radius {radius} mm failed on {n} edge(s) -- {exc}. "
            f"Largest that works here is about "
            f"{max_fillet(part, edges):.2f} mm. A fillet cannot exceed the "
            f"thinnest adjacent wall, and neighbouring fillets cannot overlap."
        ) from exc


def safe_chamfer(part, edges, length, what="chamfer"):
    try:
        return _b3d.chamfer(edges, length=length)
    except Exception as exc:
        raise VerifyError(f"{what}: length {length} mm failed -- {exc}") from exc


def max_fillet(part, edges, lo=0.0, hi=None, steps=18):
    """
    Largest radius that still builds, by bisection. Use it to report a limit
    in an error, or to pick a radius from a fraction of the maximum.
    """
    if hi is None:
        bb = part.bounding_box()
        hi = min(bb.size.X, bb.size.Y, bb.size.Z) / 2.0
    best = lo
    for _ in range(steps):
        mid = (lo + hi) / 2.0
        try:
            _b3d.fillet(edges, radius=mid)
            best, lo = mid, mid
        except Exception:
            hi = mid
    return best


# --------------------------------------------------------------------------
# Export + verification.
#
# The kernel knows the exact volume, so the gate is "did tessellation lose
# anything it should not have" -- no hand computation needed. At the default
# tolerances the loss is well under 0.1%.
# --------------------------------------------------------------------------
def export_verified(part, path, name, tolerance=0.01, angular_tolerance=0.1,
                    tol=0.005, expect_bbox=None, step=False, verbose=False):
    """
    Tessellate `part` to `path`, then gate the result:
      - watertight, winding-consistent, positive volume
      - mesh volume within `tol` of the kernel's EXACT volume
      - bounding box, if `expect_bbox` given
    Returns the loaded trimesh. Raises VerifyError rather than writing a part
    that is wrong, and deletes the file if it does.

    OUTPUT IS ONE LINE ON SUCCESS (path, volume, tessellation loss, file
    size). Pass `verbose=True` for the full per-axis report -- useful while
    first writing a model, noise on every routine re-run afterwards. A
    failure always prints in full regardless of `verbose`, because that is
    when the numbers are worth reading.

    A PASS IS A PASS. Do not re-export a part that already cleared the gate
    with a tighter `tolerance` because the margin "felt close" -- the gate is
    0.5% and 0.4% is fine. Halving tolerance multiplies triangle count and
    file size several-fold for geometry no printer will resolve. Tighten only
    when the gate actually fails, which means the tessellation genuinely is
    too coarse for the part's curvature.

    Set `step=True` to also write a STEP file beside the STL -- exact
    geometry, for handing to another CAD tool or for a machinist.
    """
    import trimesh

    exact = part.volume
    if not _export_stl(part, path, tolerance=tolerance,
                       angular_tolerance=angular_tolerance):
        raise VerifyError(f"{name}: export_stl returned False for {path}")

    mesh = trimesh.load(path)
    try:
        verify(mesh, name, reference_volume=exact, tol=tol,
               expect_bbox=expect_bbox, reference_label="exact (kernel)",
               verbose=verbose)
    except VerifyError:
        os.remove(path)          # never leave a failed part on disk
        raise

    mb = os.path.getsize(path) / 1e6
    if verbose:
        print(f"  file              : {mb:.2f} MB, {len(mesh.faces)} triangles")
        print(f"  -> {path}")
    else:
        print(f"  {mb:.2f} MB, {len(mesh.faces)} tri -> {path}")
    if len(mesh.faces) > 100_000:
        print(f"  NOTE: {len(mesh.faces)} triangles is a lot for a printed part. "
              f"The gate passed, so tolerance={tolerance} is already fine -- "
              f"raising it would shrink this file with no loss that matters.")

    if step:
        spath = os.path.splitext(path)[0] + ".step"
        _export_step(part, spath)
        print(f"  -> {spath}  (exact geometry)")
    return mesh


def solid_count(part):
    """More than one solid usually means a boolean did not merge as intended."""
    return len(part.solids())
