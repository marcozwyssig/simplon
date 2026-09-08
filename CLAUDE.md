# Simplon — working agreements

## The four quality goals

Simplon exists to give a delivery pipeline **clear structure**,
**extensibility** and **reusability**, and to be **usable** while it does it.
Those four are the point. Everything else — every rule, every refusal, every
check — is a means, and a means that costs more flexibility than it buys is a
bad one.

**Usable** is the newest of the four and the easiest to lose, because nothing
fails when it is missing. Three questions a run should answer without being
asked: *which phase are we in*, *what is happening in it*, and *what went
wrong*. Measured against those, a run that reports how many steps failed but
not why (#49), or a tree with no durations (#52), is not a small omission —
it is the tool declining to say what it already knows.

**Guard against rule creep.** Rules are easy to add, each one looks justified
on its own, and nobody ever measures the sum. Every refusal had a measured
cause; the total was never weighed. It is weighed now — see #48.

**Do not restate the count here.** si#48 found that the `grep`-level number
this paragraph used to carry (61) was the wrong population: six of those
raises run at plan or run time, or only re-raise. The live count, split by
kind, is computed from the load-path modules' syntax trees by
`tests/test_refusal_census.py` and published on `building/rules.md`. A new
refusal with no census entry turns that suite red until somebody says which
kind it is, which is the point — a number typed into a document instead is
wrong on the first day nobody checks it, and this repository has now proved
that five times, twice in this very file.

**The census only counts what it is pointed at.** si#61 found sixteen
load-time refusals sitting outside it, because the population was a list of
modules and `tasks/testrun.py` was not on it — a census whose whole purpose is
that the sum cannot grow quietly, growing quietly. When you add a refusal in a
module the census does not read, the suite stays green. Check the population,
not only the entry.

## Three kinds of refusal — only one costs flexibility

Do not lump these together. Before adding a refusal, say which kind it is.

1. **Diagnosis.** A manifest is broken and the message says where. Costs
   nothing — without it the failure would be silent. *Example:* a coordinate
   the catalogue does not carry.
2. **Expression rule.** A product may no longer say something it could have
   said, and the manifest it wrote would have produced a working product —
   merely a different one. **Only this kind costs flexibility.** *Examples:*
   #33 (one manifest form instead of two), #34 (a phase name in a coordinate
   is the placement), #43 (`env_groups` may not contradict the platform).

**Self-binding is not a third kind — it is an expression rule's reach.** The
first draft of this file listed it separately and put #34 under both, which is
how the mistake showed. Ask instead how far a rule reaches: does it hold the
kernel's own catalogue too (#34 checks over the *merged* tree, so it does), or
does it exempt the kernel from what it asks of a product? Measured in #48 and
again in #61, and **the split is on `building/rules.md`, not here** — every
count this paragraph used to carry has gone stale, the last two within a day of
being typed. Most expression rules bind the kernel with the product; a few sit
exactly on the platform/product seam; and **none exempts the kernel** any more.
There was one, `check_every_task_is_used`, and si#53 struck it — measuring the
exemption is what ended it. The rule would have refused 14 of the kernel's own
22 catalogue tasks, it was the only expression rule with no measured cause in
ticket, commit or docstring, and over every reachable manifest — this kernel's own
and the five in `surface.CONSUMERS` — it had never refused anything. An exemption is not automatically wrong. An unexamined one is
— and examining this one is what showed there was nothing left to defend.
`test_no_expression_rule_exempts_the_kernel_from_itself` holds the zero.

## Before building an expression rule, answer these

- **Does it forbid something a product might legitimately want?** If so,
  which product, and what does it do instead? #34 showed *zero violations
  across both manifests on this machine* — and #48 later measured all **six**
  real manifests through the GitHub API and found one violation the smaller
  population had hidden. The bar is every manifest you can reach, and you can
  reach them all without a checkout; #37 and #47 had already shown how.
- **Is it diagnosis or expression rule?** Diagnosis needs no such
  justification.
- **Would deleting be cheaper than guarding?** A second source you do not
  have cannot drift, and it needs no rule to watch it. First applied in #46.
- **If a manifest does violate it, what does the fix cost that product?** Not
  the manifest line — the surface. #34 moved netctl's `monitor accept` to
  `test accept`, and its maintainers measured the real bill: the manifest is
  one line, the old command name is in eight comments and docstrings and an
  architecture document, and every user who types it has to learn the new one.
  "One violation" and "one line" are not the same number, and only the product
  can tell you which it is. Ask before shipping, not after.

## The recurring defect this project hunts

**An outcome that cannot tell "nothing to do" from "failed" is a bug.**
Found in more than a dozen distinct places. It is the reason for most of the
checks that do exist, and it is the one class of check that is always worth
its cost, because such a defect is green precisely because nobody looks.

The generalisation, from a consumer: **what meaning does a value carry on the
far side of a seam that it did not carry on this side?** `None` means "no
verdict" to a caller and "failure" to `rc != 0`; `True` means "yes" to a hook
and `1` — failure — to an exit code.

The resolution is always the same: exclude the ambiguous value at the seam,
or widen the range so each meaning gets its own value.

## Working practices

- **Measure, do not assume.** If you state something about behaviour, you ran
  it. Where an assumption is not testable, say so rather than hiding it.
- **See it red.** A new assertion that has never failed is not yet an
  assertion. Break the property it claims to protect and watch it fail.
- **Report findings, do not patch them away.** A defect found against a real
  system is worth more than the quick fix; record it, then decide.
- **A quoted error text is a second source for a string**, not prose. Pin it
  against the real message.
- Commit messages and issue text go through a quoted heredoc or `--body-file`
  — never inline. Backticks in double quotes run as shell substitution.
