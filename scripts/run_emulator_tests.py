"""Opt into destructive tests only inside the local Data Connect emulator suite."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == '__main__':
    if os.environ.get('GCLOUD_PROJECT') != 'demo-terra-local' or not os.environ.get('DATA_CONNECT_EMULATOR_HOST'):
        sys.exit('Use npm run test:integration; this test runner requires the demo emulator context.')
    os.environ['TERRA_RUN_EMULATOR_TESTS'] = '1'
    suite = unittest.defaultTestLoader.loadTestsFromName('tests.test_emulator')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
