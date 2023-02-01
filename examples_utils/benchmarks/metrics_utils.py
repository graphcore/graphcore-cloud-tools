# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import logging
import math
import re
import statistics
from datetime import datetime
from typing import Tuple
from examples_utils.benchmarks.custom_metrics import register_custom_metric

# Get the module logger
logger = logging.getLogger(__name__)

# Regexes below for both TF and popart/poptorch
date_regex = r"(\d{4}\-\d{2}\-\d{2}[T ?]\d{2}:\d{2}:\d{2}.\d{6})"
compile_time_lookup = [
    {
        "name": "Pre poplar compilation time",
        "ref": "pre_poplar_compilation_time",
        "start_regex": [
            re.compile(date_regex + r".* Poplar version:"),
            re.compile(date_regex + r".* Popart version:"),
        ],
        "end_regex": [
            re.compile(date_regex + r".* Begin Poplar graph construction"),
            re.compile(date_regex + r".* Poplar graph initialised"),
        ],
    },
    {
        "name": "Graph construction time",
        "ref": "graph_construction_time",
        "start_regex": [
            re.compile(date_regex + r".* Begin Poplar graph construction"),
            re.compile(date_regex + r".* Poplar graph initialised"),
        ],
        "end_regex": [
            re.compile(date_regex + r".* End Poplar graph construction"),
            re.compile(date_regex + r".* Starting compilation"),
        ],
    },
    {
        "name": "Poplar compilation time",
        "ref": "poplar_compilation_time",
        "start_regex": [
            re.compile(date_regex + r".* Begin compiling Poplar engine"),
            re.compile(date_regex + r".* Starting compilation"),
        ],
        "end_regex": [
            re.compile(date_regex + r".* End compiling Poplar engine"),
            re.compile(date_regex + r".* Graph compiled"),
        ],
    },
]
date_format = "%Y-%m-%d %H:%M:%S.%f"
poprun_instance_regex = re.compile(r"\[(.*?),(.*?)\]<stderr>:")


def get_instance_compile_times(compile_log: str) -> list:
    """Get compile times for each instance from the logs.

    Parameters
        compile_log (str): The log containing compile time outputs from
            poplar/popart, as a string

    Returns:
        results_per_inst (list): Compile time results per instance for all
            instances found

    """

    results_per_inst = {comp_time["ref"]: {} for comp_time in compile_time_lookup}
    for line in compile_log.split("\n"):
        for comp_time in compile_time_lookup:

            # Get compilation start and end times from line
            start_match = get_match_of_list(comp_time["start_regex"], line)
            end_match = get_match_of_list(comp_time["end_regex"], line) if not start_match else None

            # Create a structure to store compile start/end times from multiple
            # instances
            poprun_inst = "N/A"
            if start_match or end_match:
                poprun_match = re.search(poprun_instance_regex, line)
                if poprun_match:
                    poprun_inst = f"[{poprun_match.group(1)},{poprun_match.group(2)}]"
            if poprun_inst not in results_per_inst[comp_time["ref"]]:
                results_per_inst[comp_time["ref"]].update({poprun_inst: {"start_times": [], "end_times": []}})

            # Convert to datetime objects and store against instance numbers
            if start_match:
                time = datetime.strptime(start_match.group(1).replace("T", " "), date_format)
                results_per_inst[comp_time["ref"]][poprun_inst]["start_times"].append(time)
            if end_match:
                time = datetime.strptime(end_match.group(1).replace("T", " "), date_format)
                results_per_inst[comp_time["ref"]][poprun_inst]["end_times"].append(time)

    return results_per_inst


def get_overall_compile_times(results_per_inst: dict, exitcode: int) -> dict:
    """Get the overall compile time from all instances, allreduced.

    Args:
        results (dict): The benchmarks/variants results
        results_per_inst (dict): Compile time results per instance for all
            instances
        exitcode (int): The exitcode from the process that ran the
            benchmark/variant

    Returns:
        total_compiling_time (dict): The compile time as a dictionary

    """

    overall_start_time = None
    overall_end_time = None
    for comp_time in compile_time_lookup:
        ref = comp_time["ref"]

        if not exitcode:
            for _, times in results_per_inst[ref].items():
                start_time_list = times["start_times"]
                end_time_list = times["end_times"]

                if start_time_list and end_time_list:
                    start_time = min(start_time_list)
                    end_time = max(end_time_list)

                    # Get earliest start time
                    if overall_start_time:
                        overall_start_time = min(start_time, overall_start_time)
                    else:
                        overall_start_time = start_time

                    # Get latest end time
                    if overall_end_time:
                        overall_end_time = max(end_time, overall_end_time)
                    else:
                        overall_end_time = end_time

    # Finally, get the overall total compiling time
    total_compiling_time = None
    if overall_end_time and overall_start_time:
        if not exitcode:
            total_compiling_time = (overall_end_time - overall_start_time).total_seconds()

    return {"mean": total_compiling_time}


def get_results_for_compile_time(_: str, stderr: str, exitcode: int) -> dict:
    """Function to gather compile time results from stderr.

    This function conforms to the ``MetricFunction`` interface.

    Args:
        _ (str): The stdout output from the benchmark process
        stderr (str): stderr output from the benchmark process
        exitcode (int): The exitcode form the process that ran the benchmark command

    Results:
        total_compiling_time (dict): The compile as a dictionary

    """

    # Get compile start/end times from stderr
    results_per_inst = get_instance_compile_times(stderr)

    # Calculate overall start/end times from all instances
    total_compiling_time = get_overall_compile_times(results_per_inst, exitcode)

    # Log compile time and add to stderr
    is_recording_legit = isinstance(total_compiling_time["mean"], float)
    if is_recording_legit:
        printable_time = round(total_compiling_time["mean"], 2)
        compile_time_output = f"   Total compile time: {printable_time} seconds"
    else:
        compile_time_output = f"   Total compile time: ERROR"

    logger.info(compile_time_output)

    return total_compiling_time


def set_config_defaults(data_extraction_dict: dict) -> dict:
    """Set default values for some data configs if they are not defined.

    Note:
        'skip' is not currently used in derivation

    Args:
        data_extraction_dict (dict): Dict from the benchmark definition dict
            that defined how data will be extraced from stdout/stderr

    Returns:
        data_extraction_dict (dict): Updated data extraction specification dict

    """

    defaults = {"skip": 0, "reduction_type": "mean"}
    for k, v in defaults.items():
        if k not in data_extraction_dict:
            data_extraction_dict[k] = v

    return data_extraction_dict


def extract_metrics(
    extraction_config: dict, stdout: str, stderr: str, exitcode: int, num_replicas: int
) -> Tuple[dict, bool]:
    """Extract metrics from a given log.

    Args:
        extraction_config (dict): Configuration describing how to extract
            metrics from the log
        stdout (str): The stdout from the benchmark containing metrics
        stderr (str): The stderr from the benchmark containing metrics
        exitcode (int): The benchmark process exitcode
        num_replicas (int): The number of replicas used in this benchmark

    Returns:
        extracted_metrics (dict): All metrics that were extracted from the log
        did_extraction_fail (bool): Whether or not the metrics extraction from
            the logs was a failure

    """

    extracted_metrics = {}
    did_extraction_fail = False

    for name, metric in extraction_config.items():
        result = None

        # Set defaults for any reduction types/skip values that could be missed
        metric_spec = set_config_defaults(metric)

        # Get all raw results from log according to all regexes given
        all_results = []
        for line in stdout.split("\n"):
            for match in re.findall(metric_spec["regexp"], line):
                all_results.append(float(match))

        for line in stderr.split("\n"):
            for match in re.findall(metric_spec["regexp"], line):
                all_results.append(float(match))

        if any([math.isnan(ar) for ar in all_results]):
            logger.error(f"  '{name}' is a NaN")
        elif exitcode:
            logger.error(f"  '{name}' had non-zero exitcode: '{str(exitcode)}'")
        # Check results sufficient for 'skip'
        elif len(all_results) <= metric_spec["skip"]:
            logger.error(f"  '{name}' has less results than the skip value: '{metric_spec['skip']}'")

        # Post-process the results
        else:
            if metric_spec["reduction_type"] == "mean":
                if name == "latency":
                    all_results.sort(reverse=True)
                else:
                    all_results.sort()

                all_results = all_results[metric_spec["skip"] :]
                result = sum(all_results) / len(all_results)

            elif metric_spec["reduction_type"] == "final":
                result = all_results[-1]
            elif metric_spec["reduction_type"] == "min":
                result = min(all_results)
            elif metric_spec["reduction_type"] == "value":
                result = all_results[0]

            # Multiply the result by the number of replicas if mpinum is >1.
            # NOTE: mpinum will only be > 1 if mpirun was used in the command
            # and hence throughput values could not have been allreduced within
            # the app
            if name == "throughput":
                result *= num_replicas

        extracted_metrics[name] = {metric_spec["reduction_type"]: result}
        logger.info(f"   {name} = '{str(result) if result is not None else 'VALUE_NOT_FOUND'}'")

        if result is None:
            did_extraction_fail = True

    return extracted_metrics, did_extraction_fail


def flatten_results(results: dict, derivation_config: dict) -> dict:
    """Flatten and simplify the results dict into <metric>:<result> format.

    Args:
        results (dict): The benchmark results dict, containing all info duch as
            reduction types too
        derivation_config (dict): The configuration defining how metrics are
            derived from logs

    Returns:
        flat_results (dict): The flattened dict of all results in
            <metric>:<result> format

    """

    flat_results = {}
    for metric, results_dict in results.items():
        key = derivation_config.get(metric, {}).get("reduction_type", "mean")
        flat_results[metric] = results_dict[key]

    return flat_results


def derive_metrics(
    derivation_config: dict,
    benchmark_config: dict,
    results: dict,
    exitcode: int,
) -> Tuple[dict, bool]:
    """Derive metrics from other metrics using specified expressions.

    Args:
        derivation_config (dict): The config defining how metrics will be
            dervied from other metrics
        benchmark_config (dict): The benchmark configuration
        results (dict): The raw results from the benchmark
        exitcode (int): The exitcode form the process that ran the benchmark
            command

    Returns:
        derived_metrics (dict): Metrics, now including those that were derived
            from other metrics

    """

    did_derivation_fail = False

    for name, config in derivation_config.items():
        result = None
        config = set_config_defaults(config)

        # In the case of a non-zero exitcode
        if exitcode:
            logger.error(f"  '{name}' had non-zero exitcode: '{str(exitcode)}'")
        else:
            # Format the expression to replace parameter names with actual
            # values for this benchmark/variant
            expression = config["expr"].format(**{**flatten_results(results, derivation_config), **benchmark_config})

            # Evaluate the expression
            try:
                result = eval(expression)
                logger.info(f"   '{name}' = '{str(result)}'")
            except:
                logger.error(f"   ERROR: '{name}' = 'derived' expression: '{expression}' excepted")

        results[name] = {config["reduction_type"]: result}

        if result is None:
            did_derivation_fail = True

    return results, did_derivation_fail


def get_match_of_list(regex_list: list, line: str) -> str:
    """Finds first match in a line given a list of regexes.

    Args:
        regex_list (list): List of all regexes to find matches for
        line (str): The line to find matches in

    Returns:
        match (str): The first match that has been found in the given line

    """

    match = None
    for regex in regex_list:
        match = re.search(regex, line)

        if match:
            return match

    return match


def additional_metrics(
    results: dict, test_duration: float, cmd: str, exitcode: int, env: dict, git_commit_hash: str
) -> dict:
    results["test_duration"] = {"test_duration": test_duration}
    results["cmd"] = {"cmd": cmd}
    results["result"] = {"result": str(bool(not exitcode))}
    results["git_commit_hash"] = {"git_commit_hash": git_commit_hash}

    env_string = str()
    for k, v in env.items():
        env_string = env_string + f"{k}={v} "
    results["env"] = {"env": env_string}

    return results


register_custom_metric("total_compiling_time", get_results_for_compile_time)
