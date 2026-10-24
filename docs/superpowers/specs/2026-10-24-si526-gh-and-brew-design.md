# si#526: `support install` provisions gh and Homebrew as host toolchains

Ticket: si#526 (Marco, 2026-10-23). The Homebrew half was added by Marco on 2026-10-24: "Homebrew auch als
Toolchain vorsehen". It is the host tool here, not the si#449 tap.

## Intent

`support install` is the deliberate, up-front setup of a developer machine. Today it provisions only oras
and the `claude` plugins. On a fresh host it reports green, and then the first `release asset`,
`vcs auth-scopes` or GitHub issue command fails on a missing `gh`, or `vcs prune-branches` quietly does
less (`gitops.py:219`). A product that declares `gh` in `toolchains:` should get gh from `support install`,
or be told exactly why not. A product that declares `brew` should get Homebrew, and the other gates then
install through it.

## Decided by Marco

1. **gh is installed through the platform's package manager, with sudo where the platform needs it**
   (2026-10-24, "Paketmanager mit sudo"). gh is installed system-wide, so every later process finds it on
   PATH and the gh call sites stay as they are.
2. **`brew` is a host toolchain** like `gh` and `claude` (2026-10-24, "Host-Toolchain brew"). With `brew`
   in `toolchains:`, `support install` provisions Homebrew itself, and the gh and oras gates use it as
   their install route.
3. From si#525: a host toolchain is switched on by its name in `toolchains:`, and absent means OFF,
   which is silent.

## Measured (2026-10-24, Debian 13 host, root, gh 2.103.0)

- **This host's gh came from the official apt repo** (`/etc/apt/sources.list.d/github-cli.list`, `dpkg -S`
  says `gh`). That is exactly the route below.
- **The keyring is pinnable.** `/etc/apt/keyrings/githubcli-archive-keyring.gpg` has sha256
  `6084d5d7bd8e288441e0e94fc6275570895da18e6751f70f057485dc2d1a811b`, the value cli/cli's
  `docs/install_linux.md` publishes.
- **The official Debian steps:**
  - write the keyring to `/etc/apt/keyrings` with `go+r`;
  - write the line `deb [arch=<dpkg --print-architecture> signed-by=...] https://cli.github.com/packages stable main`
    to `/etc/apt/sources.list.d/github-cli.list`;
  - run `apt update`, then `apt install gh -y`.
  All of this runs under sudo.
- **RPM differs between DNF4 and DNF5** (`config-manager --add-repo` against `addrepo --from-repofile`).
- **Homebrew's `install.sh` (HEAD, 1243 lines):**
  - It aborts on Windows ("only supported on macOS and Linux").
  - It aborts on Intel macOS ("only supported on Apple Silicon").
  - It aborts as root on a plain host ("Don't run this as root!"), except inside a container or CI
    (`/.dockerenv`, `/run/.containerenv`, a CI cgroup).
  - It installs to the prefix `/opt/homebrew` (macOS) or `/home/linuxbrew/.linuxbrew` (Linux).
  - With `NONINTERACTIVE=1` and no passwordless sudo, it aborts.
  - Afterwards `brew` is **not on PATH** until the shell evaluates `brew shellenv`.
- **`support install` is not a pipeline**, so no TUI is in the way. A sudo password prompt reaches the
  terminal, as long as the command runs uncaptured.
- `claudeplugins._skip_reason` already says why a host step does nothing: in the container route, and
  with `CI=true` or `GITHUB_ACTIONS=true`.

## Behaviour

**Gate order:** `brew`, oras, `gh`, then the `claude` plugins. Homebrew comes first so that the gates
after it can install through it. oras is unchanged: it already prefers brew when brew is on PATH.

### Outcomes

Each gate reports exactly one outcome, and no two of them look alike:

| Outcome | When | rc |
|---|---|---|
| OFF | the name is not in `toolchains:`; silent | 0 |
| PRESENT | already there, verified by running `--version` | 0 |
| INSTALLED | it was missing, it was installed, and `--version` now runs | 0 |
| SKIPPED | this machine is not one to provision: the container route, CI, or a platform the tool does not support (Homebrew on Windows or on Intel macOS); the reason is stated | 0 |
| NO_ROUTE | the tool is declared and missing, and this machine offers no way to install it; the reason and the manual install link are stated | 1 |
| FAILED | an install command failed or timed out, or the tool still does not run afterwards; the detail is stated | 1 |

`support install` still attempts every gate and exits 1 if any gate ended in NO_ROUTE or FAILED.

### gh

The first route that applies is taken:

1. **brew is on PATH:** `brew install gh`.
2. **Windows:** `winget install --id GitHub.cli -e --source winget --accept-package-agreements
   --accept-source-agreements`.
3. **Debian family** (`apt-get` and `dpkg` present): the official steps above. The kernel downloads the
   keyring itself and checks its sha256 against the pinned value before installing it. A mismatch is
   FAILED, and nothing is written.
4. **Anything else:** NO_ROUTE, with the link `https://github.com/cli/cli#installation`.

How privileged commands run:
- **As root:** directly.
- **Otherwise:** prefixed with `sudo`, uncaptured, so the password prompt reaches the person.
- **No sudo on PATH:** NO_ROUTE.

Every install command has a time limit of 600 s. A timeout is FAILED.

### brew

- **PRESENT:** `brew` is on PATH. Or it sits at the platform's default prefix but is off PATH: then the
  gate prepends the prefix's `bin` to this process' PATH and prints the `brew shellenv` line to add to
  the shell profile. The gate never edits a dotfile.
- **SKIPPED:** on Windows and on Intel macOS, with the reason. A Windows developer in a product that
  declares `brew` for its Mac and Linux developers must not get a red setup.
- **NO_ROUTE:** as root on a plain host, with Homebrew's own reason.
- **Install:** download `install.sh` from a **pinned commit** of Homebrew/install, never from HEAD, and
  run it with bash.
  - On a terminal, it runs interactively, so its RETURN and sudo prompts reach the person.
  - Without a terminal, it runs with `NONINTERACTIVE=1`.
  - Then the gate prepends the prefix's `bin` to PATH, verifies `brew --version`, and prints the
    shellenv line.

### Other changes

- `profiles.HOST_TOOLCHAINS` gains `"brew": "Homebrew"`. This adds no refusal and no new key.
- `claudeplugins.BASE_REQUIRES` gains `github@claude-plugins-official -> ("gh",)`. The plugin step then
  names a missing gh the way it names a missing node (the ticket's optional point).
- The starter manifest is unchanged: it already declares `claude` and `gh`, and `brew` stays opt-in.

## Calls I made (Claude), each with the trigger that reopens it

- **No dnf, zypper or pacman route.** Those hosts get NO_ROUTE with the link. Reopen when a developer of a
  reachable product works on one.
- **On Debian, no Homebrew fallback when apt fails.** Each route is attempted once, and the first one that
  applies decides. Reopen if a measured case shows that apt is unusable where brew works.
- **Windows: gh being found right after winget is unmeasured.** winget's PATH change reaches new shells,
  not this process. If `gh --version` does not run afterwards, the outcome is INSTALLED with "open a new
  shell", not FAILED. This is to be measured on a Windows host before it is claimed.
- **Real-instance tests:** the apt route is measured in a `debian:trixie` container, as root and as a
  sudo user. The Homebrew install is measured in a container (root is allowed there). The unit tests use
  fake `brew`, `winget`, `apt-get` and `sudo` executables on PATH, and their limits are written down in
  the test module.

## Non-goals

- Tokens and scopes stay with `vcs auth-scopes`.
- si#449's tap publishing.
- Upgrading a gh or brew that is already present.
- CI, which sets up gh through its runners.
