"""Unit tests for compose - the pure readings of a resolved compose configuration (platform#43, the
mechanism half of biz-cockpit#74).

The documents below are shaped exactly like `docker compose config --format json` output, because that
is the input a product's deployment guards judge. No docker, no filesystem: `exists` and `owner` are
injected. AAA throughout.

Every fixture carries TWO of whatever the function under test picks from - two services, two bind mounts,
two published ports, two variables - with DIFFERENT values, so a wrong implementation that takes "the
first one", "any one" or "all of them" cannot pass by accident.
"""
import pytest

from delivery import compose

# One realistic two-service instance: a proxy publishing the front door, a backend with the data tree.
# Bind mounts are declared UNSORTED on purpose, and the read-only workbook mount is a bind the container
# never writes to.
_RESOLVED = {
    "name": "acme-prod",
    "services": {
        "proxy": {
            "image": "caddy:2-alpine",
            "environment": {"SITE_ADDRESS": "acme.example", "UPSTREAM": "backend:8000"},
            "ports": [
                {"mode": "ingress", "target": 53, "published": "53", "protocol": "udp"},
                {"mode": "ingress", "target": 80, "published": "8080", "protocol": "tcp"},
                {"mode": "ingress", "target": 443, "published": "8443", "protocol": "tcp"},
            ],
        },
        "backend": {
            "image": "acme-backend:1.4.0",
            "environment": {"APP_TITLE": "Acme", "TOKEN_A": "live-a", "TOKEN_B": None,
                            "TOKEN_C": "   ", "TOKEN_D": "live-d"},
            "ports": [{"mode": "ingress", "target": 8000, "host_ip": "10.0.0.2",
                       "published": "9000", "protocol": "tcp"}],
            "volumes": [
                {"type": "bind", "source": "/srv/acme/prod/reports", "target": "/reports"},
                {"type": "volume", "source": "acme_cache", "target": "/cache"},
                {"type": "bind", "source": "/srv/acme/prod/data", "target": "/data"},
                {"type": "bind", "source": "/srv/acme/prod/books", "target": "/books",
                 "read_only": True},
            ],
        },
    },
}

_UID = 1000


# --- reading one service out of the document ---------------------------------------------------------

def test_a_service_is_read_by_name_and_not_by_position():
    # arrange: two services, the wanted one declared second

    # act
    found = compose.service(_RESOLVED, "backend")

    # assert
    assert found["image"] == "acme-backend:1.4.0"


def test_a_service_the_document_does_not_declare_reads_as_empty():
    # arrange / act
    found = compose.service(_RESOLVED, "worker")

    # assert: an absent service is empty, never the other service and never a KeyError
    assert found == {}


def test_a_document_without_services_reads_as_empty():
    # arrange: a resolution that failed to produce services at all
    config = {"name": "acme-prod"}

    # act / assert
    assert compose.service(config, "backend") == {}


# --- the resolved environment of one service ---------------------------------------------------------

def test_the_environment_of_a_service_is_read_as_strings():
    # arrange / act
    resolved = compose.service_environment(_RESOLVED, "proxy")

    # assert: this service's own environment, not the other's
    assert resolved == {"SITE_ADDRESS": "acme.example", "UPSTREAM": "backend:8000"}


def test_a_variable_passed_through_without_a_value_reads_as_unset():
    # arrange / act: compose renders `null` for a pass-through variable that has no value
    resolved = compose.service_environment(_RESOLVED, "backend")

    # assert: the empty string, NOT the string "None" - which would look like a value downstream
    assert resolved["TOKEN_B"] == ""


def test_a_missing_service_reads_as_an_empty_environment():
    # arrange / act
    resolved = compose.service_environment(_RESOLVED, "worker")

    # assert
    assert resolved == {}


# --- which of the product's variables carry a value --------------------------------------------------

def test_only_the_variables_that_carry_a_value_are_reported():
    # arrange: two set, one null, one whitespace-only
    resolved = compose.service_environment(_RESOLVED, "backend")

    # act
    assigned = compose.assigned_variables(resolved, ("TOKEN_A", "TOKEN_B", "TOKEN_C", "TOKEN_D"))

    # assert: whitespace is not a value, an unset pass-through is not a value
    assert assigned == ["TOKEN_A", "TOKEN_D"]


def test_the_answer_follows_the_order_of_the_asked_keys():
    # arrange: the asked order is the REVERSE of the environment's declaration order
    resolved = compose.service_environment(_RESOLVED, "backend")

    # act
    assigned = compose.assigned_variables(resolved, ("TOKEN_D", "TOKEN_C", "TOKEN_B", "TOKEN_A"))

    # assert: the product's list is the order it gets to read back
    assert assigned == ["TOKEN_D", "TOKEN_A"]


def test_a_variable_outside_the_asked_keys_is_never_reported():
    # arrange: APP_TITLE carries a value but is none of the product's business here
    resolved = compose.service_environment(_RESOLVED, "backend")

    # act
    assigned = compose.assigned_variables(resolved, ("TOKEN_B", "TOKEN_C"))

    # assert
    assert assigned == []


def test_a_variable_the_environment_does_not_have_is_not_reported():
    # arrange / act: asked for a key nothing resolved
    assigned = compose.assigned_variables({"TOKEN_A": "live-a"}, ("TOKEN_A", "TOKEN_Z"))

    # assert
    assert assigned == ["TOKEN_A"]


# --- the bind mounts of one service ------------------------------------------------------------------

def test_bind_sources_map_container_targets_to_host_paths():
    # arrange / act
    sources = compose.bind_sources(_RESOLVED, "backend")

    # assert: every bind, in declaration order; the named volume is not one
    assert sources == {"/reports": "/srv/acme/prod/reports",
                       "/data": "/srv/acme/prod/data",
                       "/books": "/srv/acme/prod/books"}


def test_a_read_only_mount_is_not_a_writable_bind_source():
    # arrange / act
    writable = compose.bind_sources(_RESOLVED, "backend", writable_only=True)

    # assert: the workbook mount drops out, the two writable ones stay
    assert writable == {"/reports": "/srv/acme/prod/reports", "/data": "/srv/acme/prod/data"}


def test_a_service_without_volumes_binds_nothing():
    # arrange / act
    sources = compose.bind_sources(_RESOLVED, "proxy")

    # assert
    assert sources == {}


def test_only_the_absent_host_directories_are_reported_missing():
    # arrange: one of the three bind sources exists on the host
    present = {"/srv/acme/prod/data"}

    # act
    missing = compose.missing_bind_sources(_RESOLVED, "backend", present.__contains__)

    # assert: sorted, so the report reads the same whatever order compose declared them in
    assert missing == ["/srv/acme/prod/books", "/srv/acme/prod/reports"]


def test_a_complete_data_tree_reports_nothing_missing():
    # arrange / act: every path exists
    missing = compose.missing_bind_sources(_RESOLVED, "backend", lambda _path: True)

    # assert
    assert missing == []


def test_a_read_only_mount_is_still_expected_to_exist():
    # arrange: nothing exists on this host at all
    missing = compose.missing_bind_sources(_RESOLVED, "backend", lambda _path: False)

    # act / assert: a read-only mount is dropped from the OWNERSHIP check, never from the existence one -
    # docker would create it root-owned just the same
    assert missing == ["/srv/acme/prod/books", "/srv/acme/prod/data", "/srv/acme/prod/reports"]


def test_a_writable_directory_owned_by_someone_else_than_the_image_user_is_reported():
    # arrange: one writable mount owned by root, one by the image's uid
    owners = {"/srv/acme/prod/data": 0,
              "/srv/acme/prod/reports": _UID,
              "/srv/acme/prod/books": 0}

    # act
    foreign = compose.foreign_owner_bind_sources(_RESOLVED, "backend", owners.get, uid=_UID)

    # assert: only the writable stranger; the read-only one is nobody's business
    assert foreign == ["/srv/acme/prod/data"]


def test_an_unreadable_directory_is_left_to_the_missing_check():
    # arrange: the owner probe cannot read anything (the missing case)

    # act
    foreign = compose.foreign_owner_bind_sources(_RESOLVED, "backend", lambda _path: None, uid=_UID)

    # assert
    assert foreign == []


def test_the_image_uid_comes_from_the_caller_and_not_from_the_kernel():
    # arrange: every writable mount is owned by 1000
    owners = {"/srv/acme/prod/data": 1000, "/srv/acme/prod/reports": 1000}

    # act: an image running as 65532 is a stranger in exactly the same tree
    foreign = compose.foreign_owner_bind_sources(_RESOLVED, "backend", owners.get, uid=65532)

    # assert
    assert foreign == ["/srv/acme/prod/data", "/srv/acme/prod/reports"]


# --- where a probe has to knock ----------------------------------------------------------------------

def test_a_port_published_on_every_interface_is_reached_on_the_loopback():
    # arrange / act: the proxy's first TCP publication has no host_ip
    endpoint = compose.published_endpoint(_RESOLVED, "proxy")

    # assert: the UDP entry declared before it is not a TCP endpoint, and 8443 is not the first one
    assert endpoint == ("127.0.0.1", 8080)


def test_a_port_pinned_to_one_address_is_reached_on_that_address():
    # arrange / act: the backend publishes on a single interface
    endpoint = compose.published_endpoint(_RESOLVED, "backend")

    # assert
    assert endpoint == ("10.0.0.2", 9000)


def test_a_port_published_on_every_ipv6_interface_is_reached_on_the_loopback():
    # arrange
    config = {"services": {"proxy": {"ports": [{"host_ip": "::", "published": "8080",
                                                "protocol": "tcp"}]}}}

    # act / assert
    assert compose.published_endpoint(config, "proxy") == ("127.0.0.1", 8080)


def test_a_published_range_is_entered_at_its_first_port():
    # arrange
    config = {"services": {"proxy": {"ports": [{"published": "8080-8090", "protocol": "tcp"}]}}}

    # act / assert
    assert compose.published_endpoint(config, "proxy") == ("127.0.0.1", 8080)


def test_a_service_that_publishes_nothing_cannot_be_reached():
    # arrange: a service with no ports at all
    config = {"services": {"proxy": {"image": "caddy:2-alpine"}}}

    # act / assert
    with pytest.raises(LookupError, match="proxy"):
        compose.published_endpoint(config, "proxy")


def test_a_service_that_publishes_only_udp_cannot_be_reached():
    # arrange
    config = {"services": {"dns": {"ports": [{"published": "53", "protocol": "udp"}]}}}

    # act / assert
    with pytest.raises(LookupError):
        compose.published_endpoint(config, "dns")


def test_the_health_url_follows_what_compose_published():
    # arrange / act: the product supplies its front door and its liveness route
    url = compose.health_url(_RESOLVED, "proxy", "/api/v1/health")

    # assert
    assert url == "http://127.0.0.1:8080/api/v1/health"


def test_the_health_url_names_the_service_the_product_asked_for():
    # arrange / act: the same document, a different service and route
    url = compose.health_url(_RESOLVED, "backend", "/healthz")

    # assert
    assert url == "http://10.0.0.2:9000/healthz"


def test_a_stack_terminating_tls_itself_is_probed_over_https():
    # arrange / act
    url = compose.health_url(_RESOLVED, "proxy", "/api/v1/health", scheme="https")

    # assert
    assert url == "https://127.0.0.1:8080/api/v1/health"


# --- which file the container will see ---------------------------------------------------------------

_HOST_DIR = "/srv/acme/prod/backups"
_MOUNT = "/backups"


def test_a_bare_file_name_is_taken_from_the_mounted_directory():
    # arrange
    snapshot = "acme-backup-20260820-071500.db"

    # act
    target = compose.snapshot_container_path(snapshot, _HOST_DIR, _MOUNT)

    # assert
    assert target == "/backups/acme-backup-20260820-071500.db"


def test_a_path_already_expressed_container_side_is_passed_through():
    # arrange
    snapshot = "/backups/nightly/acme-backup-20260820-071500.db"

    # act
    target = compose.snapshot_container_path(snapshot, _HOST_DIR, _MOUNT)

    # assert
    assert target == "/backups/nightly/acme-backup-20260820-071500.db"


def test_a_host_path_inside_the_bound_directory_is_rewritten_onto_the_mount():
    # arrange
    snapshot = f"{_HOST_DIR}/nightly/acme-backup-20260820-071500.db"

    # act
    target = compose.snapshot_container_path(snapshot, _HOST_DIR, _MOUNT)

    # assert
    assert target == "/backups/nightly/acme-backup-20260820-071500.db"


def test_the_mount_point_comes_from_the_caller():
    # arrange: another product mounts its archive somewhere else entirely
    snapshot = f"{_HOST_DIR}/acme-backup-20260820-071500.db"

    # act
    target = compose.snapshot_container_path(snapshot, _HOST_DIR, "/var/lib/archive")

    # assert
    assert target == "/var/lib/archive/acme-backup-20260820-071500.db"


def test_a_host_path_of_another_instance_is_refused():
    # arrange: the same file name under a sibling instance's tree
    snapshot = "/srv/acme/test/backups/acme-backup-20260820-071500.db"

    # act / assert
    with pytest.raises(ValueError, match="not inside this environment's directory"):
        compose.snapshot_container_path(snapshot, _HOST_DIR, _MOUNT)


def test_a_host_path_is_refused_when_the_bound_directory_is_unknown():
    # arrange: the resolved configuration had no bind source behind the mount
    snapshot = f"{_HOST_DIR}/acme-backup-20260820-071500.db"

    # act / assert
    with pytest.raises(ValueError):
        compose.snapshot_container_path(snapshot, None, _MOUNT)


def test_a_relative_escape_is_refused():
    # arrange
    snapshot = "../data/app.db"

    # act / assert
    with pytest.raises(ValueError, match="escapes"):
        compose.snapshot_container_path(snapshot, _HOST_DIR, _MOUNT)


def test_the_mounted_directory_itself_is_not_a_file_in_it():
    # arrange / act / assert
    with pytest.raises(ValueError, match="not a file in it"):
        compose.snapshot_container_path(_MOUNT, _HOST_DIR, _MOUNT)


def test_the_bound_host_directory_itself_is_not_a_file_in_it():
    # arrange / act / assert: naming the directory the mount is bound to must not resolve to the mount
    # point itself - a caller would then hand the container a directory where it expects a file
    with pytest.raises(ValueError, match="not inside this environment's directory"):
        compose.snapshot_container_path(_HOST_DIR, _HOST_DIR, _MOUNT)


def test_an_empty_argument_is_refused():
    # arrange / act / assert
    with pytest.raises(ValueError, match="no snapshot given"):
        compose.snapshot_container_path("   ", _HOST_DIR, _MOUNT)
