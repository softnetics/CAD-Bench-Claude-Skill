# The CAD Bench artifact

A single published Artifact, `<title>CAD Bench</title>`, holding a picker of
parts. Each part is a self-contained recipe object. The page renders sliders,
live derived values, pass/fail constraint checks, and an SVG orthographic
preview -- and can write the current values into its own store for Claude to
read back.

`assets/bench-template.html` is this page with one example part (`boss-plate`)
already wired. Publish it as-is on first use; extend `PARTS` thereafter.

## Contents

1. Publishing and the `db` capability
2. The PART recipe object
3. `derive` / `cards` / `checks` / `draw` in detail
4. The SVG helper vocabulary
5. The handoff: writing `bench/<part>` and reading it back
6. Extending the shared page without breaking it
7. Home / preview / edit navigation

---

## 1. Publishing and the `db` capability

The page calls `window.claude.use("db")`. For that to resolve, publish with
the capability declared:

```
Artifact  file_path:<bench.html>  title:"CAD Bench"  favicon:"📐"
          capabilities: { "db": {} }
```

Read the `artifact-capabilities` skill first for the current contract. If the
capability is not granted in a given context the page still works -- the
"Hand these to Claude" button hides and the user falls back to **Copy
constants** (a plain text block) which you paste in yourself.

On every later republish to the same URL, **omit `favicon`** and keep the
`title` stable, or the artifact reads as a different page.

## 2. The PART recipe object

```js
"boss-plate": {
  label: "Boss plate",                    // home-list item name
  file:  "models/boss_plate.py",          // shown on the page; the model it pairs with
  note:  "Why the dimensions are what they are — the reasoning a reviewer needs.",
  params: [
    // one row per slider. id === the model PARAMS key. fs is optional and only
    // used to emit a `const` block for copy-paste; omit it and the value is
    // still handed over, just not printed in the consts pane.
    {id:"plate_x", fs:"PLATE_X", u:"MM",  g:"Plate", label:"Long side",  min:40, max:200, step:1,  val:60},
    {id:"plate_y", fs:"PLATE_Y", u:"MM",  g:"Plate", label:"Short side", min:30, max:160, step:1,  val:40},
    {id:"plate_t", fs:"PLATE_T", u:"MM",  g:"Plate", label:"Thickness",  min:2,  max:8,   step:.5, val:3},
    {id:"inset",   fs:"INSET",   u:"MM",  g:"Plate", label:"Hole inset", min:3,  max:20,  step:.5, val:8},
    {id:"boss_d",  fs:"BOSS_D",  u:"MM",  g:"Boss",  label:"Diameter",   min:5,  max:24,  step:.5, val:10},
    {id:"boss_h",  fs:"BOSS_H",  u:"MM",  g:"Boss",  label:"Height",     min:4,  max:40,  step:1,  val:12},
    {id:"bore_d",  fs:"BORE_D",  u:"MM",  g:"Boss",  label:"Bore",       min:2,  max:10,  step:.1, val:4},
  ],
  derive(p) { /* returns an object of computed values, see below */ },
  cards:  d => [ ["Boss wall", d.boss_wall.toFixed(2)], /* ... */ ],
  checks(p, d) { /* returns [ [ok, label, detail], ... ] */ },
  draw(p, d) { /* returns an SVG string */ },
  // mesh(p, THREE, CSG) { /* optional -- returns a THREE.BufferGeometry
  //   for a live-rendered 3D preview instead of/alongside draw()'s flat
  //   sketch. Only worth it for genuinely curved parts -- see the decision
  //   checklist and the mesh() contract in references/live-mesh-preview.md
  //   before adding one, and gate its publish on scripts/check_mesh_parity.py. */ },
}
```

`g` groups sliders under a heading. `u` is `"MM"` or `"DEG"` and controls the
unit shown and the `* MM` / `* DEG` suffix in the consts pane; use `u:""`
for a bare count (a lobe count, a hole count) -- no unit suffix in the
numbox, no `* unit` in the emitted `const`, just the number. `step` sets the
slider granularity -- match it to what you can actually hold in a print
(0.1 mm for fits, 1 mm for gross size, 0.5-1° for angles).

**A param can be `locked` -- fixed to an external requirement, not a free
starting point.** Add `locked:true` and a `lockNote` explaining the source:

```js
{id:"hole_d", fs:"HOLE_D", u:"MM", g:"Hole", label:"Diameter",
  min:3, max:7.5, step:.1, val:6.2,
  locked:true, lockNote:"JGB37-520 datasheet Ø6.0 mm shaft + 0.1 mm radial clearance"},
```

A locked slider renders disabled and dimmed with a 🔒 next to its label
(tooltip = `lockNote`); clicking the lock toggles it to 🔓 and enables free
editing until clicked again. Locked always shows the param's own `val`,
ignoring any previously-saved override, because the point of locking is
that this number is not supposed to drift. Use it for anything sourced from
a datasheet, a measured mating part, or a fastener standard -- a value the
model needs to match something real, not a value the user is meant to be
dialing. See `references/stl-reverse-engineering.md` §5 for the case this
was built for. Leave `locked` off entirely for ordinary design choices
(chamfer size, clearance margin, lobe count) -- those stay free sliders.

**The value box beside each slider is a typed-entry field, not a read-out.**
A slider alone can't always land on the exact number a reviewer wants, so the
template also renders `<input class="numbox" id="o_<id>">` next to it. On
commit (blur, or Enter) `commitNumbox()` clamps the typed value to `[min,max]`
-- the same bound the slider enforces -- then snaps it to the slider's own
step grid (multiples of `step` from `min`), matching what the slider would
land on if you'd dragged there. **Round to the step grid, not just to the
step's decimal width**: a step of `0.5` means valid values are `..., 17.0,
17.5, 18.0, ...`, so typing `17.3` lands on `17.5`, not `17.3` -- rounding
only the decimal *count* (1 dp) would wrongly accept `17.3`. This was
verified empirically, not assumed: assigning an off-grid value to a range
input's `.value` gets silently re-snapped by the browser itself, so the box
has to replicate that or it would show a number the slider can't actually
hold. The box briefly gets a `.clamped` (warn-coloured border) class when the
committed value differs from what was typed, then clears itself. An
unparseable entry (empty, letters) reverts to the slider's current value
rather than erroring. Nothing about `params` entries needs to change to get
this -- it reads `min`/`max`/`step` off the same row spec the slider uses.

## 3. derive / cards / checks / draw

**`derive(p)` -> object.** Pure function of the slider values. Put every
computed quantity here -- radii, positions, wall thicknesses, angles -- so
`cards`, `checks` and `draw` all read the same numbers. This should mirror the
model's own `derive(P)` so the page and the STL agree. JS getters are fine for
chained derivations.

**`cards(d)` -> `[[label, text], ...]`.** The read-out grid under the drawing.
Show the numbers a reviewer checks first: key radii, volume, critical gaps.

**`checks(p, d)` -> `[[ok, label, detail], ...]`.** The heart of the page.
Each row is a boolean, a short claim, and a measured detail string. Write one
per binding constraint:

```js
checks(p, d) {
  const tip = p.bore_d ? (p.inset - p.bore_d / 2) : 0;
  return [
    [d.boss_wall >= 2, "Boss survives the insert",
      d.boss_wall.toFixed(2) + " mm wall, want 2"],
    [p.boss_h > p.plate_t + 3, "Boss stands proud of the plate",
      (p.boss_h - p.plate_t).toFixed(1) + " mm"],
    [tip >= 2, "Bore clears the plate edge", tip.toFixed(2) + " mm"],
    [2 * p.inset < Math.min(p.plate_x, p.plate_y), "Bosses do not overlap",
      "centres " + (Math.min(p.plate_x, p.plate_y) - 2 * p.inset).toFixed(1) + " mm apart"],
  ];
}
```

A `true` literal as the first element makes an always-green informational row
("Opening is the body's own outline, 15.5 × 12.5 plus 0.5") -- useful for
stating a design decision inline.

**The `d.` / `p.` trap.** Slider values live on `p`; computed values live on
`d`. Writing `d.boss_d` when `boss_d` is a slider yields `undefined`. In an
arithmetic context that becomes `NaN` and every comparison against it is
`false`; in a bare comparison like `undefined >= 2` it is simply `false` with
no `NaN` anywhere. Either way the row goes **red and looks like a genuine
constraint failure**, so you tune sliders trying to fix a typo.

The template's `render()` labels a `NaN` row "CHECK IS BROKEN", but that only
catches the arithmetic half. Catching the *read* is the reliable detection, so
always run the shipped checker before publishing:

```
python scripts/check_bench.py <bench.html>
```

It evaluates every recipe at defaults and at every slider extreme, and traps
reads of keys that do not exist on the object being read -- the only reliable
detection for this class. It exits non-zero on any problem.

**`draw(p, d)` -> SVG string.** At least one orthographic view (top, or a
section) with the driving dimensions and the constrained features marked.
Scale to fit the `viewBox` (`0 0 620 400` in the template). This is a
sanity-check sketch, not a render -- its job is to make a gross error
obvious (a boss off the plate, a wall on the wrong side).

**Laying out more than one view -- give each a region BEFORE you scale
anything into it.** The recurring failure isn't a wrong shape, it's two
views (or a view and its own caption) drawn into the same pixel space
because the scale factor for each was computed independently from its own
content with no bound on where the result would land:

```js
// WRONG -- s1 and s2 are each "however big my content needs to be", with
// nothing stopping the section (bz0=270, tall) from landing on top of the
// top view (cy=80) the moment its own geometry happens to be large.
const s1 = 280/(2*arcHalf), cy=80;
const s2 = 150/thickness,   bz0=270;
```

```js
// RIGHT -- carve the 620x400 canvas into disjoint regions FIRST (own a
// rectangle each, caption included), then compute a scale that fits each
// view'S OWN content inside its OWN region -- never the other way round.
const topX0=24, topX1=596, topY0=46, topY1=150;      // region, not a guess
const s1 = Math.min((topX1-topX0)/widthMm, (topY1-topY0)/heightMm);
const tcx=(topX0+topX1)/2, tcy=(topY0+topY1)/2;       // centre OF the region
const T=(x,y)=>[tcx+x*s1, tcy-y*s1];
```

Then: **captions and labels get a fixed slot, never a position computed from
a shape's own scaled geometry.** `cap()` for a view goes a fixed distance
above that view's own `Y0`; a note between two views goes at a fixed Y in the
gap you left for it; a label for a small feature (a bore, a corner) goes
*outside* the region in its own column, joined by `ln()` as a leader line,
rather than guessed to land in empty space inside the shape -- shapes grow
under slider changes, empty space today is not empty space at another value.
Multi-view layouts in this file (`bottom-cover`'s top/section/unrolled,
`tof-wedge`'s top/section) both follow this: fixed region bounds, fixed
caption offsets, a leader line for anything labelled off to the side.

**How to know a layout is actually right: run the checker, don't eyeball
it.** `check_bench.py` (below) parses every `draw()` output's `<rect>`,
`<circle>`, `<polygon>`, `<path>` and `<text>` into approximate bounding
boxes and flags two things: a text box more than ~35% covered by a filled
shape (unreadable), and two part-coloured solid shapes overlapping between
~30% and ~95% of the smaller one's area (the two-views-sharing-one-region
bug). It runs at defaults AND at every slider's min/max, because a layout
that's fine at the default value can still collide once a slider pushes one
view's content larger. A clean run is necessary, not sufficient -- still
glance at the rendered page once before publishing -- but it catches the
actual recurring bug class without a human staring at every slider extreme.

**Two false-positive shapes the solid-overlap check deliberately does NOT
flag, both found the hard way:**

- **A hole in a boss.** The hole is void-fill against the boss's part-fill,
  so it never matches the part-vs-part filter at all.
- **Full containment (>95%).** A boss standing on a wall or plate, drawn
  solid-on-solid to show it rising from a solid section, has the smaller
  shape's bbox entirely inside the larger one's -- geometrically distinct
  from a real view collision, where each shape has some area the *other*
  doesn't. Above 95% is treated as intentional nesting, not a bug.

**What the checker still WILL flag, correctly, and what to do about it: a
"boss fused to its own base" T-junction.** Two rects representing one
continuous solid -- a tall boss rect and a short, wide base/ledge rect it
grows out of -- cross like a `+`, each sticking out where the other doesn't,
which is a **real partial overlap** (30-95%), not full containment, and the
checker has no way to tell it apart from an actual collision by geometry
alone. This isn't a false positive to suppress -- it's a genuine limit of
this heuristic. Chasing it by resizing the ledge just relocates which axis
overlaps (verified: tying a boss-plate model's ledge width to `boss_d`
stopped the X-axis overlap and immediately produced a Y-axis one instead,
flagged at *every* slider value tried, not just the extremes -- the pattern
is inherent to two rects sharing an edge, not a tunable dimension). If the
secondary shape is decorative -- doesn't carry a dimension the caption or
another view doesn't already show -- the fix that actually works is to
**remove it**, not keep re-tuning a size that will always cross the other
shape somewhere.

## 4. SVG helper vocabulary

The template defines these at the top of `<script>`; use them in `draw`:

| helper | makes |
|---|---|
| `S(x,y)` | `"x,y"` point string, 1 dp |
| `pg(pts, attr)` | `<polygon>` from `[[x,y],...]`; default fill = part colour |
| `rc(x,y,w,h, attr)` | `<rect>` (w/h may be negative) |
| `ci(x,y,r, attr)` | `<circle>`; default = void colour (a hole) |
| `ln(x1,y1,x2,y2)` | dashed construction line |
| `tx(x,y,s, size)` | small label text |
| `cap(x,y,s)` | tracked-out caption (view title) |
| `A(extra)` / `V` / `G` | attribute strings: part fill / void fill / ghost outline |

Colours come from CSS variables that already adapt to light/dark
(`--part`, `--part-line`, `--void`, `--rule`, `--warn`, `--ok`). Never
hard-code a hex value in `draw`.

## 5. The handoff

The page's sliders live only in the browser. The handoff copies them into the
artifact's store where `read_db` can reach them.

**On "Hand these to Claude"** the page runs:

```js
DB.doc("bench/" + KEY).set({
  part:   KEY,             // e.g. "boss-plate"
  label:  part.label,
  file:   part.file,
  params: vals(),          // { plate_x: 62, plate_y: 40, ... }  <- what you want
  consts: <the const block text>,
  savedAt: new Date().toISOString(),
});
```

A live snapshot listener shows "Claude last received this part at HH:MM:SS"
so the user can see whether the sliders in front of them have been sent.

**To read it back:**

```
Artifact  action:read_db  url:<artifact-url>  db_op:get
          collection:"bench"  doc_id:"<part>"
```

Returns the document. Take `params`, write it to
`models/<part>.params.json`, and the model's `__main__` picks it up. If
`savedAt` is older than your last delivery, the user hasn't re-handed --
ask before regenerating.

`bench/` is a shared collection; each part is one document, overwritten on
each hand-off. Nothing else writes there.

## 6. Extending the shared page

1. `Artifact action:read url:<artifact-url>` to get the current HTML into a
   local file.
2. Add your new key to the `PARTS` object. Nothing else needs to change to
   point at it -- the page opens on the home list (§7), not on a specific
   part, so there is no `let KEY = "<first-part>"` to keep in sync any more.
3. Keep the existing parts byte-for-byte. They have their own `bench/<part>`
   rows and users may be mid-tweak.
4. Republish to the **same URL** (`Artifact file_path:<file> url:<artifact-url>`),
   no `favicon`, same `title`.
5. If you changed a part's `params` (added/renamed a slider), update that
   part's model `PARAMS` in the same change, and note it to the user -- their
   stored `bench/<part>` row and their `localStorage` slider state are now
   partly stale.

## 7. Home / preview / edit navigation

The page opens on a **home list** -- just the part names and their model
file, nothing else -- not straight into whichever part happened to load
first. Clicking a name opens a **read-only preview**: the drawing, the
derived-value cards, the checks, all rendered from that part's own default
values, but no sliders. An **"Edit dimensions →"** button on that preview
is what actually reveals the slider panel. This exists so opening the page
(or switching parts) shows you *what a part is* before committing to
*changing it* -- useful once a bench page holds more than two or three
parts and "which one was I looking at" stops being obvious from a wall of
sliders.

Three states, one function each:

```js
let KEY = null;         // no part selected until one is opened
let VIEW = 'home';      // 'home' | 'preview' | 'edit'

function openPart(k){   // called ONLY from the home list -- there is no
  KEY=k; VIEW='preview'; // in-editor part switcher, so this is the one
  buildControls(); render(); showView();  // way in, and always to preview
}

function showView(){
  const isHome = VIEW==='home';
  el("home").hidden = !isHome;
  el("editorArea").hidden = isHome;
  if(isHome) return;
  const isPreview = VIEW==='preview';
  el("cols").classList.toggle("preview-mode", isPreview);  // collapses the
  el("controls").hidden = isPreview;                        // 340px slider
  el("ioPanel").hidden = isPreview;                          // column to 0
  el("previewActions").hidden = !isPreview;
  el("editorFile").textContent = P().file;
}
```

**There is no in-editor part-picker.** An earlier revision had a row of
part-name tabs above the sliders so you could jump straight from one part's
editor to another's preview. The user found that row confusing on a page
that also has a "← All parts" button right next to it -- two different
controls both claiming to be "the way to another part." Removed entirely:
`openPart()` is now only ever called from the home list, and the editor
view shows nothing but "← All parts" plus the current part's file name.
Getting to a different part always means going back to the home list
first -- one path, not two.

**This costs nothing at the `check_bench.py` / model-parity level.** The
headless checker evaluates `PARTS[key].derive/checks/draw` directly against
each part's own default and extreme slider values -- it never touches
`buildHome`, `openPart`, `showView`, or any other page-navigation function,
so restructuring how a part gets ON screen has no effect on whether its own
numbers are still correct. Verified by running `check_bench.py` before and
after adding this navigation and confirming the problem count didn't
change, then a real click-through (home → preview → edit → back) in the
browser pane to confirm the states themselves behave, since that's the one
thing the headless checker cannot see.

**Un-handed slider changes are guarded against being silently lost.** A
`DIRTY` flag goes `true` on any slider drag, typed-numbox commit, or
successful "Load into sliders" paste, and back to `false` only when a part
is freshly opened, or values are actually handed off (via the DB
hand-off, or "Copy constants" as the fallback). The only way left to leave
a dirty part without going through a hand-off is "← All parts" (plus
closing the tab/window itself), and it checks first:

```js
function askLeaveConfirm(){
  if(!DIRTY) return Promise.resolve(true);
  return new Promise(resolve=>{
    el("leaveModal").hidden=false;
    const cleanup=(v)=>{
      el("leaveModal").hidden=true;
      el("leaveModalConfirm").removeEventListener("click",onYes);
      el("leaveModalCancel").removeEventListener("click",onNo);
      resolve(v);
    };
    const onYes=()=>cleanup(true), onNo=()=>cleanup(false);
    el("leaveModalConfirm").addEventListener("click",onYes);
    el("leaveModalCancel").addEventListener("click",onNo);
  });
}
```

**This is an in-page modal, not a native `confirm()`, and that is load-
bearing, not stylistic.** The first cut of this feature used a plain
`confirm()` call and shipped with `check_bench.py` green -- but on the real
published Artifact it produced no dialog at all: an Artifact renders in a
sandboxed iframe, and `window.confirm()`/`alert()`/`prompt()` are silently
no-ops there (no dialog, no thrown error, `confirm()` just returns
immediately) rather than failing loudly. The user reported it as "there is
no pop-up," not as an error, which is exactly what that failure mode looks
like from the outside. Fix: a `.modal-overlay`/`.modal-box` pair already in
the page's own DOM, shown/hidden via the `hidden` attribute, with
`askLeaveConfirm()` returning a `Promise<boolean>` that resolves when
"Stay" or "Leave" is clicked -- so callers (`backHome`'s click handler) are
`async` and `await` it instead of branching on a synchronous return value.
**If you ever add another place that needs this guard, await
`askLeaveConfirm()`; do not reach for `confirm()` again, on this page or
any future bench page** -- it will look correct in `check_bench.py` and in
a plain local `file://` open, and then do nothing at all once published.

`window.addEventListener("beforeunload", ...)` (the real-tab-close case)
still uses the native event -- there's no DOM alternative for that one --
and needs an existence guard: `if (typeof window.addEventListener ===
"function")`, because `check_bench.py`'s headless harness stubs `window` as
a bare `{}` with no methods on it, unlike a real browser; without the
guard the harness throws "window.addEventListener is not a function" and
every part reports as failed, which is how this was actually caught before
publishing, not by inspection.

Verified in a real browser (a native `confirm()` cannot be driven through
browser automation, so the earlier version of this guard could only ever
be checked by direct state stubbing -- the sandboxed-iframe failure above
was invisible to that method and only showed up on the real published
page): dirty a slider, click "← All parts," confirm the modal renders with
real text and two buttons; click "Stay," confirm the editor view and the
dirty slider value are unchanged; click "← All parts" again, click "Leave,"
confirm it lands back on the home list.

**"Leave" actually discards the changes, not just navigates away from
them.** The warning text promises "your changes will not be saved" --
the first cut of this only kept that promise by accident, because
`localStorage["cadbench"]` (the seed `buildControls()` reads a part's
sliders from) was being overwritten on every single `render()` call, i.e.
on every slider tick, dirty or not. That meant there was never anything
correct to revert TO: reopening a part after "Leave" showed the exact same
un-handed values right back, because they'd already been cached as if they
were legitimate. Fixed by narrowing what gets written there to only the two
real hand-off moments:

```js
function saveHandoffSnapshot(p){
  try{ const all=JSON.parse(localStorage.getItem("cadbench")||"{}");
       all[KEY]=p; localStorage.setItem("cadbench", JSON.stringify(all)); }catch(e){}
}
function revertToLastHandoff(){
  let saved=null;
  try{ saved=(JSON.parse(localStorage.getItem("cadbench")||"{}"))[KEY]; }catch(e){}
  P().params.forEach(q=>{
    if(isLocked(q)) return;
    const v = saved && saved[q.id]!==undefined ? saved[q.id] : q.val;
    el(q.id).value = v;
  });
  render();
}
```

`saveHandoffSnapshot(vals())` is called from exactly two places -- the DB
`send` handler's success branch, and the `copy` button's success branch --
both already the moments that reset `DIRTY=false`, so "handed over" means
the same thing to the snapshot as it already meant to the dirty flag.
`revertToLastHandoff()` is called from `backHome`'s click handler, only
when the part WAS dirty and the user chose "Leave":

```js
el("backHome").addEventListener("click", async ()=>{
  const wasDirty = DIRTY;
  if(!(await askLeaveConfirm())) return;
  if(wasDirty) revertToLastHandoff();
  DIRTY=false; VIEW='home'; showView();
});
```

A part that has never been handed over reverts to its own coded default
(`q.val`), not to some earlier arbitrary drag position -- there is no
"before" to speak of until a hand-off actually happens once. Locked
sliders are skipped: their value is never a user edit in the first place,
so there is nothing on them to revert. Verified in a real browser: fake a
prior hand-off by writing `{wallH:45}` into `localStorage["cadbench"]`
directly, reopen the part and confirm the slider seeds at 45 (not the
coded default), drag it to 30, click "← All parts" → "Leave," confirm it
reads back 45; separately, drag to 33 and click "Stay," confirm it stays at
33 and nothing was written to storage.
