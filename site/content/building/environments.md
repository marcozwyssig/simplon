---
title: "Environments"
weight: 5
---

Some commands are meaningless without a target, and some are meaningless with one. Simplon makes that a
declaration rather than a convention, and then enforces it in the dispatch.

## The matrix

```yaml
default: dev
environments:
  dev:  { backend: local,    description: "Local development environment (the default)." }
  test: { backend: exoscale, description: "Shared integration environment." }
  prod: { backend: exoscale, description: "Production." }
```

`backend` decides **how** an environment is realised - which is a product's own vocabulary, not the
kernel's. A product supplies the set of valid backend names, and the registry validates every row
against it, so a typo'd backend fails at load rather than half-way through a deployment. `default` must
name a real environment, checked the same way.

This lives in the one manifest alongside the command tree. There is no separate `environments.yml` to
keep in step.

## Env-first groups

```yaml
env_groups: [deploy, monitor]
```

`deploy` and `monitor` are declared `env_first: true` in the kernel's own catalogue, so a product
inherits the gate and the two lines above are a restatement rather than a requirement.

What the key may never do is **contradict** the catalogue. An entry naming a group the catalogue
declares not env-first is refused, with the same reason - and the same way out - that `env_first: true`
written onto that group's node already gets: a product adds commands and sub-groups to a platform group,
it never changes the group's shape. Write `env_groups:` for a top-level group **no catalogue owns**,
which is a manifest loaded without one; there it is that manifest's own statement about its own group
and switches the gate on.

Commands in those groups take the environment as the **outer** token, before the group:

```text
myctl prod deploy up
myctl prod monitor status
```

Outer rather than an option, because the target is part of *naming* the command. `deploy up --env prod`
reads as one command configured for prod; `myctl prod deploy up` reads as the prod deployment - which is
what it is, and what the person reviewing the change is looking for.

Every other group is environment-agnostic and refuses the token:

```text
$ ./myctl.sh dev build
[14:48:59] ERR 'build' is environment-agnostic and takes no env prefix; run 'myctl build'
```

Say that as a statement about artefacts. A wheel built "for dev" is either byte-identical to the one you
would have built anyway, in which case the token meant nothing, or it is a different artefact, in which
case the thing you tested and the thing you ship have quietly become two things.

Leave the token off an env-first command and the `default:` applies. Both spellings below run the same
command, and the second one is the one to put in anything anyone else will read - the default is a
convenience for your own terminal, not documentation:

```text
myctl deploy up
myctl dev deploy up
```

## What the dispatch actually does

Four steps, in order:

1. **Consume a leading environment token, if there is one.** Whether one was given *explicitly* is
   remembered, because an agnostic group has to be able to reject one.
2. **Export the active environment** into the process environment variable the product's provider names,
   so a task body reads it from one place.
3. **Ask the manifest taxonomy for a verdict** on the command's group: `reject-env` for an agnostic
   group that was handed an explicit environment, `gate-backend` for an env-first group, `ok` otherwise.
4. **Apply it.** A rejection is an error with the command you meant. A `gate-backend` verdict against a
   non-local backend goes through the product's own backend gate.

The gate in step 4 is the product's, not the kernel's. The kernel knows that a CD group must be gated;
*what* a non-local backend requires - credentials, a reachable API, a confirmation - is the product's
call, and it arrives through a small structural provider interface. Nothing named is imported by the
kernel, so the coupling only ever flows product to kernel.

### The one collision, resolved on purpose

A leading token that names a **group** is the command layer, never an environment token. This is not a
detail: a product may perfectly well have an environment called `test` and a CI group called `test`, and
`myctl test unit` has to dispatch the test group or that whole subtree becomes unreachable.

The rule is "group wins", and it loses nothing - the environment is still reachable everywhere the
environment is what you meant, which is in front of an env-first group, where no group name is being
shadowed.

## Listing them

```yaml
groups:
  support:
    commands:
      environments: { task: "support:environments" }
```

```text
$ ./myctl.sh support environments
```

Note that this is a command the product declares, and the catalogue does not place it for everybody.
`support:environments` reads an `environments:` section; placed by default, it would be a command that
dies on its first line in every product that has none. That is the same rule as `docs:site` and
`test:gate` - see [the manifest chapter](../manifest/#product-data-sections).
