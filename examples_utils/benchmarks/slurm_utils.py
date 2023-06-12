# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

from __future__ import annotations
import argparse
import atexit
import logging
import os
import subprocess
import sys
import textwrap
import time
from datetime import timedelta
from io import TextIOWrapper
from typing import Tuple, Dict, Any
from pathlib import Path
import shutil
import shlex

from examples_utils.benchmarks.command_utils import get_num_ipus, query_option_in_cmd, determine_variant_timeout

# Get the module logger
logger = logging.getLogger(__name__)


class SlurmBenchmarkError(Exception):
    pass


class StringFileEmulator:
    def __init__(self, file_path):
        self.file_path = file_path
        self._open_for_reading()

    def _open_for_reading(self) -> None:
        self.file = open(self.file_path, "r")

    def splitlines(self):
        self.file.seek(0)
        for line in self.file:
            yield line

    def split(self, str_pattern: str):
        self.file.seek(0)
        if str_pattern == "\n":
            for line in self.file:
                yield line
        else:
            for line in self.file:
                for elem in line.split(str_pattern):
                    yield elem

    def __add__(self, rh_str: str) -> StringFileEmulator:
        if isinstance(rh_str, str):
            self.file.close()
            with open(self.file_path, "a") as f:
                f.write(rh_str)
            self._open_for_reading()
            return self
        else:
            raise ValueError(
                "binary operator `+` with `StringFileEmulator` objects only supported with `str` right hand side operands"
            )

    def __contains__(self, value: Any) -> bool:
        self.file.seek(0)
        for line in self.file:
            if value in line:
                return True
        return False

    def close(self) -> None:
        self.file.close()


def check_slurm_configured() -> bool:
    proc = subprocess.run(
        "sinfo; sinfo | grep neverland",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ,
        shell=True,
    )
    if proc.returncode != 0:
        err_msg = (
            "You provided --submit-on-slurm however the use of SLURM is either "
            "not configured on this host, or, the configured SLURM queue is not "
            "compatible. Please contact the maintainers of this package for more information. "
        )
        raise SlurmBenchmarkError(err_msg)

    return True


def configure_environment_variables(env: dict):
    # These values are the same on all SLURM job hosts
    env["RNIC_SUBNET_MASK"] = "10.5.0.0/16"
    env["IPUOF_VIPU_API_HOST"] = "angelsfall-ctrl"
    env["IPUOF_VIPU_API_PORT"] = "8090"

    # if the user has an activated virtualenv, remove it from the path
    # otherwise the path to the venv will persist on the allocated node
    # and will affect package resolution
    if "VIRTUAL_ENV" in env:
        env["PATH"] = ":".join([p for p in env["PATH"].split(":") if p != str(Path(env["VIRTUAL_ENV"]) / "bin")])
    return env


def configure_job_working_directory(job_wd: str) -> str:
    """Add instruction to bash job script to cd to the current job working directory
    Args:
        job_wd (str): absolute path to the current benchmark variant working directory
    Returns:
        bash instruction (str): cd to job working directory
    """
    return textwrap.dedent(
        f"""
        cd {job_wd}
    """
    )


def configure_python_command(cmd: list) -> str:
    """Add instruction to bash job script to execute the benchmark variant python command
    Args:
        cmd (list): benchmark variant command
    Returns:
        bash instruction (str): benchmark variant python command
    """
    python_index = query_option_in_cmd(cmd, ["python", "python3"])
    return textwrap.dedent(
        f"""
        {shlex.join(cmd[python_index:])}
    """
    )


def configure_job_environment(
    args: argparse.ArgumentParser,
    variant_dict: Dict,
    variant_name: str,
    variant_log_dir: str,
) -> str:
    """Add instruction to bash job script to:
    1. Activate poplar SDK
    2. Create and activate a python venv
    3. Run pre application run build commands
    Args:
        args (argparse.Namespace): Arguments passed to run the benchmarks
            with
        variant (Dict): Dictionary containing information to configure the job environment. Path to requirements.txt
            for installing python dependencies. Path/list of required system libraries e.g. libturbojpeg. Pre run commands to be
            executed before running the benchmark command e.g. make/ make clean.
        variant_name (str): Name of the benchmark variant being run
        variant_log_dir (str): Path for storing this variants outputs
        job_wd (str): absolute path to the current benchmark variant working directory
    Returns:
        bash comamnds (str): commands that activate a poplar SDK, create a python venv and run build commands
    """

    # get application root path
    variant_log_dir_parts = Path(variant_dict["benchmark_path"]).parts
    examples_internal_index = variant_log_dir_parts.index("examples-internal")
    application_root = Path(*variant_log_dir_parts[0 : examples_internal_index + 4])

    # make sure requirements exists in variant_dict
    if "requirements_path" not in variant_dict:
        err_msg = (
            "To run on SLURM, benchmark must have a field with key `requirements_path` "
            "that details the path from the root of the application to requirements.txt (inclusive) "
            "eg requirements_path=APPLICATION_ROOT/path/to/requirements.txt where APPLICATION_ROOT is not included."
        )
        raise SlurmBenchmarkError(err_msg)

    requirements_path = application_root / Path(variant_dict.get("requirements_path"))
    if not requirements_path.exists():
        err_msg = f"benchmark key: requirements_path with value {str(requirements_path)} does not exist."
        raise FileNotFoundError(err_msg)

    venv_path = variant_log_dir / ("venv" + str(os.getpid()))
    if venv_path.exists():
        warn_msg = f"variant venv dir already exists. Rebuilding path {venv_path}"
        logger.warning(warn_msg)
        shutil.rmtree(venv_path)

    pre_run_commands = variant_dict.get("pre_run_commands", None)
    pip_install_str = "python3 -m pip install --no-cache-dir"

    bash_script = textwrap.dedent(
        f"""
        ORIG_DIR=$(pwd)
        echo "[INFO] Enabling Poplar SDK at {args.sdk_path}"
        cd {args.sdk_path}
        source enable

        # create a temporary venv for this variant
        echo "[INFO] Creating and activating python venv at {venv_path}"
        python3 -m venv {venv_path}
        trap 'echo "[INFO] Removing temporary venv"; rm -rf {venv_path}' EXIT

        # activate venv
        source {venv_path}/bin/activate

        echo "[INFO] Upgrading pip, setuptools and wheel"
        {pip_install_str} --upgrade setuptools wheel pip
    """
    )

    # determine cpu arch for tf1 & tf2 wheels
    bash_script += textwrap.dedent(
        """
        echo "[INFO] determining CPU arch"
        amd_arch=$(cpuinfo | grep -i amd)
        intel_arch=$(cpuinfo | grep -i intel)
        if ! [[ -z amd_arch ]]
        then
            CPU_ARCH="amd"
        elif ! [[ -z intel_arch ]]
        then
            CPU_ARCH="intel"
        else
            echo "[ERROR] Only amd and intel arch are supported for now.." 1>&2
            exit 1
        fi

        echo "[INFO] CPU arch is ${CPU_ARCH}"
    """
    )

    # Determine framework used and install packages needed
    bash_script += textwrap.dedent(
        """
        echo "[INFO] Installing framework wheel files"
    """
    )

    framework = variant_name[0:3]
    if framework == "pyt":
        packages = "poptorch-*.whl"
    elif framework == "tf2":
        packages = "tensorflow-2*${CPU_ARCH}*.whl ipu_tensorflow_addons-2*.whl keras-2*.whl"
    elif framework == "pop":
        pass
    else:
        err_msg = "Benchmark name should begin with pytorch, popart or tf2. Other frameworks are not supported."
        raise ValueError(err_msg)

    if framework != "pop":
        bash_script += textwrap.dedent(
            f"""
            {pip_install_str} {packages}
        """
        )

    # application requirements
    bash_script += textwrap.dedent(
        f"""
        echo "[INFO] Installing application requirements"
        cd {application_root}
        {pip_install_str} -r {requirements_path}
        echo "[INFO] Installed application requirements"
    """
    )

    # run build commands
    bash_script += textwrap.dedent(
        f"""
        echo "[INFO] Running pre run commands"
    """
    )

    if pre_run_commands:
        for cmd in pre_run_commands:
            bash_script += textwrap.dedent(
                f"""
                eval {cmd}
            """
            )

    bash_script += textwrap.dedent(
        f"""
        echo "[INFO] Finished running pre run commands"
    """
    )

    # go back to original dir
    bash_script += textwrap.dedent(
        """
        # go back to original directory"
        cd $ORIG_DIR
    """
    )

    return bash_script


def configure_hosts(poprun_config: dict, num_ipus: int) -> Tuple[str, int, int]:
    """Configure the number of instances to use on each host, and also
    the number of hosts

    Args:
        poprun_config (dict):
        num_ipus (int):
    Returns
        bash command, number of hosts, number of instances as a tuple
    """

    num_instances = 1
    num_hosts = 1

    if poprun_config != {}:
        if poprun_config["num_instances"] is not None:
            num_instances = int(poprun_config["num_instances"])

        if poprun_config["host"] is not None:
            # users want to use a specific number of hosts
            # set this depending on the default number of hosts
            # available on each POD size
            if num_ipus <= 16:
                num_hosts = 1
            elif num_ipus <= 64:
                num_hosts = 4
            elif num_ipus <= 128:
                num_hosts = 8
            elif num_ipus <= 256:
                num_hosts = 16

    # reconfigure number of instances per host before moving to the next host
    if num_instances < num_hosts:
        bash_script = textwrap.dedent(
            """
            export SLURM_NTASKS_PER_NODE=1
        """
        )
    else:
        if (num_instances % num_hosts) != 0:
            err_msg = (
                "Number of poprun instances must divide number of hosts. "
                f"Provided num_instances: {num_instances}. num_hosts: {num_hosts}."
            )
            raise ValueError(err_msg)
        else:
            bash_script = textwrap.dedent(
                f"""
                export SLURM_NTASKS_PER_NODE={int(num_instances / num_hosts)}
            """
            )

    # reconfigure the host set to be used for the job
    bash_script += textwrap.dedent(
        f"""
        NUM_HOSTS={num_hosts}
    """
    )

    bash_script += textwrap.dedent(
        """
        echo "[INFO] Determining restricted host set from $SLURM_JOB_NODELIST"
        BASE=$(echo $SLURM_JOB_NODELIST  | cut -d '-' -f 1,2)
        if [ "${SLURM_JOB_NODELIST/[/}" == "${SLURM_JOB_NODELIST}" ]
        then NODELIST=$SLURM_JOB_NODELIST
        else
            #echo base=$BASE
            NODERANGE=$(echo $SLURM_JOB_NODELIST | cut -d '-' -f 3,4,5,6 | sed -e "s/\[/{/" -e "s/\-/../g" -e "s/\]/}/" -e "s/,/} {/")
            RAWNODELIST=$(sed "s/{/$BASE-{/g" <<< $NODERANGE )
            #echo raw $RAWNODELIST
            NODELIST=$(eval echo $(echo $RAWNODELIST))
        fi
        #echo node $NODELIST
        COUNT=$(echo $NODELIST | wc -w)
        SKIP=$((COUNT/NUM_HOSTS))
        I=0
        read -a NA <<< $NODELIST
        HOSTS=""
        while [ $I -lt $((COUNT+1)) ]
        do
            HOSTS="$HOSTS,${NA[$I]}"
            I=$(($I+$SKIP))
        done
        HOSTS=$(sed -e 's/^,//g' -e 's/,$//g' <<<$HOSTS)
        echo "[INFO] Restricted host set is: $HOSTS"

        export SLURM_JOB_NODELIST=$HOSTS
    """
    )

    # for multi host runs on neverland cl1:
    # 1. Poprun can deduce the subnet mask by considering the network
    # address of an RNIC or the default gateway
    #
    # 2. No need to synchronize python venv, poplar sdk, as they are stored
    # on a shared drive
    #
    # 3. No need to distribute ssh-keys as the public key and private keys
    # are on a shared network drive. Also, cat id_rsa.pub > authorized_keys
    # has been done so no need to password authenticate. The only user interaction
    # that may happen if rsync is needed to other hosts, however the other
    # hosts are not populated in known_hosts, but that can be done:

    if num_hosts > 1:
        # update host public IPs
        bash_script += textwrap.dedent(
            """
            echo "[INFO] Adding host public IPs to known hosts"
            OLDIFS=$IFS
            IFS=','
            for host in $SLURM_JOB_NODELIST; do
                ssh-keygen -R $host
                ssh-keyscan -H $host >> ~/.ssh/known_hosts
            done
            IFS=$OLDIFS
        """
        )
    return bash_script


def configure_ipu_partition(poprun_config: dict, num_ipus: int) -> str:
    """Add instruction to bash job script to create a compatible partition for
    the benchmark variant. If the benchmark variant is using poprun, poprun will
    be used to create the partition. If it is not using poprun, vipu will be used
    to create the partition

    Args:
        poprun_config (Dict): output of command_utils.get_poprun_config
        num_ipus (str): the number of ipus required for the benchmark variant
    Returns:
        bash instruction (str): commands to create a partition
    """

    # TODO: support recreation of clusters for jobs that require more than one ild
    # this is currently not supported on the neverland SLURM queue but will be in the
    # the future

    bash_script = textwrap.dedent(
        """
        export IPUOF_VIPU_API_PARTITION_ID=p${SLURM_JOB_ID}
        export ALLOCATION=c${SLURM_JOB_ID}

        echo "[INFO] Configuring IPU partition and running benchmark"
    """
    )

    if poprun_config == {}:
        bash_script += textwrap.dedent(
            f"""
            vipu create partition $IPUOF_VIPU_API_PARTITION_ID --allocation $ALLOCATION --size {num_ipus} --reconfigurable
        """
        )
    else:
        num_ilds = poprun_config["num_ilds"]
        if num_ilds is None:
            num_ilds = 1
        else:
            try:
                num_ilds = int(num_ilds)
            except ValueError:
                raise ValueError("Poprun --num-ilds option must be of integral type")
            if num_ilds > 1 and num_ipus < 128:
                logger.warning(
                    "The Slurm queue does not support augmenting the cluster specification. Forcing --num-ilds to 1."
                )
                num_ilds = 1

        # add poprun options
        # make sure no whitespace is trailing after \\, otherwise multline commands will fail
        bash_script += textwrap.dedent(
            f"""
            poprun \\
                --host=$SLURM_JOB_NODELIST \\
                --num-ilds {num_ilds} \\
                --num-instances={int(poprun_config.get("num_instances", 1))} \\
                --vipu-allocation=$ALLOCATION  \\
                --mpi-global-args="--mca oob_tcp_if_include $RNIC_SUBNET_MASK --mca btl_tcp_if_include $RNIC_SUBNET_MASK" \\
                {poprun_config["other_args"]} \\"""
        )

    return bash_script


def configure_datasets(cmd, poprun_config) -> str:
    # identify if cmd has any entries relying on $DATASETS_DIR
    datasets_dir = os.environ.get("DATASETS_DIR")
    local_datasets_dir = Path("/localdata", "examples-datasets")
    rsync_dirs = []
    for i, src in enumerate(cmd):
        if datasets_dir in src:
            example_dataset = Path(src).relative_to(datasets_dir)
            dest = local_datasets_dir / example_dataset
            cmd[i] = str(dest)
            # the destination for rsync is the parent dir of dest,
            # rsync will create the required dir from src
            rsync_dirs.append((src, Path(dest).parent))

    # add instructions to rsync datasets
    if len(rsync_dirs) == 0:
        return "", cmd
    else:
        bash_script = textwrap.dedent(
            """
            echo "[INFO] rsyncing datasets to a local destination"
        """
        )

        # not using poprun
        if poprun_config == {}:
            rsync_cmds = "\n".join(
                [f"mkdir -p {dest}; rsync --copy-links -au {src} {dest} " for src, dest in rsync_dirs]
            )
            bash_script += "\n" + rsync_cmds + "\n"
        else:
            rsync_cmds = "\n".join(
                [f"mkdir -p $host:{dest}; rsync --copy-links -au {src} $host:{dest} &" for src, dest in rsync_dirs]
            )
            bash_script += textwrap.dedent(
                f"""
                OLDIFS=$IFS
                IFS=','
                for host in $SLURM_JOB_NODELIST; do
                    {rsync_cmds}
                done
                wait
                IFS=$OLDIF
            """
            )

    return bash_script, cmd


def configure_slurm_job(
    args: argparse.ArgumentParser,
    benchmark_dict: Dict,
    poprun_config: Dict,
    cmd: list,
    variant_name: str,
    variant_log_dir: str,
    job_wd: str,
    env: dict,
    rsync_datasets: bool = False,
):
    """Construct a bash script that will be used to submit the given benchmark variant
    in a SLURM queue. The bash script is created in a series of steps:

    1. Configure job working directory
    2. Configure poplar SDK and python venv to be used
    3. Configure the IPU partition to be used for the job
    4. Add the python command to be run on the SLURM allocated node

    The bash script is then output to the logging directory for the given benchmark variant

    Args:
        args (argparse.Namespace): Arguments passed to run the benchmarks
            with
        benchmark_dict (dict): The benchmark definition from the yaml file
        poprun_config (dict): output of command_utils.get_poprun_config
        requirements (str): path to requirements.txt to be used for installing packages
        cmd (list): benchmark variant command
        variant_name (str): benchmark variant name
        variant_log_dir (str): absolute path to dir used to store execution logs
        job_wd (str): absolute path to the current benchmark variant working directory
        env (dict): dictionary with environment variables to be used in benchmark subprocess
        rsync_datasets (bool): rsync datasets from network storage to local storage
    Returns:
        SLURM configuration (dict): SLURM job submission information
    """

    # TODO: expose dataset rsync to users

    logger.info("Configuring benchmark to run as a SLURM job")

    num_ipus = int(get_num_ipus(variant_name))

    # SLURM helper scripts to submit jobs depending on the number of IPUs
    machine_type = {"any": "", "mk2": "c", "mk2w": "w"}[args.slurm_machine_type]

    if num_ipus <= 16:
        submission_script = f"runonpod16{machine_type}.sh"
    elif num_ipus <= 64:
        submission_script = f"runonpod64{machine_type}.sh"
    elif num_ipus <= 128:
        submission_script = f"runonpod128{machine_type}.sh"
    elif num_ipus <= 256:
        submission_script = f"runonpod256{machine_type}.sh"
    else:
        err_msg = "Benchmark cannot utilise more than 256 IPUs."
        raise ValueError(err_msg)

    env = configure_environment_variables(env)

    # construct job submission bash script
    bash_script = "#!/bin/bash"
    bash_script += configure_job_working_directory(job_wd)
    bash_script += configure_job_environment(args, benchmark_dict, variant_name, variant_log_dir)
    bash_script += configure_hosts(poprun_config, num_ipus)
    if rsync_datasets:
        rsync_commands, cmd = configure_datasets(cmd, poprun_config)
        bash_script += rsync_commands
    bash_script += configure_ipu_partition(poprun_config, num_ipus)
    bash_script += configure_python_command(cmd)

    # output job submission script to variant logging dir
    job_script_path = str(variant_log_dir / "submit.sh")

    with open(job_script_path, "w") as script_handle:
        script_handle.write(bash_script)

    logger.info(f"SLURM job submission script created. Please view: {job_script_path}")

    # configure stdout and stderr files for the job
    stdout_log_path = str(variant_log_dir / "stdout")
    stderr_log_path = str(variant_log_dir / "stderr")

    # pass --wait to sbatch so that we can obtain the return code from the submitted job
    if args.slurm_resource_reservation is not None:
        slurm_job_command = [
            submission_script,
            "--reservation",
            args.slurm_resource_reservation,
        ]
    else:
        slurm_job_command = [submission_script]
    slurm_job_command += [
        "--wait",
        "--job-name",
        variant_name,
        "-e",
        stderr_log_path,
        "-o",
        stdout_log_path,
        job_script_path,
    ]

    variant_timeout = determine_variant_timeout(args.timeout, benchmark_dict)

    return {
        "cmd": slurm_job_command,
        "stdout_log_path": stdout_log_path,
        "stderr_log_path": stderr_log_path,
        "job_name": variant_name,
        "timeout": variant_timeout,
        "env": env,
    }


def kill_slurm_job(proc: subprocess.Popen, job_name: str) -> None:
    """Clean up if the job launching subprocess exits uncleanly
    or the user issues an interrupt

    Args:
        proc (python subprocess): job submission process
        job_name (str): name of the job
    """
    proc.kill()
    logger.warning("SLURM job launching process exited abnormally." f" Killing job with job name: {job_name}")
    proc = subprocess.run(
        ["scancel", "--jobname", job_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ,
    )
    if proc.returncode != 0:
        raise SlurmBenchmarkError(
            f"Unable to kill SLURM job: {job_name}"
            f"Exit code: {proc.returncode}."
            f"Reported error: {proc.stderr.decode()}."
        )


def run_and_monitor_progress_on_slurm(
    cmd: list,
    job_name: str,
    stdout_log_path: str,
    stderr_log_path: str,
    listener: TextIOWrapper,
    env: dict,
    timeout: int = None,
    **kwargs,
) -> Tuple[str, str, int]:
    """
    Run the benchmark in the SLURM queue and monitor progress.

    Args:
        cmd (list): The command to be run, as a list for use by subprocess
        job_name (str): the SLURM job name for the given benchmark
        stdout_log_path (str): Absolute path to stdout from the SLURM job
        stderr_log_path (str): Absolute path to stderr from the SLURM job
        listener (TextIOWrapper): Listener that takes the output from the process
        env (dict): dictionary of environment variables to propagate to SLURM allocated nodes
        timeout (int): Seconds until the process will timeout, forcing termination
        kwargs: all additional keyword arguments are passed to `subprocess.Popen`.

    Returns:
        output (str): stdout from the process
        err (str): stderr from the process
        exitcode (int): The process exitcode

    """

    logger.info("Submitting SLURM job")

    logger.info(f"SLURM Job submission command: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=80,
        env=env,
        **kwargs,
    )

    # make sure job is killed if the current thread is interrupted or exists unexpectedly
    atexit.register(kill_slurm_job, proc, job_name)

    job_submitted = False
    stdout_path = None
    stderr_path = None

    # poll until job has been submited every 1s
    while proc.poll() is None and (stdout_path is None or stderr_path is None):
        if job_submitted:
            if Path(stdout_log_path).exists():
                stdout_path = stdout_log_path
            if Path(stderr_log_path).exists():
                stderr_path = stderr_log_path
        else:
            o = proc.stdout.readline().decode()
            if "Submitted" in o:
                job_id = o.split()[-1]
                job_submitted = True
                logger.info(f"SLURM Job submitted. Job id: {job_id}. Job name: {job_name}")
        time.sleep(1)

    logger.info("Monitoring SLURM job")

    # something bad may have happened
    if proc.poll() is not None:
        logger.info("Something unexpected occurred while monitoring SLURM job." " Attempting to extract logs.")

        exitcode = proc.returncode
        stdout_log = proc.stdout.read().decode()
        stderr_log = proc.stderr.read().decode()

        # cleanup just in case
        if exitcode != 0:
            kill_slurm_job(proc, job_name)
            atexit.unregister(kill_slurm_job)

        # cannot pick up additional information from log outputs
        # if the files don't exist, otherwise go ahead
        if Path(stdout_log_path).exists() and Path(stderr_log_path).exists():
            stdout_path = stdout_log_path
            stderr_path = stderr_log_path
        else:
            return exitcode, stdout_log, stderr_log

    total_time = 0
    timeout_error = False

    # read stdout and stderr every 1s while the process is still active
    with open(stdout_path, "rb", 80) as stdout, open(stderr_path, "rb", 80) as stderr:
        while proc.poll() is None:
            stdout_data = stdout.read().decode()
            if stdout_data != "":
                listener.write(stdout_data)

            stderr_data = stderr.read().decode()
            if stderr_data != "":
                listener.write(stderr_data)

            listener.flush()

            time.sleep(1)
            total_time += 1

            if timeout is not None and total_time >= timeout:
                logger.error("TIMEOUT")
                timeout_error = True
                proc.kill()
                kill_slurm_job(proc, job_name)
                atexit.unregister(kill_slurm_job)

            sys.stderr.write("\r")
            sys.stderr.write(f"\tBenchmark elapsed time: {str(timedelta(seconds=total_time))} ({total_time} seconds)")
            sys.stderr.flush()

        # read the rest
        listener.write("".join(stdout.readlines()))
        listener.write("".join(stderr.readlines()))
        listener.flush()

    sys.stderr.write("\r")
    sys.stderr.write("\n")

    # open stdout and stderr log files which will be processed for metrics
    stdout_log = StringFileEmulator(stdout_path)
    stderr_log = StringFileEmulator(stderr_path)
    atexit.register(lambda x: x.close(), stdout_log)
    atexit.register(lambda x: x.close(), stderr_log)

    if timeout_error:
        stderr_log += f"\nTimeout ({timeout})\n"

    exitcode = proc.returncode

    # does nothing if kill_slurm_job has been previously removed
    atexit.unregister(kill_slurm_job)

    return stdout_log, stderr_log, exitcode
