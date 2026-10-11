"""si#346 / spec D.1: `simplon.manifest` models exactly the top-level sections the kernel reads.

Both directions. A kernel reader with no property here, and a property here with no reader, are each
red, because a typed list is wrong on the first day nobody checks it, and this one is checked against
the census's derived population, not against a list.
"""
import re
from pathlib import Path

from simplon import manifestmodel
from test_refusal_census import sections_read

M2 = Path(__file__).resolve().parents[1] / "firn" / "model" / "simplon" / "manifest" / "manifest.firn"

# `key` and `data` are the resource's own bookkeeping. `environments` is structure, not a section: since
# si#344 the environment matrix lives under `cd:`, so the kernel reads no top-level `environments`, but
# the bridge exports the matrix as Product.environments (simplon.pipeline.Environment). `product:` is not
# in sections_read() either (the kernel never reads it), so there is nothing to remove from `read`.
# `default` is `cd: default:` beside the matrix, for the same reason - a top-level `default:` is refused.
_STRUCTURE = {"key", "data", "environments", "default"}


def _product_properties() -> set[str]:
    text = M2.read_text(encoding="utf-8")
    block = re.search(r"^Product typeOf .*?^\}", text, re.MULTILINE | re.DOTALL)
    assert block, "manifest.firn declares no Product class"
    return set(re.findall(r"^\s+property (\w+) typeOf", block.group(0), re.MULTILINE)) - _STRUCTURE


def test_the_manifest_package_models_exactly_what_the_kernel_reads():
    # arrange
    read = {manifestmodel.mangle(section) for section in sections_read()}

    # act
    modelled = _product_properties()

    # assert
    assert read - modelled == set(), f"read by the kernel, not modelled: {sorted(read - modelled)}"
    assert modelled - read == set(), f"modelled, read by nothing: {sorted(modelled - read)}"


def test_the_bridges_typed_section_list_is_the_census_and_the_model():
    # arrange: KERNEL_SECTIONS is typed (src/firn/ is no part of the simplon package), so it is the third
    # copy, and it is held by both of the other two - the census that derives the set, and the Product it
    # models
    typed = manifestmodel.KERNEL_SECTIONS

    # act / assert
    assert list(typed) == sorted(sections_read())
    assert {manifestmodel.mangle(section) for section in typed} == _product_properties()
