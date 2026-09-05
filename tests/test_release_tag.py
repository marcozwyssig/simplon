"""Unit tests for `release:tag` (#32) and the release guard it carries (#23).

TWO SUITES IN ONE FILE, and the split is deliberate.

`tag_verdict` is the pure decision, tested the way `prune_verdict` is: primitives in, a named state out.
It is where the ORDER of the rules is pinned, and the order is the part a reader has to be able to check
without a repository.

Everything below `--- against a real remote ---` runs against REAL git repositories: a work tree and a
`--bare` origin it pushes to, both under `tmp_path`. Nothing here is monkeypatched, and that is the
point. The two states #32's acceptance names - a push the remote REFUSES, and the local tag that push
leaves behind - do not exist in a mocked `run()`; a suite that faked them would assert the wording of a
message about a situation it had never produced. They cost about a second in total and buy the only
proof that matters.

No network: the remote is a bare repository on disk, which speaks the same protocol as origin does and
refuses a taken tag with the same words.

AAA throughout.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from simplon import context, vcs
from simplon.context import ProductContext
from simplon.tasks import release


# --- the pure decision -------------------------------------------------------------------------------

def test_the_verdict_cuts_a_tag_that_does_not_exist_yet():
    # arrange / act
    action, reason = vcs.tag_verdict(carried_by_main=True, local_tag_at="", head="abc1234")

    # assert
    assert (action, reason) == ("cut", "")


def test_the_verdict_refuses_a_commit_the_default_branch_does_not_carry():
    # arrange / act: #23's whole question, and the answer is a refusal rather than a warning
    action, reason = vcs.tag_verdict(carried_by_main=False, local_tag_at="", head="abc1234")

    # assert
    assert (action, reason) == ("refuse", "off-main")


def test_the_verdict_resumes_a_tag_already_cut_at_head():
    # arrange / act: the state a rejected push leaves behind - neither "nothing to do" nor "done"
    action, reason = vcs.tag_verdict(carried_by_main=True, local_tag_at="abc1234", head="abc1234")

    # assert
    assert (action, reason) == ("resume", "unpushed")


def test_the_verdict_refuses_a_tag_that_already_names_another_commit_here():
    # arrange / act
    action, reason = vcs.tag_verdict(carried_by_main=True, local_tag_at="0000111", head="abc1234")

    # assert
    assert (action, reason) == ("refuse", "moved")


def test_the_guard_outranks_a_tag_that_is_already_cut():
    # arrange / act: a tag cut on a feature branch by an earlier run is still a tag on a feature branch,
    # so the resume must not be the answer that reaches the remote
    action, reason = vcs.tag_verdict(carried_by_main=False, local_tag_at="abc1234", head="abc1234")

    # assert
    assert (action, reason) == ("refuse", "off-main")


# --- against a real remote ---------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _sha(repo: Path, rev: str = "HEAD") -> str:
    return _git(repo, "rev-parse", rev).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", name)
    return _sha(repo)


class Lab:
    """A work tree, the bare repository it calls `origin`, and a second clone to play the rival with."""

    def __init__(self, work: Path, origin: Path):
        self.work, self.origin = work, origin

    def remote_tags(self) -> dict[str, str]:
        out = _git(self.work, "ls-remote", "--tags", str(self.origin)).stdout
        return {line.split("refs/tags/")[1]: line.split("\t")[0]
                for line in out.splitlines() if "refs/tags/" in line and not line.endswith("^{}")}

    def local_tags(self) -> list[str]:
        return sorted(t for t in _git(self.work, "tag", "-l").stdout.split())


@pytest.fixture
def lab(tmp_path, monkeypatch) -> Lab:
    """A real repository pair, isolated from the developer's own git configuration.

    GIT_CONFIG_GLOBAL/SYSTEM point at an empty file so a machine that signs every commit, rewrites
    author identities or sets `push.followTags` cannot change what this suite measures - the last of
    those would push tags this suite asserts are still unpushed.
    """
    empty = tmp_path / "gitconfig"
    empty.write_text("", encoding="utf-8")
    for name, value in (("GIT_CONFIG_GLOBAL", str(empty)), ("GIT_CONFIG_SYSTEM", str(empty)),
                        ("GIT_AUTHOR_NAME", "Test"), ("GIT_AUTHOR_EMAIL", "test@example.invalid"),
                        ("GIT_COMMITTER_NAME", "Test"), ("GIT_COMMITTER_EMAIL", "test@example.invalid")):
        monkeypatch.setenv(name, value)

    origin, work = tmp_path / "origin.git", tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    _commit(work, "one")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "-u", "origin", "main")

    monkeypatch.setattr(context, "_current", ProductContext("sample", work, work / "sample.yaml"))
    return Lab(work, origin)


def _rival_claims(lab: Lab, tmp_path: Path, tag: str) -> str:
    """Someone else pushes `tag` first, from their own clone - the collision #3 relies on, produced
    rather than described. Returns the commit they claimed it for.

    They then commit ONCE MORE and push `main` past the tagged commit, which is what makes this a real
    collision rather than a coincidence: without it our head would land on the very commit their tag
    names, and git answers `Everything up-to-date` to a tag push that changes nothing.
    """
    rival = tmp_path / "rival"
    subprocess.run(["git", "clone", "-q", str(lab.origin), str(rival)], check=True)
    claimed = _commit(rival, "theirs")
    _git(rival, "tag", tag)
    _commit(rival, "and-more")
    _git(rival, "push", "-q", "origin", "main")
    _git(rival, "push", "-q", "origin", tag)
    return claimed


# Acceptance 2: a tag on a commit `main` does not carry is refused, loudly, with the reason and the way out.

def test_a_tag_on_a_commit_the_default_branch_does_not_carry_is_refused(lab, capsys):
    # arrange: a feature branch, exactly the state nothing stops anyone from tagging today
    _git(lab.work, "checkout", "-q", "-b", "feature")
    _commit(lab.work, "two")

    # act
    rc = release.tag("v1.0.0")

    # assert: refused, and NOTHING was cut - a refusal that left a tag behind would be the very
    # half-done state acceptance 5 is about
    assert rc == 1
    assert lab.local_tags() == []
    assert lab.remote_tags() == {}


def test_the_refusal_names_the_commit_the_branch_and_the_head_of_main(lab, capsys):
    # arrange: #23's third open question - the message has to let a human see the situation, not read
    # "protection rule failed"
    _git(lab.work, "checkout", "-q", "-b", "feature")
    head = _commit(lab.work, "two")
    main_head = _sha(lab.work, "main")

    # act
    release.tag("v1.0.0")

    # assert
    err = capsys.readouterr().err
    assert head[:7] in err
    assert main_head[:7] in err
    assert "feature" in err
    assert "origin/main" in err


def test_the_refusal_names_a_way_out_that_does_not_weaken_the_guard(lab, capsys):
    # arrange
    _git(lab.work, "checkout", "-q", "-b", "feature")
    _commit(lab.work, "two")

    # act
    release.tag("v1.0.0")

    # assert: merging first is the way out, and it is the only one offered - a flag that switched the
    # guard off would be the "silently set condition" #23 asks for it not to be
    err = capsys.readouterr().err
    assert "merge" in err.lower()


# Acceptance 3: a tag the remote already has fails AT THE REMOTE, not at a pre-check of our own.

def test_a_tag_the_remote_already_has_is_refused_by_the_remote(lab, tmp_path, capsys):
    # arrange: a rival claims the number first, from their own clone, and we never learn of it - which
    # is the real case: the number a stranger reserved is in no tag and no commit we can see
    _rival_claims(lab, tmp_path, "v1.0.0")
    _git(lab.work, "fetch", "-q", "--no-tags", "origin")
    _git(lab.work, "merge", "-q", "--ff-only", "origin/main")

    # act
    rc = release.tag("v1.0.0")

    # assert: it got as far as the push - the tag was CUT locally, which is the proof that no
    # pre-check of ours decided this. The remote did.
    assert rc == 1
    assert lab.local_tags() == ["v1.0.0"]
    out = capsys.readouterr()
    assert "already exists" in (out.out + out.err)


def test_nothing_asks_the_remote_whether_the_tag_is_taken_before_cutting_it(lab, tmp_path, capsys):
    # arrange: the same collision. What this pins is the ABSENCE of a pre-flight check - `ls-remote`
    # before the push would let this task decide the collision itself, and #3's whole point is that the
    # remote decides it. If a pre-check were ever added, the tag would not be cut and this goes red.
    _rival_claims(lab, tmp_path, "v1.0.0")
    _git(lab.work, "fetch", "-q", "--no-tags", "origin")
    _git(lab.work, "merge", "-q", "--ff-only", "origin/main")

    # act
    release.tag("v1.0.0")

    # assert
    assert _sha(lab.work, "v1.0.0") == _sha(lab.work, "HEAD")


# Acceptance 5: a rejected push says whether the tag stayed behind.

def test_a_rejected_push_says_the_tag_was_left_behind(lab, tmp_path, capsys):
    # arrange
    _rival_claims(lab, tmp_path, "v1.0.0")
    _git(lab.work, "fetch", "-q", "--no-tags", "origin")
    _git(lab.work, "merge", "-q", "--ff-only", "origin/main")

    # act
    release.tag("v1.0.0")

    # assert: the state has a name in the output, and the two ways out of it are both named. Without
    # this the next run reads "tag already exists" as "already released".
    err = capsys.readouterr().err
    assert "v1.0.0" in err
    assert "still" in err.lower() or "left" in err.lower()
    assert "git tag -d v1.0.0" in err
    assert "nothing was published" in err.lower()


def test_a_second_run_resumes_the_cut_tag_instead_of_reading_it_as_done(lab, tmp_path, capsys):
    # arrange: the first run is refused by the remote and leaves the tag behind; the rival's tag is then
    # deleted, so the second run's push can land. A body that treated "tag exists" as "already released"
    # would report OK here and publish nothing.
    _rival_claims(lab, tmp_path, "v1.0.0")
    _git(lab.work, "fetch", "-q", "--no-tags", "origin")
    _git(lab.work, "merge", "-q", "--ff-only", "origin/main")
    release.tag("v1.0.0")
    subprocess.run(["git", "-C", str(lab.origin), "tag", "-d", "v1.0.0"], capture_output=True)
    capsys.readouterr()

    # act
    rc = release.tag("v1.0.0")

    # assert
    assert rc == 0
    assert lab.remote_tags()["v1.0.0"] == _sha(lab.work, "HEAD")
    assert "resume" in capsys.readouterr().out.lower()


# H1: a plain `git pull` brings a rival's tag down as a LOCAL tag, and the refusal must not then
# describe someone else's claim as a leftover of ours.

def _pull_including_tags(lab: Lab) -> None:
    """What a person actually types before cutting a release - and what this command's own off-main
    advice tells them to type. `git pull` fetches tags; `--no-tags` protects only the fetch INSIDE the
    command, never the user's own."""
    _git(lab.work, "pull", "-q")


def test_a_plain_git_pull_brings_the_rivals_tag_and_it_is_not_mistaken_for_our_own(lab, tmp_path, capsys):
    # arrange: the rival holds v1.0.0; the user pulls before releasing, exactly as advised
    _rival_claims(lab, tmp_path, "v1.0.0")
    _pull_including_tags(lab)
    assert lab.local_tags() == ["v1.0.0"], "the pull really did bring the tag down"

    # act
    rc = release.tag("v1.0.0")

    # assert: refused, and named as someone else's claim rather than as our own leftover
    err = capsys.readouterr().err
    assert rc == 1
    assert "already claimed by someone else" in err
    assert "not a tag of yours" in err.lower()


def test_the_remote_is_asked_before_that_refusal_is_diagnosed(lab, tmp_path, capsys):
    # arrange: the advice must be the OPPOSITE of the leftover case - take the next number, and do not
    # bother deleting a copy the next fetch restores
    _rival_claims(lab, tmp_path, "v1.0.0")
    _pull_including_tags(lab)

    # act
    release.tag("v1.0.0")

    # assert
    err = capsys.readouterr().err
    assert "take the next one" in err
    assert "would only delete your copy of their tag" in err


def test_our_own_leftover_on_another_commit_still_reads_as_ours(lab, capsys):
    # arrange: the same verdict, the opposite cause - origin has no such tag, so it really is ours
    _git(lab.work, "tag", "v1.0.0")
    _commit(lab.work, "two")
    _git(lab.work, "push", "-q", "origin", "main")

    # act
    release.tag("v1.0.0")

    # assert
    err = capsys.readouterr().err
    assert "origin has no such tag, so this one is yours" in err
    assert "git tag -d v1.0.0" in err


def test_a_tag_that_already_names_another_commit_here_is_refused_before_the_push(lab, capsys):
    # arrange: the tag was cut on an earlier commit and the tree has moved on. Re-pointing it silently
    # would publish something other than what the earlier run promised.
    earlier = _sha(lab.work)
    _git(lab.work, "tag", "v1.0.0")
    _commit(lab.work, "two")
    _git(lab.work, "push", "-q", "origin", "main")

    # act
    rc = release.tag("v1.0.0")

    # assert
    assert rc == 1
    assert _sha(lab.work, "v1.0.0") == earlier
    assert lab.remote_tags() == {}
    assert "git tag -d v1.0.0" in capsys.readouterr().err


# The push itself.

def test_the_happy_path_cuts_the_tag_pushes_it_and_reads_it_back_off_the_remote(lab, capsys):
    # arrange / act
    rc = release.tag("v1.0.0")

    # assert
    assert rc == 0
    assert lab.remote_tags() == {"v1.0.0": _sha(lab.work, "HEAD")}
    assert "v1.0.0" in capsys.readouterr().out


def test_the_push_names_the_one_tag_and_leaves_every_other_local_tag_alone(lab, capsys):
    # arrange: the measured difference between `git push origin <tag>` and `git push --tags`. A stray
    # local tag is not hypothetical - it is what anyone trying something out leaves behind, and `--tags`
    # would publish it.
    _git(lab.work, "tag", "scratch-experiment")

    # act
    release.tag("v1.0.0")

    # assert
    assert sorted(lab.remote_tags()) == ["v1.0.0"]
    assert lab.local_tags() == ["scratch-experiment", "v1.0.0"]


# M1: the success line reports what happened, and does not promise what a workflow will do with it.

def test_the_success_line_states_the_fact_and_promises_no_publication(lab, capsys):
    # arrange / act
    rc = release.tag("v1.0.0")

    # assert
    out = capsys.readouterr().out
    assert rc == 0
    assert "origin carries v1.0.0" in out
    # The first version of this message said "the workflow builds the wheel, publishes it, and rebuilds
    # the website" - unconditionally, for every product this catalogue reaches. It is simplon's own
    # convention stated as a fact about somebody else's repository, and it is not even reliable here.
    for promise in ("wheel", "PyPI", "website", "publishes it"):
        assert promise not in out, f"the success line must not promise {promise!r}"


def test_a_tag_no_workflow_may_be_watching_for_is_still_reported_honestly(lab, capsys):
    # arrange: `0.1.14` - no `v`. The command pushes it, because which tags publish is the product's
    # statement and not the kernel's; what it must not do is call that a release.
    rc = release.tag("0.1.14")

    # act
    out = capsys.readouterr().out

    # assert
    assert rc == 0
    assert lab.remote_tags() == {"0.1.14": _sha(lab.work, "HEAD")}
    assert "nothing further happens" in out and "nothing says so" in out


def test_a_rerun_after_a_successful_release_does_not_invent_a_failed_push(lab, capsys):
    # arrange: the resume verdict is reached by two roads - a push that did not land, and a release that
    # went out fine. Telling the second caller their push failed would be inventing a failure.
    release.tag("v1.0.0")
    capsys.readouterr()

    # act
    rc = release.tag("v1.0.0")

    # assert
    out = capsys.readouterr().out
    assert rc == 0
    assert "did not land" not in out.split("If an earlier push")[0]
    assert "origin carries v1.0.0" in out


def test_a_push_that_fails_for_no_collision_is_not_reported_as_a_taken_number(lab, capsys):
    # arrange: the reason is asked OF ORIGIN rather than parsed out of git's English. Here origin is
    # gone entirely - a failure with no collision behind it - and the advice must be "retry", never
    # "the number is gone".
    _git(lab.work, "remote", "set-url", "origin", str(lab.origin) + "-does-not-exist")

    # act
    rc = release.tag("v1.0.0")

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert "that number is gone" not in err
    assert "to retry the push" in err
    assert "THE TAG IS STILL HERE" in err


def test_nothing_in_the_body_classifies_a_failure_by_reading_gits_english(lab):
    # arrange: `simplon.run` pins no locale, so a translated git would have made every collision read as
    # an ordinary failure with "retry the push" underneath - advice that can only fail again. This is the
    # absence that keeps it out.
    body = (Path(__file__).resolve().parents[1] / "src" / "simplon" / "tasks" / "release.py").read_text(
        encoding="utf-8")
    code = "\n".join(line for line in body.splitlines() if not line.strip().startswith("#"))

    # act / assert
    for english in ('"already exists"', "'already exists'", '"rejected"', '"up to date"'):
        assert english not in code, f"a decision must not hang on git printing {english}"


def test_a_tag_name_git_would_refuse_is_caught_before_anything_happens(lab, capsys):
    # arrange / act: `git check-ref-format`'s own rules, not a convention of ours - the kernel does not
    # know which tag shape a product's release workflow listens for
    rc = release.tag("v1.0 0")

    # assert
    assert rc == 1
    assert lab.local_tags() == []
    assert "not a valid" in capsys.readouterr().err.lower()


def test_an_empty_tag_is_refused(lab, capsys):
    # arrange / act
    rc = release.tag("   ")

    # assert
    assert rc == 1
    assert lab.local_tags() == []


def test_the_guard_reads_the_branch_origin_head_names_rather_than_assuming_main(tmp_path, monkeypatch,
                                                                                capsys):
    # arrange: a remote whose default branch is `trunk`. Assuming `main` would judge every commit
    # against a branch that does not exist and refuse every release.
    empty = tmp_path / "gitconfig"
    empty.write_text("", encoding="utf-8")
    for name, value in (("GIT_CONFIG_GLOBAL", str(empty)), ("GIT_CONFIG_SYSTEM", str(empty)),
                        ("GIT_AUTHOR_NAME", "Test"), ("GIT_AUTHOR_EMAIL", "test@example.invalid"),
                        ("GIT_COMMITTER_NAME", "Test"), ("GIT_COMMITTER_EMAIL", "test@example.invalid")):
        monkeypatch.setenv(name, value)
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "trunk", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "trunk", str(work)], check=True)
    _commit(work, "one")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "-u", "origin", "trunk")
    _git(work, "remote", "set-head", "origin", "-a")
    monkeypatch.setattr(context, "_current", ProductContext("sample", work, work / "sample.yaml"))

    # act
    rc = release.tag("v1.0.0")

    # assert
    assert rc == 0
    assert "trunk" in capsys.readouterr().out


def test_a_repository_with_no_remote_branch_to_judge_against_is_refused_rather_than_guessed(
        tmp_path, monkeypatch, capsys):
    # arrange: no origin at all. `merge-base --is-ancestor` against a ref that does not exist answers
    # "not an ancestor", which reads exactly like a feature branch - a wrong diagnosis for a repository
    # that simply has no remote yet.
    empty = tmp_path / "gitconfig"
    empty.write_text("", encoding="utf-8")
    for name, value in (("GIT_CONFIG_GLOBAL", str(empty)), ("GIT_CONFIG_SYSTEM", str(empty)),
                        ("GIT_AUTHOR_NAME", "Test"), ("GIT_AUTHOR_EMAIL", "test@example.invalid"),
                        ("GIT_COMMITTER_NAME", "Test"), ("GIT_COMMITTER_EMAIL", "test@example.invalid")):
        monkeypatch.setenv(name, value)
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    _commit(work, "one")
    monkeypatch.setattr(context, "_current", ProductContext("sample", work, work / "sample.yaml"))

    # act
    rc = release.tag("v1.0.0")

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert sorted(_git(work, "tag", "-l").stdout.split()) == []
    assert "origin/main" in err
