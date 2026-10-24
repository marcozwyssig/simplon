"""A Homebrew formula for a Python CLI, rendered from the wheel's own metadata (si#536).

This part is pure: it reads a wheel, checks the shape of the `with:` values and renders text. It touches no
docker and no network, so it imports anywhere. Every refusal is a `ValueError` that names the field or value
and the way out; the task body that turns it into a return code lives further down this module.
"""
from __future__ import annotations

import email
import hashlib
import re
import shlex
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

_PYTHON_FORMULA = re.compile(r"^python@3\.\d+$")


class WheelMeta(NamedTuple):
    name: str
    version: str
    summary: str
    homepage: str
    license: str
    command: str
    filename: str
    sha256: str


class Resource(NamedTuple):
    name: str
    url: str
    sha256: str


class PythonShape(NamedTuple):
    depends_on: tuple[str, ...]
    python: str
    env: Mapping[str, str]
    test_args: tuple[str, ...]
    test_expect: str


def the_wheel(directory: Path) -> Path:
    if not Path(directory).is_dir():
        raise ValueError(f"{directory} does not exist or is not a directory; the wheel input must be a directory "
                         f"holding the built .whl")
    found = sorted(Path(directory).glob("*.whl"))
    if len(found) != 1:
        listed = [p.name for p in found]
        raise ValueError(f"{directory} must hold exactly one .whl, found "
                         f"{listed if listed else 'no .whl'}; build the wheel into a directory of its own")
    return found[0]


def wheel_meta(path: Path) -> WheelMeta:
    path = Path(path)
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise ValueError(f"{path.name} is not a zip file, so not a wheel; rebuild it") from e
    with z:
        names = z.namelist()
        meta_name = next((n for n in names if n.endswith(".dist-info/METADATA")), None)
        if meta_name is None:
            raise ValueError(f"{path.name} has no .dist-info/METADATA; it is not a wheel")
        meta = email.message_from_bytes(z.read(meta_name))
        ep_name = meta_name[: -len("METADATA")] + "entry_points.txt"
        entry_points = z.read(ep_name).decode() if ep_name in names else ""

    def field(key: str, hint: str = "") -> str:
        value = (meta[key] or "").strip()
        if not value:
            raise ValueError(f"{path.name} has no {key} in its METADATA{hint}")
        return value

    homepage = next((u.split(",", 1)[1].strip() for u in meta.get_all("Project-URL") or []
                     if "," in u and u.split(",", 1)[0].strip().lower() == "homepage"), "")
    if not homepage:
        raise ValueError(f"{path.name} has no Homepage in its METADATA Project-URL; add `Homepage = <url>` "
                         f"under [project.urls]")
    return WheelMeta(
        name=field("Name"), version=field("Version"), summary=field("Summary"), homepage=homepage,
        license=field("License-Expression", "; the legacy `License:` field is not read, declare `license = "
                                            "\"<SPDX>\"` in pyproject.toml"),
        command=_console_command(entry_points, path.name), filename=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def _console_command(entry_points: str, wheel: str) -> str:
    in_scripts = False
    for line in entry_points.splitlines():
        line = line.strip()
        if line.startswith("["):
            in_scripts = line == "[console_scripts]"
        elif in_scripts and "=" in line:
            return line.split("=", 1)[0].strip()
    raise ValueError(f"{wheel} has no console_scripts entry in its entry_points.txt; the formula's test "
                     f"needs the command to run")


def class_name(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[-_.]+", name) if part)


def shape_of(shape: object, depends_on: object, python: object, env: object, test: object) -> PythonShape:
    if shape == "binary":
        raise ValueError("shape 'binary' is built with firn's part F (si#449); use shape 'python'")
    if shape != "python":
        raise ValueError(f"shape must be 'python' (or 'binary', built with firn's part F, si#449), got {shape!r}")
    if not isinstance(python, str) or not _PYTHON_FORMULA.match(python):
        raise ValueError(f"python must name a python formula such as 'python@3.14' (python@3.<minor>), "
                         f"got {python!r}")
    if not isinstance(depends_on, (list, tuple)) or not all(isinstance(d, str) and d for d in depends_on):
        raise ValueError(f"depends_on must be a list of formula names, got {depends_on!r}")
    if not isinstance(env, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ValueError(f"env must be a mapping of strings to strings, got {env!r}")
    if not isinstance(test, Mapping) or set(test) != {"args", "expect"}:
        raise ValueError(f"test must be a mapping with exactly the keys args and expect, got {test!r}")
    args, expect = test["args"], test["expect"]
    if not isinstance(args, (list, tuple)) or not all(isinstance(a, str) for a in args):
        raise ValueError(f"test.args must be a list of strings, got {args!r}")
    if not isinstance(expect, str) or not expect:
        raise ValueError(f"test.expect must be a non-empty string, got {expect!r}")
    return PythonShape(tuple(depends_on), python, dict(env), tuple(args), expect)


def _ruby(text: str) -> str:
    """Make `text` safe inside a Ruby double-quoted string: no quote, escape or interpolation survives."""
    return re.sub(r"#(?=[{@$])", r"\\#", text.replace("\\", "\\\\").replace('"', '\\"'))


def render(meta: WheelMeta, url: str, sha256: str, resources: Sequence[Resource], shape: PythonShape) -> str:
    venv_python = "python" + shape.python.split("@", 1)[1]
    if meta.version not in meta.filename:
        raise ValueError(f"the wheel file name {meta.filename} does not contain its METADATA version "
                         f"{meta.version}, so the formula cannot name it as #{{version}}; rebuild the wheel")
    wheel_in_build = "#{version}".join(_ruby(part) for part in meta.filename.split(meta.version))
    command = " ".join([f"#{{bin}}/{_ruby(meta.command)}", *(_ruby(shlex.quote(a)) for a in shape.test_args)])
    lines = [f"class {class_name(meta.name)} < Formula",
             "  include Language::Python::Virtualenv", "",
             f'  desc "{_ruby(meta.summary)}"',
             f'  homepage "{_ruby(meta.homepage)}"',
             f'  url "{_ruby(url)}", using: :nounzip',
             f'  sha256 "{sha256}"',
             f'  license "{_ruby(meta.license)}"', ""]
    lines += [f'  depends_on "{_ruby(d)}"' for d in sorted(set(shape.depends_on) | {shape.python})] + [""]
    for res in sorted(resources, key=lambda r: r.name.lower()):
        lines += [f'  resource "{_ruby(res.name.lower())}" do', f'    url "{_ruby(res.url)}"',
                  f'    sha256 "{res.sha256}"', "  end", ""]
    lines += ["  def install"]
    lines += [f'    ENV["{_ruby(k)}"] = "{_ruby(v)}"' for k, v in sorted(shape.env.items())]
    lines += [f'    venv = virtualenv_create(libexec, "{venv_python}")',
              "    venv.pip_install resources",
              f'    venv.pip_install_and_link buildpath/"{wheel_in_build}"',
              "  end", "",
              "  test do",
              f'    assert_match "{_ruby(shape.test_expect)}", shell_output("{command}")',
              "  end", "end", ""]
    return "\n".join(lines)
