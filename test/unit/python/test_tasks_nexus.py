"""Unit tests for delivery.tasks.nexus (netctl#1405, framework-free since netctl#1444): the thin body
a product's manifest points its `impl:` at.

The MECHANISM - probe, reconcile, report - is `delivery.nexus` and is covered by test_nexus.py. What is
asserted here is the seam the generator introspects: the payload parameter survives, its annotation is the
one Typer needs to render an optional positional, and nothing in the module raises `typer.Exit` any more.

AAA throughout.
"""
import inspect
from pathlib import Path

from delivery.tasks import nexus as nexus_cmd


def test_nexus_cmd_keeps_its_member_payload_parameter():
    # arrange: the manifest resolves this callable directly and the generator introspects it. The
    # ANNOTATION is load-bearing: `str | None` is what makes the generated wrapper an OPTIONAL positional
    # rather than a required one, and a body without one gets no annotation at all - which Typer reads as
    # a text option.
    # act
    signature = inspect.signature(nexus_cmd.nexus_cmd)

    # assert
    assert list(signature.parameters) == ["member"]
    assert signature.parameters["member"].annotation == "str | None"
    assert signature.parameters["member"].default is None


def test_nexus_cmd_returns_the_dispatch_exit_code_rather_than_raising_typer_exit(monkeypatch):
    # arrange: the point of netctl#1444 - the body is callable from anything, not only a Click parser
    seen = []
    monkeypatch.setattr("delivery.nexus.dispatch", lambda member: seen.append(member) or 3)

    # act
    rc = nexus_cmd.nexus_cmd("status")

    # assert
    assert rc == 3
    assert seen == ["status"]


def test_nexus_cmd_passes_a_missing_member_through_as_none(monkeypatch):
    # arrange: a bare call must reach dispatch as None so it LISTS the members - pure group logic, no
    # default action. Substituting a member here would give the group a silent default.
    seen = []
    monkeypatch.setattr("delivery.nexus.dispatch", lambda member: seen.append(member) or 0)

    # act
    rc = nexus_cmd.nexus_cmd()

    # assert
    assert rc == 0
    assert seen == [None]


def test_the_module_carries_no_typer_import_or_exit():
    # arrange: the metavar and help that used to sit in this signature are manifest `params:` data now,
    # so a framework declaration left behind would state one of them twice and let the two drift
    # act
    source = Path(nexus_cmd.__file__).read_text(encoding="utf-8")

    # assert
    assert "typer.Exit" not in source
    assert "\nimport typer" not in source
