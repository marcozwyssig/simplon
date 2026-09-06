---
title: "Task and command"
weight: 1
---

Two words that sound like synonyms and are not, and almost everything in the manifest follows from the
difference. Read this chapter first: the rest of this half of the site assumes it.

> A **task** is a template. It carries the body.
> A **command** is an instance of one. It carries the name, the group, and the values pinned for this
> particular placement.

Nothing else in the model is allowed to blur that. A body is declared once, in one place; a name in the
command tree is always a placement of something already declared. So "where does this command's code
live" has exactly one answer, and "what happens if I change this body" has a knowable one - it changes
for every placement of it, everywhere.

## The two declarations, side by side

```yaml
tasks:
  wheel:
    impl: "orchestrator.cli:build_wheel"
    help: "Build the wheel."

groups:
  build:
    commands:
      wheel: { task: "wheel" }
```

The `tasks:` entry is the template: a name, a body, and the wording that goes with the body. The
`groups:` entry is the placement: this template, under this group, called this. They are two entries
because they answer two questions, and a product very often wants the same answer to the first one and a
different answer to the second one twice over.

| | **task** | **command** |
|---|---|---|
| answers | *what does this do* | *what is it called, where does it live, with what data* |
| declared under | `tasks:` | `groups: <group>: commands:` |
| how many of the other | any number of commands | exactly one task (or none, if it is an aggregate) |
| may name a body | yes, and must | never |
| may pin a value | never | yes, with `with:` |

## Which keys belong to which

A task takes exactly four keys:

```text
impl   help   passthrough_args   params
```

A command takes those it needs to place a task, plus the ones that describe *this* placement:

```text
task   with   help   params   hidden   keep_awake   stop_on_failure   depends_on   override
```

Two of the task's keys are **inherited** by every command that instantiates it unless the command says
otherwise: `help` and `passthrough_args`. That is the template doing its job - one task documents itself
once, and every placement gets that wording for free while remaining free to override it.

`impl` is not in that list, because it is never the command's to declare. `with` is not in it either, and
the reason is worth stating plainly: **a template that pinned a value would not be a template.** It would
be one particular use of itself, and the second product that wanted the same body with different data
would have to fork it. The same argument covers `hidden`, `keep_awake`, `stop_on_failure` and
`depends_on` - a template that hid itself, or planned other commands, has stopped being a template and
become a use.

## The five refusals

Each of these is a load error with the offending name in it, not a warning and not a silent drop. They
are worth reading as a group, because together they are the whole of the rule.

**A command that declares a body.**

> command 'build wheel' declares `impl:`. A command is an instance of a task: declare the body once under
> `tasks:` and point this command at it with `task:`.

**A task that declares a command's key.**

> task 'wheel' declares `with:`, which belongs on a command rather than on the task it instantiates. Move
> it to the command under `groups:`.

**A task that declares a key nobody reads.** Anything outside the four is rejected rather than dropped,
including keys that read as entirely plausible on a template:

> task 'wheel' declares unknown key `group:`. A task takes impl, help, passthrough_args, params - check
> the spelling.

**A task with no body at all.** The message names the alternative, because the mistake it usually
represents is reaching for the wrong construct:

> task 'all' declares no `impl:`. A task is a template for a body, so it names one as "module:function";
> a command that plans other commands uses `depends_on:` instead.

**A task that no command instantiates.**

> task 'wheel' is declared and no command instantiates it. A template nobody uses is a dead declaration:
> add a command for it under `groups:`, or delete it.

That last one is scoped to the *product's* own `tasks:` on purpose. The kernel's catalogue deliberately
declares more than it places: a task that needs a manifest section or a running lab must not become a
baseline command that dies on its first line in every product that has neither.

{{< callout type="info" >}}
Read the five together and the shape behind them is one rule: **a declaration that renders nowhere is
worse than one that fails.** A task key that is read by nobody, a template nothing instantiates, a body
written where it cannot be found - each of them loads clean and then does not exist, which is the most
expensive kind of nothing. There is [a rule about exactly this](../rules/), and it is the one that comes
up most often.
{{< /callout >}}

## The colon tells you which `tasks:` is meant

A command's `task:` value is resolved by one function against two sources, and the colon is the whole of
the decision:

| `task:` value | Where the template comes from |
|---|---|
| `wheel` — no colon | a task **this manifest** declares under its own `tasks:` |
| `docs:site` — a colon | a **catalogue coordinate**: the template lives in the kernel |

The two name spaces cannot intersect - a bare name can never contain a colon - so nothing shadows
anything and there is no precedence rule to memorise. A bare name is yours; a coordinate is the
platform's. A value that resolves in neither is a load error that lists what *is* available in the source
it looked in:

> command 'build site' names no task: 'docs:website' is not declared by the platform catalogue. A name
> with a colon is a platform coordinate, a name without one is a task in this manifest's `tasks:`.
> Available there: docs:reference, docs:render, docs:site, support:claude-plugins, ...

A coordinate is deliberately not a module path. The body behind `docs:site` can move inside the kernel
without breaking a single product manifest, and that indirection is the entire reason the catalogue
exists.

## One template, several commands

This is the payoff, and it is the reason the split earns its keep:

```yaml
groups:
  test:
    commands:
      unit:   { task: "test:gate", with: { name: "unit" },   help: "Run the unit suite." }
      system: { task: "test:gate", with: { name: "system" }, help: "Run the system suite." }
      smoke:  { task: "test:gate", with: { name: "smoke" },  help: "Run the smoke suite." }
```

Three commands. One body. The only difference between them is a value the manifest pinned.

A pinned parameter is **absent from the command line**. It is not an option with a default that can still
be overridden - it is removed from the generated signature and supplied at call time. `myctl test unit
--name system` is not a command, and that is the point: the manifest decided, so there is nothing left to
decide at the prompt.

The one conflict that follows from this is checked, because it would otherwise be invisible:

> command 'test unit' pins name with `with:` and also declares `params:` for it. A pinned parameter is off
> the command line, so its presentation renders nowhere - drop the `params:` entry, or drop the pin if the
> user should still be able to set it.

Note the scope: this is about the command's **own** `params:`. A parameter the *template* documents and
this command pins is the design's canonical shape - one task documents a parameter once, every instance
may pin it - so the pinned key is simply dropped from the merged presentation rather than rejected. Any
sibling command that leaves it unpinned still gets the documentation.

## The third kind of command: an aggregate

A command need not instantiate a task at all. It can instead be a plan over other commands:

```yaml
docs:
  help: "Write the command reference, then build the website from it."
  depends_on: [reference, site]
```

`task:` and `depends_on:` are mutually exclusive, and a command must have one of them:

> command 'build docs' declares both `task:` and `depends_on:`. A command either instantiates a task or
> plans other commands, never both - split it into two.

> command 'build docs' declares neither `task:` nor `depends_on:`. A command either instantiates a task or
> is an aggregate that plans other commands.

An aggregate is still a command - it has a name, a group, a help text and a place in the tree. What it
does not have is a template, which is why `depends_on` is a command key and could never be a task key.
The rest of the mechanics - post-order walk, dedup, list order as execution order - are in [the
manifest](../manifest/#aggregates-depends_on).

## Refinement, and deliberate replacement

Because the catalogue *places* some commands itself, a product's tree and the platform's can name the same
command. Merging is per key, not per node, so a product refining one thing keeps everything else:

- point at the **same** `task:` (or name none) and change `help:`, `params:` or `with:` - that is a
  **refinement**, and it is silent, because it is the mechanism working;
- point at a **different** `task:` and it is not a refinement. It is a second, different body under one
  name, and the loader stops rather than letting one dictionary win over the other.

The rejection names both bodies by their real `module:function` rather than by the coordinate they share:

> command 'support install' redeclares `task:` from 'support:install' to 'install' - two different bodies
> placed under one name: the platform's is `simplon.tasks.hosttools:install`, the product's is
> `orchestrator.cli:install`. Which one runs is exactly the silent choice this loader refuses to make -
> `install` and `install` look the same, `simplon.tasks.hosttools:install` and `orchestrator.cli:install`
> do not. If the product's body must deliberately replace the platform's here, add `override: true` [...]

`install` and `install` read identically; two module paths do not. A human cannot act on the first pair
and can act on the second. `override: true` is the explicit yes, and an overriding node then stands
**alone** rather than merging with the base's `help:` and `params:` - those describe the body that no
longer runs. This has [its own rule](../rules/#a-name-collision-breaks-loudly).

One more shape is refused for the same reason: refining a task-backed command into an aggregate, or the
reverse. Moving a command between the two is a different command wearing the same name, and it is asked
to have its own.

## Offered, or placed

A catalogue task can reach a product two ways, and the difference decides who chooses.

**Offered** is the default. The task exists at its coordinate, and a product that wants it declares a
command pointing at it. Most tasks are here: `docs:site`, `release:artifact`, `test:gate` and the rest
all need a section in the product's manifest, so a command placed for everyone would die on its first
line in a product that declared nothing.

**Placed** means the kernel writes the command into its own tree, and every product using the tree form
gets it. There is no way to decline one: the two trees are unioned, and a product cannot subtract.

That absence of a veto is what sets the bar. A placed command has to be **useful in every product**, not
merely harmless in most:

- it reads nothing from a product manifest, so it cannot fail for lack of declaration;
- it acts on the machine or the repository, which every product has;
- and a product that never runs it is no worse off for having it.

`support install`, the `support git` verbs and `support tasks` pass all three. `release:tag` does not,
and it is the case that fixed the rule: it **publishes** — it cuts a tag and pushes it, so a misfire is
public and cannot be taken back, and a product with no tag-triggered workflow has nothing waiting for
that tag. Offering it costs a product one line in its manifest. Placing it would cost every product a
command it never asked for, pointed at its own origin.

Simplon releases by tag, so simplon declares it — which is exactly the shape a product should copy.

## Phase or family: which half of a coordinate is a placement

"Offered, or placed" above decides whether the kernel hands a command to everybody. This is the question
underneath it, and it applies to every coordinate whether the kernel placed it or a product did: **where
may this one go?**

> A coordinate that starts with a **phase** name belongs in exactly that phase.
> Any other namespace is a **family**, and the product places it where it likes.

The phases are the platform's own top-level groups - `build`, `test`, `release`, `deploy`, `monitor` and
`support`. So `build:image` is under `build`, in every product, always; `docs:site` is a documentation
task and says nothing at all about when it runs.

### Why two axes, and why this is what keeps them two

The namespace says the **family**; the group says the **placement**. They are two questions because
products genuinely answer them differently:

```yaml
# one product builds its site as part of the build
build:
  commands:
    site: { task: "docs:site" }

# another publishes it, and files the very same task there
release:
  commands:
    site: { task: "docs:site" }
```

Both are right, and no rule should have to pick. That is exactly what the two alternatives on the table
would have cost. Making every coordinate thematic (`image:build`, `pytest:gate`) would have renamed every
product manifest to say something they already said. Making every coordinate a phase would have deleted
the second axis outright - and would have broken on `vcs:commit` first, because committing belongs to no
single phase.

What the rule removes is neither axis. It is the **third state**: a namespace that reads like a phase and
is placed somewhere else. That case is the only one where a reader cannot tell which axis a name is on -
and, before this rule, nothing stopped it from appearing.

### What it costs today: nothing

Measured over both manifests that exist before the rule was written - simplon's own and agile-cockpit's -
**zero** placements violate it. The rule does not rename anything; it writes down what both files already
do, and turns a habit into something the loader holds.

### The refusal

Placing a phase-named coordinate anywhere but its phase is a load error. It names both coordinates - the
one in the tree and the one in the catalogue - the group that is allowed, and the two ways out:

> command 'test image' places the coordinate 'build:image', whose namespace 'build' is a phase. A
> coordinate that starts with a phase name says where the task belongs, so 'build:image' belongs under
> `groups: build:` and nowhere else - this places it under 'test'. Move the command to `groups: build:
> commands: image:`, or - if this body really is a family each product places where it likes - give it a
> namespace in the platform catalogue that is not a phase, the way `docs:site` can sit under `build` in
> one product and under `release` in another. The phases are: build, deploy, monitor, release, support,
> test.

Two details of the scope are worth stating, because both are deliberate:

- **Only the first segment of the path is the phase.** `support git commit` is in `support`, so a
  coordinate filed one shelf deeper inside its own phase is placed correctly - the rule is about which
  phase a task runs in, not which shelf it sits on inside one.
- **A bare `task:` name is outside the rule.** A name without a colon is a task this manifest declares
  itself; there is no namespace to read, and where a product files its own body is its own business.


## How to read a manifest with this in hand

Three questions, in this order, will tell you what any entry is:

1. **Is it under `tasks:` or under `commands:`?** That is template versus placement, and it settles which
   keys are even legal.
2. **Does its `task:` value contain a colon?** That settles where the body comes from - this file, or the
   kernel.
3. **Does it have `depends_on:` instead?** Then it has no body at all; it is a plan, and its steps are
   other commands in the same tree.

With those three answered, [The manifest](../manifest/) is a description of a file rather than a set of
new ideas.
