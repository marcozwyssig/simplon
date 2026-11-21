"""Which values are secret, and the one place output asks (si#833).

THE GAP THIS CLOSES. Every mechanism the kernel had for a credential was keyed by WHICH SITE - `getpass`
in `credentials.py`, `-e NAME` by name in `carrier.py`, `--env-file` in `nuget.py`, `run.shown` for a failed
call - and none by WHICH VALUE. A value that reached a log line through a site nobody had looked at (a
`directories:` path templated from a token, si#809; a compose image resolved from one, si#785) was printed,
and nothing could say it should not have been, because nothing knew it was secret.

WHERE A ROLE COMES FROM (Option C, decided by Marco 2026-11-21). A name is `SECRET` or `PLAIN`, exactly two
values and no "unknown" - the ambiguous value is excluded at this seam:

- a kernel READER says it, in the same edit that spells the name: `credentials.variable_roles` (the user
  half plain, the password half secret), `portainer.variable_roles`, `carrier.variable_roles`, and the
  launcher's forwarded fixed names (`launcherenv.FORWARDED_ROLES`). Not a name pattern: the reader that
  already knows which half of a pair it is reading says so;
- a command's `env: pass:` name is secret by role. The kernel only forwards it and never interpolates it,
  so calling it secret costs nothing and needs no declaration (`launcherenv.within` reads each through
  `read`);
- a `required:`/`optional:` name is plain unless the environment lists it under `secret:` - the one place
  no reader can know (`environments.Environment.secret`).

WHAT THE KERNEL DOES WITH IT.

- `read(name)` is how kernel code reads a secret value: it declares the name secret and REGISTERS the
  value. A multi-line value (a private key) is registered line by line as well as whole.
- `redact(text)` turns every registered value into `***`, longest first. The SINKS call it, not the sites:
  `install` wraps `sys.stdout`/`sys.stderr` at dispatch (every `log.*`, every `print`, the top-level refusal
  and traceback render), and the file sinks call it themselves - the step log, the run transcript and a
  streaming step's identity. Asking each of the hundreds of sites would rebuild the per-site defect.
- `check_argv(argv)` refuses an argv that carries a registered value, naming the variable and never the
  value. No manifest can trip it, because a manifest literal is never a registered secret; it catches a
  kernel change that writes `-e NAME=$value` - a diagnosis of a kernel bug, not a rule for products.
- In GitHub Actions (`GITHUB_ACTIONS=true`) registering a value prints `::add-mask::<line>` for each of its
  lines, at run time, to the process's real stdout - so the runner masks it in every later line, the
  child processes' included.

WHAT IT DOES NOT COVER, said rather than implied. A child started with `capture=False` writes straight to
the file descriptor and nothing in Python sees it (in Actions the runtime mask covers it). Portainer stores
a stack's environment by design. A value split across two separate writes to a stream is not seen whole.
And `docker inspect` of the kernel's container shows the forwarded values in Config.Env: ACCEPTED, because
reading another container's Config.Env takes the docker socket, which is root-equivalent on that host - a
principal who can read it could already read this process's memory. REOPEN TRIGGER: a docker daemon shared
with a principal who is not root-equivalent on that host (a shared remote DOCKER_HOST, a multi-tenant
runner). The fix then is #827's pattern, values as files in a tmpfs, taken into the launcher's hop.

NO MINIMUM LENGTH. A one-character secret would mask that character everywhere; no rule is written until
a real secret that short is measured (decided 2026-11-21).

LIBRARY BY INTENT, in the kernel layer: it knows no manifest and no reader. The layers above hand it roles.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Mapping
from typing import TextIO

SECRET = "secret"
PLAIN = "plain"
ROLES = (SECRET, PLAIN)

#: What a registered value is replaced with.
MASK = "***"

#: The variable GitHub sets to "true" in every Actions job.
ACTIONS_ENV = "GITHUB_ACTIONS"

#: Names declared so far in this process, and their role. A name declared SECRET anywhere stays secret: a
#: second reader calling it plain cannot make a value printable that another reader holds as a credential.
_roles: dict[str, str] = {}

#: Every registered value (and every line of a multi-line one) -> the variable it was read from.
_values: dict[str, str] = {}


class SecretInArgv(ValueError):
    """A command line that would carry a secret value. Names the variable, never the value."""


def declare(roles: Mapping[str, str]) -> None:
    """Record what the readers say about each name. A role outside `ROLES` is a kernel bug and raises."""
    for name, role in roles.items():
        if role not in ROLES:
            raise ValueError(f"{name}: role must be one of {', '.join(ROLES)}, got {role!r}")
        if _roles.get(name) != SECRET:
            _roles[name] = role


def role(name: str) -> str:
    """`SECRET` when a reader, an `env: pass:` or a `secret:` list said so; `PLAIN` otherwise."""
    return SECRET if _roles.get(name) == SECRET else PLAIN


def _mask_stream() -> TextIO | None:
    """Where `::add-mask::` goes: the process's REAL stdout, never the redacting wrapper (which would turn
    the command into `::add-mask::***`) and never a step capture (which would hold it back from the
    runner until after the value was printed)."""
    return sys.__stdout__


def register(name: str, value: str) -> None:
    """Remember `value` as `name`'s, so every sink redacts it. Empty and whitespace-only values are not
    registered: there is nothing to hide, and masking whitespace would mangle every line."""
    pieces = [value.strip(), *(line.strip() for line in value.splitlines())]
    actions = os.environ.get(ACTIONS_ENV) == "true"
    for piece in dict.fromkeys(pieces):
        if not piece or piece in _values:
            continue
        # A workflow command is ONE line: `::add-mask::` of a multi-line value would print every line after
        # the first in clear. The whole value is masked through its lines, each registered on its own.
        if actions and "\n" not in piece:
            stream = _mask_stream()
            if stream is not None:
                stream.write(f"::add-mask::{piece}\n")
                stream.flush()
        _values[piece] = name


def read(name: str, environ: Mapping[str, str] | None = None) -> str:
    """The value of the secret `name`, or "" when it is unset - and from now on redacted wherever it is
    printed. Calling it IS the declaration: a reader that reads a credential through here cannot forget
    to say it is one."""
    source = os.environ if environ is None else environ
    declare({name: SECRET})
    value = source.get(name) or ""
    register(name, value)
    return value


def register_present(roles: Mapping[str, str], environ: Mapping[str, str] | None = None) -> None:
    """Declare `roles` and register the value of every secret-role name among them that is set."""
    declare(roles)
    source = os.environ if environ is None else environ
    for name, given in roles.items():
        if given == SECRET and source.get(name):
            register(name, source[name])


def redact(text: str) -> str:
    """`text` with every registered value replaced by `MASK`, the longest first so a value that contains
    another is masked whole."""
    if not _values or not text:
        return text
    for value in sorted(_values, key=len, reverse=True):
        if value in text:
            text = text.replace(value, MASK)
    return text


def check_argv(argv: Iterable[str]) -> None:
    """Refuse an argv that carries a registered value. A secret crosses a process boundary by NAME
    (`docker run -e NAME`, `--env-file`, `--password-stdin`), never on the command line, which every user
    of the machine can read in `/proc/<pid>/cmdline` and `ps`."""
    for arg in argv:
        for value, name in _values.items():
            if value in str(arg):
                raise SecretInArgv(
                    f"a command line would carry the value of {name}, which is secret - every user of this "
                    f"machine could read it in `ps`. It has to cross by name (`docker run -e {name}`), an "
                    f"env file or stdin. This is a kernel defect: report it with the command that ran")


class _Redacting:
    """`sys.stdout`/`sys.stderr` with every write redacted. Subclasses nothing, for the measured reason
    `steps._StdoutRouter` records: `io.TextIOBase`'s `encoding` cannot be carried. Every other member is
    the wrapped stream's, so `isatty`, `fileno` and `encoding` answer as before."""

    def __init__(self, under: TextIO) -> None:
        self.under = under

    def write(self, text: str) -> int:
        self.under.write(redact(text))
        return len(text)

    def writelines(self, texts: Iterable[str]) -> None:
        for text in texts:
            self.write(text)

    def __getattr__(self, attribute: str) -> object:
        return getattr(self.under, attribute)


def install() -> None:
    """Wrap this process's stdout and stderr so every write is redacted. Idempotent: a stream already
    wrapped is left as it is."""
    if not isinstance(sys.stdout, _Redacting):
        sys.stdout = _Redacting(sys.stdout)
    if not isinstance(sys.stderr, _Redacting):
        sys.stderr = _Redacting(sys.stderr)


def reset() -> None:
    """Forget every role and value - for a test, which must not inherit another test's secrets."""
    _roles.clear()
    _values.clear()
