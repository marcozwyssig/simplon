# The eight reachable manifests, frozen in the OLD (`groups:`) form

Fetched on 2026-10-11 through the GitHub API, exactly as each product's default branch carried them.
They are the population si#344's migration is measured against: `test_migrate.py` migrates each one and
asserts that the migrated manifest assembles the same CLI surface as `golden/<product>.json`. The goldens
were recorded by the kernel BEFORE the ci/cd change (plan A, Task 1), which is the only kernel that could
still load these files.

Do not refresh these files: a refreshed copy would be in the new form, and the test would prove nothing.

## Not loadable by the recording kernel

None: all eight loaded with the recording kernel.
