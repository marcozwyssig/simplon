"""A `gh` on PATH that is a real process and records every call (si#861's decide table, si#874's merge script).

Not a mock of the script under test: the rendered bash really runs and starts a real executable named `gh`. What
it cannot show is GitHub: each test says which answer it stages, and that answer is the test's assumption.
"""
from __future__ import annotations

from pathlib import Path


def gh_on_path(tmp_path: Path, answer: str) -> tuple[Path, Path]:
    """Write `<tmp_path>/bin/gh`: a line appending `$*` to `<tmp_path>/gh.calls`, then `answer` (POSIX sh, `$@`
    is gh's argv). Returns (the bin dir to put first on PATH, the calls file)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "gh.calls"
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\n{answer}', encoding="utf-8")
    gh.chmod(0o755)
    return bin_dir, calls


def calls_made(calls: Path) -> str:
    """Every recorded call, one per line; empty when gh was never started."""
    return calls.read_text(encoding="utf-8") if calls.exists() else ""
