// The value store shared by both bench pages: typed values are exact.
// Extracts the `// <value-store>` block from each page's <script> and runs it
// against a stub slider that behaves like a browser range input (clamps to
// [min,max], snaps to step) -- so a store that read the slider back would fail.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const ROOT = new URL('../../', import.meta.url);
const PAGES = ['assets/bench-template.html', 'assets/live-bench.html'];
const BLOCK = /\/\/ <value-store>\r?\n([\s\S]*?)\/\/ <\/value-store>/;

function block(page) {
  const m = readFileSync(new URL(page, ROOT), 'utf8').match(BLOCK);
  assert.ok(m, `${page}: no // <value-store> ... // </value-store> block`);
  return m[1];
}

function rangeInput(q) {
  let v = String(q.val);
  return {
    get value() { return v; },
    set value(x) {
      const n = Math.min(q.max, Math.max(q.min, parseFloat(x)));
      const snapped = q.min + Math.round((n - q.min) / q.step) * q.step;
      v = String(Number(Math.min(q.max, snapped).toFixed(6)));
    },
  };
}

function load(page) {
  const params = [
    { id: 'x', fs: 'X', u: 'MM', g: 'Main', label: 'X', min: 0, max: 200, step: 0.5, val: 10 },
    { id: 't', fs: 'T', u: 'MM', g: 'Main', label: 'T', min: 0.1, max: 5, step: 0.1, val: 1 },
  ];
  const els = Object.fromEntries(params.map(q => [q.id, rangeInput(q)]));
  const el = id => {
    if (!(id in els)) throw new Error(`value store touched element ${id}`);
    return els[id];
  };
  const api = new Function('KEY', 'P', 'el',
    block(page) + '\nreturn {VALUES, vals, setFromSlider, setTyped, applyPasted};')(
    'part', () => ({ params }), el);
  params.forEach(q => api.setFromSlider(q));
  return { api, els, q: Object.fromEntries(params.map(q => [q.id, q])) };
}

for (const page of PAGES) {
  test(`${page}: slider input sets the store`, () => {
    const { api, els, q } = load(page);
    els.x.value = '37.5';
    api.setFromSlider(q.x);
    assert.equal(api.vals().x, 37.5);
    assert.equal(api.VALUES.part.x, 37.5);
  });

  test(`${page}: typed 0.4 on a step-0.5 slider stays 0.4`, () => {
    const { api, els, q } = load(page);
    assert.equal(api.setTyped(q.x, '0.4'), true);
    assert.equal(api.vals().x, 0.4);
    assert.equal(els.x.value, '0.5');  // the slider snaps; the value does not
  });

  test(`${page}: typed 250 on a max-200 slider stays 250`, () => {
    const { api, els, q } = load(page);
    api.setTyped(q.x, '250 mm');
    assert.equal(api.vals().x, 250);
    assert.equal(els.x.value, '200');
  });

  test(`${page}: unparseable typed value leaves the value unchanged`, () => {
    const { api, q } = load(page);
    api.setTyped(q.x, '12.25');
    assert.equal(api.setTyped(q.x, 'abc'), false);
    assert.equal(api.setTyped(q.x, ''), false);
    assert.equal(api.setTyped(q.x, '3abc'), false);
    assert.equal(api.vals().x, 12.25);
  });

  test(`${page}: pasted constants are applied exactly`, () => {
    const { api, els, q } = load(page);
    const r = api.applyPasted('const T = 0.43 * MM;\nconst X = 250 * MM;\nconst Z = 3 * MM;');
    assert.equal(api.vals().t, 0.43);
    assert.equal(api.vals().x, 250);
    assert.equal(els.x.value, '200');
    assert.deepEqual(r.loaded, ['T', 'X']);
    assert.deepEqual(r.outside, ['X']);
    assert.deepEqual(r.other, ['Z']);
    assert.equal(api.vals().x, 250, String(q.x.max));
  });
}

test('both pages share the same value-store code', () => {
  const norm = s => s.replace(/\r\n/g, '\n');
  assert.equal(norm(block(PAGES[0])), norm(block(PAGES[1])));
});
