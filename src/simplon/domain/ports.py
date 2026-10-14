"""Port bindings (si#344 C.2): a command binds its task's ports with `produces:` and `consumes:`.

A port is `artifactschema.Port`. A catalogue task's ports come from the model (`PORTS`, generated, si#344
C.1); a product task's come from its own `input:`/`output:`. A port with a `param:` hands the bound
artifact's NAME to that body parameter - the only way an artifact reaches a body (spec C.1) - so the
loader writes the binding into the command's `with:`. A port without one is checked and modelled only.

`with: { name: X }` alone, on the parameter a port binds, is read as that port's binding (decided
2026-10-14, si#344): the rules see an unmigrated manifest too, and `simplon manifest migrate` rewrites it.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from simplon.domain import artifactsection

from simplon.domain.artifactschema import PORTS, Port

if TYPE_CHECKING:
    from simplon.domain.manifest import Manifest

#: The command key that binds each direction's ports.
SIDE = {"output": "produces", "input": "consumes"}


def of(ref: str, product_tasks: Mapping[str, object]) -> tuple[Port, ...]:
    """The ports of the task a command's `task:` names: the model's for a coordinate, the task's own
    `input:`/`output:` for a product task."""
    if ":" in ref:
        return PORTS.get(ref, ())
    spec = product_tasks.get(ref)
    return declared(ref, spec) if isinstance(spec, Mapping) else ()


#: What a port declaration takes.
_PORT_KEYS = ("accepts", "param")


def declared(task: str, spec: Mapping[str, object]) -> tuple[Port, ...]:
    """A product task's own `input:` and `output:` (si#344 C.2) as Ports, inputs first. The shape only:
    which kinds exist is the catalogue's, and `check` holds `accepts:` to it."""
    out: list[Port] = []
    seen: dict[str, str] = {}
    for direction in ("input", "output"):
        raw = spec.get(direction)
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"task '{task}' declares `{direction}:` as {type(raw).__name__}, not a mapping of port name to "
                f"port: `{direction}: {{ <port>: {{ accepts: <kind>, param: <parameter> }} }}`")
        for key, body in raw.items():
            name = str(key)
            if not isinstance(body, Mapping):
                raise ValueError(
                    f"task '{task}' port '{name}' is not a mapping: it takes `accepts:` and optionally `param:`")
            unknown = sorted(str(k) for k in body if k not in _PORT_KEYS)
            if unknown:
                raise ValueError(
                    f"task '{task}' port '{name}' declares unknown key `{unknown[0]}:` - a port takes "
                    f"{', '.join(_PORT_KEYS)}")
            accepts, param = body.get("accepts"), body.get("param", "")
            if not isinstance(accepts, str) or not accepts.strip():
                raise ValueError(
                    f"task '{task}' port '{name}' declares no `accepts:` - name the kind of artifact it takes")
            if not isinstance(param, str):
                raise ValueError(
                    f"task '{task}' port '{name}': `param:` is the name of a body parameter, written as text")
            if name in seen:
                raise ValueError(
                    f"task '{task}' declares port '{name}' as an {seen[name]} and an {direction}: a port name "
                    f"says which port a command binds, so it names one")
            seen[name] = direction
            out.append(Port(name, direction, accepts.strip(), param.strip(), ()))
    return tuple(out)


def bindings(where: str, ref: str, spec: Mapping[str, object],
             ports: tuple[Port, ...]) -> dict[str, dict[str, tuple[str, ...]]]:
    """The command's `produces:` and `consumes:` as {key: {port: (artifact, ...)}}, each port one of
    `ports` on the side its key binds (rule 4)."""
    out: dict[str, dict[str, tuple[str, ...]]] = {"produces": {}, "consumes": {}}
    for direction, key in SIDE.items():
        raw = spec.get(key)
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"command '{where}' declares `{key}:` as {type(raw).__name__}, not a mapping. `{key}:` binds "
                f"a port to an artifact: `{key}: {{ <port>: <artifact> }}`")
        offered = {p.name: p for p in ports if p.direction == direction}
        for name, value in raw.items():
            port = offered.get(str(name))
            if port is None:
                raise ValueError(
                    f"command '{where}' binds `{key}: {name}`, and task '{ref}' has no {direction} port "
                    f"'{name}' - its {direction} ports: {', '.join(sorted(offered)) or 'none'}")
            out[key][port.name] = _artifacts(where, key, port, value)
    return out


def _artifacts(where: str, key: str, port: Port, value: object) -> tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    if key == "consumes" and isinstance(value, list) and value \
            and all(isinstance(item, str) and item.strip() for item in value):
        if port.param:
            raise ValueError(
                f"command '{where}' binds port '{port.name}' to a list, and that port hands ONE artifact's "
                f"name to `{port.param}` - bind one artifact")
        return tuple(item.strip() for item in value)
    raise ValueError(
        f"command '{where}' binds port '{port.name}' to {value!r}: `{key}:` names an artifact"
        + (", or a list of them on a port without `param:`" if key == "consumes" else ""))


def check(manifest: "Manifest", declared: Mapping[str, "artifactsection.Declared"],
          kinds: Mapping[str, str]) -> None:
    """Load rules 1, 2, 3 and 5 (spec C.5, si#344 C.2) over the loaded manifest, all four diagnosis; then
    the test-result rules (si#344 C.3, `_check_results`)."""
    producers: dict[str, list[str]] = {}
    consumers: list[tuple[str, str]] = []
    for group, members in manifest.commands.items():
        for name, spec in members.items():
            where = f"{group} {name}"
            for port in spec.ports:
                if port.accepts not in kinds:
                    raise ValueError(
                        f"command '{where}': port '{port.name}' of task '{spec.task}' accepts '{port.accepts}', "
                        f"which is no kind the catalogue declares - it declares: {', '.join(kinds)}")
            for key, side in (("produces", spec.produces), ("consumes", spec.consumes)):
                for port_name, artifacts in side.items():
                    port = next(p for p in spec.ports if p.name == port_name)
                    for artifact in artifacts:
                        if artifact not in declared:
                            raise ValueError(
                                f"command '{where}' binds '{artifact}' to port '{port_name}', and `artifacts:` "
                                f"declares no '{artifact}' - declare it there with its `kind:`")
                        kind = declared[artifact].kind
                        if not artifactsection.accepts(kinds, port.accepts, kind):
                            raise ValueError(
                                f"command '{where}' binds '{artifact}', a `{kind}`, to port '{port_name}', which "
                                f"accepts `{port.accepts}` and the kinds that refine it")
                        if key == "produces":
                            producers.setdefault(artifact, []).append(where)
                        else:
                            consumers.append((where, artifact))
    for where, artifact in consumers:
        if artifact not in producers and not declared[artifact].registry:
            raise ValueError(
                f"command '{where}' consumes '{artifact}', and no command produces it - produce it with a "
                f"command, or give it a `registry:` it is fetched from")
    for group, members in manifest.commands.items():
        for name, spec in members.items():
            if spec.depends_on:
                _check_plan(manifest, f"{group} {name}", manifest.plan_for(name, group=group))
    about = _check_results(manifest, declared, kinds)
    _check_release(manifest, declared, kinds, about)


def _check_plan(manifest: "Manifest", aggregate: str, plan: tuple[str, ...]) -> None:
    """Rule 1 per plan (decided 2026-10-14) and rule 5: one producer of an artifact in a plan, planned
    before every consumer of it there."""
    made: dict[str, tuple[int, str]] = {}
    for at, step in enumerate(plan):
        spec = manifest.spec_by_name(step)
        for artifact in (a for names in (spec.produces if spec else {}).values() for a in names):
            if artifact in made:
                raise ValueError(
                    f"aggregate '{aggregate}' plans two producers of '{artifact}': '{made[artifact][1]}' and "
                    f"'{step}' - one plan builds an artifact once, so plan one of them")
            made[artifact] = (at, step)
    for at, step in enumerate(plan):
        spec = manifest.spec_by_name(step)
        for artifact in (a for names in (spec.consumes if spec else {}).values() for a in names):
            if artifact in made and made[artifact][0] > at:
                producer = made[artifact][1]
                raise ValueError(
                    f"aggregate '{aggregate}' plans '{step}' before '{producer}', and '{step}' consumes "
                    f"'{artifact}', which '{producer}' produces - list '{producer}' first in `depends_on`")


#: The kinds a release produces about itself (si#344 C.3, decided 2026-10-14). The release rule asks for test
#: results about every OTHER artifact a release command consumes: the notes, the tag, the bundle and the
#: evidence itself are not what a release publishes.
OWN_KINDS = ("test-result", "release-notes", "tag", "release")


def _top(group: str) -> str:
    return group.split(".", 1)[0]


def _check_results(manifest: "Manifest", declared: Mapping[str, "artifactsection.Declared"],
                   kinds: Mapping[str, str]) -> dict[str, set[str]]:
    """A produced test result has a `path:` and is produced under `ci: test:` (si#344 C.3). Returns what
    each artifact's test results are: artifact -> the results whose producer consumes it."""
    about: dict[str, set[str]] = {}
    for group, members in manifest.commands.items():
        for name, spec in members.items():
            made = [a for names in spec.produces.values() for a in names
                    if artifactsection.accepts(kinds, "test-result", declared[a].kind)]
            if not made:
                continue
            where = f"{group} {name}"
            for result in made:
                if not declared[result].path:
                    raise ValueError(
                        f"command '{where}' produces the test result '{result}', which declares no `path:` - "
                        f"a test result is what the test writes, so name where")
            if (manifest.area_of(group), _top(group)) != ("ci", "test"):
                raise ValueError(
                    f"command '{where}' produces the test result '{made[0]}' outside `ci: test:` - a test "
                    f"result is evidence that a test ran, so only a command under `ci: test:` produces one")
            for subject in (a for names in spec.consumes.values() for a in names):
                about.setdefault(subject, set()).update(made)
    return about


def _check_release(manifest: "Manifest", declared: Mapping[str, "artifactsection.Declared"],
                   kinds: Mapping[str, str], about: Mapping[str, set[str]]) -> None:
    """Rule 6 (spec C.3, C.5): a command under `ci: release:` that consumes an artifact X consumes every test
    result about X, and at least one exists. X is every consumed artifact whose kind is not one of OWN_KINDS
    (decided 2026-10-14). "About" is direct: a result is about what its producer consumes."""
    for group, members in manifest.commands.items():
        if (manifest.area_of(group), _top(group)) != ("ci", "release"):
            continue
        for name, spec in members.items():
            where = f"{group} {name}"
            consumed = [a for names in spec.consumes.values() for a in names]
            evidence = {a for a in consumed if artifactsection.accepts(kinds, "test-result", declared[a].kind)}
            for subject in consumed:
                if any(artifactsection.accepts(kinds, own, declared[subject].kind) for own in OWN_KINDS):
                    continue
                wanted = about.get(subject, set())
                if not wanted:
                    raise ValueError(
                        f"command '{where}' releases '{subject}', and no test produces a result about it - add "
                        f"a command under `ci: test:` that consumes '{subject}' and produces a `test-result`, "
                        f"and bind that result to this command's `evidence` port")
                missing = sorted(wanted - evidence)
                if missing:
                    raise ValueError(
                        f"command '{where}' releases '{subject}' without the test result(s) "
                        f"{', '.join(missing)} about it - bind every one to its `evidence` port, so no "
                        f"release goes past a test that ran")
