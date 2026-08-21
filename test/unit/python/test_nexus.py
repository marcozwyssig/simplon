"""Unit tests for the `nexus` group's PURE decisions (#948, #994, #996): where the API is addressed, how a
docker inspect line and an HTTP answer are classified, what `status` is allowed to claim, how the two
reachability vantage points are reported, and how the blob store and the cleanup policies are decided. No
docker, no network, no subprocess; AAA throughout, negative cases included.

The load-bearing case here is a NEGATIVE one: a GREEN container that answers 403 or 401 is a FAILURE, not
a success, because Nexus serves no ARTEFACT until its EULA is accepted and none anonymously until anonymous
read is switched on. And the sharper form of it, measured on a virgin instance on 2026-08-05: a repository
LISTING answers 200 in both of those states, so only a real content fetch may decide `serving`. The
service_verdict block below carries the full matrix.

The #996 group has a second one: the operator's shell and a build container disagree on a VM-hosted docker
daemon (measured 2026-08-05: the shell reached NEITHER candidate URL while a build container got 200), so
no single verdict is honest and the report must carry both.

The #994 group has a third: nothing may claim a size it did not measure, and nothing may suggest reclaiming
the blob store by removing its volume.

Every product token in the report comes from the manifest, so the fixture below deliberately names a
product that is NOT netctl: a report that still read `netctl` anywhere would be a hardcoded product name
this move exists to remove. Which repositories a PARTICULAR product declares, and whether its declaration
agrees with its own create-repositories.sh, is a product-side test.
"""
import json
from pathlib import Path

import pytest

from delivery import nexus

# The product DATA a manifest supplies, as one fixture value the pure decisions are asked with. `democtl`
# rather than `netctl` on purpose (see the module docstring), and the two maven2 repositories are kept
# because the format-scoped cleanup policy has to collapse them onto one.
CFG = nexus.NexusConfig(
    cli="democtl",
    container="democtl-nexus",
    volume="sonatype_nexus-data",
    compose_file=Path("/repo/deploy/provision/sonatype/docker-compose.yml"),
    repositories_script=Path("/repo/deploy/provision/sonatype/create-repositories.sh"),
    base_url_env="DEMOCTL_NEXUS_URL",
    http_port="8181",
    probe_image="gradle:jdk25",
    content_probe_path="/repository/maven-public/org/apiguardian/apiguardian-api/1.1.2/"
                       "apiguardian-api-1.1.2.pom",
    proxy_repositories=(
        nexus.ProxyRepository("maven-central", "maven2", "maven"),
        nexus.ProxyRepository("gradle-plugins-proxy", "maven2", "maven"),
        nexus.ProxyRepository("npm-proxy", "npm", "npm"),
    ),
)

_MANIFEST = {
    "nexus": {
        "cli": "democtl",
        "container": "democtl-nexus",
        "volume": "sonatype_nexus-data",
        "compose_file": "deploy/provision/sonatype/docker-compose.yml",
        "repositories_script": "deploy/provision/sonatype/create-repositories.sh",
        "base_url_env": "DEMOCTL_NEXUS_URL",
        "http_port": "8181",
        "probe_image": "gradle:jdk25",
        "content_probe_path": CFG.content_probe_path,
        "proxy_repositories": [
            {"name": "maven-central", "format": "maven2", "api": "maven"},
            {"name": "npm-proxy", "format": "npm", "api": "npm"},
        ],
    }
}


# --- declared (the manifest is the ONLY source of product knowledge) ---------------------------------

def test_declared_reads_the_product_data_from_the_manifest_section():
    # arrange / act
    cfg = nexus.declared(_MANIFEST, Path("/repo"))

    # assert: nothing is derived from a product import, and the two file keys are resolved under the root
    assert (cfg.cli, cfg.container, cfg.base_url_env) == ("democtl", "democtl-nexus", "DEMOCTL_NEXUS_URL")
    assert cfg.compose_file == Path("/repo/deploy/provision/sonatype/docker-compose.yml")
    assert [(r.name, r.fmt, r.api_segment) for r in cfg.proxy_repositories] == [
        ("maven-central", "maven2", "maven"), ("npm-proxy", "npm", "npm")]


def test_declared_labels_its_errors_with_the_source_the_caller_names():
    # arrange: `config` passes the manifest path, so the message points at a file on a multi-product host
    # act / assert
    with pytest.raises(ValueError, match="/tmp/other.yaml: the 'nexus' section is missing"):
        nexus.declared({}, Path("/repo"), source="/tmp/other.yaml")


def test_declared_refuses_a_section_that_declares_no_proxy_repository():
    # arrange: an empty list would make `cleanup` report success while the blob store keeps growing
    data = {"nexus": dict(_MANIFEST["nexus"], proxy_repositories=[])}

    # act / assert
    with pytest.raises(ValueError, match="declares none"):
        nexus.declared(data, Path("/repo"))


def test_declared_refuses_a_repository_that_names_no_api_segment():
    # arrange: `format` and `api` differ for maven only, which is exactly the detail that makes a guessed
    # URL 404 silently - so a missing one must fail here, not at the first PUT
    data = {"nexus": dict(_MANIFEST["nexus"],
                          proxy_repositories=[{"name": "maven-central", "format": "maven2"}])}

    # act / assert
    with pytest.raises(ValueError, match="'name', 'format' and 'api'"):
        nexus.declared(data, Path("/repo"))


def test_declared_refuses_a_rest_listing_as_the_content_probe():
    # arrange: THE structural guard against reintroducing "a listing means it works". A listing answers 200
    # on a virgin instance that serves nothing at all, so it may never decide `serving`
    data = {"nexus": dict(_MANIFEST["nexus"], content_probe_path=nexus.REPOSITORIES_API_PATH)}

    # act / assert
    with pytest.raises(ValueError, match="must be a CONTENT path"):
        nexus.declared(data, Path("/repo"))


# --- api_base (where status/repos talk) --------------------------------------------------------------

def test_api_base_defaults_to_localhost_on_the_published_port():
    # arrange: nothing configured. Container-internal 8081 is published as 8181 because host 8081 is taken
    # by netctl's own portal and the dev lab publishes 8080-8083
    env = {}

    # act / assert
    assert nexus.api_base(CFG, env) == "http://localhost:8181"


def test_api_base_follows_an_overridden_published_port():
    # arrange: the compose file's NEXUS_HTTP_PORT override, as a second instance on one host needs
    env = {"NEXUS_HTTP_PORT": "9181"}

    # act / assert
    assert nexus.api_base(CFG, env) == "http://localhost:9181"


def test_api_base_prefers_an_explicit_nexus_url_over_the_client_base():
    # arrange: both set. NEXUS_URL is what the shipped create-repositories.sh already reads, so it wins
    env = {"NEXUS_URL": "http://admin.lan:8181/", CFG.base_url_env: "http://nexus.lan:8181"}

    # act / assert: and the trailing slash is normalised away so no probe URL carries a `//`
    assert nexus.api_base(CFG, env) == "http://admin.lan:8181"


def test_api_base_falls_back_to_the_client_side_base_url():
    # arrange: only the build-side knob set - it names the same instance, so guessing localhost instead
    # would probe the wrong machine
    env = {CFG.base_url_env: "http://nexus.lan:8181"}

    # act / assert
    assert nexus.api_base(CFG, env) == "http://nexus.lan:8181"


# --- parse_container_state --------------------------------------------------------------------------

def test_parse_container_state_reads_the_state_and_health_pair():
    # arrange: the `<state>|<health>` docker inspect template output
    text = "running|healthy\n"

    # act
    verdict = nexus.parse_container_state(text)

    # assert
    assert (verdict.present, verdict.state, verdict.health) == (True, "running", "healthy")
    assert verdict.running is True


def test_parse_container_state_treats_empty_output_as_an_absent_container():
    # arrange: docker inspect on a container that does not exist fails with empty stdout. `status` must be
    # runnable BEFORE the first `nexus up`, so this is a legitimate state and not an error
    text = ""

    # act
    verdict = nexus.parse_container_state(text)

    # assert
    assert verdict.present is False
    assert verdict.running is False


def test_parse_container_state_reports_a_stopped_container_as_not_running():
    # arrange: the container exists but is stopped (a `nexus down` earlier, or a crash)
    text = "exited|none"

    # act
    verdict = nexus.parse_container_state(text)

    # assert: present, but not running - the two are different facts and both are reported
    assert verdict.present is True
    assert verdict.running is False


def test_parse_container_state_defaults_a_missing_health_field_to_none():
    # arrange: an image without a healthcheck yields an empty health half rather than a word
    text = "running|"

    # act / assert: "none", never an empty string that reads as a missing line in the report
    assert nexus.parse_container_state(text).health == "none"


# --- service_verdict (the failure mode people actually hit) ------------------------------------------
#
# THE PROBE IS A CONTENT FETCH, NOT A LISTING, and these tests pin why. Measured against a VIRGIN throwaway
# 3.94.1 instance on 2026-08-05:
#
#   EULA | anon read | anonymous LISTING       | anonymous CONTENT fetch
#   -----|-----------|-------------------------|------------------------------
#   no   | off       | 200 []                  | 401
#   no   | ON        | 200 with the FULL list  | 403 + the EULA body
#   yes  | ON        | 200 with the full list  | 200 (or 404)
#
# A 200 listing therefore proves NOTHING - the EULA gate sits on the /repository/... content path only, and
# the listing answers 200 to admin while the EULA is unaccepted as well. Classifying the listing reported a
# green, "serving" proxy on an instance that served nothing at all.

def test_the_serving_probe_is_a_content_fetch_and_not_a_repository_listing():
    # arrange / act: the one structural guard against reintroducing "a listing means it works"
    path = CFG.content_probe_path

    # assert: a real artefact under /repository/..., and NOT the REST listing endpoint. That it is also the
    # URL the BUILD resolves through is a PRODUCT assertion - only the product knows which repository its
    # gradle/npm/pip wiring points at - so it is a test in the product repo, next to that wiring
    assert path.startswith("/repository/")
    assert nexus.REPOSITORIES_API_PATH not in path


def test_service_verdict_calls_only_a_real_anonymous_content_fetch_serving():
    # arrange: an artefact really came back (verified 200 / 1526 bytes on the live instance). This is the
    # ONLY answer that proves the proxy serves
    code, body = 200, "<project>...</project>"

    # act
    verdict = nexus.service_verdict(CFG, code, body)

    # assert
    assert (verdict.serving, verdict.eula_accepted, verdict.anonymous_read) == (True, True, True)
    assert "CONTENT fetch" in verdict.reason


def test_service_verdict_names_the_unaccepted_eula_behind_a_403():
    # arrange: the measured answer of a fresh instance on the CONTENT path - no artefact is served in this
    # state, not even to admin, while the repository listing happily answers 200
    code = 403
    body = ("You must accept the End User License Agreement (EULA) through the onboarding wizard or "
            "REST API before proceeding.")

    # act
    verdict = nexus.service_verdict(CFG, code, body)

    # assert: a hard NO on the EULA. anonymous read is proven ON, because reaching the EULA gate at all
    # means the request got PAST the auth check (measured: with anonymous read off the same call gives 401)
    assert verdict.serving is False
    assert verdict.eula_accepted is False
    assert verdict.anonymous_read is True
    assert "EULA" in verdict.reason


def test_service_verdict_says_a_listing_still_answers_200_in_the_eula_state():
    # arrange: the trap is worth stating in the operator-facing reason, not only in a comment - a reader who
    # checks the listing by hand will see 200 and conclude the opposite
    verdict = nexus.service_verdict(CFG, 403, "You must accept the End User License Agreement (EULA)")

    # act / assert
    assert "LISTING still answers 200" in verdict.reason


def test_service_verdict_reports_a_403_without_an_eula_hint_as_unknown():
    # arrange: a 403 that is NOT the EULA one - diagnosing it as an unaccepted EULA would be fabrication
    code, body = 403, "Access denied"

    # act
    verdict = nexus.service_verdict(CFG, code, body)

    # assert
    assert verdict.serving is False
    assert verdict.eula_accepted is None


def test_service_verdict_flags_disabled_anonymous_read_behind_a_401():
    # arrange: this version's default, measured on the content path of a virgin instance
    code = 401

    # act
    verdict = nexus.service_verdict(CFG, code, "")

    # assert
    assert verdict.serving is False
    assert verdict.anonymous_read is False


def test_service_verdict_does_not_claim_the_eula_is_accepted_behind_a_401():
    # arrange: THE regression this pins. The two gates are ORDERED - an unauthenticated caller is rejected
    # BEFORE the EULA is consulted (measured: a virgin instance with anonymous read off answers 401 on the
    # content path, and only 403+EULA once anonymous read is on), so a 401 says NOTHING about the EULA
    verdict = nexus.service_verdict(CFG, 401, "")

    # assert
    assert verdict.eula_accepted is None
    assert "says nothing about the EULA" in verdict.reason


def test_service_verdict_reports_a_404_as_past_both_gates_but_not_serving():
    # arrange: measured live - the same pom answered 404 through `maven-central` while the `maven-public`
    # group served it. A cold cache whose remote did not supply it is the negative-cache trap, and it is
    # NOT a healthy proxy
    verdict = nexus.service_verdict(CFG, 404, "")

    # assert: both prerequisites are past (the call got through them), but nothing is served
    assert verdict.serving is False
    assert (verdict.eula_accepted, verdict.anonymous_read) == (True, True)
    assert "negative-cache trap" in verdict.reason


def test_service_verdict_does_not_guess_which_of_the_two_404_causes_it_is():
    # arrange: a missing artefact and a missing repository both answer 404 (measured: 1429 vs 1344 byte
    # bodies, same status), so naming one would be a fabricated diagnosis
    verdict = nexus.service_verdict(CFG, 404, "")

    # act / assert: both are named as possibilities, neither is claimed
    assert "cache is cold" in verdict.reason
    assert "repository does not exist" in verdict.reason
    assert "neither is claimed" in verdict.reason


def test_service_verdict_reports_no_http_answer_as_not_up():
    # arrange: nothing answered at all (not started, still booting, or not published on this port)
    code = None

    # act
    verdict = nexus.service_verdict(CFG, code, "")

    # assert: nothing is claimed about either prerequisite - the answer does not say
    assert verdict.serving is False
    assert verdict.eula_accepted is None
    assert verdict.anonymous_read is None


def test_service_verdict_does_not_guess_a_cause_for_an_unexpected_status():
    # arrange: e.g. a reverse proxy in front returning 502
    code = 502

    # act
    verdict = nexus.service_verdict(CFG, code, "")

    # assert
    assert verdict.serving is False
    assert "502" in verdict.reason


# --- repository_names -------------------------------------------------------------------------------

def test_repository_names_reads_the_listing():
    # arrange: the shape of the repositories API answer
    body = '[{"name":"npm-proxy","format":"npm"},{"name":"pypi-proxy","format":"pypi"}]'

    # act / assert
    assert nexus.repository_names(body) == ("npm-proxy", "pypi-proxy")


def test_repository_names_degrades_to_empty_on_a_body_it_cannot_parse():
    # arrange: an HTML error page from a proxy in front, not the JSON listing. `status` must not traceback
    body = "<html>502 Bad Gateway</html>"

    # act / assert
    assert nexus.repository_names(body) == ()


def test_repository_names_ignores_entries_without_a_name():
    # arrange: a defensive case - a listing entry that is not the expected object
    body = '[{"format":"npm"}, "npm-proxy", {"name":"pypi-proxy"}]'

    # act / assert
    assert nexus.repository_names(body) == ("pypi-proxy",)


# --- status_lines / status_rc (what the command may claim) -------------------------------------------

def test_status_rc_fails_a_green_container_that_does_not_actually_serve():
    # arrange: THE case this command exists for - the container runs and its healthcheck is green, but the
    # EULA is unaccepted so every repository answers 403
    container = nexus.ContainerVerdict(present=True, state="running", health="healthy")
    service = nexus.service_verdict(CFG, 403, "accept the End User License Agreement (EULA)")

    # act / assert: non-zero, because "healthy" is not "usable"
    assert nexus.status_rc(container, service) == 1


def test_status_rc_is_zero_only_when_the_container_runs_and_an_anonymous_read_succeeds():
    # arrange: fully provisioned
    container = nexus.ContainerVerdict(present=True, state="running", health="healthy")
    service = nexus.service_verdict(CFG, 200, "<project>...</project>")

    # act / assert
    assert nexus.status_rc(container, service) == 0


def test_status_rc_fails_when_the_container_is_absent():
    # arrange: nothing started yet, but something else answers on the port (a stale tunnel, another host)
    container = nexus.ContainerVerdict(present=False, state="", health="none")
    service = nexus.service_verdict(CFG, 200, "<project>...</project>")

    # act / assert: a serving URL that is not THIS service is not a pass
    assert nexus.status_rc(container, service) == 1


def test_status_lines_point_at_the_bring_up_command_when_the_container_is_absent():
    # arrange: a first run before `nexus up`
    container = nexus.ContainerVerdict(present=False, state="", health="none")
    service = nexus.service_verdict(CFG, None, "")

    # act
    lines = nexus.status_lines(CFG, container, service, "http://localhost:8181")

    # assert
    assert any("absent" in line and "nexus up" in line for line in lines)


def test_status_lines_report_both_prerequisites_from_the_eula_answer():
    # arrange: the EULA 403 on the CONTENT path. It reports both facts, and both are measured: the EULA is a
    # hard NO, and anonymous read is a YES because the request reached the EULA gate at all (with anonymous
    # read off the same call is rejected earlier, with 401)
    container = nexus.ContainerVerdict(present=True, state="running", health="healthy")
    service = nexus.service_verdict(CFG, 403, "accept the End User License Agreement (EULA)")

    # act
    lines = nexus.status_lines(CFG, container, service, "http://localhost:8181")

    # assert
    assert any(line.startswith("eula accepted: NO") for line in lines)
    assert any(line.startswith("anonymous read: yes") for line in lines)


def test_status_lines_report_an_unknown_prerequisite_as_unknown():
    # arrange: a 403 that is NOT the EULA one says nothing about either prerequisite, and reporting those
    # Nones as "no" would be a fabricated diagnosis
    container = nexus.ContainerVerdict(present=True, state="running", health="healthy")
    service = nexus.service_verdict(CFG, 403, "Access denied")

    # act
    lines = nexus.status_lines(CFG, container, service, "http://localhost:8181")

    # assert
    assert any(line.startswith("eula accepted: unknown") for line in lines)
    assert any(line.startswith("anonymous read: unknown") for line in lines)


def test_status_lines_never_claim_a_listed_repository_serves():
    # arrange: repositories exist, but presence is NOT proof - a proxy answers 404 while its upstream
    # rate-limits, and Nexus remembers that 404 for 24 h by default. Observed exactly that on maven-public
    # during the 2026-08-04 429 window, on a repository that serves correctly now
    container = nexus.ContainerVerdict(present=True, state="running", health="healthy")
    service = nexus.service_verdict(CFG, 200, "<project>...</project>")

    # act
    lines = nexus.status_lines(CFG, container, service, "http://localhost:8181",
                               ("maven-public", "npm-proxy"))

    # assert: the repositories are reported as PRESENT, with the caveat, and nothing is called working
    report = "\n".join(lines)
    assert "repositories present (2): maven-public, npm-proxy" in report
    assert "not a repository SERVING" in report
    assert "CONFIGURATION, not a fetch" in report


def test_status_lines_omit_the_repository_caveat_when_nothing_is_listed():
    # arrange: no listing available (the 401/403 paths) - a caveat about an empty list is noise
    container = nexus.ContainerVerdict(present=True, state="running", health="healthy")
    service = nexus.service_verdict(CFG, 401, "")

    # act
    lines = nexus.status_lines(CFG, container, service, "http://localhost:8181")

    # assert
    assert not any("repositories present" in line for line in lines)


# --- #996 parse_curl_answer (the container probe keeps the BODY) -------------------------------------

def test_parse_curl_answer_splits_the_tagged_status_code_from_the_body():
    # arrange: what `curl -o - -w '\n<marker>%{http_code}'` writes - the body, then the tagged code
    text = f'[{{"name":"npm-proxy"}}]\n{nexus.CURL_CODE_MARKER}200'

    # act
    code, body = nexus.parse_curl_answer(text)

    # assert: the body survives intact, which is the whole reason this probe is not `-o /dev/null`
    assert code == 200
    assert body == '[{"name":"npm-proxy"}]'


def test_parse_curl_answer_keeps_an_error_body_that_ends_in_digits():
    # arrange: THE reason the code is tagged and not read off the last line - an error body can end in
    # digits itself, and a positional parse would report the body's own number as the status
    text = f"upstream said 429\n{nexus.CURL_CODE_MARKER}403"

    # act
    code, body = nexus.parse_curl_answer(text)

    # assert
    assert code == 403
    assert body == "upstream said 429"


def test_parse_curl_answer_maps_curls_zero_code_to_no_answer():
    # arrange: curl writes 000 when it never got an answer (DNS failure, connection refused)
    text = f"\n{nexus.CURL_CODE_MARKER}000"

    # act
    code, _ = nexus.parse_curl_answer(text)

    # assert: the same "no answer at all" the host probe reports, never a status code of 0
    assert code is None


def test_parse_curl_answer_treats_output_without_the_marker_as_no_answer():
    # arrange: the probe could not even run (no docker binary, image missing), so docker's own error is
    # all there is - it must not be mistaken for an HTTP answer
    text = "docker: Cannot connect to the Docker daemon"

    # act / assert
    assert nexus.parse_curl_answer(text) == (None, "")


# --- #996 effective_answer / reachability_lines ------------------------------------------------------

def test_effective_answer_classifies_the_build_containers_answer_when_the_shell_got_none():
    # arrange: the measured Colima case - the shell reaches nothing, the build container gets the EULA 403
    host = (None, "")
    build = (403, "You must accept the End User License Agreement (EULA)")

    # act
    code, body = nexus.effective_answer(host, build)

    # assert: the diagnosis comes from the vantage point that ANSWERED, so the EULA body is not lost
    assert code == 403
    assert "EULA" in body


def test_effective_answer_falls_back_to_the_shell_when_no_container_answered():
    # arrange: a reachable host, an unreachable container (a `localhost` base URL)
    host = (200, "[]")
    build = (None, "")

    # act / assert
    assert nexus.effective_answer(host, build) == (200, "[]")


def test_reachability_lines_report_each_vantage_point_on_its_own_line():
    # arrange: the measured disagreement on this Colima host
    host_code, build_code = None, 200

    # act
    lines = nexus.reachability_lines(CFG, host_code, build_code, "http://172.17.0.1:8181")

    # assert: two separate honest statements, never one merged verdict
    assert f"reachable from {nexus.HOST_VANTAGE}: no (no answer)" in lines
    assert f"reachable from {nexus.BUILD_VANTAGE}: yes (HTTP 200)" in lines


def test_reachability_lines_say_the_builds_are_fine_when_only_the_shell_cannot_reach_it():
    # arrange: exactly the #996 complaint - `status` claimed a dead proxy while every build resolved
    # through it, because only the shell was asked
    lines = nexus.reachability_lines(CFG, None, 200, "http://172.17.0.1:8181")

    # act
    report = "\n".join(lines)

    # assert: it says the builds are fine, and it keeps the NEXUS_URL override hint
    assert "the BUILDS resolve through the proxy fine" in report
    assert "this is not a fault" in report
    assert nexus.NEXUS_URL_ENV_VAR in report


def test_reachability_lines_flag_the_opposite_disagreement_as_broken_builds():
    # arrange: the inverse, and it is NOT harmless - the shell reaches a `localhost` base that a container
    # resolves to itself, so every build silently resolves against the origins
    lines = nexus.reachability_lines(CFG, 200, None, "http://localhost:8181")

    # act
    report = "\n".join(lines)

    # assert: named as a real fault, with the address a build container can actually reach
    assert "resolves against the origins" in report
    assert "172.17.0.1" in report


def test_reachability_lines_add_no_note_when_both_vantage_points_agree():
    # arrange: both reach it - there is no disagreement to explain, and a note would be noise
    lines = nexus.reachability_lines(CFG, 200, 200, "http://172.17.0.1:8181")

    # act / assert
    assert len(lines) == 2
    assert not any(line.startswith("note:") for line in lines)


def test_status_rc_fails_when_a_build_container_cannot_reach_a_proxy_the_shell_can():
    # arrange: green container, the shell gets a serving 200, but no build container reaches it - the
    # builds are broken and it looks perfect from here, which is the case a single verdict hides
    container = nexus.ContainerVerdict(present=True, state="running", health="healthy")
    service = nexus.service_verdict(CFG, 200, "<project>...</project>")

    # act / assert
    assert nexus.status_rc(container, service, build_reachable=False) == 1


def test_status_rc_does_not_fail_on_an_unasked_build_vantage():
    # arrange: the default - an UNKNOWN build vantage must not invent a failure
    container = nexus.ContainerVerdict(present=True, state="running", health="healthy")
    service = nexus.service_verdict(CFG, 200, "<project>...</project>")

    # act / assert
    assert nexus.status_rc(container, service) == 0


# --- #994 blob store --------------------------------------------------------------------------------

def test_parse_blob_stores_reads_the_size_the_blob_count_and_the_free_space():
    # arrange: the live /v1/blobstores answer (2026-08-05)
    body = ('[{"softQuota":null,"name":"default","type":"File","unavailable":false,"blobCount":481,'
            '"totalSizeInBytes":85060857,"availableSpaceInBytes":33630093312}]')

    # act
    stores = nexus.parse_blob_stores(body)

    # assert
    assert len(stores) == 1
    assert (stores[0].name, stores[0].blob_count) == ("default", 481)
    assert (stores[0].total_bytes, stores[0].available_bytes) == (85060857, 33630093312)


def test_parse_blob_stores_degrades_to_empty_on_a_body_it_cannot_parse():
    # arrange: the 403 HTML/JSON error body an unauthenticated call gets. This rides along in a STATUS
    # report, so it must degrade, never traceback mid-output
    body = '{"message":"access denied"}'

    # act / assert: not a list -> no blob store, no exception
    assert nexus.parse_blob_stores(body) == ()


def test_format_bytes_uses_binary_units_so_it_matches_df_and_docker():
    # arrange / act / assert: the same base the numbers a reader compares this against use
    assert nexus.format_bytes(85060857) == "81.1 MiB"
    assert nexus.format_bytes(33630093312) == "31.3 GiB"
    assert nexus.format_bytes(512) == "512 B"


def test_blob_store_lines_report_the_size_and_the_free_space_under_it():
    # arrange: a real reading
    store = nexus.BlobStore(name="default", blob_count=481, total_bytes=85060857,
                            available_bytes=33630093312)

    # act
    report = "\n".join(nexus.blob_store_lines(CFG, 200, (store,)))

    # assert: the size AND the filesystem headroom, because the failure #994 is about is a full disk
    assert "blob store default: 81.1 MiB in 481 blobs" in report
    assert "31.3 GiB free on its filesystem" in report


def test_blob_store_lines_never_suggest_removing_the_volume():
    # arrange: THE negative case of #994 - the wrong reaction to a large number here is a volume rm, which
    # throws the whole cache away and sends every build back to the rate-limited origins
    store = nexus.BlobStore(name="default", blob_count=481, total_bytes=85060857,
                            available_bytes=33630093312)

    # act
    report = "\n".join(nexus.blob_store_lines(CFG, 200, (store,)))

    # assert: it names the disk guard and clean as deliberately leaving it, and points at the reclaim
    assert "never with a volume rm" in report
    assert "nexus cleanup" in report
    assert "SERVICE state" in report


def test_blob_store_lines_report_a_missing_credential_as_not_measured():
    # arrange: no admin password available at all (the generated file is gone, the env var unset)
    lines = nexus.blob_store_lines(CFG, None, credentials=False)

    # act
    report = "\n".join(lines)

    # assert: NOT REPORTED with the reason - never a fabricated 0 B for the one thing this measures
    assert "not reported" in report
    assert nexus.ADMIN_PASSWORD_ENV_VAR in report
    assert "0 B" not in report


def test_blob_store_lines_report_a_refused_credential_as_not_measured():
    # arrange: the endpoint is admin-only even with anonymous read on (measured: anonymous gets 403)
    report = "\n".join(nexus.blob_store_lines(CFG, 403))

    # act / assert
    assert "not reported" in report
    assert "admin-only" in report


def test_blob_store_lines_do_not_claim_a_reading_from_an_empty_listing():
    # arrange: a 200 that carried no blob store at all - reporting "0 B" would be a measurement nobody made
    report = "\n".join(nexus.blob_store_lines(CFG, 200, ()))

    # act / assert
    assert "not reported" in report


# --- #994 the disk guard warns and never acts -------------------------------------------------------

def test_volume_guard_note_warns_about_the_volume_the_guard_must_not_prune():
    # arrange: the disk is below the bar and a Nexus volume exists
    note = nexus.volume_guard_note(CFG, free_pct=9, min_free_pct=15, volume_present=True)

    # assert: it says the guard does NOT prune it, why, and what to do instead
    assert note is not None
    assert CFG.volume in note
    assert "does NOT prune" in note
    assert "nexus cleanup" in note


def test_volume_guard_note_is_silent_when_the_disk_is_not_actually_low():
    # arrange: plenty of room - a standing warning on every `up` would just be noise
    # act / assert
    assert nexus.volume_guard_note(CFG, free_pct=40, min_free_pct=15, volume_present=True) is None


def test_volume_guard_note_is_silent_on_a_host_that_has_no_nexus():
    # arrange: low disk, but no such volume - warning about a volume that does not exist is fabrication
    # act / assert
    assert nexus.volume_guard_note(CFG, free_pct=3, min_free_pct=15, volume_present=False) is None


def test_volume_guard_note_is_silent_when_the_free_space_is_unknown():
    # arrange: an unparseable df line - no verdict, so no warning
    # act / assert
    assert nexus.volume_guard_note(CFG, free_pct=None, min_free_pct=15, volume_present=True) is None


# --- #994 cleanup policies --------------------------------------------------------------------------

def test_cleanup_days_defaults_to_the_shipped_retention_window():
    # arrange: nothing configured
    env = {}

    # act / assert
    assert nexus.cleanup_days(env) == nexus.DEFAULT_CLEANUP_DAYS


def test_cleanup_days_follows_an_explicit_override():
    # arrange: an operator widening the window on a host with plenty of disk
    env = {nexus.CLEANUP_DAYS_ENV_VAR: "90"}

    # act / assert
    assert nexus.cleanup_days(env) == 90


def test_cleanup_days_refuses_a_zero_window_and_falls_back_to_the_default():
    # arrange: 0 days would delete artefacts the moment they stop being downloaded, i.e. exactly the
    # self-inflicted re-download this feature exists to avoid
    env = {nexus.CLEANUP_DAYS_ENV_VAR: "0"}

    # act / assert
    assert nexus.cleanup_days(env) == nexus.DEFAULT_CLEANUP_DAYS


def test_cleanup_days_ignores_a_non_numeric_override():
    # arrange: a typo must not become a criterion
    env = {nexus.CLEANUP_DAYS_ENV_VAR: "thirty"}

    # act / assert
    assert nexus.cleanup_days(env) == nexus.DEFAULT_CLEANUP_DAYS


def test_policy_name_is_stable_across_retention_changes():
    # arrange / act: the days live in the criteria, not in the name, so a re-run with a different window
    # UPDATES one policy instead of leaving a trail of them attached to the same repository
    name = nexus.policy_name(CFG, "maven2")

    # assert
    assert name == "democtl-maven2-lastdownload"
    assert "30" not in name


def test_cleanup_formats_collapses_the_two_maven_repositories_onto_one_policy():
    # arrange / act: a cleanup policy is FORMAT-scoped, and maven-central + gradle-plugins-proxy are both
    # maven2, so creating one policy per repository would create a duplicate
    formats = nexus.cleanup_formats(CFG)

    # assert: distinct, and every configured repository's format is covered
    assert len(formats) == len(set(formats))
    assert set(formats) == {repo.fmt for repo in CFG.proxy_repositories}


def test_policy_body_carries_the_last_downloaded_criterion_in_days_and_nothing_else():
    # arrange / act
    body = json.loads(nexus.policy_body(CFG, "npm", 45))

    # assert: exactly one criterion is set; the others stay null so the policy says one thing
    assert (body["format"], body["criteriaLastDownloaded"]) == ("npm", 45)
    assert body["criteriaLastBlobUpdated"] is None
    assert body["criteriaAssetRegex"] is None


def test_policy_verdict_treats_an_existing_policy_as_an_update_not_an_error():
    # arrange: the measured pair - POST answers 400 "Name is already used", PUT on the name answers 200
    # and really does change the criteria (verified 30 -> 45 days, read back)
    ok, outcome = nexus.policy_verdict(post_code=400, put_code=200)

    # assert
    assert ok is True
    assert outcome == "updated"


def test_policy_verdict_reports_a_failed_update_of_an_existing_policy_as_a_failure():
    # arrange: the name is taken but the update was refused, so the retention window is NOT what was asked
    # for - reporting "exists" as success would hide that
    ok, outcome = nexus.policy_verdict(post_code=400, put_code=403)

    # assert
    assert ok is False
    assert "403" in outcome


def test_policy_verdict_reports_no_answer_as_a_failure():
    # arrange: the API did not answer at all
    ok, outcome = nexus.policy_verdict(post_code=None)

    # assert
    assert ok is False
    assert "no answer" in outcome


def test_cleanup_patch_adds_the_policy_to_a_repository_that_has_none():
    # arrange: the live GET body of a proxy repository, whose `cleanup` key is null until something sets it
    repo_body = ('{"name":"npm-proxy","cleanup":null,'
                 '"negativeCache":{"enabled":true,"timeToLive":1},"format":"npm","type":"proxy"}')

    # act
    patched, outcome = nexus.cleanup_patch(repo_body, "democtl-npm-lastdownload")

    # assert: the policy is attached and NOTHING else in the configuration changed - a re-render of the
    # canonical body would silently undo an operator's raised negativeCache TTL
    assert outcome == "attach"
    parsed = json.loads(patched)
    assert parsed["cleanup"] == {"policyNames": ["democtl-npm-lastdownload"]}
    assert parsed["negativeCache"] == {"enabled": True, "timeToLive": 1}


def test_cleanup_patch_keeps_a_policy_someone_else_attached():
    # arrange: an operator's own policy is already on the repository. Replacing policyNames would silently
    # delete their retention rule
    repo_body = '{"name":"npm-proxy","cleanup":{"policyNames":["ops-own-policy"]}}'

    # act
    patched, outcome = nexus.cleanup_patch(repo_body, "democtl-npm-lastdownload")

    # assert: a UNION, in order
    assert outcome == "attach"
    assert json.loads(patched)["cleanup"]["policyNames"] == ["ops-own-policy", "democtl-npm-lastdownload"]


def test_cleanup_patch_is_a_no_op_when_the_policy_is_already_attached():
    # arrange: a re-run. It must perform no PUT at all, not an identical one
    repo_body = '{"name":"npm-proxy","cleanup":{"policyNames":["democtl-npm-lastdownload"]}}'

    # act
    patched, outcome = nexus.cleanup_patch(repo_body, "democtl-npm-lastdownload")

    # assert
    assert patched is None
    assert outcome == "already"


def test_cleanup_patch_refuses_to_put_back_a_body_it_could_not_read():
    # arrange: an HTML error page from a proxy in front instead of the repository configuration. PUTting a
    # guessed body would REPLACE the whole repository configuration
    repo_body = "<html>502 Bad Gateway</html>"

    # act
    patched, outcome = nexus.cleanup_patch(repo_body, "democtl-npm-lastdownload")

    # assert
    assert patched is None
    assert outcome == "unreadable"


def test_curl_stdin_config_keeps_the_credential_out_of_argv():
    # arrange / act: the credential travels as a `curl -K -` config on STDIN, the mechanism
    # create-repositories.sh established, because argv is visible in `ps` and lands in shell history
    config = nexus.curl_stdin_config("s3cret")

    # assert
    assert config == 'user = "admin:s3cret"\n'


def test_curl_stdin_config_escapes_a_body_containing_quotes_and_backslashes():
    # arrange: a JSON body is nothing but quotes, and curl's config syntax needs both escaped. Verified
    # against the live instance with exactly these two characters in the payload (HTTP 200, intact)
    config = nexus.curl_stdin_config("pw", '{"notes":"a \\" quote"}')

    # act / assert: every quote and backslash of the payload is escaped for the config parser
    assert 'data = "{\\"notes\\":\\"a \\\\\\" quote\\"}"' in config
    assert 'header = "Content-Type: application/json"' in config


def test_curl_stdin_config_escapes_a_password_containing_a_quote():
    # arrange: an operator-set NEXUS_ADMIN_PASSWORD may contain anything; an unescaped quote would end the
    # config value early and send a TRUNCATED password
    config = nexus.curl_stdin_config('we"ird')

    # act / assert
    assert config == 'user = "admin:we\\"ird"\n'


def test_dry_run_line_reports_how_many_components_would_be_deleted():
    # arrange: the live dryRun answer - it evaluates the attached policies synchronously and deletes
    # nothing (verified 2026-08-05)
    body = '{"repository":"npm-proxy","status":"COMPLETED","componentCount":17,"dryRun":true}'

    # act
    line = nexus.dry_run_line("npm-proxy", 200, body)

    # assert: a count, and named as what the shipped task WOULD do, never as something already done
    assert "17 component(s) would be deleted" in line
    assert nexus.CLEANUP_TASK_NAME in line


def test_dry_run_line_reports_an_absent_repository_as_nothing_to_evaluate():
    # arrange: a partially provisioned instance answers 404 for a repository `nexus repos` never created
    # act / assert: not an error - this command must work before every repository exists
    assert "absent" in nexus.dry_run_line("nodejs-proxy", 404, "")


def test_dry_run_line_does_not_invent_a_count_from_an_answer_without_one():
    # arrange: a 200 whose body is not the execution status (a proxy in front, a version change)
    line = nexus.dry_run_line("npm-proxy", 200, "<html>ok</html>")

    # act / assert
    assert "no componentCount" in line
    assert "would be deleted" not in line


# --- pure group logic -------------------------------------------------------------------------------

def test_member_listing_names_every_member():
    # arrange / act: the bare `netctl nexus` call lists its members; no default action shadows the group
    listing = "\n".join(nexus.member_listing(CFG))

    # assert
    for member in ("up", "down", "status", "repos", "cleanup"):
        assert f"  {member}" in listing


def test_unknown_member_fails_loudly_with_the_member_list():
    # arrange / act: a typo must never silently fall back to a default member
    message = nexus.unknown_member_message("statuss")

    # assert
    assert "statuss" in message
    assert "status" in message
