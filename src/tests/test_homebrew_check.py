"""`test:homebrew-formula`, the body (si#536): the digest checks and the verdict record, without docker.

The audit container is a stub here (`homebrewtap.audit` patched); `test_homebrew_check_e2e.py` runs the real
one. PyPI is a real local HTTP server reached through `homebrewformula.PYPI_INDEX`, as in
`test_homebrew_build.py`, so the adapter runs unmodified.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from simplon.manifest import context
from simplon.tasks import homebrewformula as hf
from simplon.tasks import homebrewtap
from test_homebrew_build import _release, pypi  # noqa: F401 - `pypi` is a fixture
from test_homebrew_render import make_wheel

WHEEL = "simplon-0.36.0-py3-none-any.whl"
MANIFEST = ("product: sample\nartifacts:\n"
            "  dist: { kind: directory, path: dist }\n"
            "  formula: { kind: homebrew-formula, path: build/homebrew/simplon.rb }\n"
            "  checked: { kind: test-result, path: build/results/homebrew.json }\n")
SHAPE = hf.shape_of("python", ["libsodium"], "python@3.14", {}, {"args": ["--version"], "expect": "simplon"})
PYYAML = hf.Resource("PyYAML", "https://files.example/pyyaml-6.0.2.tar.gz", "cc" * 32)


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A product with one wheel in `dist`, a formula rendered for it with the placeholder URL, and a stubbed
    audit that answers green unless a test says otherwise."""
    (tmp_path / "sample.yaml").write_text(MANIFEST, encoding="utf-8")
    wheel = make_wheel(tmp_path / "dist", summary="Delivers products")
    monkeypatch.setattr(context, "_current", context.ProductContext("sample", tmp_path, tmp_path / "sample.yaml"))
    calls: list[tuple[str, str, bool]] = []

    def audit(text, name, online):
        calls.append((text, name, online))
        return 0, 0
    monkeypatch.setattr(homebrewtap, "audit", audit)
    sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    write(tmp_path, hf.PLACEHOLDER + WHEEL, sha)
    return tmp_path, sha, calls


def write(root, url, sha, resources=(PYYAML,)):
    meta = hf.wheel_meta(root / "dist" / WHEEL)
    out = root / "build" / "homebrew" / "simplon.rb"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(hf.render(meta, url, sha, list(resources), SHAPE), encoding="utf-8")
    return out


def _check(online="false", **over):
    return homebrewtap.check(**{"formula": "formula", "wheel": "dist", "results": "checked", "online": online,
                                **over})


def _record(root):
    return json.loads((root / "build" / "results" / "homebrew.json").read_text(encoding="utf-8"))


def _said(capsys) -> str:
    out = capsys.readouterr()
    return out.out + out.err


def test_formula_digests_reads_the_top_level_sha_and_each_resource(product):
    root, sha, _ = product
    top, resources = homebrewtap.formula_digests((root / "build" / "homebrew" / "simplon.rb").read_text())
    assert top == sha
    assert resources == [hf.Resource("pyyaml", PYYAML.url, PYYAML.sha256)]


@pytest.mark.parametrize("online", ["", "False", "yes", "1"])
def test_online_none_is_refused(product, pypi, online):  # noqa: F811
    # a bool param would be a CLI flag, which `params: {online: false}` cannot reach; so it is a string
    # with exactly two values and no default
    root, _, calls = product
    with pytest.raises(ValueError, match="online must be 'true'.*or 'false'"):
        _check(online=online)
    assert calls == []
    assert not (root / "build" / "results" / "homebrew.json").exists()


def test_a_formula_sha_that_differs_from_the_wheel_is_red(product, pypi, capsys):  # noqa: F811
    root, sha, _ = product
    pypi["/pypi/pyyaml/6.0.2/json"] = _release(("pyyaml-6.0.2.tar.gz", "cc" * 32))
    write(root, hf.PLACEHOLDER + WHEEL, "0" * 64)
    assert _check() == 1
    said = _said(capsys)
    assert "0" * 64 in said and sha in said
    assert _record(root)["verdict"] == 1


def test_online_compares_the_formula_sha_with_pypi(product, pypi, capsys):  # noqa: F811
    root, sha, calls = product
    pypi["/pypi/pyyaml/6.0.2/json"] = _release(("pyyaml-6.0.2.tar.gz", "cc" * 32))
    pypi["/pypi/simplon/0.36.0/json"] = _release((WHEEL, "e" * 64))
    write(root, f"https://files.example/{WHEEL}", sha)
    assert _check(online="true") == 1
    said = _said(capsys)
    assert "PyPI" in said and "e" * 64 in said
    assert calls[-1][2] is True
    # and green once PyPI lists the same bytes
    pypi["/pypi/simplon/0.36.0/json"] = _release((WHEEL, sha))
    assert _check(online="true") == 0
    assert _record(root)["verdict"] == 0


def test_online_refuses_the_dry_run_placeholder_url(product, pypi, capsys):  # noqa: F811
    root, sha, _ = product
    pypi["/pypi/pyyaml/6.0.2/json"] = _release(("pyyaml-6.0.2.tar.gz", "cc" * 32))
    pypi["/pypi/simplon/0.36.0/json"] = _release((WHEEL, sha))
    assert _check(online="true") == 1
    assert "pypi.invalid" in _said(capsys)


def test_online_without_the_wheel_on_pypi_is_red_by_name(product, pypi, capsys):  # noqa: F811
    # the adapter answers () for a 200 with an empty `urls`; that must not read as "nothing to compare"
    root, sha, _ = product
    pypi["/pypi/pyyaml/6.0.2/json"] = _release(("pyyaml-6.0.2.tar.gz", "cc" * 32))
    pypi["/pypi/simplon/0.36.0/json"] = {"urls": []}
    write(root, f"https://files.example/{WHEEL}", sha)
    assert _check(online="true") == 1
    assert WHEEL in _said(capsys)
    assert _record(root)["verdict"] == 1


def test_a_resource_sha_that_differs_from_pypi_is_red(product, pypi, capsys):  # noqa: F811
    root, _, _ = product
    pypi["/pypi/pyyaml/6.0.2/json"] = _release(("pyyaml-6.0.2.tar.gz", "f" * 64))
    assert _check() == 1
    said = _said(capsys)
    assert "pyyaml" in said and "f" * 64 in said
    assert _record(root)["verdict"] == 1


def test_a_resource_pypi_does_not_list_is_red_by_name(product, pypi, capsys):  # noqa: F811
    root, _, _ = product
    pypi["/pypi/pyyaml/6.0.2/json"] = {"urls": []}
    assert _check() == 1
    assert "pyyaml-6.0.2.tar.gz" in _said(capsys)
    assert _record(root)["verdict"] == 1


def test_the_record_names_the_formula_digest(product, pypi):  # noqa: F811
    root, _, calls = product
    pypi["/pypi/pyyaml/6.0.2/json"] = _release(("pyyaml-6.0.2.tar.gz", "cc" * 32))
    assert _check() == 0
    record = _record(root)
    digest = hashlib.sha256((root / "build" / "homebrew" / "simplon.rb").read_bytes()).hexdigest()
    assert record["formula"] == "simplon"
    assert record["verdict"] == 0
    assert record["runs"][0]["id"] == "sha256:" + digest
    assert record["runs"][0]["reference"] == "build/homebrew/simplon.rb"
    assert calls == [((root / "build" / "homebrew" / "simplon.rb").read_text(encoding="utf-8"), "simplon", False)]


def test_a_red_audit_writes_verdict_1_and_returns_1(product, pypi, monkeypatch):  # noqa: F811
    root, _, _ = product
    pypi["/pypi/pyyaml/6.0.2/json"] = _release(("pyyaml-6.0.2.tar.gz", "cc" * 32))
    monkeypatch.setattr(homebrewtap, "audit", lambda text, name, online: (1, 0))
    assert _check() == 1
    record = _record(root)
    assert record["verdict"] == 1
    assert (record["runs"][0]["audit_rc"], record["runs"][0]["style_rc"]) == (1, 0)


def test_an_audit_that_reached_no_verdict_writes_no_record_and_removes_the_old_one(product, pypi, monkeypatch):  # noqa: F811
    root, _, _ = product
    pypi["/pypi/pyyaml/6.0.2/json"] = _release(("pyyaml-6.0.2.tar.gz", "cc" * 32))
    assert _check() == 0
    assert _record(root)["verdict"] == 0

    def broken(text, name, online):
        raise ValueError("the audit run printed no result line")
    monkeypatch.setattr(homebrewtap, "audit", broken)
    with pytest.raises(ValueError, match="no result line"):
        _check()
    assert not (root / "build" / "results" / "homebrew.json").exists()


def test_the_audit_rc_lines_are_read_and_their_absence_is_no_verdict():
    out = "noise\n--- simplon audit rc=1 ---\nstyle says\n--- simplon style rc=0 ---\n"
    assert homebrewtap.parse(out, "") == (1, 0)
    with pytest.raises(ValueError, match="style"):
        homebrewtap.parse("--- simplon audit rc=0 ---\n", "boom")
