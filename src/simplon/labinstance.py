"""Lab-instance resolution: WHICH of N isolated labs a command acts on (netctl#1404, epic netctl#1403).

A `*ctl` product that runs several isolated labs on one host has to answer that question exactly once per
process, and the answer follows a precedence that carries no product knowledge at all:

1. an explicit ``--instance`` FLAG value (when given and non-blank),
2. else the product's instance ENV var when set and non-empty (the CI/agent override),
3. else, when the checkout is a LINKED git worktree, an id DERIVED from the worktree basename
   (normalised + hashed into the product's id-length budget),
4. else the product's reserved DEFAULT id.

Step 3 is the one that looks product-specific and is not: it exists because an agent working in a git
worktree must not act on the main checkout's lab, which is a property of the TOOLING, not of the product.

The three product-specific values - the env var's spelling, the reserved default id and the id-length
budget - reach this module as manifest DATA through ``delivery.context``, never as an import:

```yaml
instance:
  env_var: NETCTL_INSTANCE   # the variable carrying the resolved id to child processes
  default: dev               # the reserved default id (collapses every derived name to the bare base)
  max_id_len: 2              # the product's id-length budget (netctl: the 15-char IFNAMSIZ ceiling)
```

The derivations are PURE. ``resolve`` performs exactly two reads: the manifest (through the context, so
a test registers a fake one) and the single INJECTABLE worktree probe, deliberately kept out of the
derivation so the precedence is unit-testable without touching the filesystem.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import NamedTuple

from delivery import context

# The manifest section carrying the three product values above.
MANIFEST_SECTION = "instance"

# The ifname-safe id charset. base36, so a hashed id is itself a legal lab id and never needs a second
# normalisation pass. Matches the ``[a-z0-9]`` class a product's own id validation enforces.
_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

# Sentinel distinguishing "caller did not inject a worktree" (probe the real checkout) from an injected
# ``None`` (caller asserts 'this IS the main checkout'). Keeps resolve unit-testable without touching the
# filesystem while the bare call still probes for real.
_PROBE = object()


class InstanceSpec(NamedTuple):
    """The product's instance data, as declared in its manifest's ``instance:`` section."""

    env_var: str
    default: str
    max_id_len: int


def spec() -> InstanceSpec:
    """Read the product's ``instance:`` section RAW through ``delivery.context`` (the same seam the build
    data and the environments listing use). Fails loudly naming the manifest and the missing/invalid key,
    so a yaml typo surfaces here rather than as a lab silently resolving to the wrong tenant."""
    ctx = context.current()
    data = ctx.manifest_data().get(MANIFEST_SECTION)
    if not isinstance(data, dict):
        raise ValueError(f"delivery: manifest {ctx.manifest_path} is missing the '{MANIFEST_SECTION}' section")
    env_var = str(data.get("env_var") or "").strip()
    default = str(data.get("default") or "").strip()
    raw_len = data.get("max_id_len")
    for key, present in (("env_var", bool(env_var)), ("default", bool(default)),
                         ("max_id_len", raw_len is not None)):
        if not present:
            raise ValueError(
                f"delivery: manifest {ctx.manifest_path} is missing '{MANIFEST_SECTION}.{key}'")
    # `isinstance` rather than `int(...)`: yaml parses `2.5` to a float, and int() would silently truncate
    # it to a legal-looking 2 - exactly the quiet drift this loud read exists to prevent. bool is an int
    # subclass, so `max_id_len: true` has to be rejected explicitly.
    if isinstance(raw_len, bool) or not isinstance(raw_len, int):
        raise ValueError(
            f"delivery: manifest {ctx.manifest_path} '{MANIFEST_SECTION}.max_id_len' must be an integer, "
            f"got {raw_len!r}")
    max_id_len = raw_len
    if max_id_len < 1:
        raise ValueError(
            f"delivery: manifest {ctx.manifest_path} '{MANIFEST_SECTION}.max_id_len' must be >= 1, "
            f"got {max_id_len}")
    return InstanceSpec(env_var, default, max_id_len)


def hash_to_id(text: str, length: int) -> str:
    """Fold ``text`` deterministically into ``length`` chars of ``_ID_ALPHABET``. sha1-based (stable
    across processes, unlike the salted builtin ``hash``), so the same worktree derives the same id on
    every run and on every host. PURE."""
    digest = int(hashlib.sha1(text.encode("utf-8")).hexdigest(), 16)
    chars = []
    for _ in range(length):
        digest, rem = divmod(digest, len(_ID_ALPHABET))
        chars.append(_ID_ALPHABET[rem])
    return "".join(chars)


def from_worktree(basename: str, max_id_len: int) -> str:
    """Derive a stable, ifname-safe lab id from a git-worktree ``basename`` (precedence step 3).
    PURE + deterministic. Normalise to ``[a-z0-9]``; if the normalised form already fits ``max_id_len``
    (a short human-named worktree like ``a1``) keep it verbatim, else fold the FULL basename to a stable
    ``max_id_len``-char hash (an ``agent-<hex>`` worktree -> a 2-char id for netctl). Hashing the whole
    basename (not the truncated prefix) is what keeps two differently-named worktrees from collapsing onto
    the same id. An empty / all-punctuation basename has no usable chars, so it hashes too and never
    yields an empty (illegal) id. The result always satisfies the product's id validation."""
    normalised = re.sub(r"[^a-z0-9]", "", basename.lower())
    if 1 <= len(normalised) <= max_id_len:
        return normalised
    return hash_to_id(basename, max_id_len)


def worktree_basename(root: Path) -> str | None:
    """The ONE filesystem probe behind the worktree fallback (IMPURE, kept out of the pure derivation).
    Returns the basename of ``root`` IFF it is a LINKED git worktree - whose top-level ``.git`` is a FILE
    (``gitdir: ...`` pointer), as agent worktrees are - else ``None`` for the main checkout (a real ``.git``
    DIRECTORY) or a non-git tree. So the reserved default id is preserved for the main checkout, and only
    sibling worktrees auto-derive an isolated id."""
    return root.name if (root / ".git").is_file() else None


def resolve(flag: str | None = None, *, worktree: object = _PROBE) -> str:
    """Resolve the lab instance id by the four-step precedence at the top of this module. THE single
    resolution point: an explicit ``flag`` wins, else the manifest-named env var, else a linked worktree's
    derived id, else the manifest's reserved default.

    The MAIN checkout has no worktree basename (its ``.git`` is a directory) and still resolves to the
    default, so a product's single-tenant human UX is byte-for-byte unchanged. ``worktree`` is injectable
    purely for tests (the basename, or ``None`` to assert the main-checkout branch); left unset it probes
    the real checkout via ``delivery.context.current().root``. The derived id always satisfies the
    product's id validation, so import-time resolution never fails loudly."""
    if flag is not None and flag.strip():
        return flag.strip()
    product = spec()
    value = os.environ.get(product.env_var, "").strip()
    if value:
        return value
    basename = worktree_basename(context.current().root) if worktree is _PROBE else worktree
    if isinstance(basename, str) and basename:
        return from_worktree(basename, product.max_id_len)
    return product.default
