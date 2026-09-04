"""Line-ending policy for the batch launcher (platform#78).

launch.sh and launch.cmd themselves move to src/sh/ only as scaffolded templates from Task 4
onward (bootstrap.py renders them per product); this repo carries no launcher of its own to test
directly any more. What does survive here is the crlf policy: cmd.exe mis-parses multi-line
blocks in an LF-only .cmd, and every file in this repo is authored on Linux, so .gitattributes
has to keep pinning *.cmd to crlf regardless of what generates the file.
"""
from pathlib import Path


def test_batch_line_endings_are_pinned_to_crlf():
    # Arrange
    attrs = Path(__file__).resolve().parents[1] / ".gitattributes"
    # Act / Assert
    assert attrs.is_file(), ".gitattributes is missing"
    assert "*.cmd text eol=crlf" in attrs.read_text()
