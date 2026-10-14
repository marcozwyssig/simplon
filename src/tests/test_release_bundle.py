"""si#344 C.3: a release is one aggregate that names one `kind: release` bundle (spec C.4, C.5 rule 8).

AAA; the name states the behaviour under test.
"""
from pathlib import Path

import pytest

from simplon.domain import catalogue, manifest

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
    assert loaded.spec_for("release", "all").produces == {"release": ("app-release",)}


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
    assert spec.produces == {"release": ("kernel-release",)}
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
PORTS = ROOT / "src" / "simplon" / "domain" / "ports.py"


def _raised_in(function):
    """Each `raise ValueError(f"...")` in `function` of ports.py, its f-string pieces joined and every
    substitution kept as `{}` - adjacent f-strings are one JoinedStr once parsed, as the census reads them."""
    import ast
    tree = ast.parse(PORTS.read_text(encoding="utf-8"))
    body = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function)
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


@pytest.mark.parametrize("rule, function", [(6, "_check_release"), (8, "_check_bundles")])
def test_every_refusal_the_manifest_page_quotes_is_the_real_message(rule, function):
    # arrange
    quoted = _quoted_under(rule)
    raised = _raised_in(function)

    # act
    unmatched = [q for q in quoted if not any(q in r for r in raised)]

    # assert
    assert quoted, f"the page quotes no refusal under rule {rule} - the extraction no longer finds them"
    assert unmatched == []
