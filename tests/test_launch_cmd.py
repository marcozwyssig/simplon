"""Line-ending policy for the rendered launchers (platform#78, si#57).

launch.sh and launch.cmd live in `src/simplon/templates/` as Jinja templates that `simplon init` renders
per product, so there is no single launcher file to assert against. Two things survive that: the crlf
policy `.gitattributes` holds for simplon's OWN `simplon.cmd`, and - since si#57 - the line endings
`simplon.bootstrap.write` gives a SCAFFOLDED product, which used to be whichever ones the scaffolding host
happened to have.

WHAT IS MEASURED HERE AND WHAT IS INHERITED, because the two are not the same strength of evidence and
this file is the one that would otherwise blur them.

  - MEASURED. That a scaffolded `.cmd` comes out CRLF and every other scaffolded file LF, on a host whose
    own `os.linesep` is LF - so the output provably no longer follows the host. And that a shim carrying
    the launcher's real shebang with CRLF endings does not launch at all here: the kernel takes `bash\r`
    as the interpreter name. That is the shell half of the policy, reproduced rather than asserted.
  - INHERITED. That cmd.exe mis-parses the multi-line `if (...)` blocks of an LF-only `.cmd`. That is this
    repository's standing claim - it is the stated reason for the `.gitattributes` line, and it is why the
    kernel's own launcher is CRLF on disk - and there is no Windows here to reproduce it on. si#57 says so
    too. What si#57 DID reproduce is the inconsistency: the kernel keeps the promise for itself through
    `.gitattributes` and hands a scaffolded product none, so on Linux it shipped Windows users the very
    file shape the policy exists to avoid.
"""
import os
import stat
import subprocess
from pathlib import Path

from simplon import bootstrap
from simplon.run import run


def _scaffold(tmp_path):
    """A freshly scaffolded product, returned as {relative path: bytes} - bytes, because the whole subject
    of this file is invisible to `read_text`, which normalises the endings away on the way in."""
    bootstrap.write("democtl", tmp_path)
    return {str(p.relative_to(tmp_path)): p.read_bytes()
            for p in sorted(tmp_path.rglob("*")) if p.is_file()}


def test_batch_line_endings_are_pinned_to_crlf():
    # Arrange
    attrs = Path(__file__).resolve().parents[1] / ".gitattributes"
    # Act / Assert
    assert attrs.is_file(), ".gitattributes is missing"
    assert "*.cmd text eol=crlf" in attrs.read_text()


def test_a_scaffolded_batch_launcher_is_crlf_even_though_this_host_writes_lf(tmp_path):
    # Arrange: the host these tests run on, which is what `write_text(newline=None)` would have followed
    files = _scaffold(tmp_path)
    cmd = files["democtl.cmd"]

    # Act / Assert: every line ends CRLF, and none of them is a lone LF that a partial fix would leave
    assert os.linesep == "\n", "this measurement only says something on an LF host"
    assert cmd.count(b"\r\n") == cmd.count(b"\n") > 0
    assert b"\r" not in cmd.replace(b"\r\n", b"")


def test_the_scaffolded_batch_launcher_is_built_from_the_multi_line_blocks_the_policy_is_about(tmp_path):
    # Arrange: the form the .gitattributes line names - `if ... (` opened on one line and closed on a
    # later one. If the template ever stopped using them, the inherited claim would need re-arguing
    # rather than being quietly carried on.
    files = _scaffold(tmp_path)
    text = files["democtl.cmd"].decode("utf-8")

    # Act
    blocks = [line for line in text.splitlines() if line.rstrip().endswith("(") and "if" in line]

    # Assert
    assert blocks, "the launcher no longer has multi-line blocks; the crlf claim needs re-stating"


def test_every_other_scaffolded_file_stays_lf_because_it_is_read_on_the_host_that_runs_it(tmp_path):
    # Arrange / Act
    files = _scaffold(tmp_path)

    # Assert: the shim, the manifest, the requirements and the generated python - a CRLF one of these is
    # the same defect pointing the other way, and it is the direction that breaks on THIS host
    lf_only = {rel: blob for rel, blob in files.items() if not rel.endswith(".cmd")}
    assert set(lf_only) >= {"democtl.sh", "democtl.yaml", "orchestrator/requirements.txt"}
    assert [rel for rel, blob in lf_only.items() if b"\r" in blob] == []


def test_a_shim_written_with_crlf_does_not_launch_at_all_on_this_host(tmp_path):
    # Arrange: the scaffolded shim's OWN shebang, not a stand-in for it, in both line endings
    files = _scaffold(tmp_path)
    shebang = files["democtl.sh"].decode("utf-8").splitlines()[0]
    written = {}
    for label, newline in (("crlf", "\r\n"), ("lf", "\n")):
        path = tmp_path / f"{label}.sh"
        path.write_text(f"{shebang}\nexit 0\n", encoding="utf-8", newline=newline)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        written[label] = run([str(path)])

    # Act / Assert: the reason the LF half of the policy is measured and not merely claimed - the CR ends
    # up inside the interpreter's NAME, so nothing runs and the message is about a file nobody named
    assert written["lf"].rc == 0
    assert written["crlf"].rc != 0
    assert "\\r" in written["crlf"].err or "\r" in written["crlf"].err


def test_the_line_ending_is_chosen_by_extension_rather_than_by_the_scaffolding_host():
    # Arrange / Act / Assert: the decision itself, so a new file type added to the skeleton has one place
    # to be answered in
    assert bootstrap.newline_for("democtl.cmd") == "\r\n"
    assert bootstrap.newline_for("democtl.sh") == "\n"
    assert bootstrap.newline_for("orchestrator/src/python/orchestrator/cli.py") == "\n"


def test_the_kernels_own_launcher_on_disk_matches_what_a_scaffold_would_now_write(tmp_path):
    # Arrange: si#57 came out of si#24's cross-check, which found this exact byte difference between the
    # kernel's committed launcher and the one its own scaffolder writes
    root = Path(__file__).resolve().parents[1]
    bootstrap.write("simplon", tmp_path, orch_dir="deploy/orchestrator")

    # Act / Assert: no difference left, and now at the byte level - `.gitattributes` keeps the kernel's
    # copy CRLF and the scaffolder finally writes the same thing for everybody else
    assert (tmp_path / "simplon.cmd").read_bytes() == (root / "simplon.cmd").read_bytes()
    assert (tmp_path / "simplon.sh").read_bytes() == (root / "simplon.sh").read_bytes()


def test_git_would_store_the_kernels_own_launcher_unchanged(tmp_path):
    # Arrange / Act: the committed bytes, asked of git rather than of the working tree, because a
    # checkout's `.gitattributes` could be what put the CRLF there rather than the scaffolder
    root = Path(__file__).resolve().parents[1]
    blob = subprocess.run(["git", "show", "HEAD:simplon.cmd"], cwd=root,
                          capture_output=True, check=True).stdout

    # Assert: eol=crlf is a CHECKOUT filter, so the blob itself is LF - which is exactly why a product
    # without a .gitattributes cannot get its CRLF from git and has to get it from the scaffolder
    assert b"\r\n" not in blob
    assert blob.replace(b"\n", b"\r\n") == (root / "simplon.cmd").read_bytes()
