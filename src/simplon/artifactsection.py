"""The `artifacts:` section, one reading for every reader (si#344 B2, spec B.1-B.3).

Every entry names its `kind:`, one of the catalogue's kinds, carries only that kind's keys, each in the shape
`simplon.artifactschema` - GENERATED from simplon's firn model - checks, and a reader finds there the keys
its coordinate NEEDS. Two functions, for the two moments the section is read:

  - `check(document, kinds, source)` at LOAD, from `orchestrator.manifest.load`: every entry is a mapping,
    names a kind the catalogue declares, and declares only its kind's keys, in their shapes;
  - `entry(section, name, wanted, source, coordinate)` at USE, from a task that reads one entry by name: the
    entry is of the kind the task reads or of one that refines it ("a port accepts a kind and every kind that
    refines it"), validated into its generated model, with every key `coordinate` needs.

A PRODUCT asks one question of it: `is_a(kind, wanted)` - "is this entry an image?" - so that its own code
never restates which kinds refine which (`kind == "image"` would miss every kind that refines `image`).

THE ONE IMPORTER OF THE GENERATED MODULE on the loader's path, and that is a guard, not a style. firn
deletes `artifactschema.py` or leaves only its id line with rc 0 (firn#966). The loader imports this module,
so a broken schema would otherwise stop every `./simplon.sh` command - `build model`, which would regenerate
it, included - with a traceback. Here it stops them with the way out.

THE CENSUS SEES ALL OF IT. Each refusal here is a `raise ValueError` the refusal census reaches from the
loader (`check`) and from `tasks.image.declared` (`entry`); a shape or unknown-key refusal is raised in the
generated root's validators, which the walk reaches through the model classes. `_validated` re-raises what a
model raised and carries `_validation_message`, the census's funnel: it refuses nothing of its own. The readers
that read the section INLINE (`tasks.artifact`, `.conan`, `.nuget`, `.maven`) still fetch it themselves and
hand `entry` the SECTION, never the document, so they stay in the census's `READS_INLINE` and the hole
`tasks/maven.py`'s `_declared` describes stays closed.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

from pydantic import ValidationError

try:
    from simplon import artifactschema
    REFINES = artifactschema.REFINES
    READERS = artifactschema.READERS
    NEEDS = artifactschema.NEEDS
    _ROOT = artifactschema.ArtifactEntry
except Exception as exc:  # ImportError, SyntaxError, AttributeError: each is what firn#966 can leave behind
    raise ImportError(
        "simplon.artifactschema is missing, empty or broken - firn deletes or half-writes it with rc 0 "
        "(firn#966), and nothing that loads a manifest runs without it. In simplon's checkout: "
        "`git checkout -- src/simplon/artifactschema.py`, then `./simplon.sh build model` and read firn's "
        "own error; in an installed kernel, reinstall it") from exc

SECTION = "artifacts"

Entry = TypeVar("Entry", bound="artifactschema.ArtifactEntry")


def accepts(parents: Mapping[str, str], wanted: str, kind: str) -> bool:
    """Whether a reader of `wanted` accepts an entry of `kind`: `kind` IS `wanted`, or refines it at any
    distance. `parents` maps each kind to the one it refines, "" for the root (`Catalogue.kinds`, `REFINES`).
    A kind `parents` does not declare is accepted by nothing, and a circle - which `catalogue.loads` refuses -
    ends the walk rather than looping."""
    seen: set[str] = set()
    at = kind
    while at in parents and at not in seen:
        if at == wanted:
            return True
        seen.add(at)
        at = parents[at]
    return False


def is_a(kind: str, wanted: str) -> bool:
    """Whether an entry of `kind` is a `wanted` - the kind itself or one that refines it. The question a
    product's own code asks (`is_a(body["kind"], "image")`), answered from the kernel's vocabulary."""
    return accepts(REFINES, wanted, kind)


def _validation_message(error: ValidationError) -> str:
    """The first refusal's own sentence - the generated validators', verbatim - or `'<key>': <pydantic's
    message>` for a case they did not rule on (none is left, which `test_generated_schema.py` holds)."""
    details = error.errors(include_url=False)
    for detail in details:
        original = (detail.get("ctx") or {}).get("error")
        if isinstance(original, Exception):
            return str(original)
    detail = details[0]
    location = ".".join(str(part) for part in detail.get("loc", ()))
    return f"'{location}': {detail.get('msg', 'invalid')}"


def _validated(kind: str, body: Mapping[str, object], where: str) -> artifactschema.ArtifactEntry:
    try:
        return artifactschema.validate(kind, body)
    except ValidationError as error:
        raise ValueError(f"{where}: {_validation_message(error)}") from None


def check(document: Mapping[str, object], kinds: Mapping[str, str], source: str) -> None:
    """Every entry of `document`'s `artifacts:` is a mapping, names one of `kinds`, and declares only its
    kind's keys, in their shapes - or a ValueError naming the entry. `kinds` is the catalogue's, the authority
    at load; a load without a catalogue passes `REFINES`, the same model's output, so no load skips the
    check. What a READER needs is not asked here: an entry no placed command reads needs nothing."""
    raw = document.get(SECTION)
    if raw is None:
        return
    if not isinstance(raw, Mapping):
        raise ValueError(f"{source}: `{SECTION}:` must be a mapping of artifact name to its entry, "
                         f"found {type(raw).__name__}")
    for name, body in raw.items():
        where = f"{source}: '{SECTION}.{name}'"
        if not isinstance(body, Mapping):
            raise ValueError(f"{where} is not a mapping - an artifact declares its `kind:` and its keys")
        kind = body.get("kind")
        if not isinstance(kind, str) or kind not in kinds:
            raise ValueError(f"{where} declares `kind: {kind}`, which the catalogue does not declare; the "
                             f"kinds are: {', '.join(kinds)}")
        _validated(kind, body, where)


def entry(section: Mapping[str, object], name: str, wanted: type[Entry], source: str, coordinate: str) -> Entry:
    """The entry `name`, validated as the generated model of its kind - `wanted`'s kind or one that refines
    it - and holding every key `coordinate` needs (`NEEDS`, in the model). A ValueError says which kind it is
    and which the task reads, or which key is missing and every key the coordinate reads."""
    if READERS.get(coordinate) != wanted.KIND:
        # Not a refusal of the manifest: a body named a coordinate the model does not route to its kind.
        raise KeyError(f"{coordinate} is not a reader of '{wanted.KIND}' in the model (READERS)")
    body = section[name]
    where = f"{source}: '{SECTION}.{name}'"
    if not isinstance(body, Mapping):
        raise ValueError(f"{where} is not a mapping - an artifact declares its `kind:` and its keys")
    kind = body.get("kind")
    if not isinstance(kind, str) or kind not in REFINES:
        raise ValueError(f"{where} names no kind this kernel knows ({kind!r}); the kinds are: "
                         f"{', '.join(REFINES)}")
    if not accepts(REFINES, wanted.KIND, kind):
        raise ValueError(f"{where} is of kind '{kind}', and this task reads a '{wanted.KIND}' or a kind that "
                         f"refines it - name an entry of that kind, or change the entry's `kind:`")
    validated = _validated(kind, body, where)
    if not isinstance(validated, wanted):
        # Not a refusal either: the generated classes and REFINES disagree, which
        # test_a_kind_that_refines_another_is_its_subclass holds at zero.
        raise TypeError(f"artifactschema.{type(validated).__name__} does not subclass {wanted.__name__} although "
                        f"REFINES says '{kind}' refines '{wanted.KIND}' - run `./simplon.sh build model`")
    needs = NEEDS[coordinate]
    for key in needs:
        if getattr(validated, key) is None:
            raise ValueError(f"{where} declares no `{key}:`, which {coordinate} needs - it reads "
                             f"{', '.join(needs)}")
    return validated
