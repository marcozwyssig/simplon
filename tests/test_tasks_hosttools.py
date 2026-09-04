"""Unit tests for simplon.tasks.hosttools - `support install`, the command that provisions the host
tooling the kernel itself cannot work without. Nothing here installs anything: every gate is
monkeypatched, so the suite proves what the command DECIDES and reports. AAA throughout.
"""
import pytest

from simplon import context, oras
from simplon.context import ProductContext
from simplon.tasks import hosttools


@pytest.fixture(autouse=True)
def _registered_context(monkeypatch, tmp_path):
    monkeypatch.setattr(context, "_current",
                        ProductContext("sample", tmp_path / "repo", tmp_path / "sample.yaml"))


def test_it_provisions_oras(monkeypatch):
    # arrange
    provisioned = []
    monkeypatch.setattr(oras, "ensure_oras", lambda: provisioned.append(1))

    # act
    rc = hosttools.install()

    # assert
    assert provisioned == [1]
    assert rc == 0


def test_a_tool_that_could_not_be_provided_is_reported_as_a_failed_command(monkeypatch):
    # arrange: the gate exhausted package manager AND download
    def refuse():
        raise oras.OrasError("no oras and no way to get one")
    monkeypatch.setattr(oras, "ensure_oras", refuse)

    # act
    rc = hosttools.install()

    # assert: a non-zero exit, not a traceback - this is a command, not a library call
    assert rc == 1
