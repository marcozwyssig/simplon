---
title: "One contract, two products"
weight: 7
---

Every other chapter here follows one product through the loop. This one is about the seam *between* two:
a Java product and a Python product that have to agree on an interface, and what the platform does and
does not do about it.

## What was driven

Two products scaffolded with `simplon init`, one `.proto`, and a call that crossed the wire. Every line
below was run on 2026-09-13.

```text
$ ./pysvc.sh   support toolchain python 3.12     python: wrote 4 command(s) - proto, deps, unit, analyse
$ ./javasvc.sh support toolchain java 21         java: wrote 3 command(s) - proto, compile, unit
$ ./pysvc.sh   build proto                       build/proto/python/greeter_pb2.py, greeter_pb2_grpc.py
$ ./javasvc.sh build proto                       build/proto/java/demo/grpc/GreeterGrpc.java + 5 more
```

Then a Java client, built from `javasvc`'s stubs, against a Python service running `pysvc`'s:

```text
REPLY: hello javasvc, from the python service
```

That is the whole claim of this page, and it is a measurement rather than a diagram: **the same four
words on both sides.** `build proto` reads identically in a Java product and a Python one, because what
differs - `protoc`, the plugin, the output layout - sits behind a command the kernel scaffolds and the
product owns.

## The contract

Seven lines, and neither product owns them:

```proto
syntax = "proto3";
package demo;
option java_package = "demo.grpc";
option java_multiple_files = true;
service Greeter { rpc Hello (HelloRequest) returns (HelloReply); }
message HelloRequest { string name = 1; }
message HelloReply { string text = 1; }
```

Each side generated from it into `build/proto/`, regenerated on every run and committed by nobody -
generated code is not source, so nothing in either tree can go stale against the contract.

## What is *not* shared, and it is the interesting half

**The `.proto` was copied into both trees.** There is one contract in this chapter and two files, and
nothing in the kernel keeps them equal. That is the second-source shape this platform removes everywhere
else - and here it is, in the middle of a page about two products agreeing.

What the kernel does today is make both sides *generate* identically. What it does not do is give the
contract a home: no section names it, no command fetches it, and a `greeter.proto` that drifts in one
repository produces two stub sets that compile and disagree at run time.

Three ways out exist and none is chosen here: a submodule, a published artefact both products fetch (the
shape [handing a package over](../handing-a-package-over/) already describes for libraries), or one
repository owning the contract and the other generating from a pinned copy. Naming the gap is what this
page can honestly do; closing it is a decision about somebody's repositories, not a documentation change.

**Also not shared:** the servers, the tests, and the deployments. The Java product builds a jar and the
Python one does not; each has its own suites and its own `deploy:` answer. The interface is the only
thing in common, which is the point of an interface.

## What this does not say

The run above proves that both sides generate from one contract and that the generated code interoperates
over the wire. It says nothing about versioning: nothing here detects that a field was renumbered, and a
breaking change to the contract would produce two stub sets that build and fail at run time exactly as
the drift above would. A contract check belongs under `test`, and there is none yet - it is named as open
work in [simplon#238](https://github.com/marcozwyssig/simplon/issues/238) rather than implied by this
page.
