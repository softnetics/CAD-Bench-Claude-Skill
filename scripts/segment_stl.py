#!/usr/bin/env python3
"""
segment_stl.py -- split a multi-body STL into its disjoint components and
describe each one structurally, so a human can decide what to drop before
anything gets deleted.

Deliberately does NOT try to guess semantic names ("visor", "leg", "arm").
That was the first draft of this idea and it overfits immediately: the next
model someone points this at won't be a humanoid with exactly four
recognizable parts, and a script that only knows "biggest = body, symmetric
pair = legs" is worthless on a mechanical assembly, an animal, a vehicle, or
a humanoid with a different part count. What generalizes is describing HOW
each component relates to the whole -- its size rank, whether it has a
mirror twin, whether it touches the ground, whether it's a thin shell or a
solid lump, how far off-center it sits -- and letting a person map that onto
names for the model actually in front of them.

    python scripts/segment_stl.py crewmate.stl
    python scripts/segment_stl.py crewmate.stl --export-parts out/
    python scripts/segment_stl.py crewmate.stl --delete 2 --out result.stl

If the file is a single connected body, there is nothing to segment -- this
script says so and stops. That is not a bug to work around; a fused mesh
needs real segmentation (surface curvature / boundary detection) or manual
part-picking, which is a different, much harder tool than this one. See
inspect_stl.py's FEATURE-BASED / ORGANIC-SCULPTED screen for that case.
"""

import argparse
import os
import sys

import numpy as np


def _load(path):
    import trimesh
    m = trimesh.load(path)
    if isinstance(m, trimesh.Scene):
        m = trimesh.util.concatenate(m.dump())
    return m


def _mirror_partner(components, i, j, overall_center, tol_frac=0.03):
    """Is component j a mirror image of component i across some axis-
    aligned plane through the ASSEMBLY's center? Checked on all three
    candidate planes (X, Y, Z) rather than assuming which axis a model's
    bilateral symmetry runs along -- a printable part can be symmetric
    front-to-back just as easily as left-to-right.

    Volume/extent proximity alone is a weak, fakeable signal (two
    same-sized but differently-shaped lumps would pass it); this also
    reflects component i's actual points across the candidate plane and
    checks they land close to component j's actual surface via a KD-tree
    nearest-neighbour distance, which a real mirror pair satisfies and a
    coincidentally-similar-sized-but-different part does not.
    """
    from scipy.spatial import cKDTree

    a, b = components[i], components[j]
    if a.volume <= 0 or b.volume <= 0:
        return None
    if abs(a.volume - b.volume) / max(a.volume, b.volume) > 0.10:
        return None

    scale = np.linalg.norm(a.extents)
    tree_b = cKDTree(b.vertices)
    best_axis, best_err = None, None
    for axis in range(3):
        mirrored = a.vertices.copy()
        mirrored[:, axis] = 2 * overall_center[axis] - mirrored[:, axis]
        dist, _ = tree_b.query(mirrored, k=1)
        err = float(np.mean(dist)) / scale if scale > 0 else float(np.mean(dist))
        if best_err is None or err < best_err:
            best_axis, best_err = axis, err
    if best_err is not None and best_err < tol_frac:
        return "XYZ"[best_axis], best_err
    return None


def _shell_factor(mesh):
    """area / volume^(2/3), a dimensionless shape number: a sphere sits
    near its minimum (~4.84); thin shells, flat plates, and anything with
    a lot of surface relative to its bulk score much higher. Generic --
    no assumption about what the thin part IS, just that it is thin."""
    if mesh.volume <= 0:
        return None
    return float(mesh.area / mesh.volume ** (2.0 / 3.0))


def describe(mesh):
    """Split into connected components and compute structural facts about
    each one relative to the whole assembly. Returns the component list and
    a list of fact-dicts, sorted by volume descending."""
    parts = mesh.split(only_watertight=False)
    if len(parts) <= 1:
        return parts, None

    overall_min = mesh.bounds[0]
    overall_extent = mesh.bounds[1] - mesh.bounds[0]
    overall_center = mesh.centroid
    overall_diag = np.linalg.norm(overall_extent)
    ground_tol = 0.02 * overall_extent[2] if overall_extent[2] > 0 else 1e-6

    order = np.argsort([-p.volume for p in parts])
    parts = [parts[i] for i in order]

    facts = []
    for p in parts:
        z_frac = (p.bounds[0][2] - overall_min[2]) / overall_extent[2] if overall_extent[2] > 0 else 0.0
        off_center = np.linalg.norm(p.centroid - overall_center) / overall_diag if overall_diag > 0 else 0.0
        facts.append({
            "volume": p.volume,
            "bbox_extents": p.extents,
            "centroid": p.centroid,
            "shell_factor": _shell_factor(p),
            "touches_ground": bool(p.bounds[0][2] - overall_min[2] <= ground_tol),
            "off_center_frac": off_center,
            "watertight": p.is_watertight,
        })

    # Symmetric-pair detection: generic over all C(n,2) pairs, not assumed.
    pair_of = [None] * len(parts)
    for i in range(len(parts)):
        if pair_of[i] is not None:
            continue
        for j in range(i + 1, len(parts)):
            if pair_of[j] is not None:
                continue
            hit = _mirror_partner(parts, i, j, overall_center)
            if hit:
                axis, err = hit
                pair_of[i] = (j, axis, err)
                pair_of[j] = (i, axis, err)
                break
    for i, pair in enumerate(pair_of):
        facts[i]["mirror_of"] = pair

    return parts, facts


def _print_report(parts, facts, path):
    print(f"[{path}]")
    if facts is None:
        print(f"  1 connected component -- nothing to segment.")
        print(f"  This is a single fused body. Splitting/deleting a named part needs")
        print(f"  real surface segmentation or manual selection, not this script.")
        print(f"  Run inspect_stl.py on it instead to check whether it's even a")
        print(f"  feature-based shape worth reconstructing at all.")
        return

    print(f"  {len(parts)} disjoint components (by connectivity, not by name):\n")
    for idx, (p, f) in enumerate(zip(parts, facts)):
        tags = []
        if idx == 0:
            tags.append("LARGEST")
        if f["touches_ground"]:
            tags.append("GROUND-CONTACT")
        if f["shell_factor"] and f["shell_factor"] > 8.0:
            tags.append("THIN-SHELL")
        if f["off_center_frac"] > 0.3:
            tags.append("PERIPHERAL")
        if f["mirror_of"]:
            j, axis, err = f["mirror_of"]
            tags.append(f"MIRROR-PAIR with #{j} (axis {axis}, match {err:.3f})")
        if not f["watertight"]:
            tags.append("NOT WATERTIGHT")

        sf = f"{f['shell_factor']:.2f}" if f['shell_factor'] else "n/a"
        print(f"  #{idx}  volume={f['volume']:9.2f}mm^3  "
              f"bbox={np.round(f['bbox_extents'], 1)}  shell_factor={sf}")
        if tags:
            print(f"        {', '.join(tags)}")
    print()
    print("  These are structural facts, not identities -- map them onto real part")
    print("  names yourself (open each exported piece, or eyeball the tags above)")
    print("  before deleting one. A wrong guess here has no undo.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stl", help="path to the STL to segment")
    ap.add_argument("--export-parts", metavar="DIR",
                    help="write each component as its own numbered STL for visual inspection")
    ap.add_argument("--delete", type=int, metavar="N",
                    help="component index to drop (see the report for indices)")
    ap.add_argument("--out", metavar="FILE",
                    help="output STL path when using --delete")
    args = ap.parse_args()

    m = _load(args.stl)
    parts, facts = describe(m)
    _print_report(parts, facts, args.stl)

    if args.export_parts:
        if facts is None:
            sys.exit("nothing to export -- single connected component")
        os.makedirs(args.export_parts, exist_ok=True)
        for idx, p in enumerate(parts):
            out = os.path.join(args.export_parts, f"part_{idx}.stl")
            p.export(out)
        print(f"\n  wrote {len(parts)} part files to {args.export_parts}/")

    if args.delete is not None:
        if facts is None:
            sys.exit("nothing to delete -- single connected component")
        if not (0 <= args.delete < len(parts)):
            sys.exit(f"--delete {args.delete} out of range (0..{len(parts) - 1})")
        if not args.out:
            sys.exit("--delete requires --out <file.stl>")
        import trimesh
        kept = [p for i, p in enumerate(parts) if i != args.delete]
        result = trimesh.util.concatenate(kept)
        result.export(args.out)
        print(f"\n  dropped #{args.delete}, wrote {len(kept)} remaining components to {args.out}")
        print(f"  volume: {result.volume:.2f}mm^3   watertight: {result.is_watertight}")


if __name__ == "__main__":
    main()
