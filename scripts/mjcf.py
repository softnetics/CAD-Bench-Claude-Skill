"""mjcf.py -- the assembly as a MuJoCo model (MJCF), gated by loading it.

Bodies follow the joint tree out from the base; each body's frame is its
part's own build frame. Masses, centres of mass and inertia tensors come
from the exact CAD solid (asm_export.mass_properties). Units: metres, kg,
radians. A model that does not load in `mujoco` is a broken export and
raises -- it is never left looking finished.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

import brep as B

MM = 1e-3
STEPS = 200


class MJCFError(RuntimeError):
    pass


def _quat(R):
    """Rotation matrix -> (w, x, y, z)."""
    t = np.trace(R)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = [0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s]
    else:
        i = int(np.argmax(np.diag(R)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = math.sqrt(1.0 + R[i, i] - R[j, j] - R[k, k]) * 2
        q = [0.0] * 4
        q[0] = (R[k, j] - R[j, k]) / s
        q[1 + i] = 0.25 * s
        q[1 + j] = (R[j, i] + R[i, j]) / s
        q[1 + k] = (R[k, i] + R[i, k]) / s
    q = np.array(q)
    return q / np.linalg.norm(q)


def _s(v, fmt="{:.6g}"):
    return " ".join(fmt.format(0.0 if abs(x) < 1e-12 else x) for x in v)


def _lowest_z(solved):
    return min(solved.placed_shape(n).bounding_box().min.Z for n in solved.instances)


def write(solved, path, masses, floor=True):
    path = Path(path)
    asm = solved.asm
    meshdir = path.parent / "meshes"
    meshdir.mkdir(parents=True, exist_ok=True)

    root = ET.Element("mujoco", model=asm.name)
    ET.SubElement(root, "compiler", angle="radian", meshdir="meshes", autolimits="true")
    ET.SubElement(root, "option", timestep="0.002")
    asset = ET.SubElement(root, "asset")
    world = ET.SubElement(root, "worldbody")
    if floor:
        ET.SubElement(world, "light", pos="0 0 2", dir="0 0 -1")
        ET.SubElement(world, "geom", name="floor", type="plane", size="2 2 0.05",
                      rgba="0.85 0.85 0.85 1")

    for name, inst in solved.instances.items():
        f = meshdir / f"{name}.stl"
        B.export_stl(inst.shape, str(f), tolerance=0.05, angular_tolerance=0.2)
        ET.SubElement(asset, "mesh", name=name, file=f.name, scale="0.001 0.001 0.001")

    children = {}
    for e in solved.edges:
        children.setdefault(e.parent, []).append(e)

    actuators, custom = [], []

    def body(name, parent_T, edge, xml_parent, extra_pos=np.zeros(3)):
        T = solved.placement(name)
        rel = np.linalg.inv(parent_T) @ T
        el = ET.SubElement(xml_parent, "body", name=name,
                           pos=_s(rel[:3, 3] * MM + extra_pos), quat=_s(_quat(rel[:3, :3])))
        if edge is None:
            if asm.base_joint == "free":
                ET.SubElement(el, "freejoint", name=f"{name}_free")
        else:
            _joints(el, edge, T)
        mass, com, I, _ = masses[name]
        if mass <= 0:
            raise MJCFError(f"{name}: zero mass")
        I = I * MM * MM                                   # kg*mm^2 -> kg*m^2
        ET.SubElement(el, "inertial", pos=_s(com * MM), mass=f"{mass:.6g}",
                      fullinertia=_s([I[0, 0], I[1, 1], I[2, 2], I[0, 1], I[0, 2], I[1, 2]],
                                     "{:.6e}"))
        r, g, b = solved.instances[name].color
        ET.SubElement(el, "geom", name=f"{name}_geom", type="mesh", mesh=name,
                      rgba=f"{r:.3g} {g:.3g} {b:.3g} 1")
        for e in children.get(name, []):
            body(e.child, T, e, el)

    def _joints(el, edge, T_child):
        j = edge.joint
        L = np.linalg.inv(T_child) @ solved.joint_world(j)
        # A positive joint value always moves b relative to a about (along) a's
        # z. MuJoCo moves the CHILD relative to the parent, so when a is the
        # child (b was placed first) the axis is negated; the limits and the
        # motor's sign then keep their meaning unchanged.
        sense = -1.0 if edge.child == j.a[0] else 1.0
        pos, ax = _s(L[:3, 3] * MM), _s(sense * L[:3, 2])
        jname = j.name()
        kinds = {"revolute": ["hinge"], "wheel": ["hinge"], "slider": ["slide"],
                 "cylindrical": ["hinge", "slide"], "fixed": []}[j.type]
        for k in kinds:
            n = jname if len(kinds) == 1 else f"{jname}.{k}"
            attrs = dict(name=n, type=k, pos=pos, axis=ax)
            if j.limits is not None and j.type != "wheel":
                lo, hi = j.limits
                if k == "hinge":
                    lo, hi = math.radians(lo), math.radians(hi)
                else:
                    lo, hi = lo * MM, hi * MM
                attrs.update(limited="true", range=f"{lo:.6g} {hi:.6g}")
            ET.SubElement(el, "joint", **attrs)
            if j.motor is not None and (k == "hinge" or j.type == "slider"):
                t = j.motor.torque
                actuators.append(dict(name=f"{n}.motor", joint=n, gear="1",
                                      ctrlrange=f"{-t:g} {t:g}"))
                if j.motor.speed is not None:
                    custom.append((f"{n}.speed_max", j.motor.speed))

    lift = np.zeros(3)
    if asm.base_joint == "free" and floor:
        lift[2] = -_lowest_z(solved) * MM
    body(asm.base, np.eye(4), None, world, lift)

    if actuators:
        act = ET.SubElement(root, "actuator")
        for a in actuators:
            ET.SubElement(act, "motor", **a)
    if custom:
        cu = ET.SubElement(root, "custom")
        for n, v in custom:
            ET.SubElement(cu, "numeric", name=n, data=f"{v:g}")

    ET.indent(root)
    path.write_text(ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")
    check(path)


def check(path):
    """Load and step the model; raise MJCFError if either fails."""
    try:
        import mujoco
    except ImportError as e:
        raise MJCFError("mujoco is not installed: pip install mujoco") from e
    try:
        m = mujoco.MjModel.from_xml_path(str(path))
    except Exception as e:
        raise MJCFError(f"{Path(path).name} does not load in mujoco: {e}") from e
    d = mujoco.MjData(m)
    for _ in range(STEPS):
        mujoco.mj_step(m, d)
    if not np.isfinite(d.qpos).all():
        raise MJCFError(f"{Path(path).name}: simulation blew up within {STEPS} steps")
