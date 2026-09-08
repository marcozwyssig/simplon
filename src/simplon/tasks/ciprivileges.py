"""The CI privileges of a host: passwordless sudo and the docker group, granted deliberately (si#92).

WHY THIS IS A COMMAND AND NOT A PARAGRAPH IN A RUNBOOK. Every product that puts a CI agent on a host
writes the same six lines, and one of them is easy to leave out: without `#includedir /etc/sudoers.d` in
`/etc/sudoers` the drop-in in that directory is INERT, and everything still looks right. Measured on
three hosts that answered `sudo: a password is required` while the file sat at exactly the expected path
with exactly the expected content. A hand-copied version without that check reports success and delivers
nothing.

WHY IT REFUSES WHEN IT IS NOT ROOT. This grants the privilege the kernel needs in order to be allowed to
do anything, so it cannot grant it to itself - si#87 drew the same line one level down, where the docker
group moved to the engine install. The refusal naming the cure IS the value here; "it did not work" is
not.

WHY IT IS NOT PART OF `support install`. That command runs on a developer's laptop too, and
`NOPASSWD: ALL` for a user is not a convenience there but a change nobody asked for. A privilege grant
has to be something a person typed.

WHAT IT VERIFIES, AND AS WHOM. Root can always sudo, so a check from here would pass on a host where the
grant did nothing. The verification runs AS the user - the same distinction si#87 turned on, one step up.
"""
from __future__ import annotations

import os
import pwd
from pathlib import Path

from simplon import log
from simplon.run import run

#: The two files this touches. Module-level so a test can point them somewhere harmless.
SUDOERS = Path("/etc/sudoers")
SUDOERS_D = Path("/etc/sudoers.d")

#: The line without which everything in SUDOERS_D is inert.
INCLUDEDIR = "#includedir /etc/sudoers.d"


def _user_exists(user: str) -> bool:
    try:
        pwd.getpwnam(user)
        return True
    except KeyError:
        return False


def _groups_of(user: str) -> list[str]:
    return run(["id", "-nG", user]).out.split()


def _write_sudoers_dropin(user: str) -> None:
    """Validate the drop-in BEFORE it is in force, then move it into place.

    A broken file in /etc/sudoers.d does not fail this command - it breaks `sudo` for everyone on the
    host, and the way back needs the privilege that just stopped working. So it is written beside the
    directory, checked with `visudo -c`, and only then moved.
    """
    staged = SUDOERS_D.parent / f".{user}.sudoers.staged"
    staged.write_text(f"{user} ALL=(ALL) NOPASSWD: ALL\n")
    staged.chmod(0o440)
    if not run(["visudo", "-cqf", str(staged)]).ok:
        staged.unlink(missing_ok=True)
        log.die(f"visudo refused the drop-in for '{user}', so NOTHING was installed - "
                f"{SUDOERS_D} is untouched and sudo on this host still works")
        return
    staged.replace(SUDOERS_D / user)
    (SUDOERS_D / user).chmod(0o440)


def _ensure_includedir() -> None:
    body = SUDOERS.read_text()
    if any(line.strip() == INCLUDEDIR for line in body.splitlines()):
        return
    log.info(f"{SUDOERS} does not read {SUDOERS_D}; adding the include (without it the drop-in is inert)")
    SUDOERS.write_text(body + ("" if body.endswith("\n") else "\n") + INCLUDEDIR + "\n")


def grant(user: str) -> int:
    """Give `user` passwordless sudo and docker-group membership on THIS host. Needs root; idempotent.

    Both halves are what a CI agent needs before it can provision anything else, and neither can be
    obtained from inside a job: sudo is the seed privilege, and a group is inherited at process start -
    so an agent that is already running must be RESTARTED afterwards, which this command says and does
    not do, because it does not know what the service is called.
    """
    if os.getuid() != 0:
        log.die("granting CI privileges needs root - this writes /etc/sudoers.d and changes group "
                "membership, which is exactly the privilege it is granting, so it cannot be taken "
                "from inside a job. Run it once on the host: sudo <product>.sh support ci-privileges "
                f"{user}")
        return 1
    if not _user_exists(user):
        log.die(f"no such user on this host: '{user}' - nothing was written")
        return 1

    _write_sudoers_dropin(user)
    _ensure_includedir()
    run(["groupadd", "-f", "docker"])
    run(["usermod", "-aG", "docker", user])

    # Verified AS the user, because root proves nothing here.
    if not run(["sudo", "-nu", user, "sudo", "-n", "true"]).ok:
        log.die(f"'{user}' still cannot sudo without a password. The drop-in is in place, so the usual "
                f"cause is that {SUDOERS} does not read {SUDOERS_D}, or another rule later in the file "
                f"overrides it")
        return 1
    if "docker" not in _groups_of(user):
        log.warn(f"'{user}' is not in the docker group yet; if the group was created just now this is "
                 "a stale name-service cache, otherwise usermod did not take")
    log.ok(f"'{user}' has passwordless sudo and the docker group on this host")
    log.info("a CI agent that is ALREADY RUNNING inherited its groups at start and must be restarted "
             "before the docker group reaches it")
    return 0
