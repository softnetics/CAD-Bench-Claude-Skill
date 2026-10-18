// live-bench.html: checkpoint / try / keep hand off ALL current values first,
// so a snapshot never misses the sliders; a failed hand-off stops the op.
// Extracts the `// <vc-ops>` block and runs it with a recording postJSON.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('../../assets/live-bench.html', import.meta.url), 'utf8');
const m = src.match(/\/\/ <vc-ops>\r?\n([\s\S]*?)\/\/ <\/vc-ops>/);

function load(handoffReply = { ok: true, path: 'p' }) {
  assert.ok(m, 'live-bench.html: no // <vc-ops> ... // </vc-ops> block');
  const calls = [];
  const postJSON = async (path, body) => {
    calls.push([path, body]);
    return path === '/api/handoff' ? handoffReply : { ok: true, line: 'did it' };
  };
  const vals = () => ({ w: 77, t: 0.4 });
  const runVc = new Function('KEY', 'vals', 'postJSON', m[1] + '\nreturn runVc;')('spacer', vals, postJSON);
  return { runVc, calls };
}

for (const op of ['checkpoint', 'try', 'keep']) {
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

for (const op of ['revert', 'back', 'forward', 'goto']) {
  test(`${op} does not hand off`, async () => {
    const { runVc, calls } = load();
    await runVc(op, 'x');
    assert.deepEqual(calls.map(c => c[0]), ['/api/vc']);
  });
}
