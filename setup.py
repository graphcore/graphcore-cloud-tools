# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import io
import os
from pathlib import Path
from glob import glob

from setuptools import find_packages, setup


def read(*paths, **kwargs):
    """Read the contents of a text file safely.
    >>> read("project_name", "VERSION")
    '0.1.0'
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
    return [
        line.strip()
        for line in read(path).split("\n")
        if not line.startswith(('"', "#", "-"))
    ]


setup(
    name='examples-utils',
    description="Utils and common code for Graphcore's example applications",
    long_description="file: README.md",
    long_description_content_type="text/markdown",
    license="MIT License",
    author="Graphcore Ltd.",
    url="https://github.com/graphcore/examples-utils",
    # download_urls = "https://pypi.org/project/examples-utils",
    project_urls={
        # "Documentation": "https://graphcore.github.io/examples-utils",
        "Code": "https://github.com/graphcore/examples-utils",
        # "Issue tracker": "https://github.com/graphcore/examples-utils/issues",
    },
    classifiers=[  # Optional
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Scientific/Engineering",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
    ],
    install_requires=read_requirements("requirements.txt"),
    extras_require={"dev": read_requirements("requirements-dev.txt")},
    packages=['examples_utils'],
    package_data={'examples_utils': [os.path.join(*Path(f).parts[1:]) for f in glob('**/*.cpp', recursive=True)]},
)
