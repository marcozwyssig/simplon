"""THE API CONTRACT AS A GENERATED FILE: the `spec` command both web profiles carry (si#240).

WHY THE PYTHON HALF IS TESTED AND THE JAVA HALF IS NOT. The java entry is an invocation of somebody
else's gradle plugin - there is nothing here to go wrong that a test could see without starting Spring
Boot, and what it does was measured against a real tree on 2026-09-14 and written into the table. The
python entry ships a PROGRAM, and a program has a behaviour to protect.

THE ONE THING WORTH PROTECTING, and it is this repository's recurring defect at a new place. The program
has to tell a FACTORY from an APP, and the obvious predicate - `callable(target)` - is wrong in a way
that is silent in review and loud at run time: a FastAPI app is itself callable, because being callable
is what an ASGI application IS. So `callable` carries "a factory" on this side of the seam and "an app"
on the other, and the first draft of this program called the app with no arguments:

    TypeError: FastAPI.__call__() missing 3 required positional arguments: 'scope', 'receive', 'send'

The fix is the one this project always reaches for - stop asking the ambiguous question. `hasattr(target,
"openapi")` asks for the method the very next line calls. `test_a_callable_app_object_is_not_mistaken_for
_a_factory` is that repair held in place: rewrite the predicate as `callable` and it goes red.

NO FASTAPI HERE, deliberately. The program never mentions the framework, so the test does not install
one - two hand-written objects say everything the program can distinguish, and a suite that needed a web
framework to check five lines would be paid for on every run.

AAA throughout.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from simplon.tasks.profiles import EXPORT_OPENAPI, PROFILES

#: A module the program can import, carrying the three shapes it is ever handed: a factory, an app
#: object that is ALSO callable (what FastAPI really is), and something that is neither.
PRODUCT = '''
class App:
    """An app the way an ASGI framework builds one: it has `openapi()` AND it is callable."""

    def __init__(self, title):
        self.title = title

    def openapi(self):
        return {"openapi": "3.1.0", "info": {"title": self.title}}

    def __call__(self, scope, receive, send):
        raise AssertionError("the export called the application instead of reading its contract")


app = App("from the object")


def create_app():
    return App("from the factory")


not_an_app = 42
'''


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "product"
    root.mkdir()
    (root / "product.py").write_text(PRODUCT, encoding="utf-8")
    return root


def _export(root: Path, target: str, out: str) -> subprocess.CompletedProcess[str]:
    """Run the profile's own argv, minus the container: the same interpreter, the same program, the same
    two positional arguments the table passes."""
    return subprocess.run([sys.executable, "-c", EXPORT_OPENAPI, target, out],
                          cwd=str(root), capture_output=True, text=True)


def test_both_web_profiles_carry_the_command():
    """The ticket asked for one language and the measurement found two consumers in two - biz-cockpit in
    Python and netctl's Java control plane, whose `src/netctl/api/rest/` is an empty directory whose
    README calls a generated OpenAPI extract future work. One profile would have served half of that."""
    # assert
    for language in ("python", "java"):
        assert "spec" in PROFILES[language].commands, f"the {language} profile lost its `spec` command"


def test_a_factory_is_called(tmp_path):
    """`app.main:create_app` is the spelling biz-cockpit types today, so it is the spelling the table
    ships as its starting point."""
    # arrange
    root = _tree(tmp_path)

    # act
    done = _export(root, "product:create_app", "contract.json")

    # assert
    assert done.returncode == 0, done.stderr
    written = json.loads((root / "contract.json").read_text(encoding="utf-8"))
    assert written["info"]["title"] == "from the factory"


def test_a_callable_app_object_is_not_mistaken_for_a_factory(tmp_path):
    """THE SEAM. An ASGI app is callable; `callable` is therefore not the question. Rewrite the
    predicate as `callable(target)` and `App.__call__` raises, which is what this asserts."""
    # arrange
    root = _tree(tmp_path)

    # act
    done = _export(root, "product:app", "contract.json")

    # assert
    assert done.returncode == 0, done.stderr
    written = json.loads((root / "contract.json").read_text(encoding="utf-8"))
    assert written["info"]["title"] == "from the object"


def test_a_failed_export_leaves_no_file_for_the_gate_to_compare(tmp_path):
    """The other half of the same defect, one step later. `test:generated` regenerates and then diffs;
    a program that wrote a partial document before failing would hand it a file to compare and turn a
    broken export into a stale-contract message. The write is the last statement, so it does not."""
    # arrange
    root = _tree(tmp_path)

    # act
    missing_attribute = _export(root, "product:make_app", "contract.json")
    not_an_app = _export(root, "product:not_an_app", "contract.json")

    # assert
    assert missing_attribute.returncode != 0
    assert "make_app" in missing_attribute.stderr
    assert not_an_app.returncode != 0
    assert not (root / "contract.json").exists(), "a failed export wrote a contract anyway"
