# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import tempfile
import os
import pathlib
import pytest
import argparse
import yaml
import subprocess
from examples_utils.benchmarks import environment_utils
from examples_utils.testing import test_commands

cwd = pathlib.Path.cwd()


@pytest.fixture(autouse=True)
def teardown():
    yield
    os.chdir(cwd)


@pytest.fixture()
def mocked_args():
    """Something which looks like the arguments to the benchmarks"""
    return argparse.Namespace(
        allow_wandb=False,
        submit_on_slurm=False,
        upload_checkpoints=[],
    )


def test_git_commit_hash_in_repo():
    os.chdir(pathlib.Path(__file__).parent)
    hash = environment_utils.get_git_commit_hash()
    assert is_sha_1(hash)


def test_git_commit_hash_out_of_repo():
    os.chdir(tempfile.gettempdir())
    not_a_hash = environment_utils.get_git_commit_hash()
    assert "Not a git repo" in not_a_hash


def is_sha_1(hash_input: str) -> bool:
    # length check
    if len(hash_input) != 40:
        return False

    # can convert to hex value
    try:
        int(hash_input, 16)
    except:
        return False
    return True


def test_vipu_parser():
    """Checks that what vipu server returns is pingable"""
    out = environment_utils.parse_vipu_server()
    assert out is not None, "vipu failed if you are on a machine with IPU this is a problem"

    pingable = test_commands.run_command_fail_explicitly(["ping", "-c", "1", "-w", "10", out])
    assert "Error" not in pingable, f"{out} is not a valid host and could not be pinged"


class TestPoprunEnvFallback:
    @pytest.fixture
    def safe_var(self, monkeypatch):
        """Sets up the environment without the environment variable
        to trigger the fallback"""
        safe_var = "VIPU_CLI_API_HOST"
        assert safe_var in environment_utils.POPRUN_VARS
        assert safe_var in environment_utils.FALLBACK_VAR_FUNCTIONS

        monkeypatch.delenv("VIPU_CLI_API_HOST", raising=False)
        monkeypatch.delenv("IPUOF_VIPU_API_HOST", raising=False)
        return safe_var

    def test_poprun_env_fallback_no_action(self, mocked_args, safe_var: str):
        """If the command does not contain the safe environment variable nothing happens"""
        command_without_safe_var = f"poprun NOT_A_SAFE_VAR python file.py"
        assert os.getenv(safe_var) is None
        environment_utils.check_env(mocked_args, "name", command_without_safe_var)
        assert os.getenv(safe_var) is None

    def test_poprun_env_fallback(self, mocked_args, safe_var: str):
        """If the command does contain the safe environment variable it gets set by fallback"""
        command_with_safe_var = f"poprun ${safe_var} python file.py"
        assert os.getenv(safe_var) is None
        environment_utils.check_env(mocked_args, "name", command_with_safe_var)
        assert os.getenv(safe_var) is not None


@pytest.fixture(scope="class")
def setup_test_timeout(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("test-timeout")

    # create python file to be run from the yaml
    python_filename = "sleep.py"
    py_filepath = tmp_dir / python_filename
    with open(py_filepath, "w") as f:
        f.write("import time; time.sleep(5); print('Done')")

    # create yaml file containing the variant configs
    yaml_filepath = tmp_dir / "timeout_config.yaml"
    yaml_config = {
        "timeout_variant": {"timeout": 2, "generated": True, "cmd": f"python3 {tmp_dir / python_filename}"},
        "no_timeout_variant": {"generated": True, "cmd": f"python3 {tmp_dir / python_filename}"},
    }
    with open(yaml_filepath, "w") as f:
        yaml.dump(yaml_config, f, default_flow_style=False)

    return yaml_filepath


@pytest.mark.usefixtures("setup_test_timeout")
# test that the subprocess timeouts work, when set at the app and global levels
class TestTimeout:
    # global timeout 3s, variant timeout 2s -> should timeout in 2s
    def test_variant_timeout_smaller(self, setup_test_timeout):
        yaml_config = setup_test_timeout
        cmd = f"python3 -m examples_utils benchmark --spec {yaml_config} --benchmark timeout_variant --timeout 3"
        result = subprocess.run(cmd.split(), capture_output=True, text=True)
        assert "Timeout (2)" in result.stderr

    # global timeout 1s, variant timeout 2s -> should timeout in 1s
    def test_variant_timeout_larger(self, setup_test_timeout):
        yaml_config = setup_test_timeout
        cmd = f"python3 -m examples_utils benchmark --spec {yaml_config} --benchmark timeout_variant --timeout 1"
        result = subprocess.run(cmd.split(), capture_output=True, text=True)
        assert "Timeout (1)" in result.stderr

    # no global timeout, variant timeout 2s -> should timeout in 2s
    def test_only_variant_timeout(self, setup_test_timeout):
        yaml_config = setup_test_timeout
        cmd = f"python3 -m examples_utils benchmark --spec {yaml_config} --benchmark timeout_variant"
        result = subprocess.run(cmd.split(), capture_output=True, text=True)
        assert "Timeout (2)" in result.stderr

    # global timeout 2s, no variant timeout -> should timeout in 2s
    def test_only_global_timeout(self, setup_test_timeout):
        yaml_config = setup_test_timeout
        cmd = f"python3 -m examples_utils benchmark --spec {yaml_config} --benchmark no_timeout_variant --timeout 2"
        result = subprocess.run(cmd.split(), capture_output=True, text=True)
        assert "Timeout (2)" in result.stderr
