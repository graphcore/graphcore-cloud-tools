# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import argparse
import atexit
from genericpath import exists
import logging
from multiprocessing.sharedctypes import Value
import os
import subprocess
import sys
import textwrap
import time
from datetime import timedelta
from io import TextIOWrapper
from typing import Tuple, Dict
from pathlib import Path
import shutil

from examples_utils.benchmarks.command_utils import (get_num_ipus, query_option_in_cmd)


class SlurmBenchmarkError(Exception):
    pass


# Get the module logger
logger = logging.getLogger(__name__)


def check_slurm_configured() -> bool:
    proc = subprocess.run("sinfo; sinfo | grep neverland",
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,
                          env=os.environ,
                          shell=True)
    if proc.returncode != 0:
        err_msg = ("You provided --submit-on-slurm however the use of SLURM is either "
                   "not configured on this host, or, the configured SLURM queue is not "
                   "compatible. Please contact the maintainers of this package for more information. ")
        raise SlurmBenchmarkError(err_msg)

    return True


def configure_slurm_environment_variables(env: dict):
    # if the user has an activated virtualenv, remove it from the path
    # otherwise the path to the venv will persist on the allocated node
    # and will affect package resolution
    # import pdb; pdb.set_trace()
    if "VIRTUAL_ENV" in env:
        env["PATH"] = ":".join([p for p in env["PATH"].split(":") if p != str(Path(env["VIRTUAL_ENV"]) / "bin")])

    return env


def configure_slurm_job_working_directory(job_wd: str) -> str:
    """Add instruction to bash job script to cd to the current job working directory
    Args:
        job_wd (str): absolute path to the current benchmark variant working directory
    Returns:
        bash instruction (str): cd to job working directory
    """
    return textwrap.dedent(f"""
        cd {job_wd}
    """)


def configure_slurm_python_command(cmd: list) -> str:
    """Add instruction to bash job script to execute the benchmark variant python command
    Args:
        cmd (list): benchmark variant command
    Returns:
        bash instruction (str): benchmark variant python command
    """
    python_index = query_option_in_cmd(cmd, ["python", "python3"])
    return textwrap.dedent(f"""
        {" ".join(cmd[python_index:])}
    """)


def configure_slurm_job_environment(args: argparse.ArgumentParser, variant_dict: Dict, variant_name: str,
                                    variant_log_dir: str) -> str:
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
    variant_log_dir_parts = variant_log_dir.parts
    examples_internal_index = variant_log_dir_parts.index("examples-internal")
    application_root = Path(*variant_log_dir_parts[0:examples_internal_index + 4])

    # make sure requirements exists in variant_dict
    if "requirements_path" not in variant_dict:
        err_msg = (
            "To run on SLURM, benchmark must have a field with key `requirements_path` "
            "that details the path from the root of the application to requirements.txt (inclusive) "
            "eg requirements_path=APPLICATION_ROOT/path/to/requirements.txt where APPLICATION_ROOT is not included.")
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

    bash_script = textwrap.dedent(f"""
        ORIG_DIR=$(pwd)
        # enable SDK (poplar and popart)
        cd {args.sdk_path}
        source enable
        echo "[INFO] Poplar SDK at {args.sdk_path} enabled"

        # create a temporary venv for this variant
        python3 -m venv {venv_path}
        trap 'echo "[INFO] Removing temporary venv"; rm -rf {venv_path}' EXIT

        # activate venv
        source {venv_path}/bin/activate
        echo "[INFO] Python venv at {venv_path} activated"
        
        # upgrade pip, setuptools and wheel
        python3 -m pip install -U pip
        python3 -m pip install -U setuptools wheel
    """)

    # determine cpu arch for tf1 & tf2 wheels
    bash_script += textwrap.dedent("""
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

        echo "[INFO] CPU ARCH is ${CPU_ARCH}"
    """)

    # Determine framework used and install packages needed
    framework = variant_name[0:3]
    if framework == "pyt":
        bash_script += textwrap.dedent("""
            python3 -m pip install poptorch*.whl
        """)
    elif framework == "tf1":
        bash_script += textwrap.dedent("""
            python3 -m pip install tensorflow-1*${CPU_ARCH}*.whl
            python3 -m pip install ipu_tensorflow_addons-1*.whl
        """)
    elif framework == "tf2":
        bash_script += textwrap.dedent("""
            python3 -m pip install tensorflow-2*${CPU_ARCH}*.whl
            python3 -m pip install ipu_tensorflow_addons-2*.whl
            python3 -m pip install keras-2*.whl
        """)
    else:
        err_msg = "Benchmark name should begin with pytorch, popart, tf1 or tf2."
        raise ValueError(err_msg)

    # application requirements
    bash_script += textwrap.dedent(f"""
        # Install application requirements
        cd {application_root}
        python3 -m pip install -r {requirements_path} --no-cache-dir

        echo "[INFO] Installed application requirements"
    """)

    # run build commands
    if pre_run_commands:
        for cmd in pre_run_commands:
            bash_script += textwrap.dedent(f"""
                eval {cmd}
            """)

    bash_script += textwrap.dedent(f'''
        echo "[INFO] Finished running pre run commands"
    ''')

    # go back to original dir
    bash_script += textwrap.dedent("""
        # go back to original directory"
        cd $ORIG_DIR
    """)

    return bash_script


def configure_slurm_hosts(poprun_config: dict, num_ipus: int) -> Tuple[str, int, int]:
    """Configure the number of instances to use on each host, and also 
    the number of hosts

    Args:
        poprun_config (dict): 
        num_ipus (int): 
    Returns 
        bash command, number of hosts, number of instances as a tuple
    """
    num_instances = 1
    if poprun_config["num_instances"] is not None:
        num_instances = int(poprun_config["num_instances"])

    num_hosts = 1
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
        bash_script = textwrap.dedent("""
            export SLURM_NTASKS_PER_NODE=1
        """)
    else:
        if (num_instances % num_hosts) != 0:
            err_msg = ("Number of poprun instances must divide number of hosts. "
                       f"Provided num_instances: {num_instances}. num_hosts: {num_hosts}.")
            raise ValueError(err_msg)
        else:
            bash_script = textwrap.dedent(f"""
                export SLURM_NTASKS_PER_NODE={int(num_instances / num_hosts)}
            """)

    # reconfigure the host set to be used for the job
    bash_script += textwrap.dedent(f"""
        NUM_HOSTS={num_hosts}
    """)

    bash_script += textwrap.dedent("""
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
        echo "[INFO] $HOSTS"

        export SLURM_JOB_NODELIST=$HOSTS
    """)

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
        bash_script += textwrap.dedent("""
            OLDIFS=$IFS
            IFS=','
            for host in $SLURM_JOB_NODELIST; do
                ssh-keygen -R $host
                ssh-keyscan -H $host >> ~/.ssh/known_hosts
            done
            IFS=$OLDIFS
        """)
    return bash_script, num_hosts, num_instances


def configure_slurm_ipu_partition(poprun_config: dict, num_ipus: int) -> str:
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

    # IPUOF_VIPU_API_HOST & IPUOF_VIPU_API_PORT will be deduced by poprun
    # on neverland this is guaranteed to be correct
    bash_script = textwrap.dedent("""
        export IPUOF_VIPU_API_PARTITION_ID=p${SLURM_JOB_ID}
        export ALLOCATION=c${SLURM_JOB_ID}
    """)

    if poprun_config == {}:
        bash_script += textwrap.dedent(f"""
            vipu create partition $IPUOF_VIPU_API_PARTITION_ID --allocation $ALLOCATION --size {num_ipus} --reconfigurable
        """)
    else:
        host_commands, num_hosts, num_instances = configure_slurm_hosts(poprun_config, num_ipus)
        bash_script += host_commands

        # add poprun options
        # make sure no whitespace is trailing after \\, otherwise multline commands will fail
        bash_script += textwrap.dedent(f"""
            poprun --host=$SLURM_JOB_NODELIST --num-instances={num_instances} \\
                --vipu-allocation=$ALLOCATION  --host-subnet={os.environ['SLURM_HOST_SUBNET_MASK']} \\
                {"" + poprun_config["other_args"]} \\""")

    return bash_script


def configure_slurm_job(args: argparse.ArgumentParser, benchmark_dict: Dict, poprun_config: Dict, cmd: list,
                        variant_name: str, variant_log_dir: str, job_wd: str, env: dict):
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
    Returns:
        SLURM configuration (dict): SLURM job submission information
    """

    logger.info("Configuring benchmark to run as a SLURM job")

    num_ipus = int(get_num_ipus(variant_name))

    # SLURM helper scripts to submit jobs depending on the number of IPUs
    if num_ipus <= 16:
        submission_script = "runonpod16.sh"
    elif num_ipus <= 64:
        submission_script = "runonpod64.sh"
    elif num_ipus <= 128:
        submission_script = "runonpod128.sh"
    elif num_ipus <= 256:
        submission_script = "runonpod256.sh"
    else:
        err_msg = "Benchmark cannot utilise more than 256 IPUs."
        raise ValueError(err_msg)

    # construct job submission bash script
    bash_script = "#!/bin/bash"
    bash_script += configure_slurm_job_working_directory(job_wd)
    bash_script += configure_slurm_job_environment(args, benchmark_dict, variant_name, variant_log_dir)
    bash_script += configure_slurm_ipu_partition(poprun_config, num_ipus)
    bash_script += configure_slurm_python_command(cmd)

    # output job submission script to variant logging dir
    job_script_path = variant_log_dir / "submit.sh"

    with open(job_script_path, "w") as script_handle:
        script_handle.write(bash_script)

    logger.info(f"SLURM job submission script created. Please view: {job_script_path}.")

    # configure stdout and stderr files for the job
    stdout_log_path = str(variant_log_dir / "stdout")
    stderr_log_path = str(variant_log_dir / "stderr")

    # pass --wait to sbatch so that we can obtain the return code from the submitted job
    slurm_job_command = [
        submission_script, "--wait", "--job-name", variant_name, "-e", stderr_log_path, "-o", stdout_log_path,
        job_script_path
    ]

    env = configure_slurm_environment_variables(env)

    return {
        "cmd": slurm_job_command,
        "stdout_log_path": stdout_log_path,
        "stderr_log_path": stderr_log_path,
        "job_name": variant_name,
        "timeout": args.timeout,
        "env": env
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
    proc = subprocess.run(["scancel", "--jobname", job_name],
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,
                          env=os.environ)
    if proc.returncode != 0:
        raise SlurmBenchmarkError(f"Unable to kill SLURM job: {job_name}"
                                  f"Exit code: {proc.returncode}."
                                  f"Reported error: {proc.stderr.decode()}.")


def run_and_monitor_progress_on_slurm(cmd: list,
                                      job_name: str,
                                      stdout_log_path: str,
                                      stderr_log_path: str,
                                      listener: TextIOWrapper,
                                      env: dict,
                                      timeout: int = None,
                                      **kwargs) -> Tuple[str, str, int]:
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

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=80, env=env, **kwargs)

    # make sure job is killed if the current thread is interrupted or exists unexpectedly
    atexit.register(kill_slurm_job, proc, job_name)

    job_submitted = False
    stdout_path = None
    stderr_path = None
    stdout_log = None
    stderr_log = None

    while proc.poll() is None and (stdout_path is None or stderr_path is None):
        if not job_submitted:
            o = proc.stdout.readline().decode()
            if "Submitted" in o:
                job_id = o.split()[-1]
                job_submitted = True
                logger.info(f"SLURM Job submitted. Job id: {job_id}. Job name: {job_name}")
        else:
            if Path(stdout_log_path).exists():
                stdout_path = stdout_log_path
            if Path(stderr_log_path).exists():
                stderr_path = stderr_log_path

    # something bad may have happened
    if proc.poll() is not None:
        exitcode = proc.returncode
        stdout_log = proc.stdout.read().decode()
        stderr_log = proc.stderr.read().decode()

        # cleanup just in case
        if exitcode != 0:
            kill_slurm_job(proc, job_name)
            atexit.unregister(kill_slurm_job)

        # cannot pick up additional information from log outputs
        # if the files don't exist, otherwise go ahead
        if stdout_log_path is None or stderr_log_path is None:
            return exitcode, stdout_log, stderr_log

    logger.info("Monitoring SLURM job")

    outs = [[], []]
    total_time = 0
    timeout_error = False

    # read stdout and stderr every 1s while the process is still active
    with open(stdout_path, "rb", 80) as stdout, open(stderr_path, "rb", 80) as stderr:
        while proc.poll() is None:

            stdout_data = stdout.read().decode()
            if stdout_data != '':
                outs[0].append(stdout_data)
                listener.write(stdout_data)

            stderr_data = stderr.read().decode()
            if stderr_data != '':
                outs[1].append(stderr_data)
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
        outs[0].extend(stdout.readlines())
        listener.write(outs[0][-1])
        outs[1].extend(stderr.readlines())
        listener.write(outs[1][-1])
        listener.flush()

    sys.stderr.write("\r")
    sys.stderr.write("\n")

    # construct stdout/stderr log for output
    if stdout_log is None:
        stdout_log = "".join(outs[0])
    else:
        stdout_log += "\n" + "".join(outs[0])

    if stderr_log is None:
        stderr_log = "".join(outs[1])
    else:
        stderr_log += "\n" + "".join(outs[1])

    if timeout_error:
        stderr_log += f"\nTimeout ({timeout})\n"

    exitcode = proc.returncode

    # does nothing if kill_slurm_job has been previously removed
    atexit.unregister(kill_slurm_job)

    return stdout_log, stderr_log, exitcode
