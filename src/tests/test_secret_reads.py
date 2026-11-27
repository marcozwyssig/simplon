"""si#839 (si#833 design note, 6.2 and 6.3): no secret value bypasses `secrets`, by reading or by printing.

`test_secret_census.py` proves that every name a reader DERIVES has a role (6.1) and that the sinks it knows
about redact (6.4). Neither can see a site nobody listed: a reader that calls `os.environ[...]` directly gets
a value `redact` and `check_argv` never learn about, and a new output path that does not go through the
wrapped streams or a self-redacting file sink prints whatever it is handed. Both are measured here from the
kernel's own source, by walking its syntax trees, so the population is derived and not listed.

6.2, EVERY READ OF THE ENVIRONMENT. The walk finds every read of one variable out of the process
environment in `src/simplon`: `os.getenv(K)`, and `.get(K)`, `.pop(K)` and `[K]` on `os.environ` or on a
mapping that came from it - a local assigned from an expression holding `os.environ`, or a parameter some
call site hands `os.environ` (or such a local) to, followed across modules to a fixpoint. `K` is resolved
where it is static: a literal, a module constant (this module's or imported), or a loop variable over a
constant tuple. Then:

- a read through `secrets.read` is the declaration and the registration at once, and needs nothing else;
- a read that only TESTS the value (`if env.get(K)`, `not env.get(K)`, a comprehension's `if`) hands the
  value nowhere, so it cannot reach a sink and is not ruled on;
- every other resolved name has to be plain: the launcher says so (`launcherenv.FORWARDED_ROLES`) or `PLAIN`
  below does, with what it holds. A name in neither is red, so a new direct read - of a secret or of
  anything nobody classified yet - cannot join quietly. `PLAIN` may not name a secret some reader holds,
  and an entry nothing reads any more is red too;
- a name that cannot be resolved is named in `READS_DYNAMIC` with the reason, exactly, both ways.

6.3, EVERY OUTPUT PRIMITIVE. The walk finds every call that writes text out of the process: `print`,
`.write`/`.writelines` on a stream, `os.write`, `Path.write_text`/`write_bytes`, `json.dump`/`yaml.dump` to
a stream, a `logging` handler, and every touch of `sys.__stdout__`/`sys.__stderr__`. A call reaches a
redacting sink when it writes to the wrapped `sys.stdout`/`sys.stderr` (`print` without `file=`, or with
one of the two) or when its own text is wrapped in `secrets.redact` (`steplog.write`, the wrapper itself).
Every other site is named in `UNREDACTED`, keyed by module and function, with the reason its text cannot
hold a secret value or where it is redacted instead. A new one is red until somebody says which it is.

A LIBRARY THAT DRAWS THE TERMINAL ITSELF is the one output path no walk of this source can see: Textual
draws to `sys.__stderr__`, past the wrapper. The walk found that by its own `rlog.write` sites, and on main
the details pane showed a step's secret in clear and `c` copied it (si#839, seen red). So every module
importing such a library is named in `OWNS_THE_TERMINAL`, and the TUI pane and its clipboard redact.

WHAT THE WALK CANNOT SEE, said here rather than left to be found. A call through a method on an object
(`self.f(os.environ)`) is not followed, so a parameter it hands the environment to is not an alias; a
mapping copied into a dataclass field and read later is not either. A secret that never was an environment
variable (the token `gh auth token` prints, the Nexus password read from its container) is not a read
this walk rules on; those two are registered where they are taken, held by their canaries in
`test_secret_census.py`. A child process started with `capture=False` writes to the inherited descriptor (the
module head of `secrets` records that limit). A write through a stream handle the walk cannot type
(`handle.write(...)` on a file object) IS counted: every `.write` that is not on `sys.stdout`/`sys.stderr`,
`self` or a kernel module is a site, so this limit errs towards naming too much.

RED WHEN THERE IS NOTHING. Every population assertion is paired with how many sites it ruled on.

AAA; the name states the behaviour under test.
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path
from typing import NamedTuple

from simplon.kernel import secrets
from simplon.manifest import launcherenv

SRC = Path(__file__).resolve().parents[1] / "simplon"


# --- the module index -------------------------------------------------------------------------------------


def _dotted(path: Path) -> str:
    parts = list(path.relative_to(SRC.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class _Module:
    """One module's tree, its string constants, what it imports from `simplon`, and its functions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.dotted = _dotted(path)
        self.tree = ast.parse(path.read_text(encoding="utf-8"))
        self.constants: dict[str, tuple[str, ...]] = {}
        for node in self.tree.body:
            target, value = None, None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
                target, value = node.target.id, node.value
            if target:
                items = value.elts if isinstance(value, (ast.Tuple, ast.List)) else [value]
                strings = tuple(i.value for i in items if isinstance(i, ast.Constant) and isinstance(i.value, str))
                if strings and len(strings) == len(items):
                    self.constants[target] = strings
        #: alias -> ("module", dotted) or ("name", dotted, name)
        self.imports: dict[str, tuple[str, ...]] = {}
        package = self.dotted if path.name == "__init__.py" else self.dotted.rpartition(".")[0]
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    anchor = package.split(".")
                    anchor = anchor[:len(anchor) - (node.level - 1)]
                    base = ".".join([*anchor, base] if base else anchor)
                if not base.startswith("simplon"):
                    continue
                for alias in node.names:
                    full = f"{base}.{alias.name}"
                    kind = ("module", full) if full in _paths() else ("name", base, alias.name)
                    self.imports[alias.asname or alias.name] = kind
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("simplon.") and alias.asname:
                        self.imports[alias.asname] = ("module", alias.name)
        self.functions: dict[str, list[ast.AST]] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions.setdefault(node.name, []).append(node)


@functools.lru_cache(maxsize=None)
def _paths() -> dict[str, Path]:
    return {_dotted(path): path for path in sorted(SRC.rglob("*.py"))}


@functools.lru_cache(maxsize=None)
def _module(dotted: str) -> _Module:
    return _Module(_paths()[dotted])


def _modules() -> list[_Module]:
    return [_module(dotted) for dotted in _paths()]


def _strings(module: _Module, node: ast.AST) -> tuple[str, ...]:
    """The strings `node` stands for when that is static, else ()."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.Name):
        if node.id in module.constants:
            return module.constants[node.id]
        imported = module.imports.get(node.id)
        if imported and imported[0] == "name" and imported[1] in _paths():
            return _module(imported[1]).constants.get(imported[2], ())
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        imported = module.imports.get(node.value.id)
        if imported and imported[0] == "module" and imported[1] in _paths():
            return _module(imported[1]).constants.get(node.attr, ())
    if isinstance(node, (ast.Tuple, ast.List)):
        parts = [_strings(module, element) for element in node.elts]
        return tuple(s for part in parts for s in part) if parts and all(parts) else ()
    return ()


def _scopes(module: _Module) -> list[ast.AST]:
    return [module.tree, *(f for functions in module.functions.values() for f in functions)]


def _own_nodes(scope: ast.AST):
    """The nodes of `scope` that are not inside a nested `def` (which is a scope of its own). A lambda's
    body is its enclosing function's."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.extend(ast.iter_child_nodes(node))


# --- 6.2: the environment reads ---------------------------------------------------------------------------


def _is_os_environ(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "environ"
            and isinstance(node.value, ast.Name) and node.value.id == "os")


def _is_environ(node: ast.AST, aliases: set[str] | frozenset[str]) -> bool:
    """`node` evaluates to the environment mapping itself (or a copy): `os.environ`, a local holding it,
    `dict(...)`/`.copy()` of one, `{**env, ...}`, or either side of `a if c else b` / `a or b`."""
    if _is_os_environ(node) or (isinstance(node, ast.Name) and node.id in aliases):
        return True
    if isinstance(node, ast.IfExp):
        return _is_environ(node.body, aliases) or _is_environ(node.orelse, aliases)
    if isinstance(node, ast.BoolOp):
        return any(_is_environ(value, aliases) for value in node.values)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "dict" and node.args:
            return _is_environ(node.args[0], aliases)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "copy":
            return _is_environ(node.func.value, aliases)
    if isinstance(node, ast.Dict):
        return any(key is None and _is_environ(value, aliases) for key, value in zip(node.keys, node.values))
    return False


def _callee(module: _Module, func: ast.AST) -> list[ast.AST]:
    """The function definitions a call can reach by name: this module's, or an imported module's."""
    if isinstance(func, ast.Name):
        if func.id in module.functions:
            return module.functions[func.id]
        imported = module.imports.get(func.id)
        if imported and imported[0] == "name" and imported[1] in _paths():
            return _module(imported[1]).functions.get(imported[2], [])
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        imported = module.imports.get(func.value.id)
        if imported and imported[0] == "module" and imported[1] in _paths():
            return _module(imported[1]).functions.get(func.attr, [])
    return []


@functools.lru_cache(maxsize=None)
def _aliases() -> dict[int, frozenset[str]]:
    """id(scope) -> the local names in that scope that hold the process environment, to a fixpoint over
    the parameters call sites hand it to."""
    handed: dict[int, set[str]] = {}
    while True:
        out: dict[int, frozenset[str]] = {}
        grew = False
        for module in _modules():
            for scope in _scopes(module):
                names = set(handed.get(id(scope), ()))
                nodes = list(_own_nodes(scope))
                changed = True
                while changed:
                    changed = False
                    for node in nodes:
                        targets, value = (), None
                        if isinstance(node, ast.Assign):
                            targets, value = node.targets, node.value
                        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                            targets, value = (node.target,), node.value
                        if value is None or not _is_environ(value, names):
                            continue
                        for target in targets:
                            if isinstance(target, ast.Name) and target.id not in names:
                                names.add(target.id)
                                changed = True
                out[id(scope)] = frozenset(names)
                for node in nodes:
                    if not isinstance(node, ast.Call):
                        continue
                    for callee in _callee(module, node.func):
                        params = [a.arg for a in (*callee.args.posonlyargs, *callee.args.args)]
                        if params and params[0] in ("self", "cls"):
                            params = params[1:]
                        passed = list(zip(params, node.args))
                        passed += [(k.arg, k.value) for k in node.keywords if k.arg]
                        for param, value in passed:
                            if _is_environ(value, names) and param not in handed.setdefault(id(callee), set()):
                                handed[id(callee)].add(param)
                                grew = True
        if not grew:
            return out


class _Read(NamedTuple):
    module: str
    function: str
    names: tuple[str, ...]      # () when the name is not static
    through: bool               # read through `secrets.read`
    presence: bool              # only asked whether it is set: the value goes nowhere


def _loop_strings(module: _Module, scope: ast.AST, name: str) -> tuple[str, ...]:
    """The strings a loop variable takes when it iterates a constant tuple."""
    for node in ast.walk(scope):
        generators = [node] if isinstance(node, (ast.For, ast.comprehension)) else []
        for generator in generators:
            if isinstance(generator.target, ast.Name) and generator.target.id == name:
                return _strings(module, generator.iter)
    return ()


def _key(module: _Module, scope: ast.AST, node: ast.AST) -> tuple[str, ...]:
    found = _strings(module, node)
    if not found and isinstance(node, ast.Name):
        found = _loop_strings(module, scope, node.id)
    return found


def _is_secrets_read(module: _Module, func: ast.AST) -> bool:
    if not (isinstance(func, ast.Attribute) and func.attr == "read" and isinstance(func.value, ast.Name)):
        return False
    return module.imports.get(func.value.id) == ("module", "simplon.kernel.secrets")


def _presence(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """`node` is only tested for truth - `if env.get(K)`, `not env.get(K)`, a comprehension's `if` - so
    the value it reads goes nowhere and cannot reach a sink."""
    child, parent = node, parents.get(node)
    while isinstance(parent, ast.BoolOp):
        child, parent = parent, parents.get(parent)
    if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
        return True
    if isinstance(parent, (ast.If, ast.While, ast.IfExp, ast.Assert)) and parent.test is child:
        return True
    return isinstance(parent, ast.comprehension) and child in parent.ifs


@functools.lru_cache(maxsize=None)
def _reads() -> tuple[_Read, ...]:
    aliases = _aliases()
    out: list[_Read] = []
    for module in _modules():
        parents = {child: node for node in ast.walk(module.tree) for child in ast.iter_child_nodes(node)}
        for scope in _scopes(module):
            names = aliases.get(id(scope), frozenset())
            function = getattr(scope, "name", "<module>")
            for node in _own_nodes(scope):
                key = None
                through = False
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    base = node.func.value
                    if node.func.attr == "getenv" and isinstance(base, ast.Name) and base.id == "os" and node.args:
                        key = node.args[0]
                    elif (node.func.attr in ("get", "pop") and node.args
                          and (_is_os_environ(base) or (isinstance(base, ast.Name) and base.id in names))):
                        key = node.args[0]
                    elif _is_secrets_read(module, node.func) and node.args:
                        key, through = node.args[0], True
                elif (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load)
                      and (_is_os_environ(node.value)
                           or (isinstance(node.value, ast.Name) and node.value.id in names))):
                    key = node.slice
                if key is not None:
                    out.append(_Read(module.dotted, function, _key(module, scope, key), through,
                                     _presence(node, parents)))
    return tuple(out)


_SWITCH = "a switch the kernel or its launcher sets"
_PATH = "a path"
_DOCKER = "docker's own client setting: a socket address, a context name or a config directory"
_ACTIONS = "set by GitHub Actions: an identifier, a URL or a ref, never a credential"
_LAUNCHER = "the launcher's own parameter, set by the kernel's rendered launcher: a path, a name or a pin"

#: Every name the kernel reads DIRECTLY out of its environment that is not a credential, and what it holds.
#: `launcherenv.FORWARDED_ROLES` carries the launcher's own plain names; these are the rest. An entry is a
#: statement that the value may be printed, so only a switch, a path, an address or an identifier belongs
#: here. A credential is read through `secrets.read` instead, which needs no entry.
PLAIN: dict[str, str] = {
    "COLIMA_PROFILE": _DOCKER,
    "DELIVERY_DEGRADED_FILE": _PATH,
    "DELIVERY_DIR_CACHE": _PATH,
    "DELIVERY_DIR_CACHE_HOST": _PATH,
    "DELIVERY_DIST_CACHE": _PATH,
    "DELIVERY_DOCKER_BOOTSTRAP": _SWITCH,
    "DELIVERY_ENV_PASS": "the launcher's list of forwarded NAMES, never their values",
    "DELIVERY_ENVIRONMENT": "the selected environment's name",
    "DELIVERY_HOST_ROOT": _PATH,
    "DELIVERY_MANIFEST": _PATH,
    "DELIVERY_MOUNT_ROOT": _PATH,
    "DELIVERY_PRODUCT_ROOT": _PATH,
    "DELIVERY_ROUTE": _SWITCH,
    "DELIVERY_VERBOSE": _SWITCH,
    "DOCKER_CONFIG": _DOCKER,
    "DOCKER_CONTEXT": _DOCKER,
    "DOCKER_HOST": _DOCKER,
    "GITHUB_ACTIONS": _ACTIONS,
    "GITHUB_ACTOR": _ACTIONS,
    "GITHUB_API_URL": _ACTIONS,
    "GITHUB_REF": _ACTIONS,
    "GITHUB_REPOSITORY": _ACTIONS,
    "GITHUB_SERVER_URL": _ACTIONS,
    "GITHUB_USERNAME": "the account name a registry login is made as",
    "GIT_CONFIG_COUNT": "git's count of `GIT_CONFIG_*` pairs",
    "HOME": _PATH,
    "LAUNCH_IMAGE_PIN": _LAUNCHER,
    "LAUNCH_ORCH_DIR": _LAUNCHER,
    "NEXUS_CLEANUP_DAYS": "a number of days",
    "NEXUS_HTTP_PORT": "a port",
    "PATH": _PATH,
    "PORTAINER_ENDPOINT_ID": "Portainer's endpoint number",
    "PORTAINER_STACK": "a stack name",
    "PORTAINER_URL": "the URL half, plain by `portainer.target_roles`",
    "RUNNER_TOOL_CACHE": _PATH,
    "SIMPLON_CARRIER_SSH_KEY": "the RETIRED name, which held a key's PATH (si#819); read only to say so",
    "SIMPLON_MAX_PARALLEL": "a number",
    "SIMPLON_NO_TUI": _SWITCH,
    "SIMPLON_PLUGIN_STEP": _SWITCH,
    "SIMPLON_SETUP_FAILED": _PATH,
    "SUDO": "the command that escalates, `sudo` by default",
    "XDG_CACHE_HOME": _PATH,
}

#: Reads whose name the walk cannot resolve, by (module, function), with what the name is and why its
#: value cannot reach a sink unregistered.
READS_DYNAMIC: dict[tuple[str, str], str] = {
    ("simplon.adapters.credentials", "ask_for_name"):
        "a credential's USER half, which `credentials.variable_roles` declares plain",
    ("simplon.adapters.credentials", "ask_for_secret"):
        "the variable is only tested for being set; when it is, its value is read through `secrets.read`",
    ("simplon.adapters.credentials", "credential"):
        "the USER half (plain by `variable_roles`); the password half is read through `secrets.read`",
    ("simplon.adapters.credentials", "missing_password_variable"):
        "both halves of a pair, only tested for being set (`.strip()` of the value, never kept)",
    ("simplon.adapters.labegress", "enabled"): "a switch the product names: `0` turns egress hardening off",
    ("simplon.adapters.labinstance", "resolve"): "the product's lab-instance variable: an instance name",
    ("simplon.adapters.nexusproxy", "api_base"): "the manifest's `base_url_env`: the Nexus base URL",
    ("simplon.adapters.portainer", "_ensure_registry"):
        "both halves of the GHCR pair, only tested for being set; the pair is read through "
        "`credentials.credential`",
    ("simplon.adapters.portainer", "from_carrier"):
        "copies `<prefix>_URL`/`_TOKEN` onto `PORTAINER_URL`/`_TOKEN` in a local copy; the token was read "
        "through `secrets.read` two lines above, so its value is registered",
    ("simplon.kernel.secrets", "read"): "the reader itself",
    ("simplon.kernel.secrets", "register_present"): "the registration itself",
    ("simplon.manifest.environments", "default"): "`ENV_VAR`, which names the selected environment",
    ("simplon.manifest.launcherenv", "withheld"):
        "the forwarded `env: pass:` names, unset and put back; the values never leave `os.environ`",
    ("simplon.tasks.env", "_active"): "the manifest's `env_var:`, which names the active environment",
}


def _secret_names() -> set[str]:
    """Every name some reader holds as a secret, statically: the launcher's, and every literal name read
    through `secrets.read`."""
    forwarded = {name for name, role in launcherenv.FORWARDED_ROLES.items() if role == secrets.SECRET}
    return forwarded | {name for read in _reads() if read.through for name in read.names}


def _direct() -> list[_Read]:
    """The reads that hand a value on without `secrets.read`: neither through it nor a presence test."""
    return [read for read in _reads() if not read.through and not read.presence]


def test_every_name_the_kernel_reads_directly_is_plain():
    # arrange
    plain = {name for name, role in launcherenv.FORWARDED_ROLES.items() if role == secrets.PLAIN} | set(PLAIN)
    resolved = [read for read in _direct() if read.names]

    # act
    unplain = sorted({f"{read.module}.{read.function} reads {name}"
                      for read in resolved for name in read.names if name not in plain})

    # assert
    assert not unplain, ("a direct read of a name nobody declared plain - a credential goes through "
                         "`secrets.read`, anything else gets a `PLAIN` entry saying what it holds: "
                         + "; ".join(unplain))
    assert len(resolved) > 50, f"the walk resolved only {len(resolved)} direct reads: it is broken"


def test_every_read_the_walk_cannot_resolve_is_named():
    # act
    unresolved = {(read.module, read.function) for read in _direct() if not read.names}

    # assert
    assert sorted(unresolved - set(READS_DYNAMIC)) == [], "a read of a name the walk cannot resolve"
    assert sorted(set(READS_DYNAMIC) - unresolved) == [], "a READS_DYNAMIC entry the walk no longer finds"


def test_no_name_declared_plain_is_held_as_a_secret_and_none_is_stale():
    # arrange
    read_directly = {name for read in _direct() for name in read.names}

    # act
    contradicted = sorted(set(PLAIN) & _secret_names())
    stale = sorted(set(PLAIN) - read_directly)
    doubled = sorted(set(PLAIN) & set(launcherenv.FORWARDED_ROLES))

    # assert
    assert not contradicted, f"declared plain here and read as a secret elsewhere: {contradicted}"
    assert not stale, f"a PLAIN entry nothing reads directly any more: {stale}"
    assert not doubled, f"the launcher already gives these a role: {doubled}"
    assert {"GITHUB_TOKEN", "PORTAINER_TOKEN", "SIMPLON_STATE_PASSPHRASE"} <= _secret_names()


# --- 6.3: the output primitives ---------------------------------------------------------------------------


def _is_sys(node: ast.AST, *attributes: str) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr in attributes
            and isinstance(node.value, ast.Name) and node.value.id == "sys")


def _redacts(node: ast.AST) -> bool:
    """`node`'s arguments hold a `secrets.redact(...)` call (bare `redact(...)` inside `secrets` itself):
    the text is redacted where it is written."""
    def is_redact(func: ast.AST) -> bool:
        if isinstance(func, ast.Name):
            return func.id == "redact"
        return (isinstance(func, ast.Attribute) and func.attr == "redact"
                and isinstance(func.value, ast.Name) and func.value.id == "secrets")
    return any(isinstance(n, ast.Call) and is_redact(n.func) for n in ast.walk(node))


class _Sink(NamedTuple):
    module: str
    function: str
    primitive: str
    redacted: bool
    line: int


def _primitive(module: _Module, node: ast.AST) -> str | None:
    """What output primitive `node` is, or None when it writes nothing out of the process, writes to the
    wrapped `sys.stdout`/`sys.stderr`, or calls a kernel function (`steplog.write`), whose own body is
    walked, or the object's own method (`self.write`), which is walked as a function of its own."""
    if _is_sys(node, "__stdout__", "__stderr__"):
        return f"sys.{node.attr}"
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name) and func.id == "print":
        target = next((k.value for k in node.keywords if k.arg == "file"), None)
        return None if target is None or _is_sys(target, "stdout", "stderr") else "print(file=)"
    if not isinstance(func, ast.Attribute):
        return None
    base = func.value
    if func.attr == "write" and isinstance(base, ast.Name) and base.id == "os":
        return "os.write"
    if isinstance(base, ast.Name) and (base.id == "self" or module.imports.get(base.id, ("",))[0] == "module"):
        return None
    if func.attr in ("write", "writelines"):
        return None if _is_sys(base, "stdout", "stderr") else f".{func.attr}"
    if func.attr in ("write_text", "write_bytes"):
        return f".{func.attr}"
    if isinstance(base, ast.Name) and base.id in ("json", "yaml") and func.attr in ("dump", "safe_dump"):
        if len(node.args) > 1 or any(k.arg == "stream" for k in node.keywords):
            return f"{base.id}.{func.attr}"
    if isinstance(base, ast.Name) and base.id == "logging" and (func.attr.endswith("Handler")
                                                                or func.attr == "basicConfig"):
        return f"logging.{func.attr}"
    return None


@functools.lru_cache(maxsize=None)
def _sinks() -> tuple[_Sink, ...]:
    out: list[_Sink] = []
    for module in _modules():
        for scope in _scopes(module):
            function = getattr(scope, "name", "<module>")
            for node in _own_nodes(scope):
                primitive = _primitive(module, node)
                if primitive:
                    out.append(_Sink(module.dotted, function, primitive, _redacts(node), node.lineno))
    return tuple(out)


_GENERATED = ("a generated or rewritten artefact: rendered from the manifest, the kernel's templates or the "
              "product's own files; nothing in it is read from the environment")
_RECORD = "a record of the run's own facts (a digest, a reference, a URL, a verdict); no environment value"
_FETCHED = "bytes fetched from a URL or unpacked from an archive; nothing the kernel holds"
_HOST = "a host configuration file (apt, sudoers, docker's daemon or client config) built from host facts"
_HANDOVER = ("hands a secret to a child process as a file, which is how one is meant to cross (si#833): the "
             "value is the point, the file is the child's input and is removed, not output anyone reads")
_ROUTER = ("in memory: a step's capture, or the stream the router replaced; the text leaves the process only "
           "through the wrapped streams, `steplog` or the TUI pane, each of which redacts")
_MASK = ("`::add-mask::` to the REAL stdout on purpose (`secrets._mask_stream`): through the wrapper the "
         "command would read `::add-mask::***`")
_PANE = ("the TUI's details pane, whose `_SelectableLog.write` redacts every line (si#839); held by "
         "test_secret_census.test_the_tui_pane_and_its_clipboard_never_hold_a_secret_value")

#: Every output primitive whose own call does not redact, by (module, function), with why its text cannot
#: carry a secret value - or where it is redacted instead.
UNREDACTED: dict[tuple[str, str], str] = {
    ("simplon.adapters.checksum", "_write"): _RECORD,
    ("simplon.adapters.clabrender", "render_to_file"): _GENERATED,
    ("simplon.adapters.fetch", "_remember"): _RECORD,
    ("simplon.adapters.fetch", "download"): _FETCHED,
    ("simplon.adapters.gh", "_apt_install"): _HOST,
    ("simplon.adapters.githubpackages", "scoped_credentials"):
        "a scoped docker config: the caller's settings with every credential key (`_CREDENTIAL_KEYS`) removed",
    ("simplon.adapters.labhost", "_fix_docker_credstore"): _HOST,
    ("simplon.adapters.oras", "_fetch_release"): _FETCHED,
    ("simplon.cli.bootstrap", "apply_ignore_block"): _GENERATED,
    ("simplon.cli.bootstrap", "write"): _GENERATED,
    ("simplon.cli.bootstrap", "write_launchers"): _GENERATED,
    ("simplon.kernel.degraded", "add"):
        "kernel-authored notes handed between the processes of one run; `items` prints them through the "
        "wrapped stream",
    ("simplon.kernel.secrets", "_mask_stream"): _MASK,
    ("simplon.kernel.secrets", "register"): _MASK,
    ("simplon.kernel.steps", "write"): _ROUTER,
    ("simplon.kernel.verdict", "write_stamp"): _RECORD,
    ("simplon.tasks.acceptance", "document"): _GENERATED,
    ("simplon.tasks.allure", "merge_results"): "the test tools' own result files, merged into one directory",
    ("simplon.tasks.allure", "write_environment"): _RECORD,
    ("simplon.tasks.buildfiles", "_written"): _GENERATED,
    ("simplon.tasks.carrier", "_ansible"):
        "the plays, the inventory and the `!unsafe` vars file: names and manifest values (`manifest_values`); "
        "the secrets cross by `docker run -e NAME` (si#819)",
    ("simplon.tasks.carrier", "render"): _GENERATED,
    ("simplon.tasks.ciarm64", "_write_if_changed"): _HOST,
    ("simplon.tasks.cidisk", "_write_if_changed"): _HOST,
    ("simplon.tasks.ciprivileges", "_ensure_includedir"): _HOST,
    ("simplon.tasks.ciprivileges", "_write_sudoers_dropin"): _HOST,
    ("simplon.tasks.claudemd", "generate"): _GENERATED,
    ("simplon.tasks.cliref", "reference"): _GENERATED,
    ("simplon.tasks.completiongen", "write"): _GENERATED,
    ("simplon.tasks.fetchfile", "_record"): _RECORD,
    ("simplon.tasks.githubrelease", "_attached"): f"{_FETCHED}, and {_RECORD}",
    ("simplon.tasks.homebrewformula", "build"): _GENERATED,
    ("simplon.tasks.homebrewtap", "check"): _RECORD,
    ("simplon.tasks.image", "_resolver_passed_through"): _HOST,
    ("simplon.tasks.image", "_write_archive_digests"): _RECORD,
    ("simplon.tasks.image", "_write_built"): _RECORD,
    ("simplon.tasks.image", "record"): _RECORD,
    ("simplon.tasks.image", "smoke"): _RECORD,
    ("simplon.tasks.image", "write_bake"): _GENERATED,
    ("simplon.tasks.imagefile", "check"): _RECORD,
    ("simplon.tasks.manifestcheck", "stage"): _GENERATED,
    ("simplon.tasks.manifestmodel", "_write"): _GENERATED,
    ("simplon.tasks.maven", "pack"): _GENERATED,
    ("simplon.tasks.migrate", "migrate"): _GENERATED,
    ("simplon.tasks.nuget", "_env_file"): _HANDOVER,
    ("simplon.tasks.nuget", "config"): f"{_GENERATED}; the token crosses by `_env_file`, never here",
    ("simplon.tasks.releasenotes", "write"): _GENERATED,
    ("simplon.tasks.site", "_renders"): _GENERATED,
    ("simplon.tasks.taskgen", "write"): _GENERATED,
    ("simplon.tasks.toolchain", "scaffold"): _GENERATED,
    ("simplon.tasks.unittests", "_venv"): _RECORD,
    ("simplon.tasks.walk", "save_state"): _RECORD,
    ("simplon.tasks.workflowgen", "write"): _GENERATED,
    ("simplon.test_impls", "pinned_rc"): _RECORD,
    ("simplon.ui.tui", "_begin_details"): _PANE,
    ("simplon.ui.tui", "_on_line"): _PANE,
    ("simplon.ui.tui", "_render_details"): _PANE,
}

#: A library that draws the terminal itself writes past the wrapped streams, and the walk cannot see into
#: it. Every module that imports one is named here with where its output is redacted.
TERMINAL_OWNERS = ("textual",)
OWNS_THE_TERMINAL: dict[str, str] = {
    "simplon.ui.tui": "textual draws to `sys.__stderr__`; " + _PANE + ", and `copy_to_clipboard` redacts",
}


def test_every_output_primitive_redacts_or_is_named():
    # arrange
    sinks = _sinks()

    # act
    unredacted = {(sink.module, sink.function) for sink in sinks if not sink.redacted}

    # assert
    assert sorted(unredacted - set(UNREDACTED)) == [], (
        "an output primitive that does not redact: wrap its text in `secrets.redact`, or name it in "
        "UNREDACTED with why its text cannot carry a secret value")
    assert sorted(set(UNREDACTED) - unredacted) == [], "an UNREDACTED entry the walk no longer finds"
    redacted = {(sink.module, sink.function) for sink in sinks if sink.redacted}
    assert {("simplon.kernel.steplog", "write"), ("simplon.kernel.steplog", "write_run"),
            ("simplon.kernel.secrets", "write")} <= redacted, f"the known redacting sinks: {sorted(redacted)}"


def test_every_module_that_hands_the_terminal_to_a_library_is_named():
    # act
    owners = {module.dotted for module in _modules() for node in ast.walk(module.tree)
              if isinstance(node, (ast.Import, ast.ImportFrom))
              and any((name or "").split(".")[0] in TERMINAL_OWNERS
                      for name in ([node.module] if isinstance(node, ast.ImportFrom)
                                   else [alias.name for alias in node.names]))}

    # assert
    assert owners == set(OWNS_THE_TERMINAL)
