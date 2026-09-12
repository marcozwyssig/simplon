# The simplon KERNEL as a container image (si#200), for the second route si#201 builds on: a machine with
# bash and docker runs a product without a host Python.
#
# WHAT IS IN IT, AND WHY THAT IS THE WHOLE ANSWER. The kernel and nothing of any product. si#121 measured
# the wall: no prebuilt image can carry a product's wheels, because a product's suites import the
# product's own dependencies and those are known only in the product's checkout. So this image carries
# what is the same for everybody - the kernel, its runtime dependencies and the git it shells out to -
# and a product's tree arrives as a bind mount at /src. si#201 inherits that boundary; it is the reason
# the launcher's container route mounts the checkout instead of building an image per product.
#
# THE DOCKER CLI IS IN IT, AND ORAS IS NOT, and si#201 measured the difference rather than reasoning it.
# si#200 left both out on the argument that the kernel already knows how to get them
# (`simplon.docker.ensure_docker` with DELIVERY_DOCKER_BOOTSTRAP, `simplon.oras.ensure_oras`) and that a
# baked copy would be the one nobody bumps. The numbers split the two:
#
#   * DOCKER. Every task this kernel runs is a `docker run`, so on the container route the CLI is not an
#     optional tool but the route's premise. Fetched at runtime it costs 84 MB and 15.0 s on first use
#     (measured on this box, download.docker.com static bundle) and needs egress from a container whose
#     selling point is "a machine with bash and docker". It also changed VERDICTS: running simplon's own
#     `test all` through this image, three tests SKIPPED with "no docker daemon here" and one FAILED
#     with `FileNotFoundError: 'docker'` where the venv route has neither - four differences between two
#     routes that are required to be indistinguishable. In the layer it is 41 MB.
#   * ORAS. Reached only by `release:artifact` and the read-back in `release:image`, provisioned by a
#     gate that works, and it changed no verdict at all in the same run. It stays out.
#
# The "version nobody bumps" objection is answered rather than accepted: the version installed below is
# `simplon.docker.DOCKER_CLI_VERSION`, the number the kernel's own bootstrap already pins, and
# tests/test_own_image.py holds the two against each other. One source, two consumers.
#
# THE INTERPRETER IS THE ONE THE GATE PROVES. simplon.yaml declares python 3.12 for its own CI job, so
# that is the interpreter every push is measured on and the one this image runs. `requires-python` is
# >=3.11, so the image is a statement about what is tested, not about what is possible.
#
# THE VERSION IS DERIVED IN HERE, ONCE. setuptools-scm reads the git tag, which is why the build context
# carries `.git` (see .dockerignore, which excludes the venv and the build tree and keeps that one
# directory on purpose). `simplon.tasks.image` passes VERSION and REVISION as build arguments, and they
# are LABELS here rather than a second version input: pip must not be told a number that git already
# knows, or an image could be tagged 0.13.0 and carry 0.12.0.
#
# The cost of that decision is stated rather than discovered: the image can only be built from a real
# checkout. A linked git worktree cannot build it, because its `.git` is a file naming a gitdir outside
# the context - the guard in the build stage below says so in one sentence. The alternative, passing the
# number in as SETUPTOOLS_SCM_PRETEND_VERSION, was rejected: `git describe` writes `v0.12.0-6-gf3862e6`
# and PEP 440 wants `0.12.1.dev6+gf3862e6`, so it would need a rule that rewrites the number, and a
# rewritten number is a second statement about the version - which is the thing si#200 removed.

FROM python:3.12-slim AS build

# git, because setuptools-scm shells out to it. Without it the wheel builds as the 0.1.dev1 no-tag
# sentinel and the image would carry a version nobody chose.
RUN apt-get update \
 && apt-get install --yes --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY . .

# THE CONTEXT HAS TO CARRY A REAL REPOSITORY, and this says so before setuptools-scm does. Measured in a
# linked git worktree, which is how several agents work in this repository at once: there `.git` is a
# FILE holding the path of a gitdir that lives under the MAIN checkout, so it is copied into the context
# and points at nothing. The build then dies six lines into `python -m build` with "setuptools-scm was
# unable to detect version for /build", which is a true sentence about a cause the reader cannot see
# from here. Three lines to name it instead.
RUN test -d .git || { \
      echo "the build context carries no git repository, so the kernel's version cannot be derived."; \
      echo "  a LINKED GIT WORKTREE cannot build this image: its .git is a file naming a gitdir that"; \
      echo "  lives under the main checkout and is therefore not in the build context."; \
      echo "  build from the main checkout, or from a clone of this branch."; \
      exit 1; \
    } >&2

RUN pip install --no-cache-dir build \
 && python -m build --wheel --outdir /wheels

FROM python:3.12-slim

ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="simplon" \
      org.opencontainers.image.description="The simplon kernel: one manifest, one CLI, one gate." \
      org.opencontainers.image.source="https://github.com/marcozwyssig/simplon" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.revision="$REVISION"

# git at RUNTIME too, and for three kernel paths rather than for tidiness: the release-notes guard reads
# the merge range, `release:tag` refuses a commit main does not carry, and this task's own provenance
# runs `git describe` over the mounted product tree.
RUN apt-get update \
 && apt-get install --yes --no-install-recommends ca-certificates curl git \
 && rm -rf /var/lib/apt/lists/*

# THE DOCKER CLIENT, and only the client. The bundle also carries the engine binaries, which are useless
# here: this image never runs a daemon, it talks to the host's through the socket the launcher mounts -
# the docker-outside-of-docker shape `simplon.docker` was written for. The version is the one
# `simplon.docker.DOCKER_CLI_VERSION` pins, so the runtime bootstrap and this layer cannot disagree.
#
# NOT CHECKSUM-VERIFIED, and that is a gap rather than an oversight (found on review of si#201). The
# tarball is pinned by version and fetched over TLS from download.docker.com, and nothing here compares
# it against a published SHA256. The same gap already exists one module away, in
# `simplon.docker._fetch_static_cli`, which is the runtime half of the very same fetch - so closing it
# HERE alone would leave this kernel keeping a rule in one of the two places it argues for it, which is
# the shape si#47 exists to refuse. The fix is one digest table beside DOCKER_CLI_VERSION used by both,
# and it is a ticket rather than a line in this file.
ARG DOCKER_CLI_VERSION=29.6.1
RUN arch="$(uname -m)" \
 && case "$arch" in x86_64|amd64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; \
      *) echo "no static docker CLI for $arch" >&2; exit 1 ;; esac \
 && curl -fsSL "https://download.docker.com/linux/static/stable/$arch/docker-$DOCKER_CLI_VERSION.tgz" \
      -o /tmp/docker.tgz \
 && tar -xzf /tmp/docker.tgz -C /usr/local/bin --strip-components=1 docker/docker \
 && rm /tmp/docker.tgz \
 && docker --version

COPY --from=build /wheels/*.whl /tmp/wheels/
RUN pip install --no-cache-dir /tmp/wheels/*.whl \
 && rm -rf /tmp/wheels

# WHERE A PRODUCT'S TREE IS EXPECTED. /src, matching every `docker run -v <root>:/src` this kernel already
# writes for its own toolchain containers, so the convention is one convention.
WORKDIR /src

# NO ENTRYPOINT, and that is a decision si#201 depends on. The `simplon` console script is the SCAFFOLDER
# (`simplon init`); a product's own CLI is reached as `python -m orchestrator` with its block on
# PYTHONPATH, which is a different argv entirely. An ENTRYPOINT of either would make the other an
# override, so the image commits to neither and the launcher says what it means.
CMD ["simplon", "--help"]
