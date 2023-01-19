# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import unittest
import argparse

from examples_utils.parsing import file_argparse


def add_arguments(parser):
    parser.add_argument("--config", type=str)
    parser.add_argument("--config-path", type=str)
    parser.add_argument("--model-name", type=str)
    return parser


class LoadingConfigsTest(unittest.TestCase):
    def test_loading_configs(self):
        parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser = add_arguments(parser)
        args = parser.parse_args(["--config", "resnet8_test", "--config-path", "tests/test_files/configs.yml"])
        args = file_argparse.parse_yaml_config(args, parser)
        assert args.model_name == "cifar_resnet8"
