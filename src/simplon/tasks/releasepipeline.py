"""The dispatch release workflow of a product, derived through the firn workflow model (si#862).

The release counterpart of `cipipeline`: `derive` decides the release job from the release aggregate and builds
it as the generated model (`simplon.model.workflowschema`), and `to_workflow` turns that model into the
`workflowgen.Workflow` the renderer writes. Until si#862 the job was assembled from `workflowgen`'s own
dataclasses (`workflowgen._release`), the one derived job the model did not describe; the rendered release.yml
is byte-identical across the move (`test_release_workflow.py`).

WHAT A RELEASE DERIVES, and why the product writes none of it (si#490). A release is started by dispatch with the
version typed and a dry run by default (si#463 D2); the version reaches a script only through the job's `env:` and
a command only as `"$RELEASE_VERSION"` (si#488), never as `${{ inputs.* }}` inside a `run:` line. The ORDER is the
aggregate's: `plan_for` already returns it in the one order rule 8 accepts (si#489), so nothing here orders
anything.

WHAT THE PRODUCT STILL SAYS, AND WHERE (si#862). The release is the ReleaseCommand's: one aggregate under
`ci: release:` that `produces: { release: <artifact> }` derives release.yml, and its `ci: { runner:, emulates:,
timeout_minutes: }` say the job's machine, emulation and time limit, as the same keys do on a CI leaf. The
`workflows: release:` entry no longer names the aggregate (`workflowgen._refuse_retired_keys`): it adds jobs that
land beside the derived `release` job, with the workflow's `permissions:`, `env:` and `note:`, and its
`handwritten:` switches the derivation off. PyPI's Trusted Publishing is bound to the file name release.yml, which is
why the added jobs land in this file and not in one of their own.

THE WEBSITE, WHEN `website: { pages: release, by: <command> }` SAYS SO (si#862). Two more jobs, `docs` and `pages`,
carry si#851's boundary: `docs` builds the site with the named command and uploads it as its LAST step, and `pages`
deploys it in a job of its own. The switch is explicit (`site.pages`), because a `website:` alone is also firn's,
with no Pages, and biz-cockpit's, served from another repository.
"""
from __future__ import annotations

import shlex
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import replace

from simplon.manifest import artifactsection, runners, signatures, sources
from simplon.manifest import load as manifest_load
from simplon.manifest.load import Manifest
from simplon.model import task, workflowschema
from simplon.model.command import CiRelease, EnvValue, ReleaseCommand, TaskCommand
from simplon.tasks import cipipeline, site, workflowgen
from simplon.tasks.docs_site import DocsSite

#: The kernel steps of the release job, in the model as `Step.kernel_step` and written by `to_workflow`.
PASS_SECRETS_CHECK = "pass-secrets-check"
EMULATION = "emulation"
PROVISION = "provision"
RELEASE_CUT = "release-cut"
RELEASE_STAMP = "release-stamp"
DRY_RUN_TAIL = "dry-run-tail"
REPORT = "report"
#: si#862: the kernel steps of the derived `docs` and `pages` jobs.
RELEASE_ON_ORIGIN = "release-on-origin"
PAGES_UPLOAD = "pages-upload"
PAGES_CONFIGURE = "pages-configure"
PAGES_DEPLOY = "pages-deploy"

#: si#789: the job that runs the release's producers once more, on the tag (design 4.3).
ARTIFACTS_JOB = "artifacts"

#: si#862: the two jobs `website: { pages: release }` derives, and the deploy's environment and queue.
DOCS_JOB = "docs"
PAGES_JOB = "pages"
PAGES_ENVIRONMENT = "github-pages"
#: One deploy at a time per repository, never cancelled: Pages has one site, whatever workflow deploys it.
PAGES_CONCURRENCY = "pages"
DEPLOYMENT_ID = "deployment"
#: The upload's one parameter: the directory `site.declared` builds the site into.
PATH_PARAM = "path"

#: The dry-run tail's one parameter: the path of the notes the release would have published, if a leaf writes any.
NOTES_PARAM = "notes"

_DRY_RUN = "${{ inputs.dry_run }}"
_NOT_DRY_RUN = "${{ !inputs.dry_run }}"
_GITHUB_TOKEN = "GITHUB_TOKEN"
#: The dispatch's version, in the `env:` of every derived job that reads it (si#488: never `${{ inputs.* }}` in `run:`).
_VERSION_ENV = workflowschema.RunnerEnv(env_name=workflowgen.RELEASE_ENV, env_value="${{ inputs.version }}")
_SECRET = "${{{{ secrets.{name} }}}}"

#: The dispatch a release is started by (si#490): the version, exactly as its tag will be, and a rehearsal switch
#: that defaults to rehearsing.
TRIGGER = workflowschema.Trigger(event="dispatch", dispatch_input=(
    workflowschema.DispatchInput(input_name="version", description="The version to release, exactly as its tag "
                                 "will be: vX.Y.Z", input_type="string", required=True),
    workflowschema.DispatchInput(input_name="dry_run", description="Rehearse: build and check everything, publish "
                                 "nothing", input_type="boolean", required=True, default_value="true")))

#: The scopes the release itself needs: `contents` to push the tag and write the GitHub Release, `packages`
#: to push an image, `actions` (read) for `release:check` to read main's CI runs (si#789). They are the
#: derived release job's own (si#719), never the workflow's.
_RELEASE_PERMISSIONS: Mapping[str, str] = {"contents": "write", "packages": "write", "actions": "read"}
#: One release per version, never cancelled in progress. The converter's, as `cipipeline.to_workflow` decides a
#: cadence file's: the renderer decides concurrency per kind of file (workflow.firn, `Workflow`).
_RELEASE_CONCURRENCY: Mapping[str, object] = {"group": "${{ github.workflow }}-${{ inputs.version }}",
                                              "cancel-in-progress": False}

#: si#718: said above the step, because a reader asks why the release job starts with `help`.
PROVISION_NOTE = """si#718: the launcher's first run in a fresh checkout builds its venv - a pip install of the
kernel and its dependencies from PyPI. Here it happens in a step with no token in its environment, so
nothing that install runs sits beside the GITHUB_TOKEN a `token: github` step gets. `help` loads the
manifest and prints the command list; a launcher that cannot provision is red here, before the cut."""

PASS_SECRETS_CHECK_NAME = "Check the secrets every `env: pass:` step needs"

#: si#862: the derived jobs' own prose, written above each in release.yml.
DOCS_NOTE = """The website, built by `{by}` (`website: by:`) and uploaded into the run for the `pages`
job. {waits} The upload is the LAST step (si#851): no step after it can turn this job red with the artifact already made, so a
rerun of this job never meets an upload of its own. It reads the checkout and writes nothing outside the
run; the Pages rights are the `pages` job's."""
#: The docs job's order, said in its note: after the jobs `website: after:` names, or after the release alone.
DOCS_AFTER = ("It waits for `release` and for {jobs} (`website: after:`), so the site never documents a version "
              "they have not published.")
DOCS_ALONE = ("It waits for `release` alone (`website: after:` names none), so a job declared beside it that fails "
              "for its own reason does not skip the site.")

PAGES_NOTE = """The deploy of what `docs` uploaded, in a job of its own (si#851). In one job with the
upload, `deploy-pages` listed the run's artifacts one second after the upload, found no `github-pages`
and failed (runs 44901604309, 44938156739). Here the job boundary stands between the upload and the
listing. A red deploy is rerun with "Re-run failed jobs", which reruns this job alone and not `docs`,
which succeeded, so the rerun finds the one artifact the run holds. A FULL rerun uploads a second one,
and the deploy refuses two: delete the run's `github-pages` artifacts first. On GitHub-hosted Ubuntu
whatever the release's machine: no checkout, nothing here reads the repository, and no container is
started, so no reap step sits beside `pages: write` and `id-token: write`, which are this job's alone
(si#719), as are the environment and the queue."""

CUT_NOTE = """si#491 decision 5, on a REHEARSAL only: the release job's own cut. A dry run pushes no
tag, and without it the site would be built for a version the checkout does not carry."""

#: si#789: the artifacts job's own wording of the two tag steps, because what it builds is not the site.
ARTIFACTS_CUT_NOTE = """si#789, on a REHEARSAL only: the release job's own cut. A dry run pushes no tag, and
without it the producers below would build a `.devN` version, not the one a real run releases."""

ARTIFACTS_ON_ORIGIN_NOTE = """On a REAL run nothing is cut here: the producers build the tag the release job
pushed, fetched by the checkout, and a tag deleted from origin after a failed publish is not re-created
here - the rule of the `docs` job (si#491, final review, Important 2)."""

ARTIFACTS_NOTE = """si#789: the release's producers, run once more on the tag after `release` cut it (design 4.3):
the build and test leaves whose artifact a step of this workflow consumes, and the tests whose evidence
one consumes. The suite and the other gates do not run again: the green `main` run `release check`
required is their evidence. With the release's parameters, not `ci: params:`, so what is built and
tested here is what the release publishes; on the release's machine and emulation."""

ON_ORIGIN_NOTE = """On a REAL run nothing is cut here: the tag must be the one the release job pushed,
fetched by the checkout. A tag deleted from origin after a failed publish, then "Re-run failed jobs",
would otherwise be re-created locally and documented as a version origin does not carry - the final
review of si#491 (Important 2)."""

PASS_SECRETS_NOTE = """si#836: a step below whose command declares `env: pass:` reads those names from this
repository's Actions secrets, in its own `env:` and no other step's. A secret that is not set would reach
the step as an empty string, and a dry run skips a publishing step, so without this check the real run
would stop there after the tag and whatever published before it (si#574's lesson). The expression
`secrets.X != ''` hands this step true or false, never the value; it runs on a dry run too.
Checked here: {needs}."""


def runner_of(ci: CiRelease) -> tuple[runners.Runner, tuple[str, ...]] | None:
    """si#862: the `(Runner, labels)` a release aggregate's `ci: { runner: }` named, as `runners.resolve` returns
    them, or None when it named none (the derivation's default machine is then its own choice)."""
    if not ci.runner_kind:
        return None
    return runners.resolve({"kind": ci.runner_kind, "labels": list(ci.runner_labels)}, "release ci:")


#: si#862: every ReleaseCommand as `(<command words>, spec)`, in manifest order; the loader's walk, shared.
release_commands = manifest_load.release_commands


def _the_release(manifest: Manifest) -> tuple[str, ReleaseCommand]:
    """The one ReleaseCommand release.yml derives from.

    Two are refused, an EXPRESSION rule (si#862, decision 3 of its plan): each would derive release.yml, a file has
    one owner, and a second dispatch file would need a name the kernel would have to invent. Measured before it
    shipped: no reachable manifest declares two. Reopens when one does."""
    found = release_commands(manifest)
    if len(found) > 1:
        raise ValueError(
            f"the manifest declares more than one release aggregate ({', '.join(repr(w) for w, _ in found)}), and "
            f"each would derive release.yml - keep one under `ci: release:` that `produces: {{ release: <artifact> "
            f"}}`; the others can be plain aggregates")
    return found[0]


def _refuse_beside_the_release(entry: workflowgen.Workflow, words: str) -> None:
    """What `workflows: release:` may not say beside the derived release, because the derivation says it.

    Two are EXPRESSION rules (si#490 decision 1, kept by si#862): a second trigger would start a release with no
    `version`, and its own concurrency would let two runs of one version cancel each other mid-release. The rest
    are DIAGNOSES: a rollout and a release would derive two triggers into one file, a job named `release` or
    `artifacts` (si#789) is a derived job's name, a `RELEASE_VERSION` in `env:` would be shadowed by the dispatch input's, and a
    `permissions:` that is not a mapping is no default for any job."""
    where = f"workflow '{entry.key}'"
    if entry.declared_on and not entry.flow:
        raise ValueError(
            f"{where}: declares `on:`, and the trigger is derived from the release aggregate '{words}' - a dispatch "
            f"with the version and a dry run; remove `on:`")
    if entry.extras.get("concurrency") is not None:
        raise ValueError(
            f"{where}: `concurrency:` is derived from the release aggregate '{words}' - one release per version, "
            f"never cancelled in progress; remove it")
    if entry.flow:
        raise ValueError(
            f"{where}: declares `{workflowgen.FLOW_KEY}:`, and release.yml is the release of '{words}' - one "
            f"workflow is a rollout or a release, not both, because each derives its own trigger; give the "
            f"rollout its own workflow")
    if any(job.name == workflowgen.RELEASE_JOB for job in entry.jobs):
        raise ValueError(
            f"{where}: declares a job '{workflowgen.RELEASE_JOB}', and the derived job is named "
            f"'{workflowgen.RELEASE_JOB}' - rename yours; it can still `needs: {workflowgen.RELEASE_JOB}`")
    if any(job.name == ARTIFACTS_JOB for job in entry.jobs):
        # si#789: refused whether or not `producers_on_tag` selects anything, so the rule does not depend on it.
        raise ValueError(
            f"{where}: declares a job '{ARTIFACTS_JOB}', the name of the derived job that runs the release's "
            f"producers on the tag (si#789) - rename yours; it can still `needs: {ARTIFACTS_JOB}`")
    env = entry.extras.get("env")
    if isinstance(env, Mapping) and workflowgen.RELEASE_ENV in env:
        raise ValueError(
            f"{where}: sets {workflowgen.RELEASE_ENV} in `env:`, and {workflowgen.RELEASE_ENV} is the dispatch "
            f"input's - the job sets it from `inputs.version`, and a second value would be shadowed with nobody told")
    declared = entry.extras.get("permissions")
    if declared is not None and not isinstance(declared, Mapping):
        raise ValueError(
            f"{where}: `permissions:` beside the release is a mapping of scope -> level, the default of every job "
            f"without its own block; got '{declared}'")


def refuse_an_empty_entry(entry: workflowgen.Workflow) -> None:
    """si#862: a `workflows: release:` entry with no `jobs:` and no `flow:` where the manifest has no
    ReleaseCommand. Beside one, the entry's `permissions:`, `env:`, `name:` and `note:` shape the derived release;
    without one it is an ordinary workflow with no job, which GitHub refuses. A DIAGNOSIS, the one
    `workflowgen._workflow` gives every other key, with the reading it is missing named."""
    if not entry.generated or entry.flow or entry.jobs:
        return
    raise ValueError(
        f"workflow '{entry.key}': `jobs:` must be a non-empty mapping of job name -> its declaration, or "
        f"`{workflowgen.FLOW_KEY}:` must name the environments this release is rolled out to - an entry without "
        f"either only shapes the release derived from a ReleaseCommand (an aggregate under `ci: release:` that "
        f"`produces: {{ release: <artifact> }}`), and this manifest declares none")


def refuse_ci_where_handwritten(manifest: Manifest, entry: workflowgen.Workflow) -> None:
    """si#862: with `workflows: release: { handwritten: }` the kernel derives no release.yml, so a ReleaseCommand's
    `ci:` key would shape nothing. A DIAGNOSIS, as `cipipeline._refuse_variants_nobody_derives` is for a CI leaf."""
    for words, spec in release_commands(manifest):
        written = [key for key, value in (("runner", spec.ci.runner_kind), ("emulates", spec.ci.emulates),
                                          ("timeout_minutes", spec.ci.timeout_minutes)) if value not in ("", (), None)]
        if written:
            raise ValueError(
                f"the release aggregate '{words}' declares `ci: {written[0]}:`, and `{workflowgen.SECTION}: "
                f"{entry.key}:` is `handwritten:`, so the kernel derives no release.yml and the key would shape "
                f"nothing. Take the key off, or drop the `handwritten:` entry so the kernel derives release.yml and "
                f"reads it")


def derive(manifest: Manifest, data: Mapping[str, object],
           entry: workflowgen.Workflow | None) -> workflowschema.Workflow:
    """The release workflow of the manifest's ReleaseCommand as the model: one dispatch trigger, the workflow's
    token scopes and the job `release`: the cut, the stamp, the aggregate's plan, the dry-run tail and the
    test archive; then `artifacts` (si#789, `producers_on_tag`) and the website's jobs, where they apply. `entry`
    is the declared `workflows: release:` (its jobs are `to_workflow`'s), or None.

    The job's machine is the aggregate's `ci: { runner: }`, or else the product's top-level `runner:`
    (`cipipeline.runner_of`); its emulation and time limit are `ci: { emulates:, timeout_minutes: }`, the limit
    `workflowgen.RELEASE_TIMEOUT_MINUTES` when unwritten.

    What a plan cannot say is added here:
    - a leaf whose task `publishes:` is skipped on a dry run (si#490 decision 5);
    - a `token: github` leaf, and only that one, gets the run's GITHUB_TOKEN (decision 4);
    - a leaf whose command declares `env: pass:` gets those names from the secrets of the same names, in its
      own `env:`, and the job checks first that each is set (si#836, `_passed_secrets`);
    - a leaf taking a passed parameter unpinned gets it as `"$RELEASE_VERSION"`, the CLI's own reading of
      `passes:` (si#433), so `release all --tag v1.4.0` and the workflow hand the same leaves the version;
    - a first leaf that is `release:check` runs BEFORE the cut and the stamp (si#487). Left after them, a
      malformed version or another version tag at HEAD would fail in shell with the shell's message, and the
      check would never speak. The load holds it first (`ports._check_release_first`), so this moves no
      member past another; it only places the two kernel steps after it.

    Every refusal here is a DIAGNOSIS: each names a release that would reach no command with its version, hand a
    leaf a wrong value, release past a member nobody ran, or register an emulator where it cannot be registered
    (#722). `_the_release` and `_refuse_beside_the_release` say their own kinds."""
    words, spec = _the_release(manifest)
    if entry is not None:
        _refuse_beside_the_release(entry, words)
    where = f"release aggregate '{words}'"
    if "tag" not in spec.passes:
        raise ValueError(
            f"{where} passes no `tag`, so the version would reach no command - add `passes: [tag]` to the aggregate")
    if set(spec.passes) - {"tag"}:
        # A dispatch carries the version and nothing else, so every other passed parameter would reach its
        # leaves with no value - or, handed the version, with a wrong one.
        raise ValueError(
            f"{where} passes {', '.join(sorted(set(spec.passes) - {'tag'}))}, and a dispatch carries only the "
            f"version - pin it on the leaves with `with:`, or pass only `tag`")
    runner, labels = runner_of(spec.ci) or cipipeline.runner_of(data)
    workflowgen._refuse_emulates_where_it_cannot_register(runner, spec.ci.emulates, where)
    artifacts = artifactsection.declared(data)
    leaves = workflowgen._leaves(manifest, workflowgen.Step(command=words), where)
    lifted = 1 if leaves and leaves[0][1].task == workflowgen.RELEASE_CHECK else 0
    steps: list[workflowschema.Step] = []
    notes = ""
    passes_secrets = False
    for line, leaf in leaves:
        if leaf.unattended is not True:
            raise ValueError(
                f"{where}: '{line}' cannot run in the release job unattended - it declares `unattended: "
                f"{str(leaf.unattended).lower() if leaf.unattended is not None else '(nothing)'}`, and a "
                f"release member that is skipped would release past it; declare `unattended: true` or "
                f"take it out of '{words}'")
        step = _leaf_step(leaf, line, where)
        passes_secrets = passes_secrets or _passes_secrets(step)
        steps.append(step)
        if leaf.task == "release:notes" and not notes:
            produced = leaf.produces.get("release-notes", ())
            notes = artifacts[produced[0]].path if produced and produced[0] in artifacts else ""
    steps[lifted:lifted] = [workflowschema.Step(kernel_step=RELEASE_CUT), workflowschema.Step(kernel_step=RELEASE_STAMP)]
    steps.insert(0, workflowschema.Step(kernel_step=PROVISION))
    if spec.ci.emulates:
        steps.insert(0, workflowschema.Step(kernel_step=EMULATION))
    if passes_secrets:
        steps.insert(0, workflowschema.Step(kernel_step=PASS_SECRETS_CHECK))
    steps.append(workflowschema.Step(kernel_step=DRY_RUN_TAIL, condition=_DRY_RUN, params=(
        (workflowschema.StepParam(param_name=NOTES_PARAM, param_value=notes),) if notes else ())))
    # si#789: the archive follows the tests the PLAN runs. A product that places `test:report` but whose
    # aggregate runs no test has nothing in this job to report on, and the step would archive an empty report.
    if any(leaf.task == workflowgen.REPORT_TASK for _, leaf in leaves):
        steps.append(workflowschema.Step(kernel_step=REPORT))
    # si#719: the workflow-level block is the default of every job without its own (`contents: read` when the
    # product declares none); the job's own block replaces it, so a scope the product declared there is carried
    # over and the scopes the release needs win over a lower default.
    declared = entry.extras.get("permissions") if entry is not None else None
    workflow_scopes = ({str(k): str(v) for k, v in declared.items()} if isinstance(declared, Mapping)
                       else dict(workflowgen._WORKFLOW_DEFAULT_PERMISSIONS))
    job = workflowschema.Job(
        key=workflowgen.RELEASE_JOB,
        runner=workflowschema.Runner(kind=workflowschema.RUNNER_KINDS[runner.kind], labels=labels),
        step=tuple(steps), timeout_minutes=spec.ci.timeout_minutes or workflowgen.RELEASE_TIMEOUT_MINUTES,
        permission=_permissions({**workflow_scopes, **_RELEASE_PERMISSIONS}),
        env=(_VERSION_ENV,))
    path = entry.path if entry is not None else f"{workflowgen.DIRECTORY}/{workflowgen.RELEASE_KEY}.yml"
    title = entry.name if entry is not None else workflowgen.RELEASE_KEY
    return workflowschema.Workflow(path=path, title=title, trigger=(TRIGGER,),
                                   job=(job, *_artifacts(manifest, data, spec, job),
                                        *_website(manifest, data, entry, job)),
                                   permission=_permissions(workflow_scopes))


def _leaf_step(leaf: TaskCommand, line: str, where: str) -> workflowschema.Step:
    """One release-workflow leaf as a model step, the same in `release` and `artifacts` (si#789):
    - skipped on a dry run where its task `publishes:` (si#490 decision 5);
    - the run's GITHUB_TOKEN for a `token: github` leaf, and only that one (decision 4);
    - its `env: pass:` names from the secrets of the same names, in its own `env:` (si#836, `_passed_secrets`);
    - a passed `tag` taken unpinned bound to `"$RELEASE_VERSION"`, the CLI's own reading of `passes:` (si#433).
    No `ci: params:`: those narrow a CI run, and the release builds what it publishes."""
    env = [workflowschema.RunnerEnv(env_name=_GITHUB_TOKEN, env_value=_SECRET.format(name=_GITHUB_TOKEN))
           ] if leaf.token == "github" else []
    passed = _passed_secrets(leaf, line, where)
    env += [workflowschema.RunnerEnv(env_name=secret, env_value=value) for secret, value in passed.items()]
    # The takers are read off the body's signature, as `cli.receivers` reads them, so the command line
    # and the workflow hand the same leaves the version (final review of si#490, Important 3).
    takes = {p.name for p in signatures.bindable(task.body_of(leaf, where=f"{where}, '{line}'"))}
    params = ((workflowschema.StepParam(param_name="tag", param_env=workflowgen.RELEASE_ENV),)
              if "tag" in takes and "tag" not in leaf.with_ else ())
    return workflowschema.Step(command=leaf, command_words=line, condition=_NOT_DRY_RUN if leaf.publishes else "",
                               env=tuple(env), params=params)


def _passes_secrets(step: workflowschema.Step) -> bool:
    """True when the step reads a secret through `env: pass:` (the run's GITHUB_TOKEN is not one)."""
    return any(env.env_name != _GITHUB_TOKEN and env.env_value == _SECRET.format(name=env.env_name)
               for env in step.env)


def _release_steps(manifest: Manifest, data: Mapping[str, object]) -> tuple[workflowgen.Step, ...]:
    """The command steps release.yml runs, as `workflowgen.Step`s: the ReleaseCommand, every command step of the
    jobs declared under `workflows: release:`, and the `website: by:` of the derived `docs` job; () where no
    release.yml is derived (no ReleaseCommand, or a `handwritten:` release)."""
    found = release_commands(manifest)
    if not found:
        return ()
    entry = next((w for w in workflowgen.parse(data) if w.key == workflowgen.RELEASE_KEY), None)
    if entry is not None and not entry.generated:
        return ()
    words, _ = found[0]
    steps = [workflowgen.Step(command=words), *(step for job in (entry.jobs if entry is not None else ())
                                                for step in job.steps)]
    pages = site.pages(data)
    if pages is not None:
        steps.append(workflowgen.Step(command=pages.by))
    return tuple(steps)


def _release_leaves(manifest: Manifest, data: Mapping[str, object]) -> tuple[TaskCommand, ...]:
    """Every leaf `_release_steps` runs, with repeats where two steps run one leaf."""
    return tuple(leaf for step in _release_steps(manifest, data)
                 for _, leaf in workflowgen._leaves(manifest, step, f"workflow '{workflowgen.RELEASE_KEY}'"))


def producers_on_tag(manifest: Manifest, data: Mapping[str, object]) -> tuple[cipipeline.Leaf, ...]:
    """si#789 (design 4.3): the CI leaves the release runs once more, on the tag, in `cipipeline.order`.

    A leaf is a candidate when ci.yml would run it: a `TaskCommand` in a `build` or `test` group of the CI area
    that declares no `ci: { skip: }` and runs unattended. Selected are the candidates that produce an artifact a
    leaf of release.yml consumes, registry images included,
    and with it the `evidence:` a release step consumes, which a test produces; then the producers of what a
    selected leaf consumes, so the job never consumes what nothing in this run built.

    What release.yml makes itself is not rebuilt here (design 4.3): everything any of its steps produces. The
    release aggregate's plan runs in the `release` job before this one, so what it makes is on the tag already
    (the notes, the tag, and a product whose aggregate still builds what it publishes); what a job declared under
    `workflows: release:` makes, such as simplon's formula, rendered after the PyPI upload, is made there and
    would otherwise be built twice in one run. () where no release.yml is derived or nothing it consumes is built
    by CI; then there is no `artifacts` job.

    A candidate that has not ruled on `unattended:` is refused where it is selected
    (`workflowgen.require_unattended`), because whether it may run on the tag is then unknown."""
    leaves = _release_leaves(manifest, data)
    if not leaves:
        return ()
    candidates: list[cipipeline.Leaf] = []
    for group, members in manifest.commands.items():
        if group.split(".", 1)[0] not in cipipeline.CI_PHASES or manifest.area_of(group) != "ci":
            continue
        for name, spec in members.items():
            if isinstance(spec, TaskCommand) and not spec.ci_skip:
                candidates.append(cipipeline.Leaf(cipipeline._words(group, name), spec))
    own = {artifact for leaf in leaves for names in leaf.produces.values() for artifact in names}
    wanted = {artifact for leaf in leaves for names in leaf.consumes.values() for artifact in names} - own
    chosen: list[cipipeline.Leaf] = []
    while True:
        found = [leaf for leaf in candidates if leaf not in chosen
                 and any(artifact in wanted for names in leaf.spec.produces.values() for artifact in names)]
        for leaf in found:
            workflowgen.require_unattended(leaf.spec, leaf.words, f"release job '{ARTIFACTS_JOB}'")
        found = [leaf for leaf in found if leaf.spec.unattended]
        if not found:
            break
        chosen += found
        wanted |= {artifact for leaf in found for names in leaf.spec.consumes.values() for artifact in names} - own
    return cipipeline.order([leaf for leaf in candidates if leaf in chosen])


def _artifacts(manifest: Manifest, data: Mapping[str, object], spec: ReleaseCommand,
               release: workflowschema.Job) -> tuple[workflowschema.Job, ...]:
    """si#789: the `artifacts` job, or none when `producers_on_tag` selects nothing.

    After `release`, on its machine with its emulation and time limit: the launcher provisioned first, the tag
    cut on a rehearsal and required on origin on a real run, the build stamped, then each selected leaf as the
    release job runs its own (`_leaf_step`)."""
    selected = producers_on_tag(manifest, data)
    if not selected:
        return ()
    where = f"release job '{ARTIFACTS_JOB}'"
    leaves = [_leaf_step(leaf.spec, leaf.words, where) for leaf in selected]
    steps = [workflowschema.Step(kernel_step=PROVISION)]
    if spec.ci.emulates:
        steps.append(workflowschema.Step(kernel_step=EMULATION))
    if any(_passes_secrets(step) for step in leaves):
        steps.insert(0, workflowschema.Step(kernel_step=PASS_SECRETS_CHECK))
    steps += [workflowschema.Step(kernel_step=RELEASE_CUT, condition=_DRY_RUN),
              workflowschema.Step(kernel_step=RELEASE_ON_ORIGIN, condition=_NOT_DRY_RUN),
              workflowschema.Step(kernel_step=RELEASE_STAMP), *leaves]
    return (workflowschema.Job(key=ARTIFACTS_JOB, runner=release.runner, needs=(release,), step=tuple(steps),
                               timeout_minutes=release.timeout_minutes,
                               permission=_permissions({"contents": "read"}), env=(_VERSION_ENV,)),)


def refuse_pages_nobody_derives(data: Mapping[str, object], why: str) -> None:
    """si#862: `website: { pages: release }` where no release.yml is derived - no ReleaseCommand, or a
    `handwritten:` release. The switch would deploy nothing. A DIAGNOSIS, as `refuse_ci_where_handwritten` is for
    the ReleaseCommand's `ci:`; `why` names which of the two."""
    if site.pages(data) is None:
        return
    raise ValueError(
        f"'{site.SECTION}: pages: {site.PAGES_RELEASE}' deploys the site from the derived release.yml, and {why}, "
        f"so nothing would deploy it. Take `pages:` and `by:` out of `{site.SECTION}:`, or let the kernel derive "
        f"release.yml")


def _website(manifest: Manifest, data: Mapping[str, object], entry: workflowgen.Workflow | None,
             release: workflowschema.Job) -> tuple[workflowschema.Job, ...]:
    """si#862: the `docs` and `pages` jobs `website: { pages: release, by: }` switches on, or none.

    `docs` runs on the release job's machine and needs `release` and the jobs `website: after:` names, in its order
    (Marco, 2026-11-26): a product says which declared job the site must not get ahead of (simplon: `publish`, so
    it never documents a version nobody can install), and a job it does not name cannot skip the site by failing
    for its own reason (si#638's missing tap secret). The declared jobs are the entry's, not the model's, so they
    are named by key in `needs_declared`. `pages` runs on GitHub-hosted Ubuntu whatever the
    release's machine (plan decision 2): it takes no checkout and starts no container, so it needs none of a
    self-hosted kind's steps and gets no reap step beside its `pages: write`.

    Every refusal is a DIAGNOSIS: an `after:` name that is no declared job (GitHub refuses a `needs:` naming no
    job in the file), `by:` naming nothing (`workflowgen.resolve_command`), a leaf of it that would
    stop or be skipped with nobody watching, a plan with no `docs:site` leaf (the upload would publish a directory
    nothing built), and a declared job named `docs` or `pages` (the derived job's name, as for `release`)."""
    pages = site.pages(data)
    if pages is None:
        return ()
    where = f"'{site.SECTION}: by: {pages.by}'"
    for name in (DOCS_JOB, PAGES_JOB):
        if entry is not None and any(job.name == name for job in entry.jobs):
            raise ValueError(
                f"workflow '{entry.key}': declares a job '{name}', and `{site.SECTION}: pages: {pages.on}` derives "
                f"a job named '{name}' - rename yours, or take `pages:` out of `{site.SECTION}:` and keep your own")
    group, name = workflowgen.resolve_command(manifest, pages.by, where=where)
    leaves = workflowgen._leaves(manifest, workflowgen.Step(command=pages.by), where)
    for line, leaf in leaves:
        workflowgen.require_unattended(leaf, line, where)
        if leaf.unattended is not True:
            raise ValueError(
                f"{where}: '{line}' cannot run in the docs job unattended - it declares `unattended: false`, and "
                f"the job would stop there or publish a site without it; name a command that plans only "
                f"unattended leaves")
    if not any(leaf.task == DocsSite.KEY for _, leaf in leaves):
        raise ValueError(
            f"{where}: '{pages.by}' plans no `{DocsSite.KEY}` leaf, so the docs job would upload a "
            f"directory nothing built - name the command that builds the site (a `{DocsSite.KEY}` leaf, "
            f"or an aggregate that plans one)")
    output = site.declared(data).output
    declared = [job.name for job in entry.jobs] if entry is not None else []
    for after in pages.after:
        if after not in declared:
            raise ValueError(
                f"'{site.SECTION}: after:' names '{after}', which is no job declared beside the release - declared: "
                f"{', '.join(declared) or '(none)'}; name a job under `{workflowgen.SECTION}: "
                f"{workflowgen.RELEASE_KEY}: jobs:`, or take it out of `after:`")
    docs = workflowschema.Job(
        key=DOCS_JOB, runner=release.runner, needs=(release,), needs_declared=pages.after,
        # Bounded like the release job on the same machine: a docs build that hangs is no verdict.
        timeout_minutes=release.timeout_minutes,
        permission=_permissions({"contents": "read"}), env=(_VERSION_ENV,),
        step=(workflowschema.Step(kernel_step=RELEASE_CUT, condition=_DRY_RUN),
              workflowschema.Step(kernel_step=RELEASE_ON_ORIGIN, condition=_NOT_DRY_RUN),
              workflowschema.Step(command=manifest.commands[group][name], command_words=pages.by),
              workflowschema.Step(kernel_step=PAGES_UPLOAD,
                                  params=(workflowschema.StepParam(param_name=PATH_PARAM, param_value=output),))))
    deploy = workflowschema.Job(
        key=PAGES_JOB, runner=workflowschema.Runner(kind=workflowschema.RUNNER_KINDS["github-ubuntu"],
                                                    labels=tuple(runners.TABLE["github-ubuntu"].labels)),
        needs=(docs,), no_checkout=True, starts_no_container=True, concurrency=PAGES_CONCURRENCY,
        permission=_permissions({"pages": "write", "id-token": "write"}),
        environment=workflowschema.DeployEnvironment(environment_name=PAGES_ENVIRONMENT,
                                                     url=f"${{{{ steps.{DEPLOYMENT_ID}.outputs.page_url }}}}"),
        step=(workflowschema.Step(kernel_step=PAGES_CONFIGURE),
              workflowschema.Step(kernel_step=PAGES_DEPLOY, step_id=DEPLOYMENT_ID, condition=_NOT_DRY_RUN)))
    return docs, deploy


def _permissions(scopes: Mapping[str, str]) -> tuple[workflowschema.Permission, ...]:
    return tuple(workflowschema.Permission(scope=scope, access=access) for scope, access in scopes.items())


def _passed_secrets(leaf: TaskCommand, words: str, where: str) -> dict[str, str]:
    """si#836: the `env:` a release leaf's `env: pass:` names get - each from the secret of the same name.

    A name the kernel already fills for this leaf keeps that mechanism and is left out here: GITHUB_TOKEN
    for a `token: github` leaf (the run's own token, si#490 decision 4) and GH_APP_TOKEN for a `token: app`
    leaf (the token the derived step mints, si#534). Any other `GITHUB_*` name is refused, a DIAGNOSIS: GitHub
    refuses a secret by that name, so the check would be red on every run with nothing that could be set, and
    GITHUB_TOKEN itself reaches only a leaf that declares `token: github`."""
    filled = {"github": {_GITHUB_TOKEN}, "app": {workflowgen.APP_TOKEN_ENV}}.get(str(leaf.token), set())
    out: dict[str, str] = {}
    for name in leaf.env_pass:
        if name in filled:
            continue
        if name.upper().startswith("GITHUB_"):
            raise ValueError(
                f"{where}: '{words}' passes {name} in `env: pass:`, and the release workflow fills such a name "
                f"from the Actions secret of the same name - but GitHub refuses a secret named GITHUB_*, so "
                f"there is nothing to set. The run's own GITHUB_TOKEN reaches a leaf whose task declares "
                f"`token: github`; take {name} out of `env: pass:`, or declare `token: github` for that")
        out[name] = _SECRET.format(name=name)
    return out


def to_workflow(model: workflowschema.Workflow, manifest: Manifest, data: Mapping[str, object],
                entry: workflowgen.Workflow | None, *, product: str) -> workflowgen.Workflow:
    """The model as the `workflowgen.Workflow` the renderer writes: the model's trigger, its token scopes and the
    release concurrency, and the converted `release` job and `artifacts` (si#789) ahead of the entry's own jobs,
    which come after the tag and may take what `artifacts` built, with the entry's other
    workflow-level keys and its note. The website's `docs` and `pages` (si#862) follow the entry's jobs, which `docs`
    waits for. `release` is set, because `workflowgen.render` inserts the app-secrets check
    (si#574) into the job of that name; `derived` is set, because the job is."""
    words, spec = _the_release(manifest)
    base = entry if entry is not None else workflowgen.Workflow(key=workflowgen.RELEASE_KEY, path=model.path,
                                                               sources=sources.declared(data))
    own = {key: value for key, value in base.extras.items() if key != "permissions"}
    extras = {"permissions": {p.scope: p.access for p in model.permission}, "concurrency": dict(_RELEASE_CONCURRENCY),
              **own}
    release, *rest = (_to_job(job, manifest, data, spec, product=product) for job in model.job)
    artifacts = tuple(job for job in rest if job.name == ARTIFACTS_JOB)
    website = tuple(job for job in rest if job.name != ARTIFACTS_JOB)
    return replace(base, name=model.title, path=model.path, on=cipipeline._on(model.trigger), extras=extras,
                   jobs=(release, *artifacts, *base.jobs, *website), release=words, derived=True)


def _to_job(job: workflowschema.Job, manifest: Manifest, data: Mapping[str, object], spec: ReleaseCommand, *,
            product: str) -> workflowgen.Job:
    """One model job as the renderer's job. The kernel steps are written here, and the command steps carry the
    model's `if:`, `env:` and `id:` in the order GitHub's own documentation writes them. The machine is the
    model's runner: its labels, and the kind's own `env:` beside the job's. `spec` is the release aggregate
    `to_workflow` derived from, whose `ci: emulates:` the emulation step registers."""
    reporting = any(step.kernel_step == REPORT for step in job.step)
    # The test archive is the release job's alone (si#509); `docs` and `pages` ask nothing of it.
    archive, unarchived = (workflowgen._release_archive(manifest, workflowgen.report_dir(data) if reporting else "")
                           if job.key == workflowgen.RELEASE_JOB else ((), ""))
    needed: dict[str, list[str]] = {}
    for step in job.step:
        if step.command is not None:
            for env in step.env:
                if env.env_name != _GITHUB_TOKEN and env.env_value == _SECRET.format(name=env.env_name):
                    needed.setdefault(env.env_name, []).append(step.command_words)
    steps: list[workflowgen.Step] = []
    for step in job.step:
        if step.kernel_step == PASS_SECRETS_CHECK:
            steps.append(_pass_secrets_check(needed))
        elif step.kernel_step == EMULATION:
            steps.append(workflowgen.emulation_step(spec.ci.emulates)._replace(note=(
                f"si#570: the release aggregate's `ci: {workflowgen.EMULATES_KEY}:`, registered before anything in "
                f"the job runs.")))
        elif step.kernel_step == PROVISION:
            steps.append(workflowgen.Step(verbatim={"name": "Provision the launcher before any step holds a token",
                                                    "run": f"{workflowgen.launcher(product)} help"},
                                          note=PROVISION_NOTE))
        elif step.kernel_step == RELEASE_CUT:
            # The release job cuts on every run; the docs job only on a rehearsal (si#862), with the note.
            cut_note = ARTIFACTS_CUT_NOTE if job.key == ARTIFACTS_JOB else CUT_NOTE
            steps.append(workflowgen.Step(verbatim={"name": "Cut the tag in this checkout",
                                                    **({"if": step.condition} if step.condition else {}),
                                                    "run": workflowgen.RELEASE_CUT},
                                          note=cut_note if step.condition else ""))
        elif step.kernel_step == RELEASE_ON_ORIGIN:
            steps.append(workflowgen.Step(verbatim={"name": "The tag is on origin at this commit",
                                                    "if": step.condition, "run": workflowgen.RELEASE_ON_ORIGIN},
                                          note=ARTIFACTS_ON_ORIGIN_NOTE if job.key == ARTIFACTS_JOB
                                          else ON_ORIGIN_NOTE))
        elif step.kernel_step == PAGES_UPLOAD:
            path = next(p.param_value for p in step.params if p.param_name == PATH_PARAM)
            steps.append(workflowgen.Step(verbatim={"uses": workflowgen.UPLOAD_PAGES_ACTION, "with": {"path": path}}))
        elif step.kernel_step == PAGES_CONFIGURE:
            steps.append(workflowgen.Step(verbatim={"uses": workflowgen.CONFIGURE_PAGES_ACTION,
                                                    "with": {"enablement": True}}))
        elif step.kernel_step == PAGES_DEPLOY:
            steps.append(workflowgen.Step(verbatim={"id": step.step_id, "uses": workflowgen.DEPLOY_PAGES_ACTION,
                                                    "if": step.condition}))
        elif step.kernel_step == RELEASE_STAMP:
            steps.append(workflowgen.Step(verbatim={"name": "The build will be stamped with the version",
                                                    "run": workflowgen.RELEASE_STAMP}))
        elif step.kernel_step == DRY_RUN_TAIL:
            notes = next((p.param_value for p in step.params if p.param_name == NOTES_PARAM), "")
            tail = (f'echo "dry run: no draft, no tag pushed, nothing published. The notes for $RELEASE_VERSION:"\n'
                    f"cat {shlex.quote(notes)}\n" if notes else
                    'echo "dry run: nothing published for $RELEASE_VERSION"\n')
            steps.append(workflowgen.Step(verbatim={"name": "What a release would have published (dry run)",
                                                    "if": step.condition, "run": tail}))
        elif step.kernel_step == REPORT:
            steps.extend(archive)
        else:
            modifiers: dict[str, object] = {"id": step.step_id} if step.step_id else {}
            if step.condition:
                modifiers["if"] = step.condition
            if step.env:
                modifiers["env"] = {env.env_name: env.env_value for env in step.env}
            params = {param.param_name: EnvValue(param.param_env) if param.param_env else param.param_value
                      for param in step.params}
            steps.append(workflowgen.Step(command=step.command_words, modifiers=modifiers, params=params))
    kind = next(name for name, known in workflowschema.RUNNER_KINDS.items() if known is job.runner.kind)
    runner = runners.TABLE[kind]
    labels = job.runner.labels
    extras: dict[str, object] = {}
    if job.needs or job.needs_declared:
        needs = [*(need.key for need in job.needs), *job.needs_declared]
        extras["needs"] = needs[0] if len(needs) == 1 else needs
    if job.environment is not None:
        extras["environment"] = ({"name": job.environment.environment_name, "url": job.environment.url}
                                 if job.environment.url else job.environment.environment_name)
    if job.permission:
        extras["permissions"] = {p.scope: p.access for p in job.permission}
    if job.concurrency:
        extras["concurrency"] = {"group": job.concurrency, "cancel-in-progress": False}
    if job.timeout_minutes is not None:
        extras["timeout-minutes"] = job.timeout_minutes
    # The kind's own settings after the job's (si#267), as the entry's runner env stood before si#862.
    job_env = {**{env.env_name: env.env_value for env in job.env}, **runner.env}
    if job_env:
        extras["env"] = job_env
    note = {workflowgen.RELEASE_JOB: unarchived, ARTIFACTS_JOB: ARTIFACTS_NOTE, DOCS_JOB: _docs_note(job),
            PAGES_JOB: PAGES_NOTE}
    return workflowgen.Job(name=job.key, runs_on=labels[0] if len(labels) == 1 else labels, steps=tuple(steps),
                           runner=runner, note=note.get(job.key, ""), checkout=not job.no_checkout, extras=extras,
                           reap=not job.starts_no_container)


def _docs_note(job: workflowschema.Job) -> str:
    """The docs job's note: the command its one command step runs (`website: by:`) and what it waits for."""
    by = next((step.command_words for step in job.step if step.command is not None), "")
    jobs = ", ".join(f"`{name}`" for name in job.needs_declared)
    waits = DOCS_AFTER.format(jobs=jobs) if jobs else DOCS_ALONE
    return "\n".join(textwrap.wrap(DOCS_NOTE.format(by=by, waits=waits).replace("\n", " "), 104,
                                   break_on_hyphens=False))


def _pass_secrets_check(needed: Mapping[str, Sequence[str]]) -> workflowgen.Step:
    """si#836: the release job's step that is red when a secret an `env: pass:` leaf is handed is not set,
    naming each missing one. si#574's shape: true/false, never the value."""
    names = list(needed)
    leaves = list(dict.fromkeys(words for words_of in needed.values() for words in words_of))
    script = ['missing=""',
              *(f'[ "$SET_{name}" = true ] || missing="$missing {name}"' for name in names),
              'if [ -n "$missing" ]; then',
              f'  echo "::error::not set in this repository\'s Actions secrets:$missing - the release job hands '
              f'each to the step whose command passes it in env: pass: ({", ".join(leaves)}), si#836; store '
              f'them under Settings, Secrets and variables, Actions before releasing"',
              "  exit 1",
              "fi",
              f'echo "set: {" ".join(names)}"']
    needs = "; ".join(f"'{words}' passes {', '.join(n for n in names if words in needed[n])}" for words in leaves)
    return workflowgen.Step(verbatim={"name": PASS_SECRETS_CHECK_NAME,
                                      "env": {f"SET_{name}": f"${{{{ secrets.{name} != '' }}}}" for name in names},
                                      "run": "\n".join(script) + "\n"},
                            note=PASS_SECRETS_NOTE.format(needs=needs))
