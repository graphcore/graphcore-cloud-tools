# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import copy
import logging
import os
import re
from argparse import ArgumentParser
from pathlib import Path

# Get the module logger
logger = logging.getLogger(__name__)

POPRUN_VARS = {
    "HOSTS": ("Comma seperated list of IP addresses/names of the machines you "
              "want to run on. Try to copy across ssh-keys before attempting "
              "if possible. e.g. 10.1.3.101,10.1.3.102,... or "
              "lr17-1,lr17-2,..."),
    "IPUOF_VIPU_API_PARTITION_ID": ("Name of the Virtual IPU partition. Can be "
                                    "found with 'vipu list partitions'."),
    "CLUSTER": ("Name of the Virtual IPU cluster. Can be found with 'vipu "
                "list partition'."),
    "TCP_IF_INCLUDE": ("The range of network interfaces available to use for "
                       "poprun to communicate between hosts."),
    "VIPU_CLI_API_HOST": ("The IP address/name of the HOST where the virtual "
                          "IPU server is running."),
}


def check_poprun_env_variables(benchmark_name: str, cmd: str):
    """Check if poprun environment variables have been set prior to running.

    Args:
        benchmark_name (str): The name of the benchmark being run
        cmd (str): The command being run

    """

    # If PARTITION exists in env but IPUOF_VIPU_API_PARTITION_ID isnt, set it
    # to the existing value
    if ("PARTITION" in os.environ) and ("IPUOF_VIPU_API_PARTITION_ID" not in os.environ):
        os.environ["IPUOF_VIPU_API_PARTITION_ID"] = os.environ["PARTITION"]

    # Check if any of the poprun env vars are required but not set
    missing_env_vars = [
        env_var for env_var in POPRUN_VARS.keys() if f"${env_var}" in cmd and os.getenv(env_var) is None
    ]
    if missing_env_vars:
        err = (f"{len(missing_env_vars)} environment variables are needed by "
               f"command {benchmark_name} but are not defined: "
               f"{missing_env_vars}. Hints: \n")
        err += "".join([f"\n\t{missing} : {POPRUN_VARS[missing]}" for missing in missing_env_vars])

        logger.error(err)
        raise EnvironmentError(err)


def enter_benchmark_dir(benchmark_dict: dict):
    """Find and change to the path required to run the benchmark.

    Notes:
        For examples where the directory structure is non-standard (does not
        follow the <category>/<model>/<framework>/'train.py' etc. convention),
        the benchmark specification in the benchmarks.yml file will contain an
        additional field 'location' which will inform this sub-module on how to
        locate the python file that needs to be called.

    Args:
        benchmark_dict (dict): Dict created when evaluating the benchmark spec

    """

    # Find the root dir of the benchmarks.yml file
    benchmark_path = Path(benchmark_dict["benchmark_path"]).parent

    # If a special path is required, find and move to that in addition
    if benchmark_dict.get("location"):
        benchmark_path = benchmark_path.joinpath(benchmark_dict["location"])

    os.chdir(benchmark_path)


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


def infer_paths(args: ArgumentParser, benchmark_dict: dict) -> ArgumentParser:
    """Infer paths to key directories based on argument and environment info.

    Args:
        args (ArgumentParser): The arguments passed to this benchmarking run
        benchmark_dict (dict): The parameters for a particular benchmark
    
    Returns:
        args (ArgumentParser): args, but with additional paths attributes added
    
    """

    spec_path = benchmark_dict["benchmark_path"]
    offset = 4
    # If the benchmarks.yml file is in train/infer the application root dir
    if ("train" in spec_path) or ("infer" in spec_path):
        offset += 1

    # Split path to benchmark.yml, find what the dir contatining all examples
    # is called, and add it back together
    args.examples_path = str(Path("/".join(spec_path.split("/")[:-offset])).resolve())

    # Find based on the required environment variable when a SDK is enabled
    sdk_path = os.getenv("POPLAR_SDK_ENABLED")
    if sdk_path is None:
        err = ("It appears that a poplar SDK has not been enabled, determined "
               "by 'POPLAR_SDK_ENABLED' environment variable not detected in "
               "this environment. Please make sure the SDK is enabled in this "
               "environment (use 'source' when enabling/activating).")
        logger.error(err)
        raise EnvironmentError(err)
    args.sdk_path = str(Path(sdk_path).parents[1].resolve())

    # Find based on the required environment variable when a venv is activated
    venv_path = os.getenv("VIRTUAL_ENV")
    if venv_path is None:
        err = ("It appears that a python virtual environment has not been "
               "activated, determined by 'VIRTUAL_ENV' environment variable "
               "not detected in this environment. Please make sure the python "
               "virtual environment is activate in this environment (use "
               "'source' when enabling/activating).")
        logger.error(err)
        raise EnvironmentError(err)
    args.venv_path = str(Path(venv_path).parents[1].resolve())

    return args


def merge_environment_variables(new_env: dict, benchmark_spec: dict) -> dict:
    """Merge existing environment variables with new ones in the benchmark.

    Args:
        new_env (dict): The new environment variables state to merge into 
            current state
        benchmark_dict (dict): The benchmark entry itself in the yaml file

    Returns:
        existing_env (dict): Merged environment state to use for benchmarking
    
    """

    # Build and log the additional ENV variables
    benchmark_env = {}
    if "env" in benchmark_spec:
        benchmark_env = copy.deepcopy(benchmark_spec["env"])
    new_env.update(benchmark_env)

    logger.info(f"Running with the following {len(new_env)} ADDITIONAL ENV variables:")
    for k, v in new_env.items():
        logger.info(f"    {k}={v}")

    # Finally update existing env with new env
    existing_env = os.environ.copy()
    existing_env.update(new_env)

    return existing_env
