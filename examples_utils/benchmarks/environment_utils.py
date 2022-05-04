# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import copy
import logging
import os
import re

# Get the module logger
logger = logging.getLogger(__name__)


def get_mpinum(command: str) -> int:
    """Get num replicas (mpinum) from the cmd.

    Args:
        command (str): The command line that includes a call to mpirun

    Returns:
        mpinum (int): Number of processes passed to mpirun
    
    """

    m = re.search(r"mpirun.+--np.(\d*) ", command)
    if m:
        mpinum = float(m.group(1))
    else:
        mpinum = 1

    return mpinum


def merge_environment_variables(benchmark_spec: dict) -> dict:
    """Merge existing environment variables with new ones in the benchmark.

    Args:
        benchmark_dict (dict): The benchmark entry itself in the yaml file
        logger (logging.Logger): Logger to use

    Returns:
        env (dict): Merged environment state to use for benchmarking
    
    """

    # Build and log the additional ENV variables
    new_env = {}
    if "env" in benchmark_spec:
        new_env = copy.deepcopy(benchmark_spec["env"])

    logger.info(f"Running with the following {len(new_env)} ADDITIONAL ENV variables:")
    for k, v in new_env.items():
        logger.info(f"    {k}={v}")

    # Finally update existing env with new env
    env = os.environ.copy()
    env.update(new_env)

    return env
