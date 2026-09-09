"""The one line of the top-level `--help` that says which simplon answered (si#125).

WHY THIS IS A TEST FILE OF ITS OWN. Everything else about `assemble` is a fact about the MANIFEST: this
group becomes a sub-app, that name gets no flat alias. The epilog is a fact about the INSTALLATION - the
version the kernel resolved for itself and the directory it was imported from - and every one of those
facts can be absent. A product pins the kernel, an agent installs it into a venv, a maintainer keeps an
editable checkout on the same machine, and before si#125 the three rendered a byte-identical help screen.

So the interesting cases here are the degraded ones, and they are the reason the introspection is not
allowed to raise: a help screen that cannot render because the tool could not introspect itself is far
worse than one that says "location unknown". Each test below removes exactly one fact and asserts the
WHOLE line, because a substring assertion would pass on a line that had quietly lost its other half.

AAA throughout.
"""
import sys
import types

import pytest
import typer
from typer.testing import CliRunner

import simplon
from simplon import cli
from simplon.orchestrator import manifest

_MANIFEST = """
product: demo
tasks:
  fmt: { impl: "demo_impls:fmt", help: "Format the sources." }
  lint: { impl: "demo_impls:lint", help: "Lint the sources." }
groups:
  code:
    commands:
      fmt: { task: "fmt" }
      lint: { task: "lint" }
"""

#: A plausible released-wheel layout, spelled once so the assertions read as one shape with one fact
#: changed. `__file__` is what the kernel reads its location off; the package directory is its parent.
_WHEEL_FILE = "/opt/netctl/.venv/lib/python3.12/site-packages/simplon/__init__.py"
_WHEEL_DIR = "/opt/netctl/.venv/lib/python3.12/site-packages/simplon"
_CHECKOUT_FILE = "/home/marco/git/simplon/src/simplon/__init__.py"
_CHECKOUT_DIR = "/home/marco/git/simplon/src/simplon"

#: The rendered-help tests use a SHORT path on purpose: rich wraps the epilog to the terminal width and
#: may break a long path anywhere, so a test that asserted the real shape would be asserting the width it
#: happened to run at. The shape is asserted on `_provenance()` above; these ask only whether it arrives.
_SHORT_FILE = "/venv/simplon/__init__.py"
_SHORT_DIR = "/venv/simplon"


class _Dist:
    """The one thing the kernel asks a distribution for: its PEP 610 `direct_url.json`, or a failure.

    `payload` is what `read_text` answers - a string, `None` for the file a released wheel does not carry,
    or an exception instance to raise, which is how the unreadable-metadata paths are reached without a
    broken venv on disk.
    """

    def __init__(self, payload):
        self._payload = payload

    def read_text(self, name):
        assert name == "direct_url.json"
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


def _install(monkeypatch, *, version="0.9.0", file=_WHEEL_FILE, path=(), dist=None):
    """Pretend the kernel was imported from a given installation.

    `dist` is a `_Dist`, or an exception instance the distribution lookup raises; the default is the
    released wheel, which carries no `direct_url.json` at all. The metadata half and the imported-module
    half (`file=` / `path=`) are set separately because a real machine can lose either one without the
    other.
    """
    monkeypatch.setattr(simplon, "__version__", version, raising=False)
    monkeypatch.setattr(simplon, "__file__", file, raising=False)
    monkeypatch.setattr(simplon, "__path__", list(path), raising=False)
    answer = _Dist(None) if dist is None else dist

    def _lookup(name):
        assert name == "simplon"
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(cli, "_distribution", _lookup)


def _assemble(**kwargs):
    """A root app with the synthetic manifest assembled onto it, as a product's composition root does.

    Assembly happens INSIDE the test body rather than in a fixture, because the epilog is composed at
    assemble time - an app built by a fixture would carry this machine's real provenance, not the
    pretended one.
    """
    sys.modules["demo_impls"] = types.ModuleType("demo_impls")
    for name in ("fmt", "lint"):
        setattr(sys.modules["demo_impls"], name, lambda: None)
    try:
        app = typer.Typer(add_completion=False, no_args_is_help=True, help="demo root", **kwargs)
        cli.assemble(app, manifest.load(_MANIFEST), product="demo")
        return app
    finally:
        del sys.modules["demo_impls"]


def _unwrapped(text: str) -> str:
    """Rich pads and wraps every rendered line, so a help screen is not a place to match a phrase in one
    piece. Collapsing the whitespace makes the assertion be about the LINE rather than about the layout."""
    return " ".join(text.split())


# --- the line itself --------------------------------------------------------------------------------


def test_a_released_wheel_names_the_version_and_the_site_packages_directory(monkeypatch):
    """The ordinary case: a product pinned a version, pip put it in the venv, and the help screen can now
    say which one is answering."""
    # arrange
    _install(monkeypatch, version="0.9.0", file=_WHEEL_FILE)

    # act
    line = cli._provenance()

    # assert
    assert line == f"assembled by simplon 0.9.0 ({_WHEEL_DIR})"


def test_an_editable_install_is_visibly_different_from_a_wheel(monkeypatch):
    """The case si#125 exists for. A maintainer's editable checkout of a TAGGED tree resolves a clean
    release version, so the version alone says nothing and only the path differs - and a path is read as
    noise. The word is what makes it unmissable."""
    # arrange: the same version as the wheel above, deliberately
    _install(monkeypatch, version="0.9.0", file=_CHECKOUT_FILE,
             dist=_Dist('{"dir_info": {"editable": true}, "url": "file:///home/marco/git/simplon"}'))

    # act
    line = cli._provenance()

    # assert
    assert line == f"assembled by simplon 0.9.0 (editable install, {_CHECKOUT_DIR})"


def test_a_direct_url_install_that_is_not_editable_reads_as_an_ordinary_install(monkeypatch):
    """`pip install .` writes `direct_url.json` too, without the editable flag. It IS a built copy in
    site-packages, so it gets no marker: the flag is the question, not the file's presence."""
    # arrange
    _install(monkeypatch, file=_WHEEL_FILE,
             dist=_Dist('{"dir_info": {}, "url": "file:///home/marco/git/simplon"}'))

    # act
    line = cli._provenance()

    # assert
    assert line == f"assembled by simplon 0.9.0 ({_WHEEL_DIR})"


# --- the degraded paths -----------------------------------------------------------------------------


def test_a_source_tree_with_no_installed_distribution_says_so(monkeypatch):
    """A bare `sys.path` insertion: the modules import, nothing installed them. That is exactly the state
    `simplon.__init__` reports as `0.0.0.dev0+unknown`, and the two halves of the line agree here."""
    # arrange
    _install(monkeypatch, version="0.0.0.dev0+unknown", file=_CHECKOUT_FILE,
             dist=cli.PackageNotFoundError("simplon"))

    # act
    line = cli._provenance()

    # assert
    assert line == f"assembled by simplon 0.0.0.dev0+unknown (no installed distribution, {_CHECKOUT_DIR})"


def test_a_distribution_lookup_that_fails_for_any_other_reason_leaves_the_line_standing(monkeypatch):
    """Metadata can be broken rather than absent - a half-written dist-info, a packaging tool nobody here
    predicted. There is nothing true to say about the install shape then, so the line says nothing about
    it and still carries the two facts it does have."""
    # arrange
    _install(monkeypatch, file=_WHEEL_FILE, dist=ValueError("broken dist-info"))

    # act
    line = cli._provenance()

    # assert
    assert line == f"assembled by simplon 0.9.0 ({_WHEEL_DIR})"


@pytest.mark.parametrize("payload", [
    pytest.param(OSError("permission denied"), id="read-raises"),
    pytest.param(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"), id="undecodable"),
    pytest.param("{not json", id="not-json"),
    pytest.param('["a", "list"]', id="not-an-object"),
    pytest.param('{"url": "file:///x"}', id="no-dir-info"),
])
def test_unusable_direct_url_metadata_does_not_break_the_line(monkeypatch, payload):
    """Five ways the editable flag can be unusable, and the same answer to all of them: the marker is
    the decoration, the line is not.

    `read-raises` is the one that does not come from a real venv: the stock `PathDistribution.read_text`
    suppresses a missing or unreadable file and answers `None`, so only a non-stock finder raises there.
    It is covered because the kernel names `OSError` in its own except clause, and a branch nobody
    exercises is a branch nobody knows the answer of."""
    # arrange
    _install(monkeypatch, file=_WHEEL_FILE, dist=_Dist(payload))

    # act
    line = cli._provenance()

    # assert
    assert line == f"assembled by simplon 0.9.0 ({_WHEEL_DIR})"


def test_a_version_that_could_not_be_resolved_is_named_as_unresolved(monkeypatch):
    """`simplon.__version__` has a fallback of its own, so an empty one means the module itself is not
    what it should be. Rendering `assembled by simplon  (...)` would read as a formatting bug; saying so
    reads as the fact it is."""
    # arrange
    _install(monkeypatch, version="", file=_WHEEL_FILE)

    # act
    line = cli._provenance()

    # assert
    assert line == f"assembled by simplon, version unknown ({_WHEEL_DIR})"


def test_a_package_with_no_file_falls_back_to_its_search_path(monkeypatch):
    """A namespace package, a zipimport, a loader that sets no `__file__`: `__path__` still knows where
    the package was found, and every entry is named rather than the first one guessed at."""
    # arrange
    _install(monkeypatch, file=None, path=[_WHEEL_DIR, _CHECKOUT_DIR])

    # act
    line = cli._provenance()

    # assert
    assert line == f"assembled by simplon 0.9.0 ({_WHEEL_DIR}, {_CHECKOUT_DIR})"


def test_a_package_with_no_location_at_all_still_renders(monkeypatch):
    """Both halves gone. This is the assertion that says the help screen outranks the introspection."""
    # arrange
    _install(monkeypatch, file=None, path=[], dist=cli.PackageNotFoundError("simplon"))

    # act
    line = cli._provenance()

    # assert
    assert line == "assembled by simplon 0.9.0 (no installed distribution, location unknown)"


# --- where it is rendered ---------------------------------------------------------------------------


def test_the_top_level_help_carries_the_line(monkeypatch):
    """Rendered, not merely composed: through Typer's own help formatter, on an app assembled the way a
    product's composition root assembles one."""
    # arrange
    _install(monkeypatch, file=_SHORT_FILE)
    app = _assemble()

    # act
    out = CliRunner().invoke(app, ["--help"]).output

    # assert
    assert f"assembled by simplon 0.9.0 ({_SHORT_DIR})" in _unwrapped(out)


def test_a_group_help_does_not_repeat_the_line(monkeypatch):
    """si#125's first decision: the top level is where a reader looks for provenance, and repeating it on
    every group screen is noise."""
    # arrange
    _install(monkeypatch, file=_SHORT_FILE)
    app = _assemble()

    # act
    out = CliRunner().invoke(app, ["code", "--help"]).output

    # assert
    assert "assembled by simplon" not in _unwrapped(out)


def test_a_product_that_wrote_its_own_epilog_keeps_it(monkeypatch):
    """The epilog is the product's slot, not the kernel's. Overwriting it would make adopting a new kernel
    silently delete a line the product wrote on purpose."""
    # arrange
    _install(monkeypatch, file=_WHEEL_FILE)

    # act
    app = _assemble(epilog="Docs: https://example.invalid/demo")

    # assert
    assert app.info.epilog == (f"Docs: https://example.invalid/demo\n\n"
                               f"assembled by simplon 0.9.0 ({_WHEEL_DIR})")
