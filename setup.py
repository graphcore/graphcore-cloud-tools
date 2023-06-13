# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import io
import os
from pathlib import Path
from glob import glob
import re

from setuptools import find_packages, setup


def read(*paths, **kwargs):
    """Read the contents of a text file safely.
    >>> read("project_name", "VERSION")
    '1.0.0'
    >>> read("README.md")
    ...
    """

    content = ""
    with io.open(
        os.path.join(os.path.dirname(__file__), *paths),
        encoding=kwargs.get("encoding", "utf8"),
    ) as open_file:
        content = open_file.read().strip()
    return content


def read_requirements(path):
    return [line.strip() for line in read(path).split("\n") if not line.startswith(('"', "#", "-"))]


def get_version():
    """Looks for __version__ attribute in top most __init__.py"""
    version_lines = [l for l in read("examples_utils/__init__.py").splitlines() if re.match("__version__\\s*=", l)]
    if len(version_lines) != 1:
        raise ValueError(
            "Cannot identify version: 0 or multiple lines " f"were identified as candidates: {version_lines}"
        )
    version_line = version_lines[0]
    m = re.search(r"['\"]([0-9a-zA-Z\.]*)['\"]", version_line)
    if not m:
        raise ValueError(f"Could not identify version in line: {version_line}")
    return m.groups()[-1]


extra_requires = {
    "benchmark": read_requirements("requirements-benchmark.txt"),
    # Alias to avoid breaking existing requirements.txt files where [common] is used
    "common": read_requirements("requirements.txt"),
    "dev": read_requirements("requirements-dev.txt"),
    "jupyter": read_requirements("requirements-jupyter.txt") + read_requirements("requirements-benchmark.txt"),
    "logger": read_requirements("requirements-logger.txt"),
    "precommit": read_requirements("requirements-precommit.txt"),
}
extra_requires["all"] = extra_requires["dev"] + extra_requires["jupyter"] + extra_requires["precommit"]

setup(
    name="examples-utils",
    description="Utilities, benchmarking and common code for Graphcore's example applications",
    long_description="file: README.md",
    long_description_content_type="text/markdown",
    license="MIT License",
    author="Graphcore Ltd.",
    url="https://github.com/graphcore/examples-utils",
    # download_urls = "https://pypi.org/project/examples-utils",
    project_urls={
        # "Documentation": "https://graphcore.github.io/examples-utils",
        "Code": "https://github.com/graphcore/examples-utils",
        "Issue tracker": "https://github.com/graphcore/examples-utils/issues",
    },
    classifiers=[  # Optional
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Scientific/Engineering",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
    ],
    install_requires=read_requirements("requirements.txt"),
    extras_require=extra_requires,
    packages=["examples_utils"],
    package_data={
        "examples_utils":
        # Paths need to be relative to `examples_utils/` folder
        [os.path.join(*Path(f).parts[1:]) for f in glob("examples_utils/**/*.py", recursive=True)]
        + [os.path.join(*Path(f).parts[1:]) for f in glob("examples_utils/**/*.cpp", recursive=True)]
    },
    version=get_version(),
)
