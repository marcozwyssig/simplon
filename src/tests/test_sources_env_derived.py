"""si#873: the names `support sources` reads reach the kernel on the container route.

The launcher forwards only names somebody declared, and `support sources` is placed by the catalogue, so no
product command carries them. They are derived straight from the `sources:` section (ruled 2026-11-24, option
C): every `secret:`, and `GITHUB_ACTIONS` when at least one source declares a secret - the only case
`support sources` reads it (its empty-secret guard). The in-kernel keep holds them for a command bound to
`support:sources` and for no other.
"""
from pathlib import Path

import yaml

from simplon import cli
from simplon.cli import bootstrap
from simplon.kernel import secrets
from simplon.manifest import context, launcherenv
from simplon.manifest import sources as declared_sources
from simplon.manifest.context import ProductContext
from simplon.tasks import deploy

ROOT = Path(__file__).resolve().parents[2]
SECRET_SOURCE = {"sources": [{"submodule": "lib/platform", "secret": "PLATFORM_REPO_TOKEN"}]}


def _declared(document):
    return launcherenv.declared(document, derive=lambda task: deploy.variables_read(document, task),
                                product="simplon")


def _simplon():
    return yaml.safe_load((ROOT / "simplon.yaml").read_text(encoding="utf-8"))


def test_a_secret_source_puts_its_secret_and_github_actions_on_the_pass_list():
    document = {**_simplon(), **SECRET_SOURCE}

    names = _declared(document)

    assert "PLATFORM_REPO_TOKEN" in names and "GITHUB_ACTIONS" in names
    assert names[:len(_declared(_simplon()))] == _declared(_simplon())


def test_a_public_source_derives_nothing_because_nothing_reads_github_actions():
    document = {**_simplon(), "sources": [{"submodule": "lib/platform"}]}

    assert _declared(document) == _declared(_simplon())


def test_the_roles_say_the_token_is_secret_and_github_actions_is_not():
    assert declared_sources.variable_roles(SECRET_SOURCE) == {"PLATFORM_REPO_TOKEN": secrets.SECRET,
                                                               "GITHUB_ACTIONS": secrets.PLAIN}


def test_without_sources_the_rendered_launchers_are_byte_identical(tmp_path):
    """The launchers `--launchers-only` renders from a manifest with no `sources:` do not change; with one, the
    pass list gains exactly the derived names."""
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "simplon.yaml").write_text((ROOT / "simplon.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    assert bootstrap.launcher_env_pass("simplon", plain) == _declared(_simplon())
    assert bootstrap.launcher_left_out("simplon", plain) == ()

    with_sources = tmp_path / "with"
    with_sources.mkdir()
    (with_sources / "simplon.yaml").write_text(yaml.safe_dump({**_simplon(), **SECRET_SOURCE}), encoding="utf-8")
    added = bootstrap.launcher_env_pass("simplon", with_sources)
    assert set(added) - set(bootstrap.launcher_env_pass("simplon", plain)) == {"PLATFORM_REPO_TOKEN",
                                                                              "GITHUB_ACTIONS"}


def _context(monkeypatch, tmp_path, document):
    manifest = tmp_path / "sample.yaml"
    manifest.write_text(yaml.safe_dump(document), encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("sample", tmp_path, manifest))


def test_the_kernel_keeps_the_names_for_support_sources_only(monkeypatch, tmp_path):
    _context(monkeypatch, tmp_path, {"product": "sample", **SECRET_SOURCE})

    assert set(cli._derived("support:sources")) == {"PLATFORM_REPO_TOKEN", "GITHUB_ACTIONS"}
    assert cli._derived("support:install") == ()


def test_confine_unsets_the_token_for_every_other_command(monkeypatch, tmp_path):
    _context(monkeypatch, tmp_path, {"product": "sample", **SECRET_SOURCE})
    environ = {"DELIVERY_ENV_PASS": "PLATFORM_REPO_TOKEN GITHUB_ACTIONS", "PLATFORM_REPO_TOKEN": "t",
               "GITHUB_ACTIONS": "true"}

    kept = dict(environ)
    launcherenv.confine(cli._derived("support:sources"), kept)
    other = dict(environ)
    launcherenv.confine(cli._derived("support:install"), other)

    assert kept["PLATFORM_REPO_TOKEN"] == "t" and kept["GITHUB_ACTIONS"] == "true"
    assert "PLATFORM_REPO_TOKEN" not in other and "GITHUB_ACTIONS" not in other


def test_github_actions_is_never_masked(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets, "_values", {})
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("PLATFORM_REPO_TOKEN", "tok-derived-1234")
    _context(monkeypatch, tmp_path, {"product": "sample", **SECRET_SOURCE})

    cli._derived("support:sources")

    assert secrets.redact("ok true tok-derived-1234") == "ok true ***"


_GENERATED = """
product: demo
sources:
  - submodule: lib/platform
    secret: PLATFORM_REPO_TOKEN
tasks:
  ship:
    impl: "simplon.tasks.sources:sources_cmd"
    help: "Ship it."
support:
  commands:
    ship:
      task: ship
      env: { pass: [VSCE_PAT] }
"""


def test_the_generated_module_keeps_the_sources_names_for_support_sources_only():
    """A generated module whose commands pass a name confines every command; `support sources` keeps what the
    `sources:` section derives, asked when it runs, and the other command keeps only its own list."""
    from simplon.manifest import catalogue
    from simplon.manifest import load as manifest_load
    from simplon.tasks import taskgen

    manifest = manifest_load.load(_GENERATED, catalogue=catalogue.load())

    text = taskgen.render(manifest, source="demo.yaml", product="demo", groups=frozenset({"support"}))

    assert "from simplon.tasks import sources as _sources" in text
    assert "_launcherenv.confined(() + _sources.variables_kept('support:sources'), lambda: " in text
    assert "_launcherenv.confined(('VSCE_PAT',), lambda: " in text
    assert text.count("_sources.variables_kept(") == 1
    compile(text, "demo_cli.py", "exec")


_NO_PASS = """
product: demo
sources:
  - submodule: lib/platform
    secret: PLATFORM_REPO_TOKEN
tasks:
  ship:
    impl: "simplon.tasks.sources:sources_cmd"
    help: "Ship it."
support:
  commands:
    ship: { task: ship }
"""


def _render(text, groups=frozenset({"support"})):
    from simplon.manifest import catalogue
    from simplon.manifest import load as manifest_load
    from simplon.tasks import taskgen

    return taskgen.render(manifest_load.load(text, catalogue=catalogue.load()), source="demo.yaml",
                          product="demo", groups=groups)


def test_a_sources_secret_alone_makes_the_generated_module_confine_every_command():
    """No command passes a name, but the launcher forwards the `sources:` secret, so every command is confined
    and only `support sources` keeps it."""
    text = _render(_NO_PASS)

    calls = [line for line in text.splitlines() if "lambda: _rc(" in line]
    assert calls and all("_launcherenv.confined(" in line for line in calls)
    assert text.count("_sources.variables_kept('support:sources')") == 1
    compile(text, "demo_cli.py", "exec")


def test_a_public_source_leaves_the_generated_module_unconfined():
    text = _render(_NO_PASS.replace("    secret: PLATFORM_REPO_TOKEN\n", ""))

    assert "_launcherenv.confined(" not in text


def test_an_aggregate_whose_plan_reaches_support_sources_keeps_the_names():
    text = _render(_NO_PASS + """
    ci:
      build:
        commands:
          prepare:
            help: "Check out and ship."
            depends_on: [support sources, support ship]
    """.replace("\n    ", "\n"), groups=frozenset({"support", "build"}))

    assert ("_launcherenv.confined(() + _sources.variables_kept('support:sources'), "
            "lambda: _plan('prepare', 'build'))") in text


def test_a_secret_the_launcher_already_forwards_stays_off_the_pass_list():
    """`secret: GH_TOKEN` is forwarded by every launcher already; on DELIVERY_ENV_PASS confine would unset it
    for every other command, so the derivation leaves it off (and GITHUB_ACTIONS, read for it, on)."""
    document = {**_simplon(), "sources": [{"submodule": "lib/platform", "secret": "GH_TOKEN"}]}

    names = _declared(document)

    assert "GH_TOKEN" not in names and "GITHUB_ACTIONS" in names
    for secret in ("GITHUB_TOKEN", "DELIVERY_X_TOKEN", "SIMPLON_PLATFORM_TOKEN"):
        document = {**_simplon(), "sources": [{"submodule": "lib/platform", "secret": secret}]}
        assert secret not in _declared(document)
