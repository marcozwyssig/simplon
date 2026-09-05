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


# --- the wipe is not best-effort (review finding 1) -------------------------------------------------------


@pytest.mark.skipif(not hasattr(os, "getuid") or os.getuid() == 0,
                    reason="the block is a DIRECTORY permission: root ignores it and Windows has no "
                           "equivalent, so only an unprivileged posix run can reproduce the case")
def test_build_is_red_when_the_output_tree_cannot_be_cleared(monkeypatch, tmp_path, capsys):
    # arrange: the real thing, not a stubbed rmtree - a destination the caller cannot delete FROM, which
    # is what a container that ran without --user leaves behind (it creates the directories itself,
    # root-owned and 0755, and unlinking an entry needs write permission on the DIRECTORY that holds it).
    # 0555 reproduces exactly that block without needing root or docker. Plus a hugo that exits 0 and
    # writes nothing: with an ignore_errors wipe the tree simply stays, hugo "succeeds", and the check
    # for index.html finds the PREVIOUS run's home page - rc 0 for a site this build did not produce
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    out = tmp_path / "build" / "website"
    out.mkdir(parents=True)
    (out / "index.html").write_text("the previous run", encoding="utf-8")
    out.chmod(0o555)
    _docker(monkeypatch)
    seen = _stub_run(monkeypatch, rc=0, seen=[])

    # act
    try:
        rc = site_task.build()
    finally:
        out.chmod(0o755)          # so the temp tree can be cleaned up afterwards

    # assert: red, hugo was never asked to build over a tree that is still standing, and the stale page
    # is still there - which is precisely why a green verdict here would have been a lie
    assert rc != 0
    assert seen == []
    assert "clear" in capsys.readouterr().err
    assert (out / "index.html").read_text(encoding="utf-8") == "the previous run"


def test_a_first_build_with_no_output_tree_yet_is_not_a_failure(monkeypatch, tmp_path):
    # arrange: nothing to clear is the normal first-build case, not an error
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    _docker(monkeypatch)
    _stub_run(monkeypatch, rc=0, writes=["index.html"])

    # act / assert
    assert site_task.build() == 0


# --- a manifest path stays under the product root (review finding 2) --------------------------------------


@pytest.mark.parametrize("key", ["source", "output"])
@pytest.mark.parametrize("bad", ["/var/tmp/x", "../sibling", "build/../../escape", "C:/drive/site",
                                 "build\\website", "build//website", "build/./website", ".", ".."])
def test_declared_refuses_a_path_that_leaves_the_product_root(key, bad):
    # arrange: `root / value` collapses onto an absolute value, and `output` is then handed to rmtree -
    # `output: /var/tmp/x` would DELETE /var/tmp/x. The manifest is the product's, but a typo with a slash
    # in front of it must not delete a directory outside the project. Same rule as `--orch-dir` (#4)
    # act / assert
    with pytest.raises(ValueError, match=key):
        site_task.declared({"site": {**_SITE, key: bad}})


def test_the_refusal_of_an_escaping_path_names_the_value_and_the_rule():
    # arrange / act
    with pytest.raises(ValueError) as excinfo:
        site_task.declared({"site": {**_SITE, "output": "/var/tmp/x"}})

    # assert: actionable without reading the source
    message = str(excinfo.value)
    assert "/var/tmp/x" in message
    assert "relative" in message.lower()


def test_declared_normalises_a_trailing_slash_rather_than_refusing_it():
    # arrange: a trailing slash is a typo, not an escape - it does not deserve a refusal
    # act
    cfg = site_task.declared({"site": {**_SITE, "output": "build/website/"}})

    # assert
    assert cfg.output == "build/website"


# --- the theme pin is the same rule as the image pin (review finding 3) -----------------------------------


@pytest.mark.parametrize("theme", ["github.com/imfing/hextra@latest",
                                   "github.com/imfing/hextra@master",
                                   "github.com/imfing/hextra@main",
                                   "github.com/imfing/hextra@upgrade",
                                   "github.com/imfing/hextra@",
                                   "@",
                                   "@v0.9.6"])
def test_declared_refuses_a_theme_whose_version_is_a_moving_query(theme):
    # arrange: checking only for an '@' lets all of these through, and `hugo mod get x@latest` fetches
    # exactly the moving thing the pin exists to exclude - so the rule was not the same rule as the image
    # pin, however loudly the comment said it was
    # act / assert
    with pytest.raises(ValueError, match="theme"):
        site_task.declared({"site": {**_SITE, "theme": theme}})


@pytest.mark.parametrize("theme", ["github.com/imfing/hextra@v0.9.6",
                                   "github.com/imfing/hextra@v1.2.3-rc.1",
                                   "github.com/imfing/hextra@v2",
                                   "github.com/imfing/hextra@3c9f2ab"])
def test_declared_accepts_a_version_tag_or_a_commit(theme):
    # arrange: the two forms that name one revision for good
    # act
    cfg = site_task.declared({"site": {**_SITE, "theme": theme}})

    # assert
    assert cfg.theme == theme


# --- the image pin, at its edges (review, minor) ----------------------------------------------------------


@pytest.mark.parametrize("image", ["hugomods/hugo:", "hugomods/hugo::"])
def test_declared_refuses_an_image_reference_that_only_looks_pinned(image):
    # arrange: an empty tag reads as pinned to a careless eye, and fails later in docker with a worse
    # message than this one
    # act / assert
    with pytest.raises(ValueError, match="image"):
        site_task.declared({"site": {**_SITE, "image": image}})


@pytest.mark.parametrize("image", ["my.image:1.0", "hugo.mods:0.148.2", "a.b.c:1.0",
                                   "registry.example:5000"])
def test_declared_accepts_a_dotted_name_with_no_slash_because_docker_reads_it_as_image_plus_tag(image):
    # arrange: a first component is a REGISTRY only when a '/' follows it (or it is 'localhost') - that is
    # docker's own rule. Without a slash there is no registry, dot or no dot, so all of these are an image
    # with a tag and refusing them rejects valid input. `registry.example:5000` rides along: docker reads
    # '5000' as a tag there too, and no rule can tell that from a version without guessing
    # act
    cfg = site_task.declared({"site": {**_SITE, "image": image}})

    # assert
    assert cfg.image == image


def test_the_required_keys_are_checked_before_the_optional_theme():
    # arrange: a section missing `image` altogether should say so, not complain about the theme it also
    # got wrong
    section = {"source": "website", "output": "build/website", "theme": "github.com/imfing/hextra"}

    # act / assert
    with pytest.raises(ValueError, match="image"):
        site_task.declared({"site": section})
