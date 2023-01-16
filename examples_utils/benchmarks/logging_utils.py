# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
from typing import Sequence
import argparse
import csv
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from time import time

# Attempt to import wandb silently, if app being benchmarked has required it
WANDB_AVAILABLE = True
try:
    import wandb
    # avoid namespace packages ref: https://peps.python.org/pep-0420/#specification
    getattr(wandb, "init")
except:
    WANDB_AVAILABLE = False

# Get the module logger
logger = logging.getLogger(__name__)


def configure_logger(args: argparse.Namespace):
    """Setup the benchmarks runner logger

    Args:
        args (argparse.ArgumentParser): Argument parser used for benchmarking

    """

    # Setup dir
    if not args.log_dir:
        time_str = datetime.fromtimestamp(time()).strftime("%Y-%m-%d-%H.%M.%S.%f")
        args.log_dir = Path(os.getcwd(), f"log_{time_str}").resolve()
    else:
        args.log_dir = Path(args.log_dir).resolve()

    if not args.log_dir.exists():
        args.log_dir.mkdir(parents=True)

    # Setup logger
    logger = logging.getLogger()
    formatter = logging.Formatter("[%(levelname)s] %(asctime)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(args.log_dir / "console.log")
    file_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    logger.setLevel(args.logging)

    logger.info(f"Logging directory: '{args.log_dir}'")


def print_benchmark_summary(results: dict):
    """Print a summary of all benchmarks run.

    Args:
        results (dict): Benchmark results dict to create summary from

    """

    # Print PASS/FAIL statements
    summary = []
    passed, failed = 0, 0
    for benchmark, variants in results.items():
        for variant in variants:
            if variant.get("exitcode") == 0:
                summary.append(f"PASSED {benchmark}::" f"{variant['benchmark_name']}")
                passed += 1
            else:
                summary.append(f"FAILED {benchmark}::" f"{variant['benchmark_name']}")
                failed += 1

    if summary:
        print("=================== short test summary info ====================\n")
        print("\n".join(summary) + "\n")
        print(f"================ {failed} failed, {passed} passed ===============")


def get_latest_checkpoint_path(checkpoint_root_dir: Path, variant_cmd: str) -> Path:
    """Get the path to the latest available checkpoint for a model.

    Args:
        checkpoint_root_dir (Path): The path to the benchmarking dir
        variant_cmd (str): The command used for this model run (benchmark)

    Returns:
        latest_checkpoint_path (Path): The directory containing all checkpoints
            as specified in the benchmarks.yml (or 'None' if this is not found.)

    """

    cmd_args = variant_cmd.split(" --")

    # Look at each arg to see if it could be a checkpoint path
    checkpoint_dir = None
    for arg in cmd_args:
        if "checkpoint-output-dir" in arg:
            checkpoint_dir = arg.replace("=", " ").split(" ")[1]
            checkpoint_dir = checkpoint_dir.replace("\"", "").replace("'", "")
            break

    latest_checkpoint_path = None
    if checkpoint_dir is not None:
        # Resolve relative to the benchmarks.yml path
        checkpoint_dir = checkpoint_root_dir.joinpath(checkpoint_dir).resolve()

        # Find all directories in checkpoint root dir
        list_of_dirs = [x for x in checkpoint_dir.glob('**/*') if x.is_dir()]

        # Sort list of files based on last modification time and take latest
        time_sorted_dirs = sorted(list_of_dirs, key=os.path.getmtime, reverse=True)

        try:
            latest_checkpoint_path = time_sorted_dirs[0]
        except:
            logger.warn(f"Checkpoint file(s) in {checkpoint_dir} could not be found. Skipping uploading")

    logger.info(f"Checkpoints to be uploaded: {latest_checkpoint_path}")

    return latest_checkpoint_path


def get_wandb_link(stderr: str) -> str:
    """Get a wandb link from stderr if it exists.

    Args:
        stderr (str): the stderr output from the benchmark

    """

    wandb_link = None
    for line in stderr.split("\n"):
        if "https://wandb.sourcevertex.net" in line and "/runs/" in line:
            wandb_link = "https:/" + line.split("https:/")[1]
            wandb_link = wandb_link.replace("\n", "")

    if wandb_link:
        logger.info(f"Wandb link found from stdout/stderr: {wandb_link}")

    return wandb_link


def save_results(log_dir: str, additional_metrics: bool, results: dict, extra_csv_metrics: Sequence[str] = tuple()):
    """Save benchmark results into files.

    Args:
        log_dir (str): The path to the logging directory
        results (dict): The results for this benchmark

    """
    # Save results dict as JSON
    json_filepath = Path(log_dir, "benchmark_results.json")
    with open(json_filepath, "w") as json_file:
        json.dump(results, json_file, sort_keys=True, indent=2)
    logger.info(f"Results saved to {str(json_filepath)}")

    # Parse summary into CSV and save in logs directory
    csv_metrics = ["throughput", "latency", "total_compiling_time"]
    if additional_metrics:
        csv_metrics.extend(["test_duration", "loss", "result", "cmd", "env", "git_commit_hash"])
    csv_metrics.extend(extra_csv_metrics)

    csv_filepath = Path(log_dir, "benchmark_results.csv")
    with open(csv_filepath, "w") as csv_file:
        writer = csv.writer(csv_file, quoting=csv.QUOTE_ALL)
        # Use a fixed set of headers, any more detail belongs in the JSON file
        writer.writerow(["benchmark name", "Variant name"] + csv_metrics)

        # Write a row for each variant
        for benchmark, result in results.items():
            for r in result:
                csv_row = [benchmark, r["variant_name"]]

                # Find all the metrics we have available from the list defined
                for metric in csv_metrics:
                    value = list(r["results"].get(metric, {0: None}).values())[0]
                    csv_row.append(value)

                writer.writerow(csv_row)
    logger.info(f"Results saved to {str(csv_filepath)}")


def upload_checkpoints(upload_targets: list, checkpoint_path: Path, benchmark_path: str, checkpoint_dir_depth: int,
                       run_name: str, stderr: str):
    """Upload checkpoints from model run to

    Args:
        upload_targets (list): Which targets/locations to upload checkpoints to
        checkpoint_path (Path): Path to the checkpoint to upload
        benchmark_path (str): Path to the benchmark dir
        run_name (str): Name for this benchmarking run
        stderr (str): Stderr output from this benchmarking run

    """

    # Get confirmation user wants to upload checkpoint (post results), else exit
    upload_confirmed = input("Upload checkpoints? (y/n): ")
    while upload_confirmed not in {"y", "n"}:
        upload_confirmed = input("Please enter either y (yes) or n (no): ")

    if upload_confirmed != "y":
        logger.warn(f"Checkpoint uploading was refused by user input, skipping "
                    f"uploading checkpoints at {checkpoint_path}")
        return

    checkpoint_path = str(checkpoint_path)

    if "wandb" in upload_targets:
        try:
            # Extract info from wandb link
            wandb_link = get_wandb_link(stderr)
            link_parts = wandb_link.split("/")

            # Prevent wandb from printing to terminal unecessarily
            os.environ["WANDB_SILENT"] = "true"

            run = wandb.init(project=link_parts[-3], id=link_parts[-1], resume="allow")

            artifact = wandb.Artifact(name=run_name + "-checkpoint", type="model")
            artifact.add_dir(checkpoint_path)

            run.log_artifact(artifact)

            # Revert to normal
            os.environ["WANDB_SILENT"] = "false"

            logger.info(f"Checkpoint at {checkpoint_path} successfully uploaded to wandb.")
        except Exception as e:
            logger.warn(f"Failed to upload checkpoint at {checkpoint_path} to wandb.")
            logger.warn(e)

    if "s3" in upload_targets:
        # Create the upload path (target within the bucket)
        upload_path = "/".join(benchmark_path.replace("/benchmarks.yml", "").split("/")[-checkpoint_dir_depth:]) + "/"

        # Compose the AWSCLI upload command
        cmd = ["aws", "s3", "cp", f"{checkpoint_path}", f"s3://gc-public-examples/{upload_path}", "--recursive"]

        try:
            proc = subprocess.run(
                cmd,
                env=os.environ,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout = proc.stdout.decode()
            stderr = proc.stderr.decode()

            if proc.returncode == 0:
                logger.info(f"Checkpoint at {checkpoint_path} successfully uploaded to s3.")

        except Exception as e:
            logger.warn(f"Failed to upload checkpoint at {checkpoint_path} to s3.")
            logger.warn(e)

        if "AccessDenied" in stdout + stderr:
            msg = ("It appears that awscli is denied access when uploading. "
                   "If you have MFA (Multi-factor authentication) enabled for "
                   "your AWS account, then it will require setting up prior "
                   "to attempting any uploads. Please repeat this benchmarking "
                   "run after configuring aws-mfa "
                   "(https://github.com/broamski/aws-mfa) in your environment: "
                   "\n1 - `pip3 install aws-mfa`"
                   "\n2 - In your aws credentials, append '-long-term' to the "
                   "profile you want to use (e.g. [default-long-term]) and add "
                   "a new field called aws_mfa_device, the value of which you "
                   "can get from your AWS account > security credentials (e.g "
                   "aws_mfa_device "
                   "= arn:aws:iam::<account number>:mfa/<username>) "
                   "\n3 - `aws-mfa` "
                   "\n4 - Enter the MFA code from your "
                   "authenticator app you use when logging into AWS in the "
                   "web browser etc.")
            logger.warn(msg)


def upload_compile_time(wandb_link: str, results: dict):
    """Upload compile time results to a wandb link

    Args:
        wandb_link (str): The link to the W&B run for this benchmark
        results (dict): The results for this benchmark

    """

    # Re-initialise link to allow uploading again
    link_parts = wandb_link.split("/")

    # Prevent wandb from printing to terminal unecessarily
    os.environ["WANDB_SILENT"] = "true"

    run = wandb.init(project=link_parts[-3], id=link_parts[-1], resume="allow")
    run.log({"Total compile time": results["total_compiling_time"]["mean"]})

    # Revert to normal
    os.environ["WANDB_SILENT"] = "false"
