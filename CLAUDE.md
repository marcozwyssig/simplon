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
on its own, and nobody ever measures the sum. As of 2026-09-06 the kernel
carries **61 load-time refusals**, 23 of them in `treeform.py` alone. Every
one had a measured cause; the total was never weighed. See #48.

## Three kinds of refusal — only one costs flexibility

Do not lump these together. Before adding a refusal, say which kind it is.

1. **Diagnosis.** A manifest is broken and the message says where. Costs
   nothing — without it the failure would be silent. *Example:* a coordinate
   the catalogue does not carry.
2. **Self-binding.** The kernel subjects itself to a rule it imposes. Costs a
   product nothing. *Examples:* #34 checks over the **merged** tree and so
   holds the catalogue's own placements; #47 removes the kernel's exemption
   from the image pin.
3. **Expression rule.** A product may no longer say something it could have
   said. **Only this kind costs flexibility.** *Examples:* #34 (a phase name
   in a coordinate is the placement), #43 (`env_groups` may not contradict the
   platform), #33 (one manifest form instead of two).

## Before building an expression rule, answer these

- **Does it forbid something a product might legitimately want?** If so,
  which product, and what does it do instead? #34 could show *zero violations
  across both existing manifests* — that is the bar.
- **Is it diagnosis or expression rule?** Diagnosis needs no such
  justification.
- **Would deleting be cheaper than guarding?** A second source you do not
  have cannot drift, and it needs no rule to watch it. First applied in #46.

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
