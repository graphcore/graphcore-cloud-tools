# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import argparse
import logging
import os
import selectors
import shlex
import subprocess
import sys
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from io import TextIOWrapper
from pathlib import Path
from typing import Tuple, Union, Dict, List
import yaml
import json
import time
from examples_utils.benchmarks.command_utils import (formulate_benchmark_command, get_benchmark_variants,
                                                     get_local_poprun_hosts, get_poprun_config)
from examples_utils.benchmarks.distributed_utils import (remove_distributed_filesystems, setup_distributed_filesystems)
from examples_utils.benchmarks.environment_utils import (
    check_env,
    enter_benchmark_dir,
    get_git_commit_hash,
    get_mpinum,
    infer_paths,
    expand_environment_variables,
    merge_environment_variables,
    preprocess_args,
)
from examples_utils.benchmarks.logging_utils import (WANDB_AVAILABLE, get_latest_checkpoint_path, get_wandb_link,
                                                     print_benchmark_summary, save_results, upload_checkpoints,
                                                     upload_compile_time)
from examples_utils.benchmarks.metrics_utils import additional_metrics, derive_metrics, extract_metrics
from examples_utils.benchmarks.custom_metrics import process_registered_metrics, import_metrics_hooks_files
from examples_utils.benchmarks.profiling_utils import add_profiling_vars
from examples_utils.benchmarks.slurm_utils import (check_slurm_configured, configure_slurm_job,
                                                   run_and_monitor_progress_on_slurm)

try:
    # Plotting of IPU usage is only supported with [jupyter] requirements
    # but the function will be called whenever `--gc-monitor` argument is set
    # so we define a dummy function when the dependencies are not available.
    from .monitoring_utils import plot_ipu_usage
except (ImportError, ModuleNotFoundError) as error:

    def plot_ipu_usage(*args, **kwargs):
        """Does nothing install the package with examples-utils[jupyter] to
        plot IPU usage during benchmarks"""
        return None


# Get the module logger
logger = logging.getLogger(__name__)

# Progress spinner frames to iterate through
progress_frames = [
    "      ",
    ">     ",
    "=>    ",
    "==>   ",
    "===>  ",
    "====> ",
    "<====>",
    " <====",
    "  <===",
    "   <==",
    "    <=",
    "     <",
]

# A dictionary which defines a benchmark
BenchmarkDict = Dict


def should_reattempt_benchmark(variant, output, err, exitcode) -> Union[bool, str]:
    if "Timeout" in err:
        return False
    is_a_notebook = "examples_utils.benchmarks.notebook_utils" in variant["cmd"]
    if is_a_notebook and "ModuleNotFoundError" in err and exitcode != 0:
        if "Successfully installed" in output:
            return "Notebook has installed some packages, need to restart kernel"

    return False


def run_and_monitor_progress(cmd: list,
                             listener: TextIOWrapper,
                             timeout: int = None,
                             monitor_ipus: bool = True,
                             **kwargs) -> Tuple[str, str, int, List[str]]:
    """Run the benchmark monitor progress.

    Args:
        cmd (list): The command to be run, as a list for use by subprocess
        listener (TextIOWrapper): Listener that takes the output from the process
        timeout (int): Seconds until the process will timeout, forcing termination
        kwargs: all additional keyword arguments are passed to `subprocess.Popen`.

    Returns:
        output (str): stdout from the process
        err (str): stderr from the process
        exitcode (int): The process exitcode

    """

    # Begin in subprocess
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=80, **kwargs)

    # All this appears to be for reading process output ------------------------
    outs = [[], []]
    ipu_monitoring: List[str] = []

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
                    pass

        (a, b) = proc.communicate()
        outs[0].append(a.decode())
        listener.write(a.decode())
        outs[1].append(b.decode())
        listener.write(b.decode())
        listener.flush()

    t = threading.Thread(target=proc_thread, name="proc_thread")
    t.start()

    def monitor_thread():
        while t.is_alive():
            try:
                timestamp = datetime.now().strftime("%Y-%m-%d-%H.%M.%S.%f")
                ipu_log_line = json.dumps({
                    "timestamp": timestamp,
                    **json.loads(subprocess.check_output(["gc-monitor", "--json"]))
                })
                ipu_monitoring.append(f"{ipu_log_line}\n")
                time.sleep(5)
            except:
                pass

    if monitor_ipus:
        t_monitor = threading.Thread(target=monitor_thread, name="monitor_thread")
        t_monitor.start()

    total_time = 0
    timeout_error = False
    while True:
        # Check if benchmarking process thread has terminated every second
        t.join(1)
        if not t.is_alive():
            if monitor_ipus:
                t_monitor.join()
            break
        total_time += 1

        # Monitor if benchmark has timed out
        if (timeout is not None) and (total_time >= timeout):
            logger.error("TIMEOUT")
            timeout_error = True
            proc.kill()

        sys.stderr.write("\r")
        index = total_time % len(progress_frames)
        sys.stderr.write(f"\tBenchmark elapsed time: {str(timedelta(seconds=total_time))} "
                         f"({total_time} seconds) {progress_frames[index]}")
        sys.stderr.flush()

    sys.stderr.write("\r")
    sys.stderr.write("\n")
    # ---------------------------------------------------------------------------

    # return the info of the running of the benchmark
    output, err = "".join(outs[0]), "".join(outs[1])
    exitcode = proc.returncode
    if timeout_error:
        err += f"\nTimeout ({timeout})\n"

    return (output, err, exitcode, ipu_monitoring)


def run_benchmark_variant(
        variant_name: str,
        benchmark_name: str,
        variant_dict: dict,
        benchmark_dict: dict,
        listener: TextIOWrapper,
        args: argparse.Namespace,
) -> dict:
    """Run a variant and collect results.

    Args:
        variant_name (str): The name of the variant to be run
        benchmark_name (str): The name of the benchmark to be run
        variant_dict (dict): The variant definition created by the formatting
            and evaluation of the benchmark definition
        benchmark_dict (dict): The benchmark definition from the yaml file
        listener (TextIOWrapper): Open file to collect stdout/stderr from the
            process running the variant
        args (argparse.Namespace): Arguments passed to this script

    Returns:
        variant_result (dict): The results from this variants run

    """

    if variant_name != benchmark_name:
        logger.info(f"\tRunning variant: '{variant_name}'")

    # Purge data fields for compile only tests
    if args.compile_only:
        benchmark_dict["data"] = {}
        benchmark_dict["derived"] = {}
        logger.info("Removed data metrics for compile only benchmark")
    # Change cwd to where the benchmarks file was
    enter_benchmark_dir(benchmark_dict)
    # get the hash of the head commit of the benchmark directory
    git_commit_hash = get_git_commit_hash()

    # Create the actual command for the variant
    variant_command = formulate_benchmark_command(benchmark_dict, variant_dict, args)

    # Set the environment variables
    new_env = {}
    new_env["POPLAR_LOG_LEVEL"] = args.logging
    new_env["POPART_LOG_LEVEL"] = args.logging
    new_env["TF_CPP_VMODULE"] = "poplar_compiler=1"

    # Add profiling variables
    if args.profile:
        new_env = add_profiling_vars(new_env, variant_name, cwd)

    # Merge environment variables from benchmark and here with existing
    # environment variables
    env = merge_environment_variables(new_env, benchmark_dict)

    # Expand any environment variables in the command and split the command
    # into a list, respecting things like quotes, like the shell would
    cmd = shlex.split(expand_environment_variables(variant_command, env))

    # Define where the benchmark should be run (dir containing examples)
    cwd = str(Path.cwd().resolve())
    logger.info(f"\tcwd = '{cwd}'")

    # Create the log directory
    variant_log_dir = Path(args.log_dir, variant_name)
    if not variant_log_dir.exists():
        variant_log_dir.mkdir(parents=True)
    outlog_path = Path(variant_log_dir, "stdout.log")
    errlog_path = Path(variant_log_dir, "stderr.log")

    # Infer examples, SDK and venv path for this benchmark
    args = infer_paths(args, benchmark_dict)
    logger.info(f"Datasets directory: '{os.getenv('DATASETS_DIR')}'")

    # Detect if a requirements file has been provided
    reqs = benchmark_dict.get("requirements_file")
    if reqs and not Path(reqs).exists():
        raise FileNotFoundError(f"Invalid python requirements where specified at {reqs}")

    # Check if poprun is being used
    poprun_config = get_poprun_config(args, cmd)

    # only validate user supplied hosts if not submitting on SLURM
    # Similarly, only install requirements if not submitting on SLURM
    if not args.submit_on_slurm:
        # Detect if benchmark requires instances running (not just compiling) on
        # other hosts, and then prepare hosts
        poprun_hostnames = get_local_poprun_hosts(poprun_config)
        is_distributed = len(poprun_hostnames) > 1 and not args.compile_only

        if is_distributed:
            if args.no_code_sync:
                logger.info("Filesystem (venv/code) syncing has been disabled "
                            "with the '--no-code-sync' arg. Skipping copying "
                            f"the files at {args.venv_path} and "
                            f"{args.examples_path} automatically to all hosts.")
            else:
                # Setup temporary filesystems on all hosts and modify cmd to use this
                setup_distributed_filesystems(args, poprun_hostnames)

        if reqs:
            logger.info(f"Install python requirements")
            subprocess.check_output([sys.executable, "-m", "pip", "install", "-r", str(reqs)])

    # configure benchmark to run on slurm
    if args.submit_on_slurm:
        slurm_config = configure_slurm_job(args, benchmark_dict, poprun_config, cmd, variant_name, variant_log_dir, cwd,
                                           env)

    start_time = datetime.now()
    logger.info(f"Start test: {start_time}")
    need_to_run = True
    monitor_log = []
    exitcode = 0
    stdout = stderr = ""
    while need_to_run:
        if args.submit_on_slurm:
            stdout, stderr, exitcode = run_and_monitor_progress_on_slurm(listener=listener, **slurm_config)
        else:
            stdout, stderr, exitcode, monitor_log = run_and_monitor_progress(
                cmd,
                listener,
                args.timeout,
                monitor_ipus=args.gc_monitor,
                cwd=cwd,
                env=env,
            )
        need_to_run = should_reattempt_benchmark(benchmark_dict, stdout, stderr, exitcode)
        if need_to_run:
            logger.info(f"Re-running benchmark because: {need_to_run}")

    end_time = datetime.now()
    total_runtime = (end_time - start_time).total_seconds()
    logger.info(f"End test: {end_time}")
    logger.info(f"Total runtime: {total_runtime} seconds")

    # TODO: Analyse profile data and output to logs with REPTIL
    # if args.profile:
    #     output += analyse_profile(variant_name, cwd)

    # Teardown temporary filesystem on all hosts
    if args.no_code_sync:
        logger.info("Filesystem (venv/code) syncing has been disabled "
                    "with the '--no-code-sync' arg. Skipping removing "
                    f"the files at {args.venv_path} and "
                    f"{args.examples_path} automatically on all hosts.")
        args.remove_dirs_after = False

    if not args.submit_on_slurm and args.remove_dirs_after:
        if is_distributed:
            remove_distributed_filesystems(args, poprun_hostnames)
        else:
            logger.info("'--remove-dirs-after' has been set but this "
                        "benchmark has not been specified to use multiple "
                        "hosts, and so there are no remote temporary "
                        "filesystems to delete. Local filesystems on this "
                        "host will not automatically be deleted.")

    # If process didnt end as expected
    if exitcode:
        err = (f"Benchmark ERROR, exited with code: ({str(exitcode)}). Please check logs for more information.")
        logger.error(err)

        if args.stop_on_error:
            error_tail = "\n\t" + "\n\t".join(stderr.splitlines()[-10:]) + "\n"
            logger.error(f"Last 10 lines of stderr from {variant_name}:{error_tail}")
            sys.excepthook = lambda exctype, exc, traceback: print("{}: {}".format(exctype.__name__, exc))
            raise RuntimeError(err)
        else:
            logger.info("Continuing to next benchmark as `--stop-on-error` was not passed")

    # Get 'data' metrics, these are metrics scraped from the log
    results, extraction_failure = extract_metrics(
        benchmark_dict.get("data", {}),
        stdout + stderr,
        exitcode,
        get_mpinum(variant_command),
    )

    if args.additional_metrics:
        results = additional_metrics(
            results,
            total_runtime,
            str(' '.join(cmd)),
            exitcode,
            new_env,  # just additional environment variables
            git_commit_hash)

    # Get 'derived' metrics, these are metrics 'derived' from other metrics
    results, derivation_failure = derive_metrics(
        benchmark_dict.get("derived", {}),
        variant_dict,
        results,
        exitcode,
    )

    # Get compile_time metrics (scraped from the log)
    results = process_registered_metrics(
        results,
        stdout,
        stderr,
        exitcode,
    )

    # Add compile time results to wandb link, if wandb was imported by app
    if WANDB_AVAILABLE:
        wandb_link = get_wandb_link(stderr)
        if wandb_link is not None:
            upload_compile_time(wandb_link, results)

    # Find checkpoints from this run
    checkpoint_root_dir = Path(benchmark_dict["benchmark_path"]).parent.joinpath(benchmark_dict.get("location", ""))
    latest_checkpoint_path = get_latest_checkpoint_path(checkpoint_root_dir, variant_command)

    # Upload checkpoints if required
    if args.upload_checkpoints and latest_checkpoint_path is not None:
        upload_checkpoints(
            upload_targets=args.upload_checkpoints,
            checkpoint_path=latest_checkpoint_path,
            benchmark_path=benchmark_dict["benchmark_path"],
            checkpoint_dir_depth=(4 if benchmark_dict.get("location") else 3),
            run_name=variant_name,
            stderr=stderr,
        )

    if not args.submit_on_slurm:
        with open(outlog_path, "w") as f:
            f.write(stdout)
        if monitor_log:
            with open(variant_log_dir / "ipu-monitor.jsonl", "w") as f:
                f.writelines(monitor_log)
            plot_ipu_usage(outlog_path.parent)
        with open(errlog_path, "w") as f:
            f.write(stderr)

    # Store metrics/details for this variant and return
    variant_result = {
        "benchmark_path": benchmark_dict["benchmark_path"],
        "benchmark_name": benchmark_name,
        "variant_name": variant_name,
        "params": variant_dict,
        "command": variant_command,
        "results": results,
        "start_time": str(start_time),
        "end_time": str(end_time),
        "compilation_end_time": str(results["total_compiling_time"]["mean"]),
        "test_duration": str(total_runtime),
        "exitcode": exitcode,
        "log_paths": {
            "out": str(outlog_path),
            "err": str(errlog_path)
        },
    }

    # These failure points are not caught normally, check here
    possible_failure_points = [
        extraction_failure,
        derivation_failure,
    ]
    if any(possible_failure_points) and exitcode == 0:
        variant_result["exitcode"] = 1

    if not args.submit_on_slurm:
        with open(variant_log_dir / "variant_result.json", "w") as f:
            json.dump(variant_result, f)

    return variant_result


def process_notebook_to_command(variant, name="unknown"):
    if "notebook" not in variant:
        return variant
    if "notebook" in variant and "cmd" in variant:
        raise ValueError("Invalid combination of entries 'notebook' and 'cmd' in " f"benchmark: {name}")
    notebook_def = variant.pop("notebook")
    if not isinstance(notebook_def, dict):
        notebook_def = {"file": str(notebook_def)}

    allowed_fields = {"file", "working_directory", "timeout"}
    unknown_entries = [f for f in notebook_def if f not in allowed_fields]
    if unknown_entries:
        raise yaml.YAMLError(f"Notebook entry '{name}' has un-recognised options: {unknown_entries}")
    variant["cmd"] = " ".join([
        f"python3",
        "-m",
        "examples_utils.benchmarks.notebook_utils",
        str(notebook_def['file']),
        str(notebook_def.get('working_directory', '.')),
    ] + (["--timeout", str(notebook_def['timeout'])] if "timeout" in notebook_def else []))

    return variant


def run_benchmarks(args: argparse.Namespace):
    """Run benchmarks.

    Args:
        args (argparse.Namespace): Arguments passed to run the benchmarks
            with

    """

    spec_files = ",".join([str(sf) for sf in args.spec if ".yml" in str(sf)])

    # Load all benchmark configs from all files given
    spec = {}
    for spec_file in args.spec:
        logger.info(f"Examining: '{spec_file}'")
    # Preprocess args to resolve any inconsistencies or cover up any gaps
    args = preprocess_args(args)

    # check if dispatching jobs to a SLURM queue
    if args.submit_on_slurm and check_slurm_configured():
        logger.info("Benchmarks to be submitted via SLURM")

    spec = parse_benchmark_specs(args.spec)
    return run_benchmarks_from_spec(spec, args)


def parse_benchmark_specs(spec_files: List[str]):
    """Parses a list of benchmark spec files into benchmarks definition"""
    # Resolve paths to benchmarks specs

    spec_files_str = ",".join([str(sf) for sf in spec_files if ".yml" in str(sf)])
    logger.info(f"Running benchmark suite: '{spec_files_str}'")

    # Load all benchmark configs from all files given
    spec: Dict[str, BenchmarkDict] = {}
    for spec_file in spec_files:
        logger.debug(f"Examining: '{spec_file}'")
        found_benchmarks = yaml.load(open(spec_file).read(), Loader=yaml.FullLoader)

        # Add the file each benchmark config came from
        for _, v in found_benchmarks.items():
            v["benchmark_path"] = spec_file
        spec.update(found_benchmarks)
    return spec


def run_benchmarks_from_spec(spec: Dict[str, BenchmarkDict], args: argparse.Namespace):
    results = {}
    output_log_path = Path(args.log_dir, "output.log")
    if args.custom_metrics_files is not None:
        import_metrics_hooks_files(args.custom_metrics_files)
    with open(output_log_path, "w", buffering=1) as listener:
        print("#" * 80)
        logger.info(f"Logs at: {output_log_path}")
        print("#" * 80 + "\n")

        # Only check explicitily listed benchmarks if provided
        if args.benchmark is None:
            benchmarks_list = list(spec.keys())
        else:
            benchmarks_list = args.benchmark

        for variant_name, variant in spec.items():
            variant = process_notebook_to_command(variant, variant_name)
        variant_dictionary = OrderedDict()
        for benchmark_name in benchmarks_list:
            # Check if this benchmark exists
            if benchmark_name not in list(spec.keys()):
                err = (f"Benchmark {benchmark_name} not found in any of the provided spec files, exiting.")
                logger.error(err)
                raise ValueError(err)

            # Do not treat the common options or similar specifications as
            # benchmarks
            if "options" in benchmark_name:
                continue

            # is provided, or they are explicitly named in --benchmarks
            if ((args.benchmark is None) and ("_conv" in benchmark_name) and (not args.include_convergence)):
                continue
            spec_entry = spec.get(benchmark_name, {})
            if "gen" in benchmark_name:
                spec_entry["generated"] = True
            if "synth" in benchmark_name:
                spec_entry["synthetic"] = True
            # Enforce DATASETS_DIR set only if this benchmark needs real data
            if not (spec_entry.get("generated") or spec_entry.get("synthetic")):
                if "DATASETS_DIR" not in os.environ:
                    err = (f"Benchmark '{benchmark_name}' requires a dataset "
                           "as it is not configured to use generated or "
                           "synthetic ('gen' or 'synth' in the benchmark name) "
                           "data. The environment variable 'DATASETS_DIR' is "
                           "required for locating the dataset for this "
                           "dataset. Please set the DATASETS_DIR environment "
                           "variable to be the base of the dataset directory. "
                           "For example, run: "
                           "'export DATASETS_DIR=/localdata/datasets/'")
                    logger.error(err)
                    raise ValueError(err)

            # Get all benchmark variants made by combinations of parameters
            # specified in the benchmark
            benchmark_spec = spec.get(benchmark_name, {})
            variant_list = get_benchmark_variants(benchmark_name, benchmark_spec)
            variant_dictionary[benchmark_name] = variant_list

        # If no variants are possible, exit
        if not variant_dictionary:
            err = "No valid benchmarks selected"
            logger.error(err)
            raise ValueError(err)

        # Early check for env variables required by poprun and other calls
        for benchmark_name in variant_dictionary:
            check_env(args, benchmark_name, spec[benchmark_name]["cmd"])

        for benchmark_name in variant_dictionary:
            benchmark_spec = spec.get(benchmark_name, {})
            logger.info("Running " + benchmark_name)

            if len(variant_dictionary) > 1:
                logger.info(f"Running {str(len(variant_dictionary[benchmark_name]))} variants:")

                for variant_name in variant_dictionary[benchmark_name]:
                    name = variant_name.get("name")
                    logger.info(f"\t{name}")

            result_list = []
            benchmark_result = dict()
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

    # Print PASSED/FAILED summary
    print_benchmark_summary(results)

    save_results(args.log_dir, args.additional_metrics, results, args.csv_metrics)
    if args.gc_monitor:
        plot_ipu_usage(args.log_dir)
    return results


def benchmarks_parser(parser: argparse.ArgumentParser):
    """Add benchmarking arguments to argparse parser"""

    # Key arguments
    parser.add_argument(
        "--additional-metrics",
        action="store_true",
        help="Collect additional metrics to the output CSV file",
    )
    parser.add_argument(
        "--spec",
        type=str,
        nargs="+",
        default=["./benchmarks.yml"],
        help="Yaml files with benchmark spec",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        nargs="+",
        help="List of benchmark ids to run",
    )

    # Additional functionality controls
    parser.add_argument(
        "--allow-wandb",
        action="store_true",
        help="Allow any wandb commands (do not automatically remove them)",
    )
    parser.add_argument(
        "--compile-only",
        action="store_true",
        help="Enable compile only options in compatible models",
    )
    parser.add_argument(
        "--csv-metrics",
        type=str,
        nargs="+",
        default=tuple(),
        help="List of extra metrics to capture in the CSV output.",
    )
    parser.add_argument(
        "--custom-metrics-files",
        type=str,
        nargs="+",
        help="List of python files containing extra metrics functions.",
    )
    parser.add_argument(
        "--include-convergence",
        action="store_true",
        help=("Include convergence tests (name ending in '_conv') in the set "
              "of benchmarks being run. This only has any effect if "
              "convergence tests would be run anyway i.e. if there are "
              "convergence benchmarks in the yaml file provided in '--spec' or "
              "if the convergence test required is named explicitly in "
              "'--benchmarks'."),
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help=("Stop on the first error and terminate all runs, instead of "
              "proceeding to the next benchmark"),
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        type=str,
        help="Folder to place log files",
    )
    parser.add_argument(
        "--logging",
        choices=["DEBUG", "INFO", "ERROR", "CRITICAL", "WARNING"],
        default="INFO",
        help=("Specify the logging level set for poplar/popart (the example "
              "itself, not this benchmarking module"),
    )
    parser.add_argument(
        "--no-code-sync",
        action="store_true",
        help=("Disable automatic syncing of venv/code files across all hosts "
              "in multi-host benchmarks."),
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help=("Enable profiling for the benchmarks, setting the appropriate "
              "environment variables and storing profiling reports in the cwd"),
    )
    parser.add_argument(
        "--gc-monitor",
        action="store_true",
        help=("Enable usage monitoring during benchmarks. when set, runs "
              "gc-monitor every 5 seconds"),
    )
    parser.add_argument(
        "--remove-dirs-after",
        action="store_true",
        help=("Whether or not to remove all directories used for benchmarking "
              "from all hosts involved after the benchmark is complete. This "
              "includes the examples, SDKs and venvs directories."),
    )
    parser.add_argument(
        "--requirements-file",
        default=str(Path.cwd().joinpath("requirements.txt")),
        type=str,
        help=("Path to the application's requirements file. Should only be "
              "manually provided if requested by this benchmarking module. "
              "Defaults to the parent dir of the benchmarks.yml file."),
    )
    parser.add_argument(
        "--timeout",
        default=None,
        type=int,
        help="Maximum time allowed for any benchmark/variant (in seconds)",
    )
    parser.add_argument(
        "--upload-checkpoints",
        default="",
        type=str,
        nargs="+",
        choices=["wandb", "s3"],
        help="List of locations to upload model checkpoints to",
    )

    parser.add_argument("--submit-on-slurm", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--slurm-machine-type", choices=["any", "mk2", "mk2w"], default="any", help=argparse.SUPPRESS)
