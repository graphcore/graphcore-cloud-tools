# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import logging
from typing import NamedTuple, Optional, Union, List, Dict
import re
import os
import argparse
import subprocess
import sys
from pathlib import Path
from io import TextIOWrapper
from contextlib import contextmanager

from .run_benchmarks import run_and_monitor_progress, BenchmarkDict, parse_benchmark_specs, run_benchmarks_from_spec, preprocess_args, benchmarks_parser
from .environment_utils import enter_benchmark_dir

try:
    import git
except (ImportError, ModuleNotFoundError) as error:
    from . import _incorrect_requirement_variant_error
    raise _incorrect_requirement_variant_error from error

logger = logging.getLogger(__name__)


class Repository(NamedTuple):
    origin: str
    ref: Optional[str] = None

    def prepare(self, cloning_directory: Path = Path(".").resolve() / "clones") -> Path:
        """Clones and checkouts the correct ref of the origin"""
        # Treat the origin as a folder, if it doesn't exist it's a URL to clone
        repo_folder = Path(self.origin)
        if not repo_folder.exists():
            repo_folder = cloning_directory / self._sanitised_url()
            cloning_directory.mkdir(exist_ok=True, parents=True)

        if not repo_folder.exists():
            logger.info(f"Cloning repository {self.origin} to {repo_folder}")
            repo = git.Repo.clone_from(self.origin, to_path=repo_folder)
        else:
            try:
                repo = git.Repo(repo_folder)
            except git.InvalidGitRepositoryError as error:
                raise git.InvalidGitRepositoryError(
                    f"{repo_folder} is not a git repository. If this folder"
                    "was cloned make sure the clone was successful, or if it is meant to be"
                    "a local repository make sure to run `git init` in the folder before "
                    "calling `prepare` on that path.") from error
        # if a ref is specified, try to fetch it then try to check it out
        if repo.remotes and self.ref:
            try:
                repo.git.fetch()
            except git.GitCommandError as error:
                logger.warn(f"Failed to fetch the repository {self.origin} in folder"
                            f" {repo_folder}. Trying to fetch raised: {error}")
        if self.ref:
            repo.git.checkout(self.ref)
            if not repo.head.is_detached:
                repo.git.pull()

        return repo_folder

    def _sanitised_url(self) -> str:
        return "".join([c if re.match("[a-zA-Z0-9]", c) else "-" for c in str(self.origin)])


def install_patched_requirements(requirements_file: Union[str, Path], listener: TextIOWrapper):
    """Removes any 'examples-utils' requirements from a a requirements
    file before installing it. It returns the original unpatched requirements
    in case they are needed later."""

    requirements_file = Path(requirements_file)
    logger.info(f"Install python requirements")
    if not requirements_file.exists():
        err = (f"Invalid python requirements where specified at {requirements_file.resolve().absolute()} in folder")
        logger.error(err)
        raise FileNotFoundError(err)
    # Strip examples-utils requirement as it can break the installation
    original_requirements = requirements_file.read_text()
    requirements_file.write_text("\n".join(l for l in original_requirements.splitlines() if "examples-utils" not in l))
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(requirements_file)]
    out, err, exit_code = run_and_monitor_progress(cmd, listener)
    if exit_code:
        err = (f"Installation of pip packages in file {requirements_file} failed with stderr: {err}.")
        logger.error(err)
        raise subprocess.CalledProcessError(exit_code, cmd, out, err)
    return original_requirements


def install_apt_packages(requirements_file_or_list: Union[str, Path, List[str]], listener: TextIOWrapper):
    """Installs system packages with apt."""
    logger.info(f"Installing apt requirements")
    if not isinstance(requirements_file_or_list, list):
        requirements_file = Path(requirements_file_or_list)
        if not requirements_file.exists():
            err = (f"Invalid apt requirements where specified at {requirements_file.resolve().absolute()} in folder")
            logger.error(err)
            raise FileNotFoundError(err)
        requirements_list: List[str] = requirements_file.read_text().splitlines()
    else:
        requirements_list = requirements_file_or_list
    logger.debug(f"  Collected the following requirements: " + " ".join(requirements_list))
    for cmd in [
        ["apt", "update", "-y"],
        ["apt", "install", "-y", *requirements_list],
    ]:
        out, err, exit_code = run_and_monitor_progress(cmd, listener)
        if exit_code:
            err = (f"System packages installation failed with stderr: {err}.")
            logger.error(err)
            raise subprocess.CalledProcessError(exit_code, cmd, out, err)

    return requirements_list


@contextmanager
def in_benchmark_dir(benchmark_dict):
    previous_work_dir = enter_benchmark_dir(benchmark_dict)
    try:
        yield previous_work_dir
    finally:
        logger.debug(f"Returning to {previous_work_dir}")
        os.chdir(previous_work_dir)


def prepare_benchmark_environment(benchmark_dict: BenchmarkDict, listener: TextIOWrapper):
    changes_to_revert = {}
    if benchmark_dict.get("repository"):
        repo_in = benchmark_dict.get("repository", {})
        repo = Repository(**repo_in)
        benchmark_dict["reference_directory"] = repo.prepare()

    with in_benchmark_dir(benchmark_dict):
        required_apt_packages: Optional[str] = benchmark_dict.get("required_apt_packages")
        if required_apt_packages:
            install_apt_packages(required_apt_packages, listener)
        requirements_file: Optional[str] = benchmark_dict.get("requirements_file")
        original_requirements = ""
        if requirements_file:
            original_requirements = install_patched_requirements(requirements_file, listener)
        changes_to_revert["original_requirements"] = original_requirements

    return changes_to_revert


def cleanup_benchmark_environments(benchmark_dict: BenchmarkDict, changes_to_revert: Optional[Dict]):
    if changes_to_revert is None:
        return
    # Undo the patch to the requirements files
    with in_benchmark_dir(benchmark_dict):
        requirements_file: Optional[str] = benchmark_dict.get("requirements_file")
        if requirements_file:
            Path(requirements_file).write_text(changes_to_revert["original_requirements"])


def assess_platform(args: argparse.Namespace):
    # Parse files
    args = preprocess_args(args)
    args.spec = [str(Path(file).resolve()) for file in args.spec]
    benchmarks = parse_benchmark_specs(args.spec)

    # extract and modify benchmarks
    with open(Path(args.log_dir) / "environment_setup.log", "w") as log_file:
        revertible_changes: Dict[str, Dict] = {}
        try:
            logger.info("-" * 40)
            for name, benchmark in benchmarks.items():
                logger.info(f"Preparing environment for '{name}'")
                revertible_changes[name] = prepare_benchmark_environment(benchmark, log_file)

            _ = run_benchmarks_from_spec(benchmarks, args)
        finally:
            # Make sure that clean up happens even on failures
            for name, benchmark in benchmarks.items():
                logger.info(f"Cleaning-up environment for '{name}'")
                cleanup_benchmark_environments(benchmark, revertible_changes.get(name))


def platform_parser(parser):
    return benchmarks_parser(parser)
