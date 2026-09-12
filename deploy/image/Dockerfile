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
# WHAT IS DELIBERATELY NOT IN IT. The docker CLI and oras, which the kernel does use. Both are already
# PROVIDED at runtime rather than demanded (`simplon.docker.ensure_docker` with
# DELIVERY_DOCKER_BOOTSTRAP, `simplon.oras.ensure_oras`), so baking them in would create a second,
# older copy of a tool the kernel already knows how to get, and the version in the layer would be the
# one nobody bumps. si#201 is the ticket that can MEASURE whether a container that fetches them on every
# run is worth a layer; it should decide that with a number rather than this file with a guess.
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
 && apt-get install --yes --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

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
