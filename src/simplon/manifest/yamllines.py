"""The one line-based reading of a YAML block that the manifest's text splices share (si#670 item 11).

`toolchain scaffold` (si#110) and `manifest migrate` (si#344) both edit a manifest as text, so a comment
survives, and both have to say where a key's block begins and ends without a parser's help - a parsed
node's end mark sits on the NEXT key's line (measured on cleon), so it cannot say. Each kept its own
reader - migrate even a third, for a `with:` block - and they disagreed: si#662 was the toolchain reader
refusing a list migrate's read fine, and item 11 found the splice refusing a column-0 comment inside
`ci:` that migrate reads as the next key's, and the copies not measuring a line's indent alike. One
reader, so the next disagreement cannot happen.

Both splices parse their result back and do not write what fails to load to the expected data, so this
reader may be wrong about a shape it does not understand (a quoted scalar continued over several lines
at or left of its key's column) without corrupting a file.
"""
from __future__ import annotations


def indent(line: str) -> int:
    """The column a line's content starts at: its leading YAML white space, spaces AND tabs.

    Neither of the two measures this replaces. Python's `lstrip()` also strips what YAML reads as
    content - a key `\\u00a0z:` starts at column 0, and `lstrip()` put it under the key above, so two
    identical copies of that key were refused as different. Spaces alone (`lstrip(" ")`, YAML's
    indentation) put a tab-led line at column 0, and in a valid document the only line that starts with
    a tab is the continuation of a quoted scalar, which belongs to the key above it."""
    return len(line) - len(line.lstrip(" \t"))


def skippable(line: str) -> bool:
    """A blank or comment line - one that carries no data and so never decides where a block ends."""
    return not line.strip() or line.lstrip().startswith("#")


def leads(line: str, key_indent: int) -> bool:
    """Whether `line`, standing directly above a key at `key_indent`, belongs to that key's block.

    A blank line does, and a comment at the key's indent OR LESS: firn writes a column-0 banner inside
    `groups:` above `  deploy:`, and it announces deploy. A comment indented deeper than the key is the
    previous block's content (a commented-out command)."""
    return not line.strip() or (line.lstrip().startswith("#") and indent(line) <= key_indent)


def span(lines: list[str], at: int, key_indent: int) -> tuple[int, int]:
    """The half-open line range of the block whose key line is `at`: the lines directly above it that
    `leads` gives it, the key line, and every line under it up to the next content line indented no
    deeper than the key - except a `- ` item at the key's own column, which YAML reads as the key's value
    (PyYAML's own dump style, si#662). A comment at any column does not end it. Trailing comment and
    blank lines belong to whatever comes next, so `end` is one past the last line that carries data -
    the line a splice inserts before, so a comment introducing the next sibling keeps that sibling."""
    def is_own_item(line: str) -> bool:
        return indent(line) == key_indent and (line.lstrip() == "-" or line.lstrip().startswith("- "))

    end = at + 1
    while end < len(lines) and (skippable(lines[end]) or is_own_item(lines[end])
                                or indent(lines[end]) > key_indent):
        end += 1
    while end > at + 1 and skippable(lines[end - 1]):
        end -= 1
    top = at
    while top > 0 and leads(lines[top - 1], key_indent):
        top -= 1
    return top, end


def child_indent(lines: list[str], start: int, end: int) -> int | None:
    """The indent the first data line in [start, end) is written at - a block's own entries; None when
    there is none."""
    return next((indent(lines[i]) for i in range(start, end) if not skippable(lines[i])), None)
