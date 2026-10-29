# The site is simple: six sections, far less text, and a shape every product inherits

Ticket: none yet (Marco, 2026-10-29). Open one before the plan.

## Intent

The documentation site at `marcozwyssig.github.io/simplon/` is structurally sound (Hextra as a module,
generated command reference, Pages deploy) but it does not read as simple. The hero argues instead of
stating, the landing page offers six cards and no install command, the five-question navigation
(Why / What / How / With what / When) asks the reader to decode labels, and the content is ~15,500
lines of essay-style prose where a reader wants a command and a result.

The site also has a second job: it is the TEMPLATE for the sites of Marco's other products. Whatever
shape it ends up with, `simplon init` must be able to write that shape into a fresh product.

## Decided by Marco (2026-10-29)

1. **It must be simple.** Six top-level sections, no more:
   Why, Getting started, Examples, Documentation, Reference, Releases.
2. **Reference and Documentation are different things.** Reference is GENERATED and lists what exists,
   completely, with no prose. Documentation is WRITTEN and explains how something works. A page that
   somebody would edit by hand is Documentation. Test per page: "What is X? / Which options does X
   have?" is Reference; "How do I do Y? / Why is it so?" is Documentation.
3. **Far less text.** Target: under 3,000 lines of Markdown across the site. Every written page opens
   with the command or the example, then at most three short paragraphs.
4. **The site is the template for the other product sites.** The structure, the landing page shape and
   the Pages deploy are produced by `simplon init`, not copied by hand.

## Target structure

```
/                   hero: badge, one-line headline, install command, [Get started] [Why], three cards
/why/               one page: the problem, what Simplon does, what it is not
/getting-started/   one page: the four commands from empty repo to working CLI
/examples/          one page per language: python, java, dotnet, cpp
/docs/              written: manifest, tasks and kinds, environments, phases, releasing, ci-hosts
/reference/         generated: commands, acceptance, manifest schema (new)
/releases/          changelog
```

Navigation in that order, weights 1..6, then Search and GitHub as today. `cascade: type: docs` on
every section except `/`.

### Mapping from today's content

| today | becomes |
|---|---|
| `why/why.md` | `/why/` (one page, cut to about one screen) |
| `why/the-design.md` | dropped from the site, stays in the repo under `docs/` |
| `how/getting-started.md` | `/getting-started/` |
| `how/what-init-wrote.md`, `running.md`, `task-and-command.md`, `manifest.md`, `tasks.md`, `ci-hosts.md`, `releasing.md` | `/docs/`, each cut to example + at most three paragraphs; `what-init-wrote` and `running` fold into `getting-started` or `manifest` where they are short enough |
| `what/case-python.md`, `case-java.md`, `case-dotnet.md`, `case-cpp.md` | `/examples/<lang>/` |
| `what/examples.md`, `one-contract-two-products.md`, `handing-a-package-over.md` | at most one paragraph each inside the relevant example page, otherwise dropped |
| `with-what/commands.md`, `acceptance.md` (generated) | `/reference/` unchanged in mechanism, new output paths |
| `with-what/architecture.md`, `rules.md`, `surface.md`, `test-levels.md` | dropped from the site, stay under `docs/` in the repo |
| `with-what/environments.md`, `kinds.md`, `phases.md` | `/docs/` |
| `when/releases.md` | `/releases/` |

Aliases: every old path gets an `aliases:` entry on its successor, so no bookmark lands on a 404.
Pages dropped from the site alias to the section they would have belonged to.

### Landing page

In this order and nothing else:

- hero badge: "MIT licensed · on PyPI"
- headline: one line, e.g. "One manifest, a whole delivery CLI"
- subtitle: ONE sentence. The current four-line argument moves to `/why/`.
- install command, as a code block: `pip install simplon`
- two buttons: Get started → `/getting-started/`, Why → `/why/`
- three feature cards, each one sentence of subtitle. Candidates: "The manifest is the CLI",
  "A reference that cannot go stale", "Nothing to vendor". The other three cards are dropped.

### Reference

Only generated files live under `/reference/`. A human never edits a file there; the build writes it.

- `commands.md`: from `docs:reference`, output path moves to `src/site/content/reference/commands.md`.
- `acceptance.md`: from `docs:acceptance`, output path moves likewise.
- `manifest.md` (NEW): the manifest schema, derived from the loader (the kinds, phases and fields it
  accepts, with their types and defaults). Same rule as `commands.md`: walked off the objects, not
  parsed from text. If the loader does not expose enough to derive this, say so in the plan and leave
  the page out rather than writing it by hand.

### Text rule

For every written page (`/why/`, `/getting-started/`, `/examples/`, `/docs/`):

- first thing on the page: the command, the manifest snippet or the example output
- then at most three paragraphs, each three or four sentences
- no justification of design decisions; that belongs in `docs/superpowers/` and the Git history
- no HTML comments explaining the page to its editor; the page explains itself or it is wrong

The same rule applies to `hugo.yaml` and `_index.md`: the editorial comments are removed. The seam
between manifest and `hugo.yaml` (baseURL and theme repeated on purpose) keeps ONE short comment.

## The template

`simplon init` writes `src/site/` into a fresh product, with the structure above and empty pages:

- `hugo.yaml`: title from the product name; `baseURL` derived as
  `https://<owner>.github.io/<product>/` from the `origin` remote (the same read `init` already does
  for the product name), overridable in the manifest `site:` section; the six menu entries; the Hextra
  module import. No editorial comments.
- `go.mod` with the module path derived from the remote.
- `content/_index.md`: the landing page skeleton above with placeholders for headline, subtitle, the
  install command and three cards.
- `content/<section>/_index.md` for the six sections, with `cascade: type: docs`.
- `content/getting-started/_index.md`: the four-step skeleton.
- the `docs:reference` and `docs:acceptance` entries in the starter manifest, with output paths under
  `content/reference/`.

The Pages deploy is part of the generated release workflow, as it is today. In addition, a second
deploy runs on every push to `main` that touches `src/site/**`, so a documentation fix reaches the site
without a release. Both deploys publish `build/site`; the push-triggered one skips the tag checks.

A product that already has `src/site/` is not overwritten by `init` unless `--force` is given, as
with the launchers.

## The standard for every product (Marco, 2026-10-29)

The six-section shape is not simplon's choice; it is the kernel's. Every product that has the `docs`
tasks gets the same site shape, the same landing page rule and the same text rule, the way every
product gets the same five verbs.

- The site skeleton is kernel data (a template directory in `src/simplon/`), written by `init` and
  refreshed by `init --force`, exactly like the launchers. A product edits the content, never the shape.
- The six section names and their order are fixed by the kernel. A product that wants a seventh section
  has a reason the kernel should hear; it does not add one locally.
- The landing page rule (badge, headline, one sentence, install block, two buttons, three cards) and the
  text rule (example first, at most three paragraphs) go into the generated central part of `CLAUDE.md`
  (`support claude-md`), so every product's agent works to them without being told.
- `docs:site` checks the shape at build time as a DIAGNOSIS, not an expression rule: a section
  directory missing from the six is reported by name with the fix; an extra one is reported, not
  refused. The check says what is absent; it does not forbid.
- Migration of the existing products (netctl and the others in `surface.CONSUMERS`) is one ticket per
  product after the kernel ships the template: `init --force` for the shape, then the content moved by
  hand under the mapping rule above. Simplon goes first and is the worked example.

## Out of scope

- Rewriting content for voice. This change moves and cuts; it does not write new chapters.
- PDF or any second output format.
- Changing the theme.

## Acceptance

1. The six sections exist with the content mapped as in the table; `hugo` builds with no warnings
   about missing pages.
2. `wc -l` over `src/site/content/**/*.md` is under 3,000.
3. Every old URL redirects (alias) to a page on the new site; a crawl of the old sitemap finds no 404.
4. `/reference/` contains only files written by the build; `git status` after `./simplon.sh build docs`
   shows them unchanged from the committed state (they are committed as a snapshot) or they are
   gitignored, whichever the plan decides and justifies.
5. The landing page has exactly: one badge, one headline, one subtitle sentence, one install block,
   two buttons, three cards.
6. `simplon init myctl --dir .` in an empty repo writes `src/site/` with the structure above, and
   `hugo` builds it to a site with six navigation entries and a home page.
7. A push to `main` touching `src/site/` deploys the site without a release; a release still deploys
   it as before.
8. `./simplon.sh support claude-md` emits the landing page rule and the text rule in the central part.
9. `docs:site` on a product with a section missing names it and the fix; on a product with an extra
   section it reports and still builds (rc 0).
