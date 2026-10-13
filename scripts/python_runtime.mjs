// Development tooling only. Python owns application and database behavior.
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

export const root = fileURLToPath(new URL('../', import.meta.url));

export function venvPython(repo = root, platform = process.platform) {
  const paths = platform === 'win32' ? path.win32 : path.posix;
  return paths.join(repo, '.venv', ...(platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python']));
}

export function requirePython(repo = root, platform = process.platform) {
  const python = venvPython(repo, platform);
  if (!existsSync(python)) {
    throw new Error('Project Python environment is missing. Run npm run setup first.');
  }
  return python;
}

export function pythonEnvironment(env = process.env) {
  // Windows consoles and file defaults need not match the dataset's UTF-8.
  return { ...env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' };
}

export function run(command, args, { cwd = root, env = process.env } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env, stdio: 'inherit', shell: false });
    const interrupt = () => child.kill('SIGINT');
    const terminate = () => child.kill('SIGTERM');
    process.on('SIGINT', interrupt);
    process.on('SIGTERM', terminate);
    const cleanup = () => {
      process.off('SIGINT', interrupt);
      process.off('SIGTERM', terminate);
    };
    child.once('error', (error) => { cleanup(); reject(error); });
    child.once('close', (code, signal) => {
      cleanup();
      resolve(code ?? (signal === 'SIGINT' ? 130 : 1));
    });
  });
}
