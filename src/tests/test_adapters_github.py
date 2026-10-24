"""si#486: `adapters.github` - found, absent or unanswered, over PyGithub, against a local stand-in."""
from __future__ import annotations

import socket

import pytest

import githubstandin
from simplon.adapters import github


@pytest.fixture
def standin(monkeypatch):
    """A running stand-in, with the variables Actions would set pointed at it."""
    shared = githubstandin.state()
    base, stop = githubstandin.serve(shared)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_API_URL", base)
    monkeypatch.setenv("GITHUB_REPOSITORY", githubstandin.REPO)
    try:
        yield shared
    finally:
        stop()


@pytest.mark.parametrize("url, expected", [
    ("https://github.com/o/n.git", ("o/n", "https://api.github.com")),
    ("https://github.com/o/n/", ("o/n", "https://api.github.com")),
    ("https://github.com/o/n", ("o/n", "https://api.github.com")),
    ("git@github.com:o/n.git", ("o/n", "https://api.github.com")),
    ("ssh://git@github.com/o/n.git", ("o/n", "https://api.github.com")),
    ("https://x-access-token:secret@github.com/o/n.git", ("o/n", "https://api.github.com")),
    # an Enterprise host is never read off a remote: the token would go to whatever host the clone names
    ("https://ghe.example/o/n.git", None),
    ("git@ghe.example:o/n.git", None),
    ("https://github.com.evil.example/o/n.git", None),
    ("/srv/git/n.git", None),
    ("", None),
])
def test_locate_reads_repository_and_api_base_from_origin(url, expected):
    assert github.locate(url) == expected


def test_set_variables_win_over_origin(standin):
    # act: origin names another repository on another host
    repo = github.repository("https://ghe.example/x/y.git")

    # assert
    assert repo.full_name == githubstandin.REPO
    assert ("GET", f"/repos/{githubstandin.REPO}", None) in standin["requests"]


def test_origin_supplies_what_the_environment_does_not(monkeypatch):
    # arrange: neither variable set
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_API_URL", raising=False)

    # act: origin on github.com
    where = github.where("git@github.com:o/n.git")

    # assert
    assert where == ("o/n", "https://api.github.com")


def test_a_non_github_origin_with_no_variable_names_both_variables(monkeypatch):
    # arrange
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_API_URL", raising=False)

    # act / assert
    with pytest.raises(github.Unanswered) as refused:
        github.repository("https://user:hunter2@ghe.example/o/n.git")
    assert "GITHUB_REPOSITORY" in str(refused.value) and "GITHUB_API_URL" in str(refused.value)
    assert "hunter2" not in str(refused.value) and "ghe.example" not in str(refused.value)


def test_a_repository_the_token_cannot_see_is_unanswered_not_absent(standin):
    # arrange: GitHub answers 404 for a repository the token cannot see, exactly as for none
    standin["repo"] = None

    # act / assert
    with pytest.raises(github.Unanswered) as refused:
        github.repository()
    assert githubstandin.REPO in str(refused.value)


def test_a_404_on_the_tag_lookup_is_absent(standin):
    # arrange: a draft is invisible to the tag lookup, which answers published releases only
    standin["releases"].append(githubstandin.release(1, "v1.0.0", draft=True))

    # act / assert
    assert github.published(github.repository(), "v1.0.0") is None


def test_a_published_release_is_found_by_its_tag(standin):
    standin["releases"].append(githubstandin.release(1, "v1.0.0", draft=False))
    found = github.published(github.repository(), "v1.0.0")
    assert found is not None and found.id == 1


def test_a_500_on_the_tag_lookup_is_unanswered_and_asked_once(standin):
    # arrange
    standin["fail"][("GET", f"/repos/{githubstandin.REPO}/releases/tags")] = 500
    repo = github.repository()

    # act / assert
    with pytest.raises(github.Unanswered) as refused:
        github.published(repo, "v1.0.0")
    assert "500" in str(refused.value)
    asked = [r for r in standin["requests"] if r[1].startswith(f"/repos/{githubstandin.REPO}/releases/tags")]
    assert len(asked) == 1, f"PyGithub retried a 500 behind our back: {asked}"


def test_a_refused_connection_is_unanswered(monkeypatch):
    # arrange: a port nothing listens on
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", githubstandin.REPO)
    monkeypatch.setenv("GITHUB_API_URL", f"http://127.0.0.1:{port}")

    # act / assert
    with pytest.raises(github.Unanswered) as refused:
        github.repository()
    assert f"127.0.0.1:{port}" in str(refused.value)


def test_releases_for_finds_drafts_and_published_by_tag(standin):
    standin["releases"] += [githubstandin.release(1, "v1.0.0", draft=True),
                            githubstandin.release(2, "v1.0.0", draft=False),
                            githubstandin.release(3, "v0.9.0", draft=False)]
    found = github.releases_for(github.repository(), "v1.0.0")
    assert sorted(r.id for r in found) == [1, 2]


def test_releases_past_the_page_bound_is_unanswered(standin):
    # arrange: a thousand and one releases, none with the tag
    standin["releases"] += [githubstandin.release(i, f"x{i}", draft=False) for i in range(1, 1002)]

    # act / assert
    with pytest.raises(github.Unanswered) as refused:
        github.releases_for(github.repository(), "v1.0.0")
    assert "1000" in str(refused.value)


def test_no_token_and_no_gh_is_unanswered_with_a_message(monkeypatch):
    # arrange: the venv route on a host without `gh` - `run` raises FileNotFoundError for the missing tool
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", githubstandin.REPO)
    monkeypatch.setenv("GITHUB_API_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("PATH", "/nonexistent")

    # act / assert
    with pytest.raises(github.Unanswered) as refused:
        github.repository()
    assert "GITHUB_TOKEN" in str(refused.value)


def test_the_refusal_names_the_launcher_pass_for_the_container_route(monkeypatch):
    # arrange: an Enterprise origin, and the container route forwards neither GITHUB_* variable
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_API_URL", raising=False)

    # act / assert
    with pytest.raises(github.Unanswered) as refused:
        github.where("git@ghe.example:o/n.git")
    assert "launcher: env: pass: [GITHUB_REPOSITORY, GITHUB_API_URL]" in str(refused.value)


def test_other_asks_for_the_named_repository(standin):
    # act: a token of its own, not the environment's
    repo = github.other(githubstandin.REPO, "given-token")

    # assert
    assert repo.full_name == githubstandin.REPO
    assert standin["requests"] == [("GET", f"/repos/{githubstandin.REPO}", None)]
    assert standin["auth"] == ["token given-token"]


def test_other_with_an_empty_token_sends_nothing(standin):
    # act
    with pytest.raises(github.Unanswered) as why:
        github.other(githubstandin.REPO, "")

    # assert
    assert githubstandin.REPO in str(why.value)
    assert "token" in str(why.value)
    assert standin["requests"] == []


def test_other_maps_404_to_unanswered(standin):
    # act: the stand-in knows one repository only
    with pytest.raises(github.Unanswered) as why:
        github.other("o/missing", "t")

    # assert
    assert "404" in str(why.value)
    assert "o/missing" in str(why.value)
