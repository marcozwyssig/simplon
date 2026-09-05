"""Unit tests for the product scaffolder (simplon.bootstrap, netctl#651 strand 4): the PURE render (the
generated starter manifest validates through the real delivery loader, the file set + placeholder
substitution are exact) and the file-writing (every file lands, the shim is executable, an existing tree is
not clobbered). No Typer, no product deps; AAA throughout, incl. negative cases.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import simplon
from simplon import bootstrap
from simplon import environments as env_mod
from simplon.orchestrator import manifest


def _kernel_src() -> Path:
    """The kernel's python source dir (…/src), the parent of the `simplon` package - so a subprocess can
    import the kernel exactly as the product shim's PYTHONPATH does."""
    return Path(simplon.__file__).resolve().parents[1]


def _run_generated(pkg_src: Path, argv: list[str], *, code: str | None = None) -> subprocess.CompletedProcess:
    """Run the SCAFFOLDED product package in a SUBPROCESS - so its import-time context.set_current() +
    marker-walk never leak into the test process - with the kernel + the generated package on PYTHONPATH,
    the exact seam `<product>.sh` sets. PYTHONSAFEPATH keeps CWD off sys.path (no namespace-package
    shadowing). `code` runs `python -c code`; else `python -m orchestrator <argv>`."""
    env = dict(os.environ, PYTHONSAFEPATH="1",
               PYTHONPATH=os.pathsep.join([str(_kernel_src()), str(pkg_src)]))
    args = ([sys.executable, "-c", code] if code is not None
            else [sys.executable, "-m", "orchestrator", *argv])
    return subprocess.run(args, env=env, capture_output=True, text=True)

_EXPECTED_FILES = {
    "fooctl.sh",
    "fooctl.cmd",
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

    # assert: exactly the two launchers (sh + cmd) + manifest + the orchestrator package wiring, nothing more
    assert set(rendered) == _EXPECTED_FILES


def test_generated_manifest_validates_through_the_delivery_loader():
    # arrange
    text = bootstrap.manifest_yaml("fooctl")

    # act: the SAME loader the product CLI assembles from
    mf = manifest.load(text)

    # assert: the starter taxonomy - an agnostic group, and an env-first CD group whose `all` member is the
    # impl-less aggregate over build -> up
    assert mf.groups == {"build": ("build",), "deploy": ("up", "down", "all")}
    assert mf.env_groups == frozenset({"deploy"})
    assert set(mf.commands) == {"build", "deploy"}
    assert set(mf.commands["deploy"]) == {"up", "down", "all"}
    assert mf.spec_for("deploy", "all").depends_on == ("build", "up")


def test_generated_manifest_impls_reference_the_scaffolded_orchestrator_package():
    # arrange / act
    mf = manifest.load(bootstrap.manifest_yaml("fooctl"))

    # assert: each leaf impl is a resolvable "module:function" into the generated package (the wiring
    # contract); `all` is the impl-less aggregate the kernel binds itself
    assert mf.spec_for("build", "build").impl == "orchestrator.cli:build"
    assert mf.spec_for("deploy", "up").impl == "orchestrator.cli:up"
    assert mf.spec_for("deploy", "down").impl == "orchestrator.cli:down"
    assert mf.spec_for("deploy", "all").impl == ""


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
    assert 'context.bootstrap("fooctl"' in rendered["orchestrator/src/python/orchestrator/paths.py"]
    env_src = rendered["orchestrator/src/python/orchestrator/environments.py"]
    assert 'ENV_VAR = "FOOCTL_ENV"' in env_src
    assert 'shim="./fooctl.sh"' in env_src


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

    # assert: the sh launcher is executable, the cmd launcher and a plain file (the manifest) are not
    assert (tmp_path / "fooctl.sh").stat().st_mode & 0o111
    assert not (tmp_path / "fooctl.cmd").stat().st_mode & 0o111
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


def test_next_steps_names_the_product_and_the_target_but_no_submodule(tmp_path):
    # arrange / act
    steps = bootstrap.next_steps("fooctl", tmp_path)

    # assert: it points at the CLI and the manifest
    assert "./fooctl.sh help" in steps
    assert "fooctl.yaml" in steps
    assert str(tmp_path) in steps

    # assert: nothing tells the user to vendor a kernel - there is nothing left to vendor
    assert "lib/platform" not in steps
    assert "submodule" not in steps


# --- the kernel is a pinned PyPI dependency now, not a -r include into a vendored submodule ------------

def test_requirements_pin_the_kernel_by_version_and_do_not_repin_its_deps():
    # arrange / act
    req = bootstrap.render("fooctl")["orchestrator/requirements.txt"]

    # assert: the kernel is a version-pinned ordinary dependency, not a -r include
    assert re.search(r"^simplon==\d+\.\d+\.\d+", req, re.M), req
    assert "-r " not in req, "the kernel is a dependency now, not an include"
    # assert: none of the kernel's OWN deps are re-pinned in the product file - simplon's own pins cover them
    for kernel_pin in ("typer==", "click==", "pydantic==", "textual==", "rich==", "PyYAML=="):
        assert kernel_pin not in req, f"kernel dep {kernel_pin!r} is re-pinned inline instead of via simplon's own deps"


def test_requirements_kernel_pin_matches_the_released_kernel_this_one_descends_from(tmp_path):
    # arrange: a real scaffold on disk
    bootstrap.write("fooctl", tmp_path)
    req_file = tmp_path / "orchestrator" / "requirements.txt"

    # act: pull the pinned version out of the written file
    text = req_file.read_text(encoding="utf-8")
    pinned = re.search(r"^simplon==(\S+)", text, re.M).group(1)

    # assert: the scaffolder pins the kernel it ships with, REDUCED to a released version - identical to
    # __version__ when this kernel was built from a tag, and the release it descends from otherwise. A
    # fresh product's first `pip install -r requirements.txt` must land on a kernel that is on PyPI.
    assert pinned == bootstrap.released_pin(simplon.__version__)


# --- the pin must name a version PyPI HAS, which is not always the version this kernel IS (#3) ---------
#
# With the version coming from the tag, a kernel built from an untagged tree calls itself
# `0.1.12.post1.dev3+g1234abc`. That is the right answer for the kernel and poison for the pin:
# `pip install simplon==0.1.12.post1.dev3+g1234abc` finds nothing on PyPI, so a product scaffolded from a
# developer's checkout would arrive un-installable. `released_pin` is the one place that reduction is
# decided, and it refuses rather than guesses when it cannot make a released version out of what it has.


def test_released_pin_passes_a_release_version_through_unchanged():
    # arrange / act / assert: a kernel built from a tag IS a release; the pin is the version, as before
    assert bootstrap.released_pin("0.1.12") == "0.1.12"


def test_released_pin_reduces_a_dev_build_to_the_release_it_descends_from():
    # arrange: what `no-guess-dev` renders three commits after v0.1.12, with and without the local part
    # (the local part carries the node, and a `.dYYYYMMDD` suffix when the working tree is dirty)
    # act / assert: the answer is the last version that actually shipped, never the next one
    assert bootstrap.released_pin("0.1.12.post1.dev3") == "0.1.12"
    assert bootstrap.released_pin("0.1.12.post1.dev3+g1234abc") == "0.1.12"
    assert bootstrap.released_pin("0.1.12.post1.dev3+g1234abc.d20260905") == "0.1.12"


@pytest.mark.parametrize("version", [
    "0.1.13.dev3+g1234abc",   # `guess-next-dev`: names the NEXT version, which nobody has published
    "0.0.0.dev0+unknown",     # simplon neither built nor installed - there is no true answer to give
    "0.2.0rc1",               # a pre-release: on PyPI, but `pip install` skips it without --pre
    "",
])
def test_released_pin_refuses_anything_it_cannot_turn_into_a_released_version(version):
    # arrange / act / assert: loudly, and naming the value - writing a broken pin into somebody else's
    # requirements.txt is a failure they would meet later and elsewhere
    with pytest.raises(ValueError, match="released"):
        bootstrap.released_pin(version)


def test_the_scaffolded_pin_is_a_plain_release_whatever_this_kernel_calls_itself():
    # arrange / act: the pin as it is actually rendered, from whatever version this checkout produces
    req = bootstrap.render("fooctl")["orchestrator/requirements.txt"]
    pinned = re.search(r"^simplon==(\S+)", req, re.M).group(1)

    # assert: three final numbers and nothing else - no `.dev`, no `.post`, no local `+...` segment
    assert re.fullmatch(r"\d+\.\d+\.\d+", pinned), (
        f"the scaffolder would pin {pinned!r}, which PyPI cannot resolve")


# --- gap #737-2: the `all` aggregate is reachable (the kernel binds it), not a dead placeholder --------

def test_scaffolded_manifest_declares_no_dead_aggregate():
    # arrange
    mf = manifest.load(bootstrap.manifest_yaml("fooctl"))
    aggregates = {name: spec for members in mf.commands.values()
                  for name, spec in members.items() if spec.depends_on}

    # assert: the starter declares a live aggregate and its plan expands to real leaves
    assert aggregates, "starter should exercise the aggregate feature"
    for name in aggregates:
        plan = mf.plan_for(name)
        assert plan, f"aggregate '{name}' plans no leaves (dead placeholder)"


def test_scaffolded_aggregate_actually_runs_through_the_shared_runner(tmp_path):
    # arrange: a real scaffold; drive its `all` command with the runner's dispatch patched to a recorder,
    # so we observe the aggregate really being planned + dispatched (behavioural, not just declared)
    bootstrap.write("fooctl", tmp_path)
    probe = (
        "from simplon.orchestrator import product\n"
        "seen = {}\n"
        "def _record(pipeline):\n"
        "    seen['name'] = pipeline.name\n"
        "    seen['labels'] = [s.label for s in pipeline.steps]\n"
        "    return 0\n"
        "product.dispatch = _record\n"           # run_command calls the module-level dispatch
        "from typer.testing import CliRunner\n"
        "from orchestrator import cli\n"         # import assembles the app (step_context binds `all`)
        "result = CliRunner().invoke(cli.app, ['all'])\n"
        "assert result.exit_code == 0, result.output\n"
        "assert seen['name'] == 'all', seen\n"
        "assert seen['labels'] == ['build', 'up'], seen\n"
        "print('AGGREGATE_REACHABLE')\n"
    )

    # act
    res = _run_generated(tmp_path / "orchestrator" / "src" / "python", [], code=probe)

    # assert: the `all` command ran its dependency plan through run_command (leaves build -> up)
    assert res.returncode == 0, res.stderr
    assert "AGGREGATE_REACHABLE" in res.stdout


# --- #42: the scaffolded step factory stamps each step's exact-command identity -----------------------

def test_scaffolded_aggregate_keeps_the_plan_tree_and_with_it_every_stop_scope(tmp_path):
    """The scaffolded factory must stamp `command=` on every step it builds. Without it the kernel cannot
    verify the leaf-to-step pairing, drops the WHOLE plan tree, and with it every subtree's
    `stop_on_failure` - so a scaffolded product's `lint -> check-contract -> test` chain kept running
    after a failure, its manifest's declaration silently void behind one warning in the log (#42).
    Asserting the tree SURVIVED is the point; the stamped identities are how it can."""
    # arrange: a real scaffold, driven through its `all` aggregate with dispatch patched to a recorder, so
    # the verdict is read off the Pipeline the kernel really built
    bootstrap.write("fooctl", tmp_path)
    probe = (
        "from simplon.orchestrator import product\n"
        "seen = {}\n"
        "def _record(pipeline):\n"
        "    seen['commands'] = [s.command for s in pipeline.steps]\n"
        "    seen['usable'] = pipeline.usable_tree() is not None\n"
        "    return 0\n"
        "product.dispatch = _record\n"           # run_command calls the module-level dispatch
        "from typer.testing import CliRunner\n"
        "from orchestrator import cli\n"         # import assembles the app (step_context binds `all`)
        "result = CliRunner().invoke(cli.app, ['all'])\n"
        "assert result.exit_code == 0, result.output\n"
        "assert seen['commands'] == ['build.build', 'deploy.up'], seen\n"
        "assert seen['usable'], seen\n"
        "print('PLAN_TREE_VERIFIED')\n"
    )

    # act
    res = _run_generated(tmp_path / "orchestrator" / "src" / "python", [], code=probe)

    # assert: each step names its planned leaf's dotted path, so the kernel keeps the tree it was given
    assert res.returncode == 0, res.stderr
    assert "PLAN_TREE_VERIFIED" in res.stdout


# --- gap #737-3: root detection is a marker-walk, robust to relocating the orchestrator dir -----------

def test_root_detection_survives_relocating_the_orchestrator_dir(tmp_path):
    # arrange: scaffold, then RELOCATE the orchestrator package deep (as netctl did to deploy/provision/…),
    # leaving the manifest at the repo root - the exact layout change that forced netctl's parents[6] edit
    bootstrap.write("fooctl", tmp_path)
    relocated = tmp_path / "deploy" / "provision" / "orchestrator"
    relocated.parent.mkdir(parents=True)
    (tmp_path / "orchestrator").rename(relocated)

    # act: import paths from the relocated tree and read the derived ROOT
    res = _run_generated(relocated / "src" / "python", [],
                         code="import orchestrator.paths as p; print(p.ROOT)")

    # assert: the walk-up-to-manifest-marker still finds the true repo root - no hand-edited parent depth
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == str(tmp_path)


# --- gap #737 end-to-end: the assembled CLI boots + `help` runs (#740's verify step) ------------------

def test_generated_cli_help_runs_end_to_end(tmp_path):
    # arrange
    bootstrap.write("fooctl", tmp_path)

    # act: boot the assembled CLI headless - this resolves every manifest impl and binds the `all`
    # aggregate at assembly
    res = _run_generated(tmp_path / "orchestrator" / "src" / "python", ["help"])

    # assert: help renders and exits clean, so a freshly-scaffolded product's `./<name>.sh help` works
    assert res.returncode == 0, res.stderr
    assert "fooctl orchestrator" in res.stdout
    assert "deploy" in res.stdout
