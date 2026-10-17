"""si#400 4c: every command's body runs through a Task class - the generated one for a catalogue coordinate,
one the kernel builds from `impl:` for a product task.

AAA; the name states the behaviour under test.
"""
import pytest

from simplon.manifest import catalogue, signatures
from simplon.model import command, task
from simplon.model.task import mangle
from simplon.tasks.image import build


def test_a_catalogue_coordinate_names_its_generated_class():
    # act / assert
    assert task.class_ref("build:image") == "simplon.tasks.build_image:BuildImage"
    assert task.class_ref("support:ci-arm64") == "simplon.tasks.support_ci_arm64:SupportCiArm64"


@pytest.mark.parametrize("coordinate", sorted(catalogue.load().tasks))
def test_every_class_ref_resolves_to_the_class_carrying_that_coordinate(coordinate):
    # act
    cls = task.task_class(task.class_ref(coordinate), coordinate, where=coordinate)

    # assert
    assert issubclass(cls, task.Task) and cls.KEY == coordinate


def test_a_generated_class_is_returned_as_it_is():
    # arrange
    from simplon.tasks.build_image import BuildImage

    # act / assert
    assert task.task_class("simplon.tasks.build_image:BuildImage", "build:image", where="x") is BuildImage


def test_a_product_function_becomes_a_class_whose_run_binds_what_the_function_binds():
    # act
    cls = task.task_class("simplon.tasks.image:build", "pack", where="build pack")

    # assert
    assert issubclass(cls, task.Task) and cls.KEY == "pack"
    assert signatures.bindable(cls().run) == signatures.bindable(build)


def test_two_product_tasks_on_one_function_are_two_classes():
    # act: si#420 - one body, two tasks; keyed by impl, the second would borrow the first's KEY
    a = task.task_class("simplon.tasks.image:build", "pack-a", where="a")
    b = task.task_class("simplon.tasks.image:build", "pack-b", where="b")

    # assert
    assert a is not b and (a.KEY, b.KEY) == ("pack-a", "pack-b")


def test_a_reference_to_something_that_is_no_body_is_refused_naming_the_command():
    # act / assert: a module constant is neither a Task nor a function - running it is not an option
    with pytest.raises(ValueError, match=r"build pack.*PORTS"):
        task.task_class("simplon.model.artifactschema:PORTS", "pack", where="build pack")


def test_the_class_name_follows_firns_class_name():
    # act / assert: the Tasks template's className, in Python (4b holds the generated side)
    assert [task.class_name(mangle(c)) for c in ("build:image", "test:typecheck-python", "vcs:auth-scopes")] == [
        "BuildImage", "TestTypecheckPython", "VcsAuthScopes"]


def test_assembling_the_cli_imports_the_class_of_a_placed_coordinate_only():
    # arrange: `cli.assemble` resolves every placed leaf's body eagerly, so the classes of the coordinates a
    # manifest places are imported on start (measured 2026-10-16: `--help` 0.319 s before 4c, 0.314 s after);
    # what must not happen is importing EVERY class module (+0.19 s, 411 modules). Counted by a meta-path
    # hook - an earlier count through PYTHONPROFILEIMPORTTIME under ./simplon.sh said 8 and was wrong (30).
    import subprocess
    import sys
    from conftest import ROOT
    from simplon.model.task import mangle
    hook = ("import sys, importlib.abc, runpy, io, contextlib\n"
            "seen = set()\n"
            "class H(importlib.abc.MetaPathFinder):\n"
            "    def find_spec(self, name, path, target=None):\n"
            "        seen.add(name)\n"
            "sys.meta_path.insert(0, H())\n"
            "sys.argv = ['simplon', '--help']\n"
            f"sys.path.insert(0, {str(ROOT / 'deploy' / 'orchestrator' / 'src' / 'python')!r})\n"
            "with contextlib.redirect_stdout(io.StringIO()):\n"
            "    try:\n"
            "        runpy.run_module('orchestrator', run_name='__main__')\n"
            "    except SystemExit:\n"
            "        pass\n"
            "print('\\n'.join(sorted(seen)))\n")
    classes = {f"simplon.tasks.{mangle(c)}" for c in catalogue.load().tasks}
    from simplon.manifest import load as manifest_mod
    mf = manifest_mod.load((ROOT / "simplon.yaml").read_text(encoding="utf-8"), catalogue=catalogue.load())
    # placed by simplon.yaml or by the catalogue's own tree: the merged manifest's commands
    placed = {f"simplon.tasks.{mangle(spec.task)}" for members in mf.commands.values()
              for spec in members.values() if isinstance(spec, command.TaskCommand) and spec.task}

    # act
    run = subprocess.run([sys.executable, "-c", hook], cwd=ROOT, capture_output=True, text=True)
    imported = set(run.stdout.split()) & classes

    # assert
    assert run.returncode == 0, run.stderr[-2000:]
    assert imported, "no class module was imported - the hook measured nothing"
    assert imported <= placed, sorted(imported - placed)
    assert imported < classes

def test_the_catalogue_names_each_coordinates_class_and_no_function():
    # act
    tasks = catalogue.load().tasks

    # assert
    assert {c: s["impl"] for c, s in tasks.items()} == {c: task.class_ref(c) for c in tasks}


def test_a_catalogue_file_whose_task_writes_impl_is_refused(tmp_path):
    # arrange: the body lives in the task's class (si#400 4c); a written `impl:` is a second source of it
    path = tmp_path / "catalogue.yaml"
    path.write_text("tasks:\n  vcs:push:\n    impl: simplon.tasks.vcs:push\n    help: x\n", encoding="utf-8")

    # act / assert
    with pytest.raises(ValueError, match=r"`impl:` is written on vcs:push"):
        catalogue.load(path)


def test_a_catalogue_built_from_text_keeps_the_impl_it_writes():
    # arrange: test catalogues name bodies no model generates (`build:wheel` is no catalogue task)
    text = "tasks:\n  build:wheel:\n    impl: orchestrator.cli:build_wheel\n    help: x\n"

    # act / assert
    assert catalogue.loads(text).tasks["build:wheel"]["impl"] == "orchestrator.cli:build_wheel"


_RAW = """product: demo
tasks:
  pre: { impl: "simplon.tasks.cidisk:preflight", help: x }
  gate-a: { impl: "simplon.tasks.testrun:gate", help: y }
ci:
  build:
    commands:
      pre: { task: pre }
  test:
    commands:
      gate-a: { task: gate-a }
      gate-b: { task: "test:gate" }
"""


def test_a_product_task_naming_a_kernel_function_counts_as_that_coordinate_placed():
    # arrange: since si#400 4c a coordinate's impl names its class while such a product task names the
    # function; the readers that compare bodies by impl must still see one body (4c final review, I1)
    from simplon.manifest import load as manifest_mod, runners
    from simplon.tasks import cliref, workflowgen
    mf = manifest_mod.load(_RAW, catalogue=catalogue.load())

    # act
    placed = workflowgen._placed(mf, runners.PREFLIGHT[1])
    unplaced = {c for c, *_ in cliref.unplaced(mf, catalogue.load())}

    # assert
    assert placed == "build pre"
    assert "support:ci-disk-preflight" not in unplaced


def test_one_body_behind_a_product_task_and_a_coordinate_is_one_shared_impl():
    # arrange: the cli gives commands that share a body their own `help:` (netctl#1406)
    from simplon.manifest import load as manifest_mod

    # act
    mf = manifest_mod.load(_RAW, catalogue=catalogue.load())
    a, b = mf.commands["test"]["gate-a"].impl, mf.commands["test"]["gate-b"].impl

    # assert
    assert task.body_identity(a) == task.body_identity(b)
