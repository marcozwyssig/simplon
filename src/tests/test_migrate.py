"""The migration (si#344 plan A): text in, text out, and the CLI it assembles unchanged."""
import json
import pathlib
import re
import textwrap

import pytest
import yaml

import realmanifests
from simplon.domain import catalogue, yamlkeys
from simplon.domain import manifest
from simplon.tasks.migrate import migrate_text
from manifestsurface import cli_surface

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "manifests"
PRODUCTS = sorted(p.stem for p in (FIXTURES / "golden").glob("*.json"))


def test_there_are_eight_goldens():
    # assert: the population is the eight reachable manifests, not whichever happened to load
    assert len(PRODUCTS) + len(_not_loadable()) == 8


def _not_loadable() -> list[str]:
    readme = (FIXTURES / "README.md").read_text()
    return [line.split("`")[1] for line in readme.splitlines() if line.startswith("- `")]


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


def test_an_env_groups_entry_naming_a_group_the_manifest_does_not_have_is_refused():
    # arrange: the old loader refused this manifest ("is not a declared group"); deleting the entry would
    # turn it into one that loads, and nobody would have said so
    text = "product: demo\ngroups:\n  build:\n    commands:\n      w: { task: wheel }\nenv_groups: [deploy]\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.text == text
    assert result.reason == ("env_groups: [deploy] names 'deploy', which groups: does not declare - the "
                             "manifest did not load before the migration either, so deleting the entry "
                             "would hide a mistake rather than move it. Declare the group or drop the entry, "
                             "and run again")


def test_a_document_that_does_not_parse_is_refused_naming_the_parse_error():
    # arrange: the starter template's own placeholder, which is not YAML until it is substituted
    text = "product: @@PRODUCT@@\ngroups:\n  build: {}\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.text == text
    assert result.reason.startswith("it is not valid YAML, so nothing can be moved: line 1, column 10: ")
    assert "'@'" in result.reason


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


def test_a_splice_that_does_not_parse_back_is_refused_and_names_where(monkeypatch):
    # arrange: an oracle that disagrees with the splice - the guard has to name where, whatever the cause
    from simplon.tasks import migrate as migrate_mod
    monkeypatch.setattr(migrate_mod, "_expected", lambda old, into=None: {"product": "demo", "ci": {}})
    text = "product: demo\ngroups:\n  build:\n    commands:\n      w: { task: wheel }\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.text == text
    assert result.reason == "the spliced text does not parse back to the same manifest: ci.build"


#: A key the splice writes, already standing at the top level beside what it would move there - in both
#: orders. YAML keeps the last of two equal keys, so a splice that wrote a second one "migrated" and the
#: first one's content vanished on load (measured: `ci: build:` + `groups: test:` lost `build`).
COLLISIONS = {
    "ci, before groups": ("product: demo\nci:\n  build:\n    commands:\n      a: { task: wheel }\n"
                          "groups:\n  test:\n    commands:\n      t: { task: pytest }\n", "ci", "groups"),
    "ci, after groups": ("product: demo\ngroups:\n  test:\n    commands:\n      t: { task: pytest }\n"
                         "ci:\n  build:\n    commands:\n      a: { task: wheel }\n", "ci", "groups"),
    "cd, before default": ("product: demo\ncd:\n  deploy:\n    commands:\n      u: { task: up }\n"
                           "default: dev\n", "cd", "default"),
    "cd, after default": ("product: demo\ndefault: dev\n"
                          "cd:\n  deploy:\n    commands:\n      u: { task: up }\n", "cd", "default"),
    "support, before groups": ("product: demo\nsupport:\n  commands:\n    a: { task: doctor }\n"
                               "groups:\n  support:\n    commands:\n      b: { task: doctor }\n",
                               "support", "groups"),
    "support, after groups": ("product: demo\ngroups:\n  support:\n    commands:\n      b: { task: doctor }\n"
                              "support:\n  commands:\n    a: { task: doctor }\n", "support", "groups"),
    "website, before site": ("product: demo\nwebsite:\n  image: x\nsite:\n  image: y\n", "website", "site"),
    "website, after site": ("product: demo\nsite:\n  image: y\nwebsite:\n  image: x\n", "website", "site"),
}


@pytest.mark.parametrize("case", sorted(COLLISIONS))
def test_a_key_the_splice_writes_that_already_exists_is_refused_by_name(case):
    # arrange
    text, written, source = COLLISIONS[case]

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.text == text
    assert result.reason == (f"`{written}:` already exists beside `{source}:` - merge them by hand, "
                             "then run again")


def test_the_oracle_refuses_a_key_it_would_overwrite():
    # arrange: the second guard - should the pre-check ever miss a key, the data check must not pass by
    # overwriting the existing one the way YAML would
    from simplon.tasks.migrate import _expected

    # act / assert
    with pytest.raises(ValueError, match="`ci:` already exists beside `groups:`"):
        _expected({"product": "demo", "ci": {"build": {}}, "groups": {"test": {}}})


def test_an_empty_groups_with_a_comment_on_its_key_line_is_refused_rather_than_losing_it():
    # arrange: no section moves, so there is no area for the comment to travel onto
    text = "product: demo\ngroups:  # c\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.text == text
    assert result.reason == ("groups: on line 2 holds no section to move, so its comment ('# c') has no "
                             "area to travel onto - move the comment or delete it, and run again")


@pytest.mark.parametrize("value", ["null  ", "~ "])
def test_a_comment_after_an_empty_groups_value_is_refused_even_when_something_else_moves(value):
    # arrange: `default:` moves, so the run "migrated" - and the comment after `null` / `~` went with the
    # deleted key line (measured: `cd:\n  default: dev\n`, the comment gone)
    text = f"product: demo\ngroups: {value}# c\ndefault: dev\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.text == text
    assert result.reason == ("groups: on line 2 holds no section to move, so its comment ('# c') has no "
                             "area to travel onto - move the comment or delete it, and run again")


@pytest.mark.parametrize("text", ["product: demo\ngroups:\n", "product: demo\ngroups: null\n",
                                  "product: demo\ngroups: {}\n"])
def test_an_empty_groups_that_moves_nothing_is_refused_not_migrated(text):
    # arrange: "migrated (0 section(s) moved)" was the old answer - green, and nothing done

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.text == text
    assert result.reason == ("groups: on line 2 holds no section, so there is nothing to move into ci: / "
                             "cd: / support: - delete the key by hand, and run again")


def test_a_groups_indented_by_four_spaces_is_refused_naming_the_indentation():
    # arrange
    text = "product: demo\ngroups:\n    build:\n        commands:\n            a: { task: wheel }\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.text == text
    assert result.reason == ("groups: indents its sections by 4 spaces (line 3); the splice moves a "
                             "manifest indented by two spaces per level, the way `simplon init` writes "
                             "one - reindent it, and run again")


def test_groups_declared_twice_with_different_content_is_refused_naming_both_lines():
    # arrange
    text = ("product: demo\n"
            "groups:\n  build:\n    commands:\n      w: { task: wheel }\n"
            "groups:\n  test:\n    commands:\n      t: { task: pytest }\n")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.text == text
    assert result.reason == ("groups is written twice, on lines 2 and 6, and the two copies differ - YAML "
                             "keeps only the second, so merge them into one by hand, and run again")


def test_a_comment_on_the_groups_key_line_is_carried_onto_the_first_area():
    # arrange
    text = "product: demo\ngroups:   # the command groups\n  build:\n    commands:\n      w: { task: wheel }\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated", result.reason
    assert result.text == "product: demo\nci:   # the command groups\n  build:\n    commands:\n      w: { task: wheel }\n"


def test_a_groups_holding_only_comments_is_refused_rather_than_losing_them():
    # arrange: there is no area to carry the comment into, and the data check cannot see it go
    text = "product: demo\ngroups:\n  # nothing yet\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.text == text
    assert result.reason == ("groups: on line 2 holds no section, so there is nothing to move into ci: / "
                             "cd: / support: - delete the key by hand, and run again")


def test_a_support_line_too_shallow_to_dedent_is_refused_naming_its_column():
    # arrange: a column-1 comment trailing the support group, with no group after it to take it
    text = "product: demo\ngroups:\n  support:\n    commands:\n      d: { task: doctor }\n # stray\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.reason == ("groups: support carries line 6 at column 1 ('# stray'); support: moves to the "
                             "top level by removing two spaces from each of its lines, and that line has "
                             "only 1 to remove - indent it or move it out of the support group, and run again")


def test_a_comment_above_env_groups_is_deleted_with_it_and_the_move_says_so():
    # arrange
    text = ("product: demo\ngroups:\n  deploy:\n    commands:\n      u: { task: up }\n"
            "# deploy only\nenv_groups: [deploy]\n")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated", result.reason
    assert result.text == "product: demo\ncd:\n  deploy:\n    commands:\n      u: { task: up }\n"
    assert result.moved[-1] == "env_groups: deleted ([deploy]) with the 1 comment line it owns"


def test_a_group_written_twice_identically_keeps_one_copy_and_says_so():
    # arrange: cleon's shape - the second copy is the first, line for line
    text = ("product: demo\n"
            "groups:\n  support:\n    commands:\n      a: { task: doctor }\n"
            "  support:\n    commands:\n      a: { task: doctor }\n")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated", result.reason
    assert result.text == "product: demo\nsupport:\n  commands:\n    a: { task: doctor }\n"
    assert result.moved[0] == ("groups.support: written twice, identically (lines 3 and 6) - the second "
                               "copy dropped")


def test_a_group_written_twice_differently_is_refused_and_nothing_is_written(tmp_path):
    # arrange: the shape the old test pinned as "keeps both copies" - YAML loses `a`, so the migration may not
    path = tmp_path / "demo.yaml"
    text = ("product: demo\n"
            "groups:\n  support:\n    commands:\n      a: { task: doctor }\n"
            "  support:\n    commands:\n      b: { task: doctor }\n")
    path.write_text(text)

    # act
    rc = migrate_mod.migrate(str(path))

    # assert
    assert rc == 1
    assert path.read_text() == text
    assert migrate_text(text).reason == (
        "groups.support is written twice, on lines 3 and 6, and the two copies differ - YAML keeps only the "
        "second, so merge them into one by hand, and run again")


def test_cleons_doubled_groups_come_out_once():
    # arrange: the frozen text for the line numbers (cleon's hand edit adds a line above them)
    raw = (realmanifests.FIXTURES / "cleon.yaml").read_text()

    # act
    deduped = migrate_mod._dedupe(raw)
    result = migrate_text(realmanifests.text("cleon"))

    # assert: both duplicates named, in document order, with the frozen file's line numbers
    assert deduped.status == "migrated", deduped.reason
    assert deduped.moved == (
        "groups.release: written twice, identically (lines 215 and 233) - the second copy dropped",
        "groups.support: written twice, identically (lines 222 and 240) - the second copy dropped")
    # assert: and the whole migration's result loads with the duplicate check on
    assert result.status == "migrated", result.reason
    assert yamlkeys.load(result.text)


def test_a_duplicate_in_a_sequence_item_is_refused_in_a_sentence_that_says_so():
    # arrange: review finding M4 - the `- ` prefix makes the copy uncuttable, and "flow mapping" was wrong
    text = "product: demo\nlist:\n  - a: 1\n    a: 1\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert "inside a flow mapping or a sequence item (line 4)" in result.reason


def test_a_merge_override_in_a_mapping_merged_elsewhere_is_not_a_duplicate_to_the_migration():
    # arrange: review finding I1, the loader's reproducer
    from test_yamlkeys import MERGED_OVERRIDE

    # act
    result = migrate_text(MERGED_OVERRIDE)

    # assert
    assert (result.status, result.reason) == ("current", "")


def test_two_spellings_of_one_boolean_key_are_a_duplicate_to_the_migration_too():
    # arrange: review minor 3 - `yes:` and `true:` are one key to YAML, and the lines differ
    text = "product: demo\nflags:\n  yes: 1\n  true: 1\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.reason == ("flags.true is written twice, on lines 3 and 4, and the two copies differ - YAML "
                             "keeps only the second, so merge them into one by hand, and run again")


def test_a_list_written_at_its_keys_own_indent_twice_identically_keeps_one_copy():
    # arrange: review minor 1 - PyYAML's own dump style puts `- ` at the key's column
    text = "product: demo\nl:\n- x\n- y\nl:\n- x\n- y\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated", result.reason
    assert result.text == "product: demo\nl:\n- x\n- y\n"


def test_copies_that_differ_only_in_indentation_are_said_to_differ():
    # arrange: review minor 2 - `c` is a sibling of `b` in one copy and its child in the other
    text = "product: demo\na:\n  b:\n  c: 1\na:\n  b:\n    c: 1\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.reason == ("a is written twice, on lines 2 and 5, and the two copies differ - YAML keeps "
                             "only the second, so merge them into one by hand, and run again")


def test_a_merge_key_override_is_not_a_duplicate_to_the_migration():
    # arrange
    text = "product: demo\nbase: &b {a: 1}\nx:\n  <<: *b\n  a: 2\n"

    # act / assert
    assert migrate_text(text).status == "current"


def test_a_column_0_comment_above_a_group_travels_with_that_group():
    # arrange: firn's shape - a comment at column 0, inside groups:, directly above `  deploy:`
    text = ("product: demo\n"
            "groups:\n  support:\n    commands:\n      doctor: { task: doctor }\n"
            "\n# --- deploy ---\n  deploy:\n    commands:\n      up: { task: up }\n")

    # act
    result = migrate_text(text)

    # assert: it lands under cd:, directly above deploy:, and keeps its column
    assert result.status == "migrated", result.reason
    assert result.text == ("product: demo\n"
                           "cd:\n# --- deploy ---\n  deploy:\n    commands:\n      up: { task: up }\n"
                           "support:\n  commands:\n    doctor: { task: doctor }\n")


@pytest.mark.parametrize("product", PRODUCTS)
def test_every_real_manifest_migrates_and_parses_back_to_the_same_content(product):
    # arrange
    text = realmanifests.text(product)

    # act
    result = migrate_text(text)

    # assert: one run from the frozen `groups:` form to the current form, both cuts
    assert result.status == "migrated", result.reason
    top = [line.split("#")[0].strip() for line in result.text.splitlines() if not line.startswith(" ")]
    assert "groups:" not in top and "images:" not in top
    artifacts = yaml.safe_load(result.text).get("artifacts") or {}
    assert all(isinstance(body, dict) and "kind" in body and "source" not in body
               for body in artifacts.values()), artifacts


@pytest.mark.parametrize("product", PRODUCTS)
def test_a_migrated_real_manifest_is_current_on_the_second_run(product):
    # arrange
    once = migrate_text(realmanifests.text(product))

    # act
    twice = migrate_text(once.text)

    # assert: the second run says so in its own outcome, and touches nothing
    assert (twice.status, twice.text) == ("current", once.text)


def test_cleon_without_its_hand_edit_is_refused_by_name_with_the_kinds():
    # arrange: no command of cleon's reads `updatesite` through a catalogue task - its own code publishes it
    text = (realmanifests.FIXTURES / "cleon.yaml").read_text()

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    # assert: the lists pinned as literals - built from READERS/REFINES on both sides, this could not see
    # an order change
    assert result.reason == (
        "artifacts: updatesite declares no `kind:`, and no command reads it through a catalogue task that "
        "names its kind (build:conan-cache, build:image, build:maven-pack, build:nuget-config, build:nuget-pack, build:nuget-restore, release:artifact, release:conan, release:image, release:maven, release:nuget, test:image) - add `kind:` to it by hand, one of artifact, image, directory, site, nuget, maven, conan, test-result, release-notes, tag, release, and run again")


def test_netctls_bare_image_references_keep_their_value_and_their_comment():
    # act
    lines = migrate_text(realmanifests.text("netctl")).text.splitlines()

    # assert: a reference that is not `:local` is kept as written, and so is the comment after it
    assert '  web: { kind: image, local: "netctl:local" }' in lines
    assert ('  iol: { kind: image, local: "netctl-iol:17.18.02" }            '
            '# #1475: built from the CML release asset, no longer pulled') in lines


def test_a_bare_image_reference_becomes_a_local_image_and_keeps_its_comment():
    # arrange
    text = ("product: demo\n"
            "images:\n"
            "  web: demo:local\n"
            "  iol: demo-iol:17.18.02            # built from a release asset\n")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated", result.reason
    assert result.text == ("product: demo\n"
                           "artifacts:\n"
                           '  web: { kind: image, local: "demo:local" }\n'
                           '  iol: { kind: image, local: "demo-iol:17.18.02" }            # built from a release asset\n')
    assert result.moved == ("images: web -> artifacts: web (kind: image)",
                            "images: iol -> artifacts: iol (kind: image)")


def test_a_ci_cd_form_manifest_folds_its_image_and_its_deploy_source():
    # arrange: a manifest that already ran cut 1 and reruns the command for cut 2 - of the live manifests
    # only simplon.yaml is in this form today; the seven product manifests are still byte-identical to their
    # frozen `groups:` fixtures. Comments inside an entry stay put
    text = ("product: demo\n"
            "images:\n"
            "  app:\n"
            "    registry: ghcr.io/acme\n"
            "    # the product root\n"
            "    context: .\n"
            "deploy:\n"
            "  kind: server\n"
            "  source: { images: app }\n")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated", result.reason
    assert result.text == ("product: demo\n"
                           "artifacts:\n"
                           "  app:\n"
                           "    kind: image\n"
                           "    registry: ghcr.io/acme\n"
                           "    # the product root\n"
                           "    context: .\n"
                           "deploy:\n"
                           "  kind: server\n"
                           "  source: { artifacts: app }\n")
    assert result.moved[-1] == "deploy: source: images -> artifacts"


def test_a_block_deploy_source_is_renamed_too():
    # arrange
    text = ("product: demo\n"
            "images:\n  app: { registry: r, repository: d }\n"
            "deploy:\n  kind: server\n  source:\n    images: app\n")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated", result.reason
    assert result.text == ("product: demo\n"
                           "artifacts:\n  app: { kind: image, registry: r, repository: d }\n"
                           "deploy:\n  kind: server\n  source:\n    artifacts: app\n")


def test_a_kindless_entry_takes_the_kind_of_the_coordinate_that_reads_it_and_source_becomes_path():
    # arrange
    text = ("product: demo\n"
            "ci:\n"
            "  release:\n"
            "    commands:\n"
            "      site: { task: \"release:artifact\", with: { name: updatesite } }\n"
            "artifacts:\n"
            "  updatesite:\n"
            "    registry: ghcr.io/acme\n"
            "    source: build/site\n")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated", result.reason
    assert result.text.endswith("  updatesite:\n"
                                "    kind: directory\n"
                                "    registry: ghcr.io/acme\n"
                                "    path: build/site\n")
    assert result.moved == ("artifacts: updatesite gains kind: directory (read by release:artifact)",
                            "artifacts: updatesite: source -> path")


def test_an_entry_two_coordinates_read_as_different_kinds_is_refused():
    # arrange
    text = ("product: demo\n"
            "ci:\n  release:\n    commands:\n"
            "      a: { task: \"release:artifact\", with: { name: x } }\n"
            "      b: { task: \"release:conan\", with: { name: x } }\n"
            "artifacts:\n  x:\n    registry: r\n")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.reason == ("artifacts: x declares no `kind:`, and the commands that read it disagree "
                             "(release:artifact reads a directory, release:conan reads a conan) - add `kind:` "
                             "by hand, and run again")


def test_images_beside_artifacts_are_appended_to_artifacts():
    # arrange
    text = ("product: demo\n"
            "artifacts:\n  site:\n    kind: directory\n    path: build/site\n"
            "images:\n  app: demo:local\n")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated", result.reason
    assert result.text == ("product: demo\n"
                           "artifacts:\n  site:\n    kind: directory\n    path: build/site\n"
                           '  app: { kind: image, local: "demo:local" }\n')


def test_images_beside_a_bare_empty_artifacts_key_fill_it_and_leave_one_key():
    # arrange: preflight P8 - `artifacts:` with nothing under it parses to null, and appending the images
    # anywhere but under it writes a second `artifacts:` key, which YAML resolves to the last one silently
    text = "product: demo\nartifacts:   # filled below\nimages:\n  app: demo:local\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated", result.reason
    assert result.text == ("product: demo\nartifacts:   # filled below\n"
                           '  app: { kind: image, local: "demo:local" }\n')


@pytest.mark.parametrize("written", ["{}", "null", "~"])
def test_images_beside_an_artifacts_key_written_empty_on_its_line_are_refused_by_name(written):
    # arrange: preflight P8 - the fold appends entries under a block-style key; `artifacts: {}` cannot take them
    text = f"product: demo\nartifacts: {written}\nimages:\n  app: demo:local\n"

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.reason == (f"artifacts: is written `{written}` on its key line beside `images:`, and the fold "
                             "appends the images under a block-style `artifacts:` - write it as a bare "
                             "`artifacts:` or delete it, and run again")


def test_a_name_in_both_images_and_artifacts_is_refused_and_nothing_is_written(tmp_path):
    # arrange
    path = tmp_path / "demo.yaml"
    text = ("product: demo\n"
            "artifacts:\n  app:\n    kind: directory\n    path: build/site\n"
            "images:\n  app: demo:local\n")
    path.write_text(text)

    # act
    rc = migrate_mod.migrate(str(path))

    # assert
    assert rc == 1
    assert path.read_text() == text
    assert migrate_text(text).reason == ("'app' is both an `images:` and an `artifacts:` entry, and one "
                                         "section cannot hold the name twice - rename one by hand, and run again")


def test_an_entry_with_both_source_and_path_is_refused():
    # act
    result = migrate_text("product: demo\nartifacts:\n  x:\n    kind: directory\n    source: a\n    path: b\n")

    # assert
    assert result.status == "refused"
    assert result.reason == ("artifacts: x declares both `source:` and `path:`; `source:` is the old name of "
                             "`path:`, so one of the two is stale - delete it by hand, and run again")


@pytest.mark.parametrize("text,reason", [
    ("product: demo\nartifacts:\n  web: x:local\n",
     "artifacts: web is 'x:local', not a mapping - an entry names its `kind:` and its keys; an image reference "
     "is written `web: { kind: image, local: \"x:local\" }` - fix it by hand, and run again"),
    ("product: demo\nartifacts:\n  web:\n",
     "artifacts: web holds nothing - an entry names its `kind:` and its keys; write them by hand, and run again"),
    ("product: demo\nartifacts: [a]\n",
     "artifacts: is a list, not a mapping of artifact name to entry - fix it by hand, and run again"),
])
def test_an_artifacts_section_the_loader_would_refuse_is_cannot_migrate_not_current(text, reason, tmp_path):
    # arrange: review finding B6 - each of these came back "current", rc 0, and the loader then refused it:
    # "nothing to do" standing in for "cannot do"
    path = tmp_path / "demo.yaml"
    path.write_text(text)

    # act
    rc = migrate_mod.migrate(str(path))

    # assert
    assert (migrate_text(text).status, migrate_text(text).reason) == ("refused", reason)
    assert rc == 1 and path.read_text() == text


#: What the migrated surface may differ by, and nothing else: si#344 places one new command for every
#: product (`support manifest migrate`), and si#346 a second (`support manifest model`). The goldens are
#: not refreshed (fixtures/manifests/README.md), so each kernel command is named here instead.
NEW_IN_EVERY_PRODUCT = {"support.manifest": ["migrate", "model"]}


@pytest.mark.parametrize("product", PRODUCTS)
def test_a_migrated_real_manifest_assembles_the_cli_it_always_did(product):
    # arrange
    golden = json.loads((FIXTURES / "golden" / f"{product}.json").read_text())
    migrated = migrate_text(realmanifests.text(product))

    # act: a product the release rule refuses is answered in memory (realmanifests), so its surface is still held
    surface = cli_surface(manifest.load(realmanifests.answer_release_rule(product, migrated.text),
                                        catalogue=catalogue.load(), manifest_path=f"{product}.yaml"))

    # assert: the one command the answer adds is taken out, as NEW_IN_EVERY_PRODUCT's are
    if product in realmanifests.RELEASE_RULE_ANSWERS:
        assert surface["groups"]["test"].remove(realmanifests.ADDED_TEST_COMMAND) is None
        surface["commands"]["test"].pop(realmanifests.ADDED_TEST_COMMAND)
    for group, members in NEW_IN_EVERY_PRODUCT.items():
        assert surface["groups"].pop(group) == members
        surface["commands"].pop(group)
    assert surface == golden


def test_the_release_rule_refuses_exactly_the_products_that_release_untested():
    # arrange / act
    refused = set()
    for product in PRODUCTS:
        migrated = migrate_text(realmanifests.text(product))
        try:
            manifest.load(migrated.text, catalogue=catalogue.load(), manifest_path=f"{product}.yaml")
        except ValueError as exc:
            if "no test produces a result about it" not in str(exc):
                raise
            refused.add(product)

    # assert
    assert refused == realmanifests.RELEASE_RULE_BILL


@pytest.mark.parametrize("product", PRODUCTS)
def test_the_unmigrated_real_manifest_is_refused_by_the_cut(product):
    # arrange: cleon writes two groups twice, and a duplicate is refused before any key is read
    expected = "found `release:` a second time" if product == "cleon" else "which si#344 replaced"

    # act / assert
    with pytest.raises(ValueError, match=re.escape(expected)):
        manifest.load((FIXTURES / f"{product}.yaml").read_text(), catalogue=catalogue.load())


# --- the task body: migrate() -----------------------------------------------------------------------
from simplon.tasks import migrate as migrate_mod  # noqa: E402


def test_migrate_writes_the_file_and_says_what_moved(tmp_path, capsys):
    # arrange
    path = tmp_path / "demo.yaml"
    path.write_text(OLD)

    # act
    rc = migrate_mod.migrate(str(path))

    # assert
    assert rc == 0
    assert path.read_text() == NEW
    out = capsys.readouterr().out
    assert "groups: build -> ci: build" in out
    assert f"demo.yaml: migrated to the current form ({len(migrate_text(OLD).moved)} change(s))" in out


def test_migrate_on_a_current_manifest_is_rc_0_with_its_own_sentence(tmp_path, capsys):
    # arrange
    path = tmp_path / "demo.yaml"
    path.write_text(NEW)

    # act
    rc = migrate_mod.migrate(str(path))

    # assert
    assert rc == 0
    assert path.read_text() == NEW
    assert ("demo.yaml: already in the current form (ci / cd / support, every artifact with its kind) "
            "- nothing to migrate") in capsys.readouterr().out


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


def test_migrate_on_a_document_that_does_not_parse_is_rc_1_and_writes_nothing(tmp_path, capsys):
    # arrange
    path = tmp_path / "demo.yaml"
    text = "product: @@PRODUCT@@\n"
    path.write_text(text)

    # act
    rc = migrate_mod.migrate(str(path))

    # assert: a refusal with its reason, not a traceback
    assert rc == 1
    assert path.read_text() == text
    assert "not valid YAML" in capsys.readouterr().err


def test_migrate_on_a_file_it_cannot_write_is_rc_1_with_a_reason_not_a_traceback(tmp_path, capsys):
    # arrange: a read-only manifest
    import os
    if os.geteuid() == 0:
        pytest.skip("root writes through a 0o444 file mode, so the write cannot be made to fail this way")
    path = tmp_path / "demo.yaml"
    path.write_text(OLD)
    path.chmod(0o444)

    # act
    rc = migrate_mod.migrate(str(path))

    # assert
    assert rc == 1
    assert path.read_text() == OLD
    assert "demo.yaml: not migrated - cannot write demo.yaml: " in capsys.readouterr().err


def test_a_failed_write_is_rc_1_with_a_reason_whoever_runs_it(tmp_path, capsys, monkeypatch):
    # arrange: the same failure without the file mode, so the test also runs as root (where the chmod
    # variant above has to skip)
    import pathlib as _pathlib
    path = tmp_path / "demo.yaml"
    path.write_text(OLD)

    def refuse(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(_pathlib.Path, "write_text", refuse)

    # act
    rc = migrate_mod.migrate(str(path))

    # assert
    assert rc == 1
    assert path.read_text() == OLD
    assert ("demo.yaml: not migrated - cannot write demo.yaml: [Errno 13] Permission denied"
            in capsys.readouterr().err)


@pytest.mark.parametrize("make", ["missing", "not utf-8"])
def test_migrate_on_a_file_it_cannot_read_is_rc_1_with_a_reason_not_a_traceback(tmp_path, capsys, make):
    # arrange
    path = tmp_path / "demo.yaml"
    if make == "not utf-8":
        path.write_bytes(b"product: d\xe9mo\n")

    # act
    rc = migrate_mod.migrate(str(path))

    # assert
    assert rc == 1
    err = capsys.readouterr().err
    assert "demo.yaml: not migrated, nothing written - cannot read it: " in err
    assert ("No such file or directory" if make == "missing" else "can't decode byte 0xe9") in err
    assert path.exists() == (make == "not utf-8")


def test_importing_the_migration_does_not_import_the_manifest_loader():
    # arrange: `simplon manifest migrate` exists for a manifest the loader refuses; the route must not
    # depend on the loader at all, even at import
    import subprocess
    import sys
    code = ("import sys, simplon.tasks.migrate; "
            "print('simplon.domain.manifest' in sys.modules, 'simplon.domain.context' in sys.modules)")

    # act
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout

    # assert
    assert out.split() == ["False", "False"]


def test_the_migrations_areas_are_the_catalogues():
    # arrange: CI / CD here, and `_phases_of` in the loader's messages, restate which phase groups stand
    # under which area; the catalogue is the statement
    from simplon.domain import treeform
    groups = catalogue.load().groups

    # act
    ci, cd = (tuple(groups[area]["groups"]) for area in ("ci", "cd"))

    # assert
    assert (migrate_mod.CI, migrate_mod.CD) == (ci, cd)
    assert (treeform._phases_of("ci"), treeform._phases_of("cd")) == (", ".join(ci), ", ".join(cd))


def test_support_manifest_migrate_is_placed_for_every_product():
    # act
    mf = manifest.load("product: demo\n", catalogue=catalogue.load())

    # assert
    assert "migrate" in mf.groups["support.manifest"]


@pytest.mark.parametrize("text,new,move", [
    ("product: demo\nimages:\n", "product: demo\nartifacts:\n",
     "images: -> artifacts: (it holds no entry)"),
    ("product: demo\nimages: {}\n", "product: demo\nartifacts: {}\n",
     "images: -> artifacts: (it holds no entry)"),
    ("product: demo\nartifacts:\n  a: { kind: image, local: x }\nimages:\n",
     "product: demo\nartifacts:\n  a: { kind: image, local: x }\n",
     "images: deleted - it holds no entry, and artifacts: already stands"),
    ("product: demo\nartifacts:\n  a: { kind: image, local: x }\nimages: {}\n",
     "product: demo\nartifacts:\n  a: { kind: image, local: x }\n",
     "images: deleted - it holds no entry, and artifacts: already stands"),
])
def test_an_empty_images_that_is_renamed_or_deleted_says_so(text, new, move, tmp_path, capsys):
    # arrange: Task 3 review T3a - the file was written while the run said "(0 change(s))"
    path = tmp_path / "demo.yaml"
    path.write_text(text)

    # act
    rc = migrate_mod.migrate(str(path))

    # assert
    assert rc == 0 and path.read_text() == new
    assert migrate_text(text).moved == (move,)
    out = capsys.readouterr()
    assert move in out.out + out.err
    assert "(1 change(s))" in out.out + out.err


def test_an_image_entry_that_is_neither_a_mapping_nor_a_reference_is_told_what_to_write():
    # act
    result = migrate_text("product: demo\nimages:\n  app: 5\n")

    # assert: Task 3 review T3b - the refusal says what to write instead
    assert result.status == "refused"
    assert result.reason == (
        "images: app holds '5', which is neither a mapping nor an image reference - write a mapping with its "
        "`kind:` (`app: { kind: image, local: \"<reference>\" }`), or the image reference as a quoted string "
        "(`app: \"<reference>\"`), and run again")


def _commands(body: str) -> str:
    return ("product: p\nci:\n  build:\n    commands:\n" + body
            + "artifacts:\n  k: { kind: image, registry: r, repository: k, dockerfile: D, context: . }\n")


def test_a_block_with_holding_only_name_becomes_the_binding_and_keeps_its_comments():
    # arrange
    text = _commands('      image:\n        task: "build:image"\n        with:   # pinned\n'
                     "          name: k   # the kernel\n")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated", result.reason
    assert ('        produces:   # pinned\n          image: k   # the kernel\n') in result.text
    assert "with:" not in result.text


def test_a_block_with_holding_more_keeps_the_rest_under_with():
    # arrange
    text = _commands('      image:\n        task: "build:image"\n        with:\n          name: k\n'
                     "          platform: linux/amd64\n")

    # act
    result = migrate_text(text)

    # assert
    assert ("        produces:\n          image: k\n        with:\n          platform: linux/amd64\n"
            in result.text)


@pytest.mark.parametrize("written,expected", [
    ("with: { name: k }", "produces: { image: k }"),
    ("with: { name: k, platform: linux/arm64 }   # arm",
     "produces: { image: k }\n        with: { platform: linux/arm64 }   # arm"),
])
def test_a_flow_with_becomes_the_binding(written, expected):
    # arrange
    text = _commands(f'      image:\n        task: "build:image"\n        {written}\n')

    # act
    result = migrate_text(text)

    # assert
    assert f"        {expected}\n" in result.text


def test_an_input_port_becomes_consumes():
    # arrange
    text = _commands('      image:\n        task: "release:image"\n        with: { name: k }\n')

    # act / assert
    assert "        consumes: { image: k }\n" in migrate_text(text).text


@pytest.mark.parametrize("command", [
    '      image:\n        task: "build:image"\n        with: &pinned\n          name: k\n',
    '      image: { task: "build:image", with: { name: k } }\n',
    '      gate:\n        task: "test:gate"\n        with: { name: unit }\n',
])
def test_what_the_pass_cannot_rewrite_safely_or_need_not_is_left_as_written(command):
    # arrange: an anchor others may merge, a one-line command, and a task whose `name` is no port
    text = _commands(command)

    # act
    result = migrate_text(text)

    # assert: the loader reads the first two as the same binding (decided 2026-10-14)
    assert (result.status, result.text) == ("current", text)


def test_the_binding_pass_runs_twice_as_current():
    # arrange
    once = migrate_text(_commands('      image:\n        task: "build:image"\n        with: { name: k }\n'))

    # act / assert
    assert migrate_text(once.text).status == "current"


@pytest.mark.parametrize("pinned", ["with: { name: 25 }", "with: { name: yes }",
                                    "with: { name: null, platform: x }", "with:\n          name: 25",
                                    "with:\n          name: [a, b]"])
def test_a_with_name_that_is_not_a_string_is_left_as_written_not_refused(pinned):
    # arrange: the loader reads only a string as the binding, so there is nothing to rewrite (final review)
    text = _commands(f'      image:\n        task: "build:image"\n        {pinned}\n')

    # act
    result = migrate_text(text)

    # assert
    assert (result.status, result.text) == ("current", text), result.reason
