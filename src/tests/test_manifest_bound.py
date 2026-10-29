"""The names bound to an unparametrised input port reach the body (si#553).

A port with a `param` hands its one artifact name to that body parameter. A LIST port has none, so the
body had no way to learn what was bound to it. `bound.names` is that way, and it answers with two values for
two answers: None outside a command, `()` for a port the command binds to nothing.
"""
from types import SimpleNamespace

from simplon.manifest import bound
from simplon.model.artifactschema import Port


def test_names_is_none_outside_a_command():
    assert bound.names("files") is None


def test_within_hands_the_bound_names_and_resets():
    seen = []

    def body() -> int:
        seen.append((bound.names("files"), bound.names("other")))
        return 7

    assert bound.within({"files": ("a", "b")}, body) == 7
    assert seen == [(("a", "b"), ())]
    assert bound.names("files") is None


def test_within_resets_when_the_body_raises():
    def body() -> int:
        raise RuntimeError("x")

    try:
        bound.within({"files": ("a",)}, body)
    except RuntimeError:
        pass
    assert bound.names("files") is None


def test_of_reads_only_unparametrised_input_ports_that_take_no_test_result():
    spec = SimpleNamespace(
        ports=(Port("files", "input", "file", "", ("path",)),
               Port("image", "input", "image", "name", ()),
               Port("evidence", "input", "test-result", "", ()),
               Port("out", "output", "release_assets", "", ())),
        consumes={"files": ["a", "b"], "image": ["x"], "evidence": ["r"], "out": ["o"]})
    assert bound.of(spec) == {"files": ("a", "b")}


def test_of_leaves_out_a_port_the_command_binds_to_nothing():
    spec = SimpleNamespace(ports=(Port("files", "input", "file", "", ()),), consumes={})
    assert bound.of(spec) == {}
