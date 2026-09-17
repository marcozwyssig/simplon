"""The git route and the backend the kernel ships (si#5, slice 3).

WHAT IS TESTED IS WHAT THE API MEASUREMENT COST. Every shape below was taken off a real Portainer before
it was written - the carrier `hausportainer` on 2026-09-15/16 - and the reason to pin them here is that
none of them is guessable from the documentation: that creating and redeploying are two DIFFERENT calls
with different bodies, that a public repository must be sent no authentication fields at all, and that
the Portainer the kernel installs answers only with TLS verification off.

No network: `_request` is the only place that opens one, and it is replaced.

AAA throughout.
"""
from __future__ import annotations

import ssl

import pytest

from simplon import backend, carrierspec, deployment, environments, portainer
from simplon.tasks import deploy as deploy_task

from conftest import Recorder

CARRIER = carrierspec.Carrier(
    name="hausportainer",
    proxmox=carrierspec.Proxmox(node="pve-2", kind="lxc"),
    portainer=carrierspec.Portainer(url_from="HAUS", endpoint=3, insecure=True),
)
REPOSITORY = environments.Repository(
    url="github.com/acme/app", ref="main", compose="deploy/docker-compose.yml")


@pytest.fixture
def target() -> portainer.PortainerTarget:
    return portainer.PortainerTarget(
        url="https://portainer.local", token="t", endpoint_id=3, stack_name="app-prod")


class Creating(Recorder):
    """A Portainer that has no such stack until it is created, and reports it up afterwards.

    The plain `Recorder` answers the same list every time, which cannot express the one thing the create
    path now depends on: that the stack EXISTS after the POST and has a status worth reading back.
    """

    def __init__(self, created: dict) -> None:
        super().__init__({"/stacks": []})
        self._created = created

    def __call__(self, target, method: str, path: str, body: dict | None = None) -> object:
        answer = super().__call__(target, method, path, body)
        if method == "POST":
            self.answers["/stacks"] = [self._created]
        return answer


def _sent(recorder: Recorder, method: str) -> tuple[str, str, dict]:
    """The one call that changed something, found by verb.

    Not `calls[-1]`: a deployment now READS THE OUTCOME BACK after writing it, so the last call is a GET
    and the interesting one is the write before it. That read-back is the point of si#5's last measurement
    and a test that indexed from the end would have hidden it.
    """
    return next(call for call in reversed(recorder.calls) if call[0] == method)


def _environment(**changes: object) -> environments.Environment:
    fields: dict = {"name": "prod", "backend": portainer.BACKEND, "description": "",
                    "carrier": "hausportainer", "stack": "app-prod", "repository": REPOSITORY}
    fields.update(changes)
    return environments.Environment(**fields)  # type: ignore[arg-type]


# --- the target a manifest describes ----------------------------------------------------------------

def test_the_carriers_prefix_becomes_the_two_variables_it_stands_for() -> None:
    """A manifest names `url_from: HAUS` and never a value. This is where that prefix turns into the
    variables `credentials.py`'s convention fixed."""
    # arrange
    environ = {"HAUS_URL": "https://10.0.0.124:9443/", "HAUS_TOKEN": "ptr_secret"}

    # act
    target = portainer.PortainerTarget.from_carrier(CARRIER, "app-prod", environ)

    # assert
    assert target.url == "https://10.0.0.124:9443", "the trailing slash would double the one in /api"
    assert target.token == "ptr_secret"
    assert target.stack_name == "app-prod"


def test_the_carrier_decides_the_endpoint_and_the_verification_not_the_environment() -> None:
    """Both are CONFIGURATION and both are in the manifest, so neither may be overridden by a variable
    that happens to be exported - a deployment must land where the file a reviewer read says it does."""
    # arrange
    environ = {"HAUS_URL": "https://p", "HAUS_TOKEN": "t", "PORTAINER_ENDPOINT_ID": "99"}

    # act
    target = portainer.PortainerTarget.from_carrier(CARRIER, "app-prod", environ)

    # assert
    assert target.endpoint_id == 3, "the carrier's endpoint, not the exported one"
    assert target.insecure is True


def test_a_carrier_whose_variables_are_unset_names_the_prefix_it_reads_from() -> None:
    # act / assert
    with pytest.raises(portainer.PortainerError) as refused:
        portainer.PortainerTarget.from_carrier(CARRIER, "app-prod", {})

    assert "HAUS_URL and HAUS_TOKEN" in str(refused.value), (
        "the operator has to be told which variables to export, not which ones the kernel calls them")


def test_verification_is_on_unless_the_carrier_turns_it_off() -> None:
    """THE MEASUREMENT: against the real carrier a verifying request failed with
    CERTIFICATE_VERIFY_FAILED and the same request with verification off answered 200. Portainer makes
    its own certificate, so a carrier the kernel built is unreachable without this - and the manifest has
    to say so out loud."""
    # arrange
    verifying = portainer.PortainerTarget("https://p", "t", 1, "s")
    skipping = portainer.PortainerTarget("https://p", "t", 1, "s", insecure=True)

    # act / assert
    assert portainer._context(verifying) is None, "None means urllib's own verifying default"
    context = portainer._context(skipping)
    assert isinstance(context, ssl.SSLContext) and context.verify_mode == ssl.CERT_NONE


# --- what Portainer is actually sent ----------------------------------------------------------------

def test_an_absent_stack_is_created_from_the_repository(monkeypatch, target) -> None:
    # arrange
    recorder = Creating({"Name": "app-prod", "EndpointId": 3, "Id": 9,
                         "Status": portainer.STATUS_UP})
    monkeypatch.setattr(portainer, "_request", recorder)

    # act
    message = portainer.deploy_from_repository(target, REPOSITORY)

    # assert
    method, path, body = _sent(recorder, "POST")
    assert (method, path) == ("POST", "/stacks/create/standalone/repository?endpointId=3")
    assert body["repositoryURL"] == "https://github.com/acme/app", "a manifest writes no scheme"
    assert body["repositoryReferenceName"] == "refs/heads/main"
    assert body["composeFile"] == "deploy/docker-compose.yml", (
        "the whole reason `repository:` is a block: the document is not at the root")
    assert "created" in message


def test_an_existing_stack_is_redeployed_and_is_not_described_a_second_time(monkeypatch, target) -> None:
    """THE SHAPE THAT COST A MEASUREMENT. Creating and redeploying are two different calls, and the
    second takes none of the description: Portainer already holds it. Sending it again would put a second
    copy of the repository in Portainer's database, where nothing compares it with the manifest."""
    # arrange
    recorder = Recorder({"/stacks": [{"Name": "app-prod", "EndpointId": 3, "Id": 7, "Status": portainer.STATUS_UP}]})
    monkeypatch.setattr(portainer, "_request", recorder)

    # act
    message = portainer.deploy_from_repository(target, REPOSITORY)

    # assert
    method, path, body = _sent(recorder, "PUT")
    assert (method, path) == ("PUT", "/stacks/7/git/redeploy?endpointId=3")
    assert "repositoryURL" not in body and "composeFile" not in body
    assert body["pullImage"] is True, "a redeploy that keeps the old image is the defect, not the feature"
    assert "redeployed" in message


def test_a_public_repository_is_sent_no_authentication_fields_at_all(monkeypatch, target) -> None:
    """`repositoryAuthentication: true` with two empty strings fails the clone on a credential nobody
    meant to supply - "nothing to do" arriving as "failed" one layer down."""
    # arrange
    recorder = Creating({"Name": "app-prod", "EndpointId": 3, "Id": 9,
                         "Status": portainer.STATUS_UP})
    monkeypatch.setattr(portainer, "_request", recorder)

    # act
    portainer.deploy_from_repository(target, REPOSITORY, credential=None)

    # assert
    body = _sent(recorder, "POST")[2]
    assert not any(key.startswith("repositoryAuth") or key.startswith("repositoryUser")
                   or key.startswith("repositoryPass") for key in body)


def test_a_private_repository_carries_the_credential_on_every_deployment(monkeypatch, target) -> None:
    """MEASURED: without these three the same request answers "authentication required: Repository not
    found". Sent on EVERY deployment rather than stored in Portainer (owner, 2026-09-15), so a stack
    somebody opens in the UI carries no usable read access to the source."""
    # arrange
    recorder = Recorder({"/stacks": [{"Name": "app-prod", "EndpointId": 3, "Id": 7, "Status": portainer.STATUS_UP}]})
    monkeypatch.setattr(portainer, "_request", recorder)

    # act
    portainer.deploy_from_repository(target, REPOSITORY, credential=("reader", "pat"))

    # assert
    body = _sent(recorder, "PUT")[2]
    assert body["repositoryAuthentication"] is True
    assert (body["repositoryUsername"], body["repositoryPassword"]) == ("reader", "pat")


@pytest.mark.parametrize("ref, sent", [
    ("main", "refs/heads/main"),
    ("release/2.x", "refs/heads/release/2.x"),
    ("refs/tags/v1.4.0", "refs/tags/v1.4.0"),
])
def test_a_reference_that_is_already_one_is_passed_through(ref, sent) -> None:
    """Which is what lets a product deploy from a TAG without a second manifest key saying what kind of
    reference it wrote."""
    # act / assert
    assert portainer._reference(ref) == sent


# --- removing and describing ------------------------------------------------------------------------

def test_removing_a_stack_that_is_not_there_refuses_and_lists_what_is(monkeypatch, target) -> None:
    """"Removed nothing" and "removed the stack" are two outcomes. An operator tearing an environment
    down has to be able to tell them apart - especially here, where the likely cause is a `stack:` that
    does not say what they think it says."""
    # arrange
    monkeypatch.setattr(portainer, "_request", Recorder({"/stacks": [{"Name": "other", "EndpointId": 3}]}))

    # act / assert
    with pytest.raises(portainer.PortainerError) as refused:
        portainer.remove(target)

    message = str(refused.value)
    assert "app-prod" in message and "other" in message, (
        f"both what was asked for and what is there: {message}")


def test_describing_a_stack_that_is_not_there_is_an_answer_and_not_a_refusal(monkeypatch, target) -> None:
    """The opposite of `remove` on purpose: asking what is deployed and being told "nothing" is a
    complete answer to the question that was asked."""
    # arrange
    monkeypatch.setattr(portainer, "_request", Recorder({"/stacks": []}))

    # act
    described = portainer.describe(target)

    # assert
    assert "not deployed" in described and "no stacks" in described


def test_describing_names_where_the_running_stack_came_from(monkeypatch, target) -> None:
    # arrange
    stack = {"Name": "app-prod", "EndpointId": 3, "Id": 7,
             "GitConfig": {"URL": "https://github.com/acme/app", "ReferenceName": "refs/heads/main"}}
    monkeypatch.setattr(portainer, "_request", Recorder({"/stacks": [stack]}))

    # act
    described = portainer.describe(target)

    # assert
    assert "github.com/acme/app" in described and "refs/heads/main" in described


# --- the backend the kernel ships -------------------------------------------------------------------

def test_the_kernel_ships_a_portainer_backend_so_a_product_registers_nothing() -> None:
    """THE OWNER DECISION OF 2026-09-15 ("Backend im Kernel"). The chain under this backend is already
    the kernel's - `deploy carrier` builds the Portainer, `carriers:` describes it - so a product that
    had to write the class would be writing the far end of a pipe the kernel owns both ends of."""
    # act
    backends = deploy_task.drivable_backends()

    # assert
    assert isinstance(backends[portainer.BACKEND], portainer.PortainerBackend)
    assert isinstance(backends[portainer.BACKEND], backend.Backend), (
        "structural: the shipped one satisfies the same Protocol a product's does")


def test_a_products_own_registration_wins_over_the_shipped_one(monkeypatch) -> None:
    """The alternative - refusing the collision - would mean the kernel shipping a backend could break a
    product that already had one of that name."""
    # arrange
    class Theirs:
        name = portainer.BACKEND

        def deploy(self, env, version): return 0
        def destroy(self, env): return 0
        def status(self, env): return ""

    monkeypatch.setattr(backend, "_REGISTERED", {portainer.BACKEND: Theirs()})

    # act
    backends = deploy_task.drivable_backends()

    # assert
    assert isinstance(backends[portainer.BACKEND], Theirs)


def test_a_product_that_registered_nothing_is_not_refused_any_more() -> None:
    """`backend.registered` still refuses for a product driving `resolve` itself - that is its question.
    The kernel's own deploy commands stopped asking it, because since si#5 an empty product registry is
    the ordinary case rather than a mistake."""
    # act / assert
    assert backend.product_registry() == {}
    assert deploy_task.drivable_backends(), "the kernel can deploy with no product registration at all"


@pytest.mark.parametrize("environment, fragment", [
    (_environment(carrier=""), "nothing says which Portainer"),
    (_environment(stack=""), "nothing says what the deployment is called"),
    (_environment(repository=None), "this backend deploys by handing Portainer one to clone"),
])
def test_half_a_chain_is_refused_by_the_key_that_is_missing(environment, fragment) -> None:
    # act / assert
    with pytest.raises(ValueError) as refused:
        portainer._target_for(environment)

    assert fragment in str(refused.value)


def test_local_is_refused_because_portainer_clones_rather_than_uploads(monkeypatch) -> None:
    """`local` deploys the current code base, and there is no code base on the far end of a clone. The
    refusal says that in one sentence instead of deploying whatever the repository last carried."""
    # arrange
    monkeypatch.setattr(portainer, "_target_for",
                        lambda env: (portainer.PortainerTarget("u", "t", 1, "s"), REPOSITORY))
    version = deployment.Version(selector="local", tag="", builds=True)

    # act / assert
    with pytest.raises(ValueError) as refused:
        portainer.PortainerBackend().deploy(_environment(), version)

    assert "nothing on this machine for it to deploy" in str(refused.value)


def test_the_resolved_version_reaches_the_stack(monkeypatch) -> None:
    """WITHOUT THIS the command prints "deploying 1.4.0" and deploys whatever the compose document
    happened to name - the defect this repository hunts, one command earlier. It is the kernel's OWN
    variable; a product's values are a slice of their own."""
    # arrange
    sent: dict = {}
    monkeypatch.setattr(portainer, "_target_for",
                        lambda env: (portainer.PortainerTarget("u", "t", 1, "s"), REPOSITORY))
    monkeypatch.setattr(portainer, "deploy_from_repository",
                        lambda t, r, c, env_vars: sent.update(env_vars) or "created")

    # act
    code = portainer.PortainerBackend().deploy(
        _environment(), deployment.Version(selector="1.4.0", tag="1.4.0", builds=False))

    # assert
    assert code == 0
    assert sent == {portainer.VERSION_VAR: "1.4.0"}


def test_a_named_credential_that_is_not_exported_is_refused_rather_than_dropped(monkeypatch) -> None:
    """A manifest saying `credential_from: GIT` is a statement that this repository needs one. Deploying
    without it fails inside Portainer with "authentication required: Repository not found", which blames
    the repository for a variable that was never exported."""
    # arrange
    monkeypatch.delenv("GIT_USER", raising=False)
    monkeypatch.delenv("GIT_PASSWORD", raising=False)
    repository = REPOSITORY._replace(credential_from="GIT")

    # act / assert
    with pytest.raises(ValueError) as refused:
        portainer._clone_credential(repository, _environment())

    message = str(refused.value)
    assert "GIT_USER and GIT_PASSWORD" in message


def test_a_repository_that_names_no_credential_asks_for_none(monkeypatch) -> None:
    """A public repository needs no credential, and asking for one would refuse a manifest that works."""
    # act / assert
    assert portainer._clone_credential(REPOSITORY, _environment()) is None


# --- reading the outcome back, which is what the 200 does not say -----------------------------------

def test_a_stack_that_failed_to_come_up_is_not_reported_as_deployed(monkeypatch, target) -> None:
    """THE FIND, and it was found against the real carrier rather than reasoned about. A repository whose
    compose file does not exist is accepted with HTTP 200; the stack then fails, and without the read-back
    `deploy up` printed "created" and exited 0. The message below is Portainer's own, shortened - a
    quoted error text is a second source for a string, so it is pinned against the real one."""
    # arrange
    failed = {"Name": "app-prod", "EndpointId": 3, "Id": 7, "Status": portainer.STATUS_FAILED,
              "DeploymentStatus": [{"Status": 3, "Message": ""},
                                   {"Status": 4, "Message": "failed to pull images of the stack"}]}
    monkeypatch.setattr(portainer, "_request", Recorder({"/stacks": [failed]}))

    # act / assert
    with pytest.raises(portainer.PortainerError) as refused:
        portainer.deploy_from_repository(target, REPOSITORY)

    message = str(refused.value)
    assert "could not bring it up" in message
    assert "failed to pull images of the stack" in message, "Portainer's own sentence, not a paraphrase"


def test_a_deployment_still_running_is_waited_for_rather_than_guessed(monkeypatch, target) -> None:
    """MEASURED: the stack sat in `3` for roughly twenty seconds while one image pulled, and came up
    afterwards. A run that read the status once would have called that a failure."""
    # arrange
    def stack(status: int) -> dict:
        return {"Name": "app-prod", "EndpointId": 3, "Id": 7, "Status": status}

    seen = iter([[stack(portainer.STATUS_DEPLOYING)], [stack(portainer.STATUS_UP)]])
    monkeypatch.setattr(portainer, "_request", lambda *_a, **_k: next(seen))
    slept: list[float] = []

    # act
    settled = portainer._settled(target, stack(portainer.STATUS_DEPLOYING), "created", timeout=60.0,
                                 now=lambda: 0.0, sleep=slept.append)

    # assert - the walk is driven by find_stack, which reads through the patched _request
    assert len(slept) == 2, "it waited once per look, and stopped as soon as the stack was up"
    assert settled["Status"] == portainer.STATUS_UP


def test_running_out_of_the_wait_is_its_own_outcome(monkeypatch, target) -> None:
    """Not a failure and not a success. A slow pull is not a broken deployment, and an operator told the
    wait ended knows to look rather than to deploy again."""
    # arrange
    deploying = {"Name": "app-prod", "EndpointId": 3, "Id": 7, "Status": portainer.STATUS_DEPLOYING}
    monkeypatch.setattr(portainer, "_request", Recorder({"/stacks": [deploying]}))
    clock = iter([0.0, 999.0, 999.0])

    # act / assert
    with pytest.raises(portainer.PortainerError) as refused:
        portainer._settled(target, deploying, "created", timeout=60.0,
                           now=lambda: next(clock), sleep=lambda _s: None)

    message = str(refused.value)
    assert "still deploying" in message and "rather than deploying again" in message
    assert "could not bring it up" not in message, "a wait that ran out is not a failure"


# --- what this backend does NOT do, pinned rather than described (biz-cockpit#263) -------------------

def test_a_deployment_sends_no_compose_document_and_therefore_no_ports(monkeypatch, target) -> None:
    """A CONSUMER ASKED FOR THIS AS A PROBE RATHER THAN A SENTENCE, and the reason is the better half of
    the request: a description ages silently, a probe breaks loudly.

    biz-cockpit is VPN-only with no authentication (their ADR 0009), so anything that made a service
    publicly reachable would be a blocker rather than a feature. The guarantee they needed is that
    `deploy up` decides nothing about ports: what a service binds is written in THEIR compose document,
    and this backend never sends, rewrites or generates one. It hands over a repository and a name.

    The assertion is therefore on the whole key set and not on `ports` alone - a future key that carried a
    port, an override or a second compose document would have to pass through here, and this test is what
    makes adding one a decision somebody takes rather than a line somebody writes.
    """
    # arrange
    recorder = Creating({"Name": "app-prod", "EndpointId": 3, "Id": 9, "Status": portainer.STATUS_UP})
    monkeypatch.setattr(portainer, "_request", recorder)

    # act
    portainer.deploy_from_repository(target, REPOSITORY, credential=("reader", "pat"),
                                     env_vars={portainer.VERSION_VAR: "1.4.0"})

    # assert
    body = _sent(recorder, "POST")[2]
    assert set(body) == {"name", "repositoryURL", "repositoryReferenceName", "composeFile", "env",
                         "repositoryAuthentication", "repositoryUsername", "repositoryPassword"}, (
        "a new key in this body is a new thing the kernel decides about somebody's deployment")
    assert "stackFileContent" not in body, (
        "the git route never sends a document - that is the string route, and the two must not blur")


def test_the_whole_module_never_writes_a_compose_document(monkeypatch, target) -> None:
    """The same promise one level up, so it cannot be kept by this file alone. `stackFileContent` is the
    one field through which a compose document could reach Portainer, and on the git route nothing may
    build one - not from a template, not from a product's file, not from the version."""
    # arrange
    recorder = Creating({"Name": "app-prod", "EndpointId": 3, "Id": 9, "Status": portainer.STATUS_UP})
    monkeypatch.setattr(portainer, "_request", recorder)
    monkeypatch.setattr(portainer, "_target_for", lambda env: (target, REPOSITORY))

    # act
    portainer.PortainerBackend().deploy(
        _environment(), deployment.Version(selector="1.4.0", tag="1.4.0", builds=False))

    # assert
    assert not any("stackFileContent" in (body or {}) for _m, _p, body in recorder.calls)


# --- the values a deployment must be given (si#5, from biz-cockpit#263) ------------------------------

REQUIRED = ("COCKPIT_DATA_DIR", "BACKUP_DIR", "HTTP_BIND")


def test_the_named_values_are_read_out_of_the_environment_the_command_runs_in() -> None:
    """The consumer's own answer: from the deploy command, at EVERY deploy, not once into Portainer's
    web interface. Portainer stores them either way - the question is whether its copy is an image
    something refreshes or an original nobody does."""
    # arrange
    environ = {"COCKPIT_DATA_DIR": "/srv/biz-cockpit/prod/data", "BACKUP_DIR": "/srv/biz-cockpit/prod/backups",
               "HTTP_BIND": "127.0.0.1", "UNRELATED": "not sent"}

    # act
    values = portainer.stack_values(_environment(required=REQUIRED), environ)

    # assert
    assert values == {"COCKPIT_DATA_DIR": "/srv/biz-cockpit/prod/data",
                      "BACKUP_DIR": "/srv/biz-cockpit/prod/backups", "HTTP_BIND": "127.0.0.1"}
    assert "UNRELATED" not in values, (
        "only what the manifest names reaches the deployment - a reader has to be able to see what goes")


def test_an_empty_value_fails_the_deployment_rather_than_falling_back(monkeypatch) -> None:
    """THE CASE THE CONSUMER ASKED FOR, and it is worth the refusal because of how it fails without one.
    Their document writes `${COCKPIT_DATA_DIR:-${HOME}/.biz-cockpit}:/data`: a missing value does not
    crash compose, it falls back - and the bind mount lands in the CARRIER's /root instead of
    /srv/biz-cockpit/prod. The container writes happily, the deployment looks green, and the database sits
    outside everything `backup` knows about. Green because nobody looks."""
    # arrange
    environ = {"COCKPIT_DATA_DIR": "/srv/prod/data", "BACKUP_DIR": "   ", "HTTP_BIND": ""}

    # act / assert
    with pytest.raises(ValueError) as refused:
        portainer.stack_values(_environment(required=REQUIRED), environ)

    message = str(refused.value)
    assert "BACKUP_DIR" in message and "HTTP_BIND" in message, (
        f"every missing one at once - repairing eight variables one run at a time is the kernel's work "
        f"being handed to an operator: {message}")
    assert "COCKPIT_DATA_DIR" not in message, "the ones that ARE set are not named as problems"


def test_the_values_and_the_version_travel_together(monkeypatch) -> None:
    # arrange
    sent: dict = {}
    monkeypatch.setattr(portainer, "_target_for",
                        lambda env: (portainer.PortainerTarget("u", "t", 1, "s"), REPOSITORY))
    monkeypatch.setattr(portainer, "deploy_from_repository",
                        lambda t, r, c, env_vars: sent.update(env_vars) or "created")
    monkeypatch.setenv("HTTP_BIND", "127.0.0.1")

    # act
    portainer.PortainerBackend().deploy(
        _environment(required=("HTTP_BIND",)),
        deployment.Version(selector="1.4.0", tag="1.4.0", builds=False))

    # assert
    assert sent == {"HTTP_BIND": "127.0.0.1", portainer.VERSION_VAR: "1.4.0"}


# --- what the manifest may and may not say about those values ---------------------------------------

def test_a_manifest_names_variables_and_never_holds_one() -> None:
    """The same guarantee `credential_from:` gives one line up. Somebody writing `NAME=value` here is
    writing a value into a committed file, and it must not be read as a name containing an equals sign."""
    # act / assert
    with pytest.raises(ValueError) as refused:
        environments._names(["TOGGL_API_TOKEN=4c2b9f"], "required", "environment 'prod'")

    assert "never holds its value" in str(refused.value)


def test_the_manifest_may_not_claim_the_variable_the_kernel_sets() -> None:
    """Two answers to one question. Whichever won, `--version` would mean whatever happened to be
    exported - and nothing would print which of the two had been used."""
    # act / assert
    with pytest.raises(ValueError) as refused:
        environments._names([portainer.VERSION_VAR], "optional", "environment 'prod'")

    assert "the kernel sets it from the version being deployed" in str(refused.value)


def test_required_values_with_no_stack_have_nowhere_to_go() -> None:
    # arrange
    document = {"environments": {"prod": {"backend": "portainer", "required": ["A"]}}, "default": "prod"}

    # act / assert
    with pytest.raises(ValueError) as refused:
        environments.parse_data(document, ("portainer",))

    assert "no deployment for those values to be given to" in str(refused.value)


def test_a_product_that_names_no_values_is_given_none() -> None:
    """An absent `required:` is not a refusal: the six products that predate all of this declare none."""
    # act / assert
    assert portainer.stack_values(_environment(), {}) == {}


# --- the third state one list could not say (biz-cockpit#263, their correction) ----------------------

def test_an_optional_value_travels_when_it_is_set() -> None:
    """THE CASE THE FIRST FORM COULD NOT EXPRESS, and it was a real product's, not a hypothetical. Their
    compose writes `${SMALLINVOICE_CLIENT_SECRET:-}`: the integration is deliberately optional. In
    `required:` the product becomes uninstallable without a Smallinvoice account; in neither list the
    secret never reaches the stack and the integration is not optional but impossible."""
    # arrange
    env = _environment(required=("HTTP_BIND",), optional=("SMALLINVOICE_CLIENT_SECRET", "APP_TITLE"))
    environ = {"HTTP_BIND": "127.0.0.1", "SMALLINVOICE_CLIENT_SECRET": "si_live"}

    # act
    values = portainer.stack_values(env, environ)

    # assert
    assert values == {"HTTP_BIND": "127.0.0.1", "SMALLINVOICE_CLIENT_SECRET": "si_live"}
    assert "APP_TITLE" not in values, (
        "an optional name with no value is left OUT rather than sent as an empty string - sending \"\" "
        "and sending nothing are the same to that document today, and the day they differ the kernel "
        "would have chosen for it")


def test_an_absent_optional_value_does_not_fail_the_deployment() -> None:
    """The whole point of the second list: `deploy up` must work for an operator who has no Smallinvoice
    account at all, which is what their ticket #201 made possible in the first place."""
    # arrange
    env = _environment(required=("HTTP_BIND",),
                       optional=("SMALLINVOICE_CLIENT_SECRET", "TOGGL_API_TOKEN"))

    # act
    values = portainer.stack_values(env, {"HTTP_BIND": "127.0.0.1"})

    # assert
    assert values == {"HTTP_BIND": "127.0.0.1"}


def test_a_name_in_both_lists_is_refused_rather_than_ranked() -> None:
    """"Must have a value" and "may be absent" about one variable is not a precedence question with a
    right answer - it is a manifest that says two things, and the kernel picking one would decide it
    silently."""
    # arrange
    document = {"carriers": {"haus": {"proxmox": {"node": "pve", "kind": "lxc"},
                                      "portainer": {"url_from": "P"}}},
                "environments": {"prod": {"backend": "portainer", "carrier": "haus", "stack": "s",
                                          "required": ["TOGGL_API_TOKEN"],
                                          "optional": ["TOGGL_API_TOKEN"]}},
                "default": "prod"}

    # act / assert
    with pytest.raises(ValueError) as refused:
        environments.parse_data(document, ("portainer",))

    message = str(refused.value)
    assert "TOGGL_API_TOKEN" in message and "One of the two lists is the answer" in message


def test_optional_alone_still_needs_somewhere_to_go() -> None:
    # arrange
    document = {"environments": {"prod": {"backend": "portainer", "optional": ["APP_TITLE"]}},
                "default": "prod"}

    # act / assert
    with pytest.raises(ValueError) as refused:
        environments.parse_data(document, ("portainer",))

    assert "no deployment for those values to be given to" in str(refused.value)
