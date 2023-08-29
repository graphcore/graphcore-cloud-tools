# Copyright (c) 2023 Graphcore Ltd. All rights reserved.
from typing import Dict, List
import pathlib
import pytest
import json
import argparse
from graphcore_cloud_tools.paperspace_utils import symlink_datasets_and_caches
from moto.server import ThreadedMotoServer
import boto3
import subprocess


@pytest.fixture
def symlink_config(tmp_path: pathlib.Path, monkeypatch):
    config = tmp_path / "symlink_config.json"
    source = tmp_path / "source"
    source2 = tmp_path / "source2"
    target = tmp_path / "target"
    source.mkdir(parents=True)
    source2.mkdir(parents=True)
    (source / "test1.txt").write_text("test file 1")
    (source2 / "test2.txt").write_text("test file 2")
    config.write_text(json.dumps({str(target): [str(source), str(source2)]}))
    fuse_root = config.parent / "fusedoverlay"
    fuse_root.mkdir()
    monkeypatch.setenv("SYMLINK_FUSE_ROOTDIR", str(fuse_root))
    return config


def test_files_are_visible_in_symlink_folder(symlink_config: pathlib.Path):
    symlink_def: Dict[str, List[str]] = json.loads(symlink_config.read_text())
    expected_before_symlink_paths = []
    for target_path, source_paths in symlink_def.items():
        target_path = pathlib.Path(target_path).resolve()
        for source_path in source_paths:
            source_path = pathlib.Path(source_path).resolve()
            expected_before_symlink_paths.extend(
                [str((target_path / f.relative_to(source_path)).resolve()) for f in source_path.rglob("*")]
            )

    # Create the symlinks
    symlink_datasets_and_caches.symlink_gradient_datasets(argparse.Namespace(config_file=str(symlink_config)))

    # Get the list of files in the source directories
    expected_paths = []
    for target_path, source_paths in symlink_def.items():
        target_path = pathlib.Path(target_path).resolve()
        for source_path in source_paths:
            source_path = pathlib.Path(source_path).resolve()
            expected_paths.extend(
                [str((target_path / f.relative_to(source_path)).resolve()) for f in source_path.rglob("*")]
            )

    # Find all the files after symlink creation
    found = []
    for target_path, source_paths in symlink_def.items():
        target_path = pathlib.Path(target_path).resolve()
        found.extend([str(f) for f in target_path.rglob("*")])

    # Check that the source files haven't changed
    files_added_by_symlinking = [e for e in expected_paths if e not in expected_before_symlink_paths]
    assert (
        not files_added_by_symlinking
    ), f"Symlinking created files or folders in read/only space {files_added_by_symlinking}"
    # Check that the symlink files are there
    missing_files = [e for e in expected_paths if e not in found]
    assert not missing_files, f"There were missing files: {missing_files}\n found: {found}\n expected: {expected_paths}"


@pytest.fixture
def s3_endpoint_url():
    port = 7000
    endpoint_url=f"http://127.0.0.1:{port}"
    started_server = False
    i = 0
    for i in range(1000):
        server = ThreadedMotoServer(port=port + i)
        server.start()
        endpoint_url=f"http://127.0.0.1:{port + i}"
        try:
            subprocess.check_output(["curl", endpoint_url], timeout=5)
            started_server = True
            break
        except:
            server.stop()
            continue
    if not started_server:
        raise ValueError(f"Failed to mock S3 server on ports {port} to {port + i}")
    else:
        print(f"Started Mock S3 server at {endpoint_url}")
    yield endpoint_url
    server.stop()


@pytest.fixture
def s3_datasets(symlink_config: pathlib.Path, s3_endpoint_url: str):
    """Uploads the mocked datasets to a mock S3"""
    bucket = "sdk"
    conn = boto3.resource("s3", endpoint_url=s3_endpoint_url)
    try:
        conn.create_bucket(Bucket=bucket, CreateBucketConfiguration={
                'LocationConstraint': s3_endpoint_url
            },
        )
    except Exception as error:
        if "BucketAlreadyOwnedByYou" in  str(error):
            pass
        else:
            raise

    symlink_def: Dict[str, List[str]] = json.loads(symlink_config.read_text())
    new_symlink_def = {}
    sources = [pathlib.Path(source) for sources in symlink_def.values() for source in sources]
    # Upload files
    for key, sources in symlink_def.items():
        new_symlink_def[key] = []
        for source in sources:
            source = pathlib.Path(source)
            out = subprocess.check_output(["aws", "s3", "sync", "--endpoint-url", s3_endpoint_url, source, f"s3://{bucket}/{symlink_datasets_and_caches.S3_DATASET_FOLDER}/{source.name}/"])
            print(out)
            new_symlink_def[key].append(f"/{symlink_datasets_and_caches.S3_DATASET_FOLDER}/{source.name}")

    new_config = symlink_config.parent / f"{symlink_config.name}-s3.json"
    new_config.write_text(json.dumps(new_symlink_def))
    return (new_config, s3_endpoint_url)


def test_s3_linking(monkeypatch, s3_datasets):
    config_file, endpoint_url = s3_datasets
    monkeypatch.setenv(symlink_datasets_and_caches.AWS_ENDPOINT_ENV_VAR, endpoint_url)
    config = json.loads(config_file.read_text())
    symlink_datasets_and_caches.prepare_cred()
    source_dirs_exist_paths = symlink_datasets_and_caches.parallel_download_dataset_from_s3(
        config,
        max_concurrency=1,
        num_concurrent_downloads=1,
        symlink=True,
        endpoint_fallback=False,
    )
    assert False