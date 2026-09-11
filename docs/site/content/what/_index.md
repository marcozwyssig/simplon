---
title: "What"
weight: 2
cascade:
  type: "docs"
---

What it looks like when it is running, shown rather than described. Every chapter here is a real product
or a real job driven end to end, with the commands that were typed and the output they produced.

The case studies are the same delivery loop in four languages, and they are deliberately repetitive: the
point is that the loop does not change when the technology does. Each step carries a label saying
whether anybody has actually driven it, so the chapters can be read as evidence and not as a promise.
What any of it *means* is [How](../how/); what a value is called is [With what](../with-what/).

{{< cards >}}
  {{< card link="examples/" title="Worked examples" subtitle="Eight real jobs, end to end: cutting a release, chasing a red suite, adding a command, deploying to one environment." >}}
  {{< card link="case-python/" title="A Python product, end to end" subtitle="One loop, two real products, all five verbs - and a label on every step saying whether anybody has driven it." >}}
  {{< card link="case-java/" title="A Java product, end to end" subtitle="The same loop with no Python in the product at all: Gradle in Docker, JUnit XML in the Allure report, and a label on every step." >}}
  {{< card link="case-cpp/" title="A C++ product, end to end" subtitle="The same loop again with no task body at all: four commands, one coordinate, one pinned clang image - and the four steps between that promise and a product that can use it." >}}
  {{< card link="case-dotnet/" title="A .NET product, end to end" subtitle="The same loop again, with no task body for the build at all: one pinned SDK image, the kernel's own argv - and the four places that path does not reach yet." >}}
  {{< card link="handing-a-package-over/" title="Handing a package over" subtitle="Publishing a NuGet library so a second product resolves it - and why the Conan half is a transport rather than a remote, with the measurement that settles it." >}}
{{< /cards >}}
