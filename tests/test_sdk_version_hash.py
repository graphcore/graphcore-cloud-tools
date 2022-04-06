# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

from examples_utils.sdk_version_hash import sdk_version_hash


def test_sdk_version():
    assert isinstance(sdk_version_hash(), str)
