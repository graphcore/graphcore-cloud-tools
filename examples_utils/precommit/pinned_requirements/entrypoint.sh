#!/bin/bash
python3 -m pip install -r requirements-precommit.txt
python3 -m examples_utils.precommit.pinned_requirements.pinned_requirements $@
exit $?
