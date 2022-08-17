# Benchmark creation guide
In this guide we will go through the process of creating a benchmark, using examples to show the steps involved and attempt to explain why these are important. Please pay particular attention to the <strong>Prerequisites</strong> and <strong>Testing</strong> sections when creating and submitting benchmarks.

## Prerequisites
There are a few things that should be required but are currently impractical for all apps to provide. However, these should make benchmarking much easier.
- The app should be able to run on 16 and 64 IPUs as a minimum for training and 4 IPUs as a minimum for inference. Configurations outside these such as 8 or 32 are discouraged.
- The parent dir for the app setup and script should be the same, so that one location can be provided to the benchmarking scripts and the requirements, makefiles and all python scripts required to interface with app are available there
- Metrics output by the app should follow a standard as defined in the <strong>Formatting and standardisation</strong> section below.
- Both expected values for the metrics that are available at the end of the benchmark (throughput, accuracy etc.) and the expected runtime of the benchmarks should be known and provided. More information is given on how to setup the benchmark so that the scripts used can find the values of these metrics after benchmarking in the <strong>Other fields</strong> section below, but as a general rule of thumb, make sure to have expected values for these ready to provide to the applications-performance or test-automation teams.
- Datasets required for running these benchmarks should be available on an IT-managed machine where other teams such as software-infrastructure and test-automation can access them. In addition, dataset names and paths that the app will look for within the dataset directories should be simplified where possible, i.e. the app should be able to accept argument values like `--dataset-path $DATASETS_DIR/my_dataset` as opposed to `--dataset-path $DATASETS_DIR/my_dataset/subdir1/subdir2/data.jpg`.

## Creating the command line
Likely only a few changes will be required for the command line to be used in a benchmark:
- Add the `-vv` and `-print-topology yes` arg to all poprun calls. This is required for easy debugging and working with other teams when benchmarks fail.
- Try to avoid specifying multi-host arguments for single-host benchmarks, i.e. avoid providing `--hosts`, `--num-ilds` and VIPU arguments to POD16 and below commands. 
- Ensure that a config or equivalent file provides the majority of the arguments to the application, and only necessary arguments are provided outside of that.
- Add `--bind-to socket` to `mpirun` calls where mpirun is used instead of poprun to avoid default MPI behaviour that can negatively affect compile times.

The command can then be put into a yaml file like so:
```
cmd: >-
    poprun
        -vv
        --num-instances=16
        --num-replicas=64
        ...
    python3 train.py
        --config resnet50-pod64
        --dataloader-worker 14
        ...
```
Where the `>-` enables having multiple lines for the same field.

## Other fields
### <ins>Data/output</ins>
The data and output fields define how the benchmarking script will extract metrics from the app logs/stderr/stdout and also how it will provide them to ES (ElasticSearch, the database system we use to record benchmark results). The exact formatting and standards are described below in the <strong>Formatting and standardisation</strong> section, but as a breif summary:
```
data:
    throughput:
        regexp: 'throughput: *(.*?) samples\/sec'
        skip: 1
    accuracy:
        reduction_type: "final"
        regexp: 'accuracy: *(.*?)\%'
output:
    - [throughput, "throughput"]
    - [accuracy, "accuracy"]
```
- `regexp` defines how the benchmarks script will find the value of the metric in the logs.
- the `skip` field defines how many instances starting from the first of the metric being printed in logs will be skipped when reducing multiple values. This is mainly due to throughput values immediately post-compilation are usually wrong. 
- `reduction_type` defines how the multiple instances of the metric picked up by the regexes will be reduced. Providing no `reduction_type` results in the `mean` being used, whereas the other options are:
    - `final`: Take the value of the final instance of that metric found.
    - `min`: Take the minimum value from all the instances of that metric found.
    - `value`: Used when only one instance of that metric will exist in the logs, do no postprocessing on it.
- The output section will be used when creating a `results.csv` file, where the mapping here will determine how the string that is mapped to by the metric defined will be used as a header in that file

### <ins>Environment</ins>
```
env:
    POPLAR_ENGINE_OPTIONS: '{"target.hostSyncTimeout":"3000"}'
    PYTORCH_EXE_DIR: "/tmp/pytorch_cache/"
```
Any additional environment variables required only for this benchmark should be provided here as strings.

### <ins>Description</ins>
```
description: |
    Dino training with real data. For runs bigger than the 16 IPU benchmark
```

## Adding parameters
To generalise the command and let YAML evaluate it properly, some arguments/values can be configured to use environment variables or be parameterised to avoid repetition.

In the case of poprun variables that are unique to host/VIPU setups, these should be provided via environment variables, like so:
```
poprun
    -vv
    --host $HOSTS
    --vipu-server-host $VIPU_CLI_API_HOST
    --vipu-partition $PARTITION
    --mpi-global-args="
        --tag-output
        --allow-run-as-root
        --mca oob_tcp_if_include $TCP_IF_INCLUDE
        --mca btl_tcp_if_include $TCP_IF_INCLUDE"
...
```

For variables that can be the same on all environments, they can be defined in the yaml file itself like so:
```
env:
    POPLAR_ENGINE_OPTIONS: '{"target.hostSyncTimeout":"3000"}'
    PYTORCH_EXE_DIR: "/tmp/pytorch_cache/"
```
The benchmarking script is designed to find the `env` field and add these variables to the set of environment variables used for this benchmark. Therefore, adding the above to your benchmark will result in the set of environment variables being used for this benchmark to be updated with both the variables defined. 

In the case where multiple benchmarks can be made with one/very few arguments being changed (excluding number of IPUs used), these values can be parameterised in 3 different ways:

### <ins>As a sub-field</ins>
```
parameters:
    phase: 128,384
cmd: >-
    python3 train.py
        --config {phase}_config
```
where `{phase}` will be result in the whole command being evaluated twice with each of the values provided in the comma-separated list

### <ins>As a list</ins>
```
parameters:
    - [phase, batch_size]
    - [128, 3]
    - [384, 2]
    - [512, 1]
cmd: >-
    python3 train.py
        --config {phase}_config
        --batch-size {batch_size}
```
In this case, the first list will define the names of the parameters which will be evaluated, and the following lists will define what the values will be. When provided like this, each set of values will be used as is provided, in that exact order, i.e.:
```
python3 train.py
    --config 128_config
    --batch-size 3

python3 train.py
    --config 384_config
    --batch-size 2

python3 train.py
    --config 512_config
    --batch-size 1
```

### <ins>As a dict</ins>
```
parameters:
    - {phase, batch_size}
    - {128, 3}
    - {384, 2}
cmd: >-
    python3 train.py
        --config {phase}_config
        --batch-size {batch_size}
```
In this case, the first dict will define the names of the parameters which will be evaluated, and the following lists will define what the values can be. When provided like this, each possible combination of values will be used. The above setup will result in:
```
python3 train.py
    --config 128_config
    --batch-size 3

python3 train.py
    --config 384_config
    --batch-size 2

python3 train.py
    --config 128_config
    --batch-size 2

python3 train.py
    --config 384_config
    --batch-size 3
```

### <strong>Note: variant naming</strong>
The script will uniquely name each "variant" created by using the values of these parameters when creating the different commands in order to avoid duplication/overwriting. The variant names are created with the following process:
`[benchmark_name]_[first_parameter_name]_[first_parameter_value]_[second_parameter_name]_[second_parameter_value]...`
And so its clear that with long parameter names or values, the variant name (Which shows in the logs, results CSV files, ES and so on) can become problematic. Therefore its preferred to keep the name length/number of parameters lower and instead create more benchmarks where required.

## Multiple benchmarks
### <ins>Adding common options</ins>
Rather than repeating the same fields with the same values in the case where all/multiple benchmarks share them, you can create a commonly used section that can be referenced in benchmarks. For example:
```
common_options: &common_options
  env:
    POPLAR_ENGINE_OPTIONS: '{"opt.enableMultiAccessCopies":"false"}'
    PYTORCH_CACHE_DIR: "./pt_cache/"
...
```
Which can be used in benchmarks like so:
```
pytorch_resnet_training_16_ipu_perf:
  <<: *common_options
...
```
Just note the anchor (&) used for `common_options` which allows it to be referenced later.

And multiple such sections can be used like so:
```
pytorch_resnet_training_64_ipu_conv:
  <<: [*common_options, *multihost_options]
...
```

## Formatting and standardisation
### <ins>New lines and 2 space tabs</ins>
Each argument/value should ideally be on its own line for clarity and ease of modification/adaptation into shell scripts. In addition, arguments/values should be indented to clearly see which program/argument they are for. For example:
```
poprun
    -vv
    --num-instances=16
    --num-replicas=64
    --ipus-per-replica=1
    --vipu-server-host=$VIPU_CLI_API_HOST
    --host=$HOSTS
    --vipu-server-port 8090
    --num-ilds=1
    --vipu-partition=$PARTITION
    --numa-aware=yes
    --update-partition=no
    --remove-partition=no
    --reset-partition=no
    --print-topology=yes
    --executable-cache-path PYTORCH_CACHE_DIR
    --mpi-global-args="
        --tag-output
        --allow-run-as-root
        --mca btl_tcp_if_include eno1"
    --mpi-local-args="
        -x LD_LIBRARY_PATH
        -x OPAL_PREFIX
        -x PATH
        -x CPATH
        -x PYTHONPATH
        -x POPLAR_ENGINE_OPTIONS
        -x IPUOF_VIPU_API_TIMEOUT=800"
python3 train.py
    --config resnet50-pod64
    --dataloader-worker 14
    --dataloader-rebatch-size 256
    --imagenet-data-path $DATASETS_DIR/imagenet-raw-dataset
    --wandb
```
Where we see poprun and python are programs, and their args are indented and mpi-local/global-args are double indented

### <ins>Standardising output names</ins>
To maintain the standard metric names we use in our benchmarking/testing processes, please use the following style for acquiring and passing outputs to ES:
```
data:
    throughput:
        regexp: 'throughput: *(.*?) samples\/sec'
        skip: 1
    accuracy:
        reduction_type: "final"
        regexp: 'accuracy: *(.*?)\%'
    loss:
        reduction_type: "final"
        regexp: 'loss: *(.*?),'
    latency:
        regexp: 'latency: *(.*?) ms'
        skip: 1
output:
    - [throughput, "throughput"]
    - [accuracy, "accuracy"]
    - [loss, "loss"]
    - [latency, "latency"]
```
As mentioned in <strong>Prerequisite</strong> above, data regexes should be adhere to the above format, and the outputs should be simple and lowercase. Other metrics can be used but consult with the applications-performance and test-automation teams first.

### <ins>Benchmark naming</ins>
The standard that should be applied to benchmark names, wherever applicable, should be:
`[framework]_[app]_[sl{sequence length}]_[infer/train/pretrain/finetune/etc.]_[real/synth/gen]_[pod{4/16/64/256/etc.}/1ipu]_[perf/conv]`
with `1ipu` only being acceptable for inference and `pod4` for training only in special cases where replication is not possible.

For example:

`pytorch_dino_training_real_64_ipu_perf`

`tf1_bert_sl128_pretraining_real_16_ipu_conv`

`pytorch_resnet_bs32_inference_1_ipu_perf`

Variant names will differ by adding parameter names/values to the end of this, so please keep this in mind when creating benchmarks. The choice of whether to add distinguishing information like the sequence length etc. to the benchmark name or adding this as a parameter should be made so that the resulting name at the end is simpler and shorter.

## <ins>Testing</ins>
Once the benchmark is ready, it should be tested locally prior to submitting. the `run_benchmarks.py` script provides this functionality, located in both the `ce_benchmarking` and `examples_utils` repos. To test one or more yaml files with benchmarks, simply:
- Install and enable a popsdk version, activate the appropriate venv, and follow the installation/setup guides for the app to benchmark
- `pip install -r requirements.txt` in the benchmarking scripts directory in one of the two repos mentioned above, and `export DATASETS_DIR` environment variable to the parent dir of your dataset.
- `python3 run_benchmarks.py --spec <path_to_yaml_file1> <path_to_yaml_file2>` or alternatively, if you want to test specific benchmarks, add the `--benchmark` argument with the exact name of the specific benchmark you wish to run

The logs from these local runs should then be provided along with other details when creating diffs/PRs for the benchmarks.
