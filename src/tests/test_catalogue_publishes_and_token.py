"""si#490: `publishes:` and `token:` - which tasks a dry run skips, and which steps are handed GITHUB_TOKEN.

Both are facts about a task's BODY, declared once in the catalogue beside `unattended:` and inherited by
every command that instantiates the task, for `unattended`'s reason (si#267). A derived release workflow
reads them: a `publishes: true` leaf gets `if: ${{ !inputs.dry_run }}`, a `token: github` leaf gets the
workflow's token in its step `env:` - and no other step sees it.

A field is only as good as the population that carries it, so two tests here hold the population: every
`release:` task says whether it publishes, and the token is declared exactly where a body authenticates
to GitHub.
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest

from simplon.manifest import catalogue
from simplon.manifest import load as manifest
from simplon.tasks import workflowgen
from conftest import ROOT

#: The `release:` tasks that publish nothing: they read (the merges, the API) and write only the checkout.
#: A new `release:` task is in neither set until somebody says which it is - that is the point.
PUBLISH_READS = frozenset({"release:notes", "release:github-unpublished"})

#: How a body authenticates to GitHub, read off its module's source: the packages adapter, the Releases
#: adapter (directly or through `githubrelease`), or the `gh` CLI, which reads GITHUB_TOKEN too.
_AUTHENTICATES = re.compile(r"githubpackages|from simplon\.adapters import[^\n]*\bgithub\b|githubrelease"
                            r"|\[\"gh\",")

#: How a body authenticates with the GitHub App token a `token: app` step is handed (si#534): it reads the
#: variable by its name. Such a body may import the `github` adapter too (`adapters.repofile` does, one hop
#: away), and the app token is what it is handed, so the app check is asked first.
_READS_APP_TOKEN = re.compile(re.escape(f'"{workflowgen.APP_TOKEN_ENV}"'))


def _loaded(text: str):
    return manifest.load(textwrap.dedent(text), catalogue=catalogue.load())


def _body_source(impl: str) -> str:
    """The source of the module a catalogue task's body lives in: the generated class names it as `_body`."""
    module = impl.split(":", 1)[0]
    generated = (ROOT / "src" / Path(*module.split("."))).with_suffix(".py").read_text()
    found = re.search(r"from (simplon\.[\w.]+) import \w+ as _body", generated)
    body = found.group(1) if found else module
    return (ROOT / "src" / Path(*body.split("."))).with_suffix(".py").read_text()


def test_a_task_field_publishes_reaches_the_command_that_instantiates_it():
    loaded = _loaded("""
        tasks:
          ship: { impl: "simplon.test_impls:nullary", help: "Ship.", unattended: true, publishes: true,
                  token: github }
        ci:
          release:
            commands:
              ship: { task: ship }
              tag: { task: "release:tag" }
              notes: { task: "release:notes" }
        """)

    ship = loaded.commands["release"]["ship"]
    assert (ship.publishes, ship.token) == (True, "github")
    assert loaded.commands["release"]["tag"].publishes is True
    assert (loaded.commands["release"]["notes"].publishes, loaded.commands["release"]["notes"].token) == (False, "")


def test_publishes_is_true_or_false():
    with pytest.raises(ValueError, match="'publishes' is true or false"):
        _loaded("""
            tasks:
              ship: { impl: "simplon.test_impls:nullary", help: "Ship.", publishes: "yes" }
            ci:
              release:
                commands:
                  ship: { task: ship }
            """)


def test_token_names_a_known_issuer():
    with pytest.raises(ValueError, match="'token' is github, app or absent"):
        _loaded("""
            tasks:
              ship: { impl: "simplon.test_impls:nullary", help: "Ship.", token: gitlab }
            ci:
              release:
                commands:
                  ship: { task: ship }
            """)


def test_token_app_is_a_known_issuer():
    loaded = _loaded("""
        tasks:
          ship: { impl: "simplon.test_impls:nullary", help: "Ship.", token: app }
        ci:
          release:
            commands:
              ship: { task: ship }
        """)

    assert loaded.commands["release"]["ship"].token == "app"


def test_every_release_task_says_whether_it_publishes():
    """A publishing task that forgets the field runs on a rehearsal - the cost the decision of 2026-10-17
    accepted, and the reason this test exists: a new `release:` task has to be put in one set or the other."""
    tasks = catalogue.load().tasks
    release = {key for key in tasks if key.startswith("release:")}
    publishing = {key for key in release if tasks[key].get("publishes") is True}

    assert not publishing & PUBLISH_READS
    assert release - publishing - PUBLISH_READS == set(), (
        "these release tasks say neither `publishes: true` nor are listed as reads")
    assert PUBLISH_READS <= release


def test_token_is_declared_exactly_where_a_release_body_authenticates_to_github():
    """Scoped to `release:` (ruling of si#490 Task 1): a build or vcs body imports the packages adapter too,
    for a pull or a scope grant, and a release job's build step is exactly where the token must NOT go."""
    tasks = catalogue.load().tasks
    for key, spec in sorted(tasks.items()):
        source = _body_source(spec["impl"]) if key.startswith("release:") else ""
        wanted = ("app" if _READS_APP_TOKEN.search(source)
                  else "github" if _AUTHENTICATES.search(source) else None)
        assert spec.get("token") == wanted, (
            f"{key}: its body {'authenticates' if wanted else 'does not authenticate'} to GitHub"
            f"{f' with the {wanted} token' if wanted else ''}, and its `token:` is {spec.get('token')!r}")
