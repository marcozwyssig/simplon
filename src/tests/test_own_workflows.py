"""simplon's OWN workflows, held against simplon's own manifest (si#40).

WHY THIS FILE EXISTS SEPARATELY from test_workflowgen.py. That module proves the generator works on a
fixture. This one proves it is USED - that the files in `.github/workflows/` are the ones
`simplon.yaml` describes, and that none of them has quietly stopped being either generated or
declared. It is the drift gate itself, run by the product's own unit suite, exactly as
`tasks:generate --check` is meant to be.

THE RULE IT KEEPS, and it is this repository's oldest: a tool never used in its own house rots unseen.
The catalogue's head says so about a path resolution that was silently wrong once installed, because
nobody had ever run the kernel the way a consumer does. A workflow generator that simplon shipped and
did not point at itself would be the same thing again, one phase further along - and it would have the
particular sting of being a generator whose whole selling point is that drift becomes visible.

WHAT THIS DOES NOT CLAIM. Not that GitHub runs these files - that takes a real Actions run, and nothing
here can stand in for it. What it holds is everything that would make such a run do the wrong thing
quietly: a workflow that no longer says what the manifest says, and a file in the directory that nothing
at all is responsible for.

THE COMPLEMENT ALREADY EXISTS. tests/test_release_workflow.py, tests/test_type_gate.py and
tests/test_version_source.py assert twenty-odd properties over these same two files, and they were
written against HAND-WRITTEN ones. They are the counter-check on the generated `ci.yml`: it satisfies
every one of them, which is the "gegengeprüft, nicht behauptet" half of si#40's acceptance - the
generated file does what the hand-written file did, measured by assertions written before the generator
existed and by somebody who was not trying to make it pass.
"""

import yaml

from simplon.manifest import catalogue as catalogue_mod
from simplon.manifest import artifactsection
from simplon.tasks import cipipeline, workflowgen, workflows
from simplon.manifest import load as manifest_mod

from conftest import ROOT

MANIFEST = ROOT / "simplon.yaml"

#: The product token the launcher carries, and therefore the one the generated steps must use.
PRODUCT = "simplon"

#: The workflow files this repository has since si#863: ci.yml derived from the command tree, the hand-off canary
#: and the release declared under `workflows:`.
WORKFLOW_PATHS = (".github/workflows/ci.yml", ".github/workflows/handoff-canary.yml", ".github/workflows/release.yml")

#: The reason both halves of the hand-off canary give for staying out of ci.yml (si#863), as simplon.yaml states it.
CANARY_SKIP = "runs across a job boundary in handoff-canary.yml (si#639, spec 5.3a); one job would prove nothing"

#: Why `build model` stays out of ci.yml (si#863 final review), as the derivation states it since si#886: `test
#: generated` (si#746) regenerates every `generated:` entry and diffs it, so a `generated:` producer run before it
#: in the same checkout leaves that gate nothing to find.
MODEL_LEFT_OUT = ("it is the `by:` of a `generated:` entry, which `test generated` (`test:generated`) regenerates "
                  "and compares with the committed tree itself; run before it in the same job, it would leave that "
                  "gate comparing the regenerated tree with itself (si#886)")

#: Why both homebrew leaves stay out of ci.yml, as simplon.yaml states it: the formula refuses a local-version wheel.
HOMEBREW_SKIP = ("needs a tagged commit: the formula refuses a wheel with a local version (si#543), measured on "
                 "ghr-8 in PR #890; the release checks the formula")

#: Where the kernel's job-to-job hand-off (si#344 C.4) puts its archive, as the generated `tar` lines name it.
HANDOFF_PREFIX = workflowgen.HANDOFF_ARCHIVE.split("{artifact}")[0].format()


def _declared():
    """What the `support github workflows` verb assembles (si#863): the declared entries and the derived
    ci.yml, through the verb's own function, so the gate cannot read a narrower set than the verb writes."""
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return workflows.assemble(_loaded(), data, product=PRODUCT, root=ROOT)


def _loaded():
    return manifest_mod.load(MANIFEST.read_text(encoding="utf-8"), catalogue=catalogue_mod.load())


def _report():
    """Every input from MANIFEST, none from the registered ProductContext: which context an earlier test left
    registered must not decide this gate (it did, for #620's first push)."""
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return workflowgen.check(_declared(), ROOT, manifest=_loaded(), product=PRODUCT, source=MANIFEST.name,
                             artifacts=artifactsection.declared(data), reports=workflowgen.report_dir(data))


# --- the gate ------------------------------------------------------------------------------------------


def test_the_committed_workflows_agree_with_the_manifest():
    """THE drift gate, and the reason `--check` exists at all.

    A CLI module that has drifted is caught the moment somebody runs a command it no longer registers.
    A workflow that has drifted is caught by nothing: it runs, it goes green, and it tests whatever it
    happens to say. So the gate has to be somebody's job, and it is this suite's.
    """
    # Arrange / Act
    report = _report()

    # Assert
    assert [drift.path for drift in report.drifted] == [], (
        "a committed workflow no longer says what simplon.yaml says; regenerate with "
        "`./simplon.sh support github workflows`\n" + "\n".join(d.diff for d in report.drifted))


def test_every_file_in_the_workflows_directory_has_an_owner():
    """No file that nothing generates and nothing declares.

    This is the assertion that would have caught agile-cockpit's dead `.gitlab-ci.yml`, and the one that
    catches the next workflow somebody adds here by hand without deciding which of the two it is.
    """
    # Arrange / Act
    report = _report()

    # Assert
    assert report.unmanaged == (), (
        f"these workflow files are named by nothing in {MANIFEST.name}: {list(report.unmanaged)}")


def test_the_gate_is_ruling_on_something():
    """A check over a predicate goes green when nothing matches it, which is how a gate quietly stops
    holding anything. Every file is named, so every one is ruled on - and if a rename makes this red, the
    rename also has to say what now carries the pipeline."""
    # Arrange / Act
    report = _report()

    # Assert
    assert set(report.agreed) | set(report.handwritten) == set(WORKFLOW_PATHS)


# --- the two decisions this repository made, stated as assertions ------------------------------------------


def test_every_workflow_is_generated():
    """si#40's own house. simplon builds and tests itself with the kernel it ships, and generates its
    pipelines with it too - the release since si#491, which retired the hand-written file and its reason
    (two shell scripts and two-thirds prose) by deriving the release job from `release all`, and ci.yml since
    si#863, derived from the command tree with no `workflows: ci:` at all."""
    # Arrange / Act
    generated = [w.path for w in _declared() if w.generated]

    # Assert
    assert sorted(generated) == sorted(WORKFLOW_PATHS)


def test_no_checkout_in_this_repository_leaves_the_job_token_in_git_config():
    """si#622 on the real files: every actions/checkout in every job of every workflow says
    `persist-credentials: false`, so no build or test step can read the job's token out of `.git/config`.
    The pin branch the `image` job pushes goes through `release push-pin`, which hands git the token."""
    # Arrange
    checkouts = []
    for name in (path.rsplit("/", 1)[1] for path in WORKFLOW_PATHS):
        jobs = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))["jobs"]
        checkouts += [(name, job, step) for job, spec in jobs.items() for step in spec["steps"]
                      if str(step.get("uses", "")).startswith("actions/checkout")]

    # Act
    persisting = [f"{name}:{job}" for name, job, step in checkouts
                  if (step.get("with") or {}).get("persist-credentials") is not False]

    # Assert
    assert checkouts, "no checkout found, so this ruled on nothing"
    assert persisting == []


def test_the_generated_workflow_carries_the_prose_it_was_written_with():
    """The reasons stated in simplon.yaml reach the files that act on them.

    si#40's second hard question, checked on the real files rather than on a fixture: a generator that
    dropped the reasoning would have made these files worse than the hand-written ones they replaced. Since
    si#863 ci.yml's prose is the kernel's, so what is held here is this product's own: the canary's note in
    the workflow it moved to, and in ci.yml the reason the canary is not there.
    """
    # Arrange / Act
    canary = (ROOT / ".github" / "workflows" / "handoff-canary.yml").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    # Assert
    assert "The job hand-off canary (si#639)" in canary
    assert _flat(CANARY_SKIP) in _flat(ci)


def test_the_generated_workflow_runs_only_commands_the_manifest_declares():
    """The join, on the real files. Every `run:` in a generated CI file is the launcher plus a command that
    resolves - so a rename anywhere in the command tree breaks generation instead of leaving a file
    calling something that is gone."""
    # Arrange
    manifest = _loaded()

    for name in ("ci.yml", "handoff-canary.yml"):
        doc = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))

        # Act - the kernel's own hand-off lines (si#344 C.4) pack and unpack an archive, and name no command;
        # nor does si#756's reap, which runs before the checkout the launcher lives in
        runs = [step["run"] for job in doc["jobs"].values() for step in job["steps"]
                if "run" in step and HANDOFF_PREFIX not in step["run"]
                and step.get("name") != workflowgen.REAP_NAME]

        # Assert
        assert runs, f"{name} runs no product command at all"
        for run in runs:
            assert run.startswith(f"exec ./{PRODUCT}.sh "), run
            # The command is what precedes its flags (`build image --platform linux/amd64`, si#368).
            workflowgen.resolve_command(manifest, run.split(" ", 2)[2].split(" --", 1)[0], where=f"{name}: {run}")


# --- si#267: what the derivation would produce here, measured against what this repository runs -------


def _ci_steps() -> list[str]:
    """The product commands simplon's ci.yml runs, job by job and in order, as the verb assembles it (si#863).
    Every job, the main one and the Python cells; the kernel's own preparation steps (`support ...`) are not
    leaves and are left out."""
    return [step.command for w in _declared() if w.key == "ci" for job in w.jobs for step in job.steps
            if step.command.split(" ", 1)[0] in cipipeline.CI_PHASES]


def _ci_workflow():
    (ci,) = [w for w in _declared() if w.key == cipipeline.KEY]
    return ci


def _committed(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def test_the_derived_pipeline_over_this_manifest_is_the_unattended_build_and_test_leaves():
    """What `derive` makes of the only manifest this repository can measure: every unattended leaf of
    `build` and `test`, in the manifest's order. It holds WHICH steps, not that each would run bare.

    si#267 asked for a generator that produces a working file rather than a template with holes, and this
    test once claimed exactly that. It stopped being true with si#537 (below), and si#542 decided to accept
    it rather than teach `derive` a required parameter: no reachable manifest uses `derive:`, and the two
    leaves' signatures default to `""`, so nothing `derive` can read says that `""` refuses (Marco,
    2026-11-11). That reopens when a manifest uses `derive:` and a derived leaf refuses its empty default.

    Every other command below was run by hand on this machine before it was added here - the four this
    repository's CI does not run included - and all four exit 0 and leave the tree clean.

    si#371 added `build model` and `test model`, firn's `gen` and `check` over `src/firn/`. Both were run
    the same way on 2026-10-11: both exit 0, and `gen` writes nothing, because there is no template yet.
    si#344 B1 made `build model` an aggregate, so its two leaves stand here in its place: `model-gen`
    writes the catalogue's `kinds:` and `model-mode` makes it world-readable. Run on 2026-10-12 over the
    committed catalogue: both exit 0 and leave the tree clean. B1's final review put `model-guard` before
    them, which refuses hand-written lines outside the catalogue's region; run the same day over the
    committed catalogue, it exits 0 and writes nothing.

    si#344 B2 put `model-whole` between `model-gen` and `model-mode`; it refuses a generated file firn
    deleted or left with only its id line. Run on 2026-10-12 over the committed files: it exits 0 and
    writes nothing. si#400 4b folded `model-whole` and `model-mode` into `model-gen`, which runs
    `build:model` and does both from firn's own report; run on 2026-10-16 over the committed tree, it
    exits 0 and leaves the tree clean. si#561 generated the catalogue whole and removed its region, so
    `model-guard` went and `build model` is that one leaf again; run on 2026-11-14 over the committed
    tree, it exits 0 and leaves the tree clean.

    si#344 C.3 added `test image`, which runs the kernel image built by `build image` and writes its verdict
    record. Run on 2026-10-14 with `--platform linux/amd64` (the arm64 half was not built on this machine):
    it exits 0 and writes `build/test/kernel-image.json`, which is under the ignored `build/`.

    si#522 added `test manifest-model`, which validates the manifest's fresh export against the shipped M2.
    Run on 2026-10-24: it exits 0 and writes only `build/manifest-check/`, under the ignored `build/`.

    si#537 added `build homebrew-formula` and `test homebrew-formula`, and THEY DO NOT RUN BARE, measured
    rather than hidden. Each takes a parameter with no default (`source`, `online`)
    that release.yml binds per step under the dry-run switch, and a derived step passes none: run bare on
    2026-10-24, each exits 1 at once with "source must be 'pypi' ... or 'local' ..., got ''" (and the
    same for `online`). Run as release.yml runs them (`--source local`, `--online false`), they render
    and audit the formula. So a pipeline derived from them bare would go red on those two steps; since
    since si#863 ci.yml leaves both out (test_ci_leaves_the_homebrew_leaves_out), because a dry run on an untagged
    commit is red by design (si#543).

    si#639 added `build handoff-canary` and `test handoff-canary`, the two halves of the job hand-off canary.
    Run bare on 2026-11-13: the first exits 0 and writes `build/handoff-canary.txt`, under the ignored
    `build/`; the second exits 0 after it, and 1 without it ("is not there - nothing handed it over").
    """
    derived = workflowgen.derive(_loaded(), ["build", "test"], where="measurement")

    assert [step.command for step in derived.steps] == [
        "build wheel", "build handoff-canary", "build reference", "build acceptance", "build site", "build image",
        "build homebrew-formula", "build model", "test suite", "test typecheck-python",
        "test release-notes",
        "test report", "test generated", "test image", "test homebrew-formula",
        "test handoff-canary", "test model", "test manifest-model"]


def test_ci_runs_every_unattended_leaf_but_the_canary():
    """THE FINDING si#267 ended on, closed by si#863. Until then this repository ran a hand-picked subset of
    what `derive` produced, and the test here held that the difference stayed visible: `build reference`,
    `build acceptance`, `build site`, `build model`, `test image` and both homebrew leaves were derived but
    not run (spec D13), chiefly so the prose gate could go LAST. Spec 5.2 replaced that ordering argument
    with manifest order, and the job `ci` now runs every unattended leaf of `ci build` and `ci test`.

    The differences left are choices, and each is stated where it is made: the hand-off canary's two halves
    say `ci: { skip: }`, because in one job they would hand nothing over (si#639, spec 5.3a), and ci.yml
    names both under "Left out" with that reason. Their run is handoff-canary.yml's (the test below).
    `build model` stays out for the next test's reason, which the derivation decides (si#886), and both homebrew
    leaves say `ci: { skip: }`, for the reason of test_ci_leaves_the_homebrew_leaves_out.
    """
    derived = [step.command for step in workflowgen.derive(_loaded(), ["build", "test"],
                                                           where="measurement").steps]
    (main,) = [job for job in _ci_workflow().jobs if job.name == cipipeline.KEY]
    ran = {step.command for step in main.steps if step.command.split(" ", 1)[0] in cipipeline.CI_PHASES}
    text = _flat(_committed_text("ci.yml"))

    assert ran == set(derived) - {"build handoff-canary", "test handoff-canary", "build model",
                                  "build homebrew-formula", "test homebrew-formula"}
    for words in ("build handoff-canary", "test handoff-canary"):
        assert _flat(f"`{words}` - {CANARY_SKIP}") in text, words


def test_ci_does_not_regenerate_before_the_staleness_gate():
    """si#863 final review: `test generated` (si#746) regenerates every `generated:` entry and diffs the tree.
    ci.yml derived `build model`, a `generated:` producer, BEFORE it in the same job, so the gate compared the
    regenerated tree with itself and could never go red, and the suite and the type gate ran on the
    regenerated tree rather than the committed one. si#863 opted `build model` out with `ci: { skip: }`; since
    si#886 the derivation leaves every `generated:` producer out when a `test:generated` leaf runs, so the
    manifest carries no skip for it and ci.yml names it under "Left out" with the derivation's reason.
    """
    ran = [line.strip() for line in _committed_text("ci.yml").splitlines() if "./simplon.sh build model" in line]

    assert ran == []
    assert "build model" not in _ci_steps()
    assert not _loaded().commands["build"]["model"].ci_skip
    assert _flat(f"`build model` - {MODEL_LEFT_OUT}") in _flat(_committed_text("ci.yml"))


def test_ci_leaves_the_homebrew_leaves_out():
    """si#863, measured on ghr-8 in PR #890: `build homebrew-formula --source local` is red on every untagged
    commit, by design (si#543: the formula refuses a wheel with a local version `+...`). Both homebrew leaves
    say `ci: { skip: }`, so ci.yml runs neither and names both under "Left out" with that reason; the release
    checks the formula on a tagged commit.
    """
    (job,) = [job for name, job in _committed("ci.yml")["jobs"].items() if name == cipipeline.KEY]
    runs = " ".join(step.get("run", "") for step in job["steps"])
    text = _flat(_committed_text("ci.yml"))

    assert "homebrew-formula" not in runs
    for words in ("build homebrew-formula", "test homebrew-formula"):
        assert _flat(f"`{words}` - {HOMEBREW_SKIP}") in text, words


def _committed_text(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """`text` with the comment markers and every whitespace removed: the renderer wraps a note at its width,
    after a hyphen too (`self-` / `hosted-container`), so a sentence is found by its characters, not its breaks."""
    return "".join(text.replace("#", "").split())


def test_the_command_this_repository_never_puts_in_ci_is_the_one_the_catalogue_marks_attended():
    """The two halves of si#267 meeting: the flag the catalogue declares and the choice this repository
    made years before it existed agree, and they were arrived at independently."""
    loaded = _loaded()

    assert loaded.commands["test"]["walk"].unattended is False
    assert "test walk" not in _ci_steps()


def test_ci_runs_the_suite_on_the_formulas_python():
    """si#537: the Homebrew formula runs simplon on python@3.14, so CI runs the suite there too.

    Held on the committed ci.yml, the file GitHub runs. Since si#863 the job is the kernel's cell for
    `test suite`'s `ci: { python: ["3.14"] }` (si#860), on a hosted runner because the product's runner kind
    sets up no Python.
    """
    job = _committed("ci.yml")["jobs"]["test-suite-python"]
    setup = [step for step in job["steps"] if step.get("uses", "").startswith("actions/setup-python")]

    assert job["runs-on"] == "ubuntu-latest"
    assert [str(v) for v in job["strategy"]["matrix"]["python"]] == ["3.14"]
    assert len(setup) == 1 and setup[0]["with"]["python-version"] == "${{ matrix.python }}"
    assert any(step.get("run", "").endswith("test suite") for step in job["steps"])


def test_the_hosted_suite_job_can_run_linux_arm64_before_the_suite():
    """si#552: the e2e of `test:file` runs a linux/arm64 file under QEMU, and a hosted runner has no
    emulator (measured on PR #557: "Exec format error" on ubuntu-latest). The cell registers one before
    the suite, from the same binfmt image the kernel pins, so the two cannot drift apart. Since si#863 it
    comes from `test suite`'s `ci: { emulates: [linux/arm64] }`."""
    from simplon.adapters.labhost import BINFMT_IMAGE

    steps = _committed("ci.yml")["jobs"]["test-suite-python"]["steps"]
    qemu = [i for i, step in enumerate(steps) if step.get("uses", "").startswith("docker/setup-qemu-action@")]
    suite = next(i for i, step in enumerate(steps) if step.get("run", "").endswith("test suite"))

    assert len(qemu) == 1 and qemu[0] < suite
    step = steps[qemu[0]]
    assert len(step["uses"].split("@", 1)[1]) == 40, "pinned by commit sha"
    assert step["with"]["image"] == BINFMT_IMAGE
    assert "arm64" in step["with"]["platforms"]


def test_ci_runs_on_ghr8():
    """si#863: the main job runs where `self-build` ran, on ghr-8, named by the top-level `runner:`. ghr-8 is an
    LXC container (Marco, 2026-11-25), so its kind `self-hosted-container` registers no emulation (#722): the
    job has no QEMU step and its note names `test suite` as the leaf that needs one registered by hand. It
    reaches docker through the bootstrap, as every self-hosted kind does."""
    job = _committed("ci.yml")["jobs"]["ci"]
    gap = _flat(cipipeline.EMULATION_GAP.format(leaves="`test suite`", verb="names", platforms="linux/arm64",
                                                kind="self-hosted-container"))
    text = _flat(_committed_text("ci.yml"))

    assert job["runs-on"] == "ghr-8"
    assert job["env"]["DELIVERY_DOCKER_BOOTSTRAP"] == "1"
    assert not any(step.get("uses", "").startswith("docker/setup-qemu-action@") for step in job["steps"])
    assert gap in text


def test_the_release_job_can_run_linux_arm64_before_the_suite():
    """si#570: the v0.37.0 dry run went red on si#552's linux/arm64 e2e in the derived release job
    ("Exec format error" on ubuntu-latest). The release workflow's `emulates:` registers it first."""
    from simplon.adapters.labhost import BINFMT_IMAGE

    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["release"]["steps"]
    qemu = [i for i, step in enumerate(steps) if step.get("uses", "").startswith("docker/setup-qemu-action@")]
    suite = next(i for i, step in enumerate(steps) if step.get("run", "").endswith("test suite"))

    assert len(qemu) == 1 and qemu[0] < suite
    assert steps[qemu[0]]["with"] == {"image": BINFMT_IMAGE, "platforms": "linux/arm64"}


def test_the_handoff_canary_crosses_a_job_boundary_in_its_own_workflow():
    """si#639: the canary exists to run the kernel's job-to-job hand-off (si#344 C.4) on every push. Its
    writer and its checker in ONE job would stay green and hand nothing over, so this holds the committed
    handoff-canary.yml to the shape that makes the check mean something: two jobs, the checker's needing the
    writer's, the writer uploading the archive after it writes and the checker unpacking it before it checks.
    The jobs are found by the commands they run, not by their names. Since si#863 that file is the canary's
    own (spec 5.3a): the derived ci.yml would put both halves in one job, so it runs neither."""
    jobs = _committed("handoff-canary.yml")["jobs"]
    ci_runs = [step.get("run", "") for job in _committed("ci.yml")["jobs"].values() for step in job["steps"]]
    assert not [run for run in ci_runs if "handoff-canary" in run]
    archive = workflowgen.HANDOFF_ARCHIVE.format(artifact="handoff-canary")

    def runs(command: str) -> list[str]:
        return [name for name, job in jobs.items()
                if any(step.get("run", "") == f"exec ./{PRODUCT}.sh {command}" for step in job["steps"])]

    writers, checkers = runs("build handoff-canary"), runs("test handoff-canary")
    assert len(writers) == 1 and len(checkers) == 1, (writers, checkers)
    (writer,), (checker,) = writers, checkers
    assert writer != checker, f"job '{writer}' writes and checks the canary, so nothing crosses a job boundary"
    assert jobs[checker].get("needs") in (writer, [writer])

    w_steps = [step.get("run") or step.get("uses", "") for step in jobs[writer]["steps"]]
    c_steps = [step.get("run") or step.get("uses", "") for step in jobs[checker]["steps"]]
    w_at = w_steps.index(f"exec ./{PRODUCT}.sh build handoff-canary")
    c_at = c_steps.index(f"exec ./{PRODUCT}.sh test handoff-canary")
    assert w_steps[w_at + 1] == f'tar -cf "{archive}" build/handoff-canary.txt'
    assert w_steps[w_at + 2].startswith("actions/upload-artifact")
    assert c_steps[c_at - 2].startswith("actions/download-artifact")
    assert c_steps[c_at - 1] == f'tar -xf "{archive}"'


# --- the derived ci.yml, over this manifest (si#858) ---------------------------------------------------

#: The leaves spec section 3 D13 names: the ones a derived ci.yml runs here and the declared one does not. Typed
#: once, as the spec's named population: the test holds that the derivation reaches every one of them.
D13 = ("build reference", "build acceptance", "build site", "build model", "build homebrew-formula", "test image",
       "test homebrew-formula")


def test_simplon_without_its_ci_entry_derives_every_leaf_report_last():
    """si#858's verification on the one manifest this repository can measure, on the committed manifest since
    si#863 removed `workflows: ci:` from it: the switch derives ci.yml from the command tree.

    It holds WHICH steps and in WHICH order - every unattended `ci build` and `ci test` leaf in manifest order
    completed by their ports, the `after_all` leaf (`test report`) last - not that each would run bare: two of
    the D13 leaves do not (si#537, above) and say `ci: { skip: }`.
    """
    text = MANIFEST.read_text(encoding="utf-8")
    manifest = _loaded()
    data = yaml.safe_load(text)

    (ci,) = [w for w in cipipeline.workflows(manifest, data, product=PRODUCT) if w.key == cipipeline.KEY]
    rendered = workflowgen.render(ci, manifest=manifest, product=PRODUCT, source=MANIFEST.name,
                                  artifacts=artifactsection.declared(data), reports=workflowgen.report_dir(data))
    job = yaml.safe_load(rendered)["jobs"][cipipeline.KEY]
    launcher = f"exec ./{PRODUCT}.sh "

    def words_of(run: str) -> str:
        # A leaf's `ci: params:` (si#863) follows its words as `--name value` or after `--`; this test is about
        # which leaves run in which order, so it reads the words. test_own_image holds the parameters.
        return run.removeprefix(launcher).split(" --", 1)[0]

    ran = [words_of(step["run"]) for step in job["steps"] if step.get("run", "").startswith(launcher)]
    leaves = [words for words in ran if words.split(" ", 1)[0] in cipipeline.CI_PHASES]
    selection = cipipeline.select(manifest, artifacts=artifactsection.declared(data), data=data)
    expected = [leaf.words for leaf in selection.leaves if not leaf.spec.after_all] + ["test report"]
    # The manifest's own order, walked here rather than read off `select`, so a sort that reshuffles what no
    # port forces turns this red too: no leaf of this manifest consumes from a later one, so the two agree.
    walked = [f"{group.replace('.', ' ')} {name}" for group, members in manifest.commands.items()
              for name in members]
    ordered = set(expected[:-1])
    in_manifest_order = [words for words in walked if words in ordered]
    by_leaf = {words_of(step["run"]): step for step in job["steps"] if step.get("run", "").startswith(launcher)}
    prepared = [step["id"] for step in job["steps"] if step.get("id", "").startswith("prepare_")]
    gate = "${{ " + " && ".join(["!cancelled()", *(f"steps.{i}.outcome == 'success'" for i in prepared)]) + " }}"
    (upload,) = [step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact")]

    assert expected != ["test report"]
    assert leaves == expected
    assert leaves[:-1] == in_manifest_order
    # `build model` (test_ci_does_not_regenerate_before_the_staleness_gate) and both homebrew leaves
    # (test_ci_leaves_the_homebrew_leaves_out) are the D13 leaves ci.yml leaves out on purpose.
    assert [words for words in D13 if words not in leaves] == [
        "build model", "build homebrew-formula", "test homebrew-formula"]
    assert "test walk" not in leaves
    assert f"# `test walk` - {cipipeline.ATTENDED}" in rendered
    assert "workflows" not in data or "ci" not in data["workflows"]
    assert job["runs-on"] == "ghr-8"
    # The gate (spec 5.2): on ghr-8 simplon places all three preparation steps, the first leaf waits on them by
    # GitHub's default, every later one runs unless cancelled or a preparation went red, the report always.
    assert prepared == ["prepare_docker", "prepare_disk", "prepare_install"]
    assert "if" not in by_leaf[leaves[0]]
    # A consumer also waits for its producer (si#858 final review): `test image` runs the image `build image`
    # builds, so a red producer leaves it skipped rather than red on the missing image.
    producer = by_leaf["build image"]["id"]
    consumer = gate.removesuffix(" }}") + f" && steps.{producer}.outcome == 'success' }}}}"
    assert producer == "leaf_build_image"
    assert by_leaf["test image"].get("if") == consumer
    # Every other later leaf has the gate, and at most the success of leaves that ran before it.
    for at, words in enumerate(leaves[1:-1], start=1):
        extra = by_leaf[words]["if"].removeprefix(gate.removesuffix(" }}")).removesuffix(" }}")
        earlier = {by_leaf[before].get("id") for before in leaves[:at]}
        assert all(clause.removeprefix("steps.").removesuffix(".outcome == 'success'") in earlier
                   for clause in extra.split(" && ")[1:]), (words, extra)
        assert extra == "" or extra.startswith(" && steps.leaf_"), (words, extra)
    assert by_leaf["test report"].get("if") == "always()"
    assert upload.get("if") == "always()"


def test_the_gate_assembles_the_workflows_the_verb_writes():
    """si#863: with `workflows.ci` gone from the manifest, ci.yml is still among what the gate reads, because
    the verb derives it; and the files on disk are all accounted for by that set."""
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assembled = workflows.assemble(_loaded(), data, product=PRODUCT, root=ROOT)
    (ci,) = [w for w in assembled if w.path == ".github/workflows/ci.yml"]
    assert "ci" not in data.get("workflows", {})
    assert ci.derived and ci.generated
    assert workflowgen.unmanaged(assembled, ROOT) == ()
