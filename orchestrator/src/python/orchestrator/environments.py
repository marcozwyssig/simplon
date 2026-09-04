"""simplon's named, isolated deployment environments. The matrix itself lives in simplon.yaml
(the `environments:`/`default:` sections); this adapter supplies the three things that are simplon's
own and lets simplon.environments.Provider do the rest.

  * the process variable the active environment rides in (set by simplon.cli.main);
  * the backends this product IMPLEMENTS - `local` today; add your cloud backend (e.g. a VM-per-site
    provider) here and gate a command on it with PROVIDER.require_backend();
  * how this product's shim spells a command, so an error message can hand an operator a line that
    actually dispatches.

PROVIDER satisfies the simplon.cli EnvironmentProvider protocol structurally, so nothing named is
imported by the kernel - the coupling flows product -> kernel, never the reverse.
"""
from __future__ import annotations

from simplon.environments import LOCAL, Provider

ENV_VAR = "SIMPLON_ENV"

PROVIDER = Provider(ENV_VAR, shim="./simplon.sh", valid_backends=(LOCAL,))
