# Copyright (c) 2023 Graphcore Ltd. All rights reserved.
#! /usr/bin/env -S python3 -u
import json
import argparse
import time
from pathlib import Path
import subprocess
import os
import warnings
from typing import List

FUSEOVERLAY_ROOT = os.getenv("SYMLINK_FUSE_ROOTDIR", "/fusedoverlay")


def check_dataset_is_mounted(source_dirs_list: List[str]) -> List[str]:
    source_dirs_exist_paths = []
    for source_dir in source_dirs_list:
        source_dir_path = Path(source_dir)
        COUNTER = 0
        # wait until the dataset exists and is populated/non-empty, with a 300s/5m timeout
        while (COUNTER < 300) and (not source_dir_path.exists() or not any(source_dir_path.iterdir())):
            print(f"Waiting for dataset {source_dir_path.as_posix()} to be mounted...")
            time.sleep(1)
            COUNTER += 1

        if COUNTER == 300:
            warnings.warn(
                f"Abandoning symlink! - source dataset {source_dir} has not been mounted & populated after 5 minutes."
            )
        else:
            print(f"Found dataset {source_dir}")
            source_dirs_exist_paths.append(source_dir)

    return source_dirs_exist_paths


def create_overlays(source_dirs_exist_paths: List[str], target_dir: str) -> subprocess.CompletedProcess:
    print(f"Symlinking - {source_dirs_exist_paths} to {target_dir}")
    print("-" * 100)

    Path(target_dir).mkdir(parents=True, exist_ok=True)

    # Use this path construction as pathlib resolves 'path1 / "/path"' -> "/path"
    workdir = Path(FUSEOVERLAY_ROOT) / f"workdirs/{source_dirs_exist_paths[0]}"
    workdir.mkdir(parents=True, exist_ok=True)
    upperdir = Path(FUSEOVERLAY_ROOT) / f"upperdirs/{source_dirs_exist_paths[0]}"
    upperdir.mkdir(parents=True, exist_ok=True)

    lowerdirs = ":".join(source_dirs_exist_paths)
    overlay_command = f"fuse-overlayfs -o lowerdir={lowerdirs},upperdir={upperdir.as_posix()},workdir={workdir.as_posix()} {target_dir}"
    out = subprocess.run(
        overlay_command.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return out


def parse_symlinks_args(parser: argparse.ArgumentParser):
    parser.add_argument("--path")


def run_symlinks(args):
    # read in symlink config file
    json_data = Path(args.path).read_text()

    # substitute environment variables in the JSON data
    json_data = os.path.expandvars(json_data)
    config = json.loads(json_data)

    # loop through each key-value pair
    # the key is the target directory, the value is a list of source directories
    symlink_results = []
    expected_paths = []
    found_target_paths = []
    for target_dir, source_dirs_list in config.items():
        # need to wait until the dataset has been mounted (async on Paperspace's end)
        source_dirs_exist_paths = check_dataset_is_mounted(source_dirs_list)

        # create overlays for source dataset dirs that are mounted and populated
        out = f"There were no source directories mounted from {source_dirs_list}"
        # add all the files detected in a source dir, to be expected after symlinking
        target_path = Path(target_dir).resolve()
        for source_path in source_dirs_exist_paths:
            source_path = Path(source_path).resolve()
            expected_paths.extend([str((target_path / f.relative_to(source_path)).resolve()) for f in source_path.rglob("*")])
        if len(source_dirs_exist_paths) > 0:
            out = create_overlays(source_dirs_exist_paths, target_dir)
        symlink_results.append((target_dir, out))
        found_target_paths.extend([str(f) for f in target_path.rglob("*")])
    errors = [
        f"{t} failed with error: {o}" for t, o in symlink_results if isinstance(o, str) or o.returncode != 0
    ]
    if errors:
        raise RuntimeError("\n".join(errors))
    missing_files = [e for e in expected_paths if e not in found_target_paths]
    if missing_files:
        raise FileNotFoundError(
            "The symlink config was not applied correctly, some files could not be found in their expected location.\n"
            f"Config: {config}\n"
            f"missing_files: {missing_files}\n"
            f"expected_paths: {expected_paths}\n"
            f"found_target_paths: {found_target_paths}\n"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parse_symlinks_args(parser)
    args = parser.parse_args()
    run_symlinks(args)
