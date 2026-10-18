#!/usr/bin/env python3
"""assembly.py -- join parts at named connectors, check, export.

A part file declares connectors next to `build()`, computed from its own
parameters so a resize carries through:

    def connectors(P):
        return {"top": A.frame((0, 0, P["h"]), z=(0, 0, 1))}

An assembly file adds parts and joins connectors; nobody types a world
coordinate:

    asm = A.Assembly("bot", base="chassis", base_joint="free")
    asm.add("chassis", part="chassis_plate")
    asm.add("motor_l", part="gear_motor", mass=0.095)
    asm.join("chassis.motor_l", "motor_l.mount", "fixed")
    asm.run()

Convention: a connector's z points OUT of its part. A join puts the two z
axes opposed (face to face) with x aligned; `flip=True` aligns z instead,
`angle=` turns about z (degrees), `gap=` separates along z (mm).

Checks warn and never block: under-defined parts (naming the free motions),
loops that disagree, overlapping parts, connectors that stay put while their
part resizes (a hard-coded number), broken confirmed rules.

    python scripts/assembly.py ASSEMBLY.py      # same as running the file
"""
from __future__ import annotations

import math
import os
import runpy
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("BREP_QUIET", "1")

import brep as B  # noqa: E402
from partmodel import effective_params, load_model  # noqa: E402


class AssemblyError(RuntimeError):
    """The assembly file itself is wrong (bad name, missing part)."""


# ------------------------------------------------------------------ frames

def _unit(v, what="vector"):
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise AssemblyError(f"{what} has zero length")
    return v / n


@dataclass
class Frame:
    origin: np.ndarray
    z: np.ndarray
    x: np.ndarray
    kind: str = "frame"          # frame | axis | point

    def matrix(self):
        m = np.eye(4)
        y = np.cross(self.z, self.x)
        m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = self.x, y, self.z, self.origin
        return m

    @property
    def free(self):
        """Rotations (in this frame) a connector of this kind leaves free."""
        return {"frame": set(), "axis": {"rz"}, "point": {"rx", "ry", "rz"}}[self.kind]


def _default_x(z):
    world = np.eye(3)
    pick = world[int(np.argmin(np.abs(world @ z)))]
    return pick


def frame(origin, z=(0, 0, 1), x=None, kind="frame"):
    """A full frame: origin, z out of the part, x fixing the roll."""
    z = _unit(z, "connector z")
    x = _default_x(z) if x is None else np.asarray(x, dtype=float)
    x = x - z * (x @ z)                               # Gram-Schmidt
    x = _unit(x, "connector x (parallel to z?)")
    return Frame(np.asarray(origin, dtype=float), z, x, kind)


def axis(origin, z=(0, 0, 1)):
    """Origin + axis: roll about z is left free."""
    return frame(origin, z, None, "axis")


def point(origin):
    """Origin only: all three rotations are left free."""
    return frame(origin, (0, 0, 1), (1, 0, 0), "point")


def _vec(v):
    return np.array([v.X, v.Y, v.Z], dtype=float)


def on_face(face, x=None):
    """Centre of a face, z along its outward normal."""
    c = face.center()
    return frame(_vec(c), _vec(face.normal_at(c)), x)


def on_edge(edge, z=None):
    """Midpoint of an edge, x along the edge; z given or a perpendicular."""
    o = _vec(edge.position_at(0.5))
    t = _unit(_vec(edge.tangent_at(0.5)))
    if z is None:
        z = np.cross(t, _default_x(t))
    return frame(o, z, t)


def on_circle(edge):
    """Centre of a circular edge, z along its axis (roll free)."""
    try:
        c = edge.arc_center
    except Exception:
        c = edge.center()
    n = edge.normal() if hasattr(edge, "normal") else B.Vector(0, 0, 1)
    return axis(_vec(c), _vec(n))


def _rz(deg):
    a = math.radians(deg)
    m = np.eye(4)
    m[0, 0], m[0, 1], m[1, 0], m[1, 1] = math.cos(a), -math.sin(a), math.sin(a), math.cos(a)
    return m


def _tz(d):
    m = np.eye(4)
    m[2, 3] = d
    return m


_RX180 = np.diag([1.0, -1.0, -1.0, 1.0])


def to_location(m):
    """4x4 matrix -> build123d Location."""
    return B.Location(B.Plane(origin=tuple(m[:3, 3]), x_dir=tuple(m[:3, 0]),
                              z_dir=tuple(m[:3, 2])))


# ------------------------------------------------------------------ model

JOINT_MOTIONS = {
    "fixed": set(),
    "revolute": {"rz"},
    "wheel": {"rz"},
    "slider": {"tz"},
    "cylindrical": {"rz", "tz"},
}
MOTION_NAMES = {"tx": "slide along x", "ty": "slide along y", "tz": "slide along z",
                "rx": "rotation about x", "ry": "rotation about y", "rz": "rotation about z"}
ALL_MOTIONS = ["tx", "ty", "tz", "rx", "ry", "rz"]

PALETTE = [(0.20, 0.20, 0.22), (0.80, 0.25, 0.20), (0.20, 0.45, 0.75),
           (0.95, 0.70, 0.15), (0.30, 0.65, 0.35), (0.55, 0.35, 0.70),
           (0.45, 0.70, 0.75), (0.75, 0.50, 0.35)]

OVERLAP_MM3 = 1.0
LOOP_TOL_MM = 0.01
LOOP_TOL_DEG = 0.01
NUDGE = 0.02
LANDMARK_TOL = 0.01


@dataclass
class Motor:
    """A motor on a joint: torque in N·m (force in N on a slider), speed in rad/s (m/s)."""
    torque: float
    speed: float | None = None


@dataclass
class Instance:
    name: str
    part: str
    path: Path
    model: object
    params: dict
    material: str
    mass: float | None
    color: tuple
    P: dict = field(default_factory=dict)
    shape: object = None
    connectors: dict = field(default_factory=dict)


@dataclass
class Joint:
    a: tuple
    b: tuple
    type: str
    flip: bool
    angle: float
    gap: float
    limits: tuple | None
    motor: Motor | None

    def relative(self, fa, fb):
        """T_a^-1 T_b: where b's part frame sits in a's part frame."""
        m = np.eye(4) if self.flip else _RX180
        return fa.matrix() @ _rz(self.angle) @ _tz(self.gap) @ m @ np.linalg.inv(fb.matrix())

    def name(self):
        return f"{self.a[0]}.{self.a[1]}-{self.b[0]}.{self.b[1]}"


@dataclass
class Edge:
    """A tree edge: `child` placed from `parent` through `joint`."""
    parent: str
    child: str
    joint: Joint


@dataclass
class Solved:
    asm: "Assembly"
    instances: dict
    placements: dict
    edges: list
    warnings: list
    rule_results: list = field(default_factory=list)
    rules_ignored: int = 0

    def placement(self, inst):
        return self.placements[inst]

    def placed_shape(self, inst):
        return self.instances[inst].shape.moved(to_location(self.placements[inst]))

    def connector_world(self, inst, conn):
        return self.placements[inst] @ self.instances[inst].connectors[conn].matrix()

    def joint_world(self, joint):
        """World frame of a joint: a's connector turned by angle, moved by gap."""
        fa = self.instances[joint.a[0]].connectors[joint.a[1]]
        return self.placements[joint.a[0]] @ fa.matrix() @ _rz(joint.angle) @ _tz(joint.gap)


class Assembly:
    def __init__(self, name, base=None, base_joint="fixed", path=None):
        if base_joint not in ("fixed", "free"):
            raise AssemblyError("base_joint must be 'fixed' or 'free'")
        self.name = name
        self.base = base
        self.base_joint = base_joint
        self.path = Path(path) if path else _caller_file()
        self.instances: dict[str, Instance] = {}
        self.joints: list[Joint] = []
        self.allowed: set = set()
        self.rule_specs: list = []     # (text, why, confirmed, source)
        self.rule_kinds: list = []     # (kind, roles)

    # ---------------------------------------------------------- building up
    def part_dirs(self):
        here = self.path.parent
        return [here.parent / "parts", here]

    def _find_part(self, part):
        for d in self.part_dirs():
            f = d / f"{part}.py"
            if f.is_file():
                return f
        raise AssemblyError(f"no part file {part}.py in "
                            + " or ".join(str(d) for d in self.part_dirs()))

    def add(self, name, part, params=None, material="PLA", mass=None, color=None):
        if name in self.instances:
            raise AssemblyError(f"instance {name!r} added twice")
        if "." in name:
            raise AssemblyError(f"instance name {name!r} may not contain '.'")
        path = self._find_part(part)
        model = load_model(path)
        color = color or PALETTE[len(self.instances) % len(PALETTE)]
        self.instances[name] = Instance(name, part, path, model, dict(params or {}),
                                        material, mass, tuple(color))
        if self.base is None:
            self.base = name
        return name

    def join(self, a, b, type="fixed", flip=False, angle=0.0, gap=0.0, limits=None,
             motor=None):
        if type not in JOINT_MOTIONS:
            raise AssemblyError(f"joint type {type!r}: use one of {', '.join(JOINT_MOTIONS)}")
        if motor is not None and type == "fixed":
            raise AssemblyError(f"motor on a fixed joint {a}-{b}")
        self.joints.append(Joint(_split(a), _split(b), type, flip, float(angle),
                                 float(gap), limits, motor))

    def allow_overlap(self, a, b):
        self.allowed.add(frozenset((a, b)))

    def rule(self, text, why="", confirmed=None):
        """One-off rule. Ignored unless confirmed (a date or True)."""
        self.rule_specs.append((text, why, confirmed, f"{self.path.name} (inline)"))

    def use_rules(self, kind, **roles):
        """Bind the confirmed rule file of this kind (project, then worldwide)."""
        self.rule_kinds.append((kind, roles))

    # ---------------------------------------------------------- solving
    def _resolve_params(self):
        for inst in self.instances.values():
            pj = inst.path.with_suffix(".params.json")
            P = effective_params(inst.model, pj)
            for k, v in inst.params.items():
                if k not in inst.model.PARAMS:
                    raise AssemblyError(f"{inst.name}: {inst.part} has no parameter {k!r}")
                P[k] = v
            inst.P = P

    def _apply_rules(self):
        import rules as R
        return R.apply_assembly(self)

    def solve(self):
        if not self.instances:
            raise AssemblyError("assembly has no parts")
        self._resolve_params()
        rule_results, ignored = self._apply_rules()
        for inst in self.instances.values():
            inst.shape = inst.model.build(dict(inst.P))
            fn = getattr(inst.model, "connectors", None)
            inst.connectors = dict(fn(dict(inst.P))) if fn else {}
        for j in self.joints:
            for end in (j.a, j.b):
                self._connector(end)

        warnings = []
        placements, edges = self._place(warnings)
        solved = Solved(self, self.instances, placements, edges, warnings,
                        rule_results, ignored)
        warnings += _underdefined(self, placements, edges)
        warnings += _overlaps(solved)
        warnings += _hard_coded(self)
        warnings += [f"rule broken: {r.describe()}" for r in rule_results if not r.ok]
        return solved

    def _connector(self, end):
        inst, conn = end
        if inst not in self.instances:
            raise AssemblyError(f"no instance {inst!r} (have {', '.join(self.instances)})")
        cs = self.instances[inst].connectors
        if conn not in cs:
            have = ", ".join(cs) or "none"
            raise AssemblyError(f"{inst} ({self.instances[inst].part}) has no connector "
                                f"{conn!r}; it has: {have}")
        return cs[conn]

    def _place(self, warnings):
        if self.base not in self.instances:
            raise AssemblyError(f"base {self.base!r} is not an added part")
        placed = {self.base: np.eye(4)}
        edges, pending = [], list(self.joints)
        progress = True
        while pending and progress:
            progress = False
            for j in list(pending):
                ia, ib = j.a[0], j.b[0]
                rel = j.relative(self._connector(j.a), self._connector(j.b))
                if ia in placed and ib in placed:
                    _check_loop(j, placed[ia] @ rel, placed[ib], warnings)
                elif ia in placed:
                    placed[ib] = placed[ia] @ rel
                    edges.append(Edge(ia, ib, j))
                elif ib in placed:
                    placed[ia] = placed[ib] @ np.linalg.inv(rel)
                    edges.append(Edge(ib, ia, j))
                else:
                    continue
                pending.remove(j)
                progress = True
        for name in self.instances:
            placed.setdefault(name, np.eye(4))   # stays where it was built
        return placed, edges

    # ---------------------------------------------------------- running
    def run(self, out_dir=None, quiet=False):
        import asm_export
        return asm_export.run(self, out_dir=out_dir, quiet=quiet)


def _split(ref):
    if isinstance(ref, tuple):
        return ref
    if ref.count(".") != 1:
        raise AssemblyError(f"connector reference {ref!r}: write it as 'instance.connector'")
    return tuple(ref.split("."))


def _caller_file():
    f = sys._getframe(2)
    return Path(f.f_globals.get("__file__", "assembly.py")).resolve()


# ------------------------------------------------------------------ checks

def _check_loop(j, want, have, warnings):
    dp = np.linalg.norm(want[:3, 3] - have[:3, 3])
    r = want[:3, :3].T @ have[:3, :3]
    da = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(r) - 1) / 2))))
    if dp > LOOP_TOL_MM or da > LOOP_TOL_DEG:
        warnings.append(f"{j.b[0]}: join {j.name()} disagrees with its earlier placement "
                        f"by {dp:.2f} mm / {da:.1f} deg (over-defined loop)")


def _underdefined(asm, placements, edges):
    out = []
    reached = {asm.base} | {e.child for e in edges}
    for name in asm.instances:
        if name not in reached:
            free = ", ".join(MOTION_NAMES[m] for m in ALL_MOTIONS)
            out.append(f"{name}: under-defined, not joined to {asm.base} "
                       f"(6 free motions: {free})")
    for e in edges:
        j = e.joint
        fa = asm.instances[j.a[0]].connectors[j.a[1]]
        fb = asm.instances[j.b[0]].connectors[j.b[1]]
        loose = (fa.free | fb.free) - JOINT_MOTIONS[j.type]
        if loose:
            names = ", ".join(MOTION_NAMES[m] for m in ALL_MOTIONS if m in loose)
            kinds = "/".join(sorted({fa.kind, fb.kind} - {"frame"}))
            out.append(f"{e.child}: under-defined, {names} free at {j.name()} "
                       f"({kinds} connector on a {j.type} joint)")
    return out


def _bbox_overlap(a, b):
    alo, ahi, blo, bhi = _vec(a.min), _vec(a.max), _vec(b.min), _vec(b.max)
    return bool(np.all(alo < bhi) and np.all(blo < ahi))


def _overlaps(solved):
    names = list(solved.instances)
    shapes = {n: solved.placed_shape(n) for n in names}
    boxes = {n: shapes[n].bounding_box() for n in names}
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if frozenset((a, b)) in solved.asm.allowed or not _bbox_overlap(boxes[a], boxes[b]):
                continue
            try:
                common = shapes[a] & shapes[b]
                vol = common.volume if common is not None else 0.0
            except Exception:
                vol = 0.0
            if vol > OVERLAP_MM3:
                out.append(f"{a} and {b} overlap by {vol:.1f} mm^3 "
                           f"(asm.allow_overlap if intended)")
    return out


def _numeric(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _snapshot(model, P):
    shape = model.build(dict(P))
    bb = shape.bounding_box()
    lo, hi = _vec(bb.min), _vec(bb.max)
    fn = getattr(model, "connectors", None)
    cs = dict(fn(dict(P))) if fn else {}
    return lo, hi, {k: f.origin for k, f in cs.items()}


def _landmark(c, lo, hi):
    """Which datum a coordinate sits on: the part origin, bbox min, centre, max."""
    for i, v in enumerate((0.0, lo, (lo + hi) / 2, hi)):
        if abs(c - v) <= LANDMARK_TOL:
            return i
    return None


def _hard_coded(asm):
    out, seen = [], {}
    for inst in asm.instances.values():
        if not getattr(inst.model, "connectors", None):
            continue
        numeric = {k: v for k, v in inst.P.items() if _numeric(v)}
        if not numeric:
            continue                      # imported part: numbers are expected
        key = (str(inst.path), tuple(sorted(inst.P.items())))
        if key not in seen:
            seen[key] = _sense_connectors(inst.model, inst.P, numeric)
        for conn, axes in seen[key].items():
            for k, value in axes:
                out.append(f"{inst.name}.{conn}: {'xyz'[k]} stays at {value:.4g} "
                           f"while the part resizes (hard-coded?)")
    return out


def _sense_connectors(model, P, numeric):
    lo, hi, base = _snapshot(model, P)
    moved = {c: [False] * 3 for c in base}
    marks = {c: [_landmark(base[c][k], lo[k], hi[k]) for k in range(3)] for c in base}
    bbox_changed = [False] * 3
    for name, v in numeric.items():
        step = max(abs(v) * NUDGE, 0.05)
        for sign in (1, -1):
            Q = dict(P)
            Q[name] = v + sign * step
            try:
                nlo, nhi, now = _snapshot(model, Q)
            except Exception:
                continue
            for k in range(3):
                if abs(nlo[k] - lo[k]) > 1e-9 or abs(nhi[k] - hi[k]) > 1e-9:
                    bbox_changed[k] = True
            for c in base:
                if c not in now:
                    continue
                for k in range(3):
                    if abs(now[c][k] - base[c][k]) > 1e-9:
                        moved[c][k] = True
                    if marks[c][k] is not None and \
                            _landmark(now[c][k], nlo[k], nhi[k]) != marks[c][k]:
                        marks[c][k] = None
            break
    flagged = {}
    for c in base:
        bad = [(k, base[c][k]) for k in range(3)
               if bbox_changed[k] and not moved[c][k] and marks[c][k] is None]
        if bad:
            flagged[c] = bad
    return flagged


# ------------------------------------------------------------------ CLI

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: assembly.py ASSEMBLY.py", file=sys.stderr)
        return 2
    try:
        runpy.run_path(argv[0], run_name="__main__")
    except AssemblyError as e:
        print(f"assembly: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
