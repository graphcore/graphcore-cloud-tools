# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
#!/bin/bash

# Inputs with defaults
SDK_PATH=$1
APPLICATION_NAME=$2
BENCHMARK_NAME=$3
ADDITIONAL_DIR=${4:-""}
BUILD_STEPS=${5:-""}

# If an additional dir is given, the benchmarks yml file will be one up
BENCHMARKS_YAML=./benchmarks.yml
if [[ $ADDITIONAL_DIR != "" ]]
then
    BENCHMARKS_YAML=../benchmarks.yml
fi

# In case a SDK is already enabled
popsdk-clean
# Enable SDK (poplar and popart)
cd $SDK_PATH/poplar-*
source enable.sh
cd - > /dev/null

cd $SDK_PATH/popart-*
source enable.sh
cd - > /dev/null
echo "Poplar SDK at ${SDK_PATH} enabled"

# Create and activate venv
# Assuming a compatible version of python is already available
sudo apt-get install python3-virtualenv
python3 -m venv ~/$APPLICATION_NAME
source ~/$APPLICATION_NAME/bin/activate
echo "Python venv at ${HOME}/${APPLICATION_NAME} activated"

# Upgrade pip
pip3 install --upgrade pip

# Determine framework used and install packages needed
cd $SDK_PATH
FRAMEWORK=${BENCHMARK_NAME:0:3}
case $FRAMEWORK in
    "pyt")
        FRAMEWORK="pytorch"
        pip3 install poptorch*
        ;;
    "pop")
        FRAMEWORK="popart"
        ;;
    "tf1")
        FRAMEWORK="tensorflow1"
        pip3 install tensorflow-1*amd*
        pip3 install ipu_tensorflow_addons-1*
        ;;
    "tf2")
        FRAMEWORK="tensorflow2"
        pip3 install tensorflow-2*amd*
        pip3 install ipu_tensorflow_addons-2*
        pip3 install keras-2*
        ;;
esac

pip3 install horovod*
cd -

# Install application requirementsx
cd ~/examples/*/$APPLICATION_NAME/$FRAMEWORK/$ADDITIONAL_DIR/
pip3 install -r ./requirements.txt

# Run additional build steps
eval " $BUILD_STEPS"

# Run benchmark
python3 -m examples_utils benchmark --spec $BENCHMARKS_YAML --benchmark $BENCHMARK_NAME --log-dir /tmp/${APPLICATION_NAME}_logs/
cd -

# Deactivate venv and disable sdk
deactivate
rm -rf ~/$APPLICATION_NAME
popsdk-clean
