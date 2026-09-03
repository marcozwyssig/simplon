"""A credential a run needs, supplied without ever becoming a command-line argument.

WHY A LIBRARY AND NOT A PRODUCT'S BUSINESS. Every product that reaches a protected repository faces the
same three decisions, and getting any of them wrong is expensive in a way that is invisible until it
happens: whether to ask at all, where the answer may be written, and what to do when there is nobody to
ask. asbundle reached them first, for the Actifsource Enterprise P2 repository; the NEXT product to need
a password should inherit the answers rather than rediscover them.

THE CONVENTION. A credential is named by a PREFIX. `ACTIFSOURCE` means `ACTIFSOURCE_USER` and
`ACTIFSOURCE_PASSWORD`, and a manifest names the prefix instead of holding a secret - so the file says
WHERE the credential lives and has no field one could be written into. A product repository leaked a
token out of a committed YAML file once; leaving no such field is what stops that repeating.

WHY ONLY THE USERNAME MAY BE AN ARGUMENT. argv is world-readable - `/proc/<pid>/cmdline` on Linux, `ps`
on macOS - and a command line lands in the shell history. A username is not a secret and may be passed;
a password is asked for on the terminal, where `getpass` neither echoes it nor records it, and becomes
an environment variable that only this process and the children it spawns can read.

WHY HALF A CREDENTIAL IS THE SIGNAL. A username with no password is the one unambiguous statement that
a run WANTS the protected thing. A run that supplies neither half is asking for nothing, and must be
asked nothing - which is what lets the same code path serve a build that deliberately runs without the
secret and produces a smaller artefact.

WHY THE TTY GUARD IS NOT POLITENESS. A prompt in CI writes to a pipe nobody reads and then waits for
input that never arrives. The job does not fail; it HANGS, until a timeout kills it, with nothing in the
log to explain the stall. Without a terminal this module asks nothing and says nothing.

WHERE TO ASK. At the START of a run, not at the point of use. A pipeline that asks where the credential
is wanted asks after the downloads, of an operator who has long since walked away - so a caller should
resolve the credential before its first step and let the answer be inherited.
"""
from __future__ import annotations

import getpass
import os
import sys
from typing import Iterable, Mapping, MutableMapping, Tuple

from delivery import log

USER_SUFFIX = "_USER"
PASSWORD_SUFFIX = "_PASSWORD"


def variables(prefix: str) -> Tuple[str, str]:
    """The (user, password) variable NAMES a prefix stands for."""
    return f"{prefix}{USER_SUFFIX}", f"{prefix}{PASSWORD_SUFFIX}"


def credential(prefix: str, env: Mapping[str, str]) -> Tuple[str, str] | None:
    """The (user, password) a prefix resolves to, or None when either half is absent.

    BOTH halves must be present. A username without a password cannot authenticate, and folding half a
    credential into a URL produces a 401 whose message names the wrong problem. Both are stripped: a
    variable set to whitespace is set by accident, never on purpose.
    """
    if not prefix:
        return None
    user_var, password_var = variables(prefix)
    user = (env.get(user_var) or "").strip()
    password = (env.get(password_var) or "").strip()
    return (user, password) if user and password else None


def missing_password_variable(prefixes: Iterable[str], env: Mapping[str, str]) -> str | None:
    """The password variable a half-supplied credential still needs, or None when none does.

    Returns the variable NAME rather than a bool so a caller can name it in the prompt and set exactly
    the variable `credential` reads back. Deciding this away from the terminal is what makes it
    testable - the asking itself is three lines no test can drive.
    """
    for prefix in prefixes or ():
        if not prefix:
            continue
        user_var, password_var = variables(prefix)
        if (env.get(user_var) or "").strip() and not (env.get(password_var) or "").strip():
            return password_var
    return None


def ask_for_password(prefixes: Iterable[str],
                     env: MutableMapping[str, str] | None = None) -> str | None:
    """Ask on the terminal for the password a half-supplied credential needs. Returns what it set.

    Silent and None in all three cases where asking would be wrong: no terminal (see the module note on
    hanging a CI job), nothing missing, and nobody having named a username.

    An empty answer is left UNSET on purpose. Carrying a blank password to the server produces a 401
    whose message blames the repository; leaving it unset lets the caller's own "skipped, and named"
    path report what actually happened.
    """
    env = os.environ if env is None else env
    if not sys.stdin.isatty():
        return None

    variable = missing_password_variable(prefixes, env)
    if not variable:
        return None

    answer = getpass.getpass(f"{variable} (not echoed): ")
    if not answer:
        log.warn(f"no {variable} given; whatever needs it will be skipped")
        return None

    env[variable] = answer
    return variable
