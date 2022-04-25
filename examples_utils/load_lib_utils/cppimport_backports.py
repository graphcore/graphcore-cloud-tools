# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
# This file includes derived work from:
# The MIT License (MIT)
#
# Copyright (c) 2021 T. Ben Thompson
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""
Backported from cppimport stable branch (commit 0edf927f10d614751f7eaa58a3f7372ec298bd65) (19/04/2022)

Once cppimport version is bumped up most of this code can be removed
"""

import argparse
import logging
import os

from cppimport import settings


def _check_first_line_contains_cppimport(filepath):
    with open(filepath, "r") as f:
        return "cppimport" in f.readline()


def build_filepath(filepath, fullname=None):
    """
    `build_filepath` builds a extension module like `build` but allows
    to directly specify a file path.
    Parameters
    ----------
    filepath : the filepath to the C++ file to build.
    fullname : the name of the module to build.
    Returns
    -------
    ext_path : the path to the compiled extension.
    """
    from cppimport.importer import (
        is_build_needed,
        setup_module_data,
        template_and_build,
    )

    if fullname is None:
        fullname = os.path.splitext(os.path.basename(filepath))[0]
    module_data = setup_module_data(fullname, filepath)
    if not is_build_needed(module_data):  # cppimport BUGFIX: `is_build_needed` should be called `is_build_not_needed`
        template_and_build(filepath, module_data)

    # Return the path to the built module
    return module_data["ext_path"]


def build_all(root_directory):
    """
    `build_all` builds a extension module like `build` for each eligible (that is,
    containing the "cppimport" header) source file within the given `root_directory`.
    Parameters
    ----------
    root_directory : the root directory to search for cpp source files in.
    """
    for directory, _, files in os.walk(root_directory):
        for file in files:
            if (not file.startswith(".") and os.path.splitext(file)[1] in settings["file_exts"]):
                full_path = os.path.join(directory, file)
                if _check_first_line_contains_cppimport(full_path):
                    logging.info(f"Building: {full_path}")
                    build_filepath(full_path)


# _run_from_commandline_argparse & _run_from_commandline_run split from original function `_run_from_commandline`
def _run_from_commandline_argparse(parser: argparse.ArgumentParser):
    parser.add_argument("--verbose", "-v", action="store_true", help="Increase log verbosity.")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only print critical log messages.")

    parser.add_argument(
        "root",
        help="The file or directory to build. If a directory is given, "
        "cppimport walks it recursively to build all eligible source "
        "files.",
        nargs="*",
    )
    parser.add_argument("--force", "-f", action="store_true", help="Force rebuild.")
    return parser


def _run_from_commandline_run(args):
    if args.quiet:
        logging.basicConfig(level=logging.CRITICAL)
    elif args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.force:
        settings["force_rebuild"] = True

    for path in args.root or ["."]:
        path = os.path.abspath(os.path.expandvars(path))
        if os.path.isfile(path):
            build_filepath(path)
        elif os.path.isdir(path):
            build_all(path or os.getcwd())
        else:
            raise FileNotFoundError(f'The given root path "{path}" could not be found.')


###
