# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import shutil
from time import sleep, time

import ctypes
from contextlib import suppress

from cppimport.checksum import is_checksum_valid
from cppimport.importer import get_module_name, get_extension_suffix, setup_module_data, template_and_build
from filelock import FileLock, Timeout

from examples_utils import sdk_version_hash
import os
import logging

__all__ = ['load_lib']


def get_module_data(filepath: str):
    """Create module data dictionary that `cppimport` uses"""
    fullname = os.path.splitext(os.path.basename(filepath))[0]
    return setup_module_data(fullname, filepath)


def get_module_data_new_path(filepath: str):
    """Create module data dictionary that `cppimport` uses but with new binary path (with GC-SDK version)"""
    module_data = get_module_data(filepath)
    binary_path = get_binary_path(filepath)
    module_data['ext_path'] = binary_path
    module_data['ext_name'] = os.path.basename(binary_path)
    return module_data


def get_binary_path(filepath: str) -> str:
    """Binary path that includes GraphCore SDK version hash (derived from `cppimport` binary path).
    e.g.`foo.gc-sdk-5f7a58bf8e.cpython-36m-x86_64-linux-gnu.so`"""
    fullname = os.path.splitext(os.path.basename(filepath))[0]
    file_name = get_module_name(fullname) + f'.gc-sdk-{sdk_version_hash()}' + get_extension_suffix()
    path = os.path.join(os.path.dirname(filepath), file_name)
    return path


def load_lib(filepath: str, timeout: int = 5 * 60):
    """Compile a C++ source file using `cppimport`, load the shared library into the process using `ctypes` and
    return it.

    Compilation is not triggered if an existing binary matches the source file hash which is embedded in the binary
    file and the Graphcore SDK version hash matches the binary which is included in the binary filename.

    `cppimport` is used to compile the source which uses a special comment in the C++ file that includes the
    compilation parameters. Here is an example of such a comment which defines compiler flags, additional sources files
    and library options (see `cppimport` documentation for more info):

    ```
    /*
    <%
    cfg['sources'] = ['another_source.cpp']
    cfg['extra_compile_args'] = ['-std=c++14', '-fPIC', '-O2', '-DONNX_NAMESPACE=onnx', '-Wall']
    cfg['libraries'] = ['popart', 'poplar', 'popops', 'poputil', 'popnn']
    setup_pybind11(cfg)
    %>
    */
    ```

    Additionally the function has a safeguard against multiple processes trying to compile the source at the same time.
    When compilation is triggered the process obtains a file-lock preventing other processes to try and compile the same
    source. The file-lock is located in the same directory as the source file to also prevent processes on different
    systems from doing the same. Once one of the processes compiles the source, all processes can load the same binary
    file.

    Parameters:
    filepath (str): File path of the C++ source file
    timeout (int): Timeout time if cannot obtain lock to compile the source

    Returns:
    lib: library instance. Output of `ctypes.cdll.LoadLibrary`
    """
    filepath = os.path.abspath(filepath)  # Build tools can have issues if relative path
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Custom op file does not exist: {filepath}")

    binary_path = get_binary_path(filepath)
    lock_path = binary_path + '.lock'

    module_data = get_module_data(filepath)
    module_data_new_path = get_module_data_new_path(filepath)

    t = time()

    # Need to check:
    # 1) binary path exists - otherwise the binary could be compiled against a different SDK
    # 2) binary checksum - otherwise the c++ source may of changed and need to recompile
    while not (os.path.exists(binary_path) and is_checksum_valid(module_data_new_path)) and time() - t < timeout:
        try:
            with FileLock(lock_path, timeout=1):
                if os.path.exists(binary_path) and is_checksum_valid(module_data_new_path):
                    break
                template_and_build(filepath, module_data)
                cppimport_binary_path = module_data['ext_path']
                shutil.copy(cppimport_binary_path, binary_path)
                os.remove(cppimport_binary_path)
                logging.debug(f'{os.getpid()}: Built binary')
        except Timeout:
            logging.debug(f'{os.getpid()}: Could not obtain lock')
            sleep(1)

    if not (os.path.exists(binary_path) and is_checksum_valid(module_data_new_path)):
        raise Exception(
            f'Could not compile binary as lock already taken and timed out. Lock file will be deleted: {lock_path}')

    if os.path.exists(lock_path):
        with suppress(OSError):
            os.remove(lock_path)

    lib = ctypes.cdll.LoadLibrary(binary_path)
    logging.debug(f'{os.getpid()}: Loaded binary')

    return lib
