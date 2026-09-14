---
title: "One contract, two languages"
weight: 7
---

Every other chapter here follows one product through the loop in one language. This one is about a
product whose interface has two sides - a Python service and a Java client, one `.proto` between them -
and what it takes to drive both from a single launcher.

## Two commands, one script

```text
$ ./greeter.sh build proto
  ✓ build.proto-python  0.5s
  ✓ build.proto-java    0.4s
  OK proto: all 2 steps passed

$ ./greeter.sh test wire
  ==> service up at 172.17.0.3:50051 - calling it with the java client
  OK  REPLY: hello the java client, from the python service
```

Driven on 2026-09-14. `build proto` generated `greeter_pb2.py` + `greeter_pb2_grpc.py` and
`GreeterGrpc.java` + five more; `test wire` started the Python service from the first set and called it
with a Java client built from the second.

**Nothing above was run by hand.** The service is a container and so is the client, and both are started
by the command rather than by the reader - which is this repository's own rule about CI steps applied to
a documentation page: a step that only exists in a transcript cannot be run by the person reading it.

## The contract, and why it is one file

```proto
syntax = "proto3";
package demo;
option java_package = "demo.grpc";
option java_multiple_files = true;
service Greeter { rpc Hello (HelloRequest) returns (HelloReply); }
message HelloRequest { string name = 1; }
message HelloReply { string text = 1; }
```

One tree, one `proto/greeter.proto`, two stub sets under `build/proto/`. Generated code is not source, so
neither set is committed and neither can go stale against the contract.

{{< callout type="info" >}}
An earlier draft of this chapter used **two** products with a launcher each, and it had to end by
admitting that the `.proto` was copied into both trees - one contract, two files, and nothing keeping
them equal. That is the second-source shape this repository removes everywhere else. One launcher over
one tree removes it instead of describing it.
{{< /callout >}}

## What the scaffolder does and does not do here

`support toolchain <language>` writes a `proto` command per language, and a product that wants two
languages meets something worth knowing:

```text
$ ./greeter.sh support toolchain python 3.12    python: wrote 4 command(s) - proto, deps, unit, analyse
$ ./greeter.sh support toolchain java 21        kept your own 'proto' - scaffolding never overwrites
```

**The second language keeps the first one's command.** That is the scaffolder working as designed - it
never overwrites what a product has - and it means one tree with two languages declares its generations
itself, under names that say which is which:

```yaml
build:
  commands:
    proto-python:
      task: toolchain:run
      with: { image: namely/protoc-all:1.51_2, workdir: /defs,
              argv: ["-d", "proto", "-l", "python", "-o", "build/proto/python"] }
    proto-java:
      task: toolchain:run
      with: { image: namely/protoc-all:1.51_2, workdir: /defs,
              argv: ["-d", "proto", "-l", "java", "-o", "build/proto/java"] }
    proto:
      help: "Generate the stubs for both sides of the contract."
      depends_on: [proto-python, proto-java]
```

Three declarations and one plan: `build proto` is the aggregate, and what a person types stays one
command however many languages the contract has.

## What this does not say

The run proves that both sides generate from one contract and that the generated code interoperates over
the wire. It says nothing about **versioning**: nothing here detects a renumbered field, and a breaking
change to the contract would produce two stub sets that build and fail at run time. A contract check
belongs under `test` and there is none yet - it is named as open work in
[simplon#238](https://github.com/marcozwyssig/simplon/issues/238) rather than implied by this page.

It also says nothing about two *repositories*. Everything above is one tree. A contract shared across
repositories needs a home neither of them owns - a submodule, or a published artefact both fetch, which
is the shape [handing a package over](../handing-a-package-over/) already describes for libraries.
