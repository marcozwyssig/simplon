"""A key written twice in one mapping is refused, at both manifest seams (si#344 B2, decision 4).

PyYAML keeps the last of two equal keys and drops the first without a word; cleon's manifest carried
`release:` and `support:` twice that way. AAA throughout.
"""
import pytest
import yaml

from simplon.manifest import catalogue, context, yamlkeys
from simplon.manifest.context import ProductContext
from simplon.manifest import load as manifest

import realmanifests


def test_a_key_written_twice_names_the_key_and_both_lines():
    # arrange
    text = "a: 1\nb:\n  c: 1\n  c: 2\n"

    # act
    with pytest.raises(yaml.YAMLError) as caught:
        yamlkeys.load(text)

    # assert
    assert caught.value.problem_mark.line + 1 == 4
    assert caught.value.problem == ("found `c:` a second time (first on line 3); YAML would keep only this "
                                    "copy, so the first one is lost")


def test_two_spellings_of_one_boolean_key_are_a_duplicate():
    # arrange: review finding M4 - YAML 1.1 reads both as True and keeps only the second
    text = "flags:\n  yes: 1\n  true: 2\n"

    # act
    with pytest.raises(yaml.YAMLError) as caught:
        yamlkeys.load(text)

    # assert
    assert caught.value.problem == ("found `true:` a second time (first on line 2, as `yes:`); YAML would keep "
                                    "only this copy, so the first one is lost")


def test_a_merge_key_and_the_key_that_overrides_it_are_not_a_duplicate():
    # act
    data = yamlkeys.load("base: &b {a: 1, b: 2}\nx:\n  <<: *b\n  a: 3\n")

    # assert
    assert data == {"base": {"a": 1, "b": 2}, "x": {"a": 3, "b": 2}}


def test_the_loader_refuses_cleons_doubled_group_in_a_sentence_of_its_own():
    # act
    with pytest.raises(ValueError) as caught:
        manifest.load((realmanifests.FIXTURES / "cleon.yaml").read_text(), catalogue=catalogue.load(),
                      manifest_path="cleon.yaml")

    # assert: a refusal of its own (ruling T4a) - the document parses, and the sentence says what it lost
    assert str(caught.value) == (
        "cleon.yaml writes a key twice:\n  line 233, column 3: found `release:` a second time (first on "
        "line 215); YAML would keep only this copy, so the first one is lost\n"
        "A second copy that is the first line for line is dropped by the migration; copies that differ are "
        "merged by hand. Rewrite it with the migration, which loads no manifest and so works on this one:\n"
        "  venv:      <orch-dir>/.venv/bin/simplon manifest migrate cleon.yaml\n"
        "  container: docker run --rm --user \"$(id -u):$(id -g)\" -v \"$PWD:/src\" -w /src <kernel image> "
        "simplon manifest migrate cleon.yaml")


def test_the_products_load_fills_the_way_out_with_the_launchers_paths(tmp_path, monkeypatch):
    # arrange: re-review - a bare `simplon` is not on PATH; both routes, filled the way the cut's are
    (tmp_path / "image.pin").write_text("# pin\nghcr.io/marcozwyssig/simplon:v0.28.0\n", encoding="utf-8")
    monkeypatch.setenv("LAUNCH_ORCH_DIR", str(tmp_path / "deploy" / "orchestrator"))
    monkeypatch.setenv("LAUNCH_IMAGE_PIN", str(tmp_path / "image.pin"))
    path = tmp_path / "demo.yaml"
    path.write_text("product: demo\nproduct: demo\n", encoding="utf-8")

    # act
    with pytest.raises(ValueError) as caught:
        ProductContext("demo", tmp_path, path).manifest()

    # assert
    message = str(caught.value)
    assert message.startswith(f"{path} writes a key twice:\n  line 2, column 1: found `product:` a second time")
    assert "  venv:      deploy/orchestrator/.venv/bin/simplon manifest migrate demo.yaml\n" in message
    assert message.endswith("-w /src ghcr.io/marcozwyssig/simplon:v0.28.0 simplon manifest migrate demo.yaml")


#: Review finding I1: `common` merged into an anchored mapping that overrides it, and that mapping merged
#: elsewhere. `yaml.safe_load` accepts it; PyYAML's `flatten_mapping` rewrites the anchored node in place,
#: so a check made during construction saw the merged-in `retries` and the override as two copies.
MERGED_OVERRIDE = ("product: demo\n"
                   "common: &common {retries: 1}\n"
                   "ci:\n"
                   "  build:\n"
                   "    defaults: &builddefaults\n"
                   "      <<: *common\n"
                   "      retries: 2\n"
                   "extra:\n"
                   "  <<: *builddefaults\n")


def test_an_override_beside_a_merge_in_a_mapping_merged_elsewhere_is_not_a_duplicate():
    # act
    data = yamlkeys.load(MERGED_OVERRIDE)

    # assert
    assert data == yaml.safe_load(MERGED_OVERRIDE)


def test_the_product_context_refuses_it_too_and_names_the_file(tmp_path, monkeypatch):
    # arrange
    path = tmp_path / "demo.yaml"
    path.write_text("product: demo\nproduct: other\n", encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("demo", tmp_path, path))

    # act
    with pytest.raises(RuntimeError) as caught:
        context.current().manifest_data()

    # assert: the file, not "<unicode string>", and both lines
    assert f'in "{path}", line 2, column 1' in str(caught.value)
    assert "found `product:` a second time (first on line 1)" in str(caught.value)
