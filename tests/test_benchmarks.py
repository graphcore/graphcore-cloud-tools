# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import tempfile
import os
import pathlib
import pytest
from examples_utils.benchmarks.environment_utils import get_git_commit_hash

cwd = pathlib.Path.cwd()


@pytest.fixture(autouse=True)
def teardown():
    yield
    os.chdir(cwd)


def test_git_commit_hash_in_repo():
    os.chdir(pathlib.Path(__file__).parent)
    hash = get_git_commit_hash()
    assert (is_sha_1(hash))


def test_git_commit_hash_out_of_repo():
    os.chdir(tempfile.gettempdir())
    not_a_hash = get_git_commit_hash()
    assert "Not a git repo" in not_a_hash


def is_sha_1(hash_input: str) -> bool:
    # length check
    if len(hash_input) != 40:
        return False

    # can convert to hex value
    try:
        int(hash_input, 16)
    except:
        return False
    return True
