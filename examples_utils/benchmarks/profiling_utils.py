# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import numpy as np
import json
import reptil
import logging
from pathlib import Path

# Get the module logger
logger = logging.getLogger(__name__)


def add_profiling_vars(current_env: dict, benchmark_name: str, app_dir: str) -> dict:
    """Enable profiling for this benchmarking run.
    
    Args:
        current_env (dict): Current environment variables state
        benchmark_name (str): Name of the benchmark being run
        app_dir (str): Application root directory

    Returns:
        current_env (dict): Updated environment variables state, including
            POPLAR_ENGINE_OPTIONS
    
    """

    report_dir = Path(app_dir).joinpath(benchmark_name + "_profile").resolve()
    logger.info(f"Profile will be saved in: {report_dir}")

    profiling_opts = {
        "autoReport.all": "true",
        "autoReport.directory": str(report_dir),
        "autoReport.outputSerializedGraph": "false",
    }
    pop_engine_opts = {"POPLAR_ENGINE_OPTIONS": json.dumps(profiling_opts)}
    current_env.update(pop_engine_opts)

    return current_env


def log_profile_summary(report: reptil.Reptil) -> str:
    """
    Analyse and extract information from a popvision profile report.

    Args:
        report (reptil.Reptil): Reptil profile report object

    Returns:
        mem_writeout (str): A single string writeout of all useful memory
            information from this report

    """

    # Get summary statistics from report
    summary = report.memory.summary()
    mem_writeout = ("Memory usage summary statistics:\n" +
                    "Peak liveness: {}\n".format(summary["Peak liveness"]["total"]) +
                    "\tAs a proportion: {},\n".format(summary["Peak liveness"]["proportion"]))

    mem_writeout += "Split by categories (megabytes): \n"
    for k, v in summary["Memory categories"].items():
        mem_writeout += f"\t{k}: {v*(1024**-2)}\n"

    mem_writeout += "Overall memory usage (per IPU, megabytes):\n"
    for k, v in summary["IPU level"].items():
        mem_writeout += f"\t{k}: {v*(1024**-2)}\n"

    mem_writeout += "Detailed breakdown (per Tile, bytes):\n"
    for ipu_id, tile_summary in summary["Tile level"].items():
        mem_writeout += f"\t{ipu_id}:\n"
        for k, v in tile_summary.items():
            mem_writeout += f"\t\t{k}: {v}\n"

    # Output to logs too
    logger.info(mem_writeout)

    return mem_writeout


def save_profile_breakdowns(report: reptil.Reptil, dir: Path):
    """Save detailed memory usage breakdowns locally to csv.

    Args:
        report (reptil.Reptil): Reptil profile report object
        dir (pathlib.Path): Dir path to save files to

    """

    # All the memory categories of interest
    memory_categories = [
        "vertex",
        "control",
        "exchange",
        "constants",
        "always_live",
        "including_gaps",
        "excluding_gaps",
        "not_always_live",
    ]

    for category in memory_categories:
        # Get the category from the report and save to CSV
        memory = getattr(report.memory, category)
        np.savetxt(dir.joinpath(f"{category}_memory.csv"), memory.tiles, delimiter=",")


def analyse_profile(benchmark_name: str, app_dir: str) -> str:
    """Analyse and output information from a popvision profile.

    Args:
        benchmark_name (str): Name of the benchmark being run
        app_dir (str): Application root directory

    Returns:
        mem_writeout (str): The analysis results from the profile in str format
    
    """
    # Get first dir made by popvision (this will be the training report
    # in the case of a train + validate run)
    report_dir = Path(app_dir).joinpath(benchmark_name + "_profile").resolve()
    for path in report_dir.iterdir():
        if path.is_dir():
            profile = report_dir.joinpath(path, "profile.pop")
            break

    if not profile.is_file():
        message = "Popvision report not created. Skipping analysis."
        logger.info(message)
        return message
    else:
        report = reptil.open_report(str(profile))
        # Analyse and log the profile, Append results to stdout
        mem_writeout = log_profile_summary(report=report)
        # Save more detailed breakdowns to local
        save_profile_breakdowns(report=report, dir=profile.parent)
        return mem_writeout
