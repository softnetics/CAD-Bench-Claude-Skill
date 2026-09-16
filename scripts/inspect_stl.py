#!/usr/bin/env python3
"""
inspect_stl.py -- structured first look at an existing STL, before writing a
single line of a reconstruction model.

Born from a real miss: a first pass at reverse-engineering a part sampled a
handful of GUESSED Z heights (0, 1, 2, 5, 10, 17.5, 25...) and silently
skipped the two heights (0.2 and 15) where a blind hole actually lived,
reading its mouth-chamfer rim as a "valley" in an unrelated outer profile
instead. The fix is not "sample more carefully" -- it's not sampling at all:
every distinct Z the mesh actually has vertices at is cheap to list exactly,
so list it and never guess. See references/stl-reverse-engineering.md for
the full method this script exists to make fast.

    python scripts/inspect_stl.py part.stl
    python scripts/inspect_stl.py part.stl --z 0.2           # detail one Z
    python scripts/inspect_stl.py part.stl --z 0.2 --center 0 0

Output:
  - volume, bbox, watertight (the same facts export_verified gates on --
    this script's volume number is what you compare a reconstruction's
    kernel-exact volume against, NOT the reconstruction's own tessellation)
  - a FEATURE-BASED / ORGANIC-SCULPTED / UNCERTAIN shape screen, run before
    anything else. This whole workflow assumes the part decomposes into
    primitives -- flat faces, bores, fillets of constant radius, circular or
    rectangular cross-sections. A sculpted mesh (a character model, anything
    with continuously varying freeform curvature) has no such decomposition
    to recover, and Z-slicing it just produces plausible-looking noise. The
    screen catches that up front instead of after a wasted reconstruction
    attempt -- see _classify() below for the two signals it combines.
  - every distinct Z with a vertex count, so nothing at a real feature
    boundary goes unsampled
  - with --z: every unique (x,y) at that height, radius from --center
    (default the mesh's own XY centroid), sorted by angle, WITH A GAP
    REPORT -- radius values are clustered and printed as separate bands,
    because two unrelated loops (an outer profile, an inner bore's rim)
    can share one Z and look like one confusing ring if you don't
    separate them before trying to read the shape off the numbers.
"""

import argparse
import sys

import numpy as np


def _load(path):
    import trimesh
    m = trimesh.load(path)
    if isinstance(m, trimesh.Scene):
        m = trimesh.util.concatenate(m.dump())
    return m


def _dihedral_concentration_ratio(mesh, bin_deg=5.0, top_n=4):
    """Fraction of adjacent-face dihedral angles that fall into the top few
    histogram bins. A feature-based part's angles cluster at a handful of
    discrete values -- ~0 deg (coplanar face-diagonals), ~90 deg (a cube
    edge), or one repeated value (a constant-radius fillet) -- regardless of
    which values those are. A sculpted/organic mesh bends continuously, so
    its angles spread thinly across many bins with no dominant few. (A first
    version only checked for a spike near 0 deg and misclassified a plain
    box, whose edges are mostly 90 deg, not 0 -- concentration, not
    flatness, is the actual signal.)"""
    try:
        angles = np.degrees(mesh.face_adjacency_angles)
    except Exception:
        return None
    if len(angles) == 0:
        return None
    bins = np.arange(0, 180 + bin_deg, bin_deg)
    counts, _ = np.histogram(angles, bins=bins)
    top = np.sort(counts)[-top_n:]
    return float(top.sum() / counts.sum())


def _slice_circle_fit_ratio(mesh, tol=0.01, good_resid=0.02):
    """Fraction of distinct-Z rings (with enough points to judge) that fit a
    circle tightly. Feature-based cross-sections are circles or a handful of
    straight/arc segments -- both give a small radius std relative to the
    mean radius. A slice through an organic blob fits neither well.

    Fit against the 2D convex hull of each slice, not every raw vertex: a
    filled circular cap (fan-triangulated from a centre vertex) puts a point
    at r=0 alongside the r=R rim, which blows up the std of the *unfiltered*
    set and wrongly reads a perfect circle as a bad fit. The hull is exactly
    the outer loop the reverse-engineering workflow cares about anyway."""
    try:
        from scipy.spatial import ConvexHull
    except Exception:
        ConvexHull = None
    v = mesh.vertices
    zs = np.unique(np.round(v[:, 2] / tol) * tol)
    judged = good = 0
    for z in zs:
        mask = np.abs(v[:, 2] - z) < tol
        pts = np.unique(np.round(v[mask][:, :2], 5), axis=0)
        if len(pts) < 8:
            continue
        if ConvexHull is not None:
            try:
                pts = pts[ConvexHull(pts).vertices]
            except Exception:
                pass  # degenerate (collinear) slice -- fit whatever we have
        cx, cy = pts.mean(axis=0)
        radii = np.sqrt((pts[:, 0] - cx) ** 2 + (pts[:, 1] - cy) ** 2)
        r_mean = radii.mean()
        if r_mean < 1e-6:
            continue
        judged += 1
        if radii.std() / r_mean < good_resid:
            good += 1
    return None if judged == 0 else good / judged


def _classify(mesh):
    """Cheap organic-vs-feature-based screen, run before any reconstruction
    work. Neither signal alone is reliable (a part with no fillets can be
    all-flat with few adjacency angles to sample; a slice grid can land
    between features) so combine both and report UNCERTAIN rather than
    guess when they disagree."""
    conc = _dihedral_concentration_ratio(mesh)
    circ = _slice_circle_fit_ratio(mesh)
    # circ is None on genuinely feature-based parts with no circular
    # cross-section at all (a plain box) -- that must not count as an
    # organic signal, only as "this check doesn't apply."
    feature_signals = sum(s is not None and s > 0.5 for s in (conc, circ))
    organic_signals = sum(s is not None and s < 0.25 for s in (conc, circ))
    if feature_signals >= 1 and organic_signals == 0:
        verdict = "FEATURE-BASED"
    elif organic_signals >= 1 and feature_signals == 0:
        verdict = "ORGANIC / SCULPTED"
    else:
        verdict = "UNCERTAIN"
    return verdict, conc, circ


def _radius_bands(radii, gap=0.05):
    """Cluster sorted radius values into bands separated by >= gap mm --
    the cheap signal that two concentric loops, not one, share this Z."""
    order = np.argsort(radii)
    bands = [[radii[order[0]]]]
    for r in radii[order[1:]]:
        if r - bands[-1][-1] > gap:
            bands.append([r])
        else:
            bands[-1].append(r)
    return [(min(b), max(b), len(b)) for b in bands]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stl", help="path to the STL to inspect")
    ap.add_argument("--z", type=float, default=None,
                    help="detail every vertex at this Z (mm), within --tol")
    ap.add_argument("--tol", type=float, default=0.01,
                    help="Z / point matching tolerance, mm (default 0.01)")
    ap.add_argument("--center", type=float, nargs=2, default=None, metavar=("X", "Y"),
                    help="centre for radius measurement (default: mesh XY centroid)")
    args = ap.parse_args()

    m = _load(args.stl)
    v = m.vertices

    print(f"[{args.stl}]")
    print(f"  volume       : {m.volume:.4f} mm^3   <- compare a reconstruction's")
    print(f"                                          KERNEL-EXACT volume against")
    print(f"                                          THIS, not its own tessellation")
    print(f"  watertight   : {m.is_watertight}")
    print(f"  bbox         : {m.bounds[0]} .. {m.bounds[1]}")

    verdict, conc, circ = _classify(m)
    conc_s = "n/a" if conc is None else f"{conc:.2f}"
    circ_s = "n/a" if circ is None else f"{circ:.2f}"
    print(f"  shape screen : {verdict}   (angle-concentration {conc_s}, circle-fit ratio {circ_s})")
    if verdict == "ORGANIC / SCULPTED":
        print("                 This mesh does not resolve into flat faces, fillets, or")
        print("                 circular/rectangular cross-sections -- Z-slicing will not")
        print("                 recover a feature tree from it. The reverse-engineering")
        print("                 workflow in references/stl-reverse-engineering.md is built")
        print("                 for mechanical parts, not sculpted/organic shapes; a mesh")
        print("                 or sculpting tool is a better fit for editing this one.")
    elif verdict == "UNCERTAIN":
        print("                 Mixed signal -- eyeball a --z slice or two before trusting")
        print("                 the radius bands below as real features.")

    if args.z is None:
        zs = np.unique(np.round(v[:, 2] / args.tol) * args.tol)
        print(f"  distinct Z   : {len(zs)} values (tol {args.tol} mm)")
        for z in zs:
            n = int(np.sum(np.abs(v[:, 2] - z) < args.tol))
            print(f"    z={z:10.4f}   {n:5d} vertices")
        print()
        print("  Re-run with --z <value> on any height that looks like it might")
        print("  carry more than one feature (unexpected vertex count, a height")
        print("  that isn't a multiple of an obvious pattern, etc).")
        return

    mask = np.abs(v[:, 2] - args.z) < args.tol
    pts = v[mask][:, :2]
    if len(pts) == 0:
        sys.exit(f"no vertices within {args.tol} mm of z={args.z}")
    uniq = np.unique(np.round(pts, 5), axis=0)
    cx, cy = args.center if args.center else uniq.mean(axis=0)
    radii = np.sqrt((uniq[:, 0] - cx) ** 2 + (uniq[:, 1] - cy) ** 2)

    print(f"\n  z={args.z}: {len(uniq)} unique points, centre ({cx:.4f}, {cy:.4f})")
    bands = _radius_bands(radii)
    print(f"  {len(bands)} radius band(s) -- each is very likely a SEPARATE loop/feature:")
    for lo, hi, n in bands:
        spread = "" if hi - lo < 1e-4 else f" (spread {hi - lo:.4f})"
        shape = "circle" if hi - lo < 1e-3 else "faceted/irregular"
        print(f"    r = {lo:.4f} .. {hi:.4f}{spread}   {n:4d} points   -> looks like a {shape} loop")
    if len(bands) > 1:
        print("\n  MULTIPLE BANDS AT ONE Z: do not read this as one shape. Separate")
        print("  the points by which band they fall in (filter on radius) before")
        print("  trying to interpret either loop's profile.")


if __name__ == "__main__":
    main()
