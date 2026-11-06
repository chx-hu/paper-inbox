"""Run tests with the same flat module imports used by the app entry point."""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
result = unittest.TextTestRunner(verbosity=2 if '-v' in sys.argv else 1).run(suite)
raise SystemExit(not result.wasSuccessful())
