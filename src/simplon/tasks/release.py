"""`release:tag` - cut the release tag and push it (#32), carrying the release guard of #23.

WHY THIS IS A COMMAND AT ALL. Cutting a release here is two git commands typed by hand, and the README
describes them rather than offering them. That is the one step of the loop simplon does not hold, in a
kernel whose whole argument is that a delivery step declared once beats the same step retyped per
product. Nothing about the MECHANICS changes: the tag still IS the version, `pyproject.toml` still
declares `dynamic = ["version"]`, setuptools-scm still derives the number from the tag, and there is
still no number anywhere to edit first. What changes is that the act has a name, and therefore a place
to put a guard.

WHY THE GUARD LIVES HERE AND NOT IN THE WORKFLOW (#23, and its own comment says so). setuptools-scm
guarantees that a version names ONE commit; it does not guarantee that the commit is one `main` carries,
so a tag on a feature branch publishes without complaint today. A guard in `release.yml` would be
correct and bypassable: `git tag && git push` is a local act, it never runs a workflow step, and it is
the route everybody uses right now. Inside this command the guard sits on the path both routes take -
the only place where "the command everybody types" and "the thing that gets published" are the same
event. The hand-typed route still exists and still works, deliberately: it is the escape hatch, and it
is a better one than a flag, because a person typing raw git has decided something, whereas a flag gets
set once in a script and is never seen again. #23 asked for the exception to be LOUD rather than a
condition someone sets quietly; two typed git commands are as loud as an exception gets.

WHAT THE GUARD DOES NOT DO, and this is the line #32 draws twice. It does not ask the remote whether the
tag is free. A tag is unique on the remote, whoever pushes first owns the number, and the loser is told
by `git push` - that is #3's mechanism, it cost three collisions in one day to arrive at, and a
pre-flight check would replace a fact about the world with this command's opinion of it, raced anyway
between the asking and the pushing. The push IS the claim. So the collision arrives here as a REJECTION,
and this module's job is to say what that rejection left behind.

WHICH IS THE STATE THAT HAD NO NAME. A rejected push leaves the tag cut locally and unpublished: not
"nothing happened", not "released". Left unsaid, the next run reads `git tag` failing with "already
exists" as proof that the release went out. `gitops.tag_verdict` names it `("resume", "unpushed")`, and
every failure path below says in as many words whether the tag is still there and how to get rid of it.

`git push origin <tag>`, never `git push --tags`. `--tags` offers EVERY local tag to the remote,
including whatever somebody cut to try something out; measured here, a repository with two stray tags
offers both. Today's tag list makes it harmless and the flag makes it structural.
"""
from __future__ import annotations

from simplon import context, log
from simplon.tasks import gitops


def tag(tag: str) -> int:
    """Cut the release tag at HEAD and push it to origin - the whole act of choosing a version.

    `tag` is the tag EXACTLY as it will exist (`v1.4.0`), not a version the kernel decorates into one.
    Which tags publish is the product's statement, made in its release workflow's trigger and its
    setuptools-scm settings; a kernel that turned `1.4.0` into `v1.4.0` would be guessing at a
    convention it cannot see, and would guess wrong for the first product that spells it differently.
    The only shape check is `git check-ref-format` - git's own rule, not one of ours.
    """
    gitops.require_git()
    gitops.configure(context.current().root)
    product = context.current().name
    name = tag.strip()

    if not name:
        log.error("no tag given. The tag IS the version, so this command needs the one you are "
                  f"choosing: `./{product}.sh release tag v1.4.0`")
        return 1
    if not gitops.valid_tag_name(name):
        log.error(f"'{name}' is not a valid git tag name - `git check-ref-format` refuses it, so "
                  f"nothing was cut. Spaces, `..`, a trailing `.lock` and a leading `-` are the usual "
                  f"causes")
        return 1

    head = gitops.head_commit()
    if not head:
        log.error(f"nothing to tag: {gitops.ROOT} has no commit at HEAD (is it a git checkout?)")
        return 1

    branch = gitops.default_branch()
    if not gitops.fetch_branches():
        # Survivable, and stated rather than swallowed. A stale origin/<branch> can only make the guard
        # refuse a commit the branch really does carry; it cannot let an off-branch commit through.
        log.warn(f"could not fetch from origin, so origin/{branch} may be out of date. The guard below "
                 f"reads what is here; a stale ref can only make it refuse too much, never too little")
    if not gitops.ref_exists(f"origin/{branch}"):
        # Without this, `merge-base --is-ancestor` against a ref that does not exist answers "no" and
        # the refusal below would diagnose a feature branch in a repository that simply has no remote.
        log.error(f"there is no origin/{branch} here, so the question '{branch} carries this commit' "
                  f"has no answer - and nothing was cut. Add the remote and push {branch} first, or "
                  f"point origin/HEAD at the branch releases really are cut from "
                  f"(`git remote set-head origin -a`)")
        return 1

    action, reason = gitops.tag_verdict(carried_by_main=gitops.carried_by(head, f"origin/{branch}"),
                                        local_tag_at=gitops.tag_commit(name),
                                        head=head)

    if reason == "off-main":
        log.error(f"{name} was NOT cut: origin/{branch} does not carry this commit.")
        log.error(f"    the commit      {gitops.describe(head)}")
        log.error(f"    on branch       {gitops.current_branch()}")
        log.error(f"    origin/{branch}".ljust(20) + gitops.describe(f"origin/{branch}"))
        log.error("a release is built from the TAG, so the workflow would check this commit out and "
                  "publish it under a release number - a branch on PyPI, and a website describing it.")
        log.error(f"the way out is to merge it first and tag what {branch} then carries:")
        log.error(f"    git switch {branch} && git pull && ./{product}.sh release tag {name}")
        log.error(f"  (a squash merge REWRITES the commit, so tag {branch}'s head - the branch tip that "
                  f"went into it stays un-carried forever and will be refused again)")
        return 1

    if reason == "moved":
        # WHOSE TAG IS THIS? A local tag on another commit has two completely different causes, and
        # until this branch asked, it reported the wrong one of them as fact.
        #
        # `fetch_branches` keeps OUR fetch off the tags, but it cannot keep the USER off them: a plain
        # `git pull` brings a rival's tag down as a local tag, and that is the ordinary thing to do
        # before cutting a release - this command's own advice above says to do it. The tag is then
        # sitting here, on their commit, looking exactly like a leftover of ours.
        #
        # Asking origin here is NOT the pre-flight check acceptance 3 forbids. That one would decide
        # whether a FREE number may be claimed, replacing the push as the claim. Nothing is claimable
        # here in any case: the tag this repository holds names the wrong commit, so there is nothing to
        # push that would mean what the caller meant. The refusal is already settled by a local fact,
        # and the remote is asked only to say WHICH situation produced it - after which the advice is
        # either "take the next number" or "decide between two of your own commits", and those are
        # opposite actions.
        here = gitops.tag_commit(name)
        theirs = gitops.remote_tag_commit(name)
        log.error(f"{name} already exists here and names a different commit, so nothing was cut or "
                  f"pushed:")
        log.error(f"    {name} is at   {gitops.describe(here)}")
        log.error(f"    HEAD is at     {gitops.describe(head)}")
        if theirs is None:
            log.error("origin could not be asked, so whether this tag is yours or a copy of someone "
                      "else's cannot be told apart from here - and the two need opposite fixes. Get "
                      f"the remote back, or check by hand: git ls-remote --tags origin {name}")
        elif theirs == here:
            log.error(f"origin carries {name} at that same commit, so this is NOT a tag of yours left "
                      f"behind - it is the number, already claimed by someone else, fetched into this "
                      f"checkout by an ordinary `git pull`.")
            log.error(f"  the number is gone; take the next one:")
            log.error(f"      ./{product}.sh release tag <the next one>")
            log.error(f"  (`git tag -d {name}` would only delete your copy of their tag. The next "
                      f"fetch brings it back, and origin still has it either way.)")
        elif theirs:
            log.error(f"origin carries {name} at {gitops.describe(theirs)} - a third commit again, so the "
                      f"copy here is stale as well as misplaced. Refresh it before deciding anything:")
            log.error(f"      git fetch --force origin refs/tags/{name}:refs/tags/{name}")
        else:
            log.error("origin has no such tag, so this one is yours: cut by an earlier run, at a commit "
                      "the tree has since moved past. Moving it would publish something other than that "
                      "run promised. Decide which commit is the release:")
            log.error(f"    to keep it:     check that commit out and run this command there")
            log.error(f"    to replace it:  git tag -d {name}, then run this command again")
        return 1

    log.info(f"{gitops.describe(head)} is carried by origin/{branch}")

    cut_here = action == "cut"
    if cut_here:
        if not gitops.create_tag(name):
            log.error(f"git tag {name} failed, so nothing was cut and nothing was pushed")
            return 1
        log.info(f"cut {name} -> {gitops.describe(head)}")
    else:
        # Deliberately NOT "left by a run whose push did not land". That is the interesting case, but it
        # is not the only one reaching here: re-running the command after a SUCCESSFUL release lands on
        # the same verdict, and telling that caller their push failed would be inventing a failure. What
        # is true in both cases is that the tag is here and this run will not treat its existence as
        # proof of anything - the push and the read-back settle it.
        log.warn(f"{name} is already cut here at {head[:7]}. This run does not read that as a release "
                 f"that already happened: it pushes the tag and then asks origin. If an earlier push "
                 f"did not land, this is that push; if it did, origin simply reports it up to date.")

    log.info(f"git push origin {name}  (this one tag; `--tags` would offer every local tag)")
    pushed = gitops.push_tag(name)
    for stream in (pushed.out, pushed.err):
        if stream.strip():
            print(stream.rstrip(), flush=True)

    if not pushed.ok:
        # WHY IT FAILED, asked of the remote rather than read out of git's prose. A taken number and a
        # dead network are different situations with different ways out, and one message covering both
        # would tell a reader nothing - but the first draft of this decided it with
        # `"already exists" in git's stderr`, which is English, and nothing in `simplon.run` pins a
        # locale. On a translated git that string never matches and every collision would have been
        # reported as an ordinary failure with "retry the push" underneath it, advice that can only
        # fail again.
        #
        # So the question goes to origin, AFTER the push has been refused. That is not the pre-flight
        # check acceptance 3 forbids: the claim was already staked and already lost. `None` (origin
        # unreachable) is not "free" - it is "cannot say", and it falls through to the generic message
        # rather than promising anything.
        taken = bool(gitops.remote_tag_commit(name))
        provenance = "cut by this run" if cut_here else "already here before this run"
        if taken:
            log.error(f"origin refused {name}: it already carries that tag. Someone claimed the number "
                      f"first - a tag is unique on the remote, and being told by `git push` instead of "
                      f"by a reviewer is the point rather than a fault.")
        else:
            log.error(f"git push origin {name} failed (rc={pushed.rc}); git's own words are above.")
        log.error(f"THE TAG IS STILL HERE: {name} -> {head[:7]}, {provenance}. Nothing was published.")
        if taken:
            log.error(f"  that number is gone. Drop it and take the next one:")
            log.error(f"      git tag -d {name} && ./{product}.sh release tag <the next one>")
        else:
            log.error(f"  to retry the push:     ./{product}.sh release tag {name}")
            log.error(f"  to abandon it instead: git tag -d {name}")
        return 1

    # The read-back, for the reason `release:image` states about its own push: a push nobody verifies is
    # the same defect as a report nobody reads, and this project has shipped that twice. `ls-remote`
    # asks the REMOTE and keeps no local store, so it cannot answer out of a cache.
    there = gitops.remote_tag_commit(name)
    if there is None:
        log.error(f"git push exited 0, but origin could not be asked whether it really has {name}. "
                  f"The tag is still here locally, and an unverified push is exactly what this "
                  f"read-back exists to stop being reported as done")
        return 1
    if there != head:
        log.error(f"git push exited 0, but origin does not carry {name} at {head[:7]} - it reports "
                  f"{there[:7] or 'no such tag'}. The tag is still here locally and the publish is "
                  f"unproven, which is exactly what this read-back exists to stop being reported as done")
        return 1

    # WHAT THIS DOES NOT SAY, and the first version of it did: what happens next. It claimed "the
    # workflow builds the wheel, publishes it and rebuilds the website" - unconditionally, for every
    # tag and every product. Two things were wrong with that. It is simplon's own convention stated as
    # a fact about somebody else's repository, the exact imposition this command refuses when it
    # declines to turn `1.4.0` into `v1.4.0`; and it is not even reliable here, because a tag this
    # command pushes happily - `0.1.14`, say - is one `tags: ["v*"]` never sees. Reporting a
    # publication that no workflow was ever going to perform is the failure mode this whole project is
    # organised against, dressed up as a success line.
    #
    # So: the fact, and then the honest shape of the unknown.
    log.ok(f"origin carries {name} -> {gitops.describe(head)}")
    log.info("what happens next belongs to your release workflow, not to this command: it pushed the "
             "tag and confirmed origin has it, and that is all it knows. If nothing is watching for a "
             "tag of this shape, nothing further happens - and nothing says so.")
    return 0
