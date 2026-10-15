"""`simplon init --launchers-only`: re-render the two launchers and nothing else (si#407).

Asked by firn (firn#969): every kernel release may change the launchers, and `init --force` also rewrites
the manifest, `cli.py` and `requirements.txt`. Decided 2026-10-15 (si#407): the flag overwrites only
`<product>.sh` and `<product>.cmd`, reads the block dir off the existing `<product>.sh`, and says per file
whether it was `unchanged`, `replaced` or `written`.

AAA; the name states the behaviour under test.
"""
from simplon.cli import bootstrap


def _scaffold(tmp_path, *extra):
    target = tmp_path / "fooctl"
    assert bootstrap.main(["init", "fooctl", "--dir", str(target), *extra]) == 0
    return target


def test_only_the_launchers_are_rewritten_and_the_product_files_keep_their_edits(tmp_path, capsys):
    # arrange: the product has made the scaffold its own, and a launcher is stale
    target = _scaffold(tmp_path)
    (target / "fooctl.yaml").write_text("# mine\n", encoding="utf-8")
    requirements = target / bootstrap.DEFAULT_ORCH_DIR / "requirements.txt"
    requirements.write_text("mine==1\n", encoding="utf-8")
    (target / "fooctl.sh").write_text((target / "fooctl.sh").read_text() + "# stale\n", encoding="utf-8")
    capsys.readouterr()

    # act
    rc = bootstrap.main(["init", "fooctl", "--dir", str(target), "--launchers-only"])

    # assert
    assert rc == 0
    assert (target / "fooctl.yaml").read_text() == "# mine\n"
    assert requirements.read_text() == "mine==1\n"
    assert "# stale" not in (target / "fooctl.sh").read_text()
    out = capsys.readouterr().out
    assert "fooctl.sh replaced" in out
    assert "fooctl.cmd unchanged" in out


def test_a_second_run_says_both_launchers_are_unchanged(tmp_path, capsys):
    # arrange
    target = _scaffold(tmp_path)
    capsys.readouterr()

    # act
    rc = bootstrap.main(["init", "fooctl", "--dir", str(target), "--launchers-only"])

    # assert: nothing to do is said as such, and the batch file's CRLF is compared, not mistaken for a change
    assert rc == 0
    assert capsys.readouterr().out.splitlines() == ["simplon init: fooctl.sh unchanged",
                                                    "simplon init: fooctl.cmd unchanged"]


def test_the_block_dir_is_read_off_the_existing_launcher(tmp_path):
    # arrange: a product on agile-cockpit's layout, re-rendered without --orch-dir
    target = _scaffold(tmp_path, "--orch-dir", "deploy/orchestrator")
    (target / "fooctl.sh").unlink()
    (target / "fooctl.cmd").unlink()
    (target / "fooctl.sh").write_text('#!/usr/bin/env bash\nLAUNCH_ORCH_DIR="$ROOT/deploy/orchestrator"\n',
                                      encoding="utf-8")

    # act
    rc = bootstrap.main(["init", "fooctl", "--dir", str(target), "--launchers-only"])

    # assert
    assert rc == 0
    assert 'LAUNCH_ORCH_DIR="$ROOT/deploy/orchestrator"' in (target / "fooctl.sh").read_text()
    assert "deploy\\orchestrator" in (target / "fooctl.cmd").read_text()


def test_an_orch_dir_that_contradicts_the_launcher_is_refused(tmp_path, capsys):
    # arrange
    target = _scaffold(tmp_path, "--orch-dir", "deploy/orchestrator")
    before = (target / "fooctl.sh").read_text()

    # act
    rc = bootstrap.main(["init", "fooctl", "--dir", str(target), "--launchers-only",
                         "--orch-dir", "deploy/provision/orchestrator"])

    # assert
    assert rc == 2
    assert "--orch-dir says 'deploy/provision/orchestrator' and fooctl.sh launches 'deploy/orchestrator'" \
        in capsys.readouterr().err
    assert (target / "fooctl.sh").read_text() == before


def test_without_a_launcher_to_read_it_is_refused_and_writes_nothing(tmp_path, capsys):
    # arrange
    target = tmp_path / "fooctl"
    target.mkdir()

    # act
    rc = bootstrap.main(["init", "fooctl", "--dir", str(target), "--launchers-only"])

    # assert
    assert rc == 2
    assert "there is no fooctl.sh" in capsys.readouterr().err
    assert list(target.iterdir()) == []


def test_a_launcher_without_the_block_line_is_refused(tmp_path, capsys):
    # arrange: a hand-written launcher
    target = tmp_path / "fooctl"
    target.mkdir()
    (target / "fooctl.sh").write_text("#!/usr/bin/env bash\nexec python -m orchestrator \"$@\"\n",
                                      encoding="utf-8")

    # act
    rc = bootstrap.main(["init", "fooctl", "--dir", str(target), "--launchers-only"])

    # assert
    assert rc == 2
    assert "carries no `LAUNCH_ORCH_DIR=" in capsys.readouterr().err
