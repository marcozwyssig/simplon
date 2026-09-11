---
title: "Building on Simplon"
weight: 2
cascade:
  type: "docs"
---

This half is for the person who builds a product on the kernel: the two words the whole model rests on,
the five phases of the loop and the group beside them, the manifest's shape, how a task's body is written
and where it lives, which of the kernel's own modules you may import, how a product declares its test levels, how environments are declared and gated, and
the rules the kernel is designed by.

If you only need to *run* the resulting command line, start with [Using Simplon](../using/).

{{< cards >}}
  {{< card link="task-and-command/" title="Task and command" subtitle="A template and a placement of it. Which keys belong to which, and the five things the loader refuses." >}}
  {{< card link="phases/" title="The five phases" subtitle="The corset: build, test, release, deploy, monitor - what flows between them, what the catalogue offers each, and the two ribs that are still empty." >}}
  {{< card link="manifest/" title="The manifest" subtitle="The command tree, the group lock, pinning with `with:`, aggregates and the product data sections." >}}
  {{< card link="tasks/" title="Writing a task" subtitle="A body is a plain function. Where it goes, what it may assume, and how it reaches product data." >}}
  {{< card link="surface/" title="What you may import" subtitle="The kernel has two public surfaces - tasks by coordinate and modules by import. Which modules are promised, which are its own, and what happens when one moves." >}}
  {{< card link="test-levels/" title="Test levels" subtitle="The `suites:` section: gates in order, clear versus append, attaching a non-pytest runner, and the hook contract." >}}
  {{< card link="environments/" title="Environments" subtitle="Env-first groups, the environment matrix, and why `build` refuses a target." >}}
  {{< card link="rules/" title="The rules" subtitle="Six rules the kernel is built on, each with the mechanism that forces it." >}}
{{< /cards >}}
