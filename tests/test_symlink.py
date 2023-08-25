# Copyright (c) 2023 Graphcore Ltd. All rights reserved.
from typing import Dict, List
import pathlib
import pytest
import json
import argparse
from graphcore_cloud_tools.paperspace_utils import symlink_datasets_and_caches


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
    symlink_datasets_and_caches.symlink_gradient_datasets(argparse.Namespace(path=str(symlink_config)))

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
