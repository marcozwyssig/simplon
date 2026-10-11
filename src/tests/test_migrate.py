"""The migration (si#344 plan A): text in, text out, and the CLI it assembles unchanged."""
import json
import pathlib
import textwrap

import pytest

from simplon import catalogue
from simplon.orchestrator import manifest
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


def test_groups_declared_twice_is_refused_naming_both_lines():
    # arrange
    text = ("product: demo\n"
            "groups:\n  build:\n    commands:\n      w: { task: wheel }\n"
            "groups:\n  test:\n    commands:\n      t: { task: pytest }\n")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.text == text
    assert result.reason == ("groups: is declared twice at the top level, on lines 2 and 6 - "
                             "merge them by hand first")


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


def test_a_group_written_twice_keeps_both_copies_and_drops_no_line():
    # arrange: cleon's manifest carries `support:` twice; YAML keeps the last, the text keeps both
    text = ("product: demo\n"
            "groups:\n  support:\n    commands:\n      a: { task: doctor }\n"
            "  support:\n    commands:\n      b: { task: doctor }\n")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated"
    assert result.text == ("product: demo\n"
                           "support:\n  commands:\n    a: { task: doctor }\n"
                           "support:\n  commands:\n    b: { task: doctor }\n")


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
    text = (FIXTURES / f"{product}.yaml").read_text()

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated", result.reason
    assert "groups:" not in [line.split("#")[0].strip() for line in result.text.splitlines()
                             if not line.startswith(" ")]


#: What the migrated surface may differ by, and nothing else: si#344 places one new command for every
#: product (`support manifest migrate`), and si#346 a second (`support manifest model`). The goldens are
#: not refreshed (fixtures/manifests/README.md), so each kernel command is named here instead.
NEW_IN_EVERY_PRODUCT = {"support.manifest": ["migrate", "model"]}


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
            "print('simplon.orchestrator.manifest' in sys.modules, 'simplon.context' in sys.modules)")

    # act
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout

    # assert
    assert out.split() == ["False", "False"]


def test_the_migrations_areas_are_the_catalogues():
    # arrange: CI / CD here, and `_phases_of` in the loader's messages, restate which phase groups stand
    # under which area; the catalogue is the statement
    from simplon.orchestrator.model import treeform
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
