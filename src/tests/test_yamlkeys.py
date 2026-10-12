"""A key written twice in one mapping is refused, at both manifest seams (si#344 B2, decision 4).

PyYAML keeps the last of two equal keys and drops the first without a word; cleon's manifest carried
`release:` and `support:` twice that way. AAA throughout.
"""
import pytest
import yaml

from simplon import catalogue, context, yamlkeys
from simplon.context import ProductContext
from simplon.orchestrator import manifest

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
        "simplon manifest migrate cleon.yaml drops a second copy that is the first line for line; copies "
        "that differ are merged by hand")


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
