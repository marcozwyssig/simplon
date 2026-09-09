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

The generated-CLI check below goes one step further: it renders a scaffolded product's CLI the way
`support tasks generate` would and runs mypy over it, the same gate a product declaring
`test:typecheck-python` runs. A product's own sources passing that gate proves nothing about the file
the kernel hands it - see the regression this guards (generated-typeclean-report.md).
"""
import re
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

# Renders demo.yaml's CLI exactly the way `support tasks generate` would (taskgen.render, fed by
# manifest.load + catalogue.load - the entry point netctl's defect was reproduced through), from inside
# the scaffolded product so `orchestrator.cli`'s impls resolve. Run with the product dir as cwd.
_GENERATE_CLI = (
    "import sys; sys.path.insert(0, 'deploy/provision/orchestrator/src/python');"
    "from simplon import taskgen, catalogue;"
    "from simplon.orchestrator import manifest;"
    "text = open('demo.yaml', encoding='utf-8').read();"
    "m = manifest.load(text, catalogue=catalogue.load());"
    "src = taskgen.render(m, source='demo.yaml', product='demo');"
    "open('deploy/provision/orchestrator/src/python/orchestrator/_generated_cli.py', 'w', "
    "encoding='utf-8').write(src)"
)

# The minimal config simplon.tasks.typecheck.check() requires of a real product (mypy resolves its
# source roots against the CURRENT directory, hence `files`, not against the config's own location).
_MYPY_INI = ("[mypy]\nfiles = deploy/provision/orchestrator/src/python\n"
             "mypy_path = deploy/provision/orchestrator/src/python\n")


def _build_wheel(tmp_path_factory) -> Path:
    """Build the wheel once; each fixture below installs it into its OWN throwaway venv."""
    work = tmp_path_factory.mktemp("build")
    subprocess.run([sys.executable, "-m", "build", "--wheel",
                    "--outdir", str(work)], cwd=ROOT, check=True,
                   capture_output=True)
    wheels = list(work.glob("simplon-*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


def _venv_with_wheel(wheel: Path, tmp_path_factory, *, extra: str = "") -> Path:
    """A throwaway venv with the built wheel installed, optionally pulling in an extras group."""
    env = tmp_path_factory.mktemp("venv") / "venv"
    venv.create(env, with_pip=True)
    bindir = env / ("Scripts" if sys.platform == "win32" else "bin")
    py = bindir / ("python.exe" if sys.platform == "win32" else "python")
    target = f"{wheel}[{extra}]" if extra else str(wheel)
    subprocess.run([str(py), "-m", "pip", "install", "-q", target],
                   check=True, capture_output=True)
    return bindir


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    """Build the wheel and install it into one throwaway venv, shared by the checks below.

    Module-scoped because building a wheel and creating a venv costs seconds, and every check here
    wants the same installed package rather than a fresh one."""
    return _venv_with_wheel(_build_wheel(tmp_path_factory), tmp_path_factory)


@pytest.fixture(scope="module")
def installed_typecheck(tmp_path_factory):
    """The same wheel, installed with the `typecheck` extra into its OWN venv.

    A separate fixture rather than adding the extra to `installed`: mypy plus its stub is real install
    weight (and the point of the extra being optional), and the two checks that scaffold-and-drive the
    console script above have no reason to pay for it."""
    return _venv_with_wheel(_build_wheel(tmp_path_factory), tmp_path_factory, extra="typecheck")


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


def test_the_generated_cli_passes_its_own_type_gate(installed_typecheck, tmp_path):
    """The file the generator hands a product must survive the product's own `test:typecheck-python`.

    Regression for a defect found in netctl: 49 mypy findings of two shapes, both coming from the
    template rather than the product. `_rc`'s parameter was typed `object`, so `int(value)` had no
    overload to match (call-overload); and the scaffolded build/up/down bodies were annotated `-> None`
    while the generated wrapper reads their return value through `_rc`, so mypy flagged each as not
    returning a value (func-returns-value). A product could not fix either without `tasks generate`
    undoing it on the next run - the only available remedy was `ignore_errors = True` on the whole file.
    """
    # arrange: scaffold a product from the installed console script, same as
    # test_the_installed_console_script_scaffolds_a_product above, but in a venv that also has mypy
    exe = installed_typecheck / ("simplon.exe" if sys.platform == "win32" else "simplon")
    py = installed_typecheck / ("python.exe" if sys.platform == "win32" else "python")
    product = tmp_path / "product"
    out = subprocess.run([str(exe), "init", "demo", "--dir", str(product)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr

    # act: render demo.yaml's CLI the way `support tasks generate` would, then run the exact gate a
    # product declaring test:typecheck-python runs over it
    out = subprocess.run([str(py), "-c", _GENERATE_CLI], cwd=product,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr

    (product / "mypy.ini").write_text(_MYPY_INI, encoding="utf-8")
    out = subprocess.run([str(py), "-m", "mypy", "--config-file", "mypy.ini"], cwd=product,
                         capture_output=True, text=True)

    # assert
    assert out.returncode == 0, out.stdout + out.stderr


# --- the version, proved against a BUILT and INSTALLED package (#3) ---------------------------------------
#
# The version comes from the git tag now, and every other test in this repository reads it out of a source
# tree that has `.git` sitting right beside it. An installed package has no such thing: the tag has to have
# been baked in at build time, into `_version.py` and into the distribution metadata. Configuration cannot
# be trusted to say so - a wrong `version_file` path, a package-data omission, a build that silently fell
# back - so this builds the wheel, installs it, and asks it.

_VERSION_PROBE = (
    "import simplon, importlib.metadata as md;"
    "print(simplon.__version__);"
    "print(md.version('simplon'));"
    "import simplon._version as v; print(v.version)"
)


def _nearest_tag() -> str:
    """The release this checkout descends from, straight from git, or a skip.

    Deliberately NOT `simplon.__version__`: this module BUILDS the package, and setuptools-scm writes
    `src/simplon/_version.py` into the working tree as it does so. The value the test process imported at
    collection time can therefore be one commit behind the wheel it is about to judge - a difference that
    depends on when somebody last reinstalled, which is not a property of the code. `git describe` is the
    same fact the build itself reads, and it does not go stale.
    """
    described = subprocess.run(["git", "describe", "--tags", "--abbrev=0"], cwd=ROOT,
                               capture_output=True, text=True)
    if described.returncode != 0:
        pytest.skip("no tags reachable in this checkout; the wheel's version cannot be joined to one")
    return described.stdout.strip().lstrip("v")


def test_the_installed_package_reports_the_version_the_tag_gives_it(installed):
    """One number, three ways of asking, and it comes from the tag.

    `simplon.__version__` is what the scaffolder's pin is computed from; `importlib.metadata.version` is
    what pip resolves against; `_version.py` is the file that had to make it into the wheel for either to
    work without git. If the three disagree, or if the number is not the tag's, the wheel is mislabelled -
    and PyPI would take it anyway.
    """
    # arrange
    py = installed / ("python.exe" if sys.platform == "win32" else "python")
    tag = _nearest_tag()

    # act: run OUTSIDE the repo, so no stray `.git` and no source tree can answer for the installed package
    out = subprocess.run([str(py), "-c", _VERSION_PROBE], cwd=str(Path(py).parent),
                         capture_output=True, text=True)

    # assert
    assert out.returncode == 0, out.stderr
    dunder, metadata, from_file = out.stdout.split()
    assert dunder == metadata == from_file, out.stdout
    assert dunder.startswith(tag), (
        f"the built wheel says {dunder}, which does not descend from the tag {tag}")


def test_a_product_scaffolded_by_the_installed_kernel_pins_an_installable_kernel(installed, tmp_path):
    """The end of the chain the ticket cares about: whatever version the wheel calls itself - and on any
    branch that is a `.postN.devM+g...` one - the requirements.txt it writes for somebody else's product
    must name a version that is on PyPI. A dev pin there is not a cosmetic wart; it is a product that
    cannot install at all, discovered by its author and not by us."""
    # arrange
    exe = installed / ("simplon.exe" if sys.platform == "win32" else "simplon")
    product = tmp_path / "pinned"
    tag = _nearest_tag()

    # act
    out = subprocess.run([str(exe), "init", "demo", "--dir", str(product)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    text = (product / "deploy" / "provision" / "orchestrator" / "requirements.txt").read_text(
        encoding="utf-8")
    pinned = re.search(r"^simplon==(\S+)", text, re.M).group(1)

    # assert: a plain release, and specifically the last one that was actually cut - identical to the
    # kernel's own version when it was built at a tag, and the tag behind it otherwise
    assert re.fullmatch(r"\d+\.\d+\.\d+", pinned), f"scaffolded pin {pinned!r} is not a released version"
    assert pinned == tag
