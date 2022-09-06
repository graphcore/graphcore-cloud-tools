# Applications benchmarking

## Summary
Applications benchmarking utils for Graphcore example applications, for quickly running and logging pre-made benchmarks.

## Benchmarking
Applications which have been rigourously tested will include benchmarks (usually in a file called `benchmarks.yml` in the application's root dir) that are specifically designed for validating the application's code and performance, for both internal testing and for external users. These scripts make the process of running and logging these benchmarks simple and reliable and provide a consistent interface for the user to run any application for which benchmarks are created.

## Installation/Setup
1. Prepare the environment. Install the Poplar SDK following the [Getting Started guide](https://docs.graphcore.ai/en/latest/getting-started.html) for your IPU system. Make sure to source the `enable.sh` scripts for Poplar and PopART and activate a Python virtualenv with the required framework is installed.

2. Follow the installation and setup guide for the application you want to benchmark, provided in their respective READMEs

3. run `pip install -e .` in this directory

## Usage
Interacting with benchmarking is all done through the examples_utils module. To run a specific benchmark, provide a path to the yaml file containing the benchmark and the name of the benchmark itself:
```python
python3 -m examples_utils benchmark --spec <PATH_TO_YAML> --benchmark <BENCHMARK_NAME>
```
And the script will do some setup, run the benchmark, and collect + post-process outputs into logs, normally written to the cwd.

Some examples:
```python
python3 -m examples_utils benchmark --spec /path/to/application/benchmarks.yml
python3 -m examples_utils benchmark --spec /path/to/application/benchmarks.yml --benchmark benchmark_1 benchmark_2
python3 -m examples_utils benchmark --spec /path/to/application/benchmarks.yml /path/to/another/application/benchmarks.yml
```

NOTE: if running using code from a custom examples directory (moved or renamed etc.) then please pass the `--examples-location` argument and provide the path to the directory containing the custom examples directory.

## Other functionality
In addition to the logs and metrics already recorded, there are a few other features included for making benchmarking easier and more customisable. Please see the output of 'python3 -m examples_utils benchmark -help' for more info

Points to note are:
- Multiple values can be passed to the `--spec` argument, either as multiple paths or as a wildcard expression to a whole dir containing yaml files (only the yaml files will be read by the script)
- The `--benchmark` argument is not required, and when not provided, all benchmarks within the yaml files provided in the `--spec` argument will be run/evaluated
- Multiple benchmarks can be passed to the `--benchmark` argument and they will be run in the order provided
- When profiling, the popvision profile is saved in the current working directory (this will be the application directory where the benchmarks are being run) and `POPLAR_ENGINE_OPTIONS` is given: `"autoReport.all": "true"` and `"autoReport.outputSerializedGraph": "false"`. This is to enable all standard profiling functionality but avoiding making the profile too large. For more information on profiling, please refer to the [PopVision guide](https://docs.graphcore.ai/projects/graphcore-popvision-user-guide/en/latest/index.html#)

## Changelog
Please see the changelog file for a full history.
