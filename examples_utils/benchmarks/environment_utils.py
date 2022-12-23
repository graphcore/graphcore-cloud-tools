# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
from typing import Optional, List
import argparse
import copy
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

# Get the module logger
logger = logging.getLogger(__name__)


def parse_vipu_server() -> Optional[str]:
    out = subprocess.check_output(["vipu", "--server-version"])
    # Sample output
    # version: 1.18.0
    # host: localhost:8090
    out = out.decode()
    m = re.search("host: (.*):", out)
    if not m:
        err = ("vipu --server-version output could not be parsed. Could not identify the"
               " host of the V-IPU server, please set the IPUOF_VIPU_API_HOST environment"
               " variable according to the V-IPU documentation. "
               f"vipu --server-version returned:\n{out}")
        logger.error(err)
        return None
    return m.groups()[0]


POPRUN_VARS = {
    "HOSTS": ("Comma seperated list of IP addresses/names of the machines you want "
              "to run on. Try to copy across ssh-keys before attempting if "
              "possible. e.g. 10.1.3.101,10.1.3.102,... or lr17-1,lr17-2,..."),
    "IPUOF_VIPU_API_PARTITION_ID": ("Name of the Virtual IPU partition. Can be found with 'vipu list "
                                    "partitions'."),
    "CLUSTER": ("Name of the Virtual IPU cluster. Can be found with 'vipu list "
                "partition'."),
    "TCP_IF_INCLUDE": ("The range of network interfaces available to use for poprun to "
                       "communicate between hosts."),
    "VIPU_CLI_API_HOST": ("The IP address/name of the HOST where the virtual IPU server is "
                          "running."),
}

# Values must be a tuple of strings or None, or a function to generate them
FALLBACK_VAR_FUNCTIONS = {
    "VIPU_CLI_API_HOST": (
        os.getenv("IPUOF_VIPU_API_HOST"),
        parse_vipu_server,
    ),
    "IPUOF_VIPU_API_PARTITION_ID": (os.getenv("PARTITION"), )
}

WANDB_VARS = {
    "WANDB_API_KEY": ("The API access key for your W&B account. Available from your W&B "
                      "account > settings > API keys."),
    "WANDB_BASE_URL": ("The base URL for your W&B server (www.wandb.<domain name>.net). "
                       "Available by checking your organisations wandb account."),
}

AWSCLI_VARS = {
    "AWS_ACCESS_KEY_ID": ("The AWSCLI access key for the S3 storage account. Available from "
                          "your AWS account > security credentials."),
    "AWS_SECRET_ACCESS_KEY": ("The AWSCLI secret key for your AWS account. Available from your AWS "
                              "account > security credentials."),
}

SLURM_ENV_VARS = {
    "SLURM_HOST_SUBNET_MASK": {
        "help": "Host subnet mask for all allocations from the SLURM queue.",
        "default": "ens5"
    }
}


def _check_cmd_for_missing_poprun_vars(benchmark_name: str, cmd: str):
    # Check if any of the poprun env vars are required but not set
    missing_poprun_vars: List[str] = []
    for env_var in POPRUN_VARS.keys():
        not_in_cmd = not (f"${env_var}" in cmd or f"${{{env_var}}}" in cmd)
        is_set = os.getenv(env_var) is not None
        if not_in_cmd or is_set:
            continue
        # Try to find a fallback variable or function
        if env_var in FALLBACK_VAR_FUNCTIONS:
            for fallback in FALLBACK_VAR_FUNCTIONS[env_var]:
                fallback_val = fallback() if callable(fallback) else fallback
                if fallback_val is not None:
                    # Fallbacks set the environment variable
                    os.environ[env_var] = fallback_val
                    break
        if os.getenv(env_var) is None:
            missing_poprun_vars.append(env_var)

    if missing_poprun_vars:
        err = (f"{len(missing_poprun_vars)} environment variables are needed by "
               f"command {benchmark_name} but are not defined: "
               f"{missing_poprun_vars}. Hints: \n")
        err += "".join([f"\n\t{missing} : {POPRUN_VARS[missing]}" for missing in missing_poprun_vars])

        logger.error(err)
        raise EnvironmentError(err)


def check_env(args: argparse.Namespace, benchmark_name: str, cmd: str):
    """Check if environment has been correctly set up prior to running.

    Args:
        args (argparse.Namespace): CLI arguments provided to this benchmarking run
        benchmark_name (str): The name of the benchmark being run
        cmd (str): The command being run

    """

    # if submitting on slurm, these environment variables are ignored
    if not args.submit_on_slurm:
        _check_cmd_for_missing_poprun_vars(benchmark_name, cmd)

    if args.submit_on_slurm:
        for k, v in SLURM_ENV_VARS.items():
            if k not in os.environ:
                warn_msg = F"{k}: {v['help']} has not been set. Falling back to the default value of: {v['default']}."
                logger.warn(warn_msg)
                os.environ[k] = v["default"]

    # TODO: Investigate working of wandb and awscli on SLURM

    missing_env_vars = []
    # Check wandb variables if required
    if args.allow_wandb:
        # Determine if wandb login has not been done already
        netrc_path = Path(os.environ["HOME"], ".netrc")
        if netrc_path.exists() and os.stat(Path(os.environ["HOME"], ".netrc")).st_size == 0:
            logger.warn("wandb appears to not have been logged in. Checking "
                        "for environment variables to be used instead...")
            missing_env_vars.extend([env_var for env_var in WANDB_VARS.keys() if os.getenv(env_var) is None])

    # Check AWSCLI env vars if required
    if "s3" in args.upload_checkpoints:
        # Check for default credentials file or a env var to its path first
        if (not (Path(os.getenv("HOME"), ".aws", "credentials").exists())
                and (not os.getenv("AWS_SHARED_CREDENTIALS_FILE"))):
            logger.warn("AWSCLI has not been configured. Checking for environment variables to be used instead...")
            missing_env_vars.extend([env_var for env_var in AWSCLI_VARS.keys() if os.getenv(env_var) is None])

    # Print out all missing vars with hints for the user
    joint_vars_dict = {**WANDB_VARS, **AWSCLI_VARS}
    if missing_env_vars:
        err = (f"{len(missing_env_vars)} environment variables are needed "
               f"because of the arguments passed to this command, but are not "
               f"defined: {missing_env_vars}.\nHints: \n")
        err += "".join([f"\t{missing} : {joint_vars_dict[missing]}\n" for missing in missing_env_vars])

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
    if benchmark_dict.get("reference_directory"):
        benchmark_path = Path(benchmark_dict["reference_directory"])
    else:
        benchmark_path = Path(benchmark_dict["benchmark_path"]).parent

    # If a special path is required, find and move to that in addition
    if benchmark_dict.get("location"):
        benchmark_path = benchmark_path.joinpath(benchmark_dict["location"])
    current_working_dir = str(Path(os.curdir).resolve())
    logger.debug(f"Entering {benchmark_path}")
    os.chdir(benchmark_path)
    return current_working_dir


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


def infer_paths(args: argparse.Namespace, benchmark_dict: dict) -> argparse.Namespace:
    """Infer paths to key directories based on argument and environment info.

    Args:
        args (argparse.Namespace): The arguments passed to this benchmarking run
        benchmark_dict (dict): The parameters for a particular benchmark

    Returns:
        args (argparse.Namespace): args, but with additional paths attributes added

    """

    spec_path = benchmark_dict["benchmark_path"]
    offset = 4
    # If the benchmarks.yml file is in train/infer the application root dir
    if ("train" in spec_path) or ("infer" in spec_path):
        offset += 1

    # Split path to benchmark.yml, find what the dir contatining all examples
    # is called, and add it back together
    args.examples_path = str(Path("/".join(spec_path.split("/")[:-offset])).resolve())

    args.sdk_path = os.getenv("POPLAR_SDK_ENABLED")
    if args.sdk_path is None:
        err = ("It appears that a poplar SDK has not been enabled, determined "
               "by 'POPLAR_SDK_ENABLED' environment variable not detected in "
               "this environment. Please make sure the SDK is enabled in this "
               "environment (use 'source' when enabling/activating).")
        logger.error(err)
        raise EnvironmentError(err)
    else:
        args.sdk_path = str(Path(args.sdk_path).parent.resolve())

    args.venv_path = os.getenv("VIRTUAL_ENV")
    if args.venv_path is None:
        err = ("It appears that a python virtual environment has not been "
               "activated, determined by 'VIRTUAL_ENV' environment variable "
               "not detected in this environment. Please make sure the python "
               "virtual environment is activate in this environment (use "
               "'source' when enabling/activating).")
        logger.error(err)
        raise EnvironmentError(err)
    else:
        args.venv_path = str(Path(args.venv_path).resolve())

    return args


def get_git_commit_hash() -> str:
    # assumed we're in the top level directory of the git repo
    try:
        process = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode(sys.stdout.encoding).strip()
        return str(process)
    except Exception as error:
        logger.warning(f"Failed to get git revision: {error}")
        return "Not a git repo"


def expand_environment_variables(cmd: str, new_env: dict) -> str:
    """Expand environment variables present in the benchmark cmd
    with the existing environment. Additionally, if the benchmark has
    additional environment variables to be used, expand the command
    with those variables as well

    Args:
        cmd (str): benchmark command
        env (dict): the new environment variables to be used in the subprocess
    Returns:
        cmd (str) with environment variables expanded
    """

    # temporarily set os.environ to new env vars
    orig_env = copy.deepcopy(os.environ)
    os.environ = new_env

    # expand vars against the new environment variables and revert os.environ
    cmd = os.path.expandvars(cmd)
    os.environ = orig_env

    return cmd


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


def preprocess_args(args: argparse.Namespace) -> argparse.Namespace:
    """Resolve any gaps or inconsistencies in the arguments provided.

    Args:
        args (argparse.Namespace): The arguments passed to this benchmarking run

    Returns:
        args (argparse.Namespace): args, but with any issues resolved

    """

    # Force allow-wandb if user wants to upload checkpoints to wandb
    if "wandb" in args.upload_checkpoints:
        args.allow_wandb = True

    return args
