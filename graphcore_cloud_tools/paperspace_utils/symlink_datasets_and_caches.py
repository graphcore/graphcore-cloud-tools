#! /usr/bin/env -S python3 -u
# Copyright (c) 2023 Graphcore Ltd. All rights reserved.
import json
import time
from pathlib import Path
import subprocess
import os
import warnings
from typing import List, NamedTuple, Dict
import base64
import itertools
import time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import random
import boto3
from boto3.s3.transfer import TransferConfig
import argparse

# environment variables which can be used to configure the execution of the program
FUSEOVERLAY_ROOT_ENV_VAR = "SYMLINK_FUSE_ROOTDIR"  # must be a writeable directory
S3_DATASETS_DIR_ENV_VAR = "S3_DATASETS_DIR"  # must be a writeable directory with space to download all requested files
AWS_ENDPOINT_ENV_VAR = "DATASET_S3_DOWNLOAD_ENDPOINT"  # A list of semi-colon separated endpoints to cycle between
AWS_CREDENTIAL_ENV_VAR = "DATASET_S3_DOWNLOAD_B64_CREDENTIAL"  # See confluence


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


def get_valid_aws_endpoints():
    # Check which endpoint should be used based on if we can directly access or not
    AWS_ENDPOINT = os.getenv(AWS_ENDPOINT_ENV_VAR, "http://10.12.17.246:8000")
    aws_endpoints = AWS_ENDPOINT.split(";")
    valid_aws_endpoints = []
    for aws_endpoint in aws_endpoints:
        try:
            subprocess.check_output(["curl", aws_endpoint], timeout=5)
            print(f"Validated endpoint: {aws_endpoint}")
            valid_aws_endpoints.append(aws_endpoint)
        except subprocess.TimeoutExpired:
            print(f"End point could not be reached: {aws_endpoint}")
    if not valid_aws_endpoints:
        valid_aws_endpoints = ["https://s3.clehbtvty.paperspacegradient.com"]
        print("Using global endpoint")
    return valid_aws_endpoints


def prepare_cred():
    aws_credential = os.getenv(AWS_CREDENTIAL_ENV_VAR)
    read_only = (
        aws_credential
        if aws_credential
        else """W2djZGF0YS1yXQphd3NfYWNjZXNzX2tleV9pZCA9IDJaRUFVQllWWThCQVkwODlG
V0FICmF3c19zZWNyZXRfYWNjZXNzX2tleSA9IDZUbDdIbUh2cFhjdURkRmd5NlBV
Q0t5bTF0NmlMVVBCWWlZRFYzS2MK
"""
    )
    cred_bytes = base64.b64decode(read_only)
    creds_file = Path("/root/.aws/credentials")
    creds_file.parent.mkdir(exist_ok=True, parents=True)
    creds_file.touch(exist_ok=True)
    if "gcdata-r" not in creds_file.read_text():
        with open(creds_file, "ab") as f:
            f.write(cred_bytes)


def encode_cred(plain_text_cred:str) -> str:
    return base64.b64encode(plain_text_cred.encode()).decode()


def download_dataset_from_s3(source_dirs_list: List[str]) -> List[str]:
    aws_endpoints = get_valid_aws_endpoints()
    aws_credential = "gcdata-r"
    source_dirs_exist_paths = []
    for source_dir in source_dirs_list:
        source_dir_path = Path(source_dir)
        dataset_name = source_dir_path.name
        # Cycle through the endpoints if there are errors
        random.shuffle(aws_endpoints)
        for aws_endpoint in aws_endpoints:
            try:
                cmd = (
                    f"aws s3 --endpoint-url {aws_endpoint} --profile {aws_credential} "
                    f"cp s3://sdk/graphcore-gradient-datasets/{dataset_name}"
                    f" /graphcore-dataset/{dataset_name} --recursive"
                ).split()
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                break
            except Exception:
                pass

    return source_dirs_exist_paths


class GradientDatasetFile(NamedTuple):
    s3file: str
    relative_file: str
    local_root: str
    size: int = 0

    @classmethod
    def from_response(cls, s3_response: dict):
        bucket_name: str = f"s3://{s3_response['Name']}"
        s3_prefix = s3_response["Prefix"]
        local_root = os.getenv(S3_DATASETS_DIR_ENV_VAR, "/graphcore-gradient-datasets")
        for pre in s3_prefix.split("/"):
            if pre not in local_root:
                local_root = f"{local_root}/{pre}"
        print(local_root)
        if "/" != bucket_name[-1]:
            bucket_name = f"{bucket_name}/"

        def single_entry(s3_content_response: dict):
            s3_object_name: str = s3_content_response["Key"]
            full_s3file = f"{bucket_name}{s3_object_name}"
            relative_file = s3_object_name.replace(s3_prefix, "").strip("/")
            return cls(
                s3file=s3_object_name,
                relative_file=relative_file,
                local_root=local_root,
                size=s3_content_response.get("Size", 0),
            )

        return [single_entry(c) for c in s3_response["Contents"]]


def list_files(client: "boto3.Client", dataset_name: str):
    dataset_prefix = f"graphcore-gradient-datasets/{dataset_name}"
    out = client.list_objects_v2(Bucket="sdk", MaxKeys=10000, Prefix=dataset_prefix)
    assert out["ResponseMetadata"].get("HTTPStatusCode", 200) == 200, "Response did not have HTTPS status 200"
    assert not out["IsTruncated"], "Handling of truncated response is not handled yet"
    return GradientDatasetFile.from_response(out)


def apply_symlink(
    list_files: List[GradientDatasetFile], directory_map: Dict[str, List[str]]
) -> List[GradientDatasetFile]:
    source_target = {source: target for target, sources in directory_map.items() for source in sources}
    return [file._replace(local_root=source_target[file.local_root]) for file in list_files]


class DownloadOuput(NamedTuple):
    elapsed_seconds: float
    gigabytes: float


def download_file_iterate_endpoints(aws_endpoints: List[str], *args, **kwargs):
    # Randomly shuffles endpoints to load balance
    aws_endpoints = aws_endpoints.copy()
    random.shuffle(aws_endpoints)
    for aws_endpoint in aws_endpoints:
        try:
            return download_file(aws_endpoint, *args, **kwargs)
        except Exception:
            pass
    raise


def download_file(
    aws_endpoint: str, aws_credential, file: GradientDatasetFile, *, max_concurrency, use_cli, progress=""
):
    bucket_name = "sdk"
    s3client = boto3.Session(profile_name=aws_credential).client("s3", endpoint_url=aws_endpoint)
    print(f"Downloading {progress} {file}")
    start = time.time()
    config = TransferConfig(max_concurrency=max_concurrency)
    target = Path(file.local_root).resolve() / file.relative_file
    target.parent.mkdir(exist_ok=True, parents=True)
    if not use_cli:
        s3client.download_file(bucket_name, file.s3file, str(target), Config=config)
    else:
        cmd = (
            f"aws s3 --endpoint-url {aws_endpoint} --profile {aws_credential} "
            f"cp s3://{bucket_name}/{file.s3file}"
            f" {target}"
        ).split()
        print(cmd)
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    elapsed = time.time() - start
    size_gb = file.size / (1024**3)
    print(f"Finished {progress}: {size_gb:.2f}GB in {elapsed:.0f}s ({size_gb/elapsed:.3f} GB/s) for file {target}")
    return DownloadOuput(elapsed, size_gb)


def parallel_download_dataset_from_s3(
    directory_map: Dict[str, List[str]], *, max_concurrency=1, num_concurrent_downloads=1, symlink=True, use_cli=False
) -> List[GradientDatasetFile]:
    aws_credential = "gcdata-r"
    aws_endpoints = get_valid_aws_endpoints()

    s3 = boto3.Session(profile_name=aws_credential).client("s3", endpoint_url=aws_endpoints[0])

    # Disable thread use/transfer concurrency

    files_to_download: List[GradientDatasetFile] = []
    source_dirs_list = list(itertools.chain.from_iterable(directory_map.values()))
    for source_dir in source_dirs_list:
        source_dir_path = Path(source_dir)
        dataset_name = source_dir_path.name
        files_to_download.extend(list_files(s3, dataset_name))

    num_files = len(files_to_download)
    print(f"Downloading {num_files} from {len(source_dirs_list)} datasets")
    if symlink:
        files_to_download = apply_symlink(files_to_download, directory_map)

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
    total_elapsed = time.time() - start
    total_download_size = sum(o.result().gigabytes for o in outputs)
    print(
        f"Finished downloading {num_files} files: {total_download_size:.2f} GB in {total_elapsed:.2f}s ({total_download_size/total_elapsed:.2f}  GB/s)"
    )
    return files_to_download


def copy_graphcore_s3(args):
    # read in symlink config file
    json_data = Path(args.config_file).read_text()

    # substitute environment variables in the JSON data
    json_data = os.path.expandvars(json_data)
    config = json.loads(json_data)
    prepare_cred()
    source_dirs_exist_paths = parallel_download_dataset_from_s3(
        config,
        max_concurrency=args.max_concurrency,
        num_concurrent_downloads=args.num_concurrent_downloads,
        symlink=args.no_symlink,
    )


def symlink_arguments(parser = argparse.ArgumentParser()):

    parser.add_argument(
        "--gradient-dataset", action="store_true", help="Use gradient datasets rather than S3 storage access"
    )
    parser.add_argument("--no-symlink", action="store_false", help="Turn off the symlinking")
    parser.add_argument("--use-cli", action="store_true", help="Use the CLI instead of boto3")
    parser.add_argument(
        "--num-concurrent-downloads", default=1, type=int, help="Number of concurrent files to download"
    )
    parser.add_argument("--max-concurrency", default=1, type=int, help="S3 maximum concurrency")
    parser.add_argument("--config-file", default=str(Path(".").resolve().parent / "symlink_config.json"))
    return parser


def main(args):
    try:
        print("Starting disk usage \n", subprocess.check_output(["df", "-h"]).decode())
    except:
        pass
    print(args)
    if args.gradient_dataset:
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