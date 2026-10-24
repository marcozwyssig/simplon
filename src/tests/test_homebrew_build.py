"""`build:homebrew-formula`, the body (si#536): the wheel and the formula as artifacts, PyPI as a local server.

The closure is a stub here (`homebrewclosure.measure` patched): Task 3 measured the real container in
`test_homebrew_closure_e2e.py`. PyPI is a real local HTTP server reached through `PYPI_INDEX`, so the adapter
runs unmodified.
"""
from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from simplon.manifest import catalogue, context
from simplon.manifest import load as manifest
from simplon.tasks import homebrewclosure, homebrewformula
from simplon.tasks.homebrewclosure import Dist
from test_homebrew_render import make_wheel

WHEEL = "simplon-0.36.0-py3-none-any.whl"
MANIFEST = ("product: sample\nartifacts:\n"
            "  dist: { kind: directory, path: dist }\n"
            "  formula: { kind: homebrew-formula, path: build/homebrew/simplon.rb }\n")
SHAPE = dict(shape="python", depends_on=["libsodium"], python="python@3.14", env={"SODIUM_INSTALL": "system"},
             test={"args": ["--version"], "expect": "simplon"})
CLOSURE = (Dist("simplon", "0.36.0", (), True), Dist("pip", "25.0", (), True),
           Dist("PyYAML", "6.0.2", (), True), Dist("certifi", "2025.1.1", (), False))


def _release(*files):
    return {"urls": [{"filename": f, "url": f"https://files.example/{f}", "digests": {"sha256": sha},
                      "packagetype": "sdist" if f.endswith(".tar.gz") else "bdist_wheel"} for f, sha in files]}


class _Handler(BaseHTTPRequestHandler):
    routes: dict[str, dict] = {}

    def do_GET(self):
        body = self.routes.get(self.path)
        data = json.dumps(body).encode() if body is not None else b"not found"
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def pypi(monkeypatch):
    routes: dict[str, dict] = {"/pypi/PyYAML/6.0.2/json": _release(("pyyaml-6.0.2.tar.gz", "cc" * 32),
                                                                    ("PyYAML-6.0.2-cp314-x.whl", "dd" * 32))}
    handler = type("H", (_Handler,), {"routes": routes})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setattr(homebrewformula, "PYPI_INDEX", f"http://127.0.0.1:{httpd.server_address[1]}")
    try:
        yield routes
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A product with a `dist` directory holding one wheel and a `formula` artifact, and a stubbed closure."""
    (tmp_path / "sample.yaml").write_text(MANIFEST, encoding="utf-8")
    wheel = make_wheel(tmp_path / "dist")
    monkeypatch.setattr(context, "_current", context.ProductContext("sample", tmp_path, tmp_path / "sample.yaml"))
    monkeypatch.setattr(homebrewclosure, "measure", lambda wheel, depends_on, python: CLOSURE)
    return tmp_path, hashlib.sha256(wheel.read_bytes()).hexdigest()


def _build(**over):
    return homebrewformula.build(**{"wheel": "dist", "formula": "formula", **SHAPE, **over})


def _said(capsys) -> str:
    out = capsys.readouterr()
    return out.out + out.err


def test_local_source_uses_the_local_sha_and_the_placeholder_url(product, pypi, capsys):
    root, sha = product
    assert _build(source="local") == 0
    text = (root / "build" / "homebrew" / "simplon.rb").read_text(encoding="utf-8")
    assert f'url "https://pypi.invalid/dry-run/{WHEEL}", using: :nounzip' in text
    assert f'sha256 "{sha}"' in text
    assert 'resource "pyyaml" do' in text and "https://files.example/pyyaml-6.0.2.tar.gz" in text
    assert 'resource "pip"' not in text and 'resource "simplon"' not in text
    said = _said(capsys)
    assert "PyPI comparison" in said and "online audit" in said and "real run" in said


def test_pypi_source_uses_pypis_url_and_sha(product, pypi):
    root, sha = product
    pypi["/pypi/simplon/0.36.0/json"] = _release((WHEEL, sha), ("simplon-0.36.0.tar.gz", "ee" * 32))
    assert _build(source="pypi") == 0
    text = (root / "build" / "homebrew" / "simplon.rb").read_text(encoding="utf-8")
    assert f'url "https://files.example/{WHEEL}", using: :nounzip' in text
    assert f'sha256 "{sha}"' in text
    assert "pypi.invalid" not in text


def test_pypi_source_reads_the_wheel_from_pypi_after_the_closure(product, pypi, monkeypatch):
    # PyPI can answer 404 for a minute after an upload: the closure (an image pull and an install) runs first
    root, sha = product
    pypi["/pypi/simplon/0.36.0/json"] = _release((WHEEL, sha), ("simplon-0.36.0.tar.gz", "ee" * 32))
    calls: list[str] = []
    files = homebrewformula.pypi.files
    monkeypatch.setattr(homebrewformula.pypi, "files",
                        lambda name, *a, **k: calls.append(name) or files(name, *a, **k))
    monkeypatch.setattr(homebrewclosure, "measure", lambda *a: calls.append("measure") or CLOSURE)
    assert _build(source="pypi") == 0
    assert calls.index("measure") < calls.index("simplon"), calls


def test_pypi_sha_that_differs_from_the_local_wheel_is_refused(product, pypi, capsys):
    root, sha = product
    pypi["/pypi/simplon/0.36.0/json"] = _release((WHEEL, "0" * 64))
    assert _build(source="pypi") == 1
    said = _said(capsys)
    assert "0" * 64 in said and sha in said
    assert not (root / "build" / "homebrew" / "simplon.rb").exists()


def test_pypi_without_the_version_is_refused_not_rendered_locally(product, pypi, capsys):
    root, _ = product
    assert _build(source="pypi") == 1
    assert "not listed" in _said(capsys)
    assert not (root / "build" / "homebrew" / "simplon.rb").exists()


def test_pypi_without_the_wheel_file_is_refused_by_name(product, pypi, capsys):
    # the adapter answers () for a 200 with an empty `urls`; the body must not read that as "use the local"
    root, _ = product
    pypi["/pypi/simplon/0.36.0/json"] = {"urls": []}
    assert _build(source="pypi") == 1
    assert WHEEL in _said(capsys)
    assert not (root / "build" / "homebrew" / "simplon.rb").exists()


def test_a_resource_without_sdist_is_refused_by_name(product, pypi, capsys):
    root, _ = product
    pypi["/pypi/PyYAML/6.0.2/json"] = _release(("PyYAML-6.0.2-cp314-x.whl", "dd" * 32))
    assert _build(source="local") == 1
    said = _said(capsys)
    assert "PyYAML 6.0.2" in said and "sdist" in said
    assert not (root / "build" / "homebrew" / "simplon.rb").exists()


def test_a_closure_refusal_is_logged_and_nothing_is_written(product, pypi, monkeypatch, capsys):
    root, _ = product
    brew = Dist("PyYAML", "6.0.1", (), False)
    monkeypatch.setattr(homebrewclosure, "measure", lambda wheel, depends_on, python: (*CLOSURE, brew))
    assert _build(source="local") == 1
    said = _said(capsys)
    assert "6.0.2" in said and "6.0.1" in said
    assert not (root / "build" / "homebrew" / "simplon.rb").exists()


def test_a_refused_build_removes_the_formula_an_earlier_run_left(product, pypi, capsys):
    # a refusal must not leave yesterday's formula where the test and the tap read today's
    root, _ = product
    old = root / "build" / "homebrew" / "simplon.rb"
    old.parent.mkdir(parents=True)
    old.write_text("an earlier run's formula\n", encoding="utf-8")

    assert _build(source="pypi") == 1
    assert "not listed" in _said(capsys)
    assert not old.exists()


def test_a_formula_path_not_named_for_the_wheel_is_refused_before_the_closure(product, pypi, monkeypatch):
    root, _ = product
    (root / "sample.yaml").write_text(MANIFEST.replace("simplon.rb", "tool.rb"), encoding="utf-8")
    measured: list = []
    monkeypatch.setattr(homebrewclosure, "measure", lambda *a: measured.append(a) or CLOSURE)

    with pytest.raises(ValueError, match=r"named 'tool'.*simplon\.rb"):
        _build(source="local")
    assert measured == []


@pytest.mark.parametrize("source", ["", "pip", "PyPI"])
def test_an_empty_source_is_refused(product, pypi, source):
    with pytest.raises(ValueError, match="source"):
        _build(source=source)


def test_an_unknown_with_key_is_refused_at_load():
    text = """
ci:
  build:
    commands:
      formula: { task: "build:homebrew-formula", with: { templat: x } }
"""
    with pytest.raises(ValueError, match="templat.*not parameters"):
        manifest.load(text, catalogue=catalogue.load(), validate_with=True)
