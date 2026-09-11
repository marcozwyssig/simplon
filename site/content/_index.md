---
title: "Simplon"
layout: "hextra-home"
# The two AUDIENCE sections si#170 replaced with the five questions. Neither has an honest successor -
# "Using Simplon" became four of the five - so a bookmark on either lands on the front door, which is
# where the five questions are offered, rather than on a 404.
aliases:
  - "/using/"
  - "/building/"
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
{{< hextra/hero-button text="Start here" link="how/getting-started/" >}}
</div>

{{< hextra/feature-grid >}}
  {{< hextra/feature-card
    title="The manifest is the CLI"
    subtitle="A command is a declaration, not a hand-written argument parser. Add three lines to the manifest and the command exists, with its help, its options and its place in the tree."
    link="how/manifest/"
  >}}
  {{< hextra/feature-card
    title="Tasks that travel"
    subtitle="The kernel carries the mechanism - render docs, run a suite, push a stack - and the product supplies the data. A capability written once is available to every product that imports its namespace."
    link="how/tasks/"
  >}}
  {{< hextra/feature-card
    title="A reference that cannot go stale"
    subtitle="The command reference on this site is read off the assembled application during the build. It lists what can be typed, not what was intended."
    link="with-what/commands/"
  >}}
  {{< hextra/feature-card
    title="Rules you can check"
    subtitle="Six design rules, each with the mechanism that forces it and a way to find out in ten minutes whether your own code has the same shape."
    link="with-what/rules/"
  >}}
  {{< hextra/feature-card
    title="Environment-first where it matters"
    subtitle="Deploying and monitoring take a target environment as the outer token; building and testing refuse one. The distinction is declared once and enforced by the assembly."
    link="with-what/environments/"
  >}}
  {{< hextra/feature-card
    title="Nothing to vendor"
    subtitle="The kernel is an ordinary PyPI dependency. A fresh clone plus the generated launcher is the whole setup: it provisions its own virtual environment and installs the pinned kernel."
    link="how/getting-started/"
  >}}
{{< /hextra/feature-grid >}}
