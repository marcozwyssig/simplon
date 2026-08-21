"""The `nexus` command group: lifecycle + honest state for a LAN Sonatype Nexus artefact proxy (netctl#948,
moved into the kernel by netctl#1405).

WHY THIS IS MECHANISM. Bring a container up, create the proxy repositories a product needs, report honest
state: none of that needs product knowledge. What IS product knowledge is DATA, and it arrives through the
manifest's `nexus` section (read RAW via `ProductContext.manifest_data()`, exactly like the `claude`
section): which proxy repositories to create and the script that creates them, the compose file and the
container name, and the ONE client-side base-URL variable the product's builds already read. This module
only orchestrates them, it re-derives nothing.

WHY `status` IS THE INTERESTING COMMAND. A GREEN container proves almost nothing here, and neither does a
green API. Nexus answers `/service/rest/v1/status` with 200 while it refuses every artefact with
`HTTP 403 ... accept the End User License Agreement`, and it refuses every artefact anonymously until
anonymous access is switched on. Both are the failure mode operators actually hit, and both look like "the
proxy is up" from the outside, so `status` classifies an ANONYMOUS CONTENT FETCH (service_verdict).

A REPOSITORY LISTING WOULD BE A LIE, and this is measured, not cautious: on a virgin instance with
anonymous read switched on, `GET /service/rest/v1/repositories` answers 200 with the COMPLETE repository
list while every artefact answers 403, and the same listing answers 200 to admin while the EULA is
unaccepted. The EULA gate sits on the `/repository/...` content path only. So only a real fetch separates
"configured" from "serving", which is also why the listing that `status` prints stays explicitly labelled
CONFIGURATION and carries its caveat: a proxy answers 404 for an artefact that plainly exists while its
upstream rate-limits it, and Nexus remembers that 404 for 24 h by default.

THREE VANTAGE POINTS, REPORTED SEPARATELY (netctl#996). "Is the proxy reachable" has no single answer on a
VM-hosted docker daemon, so this module asks the question from every position that matters instead of
picking one and hiding the disagreement. Measured on a macOS/Colima host, 2026-08-05:

  * from THIS SHELL (urllib): `http://localhost:8181` refused instantly, `http://172.17.0.1:8181` timed
    out after the full 4 s. The published port is simply not forwarded to the host.
  * from A BUILD CONTAINER (a throwaway curl): `http://172.17.0.1:8181` answers 200 in ~220 ms (#990).
  * from INSIDE THE SERVICE's own network namespace (`--network container:<the service container>`):
    always, on the container-internal port, independent of both of the above.

So a host-only probe made `status` report "no HTTP answer" while every build resolved through the proxy
perfectly. It now reports the shell AND the build vantage point on their own lines, and classifies the
answer that CAME BACK - preferring the build container's, because that is the vantage point that decides
whether builds resolve. The body is kept on every path (`curl -o -`, not `-o /dev/null`): the EULA 403
body IS the diagnosis, and a boolean reachability probe would throw it away. The third vantage point is
what the ADMIN calls use (blob store, cleanup policies): it needs no reachable base URL at all, and it
exists exactly while the container runs.

WHY THE BLOB-STORE VOLUME IS OBSERVED BUT NEVER RECLAIMED AUTOMATICALLY (netctl#994). The blob store grows
monotonically on the same filesystem that builds and runs the lab containers, and nothing prunes it: the
disk guard prunes dangling images + build cache (a build rebuilds both for free) and deliberately never
touches volumes, and a product's `clean` leaves it because it is SERVICE state. That is correct and must
stay correct - a pruned proxy re-downloads everything from Central, the exact failure the proxy exists to
prevent. So the exposure is closed by MEASURING it (`status` reports the blob-store size and the free
space under it) and by a FORMAT-AWARE reclaim (`cleanup` sets Nexus' own cleanup policies), never by a
blanket volume removal.

WHY THE DOCKER CALLS ARE NOT ROUTED THROUGH `Host`. This is a HOST service like the containerised build
toolchains, not a lab-topology container, so it runs on whatever daemon the host `docker` CLI talks to
(the Colima context on macOS). Splitting it - `docker compose` on the host, `docker exec` through
`colima ssh` - would address two different daemons for the two halves of the same service, so both go
through the same plain `run(["docker", ...])` seam.

WHY IT IS NOT PART OF ANY COMPOSITE (`up`, `bringup`, `test all`). Deliberate, and it is the same
argument that produced the reachability probe in the product's mirror wiring: a build must not hard-depend
on the proxy. Gradle continues past a 404 but a transport failure aborts resolution outright, so a proxy
the build REQUIRES is a hard single point of failure for every build - the exact exposure netctl#948 set
out to remove. Two further reasons: the service is long-lived by design (started per build its cache is
empty every time and it adds nothing but a network hop), and the EULA acceptance is a legal operator
action that no unattended pipeline step may click through, so a composite could never reach a serving
state on a fresh volume anyway.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from delivery import context, log
from delivery.run import run

# --- the manifest section this module owns -----------------------------------------------------------

SECTION = "nexus"

# --- constants that are MECHANISM, not product data --------------------------------------------------
#
# Everything below is a property of Nexus itself (its API surface, its two manual gates, how its answers
# read) or of how the probes are asked. Nothing here names a product.

# The generated initial admin password, written into the volume on first boot. Nexus DELETES this file
# once the password has been changed through the onboarding wizard, so its absence is normal on a
# long-running instance and must degrade to NEXUS_ADMIN_PASSWORD, not to an error about docker.
ADMIN_PASSWORD_FILE = "/nexus-data/admin.password"
ADMIN_PASSWORD_ENV_VAR = "NEXUS_ADMIN_PASSWORD"

# Where `status` / `repos` address the API. Precedence: an explicit NEXUS_URL (what a shipped
# create-repositories.sh already reads) > the product's client-side base URL variable (netctl#948: if the
# operator named a base for the builds, that is the same instance) > localhost on the compose file's
# published port. Container-internal 8081 is deliberately published elsewhere: host 8081 tends to be taken,
# and netctl's dev lab publishes 8080-8083 - which port is the product's DATA (`http_port`).
NEXUS_URL_ENV_VAR = "NEXUS_URL"
HTTP_PORT_ENV_VAR = "NEXUS_HTTP_PORT"

# The repository listing. It reports what is CONFIGURED and nothing more; it is NOT what decides whether the
# instance serves (see `NexusConfig.content_probe_path`).
REPOSITORIES_API_PATH = "/service/rest/v1/repositories"

PROBE_TIMEOUT_S = 5.0

# The CONTENT probe gets a longer budget than the host courtesy probe: on a cold cache it is a real
# proxy fetch from Central, and reporting "no answer" for a fetch that was merely slow would be the same
# class of lie this probe exists to remove. `--connect-timeout` stays short so an unreachable base still
# fails fast instead of waiting out the full budget.
CONTENT_PROBE_TIMEOUT_S = 10.0
CONNECT_TIMEOUT_S = 3.0

# The two vantage points `status` reports for the CONFIGURED base URL, named the way the report reads.
HOST_VANTAGE = "this shell"
BUILD_VANTAGE = "a build container"

# How the container-side curl tags its status code. A MARKER, not a position: the body is arbitrary (a JSON
# listing, an HTML error page from a proxy in front) and could itself end in a line of digits.
CURL_CODE_MARKER = "netctl-http-code="

# The THIRD vantage point (see the module docstring): a probe container that joins the service container's
# own network namespace addresses the API on the container-INTERNAL port, so neither a missing host port
# forward nor a misconfigured NEXUS_URL can break it.
SERVICE_INTERNAL_PORT = "8081"
SERVICE_API_BASE = f"http://localhost:{SERVICE_INTERNAL_PORT}"

# The address a build container reaches a host-published port on, on a docker-in-VM host (Colima). Named
# here because the `localhost` base-URL trap is diagnosed by pointing at it.
BUILD_CONTAINER_GATEWAY = "172.17.0.1"

# The blob-store endpoint `status` sizes (netctl#994). ADMIN-ONLY: measured 2026-08-05, an anonymous GET
# answers 403 even with anonymous read enabled. The anonymous repository listing does carry a
# per-repository `size` field, but it read 0 on every repository on a live instance holding 85 MB of blobs,
# so it is not usable.
BLOB_STORES_API_PATH = "/service/rest/v1/blobstores"

# Cleanup policies (netctl#994). The CRUD lives on the INTERNAL API - the documented v1 surface has only
# /v1/cleanup/run - and the attachment is NOT owned by the policy: a PUT carrying a `repositories` list
# answers `400 The 'repositories' field is not supported for format 'maven2'`, so attaching is a repository
# UPDATE. All verified against the live 3.94.1 instance on 2026-08-05.
CLEANUP_POLICIES_API_PATH = "/service/rest/internal/cleanup-policies"
CLEANUP_RUN_API_PATH = "/service/rest/v1/cleanup/run"

# What RUNS the policies, and why nothing has to be scheduled here: a fresh 3.94.1 already ships an enabled
# `repository.cleanup` task named "Cleanup service" on cron `0 0 1 * * ?` (verified via /v1/tasks, with
# lastRunResult OK). Attaching a policy is therefore sufficient; creating a task would duplicate it.
CLEANUP_TASK_TYPE = "repository.cleanup"
CLEANUP_TASK_NAME = "Cleanup service"

# The retention criterion: delete what has not been DOWNLOADED for this many days. Last-downloaded rather
# than last-updated because this is a read-through proxy cache - what nothing has asked for in a month is
# what nobody misses, whereas an old-but-hot artefact (a pinned plugin version) must stay.
CLEANUP_DAYS_ENV_VAR = "NEXUS_CLEANUP_DAYS"
DEFAULT_CLEANUP_DAYS = 30
MIN_CLEANUP_DAYS = 1

# The group members, in the order the bare group lists them. `repos` runs the product's repository script;
# it is separate from `up` because creating repositories requires the EULA to be accepted first, which is
# an operator action `up` cannot perform.
MEMBERS: tuple[tuple[str, str], ...] = (
    ("up", "start the Nexus service (docker compose up -d); long-lived, leave it running"),
    ("down", "stop the Nexus service (docker compose down); the nexus-data volume SURVIVES"),
    ("status", "container state + health, reachability from BOTH vantage points, the two manual steps, "
               "and the blob-store size"),
    ("repos", "create the proxy repositories this product needs (create-repositories.sh); needs the EULA "
              "accepted"),
    ("cleanup", f"set Nexus cleanup policies (not downloaded for {DEFAULT_CLEANUP_DAYS} days) on the proxy "
                f"repositories, so the blob store stops growing unbounded"),
)
MEMBER_NAMES: tuple[str, ...] = tuple(name for name, _ in MEMBERS)


# --- the product DATA --------------------------------------------------------------------------------

@dataclass(frozen=True)
class ProxyRepository:
    """One proxy repository `cleanup` configures, with the two DIFFERENT names Nexus uses for its format.

    `fmt` is the format string a cleanup policy is scoped by (`maven2`), `api_segment` is the segment in
    the repository path (`/v1/repositories/maven/proxy/...`). They differ for maven only, which is exactly
    the kind of detail that makes a guessed URL 404 silently."""

    name: str
    fmt: str
    api_segment: str


@dataclass(frozen=True)
class NexusConfig:
    """Everything about a Nexus deployment that is the PRODUCT's, resolved from its manifest.

    Nothing in this module names a product; every product token in the report - the command names it tells
    the operator to run, the container, the volume, the base-URL variable - comes from here. `cli` is the
    product's command name, so the report reads `netctl nexus status` for netctl and `<other> nexus status`
    for the next product without a second declaration.
    """

    cli: str
    container: str
    volume: str
    compose_file: Path
    repositories_script: Path
    base_url_env: str
    http_port: str
    probe_image: str
    content_probe_path: str
    proxy_repositories: tuple[ProxyRepository, ...]

    @property
    def group_command(self) -> str:
        """How the report addresses this group's members, e.g. `netctl nexus`."""
        return f"{self.cli} {SECTION}"

    @property
    def build_container_base(self) -> str:
        """The base URL a BUILD CONTAINER can reach a host-published Nexus on, for the `localhost` trap."""
        return f"http://{BUILD_CONTAINER_GATEWAY}:{self.http_port}"


def declared(data: Mapping[str, object], root: Path, source: str = "manifest") -> NexusConfig:
    """The `nexus` section as a NexusConfig, validated LOUDLY.

    Same discipline as `delivery.commands.claudeplugins.declared`: a malformed section fails HERE, naming
    the offending key and the file, rather than surfacing later as a probe of a nonsense URL or a
    `docker compose -f` on a path that was never a path. The two file keys are resolved RELATIVE TO THE
    PRODUCT ROOT, so the manifest carries a repo-relative path and never an absolute one.

    Nothing is defaulted except `http_port`, which the compose file already defaults the same way: a
    silently defaulted container name or volume would make a wrong report about the wrong service, which is
    the class of lie this whole module exists to remove.
    """
    section = data.get(SECTION)
    if not isinstance(section, Mapping):
        raise ValueError(f"{source}: the '{SECTION}' section is missing or is not a mapping")

    def _text(key: str) -> str:
        value = str(section.get(key, "")).strip()
        if not value:
            raise ValueError(f"{source}: '{SECTION}.{key}' is missing or empty")
        return value

    raw_repos = section.get("proxy_repositories") or []
    if not isinstance(raw_repos, (list, tuple)):
        raise ValueError(f"{source}: '{SECTION}.proxy_repositories' must be a list of "
                         f"'{{name, format, api}}' entries")
    repositories: list[ProxyRepository] = []
    for entry in raw_repos:
        where = f"{SECTION}.proxy_repositories"
        if not isinstance(entry, Mapping):
            raise ValueError(f"{source}: '{where}': each entry must be a mapping with 'name', 'format' "
                             f"and 'api'")
        name = str(entry.get("name", "")).strip()
        fmt = str(entry.get("format", "")).strip()
        api = str(entry.get("api", "")).strip()
        if not (name and fmt and api):
            raise ValueError(f"{source}: '{where}': '{name or entry}' must name 'name', 'format' and 'api' "
                             f"(the format a policy is scoped by, and the path segment the API uses - they "
                             f"differ for maven)")
        repositories.append(ProxyRepository(name=name, fmt=fmt, api_segment=api))
    if not repositories:
        raise ValueError(f"{source}: '{SECTION}.proxy_repositories' declares none, so `cleanup` would "
                         f"report success while the blob store keeps growing unbounded")

    probe_path = _text("content_probe_path")
    if not probe_path.startswith("/repository/"):
        raise ValueError(f"{source}: '{SECTION}.content_probe_path' must be a CONTENT path under "
                         f"/repository/..., got '{probe_path}'. A REST listing answers 200 on an instance "
                         f"that serves nothing at all, so it may not decide `serving`")

    return NexusConfig(
        cli=_text("cli"),
        container=_text("container"),
        volume=_text("volume"),
        compose_file=root / _text("compose_file"),
        repositories_script=root / _text("repositories_script"),
        base_url_env=_text("base_url_env"),
        http_port=str(section.get("http_port", "") or "8181").strip(),
        probe_image=_text("probe_image"),
        content_probe_path=probe_path,
        proxy_repositories=tuple(repositories),
    )


def config() -> NexusConfig:
    """This process' product's Nexus configuration, off the registered ProductContext."""
    ctx = context.current()
    return declared(ctx.manifest_data(), ctx.root, source=str(ctx.manifest_path))


# --- pure decisions (unit-tested; no docker, no network) ---------------------------------------------

def api_base(cfg: NexusConfig, env: dict[str, str] | None = None) -> str:
    """The base URL `status`/`repos` address, with no trailing slash. Pure; `env` injectable for tests."""
    src = os.environ if env is None else env
    for var in (NEXUS_URL_ENV_VAR, cfg.base_url_env):
        explicit = (src.get(var) or "").strip()
        if explicit:
            return explicit.rstrip("/")
    port = (src.get(HTTP_PORT_ENV_VAR) or "").strip() or cfg.http_port
    return f"http://localhost:{port}"


@dataclass(frozen=True)
class ContainerVerdict:
    """The container half of `status`: does it exist, what state is it in, what does its healthcheck say.

    `health` is "none" for an image without a healthcheck as well as for a container docker reports no
    health block for; the compose file DOES define one, so "none" on a running container means the
    start_period has not produced a first result yet."""

    present: bool
    state: str
    health: str

    @property
    def running(self) -> bool:
        return self.present and self.state == "running"


def parse_container_state(text: str) -> ContainerVerdict:
    """PURE: read `docker inspect`'s `<state>|<health>` output into a ContainerVerdict.

    Empty/garbage output means the container does not exist (a missing container makes docker inspect
    fail with an empty stdout), which is a legitimate state and NOT an error - `status` must be runnable
    before the first `nexus up`."""
    parts = (text or "").strip().splitlines()
    if not parts or not parts[0].strip():
        return ContainerVerdict(present=False, state="", health="none")
    state, _, health = parts[0].strip().partition("|")
    return ContainerVerdict(present=True, state=state.strip(), health=(health.strip() or "none"))


@dataclass(frozen=True)
class ServiceVerdict:
    """The API half of `status`: is the instance actually SERVING, and which of the two mandatory manual
    steps is still missing.

    `serving` means an ANONYMOUS CONTENT FETCH really returned an artefact, so builds can resolve without
    credentials. Nothing weaker counts: a repository listing answers 200 on an instance that serves nothing
    (see `NexusConfig.content_probe_path` for the measured matrix).

    `eula_accepted` / `anonymous_read` are tri-state on purpose: None means this answer does not say, and
    reporting None as False would be a fabricated diagnosis."""

    serving: bool
    eula_accepted: bool | None
    anonymous_read: bool | None
    reason: str


def service_verdict(cfg: NexusConfig, status_code: int | None, body: str = "") -> ServiceVerdict:
    """PURE: classify the ANONYMOUS CONTENT-FETCH answer into the operator-relevant verdict.

    The mapping is the measured behaviour of a virgin and of a fully provisioned 3.94.1 instance
    (2026-08-05, see the content-probe matrix). Every branch is a measurement, not an inference:
      * no answer at all -> the service is not up (or not reachable from the vantage point that asked);
      * 401 -> anonymous read is off (this version's default). It says NOTHING about the EULA: the auth
        check runs FIRST, so an unauthenticated caller never reaches the EULA gate;
      * 403 naming the EULA -> the EULA is unaccepted, and no content is served at all - not even to admin.
        It ALSO proves anonymous read is on, because the call got past the auth check to reach this gate;
      * 404 -> both gates are past, but this artefact is not served: a cold cache whose remote did not
        supply it (on a rate-limited WAN IP that is the negative-cache trap, remembered for 24 h by
        default), or a repository that does not exist. Those two are indistinguishable here - both answer
        404 - so neither is claimed;
      * 200 -> both prerequisites are done AND an artefact really came through. The only proof of serving;
      * anything else -> unknown; say so rather than guess a cause.
    """
    if status_code is None:
        return ServiceVerdict(False, None, None,
                              "no HTTP answer (not up, still booting, or the published port is not reachable "
                              f"from here - a VM-hosted daemon publishes on the VM; set {NEXUS_URL_ENV_VAR} "
                              "to the address that IS reachable)")
    if status_code == 200:
        return ServiceVerdict(True, True, True,
                              "an anonymous CONTENT fetch really served an artefact (HTTP 200)")
    if status_code == 403 and "eula" in (body or "").lower():
        return ServiceVerdict(False, False, True,
                              "HTTP 403: the EULA is NOT accepted, so no artefact is served - not even to "
                              "admin (a repository LISTING still answers 200 in this state, which is why it "
                              "is not what this probes). Accept it in the onboarding wizard or via "
                              "/service/rest/v1/system/eula")
    if status_code == 403:
        return ServiceVerdict(False, None, None, "HTTP 403 without an EULA hint: access denied for another reason")
    if status_code == 401:
        return ServiceVerdict(False, None, False,
                              "HTTP 401: anonymous read is DISABLED (this version's default), so an "
                              "unauthenticated build resolves nothing. Enable it via "
                              "PUT /service/rest/v1/security/anonymous. This answer says nothing about the "
                              "EULA - the auth check runs before that gate")
    if status_code == 404:
        return ServiceVerdict(False, True, True,
                              f"HTTP 404 on {cfg.content_probe_path}: past both gates but serving no "
                              f"artefact. Either the cache is cold and the remote did not supply it (on a "
                              f"rate-limited WAN IP this is the negative-cache trap, remembered for 24 h by "
                              f"default - run Invalidate cache on the proxy) or the repository does not "
                              f"exist. Both answer 404, so neither is claimed here")
    return ServiceVerdict(False, None, None, f"unexpected HTTP {status_code} on {cfg.content_probe_path}")


def repository_names(body: str) -> tuple[str, ...]:
    """PURE: the repository names in a repository-listing body, or () when the body is not that listing.

    Best-effort by contract: `status` uses this to report what EXISTS, and a body it cannot parse must
    degrade to "no listing", never to a traceback."""
    try:
        parsed = json.loads(body or "")
    except (ValueError, TypeError):
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(entry.get("name", "")) for entry in parsed
                 if isinstance(entry, dict) and entry.get("name"))


def status_lines(cfg: NexusConfig, container: ContainerVerdict, service: ServiceVerdict, base: str,
                 repositories: tuple[str, ...] = ()) -> list[str]:
    """PURE: the `status` report. Deliberately claims nothing about whether a repository SERVES.

    Presence is not proof, and this is not a hypothetical: a proxy answers 404 for an artefact that plainly
    exists while its upstream rate-limits it, and Nexus' negative cache then remembers that 404 for 24 h
    (default 1440 MINUTES). That is exactly what `maven-public` did during the 2026-08-04 429 window - it
    serves correctly now, which is the point: a listing tells you a repository is CONFIGURED, and only a real
    fetch tells you it works. So a caveat line rides along whenever anything is listed, never a green claim."""
    lines = [f"container {cfg.container}: " + (f"absent (run `{cfg.group_command} up`)"
                                               if not container.present
                                               else f"{container.state}, health={container.health}"),
             f"api {base} (anonymous fetch of {cfg.content_probe_path}): {service.reason}"]
    for label, value in (("eula accepted", service.eula_accepted), ("anonymous read", service.anonymous_read)):
        lines.append(f"{label}: " + {True: "yes", False: "NO", None: "unknown (this answer does not say)"}[value])
    if repositories:
        lines.append(f"repositories present ({len(repositories)}): {', '.join(sorted(repositories))}")
        lines.append("note: a repository EXISTING is not a repository SERVING - a proxy answers 404 while its "
                     "upstream rate-limits, and the negative cache remembers that for 24 h by default. This "
                     "listing is CONFIGURATION, not a fetch; run a real build to know.")
    return lines


def status_rc(container: ContainerVerdict, service: ServiceVerdict, build_reachable: bool = True) -> int:
    """PURE: 0 only when the container runs AND an anonymous read really succeeds AND a build container can
    reach the configured base. A green container that answers 403/401 is a FAILURE here on purpose - that is
    the whole point of the command.

    `build_reachable` defaults to True, i.e. an UNKNOWN build vantage never fails the command: the flag
    exists to catch the case that actually breaks builds while looking fine from the operator's shell (a
    `localhost` base URL, which a container resolves to itself), not to invent a verdict when nobody asked
    the question."""
    return 0 if container.running and service.serving and build_reachable else 1


# --- netctl#996: the two vantage points, reported separately ----------------------------------------

def parse_curl_answer(text: str) -> tuple[int | None, str]:
    r"""PURE: split a probe curl's `-o - -w '\n<CURL_CODE_MARKER>%{http_code}'` output into (code, body).

    The marker is what makes this safe: the body is arbitrary and could itself end in a line of digits, so
    the status code is TAGGED rather than read off the last line. curl prints `000` when it never got an
    answer, which maps to None - the same "no answer at all" the host probe reports - and output with no
    marker at all (the probe could not even run: no docker, no image) maps to None as well."""
    marker_at = (text or "").rfind(CURL_CODE_MARKER)
    if marker_at < 0:
        return None, ""
    code_text = text[marker_at + len(CURL_CODE_MARKER):].strip()
    body = text[:marker_at]
    if body.endswith("\n"):
        body = body[:-1]
    if not code_text.isdigit() or int(code_text) == 0:
        return None, body
    return int(code_text), body


def effective_answer(host_answer: tuple[int | None, str],
                     build_answer: tuple[int | None, str]) -> tuple[int | None, str]:
    """PURE: which of the two answers `status` classifies (netctl#996). The BUILD container's when it
    answered at all, else the shell's.

    The build container wins because it is the vantage point that decides whether builds resolve, and
    because on a VM-hosted daemon it is frequently the ONLY one that answers - taking the host's silence as
    the verdict is what made `status` report a dead proxy while every build worked. Both carry the body, so
    the EULA/anonymous-read diagnosis survives either way."""
    return build_answer if build_answer[0] is not None else host_answer


def _reachability_line(vantage: str, code: int | None) -> str:
    return f"reachable from {vantage}: " + ("no (no answer)" if code is None else f"yes (HTTP {code})")


def reachability_lines(cfg: NexusConfig, host_code: int | None, build_code: int | None,
                       base: str) -> list[str]:
    """PURE: one honest line per vantage point, plus the note that matters when the two DISAGREE (#996).

    Reporting a single verdict was the defect: on a Colima host the shell reaches nothing while a build
    container gets 200, so a human read "the proxy is down" off a proxy every build was resolving through.
    The two disagreements are not symmetric and neither is its message:
      * shell no / container yes - nothing is broken, the builds are fine, and saying so is the point;
      * shell yes / container no - the builds are BROKEN and it is invisible from the shell, which is the
        `localhost` base-URL trap (a container resolves localhost to itself)."""
    lines = [_reachability_line(HOST_VANTAGE, host_code), _reachability_line(BUILD_VANTAGE, build_code)]
    if host_code is None and build_code is not None:
        lines.append(f"note: your shell cannot reach {base} but a build container can, so the BUILDS "
                     f"resolve through the proxy fine - this is not a fault. A port published by a "
                     f"VM-hosted daemon (Colima) is not forwarded to the host shell. Set "
                     f"{NEXUS_URL_ENV_VAR} to an address this shell can reach if you want the two to agree.")
    elif host_code is not None and build_code is None:
        lines.append(f"note: your shell reaches {base} but a BUILD CONTAINER does not, so every build "
                     f"resolves against the origins instead (the rate-limit exposure is back) while this "
                     f"looks healthy from here. A container resolves `localhost` to ITSELF; point "
                     f"{cfg.base_url_env} at an address the build container can reach (on a Colima host "
                     f"that is {cfg.build_container_base}).")
    return lines


# --- netctl#994: the blob store, measured -----------------------------------------------------------

@dataclass(frozen=True)
class BlobStore:
    """One blob store as /v1/blobstores reports it: how much it holds, and how much room is left under it.

    `available_bytes` is the FILESYSTEM's free space, not a quota, and it is the number that matters: the
    failure netctl#994 is about is a full disk during a lab deploy, not Nexus complaining."""

    name: str
    blob_count: int
    total_bytes: int
    available_bytes: int


def parse_blob_stores(body: str) -> tuple[BlobStore, ...]:
    """PURE: the blob stores in a /v1/blobstores listing, or () when the body is not that listing.

    Best-effort by contract, exactly like repository_names: this rides along in a STATUS report, so a body
    it cannot parse must degrade to "not reported", never to a traceback in the middle of the output."""
    try:
        parsed = json.loads(body or "")
    except (ValueError, TypeError):
        return ()
    if not isinstance(parsed, list):
        return ()
    stores = []
    for entry in parsed:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        stores.append(BlobStore(name=str(entry["name"]),
                                blob_count=int(entry.get("blobCount") or 0),
                                total_bytes=int(entry.get("totalSizeInBytes") or 0),
                                available_bytes=int(entry.get("availableSpaceInBytes") or 0)))
    return tuple(stores)


def format_bytes(count: int) -> str:
    """PURE: a byte count in binary units with one decimal. Binary because that is what df and docker
    report, so the number a reader compares this against uses the same base."""
    if count < 0:
        return "unknown"
    for unit, size in (("TiB", 1024 ** 4), ("GiB", 1024 ** 3), ("MiB", 1024 ** 2), ("KiB", 1024)):
        if count >= size:
            return f"{count / size:.1f} {unit}"
    return f"{count} B"


def blob_store_lines(cfg: NexusConfig, status_code: int | None, stores: tuple[BlobStore, ...] = (),
                     credentials: bool = True) -> list[str]:
    """PURE: the blob-store half of the `status` report (netctl#994), always exactly one verdict.

    Every failure is reported as NOT REPORTED with the reason, never as a zero size: "0 B" for an
    unauthenticated answer would be a fabricated measurement of the one thing this exists to measure. The
    note that rides along with a real reading is the load-bearing part - it names WHY nothing reclaims this
    volume and points at the format-aware reclaim, because the wrong reaction to a large number here (a
    `docker volume rm`) re-downloads everything from Central."""
    if not credentials:
        return [f"blob store: not reported (no admin credentials; {ADMIN_PASSWORD_FILE} is gone, which is "
                f"normal once the password has been changed - export {ADMIN_PASSWORD_ENV_VAR})"]
    if status_code is None:
        return [f"blob store: not reported (the admin API on container {cfg.container} did not answer)"]
    if status_code in (401, 403):
        return [f"blob store: not reported (HTTP {status_code} on {BLOB_STORES_API_PATH}: the admin "
                f"credentials were refused; this endpoint is admin-only even with anonymous read on)"]
    if status_code != 200:
        return [f"blob store: not reported (unexpected HTTP {status_code} on {BLOB_STORES_API_PATH})"]
    if not stores:
        return [f"blob store: not reported (HTTP 200, but {BLOB_STORES_API_PATH} carried no blob store)"]
    lines = [f"blob store {store.name}: {format_bytes(store.total_bytes)} in {store.blob_count} blobs, "
             f"{format_bytes(store.available_bytes)} free on its filesystem" for store in stores]
    lines.append(f"note: this is the `{cfg.volume}` docker VOLUME and NOTHING reclaims it automatically - "
                 f"the disk guard prunes dangling images + build cache and never touches volumes, and "
                 f"`{cfg.cli} clean` leaves it because it is SERVICE state. Reclaim it with "
                 f"`{cfg.group_command} cleanup` (format-aware, keeps what is still being used), never with "
                 f"a volume rm: that re-downloads everything from Central, the exact failure the proxy "
                 f"exists to prevent.")
    return lines


def volume_guard_note(cfg: NexusConfig, free_pct: int | None, min_free_pct: int,
                      volume_present: bool) -> str | None:
    """PURE: what a disk guard is allowed to say about the blob-store volume, or None when there is nothing
    to say.

    It WARNS and never acts, and that asymmetry is the design (netctl#994): the guard prunes dangling images
    and build cache because a build rebuilds both for free, while this volume is a read-through PROXY CACHE
    whose removal costs a full re-download from the rate-limited origins - the failure the proxy exists to
    prevent. None when the disk is not actually low or the volume does not exist, so a host without a Nexus
    never sees this line and a healthy disk never carries the noise."""
    if free_pct is None or not volume_present or free_pct >= min_free_pct:
        return None
    return (f"the Nexus proxy cache lives in the `{cfg.volume}` docker VOLUME, which this guard does NOT "
            f"prune ({free_pct}% free, below the {min_free_pct}% bar) and must not: pruning a proxy makes "
            f"every build re-download from the rate-limited origins. Reclaim it format-aware with "
            f"`{cfg.group_command} cleanup`, and see its size with `{cfg.group_command} status`.")


# --- netctl#994: cleanup policies -------------------------------------------------------------------

def cleanup_days(env: dict[str, str] | None = None) -> int:
    """PURE: the retention window in days, from NEXUS_CLEANUP_DAYS, defaulting to DEFAULT_CLEANUP_DAYS.

    A garbage or non-positive value falls back to the default rather than being passed on: 0 days would
    delete artefacts the moment they stop being downloaded, which on a proxy is the same self-inflicted
    re-download this whole feature exists to avoid."""
    src = os.environ if env is None else env
    raw = (src.get(CLEANUP_DAYS_ENV_VAR) or "").strip()
    if not raw.isdigit() or int(raw) < MIN_CLEANUP_DAYS:
        return DEFAULT_CLEANUP_DAYS
    return int(raw)


def policy_name(cfg: NexusConfig, fmt: str) -> str:
    """PURE: the cleanup policy name for a Nexus format, namespaced by the product so an operator's own
    policies are never touched. STABLE across retention changes on purpose - the days live in the policy's
    criteria, so re-running with a different window UPDATES one policy instead of leaving a trail of
    `netctl-maven2-30d`, `netctl-maven2-45d`, ... attached to the same repository."""
    return f"{cfg.cli}-{fmt}-lastdownload"


def cleanup_formats(cfg: NexusConfig) -> tuple[str, ...]:
    """PURE: the distinct formats to create a policy for, in declaration order. A cleanup policy is
    format-scoped, so two maven2 repositories share one policy rather than getting one each."""
    seen: list[str] = []
    for repo in cfg.proxy_repositories:
        if repo.fmt not in seen:
            seen.append(repo.fmt)
    return tuple(seen)


def policy_body(cfg: NexusConfig, fmt: str, days: int) -> str:
    """PURE: the cleanup-policy body. `criteriaLastDownloaded` is in DAYS (verified: 30 in, 30 back out);
    every other criterion stays null so the policy says exactly one thing."""
    return json.dumps({"name": policy_name(cfg, fmt), "format": fmt,
                       "notes": f"{cfg.cli}: proxy cache not downloaded for {days} days",
                       "criteriaLastBlobUpdated": None, "criteriaLastDownloaded": days,
                       "criteriaReleaseType": None, "criteriaAssetRegex": None},
                      separators=(",", ":"))


def policy_verdict(post_code: int | None, put_code: int | None = None) -> tuple[bool, str]:
    """PURE: classify creating (and, when it already exists, updating) one cleanup policy.

    Measured on the live 3.94.1 instance, 2026-08-05: a POST answers 200 with the created policy, and 400
    `Name is already used, must be unique (ignoring case)` when the name is taken; a PUT on the existing
    name answers 200 and really does change the criteria (30 -> 45 days, read back). So "exists" is an
    UPDATE, not an error - a re-run with a different NEXUS_CLEANUP_DAYS has to be able to move the window."""
    if post_code == 200:
        return True, "created"
    if post_code == 400:
        if put_code == 200:
            return True, "updated"
        return False, f"already exists but the update failed (HTTP {put_code})" if put_code is not None \
            else "already exists but the update got no answer"
    if post_code is None:
        return False, "no answer from the cleanup-policy API"
    return False, f"failed (HTTP {post_code})"


def cleanup_patch(repo_body: str, policy: str) -> tuple[str | None, str]:
    """PURE: `(the body to PUT, outcome)` for attaching `policy` to a repository's configuration.

    The attachment is a repository UPDATE, not a property of the policy: a policy PUT carrying a
    `repositories` list answers `400 The 'repositories' field is not supported for format 'maven2'`
    (verified 2026-08-05). Read-modify-write is therefore the only route, and the full GET body is what the
    PUT wants - which is also why this is a PATCH of that body and not a re-render of the canonical
    definition: an operator is told to raise `negativeCache.timeToLive` after the first fill, and a blind
    re-render would silently undo that.

    UNION, never replace: the product's policy is ADDED to `cleanup.policyNames`, so an operator's own
    policy on the same repository survives. Outcomes: "attach" with a body, "already" (idempotent, and then
    the caller performs NO PUT at all), "unreadable" for a body that is not the expected object."""
    try:
        parsed = json.loads(repo_body or "")
    except (ValueError, TypeError):
        return None, "unreadable"
    if not isinstance(parsed, dict):
        return None, "unreadable"
    current = parsed.get("cleanup") or {}
    existing = current.get("policyNames") if isinstance(current, dict) else None
    names = [str(name) for name in existing] if isinstance(existing, list) else []
    if policy in names:
        return None, "already"
    parsed["cleanup"] = {"policyNames": names + [policy]}
    return json.dumps(parsed, separators=(",", ":")), "attach"


def _curl_config_escape(value: str) -> str:
    """PURE: escape a value for a quoted curl-config parameter (backslash and double quote)."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def curl_stdin_config(password: str, data: str | None = None) -> str:
    """PURE: the `curl -K -` config fed on STDIN, so NEITHER the credential nor the request body ever
    appears in argv.

    argv is the thing to stay out of: it is visible in `ps` to every user on the host (a container's argv
    included) and a hand-typed equivalent lands in shell history. create-repositories.sh established this
    mechanism for the credential; carrying the JSON body in the same config extends it, and is what makes a
    read-modify-write PUT possible at all without writing the body to a file. Values are quoted and
    escaped per curl's config syntax, verified against the live instance with a body containing both a
    double quote and a backslash (HTTP 200, both characters intact in the stored policy)."""
    lines = [f'user = "{_curl_config_escape("admin:" + password)}"']
    if data is not None:
        lines.append('header = "Content-Type: application/json"')
        lines.append(f'data = "{_curl_config_escape(data)}"')
    return "\n".join(lines) + "\n"


def dry_run_line(repository: str, status_code: int | None, body: str) -> str:
    """PURE: what a cleanup DRY RUN reports for one repository.

    A dry run is the only honest answer to "did that policy do anything": `POST /v1/cleanup/run` with
    `dryRun: true` evaluates the attached policies SYNCHRONOUSLY and returns `componentCount`, the number
    of components a real run WOULD delete, deleting nothing (verified 2026-08-05: 200 with componentCount 0
    on a freshly attached policy, and 404 for a repository that does not exist). Reported per repository
    because that is the granularity the endpoint works at."""
    if status_code == 404:
        return f"{repository}: absent, nothing to evaluate"
    if status_code != 200:
        return f"{repository}: dry run gave " + (f"HTTP {status_code}" if status_code else "no answer")
    try:
        parsed = json.loads(body or "")
        count = parsed["componentCount"]
    except (ValueError, TypeError, KeyError, IndexError):
        return f"{repository}: dry run answered 200 but carried no componentCount"
    return f"{repository}: {count} component(s) would be deleted by the next `{CLEANUP_TASK_NAME}` run"


def member_listing(cfg: NexusConfig) -> list[str]:
    """PURE: the bare-group listing. Pure group logic - the bare call lists the members, every action is an
    explicitly named member, no default action shadowing the group."""
    width = max(len(name) for name in MEMBER_NAMES)
    return [f"usage: {cfg.group_command} <{'|'.join(MEMBER_NAMES)}>", ""] + \
           [f"  {name.ljust(width)}  {help_text}" for name, help_text in MEMBERS]


def unknown_member_message(member: str) -> str:
    """PURE: the fail-loud message for a member that does not exist (never a silent fallback)."""
    return f"unknown nexus command: {member} (use: {' | '.join(MEMBER_NAMES)})"


# --- impure edges ------------------------------------------------------------------------------------

def _require_docker() -> None:
    from delivery import docker
    docker.ensure_docker()


def _http_probe(url: str, timeout: float = PROBE_TIMEOUT_S) -> tuple[int | None, str]:
    """`(status_code, body)` for a GET, with None for "no answer at all". An HTTPError IS an answer, so
    its status + body are returned - the 401/403 bodies are the whole diagnosis."""
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read(8192).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(8192).decode("utf-8", "replace")
    except Exception:
        return None, ""


def _curl_argv(cfg: NexusConfig, url: str, timeout: float, *, netns_of: str | None = None,
               authenticated: bool = False, method: str = "GET") -> list[str]:
    """The `docker run ... curl` argv for a container-side probe. Split out so the SHAPE is inspectable.

    It borrows curl from the product's `probe_image`, the same image netctl#990 probes the mirror with and
    the same image every gradle invocation already runs in, so no extra image is ever pulled. Two
    deliberate differences from that probe: `-o -` keeps the BODY (the EULA 403 body is the diagnosis, a
    boolean is not enough here), and `-w` tags the status code so the body cannot be mistaken for it. `-f`
    stays absent for the same reason as in #990: any HTTP answer is an answer."""
    argv = ["docker", "run", "--rm"]
    if authenticated:
        argv.append("-i")  # the credential arrives on stdin as a curl config, never in argv
    if netns_of:
        argv += ["--network", f"container:{netns_of}"]
    argv += ["--entrypoint", "curl", cfg.probe_image,
             "-sS", "-o", "-", "--connect-timeout", str(CONNECT_TIMEOUT_S), "-m", str(timeout),
             "-w", f"\\n{CURL_CODE_MARKER}%{{http_code}}"]
    if authenticated:
        argv += ["-K", "-"]
    if method != "GET":
        argv += ["-X", method]
    return argv + [url]


def _container_http_probe(cfg: NexusConfig, url: str,
                          timeout: float = CONTENT_PROBE_TIMEOUT_S) -> tuple[int | None, str]:
    """`(status_code, body)` for an ANONYMOUS GET asked from a BUILD CONTAINER (netctl#996).

    The second of the two vantage points `status` reports. A plain `docker run` on the default bridge, NOT
    the service container's namespace, because the question is precisely "can a build container reach the
    CONFIGURED base URL" - joining the service's namespace would answer a different, easier question and
    hide the `localhost` base-URL trap this is meant to expose. A probe that cannot even run degrades to
    "no answer", never to a traceback."""
    try:
        res = run(_curl_argv(cfg, url, timeout))
    except Exception:
        return None, ""
    return parse_curl_answer(res.out)


def _service_curl(cfg: NexusConfig, password: str, path: str, *, method: str = "GET",
                  data: str | None = None,
                  timeout: float = PROBE_TIMEOUT_S) -> tuple[int | None, str]:
    """`(status_code, body)` for an AUTHENTICATED call to the LOCAL service container's own API.

    The third vantage point (see the module docstring), and the only one that always works for admin calls:
    the container joins the service container's network namespace, so it addresses the API on the
    container-internal port. Neither a missing host port forward (measured absent on Colima, netctl#996) nor
    a misconfigured NEXUS_URL can break it, and it needs no reachable base URL at all - which is why it is
    only available while the container RUNS, exactly when there is a blob store to size or a repository to
    configure. The credential and the body both travel on STDIN as a curl config, never in argv."""
    argv = _curl_argv(cfg, f"{SERVICE_API_BASE}{path}", timeout, netns_of=cfg.container,
                      authenticated=True, method=method)
    try:
        res = run(argv, input_text=curl_stdin_config(password, data))
    except Exception:
        return None, ""
    return parse_curl_answer(res.out)


def _inspect_container(cfg: NexusConfig) -> ContainerVerdict:
    """The container verdict off `docker inspect`. The health branch is guarded in the template because an
    image without a healthcheck has no .State.Health and go-template would fail the whole call."""
    res = run(["docker", "inspect", "-f",
               "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
               cfg.container])
    return parse_container_state(res.out if res.ok else "")


def _compose(cfg: NexusConfig, *args: str) -> int:
    """`docker compose -f <the product's compose file> <args>`, streamed."""
    if not cfg.compose_file.exists():
        log.die(f"no Nexus compose file at {cfg.compose_file}")
    return run(["docker", "compose", "-f", str(cfg.compose_file), *args], capture=False).rc


# --- commands ----------------------------------------------------------------------------------------

def up(cfg: NexusConfig) -> int:
    """Start the Nexus service. Long-lived by design: leave it running rather than starting it per build."""
    _require_docker()
    log.info(f"starting the Nexus artefact proxy ({cfg.compose_file.name}); boot took 23 s in the local "
             f"measurement")
    if _compose(cfg, "up", "-d") != 0:
        log.die("docker compose up failed for the Nexus service")
    log.ok(f"Nexus starting. Check it with `{cfg.group_command} status` - a GREEN container can still serve "
           f"403 until the EULA is accepted at {api_base(cfg)}")
    return 0


def down(cfg: NexusConfig) -> int:
    """Stop the Nexus service. The `nexus-data` volume is the SERVICE's state (repositories, config,
    cached artefacts), not build state, so it deliberately survives: dropping it means re-accepting the
    EULA and re-creating every repository."""
    _require_docker()
    log.info("stopping the Nexus artefact proxy (the nexus-data volume is kept)")
    if _compose(cfg, "down") != 0:
        log.die("docker compose down failed for the Nexus service")
    log.ok("Nexus stopped; nexus-data volume retained")
    return 0


def _blob_store_report(cfg: NexusConfig, container_running: bool) -> list[str]:
    """The blob-store lines for `status` (netctl#994), or nothing at all when there is no local service to
    size.

    Skipped entirely for a stopped or absent container: the blob store is read through the container's own
    API (the only vantage point that reliably works for an admin call), and a remote Nexus' blob store is
    not this host's disk problem, which is the problem netctl#994 is about."""
    if not container_running:
        return []
    password = _admin_password(cfg, required=False)
    if not password:
        return blob_store_lines(cfg, None, credentials=False)
    code, body = _service_curl(cfg, password, BLOB_STORES_API_PATH)
    return blob_store_lines(cfg, code, parse_blob_stores(body))


def status(cfg: NexusConfig) -> int:
    """Report the honest state: container state + health, reachability from BOTH the operator's shell and a
    build container (netctl#996), whether the two mandatory manual steps (EULA acceptance, anonymous read)
    are done - because a healthy container that answers 403 is the failure mode people hit - and how large
    the blob store has grown (netctl#994). Exits non-zero unless an anonymous read really succeeds AND a
    build container can reach the base."""
    _require_docker()
    base = api_base(cfg)
    container = _inspect_container(cfg)
    # BOTH vantage points, always: they disagree on a VM-hosted daemon, and which one is right depends on
    # what the reader is asking. One extra container start (~200 ms) on a command a human runs by hand.
    # The probed URL is a CONTENT fetch, not a listing: a listing answers 200 on an instance that serves
    # nothing at all (measured). The host keeps the shorter timeout on purpose - it is the courtesy line,
    # while the container answer is the one the verdict rests on.
    content_url = f"{base}{cfg.content_probe_path}"
    host_answer = _http_probe(content_url)
    build_answer = _container_http_probe(cfg, content_url)
    code, body = effective_answer(host_answer, build_answer)
    verdict = service_verdict(cfg, code, body)
    # WHAT is configured is a SECOND question, asked only once the content probe proved the instance really
    # serves, and asked from the vantage point that answered. It stays a caveated CONFIGURATION listing.
    repositories: tuple[str, ...] = ()
    if verdict.serving:
        listing_url = f"{base}{REPOSITORIES_API_PATH}"
        listing = (_http_probe(listing_url) if build_answer[0] is None
                   else _container_http_probe(cfg, listing_url))
        repositories = repository_names(listing[1])
    lines = status_lines(cfg, container, verdict, base, repositories)
    lines += reachability_lines(cfg, host_answer[0], build_answer[0], base)
    lines += _blob_store_report(cfg, container.running)
    for line in lines:
        print(line)
    return status_rc(container, verdict, build_reachable=build_answer[0] is not None)


def _admin_password(cfg: NexusConfig, required: bool = True) -> str:
    """The admin password for `repos`/`cleanup`/the blob-store reading, read from the container's generated
    file and falling back to NEXUS_ADMIN_PASSWORD (Nexus DELETES that file once the password has been
    changed, so its absence is normal, not an error). Never taken from a CLI argument: an argv credential is
    visible in `ps` and lands in shell history.

    `required=False` returns "" instead of dying, for the READ-ONLY blob-store reading in `status`: a status
    command must stay runnable without credentials and report what it could not measure, rather than abort
    halfway through its own output."""
    res = run(["docker", "exec", cfg.container, "cat", ADMIN_PASSWORD_FILE])
    if res.ok and res.out.strip():
        return res.out.strip()
    from_env = (os.environ.get(ADMIN_PASSWORD_ENV_VAR) or "").strip()
    if from_env:
        return from_env
    if not required:
        return ""
    log.die(f"no admin password: {ADMIN_PASSWORD_FILE} is gone (normal once it has been changed) and "
            f"{ADMIN_PASSWORD_ENV_VAR} is unset. Export it from your password store and re-run")
    return ""


def repos(cfg: NexusConfig) -> int:
    """Create the proxy repositories the product needs (its create-repositories.sh).

    The password is handed over through the ENVIRONMENT, never through argv: the script itself reads it
    via `curl -K -` on stdin for the same reason, and putting it on a command line would undo that. It is
    exported into this process so the child inherits it, which keeps it out of `ps` and out of history.
    Requires the EULA to be accepted first - without it every create answers 403."""
    _require_docker()
    if not cfg.repositories_script.exists():
        log.die(f"no repository-provisioning script at {cfg.repositories_script}")
    base = api_base(cfg)
    log.info(f"creating the {cfg.cli} proxy repositories on {base} ({cfg.repositories_script.name})")
    os.environ[NEXUS_URL_ENV_VAR] = base
    os.environ[ADMIN_PASSWORD_ENV_VAR] = _admin_password(cfg)
    rc = run(["sh", str(cfg.repositories_script)], capture=False).rc
    if rc != 0:
        log.die("create-repositories.sh failed (is the EULA accepted? without it every create answers 403)")
    log.ok("repository provisioning finished (an existing repository reports `exists`, it is not overwritten)")
    return 0


def _set_policy(cfg: NexusConfig, password: str, fmt: str, days: int) -> bool:
    """Create the cleanup policy for one format, or UPDATE it when the name is already taken. Returns
    whether the policy now says what it should."""
    body = policy_body(cfg, fmt, days)
    post_code, _ = _service_curl(cfg, password, CLEANUP_POLICIES_API_PATH, method="POST", data=body)
    put_code: int | None = None
    if post_code == 400:  # measured: "Name is already used" - an existing policy is an UPDATE, not an error
        put_code, _ = _service_curl(cfg, password,
                                    f"{CLEANUP_POLICIES_API_PATH}/{policy_name(cfg, fmt)}",
                                    method="PUT", data=body)
    ok, outcome = policy_verdict(post_code, put_code)
    (log.ok if ok else log.warn)(f"policy {policy_name(cfg, fmt)} ({fmt}, {days} days): {outcome}")
    return ok


def _attach_policy(cfg: NexusConfig, password: str, repo: ProxyRepository) -> bool:
    """Attach the format's policy to one proxy repository by read-modify-write, the only route Nexus offers
    (a policy cannot claim its repositories). Returns whether the repository is now covered; a repository
    that does not exist is SKIPPED rather than failed, so this command works on a partially provisioned
    instance."""
    path = f"{REPOSITORIES_API_PATH}/{repo.api_segment}/proxy/{repo.name}"
    get_code, repo_body = _service_curl(cfg, password, path)
    if get_code == 404:
        log.info(f"repository {repo.name}: absent, skipped (create it with `{cfg.group_command} repos`)")
        return True
    if get_code != 200:
        log.warn(f"repository {repo.name}: cannot read its configuration "
                 f"({'HTTP ' + str(get_code) if get_code else 'no answer'}), left untouched")
        return False
    patched, outcome = cleanup_patch(repo_body, policy_name(cfg, repo.fmt))
    if outcome == "already":
        log.ok(f"repository {repo.name}: {policy_name(cfg, repo.fmt)} already attached")
        return True
    if patched is None:
        log.warn(f"repository {repo.name}: its configuration did not read as JSON, left untouched rather "
                 f"than PUT back a body nothing understood")
        return False
    put_code, put_body = _service_curl(cfg, password, path, method="PUT", data=patched)
    if put_code == 204:  # measured: a repository update answers 204, not 200
        log.ok(f"repository {repo.name}: {policy_name(cfg, repo.fmt)} attached")
        return True
    log.warn(f"repository {repo.name}: attaching {policy_name(cfg, repo.fmt)} failed "
             f"({'HTTP ' + str(put_code) if put_code else 'no answer'}) {put_body[:200]}")
    return False


def cleanup(cfg: NexusConfig) -> int:
    """Set Nexus' own cleanup policies on the product's proxy repositories, so the blob store stops growing
    unbounded (netctl#994).

    THE FORMAT-AWARE RECLAIM, and deliberately the only one offered. The blob store sits on the same
    filesystem as the builds and the lab containers, nothing prunes it (the disk guard must not, `clean`
    must not), and the blunt alternative - removing the volume - throws away the entire cache and sends every
    build back to the rate-limited origins. A last-downloaded policy drops what nobody has asked for in a
    month and keeps everything still in use.

    IDEMPOTENT, and it does not fight the operator: an existing policy is updated (so the retention window
    can be changed by re-running with NEXUS_CLEANUP_DAYS), an already attached policy performs no write at
    all, and the attachment is a UNION so a policy someone else added survives. It CONFIGURES only - the
    deletion is performed by the `Cleanup service` task Nexus already ships enabled, and the dry run at the
    end reports what that task would actually delete, without deleting anything."""
    _require_docker()
    container = _inspect_container(cfg)
    if not container.running:
        log.die(f"container {cfg.container} is not running (start it with `{cfg.group_command} up`): the "
                f"cleanup policies are configured through the service's own API")
    password = _admin_password(cfg)
    days = cleanup_days()
    log.info(f"setting cleanup policies on the {cfg.cli} proxy repositories: delete what has not been "
             f"DOWNLOADED for {days} days (override with {CLEANUP_DAYS_ENV_VAR})")
    ok = True
    for fmt in cleanup_formats(cfg):
        ok = _set_policy(cfg, password, fmt, days) and ok
    for repo in cfg.proxy_repositories:
        ok = _attach_policy(cfg, password, repo) and ok
    log.info(f"dry run: what the shipped `{CLEANUP_TASK_NAME}` task ({CLEANUP_TASK_TYPE}) would delete on "
             f"its next run. It is already enabled, so nothing needs scheduling here")
    for repo in cfg.proxy_repositories:
        code, body = _service_curl(cfg, password, CLEANUP_RUN_API_PATH, method="POST",
                                   data=json.dumps({"repository": repo.name, "dryRun": True},
                                                   separators=(",", ":")))
        print(f"  {dry_run_line(repo.name, code, body)}")
    if not ok:
        log.die("some cleanup policies could not be set (see the warnings above); the blob store is still "
                "growing unobserved for those repositories")
    log.ok(f"cleanup policies in place ({days} days since last download); check the blob-store size with "
           f"`{cfg.group_command} status`")
    return 0


def dispatch(member: str | None, cfg: NexusConfig | None = None) -> int:
    """Run one group member, or list them when called bare. Pure group logic: no bare-group default
    action, and an unknown member fails loudly instead of falling back to one."""
    resolved = cfg or config()
    if not member:
        for line in member_listing(resolved):
            print(line)
        return 0
    action = {"up": up, "down": down, "status": status, "repos": repos, "cleanup": cleanup}.get(member)
    if action is None:
        log.die(unknown_member_message(member))
    return action(resolved)
