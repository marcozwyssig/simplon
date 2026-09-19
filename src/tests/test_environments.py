"""Unit tests for simplon.environments.parse - the pure environments.yml -> Registry parsing and
validation with product-supplied valid backends. No I/O; AAA throughout."""
import pytest

from simplon import environments as envs_mod
from simplon.environments import parse, parse_data

_BACKENDS = ("local", "cloud")
_OK = """
default: dev
environments:
  dev:  { backend: local, description: "Local lab." }
  test: { backend: cloud, description: "QA." }
  prod: { backend: cloud }
"""


def test_parse_reads_environments_their_backends_and_the_default():
    # arrange / act
    reg = parse(_OK, _BACKENDS)

    # assert: all three environments, their backends, and the default
    assert set(reg.environments) == {"dev", "test", "prod"}
    assert reg.environments["dev"].backend == "local"
    assert reg.environments["test"].backend == "cloud"
    assert reg.default == "dev"
    assert reg.environments["dev"].description == "Local lab."


def test_parse_defaults_missing_description_to_empty():
    # arrange: prod has no description
    reg = parse(_OK, _BACKENDS)

    # assert
    assert reg.environments["prod"].description == ""


def test_parse_rejects_a_backend_not_in_valid_backends():
    # arrange: a backend outside the product's valid set
    text = "default: dev\nenvironments:\n  dev: { backend: kubernetes }\n"

    # act / assert
    with pytest.raises(ValueError, match="backend"):
        parse(text, _BACKENDS)


def test_parse_rejects_a_default_that_is_not_a_defined_environment():
    # arrange: default points at a non-existent environment
    text = "default: staging\nenvironments:\n  dev: { backend: local }\n"

    # act / assert
    with pytest.raises(ValueError, match="default"):
        parse(text, _BACKENDS)


def test_parse_rejects_an_empty_environment_set():
    # arrange / act / assert
    with pytest.raises(ValueError, match="no environments"):
        parse("default: dev\nenvironments: {}\n", _BACKENDS)


def test_parse_data_builds_the_registry_from_an_already_parsed_mapping():
    # arrange: the one-manifest path hands parse_data an already-loaded dict, not text (no yaml round-trip)
    data = {"default": "dev",
            "environments": {"dev": {"backend": "local", "description": "Local lab."},
                             "prod": {"backend": "cloud"}}}

    # act
    reg = parse_data(data, _BACKENDS)

    # assert: same registry the text form yields, straight from the mapping
    assert set(reg.environments) == {"dev", "prod"}
    assert reg.environments["dev"].backend == "local"
    assert reg.default == "dev"


def test_parse_data_rejects_an_unknown_backend_from_a_mapping():
    # arrange: the same validation applies on the mapping path
    data = {"default": "dev", "environments": {"dev": {"backend": "kubernetes"}}}

    # act / assert
    with pytest.raises(ValueError, match="backend"):
        parse_data(data, _BACKENDS)


# --- si#287: a value that is validated and never handed over ------------------------------------------


_WITH_BOTH_LISTS = {
    "default": "prod",
    "carriers": {"c": {"portainer": {"url_from": "P"}}},
    "environments": {
        "prod": {"backend": "portainer", "carrier": "c", "stack": "s",
                 "repository": {"url": "u"},
                 "required": ["API_URL"], "optional": ["LOG_LEVEL", "APP_TITLE"]},
    },
}


def test_an_environments_optional_names_reach_the_environment_object():
    """THE DEFECT si#287 IS, and it shipped in 0.16.0: `parse_data` read `optional:`, used it in the
    "a name may not be in both lists" refusal, and then left it out of the `Environment` it built. The
    list fell back to its default `()`, so no optional value had ever reached a deployment.

    WHY IT WAS GREEN FOR A RELEASE: nothing in this suite read `Environment.optional`. The list was
    validated, it took part in a refusal, and it appeared in every message that counted it - so at every
    point where somebody looked, it looked processed."""
    env = parse_data(_WITH_BOTH_LISTS, ("portainer",)).environments["prod"]

    assert env.optional == ("LOG_LEVEL", "APP_TITLE")
    assert env.required == ("API_URL",)


def test_the_optional_names_reach_the_far_side_of_the_seam():
    """THE ASSERTION THAT WOULD HAVE CAUGHT IT, and the one above would not have on its own.

    A test written against `parse_data`'s VALIDATION passes on the broken code - validation was never
    what was missing. What was missing is arrival, so this reads the value where a deployment consumes
    it: `stack_values` iterates `(*required, *optional)` and hands the result to Portainer.

    The generalisation this repository states: *what meaning does a value carry on the far side of a seam
    that it did not carry on this side?* Here it carried none, because it never crossed."""
    from simplon import portainer

    env = parse_data(_WITH_BOTH_LISTS, ("portainer",)).environments["prod"]

    values = portainer.stack_values(env, {"API_URL": "https://api.example", "LOG_LEVEL": "debug"})

    assert values == {"API_URL": "https://api.example", "LOG_LEVEL": "debug"}


# NO PASSWORD-SHAPED LITERAL IN THESE FIXTURES, and it is not squeamishness. The first draft of these
# tests paired a password-shaped NAME with a password-shaped VALUE, four times, and the secret scanner
# failed the pull request - correctly, by its own lights. A scanner that could tell a test's stand-in
# from the real thing is the scanner you cannot trust on the day it matters, so the finding stands and
# the fixture moves.
#
# The subject of these tests is whether an OPTIONAL name travels, which `API_URL` says as well as a
# credential did, so nothing is lost. Two things were learned the expensive way and are worth the lines:
# a later commit REMOVING such a literal does not clear the finding, because the scanner reads every
# commit in the pull request and the removal diff carries the string too - the branch has to be rewritten
# so it never appears; and a comment EXPLAINING the incident must not quote it either, or it trips the
# same scanner while apologising to it.


def test_an_optional_name_with_no_value_is_simply_absent():
    """The other half of what `optional:` MEANS, now that it arrives: a name in it travels when it has a
    value and is left out when it does not - no empty string, which a compose document cannot tell from
    a deliberate blank."""
    from simplon import portainer

    env = parse_data(_WITH_BOTH_LISTS, ("portainer",)).environments["prod"]

    values = portainer.stack_values(env, {"API_URL": "https://api.example", "APP_TITLE": "   "})

    assert values == {"API_URL": "https://api.example"}


def test_every_backend_a_matrix_names_can_be_checked_against_what_a_run_resolves():
    """THE SHAPE THAT WOULD HAVE CAUGHT si#293, and the reason it is here rather than over this
    repository's own manifest.

    **simplon declares no `environments:` section at all.** So no assertion over the kernel's own matrix
    could ever have caught this - there is no matrix. The regression was invisible on both sides: this
    suite ran no environment-bound command against a `local` environment with an empty registry, and the
    consumer's suite was 69/69 green because their CI is environment-agnostic. It became visible when a
    person typed `up`.

    The consumer's own repair is the one copied here, and their argument for it is better than the test:
    assert the OUTCOME - every `backend:` in the matrix is in the set the gate resolves against - rather
    than the handle. A test on `backend.register` would have died with any rename and would not have
    caught their fourth environment.

    A product can paste this. Whether the kernel should run it for every product at assembly time is a
    separate question, recorded on si#293 rather than answered here.
    """
    scaffolded = {"default": "dev",
                  "environments": {"dev": {"backend": "local", "description": "the scaffolded one"}}}
    resolvable = {"portainer", envs_mod.LOCAL}

    matrix = parse_data(scaffolded, tuple(resolvable))

    undrivable = {name: env.backend for name, env in matrix.environments.items()
                  if env.backend not in resolvable}

    assert not undrivable, (f"these environments name a backend nothing can resolve: {undrivable} "
                            f"(resolvable: {sorted(resolvable)})")


# --- si#298: the check sits where the kernel needs an instance ----------------------------------------
#
# Measured over the eight manifests this family can reach: ONE product resolves a command to a `deploy:*`
# task, and one calls `backend.register`. The other five have their own `up`, `down` and `install` in an
# env-first group - bodies the kernel does not dispatch and has no registry for. So a gate in `cli.main`
# asked a question about the kernel's dispatch and applied it to commands the kernel never dispatches,
# and both of this week's failures are that mismatch from either end.


def test_a_matrix_is_parsed_against_what_it_itself_declares_by_default():
    """The default that stops one document being valid to one parser and invalid to another.

    si#294, measured by a consumer: the product's provider validated the matrix against its
    `valid_backends` and the kernel re-validated it against the drivable set, so one file was valid and
    invalid at the same time with nowhere to read the two against each other."""
    document = {"default": "dev",
                "environments": {"dev": {"backend": "local"}, "prod": {"backend": "portainer"}}}

    matrix = parse_data(document)

    assert sorted(matrix.environments) == ["dev", "prod"]


def test_a_caller_with_a_narrower_set_still_gets_its_refusal():
    """The default validates nothing the load did not; a caller that genuinely knows less still says so."""
    document = {"default": "dev", "environments": {"dev": {"backend": "local"}}}

    with pytest.raises(ValueError) as exc:
        parse_data(document, ("portainer",))

    assert "local" in str(exc.value)


def test_the_missing_instance_names_the_registration_and_not_the_matrix():
    """THE CONSUMER'S SECOND FINDING. Running a kernel deploy command against an unregistered `local`
    used to produce `parse_data`'s refusal - *"backend must be 'portainer', got 'local'"* - which names a
    REQUIREMENT where the cause is a MISSING REGISTRATION, and sends the reader to the `environments:`
    section while what is missing is a `backend.register` call in the composition root. Their words: it
    sends you to the wrong neighbour.

    `backend.resolve` always had the sentence that fits. It could not be reached, because the re-parse
    refused first."""
    from simplon import backend as backend_mod

    env = envs_mod.Environment("dev", "local", "")

    with pytest.raises(ValueError) as exc:
        backend_mod.resolve(env, {"portainer": object()})

    said = str(exc.value)
    assert "no backend registered for 'local'" in said
    assert "must be" not in said, "the refusal names a requirement again instead of the cause"
