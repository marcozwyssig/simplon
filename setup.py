"""The one thing pyproject.toml cannot say: the firn M2 a product's exported manifest model needs (si#522).

`manifest`, `pipeline`, `catalogue` and `vocabulary` live in `src/firn/model/simplon/`, simplon's own firn
project, and they cannot move under `src/simplon/`: firn v0.2.0 refuses a model folder inside its `simplon`
target (E105, "the next load would read generated files as input", measured 2026-10-24). So the build copies
them into the package as `simplon/m2/simplon/<package>/`, and `test_wheel` holds the copy byte for byte to
its source. `architecture` and `components` describe simplon's own code and stay out.
"""
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

M2 = ("catalogue", "manifest", "pipeline", "vocabulary")
SOURCE = Path(__file__).resolve().parent / "src" / "firn" / "model" / "simplon"


class BuildPyWithM2(build_py):
    def run(self) -> None:
        super().run()
        target = Path(self.build_lib) / "simplon" / "m2" / "simplon"
        for package in M2:
            shutil.copytree(SOURCE / package, target / package, dirs_exist_ok=True)


setup(cmdclass={"build_py": BuildPyWithM2})
