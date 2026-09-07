---
title: "Using Simplon"
weight: 1
cascade:
  type: "docs"
---

This half of the site is for the person who runs a Simplon-assembled command line: what the thing is,
how to get one running, what to type for the jobs that actually come up, and the full list of
commands.

If you are the person who has to *make* one - declare commands, write task bodies, add an environment -
the other half is [Building on Simplon](../building/).

{{< cards >}}
  {{< card link="why/" title="What Simplon is" subtitle="The one sentence the design comes from, taken apart noun by noun - and the three places a hand-written delivery script goes wrong." >}}
  {{< card link="getting-started/" title="Getting started" subtitle="`simplon init`, what it writes, and the first run - line by line." >}}
  {{< card link="examples/" title="Worked examples" subtitle="Eight real jobs, end to end: cutting a release, chasing a red suite, adding a command, deploying to one environment." >}}
  {{< card link="case-python/" title="A Python product, end to end" subtitle="One loop, two real products, all five verbs - and a label on every step saying whether anybody has driven it." >}}
  {{< card link="releasing/" title="Cutting a release" subtitle="One command. Why the tag *is* the version, why it pushes one tag and not all of them, what the guard refuses - and why a push to `main` publishes nothing." >}}
  {{< card link="commands/" title="Command reference" subtitle="Generated from the assembled application on every build." >}}
{{< /cards >}}
