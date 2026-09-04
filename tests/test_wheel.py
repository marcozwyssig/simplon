"""The only tests that use the package the way a consumer does.

Every other test here runs against the source tree, because conftest.py puts
it on sys.path. That is why nobody noticed the kernel resolved its own
catalogue by walking five directories up to the repo root -- correct when
vendored, nonsense when installed. These build the wheel, install it into a
throwaway venv, and drive it from there.

`simplon init` is checked through the venv's console script for the same
reason. It is the first command every new user runs, and nothing else proves
it against an installed package: test_init_contract.py goes through conftest's
sys.path injection, so it can neither see a missing entry point nor a
templates/*.j2 that failed to make it into the wheel. Both are package-data
by declaration today, but only a check keeps them that way.
"""
import subprocess
import sys
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PROBE = (
    "import simplon.catalogue as c, pathlib;"
    "p = pathlib.Path(c.__file__).parent;"
    "assert 'site-packages' in str(p), p;"
    "cat = c.load();"
    "assert cat.tasks, 'catalogue loaded but empty';"
    "print(len(cat.tasks))"
)


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    """Build the wheel and install it into one throwaway venv, shared by the checks below.

    Module-scoped because building a wheel and creating a venv costs seconds, and every check here
    wants the same installed package rather than a fresh one."""
    work = tmp_path_factory.mktemp("wheel")
    subprocess.run([sys.executable, "-m", "build", "--wheel",
                    "--outdir", str(work)], cwd=ROOT, check=True,
                   capture_output=True)
    wheels = list(work.glob("simplon-*.whl"))
    assert len(wheels) == 1, wheels

    env = work / "venv"
    venv.create(env, with_pip=True)
    bindir = env / ("Scripts" if sys.platform == "win32" else "bin")
    py = bindir / ("python.exe" if sys.platform == "win32" else "python")
    subprocess.run([str(py), "-m", "pip", "install", "-q", str(wheels[0])],
                   check=True, capture_output=True)
    return bindir


def test_the_wheel_carries_its_catalogue(installed):
    # arrange
    py = installed / ("python.exe" if sys.platform == "win32" else "python")

    # act
    out = subprocess.run([str(py), "-c", PROBE], capture_output=True, text=True)

    # assert
    assert out.returncode == 0, out.stderr
    assert int(out.stdout.strip()) > 0


def test_the_installed_console_script_scaffolds_a_product(installed, tmp_path):
    # arrange: the console script, not `python -m simplon.bootstrap` - the entry point is its own piece
    # of packaging metadata and can be missing while the module imports perfectly well
    exe = installed / ("simplon.exe" if sys.platform == "win32" else "simplon")
    assert exe.exists(), f"the wheel installed no console script at {exe}"
    product = tmp_path / "product"

    # act
    out = subprocess.run([str(exe), "init", "demo", "--dir", str(product)],
                         capture_output=True, text=True)

    # assert: the launcher is rendered from a templates/*.j2 package-data file and the manifest from a
    # module constant, so between them they cover both ways a scaffolded file can be absent from a wheel
    assert out.returncode == 0, out.stderr
    written = sorted(p.name for p in product.glob("*"))
    assert (product / "demo.sh").is_file(), written
    assert (product / "demo.yaml").is_file(), written
