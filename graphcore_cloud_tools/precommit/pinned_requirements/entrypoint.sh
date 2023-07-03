#!/bin/bash

pushd $(dirname $0)/../../../ > /dev/null

python3 -m pip install -r requirements.txt > /dev/null
python3 -m pip install -r requirements-precommit.txt > /dev/null

MODULE_ROOT=$(pwd)
popd > /dev/null
PYTHONPATH=$PYTHONPATH:$MODULE_ROOT python3 -m graphcore_cloud_tools.precommit.pinned_requirements.pinned_requirements $@
exit $?