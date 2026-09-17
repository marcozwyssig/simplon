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
import yaml

from simplon import context
from simplon.context import ProductContext
from simplon.tasks import testrun, toolchain

import sitepages
from conftest import ROOT

#: The page under test.
PAGE = sitepages.chapter("test-levels.md")

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


# --- the refusals about a LEVEL rather than about a command (si#196) --------------------------------------
#
# THE SCOPE si#136 DID NOT REACH, and si#196 is what proved it needed reaching. Everything above derives
# a `command:` gate's refusals; the page carries three more that are about the SUITES SECTION itself, and
# those were still hand-typed. si#196 renamed the page's third level from `ui` to `acceptance` - `ui` is
# not a level, it is one kind of acceptance test - and all three quotes name the level by name, so the
# rename would have left three messages on the page that the code cannot produce. Exactly the class si#136
# measured, one section across.
#
# THE MANIFEST IS READ OFF THE PAGE, which is the part that makes the next rename safe rather than merely
# correct today. `MANIFEST` above is retyped here in the module because the C++ shape is the module's own
# subject; this one is not - the reader copies the block that is PRINTED, so the block that is printed is
# what has to be driven. `_example_section` lifts it out of the page, and a rename that touches the YAML
# and forgets a quote turns these red with the message the code really makes.

#: The heading the page's `suites:` example sits under. Named rather than matched on `suites:` alone: the
#: page prints several YAML blocks and two of them mention the section, so a first-match rule would pick
#: whichever one somebody adds next.
EXAMPLE_HEADING = "## The `suites:` section"

#: What the page calls the manifest in the refusals it quotes. Not a real file - the loader is handed the
#: name of whatever it read - and the page picked one, so the derivation has to use the same one or every
#: comparison fails on the prefix.
SOURCE = "sample.yaml"


def _example_section() -> dict:
    """The `suites:` mapping the page prints under its own section heading, parsed.

    Read off the PAGE and not restated here. The whole defect si#196 found is a quote that no longer
    matches the block above it, so a copy of that block living in this file would be the same second
    source one directory across - green while the page said something the loader would refuse.
    """
    body = PAGE.read_text(encoding="utf-8")
    after = body.partition(f"\n{EXAMPLE_HEADING}\n")[2]
    if not after:
        raise ValueError(f"{PAGE} carries no section headed {EXAMPLE_HEADING!r}, so its example manifest "
                         f"could not be read")
    block = re.search(r"^```yaml\n(.*?)^```", after, re.S | re.M)
    if block is None:
        raise ValueError(f"{PAGE}: {EXAMPLE_HEADING!r} is followed by no yaml block")
    parsed = yaml.safe_load(block.group(1))
    if not isinstance(parsed, dict) or not isinstance(parsed.get(testrun.SECTION), dict):
        raise ValueError(f"{PAGE}: the block under {EXAMPLE_HEADING!r} is not a '{testrun.SECTION}' "
                         f"section; it parsed as {type(parsed).__name__}")
    return parsed


def _gates() -> list[dict]:
    """The example's gate list, which every case below mutates one key of."""
    return list(_example_section()[testrun.SECTION]["gates"])


def _refused(data: dict) -> str:
    """The loader's refusal of `data`, or a failure saying it loaded - a manifest that was supposed to be
    refused and was not is the silence these tests are about."""
    try:
        testrun.declared(data, source=SOURCE)
    except ValueError as refused:
        return _flat(str(refused))
    raise AssertionError(f"{SOURCE} loaded; the page quotes a refusal of it")


def test_the_opaque_gate_refusal_the_page_quotes_names_the_page_s_own_third_level():
    """The page's third level is an `impl:` gate, and the page quotes what happens when it also declares
    the two keys the kernel cannot honour on one. Both the INDEX and the NAME in that message come from
    the printed block, so a level renamed or reordered there and not here goes red."""
    # arrange: the page's own section, with 'junit' and 'args' added to its impl gate - the two keys the
    # quote lists, in the order `_gate` lists them
    section = _example_section()
    gates = _gates()
    gates[2] = {**gates[2], "junit": "junit-acceptance.xml", "args": True}
    section[testrun.SECTION]["gates"] = gates

    # act
    message = _refused(section)

    # assert
    assert message in _page(), f"the page quotes something other than:\n  {message}"


def test_the_two_args_gates_refusal_the_page_quotes_lists_the_page_s_own_level_names():
    """At most one gate may take the caller's arguments, and the refusal NAMES the offenders. The page
    quotes that list, so the list has to be the one this section produces.

    The third level is turned into a pytest gate to produce it, and that is not a liberty: an `impl:` gate
    is refused `args` several lines earlier, so a section with two argument-taking gates is necessarily a
    section with two pytest ones. The page's own words for the level survive the change, which is the half
    a rename can break.
    """
    # arrange
    section = _example_section()
    gates = _gates()
    gates[2] = {"name": gates[2]["name"], "suite": "test/acceptance/python",
                "junit": "junit-acceptance.xml", "args": True}
    section[testrun.SECTION]["gates"] = gates

    # act
    message = _refused(section)

    # assert
    assert message in _page(), f"the page quotes something other than:\n  {message}"


def test_the_unknown_level_refusal_the_page_quotes_lists_the_page_s_own_declared_levels():
    """A command pinned to a level the section does not declare is a manifest typo, and the refusal lists
    what IS declared. That list is the page's three level names in the page's own order - the one thing a
    rename touches and a hand-typed quote does not."""
    # arrange: the section exactly as printed, loaded
    cfg = testrun.declared(_example_section(), source=SOURCE)

    # act
    with pytest.raises(ValueError) as refused:
        cfg.gate("sytem")

    # assert
    assert _flat(str(refused.value)) in _page(), (
        f"the page quotes something other than:\n  {refused.value}")


def test_the_example_section_the_page_prints_is_one_the_kernel_would_accept():
    """And the block itself LOADS, which is the claim the three cases above rest on.

    Each of them mutates one key of it and asserts the loader then refuses; that says nothing unless the
    unmutated block is accepted, or every refusal above could be about a defect the page shipped rather
    than about the mutation. Measured here rather than assumed - it is one call.
    """
    # arrange / act
    cfg = testrun.declared(_example_section(), source=SOURCE)

    # assert: three levels, and the third is the opaque one the page's prose is about
    assert [gate.name for gate in cfg.gates] == ["unit", "system", "acceptance"]
    assert cfg.gates[2].impl and not cfg.gates[2].suite
