"""si#329: publishing a jar, the third publish coordinate beside `release:nuget` and `release:conan`.

WHY IT IS A COORDINATE AT ALL. The kernel BUILDS four languages (`tasks/profiles.py`: cpp, java, dotnet,
python) and, before this, published two. It has pinned a Gradle image since si#316 and could not hand the
result to anybody. GitHub Packages serves this kind - `release:conan`'s own comment lists Maven and Gradle
among them, which is also why conan took the other shape: for Conan there was no registry to publish TO.

WHY IT READS BACK. `release:nuget` trusts `dotnet nuget push`'s rc; `release:image` asks the registry
whether the tag arrived, because "a push nobody verifies is the same defect as a report nobody reads". This
takes the stronger shape, and the verification distinguishes THREE outcomes rather than two - present,
absent, and could-not-ask - for the reason si#327 paid for three days earlier.

AAA; the name states the behaviour under test.
"""
import pytest

from simplon.tasks import maven


# --- the pure layer ------------------------------------------------------------------------------------


def test_repository_url_is_built_from_the_declared_registry():
    # arrange / act / assert: one scheme, added here, so a manifest never carries one
    assert maven.repository_url("maven.pkg.github.com/marcozwyssig/firn") == \
        "https://maven.pkg.github.com/marcozwyssig/firn"


def test_repository_url_tolerates_a_trailing_slash():
    # arrange / act / assert: a doubled slash in a URL is a 404 that reads like a missing package
    assert maven.repository_url("maven.pkg.github.com/marcozwyssig/firn/") == \
        "https://maven.pkg.github.com/marcozwyssig/firn"


def test_pom_url_turns_the_group_into_path_segments():
    # arrange: Maven's layout is the group with every dot a directory
    # act
    url = maven.pom_url("maven.pkg.github.com/marcozwyssig/firn", "info.zwyssig.firn", "core", "0.2.0")

    # assert
    assert url == ("https://maven.pkg.github.com/marcozwyssig/firn/"
                   "info/zwyssig/firn/core/0.2.0/core-0.2.0.pom")


def test_publish_argv_pins_the_version_and_takes_no_daemon():
    # arrange / act
    argv = maven.publish_argv("0.2.0")

    # assert: `-Pversion=` rather than an edit to build.gradle - the version is a property of the RELEASE,
    # and a number checked into a build file is a number two people can pick at once. `--no-daemon`
    # because a daemon in a `--rm` container is a process nobody reaps.
    assert argv == ["gradle", "publish", "-Pversion=0.2.0", "--no-daemon"]


# --- the container line --------------------------------------------------------------------------------


def test_docker_argv_keeps_the_token_out_of_argv(tmp_path):
    # arrange: the property that matters more than any other here. `docker run -e TOKEN=...` puts the
    # credential in the docker CLI's own argv, which `ps` shows to every user and `docker inspect` keeps.
    env_file = tmp_path / "env"
    env_file.write_text("GITHUB_TOKEN=ghp_secret\n")

    # act
    argv = maven.docker_argv("gradle:9.7.1-jdk25", tmp_path, env_file, ["gradle", "publish"])

    # assert
    assert "--env-file" in argv
    assert not any("ghp_secret" in part for part in argv)


def test_docker_argv_points_gradle_at_a_home_inside_the_mounted_tree(tmp_path):
    # arrange: si#325, measured by a consumer and paid for once already. The JVM reads `user.home` from
    # the passwd entry and IGNORES `$HOME`, so setting HOME does NOT move a gradle run - for root it is a
    # no-op. `GRADLE_USER_HOME` is therefore the only thing that works, not merely the tidier option.
    env_file = tmp_path / "env"
    env_file.write_text("")

    # act
    argv = maven.docker_argv("gradle:9.7.1-jdk25", tmp_path, env_file, ["gradle", "publish"])
    joined = " ".join(argv)

    # assert
    assert f"GRADLE_USER_HOME={maven.WORKDIR}/{maven.GRADLE_HOME}" in joined
    assert f"{maven.WORKDIR}" in joined


# --- the read-back, with three outcomes ----------------------------------------------------------------


def test_verify_reports_every_module_it_found(monkeypatch):
    # arrange: both POMs answer 200
    monkeypatch.setattr(maven, "_status", lambda url, token: 200)

    # act
    state, missing = maven.verify("maven.pkg.github.com/o/r", "g.h", ["core", "model"], "1.0", "t")

    # assert
    assert (state, missing) == (maven.PRESENT, [])


def test_verify_names_the_modules_that_are_not_there(monkeypatch):
    # arrange: one 200, one 404
    monkeypatch.setattr(maven, "_status", lambda url, token: 404 if "model" in url else 200)

    # act
    state, missing = maven.verify("maven.pkg.github.com/o/r", "g.h", ["core", "model"], "1.0", "t")

    # assert: the NAME, not a count - a reader has to know which one to look for
    assert state == maven.ABSENT
    assert missing == ["model"]


def test_verify_says_it_could_not_ask_rather_than_reporting_absence(monkeypatch):
    # arrange: the registry answered 401 - which is not "the jar is missing", it is "we were not allowed
    # to look". si#327's lesson: an outcome that cannot tell "nothing to do" from "failed" is a bug, and
    # here the third value is what keeps a scope problem from being reported as a failed publish.
    monkeypatch.setattr(maven, "_status", lambda url, token: 401)

    # act
    state, missing = maven.verify("maven.pkg.github.com/o/r", "g.h", ["core"], "1.0", "t")

    # assert
    assert state == maven.UNKNOWN
    assert missing == []


def test_the_three_verification_states_are_distinct():
    # arrange / act / assert
    assert len({maven.PRESENT, maven.ABSENT, maven.UNKNOWN}) == 3


# --- the refusals a product hits first ------------------------------------------------------------------


def test_a_registry_that_is_not_githubs_is_refused_by_name():
    # arrange: `registry:` is a MANIFEST KEY, and this module mints a GitHub token. A product writing
    # `registry: maven.example.com/team` would have that token posted to a third party.
    # act / assert
    with pytest.raises(ValueError) as caught:
        maven.repository_url("maven.example.com/team", checked=True)
    assert "maven.example.com" in str(caught.value)


def test_a_registry_carrying_a_scheme_is_refused_rather_than_silently_doubled():
    # arrange / act / assert: `https://https://...` is a URL error reported as a missing package
    with pytest.raises(ValueError):
        maven.repository_url("https://maven.pkg.github.com/o/r", checked=True)
