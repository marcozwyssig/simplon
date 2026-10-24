"""The install closure of a wheel (si#536): parsing the container's answer and the refusals, without docker."""
from __future__ import annotations

import json

import pytest

from simplon.tasks import homebrewclosure as hc
from simplon.tasks.homebrewclosure import Dist


def _doc(*dists: Dist) -> str:
    return json.dumps([{"name": d.name, "version": d.version, "requires": list(d.requires), "in_venv": d.in_venv,
                        "differs": [[r, dict(results)] for r, results in d.differs]} for d in dists])


def test_parse_reads_the_document_after_the_marker():
    dists = (Dist("simplon", "0.36.0", ("PyYAML>=6",), True), Dist("cryptography", "46.0.1", (), False))
    out = "noise before\n" + hc.MARKER + "\n" + _doc(*dists) + "\n"
    assert hc.parse(out) == dists


def test_parse_of_an_empty_document_is_an_empty_closure_not_a_failure():
    assert hc.parse(hc.MARKER + "\n[]\n") == ()


def test_parse_without_marker_is_a_failure_with_the_tail():
    out = "\n".join(f"line {i}" for i in range(30)) + "\n"
    with pytest.raises(ValueError) as e:
        hc.parse(out)
    assert hc.MARKER in str(e.value)
    assert "line 29" in str(e.value) and "line 10" in str(e.value)
    assert "line 9\n" not in str(e.value)


def test_parse_of_a_broken_document_is_a_failure_not_an_empty_closure():
    with pytest.raises(ValueError, match="not the closure"):
        hc.parse(hc.MARKER + "\n[{\"name\": \"x\"}]\n")
    with pytest.raises(ValueError, match="not the closure"):
        hc.parse(hc.MARKER + "\n")


def _doc_with_differs(entries) -> str:
    return hc.MARKER + "\n" + json.dumps(entries) + "\n"


def test_a_marker_that_differs_between_linux_and_macos_is_refused_with_both_results():
    req = 'pyobjc; sys_platform == "darwin"'
    dists = hc.parse(_doc_with_differs([
        {"name": "simplon", "version": "0.36.0", "requires": [], "in_venv": True, "differs": []},
        {"name": "thing", "version": "1.0", "requires": [req], "in_venv": True, "differs": [[req, {
            "linux-x86_64": False, "linux-aarch64": False, "darwin-x86_64": True, "darwin-arm64": True}]]}]))
    [refusal] = hc.refusals(dists, "simplon")
    assert "thing 1.0" in refusal and req in refusal
    assert "true on darwin-x86_64, darwin-arm64" in refusal and "false on linux-x86_64, linux-aarch64" in refusal
    assert "depends_on formula" in refusal


def test_a_windows_only_marker_passes():
    req = "colorama; platform_system == 'Windows'"
    dists = hc.parse(_doc_with_differs([
        {"name": "click", "version": "8.1.8", "requires": [req], "in_venv": True, "differs": []}]))
    assert hc.refusals(dists, "simplon") == []


def test_a_python_version_marker_passes():
    req = 'tomli; python_version < "3.11"'
    dists = hc.parse(_doc_with_differs([
        {"name": "thing", "version": "1.0", "requires": [req], "in_venv": True, "differs": []}]))
    assert hc.refusals(dists, "simplon") == []


def test_a_differing_marker_of_a_formula_dist_is_not_the_closures():
    req = "tzdata; sys_platform == 'darwin'"
    differs = ((req, (("linux-x86_64", False), ("darwin-arm64", True))),)
    assert hc.refusals([Dist("pydantic", "2.14.1", (req,), False, differs)], "simplon") == []


def test_a_document_without_differs_is_not_the_closure():
    with pytest.raises(ValueError, match="not the closure"):
        hc.parse(_doc_with_differs([{"name": "x", "version": "1", "requires": [], "in_venv": True}]))


@pytest.mark.parametrize("req,listed", [
    ("colorama; platform_system == 'Windows'", False),
    ('tomli; python_version < "3.11"', False),
    ("plain>=1", False),
    ("pyobjc; sys_platform == 'darwin'", True),
    ("uvloop; platform_system != 'Darwin'", True),
    ("x; os_name == 'nt'", False),
    ("dev; extra == 'test' and sys_platform == 'darwin'", False),
    ("fast; platform_machine == 'x86_64'", True),
    ("armonly; platform_machine == 'arm64'", True),
])
def test_the_container_comparison_itself(req, listed):
    """The `differs` the container runs, run here on pip's vendored packaging (the dev venv has pip)."""
    pytest.importorskip("pip._vendor.packaging.requirements")
    namespace: dict = {}
    exec(hc._REPORT.split("dists = []")[0], namespace)
    assert bool(namespace["differs"]([req])) is listed


def test_the_container_comparison_spans_four_environments():
    pytest.importorskip("pip._vendor.packaging.requirements")
    namespace: dict = {}
    exec(hc._REPORT.split("dists = []")[0], namespace)
    [[req, results]] = namespace["differs"](["fast; platform_machine == 'x86_64'"])
    assert results == {"linux-x86_64": True, "linux-aarch64": False, "darwin-x86_64": True, "darwin-arm64": False}


def test_a_shadowed_formula_dist_is_refused_with_both_versions():
    dists = [Dist("cryptography", "44.0.0", (), True), Dist("cryptography", "46.0.1", (), False)]
    [refusal] = hc.refusals(dists, "simplon")
    assert "cryptography" in refusal and "44.0.0" in refusal and "46.0.1" in refusal


def test_pip_in_the_venv_and_in_the_formula_is_not_shadowing():
    assert hc.refusals([Dist("pip", "25.2", (), True), Dist("pip", "25.3", (), False)], "simplon") == []


def test_added_excludes_product_and_pip():
    dists = (Dist("Simplon", "0.36.0", (), True), Dist("pip", "25.2", (), True), Dist("PyYAML", "6.0.3", (), True),
             Dist("cryptography", "46.0.1", (), False))
    assert hc.added(dists, "simplon") == (Dist("PyYAML", "6.0.3", (), True),)


def test_the_image_is_pinned_by_digest():
    assert hc.BREW_IMAGE == ("ghcr.io/homebrew/brew:7.0.9@sha256:"
                             "00b643d72ab0ee27c64e3e552d08c66e1bb5272bdf4ed28964e27aa5764f2503")


def test_an_unreadable_wheel_directory_is_refused_before_docker(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "run", lambda argv, **kw: pytest.fail("docker ran"))
    wheel = tmp_path / "x-1.0-py3-none-any.whl"
    wheel.write_bytes(b"")
    tmp_path.chmod(0o700)
    with pytest.raises(ValueError, match=r"has mode 700.*uid 1000"):
        hc.measure(wheel, ["cryptography"], "python@3.14")
    tmp_path.chmod(0o755)
    wheel.chmod(0o600)
    with pytest.raises(ValueError, match=r"x-1.0-py3-none-any.whl has mode 600"):
        hc.measure(wheel, ["cryptography"], "python@3.14")


def _answering(monkeypatch, stdout):
    from simplon.kernel.run import Result
    monkeypatch.setattr(hc, "run", lambda argv, **kw: Result(0, stdout, ""))


def _wheel(tmp_path, name="x-1.0-py3-none-any.whl"):
    wheel = tmp_path / name
    wheel.write_bytes(b"")
    tmp_path.chmod(0o755)
    return wheel


@pytest.mark.parametrize("dists", [(), (Dist("x", "1.0", (), False), Dist("PyYAML", "6.0.3", (), True))])
def test_a_successful_run_whose_venv_shows_no_product_is_refused(tmp_path, monkeypatch, dists):
    _answering(monkeypatch, hc.MARKER + "\n" + _doc(*dists) + "\n")
    with pytest.raises(ValueError, match="the venv shows no x; the measurement did not see pip's install"):
        hc.measure(_wheel(tmp_path), ["cryptography"], "python@3.14")


def test_the_product_is_found_by_its_normalised_name(tmp_path, monkeypatch):
    _answering(monkeypatch, hc.MARKER + "\n" + _doc(Dist("My.Tool", "1.0", (), True)) + "\n")
    assert hc.measure(_wheel(tmp_path, "my_tool-1.0-py3-none-any.whl"), [], "python@3.14")


def test_a_python_without_a_version_is_refused_by_its_form(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "run", lambda argv, **kw: pytest.fail("docker ran"))
    with pytest.raises(ValueError, match=r"python@3\.N.*'python'"):
        hc.measure(_wheel(tmp_path), ["cryptography"], "python")


def test_a_missing_wheel_is_refused_by_its_path(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "run", lambda argv, **kw: pytest.fail("docker ran"))
    tmp_path.chmod(0o755)
    missing = tmp_path / "x-1.0-py3-none-any.whl"
    with pytest.raises(ValueError, match=f"{missing} does not exist"):
        hc.measure(missing, ["cryptography"], "python@3.14")


def test_a_failed_run_joins_stderr_and_stdout_on_a_line_boundary(tmp_path, monkeypatch):
    from simplon.kernel.run import Result
    monkeypatch.setattr(hc, "run", lambda argv, **kw: Result(1, "out line", "err line"))
    with pytest.raises(ValueError) as e:
        hc.measure(_wheel(tmp_path), ["cryptography"], "python@3.14")
    assert "err line\nout line" in str(e.value)


def test_brew_install_backs_off_between_attempts():
    script = hc.script("x-1.0-py3-none-any.whl", [], "python@3.14")
    assert "sleep $((i*5))" in script


def test_a_timeout_is_a_refusal_naming_the_limit(tmp_path, monkeypatch):
    import subprocess

    def timed_out(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
    monkeypatch.setattr(hc, "run", timed_out)
    wheel = tmp_path / "x-1.0-py3-none-any.whl"
    wheel.write_bytes(b"")
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError, match="CLOSURE_TIMEOUT_S"):
        hc.measure(wheel, ["cryptography"], "python@3.14")


def test_a_failed_run_is_a_failure_with_the_tail(tmp_path, monkeypatch):
    from simplon.kernel.run import Result
    monkeypatch.setattr(hc, "run", lambda argv, **kw: Result(1, "", "brew install attempt 5 of 5 failed\n"
                                                                     "Error: Download failed: bottle 404\n"))
    wheel = tmp_path / "x-1.0-py3-none-any.whl"
    wheel.write_bytes(b"")
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError, match="Download failed: bottle 404"):
        hc.measure(wheel, ["cryptography"], "python@3.14")


def test_the_container_line_installs_python_and_the_formulae(tmp_path, monkeypatch):
    seen = {}

    def answered(argv, **kw):
        seen["argv"], seen["timeout"] = argv, kw.get("timeout")
        from simplon.kernel.run import Result
        return Result(0, hc.MARKER + "\n" + _doc(Dist("x", "1.0", (), True)) + "\n", "")
    monkeypatch.setattr(hc, "run", answered)
    wheel = tmp_path / "x-1.0-py3-none-any.whl"
    wheel.write_bytes(b"")
    tmp_path.chmod(0o755)
    assert hc.measure(wheel, ["pydantic", "cryptography"], "python@3.14") == (Dist("x", "1.0", (), True),)
    argv = seen["argv"]
    assert seen["timeout"] == hc.CLOSURE_TIMEOUT_S
    assert argv[:3] == ["docker", "run", "--rm"] and hc.BREW_IMAGE in argv and "--user" not in argv
    assert f"{tmp_path}:/w:ro" in argv
    script = argv[-1]
    assert "brew install -q cryptography pydantic python@3.14" in script
    assert '/bin/python3.14" -m venv --system-site-packages /tmp/v' in script
    assert "/tmp/v/bin/pip -q install /w/x-1.0-py3-none-any.whl" in script
