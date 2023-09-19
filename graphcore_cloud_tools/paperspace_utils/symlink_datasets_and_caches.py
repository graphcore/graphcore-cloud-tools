#! /usr/bin/env -S python3 -u
# Copyright (c) 2023 Graphcore Ltd. All rights reserved.
import json
import time
from pathlib import Path
import subprocess
import os
import warnings
from typing import List, NamedTuple, Dict, Optional, Tuple
import base64
import itertools
import time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import random
import boto3
from boto3.s3.transfer import TransferConfig
import argparse
import logging
import yaml

from .auth import AWS_CREDENTIAL_ENV_VAR, DEFAULT_S3_CREDENTIAL


# environment variables which can be used to configure the execution of the program
DATASET_METHOD_OVERRIDE_ENV_VAR = "USE_LEGACY_DATASET_SYMLINK"
LEGACY_DATASET_ENV_VAR = "PUBLIC_DATASETS_DIR"
FUSEOVERLAY_ROOT_ENV_VAR = "SYMLINK_FUSE_ROOTDIR"  # must be a writeable directory
S3_DATASETS_DIR_ENV_VAR = "S3_DATASETS_DIR"  # must be a writeable directory with space to download all requested files
DEFAULT_S3_DATASET_DIR = "/graphcore-gradient-datasets"
AWS_ENDPOINT_ENV_VAR = "DATASET_S3_DOWNLOAD_ENDPOINT"  # A list of semi-colon separated endpoints to cycle between
DEFAULT_AWS_ENDPOINT = "http://10.12.17.91:8100"  # The S3 endpoint for Paperspace

S3_DATASET_FOLDER = "graphcore-gradient-datasets"


class MissingDataset(Exception):
    pass


class S3DownloadFailed(Exception):
    pass


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
    FUSEOVERLAY_ROOT = os.getenv(FUSEOVERLAY_ROOT_ENV_VAR, "/fusedoverlay")
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


def symlink_gradient_datasets(args):
    """Symlink gradient datasets using fuse-overlayfs"""
    # read in symlink config file
    json_data = Path(args.config_file).read_text()

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
            expected_paths.extend(
                [str((target_path / f.relative_to(source_path)).resolve()) for f in source_path.rglob("*")]
            )
        if len(source_dirs_exist_paths) > 0:
            out = create_overlays(source_dirs_exist_paths, target_dir)
        symlink_results.append((target_dir, out))
        found_target_paths.extend([str(f) for f in target_path.rglob("*")])
    errors = [f"{t} failed with error: {o}" for t, o in symlink_results if isinstance(o, str) or o.returncode != 0]
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


def get_valid_aws_endpoints(endpoint_fallback=False) -> List[str]:
    # Check which endpoint should be used based on if we can directly access or not
    AWS_ENDPOINT = os.getenv(AWS_ENDPOINT_ENV_VAR, DEFAULT_AWS_ENDPOINT)
    aws_endpoints = AWS_ENDPOINT.split(";")
    valid_aws_endpoints = []
    for aws_endpoint in aws_endpoints:
        try:
            subprocess.check_output(["curl", aws_endpoint], timeout=5)
            print(f"Validated endpoint: {aws_endpoint}")
            valid_aws_endpoints.append(aws_endpoint)
        except subprocess.TimeoutExpired:
            print(f"End point could not be reached: {aws_endpoint}")
        except subprocess.CalledProcessError as error:
            if "exit status 7" in f"{error}":
                print(f"End point cannot be reached from current executor: {aws_endpoint}")
            else:
                raise
    if not valid_aws_endpoints:
        if not endpoint_fallback:
            raise ValueError(
                f"None of the specified endpoints were available: {AWS_ENDPOINT}\n{aws_endpoints}"
                "\n If you are using this code interactively you may use the '--public-endpoint'"
                "argument to fall back to the Paperspace production S3 endpoint."
            )
        valid_aws_endpoints = ["https://s3.clehbtvty.paperspacegradient.com"]
        print("Using global endpoint")
    return valid_aws_endpoints


def prepare_cred() -> None:
    """Decode and write AWS read credential to file"""
    aws_credential = os.getenv(AWS_CREDENTIAL_ENV_VAR)
    read_only = aws_credential if aws_credential else DEFAULT_S3_CREDENTIAL
    cred_bytes = base64.b64decode(read_only)
    home = os.getenv("HOME", "/root")
    creds_file = Path(f"{home}/.aws/credentials")
    creds_file.parent.mkdir(exist_ok=True, parents=True)
    creds_file.touch(exist_ok=True)
    if "gcdata-r" not in creds_file.read_text():
        with open(creds_file, "ab") as f:
            f.write(cred_bytes)
        logging.debug(f"Credential 'gcdata-r' written to {creds_file}")
    else:
        logging.debug(f"Credential 'gcdata-r' found in credential file: {creds_file}")


def encode_cred(plain_text_cred: str) -> str:
    """Encodes a credential in the way it is expected"""
    return base64.b64encode(plain_text_cred.encode()).decode()


class GradientDatasetFile(NamedTuple):
    s3file: str
    local_file: str
    size: int = 0

    @classmethod
    def from_response(cls, s3_response: dict):
        bucket_name: str = f"s3://{s3_response['Name']}"
        s3_prefix = s3_response["Prefix"]
        local_root = os.getenv(S3_DATASETS_DIR_ENV_VAR, DEFAULT_S3_DATASET_DIR)
        for pre in s3_prefix.split("/"):
            if pre not in local_root:
                local_root = f"{local_root}/{pre}"
        print(local_root)
        if "/" != bucket_name[-1]:
            bucket_name = f"{bucket_name}/"

        def single_entry(s3_content_response: dict):
            s3_object_name: str = s3_content_response["Key"]
            relative_file = s3_object_name.replace(s3_prefix, "").strip("/")
            target = Path(local_root).resolve() / relative_file
            return cls(
                s3file=s3_object_name,
                local_file=str(target),
                size=s3_content_response.get("Size", 0),
            )

        return [single_entry(c) for c in s3_response["Contents"]]


def list_files(client: "boto3.Client", dataset_name: str) -> List[GradientDatasetFile]:
    dataset_prefix = f"{S3_DATASET_FOLDER}/{dataset_name}/"
    out = client.list_objects_v2(Bucket="sdk", MaxKeys=10000, Prefix=dataset_prefix)
    assert out["ResponseMetadata"].get("HTTPStatusCode", 200) == 200, "Response did not have HTTPS status 200"
    assert not out["IsTruncated"], "Handling of truncated response is not handled yet"
    if "Contents" not in out:
        raise MissingDataset(f"Dataset '{dataset_name}' not found at 's3://sdk/{dataset_prefix}'")
    logging.debug(f"S3 response {out}")
    return GradientDatasetFile.from_response(out)


def apply_symlink(
    list_files: List[GradientDatasetFile], directory_map: Dict[str, List[str]]
) -> List[GradientDatasetFile]:
    def with_trailing_slash(path):
        return path if path[-1] == "/" else f"{path}/"

    source_target = {
        with_trailing_slash(source): with_trailing_slash(target)
        for target, sources in directory_map.items()
        for source in sources
    }
    logging.debug(f"Mapping used for symling: {source_target}")
    symlinked_list = []
    for file in list_files:
        local_file = file.local_file
        for source, new_root in source_target.items():
            if source in local_file:
                local_file = local_file.replace(source, new_root)
        symlinked_list.append(file._replace(local_file=local_file))
    return symlinked_list


class DownloadOutput(NamedTuple):
    elapsed_seconds: float
    gigabytes: float
    error: Optional[Exception]


def download_file_iterate_endpoints(aws_endpoints: List[str], *args, **kwargs) -> DownloadOutput:
    # Randomly shuffles endpoints to load balance
    aws_endpoints = aws_endpoints.copy()
    random.shuffle(aws_endpoints)
    error_in_loop = []
    for aws_endpoint in aws_endpoints:
        try:
            return download_file(aws_endpoint, *args, **kwargs)
        except Exception as error:
            error_in_loop.append((aws_endpoint, error))
            logging.error("endpoint %s failed with error: %s", aws_endpoint, error)
            pass
    failure = S3DownloadFailed(
        f"Unhandled failure during data download from endpoints: {aws_endpoints}. Errors encountered: {error_in_loop}"
    )
    if error_in_loop is None:
        raise failure
    else:
        raise failure from error_in_loop[0][1]


def download_file(
    aws_endpoint: str, aws_credential, file: GradientDatasetFile, *, max_concurrency, use_cli, progress=""
) -> DownloadOutput:
    bucket_name = "sdk"
    s3client = boto3.Session(profile_name=aws_credential).client("s3", endpoint_url=aws_endpoint)
    print(f"Downloading {progress} {file}")
    start = time.time()
    config = TransferConfig(max_concurrency=max_concurrency)
    target = Path(file.local_file)
    target.parent.mkdir(exist_ok=True, parents=True)
    exception = None
    try:
        if not use_cli:
            s3client.download_file(bucket_name, file.s3file, str(target), Config=config)
        else:
            cmd = (
                f"aws s3 --endpoint-url {aws_endpoint} --profile {aws_credential} "
                f"cp s3://{bucket_name}/{file.s3file}"
                f" {target}"
            ).split()
            print(cmd)
            out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if out.returncode != 0:
                raise S3DownloadFailed(f"Command {cmd} failed with return code {out.returncode}")
    except Exception as error:
        exception = error
    elapsed = time.time() - start
    size_gb = file.size / (1024**3)
    print(f"Finished {progress}: {size_gb:.2f}GB in {elapsed:.0f}s ({size_gb/elapsed:.3f} GB/s) for file {target}")
    return DownloadOutput(elapsed, size_gb, exception)


def parallel_download_dataset_from_s3(
    datasets: List[str],
    directory_map: Dict[str, List[str]],
    *,
    max_concurrency=1,
    num_concurrent_downloads=1,
    symlink=True,
    use_cli=False,
    endpoint_fallback=False,
    failed_files: List[GradientDatasetFile]=None,
) -> Tuple[List[GradientDatasetFile], Dict[str, List[str]]]:
    aws_credential = "gcdata-r"
    aws_endpoints = get_valid_aws_endpoints(endpoint_fallback)

    s3 = boto3.Session(profile_name=aws_credential).client("s3", endpoint_url=aws_endpoints[0])

    # Disable thread use/transfer concurrency

    if failed_files:
        # reattempt to download failed files
        files_to_download = failed_files
        failed_datasets = []
        print(f"Retrying download of {len(files_to_download)} failed files: {files_to_download}")
    else:
        files_to_download: List[GradientDatasetFile] = []

        failed_datasets = []
        for dataset in datasets:
            try:
                files_to_download.extend(list_files(s3, dataset))
            except MissingDataset as error:
                logging.error(f"{dataset} is missing - skipping download. Error: {error}")
                failed_datasets.append(dataset)

        num_files = len(files_to_download)
        print(f"Downloading {num_files} files from {len(datasets)} datasets")
        logging.debug(f"Files to download: {files_to_download}")
        if symlink:
            logging.debug(f"Symlink mapping: {directory_map}")
            files_to_download = apply_symlink(files_to_download, directory_map)
            logging.debug(f"Files to download after symlinking: {files_to_download}")

    start = time.time()
    with ProcessPoolExecutor(max_workers=num_concurrent_downloads) as executor:
        outputs = [
            executor.submit(
                download_file_iterate_endpoints,
                aws_endpoints,
                aws_credential,
                file,
                max_concurrency=max_concurrency,
                use_cli=use_cli,
                progress=f"{i+1}/{num_files}",
            )
            for i, file in enumerate(files_to_download)
        ]

    failed_downloads = []
    failed_files = []
    for file, future_result in zip(files_to_download, outputs):
        result = future_result.result()
        if result.error is not None:
            failed_downloads.append(f"{file} failed to download with {result.error}")
            logging.error(failed_downloads[-1])
            failed_files.append(file)
    total_elapsed = time.time() - start
    total_download_size = sum(o.result().gigabytes for o in outputs)
    if not failed_downloads:
        print(
            f"Finished downloading {num_files} files: {total_download_size:.2f} GB in {total_elapsed:.2f}s ({total_download_size/total_elapsed:.2f}  GB/s)"
        )
    else:
        logging.error(f"{len(failed_downloads)}/{len(files_to_download)} files failed to download.")
    errors = {}
    if failed_datasets:
        errors["missing_datasets"] = failed_datasets
    if failed_downloads:
        errors["failed_file_downloads"] = failed_downloads
    return files_to_download, errors, failed_files


def read_gradient_settings(gradient_settings_file: Path) -> List[str]:
    """Reads the gradient settings files

    integrations:
        gcl:
            type: dataset
            ref: paperspace/ds7me5hgjbfht6q:8ngwr2a
        poplar-executables-hf-3-3:
            ...
    """
    with open(gradient_settings_file) as f:
        my_dict = yaml.safe_load(f)
        datasets = my_dict["integrations"].keys()
    return list(datasets)


def copy_graphcore_s3(args):
    # read in symlink config file
    json_data = Path(args.config_file).read_text()

    # substitute environment variables in the JSON data
    json_data = os.path.expandvars(json_data)
    symlink_config = json.loads(json_data)
    datasets = read_gradient_settings(args.gradient_settings_file)
    prepare_cred()

    max_retries = args.max_retries
    failed_files = []
    all_attempts_errors = {}

    for attempt in range(1 + max_retries): # Including the initial attempt
        _, errors, failed_files = parallel_download_dataset_from_s3(
            datasets,
            symlink_config,
            max_concurrency=args.max_concurrency,
            num_concurrent_downloads=args.num_concurrent_downloads,
            symlink=not args.no_symlink,
            endpoint_fallback=args.public_endpoint,
            failed_files=failed_files
        )

        #RRR testing - to be removed
        if attempt == 0:
            errors = {["failed_file_downloads"]:"rrr"}
            import os
            local_file = '/tmp/exe_cache/3.3.0/kge_training/4253143966390608402.popef'
            assert os.path.isfile(local_file)

            failed_files = [GradientDatasetFile(s3file='graphcore-gradient-datasets/poplar-executables-pytorch-3-3/3.3.0/kge_training/4253143966390608402.popef', local_file=local_file, size=4399398296)]
        else:
            assert os.path.isfile(local_file)
        #RRR testing end

        if errors:
            # add and label errors from different attempts
            if attempt == 0:
                all_attempts_errors = errors
            else:
                key_suffix = f"_retry_{attempt}" 
                for key, value in errors.items():
                    all_attempts_errors[f"{key}{key_suffix}"] = value

            if failed_files:
                # retry download failed files
                if attempt < max_retries:
                    print(f"Retry attempt {attempt+1}/{max_retries}: Retrying download for {len(failed_files)} failed files...") 
                else:
                    print(f"All {max_retries} retries exhausted. Failed to download {len(failed_files)} files.")
            else:
                # hit a different error, needs special addressing, not necessarily retry download. raise error below.
                break
        else:
            # Successful download. Remove any "failed files" errors from previous unsuccessful attempts.
            # There may still be other errors like missing datasets that will be raised
            if any(key.startswith("failed_file_downloads") for key in all_attempts_errors):
                all_attempts_errors = {key: value for key, value in all_attempts_errors.items() if not key.startswith("failed_file_downloads")}
            break
    if all_attempts_errors:
        raise RuntimeError(
            "There were errors during the dataset download from S3, check below for details."
            f"\nerrors: {all_attempts_errors}\nArguments were: {args}\ndatasets: {datasets}\nconfig: {symlink_config}"
        )


def symlink_arguments(parser=argparse.ArgumentParser()) -> argparse.ArgumentParser:

    parser.add_argument("--s3-dataset", action="store_true", help="Use gradient datasets rather than S3 storage access")
    parser.add_argument("--no-symlink", action="store_true", help="Turn off the symlinking")
    parser.add_argument("--use-cli", action="store_true", help="Use the CLI instead of boto3")
    parser.add_argument(
        "--num-concurrent-downloads", default=1, type=int, help="Number of concurrent files to download"
    )
    parser.add_argument("--max-concurrency", default=1, type=int, help="S3 maximum concurrency")
    parser.add_argument("--config-file", default=str(Path(".").resolve().parent / "symlink_config.json"))
    parser.add_argument(
        "--gradient-settings-file",
        default=str(Path(".").resolve().parent / "settings.yaml"),
        help="Path to gradient settings.yaml file",
    )
    parser.add_argument("--max-retries", default=1, type=int, help="Maximum number of download retries in case of failures")
    parser.add_argument("--public-endpoint", action="store_true", help="Use endpoint fallback")
    parser.add_argument("--disable-legacy-mode", action="store_true", help="block attempts to use legacy mode")
    return parser


def handle_legacy_override(args: argparse.Namespace) -> argparse.Namespace:
    """The legacy override listens for an environment variable and modifies the arguments passed to
    the method to work with the fuse overlay symlinks"""
    override_method = os.getenv(DATASET_METHOD_OVERRIDE_ENV_VAR)
    if override_method is None:
        return args
    if args.disable_legacy_mode:
        warnings.warn(
            f"Legacy mode is disabled,  env var {DATASET_METHOD_OVERRIDE_ENV_VAR} with value {override_method} ignored"
        )
        return args
    if override_method != "OVERLAY":
        warnings.warn(f"Unknown symlink override value: {override_method}, falling back on the requested CLI behavior.")
        return args
    if not args.s3_dataset:
        # Already in legacy mode, do nothing
        return args

    args.s3_dataset = False
    legacy_dataset_location = os.getenv(LEGACY_DATASET_ENV_VAR, "/datasets")
    if not Path(legacy_dataset_location).exists():
        raise FileNotFoundError(
            f"Cannot use OVERLAY mode for symlinks, as the {LEGACY_DATASET_ENV_VAR} env"
            f" var points to non-existant folder: {legacy_dataset_location}"
        )
    location_to_override = os.getenv(S3_DATASETS_DIR_ENV_VAR, DEFAULT_S3_DATASET_DIR)
    os.environ[S3_DATASETS_DIR_ENV_VAR] = legacy_dataset_location
    config_file = Path(args.config_file).resolve()
    new_conf_text = config_file.read_text().replace(location_to_override, legacy_dataset_location)
    new_conf_file = config_file.parent / f"compatibility-{config_file.name}"
    new_conf_file.write_text(new_conf_text)
    warnings.warn(
        "The --s3-dataset was overridden by the environment variable "
        f"'{DATASET_METHOD_OVERRIDE_ENV_VAR}', overlay based symlinks will be used."
        f"env var: {S3_DATASETS_DIR_ENV_VAR}, was overridden to '{legacy_dataset_location}'. "
        f"Config file: {config_file} was modified and rewritten to {new_conf_file}."
    )
    args.config_file = str(new_conf_file)
    return args


def main(args):
    try:
        print("Starting disk usage \n", subprocess.check_output(["df", "-h"]).decode())
    except:
        pass
    print(args)
    args = handle_legacy_override(args)
    if not args.s3_dataset:
        print("Symlinking gradient datasets")
        symlink_gradient_datasets(args)
    else:
        print("Downloading datasets from S3")
        copy_graphcore_s3(args)
    try:
        print("Final disk usage \n", subprocess.check_output(["df", "-h"]).decode())
    except:
        pass


if __name__ == "__main__":
    args = symlink_arguments().parse_args()
    main(args)
