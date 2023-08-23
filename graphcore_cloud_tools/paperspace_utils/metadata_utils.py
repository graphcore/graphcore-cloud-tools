# Copyright (c) 2023 Graphcore Ltd. All rights reserved.
"""
Checks if files in dataset folder match those listed in the gradient_dataset_metadata.json

To use import the check_files_match_metadata function:
check_files_match_metadata(dataset_folder: str, compare_hash: bool)
"""

from typing import NamedTuple, List, Dict
from pathlib import Path
import os
import hashlib
import json
import logging
import datetime


METADATA_FILENAME = "gradient_dataset_metadata.json"


# Copied from paperspace_automation upload script
def md5_hash_file(file_path: Path):
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        data = f.read()
        md5.update(data)
    return md5.hexdigest()


# Copied from paperspace_automation upload script
class GradientFileArgument(NamedTuple):
    """Arguments for uploading a file to Paperspace using the gradient API"""

    full_path: Path
    target_path: str

    @classmethod
    def from_filepath_and_dataset_path(cls, file_path: Path, dataset_path: Path):
        file_path = file_path.resolve()
        # Target path resolution needs to be an absolute folder starting with /
        target_path = file_path.resolve().parent.relative_to(dataset_path.resolve()).as_posix()
        target_path = "/" + str(target_path).lstrip(".")
        return cls(file_path, target_path)


# Copied from paperspace_automation but class method added that doesnt require the gradient api
class Dataset(NamedTuple):
    """Manage a Gradient Dataset, allowing easy creation of the dataset and its version"""

    name: str
    id: str
    version: str
    storage_provider_id: str


# Copied from paperspace_automation
def get_files_metadata(gradient_file_arguments: List[GradientFileArgument], generate_hash: bool):
    files_metadata = []
    for file_path, target_path in gradient_file_arguments:
        file_stat = os.stat(file_path)
        if target_path[-1] != "/":
            target_path += "/"
        path = target_path + file_path.name
        file_metadata = {"path": path, "size": file_stat.st_size}
        if generate_hash:
            file_metadata["md5_hash"] = md5_hash_file(file_path)
        files_metadata.append(file_metadata)
    return files_metadata


# Copied from paperspace_automation
def preprocess_list_of_files(dataset_folder: Path, file_list: List[Path]) -> List[GradientFileArgument]:
    gradient_file_arguments: List[GradientFileArgument] = []
    for file_path in file_list:
        if file_path.is_file():
            gradient_file_arguments.append(
                GradientFileArgument.from_filepath_and_dataset_path(file_path, dataset_folder)
            )
    return gradient_file_arguments


def compare_file_lists(
    loaded_metadata_files: List[Dict[str, str]], generated_locally_metadata_files: List[Dict[str, str]]
):
    output_dict = {}
    # Find extra or missing files and print an error, if so remove them from relevant lists
    def preprocess(file_dict):
        path = str(file_dict["path"])
        if path[0] == "/":
            path = path[1:]
        file_dict["path"] = path
        return file_dict

    loaded_metadata_files = [preprocess(d) for d in loaded_metadata_files]
    generated_locally_metadata_files = [preprocess(d) for d in generated_locally_metadata_files]
    expected_filepaths = list(map(lambda file_dict: file_dict["path"], loaded_metadata_files))
    local_filepaths = list(map(lambda file_dict: file_dict["path"], generated_locally_metadata_files))
    # Files found but not expected
    extra_files = [filepath for filepath in local_filepaths if filepath not in expected_filepaths]

    # Files expected but not found
    missing_files = [filepath for filepath in expected_filepaths if filepath not in local_filepaths]

    found_files_metadata = [filedict for filedict in loaded_metadata_files if filedict["path"] not in missing_files]
    found_files_locally = [
        filedict for filedict in generated_locally_metadata_files if filedict["path"] not in extra_files
    ]
    files_found_logging = f"{len(found_files_locally)}/{len(expected_filepaths)} files found from metadata"
    logging.info(files_found_logging)
    output_dict["Files found"] = files_found_logging
    if missing_files:
        logging.error(f"Missing files, files in metadata.json but not found in local storage: {missing_files}")
    output_dict["Missing Files"] = missing_files
    if extra_files:
        logging.warning(f"Extra files found in local storage: {extra_files}")
    output_dict["Extra files"] = extra_files
    logging.info({str(output_dict)})
    keys = generated_locally_metadata_files[0].keys()
    for i in range(len(found_files_metadata)):
        for key in keys:
            file_differences = []
            if found_files_locally[i][key] != found_files_metadata[i][key]:
                file_difference = {
                    "path": str(found_files_metadata[i]["path"]),
                    "key": key,
                    "gradient_metadata.json value": str(found_files_metadata[i][key]),
                    "local value": str(found_files_locally[i][key]),
                }
                logging.warning(f"Difference in file found and file expected\n {file_difference}")
                file_differences.append(file_difference)
        output_dict["file_differences"] = file_differences
    return output_dict


def check_files_match_metadata(dataset_folder: str, compare_hash: bool):
    """
    Checks whether files in dataset_folder match the files listed in dataset_folder/METADATA_FILENAME

    Parameters:
        dataset_folder (str): full or relative path to dataset folder
        compare_hash (bool): whether or not to compare the md5_hash of the files

    Returns:


    """
    result = {}
    dataset_folder = Path(dataset_folder)
    file_list = sorted(list(f for f in dataset_folder.rglob("*") if f.is_file() and f.name != METADATA_FILENAME))
    gradient_file_arguments = preprocess_list_of_files(dataset_folder, file_list)
    file_metadata = get_files_metadata(gradient_file_arguments, compare_hash)

    if os.path.isfile(dataset_folder / METADATA_FILENAME):
        data = json.loads((dataset_folder / METADATA_FILENAME).read_text())
        result = compare_file_lists(data["files"], file_metadata)
    else:
        logging.warning("No metadata file found, no check performed")
        result = {}
    return result


# Copied from paperspace_automation
def create_metadata_file(dictionary: dict, path: Path) -> str:
    content = json.dumps(dictionary, indent=4)
    file_name = path / METADATA_FILENAME
    Path(file_name).write_text(content)
    with open(file_name, "w") as outfile:
        outfile.write(content)
    return file_name


def get_metadata_file_data(name: str, path: str):
    dataset_folder = Path(path) / name
    dataset = Dataset(dataset_folder.name, "test_version", "test_id", "local_storage")

    file_list = sorted(list(f for f in dataset_folder.rglob("*") if f.is_file() and f.name != METADATA_FILENAME))
    gradient_file_arguments = preprocess_list_of_files(dataset_folder, file_list)

    file_metadata = get_files_metadata(gradient_file_arguments, True)
    metadata = {
        "dataset": dataset._asdict(),
        "timestamp": str(datetime.datetime.now()),
        "files": file_metadata,
    }

    metadata_filepath = create_metadata_file(metadata, dataset_folder)
    return metadata_filepath
