"""asm_export.py -- run an assembly: solve, export, print one line.

    <exports>/<name>/report.txt   placement report (the detail behind the line)
    <exports>/<name>/<name>.png   picture with connector axis markers
    <exports>/<name>/<name>.step  the whole assembly, one labelled solid per part
    <exports>/<name>/<name>.xml   MuJoCo model (+ meshes/)

<exports> is cad/exports/ for an assembly in cad/assemblies/, otherwise
exports/ beside the assembly file.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

import brep as B
from assembly import MOTION_NAMES, AssemblyError, Solved  # noqa: F401  (Solved re-exported)

DENSITY = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "aluminium": 2.70,
           "aluminum": 2.70, "steel": 7.85}       # g/cm^3


def exports_dir(asm):
    here = asm.path.resolve().parent
    if here.name == "assemblies" and here.parent.name == "cad":
        return here.parent / "exports" / asm.name
    return here / "exports" / asm.name


def mass_properties(inst):
    """(mass kg, com mm in part frame, inertia 3x3 kg·mm² about com, source)."""
    rho = DENSITY.get(inst.material)
    if rho is None:
        if inst.mass is None:
            raise AssemblyError(f"{inst.name}: unknown material {inst.material!r} "
                                f"(have {', '.join(DENSITY)}); or give mass=")
        rho = 1.0                     # any density: mass= rescales mass and inertia
    kg_per_mm3 = rho * 1e-6
    shape = inst.shape
    vol = shape.volume if shape.solids() else 0.0
    if vol > 1e-9:
        c = shape.center(B.CenterOf.MASS)
        com = np.array([c.X, c.Y, c.Z])
        inertia = np.array(shape.matrix_of_inertia) * kg_per_mm3
        source = "exact solid"
    else:                                  # imported mesh: no exact solid
        import trimesh
        verts, tris = shape.tessellate(0.05, 0.2)
        mesh = trimesh.Trimesh([(v.X, v.Y, v.Z) for v in verts], tris)
        vol = abs(mesh.volume)
        com = np.array(mesh.center_mass)
        inertia = np.array(mesh.moment_inertia) * kg_per_mm3
        source = "mesh (no exact solid)"
    mass = vol * kg_per_mm3
    if inst.mass is not None:
        scale = inst.mass / mass if mass > 0 else 0.0
        mass, inertia = inst.mass, inertia * scale
        source += f", mass given ({inst.mass:g} kg)"
    return mass, com, inertia, source


def _fmt(v):
    return " ".join(f"{x:8.3f}" for x in v)


def write_report(solved, path, masses):
    asm = solved.asm
    lines = [f"assembly {asm.name}  (base: {asm.base}, {asm.base_joint} to the world)", ""]
    parent_of = {e.child: e for e in solved.edges}
    for name, inst in solved.instances.items():
        T = solved.placement(name)
        lines.append(f"[{name}]  part {inst.part}  ({inst.path.name})")
        lines.append(f"  position   : {_fmt(T[:3, 3])} mm")
        lines.append(f"  x / y / z  : {_fmt(T[:3, 0])} | {_fmt(T[:3, 1])} | {_fmt(T[:3, 2])}")
        e = parent_of.get(name)
        if name == asm.base:
            lines.append("  placed by  : base")
        elif e:
            j = e.joint
            extra = "".join([" flip" if j.flip else "", f" angle {j.angle:g}" if j.angle else "",
                             f" gap {j.gap:g}" if j.gap else ""])
            moves = ", ".join(MOTION_NAMES[m] for m in sorted(_motions(j.type))) or "none"
            lines.append(f"  placed by  : {j.type} {j.name()}{extra}; moves: {moves}")
            if j.motor:
                sp = f", speed {j.motor.speed:g}" if j.motor.speed is not None else ""
                lines.append(f"  motor      : torque {j.motor.torque:g}{sp}")
        else:
            lines.append("  placed by  : nothing (under-defined, left where built)")
        P = ", ".join(f"{k}={v:g}" if isinstance(v, (int, float)) else f"{k}={v}"
                      for k, v in inst.P.items())
        lines.append(f"  params     : {P or '(none)'}")
        m, com, I, src = masses[name]
        lines.append(f"  mass       : {m * 1000:.2f} g  ({inst.material}, {src})")
        lines.append(f"  centre     : {_fmt(T[:3, :3] @ com + T[:3, 3])} mm (world)")
        for cn, f in inst.connectors.items():
            W = T @ f.matrix()
            lines.append(f"  {name}.{cn:<12}: at {_fmt(W[:3, 3])}  z {_fmt(W[:3, 2])}  ({f.kind})")
        lines.append("")
    if solved.rule_results or solved.rules_ignored:
        lines.append("rules")
        for r in solved.rule_results:
            lines.append(f"  {'ok  ' if r.ok else 'FAIL'} {r.describe()}  [{r.rule.source}]")
        if solved.rules_ignored:
            lines.append(f"  {solved.rules_ignored} unconfirmed rule(s) ignored")
        lines.append("")
    lines.append("warnings")
    lines += [f"  {w}" for w in solved.warnings] or ["  none"]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _motions(t):
    from assembly import JOINT_MOTIONS
    return JOINT_MOTIONS[t]


def write_step(solved, path):
    shapes = []
    for name, inst in solved.instances.items():
        s = solved.placed_shape(name)
        s.label = name
        s.color = B.Color(*inst.color)
        shapes.append(s)
    B.export_step(B.Compound(children=shapes, label=solved.asm.name), str(path))


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def summary(solved, out):
    asm = solved.asm
    bits = [_plural(len(solved.instances), "part"), _plural(len(asm.joints), "joint")]
    if solved.rule_results:
        ok = sum(r.ok for r in solved.rule_results)
        bits.append(f"{ok}/{len(solved.rule_results)} rules ok")
    if solved.rules_ignored:
        bits.append(f"{solved.rules_ignored} unconfirmed ignored")
    if solved.warnings:
        bits.append(_plural(len(solved.warnings), "warning"))
    try:
        where = os.path.relpath(out)
    except ValueError:                      # other drive on Windows
        where = str(out)
    if where.startswith(".."):
        where = str(out)
    return f"{asm.name}: {', '.join(bits)} -> {where}"


def run(asm, out_dir=None, quiet=False):
    import asm_render
    import mjcf

    solved = asm.solve()
    out = Path(out_dir) if out_dir else exports_dir(asm)
    out.mkdir(parents=True, exist_ok=True)
    masses = {n: mass_properties(i) for n, i in solved.instances.items()}
    write_report(solved, out / "report.txt", masses)
    write_step(solved, out / f"{asm.name}.step")
    asm_render.render(solved, out / f"{asm.name}.png")
    mjcf.write(solved, out / f"{asm.name}.xml", masses)
    if not quiet:
        print(summary(solved, out))
        for w in solved.warnings:
            print(f"  warn: {w}")
    return solved
