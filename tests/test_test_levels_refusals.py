"""The refusals `building/test-levels.md` quotes for a command gate, BUILT from the code that raises them.

WHY THIS FILE EXISTS AT ALL, and it is the shortest measured argument in this repository. The page
carried this, word for word, as what a gate says about a toolchain command:

    'suites.gates.unit.command': 'build unit' pins imag with `with:`, which
    simplon.tasks.toolchain:run_toolchain does not take (it takes: argv, env, image, network, workdir)

Two things were wrong with it and nothing could see either. The parameter list is not `run_toolchain`'s -
`caches` and `extra` are missing - and the message was UNREACHABLE for that body, because the gate
refused a context-taking body several lines earlier and `run_toolchain`'s first parameter is a
`typer.Context`. It was written rather than measured, and `CLAUDE.md`'s rule names exactly that: a quoted
error text is a second source for a string, not prose. Pin it against the real message.

si#136 made the case reachable, so the quotes can now be produced rather than remembered. Each one below
is raised HERE, through the same manifest shape the page shows, and compared with the page flat.

WHAT IS DELIBERATELY NOT HELD, said rather than left as a silence. The page's fourth quote lists the
commands a product's tree declares:

    ... is not a command in this product's tree (declared: build compile, build unit)

That list is not producible: the catalogue places `support:*` commands into every product's tree, so a
real message names eleven entries where the page names two. It is a pre-existing inaccuracy of a
different kind - an illustration shortened, not a fact invented - it is recorded in si#136 rather than
edited here, and holding it would mean either putting eleven irrelevant commands on the page or writing
an assertion that tolerates anything.

AAA throughout.
"""
from __future__ import annotations

import re
import textwrap

import pytest

from simplon import context
from simplon.context import ProductContext
from simplon.tasks import testrun, toolchain

import sitepages
from conftest import ROOT

#: The page under test.
PAGE = ROOT / "site" / "content" / "building" / "test-levels.md"

#: The product the page's own `command:` block describes: two `toolchain:run` commands, and the gate
#: command a gate may not name. Written here rather than reused from another suite because the whole
#: point is that these refusals come from THIS shape - the one a reader copies off the page.
MANIFEST = textwrap.dedent("""\
    product: cppdemo
    tasks:
      gate:   { impl: "simplon.tasks.testrun:gate", help: "Run a level.", passthrough_args: true }
      accept: { impl: "simplon.tasks.testrun:accept_cmd", help: "Run them all.", passthrough_args: true }
    groups:
      build:
        commands:
          compile:
            task: "toolchain:run"
            with: { image: "silkeh/clang:19", workdir: "/src", argv: ["cmake", "--build", "build"] }
            help: "Compile."
          unit:
            task: "toolchain:run"
            with: {IMAGE} workdir: "/src", argv: ["ctest", "--test-dir", "build"] }
            help: "ctest."
      test:
        commands:
          accept: { task: accept, help: "Every gate, in order." }
    """)


def _product(monkeypatch, tmp_path, *, image='image: "silkeh/clang:19",'):
    (tmp_path / "cppdemo.yaml").write_text(
        MANIFEST.replace("{IMAGE}", "{ " + image), encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        ProductContext("cppdemo", tmp_path, tmp_path / "cppdemo.yaml"))


def _flat(text: str) -> str:
    """One line, single-spaced - the shape a quoted message can be compared in after the page wrapped it
    across three lines to fit a column. `test_case_cpp_chapter.py`'s helper, for its reason."""
    return " ".join(text.split())


def _page() -> str:
    """The page flat, with its blockquote markers taken off.

    A quoted refusal is wrapped across three lines to fit the column and each of them opens with `> `,
    so a comparison against the raw text would fail on the markup rather than on the message - and a
    helper that answers "not there" for "I did not look properly" is the defect this repository hunts.
    """
    body = PAGE.read_text(encoding="utf-8")
    if not body.strip():
        raise ValueError(f"{PAGE} is empty")
    unquoted = re.sub(r"(?m)^> ?", "", sitepages.without_code(body))
    return _flat(unquoted)


def test_the_with_typo_refusal_the_page_quotes_is_the_gates_own_message(monkeypatch, tmp_path):
    """The quote si#136 was raised about. Its parameter list is `run_toolchain`'s, read off the body by
    the same call the gate makes, so a parameter added to or dropped from that body turns this red rather
    than leaving the page describing a signature nobody has any more."""
    # arrange: `imag:` for `image:`, which is the likeliest typo in a manifest whose author writes no
    # Python at all
    _product(monkeypatch, tmp_path, image='imag: "silkeh/clang:19",')

    # act
    with pytest.raises(ValueError) as refused:
        testrun._command("build unit", "gates.unit.command")

    # assert
    assert _flat(str(refused.value)) in _page(), (
        f"the page quotes something other than:\n  {refused.value}")

    # assert: and it really carries the full parameter list, which is the half that was wrong
    for name in ("caches", "extra"):
        assert name in str(refused.value), f"the refusal no longer names {name!r}; the page copies it"


def test_the_unpinned_image_refusal_the_page_quotes_is_the_toolchains_own(monkeypatch, tmp_path):
    """The quote that replaced an unreachable one. `toolchain:run` has no REQUIRED parameter, so the
    gate's "needs image, which its `with:` does not pin" cannot fire for it; what fires is the
    toolchain's own diagnosis, and it names the command a person types because the gate's stand-in
    context told the body which command it is. That is the whole of si#136 in one line."""
    # arrange
    _product(monkeypatch, tmp_path, image="")
    said: list[str] = []
    monkeypatch.setattr(toolchain.log, "die", lambda message, *a, **k: said.append(str(message)))

    # act: resolution succeeds - the refusal is the body's, at call time
    runner = testrun._command("build unit", "gates.unit.command")
    with pytest.raises(SystemExit) as exited:
        runner()

    # assert
    assert exited.value.code == 1
    assert len(said) == 1, f"the toolchain said {said}; the page argues from one refusal"
    assert _flat(said[0]) in _page(), f"the page quotes something other than:\n  {said[0]}"

    # assert: the command a person types, not the coordinate behind it
    assert said[0].startswith("build unit:"), (
        f"the diagnosis lost the command path the gate handed it: {said[0]!r}")


def test_the_loop_refusal_the_page_quotes_is_the_one_a_gate_really_makes(monkeypatch, tmp_path):
    """The rule that must survive whatever a gate hands a body: a gate may not name the command that runs
    the gates. The page quotes it, so it is raised here rather than trusted."""
    # arrange
    _product(monkeypatch, tmp_path)

    # act
    with pytest.raises(ValueError) as refused:
        testrun._command("test accept", "gates.unit.command")

    # assert
    assert _flat(str(refused.value)) in _page(), (
        f"the page quotes something other than:\n  {refused.value}")
