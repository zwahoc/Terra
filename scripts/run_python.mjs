import { requirePython, pythonEnvironment, run } from './python_runtime.mjs';

try {
  process.exitCode = await run(requirePython(), process.argv.slice(2), { env: pythonEnvironment() });
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
