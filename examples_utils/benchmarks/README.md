# Applications benchmarking

## Summary
Applications benchmarking utils for Graphcore example applications, for quickly running and logging pre-made benchmarks.

## Benchmarking
Applications which have been rigourously tested will include benchmarks (usually in a file called `benchmarks.yml` in the application's root dir) that are specifically designed for validating the application's code and performance, for both internal testing and for external users. These scripts make the process of running and logging these benchmarks simple and reliable and provide a consistent interface for the user to run any application for which benchmarks are created.

## Installation/Setup
1. Prepare the environment. Install the Poplar SDK following the Getting Started guide for your IPU system. Make sure to source the `enable.sh` scripts for Poplar and PopART and activate a Python virtualenv with the required framework is installed.

2. Follow the installation and setup guide for the application you want to benchmark, provided in their respective READMEs

3. run `pip install -r requirements.txt` in this directory

## Usage
Interacting with benchmarking is all done through the `run_benchmarks.py` script. To run a specific benchmark, provide a path to the yaml file containing the benchmark and the name of the benchmark itself:
```
python3 run_benchmarks.py --spec <PATH_TO_YAML> --benchmark <BENCHMARK_NAME>
```
And the script will do some setup, run the benchmark, and collect + post-process outputs into logs, normally written to the cwd.

Some examples:
```
python3 run_benchmarks.py --spec /path/to/application/benchmarks.yml
python3 run_benchmarks.py --spec /path/to/application/benchmarks.yml --benchmark benchmark_1 benchmark_2
python3 run_benchmarks.py --spec /path/to/application/benchmarks.yml /path/to/another/application/benchmarks.yml
```

## Other functionality
In addition to the logs and metrics already recorded, there are a few other features included for making benchmarking easier and more customisable. 

Looking at the output of script with the `--help` argument:
```
--spec SPEC [SPEC ...]
    Yaml files with benchmark spec
--benchmark BENCHMARK [BENCHMARK ...]
    List of benchmark ids to run
--logdir LOGDIR
    Folder to place log files
--compile-only
    Enable compile only options in compatible models
--ignore-wandb
    Ignore any wandb commands
--logging {DEBUG,INFO,ERROR,CRITICAL,WARNING}
    Specify the logging level
--timeout TIMEOUT
    Maximum time allowed for any of the benchmarks/variants (in seconds)
```

Points to note are:
- Multiple values can be passed to the `--spec` argument, either as multiple paths or as a wildcard expression to a whole dir containing yaml files (only the yaml files will be read by the script)
- The `--benchmark` argument is not required, and when not provided, all benchmarks within the yaml files provided in the `--spec` argument will be run/evaluated
- Multiple benchmarks can be passed to the `--benchmark` argument and they will be run in the order provided

This script is a reduction and refactor of the scripts available in ce_benchmarking, however of the functionality that is kept, all arguments/usage is equivalent to how it would be used in the original. In other words, transition to using the full functionality with the original scripts in ce_benchmarking, if you choose to do so, should be seamless.
## Changelong
07/04/22 - Initial commits
28/04/22 - Post-review cleanup and documenting

## Future work plans
- Adding more functionality from ce_benchmarks/test automation repos to run_benchmarks
- Supporting a full move of benchmarking from ce_benchmarks to applications repositories
- Moving some app-specific infrastructure from ce_benchmarking/test automation repos to examples_utils
