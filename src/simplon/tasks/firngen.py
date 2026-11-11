"""`build:model` (si#400 4b): run `firn gen` over a product's firn project, and refuse what firn only warns about.

firn v0.1.0 answers rc 0 when it KEEPS a file no template produces any more (W301) and when it appends a
protected region a template no longer produces (W300) - measured in the part 4 spec. The kept file still
defines a task class with a live KEY, so after a rename two classes carry one coordinate: green, and wrong.
`gen --format=json` names both in `diagnostics[].code`, and this reads it (spec decision 6).

It also does what `build model` did by hand-typed lists until 4b: firn v0.1.0 wrote every file 0600, so each
file firn reports is made 0644. The list is firn's own report, so it cannot go stale.

WHAT WENT, AND WHY (si#568, decided by Marco 2026-11-04). Until then this also refused a file holding only
firn's id line and every file firn reported DELETED. Since firn#966 (in docs/04 from v0.2.0 on) firn writes
no file whose template reported an error (rc 1), and refuses a run that would delete every file of a target
(E315, rc 1); an id line alone is now what a template with an empty body legitimately writes, and a partial
deletion is a regeneration firn names. Both refusals had become stricter second sources, measured by firn's
own session against its v0.5.0 tag; W300/W301 had not (rc 0 in firn), so they stay.

RCs (si#568 decisions 2, 5, 6): firn's code reaches the caller unchanged, including when its output is not
the JSON report (a usage text on 2, a product binary's registry refusal on 6). A red verdict that is the
kernel's own - firn said 0 - is 4 for W300/W301 ("output not current" in substance) and 1 for a run that
produced nothing or reported a file that is not there, and its line says the verdict is simplon's.
"""
import json
import posixpath
import sys
from pathlib import Path

import typer

from simplon.adapters import docker, hostpath
from simplon.kernel.run import Result
from simplon.manifest import context
from simplon.tasks import toolchain

#: firn's diagnostics that leave a file behind with rc 0 (docs/04 §2.5; still rc 0 in v0.5.0).
REFUSED = ("W300", "W301")
#: The kernel's own verdict for them: firn's OUTPUT_NOT_CURRENT, which is what they are in substance.
KEPT_RC = 4

#: firn's exit codes, as `ExitCode.java` names them in firn v0.6.0 (7 is new there, firn#1196, ADR 0105).
#: firn's `--help` lists none (measured on v0.2.0), so the table cannot be read from the image; a firn
#: release that adds a code is named "unknown" here until the table follows.
FIRN_CODES: dict[int, str] = {
    0: "OK",
    1: "MODEL_ERROR - the model or a template is wrong; firn's diagnostics above say where",
    2: "USAGE - firn did not understand the command line",
    3: "IO - firn could not read or write a file (no firn.toml where it started?)",
    4: "OUTPUT_NOT_CURRENT - firn kept a file it would have rewritten (W303/W304/E316); see above",
    5: "RESOURCE_EXHAUSTED - firn ran out of a resource (memory, stack)",
    6: "DUPLICATE_REGISTRY_KEY - a product binary refused two functions under one key",
    7: ("BINARY_BOOTSTRAP - the model's only errors are E181 in the project's own files: its templates call "
        "Java functions only the product's own firn holds; build it with build:model-binary, `bootstrap: true` "
        "for the first build, and run this with `binary:`"),
    70: "INTERNAL - firn's own fault; report it to firn",
}
#: docker's own codes for a container that never ran the command.
DOCKER_CODES: dict[int, str] = {
    125: "docker could not start the container (image missing, or a bad run option)",
    126: "docker found the command but could not execute it",
    127: "docker could not find the command in the image",
}


def name_rc(rc: int, *, who: str, meanings: dict[int, str] | None = None) -> None:
    """One line on stderr saying what a non-zero rc of FIRN'S (or docker's) means, and nothing for 0.
    `meanings` overrides the table for one subcommand whose ordinary red has its own sense (`fmt --check`).
    Never handed a code the kernel decided: that line is the verdict's own (final review of si#568)."""
    if rc == 0:
        return
    meaning = (meanings or {}).get(rc) or FIRN_CODES.get(rc)
    if meaning:
        print(f"{who}: firn exited {rc}, {meaning}", file=sys.stderr)
    elif rc in DOCKER_CODES:
        print(f"{who}: rc {rc} is docker's, not firn's: {DOCKER_CODES[rc]}", file=sys.stderr)
    else:
        print(f"{who}: rc {rc} is unknown - not one of firn's codes (v0.6.0) nor docker's", file=sys.stderr)


_WORKDIR = "/workspace"
#: Where `firnBinary` leaves the product's own firn, relative to the firn project (firn docs/05 section 6).
BINARY = "build/firn/firn"


def generate(ctx: typer.Context, image: str = "", cwd: str | None = None, network: str | None = None,
             binary: str = "") -> int:
    """Run `firn gen --format=json` in the pinned `image`, started in `cwd`, and rule on what it reports.
    With `binary`, the product's own firn (built by `build:model-binary`) runs instead of the image's."""
    where = ctx.command_path or "build:model"
    result = _run(where, image, ["gen", "--format=json"], cwd, network, binary)
    if result is None:
        return 1
    name_rc(result.rc, who=where)          # firn's own code only; a verdict of the kernel's says so itself
    return verdict(result.rc, result.out, context.current().root / (cwd or ""))


def validate(ctx: typer.Context, image: str = "", cwd: str | None = None, network: str | None = None,
             binary: str = "") -> int:
    """Run `firn validate --format=json` over the product's firn project, and pass firn's rc through, named."""
    return _passed_through(ctx.command_path or "test:model", image, ["validate", "--format=json"], cwd,
                           network, binary)


def format_check(ctx: typer.Context, image: str = "", cwd: str | None = None, network: str | None = None) -> int:
    """Run `firn fmt --check` over the product's firn project, and pass firn's rc through, named."""
    return _passed_through(ctx.command_path or "test:model-format", image, ["fmt", "--check"], cwd, network, "",
                           meanings={1: "not formatted as `firn fmt` would write it - the files are listed above; "
                                        "run `firn fmt` and commit the result"})


#: si#575: the Gradle property a product's own build script reads to go on past firn's rc 7 (firn v0.6.0, ADR
#: 0105). It is the script's, not firn's, so `firnBinary` itself still ends 0 or 1.
BOOTSTRAP_PROPERTY = "-Pfirn.bootstrap=true"
BOOTSTRAP = {"": False, "false": False, "true": True}


def model_binary(ctx: typer.Context, image: str = "", cwd: str | None = None, network: str | None = None,
                 bootstrap: str = "") -> int:
    """Build the product's own firn - firn with the project's Java functions - in the `firn-builder` image
    (`gradle --offline firnBinary`, firn docs/05 section 6), then run it once (`--version`).

    THE ROOT IS MOUNTED AT ITS OWN PATH: the build writes `build/firn/lsp.args` with absolute paths, which
    must hold on the host too (firn docs/07 section 9). As the caller, no network by default, and
    `GRADLE_USER_HOME` at `<cwd>/.gradle`, the path firn's own reference command uses. Gradle's rc passes
    through; a build that is green and leaves no binary, or one that does not run, is red.
    """
    where = ctx.command_path or "build:model-binary"
    # case-blind, like `online`: workflowgen renders a step's `params: {bootstrap: true}` as `--bootstrap True`.
    # A `with:` pin arrives as written, so an unquoted YAML bool is refused before this (si#578).
    if bootstrap.strip().lower() not in BOOTSTRAP:
        raise ValueError(f"bootstrap must be 'true' (a product's first binary, firn v0.6.0 on) or 'false', got "
                         f"{bootstrap!r}")
    first = BOOTSTRAP[bootstrap.strip().lower()]
    same = hostpath.translate(context.current().root)
    built = posixpath.join(same, cwd or "", BINARY)
    got = toolchain.invocation(where, image=image, argv=["gradle", "--offline", *([BOOTSTRAP_PROPERTY] if first else []), "firnBinary"],
                               workdir=same,
                               env={"GRADLE_USER_HOME": posixpath.join(same, cwd or "", ".gradle")},
                               caches=None, network=network or "none", cwd=cwd, extra=[])
    if got is None:
        return 1
    result = docker.run_container(*got, capture=False)
    if result.rc != 0:
        print(f"{where}: gradle firnBinary exited {result.rc}; its output is above", file=sys.stderr)
        return result.rc
    if not (context.current().root / (cwd or "") / BINARY).is_file():
        print(f"{where}: gradle was green and left no {BINARY} under {cwd or '.'} - nothing to run "
              "(simplon's verdict, rc 1)", file=sys.stderr)
        return 1
    got = toolchain.invocation(where, image=image, argv=["--version"], workdir=same, env=None, caches=None,
                               network=network or "none", cwd=cwd, extra=[], entrypoint=built)
    if got is None:
        return 1
    smoke = docker.run_container(*got, capture=True)
    if smoke.out.strip():
        print(smoke.out, end="" if smoke.out.endswith("\n") else "\n")
    if smoke.err.strip():
        print(smoke.err, file=sys.stderr, end="")
    name_rc(smoke.rc, who=f"{where} ({BINARY} --version)")
    return smoke.rc


def _passed_through(where: str, image: str, argv: list[str], cwd: str | None, network: str | None,
                    binary: str, meanings: dict[int, str] | None = None) -> int:
    """No verdict of the kernel's own (si#568 decision 2): firn's report is printed, its rc is the answer."""
    result = _run(where, image, argv, cwd, network, binary)
    if result is None:
        return 1
    if result.out.strip():
        print(result.out, end="" if result.out.endswith("\n") else "\n")
    name_rc(result.rc, who=where, meanings=meanings)
    return result.rc


def _run(where: str, image: str, argv: list[str], cwd: str | None, network: str | None,
         binary: str) -> Result | None:
    """One firn run in its container, or None when it cannot start (the reason is printed)."""
    entrypoint = ""
    if binary:
        on_host = context.current().root / (cwd or "") / binary
        if not on_host.is_file():
            print(f"{where}: {binary} is not there under {cwd or '.'} - build the product's own firn first, with "
                  f"a command on `build:model-binary`", file=sys.stderr)
            return None
        entrypoint = posixpath.join(_WORKDIR, cwd or "", binary)
    got = toolchain.invocation(where, image=image, argv=argv, workdir=_WORKDIR, env=None, caches=None,
                               network=network, cwd=cwd, extra=[], entrypoint=entrypoint)
    if got is None:
        return None
    result = docker.run_container(*got, capture=True)
    if result.err.strip():
        print(result.err, file=sys.stderr, end="")
    return result


def verdict(rc: int, out: str, root: Path) -> int:
    """0 only when firn succeeded, reported at least one file (or ran no template at all, si#594), left nothing
    it only warns about, and every file it reported is there and is now 0644. `root` is firn's project root,
    which the reported paths are relative to. A non-zero rc is firn's and comes back unchanged."""
    try:
        report = json.loads(out)
        diagnostics, files = report["diagnostics"], report["files"]
    except (ValueError, KeyError, TypeError):
        print(f"build:model: firn's output is not its JSON report (rc {rc}), so nothing can be ruled on:\n{out}",
              file=sys.stderr)
        return rc or 1
    for d in diagnostics:
        print(f"firn {d.get('code')}: {d.get('message')}", file=sys.stderr)
    for w in report.get("warnings") or []:      # firn v0.10.0 on: W101-W105 here, no longer on stderr (si#594)
        print(f"firn {w.get('sentence')} ({w.get('where')})", file=sys.stderr)
    if rc != 0:
        return rc
    bad = 0
    for path in files.get("kept", []):
        print(f"build:model: firn kept {path}, which no template produces any more but which holds a protected "
              f"region. It still defines what it defined - move its region's content where it belongs, then "
              f"delete the file (simplon's verdict, rc {KEPT_RC}: firn said 0)", file=sys.stderr)
        bad = KEPT_RC
    refused = sorted({str(d.get("code")) for d in diagnostics if d.get("code") in REFUSED})
    if refused:
        print(f"build:model: {', '.join(refused)} - firn left a protected region no template produces, with "
              f"rc 0; see above (simplon's verdict, rc {KEPT_RC})", file=sys.stderr)
        bad = KEPT_RC
    produced = [*files.get("written", []), *files.get("unchanged", []), *files.get("upToDate", [])]
    if not produced:
        # si#594: `run.templates` (firn v0.9.0 on) counts the templates the run's targets select. 0 is a project
        # with nothing to generate; a missing count (older firn) is not a zero, so that run stays refused.
        templates = (report.get("run") or {}).get("templates")
        if templates == 0:
            print("build:model: firn ran no template - the project selects none, so there is nothing to generate "
                  "(firn said 0)", file=sys.stderr)
            return bad
        unknown = ("" if templates is not None else "; this firn does not say how many templates it ran (v0.9.0 "
                   "on does), so a project with none cannot be told from one whose templates wrote nothing")
        print("build:model: firn reported no file at all - nothing was generated, which is not done "
              f"(simplon's verdict, rc 1: firn said 0){unknown}", file=sys.stderr)
        return 1
    for name in produced:
        path = root / name
        if not path.is_file():
            print(f"build:model: firn reported {name}, and it is not there (simplon's verdict, rc 1)",
                  file=sys.stderr)
            bad = bad or 1
            continue
        path.chmod(0o644)
    return bad
