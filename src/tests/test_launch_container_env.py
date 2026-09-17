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

#: The kernel's own launcher, and the template every scaffolded product is rendered from.
LAUNCHER = ROOT / "simplon.sh"
TEMPLATE = ROOT / "src" / "simplon" / "templates" / "launch.sh.j2"

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
    scaffolded = _forwarded(TEMPLATE.read_text(encoding="utf-8"))

    # assert
    assert mine == scaffolded, f"only in simplon.sh: {sorted(mine - scaffolded)}, " \
                               f"only in the template: {sorted(scaffolded - mine)}"


def test_the_prose_above_the_arm_names_the_same_variables_the_arm_forwards():
    """The comment over that `case` lists the variables in prose, and si#225 found it one name short of
    the code beneath it. A list written twice drifts; this is the cheap half of keeping it honest."""
    for path in (LAUNCHER, TEMPLATE):
        # arrange
        text = path.read_text(encoding="utf-8")

        # act: the prose spells them slash-separated, the arm pipe-separated
        prose = {name for name in re.findall(r"[A-Z][A-Z_]+", text.split("WHICH VARIABLES CROSS")[1]
                                             .split("ENV_PREFIX=")[0])}

        # assert
        for name in _forwarded(text) - {"DELIVERY_*"}:
            assert name in prose, f"{path.name}: the arm forwards {name} and the prose above does not " \
                                  f"name it"
