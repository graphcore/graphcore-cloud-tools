# Copyright (c) 2023 Graphcore Ltd. All rights reserved.
import sys
import pathlib
import os
from . import test_symlink
from . import testutils


REPO_ROOT = pathlib.Path(__file__).parents[1].resolve()
TEST_FILES_DIR = REPO_ROOT / "tests" / "test_files"


symlink_config = test_symlink.symlink_config


def test_symlink_command(symlink_config):

    testutils.run_command_fail_explicitly(
        [sys.executable, "-m", "graphcore_cloud_tools", "paperspace", "symlinks", "--config-file", f"{symlink_config}"],
        cwd=str(REPO_ROOT),
    )


def test_healthcheck_command(tmp_path):
    testutils.run_command_fail_explicitly(
        [sys.executable, "-m", "graphcore_cloud_tools.paperspace_utils.health_check", "--log-folder", f"{tmp_path}"],
        cwd=str(REPO_ROOT),
    )
