"""Unit tests for delivery.backend - the Backend Protocol + the env -> Backend INSTANCE resolution that
replaces `if env.backend == ...` string dispatch (netctl#735). No I/O; AAA throughout, incl. negatives.
The product supplies the concrete backends; here we register tiny fakes to exercise the kernel seam.
"""
import pytest

from delivery.backend import Backend, resolve
from delivery.environments import Environment


class _FakeBackend:
    """A minimal structural Backend (no subclassing): a name + the lifecycle triad."""

    def __init__(self, name: str) -> None:
        self.name = name

    def deploy(self, env: Environment) -> int:
        return 0

    def destroy(self, env: Environment) -> int:
        return 0

    def status(self, env: Environment) -> str:
        return f"{self.name}:{env.name}"


_LOCAL = _FakeBackend("local")
_CLOUD = _FakeBackend("cloud")
_REGISTRY = {"local": _LOCAL, "cloud": _CLOUD}


def test_resolve_returns_the_instance_registered_for_the_envs_backend_tag():
    # arrange: an env whose backend tag is registered
    env = Environment("dev", "local", "Local lab.")

    # act
    backend = resolve(env, _REGISTRY)

    # assert: the SAME instance the product registered, not a copy or a string
    assert backend is _LOCAL


def test_resolve_dispatches_by_the_backend_tag_not_the_env_name():
    # arrange: two envs with different backends share nothing but the registry
    dev = Environment("dev", "local", "")
    prod = Environment("prod", "cloud", "")

    # act / assert: each env resolves to its OWN backend instance
    assert resolve(dev, _REGISTRY) is _LOCAL
    assert resolve(prod, _REGISTRY) is _CLOUD


def test_resolve_fails_loud_when_no_backend_is_registered_for_the_tag():
    # arrange: an env whose backend has no registered implementation
    env = Environment("staging", "kubernetes", "")

    # act / assert: a clear error naming the tag AND the known backends, not a bare KeyError
    with pytest.raises(ValueError, match="no backend registered for 'kubernetes'") as exc:
        resolve(env, _REGISTRY)
    assert "cloud" in str(exc.value) and "local" in str(exc.value)


def test_resolve_reports_none_registered_when_the_registry_is_empty():
    # arrange: the degenerate empty-registry case
    env = Environment("dev", "local", "")

    # act / assert
    with pytest.raises(ValueError, match=r"known: \(none registered\)"):
        resolve(env, {})


def test_a_structural_implementation_satisfies_the_runtime_checkable_protocol():
    # arrange / act / assert: the fake satisfies Backend without subclassing it
    assert isinstance(_LOCAL, Backend)


def test_an_object_missing_a_lifecycle_method_is_not_a_backend():
    # arrange: a would-be backend that never grew a `status`
    class _Partial:
        name = "partial"

        def deploy(self, env: Environment) -> int:
            return 0

        def destroy(self, env: Environment) -> int:
            return 0

    # act / assert: the structural check rejects it (no `status`)
    assert not isinstance(_Partial(), Backend)
