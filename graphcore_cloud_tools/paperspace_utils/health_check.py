# Copyright (c) 2023 Graphcore Ltd. All rights reserved.
from datetime import datetime
import json
import os
import yaml
import logging
import pathlib
from .metadata_utils import check_files_match_metadata
from pathlib import Path
from time import time
import argparse


def check_datasets_exist(dataset_names: [str], dirname: str):
    """
    Checks status of a list of datasets in a directory
    Looks for a metadata.json file in each dataset and checks files match what is expected from the metadata file
    Returns dictionary of logging information on the status of the datasets
    """
    dirpath = Path(dirname)
    output_dict = {}
    if not dirpath.exists():
        warn = f"Directory {dirname} does not exist"
        logging.warning(warn)
        return {"warning": warn}
    else:
        logging.info(f"Directory {dirname} exists")
    for dataset_name in dataset_names:
        full_path = dirpath / dataset_name
        if not full_path.exists():
            logging.warning(f"{dataset_name} not found in {dirname}")
            output_dict[dataset_name] = {
                "warning": f"{dataset_name} dataset not mounted, {dataset_name} directory not found in {dirname}"
            }
        else:
            if (full_path / "gradient_dataset_metadata.json").exists():
                logging.info(f"Metadata found in {full_path}")
                output_dict[dataset_name] = check_files_match_metadata(full_path, False)
            else:
                logging.warning(f"Metadata file not found in {full_path}")
                output_dict[dataset_name] = {"warning": f"Metadata file not found in {full_path}"}
    return output_dict


def check_paths_exists(paths: [str]):
    """Logs whether paths exists and returns dict of logging information"""
    symlinks_exist = []
    for path in paths:
        if Path(path).exists():
            logging.info(f"Folder exists: {path}")
            symlinks_exist.append({path: True})
        else:
            logging.warning(f"Folder does not exist {path}")
            symlinks_exist.append({path: False})
    return symlinks_exist


def parse_args(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--log-folder",
        default="/storage/graphcore_health_checks",
        help="Folder for log output",
    )
    parser.add_argument(
        "--gradient-settings-file",
        default="/notebooks/.gradient/settings.yaml",
        help="Path to gradient settings.yaml file",
    )
    parser.add_argument(
        "--symlink-config-file",
        default="/notebooks/.gradient/symlink_config.json",
        help="Path to symlink_config.json file",
    )
    parser.add_argument("--dataset-folder", default="/datasets", help="Path to dataset folder")
    return parser.parse_args()


def run_health_check(args):
    notebook_id = os.environ.get("PAPERSPACE_METRIC_WORKLOAD_ID", "")
    # Check that graphcore_health_checks folder exists
    health_check_dir = pathlib.Path(args.log_folder)
    health_check_dir.mkdir(exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    logging.info("Running health check")
    logging.info("Checking datasets mounted")
    # Check that the datasets have mounted as expected
    # Gather the datasets expected from the settings.yaml
    with open(args.gradient_settings_file) as f:
        my_dict = yaml.safe_load(f)
        datasets = my_dict["integrations"].keys()

    # Check that dataset exists and if a metadata file is found check that all files in the metadata file exist
    datasets_mounted = check_datasets_exist(datasets, args.dataset_folder)

    # Check that the folders specified in the key of the symlink_config.json exist
    logging.info("Checking symlink folders exist")
    with open(args.symlink_config_file) as f:
        symlinks = json.load(f)
        new_folders = list(map(os.path.expandvars, symlinks.keys()))
    symlinks_exist = check_paths_exists(new_folders)

    output_json_dict = {
        "mounted_datasets": datasets_mounted,
        "symlinks_exist": symlinks_exist,
    }

    (
        health_check_dir / f"{datetime.fromtimestamp(time()).strftime('%Y-%m-%d-%H.%M.%S')}_{notebook_id}.json"
    ).write_text(json.dumps(output_json_dict, indent=4))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    args = parse_args(parser)
    run_health_check(args)
