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
from simplon import catalogue as catalogue_mod
from simplon import environments as env_mod
from simplon.orchestrator import manifest


def _load_scaffold(name: str = "fooctl"):
    """The scaffolded manifest, through the loader a real product goes through.

    WITH the catalogue, always: the scaffold hangs its commands off the platform's CI/CD loop and places
    two of the catalogue's own (`release tag`, `support install`), so a load without one is not a
    stricter test - it is a different product. `simplon.context.manifest()` passes the catalogue on every
    real call, and this mirrors it.
    """
    return manifest.load(bootstrap.manifest_yaml(name), catalogue=catalogue_mod.load())


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

#: The block dir a scaffold with no `--orch-dir` writes (si#130). Read off the constant rather than
#: retyped, because every path below hangs off it and the value is stated once, in `bootstrap`.
BLOCK = bootstrap.DEFAULT_ORCH_DIR

#: The generated package's directory under that block - `<block>/src/python/orchestrator`.
PKG = bootstrap.pkg_dir_for(BLOCK)

_EXPECTED_FILES = {
    "fooctl.sh",
    "fooctl.cmd",
    "fooctl.yaml",
    # si#155. The one rendered path a product may already own, so `write` treats it unlike the rest -
    # appended to, never refused and never clobbered. tests/test_init_gitignore.py holds that behaviour
    # and holds the block itself to git's verdict; here it is only part of the file set.
    bootstrap.GITIGNORE,
    f"{BLOCK}/requirements.txt",
    f"{PKG}/__init__.py",
    f"{PKG}/__main__.py",
    f"{PKG}/cli.py",
    f"{PKG}/paths.py",
    f"{PKG}/environments.py",
}


def test_render_produces_the_expected_minimal_file_set():
    # arrange / act
    rendered = bootstrap.render("fooctl")

    # assert: exactly the two launchers (sh + cmd) + manifest + .gitignore + the orchestrator package
    # wiring, nothing more
    assert set(rendered) == _EXPECTED_FILES


def test_generated_manifest_validates_through_the_delivery_loader():
    # arrange
    # act: the SAME loader the product CLI assembles from
    mf = _load_scaffold()

    # assert: ALL FIVE phases of the loop plus support, each holding at least one command (si#33) - the
    # corset a newcomer is meant to see on day one, not two ribs of it. `support git`/`support tasks`
    # come from the catalogue with no line in the scaffold at all.
    assert set(mf.commands) >= {"build", "test", "release", "deploy", "monitor", "support"}
    assert mf.groups["build"] == ("build",)
    assert mf.groups["test"] == ("check",)
    assert mf.groups["release"] == ("tag",)
    assert mf.groups["monitor"] == ("status",)
    assert set(mf.commands["deploy"]) == {"up", "down", "all"}
    assert mf.spec_for("deploy", "all").depends_on == ("build", "up")


def test_generated_manifest_impls_reference_the_scaffolded_orchestrator_package():
    # arrange / act
    mf = _load_scaffold()

    # assert: each leaf impl is a resolvable "module:function" into the generated package (the wiring
    # contract), resolved from the `tasks:` block the command instantiates rather than written on the
    # command; `all` is the impl-less aggregate the kernel binds itself, and `release tag` is the
    # catalogue's own body, which is why its impl points into the KERNEL and not into the product
    assert mf.spec_for("build", "build").impl == "orchestrator.cli:build"
    assert mf.spec_for("test", "check").impl == "orchestrator.cli:check"
    assert mf.spec_for("deploy", "up").impl == "orchestrator.cli:up"
    assert mf.spec_for("deploy", "down").impl == "orchestrator.cli:down"
    assert mf.spec_for("monitor", "status").impl == "orchestrator.cli:status"
    assert mf.spec_for("deploy", "all").impl == ""
    assert mf.spec_for("release", "tag").impl == "simplon.tasks.release:tag"


def test_generated_manifest_taxonomy_matches_the_assembly_semantics():
    # arrange
    mf = _load_scaffold()

    # act
    tax = mf.taxonomy()

    # assert: `build` collapses to one flat command, and the env gate is the CATALOGUE's statement about
    # each group rather than a second list in the scaffold - `deploy` and `monitor` are env-first, the
    # other four refuse an env prefix
    assert tax.is_flat_command_group("build") is True
    assert tax.group_requires_env("deploy") is True
    assert tax.group_requires_env("monitor") is True
    for agnostic in ("build", "test", "release", "support"):
        assert tax.group_requires_env(agnostic) is False


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
    assert 'context.bootstrap("fooctl"' in rendered[f"{PKG}/paths.py"]
    env_src = rendered[f"{PKG}/environments.py"]
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
    req = bootstrap.render("fooctl")[f"{BLOCK}/requirements.txt"]

    # assert: the kernel is a version-pinned ordinary dependency, not a -r include
    assert re.search(r"^simplon==\d+\.\d+\.\d+", req, re.M), req
    assert "-r " not in req, "the kernel is a dependency now, not an include"
    # assert: none of the kernel's OWN deps are re-pinned in the product file - simplon's own pins cover them
    for kernel_pin in ("typer==", "click==", "pydantic==", "textual==", "rich==", "PyYAML=="):
        assert kernel_pin not in req, f"kernel dep {kernel_pin!r} is re-pinned inline instead of via simplon's own deps"


def test_requirements_kernel_pin_matches_the_released_kernel_this_one_descends_from(tmp_path):
    # arrange: a real scaffold on disk
    bootstrap.write("fooctl", tmp_path)
    req_file = tmp_path / BLOCK / "requirements.txt"

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


@pytest.mark.parametrize("version, expected", [
    # THE TAG NAMESPACE IS WIDER THAN `N.N.N`, and the release workflow constrains it no further than
    # `v*`. A parser stricter than the tags this project can legally carry is not caution - it publishes a
    # wheel whose `simplon init` fails for every user of it.
    ("1.0", "1.0"),                             # two components is a legal version and a legal tag
    ("1.0.0.1", "1.0.0.1"),                     # so is four
    ("0.1.12.post1", "0.1.12.post1"),           # a post-release: published, installable, ordinary to tag
    ("0.2.0rc1", "0.2.0rc1"),                   # a pre-release - see the test below for why it is allowed
    ("1.0.post1.dev4+gabc", "1.0"),             # the distance marker peels off a two-component tag too
    ("0.2.0rc1.post1.dev4+gabc", "0.2.0rc1"),   # ...and off a pre-release tag
])
def test_released_pin_accepts_every_shape_a_legal_tag_can_have(version, expected):
    # arrange / act / assert
    assert bootstrap.released_pin(version) == expected


def test_released_pin_allows_a_pre_release_because_an_exact_pin_really_does_install_one():
    """The rejection this test replaces was justified by "`pip install` skips a pre-release without
    --pre", and that is simply not true of an exact pin: `==` is an explicit request, and pre-release
    exclusion does not apply to one. Measured with the resolver's own machinery rather than argued.

    So a kernel installed FROM a release candidate scaffolds a product pinned to that release candidate -
    truthful, installable, and what its user chose. Refusing it would break `simplon init` for exactly the
    people who volunteered to test a release.
    """
    # arrange
    from packaging.specifiers import SpecifierSet

    # act
    pin = bootstrap.released_pin("0.2.0rc1")

    # assert
    assert SpecifierSet(f"=={pin}").contains("0.2.0rc1")


@pytest.mark.parametrize("version", [
    "0.1.13.dev3+g1234abc",     # `guess-next-dev`: names the NEXT version, which nobody has published
    "0.0.0.dev0+unknown",       # simplon neither built nor installed - there is no true answer to give
    "0.0.post1.dev1+g0f8d428",  # setuptools-scm found NO TAG: what a shallow `clone --depth 1` produces
    "0.0",                      # the same sentinel, bare
    "not-a-version",
    "",
])
def test_released_pin_refuses_anything_it_cannot_turn_into_a_released_version(version):
    # arrange / act / assert: loudly, and naming the value - writing a broken pin into somebody else's
    # requirements.txt is a failure they would meet later and elsewhere
    with pytest.raises(ValueError, match="released"):
        bootstrap.released_pin(version)


def test_a_kernel_with_no_derivable_version_fails_the_CLI_loudly_and_leaves_nothing_behind(monkeypatch, tmp_path, capsys):
    """The condition reaching a USER, through the command they actually type.

    `main` promises "fail loud, no traceback" and returns 2. `released_pin`'s ValueError is raised deep
    inside `write` -> `render`, so it has to be caught where the promise is made; uncaught, the first
    command any new user runs answers with a stack trace.

    The other half is that nothing is left behind: `write` renders before its first mkdir, so a refused
    scaffold does not even create the target directory.
    """
    # arrange: a kernel that cannot say what release it descends from - a source tree that was never
    # built and never installed reports exactly this
    monkeypatch.setattr(simplon, "__version__", "0.0.0.dev0+unknown")
    target = tmp_path / "fooctl"

    # act
    code = bootstrap.main(["init", "fooctl", "--dir", str(target)])

    # assert
    assert code == 2
    err = capsys.readouterr().err
    assert "cannot derive a released kernel version" in err
    assert "0.0.0.dev0+unknown" in err
    assert not target.exists(), "a refused scaffold left a directory behind"


def test_the_scaffolded_pin_is_a_plain_release_whatever_this_kernel_calls_itself():
    # arrange / act: the pin as it is actually rendered, from whatever version this checkout produces
    req = bootstrap.render("fooctl")[f"{BLOCK}/requirements.txt"]
    pinned = re.search(r"^simplon==(\S+)", req, re.M).group(1)

    # assert: three final numbers and nothing else - no `.dev`, no `.post`, no local `+...` segment
    assert re.fullmatch(r"\d+\.\d+\.\d+", pinned), (
        f"the scaffolder would pin {pinned!r}, which PyPI cannot resolve")


# --- gap #737-2: the `all` aggregate is reachable (the kernel binds it), not a dead placeholder --------

def test_scaffolded_manifest_declares_no_dead_aggregate():
    # arrange
    mf = _load_scaffold()
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
    res = _run_generated(tmp_path / BLOCK / "src" / "python", [], code=probe)

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
    res = _run_generated(tmp_path / BLOCK / "src" / "python", [], code=probe)

    # assert: each step names its planned leaf's dotted path, so the kernel keeps the tree it was given
    assert res.returncode == 0, res.stderr
    assert "PLAN_TREE_VERIFIED" in res.stdout


# --- gap #737-3: root detection is a marker-walk, robust to relocating the orchestrator dir -----------

def test_root_detection_survives_relocating_the_orchestrator_dir(tmp_path):
    # arrange: scaffold at the SHORT layout, then RELOCATE the orchestrator package deep (as netctl did to
    # deploy/provision/…), leaving the manifest at the repo root - the exact layout change that forced
    # netctl's parents[6] edit. The starting point is passed explicitly since si#130: the deep layout is
    # the default now, so a scaffold with no flag has nowhere left to be relocated TO.
    bootstrap.write("fooctl", tmp_path, orch_dir="orchestrator")
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
    res = _run_generated(tmp_path / BLOCK / "src" / "python", ["help"])

    # assert: help renders and exits clean, so a freshly-scaffolded product's `./<name>.sh help` works
    assert res.returncode == 0, res.stderr
    assert "fooctl orchestrator" in res.stdout
    assert "deploy" in res.stdout
