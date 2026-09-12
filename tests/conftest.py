"""pytest bootstrap for the simplon unit tests: put the src-layout source tree on sys.path so
`from simplon import ...` resolves without an install (mirrors netctl's convention)."""
import sys
from pathlib import Path

import pytest

# The source tree now sits in src-layout one level above the tests. The wheel check
# (test_wheel.py) deliberately runs WITHOUT this path -- it is the only test that uses the
# package the way a consumer would.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from simplon import hostpath   # noqa: E402  (needs the sys.path line above)

#: The environment variables that change what a PURE kernel function returns, cleared for every test.
AMBIENT = ("DELIVERY_HOST_ROOT", "DELIVERY_MOUNT_ROOT")


@pytest.fixture(autouse=True)
def _this_suite_runs_as_if_on_a_host(monkeypatch):
    """Pin the two facts the kernel reads about WHERE it is running, so a unit test says the same thing
    on both of si#201's routes.

    WHY IT EXISTS, measured rather than reasoned. `simplon test all` can now be run through the kernel's
    container image, and inside it both facts are true: `DELIVERY_HOST_ROOT` is exported by the launcher,
    and `/.dockerenv` is on the filesystem. `simplon.hostpath.translate` consults both, so every unit
    test of an argv builder that passes a `tmp_path` - which is not under the mount - met a refusal it
    was never written for. The container route came back 74 failed against 4 on the venv route, and
    every one of the 74 was that.

    The routes have to reach the same verdict; that is si#199's whole acceptance criterion. A suite whose
    result depends on where the interpreter happens to sit cannot give one. So the default is "on a
    host", stated once, and a test that is ABOUT the container branch sets these itself with monkeypatch
    - a later `setattr` on the same attribute simply wins.
    """
    for name in AMBIENT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(hostpath, "in_a_container", lambda: False)
