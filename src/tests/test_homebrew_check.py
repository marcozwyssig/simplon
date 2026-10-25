"""`test:homebrew-formula`, the body (si#536): the digest checks and the verdict record, without docker.

The audit container is a stub here (`homebrewtap.audit` patched); `test_homebrew_check_e2e.py` runs the real
one. PyPI is a real local HTTP server reached through `homebrewformula.PYPI_INDEX`, as in
`test_homebrew_build.py`, so the adapter runs unmodified.
"""
from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from simplon.kernel.run import Result
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
#: the real `audit`, for the tests that stub only its `run`; the `product` fixture stubs `audit` itself
AUDIT = homebrewtap.audit
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


def _seed(root):
    """A green record an earlier run left, which a run that reaches no verdict must remove."""
    path = root / "build" / "results" / "homebrew.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"formula": "simplon", "verdict": 0, "runs": []}), encoding="utf-8")


def _said(capsys) -> str:
    out = capsys.readouterr()
    return out.out + out.err


def test_formula_digests_reads_the_top_level_sha_and_each_resource(product):
    root, sha, _ = product
    top, resources = homebrewtap.formula_digests((root / "build" / "homebrew" / "simplon.rb").read_text())
    assert top == sha
    assert resources == [hf.Resource("pyyaml", PYYAML.url, PYYAML.sha256)]


@pytest.mark.parametrize("online", ["", "yes", "1", "no", "truthy"])
def test_online_none_is_refused(product, pypi, online):  # noqa: F811
    # a bool param would be a CLI flag, which `params: {online: false}` cannot reach; so it is a string
    # with exactly two values and no default
    root, _, calls = product
    _seed(root)
    with pytest.raises(ValueError, match="online must be 'true'.*or 'false'"):
        _check(online=online)
    assert calls == []
    assert not (root / "build" / "results" / "homebrew.json").exists()


@pytest.mark.parametrize(("online", "is_online"), [("False", False), ("True", True), (" false ", False)])
def test_online_as_the_workflow_renders_it_is_accepted(product, pypi, online, is_online):  # noqa: F811
    # measured: workflowgen renders `params: {online: false}` as `--online False`, and true as `True`
    root, sha, calls = product
    pypi["/pypi/simplon/0.36.0/json"] = _release((WHEEL, sha))
    pypi["/pypi/pyyaml/6.0.2/json"] = _release(("pyyaml-6.0.2.tar.gz", "cc" * 32))

    rc = _check(online=online)

    assert [c[2] for c in calls] == [is_online]
    assert _record(root)["runs"][0]["online"] is is_online
    assert rc == (1 if is_online else 0)   # online: the placeholder url is red on a real run


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


class _Failing(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(500)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def failing_index(monkeypatch):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Failing)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setattr(hf, "PYPI_INDEX", f"http://127.0.0.1:{httpd.server_address[1]}")
    try:
        yield
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.parametrize("online", ["false", "true"])
def test_an_index_that_answers_500_is_no_verdict(product, failing_index, online):
    # a failed probe is not a result: PyPI not answering says nothing about the formula
    root, _, calls = product
    _seed(root)
    with pytest.raises(ValueError, match="500"):
        _check(online=online)
    assert calls == []
    assert not (root / "build" / "results" / "homebrew.json").exists()


def test_an_unreachable_index_is_no_verdict(product, monkeypatch):
    root, _, calls = product
    monkeypatch.setattr(hf, "PYPI_INDEX", "http://127.0.0.1:1")
    _seed(root)
    with pytest.raises(ValueError, match="pyyaml-6.0.2.tar.gz"):
        _check()
    assert calls == []
    assert not (root / "build" / "results" / "homebrew.json").exists()


def test_a_formula_file_not_named_for_the_wheel_is_refused(product, pypi):  # noqa: F811
    # brew taps `local/check/<file stem>` and looks for the class of that name; `formula.rb` holding
    # `class Simplon` is a setup fault, not a red verdict
    root, _, calls = product
    pypi["/pypi/pyyaml/6.0.2/json"] = _release(("pyyaml-6.0.2.tar.gz", "cc" * 32))
    (root / "sample.yaml").write_text(MANIFEST.replace("simplon.rb", "formula.rb"), encoding="utf-8")
    (root / "build" / "homebrew" / "simplon.rb").rename(root / "build" / "homebrew" / "formula.rb")
    _seed(root)
    with pytest.raises(ValueError, match="'formula'.*'simplon'"):
        _check()
    assert calls == []
    assert not (root / "build" / "results" / "homebrew.json").exists()


def _container(monkeypatch, out, err="", rc=0):
    """`run` as the audit container answers it: the lines `out` and `err`, and the argv it was handed."""
    seen = []

    def fake(argv, **kw):
        seen.append((argv, kw))
        return Result(rc, out, err)
    monkeypatch.setattr(homebrewtap, "run", fake)
    return seen


def _tapped(text):
    return f"--- simplon tapped sha256={hashlib.sha256(text.encode()).hexdigest()} ---\n"


def test_a_red_audit_shows_the_containers_stderr(product, monkeypatch, capsys):
    text = "class Simplon < Formula\nend\n"
    _container(monkeypatch, _tapped(text) + "--- simplon audit rc=1 ---\n--- simplon style rc=0 ---\n",
               err="Error: the reason audit gives on stderr\n")
    assert AUDIT(text, "simplon", False) == (1, 0)
    assert "the reason audit gives on stderr" in _said(capsys)


def test_a_tapped_file_that_is_not_the_bytes_sent_is_no_verdict(product, monkeypatch):
    text = "class Simplon < Formula\nend\n"
    _container(monkeypatch, _tapped(text + "x") + "--- simplon audit rc=0 ---\n--- simplon style rc=0 ---\n")
    with pytest.raises(ValueError, match="sha256"):
        AUDIT(text, "simplon", False)


def test_a_run_that_reports_no_tapped_digest_is_no_verdict(product, monkeypatch):
    _container(monkeypatch, "--- simplon audit rc=0 ---\n--- simplon style rc=0 ---\n")
    with pytest.raises(ValueError, match="tapped"):
        AUDIT("class Simplon < Formula\nend\n", "simplon", False)


def test_the_tapped_file_is_the_bytes_sent(product, monkeypatch):
    text = "class Simplon < Formula\nend\n"
    seen = _container(monkeypatch, _tapped(text) + "--- simplon audit rc=0 ---\n--- simplon style rc=0 ---\n")
    assert AUDIT(text, "simplon", False) == (0, 0)
    assert seen[0][1]["input_text"] == text
