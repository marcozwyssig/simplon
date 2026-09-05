---
title: "Building on Simplon"
weight: 2
cascade:
  type: "docs"
---

This half is for the person who builds a product on the kernel: the manifest's shape, how a task's body
is written and where it lives, how environments are declared and gated, and the rules the kernel is
designed by.

If you only need to *run* the resulting command line, start with [Using Simplon](../using/).

{{< cards >}}
  {{< card link="manifest/" title="The manifest" subtitle="The command tree, `task:`, and the colon that tells a local body from a catalogue coordinate." >}}
  {{< card link="tasks/" title="Writing a task" subtitle="A body is a plain function. Where it goes, what it may assume, and how it reaches product data." >}}
  {{< card link="environments/" title="Environments" subtitle="Env-first groups, the environment matrix, and why `build` refuses a target." >}}
  {{< card link="rules/" title="The rules" subtitle="Six rules the kernel is built on, each with the defect that forced it." >}}
{{< /cards >}}
