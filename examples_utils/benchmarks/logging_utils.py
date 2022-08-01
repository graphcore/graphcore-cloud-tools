# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from time import time

# Attempt to import wandb silently, if app being benchmarked has required it
WANDB_AVAILABLE = True
try:
    import wandb
except:
    WANDB_AVAILABLE = False


def configure_logger(args: argparse.ArgumentParser):
    """Setup the benchmarks runner logger

    Args:
        args (argparse.ArgumentParser): Argument parser used for benchmarking
    
    """

    # Setup dir
    if not args.log_dir:
        time_str = datetime.fromtimestamp(time()).strftime("%Y-%m-%d-%H.%M.%S.%f")
        args.log_dir = Path(os.getcwd(), f"log_{time_str}").resolve()
    else:
        args.log_dir = Path(args.log_dir).resolve()

    if not args.log_dir.exists():
        args.log_dir.mkdir(parents=True)

    # Setup logger
    logger = logging.getLogger()
    formatter = logging.Formatter("[%(levelname)s] %(asctime)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(args.logging)

    logger.info(f"Logging directory: '{args.log_dir}'")


def print_benchmark_summary(results: dict):
    """Print a summary of all benchmarks run.

    Args:
        results (dict): Benchmark results dict to create summary from
    
    """

    # Print PASS/FAIL statements
    summary = []
    passed, failed = 0, 0
    for benchmark, variants in results.items():
        for variant in variants:
            if variant.get("exitcode") == 0:
                summary.append(f"PASSED {benchmark}::" f"{variant['benchmark_name']}")
                passed += 1
            else:
                summary.append(f"FAILED {benchmark}::" f"{variant['benchmark_name']}")
                failed += 1

    if summary:
        print("=================== short test summary info ====================\n")
        print("\n".join(summary) + "\n")
        print(f"================ {failed} failed, {passed} passed ===============")


def get_wandb_link(stderr):
    """Get a wandb link from stderr if it exists.
    """

    wandb_link = None
    for line in stderr.split("\n"):
        if "https://wandb.sourcevertex.net" in line and "/runs/" in line:
            wandb_link = "https:/" + line.split("https:/")[1]
            wandb_link = wandb_link.replace("\n", "")

    return wandb_link


def upload_compile_time(wandb_link, results):
    """Upload compile time results to a wandb link
    """

    # Re-initialise link to allow uploading again
    link_parts = wandb_link.split("/")
    run = wandb.init(project=link_parts[-3], id=link_parts[-1], resume="allow")

    run.log({"Total compile time": results["total_compiling_time"]["mean"]})
