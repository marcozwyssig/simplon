"""`launcher: env: pass:` - a declared list of variables forwarded BY NAME into the kernel's container (si#467).

Asked by firn (firn#1041): `release publish-extension` needs `VSCE_PAT`, the name `vsce` reads, and the
container route forwarded a fixed list that did not carry it. Decided by Marco 2026-10-16 (si#467 comment
6224039695): the list is declared in the manifest, rendered into both launchers by `simplon init`, forwarded
by name only, exported back as `DELIVERY_ENV_PASS` so the kernel can refuse a stale launcher, and forwarded
by name on `toolchain:run` lines too.

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

_DECLARES = "launcher:\n  env:\n    pass: [VSCE_PAT, NOT_SET_ANYWHERE]\n"


def _declaring(tmp_path):
    """A scaffolded product whose manifest passes VSCE_PAT and a name nobody sets, launchers re-rendered."""
    root = _product(tmp_path)
    path = root / "democtl.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "\n" + _DECLARES, encoding="utf-8")
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
    path = root / "democtl.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "\nlauncher:\n  env:\n    pass: [HOME]\n",
                    encoding="utf-8")
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


# --- the loader: what the section may say -------------------------------------------------------------

_BASE = "product: democtl\nci:\n  build:\n    commands:\n      x: { impl: 'm:f', help: x }\n"


@pytest.mark.parametrize(("section", "said"), [
    ("launcher: [VSCE_PAT]", "the 'launcher' section must be a mapping"),
    ("launcher: { envs: {} }", "the 'launcher' section does not take envs"),
    ("launcher: { env: [VSCE_PAT] }", "'launcher: env' must be a mapping"),
    ("launcher: { env: { pas: [VSCE_PAT] } }", "'launcher: env' does not take pas"),
    ("launcher: { env: { pass: VSCE_PAT } }", "'launcher: env: pass' must be a list of variable names"),
    ("launcher: { env: { pass: [VSCE-PAT] } }", "names 'VSCE-PAT', which is not an environment variable name"),
    ("launcher: { env: { pass: [PYTHONPATH] } }", "names PYTHONPATH, which the launcher sets"),
    ("launcher: { env: { pass: [LAUNCH_ANYTHING] } }", "names LAUNCH_ANYTHING, which the launcher sets"),
    ("launcher: { env: { pass: [DELIVERY_ROUTE] } }", "names DELIVERY_ROUTE, which the launcher sets"),
])
def test_the_loader_refuses_a_section_that_would_forward_nothing_or_break_the_container(section, said):
    # act / assert
    with pytest.raises(ValueError, match=None) as caught:
        manifest.load(_BASE + section + "\n")
    assert said in str(caught.value)


def test_names_the_launcher_already_forwards_are_accepted_quietly():
    # act
    names = launcherenv.declared({"launcher": {"env": {"pass": ["GH_TOKEN", "DEMOCTL_X", "DELIVERY_OTHER"]}}})

    # assert
    assert names == ("GH_TOKEN", "DEMOCTL_X", "DELIVERY_OTHER")


def test_the_refused_names_are_read_off_the_launchers_and_not_typed_here():
    # assert: every `-e NAME=` the container line writes, in both templates
    sets = launcherenv.launcher_sets()
    for name in ("DELIVERY_ROUTE", "DELIVERY_HOST_ROOT", "DELIVERY_MOUNT_ROOT", "DELIVERY_ENV_PASS",
                 "PYTHONPATH", "PYTHONUSERBASE", "HOME", "LAUNCH_PRODUCT", "LAUNCH_IMAGE_PIN"):
        assert name in sets
