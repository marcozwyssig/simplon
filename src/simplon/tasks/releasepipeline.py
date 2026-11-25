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

THE MACHINE, FOR NOW, IS THE ENTRY'S (si#862 task 1, removed by task 3). simplon's `runs-on: ubuntu-latest` names
no runner kind, so the model's `Runner` cannot hold the machine the job runs on; `to_workflow` writes the entry's
`runs-on:`/`runner:` and its runner env, and `emulates:` and `timeout_minutes:` are still read beside `release:`.
"""
from __future__ import annotations

import shlex
from collections.abc import Mapping, Sequence
from dataclasses import replace

from simplon.manifest import artifactsection, runners, signatures
from simplon.manifest.load import Manifest
from simplon.model import task, workflowschema
from simplon.model.command import CiRelease, EnvValue, ReleaseCommand, TaskCommand
from simplon.tasks import cipipeline, workflowgen

#: The kernel steps of the release job, in the model as `Step.kernel_step` and written by `to_workflow`.
PASS_SECRETS_CHECK = "pass-secrets-check"
EMULATION = "emulation"
PROVISION = "provision"
RELEASE_CUT = "release-cut"
RELEASE_STAMP = "release-stamp"
DRY_RUN_TAIL = "dry-run-tail"
REPORT = "report"

#: The dry-run tail's one parameter: the path of the notes the release would have published, if a leaf writes any.
NOTES_PARAM = "notes"

_DRY_RUN = "${{ inputs.dry_run }}"
_NOT_DRY_RUN = "${{ !inputs.dry_run }}"
_GITHUB_TOKEN = "GITHUB_TOKEN"
_SECRET = "${{{{ secrets.{name} }}}}"

#: The dispatch a release is started by (si#490): the version, exactly as its tag will be, and a rehearsal switch
#: that defaults to rehearsing.
TRIGGER = workflowschema.Trigger(event="dispatch", dispatch_input=(
    workflowschema.DispatchInput(input_name="version", description="The version to release, exactly as its tag "
                                 "will be: vX.Y.Z", input_type="string", required=True),
    workflowschema.DispatchInput(input_name="dry_run", description="Rehearse: build and check everything, publish "
                                 "nothing", input_type="boolean", required=True, default_value="true")))

#: The scopes the release itself needs: `contents` to push the tag and write the GitHub Release, `packages`
#: to push an image. They are the derived release job's own (si#719), never the workflow's.
_RELEASE_PERMISSIONS: Mapping[str, str] = {"contents": "write", "packages": "write"}
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


def derive(manifest: Manifest, data: Mapping[str, object], entry: workflowgen.Workflow) -> workflowschema.Workflow:
    """The release workflow of `entry` (a `workflows:` entry with `release:`) as the model: one dispatch trigger,
    the workflow's token scopes and the one job, `release`: the cut, the stamp, the aggregate's plan, the dry-run
    tail and the test archive.

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

    Every refusal is a DIAGNOSIS: each names a release that would reach no command with its version, hand a
    leaf a wrong value, or release past a member nobody ran."""
    where = f"workflow '{entry.key}'"
    group, name = workflowgen.resolve_command(manifest, entry.release, where=where)
    spec = manifest.commands[group][name]
    if not isinstance(spec, ReleaseCommand):
        raise ValueError(
            f"{where}: `{workflowgen.RELEASE_KEY}:` names '{entry.release}', which is not a release aggregate - name "
            f"the aggregate under `ci: release:` that `produces: {{ release: <artifact> }}`")
    if "tag" not in spec.passes:
        raise ValueError(
            f"{where}: '{entry.release}' passes no `tag`, so the version would reach no command - add "
            f"`passes: [tag]` to the aggregate")
    if set(spec.passes) - {"tag"}:
        # A dispatch carries the version and nothing else, so every other passed parameter would reach its
        # leaves with no value - or, handed the version, with a wrong one.
        raise ValueError(
            f"{where}: '{entry.release}' passes {', '.join(sorted(set(spec.passes) - {'tag'}))}, and a "
            f"dispatch carries only the version - pin it on the leaves with `with:`, or pass only `tag`")
    artifacts = artifactsection.declared(data)
    leaves = workflowgen._leaves(manifest, workflowgen.Step(command=entry.release), where)
    lifted = 1 if leaves and leaves[0][1].task == workflowgen.RELEASE_CHECK else 0
    steps: list[workflowschema.Step] = []
    notes = ""
    passes_secrets = False
    for words, leaf in leaves:
        if leaf.unattended is not True:
            raise ValueError(
                f"{where}: '{words}' cannot run in the release job unattended - it declares `unattended: "
                f"{str(leaf.unattended).lower() if leaf.unattended is not None else '(nothing)'}`, and a "
                f"release member that is skipped would release past it; declare `unattended: true` or "
                f"take it out of '{entry.release}'")
        env = [workflowschema.RunnerEnv(env_name=_GITHUB_TOKEN, env_value=_SECRET.format(name=_GITHUB_TOKEN))
               ] if leaf.token == "github" else []
        passed = _passed_secrets(leaf, words, where)
        env += [workflowschema.RunnerEnv(env_name=secret, env_value=value) for secret, value in passed.items()]
        passes_secrets = passes_secrets or bool(passed)
        # The takers are read off the body's signature, as `cli.receivers` reads them, so the command line
        # and the workflow hand the same leaves the version (final review of si#490, Important 3).
        takes = {p.name for p in signatures.bindable(task.body_of(leaf, where=f"{where}, '{words}'"))}
        params = ((workflowschema.StepParam(param_name="tag", param_env=workflowgen.RELEASE_ENV),)
                  if "tag" in takes and "tag" not in leaf.with_ else ())
        steps.append(workflowschema.Step(command=leaf, condition=_NOT_DRY_RUN if leaf.publishes else "",
                                         env=tuple(env), params=params))
        if leaf.task == "release:notes" and not notes:
            produced = leaf.produces.get("release-notes", ())
            notes = artifacts[produced[0]].path if produced and produced[0] in artifacts else ""
    steps[lifted:lifted] = [workflowschema.Step(kernel_step=RELEASE_CUT), workflowschema.Step(kernel_step=RELEASE_STAMP)]
    steps.insert(0, workflowschema.Step(kernel_step=PROVISION))
    if entry.emulates:
        steps.insert(0, workflowschema.Step(kernel_step=EMULATION))
    if passes_secrets:
        steps.insert(0, workflowschema.Step(kernel_step=PASS_SECRETS_CHECK))
    steps.append(workflowschema.Step(kernel_step=DRY_RUN_TAIL, condition=_DRY_RUN, params=(
        (workflowschema.StepParam(param_name=NOTES_PARAM, param_value=notes),) if notes else ())))
    if any(isinstance(member, TaskCommand) and member.task == workflowgen.REPORT_TASK
           for members in manifest.commands.values() for member in members.values()):
        steps.append(workflowschema.Step(kernel_step=REPORT))
    # si#719: the workflow-level block is the default of every job without its own (`workflowgen._release_extras`
    # reads it, `contents: read` when the product declares none); the job's own block replaces it, so a scope the
    # product declared there is carried over and the scopes the release needs win over a lower default.
    declared = entry.extras.get("permissions")
    workflow_scopes = {str(k): str(v) for k, v in declared.items()} if isinstance(declared, Mapping) else {}
    job = workflowschema.Job(
        key=workflowgen.RELEASE_JOB, runner=_interim_runner(entry), step=tuple(steps),
        timeout_minutes=entry.timeout_minutes,
        permission=_permissions({**workflow_scopes, **_RELEASE_PERMISSIONS}),
        env=(workflowschema.RunnerEnv(env_name=workflowgen.RELEASE_ENV, env_value="${{ inputs.version }}"),))
    return workflowschema.Workflow(path=entry.path, title=entry.name, trigger=(TRIGGER,), job=(job,),
                                   permission=_permissions(workflow_scopes))


def _permissions(scopes: Mapping[str, str]) -> tuple[workflowschema.Permission, ...]:
    return tuple(workflowschema.Permission(scope=scope, access=access) for scope, access in scopes.items())


def _interim_runner(entry: workflowgen.Workflow) -> workflowschema.Runner:
    """The model's machine for the release job until si#862 task 3, which `to_workflow` does not read: the kind the
    entry's `runner:` names, or, for a machine named by `runs-on:` alone, `github-ubuntu`, the kind an absent
    `runner:` means everywhere else (`cipipeline.runner_of`), with the labels as written."""
    runs_on = entry.rollout_runs_on
    labels = (runs_on,) if isinstance(runs_on, str) else tuple(runs_on) if isinstance(runs_on, tuple) else ()
    kind = entry.rollout_runner.kind if entry.rollout_runner is not None else "github-ubuntu"
    return workflowschema.Runner(kind=workflowschema.RUNNER_KINDS[kind], labels=labels)


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
                entry: workflowgen.Workflow, *, product: str) -> workflowgen.Workflow:
    """The model as the `workflowgen.Workflow` the renderer writes: the entry, with the model's trigger, the
    model's token scopes and the release concurrency, and the converted `release` job ahead of the entry's own
    jobs. `release` stays set, because `workflowgen.render` inserts the app-secrets check (si#574) into the job of
    that name; `derived` is set, because the job is."""
    own = {key: value for key, value in entry.extras.items() if key != "permissions"}
    extras = {"permissions": {p.scope: p.access for p in model.permission}, "concurrency": dict(_RELEASE_CONCURRENCY),
              **own}
    jobs = tuple(_to_job(job, manifest, data, entry, product=product) for job in model.job)
    return replace(entry, name=model.title, path=model.path, on=cipipeline._on(model.trigger), extras=extras,
                   jobs=(*jobs, *entry.jobs), derived=True)


def _to_job(job: workflowschema.Job, manifest: Manifest, data: Mapping[str, object], entry: workflowgen.Workflow,
            *, product: str) -> workflowgen.Job:
    """One model job as the renderer's job. The kernel steps are written here, and the command steps carry the
    model's `if:`, `env:` and `id:` in the order GitHub's own documentation writes them."""
    where = f"workflow '{entry.key}'"
    words = {id(spec): line for line, spec in
             workflowgen._leaves(manifest, workflowgen.Step(command=entry.release), where)}
    reporting = any(step.kernel_step == REPORT for step in job.step)
    archive, unarchived = workflowgen._release_archive(manifest, workflowgen.report_dir(data) if reporting else None)
    needed: dict[str, list[str]] = {}
    for step in job.step:
        if step.command is not None:
            for env in step.env:
                if env.env_name != _GITHUB_TOKEN and env.env_value == _SECRET.format(name=env.env_name):
                    needed.setdefault(env.env_name, []).append(words[id(step.command)])
    steps: list[workflowgen.Step] = []
    for step in job.step:
        if step.kernel_step == PASS_SECRETS_CHECK:
            steps.append(_pass_secrets_check(needed))
        elif step.kernel_step == EMULATION:
            steps.append(workflowgen.emulation_step(entry.emulates)._replace(note=(
                f"si#570: the workflow's `{workflowgen.EMULATES_KEY}:`, registered before anything in the job runs.")))
        elif step.kernel_step == PROVISION:
            steps.append(workflowgen.Step(verbatim={"name": "Provision the launcher before any step holds a token",
                                                    "run": f"{workflowgen.launcher(product)} help"},
                                          note=PROVISION_NOTE))
        elif step.kernel_step == RELEASE_CUT:
            steps.append(workflowgen.Step(verbatim={"name": "Cut the tag in this checkout",
                                                    "run": workflowgen.RELEASE_CUT}))
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
            steps.append(workflowgen.Step(command=words[id(step.command)], modifiers=modifiers, params=params))
    extras: dict[str, object] = {}
    if job.environment is not None:
        extras["environment"] = ({"name": job.environment.environment_name, "url": job.environment.url}
                                 if job.environment.url else job.environment.environment_name)
    if job.permission:
        extras["permissions"] = {p.scope: p.access for p in job.permission}
    if job.timeout_minutes is not None:
        extras["timeout-minutes"] = job.timeout_minutes
    extras["env"] = {**{env.env_name: env.env_value for env in job.env}, **entry.rollout_env}
    return workflowgen.Job(name=job.key, runs_on=entry.rollout_runs_on, steps=tuple(steps),
                           runner=entry.rollout_runner, note=unarchived, checkout=not job.no_checkout, extras=extras)


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
