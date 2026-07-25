"""Pure Linux host-provisioning primitives: kernel-module loading, apt package availability and
binfmt_misc emulation capability. Product-agnostic MECHANISM extracted from netctl's orchestrator
(netctl#651 strand 2).

Every function is a pure text/argv transform with NO product knowledge, so the consuming product wires
them to its own host I/O (its Host / run seam) and keeps only its own module list + guard policy -
"gleiche Maschine, anderer Katalog". These are exactly the host primitives an IaaS/PaaS control plane
(infractl) needs as much as a network one (netctl): load a kernel module, decide whether an apt package
is really installable, tell whether a binfmt_misc handler can run under a container.

The headline is the netctl#95 `modprobe -a` bug: `modprobe wireguard mpls_router mpls_iptunnel` (no
`-a`) treats only the FIRST token as a module and the rest as its PARAMETERS, so it loads one module,
returns 0, and the install branch never runs - silently breaking a multi-module backbone. The argv
builders here ALWAYS pass `-a` and a unit test guards it.
"""
from __future__ import annotations

import re

# Ubuntu's kernel-module-extras package for the RUNNING kernel; a sensible default for
# load_or_install_snippet. `$(uname -r)` is expanded by the shell that runs the snippet, not here, so
# the string stays a literal template until it reaches the host.
MODULES_EXTRA_PKG = "linux-modules-extra-$(uname -r)"


def modprobe_argv(modules: list[str]) -> list[str]:
    """The modprobe argv to load SEVERAL modules. ALWAYS `-a`: without it modprobe reads only the first
    token as a module and the rest as its parameters (the netctl#95 bug), loading one module and
    returning 0. Raises ValueError on an empty list (modprobe needs at least one module)."""
    if not modules:
        raise ValueError("modprobe needs at least one module")
    return ["modprobe", "-a", *modules]


def load_or_install_snippet(modules: list[str], pkg: str = MODULES_EXTRA_PKG) -> str:
    """The shell one-liner that loads the modules, and on failure installs `pkg` (which provides them)
    and loads again. Both modprobe invocations use `-a` (the netctl#95 fix). The default `pkg` is the
    running kernel's linux-modules-extra; a product overrides it for a different distro/package."""
    mods = " ".join(modules)
    return (f'modprobe -a {mods} 2>/dev/null || '
            f'{{ apt-get install -y "{pkg}"; modprobe -a {mods}; }}')


# `apt-cache policy` prints "Candidate: <version>" - or "Candidate: (none)" when the index is empty
# (a freshly restarted VM, or a host VPN hijacking the resolver). A REAL candidate starts with a digit.
_CANDIDATE = re.compile(r"Candidate:\s*[0-9]")


def apt_candidate_present(policy_text: str) -> bool:
    """True iff `apt-cache policy` reports a real (numeric) candidate version - i.e. the package is
    actually installable, not merely the mirror reachable. False for "Candidate: (none)" on an empty
    index. Lets a caller WAIT for the apt index to populate before it tries the install."""
    return _CANDIDATE.search(policy_text) is not None


# A binfmt_misc handler entry has a `flags:` line; an F flag (e.g. `flags: OCF` for Rosetta, or `F` for
# qemu) means the interpreter is loaded fix-binary into memory and therefore usable from inside a
# container - what a foreign-arch (x86-under-emulation) container needs.
_FLAGS_F = re.compile(r"^flags:.*F", re.MULTILINE)


def has_f_flag(binfmt_entry_text: str) -> bool:
    """True iff a binfmt_misc handler entry carries an F (fix-binary / container-capable) flag, so a
    foreign-architecture container can execute under the emulator. Pure - the /proc/sys/fs/binfmt_misc
    read stays in the caller."""
    return _FLAGS_F.search(binfmt_entry_text) is not None
