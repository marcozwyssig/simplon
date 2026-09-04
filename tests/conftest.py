"""pytest bootstrap for the delivery unit tests: put the delivery block's python language level
(src/delivery/src/python) on sys.path so `from delivery import ...` resolves without an install
(mirrors netctl's convention)."""
import sys
from pathlib import Path

BLOCK = Path(__file__).resolve().parents[3]  # src/delivery
sys.path.insert(0, str(BLOCK / "src" / "python"))
