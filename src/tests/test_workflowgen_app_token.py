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
from simplon.tasks import workflowgen

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
    at = next(i for i, step in enumerate(steps) if step.get("run", "").startswith(line))
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
    text = workflowgen.render(workflowgen.parse(data)[0], manifest=loaded, product="app", source="app.yaml",
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
