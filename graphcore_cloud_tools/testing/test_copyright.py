# Copyright (c) 2019 Graphcore Ltd. All rights reserved.

import argparse
import datetime
import fileinput
import os
import re
import sys
import configparser
import json
import logging

C_FILE_EXTS = ["c", "cpp", "C", "cxx", "c++", "h", "hpp"]

EXT_TO_LANGUAGE = {"py": "python", **{ext: "c" for ext in C_FILE_EXTS}}


def check_file(path, amend):
    logging.debug(f"Checking: {path}")

    ext = path.split(".")[-1]
    language = EXT_TO_LANGUAGE[ext]

    if os.stat(path).st_size == 0:
        # Empty file
        return True

    comment = "#" if language == "python" else "//"
    found_copyright = False
    first_line_index = 0
    line = "\n"
    with open(path, "r") as f:
        regexp = r"({} )*Copyright \(c\) \d+ Graphcore Ltd. All (r|R)ights (r|R)eserved.".format(comment)

        # Skip blank, comments and shebang
        while (
            line == "\n"
            or line.startswith('"""')
            or line.startswith("'''")
            or line.startswith(comment)
            or line.startswith("#!")
        ) and not re.match(regexp, line):
            if line.startswith("#!"):
                first_line_index += 1
            line = f.readline()

        # Check first line after skips
        if re.match(regexp, line):
            found_copyright = True

    if not found_copyright:
        if amend:
            now = datetime.datetime.now()
            year = now.year
            copyright_msg = "{} Copyright (c) {} Graphcore Ltd. All rights reserved.".format(comment, year)
            index = 0
            for line in fileinput.FileInput(path, inplace=1):
                if index == first_line_index:
                    line = copyright_msg + line
                print(line[:-1])
                index += 1

        logging.debug(f"File fails: {path}")
        return False

    logging.debug(f"File passes: {path}")
    return True


def read_git_submodule_paths():
    try:
        config = configparser.ConfigParser()
        config.read(".gitmodules")
        module_paths = [config[k]["path"] for k in config.sections()]
        if len(module_paths):
            print(f"Git submodule paths: {module_paths}")
        return module_paths
    except:
        print(f"No Git submodules found to exclude.")
        return []


def test_copyrights(root_path, amend=False, exclude_josn=None):
    """A test to ensure that every source file has the correct Copyright"""
    bad_files = []

    if os.path.isfile(root_path):
        if not check_file(root_path, amend):
            bad_files.append(root_path)

    else:
        git_module_paths = read_git_submodule_paths()

        logging.info(f"Git submodule paths to exclude: {git_module_paths}")
        git_module_paths = set(git_module_paths)

        root_path = os.path.abspath(root_path)

        if exclude_josn is not None:
            with open(exclude_josn) as f:
                exclude = json.load(f)
            exclude = exclude["exclude"]
        else:
            exclude = []
        exclude = [os.path.join(root_path, p) for p in exclude]

        logging.debug(f"Exclude file list: {exclude}")

        # Search directories for files
        files = []
        for root, dirs, file_paths in os.walk(root_path, topdown=True, followlinks=False):
            # Modifying dirs in-place will prune the directories visited by os.walk
            dirs[:] = list(set(dirs).difference(git_module_paths))
            files += [os.path.join(root, path) for path in file_paths]

        # Remove excluded
        files = set(files).difference(set(exclude))

        # CMake builds generate .c and .cpp files
        # so we need to exclude all those:
        files = [file for file in files if "/CMakeFiles/" not in file]

        # Only include files with lang ext
        files = [file for file in files if file.split(".")[-1] in EXT_TO_LANGUAGE]

        logging.debug(f"Files to check: {files}")
        logging.info(f"Number of files to check: {len(files)}")

        # Check files
        for file in files:
            if not check_file(file, amend):
                bad_files.append(file)

    if len(bad_files) != 0:
        sys.stderr.write("ERROR: The following files do not have " "copyright notices:\n\n")
        for f in bad_files:
            sys.stderr.write("    {}\n".format(f))
        raise RuntimeError(f"{len(bad_files)} files do not have copyright notices: {bad_files}")
    else:
        print("Copyright headers checks passed.")


def copyright_argparser(parser: argparse.ArgumentParser):
    """Add load lib build CLI commands to argparse parser"""
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory to start searching for files. "
        "Defaults to current working directory. You can also specify a file if you would like to only check that file.",
    )
    parser.add_argument("--amend", action="store_true", help="Amend copyright headers in files.")
    parser.add_argument(
        "--exclude_json",
        default=None,
        help="Provide a path to a JSON file which include files to exclude. "
        "The paths should be relative to the current working directory.",
    )
    parser.add_argument(
        "--log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        type=str,
        default="WARNING",
        help=("Loging level for the app. "),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copyright header test")
    copyright_argparser(parser)
    opts = parser.parse_args()

    logging.basicConfig(
        level=opts.log_level, format="%(asctime)s %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    logging.info(f"Staring. Process id: {os.getpid()}")

    try:
        test_copyrights(opts.path, opts.amend, opts.exclude_json)
    except AssertionError:
        sys.exit(1)
