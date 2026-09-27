---
title: "Preparing a CI host"
weight: 8
---

## Two commands, once per machine

A self-hosted runner is the same machine on the next job. Everything a build leaves behind is still there
tomorrow, and the two commands below are what a host needs before anybody points a workflow at it:

```bash
sudo ./<product>.sh support ci-privileges <user>     # si#92
sudo ./<product>.sh support ci-disk-hygiene          # si#327
```

Both need root, both are idempotent, and both refuse with a message that names the cure rather than
failing quietly. Neither is **placed** by the catalogue: a product that never provisions a CI host should
not find commands in its CLI that change who may become root or restart a docker engine.

## Why the disk one exists

This platform's own CI died of a full disk, and the way it died is the argument for the command:

```
E: You don't have enough free space in /var/cache/apt/archives/
```

Eight minutes into a docker build, with every gate before it green. On a second run of the same commit the
step ended with `conclusion: null`, **no log at all**, and the runner went offline. Neither text mentions a
disk. The machine had **64 GB in /var/lib/docker** against a ZFS refquota of the same size — so free space
on the pool bought nothing, and the container's own `df` was the only place the truth was visible.

Three things fill a runner, and `ci-disk-hygiene` answers each one:

| what grows | what stops it |
| --- | --- |
| container logs, unbounded under the default `json-file` driver | `log-opts`: `max-size` 50m, `max-file` 3 |
| the build cache, never reclaimed unless asked | `builder.gc` with a 10 GB ceiling — the engine keeps itself in check, no cron needed |
| images and stopped containers, per run | a daily `simplon-docker-prune.timer` pruning anything older than 48h |

**It merges into `/etc/docker/daemon.json` and never replaces it.** That file is where a host's
`data-root`, `registry-mirrors` and `insecure-registries` live; a command that wrote a fresh document
carrying only its own four settings would take a mirror away from a machine that needs one, and the symptom
would appear on the next build, nowhere near the cause. A file it cannot parse is a **refusal**, not a
reason to start fresh.

**It restarts the engine only when the document actually moved.** `systemctl restart docker` kills every
running container — on a runner, including the job that called the command. A second run on a configured
host therefore touches nothing.

Look before you apply, which is what `-n` is for on a fleet:

```bash
sudo ./<product>.sh support ci-disk-hygiene -n
```

## The two halves that run inside a job

```bash
./<product>.sh support ci-disk-preflight    # before the job's own steps
./<product>.sh support ci-disk-cleanup      # after them, whatever they decided
```

Neither needs a privilege. The preflight reads `df` — not docker, so it works on a runner whose engine is
installed inside the job — and **refuses** below 15% free, which is the same line as "85% used". A machine
that cannot finish the work says so in one second instead of eight minutes, with the disk named. A disk it
could not measure is reported rather than passed over as a healthy one, and does **not** fail the job: a
preflight that blocked every build because `df` changed its output would cost more than the defect it
guards.

The cleanup prunes build cache older than a day. There is an age filter because an unfiltered prune on
every run would trade a full disk for a cold build every time, and there is no `--volumes` anywhere,
because a runner with a persistent volume would lose it and the loss would look like a bug somewhere else.

**A generated workflow places both for you**, when the job's runner kind says the disk survives it:

```yaml
jobs:
  build:
    runner: { kind: self-hosted-debian, labels: <your-runner> }
```

`github-ubuntu` gets neither, because that machine is destroyed after every job and cannot have the
problem. A job that writes `runs-on:` itself gets neither either — that spelling says *the machine is
mine*, and the kernel has no table entry to reason from. If the two coordinates are not placed in the
command tree, the generated file **says so in a comment** naming what to place: a step calling a command
that does not exist would fail on the runner with the manifest looking correct.

The preflight stands **after** the checkout, and that is a limit rather than a preference. It is one of the
product's own commands, and a command needs the checkout it lives in. A checkout is cheap; what the
preflight buys is every step after it.

## Verifying it

```bash
docker system df          # before and after - `ci-disk-hygiene` prints both itself
df -h /var/lib/docker
systemctl list-timers simplon-docker-prune.timer
```

## Warning before it hurts, one level up

The preflight refuses at 15% free, which is late by design — it is the last line, not the first. The first
line belongs on the **host** that runs the containers, because a container cannot see the pool it is
quota'd out of: `df` inside it reports the quota, which is right for the preflight and useless for "which
of my machines is about to break".

`deploy/ci-hosts/` in this repository carries that sweep as a shell script and a systemd timer for a
Proxmox host: it walks the runner containers with `pct`, reports any whose root filesystem is over 80%
used, and exits non-zero so that whatever already watches failed units is the alert channel. It is
deliberately **not** a simplon command and deliberately does **not** prune: a threshold that pages somebody
depends on who is on call, and a script that quietly repaired the symptom would hide a runner that fills up
every day from the person who needs to know it does.
