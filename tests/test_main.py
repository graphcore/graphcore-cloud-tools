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
    fuse_root = symlink_config.parent / "fusedoverlay"
    fuse_root.mkdir()
    os.environ["SYMLINK_FUSE_ROOTDIR"] = str(fuse_root)
    testutils.run_command_fail_explicitly(
        [sys.executable, "-m", "graphcore_cloud_tools", "paperspace", "symlinks", "--path", f"{symlink_config}"],
        cwd=str(REPO_ROOT),
    )
