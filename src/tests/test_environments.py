"""Unit tests for simplon.environments.parse - the pure environments.yml -> Registry parsing and
validation with product-supplied valid backends. No I/O; AAA throughout."""
import pytest

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


# --- si#288: the CD gate asks whether a backend can be DRIVEN -----------------------------------------


def _provider(backend_name: str):
    """A provider whose one environment carries `backend_name`, built the way `cli.main` builds one."""
    from simplon import environments as env_mod

    class _One(env_mod.Provider):
        def current(self, name=None):
            return env_mod.Environment("prod", backend_name, "")

    return _One("X_ENV", shim="", valid_backends=(backend_name,))


def test_a_backend_the_run_can_resolve_passes_the_gate():
    """THE DEFECT si#288 IS. The gate asked `is_local` and then demanded `LOCAL`, so every command in
    `deploy` and `monitor` died for a non-local environment - `deploy up` included. The kernel shipped a
    portainer backend in 0.16.0 that its own CLI would not let anybody reach, and every product adopting
    it needed a `Provider` subclass to get past the kernel."""
    _provider("portainer").require_drivable(("portainer", "local"))


def test_a_backend_nobody_implemented_still_dies_clean():
    """WHAT #11 MEANT TO REFUSE, unchanged. A CD command aimed at a target nobody has implemented must
    fail here rather than mis-run another backend's path."""
    import pytest as _pytest

    with _pytest.raises(SystemExit):
        _provider("exoscale").require_drivable(("portainer", "local"))


def test_the_refusal_names_what_this_run_can_drive_and_how_to_add_one(capsys):
    """A refusal that says "wrong backend" sends a reader off to guess which ones are right. This is the
    only place they can learn it: the set is assembled at run time from what the kernel ships plus what
    the product registered, so it is in no document."""
    import pytest as _pytest

    with _pytest.raises(SystemExit):
        _provider("exoscale").require_drivable(("portainer", "local"))

    captured = capsys.readouterr()
    said = captured.out + captured.err
    assert "exoscale" in said
    assert "portainer" in said and "local" in said
    assert "simplon.backend.register" in said


def test_the_gate_reads_the_same_set_deploy_up_resolves_against():
    """THE JOIN, and the reason `_backends` became public. A gate computing its own list would be a
    second source for "what can this run drive", and the two would disagree the day a product registered
    something - the gate refusing what `deploy up` would happily have driven."""
    from simplon.tasks import deploy

    assert "portainer" in deploy.drivable_backends()
