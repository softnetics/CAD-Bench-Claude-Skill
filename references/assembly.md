# Assemblies lookup

Joining parts at named connectors, rules that carry sizes between parts,
the checks, and the STEP / MuJoCo exports. **A lookup, not a read-through.**
`models/balance_bot.py` (with `bb_chassis.py`, `bb_gear_motor.py`,
`bb_wheel.py`, `rules/wheel-hub.rules`) is usually the faster answer.

## Contents

1. Connectors on a part
2. Joining: the convention
3. The assembly file
4. Purpose and rules
5. Checks and what each warning means
6. Outputs
7. MuJoCo model
8. Imported STEP / STL parts

---

## 1. Connectors on a part

Next to `build()`, computed from the part's own parameters, so a resize moves
them:

```python
import assembly as A

def connectors(P):
    d = derive(P)
    return {
        "motor_l": A.frame((-d["mount_x"], 0, 0), z=(0, 0, -1), x=(-1, 0, 0)),
        "shaft":   A.axis((d["shaft_tip"], 0, 0), z=(1, 0, 0)),
        "dot":     A.point((0, 0, P["h"])),
    }
```

| kind | pins | use for |
|---|---|---|
| `A.frame(origin, z, x=None)` | all 6 motions | faces that mate flat, mounts |
| `A.axis(origin, z)` | roll about z left free | shafts, bores, hubs: anything that spins |
| `A.point(origin)` | 3 rotations left free | ball joints, rough placement |

`x=None` picks the world axis least parallel to `z`, deterministic.

**Anchor to a feature instead of retyping arithmetic** (the "bottom edge vs
face centre" choice):

```python
A.on_face(B.top_face(part))           # face centre, z = outward normal
A.on_edge(edge)                       # edge midpoint, x along the edge
A.on_circle(B.circular_edges(part, r)[0])   # arc centre, z = arc axis (axis kind)
```

These need the built solid: `connectors(P)` may call `build(P)` and select.

## 2. Joining: the convention

- A connector's **z points OUT of its part** (out of the face, out along the
  shaft).
- `join(a, b)` puts the two z axes **opposed** (face to face) and the x axes
  aligned: b lands on a like a part set down on a table.
- `flip=True` aligns z instead. Use it when both connectors point the same
  way at the joint, e.g. a motor shaft tip (out along the shaft) and a
  wheel's outer face (out of the wheel): flipped, the wheel sits back over
  the shaft with its outer face flush with the tip.
- `angle=` turns b about the joint z (degrees); `gap=` separates along z (mm).
- Rotation sign is easy to get backwards. Check the picture (§6) rather than
  reasoning it out; `references/brep.md` §8 has the same warning.

## 3. The assembly file

In a project: `cad/assemblies/<name>.py`, parts found in `cad/parts/`. Under
`models/`: parts in the same folder. Part lookup is `../parts/` then the
assembly's own folder.

```python
asm = A.Assembly("balance_bot", base="chassis", base_joint="free", path=__file__)
asm.add("chassis", part="bb_chassis", params={"plate_x": 140}, material="PLA")
asm.add("motor_l", part="bb_gear_motor", mass=0.03)       # kg, overrides density
asm.join("chassis.motor_l", "motor_l.mount", "fixed")
asm.join("motor_l.shaft", "wheel_l.hub", "wheel", flip=True,
         motor=A.Motor(torque=0.08, speed=20))           # N·m, rad/s
asm.use_rules("wheel hub", wheel="wheel_l", shaft="motor_l")
asm.allow_overlap("wheel_l", "motor_l")                  # only for an intended press fit
asm.run()
```

- Joint types: `fixed`, `revolute` (`limits=(lo, hi)` degrees), `slider`
  (`limits=` mm, along z), `cylindrical`, `wheel` (continuous, no limits).
- `base` defaults to the first part added. `base_joint="free"` for anything
  that drives or falls; `"fixed"` bolts the base to the world.
- Parameter order: `PARAMS` → `<part>.params.json` (bench hand-off) →
  `add(params=)` → `=` rules.
- A part joined twice is placed by the first join; the second is only
  checked.
- Moving joints are shown and exported at position 0.
- Materials (g/cm³): PLA 1.24, PETG 1.27, ABS 1.04, aluminium 2.70, steel 7.85.

Run: `python <assembly>.py` or `python scripts/assembly.py <assembly>.py`.

## 4. Purpose and rules

**Before resizing a part, or first using it in an assembly, write down what
it is for and the rules that follow from that, in plain words, and get the
user's OK.** Only confirmed rules are used. Then ask: this project only, or
worldwide?

```
kind: wheel hub
purpose: A wheel pressed onto a motor shaft; carries the robot's weight.
roles: wheel, shaft
confirmed: 2026-10-18
rule: wheel.bore_d = shaft.shaft_d + 0.1      # printed holes shrink: presses on
rule: wheel.hub_len >= 1.5 * shaft.shaft_d    # enough hub to grip
```

- `=` **sets** a parameter before the build (the size carries through);
  `>=`, `<=`, `>`, `<`, `==` are **checked** (a break warns; export still
  happens, which is the user's choice).
- Right-hand sides may read parameters and `derive()` values; a target must
  be a parameter. Allowed: numbers, `inst.name`, `+ - * / **`, `min`,
  `max`, `abs`, `sqrt`.
- A parameter set by a rule must not also be in `add(params=)` (error).
  Cycles are an error.
- No `confirmed:` line → the whole file is ignored, and the summary says
  how many rules were.
- One-off rule in the assembly: `asm.rule("a.x >= b.y + 2", why="...", confirmed="2026-10-18")`.

**Where rule files live:**

| scope | folder | versioned |
|---|---|---|
| project | `cad/rules/` (or `<assembly dir>/rules/` outside a project) | with the parts' checkpoints |
| worldwide | `<skill>/library/rules/` | **git-ignored**: the skill is a public clone, so never commit one unless the user explicitly contributes it |

A project file overrides a worldwide one of the same `kind`.

**Suggesting rules for a new, similar part:** `python scripts/rules.py list
<assembly.py>` prints the kinds on one line. Read the matching file, map its
roles and parameter names onto the new part (names often differ), and
**propose** the bound rules to the user. Apply only after they confirm.

## 5. Checks and what each warning means

Every check warns and the run continues to export.

| warning | meaning | usual fix |
|---|---|---|
| `X: under-defined, not joined to base (6 free motions ...)` | nothing places X | add a `join` |
| `X: under-defined, rotation about z free at a-b (axis connector on a fixed joint)` | an `axis`/`point` connector can't pin roll | use `A.frame` with an `x`, or a moving joint if it should move |
| `X: join a-b disagrees with its earlier placement by d mm / a deg` | a loop whose two joins don't agree | fix one connector, or drop the redundant join |
| `a and b overlap by V mm^3` | solids intersect after placement | real clash: change a size or a connector; press fit: `allow_overlap` |
| `X.c: x stays at 30 while the part resizes (hard-coded?)` | connector never moves as the part's parameters change and isn't on a datum (part origin, bbox min/centre/max) | compute it from `P` / `derive(P)`, or anchor it with `on_face`/`on_edge` |
| `rule broken: ...: 5 vs 6 (why)` | a confirmed check rule fails | change a size, or revisit the rule with the user |

The hard-coded check nudges each parameter ±2 % and rebuilds (like
`sense.py`); parts with `PARAMS = {}` (imported) are skipped.

## 6. Outputs

One line on a clean run:

```
balance_bot: 5 parts, 4 joints, 4/4 rules ok -> models\exports\balance_bot
```

plus one `  warn: ...` line per warning. Everything else is in files, in
`cad/exports/<name>/` (project) or `<assembly dir>/exports/<name>/`:

- `report.txt`: per part its world position and axes, the joint that placed
  it and what that joint lets move, parameters after rules, mass and
  source, centre of mass, every connector in world coordinates; then rule
  results and warnings. **Read this, not extra prints.**
- `<name>.png`: iso + top, a colour per part, connector triads (x red,
  y green, z blue), names; coincident connectors share a label
  `a.x = b.y`. Look at it after any change to a join.
- `<name>.step`: the whole assembly, one labelled, coloured solid per part.
- `<name>.xml` + `meshes/`: MuJoCo model (§7).

## 7. MuJoCo model

- Body tree mirrors the joint tree from the base; each body frame is its
  part's build frame. Metres, kilograms, radians.
- `inertial`: mass, centre of mass and full inertia tensor from the exact
  CAD solid × density (`mass=` scales the tensor). STL-only parts use the
  mesh (noted in the report).
- Joints: `hinge` (revolute, wheel), `slide`, both for cylindrical; `range`
  when limited. Free base: `freejoint`, model lifted so its lowest point
  touches the floor plane.
- `motor=`: a `motor` actuator, `ctrlrange` = ±torque (N·m, or N on a
  slider); speed kept as `<custom><numeric name="<joint>.speed_max">` for
  project 3.
- The export loads the file in `mujoco` and steps it 200 times; failing to
  load or a NaN raises `MJCFError`. That's a broken export, not a warning.

`pip install mujoco` in the venv if it's missing.

## 8. Imported STEP / STL parts

```python
import brep as B
import assembly as A
PARAMS = {}
def derive(P): return dict(P)
def build(P): return B.import_step(r"C:\parts\n20_motor.step")
def connectors(P):
    return {"mount": A.frame((0, 0, 6.0), z=(0, 0, 1), x=(1, 0, 0)),
            "shaft": A.axis((0, 0, 21.5), z=(0, 0, 1))}
```

Numbers are expected here (measure them off the file; `inspect_stl.py` helps
for an STL); the hard-coded check skips parts with no parameters. Give
`mass=` from the datasheet; a STEP's volume × density is rarely the real
motor's mass.
