# Copyright (c) 2023 Graphcore Ltd. All rights reserved.
from graphcore_cloud_tools import notebook_logging


import pathlib
from . import testutils



REPO_ROOT = pathlib.Path(__file__).parents[1].resolve()
TEST_FILES_DIR = REPO_ROOT / "tests" / "test_files"


def test_notebook():
    notebook_filename = TEST_FILES_DIR / "sample.ipynb"
    output = testutils.run_notebook(str(notebook_filename), str(REPO_ROOT), 300)
    logger_turned_on_and_stopped = notebook_logging.USER_WARNING_STRING in output and notebook_logging.LOGGER_DISABLED_NOTICE in output
    logger_failed_to_start = output.count(notebook_logging.LOGGER_DISABLED_NOTICE) == 2
    assert logger_turned_on_and_stopped or logger_failed_to_start
