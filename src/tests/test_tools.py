"""Unit tests for tools - the product-owned directory a bootstrapped binary lands in, and putting it
within reach of the running process. Two consumers (docker's static CLI, oras) share this, which is why
the layout convention lives in one place rather than in each of them."""
import os

import pytest

from simplon import context
from simplon import tools


@pytest.fixture(autouse=True)
def _product_context(tmp_path, monkeypatch):
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("cleon", tmp_path, tmp_path / "cleon.yaml"))


def test_the_tool_directory_sits_under_the_product_build_tree(tmp_path):
    # Under build/, because that is what `clean` removes: a bootstrapped binary is a build output.
    directory = tools.bin_dir()

    assert directory == tmp_path / "build" / "tools" / "bin"


def test_a_tool_directory_goes_to_the_front_of_the_path(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin")

    tools.prepend_to_path(tmp_path / "bin")

    assert os.environ["PATH"] == f"{tmp_path / 'bin'}{os.pathsep}/usr/bin"


def test_prepending_twice_does_not_grow_the_path(monkeypatch, tmp_path):
    # A gate may run several times in one process (fetch-bundle, then publish); the PATH must not
    # collect a copy per call.
    monkeypatch.setenv("PATH", "/usr/bin")

    tools.prepend_to_path(tmp_path / "bin")
    tools.prepend_to_path(tmp_path / "bin")

    assert os.environ["PATH"] == f"{tmp_path / 'bin'}{os.pathsep}/usr/bin"
