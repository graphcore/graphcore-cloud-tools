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


def create_overlays(source_dirs_exist_paths: List[str], target_dir: str) -> None:
    print(f"Symlinking - {source_dirs_exist_paths} to {target_dir}")
    print("-" * 100)

    Path(target_dir).mkdir(parents=True, exist_ok=True)

    workdir = Path(FUSEOVERLAY_ROOT) / "workdirs" / source_dirs_exist_paths[0]
    workdir.mkdir(parents=True, exist_ok=True)
    upperdir = Path(FUSEOVERLAY_ROOT) / "upperdir" / source_dirs_exist_paths[0]
    upperdir.mkdir(parents=True, exist_ok=True)

    lowerdirs = ":".join(source_dirs_exist_paths)
    overlay_command = f"fuse-overlayfs -o lowerdir={lowerdirs},upperdir={upperdir.as_posix()},workdir={workdir.as_posix()} {target_dir}"
    subprocess.run(
        overlay_command.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    return


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
    for target_dir, source_dirs_list in config.items():
        # need to wait until the dataset has been mounted (async on Paperspace's end)
        source_dirs_exist_paths = check_dataset_is_mounted(source_dirs_list)

        # create overlays for source dataset dirs that are mounted and populated
        if len(source_dirs_exist_paths) > 0:
            create_overlays(source_dirs_exist_paths, target_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parse_symlinks_args(parser)
    args = parser.parse_args()
    run_symlinks(args)
