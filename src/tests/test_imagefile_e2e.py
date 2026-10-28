"""si#552, end to end: `build:image-file` and `test:file` against real docker, two platforms and a registry.

The spec's acceptance item 1: simplon proves both tasks on an image of its own before firn's release does.
`fixtures/imagefile` builds a static `/hello` (`--version` says `hello <VERSION>`, `--hang` never returns,
`--net` says whether the run has a route out, anything else echoes stdin), the same source dynamically linked as `/hello-dynamic`, and a directory `/adir`,
for linux/amd64 and linux/arm64. The local build goes through the kernel's own `build:image`, so the
`built-<name>.json` the copy reads is the one a product's build writes; arm64 runs under QEMU, which ghr-8
has (`docker buildx ls` lists linux/arm64).

THE `tag:` PATH reads a real registry: a `registry:2` container on a free loopback port, the image pushed to
it as an index with `docker buildx build --push` (controller ruling R2: not `release:image`, whose gates
are not under test here). The registry is reached as `localhost:<port>`, because that is the spelling both
clients treat as plain HTTP without being told: measured 2026-10-28, `oras manifest fetch
localhost:<port>/...` answers, while `127.0.0.1:<port>/...` is refused with "http: server gave HTTP response
to HTTPS client" - so the kernel needs no insecure-registry setting for this proof.

Every container and image these tests start is removed in a `finally`: the build's per-platform references,
the registry, and anything still carrying this run's `simplon.run` label.

AAA; the name states the behaviour under test.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import time
import urllib.request
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as NoAnswer
from pathlib import Path

import pytest

from conftest import docker_is_usable
from simplon.kernel.run import run
from simplon.manifest import context
from simplon.manifest.context import ProductContext
from simplon.tasks import image, imagefile

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to build an image in")

pytestmark = needs_docker

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "imagefile"

#: The registry the `tag:` tests publish to, pinned by its index digest (read 2026-10-28).
REGISTRY_IMAGE = "registry:2@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373"

#: Stamped into the image as VERSION, and so the tag the build resolves and `hello --version` answers with.
VERSION = "v0.0.1-si552"

PLATFORMS = ("linux/amd64", "linux/arm64")

#: ELF `e_machine` (offset 18, little-endian) per platform: proves the bytes are the platform's own, not the
#: other one's under its name.
ELF_MACHINE = {"linux/amd64": 0x3E, "linux/arm64": 0xB7}

_MANIFEST = """
product: {product}
artifacts:
  hello-image:
    kind: image
    registry: {registry}
    repository: hello
    dockerfile: Dockerfile
    context: .
    build_args: {{ VERSION: {version} }}
    platforms: [linux/amd64, linux/arm64]
  hello-amd64: {{ kind: file, path: build/files/hello-linux-amd64, platform: linux/amd64 }}
  hello-arm64: {{ kind: file, path: build/files/hello-linux-arm64, platform: linux/arm64 }}
  hello-dynamic-amd64: {{ kind: file, path: build/files/hello-dynamic-linux-amd64, platform: linux/amd64 }}
  hello-checked: {{ kind: test-result, path: build/test/hello.json }}
"""


def _entry(platform: str) -> str:
    return "hello-" + platform.split("/")[1]


def _product(root: Path, registry: str) -> ProductContext:
    """A product under `root`: the fixture's Dockerfile and source, and a manifest publishing to `registry`."""
    shutil.copytree(FIXTURE, root, dirs_exist_ok=True)
    name = f"si552-{uuid.uuid4().hex[:8]}"
    path = root / f"{name}.yaml"
    path.write_text(_MANIFEST.format(product=name, registry=registry, version=VERSION), encoding="utf-8")
    return ProductContext(name, root, path)


def _left_by(product: str) -> list[str]:
    """Every container, running or not, that carries this product's run label."""
    return run(["docker", "ps", "-a", "-q", "--filter", f"label=simplon.run={product}"]).out.split()


def _remove_everything_of(product: str, references: list[str]) -> None:
    for cid in _left_by(product):
        run(["docker", "rm", "-f", cid])
    for ref in references:
        run(["docker", "image", "rm", "-f", ref])


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Iterator[ProductContext]:
    """The fixture image, built for both platforms by the kernel's own `build:image`."""
    ctx = _product(tmp_path_factory.mktemp("built"), "localhost:5999/si552e2e")
    ref = f"localhost:5999/si552e2e/hello:{VERSION}"
    previous, path = context._current, os.environ.get("PATH", "")
    context._current = ctx
    try:
        assert image.build(name="hello-image") == 0, "build:image did not build the fixture"
        yield ctx
    finally:
        context._current = previous
        os.environ["PATH"] = path
        _remove_everything_of(ctx.name, [ref, *(image.platform_reference(ref, p) for p in PLATFORMS)])


@pytest.fixture
def product(built, monkeypatch) -> ProductContext:
    """`built` registered as this test's product, and nothing of its label left afterwards."""
    monkeypatch.setattr(context, "_current", built)
    yield built
    for cid in _left_by(built.name):
        run(["docker", "rm", "-f", cid])


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _push(root: Path, ref: str, platforms: str, *extra: str) -> None:
    pushed = run(["docker", "buildx", "build", "--builder", image.BUILDER, "--platform", platforms,
                  "--build-arg", f"VERSION={VERSION}", "--tag", ref, "--push", *extra, str(root)])
    assert pushed.ok, f"pushing {ref} failed: {pushed.err or pushed.out}"


@pytest.fixture(scope="module")
def published(built, tmp_path_factory) -> Iterator[tuple[ProductContext, str]]:
    """A `registry:2` on a free loopback port holding the fixture image under three tags: `VERSION` (an index
    of both platforms), `amd64-only` (an index without arm64) and `single` (one manifest, no index).

    Depends on `built` only so the builder exists and the layers are cached."""
    port = _free_port()
    registry = f"localhost:{port}/si552e2e"
    ctx = _product(tmp_path_factory.mktemp("published"), registry)
    repository = f"{registry}/hello"
    path = os.environ.get("PATH", "")
    container = f"si552-registry-{uuid.uuid4().hex[:8]}"
    try:
        started = run(["docker", "run", "-d", "--rm", "--name", container, "-p", f"127.0.0.1:{port}:5000",
                       REGISTRY_IMAGE])
        assert started.ok, f"registry:2 did not start: {started.err}"
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen(f"http://localhost:{port}/v2/", timeout=2):
                    break
            except OSError:
                assert time.monotonic() < deadline, "registry:2 never answered /v2/"
                time.sleep(0.3)
        _push(ctx.root, f"{repository}:{VERSION}", ",".join(PLATFORMS))
        # `mode=min` provenance makes even one platform an index, so this is "index without arm64" ...
        _push(ctx.root, f"{repository}:amd64-only", "linux/amd64", "--provenance=mode=min")
        # ... and with no attestation at all one platform is one manifest.
        _push(ctx.root, f"{repository}:single", "linux/amd64", "--provenance=false", "--sbom=false")
        yield ctx, repository
    finally:
        os.environ["PATH"] = path
        pulled = run(["docker", "image", "ls", "-q", repository]).out.split()
        _remove_everything_of(ctx.name, sorted(set(pulled)))
        run(["docker", "rm", "-f", container])


@pytest.fixture
def registered(published, monkeypatch) -> ProductContext:
    """`published`'s product registered as this test's product."""
    monkeypatch.setattr(context, "_current", published[0])
    return published[0]


def _record(ctx: ProductContext) -> dict:
    return json.loads((ctx.root / "build/test/hello.json").read_text(encoding="utf-8"))


def _machine(path: Path) -> int:
    return int.from_bytes(path.read_bytes()[18:20], "little")


def test_both_platforms_are_taken_out_and_answer(product):
    for platform in PLATFORMS:
        # arrange
        entry = _entry(platform)
        out = product.root / f"build/files/hello-linux-{platform.split('/')[1]}"

        # act
        extracted = imagefile.extract(name="hello-image", file=entry, inside="/hello")
        verdict = imagefile.check(file=entry, argv="--version", expect="hello {tag}", tag=VERSION, timeout=60,
                                  results="hello-checked")

        # assert: the platform's own bytes, executable, answering with the tag, and the record names them
        assert extracted == 0, platform
        assert _machine(out) == ELF_MACHINE[platform], platform
        assert os.access(out, os.X_OK)
        assert verdict == 0, platform
        run_ = _record(product)["runs"][0]
        assert (run_["platform"], run_["verdict"]) == (platform, 0)
        assert run_["id"] == "sha256:" + hashlib.sha256(out.read_bytes()).hexdigest()


def test_stdin_reaches_the_file(product):
    # arrange
    said = f"stdin for si552 {uuid.uuid4().hex}"
    (product.root / "stdin.txt").write_text(said + "\n", encoding="utf-8")
    assert imagefile.extract(name="hello-image", file="hello-amd64", inside="/hello") == 0

    # act
    verdict = imagefile.check(file="hello-amd64", expect=said, stdin="stdin.txt", timeout=30)

    # assert
    assert verdict == 0


def test_a_dynamically_linked_file_is_red(product, capsys):
    # arrange: the same source, linked against musl's loader, which FILE_TEST_IMAGE does not have
    assert imagefile.extract(name="hello-image", file="hello-dynamic-amd64", inside="/hello-dynamic") == 0
    capsys.readouterr()

    # act
    verdict = imagefile.check(file="hello-dynamic-amd64", argv="--version", timeout=30)

    # assert: red, with the loader's absence in what the run said. Under `--init` the words are tini's:
    # "[FATAL tini (7)] exec /run/file failed: No such file or directory", rc 127 (measured 2026-10-28)
    assert verdict != 0
    assert "no such file or directory" in capsys.readouterr().err.lower()


def test_a_directory_is_refused_and_no_container_is_left(product, capsys):
    # arrange
    out = product.root / "build/files/hello-linux-amd64"
    before = out.read_bytes() if out.exists() else None

    # act
    rc = imagefile.extract(name="hello-image", file="hello-amd64", inside="/adir")

    # assert: refused, the entry's path untouched, and the copy's container gone
    assert rc == 1
    assert "not a regular file" in capsys.readouterr().err
    assert (out.read_bytes() if out.exists() else None) == before
    assert _left_by(product.name) == []


def test_the_file_runs_without_a_network(product):
    # arrange
    assert imagefile.extract(name="hello-image", file="hello-amd64", inside="/hello") == 0

    # act
    verdict = imagefile.check(file="hello-amd64", argv="--net", expect="network: unreachable", timeout=30)

    # assert
    assert verdict == 0


def test_a_hanging_file_is_red_within_its_timeout(product, capsys):
    # arrange
    assert imagefile.extract(name="hello-image", file="hello-amd64", inside="/hello") == 0
    capsys.readouterr()

    # act: in a thread this test can stop waiting for, so a lost time limit is a red test and not a hung
    # suite; the `product` fixture then removes the container, which ends the run
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(imagefile.check, file="hello-amd64", argv="--hang", timeout=3)
        try:
            verdict = running.result(timeout=15)
        except NoAnswer:
            for cid in _left_by(product.name):
                run(["docker", "rm", "-f", cid])
            pytest.fail("test:file gave no verdict within 15 s for a 3 s timeout")
    took = time.monotonic() - started

    # assert: red, said so, inside its limit plus the stop, and the container is gone
    assert verdict != 0
    assert "no answer within 3 s" in capsys.readouterr().err
    assert took < 10, f"the run took {took:.1f} s"
    assert _left_by(product.name) == []


def test_tag_reads_the_index_from_a_registry(registered, capsys):
    for platform in PLATFORMS:
        # act
        started = time.monotonic()
        extracted = imagefile.extract(name="hello-image", file=_entry(platform), inside="/hello", tag=VERSION)
        took = time.monotonic() - started
        verdict = imagefile.check(file=_entry(platform), argv="--version", expect="hello {tag}", tag=VERSION,
                                  timeout=60)

        # assert
        assert extracted == 0, platform
        assert _machine(registered.root / f"build/files/hello-linux-{platform.split('/')[1]}") == ELF_MACHINE[platform]
        assert verdict == 0, platform
        with capsys.disabled():
            print(f"\nsi552 measure: build:image-file --tag {VERSION} for {platform} took {took:.2f} s")


def test_a_tag_the_registry_does_not_serve_is_refused(registered, capsys):
    # act
    rc = imagefile.extract(name="hello-image", file="hello-amd64", inside="/hello", tag="v9.9.9-never")

    # assert
    assert rc == 1
    assert "could not be read from the registry" in capsys.readouterr().err


def test_a_single_manifest_is_refused_as_not_an_index(registered, capsys):
    # act
    rc = imagefile.extract(name="hello-image", file="hello-amd64", inside="/hello", tag="single")

    # assert
    assert rc == 1
    assert "not a multi-platform index" in capsys.readouterr().err


def test_a_platform_the_index_does_not_carry_is_refused(registered, capsys):
    # act
    rc = imagefile.extract(name="hello-image", file="hello-arm64", inside="/hello", tag="amd64-only")

    # assert
    assert rc == 1
    assert "published without linux/arm64" in capsys.readouterr().err
