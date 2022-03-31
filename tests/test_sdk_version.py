# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

from examples_utils import sdk_version


def test_sdk_version():
    assert isinstance(sdk_version(), str)
