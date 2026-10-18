# si#511: `toolchain:run` bind-mounts a tree path, and one public mount helper (with si#495)

Measured on main 1b0bfb0 (si#511 comment 6250857065). Marco decided on 2026-10-18 (si#511 comment).

## Intent

npm fetches platform-optional packages only for its own host. So biz-cockpit's `src/frontend/node_modules`
carries the macOS host's bindings, and the gate in `node:24-alpine` (musl) cannot go green. The fix is one
bind mount: a tree-local directory over the block's `node_modules`. The kernel has no way to say that, so
biz-cockpit splices `-v` into the argv `toolchain.docker_argv` returns, before the image
(biz-cockpit `orchestrator/cli.py:270-273`). It also creates both directories by hand, because docker
would create them root-owned. Every product meeting this case would reinvent the splice.

firn has the neighbouring problem (si#495): `test:image`'s `_mount_argv` is private, so firn keeps a copy
of it that adds `:ro` (`imagelsp.py:302`). One public helper ends both.

## Goals

- **A `mounts` field on `Toolchain`** (`tasks/toolchain.py`), with an empty default. biz-cockpit builds
  `Toolchain(...)` and calls `docker_argv(...)` positionally (cli.py:192-193), so nothing it passes today
  may change meaning. The field holds `Mount` values (source, target, readonly), frozen like `Cache`.
- **A `mounts:` key on `toolchain:run`**, bound like every other key: a `run_toolchain` parameter, passed
  through `invocation` to `declared`, and documented in the catalogue's `toolchain:run` `params:`. Each
  entry is the string `<source>:<target>` or `<source>:<target>:ro`:
  - `source` is a plain relative path under the product root, refused when it is absolute or climbs
    (`layout.validate_relative_dir`, the rule `_inside_the_product` already uses). `build/...` reaches the
    output directory, because `output:` is validated to sit inside the tree. There is no `{output}`
    substitution (measured: none exists anywhere), and none is added.
  - `target` is an absolute container path. It may not be the tree mount's `workdir` or an ancestor of it,
    because that would mount over the tree *(my call)*. A source of `.` is allowed (`.:/src:ro`).
  - Any other suffix after `:` is refused.
- **The calling process creates every mount's source and target before the run, as the calling user.**
  Measured with docker 29.9.1 and `--user 4242:4242`: `-v` with a missing source makes the daemon create
  it `root:root 755`, and the container's write then fails with `Permission denied`. A missing target
  nested inside the tree mount is created on the host `root:root 755` too. So in `invocation`, beside
  `outputs.ensure_home()`, the kernel:
  - creates `<root>/<source>` (`mkdir(parents=True, exist_ok=True)`);
  - creates the host counterpart of `target` when `target` lies under the tree mount's `workdir`
    (`/work/src/frontend/node_modules` → `<root>/src/frontend/node_modules`). A target outside the
    workdir has no host counterpart and gets nothing.
  **Ownership is checked shallowly, before creation** *(my call)*. `docker.ownership_fault` walks every
  entry under a top, which over a Linux `node_modules` means tens of thousands of stat calls before every
  run, and its message calls the tree a build output, which a mount source need not be. So the source,
  the target's host counterpart and, when either is missing, its nearest existing ancestor must be owned
  by the calling uid. Otherwise the run is refused before any `mkdir`, with a mount-specific message that
  names the path, its owner and the way out (`sudo chown -R`, or remove it). A `PermissionError` from
  `mkdir` must therefore never surface as a traceback. The output directory's existing deep walk stays as
  it is.
- **The argv order:** mount flags come after the cache volumes and before `HOME`. Like every other flag
  they sit before the image. An empty `mounts` changes the line by not one byte. That is the property
  biz-cockpit's own unit test checks, and the kernel's test must check it too.
- **One public helper, `adapters.hostpath.mount_argv`** *(my call on the home: `hostpath` is LIBRARY,
  and it already owns the one rule every bind mount must keep, the si#201 translation)*. It takes the
  product root, the source, the target, `readonly` and `must_exist`, and returns `["-v", "<translated
  source>:<target>[:ro]"]`. It creates nothing, so `docker_argv` stays pure. Called with
  `must_exist=True`, it refuses a missing source (`test:image`'s current behaviour). `toolchain:run`
  calls it with `must_exist=False`, because `invocation` has already created the mount points (si#511's
  behaviour; *revised while planning: an earlier draft had the helper create them, which would have
  made the pure `docker_argv` write to disk*). The difference is
  explicit at the call site, as decided. *(My calls, from the builder check:)*
  - **It raises `ValueError`**, never logs and never exits. It is a public library function. Each caller
    turns the refusal into its own voice: `test:image` into `log.error` plus `None` as today, and
    `toolchain:run` into `log.die`.
  - **Callers validate in their own words first.** `test:image` keeps `_inside_the_product` (which allows
    `.`) and its messages unchanged. `toolchain:run` uses `layout.validate_relative_dir`, with `.`
    allowed as the root, as `_inside_the_product` does. The helper repeats only the safety floor: a
    source that is absolute or climbs, and a target that is not absolute. That is so firn, calling it
    directly, cannot mount outside the tree.
  - **The surface census needs no change.** `adapters.hostpath` is already LIBRARY, which promises the
    whole module. The docstring states the contract: arguments, the `ValueError`, the si#201
    translation and `must_exist`.
- **Refused at run time, like `caches:`** (decision 3). A malformed entry, a source outside the tree, a
  non-absolute target or an unknown suffix is a `log.die` when `with:` is bound, naming the command, the
  entry and the way out. These refusals are diagnoses, and they are not in the census population, which
  counts only load-time `ValueError`s on the walked seams. Say so in the PR rather than leave it implied.

## Non-goals

- Changing `caches:`. The measurement shows no manifest uses it, because a named volume is root-owned
  (#278/si#319). A tree-local mount is the working alternative, and the docs may say so. Fixing `caches:`
  is a separate ticket if anyone wants it.
- `--mount type=bind`. The kernel uses `-v` everywhere (`test_hostpath_mounts.py` holds the `hostpath`
  rule over every `-v`), and the creation step makes the difference moot.
- Changing biz-cockpit. It deletes its splice itself once the release ships, and reports the cost.

## Anti-goals

- A mount source outside the product tree, whether absolute or climbing.
- A root-owned directory left in the product tree by any run that declares a mount.
- An untranslated source on the container route (si#201: rc 0 over an empty directory).

## Tests

- `docker_argv` with no mounts is byte-identical to today's line. With mounts, each `-v` sits after the
  cache volumes and before the image, the source is translated, and `:ro` is kept.
- `declared` refuses each bad entry (no `:`, a relative target, an absolute or climbing source, an unknown
  suffix), naming the command. Pin each message against the real text.
- `invocation` creates the source and the in-workdir target as the calling user before the run. A target
  outside the workdir creates nothing on the host. Real directories in a tmp_path, no mocks of `mkdir`.
- A real docker run as a non-root uid writes into the mounted target, and afterwards the tree holds no
  root-owned directory. This is the anti-goal measured, in the e2e tier the toolchain tests already use.
- `mount_argv(must_exist=True)` refuses a missing source with `test:image`'s current message, and
  `test:image`'s existing mount tests pass unchanged.
- A root-owned source, target or missing-path ancestor is refused before any `mkdir`, with the mount
  message and no traceback (a real chown in a tmp_path, or skip with a stated reason when not root).
- A target equal to `workdir`, or an ancestor of it, is refused.

## Docs

- `with-what/phases.md` § toolchain: the key, the creation rule and why it exists. `mounts:` is the
  working alternative to `caches:` for a non-root uid.
- `how/manifest.md` near `workdir`/`build_root` (line 1266).
- The catalogue's `toolchain:run` `params:` help.
- The release notes name si#511 and si#495. After the release: tell biz-cockpit (si#511) and firn
  (si#495, it can drop its copy).

## Acceptance

- biz-cockpit's case can be written as a manifest `mounts:` entry, or as `Toolchain(mounts=...)` from
  Python, with no splice.
- firn can call `mount_argv` instead of its copy.
