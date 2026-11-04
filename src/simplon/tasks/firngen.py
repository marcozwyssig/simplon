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
import sys
from pathlib import Path

import typer

from simplon.adapters import docker
from simplon.manifest import context
from simplon.tasks import toolchain

#: firn's diagnostics that leave a file behind with rc 0 (docs/04 §2.5; still rc 0 in v0.5.0).
REFUSED = ("W300", "W301")
#: The kernel's own verdict for them: firn's OUTPUT_NOT_CURRENT, which is what they are in substance.
KEPT_RC = 4

#: firn's exit codes, as `ExitCode.java` names them in firn v0.5.0 (unchanged on firn main, 2026-11-04).
#: firn's `--help` lists none (measured on v0.2.0), so the table cannot be read from the image; a firn
#: release that adds a code (firn#1196 will add 7) is named "unknown" here until the table follows.
FIRN_CODES: dict[int, str] = {
    0: "OK",
    1: "MODEL_ERROR - the model or a template is wrong; firn's diagnostics above say where",
    2: "USAGE - firn did not understand the command line",
    3: "IO - firn could not read or write a file (no firn.toml where it started?)",
    4: "OUTPUT_NOT_CURRENT - firn kept a file it would have rewritten (W303/W304/E316); see above",
    5: "RESOURCE_EXHAUSTED - firn ran out of a resource (memory, stack)",
    6: "DUPLICATE_REGISTRY_KEY - a product binary refused two functions under one key",
    70: "INTERNAL - firn's own fault; report it to firn",
}
#: docker's own codes for a container that never ran the command.
DOCKER_CODES: dict[int, str] = {
    125: "docker could not start the container (image missing, or a bad run option)",
    126: "docker found the command but could not execute it",
    127: "docker could not find the command in the image",
}


def name_rc(rc: int, *, who: str) -> None:
    """One line on stderr saying what a non-zero rc means, whose it is, and nothing for 0."""
    if rc == 0:
        return
    if rc in FIRN_CODES:
        print(f"{who}: firn exited {rc}, {FIRN_CODES[rc]}", file=sys.stderr)
    elif rc in DOCKER_CODES:
        print(f"{who}: rc {rc} is docker's, not firn's: {DOCKER_CODES[rc]}", file=sys.stderr)
    else:
        print(f"{who}: rc {rc} is unknown - not one of firn's codes (v0.5.0) nor docker's", file=sys.stderr)


def generate(ctx: typer.Context, image: str = "", cwd: str | None = None, network: str | None = None) -> int:
    """Run `firn gen --format=json` in the pinned `image`, started in `cwd`, and rule on what it reports."""
    where = ctx.command_path or "build:model"
    got = toolchain.invocation(where, image=image, argv=["gen", "--format=json"], workdir="/workspace",
                               env=None, caches=None, network=network, cwd=cwd, extra=[])
    if got is None:
        return 1
    result = docker.run_container(*got, capture=True)
    if result.err.strip():
        print(result.err, file=sys.stderr, end="")
    rc = verdict(result.rc, result.out, context.current().root / (cwd or ""))
    name_rc(rc, who=where)
    return rc


def verdict(rc: int, out: str, root: Path) -> int:
    """0 only when firn succeeded, reported at least one file, left nothing it only warns about, and every file
    it reported is there and is now 0644. `root` is firn's project root, which the reported paths are
    relative to. A non-zero rc is firn's and comes back unchanged."""
    try:
        report = json.loads(out)
        diagnostics, files = report["diagnostics"], report["files"]
    except (ValueError, KeyError, TypeError):
        print(f"build:model: firn's output is not its JSON report (rc {rc}), so nothing can be ruled on:\n{out}",
              file=sys.stderr)
        return rc or 1
    for d in diagnostics:
        print(f"firn {d.get('code')}: {d.get('message')}", file=sys.stderr)
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
        print("build:model: firn reported no file at all - nothing was generated, which is not done "
              "(simplon's verdict, rc 1: firn said 0)", file=sys.stderr)
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
