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
import http.server
import threading

import pytest

from simplon.manifest import context
from simplon.manifest.context import ProductContext
from simplon.tasks import maven

from conftest import lifecycle_name


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


# --- si#337: the gradle task is the coordinate's, and `task:` is withdrawn ---------------------------------


def test_a_declared_task_is_refused_rather_than_ignored():
    # arrange: si#334's case - a task that never reaches the registry. Ignoring the key would run the
    # root `publish` instead of what the product named, a different publication with no word said.
    for declared in ["publishToMavenLocal", ":core:publish", ""]:
        # act
        with pytest.raises(ValueError) as caught:
            maven.refuse_withdrawn({"task": declared}, "firn")

        # assert: it names the key, the ticket, and the route that replaces it
        said = str(caught.value)
        assert "`task:` was withdrawn" in said and "si#337" in said
        assert "toolchain:run" in said


def test_an_entry_without_the_withdrawn_key_passes():
    # arrange / act / assert
    maven.refuse_withdrawn({"registry": "maven.pkg.github.com/o/r", "group": "g"}, "firn")




def test_pack_refuses_a_declared_task_before_docker_is_touched(monkeypatch, tmp_path):
    # arrange: a complete entry that still carries the 0.24.0 key, read the way `pack` reads it. The
    # refusal has to come before a container could start - a helper nobody calls refuses nothing.
    path = tmp_path / "firn.yaml"
    path.write_text("artifacts:\n  firn:\n    kind: maven\n    registry: maven.pkg.github.com/o/r\n"
                    "    image: gradle:9.7.1-jdk21\n    group: g.h\n    modules: [core]\n    tag: '1.0'\n"
                    "    task: publishToMavenLocal\n", encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("firn", tmp_path, path))

    def no_docker():
        raise AssertionError("docker was reached before the withdrawn key was refused")
    monkeypatch.setattr(maven.docker, "ensure_docker", no_docker)

    # act / assert: 0.25.0's sentence, not the schema's generic "not a key" - the reader asks first
    with pytest.raises(ValueError, match="`task:` was withdrawn"):
        maven.pack("firn")


def test_verify_refuses_to_report_on_nothing(monkeypatch):
    # arrange: si#341's measurement - a registry that holds nothing, and no modules to ask about. The loop
    # would find nothing to disagree with and say PRESENT: a read-back that checked nothing, reported green.
    monkeypatch.setattr(maven, "_status", lambda url, token: 404)

    # act / assert: the function that makes the claim refuses, rather than relying on `_modules` upstream
    with pytest.raises(ValueError, match="checked nothing"):
        maven.verify("maven.pkg.github.com/o/r", "g.h", [], "1.0", "t")


def test_may_publish_inherits_the_refusal_rather_than_calling_nothing_published(monkeypatch):
    # arrange: the second caller, where the vacuous PRESENT would have read as "already in the registry"
    monkeypatch.setattr(maven, "_status", lambda url, token: 404)

    # act / assert
    with pytest.raises(ValueError, match="checked nothing"):
        maven.may_publish("maven.pkg.github.com/o/r", "g.h", [], "1.0", "t")


# --- si#412: the pack container is named, labelled, and removed on interrupt -------------------------

@pytest.fixture
def _publishable(monkeypatch, tmp_path):
    """A complete jar entry and every outside call `pack` and `push` make, answered - so only the line is left."""
    path = tmp_path / "firn.yaml"
    path.write_text("artifacts:\n  firn:\n    kind: maven\n    registry: maven.pkg.github.com/o/r\n"
                    "    image: gradle:9.7.1-jdk21\n    group: g.h\n    modules: [core]\n    tag: '1.0'\n    path: build/maven\n",
                    encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("firn", tmp_path, path))
    monkeypatch.setattr(maven.docker, "ensure_docker", lambda: None)
    monkeypatch.setattr(maven.docker, "ownership_fault", lambda tops, root: "")
    monkeypatch.setattr(maven.githubpackages, "token", lambda: "t")
    monkeypatch.setattr(maven, "may_publish", lambda *a: (True, ""))
    monkeypatch.setattr(maven, "verify", lambda *a: (maven.PRESENT, []))

    def _stream(argv, cwd=None):  # the layout a real `gradle publish` leaves
        _stage(tmp_path / "build" / "maven")
        return 0
    monkeypatch.setattr(maven, "stream", _stream)


def test_the_pack_names_and_labels_its_container(_publishable, monkeypatch):
    # arrange
    seen: list = []
    monkeypatch.setattr(maven, "stream", lambda argv, cwd=None: (seen.append(list(argv)), 0)[1])

    # act
    maven.pack("firn")

    # assert
    lifecycle_name(seen[0], "firn")


def test_an_interrupted_pack_removes_the_container_it_named(_publishable, monkeypatch, removals):
    # arrange
    seen: list = []

    def _stream(argv, cwd=None):
        seen.append(list(argv))
        raise KeyboardInterrupt
    monkeypatch.setattr(maven, "stream", _stream)

    # act
    with pytest.raises(KeyboardInterrupt):
        maven.pack("firn")

    # assert
    assert removals == [lifecycle_name(seen[0], "firn")]


# --- si#344 C.3: pack stages, push uploads what was staged -----------------------------------------------

def _stage(staging, group="g.h", module="core", version="1.0"):
    """The layout `gradle publish` writes into a file repository: artefacts and checksums per version,
    maven-metadata.xml per module."""
    base = staging.joinpath(*group.split("."), module)
    (base / version).mkdir(parents=True, exist_ok=True)
    for suffix in (".jar", ".jar.sha1", ".pom", ".pom.sha1", ".module"):
        (base / version / f"{module}-{version}{suffix}").write_text("x", encoding="utf-8")
    (base / "maven-metadata.xml").write_text("<metadata/>", encoding="utf-8")
    (base / "maven-metadata.xml.sha1").write_text("x", encoding="utf-8")


def test_pack_argv_runs_the_staging_task_with_the_kernels_init_script():
    # act
    argv = maven.pack_argv("1.4.0")

    # assert
    assert argv == ["gradle", "publishAllPublicationsToSimplonStagingRepository", "-Pversion=1.4.0",
                    "--init-script", "/work/build/gradle-home/simplon-staging.gradle", "--no-daemon"]


def test_the_init_script_adds_one_file_repository_and_nothing_else():
    # act
    text = maven.init_script_text("/work/build/maven")

    # assert
    assert 'name = "simplonStaging"' in text
    assert 'url = uri("/work/build/maven")' in text
    assert 'plugins.withId("maven-publish")' in text


def test_staged_lists_artefacts_before_each_modules_metadata(tmp_path):
    # arrange
    _stage(tmp_path)

    # act
    files, missing = maven.staged(tmp_path, "g.h", ["core"], "1.0")

    # assert
    names = [f.name for f in files]
    assert missing == []
    assert names.index("core-1.0.pom") < names.index("maven-metadata.xml")
    assert names[-2:] == ["maven-metadata.xml", "maven-metadata.xml.sha1"]


def test_staged_names_a_module_the_pack_did_not_stage(tmp_path):
    # arrange
    _stage(tmp_path, module="core")

    # act
    _, missing = maven.staged(tmp_path, "g.h", ["core", "api"], "1.0")

    # assert
    assert missing == ["api"]


class _Recorder(http.server.BaseHTTPRequestHandler):
    puts: list = []
    status = 201

    def do_PUT(self):  # noqa: N802 - the stdlib's spelling
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        type(self).puts.append((self.path, self.headers.get("Authorization")))
        self.send_response(type(self).status)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def _registry(monkeypatch):
    """A local HTTP server standing in for the registry; `repository_url` is pointed at it."""
    _Recorder.puts, _Recorder.status = [], 201
    server = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(maven, "repository_url",
                        lambda registry, checked=False: f"http://127.0.0.1:{server.server_port}/o/r")
    yield _Recorder
    server.shutdown()


def test_upload_puts_every_staged_file_at_its_relative_path_with_the_token(tmp_path, _registry):
    # arrange
    _stage(tmp_path)
    files, _ = maven.staged(tmp_path, "g.h", ["core"], "1.0")

    # act
    status, refused = maven.upload("maven.pkg.github.com/o/r", tmp_path, files, "t")

    # assert
    assert (status, refused) == (0, "")
    paths = [p for p, _ in _registry.puts]
    assert paths[0] == "/o/r/g/h/core/1.0/core-1.0.jar"
    assert paths[-1] == "/o/r/g/h/core/maven-metadata.xml.sha1"
    assert {auth for _, auth in _registry.puts} == {"Bearer t"}


def test_upload_stops_at_the_first_refused_file_and_names_it(tmp_path, _registry):
    # arrange
    _stage(tmp_path)
    files, _ = maven.staged(tmp_path, "g.h", ["core"], "1.0")
    _registry.status = 403

    # act
    status, refused = maven.upload("maven.pkg.github.com/o/r", tmp_path, files, "t")

    # assert
    assert status == 403
    assert refused == "g/h/core/1.0/core-1.0.jar"
    assert len(_registry.puts) == 1


def test_a_push_with_nothing_staged_for_its_version_names_the_pack_command(_publishable, monkeypatch):
    # act / assert
    with pytest.raises(ValueError, match="nothing staged for 1.0 under build/maven: run `build:maven-pack` first"):
        maven.push("firn")


def test_the_push_uploads_and_then_reads_back(_publishable, monkeypatch, tmp_path):
    # arrange
    _stage(tmp_path / "build" / "maven")
    calls: list = []
    monkeypatch.setattr(maven, "upload", lambda *a: calls.append("upload") or (0, ""))
    monkeypatch.setattr(maven, "verify", lambda *a: calls.append("verify") or (maven.PRESENT, []))

    # act
    rc = maven.push("firn")

    # assert
    assert rc == 0
    assert calls == ["upload", "verify"]


def test_a_release_version_already_published_is_refused_before_anything_is_uploaded(_publishable, monkeypatch,
                                                                                   tmp_path):
    # arrange
    _stage(tmp_path / "build" / "maven")
    monkeypatch.setattr(maven, "may_publish", lambda *a: (False, "already in the registry"))
    monkeypatch.setattr(maven, "upload", lambda *a: pytest.fail("uploaded although refused"))

    # act
    rc = maven.push("firn")

    # assert
    assert rc == 1


def test_a_staging_path_outside_the_output_root_is_refused_before_anything_is_deleted(_publishable, tmp_path):
    # arrange
    path = tmp_path / "firn.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("path: build/maven", "path: ."), encoding="utf-8")
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")

    # act / assert
    with pytest.raises(ValueError, match="is not inside the output root"):
        maven.pack("firn")
    assert (tmp_path / "keep.txt").exists()


def test_a_pack_that_exits_0_and_staged_nothing_is_a_failed_step(_publishable, monkeypatch, capsys):
    # arrange: gradle answers 0 and writes nothing
    monkeypatch.setattr(maven, "stream", lambda argv: 0)

    # act
    rc = maven.pack("firn")

    # assert
    assert rc == 1
    assert "staged nothing for core" in capsys.readouterr().err
