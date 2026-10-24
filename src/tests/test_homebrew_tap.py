"""si#536: `release:homebrew-tap` - the tested formula committed to a tap, in three outcomes, against the
real-HTTP stand-in of si#535 (never a mock of PyGithub) and through the real evidence guard
(`results.guarded`), so `tested()` answers what a green record on disk says."""
from __future__ import annotations

import hashlib
import json

import pytest

import githubstandin
from simplon.manifest import context, results
from simplon.tasks import homebrewtap

FORMULA = "build/homebrew/simplon.rb"
MANIFEST = ("product: sample\nartifacts:\n"
            f"  formula: {{ kind: homebrew-formula, path: {FORMULA} }}\n"
            "  checked: { kind: test-result, path: build/results/homebrew.json }\n")
TEXT = ('class Simplon < Formula\n'
        '  url "https://files.pythonhosted.org/packages/ab/cd/simplon-0.37.0-py3-none-any.whl", using: :nounzip\n'
        '  sha256 "' + "aa" * 32 + '"\n'
        'end\n')


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A product with the formula on disk, a green record naming its digest, a running stand-in with
    `GITHUB_API_URL` pointed at it, and an app token in the environment."""
    (tmp_path / "sample.yaml").write_text(MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext("sample", tmp_path, tmp_path / "sample.yaml"))
    path = tmp_path / FORMULA
    path.parent.mkdir(parents=True)
    path.write_text(TEXT, encoding="utf-8")
    _record(tmp_path, "sha256:" + hashlib.sha256(TEXT.encode("utf-8")).hexdigest())
    shared = githubstandin.state()
    base, stop = githubstandin.serve(shared)
    monkeypatch.setenv("GITHUB_API_URL", base)
    monkeypatch.setenv("GH_APP_TOKEN", "app-token")
    try:
        yield shared
    finally:
        stop()


def _record(root, digest: str) -> None:
    path = root / "build" / "results" / "homebrew.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"formula": "simplon", "verdict": 0,
                                "runs": [{"reference": FORMULA, "id": digest, "verdict": 0}]}), encoding="utf-8")


def _tap() -> int:
    return results.guarded(("checked",), lambda: homebrewtap.tap(
        formula="formula", repository=githubstandin.REPO, branch="main"))


def _said(capsys) -> str:
    out = capsys.readouterr()
    return out.out + out.err


@pytest.mark.parametrize("token", ["", "  "])
def test_an_empty_gh_app_token_is_refused_by_name(product, monkeypatch, capsys, token):
    # arrange
    monkeypatch.setenv("GH_APP_TOKEN", token)

    # act
    rc = _tap()

    # assert
    assert rc == 1
    assert "GH_APP_TOKEN" in _said(capsys)
    assert product["requests"] == []


def test_an_unset_gh_app_token_is_refused_by_name(product, monkeypatch, capsys):
    # arrange
    monkeypatch.delenv("GH_APP_TOKEN")

    # act
    rc = _tap()

    # assert
    assert rc == 1
    assert "GH_APP_TOKEN" in _said(capsys)
    assert product["requests"] == []


def test_written_logs_the_commit_and_returns_0(product, capsys):
    # act
    rc = _tap()

    # assert
    assert rc == 0
    puts = [r for r in product["requests"] if r[0] == "PUT"]
    assert len(puts) == 1
    assert puts[0][2]["message"] == "simplon 0.37.0"
    assert product["auth"][0] == "token app-token"
    [commit] = product["commits"]
    assert f"written {commit}" in _said(capsys)


def test_the_path_is_formula_slash_name_rb(product):
    # act
    _tap()

    # assert
    assert product["files"] == {("main", "Formula/simplon.rb"): TEXT.encode("utf-8")}


def test_already_current_returns_0_in_its_own_words(product, capsys):
    # arrange
    product["files"][("main", "Formula/simplon.rb")] = TEXT.encode("utf-8")

    # act
    rc = _tap()

    # assert
    assert rc == 0
    said = _said(capsys)
    assert "already current" in said
    assert "written" not in said and "refused" not in said
    assert [r for r in product["requests"] if r[0] == "PUT"] == []


def test_refused_returns_1_with_the_reason(product, capsys):
    # arrange
    product["fail"][("PUT", f"/repos/{githubstandin.REPO}/contents")] = 403

    # act
    rc = _tap()

    # assert
    assert rc == 1
    said = _said(capsys)
    assert "refused: " in said and "403" in said and "forced 403" in said
    assert "written" not in said and "already current" not in said


def test_a_formula_not_the_tested_one_is_refused(product, tmp_path, capsys):
    # arrange: the record vouches for other bytes - the formula changed after it was tested
    _record(tmp_path, "sha256:" + "bb" * 32)

    # act
    rc = _tap()

    # assert
    assert rc == 1
    said = _said(capsys)
    assert "sha256:" + "bb" * 32 in said
    assert "sha256:" + hashlib.sha256(TEXT.encode("utf-8")).hexdigest() in said
    assert product["requests"] == []


def test_a_formula_with_no_evidence_bound_is_refused(product, capsys):
    # act: called outside the guard, as a command with no `consumes:` for `evidence` runs it
    rc = homebrewtap.tap(formula="formula", repository=githubstandin.REPO, branch="main")

    # assert
    assert rc == 1
    assert "evidence" in _said(capsys)
    assert product["requests"] == []


def test_an_unbound_repository_is_refused_by_name(product):
    with pytest.raises(ValueError, match="repository"):
        results.guarded(("checked",), lambda: homebrewtap.tap(formula="formula", repository="", branch="main"))
    assert product["requests"] == []


def test_a_formula_url_that_names_no_wheel_is_refused(product, tmp_path):
    # arrange
    text = TEXT.replace("simplon-0.37.0-py3-none-any.whl", "simplon.tar.gz")
    (tmp_path / FORMULA).write_text(text, encoding="utf-8")
    _record(tmp_path, "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest())

    # act / assert
    with pytest.raises(ValueError, match="wheel"):
        _tap()
    assert product["requests"] == []
