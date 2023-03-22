# Copyright (c) 2023 Graphcore Ltd. All rights reserved.

import base64
import copy
import hashlib
import ipynbname
import json
import nbformat
import os
import pkg_resources
import psutil
import subprocess
import time
import multiprocessing as mp


from datetime import datetime
from pathlib import Path


class GCLogger(object):
    _instance = None
    _CREATION_TIME = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    _GC_LOG_STATE = None
    _GC_LOG_PATH = Path("/notebooks").joinpath("gc_logs", f"{_CREATION_TIME}")

    _FAST_POLLING_SECONDS = 10
    _SLOW_POLLING_SECONDS = 60

    proc_list = []

    _BUCKET_NAME = "paperspace-uploading-test-bucket"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GCLogger, cls).__new__(cls)

            if cls._GC_LOG_STATE is None:
                # Request user and save their preferred choice
                print(
                    "\n============================================================================================================================================\n"
                    "Graphcore would like to collect information about the applications and code being run in this notebook, as well as the system it's being run \n"
                    "on to improve usability and support for future users. The information will be anonymised and sent to Graphcore \n\n"
                    "You can disable this at any time by running `GCLogger.stop_logging()'`.\n\n"
                    "Unless logging is disabled, the following information will be collected:\n"
                    "\t- User progression through the notebook\n"
                    "\t- Notebook details: number of cells, code being run and the output of the cells\n"
                    "\t- ML application details: Model information, performance, hyperparameters, and compilation time\n"
                    "\t- Environment details\n"
                    "\t- System performance: IO, memory and host compute performance\n\n"
                    f"You can view the information being collected at: {cls._GC_LOG_PATH}\n"
                    "=============================================================================================================================================\n"
                )

                cls._GC_LOG_PATH.mkdir(parents=True, exist_ok=True)

                # Create a short unique user ID
                cls._UNIQUE_HASH = base64.urlsafe_b64encode(
                    hashlib.md5(cls._CREATION_TIME.encode("utf-8")).digest()
                ).decode("ascii")[:12]

                # Help IPython find our custom extension
                extension_path = Path(__file__).parent.joinpath("cell_logger.py").resolve()
                destination_path = Path("/root/.ipython/extensions").resolve()

                subprocess.run(f"cp {extension_path} {destination_path}", shell=True)

                # Create necessary folders for later
                destination_path.joinpath("cell_logs", "errors").mkdir(parents=True, exist_ok=True)

        return cls._instance

    @classmethod
    def __write_json(cls, dict_to_write, filename, mode="w"):

        try:
            json_path = cls._GC_LOG_PATH.joinpath(f"{filename}.json")

            if mode == "w":
                with open(json_path, "w") as outfile:
                    json.dump(dict_to_write, outfile)

            elif mode == "a":
                # Incase it dosent, we cant read and it wont auto-create
                if not json_path.exists():
                    with open(json_path, "w+") as touchfile:
                        json.dump({}, touchfile)

                # Read and update
                with open(json_path, "r") as infile:
                    old_dict = json.load(infile)

                new_dict = dict(old_dict, **dict_to_write)

                with open(json_path, "w") as outfile:
                    json.dump(new_dict, outfile)

            else:
                return

        # Suppress all outputs and continue
        except:
            pass

    @classmethod
    def __log_env_block(cls):

        if cls._GC_LOG_STATE == "DISABLED":
            return

        env_dict = dict(copy.deepcopy(os.environ))

        # TODO: filter anything from here before saving?
        # TODO: process any vars for easier use later?

        cls.__write_json(env_dict, "initial_environment_state")

    @classmethod
    def __log_sysperf_info(cls):
        if cls._GC_LOG_STATE == "DISABLED":
            return

        log_dict = {}

        # Record some constants (CPU count, freq, disk setup)
        log_dict["CPU_count"] = psutil.cpu_count()
        log_dict["CPU_stats"] = str(psutil.cpu_stats())
        log_dict["CPU_freq"] = str(psutil.cpu_freq())
        cls.__write_json(log_dict, "cpu_info")

        # Collect all output of lscpu
        with open(cls._GC_LOG_PATH.joinpath("lscpu.json"), "w") as outfile:
            command = "lscpu -J"
            subprocess.run(command, stdout=outfile, stderr=outfile, shell=True, text=True)

        # Collect quick disk performance stats (Disk <-> Host) in background
        with open(cls._GC_LOG_PATH.joinpath("fio_results.log"), "w") as outfile:
            command = (
                "fio --name=random-write --ioengine=posixaio --rw=randwrite "
                "--bs=4k --size=1g --numjobs=1 --iodepth=1 --runtime=5 "
                "--time_based --end_fsync=1 --output-format=json+"
            )
            subprocess.run(command, stdout=outfile, stderr=outfile, shell=True, text=True)

        # Clean up files from profiling
        # Subprocess since paperspace env dosent like unlink/remove
        test_file = cls._GC_LOG_PATH.parent.joinpath("random-write.0.0")
        if test_file.exists():
            subprocess.run(f"rm -rf {test_file}", shell=True)

    @classmethod
    def __log_ipuperf_info(cls):
        if cls._GC_LOG_STATE == "DISABLED":
            return

        # Get information for each IPU available
        with open(cls._GC_LOG_PATH.joinpath("ipu_perf.json"), "a") as outfile:
            num_ipus = int(os.getenv("NUM_AVAILABLE_IPU", "0"))

            # Host <-> IPU sync latency
            for i in range(num_ipus):
                subprocess.run(
                    f"gc-hostsynclatencytest -d {i} -j",
                    stdout=outfile,
                    stderr=outfile,
                    shell=True,
                )

            # Host <-> IPU data transfer
            for i in range(num_ipus):
                subprocess.run(
                    f"gc-hosttraffictest -d {i} -j",
                    stdout=outfile,
                    stderr=outfile,
                    shell=True,
                )

            # IPU <-> IPU data transfer
            subprocess.run(
                "gc-iputraffictest --all-links -j",
                stdout=outfile,
                stderr=outfile,
                shell=True,
            )

            vipu_data = {
                "vipu_partition_id": os.getenv("IPUOF_VIPU_API_PARTITION_ID"),
                "hostname": os.getenv("HOSTNAME"),
                "num_ipus": num_ipus,
            }
            try:
                json.dump(vipu_data, outfile)
            # Suppress all outputs and continue
            except:
                pass

    @classmethod
    def __log_notebook_info(cls):
        if cls._GC_LOG_STATE == "DISABLED":
            return

        notebook_metadata = {
            "notebook_path": str(ipynbname.path()),
            "repo_id": os.getenv("PAPERSPACE_NOTEBOOK_REPO_ID"),
            "cluster_id": os.getenv("PAPERSPACE_CLUSTER_ID"),
            "notebook_id": os.getenv("PAPERSPACE_NOTEBOOK_ID"),
            "jupyter_token": os.getenv("JUPYTER_TOKEN"),
            "paperspace_fqdn": os.getenv("PAPERSPACE_FQDN"),
            "paperspace_cluster_id": os.getenv("PAPERSPACE_CLUSTER_ID"),
            "paperspace_metric_workload_id": os.getenv("PAPERSPACE_METRIC_WORKLOAD_ID"),
        }
        cls.__write_json(notebook_metadata, "notebook_info")

        # Query pip packages and versions
        pkgs_dict = {i.key: i.version for i in pkg_resources.working_set}
        cls.__write_json(pkgs_dict, "python_packages")

    @classmethod
    def __log_sysperf_metrics(cls):
        while True:
            if cls._GC_LOG_STATE == "DISABLED":
                return

            system_dict = {
                datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ"): {
                    "cpu_percent": psutil.cpu_percent(),
                    "virtual_memory": psutil.virtual_memory().percent,
                    "swap_memory": psutil.swap_memory().percent,
                    "disk_used": psutil.disk_usage("/").used,
                }
            }

            cls.__write_json(system_dict, "sys_perf", "a")

            time.sleep(cls._FAST_POLLING_SECONDS)

    @classmethod
    def __get_executables(cls):
        cache_dirs = [
            ipynbname.path().parents[1],  # Local
            os.getenv("POPLAR_EXECUTABLE_CACHE_DIR"),  # HF default
            os.getenv("POPTORCH_CACHE_DIR"),  # Possible for non-HF optimum runs
        ]
        popef_files = []

        # Get all .popef files name and size
        for dir_path in cache_dirs:
            if dir_path:
                popef_files.extend(Path(dir_path).glob("*.popef"))

        popef_dict = {}
        # Analyse the popef file using gc CLI tool
        for file in popef_files:
            proc = subprocess.run(
                f"popef_dump --all {file}",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=True,
                text=True,
            )

            popef_dict[str(file)] = proc.stdout

        cls.__write_json(popef_dict, "popef_files")

    @classmethod
    def __get_weights(cls):
        cache_dirs = [
            ipynbname.path().parents[1],  # Local
            os.getenv("CHECKPOINT_DIR"),  # HF default
            os.getenv("HUGGINGFACE_HUB_CACHE"),  # Another possible HF path?
            os.getenv("TRANSFORMERS_CACHE"),  # Possible checkpoints here
        ]

        # Search for all weight files and poll size/name
        weights_extensions = ["onnx", "pt", "pb"]
        weight_files = []
        for dir_path in cache_dirs:
            if dir_path:
                for ext in weights_extensions:
                    weight_files.extend(Path(dir_path).glob(f"**/*.{ext}"))

        weight_dict = {}
        for file in weight_files:
            weight_dict[str(file)] = file.stat().st_size

        cls.__write_json(weight_dict, "weight_files")

    @classmethod
    def __get_datasets(cls):
        dataset_dirs = [
            ipynbname.path().parents[1],  # Local
            os.getenv("HF_DATASETS_CACHE"),  # HF default
            os.getenv("PUBLIC_DATASET_DIR"),  # Our default
            os.getenv("DATASET_DIR"),  # /tmp/ location
        ]

        # Get all possible dataset dirs
        datasets = []
        for data_path in dataset_dirs:
            datasets.extend(list(Path(data_path).iterdir()))

        # Find sizes
        dataset_sizes = {}
        for folder in datasets:
            proc = subprocess.run(
                ["du", "-sh", str(folder)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            dataset_sizes[str(folder)] = str(proc.stdout).split("\t")[0]

        cls.__write_json(dataset_sizes, "datasets")

    @classmethod
    def __log_file_metrics(cls):
        while True:
            if cls._GC_LOG_STATE == "DISABLED":
                return

            # Get possible .popef files
            cls.__get_executables()

            # Get possible weights and checkpoints files
            cls.__get_weights()

            # Get all datasets and sizes available
            cls.__get_datasets()

            time.sleep(cls._SLOW_POLLING_SECONDS)

    @classmethod
    def __log_notebook_progression(cls):
        """Track cell exeuction order via timestamps

        Note: We use a custom IPython extension to track events, and use it to
        run some lines before any cell is executed. To avoid any noticeable
        delay, we keep this as light as possible, just recording the timestamp
        and cell input code.

        We write this to a cache file in .ipython/extensions/ and then append
        it to our main storage in this loop, flushing the cache afterwards.
        """

        while True:
            if cls._GC_LOG_STATE == "DISABLED":
                return

            # Load cache files written by CellTracker extension
            cache_path = Path("/root/.ipython/extensions/cell_logs/").resolve()
            cache_files = cache_path.glob("**/*.txt")

            # Read and combine all cell execution logs into one
            cell_execution_dict = {}
            for file in cache_files:
                with open(file, "r") as f:
                    code = f.read()

                cell_execution_dict[file.stem] = code

            # Append to data storage Json in logging dir
            cls.__write_json(cell_execution_dict, "cell_logs", "a")

            # Delete all cached files
            # Subprocess since paperspace env dosent like unlink/remove
            for file in cache_files:
                subprocess.run(f"rm -rf {file}", shell=True)

            time.sleep(cls._FAST_POLLING_SECONDS)

    @classmethod
    def __log_errors(cls):
        """Log all errors and the code that produced them.

        Note: We use a custom IPython extension to track events, and use it to
        run some lines before any cell is executed. To avoid any noticeable
        delay, we keep this as light as possible, just recording the timestamp,
        cell input code and error.

        We write this to a cache file in .ipython/extensions/ and then append
        it to our main storage in this loop, flushing the cache afterwards.
        """

        while True:
            if cls._GC_LOG_STATE == "DISABLED":
                return

            # Load cache files written by CellTracker extension
            cache_path = Path("/root/.ipython/extensions/cell_logs/errors").resolve()
            cache_files = cache_path.glob("**/*.json")

            # Read and combine all cell execution logs into one
            error_dict = {}
            for file in cache_files:
                with open(file, "r") as f:
                    error = json.load(f)

                error_dict[file.stem] = error

            # Append to data storage Json in logging dir
            cls.__write_json(error_dict, "error_logs", "a")

            # Delete all cached files
            # Subprocess since paperspace env dosent like unlink/remove
            for file in cache_files:
                subprocess.run(f"rm -rf {file}", shell=True)

            time.sleep(cls._FAST_POLLING_SECONDS)

    @classmethod
    def __log_compile_times(cls):
        """Capture compile time from noteboook.py

        Note: Because of how general this task is, it seems the best we can do
        for now is capture all output that mentions 'compilation' etc. and sift
        through the outputs later.

        If we can get more specificity on how compilation happens, what we can
        expect etc. (HF only, model.compile() explicit calls etc.) then we can
        clean this up a lot and be more particular about what we collect.
        """

        while True:
            if cls._GC_LOG_STATE == "DISABLED":
                return

            compilation_statements = {}

            with open(ipynbname.path()) as notebook:
                raw_notebook = nbformat.read(notebook, nbformat.NO_CONVERT)

            # Get all code cells, search for compile time
            code_cell_outputs = [cell["outputs"] for cell in raw_notebook["cells"] if cell["cell_type"] == "code"]

            for output in code_cell_outputs:
                # Some cells have a seperate 'data' outputs. We need 'text' output
                if len(output) > 1:
                    output = output[1]

                if output:
                    try:
                        text = output[0].get("text")

                        # Assuming HF optimum pipeline output
                        # Check NoneType first else substring search throws
                        if text is not None and "Graph compilation: 100%" in text:
                            compilation_statements[datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")] = text

                    # Suppress all outputs and continue
                    except:
                        pass

            if compilation_statements:
                cls.__write_json(compilation_statements, "compile_statments", "a")

            time.sleep(cls._SLOW_POLLING_SECONDS)

    @classmethod
    def __log_session_stats(cls):
        """Record how long a user is in this session for and when they fail."""
        timings_dict = {}

        while True:
            if cls._GC_LOG_STATE == "DISABLED":
                return

            timings_dict["session_time"] = str(
                (datetime.now() - datetime.strptime(cls._CREATION_TIME, "%Y-%m-%dT%H:%M:%S.%fZ")).total_seconds()
            )
            cls.__write_json(timings_dict, "session_timings")

            # TODO: Time until first error
            # TODO: Cell input/output/index/error contents

            time.sleep(cls._FAST_POLLING_SECONDS)

    @classmethod
    def __upload_files(cls):
        while True:
            if cls._GC_LOG_STATE == "DISABLED":
                return

            # Compose the AWSCLI upload command - Unique hash used to identify this user for this session ONLY
            cmd = [
                "aws",
                "s3",
                "cp",
                "--recursive",
                f"{cls._GC_LOG_PATH}",
                f"s3://{cls._BUCKET_NAME}/{cls._UNIQUE_HASH}",
            ]

            subprocess.run(
                cmd,
                env=os.environ,
            )

            time.sleep(cls._FAST_POLLING_SECONDS)

    @classmethod
    def start_logging(cls):
        if cls._GC_LOG_STATE == "ENABLED":
            print("GCLogger is already logging")
            return

        cls._GC_LOG_STATE = "ENABLED"

        background_functions = [
            # One-time collection
            # (constant, static information on system/env)
            cls.__log_env_block,
            cls.__log_sysperf_info,
            cls.__log_ipuperf_info,
            cls.__log_notebook_info,
            # Frequent polling every cls._FAST_POLLING_SECONDS
            # (changing values, metrics, measurements on system/env)
            cls.__log_sysperf_metrics,
            cls.__log_notebook_progression,
            cls.__log_errors,
            cls.__log_session_stats,
            cls.__upload_files,
            # Infrequent polling every cls._SLOW_POLLING_SECONDS
            # (names, file sizes, packages etc.)
            cls.__log_file_metrics,
            cls.__log_compile_times,
        ]

        # Start multiprocess procs for all functions
        cls.proc_list = [mp.Process(target=func) for func in background_functions]

        for proc in cls.proc_list:
            proc.daemon = True
            proc.start()

    @classmethod
    def stop_logging(cls):
        if cls._GC_LOG_STATE == "DISABLED":
            print("GCLogger has already stopped logging")
            return

        if cls._GC_LOG_STATE is None:
            print("GCLogger has not logged anything yet")
            return

        cls._GC_LOG_STATE = "DISABLED"

        # Kill logging processes
        for proc in cls.proc_list:
            proc.terminate()
            proc.join()

        print("GCLogger has stopped logging")


GCLogger()
