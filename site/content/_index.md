---
title: "Simplon"
layout: "hextra-home"
---

{{< hextra/hero-badge >}}
  <div class="hx:w-2 hx:h-2 hx:rounded-full hx:bg-primary-400"></div>
  <span>MIT licensed &middot; on PyPI</span>
{{< /hextra/hero-badge >}}

<div class="hx:mt-6 hx:mb-6">
{{< hextra/hero-headline >}}
  One manifest,&nbsp;<br class="hx:sm:block hx:hidden" />a whole delivery CLI
{{< /hextra/hero-headline >}}
</div>

<div class="hx:mb-12">
{{< hextra/hero-subtitle >}}
  Simplon is the link between the CI/CD process and the technologies, and it brings structure and
  reusability. Concretely: it assembles a product's
  build&nbsp;/&nbsp;test&nbsp;/&nbsp;release&nbsp;/&nbsp;deploy&nbsp;/&nbsp;monitor command line out of
  one YAML file, runs the steps, and knows nothing about the product itself.
{{< /hextra/hero-subtitle >}}
</div>

<div class="hx:mb-6">
{{< hextra/hero-button text="Start here" link="using/getting-started/" >}}
</div>

{{< hextra/feature-grid >}}
  {{< hextra/feature-card
    title="The manifest is the CLI"
    subtitle="A command is a declaration, not a hand-written argument parser. Add three lines to the manifest and the command exists, with its help, its options and its place in the tree."
    link="building/manifest/"
  >}}
  {{< hextra/feature-card
    title="Tasks that travel"
    subtitle="The kernel carries the mechanism - render docs, run a suite, push a stack - and the product supplies the data. A capability written once is available to every product that imports its namespace."
    link="building/tasks/"
  >}}
  {{< hextra/feature-card
    title="A reference that cannot go stale"
    subtitle="The command reference on this site is read off the assembled application during the build. It lists what can be typed, not what was intended."
    link="using/commands/"
  >}}
  {{< hextra/feature-card
    title="Rules with receipts"
    subtitle="Six design rules, each with the defect that forced it - the uid that broke a render, the collision that resolved silently, the group that promised commands it did not have."
    link="building/rules/"
  >}}
  {{< hextra/feature-card
    title="Environment-first where it matters"
    subtitle="Deploying and monitoring take a target environment as the outer token; building and testing refuse one. The distinction is declared once and enforced by the assembly."
    link="building/environments/"
  >}}
  {{< hextra/feature-card
    title="Nothing to vendor"
    subtitle="The kernel is an ordinary PyPI dependency. A fresh clone plus the generated launcher is the whole setup: it provisions its own virtual environment and installs the pinned kernel."
    link="using/getting-started/"
  >}}
{{< /hextra/feature-grid >}}
