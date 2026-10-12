---
title: "Running a command"
weight: 6
---

What you see while a command runs, where its output is kept, and how to ask for the plain version.

## Attached to a terminal, you get the plan as a tree

A command that runs several steps draws them. The plan is on the left, one row per step with its state
icon and its duration; the highlighted step's live output is on the right.

```text
 simplon build all                                    01:12

 ✓ build                             ┌ package ──────────────┐
   ✓ wheel                <0.1s      │ running setup.py       │
   ⠹ package               1.2s      │ creating build/lib     │
   · docs                            │ copying src/simplon    │
 · test                              │                        │

 q Quit  ↑↓ Move  f Follow  n Next failure  / Filter  c Copy  s Save
```

An aggregate row is never run itself: its state is derived from the children below it. The exit code
comes from the steps, never from what the screen shows.

| key | what it does |
|---|---|
| `q` | quit - the run stops and the record is still written |
| `↑` `↓` | move the cursor between rows |
| `f` | follow: the cursor jumps to whatever is running |
| `n` | jump to the next failure |
| `/` | filter the rows by a substring; `/` again closes it |
| `c` | copy the highlighted step's output |
| `s` | save the highlighted step's output to a file |

## The output outlives the screen

The UI is gone the moment the run ends, so nothing you need is kept only there.

- **Each step writes its own log** to `build/logs/<step>.log` - which is the only way to read a long
  step's output back, because the UI holds the mouse and nothing in it can be selected.
- **The whole run writes a transcript** to `build/logs/run-transcript.log`, on *both* the terminal and
  the plain path, because the run most worth attaching to a ticket is a red one from CI.
- **A failure report is printed after the UI exits**, onto the terminal you are left looking at. A run
  with no failure prints nothing there, so a green run is not one line longer.

## Without a terminal, you get a flat log

Piped, redirected or in CI, the same plan runs as a flat log - one line per step, the tree printed once
at the end in the same icons - so a log stays a log. The verdict is identical either way.

**You can ask for that on purpose**, rather than arranging for a redirection:

```text
$ ./myctl.sh --no-tui build all
```

The flag sets `SIMPLON_NO_TUI=1`, and a workflow can export that variable directly instead:

```yaml
env:
  SIMPLON_NO_TUI: "1"
```

The variable is the one that travels. A plan's steps are separate `./myctl.sh <step>` processes, so a
flag on the parent reaches none of them while the variable reaches all of them. A value that is neither
`0` nor `1` leaves the runner where it was and says so.

{{< callout type="info" >}}
Redirection still works exactly as it did. `--no-tui` is a second way to say it, not a replacement.
{{< /callout >}}

## When the UI cannot start

Two cases, and they are no longer the same case.

**Textual is not installed.** The plain runner takes over without comment. That is a supported way to run
this - the headless path does not require Textual at all.

**Textual is installed and broken** - a half-finished install, a version that does not fit, anything that
falls over while the UI is being built. That now **fails, and says what happened**.

{{< callout type="warning" >}}
Until 0.13.0 the second case looked exactly like the first: a broken install quietly produced a
plain-looking run with a normal exit code, indistinguishable from a deliberate redirection. If a machine
has been giving you plain output for a reason nobody checked, it will now tell you instead.
{{< /callout >}}

## Two neighbouring questions

**How many steps run at once** is the machine's answer rather than the manifest's - `SIMPLON_MAX_PARALLEL`,
default four or the CPU count, whichever is smaller. Which steps *may* run together is declared, and that
is [`parallel:` in the manifest](../manifest/#parallel-the-one-key-that-suspends-list-order).

**What the kernel itself runs in** - Python in a virtual environment on this host, or a container - is
`DELIVERY_ROUTE`, and it is [two routes, one CLI](../what-init-wrote/#two-routes-one-cli).
