"""The handover chapter, against the catalogue and against the code it describes (si#127, si#128).

WHY THIS PAGE IS GUARDED AND MOST PROSE IS NOT. Two of its claims are the kind that go quietly wrong.

The first is the COORDINATE LIST. A page that names four of five commands stays right about everything
it does say, and si#46 measured that failure on this very site: the descriptions beside the coordinates
in `building/phases.md` had drifted and nobody had compared them.

The second is the SENTENCE THAT STOPS A WRONG ASSUMPTION. si#128's whole warning is that a reader who
sees "Conan packages in GitHub Packages" will assume a remote and be wrong, and the ticket asks for that
to be said in as many words. A warning is worth exactly as much as its presence, so its presence is
asserted rather than trusted - and asserted against the same words the module's own docstring uses, so
the page and the code cannot say different things.

WHAT IS NOT CHECKED: the prose. Whether an explanation explains is not derivable, and a rule about how
a sentence may be worded is the thing si#46 rejected.
"""
from __future__ import annotations

import pathlib

from simplon import catalogue as catalogue_mod

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / "site" / "content" / "using" / "handing-a-package-over.md"

#: The coordinates si#127 and si#128 added. Read from the catalogue below rather than trusted from here;
#: this is the set the page is ABOUT, and a sixth one arriving is a page that has to grow a paragraph.
HANDOVER = ("release:nuget", "release:conan",
            "build:nuget-config", "build:nuget-restore", "build:conan-cache")


def _text() -> str:
    """The chapter, refusing to be empty: every assertion below reads it, and a blank page would pass
    a `not in` check just as happily as a correct one."""
    body = PAGE.read_text(encoding="utf-8")
    assert body.strip(), f"{PAGE} is empty"
    return body


def test_the_five_coordinates_it_documents_are_all_real():
    """A page naming a coordinate the catalogue does not carry is fiction, however well written."""
    # arrange
    tasks = catalogue_mod.load().tasks

    # assert
    for coordinate in HANDOVER:
        assert coordinate in tasks, f"the page documents {coordinate}, which the catalogue does not carry"


def test_the_page_names_every_one_of_them():
    """The other direction, which is the one that rots: a coordinate lands and the page keeps describing
    the four it knew about."""
    # act
    body = _text()

    # assert
    missing = [c for c in HANDOVER if f"`{c}`" not in body]
    assert missing == [], f"the handover chapter does not mention {missing}"


def test_the_page_says_there_is_no_conan_registry_in_github_packages():
    """si#128's first sentence, and the fact the whole design follows from."""
    assert "GitHub Packages has no Conan registry" in _text()


def test_the_page_refuses_the_word_a_reader_would_otherwise_supply():
    """A transport, not a remote - said with all four consequences spelled out, because a reader who
    assumes a remote will not discover the difference until somebody else's build fails."""
    # act
    body = _text().lower()

    # assert
    assert "transport, not a remote" in body
    for consequence in ("no `conan install` resolution", "no version ranges",
                        "no dependency graph is solved remotely", "exact tag"):
        assert consequence in body, f"the page does not say: {consequence}"


def test_the_page_and_the_module_agree_that_conan_has_no_oci_remote():
    """The measurement is in two places on purpose - a docstring the next maintainer reads and a page the
    next USER reads - so this holds them to the same answer. A Conan release that grew an OCI remote
    would make both wrong on the same day, and that is exactly when both should be edited."""
    # arrange
    from simplon.tasks import conan

    # assert
    assert "local-recipes-index" in _text()
    assert "local-recipes-index" in (conan.__doc__ or "")


def test_the_page_says_the_generated_config_carries_no_token():
    """si#127's one security requirement, stated where the person who will commit that file reads it."""
    # act
    body = _text()

    # assert
    assert "%GITHUB_TOKEN%" in body
    assert "holds no token" in body


def test_the_page_carries_the_two_inherited_dotnet_facts():
    """Both cost a measurement in si#102, and both fail in a way that names neither: a permission denial
    on a path nobody chose, and an rc 150 from a build that succeeded."""
    # act
    body = _text()

    # assert
    assert "DOTNET_CLI_HOME" in body
    assert "rc 150" in body


def test_the_page_quotes_the_command_that_grants_the_package_scopes():
    """The advice is one string in the kernel (`githubpackages.scope_advice`), and a page that
    paraphrased it would be the second source si#46 spent a ticket removing."""
    # arrange
    from simplon import githubpackages

    # act
    body = _text()

    # assert
    assert f"gh auth refresh -h github.com -s {','.join(githubpackages.PACKAGE_SCOPES)}" in body
