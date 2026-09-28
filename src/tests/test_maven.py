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


# --- si#330: the coordinate answers the snapshot question itself ----------------------------------------
# The original ticket asks for this explicitly - "whether a publish hangs off a tag is a question this
# coordinate should answer EXPLICITLY rather than leave to each manifest". A snapshot republishes under one
# coordinate, which is right while a shape is moving and wrong the moment something builds against it. Both
# consumers that wanted this feature had the question open, so there was no product decision to inherit.


def test_a_snapshot_version_is_recognised_by_mavens_own_rule():
    # arrange / act / assert: Maven's rule is the literal suffix, and it is case-SENSITIVE - `-Snapshot`
    # is an ordinary release version to every tool in that ecosystem, which is a trap worth pinning
    assert maven.is_snapshot("0.1.0-SNAPSHOT") is True
    assert maven.is_snapshot("0.1.0") is False
    assert maven.is_snapshot("0.1.0-Snapshot") is False
    assert maven.is_snapshot("0.1.0-SNAPSHOT-1") is False


def test_a_release_version_already_in_the_registry_is_refused_before_anything_is_published(monkeypatch):
    # arrange: the whole point of checking FIRST. A release coordinate is immutable, so a second publish
    # either fails part-way - leaving some modules uploaded and some not - or silently changes nothing.
    monkeypatch.setattr(maven, "_status", lambda url, token: 200)

    # act
    state, why = maven.may_publish("maven.pkg.github.com/o/r", "g.h", ["core"], "1.0", "t")

    # assert
    assert state is False
    assert "1.0" in why


def test_a_release_version_that_is_not_there_yet_may_be_published(monkeypatch):
    # arrange
    monkeypatch.setattr(maven, "_status", lambda url, token: 404)

    # act / assert
    assert maven.may_publish("maven.pkg.github.com/o/r", "g.h", ["core"], "1.0", "t")[0] is True


def test_a_snapshot_may_always_be_published_and_is_never_probed(monkeypatch):
    # arrange: republishing IS what a snapshot is for, so the existence check would refuse the normal case
    def boom(url, token):
        raise AssertionError("a snapshot must not be probed for existence - republishing is its purpose")
    monkeypatch.setattr(maven, "_status", boom)

    # act / assert
    assert maven.may_publish("maven.pkg.github.com/o/r", "g.h", ["core"], "9.9-SNAPSHOT", "t")[0] is True


def test_an_unaskable_registry_does_not_block_a_release_publish(monkeypatch):
    # arrange: 401 means "we may not look", which is not "the version is free" and not "it is taken"
    # either. Blocking here would make a token scope look like a version collision.
    monkeypatch.setattr(maven, "_status", lambda url, token: 401)

    # act
    state, why = maven.may_publish("maven.pkg.github.com/o/r", "g.h", ["core"], "1.0", "t")

    # assert: it proceeds, and it SAYS it could not check - the half that would otherwise be missing
    assert state is True
    assert why


# --- si#330: the gradle task is the product's to name ---------------------------------------------------


def test_the_gradle_task_defaults_to_publish():
    # arrange / act / assert
    assert maven.publish_argv("1.0") == ["gradle", "publish", "-Pversion=1.0", "--no-daemon"]


def test_a_product_may_name_another_gradle_task():
    # arrange: eleven modules, and a product that publishes some of them names its own task - or reaches
    # one subproject's, which the root `publish` does not do
    # act
    argv = maven.publish_argv("1.0", task=":core:publish")

    # assert
    assert argv == ["gradle", ":core:publish", "-Pversion=1.0", "--no-daemon"]


def test_a_task_name_that_is_not_one_is_refused_by_name():
    # arrange: it goes into argv, so there is no shell to abuse - but a name with a space becomes ONE
    # argument gradle cannot resolve, and a leading dash becomes a flag. Both fail far from the manifest.
    # act / assert
    for wrong in ["publish --info", "-Dfoo=bar", "", "publish;rm -rf /"]:
        with pytest.raises(ValueError):
            maven.gradle_task({"task": wrong}, "firn")


def test_a_declared_but_empty_task_is_told_apart_from_an_absent_one():
    # arrange: both are refused by the pattern anyway, so what this pins is the MESSAGE - and that is the
    # point rather than a detail. Leaving the key out means "the default is fine"; declaring it with nothing
    # means somebody meant to name a task and did not, and those two readers need different sentences.
    # Without the distinction the second one is told their empty string "is not a gradle task name", which
    # is true and useless.
    # act
    with pytest.raises(ValueError) as caught:
        maven.gradle_task({"task": ""}, "firn")

    # assert
    assert "no value" in str(caught.value)
    assert maven.DEFAULT_TASK in str(caught.value), "the message has to name what leaving it out would give"


def test_a_legal_task_name_survives_the_check():
    # arrange / act / assert: the shapes a real build actually uses
    for good in ["publish", ":core:publish", "publishAllPublicationsToGithubRepository",
                 "publishMavenJavaPublicationToMavenRepository"]:
        assert maven.gradle_task({"task": good}, "firn") == good
    assert maven.gradle_task({}, "firn") == maven.DEFAULT_TASK
