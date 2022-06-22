# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import argparse
import logging
import os
import selectors
import shlex
import subprocess
import sys
import threading
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path
from typing import Tuple

import yaml

from examples_utils.benchmarks.command_utils import formulate_benchmark_command, get_benchmark_variants
from examples_utils.benchmarks.environment_utils import get_mpinum, merge_environment_variables
from examples_utils.benchmarks.logging_utils import print_benchmark_summary
from examples_utils.benchmarks.metrics_utils import derive_metrics, extract_metrics, get_results_for_compile_time
from examples_utils.benchmarks.profiling_utils import add_profiling_vars

# Get the module logger
logger = logging.getLogger()


def run_and_monitor_progress(cmd: list, listener: TextIOWrapper, timeout: int, **kwargs) -> Tuple[str, str, int]:
    """Run the benchmark monitor progress.

    Args:
        cmd (list): The command to be run, as a list for use by subprocess
        listener (TextIOWrapper): Listener that takes the output from the process
        timeout (int): Seconds until the process will timeout, forcing termination

    Returns:
        output (str): stdout from the process
        err (str): stderr from the process
        exitcode (int): The process exitcode

    """

    # Begin in subprocess
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=80, **kwargs)

    # All this appears to be for reading process output ------------------------
    outs = [[], []]

    def proc_thread():
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)
        sel.register(proc.stderr, selectors.EVENT_READ)
        eof = False
        while not eof:
            for key, _ in sel.select():
                stream = key.fileobj
                data = stream.read1(80)
                try:
                    data = data.decode()
                    if not data:
                        eof = True
                    listener.write(data)
                    listener.flush()

                    if stream is proc.stdout:
                        outs[0].append(data)
                    else:
                        outs[1].append(data)
                except UnicodeDecodeError as e:
                    print(f"{e} \n Unable to decode: {data}. ")

        (a, b) = proc.communicate()
        outs[0].append(a.decode())
        listener.write(a.decode())
        outs[1].append(b.decode())
        listener.write(b.decode())
        listener.flush()

    t = threading.Thread(target=proc_thread, name="proc_thread")
    t.start()

    timeouts = [0.5, 1, 2, 3, 6, 15, 30, 60]
    tcount = 0
    ts_per_line = 40
    total_time = 0
    timeout_error = False
    while True:
        # show progress
        tindex = min(int(tcount / ts_per_line), len(timeouts) - 1)
        t.join(timeouts[tindex])
        total_time += timeouts[tindex]

        # Stop monitoring progress when benchmarking process thread dies
        if not t.is_alive():
            break

        # Monitor if benchmark has timed out
        if timeout and total_time >= timeout:
            logger.critical("TIMEOUT")
            timeout_error = True
            proc.kill()

        if tcount % ts_per_line == 0:
            if tcount != 0:
                sys.stderr.write("\n")
            sys.stderr.write("                        ")
        sys.stderr.write(".")
        sys.stderr.flush()
        tcount += 1

    if tcount != 0:
        sys.stderr.write("\n")
    # ---------------------------------------------------------------------------

    # return the info of the running of the benchmark
    output, err = "".join(outs[0]), "".join(outs[1])
    exitcode = proc.returncode
    if timeout_error:
        err = "Timeout"

    return (output, err, exitcode)


def run_benchmark_variant(
        variant_name: str,
        benchmark_name: str,
        variant_dict: dict,
        benchmark_dict: dict,
        listener: TextIOWrapper,
        args: argparse.ArgumentParser,
) -> dict:
    """Run a variant and collect results.

    Note:
        For each variant:
        1) Create the variants (benchmark_test (cases)) and define the UID
            (variant_id, aka benchmark_test (case))
        2) Define and clean the command (swap out markers) Clean the command
        3) Define the config["mpirun"]
        4) Define the Working Dir
        5) Create the logs directory
        6) Actually run the benchmark
        7) Calculate and log end time and total run time
            - IF errored, log logs and exit (if not ignore errors)
        8) Write logs to files to a file - extract metrics and post-process them
        9) Return a dictionary of results dictionaries

    Args:
        variant_name (str): The name of the variant to be run
        benchmark_name (str): The name of the benchmark to be run
        variant_dict (dict): The variant definition created by the formatting
            and evaluation of the benchmark definition
        benchmark_dict (dict): The benchmark definition from the yaml file
        listener (TextIOWrapper): Open file to collect stdout/stderr from the
            process running the variant
        args (argparse.ArgumentParser): Arguments passed to this script

    Returns:
        variant_result (dict): The results from this variants run

    """

    logger.info(f"Running variant: '{variant_name}'")

    # Purge data fields for compile only tests
    if args.compile_only:
        benchmark_dict["data"] = {}
        benchmark_dict["derived"] = {}
        logger.info("Removed data metrics for compile only benchmark")

    # Create the actual command for the variant
    variant_command = formulate_benchmark_command(benchmark_dict, variant_dict, args.ignore_wandb, args.compile_only,
                                                  args.examples_location)

    # Expand any environment variables in the command and split the command
    # into a list, respecting things like quotes, like the shell would
    cmd = shlex.split(os.path.expandvars(variant_command))

    # Define where the benchmark should be run (dir containing public_examples)
    cwd = str(Path.cwd().resolve())
    logger.info(f"\tcwd = '{cwd}'")

    # Create the log directory
    variant_logdir = Path(args.logdir, variant_name)
    if not variant_logdir.exists():
        variant_logdir.mkdir(parents=True)
    outlog_path = Path(variant_logdir, "stdout.log")
    errlog_path = Path(variant_logdir, "stderr.log")

    # Set the environment variables
    new_env = {}
    new_env["POPLAR_LOG_LEVEL"] = "INFO"
    new_env["TF_CPP_VMODULE"] = "poplar_compiler=1"
    new_env["POPART_LOG_LEVEL"] = "INFO"

    # Add profiling variables
    if args.profile:
        new_env = add_profiling_vars(new_env, variant_name, cwd)

    # Merge environment variables from benchmark and here with existing
    # environment variables
    env = merge_environment_variables(new_env, benchmark_dict)

    start_time = datetime.now()
    logger.info(f"Start test: {start_time}")
    output, err, exitcode = run_and_monitor_progress(
        cmd,
        listener,
        args.timeout,
        cwd=cwd,
        env=env,
    )
    end_time = datetime.now()
    total_runtime = (end_time - start_time).total_seconds()
    logger.info(f"End test: {end_time}")
    logger.info(f"Total runtime: {total_runtime} seconds")

    # Analyse profile data and output to logs
    # if args.profile:
    #     output += analyse_profile(variant_name, cwd)

    # If process didnt end as expected
    if exitcode:
        logger.critical(f"Benchmark ERROR, return code: ({str(exitcode)})")
        logger.critical("STDOUT:")
        logger.critical(output)
        logger.critical("STDERR:")
        logger.critical(err)
        sys.exit(exitcode)

    with open(outlog_path, "w") as f:
        f.write(output)
    with open(errlog_path, "w") as f:
        f.write(err)

    # Get 'data' metrics, these are metrics scraped from the log
    results, extraction_failure = extract_metrics(
        benchmark_dict.get("data", {}),
        output + err,
        exitcode,
        get_mpinum(variant_command),
    )

    # Get 'derived' metrics, these are metrics 'derived' from other metrics
    results, derivation_failure = derive_metrics(
        benchmark_dict.get("derived", {}),
        variant_dict,
        results,
        exitcode,
    )

    # Get compile_time metrics (scraped from the log)
    results = get_results_for_compile_time(
        results,
        err,
        exitcode,
    )

    # Store metrics/details for this variant and return
    variant_result = {
        "benchmark_path": benchmark_dict["benchmark_path"],
        "benchmark_name": benchmark_name,
        "variant_name": variant_name,
        "params": variant_dict,
        "command": variant_command,
        "results": results,
        "timestamp": start_time,
        "end_time": end_time,
        "compilation_end_time": results["total_compiling_time"]["mean"],
        "test_duration": total_runtime,
        "exitcode": exitcode,
    }

    # These failure points are not caught normally, check here
    possible_failure_points = [
        extraction_failure,
        derivation_failure,
    ]
    if any(possible_failure_points) and exitcode == 0:
        variant_result["exitcode"] = 1

    return variant_result


def run_benchmarks(args: argparse.ArgumentParser):
    """Run benchmarks.

    Args:
        args (argparse.ArgumentParser): Arguments passed to run the benchmarks
            with

    """

    # Resolve paths to benchmarks specs
    args.spec = [str(Path(file).resolve()) for file in args.spec]

    spec_files = ",".join([str(sf) for sf in args.spec if ".yml" in str(sf)])
    logger.info(f"Running benchmark suite: '{spec_files}'")

    # Check if DATASETS_DIR exists
    datasets_dir = os.getenv("DATASETS_DIR")
    if datasets_dir:
        logger.info(f"Datasets directory: '{datasets_dir}'")
    else:
        logger.error("Datasets directory has not been set.  If the model "
                     "requires a dataset, please set DATASETS_DIR env at the "
                     "base of the dataset directory. For example run: 'export "
                     "DATASETS_DIR=/localdata/datasets/'")
        sys.exit(1)

    # Load all benchmark configs from all files given
    spec = {}
    for spec_file in args.spec:
        logger.debug(f"Examining: '{spec_file}'")

        found_benchmarks = yaml.load(open(spec_file).read(), Loader=yaml.FullLoader)
        # Add the file each benchmark config came from
        for _, v in found_benchmarks.items():
            v["benchmark_path"] = spec_file
        spec.update(found_benchmarks)

    results = {}
    output_log_path = Path(args.logdir, "output.log")
    with open(output_log_path, "w", buffering=1) as listener:
        logger.info(f"Logs at: {output_log_path}")

        variant_dictionary = {}
        for benchmark_name in sorted(spec.keys()):
            # Do not treat the common options or similar specifications as
            # benchmarks
            if "options" in benchmark_name:
                continue

            # Get all benchmark variants made by combinations of parameters
            # specified in the benchmark
            benchmark_spec = spec.get(benchmark_name, {})
            variant_list = get_benchmark_variants(benchmark_name, benchmark_spec)
            variant_dictionary[benchmark_name] = variant_list

            for benchmark in list(variant_dictionary.keys()):
                # if no benchmarks were provided, or this benchmark is the
                # exact one provided, proceed
                if args.benchmark is None or benchmark in args.benchmark:
                    continue

                # Keep any variants that fit the name provided in args.benchmark
                name_variants = variant_dictionary[benchmark]
                selected_variants = []
                for v in name_variants:
                    if v["name"] in args.benchmark:
                        selected_variants.append(v)
                variant_dictionary[benchmark] = selected_variants

                if len(selected_variants) == 0:
                    del variant_dictionary[benchmark]

        # If no variants are possible, exit
        if not variant_dictionary:
            logger.error("No valid benchmarks selected")
            sys.exit(1)

        # Run each variant
        for benchmark_name in variant_dictionary:
            benchmark_spec = spec.get(benchmark_name, {})
            logger.info("Running " + benchmark_name)
            logger.info(f"Running {str(len(variant_dictionary[benchmark_name]))} variants:")
            for variant_name in variant_dictionary[benchmark_name]:
                name = variant_name.get("name")
                logger.info(f"\t{name}")

            result_list = []
            for variant in variant_dictionary[benchmark_name]:
                benchmark_result = run_benchmark_variant(
                    variant["name"],
                    benchmark_name,
                    variant["config"],
                    benchmark_spec,
                    listener,
                    args,
                )
                result_list.append(benchmark_result)

            results[benchmark_name] = result_list
            print(results)

    # Print PASSED/FAILED summary
    print_benchmark_summary(results)


def benchmarks_parser(parser: argparse.ArgumentParser):
    """Add benchmarking arguments to argparse parser"""

    parser.add_argument(
        "--spec",
        required=True,
        type=str,
        nargs="+",
        help="Yaml files with benchmark spec",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        nargs="+",
        help="List of benchmark ids to run",
    )
    parser.add_argument(
        "--compile-only",
        action="store_true",
        help="Enable compile only options in compatible models",
    )
    parser.add_argument(
        "--ignore-wandb",
        action="store_true",
        help="Ignore any wandb commands",
    )
    parser.add_argument(
        "--logdir",
        default=None,
        type=str,
        help="Folder to place log files",
    )
    parser.add_argument(
        "--logging",
        choices=["DEBUG", "INFO", "ERROR", "CRITICAL", "WARNING"],
        default="INFO",
        help="Specify the logging level",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help=("Enable profiling for the benchmarks, setting the appropriate "
              "environment variables and storing profiling reports in the cwd"),
    )
    parser.add_argument(
        "--timeout",
        default=None,
        type=int,
        help="Maximum time allowed for any benchmark/variant (in seconds)",
    )
    parser.add_argument(
        "--examples-location",
        default=None,
        type=int,
        help="Location of the examples directory, defaults to user dir.",
    )
