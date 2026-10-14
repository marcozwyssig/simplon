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

from simplon.domain.artifactschema import PORTS, Port

#: The command key that binds each direction's ports.
SIDE = {"output": "produces", "input": "consumes"}


def of(ref: str, product_tasks: Mapping[str, object]) -> tuple[Port, ...]:
    """The ports of the task a command's `task:` names: the model's for a coordinate. A product task has
    none until it may declare them."""
    if ":" in ref:
        return PORTS.get(ref, ())
    return ()


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
