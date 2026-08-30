"""Sending a compose stack to Portainer (platform#155, from biz-cockpit#154).

What is tested is what can go wrong WITHOUT anybody noticing: that a foreign stack of the same name is
never overwritten, that an update really pulls again, and that a missing setting says WHICH one is
missing.

No network: `_request` is the only place that opens one, and it is replaced.
"""
from __future__ import annotations

import pytest

from delivery import portainer

STACK = "someproduct-prod"


@pytest.fixture
def target() -> portainer.PortainerTarget:
    return portainer.PortainerTarget(
        url="https://portainer.local", token="t", endpoint_id=2, stack_name=STACK
    )


class Recorder:
    """Records the calls and answers by path."""

    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, _target, method: str, path: str, body: dict | None = None) -> object:
        self.calls.append((method, path, body))
        for prefix, answer in self.answers.items():
            if path.startswith(prefix):
                return answer
        return None


def test_missing_configuration_names_the_variable() -> None:
    with pytest.raises(portainer.PortainerError, match="PORTAINER_URL"):
        portainer.PortainerTarget.from_env("prod", STACK, {})


def test_the_missing_configuration_also_says_where_it_belongs() -> None:
    """The kernel cannot know a product's layout, so the product hands the hint in - without it the
    reader is told what is missing but not where to put it."""
    with pytest.raises(portainer.PortainerError, match="deploy/env/prod/secrets.env"):
        portainer.PortainerTarget.from_env(
            "prod", STACK, {}, secrets_hint="Belongs in deploy/env/prod/secrets.env."
        )


def test_the_stack_name_falls_back_to_the_one_the_product_named() -> None:
    parsed = portainer.PortainerTarget.from_env(
        "prod", STACK, {"PORTAINER_URL": "https://p/", "PORTAINER_TOKEN": "t"}
    )

    assert parsed.stack_name == STACK
    assert parsed.url == "https://p"  # the trailing slash goes
    assert parsed.endpoint_id == 1


def test_the_environment_wins_over_the_products_default() -> None:
    parsed = portainer.PortainerTarget.from_env(
        "prod", STACK, {"PORTAINER_URL": "https://p", "PORTAINER_TOKEN": "t", "PORTAINER_STACK": "other"}
    )

    assert parsed.stack_name == "other"


def test_a_non_numeric_endpoint_is_refused() -> None:
    with pytest.raises(portainer.PortainerError, match="ENDPOINT_ID"):
        portainer.PortainerTarget.from_env(
            "prod",
            STACK,
            {"PORTAINER_URL": "https://p", "PORTAINER_TOKEN": "t", "PORTAINER_ENDPOINT_ID": "two"},
        )


def test_a_stack_of_the_same_name_on_another_endpoint_is_not_ours(monkeypatch, target) -> None:
    """Overwriting the foreign one would be the worst conceivable outcome."""
    recorder = Recorder({"/stacks": [{"Id": 9, "Name": STACK, "EndpointId": 7}]})
    monkeypatch.setattr(portainer, "_request", recorder)

    found = portainer.find_stack(target)

    assert found is None


def test_an_unknown_stack_is_created(monkeypatch, target) -> None:
    recorder = Recorder({"/stacks": []})
    monkeypatch.setattr(portainer, "_request", recorder)

    message = portainer.deploy(target, "services: {}", {"A": "1"})

    assert "created" in message
    method, path, body = recorder.calls[-1]
    assert method == "POST"
    assert "endpointId=2" in path
    assert body["name"] == STACK
    assert body["stackFileContent"] == "services: {}"
    assert body["env"] == [{"name": "A", "value": "1"}]


def test_an_existing_stack_is_updated_and_the_images_are_pulled(monkeypatch, target) -> None:
    """Without `pullImage` Portainer cheerfully keeps running the old image - the failure would look
    like "the deployment did nothing"."""
    recorder = Recorder({"/stacks": [{"Id": 5, "Name": STACK, "EndpointId": 2}]})
    monkeypatch.setattr(portainer, "_request", recorder)

    message = portainer.deploy(target, "services: {}", {})

    assert "updated" in message
    method, path, body = recorder.calls[-1]
    assert (method, path) == ("PUT", "/stacks/5?endpointId=2")
    assert body["pullImage"] is True


def test_the_registry_check_looks_for_the_named_host(monkeypatch, target) -> None:
    monkeypatch.setattr(
        portainer, "_request", Recorder({"/registries": [{"URL": "ghcr.io/someone"}]})
    )
    assert portainer.has_registry(target) is True

    monkeypatch.setattr(portainer, "_request", Recorder({"/registries": [{"URL": "docker.io"}]}))
    assert portainer.has_registry(target) is False

    monkeypatch.setattr(
        portainer, "_request", Recorder({"/registries": [{"URL": "registry.example/x"}]})
    )
    assert portainer.has_registry(target, host="registry.example") is True
