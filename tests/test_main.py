# Copyright (c) 2023 Graphcore Ltd. All rights reserved.
import sys
import pathlib
import os
import pytest
import json
from . import testutils


REPO_ROOT = pathlib.Path(__file__).parents[1].resolve()
TEST_FILES_DIR = REPO_ROOT / "tests" / "test_files"


@pytest.fixture
def symlink_config(tmp_path: pathlib.Path):
    config = tmp_path / "symlink_config.json"
    source = tmp_path / "source"
    source2 = tmp_path / "source2"
    target = tmp_path / "target"
    source.mkdir(parents=True)
    source2.mkdir(parents=True)
    (source / "test1.txt").write_text("test file 1")
    (source2 / "test2.txt").write_text("test file 2")
    config.write_text(json.dumps({str(target): [str(source), str(source2)]}))
    return config


def test_symlink_command(symlink_config):
    fuse_root = symlink_config.parent / "fusedoverlay"
    fuse_root.mkdir()
    os.environ["SYMLINK_FUSE_ROOTDIR"] = str(fuse_root)
    testutils.run_command_fail_explicitly(
        [sys.executable, "-m", "graphcore_cloud_tools", "paperspace", "symlinks", "--path", f"{symlink_config}"],
        cwd=str(REPO_ROOT),
    )
