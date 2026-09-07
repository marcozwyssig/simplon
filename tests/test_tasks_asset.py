"""`release:asset` - attaching declared files to a GitHub release.

What is the product's is DATA: which files, which repository, what the release is called. The mechanics -
create the release if nobody made it yet, replace an asset that is already there - are `gh`'s, which is
why they are three argv lists here and not a GitHub client in the kernel's dependencies. AAA throughout;
nothing uploads anything.
"""
import pytest

from simplon import run
from simplon.context import ProductContext
from simplon import context
from simplon.tasks import asset

_MANIFEST = """
product: demo
assets:
  bundle:
    source: "build-out/demo_*.zip"
  site:
    source: "build-out/site.zip"
    repository: owner/other
    tag: latest
groups: {}
env_groups: []
"""


@pytest.fixture(autouse=True)
def _product(tmp_path, monkeypatch):
    (tmp_path / "demo.yaml").write_text(_MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))
    out = tmp_path / "build-out"
    out.mkdir()
    (out / "demo_linux.zip").write_text("z", encoding="utf-8")
    return tmp_path


class _Gh(list):
    """Every `gh` invocation, in order. `replies` scripts what one subcommand returns; anything not
    scripted succeeds, so a test states only the outcome it is about."""

    replies: dict


@pytest.fixture
def gh(monkeypatch):
    calls = _Gh()
    calls.replies = {}

    def _fake(argv, **kw):
        calls.append(list(argv))
        return calls.replies.get(argv[2], run.Result(rc=0, out="", err=""))

    monkeypatch.setattr(run, "run", _fake)
    return calls


def test_a_declared_asset_is_uploaded_to_the_release_for_the_tag_it_was_given(gh, _product):
    rc = asset.publish(name="bundle", tag="0.4.149")

    assert rc == 0
    assert gh[-1] == ["gh", "release", "upload", "0.4.149",
                      str(_product / "build-out" / "demo_linux.zip"), "--clobber"]


def test_the_release_is_created_before_anything_is_attached_to_it(gh):
    """Six matrix cells upload into one release and none of them can assume it is there yet."""
    asset.publish(name="bundle", tag="0.4.149")

    assert gh[0][:4] == ["gh", "release", "create", "0.4.149"]


def test_a_release_another_cell_created_first_is_not_an_error(gh):
    """The create is the claim, and losing that race means someone made the release we wanted. Checking
    first would be the same race with a wider window, so the loss is read rather than prevented."""
    gh.replies["create"] = run.Result(rc=1, out="", err="a release with the tag already exists")

    rc = asset.publish(name="bundle", tag="0.4.149")

    assert rc == 0
    assert gh[-1][:3] == ["gh", "release", "upload"]


def test_a_create_that_failed_for_any_other_reason_attaches_nothing(gh):
    """The defect this repository hunts: a failure that cannot be told from 'it was already there'.
    Read as the race, a missing permission would upload into whatever release the tag names next."""
    gh.replies["create"] = run.Result(rc=1, out="", err="HTTP 403: Resource not accessible")

    with pytest.raises(RuntimeError, match="403"):
        asset.publish(name="bundle", tag="0.4.149")

    assert [c[:3] for c in gh] == [["gh", "release", "create"]]


def test_an_upload_that_failed_is_not_reported_as_a_publication(gh):
    """`gh` returns non-zero on a half-written asset, and a task that only ever returned 0 would turn
    that into a green release with nothing in it."""
    gh.replies["upload"] = run.Result(rc=1, out="", err="HTTP 422: validation failed")

    with pytest.raises(RuntimeError, match="422"):
        asset.publish(name="bundle", tag="0.4.149")


def test_a_source_that_matches_nothing_is_named_before_the_release_is_touched(gh, _product):
    """The files are the product's to build. Creating the release first would leave an empty one behind
    naming a version that was never published."""
    (_product / "build-out" / "demo_linux.zip").unlink()

    with pytest.raises(ValueError, match=r"build-out/demo_\*\.zip"):
        asset.publish(name="bundle", tag="0.4.149")

    assert gh == []


def test_without_a_tag_anywhere_it_says_both_places_one_could_be(gh):
    """Same split as `release:artifact`: a constant tag belongs in the manifest, but cleon's comes out
    of a generated jar after the build and can only arrive as an argument."""
    with pytest.raises(ValueError, match="--tag"):
        asset.publish(name="bundle")


def test_a_tag_declared_in_the_manifest_needs_no_argument(gh, _product):
    (_product / "build-out" / "site.zip").write_text("z", encoding="utf-8")

    asset.publish(name="site")

    assert gh[0][:4] == ["gh", "release", "create", "latest"]


def test_an_undeclared_asset_lists_the_ones_that_are(gh):
    with pytest.raises(ValueError, match="bundle, site"):
        asset.publish(name="nope", tag="1")


def test_a_declared_repository_reaches_every_call(gh, _product):
    """One asset may belong to another repository than the one the build runs in, and a `--repo` that
    reached only half the calls would create the release here and upload it there."""
    (_product / "build-out" / "site.zip").write_text("z", encoding="utf-8")

    asset.publish(name="site")

    assert all(c[-2:] == ["--repo", "owner/other"] for c in gh)


def test_without_a_declared_repository_gh_resolves_it_from_the_remote(gh):
    asset.publish(name="bundle", tag="0.4.149")

    assert not any("--repo" in c for c in gh)


def test_the_create_is_never_interactive(gh):
    """`gh release create` opens an editor for the notes when it has a terminal and refuses without one.
    A CI cell would hang or fail on a flag nobody passed, so the notes are always stated."""
    asset.publish(name="bundle", tag="0.4.149")

    assert "--notes" in gh[0]


def test_a_declared_title_and_notes_reach_the_release(gh, _product):
    (_product / "demo.yaml").write_text(
        _MANIFEST.replace('    source: "build-out/demo_*.zip"',
                          '    source: "build-out/demo_*.zip"\n'
                          '    title: cleon 0.4.149\n'
                          '    notes: pick it up from the update site'), encoding="utf-8")

    asset.publish(name="bundle", tag="0.4.149")

    assert gh[0][gh[0].index("--title") + 1] == "cleon 0.4.149"
    assert gh[0][gh[0].index("--notes") + 1] == "pick it up from the update site"


def test_asking_for_no_asset_at_all_names_where_one_is_pinned(gh):
    with pytest.raises(ValueError, match="with:"):
        asset.publish(tag="0.4.149")


def test_a_missing_gh_is_named_rather_than_raised_from_inside_the_wrapper(gh, monkeypatch):
    """`run()` does not turn a missing binary into a return code - it raises FileNotFoundError out of a
    wrapper the reader never opened. Same gate, and same wording, as `gitops`."""
    monkeypatch.setattr(asset.shutil, "which", lambda tool: None)

    with pytest.raises(SystemExit):
        asset.publish(name="bundle", tag="0.4.149")

    assert gh == []
