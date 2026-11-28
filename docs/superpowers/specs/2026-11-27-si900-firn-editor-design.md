# si#900: `support install` provisions the firn editor

Status: design, decided by Marco on 2026-11-27 (choice lists in the session that wrote this file). Milestone M1,
lane L4. Reported by cleon-firn (2026-11-25). Refs si#549, firn#197, firn#1437 (closed: the `.vsix` is
attached since firn v0.19.0).

## 1. Intent

A product that declares `toolchains: [firn]` gets firn's image for `test model` and `build model`, and nothing
to edit its projects with. Wiring firn's VS Code extension, its binary and a workspace by hand is host tooling,
which is what `support install` provisions for the other toolchains (brew, gh, oras, the claude plugins). It
needs no product knowledge beyond what the manifest already pins, so it belongs in the kernel. A product
consumes firn's published artefacts and builds none of them.

Done looks like this: in such a product, `support install`, then `code <product>.code-workspace`, and every
project opens with the language server answering.

## 2. Goals, non-goals, anti-goals

Goals:

- With `firn` declared, `support install` installs the extension at the pinned version, provides a language
  server runtime (a local binary or the image), and writes `<product>.code-workspace`.
- Both runtimes now (Marco 2026-11-27): `local` and `docker`.
- A second run with nothing changed reports nothing to do.

Non-goals:

- Projects with Java functions (Marco 2026-11-27). The kernel does not point the editor at a project's own
  binary. That is asked of firn (4.6); until firn answers it, `support install` names the affected projects.
- macOS and Windows binaries (firn#1133, firn#1134). Where firn ships no binary for the host, the default is
  `docker`.
- A kernel command that starts or stops a language server container (`support firn-lsp up|down`): not needed,
  see 4.3.

Anti-goals (a failure even if it works):

- A docker runtime that mounts the tree anywhere but at its host path. Measured (5): with the tree at
  `/workspace` the server answers every request with nothing, without an error. A workspace that opens green
  and shows no diagnostics is the recurring defect.
- An editor gate that cannot tell "nothing to do" from "no editor here" or "the asset is not published".
- A binary or `.vsix` used without its `.sha256` checked.
- A runtime switched silently: every run names the runtime it used and where that choice came from.

## 3. Constraints

- The version is the one the manifest pins: the tag of the `firn` image its model commands run. firn
  publishes `firn-<tag>.vsix`, `firn-<tag>-linux-amd64` and `firn-<tag>-linux-arm64`, each with a `.sha256`,
  only from v0.19.0 on (v0.17.0 and v0.18.0 carry binaries only, v0.11.0 nothing). A pin without the asset
  fails that gate, naming the tag and the asset. simplon itself pins v0.11.0 today, so its own run is red on
  this gate until simplon bumps its firn pin; that is the honest answer, not a defect.
- `support install` runs every gate even when an earlier one failed, and on the container route or in CI a
  host gate reports SKIPPED, not a failure (si#710, `hostinstall.container_route`).
- firn's repository is private (measured 2026-11-27: the release API answers 404 without a token; the image
  pulls anonymously). Every release read (asset list, `.vsix`, binary, `.sha256`) needs a GitHub token, and
  every developer of a consuming product needs read access to firn.
- Downloaded binaries go to the host tool directory the kernel already uses (`tools_bin()`, as for oras). It
  lives under the product root and `clean` wipes it (my call, accepted): after `clean` the editor's `local`
  server is gone until `support install` runs again, and the docker script, kept there too, likewise.
- Generated files are not hand-edited and are rewritten on each run.

## 4. The design

### 4.1 The gates

`support install` gains, with `firn` declared, three gates after the existing ones, each reported in its own
words like the brew and gh gates (`hostinstall.Outcome`):

1. **Extension.** Download `firn-<tag>.vsix` and its `.sha256` from firn's GitHub Release, check it, install
   with `code --install-extension`. `zwyssig.firn` already at the pinned version (`code --list-extensions
   --show-versions`): nothing to do. No `code` on PATH: the gate fails and says so.
2. **Runtime.** `local` or `docker` (4.2, 4.3).
3. **Workspace.** Write `<product>.code-workspace` (4.4).

### 4.1a Reading firn's release

Marco 2026-11-27: the token comes the way package operations get theirs (`githubpackages.token()`: the
environment first, then `gh auth token`). The gate keeps the three outcomes apart, because GitHub answers 404
to more than one of them:

- no token: red, naming how to get one;
- the release cannot be read with the token (no access, or no such tag, or offline): red, naming the tag
  and saying the release could not be read, never "not published";
- the release reads but lacks the asset: red, naming the tag and the asset.

When the release cannot be read, 4.2 has no default: the runtime gate is red with that reason, never a
silent `docker`.

### 4.2 Runtime choice, remembered per host

A parameter of `support install`, `--firn-runtime local|docker` (name is the builder's to settle with the
catalogue's conventions). Marco 2026-11-27: the choice is remembered per host.

- Stored in a file under the user's config directory (XDG) that holds only this value: one value for the
  host, not one per product (my call: the choice is about the machine; a value stored from product A is
  used in product B and named as "stored"). A flag overrides it and
  stores the new value.
- Without a flag or a stored value, the default: `local` when firn's release carries a binary for this host's
  OS and architecture (read from the release's assets, not from a list typed into the kernel), `docker`
  otherwise.
- Every run names the runtime and its source: flag, stored, or default (and why that default).
- An unreadable or invalid stored value is a diagnosis naming the file, not a silent fall back to the
  default.

### 4.2a Container route and CI

On the container route and in CI all three gates report SKIPPED with the reason (my call): there is no editor
there, and the workspace and the docker script embed the tree's host path, which a kernel inside the
launcher's container (tree at `/src`) cannot know without reintroducing the wrong-path defect of 5.

### 4.3 The two runtimes

- **`local`:** download `firn-<tag>-<os>-<arch>` and its `.sha256` into the host tool directory. Present at
  that version: nothing to do. The workspace sets `firn.mode = stdio` and `firn.binary` to its path.
- **`docker`:** the editor starts the container itself, over stdio (Marco 2026-11-27). `support install`
  writes a small git-ignored script that runs
  `docker run -i --rm -u <caller uid:gid> -v <tree>:<tree> -w <tree> <pinned firn image> "$@"`, and the
  workspace sets `firn.mode = stdio` and `firn.binary` to the script. The extension appends `lsp`. The
  container lives exactly as long as the editor's server process; no up/down, no port. The gate fails when
  docker cannot run here. A rerun rewrites the script when the pin changed.

  Rejected: tcp with a kernel `up|down` command. Measured (5): `firn lsp --port` serves one client and exits,
  so a reloaded window finds no server. Reopens if firn's server stays up across clients and a reason appears
  to share one container between windows.

  Rejected: the script calling the launcher (`./simplon.sh toolchain run ... lsp`). It would need
  `toolchain:run` to pass stdin through and to mount at the host path, and the launcher's stdout to stay
  clean for LSP; every editor start would pay the launcher's start. Cost accepted instead: a second place
  that spells a `docker run` beside `toolchain:run`, without its mirror logic. Reopens if a host needs a
  registry mirror to pull the firn image.

### 4.4 The workspace

`<product>.code-workspace` at the product root: one folder per project in `firn-workspace.toml` (firn docs/05
section 7), and the settings of 4.3 for the runtime used. Written on every run. When the file is not
git-ignored, the gate fails and names the line to add.

### 4.5 Projects with Java functions

Measured (5): stock firn on such a project reports false errors (cleon-firn's arc42: `firn validate` rc 1,
`E181 ... reaches only Java functions the running binary does not hold`), and the extension reads one
`firn.argumentFile` per window (the first folder that sets it), so one window over all projects cannot give
each its own binary. cleon-firn: 18 of 53 projects carry Java sources.

Marco 2026-11-27: the kernel writes the workspace with the stock runtime and `support install` names the
projects whose own binary the editor does not use, with the reason. How a project is recognised as one is the
builder's (6); "could not tell" must not read as "none".

### 4.6 Asked of firn

Filed on firn 2026-11-28 (firn#1460, firn#1461, firn#1462), each with the measurement of 5:

- The server loads each project's Java functions itself (from `firn.toml` or the project's
  `build/firn/lsp.args`), so one window serves every project. When it lands, the naming of 4.5 goes.
- The extension's `firn.mode` text says a container cannot share the editor's stdio; `docker run -i` does.
- A server whose documents lie outside what it can read (the `/workspace` mount) answers empty instead of
  saying so.

## 5. Measurements (2026-11-27, firn v0.19.0)

Spike in the scratchpad against a copy of simplon's firn project, image `ghcr.io/marcozwyssig/firn:v0.19.0`
(entrypoint `/firn`, default command `lsp --port 7654 --bind 0.0.0.0`, workdir `/workspace`, user 65532):

| Route | Result |
|---|---|
| stdio, `docker run -i`, tree at its host path | diagnostics with host URIs (5 on a broken file), 5 symbols on a valid file |
| stdio, tree at `/workspace` | 0 diagnostics on the broken file, 0 symbols on the valid one, no error |
| tcp, `-p 127.0.0.1:7654`, tree at its host path | answers like stdio; the container exits after the client leaves |

The `.vsix` checks against its `.sha256`; its `package.json` names `zwyssig.firn` 0.19.0 and the settings
`firn.mode`, `firn.binary`, `firn.argumentFile`, `firn.host`, `firn.port`. Reachable manifests: only
cleon-firn has a `firn-workspace.toml` (53 projects); simplon and firn declare firn without one.

## 6. Left to the builder

- What the workspace holds for a product with `firn` declared and no `firn-workspace.toml` (simplon): the
  model commands' project folder, or a gate that says there is nothing to open.
- How a project with Java functions is recognised for 4.5's naming.
- Which command's image tag is the pin when a manifest names several firn images (a diagnosis when they
  disagree is fine).
- Where the docker script lives (git-ignored, not `build/firn/firn`, which is a project's own binary).
- Census entries and `with-what/rules.md` for every new refusal.

## 7. Acceptance

- On a Linux host with `code` on PATH, in cleon-firn: `support install` installs extension and binary at the
  pinned version and writes the workspace; a second run reports nothing to do; `code cleon-firn.code-workspace`
  opens every project with the language server answering.
- The docker route, measured on a host without a firn binary (or with `--firn-runtime docker`): the same
  workspace answers through the image.
- Seen red first: no `code` on PATH; no GitHub token; a token without access to firn (reported as "could not
  read the release", not "not published"); a pin whose release has no `.vsix`; a `.sha256` that does not match; a
  workspace file that is not git-ignored.
- The run names the runtime and its source, and the projects whose own binary is not used.
