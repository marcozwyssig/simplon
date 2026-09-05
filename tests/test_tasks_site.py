"""Unit tests for simplon.tasks.site (#2): the containerised Hugo site build, driven purely by the
manifest's `site` section and the product root, read through simplon.context - no product import and no
simplon path.

docker is stubbed, so these assert the DECISIONS (which data is read, what is refused, that the container
runs as the caller, when a green hugo still counts as a failure) rather than that docker works. The
end-to-end measurements - including what a run WITHOUT `--user` leaves behind - are in the task report.
AAA throughout.
"""
import os

import pytest

from simplon import context
from simplon.context import ProductContext
from simplon.run import Result
from simplon.tasks import site as site_task

_IMAGE = "hugomods/hugo:exts-0.148.2"
# A complete section, so each test can vary the ONE key it is about.
_SITE = {"image": _IMAGE, "source": "website", "output": "build/website",
         "base_url": "https://example.test/simplon/", "theme": "github.com/imfing/hextra@v0.9.6"}


def _register(monkeypatch, tmp_path, section=None):
    data = {"site": dict(_SITE if section is None else section)} if section != {} else {}
    ctx = ProductContext("sample", tmp_path, tmp_path / "sample.yaml")
    monkeypatch.setattr(context, "_current", ctx)
    monkeypatch.setattr(ProductContext, "manifest_data", lambda self: data)
    return ctx


def _docker(monkeypatch, present=True):
    monkeypatch.setattr(site_task.shutil, "which",
                        lambda name: "/usr/bin/docker" if present and name == "docker" else None)


def _stub_run(monkeypatch, rc=0, seen=None, writes=None):
    """A docker that records its argv, returns `rc`, and optionally writes `writes` (relative to the
    destination hugo was handed) - the way a real run either does or does not produce a site. The
    container path is mapped back to the host through the mount the argv itself carries, so a wrong
    mount or a wrong destination shows up as a build that produced nothing."""
    def fake(argv, **kwargs):
        if seen is not None:
            seen.append((argv, kwargs))
        if writes and "--destination" in argv:
            host, container = argv[argv.index("-v") + 1].split(":", 1)
            out = site_task.Path(host) / os.path.relpath(argv[argv.index("--destination") + 1], container)
            for name in writes:
                (out / name).parent.mkdir(parents=True, exist_ok=True)
                (out / name).write_text("<html></html>", encoding="utf-8")
        return Result(rc=rc, out="", err="")
    monkeypatch.setattr(site_task, "run", fake)
    return seen


# --- what the manifest says, and what it must say -------------------------------------------------------


def test_declared_reads_every_datum_from_the_manifest_section():
    # arrange: the five product data the task is not allowed to assume
    data = {"site": dict(_SITE)}

    # act
    cfg = site_task.declared(data)

    # assert
    assert cfg.image == _IMAGE
    assert cfg.source == "website"
    assert cfg.output == "build/website"
    assert cfg.base_url == "https://example.test/simplon/"
    assert cfg.theme == "github.com/imfing/hextra@v0.9.6"


def test_declared_refuses_a_manifest_without_the_section():
    # arrange: a command bound to this task in a product that never declared the data
    # act / assert
    with pytest.raises(ValueError, match="site"):
        site_task.declared({})


@pytest.mark.parametrize("missing", ["image", "source", "output"])
def test_declared_refuses_a_section_missing_a_required_key(missing):
    # arrange: the output path belongs to the product, and so does the generator - a kernel default for
    # either would be simplon's own choice imposed on every other product
    section = {key: value for key, value in _SITE.items() if key != missing}

    # act / assert
    with pytest.raises(ValueError, match=missing):
        site_task.declared({"site": section})


@pytest.mark.parametrize("image", ["hugomods/hugo", "hugomods/hugo:latest"])
def test_declared_refuses_an_image_that_does_not_pin_a_version(image):
    # arrange: a build whose output depends on when it ran is not a build - the refusal docs.py already
    # makes for the docToolchain tag. An untagged reference means ':latest' and moves just the same
    # act / assert
    with pytest.raises(ValueError, match="pin"):
        site_task.declared({"site": {**_SITE, "image": image}})


@pytest.mark.parametrize("image", ["registry.example:5000/hugo:0.148.2",
                                   "hugomods/hugo@sha256:9af903e2a217b51c80681247a740edf16d51bb2938"])
def test_declared_accepts_a_registry_port_and_a_digest_pin(image):
    # arrange: the tag is looked for in the LAST path segment, so a registry port is not mistaken for a
    # tag; a digest is the strongest form of the same statement and passes for free
    # act
    cfg = site_task.declared({"site": {**_SITE, "image": image}})

    # assert
    assert cfg.image == image


def test_declared_accepts_a_section_with_neither_theme_nor_base_url():
    # arrange: a site with a theme in its own repo needs no module, and a site served from a domain root
    # needs no baseURL override
    data = {"site": {"image": _IMAGE, "source": "website", "output": "build/website"}}

    # act
    cfg = site_task.declared(data)

    # assert
    assert (cfg.theme, cfg.base_url) == ("", "")


def test_declared_refuses_a_theme_module_without_a_pinned_version():
    # arrange: `hugo mod get` without a version fetches whatever is newest, so a published page would be
    # set by a theme nobody chose
    data = {"site": {**_SITE, "theme": "github.com/imfing/hextra"}}

    # act / assert
    with pytest.raises(ValueError, match="@"):
        site_task.declared(data)


# --- a tool that is MISSING: a hint, and rc 0 -----------------------------------------------------------


def test_build_is_a_hint_and_rc_0_when_docker_is_not_on_the_path(monkeypatch, tmp_path, capsys):
    # arrange: the 0.1.7 rule - a missing tool must not be the reason a run goes red. Deliberately NOT
    # docker.ensure_docker(), which dies: that gate is right for a step whose output is the point
    _register(monkeypatch, tmp_path)
    _docker(monkeypatch, present=False)
    seen = _stub_run(monkeypatch, seen=[])

    # act
    rc = site_task.build()

    # assert: nothing was attempted, and the hint names docker
    out = capsys.readouterr()
    assert rc == 0
    assert seen == []
    assert "docker" in out.out
    assert out.err == ""


def test_the_hint_names_the_one_tool_there_is_to_miss(monkeypatch, tmp_path, capsys):
    # arrange: in a container hugo, go and git cannot be missing separately - "which of the three?"
    # collapses into "is docker there?", and the hint says so by naming the image that carries them
    _register(monkeypatch, tmp_path)
    _docker(monkeypatch, present=False)
    _stub_run(monkeypatch)

    # act
    site_task.build()

    # assert
    out = capsys.readouterr().out
    assert _IMAGE in out
    assert "hugo is not" not in out


# --- the container the build runs in ----------------------------------------------------------------------


def test_build_runs_the_container_as_the_calling_user(monkeypatch, tmp_path):
    # arrange: the container writes into the bind-mounted product root, so the uid it runs as is the uid
    # that owns the output. Measured with hugomods/hugo (default user uid 0): without --user the run
    # wrote index.html as 0:0, the caller could not `rm -rf` its own build dir, and a root-owned
    # .hugo_build.lock stayed in the SOURCE tree - which then failed the next, correct run. #6 from the
    # other side
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    _docker(monkeypatch)
    seen = _stub_run(monkeypatch, seen=[], writes=["index.html"])

    # act
    site_task.build()

    # assert
    argv = seen[0][0]
    assert "--user" in argv, f"the site build must pass --user; got {argv}"
    assert argv[argv.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert argv.index("--user") < argv.index(_IMAGE)


def test_build_mounts_the_product_root_and_works_from_the_declared_source(monkeypatch, tmp_path):
    # arrange: deliberately not the names simplon's own site will use, so a hardcoded path fails here
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "doku/hugo", "output": "out/pages",
                                      "base_url": "https://elsewhere.test/x/"})
    _docker(monkeypatch)
    seen = _stub_run(monkeypatch, seen=[], writes=["index.html"])

    # act
    rc = site_task.build()

    # assert: the mount is the product root, and both paths inside the container come from the manifest
    assert rc == 0
    argv = seen[0][0]
    assert argv[argv.index("-v") + 1] == f"{tmp_path}:/project"
    assert argv[argv.index("-w") + 1] == "/project/doku/hugo"
    assert argv[argv.index("--destination") + 1] == "/project/out/pages"
    assert argv[argv.index("--baseURL") + 1] == "https://elsewhere.test/x/"


def test_build_uses_the_image_the_manifest_pins_and_no_other(monkeypatch, tmp_path):
    # arrange: the generator is the product's choice; the kernel only insists that it is pinned
    _register(monkeypatch, tmp_path, {"image": "registry.example:5000/hugo:0.148.2",
                                      "source": "website", "output": "build/website"})
    _docker(monkeypatch)
    seen = _stub_run(monkeypatch, seen=[], writes=["index.html"])

    # act
    site_task.build()

    # assert
    assert "registry.example:5000/hugo:0.148.2" in seen[0][0]
    assert not any(arg.startswith("hugomods/") for arg in seen[0][0])


def test_build_omits_the_base_url_flag_when_the_product_declares_none(monkeypatch, tmp_path):
    # arrange: an empty --baseURL would override the site config with nothing
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    _docker(monkeypatch)
    seen = _stub_run(monkeypatch, seen=[], writes=["index.html"])

    # act
    site_task.build()

    # assert
    assert "--baseURL" not in seen[0][0]


def test_build_pins_no_platform_because_that_is_the_images_business(monkeypatch, tmp_path):
    # arrange: docs.py pins linux/amd64 because ITS image publishes no arm64 variant - a fact about that
    # image, not about containers. Pinning it here would take the choice from the product that picked one
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    _docker(monkeypatch)
    seen = _stub_run(monkeypatch, seen=[], writes=["index.html"])

    # act
    site_task.build()

    # assert
    assert "--platform" not in seen[0][0]


# --- the theme module -------------------------------------------------------------------------------------


def test_build_fetches_the_pinned_theme_module_before_building(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path)
    _docker(monkeypatch)
    seen = _stub_run(monkeypatch, seen=[], writes=["index.html"])

    # act
    rc = site_task.build()

    # assert: the pin reaches `hugo mod get` verbatim, in the same image, from the site's own directory,
    # and BEFORE the build
    assert rc == 0
    argv = seen[0][0]
    assert argv[-3:] == ["mod", "get", "github.com/imfing/hextra@v0.9.6"]
    assert argv[argv.index("-w") + 1] == "/project/website"
    assert _IMAGE in argv
    assert len(seen) == 2


def test_build_runs_one_container_when_the_product_declares_no_module_theme(monkeypatch, tmp_path):
    # arrange: the module fetch is a consequence of the THEME being a module, not of building a site
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    _docker(monkeypatch)
    seen = _stub_run(monkeypatch, seen=[], writes=["index.html"])

    # act
    rc = site_task.build()

    # assert
    assert rc == 0
    assert len(seen) == 1
    assert "mod" not in seen[0][0]


# --- a tool that is PRESENT and FAILS: visible, and rc != 0 ----------------------------------------------


def test_build_is_red_when_the_module_fetch_fails(monkeypatch, tmp_path, capsys):
    # arrange: a present docker that cannot get the theme is a failure, not an absence
    _register(monkeypatch, tmp_path)
    _docker(monkeypatch)
    seen = _stub_run(monkeypatch, rc=1, seen=[])

    # act / assert: and the build itself is never attempted after it
    assert site_task.build() != 0
    assert "theme" in capsys.readouterr().err
    assert len(seen) == 1


def test_build_is_red_when_hugo_exits_non_zero(monkeypatch, tmp_path, capsys):
    # arrange
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    _docker(monkeypatch)
    _stub_run(monkeypatch, rc=1)

    # act / assert
    assert site_task.build() != 0
    assert _IMAGE in capsys.readouterr().err


def test_build_is_red_when_a_green_hugo_produced_no_index_html(monkeypatch, tmp_path, capsys):
    # arrange: hugo exits 0 on an empty content tree or a contentDir that points nowhere, leaving a
    # destination with no home page. Reporting that as a success is the defect 0.1.7 fixed in
    # allure.render_report, and it went unnoticed for two releases
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    _docker(monkeypatch)
    _stub_run(monkeypatch, rc=0, writes=["about/index.html"])   # sub-pages, but no home page

    # act / assert
    assert site_task.build() != 0
    assert "index.html" in capsys.readouterr().err


def test_build_clears_a_previous_output_tree_before_running_hugo(monkeypatch, tmp_path):
    # arrange: last run's index.html left in place would make an empty build look like a good one - the
    # very confusion the output check exists to prevent
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    stale = tmp_path / "build" / "website"
    stale.mkdir(parents=True)
    (stale / "index.html").write_text("the previous run", encoding="utf-8")
    _docker(monkeypatch)
    _stub_run(monkeypatch, rc=0)

    # act / assert: hugo wrote nothing this time, so the run is red rather than green on a stale file
    assert site_task.build() != 0
    assert not (stale / "index.html").exists()


def test_build_is_green_and_says_where_when_hugo_produced_a_site(monkeypatch, tmp_path, capsys):
    # arrange
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    _docker(monkeypatch)
    _stub_run(monkeypatch, rc=0, writes=["index.html"])

    # act
    rc = site_task.build()

    # assert
    out = capsys.readouterr()
    assert rc == 0
    assert "build/website" in out.out
    assert out.err == ""


# --- the outcome object, so a caller can tell the two no-site cases apart --------------------------------


def test_a_missing_docker_is_neither_ok_nor_failed(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path)
    _docker(monkeypatch, present=False)
    _stub_run(monkeypatch)

    # act
    built = site_task.build_site(site_task.declared({"site": dict(_SITE)}), tmp_path)

    # assert: nothing was built, but nothing was broken either
    assert (built.ok, built.failed, built.tool) == (False, False, None)


def test_a_present_docker_that_produced_nothing_is_failed(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path)
    _docker(monkeypatch)
    _stub_run(monkeypatch, rc=0)

    # act
    built = site_task.build_site(site_task.declared({"site": dict(_SITE)}), tmp_path)

    # assert
    assert (built.ok, built.failed, built.tool) == (False, True, "docker")
