"""`env_groups:` states a group's shape, so the platform owns it exactly as it owns `env_first:` (si#43).

THE RULE, and it is `merge`'s rule read out loud rather than a new one: a product may add commands and
sub-groups to a platform group, never change its SHAPE. `env_first:` written onto a group the catalogue
declares is refused; `env_groups: [<that group>]` says the same thing from the top level of the same
file, so it has to land the same way.

WHAT IT IS NOT. The reasoning that "env_groups switches ON, never off - the same rule merge enforces on
env_first" does not hold, and this file exists partly to keep it from coming back: `merge` allows no
switching at all, in either direction. It forbids the STATEMENT. An asymmetry between on and off would
be a difference, not the same rule.

WHY THE KEY SURVIVES AT ALL. Where the platform has said nothing about a group - a manifest loaded
without a catalogue, which is how this loader is exercised on its own - `env_groups:` is the manifest's
own statement about its own group, and it still gates. That is the case the key was written for.

WHY EVERY GREEN HERE CARRIES A COUNT. `check_env_groups` returns how many entries it ruled on, because a
manifest with no `env_groups:` at all returns exactly like one whose every entry was checked against the
platform, and only the second is evidence the rule ran. Same reasoning as si#34's placement check, and
the same shape.

AAA throughout, including the negative cases.
"""
import pytest

from simplon import catalogue
from simplon.orchestrator import manifest
from simplon.orchestrator.model import treeform

#: A catalogue that shapes two groups and disagrees with a product about one of them: `build` is
#: explicitly NOT env-first, `deploy` is. Spelled here rather than read from the shipped catalogue so a
#: change to the shipped one cannot quietly turn either case into the other.
_SHAPED = """
taxonomy:
  build:   { help: "Produce the artefacts.", env_first: false }
  deploy:  { help: "Put them somewhere.", env_first: true }
tasks:
  vcs:push: { impl: "simplon.test_impls:nullary", help: "Push." }
"""

#: One command placed in one group, with the group's name and the `env_groups:` entry left open: every
#: case below is that same manifest with the two spellings varied.
_PRODUCT = """
tasks:
  compile: { impl: "simplon.test_impls:nullary", help: "Compile." }

groups:
  GROUP:
    commands:
      compile: { task: "compile" }
env_groups: [LISTED]
"""


def _text(group: str, listed: str) -> str:
    return _PRODUCT.replace("GROUP", group).replace("LISTED", listed)


def test_env_groups_cannot_switch_on_a_group_the_platform_shapes():
    # arrange: the back door itself. The catalogue says `build` is not env-first; the product says it is,
    # through the top-level key rather than through the group node.
    text = _text("build", "build")

    # act / assert: the same refusal `env_first: true` on that node already gets, plus the two values
    with pytest.raises(ValueError) as caught:
        manifest.load(text, catalogue=catalogue.loads(_SHAPED))
    message = str(caught.value)
    assert "env_groups" in message
    assert "the platform's node already sets" in message
    assert "never change its shape" in message


def test_the_back_door_and_the_front_door_are_refused_with_the_same_reason():
    # arrange: `env_first: true` on the node is the front door, and it has always been refused. The two
    # refusals must give the same reason and the same way out, or the back door is merely a second rule.
    front = """
tasks:
  compile: { impl: "simplon.test_impls:nullary", help: "Compile." }

groups:
  build:
    env_first: true
    commands:
      compile: { task: "compile" }
env_groups: []
"""

    # act
    with pytest.raises(ValueError) as back_door:
        manifest.load(_text("build", "build"), catalogue=catalogue.loads(_SHAPED))
    with pytest.raises(ValueError) as front_door:
        manifest.load(front, catalogue=catalogue.loads(_SHAPED))

    # assert: the shared sentence is verbatim in both; only the key named and the added values differ
    shared = ("which the platform's node already sets. A product may add commands and sub-groups to a "
              "platform group, never change its shape - change it in the platform's `groups:` instead, "
              "once, for everybody")
    assert shared in str(back_door.value)
    assert shared in str(front_door.value)


def test_env_groups_agreeing_with_the_platform_is_harmless_and_is_ruled_on():
    # arrange: `deploy` is env-first in the catalogue and the product says so too. Redundant, not wrong -
    # and the count is what separates "checked and agreed" from "never looked".
    text = _text("deploy", "deploy")

    # act
    mf = manifest.load(text, catalogue=catalogue.loads(_SHAPED))
    ruled = treeform.check_env_groups({"deploy": {"env_first": True}}, ("deploy",),
                                      frozenset({"build", "deploy"}))

    # assert
    assert mf.tree["deploy"].env_first is True
    assert mf.taxonomy().group_requires_env("deploy") is True
    assert ruled == 1


def test_env_groups_still_gates_a_group_the_manifest_declares_itself():
    # arrange: no catalogue, so no platform has said anything about `build` - the manifest's own group,
    # and `env_groups:` is the flat way of saying `env_first: true` about it. This is the case the key
    # exists for and it must keep working.
    text = _text("build", "build")

    # act
    mf = manifest.load(text)

    # assert
    assert mf.tree["build"].env_first is True
    assert mf.taxonomy().group_requires_env("build") is True


def test_a_manifest_with_no_env_groups_rules_on_nothing():
    # arrange / act: the green that is NOT evidence, held next to the one that is
    ruled = treeform.check_env_groups({"build": {"env_first": False}}, (), frozenset({"build"}))

    # assert
    assert ruled == 0


def test_an_entry_for_a_group_no_platform_owns_is_not_ruled_on():
    # arrange / act: with no catalogue there is nothing to rule against, so the entry is the manifest's
    # own statement and the count says the rule did not apply
    ruled = treeform.check_env_groups({"build": {"env_first": False}}, ("build",), frozenset())

    # assert
    assert ruled == 0
