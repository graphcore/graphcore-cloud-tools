# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

from .run_benchmarks import *

_incorrect_requirement_variant_error = ModuleNotFoundError(
    "To use notebook utilities `examples_utils` needs to have been installed with "
    "the [jupyter] set of requirements, reinstall the package with"
    " `pip install examples_utils[jupyter]`")
