# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

_MISSING_REQUIREMENTS = {}
import argparse
import sys

from .paperspace_utils import paperspace_parser, run_paperspace


def main(raw_args):
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="subparser")

    paperspace_subparser = subparsers.add_parser("paperspace", description="Run paperspace scripts.")
    paperspace_parser(paperspace_subparser)


    args = parser.parse_args(raw_args[1:])

    if len(raw_args) <= 1:
        parser.print_usage()
        sys.exit(1)

    elif args.subparser == "paperspace":
        run_paperspace(args)
    else:
        err = "Please select from one of:" "\n\t`test_copyright`" "\n\t`paperspace`"
        raise Exception(err)


if __name__ == "__main__":
    main(sys.argv)
