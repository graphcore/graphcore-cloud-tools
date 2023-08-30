# Copyright (c) 2023 Graphcore Ltd. All rights reserved.
import sys
import pathlib
import pytest
from . import test_symlink
from . import testutils
from graphcore_cloud_tools.paperspace_utils import symlink_datasets_and_caches


REPO_ROOT = pathlib.Path(__file__).parents[1].resolve()
TEST_FILES_DIR = REPO_ROOT / "tests" / "test_files"


fake_data = test_symlink.fake_data
symlink_config = test_symlink.symlink_config
settings_file = test_symlink.settings_file
s3_datasets = test_symlink.s3_datasets
s3_endpoint_url = test_symlink.s3_endpoint_url


def test_symlink_command(symlink_config):
    """Test the support for fuse-overlay symlinks"""
    testutils.run_command_fail_explicitly(
        [
            sys.executable,
            "-m",
            "graphcore_cloud_tools",
            "paperspace",
            "symlinks",
            "--config-file",
            f"{symlink_config}",
        ],
        cwd=str(REPO_ROOT),
    )

@pytest.mark.parametrize("legacy", [False, True])
def test_s3_symlink_command(settings_file, s3_datasets, monkeypatch, legacy):
    """Test the direct S3 overlay method"""
    config_file, endpoint_url = s3_datasets
    monkeypatch.setenv(symlink_datasets_and_caches.AWS_ENDPOINT_ENV_VAR, endpoint_url)
    if legacy:
        monkeypatch.setenv(symlink_datasets_and_caches.DATASET_METHOD_OVERRIDE_ENV_VAR, "OVERLAY")
    testutils.run_command_fail_explicitly(
        [
            sys.executable,
            "-m",
            "graphcore_cloud_tools",
            "paperspace",
            "symlinks",
            "--config-file",
            f"{config_file}",
            "--gradient-settings-file",
            str(settings_file),
            "--s3-dataset",
        ],
        cwd=str(REPO_ROOT),
    )


def test_healthcheck_command(tmp_path, settings_file, symlink_config):
    testutils.run_command_fail_explicitly(
        [
            sys.executable,
            "-m",
            "graphcore_cloud_tools.paperspace_utils.health_check",
            "--log-folder",
            f"{tmp_path}",
            "--gradient-settings-file",
            str(settings_file),
            "--symlink-config-file",
            str(symlink_config),
        ],
        cwd=str(REPO_ROOT),
    )
