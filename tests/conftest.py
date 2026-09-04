"""pytest bootstrap for the simplon unit tests: put the src-layout source tree on sys.path so
`from simplon import ...` resolves without an install (mirrors netctl's convention)."""
import sys
from pathlib import Path

# The source tree now sits in src-layout one level above the tests. The wheel check
# (test_wheel.py) deliberately runs WITHOUT this path -- it is the only test that uses the
# package the way a consumer would.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
