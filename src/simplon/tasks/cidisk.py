"""The docker-disk hygiene of a CI host: log rotation, builder GC and a daily prune, applied as root
(si#327).

WHAT WENT WRONG, MEASURED. A runner container answered `Disk quota exceeded` with 64 GB in
/var/lib/docker - an LXC container on ZFS with a refquota, so the quota is the filesystem's and no amount
of free space on the pool helps. The symptom reached the pipeline as
`E: You don't have enough free space in /var/cache/apt/archives/` inside a docker build, and on a second
run as a step with `conclusion: null`, no log at all, and the runner going offline. Neither text mentions
a disk, which is why this landed as a day of diagnosis rather than a minute of it.

WHAT FILLS IT, and each setting below answers one of them:

  * CONTAINER LOGS grow without bound under the default json-file driver - a chatty container is a
    multi-gigabyte log nobody looks at. `max-size` + `max-file` cap it.
  * THE BUILD CACHE grows with every `docker build` and is never reclaimed unless asked. `builder.gc`
    makes the engine itself keep it under a ceiling, which is the only half of this that needs no cron.
  * IMAGES AND STOPPED CONTAINERS accumulate per run. That is what the daily timer prunes, with an age
    filter so a run in progress is never the thing being pruned.

WHY A COMMAND AND NOT A RUNBOOK PARAGRAPH, which is `ciprivileges`' argument at a second place: this has
to be applied to every runner, and this account has eight across three repositories. Eight hand-edits of
one JSON file is how one host ends up with `log-opts` and no `builder.gc`, with nothing saying which.

WHY IT MERGES AND NEVER OVERWRITES. `/etc/docker/daemon.json` is where a host's `data-root`,
`registry-mirrors` and `insecure-registries` live. A command that wrote a fresh document carrying only the
settings it cares about would take a mirror away from a machine that needs one, and the symptom would
surface on the next build, nowhere near here. It is also why an UNPARSEABLE file is a refusal and not a
reason to start fresh: the one thing worse than a hand-edited daemon.json is this command deleting it.

WHY THE RESTART IS CONDITIONAL. `systemctl restart docker` kills every running container - on a runner,
including the job that is calling this. So the engine is restarted only when the document actually
changed, which makes a second run on a configured host a no-op rather than an outage.

WHAT IT DOES NOT DO. It does not touch volumes, anywhere, in either the timer or the advice it prints: a
runner with a persistent volume would lose it, and the loss would look like a bug somewhere else
entirely. And it does not decide the ALERT - a threshold that pages somebody is the operator's, not the
kernel's; `support ci-disk-preflight` is the in-job half and says its own number.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from simplon import disk, diskguard, log
from simplon.run import run

#: The files this touches. Module-level so a test can point them somewhere harmless.
DAEMON_JSON = Path("/etc/docker/daemon.json")
UNIT_DIR = Path("/etc/systemd/system")

#: Where the engine keeps what fills up. Read for the before/after report only - the authoritative
#: answer is whatever `data-root` in DAEMON_JSON says, and a host that moved it has moved this too.
DATA_DIR = Path("/var/lib/docker")

#: The unit pair. Named after the platform rather than the product: it is the same unit on every runner
#: in the family, and a second product installing it must find the first one's, not write a rival.
SERVICE = "simplon-docker-prune.service"
TIMER = "simplon-docker-prune.timer"

#: The settings, each with the number it was given and nothing derived twice.
#:
#: `KEEP_STORAGE` is a ceiling for the BUILD CACHE only, not for the data root - it is what the engine
#: itself will hold before collecting, so it must be comfortably under the smallest runner's quota. The
#: measured quota that failed was 64 GB total.
LOG_MAX_SIZE = "50m"
LOG_MAX_FILE = "3"
KEEP_STORAGE = "10GB"

#: The age below which the scheduled prune leaves things alone. Two days, deliberately longer than the
#: in-job `diskguard.CLEANUP_UNTIL`: this one runs on a timer and cannot know whether a build from this
#: morning is about to be resumed, so it keeps more than the step that runs at the end of a known job.
PRUNE_UNTIL = "48h"


#: The log driver the size caps apply to. Named, because `max-size` is a json-file option and setting it
#: while the host runs `journald` would be four settings that do nothing.
LOG_DRIVER = "json-file"


def _mapping(value: object) -> "dict[str, object]":
    """`value` as a document fragment, and `{}` for anything that is not one.

    A host's daemon.json is hand-edited, so `log-opts` may be a string or a list there. Merging into it
    would raise, out of a command whose whole promise is that it leaves a file it cannot understand alone -
    so a fragment that is not a mapping is replaced rather than merged into, and the settings still land.
    """
    return dict(value) if isinstance(value, dict) else {}


def document(current: "dict[str, object]") -> str:
    """`current` merged and rendered as the exact bytes this command writes.

    It exists so that "is the host already configured" and "what do we write" are ONE source. They were
    two for one test's lifetime, and the test caught it: a caller reproducing the document with different
    `json.dumps` arguments gets different bytes, the comparison says "changed", and the engine is
    restarted on every run - which on a runner means killing the job that called it.
    """
    return json.dumps(merged(current), indent=2, sort_keys=True) + "\n"


def merged(current: "dict[str, object]") -> "dict[str, object]":
    """`current` with this command's settings applied, and everything else left exactly as it was.

    Pure, so the merge can be asserted without a filesystem - including the property the conditional
    restart rests on, that merging twice is merging once.

    `builder:` is merged one level deeper than the rest, because a host may legitimately carry
    `builder.entitlements` and only `builder.gc` is ours.
    """
    out = dict(current)
    out["log-driver"] = LOG_DRIVER
    out["log-opts"] = {**_mapping(out.get("log-opts")),
                       "max-size": LOG_MAX_SIZE, "max-file": LOG_MAX_FILE}
    builder = _mapping(out.get("builder"))
    builder["gc"] = {**_mapping(builder.get("gc")),
                     "enabled": True, "defaultKeepStorage": KEEP_STORAGE}
    out["builder"] = builder
    return out


def _service_unit() -> str:
    """The prune service. `Type=oneshot` because a timer's job is to finish, not to stay running."""
    return (
        "[Unit]\n"
        "Description=Reclaim docker disk on a CI runner (simplon support ci-disk-hygiene)\n"
        "Documentation=https://marcozwyssig.github.io/simplon/how/ci-hosts/\n"
        "After=docker.service\n"
        "Requires=docker.service\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        # NO --volumes. A runner with a persistent volume would lose it, and the loss would look like a
        # bug somewhere else entirely.
        f"ExecStart=/usr/bin/docker system prune -af --filter until={PRUNE_UNTIL}\n"
    )


def _timer_unit() -> str:
    """Daily, with a randomised delay so eight runners do not all prune in the same minute."""
    return (
        "[Unit]\n"
        f"Description=Daily docker disk reclaim ({SERVICE})\n"
        "\n"
        "[Timer]\n"
        "OnCalendar=daily\n"
        # Persistent, so a runner that was off at the scheduled hour still prunes when it comes back -
        # the measured failure happened on a machine that had been offline.
        "Persistent=true\n"
        "RandomizedDelaySec=30m\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def _read_current() -> "dict[str, object]":
    """The host's daemon.json as a document, or a refusal that leaves it untouched."""
    if not DAEMON_JSON.exists():
        return {}
    text = DAEMON_JSON.read_text()
    try:
        current = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        log.die(f"{DAEMON_JSON} is not valid JSON ({exc}); NOTHING was written. This command merges into "
                f"that file and will not replace a document it could not read - a host's `data-root` or "
                f"`registry-mirrors` live there. Fix the file and run it again")
        raise
    if not isinstance(current, dict):
        log.die(f"{DAEMON_JSON} is valid JSON but not an object; NOTHING was written")
        raise ValueError(DAEMON_JSON)
    return current


def _write_if_changed(path: Path, body: str, *, dry_run: bool) -> bool:
    """Write `body` unless it is already there. True when the file changed."""
    if path.exists() and path.read_text() == body:
        return False
    if dry_run:
        log.info(f"would write {path}")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    log.info(f"wrote {path}")
    return True


def hygiene(dry_run: bool = False) -> int:
    """Configure docker log rotation, builder GC and a daily prune on THIS host. Needs root; idempotent.

    Prints `docker system df` and the data filesystem's fullness before and after, because "it ran" is not
    the question anybody has when they type this - "is there room now" is.
    """
    if os.getuid() != 0:
        log.die("configuring a CI host's docker disk needs root - it writes /etc/docker/daemon.json and "
                "/etc/systemd/system and restarts the engine. Run it once on each runner: "
                "sudo <product>.sh support ci-disk-hygiene")
        return 1

    _report("before")
    current = _read_current()
    changed = _write_if_changed(DAEMON_JSON, document(current), dry_run=dry_run)

    units = [_write_if_changed(UNIT_DIR / SERVICE, _service_unit(), dry_run=dry_run),
             _write_if_changed(UNIT_DIR / TIMER, _timer_unit(), dry_run=dry_run)]

    if dry_run:
        log.ok("dry run: nothing was written and the engine was not touched")
        return 0

    if any(units):
        run(["systemctl", "daemon-reload"])
    # Enabled unconditionally: a unit file that is present but not enabled is the inert-drop-in defect
    # `ciprivileges` measured, one directory along, and `enable --now` is idempotent.
    run(["systemctl", "enable", "--now", TIMER])

    if changed:
        # LAST, and only when the document really moved: this kills every running container, including
        # the job that may be calling it.
        log.warn("restarting docker - this kills every running container on this host")
        run(["systemctl", "restart", "docker"])
    else:
        log.info("daemon.json already carried these settings; the engine was NOT restarted")

    _report("after")
    log.ok(f"docker disk hygiene in place: logs capped at {LOG_MAX_SIZE} x{LOG_MAX_FILE}, build cache "
           f"held under {KEEP_STORAGE}, {TIMER} pruning anything older than {PRUNE_UNTIL} daily")
    return 0


def _report(when: str) -> None:
    """`docker system df` and the data filesystem's fullness - the verification, built in."""
    res = run(["docker", "system", "df"], check=False)
    if res.ok and res.out:
        log.info(f"docker system df ({when}):\n{res.out.strip()}")
    probe = run(["df", "-Ph", str(DATA_DIR)], check=False)
    if probe.ok and probe.out:
        log.info(f"disk ({when}):\n{probe.out.strip()}")
    else:
        log.info(f"disk ({when}): could not read df for the docker data directory "
                 f"(threshold in force elsewhere: {disk.DEFAULT_MIN_FREE_PCT}% free)")


# --- the two in-job halves, which are the library's and only placed here ---------------------------------
# Thin on purpose. `simplon.diskguard` is LIBRARY (`surface.py`): a product may call it directly, and two
# of them do. What belongs in a task body is the COORDINATE - the name a manifest places and a workflow
# step calls - and nothing else. A body with logic in it would be a second implementation of a decision
# that is already tested where it lives.


def preflight() -> int:
    """Refuse to start a job on a runner that is too full to finish one. Non-zero when the disk is low."""
    return diskguard.preflight()


def cleanup() -> int:
    """Give back what this run took: prune build cache older than `diskguard.CLEANUP_UNTIL`."""
    return diskguard.cleanup()
