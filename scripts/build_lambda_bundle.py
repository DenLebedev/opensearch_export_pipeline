"""Build a shared deployment directory for Python Lambda functions."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Lambda deployment directory.")

    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Directory containing the export_pipeline package.",
    )
    parser.add_argument(
        "--requirements",
        required=True,
        type=Path,
        help="Lambda requirements file.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output deployment directory.",
    )
    parser.add_argument(
        "--platform",
        required=True,
        help="Target pip platform, for example manylinux2014_aarch64.",
    )
    parser.add_argument(
        "--python-version",
        required=True,
        help="Target Python version, for example 3.13.",
    )

    return parser.parse_args()


def build_bundle(
    *,
    source: Path,
    requirements: Path,
    output: Path,
    platform: str,
    python_version: str,
) -> None:
    source = source.resolve()
    requirements = requirements.resolve()
    output = output.resolve()

    if not source.is_dir():
        raise ValueError(f"Source directory does not exist: {source}")

    if not requirements.is_file():
        raise ValueError(f"Requirements file does not exist: {requirements}")

    if output.exists():
        shutil.rmtree(output)

    output.mkdir(
        parents=True,
        exist_ok=True,
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--requirement",
            str(requirements),
            "--target",
            str(output),
            "--upgrade",
            "--disable-pip-version-check",
            "--platform",
            platform,
            "--implementation",
            "cp",
            "--python-version",
            python_version,
            "--only-binary=:all:",
        ],
        check=True,
    )

    package_destination = output / "export_pipeline"

    shutil.copytree(
        source,
        package_destination,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
        ),
    )


def main() -> None:
    arguments = parse_arguments()

    build_bundle(
        source=arguments.source,
        requirements=arguments.requirements,
        output=arguments.output,
        platform=arguments.platform,
        python_version=arguments.python_version,
    )


if __name__ == "__main__":
    main()
