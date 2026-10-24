"""A generated Homebrew formula, checked before it reaches a tap (si#536).

`check` is the body of `test:homebrew-formula`. It runs `brew audit` and `brew style` on the formula in a
throwaway local tap inside the pinned brew image (`homebrewclosure.BREW_IMAGE`), and it checks what audit
does not (measured: a wrong sha256 passes audit): the formula's `sha256` against the local wheel, and on a
real run against PyPI's digest for that wheel too, and every resource's `sha256` against PyPI's.

`online` says which run this is, with no default, because the two are different checks: `false` on a dry
run, whose formula carries the placeholder URL (`homebrewformula.PLACEHOLDER`) that `--online` and `--new`
are red on (measured), and `true` after the PyPI upload. It is a string, not a bool: a bool parameter is a
CLI flag, and a step's `params: {online: false}` is rendered as a value a flag cannot take.

THE RECORD IS WRITTEN FOR EVERY VERDICT, RED INCLUDED, AND FOR NOTHING ELSE. A release reads it as evidence
(`results.tested()`): its one run names the formula's path as `reference` and the file's digest as `id`, so a
formula changed after the test is not the one the record vouches for. A run that reaches no verdict (a bad
`online`, a missing input, an audit container that did not get to audit) writes none and removes the one an
earlier run left, so yesterday's green does not outlive today's refusal. A failed PyPI lookup during the
digest checks is a red verdict that names the file: the digest was not confirmed, and a release must not
read that as green.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote, urlparse

from simplon.adapters import docker, pypi
from simplon.kernel import log
from simplon.kernel.run import run
from simplon.manifest import artifactsection, context
from simplon.model import artifactschema
from simplon.tasks import homebrewformula
from simplon.tasks.homebrewformula import Resource

COORDINATE = "test:homebrew-formula"
ARTIFACTS = "artifacts"
ONLINE = ("true", "false")

#: Seconds the audit container may take: tapping, the formula API download, audit and style.
AUDIT_TIMEOUT_S = 900

TAIL_LINES = 20
_RC = re.compile(r"^--- simplon (audit|style) rc=(\d+) ---$")
_QUOTED = r'"((?:[^"\\]|\\.)*)"'
_TOP_URL = re.compile(r"^  url " + _QUOTED)
_TOP_SHA = re.compile(r"^  sha256 " + _QUOTED)
_RESOURCE = re.compile(r"^  resource " + _QUOTED + r" do$")
_RES_URL = re.compile(r"^    url " + _QUOTED)
_RES_SHA = re.compile(r"^    sha256 " + _QUOTED)
_SDIST = re.compile(r"\.(tar\.gz|tar\.bz2|zip)$")


class Digests(NamedTuple):
    url: str
    sha256: str
    resources: list[Resource]


def _unruby(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)


def _digests(text: str) -> Digests:
    """The formula's top-level `url` and `sha256`, and each resource block's. A formula without them is not
    one `build:homebrew-formula` rendered: a ValueError names what is missing."""
    url = sha = ""
    resources: list[Resource] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        if current is not None:
            if line == "  end":
                if not current.get("url") or not current.get("sha256"):
                    raise ValueError(f"the formula's resource '{current['name']}' has no url or no sha256; "
                                     f"render it again with build:homebrew-formula")
                resources.append(Resource(current["name"], current["url"], current["sha256"]))
                current = None
            elif m := _RES_URL.match(line):
                current["url"] = _unruby(m.group(1))
            elif m := _RES_SHA.match(line):
                current["sha256"] = _unruby(m.group(1))
        elif m := _RESOURCE.match(line):
            current = {"name": _unruby(m.group(1))}
        elif m := _TOP_URL.match(line):
            url = _unruby(m.group(1))
        elif m := _TOP_SHA.match(line):
            sha = _unruby(m.group(1))
    if current is not None:
        raise ValueError(f"the formula's resource '{current['name']}' has no closing `end`; render it again "
                         f"with build:homebrew-formula")
    if not url or not sha:
        raise ValueError("the formula has no top-level url or no top-level sha256; render it again with "
                         "build:homebrew-formula")
    return Digests(url, sha, resources)


def formula_digests(text: str) -> tuple[str, list[Resource]]:
    """The formula's top-level `sha256` and each resource block, as `build:homebrew-formula` renders them."""
    found = _digests(text)
    return found.sha256, found.resources


def check(formula: str = "", wheel: str = "", results: str = "", online: str = "") -> int:
    """Audit the formula in the brew image, check its digests, and write the verdict record to `results`."""
    record = _results_path(results) if results else None
    # An earlier run's record goes before any refusal below, so its verdict does not outlive this run.
    if record is not None:
        record.unlink(missing_ok=True)
    if online not in ONLINE:
        raise ValueError(f"online must be 'true' (a real run, after the PyPI upload) or 'false' (a dry run), got "
                         f"{online!r}; bind it with `params:` on each of the two steps")
    ctx = context.current()
    formula_rel = Path(str(_entry(formula, "formula", artifactschema.Homebrew_formulaEntry).path))
    wheel_dir = ctx.root / str(_entry(wheel, "wheel", artifactschema.DirectoryEntry).path)
    path = ctx.root / formula_rel
    if not path.is_file():
        raise ValueError(f"{formula_rel} does not exist; render it first with build:homebrew-formula")
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    found = _digests(text)
    meta = homebrewformula.wheel_meta(homebrewformula.the_wheel(wheel_dir))
    name = path.stem
    is_online = online == "true"

    problems = _top_problems(found, meta, is_online) + [p for r in found.resources for p in _resource_problems(r)]
    for line in problems:
        log.error(line)
    audit_rc, style_rc = audit(text, name, is_online)
    if audit_rc:
        log.error(f"brew audit is red on {formula_rel} (rc {audit_rc}); its output is above")
    if style_rc:
        log.error(f"brew style is red on {formula_rel} (rc {style_rc}); its output is above")
    verdict = 1 if problems or audit_rc or style_rc else 0
    if not is_online:
        log.info("online false: only `brew audit --strict` ran, and the formula's sha256 was compared with the "
                 "local wheel only; `--online --new` and the comparison with PyPI's digest run only on a real "
                 "run (online true)")
    if record is not None:
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({
            "formula": name, "verdict": verdict,
            "runs": [{"reference": formula_rel.as_posix(), "id": "sha256:" + hashlib.sha256(raw).hexdigest(),
                      "online": is_online, "audit_rc": audit_rc, "style_rc": style_rc, "problems": problems,
                      "verdict": verdict}]}, indent=2) + "\n", encoding="utf-8")
    if verdict == 0:
        log.ok(f"{formula_rel}: brew audit, brew style and every digest are green (online {online})")
    return verdict


def _top_problems(found: Digests, meta: homebrewformula.WheelMeta, online: bool) -> list[str]:
    """What is wrong with the formula's own url and sha256: against the local wheel always, and on a real run
    against PyPI's file for that wheel."""
    out = []
    if found.sha256 != meta.sha256:
        out.append(f"the formula's sha256 {found.sha256} is not the local wheel's {meta.sha256} "
                   f"({meta.filename}); render the formula from this wheel again")
    if not online:
        return out
    if found.url.startswith(homebrewformula.PLACEHOLDER):
        out.append(f"the formula's url {found.url} is the dry-run placeholder, and this is a real run (online "
                   f"true); render it with `source: pypi` after the upload")
    try:
        listed = pypi.files(meta.name, meta.version, index=homebrewformula.PYPI_INDEX)
    except pypi.PyPIError as e:
        return out + [f"PyPI's digest for {meta.filename} could not be read, so the formula's sha256 is "
                      f"unconfirmed: {e}"]
    on_pypi = [f for f in listed if f.filename == meta.filename]
    if not on_pypi:
        out.append(f"PyPI lists {meta.name} {meta.version} but not as the file {meta.filename} (it lists: "
                   f"{', '.join(f.filename for f in listed) or 'no files'}); upload this wheel, or rerun once "
                   f"PyPI shows it")
    elif on_pypi[0].sha256 != found.sha256:
        out.append(f"PyPI's {meta.filename} has sha256 {on_pypi[0].sha256}, the formula {found.sha256}: the "
                   f"formula does not name the uploaded file. Render it again with `source: pypi`")
    return out


def _resource_problems(res: Resource) -> list[str]:
    """What is wrong with one resource: PyPI must list its url's file, with the sha256 the formula names."""
    filename = unquote(urlparse(res.url).path.rsplit("/", 1)[-1])
    stem = _SDIST.sub("", filename)
    if stem == filename or "-" not in stem:
        return [f"resource '{res.name}' has the url {res.url}, which names no sdist "
                f"(<name>-<version>.tar.gz); render the formula again with build:homebrew-formula"]
    version = stem.rsplit("-", 1)[1]
    try:
        listed = pypi.files(res.name, version, index=homebrewformula.PYPI_INDEX)
    except pypi.PyPIError as e:
        return [f"resource '{res.name}': PyPI's digest for {filename} could not be read, so its sha256 is "
                f"unconfirmed: {e}"]
    found = [f for f in listed if f.filename == filename]
    if not found:
        return [f"resource '{res.name}': PyPI lists {res.name} {version} but not the file {filename} (it lists: "
                f"{', '.join(f.filename for f in listed) or 'no files'}); render the formula again"]
    if found[0].sha256 != res.sha256:
        return [f"resource '{res.name}': PyPI's {filename} has sha256 {found[0].sha256}, the formula "
                f"{res.sha256}; render the formula again"]
    return []


def script(name: str, online: bool) -> str:
    """The bash the container runs: a throwaway tap, the formula from stdin into it, audit, then style."""
    quoted = shlex.quote(f"local/check/{name}")
    flags = "--strict --online --new" if online else "--strict"
    return "\n".join([
        "set -euo pipefail",
        "export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ANALYTICS=1",
        "brew tap-new --no-git local/check >&2",
        f'cat > "$(brew --repository local/check)/Formula/"{shlex.quote(name + ".rb")}',
        "set +e",
        f"brew audit {flags} {quoted}",
        'echo "--- simplon audit rc=$? ---"',
        f"brew style {quoted}",
        'echo "--- simplon style rc=$? ---"',
    ])


def audit(text: str, name: str, online: bool) -> tuple[int, int]:
    """`(audit rc, style rc)` for the formula `text`, tapped as `local/check/<name>` in the brew image.

    The formula reaches the container on stdin, so no host path has to be readable by the image's own user.
    A run that does not print both result lines did not get to audit: that is a ValueError with its last
    lines, never a red verdict.
    """
    # lazy: the closure module validates its pinned image at import, and the part above imports anywhere
    from simplon.tasks.homebrewclosure import BREW_IMAGE
    container, lifecycle = docker.lifecycle()
    argv = ["docker", "run", "--rm", "-i", "--network", "bridge", *lifecycle, BREW_IMAGE,
            "bash", "-c", script(name, online)]
    try:
        with docker.stopped_on_interrupt(container):
            result = run(argv, timeout=AUDIT_TIMEOUT_S, input_text=text)
    except subprocess.TimeoutExpired as e:
        raise ValueError(f"auditing {name} in {BREW_IMAGE} took longer than AUDIT_TIMEOUT_S ({AUDIT_TIMEOUT_S} s) "
                         f"and was stopped; rerun it, and raise AUDIT_TIMEOUT_S if brew is that slow") from e
    if result.out:
        log.info(result.out.rstrip("\n"))
    return parse(result.out, result.err)


def parse(stdout: str, stderr: str) -> tuple[int, int]:
    """The audit and style rc lines the container printed. A missing one means the run never got there."""
    rcs: dict[str, int] = {}
    for line in stdout.splitlines():
        if m := _RC.match(line):
            rcs[m.group(1)] = int(m.group(2))
    missing = [step for step in ("audit", "style") if step not in rcs]
    if missing:
        tail = "\n".join((stderr.rstrip("\n") + "\n" + stdout).rstrip("\n").splitlines()[-TAIL_LINES:])
        raise ValueError(f"the brew run printed no {' and no '.join(missing)} result line, so it did not get to "
                         f"check the formula and there is no verdict. Last lines:\n{tail}")
    return rcs["audit"], rcs["style"]


def _results_path(name: str) -> Path:
    """The absolute path of the `test-result` artifact `name`."""
    return context.current().root / str(_entry(name, "results", artifactschema.Test_resultEntry).path)


def _entry(name: str, param: str, wanted: type[artifactsection.Entry]) -> artifactsection.Entry:
    """The `artifacts:` entry the port binding `param` names, validated as `wanted`'s kind."""
    if not name:
        raise ValueError(f"which artifact? bind `{param}` with `consumes:` or `produces:` from the "
                         f"`{ARTIFACTS}:` section, or pass --{param}")
    ctx = context.current()
    section = ctx.manifest_data().get(ARTIFACTS) or {}
    if name not in section:
        raise ValueError(f"no artifact '{name}' in {ctx.manifest_path.name}'s `{ARTIFACTS}:` section; "
                         f"declared are: {', '.join(sorted(section)) or '(none)'}")
    return artifactsection.entry(section, name, wanted, ctx.manifest_path.name, COORDINATE, param=param)
