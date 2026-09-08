"""The load-time refusals, counted and sorted by what they cost a product (si#48).

WHY THIS EXISTS. The owner's objection is not about any one rule, it is about the SUM: "we must be
careful not to build so many rules into Simplon that flexibility is restricted too far." Every refusal
in the kernel had a measured cause when it landed. Nobody had ever added them up, and nothing went red
when one more arrived. This module is the thing that goes red.

WHAT IT IS NOT. It changes no refusal and judges none of them individually. It is a census: every
load-time refusal a product manifest can trip, sorted into the kinds `CLAUDE.md` names, with the count
per kind published on the website and derived from here.

WHY THE POPULATION IS DERIVED AND NOT LISTED. The count on the website is the number this suite
computes by walking the two load-path modules' syntax trees, so a refusal added tomorrow is in the
population the moment it is written. It then has no entry in `CENSUS` and
`test_every_load_time_refusal_is_classified` goes red, naming it. That is the whole mechanism: the sum
cannot grow silently, because growing it breaks the build until somebody says which kind the new one
is. A hand-maintained list would have exactly the drift the ticket is about.

THE COUNT THAT STARTED THE TICKET WAS 61, AND IT WAS THE WRONG POPULATION - TWICE. `grep -c 'raise
ValueError'` over the loader's two modules returns 61, and six of those are not load-time refusals a
product can trip: five are methods on `Manifest`/`PlanNode` that run when a plan is built or a command is
run (two of them documented as defensive - "load() already rejects cyclic manifests, so a validated
manifest never trips it here"), and one is `_validation_message`'s funnel, which re-raises what the model
already raised rather than refusing anything of its own.

The second error was the other way round and si#61 found it: the population was two modules, and there
are three. The `suites:` section is refused by `tasks/testrun.py` - sixteen refusals a product manifest
trips at load, on the manifest's content alone - and every one of them was outside a census whose whole
job is that the sum cannot grow quietly. `Suites.gate` is the one exclusion there, on the same rule as
`Manifest`/`PlanNode`: it refuses a command name against an already-validated taxonomy.

All exclusions are computed here rather than listed, so they stay true: a class rename or a second funnel
is picked up by the walk.

THE THREE KINDS, AND WHY ONLY TWO OF THEM PARTITION. `CLAUDE.md` names diagnosis, self-binding and
expression rule. Those are not three buckets of refusal sites, and its own examples say so: si#34 is
listed under BOTH self-binding and expression rule, and si#47 - the other self-binding example - is
not a load-time refusal at all, it is an image pin in a task body. Self-binding is a statement about a
rule's REACH, not about what kind of thing it is. So the census partitions the sites into the two
kinds that do partition, by one question:

    would the refused manifest have produced a WORKING product, just a different one?

    yes -> EXPRESSION RULE. The product could have said this and meant it. This is the kind that costs
           flexibility, and the only kind that needs justifying.
    no  -> DIAGNOSIS. The declaration was broken, inert, or rendered nowhere. Refusing it takes nothing
           away, and without it the failure would be silent - which is the defect this repository
           spends most of its time hunting.

and then records, for each expression rule only, the third kind as its REACH: whether the kernel is
held to it too (`REACH_MERGED`), whether it is a statement about the seam between platform and product
where "the kernel too" means nothing (`REACH_SEAM`), or whether the kernel deliberately exempted itself
(`REACH_KERNEL_EXEMPT`).

THERE IS EXACTLY ONE SELF-EXEMPTION, and it is the finding acceptance 3 asks for. It is measured rather
than asserted: `test_the_one_self_exemption_is_real_and_its_size_is_measured` runs the rule over the
kernel's own catalogue and counts what it would refuse.

RED WHEN THERE IS NOTHING. Every helper here raises rather than returning an empty result for a missing
module, a missing heading or a missing table, and every count assertion is paired with the number of
things it ruled on - a census that classified nothing would otherwise pass exactly like one that
classified fifty-five.

AAA throughout.
"""
import ast
import re

import pytest

from simplon import catalogue as catalogue_mod

from conftest import ROOT

#: The three modules a product manifest is refused by. Everything else in the kernel refuses at RUN time -
#: a task that cannot reach its tool, an image without a pin - and those are a different population with
#: a different cost.
#:
#: `tasks/testrun.py` JOINED THIS LIST IN si#61, and the population it was missing is the point. The
#: `suites:` section is product-owned data the CLI engine never looks at, so its refusals are raised in the
#: task module rather than in the loader - but `declared()` runs before anything else does, on the
#: manifest's content alone, and refuses the whole test taxonomy without consulting a tool. Measured on a
#: real Java product: `./javademo.sh test unit` came back with a ValueError from `declared` having run no
#: gradle, no pytest and no docker. That is a load-time cost by any reading, and sixteen refusals of it
#: were outside the census while the page published a total.
LOAD_PATH = (ROOT / "src" / "simplon" / "orchestrator" / "manifest.py",
             ROOT / "src" / "simplon" / "orchestrator" / "model" / "treeform.py",
             ROOT / "src" / "simplon" / "tasks" / "testrun.py")

#: The chapter that publishes the counts.
CHAPTER = ROOT / "site" / "content" / "building" / "rules.md"

#: Classes whose methods run against an ALREADY LOADED manifest - planning and running, not loading.
#: `Suites` is the third for the same reason as the other two: `Suites.gate(name)` is a lookup a command
#: does after `declared()` has already validated the taxonomy, so it refuses a command name and not a
#: manifest section.
NOT_LOAD_TIME = ("Manifest", "PlanNode", "Suites")

#: The funnel that re-raises a Pydantic error as the plain ValueError `load()` promises. It refuses
#: nothing of its own; every rule it carries is raised inside `_ManifestModel` and counted there.
FUNNEL = "_validation_message"

DIAGNOSIS = "diagnosis"
EXPRESSION = "expression rule"

REACH_MERGED = "the kernel is held to it too"
REACH_SEAM = "a statement about the platform/product seam"
REACH_KERNEL_EXEMPT = "the kernel exempts itself"


# --- the census ----------------------------------------------------------------------------------------
#
# One entry per load-time refusal, keyed by its enclosing function and a fragment of its own message.
# Keyed that way rather than by line number because a line number is stale on the next edit, and rather
# than by an ordinal because a reordering would silently reclassify. The fragment is a SECOND SOURCE for
# the message, which this repository pins rather than trusts: `test_every_census_key_names_exactly_one
# _refusal` fails if a message is reworded past its key, so the key cannot come to describe a refusal
# that is no longer there.

CENSUS: dict[tuple[str, str], str] = {
    # --- manifest.py -----------------------------------------------------------------------------
    ("_split_impl", "impl must be 'module:function'"): DIAGNOSIS,
    ("_short_first_needs_a_short_flag_to_order", "needs a `short:` flag to put first"): DIAGNOSIS,
    ("_a_positional_takes_no_short_flag", "is positional and takes no `short:`"): DIAGNOSIS,
    # Click accepts more in the short slot than this does, and a manifest that used it would render a
    # working command line. That makes it an expression rule rather than a diagnosis, however sensible.
    ("_single_dashed_letter", "must be a single dash plus one letter"): EXPRESSION,
    ("_str_tuple", "'depends_on' must be a list of command names"): DIAGNOSIS,
    ("_reject_removed_composites", "which has been removed"): DIAGNOSIS,
    ("_coerce_groups", "'groups' must be a mapping of group name"): DIAGNOSIS,
    ("_coerce_groups", "must be a mapping of command name -> spec"): DIAGNOSIS,
    ("_coerce_env_groups", "'env_groups' must be a list of group names"): DIAGNOSIS,
    ("_validate_taxonomy", "manifest defines no groups"): DIAGNOSIS,
    ("_validate_taxonomy", "names a NESTED group"): DIAGNOSIS,
    ("_validate_taxonomy", "is not a declared group"): DIAGNOSIS,
    # The v1 lock. A command with both would run - the forward path is named in the comment beside it
    # and deliberately not built - so this forbids something expressible.
    ("_validate_taxonomy", "impl and depends_on are mutually exclusive"): EXPRESSION,
    ("_validate_taxonomy", "passthrough_args cannot combine with depends_on"): DIAGNOSIS,
    ("_validate_taxonomy", "stop_on_failure applies to an aggregate"): DIAGNOSIS,
    ("_validate_taxonomy", "keep_awake applies to an aggregate's plan"): DIAGNOSIS,
    ("_validate_taxonomy", "hidden has no effect on a group-default namesake"): DIAGNOSIS,
    ("_validate_taxonomy", "missing impl"): DIAGNOSIS,
    # An undocumented command is a working command. The kernel requires the sentence anyway.
    ("_validate_taxonomy", "missing help"): EXPRESSION,
    ("_validate_taxonomy", "is not a command in the manifest"): DIAGNOSIS,
    ("_validate_taxonomy", "is ambiguous (owned by groups"): DIAGNOSIS,
    ("walk", "dependency cycle: "): DIAGNOSIS,
    # netctl#1319. The manifest loads and runs; what is wrong is the abort scope, which is invisible.
    ("_validate_taxonomy", "disagree on stop_on_f"): EXPRESSION,
    ("load", "`groups:` is not a mapping"): DIAGNOSIS,
    ("load", "`tasks:` is not a mapping"): DIAGNOSIS,
    ("load", "generate names group(s)"): DIAGNOSIS,
    ("load", "names a nested group the `taxonomy:` block"): DIAGNOSIS,
    ("_enforce_the_catalogue_owns_the_groups", "may not declare `taxonomy:`"): EXPRESSION,
    ("_enforce_the_catalogue_owns_the_groups", "names a group the catalogue's `groups:` does not declare"):
        EXPRESSION,
    ("_validate_param_bindings", "that are not parameters of"): DIAGNOSIS,
    ("resolve_ref", "cannot import module"): DIAGNOSIS,
    ("resolve_ref", "has no attribute"): DIAGNOSIS,

    # --- treeform.py -----------------------------------------------------------------------------
    ("_check_node_keys", "declares unknown key"): DIAGNOSIS,
    ("lower", "is not a mapping"): DIAGNOSIS,
    ("merge", "is not a mapping"): DIAGNOSIS,
    ("merge", "names a group the platform's tree does not declare"): EXPRESSION,
    ("merge", "shape_is_the_platforms"): EXPRESSION,
    ("merge", "declares no commands"): DIAGNOSIS,
    ("_merge_commands", "is declared as one kind of command and refined as another"): EXPRESSION,
    ("_merge_commands", "redeclares `task:`"): EXPRESSION,
    ("_check_command_is_mapping", "is not a mapping"): DIAGNOSIS,
    ("check_task", "is not a mapping"): DIAGNOSIS,
    ("check_task", "declares no `impl:`"): DIAGNOSIS,
    ("check_task", "which belongs on a command rather than on the task"): DIAGNOSIS,
    ("check_task", "declares unknown key"): DIAGNOSIS,
    # si#33: the flat form wrote a body straight onto a command, and it loaded.
    ("_resolve_one", "declares `impl:`"): EXPRESSION,
    ("_resolve_one", "declares neither `task:` nor `depends_on:`"): DIAGNOSIS,
    ("_resolve_one", "declares both `task:` and `depends_on:`"): EXPRESSION,
    ("_resolve_one", "declares `with:` as"): DIAGNOSIS,
    ("_resolve_one", "names no task"): DIAGNOSIS,
    ("_resolve_one", "with `with:` and also declares `params:`"): DIAGNOSIS,
    ("check_no_old_form", "is written in the flat command form"): EXPRESSION,
    ("check_coordinate_placement", "places the coordinate"): EXPRESSION,
    ("check_env_groups", "shape_is_the_platforms"): EXPRESSION,

    # --- tasks/testrun.py: the `suites:` section (si#61) --------------------------------------------
    #
    # ONE OF THE TWO THE TICKET WAS ABOUT IS GONE, AND HOW IT WENT IS THE INTERESTING PART. The census
    # sorts on one question - would the refused manifest have produced a WORKING product? - and for both
    # of them the measured answer was NO, which made both diagnosis and neither a cost. That answer was
    # right and it was not the whole story: TOGETHER they made an impl-only taxonomy - a product whose
    # only test runner is its own, which is every Java product - impossible to write at all, so a Java
    # product shipped a Python test asserting nothing in order to get a report.
    #
    #   - "exactly one gate must declare results: clear": still here, still diagnosis. Nothing but a
    #     clearing gate ever clears the shared results dir - `report()` merges into whatever is already
    #     there - so a taxonomy with no clearing gate merges this run into the last one's forever.
    #   - "an 'impl' gate cannot declare 'results'": GONE (si#61). It was diagnosis on a true reading -
    #     `Gate.clears` said True while `assess_gate` returned on the impl branch before the clear was
    #     reached, so the declaration counted and did nothing - and the repair was aimed at the wrong
    #     half. A key that is accepted and inert should be MADE to work where it can be; refusing it was
    #     only defensible while some other gate could carry the clear, and for an impl-only product none
    #     could. The impl branch honours the clear now, so there is nothing left to refuse. The raise
    #     site below is the same one, minus that key: `junit`, `args` and `preamble` are still inert on
    #     a gate the kernel only calls for an rc.
    #
    # Both halves stay measured against the mechanism in `test_suites_impl_only.py`, which is also where
    # the lesson is recorded: a refusal classified as diagnosis is not thereby free. Diagnosis is a
    # statement about the manifest that was refused; what the SET of refusals makes unsayable is a
    # separate question, and this census does not answer it.
    ("_str", "is required"): DIAGNOSIS,
    ("_str", "must be a non-empty string"): DIAGNOSIS,
    ("_gate", "each gate must be a mapping"): DIAGNOSIS,
    ("_gate", "declare exactly one of 'suite'"): DIAGNOSIS,
    ("_gate", "an 'impl' gate cannot declare"): DIAGNOSIS,
    ("_gate", "'results' must be"): DIAGNOSIS,
    # A pytest gate with no `junit:` is not refused for tidiness: the name is spliced into the argv, and
    # an empty one leaves `--junit-xml=` pointing at the reports DIRECTORY. Measured beside the two above.
    ("_gate", "must declare its own 'junit' file name"): DIAGNOSIS,
    ("declared", "section is missing or is not a mapping"): DIAGNOSIS,
    ("declared", "must be a non-empty list"): DIAGNOSIS,
    ("declared", "declares a duplicate gate name"): DIAGNOSIS,
    # The one refusal in this section that costs a product something. Two gates each taking the same
    # passthrough `-k` is a coherent thing to declare and the manifest would load and run; what the
    # kernel refuses is the RESULT - an expression written for one suite filters the other down to
    # nothing and still reports green. Same shape as the `stop_on_failure` disagreement above.
    ("declared", "at most one gate may declare args: true"): EXPRESSION,
    ("declared", "exactly one gate must declare results:"): DIAGNOSIS,
    ("declared", "is not the FIRST gate"): DIAGNOSIS,
    ("declared", "'{SECTION}.report' must be a mapping"): DIAGNOSIS,
    ("declared", "must be a list of result dirs"): DIAGNOSIS,
    ("declared", "holds a non-path entry"): DIAGNOSIS,
}

#: For each EXPRESSION rule only, the third kind `CLAUDE.md` names: how far the rule reaches.
REACH: dict[tuple[str, str], str] = {
    ("_single_dashed_letter", "must be a single dash plus one letter"): REACH_MERGED,
    ("_validate_taxonomy", "impl and depends_on are mutually exclusive"): REACH_MERGED,
    ("_validate_taxonomy", "missing help"): REACH_MERGED,
    ("_validate_taxonomy", "disagree on stop_on_f"): REACH_MERGED,
    ("_enforce_the_catalogue_owns_the_groups", "may not declare `taxonomy:`"): REACH_SEAM,
    ("_enforce_the_catalogue_owns_the_groups", "names a group the catalogue's `groups:` does not declare"):
        REACH_SEAM,
    ("merge", "names a group the platform's tree does not declare"): REACH_SEAM,
    ("merge", "shape_is_the_platforms"): REACH_SEAM,
    ("_merge_commands", "is declared as one kind of command and refined as another"): REACH_MERGED,
    ("_merge_commands", "redeclares `task:`"): REACH_MERGED,
    ("_resolve_one", "declares `impl:`"): REACH_MERGED,
    ("_resolve_one", "declares both `task:` and `depends_on:`"): REACH_MERGED,
    ("check_no_old_form", "is written in the flat command form"): REACH_SEAM,
    ("check_coordinate_placement", "places the coordinate"): REACH_MERGED,
    ("check_env_groups", "shape_is_the_platforms"): REACH_SEAM,
    # The `suites:` section is not part of the merged tree at all - it is product data end to end - so
    # "the kernel too" is a real statement here rather than an empty one: a kernel manifest declaring
    # `suites:` goes through the same `declared()` with no exemption path.
    ("declared", "at most one gate may declare args: true"): REACH_MERGED,
}


# --- reading the refusals out of the source --------------------------------------------------------------


def _refusals(path) -> list[tuple[str, str]]:
    """Every LOAD-TIME refusal in one module, as (enclosing function, the source of its message).

    A refusal is `raise ValueError(<message>)`. Two things are excluded, both computed rather than
    listed: a raise inside a class whose methods run after loading, and the funnel that re-raises a
    Pydantic error the model already raised.
    """
    source = path.read_text(encoding="utf-8")
    if not source.strip():
        raise ValueError(f"{path} is empty")
    found: list[tuple[str, str]] = []

    def walk(node, function: str | None, klass: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, function, child.name)
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, child.name, klass)
                continue
            if (isinstance(child, ast.Raise) and isinstance(child.exc, ast.Call)
                    and getattr(child.exc.func, "id", None) == "ValueError" and child.exc.args):
                message = ast.unparse(child.exc.args[0])
                if klass not in NOT_LOAD_TIME and FUNNEL not in message:
                    found.append((function or "<module>", message))
            walk(child, function, klass)

    walk(ast.parse(source), None, None)
    if not found:
        raise ValueError(f"{path}: no refusals found - the walk is broken, not the module")
    return found


def _all_refusals() -> list[tuple[str, str]]:
    return [site for path in LOAD_PATH for site in _refusals(path)]


def _matches(key: tuple[str, str]) -> list[tuple[str, str]]:
    """The refusals one census key names. Exactly one is the contract; the tests below hold it."""
    function, fragment = key
    return [site for site in _all_refusals() if site[0] == function and fragment in site[1]]


def _counts() -> dict[str, int]:
    """The census's own numbers, by kind. The single source for what the website prints."""
    out = {DIAGNOSIS: 0, EXPRESSION: 0}
    for kind in CENSUS.values():
        out[kind] += 1
    return out


def _reach_counts() -> dict[str, int]:
    out = {REACH_MERGED: 0, REACH_SEAM: 0, REACH_KERNEL_EXEMPT: 0}
    for reach in REACH.values():
        out[reach] += 1
    return out


# --- the population ------------------------------------------------------------------------------------


def test_the_walk_finds_refusals_in_every_load_path_module():
    """The one that has to fail first. Every count below is computed from this walk, so a walk that
    found nothing - a renamed module, an `ast` change, a refactor to a different raise shape - must be a
    red suite rather than a census of zero things classified perfectly.

    Named per module rather than in total, because that is how the third one went missing: a total of 55
    looked healthy while an entire manifest section's refusals were outside the population.
    """
    # act
    per_module = {path.name: len(_refusals(path)) for path in LOAD_PATH}

    # assert: every module refuses, and none has quietly become the only one that does
    assert per_module["manifest.py"] > 0
    assert per_module["treeform.py"] > 0
    assert per_module["testrun.py"] > 0
    assert sum(per_module.values()) == len(_all_refusals())
    assert len(per_module) == len(LOAD_PATH)


def test_the_excluded_raises_are_the_ones_that_do_not_refuse_a_manifest_at_load():
    """The population's edge, seen rather than asserted.

    `grep -c 'raise ValueError'` over these two modules returns more than the walk does, and the
    difference is the whole reason the ticket's opening number was the wrong population. This measures
    the difference and names what is in it, so a future exclusion cannot be added silently either.
    """
    # arrange: every `raise ValueError` in the two modules, including the ones the walk drops
    total = 0
    for path in LOAD_PATH:
        total += len(re.findall(r"^\s*raise ValueError\(", path.read_text(encoding="utf-8"), re.M))

    # act
    load_time = len(_all_refusals())

    # assert: the walk really is narrower than the grep, and by the seven sites named in the docstring
    assert load_time < total
    excluded = total - load_time
    assert excluded == 7, (
        f"the grep finds {total} raises and the walk keeps {load_time}; the {excluded} excluded are "
        f"meant to be the six Manifest/PlanNode/Suites methods plus the _validation_message funnel")

    # assert: and they are excluded for the stated reason, not by accident - every dropped raise sits in
    # a plan/run-time class or is the funnel
    plan_time, funnels = 0, 0
    for path in LOAD_PATH:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for klass in ast.walk(tree):
            if isinstance(klass, ast.ClassDef) and klass.name in NOT_LOAD_TIME:
                plan_time += sum(1 for n in ast.walk(klass) if isinstance(n, ast.Raise))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args
                    and FUNNEL in ast.unparse(node.exc.args[0])):
                funnels += 1
    assert plan_time == 6, f"{plan_time} raises sit in {NOT_LOAD_TIME}, not the six documented"
    assert funnels == 1, f"{funnels} funnels re-raise a Pydantic error, not the one documented"
    assert plan_time + funnels == excluded


# --- the classification is complete, and every key still names something ---------------------------------


def test_every_load_time_refusal_is_classified():
    """Acceptance 2, and the mechanism the whole ticket is for.

    A refusal added tomorrow lands in the population automatically and has no census entry, so this goes
    red and names it. That is what "the sum was never weighed" is fixed by: it can no longer grow
    without somebody saying which kind it is.
    """
    # arrange
    classified = {site for key in CENSUS for site in _matches(key)}

    # act
    unclassified = sorted(set(_all_refusals()) - classified)

    # assert
    assert unclassified == [], (
        "a load-time refusal has no entry in CENSUS. Say which kind it is - diagnosis if the refused "
        "manifest could not have produced a working product, expression rule if it could - and if it is "
        "an expression rule, give it a REACH entry and justify it against the three questions in "
        f"CLAUDE.md: {unclassified}")

    # assert: and it ruled on the whole population rather than on an empty set
    assert len(classified) == len(_all_refusals())
    assert len(classified) > 0


@pytest.mark.parametrize("key", sorted(CENSUS))
def test_every_census_key_names_exactly_one_refusal(key):
    """The other direction: no stale entry, no fragment that has come to match two.

    The fragment is a second source for a message, and this repository pins a quoted error text against
    the real one rather than trusting it. A message reworded past its key would otherwise leave the key
    classifying nothing while the refusal it meant went uncounted.
    """
    # act
    matches = _matches(key)

    # assert
    assert len(matches) == 1, (
        f"census key {key} matches {len(matches)} refusals - a reworded message, a deleted refusal, or a "
        f"fragment that is no longer distinctive: {[m[0] for m in matches]}")


def test_only_expression_rules_carry_a_reach_and_all_of_them_do():
    """The third kind is a property of an expression rule, not a third bucket of sites.

    `CLAUDE.md`'s own examples force this reading: si#34 is listed under self-binding AND under
    expression rule, and si#47 - the other self-binding example - is an image pin in a task body, not a
    load-time refusal at all. So REACH covers the expression rules and nothing else.
    """
    # arrange
    expression = {key for key, kind in CENSUS.items() if kind == EXPRESSION}

    # assert
    assert set(REACH) == expression, (
        f"REACH and the expression rules disagree; missing a reach: {sorted(expression - set(REACH))}; "
        f"a reach on something that is not an expression rule: {sorted(set(REACH) - expression)}")

    # assert: and every reach is one of the three, so a typo cannot invent a fourth
    assert set(REACH.values()) <= {REACH_MERGED, REACH_SEAM, REACH_KERNEL_EXEMPT}
    assert len(expression) > 0


# --- no expression rule exempts the kernel any more (si#53) ----------------------------------------------


def test_no_expression_rule_exempts_the_kernel_from_itself():
    """What is left of acceptance 3's finding after the owner acted on it.

    There was exactly one self-exemption, `check_every_task_is_used`, and this suite used to measure its
    SIZE - how many of the kernel's own catalogue tasks the rule would have refused if it ran over them.
    The answer was 14 of 22, si#48 published it, and si#53 struck the rule: it was the only expression
    rule with no measured cause in ticket, commit or docstring, and it forbade a product exactly what the
    kernel does fourteen times over - treating a catalogue as an OFFER.

    So the measurement becomes an assurance instead. Zero is not a vacuous number here: it is computed
    from REACH, which `test_only_expression_rules_carry_a_reach_and_all_of_them_do` holds against the
    census, which is computed from the source. A new self-exemption goes red here and has to bring the
    argument the struck one never had.
    """
    # arrange
    exempt = sorted(key for key, reach in REACH.items() if reach == REACH_KERNEL_EXEMPT)

    # act / assert
    assert exempt == [], (
        "an expression rule exempts the kernel from itself. si#53 struck the only one there was, for "
        "the reason its docstring could not answer: a rule the kernel would have to break fourteen "
        "times in its own catalogue is not a rule anybody believes twice. Say why this one is "
        f"different, in the ticket: {exempt}")

    # assert: and there really were expression rules to rule on, so the emptiness above is a finding
    assert len(REACH) > 0
    assert set(REACH.values()) == {REACH_MERGED, REACH_SEAM}


def test_the_kernels_own_manifest_violates_none_of_its_own_expression_rules():
    """The kernel is a product of itself, so its own manifest is the first place an expression rule can
    be measured against something real. It loads, which is the whole assertion: a manifest that loads
    has violated no refusal in the census, expression rule or otherwise."""
    # arrange
    from simplon.orchestrator import manifest as manifest_mod

    # act
    loaded = manifest_mod.load((ROOT / "simplon.yaml").read_text(encoding="utf-8"),
                               catalogue=catalogue_mod.load())

    # assert: it really loaded a tree rather than an empty one that would satisfy this vacuously
    assert loaded.groups
    assert sum(len(members) for members in loaded.commands.values()) > 0


# --- the website prints the census's numbers and not its own ---------------------------------------------


def _text() -> str:
    """The chapter, refusing to be empty - every parser below would otherwise hold vacuously."""
    body = CHAPTER.read_text(encoding="utf-8")
    if not body.strip():
        raise ValueError(f"{CHAPTER} is empty")
    return body


#: A row of the census table on the page: `| diagnosis | 39 | ... |`.
_ROW = re.compile(r"^\|\s*\*{0,2}([A-Za-z][A-Za-z /-]*?)\*{0,2}\s*\|\s*\*{0,2}(\d+)\*{0,2}\s*\|")


def _published_counts(heading: str, header: str) -> dict[str, int]:
    """One table on the page, as `label -> number`.

    Located by its heading AND its header row rather than by "the n-th table", so a table added above it
    does not silently become the thing under test. A table that is not there raises: an empty mapping
    would make every comparison over it hold vacuously.
    """
    lines = _text().split("\n")
    start = lines.index(heading)
    rows: dict[str, int] = {}
    seen_header = False
    for line in lines[start:]:
        if line.startswith(header):
            seen_header = True
            continue
        if not seen_header:
            continue
        if not line.startswith("|"):
            if rows:
                break
            continue
        match = _ROW.match(line)
        if match:
            rows[match.group(1).strip()] = int(match.group(2))
    if not rows:
        raise ValueError(f"{CHAPTER}: no table '{header}...' under '{heading}'")
    return rows


def test_the_page_prints_the_census_count_for_each_kind():
    """The trap this repository has fallen into twice this week, once six paragraphs under the sentence
    saying numbers are not typed: a number typed onto a page is wrong on the day nobody checks it.

    So every number the chapter prints about the census is compared with the census, which is itself
    computed from the source. Nothing here counts the page against itself.
    """
    # arrange
    expected = _counts()

    # act
    printed = _published_counts("## What a rule costs, and how many there are",
                                "| kind |")

    # assert: the two kinds that partition, each carrying the census's own number
    assert printed["diagnosis"] == expected[DIAGNOSIS]
    assert printed["expression rule"] == expected[EXPRESSION]

    # assert: and the total, which is the number the ticket asks for as the baseline
    assert printed["all load-time refusals"] == len(_all_refusals())
    assert printed["all load-time refusals"] == expected[DIAGNOSIS] + expected[EXPRESSION]


def test_the_page_prints_the_reach_of_the_expression_rules():
    """The third kind, published with the same guarantee. The self-exemption in particular is a number
    that would otherwise be true on the day it was typed and never again."""
    # arrange
    expected = _reach_counts()

    # act
    printed = _published_counts("### How far an expression rule reaches", "| reach |")

    # assert
    assert printed["the kernel is held to it too"] == expected[REACH_MERGED]
    assert printed["a statement about the platform/product seam"] == expected[REACH_SEAM]
    assert printed["the kernel exempts itself"] == expected[REACH_KERNEL_EXEMPT]

    # assert: and the three account for every expression rule, so a rule cannot fall out of the table
    assert sum(printed.values()) == _counts()[EXPRESSION]


def test_the_page_states_the_three_quality_goals_and_the_three_kinds():
    """Acceptance 1: the goals and the distinction are on the chapter where the rules are explained,
    rather than only in the working agreements a reader of the website never sees."""
    # arrange
    body = _text()

    # act / assert: the three goals, in the owner's own words
    for goal in ("clear structure", "extensibility", "reusability"):
        assert goal in body, f"the chapter does not name the quality goal '{goal}'"

    # assert: and the distinction, with the half that carries the whole point of making it
    for kind in ("Diagnosis", "Self-binding", "Expression rule"):
        assert kind in body, f"the chapter does not name the kind '{kind}'"
    assert "Only this kind costs flexibility" in body

    # assert: and the bar a new expression rule has to clear, so the section is a rule rather than a note
    assert "#48" in body


def test_the_chapters_existing_anchors_still_resolve():
    """Three other pages link into this chapter by heading anchor. A new section above them must not
    rename one, and a heading is exactly the kind of thing an edit like this breaks silently."""
    # arrange: the anchors linked from elsewhere on the site, read off those pages rather than remembered
    linked = set()
    for page in sorted((ROOT / "site" / "content").rglob("*.md")):
        for anchor in re.findall(r"building/rules/#([a-z0-9-]+)", page.read_text(encoding="utf-8")):
            linked.add(anchor)

    # act: the anchors Hugo derives from this chapter's own headings
    headings = re.findall(r"^#{2,3} (.+)$", _text(), re.M)
    available = {re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-") for h in headings}

    # assert
    assert linked, "no page links into this chapter any more - the assertion below would hold vacuously"
    assert linked <= available, f"a link into this chapter no longer resolves: {sorted(linked - available)}"
