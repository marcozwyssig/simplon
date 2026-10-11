"""The migration (si#344 plan A): text in, text out, and the CLI it assembles unchanged."""
import json
import pathlib

import pytest

from simplon import catalogue
from simplon.orchestrator import manifest
from manifestsurface import cli_surface

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "manifests"
PRODUCTS = sorted(p.stem for p in (FIXTURES / "golden").glob("*.json"))


def test_there_are_eight_goldens():
    # assert: the population is the eight reachable manifests, not whichever happened to load
    assert len(PRODUCTS) + len(_not_loadable()) == 8


def _not_loadable() -> list[str]:
    readme = (FIXTURES / "README.md").read_text()
    return [line.split("`")[1] for line in readme.splitlines() if line.startswith("- `")]
