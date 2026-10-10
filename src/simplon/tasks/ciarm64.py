"""linux/arm64 emulation on a CI host, checked first and registered only when missing (si#358).

WHY A COMMAND AND NOT A PARAGRAPH, which is `ciprivileges`' and `cidisk`'s argument at a third place.
firn's release builds its image for linux/amd64 AND linux/arm64 (si#347). On a runner without an arm64
binfmt handler the build fails a minute in with `exec format error`, and the cure differs by what the
runner is - a VM takes a package, an LXC container takes a boot-time script, because there
`tonistiigi/binfmt --install` is refused with `permission denied` on `/proc/sys/fs/binfmt_misc/register`.
firn wrote both recipes down (`docs/07-docker.md` §7, measured in firn#945 and firn#949). A recipe that
every runner owner re-derives from prose is how one host ends up registered until the next reboot and
nothing says so.

WHAT DECIDES THE BRANCH, AND WHAT IS REFUSED. `systemd-detect-virt` answers. A VM or bare metal (`none`)
takes `qemu-user-binfmt`, which registers through `systemd-binfmt` at every boot. An `lxc` container
takes the script and a unit ordered before docker. ANY OTHER ANSWER IS REFUSED BY NAME before anything
is changed: a docker-in-docker runner or an nspawn container is neither recipe, and guessing one would
report a green setup that registered nothing.

WHAT "SET UP" MEANS IS ASKED OF THE BUILDER A BUILD USES. `image.ensure_builder()` makes the same
`simplon` builder a multi-platform build makes, and its platform list is the answer. Not a file under
`/proc/sys/fs/binfmt_misc`: measured on this kernel's own development host, an LXC whose
`binfmt_misc` directory is EMPTY while every builder lists linux/arm64, because the Proxmox node's
registration reaches the container. A file check there would install a second registration for nothing.

THREE OUTCOMES, EACH WITH ITS OWN TEXT, because "nothing to do" is not "done" and neither is "failed":
the builder already runs arm64 and nothing was installed; it runs arm64 after this command changed the
host (or only dropped a builder created before the emulator was); or it still does not, which is red.

WHY THE BUILDER IS DROPPED. A builder bootstrapped before the emulator was registered does not see it
until it is created again. `docker buildx rm simplon` costs the next build a cold cache and nothing else.

WHAT IT DOES NOT DO. It registers arm64 only - the one platform any product here declares beyond amd64.
And it never runs inside a job: it needs root and changes the host kernel for every process on it, which
is a decision for whoever owns the machine. That is why it is a command a person types, as root, once.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from simplon import log
from simplon.run import run
from simplon.labhost import BINFMT_IMAGE
from simplon.tasks import image

#: The one platform this registers.
PLATFORM = "linux/arm64"

#: `systemd-detect-virt` answers that take the package. `none` is bare metal; the rest are its VM names.
VMS = frozenset({"none", "kvm", "qemu", "amazon", "bochs", "xen", "uml", "vmware", "oracle", "microsoft",
                 "zvm", "parallels", "bhyve", "qnx", "acrn", "powervm", "apple", "sre", "google"})

#: The answer that takes the boot-time script.
LXC = "lxc"

#: The two branches, as `branch()` names them.
VM_BRANCH = "vm"
LXC_BRANCH = "lxc"

#: The package a VM takes. In Debian 13 `qemu-user-static` is a transitional package for it.
PACKAGE = "qemu-user-binfmt"

#: The LXC branch's files. Module-level so a test can point them somewhere harmless.
INTERPRETER = Path("/usr/local/lib/qemu-aarch64-static")
SCRIPT = Path("/usr/local/sbin/binfmt-aarch64")
UNIT_DIR = Path("/etc/systemd/system")
UNIT = "simplon-binfmt-aarch64.service"

#: Where the static interpreter sits inside BINFMT_IMAGE - the image the kernel already pins.
INTERPRETER_INSIDE = "/usr/bin/qemu-aarch64"

#: The standard aarch64 ELF magic and mask - the ones `tonistiigi/binfmt` writes - with the F flag, so the
#: kernel opens the interpreter once, at registration, and every nested container can use it.
_REGISTER = (r":qemu-aarch64:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00"
             r":\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff"
             r":{interpreter}:POCF")


def branch(answer: str) -> str:
    """The branch a `systemd-detect-virt` answer takes, or '' for one this command has no recipe for.
    Pure."""
    answer = answer.strip()
    if answer in VMS:
        return VM_BRANCH
    if answer == LXC:
        return LXC_BRANCH
    return ""


def script() -> str:
    """The LXC boot script: register qemu-aarch64 in this container's OWN binfmt_misc instance, which is
    the one it may write. Exits early when the entry is already there, so a second run is a no-op."""
    register = _REGISTER.format(interpreter=INTERPRETER)
    return (
        "#!/bin/sh\n"
        f"# {SCRIPT}: register qemu-aarch64 in this container's own binfmt_misc (simplon si#358)\n"
        "set -eu\n"
        "mkdir -p /run/binfmt\n"
        "mountpoint -q /run/binfmt || mount -t binfmt_misc binfmt_misc /run/binfmt\n"
        "[ -e /run/binfmt/qemu-aarch64 ] && exit 0\n"
        f"printf '%s\\n' '{register}' > /run/binfmt/register\n"
    )


def unit() -> str:
    """The unit that runs the script at every boot, BEFORE docker, so the daemon's first builder sees it."""
    return (
        "[Unit]\n"
        "Description=Register qemu-aarch64 for linux/arm64 builds (simplon support ci-arm64)\n"
        "Before=docker.service\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "RemainAfterExit=yes\n"
        f"ExecStart={SCRIPT}\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _virt() -> str:
    """`systemd-detect-virt`'s answer, or '' when there is none. It exits 1 on bare metal while printing
    `none`, so the text is the answer and the exit code is not."""
    if shutil.which("systemd-detect-virt") is None:
        return ""
    return run(["systemd-detect-virt"]).out.strip()


def _runs_arm64() -> bool:
    """Whether builder `image.BUILDER` lists linux/arm64 (or a variant of it)."""
    found = image.builder_platforms(run(["docker", "buildx", "ls", "--format", "json"]).out)
    return found is not None and not image.missing_platforms((PLATFORM,), found)


def _fresh_builder() -> bool:
    """Drop the builder and create it again, so it sees an emulator registered after it was made."""
    log.info(f"`docker buildx rm {image.BUILDER}`: a builder made before the emulator does not see it")
    run(["docker", "buildx", "rm", image.BUILDER])
    return image.ensure_builder()


def _write_if_changed(path: Path, body: str, mode: int) -> None:
    if path.exists() and path.read_text() == body:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(mode)
    log.info(f"wrote {path}")


def _install_vm() -> bool:
    log.info(f"installing {PACKAGE}, which registers the emulators through systemd-binfmt at every boot")
    installed = run(["apt-get", "install", "-y", PACKAGE])
    if not installed.ok:
        log.error(f"`apt-get install -y {PACKAGE}` failed: "
                  f"{(installed.err or installed.out).strip() or '(it said nothing)'}")
        return False
    # The package's postinst registers them already; restarting is what makes a re-run register too.
    run(["systemctl", "restart", "systemd-binfmt"])
    return True


def _install_lxc() -> bool:
    if not INTERPRETER.exists():
        log.info(f"copying the static {INTERPRETER_INSIDE} out of {BINFMT_IMAGE} to {INTERPRETER}")
        created = run(["docker", "create", BINFMT_IMAGE])
        if not created.answered:
            log.error(f"`docker create {BINFMT_IMAGE}` failed, so there is no interpreter to register: "
                      f"{(created.err or created.out).strip() or '(it said nothing)'}")
            return False
        container = created.out.strip()
        INTERPRETER.parent.mkdir(parents=True, exist_ok=True)
        copied = run(["docker", "cp", f"{container}:{INTERPRETER_INSIDE}", str(INTERPRETER)])
        run(["docker", "rm", container])
        if not copied.ok:
            log.error(f"copying {INTERPRETER_INSIDE} out of {BINFMT_IMAGE} failed: "
                      f"{(copied.err or copied.out).strip() or '(it said nothing)'}")
            return False
    _write_if_changed(SCRIPT, script(), 0o755)
    _write_if_changed(UNIT_DIR / UNIT, unit(), 0o644)
    run(["systemctl", "daemon-reload"])
    # `--now` runs the script at once; enabling is what makes it survive the reboot.
    started = run(["systemctl", "enable", "--now", UNIT])
    if not started.ok:
        log.error(f"`systemctl enable --now {UNIT}` failed: "
                  f"{(started.err or started.out).strip() or '(it said nothing)'} - "
                  f"`systemctl status {UNIT}` says why")
        return False
    return True


def arm64(dry_run: bool = False) -> int:
    """Check that this host's builder runs linux/arm64, and register the emulator when it does not.
    Needs root to change anything; idempotent."""
    if not dry_run and os.getuid() != 0:
        log.die("registering an emulator needs root - it installs a package or a boot unit and changes "
                "the host kernel for every process on it. Run it once on the runner: "
                "sudo <product>.sh support ci-arm64 (or -n first, which needs no root)")
        return 1
    answer = _virt()
    kind = branch(answer)
    if not kind:
        log.die(f"`systemd-detect-virt` answered '{answer or '(nothing - is it installed?)'}', and this "
                f"command has a recipe only for a VM or bare metal ({PACKAGE}) and for an LXC container "
                f"(a boot-time binfmt_misc registration). NOTHING was changed")
        return 1
    log.info(f"`systemd-detect-virt` answered '{answer}', so this host takes the {kind} recipe")

    if dry_run:
        state = "already lists" if _runs_arm64() else "does not list (or does not exist yet)"
        log.info(f"builder '{image.BUILDER}' {state} {PLATFORM}")
        if kind == VM_BRANCH:
            log.info(f"would run, if it does not: apt-get install -y {PACKAGE}; systemctl restart "
                     f"systemd-binfmt; docker buildx rm {image.BUILDER}")
        else:
            log.info(f"would run, if it does not: copy {INTERPRETER_INSIDE} out of {BINFMT_IMAGE} to "
                     f"{INTERPRETER}; write {SCRIPT} and {UNIT_DIR / UNIT}; systemctl enable --now {UNIT}; "
                     f"docker buildx rm {image.BUILDER}")
        log.ok("dry run: nothing was changed")
        return 0

    if not image.ensure_builder():
        return 1
    if _runs_arm64():
        log.ok(f"already set up: builder '{image.BUILDER}' runs {PLATFORM}; nothing was installed")
        return 0
    if not _fresh_builder():
        return 1
    if _runs_arm64():
        log.ok(f"set up: the emulator was already registered, and builder '{image.BUILDER}' was made before "
               f"it; created again, it runs {PLATFORM}. Nothing was installed")
        return 0

    if not (_install_vm() if kind == VM_BRANCH else _install_lxc()):
        return 1
    if not _fresh_builder():
        return 1
    if _runs_arm64():
        log.ok(f"set up: builder '{image.BUILDER}' runs {PLATFORM}, and the {kind} recipe registers it again "
               f"at every boot")
        return 0
    log.error(f"the {kind} recipe ran and builder '{image.BUILDER}' still does not list {PLATFORM}. "
              f"`docker buildx ls` shows what it can run"
              + (f"; `cat /run/binfmt/qemu-aarch64` shows whether the registration took" if kind == LXC_BRANCH
                 else "; `ls /proc/sys/fs/binfmt_misc/` shows whether systemd-binfmt registered it"))
    return 1
