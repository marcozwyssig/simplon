"""`test:homebrew-formula` against the real brew image (si#536). Needs docker and the network.

The red case is measured behaviour (spec D): `brew audit --strict` is red on a `desc` that starts with an
article. The green case is the whole dry run on the real 0.36.0 wheel: `build:homebrew-formula` with
`source: local` and the real closure (Task 3's measurement), then this check with `online: false`, whose
resource digests are compared with the real PyPI.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request

import pytest

from conftest import docker_is_usable
from simplon.adapters import pypi
from simplon.manifest import context
from simplon.tasks import homebrewformula as hf
from simplon.tasks import homebrewtap
from test_homebrew_render import make_wheel

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to run the brew image in")

WHEEL = "simplon-0.36.0-py3-none-any.whl"
MANIFEST = ("product: sample\nartifacts:\n"
            "  dist: { kind: directory, path: dist }\n"
            "  formula: { kind: homebrew-formula, path: build/homebrew/simplon.rb }\n"
            "  checked: { kind: test-result, path: build/results/homebrew.json }\n")
#: simplon's own formula inputs, as the prototype behind homebrew-tap#1 used them.
SHAPE = dict(shape="python", depends_on=["cryptography", "libsodium", "libyaml", "pydantic"], python="python@3.14",
             env={"SODIUM_INSTALL": "system"}, test={"args": ["--version"], "expect": "simplon"})


@pytest.fixture
def product(tmp_path, monkeypatch):
    (tmp_path / "sample.yaml").write_text(MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext("sample", tmp_path, tmp_path / "sample.yaml"))
    return tmp_path


def _record(root):
    return json.loads((root / "build" / "results" / "homebrew.json").read_text(encoding="utf-8"))


@needs_docker
def test_audit_is_red_on_a_desc_with_an_article(product, capsys):
    # arrange: a formula whose desc is "A tool", with the placeholder URL and no resources to look up
    wheel = make_wheel(product / "dist", summary="A tool")
    meta = hf.wheel_meta(wheel)
    shape = hf.shape_of("python", [], "python@3.14", {}, {"args": ["--version"], "expect": "simplon"})
    out = product / "build" / "homebrew" / "simplon.rb"
    out.parent.mkdir(parents=True)
    out.write_text(hf.render(meta, hf.PLACEHOLDER + WHEEL, meta.sha256, [], shape), encoding="utf-8")

    # act
    rc = homebrewtap.check(formula="formula", wheel="dist", results="checked", online="false")

    # assert: red from audit alone - the digests are right - and the record says so
    said = capsys.readouterr()
    assert rc == 1, said.out + said.err
    run = _record(product)["runs"][0]
    assert (run["problems"], run["verdict"]) == ([], 1)
    assert run["audit_rc"] != 0
    assert "article" in (said.out + said.err).lower()


@needs_docker
def test_the_0_36_0_dry_run_formula_is_green(product, capsys):
    # arrange: the real wheel, rendered by build:homebrew-formula with `source: local` and the real closure
    wheel_file = next(f for f in pypi.files("simplon", "0.36.0") if f.filename == WHEEL)
    dist = product / "dist"
    dist.mkdir()
    with urllib.request.urlopen(wheel_file.url, timeout=60) as r:
        (dist / WHEEL).write_bytes(r.read())
    assert hashlib.sha256((dist / WHEEL).read_bytes()).hexdigest() == wheel_file.sha256
    # the closure mounts the wheel's directory for the image's own user (uid 1000); pytest's tmp_path is 0700
    product.chmod(0o755)
    dist.chmod(0o755)
    assert hf.build(wheel="dist", formula="formula", source="local", **SHAPE) == 0

    # act
    rc = homebrewtap.check(formula="formula", wheel="dist", results="checked", online="false")

    # assert
    said = capsys.readouterr()
    assert rc == 0, said.out + said.err
    record = _record(product)
    # the resource digests were really compared with PyPI: the rendered formula carries the closure
    assert homebrewtap.formula_digests((product / "build" / "homebrew" / "simplon.rb").read_text())[1]
    digest = hashlib.sha256((product / "build" / "homebrew" / "simplon.rb").read_bytes()).hexdigest()
    assert (record["formula"], record["verdict"], record["runs"][0]["id"]) == ("simplon", 0, "sha256:" + digest)
