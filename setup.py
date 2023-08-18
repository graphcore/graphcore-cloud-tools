# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import io
import os
from pathlib import Path
from glob import glob
import re

from setuptools import setup


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
    version_lines = [
        l for l in read("graphcore_cloud_tools/__init__.py").splitlines() if re.match("__version__\\s*=", l)
    ]
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
    "dev": read_requirements("requirements-dev.txt"),
    "logger": read_requirements("requirements-logger.txt"),
}
extra_requires["all"] = []
for reqs in extra_requires.values():
    extra_requires["all"].extend(reqs)

setup(
    name="graphcore-cloud-tools",
    description="Various common tools and utils for Grpahcore's cloud services",
    long_description="file: README.md",
    long_description_content_type="text/markdown",
    license="MIT License",
    author="Graphcore Ltd.",
    url="https://github.com/graphcore/graphcore-cloud-tools",
    # download_urls = "https://pypi.org/project/graphcore-cloud-tools",
    project_urls={
        # "Documentation": "https://graphcore.github.io/graphcore-cloud-tools",
        "Code": "https://github.com/graphcore/graphcore-cloud-tools",
        "Issue tracker": "https://github.com/graphcore/graphcore-cloud-tools/issues",
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
    packages=["graphcore_cloud_tools"],
    package_data={
        "graphcore_cloud_tools":
        # Paths need to be relative to `graphcore-cloud-tools/` folder
        [os.path.join(*Path(f).parts[1:]) for f in glob("graphcore_cloud_tools/**/*.py", recursive=True)]
        + [os.path.join(*Path(f).parts[1:]) for f in glob("graphcore_cloud_tools/**/*.cpp", recursive=True)]
    },
    version=get_version(),
)
