"""Opt into database checks only inside the dedicated disposable emulator."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if __name__=='__main__':
    if os.environ.get('GCLOUD_PROJECT')!='demo-terra-local' or os.environ.get('DATA_CONNECT_EMULATOR_HOST')!='127.0.0.1:9499':
        sys.exit('Use npm run test:checkpoint-a; only the isolated emulator at 9499 is allowed.')
    os.environ['TERRA_RUN_EMULATOR_TESTS']='1'
    os.environ['TERRA_RUN_CHECKPOINT_A_TESTS']='1'
    suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_emulator','tests.test_ingestion_emulator','tests.test_publication','tests.test_checkpoint_a'])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
