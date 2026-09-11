---
title: "When"
weight: 5
cascade:
  type: "docs"
---

What was released when, and what a product has to do about it. One chapter, and it is a record rather
than a chapter that gets rewritten: a section is added when a version goes out and the ones above it are
left alone.

Notes start at 0.4.0 and every section from 0.5.0 on names the number of every ticket merged into that
release, which `./simplon.sh test release-notes` measures against the repository's own merges. So the
page cannot quietly fall behind the tags, and a change cannot go out undescribed.

{{< cards >}}
  {{< card link="releases/" title="Releases" subtitle="Every version from 0.4.0 on: what it changed, why, and what it costs a product already on the previous one." >}}
{{< /cards >}}
