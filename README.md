# examples-utils
Utils and common code for Graphcore's example applications.

## Command line interface

The package includes some command line interface (CLI) utils. For more details, refer to the CLI help:

```console
python -m examples_utils --help
```

## Installation

The `examples-utils` package can be installed from source via pip:

```console
python -m pip install https://github.com/graphcore/examples-utils.git
```

By default, this will only install a minimal set of requirements. To benchmark notebooks you must
install the "jupyter" set of requirements:

```console
python -m pip install "examples-utils[jupyer] @ https://github.com/graphcore/examples-utils.git"
```

The [`latest_stable`](https://github.com/graphcore/examples-utils/releases/tag/latest_stable) tag refers to a commit that is tested and should be reliable, but also updates automatically as fixes and features are added. You can use this by adding: 

```console
examples-utils[common] @ git+https://github.com/graphcore/examples-utils@latest_stable
```
to your requirements.txt file

## Benchmarking

The `benchmarking` sub-package is used for running the benchmarks that are provided with example applications in the [examples](https://github.com/graphcore/examples) repository. For more information, refer to the [benchmarks README](https://github.com/graphcore/examples-utils/blob/master/examples_utils/benchmarks/README.md).

## Notebook logging

The Graphcore logger for notebooks, `GCLogger`, is an IPython extension module that tracks user behaviour within the Jupyter notebooks we provide via Paperspace. For more information, refer to the [notebook logging README](https://github.com/graphcore/examples-utils/blob/master/examples_utils/notebook_logging/README.md)

## Pre-Commit Hooks

```console
python -m pip install "examples-utils[precommit] @ https://github.com/graphcore/examples-utils.git"
```

## Development

* Reformat code to the repo standard with `make lint`
* Use [Google-style docstrings](https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html)
* Do not push to the master branch. Make changes through GitHub PR requests.

## Licence

See file `LICENSE`
