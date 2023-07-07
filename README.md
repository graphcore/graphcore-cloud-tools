# graphcore-cloud-tools
Various common tools and utils for Graphcore's cloud services.

## Command line interface

The package includes some command line interface (CLI) utils. For more details, refer to the CLI help:

```console
python -m graphcore_cloud_tools --help
```

## Installation

The `graphcore-cloud-tools` package can be installed from source via pip:

```console
python -m pip install git+https://github.com/graphcore/graphcore-cloud-tools.git
```

## Notebook logging

The Graphcore logger for notebooks, `GCLogger`, is an IPython extension module that tracks user behaviour within the Jupyter notebooks we provide via Paperspace. For more information, refer to the [notebook logging README](https://github.com/graphcore/graphcore-cloud-tools/blob/master/graphcore_cloud_tools/notebook_logging/README.md)

To install:
```console
python -m pip install "graphcore-cloud-tools[logger] @ https://github.com/graphcore/graphcore-cloud-tools.git"
```

## Pre-Commit Hooks

```console
python -m pip install "graphcore-cloud-tools[precommit] @ https://github.com/graphcore/graphcore-cloud-tools.git"
```

## Development

* Reformat code to the repo standard with `make lint`
* Use [Google-style docstrings](https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html)
* Do not push to the master branch. Make changes through GitHub PR requests.

## Licence

See file `LICENSE`
