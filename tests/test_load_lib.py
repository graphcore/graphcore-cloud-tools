# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import subprocess
from contextlib import contextmanager
from glob import glob
from tempfile import TemporaryDirectory
from unittest.mock import patch

import hashlib
from pathlib import Path

import pytest

import os
from multiprocessing import Process

from examples_utils import load_lib
from examples_utils.load_lib_utils.load_lib_utils import get_module_data, load_lib_all

cpp_code_pybind = """// cppimport
#include <pybind11/pybind11.h>

namespace py = pybind11;

int square(int x) {
    return x * x;
}

PYBIND11_MODULE(module, m) {
    m.def("square", &square);
}
/*
<%
setup_pybind11(cfg)
%>
*/
"""

cpp_code_no_pybind = """// cppimport

int square(int x) {
    return x * x;
}

/*
<%
setup_pybind11(cfg)
%>
*/
"""


@contextmanager
def create_cpp_file(cpp_source=cpp_code_pybind):
    """Create C++ file to compile. Create new one per test."""
    # Create empty temp C++ file to compile

    with TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, 'module.cpp')
        with open(path, 'w') as f:
            f.write(cpp_source)
        yield path


def md5_file_hash(path: str) -> str:
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def test_load_lib():
    with create_cpp_file() as cpp_file:
        module_data = get_module_data(cpp_file)
        binary_path = module_data['ext_path']

        # Compile first time
        load_lib(cpp_file)
        assert os.path.exists(binary_path)
        binary_hash = md5_file_hash(binary_path)

        # Test loading again when already compiled (binary should be untouched)
        load_lib(cpp_file)

        assert binary_hash == md5_file_hash(binary_path)


def test_load_lib_file_change():
    with create_cpp_file() as cpp_file:
        module_data = get_module_data(cpp_file)
        binary_path = module_data['ext_path']

        # Compile first time
        load_lib(cpp_file)
        assert os.path.exists(binary_path)
        binary_hash = md5_file_hash(binary_path)

        # Test loading again when file has changed
        with open(cpp_file, 'a') as f:
            f.write('\n int x = 1;')

        load_lib(cpp_file)
        assert os.path.exists(binary_path)
        assert binary_hash != md5_file_hash(binary_path)


def test_load_lib_sdk_change():
    with create_cpp_file() as cpp_file:
        module_data = get_module_data(cpp_file)
        binary_path = module_data['ext_path']

        # Compile first time
        load_lib(cpp_file)
        assert os.path.exists(binary_path)
        binary_hash = md5_file_hash(binary_path)

        # Test loading again when sdk has changed (monkey patch `sdk_version_hash` function)
        with patch('examples_utils.sdk_version_hash.sdk_version_hash', new=lambda: 'patch-version'):
            # Check patch
            from examples_utils.sdk_version_hash import sdk_version_hash
            assert 'patch-version' == sdk_version_hash(), 'Monkey patch has not worked. Is the import path correct?'

            # Compile again
            load_lib(cpp_file)
            assert os.path.exists(binary_path)
            assert binary_hash != md5_file_hash(binary_path)


def test_load_lib_no_pybind():
    with create_cpp_file(cpp_code_no_pybind) as cpp_file:
        module_data = get_module_data(cpp_file)
        binary_path = module_data['ext_path']

        # Compile first time
        load_lib(cpp_file)
        assert os.path.exists(binary_path)
        binary_hash = md5_file_hash(binary_path)

        # Test loading again when file has changed
        with open(cpp_file, 'a') as f:
            f.write('\n int x = 1;')

        load_lib(cpp_file)
        assert os.path.exists(binary_path)
        assert binary_hash != md5_file_hash(binary_path)


def test_load_lib_many_processors():
    with create_cpp_file() as cpp_file:
        processes = [Process(target=load_lib, args=(cpp_file, )) for i in range(1000)]

        for p in processes:
            p.start()

        for p in processes:
            p.join()

        assert all(p.exitcode == 0 for p in processes)

        load_lib(cpp_file)

        module_data = get_module_data(cpp_file)
        binary_path = module_data['ext_path']
        assert os.path.exists(binary_path)
        assert not os.path.exists(binary_path + '.lock')


@pytest.mark.parametrize('load', (True, False))
def test_load_lib_all(load):
    with TemporaryDirectory() as tmp_dir:
        tmp_dir = Path(tmp_dir)
        os.makedirs(Path(tmp_dir) / 'dir1' / 'dir2')

        # Write cpp 3 files in nested dirs
        with open(tmp_dir / 'module.cpp', 'w') as f:
            f.write(cpp_code_pybind)

        with open(Path(tmp_dir) / 'dir1' / 'module.cpp', 'w') as f:
            f.write(cpp_code_pybind)

        with open(Path(tmp_dir) / 'dir1' / 'dir2' / 'module.cpp', 'w') as f:
            f.write(cpp_code_pybind)

        # Decoy file
        with open(tmp_dir / 'module.not_cpp', 'w') as f:
            f.write(cpp_code_pybind)

        libs = load_lib_all(str(tmp_dir), load=load)
        assert len(libs) == 3


def test_cli():
    with create_cpp_file() as cpp_file:
        file_dir = os.path.dirname(cpp_file)
        output = subprocess.run(["python3", "-m", "examples_utils", 'load_lib_build', file_dir],
                                check=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        shell_output = str(output.stdout) + '\n' + str(output.stderr)
        binaries = glob(file_dir + '/*.so')
        assert 'Built' in shell_output
        assert len(binaries) > 0
