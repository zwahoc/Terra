"""Inter-process safety and Windows import regression for local seed/reset."""
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch
from terra import seeding

ROOT = Path(__file__).resolve().parents[1]

class SeedLockTests(unittest.TestCase):
    def test_seeding_import_without_fcntl(self):
        code = textwrap.dedent('''
            import builtins
            original = builtins.__import__
            def without_fcntl(name, *args, **kwargs):
                if name == 'fcntl':
                    raise ModuleNotFoundError("No module named 'fcntl'")
                return original(name, *args, **kwargs)
            builtins.__import__ = without_fcntl
            import terra.seeding
        ''')
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_contending_process_refused_then_can_acquire(self):
        with tempfile.TemporaryDirectory(prefix='terra lock ') as directory:
            root = Path(directory)
            code = 'from pathlib import Path; from terra import seeding; seeding.ROOT=Path(__import__("sys").argv[1]);\nwith seeding.seed_lock(): print("acquired")'
            with patch.object(seeding, 'ROOT', root):
                with seeding.seed_lock():
                    result = subprocess.run([sys.executable, '-c', code, str(root)], cwd=ROOT, capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Another local import/reset is active', result.stderr)
                result = subprocess.run([sys.executable, '-c', code, str(root)], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('acquired', result.stdout)

    def test_exception_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(seeding, 'ROOT', Path(directory)):
            with self.assertRaisesRegex(ValueError, 'example'):
                with seeding.seed_lock():
                    raise ValueError('example')
            with seeding.seed_lock():
                pass

    def test_body_timeout_not_misreported_as_contention(self):
        from filelock import Timeout
        with tempfile.TemporaryDirectory() as directory, patch.object(seeding, 'ROOT', Path(directory)):
            with self.assertRaises(Timeout):
                with seeding.seed_lock():
                    raise Timeout('different.lock')

    def test_terminated_owner_releases_lock(self):
        with tempfile.TemporaryDirectory(prefix='terra lock ') as directory:
            code = 'from pathlib import Path; import sys; from terra import seeding; seeding.ROOT=Path(sys.argv[1]);\nwith seeding.seed_lock():\n print("locked", flush=True)\n sys.stdin.readline()'
            owner = subprocess.Popen([sys.executable, '-c', code, directory], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(owner.stdout.readline().strip(), 'locked')
                owner.terminate()
                owner.communicate(timeout=10)
                with patch.object(seeding, 'ROOT', Path(directory)):
                    with seeding.seed_lock():
                        pass
            finally:
                if owner.poll() is None:
                    owner.kill()
                    owner.communicate(timeout=10)
