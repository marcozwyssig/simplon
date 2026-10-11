# si#344 Plan A: the ci / cd / support shape and the migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax
> for tracking.

**Goal:** A product manifest declares its commands under `ci:` / `cd:` / `support:` instead of `groups:`.
The CLI is byte-identical, a migration command rewrites a manifest by text splice, and the old form is
refused with a diagnosis that names the migration.

**Architecture:** The front end of `orchestrator/manifest.py:load` turns the three area sections into a
tree with two **transparent** nodes, `ci` and `cd`, and merges it onto the catalogue, which now declares
those nodes. One new pure step, `treeform.elide_transparent`, folds the transparent nodes away *after*
`merge` and *before* `lower`. The group lock, the catalogue, the firn model (plan D) and the area of
every group therefore see the real level. `Manifest.groups`, the CLI, `taskgen`, `completiongen` and
`workflowgen` keep receiving the paths they receive today (`build`, `support.git`). The migration is a
pure text function, `simplon.tasks.migrate.migrate_text`, with two entry points.

**Tech Stack:** Python 3.11+, pydantic, PyYAML, Typer, pytest. Run the suite with
`deploy/orchestrator/.venv/bin/python -m pytest` from `src/tests/` (memory: three `test_tasks_docs`
failures are root-bound and pre-existing).

**Spec:** `docs/superpowers/specs/2026-10-11-ci-cd-support-and-the-artifact-chain-design.md`, part A.
Plans B–D follow separately. **A and B ship in one kernel release** (the cut), so this plan's branch is
merged to `main` but not tagged until plan B has landed.

## Global Constraints

- The CLI does not change: every command path of every manifest is identical before and after (decision 1).
- `ci:` holds exactly `build`, `test`, `release`. `cd:` holds `deploy` and `monitor` plus the data keys
  `default`, `environments` and `site`. `support:` is a group node.
- `transparent:` may be declared by the catalogue only. A product writing it is refused.
- `env_first:` anywhere under `ci:` is refused. `cd` is `env_first: true` in the catalogue.
- `env_groups:` is deleted as a manifest key. `Manifest.env_groups` stays, derived from the tree.
- The migration splices text: comments, flow style and key order survive, and nothing is written unless
  the parsed result is structurally identical to the original.
- The migration's outcomes are three: migrated (rc 0), already in the new form (rc 0, a different
  message), cannot migrate (rc 1, nothing written).
- The migration entry points are `support manifest migrate` (catalogue-placed) and
  `simplon manifest migrate [MANIFEST]` (package CLI, `bootstrap.main`).
- Every new load-time refusal gets a `CENSUS` entry with its kind (and a `REACH` entry if it is an
  expression rule) in `src/tests/test_refusal_census.py`, in the task that adds it.
- Every pinned message is asserted against the real raised text (CLAUDE.md: a quoted error text is a
  second source).
- Every new assertion is seen red before it is made green (CLAUDE.md "See it red").
- Commits go through a quoted heredoc with Marco's identity in `GIT_AUTHOR_*`/`GIT_COMMITTER_*`
  (memory `git-identity-needs-env-per-commit`) and end with the session's attribution lines.
- English in code, comments, commits and docs (si#213).
- **`images:` is NOT touched by this plan.** Its fold and its cut diagnosis (spec A.6, last row but one)
  belong to plan B.

## Review Focus

1. **A manifest with `ci:` and a leftover `groups:` both present** (half-migrated by hand): it must be
   refused by the `groups:` diagnosis, not merged silently. Task 9.
2. **A `site:` section with no docs keys and nothing else** (a product that started writing the location
   at top level): refused with the "location belongs under `cd:`" message, not the `website:` one.
   Task 9.
3. **The migration over a manifest whose `groups:` is flow style** (`groups: { build: ... }`): rc 1,
   nothing written, and the message names the line. It must not produce a half-spliced file. Task 5.
4. **The migration run twice:** the second run is rc 0 with "already in the ci/cd form", and the file is
   byte-identical. Task 5.
5. **A comment between two groups under `groups:`** (`# --- deploy ---` above `deploy:`) travels with
   the group it precedes into `cd:`, not with the group before it into `ci:`. Task 5.

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `src/simplon/orchestrator/model/treeform.py` | tree front end | `transparent` node key; `elide_transparent`; `platform_groups`; `tree_from_areas`; `AREA_SKELETON` |
| `src/simplon/catalogue.yaml` | platform tree | `groups:` becomes `ci`/`cd`/`support` |
| `src/simplon/orchestrator/manifest.py` | loader | reads areas, elides, derives `env_groups`, `areas`; cut diagnoses; rule 1 message; rule 2 deleted |
| `src/simplon/environments.py` | env matrix reader | `cd:` accessor `matrix_section` |
| `src/simplon/completiongen.py`, `tasks/env.py`, `tasks/carrier.py`, `labinstance.py` | readers | read through `environments.matrix_section` |
| `src/simplon/tasks/site.py` | docs site reader | `SECTION = "website"` |
| `src/simplon/tasks/migrate.py` | **new** | `migrate_text`, `migrate` (task body) |
| `src/simplon/bootstrap.py` | package CLI, init template | `simplon manifest migrate`; starter manifest in the new form |
| `simplon.yaml` | the kernel's own manifest | migrated by the new command |
| `src/tests/manifestsurface.py` | **new** test helper | `cli_surface(manifest) -> dict` |
| `src/tests/fixtures/manifests/` | **new** | the eight reachable manifests (old form) and their CLI-surface goldens |
| `src/tests/test_transparent.py` | **new** | elision, collision, catalogue shape |
| `src/tests/test_migrate.py` | **new** | splice, verification, outcomes, eight real manifests |
| `src/tests/test_cut.py` | **new** | the A.6 diagnoses |
| `src/tests/test_coordinate_placement.py` | si#34 | platform groups computed through the transparent level |
| `src/tests/test_env_groups.py` | si#43 | **deleted** with the key |
| `src/tests/test_refusal_census.py` | census | entries added/removed per task |
| ~50 test files with inline `groups:` manifests, `src/tests/fixtures/case_*_manifest.yaml`, docs pages | fixtures | migrated mechanically in Task 8 |

---

### Task 1: Capture the CLI-surface goldens of the eight real manifests (before anything changes)

**Files:**
- Create: `src/tests/manifestsurface.py`
- Create: `src/tests/fixtures/manifests/{agile-cockpit,asbundle,biz-cockpit,cleon,firn,netctl,simplon,swi}.yaml`
- Create: `src/tests/fixtures/manifests/golden/<product>.json` (eight)
- Create: `src/tests/fixtures/manifests/README.md`
- Test: `src/tests/test_migrate.py` (first test only)

**Interfaces:**
- Produces: `manifestsurface.cli_surface(mf: Manifest) -> dict`, which Task 10 compares against.

- [ ] **Step 1: Fetch the eight manifests through the API** (memory `reachable-manifests-are-named-per-product`)

```bash
cd /root/git/simplon/src/tests/fixtures && mkdir -p manifests/golden && cd manifests
for p in cleon:cleon biz-cockpit:biz-cockpit asbundle:asbundle agile-cockpit:agile-cockpit \
         secure-windows-images:swi netctl:netctl firn:firn; do
  r=${p%%:*}; f=${p##*:}
  gh api repos/marcozwyssig/$r/contents/$f.yaml --jq .content | tr -d '\n' | base64 -d > $f.yaml
done
cp /root/git/simplon/simplon.yaml simplon.yaml
wc -l *.yaml
```

Expected: eight files, none empty (line counts near cleon 271, biz-cockpit 576, asbundle 323,
agile-cockpit 378, swi 1002, netctl 776, firn 1496).

- [ ] **Step 2: Write the README beside them**

```markdown
# The eight reachable manifests, frozen in the OLD (`groups:`) form

Fetched on 2026-10-11 through the GitHub API, exactly as each product's default branch carried them.
They are the population si#344's migration is measured against: `test_migrate.py` migrates each one and
asserts that the migrated manifest assembles the same CLI surface as `golden/<product>.json`. The goldens
were recorded by the kernel BEFORE the ci/cd change (plan A, Task 1), which is the only kernel that could
still load these files.

Do not refresh these files: a refreshed copy would be in the new form, and the test would prove nothing.
```

- [ ] **Step 3: Write the surface helper**

```python
"""The CLI surface of a loaded manifest, as plain data a golden file can hold (si#344 plan A).

The surface is what decision 1 promises does not change: every group path, every command in it in
order, what each command runs (`impl`) or plans (`depends_on`), and which groups are env-first. Help
texts are included because a migration that lost a `help:` would change `--help`.
"""
from __future__ import annotations

from simplon.orchestrator.manifest import Manifest


def cli_surface(mf: Manifest) -> dict:
    tax = mf.taxonomy()
    return {
        "groups": {group: list(members) for group, members in sorted(mf.groups.items())},
        "commands": {
            group: {name: {"impl": spec.impl, "depends_on": list(spec.depends_on), "help": spec.help}
                    for name, spec in sorted(specs.items())}
            for group, specs in sorted(mf.commands.items())
        },
        "env_first": sorted(group for group in mf.groups if tax.group_requires_env(group)),
    }
```

`group_requires_env` is in `src/simplon/clitaxonomy.py`. Check the exact method name with
`grep -n "def group_requires_env\|def requires_env" src/simplon/clitaxonomy.py` and use the one there.

- [ ] **Step 4: Record the goldens with today's kernel**

```bash
cd /root/git/simplon/src/tests && ../../deploy/orchestrator/.venv/bin/python - <<'EOF'
import json, pathlib
from simplon import catalogue
from simplon.orchestrator import manifest
from manifestsurface import cli_surface
here = pathlib.Path("fixtures/manifests")
cat = catalogue.load()
for f in sorted(here.glob("*.yaml")):
    mf = manifest.load(f.read_text(), catalogue=cat, manifest_path=f.name)
    (here / "golden" / f"{f.stem}.json").write_text(json.dumps(cli_surface(mf), indent=2, sort_keys=True) + "\n")
    print(f.stem, sum(len(v) for v in mf.groups.values()), "commands")
EOF
```

Expected: eight lines, each with a non-zero command count. If a manifest fails to load (a product ahead
of or behind this kernel), record that in the README under "Not loadable by the recording kernel" with the
message, leave it out of the golden comparison in Task 10, and tell Marco. Do not edit the fixture to
make it load.

- [ ] **Step 5: Write the golden test that will hold the migration (expected to fail until Task 10)**

```python
"""The migration (si#344 plan A): text in, text out, and the CLI it assembles unchanged."""
import json
import pathlib

import pytest

from simplon import catalogue
from simplon.orchestrator import manifest
from manifestsurface import cli_surface

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "manifests"
PRODUCTS = sorted(p.stem for p in (FIXTURES / "golden").glob("*.json"))


def test_there_are_eight_goldens():
    # assert: the population is the eight reachable manifests, not whichever happened to load
    assert len(PRODUCTS) + len(_not_loadable()) == 8


def _not_loadable() -> list[str]:
    readme = (FIXTURES / "README.md").read_text()
    return [line.split("`")[1] for line in readme.splitlines() if line.startswith("- `")]
```

- [ ] **Step 6: Run it**

Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest test_migrate.py -v`
Expected: PASS (1 test).

- [ ] **Step 7: Commit**

```bash
git add src/tests/manifestsurface.py src/tests/fixtures/manifests src/tests/test_migrate.py
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" \
GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F- <<'EOF'
test(si#344): freeze the eight reachable manifests and their CLI surface

Recorded by the kernel before the ci/cd change, which is the last one able
to load them. The migration is held against these goldens.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 2: `treeform.elide_transparent` and the `transparent` node key

**Files:**
- Modify: `src/simplon/orchestrator/model/treeform.py` (`NODE_KEYS` at line 24, `lower`'s error text,
  new functions after `lower`)
- Create: `src/tests/test_transparent.py`
- Modify: `src/tests/test_refusal_census.py` (one entry)

**Interfaces:**
- Produces:
  - `treeform.NODE_KEYS = ("help", "env_first", "transparent", "groups", "commands")`
  - `treeform.elide_transparent(tree: dict) -> tuple[dict, dict[str, str]]`: returns the tree with every
    transparent node replaced by its children, and `areas`, which maps each hoisted child's name to the
    transparent node it came from. Children of a transparent `env_first` node inherit `env_first: True`.
  - `treeform.platform_groups(tree: dict) -> frozenset[str]`: the first non-transparent level.

- [ ] **Step 1: Write the failing tests**

```python
"""The transparent level (si#344, spec A.2): `ci` and `cd` are real nodes in the merged tree and absent
from every path the CLI is built from. AAA throughout."""
import pytest

from simplon.orchestrator.model import treeform

TREE = {
    "ci": {"transparent": True, "help": "CI", "groups": {
        "build": {"help": "Produce.", "commands": {"wheel": {"task": "wheel"}}},
        "test": {"help": "Verify."}}},
    "cd": {"transparent": True, "env_first": True, "groups": {
        "deploy": {"help": "Put.", "commands": {"up": {"task": "deploy:up"}}}}},
    "support": {"help": "Support.", "commands": {"install": {"task": "support:install"}}},
}


def test_transparent_nodes_are_folded_away_and_their_children_hoisted():
    # act
    elided, areas = treeform.elide_transparent(TREE)

    # assert
    assert list(elided) == ["build", "test", "deploy", "support"]
    assert elided["build"]["commands"] == {"wheel": {"task": "wheel"}}
    assert areas == {"build": "ci", "test": "ci", "deploy": "cd"}


def test_a_transparent_env_first_node_hands_env_first_to_every_child():
    # act
    elided, _ = treeform.elide_transparent(TREE)

    # assert
    assert elided["deploy"].get("env_first") is True
    assert "env_first" not in elided["build"]


def test_a_tree_with_no_transparent_node_is_returned_unchanged():
    # arrange
    tree = {"build": {"commands": {"x": {"task": "y"}}}}

    # act
    elided, areas = treeform.elide_transparent(tree)

    # assert
    assert elided == tree and areas == {}


def test_two_transparent_siblings_that_would_hoist_the_same_name_are_refused():
    # arrange
    tree = {"ci": {"transparent": True, "groups": {"x": {}}},
            "cd": {"transparent": True, "groups": {"x": {}}}}

    # act / assert
    with pytest.raises(ValueError) as caught:
        treeform.elide_transparent(tree)
    assert str(caught.value) == (
        "group 'x' is reached through two transparent nodes, 'ci.x' and 'cd.x', and both would be "
        "'x' on the command line. A transparent node is skipped when the CLI path is built, so its "
        "children's names must be unique across all of them - rename one in the platform's `groups:`")


def test_a_transparent_child_that_collides_with_a_visible_sibling_is_refused():
    # arrange
    tree = {"ci": {"transparent": True, "groups": {"support": {}}}, "support": {}}

    # act / assert
    with pytest.raises(ValueError, match="'ci.support' and 'support'"):
        treeform.elide_transparent(tree)


def test_platform_groups_is_the_first_visible_level():
    # act / assert
    assert treeform.platform_groups(TREE) == frozenset({"build", "test", "deploy", "support"})


def test_lower_accepts_the_transparent_key_and_keeps_it_on_the_shape():
    # act
    taxonomy, flat = treeform.lower({"ci": {"transparent": True, "groups": {"build": {}}}})

    # assert
    assert taxonomy["ci"]["transparent"] is True
    assert "ci.build" in flat
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest test_transparent.py -v`
Expected: FAIL. `AttributeError: module ... has no attribute 'elide_transparent'`, and for the last test
`ValueError: group 'ci' declares unknown key 'transparent'`.

- [ ] **Step 3: Implement**

In `treeform.py`, change `NODE_KEYS` and the two messages that list the keys (`_check_node_keys` and
`lower`'s "is not a mapping" text) to include `transparent`:

```python
NODE_KEYS = ("help", "env_first", "transparent", "groups", "commands")
```

```python
                f"group '{'.'.join(path)}' declares unknown key '{key}'. A group node's keys are "
                f"help, env_first, transparent, groups and commands - rename it, or if this is meant "
                f"to be a command, move it under `commands:`")
```

Add after `lower`:

```python
# --- the transparent level (si#344): real in the tree, absent from the command line ---------------------


def elide_transparent(tree: dict) -> tuple[dict, dict[str, str]]:
    """The tree with every TRANSPARENT node replaced by its children, plus where each child came from.

    `ci` and `cd` are nodes of the platform's tree (si#344): the group lock sees them, so `ci: deploy:`
    is refused by the same rule that refuses any undeclared path, and the area of every phase is a
    statement the catalogue makes once. They are NOT part of a command's path: `./simplon.sh build image`
    stays exactly that (decision 1). Folding them away here, after `merge` and before `lower`, is what
    lets everything downstream - `Manifest.groups`, the CLI, taskgen, completion, the workflow generator
    - receive the paths it has always received.

    `env_first:` on a transparent node is handed to each child, because the child is what survives: `cd`
    is env-first so that whatever stands under it takes an environment (decision 5).

    Only the TOP level is walked. The catalogue declares transparent nodes nowhere else, and a product
    cannot declare one at all (`load` refuses it), so a deeper one would be a catalogue defect rather
    than a shape to support.

    A name hoisted twice - from two transparent siblings, or beside a visible sibling of the same name -
    would be two groups with one command-line path. That is refused here, naming both internal paths.
    """
    elided: dict = {}
    origin: dict[str, str] = {}
    areas: dict[str, str] = {}
    for name, node in (tree or {}).items():
        name = str(name)
        node = node or {}
        if node.get("transparent"):
            for child, child_node in (node.get("groups") or {}).items():
                child = str(child)
                _refuse_a_second_path(child, f"{name}.{child}", origin)
                hoisted = dict(child_node or {})
                if node.get("env_first"):
                    hoisted["env_first"] = True
                elided[child] = hoisted
                origin[child] = f"{name}.{child}"
                areas[child] = name
        else:
            _refuse_a_second_path(name, name, origin)
            elided[name] = node
            origin[name] = name
    return elided, areas


def _refuse_a_second_path(name: str, path: str, origin: dict[str, str]) -> None:
    if name in origin:
        raise ValueError(
            f"group '{name}' is reached through two transparent nodes, '{origin[name]}' and '{path}', "
            f"and both would be '{name}' on the command line. A transparent node is skipped when the CLI "
            f"path is built, so its children's names must be unique across all of them - rename one in "
            f"the platform's `groups:`")


def platform_groups(tree: dict) -> frozenset[str]:
    """The platform's group names as a coordinate can name them: the first VISIBLE level of its tree.

    si#34's placement rule is stated over these. Before si#344 they were simply the top-level keys; with
    `ci` and `cd` transparent, the top-level keys are `ci`, `cd` and `support`, and reading those would
    make `build:image` a family overnight - the exact failure si#344 measured.
    """
    return frozenset(elide_transparent(tree)[0])
```

Note the collision message says "two transparent nodes" even when one side is visible. Change the text to
"two nodes" if Marco objects at review. The pinned test above uses the text as written.

- [ ] **Step 4: Run the tests**

Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest test_transparent.py test_treeform.py -v`
Expected: PASS. If `test_treeform.py` pins the old "keys are help, env_first, groups and commands" text,
update that pin to the new wording in this step.

- [ ] **Step 5: Classify the new refusal in the census**

In `CENSUS` (`src/tests/test_refusal_census.py`, near the other `treeform` entries around line 576):

```python
    # si#344: a transparent level whose children would collide on the command line. The refused tree
    # assembles no working CLI - Typer would register one path twice - so this is diagnosis.
    ("treeform", "_refuse_a_second_path", "is reached through two transparent nodes"): DIAGNOSIS,
```

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest test_refusal_census.py -v`
Expected: PASS. If `test_every_load_time_refusal_is_classified` does not yet see the new raise, because
nothing calls `elide_transparent` from a seam until Task 3, then `test_every_census_key_names_exactly_one_refusal`
fails for this key instead. In that case move this census entry into Task 3, Step 7, and note it there.

- [ ] **Step 6: Commit**

```bash
git add src/simplon/orchestrator/model/treeform.py src/tests/test_transparent.py src/tests/test_treeform.py src/tests/test_refusal_census.py
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" \
GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F- <<'EOF'
feat(si#344): a transparent tree level, folded away before the CLI sees it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 3: The catalogue declares `ci` / `cd`, and the loader reads both forms (transitional)

The loader gains the new form while the old one still loads. That keeps the suite green until Task 8
migrates the fixtures, and Task 9 removes the old form. Nothing between Task 3 and Task 9 is tagged.

**Files:**
- Modify: `src/simplon/catalogue.yaml:33-155` (the `groups:` block)
- Modify: `src/simplon/orchestrator/model/treeform.py` (new `tree_from_areas`, `tree_from_groups`,
  `AREA_SKELETON`)
- Modify: `src/simplon/orchestrator/manifest.py` (`Manifest` gains `areas`; `load` lines ~857-990)
- Modify: `src/tests/test_coordinate_placement.py` (the platform-group derivation)
- Modify: `src/tests/test_transparent.py` (loader-level tests)
- Modify: `src/tests/test_refusal_census.py`

**Interfaces:**
- Consumes: `elide_transparent`, `platform_groups` (Task 2).
- Produces:
  - `treeform.AREAS = ("ci", "cd", "support")`, and
    `treeform.CD_DATA_KEYS = ("default", "environments", "site")`
  - `treeform.tree_from_areas(data: dict) -> dict`: the product's `ci:`/`cd:`/`support:` as one tree
    `{"ci": {"groups": {...}}, "cd": {"groups": {...}}, "support": {...}}`. The `cd` data keys are left
    out.
  - `treeform.tree_from_groups(groups: dict, areas: dict[str, str]) -> dict`: the old `groups:` form
    wrapped into the same shape. `areas` maps a phase to its area. **Transitional, deleted in Task 9.**
  - `treeform.AREA_SKELETON`: the kernel tree a catalogue-less load merges onto, so that
    `load(text)` without a catalogue still treats `ci`/`cd` as transparent.
  - `Manifest.areas: dict[str, str]` (group → `"ci"`/`"cd"`; `support` and product-own groups are absent)
    and `Manifest.area_of(group: str) -> str | None`. The area of a nested group is the area of its
    first segment.

- [ ] **Step 1: Write the failing loader tests** (append to `test_transparent.py`)

```python
import textwrap

from simplon import catalogue as catalogue_mod
from simplon.orchestrator import manifest as manifest_mod

NEW_FORM = textwrap.dedent("""\
    product: demo
    tasks:
      wheel: { impl: "pkg.mod:wheel", help: "Build the wheel.", unattended: true }
    ci:
      build:
        commands:
          wheel: { task: wheel }
    cd:
      default: dev
      environments: { dev: { backend: local } }
""")


def _load(text: str):
    return manifest_mod.load(text, catalogue=catalogue_mod.load())


def test_the_catalogues_top_level_is_the_three_areas():
    # act
    groups = catalogue_mod.load().groups

    # assert
    assert list(groups) == ["ci", "cd", "support"]
    assert groups["ci"]["transparent"] is True and groups["cd"]["transparent"] is True
    assert groups["cd"]["env_first"] is True
    assert list(groups["ci"]["groups"]) == ["build", "test", "release"]
    assert list(groups["cd"]["groups"]) == ["deploy", "monitor"]


def test_a_command_under_ci_build_is_build_on_the_command_line():
    # act
    mf = _load(NEW_FORM)

    # assert
    assert mf.groups["build"] == ("wheel",)
    assert mf.area_of("build") == "ci"
    assert mf.area_of("support.git") is None


def test_the_old_groups_form_assembles_the_same_cli_while_both_are_read():
    # arrange
    old = NEW_FORM.replace("ci:\n  build:", "groups:\n  build:")

    # act
    new_mf, old_mf = _load(NEW_FORM), _load(old)

    # assert
    assert new_mf.groups == old_mf.groups and new_mf.commands == old_mf.commands


def test_everything_under_cd_is_env_first_and_nothing_under_ci_is():
    # act
    tax = _load(NEW_FORM).taxonomy()

    # assert
    assert tax.group_requires_env("deploy") and tax.group_requires_env("monitor")
    assert not tax.group_requires_env("build")


def test_a_catalogue_less_load_still_treats_ci_as_transparent():
    # act
    mf = manifest_mod.load(NEW_FORM.replace("{ task: wheel }",
                                            "{ impl: 'pkg.mod:wheel', help: 'w' }").replace(
        "tasks:\n  wheel: { impl: \"pkg.mod:wheel\", help: \"Build the wheel.\", unattended: true }\n", ""))

    # assert
    assert "build" in mf.groups and "ci.build" not in mf.groups


def test_the_skeleton_agrees_with_the_catalogue_on_the_areas():
    """`AREA_SKELETON` is a second statement of which areas are transparent, and it exists only so that
    a load without a catalogue reads `ci:` the way every product does. This holds it to the first."""
    # arrange
    cat = catalogue_mod.load().groups

    # act / assert
    for area, node in treeform.AREA_SKELETON.items():
        assert bool(node.get("transparent")) == bool(cat[area].get("transparent"))
        assert bool(node.get("env_first")) == bool(cat[area].get("env_first"))
```

Check the env helper's name before running: `grep -n "def group_requires_env" src/simplon/clitaxonomy.py`.
The catalogue-less test feeds `impl:` directly, so it must first pass `treeform.check_no_old_form`. If
that refuses it ("flat command form"), give the test a `tasks:` block and `task:` references instead, as
in `NEW_FORM`.

- [ ] **Step 2: Run to verify they fail**

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest test_transparent.py -v`
Expected: the six new tests FAIL. The first fails on `list(groups) == ["build", "test", ...]`, and the
others fail because `ci:` is ignored, giving "manifest defines no groups".

- [ ] **Step 3: Restructure the catalogue**

In `src/simplon/catalogue.yaml`, replace the `groups:` block's six entries (lines 33–155) with the shape
below. Keep every comment, moved with the node it describes: the `release` comment block goes above
`release:` under `ci: groups:`, and `support:` and its whole subtree stay as they are.

```yaml
groups:
  # THE AREAS (si#344). `ci` and `cd` are TRANSPARENT: real nodes of this tree - the group lock sees
  # them, so `ci: deploy:` is refused like any undeclared path, and a phase's area is said once, here -
  # and absent from every command path: `build image` stays `build image`. `treeform.elide_transparent`
  # folds them away before the CLI is built. `cd` is env-first, so everything under it takes an
  # environment and nothing under `ci` does (decision 5; `env_groups:` is gone).
  ci:
    transparent: true
    help: "Produce, verify and publish the artefacts."
    groups:
      build:   { help: "Produce the artefacts." }
      test:    { help: "Verify them." }
      # (the existing `release` comment block, unchanged)
      release: { help: "Publish them." }
  cd:
    transparent: true
    env_first: true
    help: "Put them into an environment and watch them there."
    groups:
      deploy:  { help: "Put them into an environment." }
      monitor: { help: "Watch what is running there." }
  support:
    # (unchanged from here down)
```

`deploy` and `monitor` lose their own `env_first: true`, because they inherit it from `cd`. Leaving it
on them would be a second statement of the same fact.

- [ ] **Step 4: Add the area front end to `treeform.py`**

```python
#: The three top-level sections a product declares its commands in (si#344). `ci` and `cd` are
#: transparent nodes of the platform's tree; `support` is a group node in its own right.
AREAS = ("ci", "cd", "support")

#: Keys under `cd:` that are product DATA rather than groups: the environment matrix (`default`,
#: `environments`, read by `simplon.environments`) and the location axis (`site`, reserved, si#344).
CD_DATA_KEYS = ("default", "environments", "site")

#: The kernel tree a load WITHOUT a catalogue merges onto (`locked=False`). It exists only so that such a
#: load reads `ci:` the way every product does, with `build` on the command line rather than `ci build`.
#: It is a second statement of which areas are transparent, and
#: `test_the_skeleton_agrees_with_the_catalogue_on_the_areas` holds it to the catalogue's.
AREA_SKELETON = {"ci": {"transparent": True}, "cd": {"transparent": True, "env_first": True}}


def tree_from_areas(data: dict) -> dict:
    """The product's `ci:` / `cd:` / `support:` sections as ONE tree for `merge`.

    Under `ci:` and `cd:` the phase groups stand directly (`ci: build:`), where the tree nests children
    under `groups:`; this wraps them. The data keys under `cd:` are not groups and are left out here -
    `simplon.environments` reads them from the document. `support:` already IS a group node.
    """
    tree: dict = {}
    for area in ("ci", "cd"):
        section = data.get(area)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise ValueError(
                f"`{area}:` is not a mapping: found {type(section).__name__} instead. It maps each phase "
                f"group ({_phases_of(area)}) to its node - check the indentation under this key")
        groups = {name: node for name, node in section.items()
                  if not (area == "cd" and name in CD_DATA_KEYS)}
        tree[area] = {"groups": groups} if groups else {}
    if data.get("support") is not None:
        tree["support"] = data["support"]
    return tree


def _phases_of(area: str) -> str:
    return "build, test, release" if area == "ci" else "deploy, monitor"


def tree_from_groups(groups: dict, areas: dict[str, str]) -> dict:
    """TRANSITIONAL (si#344 plan A, deleted in its Task 9): the old `groups:` form wrapped into the area
    tree, so both forms load while the fixtures are migrated. `areas` maps a phase to its area; a group
    no area claims stays at the top level, which is where a catalogue-less test's own groups live."""
    tree: dict = {}
    for name, node in (groups or {}).items():
        area = areas.get(str(name))
        if area:
            tree.setdefault(area, {"groups": {}})["groups"][str(name)] = node
        else:
            tree[str(name)] = node
    return tree
```

- [ ] **Step 5: Wire the loader**

In `manifest.py`:

1. `Manifest` gains `areas: dict[str, str] = {}`. Put it after `generate`, keeping the NamedTuple's
   defaults last. It also gains:

```python
    def area_of(self, group: str) -> str | None:
        """`ci` or `cd` for a phase group and everything nested under it; None for `support` and its
        subtree (si#344). Read off the merged tree, so it is the catalogue's statement and not a table."""
        return self.areas.get(group.split(".", 1)[0])
```

2. In `load`, replace `tree = data.get("groups") or {}` (line ~860) and the `merge`/`lower` lines with:

```python
    kernel_tree = catalogue_groups or treeform.AREA_SKELETON
    _, phase_areas = treeform.elide_transparent(kernel_tree)
    if data.get("groups") is not None:
        # TRANSITIONAL (deleted in plan A Task 9): the old form, wrapped into the area tree.
        tree = treeform.tree_from_groups(data.get("groups") or {}, phase_areas)
    else:
        tree = treeform.tree_from_areas(data)
```

   Keep the existing `isinstance(tree, dict)` refusal for `groups:`, applied to `data.get("groups")`.
   Then pass `kernel_tree` to `merge` (instead of `catalogue_groups`) with
   `locked=bool(catalogue_groups)`, unchanged. Directly after `merge`:

```python
    merged, areas = treeform.elide_transparent(merged)
```

   Every later use of `merged` now sees the elided tree: `lower`, `declared_paths(tree)` (which must
   become `declared_paths(treeform.elide_transparent(tree)[0])`, because the product's own tree is in
   area form too), `check_env_groups(merged, ...)`. `areas` goes into the `Manifest(...)` return.

3. Replace `frozenset(catalogue_groups)` in the two calls to `check_coordinate_placement` and
   `check_env_groups` with `treeform.platform_groups(catalogue_groups)`.

4. `_enforce_the_catalogue_owns_the_groups` and `_catalogue_tree(catalogue_taxonomy, ...)` read
   `lowered_taxonomy`, which is now elided as well, so they see `build`... as before. Run the suite to
   confirm, and do not change them unless it goes red.

- [ ] **Step 6: Adapt si#34's test to the transparent level**

In `test_coordinate_placement.py`, replace
`test_the_catalogue_still_declares_exactly_the_six_groups_the_rule_is_written_against`'s act line:

```python
    # arrange / act: the rule's set is the first VISIBLE level, not the top-level keys (si#344)
    groups = treeform.platform_groups(catalogue_mod.load().groups)
```

Add the two si#344 tests the spec requires (A.3):

```python
def test_build_image_under_ci_test_is_still_refused_through_the_transparent_level():
    # arrange
    text = textwrap.dedent("""\
        product: demo
        ci:
          test:
            commands:
              image: { task: "build:image", with: { name: kernel } }
    """)

    # act / assert
    with pytest.raises(ValueError, match="'build:image' belongs under"):
        manifest_mod.load(text, catalogue=catalogue_mod.load())


def test_the_old_first_segment_comparison_would_have_let_it_through():
    """The failure si#344 measured, shown rather than asserted away: compared against the catalogue's
    TOP-LEVEL keys, `build:image` is a family and the misplacement loads green."""
    # arrange
    flat = {"test": {"image": {"task": "build:image"}}}

    # act
    ruled = treeform.check_coordinate_placement(flat, frozenset(catalogue_mod.load().groups))

    # assert: nothing refused, nothing ruled on - the rule silently stopped applying
    assert ruled == 0
```

Before Step 7, see the first test red: temporarily change `platform_groups(catalogue_groups)` back to
`frozenset(catalogue_groups)` in `load`, run the test, watch it FAIL with "DID NOT RAISE", and restore.

- [ ] **Step 7: Run the whole suite**

Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -x -q`
Expected: PASS, except the three pre-existing root-bound `test_tasks_docs` failures. Fix every other
failure in this step. The likely ones:
- tests that assert `catalogue.load().groups` keys or `env_first` on `deploy`: read through
  `platform_groups`/`elide_transparent` instead.
- the census: `elide_transparent`'s refusal and `tree_from_areas`'s "is not a mapping" (DIAGNOSIS) need
  entries. `merge`'s message now lists "Available here: ci, cd, support" at the top level, so check the
  pinned texts in `test_treeform.py`.

- [ ] **Step 8: Commit**

```bash
git add -A src/simplon src/tests
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" \
GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F- <<'EOF'
feat(si#344): the catalogue declares ci and cd, and the loader reads the area form

The old groups: form still loads until the fixtures are migrated; it is
removed in the cut, within this plan.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 4: The product may not write `transparent:`, and `env_first:` under `ci:` is refused; unknown keys under `cd:` are named

**Files:**
- Modify: `src/simplon/orchestrator/model/treeform.py` (`tree_from_areas`)
- Modify: `src/tests/test_transparent.py`, `src/tests/test_refusal_census.py`

**Interfaces:**
- Consumes: `tree_from_areas` (Task 3).
- Produces: three refusals raised from `tree_from_areas`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_product_writing_transparent_is_refused():
    # arrange
    text = NEW_FORM.replace("  build:\n", "  build:\n    transparent: true\n")

    # act / assert
    with pytest.raises(ValueError) as caught:
        _load(text)
    assert str(caught.value) == (
        "`ci: build:` declares `transparent:`. Which nodes are transparent is the platform's statement "
        "(the catalogue's `groups:`), so that `ci` and `cd` are skipped on the command line in every "
        "product and nothing else is - remove the key")


def test_env_first_under_ci_is_refused():
    # arrange
    text = NEW_FORM.replace("  build:\n", "  build:\n    env_first: true\n")

    # act / assert
    with pytest.raises(ValueError) as caught:
        _load(text)
    assert str(caught.value) == (
        "`ci: build:` declares `env_first:`. Nothing under `ci:` takes an environment - a build, a test "
        "and a release run the same in every environment; what takes one stands under `cd:`, which is "
        "env-first as a whole. Remove the key, or move the commands that need an environment under `cd:`")


def test_an_unknown_key_under_cd_names_both_lists():
    # arrange
    text = NEW_FORM.replace("  default: dev\n", "  default: dev\n  rollout: {}\n")

    # act / assert
    with pytest.raises(ValueError) as caught:
        _load(text)
    assert str(caught.value) == (
        "`cd: rollout:` is neither a phase group nor a data key. Under `cd:` stand the phase groups "
        "deploy, monitor and the data keys default, environments, site")
```

Before writing the third refusal, check one thing: the `else` branch of `tree_from_areas` would otherwise
pass `rollout` to `merge`, and `merge`'s group lock would refuse it with "names a group the platform's
tree does not declare". The new message is the more precise one because it also lists the data keys,
which is why it is raised first.

- [ ] **Step 2: Run to verify they fail**

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest test_transparent.py -k "transparent_is_refused or env_first_under_ci or unknown_key_under_cd" -v`
Expected:
- the first FAILS with `merge`'s `shape_is_the_platforms` text, not the pinned one;
- the second loads green and FAILS with "DID NOT RAISE";
- the third FAILS with the group-lock text.

- [ ] **Step 3: Implement in `tree_from_areas`**

```python
def _refuse_area_shape(area: str, name: str, node: object) -> None:
    if not isinstance(node, dict):
        return
    if "transparent" in node:
        raise ValueError(
            f"`{area}: {name}:` declares `transparent:`. Which nodes are transparent is the platform's "
            f"statement (the catalogue's `groups:`), so that `ci` and `cd` are skipped on the command "
            f"line in every product and nothing else is - remove the key")
    if area == "ci" and "env_first" in node:
        raise ValueError(
            f"`ci: {name}:` declares `env_first:`. Nothing under `ci:` takes an environment - a build, a "
            f"test and a release run the same in every environment; what takes one stands under `cd:`, "
            f"which is env-first as a whole. Remove the key, or move the commands that need an "
            f"environment under `cd:`")
    for child, child_node in (node.get("groups") or {}).items():
        _refuse_area_shape(area, f"{name}: groups: {child}", child_node)
```

Call it for every group under `ci:` and `cd:`, and for `support:` (with `area="support"`, so only
`transparent` applies). The `cd` unknown-key check runs in the same loop, before the group is kept:

```python
        known = {"ci": ("build", "test", "release"), "cd": ("deploy", "monitor")}[area]
        for name, node in section.items():
            if area == "cd" and name in CD_DATA_KEYS:
                continue
            if area == "cd" and name not in known:
                raise ValueError(
                    f"`cd: {name}:` is neither a phase group nor a data key. Under `cd:` stand the phase "
                    f"groups {', '.join(known)} and the data keys {', '.join(CD_DATA_KEYS)}")
            _refuse_area_shape(area, name, node)
```

`ci:` gets no unknown-key check of its own: `merge`'s group lock already names the available groups
there, and a second message for the same case would be a second source.

The `known` lists are a second statement of the catalogue's phases. Derive them from the catalogue
instead. `tree_from_areas` gains a parameter `phases: dict[str, tuple[str, ...]]`, and `load` passes
`{area: tuple((node.get("groups") or {}).keys()) for area, node in kernel_tree.items() if node.get("transparent")}`.
The catalogue-less path passes the same from `AREA_SKELETON`, where the dict is empty, so the unknown-key
check is skipped there. Update `tree_from_areas`'s signature to
`tree_from_areas(data: dict, phases: dict[str, tuple[str, ...]]) -> dict` and its call in `load`.

- [ ] **Step 4: Run the tests and the census**

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest test_transparent.py test_refusal_census.py -v`
Expected: the new tests PASS, and the census FAILS naming the three new raises. Add:

```python
    # si#344. A product may not make a node transparent: the CLI would lose a path segment the platform
    # did not decide to drop. The refused manifest assembles a working CLI, a different one.
    ("treeform", "_refuse_area_shape", "declares `transparent:`"): EXPRESSION,
    # si#344, decision 5: nothing under ci takes an environment. A ci group made env-first would assemble
    # and run - gated - so this forbids something expressible.
    ("treeform", "_refuse_area_shape", "Nothing under `ci:` takes an environment"): EXPRESSION,
    ("treeform", "tree_from_areas", "is neither a phase group nor a data key"): DIAGNOSIS,
```

and in `REACH`:

```python
    ("treeform", "_refuse_area_shape", "declares `transparent:`"): REACH_SEAM,
    ("treeform", "_refuse_area_shape", "Nothing under `ci:` takes an environment"): REACH_MERGED,
```

`REACH_MERGED` for `env_first` is only true if the catalogue's own `ci` subtree is checked too. Add one
line to `load` that runs `_refuse_area_shape("ci", name, node)` over
`kernel_tree["ci"]["groups"]` as well, and confirm
`test_every_merged_reach_expression_rule_ruled_on_the_kernels_own_declarations` stays green. If that
test needs a hook (it monkeypatches rules to see what they were handed), follow the pattern it already
uses for `check_coordinate_placement`.

Run again. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A src/simplon src/tests
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" \
GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F- <<'EOF'
feat(si#344): transparent is the platform's, nothing under ci is env-first

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 5: `migrate_text` - the splice, its verification, its three outcomes

**Files:**
- Create: `src/simplon/tasks/migrate.py`
- Modify: `src/tests/test_migrate.py`

**Interfaces:**
- Produces:

```python
class Migration(NamedTuple):
    status: str            # "migrated" | "current" | "refused"
    text: str              # the new text ("migrated"), else the input unchanged
    moved: tuple[str, ...] # human-readable lines, one per section moved ("groups: build -> ci: build")
    reason: str = ""       # "refused" only: what could not be migrated, naming the line

def migrate_text(text: str, *, unknown_groups_into: str | None = None) -> Migration: ...
```

`unknown_groups_into` exists for Task 8's fixture script only. A real manifest is always loaded against
the catalogue, which locks the groups, so a group outside the six cannot occur in one. With the default
`None`, such a group is `refused`.

**What it does, line-oriented.** A top-level block is a column-0 key line plus every following line
that is indented, blank, or a comment, up to the next column-0 key. **Comment lines directly above a
column-0 key belong to that key's block, not to the block before it** (Review Focus 5). The same rule
applies one level down, inside `groups:`, at indent 2.

1. `groups:` with a flow value (`groups: {` on the key line) → `refused`, "groups: is written in flow
   style on line N; the splice moves block-style sections only - rewrite it in block style and run
   again".
2. `groups:` block → split into child blocks at indent 2:
   - `build`/`test`/`release` → a new `ci:` block, lines unchanged (they are at indent 2 under both);
   - `deploy`/`monitor` → a new `cd:` block, lines unchanged;
   - `support` → a top-level `support:` block, every line dedented by 2;
   - any other name → `refused` (or into `unknown_groups_into`).

   The new blocks replace the `groups:` block in place, in the order `ci`, `cd`, `support`. Comments
   that stood directly under `groups:` before the first child stay above `ci:`.
3. `default:` and `environments:` top-level blocks → removed from the top level and inserted into the
   `cd:` block, before its groups, with every line indented by 2. If there is no `cd:` block (no
   deploy/monitor group), a `cd:` block holding only them is created at the position of the first of the
   two.
4. `env_groups:` block → removed if its value parses to `[]`, `["deploy"]`, `["monitor"]` or
   `["deploy", "monitor"]` (in any order); otherwise `refused`, naming the value.
5. A top-level `site:` whose parsed value is a mapping with any of `image`, `base_url`, `theme`,
   `source`, `output` → the key line's `site:` becomes `website:`.
6. Nothing to do (no `groups:`, `env_groups:`, top-level `default:`/`environments:`, or docs `site:`)
   → `current`, text unchanged.

**Verification before returning `migrated`:** `yaml.safe_load(new)` must equal the expected structure
built from `yaml.safe_load(old)`:

```python
def _expected(old: dict) -> dict:
    out = {k: v for k, v in old.items() if k not in ("groups", "env_groups", "default", "environments")}
    groups = old.get("groups") or {}
    ci = {n: groups[n] for n in ("build", "test", "release") if n in groups}
    cd = {k: old[k] for k in ("default", "environments") if k in old}
    cd.update({n: groups[n] for n in ("deploy", "monitor") if n in groups})
    if ci: out["ci"] = ci
    if cd: out["cd"] = cd
    if "support" in groups: out["support"] = groups["support"]
    if _is_docs_site(old.get("site")): out["website"] = out.pop("site")
    return out
```

Dict equality ignores key order, so this proves the content and not the layout. The layout is pinned by
the byte-level tests below. If the two are not equal, the result is `refused` with
"the spliced text does not parse back to the same manifest: <first differing key path>", and nothing is
returned as text to write.

- [ ] **Step 1: Write the failing tests** (append to `test_migrate.py`)

```python
import textwrap

from simplon.tasks.migrate import migrate_text

OLD = textwrap.dedent("""\
    # header comment
    product: demo
    default: dev   # the default env
    groups:
      # build things
      build:
        commands:
          wheel: { task: wheel }
      # --- deploy ---
      deploy:
        commands:
          up: { task: "deploy:up" }
      support:
        commands:
          doctor: { task: doctor }
    env_groups: [deploy]
    environments:
      dev: { backend: local }
    site:
      image: "hugomods/hugo:exts-0.148.2"
""")

NEW = textwrap.dedent("""\
    # header comment
    product: demo
    ci:
      # build things
      build:
        commands:
          wheel: { task: wheel }
    cd:
      default: dev   # the default env
      environments:
        dev: { backend: local }
      # --- deploy ---
      deploy:
        commands:
          up: { task: "deploy:up" }
    support:
      commands:
        doctor: { task: doctor }
    website:
      image: "hugomods/hugo:exts-0.148.2"
""")


def test_the_old_form_is_spliced_into_the_new_byte_for_byte():
    # act
    result = migrate_text(OLD)

    # assert
    assert result.status == "migrated"
    assert result.text == NEW


def test_a_comment_above_a_group_travels_with_that_group():
    # act
    text = migrate_text(OLD).text

    # assert: '--- deploy ---' sits under cd:, directly above deploy:, not at the end of ci:
    lines = text.splitlines()
    assert lines[lines.index("  # --- deploy ---") + 1] == "  deploy:"
    assert lines.index("cd:") < lines.index("  # --- deploy ---")


def test_running_it_twice_is_current_and_changes_nothing():
    # arrange
    once = migrate_text(OLD).text

    # act
    twice = migrate_text(once)

    # assert
    assert twice.status == "current"
    assert twice.text == once


def test_flow_style_groups_is_refused_and_nothing_is_returned_to_write():
    # arrange
    text = "product: demo\ngroups: { build: { commands: { w: { task: wheel } } } }\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.text == text
    assert result.reason == ("groups: is written in flow style on line 2; the splice moves block-style "
                             "sections only - rewrite it in block style and run again")


def test_an_env_groups_value_the_new_shape_cannot_say_is_refused():
    # arrange
    text = OLD.replace("env_groups: [deploy]", "env_groups: [support]")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.reason == ("env_groups: [support] names a group outside cd:. Under the ci/cd form "
                             "only what stands under cd: takes an environment, so this manifest has to "
                             "decide by hand where those commands belong")


def test_a_group_outside_the_six_is_refused_unless_told_where_it_goes():
    # arrange
    text = "product: demo\ngroups:\n  lab:\n    commands:\n      up: { task: x }\n"

    # act
    refused, placed = migrate_text(text), migrate_text(text, unknown_groups_into="ci")

    # assert
    assert refused.status == "refused"
    assert refused.reason == ("groups: lab is none of build, test, release, deploy, monitor, support - "
                              "a manifest loaded against the platform catalogue cannot have it, so there "
                              "is no area to move it to")
    assert placed.status == "migrated"
    assert placed.text == "product: demo\nci:\n  lab:\n    commands:\n      up: { task: x }\n"


def test_a_site_section_without_docs_keys_is_left_alone():
    # arrange
    text = "product: demo\nsite:\n  central: {}\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "current"


@pytest.mark.parametrize("product", PRODUCTS)
def test_every_real_manifest_migrates_and_parses_back_to_the_same_content(product):
    # arrange
    text = (FIXTURES / f"{product}.yaml").read_text()

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated", result.reason
    assert "groups:" not in [line.split("#")[0].strip() for line in result.text.splitlines()
                             if not line.startswith(" ")]
```

- [ ] **Step 2: Run to verify they fail**

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest test_migrate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'simplon.tasks.migrate'`.

- [ ] **Step 3: Implement `src/simplon/tasks/migrate.py`**

Write the module with this structure. All of it is pure text, with no I/O except in `migrate` (Task 6):

```python
"""`support manifest migrate` - rewrite a manifest from `groups:` to `ci:` / `cd:` / `support:` (si#344).

A TEXT SPLICE, the way `toolchain scaffold` writes (si#110): every byte the move does not have to touch
is the byte that was there - comments first among them, then flow style and key order. A manifest is a
document people annotate; a migration that round-tripped it through a YAML library would hand back the
data and throw away the reasons.

AND NOTHING IS TRUSTED THAT WAS NOT PARSED BACK. The spliced text is loaded again and compared with what
the original says the new form must contain. If they differ, nothing is written and the difference is
named. A splice that is wrong in a way nobody reads is worse than no splice.

THREE OUTCOMES, AND THEY STAY THREE: migrated, already current, refused. "Nothing to migrate" is rc 0
with its own sentence - it is not the same green as "migrated", and it is not a failure either.
"""
from __future__ import annotations

import re
from typing import NamedTuple

import yaml

CI = ("build", "test", "release")
CD = ("deploy", "monitor")
ENV_KEYS = ("default", "environments")
DOCS_SITE_KEYS = ("image", "base_url", "theme", "source", "output")
_TOP = re.compile(r"^(?P<key>[A-Za-z0-9_][A-Za-z0-9_.-]*):(?P<rest>.*)$")
_CHILD = re.compile(r"^  (?P<key>[A-Za-z0-9_][A-Za-z0-9_.-]*):(?P<rest>.*)$")


class Migration(NamedTuple):
    status: str
    text: str
    moved: tuple[str, ...] = ()
    reason: str = ""


def _blocks(lines: list[str], key_re: re.Pattern, indent: int) -> list[tuple[str | None, list[str]]]:
    """Split `lines` into (key, lines) blocks at `indent`. Comment and blank lines directly above a key
    line belong to that key's block; anything before the first key is a (None, lines) preamble."""
    blocks: list[tuple[str | None, list[str]]] = [(None, [])]
    pending: list[str] = []
    for line in lines:
        match = key_re.match(line)
        stripped = line.strip()
        if match:
            blocks.append((match.group("key"), pending + [line]))
            pending = []
        elif not stripped or (stripped.startswith("#") and len(line) - len(line.lstrip()) == indent):
            pending.append(line)
        else:
            if pending:
                blocks[-1][1].extend(pending)
                pending = []
            blocks[-1][1].append(line)
    if pending:
        blocks[-1][1].extend(pending)
    return blocks
```

Then:
- `_reindent(lines, by)` adds `by` spaces to each non-blank line (`by` may be negative, and then removes
  exactly that many leading spaces; a line with fewer is a bug, so raise `AssertionError`);
- `_is_docs_site(value)`;
- `_expected(old)` (above);
- `_first_difference(a, b, path="")` returns the first dotted key path whose values differ, for the
  refusal message;
- `migrate_text` follows rules 1–6 above, with exactly the messages the tests pin.

A trailing comment on a moved line (`default: dev   # the default env`) moves with its line, because
lines move whole. `moved` gets one line per section, in the order applied, for example
`"groups: build -> ci: build"`, `"default -> cd: default"`, `"env_groups: deleted ([deploy])"`,
`"site -> website"`.

Keep the preamble (comments before `product:`) where it is. Insert the new `ci:`/`cd:`/`support:`
blocks where the `groups:` block stood.

- [ ] **Step 4: Run the tests**

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest test_migrate.py -v`
Expected: PASS. For every real manifest that is `refused`, read the reason. If it is a construct the
spec's rules do not cover, stop and report it to Marco with the manifest name and the line. Do not widen
the splice on your own: the eight manifests are the measurement, and a ninth rule is a design change.

- [ ] **Step 5: Commit**

```bash
git add src/simplon/tasks/migrate.py src/tests/test_migrate.py
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" \
GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F- <<'EOF'
feat(si#344): splice a manifest from groups: into ci / cd / support

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 6: The two entry points: `support manifest migrate` and `simplon manifest migrate`

**Files:**
- Modify: `src/simplon/tasks/migrate.py` (add `migrate`)
- Modify: `src/simplon/catalogue.yaml` (task `support:migrate`; placement under `support: groups: manifest:`)
- Modify: `src/simplon/bootstrap.py` (`main`, line 1130)
- Modify: `src/tests/test_migrate.py`, `src/tests/test_bootstrap.py`

**Interfaces:**
- Consumes: `migrate_text` (Task 5).
- Produces:
  - `simplon.tasks.migrate.migrate(manifest: str = "") -> int`. An empty `manifest` means the current
    product's (`context.current().manifest_path`).
  - The CLI path `support manifest migrate`.
  - `simplon manifest migrate [MANIFEST]` (default: the single `*.yaml` in the working directory that
    carries a top-level `product:`; if there is none or more than one, rc 2 naming them).

- [ ] **Step 1: Write the failing tests**

In `test_migrate.py`:

```python
from simplon.tasks import migrate as migrate_mod


def test_migrate_writes_the_file_and_says_what_moved(tmp_path, capsys):
    # arrange
    path = tmp_path / "demo.yaml"
    path.write_text(OLD)

    # act
    rc = migrate_mod.migrate(str(path))

    # assert
    assert rc == 0
    assert path.read_text() == NEW
    assert "groups: build -> ci: build" in capsys.readouterr().out


def test_migrate_on_a_current_manifest_is_rc_0_with_its_own_sentence(tmp_path, capsys):
    # arrange
    path = tmp_path / "demo.yaml"
    path.write_text(NEW)

    # act
    rc = migrate_mod.migrate(str(path))

    # assert
    assert rc == 0
    assert path.read_text() == NEW
    assert "already in the ci/cd form - nothing to migrate" in capsys.readouterr().out


def test_migrate_refused_is_rc_1_and_writes_nothing(tmp_path, capsys):
    # arrange
    path = tmp_path / "demo.yaml"
    text = "product: demo\ngroups: { build: {} }\n"
    path.write_text(text)

    # act
    rc = migrate_mod.migrate(str(path))

    # assert
    assert rc == 1
    assert path.read_text() == text
    assert "flow style on line 2" in capsys.readouterr().err
```

Check how `simplon.log` writes (`log.ok`/`log.info` go to stdout, `log.die`/`log.error` to stderr?) with
`grep -n "^def " src/simplon/log.py`, and use `capsys`'s `out`/`err` accordingly.

In `test_bootstrap.py`:

```python
def test_simplon_manifest_migrate_runs_without_loading_the_manifest(tmp_path, monkeypatch):
    # arrange: an OLD-form manifest that the cut kernel will refuse to load - this entry point must not care
    (tmp_path / "demo.yaml").write_text("product: demo\ngroups:\n  build:\n    commands:\n      w: { task: x }\n")
    monkeypatch.chdir(tmp_path)

    # act
    rc = bootstrap.main(["manifest", "migrate"])

    # assert
    assert rc == 0
    assert (tmp_path / "demo.yaml").read_text().startswith("product: demo\nci:\n")
```

And in `test_catalogue.py` (or `test_transparent.py`):

```python
def test_support_manifest_migrate_is_placed_for_every_product():
    # act
    mf = manifest_mod.load("product: demo\n", catalogue=catalogue_mod.load())

    # assert
    assert "migrate" in mf.groups["support.manifest"]
```

`load("product: demo\n")` may be refused by rule 1 until Task 9 rewrites it. If it is, give the manifest
one `ci: build:` command.

- [ ] **Step 2: Run to verify they fail**

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest test_migrate.py test_bootstrap.py -k "migrate" -v`
Expected: FAIL with `AttributeError: ... has no attribute 'migrate'`, and the bootstrap test prints the
"nothing to do" usage with rc != 0.

- [ ] **Step 3: Implement**

`migrate.py`:

```python
def migrate(manifest: str = "") -> int:
    """Rewrite THIS product's manifest (or the one named) from `groups:` to `ci:` / `cd:` / `support:`.

    rc 0 when it migrated and when there was nothing to migrate - with a different sentence each, because
    those are two answers. rc 1 when it could not, with nothing written.
    """
    path = Path(manifest) if manifest else context.current().manifest_path
    result = migrate_text(path.read_text(encoding="utf-8"))
    if result.status == "current":
        log.ok(f"{path.name}: already in the ci/cd form - nothing to migrate")
        return 0
    if result.status == "refused":
        log.error(f"{path.name}: not migrated, nothing written - {result.reason}")
        return 1
    path.write_text(result.text, encoding="utf-8")
    for line in result.moved:
        log.info(line)
    log.ok(f"{path.name}: migrated to ci / cd / support ({len(result.moved)} section(s) moved)")
    return 0
```

Use whichever of `log.error`/`log.die` exists without exiting, as found in Step 1.

`catalogue.yaml`, under `tasks:` beside `support:toolchain`:

```yaml
  support:migrate:
    impl: simplon.tasks.migrate:migrate
    help: "Rewrite this product's manifest from `groups:` to `ci:` / `cd:` / `support:` (si#344)."
    unattended: true
    params:
      manifest: { help: "the manifest to rewrite (default: this product's own)", argument: true }
```

and under `support: groups:`, beside `tasks:`, with a comment that gives the placement
argument (spec A.5):

```yaml
      # manifest: tools over the product's manifest itself (si#344). PLACED for the reason `tasks
      # generate` is placed: it reads no section a product might lack, touches only the product's own
      # root and publishes nothing.
      manifest:
        help: "Tools over this product's manifest."
        commands:
          migrate: { task: "support:migrate" }
```

`bootstrap.main`: before the `init` handling, add

```python
    if argv[:2] == ["manifest", "migrate"]:
        return _manifest_migrate(argv[2:])
```

with

```python
def _manifest_migrate(args: list[str]) -> int:
    """`simplon manifest migrate [MANIFEST]` - the route that works AFTER the cut (si#344).

    Both launcher routes exec `python -m <product>`, which assembles the CLI from the manifest; once the
    kernel refuses `groups:`, that CLI is never built and `support manifest migrate` cannot be reached.
    This entry point loads no manifest at all.
    """
    from simplon.tasks import migrate as migrate_mod
    if len(args) > 1:
        print("usage: simplon manifest migrate [MANIFEST]", file=sys.stderr)
        return 2
    if args:
        return migrate_mod.migrate(args[0])
    candidates = [p for p in sorted(Path.cwd().glob("*.yaml"))
                  if re.search(r"(?m)^product:", p.read_text(encoding="utf-8", errors="replace"))]
    if len(candidates) != 1:
        print(f"simplon manifest migrate: name the manifest - found "
              f"{', '.join(p.name for p in candidates) or 'no *.yaml with a top-level product:'} here",
              file=sys.stderr)
        return 2
    return migrate_mod.migrate(str(candidates[0]))
```

Also add one line to the "nothing to do" text in `main` that names the second command
(`simplon manifest migrate [MANIFEST]`), and update the test that pins that text.

- [ ] **Step 4: Run the tests and the census**

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest -x -q`
Expected: PASS. `support manifest migrate` now appears in every product's CLI. That changes:
- the generated completion (`deploy/completions/simplon.bash`) and `.github/workflows/ci.yml`, if it
  lists commands. Regenerate them with `./simplon.sh support completion` and
  `./simplon.sh support workflows`, then confirm the staleness gate (`test generated`) is green;
- the command reference page (`docs/site/content/with-what/commands.md`), which is generated and
  gitignored, so there is nothing to commit;
- any test that counts the catalogue's placed commands (`test_the_page_prints_the_catalogues_own_size_and_what_it_places`).
  Update `with-what/rules.md`'s printed number to what the test demands.

Also run the five goldens from Task 1 against the old kernel? No: they are compared in Task 10, and
`support.manifest` will appear in every migrated surface there. Task 10 accounts for it.

- [ ] **Step 5: Commit**

```bash
git add -A src/simplon src/tests deploy/completions .github/workflows docs/site/content/with-what/rules.md
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" \
GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F- <<'EOF'
feat(si#344): support manifest migrate, and simplon manifest migrate for after the cut

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 7: The readers move: `cd: default` / `cd: environments`, and `website:`

**Files:**
- Modify: `src/simplon/environments.py` (new `matrix_section`; `parse_data` ~line 205-240; `Provider.registry` ~329)
- Modify: `src/simplon/completiongen.py:130`, `src/simplon/tasks/env.py:41`, `src/simplon/tasks/carrier.py:140`,
  `src/simplon/labinstance.py:69`
- Modify: `src/simplon/tasks/site.py:62` (`SECTION`)
- Modify: tests of each (`test_environments*.py`, `test_completiongen.py`, `test_tasks_env.py` or similar,
  `test_carrier*.py`, `test_labinstance.py`, `test_tasks_site*.py`)

**Interfaces:**
- Produces: `environments.matrix_section(document: Mapping) -> dict`, which returns
  `{"default": ..., "environments": ...}` read from `cd:` and, **transitionally until Task 9**, from the
  top level when `cd:` does not carry them. Every other reader of `default`/`environments` calls it.

- [ ] **Step 1: Find every reader, measured**

Run: `grep -rn "get(\"default\")\|\[\"default\"\]\|get(\"environments\")\|\[\"environments\"\]\|SECTION = \"site\"\|\"site\"" src/simplon --include=*.py`
Expected, from the measurement made while writing this plan: `environments.py:208,236,330`,
`completiongen.py:130`, `tasks/carrier.py:140`, `tasks/env.py:41`, `labinstance.py:69` and
`tasks/site.py:62`. If the list differs, the difference goes into this task too.

- [ ] **Step 2: Write the failing tests**

In `test_environments.py`:

```python
def test_the_matrix_is_read_from_cd():
    # arrange
    doc = {"cd": {"default": "dev", "environments": {"dev": {"backend": "local"}}}}

    # act
    section = environments.matrix_section(doc)

    # assert
    assert section == {"default": "dev", "environments": {"dev": {"backend": "local"}}}


def test_parse_data_reads_a_cd_matrix():
    # arrange
    doc = {"cd": {"default": "dev", "environments": {"dev": {"backend": "local"}}}}

    # act
    matrix = environments.parse_data(doc)

    # assert
    assert matrix.default == "dev"
```

Check `parse_data`'s return type (`grep -n "def parse_data" -A20 src/simplon/environments.py`) and
assert on the attribute it really has.

Add the same shape of test for `completiongen.environments_of`, for `labinstance` (its `default`), for
`tasks/env`, for `tasks/carrier`, each reading a `cd:` document. In `test_tasks_site*.py`, add a test
that `site.declared({"website": {...}}, source="x")` returns the config the old `site:` key returned.

- [ ] **Step 3: Run to verify they fail**

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest -q -k "cd or website"`
Expected: FAIL. `matrix_section` does not exist, `parse_data` reports "defines no environments", and
`site.declared` reports `site:` missing.

- [ ] **Step 4: Implement**

```python
def matrix_section(document: Mapping) -> dict:
    """The environment matrix's two keys, read from `cd:` (si#344).

    `cd` is where whatever takes an environment stands, so the matrix it takes them from stands there too.
    ONE accessor for every reader - `parse_data`, completion, `tasks/env`, `tasks/carrier`, `labinstance` -
    because five readers each walking `document["cd"]` by hand would be five places to forget the
    transitional fallback below when it is removed.

    TRANSITIONAL (deleted in si#344 plan A Task 9): a top-level `default:`/`environments:` is still read
    when `cd:` carries neither, so the not-yet-migrated fixtures keep loading.
    """
    cd = document.get("cd") if isinstance(document, Mapping) else None
    source = cd if isinstance(cd, Mapping) and ("default" in cd or "environments" in cd) else document
    return {"default": source.get("default"), "environments": source.get("environments")}
```

Change each reader to take its two values from `matrix_section(document)`. The census test
`test_the_section_walk_is_an_accessor_and_not_a_reader` may require the accessor to go through
`context.section`. Read that test first and follow what it requires: if it does, implement
`matrix_section` with `context.section(document, "cd")`.

`tasks/site.py`: `SECTION = "website"`. Then update the module's docstring and comments that say
`site:` meaning the docs section (`grep -n "site:" src/simplon/tasks/site.py`), and the same words in
`bootstrap.py:840-849`.

- [ ] **Step 5: Run the whole suite**

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest -x -q`
Expected: every test that builds a docs-site manifest with `site:` now FAILS. Those fixtures move in
Task 8. To keep this task green on its own, give `site.declared` the same transitional fallback (read
`site:` when `website:` is absent and `site:` has a docs key), marked TRANSITIONAL and deleted in Task 9.
Run again. Expected: PASS. Then fix the census: a refusal text in `site.py` that names `site:` changes,
so update its `CENSUS` key fragment.

- [ ] **Step 6: Commit**

```bash
git add -A src/simplon src/tests
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" \
GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F- <<'EOF'
feat(si#344): the environment matrix is read from cd:, the docs site from website:

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 8: Migrate the kernel's own manifests, the starter manifest, the fixtures and the docs

**Files:**
- Modify: `simplon.yaml` (by the command, not by hand)
- Modify: `src/simplon/bootstrap.py:485-545` (the starter manifest template)
- Modify: `src/tests/fixtures/case_{cpp,dotnet,java}_manifest.yaml`, every test file with an inline
  `groups:` manifest (about 50, measured: `grep -rl "groups:" src/tests | wc -l`)
- Modify: `docs/site/content/**/*.md` pages that show a manifest (measured: test-levels, why, releases,
  environments, the-design, case-java, what-init-wrote, manifest, task-and-command, tasks)
- Create: `src/tests/fixtures/manifests/migrate_inline.py` (a one-off script; deleted at the end of this
  task)

**Interfaces:**
- Consumes: `migrate_text(text, unknown_groups_into="ci")` (Task 5).

- [ ] **Step 1: Migrate `simplon.yaml` with its own command**

Run: `./simplon.sh support manifest migrate`
Expected: rc 0 and a list of moved sections (`groups: build -> ci: build`, `groups: test -> ci: test`,
`groups: release -> ci: release`, `groups: support -> support`, `default -> cd: default`,
`site -> website`). Read the diff (`git diff simplon.yaml`): comments in place, nothing else changed.
This is the step that dogfoods the splice on a 650-line commented manifest. Any surprise here is a
finding for Task 5, not something to fix by hand.

- [ ] **Step 2: Move the starter manifest template**

Rewrite `bootstrap.py`'s template (line 485 onwards) in the new form, by hand, keeping its comments. Then
run `../../deploy/orchestrator/.venv/bin/python -m pytest test_init_contract.py test_getting_started_scaffold.py test_bootstrap.py -q`.
Expected: PASS, after updating any test that pins the template's `groups:` text.

- [ ] **Step 3: Write the fixture script**

```python
"""ONE-OFF (si#344 plan A Task 8): migrate the manifests embedded in the test suite.

Rewrites (a) whole fixture YAML files and (b) triple-quoted YAML strings inside test modules that
contain a top-level `groups:` line. Each string is dedented, migrated with `unknown_groups_into="ci"`
(test manifests have groups no catalogue declares; under the transparent `ci` they keep their CLI path),
re-indented and spliced back. Prints every file it touched and every string it could not migrate.
Deleted at the end of the task that runs it.
"""
import pathlib
import re
import sys
import textwrap

from simplon.tasks.migrate import migrate_text

STRING = re.compile(r'("""|\'\'\')(.*?)(\1)', re.S)


def migrate_string(body: str) -> str | None:
    if not re.search(r"(?m)^\s*groups:\s*$", body):
        return None
    indent = min((len(line) - len(line.lstrip()) for line in body.splitlines() if line.strip()), default=0)
    result = migrate_text(textwrap.dedent(body), unknown_groups_into="ci")
    if result.status != "migrated":
        return None
    return textwrap.indent(result.text, " " * indent) if indent else result.text


def main(paths: list[str]) -> None:
    for name in paths:
        path = pathlib.Path(name)
        text = path.read_text()
        if path.suffix == ".yaml":
            result = migrate_text(text, unknown_groups_into="ci")
            if result.status == "migrated":
                path.write_text(result.text)
                print("file", path)
            elif result.status == "refused":
                print("REFUSED", path, result.reason)
            continue
        new = STRING.sub(lambda m: m.group(1) + (migrate_string(m.group(2)) or m.group(2)) + m.group(3), text)
        if new != text:
            path.write_text(new)
            print("strings", path)


if __name__ == "__main__":
    main(sys.argv[1:])
```

- [ ] **Step 4: Run it over the fixtures and the test modules**

```bash
cd /root/git/simplon/src/tests
../../deploy/orchestrator/.venv/bin/python -I fixtures/manifests/migrate_inline.py \
  fixtures/case_*_manifest.yaml $(grep -rl "groups:" --include=*.py . | grep -v fixtures/manifests)
```

Expected: a list of touched files and possibly some `REFUSED` lines. The eight frozen manifests in
`fixtures/manifests/*.yaml` are **not** passed: they stay in the old form.

Manifests built in Python as dicts (`{"groups": {...}}`) or with f-strings are not touched by the
script. Find them with `grep -rn "\"groups\":\|'groups':" src/tests` and move them by hand: `"groups"`
becomes `"ci"` for build/test/release groups, `"cd"` for deploy/monitor, and the support node goes
top-level; any `"env_groups"` is deleted.

- [ ] **Step 5: Run the whole suite**

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest -q`
Expected: PASS (minus the three root-bound failures). Two kinds of failure are expected here:
- tests that pin a manifest's text layout. Update the pin to the migrated text;
- tests about the `groups:` form itself: `test_treeform.py`'s `check_no_old_form`, and tests of the
  `groups:` mapping refusal in `test_manifest.py`. Leave those on `groups:`, because Task 9 is where they
  become cut-diagnosis tests, and mark each one `# si#344 Task 9: becomes a cut diagnosis`.

- [ ] **Step 6: Migrate the docs pages**

For each page in the file list, edit the YAML blocks by hand into the new form. The narrative may say
"the `groups:` section"; change it to "`ci:` / `cd:` / `support:`" only where it describes the current
form, and leave history (release notes, design pages that tell what was) as it is.
`docs/site/content/when/releases.md` is history, so it gets no edits. The case chapters
(`what/case-java.md` and its siblings) are checked by `test_case_*_chapter.py` against the fixtures, so
run those tests after editing.

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest -q -k "chapter or page or site"`
Expected: PASS.

- [ ] **Step 7: Delete the script and commit**

```bash
git rm -q --cached src/tests/fixtures/manifests/migrate_inline.py 2>/dev/null; rm -f src/tests/fixtures/manifests/migrate_inline.py
git add -A simplon.yaml src/simplon/bootstrap.py src/tests docs/site/content
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" \
GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F- <<'EOF'
chore(si#344): migrate the kernel's own manifest, the starter, the fixtures and the docs

simplon.yaml was rewritten by `support manifest migrate` itself.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 9: The cut: `env_groups:` deleted, the old form refused, the transitional paths removed

**Files:**
- Modify: `src/simplon/orchestrator/manifest.py`:
  - `_ManifestModel.env_groups` and `_coerce_env_groups`;
  - rule 1 and rule 2 in `_validate_taxonomy`;
  - `load`'s `tree_from_groups` branch and `check_env_groups` call;
  - `Manifest.env_groups`, which becomes derived.
- Modify: `src/simplon/orchestrator/model/treeform.py`: delete `check_env_groups` and
  `tree_from_groups`; add `check_no_pre_si344_form`.
- Modify: `src/simplon/environments.py` (`matrix_section` fallback), `src/simplon/tasks/site.py`
  (fallback)
- Delete: `src/tests/test_env_groups.py`
- Create: `src/tests/test_cut.py`
- Modify: `src/tests/test_refusal_census.py`, `docs/site/content/with-what/rules.md` (counts)

**Interfaces:**
- Produces: `treeform.check_no_pre_si344_form(data: dict, manifest_path: str | None) -> None`, called in
  `load` directly after `check_no_old_form`.
- `Manifest.env_groups` stays a field, filled in `load` as
  `frozenset(name for name, node in tree.items() if node.env_first)`. Its consumers (`completiongen`,
  `clitaxonomy`) are unchanged.

- [ ] **Step 1: Write the failing cut tests**

```python
"""The cut (si#344, spec A.6): every key of the old form is refused by name, with the way out - never
silently ignored, which is what `extra="ignore"` would otherwise do to it. AAA throughout."""
import textwrap

import pytest

from simplon import catalogue as catalogue_mod
from simplon.orchestrator import manifest as manifest_mod

MIGRATE = (
    "Rewrite it with the migration, which loads no manifest and so works on this one:\n"
    "  venv:      <orch-dir>/.venv/bin/simplon manifest migrate demo.yaml\n"
    "  container: docker run --rm --user \"$(id -u):$(id -g)\" -v \"$PWD:/src\" -w /src "
    "<kernel image> simplon manifest migrate demo.yaml")


def _load(text: str):
    return manifest_mod.load(textwrap.dedent(text), catalogue=catalogue_mod.load(),
                             manifest_path="demo.yaml")


def test_groups_is_refused_with_the_new_form_and_both_routes():
    # act / assert
    with pytest.raises(ValueError) as caught:
        _load("""\
            product: demo
            groups:
              build:
                commands:
                  w: { task: "build:image" }
        """)
    assert str(caught.value) == (
        "demo.yaml declares `groups:`, which si#344 replaced: commands stand under `ci:` (build, test, "
        "release), `cd:` (deploy, monitor) and `support:`, and the command line does not change:\n"
        "  ci:\n    build:\n      commands: { ... }\n" + MIGRATE)


def test_groups_beside_ci_is_refused_too_not_merged():
    # act / assert: half-migrated by hand (Review Focus 1)
    with pytest.raises(ValueError, match="declares `groups:`, which si#344 replaced"):
        _load("""\
            product: demo
            ci:
              build:
                commands:
                  w: { task: "build:image", with: { name: k } }
            groups:
              test:
                commands:
                  t: { task: "test:typecheck-python" }
        """)


def test_env_groups_is_refused():
    with pytest.raises(ValueError) as caught:
        _load("product: demo\nenv_groups: [deploy]\nci:\n  build:\n    commands:\n      w: { task: \"build:image\" }\n")
    assert str(caught.value) == (
        "demo.yaml declares `env_groups:`, which si#344 deleted: everything under `cd:` takes an "
        "environment and nothing under `ci:` does, so the structure says it. Delete the key.\n" + MIGRATE)


@pytest.mark.parametrize("key", ["default", "environments"])
def test_a_top_level_matrix_key_is_refused(key):
    with pytest.raises(ValueError) as caught:
        _load(f"product: demo\n{key}: x\nci:\n  build:\n    commands:\n      w: {{ task: \"build:image\" }}\n")
    assert str(caught.value) == (
        f"demo.yaml declares `{key}:` at the top level; since si#344 it stands under `cd:`, beside the "
        f"commands that take an environment.\n" + MIGRATE)


def test_a_docs_site_section_is_refused_as_website():
    with pytest.raises(ValueError) as caught:
        _load("product: demo\nsite:\n  theme: x\nci:\n  build:\n    commands:\n      w: { task: \"build:image\" }\n")
    assert str(caught.value) == (
        "demo.yaml declares a top-level `site:` with the documentation site's keys; since si#344 that "
        "section is `website:`, and `site:` is the deployment location under `cd:`.\n" + MIGRATE)


def test_a_location_site_at_the_top_level_is_refused_toward_cd():
    # act / assert (Review Focus 2)
    with pytest.raises(ValueError) as caught:
        _load("product: demo\nsite:\n  central: {}\nci:\n  build:\n    commands:\n      w: { task: \"build:image\" }\n")
    assert str(caught.value) == (
        "demo.yaml declares a top-level `site:`. The deployment location stands under `cd: site:` "
        "(si#344), and the documentation site is `website:` - move it to whichever it is")


def test_a_manifest_with_no_commands_anywhere_says_where_they_go():
    with pytest.raises(ValueError) as caught:
        manifest_mod.load("product: demo\n")
    assert str(caught.value) == "manifest declares no commands under ci:, cd: or support:"
```

Note the last test loads **without** a catalogue. With one, `support:` always has placed commands, so
rule 1 can only fire catalogue-less. That is today's behaviour too. Check that it is still true; if it
is not, rule 1 is unreachable from a product and the census will say so
(`test_every_census_key_names_exactly_one_refusal`).

**The `<orch-dir>` and `<kernel image>` placeholders are deliberate.** The loader is pure and is handed
text, not a launcher. The spec's A.6 promise, "filled from what the product's launcher declares", is
kept by the product CLI's `main` (`cli.py:587`): it catches this specific refusal (by message prefix
`declares \`groups:\`` and its siblings) and replaces the two placeholders with
`os.environ.get("LAUNCH_ORCH_DIR")` and the pin read from `LAUNCH_IMAGE_PIN` when the launcher exported
them. Check with `grep -n "export" src/simplon/templates/launch.sh.j2` whether it exports them. If it
does not, **leave the placeholders and tell Marco**: exporting two variables is a launcher change for
every product, and that is his call, not this plan's.

- [ ] **Step 2: Run to verify they fail**

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest test_cut.py -v`
Expected: all FAIL. `groups:` still loads (transitional), `env_groups:` loads, and so on.

- [ ] **Step 3: Implement `check_no_pre_si344_form`** in `treeform.py`, beside `check_no_old_form`

```python
_MIGRATE = (
    "Rewrite it with the migration, which loads no manifest and so works on this one:\n"
    "  venv:      <orch-dir>/.venv/bin/simplon manifest migrate {name}\n"
    "  container: docker run --rm --user \"$(id -u):$(id -g)\" -v \"$PWD:/src\" -w /src "
    "<kernel image> simplon manifest migrate {name}")

_DOCS_SITE_KEYS = ("image", "base_url", "theme", "source", "output")


def check_no_pre_si344_form(data: dict, manifest_path: str | None) -> None:
    """Refuse every key of the form si#344 replaced, by name, with the way out.

    DIAGNOSIS, all of it: `_ManifestModel` ignores unknown top-level keys, so without this a `groups:`
    manifest would load as a product with no commands and a top-level `environments:` would leave every
    deploy without a matrix - green at load, wrong at the first command. Runs FIRST, before any check
    could report a symptom instead.
    """
    name = manifest_path or "the manifest"
    how = _MIGRATE.format(name=manifest_path or "<manifest>.yaml")
    if "groups" in data:
        raise ValueError(
            f"{name} declares `groups:`, which si#344 replaced: commands stand under `ci:` (build, test, "
            f"release), `cd:` (deploy, monitor) and `support:`, and the command line does not change:\n"
            f"  ci:\n    build:\n      commands: {{ ... }}\n{how}")
    if "env_groups" in data:
        raise ValueError(
            f"{name} declares `env_groups:`, which si#344 deleted: everything under `cd:` takes an "
            f"environment and nothing under `ci:` does, so the structure says it. Delete the key.\n{how}")
    for key in ("default", "environments"):
        if key in data:
            raise ValueError(
                f"{name} declares `{key}:` at the top level; since si#344 it stands under `cd:`, beside "
                f"the commands that take an environment.\n{how}")
    site = data.get("site")
    if site is not None:
        if isinstance(site, dict) and any(k in site for k in _DOCS_SITE_KEYS):
            raise ValueError(
                f"{name} declares a top-level `site:` with the documentation site's keys; since si#344 "
                f"that section is `website:`, and `site:` is the deployment location under `cd:`.\n{how}")
        raise ValueError(
            f"{name} declares a top-level `site:`. The deployment location stands under `cd: site:` "
            f"(si#344), and the documentation site is `website:` - move it to whichever it is")
```

In `load`, call it right after `treeform.check_no_old_form(data)`. Delete the `tree_from_groups` branch,
the function itself, `check_env_groups` with its call, `_ManifestModel.env_groups`,
`_coerce_env_groups`, and rule 2. Rule 1's message becomes
`"manifest declares no commands under ci:, cd: or support:"`. Fill `Manifest.env_groups` from the tree
as stated under Interfaces. Delete the transitional fallbacks in `environments.matrix_section` and
`tasks/site.py`.

`check_no_old_form` may itself read `data.get("groups")` for its own flat-form detection. Read it, and
if it does, make sure the new check runs first, so that a `groups:` manifest gets the si#344 message and
not the si#33 one.

- [ ] **Step 4: Run the cut tests, then the suite**

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest test_cut.py -v`, then `-q` over everything.
Expected: `test_cut.py` PASSES. In the suite, the tests marked `# si#344 Task 9` in Task 8 fail: rewrite
each as an assertion of the new diagnosis, or delete it where `test_cut.py` now covers it. Delete
`test_env_groups.py`. Its si#43 history stays in git; the census entry it held goes in Step 5.

Then see the most important one red: comment out the `"groups" in data` branch, run
`test_groups_is_refused_with_the_new_form_and_both_routes`, watch it FAIL, and restore it.

- [ ] **Step 5: The census and the page**

Remove the entries for:
- `("manifest", "_coerce_env_groups", ...)`,
- `("manifest", "_validate_taxonomy", "names a NESTED group")`,
- `("manifest", "_validate_taxonomy", "is not a declared group")`,
- `("treeform", "check_env_groups", ...)` in both `CENSUS` and `REACH`,
- any `tree_from_groups` entry.

Change `"manifest defines no groups"` to `"declares no commands under ci:, cd: or support:"`. Add the
six `check_no_pre_si344_form` raises as `DIAGNOSIS`, keyed on `"declares \`groups:\`, which si#344
replaced"`, `"which si#344 deleted"`, `"at the top level; since si#344"`, `"with the documentation
site's keys"` and `"The deployment location stands under"`.

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest test_refusal_census.py -v`
Expected: PASS, after updating `with-what/rules.md`'s printed counts to what
`test_the_page_prints_the_census_count_for_each_kind` demands. Add one sentence there, under the
expression-rule count, saying that si#344 deleted the `env_groups:` rule (si#43) with its key: the first
change in this series that lowered the expression-rule count.

- [ ] **Step 6: Commit**

```bash
git add -A src/simplon src/tests docs/site/content/with-what/rules.md
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" \
GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F- <<'EOF'
feat(si#344): the cut - groups:, env_groups: and the top-level matrix are refused by name

Every key of the replaced form is a diagnosis naming the migration, which
works on a manifest the kernel no longer loads. env_groups: goes with its
rule (si#43); Manifest.env_groups is derived from the tree.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 10: Hold the promise: the eight real manifests, migrated, assemble the CLI they always did

**Files:**
- Modify: `src/tests/test_migrate.py`
- Modify: `src/tests/test_coordinate_placement.py`

**Interfaces:**
- Consumes: `cli_surface` and the goldens (Task 1), `migrate_text` (Task 5), the cut kernel (Task 9).

- [ ] **Step 1: Write the golden test**

```python
#: What the migrated surface may differ by, and nothing else: si#344 places one new command for every
#: product (`support manifest migrate`).
NEW_IN_EVERY_PRODUCT = {"support.manifest": ["migrate"]}


@pytest.mark.parametrize("product", PRODUCTS)
def test_a_migrated_real_manifest_assembles_the_cli_it_always_did(product):
    # arrange
    golden = json.loads((FIXTURES / "golden" / f"{product}.json").read_text())
    migrated = migrate_text((FIXTURES / f"{product}.yaml").read_text())

    # act
    surface = cli_surface(manifest.load(migrated.text, catalogue=catalogue.load(),
                                        manifest_path=f"{product}.yaml"))

    # assert
    for group, members in NEW_IN_EVERY_PRODUCT.items():
        assert surface["groups"].pop(group) == members
        surface["commands"].pop(group)
    assert surface == golden


@pytest.mark.parametrize("product", PRODUCTS)
def test_the_unmigrated_real_manifest_is_refused_by_the_cut(product):
    # act / assert
    with pytest.raises(ValueError, match="which si#344 replaced"):
        manifest.load((FIXTURES / f"{product}.yaml").read_text(), catalogue=catalogue.load())
```

The goldens were recorded with the old catalogue, which had no `support.manifest`, so that subgroup is
the one expected difference. If a product's golden differs in anything else, that is a finding: do not
edit the golden. Report it to Marco with the diff.

- [ ] **Step 2: Run them**

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest test_migrate.py -v`
Expected: PASS for all products. To see it red, break the migration on purpose: in `migrate_text`, drop
`release` from `CI`. Run, watch the products with a `release` group FAIL, and restore.

- [ ] **Step 3: Hold si#34's count**

In `test_coordinate_placement.py`:

```python
def test_the_kernels_own_manifest_rules_on_as_many_placements_as_before_the_transparent_level():
    """si#344, spec A.3: the count si#34 rules on over simplon.yaml must not drop when `ci`/`cd` became a
    tree level. A drop means the rule stopped applying to something. 7 is the count measured with the
    pre-si#344 kernel on 2026-10-11 (Task 10 Step 3 of plan A records how)."""
    # arrange
    calls = []
    original = treeform.check_coordinate_placement

    def spy(flat, groups):
        calls.append(original(flat, groups))
        return calls[-1]

    # act
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(treeform, "check_coordinate_placement", spy)
        manifest_mod.load((ROOT / "simplon.yaml").read_text(), catalogue=catalogue_mod.load())

    # assert
    assert calls == [7]
```

**Record the real number first, do not trust the 7:**
`git stash; git checkout main -- src/simplon simplon.yaml`, run the same spy in a Python snippet, read
the count, then `git checkout HEAD -- src/simplon simplon.yaml; git stash pop`. Put the measured number
in the test and its docstring. Then add the count of the new `support.manifest` placement: its
coordinate is `support:migrate` under `support`, so the count after the change is the pre-change count
+ 1. Write it as `assert calls == [BEFORE + 1]` with `BEFORE` the measured constant, so the reason for
the difference is in the assertion and not hidden in a total.

- [ ] **Step 4: Run the full suite and the type gate**

Run: `../../deploy/orchestrator/.venv/bin/python -m pytest -q` and `./simplon.sh test typecheck-python`
Expected: PASS, minus the three root-bound failures. mypy is clean.

- [ ] **Step 5: Commit**

```bash
git add src/tests/test_migrate.py src/tests/test_coordinate_placement.py
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" \
GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F- <<'EOF'
test(si#344): eight real manifests migrate to the same CLI, and si#34 rules on as much as before

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

## After this plan

- Open the PR with "Closes" **nothing**: si#344 closes with plan C (memory: the closing keyword is
  `Closes #<n>`, and plain `si#<n>` closes nothing; here neither is wanted). The body names plan A and
  says the release waits for plan B.
- Ask each product's peer session (agile-cockpit, asbundle, biz-cockpit, cleon, firn, netctl, swi) to
  run `simplon manifest migrate` on a branch against the PR's kernel and report its diff. This is the
  "ask before shipping" step, and it can start as soon as Task 6 is merged.
- Plan B starts from `support manifest migrate` and extends `migrate_text` with the `images:` fold.
