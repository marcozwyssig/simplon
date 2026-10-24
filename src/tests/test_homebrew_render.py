"""The pure part of a generated Homebrew formula (si#536): wheel metadata, class name, shape checks, render."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from simplon.tasks import homebrewformula as hf

SHA = "a" * 64


def make_wheel(directory: Path, *, name="simplon", version="0.36.0", summary="A tool", drop=(), legacy_license=False,
               console="simplon") -> Path:
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}", f"Summary: {summary}",
             "Project-URL: Homepage, https://example.org/simplon", "Project-URL: Issues, https://example.org/i"]
    lines.append("License: MIT" if legacy_license else "License-Expression: MIT")
    kept = [ln for ln in lines if not any(ln.startswith(d + ":") for d in drop)]
    ep = f"[console_scripts]\n{console} = pkg.cli:main\nother = pkg.x:y\n"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{name}-{version}.dist-info/METADATA", "\n".join(kept) + "\n\nbody\n")
        if "entry_points" not in drop:
            z.writestr(f"{name}-{version}.dist-info/entry_points.txt", ep)
    return path


def test_wheel_meta_reads_the_wheel(tmp_path):
    meta = hf.wheel_meta(make_wheel(tmp_path))
    assert (meta.name, meta.version, meta.summary, meta.homepage, meta.license, meta.command) == (
        "simplon", "0.36.0", "A tool", "https://example.org/simplon", "MIT", "simplon")
    assert meta.filename == "simplon-0.36.0-py3-none-any.whl"
    assert len(meta.sha256) == 64


@pytest.mark.parametrize("drop,field", [
    ("Name", "Name"), ("Version", "Version"), ("Summary", "Summary"), ("Project-URL", "Homepage"),
    ("License-Expression", "License-Expression"), ("entry_points", "console_scripts")])
def test_a_missing_metadata_field_is_named(tmp_path, drop, field):
    with pytest.raises(ValueError, match=field):
        hf.wheel_meta(make_wheel(tmp_path, drop=(drop,)))


def test_the_legacy_license_field_is_not_a_license_expression(tmp_path):
    with pytest.raises(ValueError, match="License-Expression"):
        hf.wheel_meta(make_wheel(tmp_path, legacy_license=True))


def test_the_wheel_finds_the_one(tmp_path):
    wheel = make_wheel(tmp_path)
    assert hf.the_wheel(tmp_path) == wheel


def test_the_wheel_needs_exactly_one(tmp_path):
    with pytest.raises(ValueError, match="no .whl"):
        hf.the_wheel(tmp_path)
    make_wheel(tmp_path)
    make_wheel(tmp_path, name="other")
    with pytest.raises(ValueError, match="other-0.36.0.*simplon-0.36.0|simplon-0.36.0.*other-0.36.0"):
        hf.the_wheel(tmp_path)


@pytest.mark.parametrize("name,expected", [("simplon", "Simplon"), ("foo-bar", "FooBar"), ("foo_bar.baz", "FooBarBaz")])
def test_class_name(name, expected):
    assert hf.class_name(name) == expected


META = hf.WheelMeta(name="simplon", version="0.36.0", summary="Delivery orchestrator", homepage="https://h.example/s",
                    license="MIT", command="simplon", filename="simplon-0.36.0-py3-none-any.whl", sha256="f" * 64)
SHAPE = hf.PythonShape(depends_on=("python@3.14", "libyaml", "cryptography"), python="python@3.14",
                       env={"SODIUM_INSTALL": "system"}, test_args=("--help",), test_expect="usage:")

EXPECTED = '''class Simplon < Formula
  include Language::Python::Virtualenv

  desc "Delivery orchestrator"
  homepage "https://h.example/s"
  url "https://files.example/simplon-0.36.0-py3-none-any.whl", using: :nounzip
  sha256 "''' + "e" * 64 + '''"
  license "MIT"

  depends_on "cryptography"
  depends_on "libyaml"
  depends_on "python@3.14"

  resource "certifi" do
    url "https://files.example/certifi.tar.gz"
    sha256 "''' + "1" * 64 + '''"
  end

  resource "pyyaml" do
    url "https://files.example/PyYAML.tar.gz"
    sha256 "''' + "2" * 64 + '''"
  end

  def install
    ENV["SODIUM_INSTALL"] = "system"
    venv = virtualenv_create(libexec, "python3.14")
    venv.pip_install resources
    venv.pip_install_and_link buildpath/"simplon-#{version}-py3-none-any.whl"
  end

  test do
    assert_match "usage:", shell_output("#{bin}/simplon --help")
  end
end
'''


def test_render_matches_the_prototype_shape():
    resources = [hf.Resource("PyYAML", "https://files.example/PyYAML.tar.gz", "2" * 64),
                 hf.Resource("certifi", "https://files.example/certifi.tar.gz", "1" * 64)]
    assert hf.render(META, "https://files.example/simplon-0.36.0-py3-none-any.whl", "e" * 64, resources, SHAPE) == EXPECTED


def test_env_is_sorted_by_key_and_empty_env_writes_no_lines():
    shape = SHAPE._replace(env={"B": "2", "A": "1"})
    out = hf.render(META, "u", "e" * 64, [], shape)
    assert '    ENV["A"] = "1"\n    ENV["B"] = "2"\n    venv =' in out
    out = hf.render(META, "u", "e" * 64, [], SHAPE._replace(env={}))
    assert "ENV[" not in out


def test_desc_escapes_ruby():
    out = hf.render(META._replace(summary='say "hi" #{x} a\\b'), "u", "e" * 64, [], SHAPE)
    assert '  desc "say \\"hi\\" \\#{x} a\\\\b"\n' in out


def test_other_strings_are_escaped_too():
    shape = SHAPE._replace(env={"K": 'v"#{x}'}, test_args=('a"b',), test_expect="x #{y}")
    out = hf.render(META._replace(homepage='h"', license='l"'), "u", "e" * 64, [], shape)
    assert 'homepage "h\\""' in out and 'license "l\\""' in out
    assert 'ENV["K"] = "v\\"\\#{x}"' in out
    assert 'assert_match "x \\#{y}", shell_output("#{bin}/simplon a\\"b")' in out


def shape_args(**over):
    args = dict(shape="python", depends_on=["python@3.14"], python="python@3.14", env={},
                test={"args": ["--help"], "expect": "usage:"})
    args.update(over)
    return args


def test_shape_of_builds_the_shape():
    s = hf.shape_of(**shape_args(env={"A": "1"}))
    assert s == hf.PythonShape(("python@3.14",), "python@3.14", {"A": "1"}, ("--help",), "usage:")


def test_shape_binary_is_refused_as_part_f():
    with pytest.raises(ValueError, match=r"built with firn's part F \(si#449\)"):
        hf.shape_of(**shape_args(shape="binary"))


@pytest.mark.parametrize("value", ["", "ruby", None])
def test_an_unknown_shape_is_refused(value):
    with pytest.raises(ValueError) as e:
        hf.shape_of(**shape_args(shape=value))
    assert "python" in str(e.value) and "binary" in str(e.value)


@pytest.mark.parametrize("value", ["python", "python@3", "python@3.x", "node@20", "", "python@3.14.1"])
def test_python_must_be_a_python_formula(value):
    with pytest.raises(ValueError, match="python@3"):
        hf.shape_of(**shape_args(python=value))


@pytest.mark.parametrize("over", [
    {"depends_on": "libyaml"}, {"depends_on": [1]}, {"env": ["A"]}, {"env": {"A": 1}},
    {"test": {"args": ["--help"]}}, {"test": {"args": "--help", "expect": "x"}},
    {"test": {"args": ["--help"], "expect": ""}}, {"test": {"args": [], "expect": "x", "extra": 1}}, {"test": None}])
def test_malformed_with_values_are_refused(over):
    with pytest.raises(ValueError):
        hf.shape_of(**shape_args(**over))
