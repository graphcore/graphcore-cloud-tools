# Copyright (c) 2022 Graphcore Ltd. All rights reserved.

import hashlib
import os
import pytest
import json
from uuid import getnode as get_mac

from tomlkit import item
from examples_utils.notebook_logger.config_logger import LoggingState, LoggingTarget, ConfigLogger
from examples_utils.testing import test_commands


def setLoggingTarget(logging_target, target_err=False):
    if target_err:
        os.environ["GC_EXAMPLE_LOG_TARGET"] = "err"
    elif logging_target is None:
        if "GC_EXAMPLE_LOG_TARGET" in os.environ:
            del os.environ["GC_EXAMPLE_LOG_TARGET"]
    else:
        os.environ["GC_EXAMPLE_LOG_TARGET"] = str(LoggingTarget.LOCAL)


def createConfigFile(enabledState, config_err=False):
    config_path = ConfigLogger.GC_EXAMPLE_LOG_CFG_PATH
    config_file = ConfigLogger.GC_EXAMPLE_LOG_CFG_FILE

    deleteConfigFile()

    config_dict = {}
    if config_err:
        # create error config file
        config_dict["error"] = "err"
    else:
        if enabledState:
            config_dict["GC_EXAMPLE_LOG_STATE"] = str(enabledState)
        else:
            return

    config_path.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w") as f:
        json.dump(config_dict, f)


def deleteConfigFile():
    if ConfigLogger.GC_EXAMPLE_LOG_CFG_FILE.is_file():
        ConfigLogger.GC_EXAMPLE_LOG_CFG_FILE.unlink()


def createLogFile(log_dict):
    if log_dict:
        ConfigLogger.GC_EXAMPLE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ConfigLogger.GC_EXAMPLE_LOG_FILE, "w") as f:
            json.dump(log_dict, f)


def deleteLogFiles():
    if ConfigLogger.GC_EXAMPLE_LOG_FILE.parent.is_dir():
        for child in ConfigLogger.GC_EXAMPLE_LOG_FILE.parent.glob("*"):
            child.unlink()
        ConfigLogger.GC_EXAMPLE_LOG_FILE.parent.rmdir()


def deleteLogDir():
    deleteConfigFile()
    deleteLogFiles()
    if ConfigLogger.GC_EXAMPLE_LOG_CFG_PATH.is_dir():
        ConfigLogger.GC_EXAMPLE_LOG_CFG_PATH.rmdir()


def clearAll():
    setLoggingTarget(None)
    deleteLogDir()


def setState(target=None, target_err=False, config_state=None, config_err=False, log_dict=None):
    clearAll()
    setLoggingTarget(target, target_err)
    createConfigFile(config_state, config_err)
    createLogFile(log_dict)


def checkConfig(config=None):
    if config:
        with open(ConfigLogger.GC_EXAMPLE_LOG_CFG_FILE, "r") as f:
            saved_config = json.load(f)
            assert saved_config["GC_EXAMPLE_LOG_STATE"] == str(config)
    else:
        assert not ConfigLogger.GC_EXAMPLE_LOG_CFG_FILE.is_file()


def checkLog(log=None):
    if log:
        with open(ConfigLogger.GC_EXAMPLE_LOG_FILE, "r") as f:
            saved_log = json.load(f)
            assert "log" in saved_log
            assert len(saved_log["log"]) == len(log["log"])
            for expected, saved in zip(log["log"], saved_log["log"]):
                assert "timestamp" in saved
                assert saved["userhash"] == expected["userhash"]
                assert saved["repository"] == expected["repository"]
                assert saved["example"] == expected["example"]
                assert saved["script_name"] == expected["script_name"]
                assert saved["command_args"] == expected["command_args"]
    else:
        assert not ConfigLogger.GC_EXAMPLE_LOG_FILE.is_file()


def getExpectedLogDict(list_of_args_lists):
    log_dict = {"log": []}

    for args in list_of_args_lists:
        log_line = {}

        # to anonymise the username, hash the mac address concatenated with the username
        # (because a mac address is not as easily knowable) TODO: this doesn't make that much sense.. could use something like a public key instead maybe?
        h = hashlib.sha256()
        username = os.environ.get("USER")
        mac_address = get_mac()
        unique_user_hash = f"{mac_address}_{username}"
        h.update(unique_user_hash.encode("utf-8"))

        log_line["userhash"] = h.hexdigest()[:10]

        # get path of repo
        log_line["repository"] = "examples-utils"
        log_line["example"] = "tests/test_files"
        log_line["script_name"] = "mock_run.py"

        log_line["command_args"] = args

        log_dict["log"].append(log_line)
    return log_dict


class TestLoggingConfigurations:
    generic_cmd = ["python", "test_files/mock_run.py"]
    generic_arguments = ["--a", "--b", "--c"]
    cwd = os.path.dirname(os.path.abspath(__file__))

    # called automatically for each test to set and creates the configuration environment specified
    @pytest.fixture(scope="function", autouse=True)
    def setup_and_teardown_env(self, target=None, target_err=False, config_state=None, config_err=False, log_dict=None):
        # import pdb; pdb.set_trace()
        # setState(target, target_err, config_state, config_err, log_dict)
        clearAll()
        yield
        clearAll()

    def run_command(self, override_args=None, std_in=None):
        cmd, default_args = self.generic_cmd.copy(), self.generic_arguments.copy()
        if override_args:
            default_args = override_args
        cmd.extend(default_args)
        out = test_commands.run_command_fail_explicitly(cmd, self.cwd, input=std_in)
        return out

    # setup with target false (which is the default)
    @pytest.mark.parametrize("config_state", [(None), (LoggingState.DISABLED), (LoggingState.ENABLED)])
    def test_no_logging_target(self, config_state):
        # import pdb; pdb.set_trace()
        setState(config_state=config_state)

        # run the script
        out = self.run_command()
        test_commands.check_missing_patterns(out, expected_patterns=["success"])
        assert out == "success\n"

        # check that no log exists regardless of the config state
        checkConfig(config=config_state)
        checkLog()

    # setup with target error
    @pytest.mark.parametrize(
        "target_err,config_state", [(True, None), (True, LoggingState.DISABLED), (True, LoggingState.ENABLED)]
    )
    def test_logging_target_error(self, target_err, config_state):
        setState(target_err=target_err, config_state=config_state)

        # run the script, check error is printed but script returns
        out = self.run_command()
        test_commands.check_missing_patterns(out, expected_patterns=["Error: no known logging target type", "success"])

        # check that no log exists regardless of the config state
        checkConfig(config=config_state)
        checkLog()

    # parameterised on, off, error
    @pytest.mark.parametrize("logging_target,config_state", [(LoggingTarget.LOCAL, LoggingState.DISABLED)])
    def test_local_target_config_off(self, logging_target, config_state):
        setState(target=logging_target, config_state=config_state)

        # run the script
        out = self.run_command()
        test_commands.check_missing_patterns(out, expected_patterns=["success"])
        assert out == "success\n"

        # check that config is set but no log exists
        checkConfig(config=config_state)
        checkLog()

    @pytest.mark.parametrize("logging_target,config_state", [(LoggingTarget.LOCAL, LoggingState.ENABLED)])
    def test_local_target_config_on(self, logging_target, config_state):
        setState(target=logging_target, config_state=config_state)

        # run the script
        out = self.run_command()
        test_commands.check_missing_patterns(out, expected_patterns=["success"])
        assert out == "success\n"

        # check that config is set and log is as expected
        checkConfig(config=config_state)
        checkLog(log=getExpectedLogDict([self.generic_arguments]))

    @pytest.mark.parametrize("logging_target,config_state", [(LoggingTarget.LOCAL, LoggingState.ENABLED)])
    def test_local_target_config_on_run_twice(self, logging_target, config_state):
        setState(target=logging_target, config_state=config_state)

        # run the script
        out = self.run_command()
        test_commands.check_missing_patterns(out, expected_patterns=["success"])
        assert out == "success\n"

        different_arguments = ["--d", "--e", "--f"]
        out = self.run_command(override_args=different_arguments)
        test_commands.check_missing_patterns(out, expected_patterns=["success"])
        assert out == "success\n"

        # check that config is set and log is as expected
        checkConfig(config=config_state)
        checkLog(log=getExpectedLogDict([self.generic_arguments, different_arguments]))

    @pytest.mark.parametrize("logging_target,config_err", [(LoggingTarget.LOCAL, True)])
    def test_local_target_config_err(self, logging_target, config_err):
        setState(target=logging_target, config_err=config_err)

        # run the script, check error is printed but script returns
        out = self.run_command()
        test_commands.check_missing_patterns(out, expected_patterns=["Error reading logging config file at", "success"])

        # check that no log exists
        checkLog()

    # parameterised y, n, (needs an input)
    @pytest.mark.parametrize(
        "logging_target,std_in",
        [(LoggingTarget.LOCAL, "no\n"), (LoggingTarget.LOCAL, "n\n"), (LoggingTarget.LOCAL, "disable\n")],
    )
    def test_local_target_no_config_set_disabled(self, logging_target, std_in):
        setState(target=logging_target)

        # run the script, check for privacy notice and script returns
        expected_patterns = []
        expected_patterns.append(
            "Graphcore would like to collect information about which examples and configurations have been run to improve usability and support for future users"
        )
        expected_patterns.append("Please respond with 'yes'/'no' whether you accept this request")
        expected_patterns.append("success")
        out = self.run_command(std_in=std_in)
        test_commands.check_missing_patterns(out, expected_patterns=expected_patterns)

        # check that config is set and log is empty
        checkConfig(config=LoggingState.DISABLED)
        checkLog()

        different_arguments = ["--d", "--e", "--f"]

        # check that it successfully runs again and doesn't create a log
        out = self.run_command(override_args=different_arguments)
        test_commands.check_missing_patterns(out, expected_patterns=["success"])
        assert out == "success\n"

        # check that config is set and no logging has occurred
        checkConfig(config=LoggingState.DISABLED)
        checkLog()

    # parameterised y, n, (needs an input)
    @pytest.mark.parametrize(
        "logging_target,std_in",
        [(LoggingTarget.LOCAL, "yes\n"), (LoggingTarget.LOCAL, "y\n"), (LoggingTarget.LOCAL, "enable\n")],
    )
    def test_local_target_no_config_set_enabled(self, logging_target, std_in):
        setState(target=logging_target)

        # run the script, check for privacy notice and script returns
        expected_patterns = []
        expected_patterns.append(
            "Graphcore would like to collect information about which examples and configurations have been run to improve usability and support for future users"
        )
        expected_patterns.append("Please respond with 'yes'/'no' whether you accept this request")
        expected_patterns.append("success")
        out = self.run_command(std_in=std_in)
        test_commands.check_missing_patterns(out, expected_patterns=expected_patterns)

        # check that config is set and log is as expected
        checkConfig(config=LoggingState.ENABLED)
        checkLog(log=getExpectedLogDict([self.generic_arguments]))

        different_arguments = ["--d", "--e", "--f"]

        # check that it successfully runs again and autmatically logs to the same file
        out = self.run_command(override_args=different_arguments)
        test_commands.check_missing_patterns(out, expected_patterns=["success"])
        assert out == "success\n"

        # check that config is set and log is as expected
        checkConfig(config=LoggingState.ENABLED)
        checkLog(log=getExpectedLogDict([self.generic_arguments, different_arguments]))
