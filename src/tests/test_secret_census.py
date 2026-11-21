"""si#833: every name the kernel reads has a role, and no sink prints a secret value.

TWO HALVES, modelled on `test_refusal_census.py`.

THE CENSUS. The population is DERIVED, not listed: every name `deploy.variables_read` derives for each task
in `deploy.READS` (`deploy:up`, `deploy:down`, and `deploy:carrier` through `carrier.variables_read`), every
name the launcher forwards (`launcherenv.declared`, which adds each command's `env: pass:`), and the
launcher's fixed names (`launcherenv.FORWARDED`). Each has to have a role a reader declared, so a reader that
joins the derivation cannot do so without saying whether its name is secret.

THE POPULATION'S LIMIT, measured 2026-11-21 and said here rather than left to be found. The eight frozen
manifests (`fixtures/manifests`) predate `carriers:`, so they derive no name at all; the live biz-cockpit
manifest derives thirty for `deploy:up`, and no reachable manifest declares a `proxmox:` carrier. So the
census also runs over two documents in the live shapes: biz-cockpit's own (`_BIZ`, its confirmed prod
`secret:` list) and a carrier the kernel makes (`_CARRIER`), which is the only way `deploy:carrier` derives
anything.

THE CANARY. A value set in the environment under a secret role must not appear in anything the kernel
writes: stdout, stderr, the step log, the run transcript, a streaming step's header, a refusal, the TUI's
details pane and clipboard (si#839), and the helper container's command on a carrier. Each canary is an
obvious fake.

THE PRODUCT'S HALF IS NOT VERIFIABLE HERE, and that limit is recorded: a product that adds a secret to
`optional:` and forgets `secret:` gets it printed wherever the kernel interpolates it.

AAA; the name states the behaviour under test.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
import typer
import yaml

import realmanifests
from simplon import cli
from simplon.adapters import portainer
from simplon.kernel import log, run, secrets, steplog, steps
from simplon.manifest import deployment, environments, launcherenv
from simplon.manifest.context import TaskRefused
from simplon.tasks import deploy

from conftest import Recorder

#: biz-cockpit's live shape (si#833 design note, section 1a): one carrier, a clone credential, and in prod
#: the three secrets its session confirmed.
_BIZ = yaml.safe_load("""\
product: biz
cd:
  default: test
  environments:
    test:
      backend: portainer
      carrier: hausportainer
      stack: biz-test
      repository: { url: "https://github.com/acme/biz", credential_from: GIT }
      required: [RESTART_POLICY, HTTP_BIND, HTTP_PORT]
      optional: [APP_TITLE, TOGGL_FAKE]
    prod:
      backend: portainer
      carrier: hausportainer
      stack: biz-prod
      repository: { url: "https://github.com/acme/biz", credential_from: GIT }
      required: [RESTART_POLICY, HTTP_BIND, HTTP_PORT]
      optional: [APP_TITLE, SMALLINVOICE_CLIENT_ID, SMALLINVOICE_CLIENT_SECRET, TOGGL_API_TOKEN,
                 O365_TENANT_ID, O365_CLIENT_ID, O365_CLIENT_SECRET]
      secret: [SMALLINVOICE_CLIENT_SECRET, TOGGL_API_TOKEN, O365_CLIENT_SECRET]
  deploy:
    commands:
      up: { task: "deploy:up" }
      down: { task: "deploy:down" }
ci:
  release:
    commands:
      publish: { task: "deploy:up", env: { pass: [VSCE_PAT] } }
carriers:
  hausportainer:
    portainer: { url_from: PORTAINER }
""")

#: A carrier the kernel makes, with every half: the only shape `deploy:carrier` derives a name for.
_CARRIER = yaml.safe_load("""\
product: demo
cd:
  default: prod
  environments:
    prod: { backend: portainer, carrier: haus, stack: demo }
  deploy:
    commands:
      carrier: { task: "deploy:carrier" }
carriers:
  haus:
    proxmox: { node: pve, kind: lxc, token_from: PVE }
    portainer: { url_from: HAUS }
    runner: { repository: acme/demo, labels: [haus], token_from: COCKPIT }
""")

_FROZEN = ("agile-cockpit", "asbundle", "biz-cockpit", "cleon", "firn", "netctl", "simplon", "swi")


def _population() -> list[tuple[str, dict]]:
    """Every document the census rules on: the frozen eight, this kernel's own manifest, and the two live
    shapes. `yaml.safe_load` rather than the kernel's loader, because a frozen manifest is read as it was."""
    documents = [(name, yaml.safe_load(realmanifests.text(name))) for name in _FROZEN]
    own = Path(__file__).resolve().parents[2] / "simplon.yaml"
    documents.append(("simplon.yaml (this kernel)", yaml.safe_load(own.read_text(encoding="utf-8"))))
    return [*documents, ("biz-cockpit (live shape)", _BIZ), ("carrier the kernel makes", _CARRIER)]


# --- the census: every name has a role ---------------------------------------------------------------


def test_every_name_a_reader_derives_has_a_role():
    # arrange
    unroled: list[str] = []
    derived: dict[str, int] = {task: 0 for task in deploy.READS}

    # act
    for label, data in _population():
        for task in deploy.READS:
            names = deploy.variables_read(data, task)
            roles = deploy.variable_roles(data, task)
            derived[task] += len(names)
            unroled += [f"{label}: {task} derives {name}" for name in names if roles.get(name) not in secrets.ROLES]

    # assert
    assert not unroled, "a reader derives a name and says nothing about whether it is secret: " + "; ".join(unroled)
    # assert: and every task derived something, so the loop ruled on names and not on nothing
    assert all(derived.values()), f"a task derived nothing over the whole population: {derived}"


def test_every_name_the_launcher_forwards_has_a_role():
    """The launcher's list is the derived names AND each command's `env: pass:`. An `env: pass:` name is
    secret by role (`launcherenv.within` reads it through `secrets.read`); every other one is a reader's."""
    # arrange
    unroled: list[str] = []
    forwarded = 0

    # act
    for label, data in _population():
        if not isinstance(data.get("cd"), dict) and not isinstance(data.get("ci"), dict):
            continue
        try:
            passed = set(launcherenv.declared(data, label, derive=lambda task: ()))
            names = launcherenv.declared(data, label, derive=lambda task, d=data: deploy.variables_read(d, task))
        except ValueError:
            continue        # a frozen manifest in a retired form: the loader refuses it before any launcher
        roles = {name: role for task in deploy.READS for name, role in deploy.variable_roles(data, task).items()}
        forwarded += len(names)
        unroled += [f"{label}: {name}" for name in names if name not in passed and name not in roles]

    # assert
    assert not unroled, f"the launcher forwards a name nobody gave a role: {unroled}"
    assert forwarded, "no document forwarded a name, so the census ruled on nothing"
    assert set(launcherenv.FORWARDED) == set(launcherenv.FORWARDED_ROLES)
    assert all(role in secrets.ROLES for role in launcherenv.FORWARDED_ROLES.values())


def test_the_reader_says_which_half_of_a_pair_is_the_secret():
    """The measured secrets of the design note, each from the reader that spells it - and nothing else."""
    # act
    up = deploy.variable_roles(_BIZ, "deploy:up")
    down = deploy.variable_roles(_BIZ, "deploy:down")
    made = deploy.variable_roles(_CARRIER, "deploy:carrier")

    # assert
    assert {name for name, role in up.items() if role == secrets.SECRET} == {
        "PORTAINER_TOKEN", "PORTAINER_GHCR_PASSWORD", "GIT_PASSWORD",
        "SMALLINVOICE_CLIENT_SECRET", "TOGGL_API_TOKEN", "O365_CLIENT_SECRET"}
    assert {name for name, role in down.items() if role == secrets.SECRET} == {"PORTAINER_TOKEN"}
    assert made == {name: secrets.SECRET for name in (
        "HAUS_PASSWORD", "COCKPIT_RUNNER_TOKEN", "PVE_API_TOKEN", "SIMPLON_STATE_PASSPHRASE",
        "SIMPLON_CARRIER_SSH_PRIVATE_KEY")}
    # assert: a port, a flag and an OAuth identifier stay plain, so `80` is never masked
    assert up["HTTP_PORT"] == up["TOGGL_FAKE"] == up["O365_CLIENT_ID"] == secrets.PLAIN


# --- the manifest key ----------------------------------------------------------------------------------


def _with_secret(secret: list[str]) -> dict:
    document = yaml.safe_load(yaml.safe_dump(_BIZ))
    document["cd"]["environments"]["prod"]["secret"] = secret
    return document


def test_a_secret_name_in_neither_list_is_refused_by_name():
    # act / assert
    with pytest.raises(ValueError) as refused:
        environments.parse_data(_with_secret(["TOGGL_API_TOKEN", "TOGGL_TOKEN"]))
    assert "`secret:` names TOGGL_TOKEN, which is in neither `required:` nor `optional:`" in str(refused.value)


def test_a_secret_list_is_read_beside_the_two_lists_and_changes_neither():
    # act
    prod = environments.parse_data(_BIZ).environments["prod"]
    test = environments.parse_data(_BIZ).environments["test"]

    # assert
    assert prod.secret == ("SMALLINVOICE_CLIENT_SECRET", "TOGGL_API_TOKEN", "O365_CLIENT_SECRET")
    assert "TOGGL_API_TOKEN" in prod.optional
    assert test.secret == ()


# --- the canary: no sink prints a secret value ----------------------------------------------------------

CANARY = "canary-833-toggl-api-token"


@pytest.fixture
def registered(monkeypatch, tmp_path):
    """The canary read the way a deployment reads it (`stack_values`), and the step log written under
    `tmp_path`. Each test wraps the streams itself, the way `cli.main` does: pytest puts its own capture
    back on `sys.stdout` when the test body starts, so a wrapper installed here would be gone."""
    monkeypatch.setenv("TOGGL_API_TOKEN", CANARY)
    monkeypatch.setenv("HTTP_PORT", "80")
    for name in ("RESTART_POLICY", "HTTP_BIND"):
        monkeypatch.setenv(name, "x")
    monkeypatch.setattr(steplog, "log_directory", lambda: tmp_path)
    portainer.stack_values(environments.parse_data(_BIZ).environments["prod"])
    return tmp_path


def test_no_stream_sink_prints_a_secret_value(registered, capsys):
    # arrange
    secrets.install()

    # act
    log.info(f"resolved /srv/{CANARY}/data")
    log.ok(f"ok {CANARY}")
    log.warn(f"warn {CANARY}")
    log.error(f"error {CANARY}")
    print(f"print {CANARY}")
    print(f"print {CANARY}", file=sys.stderr)
    log.info("listening on 80")
    said = capsys.readouterr()

    # assert
    assert CANARY not in said.out + said.err
    assert said.out.count(secrets.MASK) == 4 and said.err.count(secrets.MASK) == 2, "every line was printed"
    assert "listening on 80" in said.out, "a plain value is printed as it is"


def test_no_file_sink_writes_a_secret_value(registered):
    # act
    steplog.write("build", f"line one\nthe token is {CANARY}\n")
    steplog.write_run(f"transcript {CANARY}")
    step = steps.argv_step("probe", ["true", f"--token={CANARY}"])

    # assert
    written = "".join(path.read_text(encoding="utf-8") for path in registered.iterdir())
    assert CANARY not in written
    assert written.count(secrets.MASK) == 2
    assert CANARY not in str(step.command) and secrets.MASK in str(step.command)


def test_a_command_line_that_would_carry_a_secret_is_refused_and_named_without_it(registered):
    # act / assert
    for call in (lambda: run.run(["docker", "run", "-e", f"TOGGL_API_TOKEN={CANARY}", "img"]),
                 lambda: run.run_stream(["echo", CANARY], lambda line: None)):
        with pytest.raises(secrets.SecretInArgv) as refused:
            call()
        assert "TOGGL_API_TOKEN" in str(refused.value) and CANARY not in str(refused.value)


def test_a_refusal_rendered_at_the_top_is_redacted(registered, capsys, monkeypatch):
    # arrange
    monkeypatch.setattr(sys, "argv", ["demo"])
    secrets.install()
    app = typer.Typer()

    @app.command()
    def body() -> None:
        raise TaskRefused(f"/srv/{CANARY} is not a directory")

    # act
    with pytest.raises(SystemExit):
        cli.run_app(app, prog_name="demo")
    said = capsys.readouterr()

    # assert
    assert CANARY not in said.err and f"/srv/{secrets.MASK} is not a directory" in said.err


def test_a_directory_templated_from_a_secret_never_reaches_the_carrier_or_the_output(monkeypatch, capsys):
    """The design note's 2a: a `directories:` path resolved from a secret. Logged lines read `***`, and the
    helper's `install -d` - the command line `docker inspect` shows on the carrier - is refused."""
    # arrange
    from test_portainer_directories import FakeDaemon

    document = yaml.safe_load(yaml.safe_dump(_BIZ))
    document["cd"]["environments"]["prod"]["directories"] = [{"path": "/srv/${TOGGL_API_TOKEN}"}]
    env = environments.parse_data(document).environments["prod"]
    for name, value in {"TOGGL_API_TOKEN": CANARY, "RESTART_POLICY": "x", "HTTP_BIND": "x",
                        "HTTP_PORT": "80", "GIT_USER": "x", "GIT_PASSWORD": "canary-833-git-password"}.items():
        monkeypatch.setenv(name, value)
    daemon = FakeDaemon({"/srv": (0, 0, 0o755)})
    monkeypatch.setattr(portainer, "_request", Recorder({"/stacks": []}))
    monkeypatch.setattr(portainer, "_docker", daemon, raising=False)
    monkeypatch.setattr(portainer, "_target_for", lambda e: (portainer.PortainerTarget("https://p", "t", 3,
                                                                                       "biz-prod"), env.repository))
    monkeypatch.setattr(portainer, "_built_by_kernel", lambda e: False, raising=False)
    monkeypatch.setattr(portainer, "check_registry_access", lambda *args: None)
    secrets.install()

    # act
    with pytest.raises(secrets.SecretInArgv) as refused:
        portainer.PortainerBackend().deploy(env, deployment.Version(selector="1.4.0", tag="1.4.0", builds=False))
    said = capsys.readouterr()

    # assert
    assert CANARY not in said.out + said.err + str(refused.value)
    assert "canary-833-git-password" not in said.out + said.err
    assert not any(CANARY in " ".join(spec.get("Cmd") or []) for spec in daemon.specs.values()), \
        "no helper on the carrier was started with the secret on its command line"
    assert daemon.written == []


def test_an_env_pass_name_is_secret_when_its_command_runs(monkeypatch, capsys):
    # arrange
    monkeypatch.setenv("VSCE_PAT", "canary-833-vsce-pat")
    secrets.install()

    # act
    launcherenv.within(("VSCE_PAT",), lambda: log.info("publishing with canary-833-vsce-pat") or 0)

    # assert
    assert "canary-833-vsce-pat" not in capsys.readouterr().out
    assert secrets.role("VSCE_PAT") == secrets.SECRET


# --- GitHub Actions: masked at run time, before the first use ------------------------------------------


def _actions(monkeypatch, value: str) -> io.StringIO:
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(secrets, "_mask_stream", lambda: out)
    monkeypatch.setenv("SIMPLON_CARRIER_SSH_PRIVATE_KEY", value)
    secrets.install()
    return out


def test_in_github_actions_every_line_of_a_value_is_masked_before_its_first_use(monkeypatch):
    # arrange
    monkeypatch.setenv(secrets.ACTIONS_ENV, "true")
    key = "-----BEGIN OPENSSH PRIVATE KEY-----\ncanary-833-key-line\n-----END OPENSSH PRIVATE KEY-----"
    out = _actions(monkeypatch, key)

    # act
    secrets.read("SIMPLON_CARRIER_SSH_PRIVATE_KEY")
    log.info("the key line is canary-833-key-line")

    # assert
    lines = out.getvalue().splitlines()
    masks = [line for line in lines if line.startswith("::add-mask::")]
    assert "::add-mask::canary-833-key-line" in masks
    assert lines.index("::add-mask::canary-833-key-line") < len(masks) <= lines.index(lines[-1])
    assert "canary-833-key-line" not in lines[-1] and lines[-1].endswith(f"the key line is {secrets.MASK}")


def test_the_tui_pane_and_its_clipboard_never_hold_a_secret_value(registered, monkeypatch):
    """si#839: Textual's driver draws to `sys.__stderr__`, past the wrapper `secrets.install` puts on
    `sys.stderr` (measured in textual 8: `LinuxDriver._file = sys.__stderr__`), and a step's captured lines
    reach the details pane without passing any other redacting sink. So the pane redacts what it is handed,
    and so does every copy out of the app - `c`, and a mouse selection's ctrl+c."""
    # arrange
    pytest.importorskip("textual")
    import asyncio

    from simplon.ui import clipboard, tui
    from test_orchestrator_tui import _details

    copied: list[str] = []
    monkeypatch.setattr(clipboard, "copy", lambda text, **kw: copied.append(text) or clipboard.Result(
        clipboard.State.CONFIRMED, "stub"))
    monkeypatch.setattr(steps, "clock", lambda: 0.0)
    pipeline = steps.Pipeline("leak", [steps.Step(label="prints", action=lambda: steps.Outcome(
        rc=0, output=f"the token is {CANARY}"))])

    async def scenario() -> str:
        app = tui._StepApp(pipeline)
        async with app.run_test() as pilot:
            await pilot.pause()
            while any(s.state in (steps.StepState.PENDING, steps.StepState.RUNNING) for s in pipeline.steps):
                await pilot.pause(0.05)
            await pilot.press("down")
            await pilot.press("c")
            await pilot.pause()
            return _details(app)

    # act
    shown = asyncio.run(scenario())

    # assert
    assert f"the token is {secrets.MASK}" in shown, f"the step's output is in the pane, masked: {shown!r}"
    assert CANARY not in shown
    assert copied and all(CANARY not in text for text in copied), copied


def test_the_token_gh_prints_is_registered_like_one_read_from_the_environment(monkeypatch, capsys):
    """si#839: `githubpackages.token`'s fallback takes the token `gh auth token` prints, which never was an
    environment variable, so `secrets.read` never saw it."""
    # arrange
    from simplon.adapters import githubpackages

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(run, "run", lambda *args, **kwargs: run.Result(0, "canary-839-gh-token\n", ""))
    secrets.install()

    # act
    token = githubpackages.token()
    log.info(f"logging in with {token}")

    # assert
    assert token == "canary-839-gh-token"
    assert "canary-839-gh-token" not in capsys.readouterr().out
    with pytest.raises(secrets.SecretInArgv):
        secrets.check_argv(["oras", "login", "-p", token])


def test_the_nexus_password_read_from_its_container_is_registered(monkeypatch, capsys):
    """si#839: `nexusproxy._admin_password` reads the generated password out of the container's file first,
    and only falls back to `NEXUS_ADMIN_PASSWORD`."""
    # arrange
    from simplon.adapters import nexusproxy
    from test_nexusproxy import CFG

    monkeypatch.setattr(nexusproxy, "run", lambda *args, **kwargs: run.Result(0, "canary-839-nexus\n", ""))
    secrets.install()

    # act
    password = nexusproxy._admin_password(CFG)
    log.info(f"admin:{password}")

    # assert
    assert password == "canary-839-nexus"
    assert "canary-839-nexus" not in capsys.readouterr().out
    with pytest.raises(secrets.SecretInArgv):
        secrets.check_argv(["curl", "-u", f"admin:{password}"])


def test_outside_github_actions_nothing_is_masked(monkeypatch):
    # arrange
    monkeypatch.delenv(secrets.ACTIONS_ENV, raising=False)
    out = _actions(monkeypatch, "canary-833-key")

    # act
    secrets.read("SIMPLON_CARRIER_SSH_PRIVATE_KEY")

    # assert
    assert "::add-mask::" not in out.getvalue()
