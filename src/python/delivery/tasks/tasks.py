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
from delivery.orchestrator.manifest import Manifest


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

    The coordinate space is the whole reason a product can name `<namespace>:<name>` instead of a module
    path: a body moves inside the kernel and no product manifest changes. That only helps someone who can
    see what is on offer, which is what this prints - namespace by namespace, each coordinate with the
    kernel's own one-line summary, and a marker on the namespaces this product's manifest imports.
    """
    # CORRECTED (netctl#1469 fix round 3): the reasoning that used to sit here predates the docstring
    # chain (spec 3.7) and no longer holds. The docstring above is NOT embedded into the generated
    # module's `help=` for this command - the kernel task `tasks:catalogue` declares its own `help:` in
    # delivery.yaml, and the chain puts a command's help, then its task's, ahead of the body's docstring
    # (both `taskgen._docstring` and `cli._bound` render it), so that `help:` wins here and this
    # docstring's first paragraph never renders as `netctl catalogue`/`netctl tasks catalogue`'s
    # summary line. Rewording the docstring therefore no longer moves that golden; only editing
    # `delivery.yaml`'s `tasks:catalogue.help:` does. "Imports" is still not the full picture below -
    # `_reached_namespaces` reads the ASSEMBLED manifest, not what the product typed.
    cat = catalogue_mod.load()
    reached = _reached_namespaces(context.current().manifest(), cat)

    for namespace in cat.namespaces():
        mark = " (reached)" if namespace in reached else ""
        print(f"{namespace}{mark}")
        tasks = cat.namespace(namespace)
        width = max(len(name) for name in tasks)
        for name in sorted(tasks):
            print(f"    {name:<{width}}  {tasks[name].get('help', '')}")
        print()
    return 0


def _reached_namespaces(manifest: Manifest, cat: catalogue_mod.Catalogue) -> frozenset[str]:
    """The namespaces this product's ASSEMBLED command surface actually reaches (netctl#1469 fix round 2).

    Reads the LOADED `Manifest` rather than the raw manifest text, because a namespace can be reached
    three ways and none of them has to appear as a `task:` coordinate in the product's OWN manifest:

      - the PLATFORM places a command itself, in the kernel's own `delivery.yaml` `groups:` block
        (`support.git`, `tasks.catalogue`/`tasks.generate`) - `treeform.merge` folds that block onto
        every product that has migrated even one group, whether or not that group is the one the
        platform placed a command in;
      - a group mid-migration still names a raw `impl:` that happens to BE a kernel module path (`test`,
        while it has not converted to a command tree as a whole);
      - the pre-#1469 `import:` mechanism, which also bottoms out in a plain `impl:` once
        `_expand_imports` places it.

    All three collapse to the same shape once the manifest is loaded: a command whose resolved `impl`
    equals the `impl` a catalogue coordinate names. Matching on that - what the loader produced, not how
    the coordinate got there - needs no per-mechanism walk and cannot miss a fourth one a later migration
    step adds.
    """
    namespace_by_impl = {spec["impl"]: coordinate.split(":", 1)[0]
                         for coordinate, spec in cat.tasks.items()}
    return frozenset(namespace_by_impl[spec.impl]
                     for members in manifest.commands.values()
                     for spec in members.values()
                     if spec.impl in namespace_by_impl)
