# si#522: ship simplon's firn M2 so a product can validate its exported manifest model

Status: approved decisions (Marco, 2026-10-24), builder's calls marked.
Ticket: https://github.com/marcozwyssig/simplon/issues/522

## Intent

A product can export its manifest as a firn model (`support:model`, si#346), but it cannot check that model:
the export names simplon's M2 packages, and nothing ships them. netctl is to adopt firn for its own model
and for its exported manifest (Marco, 2026-10-23), and the second half waits on this ticket.

Success: a product with only the simplon wheel (or the kernel image) runs one command and `firn validate`
is green over its fresh export, red with firn's own message over a broken one.

## Measured (2026-10-24, firn image v0.2.0, the export of `simplon.yaml`)

- **The export needs four packages**: `simplon.manifest`, `simplon.pipeline`, `simplon.catalogue`,
  `simplon.vocabulary`. With all four beside the export, `firn validate` is rc 0. Without `catalogue`:
  `error[E200]: cannot resolve 'simplon.catalogue.docs_reference'`. Without `vocabulary`:
  `error[E200]: cannot resolve 'simplon.vocabulary.release'`. `architecture` and `components` are not
  referenced (they describe simplon's own code) and stay out.
- **A broken export is red**: `area = simplon.pipeline.Area.nosuch` gives rc 1,
  `error[E200]: cannot resolve 'simplon.pipeline.Area.nosuch'` with file and line.
- **How firn v0.2.0 finds a library**, three routes tried:
  - a path dependency, `[dependencies] simplon = { path = "<dir>" }`, where `<dir>` holds its own
    `firn.toml` and `model/`: rc 0. Lib directory missing: `E107 ... has no firn.toml`, rc 3. Lib with an
    empty model: E200 on `simplon.manifest.Product`. The dependency path may lie outside the project root.
  - a jar staged by `firn library` and passed with `validate -cp`: rc 0.
  - an absolute folder in `model = [...]`: refused, `E104 ... leaves the project directory`, rc 3.
- **Correction to si#371 and `profiles.py`'s comment**: firn v0.2.0 has `--project=<path>` and `-cp`; the
  sentence "firn ... takes no project option" is stale.

## Decisions (Marco, 2026-10-24)

1. **The M2 travels as package data inside the `simplon` wheel.** Its version is the version of the kernel
   that exports. The wheel's top level stays `simplon` plus its `.dist-info` (si#378, `test_wheel`). The
   kernel image installs the wheel, so it carries the M2 too. Rejected: an OCI artifact (a second pin and
   a second publish that can drift); the image only (a wheel-only product could not validate).
   Reopens if: a non-Python consumer needs the M2 without the wheel.
2. **The kernel builds a throwaway check project.** A new catalogue task stages, below the product's
   build output, a firn project holding the fresh export and a path dependency on the shipped M2, and
   runs `firn validate` there in the pinned firn image. The product's own `firn.toml` is never read or
   touched (netctl will have its own model). Rejected: a jar on `-cp` (firn's library format, adr/0025 and
   0028, but a zip step and a marker whose fingerprint rules, E119/E180, are still moving); a dependency
   the product writes into its own `firn.toml` (the wheel's path differs per machine and container).
   Reopens if: firn stops accepting a path dependency, or a product wants simplon's M2 in its own model.
3. **The M2 is versioned with the kernel.** Export and M2 always come from the same kernel, so the export
   has no version skew. Renaming or removing a type, attribute or literal in the four packages is a
   breaking change named in the release notes; there is no deprecation period. It is listed on
   `with-what/surface.md` as a promise to products, beside `model.task` (si#473). Reopens if: a product
   writes its own model against `simplon.*` types and asks for a grace period.

4. **simplon runs the command on itself** (Marco, 2026-10-24): `simplon.yaml` declares
   `test manifest-model` beside `test model` and adds it to `test all`, so CI checks the shipped route,
   the M2 from the installed package, and not only the tree. `test model` stays: it also checks
   `architecture` and `components`, and the committed export with its `generated:` staleness gate stays.
5. **No guard on the M2 promise** (Marco, 2026-10-24): `surface.md` and the release notes carry it, no test
   compares names against a baseline. Reopens if: the first M2 change that breaks a product.

## What gets built

- **One source.** The four packages are not copied in the tree. *Builder's call (mine):* move
  `manifest/`, `pipeline/`, `catalogue/`, `vocabulary/` from `src/firn/model/simplon/` to a package-data
  directory under `src/simplon/` (proposed: `src/simplon/m2/simplon/<package>/`), and give `src/firn.toml`
  both model folders, `model = ["firn/model", "simplon/m2"]` (both inside firn's root, `src/`). simplon's
  own `test model`, `build model` and `test generated` must stay green unchanged in behaviour.
  `vocabulary/kinds.firn` is hand-written, and firn generates from it (the catalogue's `kinds:`,
  `artifactschema.py`, `kinds.md`); those outputs and several tests name its source path, so the move is a
  regenerate-and-commit change to their headers and constants, not a change in behaviour. `architecture/` and `components/` stay
  where they are. If the move fights firn (for example a generated file firn writes by package path),
  the fallback is a build-time copy into the wheel, with a test that the copy equals the source.
- **A catalogue task**, proposed key `test:manifest-model` (the product names the command; the
  `support toolchain firn` scaffold places it as `test manifest-model`, beside `test model` and
  `build model`). It:
  1. exports the manifest fresh, exactly as `support:model` does, so a stale export on disk cannot be
     validated green (*my call*; the ticket's acceptance reads "runs support manifest model and then test
     model", and this folds the two into one verdict);
  2. writes, below the build output, a project: `firn.toml` (`name`, `model = ["model"]`,
     `[dependencies] simplon = { path = "<m2 dir>" }`), `model/<product>.firn`, and the M2 directory with
     its own `firn.toml` and the four packages copied from the installed wheel, so the container sees
     them on the product mount;
  3. runs `firn validate` there through `toolchain:run`'s machinery with the firn image the product
     declares (its `image` parameter, as `test model` takes it; no kernel default pin), `network: none`;
  4. passes firn's rc through: 0 clean, 1 model wrong, 2 usage, 3 no project, 70 firn's own fault. A
     manifest that does not load or export is rc 1 with the reason, never a skipped green.
- **Docs**: `with-what/phases.md` (the paragraph ending "shipping the M2 for that is not done yet") says
  what ships and how to run it; `how/manifest.md` gets the command; `surface.md` the promise; the stale
  "no project option" comment in `profiles.py` is corrected.
- **Census**: the task refuses nothing at load time, so no new census entry is expected; if one appears,
  classify it.

## Tests (each seen red first)

- `test_wheel`: the built wheel carries the four packages' `.firn` files at the package-data path; its
  top level is still `simplon` plus `.dist-info`; `architecture` and `components` are absent.
- End-to-end with the real firn image (skipped without docker, like `test_manifestmodel_e2e.py`): over an
  installed wheel, the task is green over simplon's own manifest and over the eight reachable fixture
  manifests; red with rc 1 and firn's E200 over a deliberately broken export; rc 1 with the load reason
  over a manifest that does not load.
- The check project never touches a `firn.toml` at the product root (a sentinel file stays byte-identical).
- simplon's own `test model`, `build model` and `test generated` unchanged.

## Non-goals

- Validating a product's own model (that is its `test model`, which works today).
- A jar, an OCI artifact, a Maven publication.
- Shipping `architecture` or `components`.
- The netctl ticket: after this ships in a release, with Marco's OK (outward).

## Left to the builder

Directory and module names, how the M2 is located inside the installed package (`importlib.resources`),
where under the build output the check project lives, and whether the export step calls `manifestmodel`
directly or the `support:model` body.
