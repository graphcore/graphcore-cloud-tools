# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import yaml
from typing import List
from pathlib import Path


def parse_yaml_config(args, parser):
    """Overwritting the command and default arguments with values
    specified in the configuration file. This method allows to 
    verify the correctness of the file arguments based on arguments
    defined in the parser.

    Args:
        args (object): Previously parsed arguments that will be updated.
        parser (object): The parser used to generate "args". The parser 
                         is applied to parse the file and overwrite the 
                         arguments in "args".

    Returns:
        object: Th args object updated with values from the yaml config.
    """

    def _read_yaml_config(config_filename):
        config_filename = Path(config_filename)
        with config_filename.open() as config_file:
            configs = yaml.full_load(config_file)
        return configs

    def _yaml_to_string_list(config: dict) -> List[str]:
        s_list = []
        for arg, value in config.items():
            s_list += [f'--{arg}']
            if type(value) == list:
                s_list += [str(element) for element in value]
            else:
                s_list += [str(value)]
        return s_list

    if args.config is not None:
        # Load the configurations from the YAML file
        # and update command line arguments
        configs = _read_yaml_config(args.config_path)
        if args.config not in configs:
            raise ValueError(f'unknown config {args.config} in config file. '
                             f'Available configs are {list(configs.keys())}.')
        string_list_config = _yaml_to_string_list(configs[args.config])
        config_args = parser.parse_args(string_list_config)
        parser.set_defaults(**vars(config_args))
        cmdline_args = parser.parse_args()
        args = cmdline_args

    return args
