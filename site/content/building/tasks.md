---
title: "Writing a task"
weight: 2
---

A task body is a plain Python function. Not a subclass, not a decorated callable, not an object with a
`run()` method - a function that takes what the manifest binds to it and returns an exit code.

```python
def build_wheel() -> int:
    """Build the wheel."""
    return run([sys.executable, "-m", "build", "--wheel"], capture=False).rc
```

That is the whole contract for the simple case. The manifest's `impl: "orchestrator.cli:build_wheel"`
means *import this module, take the attribute named after the colon*, so the function has to be at
module level and nothing else about it is special.

## Where a body lives, and what that decides

**In the product** (`orchestrator/cli.py` or a module beside it) when it knows something about *this*
product: which artefacts, which registry, which service. That is most of what a new product writes.

**In the kernel's catalogue** when it knows nothing about any particular product. Rendering
documentation, running a declared pytest suite, pushing a stack to Portainer, provisioning host tooling
- the mechanics of all four carry no product knowledge, so all four are catalogue tasks and every
product gets them by declaring a command.

The test for which side a body belongs on is not "is it useful to more than one product". It is: **can
it be written without naming this product's directories, images or services?** If yes, the data that
would have named them belongs in a manifest section, and the body belongs in the kernel. If no, it is
the product's.

There is a corollary, and it is the discipline that keeps the catalogue honest: a catalogue task is a
promise to three products, not a convenience for one. A body that reaches for a directory it merely
happens to know about has imposed one product's layout on everybody, and it will be the second product
that finds out.

## The signature is the command line

Typer derives the whole command line from the body's signature - options, arguments, types, defaults.
That has two consequences you feel immediately.

**Annotate.** An unannotated `dry_run=False` becomes a *text* option, so `--dry-run` silently turns into
`--dry-run TEXT`. Annotate it `bool` and it is a flag.

**Required means no default.** A parameter with no default is a required argument; one with a default is
an option that falls back to it.

```python
def render(config: str = "mypy.ini", workdir: str = "", strict: bool = False) -> int:
    ...
```

What the *manifest* adds on top is presentation only - the help text, the short flag, the metavar, the
declaration order:

```yaml
params:
  dry_run: { help: "preview only", short: "-n" }
```

The type and the default are never restated in YAML. They exist in the signature, and a second copy is a
second thing to keep in step.

A body that wants the raw trailing arguments takes a `typer.Context` - recognised by *name* (`c`, `ctx`,
`context`), not by position, because plenty of bodies take none and dropping the first parameter
unconditionally would hand a context object to a payload parameter. Typer does not treat it as a CLI
parameter, so it stays invisible on the command line. Pair it with `passthrough_args: true` on the task.

## Reaching product data

A body never imports the product. It asks the registered context:

```python
from simplon import context

def build() -> int:
    ctx = context.current()
    data = ctx.manifest_data()          # the raw manifest, for a product-owned section
    root = ctx.root                     # the product root
    name = ctx.name                     # the product's own name
```

`manifest_data()` is how a section like `site:` or `suites:` reaches the task that reads it. Validate it
loudly and in one place - `declared(data)` style, returning a frozen dataclass - so a manifest mistake
fails at load with the key named, rather than three minutes later as a container run against a path that
does not exist.

## Returning, not exiting

Return an `int`. Do not call `sys.exit`, and do not raise `typer.Exit` from a body: the generated
wrapper coerces the return value into the process exit code, and a body that exits by itself cannot be
called by another body or asserted on by a test.

There is history here. Five kernel bodies once raised `typer.Exit` and were annotated `-> None`, which
made every generated wrapper's `_rc(<call>)` draw a type error at the call site. They now return the int
their delegates already produced.

## Running things

Every external call goes through one seam:

```python
from simplon.run import run

result = run(["docker", "run", "--rm", image, *argv], capture=False)
if not result.ok:
    ...
```

`run` takes a **list**, never a shell string, and hands back the real return code rather than whatever
`&&`-chaining left in `$?`. It is also the single place the step UI streams per-step output from, which
is why a body that shells out by hand loses the log file it would otherwise have got for free.

## Saying what happened

```python
from simplon import log

log.info("what is about to happen")
log.ok("it worked")
log.warn("notable, not fatal")     # stdout
log.error("this went wrong")       # stderr, no exit - the caller keeps its return code
log.die("this cannot continue")    # stderr, then SystemExit
```

The `warn` / `error` line is the one that matters, and it is not a matter of tone. `warn` goes to stdout
and is for the merely notable; `error` goes to stderr and means something failed. Anyone measuring a run
by its exit code - which is every CI system - learns nothing from a warning. There is [a rule about
exactly this](../rules/#a-missing-tool-is-not-a-failed-tool), and it cost two releases to learn.

## Report the outcome, do not raise it

For anything a caller might want to *inspect* rather than merely survive, return a small frozen result
object with named predicates:

```python
@dataclass(frozen=True)
class Build:
    index: Path | None = None
    tool: str | None = None

    @property
    def ok(self) -> bool:
        """A site was built."""
        return self.index is not None

    @property
    def failed(self) -> bool:
        """The toolchain WAS available and produced no site."""
        return self.tool is not None and self.index is None
```

Two predicates, not one, because "no output" has two causes that deserve different exit codes. A caller
that ignores the return value is unaffected and nothing explodes in its face; a caller that cares can
tell a missing tool from a broken one. It is the same idiom `run.Result` uses, for the same reason.

## Registering it

**A product-local body:** declare the task, place the command.

```yaml
tasks:
  wheel: { impl: "orchestrator.cli:build_wheel", help: "Build the wheel." }

groups:
  build:
    commands:
      wheel: { task: "wheel" }
```

**A kernel body:** it goes in the catalogue under a coordinate, with the help text as its fallback
wording, and products place it by coordinate.

```yaml
docs:site:
  impl: simplon.tasks.site:build
  help: "Build the product's documentation website with Hugo, in Docker (HTML only)."
```

Whether a coordinate is also *placed* by the catalogue - so that every product gets the command without
asking - depends on one thing: whether it needs product data. `vcs:commit` needs none, so the catalogue
places it and every product has `support git commit`. `docs:site` needs a `site:` section, so it stays a
task and a product declares the command the day it has the section. Placed for everybody, it would be a
command that dies on its first line in every product that has no website.

## Testing it

Split the pure part from the shelling-out part and test the pure part directly - path validation, the
argv you assemble, the parsing of a manifest section. Then test the outcome object for both of its
answers.

One habit is worth adopting wholesale, because it is what the kernel's own history keeps rewarding:
**run a new test against the unfixed code first and watch it fail for the reason it names.** A test
written after the fix proves the code is unchanged, which is not the same thing as proving it is right.
