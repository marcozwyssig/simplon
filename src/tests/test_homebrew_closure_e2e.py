"""The install closure measured on a real wheel in the real brew image (si#536). Needs docker and the network."""
from __future__ import annotations

import hashlib
import urllib.request

import pytest

from conftest import docker_is_usable
from simplon.adapters import pypi
from simplon.tasks import homebrewclosure as hc

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to run the brew image in")

#: simplon's own formula inputs, as the prototype behind homebrew-tap#1 used them.
DEPENDS_ON = ["cryptography", "libsodium", "libyaml", "pydantic"]
PYTHON = "python@3.14"


@needs_docker
def test_simplon_0_36_0_closure_is_the_measured_one(tmp_path):
    wheel_file = next(f for f in pypi.files("simplon", "0.36.0") if f.filename == "simplon-0.36.0-py3-none-any.whl")
    wheel = tmp_path / wheel_file.filename
    with urllib.request.urlopen(wheel_file.url, timeout=60) as r:
        wheel.write_bytes(r.read())
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == wheel_file.sha256
    # The image runs as its own user (linuxbrew, uid 1000) and pytest's tmp_path is 0700: measured, pip then
    # answers "Permission denied: '/w/simplon-0.36.0-py3-none-any.whl'". A wheel directory a build writes is 0755.
    tmp_path.chmod(0o755)

    dists = hc.measure(wheel, DEPENDS_ON, PYTHON)

    assert hc.refusals(dists, "simplon") == []
    # 22: the count the prototype measured on 0.36.0 in this image (homebrew-tap#1).
    assert len(hc.added(dists, "simplon")) == 22, sorted(f"{d.name}=={d.version}" for d in hc.added(dists, "simplon"))
