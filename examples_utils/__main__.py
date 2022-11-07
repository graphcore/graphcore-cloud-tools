# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import argparse
import sys

from examples_utils.benchmarks.run_benchmarks import benchmarks_parser, run_benchmarks
from examples_utils.benchmarks.requirements_utils import platform_parser, assess_platform
from examples_utils.benchmarks.logging_utils import configure_logger
from examples_utils.load_lib_utils.cli import load_lib_build_parser, load_lib_builder_run
from examples_utils.testing.test_copyright import copyright_argparser, test_copyrights


def main(raw_args):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='subparser')

    load_lib_build_subparser = subparsers.add_parser(
        'load_lib_build', description='Use load_lib to build all eligible files in specified directory.')
    load_lib_build_parser(load_lib_build_subparser)

    benchmarks_subparser = subparsers.add_parser(
        'benchmark', description="Run applications benchmarks from the application's root directory.")
    benchmarks_parser(benchmarks_subparser)
    platform_assessment_subparser = subparsers.add_parser(
        'platform_assessment', description="Run applications benchmarks from arbitrary directories and platforms.")
    platform_parser(platform_assessment_subparser)

    copyright_subparser = subparsers.add_parser('test_copyright', description="Run copyright header test.")
    copyright_argparser(copyright_subparser)

    args = parser.parse_args(raw_args[1:])

    if len(raw_args) <= 1:
        parser.print_usage()
        sys.exit(1)

    if args.subparser == 'load_lib_build':
        load_lib_builder_run(args)
    elif args.subparser == 'benchmark':
        configure_logger(args)
        run_benchmarks(args)
    elif args.subparser == 'platform_assessment':
        configure_logger(args)
        assess_platform(args)
    elif args.subparser == 'test_copyright':
        test_copyrights(args.path, args.amend, args.exclude_json)
    else:
        raise Exception('Please select: `load_lib_build` or `benchmark`')


if __name__ == "__main__":
    main(sys.argv)
