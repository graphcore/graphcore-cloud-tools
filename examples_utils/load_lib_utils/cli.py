# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import argparse
import logging
import os

from examples_utils.load_lib_utils.load_lib_utils import load_lib_all, load_lib


def load_lib_build_parser(parser: argparse.ArgumentParser):
    """Add load lib build CLI commands to argparse parser"""

    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quite logging")
    parser.add_argument(
        "root",
        help="The file or directory to build. If a directory is given, "
        "load lib walks it recursively to build all eligible source "
        "files.",
        nargs="*",
    )
    parser.add_argument("--force", "-f", action="store_true", default=False, help="Force a rebuild.")


def load_lib_builder_run(args):
    """Build all eligible files specified in the paths using load_lib"""
    if args.quiet:
        logging.basicConfig(level=logging.CRITICAL)
    elif args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    for path in args.root or ["."]:
        path = os.path.abspath(os.path.expandvars(path))
        if os.path.isfile(path):
            load_lib(filepath=path)
        elif os.path.isdir(path):
            load_lib_all(dir_path=path or os.getcwd(), load=False)
        else:
            raise FileNotFoundError(f'Path does not exist: "{path}"')
