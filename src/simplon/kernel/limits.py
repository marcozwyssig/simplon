"""The time limits of the kernel's network-bound subprocess calls: one default per tool class (si#654).

A hung remote is a hung run, and a run that hangs is neither green nor red. These are the defaults a call
of that class gets when it does not say otherwise; a call that needs another limit passes its own
`timeout=` and says why next to it. `src/tests/test_network_limits.py` scans the kernel for a `run()` of one
of these classes that carries no `timeout=`, so a new one cannot join quietly.

Past its limit `run` stops the child and returns a Result with `timed_out`, whose `err` names the tool,
the operation and the limit (si#653, si#654).

WHAT THE NUMBERS ARE. Only `GH` rests on a measurement: it is the 60 s `adapters/gh.py` and
`adapters/tracker.py` already used, whose own note measured both of the tracker's calls well under 2 s.
The others are generous bounds chosen without one, so that a slow but working transfer is not cut off;
a measured run that needs more is the reason to change them.

`stream()` is outside this on purpose: an upload (`oras push`, `gh release upload`, `docker push`) is a
transfer somebody is watching, and its length is the size of what it carries.
"""
from __future__ import annotations

#: git operations that talk to a remote. `gitops._git` gives each of them `GIT_REMOTE`.
GIT_REMOTE_OPS = frozenset({"clone", "fetch", "ls-remote", "pull", "push"})

#: A git operation against a remote: fetch, pull, push, ls-remote.
GIT_REMOTE = 300.0

#: One `gh` call (an API request, not an upload).
GH = 60.0

#: One `oras` call that reads or logs in (a manifest, a tag list), not a push or a pull.
ORAS = 120.0

#: One `docker pull` of a product's image.
DOCKER_PULL = 900.0
