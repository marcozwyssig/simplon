"""si#534: a `token: app` leaf gets a GitHub App token, minted for the one repository it names.

A derived step mints it: `actions/create-github-app-token`, pinned, directly before the leaf's step, with the
leaf's own `if:`, so a dry run mints nothing and needs no secret. The leaf step reads the token from that
step's output through its `env:`, and no `run:` line ever carries a secret or the token.
"""
from __future__ import annotations

import re
import textwrap

import pytest
import yaml

from simplon.manifest import artifactsection
from simplon.manifest import catalogue as catalogue_mod
from simplon.manifest import load as manifest_mod
from simplon.tasks import releasepipeline, workflowgen

from test_workflowgen import _RELEASE_PRODUCT, _RELEASE_WORKFLOWS


def tap(repository: str = "") -> int:
    """The fixture body: it takes the repository a `with:` binds and does nothing with it."""
    return 0


_PINNED = "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1"

_PRODUCT = """
product: app
tasks:
  tap: { impl: "test_workflowgen_app_token:tap", help: "Tap.", token: app, unattended: true }
  plain: { impl: "test_workflowgen_app_token:tap", help: "Plain.", unattended: true }
ci:
  release:
    commands:
      tap: { task: tap, with: { repository: marcozwyssig/homebrew-tap } }
      cask: { task: tap, with: { repository: marcozwyssig/homebrew-cask } }
      plain: { task: plain }
      both: { depends_on: [plain, tap], help: "Both." }
"""


def _workflow(steps: str) -> str:
    return textwrap.dedent("""
    workflows:
      ci:
        on: [push]
        jobs:
          ship:
            runs-on: ubuntu-latest
            steps:
    """) + textwrap.indent(textwrap.dedent(steps), " " * 10)


def _render(steps: str, product: str = _PRODUCT) -> str:
    loaded = manifest_mod.load(product, catalogue=catalogue_mod.load(), manifest_path="app.yaml")
    picked = workflowgen.parse(yaml.safe_load(_workflow(steps)))[0]
    return workflowgen.render(picked, manifest=loaded, product="app", source="app.yaml", artifacts={})


def _steps(text: str, job: str = "ship") -> list[dict]:
    return yaml.safe_load(text)["jobs"][job]["steps"]


def _token_and_leaf(steps: list[dict], line: str) -> tuple[dict, dict]:
    at = next(i for i, step in enumerate(steps) if step.get("run", "").startswith(f"exec {line}"))
    return steps[at - 1], steps[at]


def test_secret_prefix_is_the_repository_name_upper_snake():
    assert workflowgen.secret_prefix("marcozwyssig/homebrew-tap") == "HOMEBREW_TAP"


def test_a_product_job_step_gets_the_token_step_before_it():
    token, leaf = _token_and_leaf(_steps(_render("- command: release tap\n")), "./app.sh release tap")

    assert token["uses"] == _PINNED
    assert token["with"] == {"client-id": "${{ secrets.HOMEBREW_TAP_CLIENT_ID }}",
                             "private-key": "${{ secrets.HOMEBREW_TAP_APP_KEY }}",
                             "owner": "marcozwyssig", "repositories": "homebrew-tap",
                             "permission-contents": "write"}
    assert leaf["env"] == {"GH_APP_TOKEN": f"${{{{ steps.{token['id']}.outputs.token }}}}"}


def test_the_pin_carries_its_version_as_a_comment():
    text = _render("- command: release tap\n")
    lines = text.splitlines()
    at = next(i for i, line in enumerate(lines) if _PINNED in line)
    assert any("v3.2.0" in line for line in lines[max(0, at - 12):at] if line.strip().startswith("#"))


def test_the_derived_release_job_gets_the_token_step_too():
    product = (_RELEASE_PRODUCT
               .replace("ci:\n", 'tasks:\n  tap: { impl: "test_workflowgen_app_token:tap", help: "Tap.", '
                                 "token: app, unattended: true, publishes: true }\nci:\n", 1)
               .replace("      all:\n", "      tap: { task: tap, with: { repository: marcozwyssig/homebrew-tap } }\n"
                                       "      all:\n", 1)
               .replace("tag, gh-publish]", "tag, gh-publish, tap]"))
    loaded = manifest_mod.load(product, catalogue=catalogue_mod.load(), manifest_path="app.yaml")
    data = {**yaml.safe_load(product), **yaml.safe_load(_RELEASE_WORKFLOWS)}
    text = workflowgen.render(_released(loaded, data), manifest=loaded, product="app", source="app.yaml",
                              artifacts=artifactsection.declared(data))

    token, leaf = _token_and_leaf(_steps(text, "release"), "./app.sh release tap")
    assert token["uses"] == _PINNED
    assert token["with"]["repositories"] == "homebrew-tap"
    assert leaf["env"] == {"GH_APP_TOKEN": f"${{{{ steps.{token['id']}.outputs.token }}}}"}
    # The leaf publishes, so a dry run skips it, and the token step with it.
    assert leaf["if"] == token["if"] == "${{ !inputs.dry_run }}"


def test_the_token_step_carries_the_leaf_steps_if():
    token, leaf = _token_and_leaf(
        _steps(_render("- command: release tap\n  if: ${{ !inputs.dry_run }}\n")), "./app.sh release tap")
    assert leaf["if"] == "${{ !inputs.dry_run }}"
    assert token["if"] == "${{ !inputs.dry_run }}"


def test_the_leaf_steps_own_env_is_kept():
    _, leaf = _token_and_leaf(_steps(_render("- command: release tap\n  env: { MODE: fast }\n")),
                              "./app.sh release tap")
    assert leaf["env"]["MODE"] == "fast" and "GH_APP_TOKEN" in leaf["env"]


def test_no_secret_reaches_a_run_line():
    steps = _steps(_render("- command: release tap\n- command: release cask\n"))
    runs = [str(step["run"]) for step in steps if "run" in step]
    assert runs
    assert not [run for run in runs if "secrets." in run or "GH_APP_TOKEN" in run]


def test_two_app_token_steps_in_one_job_have_distinct_ids():
    steps = _steps(_render("- command: release tap\n- command: release cask\n"))
    ids = [step["id"] for step in steps if step.get("uses") == _PINNED]
    assert len(ids) == 2 and len(set(ids)) == 2
    first, second = (_token_and_leaf(steps, f"./app.sh release {leaf}") for leaf in ("tap", "cask"))
    assert second[0]["with"]["repositories"] == "homebrew-cask"
    assert first[1]["env"]["GH_APP_TOKEN"] != second[1]["env"]["GH_APP_TOKEN"]


def test_a_step_without_an_app_leaf_gets_no_token_step():
    steps = _steps(_render("- command: release plain\n"))
    assert not [step for step in steps if step.get("uses") == _PINNED]
    assert not [step for step in steps if "GH_APP_TOKEN" in (step.get("env") or {})]


def test_a_token_app_leaf_without_repository_is_refused():
    product = _PRODUCT.replace("tap: { task: tap, with: { repository: marcozwyssig/homebrew-tap } }",
                               "tap: { task: tap }")
    with pytest.raises(ValueError, match="'release tap'") as exc:
        _render("- command: release tap\n", product)
    assert "repository: <owner>/<repo>" in str(exc.value)


@pytest.mark.parametrize("repository", ["homebrew-tap", "a/b/c", "/x"])
def test_a_repository_not_owner_slash_repo_is_refused(repository):
    product = _PRODUCT.replace("marcozwyssig/homebrew-tap", repository)
    with pytest.raises(ValueError, match=re.escape("<owner>/<repo>")) as exc:
        _render("- command: release tap\n", product)
    assert repr(repository) in str(exc.value) or repository in str(exc.value)


def test_an_aggregate_step_with_an_app_leaf_is_refused_in_a_product_job():
    with pytest.raises(ValueError, match="run 'release tap' as its own step"):
        _render("- command: release both\n")


def test_a_step_that_declares_gh_app_token_itself_is_refused():
    with pytest.raises(ValueError, match="GH_APP_TOKEN"):
        _render("- command: release tap\n  env: { GH_APP_TOKEN: mine }\n")


def test_a_step_env_that_is_not_a_mapping_is_refused():
    with pytest.raises(ValueError, match=r"'release tap'.*`env:` must be a mapping"):
        _render('- command: release tap\n  env: "${{ fromJSON(vars.E) }}"\n')


@pytest.mark.parametrize("repository, prefix", [("homebrew-tap", "HOMEBREW_TAP"),
                                                ("owner.github.io", "OWNER_GITHUB_IO")])
def test_secret_prefix_maps_what_a_secret_name_cannot_carry(repository, prefix):
    assert workflowgen.secret_prefix(f"marcozwyssig/{repository}") == prefix
    token, _ = _token_and_leaf(_steps(_render("- command: release tap\n",
                                              _PRODUCT.replace("homebrew-tap", repository))),
                               "./app.sh release tap")
    assert token["with"]["client-id"] == f"${{{{ secrets.{prefix}_CLIENT_ID }}}}"


@pytest.mark.parametrize("repository, prefix", [("1tap", "1TAP"), ("github-tap", "GITHUB_TAP")])
def test_a_prefix_github_forbids_is_refused(repository, prefix):
    with pytest.raises(ValueError, match=re.escape(f"marcozwyssig/{repository}")) as exc:
        _render("- command: release tap\n", _PRODUCT.replace("homebrew-tap", repository))
    assert prefix in str(exc.value)


def test_the_note_mentions_the_if_only_when_one_is_copied():
    plain = _render("- command: release tap\n")
    guarded = _render("- command: release tap\n  if: ${{ !inputs.dry_run }}\n")
    assert "carries the leaf's `if:`" not in plain
    assert "carries the leaf's `if:`" in guarded


# --- si#574: the release's dry run is red when a secret a `token: app` step needs is not set -----------------

_TAP_TASK = ('tasks:\n  tap: { impl: "test_workflowgen_app_token:tap", help: "Tap.", '
             "token: app, unattended: true, publishes: true }\nci:\n")
_TAP_COMMAND = "      tap: { task: tap, with: { repository: marcozwyssig/homebrew-tap } }\n      all:\n"
_CHECK_NAME = "Check the secrets every `token: app` step needs"

_TAP_JOB = """      tap-job:
        runs-on: ubuntu-latest
        needs: release
        steps: [{ command: release tap }]
"""


def _release_with_tap(*, in_release: bool, job: str = "") -> str:
    """The release workflow with a `token: app` leaf: a member of the aggregate (the derived job runs it), or
    the one step of a product job beside the derived one, which is simplon's own homebrew-tap shape."""
    product = _RELEASE_PRODUCT.replace("ci:\n", _TAP_TASK, 1).replace("      all:\n", _TAP_COMMAND, 1)
    if in_release:
        product = product.replace("tag, gh-publish]", "tag, gh-publish, tap]")
    return _render_release(product, _RELEASE_WORKFLOWS + job)


def _render_release(product: str = _RELEASE_PRODUCT, workflows: str = _RELEASE_WORKFLOWS) -> str:
    loaded = manifest_mod.load(product, catalogue=catalogue_mod.load(), manifest_path="app.yaml")
    data = {**yaml.safe_load(product), **yaml.safe_load(workflows)}
    return workflowgen.render(_released(loaded, data), manifest=loaded, product="app", source="app.yaml",
                              artifacts=artifactsection.declared(data))


def _released(loaded, data) -> "workflowgen.Workflow":
    """si#862: the release entry as `cipipeline.workflows` hands it to the renderer, derived through the model."""
    entry = workflowgen.parse(data)[0]
    return releasepipeline.to_workflow(releasepipeline.derive(loaded, data, entry), loaded, data, entry, product="app")


def _check(text: str) -> "tuple[int, dict] | None":
    found = [(at, step) for at, step in enumerate(_steps(text, "release")) if step.get("name") == _CHECK_NAME]
    return found[0] if found else None


@pytest.mark.parametrize("in_release, job", [(True, ""), (False, _TAP_JOB)],
                         ids=["leaf-in-the-derived-job", "leaf-in-a-product-job"])
def test_the_release_job_checks_the_app_secrets_first_and_on_a_dry_run_too(in_release, job):
    """si#574: v0.37.0's dry run was green because it skips the one step that needs the secrets; the real run
    then stopped after PyPI. The check reads `secrets.X != ''`, never the value, and carries no `if:`."""
    # act
    text = _release_with_tap(in_release=in_release, job=job)

    # assert
    found = _check(text)
    assert found is not None
    at, step = found
    steps = _steps(text, "release")
    cut = next(i for i, s in enumerate(steps) if s.get("name") == "Cut the tag in this checkout")
    assert at < cut
    assert "if" not in step
    assert step["env"] == {"SET_HOMEBREW_TAP_CLIENT_ID": "${{ secrets.HOMEBREW_TAP_CLIENT_ID != '' }}",
                           "SET_HOMEBREW_TAP_APP_KEY": "${{ secrets.HOMEBREW_TAP_APP_KEY != '' }}"}
    assert "secrets." not in step["run"]


def test_a_release_with_no_app_leaf_checks_no_secret():
    assert _check(_render_release()) is None


def test_a_leaf_in_a_job_with_an_environment_is_not_checked_and_the_file_says_so():
    """An environment's secrets are visible only to a job that names it, so the release job cannot read them:
    a check there would be red with the secret set. Not checked, and said in the release job."""
    # act
    text = _release_with_tap(in_release=False, job=_TAP_JOB + "        environment: tap\n")

    # assert
    assert _check(text) is None
    release_job = text.split("\njobs:")[1].split("\n  announce:")[0]      # its note stands above it
    assert "si#574" in release_job and "tap-job" in release_job and "environment" in release_job


@pytest.mark.parametrize("client, key, rc", [("true", "true", 0), ("false", "true", 1), ("false", "false", 1)])
def test_the_check_is_red_naming_each_secret_that_is_not_set(client, key, rc):
    """The step's own `run:` text, run by a real bash with the values GitHub's expression gives."""
    import subprocess
    _, step = _check(_release_with_tap(in_release=True))
    env = {"PATH": "/usr/bin:/bin", "SET_HOMEBREW_TAP_CLIENT_ID": client, "SET_HOMEBREW_TAP_APP_KEY": key}

    # act
    done = subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True, text=True)

    # assert
    assert done.returncode == rc
    if rc:
        assert "::error::" in done.stdout
        assert ("HOMEBREW_TAP_CLIENT_ID" in done.stdout) == (client == "false")
        assert ("HOMEBREW_TAP_APP_KEY" in done.stdout) == (key == "false")
