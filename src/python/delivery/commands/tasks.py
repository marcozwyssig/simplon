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
    cat = catalogue_mod.load()
    imported = _imported_namespaces(context.current().manifest_data())

    for namespace in cat.namespaces():
        mark = " (imported)" if namespace in imported else ""
        print(f"{namespace}{mark}")
        tasks = cat.namespace(namespace)
        width = max(len(name) for name in tasks)
        for name in sorted(tasks):
            print(f"    {name:<{width}}  {tasks[name].get('help', '')}")
        print()
    return 0


def _imported_namespaces(data: dict) -> frozenset[str]:
    """The namespaces a product's raw manifest imports from the delivery catalogue.

    Read from the RAW mapping rather than the parsed manifest on purpose: `import:` is folded into
    `groups:` during loading and is gone by the time the parsed form exists, so the parsed manifest cannot
    answer which namespaces were named. A product that imports nothing yields an empty set rather than an
    error - naming no coordinate is a legitimate state, and the listing is still worth printing.
    """
    section = (data or {}).get("import") or {}
    if not isinstance(section, dict):
        return frozenset()
    names = section.get("delivery") or []
    return frozenset(str(name) for name in names) if isinstance(names, list) else frozenset()
