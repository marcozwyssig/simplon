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


def test_a_splice_that_does_not_parse_back_is_refused_and_names_where():
    # arrange: a `ci:` written by hand after groups: - YAML keeps the last, so the spliced ci: is shadowed
    text = ("product: demo\n"
            "groups:\n  build:\n    commands:\n      w: { task: wheel }\n"
            "ci: { x: 1 }\n")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "refused"
    assert result.text == text
    assert result.reason == "the spliced text does not parse back to the same manifest: ci.build"


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
    assert result.reason == "the spliced text loses a line the original had: line 3: # nothing yet"


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


def test_support_manifest_migrate_is_placed_for_every_product():
    # act
    mf = manifest.load("product: demo\n", catalogue=catalogue.load())

    # assert
    assert "migrate" in mf.groups["support.manifest"]
