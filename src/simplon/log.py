"""Logging + ANSI colorizers for the *ctl orchestrators, ported byte-for-byte from netctl.sh:77-81
and 1449-1480 so the CLI's output is diff-identical to the bash original during the #102 migration.

`info/ok/warn/die` carry the same `[HH:MM:SS] ==>` timestamped prefixes; the colorizers
(`dot/code_color/boot_color/err_color`) reproduce the exact escape sequences and width padding the
status dashboard used. `die` prints to stderr and raises SystemExit(1) - the Python equivalent of the
bash `die() { ... >&2; exit 1; }`.
"""
from __future__ import annotations

import sys
from datetime import datetime
from typing import NoReturn

_RESET = "\033[0m"


def _ts() -> str:
    """The shared HH:MM:SS prefix (netctl.sh:77)."""
    return datetime.now().strftime("%H:%M:%S")


def info(msg: str) -> None:
    print(f"\033[1;34m[{_ts()}] ==>\033[0m {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"\033[1;32m[{_ts()}]  OK\033[0m {msg}", flush=True)


def warn(msg: str) -> None:
    # Matches bash: only `die` writes to stderr; `warn` goes to STDOUT (netctl.sh:80 vs 81).
    print(f"\033[1;33m[{_ts()}]   !\033[0m {msg}", flush=True)


def die(msg: str) -> NoReturn:
    print(f"\033[1;31m[{_ts()}] ERR\033[0m {msg}", file=sys.stderr)
    raise SystemExit(1)


def _pad(txt: str, width: int) -> str:
    """Left-justify to `width` on the PLAIN text (the colour escapes wrap the padded string), matching
    the bash `printf "%-${w}s"` before the ANSI wrap."""
    return f"{txt:<{width}}"


def dot(txt: str, width: int = 0) -> str:
    """Colorize a container state, padded to `width` (netctl.sh:1449): running=green, absent=red,
    anything else=yellow. Empty/absent normalises to the literal 'absent'."""
    if txt in ("", "absent"):
        txt = "absent"
    disp = _pad(txt, width)
    if txt == "running":
        return f"\033[1;32m{disp}{_RESET}"
    if txt == "absent":
        return f"\033[1;31m{disp}{_RESET}"
    return f"\033[1;33m{disp}{_RESET}"


def code_color(txt: str, width: int = 0) -> str:
    """Colorize an HTTP code (netctl.sh:1459): 000->'down' red, 2xx green, else yellow. The colour is
    chosen on the ORIGINAL code, the displayed text on the normalised one (000 shows as 'down')."""
    disp_txt = "down" if txt == "000" else txt
    disp = _pad(disp_txt, width)
    if txt == "000":
        return f"\033[1;31m{disp}{_RESET}"
    if txt.startswith("2"):
        return f"\033[1;32m{disp}{_RESET}"
    return f"\033[1;33m{disp}{_RESET}"


def boot_color(txt: str, width: int = 0) -> str:
    """started=green, failed=red, anything else=yellow (netctl.sh:1469)."""
    disp = _pad(txt, width)
    if txt == "started":
        return f"\033[1;32m{disp}{_RESET}"
    if txt == "failed":
        return f"\033[1;31m{disp}{_RESET}"
    return f"\033[1;33m{disp}{_RESET}"


def err_color(n: int, width: int = 0) -> str:
    """0=green, >0=red (netctl.sh:1477)."""
    disp = _pad(str(n), width)
    if n > 0:
        return f"\033[1;31m{disp}{_RESET}"
    return f"\033[1;32m{disp}{_RESET}"
