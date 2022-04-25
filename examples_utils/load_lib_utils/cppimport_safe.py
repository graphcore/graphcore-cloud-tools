# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import shutil
from time import sleep, time

from contextlib import suppress

from cppimport.checksum import is_checksum_valid
from cppimport.importer import get_module_name, get_extension_suffix, setup_module_data, template_and_build
from filelock import FileLock, Timeout

import os
import logging


def get_module_data(filepath: str):
    """Create module data dictionary that `cppimport` uses"""
    fullname = os.path.splitext(os.path.basename(filepath))[0]
    return setup_module_data(fullname, filepath)


def get_module_data_with_sdk_version(filepath: str):
    """Create module data dictionary that `cppimport` uses but with new binary path (with GC-SDK version)"""
    module_data = get_module_data(filepath)
    binary_path = get_binary_path_with_sdk_version(filepath)
    module_data['ext_path'] = binary_path
    module_data['ext_name'] = os.path.basename(binary_path)
    return module_data


def get_binary_path_with_sdk_version(filepath: str) -> str:
    """Binary path that includes GraphCore SDK version hash (derived from `cppimport` binary path).
    e.g.`foo.gc-sdk-5f7a58bf8e.cpython-36m-x86_64-linux-gnu.so`"""
    from examples_utils.sdk_version_hash import sdk_version_hash
    fullname = os.path.splitext(os.path.basename(filepath))[0]
    file_name = get_module_name(fullname) + f'.gc-sdk-{sdk_version_hash()}' + get_extension_suffix()
    path = os.path.join(os.path.dirname(filepath), file_name)
    return path


def cppimport_build_safe(filepath: str, timeout: int = 5 * 60, sdk_version_check=False):
    """Compile a C++ source file using `cppimport`.

    Safeguard against multiple processes trying to compile the module at the same time.

    Parameters:
        filepath (str): File path of the C++ source file
        timeout (int): Timeout time if it cannot obtain the lock to compile the source
        sdk_version_check (bool): Check the SDK version hash to determine if to recompile

    Returns:
        module_data: cppimport module_data dictionary. 'ext_path' is the path to the compiled binary file
    """

    filepath = os.path.abspath(filepath)  # Build tools can have issues if relative path
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Could not build or load binary. File does not exist: {filepath}")

    module_data = get_module_data(filepath)

    if sdk_version_check:
        binary_path = get_binary_path_with_sdk_version(filepath)
        module_data_new_path = get_module_data_with_sdk_version(filepath)
    else:
        binary_path = module_data['ext_path']
        module_data_new_path = module_data  # Same path. No need to rename cppimport output

    lock_path = binary_path + '.lock'

    t = time()

    # Need to check:
    # 1) binary path exists - otherwise the binary could be compiled against a different SDK
    # 2) binary checksum - otherwise the c++ source may have changed and need to recompile
    while not (os.path.exists(binary_path) and is_checksum_valid(module_data_new_path)) and time() - t < timeout:
        try:
            with FileLock(lock_path, timeout=1):
                # Obtained lock:
                # 1) Check if compilation is necessary (again)
                # 2) Build binary
                # 3) If necessary rename binary file to include SDK version hash
                if os.path.exists(binary_path) and is_checksum_valid(module_data_new_path):
                    break
                template_and_build(filepath, module_data)
                cppimport_binary_path = module_data['ext_path']
                if os.path.normpath(cppimport_binary_path) != os.path.normpath(binary_path):
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

    return module_data_new_path
