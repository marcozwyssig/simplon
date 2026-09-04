"""Line-ending policy for the batch launcher (platform#78).

launch.sh and launch.cmd live in `src/simplon/templates/` as Jinja templates that `simplon init`
renders per product, so there is no single launcher file to assert against. What survives is the
crlf policy, which covers both the rendered launchers and simplon's own `simplon.cmd`: cmd.exe
mis-parses multi-line blocks in an LF-only .cmd, and every file in this repo is authored on Linux,
so .gitattributes has to keep pinning *.cmd to crlf regardless of what generates the file.
"""
from pathlib import Path


def test_batch_line_endings_are_pinned_to_crlf():
    # Arrange
    attrs = Path(__file__).resolve().parents[1] / ".gitattributes"
    # Act / Assert
    assert attrs.is_file(), ".gitattributes is missing"
    assert "*.cmd text eol=crlf" in attrs.read_text()
