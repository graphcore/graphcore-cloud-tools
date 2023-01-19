# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import itertools
import logging
import subprocess
from argparse import ArgumentParser
from io import TextIOWrapper
from pathlib import Path

# Get the module logger
logger = logging.getLogger(__name__)


def ssh_copy_ids(poprun_hostnames: list, output_stream: TextIOWrapper):
    """Copy ssh ID

    Args:
        poprun_hostnames (list): Names/IPs of the hosts
        output_stream (TextIOWrapper): Open file to write stdout/stderr to

    """

    for hostname in poprun_hostnames:
        try:
            subprocess.run(
                ["ssh-copy-id", hostname],
                stdout=output_stream,
                stderr=output_stream,
            )
        except Exception as e:
            logger.error(f"Automated ssh-copy-id failed to {hostname}, with {e}.")
            logger.error(
                "please ensure ssh ids have been copied to all hosts "
                f"manually ('ssh-copy-id {hostname}') before "
                "attempting this benchmark."
            )


def setup_distributed_filesystems(args: ArgumentParser, poprun_hostnames: list):
    """Setup filesystems on all given poprun hosts for distributed instances.

    Notes:
        Poprun requires that the examples, sdks and venvs directories are
        available on all hosts in the exact same locations for things to work
        as intended. Here, these folders are copied to the host machines with
        rsync. In addition, ssh-copy-id is also run to ensure this host can
        talk to all others.

    Args:
        args (ArgumentParser): Arguments provided for this set of benchmarks
        poprun_hostnames (list): Names/IPs of all poprun hosts defined in this
            benchmark

    """

    dirs_to_sync = [args.examples_path, args.sdk_path, args.venv_path]

    with open(Path(args.log_dir, "host_setup.log"), "w") as output_stream:
        # Ensure this host can direct the others
        ssh_copy_ids(poprun_hostnames, output_stream)

        for hostname, dirname in itertools.product(poprun_hostnames, dirs_to_sync):
            try:
                remote_dest = hostname + ":" + str(Path(dirname).parent) + "/"
                rsync_cmd = ["rsync", "-au", dirname, remote_dest]

                logger.info(f"Copying {dirname} to {remote_dest}")
                subprocess.run(
                    rsync_cmd,
                    stdout=output_stream,
                    stderr=output_stream,
                )

            except Exception as e:
                logger.error(f"Rsync command {' '.join(rsync_cmd)} failed on {hostname} with {e}.")


def remove_distributed_filesystems(args: ArgumentParser, poprun_hostnames: list):
    """Remove filesystems on all given poprun hosts for distributed instances.

    Args:
        args (ArgumentParser): Arguments provided for this set of benchmarks
        poprun_hostnames (list): Names/IPs of all poprun hosts defined in this
            benchmark

    """

    dirs_to_remove = [args.examples_path, args.sdk_path, args.venv_path]

    with open(Path(args.log_dir, "host_teardown.log"), "w") as output_stream:
        for hostname, dirname in itertools.product(poprun_hostnames, dirs_to_remove):
            remove_cmd = ["rm", "-rf", dirname]

            try:
                remote_cmd = ["ssh", hostname]
                remote_cmd.extend(remove_cmd)
                subprocess.run(
                    remote_cmd,
                    stdout=output_stream,
                    stderr=output_stream,
                )

            except Exception as e:
                logger.warn(
                    f"Directory {dirname} on {hostname} could not be "
                    f"removed, with error {e}. `--remove-dirs-after` "
                    "has been set, so assuming the intent was to "
                    "remove this directory after the multi-host "
                    "benchmark was finished. Please remove this dir "
                    "manually if this is still wanted."
                )
