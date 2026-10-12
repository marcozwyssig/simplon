"""The manifest as a firn M1 model (si#346, spec D.2): a validated manifest in, `.firn` text out.

Run only on what `manifest.load` accepted - this module validates nothing, and a manifest the kernel
refused never reaches it (`tasks/manifestmodel.py` passes the refusal's rc on). firn gets no YAML
importer: simplon owns the parse and the validation, firn checks the shape of what it is handed.

Names. A firn name is [A-Za-z_][A-Za-z0-9_]* (firn docs/03 §2; firn#962 will allow `-`), and a
manifest's are not: `nuget-config`, `build:image`. `mangle` maps one to the other and the original is
kept in `key`, so nothing is lost.

One owner, one namespace. firn names a child by its owner and its own name, never by the property that
holds it: a group `build` under `ci` and a section `build` under `build` are one resource to firn
(measured 2026-10-11: E001 "has 2 typeOf statements"), and cleon, swi, firn and biz-cockpit each carry
such a pair. Groups keep their own names, because they are what a reader follows in `member = ...`;
every other child of the Product carries a prefix saying which section it came from, the way a task
already did (`t_`), so no two sections can meet by construction:

    t_  a task (one per distinct impl)    e_  an environment of the cd matrix
    i_  an `images:` entry                a_  an `artifacts:` entry
    s_  a kernel section                  d_  a section only the product reads

The price: a top-level group literally named like a prefixed child (`e_dev`, `d_jdk`, `t_...`) is
refused by ModelExportError. A PRODUCT cannot write one - `load` locks the top-level groups to the
platform's tree (`ci: e_dev:` is refused as "a group the platform's tree does not declare") - so it is
reachable only through a platform tree that declares such a group. The kernel's own six do not;
`test_a_platform_group_named_like_a_prefixed_child_is_refused` pins the refusal with one that does.

What is left to meet is two originals in one owner that mangle alike (`nuget-config` and
`nuget_config`), and that is refused by name: firn would merge them into one resource, and a model that
silently holds one command where the manifest has two is the defect this kernel hunts.

What is NOT exported, said so that "drops nothing" stays true of the rest:
  - `cd: site:` - the M2 has a Site class, but nothing holds one until a deploy reads a site (spec,
    "What this is NOT"); a manifest's `cd: site:` is not in the model.
  - a `tasks:` entry no command places - one Task per distinct impl a command USES (plan rule 2), so a
    task the product offers and never places (si#53) is invisible until parts B/C need it.
`cd: default:` IS exported, as `Product.default` - the name as written, not a reference to one of
`Product.environments`, because a loadable manifest may name none (simplon's own: `default: dev`, no
matrix); whether it names a real one stays `environments.parse_data`'s verdict at run time.

Every ModelExportError is a DIAGNOSIS (CLAUDE.md's first kind): the manifest loaded, and the model would
otherwise hold less than it does or something it does not. Each one names what it cannot hold - two
names that mangle alike, a group named like a prefixed child, a member that resolves to no one command,
a group in no area, a matrix or an `images:`/`artifacts:` that is not a mapping. Today they fire at RUN
time of an opt-in command (`support manifest model`) and are outside the refusal census, which counts
what refuses on the way from a manifest to a decision. Once parts B/C generate from this model they sit
on that load path, and each needs a census entry then.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from simplon.environments import matrix_section
from simplon.orchestrator.manifest import Manifest

_NOT_NAME = re.compile(r"[^A-Za-z0-9_]")

#: The top-level sections the kernel reads - exactly `test_refusal_census.sections_read()`, typed once
#: (`src/firn/` and `src/firn.toml` are no part of the `simplon` package, so `manifest.firn` is not something it can read at
#: run time. The wheel does not carry it either: si#378 excluded it after namespace discovery had shipped
#: it as a top-level `firn/`, and `test_wheel.py` holds the wheel to `simplon` alone).
#: Typed, so held twice: `test_firn_manifest_coverage` checks it against the census and against the
#: Product's properties, which is what keeps the three copies one statement. `product:` is not here: it
#: is the Product resource's own key, and no reader of the kernel's reads it as a section.
KERNEL_SECTIONS: tuple[str, ...] = (
    "artifacts", "assets", "build", "carriers", "cd", "ci", "claude", "deploy", "doctoolchain_version",
    "env_var", "generate", "generated", "images", "instance", "lab_egress", "layout", "nexus", "output",
    "releases", "suites", "support", "tasks", "taxonomy", "tracker", "website", "workflows",
)

#: Sections the bridge models as structure rather than as an opaque KernelSection.
_STRUCTURE = frozenset({"ci", "cd", "support", "tasks", "images", "artifacts"})
_AREAS = ("ci", "cd", "support")


class ModelExportError(ValueError):
    """A manifest the bridge cannot write as a model without losing something."""


def mangle(name: str) -> str:
    """`name` as a firn name (firn docs/03 §2; firn#962 will allow `-`): every character outside
    [A-Za-z0-9_] becomes `_`, and a leading digit gets `_`."""
    out = _NOT_NAME.sub("_", name)
    return f"_{out}" if out[:1].isdigit() else out


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


class _Names:
    """One OWNER's children, whatever property holds them: mangled name -> original, refusing two
    originals on one name. Per owner and not per property, because that is firn's namespace."""

    def __init__(self, owner: str) -> None:
        self.owner = owner
        self.seen: dict[str, str] = {}

    def __call__(self, original: str, prefix: str = "") -> str:
        # Every call names a NEW child (a task is named once per impl, each other child once), so any
        # repeat is two resources on one name - the same original included: a group `build` and a
        # section `build` passed a guard that only compared originals, and firn said E001.
        name = prefix + mangle(original)
        if name in self.seen:
            raise ModelExportError(
                f"{self.owner}: '{self.seen[name]}' and '{original}' are both '{name}' as a firn name, "
                f"and firn would merge them into one resource - rename one of them")
        self.seen[name] = original
        return name


def _block(head: str, body: list[str]) -> list[str]:
    return [head + " {", *("  " + line for line in body), "}"]


def _tree(manifest: Manifest) -> dict[str, dict]:
    """`manifest.groups` as nesting, in declaration order: `support.git` is `git` inside `support`. A
    parent with no commands of its own still gets its node, so no subtree is dropped."""
    root: dict[str, dict] = {}
    for path in manifest.groups:
        node = root
        for part in path.split("."):
            node = node.setdefault(part, {})
    return root


class _Export:
    def __init__(self, manifest: Manifest, product: str) -> None:
        self.manifest = manifest
        self.product = product
        self.root = f"product.{mangle(product)}.{mangle(product)}"
        self.names = _Names(f"product '{product}'")
        self.paths: dict[str, str] = {}   # dotted group path -> firn path below the Product
        self.tasks: dict[str, str] = {}   # impl -> firn name, in first-use order

    def area(self, group: str) -> str:
        area = self.manifest.area_of(group)
        if area is None and group.split(".", 1)[0] != "support":
            # area_of answers None for support AND for a group outside every area; only the first is
            # support, and calling the second support would be a model that is wrong without failing
            raise ModelExportError(f"group '{group}' stands in no area (ci, cd or support)")
        return area or "support"

    def name_groups(self, tree: dict, prefix: str, owner: _Names, at: str) -> None:
        """Name every group and command first, so a `member` can point forward."""
        for part, children in tree.items():
            path = f"{prefix}{part}"
            firn = f"{at}.{owner(part)}"
            self.paths[path] = firn
            inner = _Names(f"group '{path}'")
            for command in self.manifest.groups.get(path, ()):
                inner(command)
            self.name_groups(children, f"{path}.", inner, firn)

    def group(self, part: str, children: dict, path: str, head: str) -> list[str]:
        body = [f"key = {_q(part)}", f"area = simplon.pipeline.Area.{self.area(path)}"]
        for command in self.manifest.groups.get(path, ()):
            body += self.command(path, command)
        for sub, grandchildren in children.items():
            body += self.group(sub, grandchildren, f"{path}.{sub}",
                               f"group {self.paths[f'{path}.{sub}'].rsplit('.', 1)[1]}")
        return _block(f"{head} typeOf simplon.pipeline.Group", body)

    def command(self, group: str, name: str) -> list[str]:
        spec = self.manifest.spec_for(group, name)
        body = [f"key = {_q(name)}"]
        if spec.depends_on:
            for dep in spec.depends_on:
                # the kernel's own resolution: a dependency is a bare name one group owns (rule 4, #895)
                path = self.manifest.path_by_name(dep)
                if path is None:
                    raise ModelExportError(
                        f"command '{group}.{name}': member '{dep}' is not one unambiguous command")
                owner, _, member = path.rpartition(".")
                body.append(f"member = {self.paths[owner]}.{mangle(member)}")
            kind = "AggregateCommand"
        else:
            if spec.impl not in self.tasks:
                self.tasks[spec.impl] = self.names(spec.impl, "t_")
            body.append(f"task = {self.root}.{self.tasks[spec.impl]}")
            kind = "TaskCommand"
        return _block(f"command {mangle(name)} typeOf simplon.pipeline.{kind}", body)

    def groups(self) -> list[str]:
        tree = _tree(self.manifest)
        self.name_groups(tree, "", self.names, self.root)
        by_area: dict[str, list[str]] = {area: [] for area in _AREAS}
        for part, children in tree.items():
            area = self.area(part)
            by_area[area] += self.group(part, children, part, f"{area} {self.paths[part].rsplit('.', 1)[1]}")
        return [line for area in _AREAS for line in by_area[area]]

    def task_lines(self) -> list[str]:
        return [line for impl, name in self.tasks.items()
                for line in _block(f"tasks {name} typeOf simplon.pipeline.Task",
                                   [f"key = {_q(impl)}", f"body = {_q(impl)}"])]

    def environments(self, document: Mapping[str, object]) -> list[str]:
        matrix = matrix_section(document)
        envs = {} if matrix["environments"] is None else matrix["environments"]
        default = matrix["default"]
        if not isinstance(envs, Mapping):
            raise ModelExportError(f"cd: environments is a {type(envs).__name__}, not a mapping")
        names = {str(env): self.names(str(env), "e_") for env in envs}
        # `cd: default:` as the manifest WRITES it, a name and not a reference to an Environment: `load`
        # does not hold it to the matrix (`environments.parse_data` does, when a run first resolves an
        # environment), and simplon's own manifest says `default: dev` with no matrix at all - so a
        # reference would refuse the kernel's own model, and dropping the line would be a model quietly
        # smaller than its manifest
        lines = [] if default is None else [f"default = {_q(str(default))}"]
        order = list(names.items())
        for index, (env, name) in enumerate(order):
            body = [f"key = {_q(env)}"]
            if index + 1 < len(order):
                body.append(f"next = {self.root}.{order[index + 1][1]}")
            lines += _block(f"environments {name} typeOf simplon.pipeline.Environment", body)
        return lines

    def artifacts(self, document: Mapping[str, object]) -> list[str]:
        # kinds are coarse on purpose: part B refines them (spec B.2)
        lines: list[str] = []
        for section, prefix, kind in (("images", "i_", "image"), ("artifacts", "a_", "artifact")):
            entries = document.get(section)
            if entries is None:
                continue
            if not isinstance(entries, Mapping):
                raise ModelExportError(f"{section}: is a {type(entries).__name__}, not a mapping")
            for entry in entries:
                lines += _block(f"{section} {self.names(str(entry), prefix)} typeOf simplon.pipeline.Artifact",
                                [f"key = {_q(str(entry))}", f"kind = simplon.vocabulary.{kind}"])
        return lines

    def sections(self, document: Mapping[str, object], kernel_sections: frozenset[str]) -> list[str]:
        lines: list[str] = []
        for key in document:
            key = str(key)
            if key == "product" or key in _STRUCTURE:
                continue
            if key in kernel_sections:
                head = f"{mangle(key)} {self.names(key, 's_')} typeOf simplon.manifest.KernelSection"
            else:
                head = f"data {self.names(key, 'd_')} typeOf simplon.manifest.ProductData"
            lines += _block(head, [f"key = {_q(key)}"])
        return lines


def export(manifest: Manifest, document: Mapping[str, object], product: str,
           kernel_sections: frozenset[str] | tuple[str, ...]) -> str:
    """The complete text of one product's M1 `.firn` file, in package `product.<mangle(product)>`.

    `document` is the YAML the manifest was loaded from (sections the Manifest does not carry are read
    off it), and `kernel_sections` decides which of its top-level keys are the kernel's and which are
    the product's own data - `KERNEL_SECTIONS` in every real call."""
    run = _Export(manifest, product)
    body = [f"key = {_q(product)}"]
    body += run.groups()   # first: names the tasks the commands run
    body += run.task_lines()
    body += run.environments(document)
    body += run.artifacts(document)
    body += run.sections(document, frozenset(kernel_sections))
    lines = [
        f"// GENERATED by `support manifest model` from {product}.yaml (si#346). Do not edit; regenerate.",
        f"package product.{mangle(product)}",
        "",
        *_block(f"{mangle(product)} typeOf simplon.manifest.Product", body),
    ]
    return "\n".join(lines) + "\n"
