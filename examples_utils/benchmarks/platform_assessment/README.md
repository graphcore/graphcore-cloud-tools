# Applications benchmarking
## Platform assessment tool (benchmark automation)

## Summary
A tool for automating and simplifying the process of assessing a new platform (running multiple benchmarks auotmatically in individual environments)

## Platform assessment
One of the assessments of a new platform/service is to run a selection of applications and compare the performance of those to reference values we have from our own machines tested at SDK releases or in nightly performance tests. This set of scripts wraps the examples_utils benchmark sub-module with a set of environment setup commands, inferring the required environment from the benchmark name itself.

Individual benchmarks are run (in order) according to `assess_platform_benchmarks.yml` (or any alternate compatible yaml file provided with the `--spec` argument), and the results of these are merged into `benchmark_results.csv`, created in this directory. For details on how benchmarks are run, please refer to the documentation provided with

## Automated environment setup 
In summary, these are the steps that the `assess_platform.sh` wrapper script carries out:
- Enable the SDK provided in `--sdk-path`
- Create a python virtual environment and update pip
- Determine the framework needed for the benchmark
- Install the framework specific wheels, and horovod
- Navigate to the application root dir (assuming `examples` is in the home directory in `$HOME`)
- Install application requirements
- Run the benchmark using examples_utils benchmark
- Deactivate and remove the python virtual environment and disable the SDK

## Installation/Setup
There are no steps to build or install this set of scripts, all packages used are python standard library and the enviroment setup will install the application requirements and examples_utils benchmark as well.

## Usage
To run with the provided benchmarks in `assess_platform_benchmarks.yml`, simply run:
```
python3 assess_platform.py --sdk-path <path to a specific sdk root dir>
```

If you want to provide your own yaml file, then simply pass the path to it with `--spec`.

## Changelog
Please see the changelog in examples_utils/benchmarks for details in changes to this tool.

## Future work plans
Please see the `Future work plans` section in examples_utils/benchmarks for details of future work plans for this tool.
