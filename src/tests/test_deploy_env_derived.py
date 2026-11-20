"""si#810: `deploy:up` and `deploy:down` get the names their environment and carrier declare, on the container route.

Measured 2026-11-20 with a rendered launcher, a docker shim and the real kernel image: a command bound to
`deploy:up` with `backend: portainer` saw `<url_from>_URL`/`_TOKEN` only when some command repeated them
under `env: pass:`, and since si#757 only when the deploy command itself did. Decided by Marco the same
day: the kernel derives the names from the manifest - per environment, what the Portainer adapter reads off
the carrier's `url_from:`, the repository's `credential_from:` pair and `required:` + `optional:` - into the
launcher's list and into the deploy command's keep-list, and into nothing else's.

DRIVEN WHERE IT CAN BE: the `.sh` launcher runs against the fake `docker` of `test_launch_container.py`, so
"forwarded" is asserted on the line a shell really assembled; the keep-list through `simplon.cli.assemble`
and Typer's runner, as `test_toolchain_cli.py` drives si#757.

AAA; the name states the behaviour under test.
"""
import os

import pytest
import typer
import yaml
from typer.testing import CliRunner

from simplon import cli
from simplon.adapters import credentials, portainer
from simplon.cli import bootstrap
from simplon.manifest import context, launcherenv
from simplon.model import carrierspec
from simplon.tasks import deploy, deploy_down, deploy_up, taskgen
from test_launch_container import _product, _run

SECRET = "s3cret-810"

# The carrier and the environment of the measurement: biz-cockpit's shape, with a prefix of its own so a
# name can only have come from the derivation.
_CARRIER = """\
carriers:
  haus:
    proxmox: { node: pve, kind: lxc }
    portainer: { url_from: HAUS }
"""

_PROD = """\
    prod:
      backend: portainer
      carrier: haus
      stack: demo
      repository: { url: "https://github.com/acme/demo", credential_from: GIT }
      required: [HTTP_BIND]
      optional: [APP_TITLE]
"""

#: Every name a deploy of `prod` reads, in the readers' order: target, registry, clone credential, values.
UP = ("HAUS_URL", "HAUS_TOKEN", "HAUS_GHCR_USER", "HAUS_GHCR_PASSWORD", "GIT_USER", "GIT_PASSWORD",
      "HTTP_BIND", "APP_TITLE")
#: A destroy only finds the stack.
DOWN = ("HAUS_URL", "HAUS_TOKEN")


def _document(commands: str = "", environments: str = _PROD, carriers: str = _CARRIER) -> dict:
    return yaml.safe_load(f"""\
product: demo
tasks:
  smoke: {{ impl: "test_deploy_env_derived:smoke", help: "Look." }}
ci:
  build:
    commands:
      smoke: {{ task: smoke }}
cd:
  default: dev
  environments:
    dev: {{ backend: local }}
{environments}
  deploy:
    commands:
      rollout: {{ task: "deploy:up" }}
      teardown: {{ task: "deploy:down" }}
{commands}
{carriers}""")


# --- the derivation: the readers' own names, per task -------------------------------------------------


def test_the_coordinates_are_read_off_the_catalogues_body_table():
    # assert: the generated task classes are bound to exactly these two, and up deploys while down destroys
    assert deploy.READS == {deploy_up.DeployUp.KEY: True, deploy_down.DeployDown.KEY: False}


def test_a_deploy_reads_the_carriers_names_the_clone_credential_and_the_stack_values():
    # act
    names = deploy.variables_read(_document(), "deploy:up")

    # assert
    assert names == UP


def test_a_destroy_reads_only_the_target():
    # act / assert
    assert deploy.variables_read(_document(), "deploy:down") == DOWN


def test_the_names_are_the_readers_own_spelling():
    """A reader that gains a suffix gains it in the derivation by the same edit (si#783's `_GHCR` did)."""
    # arrange
    carrier = carrierspec.declared(_document())["haus"]

    # act
    target = portainer.PortainerTarget.from_carrier(carrier, "demo", environ={"HAUS_URL": "u", "HAUS_TOKEN": "t"})

    # assert: what from_carrier read and what it hands `_ensure_registry` are what the derivation names
    assert (target.url, target.token) == ("u", "t")
    assert portainer.target_variables("HAUS") == UP[:2]
    assert credentials.variables(target.registry_from) == UP[2:4]


@pytest.mark.parametrize("task", ["toolchain:run", "deploy:carrier", "up", ""])
def test_any_other_task_derives_nothing(task):
    # act / assert
    assert deploy.variables_read(_document(), task) == ()


def test_an_environment_another_backend_drives_derives_nothing():
    # arrange: the kernel does not know what a backend it does not ship reads
    document = _document(environments=_PROD.replace("backend: portainer", "backend: theirs"))

    # act / assert
    assert deploy.variables_read(document, "deploy:up") == ()


def test_a_manifest_without_environments_derives_nothing():
    # arrange: a client install deploys into a directory and declares no matrix
    document = _document()
    del document["cd"]["environments"], document["cd"]["default"]

    # act / assert
    assert deploy.variables_read(document, "deploy:up") == ()


# --- the launcher's list: the union, and only for a manifest that binds the tasks ----------------------


def test_the_launchers_list_carries_the_derived_names():
    # arrange
    document = _document()

    # act
    names = launcherenv.declared(document, derive=lambda task: deploy.variables_read(document, task))

    # assert: each once, the destroy's names already in the deploy's
    assert names == UP


def test_a_manifest_that_binds_no_deploy_task_derives_nothing_for_its_launcher():
    # arrange: the same carrier and environment, and no command bound to deploy:up or deploy:down
    document = _document()
    document["cd"]["deploy"]["commands"] = {"status": {"task": "toolchain:run"}}

    # act / assert
    assert launcherenv.declared(document, derive=lambda task: deploy.variables_read(document, task)) == ()


def test_a_derived_name_the_launcher_cannot_forward_is_left_out():
    # arrange: the launcher sets HOME itself; forwarding the host's would break the container
    document = _document(environments=_PROD.replace("[APP_TITLE]", "[APP_TITLE, HOME]"))

    # act
    names = launcherenv.declared(document, derive=lambda task: deploy.variables_read(document, task))

    # assert
    assert "HOME" not in names and "APP_TITLE" in names


def _rendered(tmp_path):
    """A scaffolded product with the carrier, a portainer environment and the two deploy commands, its
    launchers re-rendered."""
    root = _product(tmp_path)
    path = root / "democtl.yaml"
    text = path.read_text(encoding="utf-8")
    environments = "    dev: { backend: local, description: \"Local development environment (the default).\" }\n"
    commands = "      up:   { task: up }\n"
    assert text.count(environments) == 1 and text.count(commands) == 1
    text = (text.replace(environments, environments + _PROD)
                .replace(commands, commands + "      rollout: { task: \"deploy:up\" }\n"
                                              "      teardown: { task: \"deploy:down\" }\n")
            + _CARRIER)
    path.write_text(text, encoding="utf-8")
    assert bootstrap.main(["init", "democtl", "--dir", str(root), "--launchers-only"]) == 0
    return root


def test_a_rendered_launcher_forwards_the_carriers_names_by_name(tmp_path):
    # arrange
    root = _rendered(tmp_path)

    # act
    done = _run(root, "support", "doctor", env={"HAUS_URL": "https://haus:9443", "HAUS_TOKEN": SECRET})

    # assert: the names cross by name, the value is on no docker line, and the launcher says what it forwards
    assert done.returncode == 0, done.stderr
    kernel = done.docker[-1]
    assert " -e HAUS_URL " in f" {kernel} " and " -e HAUS_TOKEN " in f" {kernel} "
    assert f"-e DELIVERY_ENV_PASS={' '.join(UP)}" in kernel
    for line in done.docker:
        assert SECRET not in line


def test_a_name_declared_nowhere_and_derived_from_nothing_is_still_not_forwarded(tmp_path):
    # arrange: PORTAINER_STACK is read by `from_env`, and no manifest names it
    root = _rendered(tmp_path)

    # act
    done = _run(root, "support", "doctor", env={"PORTAINER_STACK": "other", "UNRELATED_SECRET": SECRET})

    # assert
    assert done.returncode == 0, done.stderr
    assert "PORTAINER_STACK" not in done.docker[-1]
    assert "UNRELATED_SECRET" not in done.docker[-1]


# --- the keep-list: the deploy commands keep them, every other command loses them ---------------------


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A registered product context over a manifest with the carrier and the deploy commands; the container
    route as the launcher leaves it, the derived names forwarded."""
    path = tmp_path / "demo.yaml"
    path.write_text(yaml.safe_dump(_document(
        commands="      both: { help: \"Both.\", depends_on: [rollout, teardown] }\n"
                 "      quiet: { help: \"Nothing derived.\", depends_on: [smoke] }\n")), encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext("demo", tmp_path, path))
    monkeypatch.setenv("HAUS_URL", "https://haus:9443")
    monkeypatch.setenv("HAUS_TOKEN", SECRET)
    monkeypatch.setenv("DELIVERY_ENV_PASS", " ".join(UP))
    return path


_SEEN: list[tuple[str | None, str | None]] = []


def _look() -> int:
    _SEEN.append((os.environ.get("HAUS_URL"), os.environ.get("HAUS_TOKEN")))
    return 0


def smoke() -> int:
    """The product's own `smoke` body: it only looks."""
    return _look()


def _deploy_body(version: str = "") -> int:
    """`deploy.up`'s and `deploy.down`'s signature, so the CLI binds what it binds for the real bodies."""
    return _look()


@pytest.fixture
def seen(monkeypatch):
    """What a body sees of HAUS_URL and HAUS_TOKEN when it runs, or an aggregate when its plan does."""
    _SEEN.clear()
    monkeypatch.setattr(deploy_up.DeployUp, "run", staticmethod(_deploy_body))
    monkeypatch.setattr(deploy_down.DeployDown, "run", staticmethod(_deploy_body))
    monkeypatch.setattr(cli, "run_command", lambda name, mf, ctx, **kw: _look())
    return _SEEN


def _app() -> typer.Typer:
    from simplon.kernel.product import StepFactoryContext
    app = typer.Typer(add_completion=False, no_args_is_help=True, help="demo root")
    cli.assemble(app, context.current().manifest(), product="demo",
                 step_context=StepFactoryContext("demo", lambda name, **kw: None))
    return app


@pytest.mark.parametrize("command", [["deploy", "rollout"], ["deploy", "teardown"]])
def test_a_deploy_command_keeps_its_carriers_names_with_nothing_declared(product, seen, command):
    # act
    result = CliRunner().invoke(_app(), command)

    # assert
    assert result.exit_code == 0, result.output
    assert seen == [("https://haus:9443", SECRET)]


def test_another_command_loses_them_before_its_code_runs(product, seen):
    # act
    result = CliRunner().invoke(_app(), ["build", "smoke"])

    # assert
    assert result.exit_code == 0, result.output
    assert seen == [(None, None)]
    assert "HAUS_TOKEN" not in os.environ


def test_an_aggregate_over_a_deploy_command_keeps_them(product, seen):
    # act
    result = CliRunner().invoke(_app(), ["deploy", "both"])

    # assert
    assert result.exit_code == 0, result.output
    assert seen == [("https://haus:9443", SECRET)]


def test_an_aggregate_over_no_deploy_command_loses_them(product, seen):
    # act
    result = CliRunner().invoke(_app(), ["deploy", "quiet"])

    # assert
    assert result.exit_code == 0, result.output
    assert seen == [(None, None)]


def test_the_generated_module_asks_for_the_derived_names_when_the_command_runs(product):
    # act
    text = taskgen.render(context.current().manifest(), source="demo.yaml", product="demo")

    # assert: the deploy commands and the aggregate over them keep what is derived when they run, so a
    # changed environment needs no regeneration; the other commands keep nothing
    assert "from simplon.tasks import deploy as _deploy" in text
    assert "_launcherenv.confined(() + _deploy.variables_kept('deploy:up'), lambda: " in text
    assert "_launcherenv.confined(() + _deploy.variables_kept('deploy:down'), lambda: " in text
    assert ("_launcherenv.confined(() + _deploy.variables_kept('deploy:up', 'deploy:down'), "
            "lambda: _plan('both', 'deploy'))") in text
    assert "_launcherenv.confined((), lambda: _plan('quiet', 'deploy'))" in text
    assert "_launcherenv.confined((), lambda: _rc(" in text
