"""The eight frozen manifests (fixtures/manifests), as their products hand them to the migration.

TWO hand edits, and each is the product's, not the kernel's. The fixture files stay frozen (README: "Do not
refresh these files"); each edit is made in memory, the way the product makes it.

- cleon's `updatesite` is published by cleon's own code (`orchestrator.cli:publish_updatesite`), so no
  catalogue coordinate says which kind it is, and the migration refuses it by name (si#344 B2, decision 5).
  cleon writes `kind: directory` itself.
- firn's `build toolchain` collides with `support toolchain`, which the kernel places since si#550:
  `deploy devcontainer` names it by bare name, and the load refuses the ambiguity. firn renames its
  command (firn#1126); `toolchain-image` stands in for whatever name firn picks, and `RENAMED` lets a
  test hold the rest of firn's surface to its golden.
"""
from pathlib import Path

import yaml

FIXTURES = Path(__file__).parent / "fixtures" / "manifests"

#: product -> [(the anchor, what the product's own edit makes of it), ...]
HAND_EDITS = {
    "cleon": [("  updatesite:\n", "  updatesite:\n    kind: directory\n")],
    "firn": [('      toolchain:\n        task: "build:image"\n',
              '      toolchain-image:\n        task: "build:image"\n'),
             ("depends_on: [preflight, toolchain, extension, devcontainer-only]",
              "depends_on: [preflight, toolchain-image, extension, devcontainer-only]")],
}

#: product -> {(group, the command's name in the fixture): its name after the product's own edit}
RENAMED = {"firn": {("build", "toolchain"): "toolchain-image"}}


def text(product: str) -> str:
    """The fixture's text, with the product's own hand edits applied when it has any."""
    raw = (FIXTURES / f"{product}.yaml").read_text(encoding="utf-8")
    for anchor, edited in HAND_EDITS.get(product, []):
        assert raw.count(anchor) == 1, f"{product}: the hand edit's anchor {anchor!r} is not there exactly once"
        raw = raw.replace(anchor, edited)
    return raw

#: The products whose migrated fixture the release rule refuses (si#344 C.3): each releases an image no test
#: writes a result about. Measured over the eight on 2026-10-14; the live manifests agree (si#344 C.3 plan).
RELEASE_RULE_BILL = frozenset({"agile-cockpit", "firn", "simplon"})

#: product -> (the release command that publishes the image, the image). What the bill's products would have
#: to say to pass rule 6; the fixtures are pre-A form and frozen, so the answer is made in memory, on the
#: MIGRATED text (si#344 C.3). Only simplon's live manifest answers the rule today.
RELEASE_RULE_ANSWERS = {
    "agile-cockpit": ("image", "app"),
    "firn": ("push-image", "firn"),
    "simplon": ("image", "kernel"),
}

#: The one command (under `ci: test:`) and the one artifact `answer_release_rule` adds. firn already has six
#: `test:image` commands on its image, none writing a result; one more is the smallest edit that is truthful,
#: since binding all six would make each of them write a result it does not today.
ADDED_TEST_COMMAND = "release-evidence"


def answer_release_rule(product: str, migrated: str) -> str:
    """The migrated manifest with rule 6 answered: one `test:image` command consuming the released image and
    producing a `test-result` with a `path:`, bound as `evidence` on the release command. Text unchanged for a
    product that releases nothing untested."""
    if product not in RELEASE_RULE_ANSWERS:
        return migrated
    leaf, image = RELEASE_RULE_ANSWERS[product]
    data = yaml.safe_load(migrated)
    result = f"{image}-checked"
    commands = data["ci"]["test"].setdefault("commands", {})
    assert ADDED_TEST_COMMAND not in commands and result not in data["artifacts"]
    commands[ADDED_TEST_COMMAND] = {"task": "test:image", "consumes": {"image": image},
                                    "produces": {"test-result": result}}
    data["artifacts"][result] = {"kind": "test-result", "path": f"build/test/{result}.json"}
    data["ci"]["release"]["commands"][leaf]["consumes"]["evidence"] = [result]
    return yaml.safe_dump(data, sort_keys=False)
