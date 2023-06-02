#!/usr/bin/env python3
# Copyright (c) 2023 Graphcore Ltd. All rights reserved.
import argparse
import re
from importlib import metadata
from typing import List, Optional, Sequence

import requirements
from requirements.requirement import Requirement

GIT_URI_PATTERN = r"(?:.+ @ )?(git\+.*)"


def is_uri(req_line: str) -> bool:
    return re.match(GIT_URI_PATTERN, req_line) is not None


def manual_parse_named_git(req_line: str):
    """
    Workaround for mis-handling of named git repo lines in requirements files by requirement-parser.
    Parses the repo path, removes the name if present, and creates a new requirement, which can then
    be checked as normal.

    Assumes it's receiving a git repo path from a requirements file and assumes that checks
    for non-git lines have been carried out prior to this. If it receives something that's not
    a git repo, it'll return False.
    """
    m = re.match(GIT_URI_PATTERN, req_line)

    if m is None:
        return False

    new_req = Requirement.parse(m[1])
    return is_valid_req(new_req)


def is_valid_req(r: Requirement) -> bool:
    if "req: unpinned" in r.line:
        return True

    if r.specs and r.specs[0][0] in ["==", "~="]:
        return True

    if r.uri and r.revision:
        return True

    # Requirements parser doesn't properly parse named requirements coming from git repos,
    # It'll read the name/optionals, but not the git URI, which then makes it looked like
    # otherwise fine dependencies haven't been pinned.
    # The backup plan is to identify these with regex and manually extract the git URI, then
    # use that to check for pinning.
    if r.name and not r.uri:
        return manual_parse_named_git(r.line)

    return False


def recommend_version_if_possible(package_name: str) -> Optional[str]:
    try:
        version_installed = metadata.version(package_name)
        print(f"Found version {version_installed} for '{package_name}'")
        return f"{package_name}=={version_installed}"
    except metadata.PackageNotFoundError:
        print(f"Failed to find package '{package_name}' - skipping")
        return None


def try_write_fixed_requirements(reqs: List[Requirement], invalid: List[Requirement], filename: str):
    has_updated = False

    for i, r in enumerate(reqs):
        if r in invalid and r.name and not is_uri(r.line):
            new_version = recommend_version_if_possible(r.name)
            if new_version:
                print(f"    Found {r.name} version {new_version}")
                reqs[i] = Requirement.parse(new_version)
                has_updated = True
            else:
                print(f"    Could not get version... Skipping.")

    if has_updated:
        with open(filename, "w") as fh:
            for r in reqs:
                fh.write(r.line + "\n")
    return has_updated


def invalid_requirements(filename: str, fix_it: bool) -> bool:
    with open(filename) as fh:
        reqs = [r for r in requirements.parse(fh)]
        f = [r for r in reqs if not is_valid_req(r)]

    if f:
        print(f"Unpinned requirements found in file {filename}")

    if fix_it:
        print(f"  Attempting to fix...")
        try_write_fixed_requirements(reqs, f, filename)

    return f


def main(argv: Optional[Sequence[str]] = None, fix_issues: bool = True) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("filenames", nargs="*")
    args = parser.parse_args(argv)

    exit_code = 0
    for filename in args.filenames:
        try:
            invalid = invalid_requirements(filename, fix_issues)
            if invalid:
                exit_code = 1
        except FileNotFoundError:
            print(f"Could not find requirements file: {filename}")
            exit_code = 2
        except Exception:
            print(f"Could not parse requirements file: {filename}")
            exit_code = 3
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
