"""The typing marker has to be IN the wheel, not just in the tree.

Without py.typed mypy treats an installed simplon as untyped, and the
obvious repair on the consumer side -- ignore_missing_imports -- turns the
whole kernel into Any while the gate reports success. A green gate that
checks nothing is worse than a red one.
"""
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_py_typed_is_shipped(tmp_path):
    subprocess.run([sys.executable, "-m", "build", "--wheel",
                    "--outdir", str(tmp_path)], cwd=ROOT, check=True,
                   capture_output=True)
    wheel = next(iter(tmp_path.glob("simplon-*.whl")))
    names = zipfile.ZipFile(wheel).namelist()
    assert "simplon/py.typed" in names, names
