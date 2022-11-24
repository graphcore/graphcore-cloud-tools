# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
from pathlib import Path
import pytest
import logging
import sys
import re
import json

from examples_utils.benchmarks import custom_metrics
from examples_utils.testing import test_commands

EXPECTED_METRIC_HOOK_NAME = "log_lengths"

CUSTOM_METRIC_FILE = f"""
from examples_utils import register_custom_metric

# Arbitrary metric function it must have a similar signature
def log_lengths(stdout: str, stderr: str, exitcode: int):
    print(f"stdout : {{stdout}}")
    print(f"stderr : {{stderr}}")
    return dict(stdout=len(stdout.splitlines()), stderr=len(stderr.splitlines()))


# Call this function to declare the metric to examples utils
# it will appear in the final results directory under the name
# passed as a first argument.
register_custom_metric("{EXPECTED_METRIC_HOOK_NAME}", log_lengths)
"""


@pytest.fixture
def metrics_file(tmp_path: Path):
    python_file = tmp_path / "my_metric.py"
    python_file.write_text(CUSTOM_METRIC_FILE)
    return python_file


@pytest.fixture(autouse=True)
def clean_hooks():
    """Makes sure that no hooks are registered before we start"""
    previous = {**custom_metrics.REGISTERED_HOOKS}
    custom_metrics.REGISTERED_HOOKS.clear()
    yield
    custom_metrics.REGISTERED_HOOKS.clear()
    custom_metrics.REGISTERED_HOOKS.update(previous)


def test_metrics_file_import_and_registration(caplog, metrics_file: Path):
    caplog.set_level(logging.INFO)
    custom_metrics.import_metrics_hooks_files([metrics_file])

    print(caplog.text)
    assert re.search(f"Imported.*from.*{metrics_file}", caplog.text)
    assert re.search(f"Registered metric hook:.*{EXPECTED_METRIC_HOOK_NAME}", caplog.text)
    assert EXPECTED_METRIC_HOOK_NAME in custom_metrics.REGISTERED_HOOKS


def test_metrics_execution(metrics_file: Path):
    """Checks that metrics can be executed with the process_registered_metrics"""
    metric_name = EXPECTED_METRIC_HOOK_NAME
    results = {}
    stdout = "\n".join("12345678")
    stderr = "\n".join("1234567890")
    exit_code = 1
    results = custom_metrics.process_registered_metrics(results, stdout, stderr, exit_code)
    assert not results
    custom_metrics.import_metrics_hooks_files([metrics_file])
    results = custom_metrics.process_registered_metrics(results, stdout, stderr, exit_code)
    assert metric_name in results
    metric = results[metric_name]
    assert "stdout" in metric and "stderr" in metric
    assert metric["stdout"] == 8 and metric["stderr"] == 10


def test_end_to_end_custom_metric(tmp_path: Path, metrics_file: Path):
    log_dir = tmp_path / "log-dir"
    python_script = tmp_path / "script.py"
    python_script.write_text(r"print('Hello\n big \nworld!')")
    yaml_file = tmp_path / "sample.yaml"
    yaml_file.write_text(f"""
test_custom_metric:
    generated: true
    cmd: python3 {python_script}
    """)
    out = test_commands.run_command_fail_explicitly(
        [
            sys.executable, "-m", "examples_utils", "benchmark", "--spec",
            str(yaml_file), "--custom-metrics-files",
            str(metrics_file), "--log-dir",
            str(log_dir)
        ],
        ".",
    )
    assert "PASSED test_custom_metric::test_custom_metric" in out
    result_files = list(log_dir.rglob("benchmark_results.json"))
    assert result_files and len(result_files) == 1, f"benchmark results could not be found in {log_dir}"
    with open(result_files[0]) as f:
        results = json.load(f)
        print(results)

    assert "test_custom_metric" in results
    assert "results" in results["test_custom_metric"][0]
    # Check that the custom metric was calculated
    assert EXPECTED_METRIC_HOOK_NAME in results["test_custom_metric"][0]["results"]
    metric = results["test_custom_metric"][0]["results"][EXPECTED_METRIC_HOOK_NAME]
    print(out)
    assert metric["stdout"] == 3 and metric["stderr"] == 0
