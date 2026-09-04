"""Unit tests for delivery.labinstance (netctl#1404, epic netctl#1403): the lab-instance resolution
precedence, moved out of netctl's orchestrator.paths so any `*ctl` product running N isolated labs
inherits it instead of restating it.

Two load-bearing contracts:
  1. PRECEDENCE - an explicit ``--instance`` flag beats the product's env var beats a LINKED git
     worktree's derived id beats the reserved default. The MAIN checkout resolves to the DEFAULT, which
     is what keeps a product's single-tenant human UX byte-for-byte unchanged;
  2. the worktree derivation is DETERMINISTIC, collision-resistant and always inside the product's
     id-length budget + ``[a-z0-9]`` charset, so an auto-derived id never trips the product's own id
     validation.

The three product values (env var spelling, default id, id-length budget) arrive as manifest DATA
through delivery.context; the tests register a fake ProductContext exactly as test_commands_env.py does.
AAA throughout; goal-stating names, incl. the negative manifest cases.
"""
import re

import pytest

from delivery import context, labinstance
from delivery.context import ProductContext

# The sample product's instance section: a 2-char budget, as netctl's IFNAMSIZ ceiling yields.
_SPEC = {"env_var": "SAMPLE_INSTANCE", "default": "dev", "max_id_len": 2}


def _register(monkeypatch, tmp_path, data=None, root=None):
    """Register a fake ProductContext carrying `data` as the raw manifest (and `root` as the checkout)."""
    ctx = ProductContext("sample", root or tmp_path, tmp_path / "sample.yaml")
    monkeypatch.setattr(context, "_current", ctx)
    monkeypatch.setattr(ProductContext, "manifest_data",
                        lambda self: {"instance": _SPEC} if data is None else data)
    return ctx


@pytest.fixture(autouse=True)
def _no_ambient_instance_env(monkeypatch):
    """No ambient instance env var leaks into a test asserting the flag/worktree/default branches."""
    monkeypatch.delenv(_SPEC["env_var"], raising=False)


# --- precedence: flag > env > worktree > default -------------------------------------------------------

def test_the_flag_beats_the_env_var_and_the_worktree(monkeypatch, tmp_path):
    # arrange: an env value AND a worktree basename are both present
    _register(monkeypatch, tmp_path)
    monkeypatch.setenv(_SPEC["env_var"], "b2")

    # act / assert: the explicit flag still wins
    assert labinstance.resolve("a1", worktree="agent-deadbeef") == "a1"


def test_the_env_var_beats_the_worktree_derivation(monkeypatch, tmp_path):
    # arrange: no flag, env set AND a worktree basename present
    _register(monkeypatch, tmp_path)
    monkeypatch.setenv(_SPEC["env_var"], "t1")

    # act / assert: the env var is the CI/agent override and wins over the derivation
    assert labinstance.resolve(worktree="agent-a8509328afcad1b0f") == "t1"


def test_a_linked_worktree_derives_its_own_id_when_flag_and_env_are_absent(monkeypatch, tmp_path):
    # arrange: no flag, no env, a linked-worktree basename
    _register(monkeypatch, tmp_path)

    # act
    resolved = labinstance.resolve(worktree="agent-a8509328afcad1b0f")

    # assert: the derived id, never the default
    assert resolved == labinstance.from_worktree("agent-a8509328afcad1b0f", _SPEC["max_id_len"])
    assert resolved != _SPEC["default"]


def test_the_main_checkout_resolves_to_the_manifest_default(monkeypatch, tmp_path):
    # arrange: nothing set anywhere; worktree=None asserts the MAIN checkout (no linked-worktree basename)
    _register(monkeypatch, tmp_path)

    # act / assert: the reserved single-tenant default
    assert labinstance.resolve(None, worktree=None) == "dev"


def test_a_blank_flag_is_semantically_absent_and_falls_through_to_the_env_var(monkeypatch, tmp_path):
    # arrange: `--instance ''` / `--instance '   '` must not be taken as an id
    _register(monkeypatch, tmp_path)
    monkeypatch.setenv(_SPEC["env_var"], "b2")

    # act / assert
    assert labinstance.resolve("") == "b2"
    assert labinstance.resolve("   ") == "b2"


def test_a_flag_value_is_stripped_of_surrounding_whitespace(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path)

    # act / assert
    assert labinstance.resolve("  a1  ") == "a1"


def test_a_whitespace_only_env_value_is_treated_as_unset(monkeypatch, tmp_path):
    # arrange: an env var set to blanks is semantically empty -> falls through to the default
    _register(monkeypatch, tmp_path)
    monkeypatch.setenv(_SPEC["env_var"], "   ")

    # act / assert
    assert labinstance.resolve(worktree=None) == "dev"


# --- the worktree probe: only a LINKED worktree derives an id ------------------------------------------

def test_worktree_basename_returns_the_name_when_dot_git_is_a_file(tmp_path):
    # arrange: a LINKED worktree has a `.git` FILE holding a `gitdir:` pointer
    root = tmp_path / "agent-a33a2c1b"
    root.mkdir()
    (root / ".git").write_text("gitdir: /elsewhere/.git/worktrees/agent-a33a2c1b\n")

    # act / assert
    assert labinstance.worktree_basename(root) == "agent-a33a2c1b"


def test_worktree_basename_returns_none_for_the_main_checkout(tmp_path):
    # arrange: the MAIN checkout has a real `.git` DIRECTORY -> the default id must be preserved
    root = tmp_path / "netctl"
    (root / ".git").mkdir(parents=True)

    # act / assert
    assert labinstance.worktree_basename(root) is None


def test_worktree_basename_returns_none_for_a_non_git_tree(tmp_path):
    # arrange: no `.git` at all
    root = tmp_path / "plain"
    root.mkdir()

    # act / assert
    assert labinstance.worktree_basename(root) is None


def test_resolve_probes_the_registered_product_root_when_no_worktree_is_injected(monkeypatch, tmp_path):
    # arrange: the registered context's root IS a linked worktree, and nothing is injected
    root = tmp_path / "agent-a8509328afcad1b0f"
    root.mkdir()
    (root / ".git").write_text("gitdir: /elsewhere\n")
    _register(monkeypatch, tmp_path, root=root)

    # act / assert: the bare call probes that root rather than falling back to the default
    assert labinstance.resolve() == labinstance.from_worktree(root.name, _SPEC["max_id_len"])


# --- from_worktree: pure normalisation + hashing -------------------------------------------------------

def test_the_worktree_id_is_deterministic_for_the_same_basename():
    # arrange / act / assert: stable hash, not the salted builtin -> same id every call
    assert labinstance.from_worktree("agent-a8509328afcad1b0f", 2) \
        == labinstance.from_worktree("agent-a8509328afcad1b0f", 2)


def test_the_worktree_id_fits_the_length_budget_and_the_charset():
    # arrange / act
    derived = labinstance.from_worktree("agent-a8509328afcad1b0f", 2)

    # assert: inside the budget and only [a-z0-9], so a product's id validation never rejects an auto id
    assert 1 <= len(derived) <= 2
    assert re.fullmatch(r"[a-z0-9]{1,2}", derived)


def test_the_worktree_id_keeps_a_short_conforming_basename_verbatim():
    # arrange / act / assert: a 2-char [a-z0-9] worktree name is used as-is, not hashed
    assert labinstance.from_worktree("a1", 2) == "a1"
    assert labinstance.from_worktree("zz", 2) == "zz"


def test_the_worktree_id_normalises_case_and_strips_punctuation_within_budget():
    # arrange / act / assert: "A-" -> "a" (lowercased, punctuation dropped), fits the budget verbatim
    assert labinstance.from_worktree("A-", 2) == "a"


def test_two_agent_worktrees_do_not_collapse_onto_the_same_prefix():
    # arrange: both start "agent-", so a naive 2-char prefix would alias them; hashing the FULL basename
    # keeps them distinct.
    left = labinstance.from_worktree("agent-a8509328afcad1b0f", 2)
    right = labinstance.from_worktree("agent-b1cbeeea59a5b945f", 2)

    # act / assert
    assert left != right


def test_the_worktree_id_hashes_an_empty_or_all_punctuation_basename_to_a_legal_id():
    # arrange: no usable [a-z0-9] chars -> must still yield a legal, non-empty id (never crash validation)
    for odd in ("", "---", "___", "!!"):
        derived = labinstance.from_worktree(odd, 2)
        assert re.fullmatch(r"[a-z0-9]{1,2}", derived)
        assert derived != "dev"


def test_the_worktree_id_hashes_an_over_long_basename_into_the_budget():
    # arrange: a long branch-style name normalises past the budget -> hashed down, still legal
    derived = labinstance.from_worktree("feat-465-worktree-instance-id", 2)

    # act / assert
    assert len(derived) == 2
    assert re.fullmatch(r"[a-z0-9]{2}", derived)


def test_the_length_budget_is_honoured_rather_than_hardcoded():
    # arrange / act / assert: a product with a wider budget gets a wider hashed id
    assert len(labinstance.from_worktree("agent-a8509328afcad1b0f", 4)) == 4


# --- spec(): the product values are manifest DATA, and a bad section fails LOUDLY ----------------------

def test_spec_reads_the_three_product_values_from_the_manifest(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path)

    # act / assert
    assert labinstance.spec() == labinstance.InstanceSpec("SAMPLE_INSTANCE", "dev", 2)


def test_spec_rejects_a_manifest_without_an_instance_section(monkeypatch, tmp_path):
    # arrange: the section is absent entirely
    _register(monkeypatch, tmp_path, data={"product": "sample"})

    # act / assert
    with pytest.raises(ValueError, match="instance"):
        labinstance.spec()


@pytest.mark.parametrize("missing", ["env_var", "default", "max_id_len"])
def test_spec_rejects_a_manifest_missing_any_of_the_three_keys(monkeypatch, tmp_path, missing):
    # arrange: drop exactly one key - a yaml typo must never silently resolve the wrong tenant
    partial = {k: v for k, v in _SPEC.items() if k != missing}
    _register(monkeypatch, tmp_path, data={"instance": partial})

    # act / assert
    with pytest.raises(ValueError, match=missing):
        labinstance.spec()


@pytest.mark.parametrize("bad", ["two", 2.5, True, [2]])
def test_spec_rejects_a_non_integer_length_budget(monkeypatch, tmp_path, bad):
    # arrange: `2.5` is the interesting one - int() would truncate it to a legal-looking 2
    _register(monkeypatch, tmp_path, data={"instance": {**_SPEC, "max_id_len": bad}})

    # act / assert
    with pytest.raises(ValueError, match="max_id_len"):
        labinstance.spec()


def test_spec_rejects_a_length_budget_below_one(monkeypatch, tmp_path):
    # arrange: a 0-char budget would derive the empty (illegal) id
    _register(monkeypatch, tmp_path, data={"instance": {**_SPEC, "max_id_len": 0}})

    # act / assert
    with pytest.raises(ValueError, match="max_id_len"):
        labinstance.spec()
