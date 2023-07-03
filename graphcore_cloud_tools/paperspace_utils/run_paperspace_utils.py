# Copyright (c) 2023 Graphcore Ltd. All rights reserved.
import argparse

from .symlink_datasets_and_caches import run_symlinks, parse_symlinks_args
from .health_check import run_health_check, parse_args

def paperspace_parser(parser: argparse.ArgumentParser):
    """Add paperspace arguments to argparse parser"""
    subparsers = parser.add_subparsers(dest="option")
    symlinks_subparser = subparsers.add_parser("symlinks")
    parse_symlinks_args(symlinks_subparser)

def run_paperspace(args: argparse.Namespace):
    """Run paperspace scripts.

    Args:
        args (argparse.Namespace): Arguments passed to run the benchmarks
            with

    """
    if args.option == "symlinks":
        run_symlinks(args)
    elif args.option == "health_check":
        run_health_check(args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    paperspace_parser(parser)
    args = parser.parse_args()
    run_paperspace(args)
