# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import sys

from examples_utils.command_logger.config_logger import ConfigLogger

if __name__ == "__main__":
    ConfigLogger.log_example_config_run()
    print("success")
