"""The `sources:` section (si#873): the submodules a product's jobs check out, and what refuses a bad one at LOAD.
AAA throughout."""
import pytest

from simplon.manifest import load as manifest
from simplon.manifest import sources
from simplon.manifest.sources import Source

from test_manifest import _OK


def test_sources_reads_submodule_and_secret():
    # arrange
    document = {"sources": [{"submodule": "lib/platform", "secret": "PLATFORM_REPO_TOKEN"}]}

    # act / assert
    assert sources.declared(document) == (Source("lib/platform", "PLATFORM_REPO_TOKEN"),)


def test_secret_is_optional():
    # act
    declared = sources.declared({"sources": [{"submodule": "lib/public"}]})

    # assert: a public submodule needs no token, and the empty string is how the tuple says so
    assert declared == (Source("lib/public", ""),)


def test_absent_section_is_empty():
    assert sources.declared({"product": "demo"}) == ()


def test_entries_keep_their_declared_order():
    # arrange
    document = {"sources": [{"submodule": "b"}, {"submodule": "a", "secret": "A_TOKEN"}]}

    # act / assert
    assert [s.submodule for s in sources.declared(document)] == ["b", "a"]


@pytest.mark.parametrize("section,message", [
    ("lib/platform", "`sources:` must be a list"),
    ({"submodule": "x"}, "`sources:` must be a list"),
    (["lib/platform"], "'sources\\[0\\]' is not a mapping"),
    ([{"submodule": "x", "token": "T"}], "unknown key 'token'.*submodule, secret"),
    ([{"secret": "T"}], "'sources\\[0\\]' declares no `submodule:`"),
    ([{"submodule": ""}], "`submodule:` must be a non-empty relative path"),
    ([{"submodule": 3}], "`submodule:` must be a non-empty relative path"),
    ([{"submodule": "/abs/path"}], "`submodule:` must be a non-empty relative path"),
    ([{"submodule": "lib/../x"}], "must not contain '..'"),
    ([{"submodule": "x", "secret": "9BAD"}], "`secret:` must be a variable name"),
    ([{"submodule": "x", "secret": "has-dash"}], "`secret:` must be a variable name"),
    ([{"submodule": "x", "secret": 4}], "`secret:` must be a variable name"),
    ([{"submodule": "x"}, {"submodule": "x"}], "names the submodule 'x' twice"),
])
def test_a_bad_section_is_refused_with_where_and_what(section, message):
    # act / assert
    with pytest.raises(ValueError, match=message):
        sources.declared({"sources": section})


def test_a_manifest_with_a_bad_sources_section_does_not_load():
    # act / assert: refused by the loader, before any command runs
    with pytest.raises(ValueError, match="unknown key 'token'"):
        manifest.load(_OK + "sources:\n  - { submodule: lib/platform, token: X }\n")


def test_a_manifest_with_a_good_sources_section_loads():
    # act
    loaded = manifest.load(_OK + "sources:\n  - { submodule: lib/platform, secret: PLATFORM_REPO_TOKEN }\n")

    # assert
    assert set(loaded.commands) == {"code", "build", "deploy"}
