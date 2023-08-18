
from graphcore_cloud_tools import notebook_logging


import pathlib

import os
import nbformat
from nbconvert import Exporter
from nbconvert.exporters.exporter import ResourcesDict
from nbconvert.preprocessors import CellExecutionError, ExecutePreprocessor
from nbformat import NotebookNode


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


REPO_ROOT = pathlib.Path(__file__).parents[1].resolve()
TEST_FILES_DIR = REPO_ROOT / "tests" / "test_files"


def test_notebook():
    notebook_filename = TEST_FILES_DIR / "sample.ipynb"
    output = run_notebook(str(notebook_filename), str(REPO_ROOT), 300)
    logger_turned_on_and_stopped = notebook_logging.USER_WARNING_STRING in output and notebook_logging.LOGGER_DISABLED_NOTICE in output
    logger_failed_to_start = output.count(notebook_logging.LOGGER_DISABLED_NOTICE) == 2
    assert logger_turned_on_and_stopped or logger_failed_to_start
