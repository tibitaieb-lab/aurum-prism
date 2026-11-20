"""Run synthetic regression and real-Qlib tests with outbound networking refused."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from public_prism.offline import install
install()

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='prism-tests-') as temporary:
        os.environ['MPLCONFIGDIR']=str(Path(temporary)/'matplotlib')
        suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
        result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
