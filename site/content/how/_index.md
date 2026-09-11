---
title: "How"
weight: 3
cascade:
  type: "docs"
---

How you work with it: getting a command line into existence, the two words the whole model rests on,
the file that declares it, where a task body lives, and how a version goes out.

This section is wider than installation on purpose. A chapter that explains how the loader reads your
manifest is not a reference entry, and calling it one would be a lie about what the page does - so
everything that EXPLAINS is here, and [With what](../with-what/) keeps only what you look a value up in.

{{< cards >}}
  {{< card link="getting-started/" title="Getting started" subtitle="`simplon init`, what it writes, and the first run - line by line." >}}
  {{< card link="task-and-command/" title="Task and command" subtitle="A template and a placement of it. Which keys belong to which, and the five things the loader refuses." >}}
  {{< card link="manifest/" title="The manifest" subtitle="The command tree, the group lock, pinning with `with:`, aggregates and the product data sections." >}}
  {{< card link="tasks/" title="Writing a task" subtitle="A body is a plain function. Where it goes, what it may assume, and how it reaches product data." >}}
  {{< card link="releasing/" title="Cutting a release" subtitle="One command. Why the tag *is* the version, why it pushes one tag and not all of them, what the guard refuses - and why a push to `main` publishes nothing." >}}
{{< /cards >}}
