"""Product-agnostic task bodies the kernel ships (netctl#1286, netctl#1280, netctl#1469).

A task declares an `impl:` reference pointing straight at a callable in here whenever the body needs no
product knowledge: `delivery.tasks.claudeplugins:install_cmd` rather than a product module that only
forwards the call. A command exists only in a manifest's `groups:`, instantiating a task by name (`task:`,
optionally pinning a parameter with `with:`) - this module holds bodies, never a command of its own.
Product data reaches these callables through `delivery.context.current()` and the manifest, never through
an import of the product - the coupling flows product -> kernel, as everywhere else.

The callables are real Typer callbacks with their Option/Argument signatures intact, because that is what
the manifest engine resolves and what Typer introspects; a bare delegate would drop the flags.
"""
