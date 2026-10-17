"""si#344 C.3: a release is one aggregate that names one `kind: release` bundle (spec C.4, C.5 rule 8).

AAA; the name states the behaviour under test.
"""
from pathlib import Path

from simplon.model.command import ReleaseCommand
import pytest

from simplon.manifest import catalogue, load as manifest

ROOT = Path(__file__).resolve().parents[2]

HEAD = """
product: demo
artifacts:
  app: { kind: image, registry: ghcr.io/o, repository: app, dockerfile: Dockerfile, context: . }
  app-checked: { kind: test-result, path: build/test/app.json }
  app-notes: { kind: release-notes, path: build/release/notes.md }
  app-tag: { kind: tag }
  app-release: { kind: release }
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
  test:
    commands:
      image: { task: "test:image", consumes: { image: app }, produces: { test-result: app-checked } }
  release:
    commands:
      notes: { task: "release:notes", produces: { release-notes: app-notes } }
      publish:  { task: "release:image", consumes: { image: app, evidence: [app-checked] } }
      tag:   { task: "release:tag", consumes: { release-notes: app-notes }, produces: { tag: app-tag } }
"""
# The publish leaf is `publish`: `depends_on` names a leaf by a bare name that one group owns (#519), and
# `image` is also `build image` and `test image` here, while `support git push` owns `push`.


def _all(deps, extra, stop="stop_on_failure: true, "):
    return HEAD + f"      all: {{ depends_on: [{deps}], help: 'h', {stop}{extra} }}\n"


def _load(text):
    return manifest.load(text, catalogue=catalogue.load(), manifest_path="demo.yaml")


def test_a_release_aggregate_names_its_bundle():
    # arrange
    text = _all("notes, publish, tag", "produces: { release: app-release }")

    # act
    loaded = _load(text)

    # assert
    spec = loaded.spec_for("release", "all")
    assert isinstance(spec, ReleaseCommand) and spec.release == "app-release"   # si#400 4d


def test_an_aggregate_outside_ci_release_naming_an_output_is_refused():
    # arrange
    stray = ("      all: { depends_on: [publish], help: 'h', stop_on_failure: true,"
             " produces: { release: app-release } }\n")
    text = HEAD.replace("  test:\n    commands:\n", "  test:\n    commands:\n" + stray)

    # act / assert
    with pytest.raises(ValueError, match="only an aggregate under `ci: release:` does"):
        _load(text)


def test_a_release_aggregate_naming_two_outputs_is_refused():
    # arrange
    text = _all("notes, publish, tag", "produces: { release: app-release, tag: app-tag }")

    # act / assert
    with pytest.raises(ValueError, match="a release aggregate names exactly one output"):
        _load(text)


def test_a_bundle_that_is_not_a_release_is_refused():
    # arrange
    text = _all("notes, publish, tag", "produces: { release: app-tag }")

    # act / assert
    with pytest.raises(ValueError, match="the bundle is a `kind: release`"):
        _load(text)


def test_a_tag_planned_before_a_publish_is_refused():
    # arrange
    text = _all("notes, tag, publish", "produces: { release: app-release }")

    # act / assert
    with pytest.raises(ValueError, match="plans 'tag' before 'publish'"):
        _load(text)


def test_an_aggregate_consuming_is_still_refused():
    # arrange
    text = _all("notes, publish, tag", "consumes: { image: app }")

    # act / assert
    with pytest.raises(ValueError, match="an aggregate runs no task"):
        _load(text)


def test_the_kernels_own_release_aggregate_loads():
    # act
    loaded = _load((ROOT / "simplon.yaml").read_text(encoding="utf-8"))

    # assert
    spec = loaded.spec_for("release", "all")
    assert isinstance(spec, ReleaseCommand) and spec.release == "kernel-release"   # si#400 4d
    assert loaded.plan_for("all", group="release")[-1] == "tag"


def test_an_aggregate_output_written_as_a_bare_string_is_refused():
    # arrange
    text = _all("notes, publish, tag", "produces: app-release")

    # act / assert
    with pytest.raises(ValueError, match="an aggregate's one output is written"):
        _load(text)


def test_a_bundle_the_artifacts_section_does_not_declare_is_refused():
    # arrange
    text = _all("notes, publish, tag", "produces: { release: nowhere }")

    # act / assert
    with pytest.raises(ValueError, match="declare it with `kind: release`"):
        _load(text)


def test_a_release_aggregate_that_does_not_stop_on_failure_is_refused():
    # arrange: without the flag a failed publish does not stop the plan, and the tag after it is still cut
    text = _all("notes, publish, tag", "produces: { release: app-release }", stop="")

    # act / assert
    with pytest.raises(ValueError, match="names a release and leaves `stop_on_failure` false - without it a "
                                         "failed publish leaf does not stop the plan"):
        _load(text)


def test_the_kernels_own_release_aggregate_stops_on_failure():
    # act
    loaded = _load((ROOT / "simplon.yaml").read_text(encoding="utf-8"))

    # assert
    assert loaded.spec_for("release", "all").stop_on_failure is True


# --- the refusal fragments the manifest page quotes are a second source (final review of si#344 C.3) ---

PAGE = ROOT / "src" / "site" / "content" / "how" / "manifest.md"
PORTS = ROOT / "src" / "simplon" / "manifest" / "ports.py"
MANIFEST_PY = ROOT / "src" / "simplon" / "manifest" / "load.py"


def _raised_in(*functions):
    """Each `raise ValueError(f"...")` in the named `(source, function)` pairs, its f-string pieces joined and
    every substitution kept as `{}` - adjacent f-strings are one JoinedStr once parsed, as the census reads
    them. Rule 8 sits in two: its shape half moved to `manifest._command` with si#400 4d."""
    import ast
    texts = []
    for source, function in functions:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        body = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function)
        texts += _raises(body)
    return texts


def _raises(body):
    import ast
    texts = []
    for node in ast.walk(body):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
            arg = node.exc.args[0]
            parts = arg.values if isinstance(arg, ast.JoinedStr) else [arg]
            texts.append("".join(p.value if isinstance(p, ast.Constant) else "{}" for p in parts))
    return texts


def _quoted_under(rule):
    """The `"... <fragment> ..."` quotes in the page's `**Rule <n>.**` bullet, whitespace folded."""
    import re
    text = PAGE.read_text(encoding="utf-8")
    bullet = re.search(rf"^- \*\*Rule {rule}\.\*\*(.*?)(?=^- |^\n)", text, re.S | re.M).group(1)
    return [" ".join(q.split()) for q in re.findall(r'"\.\.\. (.+?)(?: \.\.\.)?"', bullet, re.S)]


@pytest.mark.parametrize("rule, functions", [
    (6, ((PORTS, "_check_release"),)),
    (8, ((PORTS, "_check_bundles"), (MANIFEST_PY, "_command"))),
], ids=["6", "8"])
def test_every_refusal_the_manifest_page_quotes_is_the_real_message(rule, functions):
    # arrange
    quoted = _quoted_under(rule)
    raised = _raised_in(*functions)

    # act
    unmatched = [q for q in quoted if not any(q in r for r in raised)]

    # assert
    assert quoted, f"the page quotes no refusal under rule {rule} - the extraction no longer finds them"
    assert unmatched == []


# --- si#486: `github-release` refines `release` ----------------------------------------------------------
# Decided by Marco on 2026-10-17: a GitHub Release IS a release bundle. These pin what that touches.

GH = HEAD.replace("  app-release: { kind: release }\n",
                  "  app-release: { kind: release }\n  app-gh: { kind: github-release }\n") + \
    "      gh-publish: { task: \"release:github-publish\", produces: { github-release: app-gh } }\n"


def test_a_github_release_produced_by_a_leaf_is_in_the_model_export():
    # arrange: `app-gh` is produced by a leaf and named by no aggregate
    import yaml
    from simplon.manifest import manifestmodel

    # act
    text = manifestmodel.export(_load(GH), yaml.safe_load(GH), "demo", manifestmodel.KERNEL_SECTIONS)

    # assert: the skip at manifestmodel's `release` refinement must not drop an artifact no aggregate composes
    assert '"app-gh"' in text, "a release-refining artifact no aggregate names vanished from the model"


def test_an_aggregate_may_name_a_github_release_as_its_bundle():
    # act
    loaded = _load(GH + "      all: { depends_on: [notes, publish, tag], help: 'h', stop_on_failure: true, "
                        "produces: { release: app-gh } }\n")

    # assert
    spec = loaded.spec_for("release", "all")
    assert isinstance(spec, ReleaseCommand) and spec.release == "app-gh"


BOTH = GH + ("      all: { depends_on: [notes, publish, tag, gh-publish], help: 'h', stop_on_failure: true, "
             "produces: { release: app-gh } }\n")


def test_an_aggregate_whose_bundle_its_publish_leaf_produces_loads():
    # act / assert: measured on si#486 - the loader has no one-producer rule that refuses it
    assert _load(BOTH).spec_for("release", "all").release == "app-gh"


@pytest.mark.xfail(strict=True, reason="si#489: whether an aggregate's bundle may be its publish leaf's output "
                                       "is undecided, and the export then references a bundle it composed elsewhere")
def test_the_export_of_a_bundle_its_leaf_produces_references_only_what_it_declares():
    # arrange
    import re

    import yaml
    from simplon.manifest import manifestmodel

    # act
    text = manifestmodel.export(_load(BOTH), yaml.safe_load(BOTH), "demo", manifestmodel.KERNEL_SECTIONS)

    # assert: every product.demo.demo.a_<x> a command produces is declared at the product's own level
    produced = set(re.findall(r"produces = product\.demo\.demo\.(a_\w+)", text))
    declared = set(re.findall(r"^  artifacts (a_\w+) typeOf", text, re.MULTILINE))
    assert produced <= declared, produced - declared
