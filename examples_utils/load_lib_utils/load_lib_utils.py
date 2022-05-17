# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import ctypes
import os
import logging
from examples_utils.load_lib_utils.cppimport_backports import _check_first_line_contains_cppimport
from examples_utils.load_lib_utils.cppimport_safe import cppimport_build_safe

__all__ = ['load_lib', 'build_lib']

settings = {'file_exts': ('.cpp', )}


def build_lib(filepath: str, timeout: int = 5 * 60):
    return cppimport_build_safe(filepath=filepath, timeout=timeout, sdk_version_check=True)


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
    module_data_new_path = cppimport_build_safe(filepath=filepath, timeout=timeout, sdk_version_check=True)
    binary_path = module_data_new_path['ext_path']
    lib = ctypes.cdll.LoadLibrary(binary_path)
    logging.debug(f'{os.getpid()}: Loaded binary')

    return lib


def load_lib_all(dir_path: str, timeout: int = 5 * 60, load: bool = True):
    """
    Recursively search the directory `dir_path` and use `load_lib` to build and load eligible files.

    Eligible files have a `cpp` file extension and the first line contains the comment `\\ cppimport`.

    Args:
        dir_path: Path of directory to start search for files to compile
        timeout: Timeout of `load_lib` compile
        load: If True will load the libs and return, otherwise just compile

    Returns:
        libs: If `load==True` return a list of tuples (path, lib) otherwise just a list of paths of compiled files
    """
    libs = []
    for directory, _, files in os.walk(dir_path):
        for file in files:
            if (not file.startswith(".") and os.path.splitext(file)[1] in settings["file_exts"]):
                full_path = os.path.join(directory, file)
                if _check_first_line_contains_cppimport(full_path):
                    if load:
                        lib = load_lib(filepath=full_path, timeout=timeout)
                        libs += [(full_path, lib)]
                    else:
                        cppimport_build_safe(filepath=full_path, timeout=timeout, sdk_version_check=True)
                        libs += [full_path]
                    logging.info(f'Built: {full_path}')

    return libs
