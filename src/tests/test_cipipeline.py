"""The product's `runner:` section, read by `simplon.tasks.cipipeline` (si#858)."""
from __future__ import annotations

import pytest

from simplon.tasks import cipipeline


def test_no_runner_means_github_ubuntu() -> None:
    runner, labels = cipipeline.runner_of({})
    assert runner.kind == "github-ubuntu"
    assert labels == ("ubuntu-latest",)


def test_a_self_hosted_runner_names_its_labels() -> None:
    runner, labels = cipipeline.runner_of({"runner": {"kind": "self-hosted-debian", "labels": "ghr-8"}})
    assert runner.kind == "self-hosted-debian"
    assert labels == ("ghr-8",)


def test_a_self_hosted_runner_without_labels_is_refused() -> None:
    with pytest.raises(ValueError, match="carries no label of its own"):
        cipipeline.runner_of({"runner": "self-hosted-debian"})
