"""platformcore.orchestrator - the product-agnostic CI/CD orchestrator engine.

Phase 1a ships the step MODEL + runners (steps) and the Textual UI (tui). The manifest loader,
env-gate and CLI assembler follow in Phase 1b. Products keep only their command impls + a YAML
manifest and consume this engine."""
