import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { root, venvPython, requirePython, pythonEnvironment, run } from '../scripts/python_runtime.mjs';
import { pythonCandidates } from '../scripts/setup.mjs';

test('Windows uses the native Scripts interpreter, even in a path with spaces', () => {
  assert.equal(venvPython('C:\\Team Projects\\Terra', 'win32'), 'C:\\Team Projects\\Terra\\.venv\\Scripts\\python.exe');
});

test('macOS and Linux use the local venv without shell activation', () => {
  for (const platform of ['darwin', 'linux']) {
    assert.equal(venvPython('/Users/Team Projects/Terra', platform), '/Users/Team Projects/Terra/.venv/bin/python');
  }
});

test('missing environment gives actionable setup instructions', () => {
  const folder = mkdtempSync(path.join(os.tmpdir(), 'terra setup '));
  try { assert.throws(() => requirePython(folder), /npm run setup/); }
  finally { rmSync(folder, { recursive: true }); }
});

test('bootstrap considers the Windows launcher and native Python commands', () => {
  assert.deepEqual(pythonCandidates('win32')[0], ['py', ['-3']]);
  assert.deepEqual(pythonCandidates('darwin')[0], ['python3', []]);
});

test('UTF-8 environment is set programmatically and preserves emulator routing', () => {
  assert.deepEqual(pythonEnvironment({ DATA_CONNECT_EMULATOR_HOST: '127.0.0.1:9399', PYTHONUTF8: '0' }), {
    DATA_CONNECT_EMULATOR_HOST: '127.0.0.1:9399', PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8',
  });
});

test('launcher runs the project venv from another cwd and preserves spaced arguments', () => {
  const folder = mkdtempSync(path.join(os.tmpdir(), 'terra caller '));
  try {
    const result = spawnSync(process.execPath, [path.join(root, 'scripts', 'run_python.mjs'), '-c',
      'import json,sys,os; print(json.dumps([sys.prefix,sys.argv[1:],os.getcwd()]))',
      'two words', '$(literal)', '磁砖 ×'], { cwd: folder, encoding: 'utf-8' });
    assert.equal(result.status, 0, result.stderr);
    const [prefix, args, cwd] = JSON.parse(result.stdout);
    assert.equal(prefix, path.join(root, '.venv'));
    assert.deepEqual(args, ['two words', '$(literal)', '磁砖 ×']);
    assert.equal(path.resolve(cwd), path.resolve(root));
  } finally { rmSync(folder, { recursive: true }); }
});

test('launcher propagates Python failure status', () => {
  const result = spawnSync(process.execPath, [path.join(root, 'scripts', 'run_python.mjs'), '-c', 'raise SystemExit(7)']);
  assert.equal(result.status, 7);
});

test('process spawn errors reject and clean up signal handlers', async () => {
  const before = process.listenerCount('SIGINT');
  await assert.rejects(run(path.join(os.tmpdir(), 'terra-missing-program'), []));
  assert.equal(process.listenerCount('SIGINT'), before);
});
