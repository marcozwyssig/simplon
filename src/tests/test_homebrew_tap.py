"""si#536: `release:homebrew-tap` - the tested formula committed to a tap, in three outcomes, against the
real-HTTP stand-in of si#535 (never a mock of PyGithub) and through the real evidence guard
(`results.guarded`), so `tested()` answers what a green record on disk says."""
from __future__ import annotations

import hashlib
import json

import pytest

import githubstandin
from simplon.manifest import context, results
from simplon.tasks import homebrewformula as hf
from simplon.tasks import homebrewtap
from test_homebrew_build import _release, pypi  # noqa: F401 - `pypi` is a fixture
from test_homebrew_check import failing_index  # noqa: F401 - a fixture

FORMULA = "build/homebrew/simplon.rb"
MANIFEST = ("product: sample\nartifacts:\n"
            f"  formula: {{ kind: homebrew-formula, path: {FORMULA} }}\n"
            "  checked: { kind: test-result, path: build/results/homebrew.json }\n")
TEXT = ('class Simplon < Formula\n'
        '  url "https://files.example/simplon-0.37.0-py3-none-any.whl", using: :nounzip\n'
        '  sha256 "' + "aa" * 32 + '"\n'
        'end\n')
WHEEL = "simplon-0.37.0-py3-none-any.whl"
PYPI_ROUTE = "/pypi/simplon/0.37.0/json"


@pytest.fixture
def product(tmp_path, monkeypatch, pypi):  # noqa: F811
    """A product with the formula on disk, a green record naming its digest, a running stand-in with
    `GITHUB_API_URL` pointed at it, an app token in the environment, and PyPI listing the formula's wheel
    with the formula's sha256."""
    pypi[PYPI_ROUTE] = _release((WHEEL, "aa" * 32))
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
    _formula(tmp_path, TEXT.replace(WHEEL, "simplon.tar.gz"))

    # act / assert
    with pytest.raises(ValueError, match="wheel"):
        _tap()
    assert product["requests"] == []


def _formula(tmp_path, text: str) -> None:
    """`text` as the formula on disk, with a green record that names exactly these bytes."""
    (tmp_path / FORMULA).write_text(text, encoding="utf-8")
    _record(tmp_path, "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest())


def test_a_dry_run_placeholder_formula_is_refused_before_github_is_asked(product, tmp_path, capsys):
    # arrange: a dry-run build, tested green with online false, then released by hand
    _formula(tmp_path, TEXT.replace("https://files.example/", hf.PLACEHOLDER))

    # act
    rc = _tap()

    # assert
    assert rc == 1
    said = _said(capsys)
    assert f"{FORMULA} carries the dry-run placeholder url" in said
    assert "source: pypi" in said and "online: true" in said
    assert product["requests"] == []


def test_a_sha256_pypi_does_not_serve_is_refused_naming_both(product, pypi, capsys):  # noqa: F811
    # arrange: the evidence ran with online false, so nothing compared the formula with PyPI
    pypi[PYPI_ROUTE] = _release((WHEEL, "ee" * 32))

    # act
    rc = _tap()

    # assert
    assert rc == 1
    said = _said(capsys)
    assert "ee" * 32 in said and "aa" * 32 in said
    assert [r for r in product["requests"] if r[0] == "PUT"] == []


def test_a_wheel_pypi_does_not_list_is_refused(product, pypi, capsys):  # noqa: F811
    # arrange
    del pypi[PYPI_ROUTE]

    # act
    rc = _tap()

    # assert
    assert rc == 1
    assert "refused: " in _said(capsys)
    assert [r for r in product["requests"] if r[0] == "PUT"] == []


def test_an_index_that_answers_500_is_refused_naming_the_cause(product, failing_index, capsys):  # noqa: F811
    # act
    rc = _tap()

    # assert
    assert rc == 1
    said = _said(capsys)
    assert "refused: " in said and "500" in said
    assert [r for r in product["requests"] if r[0] == "PUT"] == []


def test_the_first_refusal_is_the_real_one(product, tmp_path, monkeypatch, capsys):
    # arrange: a url that names no wheel AND no token - the token is what stops this run
    _formula(tmp_path, TEXT.replace(WHEEL, "simplon.tar.gz"))
    monkeypatch.delenv("GH_APP_TOKEN")

    # act
    rc = _tap()

    # assert
    assert rc == 1
    assert "GH_APP_TOKEN" in _said(capsys)


def test_a_read_back_that_fails_after_the_commit_names_the_commit(product, capsys):
    # arrange
    product["fail_readback"] = 500

    # act
    rc = _tap()

    # assert
    assert rc == 1
    [commit] = product["commits"]
    said = _said(capsys)
    assert "refused: " in said and commit in said
    assert "written" not in said
