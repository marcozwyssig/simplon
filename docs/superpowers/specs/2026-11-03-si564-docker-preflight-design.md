# si#564: `support:docker-preflight` - docker found from the active context, no sudo symlink

Ticket: si#564, with its first comment (6616696004, the Dev Containers extension read from its code).
Decided by Marco on 2026-11-03, by choice list, against main 82b608d.

## Intent

On a Mac with Colima, firn's own `docker-preflight` (`firn.yaml`, `orchestrator.preflight:check`, from
firn#287) stops `deploy devcontainer` because `/var/run/docker.sock` does not exist, although docker
answers on the active context and the preflight names it. The only way out it offers is
`sudo ln -sf <colima socket> /var/run/docker.sock`. That symlink lives in `/private/var/run`, which macOS
clears at boot (not measured on the affected host), so the stop is expected back after every restart.

Marco uses both ways in: `./firn.sh dev deploy up` in a terminal, and VS Code's "Reopen in Container".
The two need different answers, and the preflight mixes them:

1. **Does docker answer?** That is a kernel question with no product knowledge in it. The kernel answers
   it twice today (`adapters/host.py:docker_socket_path`, `adapters/docker.py:_socket_path`), and
   neither asks the docker context.
2. **Will the Dev Containers extension find docker?** That question exists only on the editor path.
   The extension asks it before `initializeCommand`, so no product command can speak there.

## What the extension really does (measured from its code)

Read from `ms-vscode-remote.remote-containers` 0.471.0 (`dist/extension/extension.js`), not run on a
Mac. Details are in si#564's first comment.

- "Check Docker is running" runs `docker version` through the CLI and opens no socket.
- It picks the context in this order: the settings `containers.environment.DOCKER_CONTEXT`,
  `docker.environment.DOCKER_CONTEXT` and `docker.context`, then the env `DOCKER_CONTEXT`, then
  `docker context ls` (`Current`). A `context ls` that throws becomes `"default"`, which is firn#287's
  `Context: default`.
- `dev.containers.dockerSocketPath` is read only for the bootstrap container of a volume clone. **It is
  not a way out for this check**, although an earlier draft of this design said it was.
- `"docker.context": "<name>"` in the VS Code user settings is read before `context ls` is tried. It
  survives a reboot and carries no path and no user name.
- `"docker.host"` (with `docker.certPath`, `docker.tlsVerify`) is read too, but only on the branch where
  the context resolved to `default`: it then becomes the CLI's `DOCKER_HOST`. Checked in the bundle after
  the builder check asked.
- The extension's environment is VS Code's, not the terminal's. Started from the Dock, VS Code inherits
  no shell export, so a `DOCKER_HOST` or `DOCKER_CONTEXT` set in `~/.zshrc` is invisible to it. Measured
  by the builder check on the CLI side: with `DOCKER_HOST` set, `docker context show` says `default` and
  `inspect` names the `DOCKER_HOST` endpoint.

## Decisions (Marco, 2026-11-03)

1. **The kernel ships the task**: `support:docker-preflight`. firn deletes its own task and Python body
   at the bump that brings it, and names the coordinate instead. **Under `support`** (si#34: a `support:`
   coordinate is a placement): firn's command moves from `deploy preflight` to `support docker-preflight`,
   and `deploy devcontainer` keeps it in its `depends_on`, which resolves an unambiguous name across
   groups (`manifest/load.py` `plan_for`). Marco chose this over a family namespace after the builder
   check, knowing the command word changes for firn. The firn ticket is opened when a simplon
   release carries the task, not before.
2. **The editor part is a parameter**: `with: { editor: devcontainer }`. Without it the task checks
   only that docker answers. No new manifest key, and no inference from `.devcontainer/`.
3. **Green with a warning** when docker answers but the editor would not find it. A missing
   `/var/run/docker.sock` is never red by itself.
4. **Say, never write.** The task runs no `sudo` and writes nothing into the editor's configuration. With
   `editor: devcontainer` it names the one setting to add: `"docker.context": "<active context>"`.
5. **One resolver in the kernel, used by all three places** that resolve a socket today (the
   preflight, the lab probe with `labhost`, and the docker bootstrap). It tries `DOCKER_HOST` first,
   then the active context (`docker context inspect`), then the old fallbacks. A context docker cannot be
   asked about is "could not ask", never "default". Marco chose all three after the builder check named
   the two risks, so each caller gets the guard written below.
6. **The editor part checks what VS Code sees**, not what the terminal sees. It asks docker with
   `DOCKER_HOST` and `DOCKER_CONTEXT` removed from the environment, and warns when the terminal's
   environment says otherwise.

## The resolver

`simplon/adapters/host.py` holds it, because that module already answers "is this host's docker
usable" and owns the Colima socket path (`labhost.py` also knows Colima, as the VM it starts; the
builder check corrected "the only one").

- **`context_endpoint() -> str | None`** (I/O). It returns the endpoint of the context the docker CLI
  would use, from `docker context inspect --format '{{.Endpoints.docker.Host}}'`. It also returns the
  context's name, from `docker context show`, or from both in one `inspect` format, the builder's choice.
  `None` means docker could not be asked: no CLI, a non-zero exit, or empty output. That is not the
  same as "default". The resolver honours `DOCKER_HOST` and `DOCKER_CONTEXT` as the CLI does, by
  asking the CLI rather than reading `~/.docker/config.json`.
- **`docker_socket_path(*, darwin, environ=None, endpoint=None) -> str`** stays pure, and the endpoint
  is injected. The order is:
  1. a `unix://` `DOCKER_HOST`;
  2. the injected `unix://` endpoint;
  3. the Colima profile socket on macOS;
  4. `/var/run/docker.sock`.

  A non-unix `DOCKER_HOST` or endpoint (tcp, ssh) stays `""`: nothing local to open.
- **`context_endpoint(environ=None)`** takes the environment it runs docker in, so the editor check can
  pass one without `DOCKER_HOST`/`DOCKER_CONTEXT` (decision 6).
- **`docker._socket_path()`** delegates to it, so there is one resolution. Its `None` for non-unix
  stays as it is. **Guard:** `_grant_socket_access` runs `setfacl`/`chmod 666` under sudo on that path.
  It may act only on a path that is the system daemon's socket (`/var/run/docker.sock`, or a `unix://`
  `DOCKER_HOST` the operator set explicitly); a socket named only by the active context (a rootless or
  forwarded one, under a user's home or runtime dir) is never chmod'ed, and the die message names it
  instead. The `_socket_state` diagnosis uses the full resolution, so it names the socket that is
  actually missing.
- **The lab probe (`Host.probe`) and `labhost`.** **Guard:** on macOS they take the context's endpoint
  only when it is a Colima profile socket (`~/.colima/<profile>/docker.sock`); any other endpoint (the
  `default` context, Docker Desktop, a remote daemon) is ignored and the Colima socket is pinged as
  today. Otherwise a missing symlink would read as `UNREACHABLE`, and another daemon answering would make
  a dead Colima read as `SOCKET_ONLY` and skip `colima start` (builder check, `host.py:161-176`,
  `labhost.py:290`). An endpoint naming a different Colima profile is the improvement: today only
  `COLIMA_PROFILE` or `default` is tried. On Linux the probe takes the endpoint as the preflight does.
  When the endpoint is `None` the old order holds; the ping is the verdict there. The probe's
  netctl#1031 classification (ROUTED / SOCKET_ONLY / UNREACHABLE) does not change. The extra host-side
  `docker context inspect` runs only on the socket branch, i.e. when the routed `docker ps` already
  failed, so a healthy probe still costs one docker call.

## `support:docker-preflight`

A body in `src/simplon/tasks/` over the resolver; returns 0 or 1. `unattended: true`. Offered, not placed:
a product without docker or without an editor path has no use for it in its CLI. One param:
`editor`, a plain string. `devcontainer` turns the editor check on, and absent means no editor check.
Any other value is refused at run time with the values it knows. That is a diagnosis, raised by the
body, and it adds no load-time manifest feature and no census entry (decided after the builder check:
the param machinery has no choice type, and adding one is not this ticket).

| # | Check | Outcome | Says |
|---|---|---|---|
| 1 | `docker` on PATH | red if missing | install docker, or Colima on macOS |
| 2 | `docker version` answers | red if not | the CLI's own error lines, then how to start the daemon and "check `docker context ls`" |
| 3 | context | `context_endpoint()` is `None` | warning, not red: docker answered (check 2), so the daemon is fine; the context could not be named, so the editor advice below cannot be given |
|   |  | otherwise | log the context name and endpoint docker answers on |
| 4 | editor (only with `editor: devcontainer`, not on Windows); resolved again with `DOCKER_HOST`/`DOCKER_CONTEXT` removed (decision 6) | the terminal's environment sets either | warning: VS Code started from the Dock does not see it; the rows below say what it does see |
|   |  | the context is `default` and its socket exists | ok: the extension's fallback lands on a working daemon |
|   |  | the context is not `default` | warning: the extension may fall back to `default` (it does when `docker context ls` fails, firn#287); add `"docker.context": "<name>"` to the VS Code user settings, which it reads first |
|   |  | the context is `default` and its socket does not exist | warning: name `"docker.context": "<a context whose daemon answers>"` when one exists (the one the terminal used); otherwise `"docker.host": "unix://<socket>"` when a local socket answers; otherwise say no daemon is reachable the way VS Code looks |

Notes:

- **Check 4 warns although the extension may well find docker.** Whether `context ls` fails on a given
  machine is not knowable from outside the extension. The setting costs one line, and the warning is the
  only voice firn has before the editor's own check. The builder may make the warning quieter when the
  user settings already carry `docker.context` (read-only), if that file can be found reliably on the
  host. The builder's call is to skip that unless it is cheap.
- **Windows** stays unchecked and says so, as firn's body does today (named pipe, unmeasured).
- **No `sudo`, no symlink**, in any message. The message text is pinned by tests.

## firn

Nothing changes in firn in this ticket. At the bump that brings the task, firn's `deploy preflight`
moves to `support docker-preflight` with `task: "support:docker-preflight"` and
`with: { editor: devcontainer }`, `deploy devcontainer`'s `depends_on` names it, and
`deploy/provision/orchestrator/src/python/orchestrator/preflight.py` goes. A firn ticket says so once a
simplon release carries the task.

## Docs

- `with-what/phases.md`: the new coordinate.
- Release notes: the next unreleased section (si#564), including the resolver's new order.
- The census: the task adds no load-time refusal (its unknown-`editor` refusal is a run-time diagnosis).

## Tests (each seen red first)

- The resolver, pure: each order step with an injected env and endpoint, including a non-unix endpoint
  giving `""`, and `endpoint=None` falling back to today's order.
- `context_endpoint()` against a real docker CLI where the suite has one. `None` on a CLI that exits
  non-zero, via a `PATH` that points at a script, which is a real process and not a mock of `run`.
- The task: every row above, with docker stubbed at the PATH level (a script named `docker`). Not a real
  Colima: no host in CI has one. Record that limit in the test docstring.
- `docker._socket_path()` still answers what `_socket_state()` needs (existing tests stay green).
- The lab probe: unchanged outcomes on the existing tests, plus the guard: a non-Colima endpoint on
  macOS is ignored (a dead Colima with Docker Desktop answering stays `UNREACHABLE`), a Colima endpoint
  of another profile is pinged.
- The bootstrap guard: a context-only socket outside the system path is never chmod'ed, seen red first
  by pointing the resolution at a temporary socket.
- The editor view: with `DOCKER_HOST` set in the test's environment, the editor check resolves without
  it and warns (the builder check's measurement, as a test).

## Non-goals

- No change to the extension's behaviour (it is not ours). The finding that it reads a failed probe as
  `default` can go upstream separately, and that is not this ticket.
- No writing to editor configuration, no `sudo`, no symlink.
- No measurement of `/var/run` across a macOS reboot; nothing here depends on it any more.

## Left to the builder

- Module name for the body.
- Whether `context_endpoint` returns name and endpoint together.
- The exact wording, within the substance above.
