"""Unit tests for the process-global degraded-condition collector (platformcore.degraded): the in-memory
accumulation and the cross-process file-union channel used when a bring-up runs its phases as separate
processes. Moved here from netctl - the collector is platform's now."""
import os

from platformcore import degraded


def test_items_unions_the_shared_file_so_separate_phases_surface_to_the_verdict(tmp_path):
    # arrange: a phase (a separate process) recorded a degraded condition into the shared file
    degfile = tmp_path / "degraded"
    degfile.write_text("containerlab deploy did not complete cleanly (only 30 container(s) up)\n")
    os.environ[degraded.DEGRADED_FILE_ENV] = str(degfile)
    degraded.reset()
    try:
        # act: this phase adds its own and reads the verdict input
        degraded.add("provisioning incomplete")
        items = degraded.items()

        # assert: BOTH the other phase's file entry and this phase's in-memory entry are present
        assert any("deploy did not complete" in i for i in items)
        assert any("provisioning incomplete" in i for i in items)
    finally:
        os.environ.pop(degraded.DEGRADED_FILE_ENV, None)
        degraded.reset()


def test_items_is_in_memory_only_when_no_shared_file():
    # arrange: no shared file -> single-process semantics
    os.environ.pop(degraded.DEGRADED_FILE_ENV, None)
    degraded.reset()

    # act
    degraded.add("only this one")
    items = degraded.items()

    # assert: exactly the in-memory entry, no file bleed
    assert items == ["only this one"]
    degraded.reset()
