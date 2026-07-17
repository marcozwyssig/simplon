"""Smoke test: platformcore is importable and carries a version."""
from platformcore import __version__


def test_platformcore_exposes_a_nonempty_version_string():
    # arrange / act / assert
    assert isinstance(__version__, str)
    assert __version__
