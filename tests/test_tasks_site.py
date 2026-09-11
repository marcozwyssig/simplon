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
    # The site source EXISTS, the way it does in any product hugo could build from. A test tree without
    # it would exercise the "looked where there is nothing" path by accident, which is a real refusal
    # of its own and has its own test.
    if data:
        (tmp_path / data["site"].get("source", "website")).mkdir(parents=True, exist_ok=True)
    ctx = ProductContext("sample", tmp_path, tmp_path / "sample.yaml")
    monkeypatch.setattr(context, "_current", ctx)
    monkeypatch.setattr(ProductContext, "manifest_data", lambda self: data)
    return ctx


def _docker(monkeypatch, present=True):
    monkeypatch.setattr(site_task.shutil, "which",
                        lambda name: "/usr/bin/docker" if present and name == "docker" else None)


def _stub_run(monkeypatch, rc=0, seen=None, writes=None, mermaid_rc=0, mermaid_writes=True):
    """A docker that records its argv, returns `rc`, and optionally writes `writes` (relative to the
    destination hugo was handed) - the way a real run either does or does not produce a site. The
    container path is mapped back to the host through the mount the argv itself carries, so a wrong
    mount or a wrong destination shows up as a build that produced nothing.

    The MERMAID render is the same fake with its own verdict, told apart by the image in the argv:
    `mermaid_rc` is what mmdc exits with, and `mermaid_writes` says whether an SVG appears - the two are
    separate because a tool that exits 0 and writes nothing is a case this module treats as a failure
    everywhere else."""
    def fake(argv, **kwargs):
        if seen is not None:
            seen.append((argv, kwargs))
        if site_task.MERMAID_IMAGE in argv:
            if mermaid_rc == 0 and mermaid_writes:
                host, container = argv[argv.index("-v") + 1].split(":", 1)
                out = site_task.Path(host) / os.path.relpath(argv[argv.index("-o") + 1], container)
                out.write_text("<svg/>", encoding="utf-8")
            return Result(rc=mermaid_rc, out="", err="")
        if writes and "--destination" in argv:
            host, container = argv[argv.index("-v") + 1].split(":", 1)
            out = site_task.Path(host) / os.path.relpath(argv[argv.index("--destination") + 1], container)
            for name in writes:
                (out / name).parent.mkdir(parents=True, exist_ok=True)
                (out / name).write_text("<html></html>", encoding="utf-8")
        return Result(rc=rc, out="", err="")
    monkeypatch.setattr(site_task, "run", fake)
    return seen


#: The diagram si#45 measured, and the two single-character edits that make it invisible in a browser
#: while `build docs` stays rc 0 and the suite stays green.
_GOOD_DIAGRAM = """flowchart LR
  build["build"]
  test["test"]
  build -- "artefacts" --> test
  support["support"] -. "a host" .-> build
"""
_BROKEN_KEYWORD = _GOOD_DIAGRAM.replace("flowchart LR", "flowchrt LR")
_BROKEN_ARROW = _GOOD_DIAGRAM.replace(".-> build", ".->> build")


def _page(source, name, diagram=None):
    """A Markdown page under the site source, with a mermaid block when one is given. Returns the line
    the fence lands on, so a test asserts the number a reader is actually told."""
    body = "---\ntitle: \"x\"\n---\n\nsome prose\n"
    line = None
    if diagram is not None:
        line = len(body.splitlines()) + 1
        body += "```mermaid\n" + diagram + "```\n"
    page = source / name
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(body, encoding="utf-8")
    return line


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


@pytest.mark.parametrize("missing", ["image", "output"])
def test_declared_refuses_a_section_missing_a_required_key(missing):
    # arrange: the generator is the product's choice, and `output` is handed to a recursive delete - a
    # kernel default for either would be simplon's own choice imposed on every other product, and for
    # `output` it would be one imposed on `shutil.rmtree`
    section = {key: value for key, value in _SITE.items() if key != missing}

    # act / assert
    with pytest.raises(ValueError, match=missing):
        site_task.declared({"site": section})


def test_a_section_that_names_no_source_takes_the_documentation_root():
    """si#183: `docs/` is where documentation lives, so a product that says nothing lands there.

    The one key that gained a default, and the reason it is safe to give it one: `source` is only ever
    READ. The block on `site.DEFAULT_SOURCE` carries the census this was decided on.
    """
    # arrange: the four keys a product must still declare, and no `source`
    section = {key: value for key, value in _SITE.items() if key != "source"}

    # act
    cfg = site_task.declared({"site": section})

    # assert
    assert cfg.source == "docs/site"
    assert cfg.source == site_task.DEFAULT_SOURCE


def test_a_section_that_names_a_source_keeps_it():
    """The default is SOFT, which is the whole difference between it and a rule. Measured on the two
    real products it has to leave alone: cleon declares `site`, biz-cockpit declares `docs/website`.
    """
    # arrange / act / assert
    for declared_path in ("site", "docs/website"):
        cfg = site_task.declared({"site": {**_SITE, "source": declared_path}})
        assert cfg.source == declared_path


@pytest.mark.parametrize("bad", ["", "   ", 3])
def test_a_source_that_is_present_and_broken_is_still_refused(bad):
    """An ABSENT key takes the convention; a key that is there is ruled on. `source: ""` is a mistake
    somebody made, not a decision to use the default, and a default that swallowed it would build the
    documentation root while the manifest said something else.
    """
    # arrange / act / assert
    with pytest.raises(ValueError, match="source"):
        site_task.declared({"site": {**_SITE, "source": bad}})


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


# --- the diagram render gate (si#45) ----------------------------------------------------------------


def test_the_block_scanner_finds_the_fence_and_the_line_a_reader_has_to_open():
    # arrange: a page with prose before the diagram, so the line number is a real one rather than 1
    text = "---\ntitle: \"x\"\n---\n\nprose\n\n```mermaid\nflowchart LR\n  a --> b\n```\n\nmore prose\n"

    # act
    found = site_task.diagrams_in(text, site_task.Path("site/content/x.md"))

    # assert: one block, the fence's own line, and the body without the fences
    assert len(found) == 1
    assert found[0].line == 7
    assert found[0].body == "flowchart LR\n  a --> b"
    assert text.splitlines()[found[0].line - 1] == "```mermaid"


def test_the_block_scanner_closes_each_block_at_its_own_fence():
    # arrange: two blocks with prose between them. A regex that ends at the first ``` it finds would
    # check the GAP between them and report two green diagrams having rendered neither
    text = "```mermaid\nflowchart LR\n  a --> b\n```\n\nprose\n\n```mermaid\nflowchart TD\n  c --> d\n```\n"

    # act
    found = site_task.diagrams_in(text, site_task.Path("x.md"))

    # assert
    assert [d.line for d in found] == [1, 8]
    assert [d.body.splitlines()[0] for d in found] == ["flowchart LR", "flowchart TD"]


def test_the_scanner_ignores_a_fence_that_is_not_mermaid():
    # arrange: the phases chapter carries a ```text block beside its diagram
    text = "```text\nmyctl build wheel\n```\n\n```mermaid\nflowchart LR\n  a --> b\n```\n"

    # act
    found = site_task.diagrams_in(text, site_task.Path("x.md"))

    # assert
    assert len(found) == 1
    assert found[0].body.startswith("flowchart")


def test_the_sweep_skips_the_directories_hugo_owns_rather_than_the_author(tmp_path):
    # arrange: a diagram somebody else shipped - in the module cache, the asset cache or a previous
    # destination - is not this build's to fail on
    source = tmp_path / "site"
    _page(source, "content/mine.md", _GOOD_DIAGRAM)
    for owned in ("resources", "public", "_vendor", "node_modules", ".git"):
        _page(source, f"{owned}/theirs.md", _BROKEN_KEYWORD)

    # act
    found = site_task.diagrams_under(source)

    # assert
    assert [d.page.name for d in found] == ["mine.md"]


def test_a_build_whose_diagram_does_not_render_is_red_and_names_the_page_and_the_line(monkeypatch,
                                                                                     tmp_path, capsys):
    # arrange: `flowchart` -> `flowchrt`, one of the two single-character errors si#45 measured. Hugo
    # emits the block whatever it says, so rc 0 and a full page count prove nothing about the picture
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    line = _page(tmp_path / "website", "content/building/phases.md", _BROKEN_KEYWORD)
    _docker(monkeypatch)
    _stub_run(monkeypatch, rc=0, writes=["index.html"], mermaid_rc=1)

    # act
    rc = site_task.build()

    # assert: red, and the message names the file and the line an author opens
    err = capsys.readouterr().err
    assert rc != 0
    assert f"content/building/phases.md:{line}" in err


def test_the_other_single_character_error_is_red_too(monkeypatch, tmp_path, capsys):
    # arrange: `.->` -> `.->>`. A different failure inside mermaid (a parse error rather than an
    # unknown diagram type) and the same consequence: nothing is drawn
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    _page(tmp_path / "website", "content/x.md", _BROKEN_ARROW)
    _docker(monkeypatch)
    _stub_run(monkeypatch, rc=0, writes=["index.html"], mermaid_rc=1)

    # act / assert
    assert site_task.build() != 0
    assert "content/x.md" in capsys.readouterr().err


def test_a_mermaid_that_exits_zero_and_writes_no_svg_is_red_as_well(monkeypatch, tmp_path, capsys):
    # arrange: the shape `allure.render_report` reported as success for two releases, one level down -
    # a tool that was there, said nothing and produced nothing
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    _page(tmp_path / "website", "content/x.md", _GOOD_DIAGRAM)
    _docker(monkeypatch)
    _stub_run(monkeypatch, rc=0, writes=["index.html"], mermaid_rc=0, mermaid_writes=False)

    # act / assert
    assert site_task.build() != 0
    assert "does not render" in capsys.readouterr().err


def test_a_build_whose_diagram_renders_is_green_and_says_how_many(monkeypatch, tmp_path, capsys):
    # arrange
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    _page(tmp_path / "website", "content/a.md", _GOOD_DIAGRAM)
    _page(tmp_path / "website", "content/b.md", _GOOD_DIAGRAM)
    _docker(monkeypatch)
    _stub_run(monkeypatch, rc=0, writes=["index.html"])

    # act
    rc = site_task.build()

    # assert: green, and the count is printed - "2 rendered" is a different statement from "none found"
    out = capsys.readouterr()
    assert rc == 0
    assert "2 mermaid diagram(s) render" in out.out
    assert out.err == ""


def test_a_build_with_no_diagram_at_all_is_green_and_says_there_was_nothing_to_check(monkeypatch,
                                                                                    tmp_path, capsys):
    # arrange: ACCEPTANCE 2, and the harder half of si#45. Building the cure for "nothing to do is not
    # the same as failed" and then leaving the empty case to be inferred from silence would have
    # reproduced the very defect - so the build says which of the two green it is
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    _page(tmp_path / "website", "content/prose-only.md")
    _docker(monkeypatch)
    seen = _stub_run(monkeypatch, rc=0, seen=[], writes=["index.html"])

    # act
    rc = site_task.build()

    # assert: green, said out loud, and NOT claiming that anything was checked
    out = capsys.readouterr()
    assert rc == 0
    assert "no mermaid diagram" in out.out
    assert "nothing to render-check" in out.out
    assert "diagram(s) render" not in out.out
    assert out.err == ""

    # assert: and the second image was never pulled, because there was nothing to render
    assert not any(site_task.MERMAID_IMAGE in argv for argv, _ in seen)


def test_the_three_states_of_the_gate_are_distinguishable_by_the_caller(monkeypatch, tmp_path):
    # arrange: None = the gate never ran, 0 = it ran and found nothing, n = it rendered n. A caller
    # handed only a boolean could not tell the first two apart, which is the whole complaint
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    cfg = site_task.declared({"site": {"image": _IMAGE, "source": "website", "output": "build/website"}})

    # act / assert: no docker at all - nothing ran
    _docker(monkeypatch, present=False)
    _stub_run(monkeypatch)
    assert site_task.build_site(cfg, tmp_path).diagrams is None

    # act / assert: docker, a site, and no diagram in it
    _page(tmp_path / "website", "content/prose-only.md")
    _docker(monkeypatch)
    _stub_run(monkeypatch, rc=0, writes=["index.html"])
    assert site_task.build_site(cfg, tmp_path).diagrams == 0

    # act / assert: docker, a site, and a diagram that renders
    _page(tmp_path / "website", "content/with.md", _GOOD_DIAGRAM)
    _stub_run(monkeypatch, rc=0, writes=["index.html"])
    built = site_task.build_site(cfg, tmp_path)
    assert (built.diagrams, built.broken, built.ok) == (1, (), True)


def test_the_render_runs_as_the_caller_in_the_pinned_image_on_its_own_mount(monkeypatch, tmp_path):
    # arrange: the container writes the SVG into a mounted directory, so `--user` for the reason
    # docker.user_args documents; its OWN mount, because a render must not be able to write into the
    # tree it is checking; and no --entrypoint, because THIS image's entrypoint carries the puppeteer
    # config without which mmdc cannot find chromium at all (measured: `Could not find Chrome`, rc 1,
    # for a diagram that is perfectly fine)
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    _page(tmp_path / "website", "content/x.md", _GOOD_DIAGRAM)
    _docker(monkeypatch)
    seen = _stub_run(monkeypatch, rc=0, seen=[], writes=["index.html"])

    # act
    site_task.build()

    # assert
    argv = next(argv for argv, _ in seen if site_task.MERMAID_IMAGE in argv)
    assert argv[argv.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert argv.index("--user") < argv.index(site_task.MERMAID_IMAGE)
    assert "--entrypoint" not in argv
    assert argv[argv.index("-v") + 1].split(":")[0] != str(tmp_path)
    assert argv[argv.index("-i") + 1].startswith(str(site_task.MERMAID_MOUNT))


def test_the_gate_runs_after_the_site_is_built_and_not_instead_of_it(monkeypatch, tmp_path):
    # arrange: a hugo that fails must not also be reported as a diagram problem - the first failure is
    # the one worth reading, and rendering diagrams for a site that does not exist tells nobody anything
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    _page(tmp_path / "website", "content/x.md", _BROKEN_KEYWORD)
    _docker(monkeypatch)
    seen = _stub_run(monkeypatch, rc=1, seen=[])

    # act / assert
    assert site_task.build() != 0
    assert not any(site_task.MERMAID_IMAGE in argv for argv, _ in seen)


# --- the gate's own "nothing to do" is not allowed to be ambiguous either (si#45, review) -----------


def test_a_source_directory_that_is_not_there_is_red_rather_than_nothing_to_check(monkeypatch,
                                                                                  tmp_path, capsys):
    # arrange: the abhilfe against "nothing to do is not failed" had the defect one level up - a source
    # that does not exist walked no page, found no diagram and reported the green that means "checked,
    # and there was nothing". The build is otherwise perfect: hugo exits 0 and writes a home page
    _register(monkeypatch, tmp_path, {"image": _IMAGE, "source": "website", "output": "build/website"})
    (tmp_path / "website").rmdir()
    _docker(monkeypatch)
    _stub_run(monkeypatch, rc=0, writes=["index.html"])

    # act
    rc = site_task.build()

    # act / assert: red, and the message says which of the two answers it is refusing to give
    out = capsys.readouterr()
    assert rc != 0
    assert "not a directory" in out.err
    assert "nothing to render-check" not in out.out


def test_the_scanner_refuses_to_walk_a_directory_that_is_not_there(tmp_path):
    # arrange: the guard sits at the seam, so a caller other than build_site cannot get the ambiguous
    # answer either
    # act / assert
    with pytest.raises(NotADirectoryError):
        site_task.diagrams_under(tmp_path / "never-existed")


def test_a_build_that_never_ran_the_gate_is_not_ok(monkeypatch, tmp_path):
    # arrange: `diagrams=None` means "no verdict". A Build with a home page and no verdict must not be
    # ok, or `build()` prints one of its two greens over a gate that never ran - the same value meaning
    # different things on the two sides of a seam
    page = tmp_path / "index.html"

    # act / assert
    assert site_task.Build(index=page, tool="docker").ok is False
    assert site_task.Build(index=page, tool="docker").failed is True
    assert site_task.Build(index=page, tool="docker", diagrams=0).ok is True


# --- the fence scanner, at the shapes that made it lie (si#45, review) ------------------------------


def test_a_mermaid_example_inside_a_markdown_block_is_not_a_diagram():
    # arrange: a page that DOCUMENTS mermaid syntax. Reading the inner fence as a real diagram makes the
    # build red for a picture nobody drew - a false red is worse than the false green it replaced
    text = ("````markdown\n"
            "```mermaid\n"
            "flowchrt LR\n"
            "```\n"
            "````\n")

    # act
    found = site_task.diagrams_in(text, site_task.Path("x.md"))

    # assert
    assert found == []


def test_a_tilde_fence_and_an_attribute_list_are_still_diagrams():
    # arrange: both are ordinary Markdown, and a scanner that only knows ```mermaid on its own would
    # pass a broken diagram straight through - the false green the gate exists to end
    text = ("~~~mermaid\nflowchart LR\n  a --> b\n~~~\n"
            "\n"
            "```mermaid {class=\"big\"}\nflowchart TD\n  c --> d\n```\n")

    # act
    found = site_task.diagrams_in(text, site_task.Path("x.md"))

    # assert
    assert [d.line for d in found] == [1, 6]
    assert [d.body.splitlines()[0] for d in found] == ["flowchart LR", "flowchart TD"]


def test_a_longer_fence_is_closed_by_a_longer_fence_and_not_by_a_shorter_one():
    # arrange: CommonMark's rule, and the reason the scanner walks every block rather than only its own
    text = "````mermaid\nflowchart LR\n```\n  a --> b\n````\n"

    # act
    found = site_task.diagrams_in(text, site_task.Path("x.md"))

    # assert: one block, and the three-backtick line is part of it rather than its end
    assert len(found) == 1
    assert found[0].body == "flowchart LR\n```\n  a --> b"


# --- the cache that makes a second build possible without a network (si#27) --------------------------------


def test_every_hugo_run_is_handed_a_cache_that_outlives_the_container(monkeypatch, tmp_path):
    # arrange: `docker run --rm` with only the product root mounted left hugo's cache inside the
    # container, so both the module fetch AND the build itself went to the network on every run - si#27's
    # finding, and the reason a build in a train or during a GitHub outage was impossible
    _register(monkeypatch, tmp_path)
    _docker(monkeypatch)
    seen = _stub_run(monkeypatch, seen=[], writes=["index.html"])

    # act
    rc = site_task.build()

    # assert: BOTH runs get it - the fetch and the build resolve the theme module separately, and a cache
    # on only one of them leaves the other going to the network
    assert rc == 0
    assert len(seen) == 2
    for argv, _kwargs in seen:
        assert "-e" in argv, f"no environment reaches hugo in {argv}"
        assert f"HUGO_CACHEDIR={site_task.MOUNT / site_task.CACHE_DIR}" in argv, argv

    # assert: and it is a path inside the mount, so the container writes it into the product tree rather
    # than into a layer that goes away with `--rm`
    assert str(site_task.CACHE_DIR).startswith("build")


def test_the_cache_directory_exists_on_the_host_before_hugo_is_told_about_it(monkeypatch, tmp_path):
    # arrange: a HUGO_CACHEDIR that is not there is handed to a container running as the caller's uid,
    # which cannot create it under a root-owned parent - the failure `--user` exists to avoid, reached
    # from the other side
    _register(monkeypatch, tmp_path)
    _docker(monkeypatch)
    _stub_run(monkeypatch, writes=["index.html"])

    # act
    rc = site_task.build()

    # assert
    assert rc == 0
    assert (tmp_path / site_task.CACHE_DIR).is_dir()


def test_the_cache_survives_the_wipe_of_the_destination(monkeypatch, tmp_path):
    # arrange: the destination is cleared before every build, and a cache cleared with it would send the
    # next run back to the network without a word - the whole point of si#27 undone by the neighbouring
    # step. A product whose output is `build/website` keeps both, which is the normal shape.
    _register(monkeypatch, tmp_path)
    _docker(monkeypatch)
    _stub_run(monkeypatch, writes=["index.html"])
    kept = tmp_path / site_task.CACHE_DIR / "modules" / "warm"
    kept.parent.mkdir(parents=True)
    kept.write_text("cached", encoding="utf-8")

    # act
    rc = site_task.build()

    # assert
    assert rc == 0
    assert kept.read_text(encoding="utf-8") == "cached"


def test_a_product_whose_output_swallows_the_cache_still_gets_a_directory(monkeypatch, tmp_path):
    # arrange: `output: build` puts the destination ON TOP of the cache, so the wipe takes it. That
    # product pays a cold cache every run - the behaviour it had before si#27 - but hugo must never be
    # handed a HUGO_CACHEDIR that is not there, and the recreation is what guarantees it. Stated rather
    # than refused: it is a real manifest a product may write, and a cold cache is slow, not wrong.
    _register(monkeypatch, tmp_path, {**_SITE, "output": "build"})
    _docker(monkeypatch)
    _stub_run(monkeypatch, writes=["index.html"])

    # act
    rc = site_task.build()

    # assert
    assert rc == 0
    assert (tmp_path / site_task.CACHE_DIR).is_dir()


def test_the_diagram_sweep_does_not_read_the_theme_out_of_the_cache(tmp_path):
    # arrange: the cache now holds the theme module's OWN Markdown, inside the product root. A product
    # whose site source is the product root would otherwise have every hextra page swept for diagrams,
    # and a broken one in somebody else's theme would fail this product's build
    source = tmp_path
    _page(source, "content/mine.md", _GOOD_DIAGRAM)
    _page(source, f"{site_task.CACHE_DIR}/modules/theirs.md", _BROKEN_KEYWORD)

    # act
    found = site_task.diagrams_under(source)

    # assert
    assert [d.page.name for d in found] == ["mine.md"]
