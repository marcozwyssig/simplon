"""WHICH VARIABLES CROSS THE CONTAINER BOUNDARY, and why that list needed a test (si#225).

The venv route inherits the caller's whole environment; the container route inherits exactly what
`launch.sh.j2` names and nothing else. That asymmetry is deliberate - forwarding an unbounded environment
is how a secret reaches a place nobody looked - and it means the list is a DECISION, one item at a time,
about what a product can still do once it runs in a container.

Nothing asserted that list before this file. si#206 found out the expensive way: its walk turns a
customer's refusal into a ticket through `gh`, the image carried no `gh`, and a walk on the container
route therefore asked its questions, recorded its refusals and filed none of them. si#225 put `gh` in the
image - and putting it there alone would have moved the failure rather than fixed it, because `GH_TOKEN`
is the variable `gh` reads FIRST and it was not crossing either. A walk would then have found the tool
present, skipped the sentence that says the tool is missing, and died with a 401.

BOTH FILES ARE HELD, and that is the point of reading them twice. `simplon.sh` in this repository is the
kernel's own rendered launcher and `launch.sh.j2` is what every scaffolded product gets. An edit to one
that misses the other gives simplon a capability it does not ship - which is the platform/product seam
this repository refuses everywhere else.
"""
import re

from conftest import ROOT
from simplon.cli import bootstrap
from simplon.manifest import launcherenv

#: The kernel's own launcher, and the template every scaffolded product is rendered from.
LAUNCHER = ROOT / "simplon.sh"
TEMPLATE = ROOT / "src" / "simplon" / "templates" / "launch.sh.j2"

#: A hyphenated product name, so the rendered templates also show the `<PRODUCT>_*` prefix taking `-` as `_`.
SCAFFOLDED = "foo-ctl"


def _rendered(template: str) -> str:
    """A template as `simplon init` renders it for a product: the fixed names are a placeholder in the
    template (si#479), so membership is a question about what a product receives."""
    return bootstrap._render_launcher(SCAFFOLDED, template, "deploy/orchestrator")


def _shell_texts() -> list[tuple[str, str]]:
    return [(LAUNCHER.name, LAUNCHER.read_text(encoding="utf-8")), (TEMPLATE.name, _rendered(TEMPLATE.name))]

#: The `case` arm that decides what is forwarded. Read as a pattern rather than as a literal line so a
#: reordering of the list is not a failure - the question is membership, not spelling.
_ARM = re.compile(r"^\s*(DELIVERY_\*\|[A-Z_|]+)\)\s*DOCKER_RUN\+=\(-e ", re.M)


def _forwarded(text: str) -> set[str]:
    """The names the launcher's own `case` arm forwards, as a set."""
    match = _ARM.search(text)
    assert match, "the launcher no longer has a case arm forwarding named variables"
    return set(match.group(1).split("|"))


def test_gh_token_crosses_because_gh_reads_it_before_github_token():
    """si#225. GITHUB_TOKEN was already on the list and is only `gh`'s FALLBACK; GH_TOKEN is what it reads
    first and what si#206's own broken-tracker proof was driven with."""
    # arrange / act
    forwarded = _forwarded(LAUNCHER.read_text(encoding="utf-8"))

    # assert
    assert "GH_TOKEN" in forwarded, sorted(forwarded)
    assert "GITHUB_TOKEN" in forwarded, sorted(forwarded)


def test_the_template_forwards_exactly_what_the_kernels_own_launcher_does():
    """A capability simplon keeps for itself and does not render into a scaffolded product is the seam
    this repository refuses everywhere else, and an edit to one file is how it would happen."""
    # arrange / act
    mine = _forwarded(LAUNCHER.read_text(encoding="utf-8"))
    scaffolded = _forwarded(_rendered(TEMPLATE.name))

    # assert
    assert mine == scaffolded, f"only in simplon.sh: {sorted(mine - scaffolded)}, " \
                               f"only in the template: {sorted(scaffolded - mine)}"


def test_the_prose_above_the_arm_names_the_same_variables_the_arm_forwards():
    """The comment over that `case` lists the variables in prose, and si#225 found it one name short of
    the code beneath it. A list written twice drifts; this is the cheap half of keeping it honest."""
    for name, text in _shell_texts():
        # act: the prose spells them slash-separated, the arm pipe-separated
        prose = {name for name in re.findall(r"[A-Z][A-Z_]+", text.split("WHICH VARIABLES CROSS")[1]
                                             .split("ENV_PREFIX=")[0])}

        # assert
        for forwarded in _forwarded(text) - {"DELIVERY_*"}:
            assert forwarded in prose, f"{name}: the arm forwards {forwarded} and the prose above does " \
                                       f"not name it"


def test_the_launch_parameters_a_refusal_names_reach_the_kernel_on_both_routes():
    """si#344. The cut's refusal names the migration's two commands, written in terms of where THIS
    checkout keeps its orchestrator and which image it pins; the kernel fills them from `LAUNCH_ORCH_DIR`
    and `LAUNCH_IMAGE_PIN`, so both have to be in its environment - exported on the venv route, and passed
    in the container's own coordinates on the container route."""
    for path in (LAUNCHER, TEMPLATE):
        # arrange
        text = path.read_text(encoding="utf-8")

        # act: the export, and the `-e` pairs the container run is given
        exported = {name for line in re.findall(r"^export ([A-Z_ ]+)$", text, re.M) for name in line.split()}
        crossing = dict(re.findall(r'-e "(LAUNCH_[A-Z_]+)=([^"]+)"', text))

        # assert
        assert {"LAUNCH_ORCH_DIR", "LAUNCH_IMAGE_PIN"} <= exported, f"{path.name}: {sorted(exported)}"
        assert crossing.get("LAUNCH_ORCH_DIR") == "$ORCH_IN_SRC", f"{path.name}: {crossing}"
        assert crossing.get("LAUNCH_IMAGE_PIN") == "$PIN_IN_SRC", f"{path.name}: {crossing}"
        assert 'PIN_IN_SRC="/src/${LAUNCH_IMAGE_PIN#"$ROOT/"}"' in text, path.name


# --- THE BATCH LAUNCHER (si#479) ------------------------------------------------------------------------
#
# si#225 put GH_TOKEN on the `.sh` arm only, and everything above read `.sh` files only, so nothing saw the
# `.cmd` launcher stop one name short. These hold the batch launcher's three ways in - the two namespaces
# and the fixed names - against the shell launcher's `case`, on the kernel's own `simplon.cmd` and on the
# template every scaffolded product gets.

BATCH_LAUNCHER = ROOT / "simplon.cmd"
BATCH_TEMPLATE = ROOT / "src" / "simplon" / "templates" / "launch.cmd.j2"

#: `for %%N in (CI NO_COLOR ...) do call :forward %%N` - the fixed names. Letters only inside the
#: parentheses, so the `(%LAUNCH_ENV_PASS%)` loop beside it is not read as one.
_BATCH_FIXED = re.compile(r"^for %%N in \(([A-Z_ ]+)\) do call :forward %%N$", re.M)

#: `` for /f ... (`set DELIVERY_ 2^>nul`) do call :forward %%N `` - a namespace, matched by prefix.
_BATCH_NAMESPACE = re.compile(r"\(`set ([A-Z_]+?)_ 2\^>nul`\) do call :forward %%N$", re.M)

#: `if /i "%~1"=="NAME" goto :eof` inside `:forward` - a name it refuses to forward.
_BATCH_SKIP = re.compile(r'^if /i "%~1"=="([A-Z_]+)" goto :eof$', re.M)

#: The shell arm that skips the names the launcher sets itself.
_SKIP_ARM = re.compile(r"^\s*([A-Z_|]+)\)\s*;;$", re.M)


def _batch_texts() -> list[tuple[str, str]]:
    return [(BATCH_LAUNCHER.name, BATCH_LAUNCHER.read_text(encoding="utf-8")),
            (BATCH_TEMPLATE.name, _rendered(BATCH_TEMPLATE.name))]


def test_the_batch_launcher_forwards_the_same_fixed_names_as_the_shell_one():
    """si#479. The `.cmd` loop forwarded CI, NO_COLOR, TERM, TZ and GITHUB_TOKEN - GH_TOKEN, the one `gh`
    reads first, stopped at the boundary on Windows only."""
    # arrange
    shell = _forwarded(LAUNCHER.read_text(encoding="utf-8")) - {"DELIVERY_*"}
    for name, text in _batch_texts():
        # act
        loops = _BATCH_FIXED.findall(text)
        assert len(loops) == 1, f"{name}: expected one fixed-name forwarding loop, found {loops}"
        batch = set(loops[0].split())

        # assert
        assert batch == shell, f"{name}: only in the .cmd: {sorted(batch - shell)}, " \
                               f"only in the .sh: {sorted(shell - batch)}"


def test_the_batch_launcher_forwards_the_kernels_namespace_and_the_products():
    """The `.sh` arm's other two ways in: `DELIVERY_*` and `"$ENV_PREFIX"_*`, the prefix being the
    product name upper-cased with `-` as `_`. simplon's own `simplon.cmd` must say SIMPLON."""
    for name, text in _batch_texts():
        # act
        namespaces = _BATCH_NAMESPACE.findall(text)

        # assert
        assert "DELIVERY" in namespaces, f"{name}: {namespaces}"
        expected = "SIMPLON" if name == "simplon.cmd" else "FOO_CTL"
        assert expected in namespaces, f"{name}: {namespaces}"
        assert len(namespaces) == 2, f"{name}: {namespaces}"


def test_the_batch_launcher_skips_the_names_the_shell_one_skips():
    """The names the launcher sets on the container line itself; a host value of them must not cross."""
    # arrange
    arm = _SKIP_ARM.search(LAUNCHER.read_text(encoding="utf-8"))
    assert arm, "the shell launcher no longer has a skip arm"
    shell = set(arm.group(1).split("|"))
    for name, text in _batch_texts():
        # act
        batch = set(_BATCH_SKIP.findall(text.split("\n:forward\n")[1].split("goto :eof\n\n")[0] + "\n"))

        # assert
        assert batch == shell, f"{name}: only in the .cmd: {sorted(batch - shell)}, " \
                               f"only in the .sh: {sorted(shell - batch)}"


def test_both_launchers_forward_the_one_list_the_kernel_keeps():
    """si#479's repair: the fixed names are written once, `launcherenv.FORWARDED`, and rendered into both
    templates - so neither template may carry a literal list of its own beside the placeholder."""
    # arrange
    expected = set(launcherenv.FORWARDED)
    for name, text in _shell_texts():
        # act / assert
        assert _forwarded(text) - {"DELIVERY_*"} == expected, name
    for name, text in _batch_texts():
        assert set(_BATCH_FIXED.findall(text)[0].split()) == expected, name
    assert "{{ forwarded_sh }}" in TEMPLATE.read_text(encoding="utf-8")
    assert "{{ forwarded }}" in BATCH_TEMPLATE.read_text(encoding="utf-8")
