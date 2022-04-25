# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import os
from examples_utils.load_lib_utils.cppimport_safe import cppimport_build_safe

cd = os.path.dirname(os.path.abspath(__file__))
cppimport_build_safe(os.path.join(cd, 'sdk_version_hash_lib.cpp'))
from . import sdk_version_hash_lib

__all__ = ['sdk_version_hash']


def sdk_version_hash() -> str:
    """Graphcore SDK version hash (sanitised output from C++ function `poplar::packageHash`)"""
    return sdk_version_hash_lib.sdk_version_hash()
