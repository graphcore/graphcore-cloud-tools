# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import logging
import re
from pathlib import Path

# Get the module logger
logger = logging.getLogger(__name__)


def create_variants(benchmark_dict: dict) -> list:
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
            raise ValueError("'parameters' defined are neither a list nor a dict")

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
    variant_names = create_variants(benchmark_dict)

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
        ignore_wandb: bool,
        compile_only: bool,
        examples_location: str = None,
) -> str:
    """Create the actual command to be run from an unformatted string.

    Args:
        benchmark_dict (dict): Benchmark as specified in the yaml file,
            pre-formating to fill in variables
        variant_dict (dict): Variant specification, containing all the actual
            values of the variables to be used to construct this command
        ignore_wandb (bool): Whether or not to ignore wandb flags passed to the
            original command
        compile_only (bool): Whether or not to pass a `--compile-only` flag to
            the command. NOTE: This will only work if the app being run itself
            has implemented a `--compile-only` argument
        examples_location (str): Location of the examples directory in system.
            If not provided, defaults to assuming examples dir is located in
            home dir.

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

    if examples_location is None:
        examples_location = Path.home()
    resolved_file = str(Path(examples_location, benchmark_dict["location"], called_file).resolve())
    cmd = cmd.replace(called_file, resolved_file)

    if ignore_wandb and "--wandb" in cmd:
        logger.info("Both '--ignore-wandb' and '--wandb' were passed, '--ignore-wandb' "
                    "is overriding, purging '--wandb' from command.")
        cmd = cmd.replace("--wandb", "")

    if compile_only:
        logger.info("'--compile-only' was passed here. Appending '--compile-only' to " "the benchmark command.")
        cmd = cmd + " --compile-only"

        # Dont import wandb if compile only mode
        if "--wandb" in cmd:
            logger.info("--compile-only was passed, and wandb is not used for "
                        "compile only runs, purging '--wandb' from command.")
            cmd = cmd.replace("--wandb", "")

        # Remove vipu settings that prevent from running in compile-only mode
        cmd = re.sub(r"--vipu-partition.*?=.*?\S*", "", cmd)
        cmd = re.sub(r"--vipu-server-host.*?=.*?\S*", "", cmd)
        cmd = re.sub(r"--vipu-server-port.*?.*?\S*", "", cmd)

    # Cleanse the string of new line chars and extra spaces
    cmd = " ".join(cmd.replace("\n", " ").split())

    logger.info(f"new cmd = '{cmd}'")

    return cmd
