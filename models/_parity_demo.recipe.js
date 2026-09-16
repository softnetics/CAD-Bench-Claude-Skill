// _parity_demo.recipe.js -- fixture for scripts/check_mesh_parity.py's own
// self-test. Mirrors models/_parity_demo.py: a box with a cylindrical bore.
//
// CONTRACT: mesh(p, THREE, CSG) receives THREE and a small CSG namespace as
// EXPLICIT ARGUMENTS rather than importing them itself. This is the
// pattern every live-preview recipe should follow (see
// references/live-mesh-preview.md) -- it means the same function runs
// unchanged in the browser (where the bench page imports three.js once
// from a CDN and passes it in) and in this checker's headless Node
// harness (which imports the installed npm packages and passes those
// instead). A mesh() that does its own `import` statement can only run in
// one of those two places.
//
// CSG here is {Brush, Evaluator, SUBTRACTION} from three-bvh-csg -- the
// bench page and this checker both inject the same three names.

export const params = [
  {id: "box_x", min: 8, max: 40, step: 0.5, val: 20.0},
  {id: "box_y", min: 8, max: 40, step: 0.5, val: 16.0},
  {id: "box_z", min: 4, max: 30, step: 0.5, val: 10.0},
  {id: "bore_d", min: 2, max: 12, step: 0.1, val: 6.0},
];

export function mesh(p, THREE, CSG) {
  const box = new CSG.Brush(new THREE.BoxGeometry(p.box_x, p.box_y, p.box_z));
  box.updateMatrixWorld();
  const bore = new CSG.Brush(new THREE.CylinderGeometry(
    p.bore_d / 2, p.bore_d / 2, p.box_z + 2, 32));
  bore.rotateX(Math.PI / 2);          // CylinderGeometry's axis is Y; the
  bore.updateMatrixWorld();           // model's bore runs along Z.

  const evaluator = new CSG.Evaluator();
  const result = evaluator.evaluate(box, bore, CSG.SUBTRACTION);
  return result.geometry;
}
