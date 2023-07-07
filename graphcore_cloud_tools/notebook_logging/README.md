# GCLogger

## Installation and usage
Logging of metrics and analytics from within notebooks.

For basic usage, install the `graphcore-cloud-tools` package and then load the extension:
```python
%load_ext graphcore_cloud_tools.notebook_logging.gc_logger
```

This will start up background processes that log and upload system, IPU and notebook usage information.

To stop all logging and uploading, run:
```python
%unload_ext graphcore_cloud_tools.notebook_logging.gc_logger
```
from any cell in the notebook.

## Disclaimer

When you first import and generate a `GCLogger` object, the following disclaimer is displayed in the stdout of the cell in which the `%load_ext %load_ext graphcore_cloud_tools.notebook_logging.gc_logger` was run in the notebook:
```
In order to improve usability and support for future users, Graphcore would like to collect information about the
applications and code being run in this notebook. The following information will be anonymised before being sent to Graphcore:

- User progression through the notebook
- Notebook details: number of cells, code being run and the output of the cells
- Environment details

You can disable logging at any time by running `%unload_ext graphcore_cloud_tools.notebook_logging.gc_logger` from any cell.

```

## Design notes

The following notes describe the design and architecture of the notebook logging module.

### IPython extension format
The module is written as an IPython extension for two reasons:
- It can be loaded/unloaded into/out of the IPython kernel via IPython line magic easily and cleanly.
- It can access the IPython events register so that we can register custom pre- or post-cell execution functions.

This allows us to perform event-based logging, where each cell execution counts as an event. Whilst some of the data we need to store is independent of the cells themselves, the majority of the information is specific and hence suits this logging method very well. 

### Background processes
Some functions need to be run in background processes which do not stall the execution of the pre/post cell execution functions in order to avoid making any delays visible to the user. These are functions that:
- Have a very long run time relative to the other pre/post cell execution methods
- Only need to be run once per instance of notebook/logger (notebook metadata)
- Need to access the notebook itself (JSON), which isn't saved on demand

Instead, the [`multiprocess`](https://docs.python.org/3/library/multiprocessing.html) library is used to create and manage the data structures and background processes. With this we create, run, terminate and cleanup processes that are not exposed to the user and do not (significantly in any way) affect the python kernel itself.

### Multiprocess managed payload
As a consequence of using `multiprocess` to execute and manage the background processes, we also need to use specialised data structures that are managed by `multiprocess` itself to ensure consistency when multiple processes are writing to the same memory at the same time. To this extent, the class creates and maintains its own `multiprocess` manager, as well as a dictionary and list:
```python 
_MP_MANAGER = mp.Manager()
_PAYLOAD = _MP_MANAGER.dict()
_CODE_CELLS = _MP_MANAGER.list()
```

These are then modified by background processes and the class methods as appropriate. 

In the post-cell execution method, a local copy of the `multiprocess` managed payload is created which is a regular Python dictionary. It is then modified and formatted into the final payload which is uploaded. The only methods which modify the `multiprocess` managed payload are the background run methods specified in the [background processes section](#background-processes) above.

### Loading and unloading

The `%load_ext` line magic runs the register function that enables the actual pre- and post-cell execution computation to happen. Upon loading, the `GCLogger` object is instantiated and the events are registered to the IPython events object. Upon unloading with the `%unload_ext` line magic, the object is then deleted so that attributes and methods can no longer be accessed by attempting to access the same instance, and the events are unregistered so that they are no longer run by the kernel when cells are executed.

### AWS firehose
The payloads, once finalised, are uploaded to our database via AWS Firehose. The implementation and details behind this are not described here. 
The setup, however, currently relies on AWS keys that are salted and base64 encoded and available in the `gcl` dataset in Paperspace environments. Once the class is instantiated, it looks for the keys in the dataset, decodes them and then provides them to the `boto3` client. After that, payloads are constructed as described above and provided to the `boto3` client, which also requires a firehose stream (provided as a class attribute) and performs the upload.
