# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import os.path
from tempfile import NamedTemporaryFile
from unittest.mock import patch

import hashlib
import pathlib
from examples_utils.load_lib.load_lib import load_lib, get_binary_path

from multiprocessing import Process


def create_cpp_file():
    """Create C++ file to compile. Create new one per test."""
    # Create empty temp C++ file to compile
    cpp_code = """
    // cppimport
    #include <pybind11/pybind11.h>

    namespace py = pybind11;

    int square(int x) {
        return x * x;
    }

    PYBIND11_MODULE(somecode, m) {
        m.def("square", &square);
    }
    /*
    <%
    setup_pybind11(cfg)
    %>
    */
    """
    file = NamedTemporaryFile(suffix='.cpp', mode='w')
    file.write(cpp_code)
    return file


def md5_file_hash(path: str) -> str:
    return hashlib.md5(pathlib.Path(path).read_bytes()).hexdigest()


def test_custom_ops():
    cpp_file = create_cpp_file()

    # Compile first time
    load_lib(cpp_file.name)

    binary_path = get_binary_path(cpp_file.name)
    assert os.path.exists(binary_path)
    assert not os.path.exists(binary_path + '.lock')
    binary_hash = md5_file_hash(binary_path)

    # Test loading again when already compiled (binary should be untouched)
    load_lib(cpp_file.name)

    assert os.path.exists(binary_path)
    assert not os.path.exists(binary_path + '.lock')
    assert binary_hash == md5_file_hash(binary_path)


def test_custom_ops_file_change():
    cpp_file = create_cpp_file()

    # Compile first time
    load_lib(cpp_file.name)

    binary_path = get_binary_path(cpp_file.name)
    assert os.path.exists(binary_path)
    assert not os.path.exists(binary_path + '.lock')
    binary_hash = md5_file_hash(binary_path)

    # Test loading again when file has changed
    with open(cpp_file.name, 'a') as f:
        f.write('\n int x = 1;')

    load_lib(cpp_file.name)
    assert os.path.exists(binary_path)
    assert not os.path.exists(binary_path + '.lock')
    assert binary_hash != md5_file_hash(binary_path)


def test_custom_ops_sdk_change():
    cpp_file = create_cpp_file()

    # Compile first time
    load_lib(cpp_file.name)

    binary_path = get_binary_path(cpp_file.name)
    assert os.path.exists(binary_path)
    assert not os.path.exists(binary_path + '.lock')
    binary_hash = md5_file_hash(binary_path)

    # Test loading again when sdk has changed (monkey patch `sdk_version_hash` function)
    with patch('examples_utils.load_lib.load_lib.sdk_version_hash', new=lambda: 'patch-version'):
        load_lib(cpp_file.name)
        binary_path_new = get_binary_path(cpp_file.name)
        assert 'patch-version' in binary_path_new, 'Monkey patch has not worked. Is the path correct?'
        assert os.path.exists(binary_path_new)
        assert not os.path.exists(binary_path_new + '.lock')
        assert binary_hash == md5_file_hash(binary_path)


def test_custom_ops_many_processors():
    cpp_file = create_cpp_file()
    processes = [Process(target=load_lib, args=(cpp_file.name, )) for i in range(1000)]

    for p in processes:
        p.start()

    for p in processes:
        p.join()

    assert all(p.exitcode == 0 for p in processes)

    load_lib(cpp_file.name)

    binary_path = get_binary_path(cpp_file.name)
    assert os.path.exists(binary_path)
    assert not os.path.exists(binary_path + '.lock')
