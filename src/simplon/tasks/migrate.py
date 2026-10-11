"""`support manifest migrate` - rewrite a manifest from `groups:` to `ci:` / `cd:` / `support:` (si#344).

A TEXT SPLICE, the way `toolchain scaffold` writes (si#110): every byte the move does not have to touch
is the byte that was there - comments first among them, then flow style and key order. A manifest is a
document people annotate; a migration that round-tripped it through a YAML library would hand back the
data and throw away the reasons.

AND NOTHING IS TRUSTED THAT WAS NOT PARSED BACK. The spliced text is loaded again and compared with what
the original says the new form must contain. If they differ, nothing is written and the difference is
named. A splice that is wrong in a way nobody reads is worse than no splice.

THREE OUTCOMES, AND THEY STAY THREE: migrated, already current, refused. "Nothing to migrate" is rc 0
with its own sentence - it is not the same green as "migrated", and it is not a failure either.

WHAT MOVES, AND WHAT A MOVE TAKES WITH IT. The unit of the splice is a BLOCK: a key line, every line
under it, and the comment lines directly above it. The last part is the one a reader notices: a
`# --- deploy ---` banner belongs to the group it announces, so it travels with `deploy:` into `cd:`
instead of staying behind at the end of `ci:`. Lines move whole, so a trailing comment goes where its
line goes. The one block that is DELETED rather than moved, `env_groups:`, takes the comments above it
along: they explained a key the ci/cd form no longer has.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import NamedTuple

import yaml

CI = ("build", "test", "release")
CD = ("deploy", "monitor")
ENV_KEYS = ("default", "environments")
DOCS_SITE_KEYS = ("image", "base_url", "theme", "source", "output")
_TOP = re.compile(r"^(?P<key>[A-Za-z0-9_][A-Za-z0-9_.-]*):(?P<rest>.*)$")
_CHILD = re.compile(r"^  (?P<key>[A-Za-z0-9_][A-Za-z0-9_.-]*):(?P<rest>.*)$")


class Migration(NamedTuple):
    status: str            # "migrated" | "current" | "refused"
    text: str              # the new text ("migrated"), else the input unchanged
    moved: tuple[str, ...] = ()  # one human-readable line per section moved
    reason: str = ""       # "refused" only: what could not be migrated, naming the line


def _blocks(lines: list[str], key_re: re.Pattern, indent: int) -> list[tuple[str | None, list[str]]]:
    """Split `lines` into (key, lines) blocks at `indent`. Comment and blank lines directly above a key
    line belong to that key's block; anything before the first key is a (None, lines) preamble.

    "Directly above" is read by POSITION, not by exact indent: a comment at the key's indent OR LESS
    counts. firn writes a column-0 banner inside `groups:` above `  deploy:`, and it announces deploy -
    read by exact indent, it became the tail of `support:`, which cannot then be dedented. A comment
    indented DEEPER than the key is still the previous block's content (a commented-out command)."""
    blocks: list[tuple[str | None, list[str]]] = [(None, [])]
    pending: list[str] = []
    for line in lines:
        match = key_re.match(line)
        stripped = line.strip()
        if match:
            blocks.append((match.group("key"), pending + [line]))
            pending = []
        elif not stripped or (stripped.startswith("#") and len(line) - len(line.lstrip()) <= indent):
            pending.append(line)
        else:
            if pending:
                blocks[-1][1].extend(pending)
                pending = []
            blocks[-1][1].append(line)
    if pending:
        blocks[-1][1].extend(pending)
    return blocks


def _reindent(lines: list[str], by: int) -> list[str]:
    """Shift every non-blank line by `by` spaces. A negative shift removes exactly that many; a line
    with fewer leading spaces would change what the YAML says, so it is a bug, not a case."""
    if by >= 0:
        return [" " * by + line if line.strip() else line for line in lines]
    cut = -by
    out = []
    for line in lines:
        if not line.strip():
            out.append(line)
            continue
        assert line[:cut] == " " * cut, f"cannot dedent {cut}: {line!r}"
        out.append(line[cut:])
    return out


def _is_docs_site(value: object) -> bool:
    """A top-level `site:` is the docs site (now `website:`) when it carries one of the Hugo keys; a
    `site:` without them is something else a product named site, and is left alone."""
    return isinstance(value, dict) and any(key in value for key in DOCS_SITE_KEYS)


def _expected(old: dict, unknown_groups_into: str | None = None) -> dict:
    """What the new form must contain, built from the old form's DATA - the oracle the splice is
    checked against. It knows nothing about lines, which is why it can check them."""
    out = {k: v for k, v in old.items() if k not in ("groups", "env_groups", "default", "environments")}
    groups = old.get("groups") or {}
    ci = {n: groups[n] for n in CI if n in groups}
    cd = {k: old[k] for k in ENV_KEYS if k in old}
    cd.update({n: groups[n] for n in CD if n in groups})
    if unknown_groups_into is not None:
        area = ci if unknown_groups_into == "ci" else cd
        area.update({n: v for n, v in groups.items() if n not in CI + CD + ("support",)})
    if ci:
        out["ci"] = ci
    if cd:
        out["cd"] = cd
    if "support" in groups:
        out["support"] = groups["support"]
    if _is_docs_site(old.get("site")):
        out["website"] = out.pop("site")
    return out


def _first_difference(a: object, b: object, path: str = "") -> str:
    """The first dotted key path at which `a` and `b` differ ('' when they are equal)."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in list(a) + [k for k in b if k not in a]:
            where = f"{path}.{key}" if path else str(key)
            if key not in a or key not in b:
                return where
            found = _first_difference(a[key], b[key], where)
            if found:
                return found
        return ""
    return "" if a == b else (path or "<top level>")


def _render(value: object) -> str:
    """An `env_groups:` value the way a reader wrote it: `[deploy, monitor]`."""
    if isinstance(value, list):
        return "[" + ", ".join(str(item) for item in value) + "]"
    return str(value)


def _area(key: str, head: list[str], children: list[list[str]]) -> list[str]:
    """`key:` followed by its children. Blank lines directly under the key line are dropped: they
    separated a moved block from whatever stood above it in its old place, and above it now is `key:`."""
    body = [line for child in children for line in child]
    while body and not body[0].strip():
        body.pop(0)
    return head + [f"{key}:"] + body


def _accounting(old: list[str], new: list[str], removed: list[str], added: list[str]) -> tuple[str, str]:
    """The check the data comparison cannot make: every non-blank line of the original is in the new
    text, compared stripped (a move reindents), except the ones the splice deletes on purpose, and
    nothing else appears but the key lines it writes. YAML keeps the last of two equal keys and drops
    every comment, so a splice that loses either still parses back to the same data - measured on
    cleon, whose duplicated `support:` group was dropped by a first draft that the data check passed.
    Returns the first lost line ('line N: ...') and the first extra line, '' for none."""
    def counted(lines: list[str]) -> Counter:
        return Counter(line.strip() for line in lines if line.strip())

    lost = counted(old) - counted(removed) - counted(new)
    extra = counted(new) - counted(added) - (counted(old) - counted(removed))
    first_lost = next((f"line {n}: {line.strip()}" for n, line in enumerate(old, 1)
                       if lost[line.strip()]), "")
    first_extra = next((line.strip() for line in new if extra[line.strip()]), "")
    return first_lost, first_extra


def migrate_text(text: str, *, unknown_groups_into: str | None = None) -> Migration:
    """Splice `text` from the `groups:` form into the ci/cd form; see the module head for the rules."""
    if unknown_groups_into not in (None, "ci", "cd"):
        raise ValueError(f"unknown_groups_into must be 'ci' or 'cd', not {unknown_groups_into!r}")
    old = yaml.safe_load(text)
    if not isinstance(old, dict):
        return Migration("current", text)
    docs_site = _is_docs_site(old.get("site"))
    if not (any(k in old for k in ("groups", "env_groups") + ENV_KEYS) or docs_site):
        return Migration("current", text)

    def refused(reason: str) -> Migration:
        return Migration("refused", text, (), reason)

    lines = text.splitlines()
    blocks = _blocks(lines, _TOP, 0)
    keys = [key for key, _ in blocks]
    moved: list[str] = []

    # Rule 2 (and 1): the groups block, split into its children and sorted into areas.
    ci: list[list[str]] = []
    cd: list[list[str]] = []
    support: list[str] = []  # a list of lines, not one block: a duplicate key keeps both copies
    groups_head: list[str] = []
    groups_preamble: list[str] = []
    groups_comment = ""  # a trailing comment on the `groups:` key line, carried onto the first area
    removed: list[str] = []  # lines the splice deletes on purpose - the line accounting's allowance
    added: list[str] = []    # lines the splice writes that the original did not have
    if keys.count("groups") > 1:
        numbers = [n for n, line in enumerate(lines, 1) if _TOP.match(line) and line.startswith("groups:")]
        return refused(f"groups: is declared twice at the top level, on lines {numbers[0]} and "
                       f"{numbers[1]} - merge them by hand first")
    if "groups" in keys:
        index = keys.index("groups")
        block = blocks[index][1]
        at = next(i for i, line in enumerate(block) if _TOP.match(line))
        number = sum(len(prior) for _, prior in blocks[:index]) + at + 1  # 1-based, of the key line
        rest = _TOP.match(block[at]).group("rest")
        if rest.lstrip().startswith(("{", "[")):
            return refused(f"groups: is written in flow style on line {number}; the splice moves "
                           "block-style sections only - rewrite it in block style and run again")
        groups_head = block[:at]
        groups_comment = rest
        removed.append(block[at])
        children = _blocks(block[at + 1:], _CHILD, 2)
        groups_preamble = children[0][1]
        first = number + 1 + len(groups_preamble)  # line number of each child block's first line
        for name, child in children[1:]:
            first, starts = first + len(child), first
            if name in CI or (name not in CD + ("support",) and unknown_groups_into == "ci"):
                ci.append(child)
                moved.append(f"groups: {name} -> ci: {name}")
            elif name in CD or (name != "support" and unknown_groups_into == "cd"):
                cd.append(child)
                moved.append(f"groups: {name} -> cd: {name}")
            elif name == "support":
                shallow = next((i for i, line in enumerate(child)
                                if line.strip() and not line.startswith("  ")), None)
                if shallow is not None:
                    column = len(child[shallow]) - len(child[shallow].lstrip())
                    return refused(f"groups: support carries line {starts + shallow} at column {column} "
                                   f"({child[shallow].strip()[:40]!r}); support: moves to the top level by "
                                   "removing two spaces from each of its lines, and that line has only "
                                   f"{column} to remove - indent it or move it out of the support group, "
                                   "and run again")
                support += _reindent(child, -2)
                moved.append("groups: support -> support")
            else:
                return refused(f"groups: {name} is none of {', '.join(CI + CD + ('support',))} - a "
                               "manifest loaded against the platform catalogue cannot have it, so there "
                               "is no area to move it to")

    # Rule 3: default / environments, under cd: before its groups.
    env_blocks = [block for key, block in blocks if key in ENV_KEYS]
    for key, _ in blocks:
        if key in ENV_KEYS:
            moved.append(f"{key} -> cd: {key}")
    env_lines = [_reindent(block, 2) for block in env_blocks]

    # Rule 4: env_groups: deleted, if what it says is what cd: now says.
    if "env_groups" in old:
        value = old["env_groups"]
        if not (isinstance(value, list) and len(set(value)) == len(value) and set(value) <= set(CD)):
            return refused(f"env_groups: {_render(value)} names a group outside cd:. Under the ci/cd form "
                           "only what stands under cd: takes an environment, so this manifest has to "
                           "decide by hand where those commands belong")
        owned = [line for line in blocks[keys.index("env_groups")][1] if line.strip()]
        removed += owned
        comments = sum(1 for line in owned if line.strip().startswith("#"))
        said = f" with the {comments} comment line{'s' if comments != 1 else ''} it owns" if comments else ""
        moved.append(f"env_groups: deleted ({_render(value)}){said}")

    # Assemble: the new areas replace groups: in place; cd: stands at the first env key if there is
    # no groups: to stand in for, or groups: had no deploy/monitor to give it.
    cd_block = _area("cd", [], env_lines + cd) if (env_lines or cd) else []
    cd_with_groups = "groups" in keys and bool(cd)
    out: list[str] = []
    cd_placed = False
    for key, block in blocks:
        if key == "groups":
            areas: list[str] = []
            if ci:
                areas += _area("ci", [], ci)
            if cd_block and cd_with_groups:
                areas += cd_block
                cd_placed = True
            if support:
                areas += support
            if areas:
                head_end = areas.index(next(line for line in areas if _TOP.match(line))) + 1
                areas[head_end - 1] += groups_comment
                areas[head_end:head_end] = [line for line in groups_preamble if line.strip()]
            added += [line for line in areas if _TOP.match(line) and line.split(":")[0] in ("ci", "cd")]
            out += groups_head + areas
        elif key in ENV_KEYS:
            if cd_block and not cd_with_groups and not cd_placed:
                out += cd_block
                added.append(cd_block[0])
                cd_placed = True
        elif key == "env_groups":
            continue
        elif key == "site" and docs_site:
            renamed = [re.sub(r"^site:", "website:", line, count=1) for line in block]
            removed += [line for line in block if line.startswith("site:")]
            added += [line for line in renamed if line.startswith("website:")]
            out += renamed
            moved.append("site -> website")
        else:
            out += block
    new = "\n".join(out) + ("\n" if text.endswith("\n") else "")

    # The verification: the splice is trusted only as far as it parses back to the oracle.
    try:
        parsed = yaml.safe_load(new)
    except yaml.YAMLError as error:
        return refused(f"the spliced text does not parse back to the same manifest: {error}")
    expected = _expected(old, unknown_groups_into)
    if parsed != expected:
        return refused("the spliced text does not parse back to the same manifest: "
                       f"{_first_difference(expected, parsed)}")
    lost, extra = _accounting(lines, new.splitlines(), removed, added)
    if lost:
        return refused(f"the spliced text loses a line the original had: {lost}")
    if extra:
        return refused(f"the spliced text has a line the original did not: {extra}")
    return Migration("migrated", new, tuple(moved))
