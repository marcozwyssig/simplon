"""The only test that uses the package the way a consumer does.

Every other test here runs against the source tree, because conftest.py puts
it on sys.path. That is why nobody noticed the kernel resolved its own
catalogue by walking five directories up to the repo root -- correct when
vendored, nonsense when installed. This builds the wheel, installs it into a
throwaway venv, and asks it to load its catalogue from site-packages.
"""
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROBE = (
    "import simplon.catalogue as c, pathlib;"
    "p = pathlib.Path(c.__file__).parent;"
    "assert 'site-packages' in str(p), p;"
    "cat = c.load();"
    "assert cat.tasks, 'catalogue loaded but empty';"
    "print(len(cat.tasks))"
)


def test_the_wheel_carries_its_catalogue(tmp_path):
    subprocess.run([sys.executable, "-m", "build", "--wheel",
                    "--outdir", str(tmp_path)], cwd=ROOT, check=True,
                   capture_output=True)
    wheels = list(tmp_path.glob("simplon-*.whl"))
    assert len(wheels) == 1, wheels

    env = tmp_path / "venv"
    venv.create(env, with_pip=True)
    py = env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run([str(py), "-m", "pip", "install", "-q", str(wheels[0])],
                   check=True, capture_output=True)

    out = subprocess.run([str(py), "-c", PROBE], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert int(out.stdout.strip()) > 0
