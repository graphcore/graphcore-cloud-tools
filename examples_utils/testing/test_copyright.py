# Copyright (c) 2019 Graphcore Ltd. All rights reserved.

import argparse
import datetime
import fileinput
import os
import re
import sys
import configparser
import json

C_FILE_EXTS = ['c', 'cpp', 'C', 'cxx', 'c++', 'h', 'hpp']


def check_file(path, language, amend):
    if os.stat(path).st_size == 0:
        # Empty file
        return True

    comment = "#" if language == "python" else "//"
    found_copyright = False
    first_line_index = 0
    line = ''
    with open(path, "r") as f:
        regexp = r"{} Copyright \(c\) \d+ Graphcore Ltd. All (r|R)ights (r|R)eserved.".format(comment)

        # Skip blank, comments and shebang
        while (line == '' or line.startswith(comment) or line.startswith("#!")) and not re.match(regexp, line):
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
            copyright_msg = '{} Copyright (c) {} Graphcore Ltd. All rights reserved.'.format(comment, year)
            index = 0
            for line in fileinput.FileInput(path, inplace=1):
                if index == first_line_index:
                    line = copyright_msg + line
                print(line[:-1])
                index += 1

        return False

    return True


def read_git_submodule_paths():
    try:
        config = configparser.ConfigParser()
        config.read('.gitmodules')
        module_paths = [config[k]['path'] for k in config.sections()]
        if len(module_paths):
            print(f"Git submodule paths: {module_paths}")
        return module_paths
    except:
        print(f"No Git submodules found to exclude.")
        return []


def test_copyrights(root_path, amend=False, exclude_josn=None):
    """A test to ensure that every source file has the correct Copyright"""
    git_module_paths = read_git_submodule_paths()

    root_path = os.path.abspath(root_path)

    if exclude_josn is not None:
        with open(exclude_josn) as f:
            exclude = json.load(f)
        exclude = exclude['exclude']
    else:
        exclude = []

    bad_files = []
    excluded = [os.path.join(root_path, p) for p in exclude]
    for path, _, files in os.walk(root_path):
        for file_name in files:
            file_path = os.path.join(path, file_name)

            if file_path in excluded:
                continue

            # CMake builds generate .c and .cpp files
            # so we need to exclude all those:
            if '/CMakeFiles/' in file_path:
                continue

            # Also exclude git submodules from copyright checks:
            if any(path in file_path for path in git_module_paths):
                continue

            if file_name.endswith('.py'):
                if not check_file(file_path, "python", amend):
                    bad_files.append(file_path)

            if file_name.split('.')[-1] in C_FILE_EXTS:
                if not check_file(file_path, "c", amend):
                    bad_files.append(file_path)

    if len(bad_files) != 0:
        sys.stderr.write("ERROR: The following files do not have " "copyright notices:\n\n")
        for f in bad_files:
            sys.stderr.write("    {}\n".format(f))
        raise RuntimeError(f"{len(bad_files)} files do not have copyright notices: {bad_files}")
    else:
        print("Copyright headers checks passed.")


def copyright_argparser(parser: argparse.ArgumentParser):
    """Add load lib build CLI commands to argparse parser"""
    parser.add_argument('path',
                        nargs='?',
                        default='.',
                        help='Directory to start searching for files. '
                        'Defaults to current working directory.')
    parser.add_argument("--amend", action="store_true", help="Amend copyright headers in files.")
    parser.add_argument("--exclude_json",
                        default=None,
                        help="Provide a path to a JSON file which include files to exclude")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copyright header test")
    copyright_argparser(parser)

    opts = parser.parse_args()
    try:
        test_copyrights(opts.path, opts.amend, opts.exclude_json)
    except AssertionError:
        sys.exit(1)
