"""si#812: `deploy:carrier` gets the names its carrier declares, on the container route.

si#810 (PR #811) derived what `deploy:up`/`deploy:down` read. `deploy:carrier` had the same gap: it reads the
Portainer admin password `<url_from>_PASSWORD`, the Proxmox `<token_from>_API_TOKEN`, the runner's
`<token_from>_RUNNER_TOKEN` (si#781) and the kernel's own `SIMPLON_STATE_PASSPHRASE` and
`SIMPLON_CARRIER_SSH_KEY` (since si#819 `SIMPLON_CARRIER_SSH_PRIVATE_KEY`). None of them is a fixed launcher name and none is under a product's own
`<PRODUCT>_*` prefix unless the product happens to be called `simplon`, so on the container route a carrier
run saw them only when some command repeated them under `env: pass:`.

The same mechanism as si#810, measured the same way: the `.sh` launcher runs against the fake `docker` of
`test_launch_container.py`, the keep-list through `simplon.cli.assemble` and Typer's runner.

AAA; the name states the behaviour under test.
"""
import os

import pytest
import typer
import yaml
from typer.testing import CliRunner

from simplon import cli
from simplon.cli import bootstrap
from simplon.manifest import context, launcherenv
from simplon.model import carrierspec
from simplon.tasks import carrier, deploy, deploy_carrier, taskgen
from test_launch_container import _product, _run

SECRET = "s3cret-812-long-enough"

#: biz-cockpit's shape: one carrier with all three halves, each with a prefix of its own, so a name can
#: only have come from the derivation.
_CARRIER = """\
carriers:
  haus:
    proxmox: { node: pve, kind: lxc, token_from: PVE }
    portainer: { url_from: HAUS }
    runner: { repository: acme/demo, labels: [haus], token_from: COCKPIT }
"""

_PROD = """\
    prod:
      backend: portainer
      carrier: haus
      stack: demo
"""

#: Every name a carrier run for `haus` reads, in the order `carrier.up` asks for them.
CARRIER = ("HAUS_PASSWORD", "COCKPIT_RUNNER_TOKEN", "PVE_API_TOKEN",
           "SIMPLON_STATE_PASSPHRASE", "SIMPLON_CARRIER_SSH_PRIVATE_KEY")


def _document(commands: str = "", environments: str = _PROD, carriers: str = _CARRIER) -> dict:
    return yaml.safe_load(f"""\
product: demo
tasks:
  smoke: {{ impl: "test_carrier_env_derived:smoke", help: "Look." }}
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
      machine: {{ task: "deploy:carrier" }}
{commands}
{carriers}""")


def _derive(document):
    return lambda task: deploy.variables_read(document, task)


# --- the derivation: the readers' own names ------------------------------------------------------------


def test_deploy_carrier_is_among_the_tasks_whose_names_are_derived():
    # assert: read off the catalogue's body table, like up and down
    assert deploy_carrier.DeployCarrier.KEY in deploy.READS


def test_a_carrier_run_reads_the_password_the_runner_token_the_api_token_and_the_kernels_two():
    # act / assert
    assert deploy.variables_read(_document(), "deploy:carrier") == CARRIER


def test_the_names_are_the_ones_the_readers_read(monkeypatch):
    """The derivation and the readers agree: set exactly the derived names, and every reader finds its value."""
    # arrange
    haus = carrierspec.declared(_document())["haus"]
    for name in deploy.variables_read(_document(), "deploy:carrier"):
        monkeypatch.setenv(name, f"{SECRET}-{name}")
    # The key is checked for its BEGIN line, so it gets a value of the shape it is read as.
    monkeypatch.setenv(carrier.SSH_PRIVATE_KEY_ENV, "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n"
                                                    "-----END OPENSSH PRIVATE KEY-----\n")

    # act / assert
    assert carrier.portainer_password(haus) == f"{SECRET}-HAUS_PASSWORD"
    assert carrier.runner_token(haus) == f"{SECRET}-COCKPIT_RUNNER_TOKEN"
    assert carrier._token(haus, haus.proxmox) == f"{SECRET}-PVE_API_TOKEN"
    assert os.environ[carrier.PASSPHRASE_ENV]
    carrier.private_key(haus)  # no SystemExit: the reader found what the derivation named


def test_a_carrier_with_only_the_machine_reads_the_api_token_and_the_state_passphrase():
    # arrange: no portainer:, no runner: - nothing asks for a password, a registration token or an SSH key
    document = _document(carriers=_CARRIER.replace("    portainer: { url_from: HAUS }\n", "")
                         .replace("    runner: { repository: acme/demo, labels: [haus], token_from: COCKPIT }\n", ""))

    # act / assert
    assert deploy.variables_read(document, "deploy:carrier") == ("PVE_API_TOKEN", "SIMPLON_STATE_PASSPHRASE")


def test_a_carrier_somebody_else_built_derives_nothing():
    # arrange: no proxmox: - `deploy carrier` refuses it, so it reads nothing
    document = _document(carriers="carriers:\n  haus:\n    portainer: { url_from: HAUS }\n")

    # act / assert
    assert deploy.variables_read(document, "deploy:carrier") == ()


def test_any_backend_standing_on_a_carrier_counts():
    # arrange: `deploy carrier` makes the machine whatever drives the environment on it
    document = _document(environments=_PROD.replace("backend: portainer", "backend: theirs"))

    # act / assert
    assert deploy.variables_read(document, "deploy:carrier") == CARRIER


def test_a_manifest_without_environments_derives_nothing_for_the_carrier():
    # arrange
    document = _document()
    del document["cd"]["environments"], document["cd"]["default"]

    # act / assert
    assert deploy.variables_read(document, "deploy:carrier") == ()


# --- the launcher's list, and the stale check that reads the same list ---------------------------------


def test_the_launchers_list_carries_the_carriers_names():
    # act / assert
    document = _document()
    assert launcherenv.declared(document, derive=_derive(document)) == CARRIER


def test_a_manifest_that_binds_no_carrier_command_derives_nothing_for_its_launcher():
    # arrange: the same carrier, and no command bound to deploy:carrier
    document = _document()
    document["cd"]["deploy"]["commands"] = {"status": {"task": "toolchain:run"}}

    # act / assert
    assert launcherenv.declared(document, derive=_derive(document)) == ()


def _rendered(tmp_path):
    """A scaffolded product with the carrier, a portainer environment and a carrier command, its launchers
    re-rendered by `simplon init --launchers-only`."""
    root = _product(tmp_path)
    path = root / "democtl.yaml"
    text = path.read_text(encoding="utf-8")
    environments = "    dev: { backend: local, description: \"Local development environment (the default).\" }\n"
    commands = "      up:   { task: up }\n"
    assert text.count(environments) == 1 and text.count(commands) == 1
    text = (text.replace(environments, environments + _PROD)
                .replace(commands, commands + "      machine: { task: \"deploy:carrier\" }\n")
            + _CARRIER)
    path.write_text(text, encoding="utf-8")
    assert bootstrap.main(["init", "democtl", "--dir", str(root), "--launchers-only"]) == 0
    return root


def test_a_rendered_launcher_forwards_the_carriers_names_by_name(tmp_path):
    # arrange
    root = _rendered(tmp_path)

    # act
    done = _run(root, "support", "doctor", env={name: SECRET for name in CARRIER})

    # assert: each name crosses by name, no value is on any docker line, and the list is the derived one
    assert done.returncode == 0, done.stderr
    kernel = done.docker[-1]
    for name in CARRIER:
        assert f" -e {name} " in f" {kernel} ", name
    assert f"-e DELIVERY_ENV_PASS={' '.join(CARRIER)}" in kernel
    for line in done.docker:
        assert SECRET not in line


def test_the_stale_check_agrees_with_the_rendered_launcher(tmp_path):
    """The container-route check computes the list the way the renderer does; disagreeing would refuse every run."""
    # arrange
    root = _rendered(tmp_path)
    (line,) = [line for line in (root / "democtl.sh").read_text(encoding="utf-8").splitlines()
               if line.startswith("LAUNCH_ENV_PASS=")]
    rendered = line.split("=", 1)[1].strip('"')
    data = yaml.safe_load((root / "democtl.yaml").read_text(encoding="utf-8"))

    # act
    stale = launcherenv.stale_launcher(launcherenv.declared(data, derive=_derive(data)),
                                       {launcherenv.EXPORTED: rendered}, "democtl.sh")

    # assert: and the list is the carrier's, so the agreement is not two empty lists
    assert rendered.split() == list(CARRIER)
    assert stale is None


# --- the keep-list: the carrier command keeps them, every other command loses them ---------------------


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A registered product context over the manifest; the container route as the launcher leaves it."""
    path = tmp_path / "demo.yaml"
    path.write_text(yaml.safe_dump(_document(
        commands="      both: { help: \"Both.\", depends_on: [machine] }\n"
                 "      quiet: { help: \"Nothing derived.\", depends_on: [smoke] }\n")), encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext("demo", tmp_path, path))
    for name in CARRIER:
        monkeypatch.setenv(name, SECRET)
    monkeypatch.setenv("DELIVERY_ENV_PASS", " ".join(CARRIER))
    return path


_SEEN: list[tuple[str | None, ...]] = []


def _look() -> int:
    _SEEN.append(tuple(os.environ.get(name) for name in CARRIER))
    return 0


def smoke() -> int:
    """The product's own `smoke` body: it only looks."""
    return _look()


def _carrier_body(environment: str = "") -> int:
    """`carrier.up`'s signature, so the CLI binds what it binds for the real body."""
    return _look()


@pytest.fixture
def seen(monkeypatch):
    _SEEN.clear()
    monkeypatch.setattr(deploy_carrier.DeployCarrier, "run", staticmethod(_carrier_body))
    monkeypatch.setattr(cli, "run_command", lambda name, mf, ctx, **kw: _look())
    return _SEEN


def _app() -> typer.Typer:
    from simplon.kernel.product import StepFactoryContext
    app = typer.Typer(add_completion=False, no_args_is_help=True, help="demo root")
    cli.assemble(app, context.current().manifest(), product="demo",
                 step_context=StepFactoryContext("demo", lambda name, **kw: None))
    return app


def test_the_carrier_command_keeps_its_names_with_nothing_declared(product, seen):
    # act
    result = CliRunner().invoke(_app(), ["deploy", "machine"])

    # assert
    assert result.exit_code == 0, result.output
    assert seen == [(SECRET,) * len(CARRIER)]


def test_another_command_loses_them_before_its_code_runs(product, seen):
    # act
    result = CliRunner().invoke(_app(), ["build", "smoke"])

    # assert
    assert result.exit_code == 0, result.output
    assert seen == [(None,) * len(CARRIER)]


def test_an_aggregate_over_the_carrier_command_keeps_them(product, seen):
    # act
    result = CliRunner().invoke(_app(), ["deploy", "both"])

    # assert
    assert result.exit_code == 0, result.output
    assert seen == [(SECRET,) * len(CARRIER)]


def test_an_aggregate_over_no_carrier_command_loses_them(product, seen):
    # act
    result = CliRunner().invoke(_app(), ["deploy", "quiet"])

    # assert
    assert result.exit_code == 0, result.output
    assert seen == [(None,) * len(CARRIER)]


def test_the_generated_module_asks_for_the_carriers_names_when_the_command_runs(product):
    # act
    text = taskgen.render(context.current().manifest(), source="demo.yaml", product="demo")

    # assert
    assert "_launcherenv.confined(() + _deploy.variables_kept('deploy:carrier'), lambda: " in text
    assert ("_launcherenv.confined(() + _deploy.variables_kept('deploy:carrier'), "
            "lambda: _plan('both', 'deploy'))") in text
    assert "_launcherenv.confined((), lambda: _plan('quiet', 'deploy'))" in text
