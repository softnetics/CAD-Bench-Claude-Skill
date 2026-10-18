# cad-bench assemblies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assemblies for cad-bench: connectors on parts, an assembly file that
joins them, warn-only checks, confirmed rules that carry sizes between parts,
and STEP / PNG / report / MuJoCo exports.

**Architecture:** `assembly.py` owns frames, placement (numpy 4×4 frame
matching, converted to `B.Location(B.Plane(...))` to move shapes) and the
checks; `rules.py` parses and evaluates rule files (safe `ast` subset);
`mjcf.py` writes and load-gates the MuJoCo model; `asm_render.py` draws the
PNG. Parts load through the foundation's `partmodel`.

**Tech Stack:** build123d via `brep`, numpy, trimesh, Pillow, mujoco 3.16, pytest.

**Spec:** `docs/superpowers/specs/2026-10-18-cad-bench-assemblies-design.md`

## Global Constraints

- `import brep as B` only; never `import build123d`.
- Do not edit `assets/bench-template.html`, `scripts/new_part.py`,
  `scripts/check_bench.py`, server or git-history code.
- One line on a clean run; one extra line per warning; detail in `report.txt`.
- Warnings never block export; an MJCF that fails to load raises.
- World rules live in git-ignored `<skill>/library/rules/` (`CAD_BENCH_LIBRARY` env overrides, for tests).
- Venv: `C:\Users\gritp\cad-bench-venv\Scripts\python`.

## Review Focus

- Part file with no `connectors()` used only as a base → works, no crash.
- A join naming a connector that doesn't exist → error listing the part's connector names.
- Rule referring to an unknown instance/parameter → error naming it, not a KeyError.
- Exports folder for an assembly under `cad/assemblies/` → `cad/exports/<name>/`, never `cad/assemblies/`.
- Running the same assembly twice → overwrites exports cleanly (meshes folder reused).

---

### Task 1: frames and placement (`scripts/assembly.py`, `tests/test_assembly.py`)

**Produces:** `frame(origin, z=(0,0,1), x=None) -> Frame`, `axis(origin, z)`,
`point(origin)`, `on_face(face)`, `on_edge(edge)`, `on_circle(edge)`;
`Frame.matrix() -> np.ndarray (4,4)`; `Frame.kind in {"frame","axis","point"}`;
`Motor(torque, speed=None)`; `Assembly(name, base=None, base_joint="fixed", path=None)`
with `add(name, part, params=None, material="PLA", mass=None, color=None)`,
`join(a, b, type="fixed", flip=False, angle=0, gap=0, limits=None, motor=None)`,
`allow_overlap(a, b)`, `solve() -> Solved`.

Placement: `T_child = T_parent · F_a · Rz(angle) · Tz(gap) · M · F_b⁻¹`,
`M = Rx(180°)` unless `flip`. `x` default for `axis`: world axis least parallel
to `z`, Gram-Schmidt; `point`: world axes.

- [ ] Tests: box B on box A's top face sits at A's top; resizing A's height moves B; flip/angle/gap; unknown connector raises listing names; part with no `connectors()` is fine as base.
- [ ] Implement, pass, commit.

### Task 2: checks (same files)

- Under-defined: unreachable part → warning naming 6 motions; `axis`/`point` connector on a joint whose intended motions don't cover rz / rx,ry,rz → warning naming them. Intended: fixed ∅, revolute/wheel {rz}, slider {tz}, cylindrical {rz,tz}.
- Loop: second join checked; mismatch > 0.01 mm / 0.01° → warning.
- Overlap: pairwise bbox prefilter then `a.intersect(b).volume > 1.0 mm³`, skip `allow_overlap` pairs.
- Hard-coded connector: per instance with numeric params, nudge each ±2 % (min 0.05); per connector per axis, OK if the coordinate moved under some nudge, or matched the same bbox landmark (min/centre/max, 0.01 mm) in base and every nudge, or the bbox never changed in that axis; else warning `"<inst>.<conn>: x stays at 30 while the part resizes (hard-coded?)"`.

- [ ] Tests for each, including the face-centre anchor not flagged and an imported STEP part (`PARAMS = {}`) skipped.
- [ ] Implement, pass, commit.

### Task 3: rules (`scripts/rules.py`, `tests/test_rules.py`)

**Produces:** `load_rule_file(path) -> RuleFile(kind, purpose, roles, confirmed, rules)`;
`Rule(text, why, source)`; `find_kind(kind, project_dir, world_dir) -> RuleFile | None`
(project wins); `project_rules_dir(asm_path)` (`cad/assemblies/x.py` → `cad/rules`, else `<dir>/rules`);
`world_rules_dir()`; `bind(rule_text, roles: dict) -> str`;
`apply(rules, params: dict[inst, dict], derived: callable) -> (params, results)`
where `=` rules set params in dependency order (cycle → `RuleError`), comparisons
return `RuleResult(rule, ok, lhs, rhs)`; unknown names → `RuleError` naming them.
`Assembly.use_rules(kind, **roles)`, `Assembly.rule(text, why="", confirmed=None)`
(unconfirmed inline/file rules ignored and counted). Rule-set param also in
`add(params=)` → `RuleError`. CLI `python scripts/rules.py list [PATH]` → one line.
`.gitignore`: add `library/`, `models/exports/`.

- [ ] Tests: set propagates; broken check reported, export still happens; unconfirmed ignored; cycle; conflict; role binding; project overrides world; dir resolution for both layouts.
- [ ] Implement, pass, commit.

### Task 4: exports (`assembly.py` run/export, `scripts/asm_render.py`, `scripts/mjcf.py`, `tests/test_exports.py`)

- `Assembly.run(out_dir=None) -> Solved`: rules → build → place → checks → exports → print summary. Exports dir: `cad/exports/<name>/` for `cad/assemblies/`, else `<asm dir>/exports/<name>/`.
- `report.txt`, `<name>.step` (labelled, coloured compound), `<name>.png` (iso + top panels, per-part colours, connector triads x red / y green / z blue with names), `<name>.xml` + `meshes/<inst>.stl`.
- MJCF: mm→m, kg; body tree; `freejoint` for `base_joint="free"` with model lifted so min z = 0; inertial from `matrix_of_inertia` (volume×density, mass override scales), mesh fallback via trimesh; hinge/slide/both; `motor` actuator with `ctrlrange`/`forcerange` = ±torque; speed in `<custom><numeric>`; ground plane. Gate: `mujoco.MjModel.from_xml_path` + 200 steps no NaN, else raise.
- Densities g/cm³: PLA 1.24, PETG 1.27, ABS 1.04, aluminium 2.70, steel 7.85.

- [ ] Tests: run writes all files; summary is one line; MJCF loads and steps; box mass = volume × 1.24e-6 kg; freejoint present; exports path for cad/ layout.
- [ ] Implement, pass, commit.

### Task 5: example, docs

- `models/bb_chassis.py`, `models/bb_gear_motor.py`, `models/bb_wheel.py`, `models/balance_bot.py`, `models/rules/wheel-hub.rules` (confirmed). `tests/test_example.py`: runs clean in one line; changing `shaft_d` moves bore via rule; changing chassis width moves motors and wheels.
- `references/assembly.md`; "Assemblies" sections in SKILL.md and README.md.
- [ ] Implement, full test suite, commit.
