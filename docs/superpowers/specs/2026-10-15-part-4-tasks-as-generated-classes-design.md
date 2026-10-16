# Part 4: tasks as generated classes, the body as a protected method

**Status:** design, decided by Marco on 2026-10-15 by two choice lists. Ticket: si#400. Builds on
"Part 4, decided now" in `2026-10-13-architecture-as-a-firn-model-design.md`, which fixed the shape: a
task is a class, a command is an instance, kinds and habitats are classes, `local` is gone, and SOLID is
the check. This spec says how that shape reaches Python, in the kernel and in a product.

**Revised 2026-10-16 (Marco, on the closed si#400 4a PR #462): in the firn model a task is an
INSTANCE, not a class.** `TaskType extends firn.core.Class` was the wrong shape. The model keeps the form
main has: `Task typeOf firn.core.Class extends firn.core.NamedResource`, its `key`, `body`, `input` and
`output`, and the catalogue's tasks as instances of `CatalogueTask`. What firn *generates* from each
instance is still a Python class, with the body in its protected region. Decisions 1, 2, 3, 5 and 6
stand as written. Decision 4 changes (below). Measured on firn v0.1.0 while settling it:

- With `TaskType extends firn.core.Resource`, a task written as a class (`BuildImage typeOf TaskType
  extends Task`) is red: `E200 cannot resolve` on `extends`, `property` and `name`.
- A **named** instance of a class that extends `firn.core.Resource` is red too: `E200 cannot resolve
  'name'`. The name comes from `firn.core.NamedResource`, and a command can only reference a named task.

## The goal, in one sentence

Every task, the kernel's and every product's, is a Python class that firn generates from a task instance
in a firn model (an instance of `simplon.pipeline.Task`, revised 2026-10-16). Its ports are typed attributes and its body is a hand-written method
in a protected region. A command is an object of a `Command` class (revised 2026-10-16), and `CommandSpec` and the `impl:` lookup
go.

## Decisions (Marco, 2026-10-15)

1. **The model reaches a product inside the wheel, as a firn library jar.** The wheel carries a jar with
   `META-INF/firn/firn.toml`, which is firn's own form for a model library (firn adr/0025, adr/0042).
   The kernel's command that runs `firn gen` hands it to firn with `-cp`. A product's `firn.toml` names
   nothing, and the model's version is the `simplon==` pin.
2. **The body meets the generated class in a protected region.** firn generates the whole class, and its
   `run` method's body is a protected region named per class. There is one class per task, not a
   generated base and a hand subclass.
3. **The migration is a generated wrapper.** The protected region's first content is a call to the
   function that `impl:` names today. No product has to rewrite a body at once. Each one moves a body
   into the method when it chooses, and `CommandSpec` and the `impl:` lookup still go in the same step,
   so only one source is live (si#456's guard rail).
4. **Every task writes its own coordinate.** Two tasks with one coordinate would be ambiguous, which is
   the defect this project hunts, and a task without a `key` is a **diagnosis**. *Revised 2026-10-16:*
   first written for task classes, where `key` is not inherited (measured). With tasks as instances
   there is nothing to inherit; the open part is that `key` is `0..1` on `Task` today, so making it
   required is part of building 4a.
5. **One file per class.** The default is `<package>/tasks/<name>.py`: one task, one file, one region,
   small diffs (SRP). The location is a kernel default that a product's `firn.toml` target may override.
6. **A protected region that firn no longer produces is a refusal.** This is a diagnosis, not an
   expression rule, because without it the failure is silent (measured below).

## Measured 2026-10-15 (pinned `ghcr.io/marcozwyssig/firn:v0.1.0`, probes in the session scratchpad, not committed)

The probes below were written in the class form withdrawn on 2026-10-16. What they show about the jar,
the template's scope and protected regions does not depend on that form; the selectors do (`for t :
\`simplon.pipeline.CatalogueTask\`` over instances, as main's templates already walk them).

- **A product extends a library's task class through a jar, with rc 0.** The library jar carries
  `META-INF/firn/firn.toml`, `model/kern/kern.firn` (`TaskType`, `Task`, `BuildImage`) and
  `templates/tasks.firnt`. The product's model writes `MyBuild typeOf kern.TaskType extends
  kern.BuildImage { key = "build:mine" }`, and `firn gen -cp libs/kern.jar` writes `class
  MyBuild(BuildImage)`. **The paths inside the marker are relative to the jar root, not to the
  marker.** A jar laid out under `META-INF/firn/model/` failed with `E200 cannot resolve 'name'` on
  every name, `firn.core`'s included.
- **The library's template generates the library's classes too.** `for t : \`kern.TaskType\`` answered
  `BuildImage` beside `MyBuild`, so a product would get the kernel's classes in its own tree, which is a
  second source. The product's template has to keep only the product's own package. *Measured
  2026-10-16:* ``.inBuild()`` does it (firn docs/04, adr/0072): over a library on `-cp`, the product's
  output held only its own.
- **A protected region per class works inside a `for`.** `protected "${t.name}.run"` writes one
  region per class. A hand-written body survives a second `gen` ("1 up to date").
- **Renaming a class orphans its body, with rc 0.** With one file for all classes, firn appends the old
  region at the end of the file, at column 0, and says `warning[W300]: template 'Tasks' no longer
  produces the protected region 'BuildImage.run'`. The renamed class's `run` is back to
  `raise NotImplementedError`. In the probe it was loud only by luck: the orphan was a `return`, and
  `return` outside a function does not compile. A body without `return` would import cleanly.
- **With one file per class, the old file is kept, with rc 0.** firn says `warning[W301]: no template
  produces 'out/BuildImage.py' any more ... it was kept rather than deleted because it holds a protected
  region`. The old file still defines the old class with the old `KEY`, so after a rename that does not
  change the key, two classes carry one coordinate.
- **Both warnings can be read by a machine.** `firn gen --format=json` lists them in
  `diagnostics[].code` (`W300`, `W301`) and the kept files in `files.kept`. That is how decision 6 is
  built: the kernel's `gen` command reads the JSON and answers rc 1 on either code, naming the file.

## How the jar reaches firn

firn runs in its container through `toolchain:run`, which mounts the product root only:
`hostpath.translate(root)` (`src/simplon/tasks/toolchain.py`). A jar inside the installed package lies
outside that mount, and inside the kernel image it is not a host path at all. So the kernel's `gen`
command **copies the jar from the installed package into the product's build directory** before it
runs firn, and passes that path to `-cp`. That copy is a build output, written on every run and never
committed, so it is not a second source. *Unmeasured:* that the copy is reachable when the kernel itself
runs in its image (the host-path translation of `build/`).

`build wheel` builds the jar from `src/firn/` (the marker is `firn.toml` with paths relative to the jar
root), and `test_wheel.py` has to say that it ships, as it now says the wheel ships nothing beside
`simplon`.

## The shape in Python

```python
# <package>/tasks/build_image.py - GENERATED; edit only inside the protected region
class BuildImage(Task):
    KEY = "build:image"
    image: Image                      # output port; the type is the kind class

    def run(self) -> None:
        # Begin Protected Region [BuildImage.run]
        return build(self)            # the wrapper (decision 3): impl "simplon.tasks.image:build"
        # End Protected Region  [BuildImage.run]

# the kernel's, hand-written - the Python image of simplon.pipeline's TaskCommand and AggregateCommand
class TaskCommand(Command): ...       # holds its task class and its port bindings
class AggregateCommand(Command): ...  # holds its members; runs no task

build_firn = TaskCommand(task=BuildImage, produces={"image": firn_image})  # a command is an object
build_all = AggregateCommand(members=[build_firn])
```

**Revised 2026-10-16 (Marco, by choice list): a command is an object of a `Command` class, not of its task
class.** The Python classes mirror the firn model: every task is a generated class deriving from `Task`;
`TaskCommand` and `AggregateCommand` derive from `Command`, and each command of a manifest is an object of
one of them. The first form (`build_firn = BuildImage(image=firn_image)`) had no place for an aggregate,
which runs no task, and left `Command` without a role.

The wrapper's call is the function that `impl:` names today. How the wrapper hands the bound ports and
parameters to a function that takes keyword arguments is the plan's first design step, measured against
`signatures.py`, which reads those parameters with `inspect` at run time today.

## What goes, and in what order

Each step is small, and only one source is live at a time.

1. **The kernel's model.** The catalogue's tasks stay instances of `CatalogueTask` (revised
   2026-10-16), and their ports stay `input`/`output` compositions of `Port`. Today
   `catalogue/tasks.firn` holds 18 of the 54; the template needs all of them, so the 36 without a port
   join as instances. `test_catalogue_ports.py` stays, because firn does not refuse a `needs` on a
   foreign kind (measured in the part 1 spec).
2. **The template, over the kernel first.** It generates one Python class per task instance, one file
   per class, with wrapper regions. The kernel follows the layout it gives products, and no exemption.
3. **The runtime.** The loader builds each command as a `TaskCommand` or `AggregateCommand` object that holds
   its task class, instead of looking up
   `impl:` text. `CommandSpec` and the `impl:` lookup go. `signatures.py` goes once ports and parameters
   are typed attributes.
4. **The gen guard.** W300 and W301 become rc 1 (decision 6), seen red on a rename.
5. **The jar in the wheel**, and `gen -cp` in a product.
6. **The products, one per peer session**, each measuring its bill first (below).
7. **`Manifest` and `_ManifestModel`** go, as part 1 fixed. Kinds follow the same mechanism (kind
   classes, `refines` becomes `extends`). Habitats are si#455's, on this same mechanism.

Each class is checked against SOLID before it is generated (table on si#455, comment 6202270420), and
each step names the principle it moves toward.

## The bill, before anything ships

The rule "every task is a generated class" is an expression rule: a function body makes a working
product today. The wrapper (decision 3) is what keeps it affordable, because no body has to be rewritten.
What each product still pays, and its peer session measures before step 6, is:

- its `impl:` entries become task instances in a model: netctl 52, biz-cockpit 22, asbundle 15, cleon 12, swi 11,
  simplon 6, firn 4, agile-cockpit 3 (measured 2026-10-13);
- a `firn.toml` and a model in a product that has none today. No product imports `simplon.pipeline`
  (code search across all repos, 2026-10-15: only simplon's own files);
- the artifact entries that become instances of kind classes, and the `backend: local` that 6 of the 8
  manifests write (part 1's spec).

## Gates

`test model`, `build model` (tree clean afterwards), `test generated`, the suite, `typecheck-python`,
`build docs`, `build wheel` with `test_wheel.py`.

## Testing, per CLAUDE.md

- Decision 4 is seen red: a task instance without `key`.
- Decision 6 is seen red twice: a rename with one file per class (W301), and a region taken out of a
  template (W300).
- The jar is seen loading in a product the way it was in the probe, from the wheel's own copy, not a
  hand-zipped one.
- The template's package filter is seen red: without it, the kernel's classes appear in a product's tree.
