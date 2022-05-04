# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import argparse
import sys

from examples_utils.benchmarks.run_benchmarks import benchmarks_parser, run_benchmarks
from examples_utils.benchmarks.logging_utils import configure_logger
from examples_utils.load_lib_utils.cli import load_lib_build_parser, load_lib_builder_run
from examples_utils.load_lib_utils.cppimport_backports import _run_from_commandline_argparse, _run_from_commandline_run


def main(raw_args):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='subparser')

    load_lib_build_subparser = subparsers.add_parser(
        'load_lib_build', description='Use load_lib to build all eligible files in specified directory.')
    load_lib_build_parser(load_lib_build_subparser)

    # Cppimport CLI backported. Can be removed once version is upgraded
    cppimport_build_subparser = subparsers.add_parser(
        'cppimport_build', description='Backported from cppimport. Equivalent to `python3 -m cppimport build`')
    _run_from_commandline_argparse(cppimport_build_subparser)

    benchmarks_subparser = subparsers.add_parser(
        'benchmark', description="Run applications benchmarks from the application's root directory.")
    benchmarks_parser(benchmarks_subparser)

    args = parser.parse_args(raw_args[1:])

    if args.subparser == 'load_lib_build':
        load_lib_builder_run(args)
    elif args.subparser == 'cppimport_build':
        _run_from_commandline_run(args)
    elif args.subparser == 'benchmark':
        configure_logger(args)
        run_benchmarks(args)
    else:
        raise Exception()


if __name__ == "__main__":
    main(sys.argv)
