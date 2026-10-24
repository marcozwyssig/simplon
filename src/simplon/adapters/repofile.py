"""One file committed to a branch of another GitHub repository, over the contents API (si#535).

THREE OUTCOMES, NEVER TWO. `written` carries the new commit's sha; `already current` means the file on the
branch is byte-identical and nothing was committed; `refused` carries GitHub's status and words, or the
reason no request was made. "Already current" must never read as a failed push, nor a failed push as
current, so each has its own value and `write()` never raises for a GitHub or network failure.

NO RETRY. A PUT that answers 409 because the blob sha moved under it (another writer) is `refused` with the
409: the next run reads the new file and decides again, rather than this one overwriting what it never saw.

READ BACK. After a write, the file at the new commit must equal the content; if it does not, the outcome
is `refused` with "read back differs", because a commit that holds other bytes is not the file asked for.

Nothing here knows what the file is or which package manager reads it, so the next one reuses it as is.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import requests
from github import GithubException, UnknownObjectException

from simplon.adapters import github


class State(Enum):
    WRITTEN = "written"
    CURRENT = "already current"
    REFUSED = "refused"


@dataclass(frozen=True)
class Outcome:
    state: State
    commit: str = ""     # set only for WRITTEN
    reason: str = ""     # set only for REFUSED


def write(repository: str, branch: str, path: str, content: bytes, message: str, token: str) -> Outcome:
    """Commit `content` to `path` on `branch` of `repository` (`owner/name`) with `token`."""
    where = f"{path} on {branch} of {repository}"
    try:
        repo = github.other(repository, token)
        try:
            existing = repo.get_contents(path, ref=branch)
        except UnknownObjectException:
            # No such file, or no such branch: GitHub answers both with 404. The PUT names the branch, so
            # an unknown one is refused there rather than written to the default branch.
            existing = None
        if isinstance(existing, list):
            return Outcome(State.REFUSED, reason=f"{where} is a directory, not a file: nothing was written")
        if existing is None:
            result = repo.create_file(path, message, content, branch=branch)
        elif existing.decoded_content == content:
            return Outcome(State.CURRENT)
        else:
            result = repo.update_file(path, message, content, sha=existing.sha, branch=branch)
        commit = result["commit"].sha
        back = repo.get_contents(path, ref=commit)
        if isinstance(back, list) or back.decoded_content != content:
            return Outcome(State.REFUSED, reason=f"{where}: read back differs at commit {commit}, which "
                                                 f"holds other bytes than were sent")
    except github.Unanswered as unanswered:
        return Outcome(State.REFUSED, reason=str(unanswered))
    except GithubException as refused:
        return Outcome(State.REFUSED, reason=f"{where}: {github.said(refused)}")
    except requests.exceptions.RequestException as unreachable:
        return Outcome(State.REFUSED, reason=f"{where}: could not reach GitHub: {unreachable}")
    return Outcome(State.WRITTEN, commit=commit)
