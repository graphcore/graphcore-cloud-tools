# Copyright (c) 2023 Graphcore Ltd. All rights reserved.

import pytest
from pathlib import Path
from typing import Dict, Generator, List, Tuple
from requirements.requirement import Requirement
from graphcore_cloud_tools.precommit.pinned_requirements.pinned_requirements import (
    main,
    manual_parse_named_git,
    is_valid_req,
    invalid_requirements,
    try_write_fixed_requirements,
)


REQUIREMENTS: List[Tuple[str, bool]] = [
    ("protobuf==3.19.4", True),
    ("wandb>=0.12.8", False),
    ("horovod[pytorch]==0.24.0", True),
    ("git+https://github.com/graphcore/graphcore-cloud-tools", False),
    ("cmake==3.22.4", True),
    ("numpy==1.23.5; python_version > '3.7'", True),
    ("numpy==1.19.5; python_version <= '3.7'", True),
    ("pandas", False),
    (
        "graphcore-cloud-tools[common] @ git+https://github.com/graphcore/graphcore-cloud-tools.git@7cd37a8eccabe88e3741eef2c31bafd4fcd30c4c",
        True,
    ),
    (
        "graphcore-cloud-tools @ git+https://github.com/graphcore/graphcore-cloud-tools.git",
        False,
    ),
    ("torch>=2.0.0+cpu", False),
    ("torch>=2.0.0+cpu # req: unpinned", True),
]


@pytest.mark.parametrize(
    "line, expected_result",
    [
        ("git+https://github.com/graphcore/graphcore-cloud-tools", False),
        (
            "graphcore-cloud-tools[common] @ git+https://github.com/graphcore/graphcore-cloud-tools.git@7cd37a8eccabe88e3741eef2c31bafd4fcd30c4c",
            True,
        ),
        (
            "graphcore-cloud-tools @ git+https://github.com/graphcore/graphcore-cloud-tools.git",
            False,
        ),
    ],
)
def test_manual_parse_named_git(line: str, expected_result: bool):
    output = manual_parse_named_git(line)
    assert output == expected_result


@pytest.mark.parametrize("line, expected_result", REQUIREMENTS)
def test_is_valid_req(line: str, expected_result: bool):
    req = Requirement.parse(line)
    output = is_valid_req(req)
    assert output == expected_result


def create_req_file(tmp_path: Path, requirement_dict: Dict[str, bool]) -> str:
    req_file = tmp_path / "requirements.txt"
    with open(req_file, "w") as fh:
        for r in requirement_dict.keys():
            fh.write(r + "\n")

    return str(req_file)


def test_invalid_requirements(tmp_path: Path):
    requirement_dict = dict(REQUIREMENTS)
    req_file = create_req_file(tmp_path, requirement_dict)
    invalid = invalid_requirements(req_file, False)

    invalid_lines = [r.line for r in invalid]
    for req_line, valid in requirement_dict.items():
        if not valid:
            assert req_line in invalid_lines
        else:
            assert req_line not in invalid_lines


@pytest.mark.parametrize(
    "reqs, expected_result",
    [
        (REQUIREMENTS, 1),
        ([REQUIREMENTS[0]], 0),
    ],
)
def test_main(tmp_path: Path, reqs: List[Tuple[str, bool]], expected_result: int):
    requirement_dict = dict(reqs)
    req_file = create_req_file(tmp_path, requirement_dict)
    output = main([req_file], False)
    assert output == expected_result


def test_bad_filename():
    output = main(["myfile.txt"])
    assert output == 2


def test_fix_invalid(tmp_path: Path, mocker: Generator["MockerFixture", None, None]):
    mocker.patch("importlib.metadata.version", return_value="5.1.1")

    requirement_dict = {
        "numpy==1.23.5": True,
        "pandas": False,
        "git+https://github.com/graphcore/graphcore-cloud-tools": False,
    }

    reqs = [Requirement.parse(x) for x in requirement_dict.keys()]

    invalid = [
        Requirement.parse("pandas"),
        Requirement.parse("git+https://github.com/graphcore/graphcore-cloud-tools"),
    ]

    req_file = create_req_file(tmp_path, requirement_dict)
    try_write_fixed_requirements(reqs, invalid, req_file)

    expected_lines = [
        "numpy==1.23.5",
        "pandas==5.1.1",
        "git+https://github.com/graphcore/graphcore-cloud-toolsd-tools",
    ]
    with open(req_file) as fh:
        lines = fh.readlines()

    assert len(lines) == len(requirement_dict)
    for line in lines:
        assert line.strip() in expected_lines
