# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
""" This module lets you register custom metrics to let you
define arbitrary ways in which the standard output, the standard
error and the exit code of a benchmark will be parsed.

In order to define a new metric:

 1. Write new metric functions in a python file ``my_metric.py``
 2. Register those metrics with the ``register_custom_metric`` function
 3. Run the benchmarks with the additional argument ``--custom-metrics-files=my_metric.py``

Example content of ``my_metric.py``

```
from examples_utils import register_custom_metric

# Arbitrary metric function it must have a similar signature
def log_lengths(stdout: str, stderr: str, exitcode: int):
    return dict(stdout=len(stdout), stderr=len(stderr))


# Call this function to declare the metric to examples utils
# it will appear in the final results directory under the name
# passed as a first argument.
register_custom_metric("log_lengths", log_lengths)
```

"""
from typing import List, Callable, Optional, Any, Dict, Union
import logging
import pathlib
import importlib.util

logger = logging.getLogger(__name__)

MetricFunction = Callable[[str, str, int], Optional[Any]]

REGISTERED_HOOKS: Dict[str, MetricFunction] = {}


def import_metrics_hooks_files(hook_files: List[Union[str, pathlib.Path]]):
    """Imports files which define additional metrics in python"""
    for file in hook_files:
        file_path = pathlib.Path(file).resolve()
        module_name = file_path.stem
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            logger.warning(f"{file_path} specified as defining additional metrics could not be imported.")
        else:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            logger.info(f"Imported {module_name} from '{file_path}'")


def register_custom_metric(name: str, function: MetricFunction):
    """Register a new metric function to be run during processing of the benchmark."""
    if name in REGISTERED_HOOKS:
        logger.warning(f"Metric '{name}' multiply defined, only the last registered implementation will be executed.")
    REGISTERED_HOOKS[name] = function
    logger.info(f"    Registered metric hook: {name} with object: {function}")


def process_registered_metrics(results: dict, stdout: str, stderr: str, exitcode: int):
    """Process the metrics registered with ``register_custom_metric``"""
    for metric_name, metric_function in REGISTERED_HOOKS.items():
        try:
            results[metric_name] = metric_function(stdout, stderr, exitcode)
        except Exception as error:
            err = f"Metric '{metric_name}' failed during execution with: {type(error).__name__} {error}"
            logger.error(err)
    return results
