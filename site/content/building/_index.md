---
title: "Building on Simplon"
weight: 2
cascade:
  type: "docs"
---

This half is for the person who builds a product on the kernel: the two words the whole model rests on,
the manifest's shape, how a task's body is written and where it lives, how a product declares its test
levels, how environments are declared and gated, and the rules the kernel is designed by.

If you only need to *run* the resulting command line, start with [Using Simplon](../using/).

{{< cards >}}
  {{< card link="task-and-command/" title="Task and command" subtitle="A template and a placement of it. Which keys belong to which, and the five things the loader refuses." >}}
  {{< card link="manifest/" title="The manifest" subtitle="The command tree, the group lock, pinning with `with:`, aggregates and the product data sections." >}}
  {{< card link="tasks/" title="Writing a task" subtitle="A body is a plain function. Where it goes, what it may assume, and how it reaches product data." >}}
  {{< card link="test-levels/" title="Test levels" subtitle="The `suites:` section: gates in order, clear versus append, attaching a non-pytest runner, and the hook contract." >}}
  {{< card link="environments/" title="Environments" subtitle="Env-first groups, the environment matrix, and why `build` refuses a target." >}}
  {{< card link="rules/" title="The rules" subtitle="Six rules the kernel is built on, each with the mechanism that forces it." >}}
{{< /cards >}}
