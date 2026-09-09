"""si#105: the four defects that sat between the design, the scaffolder and the manifest loader.

WHY THIS FILE EXISTS BESIDE test_toolchain.py. Every defect si#105 measured lives in a SEAM - between the
`with:` block the design writes, the impl the loader binds it to, and the command line Click renders from
that impl's signature. A unit test over `declared()` or `argv()` cannot see any of them, and that is
exactly how all four shipped: the pieces were each green on their own. So every test here goes through
the two steps a product actually takes, `ProductContext.manifest()` and `simplon.cli.assemble`, and
drives the result with Typer's runner.

AAA; the name states the behaviour under test.
"""
import pytest
import typer
import yaml
from typer.testing import CliRunner

from simplon import cli, context
from simplon.run import Result
from simplon.tasks import toolchain


# A product manifest in the shape `simplon init` writes: no `instance:` section, because nothing writes
# one (si#105 defect 4), and the two toolchain coordinates placed the way a product places them.
_MANIFEST = """\
product: demo
groups:
  build:
    commands:
{commands}
  support:
    commands:
      toolchain: { task: "support:toolchain" }
default: dev
environments:
  dev: { backend: local, description: "Local." }
"""

# The design's section 1 block, verbatim in shape: image / workdir / argv at the TOP LEVEL of `with:`.
_COMPILE = """\
      compile:
        task: "toolchain:run"
        help: "Compile in the containerised toolchain."
        with:
          image: "gradle:jdk25"
          workdir: /work
          argv: ["gradle", "build", "--no-daemon"]
"""

# A build group that holds SOMETHING the cpp profile will not collide with, so a scaffold test starts
# from a legal manifest (a declared group with no command anywhere under it is a load error).
_OTHER = """\
      smoke:
        task: "toolchain:run"
        with:
          image: "alpine:3.20"
          argv: ["true"]
"""

_COMPILE_WITH_CACHE = """\
      compile:
        task: "toolchain:run"
        with:
          image: "gradle:jdk25"
          workdir: /work
          argv: ["gradle", "build"]
          env: { GRADLE_USER_HOME: /home/gradle/.gradle }
          caches:
            - { volume: gradle-cache, path: /home/gradle/.gradle }
"""


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A registered product context over a manifest this test writes. Returns the manifest path."""
    path = tmp_path / "demo.yaml"
    monkeypatch.setattr(context, "_current", context.ProductContext("demo", tmp_path, path))
    monkeypatch.setattr(toolchain, "_manifest_path", lambda: path)
    return path


def _write(path, commands: str) -> None:
    path.write_text(_MANIFEST.replace("{commands}", commands), encoding="utf-8")


def _app(path) -> typer.Typer:
    """The product's CLI, assembled from its manifest exactly as `orchestrator/cli.py` assembles it."""
    app = typer.Typer(add_completion=False, no_args_is_help=True, help="demo root")
    cli.assemble(app, context.current().manifest(), product="demo")
    return app


@pytest.fixture
def docker_lines(monkeypatch):
    """Capture the docker argv instead of running it, and pin the uid flags so the line is comparable."""
    seen: list[list[str]] = []
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: ["--user", "1000:1000"])
    monkeypatch.setattr(toolchain, "run",
                        lambda a, **kw: seen.append(list(a)) or Result(rc=0, out="", err=""))
    return seen


# --- defect 2: the block the design writes must ASSEMBLE ----------------------------------------------

def test_the_with_block_the_design_writes_binds_to_the_impl(product, docker_lines):
    # arrange: image / workdir / argv at the top level of `with:`, which is the design's section 1 form
    _write(product, _COMPILE)

    # act
    result = CliRunner().invoke(_app(product), ["build", "compile"])

    # assert: it assembles, it runs, and the manifest's argv is what the container is handed
    assert result.exit_code == 0, result.output
    assert docker_lines[0][-3:] == ["gradle", "build", "--no-daemon"]
    assert "gradle:jdk25" in docker_lines[0]


def test_the_image_still_goes_through_the_one_pinned_gate(product, docker_lines):
    # arrange: the same block with an unpinned reference - the refusal must survive the new binding
    _write(product, _COMPILE.replace("gradle:jdk25", "gradle:latest"))

    # act
    result = CliRunner().invoke(_app(product), ["build", "compile"])

    # assert: refused before docker was asked, and the diagnosis names the command it was read from
    assert result.exit_code != 0
    assert docker_lines == []
    assert "latest" in result.output and "compile" in result.output


# --- defect 3: the appending rule needs a command line ------------------------------------------------

def test_the_caller_argv_is_appended_after_the_manifest_argv(product, docker_lines):
    # arrange
    _write(product, _COMPILE)

    # act: netctl#1091's promise - the full vocabulary survives behind a pinned default
    result = CliRunner().invoke(_app(product), ["build", "compile", "--rerun-tasks", "-x"])

    # assert
    assert result.exit_code == 0, result.output
    assert docker_lines[0][-5:] == ["gradle", "build", "--no-daemon", "--rerun-tasks", "-x"]


def test_an_empty_caller_argv_changes_the_line_by_not_one_byte(product, docker_lines):
    # arrange
    _write(product, _COMPILE)

    # act
    CliRunner().invoke(_app(product), ["build", "compile"])
    CliRunner().invoke(_app(product), ["build", "compile"])

    # assert: the manifest's declaration is the whole line when the caller adds nothing
    assert docker_lines[0] == docker_lines[1]
    assert docker_lines[0][-3:] == ["gradle", "build", "--no-daemon"]


def test_the_network_is_the_commands_own_option_and_not_the_tools(product, docker_lines):
    # arrange: the one runtime value a manifest cannot supply (the design's section 5)
    _write(product, _COMPILE)

    # act
    result = CliRunner().invoke(_app(product), ["build", "compile", "--network", "scratch-net", "-q"])

    # assert: `--network` is consumed here, everything after it still reaches the tool
    assert result.exit_code == 0, result.output
    assert ["--network", "scratch-net"] == docker_lines[0][3:5]
    assert docker_lines[0][-1] == "-q"


# --- defect 4: no `instance:` section until a cache needs one -----------------------------------------

def test_a_command_declaring_no_cache_runs_without_an_instance_section(product, docker_lines):
    # arrange: `simplon init` writes no `instance:` section, and neither does simplon.yaml itself
    _write(product, _COMPILE)

    # act
    result = CliRunner().invoke(_app(product), ["build", "compile"])

    # assert: nothing in the line needs an instance, so nothing asked for one
    assert result.exit_code == 0, result.output
    assert not [a for a in docker_lines[0] if a.startswith("demo-")]


def test_a_cache_volume_still_carries_the_product_and_the_instance(product, docker_lines, monkeypatch):
    # arrange: the instance is resolved WHERE it is needed, so the netctl#453 property is untouched
    monkeypatch.setattr(toolchain.labinstance, "resolve", lambda *a, **k: "a1")
    _write(product, _COMPILE_WITH_CACHE)

    # act
    result = CliRunner().invoke(_app(product), ["build", "compile"])

    # assert
    assert result.exit_code == 0, result.output
    assert "demo-gradle-cache-a1:/home/gradle/.gradle" in docker_lines[0]


def test_a_cached_command_without_an_instance_section_is_refused_by_name(product, docker_lines):
    # arrange: moving the resolve behind the cache must not SILENTLY drop it - a cache still needs the id
    _write(product, _COMPILE_WITH_CACHE)

    # act
    result = CliRunner().invoke(_app(product), ["build", "compile"])

    # assert: the manifest is named, and the missing section with it
    assert result.exit_code != 0
    assert "instance" in str(result.exception) + result.output


# --- defect 1: the scaffolder receives the version ----------------------------------------------------

def test_the_scaffolder_takes_the_version_from_the_command_line(product):
    # arrange: `**kwargs` never reached the body, so every language raised KeyError: 'version'
    _write(product, _OTHER)

    # act
    result = CliRunner().invoke(_app(product), ["support", "toolchain", "cpp", "19"])

    # assert
    assert result.exit_code == 0, result.output
    written = yaml.safe_load(product.read_text())["groups"]["build"]["commands"]
    assert written["compile"]["with"]["image"] == "silkeh/clang:19"


def test_the_scaffolder_takes_a_version_the_manifest_pins(product):
    # arrange: the design's 1b - the product declares its parameters and the command carries them
    _write(product, _OTHER)
    data = yaml.safe_load(product.read_text())
    data["groups"]["support"]["commands"]["toolchain"] = {
        "task": "support:toolchain", "with": {"version": "20"}}
    product.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    # act
    result = CliRunner().invoke(_app(product), ["support", "toolchain", "cpp"])

    # assert
    assert result.exit_code == 0, result.output
    written = yaml.safe_load(product.read_text())["groups"]["build"]["commands"]
    assert written["compile"]["with"]["image"] == "silkeh/clang:20"


def test_what_the_scaffolder_writes_is_a_manifest_that_then_LOADS_and_RUNS(product, docker_lines):
    # arrange: the design's own test list asks for exactly this round trip, and it never ran
    _write(product, _OTHER)
    assert CliRunner().invoke(_app(product), ["support", "toolchain", "cpp", "19"]).exit_code == 0

    # act: a SECOND assembly, over the file the scaffolder just wrote
    result = CliRunner().invoke(_app(product), ["build", "compile"])

    # assert
    assert result.exit_code == 0, result.output
    assert docker_lines[0][-4:] == ["cmake", "--build", "build", "-j"]
    assert "silkeh/clang:19" in docker_lines[0]


# --- an UNPINNED key is still a real option, so it must refuse the way the gate refuses -------------

def test_a_stray_env_on_the_command_line_is_refused_and_not_a_traceback(product, docker_lines):
    # arrange: no profile pins `env:`, so every scaffolded command carries a real `--env` (the price of
    # binding the manifest's keys as parameters). It has to end in the gate's refusal like everything
    # else - a body that coerces the value first hands the caller a raw ValueError instead
    _write(product, _COMPILE)

    # act
    result = CliRunner().invoke(_app(product), ["build", "compile", "--env", "foo"])

    # assert: refused by name, nothing run, and no exception escaping to the terminal
    assert result.exit_code != 0
    assert docker_lines == []
    assert isinstance(result.exception, SystemExit)
    assert "env" in result.output


def test_a_stray_caches_on_the_command_line_is_refused_the_same_way(product, docker_lines):
    # arrange: the second unpinned key, and it must fail like the first rather than in its own dialect
    _write(product, _COMPILE)

    # act
    result = CliRunner().invoke(_app(product), ["build", "compile", "--caches", "bar"])

    # assert: the shape it wanted, not a report about one CHARACTER of the string it was handed - a
    # coerced value reached `_caches` as a sequence of letters and the refusal then named 'b'
    assert result.exit_code != 0
    assert docker_lines == []
    assert isinstance(result.exception, SystemExit)
    assert "must be a list of" in result.output
