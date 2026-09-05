"""Unit tests for simplon.tasks.site (#2): the Hugo site build, driven purely by the manifest's `site`
section and the product root, read through simplon.context - no product import and no simplon path.

hugo is stubbed, so these assert the DECISIONS (which data is read, what is refused, which of the two
tools is reported missing, when a green hugo still counts as a failure) rather than that hugo works.
AAA throughout.
"""
import pytest

from simplon import context
from simplon.context import ProductContext
from simplon.run import Result
from simplon.tasks import site as site_task

# A complete section, so each test can vary the ONE key it is about.
_SITE = {"source": "website", "output": "build/website", "base_url": "https://example.test/simplon/",
         "theme": "github.com/imfing/hextra@v0.9.6"}


def _register(monkeypatch, tmp_path, section=None):
    data = {"site": dict(_SITE if section is None else section)} if section != {} else {}
    ctx = ProductContext("sample", tmp_path, tmp_path / "sample.yaml")
    monkeypatch.setattr(context, "_current", ctx)
    monkeypatch.setattr(ProductContext, "manifest_data", lambda self: data)
    return ctx


def _tools(monkeypatch, *present):
    """Which of hugo/go the host has, and nothing else."""
    monkeypatch.setattr(site_task.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name in present else None)


def _stub_hugo(monkeypatch, rc=0, seen=None, writes=None):
    """A hugo that records its argv, returns `rc`, and optionally writes `writes` (relative to the
    destination it was handed) - the way the real one either does or does not produce a site."""
    def fake(argv, **kwargs):
        if seen is not None:
            seen.append((argv, kwargs))
        if writes and "--destination" in argv:
            out = site_task.Path(argv[argv.index("--destination") + 1])
            for name in writes:
                (out / name).parent.mkdir(parents=True, exist_ok=True)
                (out / name).write_text("<html></html>", encoding="utf-8")
        return Result(rc=rc, out="", err="")
    monkeypatch.setattr(site_task, "run", fake)
    return seen


# --- what the manifest says, and what it must say -------------------------------------------------------


def test_declared_reads_every_datum_from_the_manifest_section():
    # arrange: the four product data the task is not allowed to assume
    data = {"site": {"source": "website", "output": "build/website",
                     "base_url": "https://example.test/simplon/",
                     "theme": "github.com/imfing/hextra@v0.9.6"}}

    # act
    cfg = site_task.declared(data)

    # assert
    assert cfg.source == "website"
    assert cfg.output == "build/website"
    assert cfg.base_url == "https://example.test/simplon/"
    assert cfg.theme == "github.com/imfing/hextra@v0.9.6"


def test_declared_refuses_a_manifest_without_the_section():
    # arrange: a command bound to this task in a product that never declared the data
    # act / assert
    with pytest.raises(ValueError, match="site"):
        site_task.declared({})


def test_declared_refuses_a_section_without_a_source():
    # arrange
    data = {"site": {"output": "build/website"}}

    # act / assert
    with pytest.raises(ValueError, match="source"):
        site_task.declared(data)


def test_declared_refuses_a_section_without_an_output():
    # arrange: the output path belongs to the product; a kernel default would be a simplon convention
    # imposed on every other product
    data = {"site": {"source": "website"}}

    # act / assert
    with pytest.raises(ValueError, match="output"):
        site_task.declared(data)


def test_declared_accepts_a_section_with_neither_theme_nor_base_url():
    # arrange: a site with a theme in its own repo needs no module and no Go, and a site served from a
    # domain root needs no baseURL override
    data = {"site": {"source": "website", "output": "build/website"}}

    # act
    cfg = site_task.declared(data)

    # assert
    assert (cfg.theme, cfg.base_url) == ("", "")


def test_declared_refuses_a_theme_module_without_a_pinned_version():
    # arrange: `hugo mod get` without a version fetches whatever is newest, so a published page would be
    # set by a theme nobody chose - the same refusal docs.py makes for an unpinned image tag
    data = {"site": {"source": "website", "output": "build/website", "theme": "github.com/imfing/hextra"}}

    # act / assert
    with pytest.raises(ValueError, match="@"):
        site_task.declared(data)


# --- a tool that is MISSING: a hint, and rc 0 -----------------------------------------------------------


def test_build_is_a_hint_and_rc_0_when_hugo_is_not_on_the_path(monkeypatch, tmp_path, capsys):
    # arrange: the 0.1.7 rule - a missing tool must not be the reason a run goes red
    _register(monkeypatch, tmp_path)
    _tools(monkeypatch)
    seen = _stub_hugo(monkeypatch, seen=[])

    # act
    rc = site_task.build()

    # assert: nothing was attempted, and the hint names hugo
    out = capsys.readouterr()
    assert rc == 0
    assert seen == []
    assert "hugo" in out.out
    assert out.err == ""


def test_build_names_GO_and_not_hugo_when_a_module_theme_meets_a_host_without_go(
        monkeypatch, tmp_path, capsys):
    # arrange: hugo IS there; what is missing is the Go the module fetch needs. Two causes under one
    # message would be half a message - a reader would go looking for the tool that is already installed
    _register(monkeypatch, tmp_path)
    _tools(monkeypatch, "hugo")
    seen = _stub_hugo(monkeypatch, seen=[])

    # act
    rc = site_task.build()

    # assert
    out = capsys.readouterr()
    assert rc == 0
    assert seen == []
    assert "go" in out.out.lower()
    assert "hugo is not" not in out.out


def test_build_needs_no_go_when_the_product_declares_no_module_theme(monkeypatch, tmp_path):
    # arrange: Go is a consequence of the THEME being a Hugo module, not of building a site
    _register(monkeypatch, tmp_path, {"source": "website", "output": "build/website"})
    _tools(monkeypatch, "hugo")
    seen = _stub_hugo(monkeypatch, seen=[], writes=["index.html"])

    # act
    rc = site_task.build()

    # assert: the build ran, and it ran ONLY hugo (no module fetch)
    assert rc == 0
    assert len(seen) == 1
    assert "mod" not in seen[0][0]


# --- the build itself ------------------------------------------------------------------------------------


def test_build_fetches_the_pinned_theme_module_before_building(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path)
    _tools(monkeypatch, "hugo", "go")
    seen = _stub_hugo(monkeypatch, seen=[], writes=["index.html"])

    # act
    rc = site_task.build()

    # assert: the pin reaches `hugo mod get` verbatim, from the site's own directory, and BEFORE the build
    assert rc == 0
    argv, kwargs = seen[0]
    assert argv == ["hugo", "mod", "get", "github.com/imfing/hextra@v0.9.6"]
    assert kwargs["cwd"] == str(tmp_path / "website")


def test_build_passes_the_manifests_paths_and_base_url_and_assumes_none_of_them(monkeypatch, tmp_path):
    # arrange: deliberately not the names simplon's own site will use, so a hardcoded path fails here
    _register(monkeypatch, tmp_path, {"source": "doku/hugo", "output": "out/pages",
                                      "base_url": "https://elsewhere.test/x/"})
    _tools(monkeypatch, "hugo")
    seen = _stub_hugo(monkeypatch, seen=[], writes=["index.html"])

    # act
    rc = site_task.build()

    # assert
    assert rc == 0
    argv = seen[0][0]
    assert argv[argv.index("--source") + 1] == str(tmp_path / "doku" / "hugo")
    assert argv[argv.index("--destination") + 1] == str(tmp_path / "out" / "pages")
    assert argv[argv.index("--baseURL") + 1] == "https://elsewhere.test/x/"


def test_build_omits_the_base_url_flag_when_the_product_declares_none(monkeypatch, tmp_path):
    # arrange: an empty --baseURL would override the site config with nothing
    _register(monkeypatch, tmp_path, {"source": "website", "output": "build/website"})
    _tools(monkeypatch, "hugo")
    seen = _stub_hugo(monkeypatch, seen=[], writes=["index.html"])

    # act
    site_task.build()

    # assert
    assert "--baseURL" not in seen[0][0]


def test_build_clears_a_previous_output_tree_before_running_hugo(monkeypatch, tmp_path):
    # arrange: last run's index.html left in place would make an empty build look like a good one - the
    # very confusion this task's output check exists to prevent
    _register(monkeypatch, tmp_path, {"source": "website", "output": "build/website"})
    stale = tmp_path / "build" / "website"
    stale.mkdir(parents=True)
    (stale / "index.html").write_text("the previous run", encoding="utf-8")
    _tools(monkeypatch, "hugo")
    _stub_hugo(monkeypatch, rc=0)

    # act / assert: hugo wrote nothing this time, so the run is red rather than green on a stale file
    assert site_task.build() != 0
    assert not (stale / "index.html").exists()


# --- a tool that is PRESENT and FAILS: visible, and rc != 0 ----------------------------------------------


def test_build_is_red_when_hugo_is_present_and_exits_non_zero(monkeypatch, tmp_path, capsys):
    # arrange
    _register(monkeypatch, tmp_path, {"source": "website", "output": "build/website"})
    _tools(monkeypatch, "hugo")
    _stub_hugo(monkeypatch, rc=1)

    # act / assert
    assert site_task.build() != 0
    assert "hugo" in capsys.readouterr().err


def test_build_is_red_when_the_module_fetch_fails(monkeypatch, tmp_path, capsys):
    # arrange: a present hugo that cannot get the theme is a failure, not an absence
    _register(monkeypatch, tmp_path)
    _tools(monkeypatch, "hugo", "go")
    _stub_hugo(monkeypatch, rc=1)

    # act / assert
    assert site_task.build() != 0
    assert "theme" in capsys.readouterr().err


def test_build_is_red_when_a_green_hugo_produced_no_index_html(monkeypatch, tmp_path, capsys):
    # arrange: hugo exits 0 on an empty content tree or a contentDir that points nowhere, leaving a
    # destination with no home page. Reporting that as a success is the defect 0.1.7 fixed in
    # allure.render_report, and it went unnoticed for two releases
    _register(monkeypatch, tmp_path, {"source": "website", "output": "build/website"})
    _tools(monkeypatch, "hugo")
    _stub_hugo(monkeypatch, rc=0, writes=["about/index.html"])   # sub-pages, but no home page

    # act / assert
    assert site_task.build() != 0
    assert "index.html" in capsys.readouterr().err


def test_build_is_green_and_says_where_when_hugo_produced_a_site(monkeypatch, tmp_path, capsys):
    # arrange
    _register(monkeypatch, tmp_path, {"source": "website", "output": "build/website"})
    _tools(monkeypatch, "hugo")
    _stub_hugo(monkeypatch, rc=0, writes=["index.html"])

    # act
    rc = site_task.build()

    # assert
    out = capsys.readouterr()
    assert rc == 0
    assert "build/website" in out.out
    assert out.err == ""


# --- the outcome object, so a caller can tell the two no-site cases apart --------------------------------


def test_a_missing_tool_is_neither_ok_nor_failed(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path)
    _tools(monkeypatch)
    _stub_hugo(monkeypatch)

    # act
    built = site_task.build_site(site_task.declared({"site": dict(_SITE)}), tmp_path)

    # assert: nothing was built, but nothing was broken either
    assert (built.ok, built.failed, built.missing) == (False, False, "hugo")


def test_a_present_hugo_that_produced_nothing_is_failed(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path)
    _tools(monkeypatch, "hugo", "go")
    _stub_hugo(monkeypatch, rc=0)

    # act
    built = site_task.build_site(site_task.declared({"site": dict(_SITE)}), tmp_path)

    # assert
    assert (built.ok, built.failed, built.missing) == (False, True, None)
