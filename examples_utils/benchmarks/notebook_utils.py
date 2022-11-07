# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import argparse
import os

try:
    import nbformat
    from nbconvert import Exporter
    from nbconvert.exporters.exporter import ResourcesDict
    from nbconvert.preprocessors import CellExecutionError, ExecutePreprocessor
    from nbformat import NotebookNode
except (ImportError, ModuleNotFoundError) as error:
    from . import _incorrect_requirement_variant_error
    raise _incorrect_requirement_variant_error from error

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
            output.get("text", "") + os.linesep for cell in notebook.cells if cell.cell_type == "code"
            for output in cell.outputs if output if output.get("output_type") == "stream"
        ]

        outputs = os.linesep.join(cell_outputs)

        return outputs, ResourcesDict()


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("filename", type=str, help="The filename of the notebook to run")
    parser.add_argument("working_dir", type=str, help="The working directory in which to run")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="The timeout of the notebook")
    arg = parser.parse_args()
    stream = run_notebook(arg.filename, arg.working_dir, arg.timeout)
    print(stream)


if __name__ == "__main__":
    cli()
