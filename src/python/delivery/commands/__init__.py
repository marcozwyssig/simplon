"""Product-agnostic CLI command implementations the kernel ships (netctl#1286, netctl#1280).

A product's manifest points an `impl:` reference straight at a callable in here whenever the command needs
no product knowledge: `delivery.commands.claudeplugins:install_cmd` rather than a product module that only
forwards the call. Product data reaches these callables through `delivery.context.current()` and the
manifest, never through an import of the product - the coupling flows product -> kernel, as everywhere else.

The callables are real Typer callbacks with their Option/Argument signatures intact, because that is what
the manifest engine resolves and what Typer introspects; a bare delegate would drop the flags.
"""
