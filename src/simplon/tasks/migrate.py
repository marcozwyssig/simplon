"""`support manifest migrate` - rewrite a manifest into the current form: `groups:` to `ci:` / `cd:` /
`support:`, and `images:` into `artifacts:` with a kind on every entry (si#344).

A TEXT SPLICE, the way `toolchain scaffold` writes (si#110): every byte the move does not have to touch
is the byte that was there - comments first among them, then flow style and key order. A manifest is a
document people annotate; a migration that round-tripped it through a YAML library would hand back the
data and throw away the reasons.

AND NOTHING IS TRUSTED THAT WAS NOT PARSED BACK. The spliced text is loaded again and compared with what
the original says the new form must contain. If they differ, nothing is written and the difference is
named. A splice that is wrong in a way nobody reads is worse than no splice.

FOUR PASSES, ONE COMMAND (si#344 B2, C.2). `_dedupe` runs first: a key written twice is dropped when the second
copy is the first line for line, and refused when they differ (si#344 B2, decision 4). `_shape` is cut 1
(`groups:` into `ci:` / `cd:` / `support:`); `_fold` is cut 2 (`images:` into `artifacts:` with `kind: image`,
a `kind:` on every artifacts entry, `source:` into `path:`, `deploy: source: { images: }` into
`{ artifacts: }`). A product still on the `groups:` form arrives in the current form in one run, and one that
already ran cut 1 reruns the same command for cut 2. Each pass is spliced, parsed back against its own oracle and
line-accounted on its own; a refusal in any pass writes nothing, so no pass is ever half-applied. `_bind` is si#344 C.2:
`with: { name: X }` on a port task becomes `produces:`/`consumes:`; what it cannot rewrite safely stays, and the
loader reads it as the same binding.

THREE OUTCOMES, AND THEY STAY THREE: migrated, already current, refused. "Nothing to migrate" is rc 0
with its own sentence - it is not the same green as "migrated", and it is not a failure either.

WHAT MOVES, AND WHAT A MOVE TAKES WITH IT. The unit of the splice is a BLOCK: a key line, every line
under it, and the comment lines directly above it. The last part is the one a reader notices: a
`# --- deploy ---` banner belongs to the group it announces, so it travels with `deploy:` into `cd:`
instead of staying behind at the end of `ci:`. Lines move whole, so a trailing comment goes where its
line goes. The one block that is DELETED rather than moved, `env_groups:`, takes the comments above it
along: they explained a key the ci/cd form no longer has.

A COLUMN-0 COMMENT IS A GUESS, AND THE RUN SAYS SO (si#406). Inside `groups:` a comment at column 0 is
read as the next group's, by position, because nothing else can be read from it - in firn one of three
such banners above `deploy:` announced deploy, and the other two announced top-level sections. The move
keeps the guess and names every such run of lines as a warning, with the area it went to. And the areas
the splice writes one after another stand a blank line apart, as top-level sections do.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import yaml

from simplon.kernel import log
from simplon.domain.artifactschema import PORTS
from simplon.domain.artifactsection import READERS, REFINES
from simplon.domain.treeform import DOCS_SITE_KEYS
from simplon.domain.yamlkeys import UniqueKeyLoader, duplicates

#: The phase groups each area holds. A second statement of the catalogue's `ci` / `cd` groups, kept here
#: because this module reads a manifest the catalogue-backed loader refuses;
#: `test_the_migrations_areas_are_the_catalogues` holds the two together.
CI = ("build", "test", "release")
CD = ("deploy", "monitor")
ENV_KEYS = ("default", "environments")
_TOP = re.compile(r"^(?P<key>[A-Za-z0-9_][A-Za-z0-9_.-]*):(?P<rest>.*)$")
_CHILD = re.compile(r"^  (?P<key>[A-Za-z0-9_][A-Za-z0-9_.-]*):(?P<rest>.*)$")


class Migration(NamedTuple):
    status: str            # "migrated" | "current" | "refused"
    text: str              # the new text ("migrated"), else the input unchanged
    moved: tuple[str, ...] = ()  # one human-readable line per section moved
    reason: str = ""       # "refused" only: what could not be migrated, naming the line
    checks: tuple[str, ...] = ()  # "migrated" only: what the splice moved but cannot vouch for (si#406)


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


def _collision(written: str, source: str) -> str:
    return f"`{written}:` already exists beside `{source}:` - merge them by hand, then run again"


def _expected(old: dict, unknown_groups_into: str | None = None) -> dict:
    """What the new form must contain, built from the old form's DATA - the oracle the splice is
    checked against. It knows nothing about lines, which is why it can check them.

    It REFUSES (ValueError) to set a key the old form already has, rather than overwrite it: an oracle
    that overwrites agrees with a splice that writes a second copy, because YAML keeps the last of two
    equal keys - the first one's content is gone either way, and the check passes."""
    out = {k: v for k, v in old.items() if k not in ("groups", "env_groups", "default", "environments")}

    def put(key: str, value: object, source: str) -> None:
        if key in out:
            raise ValueError(_collision(key, source))
        out[key] = value

    groups = old.get("groups") or {}
    ci = {n: groups[n] for n in CI if n in groups}
    cd = {k: old[k] for k in ENV_KEYS if k in old}
    cd.update({n: groups[n] for n in CD if n in groups})
    if unknown_groups_into is not None:
        area = ci if unknown_groups_into == "ci" else cd
        area.update({n: v for n, v in groups.items() if n not in CI + CD + ("support",)})
    if ci:
        put("ci", ci, "groups")
    if cd:
        put("cd", cd, "groups" if any(n in groups for n in CD) else next(k for k in ENV_KEYS if k in old))
    if "support" in groups:
        put("support", groups["support"], "groups")
    if _is_docs_site(old.get("site")):
        put("website", out.pop("site"), "site")
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


def _area(key: str, head: list[str], children: list[list[str]]) -> tuple[list[str], list[str]]:
    """`key:` followed by its children, and apart from it the blank lines the first child had above it.

    Those blank lines separated a moved block from whatever stood above it in its old place; above it
    now is `key:`, so they cannot stay under it. Where the area goes decides what becomes of them: `cd:`
    standing where `environments:` stood keeps the ones that stood above that key, and an area following
    another area gets exactly one (si#406)."""
    body = [line for child in children for line in child]
    above: list[str] = []
    while body and not body[0].strip():
        above.append(body.pop(0))
    return above, head + [f"{key}:"] + body


def _column_0_comments(child: list[str], first: int) -> list[tuple[int, int]]:
    """The runs of column-0 comment lines in a moved group, as (first, last) line numbers of the original.

    `_blocks` reads such a comment as the next key's, by position, because nothing else can be read from
    it: firn's `# --- the development environment ---` above `  deploy:` announced deploy, and the two
    banners above it announced `images:` and `suites:` (si#406). The move keeps the guess; this names it."""
    runs: list[tuple[int, int]] = []
    for number, line in enumerate(child, first):
        if line.startswith("#"):
            if runs and runs[-1][1] == number - 1:
                runs[-1] = (runs[-1][0], number)
            else:
                runs.append((number, number))
    return runs


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


def _parse(text: str) -> tuple[object, str]:
    """(the document, ''), or (None, the refusal) when it is not valid YAML - reprinted from the parser's mark,
    because it was handed a STRING and its `str()` would name "<unicode string>". A refusal and not a
    traceback: this command is the way out of a manifest the kernel no longer loads, so it is run on files
    somebody is in the middle of editing."""
    try:
        return yaml.load(text, Loader=UniqueKeyLoader), ""
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"line {mark.line + 1}, column {mark.column + 1}: " if mark is not None else ""
        problem = getattr(exc, "problem", None) or str(exc)
        return None, f"it is not valid YAML, so nothing can be moved: {where}{problem}"


def _duplicates(text: str) -> list[tuple[str, int, int, int]]:
    """Every scalar key one mapping writes twice, as (dotted path, the key's column, the first copy's key
    line, the second's), 0-based lines, in document order - `yamlkeys.duplicates`, the loader's own check,
    so the migration and the loader cannot disagree on what a duplicate is (review finding I1)."""
    return [(found.path, found.second.start_mark.column, found.first.start_mark.line,
             found.second.start_mark.line)
            for found in duplicates(yaml.compose(text, Loader=yaml.SafeLoader))]


def _span(lines: list[str], at: int, indent: int) -> tuple[int, int]:
    """The half-open line range of the block whose key line is `at`: the comment and blank lines directly
    above it (`_blocks`' rule - a comment at the key's indent or less), the key line, and every line under
    it up to the next content line indented no deeper than the key - except a `- ` item at the key's own
    column, which YAML reads as the key's value (PyYAML's own dump style). Trailing comments and blank lines
    belong to whatever comes next, as they do in `_blocks`. Read by indentation: a block value's end mark
    sits on the NEXT key's line (measured on cleon), so it cannot say where this one ends."""
    def is_comment_or_blank(line: str) -> bool:
        return not line.strip() or line.lstrip().startswith("#")

    def is_own_item(line: str) -> bool:
        return len(line) - len(line.lstrip()) == indent and (line.lstrip() == "-" or line.lstrip().startswith("- "))

    end = at + 1
    while end < len(lines) and (is_comment_or_blank(lines[end]) or is_own_item(lines[end])
                                or len(lines[end]) - len(lines[end].lstrip()) > indent):
        end += 1
    while end > at + 1 and is_comment_or_blank(lines[end - 1]):
        end -= 1
    top = at
    while top > 0 and (not lines[top - 1].strip()
                       or (lines[top - 1].lstrip().startswith("#")
                           and len(lines[top - 1]) - len(lines[top - 1].lstrip()) <= indent)):
        top -= 1
    return top, end


def _as_written(block: list[str], indent: int) -> list[str]:
    """A copy's non-blank lines with the key's column taken off - so two copies at the same place compare
    with their structure (review minor 2: `c:` beside `b:` and `c:` under it are different copies), and a
    comment above the key, which may stand left of it, compares by its text."""
    return [line[min(indent, len(line) - len(line.lstrip())):].rstrip() for line in block if line.strip()]


def _dedupe(text: str) -> Migration:
    """Pass 0 (si#344 B2): a key written twice in one mapping. YAML keeps the second copy and loses the
    first, so the loader refuses it; here an IDENTICAL second copy - the same lines, comments included - is
    dropped, and copies that differ are refused, because only a person can say which one was meant."""
    def refused(why: str) -> Migration:
        return Migration("refused", text, (), why)

    try:
        _duplicates(text)
    except yaml.YAMLError:
        return refused(_parse(text)[1])
    lines = text.splitlines()
    removed: list[str] = []
    moved: list[str] = []
    while True:
        found = _duplicates("\n".join(lines) + "\n")
        if not found:
            break
        path, indent, first, second = found[-1]  # the last first: dropping it moves no line above it
        if first == second or lines[first][:indent].strip() or lines[second][:indent].strip():
            return refused(f"{path} is written twice where the splice cannot cut a copy out - inside a flow "
                           f"mapping or a sequence item (line {second + 1}) - merge the two by hand, and run again")
        a0, a1 = _span(lines, first, indent)
        b0, b1 = _span(lines, second, indent)
        if _as_written(lines[a0:a1], indent) != _as_written(lines[b0:b1], indent):
            return refused(f"{path} is written twice, on lines {first + 1} and {second + 1}, and the two copies "
                           "differ - YAML keeps only the second, so merge them into one by hand, and run again")
        removed += lines[b0:b1]
        del lines[b0:b1]
        moved.insert(0, f"{path}: written twice, identically (lines {first + 1} and {second + 1}) - the "
                        "second copy dropped")
    if not moved:
        return Migration("current", text)
    new = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    parsed, reason = _parse(new)
    if reason:
        return refused(f"the text without its second copies does not parse back: {reason}")
    if parsed != yaml.safe_load(text):
        return refused("the text without its second copies does not parse back to the same manifest")
    lost, extra = _accounting(text.splitlines(), new.splitlines(), removed, [])
    if lost or extra:
        return refused(f"dropping a second copy changed a line it should not have: {lost or extra}")
    return Migration("migrated", new, tuple(moved))


def _kinds_read(old: dict) -> dict[str, dict[str, str]]:
    """entry name -> {coordinate: the kind it reads}, for every command whose `task:` is a coordinate that
    reads ONE `artifacts:` entry (`READERS`, generated from the model) and whose `with:` names that entry."""
    found: dict[str, dict[str, str]] = {}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            task, bound = node.get("task"), node.get("with")
            if isinstance(task, str) and task in READERS and isinstance(bound, dict) \
                    and isinstance(bound.get("name"), str):
                found.setdefault(bound["name"], {})[task] = READERS[task]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for area in ("ci", "cd", "support"):
        walk(old.get(area))
    return found


def _derived_kind(name: str, read: dict[str, dict[str, str]]) -> tuple[str, str]:
    """(the kind, '') for a kindless entry exactly one kind of reader reads, else ('', the refusal)."""
    readers = read.get(name, {})
    kinds = sorted(set(readers.values()))
    if len(kinds) == 1:
        return kinds[0], ""
    if not kinds:
        return "", (f"artifacts: {name} declares no `kind:`, and no command reads it through a catalogue "
                    f"task that names its kind ({', '.join(sorted(READERS))}) - add `kind:` to it by hand, "
                    f"one of {', '.join(REFINES)}, and run again")
    said = ", ".join(f"{coordinate} reads a {kind}" for coordinate, kind in sorted(readers.items()))
    return "", (f"artifacts: {name} declares no `kind:`, and the commands that read it disagree ({said}) - "
                "add `kind:` by hand, and run again")


#: A key line's rest, split into its value and a trailing comment (`  iol: x:1   # why`).
_VALUE = re.compile(r"^(?P<value>.*?)(?P<comment>\s+#.*)?$")


def _rewrite_entry(child: list[str], kind: str | None,
                   scalar: str | None) -> tuple[list[str], list[str], list[str]] | str:
    """One `  <name>:` block of `images:` or `artifacts:`, rewritten in place: `kind: <kind>` written as its
    first key when `kind` is given, a `source:` key renamed `path:`, and a bare image reference (`scalar`)
    written as `{ kind: image, local: "<reference>" }` with its comment kept on the line. Returns
    (the lines, the lines it removed, the lines it added), or the reason it cannot."""
    at = next(i for i, line in enumerate(child) if _CHILD.match(line))
    head = _CHILD.match(child[at])
    assert head is not None  # `at` is the first line `_CHILD` matches
    key, parts = head.group("key"), _VALUE.match(head.group("rest"))
    assert parts is not None  # a lazy value and an optional comment match every string
    value, comment = parts.group("value").strip(), parts.group("comment") or ""
    lines = list(child)
    if scalar is not None:
        lines[at] = f"  {key}: {{ kind: image, local: {json.dumps(scalar)} }}{comment}"
        return lines, [child[at]], [lines[at]]
    if value.startswith("{"):
        if not value.endswith("}"):
            return f"{key} is a flow mapping written across lines - write it on one line or in block style"
        inner = value[1:-1].strip()
        if kind:
            inner = f"kind: {kind}, {inner}" if inner else f"kind: {kind}"
        inner = re.sub(r"(^|,\s*)source(\s*:)", r"\1path\2", inner)
        lines[at] = f"  {key}: {{ {inner} }}{comment}"
        return lines, [child[at]], [lines[at]]
    if value:
        return (f"{key} holds {value!r}, which is neither a mapping nor an image reference - write a mapping "
                f"with its `kind:` (`{key}: {{ kind: image, local: \"<reference>\" }}`), or the image reference "
                f"as a quoted string (`{key}: \"<reference>\"`)")
    body = [i for i in range(at + 1, len(child))
            if child[i].strip() and not child[i].lstrip().startswith("#")]
    if not body:
        return f"{key} holds nothing - an entry needs at least its `kind:`"
    indent = len(child[body[0]]) - len(child[body[0]].lstrip())
    removed: list[str] = []
    added: list[str] = []
    for i in body:
        if child[i].startswith(" " * indent + "source:"):
            lines[i] = " " * indent + "path:" + child[i][indent + len("source:"):]
            removed.append(child[i])
            added.append(lines[i])
    if kind:
        written = " " * indent + f"kind: {kind}"
        lines.insert(at + 1, written)
        added.append(written)
    return lines, removed, added


def _deploy_source(block: list[str]) -> tuple[list[str], list[str], list[str]] | str:
    """The `deploy:` block with `source:`'s `images` renamed `artifacts`, flow (`source: { images: x }`) or
    block (`source:` / `    images: x`)."""
    lines = list(block)
    for i, line in enumerate(block):
        match = _CHILD.match(line)
        if not match or match.group("key") != "source":
            continue
        if "{" in match.group("rest"):
            lines[i] = re.sub(r"([{,]\s*)images(\s*:)", r"\1artifacts\2", line, count=1)
            return lines, [line], [lines[i]]
        for j in range(i + 1, len(block)):
            inner = block[j]
            if inner.strip() and not inner.lstrip().startswith("#") and len(inner) - len(inner.lstrip()) <= 2:
                break
            if re.match(r"^\s{4,}images\s*:", inner):
                lines[j] = inner.replace("images", "artifacts", 1)
                return lines, [inner], [lines[j]]
    return ("deploy: source: names `images:` in a shape the fold does not rewrite - write "
            "`source: { artifacts: <name> }` by hand, and run again")


def _fold_expected(old: dict, kinds: dict[str, str]) -> dict:
    """What the folded text must parse to, built from the DATA - `_expected`'s role for the second pass."""
    out = {k: v for k, v in old.items() if k != "images"}
    folded: dict = {}
    for name, body in (old.get("artifacts") or {}).items():
        if isinstance(body, dict):
            body = dict(body)
            if "source" in body:
                body["path"] = body.pop("source")
            if name in kinds:
                body["kind"] = kinds[name]
        folded[name] = body
    for name, body in (old.get("images") or {}).items():
        folded[name] = ({"kind": "image", "local": body} if isinstance(body, str)
                        else {"kind": "image", **(body or {})})
    if "images" in old or "artifacts" in old:
        out["artifacts"] = folded or old.get("artifacts", old.get("images"))
    deploy = old.get("deploy")
    if isinstance(deploy, dict) and isinstance(deploy.get("source"), dict) and "images" in deploy["source"]:
        source = dict(deploy["source"])
        source["artifacts"] = source.pop("images")
        out["deploy"] = {**deploy, "source": source}
    return out


def _fold(text: str) -> Migration:
    """Pass 2 (si#344 B2): `images:` into `artifacts:` with `kind: image`, a `kind:` on every artifacts
    entry (derived from the coordinate that reads it), `source:` into `path:`, and `deploy: source:
    { images: x }` into `{ artifacts: x }`. `images:` beside an existing `artifacts:` is appended to it; the
    comments above `images:` stay where they stood."""
    old, reason = _parse(text)
    if reason:
        return Migration("refused", text, (), reason)
    if not isinstance(old, dict):
        return Migration("current", text)
    images, artifacts, deploy = old.get("images"), old.get("artifacts"), old.get("deploy")
    source = deploy.get("source") if isinstance(deploy, dict) else None
    entries = artifacts if isinstance(artifacts, dict) else {}
    kindless = [str(n) for n, body in entries.items() if isinstance(body, dict) and "kind" not in body]
    renamed = [str(n) for n, body in entries.items() if isinstance(body, dict) and "source" in body]
    shapeless = [str(n) for n, body in entries.items() if not isinstance(body, dict)]
    deploy_images = isinstance(source, dict) and "images" in source
    unreadable = artifacts is not None and not isinstance(artifacts, dict)
    # "current" only for a manifest this pass would leave as the loader wants it: an `artifacts:` that is
    # not a mapping, or an entry that is not one, is NOT current - it is cannot-migrate, named below.
    if ("images" not in old and not kindless and not renamed and not shapeless and not deploy_images
            and not unreadable):
        return Migration("current", text)

    def refused(why: str) -> Migration:
        return Migration("refused", text, (), why)

    if images is not None and not isinstance(images, dict):
        return refused(f"images: is a {type(images).__name__}, not a mapping of image name to entry - fix it "
                       "by hand, and run again")
    if unreadable:
        return refused(f"artifacts: is a {type(artifacts).__name__}, not a mapping of artifact name to entry "
                       "- fix it by hand, and run again")
    for name in shapeless:
        value = entries[name]
        if value is None:
            return refused(f"artifacts: {name} holds nothing - an entry names its `kind:` and its keys; write "
                           "them by hand, and run again")
        return refused(f"artifacts: {name} is {value!r}, not a mapping - an entry names its `kind:` and its "
                       f"keys; an image reference is written `{name}: {{ kind: image, local: \"{value}\" }}` - "
                       "fix it by hand, and run again")
    images = images or {}
    both = sorted(str(name) for name in set(images) & set(entries))
    if both:
        return refused(f"'{both[0]}' is both an `images:` and an `artifacts:` entry, and one section cannot "
                       "hold the name twice - rename one by hand, and run again")
    for name in renamed:
        if "path" in entries[name]:
            return refused(f"artifacts: {name} declares both `source:` and `path:`; `source:` is the old name "
                           "of `path:`, so one of the two is stale - delete it by hand, and run again")
    for name, body in images.items():
        if isinstance(body, dict) and body.get("kind", "image") != "image":
            return refused(f"images: {name} declares `kind: {body['kind']}`; an `images:` entry is an image - "
                           "delete the key, or move the entry to `artifacts:` by hand, and run again")
    read = _kinds_read(old)
    kinds: dict[str, str] = {}
    for name in kindless:
        derived, why = _derived_kind(name, read)
        if why:
            return refused(why)
        kinds[name] = derived

    lines = text.splitlines()
    removed: list[str] = []
    added: list[str] = []
    moved: list[str] = []
    out: list[list[str]] = []
    folded: list[str] = []  # image entries bound for an `artifacts:` block that stands elsewhere
    artifacts_at = -1       # where in `out` the `artifacts:` block stands
    for key, block in _blocks(lines, _TOP, 0):
        if key not in ("images", "artifacts", "deploy"):
            out.append(block)
            continue
        if key == "deploy":
            if deploy_images:
                rewritten = _deploy_source(block)
                if isinstance(rewritten, str):
                    return refused(rewritten)
                block, gone, came = rewritten
                removed += gone
                added += came
                moved.append("deploy: source: images -> artifacts")
            out.append(block)
            continue
        at = next(i for i, line in enumerate(block) if _TOP.match(line))
        head = _TOP.match(block[at])
        assert head is not None  # `at` is the first line `_TOP` matches
        rest = head.group("rest")
        section = images if key == "images" else entries
        written_as = _VALUE.match(rest)
        assert written_as is not None
        written = written_as.group("value").strip()
        if written and section:
            return refused(f"{key}: is written in flow style on its key line; the fold rewrites block-style "
                           "sections only - rewrite it in block style, and run again")
        # preflight P8: an empty `artifacts:` beside `images:` - the images go under it, so it must be a bare
        # key line; `artifacts: {}` or `artifacts: null` cannot take them, and writing a second `artifacts:`
        # key instead would parse back to the right data (YAML keeps the last of two) and be wrong
        if written and key == "artifacts" and images:
            return refused(f"artifacts: is written `{written}` on its key line beside `images:`, and the fold "
                           "appends the images under a block-style `artifacts:` - write it as a bare "
                           "`artifacts:` or delete it, and run again")
        children = _blocks(block[at + 1:], _CHILD, 2)
        body = list(children[0][1])
        for found, child in children[1:]:
            name = str(found)  # a child block always has its key; only the preamble (index 0) is None
            value = section.get(name)
            if key == "images":
                kind = None if isinstance(value, dict) and "kind" in value else "image"
                scalar = value if isinstance(value, str) else None
            else:
                kind, scalar = kinds.get(str(name)), None
                if not kind and not (isinstance(value, dict) and "source" in value):
                    body += child
                    continue
            rewritten = _rewrite_entry(child, kind, scalar)
            if isinstance(rewritten, str):
                return refused(f"{key}: {rewritten}, and run again")
            entry, gone, came = rewritten
            body += entry
            removed += gone
            added += came
            if key == "images":
                moved.append(f"images: {name} -> artifacts: {name} (kind: image)")
                continue
            if kind:
                moved.append(f"artifacts: {name} gains kind: {kind} (read by {', '.join(sorted(read[str(name)]))})")
            if isinstance(value, dict) and "source" in value:
                moved.append(f"artifacts: {name}: source -> path")
        if key == "artifacts":
            artifacts_at = len(out)
            out.append(block[:at + 1] + body)
        elif "artifacts" in old:
            folded = body
            removed.append(block[at])
            out.append(block[:at])
            if not images:  # Task 3 review T3a: an empty section moves no entry, so it says its own move
                moved.append("images: deleted - it holds no entry, and artifacts: already stands")
        else:
            if not images:
                moved.append("images: -> artifacts: (it holds no entry)")
            renamed_line = "artifacts:" + rest
            removed.append(block[at])
            added.append(renamed_line)
            out.append(block[:at] + [renamed_line] + body)
    if folded:
        out[artifacts_at] = out[artifacts_at] + folded
    new = "\n".join(line for chunk in out for line in chunk) + ("\n" if text.endswith("\n") else "")

    parsed, reason = _parse(new)
    if reason:
        return refused(f"the folded text does not parse back: {reason}")
    expected = _fold_expected(old, kinds)
    if parsed != expected:
        return refused("the folded text does not parse back to the same manifest: "
                       f"{_first_difference(expected, parsed)}")
    lost, extra = _accounting(lines, new.splitlines(), removed, added)
    if lost:
        return refused(f"the folded text loses a line the original had: {lost}")
    if extra:
        return refused(f"the folded text has a line the original did not: {extra}")
    return Migration("migrated", new, tuple(moved))


#: Each catalogue coordinate whose port binds `name` -> (that port, the command key that binds it).
_BINDS_NAME = {coordinate: (p.name, "produces" if p.direction == "output" else "consumes")
               for coordinate, ports in PORTS.items() for p in ports if p.param == "name"}
_TASK_LINE = re.compile(r"""^(?P<indent> *)task:\s*(?P<q>["']?)(?P<coordinate>[^"'\s#]+)(?P=q)\s*(?:#.*)?$""")
_WITH_FLOW = re.compile(r"^(?P<indent> *)with:\s*\{(?P<body>[^{}&*<]*)\}(?P<comment>\s+#.*)?$")
_WITH_BLOCK = re.compile(r"^(?P<indent> *)with:(?P<comment>\s+#.*)?$")
_NAME_LINE = re.compile(r"^(?P<indent> *)name:\s*(?P<value>[^\s#&*|>][^#]*?)(?P<comment>\s+#.*)?$")


def _bound(node: object) -> object:
    """The document as the loader reads it since si#344 C.2: on a coordinate in `_BINDS_NAME`, a string
    `with: name` IS that port's binding. The oracle `_bind`'s splice is held to."""
    if isinstance(node, list):
        return [_bound(value) for value in node]
    if not isinstance(node, dict):
        return node
    out = {key: _bound(value) for key, value in node.items()}
    task, pinned = out.get("task"), out.get("with")
    if isinstance(task, str) and task in _BINDS_NAME and isinstance(pinned, dict) \
            and isinstance(pinned.get("name"), str):
        port, key = _BINDS_NAME[task]
        written = out.get(key)
        out[key] = {port: pinned["name"], **(written if isinstance(written, dict) else {})}
        rest = {k: v for k, v in pinned.items() if k != "name"}
        if rest:
            out["with"] = rest
        else:
            out.pop("with")
    return out


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _siblings(lines: list[str], at: int, width: int) -> tuple[int, int]:
    """[first, last) of the mapping the key on line `at`, `width` spaces in, stands in."""
    def inside(line: str) -> bool:
        return not line.strip() or line.lstrip().startswith("#") or _indent(line) >= width
    first, last = at, at + 1
    while first > 0 and inside(lines[first - 1]):
        first -= 1
    while last < len(lines) and inside(lines[last]):
        last += 1
    return first, last


def _with_flow(match: re.Match, port: str, key: str) -> list[str] | None:
    indent, body, comment = match["indent"], match["body"], match["comment"] or ""
    items = [item.strip() for item in body.split(",") if item.strip()]
    named = [item for item in items if re.match(r"name\s*:", item)]
    if len(named) != 1:
        return None
    rest = [item for item in items if item not in named]
    value = named[0].split(":", 1)[1].strip()
    if not isinstance(yaml.safe_load(value or "~"), str):
        return None   # the loader reads only a string as the binding: nothing to rewrite
    # the split is trusted only if it parses back to what the line said (a comma inside a value would not)
    if yaml.safe_load("{" + ", ".join(rest) + "}") != {k: v for k, v in yaml.safe_load("{" + body + "}").items()
                                                       if k != "name"}:
        return None
    if not rest:
        return [f"{indent}{key}: {{ {port}: {value} }}{comment}"]
    return [f"{indent}{key}: {{ {port}: {value} }}", f"{indent}with: {{ {', '.join(rest)} }}{comment}"]


def _with_block(lines: list[str], at: int, match: re.Match, port: str, key: str) -> tuple[int, list[str]] | None:
    """The `with:` block on line `at`, rewritten: (the line after it, its new lines), or None."""
    width = len(match["indent"])
    end = at + 1
    while end < len(lines) and (not lines[end].strip() or _indent(lines[end]) > width):
        end += 1
    body = lines[at + 1:end]
    keys = [line for line in body if line.strip() and not line.lstrip().startswith("#")]
    if not keys:
        return None
    child = _indent(keys[0])
    names = [n for n, line in enumerate(body) if _indent(line) == child and _NAME_LINE.match(line)]
    own = [line for line in keys if _indent(line) == child]
    if len(names) != 1 or any(line.lstrip().startswith("<<") for line in own):
        return None
    found = _NAME_LINE.match(body[names[0]])
    assert found is not None
    if not isinstance(yaml.safe_load(found["value"]), str):
        return None   # the loader reads only a string as the binding: nothing to rewrite
    binding = f"{' ' * child}{port}: {found['value']}{found['comment'] or ''}"
    if len(own) == 1:
        return end, [f"{match['indent']}{key}:{match['comment'] or ''}",
                     *(binding if n == names[0] else line for n, line in enumerate(body))]
    return end, [f"{match['indent']}{key}:", binding, lines[at],
                 *(line for n, line in enumerate(body) if n != names[0])]


def _bind(text: str) -> Migration:
    """Pass 3 (si#344 C.2): `with: { name: X }` on a coordinate whose port binds `name` becomes that port's
    binding - `produces: { image: X }` on `build:image`, `consumes: { image: X }` on `release:image`. Only a
    `task:` on its own line whose sibling `with:` carries no anchor, alias or merge key is rewritten; the
    rest stays as written, which the loader reads as the same binding (decided 2026-10-14), so leaving it
    is never wrong - only older."""
    old, reason = _parse(text)
    if reason:
        return Migration("refused", text, (), reason)
    if not isinstance(old, dict):
        return Migration("current", text)
    lines = text.splitlines()
    edits: list[tuple[int, int, list[str], str]] = []
    for number, line in enumerate(lines):
        task = _TASK_LINE.match(line)
        if not task or task["coordinate"] not in _BINDS_NAME:
            continue
        port, key = _BINDS_NAME[task["coordinate"]]
        width = len(task["indent"])
        first, last = _siblings(lines, number, width)
        for at in range(first, last):
            if _indent(lines[at]) != width:
                continue
            flow, block = _WITH_FLOW.match(lines[at]), _WITH_BLOCK.match(lines[at])
            new = _with_flow(flow, port, key) if flow else None
            end = at + 1
            if block:
                rewritten = _with_block(lines, at, block, port, key)
                if rewritten:
                    end, new = rewritten
            if new:
                edits.append((at, end, new, f"line {at + 1}: {task['coordinate']} binds its `{port}` port with "
                                            f"`{key}:` instead of `with: name`"))
    if not edits:
        return Migration("current", text)
    out = list(lines)
    removed: list[str] = []
    added: list[str] = []
    for start, end, new, _ in sorted(edits, reverse=True):
        removed += out[start:end]
        added += new
        out[start:end] = new
    new_text = "\n".join(out) + ("\n" if text.endswith("\n") else "")
    parsed, reason = _parse(new_text)
    if reason:
        return Migration("refused", text, (), f"the bound text does not parse back: {reason}")
    if _bound(parsed) != _bound(old):
        return Migration("refused", text, (), "the bound text does not read back as the same bindings: "
                         + _first_difference(_bound(old), _bound(parsed)))
    lost, extra = _accounting(lines, out, removed, added)
    if lost or extra:
        return Migration("refused", text, (), f"binding changed a line it should not have: {lost or extra}")
    return Migration("migrated", new_text, tuple(move for *_, move in sorted(edits)))


def _shape(text: str, *, unknown_groups_into: str | None = None) -> Migration:
    """Pass 1 (si#344 A): splice `text` from the `groups:` form into the ci/cd form; see the module head."""
    old, reason = _parse(text)
    if reason:
        return Migration("refused", text, (), reason)
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
    checks: list[str] = []

    # Rule 2 (and 1): the groups block, split into its children and sorted into areas.
    ci: list[list[str]] = []
    cd: list[list[str]] = []
    support: list[str] = []  # a list of lines, not one block
    groups_head: list[str] = []
    groups_preamble: list[str] = []
    groups_comment = ""  # a trailing comment on the `groups:` key line, carried onto the first area
    removed: list[str] = []  # lines the splice deletes on purpose - the line accounting's allowance
    added: list[str] = []    # lines the splice writes that the original did not have
    if "groups" in keys:
        index = keys.index("groups")
        block = blocks[index][1]
        at = next(i for i, line in enumerate(block) if _TOP.match(line))
        number = sum(len(prior) for _, prior in blocks[:index]) + at + 1  # 1-based, of the key line
        key_line = _TOP.match(block[at])
        assert key_line is not None  # `at` is the first line `_TOP` matches
        rest = key_line.group("rest")
        # A `groups:` with no section moves nothing, and "migrated (0 section(s) moved)" would be the
        # green of a run that did nothing. Its key line is deleted, so a comment on it would go too - and
        # not only one standing alone: `groups: null  # c` and `groups: ~ # c` carry one after the value.
        # A YAML comment starts at a `#` that opens the rest or follows whitespace; an empty value holds
        # no string a `#` could hide in, so that is the whole test.
        if not old.get("groups"):
            hash_at = re.search(r"(?:^|\s)(#.*)$", rest)
            comment = hash_at.group(1).strip() if hash_at else ""
            if comment:
                return refused(f"groups: on line {number} holds no section to move, so its comment "
                               f"({comment!r}) has no area to travel onto - move the comment or delete it, "
                               "and run again")
            if not (any(k in old for k in ("env_groups",) + ENV_KEYS) or docs_site):
                return refused(f"groups: on line {number} holds no section, so there is nothing to move "
                               "into ci: / cd: / support: - delete the key by hand, and run again")
        if rest.lstrip().startswith(("{", "[")):
            return refused(f"groups: is written in flow style on line {number}; the splice moves "
                           "block-style sections only - rewrite it in block style and run again")
        groups_head = block[:at]
        groups_comment = rest
        removed.append(block[at])
        # The splice reads a section at exactly two spaces. A manifest indented by more is valid YAML
        # that `_CHILD` sees no section in, and the refusal it then earned ("does not parse back: ci")
        # named a symptom; this names the cause.
        body = next(((n, line) for n, line in enumerate(block[at + 1:], number + 1)
                     if line.strip() and not line.lstrip().startswith("#")), None)
        if body is not None and body[1].startswith(" "):
            indent = len(body[1]) - len(body[1].lstrip())
            if indent != 2:
                return refused(f"groups: indents its sections by {indent} spaces (line {body[0]}); the "
                               "splice moves a manifest indented by two spaces per level, the way `simplon "
                               "init` writes one - reindent it, and run again")
        children = _blocks(block[at + 1:], _CHILD, 2)
        groups_preamble = children[0][1]
        first = number + 1 + len(groups_preamble)  # line number of each child block's first line
        for name, child in children[1:]:
            first, starts = first + len(child), first
            if name in CI or (name not in CD + ("support",) and unknown_groups_into == "ci"):
                ci.append(child)
                moved.append(f"groups: {name} -> ci: {name}")
                area = "ci"
            elif name in CD or (name != "support" and unknown_groups_into == "cd"):
                cd.append(child)
                moved.append(f"groups: {name} -> cd: {name}")
                area = "cd"
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
            for low, high in _column_0_comments(child, starts):
                lines_said = f"line {low}" if low == high else f"lines {low}-{high}"
                checks.append(f"{lines_said}: a column-0 comment moved with groups: {name} into {area}: - a "
                              "comment at column 0 does not say which key it belongs to, so check it "
                              "belongs there")

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
        # An entry naming a group the manifest does not declare was REFUSED by the loader the key
        # belonged to. Deleting it here would turn a manifest that did not load into one that does,
        # silently - the migration would have fixed a mistake nobody was told about.
        declared = old["groups"] if isinstance(old.get("groups"), dict) else {}
        missing = [group for group in value if group not in declared]
        if missing:
            return refused(f"env_groups: {_render(value)} names '{missing[0]}', which groups: does not "
                           "declare - the manifest did not load before the migration either, so deleting "
                           "the entry would hide a mistake rather than move it. Declare the group or drop "
                           "the entry, and run again")
        owned = [line for line in blocks[keys.index("env_groups")][1] if line.strip()]
        removed += owned
        comments = sum(1 for line in owned if line.strip().startswith("#"))
        said = f" with the {comments} comment line{'s' if comments != 1 else ''} it owns" if comments else ""
        moved.append(f"env_groups: deleted ({_render(value)}){said}")

    # A key the splice writes may not already stand at the top level: YAML keeps the last of two equal
    # keys, so writing a second one "migrates" and loses the first one's content on load.
    writes = [("ci", "groups", bool(ci)), ("support", "groups", bool(support)),
              ("cd", "groups" if cd else next((k for k in keys if k in ENV_KEYS), ""), bool(cd or env_lines)),
              ("website", "site", docs_site)]
    for written, source, happens in writes:
        if happens and written in keys:
            return refused(_collision(written, source))

    # Assemble: the new areas replace groups: in place; cd: stands at the first env key if there is
    # no groups: to stand in for, or groups: had no deploy/monitor to give it.
    cd_above, cd_block = _area("cd", [], env_lines + cd) if (env_lines or cd) else ([], [])
    cd_with_groups = "groups" in keys and bool(cd)
    out: list[str] = []
    cd_placed = False
    for key, block in blocks:
        if key == "groups":
            # Each area after the first stands below a blank line, as two top-level sections do; the
            # first stands where groups: stood, below whatever stood above that (si#406).
            written: list[list[str]] = []
            if ci:
                written.append(_area("ci", [], ci)[1])
            if cd_block and cd_with_groups:
                written.append(cd_block)
                cd_placed = True
            if support:
                support_body = list(support)
                while support_body and not support_body[0].strip():
                    support_body.pop(0)
                written.append(support_body)
            areas: list[str] = []
            for area_lines in written:
                if areas:
                    areas.append("")
                areas += area_lines
            if areas:
                head_end = areas.index(next(line for line in areas if _TOP.match(line))) + 1
                areas[head_end - 1] += groups_comment
                areas[head_end:head_end] = [line for line in groups_preamble if line.strip()]
            added += [line for line in areas if _TOP.match(line) and line.split(":")[0] in ("ci", "cd")]
            out += groups_head + areas
        elif key in ENV_KEYS:
            if cd_block and not cd_with_groups and not cd_placed:
                out += cd_above + cd_block
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
        parsed = yaml.load(new, Loader=UniqueKeyLoader)
    except yaml.YAMLError as error:
        return refused(f"the spliced text does not parse back to the same manifest: {error}")
    try:
        expected = _expected(old, unknown_groups_into)
    except ValueError as error:
        return refused(str(error))
    if parsed != expected:
        return refused("the spliced text does not parse back to the same manifest: "
                       f"{_first_difference(expected, parsed)}")
    lost, extra = _accounting(lines, new.splitlines(), removed, added)
    if lost:
        return refused(f"the spliced text loses a line the original had: {lost}")
    if extra:
        return refused(f"the spliced text has a line the original did not: {extra}")
    return Migration("migrated", new, tuple(moved), checks=tuple(checks))


def migrate_text(text: str, *, unknown_groups_into: str | None = None) -> Migration:
    """Rewrite `text` into the current form: `_dedupe`, then `_shape`, then `_fold` - see the module head.
    "current" only when no pass changed a byte; a refusal in any pass hands back the input untouched."""
    if unknown_groups_into not in (None, "ci", "cd"):
        raise ValueError(f"unknown_groups_into must be 'ci' or 'cd', not {unknown_groups_into!r}")
    document, invalid = _parse(text)
    if not invalid and not isinstance(document, dict):
        # si#388: "current" would tell the person there is nothing to do with a file the loader refuses.
        found = "nothing" if document is None else f"a {type(document).__name__}"
        return Migration("refused", text, (), f"it is not a manifest: the document holds {found}, not a "
                         "mapping of top-level keys (product, tasks, ci, cd, support, ...)")
    current, moved, checks = text, list[str](), list[str]()
    for step in (_dedupe, lambda t: _shape(t, unknown_groups_into=unknown_groups_into), _fold, _bind):
        result = step(current)
        if result.status == "refused":
            return Migration("refused", text, (), result.reason)
        if result.status == "migrated":
            current, moved, checks = result.text, [*moved, *result.moved], [*checks, *result.checks]
    if current == text:
        return Migration("current", text)
    return Migration("migrated", current, tuple(moved), checks=tuple(checks))


def migrate(manifest: str = "") -> int:
    """Rewrite THIS product's manifest (or the one named) into the current form: ci / cd / support, and
    every artifact with its kind.

    rc 0 when it migrated and when there was nothing to migrate - with a different sentence each, because
    those are two answers. rc 1 when it could not, with nothing written.
    """
    if manifest:
        path = Path(manifest)
    else:
        # Imported here, not at the top: `simplon.domain.context` imports the manifest LOADER, and the package
        # route (`simplon manifest migrate`) exists for a manifest that loader refuses.
        from simplon.domain import context
        path = context.current().manifest_path
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        log.error(f"{path.name}: not migrated, nothing written - cannot read it: {error}")
        return 1
    result = migrate_text(text)
    if result.status == "current":
        log.ok(f"{path.name}: already in the current form (ci / cd / support, every artifact with its kind) "
               "- nothing to migrate")
        return 0
    if result.status == "refused":
        log.error(f"{path.name}: not migrated, nothing written - {result.reason}")
        return 1
    try:
        path.write_text(result.text, encoding="utf-8")
    except OSError as error:
        # A read-only file or directory: said with rc 1, like every other way this run can fail to
        # migrate, not as a traceback. Nothing is claimed about the file beyond the reason the OS gave.
        log.error(f"{path.name}: not migrated - cannot write {path.name}: {error}")
        return 1
    for line in result.moved:
        log.info(line)
    for line in result.checks:
        log.warn(line)
    to_check = f", {len(result.checks)} to check above" if result.checks else ""
    log.ok(f"{path.name}: migrated to the current form ({len(result.moved)} change(s){to_check})")
    return 0
