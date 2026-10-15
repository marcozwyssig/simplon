# Part 4: tasks as generated classes, the body as a protected method

**Status:** design, decided by Marco on 2026-10-15 by two choice lists. Ticket: si#400. Builds on
"Part 4, decided now" in `2026-10-13-architecture-as-a-firn-model-design.md`, which fixed the shape: a
task is a class, a command is an instance, kinds and habitats are classes, `local` is gone, and SOLID is
the check. This spec says how that shape reaches Python, in the kernel and in a product.

## The goal, in one sentence

Every task, the kernel's and every product's, is a Python class that firn generates from a firn model
extending `simplon.pipeline.Task`. Its ports are typed attributes and its body is a hand-written method
in a protected region. A command is an object of that class, and `CommandSpec` and the `impl:` lookup
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
4. **Every concrete task class writes its own coordinate.** `key` is not inherited in firn (measured), and
   that is right: two classes with one coordinate would be ambiguous, which is the defect this project
   hunts. A concrete task class without a `key` is a **diagnosis**.
5. **One file per class.** The default is `<package>/tasks/<name>.py`: one task, one file, one region,
   small diffs (SRP). The location is a kernel default that a product's `firn.toml` target may override.
6. **A protected region that firn no longer produces is a refusal.** This is a diagnosis, not an
   expression rule, because without it the failure is silent (measured below).

## Measured 2026-10-15 (pinned `ghcr.io/marcozwyssig/firn:v0.1.0`, probes in the session scratchpad, not committed)

- **A product extends a library's task class through a jar, with rc 0.** The library jar carries
  `META-INF/firn/firn.toml`, `model/kern/kern.firn` (`TaskType`, `Task`, `BuildImage`) and
  `templates/tasks.firnt`. The product's model writes `MyBuild typeOf kern.TaskType extends
  kern.BuildImage { key = "build:mine" }`, and `firn gen -cp libs/kern.jar` writes `class
  MyBuild(BuildImage)`. **The paths inside the marker are relative to the jar root, not to the
  marker.** A jar laid out under `META-INF/firn/model/` failed with `E200 cannot resolve 'name'` on
  every name, `firn.core`'s included.
- **The library's template generates the library's classes too.** `for t : \`kern.TaskType\`` answered
  `BuildImage` beside `MyBuild`, so a product would get the kernel's classes in its own tree, which is a
  second source. The product's template has to keep only the product's own package. *Unmeasured:*
  which selector filters a class by package.
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

build_firn = BuildImage(image=firn_image)  # a command is an object of its task class
```

The wrapper's call is the function that `impl:` names today. How the wrapper hands the bound ports and
parameters to a function that takes keyword arguments is the plan's first design step, measured against
`signatures.py`, which reads those parameters with `inspect` at run time today.

## What goes, and in what order

Each step is small, and only one source is live at a time.

1. **The kernel's model.** `TaskType` (the metaclass that carries `key` and `body`) and `Task` in
   `simplon.pipeline`. The 18 `CatalogueTask` instances in `catalogue/tasks.firn` become classes, and
   their ports become `OutputPort`/`InputPort` properties. `test_catalogue_ports.py` stays, because firn
   does not refuse a `needs` on a foreign kind (measured in the part 1 spec).
2. **The template, over the kernel first.** It generates the kernel's own task classes, one file per
   class, with wrapper regions. The kernel follows the layout it gives products, and no exemption.
3. **The runtime.** The loader builds a command as an object of its class, instead of looking up
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

- its `impl:` entries become model classes: netctl 52, biz-cockpit 22, asbundle 15, cleon 12, swi 11,
  simplon 6, firn 4, agile-cockpit 3 (measured 2026-10-13);
- a `firn.toml` and a model in a product that has none today. No product imports `simplon.pipeline`
  (code search across all repos, 2026-10-15: only simplon's own files);
- the artifact entries that become instances of kind classes, and the `backend: local` that 6 of the 8
  manifests write (part 1's spec).

## Gates

`test model`, `build model` (tree clean afterwards), `test generated`, the suite, `typecheck-python`,
`build docs`, `build wheel` with `test_wheel.py`.

## Testing, per CLAUDE.md

- Decision 4 is seen red: a concrete task class without `key`.
- Decision 6 is seen red twice: a rename with one file per class (W301), and a region taken out of a
  template (W300).
- The jar is seen loading in a product the way it was in the probe, from the wheel's own copy, not a
  hand-zipped one.
- The template's package filter is seen red: without it, the kernel's classes appear in a product's tree.
