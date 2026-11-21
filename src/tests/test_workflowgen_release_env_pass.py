"""si#836: in the derived release job, a leaf's `env: pass:` names are filled from `secrets.<NAME>`.

Decided by Marco on 2026-11-21: the general form, no catalogue leaf per registry. firn's Gradle Plugin
Portal publish is a product task with `publishes: true` whose command declares
`env: { pass: [GRADLE_PUBLISH_KEY, GRADLE_PUBLISH_SECRET] }`; the release job hands exactly those names,
from the repository's Actions secrets, to exactly that step.

A secret that is not set would reach the step as an empty string, and the tool would fail later about
something else - or, since a dry run skips a publishing step, not at all until the real run, after the
tag and whatever published before it. So the release job checks, before the cut and on a dry run too,
that every such name is set: `secrets.X != ''` hands the step true or false, never the value (si#574's
mechanism, which does the same for a `token: app` leaf's App secrets).
"""
from __future__ import annotations

import subprocess

import pytest
import yaml

from simplon.manifest import artifactsection
from simplon.manifest import catalogue as catalogue_mod
from simplon.manifest import load as manifest_mod
from simplon.tasks import workflowgen

from test_workflowgen import _RELEASE_PRODUCT, _RELEASE_WORKFLOWS


def gradle(tag: str = "") -> int:
    """The fixture body: a publish that takes the version and does nothing with it."""
    return 0


_CHECK_NAME = "Check the secrets every `env: pass:` step needs"
_SECRETS = ("GRADLE_PUBLISH_KEY", "GRADLE_PUBLISH_SECRET")
_LINE = 'exec ./app.sh release publish-plugin --tag "$RELEASE_VERSION"'


def _product(passes: str = "[GRADLE_PUBLISH_KEY, GRADLE_PUBLISH_SECRET]", token: str = "",
             second: str = "") -> str:
    """The release fixture with firn's shape added: a publishing task, its command passing two names, and
    the command a member of `release all`. `second` adds a non-publishing member passing names of its own."""
    task = ('tasks:\n  gradle: { impl: "test_workflowgen_release_env_pass:gradle", help: "Publish.", '
            f"publishes: true, unattended: true{token} }}\n"
            '  stamp: { impl: "test_workflowgen_release_env_pass:gradle", help: "Stamp.", unattended: true }\n'
            "ci:\n")
    command = f"      publish-plugin: {{ task: gradle, env: {{ pass: {passes} }} }}\n"
    member = ", publish-plugin"
    if second:
        command += f"      stamp: {{ task: stamp, env: {{ pass: {second} }} }}\n"
        member += ", stamp"
    product = _RELEASE_PRODUCT.replace("ci:\n", task, 1).replace("      all:\n", command + "      all:\n", 1)
    return product.replace("tag, gh-publish]", f"tag, gh-publish{member}]")


def _render(product: str) -> str:
    loaded = manifest_mod.load(product, catalogue=catalogue_mod.load(), manifest_path="app.yaml")
    data = {**yaml.safe_load(product), **yaml.safe_load(_RELEASE_WORKFLOWS)}
    return workflowgen.render(workflowgen.parse(data)[0], manifest=loaded, product="app", source="app.yaml",
                              artifacts=artifactsection.declared(data))


def _steps(text: str) -> list[dict]:
    return yaml.safe_load(text)["jobs"]["release"]["steps"]


def _step(text: str, run: str) -> dict:
    return next(step for step in _steps(text) if str(step.get("run", "")).startswith(run))


def _check(text: str) -> "tuple[int, dict] | None":
    found = [(at, step) for at, step in enumerate(_steps(text)) if step.get("name") == _CHECK_NAME]
    return found[0] if found else None


def test_the_publishing_step_gets_exactly_its_own_names_from_the_secrets():
    # act
    leaf = _step(_render(_product()), _LINE)

    # assert
    assert leaf["env"] == {name: f"${{{{ secrets.{name} }}}}" for name in _SECRETS}
    assert leaf["if"] == "${{ !inputs.dry_run }}"


def test_no_other_step_of_the_workflow_sees_the_names():
    """For that step only: no other step's `env:`, not the job's, not the workflow's, and no `run:` line."""
    # act
    text = _render(_product())
    doc = yaml.safe_load(text)

    # assert
    for job_name, job in doc["jobs"].items():
        assert not set(_SECRETS) & set(job.get("env") or {}), job_name
        for step in job["steps"]:
            handed = set(_SECRETS) & set(step.get("env") or {})
            assert not handed or step.get("run", "").startswith(_LINE), step
            assert "secrets." not in str(step.get("run", "")), step
    assert not set(_SECRETS) & set(doc.get("env") or {})


def test_the_release_job_checks_the_names_before_the_cut_and_on_a_dry_run_too():
    # act
    text = _render(_product())

    # assert
    found = _check(text)
    assert found is not None
    at, step = found
    cut = next(i for i, s in enumerate(_steps(text)) if s.get("name") == "Cut the tag in this checkout")
    assert at < cut
    assert "if" not in step
    assert step["env"] == {f"SET_{name}": f"${{{{ secrets.{name} != '' }}}}" for name in _SECRETS}
    assert "secrets." not in step["run"]


@pytest.mark.parametrize("key, secret, rc", [("true", "true", 0), ("false", "true", 1), ("false", "false", 1)])
def test_the_check_is_red_naming_each_secret_that_is_not_set(key, secret, rc):
    """The step's own `run:` text, run by a real bash with the values GitHub's expression gives."""
    _, step = _check(_render(_product()))
    env = {"PATH": "/usr/bin:/bin", "SET_GRADLE_PUBLISH_KEY": key, "SET_GRADLE_PUBLISH_SECRET": secret}

    # act
    done = subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True, text=True)

    # assert
    assert done.returncode == rc
    if rc:
        assert "::error::" in done.stdout
        assert "release publish-plugin" in done.stdout
        assert ("GRADLE_PUBLISH_KEY" in done.stdout) == (key == "false")
        assert ("GRADLE_PUBLISH_SECRET" in done.stdout) == (secret == "false")


def test_a_release_whose_leaves_pass_nothing_checks_nothing():
    assert _check(_render(_RELEASE_PRODUCT)) is None


def test_a_name_two_leaves_pass_is_checked_once_and_handed_to_each():
    # act
    text = _render(_product(second="[GRADLE_PUBLISH_KEY, STAMP_KEY]"))

    # assert
    _, step = _check(text)
    assert list(step["env"]) == ["SET_GRADLE_PUBLISH_KEY", "SET_GRADLE_PUBLISH_SECRET", "SET_STAMP_KEY"]
    assert _step(text, "exec ./app.sh release stamp")["env"] == {
        "GRADLE_PUBLISH_KEY": "${{ secrets.GRADLE_PUBLISH_KEY }}", "STAMP_KEY": "${{ secrets.STAMP_KEY }}"}
    assert "if" not in _step(text, "exec ./app.sh release stamp")


def test_a_token_github_leaf_keeps_the_runs_token_for_github_token():
    """GITHUB_TOKEN is the run's token, handed by `token: github`; passing it too changes nothing and is
    not checked - `secrets.GITHUB_TOKEN` is always set."""
    # act
    text = _render(_product(passes="[GITHUB_TOKEN, GRADLE_PUBLISH_KEY]", token=", token: github"))

    # assert
    assert _step(text, _LINE)["env"] == {"GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}",
                                         "GRADLE_PUBLISH_KEY": "${{ secrets.GRADLE_PUBLISH_KEY }}"}
    _, step = _check(text)
    assert list(step["env"]) == ["SET_GRADLE_PUBLISH_KEY"]


@pytest.mark.parametrize("name", ["GITHUB_TOKEN", "GITHUB_PAT"])
def test_a_github_name_no_secret_can_carry_is_refused(name):
    """GitHub refuses a secret named GITHUB_*, so the check would be red on every run with nothing to set;
    GITHUB_TOKEN is the run's own token, which only a `token: github` leaf is handed (si#490 decision 4)."""
    with pytest.raises(ValueError, match=rf"'release publish-plugin'.*{name}.*GITHUB_.*token: github"):
        _render(_product(passes=f"[{name}]"))


def test_a_token_app_leaf_keeps_the_minted_token_for_gh_app_token():
    """GH_APP_TOKEN is the token the derived step mints for a `token: app` leaf; passing it, which the
    container route needs to carry it, does not also fill it from a secret or check one."""
    # arrange
    product = _product(passes="[GH_APP_TOKEN, GRADLE_PUBLISH_KEY]", token=", token: app").replace(
        "publish-plugin: { task: gradle,", "publish-plugin: { task: gradle, with: { repository: o/plugins },")

    # act
    text = _render(product)

    # assert
    env = _step(text, _LINE)["env"]
    assert set(env) == {"GRADLE_PUBLISH_KEY", "GH_APP_TOKEN"}
    assert env["GRADLE_PUBLISH_KEY"] == "${{ secrets.GRADLE_PUBLISH_KEY }}"
    assert env["GH_APP_TOKEN"].startswith("${{ steps.app-token-")
    _, step = _check(text)
    assert "SET_GH_APP_TOKEN" not in step["env"] and "SET_GRADLE_PUBLISH_KEY" in step["env"]
