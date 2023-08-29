# Copyright (c) 2023 Graphcore Ltd. All rights reserved.
import argparse

from . import symlink_datasets_and_caches
from .health_check import run_health_check


def paperspace_parser(parser: argparse.ArgumentParser):
    """Add paperspace arguments to argparse parser"""
    subparsers = parser.add_subparsers(dest="option")
    symlinks_subparser = subparsers.add_parser("symlinks")
    symlink_datasets_and_caches.symlink_arguments(symlinks_subparser)


def run_paperspace(args: argparse.Namespace):
    """Run paperspace scripts.

    Args:
        args (argparse.Namespace): Arguments passed to run the utils
            with

    """
    if args.option == "symlinks":
        symlink_datasets_and_caches.main(args)
    elif args.option == "health_check":
        run_health_check(args)


if __name__ == "__main__":

    args = symlink_datasets_and_caches.symlink_arguments().parse_args()
    run_paperspace(args)
