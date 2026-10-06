import tomllib
from pathlib import Path

import benchmark_radar


def test_package_metadata_matches_the_current_release_and_title():
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    locked_package = next(
        package for package in lock["package"] if package["name"] == metadata["name"]
    )

    assert metadata["version"] == "0.11.0"
    assert benchmark_radar.__version__ == metadata["version"]
    assert locked_package["version"] == metadata["version"]
    assert metadata["description"] == (
        "Benchmark Radar: A Living Database and Search Engine for AI Benchmarks and Evaluation"
    )


def test_tests_import_this_checkouts_source():
    """Guard against a worktree silently testing another checkout's code.

    The venv has the repo installed as an editable package, so without
    `pythonpath = ["src"]` in pyproject.toml a bare `pytest` run inside a git
    worktree imports benchmark_radar from whichever checkout was pip-installed.
    The suite then passes while measuring source the branch never touched.
    """
    imported = Path(benchmark_radar.__file__).resolve()
    expected = (Path(__file__).parent.parent / "src" / "benchmark_radar" / "__init__.py").resolve()
    assert imported == expected, f"tests import {imported}, expected {expected}"
