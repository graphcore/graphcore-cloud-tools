# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import os
import nbformat
from nbconvert import Exporter
from nbconvert.exporters.exporter import ResourcesDict
from nbconvert.preprocessors import CellExecutionError, ExecutePreprocessor
from nbformat import NotebookNode
from typing import Union, List
import subprocess
import warnings

DEFAULT_PROCESS_TIMEOUT_SECONDS = 40 * 60

DEFAULT_TIMEOUT = 600


def run_notebook(notebook_filename: str, working_directory: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Run a notebook and return all its outputs to stdstream together

    Args:
        notebook_filename: The path to the notebook file that needs testing
        working_directory: The working directory from which the notebook is
            to be run.
    """

    with open(notebook_filename) as f:
        nb = nbformat.read(f, as_version=4)
    ep = ExecutePreprocessor(timeout=timeout, kernel_name="python3")
    exporter = OutputExporter()
    try:
        ep.preprocess(nb, {"metadata": {"path": f"{working_directory}"}})
    except CellExecutionError:
        output, _ = exporter.from_notebook_node(nb)
        print(output)
        raise
    output, _ = exporter.from_notebook_node(nb)
    return output


class OutputExporter(Exporter):
    """nbconvert Exporter to export notebook output as single string source code."""

    # Extension of the file that should be written to disk (used by parent class)
    file_extension = ".py"

    def from_notebook_node(self, nb: NotebookNode, **kwargs):
        notebook, _ = super().from_notebook_node(nb, **kwargs)
        # notebooks are lists of cells, code cells are of the format:
        # {"cell_type": "code",
        #  "outputs":[
        #     {
        #         "output_type": "stream"|"bytes",
        #         "text":"text of interest that we want to capture"
        #     }, ...]}
        # Hence the following list comprehension:
        cell_outputs = [
            output.get("text", "") + os.linesep
            for cell in notebook.cells
            if cell.cell_type == "code"
            for output in cell.outputs
            if output
            if output.get("output_type") == "stream"
        ]

        outputs = os.linesep.join(cell_outputs)

        return outputs, ResourcesDict()


class CalledProcessError(subprocess.CalledProcessError):
    """An error for subprocesses which captures stdout and stderr in the error message."""

    def __str__(self) -> str:
        original_message = super().__str__()
        return f"{original_message}\n" f"{self.stdout}\n" f"{self.stderr}"


def run_command_fail_explicitly(
    command: Union[str, List[str]],
    cwd: str = ".",
    *,
    suppress_warnings: bool = False,
    **kwargs,
) -> str:
    """Runs a command returning the output or failing with useful information

    Args:
        command: The command to execute, can also be a space separated string.
        cwd: The directory in which the command should be
            launched. If called by a pytest test function or method, this
            probably should be a `tmp_path` fixture.
        suppress_warnings: Do not include warnings in stdout, so it can be
                           parsed more reliably. Will still be captured if
                           command raises an exception.
        **kwargs: Additional keyword arguments are passed to
            `subprocess.check_output`.

    Returns:
        The standard output and error of the command if successfully executed.

    Raises:
        RuntimeError: If the subprocess command executes with a non-zero output.
    """

    if suppress_warnings:
        # Warn if parameters contradict
        if "stderr" in kwargs and kwargs["stderr"] != subprocess.PIPE:
            warnings.warn(
                "`run_command_fail_explicitly` parameter `suppress_warnings` will"
                " override other specified parameter `stderr`. Using"
                " `stderr=subprocess.PIPE`",
                stacklevel=2,
            )

        # PIPE rather None, so we can still access from exceptions below
        kwargs["stderr"] = subprocess.PIPE

    DEFAULT_KWARGS = {
        "shell": isinstance(command, str) and " " in command,
        "stderr": subprocess.STDOUT,
        "timeout": DEFAULT_PROCESS_TIMEOUT_SECONDS,
        "universal_newlines": True,
    }

    try:
        merged_kwargs = {**DEFAULT_KWARGS, **kwargs}
        out = subprocess.check_output(
            command,
            cwd=cwd,
            **merged_kwargs,
        )
    except subprocess.CalledProcessError as e:
        stdout = e.stdout
        stderr = e.stderr
        # type of the stdout stream will depend on the subprocess.
        # The python docs say decoding is to be handled at
        # application level.
        if hasattr(stdout, "decode"):
            stdout = stdout.decode("utf-8", errors="ignore")
        if hasattr(stderr, "decode"):
            stderr = stderr.decode("utf-8", errors="ignore")
        raise CalledProcessError(1, cmd=command, output=stdout, stderr=stderr) from e
    return out