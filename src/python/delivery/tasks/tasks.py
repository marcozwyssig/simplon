"""The two verbs that make the task machinery addressable from the command line (netctl#1444).

`generate` is the regeneration the drift gate otherwise only reports on: the generated CLI module is
COMMITTED, not built at import, so something has to write it, and until now that something was an
environment variable on a test run (`UPDATE_GENERATED=1 <product>.sh unit-python`). A verb is the honest
form - the test is a gate, not a build step.

`catalogue` is the other half: the coordinate space exists so a product can say `<namespace>:<name>`
instead of a module path, and a registry nobody can read is a registry nobody uses.

Both are kernel mechanisms under netctl#1280's rule - they need no product knowledge. What is product-
specific reaches them the usual way: the repo root, the manifest and its filename through
`delivery.context.current()`, and the path of the generated module as a manifest-pinned parameter
(`with: { target: ... }`), never through an import.
"""
from __future__ import annotations

from delivery import catalogue as catalogue_mod
from delivery import context, log, taskgen


def generate(target: str, check: bool = False) -> int:
    """Regenerate the product's CLI module from its manifest; `--check` reports drift and writes nothing.

    The module is committed rather than conjured at import, because the point of the exercise is that a
    task is visible - greppable, diffable, reviewable. The price is that the manifest and the module can
    disagree, which is what `--check` is for and what the product's unit gate runs.

    `--check` returning 1 on drift is deliberate: it makes the same command usable as a pre-commit hook or
    a CI step without a second entry point.

    MOVING A KERNEL BODY IS A THREE-STEP DANCE, and this is where that bites. A coordinate frees the
    product MANIFEST from naming a module path, but the generated module still imports one, and
    regenerating runs through the product's CLI - which imports that stale module. Delete the old module
    first and the regeneration fails to import before it can fix itself. So: add the new module, point the
    catalogue at it, regenerate, then delete the old one.
    """
    ctx = context.current()
    mf = ctx.manifest()
    path = ctx.root / target
    source = ctx.manifest_path.name

    if check:
        diff = taskgen.check(mf, path, source=source, product=ctx.name, groups=mf.generate)
        if diff is None:
            log.ok(f"{target} agrees with {source}")
            return 0
        log.warn(f"{target} disagrees with {source} - regenerate with `<product> tasks generate`")
        print(diff)
        return 1

    if taskgen.write(mf, path, source=source, product=ctx.name, groups=mf.generate):
        log.ok(f"regenerated {target} from {source} - commit it")
    else:
        log.ok(f"{target} was already up to date")
    return 0


def catalogue() -> int:
    """List the task coordinates the delivery kernel offers, and which of them this product imports.

    KEPT VERBATIM (netctl#1469 fix round 1): this exact sentence is netctl's CLI-surface golden's
    "summary:" line for `netctl catalogue`/`netctl tasks catalogue` - `taskgen`/`delivery.cli.assemble`
    both take a command's short help from the BODY's docstring's first paragraph, not from the
    manifest's `help:`, whenever the body is bound to only one command (see `_docstring` in taskgen.py).
    "Imports" is no longer the full picture - `_reached_namespaces` below now also counts a `task:`
    reference - but rewording this specific paragraph moves that golden for an unmigrated netctl with no
    netctl-side change to pair it with, which is exactly the failure class this migration's zero-diff
    discipline exists to prevent. The rest of this module's wording is fixed; this one paragraph is not.

    The coordinate space is the whole reason a product can name `<namespace>:<name>` instead of a module
    path: a body moves inside the kernel and no product manifest changes. That only helps someone who can
    see what is on offer, which is what this prints - namespace by namespace, each coordinate with the
    kernel's own one-line summary, and a marker on the namespaces this product's commands reach.
    """
    cat = catalogue_mod.load()
    reached = _reached_namespaces(context.current().manifest_data())

    for namespace in cat.namespaces():
        mark = " (reached)" if namespace in reached else ""
        print(f"{namespace}{mark}")
        tasks = cat.namespace(namespace)
        width = max(len(name) for name in tasks)
        for name in sorted(tasks):
            print(f"    {name:<{width}}  {tasks[name].get('help', '')}")
        print()
    return 0


def _reached_namespaces(data: dict) -> frozenset[str]:
    """The namespaces a product's manifest reaches, from EITHER of the two mechanisms that coexist for
    as long as a migration to the command tree takes (netctl#1469 plan 2).

    A wholly-migrated manifest names a coordinate under `task:`; a wholly-unmigrated one still places a
    platform coordinate the OLD way, via `import:` + a bare `tasks:` override that only becomes `impl:`
    later, inside `_expand_imports` - a step this function's RAW `data` (from `manifest_data()`) never
    sees. Reading only the `task:` walk therefore marks NOTHING for a product like netctl, which has not
    migrated a single group yet: a marker that is silently wrong is worse than one that is silently
    absent, which is exactly the failure this union avoids. Both signals stay read until plan 3 deletes
    the old form and `import:` along with it.
    """
    return _task_ref_namespaces(data) | _import_namespaces(data)


def _task_ref_namespaces(data: dict) -> frozenset[str]:
    """The namespaces a `task:` coordinate reaches anywhere in the raw `groups:` tree.

    Walked generically rather than via `treeform`'s node-shaped walk, because the raw tree can be a MIX
    of old-form groups (no `task:` concept at all) and new-form ones for as long as a migration takes
    (plan 2's per-group partition) - a plain recursive walk over whatever nesting is there needs no
    knowledge of which shape a given node is in. A `task:` value containing a colon is a platform
    coordinate ("namespace:name"); a bare name refers to a task the manifest defines itself and carries
    no namespace to report.
    """
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            ref = node.get("task")
            if isinstance(ref, str) and ":" in ref:
                found.add(ref.split(":", 1)[0])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk((data or {}).get("groups") or {})
    return frozenset(found)


def _import_namespaces(data: dict) -> frozenset[str]:
    """The namespaces the OLD form's `import: { delivery: [...] }` list names.

    The pre-netctl#1469 mechanism: `import:` makes a namespace's coordinates available, and a product
    places one under `tasks:` by bare coordinate key, expanded into `impl:` later inside
    `_expand_imports` - a step this function's RAW `data` never sees. Kept until plan 3 deletes
    `import:` along with the rest of the old form.
    """
    section = (data or {}).get("import") or {}
    if not isinstance(section, dict):
        return frozenset()
    names = section.get("delivery") or []
    return frozenset(str(name) for name in names) if isinstance(names, list) else frozenset()
