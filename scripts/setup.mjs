// Native Windows/macOS setup, without activation scripts or global pip installs.
import { existsSync } from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { root, venvPython, pythonEnvironment, run } from './python_runtime.mjs';

export function pythonCandidates(platform = process.platform) {
  return platform === 'win32'
    ? [['py', ['-3']], ['python', []], ['python3', []]]
    : [['python3', []], ['python', []]];
}

function findPython() {
  for (const [command, args] of pythonCandidates()) {
    const result = spawnSync(command, [...args, '-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'], {
      cwd: root, env: pythonEnvironment(), shell: false, stdio: 'ignore', timeout: 10000,
    });
    if (result.status === 0) return [command, args];
  }
  throw new Error('Install Python 3.11 or newer first. On Windows, enable the Python launcher (py) or add Python to PATH.');
}

async function checked(command, args, options = {}) {
  const code = await run(command, args, options);
  if (code !== 0) throw new Error(`Setup command failed with exit code ${code}; fix the reported error and rerun npm run setup.`);
}

export async function setup() {
  const python = venvPython();
  if (!existsSync(python)) {
    if (existsSync(path.join(root, '.venv'))) {
      throw new Error('The existing .venv belongs to another OS or is incomplete. Remove only .venv and rerun npm run setup.');
    }
    const [command, args] = findPython();
    await checked(command, [...args, '-m', 'venv', path.join(root, '.venv')], { env: pythonEnvironment() });
  }
  await checked(python, ['-m', 'pip', 'install', '-r', 'requirements-dev.txt', '-r', 'backend/requirements.txt'], { env: pythonEnvironment() });
  const npmCli = process.env.npm_execpath;
  if (!npmCli || !existsSync(npmCli)) throw new Error('Run setup through npm run setup so its npm executable is available.');
  // Run npm's JS entry point directly; npm.cmd cannot be spawned as an exe on Windows.
  await checked(process.execPath, [npmCli, '--prefix', 'frontend', 'ci']);
  console.log('Terra setup complete. Use npm test, npm run dev:frontend, npm run dev:backend and npm run emulator.');
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.join(root, 'scripts', 'setup.mjs')) {
  try { await setup(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
