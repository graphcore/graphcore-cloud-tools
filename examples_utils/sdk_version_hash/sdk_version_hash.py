# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import cppimport.import_hook
from . import sdk_version_hash_lib

__all__ = ["sdk_version_hash"]


def sdk_version_hash() -> str:
    """Graphcore SDK version hash (sanitised output from C++ function `poplar::packageHash`)"""
    return sdk_version_hash_lib.sdk_version_hash()
