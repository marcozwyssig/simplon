"""si#525: the `toolchains:` list names every toolchain a product uses, the host ones included.

Marco, 2026-10-23: "claude or gh is simply a toolchain that is supported, just like firn." So the list is
the one place that says which are on, and an entry the kernel does not know is refused by name rather than
read as "off" - a misspelt `Claude` that turned Claude support silently off would be the recurring defect.
"""
from __future__ import annotations

import pytest

from simplon.tasks import profiles


def test_absent_toolchains_is_empty():
    assert profiles.declared_toolchains({}) == ()


def test_toolchains_in_order():
    assert profiles.declared_toolchains({"toolchains": ["python", "claude"]}) == ("python", "claude")


def test_not_a_list_is_refused():
    with pytest.raises(ValueError, match="'toolchains' must be a list of toolchain names"):
        profiles.declared_toolchains({"toolchains": "claude"}, source="demo.yaml")


@pytest.mark.parametrize("name", ["Claude", " gh", ""])
def test_unknown_name_names_the_known_ones(name):
    with pytest.raises(ValueError) as caught:
        profiles.declared_toolchains({"toolchains": [name]}, source="demo.yaml")
    assert repr(name) in str(caught.value)
    assert "claude, cpp, dotnet, firn, gh, java, python" in str(caught.value)


def test_duplicate_is_refused():
    with pytest.raises(ValueError, match="names 'gh' twice"):
        profiles.declared_toolchains({"toolchains": ["gh", "gh"]}, source="demo.yaml")


def test_known_toolchains_are_the_profiles_and_the_host_tools():
    assert profiles.known_toolchains() == ("brew", "claude", "cpp", "dotnet", "firn", "gh", "java", "python")
