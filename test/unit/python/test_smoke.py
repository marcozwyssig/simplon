"""Smoke test: delivery is importable and carries a version."""
from delivery import __version__


def test_delivery_exposes_a_nonempty_version_string():
    # arrange / act / assert
    assert isinstance(__version__, str)
    assert __version__
