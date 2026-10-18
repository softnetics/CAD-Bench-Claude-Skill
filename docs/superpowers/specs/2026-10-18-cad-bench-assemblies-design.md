# cad-bench assemblies: connection points, joints, rules, STEP + MuJoCo

Status: design, 2026-10-18. Project 2 of 3 (see the foundation design's
*Roadmap*). Builds on the foundation now on `main` (`cadproj`, `partmodel`,
`sense`, `views`).

## Intent

The user is moving from single printed parts to machines: a two-wheel balance
bot first, later things that move and must be checked in simulation. They
want to:

- **join parts by meaning, not coordinates**: "the motor sits on the
  chassis's left mount", "the wheel goes on the motor shaft". Nobody types a
  world position.
- **resize a part and have the machine follow.** The user's example: a black
  box is resized and the red box on it must follow a *deliberately chosen*
  anchor (bottom edge vs face centre), not a number that happened to be
  right before.
- **have sizes that depend on each other stay consistent**, e.g. a wheel's
  bore follows the motor's shaft. Before any of that, Claude has to
  **understand what the part is for**, write that down as rules in plain
  words, and get the user's OK. Confirmed rules are kept as a local,
  readable library, so the next similar part comes with suggestions that
  already make sense. No model training; nothing changes without the user's
  OK.
- **hand the machine to simulation** (project 3) as a MuJoCo model whose
  masses and inertias come from the real CAD geometry.

## Goals

### 2a. Connection points (connectors)

- A part file declares named connectors next to `build()`:
  ```python
  def connectors(P):
      d = derive(P)
      return {
          "top":   A.frame((0, 0, P["h"]), z=(0, 0, 1)),        # face centre
          "edge":  A.frame((0, -P["y"]/2, 0), z=(0, 0, -1), x=(1, 0, 0)),
          "shaft": A.axis((0, 0, d["shaft_tip"]), z=(0, 0, 1)),  # roll is free
      }
  ```
  Computed from the part's own parameters, so a resize moves them.
- **Three kinds**, mirroring how much a connector pins:
  - `frame(origin, z, x)`: full frame, pins all 6 motions;
  - `axis(origin, z)`: roll about `z` is free;
  - `point(origin)`: all three rotations free.
  Joining a looser kind leaves motions free, and the under-defined check
  names them (see 2c).
- **Geometry helpers** so a connector can be *anchored to a feature* instead
  of retyped arithmetic: `A.on_face(face)` (centre, outward normal),
  `A.on_edge(edge)` (midpoint, along the edge), `A.on_circle(edge)` (arc
  centre, arc axis). The user's "bottom edge vs face centre" is a choice
  between two of these.
- **Convention: a connector's `z` points out of the part** (out of the face,
  out along the shaft). Joining two connectors puts their `z` axes
  **opposed** (face to face) and their `x` axes aligned; `flip=True` aligns
  `z` instead, `angle=` turns about `z`, `gap=` separates along `z`.
- **Imported STEP/STL parts**: a small part file whose `build()` imports the
  file, `PARAMS = {}`, and hand-placed connectors (numbers are expected here;
  the hard-coded check skips parts with no parameters).

### 2b. Assembly file

An assembly is a Python file, in a project at `cad/assemblies/<name>.py`
with parts in `cad/parts/`, or today beside the examples in `models/`.
Part lookup: `../parts/<part>.py` relative to the assembly, then the
assembly's own folder.

```python
import assembly as A

asm = A.Assembly("balance_bot", base="chassis", base_joint="free")
asm.add("chassis", part="chassis_plate", material="PLA")
asm.add("motor_l", part="gear_motor", mass=0.095)       # stand-in, datasheet mass
asm.add("wheel_l", part="wheel", params={"tyre_d": 70})
asm.join("chassis.motor_l", "motor_l.mount", "fixed")
asm.join("motor_l.shaft", "wheel_l.hub", "wheel",
         motor=A.Motor(torque=0.25, speed=30))          # N·m, rad/s
asm.use_rules("wheel hub", wheel="wheel_l", shaft="motor_l")
asm.run()        # rules -> build -> place -> checks -> exports, one line
```

- Joint types: `fixed`, `revolute` (about the shared `z`, optional
  `limits=`), `slider` (along `z`), `cylindrical` (both), `wheel` (a
  continuous revolute marked as rolling: no limits, contact on in MuJoCo).
  Optional `motor=` on any moving joint.
- **Placement solves by matching frames**, walking a tree out from the base
  part. Builder's call, flagged: build123d's own `RigidJoint` /
  `RevoluteJoint` / `LinearJoint` / `CylindricalJoint` compute the placement
  transforms; our code adds the bookkeeping build123d does not have (which
  motions are free, loops, reports). If a joint type maps badly, plain
  `Location` math is fine.
- A part joined twice (a loop) is placed by the first join; the second is
  checked for consistency and reported if it disagrees. Not passed to MuJoCo.
- The base is fixed to the world unless `base_joint="free"` (a robot that
  drives or falls).
- Builder's call, flagged: a part's parameters resolve in this order:
  `PARAMS` defaults, then its `<part>.params.json` (the bench hand-off, via
  the foundation's `effective_params`), then `add(params=...)`, then `=`
  rules. The same part file can be added several times with different
  parameters.
- Run with `python <assembly>.py` (the file calls `asm.run()`) or
  `python scripts/assembly.py <assembly>.py`. Moving joints are shown and
  exported at position 0.

### 2c. Checks (warn, never block)

Every check reports and the run continues to export.

- **Under-defined**: a part not reachable from the base names all six free
  motions and stays where it was built; a `point`/`axis` connector on a
  `fixed` joint names the rotations left free. Free motions are those beyond
  what the joint type intends. Like SolidWorks' (-) state.
- **Overlap**: after placement, every pair of parts is tested by exact
  boolean intersection (bounding-box prefilter); overlap above a small
  tolerance is reported with its volume. `asm.allow_overlap(a, b)` for an
  intended press fit.
- **Hard-coded connector**: nudge each numeric parameter of each part (as
  `sense.py` does), recompute connectors. A connector is flagged when the
  part's size changes under some nudge but the connector never moves under
  any nudge **and** it is not tied to a bounding-box landmark (min, centre or
  max in each axis stays matched). A bottom-centre anchor on a centred part
  is fine; `(30, 0, 10)` on a growing box is flagged.
- **Rules** (2d): a broken confirmed rule is reported with both sides'
  values; export still happens (user's decision).

### 2d. Purpose and rules

- **Before Claude resizes a part (or first uses it in an assembly), it
  writes down what the part is for and the rules that follow**, in plain
  words, and the user confirms, corrects or adds. Only confirmed rules are
  used. Example: *wheel hub*: "bore = motor shaft Ø + 0.1 (press fit)";
  "hub length ≥ 1.5 × shaft Ø (grip)".
- **A rule file is plain text, one per kind of part**, readable without the
  tool:
  ```
  kind: wheel hub
  purpose: A wheel pressed onto a motor shaft; carries the robot's weight.
  roles: wheel, shaft
  confirmed: 2026-10-18
  rule: wheel.bore_d = shaft.shaft_d + 0.1      # press fit on the shaft
  rule: wheel.hub_len >= 1.5 * shaft.shaft_d    # enough grip
  ```
  Roles are placeholders; `use_rules` binds them to instances. Assembly
  files may also state one-off rules inline: `asm.rule("...", why="...")`.
  A file without `confirmed:` is ignored, and the summary says how many
  were.
- **`=` rules set a parameter** before anything is built (so a size change
  carries through); `>=`, `<=`, `==` rules are checked after. Right-hand
  sides may read parameters and `derive()` values; a target must be a
  parameter. Rules are ordered by dependency; a cycle is an error.
  Builder's call: a parameter set by a rule must not also be given in
  `add(params=...)` (error, since it is a contradiction in the file).
- **Two scopes, chosen per rule file when the user confirms it:**
  - project: `cad/rules/` (versioned with the parts by the foundation's
    checkpoints); for an assembly under `models/`, `models/rules/`;
  - worldwide: `<skill>/library/rules/`, **git-ignored**, because the
    installed skill is a clone of the public repo. Never committed unless
    the user explicitly contributes a rule.
  Lookup: project first, then worldwide; a project file overrides a
  worldwide one of the same kind.
- **Suggestions**: `rules.py list` prints the kinds available (both
  scopes). Matching a library kind to a new part's parameter names is
  Claude's job; Claude proposes the bound rules and the user confirms
  before they apply.

### 2e. Outputs

- **One line on success**, e.g.
  `balance_bot: 5 parts, 4 joints, 6 rules ok -> cad/exports/balance_bot/`.
  Each warning adds one line naming the part and the problem; detail is in
  the report file.
- **Export folder** `<exports>/<assembly>/` (project: `cad/exports/`;
  `models/`: `models/exports/`, git-ignored):
  - `report.txt`: placement report: each part's world position and
    orientation, the joint that placed it, its connectors in world
    coordinates, free motions, rule results, overlaps, mass properties.
  - `<name>.png`: rendered picture (iso plus top), each part in its own
    colour, connector axis markers (x red, y green, z blue) with names.
    Builder's call: rendered from the tessellated meshes with Pillow, which
    is already installed, so markers share the exact same camera.
  - `<name>.step`: the whole assembly, one labelled solid per part.
  - `<name>.xml` + `meshes/`: MuJoCo MJCF, described below.

### 2f. MuJoCo model

- Body tree mirrors the joint tree from the base; base gets a `freejoint`
  when `base_joint="free"`. Units converted to metres and kilograms.
- Each body: mesh geom from the part's STL, `inertial` with mass, centre of
  mass and full inertia tensor from the exact CAD solid (volume × density;
  default PLA 1.24 g/cm³; materials table PLA, PETG, ABS, aluminium, steel;
  `mass=` overrides and scales the inertia). An imported STL has no exact
  solid; its mass properties come from the mesh (trimesh), flagged in the
  report.
- Joints: `hinge` (revolute, wheel, plus `range` when limited), `slide`,
  hinge + slide pair for cylindrical; axis and anchor from the connector.
- Motors: a `motor` actuator per motored joint with torque/force limit;
  speed limit kept in a `<custom>` numeric for project 3.
- A ground plane so a free base has something to stand on.
- Gate: the file must load with `mujoco.MjModel.from_xml_path` and step
  without NaN; the export fails loudly otherwise (an MJCF that doesn't load
  is a broken export, not a warning).

### 2g. Worked example and docs

- `models/` gets a balance-bot chassis assembly: chassis plate, two
  gear-motor stand-ins (simple box + shaft), two wheels, with connectors on
  each part, a `wheel hub` rule file, and an assembly file. Resizing the
  chassis or the motor shaft demonstrates the carry-through.
- `references/assembly.md` lookup doc; self-contained "Assemblies" sections
  in `SKILL.md` and `README.md` (existing sections untouched).

## Non-goals

- Running a simulation, controllers, motor datasheets (project 3).
- An assembly bench / live sliders for assemblies (possible follow-up on the
  foundation's live server).
- Gears, belts, cams, contact-driven mechanisms; loops in MuJoCo.
- Editing foundation files (`bench-template.html`, `new_part.py`,
  `check_bench.py`, the live server, git history code); a `cad.py assemble`
  command is a follow-up.

## Anti-goals

- A connector that silently stays put while its part is resized.
- A rule applied that the user never confirmed, or a library rule pushed to
  the public repo.
- Typing world coordinates into an assembly.
- Chatty output: more than one line on a clean run.
- An MJCF that exists but doesn't load.

## Constraints

- Local, free, Windows first. Venv at `C:\Users\gritp\cad-bench-venv`;
  new dependency: `mujoco` (pip wheel, 3.x). `import brep as B` only.
- New code in new files: `scripts/assembly.py`, `scripts/rules.py`,
  `scripts/mjcf.py`, `scripts/asm_render.py`, tests under `tests/`.
- Existing models and the foundation's tests keep passing.

## Left to the builder

Internal data structures, exact report layout, tolerances (overlap volume,
frame match), picture size and colours, colour/label handling in STEP,
mesh tessellation tolerance for MuJoCo, the expression parser (safe `ast`
subset), and how `point`/`axis` connectors pick a deterministic default
orientation.
