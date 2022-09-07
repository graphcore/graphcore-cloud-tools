# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import logging
import os
import re
import subprocess
from argparse import ArgumentParser
from pathlib import Path

# Get the module logger
logger = logging.getLogger(__name__)


def create_variants(benchmark_name: str, benchmark_dict: dict) -> list:
    """Create all variants from a benchmark entry.

    Note:
        There are two different ways to create variants from a benchmark entry:
        Declarative and Matrix-style

        With the first, when parameter values are listed, values for each
        parameter are matched by their index in the list only, and variants are
        created for each such combination. For example:
            - batch_size: [3, 4, 5]
            - gradient_accumulation: [150, 120, 90]
        Will result in 3 variants as such:
            - variant 1: batch_size=3, gradient_accumulation=150
            - variant 2: batch_size=4, gradient_accumulation=120
            - variant 3: batch_size=5, gradient_accumulation=90
        The length of the shortest list determines the number of variants.

        As for the second, when parameter values are provided in a dict with {},
        variations are instead created by every possible combination of
        parameters. For example:
            - batch_size: {3, 4}
            - gradient_accumulation: {150, 120}
        Will result in 4 variants:
            - variant 1: batch_size=3, gradient_accumulation=150
            - variant 2: batch_size=3, gradient_accumulation=120
            - variant 3: batch_size=4, gradient_accumulation=150
            - variant 4: batch_size=4, gradient_accumulation=120
        Dicts can have varying numbers of values, the above rule will still
        apply.

    Args:
        benchmark_name (str): Benchmarks name as given in the spec yaml file
        benchmark_dict (dict): benchmark entry itself in yaml file

    Returns:
        variants (list): List of all variants from the given benchmark entry

    """

    variants = [{}]
    if "parameters" in benchmark_dict:
        # Matching parameters as listed (see notes)
        if isinstance(benchmark_dict["parameters"], list):
            names = benchmark_dict["parameters"][0]

            variants = []
            for vals in benchmark_dict["parameters"][1:]:
                new_variant = {}
                for k, v in zip(names, vals):
                    new_variant[k] = str(v)

                variants.append(new_variant)

        # Matching parameters by every possible combination
        elif isinstance(benchmark_dict["parameters"], dict):
            for name, valstr in benchmark_dict["parameters"].items():
                current_variants = variants
                variants = []

                vals = str(valstr).split(",")
                for v in vals:
                    if v is not None:
                        for c in current_variants:
                            x = c.copy()
                            x[name] = v
                            variants.append(x)

        else:
            err = (f"In {benchmark_name} in {benchmark_dict['benchmark_path']},"
                   " the 'parameters' are defined in neither a list style or "
                   "a dict style. They must be defined as one of the two "
                   "(using a comma seperated list, optionally surrounded by "
                   "square brackets, or as a dict, surrounded by curly "
                   "brackets).")
            logger.error(err)
            raise ValueError(err)

    return variants


def get_benchmark_variants(benchmark_name: str, benchmark_dict: dict) -> list:
    """Get all named variations of a benchmark.

    Args:
        benchmark_name (str): Benchmarks name as given in the spec yaml file
        benchmark_dict (dict): benchmark entry itself in yaml file

    Returns:
        variations (list): List of all possible variants from this benchmark

    """

    # Create variants from benchmark
    variant_names = create_variants(benchmark_name, benchmark_dict)

    variants = []
    for variant in variant_names:
        work_str = benchmark_name

        for k in sorted(variant.keys()):
            work_str += "_" + k + "_" + variant[k]

        variants.append({"name": work_str, "config": variant})

    return variants


def formulate_benchmark_command(
        benchmark_dict: dict,
        variant_dict: dict,
        args: ArgumentParser,
) -> str:
    """Create the actual command to be run from an unformatted string.

    Args:
        benchmark_dict (dict): Benchmark as specified in the yaml file,
            pre-formating to fill in variables
        variant_dict (dict): Variant specification, containing all the actual
            values of the variables to be used to construct this command
        args (ArgumentParser): Arguments passed to this benchmarking run

    Returns:
        cmd (str): The final, formatted command to be run

    """

    # Format the command (containing variables) by using the variant dict
    # (containing the actual values)
    cmd = benchmark_dict["cmd"].format(**variant_dict)
    cmd = cmd.replace("\n", " ")

    cmd = " ".join(cmd.split())
    logger.info(f"original cmd = '{cmd}'")
    logger.info(f"Cleaning and modifying command if required...")

    # Append application location from yaml to command
    cmd_parts = cmd.split(" ")
    if "python3" in cmd_parts:
        py_name = "python3"
    else:
        py_name = "python"
    called_file = cmd_parts[cmd_parts.index(py_name) + 1]

    resolved_file = str(Path(called_file).resolve())
    cmd = cmd.replace(called_file, resolved_file)

    if not args.allow_wandb and "--wandb" in cmd:
        logger.info("'--allow-wandb' was not passed, however '--wandb' is an "
                    "argument provided to the benchmark. The default value of "
                    "'--allow-wandb' (False) is overriding, purging '--wandb' "
                    "and all args containing 'wandb' from command.")
        cmd = " ".join([x for x in cmd.split(" ") if "--wandb" not in x])

    if args.compile_only:
        logger.info("'--compile-only' was passed here. Appending '--compile-only' to the benchmark command.")
        cmd = cmd + " --compile-only"

        # Dont import wandb if compile only mode
        if "--wandb" in cmd:
            logger.info("--compile-only was passed, and wandb is not used for "
                        "compile only runs, purging '--wandb' and all args "
                        "containing 'wandb' in their names from command.")
            cmd = " ".join([x for x in cmd.split(" ") if "--wandb" not in x])

        # Remove vipu settings that prevent from running in compile-only mode
        cmd = re.sub(r"--vipu-partition.*?=.*?\S*", "", cmd)
        cmd = re.sub(r"--vipu-server-host.*?=.*?\S*", "", cmd)
        cmd = re.sub(r"--vipu-server-port.*?.*?\S*", "", cmd)

    # Cleanse the string of new line chars and extra spaces
    cmd = " ".join(cmd.replace("\n", " ").split())

    logger.info(f"new cmd = '{cmd}'")

    return cmd


def get_poprun_hosts(cmd: list) -> list:
    """Get names/IPs of poprun hosts defined in the `--host` argument.

    Args:
        cmd (list): The command being run, which may include a poprun call that
            specifies hosts

    Returns:
        poprun_hostnames (list): names/IPs of poprun hosts
    
    """

    # Find where in the command list "poprun", "host" and "python" exist
    # If poprun is not called, then it cannot be multihost + multi-instance
    try:
        poprun_index = cmd.index("poprun")
    except:
        logger.info("poprun not called, assuming this is a single-host, single-instance benchmark.")
        return []

    # If "--host" is not defined, then instances must be running on one host
    try:
        host_index = cmd.index([x for x in cmd if "--host" in x][0])
    except:
        logger.info("'--host' argument not provided, assuming all poprun "
                    "instances defined in this benchmark will run on this host "
                    "only")
        return []

    # Watch out for "python" instead of "python3"
    try:
        python_index = cmd.index("python3")
    except:
        python_index = cmd.index("python")

    poprun_hostnames = []
    if (poprun_index < host_index < python_index):
        # Hostnames can be passed with "=" or just with a space to the arg
        if "=" in cmd[host_index]:
            poprun_hostnames = cmd[host_index].split("=")[1].split(",")
        else:
            poprun_hostnames = cmd[host_index + 1].split(",")

    num_hosts = len(poprun_hostnames)

    if num_hosts > 1:
        logger.info("Benchmark is running multiple instances over multiple hosts, preparing all hosts.")
    else:
        logger.info("Only one value has been passed to the '--host' argument, "
                    "assuming all instances defined for this benchmark will "
                    "run on this host only")

    # Find all forms of ID for this local machine
    possible_hostnames = []
    possible_hostnames.append(os.uname()[1])

    # Query system for internal/external IPs
    try:
        possible_hostnames, _ = subprocess.Popen(
            ["hostname", "-I"],
            stdout=subprocess.PIPE,
        ).communicate()
        # All possible IPs (formatted output)
        possible_hostnames = str(possible_hostnames.decode("utf-8")).split(" ")[:-1]
    except:
        possible_hostnames = [""]

    # Remove this machines name/IP from the list
    for hostname in poprun_hostnames:
        if any(hostname in x for x in possible_hostnames):
            poprun_hostnames.remove(hostname)

    if len(poprun_hostnames) == num_hosts:
        logger.info("This machines hostname/IP could not be found in the "
                    "values provided to the '--host' argument for poprun. "
                    "Assuming that the first value in the list provided is the "
                    "this machines hostname, and skipping interacting with the "
                    "filesystem on it. If this is not the case, please use "
                    "either the host name as seen in the $HOSTNAME environment "
                    "variable, or using internal/external IP addresses.")
        poprun_hostnames = poprun_hostnames[1:]

    return poprun_hostnames
