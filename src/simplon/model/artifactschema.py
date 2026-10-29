# GENERATED from src/firn/model/simplon/vocabulary/kinds.firn (the kinds) and
# src/firn/model/simplon/catalogue/tasks.firn (the ports) by `./simplon.sh build model`. Do not edit:
# firn rewrites the whole file on every run, and this file has no protected region. If it is missing or
# empty, every `./simplon.sh` command stops at import: `git checkout -- src/simplon/model/artifactschema.py`.
"""The `artifacts:` entry of each kind, as a pydantic model (si#344 B2, spec B.1-B.3).

One class per kind of the catalogue's vocabulary. A kind that refines another is a subclass of it, so
`isinstance(entry, DirectoryEntry)` holds for a `site` too: a reader accepts a kind and every kind that
refines it. A key the kind does not declare is refused by name (`_known`); a declared key's value has
the SHAPE the model gives it (`_typed`). Which keys a reader NEEDS is `NEEDS`, applied by
`simplon.manifest.artifactsection.entry`. Every refusal here is a `raise ValueError` in the root's validators,
where the refusal census counts it.
"""
from __future__ import annotations

import datetime
import difflib
from collections.abc import Mapping
from typing import ClassVar, NamedTuple, TypeAlias

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

#: A field's type, by the SHAPE the model gives its key. `_typed` makes a present value fit it first.
_text: TypeAlias = "str | None"
_texts: TypeAlias = "tuple[str, ...] | None"
_table: TypeAlias = "dict[str, str] | None"
_untyped: TypeAlias = object

#: Each kind and the one kind it refines, "" for the root - the catalogue's `kinds:`, from the same model.
REFINES: dict[str, str] = {
    "artifact": "",
    "image": "artifact",
    "directory": "artifact",
    "file": "artifact",
    "homebrew-formula": "file",
    "site": "directory",
    "nuget": "artifact",
    "maven": "artifact",
    "conan": "artifact",
    "test-result": "artifact",
    "release-notes": "artifact",
    "tag": "artifact",
    "release": "artifact",
    "github-release": "release",
    "release-assets": "release",
}



class Port(NamedTuple):
    """One port of a catalogue task (si#344 C.1): its name, `input` or `output`, the kind it accepts (and
    every kind refining it), the body parameter that receives the bound artifact's name ("" for none) and
    the keys it needs on the entry it reads."""

    name: str
    direction: str
    accepts: str
    param: str
    needs: tuple[str, ...]


#: Each catalogue task that takes or gives an artifact -> its ports, inputs first.
PORTS: dict[str, tuple[Port, ...]] = {
    "build:image": (
        Port("file", "input", "file", "", ()),
        Port("image", "output", "image", "name", ("registry", "repository", "dockerfile", "context", )),
    ),
    "build:fetch": (
        Port("file", "output", "file", "name", ("path", "url", "sha256", )),
    ),
    "test:image": (
        Port("image", "input", "image", "name", ("registry", "repository", "dockerfile", "context", )),
        Port("test-result", "output", "test-result", "results", ("path", )),
    ),
    "build:image-file": (
        Port("image", "input", "image", "name", ("registry", "repository", "dockerfile", "context", )),
        Port("file", "output", "file", "file", ("path", )),
    ),
    "test:file": (
        Port("file", "input", "file", "file", ("path", )),
        Port("test-result", "output", "test-result", "results", ("path", )),
    ),
    "release:image": (
        Port("image", "input", "image", "name", ("registry", "repository", "dockerfile", "context", )),
        Port("evidence", "input", "test-result", "", ()),
    ),
    "release:artifact": (
        Port("directory", "input", "directory", "name", ("registry", "repository", "media_type", "path", )),
        Port("evidence", "input", "test-result", "", ()),
    ),
    "build:conan-cache": (
        Port("conan", "input", "conan", "name", ("registry", "repository", "media_type", "path", )),
    ),
    "release:conan": (
        Port("conan", "input", "conan", "name", ("registry", "repository", "media_type", "path", )),
        Port("evidence", "input", "test-result", "", ()),
    ),
    "build:nuget-config": (
        Port("nuget", "input", "nuget", "name", ("registry", )),
    ),
    "build:nuget-restore": (
        Port("nuget", "input", "nuget", "name", ("registry", "image", "project", )),
    ),
    "build:nuget-pack": (
        Port("nuget", "output", "nuget", "name", ("image", "project", "path", )),
    ),
    "release:nuget": (
        Port("nuget", "input", "nuget", "name", ("registry", "image", "path", )),
        Port("evidence", "input", "test-result", "", ()),
    ),
    "build:maven-pack": (
        Port("maven", "output", "maven", "name", ("image", "group", "modules", "path", )),
    ),
    "build:homebrew-formula": (
        Port("wheel", "input", "directory", "wheel", ("path", )),
        Port("formula", "output", "homebrew-formula", "formula", ("path", )),
    ),
    "test:homebrew-formula": (
        Port("formula", "input", "homebrew-formula", "formula", ("path", )),
        Port("wheel", "input", "directory", "wheel", ("path", )),
        Port("test-result", "output", "test-result", "results", ("path", )),
    ),
    "release:homebrew-tap": (
        Port("formula", "input", "homebrew-formula", "formula", ("path", )),
        Port("evidence", "input", "test-result", "", ()),
    ),
    "release:maven": (
        Port("maven", "input", "maven", "name", ("registry", "group", "modules", "path", )),
        Port("evidence", "input", "test-result", "", ()),
    ),
    "release:notes": (
        Port("release-notes", "output", "release-notes", "name", ("path", )),
    ),
    "release:tag": (
        Port("release-notes", "input", "release-notes", "", ()),
        Port("tag", "output", "tag", "", ()),
    ),
    "release:github-draft": (
        Port("release-notes", "input", "release-notes", "name", ("path", )),
    ),
    "release:github-attach": (
        Port("files", "input", "file", "", ("path", )),
        Port("evidence", "input", "test-result", "", ()),
        Port("release-assets", "output", "release-assets", "assets", ("path", )),
    ),
    "release:github-publish": (
        Port("github-release", "output", "github-release", "", ()),
    ),
    "docs:site": (
        Port("site", "output", "site", "", ()),
    ),
    "deploy:up": (
        Port("source", "input", "artifact", "", ()),
    ),
    "toolchain:run": (
        Port("source", "input", "artifact", "", ()),
        Port("out", "output", "artifact", "", ()),
    ),
}

#: Every catalogue task -> the body the model names. catalogue.yaml names it too until si#400 plan 4c.
BODIES: dict[str, str] = {
    "build:image": "simplon.tasks.image:build",
    "build:fetch": "simplon.tasks.fetchfile:fetch",
    "test:image": "simplon.tasks.image:smoke",
    "build:image-file": "simplon.tasks.imagefile:extract",
    "test:file": "simplon.tasks.imagefile:check",
    "release:image": "simplon.tasks.image:release",
    "release:artifact": "simplon.tasks.artifact:publish",
    "build:conan-cache": "simplon.tasks.conan:fetch",
    "release:conan": "simplon.tasks.conan:publish",
    "build:nuget-config": "simplon.tasks.nuget:config",
    "build:nuget-restore": "simplon.tasks.nuget:restore",
    "build:nuget-pack": "simplon.tasks.nuget:pack",
    "release:nuget": "simplon.tasks.nuget:push",
    "build:maven-pack": "simplon.tasks.maven:pack",
    "build:homebrew-formula": "simplon.tasks.homebrewformula:build",
    "test:homebrew-formula": "simplon.tasks.homebrewtap:check",
    "release:homebrew-tap": "simplon.tasks.homebrewtap:tap",
    "release:maven": "simplon.tasks.maven:push",
    "release:notes": "simplon.tasks.releasenotes:write",
    "release:tag": "simplon.tasks.release:tag",
    "release:github-unpublished": "simplon.tasks.githubrelease:unpublished",
    "release:github-draft": "simplon.tasks.githubrelease:draft",
    "release:github-attach": "simplon.tasks.githubrelease:attach",
    "release:github-publish": "simplon.tasks.githubrelease:publish",
    "docs:site": "simplon.tasks.site:build",
    "deploy:up": "simplon.tasks.deploy:up",
    "toolchain:run": "simplon.tasks.toolchain:run_toolchain",
    "vcs:commit": "simplon.tasks.vcs:commit",
    "vcs:push": "simplon.tasks.vcs:push",
    "vcs:prune-branches": "simplon.tasks.vcs:prune_branches",
    "vcs:auth-scopes": "simplon.tasks.vcs:auth_scopes",
    "vcs:submodules": "simplon.tasks.vcs:submodules",
    "support:ci-privileges": "simplon.tasks.ciprivileges:grant",
    "support:ci-disk-hygiene": "simplon.tasks.cidisk:hygiene",
    "support:ci-arm64": "simplon.tasks.ciarm64:arm64",
    "support:ci-disk-preflight": "simplon.tasks.cidisk:preflight",
    "support:ci-disk-cleanup": "simplon.tasks.cidisk:cleanup",
    "test:gate": "simplon.tasks.testrun:gate",
    "test:typecheck-python": "simplon.tasks.typecheck:check",
    "test:generated": "simplon.tasks.generated:check",
    "test:release-notes": "simplon.tasks.releasenotes:check",
    "test:report": "simplon.tasks.testrun:report_cmd",
    "test:accept": "simplon.tasks.testrun:accept_cmd",
    "test:walk": "simplon.tasks.walk:walk",
    "support:nexus": "simplon.tasks.nexus:nexus_cmd",
    "support:install": "simplon.tasks.hosttools:install",
    "support:claude-plugins": "simplon.tasks.claudeplugins:install_cmd",
    "support:claude-md": "simplon.tasks.claudemd:claude_md_cmd",
    "support:environments": "simplon.tasks.env:environments",
    "support:completion": "simplon.tasks.completion:generate",
    "support:workflows": "simplon.tasks.workflows:generate",
    "docs:render": "simplon.tasks.docs:render",
    "docs:reference": "simplon.tasks.cliref:reference",
    "docs:acceptance": "simplon.tasks.acceptance:document",
    "build:model": "simplon.tasks.firngen:generate",
    "build:cmake-files": "simplon.tasks.buildfiles:cmake",
    "build:dotnet-solution": "simplon.tasks.buildfiles:dotnet",
    "deploy:carrier": "simplon.tasks.carrier:up",
    "deploy:down": "simplon.tasks.deploy:down",
    "release:asset": "simplon.tasks.asset:publish",
    "tasks:generate": "simplon.tasks.taskverbs:generate",
    "tasks:catalogue": "simplon.tasks.taskverbs:catalogue",
    "support:migrate": "simplon.tasks.migrate:migrate",
    "test:manifest-model": "simplon.tasks.manifestcheck:check",
    "support:model": "simplon.tasks.manifestmodel:model",
    "support:toolchain": "simplon.tasks.toolchain:scaffold",
}

#: The catalogue coordinate that reads ONE entry by name (`with: { name: ... }`) -> the kind it reads: its
#: port that binds `name`. `simplon manifest migrate` derives a kindless entry's kind from it.
READERS: dict[str, str] = {c: p.accepts for c, ports in PORTS.items() for p in ports if p.param == "name"}

#: The catalogue coordinate -> the keys that port needs, in the order a reader is told about them.
NEEDS: dict[str, tuple[str, ...]] = {c: p.needs for c, ports in PORTS.items() for p in ports if p.param == "name"}


class ArtifactEntry(BaseModel):
    """The `artifact` kind, the root every kind refines."""

    # `forbid` is a backstop only: `_known` refuses an undeclared key first, in a sentence of its own.
    model_config = ConfigDict(extra="forbid", frozen=True)

    KIND: ClassVar[str] = "artifact"
    SHAPES: ClassVar[dict[str, str]] = {
        "kind": "text",
        "path": "text",
        "registry": "text",
    }

    kind: str
    path: _text = None
    registry: _text = None

    @model_validator(mode="before")
    @classmethod
    def _known(cls, data: object) -> object:
        # A key the kind does not declare would be ignored - a typo'd `platfroms:` would build one
        # platform with no word said - so it is refused by name, with the nearest key the kind has.
        if isinstance(data, Mapping):
            for key in data:
                if str(key) not in cls.SHAPES:
                    near = difflib.get_close_matches(str(key), list(cls.SHAPES), n=1)
                    hint = f" - did you mean '{near[0]}'?" if near else ""
                    raise ValueError(f"'{key}' is not a key of the `{cls.KIND}` artifact{hint}; it takes "
                                     f"{', '.join(sorted(cls.SHAPES))}")
        return data

    @field_validator("*", mode="before")
    @classmethod
    def _typed(cls, value: object, info: ValidationInfo) -> object:
        # Every SHAPE refusal is raised here, for every kind (the validator is inherited): pydantic's
        # own type errors carry no `raise` the census could count, so a value never reaches one.
        key = info.field_name or ""
        shape = cls.SHAPES.get(key, "untyped")
        if value is None:
            raise ValueError(f"'{key}' is written with no value - give it one, or delete the key")
        if shape == "untyped":
            return value
        if shape == "text":
            # A number or an unquoted YAML date is a value here, read as the readers always read it (`str(...)`);
            # a bool is not.
            if isinstance(value, bool) or not isinstance(value, (str, int, float, datetime.date)) or not str(value).strip():
                raise ValueError(f"'{key}' must be a non-empty string or a number")
            return str(value).strip()
        if shape == "texts":
            if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
                raise ValueError(f"'{key}' must be a list of non-empty strings, e.g. [a, b]")
            return tuple(dict.fromkeys(item.strip() for item in value))
        if not isinstance(value, Mapping):
            raise ValueError(f"'{key}' must be a mapping of name to value")
        out: dict[str, str] = {}
        for name, item in value.items():
            if item is None or isinstance(item, (list, dict, tuple)):
                raise ValueError(f"'{key}': '{name}' must be a scalar, not {type(item).__name__}")
            out[str(name)] = "true" if item is True else "false" if item is False else str(item)
        return out


class ImageEntry(ArtifactEntry):
    """The `image` kind, which refines `artifact`."""

    KIND: ClassVar[str] = "image"
    SHAPES: ClassVar[dict[str, str]] = {
        **ArtifactEntry.SHAPES,
        "repository": "text",
        "dockerfile": "text",
        "context": "text",
        "tag": "text",
        "platforms": "texts",
        "contexts": "texts",
        "build_args": "table",
        "local": "text",
        "name": "untyped",
        "build_contexts": "untyped",
    }
    repository: _text = None
    dockerfile: _text = None
    context: _text = None
    tag: _text = None
    platforms: _texts = None
    contexts: _texts = None
    build_args: _table = None
    local: _text = None
    name: _untyped = None
    build_contexts: _untyped = None


class DirectoryEntry(ArtifactEntry):
    """The `directory` kind, which refines `artifact`."""

    KIND: ClassVar[str] = "directory"
    SHAPES: ClassVar[dict[str, str]] = {
        **ArtifactEntry.SHAPES,
        "repository": "text",
        "media_type": "text",
        "tag": "text",
        "archive": "text",
    }
    repository: _text = None
    media_type: _text = None
    tag: _text = None
    archive: _text = None


class FileEntry(ArtifactEntry):
    """The `file` kind, which refines `artifact`."""

    KIND: ClassVar[str] = "file"
    SHAPES: ClassVar[dict[str, str]] = {
        **ArtifactEntry.SHAPES,
        "url": "text",
        "sha256": "text",
        "version_from": "table",
        "platform": "text",
        "asset_name": "text",
    }
    url: _text = None
    sha256: _text = None
    version_from: _table = None
    platform: _text = None
    asset_name: _text = None


class Homebrew_formulaEntry(FileEntry):
    """The `homebrew-formula` kind, which refines `file`."""

    KIND: ClassVar[str] = "homebrew-formula"
    SHAPES: ClassVar[dict[str, str]] = {
        **FileEntry.SHAPES,
    }


class SiteEntry(DirectoryEntry):
    """The `site` kind, which refines `directory`."""

    KIND: ClassVar[str] = "site"
    SHAPES: ClassVar[dict[str, str]] = {
        **DirectoryEntry.SHAPES,
    }


class NugetEntry(ArtifactEntry):
    """The `nuget` kind, which refines `artifact`."""

    KIND: ClassVar[str] = "nuget"
    SHAPES: ClassVar[dict[str, str]] = {
        **ArtifactEntry.SHAPES,
        "image": "text",
        "project": "text",
        "source_name": "text",
        "tag": "text",
    }
    image: _text = None
    project: _text = None
    source_name: _text = None
    tag: _text = None


class MavenEntry(ArtifactEntry):
    """The `maven` kind, which refines `artifact`."""

    KIND: ClassVar[str] = "maven"
    SHAPES: ClassVar[dict[str, str]] = {
        **ArtifactEntry.SHAPES,
        "image": "text",
        "group": "text",
        "modules": "untyped",
        "tag": "text",
    }
    image: _text = None
    group: _text = None
    modules: _untyped = None
    tag: _text = None


class ConanEntry(ArtifactEntry):
    """The `conan` kind, which refines `artifact`."""

    KIND: ClassVar[str] = "conan"
    SHAPES: ClassVar[dict[str, str]] = {
        **ArtifactEntry.SHAPES,
        "repository": "text",
        "media_type": "text",
        "tag": "text",
    }
    repository: _text = None
    media_type: _text = None
    tag: _text = None


class Test_resultEntry(ArtifactEntry):
    """The `test-result` kind, which refines `artifact`."""

    KIND: ClassVar[str] = "test-result"
    SHAPES: ClassVar[dict[str, str]] = {
        **ArtifactEntry.SHAPES,
    }


class Release_notesEntry(ArtifactEntry):
    """The `release-notes` kind, which refines `artifact`."""

    KIND: ClassVar[str] = "release-notes"
    SHAPES: ClassVar[dict[str, str]] = {
        **ArtifactEntry.SHAPES,
    }


class TagEntry(ArtifactEntry):
    """The `tag` kind, which refines `artifact`."""

    KIND: ClassVar[str] = "tag"
    SHAPES: ClassVar[dict[str, str]] = {
        **ArtifactEntry.SHAPES,
    }


class ReleaseEntry(ArtifactEntry):
    """The `release` kind, which refines `artifact`."""

    KIND: ClassVar[str] = "release"
    SHAPES: ClassVar[dict[str, str]] = {
        **ArtifactEntry.SHAPES,
    }


class Github_releaseEntry(ReleaseEntry):
    """The `github-release` kind, which refines `release`."""

    KIND: ClassVar[str] = "github-release"
    SHAPES: ClassVar[dict[str, str]] = {
        **ReleaseEntry.SHAPES,
    }


class Release_assetsEntry(ReleaseEntry):
    """The `release-assets` kind, which refines `release`."""

    KIND: ClassVar[str] = "release-assets"
    SHAPES: ClassVar[dict[str, str]] = {
        **ReleaseEntry.SHAPES,
    }


def validate(kind: str, body: Mapping[str, object]) -> ArtifactEntry:
    """`body` validated as an entry of `kind`. The caller has checked that `kind` is a kind of the
    catalogue; a KeyError here means this module and the catalogue came from different models."""
    if kind == "artifact":
        return ArtifactEntry.model_validate(body)
    if kind == "image":
        return ImageEntry.model_validate(body)
    if kind == "directory":
        return DirectoryEntry.model_validate(body)
    if kind == "file":
        return FileEntry.model_validate(body)
    if kind == "homebrew-formula":
        return Homebrew_formulaEntry.model_validate(body)
    if kind == "site":
        return SiteEntry.model_validate(body)
    if kind == "nuget":
        return NugetEntry.model_validate(body)
    if kind == "maven":
        return MavenEntry.model_validate(body)
    if kind == "conan":
        return ConanEntry.model_validate(body)
    if kind == "test-result":
        return Test_resultEntry.model_validate(body)
    if kind == "release-notes":
        return Release_notesEntry.model_validate(body)
    if kind == "tag":
        return TagEntry.model_validate(body)
    if kind == "release":
        return ReleaseEntry.model_validate(body)
    if kind == "github-release":
        return Github_releaseEntry.model_validate(body)
    if kind == "release-assets":
        return Release_assetsEntry.model_validate(body)
    raise KeyError(kind)
# Generated by firn, do not edit outside protected regions. id=[ArtifactSchema:,e2323b29e7b3c06d]
