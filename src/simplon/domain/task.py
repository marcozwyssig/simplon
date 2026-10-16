"""si#400 part 4: the base of every task class firn generates, one per task (`<package>/tasks/<name>.py`).

A task class carries its coordinate in `KEY`, its ports as `ClassVar[Port]` attributes, and its body as
`run`, which until a product moves the body into the method is the wrapper `run = staticmethod(<impl>)`
in the class's protected region (spec decision 3). Nothing runs these classes before plan 4c; the suite
holds each one to the catalogue it is generated from (tests/test_task_classes.py).
"""
from typing import ClassVar


class Task:
    """A task: an instance of `simplon.pipeline.Task` in the model, a class here."""

    KEY: ClassVar[str]
