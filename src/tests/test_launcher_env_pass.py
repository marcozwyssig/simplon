"""A command's `env: pass:` - variables forwarded BY NAME into the kernel's container (si#467), and from there
to that command's `toolchain:run` line only (si#492).

Asked by firn (firn#1041): `release publish-extension` needs `VSCE_PAT`, the name `vsce` reads, and the
container route forwarded a fixed list that did not carry it. Decided by Marco 2026-10-16 (si#467 comment
6224039695): the list is declared in the manifest, rendered into both launchers by `simplon init`, forwarded
by name only, exported back as `DELIVERY_ENV_PASS` so the kernel can refuse a stale launcher, and forwarded
by name on `toolchain:run` lines too. si#492 (Marco, 2026-11-11) moved the list onto the command: the launcher
forwards the UNION of every command's list, and `launcher: env: pass:` is refused by name. That the names
reach only the declaring command's `toolchain:run` line is driven through the CLI in `test_toolchain_cli.py`.

DRIVEN WHERE IT CAN BE: the `.sh` launcher is run against a fake `docker` that records its argv (the harness
of `test_launch_container.py`), so "never a value" is asserted on the line a shell really assembled, not on
the template's text. The `.cmd` is held as text, for the reason that module gives: there is no Windows here.

AAA; the name states the behaviour under test.
"""
import os
import subprocess
import sys

import pytest

from conftest import ROOT
from simplon.cli import bootstrap
from simplon.manifest import launcherenv, load as manifest
from simplon.tasks import toolchain
from test_launch_container import _product, _run

SECRET = "s3cret-value-that-must-not-appear"

def _declare(root, build="", check=""):
    """The scaffold's `build` and `check` commands, each with the `env: pass:` list given (none when empty)."""
    path = root / "democtl.yaml"
    text = path.read_text(encoding="utf-8")
    for command, names in (("build", build), ("check", check)):
        if names:
            anchor = f"{command}: {{ task: {command} }}"
            assert text.count(anchor) == 1, anchor
            text = text.replace(anchor, f"{command}: {{ task: {command}, env: {{ pass: [{names}] }} }}")
    path.write_text(text, encoding="utf-8")


def _declaring(tmp_path):
    """A scaffolded product whose `build` passes VSCE_PAT and whose `check` passes a name nobody sets, so the
    launcher forwards the union of two commands' lists; launchers re-rendered."""
    root = _product(tmp_path)
    _declare(root, build="VSCE_PAT", check="NOT_SET_ANYWHERE")
    assert bootstrap.main(["init", "democtl", "--dir", str(root), "--launchers-only"]) == 0
    return root


def _env_without(*names):
    return {k: v for k, v in os.environ.items() if k not in names}


# --- the launcher: by name, never a value, unset stays unset ------------------------------------------


def test_a_declared_name_crosses_by_name_and_its_value_is_on_no_docker_line(tmp_path):
    # arrange
    root = _declaring(tmp_path)

    # act
    done = _run(root, "support", "doctor", env={"VSCE_PAT": SECRET})

    # assert: every docker line, the install ones included, carries the name and never the value
    assert done.returncode == 0, done.stderr
    assert done.docker
    for line in done.docker:
        assert " -e VSCE_PAT " in f" {line} "
        assert SECRET not in line
    assert SECRET not in done.stdout + done.stderr


def test_a_declared_name_the_host_does_not_set_is_not_forwarded_at_all(tmp_path):
    # arrange
    root = _declaring(tmp_path)

    # act
    done = _run(root, "support", "doctor")

    # assert: no `-e NOT_SET_ANYWHERE`, so the container has no such variable rather than an empty one
    assert done.returncode == 0, done.stderr
    assert not any(" -e NOT_SET_ANYWHERE " in f" {line} " for line in done.docker), done.docker


def test_the_launcher_exports_the_list_it_was_rendered_with(tmp_path):
    # arrange
    root = _declaring(tmp_path)

    # act
    done = _run(root, "support", "doctor", env={"DELIVERY_ENV_PASS": "FORGED"})

    # assert: the names, as rendered; a host value of the variable is not what crosses
    last = done.docker[-1]
    assert "-e DELIVERY_ENV_PASS=VSCE_PAT NOT_SET_ANYWHERE" in last
    assert "FORGED" not in last


def test_without_the_section_the_boundary_is_what_it_was(tmp_path):
    # arrange: the scaffold declares nothing
    root = _product(tmp_path)

    # act
    done = _run(root, "support", "doctor", env={"VSCE_PAT": SECRET})

    # assert: nothing crosses that the fixed list does not name, and the export says "nothing"
    last = done.docker[-1]
    assert "VSCE_PAT" not in last
    assert "-e DELIVERY_ENV_PASS= " in last


def test_launchers_only_renders_the_manifests_list_into_both_launchers(tmp_path):
    # arrange / act
    root = _declaring(tmp_path)

    # assert
    assert 'LAUNCH_ENV_PASS="VSCE_PAT NOT_SET_ANYWHERE"' in (root / "democtl.sh").read_text(encoding="utf-8")
    cmd = (root / "democtl.cmd").read_text(encoding="utf-8")
    assert 'set "LAUNCH_ENV_PASS=VSCE_PAT NOT_SET_ANYWHERE"' in cmd


def test_the_batch_launcher_forwards_the_list_by_name_and_exports_it(tmp_path):
    # arrange
    cmd = bootstrap._render_launcher("democtl", "launch.cmd.j2", "deploy/provision/orchestrator",
                                     ("VSCE_PAT",))

    # assert: through `:forward`, which passes `-e NAME` only for a defined name, and the export
    assert "for %%N in (%LAUNCH_ENV_PASS%) do call :forward %%N" in cmd
    assert 'set "DOCKER_ENV=%DOCKER_ENV% -e %~1"' in cmd
    assert '-e "DELIVERY_ENV_PASS=%LAUNCH_ENV_PASS%"' in cmd
    assert 'if /i "%~1"=="DELIVERY_ENV_PASS" goto :eof' in cmd


def test_a_broken_section_stops_launchers_only_with_the_loaders_sentence(tmp_path, capsys):
    # arrange
    root = _product(tmp_path)
    _declare(root, build="HOME")
    before = (root / "democtl.sh").read_text(encoding="utf-8")

    # act
    rc = bootstrap.main(["init", "democtl", "--dir", str(root), "--launchers-only"])

    # assert
    assert rc == 2
    assert "names HOME, which the launcher sets on the kernel's container itself" in capsys.readouterr().err
    assert (root / "democtl.sh").read_text(encoding="utf-8") == before


# --- the kernel: a stale launcher is red on the container route, and only there ----------------------


def _kernel(root, env):
    """The scaffolded product's CLI, in THIS worktree's kernel, as the launcher's `inside` branch runs it."""
    pythonpath = os.pathsep.join([str(root / "deploy" / "provision" / "orchestrator" / "src" / "python"),
                                  str(ROOT / "src")])
    return subprocess.run([sys.executable, "-m", "orchestrator", "--help"], cwd=root, capture_output=True,
                          text=True, env={**_env_without("DELIVERY_ENV_PASS", "DELIVERY_ROUTE"),
                                          "PYTHONPATH": pythonpath, **env})


def test_a_launcher_rendered_before_the_list_changed_is_refused_on_the_container_route(tmp_path):
    # arrange: the manifest gained a name the launcher was never rendered with
    root = _declaring(tmp_path)

    # act
    done = _kernel(root, {"DELIVERY_ROUTE": "inside", "DELIVERY_ENV_PASS": "VSCE_PAT"})

    # assert
    assert done.returncode != 0
    assert "does not forward NOT_SET_ANYWHERE" in done.stderr
    assert "simplon init --dir . --launchers-only" in done.stderr


def test_a_launcher_from_before_the_section_existed_is_refused_once_the_manifest_declares_one(tmp_path):
    # arrange: an old launcher exports nothing at all
    root = _declaring(tmp_path)

    # act
    done = _kernel(root, {"DELIVERY_ROUTE": "inside"})

    # assert
    assert done.returncode != 0
    assert "does not forward VSCE_PAT, NOT_SET_ANYWHERE" in done.stderr


def test_a_launcher_that_agrees_with_the_manifest_runs(tmp_path):
    # arrange
    root = _declaring(tmp_path)

    # act
    done = _kernel(root, {"DELIVERY_ROUTE": "inside", "DELIVERY_ENV_PASS": "VSCE_PAT NOT_SET_ANYWHERE"})

    # assert
    assert done.returncode == 0, done.stderr


def test_the_venv_route_is_not_compared(tmp_path):
    # arrange: there is no container on the venv route, so no launcher copy to be stale
    root = _declaring(tmp_path)

    # act
    done = _kernel(root, {})

    # assert
    assert done.returncode == 0, done.stderr


def test_an_old_launcher_and_a_manifest_that_declares_nothing_run(tmp_path):
    # arrange: every product in the family today
    root = _product(tmp_path)

    # act
    done = _kernel(root, {"DELIVERY_ROUTE": "inside"})

    # assert
    assert done.returncode == 0, done.stderr


def test_the_stale_sentence_names_a_name_still_forwarded_after_it_left_the_manifest():
    # act
    said = launcherenv.stale_launcher(("A",), {"DELIVERY_ENV_PASS": "A OLD"}, "./x.sh")

    # assert
    assert said is not None
    assert "still forwards OLD" in said


# --- toolchain:run: the same names, by name ----------------------------------------------------------


def test_a_toolchain_line_forwards_each_passed_name_by_name():
    # arrange
    cfg = toolchain.Toolchain(image="alpine:3.20", argv=["true"], env={"MODE": "ci"})

    # act
    line = toolchain.docker_argv(cfg, root=ROOT, product="democtl", instance="", extra=[],
                                 passes=("VSCE_PAT",))

    # assert: `-e VSCE_PAT` as two argv elements, no `VSCE_PAT=` anywhere, before the manifest's own env
    at = line.index("VSCE_PAT")
    assert line[at - 1] == "-e"
    assert not any(arg.startswith("VSCE_PAT=") for arg in line)
    assert at < line.index("MODE=ci")


def test_a_toolchain_line_without_passes_is_unchanged():
    # arrange
    cfg = toolchain.Toolchain(image="alpine:3.20", argv=["true"])

    # act / assert
    assert (toolchain.docker_argv(cfg, root=ROOT, product="democtl", instance="", extra=[])
            == toolchain.docker_argv(cfg, root=ROOT, product="democtl", instance="", extra=[], passes=()))


# --- the loader: what a command's `env:` may say ---------------------------------------------------------

_BASE = """\
product: democtl
tasks:
  x: { impl: "m:f", help: x }
ci:
  build:
    commands:
      x: { task: x{env} }
      y: { task: x }
      both: { help: both, depends_on: [x, y]{aggregate_env} }
"""


def _doc(env="", aggregate_env=""):
    return _BASE.replace("{env}", env).replace("{aggregate_env}", aggregate_env)


@pytest.mark.parametrize(("env", "said"), [
    (", env: [VSCE_PAT]", "command 'build x': `env:` must be a mapping"),
    (", env: { pas: [VSCE_PAT] }", "command 'build x': `env:` does not take pas"),
    (", env: { pass: VSCE_PAT }", "command 'build x': `env: pass:` must be a list of variable names"),
    (", env: { pass: [VSCE-PAT] }", "names 'VSCE-PAT', which is not an environment variable name"),
    (", env: { pass: [PYTHONPATH] }", "names PYTHONPATH, which the launcher sets"),
    (", env: { pass: [LAUNCH_ANYTHING] }", "names LAUNCH_ANYTHING, which the launcher sets"),
    (", env: { pass: [DELIVERY_ROUTE] }", "names DELIVERY_ROUTE, which the launcher sets"),
])
def test_the_loader_refuses_an_env_that_would_forward_nothing_or_break_the_container(env, said):
    # act / assert
    with pytest.raises(ValueError, match=None) as caught:
        manifest.load(_doc(env=env))
    assert said in str(caught.value)


def test_the_retired_launcher_section_is_refused_with_the_way_out():
    # act / assert: si#492 - one form, not two (#33); the old one fails loudly rather than forwarding
    with pytest.raises(ValueError) as caught:
        manifest.load(_doc() + "launcher:\n  env:\n    pass: [VSCE_PAT]\n")
    said = str(caught.value)
    assert "the 'launcher' section is gone (si#492)" in said
    assert "`env: { pass: [NAME, ...] }` on each command" in said


def test_the_launchers_list_is_the_union_of_the_task_commands_lists(tmp_path):
    # arrange: two commands, one name shared
    import yaml
    doc = yaml.safe_load(_doc(env=", env: { pass: [VSCE_PAT, SHARED] }").replace(
        "y: { task: x }", "y: { task: x, env: { pass: [SHARED, OTHER] } }"))

    # act / assert: in the order written, each name once
    assert launcherenv.declared(doc) == ("VSCE_PAT", "SHARED", "OTHER")


def test_each_member_of_an_aggregate_keeps_its_own_list():
    # arrange: si#492 Q3 C - members x (VSCE_PAT) and y (none) under one aggregate
    text = _doc(env=", env: { pass: [VSCE_PAT] }")

    # act
    loaded = manifest.load(text)

    # assert: no member gains a sibling's names, and the aggregate carries none
    build = loaded.commands["build"]
    assert build["x"].env_pass == ("VSCE_PAT",)
    assert build["y"].env_pass == ()
    assert not hasattr(build["both"], "env_pass")


def test_the_launchers_union_leaves_an_aggregates_env_out():
    # arrange: the raw union is read before any load (`simplon init --launchers-only`), so it must not count
    # what the loader refuses below
    import yaml
    text = _doc(env=", env: { pass: [VSCE_PAT] }", aggregate_env=", env: { pass: [AGGREGATE_ONLY] }")

    # act / assert
    assert launcherenv.declared(yaml.safe_load(text)) == ("VSCE_PAT",)


def test_an_env_on_an_aggregate_is_refused_and_points_at_the_members():
    # arrange: si#492, decided by Marco 2026-11-11 - an aggregate runs no `toolchain:run` line, so the names
    # would reach nothing; diagnosis
    text = _doc(aggregate_env=", env: { pass: [VSCE_PAT] }")

    # act / assert
    with pytest.raises(ValueError) as caught:
        manifest.load(text)
    said = str(caught.value)
    assert "aggregate 'build both' declares `env:`" in said
    assert "on the member commands" in said


def test_names_the_launcher_already_forwards_are_accepted_quietly():
    # act
    names = launcherenv.of_command({"pass": ["GH_TOKEN", "DEMOCTL_X", "DELIVERY_OTHER"]}, "build x")

    # assert
    assert names == ("GH_TOKEN", "DEMOCTL_X", "DELIVERY_OTHER")


def test_the_refused_names_are_read_off_the_launchers_and_not_typed_here():
    # assert: every `-e NAME=` the container line writes, in both templates
    sets = launcherenv.launcher_sets()
    for name in ("DELIVERY_ROUTE", "DELIVERY_HOST_ROOT", "DELIVERY_MOUNT_ROOT", "DELIVERY_ENV_PASS",
                 "PYTHONPATH", "PYTHONUSERBASE", "HOME", "LAUNCH_PRODUCT", "LAUNCH_IMAGE_PIN"):
        assert name in sets
