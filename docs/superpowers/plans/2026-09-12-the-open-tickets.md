# The open tickets, and the order they can be built in

**Written:** 2026-09-12, after v0.12.0.
**Scope:** every open issue except si#5, which is a new subsystem and belongs in a design conversation
rather than in a lane.

## What decides the order

Not subject matter. Two things:

1. **Which files two branches would both rewrite.** Every lane writes a release-notes entry, and that has
   conflicted on every merge for three days - one section has one introduction and four branches each
   wrote one. That is survivable and mechanical. What is not survivable is two branches editing the same
   source module.
2. **Which coordinate space a lane touches.** Declaring a catalogue coordinate turns **nine** counted
   guards red at once, all in shared docs files (the survey is in PR #198's report; my earlier briefs said
   eight). Only one lane at a time may add one.

## The two clusters

### Cluster A: docker-only (si#199's rule)

si#199 is the analysis and the record of the decision - simplon usable as a venv **or** as a container,
one implementation behind two transports. It is not itself a lane.

| ticket | what | depends on |
|---|---|---|
| **si#200** | simplon's own image, built and published outside GHCR | - |
| **si#201** | the launcher's container route | si#200 (needs the image) |
| **si#202** | `test:gate` without a host venv | - |
| **si#203** | the type gate without a host venv | - |

si#202 and si#203 are **one lane**, not two. Both stand behind the same wall si#121 measured - no
prebuilt image can carry a product's wheels - and answering it twice is how two answers appear.

si#201 carries the risk of the whole cluster: a container that runs containers passes HOST paths to the
daemon. Measure that before building anything else in it.

### Cluster B: acceptance (si#197's split)

si#197 is the analysis; si#204, si#205 and si#206 are the lanes, and they are **strictly sequential**.

| ticket | what | depends on |
|---|---|---|
| **si#204** | the generated document of every acceptance test | - |
| **si#205** | a person walks the steps; resume; selection | si#204 (built against its format) |
| **si#206** | a refused step becomes a bug ticket, once | si#205 |

The maintainer's decisions, already taken: somebody sits with the customer and drives the Textual runner
(no browser artefact, no checkout at the customer); tickets are opened by the manual mode only; the
document comes first.

PR #198's measurement is the input to all three, and one of its findings is a requirement on the product
rather than on the kernel: **without `allure-pytest-bdd`, an Allure result carries `steps: []`**, so the
per-step evidence the manual half must produce does not exist on the automatic side either and the two
modes are not comparable at all.

### Independent

**si#193** - `sha256_of` meets a byte-range lock on Windows. The cause is measured and handed over by the
product that hit it; the retry schedule is explicitly not. Small, touches `checksum.py` only.

## What can run at once, now

Four lanes, disjoint in their source files:

- **si#200** - `simplon.yaml`'s `images:` section, a Dockerfile, `tasks/image.py`.
- **si#202 + si#203** - `tasks/testrun.py`, `tasks/typecheck.py`, `pyvenv.py`, `tasks/profiles.py`.
- **si#204** - a new `docs:` coordinate and its renderer. **Owns the coordinate space**; nothing else may
  add one while it runs.
- **si#193** - `checksum.py`.

Then, in order: si#201 after si#200. si#205 after si#204. si#206 after si#205.

## What every lane owes, regardless of subject

These are not ceremony; each was paid for by a defect in the last three releases.

- **Measure before designing.** Three tickets in a row had their central premise killed by a count -
  si#159's unread-key population was zero, si#172's silent loser was loud, si#192's "the runner owns
  `==>`" was `log.info`. State the measurement before the design.
- **Drive the artefact, not the argv.** `file` says shared or static, `nm` says symbols, the archive says
  what shipped. A string assertion over generated text is how 0.8.0 shipped undriveable.
- **See it red.** Break the property and confirm. Five checks that could not fail were found across 0.11.0
  and 0.12.0, two of them inside the very diff that was fixing another.
- **A feature that breaks a principle is declined, with the collision written down** - not bent around.
  si#192 ended that way this week and the requester agreed it was the better answer.
- **Add the release-notes entry.** The gate refuses an unnamed merged ticket, and creating a new version
  section arms it for everything since the tag.

## What is deliberately not planned

**si#5**, deployment providers per environment. It is a new subsystem, the largest thing open, and the
only `does not exist yet` row left in the Java chapter. It needs a design conversation with the
maintainer before it can be a plan.
