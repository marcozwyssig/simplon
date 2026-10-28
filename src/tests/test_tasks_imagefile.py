"""si#552: `build:image-file` copies one file out of an image, for the platform its file entry names.

Decided 2026-10-28 (si#552, Marco's item 4): the kind `file` carries an optional `platform:`, exactly one, and
`build:image-file` reads it - a file entry without one, or with one the image does not declare, is refused
before docker is asked.

`test:file` runs that file alone in `imagefile.FILE_TEST_IMAGE`, for the same entry's platform, under a required
time limit, and records the file's sha256 as the subject a release compares with (si#553).

AAA; the name states the behaviour under test. Nothing touches docker: the command line is a recorder whose
`docker cp` leaves behind what a real one would - a regular file, or a directory.
"""
import hashlib
import json
import os
import stat
import subprocess

import pytest
from test_tasks_image import _INDEX_AMD64_ONLY, _INDEX_BOTH, _SINGLE_MANIFEST

from simplon.adapters import docker, githubpackages
from simplon.kernel.run import Result
from simplon.manifest import catalogue, context
from simplon.manifest import load as manifest_mod
from simplon.manifest import results as results_mod
from simplon.manifest.context import ProductContext
from simplon.tasks import image, imagefile

_MANIFEST = """
product: demo
artifacts:
  firn-image:
    kind: image
    registry: ghcr.io/owner
    repository: firn
    dockerfile: Dockerfile
    context: .
    tag: v1.0
    platforms: [linux/amd64, linux/arm64]
  amd-only:
    kind: image
    registry: ghcr.io/owner
    repository: amd-only
    dockerfile: Dockerfile
    context: .
    tag: v1.0
    platforms: [linux/amd64]
  single:
    kind: image
    registry: ghcr.io/owner
    repository: single
    dockerfile: Dockerfile
    context: .
    tag: v1.0
  elsewhere:
    kind: image
    registry: registry.example.com/team
    repository: firn
    dockerfile: Dockerfile
    context: .
    tag: v1.0
    platforms: [linux/amd64, linux/arm64]
  firn-arm64:
    kind: file
    path: build/firn-linux-arm64
    platform: linux/arm64
  firn-amd64:
    kind: file
    path: build/firn-linux-amd64
    platform: linux/amd64
  firn-anywhere:
    kind: file
    path: build/firn
"""

REF = "ghcr.io/owner/firn:v1.0"


@pytest.fixture
def product(tmp_path, monkeypatch):
    (tmp_path / "demo.yaml").write_text(_MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))
    monkeypatch.setattr(docker, "ensure_docker", lambda: None)
    return tmp_path


class _Cli:
    """The command line, recorded with the `DOCKER_CONFIG` each call ran under. `docker cp` leaves `copied`
    at its destination: "file" or "dir". `oras manifest fetch` answers `index`, or fails when it is None."""

    def __init__(self, copied="file"):
        self.calls: list[list[str]] = []
        self.configs: list[str | None] = []
        self.copied = copied
        self.index: str | None = _INDEX_BOTH

    def run(self, argv, **kwargs) -> Result:
        argv = list(argv)
        self.calls.append(argv)
        self.configs.append(os.environ.get("DOCKER_CONFIG"))
        if argv[:3] == ["oras", "manifest", "fetch"]:
            if self.index is None:
                return Result(rc=1, out="", err="Error: ghcr.io/owner/firn:v9.9: not found")
            return Result(rc=0, out=self.index, err="")
        if argv[:2] == ["docker", "cp"]:
            from pathlib import Path
            dest = Path(argv[-1])
            if self.copied == "dir":
                dest.mkdir(parents=True)
                (dest / "inner").write_text("x", encoding="utf-8")
            else:
                dest.write_bytes(b"\x7fELF firn")
        if argv[:4] == ["docker", "image", "inspect", "--format"]:
            return Result(rc=0, out="sha256:image-id\n", err="")
        return Result(rc=0, out="", err="")

    def docker_calls(self) -> list[list[str]]:
        return [c for c in self.calls if c[:1] == ["docker"]]


@pytest.fixture
def cli(monkeypatch):
    fake = _Cli()
    monkeypatch.setattr(image, "run", fake.run)
    monkeypatch.setattr(imagefile, "run", fake.run)
    return fake


@pytest.fixture
def built(monkeypatch):
    """`build:image` recorded arm64 and amd64 under REF."""
    recorded = {"linux/arm64": "sha256:aa", "linux/amd64": "sha256:bb"}
    monkeypatch.setattr(image, "read_built", lambda name, ref: dict(recorded) if ref == REF else {})
    return recorded


# --- the field ------------------------------------------------------------------------------------------

def test_a_file_entry_carries_its_platform(product):
    # arrange: the catalogue checks the section's keys at load, and the command binds the task's ports
    text = ("product: demo\n"
            "ci:\n  build:\n    commands:\n"
            "      firn-arm64: { task: \"build:image-file\", consumes: { image: firn-image }, "
            "produces: { file: firn-arm64 }, with: { inside: /firn } }\n"
            + _MANIFEST.split("product: demo\n", 1)[1])

    # act
    loaded = manifest_mod.load(text, catalogue=catalogue.load(), manifest_path="demo.yaml")
    entry, root = imagefile.file_entry("firn-arm64", "build:image-file")

    # assert
    assert loaded is not None
    assert entry.platform == "linux/arm64"
    assert entry.path == "build/firn-linux-arm64"
    assert root == product


# --- refusals before docker -----------------------------------------------------------------------------

def test_extract_refuses_a_file_entry_without_platform(product, cli, built, capsys):
    # act
    rc = imagefile.extract(name="firn-image", file="firn-anywhere", inside="/firn")

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert "platform:" in err and "firn-anywhere" in err
    assert cli.docker_calls() == []


def test_extract_refuses_a_platform_the_image_does_not_declare(product, cli, built, capsys):
    # act
    rc = imagefile.extract(name="amd-only", file="firn-arm64", inside="/firn")

    # assert: the entry at fault, and both ways out
    err = capsys.readouterr().err
    assert rc == 1
    assert "linux/arm64" in err and "linux/amd64" in err
    assert "artifacts.firn-arm64.platform" in err
    assert "Change the file entry's `platform:`" in err
    assert "add linux/arm64 to `platforms:` on `artifacts.amd-only`" in err
    assert cli.docker_calls() == []


def test_extract_refuses_an_image_without_platforms(product, cli, built, capsys):
    # act
    rc = imagefile.extract(name="single", file="firn-arm64", inside="/firn")

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert "declare `platforms:`" in err.replace("Declare", "declare")
    # not `_platform_declared`'s way out: the file entry's `platform:` is required, so it cannot be dropped
    assert "drop `platform:`" not in err
    assert cli.docker_calls() == []


def test_extract_refuses_a_relative_path_inside_the_image(product, cli, built, capsys):
    # act
    rc = imagefile.extract(name="firn-image", file="firn-arm64", inside="firn")

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert "absolute" in err and "firn" in err
    assert cli.docker_calls() == []


def test_extract_refuses_without_a_recorded_build(product, cli, monkeypatch, capsys):
    # arrange
    monkeypatch.setattr(image, "read_built", lambda name, ref: {})

    # act
    rc = imagefile.extract(name="firn-image", file="firn-arm64", inside="/firn")

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert "build:image" in err and "firn-image" in err and "linux/arm64" in err
    assert not [c for c in cli.calls if c[:2] == ["docker", "create"]]


# --- the copy -------------------------------------------------------------------------------------------

def test_extract_copies_from_the_platform_reference_and_writes_0755(product, cli, built):
    # act
    rc = imagefile.extract(name="firn-image", file="firn-arm64", inside="/firn")

    # assert: created from arm64's own reference, copied following a symlink, removed
    assert rc == 0
    created = [c for c in cli.calls if c[:2] == ["docker", "create"]]
    assert len(created) == 1
    assert created[0][-2:] == [image.platform_reference(REF, "linux/arm64"), imagefile.NEVER_STARTED]
    container = created[0][created[0].index("--name") + 1]
    copies = [c for c in cli.calls if c[:2] == ["docker", "cp"]]
    assert len(copies) == 1 and copies[0][:4] == ["docker", "cp", "-L", f"{container}:/firn"]
    assert cli.calls.index(copies[0]) < cli.calls.index(["docker", "rm", container])
    out = product / "build/firn-linux-arm64"
    assert out.read_bytes() == b"\x7fELF firn"
    assert stat.S_IMODE(out.stat().st_mode) == 0o755
    assert sorted(p.name for p in out.parent.iterdir()) == ["firn-linux-arm64"]


def test_extract_refuses_a_directory_and_leaves_nothing(product, cli, built, capsys):
    # arrange
    cli.copied = "dir"

    # act
    rc = imagefile.extract(name="firn-image", file="firn-arm64", inside="/firn")

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert "/firn" in err and "is not a regular file" in err
    out = product / "build/firn-linux-arm64"
    assert not out.exists()
    assert list(out.parent.iterdir()) == []
    created = [c for c in cli.calls if c[:2] == ["docker", "create"]][0]
    container = created[created.index("--name") + 1]
    assert ["docker", "rm", container] in cli.calls


# --- with a tag: the published image, by the platform's digest -----------------------------------------

PUBLISHED = "ghcr.io/owner/firn:v2.0"


@pytest.fixture
def registry(monkeypatch, tmp_path):
    """oras is on hand, the GitHub login records the config it wrote into, and nothing reads a local build:
    with a tag the published image is the source, whatever this checkout built."""
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / "operator"))
    logins: list[str] = []
    monkeypatch.setattr(githubpackages, "require_oras", lambda: None)
    monkeypatch.setattr(githubpackages, "docker_login",
                        lambda registry, **kw: logins.append(os.environ["DOCKER_CONFIG"]))

    def _no_local_build(name, ref):
        raise AssertionError("a tag reads the registry, not this checkout's build")

    monkeypatch.setattr(image, "read_built", _no_local_build)
    return logins


def _pulls(cli) -> list[list[str]]:
    return [c for c in cli.calls if c[:2] == ["docker", "pull"]]


def test_tag_pulls_the_platforms_digest_from_the_index(product, cli, registry, tmp_path):
    # act
    rc = imagefile.extract(name="firn-image", file="firn-arm64", inside="/firn", tag="v2.0")

    # assert: the index was read, arm64's digest pulled and copied from, all inside one scoped login
    assert rc == 0
    fetches = [c for c in cli.calls if c[:3] == ["oras", "manifest", "fetch"]]
    assert fetches == [["oras", "manifest", "fetch", PUBLISHED]]
    by_digest = "ghcr.io/owner/firn@sha256:f674"
    assert _pulls(cli) == [["docker", "pull", by_digest]]
    created = [c for c in cli.calls if c[:2] == ["docker", "create"]]
    assert len(created) == 1 and created[0][-2:] == [by_digest, imagefile.NEVER_STARTED]
    scope = registry[0]
    assert scope != str(tmp_path / "operator")
    for call in (fetches[0], _pulls(cli)[0], created[0]):
        assert cli.configs[cli.calls.index(call)] == scope
    assert os.environ["DOCKER_CONFIG"] == str(tmp_path / "operator")
    assert (product / "build/firn-linux-arm64").read_bytes() == b"\x7fELF firn"


def test_tag_takes_a_variant_the_registry_added(product, cli, registry):
    # arrange: a registry may publish `linux/arm64/v8` for a declared `linux/arm64`, as missing_platforms reads
    cli.index = _INDEX_BOTH.replace('"architecture": "arm64", "os": "linux"',
                                    '"architecture": "arm64", "os": "linux", "variant": "v8"')

    # act
    rc = imagefile.extract(name="firn-image", file="firn-arm64", inside="/firn", tag="v2.0")

    # assert
    assert rc == 0
    assert _pulls(cli) == [["docker", "pull", "ghcr.io/owner/firn@sha256:f674"]]


def test_tag_refuses_a_tag_the_registry_does_not_serve(product, cli, registry, capsys):
    # arrange
    cli.index = None

    # act
    rc = imagefile.extract(name="firn-image", file="firn-arm64", inside="/firn", tag="v2.0")

    # assert: both causes, oras's own words, the GitHub token as the way to read - never "no index"
    err = capsys.readouterr().err
    assert rc == 1
    assert f"{PUBLISHED} could not be read from the registry" in err
    assert "not found" in err
    assert "not published" in err and "may not read it" in err
    assert "GITHUB_TOKEN" in err
    assert "index" not in err
    assert _pulls(cli) == []
    assert not [c for c in cli.calls if c[:2] == ["docker", "create"]]


def test_a_failed_fetch_from_a_foreign_registry_names_docker_login(product, cli, registry, monkeypatch, capsys):
    # arrange: a 401 and an absent tag look alike from here, so both causes are named
    monkeypatch.setattr(docker, "has_stored_login", lambda host: True)
    cli.index = None

    # act
    rc = imagefile.extract(name="elsewhere", file="firn-arm64", inside="/firn", tag="v2.0")

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert "not published" in err and "may not read it" in err
    assert "if the registry needs a login: `docker login registry.example.com`" in err
    assert _pulls(cli) == []


def test_tag_refuses_an_index_without_the_platform(product, cli, registry, capsys):
    # arrange
    cli.index = _INDEX_AMD64_ONLY

    # act
    rc = imagefile.extract(name="firn-image", file="firn-arm64", inside="/firn", tag="v2.0")

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert PUBLISHED in err and "linux/arm64" in err
    assert "its index carries linux/amd64" in err
    assert _pulls(cli) == []


def test_tag_refuses_a_single_manifest(product, cli, registry, capsys):
    # arrange
    cli.index = _SINGLE_MANIFEST

    # act
    rc = imagefile.extract(name="firn-image", file="firn-arm64", inside="/firn", tag="v2.0")

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert PUBLISHED in err and "not a multi-platform index" in err
    assert _pulls(cli) == []


def test_tag_reads_a_foreign_registry_without_a_stored_login(product, cli, registry, monkeypatch):
    # arrange: no credential for the host - a public image pulls anonymously, so nothing refuses before trying
    monkeypatch.setattr(docker, "has_stored_login", lambda host: False)

    # act
    rc = imagefile.extract(name="elsewhere", file="firn-arm64", inside="/firn", tag="v2.0")

    # assert: no GitHub token minted for it, and the registry was asked
    assert rc == 0
    assert registry == []
    assert ["oras", "manifest", "fetch", "registry.example.com/team/firn:v2.0"] in cli.calls
    assert _pulls(cli) == [["docker", "pull", "registry.example.com/team/firn@sha256:f674"]]


def test_tag_reads_github_packages_anonymously_without_a_token(product, cli, registry, monkeypatch, tmp_path):
    # arrange: no GITHUB_TOKEN and no `gh` - a public package still pulls without one
    def _no_token(registry, **kw):
        raise githubpackages.PackageError("no GitHub token: GITHUB_TOKEN is not set")

    monkeypatch.setattr(githubpackages, "docker_login", _no_token)

    # act
    rc = imagefile.extract(name="firn-image", file="firn-arm64", inside="/firn", tag="v2.0")

    # assert: fetched and pulled anyway, inside a scope rather than the operator's config
    assert rc == 0
    assert _pulls(cli) == [["docker", "pull", "ghcr.io/owner/firn@sha256:f674"]]
    assert cli.configs[cli.calls.index(_pulls(cli)[0])] not in (None, str(tmp_path / "operator"))


def test_tag_pulls_from_a_foreign_registry_with_the_operators_login(product, cli, registry, monkeypatch, tmp_path):
    # arrange: a stored login lives in the operator's config, which a scope would leave behind

    # act
    rc = imagefile.extract(name="elsewhere", file="firn-arm64", inside="/firn", tag="v2.0")

    # assert
    assert rc == 0
    assert registry == []
    assert _pulls(cli) == [["docker", "pull", "registry.example.com/team/firn@sha256:f674"]]
    assert cli.configs[cli.calls.index(_pulls(cli)[0])] == str(tmp_path / "operator")


# --- test:file: the bare file, run in a pinned libc-free container -------------------------------------

_BYTES = b"\x7fELF firn arm64"


class _Docker:
    """The command line for `check`: `docker run` answers `answer` (rc, out, err), or raises
    `subprocess.TimeoutExpired` when `answer` is None; every call is recorded with its keyword arguments."""

    def __init__(self):
        self.calls: list[tuple[list[str], dict]] = []
        self.answer: tuple[int, str, str] | None = (0, "firn v1.0.0\n", "")

    def run(self, argv, **kwargs) -> Result:
        argv = list(argv)
        self.calls.append((argv, kwargs))
        if argv[:2] == ["docker", "run"]:
            if self.answer is None:
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
            rc, out, err = self.answer
            return Result(rc=rc, out=out, err=err)
        return Result(rc=0, out="", err="")

    def runs(self) -> list[tuple[list[str], dict]]:
        return [(argv, kw) for argv, kw in self.calls if argv[:2] == ["docker", "run"]]


@pytest.fixture
def box(product, monkeypatch):
    """The arm64 file `build:image-file` wrote, a test result to record into, and a recorded docker."""
    (product / "build").mkdir()
    (product / "build/firn-linux-arm64").write_bytes(_BYTES)
    text = (product / "demo.yaml").read_text(encoding="utf-8")
    (product / "demo.yaml").write_text(
        text + "  firn-checked: { kind: test-result, path: build/test/firn.json }\n", encoding="utf-8")
    fake = _Docker()
    monkeypatch.setattr(imagefile, "run", fake.run)
    monkeypatch.setattr(docker, "run", fake.run)

    def _no_git(root):
        raise AssertionError("a tag was given or none is expected, so git is not asked")

    monkeypatch.setattr(image, "provenance", _no_git)
    return fake


def _record(product) -> dict:
    return json.loads((product / "build/test/firn.json").read_text(encoding="utf-8"))


def test_check_refuses_without_a_timeout(product, box, capsys):
    # arrange: yesterday's green record, which must not outlive the refusal
    stale = product / "build/test/firn.json"
    stale.parent.mkdir(parents=True)
    stale.write_text('{"file": "firn-arm64", "verdict": 0, "runs": []}\n', encoding="utf-8")

    # act
    rc = imagefile.check(file="firn-arm64", argv="--version", tag="v1.0.0", timeout=0, results="firn-checked")

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert "timeout" in err
    assert box.calls == []
    assert not stale.exists()


def test_check_runs_the_file_in_the_pinned_image(product, box):
    # act
    rc = imagefile.check(file="firn-arm64", argv="--version 'two words'", expect="firn", timeout=5)

    # assert: the Global Constraints line, for the entry's platform, under a time limit
    assert rc == 0
    [(argv, kwargs)] = box.runs()
    name = argv[argv.index("--name") + 1]
    assert argv == ["docker", "run", "--rm", "-i", "--platform", "linux/arm64", "--network", "none",
                    *docker.lifecycle_args(name, "demo"),
                    "-v", f"{product}/build/firn-linux-arm64:/run/file:ro",
                    imagefile.FILE_TEST_IMAGE, "/run/file", "--version", "two words"]
    assert kwargs["timeout"] == 5
    assert imagefile.FILE_TEST_IMAGE.startswith("busybox:1.37.0-musl@sha256:")


def test_check_omits_platform_for_an_entry_without_one(product, box):
    # arrange
    (product / "build/firn").write_bytes(_BYTES)

    # act
    rc = imagefile.check(file="firn-anywhere", argv="--version", timeout=5)

    # assert: the host's platform, by saying none
    assert rc == 0
    [(argv, _)] = box.runs()
    assert "--platform" not in argv


def test_check_feeds_stdin_from_the_product(product, box):
    # arrange
    request = product / "tests/lsp/initialize.json"
    request.parent.mkdir(parents=True)
    request.write_text('{"jsonrpc": "2.0", "method": "initialize"}\n', encoding="utf-8")

    # act
    rc = imagefile.check(file="firn-arm64", argv="lsp", stdin="tests/lsp/initialize.json", timeout=5)

    # assert
    assert rc == 0
    [(_, kwargs)] = box.runs()
    assert kwargs["input_text"] == '{"jsonrpc": "2.0", "method": "initialize"}\n'


def test_check_refuses_stdin_outside_the_product(product, box, capsys):
    # act
    rc = imagefile.check(file="firn-arm64", argv="lsp", stdin="../secrets.json", timeout=5)

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert "stdin" in err and "product root" in err
    assert box.runs() == []


def test_check_expands_tag_in_expect(product, box):
    # act
    rc = imagefile.check(file="firn-arm64", argv="--version", expect="firn {tag}", tag="v1.0.0", timeout=5)

    # assert
    assert rc == 0


def test_check_without_tag_expects_the_derived_version(product, box, monkeypatch, capsys):
    # arrange
    monkeypatch.setattr(image, "provenance", lambda root: {image.VERSION_ARG: "v2.0.0"})

    # act
    rc = imagefile.check(file="firn-arm64", argv="--version", expect="firn {tag}", timeout=5)

    # assert: the file printed v1.0.0, and v2.0.0 was expected
    err = capsys.readouterr().err
    assert rc == 1
    assert "firn v2.0.0" in err


def test_check_writes_the_record_naming_the_files_sha256(product, box):
    # act
    rc = imagefile.check(file="firn-arm64", argv="--version", expect="firn", timeout=5, results="firn-checked")

    # assert: the subject si#553 compares with what it uploads
    assert rc == 0
    record = _record(product)
    assert record == {"file": "firn-arm64", "verdict": 0,
                      "runs": [{"reference": "build/firn-linux-arm64",
                                "id": "sha256:" + hashlib.sha256(_BYTES).hexdigest(),
                                "platform": "linux/arm64", "argv": "--version", "expected_rc": 0, "rc": 0,
                                "verdict": 0}]}
    assert results_mod._subjects("firn-checked", record) is not None


def test_a_changed_file_gets_a_new_id(product, box):
    # arrange
    imagefile.check(file="firn-arm64", argv="--version", timeout=5, results="firn-checked")
    before = _record(product)["runs"][0]["id"]
    (product / "build/firn-linux-arm64").write_bytes(_BYTES + b" rebuilt")

    # act
    imagefile.check(file="firn-arm64", argv="--version", timeout=5, results="firn-checked")

    # assert
    after = _record(product)["runs"][0]["id"]
    assert after != before
    assert after == "sha256:" + hashlib.sha256(_BYTES + b" rebuilt").hexdigest()


def test_check_red_on_timeout_removes_the_container(product, box, capsys):
    # arrange
    box.answer = None

    # act
    rc = imagefile.check(file="firn-arm64", argv="lsp", timeout=5, results="firn-checked")

    # assert
    err = capsys.readouterr().err
    assert rc != 0
    assert "no answer within 5 s" in err
    [(argv, _)] = box.runs()
    name = argv[argv.index("--name") + 1]
    assert (["docker", "rm", "-f", name]) in [c for c, _ in box.calls]
    assert _record(product)["verdict"] != 0


def test_check_red_writes_the_record(product, box):
    # arrange
    box.answer = (3, "", "boom")

    # act
    rc = imagefile.check(file="firn-arm64", argv="--version", timeout=5, results="firn-checked")

    # assert
    assert rc == 3
    record = _record(product)
    assert record["verdict"] == 3 and record["runs"][0]["rc"] == 3


def test_check_on_a_foreign_platform_without_emulation_carries_the_advice(product, box, capsys):
    # arrange
    box.answer = (1, "", "exec /run/file: exec format error\n")

    # act
    rc = imagefile.check(file="firn-arm64", argv="--version", timeout=5)

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert image._emulation_advice(["linux/arm64"]).strip() in err


def test_check_refuses_a_file_build_image_file_has_not_written(product, box, capsys):
    # act
    rc = imagefile.check(file="firn-amd64", argv="--version", timeout=5)

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert "build/firn-linux-amd64" in err and "build:image-file" in err
    assert box.runs() == []
