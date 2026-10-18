#!/usr/bin/env python3
"""sense.py -- dimension sensing: nudge each parameter, rebuild, see what moved.

Flags parameters that duplicate each other (redundant), do nothing (no_effect),
and circular features pinned by a hard-coded number (hard_coded).

    python scripts/sense.py PART.py [PARAMS.json]     # one summary line
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import brep as B  # noqa: E402
from partmodel import build_part, effective_params, load_model  # noqa: E402

NO_EFFECT_TOL = 1e-6
COS_REDUNDANT = 0.999
SAME_TOL = 1e-6
ANCHOR_TOL = 0.05


def _signature(part):
    bb = part.bounding_box()
    circles = []
    for e in B.circular_edges(part):
        try:
            c = e.arc_center
        except Exception:
            c = e.center()
        circles.append((float(e.radius), (float(c.X), float(c.Y), float(c.Z))))
    circles.sort(key=lambda t: (t[1], t[0]))
    return {"vol": float(part.volume), "area": float(part.area),
            "bbox": [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z],
            "circles": circles}


def _dist(a, b):
    return math.dist(a[1], b[1]) + abs(a[0] - b[0])


def _match(base, new):
    """For each base circle, the nearest circle of `new` (or None)."""
    return [min(new, key=lambda c: _dist(b, c)) if new else None for b in base]


def _scale(sig):
    bb = sig["bbox"]
    return max(math.dist(bb[:3], bb[3:]), 1e-9)


def _delta(base, new):
    """Change vector (relative to part size) and per-circle moved flags."""
    s = _scale(base)
    vec = [(new["vol"] - base["vol"]) / max(abs(base["vol"]), 1e-9),
           (new["area"] - base["area"]) / max(abs(base["area"]), 1e-9)]
    vec += [(a - b) / s for a, b in zip(new["bbox"], base["bbox"])]
    moved = []
    for b, n in zip(base["circles"], _match(base["circles"], new["circles"])):
        if n is None:
            vec += [1.0, 1.0, 1.0, 1.0]
            moved.append(True)
            continue
        vec += [(n[0] - b[0]) / s] + [(x - y) / s for x, y in zip(n[1], b[1])]
        moved.append(_dist(b, n) > SAME_TOL * max(s, 1.0))
    if len(new["circles"]) != len(base["circles"]):
        vec.append(1.0)
    return vec, moved


def _cos(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _numeric(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _anchored(circle, sig):
    """Centre sits on the part's bbox centre in x and y."""
    bb = sig["bbox"]
    cx, cy = (bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0
    return abs(circle[1][0] - cx) <= ANCHOR_TOL and abs(circle[1][1] - cy) <= ANCHOR_TOL


def sense(model, P, rel_step=0.02, notes=None):
    """Flags for `model` at `P`. Skipped nudges are described in `notes` (a list)."""
    notes = notes if notes is not None else []
    base = _signature(build_part(model, dict(P)))
    flags, vecs = [], {}
    n_circ = len(base["circles"])
    circle_moved = [False] * n_circ
    circle_anchored = [_anchored(c, base) for c in base["circles"]]
    bbox_changed = False
    for name, v in P.items():
        if not _numeric(v):
            continue
        step = max(abs(v) * rel_step, 0.05)
        built = False
        for sign in (1, -1):
            Q = dict(P)
            Q[name] = v + sign * step
            try:
                sig = _signature(build_part(model, Q))
            except Exception as e:
                notes.append(f"{name}: nudge {'+' if sign > 0 else '-'} skipped, "
                             f"build failed ({type(e).__name__})")
                continue
            built = True
            vec, moved = _delta(base, sig)
            if max(abs(x) for x in vec) < NO_EFFECT_TOL:
                continue
            circle_moved = [a or b for a, b in zip(circle_moved, moved)]
            for i, (b, n) in enumerate(zip(base["circles"],
                                           _match(base["circles"], sig["circles"]))):
                if n is None or not _anchored(n, sig):
                    circle_anchored[i] = False
            if any(abs(x) > NO_EFFECT_TOL for x in vec[2:8]):
                bbox_changed = True
            vecs[name] = vec
            break
        if not built:
            continue  # both nudges failed: nothing to say about this parameter
        if name not in vecs:
            flags.append({"kind": "no_effect", "params": [name],
                          "detail": f"{name}: changing it does not change the part"})
    names = list(vecs)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if len(vecs[a]) == len(vecs[b]) and _cos(vecs[a], vecs[b]) >= COS_REDUNDANT:
                flags.append({"kind": "redundant", "params": [a, b],
                              "detail": f"{a} and {b} change the part the same way"})
    if bbox_changed:
        seen = set()
        for (r, c), moved, anch in zip(base["circles"], circle_moved, circle_anchored):
            key = (round(r, 4), round(c[0], 4), round(c[1], 4))
            if moved or anch or key in seen:
                continue
            seen.add(key)
            flags.append({"kind": "hard_coded", "params": [],
                          "detail": f"hard-coded: Ø{2 * r:.1f} hole at "
                                    f"({c[0]:.4g},{c[1]:.4g})"})
    return flags


def summarize(part_name, flags):
    if not flags:
        return f"sense {part_name}: clean"
    groups = {}
    for f in flags:
        label = {"redundant": "redundant", "no_effect": "no effect",
                 "hard_coded": "hard-coded"}[f["kind"]]
        if f["kind"] == "hard_coded":
            text = f["detail"].split(": ", 1)[1]
        else:
            text = "~".join(f["params"])
        groups.setdefault(label, []).append(text)
    inner = "; ".join(f"{k}: {', '.join(v)}" for k, v in groups.items())
    n = len(flags)
    return f"sense {part_name}: {n} flag{'' if n == 1 else 's'} ({inner})"


def main(argv=None):
    from pathlib import Path
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: sense.py PART.py [PARAMS.json]", file=sys.stderr)
        return 2
    path = Path(argv[0])
    model = load_model(path)
    P = effective_params(model, argv[1] if len(argv) > 1 else None)
    print(summarize(path.stem, sense(model, P)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
