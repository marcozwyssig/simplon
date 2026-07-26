"""Unit tests for delivery.labhost - the dev-lab Colima VM substrate (netctl#731 Strand 3, extracted from
netctl's orchestrator.hostsetup + orchestrator.lab). Covers the PURE VM sizing (#425), the amd64 binfmt
watchdog (#583), the ensure-colima install-callback seam, and the host install dispatch. No real
subprocess / VM: run/_have/IS_DARWIN are stubbed. AAA throughout."""
import pytest

from delivery import labhost
from delivery.run import Result


# --- #425 VM sizing (pure) --------------------------------------------------------------------------

def test_vm_sizing_leaves_headroom_on_a_typical_host():
    # arrange: 16 GB / 10 cores  act
    mem, cpu = labhost.vm_sizing(16, 10)
    # assert: mem = 16-4, cpu = 10-2
    assert mem == 12
    assert cpu == 8


def test_vm_sizing_clamps_memory_floor_to_six():
    # arrange: an 8 GB host -> 8-4=4, clamped up to the 6 GB floor
    mem, _ = labhost.vm_sizing(8, 8)
    assert mem == 6


def test_vm_sizing_clamps_memory_ceiling_to_thirtytwo():
    # arrange: a 128 GB host -> 124, clamped down to 32
    mem, _ = labhost.vm_sizing(128, 32)
    assert mem == 32


def test_vm_sizing_cpu_floor_is_two():
    # arrange: a 3-core host -> 3-2=1, clamped up to the 2-CPU floor
    _, cpu = labhost.vm_sizing(16, 3)
    assert cpu == 2


@pytest.mark.parametrize("mem_gb,cores,exp_mem,exp_cpu", [
    (8, 4, 6, 2), (16, 8, 12, 6), (32, 14, 28, 12), (64, 24, 32, 22),
])
def test_vm_sizing_matrix(mem_gb, cores, exp_mem, exp_cpu):
    assert labhost.vm_sizing(mem_gb, cores) == (exp_mem, exp_cpu)


def test_colima_start_argv_pins_virtiofs_disk_and_vz_backend():
    # arrange: a non-Rosetta host, VM sized 14 CPU / 32 GB  act
    argv = labhost.colima_start_argv(14, 32, rosetta=False)
    # assert: explicit resources + the fast virtiofs mount are pinned so a build cannot starve the mesh
    assert argv[:2] == ["colima", "start"]
    assert "--mount-type" in argv and argv[argv.index("--mount-type") + 1] == "virtiofs"
    assert argv[argv.index("--disk") + 1] == str(labhost.VM_DISK_GB)
    assert argv[argv.index("--cpu") + 1] == "14" and argv[argv.index("--memory") + 1] == "32"
    assert argv[argv.index("--vm-type") + 1] == "vz"
    assert "--vz-rosetta" not in argv  # only on Apple Silicon


def test_colima_start_argv_appends_rosetta_on_apple_silicon():
    # arrange / act: an arm64 host needs Rosetta for the x86 kinds
    argv = labhost.colima_start_argv(14, 32, rosetta=True)
    assert argv[-1] == "--vz-rosetta"


def test_parse_colima_resources_reads_cpu_mem_disk_from_jsonl():
    # arrange: a captured `colima list --json` line; memory + disk are in BYTES
    payload = ('{"name":"default","status":"Running","arch":"aarch64","cpus":14,'
               '"memory":34359738368,"disk":64424509440,"runtime":"docker"}')
    # act
    got = labhost.parse_colima_resources(payload)
    # assert: bytes -> GB (32 GB RAM, 60 GB disk)
    assert got == (14, 32, 60)


def test_parse_colima_resources_returns_none_on_empty_or_garbage():
    # negative: no VM / unparsable payload must not raise, just yield None
    assert labhost.parse_colima_resources("") is None
    assert labhost.parse_colima_resources("not json\n{oops") is None


def test_vm_underprovisioned_flags_every_short_dimension():
    # arrange: a 2 CPU / 2 GB / 10 GB VM against a 14 / 32 / 60 floor
    short = labhost.vm_underprovisioned(2, 2, 10, 14, 32, 60)
    # assert: all three dimensions are reported short, in a stable order
    assert short == ("cpu", "memory", "disk")


def test_vm_underprovisioned_reports_only_the_short_dimension():
    # arrange / act: enough CPU + disk but half the RAM
    short = labhost.vm_underprovisioned(14, 16, 60, 14, 32, 60)
    assert short == ("memory",)


def test_vm_underprovisioned_is_empty_when_adequately_resourced():
    # a VM at the floor is NOT under-provisioned
    assert labhost.vm_underprovisioned(14, 32, 60, 14, 32, 60) == ()


def _fake_run_factory(list_json: str, host_mem_bytes: int, host_cores: int):
    """A run() double that answers the three calls warn_if_vm_underprovisioned makes."""
    def fake_run(argv, **kwargs):
        if argv[:3] == ["colima", "list", "--json"]:
            return Result(rc=0, out=list_json, err="")
        if argv == ["sysctl", "-n", "hw.memsize"]:
            return Result(rc=0, out=str(host_mem_bytes), err="")
        if argv == ["sysctl", "-n", "hw.logicalcpu"]:
            return Result(rc=0, out=str(host_cores), err="")
        return Result(rc=0, out="", err="")
    return fake_run


def test_under_resourced_vm_is_detected_and_warns(monkeypatch):
    # arrange: a 16-core / 36 GB host (warrants 14 CPU / 32 GB) but an existing 2 CPU / 2 GB VM
    monkeypatch.setattr(labhost, "IS_DARWIN", True)
    payload = '{"cpus":2,"memory":2147483648,"disk":64424509440}'
    monkeypatch.setattr(labhost, "run", _fake_run_factory(payload, 36 * 1024 ** 3, 16))
    warnings: list[str] = []
    monkeypatch.setattr(labhost.log, "warn", lambda m: warnings.append(m))
    # act
    short = labhost.warn_if_vm_underprovisioned()
    # assert: cpu + memory reported short and a warning was emitted naming the resize path
    assert short == ("cpu", "memory")
    assert len(warnings) == 1
    assert "under-resourced" in warnings[0] and "colima stop" in warnings[0]


def test_adequately_resourced_vm_does_not_warn(monkeypatch):
    # arrange: the same host, but the VM already matches the sizing (14 CPU / 32 GB / 60 GB)
    monkeypatch.setattr(labhost, "IS_DARWIN", True)
    payload = '{"cpus":14,"memory":34359738368,"disk":64424509440}'
    monkeypatch.setattr(labhost, "run", _fake_run_factory(payload, 36 * 1024 ** 3, 16))
    warnings: list[str] = []
    monkeypatch.setattr(labhost.log, "warn", lambda m: warnings.append(m))
    # act
    short = labhost.warn_if_vm_underprovisioned()
    assert short == ()
    assert warnings == []


def test_warn_if_vm_underprovisioned_is_a_noop_off_macos(monkeypatch):
    # arrange: a Linux host has no Colima VM to size, so the check must not touch subprocesses
    monkeypatch.setattr(labhost, "IS_DARWIN", False)

    def boom(argv, **kwargs):
        raise AssertionError(f"run() must not be called off macOS, got {argv}")

    monkeypatch.setattr(labhost, "run", boom)
    assert labhost.warn_if_vm_underprovisioned() == ()


# --- ensure_colima_vm - the injected install-callback seam ------------------------------------------

def test_ensure_colima_vm_is_a_noop_off_macos(monkeypatch):
    # arrange: Linux has no Colima VM; the install callback must never fire
    monkeypatch.setattr(labhost, "IS_DARWIN", False)
    calls: list[str] = []
    # act
    labhost.ensure_colima_vm(install=lambda: calls.append("install"))
    # assert: no install on Linux
    assert calls == []


def test_ensure_colima_vm_runs_the_injected_install_when_no_vm(monkeypatch):
    # arrange: macOS, colima on PATH but no lima instance dir -> a never-created VM -> product install
    monkeypatch.setattr(labhost, "IS_DARWIN", True)
    monkeypatch.setattr(labhost, "_have", lambda tool: True)
    monkeypatch.setattr(labhost.os.path, "isdir", lambda p: False)  # VM dir absent
    calls: list[str] = []
    # act
    labhost.ensure_colima_vm(install=lambda: calls.append("install"))
    # assert: the substrate delegated to the product's install callback, named nothing itself
    assert calls == ["install"]


def test_ensure_colima_vm_starts_a_stopped_vm_without_installing(monkeypatch):
    # arrange: macOS, colima present, VM dir present, but `colima status` reports stopped
    monkeypatch.setattr(labhost, "IS_DARWIN", True)
    monkeypatch.setattr(labhost, "_have", lambda tool: True)
    monkeypatch.setattr(labhost.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(labhost, "warn_if_vm_underprovisioned", lambda: ())
    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        # status non-zero (stopped), start ok
        return Result(rc=1 if argv == ["colima", "status"] else 0, out="", err="")

    monkeypatch.setattr(labhost, "run", fake_run)
    installed: list[str] = []
    # act
    labhost.ensure_colima_vm(install=lambda: installed.append("install"))
    # assert: it started the VM and did NOT run the install fallback
    assert ["colima", "start"] in seen
    assert installed == []


# --- disk-guard toggle ------------------------------------------------------------------------------

def test_disk_guard_short_circuits_when_disabled(monkeypatch):
    # arrange (negative): a disabled toggle must not touch the diskguard mechanism at all
    def boom(*a, **k):
        raise AssertionError("diskguard must not run when the toggle is disabled")

    monkeypatch.setattr(labhost.diskguard, "disk_guard", boom)
    # act / assert
    assert labhost.disk_guard(enabled=False) == 0


def test_disk_guard_delegates_to_diskguard_with_the_threshold(monkeypatch):
    # arrange: an enabled toggle delegates to the shared mechanism with the product's threshold
    seen = {}

    def fake_dg(host, *, min_free_pct):
        seen["min_free_pct"] = min_free_pct
        return 0

    monkeypatch.setattr(labhost.diskguard, "disk_guard", fake_dg)
    # act
    rc = labhost.disk_guard(enabled=True, min_free_pct=20)
    # assert
    assert rc == 0
    assert seen["min_free_pct"] == 20


# --- amd64 binfmt watchdog (#583) -------------------------------------------------------------------

# A real /proc/sys/fs/binfmt_misc/qemu-x86_64 entry as tonistiigi/binfmt registers it.
QEMU_PROC_ENTRY = """enabled
interpreter /usr/bin/qemu-x86_64
flags: POCF
offset 0
magic 7f454c4602010100000000000000000002003e00
mask fffffffffffefe00fffffffffffffffffeffffff
"""

EXPECTED_REGISTER_LINE = (
    ":qemu-x86_64:M:0:"
    "\\x7f\\x45\\x4c\\x46\\x02\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00"
    "\\x02\\x00\\x3e\\x00:"
    "\\xff\\xff\\xff\\xff\\xff\\xfe\\xfe\\x00\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xff"
    "\\xfe\\xff\\xff\\xff:"
    "/usr/bin/qemu-x86_64:POCF"
)


class _Res:
    def __init__(self, ok, out=""):
        self.ok = ok
        self.out = out
        self.rc = 0 if ok else 1


def test_qemu_register_line_is_rebuilt_verbatim_from_the_proc_entry():
    # arrange: the live /proc entry of an F-flagged qemu handler  act
    line = labhost.qemu_binfmt_register_line(QEMU_PROC_ENTRY)
    # assert: byte-for-byte the line binfmt_misc accepts on its register file
    assert line == EXPECTED_REGISTER_LINE


def test_qemu_register_line_refuses_a_disabled_or_garbled_entry():
    # negative: no usable handler must yield None, never a broken line
    assert labhost.qemu_binfmt_register_line("") is None
    assert labhost.qemu_binfmt_register_line("disabled\n") is None
    assert labhost.qemu_binfmt_register_line("enabled\ninterpreter /usr/bin/qemu-x86_64\n") is None


def test_watchdog_guards_the_qemu_handler_when_rosetta_is_absent(monkeypatch):
    # arrange: no rosetta.conf in the VM, but a live qemu-x86_64 /proc entry; record every VM call
    calls = []

    def fake_run(argv, input_text=None, **kwargs):
        joined = " ".join(argv)
        calls.append((joined, input_text))
        if "test -e /usr/lib/binfmt.d/rosetta.conf" in joined or "rosetta.conf" in joined and "test" in joined:
            return _Res(False)
        if "binfmt_misc/qemu-x86_64" in joined and "cat" in joined:
            return _Res(True, QEMU_PROC_ENTRY)
        return _Res(True)

    monkeypatch.setattr(labhost, "run", fake_run)
    monkeypatch.setattr(labhost, "_have", lambda tool: True)
    monkeypatch.setattr(labhost, "IS_DARWIN", True)
    # act
    labhost.binfmt_watchdog_start(object())
    # assert: the reconstructed register line is persisted into the VM ...
    teed = [(c, t) for c, t in calls if "tee" in c and t]
    assert any(EXPECTED_REGISTER_LINE in (t or "") for _, t in teed), \
        "the qemu register line must be written into the VM for the spin loop"
    # ... and the spin script guards the QEMU handler, not rosetta
    scripts = [t for c, t in teed if t and "while true" in t]
    assert scripts, "the watchdog spin script must be installed"
    assert "binfmt_misc/qemu-x86_64" in scripts[0], "the spin must watch the qemu handler"
    assert "rosetta" not in scripts[0], "without rosetta.conf the spin must not reference rosetta"


def test_watchdog_still_guards_rosetta_when_its_config_exists(monkeypatch):
    # arrange: rosetta.conf present - the pre-#583 behaviour must be preserved
    calls = []

    def fake_run(argv, input_text=None, **kwargs):
        joined = " ".join(argv)
        calls.append((joined, input_text))
        return _Res(True)

    monkeypatch.setattr(labhost, "run", fake_run)
    monkeypatch.setattr(labhost, "_have", lambda tool: True)
    monkeypatch.setattr(labhost, "IS_DARWIN", True)
    # act
    labhost.binfmt_watchdog_start(object())
    # assert
    scripts = [t for c, t in calls if "tee" in c and t and "while true" in t]
    assert scripts, "the watchdog spin script must be installed"
    assert "binfmt_misc/rosetta" in scripts[0], "with rosetta.conf the spin must guard rosetta"


def test_watchdog_warns_and_stays_out_when_no_amd64_handler_is_recoverable(monkeypatch):
    # negative: neither rosetta.conf nor a readable qemu entry - the watchdog must not install a spin
    # loop that would busy-write garbage into binfmt register
    def fake_run(argv, input_text=None, **kwargs):
        joined = " ".join(argv)
        if "rosetta.conf" in joined or "qemu-x86_64" in joined:
            return _Res(False)
        return _Res(True)

    installed = []

    def recording_run(argv, input_text=None, **kwargs):
        if input_text and "while true" in input_text:
            installed.append(input_text)
        return fake_run(argv, input_text=input_text, **kwargs)

    monkeypatch.setattr(labhost, "run", recording_run)
    monkeypatch.setattr(labhost, "_have", lambda tool: True)
    monkeypatch.setattr(labhost, "IS_DARWIN", True)
    # act
    labhost.binfmt_watchdog_start(object())
    # assert
    assert installed == [], "no recoverable handler -> no spin loop"


def test_watchdog_is_a_noop_off_macos(monkeypatch):
    # arrange (negative): on Linux there is no binfmt flush to guard - the watchdog must not touch the VM
    monkeypatch.setattr(labhost, "IS_DARWIN", False)

    def boom(*a, **k):
        raise AssertionError("the watchdog must not run off macOS")

    monkeypatch.setattr(labhost, "run", boom)
    labhost.binfmt_watchdog_start(object())  # no raise == pass


# --- host install dispatch --------------------------------------------------------------------------

def test_install_host_dispatches_linux(monkeypatch):
    # arrange: os_name Linux -> the Linux installer, never the macOS one
    monkeypatch.setattr(labhost, "_install_linux", lambda: 0)

    def boom(**k):
        raise AssertionError("must not run the macOS installer on Linux")

    monkeypatch.setattr(labhost, "_install_macos", boom)
    # act / assert
    assert labhost.install_host(os_name="Linux") == 0


def test_install_host_invokes_injected_macos_tooling_between_colima_and_credstore(monkeypatch):
    # arrange: drive _install_macos with brew + colima present; record the ORDER of the substrate calls and
    # the injected-tooling callback, then die at the <8GB host check so no real colima start runs.
    monkeypatch.setattr(labhost, "_have", lambda tool: tool in ("brew", "colima"))
    order: list[str] = []

    def fake_run(argv, **kwargs):
        if "brew" in argv and "install" in argv and "colima" in argv:
            order.append("colima")
        return Result(rc=0, out="", err="")

    monkeypatch.setattr(labhost, "run", fake_run)
    monkeypatch.setattr(labhost, "_fix_docker_credstore", lambda: order.append("credstore"))
    monkeypatch.setattr(labhost, "_host_capacity", lambda: (4, 4))  # <8 GB -> die after tooling

    def boom(msg):
        raise SystemExit(msg)

    monkeypatch.setattr(labhost.log, "die", boom)
    # act
    with pytest.raises(SystemExit):
        labhost.install_host(os_name="Darwin",
                             extra_macos_tooling=lambda: order.append("tooling"))
    # assert: colima substrate first, THEN the injected product tooling, THEN the credstore fix
    assert order == ["colima", "tooling", "credstore"]


def test_macos_install_aborts_when_colima_missing_after_brew_install(monkeypatch):
    # arrange: brew present, but no colima binary appears after `brew install` (broken/unavailable formula)
    monkeypatch.setattr(labhost, "_have", lambda tool: tool == "brew")
    monkeypatch.setattr(labhost, "run", lambda argv, **kwargs: Result(rc=0, out="", err=""))

    def boom(msg):
        raise SystemExit(msg)

    monkeypatch.setattr(labhost.log, "die", boom)
    # act / assert: install must die at the post-install colima check, before ever reaching colima start
    with pytest.raises(SystemExit):
        labhost._install_macos()


def test_linux_install_pipes_the_installer_into_bash_not_command_substitution(monkeypatch):
    # arrange: docker present, containerlab absent so ONLY the clab install path runs; capture the argv
    monkeypatch.setattr(labhost, "_have", lambda tool: tool == "docker")
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return Result(rc=0, out="", err="")

    monkeypatch.setattr(labhost, "run", fake_run)
    # act
    rc = labhost._install_linux()
    # assert: the installer is PIPED into bash (never $(...), the footgun that broke the Ubuntu install)
    cmd = captured["argv"][-1]
    assert rc == 0
    assert "| sudo -E bash" in cmd
    assert "$(" not in cmd


def test_linux_install_installs_docker_before_containerlab_when_missing(monkeypatch):
    # arrange: neither docker nor containerlab present; docker appears once its installer ran (#468)
    present = {"docker": False}
    calls = []

    def fake_run(argv, **kwargs):
        cmd = argv[-1]
        calls.append(cmd)
        if "get.docker.com" in cmd:
            present["docker"] = True
        return Result(rc=0, out="", err="")

    monkeypatch.setattr(labhost, "_have", lambda tool: present.get(tool, False))
    monkeypatch.setattr(labhost, "run", fake_run)
    # act
    rc = labhost._install_linux()
    # assert: docker installs FIRST (piped into the shell, never $(...)), then containerlab
    assert rc == 0
    docker_cmd = next(c for c in calls if "get.docker.com" in c)
    clab_cmd = next(c for c in calls if "get.containerlab.dev" in c)
    assert "| sudo -E sh" in docker_cmd and "$(" not in docker_cmd
    assert calls.index(docker_cmd) < calls.index(clab_cmd)


def test_remove_colima_deletes_the_vm_uninstalls_the_package_and_wipes_the_lima_host_state(monkeypatch):
    # arrange: capture every run() argv and every rmtree() target; no real subprocess or filesystem touch
    argvs = []
    removed = []
    monkeypatch.setattr(labhost, "run", lambda argv, **kwargs: argvs.append(argv) or Result(0, "", ""))
    monkeypatch.setattr(labhost.shutil, "rmtree", lambda path, **kwargs: removed.append(str(path)))
    # act
    labhost.remove_colima()
    # assert: the full nuke ran - the VM deleted, the brew package uninstalled (autoremoves lima), and
    # BOTH corrupt lima state dirs wiped. A plain `colima delete` alone never cleared the `000` failure.
    assert ["colima", "delete", "--force"] in argvs
    assert ["env", "NONINTERACTIVE=1", "brew", "uninstall", "colima"] in argvs
    assert any(p.endswith("/.colima") for p in removed)
    assert any(p.endswith("/.lima") for p in removed)
