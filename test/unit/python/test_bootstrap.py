"""Unit tests for the product scaffolder (delivery.bootstrap, netctl#651 strand 4): the PURE render (the
generated starter manifest validates through the real delivery loader, the file set + placeholder
substitution are exact) and the file-writing (every file lands, the shim is executable, an existing tree is
not clobbered). No Typer, no product deps; AAA throughout, incl. negative cases.
"""
import pytest

from delivery import bootstrap
from delivery import environments as env_mod
from delivery.orchestrator import manifest

_EXPECTED_FILES = {
    "fooctl.sh",
    "fooctl.yaml",
    "orchestrator/requirements.txt",
    "orchestrator/src/python/orchestrator/__init__.py",
    "orchestrator/src/python/orchestrator/__main__.py",
    "orchestrator/src/python/orchestrator/cli.py",
    "orchestrator/src/python/orchestrator/paths.py",
    "orchestrator/src/python/orchestrator/environments.py",
}


def test_render_produces_the_expected_minimal_file_set():
    # arrange / act
    rendered = bootstrap.render("fooctl")

    # assert: exactly the shim + manifest + the orchestrator package wiring, nothing more
    assert set(rendered) == _EXPECTED_FILES


def test_generated_manifest_validates_through_the_delivery_loader():
    # arrange
    text = bootstrap.manifest_yaml("fooctl")

    # act: the SAME loader the product CLI assembles from
    mf = manifest.load(text)

    # assert: the starter taxonomy - an agnostic group, an env-first CD group, a composite
    assert mf.groups == {"build": ("build",), "deploy": ("up", "down")}
    assert mf.env_groups == frozenset({"deploy"})
    assert set(mf.commands) == {"build", "deploy"}
    assert set(mf.commands["deploy"]) == {"up", "down"}
    assert mf.composites["all"].steps == ("build", "up")


def test_generated_manifest_impls_reference_the_scaffolded_orchestrator_package():
    # arrange / act
    mf = manifest.load(bootstrap.manifest_yaml("fooctl"))

    # assert: each impl is a resolvable "module:function" into the generated package (the wiring contract)
    assert mf.spec_for("build", "build").impl == "orchestrator.cli:build"
    assert mf.spec_for("deploy", "up").impl == "orchestrator.cli:up"
    assert mf.spec_for("deploy", "down").impl == "orchestrator.cli:down"


def test_generated_manifest_taxonomy_matches_the_assembly_semantics():
    # arrange
    mf = manifest.load(bootstrap.manifest_yaml("fooctl"))

    # act
    tax = mf.taxonomy()

    # assert: `build` collapses to one flat command, `deploy` is the env-first sub-app (what assemble reads)
    assert tax.is_flat_command_group("build") is True
    assert tax.group_requires_env("deploy") is True
    assert tax.group_requires_env("build") is False


def test_generated_env_matrix_parses_with_the_local_backend():
    # arrange
    text = bootstrap.manifest_yaml("fooctl")

    # act: the env provider parses the manifest's environments/default sections
    registry = env_mod.parse(text, ("local",))

    # assert: a single local `dev` environment, and it is the default
    assert registry.default == "dev"
    assert registry.environments["dev"].backend == "local"


def test_render_substitutes_the_product_into_the_shim_and_the_wiring():
    # arrange / act
    rendered = bootstrap.render("fooctl")

    # assert: the product name is threaded through the shim params and the ProductContext wiring
    assert "LAUNCH_PRODUCT=fooctl" in rendered["fooctl.sh"]
    assert 'ProductContext.resolve("fooctl"' in rendered["orchestrator/src/python/orchestrator/paths.py"]
    env_src = rendered["orchestrator/src/python/orchestrator/environments.py"]
    assert 'ENV_VAR = "FOOCTL_ENV"' in env_src


def test_no_placeholder_tokens_survive_the_render():
    # arrange / act
    rendered = bootstrap.render("fooctl")

    # assert: every sentinel was substituted in every file (a missed placeholder is a template bug)
    for rel, content in rendered.items():
        assert "@@PRODUCT@@" not in content, rel
        assert "@@ENV_VAR@@" not in content, rel


def test_write_creates_every_file_and_marks_only_the_shim_executable(tmp_path):
    # arrange / act
    written = bootstrap.write("fooctl", tmp_path)

    # assert: every expected file landed on disk
    on_disk = {p.relative_to(tmp_path).as_posix() for p in written}
    assert on_disk == _EXPECTED_FILES
    assert all(p.exists() for p in written)

    # assert: the shim is executable, a plain file (the manifest) is not
    assert (tmp_path / "fooctl.sh").stat().st_mode & 0o111
    assert not (tmp_path / "fooctl.yaml").stat().st_mode & 0o111


def test_write_refuses_to_clobber_an_existing_tree_without_force(tmp_path):
    # arrange: a first scaffold, then a hand edit
    bootstrap.write("fooctl", tmp_path)
    (tmp_path / "fooctl.yaml").write_text("# hand-edited, do not lose\n", encoding="utf-8")

    # act / assert: a second write refuses loudly rather than overwriting
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        bootstrap.write("fooctl", tmp_path)
    assert (tmp_path / "fooctl.yaml").read_text(encoding="utf-8") == "# hand-edited, do not lose\n"


def test_write_force_overwrites_an_existing_tree(tmp_path):
    # arrange
    bootstrap.write("fooctl", tmp_path)
    (tmp_path / "fooctl.yaml").write_text("# stale\n", encoding="utf-8")

    # act: force re-renders every file
    bootstrap.write("fooctl", tmp_path, force=True)

    # assert: the manifest is back to the rendered starter
    assert "product: fooctl" in (tmp_path / "fooctl.yaml").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad", ["Fooctl", "1ctl", "foo_ctl", "foo ctl", "", "-foo", "foo/ctl"])
def test_validate_product_name_rejects_illegal_slugs(bad):
    # act / assert: a non-slug fails loudly, never a broken filename downstream
    with pytest.raises(ValueError, match="is invalid"):
        bootstrap.validate_product_name(bad)


@pytest.mark.parametrize("good", ["fooctl", "foo-ctl", "netctl", "a", "x9"])
def test_validate_product_name_accepts_lowercase_slugs(good):
    # act / assert: trimmed and returned unchanged
    assert bootstrap.validate_product_name(f"  {good}  ") == good


@pytest.mark.parametrize(("name", "expected"), [
    ("netctl", "NETCTL_ENV"),
    ("foo-ctl", "FOO_CTL_ENV"),
    ("x9", "X9_ENV"),
])
def test_env_var_name_derives_the_active_env_variable(name, expected):
    # act / assert
    assert bootstrap.env_var_name(name) == expected


def test_next_steps_names_the_product_the_target_and_the_submodule(tmp_path):
    # arrange / act
    steps = bootstrap.next_steps("fooctl", tmp_path)

    # assert: it points at the CLI, the manifest and the lib/platform vendoring the new product needs
    assert "./fooctl.sh help" in steps
    assert "fooctl.yaml" in steps
    assert "lib/platform" in steps
