"""The load-time refusals, counted and sorted by what they cost a product (si#48).

WHY THIS EXISTS. The owner's objection is not about any one rule, it is about the SUM: "we must be
careful not to build so many rules into Simplon that flexibility is restricted too far." Every refusal
in the kernel had a measured cause when it landed. Nobody had ever added them up, and nothing went red
when one more arrived. This module is the thing that goes red.

WHAT IT IS NOT. It changes no refusal and judges none of them individually. It is a census: every
load-time refusal a product manifest can trip, sorted into the kinds `CLAUDE.md` names, with the count
per kind published on the website and derived from here.

WHY THE POPULATION IS DERIVED AND NOT LISTED, AND WHAT IT COST TO LEARN THAT TWICE. The mechanism was
always meant to be: a refusal added tomorrow is in the population the moment it is written, has no entry
in `CENSUS`, and `test_every_load_time_refusal_is_classified` goes red naming it. What was NOT derived was
which modules to look in. That was a tuple of three paths, typed.

    si#48's opening number, 61, was `grep -c 'raise ValueError'` over the loader's two modules, and six
    of those are not refusals a product trips: five are methods on `Manifest`/`PlanNode` that run when a
    plan is built or a command is run, and one is `_validation_message`'s funnel, which re-raises what
    the model already raised.

    si#61 found the error the other way round: the population was two modules and there were three. The
    `suites:` section is refused in `tasks/testrun.py`, on the manifest's content alone, before any tool -
    sixteen refusals outside a census whose whole job is that the sum cannot grow quietly. The repair was
    to add a third path to the tuple.

    si#53 stopped repairing the list and derived it. The definition is in the block on `LOADER_ENTRY`
    below; the short form is that a manifest enters this kernel at two seams and the population is
    everything raised on the way from either of them to a decision, with no tool consulted in between.
    That found SIX more modules: `nexusproxy`, `tasks/claudeplugins.py`, `tasks/image.py`,
    `tasks/site.py`, `workflowgen`, and `docker.pinned_image` reached from `site.declared`.

The derivation is trusted because it agrees with numbers other people measured by hand: `treeform.py`
exactly, `manifest.py` exactly once the funnel is dropped, and `testrun.declared`'s closure is exactly
si#61's sixteen. A walk that reproduces three independent hand counts and then finds six more modules is
measuring something; one that only found more would be guessing.

The `NOT_LOAD_TIME` class list this docstring used to describe is GONE and its absence is the evidence:
`Manifest`, `PlanNode` and `Suites` still have methods that raise, and no rule has to remember to exclude
them, because nothing reaches them from either seam. One exclusion is left, `_validation_message`'s
funnel, and `test_the_only_excluded_raise_is_the_funnel_that_re_raises_the_model` holds it at exactly one.

WHAT THE WALK CANNOT DO, said here rather than left to be discovered. Six modules read the manifest
document INLINE, in the middle of a task body, so the reading and the tool-running are one function and no
static rule separates them. They are named in `READS_INLINE` with the reason - and which modules read the
document is COMPUTED, so a new one that is in neither half turns
`test_every_module_that_reads_the_manifest_is_accounted_for` red. The population is derived; the handling
of what it cannot walk is declared. That is the same division the census makes everywhere else.

THE THREE KINDS, AND WHY ONLY TWO OF THEM PARTITION. `CLAUDE.md` names diagnosis, self-binding and
expression rule. Those are not three buckets of refusal sites, and its own examples say so: si#34 is
listed under BOTH self-binding and expression rule, and si#47 - the other self-binding example - is
an image pin in a task body - which si#53 measured to BE a load-time refusal after all, decided on a
manifest string with nothing running, so that half of the old reading is simply wrong. Self-binding is a
statement about a rule's REACH, not about what kind of thing it is. So the census partitions the sites into the two
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

THERE IS NO SELF-EXEMPTION LEFT. There was one - `check_every_task_is_used` - and measuring it is what
ended it: si#48 put the exemption at 14 of the kernel's own 22 catalogue tasks and si#53 struck the rule.
`test_no_expression_rule_exempts_the_kernel_from_itself` now holds the zero, and goes red if a new
exemption arrives without the argument the struck one never had.

RED WHEN THERE IS NOTHING. Every helper here raises rather than returning an empty result for a missing
module, a missing heading or a missing table, and every count assertion is paired with the number of
things it ruled on - a census that classified nothing would otherwise pass exactly like one that
classified fifty-five.

AAA throughout.
"""
import ast
import functools
import re

import pytest

from simplon import catalogue as catalogue_mod

from conftest import ROOT

#: WHERE THE POPULATION COMES FROM, AND WHY IT IS NO LONGER A LIST (si#53, out of si#61).
#:
#: This used to be three module paths, typed. si#61 found what that costs: `tasks/testrun.py` was not on
#: the list, so sixteen refusals sat outside a census whose whole purpose is that the sum cannot grow
#: quietly. A list is only right for as long as somebody remembers it, and that assumption had already
#: broken once. So the population is DERIVED, and this is the definition it is derived from:
#:
#:     A LOAD-TIME REFUSAL IS ONE RAISED ON THE WAY FROM THE MANIFEST TO A DECISION, WITH NO TOOL
#:     CONSULTED IN BETWEEN.
#:
#: The manifest enters the kernel at exactly two seams, and both are in the source rather than in
#: anybody's memory:
#:
#:   1. `manifest.load(text)` - the document as TEXT, parsed into a command tree. Everything the loader
#:      reaches from there is load-path by construction.
#:   2. `ProductContext.manifest_data()` - the parsed DOCUMENT, handed to whatever reads a section of it.
#:      Every function the kernel calls with that value is a manifest reader, and `_document_entries`
#:      finds them by reading the call sites.
#:
#: From those two the walk follows calls - module-local by name, cross-module by `module.function`, and
#: into a Pydantic model's validators where one is constructed, because that is how `_ManifestModel`'s
#: rules actually run - and collects every `raise ValueError` it can reach. THAT is the population.
#:
#: WHAT THIS FOUND, and it is si#61's lesson repeating at a larger size: the list was short by six more
#: modules. `docker.pinned_image` (reached from `site.declared`), `nexusproxy`, `tasks/claudeplugins.py`,
#: `tasks/docs.py`, `tasks/image.py`, `tasks/site.py` and `workflowgen` refuse a product manifest on its
#: content alone, before any tool is consulted, exactly as `testrun.declared` does - and the sentence
#: this block used to open with ("everything else in the kernel refuses at RUN time - a task that cannot
#: reach its tool, an image without a pin") named one of them as the counter-example. The image pin is
#: decided on a manifest string with no docker running. It was never run time.
LOADER_ENTRY = ("orchestrator.manifest", "load")

#: The accessor a product's manifest DOCUMENT leaves `simplon.context` through. Read off the call sites
#: rather than assumed: a rename here changes the entry points and `test_the_walk_finds_refusals_at_both
#: _seams` goes red rather than quietly finding none.
DOCUMENT_ACCESSOR = "manifest_data"

SRC = ROOT / "src" / "simplon"

#: The chapter that publishes the counts.
CHAPTER = ROOT / "site" / "content" / "building" / "rules.md"

#: Modules that read the manifest document INLINE - `ctx.manifest_data().get(SECTION)` in the middle of a
#: task body - rather than handing it to a function of their own. The walk cannot separate the reading
#: from the running there: the enclosing function IS the task, so a closure from it reaches the tool and
#: the census would swell with refusals that are not about a manifest at all (measured: taking the
#: enclosing functions as entry points brings the population from 128 sites to 162, `docker.ensure_docker`
#: among them).
#:
#: THE LIST IS THE CLASSIFICATION, NOT THE POPULATION, which is the same division the census itself
#: makes. Which modules read the document is COMPUTED; what to do about one that cannot be walked is
#: declared here, with its reason, and `test_every_module_that_reads_the_manifest_is_accounted_for` goes
#: red the day a new one appears. That is the property si#61 asked for: a manifest reader cannot join the
#: kernel quietly, whether or not the walk can follow it.
READS_INLINE = {
    "environments": "reads `environments:`/`default:` into a local `data` inside `Provider.registry`, "
                    "which then builds backends - the reading and the wiring are one function",
    "labinstance": "`spec()` reads the topology section and goes on to talk to docker in the same body",
    "labegress": "`spec()`, same shape as labinstance",
    "tasks.artifact": "`_declared(name)` reads its section inline and is the front half of a task body",
    "tasks.asset": "`_declared(name)`, same shape as tasks.artifact",
    "tasks.env": "`environments()` reads the document inline to answer a listing",
}

#: The funnel that re-raises a Pydantic error as the plain ValueError `load()` promises. It refuses
#: nothing of its own; every rule it carries is raised inside `_ManifestModel` and counted there. The
#: ONE exclusion left: the walk's own shape now does what the `NOT_LOAD_TIME` class list used to do,
#: because `Manifest`, `PlanNode` and `Suites` are simply not reachable from either seam.
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

CENSUS: dict[tuple[str, str, str], str] = {
    # --- manifest.py -----------------------------------------------------------------------------
    ("manifest", "_split_impl", "impl must be 'module:function'"): DIAGNOSIS,
    ("manifest", "_short_first_needs_a_short_flag_to_order", "needs a `short:` flag to put first"): DIAGNOSIS,
    ("manifest", "_a_positional_takes_no_short_flag", "is positional and takes no `short:`"): DIAGNOSIS,
    # Click accepts more in the short slot than this does, and a manifest that used it would render a
    # working command line. That makes it an expression rule rather than a diagnosis, however sensible.
    ("manifest", "_single_dashed_letter", "must be a single dash plus one letter"): EXPRESSION,
    ("manifest", "_str_tuple", "'depends_on' must be a list of command names"): DIAGNOSIS,
    ("manifest", "_reject_removed_composites", "which has been removed"): DIAGNOSIS,
    ("manifest", "_coerce_groups", "'groups' must be a mapping of group name"): DIAGNOSIS,
    ("manifest", "_coerce_groups", "must be a mapping of command name -> spec"): DIAGNOSIS,
    ("manifest", "_coerce_env_groups", "'env_groups' must be a list of group names"): DIAGNOSIS,
    ("manifest", "_validate_taxonomy", "manifest defines no groups"): DIAGNOSIS,
    ("manifest", "_validate_taxonomy", "names a NESTED group"): DIAGNOSIS,
    ("manifest", "_validate_taxonomy", "is not a declared group"): DIAGNOSIS,
    # The v1 lock. A command with both would run - the forward path is named in the comment beside it
    # and deliberately not built - so this forbids something expressible.
    ("manifest", "_validate_taxonomy", "impl and depends_on are mutually exclusive"): EXPRESSION,
    ("manifest", "_validate_taxonomy", "passthrough_args cannot combine with depends_on"): DIAGNOSIS,
    ("manifest", "_validate_taxonomy", "stop_on_failure applies to an aggregate"): DIAGNOSIS,
    ("manifest", "_validate_taxonomy", "keep_awake applies to an aggregate's plan"): DIAGNOSIS,
    ("manifest", "_validate_taxonomy", "hidden has no effect on a group-default namesake"): DIAGNOSIS,
    # si#60: a nested group-default group answered `KeyError` out of `cli.assemble`. The refused
    # manifest produced no working product - it produced a stacktrace - so this is diagnosis, and
    # the capability stays deliberately unbuilt.
    ("manifest", "_validate_taxonomy", "a NESTED group cannot have a group-default namesake"): DIAGNOSIS,
    ("manifest", "_validate_taxonomy", "missing impl"): DIAGNOSIS,
    # An undocumented command is a working command. The kernel requires the sentence anyway.
    ("manifest", "_validate_taxonomy", "missing help"): EXPRESSION,
    ("manifest", "_validate_taxonomy", "is not a command in the manifest"): DIAGNOSIS,
    ("manifest", "_validate_taxonomy", "is ambiguous (owned by groups"): DIAGNOSIS,
    ("manifest", "walk", "dependency cycle: "): DIAGNOSIS,
    # netctl#1319. The manifest loads and runs; what is wrong is the abort scope, which is invisible.
    ("manifest", "_validate_taxonomy", "disagree on stop_on_f"): EXPRESSION,
    ("manifest", "load", "`groups:` is not a mapping"): DIAGNOSIS,
    ("manifest", "load", "`tasks:` is not a mapping"): DIAGNOSIS,
    ("manifest", "load", "generate names group(s)"): DIAGNOSIS,
    ("manifest", "load", "names a nested group the `taxonomy:` block"): DIAGNOSIS,
    ("manifest", "_enforce_the_catalogue_owns_the_groups", "may not declare `taxonomy:`"): EXPRESSION,
    ("manifest", "_enforce_the_catalogue_owns_the_groups", "names a group the catalogue's `groups:` does not declare"):
        EXPRESSION,
    ("manifest", "_validate_param_bindings", "that are not parameters of"): DIAGNOSIS,
    ("manifest", "resolve_ref", "cannot import module"): DIAGNOSIS,
    ("manifest", "resolve_ref", "has no attribute"): DIAGNOSIS,

    # --- treeform.py -----------------------------------------------------------------------------
    ("treeform", "_check_node_keys", "declares unknown key"): DIAGNOSIS,
    ("treeform", "lower", "is not a mapping"): DIAGNOSIS,
    ("treeform", "merge", "is not a mapping"): DIAGNOSIS,
    ("treeform", "merge", "names a group the platform's tree does not declare"): EXPRESSION,
    ("treeform", "merge", "shape_is_the_platforms"): EXPRESSION,
    ("treeform", "merge", "declares no commands"): DIAGNOSIS,
    ("treeform", "_merge_commands", "is declared as one kind of command and refined as another"): EXPRESSION,
    ("treeform", "_merge_commands", "redeclares `task:`"): EXPRESSION,
    ("treeform", "_check_command_is_mapping", "is not a mapping"): DIAGNOSIS,
    ("treeform", "check_task", "is not a mapping"): DIAGNOSIS,
    ("treeform", "check_task", "declares no `impl:`"): DIAGNOSIS,
    ("treeform", "check_task", "which belongs on a command rather than on the task"): DIAGNOSIS,
    ("treeform", "check_task", "declares unknown key"): DIAGNOSIS,
    # si#33: the flat form wrote a body straight onto a command, and it loaded.
    ("treeform", "_resolve_one", "declares `impl:`"): EXPRESSION,
    ("treeform", "_resolve_one", "declares neither `task:` nor `depends_on:`"): DIAGNOSIS,
    ("treeform", "_resolve_one", "declares both `task:` and `depends_on:`"): EXPRESSION,
    ("treeform", "_resolve_one", "declares `with:` as"): DIAGNOSIS,
    ("treeform", "_resolve_one", "names no task"): DIAGNOSIS,
    ("treeform", "_resolve_one", "with `with:` and also declares `params:`"): DIAGNOSIS,
    ("treeform", "check_no_old_form", "is written in the flat command form"): EXPRESSION,
    # si#81, and it is DIAGNOSIS by the sorting question rather than by preference. What is refused is a
    # `tasks:` declaration that is accepted and INERT: a command of the same name already runs a
    # different body, so the one written here is dead in the tree and nothing said so. That is the same
    # call this census already makes for `hidden` on a group-default namesake and for a `nexus:` block
    # declaring no repositories. It is deliberately NARROWER than `check_every_task_is_used`, which si#53
    # struck: a declared task whose name no command has taken is an offer and still loads.
    ("treeform", "check_no_shadowed_task_declaration",
     "is declared under `tasks:` and instantiated by no command"): DIAGNOSIS,
    ("treeform", "check_coordinate_placement", "places the coordinate"): EXPRESSION,
    ("treeform", "check_env_groups", "shape_is_the_platforms"): EXPRESSION,

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
    ("testrun", "_str", "is required"): DIAGNOSIS,
    ("testrun", "_str", "must be a non-empty string"): DIAGNOSIS,
    ("testrun", "_gate", "each gate must be a mapping"): DIAGNOSIS,
    ("testrun", "_gate", "declare exactly one of 'suite'"): DIAGNOSIS,
    ("testrun", "_gate", "an 'impl' gate cannot declare"): DIAGNOSIS,
    ("testrun", "_gate", "'results' must be"): DIAGNOSIS,
    # A pytest gate with no `junit:` is not refused for tidiness: the name is spliced into the argv, and
    # an empty one leaves `--junit-xml=` pointing at the reports DIRECTORY. Measured beside the two above.
    ("testrun", "_gate", "must declare its own 'junit' file name"): DIAGNOSIS,
    ("testrun", "declared", "section is missing or is not a mapping"): DIAGNOSIS,
    ("testrun", "declared", "must be a non-empty list"): DIAGNOSIS,
    ("testrun", "declared", "declares a duplicate gate name"): DIAGNOSIS,
    # The one refusal in this section that costs a product something. Two gates each taking the same
    # passthrough `-k` is a coherent thing to declare and the manifest would load and run; what the
    # kernel refuses is the RESULT - an expression written for one suite filters the other down to
    # nothing and still reports green. Same shape as the `stop_on_failure` disagreement above.
    ("testrun", "declared", "at most one gate may declare args: true"): EXPRESSION,
    ("testrun", "declared", "exactly one gate must declare results:"): DIAGNOSIS,
    ("testrun", "declared", "is not the FIRST gate"): DIAGNOSIS,
    ("testrun", "declared", "'{SECTION}.report' must be a mapping"): DIAGNOSIS,
    ("testrun", "declared", "must be a list of result dirs"): DIAGNOSIS,
    ("testrun", "declared", "holds a non-path entry"): DIAGNOSIS,

    # --- the six modules the population was short by (si#53) -----------------------------------------
    #
    # si#61 added `tasks/testrun.py` because somebody hit it. si#53 derived the population instead, and
    # the same shape came back six more times: every module below refuses a product manifest on its
    # content alone, before any tool is consulted, exactly as `testrun.declared` does. They were outside
    # a census that published a total, and the block at the top of this module used to name one of them -
    # "an image without a pin" - as the example of what is NOT in the population. The pin is decided on a
    # manifest string with nothing running. It was never run time.
    #
    # `nexusproxy` (the `nexus:` section), `tasks/claudeplugins.py` (`claude:`), `tasks/image.py`
    # (`images:`), `tasks/site.py` (`site:`), `workflowgen` (`workflows:`) and `docker.pinned_image`
    # (reached from `site.declared`, deciding the `site.image:` string) - and every one of those sections
    # is declared by a real product manifest today.

    # --- docker.pinned_image: the image string a manifest section pins ---------------------------------
    #
    # An unpinned image and `:latest` BOTH build. What they produce depends on the day, which is the
    # whole content of si#47 - and si#47 is also why these are REACH_MERGED rather than an exemption: the
    # kernel pinned its own three unpinned images rather than keep the rule for products only.
    ("docker", "pinned_image", "must pin a version ('<image>:<tag>')"): EXPRESSION,
    ("docker", "pinned_image", "not the moving tag 'latest'"): EXPRESSION,
    # These two are the malformed halves of the same key - `foo:` and a digest that is not one. Nothing
    # would have been built at all, so they take nothing away.
    ("docker", "pinned_image", "has no usable tag"): DIAGNOSIS,
    ("docker", "pinned_image", "carries a broken digest"): DIAGNOSIS,

    # --- nexusproxy: the `nexus:` section (netctl declares one) ----------------------------------------
    ("nexusproxy", "declared", "section is missing or is not a mapping"): DIAGNOSIS,
    ("nexusproxy", "declared", "proxy_repositories' must be a list"): DIAGNOSIS,
    # "declares none" is the accepted-and-inert shape, not a taste: the message says what the empty list
    # buys - a `cleanup` that reports success while the blob store grows. A declaration that renders
    # nowhere is diagnosis by this census's own question.
    ("nexusproxy", "declared", "proxy_repositories' declares none"): DIAGNOSIS,
    # The one refusal in this section that costs a product something. A REST listing path is a coherent
    # thing to declare and the product would run; what the kernel refuses is the RESULT - a listing
    # answers 200 on an instance serving nothing, so `serving` would be green on a dead Nexus. Same shape
    # as testrun's `args: true` rule, and the `nexus:` section is product data the kernel goes through
    # unchanged, so "the kernel too" is a real statement here.
    ("nexusproxy", "declared", "content_probe_path' must be a CONTENT path"): EXPRESSION,
    ("nexusproxy", "declared", "each entry must be a mapping with 'name', 'format' and 'api'"): DIAGNOSIS,
    ("nexusproxy", "declared", "must name 'name', 'format' and 'api'"): DIAGNOSIS,
    ("nexusproxy", "_text", "is missing or empty"): DIAGNOSIS,

    # --- tasks/claudeplugins.py: the `claude:` section (netctl declares one) ---------------------------
    ("claudeplugins", "declared", "section is missing or is not a mapping"): DIAGNOSIS,
    ("claudeplugins", "declared", "marketplaces' must be a mapping"): DIAGNOSIS,
    ("claudeplugins", "declared", "marketplaces' declares none"): DIAGNOSIS,
    ("claudeplugins", "declared", "plugins' must be a list"): DIAGNOSIS,
    ("claudeplugins", "declared", "plugins' declares none"): DIAGNOSIS,
    ("claudeplugins", "declared", "must be a mapping with 'source' and 'repo'"): DIAGNOSIS,
    # Not a rule about what a product may say - nothing but github is implemented, so the refused
    # manifest names a mechanism that does not exist.
    ("claudeplugins", "declared", "only source 'github' is supported"): DIAGNOSIS,
    ("claudeplugins", "declared", "repo must be 'owner/name'"): DIAGNOSIS,
    ("claudeplugins", "declared", "must be 'name@marketplace'"): DIAGNOSIS,
    ("claudeplugins", "declared", "names undeclared marketplace"): DIAGNOSIS,

    # --- tasks/docs.py: the docToolchain image tag ----------------------------------------------------
    ("docs", "_version", "pin the docToolchain image tag"): DIAGNOSIS,

    # --- tasks/image.py: the `images:` section (agile-cockpit declares one) ----------------------------
    ("image", "declared", "section is missing or is not a mapping - declare the registry"): DIAGNOSIS,
    ("image", "declared", "no image '{name}' in the"): DIAGNOSIS,
    ("image", "declared", "image '{name}' is not a mapping"): DIAGNOSIS,
    ("image", "_str", "is required"): DIAGNOSIS,
    ("image", "_str", "must be a non-empty string"): DIAGNOSIS,
    ("image", "_build_args", "'build_args' must be a mapping of name to value"): DIAGNOSIS,
    ("image", "_build_args", "must be a scalar, not"): DIAGNOSIS,

    # --- tasks/site.py: the `site:` section (three products declare one) ------------------------------
    ("site", "declared", "section is missing or is not a mapping - declare the pinned hugo image"):
        DIAGNOSIS,
    # The theme pin, si#47's other half. An unpinned module and a version QUERY both build a site; what
    # they build depends on the day. The kernel's own site pins its theme through this same code, so the
    # rule holds the kernel with the product.
    ("site", "_pinned_theme", "'theme' must pin a version"): EXPRESSION,
    ("site", "_pinned_theme", "which is a query rather than a version"): EXPRESSION,
    # The malformed halves: nothing before the '@', nothing after it.
    ("site", "_pinned_theme", "names no module before the '@'"): DIAGNOSIS,
    ("site", "_pinned_theme", "pins an empty version"): DIAGNOSIS,
    ("site", "_str", "is required"): DIAGNOSIS,
    ("site", "_str", "must be a non-empty string"): DIAGNOSIS,

    # --- workflowgen: the `workflows:` section (simplon's own manifest declares one) -------------------
    ("workflowgen", "parse", "so there is nothing to generate"): DIAGNOSIS,
    ("workflowgen", "parse", "must be a non-empty mapping of workflow name"): DIAGNOSIS,
    ("workflowgen", "_workflow", "must be a mapping, not {type(body)"): DIAGNOSIS,
    # An empty `handwritten:` would generate nothing and work. The kernel demands the SENTENCE, which is
    # the same call as `missing help` on a command - and made in the same place, over a merged surface
    # the kernel's own manifest goes through.
    ("workflowgen", "_workflow", "`handwritten:` must say why"): EXPRESSION,
    # GitHub itself requires a trigger and a runner: a file without either is not a workflow that runs
    # differently, it is a file that never runs.
    ("workflowgen", "_workflow", "declares no `on:` trigger"): DIAGNOSIS,
    ("workflowgen", "_workflow", "`jobs:` must be a non-empty mapping"): DIAGNOSIS,
    ("workflowgen", "_workflow", "so it cannot also declare"): DIAGNOSIS,
    ("workflowgen", "_job", "must be a mapping, not {type(spec)"): DIAGNOSIS,
    ("workflowgen", "_job", "declares no `runs-on:`"): DIAGNOSIS,
    ("workflowgen", "_job", "`steps:` must be a non-empty list"): DIAGNOSIS,
    ("workflowgen", "_job", "`checkout:` is true or false"): DIAGNOSIS,
    ("workflowgen", "_step", "must be a mapping, not {type(item)"): DIAGNOSIS,
    ("workflowgen", "_step", "declares neither `command:` nor a verbatim"): DIAGNOSIS,
    ("workflowgen", "_step", "a verbatim step needs `uses:` or `run:`"): DIAGNOSIS,
    ("workflowgen", "_step", "already gives this step its body"): DIAGNOSIS,
    ("workflowgen", "_declared_trigger", "declares the trigger twice"): DIAGNOSIS,
    ("workflowgen", "_check_path", "must be relative to the product root"): DIAGNOSIS,
    ("workflowgen", "_check_path", "must be under '{DIRECTORY}/'"): DIAGNOSIS,
    ("workflowgen", "_check_path", "must end in .yml or .yaml"): DIAGNOSIS,
    ("workflowgen", "_reject_duplicate_paths", "one file has one owner"): DIAGNOSIS,
}

#: For each EXPRESSION rule only, the third kind `CLAUDE.md` names: how far the rule reaches.
REACH: dict[tuple[str, str, str], str] = {
    ("manifest", "_single_dashed_letter", "must be a single dash plus one letter"): REACH_MERGED,
    ("manifest", "_validate_taxonomy", "impl and depends_on are mutually exclusive"): REACH_MERGED,
    ("manifest", "_validate_taxonomy", "missing help"): REACH_MERGED,
    ("manifest", "_validate_taxonomy", "disagree on stop_on_f"): REACH_MERGED,
    ("manifest", "_enforce_the_catalogue_owns_the_groups", "may not declare `taxonomy:`"): REACH_SEAM,
    ("manifest", "_enforce_the_catalogue_owns_the_groups", "names a group the catalogue's `groups:` does not declare"):
        REACH_SEAM,
    ("treeform", "merge", "names a group the platform's tree does not declare"): REACH_SEAM,
    ("treeform", "merge", "shape_is_the_platforms"): REACH_SEAM,
    ("treeform", "_merge_commands", "is declared as one kind of command and refined as another"): REACH_MERGED,
    ("treeform", "_merge_commands", "redeclares `task:`"): REACH_MERGED,
    ("treeform", "_resolve_one", "declares `impl:`"): REACH_MERGED,
    ("treeform", "_resolve_one", "declares both `task:` and `depends_on:`"): REACH_MERGED,
    ("treeform", "check_no_old_form", "is written in the flat command form"): REACH_SEAM,
    ("treeform", "check_coordinate_placement", "places the coordinate"): REACH_MERGED,
    ("treeform", "check_env_groups", "shape_is_the_platforms"): REACH_SEAM,
    # The `suites:` section is not part of the merged tree at all - it is product data end to end - so
    # "the kernel too" is a real statement here rather than an empty one: a kernel manifest declaring
    # `suites:` goes through the same `declared()` with no exemption path.
    ("testrun", "declared", "at most one gate may declare args: true"): REACH_MERGED,
    # The six modules si#53 brought into the population. All REACH_MERGED, and none of it is a coincidence
    # of wording: each of these sections is product-owned data the kernel reads through the SAME function
    # for its own manifest - simplon declares `site:` and `workflows:` and goes through `site.declared`,
    # `docker.pinned_image` and `workflowgen.parse` with no exemption path. si#47 is the precedent that
    # settled the pin case by making the kernel pin its own images rather than keeping the rule for
    # products.
    ("docker", "pinned_image", "must pin a version ('<image>:<tag>')"): REACH_MERGED,
    ("docker", "pinned_image", "not the moving tag 'latest'"): REACH_MERGED,
    ("nexusproxy", "declared", "content_probe_path' must be a CONTENT path"): REACH_MERGED,
    ("site", "_pinned_theme", "'theme' must pin a version"): REACH_MERGED,
    ("site", "_pinned_theme", "which is a query rather than a version"): REACH_MERGED,
    ("workflowgen", "_workflow", "`handwritten:` must say why"): REACH_MERGED,
}


# --- reading the refusals out of the source --------------------------------------------------------------
#
# A small call-graph walk, and small on purpose. It follows exactly three kinds of edge, each of which is
# a thing this kernel actually does on the way from a manifest to a decision:
#
#   - `helper(...)`            a module-local function
#   - `treeform.merge(...)`    a function in another simplon module, resolved through this module's imports
#   - `_ManifestModel(...)`    a Pydantic model's own validators, which pydantic calls and no call
#                              expression names - without this edge the loader's own rules are invisible
#
# It follows no dynamic dispatch and no callable passed as a value, and it does not need to: measured
# against the hand-made population it replaces, it reproduces `treeform.py` exactly (22) and `manifest.py`
# exactly (33 once the funnel is dropped), and `testrun.declared`'s closure is exactly the sixteen si#61
# counted by hand. Three independent agreements with a number somebody else measured is what makes this a
# derivation rather than a guess.


class _Module:
    """One kernel module's syntax tree, indexed by what the walk asks it: functions, classes, imports."""

    def __init__(self, dotted: str) -> None:
        self.dotted = dotted
        self.path = _module_file(dotted)
        if self.path is None:
            raise ValueError(f"no such kernel module: {dotted} - the walk is broken, not the kernel")
        source = self.path.read_text(encoding="utf-8")
        if not source.strip():
            raise ValueError(f"{self.path} is empty")
        self.tree = ast.parse(source)
        self.funcs: dict[str, list[ast.AST]] = {}
        self.classes: dict[str, ast.ClassDef] = {}
        self._index(self.tree)
        self.imports = self._imports()

    def _index(self, node) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                self.classes[child.name] = child
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.funcs.setdefault(child.name, []).append(child)
            self._index(child)

    def _imports(self) -> dict[str, str]:
        """alias -> simplon-relative module, for the `module.function` edge."""
        out: dict[str, str] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("simplon"):
                base = node.module[len("simplon."):] if node.module != "simplon" else ""
                for alias in node.names:
                    dotted = f"{base}.{alias.name}" if base else alias.name
                    if _module_file(dotted):
                        out[alias.asname or alias.name] = dotted
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("simplon."):
                        dotted = alias.name[len("simplon."):]
                        if _module_file(dotted):
                            out[alias.asname or alias.name.split(".")[-1]] = dotted
        return out

    def is_model(self, name: str) -> bool:
        klass = self.classes.get(name)
        return klass is not None and any(getattr(base, "id", "") == "BaseModel" for base in klass.bases)


def _module_file(dotted: str):
    candidate = SRC.joinpath(*dotted.split("."))
    for path in (candidate.with_suffix(".py"), candidate / "__init__.py"):
        if path.exists():
            return path
    return None


def _dotted_of(path) -> str:
    parts = list(path.relative_to(SRC).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


@functools.lru_cache(maxsize=None)
def _module(dotted: str) -> _Module:
    return _Module(dotted)


def _kernel_modules() -> list[str]:
    return sorted(_dotted_of(path) for path in SRC.rglob("*.py"))


@functools.lru_cache(maxsize=None)
def _document_entries() -> tuple[tuple[str, str], ...]:
    """Every function the kernel hands the manifest DOCUMENT to, read off the call sites.

    `declared(ctx.manifest_data(), ...)` names `declared` as an entry point without anybody saying so.
    A module that reads the document inline instead - `ctx.manifest_data().get(SECTION)` - has no such
    function and is answered by `_inline_readers` below, not here.
    """
    found: set[tuple[str, str]] = set()
    for dotted in _kernel_modules():
        module = _module(dotted)
        for node in ast.walk(module.tree):
            if not isinstance(node, ast.Call):
                continue
            handed = [*node.args, *(kw.value for kw in node.keywords)]
            if not any(isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute)
                       and arg.func.attr == DOCUMENT_ACCESSOR for arg in handed):
                continue
            called = node.func
            if isinstance(called, ast.Name):
                found.add((dotted, called.id))
            elif isinstance(called, ast.Attribute) and isinstance(called.value, ast.Name):
                target = module.imports.get(called.value.id)
                if target:
                    found.add((target, called.attr))
    if not found:
        raise ValueError(f"no function is handed {DOCUMENT_ACCESSOR}() - the walk is broken, not the kernel")
    return tuple(sorted(found))


@functools.lru_cache(maxsize=None)
def _inline_readers() -> tuple[str, ...]:
    """Modules that touch the manifest document without handing it to a function of their own."""
    covered = {dotted for dotted, _ in _document_entries()}
    out: set[str] = set()
    for dotted in _kernel_modules():
        module = _module(dotted)
        reads = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == DOCUMENT_ACCESSOR for node in ast.walk(module.tree))
        if not reads or dotted in covered:
            continue
        # A module may FETCH the document and hand it straight to somebody else's function
        # (`tasks/workflows.py` -> `workflowgen.parse`); that one is covered by the callee, not here.
        hands_off = False
        for node in ast.walk(module.tree):
            if not isinstance(node, ast.Call):
                continue
            handed = [*node.args, *(kw.value for kw in node.keywords)]
            if any(isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute)
                   and arg.func.attr == DOCUMENT_ACCESSOR for arg in handed):
                hands_off = True
        if not hands_off:
            out.add(dotted)
    return tuple(sorted(out))


def _closure(entries):
    """Every function body reachable from `entries`, as (module, FunctionDef)."""
    seen: set[tuple[str, str]] = set()
    bodies: list[tuple[str, ast.AST]] = []
    queue = list(entries)
    while queue:
        dotted, name = queue.pop()
        if (dotted, name) in seen:
            continue
        seen.add((dotted, name))
        module = _module(dotted)
        for function in module.funcs.get(name, []):
            bodies.append((dotted, function))
            for call in ast.walk(function):
                if not isinstance(call, ast.Call):
                    continue
                called = call.func
                model = None
                if isinstance(called, ast.Name):
                    if called.id in module.funcs:
                        queue.append((dotted, called.id))
                    if module.is_model(called.id):
                        model = called.id
                elif isinstance(called, ast.Attribute) and isinstance(called.value, ast.Name):
                    target = module.imports.get(called.value.id)
                    if target:
                        queue.append((target, called.attr))
                    elif module.is_model(called.value.id):
                        model = called.value.id
                if model:
                    bodies.extend(_validators(module, model, seen))
    return bodies


def _validators(module: _Module, name: str, seen: set) -> list[tuple[str, ast.AST]]:
    """A Pydantic model's validator methods, and those of every model its own fields name.

    Pydantic calls these; no call expression in the source names them. Without this edge the loader's own
    rules - `_validate_taxonomy` and the rest, which are most of the census - would be invisible to a walk
    that only follows calls, and the population would silently shrink to a third of itself.
    """
    out: list[tuple[str, ast.AST]] = []
    stack = [name]
    while stack:
        current = stack.pop()
        if (module.dotted, "#" + current) in seen or current not in module.classes:
            continue
        seen.add((module.dotted, "#" + current))
        klass = module.classes[current]
        for node in ast.walk(klass):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and any("validator" in ast.unparse(deco) for deco in node.decorator_list)):
                out.append((module.dotted, node))
            if isinstance(node, ast.AnnAssign) and node.annotation is not None:
                for inner in ast.walk(node.annotation):
                    named = (inner.id if isinstance(inner, ast.Name)
                             else inner.value if isinstance(inner, ast.Constant)
                             and isinstance(inner.value, str) else None)
                    if isinstance(named, str) and module.is_model(named):
                        stack.append(named)
    return out


def _with_nested(function):
    """A function and every function DEFINED inside it. `_validate_taxonomy` holds the cycle check as a
    nested `walk`, and a refusal belongs to the function that writes it rather than to whatever encloses
    that one - otherwise a census key would have to name an outer function it is not in."""
    out = [function]
    for node in ast.walk(function):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node is not function:
            out.append(node)
    return out


def _own_raises(function):
    """The ValueError raises written in THIS function, not in one nested inside it."""
    nested = {id(node) for outer in _with_nested(function)[1:] for node in ast.walk(outer)}
    for node in ast.walk(function):
        if id(node) in nested:
            continue
        if (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
                and getattr(node.exc.func, "id", None) == "ValueError" and node.exc.args):
            yield ast.unparse(node.exc.args[0])


def _raise_sites(bodies) -> list[tuple[str, str, str]]:
    """(module file stem, the function that writes the refusal, the source of its message)."""
    found: list[tuple[str, str, str]] = []
    for dotted, function in bodies:
        for inner in _with_nested(function):
            for message in _own_raises(inner):
                found.append((dotted.rsplit(".", 1)[-1], inner.name, message))
    return list(dict.fromkeys(found))


@functools.lru_cache(maxsize=None)
def _all_refusals() -> tuple[tuple[str, str, str], ...]:
    """The whole population, as (module file stem, enclosing function, the source of its message)."""
    found = [site for site in _raise_sites(_closure([LOADER_ENTRY, *_document_entries()]))
             if FUNNEL not in site[2]]
    if not found:
        raise ValueError("the walk found no refusals at all - it is broken, not the kernel")
    return tuple(found)


def _per_module() -> dict[str, int]:
    counts: dict[str, int] = {}
    for module, _, _ in _all_refusals():
        counts[module] = counts.get(module, 0) + 1
    return counts


def _matches(key: tuple[str, str, str]) -> list[tuple[str, str, str]]:
    """The refusals one census key names. Exactly one is the contract; the tests below hold it."""
    module, function, fragment = key
    return [site for site in _all_refusals()
            if site[0] == module and site[1] == function and fragment in site[2]]


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


def test_the_walk_finds_refusals_at_both_seams():
    """The one that has to fail first. Every count below is computed from this walk, so a walk that found
    nothing - a renamed module, an `ast` change, a refactor to a different raise shape - must be a red
    suite rather than a census of zero things classified perfectly.

    Named per SEAM as well as per module, because a total that looks healthy is exactly how the third
    module went missing in si#61.
    """
    # act
    per_module = _per_module()

    # assert: the loader seam refuses in both its modules
    assert per_module["manifest"] > 0
    assert per_module["treeform"] > 0

    # assert: and so does the document seam - `testrun` is si#61's module, and it is no longer the only
    # one the walk finds there, which is this change's own finding
    assert per_module["testrun"] > 0
    assert len(_document_entries()) > 1
    assert len(per_module) > 3

    # assert: nothing is counted in no module
    assert sum(per_module.values()) == len(_all_refusals())


def test_every_module_that_reads_the_manifest_is_accounted_for():
    """ACCEPTANCE 3 of si#53, and the assurance the whole population change exists for.

    si#61's finding was not that one module was missing. It was that NOTHING WOULD HAVE NOTICED. A
    manifest reader could join the kernel, refuse a product's manifest, and the census would keep
    publishing a total that did not include it - a mechanism whose only job is that the sum cannot grow
    quietly, growing quietly.

    So: every module that touches the manifest document is either walked (its refusals are in the
    population, and `test_every_load_time_refusal_is_classified` then demands a kind for each) or named in
    `READS_INLINE` with the reason the walk cannot follow it. A new one is neither, and this goes red.
    """
    # arrange: every module that touches the document at all, computed
    touching = {dotted for dotted in _kernel_modules()
                if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                       and node.func.attr == DOCUMENT_ACCESSOR
                       for node in ast.walk(_module(dotted).tree))}

    # act: the modules whose refusals the walk actually collects, and the ones left over
    walked = {dotted for dotted, _ in _document_entries()}
    unaccounted = sorted(module for module in _inline_readers() if module not in READS_INLINE)

    # assert
    assert unaccounted == [], (
        "a module reads the manifest document and is in neither half of the census. Either hand the "
        "document to a function of its own - then the walk finds its refusals and they need a kind - or "
        "say in READS_INLINE why it cannot be walked. This is the check si#61 asked for: a manifest "
        f"reader must not be able to join quietly. {unaccounted}")

    # assert: and it ruled on something rather than on an empty set - a walk that found no reader at all
    # would satisfy the line above perfectly
    assert len(walked) > 1
    assert len(touching) > len(READS_INLINE)

    # assert: the declared half stays true too. A module that stops reading the manifest and keeps its
    # entry here would leave READS_INLINE describing something that no longer exists - the second-source
    # drift this repository pins everywhere else.
    assert set(READS_INLINE) <= touching, (
        f"READS_INLINE names a module that no longer reads the manifest: "
        f"{sorted(set(READS_INLINE) - touching)}")


def test_the_only_excluded_raise_is_the_funnel_that_re_raises_the_model():
    """The population's edge, seen rather than asserted.

    One raise inside the walk's reach is dropped: `raise ValueError(_validation_message(exc))`, which
    re-raises what `_ManifestModel` already raised. Every rule it carries is counted at its own site, so
    counting it again would double one refusal and only one.

    The `NOT_LOAD_TIME` class list that used to sit beside it is GONE and that is the point of the new
    walk: `Manifest`, `PlanNode` and `Suites` have methods that raise, and they are simply not reachable
    from either seam, so nothing has to remember to exclude them.
    """
    # arrange: the walk with nothing dropped
    everything = _raise_sites(_closure([LOADER_ENTRY, *_document_entries()]))

    # act
    dropped = [site for site in everything if site not in _all_refusals()]

    # assert: exactly one, and it is the funnel
    assert len(dropped) == 1, f"the walk drops {len(dropped)} raises, not the one funnel: {dropped}"
    assert FUNNEL in dropped[0][2]

    # assert: and the classes that used to need a list really are out of reach on their own
    reachable = {(module, function) for module, function, _ in _all_refusals()}
    for method in ("gate", "plan_for", "spec_for"):
        assert not [pair for pair in reachable if pair[1] == method], (
            f"'{method}' is a method on an already-loaded manifest and the walk reached it")



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
