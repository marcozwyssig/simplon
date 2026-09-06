"""`python -m orchestrator ...` entry point - hands argv to the assembled Typer CLI (matches the shim's
LAUNCH_MODULE=orchestrator target `python -u -m orchestrator "$@"`)."""
from .cli import main

if __name__ == "__main__":
    main()
