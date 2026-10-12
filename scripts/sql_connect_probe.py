"""Run the destructive isolated Python named read/write/read-back proof."""
import sys,os,unittest,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Proof on an isolated emulator; resets its demo database.')
    parser.add_argument('--confirm',required=True)
    args=parser.parse_args()
    if args.confirm!='demo-terra-local':parser.error('requires --confirm demo-terra-local')
    os.environ['TERRA_RUN_EMULATOR_TESTS']='1'
    # Import only after opting in; setUpClass/tearDown restore the baseline.
    from tests.test_emulator import EmulatorTests
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([EmulatorTests('test_python_named_write_read_back')]))
    sys.exit(0 if result.wasSuccessful() else 1)
