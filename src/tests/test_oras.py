"""Unit tests for oras - the OCI-artifact CLI gate: package manager first, pinned release as the
fallback. No network, no real download, no PATH mutation beyond the monkeypatched environment; AAA
throughout, one decision per test.

What is under test is what this module DECIDES - which URL for which host, which installer argv, and
what it does when an install leaves no binary behind - never whether oras itself works.
"""
import os

import pytest

from simplon import context
from simplon import oras


@pytest.fixture(autouse=True)
def _product_context(tmp_path, monkeypatch):
    """Every test runs with a registered product context: the tool directory is derived from the
    product's repo root, and an unregistered context raises rather than defaulting."""
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("cleon", tmp_path, tmp_path / "cleon.yaml"))


@pytest.fixture
def absent(monkeypatch):
    """oras is not on PATH - the shape every install path starts from."""
    monkeypatch.setattr(oras.shutil, "which", lambda tool: None)


def _boom(what):
    def explode(*args, **kwargs):
        raise AssertionError(f"must not have {what}")
    return explode


def _fetch_writing(recorder):
    """A stand-in for the download that behaves like the real one: it PRODUCES the file."""
    def fake(dest):
        recorder.append(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("#!/bin/sh\n")
    return fake


# --- the release URL: pure, and the only place the host naming lives -------------------------------

def test_the_macos_archive_is_a_tarball_named_for_the_host():
    url = oras.release_url("Darwin", "arm64", version="1.3.4")

    assert url == ("https://github.com/oras-project/oras/releases/download/v1.3.4/"
                   "oras_1.3.4_darwin_arm64.tar.gz")


def test_the_windows_archive_is_a_zip():
    url = oras.release_url("Windows", "AMD64", version="1.3.4")

    assert url.endswith("oras_1.3.4_windows_amd64.zip")


def test_intel_and_arm_spellings_collapse_to_the_two_names_oras_publishes():
    intel = oras.release_url("Linux", "x86_64", version="1.3.4")
    arm = oras.release_url("Linux", "aarch64", version="1.3.4")

    assert intel.endswith("oras_1.3.4_linux_amd64.tar.gz")
    assert arm.endswith("oras_1.3.4_linux_arm64.tar.gz")


def test_an_architecture_oras_does_not_publish_is_named_in_the_failure():
    with pytest.raises(oras.OrasError, match="s390x"):
        oras.release_url("Linux", "s390x")


def test_an_operating_system_oras_does_not_publish_is_named_in_the_failure():
    # A bogus URL would 404 halfway through a build; the host is named here instead.
    with pytest.raises(oras.OrasError, match="SunOS"):
        oras.release_url("SunOS", "x86_64")


# --- the package manager: a table, so a future winget manifest is one row --------------------------

def test_homebrew_is_the_macos_installer():
    argv = oras.installer_argv("Darwin", have=lambda tool: tool == "brew")

    assert argv == ["brew", "install", "oras"]


def test_homebrew_also_serves_linux_where_it_is_present():
    argv = oras.installer_argv("Linux", have=lambda tool: tool == "brew")

    assert argv == ["brew", "install", "oras"]


def test_windows_has_no_package_manager_carrying_oras():
    # Checked, not assumed: winget has no manifests/o/oras, Chocolatey has no package, and the Scoop
    # main bucket has none either. Every Windows host therefore takes the download path.
    argv = oras.installer_argv("Windows", have=lambda tool: True)

    assert argv is None


def test_no_installer_without_the_manager_it_names():
    argv = oras.installer_argv("Darwin", have=lambda tool: False)

    assert argv is None


# --- the gate ---------------------------------------------------------------------------------------

def test_the_gate_is_a_noop_when_oras_is_already_on_path(monkeypatch):
    # arrange: oras resolvable; any install attempt or download would be a failure
    monkeypatch.setattr(oras.shutil, "which", lambda tool: "/opt/homebrew/bin/oras")
    monkeypatch.setattr(oras, "_run_installer", _boom("installed"))
    monkeypatch.setattr(oras, "_fetch_release", _boom("downloaded"))

    # act / assert: returns silently
    oras.ensure_oras()


def test_the_package_manager_is_tried_before_the_download(monkeypatch, absent):
    # arrange: brew present and it works - _run_installer answers whether an oras appeared
    ran = []
    monkeypatch.setattr(oras.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(oras, "_have", lambda tool: tool == "brew")
    monkeypatch.setattr(oras, "_run_installer", lambda argv: ran.append(argv) or True)
    monkeypatch.setattr(oras, "_fetch_release", _boom("downloaded"))

    # act
    oras.ensure_oras()

    # assert: the manager ran, and nothing was downloaded
    assert ran == [["brew", "install", "oras"]]


def test_the_download_runs_where_no_package_manager_carries_oras(monkeypatch, absent):
    # arrange: Windows - no manager to try, so the pinned release is the only path
    fetched = []
    monkeypatch.setattr(oras.platform, "system", lambda: "Windows")
    monkeypatch.setattr(oras, "_have", lambda tool: True)
    monkeypatch.setattr(oras, "_run_installer", _boom("installed"))
    monkeypatch.setattr(oras, "_fetch_release", _fetch_writing(fetched))

    # act
    oras.ensure_oras()

    # assert: into the product-owned tool directory, under the host's binary name
    assert [p.name for p in fetched] == ["oras.exe"]


def test_a_package_manager_that_produces_no_oras_falls_back_to_the_download(monkeypatch, absent):
    # arrange: brew is there but the install leaves no binary (broken tap, offline mirror)
    fetched = []
    monkeypatch.setattr(oras.platform, "system", lambda: "Linux")
    monkeypatch.setattr(oras, "_have", lambda tool: tool == "brew")
    monkeypatch.setattr(oras, "_run_installer", lambda argv: False)
    monkeypatch.setattr(oras, "_fetch_release", _fetch_writing(fetched))

    # act
    oras.ensure_oras()

    # assert
    assert len(fetched) == 1


def test_the_installed_binary_goes_on_this_process_path(monkeypatch, absent):
    # arrange: nothing but the download may put oras within reach of this run
    monkeypatch.setattr(oras.platform, "system", lambda: "Linux")
    monkeypatch.setattr(oras, "_have", lambda tool: False)
    monkeypatch.setattr(oras, "_fetch_release", _fetch_writing([]))
    monkeypatch.setenv("PATH", "/usr/bin")

    # act
    oras.ensure_oras()

    # assert: the tool directory is FIRST, so this run finds the binary it just installed
    assert os.environ["PATH"].split(os.pathsep)[0] == str(oras.tools_bin())


def test_a_second_run_reuses_the_binary_it_already_downloaded(monkeypatch, absent):
    # arrange: the tool directory already holds an oras from an earlier run
    dest = oras.tools_bin() / "oras"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("#!/bin/sh\n")
    monkeypatch.setattr(oras.platform, "system", lambda: "Linux")
    monkeypatch.setattr(oras, "_have", lambda tool: False)
    monkeypatch.setattr(oras, "_fetch_release", _boom("downloaded again"))

    # act / assert: no second download
    oras.ensure_oras()


def test_a_download_that_produces_nothing_fails_naming_the_manual_fix(monkeypatch, absent):
    # arrange: the fetch silently leaves no file behind
    monkeypatch.setattr(oras.platform, "system", lambda: "Linux")
    monkeypatch.setattr(oras, "_have", lambda tool: False)
    monkeypatch.setattr(oras, "_fetch_release", lambda dest: None)

    # act / assert: the failure names where a human gets it, not merely that it is absent
    with pytest.raises(oras.OrasError, match="oras-project/oras"):
        oras.ensure_oras()
