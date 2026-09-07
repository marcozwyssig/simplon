"""The verb that makes the shell-completion generator addressable (si#58), beside `support:workflows`.

DELIBERATELY THE SAME SHAPE as `support:workflows` and `tasks:generate`, down to `--check` returning 1,
and for the same reason: the generated file is COMMITTED rather than conjured at run time - that is the
whole point, since a TAB must not start an interpreter - so the manifest and the file can disagree, and
one command has to serve both the pre-commit hook and the CI step that notices.

WHAT IS DIFFERENT HERE, and it is the only thing: this command's output is worthless until somebody
sources the file. A generator whose product nobody installs is a file in a repository, not a working
completion, so the run says on every write where the file went and what to type to make TAB work. That
is the fourth quality goal spent where it is cheapest - one line of output - rather than left as
something a user has to go and read about.

A KERNEL MECHANISM: nothing here knows a product. The repo root, the manifest and its filename arrive
through `simplon.context.current()`, and the environment names come out of the manifest's own
`environments:` section - the same one `simplon.environments.parse_data` reads.
"""
from __future__ import annotations

from simplon import completiongen, context, log


def generate(check: bool = False) -> int:
    """Regenerate the product's shell completion from its manifest; `--check` reports drift, writes nothing.

    `--check` returns 1 when the committed completion no longer says what the manifest says - including
    when it is missing entirely, which is the state a fresh checkout is in and is drift rather than an
    error. The rc is the point, not the message: a completion that has fallen behind the command tree
    fails in the quietest way there is - the command still runs when typed in full, and only the TAB goes
    silent - so a warning nobody reads would change nothing about it, and a 1 does.
    """
    ctx = context.current()
    source = ctx.manifest_path.name
    spec = completiongen.tree(ctx.manifest(),
                              environments=completiongen.environments_of(ctx.manifest_data()))
    relative = completiongen.path_for(ctx.name)

    if check:
        drift = completiongen.check(spec, ctx.root, product=ctx.name, source=source)
        if drift is None:
            log.ok(f"{relative} agrees with {source}")
            return 0
        log.warn(f"{drift.path} disagrees with {source} - regenerate with "
                 f"`{context.launcher(ctx.name)} support completion`")
        print(drift.diff)
        return 1

    changed = completiongen.write(spec, ctx.root, product=ctx.name, source=source)
    if changed:
        log.ok(f"{relative} regenerated from {source} - commit it")
    else:
        log.ok(f"{relative} already up to date")
    for line in completiongen.install_hint(ctx.root, ctx.name):
        log.info(line)
    return 0
