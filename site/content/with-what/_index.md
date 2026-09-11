---
title: "With what"
weight: 4
cascade:
  type: "docs"
---

What you look things up in. The vocabulary the kernel offers and the lists that go with it: the groups a
command can land in, the modules you may import, the sections a manifest may declare, and the rules the
whole thing is designed by.

These pages are meant to be opened at a heading and closed again. The chapters that explain what any of
it is for are [How](../how/), and the command reference at the end of this section is not written at
all: it is read off the assembled application on every build, so it lists what can be typed rather than
what was intended.

{{< cards >}}
  {{< card link="phases/" title="The five phases" subtitle="The corset: build, test, release, deploy, monitor - what flows between them, what the catalogue offers each, and the two ribs that are still empty." >}}
  {{< card link="surface/" title="What you may import" subtitle="The kernel has two public surfaces - tasks by coordinate and modules by import. Which modules are promised, which are its own, and what happens when one moves." >}}
  {{< card link="test-levels/" title="Test levels" subtitle="The `suites:` section: gates in order, clear versus append, attaching a non-pytest runner, and the hook contract." >}}
  {{< card link="environments/" title="Environments" subtitle="Env-first groups, the environment matrix, and why `build` refuses a target." >}}
  {{< card link="rules/" title="The rules" subtitle="Six rules the kernel is built on, each with the mechanism that forces it." >}}
  {{< card link="commands/" title="Command reference" subtitle="Generated from the assembled application on every build." >}}
{{< /cards >}}
