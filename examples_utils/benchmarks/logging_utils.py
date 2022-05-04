# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from time import time


def configure_logger(args: argparse.ArgumentParser):
    """Setup the benchmarks runner logger

    Args:
        args (argparse.ArgumentParser): Argument parser used for benchmarking
    
    """

    # Setup dir
    if not args.logdir:
        time_str = datetime.fromtimestamp(time()).strftime("%Y-%m-%d-%H.%M.%S.%f")
        args.logdir = Path(os.getcwd(), f"log_{time_str}").resolve()
    else:
        args.logdir = Path(args.logdir).resolve()

    if not args.logdir.exists():
        args.logdir.mkdir(parents=True)

    # Setup logger
    logger = logging.getLogger()
    formatter = logging.Formatter("[%(levelname)s] %(asctime)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(args.logging)

    logger.info(f"Logging directory: '{args.logdir}'")


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
                summary.append(f"PASSED {variant['benchmark_path']}::{benchmark}::" f"{variant['benchmark_name']}")
                passed += 1
            else:
                summary.append(f"FAILED {variant['benchmark_path']}::{benchmark}::" f"{variant['benchmark_name']}")
                failed += 1

    if summary:
        print("=================== short test summary info ====================\n")
        print("\n".join(summary) + "\n")
        print(f"================ {failed} failed, {passed} passed ===============")
