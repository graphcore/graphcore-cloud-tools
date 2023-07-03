# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

from pathlib import Path
import sys
from graphcore_cloud_tools.testing import test_commands

import pytest

ROOT_REPOSITORY = Path(__file__).resolve().parents[1]


@pytest.fixture
def virtual_env(tmp_path: Path) -> str:
    venv_folder = tmp_path / "venv"
    test_commands.run_command_fail_explicitly(["virtualenv", "-p", f"{sys.executable}", f"{venv_folder}"], ".")
    script = tmp_path / "run-in-venv"
    script.write_text(
        f"""#!/bin/bash
source {venv_folder}/bin/activate
python $@
    """,
        encoding="ascii",
    )
    test_commands.run_command_fail_explicitly(["chmod", "+x", str(script)])
    return str(script)


class TestJupyterRequirements:
    def run_sample_notebook(self, tmp_path: Path, virtual_env: Path):
        yaml_file = tmp_path / "sample.yaml"
        yaml_file.write_text(
            f"""
notebook_benchmark:
    generated: true
    notebook:
        file: {ROOT_REPOSITORY}/tests/test_files/sample.ipynb
        """
        )
        print(test_commands.run_command_fail_explicitly([virtual_env, "-m", "pip", "list"]))
        return test_commands.run_command_fail_explicitly(
            [virtual_env, "-m", "graphcore_cloud_tools", "benchmark", "--spec", str(yaml_file)],
            ".",
        )

    def test_notebook_works(self, tmp_path, virtual_env):
        """Install the package with `pip install graphcore-cloud-tools[jupyter]`"""
        test_commands.run_command_fail_explicitly(
            [virtual_env, "-m", "pip", "install", f"{ROOT_REPOSITORY}[jupyter]"], "."
        )
        out = self.run_sample_notebook(tmp_path, virtual_env)
        assert "PASSED notebook_benchmark::notebook_benchmark" in out

    def test_notebook_fails(self, tmp_path, virtual_env):
        """The normal requirements should not install what is required to run a notebook
        it should fail."""
        test_commands.run_command_fail_explicitly([virtual_env, "-m", "pip", "install", f"{ROOT_REPOSITORY}"], ".")
        with pytest.raises(Exception, match=r"needs to have been installed with the \[jupyter\]"):
            out = self.run_sample_notebook(tmp_path, virtual_env)


def test_normal_requirements_python_file(tmp_path, virtual_env):
    test_commands.run_command_fail_explicitly([virtual_env, "-m", "pip", "install", f"{ROOT_REPOSITORY}"], ".")
    python_script = tmp_path / "script.py"
    python_script.write_text("print('Hello world!')")
    yaml_file = tmp_path / "sample.yaml"
    yaml_file.write_text(
        f"""
script_benchmark:
    generated: true
    cmd: python3 {python_script}
    """
    )
    print(test_commands.run_command_fail_explicitly([virtual_env, "-m", "pip", "list"]))
    out = test_commands.run_command_fail_explicitly(
        [virtual_env, "-m", "graphcore_cloud_tools", "benchmark", "--gc-monitor", "--spec", str(yaml_file)],
        ".",
    )
    assert "PASSED script_benchmark::script_benchmark" in out
