# examples-utils
Utils and common code for Graphcore's example applications

## Command line interface (CLI)

The package includes some command line interface utils. For more details refer to the CLI help message:

```python
python -m examples_utils --help
```

## Benchmarking

The benchmarking sub-package is used for running the benchmarks that are provided with example applications in the [examples](https://github.com/graphcore/examples) repository. For more information, refer to the [benchmark's README](https://github.com/graphcore/examples-utils/blob/master/examples_utils/benchmarks/README.md).

## Development
* Reformat code to repo standard: `make lint`
* Use [Google style docstrings](https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html)
* Do not push to master branch. Make changes through github PR requests.

## Licence

See file `LICENSE`