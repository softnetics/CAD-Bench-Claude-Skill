// live-bench.html: checkpoint / try / keep / revert hand off ALL current values
// first, so a snapshot (or the abandoned try) never misses the sliders; a failed
// hand-off stops the op. back / forward / goto ask in-page first when the
// current values differ from the last hand-off.
// Extracts the `// <vc-ops>` block and runs it with a recording postJSON.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('../../assets/live-bench.html', import.meta.url), 'utf8');
const m = src.match(/\/\/ <vc-ops>\r?\n([\s\S]*?)\/\/ <\/vc-ops>/);

// `confirmAnswer`: what the in-page confirmation resolves to (records each ask).
function load(handoffReply = { ok: true, path: 'p' }, confirmAnswer = true) {
  assert.ok(m, 'live-bench.html: no // <vc-ops> ... // </vc-ops> block');
  const calls = [], asks = [];
  const postJSON = async (path, body) => {
    calls.push([path, body]);
    return path === '/api/handoff' ? handoffReply : { ok: true, line: 'did it' };
  };
  const current = { spacer: { w: 77, t: 0.4 } };
  const valsOf = k => ({ ...current[k] });
  const vals = () => valsOf('spacer');
  const askMoveConfirm = async (text) => { asks.push(text); return confirmAnswer; };
  const api = new Function('KEY', 'vals', 'valsOf', 'postJSON', 'askMoveConfirm',
    m[1] + '\nreturn {runVc, markHanded};')('spacer', vals, valsOf, postJSON, askMoveConfirm);
  return { ...api, calls, asks, current };
}

for (const op of ['checkpoint', 'try', 'keep', 'revert']) {
  test(`${op} hands off all values before the vc request`, async () => {
    const { runVc, calls } = load();
    const r = await runVc(op, 'idea');
    assert.equal(r.ok, true);
    assert.deepEqual(calls, [
      ['/api/handoff', { part: 'spacer', params: { w: 77, t: 0.4 } }],
      ['/api/vc', { op, arg: 'idea' }],
    ]);
  });
}

test('a failed hand-off stops the op and says why', async () => {
  const { runVc, calls } = load({ ok: false, error: 'disk full' });
  const r = await runVc('checkpoint', null);
  assert.equal(r.ok, false);
  assert.match(r.error, /disk full/);
  assert.deepEqual(calls.map(c => c[0]), ['/api/handoff']);
});

for (const op of ['back', 'forward', 'goto']) {
  test(`${op} with values already handed off runs without asking`, async () => {
    const { runVc, markHanded, calls, asks } = load();
    markHanded('spacer', { w: 77, t: 0.4 });
    const r = await runVc(op, 'x');
    assert.equal(r.ok, true);
    assert.deepEqual(asks, []);
    assert.deepEqual(calls.map(c => c[0]), ['/api/vc']);
  });

  test(`${op} with values not handed off asks first; cancel runs nothing`, async () => {
    const { runVc, markHanded, calls, asks } = load(undefined, false);
    markHanded('spacer', { w: 50, t: 0.4 });
    const r = await runVc(op, 'x');
    assert.equal(r.ok, false);
    assert.equal(asks.length, 1);
    assert.match(asks[0], /spacer/);
    assert.deepEqual(calls, []);
  });

  test(`${op} with values not handed off runs once confirmed, without a hand-off`, async () => {
    const { runVc, markHanded, calls, asks } = load(undefined, true);
    markHanded('spacer', { w: 50, t: 0.4 });
    const r = await runVc(op, 'x');
    assert.equal(r.ok, true);
    assert.equal(asks.length, 1);
    assert.deepEqual(calls.map(c => c[0]), ['/api/vc']);
  });
}

test('a successful hand-off becomes the new baseline', async () => {
  const { runVc, markHanded, asks } = load();
  markHanded('spacer', { w: 50, t: 0.4 });
  await runVc('checkpoint', null);
  await runVc('back', null);
  assert.deepEqual(asks, []);
});
